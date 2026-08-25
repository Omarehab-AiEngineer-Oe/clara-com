#!/usr/bin/env python
"""Run one competitor-intelligence cycle.

    python run_intel.py                     # a cycle from stored evidence
    python run_intel.py --cycle c2          # name the cycle
    python run_intel.py --live-discovery    # also read brand index pages

A cycle is not a monitoring run. The monitoring run (`run_agent.py`) is what
contacts competitor sites and takes about an hour; this reads what that produced,
computes the new state against the previous one, and returns the structured
intelligence. Running it twice in a row is safe and is in fact the point — the
second run should report far fewer changes than the first, and if it does not,
something is being recomputed rather than compared.

`--live-discovery` is the only flag that touches the network, and it does so
through the same guarded path as everything else: robots respected, one honest
user agent, no credentials, and a blocked host escalated to a person rather than
retried differently.
"""

from __future__ import annotations

import argparse
import io
import json
import sys
import time

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

from clara_monitor import catalog, competitors as comp
from clara_monitor.agents.orchestrator import Orchestrator
from clara_monitor.config import DB_PATH, REPORT_DIR
from clara_monitor.llm import judge_singleton
from clara_monitor.store import Store

# Brand index pages, used only with --live-discovery. Every host here is already
# in the access allowlist; the fetch still goes through robots and the block
# checks, and a refusal is reported rather than worked around.
BRAND_INDEX_URLS = [
    "https://www.dyson.sa/hair-care",
    "https://laifen.sa/collections/all",
    "https://www.ghdhair.com/hair-straighteners",
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cycle", default=None,
                    help="cycle id; defaults to the next c<N>")
    ap.add_argument("--run-id", default=None,
                    help="monitoring run to read evidence from; defaults to latest")
    ap.add_argument("--live-discovery", action="store_true",
                    help="also read brand index pages through the guarded path")
    ap.add_argument("--no-llm", action="store_true",
                    help="skip Vertex entirely and run the rules path only")
    ap.add_argument("--json", default=None, help="write the final output here")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    store = Store(DB_PATH)
    try:
        for c in comp.REGISTRY.values():
            store.upsert_competitor(c)

        run_id = args.run_id or store.latest_run_id() or "r1"
        products = catalog.load_from_seed()

        llm = None if args.no_llm else judge_singleton()
        orch = Orchestrator(store, DB_PATH, llm=llm, verbose=not args.quiet)

        cycle = args.cycle or f"c{orch.intel.snapshot_count() + 1}"

        print(f"Clara competitor intelligence — cycle {cycle}")
        print(f"  evidence from monitoring run: {run_id}")
        if llm is not None:
            status = llm.model_status()
            if status.get("available"):
                print(f"  model: {status['configured_model']} on Vertex "
                      f"({status['location']})")
            else:
                print(f"  model: unavailable — "
                      f"{(status.get('unavailable_reason') or '')[:90]}")
                print("         every agent runs its deterministic path and says so")
        else:
            print("  model: skipped by --no-llm")
        print("")

        t0 = time.time()
        try:
            out = orch.run(cycle, run_id, products,
                           live_discovery=args.live_discovery,
                           brand_index_urls=BRAND_INDEX_URLS)
        finally:
            orch.close()

        s = out["summary"]
        print("")
        print(f"  cycle {cycle} finished in {time.time() - t0:.1f}s")
        print(f"    competitors tracked : {s['competitors_tracked']}")
        print(f"    new / changed / gone: {s['new']} / {s['changed']} / {s['removed']}")
        print(f"    offers live         : {s['offers_live']} "
              f"(expired {s['offers_expired']}, unknown {s['offers_unknown']})")
        print(f"    findings / actions  : {s['findings']} / {s['actions']}")
        if s["changes_by_type"]:
            print("    changes:")
            for k, v in s["changes_by_type"].items():
                print(f"      {k:22} {v}")
        else:
            print("    changes: none — a cycle with no changes is a valid cycle")

        path = args.json or (REPORT_DIR / f"intel_{cycle}.json")
        REPORT_DIR.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=2, default=str)
        print(f"\n  written: {path}")
        return 0
    finally:
        store.close()


if __name__ == "__main__":
    sys.exit(main())
