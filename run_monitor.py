#!/usr/bin/env python
"""Run the monitor without the LLM: same pipeline, deterministic discovery.

    python run_monitor.py --run-id 2026-08-17-a
    python run_monitor.py --run-id 2026-08-17-b --live-refresh
    python run_monitor.py --report-only --run-id 2026-08-17-a
"""

from __future__ import annotations

import argparse
import io
import json
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from clara_monitor import catalog, report, site
from clara_monitor.config import DB_PATH, RunConfig
from clara_monitor.matching import SeedSearchProvider
from clara_monitor.pipeline import run as run_pipeline
from clara_monitor.store import Store


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--live-refresh", action="store_true",
                    help="re-read the Clara catalog from clarahair.com first")
    ap.add_argument("--report-only", action="store_true",
                    help="rebuild reports and the site from an existing run")
    ap.add_argument("--ttl-days", type=int, default=30)
    ap.add_argument("--discovery-budget", type=int, default=6)
    ap.add_argument("--inline-images", action="store_true",
                    help="inline thumbnails as data URIs so the page is "
                         "self-contained")
    args = ap.parse_args()

    cfg = RunConfig(run_id=args.run_id, ttl_days=args.ttl_days,
                    discovery_budget=args.discovery_budget)

    if not args.report_only:
        products = catalog.load_from_seed(scope=cfg.scope_product_ids)
        print(f"[scope] {len(products)} Clara device(s) in scope")
        if args.live_refresh:
            products, problems = catalog.refresh_from_site(products)
            for pr in problems:
                print(f"[catalog] {pr['product_id']}: {pr['kind']} — {pr['signal']}")
        for p in products:
            print(f"  {p.product_id:14} {p.fmt:20} lang={p.description_lang:8} {p.name}")

        result = run_pipeline(cfg, products, SeedSearchProvider())
        print("\n[run] summary:", json.dumps(result["summary"], indent=1))
        for o in result["outcomes"]:
            print(f"  {o['status']:16} {o['path']:20} score={o['score']:<6} "
                  f"{o['clara_name']} x {o['competitor_key']}")

    store = Store(DB_PATH)
    try:
        bundle = report.build_all(store, args.run_id)
    finally:
        store.close()

    out = site.write_site(bundle, inline_images=args.inline_images)
    cov = bundle["coverage"]
    print(f"\n[coverage] {cov['pairs_total']} pair(s): {cov['by_status']}")
    print(f"[coverage] products without a valid match: "
          f"{len(cov['products_without_valid_match'])}")
    print(f"[changes]  {bundle['changes']['total']} "
          f"({bundle['changes']['flagged']} flagged)")
    print(f"[except]   {bundle['exceptions']['total']} -> {bundle['exceptions']['by_kind']}")
    print(f"[site]     {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
