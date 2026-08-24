#!/usr/bin/env python
"""Sweep every competitor's storefront for what it is advertising.

    python run_offers.py                  # all registered competitors
    python run_offers.py --only dyson,ghd
    python run_offers.py --paths 6        # try more paths per brand

Different job from `run_agent.py`. The monitoring loop reads a competitor page
only while chasing a specific Clara product, which is why most competitors had no
offer data — nothing had ever pointed at them. This goes to each storefront
directly and reads what is promoted there, so coverage follows the registry rather
than the pairings.

A few hundred fetches, all through the guarded path: robots honoured, one honest
user agent, no credentials, and a refusal recorded rather than retried
differently. Takes minutes, not an hour.

Results are stored so the competitors page can show them, and every line keeps
the URL it was read from.
"""

from __future__ import annotations

import argparse
import io
import json
import sys
import time

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

from clara_monitor import competitors as comp
from clara_monitor.agents.offer_sweep import OfferSweepAgent
from clara_monitor.agents.offer_store import OfferStore
from clara_monitor.config import DB_PATH, REPORT_DIR


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default=None,
                    help="comma-separated competitor keys")
    ap.add_argument("--paths", type=int, default=4,
                    help="how many paths to try per brand (default 4)")
    ap.add_argument("--json", default=None)
    args = ap.parse_args()

    keys = ([k.strip() for k in args.only.split(",") if k.strip()]
            if args.only else sorted(comp.REGISTRY))

    print(f"Clara offer sweep — {len(keys)} competitor(s), "
          f"up to {args.paths} path(s) each")
    print("  every fetch goes through the guarded path; a refusal is recorded, "
          "never worked around")
    print("")

    t0 = time.time()
    agent = OfferSweepAgent()
    result = agent.run(keys, max_paths=args.paths)

    store = OfferStore(DB_PATH)
    try:
        summary = store.record(result)
    finally:
        store.close()

    c = result["counts"]
    print(f"  swept in {time.time() - t0:.0f}s")
    print(f"    storefronts read       : {c['storefronts_read']}/"
          f"{c['competitors_tried']}")
    print(f"    advertising something  : {c['competitors_advertising']}")
    print(f"    offer lines collected  : {c['offer_lines']} "
          f"({summary['new']} new since the last sweep)")
    print(f"    refused every path     : {c['refused']}")
    print(f"    verifiable discounts   : {c['verifiable_discounts']} "
          f"(a banner claim is not a before-and-after pair)")

    if result["mechanisms"]:
        print("\n  by mechanism:")
        for k, v in result["mechanisms"].items():
            print(f"    {k:16} {v}")

    if result["with_offers"]:
        print(f"\n  advertising now ({len(result['with_offers'])}):")
        for brand in result["with_offers"]:
            lines = [o for o in result["offers"] if o["competitor"] == brand]
            print(f"    {brand[:22]:24} {len(lines)} line(s)")
            for o in lines[:2]:
                print(f"        [{o['mechanism']}] {o['wording'][:78]}")

    if result["blocked"]:
        print(f"\n  refused ({len(result['blocked'])}):")
        for b in result["blocked"]:
            print(f"    {b['competitor'][:22]:24} {b['signal']}")

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    path = args.json or (REPORT_DIR / "offer_sweep.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2, default=str)
    print(f"\n  written: {path}")
    print("  on the site: http://127.0.0.1:8770/#live")
    return 0


if __name__ == "__main__":
    sys.exit(main())
