"""The application shell: one chrome, one vocabulary, five tabs.

Section 10 opens with "use a consistent application shell, navigation, page title
and page-level actions", and section 2 retires the thing that made that
impossible — a single long page carrying every product, competitor, offer and
human task at once. So this module owns the frame and every page fills it in.

Three rules are enforced here rather than trusted to each page.

**Status, confidence, freshness and provenance look the same everywhere.**
`pill`, `confidence`, `fresh` and `prov` are the only ways to render them, and
`prov` takes its words from `ops.provenance_badge`, so the four definitions in 8.2
have exactly one wording across a product page, an action card and an agent
citation.

**Filters live in the URL.** `filter_bar` emits a GET form pointed at the current
path, so a filtered list is a link — which is what makes "make details routable
and bookmarkable" true of lists as well as records.

**The next valid action sits beside the unresolved item.** `empty` takes a call to
action rather than only a message, and `panel` takes page-level actions, so a page
cannot show a problem without offering the move.

The Agent is a header control on every page, not a page of its own (3.1): the
panel is rendered into the shell so it inherits whatever record the reader is
looking at. It opens by adding `agent=1` to the current URL, which means it works
with scripting off and survives a reload with its context intact.
"""

from __future__ import annotations

import html
import urllib.parse

from ..ops import provenance_badge

# --------------------------------------------------------------------------
# the five tabs of section 3, and what each one is for
# --------------------------------------------------------------------------

TABS = [
    ("overview", "/overview", "Overview",
     "Freshness, coverage, unresolved work and verified movement."),
    ("products", "/products", "Products",
     "The Clara catalogue, its assigned competitors and their prices."),
    ("competitors", "/competitors", "Competitors",
     "The competitor directory, their products, sources and offers."),
    ("actions", "/actions", "Actions",
     "The operational work queue, resolved in place."),
    ("requests", "/requests", "Requests",
     "Questions raised for a person, and their answers."),
]

# The Admin menu of 3.1. Deliberately not in the business navigation: these are
# administration, and mixing them into the five tabs is what made the old page a
# list of everything.
ADMIN_LINKS = [
    ("/admin/users", "Users", "Accounts, roles and account state."),
    ("/admin/requests", "Request administration", "Every request, and its owner."),
    ("/admin/sources", "Sources & feeds", "Approved sources and integrations."),
    ("/admin/audit", "Audit history", "Who changed what, and from what to what."),
    ("/admin/system", "System", "Storage, schema, imports and retention."),
]


def e(v) -> str:
    return html.escape(str(v if v is not None else ""))


def one(query: dict, key: str, default: str = "") -> str:
    """One value from a parsed query string, whether or not it arrived as a list."""
    v = (query or {}).get(key)
    if isinstance(v, list):
        v = v[0] if v else None
    return str(v) if v not in (None, "") else default


def qs(query: dict, **over) -> str:
    """Rebuild a query string with overrides. `None` drops a key.

    Every filter, sort and page control routes through this, which is why a
    filtered list stays a link when you change one facet of it.
    """
    out = {}
    for k, v in (query or {}).items():
        if isinstance(v, list):
            v = v[0] if v else None
        if v not in (None, "", []):
            out[k] = v
    for k, v in over.items():
        if v is None:
            out.pop(k, None)
        else:
            out[k] = v
    return ("?" + urllib.parse.urlencode(out, doseq=False)) if out else ""


# --------------------------------------------------------------------------
# the stylesheet
# --------------------------------------------------------------------------

CSS = """
*,*::before,*::after{box-sizing:border-box}
html{-webkit-text-size-adjust:100%}
body,h1,h2,h3,h4,p,ul,ol,li,figure,dl,dd,fieldset{margin:0;padding:0}
ul,ol{list-style:none}
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
  --focus:#1f6fb2;
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
  --focus:#7fb6f5;
}}
body{background:var(--bg);color:var(--ink);font-family:var(--sans);
     font-size:14.5px;line-height:1.55;-webkit-font-smoothing:antialiased}
a{color:var(--rival)}
h1,h2,h3{font-family:var(--display);font-weight:600;letter-spacing:-.01em;
         line-height:1.25}

/* Focus is visible everywhere. Section 10 asks for keyboard and focus
   expectations to be met; a shell-wide rule is the only way that stays true as
   pages are added. */
:focus-visible{outline:2px solid var(--focus);outline-offset:2px;border-radius:3px}
.skip{position:absolute;left:-9999px;top:0;background:var(--card);color:var(--ink);
      padding:10px 14px;z-index:100;border:1px solid var(--clara);
      border-radius:0 0 6px 0}
.skip:focus{left:0}

/* ---------------- header ---------------- */
.hd{background:var(--card);border-bottom:1px solid var(--line);position:sticky;
    top:0;z-index:40}
.hd-top{max-width:1440px;margin:0 auto;padding:9px 20px;display:flex;
        gap:12px;align-items:center;flex-wrap:wrap}
.brand{font-family:var(--display);font-size:17px;font-weight:600;color:var(--ink);
       text-decoration:none;white-space:nowrap}
.brand span{color:var(--clara)}
.hd-sp{margin-inline-start:auto;display:flex;gap:8px;align-items:center;
       flex-wrap:wrap}
.hd-who{font-size:12px;color:var(--ink3);white-space:nowrap}
.hd-who b{color:var(--ink2)}

/* ---------------- the five tabs ---------------- */
.tabs{max-width:1440px;margin:0 auto;padding:0 20px;display:flex;gap:2px;
      overflow-x:auto;scrollbar-width:thin}
.tabs a{font-size:13.5px;font-weight:600;color:var(--ink2);text-decoration:none;
        padding:10px 14px;border-bottom:2px solid transparent;white-space:nowrap;
        display:flex;gap:7px;align-items:center}
.tabs a:hover{color:var(--clara)}
.tabs a[aria-current="page"]{color:var(--clara);border-bottom-color:var(--clara)}
.tabs .n{font-size:10.5px;font-weight:700;background:var(--card3);color:var(--ink2);
         border-radius:9px;padding:1px 6px;font-variant-numeric:tabular-nums}
.tabs .n.hot{background:var(--bad);color:#fff}

/* ---------------- buttons ---------------- */
.b{font-family:inherit;font-size:12.5px;font-weight:600;padding:6px 12px;
   border-radius:5px;border:1px solid var(--line2);background:var(--card);
   color:var(--ink2);text-decoration:none;cursor:pointer;display:inline-flex;
   gap:6px;align-items:center;white-space:nowrap;line-height:1.4}
.b:hover{border-color:var(--clara);color:var(--clara)}
.b-pri{background:var(--clara);border-color:var(--clara);color:#fff}
.b-pri:hover{filter:brightness(1.08);color:#fff}
.b-danger:hover{border-color:var(--bad);color:var(--bad)}
.b-sm{font-size:11.5px;padding:4px 9px}
.b[disabled],.b[aria-disabled="true"]{opacity:.5;cursor:not-allowed}
.menu{position:relative}
.menu>summary{list-style:none;cursor:pointer}
.menu>summary::-webkit-details-marker{display:none}
.menu-body{position:absolute;inset-inline-end:0;top:calc(100% + 6px);z-index:50;
     background:var(--card);border:1px solid var(--line2);border-radius:7px;
     box-shadow:var(--shadow);min-width:272px;padding:6px}
.menu-body a{display:block;padding:8px 11px;border-radius:5px;font-size:13px;
     color:var(--ink);text-decoration:none}
.menu-body a:hover{background:var(--card2);color:var(--clara)}
.menu-body a small{display:block;color:var(--ink3);font-size:11px;font-weight:400}

/* ---------------- layout ---------------- */
.wrap{max-width:1440px;margin:0 auto;padding:22px 20px 70px}
.wrap.narrow{max-width:920px}
.ph{display:flex;gap:16px;align-items:flex-start;justify-content:space-between;
    flex-wrap:wrap;margin-bottom:6px}
.ph h1{font-size:25px}
.ph-acts{display:flex;gap:7px;flex-wrap:wrap}
.lede{font-size:13px;color:var(--ink2);max-width:84ch;margin-bottom:20px;
      line-height:1.65}
.crumbs{font-size:12px;color:var(--ink3);margin-bottom:7px}
.crumbs a{color:var(--ink3);text-decoration:none}
.crumbs a:hover{color:var(--clara)}

.panel{background:var(--card);border:1px solid var(--line);border-radius:8px;
       margin-bottom:16px;overflow:visible}
.panel>h2{font-size:15px;font-family:var(--sans);font-weight:700;
   padding:12px 16px;border-bottom:1px solid var(--line);background:var(--card2);
   display:flex;gap:10px;align-items:center;justify-content:space-between;
   flex-wrap:wrap;border-radius:8px 8px 0 0}
.panel>h2 .pn{font-size:11.5px;font-weight:500;color:var(--ink3)}
.panel-b{padding:16px}
.panel-b.flush{padding:0}
.cols{display:grid;gap:16px;grid-template-columns:minmax(0,2fr) minmax(0,1fr);
      align-items:start}
@media (max-width:980px){.cols{grid-template-columns:1fr}}
.grid{display:grid;gap:12px;grid-template-columns:repeat(auto-fill,minmax(310px,1fr))}

/* ---------------- badges: one vocabulary ---------------- */
.pl{font-size:10.5px;font-weight:700;letter-spacing:.02em;padding:2px 7px;
    border-radius:3px;white-space:nowrap;display:inline-block}
.pl-ok{background:var(--ok-wash);color:var(--ok)}
.pl-amb{background:var(--amb-wash);color:var(--amb)}
.pl-bad{background:var(--bad-wash);color:var(--bad)}
.pl-no{background:var(--no-wash);color:var(--no)}
.pl-info{background:var(--rival-wash);color:var(--rival)}
.pl-clara{background:var(--clara-wash);color:var(--clara)}
.pl-solid{background:var(--bad);color:#fff}
.pl-quiet{background:var(--card3);color:var(--ink3)}
.badges{display:flex;gap:5px;flex-wrap:wrap;align-items:center}

/* provenance: a chip carrying 8.2's definition as its tooltip, everywhere */
.pv{font-size:10.5px;font-weight:600;padding:2px 7px;border-radius:3px;
    white-space:nowrap;display:inline-block;border:1px solid transparent;
    cursor:help}
.pv-automatically_observed{background:var(--rival-wash);color:var(--rival)}
.pv-human_confirmed{background:var(--ok-wash);color:var(--ok);
    border-color:var(--ok)}
.pv-manually_entered{background:var(--amb-wash);color:var(--amb);
    border-color:var(--amb)}
.pv-approved_feed_api{background:var(--clara-wash);color:var(--clara)}

.fr{font-size:10.5px;font-weight:600;padding:2px 7px;border-radius:3px;
    white-space:nowrap;cursor:help;display:inline-block}
.fr-fresh{background:var(--ok-wash);color:var(--ok)}
.fr-recent{background:var(--card3);color:var(--ink2)}
.fr-stale{background:var(--bad-wash);color:var(--bad)}
.fr-unknown{background:var(--no-wash);color:var(--no)}

/* ---------------- stats ---------------- */
.stats{display:grid;gap:10px;
       grid-template-columns:repeat(auto-fit,minmax(158px,1fr))}
.st{background:var(--card);border:1px solid var(--line);border-radius:8px;
    padding:13px 15px;text-decoration:none;color:inherit;display:block}
.st:hover{border-color:var(--clara)}
.st .sv{font-size:26px;font-weight:700;letter-spacing:-.03em;line-height:1.1;
        font-variant-numeric:tabular-nums;font-family:var(--display);
        display:block}
.st .sk{font-size:12px;color:var(--ink2);font-weight:600;margin-top:3px;
        display:block}
.st .sd{font-size:11px;color:var(--ink3);line-height:1.5;margin-top:4px;
        display:block}
.st.hot{border-color:var(--bad)}
.st.hot .sv{color:var(--bad)}
.st.good .sv{color:var(--ok)}
.st.warn .sv{color:var(--amb)}
.st.calm .sv{color:var(--ink3)}

/* ---------------- tables ---------------- */
.scroll{overflow-x:auto}
table.t{width:100%;border-collapse:collapse;font-size:13px}
table.t th{text-align:start;font-size:11px;font-weight:700;color:var(--ink3);
   padding:9px 13px;background:var(--card2);border-bottom:1px solid var(--line2);
   white-space:nowrap;text-transform:uppercase;letter-spacing:.03em}
table.t th a{color:var(--ink3);text-decoration:none}
table.t th a:hover{color:var(--clara)}
table.t td{padding:10px 13px;border-bottom:1px solid var(--line);
   vertical-align:top}
table.t tbody tr:last-child td{border-bottom:0}
table.t tbody tr:hover{background:var(--card2)}
table.t td.num{text-align:end;font-variant-numeric:tabular-nums;
   white-space:nowrap}
table.t .ttl{font-weight:600;color:var(--ink);text-decoration:none;
   display:inline-block}
table.t .ttl:hover{color:var(--clara)}
table.t .sub{font-size:11.5px;color:var(--ink3);margin-top:2px}
.attn{border-inline-start:3px solid var(--bad)}

/* ---------------- filters ---------------- */
.filters{display:flex;gap:9px;flex-wrap:wrap;align-items:flex-end;
   padding:13px 16px;background:var(--card2);border-bottom:1px solid var(--line)}
.f{display:flex;flex-direction:column;gap:3px;min-width:0}
.f label{font-size:10.5px;font-weight:700;color:var(--ink3);
   text-transform:uppercase;letter-spacing:.03em}
.f input,.f select{font-family:inherit;font-size:13px;padding:6px 9px;
   background:var(--card);color:var(--ink);border:1px solid var(--line2);
   border-radius:5px;max-width:100%}
.f.grow{flex:1 1 190px}
.f.grow input{width:100%}
.applied{display:flex;gap:6px;flex-wrap:wrap;align-items:center;
   padding:9px 16px;font-size:11.5px;color:var(--ink3);
   border-bottom:1px solid var(--line);background:var(--card)}
.applied a{color:var(--ink2);text-decoration:none;background:var(--card3);
   border-radius:12px;padding:2px 9px;font-weight:600}
.applied a:hover{color:var(--bad)}

/* ---------------- pager ---------------- */
.pager{display:flex;gap:9px;align-items:center;justify-content:space-between;
   padding:11px 16px;border-top:1px solid var(--line);font-size:12px;
   color:var(--ink3);flex-wrap:wrap}
.pager .pnav{display:flex;gap:6px}

/* ---------------- empty state ---------------- */
.empty{padding:30px 22px;text-align:center;color:var(--ink2)}
.empty h3{font-size:16px;font-family:var(--sans);font-weight:700;
   color:var(--ink);margin-bottom:6px}
.empty p{font-size:13px;max-width:62ch;margin:0 auto;line-height:1.65}
.empty .ea{margin-top:14px;display:flex;gap:8px;justify-content:center;
   flex-wrap:wrap}

/* ---------------- key/value ---------------- */
dl.kv{display:grid;grid-template-columns:minmax(118px,auto) 1fr;gap:7px 14px;
   font-size:13px}
dl.kv dt{color:var(--ink3);font-size:12px;font-weight:600}
dl.kv dd{color:var(--ink);min-width:0;overflow-wrap:anywhere}
.ev{font-size:12px;color:var(--ink3);margin-top:5px;overflow-wrap:anywhere}
.mono{font-family:var(--mono);font-size:11.5px;color:var(--ink3)}
.note{font-size:12.5px;color:var(--ink2);line-height:1.6;background:var(--card2);
   border-radius:6px;padding:10px 12px;border-inline-start:3px solid var(--line2)}
.note.warn{border-inline-start-color:var(--amb);background:var(--amb-wash);
   color:var(--amb)}
.note.bad{border-inline-start-color:var(--bad);background:var(--bad-wash);
   color:var(--bad)}
.note.good{border-inline-start-color:var(--ok);background:var(--ok-wash);
   color:var(--ok)}
.note+.note{margin-top:8px}
.flash{border-radius:7px;padding:11px 14px;font-size:13.5px;margin-bottom:16px;
   line-height:1.55}
.flash.ok{background:var(--ok-wash);color:var(--ok);border:1px solid var(--ok)}
.flash.err{background:var(--bad-wash);color:var(--bad);border:1px solid var(--bad)}

/* ---------------- forms ---------------- */
.form-grid{display:grid;gap:13px;
   grid-template-columns:repeat(auto-fit,minmax(215px,1fr))}
.ff{display:flex;flex-direction:column;gap:5px;min-width:0}
.ff.fw{grid-column:1/-1}
.ff label{font-size:12.5px;font-weight:600;color:var(--ink2)}
.ff .hint{font-size:11.5px;color:var(--ink3);line-height:1.5}
.ff input,.ff select,.ff textarea{font-family:inherit;font-size:14px;
   padding:9px 11px;background:var(--bg);color:var(--ink);
   border:1px solid var(--line2);border-radius:5px;width:100%}
.ff textarea{min-height:88px;resize:vertical;line-height:1.55}
.ff .err{font-size:12px;color:var(--bad);font-weight:600}
.ff input[aria-invalid="true"],.ff textarea[aria-invalid="true"],
.ff select[aria-invalid="true"]{border-color:var(--bad)}
.fbar{display:flex;gap:8px;margin-top:15px;flex-wrap:wrap;align-items:center}
fieldset{border:1px solid var(--line);border-radius:7px;padding:14px 16px;
   margin-bottom:12px}
legend{font-size:13px;font-weight:700;color:var(--ink);padding:0 6px}
fieldset.opt{background:var(--card2)}

/* ---------------- the agent panel (3.1) ---------------- */
.ag-btn.on{background:var(--clara);border-color:var(--clara);color:#fff}
.ag{position:fixed;inset-block:0;inset-inline-end:0;width:min(430px,100vw);
    background:var(--card);border-inline-start:1px solid var(--line2);
    box-shadow:-14px 0 40px -22px rgba(24,19,24,.4);z-index:60;
    display:flex;flex-direction:column}
.ag-h{padding:12px 15px;border-bottom:1px solid var(--line);
   display:flex;gap:10px;align-items:flex-start;justify-content:space-between;
   background:var(--card2)}
.ag-h h2{font-size:14.5px;font-family:var(--sans);font-weight:700}
.ag-h .ctx{font-size:11px;color:var(--ink3);margin-top:2px}
.ag-scroll{flex:1;overflow-y:auto;padding:14px 15px;display:flex;
   flex-direction:column;gap:12px}
.ag-f{padding:12px 15px;border-top:1px solid var(--line);background:var(--card2)}
.ag-f textarea{width:100%;font-family:inherit;font-size:13.5px;padding:9px 11px;
   border:1px solid var(--line2);border-radius:6px;background:var(--card);
   color:var(--ink);min-height:66px;resize:vertical}
.msg{font-size:13px;line-height:1.6}
.msg .who{font-size:10.5px;font-weight:700;text-transform:uppercase;
   letter-spacing:.04em;color:var(--ink3);margin-bottom:4px}
.msg.you .bd{background:var(--clara-wash);color:var(--ink);border-radius:8px;
   padding:9px 12px}
.msg.agent .bd{background:var(--card2);border-radius:8px;padding:10px 12px;
   white-space:pre-wrap}
.msg .cites{margin-top:8px;display:flex;flex-direction:column;gap:5px}
.cite{font-size:11.5px;background:var(--card);border:1px solid var(--line);
   border-radius:6px;padding:7px 9px;display:flex;gap:7px;
   justify-content:space-between;align-items:flex-start;flex-wrap:wrap}
.cite a{text-decoration:none;font-weight:600}
.cite .cm{color:var(--ink3);font-size:10.5px}
.gap{font-size:11.5px;background:var(--amb-wash);color:var(--amb);
   border-radius:6px;padding:7px 9px;margin-top:5px;line-height:1.5}
.scoped{font-size:11.5px;background:var(--no-wash);color:var(--no);
   border-radius:6px;padding:9px 11px;line-height:1.55}
/* 6.2 on the panel at all times, collapsed so it informs without crowding. */
.ag-scope{border-bottom:1px solid var(--line);background:var(--card)}
.ag-scope>summary{cursor:pointer;font-size:11px;font-weight:700;
   text-transform:uppercase;letter-spacing:.03em;color:var(--ink3);
   padding:8px 15px;list-style:none}
.ag-scope>summary::-webkit-details-marker{display:none}
.ag-scope>summary::before{content:"▸ ";color:var(--ink4)}
.ag-scope[open]>summary::before{content:"▾ "}
.ag-scope>summary:hover{color:var(--clara)}
.ag-scope-b{padding:0 15px 12px;font-size:11.5px;color:var(--ink2);
   line-height:1.55}
.ag-scope-b b{color:var(--ink);display:block;margin-bottom:4px}
.ag-scope-b ul{display:flex;flex-wrap:wrap;gap:4px;margin-bottom:7px}
.ag-scope-b li{background:var(--bad-wash);color:var(--bad);font-weight:600;
   border-radius:3px;padding:2px 7px;font-size:10.5px}
.ag-scope-b p{margin:0}
/* 6.2's exclusions as chips, wherever they are listed. */
.ex-list{display:flex;flex-wrap:wrap;gap:4px;margin:5px 0 7px}
.ex-list li{background:var(--card);color:var(--bad);font-weight:700;
   border:1px solid var(--bad);border-radius:3px;padding:2px 7px;
   font-size:10.5px}
@media (max-width:620px){.ag{width:100vw}}

/* ---------------- misc ---------------- */
.thumb{width:44px;height:44px;border-radius:6px;object-fit:cover;
   background:var(--card3);flex:none}
.thumb.lg{width:92px;height:92px}
.row{display:flex;gap:11px;align-items:flex-start}
.bar{height:5px;border-radius:3px;background:var(--card3);overflow:hidden;
   min-width:54px;margin-top:4px}
.bar i{display:block;height:100%;background:var(--clara)}
.bar i.over{background:var(--bad)}
.win{color:var(--ok);font-weight:650}
.lose{color:var(--bad);font-weight:650}
.na{color:var(--ink4);font-style:italic}
.hist li{padding:9px 0;border-bottom:1px solid var(--line);font-size:12.5px}
.hist li:last-child{border-bottom:0}
.hist .when{font-size:11px;color:var(--ink3);font-variant-numeric:tabular-nums}
.hist .what{color:var(--ink);margin-top:2px}
.hist .delta{font-size:11.5px;color:var(--ink2);margin-top:3px;
   font-family:var(--mono);overflow-wrap:anywhere}
.opts{display:flex;flex-direction:column;gap:0}
.opt-row{border-bottom:1px solid var(--line);padding:14px 16px}
.opt-row:last-child{border-bottom:0}
.opt-row h3{font-size:14px;font-family:var(--sans);font-weight:700;
   margin-bottom:3px}
.opt-row .oh{font-size:12px;color:var(--ink3);margin-bottom:11px;line-height:1.55}
.cands{display:flex;flex-direction:column;gap:8px}
.cand{border:1px solid var(--line2);border-radius:7px;padding:11px 13px;
   display:flex;gap:11px;align-items:flex-start;background:var(--bg)}
.cand input{margin-top:3px;flex:none}
.cand .cb{min-width:0;flex:1}
.cand .cn{font-weight:600;font-size:13.5px}
.cand .cu{font-size:11.5px;color:var(--ink3);overflow-wrap:anywhere}
.cand .cw{font-size:12px;color:var(--ink2);margin-top:4px}
@media print{.hd,.ag,.ph-acts,.fbar{display:none}}
"""

# Opening menus and keeping the transcript scrolled. Everything here is an
# enhancement: with scripting off, `agent=1` in the URL still renders the panel
# and every form still posts, so no requirement depends on this running.
JS = """
document.addEventListener('click',function(ev){
  document.querySelectorAll('details.menu[open]').forEach(function(d){
    if(!d.contains(ev.target))d.open=false;});
});
document.addEventListener('keydown',function(ev){
  if(ev.key==='Escape')document.querySelectorAll('details.menu[open]')
    .forEach(function(d){d.open=false;});
});
(function(){var s=document.querySelector('.ag-scroll');
 if(s)s.scrollTop=s.scrollHeight;})();
"""


# --------------------------------------------------------------------------
# components
# --------------------------------------------------------------------------

def pill(label: str, tone: str = "quiet", *, title: str = "") -> str:
    """A status. One implementation, so a status means one thing everywhere."""
    t = f' title="{e(title)}"' if title else ""
    return f'<span class="pl pl-{e(tone)}"{t}>{e(label)}</span>'


CONFIDENCE_TONE = {"HIGH": "ok", "MEDIUM": "amb", "LOW": "bad",
                   "UNVERIFIED": "no"}


def confidence(value: str) -> str:
    """Match confidence, displayed the same way on every view (10)."""
    if not value:
        return ""
    v = str(value).upper()
    return pill(v.title() if v != "UNVERIFIED" else "Unverified",
                CONFIDENCE_TONE.get(v, "quiet"),
                title=f"Match confidence: {v.lower()}")


PROV_SHORT = {"Automatically observed": "Observed",
              "Human-confirmed": "Confirmed",
              "Manually entered": "Manual",
              "Approved feed/API": "Feed"}


def prov(label: str, *, short: bool = False) -> str:
    """A provenance chip carrying 8.2's definition as its tooltip.

    The words come from `ops.provenance_badge` rather than from this module, so
    the definition a reader hovers is the same string the schema documents.
    """
    if not label:
        return ""
    b = provenance_badge(label)
    text = PROV_SHORT.get(b["label"], b["label"]) if short else b["label"]
    return (f'<span class="pv pv-{e(b["key"])}" title="{e(b["definition"])}">'
            f'{e(text)}</span>')


def fresh(state: str, why: str = "", days=None) -> str:
    label = {"fresh": "Fresh", "recent": "Recent", "stale": "Stale",
             "unknown": "Age unknown"}.get(state, state or "unknown")
    if days is not None and state in ("recent", "stale"):
        try:
            label = f"{label} · {round(float(days))}d"
        except (TypeError, ValueError):
            pass
    return (f'<span class="fr fr-{e(state or "unknown")}" title="{e(why)}">'
            f'{e(label)}</span>')


def badges(*items) -> str:
    live = [i for i in items if i]
    return '<div class="badges">' + "".join(live) + "</div>" if live else ""


def stat(value, key: str, detail: str = "", *, tone: str = "",
         href: str = "") -> str:
    """A summary number that says what it counts (10: define every summary count).

    `detail` is not decoration. Section 12 requires summary counts to reconcile
    with their records, and a number whose definition is unwritten cannot be
    reconciled by the person reading it.
    """
    inner = (f'<span class="sv">{e(value)}</span>'
             f'<span class="sk">{e(key)}</span>'
             + (f'<span class="sd">{e(detail)}</span>' if detail else ""))
    cls = "st" + (f" {tone}" if tone else "")
    if href:
        return f'<a class="{cls}" href="{e(href)}">{inner}</a>'
    return f'<div class="{cls}">{inner}</div>'


def stats(items: list) -> str:
    live = [i for i in items if i]
    return '<div class="stats">' + "".join(live) + "</div>" if live else ""


def panel(title: str, body: str, *, note: str = "", acts: str = "",
          flush: bool = False) -> str:
    head = ""
    if title:
        right = acts or (f'<span class="pn">{e(note)}</span>' if note else "")
        head = f'<h2><span>{e(title)}</span>{right}</h2>'
    cls = "panel-b flush" if flush else "panel-b"
    return f'<section class="panel">{head}<div class="{cls}">{body}</div></section>'


def empty(head: str, body: str, acts: str = "") -> str:
    """An empty state that says which half is empty, why, and what to do next."""
    return (f'<div class="empty"><h3>{e(head)}</h3><p>{e(body)}</p>'
            + (f'<div class="ea">{acts}</div>' if acts else "")
            + "</div>")


def kv(rows: list) -> str:
    """A definition list. `rows` is [(term, html)]; empty values are dropped."""
    out = []
    for term, value in rows:
        if value in (None, "", []):
            continue
        out.append(f'<dt>{e(term)}</dt><dd>{value}</dd>')
    return '<dl class="kv">' + "".join(out) + "</dl>" if out else ""


def ff(name: str, label: str, *, kind: str = "text", value: str = "",
       hint: str = "", options: list | None = None, required: bool = False,
       wide: bool = False, error: str = "", placeholder: str = "",
       rows: int = 0) -> str:
    """One labelled form field. Every input in the application is built from this.

    The label is bound with `for`/`id`, and an error is announced with
    `aria-invalid` and stated in text beside the field — section 10's form-label
    and error-message expectations, met in one place so no page has to remember
    them.
    """
    fid = "f_" + name.replace("[", "_").replace("]", "").replace(".", "_")
    req = " required" if required else ""
    inv = ' aria-invalid="true"' if error else ""
    ph = f' placeholder="{e(placeholder)}"' if placeholder else ""
    if kind == "select":
        opts = []
        for spec in (options or []):
            ov, ol = spec[0], spec[1]
            sel = " selected" if str(ov) == str(value) else ""
            opts.append(f'<option value="{e(ov)}"{sel}>{e(ol)}</option>')
        control = (f'<select id="{fid}" name="{e(name)}"{req}{inv}>'
                   + "".join(opts) + "</select>")
    elif kind == "textarea":
        control = (f'<textarea id="{fid}" name="{e(name)}"{req}{inv}{ph}'
                   + (f' rows="{rows}"' if rows else "")
                   + f'>{e(value)}</textarea>')
    else:
        control = (f'<input id="{fid}" name="{e(name)}" type="{e(kind)}" '
                   f'value="{e(value)}"{req}{inv}{ph}>')
    return (f'<div class="ff{" fw" if wide else ""}">'
            f'<label for="{fid}">{e(label)}'
            + ('' if not required else ' <span aria-hidden="true">*</span>')
            + '</label>' + control
            + (f'<span class="hint">{e(hint)}</span>' if hint else "")
            + (f'<span class="err">{e(error)}</span>' if error else "")
            + "</div>")


def filter_bar(path: str, fields: list, query: dict, *,
               keep: tuple = ("agent", "c")) -> str:
    """A GET form at the current path, so a filtered list is a link (10).

    `keep` carries the panel's own state across a filter change: filtering a list
    should not close the Agent or lose the conversation you were having about it.
    """
    hidden = "".join(
        f'<input type="hidden" name="{e(k)}" value="{e(one(query, k))}">'
        for k in keep if one(query, k))
    inner = []
    for spec in fields:
        name, label = spec[0], spec[1]
        opts = spec[2] if len(spec) > 2 else None
        fid = "q_" + name
        cur = one(query, name)
        if opts is None:
            ph = spec[3] if len(spec) > 3 else "Search"
            control = (f'<input id="{fid}" type="search" name="{e(name)}" '
                       f'value="{e(cur)}" placeholder="{e(ph)}">')
            cls = "f grow"
        else:
            o = []
            for ov, ol in opts:
                sel = " selected" if str(ov) == cur else ""
                o.append(f'<option value="{e(ov)}"{sel}>{e(ol)}</option>')
            control = f'<select id="{fid}" name="{e(name)}">' + "".join(o) + "</select>"
            cls = "f"
        inner.append(f'<div class="{cls}"><label for="{fid}">{e(label)}</label>'
                     + control + "</div>")
    return (f'<form class="filters" method="get" action="{e(path)}" role="search">'
            + hidden + "".join(inner)
            + '<div class="f"><label>&nbsp;</label>'
              '<button class="b b-pri" type="submit">Apply</button></div>'
              '<div class="f"><label>&nbsp;</label>'
            + f'<a class="b" href="{e(path)}">Clear</a></div>'
            + "</form>")


def applied(path: str, query: dict, labels: dict) -> str:
    """The filters currently in force, each removable. Empty when none are."""
    chips = []
    for key, label in labels.items():
        val = one(query, key)
        if not val:
            continue
        drop = qs(query, **{key: None, "page": None})
        chips.append(f'<a href="{e(path)}{e(drop)}" '
                     f'title="Remove this filter">{e(label)}: {e(val)} &times;</a>')
    if not chips:
        return ""
    return ('<div class="applied"><span>Filtered by</span>' + "".join(chips)
            + "</div>")


def pager(path: str, query: dict, total: int, limit: int, offset: int,
          noun: str = "records") -> str:
    """Page controls, and the count they page through.

    Always states the total, because section 12 requires a summary count to
    reconcile with the records behind it and this is the count a reader checks
    it against.
    """
    if total <= limit and offset == 0:
        return (f'<div class="pager"><span>{total} {e(noun)}</span></div>'
                if total else "")
    lo = offset + 1 if total else 0
    hi = min(offset + limit, total)
    page_no = offset // limit + 1
    pages = max(1, (total + limit - 1) // limit)
    nav = []
    if offset > 0:
        prev = page_no - 1
        nav.append(f'<a class="b b-sm" href="{e(path)}'
                   f'{e(qs(query, page=prev if prev > 1 else None))}">'
                   f'&larr; Previous</a>')
    if hi < total:
        nav.append(f'<a class="b b-sm" href="{e(path)}'
                   f'{e(qs(query, page=page_no + 1))}">Next &rarr;</a>')
    return (f'<div class="pager"><span>{lo}&ndash;{hi} of {total} {e(noun)}'
            f' &middot; page {page_no} of {pages}</span>'
            f'<span class="pnav">{"".join(nav)}</span></div>')


def send_request_btn(kind: str = "", record_id: str = "", *,
                     label: str = "Send Request", small: bool = False,
                     primary: bool = False) -> str:
    """5.2: a global header action, and a contextual action on every record.

    The contextual link carries the record, which is what makes "opening Send
    Request from a supported record must prefill that context" true without the
    reader retyping anything.
    """
    href = "/requests/new"
    if kind and record_id:
        href += (f"?kind={urllib.parse.quote(str(kind))}"
                 f"&id={urllib.parse.quote(str(record_id))}")
    cls = "b" + (" b-sm" if small else "") + (" b-pri" if primary else "")
    return f'<a class="{cls}" href="{e(href)}">{e(label)}</a>'


def agent_btn(kind: str = "", record_id: str = "", *, label: str = "Ask the Agent",
              small: bool = True) -> str:
    """Open the panel with this record as its context (3.1, 6.3)."""
    href = f"?agent=1&ctx={urllib.parse.quote(str(kind))}"
    if record_id:
        href += f"&ctxid={urllib.parse.quote(str(record_id))}"
    cls = "b" + (" b-sm" if small else "")
    return f'<a class="{cls}" href="{e(href)}">{e(label)}</a>'


def crumbs(items: list) -> str:
    out = []
    for label, href in items:
        out.append(f'<a href="{e(href)}">{e(label)}</a>' if href else e(label))
    return '<nav class="crumbs">' + ' / '.join(out) + "</nav>"


def page_head(title: str, lede: str = "", *, acts: str = "",
              trail: list | None = None) -> str:
    """A page title and its page-level actions, in the same place every time."""
    P = []
    if trail:
        P.append(crumbs(trail))
    P.append('<div class="ph"><h1>' + e(title) + "</h1>"
             + (f'<div class="ph-acts">{acts}</div>' if acts else "")
             + "</div>")
    if lede:
        P.append(f'<p class="lede">{e(lede)}</p>')
    return "".join(P)


def money(amount, currency: str = "") -> str:
    """A price, or an honest blank. Never a zero standing in for a missing value."""
    if amount in (None, ""):
        return '<span class="na">not recorded</span>'
    try:
        d = float(str(amount).replace(",", ""))
        txt = f"{d:,.0f}" if abs(d - round(d)) < 0.005 else f"{d:,.2f}"
    except (TypeError, ValueError):
        txt = str(amount)
    return e(f"{txt} {currency}".strip())


def when(iso: str, *, date_only: bool = False) -> str:
    if not iso:
        return '<span class="na">never</span>'
    s = str(iso).replace("T", " ")
    return e(s[:10] if date_only else s[:16])


# --------------------------------------------------------------------------
# the page
# --------------------------------------------------------------------------

def page(title: str, body: str, *, user: dict, active: str = "",
         counts: dict | None = None, agent_panel: str = "",
         agent_href: str = "?agent=1", flash: tuple | None = None) -> str:
    """The whole document. Every page in the application comes through here."""
    counts = counts or {}
    P = ['<!doctype html><html lang="en"><head><meta charset="utf-8">',
         '<meta name="viewport" content="width=device-width, initial-scale=1">',
         '<meta name="robots" content="noindex, nofollow">',
         f'<title>{e(title)} — Clara Competitor Intelligence</title>',
         f'<style>{CSS}</style></head><body>',
         '<a class="skip" href="#main">Skip to content</a>']

    # ---- header: brand, global actions, the Agent control, Admin ----
    P.append('<header class="hd"><div class="hd-top">')
    P.append('<a class="brand" href="/overview">Clara <span>Intelligence</span></a>')
    P.append('<div class="hd-sp">')
    P.append(send_request_btn(label="Send Request"))
    on = " on" if agent_panel else ""
    P.append(f'<a class="b ag-btn{on}" href="{e(agent_href)}" '
             f'aria-expanded="{"true" if agent_panel else "false"}">'
             'Intelligence Agent</a>')
    if user.get("is_admin"):
        P.append('<details class="menu"><summary class="b">Admin</summary>'
                 '<div class="menu-body">')
        for href, label, note in ADMIN_LINKS:
            P.append(f'<a href="{e(href)}">{e(label)}<small>{e(note)}</small></a>')
        P.append('</div></details>')
    who = user.get("display_name") or user.get("username") or "signed in"
    P.append(f'<span class="hd-who"><b>{e(who)}</b>'
             + (' · admin' if user.get("is_admin") else ' · user') + '</span>')
    P.append('<form method="post" action="/logout">'
             '<button class="b b-sm" type="submit">Sign out</button></form>')
    P.append('</div></div>')

    # ---- the five tabs of section 3 ----
    P.append('<nav class="tabs" aria-label="Main">')
    for key, href, label, _why in TABS:
        cur = ' aria-current="page"' if key == active else ""
        n = counts.get(key)
        chip = ""
        if n:
            hot = " hot" if key == "actions" else ""
            chip = f'<span class="n{hot}">{e(n)}</span>'
        P.append(f'<a href="{e(href)}"{cur}>{e(label)}{chip}</a>')
    P.append('</nav></header>')

    flash_html = ""
    if flash:
        tone, message = flash
        flash_html = (f'<div class="flash {e(tone)}" role="status">'
                      f'{e(message)}</div>')

    P.append(f'<main id="main" tabindex="-1">{flash_html}{body}</main>')
    if agent_panel:
        P.append(agent_panel)
    P.append(f'<script>{JS}</script></body></html>')
    return "".join(P)
