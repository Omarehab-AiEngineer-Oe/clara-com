"""Reports (§18), built from the store only.

  run summary       pairs processed, refresh vs discovery, status counts
  price report      EVERY Clara product with its price, and its matches beside it
  coverage report   each Clara product x target competitor with status and observation
  change report     match-status and price/discount/stock/variant changes, old -> new
  escalation report blocked and ambiguous pairs with evidence and required decision
  exports           Clara-linked CSV and JSONL (§18 "Data export")

No figure is derived here that is not in the store. Prices stay Decimal-as-string
end to end so nothing is rounded by a float on the way to a report.
"""

from __future__ import annotations

import csv
import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from . import competitors as comp
from .config import REPORT_DIR
from .models import AMBIGUOUS, BLOCKED, CONFIRMED, NO_MATCH, PROBABLE
from .money import pct_change, to_decimal
from .store import Store

INVALIDATED = "invalidated"
STATUSES = (CONFIRMED, PROBABLE, AMBIGUOUS, NO_MATCH, BLOCKED, INVALIDATED)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _is_stale(observed_at: str | None, stale_days: int) -> bool:
    if not observed_at:
        return True
    try:
        when = datetime.fromisoformat(observed_at)
    except ValueError:
        return True
    return when < datetime.now(timezone.utc) - timedelta(days=stale_days)


def _obs_price(obs: dict | None) -> tuple[Decimal | None, str | None, bool]:
    """(amount, currency, is_range) from a stored observation payload."""
    if not obs:
        return None, None, False
    cur = obs.get("currency")
    if obs.get("price_is_range"):
        return to_decimal(obs.get("price_min")), cur, True
    return to_decimal(obs.get("selling_price")), cur, False


# --------------------------------------------------------------------------
# price report — the whole Clara catalog, matches beside each product
# --------------------------------------------------------------------------

def price_report(store: Store, run_id: str, stale_days: int = 7) -> dict:
    """Every Clara product, its price, and every competitor match next to it.

    Products with no assigned competitor are included and labelled, so the report
    is a complete catalog view rather than only the matched subset.
    """
    products = store.get_products()
    rows = []
    matched_products = 0
    comparable = 0            # rows where a same-currency competitor price exists

    for p in products:
        targets = store.get_targets(p.product_id)
        matches = store.get_matches_for_product(p.product_id)
        clara_price = to_decimal(p.price)

        entries = []
        for m in matches:
            obs = store.get_observation(p.product_id, m.competitor_key)
            amount, cur, is_range = _obs_price(obs)
            status = m.status
            if m.invalidated_at and status in (CONFIRMED, PROBABLE):
                status = INVALIDATED

            same_cur = bool(cur and cur == p.currency)
            delta_pct = None
            multiple = None
            if same_cur and amount is not None and clara_price and clara_price > 0:
                delta_pct = str(pct_change(clara_price, amount))
                multiple = str((amount / clara_price).quantize(Decimal("0.01")))
                comparable += 1

            entries.append({
                "competitor_key": m.competitor_key,
                "competitor_brand": m.competitor_brand,
                "competitor_product_name": m.competitor_product_name,
                "competitor_url": m.competitor_url,
                "status": status,
                "match_score": m.match_score,
                "comparison_basis": m.comparison_basis,
                "separately_available": m.separately_available,
                "competitor_price": str(amount) if amount is not None else None,
                "competitor_currency": cur,
                "price_is_range": is_range,
                "price_min": obs.get("price_min") if obs else None,
                "price_max": obs.get("price_max") if obs else None,
                "price_from": obs.get("price_from") if obs else None,
                "regular_price": obs.get("regular_price") if obs else None,
                "discount_percent": obs.get("discount_percent") if obs else None,
                "availability": obs.get("availability") if obs else None,
                "promotion_text": obs.get("promotion_text") if obs else None,
                "variant_count": obs.get("variant_count") if obs else None,
                "image_count": obs.get("image_count") if obs else None,
                "method": obs.get("method") if obs else None,
                "extraction_verdict": obs.get("verdict") if obs else None,
                "same_currency": same_cur,
                "delta_pct_vs_clara": delta_pct,
                "multiple_of_clara": multiple,
                "observed_at": obs.get("observed_at") if obs else None,
                "stale": _is_stale(obs.get("observed_at") if obs else None, stale_days),
                "validated_at": m.validated_at,
                "invalid_reason": m.invalid_reason,
                "warnings": (obs.get("warnings") or []) if obs else [],
            })

        priced = [e for e in entries if e["same_currency"] and e["competitor_price"]]
        if any(e["status"] in (CONFIRMED, PROBABLE) for e in entries):
            matched_products += 1

        cheapest = None
        if priced:
            cheapest = min(priced, key=lambda e: to_decimal(e["competitor_price"]))

        rows.append({
            "product_id": p.product_id, "name": p.name, "url": p.url,
            "segment": p.segment, "category": p.category, "fmt": p.fmt,
            "clara_price": str(clara_price) if clara_price is not None else None,
            "currency": p.currency,
            "rating": p.rating, "rating_count": p.rating_count,
            "image_url": p.image_url,
            "description_lang": p.description_lang,
            "specs": p.specs,
            "assigned_competitors": targets,
            "assigned_count": len(targets),
            "match_count": len(entries),
            "matches": entries,
            "cheapest_rival": ({
                "brand": cheapest["competitor_brand"],
                "price": cheapest["competitor_price"],
                "currency": cheapest["competitor_currency"],
                "multiple_of_clara": cheapest["multiple_of_clara"],
            } if cheapest else None),
            "unassigned": not targets,
        })

    priced_products = [r for r in rows if r["clara_price"]]
    amounts = sorted(to_decimal(r["clara_price"]) for r in priced_products)
    return {
        "run_id": run_id,
        "generated_at": _now(),
        "catalog_size": len(products),
        "products_priced": len(priced_products),
        "clara_price_min": str(amounts[0]) if amounts else None,
        "clara_price_max": str(amounts[-1]) if amounts else None,
        "clara_price_median": str(amounts[len(amounts) // 2]) if amounts else None,
        "products_with_a_match": matched_products,
        "products_unassigned": sum(1 for r in rows if r["unassigned"]),
        "comparable_price_pairs": comparable,
        "products": rows,
        "note": ("Every Clara product in the catalog appears here. A competitor price "
                 "is only compared to Clara's when both are in the same currency; "
                 "cross-currency prices are shown as-is and never converted."),
    }


# --------------------------------------------------------------------------
# coverage
# --------------------------------------------------------------------------

def coverage_report(store: Store, run_id: str, stale_days: int = 7) -> dict:
    products = store.get_products()
    by_status = {s: 0 for s in STATUSES}
    by_competitor: dict[str, dict] = {}
    rows, uncovered = [], []
    stale_count = 0

    blocked_by_pair: dict[tuple[str, str], dict] = {}
    for ex in store.exceptions_for_run(run_id):
        if ex["kind"] in ("blocked", "repeated_failure", "pair_error"):
            blocked_by_pair[(ex["clara_product_id"], ex["competitor_key"])] = ex

    for p in products:
        targets = store.get_targets(p.product_id)
        matches = {m.competitor_key: m for m in store.get_matches_for_product(p.product_id)}
        pairs = []
        has_valid = False

        for key in targets or list(matches):
            c = comp.get(key)
            brand = c.brand if c else key
            m = matches.get(key)
            ex = blocked_by_pair.get((p.product_id, key))

            if m is None and ex is not None:
                status = BLOCKED
            elif m is None:
                continue
            else:
                status = m.status
                if m.invalidated_at and status in (CONFIRMED, PROBABLE):
                    status = INVALIDATED

            by_status[status] = by_status.get(status, 0) + 1
            slot = by_competitor.setdefault(
                key, {"brand": brand, "tier": c.tier if c else "unknown",
                      **{s: 0 for s in STATUSES}})
            slot[status] = slot.get(status, 0) + 1
            if status in (CONFIRMED, PROBABLE):
                has_valid = True

            obs = store.get_observation(p.product_id, key) if m else None
            stale = _is_stale(obs.get("observed_at") if obs else None, stale_days)
            if obs and stale:
                stale_count += 1

            pairs.append({
                "competitor_key": key, "competitor_brand": brand,
                "tier": c.tier if c else "unknown",
                "status": status,
                "competitor_product_name": m.competitor_product_name if m else None,
                "competitor_url": m.competitor_url if m else None,
                "match_score": m.match_score if m else None,
                "comparison_basis": m.comparison_basis if m else "none",
                "validated_at": m.validated_at if m else None,
                "invalid_reason": m.invalid_reason if m else None,
                "discovery_used": bool(m.discovery_used) if m else True,
                "evidence": (m.evidence if m else (ex.get("evidence") if ex else [])),
                "rejected_count": len(m.rejected) if m else 0,
                "observation": obs,
                "observation_stale": stale,
                "block_detail": ex.get("observed") if ex else None,
                "recommended_action": ex.get("recommended_action") if ex else None,
                "events": store.match_events_for(p.product_id, key)[:6],
                "past_invalidations": store.invalidations_for(p.product_id, key),
                "history_points": len(store.history_for(p.product_id, key)),
            })

        if targets and not has_valid:
            reason = "no confirmed or probable match stored"
            if any((p.product_id, k) in blocked_by_pair for k in targets):
                reason += "; at least one competitor was blocked and escalated"
            uncovered.append({"product_id": p.product_id, "name": p.name,
                              "segment": p.segment, "fmt": p.fmt, "reason": reason})

        rows.append({
            "product_id": p.product_id, "name": p.name, "url": p.url,
            "segment": p.segment, "category": p.category, "fmt": p.fmt,
            "price": str(to_decimal(p.price)) if p.price is not None else None,
            "currency": p.currency, "rating": p.rating,
            "rating_count": p.rating_count, "image_url": p.image_url,
            "specs": p.specs, "description_lang": p.description_lang,
            "assigned_competitors": targets, "pairs": pairs,
        })

    return {
        "run_id": run_id, "generated_at": _now(),
        "catalog_size": len(products),
        "pairs_total": sum(len(r["pairs"]) for r in rows),
        "by_status": by_status, "by_competitor": by_competitor,
        "stale_observations": stale_count,
        "products_without_valid_match": uncovered,
        "products": rows,
    }


# --------------------------------------------------------------------------
# changes, escalations, competitors
# --------------------------------------------------------------------------

def change_report(store: Store, run_id: str) -> dict:
    changes = store.changes_for_run(run_id)
    grouped: dict[str, int] = {}
    for c in changes:
        grouped[c["change_type"]] = grouped.get(c["change_type"], 0) + 1
    events = store.match_events_for_run(run_id)
    return {
        "run_id": run_id,
        "total": len(changes),
        "flagged": sum(1 for c in changes if c["flagged"]),
        "by_type": dict(sorted(grouped.items())),
        "changes": changes,
        "match_events": events,
        "match_event_counts": {
            e: sum(1 for x in events if x["event"] == e)
            for e in sorted({x["event"] for x in events})},
        "note": ("A change is flagged only when the configured threshold was crossed. "
                 "no_change rows are recorded deliberately: a run with no movement is "
                 "a valid run."),
    }


def escalation_report(store: Store, run_id: str) -> dict:
    exs = store.exceptions_for_run(run_id)
    errors = store.errors_for_run(run_id)
    by_kind: dict[str, int] = {}
    for e in exs:
        by_kind[e["kind"]] = by_kind.get(e["kind"], 0) + 1
    by_signal: dict[str, int] = {}
    for e in errors:
        by_signal[e["signal"]] = by_signal.get(e["signal"], 0) + 1
    return {
        "run_id": run_id,
        "total": len(exs),
        "by_kind": dict(sorted(by_kind.items())),
        "exceptions": exs,
        "error_count": len(errors),
        "errors_by_signal": dict(sorted(by_signal.items(), key=lambda kv: -kv[1])),
        "errors": errors[:400],
        "note": ("Every entry needs a human. Blocked entries were refused by the site "
                 "and were not worked around."),
    }


def competitor_report(store: Store, run_id: str) -> dict:
    regs = store.get_competitors()
    cov = coverage_report(store, run_id)["by_competitor"]
    out = []
    for c in regs:
        stats = cov.get(c["key"], {})
        out.append({**c, "pair_counts": {s: stats.get(s, 0) for s in STATUSES},
                    "pairs": sum(stats.get(s, 0) for s in STATUSES)})
    return {"run_id": run_id, "registered": len(regs),
            "active": sum(1 for c in out if c["pairs"]), "competitors": out}


# --------------------------------------------------------------------------
# exports (§18)
# --------------------------------------------------------------------------

PRICE_CSV_COLUMNS = [
    "run_id", "clara_product_id", "clara_name", "clara_segment", "clara_category",
    "clara_format", "clara_price", "clara_currency", "clara_rating",
    "clara_rating_count", "clara_url",
    "competitor_key", "competitor_brand", "competitor_product_name",
    "match_status", "match_score", "comparison_basis",
    "competitor_price", "competitor_currency", "regular_price", "discount_percent",
    "availability", "promotion_text", "variant_count", "image_count",
    "same_currency", "delta_pct_vs_clara", "multiple_of_clara",
    "extraction_method", "extraction_verdict", "observed_at", "stale",
    "competitor_url",
]


def export_price_csv(price: dict, path) -> None:
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=PRICE_CSV_COLUMNS)
        w.writeheader()
        for p in price["products"]:
            base = {
                "run_id": price["run_id"],
                "clara_product_id": p["product_id"], "clara_name": p["name"],
                "clara_segment": p["segment"], "clara_category": p["category"],
                "clara_format": p["fmt"], "clara_price": p["clara_price"],
                "clara_currency": p["currency"], "clara_rating": p["rating"],
                "clara_rating_count": p["rating_count"], "clara_url": p["url"],
            }
            if not p["matches"]:
                w.writerow({**base, "match_status":
                            "unassigned" if p["unassigned"] else "no_match_stored"})
                continue
            for m in p["matches"]:
                w.writerow({**base,
                            "competitor_key": m["competitor_key"],
                            "competitor_brand": m["competitor_brand"],
                            "competitor_product_name": m["competitor_product_name"],
                            "match_status": m["status"],
                            "match_score": m["match_score"],
                            "comparison_basis": m["comparison_basis"],
                            "competitor_price": m["competitor_price"],
                            "competitor_currency": m["competitor_currency"],
                            "regular_price": m["regular_price"],
                            "discount_percent": m["discount_percent"],
                            "availability": m["availability"],
                            "promotion_text": m["promotion_text"],
                            "variant_count": m["variant_count"],
                            "image_count": m["image_count"],
                            "same_currency": m["same_currency"],
                            "delta_pct_vs_clara": m["delta_pct_vs_clara"],
                            "multiple_of_clara": m["multiple_of_clara"],
                            "extraction_method": m["method"],
                            "extraction_verdict": m["extraction_verdict"],
                            "observed_at": m["observed_at"], "stale": m["stale"],
                            "competitor_url": m["competitor_url"]})


def export_jsonl(price: dict, path) -> None:
    with open(path, "w", encoding="utf-8") as f:
        for p in price["products"]:
            f.write(json.dumps(p, ensure_ascii=False) + "\n")


# --------------------------------------------------------------------------
# bundle
# --------------------------------------------------------------------------

def build_all(store: Store, run_id: str, stale_days: int = 7,
              write: bool = True) -> dict:
    bundle = {
        "run": store.get_run(run_id),
        "price": price_report(store, run_id, stale_days),
        "coverage": coverage_report(store, run_id, stale_days),
        "changes": change_report(store, run_id),
        "escalations": escalation_report(store, run_id),
        "competitors": competitor_report(store, run_id),
    }
    if write:
        REPORT_DIR.mkdir(parents=True, exist_ok=True)
        for name in ("price", "coverage", "changes", "escalations", "competitors"):
            (REPORT_DIR / f"{name}_{run_id}.json").write_text(
                json.dumps(bundle[name], ensure_ascii=False, indent=1),
                encoding="utf-8")
        export_price_csv(bundle["price"], REPORT_DIR / f"prices_{run_id}.csv")
        export_jsonl(bundle["price"], REPORT_DIR / f"prices_{run_id}.jsonl")
    return bundle


# --------------------------------------------------------------------------
# Business-facing reports: competitors, offers, actions
# --------------------------------------------------------------------------

def competitor_cards(store: Store, run_id: str) -> dict:
    """One card per competitor: the editorial profile plus what was observed.

    Observed values and profile values live under separate keys so a maintained
    note can never be read as a price the Agent actually found.
    """
    from . import competitor_profiles as cprof

    cov = coverage_report(store, run_id)
    by_comp = cov["by_competitor"]

    observed: dict[str, dict] = {}
    for p in cov["products"]:
        for pair in p["pairs"]:
            k = pair["competitor_key"]
            o = observed.setdefault(k, {
                "matched": [], "prices": [], "currencies": set(),
                "offers": [], "observed_ats": [],
                "in_stock": 0, "out_stock": 0, "blocked": 0,
            })
            if pair["status"] == BLOCKED:
                o["blocked"] += 1
                continue
            obs = pair.get("observation") or {}
            if (pair["status"] in (CONFIRMED, PROBABLE)
                    and pair.get("competitor_product_name")):
                o["matched"].append({
                    "clara_product": p["name"],
                    "clara_price": p["price"],
                    "competitor_product": pair["competitor_product_name"],
                    "competitor_url": pair["competitor_url"],
                    "price": obs.get("selling_price"),
                    "currency": obs.get("currency"),
                    "status": pair["status"],
                    "basis": pair["comparison_basis"],
                })
            amt = to_decimal(obs.get("selling_price"))
            if amt is not None:
                o["prices"].append(amt)
                if obs.get("currency"):
                    o["currencies"].add(obs["currency"])
            if obs.get("observed_at"):
                o["observed_ats"].append(obs["observed_at"])
            if obs.get("availability") == "in_stock":
                o["in_stock"] += 1
            elif obs.get("availability") == "out_of_stock":
                o["out_stock"] += 1
            if obs.get("promotion_text"):
                o["offers"].append({
                    "text": obs["promotion_text"],
                    "mechanism": obs.get("promotion_mechanism"),
                    "on": pair.get("competitor_product_name"),
                    "url": pair.get("competitor_url"),
                    "discount_percent": obs.get("discount_percent"),
                    # Enough to judge the offer without leaving the popup, plus
                    # the link to check it. An offer you cannot open is an offer
                    # you cannot verify.
                    "price": obs.get("selling_price"),
                    "was": obs.get("regular_price"),
                    "currency": obs.get("currency"),
                    "clara_product": p.get("name"),
                    "clara_price": p.get("price"),
                    "observed_at": obs.get("observed_at"),
                })

    cards = []
    for c in store.get_competitors():
        key = c["key"]
        o = observed.get(key, {})
        prices = sorted(o.get("prices", []))
        stats = by_comp.get(key, {})
        cards.append({
            "key": key,
            "brand": c["brand"],
            "segments": c["segments"],
            "sites": c["domains"],
            "retailers": c["retail_domains"],
            "profile": cprof.as_dict(key),
            "matched_products": o.get("matched", [])[:12],
            "matched_count": len(o.get("matched", [])),
            "observed_price_min": str(prices[0]) if prices else None,
            "observed_price_max": str(prices[-1]) if prices else None,
            "observed_currencies": sorted(o.get("currencies", set())),
            "offers": o.get("offers", [])[:12],
            "offer_count": len(o.get("offers", [])),
            # The newest observation the Agent holds for this competitor. Without
            # it the popup cannot say whether a price is an hour or a month old.
            "last_observed_at": max(
                [x for x in o.get("observed_ats", []) if x] or [""], default=""),
            "in_stock": o.get("in_stock", 0),
            "out_of_stock": o.get("out_stock", 0),
            "unreachable": o.get("blocked", 0),
            "pairs": sum(stats.get(s, 0) for s in STATUSES),
            "counts": {s: stats.get(s, 0) for s in STATUSES},
        })

    cards.sort(key=lambda x: (-x["matched_count"], -x["pairs"], x["brand"]))
    return {
        "run_id": run_id,
        "generated_at": _now(),
        "total": len(cards),
        "with_matches": sum(1 for c in cards if c["matched_count"]),
        "competitors": cards,
    }


def offers_report(store: Store, run_id: str) -> dict:
    """Every promotion the Agent read on a competitor page."""
    cov = coverage_report(store, run_id)
    rows = []
    for p in cov["products"]:
        for pair in p["pairs"]:
            obs = pair.get("observation") or {}
            promo = obs.get("promotion_text")
            disc = obs.get("discount_percent")
            if not promo and not disc:
                continue
            rows.append({
                "competitor_key": pair["competitor_key"],
                "competitor_brand": pair["competitor_brand"],
                "competitor_product": pair.get("competitor_product_name"),
                "competitor_url": pair.get("competitor_url"),
                "clara_product": p["name"],
                "clara_price": p["price"],
                "price": obs.get("selling_price"),
                "regular_price": obs.get("regular_price"),
                "currency": obs.get("currency"),
                "discount_percent": disc,
                "offer": promo,
                "mechanism": obs.get("promotion_mechanism"),
                "availability": obs.get("availability"),
                "seen_at": obs.get("observed_at"),
            })

    def _key(r):
        d = to_decimal(r.get("discount_percent"))
        return (1 if d is not None else 0, d if d is not None else Decimal(0))

    rows.sort(key=_key, reverse=True)

    mech: dict[str, int] = {}
    for r in rows:
        for m in (r.get("mechanism") or "").split(","):
            m = m.strip()
            if m:
                mech[m] = mech.get(m, 0) + 1

    return {
        "run_id": run_id,
        "generated_at": _now(),
        "total": len(rows),
        "with_a_price_cut": sum(1 for r in rows
                                if to_decimal(r.get("discount_percent"))),
        "by_mechanism": dict(sorted(mech.items(), key=lambda kv: -kv[1])),
        "brands_running_offers": sorted({r["competitor_brand"] for r in rows}),
        "offers": rows,
        "note": ("Only promotions actually printed on the competitor's page are "
                 "listed. A price cut is counted only where the page showed both "
                 "the old and the new price."),
    }


def actions_report(store: Store, run_id: str) -> dict:
    """The handoff list: what a person has to DO, plus the links and help to do it.

    Each task carries the pages the Agent could not read, somewhere else to try,
    and what to capture once a page is open. It still leaves out the internals —
    which method ran, what the failure signal was — because that belongs in the
    log, not in someone's task list.
    """
    import re as _re

    from . import competitors as comp

    products = {p.product_id: p for p in store.get_products()}

    KIND_LABEL = {
        "blocked": "Page could not be read",
        "repeated_failure": "Failing repeatedly",
        "ambiguous": "Needs a human decision",
        "pair_error": "Did not complete",
        "unassigned": "No competitor assigned",
    }
    PRIORITY = {"ambiguous": 1, "repeated_failure": 2, "blocked": 3,
                "pair_error": 4, "unassigned": 5}

    HOW_TO = {
        "blocked": [
            "Open each link below in a normal browser window.",
            "Note the selling price, any before-discount price, and the currency.",
            "Note whether it is in stock, and copy any offer wording exactly.",
            "If none of the links open for you either, the site is refusing "
            "automated access: ask for an official feed, an API, or a retailer "
            "agreement instead.",
        ],
        "repeated_failure": [
            "This pair has failed on more than one run, so a plain retry will not "
            "fix it.",
            "Open the links below and confirm the product still exists at that "
            "address.",
            "If it moved, put the new link on the match. If it is gone, record that "
            "there is no counterpart.",
        ],
        "ambiguous": [
            "Open the candidate links below side by side.",
            "Pick the one that is the same product as Clara's — same format and same "
            "function, not merely the same price.",
            "If two are the same model in different colours or sizes they are "
            "variants: pick either and the rest follow.",
            "If none of them is the same product, record no counterpart rather than "
            "forcing a match.",
        ],
        "pair_error": [
            "Open the links below and check the page loads for a person.",
            "If it does, rerun this pair. If it does not, treat it as unreachable.",
        ],
        "unassigned": [
            "Decide which competitor this product should be compared against.",
            "Add it to the assignment for this category, or take the product out of "
            "competitor monitoring if it has no real rival.",
        ],
    }

    # Every URL the Agent attempted for a pair, taken from the error log and the
    # escalation text. These are the links the person actually needs to click.
    attempted: dict[tuple[str, str], list[dict]] = {}
    for err in store.errors_for_run(run_id):
        for u in _re.findall(r"https?://[^\s;)\]]+", err.get("detail") or ""):
            u = u.rstrip(".,;")
            slot = attempted.setdefault(
                (err["clara_product_id"], err["competitor_key"]), [])
            if not any(x["url"] == u for x in slot):
                slot.append({"url": u, "why": err.get("signal") or ""})

    rows = []
    for e in store.exceptions_for_run(run_id):
        kind = e["kind"]
        pid, ckey = e["clara_product_id"], e["competitor_key"]
        product = products.get(pid)
        c = comp.get(ckey)

        links = list(attempted.get((pid, ckey), []))
        blob = f'{e.get("observed") or ""} {e.get("attempted") or ""}'
        for u in _re.findall(r"https?://[^\s;)\]]+", blob):
            u = u.rstrip(".,;")
            if not any(x["url"] == u for x in links):
                links.append({"url": u, "why": "attempted"})

        # For an undecided pair, the candidates are the whole point of the task.
        candidates = []
        m = store.get_match(pid, ckey)
        if m:
            if m.competitor_url:
                candidates.append({"url": m.competitor_url,
                                   "name": m.competitor_product_name or "candidate"})
            for r in (m.rejected or [])[:6]:
                if r.get("url") and not any(x["url"] == r["url"] for x in candidates):
                    candidates.append({"url": r["url"],
                                       "name": r.get("product_name") or "candidate"})

        # Somewhere else to look. A domain that already failed above is not a
        # suggestion, so those are left out rather than repeated.
        failed_hosts = {
            (l["url"].split("/")[2].lower().removeprefix("www.")
             if "//" in l["url"] else "")
            for l in links
        }
        elsewhere = []
        if c:
            for d in c.domains:
                if d.lower().removeprefix("www.") in failed_hosts:
                    continue
                elsewhere.append({"url": f"https://{d}", "label": f"{c.brand} site"})
            for d in c.retail_domains:
                if d.lower().removeprefix("www.") in failed_hosts:
                    continue
                elsewhere.append({"url": f"https://{d}", "label": d})
            if c.search_url and product:
                q = (product.name or "").replace(" ", "+")
                elsewhere.append({"url": c.search_url.replace("{q}", q),
                                  "label": f"search {c.brand}"})

        rows.append({
            "product": product.name if product else pid,
            "product_id": pid,
            "product_url": product.url if product else None,
            "product_price": (str(to_decimal(product.price))
                              if product and product.price is not None else None),
            "currency": product.currency if product else "SAR",
            "competitor": c.brand if c else ckey,
            "competitor_key": ckey,
            "kind": kind,
            "kind_label": KIND_LABEL.get(kind, kind),
            "do": e.get("recommended_action") or "",
            "how_to": HOW_TO.get(kind, []),
            "links": links[:6],
            "candidates": candidates[:6],
            "elsewhere": elsewhere[:6],
            "blocks": e.get("blocks_downstream") or "",
            "priority": PRIORITY.get(kind, 9),
        })

    rows.sort(key=lambda r: (r["priority"], r["product"]))

    grouped: dict[str, list] = {}
    for r in rows:
        grouped.setdefault(r["kind_label"], []).append(r)

    return {
        "run_id": run_id,
        "generated_at": _now(),
        "total": len(rows),
        "with_links": sum(1 for r in rows if r["links"] or r["candidates"]),
        "by_kind": {k: len(v) for k, v in grouped.items()},
        "actions": rows,
        "note": ("Each row is one task for a person. The links are the pages the "
                 "Agent could not read, or could not choose between — open them "
                 "directly."),
    }
