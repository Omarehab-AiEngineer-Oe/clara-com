"""Renders the Beauty Trends page: a card grid, and a detail popup over it.

    scan the grid -> a card looks interesting -> open it -> understand it
    -> close -> keep scanning

That loop is what the layout is for. Cards stay short enough to scan a screenful
at a time; the popup carries the depth. Nothing that belongs in the popup is
allowed to creep onto a card, because a grid of paragraphs is a list nobody reads.

**Two kinds of content, never blurred.** Everything on the market side — stage,
momentum, publishers, markets, evidence, dates — is derived from what the agent
actually fetched. Everything on the capability side — what an agent can do with
this, example workflows, how to implement it — is a suggestion from this system's
own playbook, and the popup says so above the first one. A reader who cannot tell
which half is measured has been misled, however useful the suggestions are.

**The badges are real or absent.** `NEW` means first seen inside 48 hours,
`UPDATED` means the picture moved inside a week, both from stored timestamps. A
subject that has not moved carries no badge rather than a decorative one.

Also here: search, category and market filters that narrow the same grid, a URL
that carries the open trend so a card can be shared, and pagination so the grid
stays fast as the collector keeps adding subjects.
"""

from __future__ import annotations

import html
import json

from . import trend_sources as ts
from .site import CSS

STAGE_LABEL = {
    "emerging": "Emerging", "rising": "Rising", "viral": "Hot",
    "mainstream": "Mainstream", "declining": "Cooling",
}
STAGE_MEANING = {
    "emerging": "one or two publishers, and all of it recent",
    "rising": "several publishers, and this week heavier than the weeks before",
    "viral": "many publishers inside a short window",
    "mainstream": "sustained across many publishers over a long span",
    "declining": "nothing new for a long time",
}
SPREAD_LABEL = {
    "local": "One market", "regional": "Two markets",
    "moving": "Moving between markets", "global": "Global",
}
KIND_LABEL = {
    "search_demand": "search demand", "trade_press": "trade press",
    "consumer_press": "consumer press", "retail_press": "retail press",
}

PAGE_SIZE = 12

EXTRA_CSS = """
.tpage{padding-bottom:70px}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(148px,1fr));
       gap:12px;margin:20px 0 4px}
.tile{background:var(--card);border:1px solid var(--line);border-radius:6px;
      padding:14px 16px}
.tile .n{font-size:26px;font-weight:700;letter-spacing:-.02em}
.tile .l{font-size:12px;color:var(--ink3);margin-top:2px}
.tile .s{font-size:11.5px;color:var(--ink4);margin-top:5px;line-height:1.5}
.tile.r .n{color:var(--clara)}
.tile.b .n{color:var(--rival)}

.pill{font-size:10px;font-weight:700;padding:2px 7px;border-radius:3px;
      letter-spacing:.02em;white-space:nowrap}
.st-emerging{background:var(--rival-wash);color:var(--rival)}
.st-rising{background:var(--ok-wash);color:var(--ok)}
.st-viral{background:var(--clara-wash);color:var(--clara)}
.st-mainstream{background:var(--card3);color:var(--ink2)}
.st-declining{background:var(--amb-wash);color:var(--amb)}
.st-none{background:var(--card3);color:var(--ink3)}
.cf-HIGH{background:var(--ok-wash);color:var(--ok)}
.cf-MEDIUM{background:var(--amb-wash);color:var(--amb)}
.cf-LOW{background:var(--card3);color:var(--ink3)}
.cf-UNVERIFIED{background:var(--bad-wash);color:var(--bad)}
/* Freshness badges stay quiet: an outline, not a fill, so the stage stays the
   loudest thing on the card. */
.bdg{font-size:9.5px;font-weight:700;letter-spacing:.05em;padding:2px 6px;
     border-radius:3px;border:1px solid currentColor;white-space:nowrap}
.bdg-NEW{color:var(--clara)}
.bdg-UPDATED{color:var(--rival)}
/* The one exception to "quiet": a subject that has raised a decision is the
   only thing on this page that someone is being asked to act on. */
.bdg-DECISION{color:#fff;background:var(--clara);border-color:var(--clara)}

/* Decisions rendered inside a subject's popup. Same shape as a decision card on
   the Decisions page, one size down, so following one to the other is not a
   change of language. */
.tdec{background:var(--card2);border:1px solid var(--line);border-radius:7px;
      padding:13px 15px;margin-top:9px;border-inline-start:3px solid var(--clara)}
.tdec .td-top{display:flex;gap:7px;align-items:center;flex-wrap:wrap;
              margin-bottom:6px}
.tdec .td-w{font-weight:650;font-size:13.5px;line-height:1.45}
.tdec .td-y{font-size:12.5px;color:var(--ink2);line-height:1.6;margin-top:5px}
.tdec .td-o{font-size:11.5px;color:var(--ink3);margin-top:6px}

/* ---------- controls ---------- */
.controls{display:flex;flex-direction:column;gap:12px;background:var(--card);
          border:1px solid var(--line);border-radius:7px;padding:15px 16px;
          margin-top:18px}
.crow{display:flex;gap:16px;align-items:flex-end;flex-wrap:wrap}
.searchbox{flex:1 1 240px;display:flex;flex-direction:column;gap:5px;min-width:0}
.searchbox label{font-size:11px;color:var(--ink3);font-weight:600;
                 letter-spacing:.02em}
.searchbox input{font-family:inherit;font-size:14px;padding:9px 12px;
                 background:var(--bg);color:var(--ink);border-radius:6px;
                 border:1px solid var(--line2);width:100%}
.searchbox input:focus{outline:2px solid var(--clara);outline-offset:-1px;
                       border-color:var(--clara)}
.fgroup{display:flex;flex-direction:column;gap:5px}
.fgroup .flabel{font-size:11px;color:var(--ink3);font-weight:600;
                letter-spacing:.02em}
.fchips{display:flex;gap:5px;flex-wrap:wrap}
.chip{font-size:12px;padding:5px 11px;border-radius:14px;cursor:pointer;
      border:1px solid var(--line2);background:var(--bg);color:var(--ink2);
      font-family:inherit}
.chip:hover{border-color:var(--clara);color:var(--clara)}
.chip.on{background:var(--clara);color:#fff;border-color:var(--clara)}
.chip .n{opacity:.7;font-size:11px;margin-inline-start:4px}
.fcount{margin-inline-start:auto;font-size:12.5px;color:var(--ink3);
        white-space:nowrap}
.fcount b{color:var(--ink)}
.freset{font-size:12px;background:none;border:0;color:var(--rival);
        cursor:pointer;font-family:inherit;text-decoration:underline}

/* ---------- grid ---------- */
.tgrid{display:grid;grid-template-columns:repeat(4,1fr);gap:13px;margin-top:18px}
@media (max-width:1240px){.tgrid{grid-template-columns:repeat(3,1fr)}}
@media (max-width:900px){.tgrid{grid-template-columns:repeat(2,1fr)}}
@media (max-width:600px){.tgrid{grid-template-columns:1fr}}

.tcard{background:var(--card);border:1px solid var(--line);border-radius:8px;
       padding:15px 16px;cursor:pointer;text-align:start;font-family:inherit;
       display:flex;flex-direction:column;gap:9px;
       transition:border-color .13s ease, transform .13s ease,
                  box-shadow .13s ease}
.tcard:hover{border-color:var(--clara);transform:translateY(-2px);
             box-shadow:0 6px 18px rgba(0,0,0,.07)}
.tcard:focus-visible{outline:2px solid var(--clara);outline-offset:2px}
.tcard[hidden]{display:none}
.tcard.uncat{border-style:dashed}
.tcard .ctop{display:flex;gap:6px;align-items:center;flex-wrap:wrap}
.tcard .cicon{font-size:15px;line-height:1}
.tcard h3{font-size:16px;margin:0;line-height:1.32}
.tcard .cdesc{font-size:12.5px;color:var(--ink2);line-height:1.55;
              display:-webkit-box;-webkit-line-clamp:3;-webkit-box-orient:vertical;
              overflow:hidden}
.tcard .ctags{display:flex;gap:5px;flex-wrap:wrap}
.tcard .ctag{font-size:10.5px;color:var(--ink3);background:var(--card2);
             border-radius:3px;padding:2px 6px}
.tcard .cfoot{display:flex;gap:10px;align-items:center;justify-content:space-between;
              margin-top:auto;padding-top:9px;border-top:1px solid var(--line);
              font-size:11.5px;color:var(--ink3)}
.tcard .cmom{font-weight:600;color:var(--ink2);white-space:nowrap}
.tcard .cwhen{white-space:nowrap}
.tcard .cview{font-size:11.5px;color:var(--clara);font-weight:600}
.pager{display:flex;justify-content:center;margin-top:20px}
.pager button{font-family:inherit;font-size:13px;font-weight:600;padding:9px 18px;
              border-radius:6px;cursor:pointer;background:var(--card);
              color:var(--ink);border:1px solid var(--line2)}
.pager button:hover{border-color:var(--clara);color:var(--clara)}
.gridempty{grid-column:1/-1;background:var(--card2);border:1px dashed var(--line2);
           border-radius:6px;padding:20px;font-size:13.5px;color:var(--ink2);
           line-height:1.65}

/* ---------- popup ---------- */
.mask{position:fixed;inset:0;background:rgba(12,8,12,.55);display:none;
      align-items:flex-start;justify-content:center;padding:28px 18px;z-index:90;
      overflow-y:auto;opacity:0;transition:opacity .16s ease}
.mask.open{display:flex}
.mask.shown{opacity:1}
.sheet{background:var(--bg);border-radius:11px;max-width:900px;width:100%;
       box-shadow:0 26px 74px rgba(0,0,0,.42);padding:0;
       transform:translateY(10px) scale(.99);transition:transform .18s ease}
.mask.shown .sheet{transform:none}
@media (prefers-reduced-motion:reduce){
  .mask,.sheet,.tcard{transition:none}
  .sheet{transform:none}
}
/* On a phone the popup becomes a full-height sheet — still a modal, never a
   navigation away from the grid. */
@media (max-width:600px){
  .mask{padding:0;align-items:stretch}
  .sheet{border-radius:0;min-height:100dvh;max-width:none}
}
.shead{position:sticky;top:0;background:var(--bg);border-bottom:1px solid var(--line);
       padding:20px 26px 15px;display:flex;gap:12px;align-items:flex-start;
       justify-content:space-between;border-radius:11px 11px 0 0;z-index:2}
.shead h2{font-size:23px;line-height:1.25;margin:6px 0 0}
.shead .sub{font-size:13.5px;color:var(--ink2);line-height:1.6;margin-top:7px;
            max-width:62ch}
.sclose{background:var(--card2);border:1px solid var(--line2);border-radius:6px;
        font-family:inherit;font-size:18px;line-height:1;width:34px;height:34px;
        cursor:pointer;color:var(--ink2);flex:0 0 auto}
.sclose:hover{border-color:var(--clara);color:var(--clara)}
.sclose:focus-visible{outline:2px solid var(--clara);outline-offset:2px}
.sbody{padding:6px 26px 26px}
.mtag{display:block;font-size:11px;letter-spacing:.045em;text-transform:uppercase;
      color:var(--ink3);font-weight:700;margin:24px 0 9px}
.mwhy{font-size:14px;color:var(--ink2);line-height:1.7}
.mbox{background:var(--card2);border-radius:7px;padding:13px 15px;
      font-size:13px;color:var(--ink2);line-height:1.62}
.mbox b{color:var(--ink)}
.msug{border-inline-start:3px solid var(--rival);background:var(--rival-wash);
      border-radius:0 7px 7px 0;padding:11px 14px;font-size:12px;
      color:var(--ink2);line-height:1.6;margin-bottom:12px}
.mlist{margin:0;padding-inline-start:20px;font-size:13.5px;color:var(--ink2);
       line-height:1.75}
.wfchips{display:flex;gap:8px;flex-wrap:wrap}
.wfchip{font-size:12.5px;background:var(--card);border:1px solid var(--line2);
        border-radius:16px;padding:7px 13px;color:var(--ink2)}
.mgrid{display:grid;grid-template-columns:auto 1fr;gap:7px 14px;font-size:13px}
.mgrid dt{color:var(--ink3)}
.mgrid dd{color:var(--ink)}
.mstamps{display:flex;gap:20px;flex-wrap:wrap;font-size:12px;color:var(--ink3);
         background:var(--card);border:1px solid var(--line);border-radius:7px;
         padding:12px 15px}
.mstamps b{color:var(--ink2);font-weight:600;display:block;font-size:11px;
           margin-bottom:2px}
.evrow{border-bottom:1px solid var(--line);padding:11px 0}
.evrow:last-child{border-bottom:0}
.evrow a{font-size:13.5px;color:var(--ink);text-decoration:none;line-height:1.5;
         font-weight:550}
.evrow a:hover{color:var(--clara)}
.evrow .meta{font-size:11.5px;color:var(--ink4);margin-top:3px}
.hrow{display:flex;gap:10px;align-items:baseline;font-size:12.5px;padding:7px 0;
      border-bottom:1px solid var(--line);color:var(--ink2)}
.hrow:last-child{border-bottom:0}
.hrow .hw{color:var(--ink4);white-space:nowrap;font-size:11.5px;min-width:88px}
.relgrid{display:flex;gap:8px;flex-wrap:wrap}
.relchip{font-family:inherit;text-align:start;background:var(--card);
         border:1px solid var(--line2);border-radius:7px;padding:9px 13px;
         cursor:pointer;font-size:12.5px;color:var(--ink);display:flex;
         flex-direction:column;gap:3px;max-width:250px}
.relchip:hover{border-color:var(--clara)}
.relchip:focus-visible{outline:2px solid var(--clara);outline-offset:2px}
.relchip .rw{font-size:11px;color:var(--ink4)}
.np{color:var(--ink4)}
.scorehead{display:flex;gap:12px;align-items:baseline;flex-wrap:wrap;
           margin-bottom:12px}
.bignum{font-size:40px;font-weight:700;letter-spacing:-.03em;color:var(--clara);
        line-height:1}
.bigunit{font-size:15px;color:var(--ink3)}
.conflabel{font-size:12px;color:var(--ink3);line-height:1.5;max-width:44ch}
.sctable{width:100%;border-collapse:collapse;font-size:12.5px}
.sctable th{text-align:left;font-size:11px;color:var(--ink3);font-weight:600;
            padding:7px 9px;background:var(--card2)}
.sctable td{padding:7px 9px;border-bottom:1px solid var(--line)}
.sctable td.num{text-align:right;font-variant-numeric:tabular-nums;
                white-space:nowrap}
.sctable tr.unmeasured td{color:var(--ink4)}
.minibar{height:5px;border-radius:3px;background:var(--card3);min-width:70px}
.minibar span{display:block;height:100%;border-radius:3px;background:var(--clara)}
.basisnote{font-size:11px;color:var(--ink4)}
.hiddenbox{background:var(--clara-wash);border:1px solid var(--clara);
           border-radius:7px;padding:12px 14px;font-size:13px;color:var(--ink2);
           line-height:1.6;margin-top:14px}
.ideablock{margin-top:12px}
.ideahead{font-size:12px;font-weight:700;color:var(--ink2);margin-bottom:4px}

/* ---------- daily report lists ---------- */
.rlists{margin-top:22px}
.rlist{background:var(--card);border:1px solid var(--line);border-radius:8px;
       padding:16px 18px;margin-bottom:13px}
.rlist h3{font-size:16.5px;margin:0 0 3px;display:flex;gap:8px;
          align-items:baseline;flex-wrap:wrap}
.rlist .rcut{font-size:11.5px;color:var(--ink3);font-weight:600}
.rlist .rblurb{font-size:12.5px;color:var(--ink2);line-height:1.6;
               margin:6px 0 12px;max-width:78ch}
.rrow{display:grid;grid-template-columns:38px 1fr auto;gap:11px;
      align-items:baseline;padding:9px 0;border-top:1px solid var(--line);
      font-size:13px;cursor:pointer}
.rrow:first-of-type{border-top:0}
.rrow:hover .rname{color:var(--clara)}
.rscore{font-variant-numeric:tabular-nums;font-weight:700;font-size:15px;
        color:var(--clara);text-align:right}
.rname{font-weight:600;color:var(--ink)}
.rwhy{font-size:11.5px;color:var(--ink3);line-height:1.5;margin-top:2px}
.rmeta{font-size:11px;color:var(--ink4);white-space:nowrap}
.rempty{font-size:12.5px;color:var(--ink3);font-style:italic;padding:8px 0}
.rgrid{display:grid;grid-template-columns:repeat(auto-fit,minmax(400px,1fr));
       gap:13px}
.hidden-badge{background:var(--clara);color:#fff;font-size:9px;font-weight:700;
              padding:2px 5px;border-radius:3px;letter-spacing:.04em}
.scorebar{display:flex;gap:3px;margin-top:6px}
.scorebar span{height:4px;border-radius:2px;flex:1;background:var(--card3)}
.scorebar span.on{background:var(--clara)}
.notmeasured{background:var(--bad-wash);color:var(--bad);font-size:11px;
             padding:2px 7px;border-radius:3px;font-weight:600}
"""


def _e(v) -> str:
    return html.escape(str(v if v is not None else ""))


# --------------------------------------------------------------------------

def _head(b: dict, decisions: list | None = None) -> str:
    c = b["counts"]
    srcs = b.get("sources") or []
    read = sum(1 for s in srcs if s.get("ok"))
    refused = len(b.get("refused") or [])
    dead = len(b.get("dead") or [])

    P = ['<header class="top"><div class="wrap"><div class="hrow"><div>']
    P.append('<p class="eyebrow">Clara beauty trends</p>')
    P.append('<h1 style="margin-top:10px">What the market is talking about, '
             'as of the last scan</h1>')
    P.append('<p class="lede">One card per subject the sources are covering. Open '
             'any of them for the full profile: why it is trending, what an agent '
             'can do with it, example workflows, every headline behind it, and '
             'related subjects. Nothing here is a curated list &mdash; run a scan '
             'and the page changes, because the sources changed.</p>')
    P.append('</div></div>')

    decisions = decisions or []
    carrying = len({d.get("topic_key") for d in decisions if d.get("topic_key")})

    tiles = [
        ("Trends", c["topics"], "subjects with evidence", "r"),
        ("Signals held", c["signals"],
         f"across {c['scans']} scan(s), accumulated", "b"),
        ("Moved this week", c["changed_recently"],
         "gained evidence or changed stage", "r"),
        ("Markets", c["markets"], "with at least one signal", ""),
        ("Publishers", c["publishers"], "named behind the evidence", "b"),
        ("Feeds read", f"{c['feeds_read']}/{c['feeds_tried']}",
         "on the last scan", ""),
        ("Carrying a decision", carrying,
         "hooked to a Clara product", "b"),
    ]
    P.append('<div class="tiles">')
    for label, n, sub, cls in tiles:
        P.append(f'<div class="tile {cls}"><div class="n">{_e(n)}</div>'
                 f'<div class="l">{_e(label)}</div>'
                 f'<div class="s">{_e(sub)}</div></div>')
    P.append('</div>')

    P.append('<div class="note">')
    P.append(f'<b>Last scan {_e(b["scan_ago"])}</b> &mdash; {_e(b["scan_when"])}. ')
    P.append(f'{read} feed(s) answered; <b>{refused}</b> publisher(s) refuse '
             f'automated access and <b>{dead}</b> feed(s) no longer exist. Each '
             f'trend repeats that inside its own source block rather than hiding '
             f'it. ')
    P.append('Stages measure how many publishers carried a subject, over how long, '
             'and whether the last week is heavier than the weeks before &mdash; '
             'that is <b>attention</b>, not sales. Capability suggestions inside a '
             'trend are this system\'s own playbook and are labelled as such.')
    P.append('</div>')
    P.append('</div></header>')
    return "\n".join(P)


# --------------------------------------------------------------------------
# the daily-report lists
# --------------------------------------------------------------------------

def _score(t: dict) -> int:
    return ((t.get("score") or {}).get("total")) or 0


def _comp(t: dict, name: str) -> int:
    return ((t.get("score") or {}).get("components") or {}).get(name, 0)


def _rows(topics: list, cut, limit: int = 10, key=None) -> list:
    """Everything that meets the cut, up to the limit. Never padded."""
    hit = [t for t in topics if cut(t)]
    hit.sort(key=key or (lambda t: -_score(t)))
    return hit[:limit]


def _list_block(title: str, cut_label: str, blurb: str, rows: list,
                meta=None, empty: str = "") -> str:
    P = ['<div class="rlist">']
    P.append(f'<h3>{title}'
             f'<span class="rcut">{_e(len(rows))} &middot; {_e(cut_label)}</span>'
             f'</h3>')
    P.append(f'<p class="rblurb">{_e(blurb)}</p>')
    if not rows:
        P.append(f'<div class="rempty">{_e(empty or "Nothing meets this cut.")}'
                 f'</div>')
    for t in rows:
        sc = _score(t)
        P.append(f'<div class="rrow" data-open="{_e(t.get("key"))}">')
        P.append(f'<div class="rscore">{_e(sc)}</div>')
        P.append('<div><div class="rname">'
                 + (f'{_e(t.get("icon"))} ' if t.get("icon") else '')
                 + _e(t.get("label"))
                 + (' <span class="hidden-badge">HIDDEN</span>'
                    if (t.get("hidden") or {}).get("is_hidden") else '')
                 + '</div>')
        why = (meta(t) if meta else
               (t.get("stage_why") or t.get("why_it_matters") or ""))
        P.append(f'<div class="rwhy">{_e(why)}</div>')
        P.append('</div>')
        P.append(f'<div class="rmeta">{_e(STAGE_LABEL.get(t.get("stage"), ""))}'
                 f'<br>{_e(t.get("changed_ago"))}</div>')
        P.append('</div>')
    P.append('</div>')
    return "\n".join(P)


def _report(b: dict) -> str:
    """Seven ranked lists, all cut from the same scored set."""
    topics = b.get("topics") or []
    if not topics:
        return ""

    P = ['<section id="report"><div class="wrap">']
    P.append('<div class="shead"><h2>\U0001f525 The report</h2>'
             f'<p class="eyebrow">{len(topics)} scored subject(s)</p></div>')
    P.append('<p class="lede">Every list below is cut from the same scored set, '
             'so the numbers agree between them. The score is '
             '<b>growth 25% &middot; search 20% &middot; cross-platform 15% '
             '&middot; commercial 10% &middot; novelty 10%</b> &mdash; and '
             '<span class="notmeasured">social engagement 20%: not '
             'measured</span>, because every platform that has per-post metrics '
             'puts them behind a login this operator does not hold. Its weight is '
             'redistributed across the five measured components rather than '
             'scored zero or filled with a plausible number. No list is padded to '
             'ten: if six subjects meet the cut, six appear.</p>')

    P.append('<div class="rlists"><div class="rgrid">')

    P.append(_list_block(
        "\U0001f525 Top 10 right now", "highest total score",
        "The overall ranking. Click any row to open the full profile with its "
        "evidence, sources and score breakdown.",
        _rows(topics, lambda t: _score(t) > 0, 10)))

    P.append(_list_block(
        "\U0001f4c8 Fastest growing", "growth component 50+",
        "Ranked on acceleration alone \u2014 items in the last seven days "
        "against the three weeks before. This is the component that answers "
        "\u201cis it moving\u201d rather than \u201cis it big\u201d.",
        _rows(topics, lambda t: _comp(t, "growth") >= 50, 10,
              key=lambda t: -_comp(t, "growth")),
        meta=lambda t: (f"{(t.get('score') or {}).get('counts', {}).get('recent_7d', 0)}"
                        f" item(s) in the last week against "
                        f"{(t.get('score') or {}).get('counts', {}).get('prior_21d', 0)}"
                        f" in the three before"),
        empty="Nothing is accelerating hard enough to clear the cut. That is a "
              "real answer, not a gap."))

    P.append(_list_block(
        "\U0001f440 Emerging", "stage emerging",
        "Early and thin by definition \u2014 one or two publishers, all of it "
        "recent. Highest upside and lowest certainty, which is why the "
        "confidence figure matters more here than the score.",
        _rows(topics, lambda t: t.get("stage") == "emerging", 10)))

    P.append(_list_block(
        "\U0001f48e Low-competition opportunities", "growth or search 50+, "
        "coverage low or medium, relevant to Clara",
        "The three conditions together: it is moving, few publishers are on it, "
        "and Clara sells into it or to the same buyer. Obscure on its own is not "
        "an opportunity.",
        _rows(topics, lambda t: (t.get("hidden") or {}).get("is_hidden"), 10),
        meta=lambda t: (t.get("hidden") or {}).get("why", ""),
        empty="Nothing currently meets all three conditions."))

    P.append(_list_block(
        "\U0001f680 Could become huge", "rising or viral, growth 45+, "
        "commercial 60+",
        "Moving, broad, and worth money to Clara specifically. A prediction "
        "about direction, built from the measured components rather than "
        "asserted.",
        _rows(topics, lambda t: (t.get("stage") in ("rising", "viral")
                                 and _comp(t, "growth") >= 45
                                 and _comp(t, "commercial") >= 60), 10),
        meta=lambda t: (t.get("outlook") or {}).get("next_3_6_months", ""),
        empty="Nothing clears all three cuts right now."))

    P.append(_list_block(
        "\U0001f4c9 Declining", "stage declining",
        "No new evidence for a long time. Kept visible so a subject is not "
        "quietly dropped \u2014 and so a revival is noticeable when it happens.",
        _rows(topics, lambda t: t.get("stage") == "declining", 5,
              key=lambda t: t.get("changed_at") or ""),
        meta=lambda t: t.get("stage_why", "")))

    P.append(_list_block(
        "\U0001f4b0 Commercial opportunities", "direct or adjacent to what "
        "Clara sells, not declining",
        "Ranked by score among subjects Clara could actually act on. Open a row "
        "for the evidence behind it and where it does or does not fit.",
        _rows(topics, lambda t: (t.get("clara_relevance") in ("direct", "adjacent")
                                 and t.get("stage") != "declining"), 10),
        meta=lambda t: ((t.get("commercial") or {}).get("clara_fit", "")
                        or t.get("why_it_matters", ""))))

    P.append('</div></div>')
    P.append('</div></section>')
    return "\n".join(P)


def _controls(b: dict) -> str:
    topics = b.get("topics") or []
    labels = b.get("market_label") or {}
    order = b.get("market_order") or []

    per_market: dict = {}
    per_stage: dict = {}
    per_cat: dict = {}
    for t in topics:
        for m in t.get("markets") or []:
            per_market[m] = per_market.get(m, 0) + 1
        per_stage[t["stage"]] = per_stage.get(t["stage"], 0) + 1
        cat = t.get("category") or ""
        if cat:
            per_cat[cat] = per_cat.get(cat, 0) + 1

    P = ['<div class="controls">']

    P.append('<div class="crow">')
    P.append('<div class="searchbox"><label for="f-q">Search</label>'
             '<input id="f-q" type="search" autocomplete="off" '
             'placeholder="title, tag, publisher or market…"></div>')
    P.append('<div class="fgroup"><span class="flabel">Category</span>'
             '<div class="fchips" id="f-cat">')
    P.append('<button class="chip on" data-all="1">All</button>')
    for cat, n in sorted(per_cat.items(), key=lambda kv: -kv[1]):
        P.append(f'<button class="chip" data-cat="{_e(cat)}">'
                 f'{_e(ts.CATEGORY_LABEL.get(cat, cat))}'
                 f'<span class="n">{n}</span></button>')
    P.append('</div></div>')
    P.append('</div>')

    P.append('<div class="crow">')
    P.append('<div class="fgroup"><span class="flabel">Market</span>'
             '<div class="fchips" id="f-market">')
    P.append('<button class="chip on" data-all="1">All</button>')
    for m in order:
        P.append(f'<button class="chip" data-market="{_e(m)}">'
                 f'{_e(labels.get(m, m))}<span class="n">'
                 f'{per_market.get(m, 0)}</span></button>')
    P.append('</div></div>')

    P.append('<div class="fgroup"><span class="flabel">Stage</span>'
             '<div class="fchips" id="f-stage">')
    P.append('<button class="chip on" data-all="1">All</button>')
    for st in ("emerging", "rising", "viral", "mainstream", "declining"):
        if not per_stage.get(st):
            continue
        P.append(f'<button class="chip" data-stage="{_e(st)}">'
                 f'{_e(STAGE_LABEL[st])}<span class="n">{per_stage[st]}</span>'
                 f'</button>')
    P.append('</div></div>')

    P.append('<div class="fgroup"><span class="flabel">Changed</span>'
             '<div class="fchips" id="f-recent">')
    P.append('<button class="chip on" data-all="1">Any time</button>')
    for key, lab, buckets in (
            ("today", "Today", ("last_hour", "today")),
            ("this_week", "This week", ("last_hour", "today", "this_week"))):
        n = sum(1 for t in topics if t.get("bucket") in buckets)
        if not n:
            continue
        P.append(f'<button class="chip" data-recent="{_e(key)}">{_e(lab)}'
                 f'<span class="n">{n}</span></button>')
    P.append('</div></div>')

    P.append(f'<span class="fcount"><b id="f-shown">{len(topics)}</b> of '
             f'{len(topics)} shown '
             '<button class="freset" id="f-reset">reset</button></span>')
    P.append('</div>')
    P.append('</div>')
    return "\n".join(P)


def _card(i: int, t: dict, has_decision: bool = False) -> str:
    """A card carries only what can be scanned. Depth lives in the popup."""
    haystack = " ".join([
        t.get("label") or "", t.get("why_it_matters") or "",
        t.get("category_label") or "",
        " ".join(t.get("tags") or []),
        " ".join(t.get("publishers") or []),
        " ".join(t.get("market_labels") or []),
    ]).lower()

    P = ['<button class="tcard" data-i="%d" data-key="%s" data-stage="%s" '
         'data-cat="%s" data-markets="%s" data-bucket="%s" data-q="%s" '
         'aria-haspopup="dialog">'
         % (i, _e(t.get("key")), _e(t.get("stage")), _e(t.get("category")),
            _e(",".join(t.get("markets") or [])), _e(t.get("bucket")),
            _e(haystack))]

    P.append('<div class="ctop">')
    P.append(f'<span class="cicon" aria-hidden="true">{_e(t.get("icon"))}</span>')
    P.append(f'<span class="pill st-{_e(t.get("stage"))}">'
             f'{_e(STAGE_LABEL.get(t.get("stage"), t.get("stage")))}</span>')
    if t.get("badge"):
        P.append(f'<span class="bdg bdg-{_e(t["badge"])}">'
                 f'{_e(t.get("badge_label"))}</span>')
    P.append(f'<span class="pill cf-{_e(t.get("confidence"))}">'
             f'{_e(t.get("confidence"))}</span>')
    # The one badge that means "someone has to act on this", so a reader
    # scanning the grid can find the actionable subjects without opening any.
    if has_decision:
        P.append('<span class="bdg bdg-DECISION" '
                 'title="A decision has been raised from this subject">'
                 'Decision</span>')
    P.append('</div>')

    P.append(f'<h3>{_e(t.get("label"))}</h3>')
    if t.get("why_it_matters"):
        P.append(f'<div class="cdesc">{_e(t["why_it_matters"])}</div>')

    tags = (t.get("tags") or [])[:3]
    if tags:
        P.append('<div class="ctags">'
                 + "".join(f'<span class="ctag">#{_e(x)}</span>' for x in tags)
                 + '</div>')

    P.append('<div class="cfoot">')
    P.append(f'<span class="cmom">{_e(t.get("momentum"))} '
             f'{_e(t.get("momentum_label"))}</span>')
    P.append(f'<span class="cwhen" title="{_e(t.get("changed_when"))}">'
             f'Updated {_e(t.get("changed_ago"))}</span>')
    P.append('</div>')
    P.append('<div class="cview">View details &rarr;</div>')
    P.append('</button>')
    return "\n".join(P)


def _cards(b: dict, decisions: list | None = None) -> str:
    topics = b.get("topics") or []
    uncat = b.get("uncategorised") or []
    dec_keys = {d.get("topic_key") for d in (decisions or []) if d.get("topic_key")}

    P = ['<section id="trends"><div class="wrap">']
    P.append(_controls(b))
    P.append('<div class="tgrid" id="tgrid">')
    for i, t in enumerate(topics):
        P.append(_card(i, t, t.get("key") in dec_keys))

    if uncat:
        P.append('<button class="tcard uncat" data-i="-1" data-key="uncategorised" '
                 'data-stage="none" data-cat="" data-markets="" '
                 'data-bucket="unknown" data-nocount="1" '
                 'data-q="uncategorised unmatched signals" '
                 'aria-haspopup="dialog">')
        P.append('<div class="ctop"><span class="cicon" aria-hidden="true">'
                 '\U0001f50e</span>'
                 '<span class="pill st-none">Not yet a subject</span></div>')
        P.append('<h3>Uncategorised signals</h3>')
        P.append('<div class="cdesc">Read from the feeds but matching none of the '
                 'subjects above. Kept visible so the gap between what was '
                 'collected and what has been categorised is not hidden.</div>')
        P.append(f'<div class="cfoot"><span class="cmom">{len(uncat)} item(s)'
                 '</span></div>')
        P.append('<div class="cview">Open the list &rarr;</div>')
        P.append('</button>')

    P.append('<div class="gridempty" id="gridempty" hidden>'
             '<b>Nothing matches those filters.</b> Clear one of them, or reset '
             'to see every subject again.</div>')
    P.append('</div>')
    P.append('<div class="pager" id="pager" hidden>'
             '<button type="button" id="pagemore">Show more</button></div>')
    P.append('<p class="note" style="margin-top:18px">Cards stay short so a '
             'screenful can be scanned; each one opens the full profile. A stage '
             'is a measurement and the popup shows its arithmetic.</p>')
    P.append('</div></section>')
    return "\n".join(P)


def _payload(b: dict, decisions: list | None = None) -> str:
    """Everything the popup needs, embedded once.

    Only the fields the popup renders. Raw signal rows and internal keys stay out
    — `/trends.json` has them, and shipping them here would grow the page for
    detail nobody opens.
    """
    KEEP = ("key", "label", "stage", "stage_why", "spread", "confidence",
            "why_it_matters", "clara_relevance", "category", "category_label",
            "icon", "tags", "agent_can", "workflows", "implement",
            "markets", "market_labels", "publishers", "publisher_count",
            "signal_count", "search_demand_signals", "evidence", "history",
            "related", "badge", "badge_label", "momentum", "momentum_label",
            "first_ago", "first_when", "ago", "checked_when",
            "changed_ago", "changed_when", "last_change_note",
            # the scorecard and everything derived from it
            "score", "confidence_score", "competition", "outlook", "hidden",
            "subcategory", "platform", "audience", "commercial", "ideas")
    topics = [{k: t.get(k) for k in KEEP} for t in (b.get("topics") or [])]
    uncat = [{k: u.get(k) for k in
              ("title", "url", "publisher", "market_label", "kind", "ago",
               "when", "search_volume")}
             for u in (b.get("uncategorised") or [])]
    sources = [{k: s.get(k) for k in
                ("publisher", "url", "ok", "signal", "kept", "items", "ago",
                 "when", "what_to_do")}
               for s in (b.get("sources") or [])]
    # Only what the popup shows. A decision is rendered inside the subject that
    # raised it so the reader does not have to hold a topic key in their head and
    # go looking on another page.
    by_topic: dict = {}
    for d in (decisions or []):
        k = d.get("topic_key")
        if not k:
            continue
        by_topic.setdefault(k, []).append({
            "what": d.get("what"), "why": d.get("why"),
            "owner": d.get("owner"), "impact": d.get("impact"),
            "urgency": d.get("urgency"), "confidence": d.get("confidence"),
            "insight": d.get("insight"), "product": (d.get("relevant") or {}).get("comparison"),
        })

    payload = {
        "topics": topics,
        "decisions_by_topic": by_topic,
        "uncategorised": uncat,
        "sources": sources,
        "refused": b.get("refused") or [],
        "dead": b.get("dead") or [],
        "stage_meaning": STAGE_MEANING,
        "stage_label": STAGE_LABEL,
        "spread_label": SPREAD_LABEL,
        "kind_label": KIND_LABEL,
        "page_size": PAGE_SIZE,
    }
    blob = json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")
    return f'<script>window.__TRENDS__={blob};</script>'


MODAL_JS = r"""
(function(){
  var DATA = window.__TRENDS__ || {topics:[], uncategorised:[], sources:[]};
  var grid = document.getElementById('tgrid');
  var mask = document.getElementById('mask');
  var sheet = document.getElementById('sheet');
  if(!grid || !mask || !sheet) return;

  var BY_KEY = {};
  (DATA.topics||[]).forEach(function(t, i){ BY_KEY[t.key] = {t:t, i:i}; });

  // Same words as the Decisions page. One vocabulary across three pages.
  var IMPACT_LABEL = {critical:'Critical', high:'High impact',
                      medium:'Medium impact', low:'Low impact'};
  var URGENCY_LABEL = {now:'Today', this_week:'This week',
                       this_month:'This month', watch:'Watch'};

  function esc(s){
    return String(s == null ? '' : s).replace(/[&<>"']/g, function(c){
      return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c];
    });
  }
  function none(){ return '<span class="np">&mdash;</span>'; }

  // ------------------------------------------------------------ popup content
  function evidenceRows(list){
    if(!list || !list.length) return '<p class="mbox">No item is attached.</p>';
    return list.map(function(e){
      var t = e.url
        ? '<a href="'+esc(e.url)+'" rel="nofollow noopener">'+esc(e.title)+'</a>'
        : '<span>'+esc(e.title)+'</span>';
      var bits = [esc(e.publisher)];
      if(e.ago) bits.push('<span title="'+esc(e.when||'')+'">'+esc(e.ago)+'</span>');
      if(e.market) bits.push(esc(e.market));
      if(e.kind) bits.push(esc((DATA.kind_label||{})[e.kind] || e.kind));
      if(e.search_volume) bits.push(esc(e.search_volume)+' searches');
      return '<div class="evrow">'+t+'<div class="meta">'+bits.join(' &middot; ')+
             '</div></div>';
    }).join('');
  }

  function sourceBlock(publishers){
    var named = publishers || [];
    var read = (DATA.sources||[]).filter(function(s){
      return s.ok && named.indexOf(s.publisher) >= 0;
    });
    var h = ['<span class="mtag">Sources</span>'];
    if(read.length){
      h.push('<div>' + read.map(function(s){
        return '<div class="evrow"><a href="'+esc(s.url)+
               '" rel="nofollow noopener">'+esc(s.publisher)+'</a>'+
               '<div class="meta">checked <span title="'+esc(s.when||'')+'">'+
               esc(s.ago)+'</span> &middot; '+esc(s.kept)+' of '+esc(s.items)+
               ' item(s) kept</div></div>';
      }).join('') + '</div>');
    } else {
      h.push('<p class="mbox">'+esc(named.join(', ') || 'unknown')+'</p>');
    }
    var bad = (DATA.sources||[]).filter(function(s){ return !s.ok; });
    var dead = DATA.dead || [];
    if(bad.length || dead.length){
      h.push('<p class="mbox" style="margin-top:10px"><b>Not read on the last '+
             'scan:</b> '+bad.length+' publisher(s) refused automated access and '+
             dead.length+' feed(s) no longer exist. This subject could be wider '+
             'than what is shown &mdash; the sweep is not complete and does not '+
             'claim to be.</p>');
    }
    return h.join('');
  }

  function topicHTML(t){
    var stage = (DATA.stage_label||{})[t.stage] || t.stage;
    var h = [];

    h.push('<div class="shead"><div>');
    h.push('<div style="display:flex;gap:6px;align-items:center;flex-wrap:wrap">');
    h.push('<span aria-hidden="true">'+esc(t.icon)+'</span>');
    h.push('<span class="pill st-'+esc(t.stage)+'">'+esc(stage)+'</span>');
    if(t.badge) h.push('<span class="bdg bdg-'+esc(t.badge)+'">'+
                       esc(t.badge_label)+'</span>');
    h.push('<span class="pill cf-'+esc(t.confidence)+'">'+esc(t.confidence)+
           '</span>');
    h.push('<span class="ctag">'+esc(t.category_label)+'</span>');
    h.push('</div>');
    h.push('<h2 id="sheet-title">'+esc(t.label)+'</h2>');
    if(t.why_it_matters) h.push('<p class="sub">'+esc(t.why_it_matters)+'</p>');
    h.push('</div><button class="sclose" data-close aria-label="Close">'+
           '×</button></div>');

    h.push('<div class="sbody">');

    // The score first: it is the claim the rest of the panel rests on, and it
    // carries a hole a reader has to be told about at the point of the number.
    if(t.score){
      var sc = t.score, cs = t.confidence_score || {};
      h.push('<span class="mtag">Trend score</span>');
      h.push('<div class="scorehead"><span class="bignum">'+esc(sc.total)+
             '</span><span class="bigunit">/100</span>');
      if(cs.value != null)
        h.push('<span class="conflabel">confidence '+esc(cs.value)+
               '/100 &mdash; '+esc(cs.why)+'</span>');
      h.push('</div>');

      var W = sc.weights || {};
      var order = ['growth','search','cross_platform','commercial','novelty'];
      var NAMES = {growth:'Growth', search:'Search momentum',
                   cross_platform:'Cross-platform', commercial:'Commercial',
                   novelty:'Novelty'};
      h.push('<table class="sctable"><thead><tr><th>Component</th>'+
             '<th>Weight</th><th>Score</th><th></th></tr></thead><tbody>');
      order.forEach(function(k){
        var v = (sc.components||{})[k] || 0;
        h.push('<tr><td>'+esc(NAMES[k])+'</td><td class="num">'+
               Math.round((W[k]||0)*100)+'%</td><td class="num">'+esc(v)+
               '</td><td><div class="minibar"><span style="width:'+v+
               '%"></span></div></td></tr>');
      });
      var soc = sc.social || {};
      h.push('<tr class="unmeasured"><td>Social engagement</td>'+
             '<td class="num">'+Math.round((W.social||0)*100)+'%</td>'+
             '<td class="num">&mdash;</td><td><span class="notmeasured">'+
             'not measured</span></td></tr>');
      h.push('</tbody></table>');
      h.push('<p class="mbox">'+esc(soc.why || '')+'</p>');

      var c = sc.counts || {};
      h.push('<dl class="mgrid" style="margin-top:12px">');
      h.push('<dt>Last 7 days</dt><dd>'+esc(c.recent_7d)+' item(s)</dd>');
      h.push('<dt>Three weeks before</dt><dd>'+esc(c.prior_21d)+' item(s)</dd>');
      if(t.competition)
        h.push('<dt>Competition</dt><dd>'+esc(t.competition.level)+' &mdash; '+
               esc(t.competition.note)+'<br><span class="basisnote">'+
               esc(t.competition.basis)+'</span></dd>');
      if(t.platform)
        h.push('<dt>Best platform</dt><dd>'+esc(t.platform.platform)+' &mdash; '+
               esc(t.platform.why)+'<br><span class="basisnote">'+
               esc(t.platform.basis)+'</span></dd>');
      if(t.audience)
        h.push('<dt>Audience</dt><dd>'+esc(t.audience.audience)+
               '<br><span class="basisnote">'+esc(t.audience.basis)+
               '</span></dd>');
      h.push('</dl>');

      if(t.hidden && t.hidden.is_hidden){
        h.push('<p class="hiddenbox"><b>\U0001f48e Hidden opportunity</b> '+
               esc(t.hidden.why)+'</p>');
      }
    }

    if(t.outlook){
      h.push('<span class="mtag">Outlook</span>');
      h.push('<p class="msug">'+esc(t.outlook.basis)+'</p>');
      h.push('<dl class="mgrid">');
      h.push('<dt>Next 7 days</dt><dd>'+esc(t.outlook.next_7_days)+'</dd>');
      h.push('<dt>Next 30 days</dt><dd>'+esc(t.outlook.next_30_days)+'</dd>');
      h.push('<dt>3&ndash;6 months</dt><dd>'+esc(t.outlook.next_3_6_months)+
             '</dd>');
      h.push('<dt>Estimated lifespan</dt><dd>'+esc(t.outlook.lifespan)+'</dd>');
      h.push('</dl>');
    }

    h.push('<span class="mtag">Why is this trending?</span>');
    h.push('<div class="mbox"><b>'+esc(t.stage_why)+'</b><br><br>'+esc(stage)+
           ' means: '+esc((DATA.stage_meaning||{})[t.stage] || '')+
           '. That is a count of publishers and dates, not a sales figure &mdash; '+
           'no activity number here is estimated.</div>');

    h.push('<span class="mtag">Reach</span>');
    h.push('<dl class="mgrid">');
    h.push('<dt>Spread</dt><dd>'+
           esc((DATA.spread_label||{})[t.spread] || t.spread)+'</dd>');
    h.push('<dt>Markets</dt><dd>'+
           (esc((t.market_labels||[]).join(', '))||none())+'</dd>');
    h.push('<dt>Publishers</dt><dd>'+
           (esc((t.publishers||[]).join(', '))||none())+'</dd>');
    h.push('<dt>Items</dt><dd>'+esc(t.signal_count)+'</dd>');
    h.push('<dt>Search demand</dt><dd>'+
           (t.search_demand_signals
             ? esc(t.search_demand_signals)+' rising query/queries' : none())+
           '</dd>');
    h.push('<dt>Relevance to Clara</dt><dd>'+(esc(t.clara_relevance)||none())+
           '</dd>');
    h.push('</dl>');

    if((t.agent_can||[]).length || (t.workflows||[]).length || t.implement){
      h.push('<span class="mtag">What an agent can do with this</span>');
      h.push('<div class="msug">These are suggestions from this system’s own '+
             'playbook &mdash; what the Clara agent could do about the subject. '+
             'They are not findings about the market, and nothing below is '+
             'evidence.</div>');
    }
    if((t.agent_can||[]).length){
      h.push('<ul class="mlist">'+t.agent_can.map(function(x){
        return '<li>'+esc(x)+'</li>'; }).join('')+'</ul>');
    }
    if((t.workflows||[]).length){
      h.push('<span class="mtag">Example workflows</span>');
      h.push('<div class="wfchips">'+t.workflows.map(function(x){
        return '<span class="wfchip">'+esc(x)+'</span>'; }).join('')+'</div>');
    }
    if(t.implement){
      h.push('<span class="mtag">How to implement it</span>');
      h.push('<div class="mbox">'+esc(t.implement)+'</div>');
    }

    h.push('<span class="mtag">Evidence &mdash; '+esc(t.signal_count)+
           ' item(s), newest first</span>');
    h.push(evidenceRows(t.evidence));

    h.push(sourceBlock(t.publishers));

    if(t.commercial){
      h.push('<span class="mtag">Commercial read</span>');
      h.push('<div class="mbox"><b>Evidence:</b> '+
             esc((t.commercial.evidence||[]).join('; '))+'<br><br>'+
             esc(t.commercial.clara_fit)+'</div>');
      h.push('<p class="msug">Category list below is an agent suggestion; the '+
             'evidence line above is measured.</p>');
      h.push('<div class="wfchips">'+(t.commercial.categories||[]).map(
        function(x){ return '<span class="wfchip">'+esc(x)+'</span>'; }
      ).join('')+'</div>');
    }

    if(t.ideas){
      var I = t.ideas;
      h.push('<span class="mtag">Content ideas</span>');
      h.push('<div class="msug"><b>Agent-generated, not measured.</b> '+
             esc(I.basis)+'</div>');
      var BLOCKS = [
        ['TikTok', I.tiktok], ['Instagram Reels', I.reels],
        ['YouTube', I.youtube], ['Pinterest', I.pinterest],
        ['Hooks', I.hooks], ['Educational', I.educational],
        ['Product-focused', I.product],
      ];
      BLOCKS.forEach(function(pair){
        if(!pair[1] || !pair[1].length) return;
        h.push('<div class="ideablock"><div class="ideahead">'+esc(pair[0])+
               '</div><ul class="mlist">'+pair[1].map(function(x){
                 return '<li>'+esc(x)+'</li>'; }).join('')+'</ul></div>');
      });
    }

    if(t.history && t.history.length){
      h.push('<span class="mtag">How it has moved</span>');
      h.push(t.history.map(function(e){
        return '<div class="hrow"><span class="hw" title="'+esc(e.when||'')+'">'+
               esc(e.ago)+'</span><span><b>'+esc(e.label)+'</b> &mdash; '+
               esc(e.detail)+'</span></div>';
      }).join(''));
    }

    h.push('<span class="mtag">Freshness</span>');
    h.push('<div class="mstamps">');
    h.push('<span><b>First seen</b><span title="'+esc(t.first_when||'')+'">'+
           esc(t.first_ago)+'</span></span>');
    h.push('<span><b>Last verified</b><span title="'+esc(t.checked_when||'')+'">'+
           esc(t.ago)+'</span></span>');
    h.push('<span><b>Last changed</b><span title="'+esc(t.changed_when||'')+'">'+
           esc(t.changed_ago)+'</span></span>');
    h.push('</div>');

    var decs = (DATA.decisions_by_topic||{})[t.key] || [];
    if(decs.length){
      h.push('<span class="mtag">Decisions this raises ('+decs.length+')</span>');
      h.push('<p class="mnote">These are on the Decisions page too. They appear '+
             'here because a trend only matters once it is attached to a Clara '+
             'product and someone is asked to act — and that is the same '+
             'decision, not a second one.</p>');
      decs.forEach(function(d){
        h.push('<div class="tdec"><div class="td-top">');
        if(d.impact) h.push('<span class="bx bx-'+esc(d.impact)+'">'+
                            esc(IMPACT_LABEL[d.impact]||d.impact)+'</span>');
        if(d.urgency) h.push('<span class="bx bx-'+esc(d.urgency)+'">'+
                             esc(URGENCY_LABEL[d.urgency]||d.urgency)+'</span>');
        if(d.confidence) h.push('<span class="bx bx-'+esc(d.confidence)+'">'+
                                esc(d.confidence)+'</span>');
        h.push('</div>');
        h.push('<div class="td-w">'+esc(d.what)+'</div>');
        if(d.why) h.push('<div class="td-y">'+esc(d.why)+'</div>');
        h.push('<div class="td-o">'+esc(d.owner||'')+
               (d.product? ' · on '+esc(d.product) : '')+'</div>');
        h.push('</div>');
      });
      h.push('<div class="xlinks"><a class="xlink primary" href="/decisions">'+
             '<span class="xi">→</span><span>Open on the Decisions page'+
             '</span></a><a class="xlink" href="/#prices">'+
             '<span class="xi">▤</span><span>See the product in the '+
             'comparison</span></a></div>');
    } else {
      h.push('<span class="mtag">Decisions this raises</span>');
      h.push('<p class="mnote">None. A subject only becomes a decision when it '+
             'can be attached to a specific product in Clara’s catalogue — '+
             'without one there is nothing to act on, and inventing an action '+
             'would be worse than saying so. It stays tracked either way.</p>');
      h.push('<div class="xlinks"><a class="xlink" href="/decisions">'+
             '<span class="xi">→</span><span>Every open decision</span>'+
             '</a></div>');
    }

    if((t.related||[]).length){
      h.push('<span class="mtag">Related trends</span>');
      h.push('<div class="relgrid">'+t.related.map(function(r){
        return '<button class="relchip" data-rel="'+esc(r.key)+'">'+
               '<span>'+esc(r.icon||'')+' '+esc(r.label)+'</span>'+
               '<span class="rw">'+esc(r.why)+'</span></button>';
      }).join('')+'</div>');
    }

    h.push('</div>');
    return h.join('');
  }

  function uncatHTML(){
    var list = DATA.uncategorised || [];
    var h = [];
    h.push('<div class="shead"><div><h2 id="sheet-title">Uncategorised signals'+
           '</h2><p class="sub">'+list.length+' item(s) read from the feeds that '+
           'match none of the subjects on the page. Kept because the gap between '+
           'what was collected and what has been categorised is real, and '+
           'because a subject nobody has a pattern for yet shows up here first.'+
           '</p></div><button class="sclose" data-close aria-label="Close">'+
           '×</button></div>');
    h.push('<div class="sbody">');
    h.push(evidenceRows(list.map(function(u){
      return {title:u.title, url:u.url, publisher:u.publisher, ago:u.ago,
              when:u.when, market:u.market_label, kind:u.kind,
              search_volume:u.search_volume};
    })));
    h.push('</div>');
    return h.join('');
  }

  // ------------------------------------------------------------ popup plumbing
  var lastFocus = null;
  var scrollY = 0;
  var currentKey = null;

  function lockPage(){
    // Fix the body at its current offset instead of hiding overflow, so closing
    // the popup returns to the same place in the grid rather than the top.
    scrollY = window.scrollY || window.pageYOffset || 0;
    document.body.style.position = 'fixed';
    document.body.style.top = (-scrollY) + 'px';
    document.body.style.width = '100%';
  }
  function unlockPage(){
    document.body.style.position = '';
    document.body.style.top = '';
    document.body.style.width = '';
    window.scrollTo(0, scrollY);
  }

  function setUrl(key){
    if(!window.history || !window.history.replaceState) return;
    var u = new URL(window.location.href);
    if(key) u.searchParams.set('trend', key);
    else u.searchParams.delete('trend');
    window.history.replaceState({trend:key||null}, '', u.toString());
  }

  function show(inner, key, pushUrl){
    var first = !mask.classList.contains('open');
    if(first){
      lastFocus = document.activeElement;
      lockPage();
      mask.classList.add('open');
      // one frame, so the transition has a state to animate from
      requestAnimationFrame(function(){ mask.classList.add('shown'); });
    }
    sheet.innerHTML = inner;
    sheet.scrollTop = 0;
    mask.scrollTop = 0;
    currentKey = key || null;
    if(pushUrl !== false) setUrl(currentKey);
    var b = sheet.querySelector('[data-close]');
    if(b) b.focus();
  }

  function openKey(key, pushUrl){
    if(key === 'uncategorised'){ show(uncatHTML(), key, pushUrl); return true; }
    var hit = BY_KEY[key];
    if(!hit) return false;
    show(topicHTML(hit.t), key, pushUrl);
    return true;
  }

  function close(){
    if(!mask.classList.contains('open')) return;
    mask.classList.remove('shown');
    var done = function(){
      mask.classList.remove('open');
      sheet.innerHTML = '';
      unlockPage();
      if(lastFocus && lastFocus.focus) lastFocus.focus();
      lastFocus = null;
    };
    // Wait for the fade, but never hang if transitions are off.
    var fired = false;
    mask.addEventListener('transitionend', function h(){
      if(fired) return; fired = true;
      mask.removeEventListener('transitionend', h); done();
    });
    setTimeout(function(){ if(!fired){ fired = true; done(); } }, 220);
    currentKey = null;
    setUrl(null);
  }

  grid.addEventListener('click', function(ev){
    var card = ev.target.closest ? ev.target.closest('.tcard') : null;
    if(!card) return;
    openKey(card.getAttribute('data-key'));
  });

  // A report row opens the same popup as its card — one detail view, two ways in.
  document.addEventListener('click', function(ev){
    var row = ev.target.closest ? ev.target.closest('[data-open]') : null;
    if(!row) return;
    openKey(row.getAttribute('data-open'));
  });

  sheet.addEventListener('click', function(ev){
    var rel = ev.target.closest ? ev.target.closest('[data-rel]') : null;
    if(rel){ openKey(rel.getAttribute('data-rel')); return; }
    if(ev.target.closest && ev.target.closest('[data-close]')) close();
  });

  mask.addEventListener('click', function(ev){
    if(ev.target === mask) close();
  });

  document.addEventListener('keydown', function(ev){
    if(!mask.classList.contains('open')) return;
    if(ev.key === 'Escape'){ close(); return; }
    if(ev.key !== 'Tab') return;
    // Keep Tab inside the sheet while it is open.
    var f = sheet.querySelectorAll('a[href],button:not([disabled]),[tabindex]:not([tabindex="-1"])');
    if(!f.length) return;
    var first = f[0], last = f[f.length - 1];
    if(ev.shiftKey && document.activeElement === first){
      ev.preventDefault(); last.focus();
    } else if(!ev.shiftKey && document.activeElement === last){
      ev.preventDefault(); first.focus();
    }
  });

  window.addEventListener('popstate', function(){
    var key = new URL(window.location.href).searchParams.get('trend');
    if(key) openKey(key, false); else close();
  });

  // ------------------------------------------------------------ filters
  var cards = Array.prototype.slice.call(grid.querySelectorAll('.tcard'));
  var shown = document.getElementById('f-shown');
  var empty = document.getElementById('gridempty');
  var pager = document.getElementById('pager');
  var more = document.getElementById('pagemore');
  var qbox = document.getElementById('f-q');
  var PAGE = DATA.page_size || 12;
  var limit = PAGE;
  var state = {market:null, stage:null, recent:null, cat:null, q:''};

  function matches(c){
    if(state.market){
      var ms = (c.getAttribute('data-markets')||'').split(',');
      if(ms.indexOf(state.market) < 0) return false;
    }
    if(state.stage && c.getAttribute('data-stage') !== state.stage) return false;
    if(state.cat && c.getAttribute('data-cat') !== state.cat) return false;
    if(state.recent){
      var allowed = state.recent === 'today'
        ? ['last_hour','today'] : ['last_hour','today','this_week'];
      if(allowed.indexOf(c.getAttribute('data-bucket')) < 0) return false;
    }
    if(state.q && (c.getAttribute('data-q')||'').indexOf(state.q) < 0) return false;
    return true;
  }

  function apply(){
    var kept = 0, drawn = 0;
    cards.forEach(function(c){
      var ok = matches(c);
      // Pagination hides beyond the limit, so a long grid stays cheap to paint
      // while the filters still report the true total.
      var visible = ok && drawn < limit;
      if(ok){ kept += c.getAttribute('data-nocount') ? 0 : 1; drawn++; }
      c.hidden = !visible;
    });
    if(shown) shown.textContent = kept;
    if(empty) empty.hidden = drawn !== 0;
    if(pager) pager.hidden = drawn <= limit;
    if(more) more.textContent = 'Show more (' + Math.max(0, drawn - limit) + ')';
  }

  function wire(id, key){
    var box = document.getElementById(id);
    if(!box) return;
    box.addEventListener('click', function(ev){
      var btn = ev.target.closest ? ev.target.closest('.chip') : null;
      if(!btn) return;
      var val = btn.getAttribute('data-' + key);
      state[key] = (!val || state[key] === val) ? null : val;
      Array.prototype.forEach.call(box.querySelectorAll('.chip'), function(c){
        var v = c.getAttribute('data-' + key);
        c.classList.toggle('on', state[key] ? v === state[key] : !v);
      });
      limit = PAGE;
      apply();
    });
  }
  wire('f-market','market'); wire('f-stage','stage');
  wire('f-recent','recent'); wire('f-cat','cat');

  if(qbox){
    var timer = null;
    qbox.addEventListener('input', function(){
      clearTimeout(timer);
      timer = setTimeout(function(){
        state.q = (qbox.value||'').trim().toLowerCase();
        limit = PAGE;
        apply();
      }, 120);
    });
  }
  if(more) more.addEventListener('click', function(){ limit += PAGE; apply(); });

  var reset = document.getElementById('f-reset');
  if(reset) reset.addEventListener('click', function(){
    state = {market:null, stage:null, recent:null, cat:null, q:''};
    if(qbox) qbox.value = '';
    ['f-market','f-stage','f-recent','f-cat'].forEach(function(id){
      var box = document.getElementById(id);
      if(!box) return;
      Array.prototype.forEach.call(box.querySelectorAll('.chip'), function(c){
        c.classList.toggle('on', !!c.getAttribute('data-all'));
      });
    });
    limit = PAGE;
    apply();
  });

  apply();

  // A shared link opens straight into its trend.
  var initial = new URL(window.location.href).searchParams.get('trend');
  if(initial) openKey(initial, false);
})();
"""


def _footer(b: dict) -> str:
    P = ['<footer><div class="wrap">']
    P.append('<p><b>How this stays current.</b> A scan fetches every registered '
             'feed, keeps only what touches beauty, attaches each item to the '
             'subjects it is evidence for, and recomputes every subject across '
             'everything collected so far. Signals are stored once and never '
             'duplicated, so the clocks are real and the history accumulates. New '
             'subjects appear as cards in the same grid with no page change.</p>')
    P.append('<p>What this does <b>not</b> measure: sales, market share, or '
             'anything behind a login. Press and search attention is what feeds '
             'expose, and it is what the stages describe. Capability suggestions '
             'inside a trend are this system\'s own playbook, marked as such, and '
             'never mixed into the evidence.</p>')
    P.append(f'<p>Rendered {_e(b.get("generated_when"))}. Last scan '
             f'{_e(b.get("scan_when"))}. Full data at '
             f'<code>/trends.json</code>.</p>')
    P.append('</div></footer>')
    return "\n".join(P)


def render(b: dict, decisions: list | None = None) -> str:
    """The trends page.

    `decisions` is the list from `intel_sections.decision_items`. It is optional
    because trends can be rendered on its own, but without it the page can only
    say what is moving — not which of it is already carrying a decision, which is
    the fact that makes a trend actionable rather than interesting.
    """
    from . import scan_layer, ui

    decisions = decisions or []
    P = ['<title>Beauty Trends — Clara</title>',
         '<meta name="viewport" content="width=device-width, initial-scale=1">',
         f'<style>{CSS}{ui.SHARED_CSS}{EXTRA_CSS}</style>',
         '<div class="tpage">']
    P.append(_head(b, decisions))
    # The reading before the grid, same as the comparator: what is climbing,
    # what is cooling, and which of it a person is already being asked to decide.
    P.append(scan_layer.trends_band(b, decisions))
    P.append(_report(b))
    P.append(_cards(b, decisions))
    P.append(_footer(b))
    P.append('</div>')
    P.append('<div class="mask" id="mask" role="dialog" aria-modal="true" '
             'aria-labelledby="sheet-title"><div class="sheet" id="sheet"></div>'
             '</div>')
    P.append(_payload(b, decisions))
    P.append(f'<script>{MODAL_JS}</script>')
    return "\n".join(P)
