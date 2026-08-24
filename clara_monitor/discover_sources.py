#!/usr/bin/env python
"""Run the discovery loop by hand.

    python -m clara_monitor.discover_sources                # both loops
    python -m clara_monitor.discover_sources --sources-only
    python -m clara_monitor.discover_sources --topics-only
    python -m clara_monitor.discover_sources --force        # ignore cooldowns
    python -m clara_monitor.discover_sources --report       # show, change nothing

Discovery is deliberately not part of a normal scan. Scanning is hourly and
cheap; discovery fetches unknown hosts and rewrites the taxonomy, so it runs on
a 24-hour cooldown and can always be inspected with `--report` before it is
allowed to act.

Nothing here trusts what it finds. A discovered feed becomes a candidate row with
its provenance; only a quality score above the configured threshold activates it,
and the reason is written down either way. Likewise a cluster of uncategorised
signals becomes a candidate subject; only the evidence gate and a corpus-wide
pattern test promote it.
"""

from __future__ import annotations

import argparse
import io
import sys
import time

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

from . import trend_sources as ts, trend_store
from .config import DB_PATH
from .discovery import DiscoveryConfig, DiscoveryStore
from .discovery.report import full_report
from .discovery.sources import run_source_discovery
from .discovery.topics import run_topic_discovery


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="clara_monitor.discover_sources")
    ap.add_argument("--sources-only", action="store_true")
    ap.add_argument("--topics-only", action="store_true")
    ap.add_argument("--force", action="store_true",
                    help="ignore the cooldowns")
    ap.add_argument("--report", action="store_true",
                    help="print the dashboard and change nothing")
    ap.add_argument("--run-id", default=None)
    args = ap.parse_args(argv)

    cfg = DiscoveryConfig.load()
    ds = DiscoveryStore(DB_PATH)
    tstore = trend_store.TrendStore(DB_PATH)
    run_id = args.run_id or f"disc{int(time.time()) % 100000}"

    try:
        ds.sync_seeds(ts.SOURCES)

        if args.report:
            print(full_report(ds, len(ts.SOURCES), len(ts.TOPICS)))
            return 0

        if not cfg.enabled:
            print("Discovery is disabled in the configuration "
                  "(discovery.enabled = false, or CLARA_DISCOVERY_ENABLED=0).")
            return 0

        print(f"Clara discovery — run {run_id}")
        print(f"  seeds: {len(ts.SOURCES)} feed(s), {len(ts.TOPICS)} topic "
              f"pattern(s) — never modified by this run")
        print("")

        did_anything = False

        # ---------------- sources ----------------
        if not args.topics_only and cfg.sources.enabled:
            ok, why = (True, "forced") if args.force else ds.cooled_down(
                "source_discovery", cfg.sources.cooldown_hours)
            print(f"  SOURCE DISCOVERY  ({why})")
            if not ok:
                print("    skipped — still cooling down")
            else:
                did_anything = True
                signals = tstore._all_signals()
                out = run_source_discovery(ds, signals, cfg=cfg, run_id=run_id,
                                           depth=1)
                st = out["stats"]
                print("")
                print(f"    domains considered : {st['domains_considered']}")
                print(f"    feed URLs proposed : {st['feeds_proposed']}")
                print(f"    feeds validated    : {st['validated']}")
                print(f"    failed validation  : {st['failed_validation']}")
                print(f"    activated          : {st['activated']}")
                print(f"    kept as candidates : {st['candidates']}")
                print(f"    rejected           : {st['rejected']}")
                print(f"    already known      : {st['rediscovered']}")
                print(f"    requests used      : {st['requests']}"
                      f"/{cfg.sources.max_discovery_requests}")
            print("")

        # ---------------- topics ----------------
        if not args.sources_only and cfg.topics.enabled:
            ok, why = (True, "forced") if args.force else ds.cooled_down(
                "topic_discovery", cfg.topics.cooldown_hours)
            print(f"  TOPIC DISCOVERY  ({why})")
            if not ok:
                print("    skipped — still cooling down")
            else:
                did_anything = True
                out = run_topic_discovery(ds, tstore, cfg=cfg, run_id=run_id)
                st = out["stats"]
                print("")
                print(f"    clusters meeting the gate : {st['clusters']}")
                print(f"    candidates recorded       : {st['candidates']}")
                print(f"    activated as new subjects : {st['activated']}")
                print(f"    merged into existing      : {st['merged']}")
                print(f"    rejected                  : {st['rejected']}")
                print(f"    uncategorised {out['before']} -> {out['after']} "
                      f"of {out['total']}")
            print("")

        if did_anything:
            print("=" * 68)
            print(full_report(ds, len(ts.SOURCES), len(ts.TOPICS)))
        return 0
    finally:
        tstore.close()
        ds.close()


if __name__ == "__main__":
    sys.exit(main())
