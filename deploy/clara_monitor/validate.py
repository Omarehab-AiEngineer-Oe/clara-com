"""Do the stored notes agree with the stored data?

A warning is a claim about a record, and it can go stale exactly like a price
can. This module checks that every note on an observation is still true of the
data beside it, because a note that contradicts its own row is worse than no
note: a reader trusts it, and it is the part of the record that says how far the
rest can be trusted.

The defect this was written for. `repair_prices.py` re-derived prices after a
parsing bug that read "2299" as a 9-to-229 range. It corrected the values and
then carried the OLD warnings forward, so 17 observations ended up saying

    price shown as a range; min and max kept, no midpoint computed

beside `price_is_range = false` and `price_min = price_max = null`. The note
described the bug that had just been fixed. Nothing in the system could notice,
because nothing was checking notes against data — only data against sources.

Two rules make this tractable.

**A note that belongs to a derivation must be re-derived with it.** Price notes
come from `parse_price` and `discount`. When a price is re-parsed, the previous
parse's notes are superseded and have to be dropped, not merged. Notes from other
extractors — stock wording, images — are about other fields and survive.

**Repair states what it changed.** A cleanup that silently rewrites warnings is
the same class of mistake as the one it is cleaning up, so every repair records
what it removed and why.
"""

from __future__ import annotations

import json
import sqlite3

# Notes produced by the price derivation. These are the ones that must be
# re-derived with the price rather than carried across it.
PRICE_NOTES = (
    "empty price text",
    "no numeric value found in price text; raw text preserved",
    "price shown as a range; min and max kept, no midpoint computed",
    "'from' price: applies to the cheapest variant only",
    "regular price is not positive; no discount computed",
)

# `discount` builds one note with the two prices interpolated, so it is matched
# by prefix rather than by equality.
PRICE_NOTE_PREFIXES = ("selling price ",)

# The repair note itself. Kept, because it is a fact about the row's history.
REPAIR_NOTE_PREFIX = "price re-derived from the preserved raw text"


def is_price_note(note: str) -> bool:
    """Whether a note came from the price derivation and travels with it."""
    note = (note or "").strip()
    if note in PRICE_NOTES:
        return True
    return any(note.startswith(p) for p in PRICE_NOTE_PREFIXES)


def check(payload: dict) -> list[dict]:
    """Contradictions between what a payload says and what it holds.

    Each finding names the note, what the data actually says, and whether the
    note can be dropped safely — which it can only be when the data is
    unambiguous. A note contradicted by data that is itself missing is reported
    and left alone: that is a collection problem, not a stale note.
    """
    out = []
    notes = list(payload.get("warnings") or [])
    is_range = bool(payload.get("price_is_range"))
    pmin, pmax = payload.get("price_min"), payload.get("price_max")
    amount = payload.get("selling_price")

    for note in notes:
        if note == "price shown as a range; min and max kept, no midpoint computed":
            if not is_range and pmin is None and pmax is None:
                out.append({
                    "note": note,
                    "field": "price_is_range",
                    "says": "the price was a range and both ends were kept",
                    "data": f"price_is_range is false and both ends are null; "
                            f"a single price {amount!r} is recorded",
                    "verdict": "stale",
                    "why": "the price was re-derived after the range-parsing "
                           "defect and came out as one value, so this note "
                           "describes the parse that was replaced",
                })
            elif is_range and (pmin is None or pmax is None):
                out.append({
                    "note": note,
                    "field": "price_min/price_max",
                    "says": "both ends of the range were kept",
                    "data": f"price_min={pmin!r} price_max={pmax!r}",
                    "verdict": "contradicted",
                    "why": "the note claims both ends were kept and one is "
                           "missing, so the range itself is not trustworthy "
                           "and a person has to look",
                })

        if note == "'from' price: applies to the cheapest variant only":
            if not payload.get("price_from"):
                out.append({
                    "note": note,
                    "field": "price_from",
                    "says": "the page stated a 'from' price",
                    "data": "price_from is false",
                    "verdict": "stale",
                    "why": "re-derived without the 'from' marker, so the note "
                           "belongs to the superseded parse",
                })

        if note == "no numeric value found in price text; raw text preserved":
            if amount not in (None, ""):
                out.append({
                    "note": note,
                    "field": "selling_price",
                    "says": "no number could be read from the price text",
                    "data": f"selling_price is {amount!r}",
                    "verdict": "stale",
                    "why": "a value was read on the later parse, so the note "
                           "describes the parse that failed",
                })

        if note.startswith("selling price ") and "exceeds regular price" in note:
            reg, sell = payload.get("regular_price"), amount
            try:
                if reg is not None and sell is not None \
                        and float(sell) <= float(reg):
                    out.append({
                        "note": note,
                        "field": "regular_price",
                        "says": "the selling price exceeded the regular price",
                        "data": f"selling {sell!r} <= regular {reg!r}",
                        "verdict": "stale",
                        "why": "the disagreement is gone after re-derivation",
                    })
            except (TypeError, ValueError):
                pass
    return out


def repair(payload: dict) -> tuple[dict, list[dict]]:
    """Drop the notes that are stale. Leave the contradicted ones alone.

    A stale note describes a derivation that has been replaced and can go. A
    contradicted one means the data disagrees with itself, and deleting the note
    would hide that rather than fix it — so it stays and is reported.
    """
    findings = check(payload)
    stale = {f["note"] for f in findings if f["verdict"] == "stale"}
    if not stale:
        return payload, findings
    out = dict(payload)
    out["warnings"] = [w for w in (payload.get("warnings") or [])
                       if w not in stale]
    return out, findings


def scan(db_path, *, apply: bool = False) -> dict:
    """Check every stored observation. With `apply`, repair the stale notes."""
    db = sqlite3.connect(str(db_path))
    db.row_factory = sqlite3.Row
    try:
        rows = db.execute("SELECT clara_product_id, competitor_key, payload "
                          "FROM observation").fetchall()
        checked = repaired = 0
        stale_n = contradicted_n = 0
        detail = []
        for r in rows:
            try:
                payload = json.loads(r["payload"])
            except json.JSONDecodeError:
                continue
            checked += 1
            fixed, findings = repair(payload)
            if not findings:
                continue
            stale_n += sum(1 for f in findings if f["verdict"] == "stale")
            contradicted_n += sum(1 for f in findings
                                  if f["verdict"] == "contradicted")
            detail.append({"product": r["clara_product_id"],
                           "competitor": r["competitor_key"],
                           "findings": findings})
            if fixed is not payload:
                repaired += 1
                if apply:
                    db.execute(
                        "UPDATE observation SET payload=? "
                        "WHERE clara_product_id=? AND competitor_key=?",
                        (json.dumps(fixed, ensure_ascii=False),
                         r["clara_product_id"], r["competitor_key"]))
        if apply:
            db.commit()
        return {"checked": checked, "rows_with_findings": len(detail),
                "stale": stale_n, "contradicted": contradicted_n,
                "repaired": repaired, "applied": apply, "detail": detail}
    finally:
        db.close()


def _main(argv=None) -> int:
    """`python -m clara_monitor.validate [--apply]`"""
    import argparse
    import sys

    from .config import DB_PATH

    ap = argparse.ArgumentParser(
        description="Check stored notes against the data beside them.")
    ap.add_argument("--apply", action="store_true",
                    help="drop the notes that are stale")
    args = ap.parse_args(argv)

    r = scan(DB_PATH, apply=args.apply)
    for row in r["detail"]:
        print(f"{row['product']} x {row['competitor']}")
        for f in row["findings"]:
            print(f"  {f['verdict']:13} {f['note']}")
            print(f"  {'':13} data: {f['data']}")
            print(f"  {'':13} why : {f['why']}")
    print("")
    print(f"{r['checked']} observation(s) checked")
    print(f"{r['stale']} stale note(s), {r['contradicted']} contradiction(s)")
    if r["applied"]:
        print(f"{r['repaired']} row(s) repaired")
    elif r["stale"]:
        print("re-run with --apply to drop the stale notes")
    if r["contradicted"]:
        print("contradictions are NOT repaired: the data disagrees with itself, "
              "and deleting the note would hide that rather than fix it")
    return 1 if r["contradicted"] else 0


if __name__ == "__main__":
    import sys
    sys.exit(_main())
