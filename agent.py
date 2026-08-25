"""Autonomous Competitor Intelligence Agent — Google ADK entry point.

The Agent is the only orchestrator (§1). Catalog access, match lookup, HTTP
retrieval, discovery, structured-data parsing, candidate scoring, image
collection, validation, storage and reporting are tools under its control, one
per step of §4, so the loop can only advance in the permitted order.

Model: Gemini on Vertex AI, pinned to the `global` location. Identity judgement
is model-assisted but never authoritative: the deterministic format gate and the
validation rules in `extract.py` decide what may be stored, per §6 ("validation
and storage integrity must not depend only on free-form model judgment").

Access: every network read goes through `clara_monitor.access.guarded_get`. The
model cannot route around it even if instructed to.
"""

from __future__ import annotations

import json
from functools import cached_property
from pathlib import Path

from google.adk.agents import LlmAgent
from google.adk.models import Gemini
from google.adk.tools import FunctionTool, agent_tool
from google.adk.tools.google_search_tool import GoogleSearchTool
from google.genai import Client

from clara_monitor import (
    trend_data, trend_store,
    catalog, competitors as comp, engine, reporting, site,
)
from clara_monitor.config import DB_PATH, RunConfig
from clara_monitor.llm import MODEL_ID, judge_singleton
from clara_monitor.store import Store

PROMPT = (Path(__file__).parent / "prompts" / "catalog_monitor.md").read_text(
    encoding="utf-8")


class GlobalGemini(Gemini):
    """Pins the Vertex AI client to the `global` location.

    gemini-3 series models are only served from `global`; the default ADK
    `Gemini` integration constructs a `google.genai.Client` whose location
    defaults to the AgentEngine instance's region (e.g. `us-central1`) and
    fails with model-not-found for these models. Subclassing per the override
    pattern documented on `google.adk.models.google_llm.Gemini` lets the agent
    keep running in its regional AgentEngine instance while routing the model
    request to the global endpoint.
    """

    @cached_property
    def api_client(self) -> Client:
        return Client(vertexai=True, location="global")


# ---------------------------------------------------------------------------
# Tools — one per step of §4
# ---------------------------------------------------------------------------

def load_clara_catalog(devices_only: bool = False,
                       live_refresh: bool = False) -> dict:
    """Step 1 — load the Clara catalog and the competitors assigned to each product.

    Args:
        devices_only: restrict to the styling-device lineup instead of the whole
            catalog.
        live_refresh: re-read each Clara product page instead of using the stored
            crawl.
    """
    cfg = RunConfig(run_id="_scope")
    products = catalog.load_from_seed(
        scope=cfg.scope_product_ids if devices_only else None)
    problems: list[dict] = []
    if live_refresh:
        products, problems = catalog.refresh_from_site(products)

    rows, segments, unassigned = [], {}, 0
    for p in products:
        targets = comp.targets_for(p.fmt, p.category, p.segment)
        segments[p.segment] = segments.get(p.segment, 0) + 1
        if not targets:
            unassigned += 1
        rows.append({
            "product_id": p.product_id, "name": p.name, "price": p.price,
            "currency": p.currency, "segment": p.segment, "category": p.category,
            "format": p.fmt, "specs": p.specs,
            "description_lang": p.description_lang,
            "assigned_competitors": targets,
        })
    return {
        "catalog_size": len(products), "by_segment": segments,
        "products_without_assignment": unassigned,
        "pairs_planned": sum(len(r["assigned_competitors"]) for r in rows),
        "catalog_problems": problems,
        "products": rows,
    }


def list_competitors() -> dict:
    """The competitor registry: brands, tiers, segments and the domain allowlist."""
    return {
        "registered": len(comp.REGISTRY),
        "competitors": comp.summary(),
        "allowed_hosts": sorted(comp.allowed_hosts()),
        "note": ("Only these hosts may ever be fetched. Adding a competitor is a "
                 "configuration change a human approves (§19), not something the "
                 "Agent may do mid-run."),
    }


def read_stored_matches(product_id: str) -> dict:
    """Step 2 — every stored match for one Clara product, with the validity verdict
    that decides whether discovery is permitted at all.

    Args:
        product_id: Clara product id, e.g. "p1268166868".
    """
    cfg = RunConfig(run_id="_probe")
    store = Store(DB_PATH)
    try:
        out = []
        for m in store.get_matches_for_product(product_id):
            valid, why = store.match_is_valid(m, cfg.ttl_days, comp.allowed_hosts())
            out.append({
                **m.as_dict(), "is_valid": valid, "validity_reason": why,
                "next_step": "refresh_only" if valid else "discovery_permitted",
                "current_observation": store.get_observation(product_id,
                                                             m.competitor_key),
                "events": store.match_events_for(product_id, m.competitor_key)[:8],
                "past_invalidations": store.invalidations_for(product_id,
                                                              m.competitor_key),
            })
        return {"product_id": product_id, "count": len(out), "stored_matches": out}
    finally:
        store.close()


def check_access(url: str) -> dict:
    """Test whether a URL may be read at all, before relying on it.

    Reports the allowlist verdict, the robots.txt verdict and any blocking signal.
    A blocked URL must be escalated, never worked around.

    Args:
        url: the competitor URL to test.
    """
    from clara_monitor.access import guarded_get, host_allowed, robots_allows
    hosts = comp.allowed_hosts()
    if not host_allowed(url, hosts):
        return {"url": url, "readable": False, "reason": "host_not_in_allowlist",
                "action": "Do not fetch. Ask a human to approve the domain if it is "
                          "genuinely in scope."}
    ok, why = robots_allows(url)
    if not ok:
        return {"url": url, "readable": False, "reason": "robots_disallowed",
                "detail": why,
                "action": "Do not fetch. Escalate; robots directives are honoured."}
    res = guarded_get(url, hosts)
    return {
        "url": url, "readable": bool(res.ok), "status": res.status,
        "blocked": res.blocked, "block_signal": res.block_signal,
        "evidence": res.evidence,
        "action": ("proceed" if res.ok else
                   "escalate to a human; do not retry with different headers, "
                   "credentials or a challenge solver"),
    }


def inspect_page(url: str) -> dict:
    """Read one competitor page and return the extracted, validated record.

    Runs the §9 method ladder and the §13 validation rules, so the reply shows
    which method was used, why, and whether the record is accepted,
    accepted_with_warnings or rejected. Nothing is stored.

    Args:
        url: the competitor product URL to inspect.
    """
    from clara_monitor.access import guarded_get, host_allowed
    from clara_monitor.extract import extract
    hosts = comp.allowed_hosts()
    res = guarded_get(url, hosts)
    if res.blocked:
        return {"url": url, "blocked": True, "block_signal": res.block_signal,
                "evidence": res.evidence,
                "action": "escalate; do not attempt to bypass"}
    if not res.ok or not res.html:
        return {"url": url, "readable": False, "status": res.status,
                "evidence": res.evidence}
    ex = extract(res.final_url or url, res.html, "SAR",
                 lambda u: host_allowed(u, hosts))
    return ex.as_dict()


def run_monitoring(run_id: str, targets_per_product: int = 2,
                   discovery_budget: int = 3, devices_only: bool = False,
                   use_model: bool = True, resume: bool = False) -> dict:
    """Steps 3-11 — run the whole loop and write the store.

    Refreshes every valid stored match first and enters discovery only for a pair
    whose stored match is missing, invalid, expired or unresolved.

    Args:
        run_id: identifier for this run, e.g. "2026-08-17-a".
        targets_per_product: cap on assigned competitors evaluated per product.
        discovery_budget: max candidate pages read per pair.
        devices_only: restrict to the styling-device lineup.
        use_model: use Vertex AI for identity judgement; when false, or when the
            model is unavailable, the deterministic rules decide and the run
            records that as the decision source.
        resume: continue an open run instead of refusing to overlap it.
    """
    cfg = RunConfig(run_id=run_id, discovery_budget=discovery_budget)
    products = catalog.load_from_seed(
        scope=cfg.scope_product_ids if devices_only else None)
    result = engine.run(cfg, products, targets_limit=targets_per_product,
                        use_llm=use_model, resume=resume)
    return {"run_id": result["run_id"], "summary": result["summary"],
            "outcomes": result["outcomes"][:120]}


def build_reports(run_id: str, inline_images: bool = True) -> dict:
    """Step 12 — build every report from the store and render the website.

    Produces the price report (all Clara products with matches beside them),
    coverage, change, escalation and competitor reports, plus the Clara-linked
    CSV and JSONL exports (§18).

    Args:
        run_id: the run to report on.
        inline_images: embed thumbnails so the page is self-contained.
    """
    store = Store(DB_PATH)
    try:
        bundle = reporting.build_all(store, run_id)
    finally:
        store.close()
    path = site.write_site(bundle, inline_images=inline_images)
    return {
        "run_id": run_id,
        "site_path": str(path),
        "price": {k: v for k, v in bundle["price"].items() if k != "products"},
        "coverage": {k: v for k, v in bundle["coverage"].items() if k != "products"},
        "changes": {k: v for k, v in bundle["changes"].items()
                    if k not in ("changes", "match_events")},
        "escalations": {k: v for k, v in bundle["escalations"].items()
                        if k not in ("exceptions", "errors")},
        "exports": [f"prices_{run_id}.csv", f"prices_{run_id}.jsonl"],
    }


def get_price_report(run_id: str, segment: str = "", limit: int = 40) -> dict:
    """The price report: every Clara product with its price and its matches.

    Args:
        run_id: the run to read.
        segment: optional filter, one of device, haircare, accessory.
        limit: max products returned.
    """
    store = Store(DB_PATH)
    try:
        pr = reporting.price_report(store, run_id)
    finally:
        store.close()
    rows = pr["products"]
    if segment:
        rows = [r for r in rows if r["segment"] == segment]
    return {**{k: v for k, v in pr.items() if k != "products"},
            "returned": min(len(rows), limit), "products": rows[:limit]}


def list_escalations(run_id: str) -> dict:
    """The escalation queue: blocked, ambiguous, repeated and failed pairs with
    evidence and a recommended next action.

    Args:
        run_id: the run to read.
    """
    store = Store(DB_PATH)
    try:
        return reporting.escalation_report(store, run_id)
    finally:
        store.close()


def model_status() -> dict:
    """Whether Vertex AI is reachable, and what happens if it is not.

    Probes with one real call rather than reporting the cached verdict, so asking
    the question always gets an answer instead of "not probed yet".
    """
    j = judge_singleton()
    j.probe()
    s = j.status
    return {**s,
            "fallback": ("Decisions fall back to the deterministic rules and each "
                         "match records decision_source=deterministic_rules. The run "
                         "never stalls on the model, and the fallback is reported "
                         "rather than hidden."),
            "fix": ("If unavailable because of credentials, run "
                    "`gcloud auth application-default login` (or supply a service "
                    "account) and rerun.")}


def get_beauty_trends(market: str = "", stage: str = "", category: str = "",
                      limit: int = 20) -> dict:
    """Read the Beauty Trends intelligence: trends, offers and brands to watch.

    Every item carries the source it came from. Stages run emerging -> rising ->
    viral -> mainstream -> declining, and `spread` says whether a trend is local,
    regional, global, or moving from one market into another.

    Args:
        market: optional filter, one of ME, CN, KR, UK, US, GLOBAL.
        stage: optional filter, one of emerging, rising, viral, mainstream,
            declining.
        category: optional filter, e.g. skincare, haircare, fragrance, wellness,
            makeup, industry.
        limit: max trends returned.
    """
    ts = trend_store.TrendStore(DB_PATH)
    try:
        ts.seed()
        b = trend_store.build(ts)
    finally:
        ts.close()
    rows = b["trends"]
    if market:
        rows = [t for t in rows if market.upper() in t["markets"]]
    if stage:
        rows = [t for t in rows if t["stage"] == stage.lower()]
    if category:
        rows = [t for t in rows if t["category"] == category.lower()]
    return {
        "generated_at": b["generated_at"],
        "counts": b["counts"],
        "by_stage": b["by_stage"],
        "market_counts": b["market_counts"],
        "returned": min(len(rows), limit),
        "trends": rows[:limit],
        "offers": b["offers"][:12],
        "brands_to_watch": b["brands"][:12],
        "moving_between_markets": [
            {"title": t["title"], "from": t["origin_market"],
             "into": [m for m in t["markets"] if m != t["origin_market"]],
             "stage": t["stage"]}
            for t in b["moving"]],
        "note": b["note"],
    }


def compare_beauty_markets() -> dict:
    """Compare what is trending across Korea, China, the Middle East, the US, the
    UK and global — and which trends are crossing from one market into another."""
    ts = trend_store.TrendStore(DB_PATH)
    try:
        ts.seed()
        b = trend_store.build(ts)
    finally:
        ts.close()
    return {
        "generated_at": b["generated_at"],
        "markets": {k: trend_data.MARKET_LABEL[k] for k in trend_data.MARKET_ORDER},
        "market_counts": b["market_counts"],
        "matrix": b["matrix"],
        "moving": [
            {"title": t["title"], "from": t["origin_market"],
             "into": [m for m in t["markets"] if m != t["origin_market"]],
             "stage": t["stage"], "spread": t["spread"]}
            for t in b["moving"]],
        "note": ("A trend is only listed in a market where a source actually "
                 "observed it. An empty cell means no evidence was found for that "
                 "market, not that the trend is absent."),
    }


# ---------------------------------------------------------------------------
# Sub-agents
# ---------------------------------------------------------------------------

discovery_search_agent = LlmAgent(
    name="Clara_ACI_discovery_search_agent",
    model=GlobalGemini(model=MODEL_ID),
    description="Finds candidate competitor product URLs inside a fixed domain set.",
    instruction=(
        "Use GoogleSearchTool to find candidate PRODUCT PAGE urls for the product "
        "description you are given, restricted to the domains you are given.\n"
        "Build queries from the product's format and specifications, using the "
        "competitor's own naming conventions.\n"
        "Return only URLs, one per line, with no commentary.\n"
        "Never return a search, category or listing page. Never return a domain you "
        "were not given. Never invent a URL. If you find nothing, return nothing."
    ),
    tools=[GoogleSearchTool()],
)

root_agent = LlmAgent(
    name="Clara_Centric_Autonomous_Competitor_Intelligence_Agent",
    model=GlobalGemini(model=MODEL_ID),
    description=(
        "Clara-catalog-driven competitor intelligence agent. For every Clara product "
        "and assigned competitor it reuses and refreshes a valid stored match before "
        "considering discovery, discovers and evaluates candidates only when no usable "
        "match exists, classifies each pair as confirmed_match, probable_match, "
        "ambiguous, no_match or invalidated with score and evidence, collects "
        "normalized variant, price, discount, stock, promotion, image and URL data, "
        "stores match, observation and append-only history, produces price, coverage, "
        "change and escalation reports, and escalates blocked or ambiguous pairs to a "
        "human without bypassing any login, CAPTCHA or access restriction."
    ),
    instruction=PROMPT,
    tools=[
        FunctionTool(load_clara_catalog),
        FunctionTool(list_competitors),
        FunctionTool(read_stored_matches),
        FunctionTool(check_access),
        FunctionTool(inspect_page),
        FunctionTool(run_monitoring),
        FunctionTool(build_reports),
        FunctionTool(get_price_report),
        FunctionTool(list_escalations),
        FunctionTool(model_status),
        FunctionTool(get_beauty_trends),
        FunctionTool(compare_beauty_markets),
        agent_tool.AgentTool(agent=discovery_search_agent),
    ],
)
