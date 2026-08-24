"""Card grid + detail modal for the price report.

Products are cards, not table rows. A card carries what you scan for — image,
Clara price, cheapest rival, status — and opening it shows every field the Agent
recorded for that product and each of its matches.

The detail payload is embedded once as JSON and rendered client-side, so the page
stays small and the modal has the complete record rather than a summary of it.
Nothing here invents a value: absent fields render as not_published / unresolved,
exactly as in the store.
"""

from __future__ import annotations

import html
import json
from decimal import Decimal

from . import scope, ui
from .models import AMBIGUOUS, BLOCKED, CONFIRMED, NO_MATCH, PROBABLE
from .money import to_decimal

INVALIDATED = "invalidated"
STATUS_ORDER = [CONFIRMED, PROBABLE, AMBIGUOUS, NO_MATCH, BLOCKED, INVALIDATED]

# Display labels only. The technical values stay as they are in the store.
SEG_AR = {"device": "devices", "haircare": "haircare",
          "accessory": "accessories", "unknown": "unclassified"}
FMT_AR = {"multi_styler": "multi-styler", "dryer": "dryer",
          "air_brush": "air brush", "hot_brush": "hot brush",
          "auto_curler": "auto curler", "straightener": "straightener",
          "straightener_brush": "straightener + brush",
          "hair_styling_device": "styling device", "unknown": "unclassified"}
STATUS_AR = {CONFIRMED: "confirmed", PROBABLE: "probable",
             AMBIGUOUS: "needs a decision", NO_MATCH: "no counterpart",
             BLOCKED: "site unavailable", INVALIDATED: "no longer valid",
             "unassigned": "no competitor assigned"}

CARD_CSS = """
/* ---------- family sections ----------
   The page is read family by family, so each one gets a heading with its own
   count. `.fam-empty` is set by the filter rather than by the server: a heading
   left standing over nothing reads as a section that failed to load. */
.fam{margin:26px 0 0}
.fam-h{display:flex;align-items:baseline;gap:10px;flex-wrap:wrap;
  padding:0 0 9px;border-bottom:1px solid var(--line);margin-bottom:14px}
.fam-h h2{margin:0;font-size:17px;font-weight:680;letter-spacing:-.01em}
.fam-h .en{font-size:12.5px;color:var(--ink3)}
.fam-h .n{font-size:11.5px;font-weight:650;color:var(--ink3);
  background:var(--card2);border:1px solid var(--line2);border-radius:999px;
  padding:1px 8px;font-variant-numeric:tabular-nums}
.fam-h .sc{flex:1 1 100%;font-size:12px;color:var(--ink4);line-height:1.5}
.fam-empty{display:none}
.fam-note{font-size:12.5px;color:var(--ink3);line-height:1.6;
  background:var(--card2);border:1px solid var(--line2);border-radius:7px;
  padding:11px 13px;margin:14px 0 0}

/* ---------- card grid ---------- */
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(268px,1fr));
      gap:14px;margin-top:18px}
/* A link, not a button: pressing a product opens its page, which holds
   everything the popup used to and the market and content sections besides.
   `text-decoration:none` and the inherited colour are what keep an <a> looking
   like the card it is rather than a blue underlined block. */
.pcard{background:var(--card);border:1px solid var(--line);border-radius:5px;
       box-shadow:var(--shadow);padding:14px;display:flex;flex-direction:column;
       gap:10px;cursor:pointer;text-align:start;font:inherit;color:inherit;
       text-decoration:none;
       transition:border-color .12s, transform .12s}
.pcard:hover{border-color:var(--clara)}
.pcard:hover .pc-name{color:var(--clara)}
.pcard:focus-visible{outline:2px solid var(--clara);outline-offset:2px}
.pc-top{display:flex;gap:12px;align-items:flex-start}
.pc-img{width:62px;height:62px;flex:none;object-fit:contain;background:#fff;
        border:1px solid var(--line);border-radius:3px;padding:3px}
.pc-imgph{width:62px;height:62px;flex:none;border:1px dashed var(--line2);
          border-radius:3px;display:flex;align-items:center;justify-content:center;
          font-family:var(--mono);font-size:8.5px;color:var(--ink4);text-align:center;
          padding:4px}
.pc-head{min-width:0;flex:1}
.pc-name{font-weight:600;font-size:14.5px;line-height:1.25;overflow-wrap:anywhere}
.pc-meta{font-family:var(--mono);font-size:10px;color:var(--ink3);margin-top:4px;
         letter-spacing:.04em}
.pc-price{display:flex;align-items:baseline;gap:8px;flex-wrap:wrap}
.pc-price b{font-family:var(--mono);font-variant-numeric:tabular-nums;font-size:20px;
            letter-spacing:-.02em;color:var(--clara)}
.pc-price span{font-family:var(--mono);font-size:10.5px;color:var(--ink3)}
.pc-pills{display:flex;gap:4px;flex-wrap:wrap}
.pc-rivals{border-top:1px solid var(--line);padding-top:9px;display:flex;
           flex-direction:column;gap:6px}
.pc-rival{display:flex;justify-content:space-between;gap:8px;align-items:baseline;
          font-size:12px}
.pc-rival .rb{color:var(--ink2);overflow:hidden;text-overflow:ellipsis;
              white-space:nowrap}
.pc-rival .rp{font-family:var(--mono);font-variant-numeric:tabular-nums;
              white-space:nowrap;color:var(--rival)}
.pc-bars{display:flex;flex-direction:column;gap:3px}
.pc-bar{height:6px;border-radius:1px;position:relative}
.pc-bar i{position:absolute;inset:0 auto 0 0;border-radius:1px;display:block}
.pc-bar.c{background:var(--clara-wash)} .pc-bar.c i{background:var(--clara)}
.pc-bar.r{background:var(--rival-wash)} .pc-bar.r i{background:var(--rival)}
.pc-mult{font-family:var(--mono);font-size:10px;color:var(--ink3)}
.pc-none{font-size:12px;color:var(--ink4);font-style:italic;border-top:1px solid var(--line);
         padding-top:9px}
.pc-open{margin-top:auto;font-family:var(--mono);font-size:9.5px;letter-spacing:.1em;
         text-transform:uppercase;color:var(--ink4)}

/* ---------- modal ---------- */
.mask{position:fixed;inset:0;background:rgba(20,15,20,.62);z-index:100;
      display:none;padding:24px;overflow-y:auto}
.mask.open{display:block}
.sheet{max-width:1000px;margin:0 auto;background:var(--bg);border:1px solid var(--line2);
       border-radius:6px;box-shadow:0 24px 70px -20px rgba(0,0,0,.55);overflow:hidden}
.sheet-top{display:flex;gap:16px;align-items:flex-start;padding:20px 22px;
           background:var(--card);border-bottom:1px solid var(--line)}
.sheet-top img{width:92px;height:92px;flex:none;object-fit:contain;background:#fff;
               border:1px solid var(--line);border-radius:3px;padding:4px}
.sheet-top .st-meta{flex:1;min-width:0}
.sheet-top h3{font-size:21px;line-height:1.2}
.sheet-close{flex:none;background:var(--card2);border:1px solid var(--line2);
             border-radius:3px;width:30px;height:30px;cursor:pointer;color:var(--ink2);
             font-size:16px;line-height:1;font-family:var(--mono)}
.sheet-close:hover{color:var(--clara);border-color:var(--clara)}
.sheet-body{padding:20px 22px 24px;display:flex;flex-direction:column;gap:18px}
.kvgrid{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));
        gap:1px;background:var(--line);border:1px solid var(--line);border-radius:3px;
        overflow:hidden}
.kvgrid div{background:var(--card);padding:9px 11px}
.kvgrid .k{font-family:var(--mono);font-size:9px;letter-spacing:.1em;
           text-transform:uppercase;color:var(--ink3)}
.kvgrid .v{font-family:var(--mono);font-size:13px;margin-top:4px;overflow-wrap:anywhere}
.mblock{background:var(--card);border:1px solid var(--line);border-inline-start:3px solid var(--rival);
        border-radius:3px;padding:15px 17px}
.mblock.blocked{border-inline-start-color:var(--bad)}
.mblock.ambiguous{border-inline-start-color:var(--amb)}
.mblock.confirmed_match{border-inline-start-color:var(--ok)}
.mblock.no_match{border-inline-start-color:var(--no)}
.mblock h4{font-size:15px;display:flex;gap:9px;align-items:center;flex-wrap:wrap}
.mblock h4 a{font-weight:400;font-size:13px}
.mb-sub{font-family:var(--mono);font-size:10.5px;color:var(--ink3);margin-top:5px}
.mlist{margin:9px 0 0;padding-inline-start:17px;font-size:12.5px;color:var(--ink2)}
.mlist li{margin:2px 0}
.mtag{font-family:var(--mono);font-size:9px;letter-spacing:.09em;text-transform:uppercase;
      color:var(--ink3);margin-top:12px;display:block}
.vtable{width:100%;border-collapse:collapse;font-size:12px;margin-top:6px}
.vtable th,.vtable td{padding:5px 8px;text-align:start;border-bottom:1px solid var(--line)}
.vtable th{font-family:var(--mono);font-size:9px;letter-spacing:.08em;
           text-transform:uppercase;color:var(--ink3);font-weight:400}
.imgstrip{display:flex;gap:6px;flex-wrap:wrap;margin-top:7px}
.imgstrip a{font-family:var(--mono);font-size:10px;padding:3px 6px;border:1px solid var(--line2);
            border-radius:2px;color:var(--ink2);text-decoration:none}
.imgstrip a:hover{border-color:var(--rival);color:var(--rival)}
@media (max-width:620px){
  .mask{padding:0}
  .sheet{border-radius:0;min-height:100%}
  .sheet-top{flex-wrap:wrap}
}
"""

CARD_JS = r"""
(function(){
  // The modal that used to live here is gone. A product card is a link to its
  // own page now, and that page carries everything the modal did plus the
  // market and content sections — so there is one place to look rather than a
  // popup holding half the answer and a link holding the other half. Dropping
  // it also drops the embedded product payload the modal needed, which was the
  // single largest thing on this page.
  var grid = document.getElementById('pgrid');
  var seg = document.getElementById('f-seg'), st = document.getElementById('f-status'),
      q = document.getElementById('f-q'), cnt = document.getElementById('f-count');
  if(!grid || !seg || !st || !q) return;

  function apply(){
    var s=seg.value, t=st.value, needle=(q.value||'').toLowerCase().trim(), shown=0;
    var cards = grid.querySelectorAll('.pcard');
    cards.forEach(function(c){
      var okFam = !s || c.dataset.fam===s;
      var okQ = !needle || (c.dataset.search||'').indexOf(needle)>-1;
      var okSt = !t || (c.dataset.statuses||'').split(' ').indexOf(t)>-1;
      var vis = okFam && okQ && okSt;
      c.style.display = vis? '' : 'none';
      if(vis) shown++;
    });
    // A family whose every card is filtered out is hidden along with its
    // heading, and the count beside each heading is recomputed. Otherwise the
    // number describes what was there on load rather than what is on screen,
    // and a filter that leaves four empty headings behind reads as breakage.
    grid.querySelectorAll('.fam').forEach(function(f){
      var all = f.querySelectorAll('.pcard'), vis = 0;
      all.forEach(function(c){ if(c.style.display!=='none') vis++; });
      f.classList.toggle('fam-empty', vis===0);
      var n = f.querySelector('.fam-h .n');
      if(n) n.textContent = vis;
    });
    cnt.textContent = shown+' of '+cards.length+' products';
  }
  [seg,st].forEach(function(el){ el.addEventListener('change', apply); });
  q.addEventListener('input', apply);
  apply();
})();
"""


def _e(v) -> str:
    if v is None or v == "":
        return '<span class="np">&mdash;</span>'
    if v == "not_published":
        return '<span class="np">not_published</span>'
    return html.escape(str(v))


def _money(amount, currency=None) -> str:
    d = to_decimal(amount)
    if d is None:
        return '<span class="np">unresolved</span>'
    q = d.quantize(Decimal("0.01"))
    s = f"{q:,.2f}"
    if s.endswith(".00"):
        s = s[:-3]
    return html.escape(f"{currency} {s}" if currency else s)


def _pill(status: str) -> str:
    s = html.escape(str(status))
    label = html.escape(STATUS_AR.get(status, status))
    return f'<span class="pill s-{s}">{label}</span>'


def render_price_cards(bundle: dict) -> str:
    """The price report as a card grid, with the full record behind each card."""
    pr = bundle["price"]
    cfg = (bundle.get("run") or {}).get("config") or {}
    cur = cfg.get("currency", "SAR")

    biggest = Decimal("1")
    for p in pr["products"]:
        d = to_decimal(p["clara_price"])
        if d and d > biggest:
            biggest = d
        for m in p["matches"]:
            if m["same_currency"]:
                d = to_decimal(m["competitor_price"])
                if d and d > biggest:
                    biggest = d

    P = ['<section id="prices"><div class="wrap">']
    P.append('<div class="shead"><h2>Clara products and prices</h2>'
             f'<p class="eyebrow">{pr["catalog_size"]} products &middot; '
             'open a card to see the competitors and their prices</p></div>')
    P.append('<p class="lede">Every product in the catalogue appears here. A rival '
             'price is only compared to Clara\'s when both are in the same currency; '
             'prices in another currency are shown as read, never converted.</p>')

    # Grouped and filtered by FAMILY, not by the old three-way segment. The
    # segment split (device / haircare / accessory) is a database detail; the
    # four families are how the business describes what it sells, and a page
    # organised by anything else makes the reader do the translation.
    groups = scope.group_by_family(pr["products"])
    index_of = {pp["product_id"]: i for i, pp in enumerate(pr["products"])}

    # The frame, stated with this page's own counts, so the scope is on screen
    # rather than inferred from whichever products happen to be present.
    P.append(ui.frame_strip(
        counts={f["key"]: len(items) for f, items in groups}))
    P.append('<div class="toolbar">')
    P.append(f'<label for="f-seg">{html.escape("Family")}'
             f'</label><select id="f-seg">'
             f'<option value="">{html.escape("all four families")}'
             f'</option>')
    for fam, items in groups:
        P.append(f'<option value="{html.escape(fam["key"])}">'
                 f'{html.escape(fam["en"])} ({len(items)})</option>')
    P.append('</select>')
    P.append(f'<label for="f-status">'
             f'{html.escape("Match status")}</label>'
             f'<select id="f-status"><option value="">all</option>')
    for s in STATUS_ORDER:
        P.append(f'<option value="{s}">{html.escape(STATUS_AR.get(s, s))}</option>')
    P.append('</select>')
    P.append(f'<label for="f-q">{html.escape("Find")}</label>'
             '<input id="f-q" type="search" '
             'placeholder="product or competitor" size="20">')
    P.append('<span class="count" id="f-count"></span></div>')

    P.append('<div id="pgrid">')
    for fam, items in groups:
        P.append('<section class="fam" data-fam="%s">' % fam["key"])
        P.append('<div class="fam-h">'
                 f'<h2>{html.escape(fam["en"])}</h2>'
                 f'<span class="n">{len(items)}</span>'
                 + (f'<span class="sc">{html.escape(fam["en_scope"])}</span>'
                    if fam.get("en_scope") else "")
                 + '</div>')
        if fam["key"] == "unclassified":
            P.append('<div class="fam-note">In the catalogue, and matching none '
                     'of the four families. Shown rather than hidden: a product '
                     'the frame does not describe is a decision waiting for a '
                     'person, not a rendering error.</div>')
        P.append('<div class="grid">')
        for p in items:
            i = index_of[p["product_id"]]
            statuses = " ".join(sorted({m["status"] for m in p["matches"]})) or "unassigned"
            search = " ".join(filter(None, [
                p["name"].lower(), p["product_id"].lower(), p["segment"], p["category"],
                " ".join((m["competitor_brand"] or "").lower() for m in p["matches"]),
                " ".join((m["competitor_product_name"] or "").lower()
                         for m in p["matches"]),
            ]))
            cd = to_decimal(p["clara_price"])
            cw = float(cd / biggest * 100) if cd else 0.0

            P.append(f'<a class="pcard" '
                     f'href="/product?id={html.escape(p["product_id"])}" '
                     f'data-fam="{html.escape(fam["key"])}" '
                     f'data-seg="{html.escape(p["segment"])}" '
                     f'data-statuses="{html.escape(statuses)}" '
                     f'data-search="{html.escape(search)}">')
            P.append('<div class="pc-top">')
            if p.get("image_url"):
                P.append(f'<img class="pc-img" src="{html.escape(p["image_url"])}" '
                         f'alt="" loading="lazy">')
            else:
                P.append('<div class="pc-imgph">no image</div>')
            P.append('<div class="pc-head">')
            P.append(f'<div class="pc-name">{_e(p["name"])}</div>')
            P.append(f'<div class="pc-meta">{_e(SEG_AR.get(p["segment"], p["segment"]))} &middot; {_e(FMT_AR.get(p["fmt"], p["fmt"]))}'
                     + (f' &middot; ★ {_e(p["rating"])}' if p.get("rating") else "")
                     + '</div>')
            P.append('</div></div>')

            P.append('<div class="pc-price"><b>'
                     + _money(p["clara_price"], p["currency"]) + '</b>'
                     + (f'<span>{_e(p["rating_count"])} reviews</span>'
                        if p.get("rating_count") else "") + '</div>')

            if p["matches"]:
                best = sorted({m["status"] for m in p["matches"]},
                              key=lambda s: STATUS_ORDER.index(s)
                              if s in STATUS_ORDER else 9)
                P.append('<div class="pc-pills">'
                         + "".join(_pill(s) for s in best[:3]) + '</div>')
            else:
                P.append('<div class="pc-pills">'
                         + _pill("unassigned" if p["unassigned"] else "no_match")
                         + '</div>')

            ch = p.get("cheapest_rival")
            if p["matches"]:
                P.append('<div class="pc-rivals">')
                for m in p["matches"][:3]:
                    price = (_money(m["competitor_price"], m["competitor_currency"])
                             if m.get("competitor_price") else
                             '<span class="np">no price</span>')
                    P.append('<div class="pc-rival">'
                             f'<span class="rb">{_e(m["competitor_brand"])}</span>'
                             f'<span class="rp">{price}</span></div>')
                if len(p["matches"]) > 3:
                    P.append(f'<div class="pc-mult">+{len(p["matches"]) - 3} more</div>')
                if ch and ch.get("multiple_of_clara"):
                    mw = float(to_decimal(ch["price"]) / biggest * 100)
                    P.append(f'<div class="pc-bars">'
                             f'<div class="pc-bar c"><i style="width:{cw:.1f}%"></i></div>'
                             f'<div class="pc-bar r"><i style="width:{mw:.1f}%"></i></div></div>')
                    P.append(f'<div class="pc-mult">cheapest rival '
                             f'{html.escape(ch["multiple_of_clara"])}× Clara</div>')
                P.append('</div>')
            else:
                P.append('<div class="pc-none">'
                         + ('no competitor assigned to this category'
                            if p["unassigned"] else 'no counterpart observed') + '</div>')

            P.append('<span class="pc-open">'
                     + html.escape("Everything about this product")
                     + ' &rarr;</span>')
            P.append('</a>')
        P.append('</div>')
        P.append('</section>')
    P.append('</div>')

    P.append('<div class="note">')
    P.append(f'<b>{pr["products_with_a_match"]}</b> of '
             f'<b>{pr["catalog_size"]}</b> products have a confirmed or probable '
             f'counterpart &middot; <b>{pr["products_unassigned"]}</b> have no '
             f'competitor assigned &middot; '
             f'<b>{pr["comparable_price_pairs"]}</b> directly price-comparable in '
             f'{html.escape(str(cur))}.')
    P.append('</div></div></section>')

    # No payload and no modal shell. Every field they carried is rendered
    # server-side on the product page, so shipping the whole catalogue to the
    # browser to fill a popup is work this page no longer does.
    return "\n".join(P)


COMP_JS = r"""
(function(){
  var DATA = window.__COMP__ || {competitors:[]};
  var grid = document.getElementById('cgrid');
  var mask = document.getElementById('mask');
  var sheet = document.getElementById('sheet');
  var seg=document.getElementById('c-seg'), tier=document.getElementById('c-tier'),
      threat=document.getElementById('c-threat'), q=document.getElementById('c-q'),
      cnt=document.getElementById('c-count');
  if(!grid) return;

  function ago(s){
    if(!s) return '<span class="np">&mdash;</span>';
    var d=new Date(s); if(isNaN(d)) return '<span class="np">&mdash;</span>';
    var secs=(Date.now()-d.getTime())/1000;
    var out;
    if(secs<90) out='just now';
    else if(secs<3600) out=Math.floor(secs/60)+' min ago';
    else if(secs<86400){var h=Math.floor(secs/3600); out=h+' hour'+(h!==1?'s':'')+' ago';}
    else {var dy=Math.floor(secs/86400);
          out = dy===1?'yesterday' : dy<7?dy+' days ago'
              : dy<30?Math.floor(dy/7)+' week(s) ago'
              : Math.floor(dy/30)+' month(s) ago';}
    return '<span title="'+esc(d.toUTCString())+'">'+esc(out)+'</span>';
  }

  var TIER={premium:'premium', professional:'professional',
            mid_market:'mid-market', value:'value'};
  var THREAT={high:'high threat', medium:'medium threat', low:'low threat'};
  var SEG={device:'devices', haircare:'haircare'};
  var STAT={confirmed_match:'confirmed', probable_match:'probable',
            ambiguous:'needs a decision', no_match:'no counterpart',
            blocked:'site unavailable', invalidated:'no longer valid'};

  function esc(v){
    if(v===null||v===undefined||v==='') return '<span class="np">&mdash;</span>';
    return String(v).replace(/[&<>"']/g,function(c){
      return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c];});
  }
  function money(a,cur){
    if(a===null||a===undefined||a==='') return '<span class="np">unresolved</span>';
    var n=Number(a); if(isNaN(n)) return esc(a);
    return '<span class="num">'+esc((cur?cur+' ':'')+
      n.toLocaleString('en-US',{minimumFractionDigits:0,maximumFractionDigits:2}))+'</span>';
  }
  function kv(k,v){ return '<div><div class="k">'+esc(k)+'</div><div class="v">'+v+'</div></div>'; }

  function open(idx){
    var c=DATA.competitors[idx]; if(!c) return;
    var p=c.profile||{}, h=[];
    h.push('<div class="sheet-top"><div class="st-meta">');
    h.push('<h3>'+esc(c.brand)+'</h3>');
    h.push('<div class="mb-sub">'+esc(p.origin)+(p.founded?' &middot; founded '+esc(p.founded):'')+
           ' &middot; '+esc((c.segments||[]).map(function(s){return SEG[s]||s;}).join(', '))+'</div>');
    h.push('<div class="cc-pills" style="margin-top:9px">');
    if(p.price_tier) h.push('<span class="pill t-'+esc(p.price_tier)+'">'+esc(TIER[p.price_tier]||p.price_tier)+'</span>');
    if(p.threat_to_clara) h.push('<span class="pill th-'+esc(p.threat_to_clara)+'">'+esc(THREAT[p.threat_to_clara]||p.threat_to_clara)+'</span>');
    h.push('</div></div>');
    h.push('<button class="sheet-close" data-close="1" aria-label="Close">&times;</button></div>');

    h.push('<div class="sheet-body">');
    if(p.positioning) h.push('<div class="note"><b>Market position:</b> '+esc(p.positioning)+'</div>');

    h.push('<span class="mtag">Commercial profile (maintained by a human)</span>');
    h.push('<div class="kvgrid">');
    h.push(kv('Typical price band', p.sar_band? 'SAR '+esc(p.sar_band) : '<span class="np">&mdash;</span>'));
    h.push(kv('Target audience', esc(p.audience)));
    h.push(kv('Saudi availability', esc(p.ksa_presence)));
    h.push(kv('Discount habit', esc(p.discount_habit)));
    h.push('</div>');

    if(p.known_for && p.known_for.length){
      h.push('<span class="mtag">Known for</span><ul class="mlist">');
      p.known_for.forEach(function(k){ h.push('<li>'+esc(k)+'</li>'); });
      h.push('</ul>');
    }
    if(p.threat_note){
      h.push('<div class="mblock '+(p.threat_to_clara==='high'?'blocked':
             (p.threat_to_clara==='medium'?'ambiguous':'no_match'))+'">');
      h.push('<h4>What it means for Clara '+(p.threat_to_clara?
             '<span class="pill th-'+esc(p.threat_to_clara)+'">'+esc(THREAT[p.threat_to_clara])+'</span>':'')+'</h4>');
      h.push('<div style="margin-top:8px;font-size:13.5px">'+esc(p.threat_note)+'</div>');
      h.push('</div>');
    }

    h.push('<span class="mtag">What the system actually observed</span>');
    h.push('<div class="kvgrid">');
    h.push(kv('Counterpart products', esc(c.matched_count)));
    h.push(kv('Observed price range', c.observed_price_min
      ? money(c.observed_price_min,(c.observed_currencies||[])[0])+' – '+money(c.observed_price_max,'')
      : '<span class="np">no price observed</span>'));
    h.push(kv('Live offers', esc(c.offer_count)));
    h.push(kv('In stock / out of stock', esc(c.in_stock)+' / '+esc(c.out_of_stock)));
    h.push(kv('Pages unavailable', esc(c.unreachable)));
    h.push(kv('Brand sites', (c.sites||[]).length? esc((c.sites||[]).join(', ')):'<span class="np">&mdash;</span>'));
    h.push(kv('Retailers', (c.retailers||[]).length? esc((c.retailers||[]).join(', ')):'<span class="np">&mdash;</span>'));
    h.push('</div>');

    if(c.offers && c.offers.length){
      h.push('<span class="mtag">Offers read on this competitor&rsquo;s pages ('
             +c.offers.length+')</span>');
      h.push('<table class="vtable"><thead><tr><th>On product</th><th>Offer</th>'+
             '<th>Now</th><th>Was</th><th>Cut</th><th>Against Clara</th>'+
             '<th>Seen</th></tr></thead><tbody>');
      c.offers.forEach(function(o){
        // The product name is the link: an offer that cannot be opened cannot
        // be verified, and verifying is the whole point of showing it.
        var nm = o.url
          ? '<a href="'+esc(o.url)+'" rel="nofollow noopener">'+esc(o.on||'the page')+'</a>'
          : esc(o.on||'');
        var vs = o.clara_product
          ? esc(o.clara_product)+' &middot; '+money(o.clara_price,'SAR')
          : '<span class="np">&mdash;</span>';
        h.push('<tr><td>'+nm+'</td><td>'+esc(o.text)+'</td><td>'+
               money(o.price,o.currency)+'</td><td>'+
               (o.was? money(o.was,o.currency):'<span class="np">&mdash;</span>')+'</td><td>'+
               (o.discount_percent? esc(o.discount_percent)+'%':'<span class="np">&mdash;</span>')+
               '</td><td>'+vs+'</td><td>'+ago(o.observed_at)+'</td></tr>');
      });
      h.push('</tbody></table>');
      if(c.offer_count > c.offers.length){
        h.push('<p class="mnote">'+(c.offer_count-c.offers.length)+
               ' further offer(s) recorded for this competitor.</p>');
      }
    } else {
      h.push('<span class="mtag">Offers</span>');
      h.push('<p class="mnote">No promotion was printed on any page the Agent '+
             'read for this competitor. That is not the same as this competitor '+
             'running no promotions &mdash; only that none appeared on the pages '+
             'that were readable.</p>');
    }

    if(c.matched_products && c.matched_products.length){
      h.push('<span class="mtag">Counterparts to Clara products</span>');
      h.push('<table class="vtable"><thead><tr><th>Clara product</th><th>Clara price</th>'+
             '<th>Competitor product</th><th>Its price</th><th>Status</th></tr></thead><tbody>');
      c.matched_products.forEach(function(m){
        var nm = m.competitor_url
          ? '<a href="'+esc(m.competitor_url)+'" rel="nofollow noopener">'+esc(m.competitor_product)+'</a>'
          : esc(m.competitor_product);
        h.push('<tr><td>'+esc(m.clara_product)+'</td><td>'+money(m.clara_price,'SAR')+
               '</td><td>'+nm+'</td><td>'+money(m.price,m.currency)+'</td><td>'+
               '<span class="pill s-'+esc(m.status)+'">'+esc(STAT[m.status]||m.status)+'</span></td></tr>');
      });
      h.push('</tbody></table>');
    }
    h.push('</div>');

    sheet.innerHTML=h.join('');
    mask.classList.add('open');
    document.body.style.overflow='hidden';
    var b=sheet.querySelector('[data-close]'); if(b) b.focus();
  }
  function close(){ mask.classList.remove('open'); document.body.style.overflow=''; sheet.innerHTML=''; }

  grid.addEventListener('click',function(ev){
    var card=ev.target.closest('.ccard'); if(card) open(Number(card.dataset.idx));
  });
  grid.addEventListener('keydown',function(ev){
    if(ev.key!=='Enter'&&ev.key!==' ') return;
    var card=ev.target.closest('.ccard');
    if(card){ ev.preventDefault(); open(Number(card.dataset.idx)); }
  });
  mask.addEventListener('click',function(ev){
    if(ev.target===mask||ev.target.hasAttribute('data-close')) close();
  });
  document.addEventListener('keydown',function(ev){ if(ev.key==='Escape') close(); });

  function apply(){
    var s=seg.value,t=tier.value,th=threat.value,n=(q.value||'').toLowerCase().trim(),shown=0;
    var all=grid.querySelectorAll('.ccard');
    all.forEach(function(c){
      // The first filter is the product family the card is filed under, which
      // is what the sections below are grouped by.
      var ok = (!s || c.dataset.fam===s)
            && (!t || c.dataset.tier===t)
            && (!th || c.dataset.threat===th)
            && (!n || (c.dataset.search||'').indexOf(n)>-1);
      c.style.display = ok? '' : 'none';
      if(ok) shown++;
    });
    // Hide a family heading whose cards are all filtered out, and recount the
    // rest, so the number beside a heading always describes what is under it.
    grid.querySelectorAll('.fam').forEach(function(f){
      var cards=f.querySelectorAll('.ccard'), vis=0;
      cards.forEach(function(c){ if(c.style.display!=='none') vis++; });
      f.classList.toggle('fam-empty', vis===0);
      var lab=f.querySelector('.fam-h .n');
      if(lab) lab.textContent = vis;
    });
    cnt.textContent = shown+' of '+all.length+' competitors';
  }
  [seg,tier,threat].forEach(function(el){ el.addEventListener('change',apply); });
  q.addEventListener('input',apply);
  apply();

  // Arriving from a decision. A decision that links to "the competitor page"
  // and drops the reader at the top of a 46-card grid has not actually linked
  // to anything, so ?focus=<key> finds the card, marks it, and opens it.
  function focusFrom(){
    var m = /[?&]focus=([^&#]+)/.exec(location.search);
    if(!m) return;
    var key = decodeURIComponent(m[1]).toLowerCase();
    // Matched by walking the cards rather than by building a selector, so a key
    // never has to be escaped into one.
    var card = null;
    grid.querySelectorAll('.ccard').forEach(function(c){
      if(!card && (c.dataset.key||'').toLowerCase() === key) card = c;
    });
    if(!card) return;
    // Clear the filters first, or a focused card that a filter is hiding
    // silently does nothing.
    seg.value=''; tier.value=''; threat.value=''; q.value=''; apply();
    grid.querySelectorAll('.ccard.focused').forEach(function(c){
      c.classList.remove('focused'); });
    card.classList.add('focused');
    card.scrollIntoView({block:'center', behavior:'smooth'});
    open(Number(card.dataset.idx));
  }
  focusFrom();
  window.addEventListener('popstate', focusFrom);
})();
"""
