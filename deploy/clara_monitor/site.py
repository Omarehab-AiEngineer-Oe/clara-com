"""Builds the site from the Agent's output.

This file holds no number or conclusion of its own — every value is read from the
store via `reporting.py`. Where the Agent recorded nothing, the page says so
rather than filling the gap.

Sections: Products (cards) · Competitors (cards) · Live competitor offers ·
Decisions to make · Actions needed · Refused pairings

Everything technical is left off the screen: extraction method, match scores,
evidence logs, decision source and discovery path. All of it is still recorded in
the store for traceability, but it is not what a commercial team needs to read.
"""

from __future__ import annotations

import base64
import html
import io as _io
import json
import urllib.parse
import urllib.request
from decimal import Decimal
from pathlib import Path

from . import cards, intel_sections, scan_layer, scope, ui
from .config import REPORT_DIR
from .models import AMBIGUOUS, BLOCKED, CONFIRMED, NO_MATCH, PROBABLE
from .money import to_decimal

INVALIDATED = "invalidated"

# Plain-language labels for the screen. The technical status stays in the store.
STATUS_AR = {
    CONFIRMED: "confirmed",
    PROBABLE: "probable",
    AMBIGUOUS: "needs a decision",
    NO_MATCH: "no counterpart",
    BLOCKED: "site unavailable",
    INVALIDATED: "no longer valid",
    "unassigned": "no competitor assigned",
}
STATUS_ORDER = [CONFIRMED, PROBABLE, AMBIGUOUS, NO_MATCH, BLOCKED, INVALIDATED]

TIER_AR = {
    "premium": "premium",
    "professional": "professional",
    "mid_market": "mid-market",
    "value": "value",
}
THREAT_AR = {"high": "high threat", "medium": "medium threat", "low": "low threat"}
SEGMENT_AR = {"device": "devices", "haircare": "haircare",
              "accessory": "accessories", "unknown": "unclassified"}

CSS = """
:root{
  --ink:#181318; --ink2:#574d55; --ink3:#8a7f87; --ink4:#a99ea6;
  --bg:#faf7f8; --card:#fff; --card2:#f4eff1; --card3:#ebe4e7;
  --line:#e5dde1; --line2:#d2c6cc;
  --clara:#b8446e; --clara-wash:#f9ecf1;
  --rival:#1f6fb2; --rival-wash:#e9f1f9;
  --ok:#2f6b4f;   --ok-wash:#e8f1ec;
  --amb:#8d5a12;  --amb-wash:#f8f0e3;
  --no:#6a6169;   --no-wash:#eeecee;
  --bad:#a8323f;  --bad-wash:#fbeaec;
  --display:"Hoefler Text","Iowan Old Style","Palatino Linotype",Palatino,Georgia,serif;
  --sans:"Segoe UI",-apple-system,BlinkMacSystemFont,"Helvetica Neue",Arial,sans-serif;
  --mono:"Cascadia Mono","SF Mono",ui-monospace,Consolas,monospace;
  --shadow:0 1px 2px rgba(24,19,24,.05),0 8px 22px -14px rgba(24,19,24,.14);
}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){
  --ink:#f2ecef; --ink2:#b2a7ad; --ink3:#867c83; --ink4:#6d646a;
  --bg:#121013; --card:#1b181b; --card2:#232025; --card3:#2c272d;
  --line:#332e34; --line2:#443d45;
  --clara:#d5628e; --clara-wash:#331b25;
  --rival:#4b95ee; --rival-wash:#152738;
  --ok:#6cb28c;  --ok-wash:#18291f;
  --amb:#d3a45f; --amb-wash:#2b2313;
  --no:#8e858c;  --no-wash:#242024;
  --bad:#e8808d; --bad-wash:#331a1e;
  --shadow:0 1px 2px rgba(0,0,0,.4),0 8px 22px -14px rgba(0,0,0,.7);
}}
:root[data-theme="dark"]{
  --ink:#f2ecef; --ink2:#b2a7ad; --ink3:#867c83; --ink4:#6d646a;
  --bg:#121013; --card:#1b181b; --card2:#232025; --card3:#2c272d;
  --line:#332e34; --line2:#443d45;
  --clara:#d5628e; --clara-wash:#331b25;
  --rival:#4b95ee; --rival-wash:#152738;
  --ok:#6cb28c;  --ok-wash:#18291f;
  --amb:#d3a45f; --amb-wash:#2b2313;
  --no:#8e858c;  --no-wash:#242024;
  --bad:#e8808d; --bad-wash:#331a1e;
  --shadow:0 1px 2px rgba(0,0,0,.4),0 8px 22px -14px rgba(0,0,0,.7);
}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font-family:var(--sans);
     font-size:15px;line-height:1.6;-webkit-font-smoothing:antialiased}
.wrap{max-width:1320px;margin:0 auto;padding:0 22px}
h1,h2,h3,h4{margin:0;font-family:var(--display);font-weight:600;
            letter-spacing:-.01em;text-wrap:balance}
h1{font-size:clamp(26px,3.6vw,38px);line-height:1.15}
h2{font-size:clamp(19px,2.2vw,25px)}
h3{font-size:16.5px}
p{margin:0}
a{color:var(--rival);text-underline-offset:3px}
a:focus-visible,button:focus-visible,select:focus-visible,input:focus-visible{
  outline:2px solid var(--clara);outline-offset:2px;border-radius:3px}
.num{font-family:var(--mono);font-variant-numeric:tabular-nums}
/* Forces LTR on things that are always LTR — a URL, an id, a
   version string. Deliberately NOT mirrored: that is its job. */
.ltr{direction:ltr;display:inline-block;text-align:left}
.eyebrow{font-size:11.5px;letter-spacing:.02em;color:var(--ink3)}
.np{color:var(--ink4);font-style:italic}

header.top{background:var(--card);border-bottom:1px solid var(--line);padding:34px 0 24px}
.hrow{display:flex;flex-wrap:wrap;gap:26px;justify-content:space-between;align-items:flex-end}
.lede{color:var(--ink2);max-width:80ch;margin-top:10px;font-size:15px}
.runmeta{font-size:12px;color:var(--ink3);display:flex;flex-direction:column;gap:4px;
         text-align:end}
.runmeta b{color:var(--ink)}

.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(152px,1fr));gap:1px;
       background:var(--line);border:1px solid var(--line);border-radius:4px;
       overflow:hidden;margin-top:24px}
.tile{background:var(--card);padding:14px 16px}
.tile .k{font-size:11.5px;color:var(--ink3)}
.tile .v{font-family:var(--mono);font-size:24px;margin-top:6px;letter-spacing:-.02em}
.tile .n{font-size:11.5px;color:var(--ink2);margin-top:3px;line-height:1.4}
.v.c{color:var(--clara)} .v.r{color:var(--rival)} .v.g{color:var(--ok)}
.v.a{color:var(--amb)} .v.b{color:var(--bad)}

nav.jump{position:sticky;top:0;z-index:30;background:var(--card);
         border-bottom:1px solid var(--line);padding:9px 0}
nav.jump .wrap{display:flex;gap:16px;flex-wrap:wrap;align-items:center}
nav.jump a{font-size:12.5px;color:var(--ink2);text-decoration:none;font-weight:600}
nav.jump a:hover{color:var(--clara)}

section{padding:40px 0}
section+section{border-top:1px solid var(--line)}
.shead{display:flex;gap:16px;align-items:baseline;justify-content:space-between;
       flex-wrap:wrap;margin-bottom:6px}

.pill{display:inline-block;font-size:11px;padding:2px 8px;border-radius:3px;
      white-space:nowrap;font-weight:600}
.s-confirmed_match{background:var(--ok-wash);color:var(--ok)}
.s-probable_match{background:var(--rival-wash);color:var(--rival)}
.s-ambiguous{background:var(--amb-wash);color:var(--amb)}
.s-no_match{background:var(--no-wash);color:var(--no)}
.s-blocked{background:var(--bad-wash);color:var(--bad)}
.s-invalidated{background:var(--amb-wash);color:var(--amb)}
.s-unassigned{background:var(--no-wash);color:var(--no)}
.t-premium{background:var(--clara-wash);color:var(--clara)}
.t-professional{background:var(--rival-wash);color:var(--rival)}
.t-mid_market{background:var(--card3);color:var(--ink2)}
.t-value{background:var(--ok-wash);color:var(--ok)}
.th-high{background:var(--bad-wash);color:var(--bad)}
.th-medium{background:var(--amb-wash);color:var(--amb)}
.th-low{background:var(--no-wash);color:var(--no)}

.toolbar{display:flex;gap:10px;flex-wrap:wrap;align-items:center;margin:18px 0 10px;
         font-size:12.5px}
.toolbar label{color:var(--ink3)}
.toolbar select,.toolbar input{font-family:inherit;font-size:12.5px;padding:6px 9px;
  background:var(--card);color:var(--ink);border:1px solid var(--line2);border-radius:4px}
.count{color:var(--ink3);margin-inline-start:auto}

.scroller{overflow-x:auto;border:1px solid var(--line);border-radius:4px;
          background:var(--card);box-shadow:var(--shadow)}
table{border-collapse:collapse;width:100%;font-size:13.5px}
thead th{font-size:11.5px;color:var(--ink3);font-weight:600;background:var(--card2);
         text-align:start;padding:10px 12px;border-bottom:1px solid var(--line2)}
td{padding:10px 12px;vertical-align:top;border-bottom:1px solid var(--line)}
tbody tr:last-child td{border-bottom:0}
td.n{font-family:var(--mono);font-variant-numeric:tabular-nums;white-space:nowrap}

.empty{background:var(--card);border:1px dashed var(--line2);border-radius:4px;
       padding:24px;text-align:center;color:var(--ink3);font-size:14px;margin-top:16px}
.note{background:var(--card2);border:1px solid var(--line);border-radius:4px;
      padding:15px 17px;font-size:13.5px;color:var(--ink2);margin-top:16px}
.note b{color:var(--ink)}
footer{border-top:1px solid var(--line);padding:26px 0 44px;font-size:12.5px;color:var(--ink3)}
footer p+p{margin-top:6px}

/* ---------- competitor cards ---------- */
.cc-fams{display:flex;flex-wrap:wrap;gap:4px;margin-top:9px}
.cc-fams span{font-size:10px;color:var(--ink3);background:var(--card2);
  border:1px solid var(--line2);border-radius:3px;padding:1px 5px}
.cc-fams span.on{color:var(--clara);border-color:var(--clara);
  background:var(--clara-wash);font-weight:650}
.cgrid{display:grid;grid-template-columns:repeat(auto-fill,minmax(330px,1fr));
       gap:14px;margin-top:18px}
.ccard{background:var(--card);border:1px solid var(--line);border-radius:6px;
       box-shadow:var(--shadow);padding:16px;display:flex;flex-direction:column;
       gap:11px;cursor:pointer;text-align:start;font:inherit;color:inherit;
       transition:border-color .12s}
.ccard:hover{border-color:var(--clara)}
.ccard:hover .cc-name{color:var(--clara)}
.cc-top{display:flex;gap:10px;align-items:flex-start;justify-content:space-between}
.cc-name{font-weight:700;font-size:17px;line-height:1.2}
.cc-origin{font-size:11.5px;color:var(--ink3);margin-top:3px}
.cc-pos{font-size:13px;color:var(--ink2);line-height:1.5}
.cc-pills{display:flex;gap:5px;flex-wrap:wrap}
.cc-stats{display:grid;grid-template-columns:repeat(3,1fr);gap:1px;
          background:var(--line);border:1px solid var(--line);border-radius:4px;
          overflow:hidden}
.cc-stats div{background:var(--card2);padding:8px 9px;text-align:center}
.cc-stats .sv{font-family:var(--mono);font-size:16px}
.cc-stats .sk{font-size:10.5px;color:var(--ink3);margin-top:2px}
.cc-band{font-size:12.5px;color:var(--ink2)}
.cc-band b{font-family:var(--mono)}
.cc-known{display:flex;gap:5px;flex-wrap:wrap}
.cc-known span{font-size:11px;background:var(--card2);border:1px solid var(--line);
               border-radius:3px;padding:2px 7px;color:var(--ink2)}
.cc-open{margin-top:auto;font-size:11.5px;color:var(--ink4)}

/* ---------- offers ---------- */
.ogrid{display:grid;grid-template-columns:repeat(auto-fill,minmax(310px,1fr));
       gap:13px;margin-top:18px}
.ocard{background:var(--card);border:1px solid var(--line);
       border-inline-start:3px solid var(--amb);border-radius:5px;padding:14px;
       display:flex;flex-direction:column;gap:8px}
.ocard .ob{font-weight:700;font-size:15px}
.ocard .op{font-size:12.5px;color:var(--ink2)}
.ocard .oprice{font-family:var(--mono);font-size:17px;color:var(--rival)}
.ocard .odisc{font-family:var(--mono);font-size:13px;color:var(--bad)}
.ocard .otext{font-size:12.5px;color:var(--ink);background:var(--amb-wash);
              border-radius:3px;padding:7px 9px;line-height:1.5}
.ocard .ovs{font-size:12px;color:var(--ink3)}

/* ---------- actions ---------- */
.agroup{margin-top:24px}
.agroup h3{display:flex;gap:9px;align-items:center;margin-bottom:10px}
.howto{background:var(--card2);border:1px solid var(--line);border-radius:5px;
       padding:13px 16px;margin-bottom:12px;font-size:13px;color:var(--ink2)}
.howto b{color:var(--ink);display:block;margin-bottom:6px;font-size:12.5px}
.howto ol{margin:0;padding-inline-start:20px;display:flex;flex-direction:column;
          gap:3px}
.acard{background:var(--card);border:1px solid var(--line);
       border-inline-start:3px solid var(--bad);border-radius:5px;padding:13px 16px;
       margin-bottom:9px;display:flex;flex-direction:column;gap:9px}
.acard.k-ambiguous{border-inline-start-color:var(--amb)}
.acard.k-unassigned{border-inline-start-color:var(--no)}
.acard .ahead{display:flex;gap:12px;flex-wrap:wrap;align-items:baseline}
.acard .ap{font-weight:700;font-size:14.5px}
.acard .aprice{font-family:var(--mono);font-size:13px;color:var(--clara)}
.acard .ac{font-size:12.5px;color:var(--ink3)}
.acard .ad{font-size:13.5px;color:var(--ink)}
.alinks{display:flex;gap:7px;flex-wrap:wrap;align-items:center}
.alinks .alab{font-size:11.5px;color:var(--ink3);margin-inline-end:2px}
.alinks a{font-size:12.5px;padding:4px 10px;border:1px solid var(--line2);
          border-radius:4px;text-decoration:none;color:var(--rival);
          max-width:340px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.alinks a:hover{border-color:var(--rival);background:var(--rival-wash)}
.alinks.alt a{color:var(--ink2)}
.alinks.alt a:hover{color:var(--clara);border-color:var(--clara);
                    background:var(--clara-wash)}
.ablocks{font-size:12px;color:var(--ink3);font-style:italic}

/* ---------- modal (shared) ---------- */
.mask{position:fixed;inset:0;background:rgba(20,15,20,.62);z-index:100;
      display:none;padding:24px;overflow-y:auto}
.mask.open{display:block}
.sheet{max-width:1020px;margin:0 auto;background:var(--bg);
       border:1px solid var(--line2);border-radius:7px;
       box-shadow:0 24px 70px -20px rgba(0,0,0,.55);overflow:hidden}
.sheet-top{display:flex;gap:16px;align-items:flex-start;padding:20px 22px;
           background:var(--card);border-bottom:1px solid var(--line)}
.sheet-top img{width:92px;height:92px;flex:none;object-fit:contain;background:#fff;
               border:1px solid var(--line);border-radius:4px;padding:4px}
.sheet-top .st-meta{flex:1;min-width:0}
.sheet-top h3{font-size:21px;line-height:1.25}
.sheet-close{flex:none;background:var(--card2);border:1px solid var(--line2);
             border-radius:4px;width:32px;height:32px;cursor:pointer;
             color:var(--ink2);font-size:17px;line-height:1}
.sheet-close:hover{color:var(--clara);border-color:var(--clara)}
.sheet-body{padding:20px 22px 24px;display:flex;flex-direction:column;gap:18px}
.kvgrid{display:grid;grid-template-columns:repeat(auto-fit,minmax(165px,1fr));
        gap:1px;background:var(--line);border:1px solid var(--line);border-radius:4px;
        overflow:hidden}
.kvgrid div{background:var(--card);padding:10px 12px}
.kvgrid .k{font-size:11px;color:var(--ink3)}
.kvgrid .v{font-size:13.5px;margin-top:4px;overflow-wrap:anywhere}
.mblock{background:var(--card);border:1px solid var(--line);
        border-inline-start:3px solid var(--rival);border-radius:5px;padding:15px 17px}
.mblock.blocked{border-inline-start-color:var(--bad)}
.mblock.ambiguous{border-inline-start-color:var(--amb)}
.mblock.confirmed_match{border-inline-start-color:var(--ok)}
.mblock.no_match{border-inline-start-color:var(--no)}
.mblock h4{font-size:15.5px;display:flex;gap:9px;align-items:center;flex-wrap:wrap}
.mblock h4 a{font-weight:400;font-size:13px}
.mb-sub{font-size:12.5px;color:var(--ink3);margin-top:5px}
.mtag{font-size:11.5px;color:var(--ink3);margin-top:13px;display:block;font-weight:600}
.mlist{margin:7px 0 0;padding-inline-start:18px;font-size:13px;color:var(--ink2)}
.mlist li{margin:3px 0}
.vtable{width:100%;border-collapse:collapse;font-size:12.5px;margin-top:6px}
.vtable th,.vtable td{padding:6px 9px;text-align:start;border-bottom:1px solid var(--line)}
.vtable th{font-size:11px;color:var(--ink3);font-weight:600}
@media (max-width:620px){
  .mask{padding:0}
  .sheet{border-radius:0;min-height:100%}
  .sheet-top{flex-wrap:wrap}
  .cc-stats{grid-template-columns:repeat(3,1fr)}
}
@media (prefers-reduced-motion:reduce){*{transition:none!important;animation:none!important}}
"""


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------


# A competitor arrived at from a decision. Marked rather than merely scrolled to,
# because a smooth scroll that ends on an unmarked card in a grid of 46 leaves the
# reader to work out which one was meant.
FOCUS_CSS = """
.ccard.focused{border-color:var(--clara);border-width:2px;
               box-shadow:0 0 0 4px var(--clara-wash)}
.ccard.focused .cc-name{color:var(--clara)}
"""

def e(v) -> str:
    if v is None or v == "":
        return '<span class="np">&mdash;</span>'
    if v == "not_published":
        return '<span class="np">not published</span>'
    return html.escape(str(v))


def money(amount, currency=None) -> str:
    d = to_decimal(amount)
    if d is None:
        return '<span class="np">unresolved</span>'
    q = d.quantize(Decimal("0.01"))
    s = f"{q:,.2f}"
    if s.endswith(".00"):
        s = s[:-3]
    return f'<span class="num">{html.escape((currency + " " + s) if currency else s)}</span>'


def pill(status: str) -> str:
    s = html.escape(str(status))
    return f'<span class="pill s-{s}">{html.escape(STATUS_AR.get(status, status))}</span>'


# --------------------------------------------------------------------------
# sections
# --------------------------------------------------------------------------

def _header(b: dict) -> str:
    pr, cc, of, ac = b["price"], b["competitors"], b["offers"], b["actions"]
    cov = b["coverage"]
    run = b.get("run") or {}
    cfg = run.get("config") or {}
    st = cov["by_status"]
    cur = cfg.get("currency", "SAR")

    P = ['<header class="top"><div class="wrap"><div class="hrow"><div>']
    P.append('<p class="eyebrow">Clara price and competitor report</p>')
    P.append('<h1 style="margin-top:10px">Clara vs. the competition</h1>')
    P.append('<p class="lede">Every product in Clara\'s catalogue with its price, and '
             'the competing product and its price beside it. Each competitor carries '
             'its commercial profile, its current offers and its price direction. '
             'What was not actually observed is not filled in here.</p>')
    P.append('</div><div class="runmeta">')
    for k, v in [("Run", run.get("run_id") or pr["run_id"]),
                 ("Updated", pr["generated_at"]),
                 ("Market", cfg.get("market", "SA")),
                 ("Currency", cur)]:
        P.append(f'<div>{html.escape(str(k))} &nbsp;<b>{e(v)}</b></div>')
    P.append('</div></div>')

    P.append('<div class="tiles">')
    for k, v, n, cls in [
        ("Clara products", pr["catalog_size"], "the whole catalogue", ""),
        ("Clara price band", f'{pr["clara_price_min"]}–{pr["clara_price_max"]}',
         f'median {pr["clara_price_median"]} {cur}', "c"),
        ("Competitors tracked", cc["total"],
         f'{cc["with_matches"]} with an observed counterpart', "r"),
        ("Confirmed matches", st.get(CONFIRMED, 0), "counterpart proven", "g"),
        ("Probable matches", st.get(PROBABLE, 0), "counterpart likely", "r"),
        ("Live offers", of["total"],
         f'{len(of["brands_running_offers"])} brands running one now', "a"),
        ("Products with a rival", pr["products_with_a_match"], "of the catalogue", ""),
        ("Actions needed", ac["total"], "tasks waiting on a person", "b"),
    ]:
        P.append(f'<div class="tile"><div class="k">{html.escape(k)}</div>'
                 f'<div class="v {cls}">{e(v)}</div>'
                 f'<div class="n">{html.escape(str(n))}</div></div>')
    P.append('</div></div></header>')

    P.append('<nav class="jump"><div class="wrap">')
    for a, l in [("takeaway", "What this scan says"),
                 ("prices", "Products"), ("competitors", "Competitors"),
                 ("live", "Live competitor offers"),
                 ("actions", "Actions needed")]:
        P.append(f'<a href="#{a}">{l}</a>')
    P.append('</div></nav>')
    return "\n".join(P)


def _competitor_section(b: dict) -> str:
    cc = b["competitors"]
    P = ['<section id="competitors"><div class="wrap">']
    P.append('<div class="shead"><h2>Competitors</h2>'
             f'<p class="eyebrow">{cc["total"]} brands &middot; open a card for the '
             'full profile</p></div>')
    P.append('<p class="lede">Each competitor carries its commercial profile: who it '
             'is, who it sells to, its typical Saudi price band and how it usually '
             'discounts — alongside the prices, offers and counterpart products the '
             'Agent actually observed.</p>')

    # Grouped and filtered by product family, not by the three-way segment.
    # `segments` cannot separate families 2 and 3 — a bond-repair house and a
    # hairspray house are both "haircare" there — so the family comes from the
    # assignment tables, which name the exact category.
    from . import competitors as _comp

    for c in cc["competitors"]:
        c["families"] = _comp.families_for(c["key"])
        c["primary_family"] = _comp.primary_family(c["key"])
    groups = scope.group_by_family(cc["competitors"],
                                   key=lambda c: c["primary_family"])
    index_of = {c["key"]: i for i, c in enumerate(cc["competitors"])}

    P.append(ui.frame_strip(
        counts={f["key"]: len(items) for f, items in groups}))

    P.append('<div class="toolbar">')
    P.append('<label for="c-seg">Family</label><select id="c-seg">'
             '<option value="">all four families</option>')
    for fam, items in groups:
        P.append(f'<option value="{html.escape(fam["key"])}">'
                 f'{html.escape(fam["en"])} ({len(items)})</option>')
    P.append('</select>')
    P.append('<label for="c-tier">Price tier</label><select id="c-tier">'
             '<option value="">all</option>')
    for t, lab in TIER_AR.items():
        P.append(f'<option value="{t}">{lab}</option>')
    P.append('</select>')
    P.append('<label for="c-threat">Threat level</label><select id="c-threat">'
             '<option value="">all</option>')
    for t, lab in THREAT_AR.items():
        P.append(f'<option value="{t}">{lab}</option>')
    P.append('</select>')
    P.append('<label for="c-q">Find</label><input id="c-q" type="search" '
             'placeholder="brand name" size="18">')
    P.append('<span class="count" id="c-count"></span></div>')

    P.append('<div id="cgrid">')
    for fam, items in groups:
        P.append(f'<section class="fam" data-fam="{html.escape(fam["key"])}">')
        P.append('<div class="fam-h">'
                 f'<h2>{html.escape(fam["en"])}</h2>'
                 f'<span class="n">{len(items)}</span>'
                 + (f'<span class="sc">{html.escape(fam["en_scope"])}</span>'
                    if fam.get("en_scope") else "")
                 + '</div>')
        if fam["key"] == "unclassified":
            P.append('<div class="fam-note">Registered as a competitor and '
                     'assigned to no family. That is a real position, not a '
                     'gap: a brand can compete for the same spend without '
                     'selling anything in the four families, and it must not '
                     'enter a price comparison.</div>')
        P.append('<div class="cgrid">')
        for c in items:
            i = index_of[c["key"]]
            pr = c["profile"] or {}
            tier = pr.get("price_tier", "mid_market")
            threat = pr.get("threat_to_clara", "low")
            search = " ".join([c["brand"].lower(), c["key"],
                               (pr.get("positioning") or "")[:80].lower()])
            P.append(f'<button class="ccard" type="button" data-idx="{i}" '
                 f'data-key="{html.escape(c["key"])}" '
                 f'data-fam="{html.escape(c["primary_family"])}" '
                 f'data-seg="{html.escape(" ".join(c["segments"]))}" '
                     f'data-tier="{html.escape(tier)}" '
                     f'data-threat="{html.escape(threat)}" '
                     f'data-search="{html.escape(search)}">')
            P.append('<div class="cc-top"><div>')
            P.append(f'<div class="cc-name">{e(c["brand"])}</div>')
            # The entity goes outside e(), not through it — escaping it produced
            # the literal text "&mdash;" on every competitor without a profile.
            P.append('<div class="cc-origin">'
                     + (e(pr["origin"]) if pr.get("origin") else "&mdash;")
                     + (f' &middot; {e(pr.get("founded"))}' if pr.get("founded") else "")
                     + '</div>')
            P.append('</div><div class="cc-pills">')
            P.append(f'<span class="pill t-{html.escape(tier)}">'
                     f'{html.escape(TIER_AR.get(tier, tier))}</span>')
            P.append(f'<span class="pill th-{html.escape(threat)}">'
                     f'{html.escape(THREAT_AR.get(threat, threat))}</span>')
            P.append('</div></div>')

            if pr.get("positioning"):
                P.append(f'<div class="cc-pos">{e(pr["positioning"])}</div>')

            P.append('<div class="cc-stats">')
            P.append(f'<div><div class="sv">{c["matched_count"]}</div>'
                     f'<div class="sk">counterparts</div></div>')
            P.append(f'<div><div class="sv">{c["offer_count"]}</div>'
                     f'<div class="sk">live offers</div></div>')
            P.append(f'<div><div class="sv">{c["pairs"]}</div>'
                     f'<div class="sk">comparisons</div></div>')
            P.append('</div>')

            if pr.get("sar_band"):
                P.append('<div class="cc-band">Typical price band: '
                         f'<b>SAR {e(pr["sar_band"])}</b></div>')
            if c.get("observed_price_min"):
                cur = (c.get("observed_currencies") or ["SAR"])[0]
                P.append('<div class="cc-band">Actually observed: '
                         f'<b>{e(c["observed_price_min"])}–{e(c["observed_price_max"])}</b> '
                         f'{e(cur)}</div>')

            # Which families this rival actually competes in. The section it
            # sits in is one of them; a brand competing in three is filed under
            # one and says so here, because the filing is a page decision and
            # not a claim that the other two are absent.
            if len(c["families"]) > 1:
                P.append('<div class="cc-fams">'
                         + "".join(
                             f'<span{" class=\"on\"" if f == c["primary_family"] else ""}>'
                             f'{html.escape(scope.family_label(f, lang="en"))}'
                             f'</span>' for f in c["families"])
                         + '</div>')

            if pr.get("known_for"):
                P.append('<div class="cc-known">'
                         + "".join(f'<span>{e(k)}</span>' for k in pr["known_for"][:3])
                         + '</div>')
            P.append('<span class="cc-open">Open for the full profile</span>')
            P.append('</button>')
        P.append('</div>')
        P.append('</section>')
    P.append('</div>')

    payload = json.dumps({"competitors": cc["competitors"]},
                         ensure_ascii=False).replace("</", "<\\/")
    P.append(f'<script>window.__COMP__={payload};</script>')
    P.append('</div></section>')
    return "\n".join(P)


def _actions_section(b: dict) -> str:
    ac = b["actions"]
    P = ['<section id="actions"><div class="wrap">']
    P.append('<div class="shead"><h2>Actions needed</h2>'
             f'<p class="eyebrow">{ac["total"]} tasks &middot; '
             f'{ac["with_links"]} come with a link to open</p></div>')
    P.append(f'<p class="lede">{html.escape(ac["note"])}</p>')

    if not ac["actions"]:
        P.append('<div class="empty">Nothing outstanding. Every comparison '
                 'completed.</div>')
        P.append('</div></section>')
        return "\n".join(P)

    grouped: dict[str, list] = {}
    for a in ac["actions"]:
        grouped.setdefault(a["kind_label"], []).append(a)

    for label, rows in grouped.items():
        kind = rows[0]["kind"]
        P.append('<div class="agroup">')
        P.append(f'<h3>{html.escape(label)} '
                 f'<span class="pill s-{html.escape(kind if kind in STATUS_AR else BLOCKED)}">'
                 f'{len(rows)}</span></h3>')

        # The steps are the same for every task of a kind, so they are stated once
        # for the group rather than repeated on all 26 cards.
        if rows[0]["how_to"]:
            P.append('<div class="howto"><b>How to handle these</b><ol>')
            for step in rows[0]["how_to"]:
                P.append(f'<li>{e(step)}</li>')
            P.append('</ol></div>')

        for a in rows[:60]:
            P.append(f'<div class="acard k-{html.escape(a["kind"])}">')
            P.append('<div class="ahead">')
            name = e(a["product"])
            if a.get("product_url"):
                name = (f'<a href="{html.escape(a["product_url"])}" '
                        f'rel="nofollow noopener">{name}</a>')
            P.append(f'<span class="ap">{name}</span>')
            if a.get("product_price"):
                P.append('<span class="aprice">'
                         + money(a["product_price"], a.get("currency")) + '</span>')
            P.append(f'<span class="ac">vs {e(a["competitor"])}</span>')
            P.append('</div>')

            P.append(f'<div class="ad">{e(a["do"])}</div>')

            if a.get("candidates"):
                P.append('<div class="alinks"><span class="alab">'
                         'Candidates to choose between</span>')
                for cnd in a["candidates"]:
                    P.append(f'<a href="{html.escape(cnd["url"])}" '
                             f'rel="nofollow noopener">{e(cnd["name"])}</a>')
                P.append('</div>')

            if a.get("links"):
                P.append('<div class="alinks"><span class="alab">'
                         'Pages the Agent could not read</span>')
                for ln in a["links"]:
                    # Host alone is not enough: two different product pages on the
                    # same site would render as the same label. The last path
                    # segment tells them apart.
                    parts = [x for x in ln["url"].split("?")[0].split("/") if x]
                    host = parts[1] if len(parts) > 1 else ln["url"]
                    # Take the last segment that actually names something. Some
                    # shops end a product URL with "/p" or an id, which tells the
                    # reader nothing.
                    # Prefer the longest descriptive segment. The tail of a
                    # product URL is often "/p" or a bare id, which names nothing.
                    segs = [urllib.parse.unquote(x) for x in parts
                            if x not in (host, "https:", "http:")]
                    worded = [x for x in segs if "-" in x or "_" in x]
                    slug = max(worded or segs or [""], key=len)
                    slug = slug.replace("-", " ").replace("_", " ")[:46]
                    label_txt = f'{host} — {slug}' if slug else host
                    P.append(f'<a href="{html.escape(ln["url"])}" '
                             f'rel="nofollow noopener" '
                             f'title="{html.escape(ln["url"])}">{e(label_txt)}</a>')
                P.append('</div>')

            if a.get("elsewhere"):
                P.append('<div class="alinks alt"><span class="alab">'
                         'Try instead</span>')
                for el in a["elsewhere"]:
                    P.append(f'<a href="{html.escape(el["url"])}" '
                             f'rel="nofollow noopener">{e(el["label"])}</a>')
                P.append('</div>')

            if a.get("blocks"):
                P.append(f'<div class="ablocks">{e(a["blocks"])}</div>')
            P.append('</div>')

        if len(rows) > 60:
            P.append(f'<div class="note">And {len(rows) - 60} more of the same '
                     f'kind.</div>')
        P.append('</div>')
    P.append('</div></section>')
    return "\n".join(P)


def render(bundle: dict) -> str:
    P = ['<title>Clara vs. the Competition</title>',
         '<meta name="viewport" content="width=device-width, initial-scale=1">',
         "<style>" + CSS + cards.CARD_CSS
         + intel_sections.INTEL_CSS + ui.SHARED_CSS + FOCUS_CSS + "</style>"]
    P.append(_header(bundle))
    # The reading of the tables comes before the tables. A reader who wants the
    # raw pairings scrolls; a reader who wants the point does not have to.
    P.append(scan_layer.comparator_band(bundle))
    P.append(cards.render_price_cards(bundle))
    P.append(_competitor_section(bundle))
    # One offers section, not two. The lifecycle version replaces the old
    # list-everything one and keeps its name and its slot.
    P.append(intel_sections.live_offers(bundle))
    # Decisions have their own page now. This report is the input to them.
    P.append(_actions_section(bundle))
    P.append(intel_sections.after_offers(bundle))
    P.append('<div class="mask" id="mask" role="dialog" aria-modal="true" '
             'aria-label="Details"><div class="sheet" id="sheet"></div></div>')
    P.append(f"<script>{cards.CARD_JS}</script>")
    P.append(f"<script>{cards.COMP_JS}</script>")
    return "\n".join(P)


# --------------------------------------------------------------------------
# image inlining
# --------------------------------------------------------------------------

IMAGE_HOSTS = {
    "cdn.salla.sa", "salla.sa", "dyson-h.assetsadobe2.com", "laifen.sa",
    "cdn.shopify.com", "imgs.dev-almanea.com", "almanea.sa",
    "static.sweetcare.com", "sharkninja.com", "www.sharkninja.com",
    "ghdhair.com", "www.ghdhair.com", "olaplex.com", "www.olaplex.com",
}


def embed_images(bundle: dict, max_px: int = 160) -> dict:
    try:
        from PIL import Image
    except ImportError:
        return bundle
    cache: dict[str, str | None] = {}

    def grab(url: str) -> str | None:
        if url in cache:
            return cache[url]
        host = url.split("/")[2].lower() if "//" in url else ""
        if host not in IMAGE_HOSTS:
            cache[url] = None
            return None
        try:
            req = urllib.request.Request(
                url, headers={"User-Agent": "ClaraCatalogMonitor/1.0 (thumbnail)"})
            raw = urllib.request.urlopen(req, timeout=35).read()
            im = Image.open(_io.BytesIO(raw))
            if im.mode in ("RGBA", "LA", "P"):
                im = im.convert("RGBA")
                bg = Image.new("RGB", im.size, (255, 255, 255))
                bg.paste(im, mask=im.split()[-1])
                im = bg
            else:
                im = im.convert("RGB")
            im.thumbnail((max_px, max_px), Image.LANCZOS)
            buf = _io.BytesIO()
            im.save(buf, "JPEG", quality=70, optimize=True)
            cache[url] = "data:image/jpeg;base64," + base64.b64encode(
                buf.getvalue()).decode()
        except Exception:
            cache[url] = None
        return cache[url]

    for p in bundle["price"]["products"]:
        if p.get("image_url"):
            p["image_url"] = grab(p["image_url"])
    return bundle


def write_site(bundle: dict, out_path: Path | None = None,
               inline_images: bool = False) -> Path:
    if inline_images:
        bundle = embed_images(bundle)
    run_id = bundle["price"]["run_id"]
    out_path = out_path or (REPORT_DIR / f"site_{run_id}.html")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(render(bundle), encoding="utf-8")
    return out_path
