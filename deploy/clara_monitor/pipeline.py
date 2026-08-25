"""The monitoring run.

Product-first loop, exactly the order in section 4:

  load -> read stored matches -> refresh valid ones -> revalidate
       -> discover only if necessary -> evaluate -> classify
       -> observe -> store -> report

Discovery is unreachable except through a failed validity test.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from .config import ASSIGNMENT_BY_FORMAT, DB_PATH, RunConfig
from .matching import (
    RefreshResult, SearchProvider, SeedSearchProvider, classify,
    comparison_basis_for, discover, fingerprint, refresh_match,
)
from .models import (
    AMBIGUOUS, BLOCKED, CONFIRMED, NOT_PUBLISHED, NO_MATCH, PROBABLE,
    Change, ClaraProduct, Exception_, Match, Observation,
)
from .observe import observe_from_html
from .store import Store, utcnow


@dataclass
class PairOutcome:
    clara_product_id: str
    clara_name: str
    competitor_key: str
    status: str
    path: str                  # refreshed | discovered | reused_blocked | ...
    score: float = 0.0
    discovery_used: bool = False
    changes: list[Change] = field(default_factory=list)
    exception: Exception_ | None = None
    log: list[str] = field(default_factory=list)


def assigned_competitors(product: ClaraProduct, cfg: RunConfig) -> list[str]:
    keys = ASSIGNMENT_BY_FORMAT.get(product.fmt, [])
    return [k for k in keys if k in cfg.competitors]


# --------------------------------------------------------------------------
# change detection
# --------------------------------------------------------------------------

_TRACKED = (
    ("current_price", "price"),
    ("discount_percent", "discount"),
    ("stock_status", "stock"),
    ("promotion_text", "promotion"),
    ("variant", "variant"),
    ("primary_image_url", "image"),
    ("product_url", "url"),
)


def detect_changes(prev: dict | None, obs: Observation, cfg: RunConfig,
                   prev_status: str | None, new_status: str) -> list[Change]:
    now = utcnow()
    pid, ck = obs.clara_product_id, obs.competitor_key
    out: list[Change] = []

    if prev_status and prev_status != new_status:
        out.append(Change(pid, ck, "status_changed", prev_status, new_status,
                          detected_at=now, flagged=True))

    if prev is None:
        out.append(Change(pid, ck, "no_change", None,
                          "first observation for this pair", detected_at=now))
        return out

    cur = obs.as_dict()
    changed = False

    for field_name, label in _TRACKED:
        a, b = prev.get(field_name, NOT_PUBLISHED), cur.get(field_name, NOT_PUBLISHED)
        if a == b:
            continue
        changed = True

        if label == "price":
            if isinstance(a, (int, float)) and isinstance(b, (int, float)):
                delta = round((b - a) / a * 100, 2) if a else None
                ctype = "price_increase" if b > a else "price_decrease"
                flagged = delta is not None and abs(delta) >= cfg.price_change_flag_pct
                out.append(Change(pid, ck, ctype, a, b, delta, flagged, now))
                if delta is not None and abs(delta) >= cfg.price_sanity_pct:
                    out.append(Change(pid, ck, "price_beyond_sanity_bound", a, b,
                                      delta, True, now))
            else:
                out.append(Change(pid, ck, "price_availability_changed", a, b,
                                  None, True, now))

        elif label == "discount":
            was = isinstance(a, (int, float)) and a > 0
            now_d = isinstance(b, (int, float)) and b > 0
            if not was and now_d:
                ctype = "discount_started"
            elif was and not now_d:
                ctype = "discount_ended"
            else:
                ctype = "discount_changed"
            out.append(Change(pid, ck, ctype, a, b, None, True, now))

        elif label == "stock":
            if b == "in_stock" and a != "in_stock":
                ctype = "stock_in"
            elif b == "out_of_stock" and a != "out_of_stock":
                ctype = "stock_out"
            else:
                ctype = "stock_status_changed"
            out.append(Change(pid, ck, ctype, a, b, None, True, now))

        elif label == "promotion":
            if a in (NOT_PUBLISHED, None) and b not in (NOT_PUBLISHED, None):
                ctype = "promotion_started"
            elif b in (NOT_PUBLISHED, None):
                ctype = "promotion_ended"
            else:
                ctype = "promotion_changed"
            out.append(Change(pid, ck, ctype, a, b, None, True, now))

        elif label == "variant":
            out.append(Change(pid, ck, "variant_changed", a, b, None, False, now))
        elif label == "image":
            out.append(Change(pid, ck, "image_changed", a, b, None, False, now))
        elif label == "url":
            out.append(Change(pid, ck, "url_changed", a, b, None, True, now))

    if not changed and not out:
        out.append(Change(pid, ck, "no_change", None, None, detected_at=now))
    return out


def _mark_stale(obs: Observation, cfg: RunConfig) -> Observation:
    try:
        when = datetime.fromisoformat(obs.observed_at)
    except ValueError:
        return obs
    if when < datetime.now(timezone.utc) - timedelta(days=cfg.observation_stale_days):
        obs.is_stale = True
        obs.notes.append(
            f"observation older than {cfg.observation_stale_days} days; labelled stale")
    return obs


# --------------------------------------------------------------------------
# one pair
# --------------------------------------------------------------------------

def process_pair(store: Store, product: ClaraProduct, competitor_key: str,
                 cfg: RunConfig, provider: SearchProvider) -> PairOutcome:
    brand = cfg.competitors[competitor_key].get("brand", competitor_key)
    out = PairOutcome(product.product_id, product.name, competitor_key,
                      status=NO_MATCH, path="none")
    prev_obs = store.get_observation(product.product_id, competitor_key)
    stored = store.get_match(product.product_id, competitor_key)
    prev_status = stored.status if stored else None

    # ---- STEP 2/3: stored match, refresh valid ones first ----
    refreshed: RefreshResult | None = None
    if stored:
        valid, why = store.match_is_valid(stored, cfg.ttl_days, cfg.allowed_hosts())
        out.log.append(f"stored match {stored.status}: {why}")
        if valid:
            refreshed = refresh_match(stored, cfg)

            if refreshed.blocked:
                out.status, out.path = BLOCKED, "refresh_blocked"
                out.exception = Exception_(
                    run_id="", clara_product_id=product.product_id,
                    competitor_key=competitor_key, kind="blocked",
                    attempted=f"refresh stored match at {stored.competitor_url}",
                    observed=f"access blocked: {refreshed.block_signal}",
                    why_unresolved=("The site refused or challenged the request. Working "
                                    "around a login, CAPTCHA, rate limit or access "
                                    "restriction is not permitted."),
                    recommended_action=("A human should open the URL manually and confirm "
                                        "the price and stock, or arrange permitted access "
                                        "(official feed, API, or agreement with the "
                                        "retailer)."),
                    blocks_downstream=(f"No current observation for {product.name} × "
                                       f"{brand}; the stored match is kept, not invalidated."),
                    evidence=refreshed.evidence,
                )
                # stale-but-kept: surface the last known observation as stale
                if prev_obs:
                    stale = Observation(**{k: v for k, v in prev_obs.items()
                                           if k in Observation.__dataclass_fields__})
                    _mark_stale(stale, cfg)
                    stale.notes.append(f"not refreshed this run: {refreshed.block_signal}")
                    store.put_observation("", stale)
                return out

            if refreshed.ok:
                out.status, out.path, out.score = stored.status, "refreshed", stored.match_score
                obs = observe_from_html(
                    product.product_id, competitor_key, brand,
                    stored.competitor_url or "", refreshed.html or "",
                    cfg.source_type_for_host(
                        (stored.competitor_url or "").split("/")[2]
                        if "//" in (stored.competitor_url or "") else ""),
                    cfg.currency,
                )
                stored.validated_at = utcnow()
                stored.evidence = (stored.evidence + refreshed.evidence)[-12:]
                store.put_match(stored)
                out.changes = detect_changes(prev_obs, obs, cfg, prev_status, stored.status)
                store.put_observation("", obs)
                out.log.append("refreshed without re-running discovery")
                return out

            # refresh says the stored match no longer holds
            store.invalidate_match(stored, refreshed.invalid_reason or "refresh failed")
            out.log.append(f"stored match invalidated: {refreshed.invalid_reason}")
        else:
            out.log.append("stored match not valid; discovery permitted")

    # ---- STEP 5: discovery, only now ----
    candidates, blocks, dlog = discover(product, competitor_key, cfg, provider)
    out.log.extend(dlog)
    out.discovery_used = True

    if blocks and not candidates:
        out.status, out.path = BLOCKED, "discovery_blocked"
        first = blocks[0]
        out.exception = Exception_(
            run_id="", clara_product_id=product.product_id,
            competitor_key=competitor_key, kind="blocked",
            attempted=f"discovery across {competitor_key} domains "
                      f"({len(blocks)} candidate URL(s) attempted)",
            observed="; ".join(f"{b['url']} → {b['signal']}" for b in blocks[:4]),
            why_unresolved=("Every candidate page was refused or challenged. Bypassing "
                            "those controls is not permitted."),
            recommended_action=("A human should confirm whether this competitor's Saudi "
                                "catalogue is readable at all, and if not, register an "
                                "approved data source for it."),
            blocks_downstream=f"No match can be established for {product.name} × {brand}.",
            evidence=[e for b in blocks for e in b["evidence"]][:8],
        )
        return out

    # ---- STEP 6/7: evaluate and classify ----
    decision = classify(product, candidates, cfg)
    out.status, out.score, out.path = decision.status, decision.score, "discovered"
    out.log.extend(decision.evidence)

    if decision.status == AMBIGUOUS:
        top = decision.winner
        out.exception = Exception_(
            run_id="", clara_product_id=product.product_id,
            competitor_key=competitor_key, kind="ambiguous",
            attempted=f"discovery and scoring of {len(candidates)} candidate(s)",
            observed="; ".join(
                f"{c.product_name} ({c.score})" for c in candidates[:4] if not c.disqualified),
            why_unresolved=" ".join(decision.evidence),
            recommended_action=("A human should pick the correct competitor product, or "
                                "narrow the assignment for this Clara device so the "
                                "candidates are separable."),
            blocks_downstream=f"No match stored for {product.name} × {brand}.",
            evidence=(top.evidence[:6] if top else []),
        )
        # An ambiguous outcome is recorded as a match row with status ambiguous,
        # so the pair is not re-discovered blindly on the next run.
        store.put_match(Match(
            clara_product_id=product.product_id, competitor_key=competitor_key,
            competitor_brand=brand, status=AMBIGUOUS, match_score=decision.score,
            comparison_basis=comparison_basis_for(product, top) if top else "unknown",
            competitor_url=top.url if top else None,
            competitor_product_name=top.product_name if top else None,
            fingerprint=fingerprint(top.brand, top.product_name) if top else None,
            evidence=decision.evidence,
            rejected=[c.as_dict() for c in decision.rejected[:6]],
            validated_at=None, ttl_days=cfg.ttl_days, discovery_used=True,
        ))
        return out

    if decision.status == NO_MATCH or decision.winner is None:
        store.put_match(Match(
            clara_product_id=product.product_id, competitor_key=competitor_key,
            competitor_brand=brand, status=NO_MATCH, match_score=decision.score,
            comparison_basis="none", evidence=decision.evidence,
            rejected=[c.as_dict() for c in decision.rejected[:6]],
            validated_at=utcnow(), ttl_days=cfg.ttl_days, discovery_used=True,
        ))
        out.log.append("no_match stored with the candidates that were rejected")
        return out

    # ---- STEP 8/9: observe and store the winner ----
    win = decision.winner
    res_html = None
    from .access import guarded_get
    res = guarded_get(win.url, cfg.allowed_hosts())
    if res.ok and res.html:
        res_html = res.html
    basis = comparison_basis_for(product, win)

    match = Match(
        clara_product_id=product.product_id, competitor_key=competitor_key,
        competitor_brand=win.brand, status=decision.status,
        match_score=decision.score, comparison_basis=basis,
        competitor_url=win.url, competitor_product_name=win.product_name,
        fingerprint=fingerprint(win.brand, win.product_name),
        evidence=win.evidence[:8] + decision.evidence,
        rejected=[c.as_dict() for c in decision.rejected[:6]],
        validated_at=utcnow(), ttl_days=cfg.ttl_days, discovery_used=True,
    )

    if res_html:
        obs = observe_from_html(product.product_id, competitor_key, win.brand,
                                win.url, res_html, win.source_type, cfg.currency)
        if basis == "attachment_of_system":
            match.separately_available = False
            if isinstance(obs.current_price, (int, float)):
                match.system_price = obs.current_price
            obs.notes.append(
                "comparison_basis is attachment_of_system: this price is for the whole "
                "system, and the matched attachment is not sold separately")
        store.put_match(match)
        out.changes = detect_changes(prev_obs, obs, cfg, prev_status, decision.status)
        store.put_observation("", obs)
    else:
        store.put_match(match)
        out.log.append("match stored but the winning page could not be re-read for "
                       "an observation")
    return out


# --------------------------------------------------------------------------
# the run
# --------------------------------------------------------------------------

def run(cfg: RunConfig, products: list[ClaraProduct],
        provider: SearchProvider | None = None,
        db_path=DB_PATH) -> dict:
    provider = provider or SeedSearchProvider()
    store = Store(db_path)
    store.start_run(cfg.run_id, {
        "market": cfg.market, "currency": cfg.currency, "ttl_days": cfg.ttl_days,
        "discovery_budget": cfg.discovery_budget,
        "confirm_threshold": cfg.confirm_threshold,
        "probable_threshold": cfg.probable_threshold,
        "competitors": list(cfg.competitors),
        "allowed_hosts": sorted(cfg.allowed_hosts()),
        "scope_size": len(products),
    })

    for p in products:
        store.upsert_product(p)

    outcomes: list[PairOutcome] = []

    for product in products:
        comps = assigned_competitors(product, cfg)
        if not comps:
            store.add_exception(Exception_(
                run_id=cfg.run_id, clara_product_id=product.product_id,
                competitor_key="-", kind="unassigned",
                attempted=f"assign competitors for format {product.fmt!r}",
                observed=f"no competitor is assigned to format {product.fmt!r}",
                why_unresolved="The configuration has no assignment for this format.",
                recommended_action="Add an assignment for this format, or mark the "
                                   "product out of scope for catalog monitoring.",
                blocks_downstream=f"{product.name} has no competitor coverage.",
                evidence=[f"product {product.product_id} classified as {product.fmt}"],
            ))
            continue

        for ck in comps:
            outcome = process_pair(store, product, ck, cfg, provider)
            outcomes.append(outcome)

            for c in outcome.changes:
                store.add_change(cfg.run_id, c)

            if outcome.exception:
                outcome.exception.run_id = cfg.run_id
                outcome.exception.created_at = utcnow()
                fails = store.consecutive_failures(product.product_id, ck)
                if fails >= 2:
                    outcome.exception.kind = "repeated_failure"
                    outcome.exception.why_unresolved += (
                        f" This pair has now failed on {fails} runs.")
                store.add_exception(outcome.exception)

    summary = {
        "pairs": len(outcomes),
        "by_status": {s: sum(1 for o in outcomes if o.status == s)
                      for s in (CONFIRMED, PROBABLE, AMBIGUOUS, NO_MATCH, BLOCKED)},
        "refreshed": sum(1 for o in outcomes if o.path == "refreshed"),
        "discovered": sum(1 for o in outcomes if o.discovery_used),
        "changes": len(store.changes_for_run(cfg.run_id)),
        "exceptions": len(store.exceptions_for_run(cfg.run_id)),
    }
    store.finish_run(cfg.run_id, summary)
    store.close()
    return {"run_id": cfg.run_id, "summary": summary,
            "outcomes": [
                {"clara_product_id": o.clara_product_id, "clara_name": o.clara_name,
                 "competitor_key": o.competitor_key, "status": o.status,
                 "path": o.path, "score": o.score,
                 "discovery_used": o.discovery_used,
                 "changes": [c.as_dict() for c in o.changes],
                 "log": o.log}
                for o in outcomes
            ]}
