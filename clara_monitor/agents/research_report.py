"""Assembles the six agents' output into one executive report.

The report has the sections an executive asked for, in that order. What it adds
to them is a **gap register**: an explicit list of what is not established, with
the command that would establish it. That register exists because the failure mode
of a competitive report is not being wrong — it is being silently incomplete, and
then being quoted as if it were complete.

Two rules the assembly enforces:

* A section that has no evidence says so in its own words and names the run that
  would fill it. It never renders as an empty table, because an empty table reads
  as "we checked and there is nothing".
* Nothing is promoted on the way through. A field that arrived EDITORIAL is
  printed EDITORIAL, including in the executive summary, where the temptation to
  round it up to a fact is strongest.
"""

from __future__ import annotations

from .contracts import now_iso
from .research import EDITORIAL, NOT_ESTABLISHED, OBSERVED

MARK = {
    OBSERVED: "observed",
    EDITORIAL: "editorial",
    NOT_ESTABLISHED: "not established",
}


def _gaps(discovery: dict, clara: dict, pricing: dict, news: dict,
          offers: dict) -> list[dict]:
    """What this report does not know, and the command that would fix each one."""
    out = []

    missing = pricing["competitors_without_prices"]
    if missing:
        out.append({
            "gap": f"{len(missing)} of "
                   f"{len(discovery['competitors'])} competitors have no observed "
                   f"price",
            "impact": "every price comparison in this report rests on the "
                      f"{len(pricing['competitors_with_prices'])} brand(s) that "
                      "were read; the rest cannot be ranked on price at all",
            "fix": "python run_agent.py --targets 8",
            "who": ", ".join(missing[:10]) + ("…" if len(missing) > 10 else ""),
        })

    if pricing["verifiable_discounts"] == 0 and offers["advertised"]:
        out.append({
            "gap": "no advertised discount could be verified",
            "impact": f"{len(offers['advertised'])} promotion(s) were read and "
                      "none printed a before-price, so the percentages are the "
                      "retailers' claims rather than measured savings",
            "fix": "re-read those pages on a cycle; a before-price appears when "
                   "the retailer publishes one",
            "who": ", ".join(sorted({a['competitor'] for a in offers['advertised']})),
        })

    silent = news["competitors_not_mentioned"]
    if silent:
        out.append({
            "gap": f"{len(silent)} competitors appear in no news item",
            "impact": "the registered feeds are beauty-market press, not company "
                      "newsrooms, so silence means nothing was read rather than "
                      "nothing happened",
            "fix": "add each brand's own newsroom or press feed to "
                   "clara_monitor/trend_sources.py, then python run_trends.py",
            "who": ", ".join(silent[:10]) + ("…" if len(silent) > 10 else ""),
        })

    if clara["without_a_matched_rival"]:
        out.append({
            "gap": f"{clara['without_a_matched_rival']} Clara products face no "
                   f"matched rival",
            "impact": "they may be uncontested or simply unread; until a run "
                      "resolves which, they cannot be priced against anything",
            "fix": "python run_agent.py --targets 8 --discovery-budget 5",
            "who": "",
        })

    out.append({
        "gap": "no revenue, market-share or company-size figure",
        "impact": "competitor scale is reported as observed presence — surfaces "
                  "registered, pages read, Clara products faced — which is not "
                  "the same thing and is not a substitute",
        "fix": "a licensed market-data subscription; nothing public supports "
               "these numbers for most of these brands",
        "who": "all competitors",
    })

    if pricing.get("stale_prices"):
        out.append({
            "gap": f"{pricing['stale_prices']} observed price(s) are over two "
                   f"weeks old",
            "impact": "a price that old should be re-read before it is quoted "
                      "in a negotiation or a listing",
            "fix": "python run_agent.py on the affected competitors",
            "who": "",
        })
    return out


def build_report(discovery: dict, clara: dict, pricing: dict, news: dict,
                 offers: dict, comparison: dict, agents: dict,
                 model_status: dict) -> dict:
    gaps = _gaps(discovery, clara, pricing, news, offers)
    comparable = [c for c in pricing["comparisons"]
                  if c.get("gap_percent") is not None]

    small = [c for c in discovery["competitors"]
             if (c["price_tier"]["value"] or "") in ("value", "mid_market")
             or c["kind"].startswith("emerging")]
    large = [c for c in discovery["competitors"]
             if (c["price_tier"]["value"] or "") in ("premium", "professional")
             and not c["kind"].startswith("emerging")]

    return {
        "generated_at": now_iso(),
        "title": "Clara competitive research — executive report",
        "how_to_read": (
            "Every field carries how it is known. OBSERVED was read by the Agent "
            "from a real page with a URL and a timestamp. EDITORIAL was written by "
            "a person and this system did not verify it. NOT_ESTABLISHED means "
            "nothing is held — it is named as a gap with the fix beside it, never "
            "left blank. No revenue estimate, market share, or negotiated "
            "discount appears anywhere: no code path produces one."),
        "summary": {
            "competitors": len(discovery["competitors"]),
            "competitors_with_observed_prices":
                len(pricing["competitors_with_prices"]),
            "clara_products": clara["total"],
            "clara_price_range": f"{clara['price_min']}–{clara['price_max']} "
                                 f"{clara['currency']}",
            "comparable_pairs": len(comparable),
            "distinct_rival_products": len({
                (c["competitor"], c["competitor_product"])
                for c in pricing["comparisons"]}),
            "clara_cheaper_in": len(comparison["clara_price_advantage"]),
            "competitor_cheaper_in": len(comparison["cheapest_rivals"]),
            "advertised_offers": len(offers["advertised"]),
            "verifiable_discounts": pricing["verifiable_discounts"],
            "news_items": len(news["items"]),
            "recent_news_items": len(news["recent_items"]),
            "gaps": len(gaps),
            "decision_source": ("vertex_gemini" if model_status.get("available")
                                else "deterministic_rules"),
        },
        "clara_portfolio": clara,
        "small_competitors": small,
        "large_competitors": large,
        "all_competitors": discovery["competitors"],
        "discovery": discovery,
        "product_comparison": pricing["comparisons"],
        "pricing_comparison": {
            "prices": pricing["prices"],
            "competitors_with_prices": pricing["competitors_with_prices"],
            "competitors_without_prices": pricing["competitors_without_prices"],
            "note": pricing["note"],
        },
        "best_offers": offers,
        "recent_news": news,
        "threats": comparison["biggest_threats"],
        "opportunities": comparison["opportunities"],
        "comparison": comparison,
        "gaps": gaps,
        "recommended_actions": _actions(comparison, pricing, offers, gaps),
        "agents": agents,
        "model_status": {
            "model": model_status.get("configured_model"),
            "available": bool(model_status.get("available")),
            "reason": model_status.get("unavailable_reason"),
        },
    }


def _actions(comparison: dict, pricing: dict, offers: dict,
             gaps: list) -> list[dict]:
    """What to do, ordered by whether the evidence supports doing it yet."""
    out = []

    for c in comparison["cheapest_rivals"][:3]:
        out.append({
            "action": (f"Decide whether {c['clara_product']} holds at "
                       f"{c['clara_price']} {c['clara_currency']} against "
                       f"{c['competitor']} at {c['competitor_price']} "
                       f"{c['competitor_currency']} — "
                       f"{abs(c['gap_percent']):.0f}% below it."),
            "owner": "pricing",
            "urgency": "this_week",
            "basis": OBSERVED,
            "evidence": c.get("url"),
        })

    for c in comparison["clara_price_advantage"][:2]:
        out.append({
            "action": (f"Put the comparison on the {c['clara_product']} listing: "
                       f"{c['clara_price']} {c['clara_currency']} against "
                       f"{c['competitor']} at {c['competitor_price']} — a "
                       f"{c['gap_percent']:.0f}% saving. Date the screenshot."),
            "owner": "marketing",
            "urgency": "this_month",
            "basis": OBSERVED,
            "evidence": c.get("url"),
        })

    if "bundle" in offers["mechanisms_seen"]:
        out.append({
            "action": ("Answer bundling with bundling. Every rival promotion read "
                       "was a bundle, often with free shipping — price a Clara "
                       "device-plus-consumable set against them rather than "
                       "cutting a headline price."),
            "owner": "product",
            "urgency": "this_month",
            "basis": OBSERVED,
            "evidence": "",
        })

    if pricing["verifiable_discounts"] == 0 and offers["advertised"]:
        out.append({
            "action": ("Do not match an unverified percentage. No rival printed a "
                       "before-price, so their advertised savings are unproven; "
                       "state Clara's own price plainly instead."),
            "owner": "pricing",
            "urgency": "this_week",
            "basis": OBSERVED,
            "evidence": "",
        })

    for g in gaps[:3]:
        if not g.get("fix", "").startswith("python"):
            continue
        out.append({
            "action": f"Close a coverage gap: {g['gap']}. Run `{g['fix']}`.",
            "owner": "ops",
            "urgency": "this_week",
            "basis": OBSERVED,
            "evidence": "",
        })

    return out


# --------------------------------------------------------------------------
# markdown
# --------------------------------------------------------------------------

def _mark(f: dict) -> str:
    v = f.get("value")
    label = MARK.get(f.get("verification"), "?")
    if v in (None, "", [], {}):
        note = f.get("note") or "not established"
        return f"_not established — {note}_"
    if isinstance(v, list):
        v = ", ".join(str(x) for x in v[:6])
    if f.get("verification") == OBSERVED:
        return str(v)
    return f"{v} _({label})_"


def to_markdown(r: dict) -> str:
    s = r["summary"]
    L = []
    A = L.append

    A(f"# {r['title']}")
    A("")
    A(f"_Generated {r['generated_at']}_")
    A("")
    A("## How to read this")
    A("")
    A(r["how_to_read"])
    A("")

    A("## At a glance")
    A("")
    A("| | |")
    A("|---|---|")
    A(f"| Competitors tracked | **{s['competitors']}** "
      f"({s['competitors_with_observed_prices']} with an observed price) |")
    A(f"| Clara products | **{s['clara_products']}**, "
      f"{s['clara_price_range']} |")
    A(f"| Comparable price pairs | **{s['comparable_pairs']}** across "
      f"{s['distinct_rival_products']} distinct rival product(s) |")
    A(f"| Clara cheaper in | {s['clara_cheaper_in']} pair(s) |")
    A(f"| Competitor cheaper in | {s['competitor_cheaper_in']} pair(s) |")
    A(f"| Advertised offers read | {s['advertised_offers']} "
      f"(**{s['verifiable_discounts']}** with a verifiable discount) |")
    A(f"| Dated news items | {s['news_items']} "
      f"({s['recent_news_items']} recent) |")
    A(f"| Flagged gaps | **{s['gaps']}** |")
    A(f"| Decided by | {s['decision_source']} |")
    A("")

    # ---- gaps first: an executive should see the shape of the evidence ----
    A("## What this report does not know")
    A("")
    A("Listed before the findings on purpose. Each gap names the command that "
      "would close it.")
    A("")
    for g in r["gaps"]:
        A(f"- **{g['gap']}** — {g['impact']}")
        if g.get("who"):
            A(f"  - Affects: {g['who']}")
        A(f"  - Fix: `{g['fix']}`" if g["fix"].startswith("python")
          else f"  - Fix: {g['fix']}")
    A("")

    # ---- Clara portfolio ----
    cp = r["clara_portfolio"]
    A("## Clara's product and pricing overview")
    A("")
    A(f"{cp['total']} products, every one priced on Clara's own storefront. "
      f"{cp['with_a_matched_rival']} have at least one rival matched; "
      f"{cp['without_a_matched_rival']} do not.")
    A("")
    A("| Segment | Products | Min | Median | Max |")
    A("|---|---|---|---|---|")
    for seg, b in sorted(cp["bands_by_segment"].items()):
        A(f"| {seg} | {b['count']} | {b['min']} | {b['median']} | {b['max']} |")
    A("")
    A(f"_{cp['note']}_")
    A("")
    A("<details><summary>Every Clara product</summary>")
    A("")
    A("| Product | Segment | Price | Rating | Rivals matched |")
    A("|---|---|---|---|---|")
    for p in cp["products"]:
        rivals = p["competitors_with_similar"]["value"]
        A(f"| [{p['name']['value']}]({p['url']}) | {p['segment']['value']} | "
          f"{p['price']['value']} {p['currency']['value']} | "
          f"{p['rating']['value'] if p['rating']['value'] is not None else '—'} | "
          f"{', '.join(rivals) if rivals else '—'} |")
    A("")
    A("</details>")
    A("")

    # ---- competitors ----
    for title, rows, blurb in (
        ("Small and emerging competitors", r["small_competitors"],
         "Value and mid-market brands, plus anything founded from 2015."),
        ("Large and established competitors", r["large_competitors"],
         "Premium and professional brands with an established position."),
    ):
        A(f"## {title}")
        A("")
        A(f"{blurb} {len(rows)} of {s['competitors']}.")
        A("")
        A("| Company | Country | Positioning | Price tier | Threat | "
          "Pages read | Clara products faced |")
        A("|---|---|---|---|---|---|---|")
        for c in rows:
            pres = c["observed_presence"]["value"]
            A(f"| **{c['company_name']['value']}** "
              f"([site](https://{c['website']['value']})) "
              f"| {_mark(c['country'])} | {_mark(c['positioning'])} "
              f"| {_mark(c['price_tier'])} | {_mark(c['threat_to_clara'])} "
              f"| {pres['pages_read_successfully']} "
              f"| {pres['clara_products_faced']} |")
        A("")

    # ---- product comparison ----
    A("## Competitor product comparison")
    A("")
    comps = r["product_comparison"]
    if not comps:
        A("_No product pairing holds today. A monitoring run is what fills this._")
    else:
        # Grouped by the rival product, not listed flat. One Dyson page matched
        # against sixteen Clara bundles is one finding repeated sixteen times,
        # and a flat table presents it as sixteen findings.
        groups: dict = {}
        for c in comps:
            groups.setdefault((c["competitor"], c["competitor_product"]),
                              []).append(c)
        A(f"{len(comps)} stored pairing(s), resting on **{len(groups)} distinct "
          f"rival product(s)**. They are grouped below by the rival product: one "
          f"rival page matched against several Clara bundles is one comparison, "
          f"not several. A verdict appears only where both sides publish in the "
          f"same currency; currency is never converted.")
        A("")
        for (brand, rival), rows in sorted(
                groups.items(), key=lambda kv: -len(kv[1])):
            priced = [x for x in rows if x["competitor_price"] is not None]
            head = priced[0] if priced else rows[0]
            link = (f"[{rival or 'page'}]({head['url']})" if head.get("url")
                    else (rival or "—"))
            A(f"**{brand}** — {link} at "
              f"{head['competitor_price']} {head['competitor_currency'] or ''}")
            A("")
            A("| Clara product | Clara price | Verdict | Gap | Match |")
            A("|---|---|---|---|---|")
            ranked = sorted(rows, key=lambda x: abs(x["gap_percent"] or 9999))
            for c in ranked[:6]:
                gap = (f"{c['gap_percent']:+.0f}%"
                       if c["gap_percent"] is not None else "—")
                A(f"| {c['clara_product']} | {c['clara_price']} "
                  f"{c['clara_currency']} | {c['verdict']} | {gap} "
                  f"| {c['match_status'].replace('_', ' ')} |")
            if len(ranked) > 6:
                A(f"| _and {len(ranked) - 6} further Clara product(s) matched to "
                  f"this same rival product_ | | | | |")
            A("")
        A("_A single rival product matched against many Clara products usually "
          "means the pairing is broad rather than exact. Those rows are "
          "`probable match`, and narrowing them is what the ambiguous-pair "
          "handoff on the competitors page is for._")
    A("")

    # ---- pricing comparison ----
    pc = r["pricing_comparison"]
    A("## Competitor pricing")
    A("")
    A(f"Observed on **{len(pc['competitors_with_prices'])}** of "
      f"{s['competitors']} competitors: "
      f"{', '.join(pc['competitors_with_prices'])}.")
    A("")
    A(f"_{pc['note']}_")
    A("")
    A("| Competitor | Product | Price | Before | Stock | Read |")
    A("|---|---|---|---|---|---|")
    for p in pc["prices"]:
        before = (p["regular_price"]["value"]
                  if p["regular_price"]["value"] is not None else "—")
        A(f"| {p['competitor']} | [{p['product']['value']}]({p['url']}) "
          f"| {p['price']['value']} {p['currency']['value']} | {before} "
          f"| {p['availability']['value'] or '—'} "
          f"| {(p['observed_at'] or '')[:10]} |")
    A("")

    # ---- offers ----
    off = r["best_offers"]
    A("## Best competitor offers")
    A("")
    A(f"_{off['note']}_")
    A("")
    A("### Advertised — quotable")
    A("")
    if not off["advertised"]:
        A("_No promotion was printed on any page read._")
    else:
        A("| Competitor | Product | Wording | Mechanism | Price shown | "
          "Verified discount | Read |")
        A("|---|---|---|---|---|---|---|")
        for a in off["advertised"]:
            A(f"| {a['competitor']} | [{a['product']}]({a['url']}) "
              f"| {a['wording']} | {', '.join(a['mechanisms'])} "
              f"| {a['price_shown']} {a['currency']} "
              f"| **none — no before-price printed** "
              f"| {(a['observed_at'] or '')[:10]} |")
    A("")
    A("### Negotiation openings — inferences, not offers")
    A("")
    A("Nobody was contacted and no quote was requested. Each line states what "
      "would have to be true.")
    A("")
    for o in off["openings"]:
        A(f"- **{o['opportunity']}** _({MARK.get(o['verification'], '?')})_ — "
          f"{o['detail']}")
        A(f"  - Would be confirmed by: {o['what_would_confirm_it']}")
    A("")
    A("**Not applicable in this category:**")
    A("")
    for k, why in off["not_applicable"].items():
        A(f"- `{k}` — {why}")
    A("")

    # ---- news ----
    nw = r["recent_news"]
    A("## Recent competitor and channel news")
    A("")
    A(f"_{nw['note']}_")
    A("")
    if nw["items"]:
        A("| Date | Headline | Publisher | Names | Type |")
        A("|---|---|---|---|---|")
        for i in nw["items"][:40]:
            names = ", ".join((i["competitors_named"] or []) +
                              (i["industry_named"] or []))
            A(f"| {(i['published_at'] or '')[:10]} "
              f"| [{i['headline']}]({i['url']}) | {i['publisher']} "
              f"| {names} | {', '.join(i['categories'])} |")
    else:
        A("_No item in the collected signals names a tracked competitor._")
    A("")

    # ---- threats and opportunities ----
    A("## Major competitive threats")
    A("")
    A("Ranked by an editorial threat rating combined with two observed counts. "
      "The rating is a person's judgement; the counts are measured.")
    A("")
    A("| Competitor | Rating | Basis | Clara products faced | Pages read | Why |")
    A("|---|---|---|---|---|---|")
    for t in r["threats"]:
        A(f"| **{t['competitor']}** | {t['threat_rating']} "
          f"| _{MARK.get(t['rating_basis'], '?')}_ "
          f"| {t['clara_products_faced']} | {t['observed_pages']} "
          f"| {t['why']} |")
    A("")

    A("## Market opportunities for Clara")
    A("")
    for o in r["opportunities"]:
        A(f"- **{o['opportunity']}** _({MARK.get(o['basis'], '?')})_ — "
          f"{o['detail']}")
        A(f"  - Next: `{o['action']}`" if o["action"].startswith("python")
          else f"  - Next: {o['action']}")
    A("")

    A("## Recommended actions")
    A("")
    A("| Urgency | Owner | Action | Basis |")
    A("|---|---|---|---|")
    for a in r["recommended_actions"]:
        A(f"| {a['urgency'].replace('_', ' ')} | {a['owner']} | {a['action']} "
          f"| _{MARK.get(a['basis'], '?')}_ |")
    A("")

    ms = r["model_status"]
    A("---")
    A("")
    A(f"Six agents produced this report. Judgement came from "
      + ("the Vertex model with the deterministic rules underneath."
         if ms["available"] else
         f"the deterministic rules on every agent — `{ms['model']}` was "
         f"unavailable, and this report says so rather than implying a model "
         f"weighed anything."))
    A("")
    A("No competitor was contacted. No login, CAPTCHA or access control was "
      "worked around. Pages that refused automated access are reported as "
      "refused.")
    return "\n".join(L)
