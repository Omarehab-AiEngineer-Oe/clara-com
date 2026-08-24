"""Build the source register: every external thing this project reads, with links.

Generated, never typed. The whole point of a provenance document is that a reader
can check it, and a hand-written list of two hundred domains goes stale the first
time someone adds a feed. So this reads the live registry, the trend store, the
discovery tables and the offer sweep, and renders what is actually there —
including, deliberately, the sources that refuse us and the ones that have died.

The refusals are not an appendix. A register that lists only what answered would
imply the market was fully covered, and the honest shape of this system is that
a third of what it asks for says no.

    python make_source_register.py            # writes source_register.html
"""

from __future__ import annotations

import html
import json
import subprocess
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
OUT = ROOT / "source_register.html"


def e(v) -> str:
    return html.escape(str(v if v is not None else ""))


def host(u: str) -> str:
    return (urlsplit(u).hostname or "").removeprefix("www.")


def gather() -> dict:
    """Everything, read from the running system."""
    from clara_monitor import competitors as comp, trend_sources as ts
    from clara_monitor import trend_store
    from clara_monitor.agents.offer_store import OfferStore
    from clara_monitor.config import DB_PATH
    import sqlite3

    db = sqlite3.connect(str(DB_PATH))
    db.row_factory = sqlite3.Row

    st = trend_store.TrendStore(DB_PATH)
    tb = trend_store.build(st)
    st.close()
    read = {s.get("publisher"): s for s in (tb.get("sources") or [])}

    feeds = []
    for s in ts.SOURCES:
        r = read.get(s.publisher) or {}
        feeds.append({
            "publisher": s.publisher, "url": s.url, "kind": s.kind,
            "market": s.market, "weight": s.weight, "note": s.note,
            "ok": bool(r.get("ok")), "items": r.get("items") or 0,
            "kept": r.get("kept") or 0, "signal": r.get("signal") or "",
        })

    rivals = []
    for k, c in comp.REGISTRY.items():
        rivals.append({
            "key": k, "brand": c.brand, "market": c.market, "tier": c.tier,
            "segments": list(c.segments or []),
            "domains": list(c.domains or []),
            "retail_domains": list(c.retail_domains or []),
            "sitemaps": list(c.sitemaps or []), "notes": c.notes or "",
        })

    sweep = [dict(r) for r in db.execute(
        "SELECT competitor_key, competitor, pages_read, offers, refusal, "
        "checked_at FROM swept_status ORDER BY competitor")]

    wa = [dict(r) for r in db.execute(
        "SELECT DISTINCT url, page_type, status FROM wa_page ORDER BY url")]

    clara = [dict(r) for r in db.execute(
        "SELECT product_id, name, url FROM clara_product ORDER BY name")]

    disc = [dict(r) for r in db.execute(
        "SELECT name, url, feed_url, domain, source_type, kind, market, status, "
        "quality_score FROM ds_source ORDER BY source_type, name")]
    db.close()

    retail = Counter(r for c in rivals for r in c["retail_domains"])
    brands_at = defaultdict(list)
    for c in rivals:
        for r in c["retail_domains"]:
            brands_at[r].append(c["brand"])

    return {
        "feeds": feeds,
        "refused": [{"publisher": p, "url": u, "why": w} for p, u, w in ts.REFUSED],
        "dead": [{"publisher": p, "url": u, "why": w} for p, u, w in ts.DEAD],
        "rivals": rivals,
        "retailers": [{"domain": k, "count": v, "brands": sorted(brands_at[k])}
                      for k, v in retail.most_common()],
        "sweep": sweep,
        "wa": wa,
        "clara": clara,
        "discovery": disc,
        "generated": datetime.now(timezone.utc).strftime("%d %B %Y, %H:%M UTC"),
        "scan": tb.get("scan") or {},
        "scan_when": tb.get("scan_when") or "",
    }


# --------------------------------------------------------------------------
# vendor and standards sources: the things the project depends on but does not
# scrape. Hand-maintained because they are not in any database, and short enough
# that staleness is visible.
# --------------------------------------------------------------------------

PLATFORM = [
    ("Vertex AI — Gemini pricing",
     "https://cloud.google.com/vertex-ai/generative-ai/pricing",
     "The per-million-token rates in clara_monitor/pricing.py. Checked "
     "2026-05-01; that module prints its own age."),
    ("Vertex AI — model reference",
     "https://cloud.google.com/vertex-ai/generative-ai/docs/models",
     "Which model IDs are served, and from which region. gemini-3.5-flash is "
     "global-endpoint only, which is why LOCATION is 'global'."),
    ("google-genai Python SDK",
     "https://googleapis.github.io/python-genai/",
     "The client every model call goes through."),
    ("Application Default Credentials",
     "https://cloud.google.com/docs/authentication/application-default-credentials",
     "How the project authenticates. No key is stored in the repository."),
    ("Vercel Python runtime",
     "https://vercel.com/docs/functions/runtimes/python",
     "The hosted deployment. Read-only filesystem except /tmp, which is why "
     "section 9 of the addendum requires PostgreSQL."),
    ("Robots Exclusion Protocol (RFC 9309)",
     "https://www.rfc-editor.org/rfc/rfc9309.html",
     "The standard clara_monitor/access.py honours before every fetch."),
    ("Python urllib.robotparser",
     "https://docs.python.org/3/library/urllib.robotparser.html",
     "The implementation used to read robots.txt."),
    ("schema.org Product / Offer",
     "https://schema.org/Product",
     "The JSON-LD vocabulary most prices are extracted from."),
    ("Open Graph protocol",
     "https://ogp.me/",
     "og:site_name and og:title, used to name a publisher and a page."),
    ("Public Suffix List",
     "https://publicsuffix.org/",
     "The reference behind the 29 two-part suffixes in "
     "discovery/feeds.py — the fix for chinadaily.com.cn being read as "
     "'com.cn'."),
    ("RSS 2.0 specification",
     "https://www.rssboard.org/rss-specification",
     "The feed format the trend collector parses."),
    ("Atom (RFC 4287)",
     "https://www.rfc-editor.org/rfc/rfc4287",
     "The other feed format it parses."),
]

KIND_LABEL = {
    "consumer_press": "Consumer press",
    "trade_press": "Trade press",
    "retail_press": "Retail press",
    "search_demand": "Search demand",
}

MARKET_LABEL = {
    "ME": "Middle East", "US": "United States", "UK": "United Kingdom",
    "KR": "South Korea", "CN": "China", "GLOBAL": "Global",
}

REFUSAL_MEANING = {
    "http_forbidden": "answered 403 to a plain public request",
    "forbidden": "answered 403 to a plain public request",
    "captcha_challenge": "served a CAPTCHA or bot-check page",
    "login_required": "the content sits behind a sign-in",
    "transport_error": "the connection failed or timed out",
    "http_unavailable": "answered 503, or the host did not resolve",
    "robots_disallowed": "robots.txt disallows this path for our agent",
    "HTTP 404": "the address no longer exists",
    "HTTP 403": "answered 403 to a plain public request",
}


def meaning(why: str) -> str:
    return REFUSAL_MEANING.get(why, why or "")


# --------------------------------------------------------------------------

CSS = """
:root{
  --ink:#191317; --ink2:#4A4048; --ink3:#7B707A; --ink4:#A69DA4;
  --paper:#FCFBFB; --card:#FFFFFF; --wash:#F5F1F3; --line:#E7E0E4;
  --line2:#D6CCD2; --rose:#B8446E; --rose-wash:#FAEDF2;
  --ok:#2E6B4F; --ok-wash:#E9F2ED; --no:#A83A3A; --no-wash:#F9ECEC;
  --dim:#7B707A; --dim-wash:#F1EEF0;
  --mono:"Cascadia Mono",Consolas,"SF Mono",ui-monospace,Menlo,monospace;
  --sans:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
  --serif:"Iowan Old Style","Palatino Linotype",Palatino,Georgia,serif;
}
:root:not([data-theme="light"]){}
@media (prefers-color-scheme: dark){
  :root:not([data-theme="light"]){
    --ink:#F2EDF0; --ink2:#C3B9C0; --ink3:#948A92; --ink4:#6E6570;
    --paper:#141013; --card:#1C171B; --wash:#231D22; --line:#2E2730;
    --line2:#3E3540; --rose:#E88BAE; --rose-wash:#2C1B24;
    --ok:#79C79B; --ok-wash:#16261E; --no:#E58A8A; --no-wash:#2A1919;
    --dim:#948A92; --dim-wash:#231D22;
  }
}
:root[data-theme="dark"]{
  --ink:#F2EDF0; --ink2:#C3B9C0; --ink3:#948A92; --ink4:#6E6570;
  --paper:#141013; --card:#1C171B; --wash:#231D22; --line:#2E2730;
  --line2:#3E3540; --rose:#E88BAE; --rose-wash:#2C1B24;
  --ok:#79C79B; --ok-wash:#16261E; --no:#E58A8A; --no-wash:#2A1919;
  --dim:#948A92; --dim-wash:#231D22;
}

*{box-sizing:border-box}
body{background:var(--paper);color:var(--ink);font-family:var(--sans);
     font-size:15px;line-height:1.65;margin:0;
     -webkit-font-smoothing:antialiased}
.wrap{max-width:1080px;margin:0 auto;padding:0 26px}
a{color:var(--rose);text-decoration:none;
  border-bottom:1px solid color-mix(in oklab,var(--rose) 30%,transparent)}
a:hover{border-bottom-color:var(--rose)}
a:focus-visible,button:focus-visible,input:focus-visible{
  outline:2px solid var(--rose);outline-offset:2px;border-radius:2px}

/* ---- masthead: a register has a title page, not a hero ---- */
header.top{border-bottom:2px solid var(--ink);padding:52px 0 26px;
           margin-bottom:0;background:var(--paper)}
.kicker{font-family:var(--mono);font-size:10.5px;letter-spacing:.16em;
        text-transform:uppercase;color:var(--rose);font-weight:700}
h1{font-family:var(--serif);font-size:clamp(34px,6vw,54px);line-height:1.02;
   letter-spacing:-.022em;margin:14px 0 0;font-weight:600;text-wrap:balance}
.sub{font-size:16.5px;color:var(--ink2);max-width:66ch;margin:16px 0 0;
     line-height:1.6}
.stamp{font-family:var(--mono);font-size:11.5px;color:var(--ink3);
       margin-top:20px;display:flex;gap:20px;flex-wrap:wrap}
.stamp b{color:var(--ink);font-weight:600}

/* ---- the count band ---- */
.counts{display:grid;grid-template-columns:repeat(auto-fit,minmax(128px,1fr));
        border-bottom:1px solid var(--line);background:var(--card)}
.ct{padding:18px 20px;border-inline-end:1px solid var(--line)}
.ct:last-child{border-inline-end:0}
.ct .n{font-family:var(--serif);font-size:30px;line-height:1;font-weight:600;
       letter-spacing:-.02em;font-variant-numeric:tabular-nums}
.ct .l{font-size:11.5px;color:var(--ink3);margin-top:6px;line-height:1.4}
.ct.no .n{color:var(--no)} .ct.ok .n{color:var(--ok)} .ct.r .n{color:var(--rose)}

/* ---- filter bar, sticky ---- */
.bar{position:sticky;top:0;z-index:20;background:var(--paper);
     border-bottom:1px solid var(--line);padding:12px 0}
.bar .wrap{display:flex;gap:10px;align-items:center;flex-wrap:wrap}
.bar input{font:inherit;font-size:13.5px;padding:7px 12px;border-radius:6px;
           border:1px solid var(--line2);background:var(--card);color:var(--ink);
           min-width:230px;flex:1}
.bar input::placeholder{color:var(--ink4)}
.chip{font-family:var(--mono);font-size:11px;letter-spacing:.04em;
      text-transform:uppercase;padding:6px 11px;border-radius:20px;cursor:pointer;
      border:1px solid var(--line2);background:var(--card);color:var(--ink2);
      font-weight:600}
.chip[aria-pressed="true"]{background:var(--ink);color:var(--paper);
                           border-color:var(--ink)}
.hits{font-family:var(--mono);font-size:11.5px;color:var(--ink3);
      margin-inline-start:auto;white-space:nowrap}

/* ---- sections ---- */
section{padding:46px 0 8px;border-top:1px solid var(--line)}
section:first-of-type{border-top:0}
.sh{display:flex;gap:16px;align-items:baseline;flex-wrap:wrap;margin-bottom:8px}
h2{font-family:var(--serif);font-size:27px;font-weight:600;margin:0;
   letter-spacing:-.015em}
.tag{font-family:var(--mono);font-size:11px;color:var(--ink3);
     letter-spacing:.05em}
.lede{color:var(--ink2);max-width:74ch;margin:0 0 22px;font-size:14.5px}

/* ---- the register table ---- */
.reg{width:100%;border-collapse:collapse;font-size:13.5px}
.reg th{text-align:start;font-family:var(--mono);font-size:10px;
        letter-spacing:.1em;text-transform:uppercase;color:var(--ink3);
        font-weight:700;padding:0 12px 9px;border-bottom:1px solid var(--line2);
        white-space:nowrap}
.reg td{padding:11px 12px;border-bottom:1px solid var(--line);
        vertical-align:top}
.reg tbody tr:hover{background:var(--wash)}
.reg .nm{font-weight:600;color:var(--ink)}
.reg .u,.mono{font-family:var(--mono);font-size:12px;word-break:break-all;
              line-height:1.5}
.reg .why{color:var(--ink2);font-size:12.5px;line-height:1.5}
.num{font-variant-numeric:tabular-nums;text-align:end;white-space:nowrap;
     font-family:var(--mono);font-size:12px}
.reg tr[hidden]{display:none}

/* status is a stripe, so a scan of the column reads without the words */
.st{display:inline-flex;align-items:center;gap:6px;font-family:var(--mono);
    font-size:10.5px;letter-spacing:.05em;text-transform:uppercase;
    font-weight:700;padding:3px 8px;border-radius:3px;white-space:nowrap}
.st.ok{background:var(--ok-wash);color:var(--ok)}
.st.no{background:var(--no-wash);color:var(--no)}
.st.dim{background:var(--dim-wash);color:var(--dim)}
.st.r{background:var(--rose-wash);color:var(--rose)}

.pill{font-family:var(--mono);font-size:10px;letter-spacing:.04em;
      padding:2px 7px;border-radius:3px;background:var(--wash);color:var(--ink2);
      white-space:nowrap;display:inline-block;margin:1px 3px 1px 0}

.scroll{overflow-x:auto;-webkit-overflow-scrolling:touch;
        border:1px solid var(--line);border-radius:8px;background:var(--card);
        padding:16px 4px 4px}
.note{background:var(--wash);border-inline-start:3px solid var(--rose);
      padding:14px 18px;border-radius:0 7px 7px 0;font-size:13.5px;
      color:var(--ink2);margin:20px 0;line-height:1.6;max-width:80ch}
.note b{color:var(--ink)}
.empty{color:var(--ink3);font-style:italic;padding:14px 12px;font-size:13.5px}

footer{border-top:2px solid var(--ink);margin-top:56px;padding:26px 0 70px;
       font-size:13px;color:var(--ink3)}
footer p{max-width:78ch;margin:0 0 9px}
@media (max-width:640px){
  .reg{font-size:12.5px}
  .ct{padding:14px}
  .stamp{gap:12px}
}
@media print{ .bar{display:none} body{background:#fff} }
"""

JS = """
(function(){
  var q=document.getElementById('q'), hits=document.getElementById('hits');
  var chips=[].slice.call(document.querySelectorAll('.chip[data-f]'));
  var rows=[].slice.call(document.querySelectorAll('.reg tbody tr'));
  var active='';
  function apply(){
    var n=(q.value||'').toLowerCase().trim(), shown=0;
    rows.forEach(function(r){
      var okText=!n||(r.dataset.s||'').indexOf(n)>-1;
      var okState=!active||(r.dataset.state||'')===active;
      var vis=okText&&okState;
      r.hidden=!vis; if(vis) shown++;
    });
    // hide a section whose every row is filtered out
    document.querySelectorAll('section[data-sec]').forEach(function(s){
      var any=[].slice.call(s.querySelectorAll('.reg tbody tr')).some(function(r){return !r.hidden;});
      var has=s.querySelector('.reg');
      if(has) s.style.display = any ? '' : 'none';
    });
    hits.textContent = shown+' of '+rows.length+' entries';
  }
  q.addEventListener('input',apply);
  chips.forEach(function(c){
    c.addEventListener('click',function(){
      var f=c.dataset.f;
      active = (active===f) ? '' : f;
      chips.forEach(function(x){x.setAttribute('aria-pressed', x.dataset.f===active);});
      apply();
    });
  });
  apply();
})();
"""


def row(cells: list, search: str, state: str = "") -> str:
    tds = "".join(cells)
    return (f'<tr data-s="{e(search.lower())}" data-state="{e(state)}">'
            f"{tds}</tr>")


def table(headers: list, rows: list, empty: str = "Nothing recorded.") -> str:
    if not rows:
        return f'<p class="empty">{e(empty)}</p>'
    head = "".join(f"<th>{e(h)}</th>" for h in headers)
    return ('<div class="scroll"><table class="reg"><thead><tr>' + head
            + "</tr></thead><tbody>" + "".join(rows) + "</tbody></table></div>")


def build(d: dict) -> str:
    P = []
    feeds_ok = [f for f in d["feeds"] if f["ok"]]
    items = sum(f["items"] for f in d["feeds"])
    kept = sum(f["kept"] for f in d["feeds"])
    sweep_ok = [s for s in d["sweep"] if not s["refusal"]]
    sweep_no = [s for s in d["sweep"] if s["refusal"]]
    own = [c for c in d["rivals"] if c["domains"]]
    total_external = (len(d["feeds"]) + len(d["refused"]) + len(d["dead"])
                      + len(own) + len(d["retailers"]) + len(PLATFORM) + 1)

    P.append('<title>Clara Source Register</title>')
    P.append(f"<style>{CSS}</style>")

    # ---- masthead
    P.append('<header class="top"><div class="wrap">')
    P.append('<p class="kicker">Data provenance</p>')
    P.append('<h1>Source register</h1>')
    P.append('<p class="sub">Every external thing the Clara intelligence '
             'platform reads, with the address it reads it from and whether it '
             'answers. The sources that refuse us are listed beside the ones '
             'that do not, because a register of only what worked would imply '
             'a coverage this system does not have.</p>')
    P.append(f'<div class="stamp"><span>Generated <b>{e(d["generated"])}</b>'
             f'</span><span>Last trend scan <b>{e(d["scan_when"] or "never")}'
             f'</b></span><span>Read from the live registry, not maintained by '
             f'hand</span></div>')
    P.append('</div></header>')

    # ---- counts
    P.append('<div class="counts">')
    for n, label, cls in [
        (total_external, "External sources registered", "r"),
        (len(feeds_ok), "Feeds that answered", "ok"),
        (len(d["refused"]) + len(d["dead"]), "Feeds refusing or gone", "no"),
        (len(own), "Competitor brands", ""),
        (len(d["retailers"]), "Retailer domains", ""),
        (len(sweep_ok), "Storefronts readable", "ok"),
        (len(sweep_no), "Storefronts refusing", "no"),
        (len(d["clara"]), "Clara products", "r"),
    ]:
        P.append(f'<div class="ct {cls}"><div class="n">{n}</div>'
                 f'<div class="l">{e(label)}</div></div>')
    P.append('</div>')

    # ---- filter
    P.append('<div class="bar"><div class="wrap">')
    P.append('<input id="q" type="search" placeholder="Filter every table — '
             'publisher, brand, domain, reason…" aria-label="Filter sources">')
    for f, lab in (("ok", "Answers"), ("no", "Refuses"), ("dead", "Gone")):
        P.append(f'<button class="chip" data-f="{f}" aria-pressed="false">'
                 f'{e(lab)}</button>')
    P.append('<span class="hits" id="hits"></span>')
    P.append('</div></div>')

    P.append('<main class="wrap">')

    # ---- 1. trend feeds
    P.append('<section data-sec="feeds">')
    P.append(f'<div class="sh"><h2>Trend feeds</h2>'
             f'<span class="tag">{len(d["feeds"])} registered · '
             f'{len(feeds_ok)} answered on the last scan · {items:,} items read '
             f'· {kept:,} kept</span></div>')
    P.append('<p class="lede">RSS and Atom feeds across six markets. '
             '<b>Kept</b> is how many items survived the beauty filter — the '
             'gap between read and kept is the point of having a filter. '
             'Weight is how much a source counts toward a trend score.</p>')
    rows = []
    for f in sorted(d["feeds"], key=lambda x: (not x["ok"], x["market"],
                                               x["publisher"])):
        st = ('<span class="st ok">answers</span>' if f["ok"]
              else '<span class="st no">no answer</span>')
        rows.append(row([
            f'<td><div class="nm">{e(f["publisher"])}</div>'
            f'<div class="u"><a href="{e(f["url"])}" rel="nofollow noopener">'
            f'{e(f["url"])}</a></div></td>',
            f'<td><span class="pill">{e(MARKET_LABEL.get(f["market"], f["market"]))}</span>'
            f'<span class="pill">{e(KIND_LABEL.get(f["kind"], f["kind"]))}</span></td>',
            f'<td>{st}</td>',
            f'<td class="num">{f["items"]:,}</td>',
            f'<td class="num">{f["kept"]:,}</td>',
            f'<td class="num">{f["weight"]}</td>',
            f'<td class="why">{e(f["note"])}</td>',
        ], f'{f["publisher"]} {f["url"]} {f["kind"]} {f["market"]} {f["note"]}',
            "ok" if f["ok"] else "no"))
    P.append(table(["Publisher and feed", "Market / kind", "Status", "Items",
                    "Kept", "Weight", "Why it is registered"], rows))
    P.append('</section>')

    # ---- 2. refused
    P.append('<section data-sec="refused">')
    P.append(f'<div class="sh"><h2>Publishers that refuse automated access</h2>'
             f'<span class="tag">{len(d["refused"])} sources</span></div>')
    P.append('<p class="lede">Each of these was asked once, politely, with a '
             'single unrotated user agent and no credentials. Each said no. '
             'They stay on this list rather than being deleted, so nobody adds '
             'them again next quarter and so the coverage gap is visible. '
             '<b>Nothing here is retried with different headers.</b></p>')
    rows = []
    for r in sorted(d["refused"], key=lambda x: x["publisher"]):
        rows.append(row([
            f'<td><div class="nm">{e(r["publisher"])}</div>'
            f'<div class="u">{e(r["url"])}</div></td>',
            f'<td><span class="st no">{e(r["why"].replace("_", " "))}</span></td>',
            f'<td class="why">{e(meaning(r["why"]))}</td>',
        ], f'{r["publisher"]} {r["url"]} {r["why"]}', "no"))
    P.append(table(["Publisher", "Signal", "What that means"], rows))
    P.append('</section>')

    # ---- 3. dead
    P.append('<section data-sec="dead">')
    P.append(f'<div class="sh"><h2>Feeds that no longer exist</h2>'
             f'<span class="tag">{len(d["dead"])} sources</span></div>')
    P.append('<p class="lede">These answered once and now return nothing. Kept '
             'for the same reason as the refusals: a dead address that is '
             'quietly dropped gets rediscovered and re-added.</p>')
    rows = []
    for r in sorted(d["dead"], key=lambda x: x["publisher"]):
        rows.append(row([
            f'<td><div class="nm">{e(r["publisher"])}</div>'
            f'<div class="u">{e(r["url"])}</div></td>',
            f'<td><span class="st dim">{e(r["why"])}</span></td>',
            f'<td class="why">{e(meaning(r["why"]))}</td>',
        ], f'{r["publisher"]} {r["url"]} {r["why"]}', "dead"))
    P.append(table(["Publisher", "Signal", "What that means"], rows))
    P.append('</section>')

    # ---- 4. competitors
    P.append('<section data-sec="rivals">')
    P.append(f'<div class="sh"><h2>Competitor brands</h2>'
             f'<span class="tag">{len(d["rivals"])} registered · '
             f'{len(own)} with their own Saudi domain</span></div>')
    P.append('<p class="lede">Every brand the price monitor is allowed to '
             'read. <b>Own site</b> is the brand&rsquo;s own storefront; '
             '<b>via retailers</b> are the marketplaces where the same brand is '
             'also sold, used when the brand site refuses or has no Saudi '
             'price.</p>')
    rows = []
    for c in sorted(d["rivals"], key=lambda x: x["brand"].lower()):
        dom = "".join(
            f'<div class="u"><a href="https://{e(x)}" rel="nofollow noopener">'
            f'{e(x)}</a></div>' for x in c["domains"]) or \
            '<span class="st dim">no own site</span>'
        ret = "".join(f'<span class="pill">{e(x)}</span>'
                      for x in c["retail_domains"]) or \
            '<span class="pill">none</span>'
        segs = "".join(f'<span class="pill">{e(s)}</span>'
                       for s in c["segments"])
        rows.append(row([
            f'<td><div class="nm">{e(c["brand"])}</div>{segs}</td>',
            f'<td>{dom}</td>',
            f'<td>{ret}</td>',
            f'<td class="why">{e(c["notes"])}</td>',
        ], f'{c["brand"]} {c["key"]} {" ".join(c["domains"])} '
           f'{" ".join(c["retail_domains"])} {c["notes"]}'))
    P.append(table(["Brand", "Own site", "Also sold via", "Note"], rows))
    P.append('</section>')

    # ---- 5. retailers
    P.append('<section data-sec="retail">')
    P.append(f'<div class="sh"><h2>Saudi retailers and marketplaces</h2>'
             f'<span class="tag">{len(d["retailers"])} domains</span></div>')
    P.append('<p class="lede">Where competitor products are also listed. These '
             'matter because a brand site with no Saudi price often has one '
             'here, in riyals, on a page that can be read.</p>')
    rows = []
    for r in d["retailers"]:
        rows.append(row([
            f'<td><div class="nm"><a href="https://{e(r["domain"])}" '
            f'rel="nofollow noopener">{e(r["domain"])}</a></div></td>',
            f'<td class="num">{r["count"]}</td>',
            f'<td class="why">{e(", ".join(r["brands"]))}</td>',
        ], f'{r["domain"]} {" ".join(r["brands"])}'))
    P.append(table(["Domain", "Brands", "Which brands"], rows))
    P.append('</section>')

    # ---- 6. storefront sweep
    P.append('<section data-sec="sweep">')
    P.append(f'<div class="sh"><h2>Storefronts probed for offers</h2>'
             f'<span class="tag">{len(d["sweep"])} probed · {len(sweep_ok)} '
             f'readable · {sum(s["offers"] for s in d["sweep"])} offer lines '
             f'read</span></div>')
    P.append('<p class="lede">The offer sweep asks each brand&rsquo;s own '
             'storefront what it is currently advertising. Roughly half refuse. '
             'A refusal is recorded as a refusal &mdash; never as &ldquo;this '
             'brand is running no promotions&rdquo;.</p>')
    rows = []
    for s in sorted(d["sweep"], key=lambda x: (bool(x["refusal"]),
                                               x["competitor"].lower())):
        if s["refusal"]:
            st = (f'<span class="st no">'
                  f'{e(s["refusal"].replace("_", " "))}</span>')
        else:
            st = '<span class="st ok">read</span>'
        rows.append(row([
            f'<td class="nm">{e(s["competitor"])}</td>',
            f'<td>{st}</td>',
            f'<td class="num">{s["pages_read"]}</td>',
            f'<td class="num">{s["offers"]}</td>',
            f'<td class="why">{e(meaning(s["refusal"]) if s["refusal"] else "the storefront answered a plain public request")}</td>',
        ], f'{s["competitor"]} {s["refusal"]}',
            "no" if s["refusal"] else "ok"))
    P.append(table(["Brand", "Result", "Pages", "Offers", "What happened"],
                   rows))
    P.append('</section>')

    # ---- 7. clara's own
    P.append('<section data-sec="clara">')
    P.append(f'<div class="sh"><h2>Clara&rsquo;s own site</h2>'
             f'<span class="tag">{len(d["clara"])} products in the '
             f'catalogue</span></div>')
    P.append('<p class="lede">The one site this project is allowed to render '
             'with a browser when a plain request is refused, because it is '
             'the operator&rsquo;s own property. Clara&rsquo;s storefront '
             'serves a JavaScript bot-check at HTTP&nbsp;200, so the website '
             'analysis reads it through a local Chromium with the same user '
             'agent. No competitor gets that treatment.</p>')
    rows = [row([
        '<td><div class="nm">Clara Hair</div>'
        '<div class="u"><a href="https://clarahair.com/en" '
        'rel="nofollow noopener">https://clarahair.com/en</a></div></td>',
        '<td><span class="st r">own property</span></td>',
        f'<td class="num">{len(d["clara"])}</td>',
        '<td class="why">Salla-hosted storefront. Catalogue, prices and '
        'product pages; the seed crawl in data/ is the fallback when the live '
        'site is behind its bot-check.</td>',
    ], "clara clarahair salla", "ok")]
    P.append(table(["Site", "Relationship", "Products", "What is read from it"],
                   rows))

    if d["wa"]:
        pages_ok = [p for p in d["wa"] if p["status"] == "OK"]
        P.append(f'<p class="lede" style="margin-top:26px">Pages the website '
                 f'analysis has actually collected: {len(pages_ok)} read of '
                 f'{len(d["wa"])} attempted.</p>')
        rows = []
        for p in d["wa"]:
            good = p["status"] == "OK"
            rows.append(row([
                f'<td class="u"><a href="{e(p["url"])}" rel="nofollow noopener">'
                f'{e(p["url"])}</a></td>',
                f'<td><span class="pill">{e(p["page_type"])}</span></td>',
                f'<td><span class="st {"ok" if good else "no"}">'
                f'{e(p["status"].lower())}</span></td>',
            ], f'{p["url"]} {p["page_type"]} {p["status"]}',
                "ok" if good else "no"))
        P.append(table(["Page", "Type", "Status"], rows))
    P.append('</section>')

    # ---- 8. platform
    P.append('<section data-sec="platform">')
    P.append(f'<div class="sh"><h2>Platform, vendor and standards</h2>'
             f'<span class="tag">{len(PLATFORM)} references</span></div>')
    P.append('<p class="lede">Not scraped &mdash; depended on. These are the '
             'specifications the code implements and the services it runs on. '
             'This is the only table on the page maintained by hand, which is '
             'why it is short.</p>')
    rows = []
    for name, url, why in PLATFORM:
        rows.append(row([
            f'<td><div class="nm">{e(name)}</div>'
            f'<div class="u"><a href="{e(url)}" rel="nofollow noopener">'
            f'{e(url)}</a></div></td>',
            f'<td class="why">{e(why)}</td>',
        ], f"{name} {url} {why}"))
    P.append(table(["Reference", "What it is used for"], rows))
    P.append('</section>')

    # ---- 9. discovery
    P.append('<section data-sec="discovery">')
    seeds = [x for x in d["discovery"] if x["source_type"] == "seed"]
    found = [x for x in d["discovery"] if x["source_type"] != "seed"]
    P.append(f'<div class="sh"><h2>The discovery registry</h2>'
             f'<span class="tag">{len(seeds)} seed · {len(found)} '
             f'discovered</span></div>')
    P.append('<p class="lede">The source list is meant to grow: the discovery '
             'loop reads article pages for outbound links to publishers it does '
             'not know, scores each candidate, and activates only those above '
             '0.80. <b>Discovery is not activation</b> &mdash; a candidate '
             'between 0.60 and 0.79 is kept and watched but never scanned. '
             + (f'Nothing has been activated yet: the registry is still all '
                f'{len(seeds)} seeds, which is the honest state rather than a '
                f'failure to report one.' if not found else
                f'{len(found)} source(s) have been added by the loop.')
             + '</p>')
    if found:
        rows = []
        for x in found:
            rows.append(row([
                f'<td><div class="nm">{e(x["name"])}</div>'
                f'<div class="u">{e(x["feed_url"] or x["url"])}</div></td>',
                f'<td><span class="pill">{e(x["source_type"])}</span></td>',
                f'<td><span class="st {"ok" if x["status"]=="active" else "dim"}">'
                f'{e(x["status"])}</span></td>',
                f'<td class="num">{x["quality_score"]}</td>',
            ], f'{x["name"]} {x["domain"]} {x["status"]}',
                "ok" if x["status"] == "active" else ""))
        P.append(table(["Source", "Origin", "Status", "Score"], rows))
    P.append('</section>')

    P.append('</main>')

    # ---- footer
    P.append('<footer><div class="wrap">')
    P.append('<p><b>How this page was made.</b> Generated by '
             '<span class="mono">make_source_register.py</span> from the live '
             'competitor registry, the trend store, the discovery tables and '
             'the last offer sweep. Only the platform-and-standards table is '
             'maintained by hand.</p>')
    P.append('<p><b>The access policy behind every row.</b> One never-rotated '
             'user agent, robots.txt honoured before every fetch, no '
             'credentials, no CAPTCHA solving, and a block treated as a '
             'terminal result that goes to a person. Roughly a third of the '
             'sources here refuse us, and that is recorded rather than worked '
             'around.</p>')
    P.append('<p>Counts on this page describe what was registered and what was '
             'observed on the runs named at the top. They are not a claim about '
             'the whole market.</p>')
    P.append('</div></footer>')
    P.append(f"<script>{JS}</script>")
    return "\n".join(P)


def main() -> int:
    d = gather()
    OUT.write_text(build(d), encoding="utf-8")
    print(f"  {OUT.name}: {OUT.stat().st_size:,} bytes")
    print(f"  feeds {len(d['feeds'])} | refused {len(d['refused'])} | "
          f"dead {len(d['dead'])} | brands {len(d['rivals'])} | "
          f"retailers {len(d['retailers'])} | storefronts {len(d['sweep'])} | "
          f"platform {len(PLATFORM)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
