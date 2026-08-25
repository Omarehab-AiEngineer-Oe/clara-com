#!/usr/bin/env python
"""Run one live trend scan.

    python run_trends.py              # fetch every registered feed
    python run_trends.py --scan s7    # name the scan

Unlike a competitor monitoring run, this is fast — a few dozen public feeds, a
minute or two — so it is safe to schedule hourly. It contacts only sources that
publish a feed, through the same guarded path as everything else: robots
respected, one honest user agent, no credentials, refusals recorded as refusals.

Run it repeatedly. The value is cumulative: a single scan sees one recent window
per feed, and the stages only become meaningful once there is a before to compare
against.
"""

from __future__ import annotations

import argparse
import io
import sys
import time

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

from clara_monitor import trend_sources as ts, trend_store
from clara_monitor.agents.trend_collector import TrendCollectionAgent
from clara_monitor.config import DB_PATH


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--scan", default=None, help="scan id; defaults to the next s<N>")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    store = trend_store.TrendStore(DB_PATH)
    try:
        scan_id = args.scan or f"s{store.scan_count() + 1}"
        print(f"Clara trend scan — {scan_id}")
        print(f"  {len(ts.SOURCES)} feeds registered, "
              f"{len(ts.REFUSED)} known refusals, {len(ts.DEAD)} dead feeds")
        print("")

        t0 = time.time()
        agent = TrendCollectionAgent()
        result = agent.run(store, scan_id)
        summary = store.record(result)

        took = time.time() - t0
        c = result["counts"]
        print(f"  read {c['feeds_read']} of {c['feeds_tried']} feeds in {took:.0f}s")
        print(f"  {c['signals']} beauty signals this scan, "
              f"{summary['new_signals']} of them new")
        print(f"  {summary['total_signals']} signals held in total")
        print(f"  {summary['topics']} topics have evidence")

        if not args.quiet:
            blocked = [s for s in result["sources"] if not s["ok"]]
            if blocked:
                print(f"\n  could not read {len(blocked)}:")
                for s in blocked:
                    print(f"    {s['publisher'][:30]:32} {s['signal'] or 'no signal'}")

            if summary["changes"]:
                print(f"\n  what moved ({len(summary['changes'])}):")
                for ch in summary["changes"][:20]:
                    print(f"    {ch['kind']:14} {ch['topic'][:30]:32} {ch['note'][:60]}")
            else:
                print("\n  nothing moved since the last scan — a valid result")

        return 0
    finally:
        store.close()


if __name__ == "__main__":
    sys.exit(main())
