"""The Agent run loop (§4).

Order is fixed and discovery is unreachable except through a failed validity
test:

    load catalog -> select Clara product -> load assigned competitors
    -> stored match? -> validate identity + refresh known URL FIRST
    -> else discover candidates -> evaluate -> classify
    -> collect price/discount/stock/variants/images -> validate + normalize
    -> store match + observation + append-only history + match_event
    -> next competitor -> next product -> reports

Every decision records its source: `deterministic_rules` or `vertex_gemini`
(§9A "decision source"). A model that is unavailable degrades to rules and says
so on the match rather than stalling the run.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from . import competitors as comp
from .access import guarded_get, host_allowed, reset_pauses
from .config import DB_PATH, RunConfig
# `candidates`, not `discovery`. A `discovery/` package for trend-source
# discovery was added later and shadowed the `discovery.py` module this
# imports from — a package always wins — so `DiscoveryChain` became
# unreachable and every monitoring run died on this line. The module is
# renamed for what it does: conditional candidate discovery (§8).
from .candidates import DiscoveryChain
from .extract import (
    ACCEPTED, ACCEPTED_WITH_WARNINGS, REJECTED, browser_required, extract,
)
from .llm import DECISION_SOURCE_MODEL, DECISION_SOURCE_RULES, RULES_VERSION, judge_singleton
from .matching import (
    DRIFT_TOLERANCE, FORMAT_EQUIVALENCE, fingerprint, fingerprint_drift,
)
from .models import (
    AMBIGUOUS, ATTACHMENT_OF_SYSTEM, BLOCKED, CONFIRMED, NO_MATCH, PROBABLE,
    STANDALONE, ClaraProduct, Exception_, Match,
)
from .money import fmt as money_fmt, pct_change, to_decimal
from .store import Store, utcnow

INVALIDATED = "invalidated"       # §9A fifth status

# §20 "Timeouts ... configurable". A single pair must not be able to consume the
# run: once this budget is spent, the pair stops reading further candidates and
# records why, instead of blocking every product behind it.
PAIR_TIME_BUDGET_S = 75.0


# --------------------------------------------------------------------------
# scoring (deterministic path)
# --------------------------------------------------------------------------

SPEC_KEYS = ("power_w", "heat_settings", "ionic", "attachment_count", "voltage")


def _spec_agreement(a: dict, b: dict) -> tuple[float, list[str], list[str]]:
    """(score, evidence, differences) over specs BOTH sides publish.

    The third value is *attribute differences*, not identity conflicts. A rival
    dryer that is 1400 W where Clara is 2000 W is still the rival dryer; that is
    information for the report, not grounds to escalate. Only §9A "material
    conflicting evidence" about identity blocks a decision, and that is tracked
    separately in `identity_conflicts`.
    """
    ev: list[str] = []
    conflicts: list[str] = []
    agree, compared = 0.0, 0
    for k in SPEC_KEYS:
        av, bv = a.get(k), b.get(k)
        if av is None or bv is None:
            continue
        compared += 1
        if isinstance(av, bool) or isinstance(bv, bool):
            if bool(av) == bool(bv):
                agree += 1
                ev.append(f"{k}: both {av}")
            else:
                conflicts.append(f"{k}: Clara {av} vs competitor {bv}")
            continue
        if isinstance(av, (int, float)) and isinstance(bv, (int, float)):
            hi = max(abs(av), abs(bv)) or 1
            ratio = max(0.0, 1.0 - abs(av - bv) / hi)
            agree += ratio
            (ev if ratio > 0.8 else conflicts).append(
                f"{k}: Clara {av} vs competitor {bv}")
            continue
        if str(av).lower() == str(bv).lower():
            agree += 1
            ev.append(f"{k}: both {av}")
        else:
            conflicts.append(f"{k}: Clara {av} vs competitor {bv}")
    if compared == 0:
        return 0.5, ["no specification published by both sides; spec score neutral"], []
    return agree / compared, ev, conflicts


@dataclass
class Candidate2:
    url: str
    brand: str
    product_name: str
    host: str
    source_tier: str
    fmt: str
    extraction: object
    score: float = 0.0
    breakdown: dict = field(default_factory=dict)
    basis: str = STANDALONE
    disqualified: bool = False
    disqualified_reason: str | None = None
    evidence: list[str] = field(default_factory=list)
    spec_differences: list[str] = field(default_factory=list)
    identity_conflicts: list[str] = field(default_factory=list)
    decision_source: str = DECISION_SOURCE_RULES
    model_verdict: dict | None = None

    def as_dict(self) -> dict:
        return {
            "url": self.url, "brand": self.brand,
            "product_name": self.product_name, "host": self.host,
            "source_tier": self.source_tier, "fmt": self.fmt,
            "score": round(self.score, 3), "breakdown": self.breakdown,
            "comparison_basis": self.basis,
            "disqualified": self.disqualified,
            "disqualified_reason": self.disqualified_reason,
            "evidence": self.evidence[:8],
            "spec_differences": self.spec_differences[:8],
            "identity_conflicts": self.identity_conflicts[:8],
            "decision_source": self.decision_source,
            "model_verdict": self.model_verdict,
        }


def score_candidate(product: ClaraProduct, cand: Candidate2,
                    judge=None) -> Candidate2:
    """Deterministic format gate, then optional model judgement on identity.

    §9A: price is never evidence of identity, and format mismatch disqualifies.
    The model can lower confidence or flag conflicts but cannot promote a pair
    past the format gate — that keeps storage integrity off free-form judgement
    (§6).
    """
    key = (product.fmt, cand.fmt)
    if key not in FORMAT_EQUIVALENCE:
        cand.disqualified = True
        cand.disqualified_reason = (
            f"format mismatch: Clara is {product.fmt}, candidate is {cand.fmt}")
        cand.evidence.append(cand.disqualified_reason)
        return cand

    fmt_score, basis = FORMAT_EQUIVALENCE[key]
    cand.basis = basis
    spec_score, spec_ev, spec_diff = _spec_agreement(
        product.specs, getattr(cand.extraction, "specs", {}) or {})

    brand_signal = 1.0 if cand.brand else 0.4
    identity_signal = 0.0
    ex = cand.extraction
    if getattr(ex, "sku", None) or getattr(ex, "source_product_id", None):
        identity_signal = 1.0
        cand.evidence.append(
            f"competitor publishes a stable identifier "
            f"(sku/productID: {ex.sku or ex.source_product_id})")
    tier_signal = {"brand_official": 1.0, "authorized_retailer": 0.8,
                   "marketplace_third_party": 0.55}.get(cand.source_tier, 0.4)

    cand.breakdown = {
        "format": round(fmt_score, 3),
        "specs": round(spec_score, 3),
        "brand": round(brand_signal, 3),
        "identifier": round(identity_signal, 3),
        "source_tier": round(tier_signal, 3),
    }
    # No price term: §9A forbids price as identity evidence.
    cand.score = round(
        0.40 * fmt_score + 0.25 * spec_score + 0.12 * brand_signal
        + 0.13 * identity_signal + 0.10 * tier_signal, 3)
    cand.evidence.append(f"format basis {basis} ({product.fmt} vs {cand.fmt})")
    cand.evidence.extend(spec_ev)
    cand.spec_differences.extend(spec_diff)
    cand.evidence.append(
        "score " + str(cand.score) + " = "
        + ", ".join(f"{k} {v}" for k, v in cand.breakdown.items())
        + " (price excluded by policy)")

    if judge is not None and getattr(judge, "available", False):
        v = judge.judge(
            {"name": product.name, "format": product.fmt,
             "category": product.category, "specs": product.specs,
             "brand": "Clara"},
            {"name": cand.product_name, "format": cand.fmt,
             "brand": cand.brand,
             "specs": getattr(ex, "specs", {}) or {},
             "sku": getattr(ex, "sku", None),
             "category_path": getattr(ex, "category_path", [])},
        )
        if v is not None:
            cand.decision_source = DECISION_SOURCE_MODEL
            cand.model_verdict = v.as_dict()
            cand.evidence.extend(f"model: {e}" for e in v.identity_evidence[:4])
            # A model conflict IS about identity: that is what it was asked to judge.
            cand.identity_conflicts.extend(f"model: {c}" for c in v.conflicts[:4])
            if v.comparison_basis == ATTACHMENT_OF_SYSTEM:
                cand.basis = ATTACHMENT_OF_SYSTEM
            # Blend: the model moderates the rules score, never overrides the gate.
            blended = 0.6 * cand.score + 0.4 * float(v.confidence)
            if not v.same_product:
                blended = min(blended, 0.55)
                cand.identity_conflicts.append(
                    "model judged these are not the same product")
                cand.evidence.append(
                    "model judged these are not the same product; score capped "
                    "below the probable threshold")
            cand.breakdown["model_confidence"] = round(float(v.confidence), 3)
            cand.score = round(blended, 3)
    return cand


# --------------------------------------------------------------------------
# classification (§9A)
# --------------------------------------------------------------------------

@dataclass
class Decision:
    status: str
    score: float
    winner: Candidate2 | None
    rejected: list[Candidate2]
    evidence: list[str]
    conflicts: list[str] = field(default_factory=list)
    decision_source: str = DECISION_SOURCE_RULES


SAME_FAMILY_DRIFT = 0.34   # below this, two candidates are one product's variants


def _fold_variant_families(live: list[Candidate2]) -> tuple[list[Candidate2], list[str]]:
    """Collapse candidates that are the same product in different variants.

    Two colourways of one Airwrap are not "two plausible candidates" under §9A —
    they are variants of a single product, and §11 says variants belong on the
    record rather than being treated as rivals. Folding them here stops the
    ambiguity test from escalating what is really one product.
    """
    kept: list[Candidate2] = []
    notes: list[str] = []
    for c in live:
        fp = fingerprint(c.brand, c.product_name)
        merged_into = None
        for k in kept:
            if fingerprint_drift(fingerprint(k.brand, k.product_name), fp) <= SAME_FAMILY_DRIFT:
                merged_into = k
                break
        if merged_into is None:
            kept.append(c)
            continue
        merged_into.evidence.append(
            f"same product family as this candidate, folded as a variant: "
            f"{c.product_name!r} ({c.url})")
        notes.append(f"folded variant {c.product_name!r} into "
                     f"{merged_into.product_name!r}")
    return kept, notes


def classify(product: ClaraProduct, cands: list[Candidate2],
             cfg: RunConfig) -> Decision:
    live = [c for c in cands if not c.disqualified]
    rejected = [c for c in cands if c.disqualified]
    ev: list[str] = []

    if not live:
        ev.append(f"{len(cands)} candidate(s) read; none passed the format test"
                  if cands else "discovery returned no readable candidate pages")
        return Decision(NO_MATCH, 0.0, None, rejected, ev)

    live.sort(key=lambda c: c.score, reverse=True)
    live, fold_notes = _fold_variant_families(live)
    ev.extend(fold_notes)

    best = live[0]
    runner = live[1] if len(live) > 1 else None
    src = best.decision_source
    conflicts = best.identity_conflicts

    if runner and (best.score - runner.score) < cfg.ambiguity_margin:
        ev.append(
            f"two distinct candidates cannot be separated: {best.product_name!r} "
            f"({best.score}) vs {runner.product_name!r} ({runner.score}); margin "
            f"{round(best.score - runner.score, 3)} < {cfg.ambiguity_margin}")
        return Decision(AMBIGUOUS, best.score, best, live[1:] + rejected, ev,
                        conflicts, src)

    # §9A "material conflicting evidence" means conflicting evidence about
    # IDENTITY. A specification difference is not a conflict — it is the finding.
    if conflicts and best.score < cfg.confirm_threshold:
        ev.append("material conflicting evidence about identity, and the score is "
                  "below the confirm threshold: " + "; ".join(conflicts[:3]))
        return Decision(AMBIGUOUS, best.score, best, live[1:] + rejected, ev,
                        conflicts, src)

    if (best.source_tier == "marketplace_third_party"
            and best.score < cfg.probable_threshold):
        ev.append("only third-party marketplace evidence is available and the "
                  "score does not reach the probable threshold")
        return Decision(AMBIGUOUS, best.score, best, live[1:] + rejected, ev,
                        conflicts, src)

    if best.spec_differences:
        ev.append("specification differences recorded (not identity conflicts): "
                  + "; ".join(best.spec_differences[:4]))

    if best.score >= cfg.confirm_threshold:
        if best.basis == ATTACHMENT_OF_SYSTEM:
            ev.append(
                f"score {best.score} meets the confirm threshold, but "
                f"comparison_basis is attachment_of_system: the competitor item is "
                f"part of a larger system and is not sold separately, so formats do "
                f"not fully agree; capped at probable_match")
            return Decision(PROBABLE, best.score, best, live[1:] + rejected, ev,
                            conflicts, src)
        ev.append(f"score {best.score} >= confirm threshold {cfg.confirm_threshold}")
        return Decision(CONFIRMED, best.score, best, live[1:] + rejected, ev,
                        conflicts, src)

    if best.score >= cfg.probable_threshold:
        ev.append(f"score {best.score} between {cfg.probable_threshold} and "
                  f"{cfg.confirm_threshold}; identity evidence is incomplete")
        return Decision(PROBABLE, best.score, best, live[1:] + rejected, ev,
                        conflicts, src)

    ev.append(f"best score {best.score} is below the probable threshold "
              f"{cfg.probable_threshold}")
    return Decision(NO_MATCH, best.score, None, live + rejected, ev,
                    conflicts, src)


# --------------------------------------------------------------------------
# observation record (§10)
# --------------------------------------------------------------------------

def build_observation(run_id: str, product: ClaraProduct, competitor_key: str,
                      brand: str, ex, tier: str, cfg: RunConfig,
                      basis: str) -> dict:
    """The full §10 field set, as a JSON-safe dict (prices as Decimal strings)."""
    d = ex.as_dict()
    d.update({
        "run_id": run_id,
        "clara_product_id": product.product_id,
        "competitor_key": competitor_key,
        "competitor_brand": brand or ex.brand,
        "source_type": tier,
        "comparison_basis": basis,
        "scraped_at": utcnow(),
        "observed_at": utcnow(),
        "market": cfg.market,
        "is_stale": False,
    })
    if basis == ATTACHMENT_OF_SYSTEM:
        d["notes"] = d.get("warnings", []) + [
            "comparison_basis is attachment_of_system: this price is for the whole "
            "system and the matched attachment is not sold separately"]
    return d


TRACKED_FIELDS = (
    ("selling_price", "price"),
    ("discount_percent", "discount"),
    ("availability", "stock"),
    ("promotion_text", "promotion"),
    ("variant_count", "variant"),
    ("image_count", "image"),
    ("canonical_url", "url"),
)


def detect_changes(prev: dict | None, cur: dict, cfg: RunConfig,
                   prev_status: str | None, new_status: str) -> list[dict]:
    """§12 change types, with previous and new values, using Decimal maths."""
    now = utcnow()
    out: list[dict] = []

    def add(ctype, a, b, delta=None, flagged=False):
        out.append({"change_type": ctype, "previous_value": a, "new_value": b,
                    "delta_pct": str(delta) if delta is not None else None,
                    "flagged": flagged, "detected_at": now})

    if prev_status and prev_status != new_status:
        add("status_changed", prev_status, new_status, flagged=True)

    if prev is None:
        add("no_change", None, "first observation for this pair")
        return out

    changed = False
    for fname, label in TRACKED_FIELDS:
        a, b = prev.get(fname), cur.get(fname)
        if a == b:
            continue
        changed = True
        if label == "price":
            da, db = to_decimal(a), to_decimal(b)
            if da is not None and db is not None:
                delta = pct_change(da, db)
                ctype = "price_increase" if db > da else "price_decrease"
                flagged = delta is not None and abs(delta) >= Decimal(
                    str(cfg.price_change_flag_pct))
                add(ctype, a, b, delta, flagged)
                if delta is not None and abs(delta) >= Decimal(
                        str(cfg.price_sanity_pct)):
                    add("price_beyond_sanity_bound", a, b, delta, True)
            else:
                add("price_availability_changed", a, b, None, True)
        elif label == "discount":
            was = to_decimal(a) is not None and (to_decimal(a) or 0) > 0
            now_d = to_decimal(b) is not None and (to_decimal(b) or 0) > 0
            add("discount_started" if (not was and now_d)
                else "discount_ended" if (was and not now_d)
                else "discount_changed", a, b, None, True)
        elif label == "stock":
            add("stock_in" if b == "in_stock" else
                "stock_out" if b == "out_of_stock" else
                "stock_status_changed", a, b, None, True)
        elif label == "promotion":
            add("promotion_started" if not a else
                "promotion_ended" if not b else
                "promotion_changed", a, b, None, True)
        elif label == "variant":
            add("variant_added" if (b or 0) > (a or 0) else "variant_removed",
                a, b, None, False)
        elif label == "image":
            add("image_changed", a, b, None, False)
        elif label == "url":
            add("url_changed", a, b, None, True)

    if not changed and not out:
        add("no_change", None, None)
    return out


# --------------------------------------------------------------------------
# one pair
# --------------------------------------------------------------------------

@dataclass
class PairOutcome:
    clara_product_id: str
    clara_name: str
    competitor_key: str
    status: str
    path: str
    score: float = 0.0
    discovery_used: bool = False
    decision_source: str = DECISION_SOURCE_RULES
    method: str | None = None
    verdict: str | None = None
    changes: list[dict] = field(default_factory=list)
    exception: Exception_ | None = None
    discovery_log: dict | None = None
    log: list[str] = field(default_factory=list)


def _tier(url: str, keys: list[str]) -> str:
    host = url.split("/")[2].lower() if "//" in url else ""
    return comp.tier_for_host(host, keys)


def process_pair(store: Store, run_id: str, product: ClaraProduct,
                 competitor_key: str, cfg: RunConfig, chain: DiscoveryChain,
                 judge, hosts: set[str]) -> PairOutcome:
    c = comp.get(competitor_key)
    brand = c.brand if c else competitor_key
    out = PairOutcome(product.product_id, product.name, competitor_key,
                      NO_MATCH, "none")
    prev_obs = store.get_observation(product.product_id, competitor_key)
    stored = store.get_match(product.product_id, competitor_key)
    prev_status = stored.status if stored else None
    trigger = "no stored match"

    # ---- STEP: stored match first ----
    if stored:
        valid, why = store.match_is_valid(stored, cfg.ttl_days, hosts)
        out.log.append(f"stored match {stored.status}: {why}")
        if valid:
            res = guarded_get(stored.competitor_url or "", hosts)

            if res.blocked:
                out.status, out.path = BLOCKED, "refresh_blocked"
                store.add_error(run_id, product.product_id, competitor_key,
                                "refresh", "http", res.block_signal or "blocked",
                                "; ".join(res.evidence))
                out.exception = Exception_(
                    run_id=run_id, clara_product_id=product.product_id,
                    competitor_key=competitor_key, kind="blocked",
                    attempted=f"refresh the stored match at {stored.competitor_url}",
                    observed=f"access blocked: {res.block_signal}",
                    why_unresolved=("The site refused or challenged the request. "
                                    "Bypassing a login, CAPTCHA, rate limit or access "
                                    "control is not permitted."),
                    recommended_action=("Open the URL manually and confirm the price and "
                                        "stock, or arrange permitted access (an "
                                        "official feed, an API, or a retailer "
                                        "agreement)."),
                    blocks_downstream=(f"No current observation for {product.name} x "
                                       f"{brand}; the stored match is kept, not "
                                       f"invalidated."),
                    evidence=res.evidence)
                if prev_obs:
                    stale = dict(prev_obs)
                    stale["is_stale"] = True
                    stale.setdefault("notes", [])
                    stale["notes"] = list(stale["notes"]) + [
                        f"not refreshed in run {run_id}: {res.block_signal}"]
                    store.put_observation(run_id, _as_obs(stale))
                store.add_match_event(run_id, product.product_id, competitor_key,
                                      "refresh_blocked", prev_status, prev_status,
                                      f"blocked: {res.block_signal}", res.evidence)
                return out

            if res.status in (404, 410):
                trigger = f"stored URL returns HTTP {res.status}"
                store.invalidate_match(stored, trigger)
                store.add_match_event(run_id, product.product_id, competitor_key,
                                      INVALIDATED, prev_status, INVALIDATED,
                                      trigger, res.evidence)
                out.log.append(f"invalidated: {trigger}")
            elif not res.ok or not res.html:
                trigger = f"stored URL unreadable (HTTP {res.status})"
                store.add_error(run_id, product.product_id, competitor_key,
                                "refresh", "http", f"http_{res.status}",
                                "; ".join(res.evidence))
                store.invalidate_match(stored, trigger)
                store.add_match_event(run_id, product.product_id, competitor_key,
                                      INVALIDATED, prev_status, INVALIDATED,
                                      trigger, res.evidence)
            else:
                ex = extract(res.final_url or stored.competitor_url, res.html,
                             cfg.currency, lambda u: host_allowed(u, hosts))
                current_fp = fingerprint(ex.brand or brand, ex.product_name or "")
                drift = fingerprint_drift(stored.fingerprint, current_fp)

                if drift > DRIFT_TOLERANCE:
                    trigger = (f"identity fingerprint drifted {round(drift, 2)} > "
                               f"{DRIFT_TOLERANCE}: stored "
                               f"{stored.competitor_product_name!r}, page now "
                               f"{ex.product_name!r}")
                    store.invalidate_match(stored, trigger)
                    store.add_match_event(run_id, product.product_id, competitor_key,
                                          INVALIDATED, prev_status, INVALIDATED,
                                          trigger, res.evidence)
                    out.log.append(f"invalidated: {trigger}")
                elif ex.verdict == REJECTED:
                    trigger = f"refreshed page failed validation: {'; '.join(ex.errors)}"
                    store.add_error(run_id, product.product_id, competitor_key,
                                    "refresh", ex.method, "validation_rejected",
                                    trigger)
                    store.invalidate_match(stored, trigger)
                    store.add_match_event(run_id, product.product_id, competitor_key,
                                          INVALIDATED, prev_status, INVALIDATED,
                                          trigger, ex.errors)
                else:
                    # Valid stored match, refreshed. No discovery.
                    out.status, out.path = stored.status, "refreshed"
                    out.score, out.method, out.verdict = (
                        stored.match_score, ex.method, ex.verdict)
                    out.decision_source = "stored_match"
                    tier = _tier(stored.competitor_url or "", [competitor_key])
                    obs = build_observation(run_id, product, competitor_key, brand,
                                            ex, tier, cfg, stored.comparison_basis)
                    stored.validated_at = utcnow()
                    stored.evidence = (stored.evidence + [
                        f"refreshed via {ex.method}; fingerprint drift "
                        f"{round(drift, 2)} within tolerance"])[-14:]
                    store.put_match(stored)
                    store.upsert_competitor_product(competitor_key, ex)
                    out.changes = detect_changes(prev_obs, obs, cfg, prev_status,
                                                 stored.status)
                    store.put_observation(run_id, _as_obs(obs))
                    store.add_match_event(run_id, product.product_id, competitor_key,
                                          "refreshed", prev_status, stored.status,
                                          "stored match revalidated and refreshed "
                                          "without discovery", [ex.method])
                    out.log.append("refreshed without invoking discovery")
                    return out
        else:
            trigger = why

    # ---- STEP: discovery, only now ----
    out.discovery_used = True
    urls, dlog = chain.candidates(product, competitor_key,
                                  cfg.discovery_budget, trigger)
    out.discovery_log = dlog.as_dict()
    out.log.append(f"discovery triggered ({trigger}); {len(urls)} candidate(s)")

    cands: list[Candidate2] = []
    blocks: list[dict] = []
    deadline = time.monotonic() + PAIR_TIME_BUDGET_S
    for u in urls:
        if time.monotonic() > deadline:
            out.log.append(
                f"pair time budget of {PAIR_TIME_BUDGET_S:.0f}s spent; stopped after "
                f"{len(cands)} readable candidate(s) with {len(urls)} proposed")
            store.add_error(run_id, product.product_id, competitor_key,
                            "discovery", "budget", "pair_time_budget_spent",
                            f"stopped before {u}")
            break
        res = guarded_get(u, hosts)
        if res.blocked:
            blocks.append({"url": u, "signal": res.block_signal,
                           "evidence": res.evidence})
            store.add_error(run_id, product.product_id, competitor_key,
                            "discovery", "http", res.block_signal or "blocked",
                            f"{u} :: " + "; ".join(res.evidence))
            continue
        if not res.ok or not res.html:
            store.add_error(run_id, product.product_id, competitor_key,
                            "discovery", "http", f"http_{res.status}", u)
            continue
        ex = extract(res.final_url or u, res.html, cfg.currency,
                     lambda x: host_allowed(x, hosts))
        if ex.verdict == REJECTED:
            store.add_error(run_id, product.product_id, competitor_key,
                            "extract", ex.method, "validation_rejected",
                            f"{u} :: " + "; ".join(ex.errors))
            continue
        if browser_required(ex):
            store.add_error(run_id, product.product_id, competitor_key,
                            "extract", ex.method, "browser_required",
                            f"{u} :: page too thin for HTTP extraction")
            continue
        from .catalog import classify_format
        ex.specs = _specs_from_extraction(ex)
        cands.append(Candidate2(
            url=ex.canonical_url or u,
            brand=ex.brand or brand,
            product_name=ex.product_name or "unknown",
            host=(ex.url.split("/")[2].lower() if "//" in ex.url else ""),
            source_tier=_tier(ex.url, [competitor_key]),
            fmt=classify_format(ex.product_name or "", ""),
            extraction=ex,
            evidence=[f"page read via {ex.method}: {ex.url}",
                      f"extraction verdict {ex.verdict} "
                      f"(confidence {round(ex.confidence, 2)})"],
        ))

    if blocks and not cands:
        out.status, out.path = BLOCKED, "discovery_blocked"
        out.exception = Exception_(
            run_id=run_id, clara_product_id=product.product_id,
            competitor_key=competitor_key, kind="blocked",
            attempted=f"discovery across {competitor_key} domains "
                      f"({len(blocks)} candidate URL(s) attempted)",
            observed="; ".join(f"{b['url']} -> {b['signal']}" for b in blocks[:4]),
            why_unresolved="Every candidate page was refused or challenged. "
                           "Bypassing those controls is not permitted.",
            recommended_action="Confirm whether this competitor's Saudi catalogue is "
                               "readable at all; if not, register an approved data "
                               "source (a feed, an API, or a retailer agreement).",
            blocks_downstream=f"No match can be established for {product.name} x {brand}.",
            evidence=[e for b in blocks for e in b["evidence"]][:8])
        store.add_match_event(run_id, product.product_id, competitor_key,
                              "discovery_blocked", prev_status, BLOCKED,
                              "all candidates blocked",
                              [b["signal"] for b in blocks][:6])
        return out

    if not cands:
        out.status, out.path = NO_MATCH, "discovered"
        store.put_match(Match(
            clara_product_id=product.product_id, competitor_key=competitor_key,
            competitor_brand=brand, status=NO_MATCH, match_score=0.0,
            comparison_basis="none",
            evidence=[f"discovery trigger: {trigger}",
                      f"providers: {', '.join(dlog.provider_chain)}",
                      f"stop reason: {dlog.stop_reason}",
                      "no candidate page was readable and valid"],
            validated_at=utcnow(), ttl_days=cfg.ttl_days, discovery_used=True))
        store.add_match_event(run_id, product.product_id, competitor_key,
                              NO_MATCH, prev_status, NO_MATCH,
                              "no readable candidate found", [dlog.stop_reason])
        return out

    # ---- STEP: evaluate + classify ----
    scored = [score_candidate(product, c, judge) for c in cands]
    decision = classify(product, scored, cfg)
    out.status, out.score, out.path = decision.status, decision.score, "discovered"
    out.decision_source = decision.decision_source
    out.log.extend(decision.evidence)

    base_ev = [f"discovery trigger: {trigger}",
               f"providers: {', '.join(dlog.provider_chain)}"] + decision.evidence

    if decision.status == AMBIGUOUS:
        top = decision.winner
        out.exception = Exception_(
            run_id=run_id, clara_product_id=product.product_id,
            competitor_key=competitor_key, kind="ambiguous",
            attempted=f"discovery and scoring of {len(scored)} candidate(s)",
            observed="; ".join(f"{c.product_name} ({c.score})"
                               for c in scored if not c.disqualified)[:600],
            why_unresolved=" ".join(decision.evidence)[:800],
            recommended_action="Pick the correct competitor product, or narrow the "
                               "competitor set assigned to this product so the "
                               "candidates can be told apart.",
            blocks_downstream=f"No usable match stored for {product.name} x {brand}.",
            evidence=(top.evidence[:5] + top.identity_conflicts[:3]) if top else [])
        store.put_match(Match(
            clara_product_id=product.product_id, competitor_key=competitor_key,
            competitor_brand=brand, status=AMBIGUOUS, match_score=decision.score,
            comparison_basis=top.basis if top else "unknown",
            competitor_url=top.url if top else None,
            competitor_product_name=top.product_name if top else None,
            fingerprint=fingerprint(top.brand, top.product_name) if top else None,
            evidence=base_ev, rejected=[c.as_dict() for c in decision.rejected[:6]],
            validated_at=None, ttl_days=cfg.ttl_days, discovery_used=True))
        store.add_match_event(run_id, product.product_id, competitor_key,
                              AMBIGUOUS, prev_status, AMBIGUOUS,
                              "candidates could not be separated",
                              decision.evidence[:4])
        return out

    if decision.status == NO_MATCH or decision.winner is None:
        store.put_match(Match(
            clara_product_id=product.product_id, competitor_key=competitor_key,
            competitor_brand=brand, status=NO_MATCH, match_score=decision.score,
            comparison_basis="none", evidence=base_ev,
            rejected=[c.as_dict() for c in decision.rejected[:6]],
            validated_at=utcnow(), ttl_days=cfg.ttl_days, discovery_used=True))
        store.add_match_event(run_id, product.product_id, competitor_key,
                              NO_MATCH, prev_status, NO_MATCH,
                              "no candidate met the threshold",
                              decision.evidence[:4])
        return out

    # ---- STEP: store the winner + observation ----
    win = decision.winner
    ex = win.extraction
    out.method, out.verdict = ex.method, ex.verdict
    match = Match(
        clara_product_id=product.product_id, competitor_key=competitor_key,
        competitor_brand=win.brand, status=decision.status,
        match_score=decision.score, comparison_basis=win.basis,
        competitor_url=win.url, competitor_product_name=win.product_name,
        fingerprint=fingerprint(win.brand, win.product_name),
        evidence=base_ev + win.evidence[:6],
        rejected=[c.as_dict() for c in decision.rejected[:6]],
        validated_at=utcnow(), ttl_days=cfg.ttl_days, discovery_used=True)
    if win.basis == ATTACHMENT_OF_SYSTEM:
        match.separately_available = False
        amt = ex.selling.amount if ex.selling else None
        if amt is not None:
            match.system_price = float(amt)   # display only; Decimal kept on the observation
    store.put_match(match)
    store.upsert_competitor_product(competitor_key, ex)
    obs = build_observation(run_id, product, competitor_key, win.brand, ex,
                            win.source_tier, cfg, win.basis)
    out.changes = detect_changes(prev_obs, obs, cfg, prev_status, decision.status)
    store.put_observation(run_id, _as_obs(obs))
    store.add_match_event(run_id, product.product_id, competitor_key,
                          decision.status, prev_status, decision.status,
                          f"matched via {win.decision_source}", win.evidence[:4])
    return out


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------

def _specs_from_extraction(ex) -> dict:
    """Competitor specs, read from the page the same way Clara's are."""
    from .catalog import extract_specs
    blob = " ".join(filter(None, [
        ex.product_name or "",
        " ".join(str(v.get("option_key") or "") for v in ex.variants[:10]),
        " ".join(ex.category_path or []),
    ]))
    return extract_specs(blob)


def _as_obs(d: dict):
    """Wrap a §10 dict in the Observation shape the store persists."""
    from .models import Observation
    o = Observation(
        clara_product_id=d["clara_product_id"],
        competitor_key=d["competitor_key"],
        observed_at=d.get("observed_at") or utcnow(),
        product_url=d.get("canonical_url") or d.get("url") or "",
        competitor_brand=d.get("competitor_brand") or "",
        competitor_product_name=d.get("product_name") or "",
        source_type=d.get("source_type") or "unknown",
    )
    o.notes = list(d.get("notes") or d.get("warnings") or [])
    o.is_stale = bool(d.get("is_stale"))
    # The full §10 payload rides along so nothing is lost to the narrower shape.
    o.__dict__["payload"] = d
    return o


# --------------------------------------------------------------------------
# the run
# --------------------------------------------------------------------------

def run(cfg: RunConfig, products: list[ClaraProduct],
        targets_limit: int | None = None, use_llm: bool = True,
        search_fn=None, db_path=DB_PATH, resume: bool = False) -> dict:
    reset_pauses()
    store = Store(db_path)

    # §16: never overlap runs for the same scope.
    inflight = store.run_in_progress()
    if inflight and inflight != cfg.run_id and not resume:
        store.close()
        raise RuntimeError(
            f"run {inflight} is still open; finish or resume it before starting "
            f"{cfg.run_id} (§16 forbids overlapping runs for one scope)")

    judge = judge_singleton() if use_llm else None
    chain = DiscoveryChain(judge=judge, search_fn=search_fn)

    for c in comp.REGISTRY.values():
        store.upsert_competitor(c)

    active_keys: set[str] = set()
    plan: list[tuple[ClaraProduct, list[str]]] = []
    for p in products:
        store.upsert_product(p)
        keys = comp.targets_for(p.fmt, p.category, p.segment, limit=targets_limit)
        store.set_targets(p.product_id, keys)
        active_keys.update(keys)
        plan.append((p, keys))

    hosts = comp.allowed_hosts(sorted(active_keys)) if active_keys else set()

    store.start_run(cfg.run_id, {
        "market": cfg.market, "currency": cfg.currency, "ttl_days": cfg.ttl_days,
        "discovery_budget": cfg.discovery_budget,
        "confirm_threshold": cfg.confirm_threshold,
        "probable_threshold": cfg.probable_threshold,
        "ambiguity_margin": cfg.ambiguity_margin,
        "price_change_flag_pct": cfg.price_change_flag_pct,
        "targets_limit": targets_limit,
        "catalog_size": len(products),
        "competitors_registered": len(comp.REGISTRY),
        "competitors_active": sorted(active_keys),
        "allowed_hosts": sorted(hosts),
        "llm": (judge.status if judge else {"available": False,
                                            "unavailable_reason": "disabled"}),
    })

    done = store.completed_pairs(cfg.run_id) if resume else set()
    outcomes: list[PairOutcome] = []

    for product, keys in plan:
        if not keys:
            store.add_match_event(cfg.run_id, product.product_id, "-",
                                  "unassigned", None, None,
                                  f"no competitor is assigned to segment "
                                  f"{product.segment!r} / category {product.category!r}",
                                  [])
            continue
        for key in keys:
            if (product.product_id, key) in done:
                continue
            try:
                o = process_pair(store, cfg.run_id, product, key, cfg, chain,
                                 judge, hosts)
            except Exception as e:      # §17: one pair must not end the run
                store.add_error(cfg.run_id, product.product_id, key, "pair",
                                "engine", type(e).__name__, str(e)[:1500])
                o = PairOutcome(product.product_id, product.name, key,
                                NO_MATCH, "error")
                o.log.append(f"pair failed: {type(e).__name__}: {e}")
                o.exception = Exception_(
                    run_id=cfg.run_id, clara_product_id=product.product_id,
                    competitor_key=key, kind="pair_error",
                    attempted="process the pair", observed=f"{type(e).__name__}: {e}",
                    why_unresolved="An unexpected error ended this pair; the run "
                                   "continued.",
                    recommended_action="Check the error log for this comparison and rerun "
                                       "it once the cause is fixed.",
                    blocks_downstream=f"No result for {product.name} x {key}.")
            outcomes.append(o)

            for ch in o.changes:
                from .models import Change
                store.add_change(cfg.run_id, Change(
                    clara_product_id=product.product_id, competitor_key=key,
                    change_type=ch["change_type"],
                    previous_value=ch["previous_value"],
                    new_value=ch["new_value"],
                    delta_pct=float(ch["delta_pct"]) if ch.get("delta_pct") else None,
                    flagged=bool(ch.get("flagged")),
                    detected_at=ch.get("detected_at") or utcnow()))

            if o.exception:
                fails = store.consecutive_failures(product.product_id, key)
                if fails >= 2 and o.exception.kind == "blocked":
                    o.exception.kind = "repeated_failure"
                    o.exception.why_unresolved += (
                        f" This pair has now failed on {fails} runs.")
                store.add_exception(o.exception)

    summary = {
        "catalog_size": len(products),
        "pairs": len(outcomes),
        "by_status": {s: sum(1 for o in outcomes if o.status == s)
                      for s in (CONFIRMED, PROBABLE, AMBIGUOUS, NO_MATCH, BLOCKED)},
        "refreshed": sum(1 for o in outcomes if o.path == "refreshed"),
        "discovered": sum(1 for o in outcomes if o.discovery_used),
        "decision_sources": {
            src: sum(1 for o in outcomes if o.decision_source == src)
            for src in {o.decision_source for o in outcomes}},
        "methods": {m: sum(1 for o in outcomes if o.method == m)
                    for m in {o.method for o in outcomes if o.method}},
        "changes": len(store.changes_for_run(cfg.run_id)),
        "exceptions": len(store.exceptions_for_run(cfg.run_id)),
        "errors": len(store.errors_for_run(cfg.run_id)),
        "llm": judge.status if judge else {"available": False},
    }
    store.finish_run(cfg.run_id, summary)
    store.close()
    return {"run_id": cfg.run_id, "summary": summary,
            "outcomes": [{
                "clara_product_id": o.clara_product_id, "clara_name": o.clara_name,
                "competitor_key": o.competitor_key, "status": o.status,
                "path": o.path, "score": o.score,
                "discovery_used": o.discovery_used,
                "decision_source": o.decision_source, "method": o.method,
                "verdict": o.verdict, "changes": o.changes,
                "discovery": o.discovery_log, "log": o.log,
            } for o in outcomes]}
