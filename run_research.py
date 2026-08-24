#!/usr/bin/env python
"""Run the six research agents and write the executive report.

    python run_research.py                  # report from stored evidence
    python run_research.py --news-days 60   # narrow the news window
    python run_research.py --md reports/executive_report.md

Reads what the monitoring runs and trend scans already collected; contacts
nothing itself, so it takes about a second. Deepening it is a matter of running
the collectors longer, not of running this again:

    python run_agent.py --targets 8     more competitors get observed prices
    python run_trends.py                more dated news reaches the news agent

Every field in the output carries how it is known — OBSERVED, EDITORIAL or
NOT_ESTABLISHED — and the report prints that. There is no code path that produces
a revenue estimate, a market share, or a price for a competitor whose page was
never read, so no run can accidentally report one.
"""

from __future__ import annotations

import argparse
import io
import json
import sys
import time

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

from clara_monitor.agents import research as R
from clara_monitor.agents.research_report import build_report, to_markdown
from clara_monitor.config import DB_PATH, REPORT_DIR
from clara_monitor.llm import judge_singleton
from clara_monitor.store import Store


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--news-days", type=int, default=90)
    ap.add_argument("--json", default=None)
    ap.add_argument("--md", default=None)
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    llm = judge_singleton()
    status = llm.model_status()

    print("Clara competitive research — six agents")
    print(f"  model: {status['configured_model']} "
          + ("available" if status.get("available")
             else "unavailable, so every agent ran its deterministic path"))
    print("")

    store = Store(DB_PATH)
    t0 = time.time()
    try:
        agents = {}

        def run(cls, *a, **kw):
            agent = cls(llm=llm)
            out = agent.run(*a, **kw)
            agents[agent.name] = agent.report.to_dict()
            if not args.quiet:
                label = agent.name.replace("research_", "").replace("_", " ")
                print(f"  {label:26} {agent.report.items_out:4} item(s)")
                for note in agent.report.notes:
                    if note.startswith("took "):
                        continue
                    print(f"      {note}")
            return out

        discovery = run(R.CompetitorDiscoveryResearchAgent, store)
        clara = run(R.ClaraProductPricingAgent, store)
        pricing = run(R.CompetitorPricingOffersAgent, store)
        news = run(R.CompetitorNewsAgent, store, days=args.news_days)
        offers = run(R.OfferNegotiationAgent, store)
        comparison = run(R.CompetitiveComparisonAgent, store, discovery, clara,
                         pricing, news, offers)
    finally:
        store.close()

    report = build_report(discovery=discovery, clara=clara, pricing=pricing,
                          news=news, offers=offers, comparison=comparison,
                          agents=agents, model_status=status)

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    json_path = args.json or (REPORT_DIR / "executive_report.json")
    md_path = args.md or (REPORT_DIR / "executive_report.md")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2, default=str)
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(to_markdown(report))

    s = report["summary"]
    print("")
    print(f"  finished in {time.time() - t0:.1f}s")
    print(f"    competitors            : {s['competitors']} "
          f"({s['competitors_with_observed_prices']} with an observed price)")
    print(f"    Clara products         : {s['clara_products']}")
    print(f"    price comparisons      : {s['comparable_pairs']} comparable pair(s)")
    print(f"    advertised offers      : {s['advertised_offers']} "
          f"({s['verifiable_discounts']} with a verifiable discount)")
    print(f"    dated news items       : {s['news_items']}")
    print(f"    flagged gaps           : {s['gaps']}")
    print("")
    print(f"  written: {md_path}")
    print(f"           {json_path}")
    print("  on the site: http://127.0.0.1:8770/research")
    return 0


if __name__ == "__main__":
    sys.exit(main())
