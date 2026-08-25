#!/usr/bin/env python
"""Update everything, in the order the dependencies actually run.

    python run_all.py                 # trends + intelligence cycle
    python run_all.py --monitor       # also re-read competitor pages (slow)
    python run_all.py --targets 3

Three jobs with very different costs, which is why they are separate commands
underneath and only chained here:

    trend scan   ~1-3 min   public feeds, safe to run hourly
    intel cycle  <1 sec     reads stored evidence, contacts nothing
    monitoring   ~1 hour    contacts competitor sites, bound by the access policy

The order matters. The monitoring run produces the observations, the trend scan
produces the market signals, and the intelligence cycle compares both against the
previous state — so it runs last or it compares against yesterday's evidence.

`--monitor` is off by default. An hour-long crawl should be something you ask for,
not something a convenience wrapper does because it was next in a list.

For a schedule, this is the command to point at:

    Windows   schtasks /create /tn ClaraHourly /tr "python D:\\clara project\\run_all.py" /sc hourly
    cron      0 * * * * cd /path/to/clara && python run_all.py
"""

from __future__ import annotations

import argparse
import io
import json
import subprocess
import sys
import time

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

from clara_monitor import catalog, competitors as comp, trend_store
from clara_monitor.agents.orchestrator import Orchestrator
from clara_monitor.agents.trend_collector import TrendCollectionAgent
from clara_monitor.config import DB_PATH, REPORT_DIR
from clara_monitor.llm import judge_singleton
from clara_monitor.store import Store


def rule(title: str) -> None:
    print("")
    print(f"  {title}")
    print("  " + "-" * (len(title) + 2))


def do_monitor(run_id: str, targets: int) -> None:
    rule(f"1. Monitoring run {run_id} — contacting competitor sites")
    print("     This is the slow one. Every fetch goes through the guarded path;")
    print("     a page that refuses is escalated, never worked around.")
    r = subprocess.run([sys.executable, "run_agent.py", "--run-id", run_id,
                        "--targets", str(targets)], cwd=".")
    print(f"     exit {r.returncode}")


def do_trends() -> dict:
    rule("Trend scan — reading public feeds")
    st = trend_store.TrendStore(DB_PATH)
    try:
        scan_id = f"s{st.scan_count() + 1}"
        t0 = time.time()
        result = TrendCollectionAgent().run(st, scan_id)
        summary = st.record(result)
        c = result["counts"]
        print(f"     {scan_id}: read {c['feeds_read']}/{c['feeds_tried']} feeds in "
              f"{time.time() - t0:.0f}s")
        print(f"     {summary['new_signals']} new signal(s), "
              f"{summary['total_signals']} held, {summary['topics']} topics")
        if summary["changes"]:
            print(f"     moved ({len(summary['changes'])}):")
            for ch in summary["changes"][:12]:
                print(f"       {ch['kind']:14} {ch['topic'][:32]:34} "
                      f"{ch['note'][:52]}")
        else:
            print("     nothing moved — a valid result")
        return summary
    finally:
        st.close()


def do_discovery(force: bool = False) -> dict:
    """Publisher and topic discovery, on their own cooldowns.

    Kept out of the default run on purpose. Scanning is hourly and cheap;
    discovery fetches unknown hosts and rewrites the taxonomy, so it runs once a
    day and only when asked. Both loops are bounded and both record why they did
    what they did.
    """
    rule("Discovery — publishers and subjects")
    from clara_monitor.discover_sources import main as discover
    argv = ["--force"] if force else []
    code = discover(argv)
    print(f"     exit {code}")
    return {"exit": code}


def do_cycle(run_id: str) -> dict:
    rule("Intelligence cycle — comparing against the previous state")
    store = Store(DB_PATH)
    try:
        for c in comp.REGISTRY.values():
            store.upsert_competitor(c)
        orch = Orchestrator(store, DB_PATH, llm=judge_singleton(), verbose=False)
        try:
            cid = f"c{orch.intel.snapshot_count() + 1}"
            out = orch.run(cid, run_id, catalog.load_from_seed())
            REPORT_DIR.mkdir(parents=True, exist_ok=True)
            with open(REPORT_DIR / f"intel_{cid}.json", "w", encoding="utf-8") as f:
                json.dump(out, f, ensure_ascii=False, indent=2, default=str)
            s = out["summary"]
            print(f"     {cid}: {s['competitors_tracked']} competitors, "
                  f"{s['new']} new, {s['changed']} changed, "
                  f"{s['removed']} gone")
            print(f"     offers: {s['offers_live']} live, "
                  f"{s['offers_expired']} ended, {s['offers_unknown']} unconfirmed")
            print(f"     {s['findings']} finding(s), {s['actions']} action(s)")
            if s["changes_by_type"]:
                for k, v in s["changes_by_type"].items():
                    print(f"       {k:22} {v}")
            else:
                print("       no competitor change this cycle")
            return s
        finally:
            orch.close()
    finally:
        store.close()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-id", default=None,
                    help="monitoring run to read from; defaults to the latest")
    ap.add_argument("--monitor", action="store_true",
                    help="also re-read competitor pages (about an hour)")
    ap.add_argument("--targets", type=int, default=2)
    ap.add_argument("--skip-trends", action="store_true")
    ap.add_argument("--discover-sources", action="store_true",
                    help="also run publisher and topic discovery (respects "
                         "the 24h cooldowns unless --force-discovery)")
    ap.add_argument("--force-discovery", action="store_true")
    args = ap.parse_args()

    store = Store(DB_PATH)
    try:
        run_id = args.run_id or store.latest_run_id() or "r1"
    finally:
        store.close()

    print("Clara — updating everything")
    print(f"  evidence run: {run_id}")
    status = judge_singleton().model_status()
    print(f"  model: {status['configured_model']} "
          + ("available" if status.get("available")
             else "unavailable — the deterministic path runs and the pages say so"))

    t0 = time.time()
    if args.monitor:
        do_monitor(run_id if args.run_id else f"r{int(time.time()) % 10000}",
                   args.targets)
    if not args.skip_trends:
        do_trends()
    if args.discover_sources:
        do_discovery(force=args.force_discovery)
    do_cycle(run_id)

    print("")
    print(f"  done in {time.time() - t0:.0f}s. Both pages now reflect this update:")
    print("    http://127.0.0.1:8770/         competitors, offers, next steps")
    print("    http://127.0.0.1:8770/trends   live trends")
    return 0


if __name__ == "__main__":
    sys.exit(main())
