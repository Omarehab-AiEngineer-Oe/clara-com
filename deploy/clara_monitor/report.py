"""Coverage, change and exception reports — built from the store only.

If a figure is not in the store, the report says so rather than deriving it.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from .config import REPORT_DIR
from .models import AMBIGUOUS, BLOCKED, CONFIRMED, NOT_PUBLISHED, NO_MATCH, PROBABLE
from .store import Store


def _is_stale(observed_at: str | None, stale_days: int) -> bool:
    if not observed_at:
        return True
    try:
        when = datetime.fromisoformat(observed_at)
    except ValueError:
        return True
    return when < datetime.now(timezone.utc) - timedelta(days=stale_days)


def coverage_report(store: Store, run_id: str, stale_days: int = 7) -> dict:
    products = store.get_products()
    rows, uncovered = [], []
    by_status = {s: 0 for s in (CONFIRMED, PROBABLE, AMBIGUOUS, NO_MATCH, BLOCKED)}
    by_competitor: dict[str, dict] = {}
    stale_count = 0

    blocked_by_product: dict[str, list[dict]] = {}
    for ex in store.exceptions_for_run(run_id):
        if ex["kind"] in ("blocked", "repeated_failure"):
            blocked_by_product.setdefault(ex["clara_product_id"], []).append(ex)

    for p in products:
        matches = store.get_matches_for_product(p.product_id)
        pairs = []
        has_valid = False

        for m in matches:
            obs = store.get_observation(p.product_id, m.competitor_key)
            stale = _is_stale(obs.get("observed_at") if obs else None, stale_days)
            if obs and stale:
                stale_count += 1

            status = m.status
            if m.invalidated_at and status in (CONFIRMED, PROBABLE):
                status = "invalidated"
            else:
                by_status[status] = by_status.get(status, 0) + 1
            if status in (CONFIRMED, PROBABLE):
                has_valid = True

            slot = by_competitor.setdefault(
                m.competitor_key,
                {"brand": m.competitor_brand, **{s: 0 for s in by_status}},
            )
            slot[status] = slot.get(status, 0) + 1

            pairs.append({
                "competitor_key": m.competitor_key,
                "competitor_brand": m.competitor_brand,
                "competitor_product_name": m.competitor_product_name,
                "competitor_url": m.competitor_url,
                "status": status,
                "match_score": m.match_score,
                "comparison_basis": m.comparison_basis,
                "validated_at": m.validated_at,
                "invalid_reason": m.invalid_reason,
                "discovery_used": m.discovery_used,
                "evidence": m.evidence,
                "rejected_count": len(m.rejected),
                "observation": obs,
                "observation_stale": stale,
                "system_price": m.system_price,
                "separately_available": m.separately_available,
                "history_points": len(store.history_for(p.product_id, m.competitor_key)),
                "match_revisions": len(store.match_history_for(p.product_id,
                                                              m.competitor_key)),
                # Survives re-discovery: replacing an invalid match must not
                # erase the record of why it was invalidated.
                "past_invalidations": store.invalidations_for(p.product_id,
                                                             m.competitor_key),
            })

        # A blocked pair is never stored as a match, so it would otherwise be
        # invisible here. It must show up: a refused site is a reportable
        # outcome, not an absence.
        matched_keys = {m.competitor_key for m in matches}
        for ex in blocked_by_product.get(p.product_id, []):
            if ex["competitor_key"] in matched_keys:
                continue
            by_status[BLOCKED] = by_status.get(BLOCKED, 0) + 1
            slot = by_competitor.setdefault(
                ex["competitor_key"],
                {"brand": ex["competitor_key"], **{s_: 0 for s_ in by_status}},
            )
            slot[BLOCKED] = slot.get(BLOCKED, 0) + 1
            pairs.append({
                "competitor_key": ex["competitor_key"],
                "competitor_brand": ex["competitor_key"],
                "competitor_product_name": None,
                "competitor_url": None,
                "status": BLOCKED,
                "match_score": None,
                "comparison_basis": "none",
                "validated_at": None,
                "invalid_reason": None,
                "discovery_used": True,
                "evidence": ex.get("evidence", []),
                "rejected_count": 0,
                "observation": None,
                "observation_stale": False,
                "system_price": None,
                "separately_available": None,
                "history_points": 0,
                "block_detail": ex.get("observed"),
                "recommended_action": ex.get("recommended_action"),
            })

        if not has_valid:
            reason = "no confirmed or probable match stored"
            if blocked_by_product.get(p.product_id):
                reason += "; at least one competitor was blocked and escalated"
            uncovered.append({"product_id": p.product_id, "name": p.name,
                              "fmt": p.fmt, "reason": reason})

        rows.append({
            "product_id": p.product_id, "name": p.name, "fmt": p.fmt,
            "price": p.price, "currency": p.currency,
            "rating": p.rating, "rating_count": p.rating_count,
            "image_url": p.image_url, "url": p.url,
            "specs": p.specs, "description_lang": p.description_lang,
            "pairs": pairs,
        })

    return {
        "run_id": run_id,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "products_in_scope": len(products),
        "pairs_total": sum(len(r["pairs"]) for r in rows),
        "by_status": by_status,
        "by_competitor": by_competitor,
        "stale_observations": stale_count,
        "products_without_valid_match": uncovered,
        "products": rows,
    }


def change_report(store: Store, run_id: str) -> dict:
    changes = store.changes_for_run(run_id)
    grouped: dict[str, list] = {}
    for c in changes:
        grouped.setdefault(c["change_type"], []).append(c)
    return {
        "run_id": run_id,
        "total": len(changes),
        "flagged": sum(1 for c in changes if c["flagged"]),
        "by_type": {k: len(v) for k, v in sorted(grouped.items())},
        "changes": changes,
        "note": ("A change is flagged only when the configured threshold was "
                 "crossed. no_change rows are recorded deliberately: a run with "
                 "no movement is a valid run."),
    }


def exception_report(store: Store, run_id: str) -> dict:
    exs = store.exceptions_for_run(run_id)
    grouped: dict[str, list] = {}
    for e in exs:
        grouped.setdefault(e["kind"], []).append(e)
    return {
        "run_id": run_id,
        "total": len(exs),
        "by_kind": {k: len(v) for k, v in sorted(grouped.items())},
        "exceptions": exs,
        "note": ("Every entry here needs a human. Blocked entries were refused by "
                 "the site and were not worked around."),
    }


def build_all(store: Store, run_id: str, stale_days: int = 7,
              write: bool = True) -> dict:
    bundle = {
        "run": store.get_run(run_id),
        "coverage": coverage_report(store, run_id, stale_days),
        "changes": change_report(store, run_id),
        "exceptions": exception_report(store, run_id),
    }
    if write:
        REPORT_DIR.mkdir(parents=True, exist_ok=True)
        for name in ("coverage", "changes", "exceptions"):
            (REPORT_DIR / f"{name}_{run_id}.json").write_text(
                json.dumps(bundle[name], ensure_ascii=False, indent=1), encoding="utf-8")
        (REPORT_DIR / f"run_{run_id}.json").write_text(
            json.dumps(bundle, ensure_ascii=False, indent=1), encoding="utf-8")
    return bundle
