"""The shared design layer for the three pages.

Competitors, Trends and Decisions were built at different times and drifted:
three card shapes, three badge vocabularies, three ways of showing a number. This
is the one place they now agree, so a change to how a decision card looks is a
change everywhere it appears rather than three edits and a mismatch.

Two ideas run through it.

**One vocabulary for confidence and impact.** A `HIGH` on the competitors page
means the same thing, and looks the same, as a `HIGH` on Decisions. The badge
classes live here; no page defines its own.

**Cross-links are components, not markup.** A decision that cannot be traced back
to the comparison and the trend that produced it is an assertion. `crosslink()`
renders that trace the same way on every page, which is what makes the three feel
like one product instead of three screens that happen to share a colour.

The colour rules, stated once: `--clara` is Clara's own, `--rival` is a
competitor's, `--ok` / `--amb` / `--bad` are semantic status and are never used
for identity. An impact level is allowed to be loud. Everything else is quiet.
"""

from __future__ import annotations

import html

# --------------------------------------------------------------------------
# vocabulary
# --------------------------------------------------------------------------

IMPACT_ORDER = ("critical", "high", "medium", "low")
IMPACT_LABEL = {"critical": "Critical", "high": "High impact",
                "medium": "Medium impact", "low": "Low impact"}

URGENCY_ORDER = ("now", "this_week", "this_month", "watch")
URGENCY_LABEL = {"now": "Today", "this_week": "This week",
                 "this_month": "This month", "watch": "Watch"}

CONFIDENCE_ORDER = ("HIGH", "MEDIUM", "LOW", "UNVERIFIED")

ORIGIN_LABEL = {"competitor move": "Competitor move",
                "market trend": "Market trend"}


def e(v) -> str:
    return html.escape(str(v if v is not None else ""))


# --------------------------------------------------------------------------
# the shared stylesheet
# --------------------------------------------------------------------------

SHARED_CSS = """
/* ============ shared design layer: used by all three pages ============ */

/* --- section rhythm. One vertical scale so the pages breathe alike. --- */
.sec{padding:34px 0;border-top:1px solid var(--line)}
.sec:first-of-type{border-top:0}
.sec-h{display:flex;gap:14px;align-items:baseline;justify-content:space-between;
       flex-wrap:wrap;margin-bottom:6px}
.sec-h h2{font-size:22px;margin:0}
.sec-h .sec-meta{font-size:11.5px;color:var(--ink3);white-space:nowrap}
.sec-lede{font-size:13.5px;color:var(--ink2);line-height:1.7;max-width:76ch;
          margin-bottom:18px}

/* --- badges. One vocabulary, three pages. --- */
.bx{font-size:10px;font-weight:700;padding:2px 7px;border-radius:3px;
    letter-spacing:.03em;white-space:nowrap;display:inline-block}
.bx-critical{background:var(--bad);color:#fff}
.bx-high{background:var(--bad-wash);color:var(--bad)}
.bx-medium{background:var(--amb-wash);color:var(--amb)}
.bx-low{background:var(--card3);color:var(--ink3)}
.bx-now{background:var(--bad);color:#fff}
.bx-this_week{background:var(--amb-wash);color:var(--amb)}
.bx-this_month{background:var(--rival-wash);color:var(--rival)}
.bx-watch{background:var(--card3);color:var(--ink3)}
.bx-HIGH{background:var(--ok-wash);color:var(--ok)}
.bx-MEDIUM{background:var(--amb-wash);color:var(--amb)}
.bx-LOW{background:var(--card3);color:var(--ink3)}
.bx-UNVERIFIED{background:var(--bad-wash);color:var(--bad)}
.bx-clara{background:var(--clara-wash);color:var(--clara)}
.bx-rival{background:var(--rival-wash);color:var(--rival)}
.bx-quiet{background:var(--card3);color:var(--ink3)}
.bx-solid{background:var(--clara);color:#fff}

/* --- the metric strip. The numbers a decision rests on. --- */
.metrics{display:flex;gap:22px;flex-wrap:wrap;background:var(--card2);
         border-radius:7px;padding:12px 15px;margin-top:12px}
.metric{display:flex;flex-direction:column;gap:2px;min-width:0}
.metric .mv{font-size:19px;font-weight:700;letter-spacing:-.02em;
            font-variant-numeric:tabular-nums;line-height:1.15}
.metric .mk{font-size:11px;color:var(--ink3);white-space:nowrap}
.metric .mn{font-size:10.5px;color:var(--ink4)}
.metric.up .mv{color:var(--ok)}
.metric.down .mv{color:var(--bad)}
.metric.neutral .mv{color:var(--ink)}
.metric.hero .mv{color:var(--clara);font-size:24px}

/* --- the insight line. Why this matters, in one sentence. --- */
.insight{font-size:14px;color:var(--ink);line-height:1.65;font-weight:550;
         border-inline-start:3px solid var(--clara);padding-inline-start:13px;
         margin:12px 0}
.insight.trend{border-inline-start-color:var(--rival)}

/* --- cross-links. A trace back to the evidence, rendered identically. --- */
.xlinks{display:flex;gap:7px;flex-wrap:wrap;margin-top:13px;
        padding-top:12px;border-top:1px solid var(--line)}
.xlink{font-size:12px;text-decoration:none;border:1px solid var(--line2);
       border-radius:16px;padding:6px 12px;color:var(--ink2);
       display:inline-flex;gap:6px;align-items:center;background:var(--card)}
.xlink:hover{border-color:var(--clara);color:var(--clara)}
.xlink .xi{font-size:11px;opacity:.75}
.xlink.primary{background:var(--clara);color:#fff;border-color:var(--clara);
               font-weight:650}
.xlink.primary:hover{filter:brightness(1.08);color:#fff}
.xlink.ext{color:var(--rival)}

/* --- decision card. The single most important component. --- */
.dc{background:var(--card);border:1px solid var(--line);border-radius:9px;
    padding:18px 20px;margin-bottom:13px;
    border-inline-start:3px solid var(--clara)}
.dc.trend{border-inline-start-color:var(--rival)}
.dc-top{display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-bottom:9px}
.dc h3{font-size:17px;margin:0 0 2px;line-height:1.35}
.dc .dc-sub{font-size:12.5px;color:var(--ink3)}
.dc .dc-why{font-size:13px;color:var(--ink2);line-height:1.65;margin-top:9px}
.dc .dc-do{font-size:13.5px;color:var(--ink);line-height:1.6;margin-top:12px;
           background:var(--card2);border-radius:7px;padding:12px 14px}
.dc .dc-do b{color:var(--ink)}
.dc .dc-done{font-size:12px;color:var(--ink3);line-height:1.55;margin-top:7px}

/* The hero treatment. Reserved for the few decisions that actually matter,
   because a page where everything is emphasised has no hierarchy at all. */
.dc.hero{border:1px solid var(--clara);border-inline-start-width:4px;
         box-shadow:0 4px 20px rgba(0,0,0,.06);padding:22px 24px}
.dc.hero h3{font-size:20px}
.dc.hero .dc-do{background:var(--clara-wash)}

/* --- an insight callout on the comparator and trends pages --- */
.callout{background:var(--card);border:1px solid var(--line);border-radius:8px;
         padding:15px 17px;margin-bottom:12px;
         border-inline-start:3px solid var(--rival)}
.callout .co-t{font-weight:650;font-size:14px;margin-bottom:5px;
               display:flex;gap:8px;align-items:center;flex-wrap:wrap}
.callout .co-b{font-size:12.5px;color:var(--ink2);line-height:1.6}
.callout.win{border-inline-start-color:var(--ok)}
.callout.risk{border-inline-start-color:var(--bad)}

.cgrid2{display:grid;grid-template-columns:repeat(auto-fit,minmax(330px,1fr));
        gap:12px}
@media (max-width:700px){.cgrid2{grid-template-columns:1fr}}

/* --- the empty state. Says which half is empty and why. --- */
.nothing{background:var(--card2);border:1px dashed var(--line2);
         border-radius:8px;padding:20px 22px;font-size:13.5px;
         color:var(--ink2);line-height:1.7}
.nothing b{color:var(--ink)}

.win-v{color:var(--ok);font-weight:650}
.lose-v{color:var(--bad);font-weight:650}
.flat-v{color:var(--ink3)}
.na-v{color:var(--ink4);font-style:italic}
"""


# --------------------------------------------------------------------------
# components
# --------------------------------------------------------------------------

def badge(kind: str, label: str = "") -> str:
    """One badge implementation. Every page calls this rather than styling its own."""
    if not kind:
        return ""
    text = label or IMPACT_LABEL.get(kind) or URGENCY_LABEL.get(kind) or kind
    return f'<span class="bx bx-{e(kind)}">{e(text)}</span>'


def metric(value, key: str, note: str = "", tone: str = "neutral") -> str:
    """A number with what it is and, where useful, where it came from."""
    return (f'<div class="metric {e(tone)}">'
            f'<span class="mv">{e(value)}</span>'
            f'<span class="mk">{e(key)}</span>'
            + (f'<span class="mn">{e(note)}</span>' if note else '')
            + '</div>')


def metrics(rows: list) -> str:
    """The strip of supporting numbers under a decision.

    Empty in, nothing out — an empty metric strip is worse than none, because it
    reads as a measurement of zero.
    """
    live = [m for m in rows if m]
    if not live:
        return ""
    return '<div class="metrics">' + "".join(live) + '</div>'


def insight(text: str, *, trend: bool = False) -> str:
    """The one sentence that says why this matters. Never more than one."""
    if not text:
        return ""
    return f'<div class="insight{" trend" if trend else ""}">{e(text)}</div>'


def crosslink(href: str, label: str, *, icon: str = "", primary: bool = False,
              external: bool = False) -> str:
    """A trace back to the evidence.

    The same component on all three pages, so following a decision to its
    comparison and its trend feels like one product rather than three.
    """
    cls = "xlink" + (" primary" if primary else "") + (" ext" if external else "")
    rel = ' rel="nofollow noopener"' if external else ""
    return (f'<a class="{cls}" href="{e(href)}"{rel}>'
            + (f'<span class="xi">{e(icon)}</span>' if icon else '')
            + f'<span>{e(label)}</span></a>')


def crosslinks(items: list) -> str:
    live = [i for i in items if i]
    if not live:
        return ""
    return '<div class="xlinks">' + "".join(live) + '</div>'


def section_head(title: str, meta: str = "", lede: str = "") -> str:
    P = ['<div class="sec-h">', f'<h2>{e(title)}</h2>']
    if meta:
        P.append(f'<span class="sec-meta">{e(meta)}</span>')
    P.append('</div>')
    if lede:
        P.append(f'<p class="sec-lede">{e(lede)}</p>')
    return "".join(P)


def nothing(headline: str, body: str) -> str:
    """An empty state that says which half is empty and why."""
    return (f'<div class="nothing"><b>{e(headline)}</b> {e(body)}</div>')


def callout(title: str, body: str, *, tone: str = "", badges: str = "",
            links: str = "") -> str:
    """An insight on the comparator or trends page, shaped like a decision.

    Deliberately the same shape: an insight that leads to a decision should look
    like the decision it leads to.
    """
    cls = "callout" + (f" {tone}" if tone else "")
    P = [f'<div class="{cls}">',
         f'<div class="co-t">{e(title)}{badges}</div>',
         f'<div class="co-b">{e(body)}</div>']
    if links:
        P.append(links)
    P.append('</div>')
    return "".join(P)


# --------------------------------------------------------------------------
# impact
# --------------------------------------------------------------------------

def impact_of(item: dict) -> tuple[str, str]:
    """How much a decision matters, and the reason in one clause.

    Built from things already measured — urgency, confidence, and whether a real
    price gap or a rising subject sits behind it. Deliberately hard to reach
    `critical`: if everything is critical the page has no hierarchy, and a reader
    learns to ignore the loudest thing on it.
    """
    urgency = item.get("urgency") or "watch"
    conf = (item.get("confidence") or "").upper()
    gap = item.get("gap_percent")
    stage = item.get("stage")

    score = 0
    why = []
    if urgency == "now":
        score += 3
        why.append("a competitor has already moved")
    elif urgency == "this_week":
        score += 2
        why.append("the condition is live now")
    elif urgency == "this_month":
        score += 1

    if conf == "HIGH":
        score += 2
        why.append("high-confidence evidence")
    elif conf == "MEDIUM":
        score += 1

    if isinstance(gap, (int, float)) and abs(gap) >= 25:
        score += 2
        why.append(f"a {abs(gap):.0f}% price gap")
    if stage in ("rising", "viral"):
        score += 1
        why.append(f"the subject is {stage}")

    level = ("critical" if score >= 6 else "high" if score >= 4
             else "medium" if score >= 2 else "low")
    return level, "; ".join(why) or "no strong signal behind it"
