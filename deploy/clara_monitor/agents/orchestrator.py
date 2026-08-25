"""Competitor Intelligence Orchestrator.

Runs the cycle and owns the decisions the specialists must not make for
themselves: when each one is worth calling, how their outputs combine, which
conflicts a person has to settle, and what the new state actually is.

The order is fixed because each step needs the one before it:

    previous state -> discovery -> collection -> offers -> diff
                   -> verification -> intelligence -> actions -> arrangement
                   -> new state

Verification sits deliberately after the diff and before the analysis. Verifying
raw findings would mean checking hundreds of unchanged facts every cycle; putting
it after the analysis would mean the threat assessment had already been written
from unproven claims. Between the two, it checks exactly what is new and lets only
what survives through to interpretation.

The orchestrator never edits an agent's numbers. Where two agents disagree it
records the conflict and lowers confidence, because a coordinator that quietly
picks a winner destroys the only signal that something needs a human.
"""

from __future__ import annotations

import json

from ..config import DB_PATH
from ..money import to_decimal
from . import state as state_mod
from .action import ActionRecommendationAgent
from .arrangement import ContentArrangementAgent
from .collection import CompetitorDataCollectionAgent
from .contracts import (Change, ChangeType, Claim, Confidence, DiscoveryStatus,
                        Evidence, OfferStatus, VerificationStatus,
                        evidence_list, now_iso)
from .discovery import CompetitorDiscoveryAgent
from .identity import identity_key
from .intelligence import CompetitorIntelligenceAgent
from .offers import LiveCompetitorOffersAgent
from .store import IntelStore
from .verification import CompetitorVerificationAgent

# How stale a discovery run may be before the orchestrator reruns it. The prompt
# lists "the previous discovery run is outdated" as a trigger; this is what
# outdated means in cycles rather than in feeling.
DISCOVERY_EVERY_CYCLES = 1


class Orchestrator:
    def __init__(self, store, db_path=DB_PATH, llm=None, verbose: bool = True):
        self.store = store
        self.intel = IntelStore(db_path)
        self.llm = llm
        self.verbose = verbose
        self.agents: dict[str, dict] = {}
        self.pair_conflicts: list[dict] = []

    def close(self) -> None:
        self.intel.close()

    def log(self, msg: str) -> None:
        if self.verbose:
            print(f"  {msg}", flush=True)

    # ----------------------------------------------------------------------

    def run(self, cycle_id: str, run_id: str, clara_products: list,
            live_discovery: bool = False,
            brand_index_urls: list[str] | None = None) -> dict:
        self.intel.start_cycle(cycle_id)
        previous = self.intel.previous_state() or {}
        first_cycle = not previous
        self.log(f"previous state: "
                 f"{'none — this is the first cycle' if first_cycle else str(len(previous.get('competitors') or {})) + ' competitors'}")

        # ---- 1. discovery ----
        discovery = CompetitorDiscoveryAgent(llm=self.llm)
        candidates = discovery.run(self.store, self.intel, clara_products,
                                   live=live_discovery,
                                   brand_index_urls=brand_index_urls)
        self._record(discovery)
        for c in candidates:
            self.intel.put_candidate(cycle_id, c)
        new_names = [c.competitor_name for c in candidates
                     if c.status == DiscoveryStatus.NEW]
        self.log(f"discovery: {len(candidates)} candidates, {len(new_names)} new")

        # ---- 2. collection ----
        # Collect for everything tracked, plus anything discovery calls new. The
        # prompt's triggers all reduce to "the record may not reflect reality".
        keys = [c["key"] for c in self.store.get_competitors()]
        collection = CompetitorDataCollectionAgent(llm=self.llm)
        profiles = collection.run(self.store, keys, clara_products)
        self._record(collection)
        self.log(f"collection: {len(profiles)} profiles")

        # ---- 3. live offers ----
        offers_agent = LiveCompetitorOffersAgent(llm=self.llm)
        offers = offers_agent.run(self.store, self.intel, run_id, cycle_id,
                                  brand_names=self._brand_names())
        self._record(offers_agent)
        live_now = [o for o in offers if o.is_live()]
        self.log(f"offers: {len(live_now)} live of {len(offers)} tracked")

        # ---- 4. new state, and the diff against the previous one ----
        current = self._compose(profiles, candidates, cycle_id, previous)
        changes = state_mod.diff_competitors(previous.get("competitors") or {},
                                             current)
        changes += state_mod.diff_offers(self.intel.offers(), offers)
        working = {"competitors": current}
        working, expired_changes = state_mod.expire(working, cycle_id)
        changes += expired_changes
        current = working["competitors"]
        self.log(f"changes: {len(changes)} — "
                 + ", ".join(f"{k} {v}" for k, v in
                             state_mod.summarise(changes).items()) or "none")

        # ---- 5. verification ----
        claims = self._claims_from(changes, offers)
        verification = CompetitorVerificationAgent(llm=self.llm)
        verified = verification.run(claims, known_entities=self._known_facts(previous))
        self._record(verification)
        verdicts = {c.claim: c for c in verified}
        change_verdicts = {}
        for ch in changes:
            key = self._claim_text(ch)
            v = verdicts.get(key)
            if v:
                change_verdicts[f"{ch.change_type}|{ch.entity}|{ch.field_name}"] = \
                    v.verification_status
                ch.confidence = Confidence.weakest(ch.confidence, v.confidence)
        for c in verified:
            self.intel.add_claim(cycle_id, c)
        for ch in changes:
            self.intel.add_change(cycle_id, ch)

        # ---- 6. intelligence ----
        price_ctx = self._price_context(clara_products)
        intelligence = CompetitorIntelligenceAgent(llm=self.llm)
        analysable = changes
        if first_cycle:
            # Everything is "new" against an empty previous state. Reporting 26
            # new competitors as market movement would be true and useless, and
            # it would generate a task to assign companies already assigned.
            analysable = [c for c in changes
                          if c.change_type != ChangeType.NEW_COMPETITOR]
            self.log(f"first cycle: {len(changes) - len(analysable)} "
                     f"NEW_COMPETITOR entries recorded as the baseline, not "
                     f"analysed as movement")
        findings = intelligence.run(analysable, change_verdicts, price_ctx)
        findings += self._standing_findings(offers, findings, price_ctx)
        self._record(intelligence)
        for f in findings:
            self.intel.add_finding(cycle_id, f)
        self.log(f"intelligence: {len(findings)} findings")

        # ---- 7. actions ----
        action_agent = ActionRecommendationAgent(llm=self.llm)
        actions = action_agent.run(findings, price_ctx)
        self._record(action_agent)
        for a in actions:
            self.intel.add_action(cycle_id, a)
        self.log(f"actions: {len(actions)}")

        # ---- 8. arrangement ----
        arrangement = ContentArrangementAgent(llm=self.llm)
        layout = arrangement.run(profiles, offers, findings, actions, candidates,
                                 price_ctx)
        self._record(arrangement)

        # ---- 9. persist the new state ----
        for key, rec in current.items():
            self.intel.put_competitor(rec, cycle_id)
        for o in offers:
            self.intel.put_offer(o.to_dict(), cycle_id)

        output = self._output(cycle_id, previous, current, changes, findings,
                              actions, offers, candidates, layout, first_cycle)
        self.intel.save_snapshot(cycle_id, {"competitors": current,
                                            "offers": {o.offer_key: o.to_dict()
                                                       for o in offers}},
                                 output["summary"])
        self.intel.finish_cycle(cycle_id, self.agents)
        return output

    # ----------------------------------------------------------------------
    # helpers
    # ----------------------------------------------------------------------

    def _brand_names(self) -> dict:
        """Registry key -> the one display name this report uses for it."""
        return {c["key"]: (c.get("brand") or c["key"])
                for c in self.store.get_competitors()}

    def _standing_findings(self, offers, existing, price_ctx) -> list:
        """One finding per live offer that no change-driven finding covers.

        A promotion running for the third cycle in a row is not news, but it is
        still a live competitive condition, and the task it implies is still
        outstanding. Marking these `standing` keeps them out of the "what changed"
        reading of the page while keeping them in the "what to do" one.
        """
        from .contracts import ChangeType, Finding, ThreatLevel

        covered = {f.entity for f in existing}
        out = []
        for o in offers:
            if not o.is_live() or o.competitor in covered:
                continue
            pair = (price_ctx.get("pairs") or {}).get(o.competitor) or {}
            f = Finding(
                title=f"{o.competitor}: promotion still running",
                entity=o.competitor,
                change_type=ChangeType.NEW_OFFER,
                competitive_impact=(
                    f"{o.competitor} is still running \"{o.offer_title}\" at "
                    f"{o.current_price} {o.currency}. This has not changed since "
                    f"the last cycle, so it is a standing condition rather than "
                    f"news."),
                threat_level=ThreatLevel.LOW,
                opportunity="",
                strategic_significance=(
                    "Worth acting on for as long as it runs, not once when it "
                    "appeared."),
                versus_previous="Unchanged since the previous cycle.",
                confidence=o.confidence,
                evidence=o.evidence,
                change_keys=[f"STANDING|{o.competitor}|{o.offer_key}"],
            )
            f.standing = True
            out.append(f)
        if out:
            self.log(f"standing: {len(out)} live condition(s) kept on the task list")
        return out

    def _record(self, agent) -> None:
        self.agents[agent.name] = agent.report.to_dict()

    def _compose(self, profiles, candidates, cycle_id: str,
                 previous: dict) -> dict:
        """The new competitor state: previous, overwritten by what was collected."""
        prev = previous.get("competitors") or {}
        out: dict[str, dict] = {}

        by_name = {c.competitor_name: c for c in candidates}
        for p in profiles:
            company = p.company or {}
            doms = company.get("all_domains") or []
            key = identity_key(p.competitor, doms)
            if not key:
                continue
            cand = by_name.get(p.competitor)
            fresh = {
                "identity_key": key,
                "name": p.competitor,
                "domains": doms,
                "type": (cand.type if cand else "direct"),
                "profile": p.to_dict(),
                "confidence": p.confidence,
                "status": "active",
                "relevance": (cand.type if cand else "direct"),
                "last_seen_at": now_iso(),
                "evidence": [e.to_dict() for e in p.evidence],
            }
            out[key] = state_mod.carry_forward(prev.get(key) or {}, fresh, cycle_id)

        # A discovered company with no profile yet is still part of the state —
        # dropping it would mean rediscovering it as "new" every single cycle.
        for c in candidates:
            if c.status not in (DiscoveryStatus.NEW, DiscoveryStatus.POSSIBLE):
                continue
            if c.identity_key in out:
                continue
            out[c.identity_key] = state_mod.carry_forward(
                prev.get(c.identity_key) or {},
                {"identity_key": c.identity_key, "name": c.competitor_name,
                 "domains": [c.domain] if c.domain else [],
                 "type": c.type, "profile": {}, "confidence": c.confidence,
                 "status": "watchlist", "relevance": c.type,
                 "last_seen_at": c.first_detected_at or now_iso(),
                 "why_competitive": c.why_competitive,
                 "evidence": [e.to_dict() for e in c.evidence]},
                cycle_id)
        return out

    def _claim_text(self, ch: Change) -> str:
        return (f"{ch.entity}: {ch.change_type} on "
                f"{ch.field_name or 'the record'} "
                f"({ch.previous_value or 'none'} -> {ch.new_value or 'none'})")

    def _claims_from(self, changes: list[Change], offers: list) -> list[Claim]:
        """Only what is new or changed goes to verification.

        Re-verifying the unchanged every cycle would spend the whole budget
        confirming things nobody disputed.
        """
        SUBJECT = {
            ChangeType.PRICE_CHANGED: "pricing",
            ChangeType.NEW_OFFER: "offer",
            ChangeType.OFFER_CHANGED: "offer",
            ChangeType.OFFER_EXPIRED: "offer",
            ChangeType.NEW_COMPETITOR: "identity",
            ChangeType.REMOVED_COMPETITOR: "identity",
            ChangeType.NEW_PRODUCT: "product",
            ChangeType.PRODUCT_CHANGED: "product",
            ChangeType.FEATURE_CHANGED: "feature",
            ChangeType.POSITIONING_CHANGED: "market_claim",
            ChangeType.RELEVANCE_CHANGED: "relevance",
            ChangeType.COMPETITOR_CHANGED: "identity",
        }
        claims = []
        for ch in changes:
            claims.append(Claim(
                claim=self._claim_text(ch), entity=ch.entity,
                subject=SUBJECT.get(ch.change_type, "market_claim"),
                evidence=evidence_list([e.to_dict() if hasattr(e, "to_dict") else e
                                        for e in ch.evidence or []])))
        for o in offers:
            if o.status != OfferStatus.ACTIVE:
                continue
            claims.append(Claim(
                claim=f"{o.competitor}: '{o.offer_title}' is running right now",
                entity=o.competitor, subject="offer", evidence=o.evidence))
        return claims

    def _known_facts(self, previous: dict) -> dict:
        out = {}
        for rec in (previous.get("competitors") or {}).values():
            name = (rec.get("name") or "").lower()
            prof = rec.get("profile") or {}
            out[name] = {"facts": {
                "domain": (prof.get("company") or {}).get("domain"),
            }, "asserted": {}}
        return out

    def _price_context(self, clara_products: list) -> dict:
        """Each competitor's closest Clara pairing, for the gap arithmetic.

        Built from stored matches, so a gap is only ever computed for a pairing
        the matcher actually holds — never between two products that merely share
        a category.

        Both sides are re-classified before the pair is used. A stored match can
        be wrong, and this layer has no business computing a price gap between a
        conditioner and a styling device just because a `confirmed_match` row says
        they are the same product. Mismatched pairs are skipped and reported as
        data-quality warnings rather than dropped in silence.
        """
        from .. import catalog as cat
        clara_by_id = {p.product_id: p for p in clara_products}
        names = self._brand_names()
        pairs: dict[str, dict] = {}
        rows = self.store.db.execute(
            "SELECT * FROM match WHERE COALESCE(rejected,'[]') IN ('[]','','null') "
            "AND status IN ('confirmed_match','probable_match')").fetchall()
        for r in rows:
            m = dict(r)
            clara = clara_by_id.get(m.get("clara_product_id"))
            if not clara:
                continue
            obs = self.store.get_observation(m["clara_product_id"],
                                             m["competitor_key"]) or {}
            payload = obs.get("payload") if isinstance(obs.get("payload"), dict) else {}
            if isinstance(obs.get("payload"), str):
                try:
                    payload = json.loads(obs["payload"])
                except (ValueError, TypeError):
                    payload = {}
            # Key on the registry name, the same one findings carry.
            # Keying on the match row's own spelling silently orphaned
            # every pairing whose page wrote the brand differently.
            rival_name = m.get("competitor_product_name") or ""
            rival_segment = cat.classify_category(rival_name)[0] if rival_name else ""
            if (rival_segment and clara.segment not in ("unknown", "")
                    and rival_segment != "unknown"
                    and rival_segment != clara.segment):
                self.pair_conflicts.append({
                    "clara_product": clara.name,
                    "clara_segment": clara.segment,
                    "competitor": m.get("competitor_brand") or m.get("competitor_key"),
                    "competitor_product": rival_name,
                    "competitor_segment": rival_segment,
                    "stored_status": m.get("status"),
                    "stored_score": m.get("match_score"),
                    "why_it_matters": ("a stored match pairs two different kinds of "
                                       "product; no price gap was computed from it, "
                                       "and the pairing should be re-decided"),
                    "url": m.get("competitor_url"),
                })
                continue

            brand = (names.get(m.get("competitor_key"))
                     or m.get("competitor_brand") or m.get("competitor_key"))
            existing = pairs.get(brand)
            entry = {
                "clara_name": clara.name,
                "clara_price": getattr(clara, "price", None),
                "clara_currency": getattr(clara, "currency", "SAR"),
                "competitor_price": payload.get("selling_price"),
                "competitor_currency": payload.get("currency"),
                "competitor_url": m.get("competitor_url"),
                "match_status": m.get("status"),
                "match_score": m.get("match_score"),
            }
            # Prefer a confirmed pairing with a readable price over anything else.
            def rank(e):
                return (0 if e.get("match_status") == "confirmed_match" else 1,
                        0 if e.get("competitor_price") is not None else 1,
                        -float(e.get("match_score") or 0))
            if not existing or rank(entry) < rank(existing):
                pairs[brand] = entry
        return {"pairs": pairs}

    # ----------------------------------------------------------------------
    # output
    # ----------------------------------------------------------------------

    def _output(self, cycle_id, previous, current, changes, findings, actions,
                offers, candidates, layout, first_cycle) -> dict:
        prev_comp = previous.get("competitors") or {}
        new_keys = [k for k in current if k not in prev_comp]
        gone_keys = [k for k in prev_comp if k not in current]
        changed_keys = sorted({
            c.entity for c in changes
            if c.change_type in (ChangeType.COMPETITOR_CHANGED,
                                 ChangeType.POSITIONING_CHANGED,
                                 ChangeType.RELEVANCE_CHANGED,
                                 ChangeType.PRODUCT_CHANGED,
                                 ChangeType.PRICE_CHANGED,
                                 ChangeType.FEATURE_CHANGED)})

        sources, seen = [], set()
        for c in changes:
            for e in c.evidence or []:
                d = e.to_dict() if hasattr(e, "to_dict") else e
                if d.get("url") and d["url"] not in seen:
                    seen.add(d["url"])
                    sources.append(d)

        important = sorted(
            [c.to_dict() for c in changes
             if Confidence.rank(c.confidence) >= Confidence.rank(Confidence.MEDIUM)],
            key=lambda d: ChangeType.WEIGHT.get(d["change_type"], 99))

        summary = {
            "cycle_id": cycle_id,
            "first_cycle": first_cycle,
            "competitors_tracked": len(current),
            "new": len(new_keys),
            "removed": len(gone_keys),
            "changed": len(changed_keys),
            "changes_by_type": state_mod.summarise(changes),
            "offers_live": sum(1 for o in offers if o.is_live()),
            "offers_expired": sum(1 for o in offers
                                  if o.status == OfferStatus.EXPIRED),
            "offers_unknown": sum(1 for o in offers
                                  if o.status == OfferStatus.UNKNOWN),
            "findings": len(findings),
            "actions": len(actions),
            "pairings_refused": len(self.pair_conflicts),
            "decision_sources": {name: rep["decision_source"]
                                 for name, rep in self.agents.items()},
        }

        return {
            "updated_at": now_iso(),
            "cycle_id": cycle_id,
            "new_competitors": [current[k] for k in new_keys],
            "changed_competitors": changed_keys,
            "removed_competitors": [prev_comp[k].get("name") or k
                                    for k in gone_keys],
            "product_competitors": layout["product_competitors"],
            "competitors": layout["competitors"],
            "live_competitor_offers": layout["live_competitor_offers"],
            "actions_needed": layout["actions_needed"],
            "important_changes": important,
            "sources": sources,
            "watchlist": layout["watchlist"],
            "offer_history": layout["offer_history"],
            "findings": [f.to_dict() for f in findings],
            "section_order": layout["section_order"],
            "section_notes": layout["section_notes"],
            "agents": self.agents,
            "data_quality_warnings": self.pair_conflicts,
            "summary": summary,
        }
