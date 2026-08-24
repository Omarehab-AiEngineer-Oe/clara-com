#!/usr/bin/env python
"""Run the Autonomous Competitor Intelligence Agent (§16 manual run command).

    python run_agent.py --run-id r1                       # full catalog
    python run_agent.py --run-id r1 --targets 2           # cap competitors per product
    python run_agent.py --run-id r1 --no-llm              # deterministic only
    python run_agent.py --run-id r1 --resume              # continue an open run
    python run_agent.py --run-id r1 --report-only         # rebuild reports + site
"""

from __future__ import annotations

import argparse
import io
import json
import sys
import time

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

from clara_monitor import catalog, competitors as comp, engine, reporting, site
from clara_monitor.config import DB_PATH, RunConfig
from clara_monitor.store import Store


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--targets", type=int, default=None,
                    help="max assigned competitors evaluated per Clara product")
    ap.add_argument("--discovery-budget", type=int, default=3)
    ap.add_argument("--ttl-days", type=int, default=30)
    ap.add_argument("--devices-only", action="store_true",
                    help="restrict the run to the device lineup")
    ap.add_argument("--no-llm", action="store_true",
                    help="deterministic scoring only; do not call Vertex AI")
    ap.add_argument("--live-refresh", action="store_true",
                    help="re-crawl clarahair.com before running")
    ap.add_argument("--resume", action="store_true")
    ap.add_argument("--report-only", action="store_true")
    ap.add_argument("--inline-images", action="store_true", default=True)
    args = ap.parse_args()

    cfg = RunConfig(run_id=args.run_id, ttl_days=args.ttl_days,
                    discovery_budget=args.discovery_budget)

    if not args.report_only:
        scope = cfg.scope_product_ids if args.devices_only else None
        products = catalog.load_from_seed(scope=scope)
        if args.live_refresh:
            products, problems = catalog.refresh_from_site(products)
            for pr in problems:
                print(f"[catalog] {pr['product_id']}: {pr['kind']} - {pr['signal']}")

        segs: dict[str, int] = {}
        for p in products:
            segs[p.segment] = segs.get(p.segment, 0) + 1
        print(f"[scope]  {len(products)} Clara products: {segs}")
        print(f"[comp]   {len(comp.REGISTRY)} competitors registered")

        planned = sum(len(comp.targets_for(p.fmt, p.category, p.segment,
                                           limit=args.targets)) for p in products)
        print(f"[plan]   {planned} product x competitor pairs "
              f"(targets cap = {args.targets})")

        t0 = time.time()
        result = engine.run(cfg, products, targets_limit=args.targets,
                            use_llm=not args.no_llm, resume=args.resume)
        dt = time.time() - t0
        print(f"\n[run]    finished in {dt/60:.1f} min")
        print("[summary]", json.dumps(result["summary"], indent=1, default=str))

    store = Store(DB_PATH)
    try:
        bundle = reporting.build_all(store, args.run_id)
    finally:
        store.close()

    out = site.write_site(bundle, inline_images=args.inline_images)
    pr, cv, ch, es = (bundle["price"], bundle["coverage"],
                      bundle["changes"], bundle["escalations"])
    print(f"[price]  {pr['catalog_size']} products, "
          f"{pr['products_with_a_match']} with a match, "
          f"{pr['comparable_price_pairs']} comparable price pairs")
    print(f"         Clara band {pr['clara_price_min']}-{pr['clara_price_max']} "
          f"(median {pr['clara_price_median']})")
    print(f"[cover]  {cv['pairs_total']} pairs: {cv['by_status']}")
    print(f"[change] {ch['total']} ({ch['flagged']} flagged); "
          f"events {ch['match_event_counts']}")
    print(f"[escal]  {es['total']} -> {es['by_kind']}; errors {es['error_count']}")
    print(f"[site]   {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
