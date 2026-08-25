"""Computing the new state from the previous one.

The orchestrator's governing rule is that stored data is the *previous state*, not
the truth, and the new state has to be computed as

    previous  +  new evidence  +  verified changes  -  expired information

Two of those four terms are the ones systems usually get wrong.

**Never simply copy the previous state.** A field carries forward only when this
cycle produced nothing better for it, and when it does it is stamped
`carried_from` with the cycle it came from and `stale: true` once nothing has
re-confirmed it. So a value that has not been re-observed for six cycles is still
visible, but it is visibly old rather than quietly presented as current.

**Expired information is subtracted, not left lying around.** An offer that ended
leaves the live set; a competitor that has not been seen for a long time goes
dormant rather than staying in the active list forever. Removal is recorded as a
typed change, because a competitor disappearing is itself intelligence.

The diff produces the twelve change types the orchestrator names, and every change
carries the evidence behind it so the Verification Agent can rule on it before the
Intelligence Agent is allowed to interpret it.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from ..money import to_decimal
from .contracts import (Change, ChangeType, Confidence, Evidence, OfferStatus,
                        evidence_list, now_iso)

# A competitor not seen for this long stops counting as active. It is not deleted
# — a brand that goes quiet for a season and returns is one company, not two.
DORMANT_AFTER_DAYS = 45

# How far a price may move before it is worth reporting. Below this it is
# rounding, currency display or a rewritten template, not a pricing decision.
PRICE_NOISE_PERCENT = 1.0


def _age_days(stamp: str) -> float | None:
    if not stamp:
        return None
    try:
        dt = datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - dt).total_seconds() / 86400.0


def carry_forward(previous: dict, fresh: dict, cycle_id: str) -> dict:
    """Merge a fresh record over a previous one without pretending it is all new.

    A fresh value always wins. A previous value survives only where the fresh
    record has nothing — and it arrives marked, so the report can show it as
    carried rather than confirmed.
    """
    if not previous:
        return dict(fresh)
    out = dict(previous)
    carried = []
    for key, value in fresh.items():
        if value in (None, "", [], {}, "unknown"):
            if key in previous and previous[key] not in (None, "", [], {}):
                carried.append(key)
                continue
        out[key] = value
    if carried:
        out["carried_from"] = previous.get("last_cycle_id") or previous.get(
            "carried_from") or "an earlier cycle"
        out["carried_fields"] = carried
        age = _age_days(previous.get("last_seen_at") or "")
        out["stale"] = bool(age and age > DORMANT_AFTER_DAYS)
    else:
        out.pop("carried_from", None)
        out.pop("carried_fields", None)
        out["stale"] = False
    out["last_cycle_id"] = cycle_id
    return out


# --------------------------------------------------------------------------
# change detection
# --------------------------------------------------------------------------

def diff_competitors(previous: dict, current: dict) -> list[Change]:
    """NEW_ / REMOVED_ / COMPETITOR_CHANGED / POSITIONING_ / RELEVANCE_."""
    changes: list[Change] = []
    prev = previous or {}
    stamp = now_iso()

    for key, rec in current.items():
        old = prev.get(key)
        name = rec.get("name") or key
        ev = evidence_list(rec.get("evidence") or [])

        if not old:
            changes.append(Change(
                change_type=ChangeType.NEW_COMPETITOR, entity=name,
                new_value=name,
                detail=(f"{name} was not in the previous state. "
                        + (rec.get("why_competitive") or "")),
                confidence=rec.get("confidence") or Confidence.UNVERIFIED,
                evidence=ev, detected_at=stamp))
            continue

        old_prof = old.get("profile") or {}
        new_prof = rec.get("profile") or {}

        old_pos = (old_prof.get("positioning") or {}).get("value_proposition")
        new_pos = (new_prof.get("positioning") or {}).get("value_proposition")
        if old_pos and new_pos and old_pos != new_pos and new_pos != "unknown":
            changes.append(Change(
                change_type=ChangeType.POSITIONING_CHANGED, entity=name,
                field_name="value_proposition",
                previous_value=old_pos, new_value=new_pos,
                confidence=rec.get("confidence") or Confidence.UNVERIFIED,
                evidence=ev, detected_at=stamp))

        if old.get("relevance") and rec.get("relevance") and \
                old["relevance"] != rec["relevance"]:
            changes.append(Change(
                change_type=ChangeType.RELEVANCE_CHANGED, entity=name,
                field_name="relevance",
                previous_value=old["relevance"], new_value=rec["relevance"],
                detail="how this company relates to Clara has been reassessed",
                confidence=rec.get("confidence") or Confidence.UNVERIFIED,
                evidence=ev, detected_at=stamp))

        old_doms = set(old.get("domains") or [])
        new_doms = set(rec.get("domains") or [])
        if new_doms - old_doms:
            changes.append(Change(
                change_type=ChangeType.COMPETITOR_CHANGED, entity=name,
                field_name="domains",
                previous_value=", ".join(sorted(old_doms)),
                new_value=", ".join(sorted(new_doms)),
                detail="a new selling surface was found for this company",
                confidence=rec.get("confidence") or Confidence.UNVERIFIED,
                evidence=ev, detected_at=stamp))

        changes.extend(_diff_products(name, old_prof, new_prof, ev, stamp))

    for key, old in prev.items():
        if key in current:
            continue
        name = old.get("name") or key
        age = _age_days(old.get("last_seen_at") or "")
        changes.append(Change(
            change_type=ChangeType.REMOVED_COMPETITOR, entity=name,
            previous_value=name,
            detail=(f"not present in this cycle"
                    + (f"; last seen {age:.0f} days ago" if age else "")),
            confidence=Confidence.MEDIUM,
            evidence=evidence_list(old.get("evidence") or []), detected_at=stamp))
    return changes


def _diff_products(name: str, old_prof: dict, new_prof: dict,
                   ev: list[Evidence], stamp: str) -> list[Change]:
    """NEW_PRODUCT / PRODUCT_CHANGED / FEATURE_CHANGED / PRICE_CHANGED."""
    changes: list[Change] = []

    old_products = {p.get("url"): p for p in (old_prof.get("products") or [])
                    if p.get("url")}
    new_products = {p.get("url"): p for p in (new_prof.get("products") or [])
                    if p.get("url")}

    for url, p in new_products.items():
        if url not in old_products:
            changes.append(Change(
                change_type=ChangeType.NEW_PRODUCT, entity=name,
                field_name=p.get("product_name") or url,
                new_value=p.get("product_name") or url,
                detail=f"first seen on {url}",
                confidence=Confidence.MEDIUM, evidence=ev, detected_at=stamp))
            continue
        old = old_products[url]
        if old.get("status") != p.get("status") and p.get("status") != "unknown":
            changes.append(Change(
                change_type=ChangeType.PRODUCT_CHANGED, entity=name,
                field_name=f"{p.get('product_name') or url} availability",
                previous_value=old.get("status") or "unknown",
                new_value=p.get("status") or "unknown",
                confidence=Confidence.MEDIUM, evidence=ev, detected_at=stamp))

    old_feats = {f.get("product"): set(f.get("features") or [])
                 for f in (old_prof.get("features") or [])}
    for f in new_prof.get("features") or []:
        before = old_feats.get(f.get("product"))
        after = set(f.get("features") or [])
        if before is not None and after != before:
            added, gone = after - before, before - after
            bits = []
            if added:
                bits.append("added " + ", ".join(sorted(added)))
            if gone:
                bits.append("no longer stated: " + ", ".join(sorted(gone)))
            changes.append(Change(
                change_type=ChangeType.FEATURE_CHANGED, entity=name,
                field_name=f.get("product") or "",
                previous_value=", ".join(sorted(before)),
                new_value=", ".join(sorted(after)),
                detail="; ".join(bits),
                confidence=Confidence.MEDIUM, evidence=ev, detected_at=stamp))

    old_prices = {p.get("url"): p for p in (old_prof.get("pricing") or [])
                  if p.get("url")}
    for p in new_prof.get("pricing") or []:
        old = old_prices.get(p.get("url"))
        if not old:
            continue
        before, after = to_decimal(old.get("selling_price")), to_decimal(
            p.get("selling_price"))
        if not before or not after or before <= 0:
            continue
        move = abs(float((after - before) / before * 100))
        if move < PRICE_NOISE_PERCENT:
            continue
        if old.get("currency") != p.get("currency"):
            # Currency is never converted, so a currency switch is a change of
            # record rather than a price move, and is reported as such.
            changes.append(Change(
                change_type=ChangeType.PRODUCT_CHANGED, entity=name,
                field_name=f"{p.get('product')} currency",
                previous_value=str(old.get("currency")),
                new_value=str(p.get("currency")),
                detail="the page now prices in a different currency; the two "
                       "figures are not comparable",
                confidence=Confidence.MEDIUM, evidence=ev, detected_at=stamp))
            continue
        changes.append(Change(
            change_type=ChangeType.PRICE_CHANGED, entity=name,
            field_name=p.get("product") or p.get("url"),
            previous_value=str(old.get("selling_price")),
            new_value=str(p.get("selling_price")),
            detail=f"{move:.1f}% move in {p.get('currency')}",
            confidence=Confidence.HIGH, evidence=ev, detected_at=stamp))

    return changes


def diff_offers(previous_offers: dict, current_offers: list) -> list[Change]:
    """NEW_OFFER / OFFER_CHANGED / OFFER_EXPIRED.

    An offer whose status is UNKNOWN produces no change at all. Nothing happened
    that anyone established — the crawler simply could not see the page — and
    inventing an event out of that would be the exact failure the offers agent
    was separated out to prevent.
    """
    changes: list[Change] = []
    stamp = now_iso()
    prev = previous_offers or {}

    for offer in current_offers:
        d = offer.to_dict() if hasattr(offer, "to_dict") else dict(offer)
        key = d.get("offer_key")
        was = prev.get(key)
        ev = evidence_list(d.get("evidence") or [])
        label = f"{d.get('competitor')} — {d.get('offer_title')}"

        if d.get("status") == OfferStatus.UNKNOWN:
            continue
        if d.get("status") == OfferStatus.EXPIRED:
            if was and was.get("status") in OfferStatus.LIVE:
                changes.append(Change(
                    change_type=ChangeType.OFFER_EXPIRED,
                    entity=d.get("competitor") or "",
                    field_name=d.get("product") or "",
                    previous_value=d.get("offer_title") or "",
                    detail=d.get("change_note") or "",
                    confidence=d.get("confidence") or Confidence.MEDIUM,
                    evidence=ev, detected_at=stamp))
            continue
        if not was:
            changes.append(Change(
                change_type=ChangeType.NEW_OFFER,
                entity=d.get("competitor") or "",
                field_name=d.get("product") or "",
                new_value=d.get("offer_title") or "",
                detail=(f"{d.get('discount')} off, now {d.get('current_price')} "
                        f"{d.get('currency')}").strip(),
                confidence=d.get("confidence") or Confidence.UNVERIFIED,
                evidence=ev, detected_at=stamp))
        elif d.get("status") == OfferStatus.CHANGED:
            changes.append(Change(
                change_type=ChangeType.OFFER_CHANGED,
                entity=d.get("competitor") or "",
                field_name=d.get("product") or "",
                previous_value=(d.get("previous") or {}).get("current_price") or "",
                new_value=d.get("current_price") or "",
                detail=d.get("change_note") or "",
                confidence=d.get("confidence") or Confidence.UNVERIFIED,
                evidence=ev, detected_at=stamp))

    return changes


def expire(state: dict, cycle_id: str) -> tuple[dict, list[Change]]:
    """Subtract what has aged out.

    Returns the state with dormant competitors marked and the changes that
    records the demotion. Nothing is deleted: the point is that the report stops
    presenting it as current, not that the history is lost.
    """
    changes: list[Change] = []
    stamp = now_iso()
    for key, rec in (state.get("competitors") or {}).items():
        age = _age_days(rec.get("last_seen_at") or "")
        if age is None or age <= DORMANT_AFTER_DAYS:
            continue
        if rec.get("status") == "dormant":
            continue
        rec["status"] = "dormant"
        changes.append(Change(
            change_type=ChangeType.RELEVANCE_CHANGED,
            entity=rec.get("name") or key,
            field_name="status", previous_value="active", new_value="dormant",
            detail=(f"nothing has been read from this company for {age:.0f} days, "
                    f"so it is no longer presented as current"),
            confidence=Confidence.MEDIUM, detected_at=stamp))
    return state, changes


def summarise(changes: list[Change]) -> dict:
    out: dict[str, int] = {}
    for c in changes:
        out[c.change_type] = out.get(c.change_type, 0) + 1
    return dict(sorted(out.items(), key=lambda kv: ChangeType.WEIGHT.get(kv[0], 99)))
