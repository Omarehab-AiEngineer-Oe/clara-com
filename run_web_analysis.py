"""Run a Website Analysis. Section 10: manual run, report display, exports.

    python run_web_analysis.py --clara https://clarahair.com/en \
        --competitor https://ghdhair.com --competitor https://www.dyson.sa \
        --pages 10

Collection is slow and it contacts real websites, so it is an explicit act rather
than something a page load triggers. Rendering the report never fetches anything.
"""
from __future__ import annotations

import argparse
import json

from clara_monitor.config import DB_PATH, REPORT_DIR
from clara_monitor.llm import judge_singleton
from clara_monitor.web.orchestrator import WebsiteAnalysisAgent


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--clara", default="https://clarahair.com/en")
    ap.add_argument("--competitor", action="append", default=[],
                    help="repeatable")
    ap.add_argument("--page", action="append", default=[],
                    help="a specific page that must be included; repeatable")
    ap.add_argument("--pages", type=int, default=10, help="page limit per site")
    ap.add_argument("--audience", default="")
    ap.add_argument("--brand", default="")
    ap.add_argument("--goals", default="")
    ap.add_argument("--no-screenshots", action="store_true")
    ap.add_argument("--no-model", action="store_true")
    ap.add_argument("--show", metavar="RUN_ID", help="print a stored run instead")
    args = ap.parse_args()

    agent = WebsiteAnalysisAgent(
        DB_PATH, llm=None if args.no_model else judge_singleton(), verbose=True)
    try:
        if args.show:
            out = agent.report(args.show)
        else:
            out = agent.run(
                clara_url=args.clara, competitor_urls=args.competitor,
                specific_pages=args.page, page_limit=args.pages,
                audience=args.audience, brand_guidelines=args.brand,
                business_goals=args.goals, requested_by="cli",
                want_screenshots=not args.no_screenshots)
    finally:
        agent.close()

    run = out.get("run") or {}
    rid = run.get("run_id", "?")
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    path = REPORT_DIR / f"website_{rid}.json"
    path.write_text(json.dumps(out, ensure_ascii=False, indent=2, default=str),
                    encoding="utf-8")

    s = out.get("summary") or {}
    print(f"\n  {s.get('findings', 0)} finding(s): "
          f"{s.get('high', 0)} high, {s.get('medium', 0)} medium, "
          f"{s.get('low', 0)} low")
    print(f"  {s.get('gaps', 0)} gap(s), {s.get('strengths', 0)} strength(s), "
          f"{s.get('limitations', 0)} limitation(s)")
    print(f"  pages: {s.get('pages_read', 0)} read, "
          f"{s.get('pages_blocked', 0)} blocked")
    for w in (out.get("warnings") or [])[:8]:
        print(f"  ! {w}")
    print(f"  written to {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
