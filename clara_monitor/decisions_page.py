"""The Decisions page — where the other two pages end up.

Competitors answers *what is true*. Trends answers *what is moving*. Neither
answers *so what*, and that is the only question anyone actually has. This page
exists so the output of the system is not buried under its inputs.

Built on `ui.py`, the same components the other two pages now use, so the three
read as one product. A decision card here looks like the insight callouts that
lead to it, on purpose: the shape of a thought should not change when it crosses
a page boundary.

Every card carries the six things a decision needs to be actionable rather than
merely interesting:

    title        what to decide
    insight      the one sentence a reader would repeat to a colleague
    metrics      the numbers it rests on, with direction
    relevant     which comparison and which trend produced it
    action       what to actually do
    impact       how much it matters, and confidence in the evidence

**Hierarchy is enforced, not decorated.** The top few decisions get a hero
treatment and nothing else does. A page where everything is emphasised has no
hierarchy at all, and a reader learns within a day to ignore whatever is loudest.

**Drill-down is the point.** Every card links back to the competitor row and the
trend popup that argued for it. A decision you cannot trace is an assertion, and
this page would rather be checkable than confident.
"""

from __future__ import annotations

import html

from . import intel_sections as isec, ui
from .ui import (IMPACT_LABEL, IMPACT_ORDER, URGENCY_LABEL, badge, crosslink,
                 crosslinks, e, insight, metric, metrics, nothing, section_head)

# How many decisions get the hero treatment. Deliberately small.
HERO_COUNT = 3

GROUP_TITLE = {
    "now": "Decide today",
    "this_week": "Decide this week",
    "this_month": "Decide this month",
    "watch": "Watch — no decision asked for",
}
GROUP_LEDE = {
    "now": "A competitor has already moved in a way that changes Clara's "
           "position. Leaving these is itself a decision.",
    "this_week": "The condition that raised these is live and will not stay "
                 "that way.",
    "this_month": "Worth doing deliberately rather than urgently. Most "
                  "trend-driven calls land here, because a trend is a window "
                  "and not an event.",
    "watch": "Recorded so it is not rediscovered as news next cycle. No action "
             "is being asked for.",
}

EXTRA_CSS = """
.dpage{padding-bottom:80px}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(152px,1fr));
       gap:12px;margin:20px 0 4px}
.tile{background:var(--card);border:1px solid var(--line);border-radius:7px;
      padding:15px 17px}
.tile .n{font-size:27px;font-weight:700;letter-spacing:-.025em;line-height:1.1}
.tile .l{font-size:12px;color:var(--ink3);margin-top:3px}
.tile .s{font-size:11.5px;color:var(--ink4);margin-top:5px;line-height:1.5}
.tile.crit .n{color:var(--bad)}
.tile.r .n{color:var(--clara)}
.tile.b .n{color:var(--rival)}

/* The hero band. Its own ground so the top decisions read as a different
   class of thing rather than as the first three rows of a list. */
.heroband{background:var(--card2);border-top:1px solid var(--line);
          border-bottom:1px solid var(--line);padding:30px 0 34px}
.heroband .hb-h{font-size:12px;letter-spacing:.06em;text-transform:uppercase;
                color:var(--ink3);font-weight:700;margin-bottom:4px}
.heroband .hb-s{font-size:13.5px;color:var(--ink2);line-height:1.65;
                max-width:74ch;margin-bottom:20px}

.basis{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));
       gap:12px}
.basiscard{background:var(--card);border:1px solid var(--line);
           border-radius:8px;padding:15px 17px}
.basiscard .bt{font-weight:650;font-size:13.5px;margin-bottom:8px;
               display:flex;gap:8px;align-items:center}
.basiscard dl{display:grid;grid-template-columns:auto 1fr;gap:5px 12px;
              font-size:12.5px;margin:0}
.basiscard dt{color:var(--ink3)}
.basiscard dd{color:var(--ink);margin:0}
"""


def _tiles(items: list, b: dict) -> str:
    by_impact = {k: 0 for k in IMPACT_ORDER}
    for i in items:
        by_impact[i.get("impact", "low")] = by_impact.get(i.get("impact", "low"), 0) + 1
    moves = sum(1 for i in items if not i["trend"])
    trends = sum(1 for i in items if i["trend"])
    high_conf = sum(1 for i in items
                    if (i.get("confidence") or "").upper() == "HIGH")

    rows = [
        ("Open decisions", len(items), "waiting on a person", "r"),
        ("Critical", by_impact.get("critical", 0),
         "act before anything else", "crit"),
        ("High impact", by_impact.get("high", 0), "this week at the latest", ""),
        ("From comparisons", moves, "a competitor actually moved", "b"),
        ("From trends", trends, "a subject is moving", "b"),
        ("High confidence", high_conf, "the evidence supports acting", ""),
    ]
    P = ['<div class="tiles">']
    for label, n, sub, cls in rows:
        P.append(f'<div class="tile {cls}"><div class="n">{e(n)}</div>'
                 f'<div class="l">{e(label)}</div>'
                 f'<div class="s">{e(sub)}</div></div>')
    P.append('</div>')
    return "".join(P)


def _header(b: dict, items: list) -> str:
    intel = b.get("intel") or {}
    trends = b.get("trends") or {}
    P = ['<header class="top"><div class="wrap"><div class="hrow"><div>']
    P.append('<p class="eyebrow">Clara decisions</p>')
    P.append('<h1 style="margin-top:10px">What to decide, and why now</h1>')
    P.append('<p class="lede">The comparator says what is true. Trends says what '
             'is moving. This is where both end up: every call waiting on a '
             'person, ordered by how much it matters, with the numbers behind it '
             'and a route back to the evidence. Nothing appears here unless it '
             'can name a number, a product and a source.</p>')
    P.append('</div><div class="runmeta">')
    for k, v in [("Cycle", intel.get("cycle_id") or "—"),
                 ("Updated", isec.ago(intel.get("updated_at"))),
                 ("Last trend scan", trends.get("scan_ago") or "never"),
                 ("Subjects tracked", (trends.get("counts") or {}).get("topics", 0))]:
        P.append(f'<div>{e(k)} &nbsp;<b>{e(v)}</b></div>')
    P.append('</div></div>')
    P.append(_tiles(items, b))
    P.append('<div class="note"><b>How to read a card.</b> A '
             + badge("clara", "comparison") +
             ' decision comes from something a competitor was verified to have '
             'done, so it is about responding. A ' + badge("rival", "trend") +
             ' decision comes from a subject several publishers are moving on, '
             'hooked to a real Clara product — an opportunity with a window '
             'rather than an event. Impact is derived from urgency, confidence '
             'and the size of the gap; confidence is the confidence of the '
             'evidence underneath, and nothing was raised to make a decision '
             'look safer than it is.</div>')
    P.append('</div></header>')
    return "\n".join(P)


def _nav(items: list) -> str:
    present = [u for u in ("now", "this_week", "this_month", "watch")
               if any(i["urgency"] == u for i in items)]
    P = ['<nav class="jump"><div class="wrap">']
    if items:
        P.append('<a href="#top-calls">Top calls</a>')
    for u in present:
        P.append(f'<a href="#{e(u)}">{e(GROUP_TITLE[u])}</a>')
    P.append('<a href="#basis">What this rests on</a>')
    P.append('</div></nav>')
    return "".join(P)


def _card(i: dict, *, hero: bool = False) -> str:
    """One decision, with all six required parts and a route back."""
    cls = "dc" + (" trend" if i["trend"] else "") + (" hero" if hero else "")
    P = [f'<div class="{cls}">']

    P.append('<div class="dc-top">')
    P.append(badge(i.get("impact", "low")))
    P.append(badge(i.get("urgency", "watch")))
    P.append(badge("rival" if i["trend"] else "clara",
                   "trend" if i["trend"] else "comparison"))
    P.append(badge((i.get("confidence") or "UNVERIFIED").upper()))
    P.append(f'<span class="dc-sub">{e(i.get("owner"))}</span>')
    P.append('</div>')

    P.append(f'<h3>{e(i.get("what"))}</h3>')
    P.append(f'<div class="dc-sub">{e(i.get("entity"))}</div>')

    if i.get("insight"):
        P.append(insight(i["insight"], trend=i["trend"]))

    P.append(metrics([metric(m["value"], m["key"], m.get("note", ""),
                             m.get("tone", "neutral"))
                      for m in (i.get("metrics") or [])]))

    # Only when it adds something. Where the insight was derived from the same
    # sentence, printing both teaches the reader to skip both.
    if i.get("why") and i["why"] != i.get("insight"):
        P.append(f'<div class="dc-why"><b>Why now:</b> {e(i["why"])}</div>')
    if i.get("impact_why"):
        P.append(f'<div class="dc-why"><b>{e(IMPACT_LABEL.get(i.get("impact"), ""))}'
                 f' because:</b> {e(i["impact_why"])}</div>')
    if i.get("note"):
        P.append(f'<div class="dc-why">{i["note"]}</div>')

    if i.get("done"):
        P.append(f'<div class="dc-do"><b>Done looks like:</b> '
                 f'{e(i["done"])}</div>')

    # Drill-down. This is what separates a decision from an assertion.
    links = []
    rel = i.get("relevant") or {}
    if i.get("competitor_key"):
        links.append(crosslink(f"/?focus={e(i['competitor_key'])}#competitors",
                               f"Compare {i.get('entity')}", icon="▤",
                               primary=True))
    elif not i["trend"]:
        links.append(crosslink("/#competitors", "Open the comparison",
                               icon="▤", primary=True))
    if i.get("topic_key"):
        links.append(crosslink(f"/trends?trend={e(i['topic_key'])}",
                               f"Trend: {i.get('entity')}", icon="↗",
                               primary=True))
    elif i["trend"]:
        links.append(crosslink("/trends#report", "Open the trend report",
                               icon="↗", primary=True))
    if rel.get("comparison"):
        # For a trend decision this is the Clara product carrying it; for a
        # competitor decision it is the pairing the gap was measured on.
        label = (f"Product: {rel['comparison'][:38]}" if i["trend"]
                 else f"Pairing: {rel['comparison'][:38]}")
        links.append(crosslink("/#prices", label, icon="●"))
    for l in (i.get("links") or [])[:3]:
        if l.get("url"):
            links.append(crosslink(l["url"], l.get("label") or "source",
                                   icon="↗", external=True))
    P.append(crosslinks(links))

    P.append('</div>')
    return "\n".join(P)


def _hero_band(items: list) -> str:
    """The few decisions that actually matter, given their own ground."""
    top = items[:HERO_COUNT]
    if not top:
        return ""
    P = ['<section class="heroband" id="top-calls"><div class="wrap">']
    P.append('<div class="hb-h">The calls that matter most</div>')
    P.append(f'<p class="hb-s">Ranked by impact: urgency, the confidence of the '
             f'evidence, the size of the price gap, and whether the subject is '
             f'moving. Only {HERO_COUNT} get this treatment — a page where '
             f'everything is emphasised has no hierarchy at all.</p>')
    for i in top:
        P.append(_card(i, hero=True))
    P.append('</div></section>')
    return "\n".join(P)


def _groups(items: list) -> str:
    if not items:
        return ('<section class="sec"><div class="wrap">'
                + nothing("Nothing is waiting on a decision.",
                          "Two things had to both be empty: no verified "
                          "competitor change cleared the bar for a task that "
                          "names a number, a product and a decision; and no "
                          "moving subject hooks onto a product in the catalogue. "
                          "Neither half is hiding the other. This page is only as "
                          "current as the last cycle and the last trend scan — "
                          "run python run_all.py and check again.")
                + '</div></section>')

    rest = items[HERO_COUNT:]
    P = []
    for u in ("now", "this_week", "this_month", "watch"):
        rows = [i for i in rest if i["urgency"] == u]
        if not rows:
            continue
        P.append(f'<section class="sec" id="{e(u)}"><div class="wrap">')
        P.append(section_head(GROUP_TITLE[u],
                              f"{len(rows)} decision(s)", GROUP_LEDE[u]))
        for i in rows:
            P.append(_card(i))
        P.append('</div></section>')
    return "\n".join(P)


def _basis(b: dict, items: list) -> str:
    intel = b.get("intel") or {}
    trends = b.get("trends") or {}
    summary = intel.get("summary") or {}
    tc = trends.get("counts") or {}

    P = ['<section class="sec" id="basis"><div class="wrap">']
    P.append(section_head(
        "What this rests on", "two inputs, both dated",
        "A decision is only as good as what raised it. Both inputs are stated "
        "with their own clock — if either is stale, every call above is stale in "
        "the same way."))
    P.append('<div class="basis">')

    P.append('<div class="basiscard">')
    P.append(f'<div class="bt">The comparison{badge("clara", "comparator")}</div>')
    P.append('<dl>')
    # Two counts that differ, said as two counts. The cycle only sees a
    # competitor once it has a stored snapshot, so "tracked" and "registered"
    # drift after the registry grows — and one number labelled loosely is how a
    # reader loses trust in every other number on the page.
    in_cycle = summary.get("competitors_tracked", 0)
    registered = ((bundle_competitors := (b.get("competitors") or {}))
                  .get("total") or 0)
    P.append(f'<dt>In this cycle</dt><dd>{e(in_cycle)} competitor(s) with a '
             f'stored snapshot</dd>')
    if registered and registered != in_cycle:
        P.append(f'<dt>Registered</dt><dd>{e(registered)} — the rest have no '
                 f'snapshot yet, so no change could be computed for them</dd>')
    P.append(f'<dt>Live offers</dt><dd>{e(summary.get("offers_live", 0))}</dd>')
    P.append(f'<dt>Findings</dt><dd>{e(summary.get("findings", 0))}</dd>')
    P.append(f'<dt>Updated</dt><dd>{e(isec.ago(intel.get("updated_at")))} '
             f'&middot; {e(isec.when(intel.get("updated_at")))}</dd>')
    P.append('</dl>')
    P.append(crosslinks([crosslink("/", "Open the comparator", icon="▤")]))
    P.append('</div>')

    P.append('<div class="basiscard">')
    P.append(f'<div class="bt">The trend scan{badge("rival", "trends")}</div>')
    P.append('<dl>')
    P.append(f'<dt>Subjects</dt><dd>{e(tc.get("topics", 0))} with evidence</dd>')
    P.append(f'<dt>Publishers</dt><dd>{e(tc.get("publishers", 0))}</dd>')
    P.append(f'<dt>Feeds read</dt><dd>{e(tc.get("feeds_read", 0))} of '
             f'{e(tc.get("feeds_tried", 0))}</dd>')
    P.append(f'<dt>Last scan</dt><dd>{e(trends.get("scan_ago") or "never")} '
             f'&middot; {e(trends.get("scan_when") or "")}</dd>')
    P.append('</dl>')
    P.append(crosslinks([crosslink("/trends", "Open the trends", icon="↗")]))
    P.append('</div>')
    P.append('</div>')

    refused = summary.get("pairings_refused") or 0
    if refused:
        P.append(f'<div class="note"><b>{e(refused)} stored pairing(s) were '
                 f'refused this cycle</b> because the two sides are different '
                 f'kinds of product, so no price decision was derived from them. '
                 f'They are listed on the comparator.</div>')

    src = summary.get("decision_sources") or {}
    model = "vertex_gemini" in set(src.values())
    P.append('<div class="note">Judgement came from '
             + ('the Vertex model with the deterministic rules underneath.'
                if model else
                'the deterministic rules on every agent — Vertex was '
                'unavailable, and this page says so rather than implying a model '
                'weighed these decisions.') + '</div>')
    P.append('</div></section>')
    return "\n".join(P)


def _footer(b: dict) -> str:
    P = ['<footer><div class="wrap">']
    P.append('<p><b>Where these come from.</b> Comparison decisions are raised by '
             'the intelligence cycle from verified changes and confirmed-live '
             'promotions. Trend decisions are raised where a subject several '
             'publishers are moving on can be attached to a specific Clara '
             'product. A subject with no product to carry it produces nothing, '
             'which is why this list is short rather than comprehensive.</p>')
    P.append('<p>Every card links back to the comparison row and the trend that '
             'argued for it. A decision you cannot trace is an assertion.</p>')
    P.append('</div></footer>')
    return "\n".join(P)


def render(bundle: dict, trends: dict | None = None) -> str:
    from .site import CSS
    b = dict(bundle)
    if trends is not None:
        b["trends"] = trends
    items = isec.decision_items(b, b.get("trends"))

    P = ['<title>Decisions — Clara</title>',
         '<meta name="viewport" content="width=device-width, initial-scale=1">',
         f'<style>{CSS}{ui.SHARED_CSS}{EXTRA_CSS}</style>',
         '<div class="dpage">']
    P.append(_header(b, items))
    P.append(_nav(items))
    P.append(_hero_band(items))
    P.append(_groups(items))
    P.append(_basis(b, items))
    P.append(_footer(b))
    P.append('</div>')
    return "\n".join(P)
