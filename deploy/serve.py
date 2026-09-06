#!/usr/bin/env python
"""Serves the Clara report as a local website, behind a sign-in.

    python serve.py                  # http://127.0.0.1:8770
    python serve.py --port 9000

Routes
    /login          the sign-in page
    /               the report (requires a session)
    /trends         Beauty Trends Intelligence
    /decisions      Decisions to make
    /admin          user management (admins only)
    /refresh        re-read the store and re-render
    /rerun          a fresh monitoring run against competitor sites (slow)
    /prices.csv     CSV export
    /prices.jsonl   JSONL export

The first run creates an admin account with a random password printed once to the
console. Binds to 127.0.0.1 only: sessions ride a cookie with no TLS in front, so
this must not be exposed on a public interface without HTTPS ahead of it.
"""

from __future__ import annotations

import argparse
import io
import json
import sys
import threading
import time
import urllib.parse
from http import cookies
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

from clara_monitor import (
    catalog, competitors as comp, decisions_page,
    pages, reporting,
    site, trend_page, trend_store,
)
from clara_monitor.auth import Auth, ROLE_ADMIN, ROLE_VIEWER
from clara_monitor.config import DB_PATH, REPORT_DIR, RunConfig
from clara_monitor.store import Store

COOKIE = "clara_session"

STATE = {
    "run_id": "r1",
    "rendered_at": None,
    "render_ms": None,
    "rerun_active": False,
    "rerun_started_at": None,
    "rerun_finished_at": None,
    "rerun_summary": None,
    "rerun_error": None,
}
_lock = threading.Lock()
_auth: Auth | None = None

def build_bundle(run_id: str) -> dict:
    store = Store(DB_PATH)
    try:
        # keep the registry in the store in step with the code
        for c in comp.REGISTRY.values():
            store.upsert_competitor(c)
        bundle = reporting.build_all(store, run_id, write=True)
        bundle["competitors"] = reporting.competitor_cards(store, run_id)
        bundle["offers"] = reporting.offers_report(store, run_id)
        bundle["actions"] = reporting.actions_report(store, run_id)
    finally:
        store.close()
    # The intelligence cycle rides on the same page rather than having its own,
    # and the trend scan comes with it — "what to do next" is the join between
    # the two, and neither half is worth much alone.
    bundle["intel"] = latest_intel()
    bundle["trends"] = build_trends()
    bundle["sweep"] = build_sweep()
    return bundle


def build_sweep() -> dict:
    """The last storefront offer sweep. Reads only; sweeping is run_offers.py."""
    from clara_monitor.agents.offer_store import OfferStore

    st = OfferStore(DB_PATH)
    try:
        return st.build()
    finally:
        st.close()


def latest_intel() -> dict:
    """The most recent completed cycle, or a fresh one if none exists.

    A cycle reads stored evidence and compares it with the previous state; it
    contacts nothing and takes well under a second, so building one on demand is
    honest. Collecting new evidence remains a separate, slow, local job.
    """
    import json as _json

    from clara_monitor.agents.orchestrator import Orchestrator
    from clara_monitor.agents.store import IntelStore
    from clara_monitor.llm import judge_singleton

    st = IntelStore(DB_PATH)
    try:
        done = [c for c in st.cycles() if c.get("finished_at")]
    finally:
        st.close()

    if done:
        path = REPORT_DIR / f"intel_{done[0]['cycle_id']}.json"
        if path.exists():
            with open(path, encoding="utf-8") as f:
                return _json.load(f)

    store2 = Store(DB_PATH)
    try:
        orch = Orchestrator(store2, DB_PATH, llm=judge_singleton(), verbose=False)
        try:
            cid = f"c{orch.intel.snapshot_count() + 1}"
            out = orch.run(cid, STATE["run_id"], catalog.load_from_seed())
            REPORT_DIR.mkdir(parents=True, exist_ok=True)
            with open(REPORT_DIR / f"intel_{cid}.json", "w", encoding="utf-8") as f:
                _json.dump(out, f, ensure_ascii=False, indent=2, default=str)
            return out
        finally:
            orch.close()
    finally:
        store2.close()


def build_trends() -> dict:
    """Render whatever the last scan collected. Reading never fetches.

    A page load must not silently hit two dozen publishers, so this only reads
    the store. Collecting is an explicit act: the Scan now button, or
    `python run_trends.py`.
    """
    st = trend_store.TrendStore(DB_PATH)
    try:
        return trend_store.build(st)
    finally:
        st.close()


def scan_trends() -> dict:
    """Fetch every registered feed and fold the result into the store."""
    from clara_monitor.agents.trend_collector import TrendCollectionAgent

    st = trend_store.TrendStore(DB_PATH)
    try:
        scan_id = f"s{st.scan_count() + 1}"
        result = TrendCollectionAgent().run(st, scan_id)
        return st.record(result)
    finally:
        st.close()


def build_intel(cycle: str | None = None) -> dict:
    """Read a stored cycle, or run one if none exists yet.

    Rendering never triggers a monitoring run — a cycle reads evidence the
    monitor already collected and takes well under a second, so serving it live
    is honest. Collecting *new* evidence is still a separate, slow, local job.
    """
    import json

    from clara_monitor.agents.orchestrator import Orchestrator
    from clara_monitor.llm import judge_singleton

    store = Store(DB_PATH)
    try:
        orch = Orchestrator(store, DB_PATH, llm=judge_singleton(), verbose=False)
        try:
            # A named cycle is a request to READ that cycle, not to recompute
            # it. Recomputing would overwrite the very history the picker exists
            # to show, and would date-stamp an old cycle as if it were new.
            cycles = [c for c in orch.intel.cycles() if c.get("finished_at")]
            wanted = cycle or (cycles[0]["cycle_id"] if cycles else None)
            if wanted:
                path = REPORT_DIR / f"intel_{wanted}.json"
                if path.exists():
                    with open(path, encoding="utf-8") as f:
                        return json.load(f)
            target = f"c{orch.intel.snapshot_count() + 1}"
            out = orch.run(target, STATE["run_id"], catalog.load_from_seed())
            REPORT_DIR.mkdir(parents=True, exist_ok=True)
            with open(REPORT_DIR / f"intel_{target}.json", "w",
                      encoding="utf-8") as f:
                json.dump(out, f, ensure_ascii=False, indent=2, default=str)
            return out
        finally:
            orch.close()
    finally:
        store.close()


def render_product(user: dict, product_id: str) -> bytes:
    """One product page, in the same design layer and under the same livebar."""
    from clara_monitor import product_data, product_page

    bundle = build_bundle(STATE["run_id"])
    view = product_data.build(bundle, product_id)
    html_out = product_page.render(view)
    html_out = html_out.replace("</style>", BAR_CSS + "</style>", 1)
    html_out = html_out.replace('<header class="top">',
                                _bar(user, STATE["run_id"], page="prices")
                                + '<header class="top">', 1)
    return (html_out + f"<script>{BAR_JS}</script>").encode("utf-8")


def render_decisions(user: dict) -> bytes:
    # The decisions page reads both halves — the price comparison and the
    # trends — because a decision that cannot be traced to the comparison and
    # the trend that produced it is an assertion.
    bundle = build_bundle(STATE["run_id"])
    html_out = decisions_page.render(bundle, bundle.get("trends"))
    html_out = html_out.replace("</style>", BAR_CSS + "</style>", 1)
    html_out = html_out.replace('<header class="top">',
                                _bar(user, STATE["run_id"], page="decisions")
                                + '<header class="top">', 1)
    return (html_out + f"<script>{BAR_JS}</script>").encode("utf-8")


def render_trends(user: dict) -> bytes:
    # The trends page needs the decisions to say which subjects are already
    # carrying one, and decisions are derived from both halves. So the full
    # bundle is built, and the trends half of it is what the page renders.
    from clara_monitor import intel_sections as _isec

    bundle = build_bundle(STATE["run_id"])
    trends = bundle.get("trends") or {}
    html_out = trend_page.render(trends, _isec.decision_items(bundle, trends))
    html_out = html_out.replace("</style>", BAR_CSS + "</style>", 1)
    html_out = html_out.replace('<header class="top">',
                                _bar(user, STATE["run_id"], page="trends")
                                + '<header class="top">', 1)
    return (html_out + f"<script>{BAR_JS}</script>").encode("utf-8")


BAR_CSS = """
.livebar{position:sticky;top:0;z-index:45;background:var(--card2);
  border-bottom:1px solid var(--line2);padding:8px 0;font-size:12.5px;color:var(--ink2)}
.livebar .wrap{display:flex;gap:11px;align-items:center;flex-wrap:wrap}
.livebar b{color:var(--ink)}
.livebar form{display:inline}
.livebar button,.livebar a.lb{font-family:inherit;font-size:12.5px;padding:5px 11px;
  cursor:pointer;background:var(--card);color:var(--ink);border:1px solid var(--line2);
  border-radius:5px;text-decoration:none;font-weight:600}
.livebar button:hover,.livebar a.lb:hover{border-color:var(--clara);color:var(--clara)}
.livebar a.lb.on{background:var(--clara);color:#fff;border-color:var(--clara)}
.livebar .dot{width:8px;height:8px;border-radius:50%;background:var(--ok);
  display:inline-block}
.livebar .dot.busy{background:var(--amb)}
.livebar .sp{margin-inline-start:auto;display:flex;gap:7px;align-items:center}
nav.jump{top:39px}
"""

BAR_JS = """
(function(){
  var auto=document.getElementById('auto'), lbl=document.getElementById('autolbl');
  var timer=null;
  function poll(reloadIfIdle){
    fetch('status.json',{credentials:'same-origin'}).then(function(r){return r.json();})
      .then(function(s){
        var d=document.querySelector('.livebar .dot');
        if(s.rerun_active){ d.classList.add('busy'); lbl.textContent='run in progress…'; }
        else {
          d.classList.remove('busy');
          if(reloadIfIdle && auto.checked){ location.reload(); return; }
          if(!auto.checked) lbl.textContent='auto-refresh off';
          else lbl.textContent='auto-refresh every 60s';
        }
      }).catch(function(){});
  }
  function set(){
    if(timer){clearInterval(timer); timer=null;}
    if(auto.checked){ lbl.textContent='auto-refresh every 60s';
      timer=setInterval(function(){poll(true);},60000); }
    else lbl.textContent='auto-refresh off';
    try{ localStorage.setItem('clara-auto', auto.checked?'1':'0'); }catch(e){}
  }
  try{ auto.checked = localStorage.getItem('clara-auto')==='1'; }catch(e){}
  auto.addEventListener('change', set); set();
  setInterval(function(){poll(false);}, 8000);
})();
"""


def _bar(user: dict, run_id: str, page: str = "prices") -> str:
    with _lock:
        rendered = STATE.get("rendered_at") or "just now"
        busy = STATE.get("rerun_active")
    P = ['<div class="livebar"><div class="wrap">']
    P.append(f'<span class="dot{" busy" if busy else ""}"></span>')
    # The three pages are peers, so each is always one click from the others.
    for href, label, key in (("/", "Competitors", "prices"),
                             ("/trends", "Trends", "trends"),
                             ("/decisions", "Decisions", "decisions")):
        P.append('<a class="lb%s" href="%s">%s</a>'
                 % (' on' if page == key else '', href, label))
    if page == "trends":
        P.append('<span>Live feeds</span>')
    elif page == "decisions":
        P.append('<span>Competitor moves and market trends</span>')
    else:
        P.append(f'<span>Run <b>{run_id}</b></span>')
        P.append(f'<span>Updated <b>{rendered}</b></span>')
        P.append('<form method="post" action="/refresh"><button type="submit" '
                 'title="Re-reads the store and rebuilds the page. Contacts no '
                 'competitor site.">Refresh from store</button></form>')
        P.append('<form method="post" action="/rerun"><button type="submit" '
                 'title="A fresh monitoring run against competitor sites. Takes a '
                 'long time.">Re-run monitoring</button></form>')
    P.append('<label><input type="checkbox" id="auto"> '
             '<span id="autolbl">auto-refresh off</span></label>')
    P.append('<span class="sp">')
    if page == "trends":
        P.append('<a class="lb" href="/trends.json">JSON</a>')
        P.append('<form method="post" action="/scan"><button type="submit" '
                 'title="Fetch every registered feed now. Public feeds only, '
                 'about a minute.">Scan now</button></form>')
    elif page == "decisions":
        P.append('<a class="lb" href="/decisions.json">JSON</a>')
    else:
        P.append('<a class="lb" href="/prices.csv">CSV</a>')
    if user.get("is_admin"):
        P.append('<a class="lb" href="/admin">Users</a>')
    P.append(f'<span>{user["display_name"]}</span>')
    P.append('<form method="post" action="/logout">'
             '<button type="submit">Sign out</button></form>')
    P.append('</span></div></div>')
    return chr(10).join(P)


def render_report(user: dict, run_id: str) -> bytes:
    t0 = time.time()
    bundle = build_bundle(run_id)
    html = site.render(bundle)
    with _lock:
        STATE["run_id"] = run_id
        STATE["rendered_at"] = time.strftime("%Y-%m-%d %H:%M")
        STATE["render_ms"] = int((time.time() - t0) * 1000)
    html = html.replace("</style>", BAR_CSS + "</style>", 1)
    html = html.replace('<header class="top">', _bar(user, run_id)
                        + '<header class="top">', 1)
    return (html + f"<script>{BAR_JS}</script>").encode("utf-8")


def _flash(q: dict):
    """A message carried across a redirect, in the same shape the pages use."""
    msg = (q.get("m") or [""])[0]
    err = (q.get("e") or [""])[0]
    if err:
        return ("err", err)
    return ("ok", msg) if msg else None


def _rerun(run_id: str, targets: int, budget: int) -> None:
    from clara_monitor import engine
    with _lock:
        STATE.update(rerun_active=True, rerun_error=None, rerun_summary=None,
                     rerun_started_at=time.strftime("%Y-%m-%d %H:%M"),
                     rerun_finished_at=None)
    try:
        cfg = RunConfig(run_id=run_id, discovery_budget=budget)
        products = catalog.load_from_seed()
        res = engine.run(cfg, products, targets_limit=targets, use_llm=True,
                         resume=True)
        with _lock:
            STATE["rerun_summary"] = res["summary"]
    except Exception as e:
        with _lock:
            STATE["rerun_error"] = f"{type(e).__name__}: {e}"
    finally:
        with _lock:
            STATE.update(rerun_active=False,
                         rerun_finished_at=time.strftime("%Y-%m-%d %H:%M"))


# --------------------------------------------------------------------------
# handler
# --------------------------------------------------------------------------

class Handler(BaseHTTPRequestHandler):
    server_version = "ClaraReport/2.0"
    run_id = "r1"
    targets = 2
    budget = 3

    # ---------- plumbing ----------

    # Set from the command line in main().
    run_id = "r1"
    targets = 2
    budget = 3
    with_trends = False

    def log_message(self, fmt, *args):
        sys.stdout.write("  %s %s\n" % (self.address_string(), fmt % args))
        sys.stdout.flush()

    def _send(self, body: bytes, ctype: str, code: int = 200,
              set_cookie: str | None = None, clear_cookie: bool = False):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Frame-Options", "DENY")
        if set_cookie:
            self.send_header("Set-Cookie",
                             f"{COOKIE}={set_cookie}; HttpOnly; SameSite=Lax; Path=/")
        if clear_cookie:
            self.send_header("Set-Cookie",
                             f"{COOKIE}=; HttpOnly; SameSite=Lax; Path=/; Max-Age=0")
        self.end_headers()
        self.wfile.write(body)

    def _html(self, markup: str, code: int = 200, **kw):
        self._send(markup.encode("utf-8"), "text/html; charset=utf-8", code, **kw)

    def _redirect(self, to: str = "/", **kw):
        self.send_response(303)
        self.send_header("Location", to)
        self.send_header("Content-Length", "0")
        if kw.get("set_cookie"):
            self.send_header("Set-Cookie",
                             f"{COOKIE}={kw['set_cookie']}; HttpOnly; SameSite=Lax; Path=/")
        if kw.get("clear_cookie"):
            self.send_header("Set-Cookie",
                             f"{COOKIE}=; HttpOnly; SameSite=Lax; Path=/; Max-Age=0")
        self.end_headers()

    def _token(self) -> str | None:
        raw = self.headers.get("Cookie")
        if not raw:
            return None
        c = cookies.SimpleCookie()
        try:
            c.load(raw)
        except cookies.CookieError:
            return None
        m = c.get(COOKIE)
        return m.value if m else None

    def _user(self) -> dict | None:
        return _auth.session_user(self._token()) if _auth else None

    def _form(self) -> dict:
        try:
            n = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            n = 0
        if n <= 0 or n > 100_000:
            return {}
        raw = self.rfile.read(n).decode("utf-8", "replace")
        return {k: v[0] for k, v in urllib.parse.parse_qs(raw).items()}

    def _file(self, name: str, ctype: str):
        path = REPORT_DIR / name
        if not path.exists():
            self._send(b"not generated yet", "text/plain; charset=utf-8", 404)
            return
        self._send(path.read_bytes(), ctype)

    # ---------- GET ----------

    def do_GET(self):
        parts = urllib.parse.urlsplit(self.path)
        route = parts.path.rstrip("/") or "/"
        q = urllib.parse.parse_qs(parts.query)
        user = self._user()

        if route == "/login":
            if user:
                return self._redirect("/")
            return self._html(pages.login_page(
                error=(q.get("e") or [""])[0], notice=(q.get("m") or [""])[0],
                next_url=(q.get("next") or ["/"])[0]))

        if not user:
            nxt = urllib.parse.quote(route, safe="/")
            return self._redirect(f"/login?next={nxt}")

        if route == "/":
            try:
                return self._send(render_report(user, self.run_id),
                                  "text/html; charset=utf-8")
            except Exception as ex:
                return self._send(
                    f"could not build the report: {type(ex).__name__}: {ex}".encode(),
                    "text/plain; charset=utf-8", 500)
        if route == "/product":
            try:
                return self._send(
                    render_product(user, (q.get("id") or [""])[0]),
                    "text/html; charset=utf-8")
            except Exception as ex:
                return self._send(
                    f"could not build the product page: "
                    f"{type(ex).__name__}: {ex}".encode(),
                    "text/plain; charset=utf-8", 500)
        if route == "/trends":
            try:
                return self._send(render_trends(user), "text/html; charset=utf-8")
            except Exception as ex:
                return self._send(
                    f"could not build the trends page: {type(ex).__name__}: {ex}"
                    .encode(), "text/plain; charset=utf-8", 500)
        if route == "/decisions":
            try:
                return self._send(render_decisions(user),
                                  "text/html; charset=utf-8")
            except Exception as ex:
                return self._send(
                    f"could not build the decisions page: "
                    f"{type(ex).__name__}: {ex}".encode(),
                    "text/plain; charset=utf-8", 500)
        if route == "/decisions.json":
            from clara_monitor import intel_sections as _isec
            b = build_bundle(STATE["run_id"])
            return self._send(
                json.dumps({"generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                            "decisions": _isec.decision_items(
                                b, b.get("trends"))},
                           ensure_ascii=False, default=str).encode(),
                "application/json; charset=utf-8")
        if route == "/trends.json":
            b = build_trends()
            return self._send(json.dumps(b, ensure_ascii=False).encode(),
                              "application/json; charset=utf-8")
        if route == "/admin":
            if not user["is_admin"]:
                return self._html("<p>This page is for admins only.</p>", 403)
            pw = None
            if q.get("pw") and q.get("who"):
                pw = (q["who"][0], q["pw"][0])
            return self._html(pages.admin_page(
                user, _auth.list_users(),
                error=(q.get("e") or [""])[0], notice=(q.get("m") or [""])[0],
                new_password=pw))
        if route == "/status.json":
            with _lock:
                return self._send(json.dumps(STATE, default=str).encode(),
                                  "application/json; charset=utf-8")
        if route == "/prices.csv":
            return self._file(f"prices_{self.run_id}.csv", "text/csv; charset=utf-8")
        if route == "/prices.jsonl":
            return self._file(f"prices_{self.run_id}.jsonl",
                              "application/x-ndjson; charset=utf-8")
        if route in ("/scan", "/cycle", "/intel"):
            return self._redirect("/trends" if route == "/scan" else "/")
        if route in ("/refresh", "/rerun", "/logout"):
            return self._redirect("/")
        return self._send(b"not found", "text/plain; charset=utf-8", 404)

    # ---------- POST ----------

    def do_POST(self):
        route = urllib.parse.urlsplit(self.path).path.rstrip("/") or "/"
        form = self._form()

        if route == "/login":
            token = _auth.login(form.get("username", ""), form.get("password", ""),
                                self.headers.get("User-Agent", ""))
            if not token:
                return self._redirect(
                    "/login?e=" + urllib.parse.quote(
                        "Wrong username or password, or the account is "
                        "disabled."))
            nxt = form.get("next") or "/"
            if not nxt.startswith("/"):
                nxt = "/"
            return self._redirect(nxt, set_cookie=token)

        user = self._user()
        if not user:
            return self._redirect("/login")

        if route == "/logout":
            _auth.logout(self._token())
            return self._redirect("/login?m=" + urllib.parse.quote("Signed out."),
                                  clear_cookie=True)
        if route == "/scan":
            # Public feeds only, and roughly a minute. Unlike a competitor
            # monitoring run this is safe to trigger from a click.
            try:
                scan_trends()
            except Exception as ex:
                sys.stdout.write(f"  scan failed: {type(ex).__name__}: {ex}\n")
            return self._redirect("/trends")
        if route == "/refresh":
            return self._redirect("/")
        if route == "/rerun":
            with _lock:
                busy = STATE["rerun_active"]
            if not busy:
                threading.Thread(target=_rerun,
                                 args=(self.run_id, self.targets, self.budget),
                                 daemon=True).start()
            return self._redirect("/")

        if route.startswith("/admin"):
            if not user["is_admin"]:
                return self._html("<p>This page is for admins only.</p>", 403)
            import secrets
            target = (form.get("username") or "").strip().lower()
            try:
                if route == "/admin/add":
                    pw = form.get("password") or ""
                    generated = not pw
                    if generated:
                        pw = secrets.token_urlsafe(9)
                    _auth.create_user(
                        target, pw,
                        role=(ROLE_ADMIN if form.get("role") == "admin"
                              else ROLE_VIEWER),
                        display_name=form.get("display_name", ""),
                        created_by=user["username"])
                    if generated:
                        return self._redirect(
                            "/admin?who=" + urllib.parse.quote(target)
                            + "&pw=" + urllib.parse.quote(pw))
                    return self._redirect("/admin?m=" + urllib.parse.quote(
                        f"Added {target}."))
                if route == "/admin/disable":
                    _auth.set_active(target, False, user["username"])
                    msg = f"Disabled {target}."
                elif route == "/admin/enable":
                    _auth.set_active(target, True, user["username"])
                    msg = f"Enabled {target}."
                elif route == "/admin/role":
                    _auth.set_role(target, form.get("role", ROLE_VIEWER),
                                   user["username"])
                    msg = f"Updated the role for {target}."
                elif route == "/admin/delete":
                    _auth.delete_user(target, user["username"])
                    msg = f"Deleted {target}."
                elif route == "/admin/reset":
                    pw = secrets.token_urlsafe(9)
                    _auth.reset_password(target, pw)
                    return self._redirect("/admin?who="
                                          + urllib.parse.quote(target)
                                          + "&pw=" + urllib.parse.quote(pw))
                else:
                    return self._redirect("/admin")
                return self._redirect("/admin?m=" + urllib.parse.quote(msg))
            except ValueError as ex:
                return self._redirect("/admin?e=" + urllib.parse.quote(str(ex)))

        return self._send(b"not found", "text/plain; charset=utf-8", 404)


def main() -> int:
    global _auth
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-id", default="r1")
    ap.add_argument("--port", type=int, default=8770)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--targets", type=int, default=2)
    ap.add_argument("--discovery-budget", type=int, default=3)
    args = ap.parse_args()

    Handler.run_id = args.run_id
    Handler.targets = args.targets
    Handler.budget = args.discovery_budget
    STATE["run_id"] = args.run_id

    _auth = Auth(DB_PATH)
    _auth.purge_expired()
    created = _auth.ensure_admin()

    # fail loudly now rather than on the first request
    build_bundle(args.run_id)

    print(f"Clara report:  http://{args.host}:{args.port}/")
    if created:
        u, p = created
        print("")
        print("  +- first admin account --------------------------")
        print(f"  |  username:  {u}")
        print(f"  |  password:  {p}")
        print("  |  Shown once only and never stored in readable form.")
        print("  |  Change it after signing in, then add the rest of the")
        print("  |  team from the Users page.")
        print("  +-----------------------------------------------")
        print("")
    else:
        print(f"  users: {_auth.user_count()} "
              f"({_auth.admin_count()} admin)")
    print(f"  run: {args.run_id}")
    print("  Ctrl+C to stop.")

    srv = ThreadingHTTPServer((args.host, args.port), Handler)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
    finally:
        srv.server_close()
        if _auth:
            _auth.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
