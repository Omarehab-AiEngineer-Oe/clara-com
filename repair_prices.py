#!/usr/bin/env python
"""Re-derive stored prices from their preserved raw text.

A price-parsing defect (a regex alternation that read "2299" as a 9-to-229 range)
produced wrong derived values in observations already written. §11 requires the
raw price text to be kept alongside the normalized decimal, and that is what makes
this recoverable without re-reading a single competitor page.

What this touches:
  * `observation` — the current snapshot the reports read: re-parsed in place.
  * `observation_history` — insert-only by design (§15); left untouched. Its rows
    still carry their raw text, so they can be re-derived the same way if needed.

Every repaired row gets a note saying so, so the correction is visible in the
reports rather than silent.

    python repair_prices.py            # report what would change
    python repair_prices.py --apply
"""

from __future__ import annotations

import argparse
import io
import json
import sqlite3
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from clara_monitor.config import DB_PATH
from clara_monitor.money import discount, parse_price

NOTE = ("price re-derived from the preserved raw text after a price-parsing fix; "
        "no competitor page was re-read")


def rederive(payload: dict) -> tuple[dict, list[str]]:
    changes: list[str] = []
    cur = dict(payload)
    currency = cur.get("currency")

    sell_raw = cur.get("selling_price_raw")
    if sell_raw:
        p = parse_price(sell_raw, currency)
        before = (cur.get("selling_price"), cur.get("price_is_range"),
                  cur.get("price_min"), cur.get("price_max"))
        after = (str(p.amount) if p.amount is not None else None,
                 p.is_range,
                 str(p.minimum) if p.minimum is not None else None,
                 str(p.maximum) if p.maximum is not None else None)
        if before != after:
            changes.append(f"selling {before[0]!r}/range={before[1]} -> "
                           f"{after[0]!r}/range={after[1]}")
        cur["selling_price"], cur["price_is_range"] = after[0], after[1]
        cur["price_min"], cur["price_max"] = after[2], after[3]
        cur["price_from"] = p.from_price

    reg_raw = cur.get("regular_price_raw") or None
    reg = parse_price(reg_raw, currency).amount if reg_raw else None
    if reg is None and cur.get("regular_price"):
        reg = parse_price(str(cur["regular_price"]), currency).amount
    sell = parse_price(str(cur["selling_price"]), currency).amount \
        if cur.get("selling_price") else None

    amt, pct, notes = discount(reg, sell)
    old_pct = cur.get("discount_percent")
    new_pct = str(pct) if pct is not None else None
    if old_pct != new_pct:
        changes.append(f"discount_percent {old_pct!r} -> {new_pct!r}")
    cur["regular_price"] = str(reg) if reg is not None else None
    cur["discount_amount"] = str(amt) if amt is not None else None
    cur["discount_percent"] = new_pct

    if changes:
        w = list(cur.get("warnings") or [])
        w.append(NOTE)
        cur["warnings"] = w + [n for n in notes if n not in w]
    return cur, changes


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    rows = db.execute("SELECT clara_product_id, competitor_key, payload "
                      "FROM observation").fetchall()

    touched = 0
    for r in rows:
        try:
            payload = json.loads(r["payload"])
        except json.JSONDecodeError:
            continue
        fixed, changes = rederive(payload)
        if not changes:
            continue
        touched += 1
        print(f"{r['clara_product_id']} x {r['competitor_key']}: "
              + "; ".join(changes))
        if args.apply:
            db.execute("UPDATE observation SET payload=? "
                       "WHERE clara_product_id=? AND competitor_key=?",
                       (json.dumps(fixed, ensure_ascii=False),
                        r["clara_product_id"], r["competitor_key"]))
    if args.apply:
        db.commit()
    db.close()

    print(f"\n{touched} of {len(rows)} observation(s) "
          f"{'repaired' if args.apply else 'would change'}")
    if not args.apply and touched:
        print("re-run with --apply to write the corrections")
    return 0


if __name__ == "__main__":
    sys.exit(main())
