"""Vercel serverless entrypoint for the Clara intelligence application.

Serves the same five tabs as the local server, through the same
`clara_monitor.app.router`. That sharing is the point: two route tables would
mean the hosted site is a different application from the tested one, and the
hosted one is the one the team actually uses.

Five platform facts shape this file, and each is handled rather than hidden.

1. OPERATIONAL WRITES GO TO POSTGRES, not to this filesystem. Section 9 is
   explicit — operational data must survive restarts, instance recycling and
   redeployment, and deploy-time snapshots and instance-local files must not be
   the system of record. `DATABASE_URL` is therefore the load-bearing piece of
   configuration here: with it set, every resolution, request, conversation and
   audit event goes to managed Postgres and outlives the deployment. Without it
   the application still renders, and says on the System page and in a banner
   that storage is not durable — because a silent fallback to /tmp is exactly the
   bug section 2 lists as no longer appropriate.

2. THE BUNDLED SQLITE FILE IS COLLECTION EVIDENCE ONLY. It carries the catalogue,
   the scan results and the password hashes, and it is read-only, so it is copied
   to /tmp on cold start to be opened. Nothing a person does in the application
   is written to it.

3. INSTANCES ARE EPHEMERAL AND INDEPENDENT, so sessions are stateless: a signed
   cookie carrying a username and an expiry, verified with HMAC against a secret
   identical on every instance. Passwords are still checked against the scrypt
   hashes in the bundled store.

   The same reasoning still applies to *accounts*: they live in the bundled
   SQLite file, so adding or disabling one here would write to a /tmp copy no
   other instance can see. The Users page is shown read-only with the reason
   stated, rather than offering buttons that discard the change. Everything
   else — actions, requests, the agent, audit — is fully writable, because it
   goes to Postgres.

4. REQUESTS ARE SHORT-LIVED. A collection run contacts competitor sites for about
   an hour and is bound by the access policy, so it cannot happen inside a
   serverless request. Collection stays a local job; the run is imported into
   Postgres afterwards (`python ops_import.py`), which is what makes a redeploy
   stop resetting the operational records.

5. WHAT IS SERVED IS LIVE OPERATIONAL DATA over a SNAPSHOT OF COLLECTION. The
   prices came from the last imported scan; the resolutions, requests and audit
   trail are current. The System page states both, separately, because conflating
   them is how "the data is old" and "your work was lost" get mistaken for each
   other.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import shutil
import sys
import time
import urllib.parse
from http import cookies
from http.server import BaseHTTPRequestHandler
from pathlib import Path

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

BUNDLED_DB = os.path.join(ROOT, "data", "monitor.sqlite3")
TMP_DIR = "/tmp/clara"
TMP_DB = os.path.join(TMP_DIR, "monitor.sqlite3")
# Records which bundle TMP_DB was copied from; see `_writable_db`.
TMP_MARK = os.path.join(TMP_DIR, "bundle.id")

COOKIE = "clara_session"
SESSION_HOURS = 12

_cache: dict = {}


def _writable_db() -> Path:
    """Copy the read-only bundled snapshot somewhere SQLite can open it.

    Re-copied when the bundle it came from has changed. A warm instance holding
    a copy from before a redeploy would keep serving the previous scan while the
    deployment log says the new one shipped — the most confusing kind of stale,
    because everything looks like it worked.
    """
    os.makedirs(TMP_DIR, exist_ok=True)
    # Which bundle the copy came from, recorded beside it. Comparing the copy's
    # own mtime would be wrong twice over: `copyfile` stamps it with the current
    # time so it always looks newer, and *anything* that writes to the copy
    # would then look like a new bundle and trigger a re-copy that destroyed
    # those writes. The marker describes the source, so only a genuinely new
    # bundle replaces the copy.
    want = f"{os.path.getmtime(BUNDLED_DB)}:{os.path.getsize(BUNDLED_DB)}"
    have = ""
    if os.path.exists(TMP_MARK):
        try:
            with open(TMP_MARK, encoding="utf-8") as f:
                have = f.read().strip()
        except OSError:
            have = ""
    if not os.path.exists(TMP_DB) or have != want:
        shutil.copyfile(BUNDLED_DB, TMP_DB)
        # A write-ahead log left beside the new copy would be read in
        # preference to it.
        for suffix in ("-wal", "-shm"):
            leftover = TMP_DB + suffix
            if os.path.exists(leftover):
                os.remove(leftover)
        with open(TMP_MARK, "w", encoding="utf-8") as f:
            f.write(want)
        _cache.clear()
    return Path(TMP_DB)


# --------------------------------------------------------------------------
# stateless sessions
# --------------------------------------------------------------------------

def _secret() -> bytes:
    """The HMAC key, which must be the same byte string on every instance.

    `CLARA_SESSION_SECRET` wins if it is set. Otherwise it is derived from the
    password material already in the bundled store: identical on every instance
    because they all unpack the same bundle, and it rotates on its own when a
    password changes — which correctly invalidates outstanding cookies.
    """
    if _cache.get("secret"):
        return _cache["secret"]
    env = os.environ.get("CLARA_SESSION_SECRET")
    if env:
        key = hashlib.sha256(env.encode("utf-8")).digest()
    else:
        import sqlite3
        con = sqlite3.connect(str(_writable_db()))
        try:
            rows = con.execute(
                "SELECT username, pw_salt, pw_hash FROM app_user ORDER BY username"
            ).fetchall()
        finally:
            con.close()
        h = hashlib.sha256(b"clara-session-v1")
        for u, salt, digest in rows:
            h.update(u.encode("utf-8"))
            h.update(bytes(salt))
            h.update(bytes(digest))
        key = h.digest()
    _cache["secret"] = key
    return key


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _unb64(txt: str) -> bytes:
    return base64.urlsafe_b64decode(txt + "=" * (-len(txt) % 4))


def _issue(username: str) -> str:
    exp = int(time.time()) + SESSION_HOURS * 3600
    body = _b64(json.dumps({"u": username, "exp": exp}).encode())
    sig = _b64(hmac.new(_secret(), body.encode(), hashlib.sha256).digest())
    return f"{body}.{sig}"


def _verify(token: str | None) -> dict | None:
    """Return the signed-in user, or None. Signature is checked before anything
    inside the cookie is trusted, and the account is re-read from the store so a
    disabled account cannot keep an issued cookie alive."""
    if not token or token.count(".") != 1:
        return None
    body, sig = token.split(".", 1)
    want = _b64(hmac.new(_secret(), body.encode(), hashlib.sha256).digest())
    if not hmac.compare_digest(sig, want):
        return None
    try:
        claims = json.loads(_unb64(body))
    except (ValueError, TypeError):
        return None
    if int(claims.get("exp") or 0) < time.time():
        return None
    u = _auth().get_user(str(claims.get("u") or ""))
    if not u or not u["is_active"]:
        return None
    return {"username": u["username"], "role": u["role"],
            "display_name": u["display_name"] or u["username"],
            "is_admin": u["role"] == "admin"}


def _auth():
    if not _cache.get("auth"):
        from clara_monitor.auth import Auth
        _cache["auth"] = Auth(_writable_db())
    return _cache["auth"]


# --------------------------------------------------------------------------
# the operational database (section 9)
# --------------------------------------------------------------------------

WITH_TRENDS = os.environ.get("CLARA_WITH_TRENDS", "").strip().lower() in (
    "1", "true", "yes")

NOT_DURABLE = (
    "DATABASE_URL is not set, so operational writes are going to this "
    "instance's own temporary filesystem. They will be lost when the instance "
    "recycles and are invisible to every other instance. Section 9 requires a "
    "managed database for a hosted deployment; set DATABESE_URL to a "
    "PostgreSQL connection string.").replace("DATABESE_URL", "DATABASE_URL")

ACCOUNTS_READ_ONLY = (
    "User accounts live in the bundled collection snapshot, which is read-only "
    "here: a change would be written to this instance's temporary filesystem, "
    "invisible to every other instance and discarded on recycle. Manage users "
    "on the local server. Everything else in this application is writable and "
    "durable."
)


def _ops_db():
    """A migrated operational connection for this request.

    `ops.Db` is not thread-safe by design and each request takes its own. The
    schema migration is idempotent and cheap (one SELECT when already current),
    which is what makes it safe to call on a cold start rather than needing a
    separate deploy step that somebody has to remember.
    """
    from clara_monitor import ops
    if not _cache.get("migrated"):
        db = ops.connect(_writable_db())
        _cache["migrated"] = True
        return db
    return ops.Db(_writable_db())


def _ops_accounts():
    from clara_monitor.app.accounts import ReadOnlyAccounts
    return ReadOnlyAccounts(_auth().list_users(), ACCOUNTS_READ_ONLY)


def _engine_note() -> dict:
    from clara_monitor.ops import engine_status
    e = engine_status()
    return {"engine": e.get("engine"), "durable": e.get("durable"),
            "why": e.get("why")}


def _durable() -> bool:
    from clara_monitor.ops import engine_status
    return bool(engine_status().get("durable"))


def _app(handler, user: dict, route: str, query: dict, form=None):
    """Hand the request to the shared router (the same one serve.py calls)."""
    from clara_monitor import app as opsapp
    db = _ops_db()
    try:
        req = opsapp.Request(
            method=("POST" if form is not None else "GET"), path=route,
            query=query, form=form or {}, user=user, db=db,
            auth=_ops_accounts())
        resp = opsapp.handle(req)
    finally:
        db.close()
    if resp.status in (301, 302, 303, 307) and resp.location:
        return handler._redirect(resp.location)
    body = (resp.body if isinstance(resp.body, bytes)
            else resp.body.encode("utf-8"))
    if not _durable() and resp.content_type.startswith("text/html"):
        # Said on every page, not only on the System page. A reader who cannot
        # see that their resolution is about to be discarded has been misled.
        banner = (
            '<div role="alert" style="background:#fbeaec;color:#a8323f;'
            'padding:10px 20px;font:600 12.5px/1.5 system-ui,sans-serif;'
            'text-align:center;border-bottom:1px solid #a8323f">'
            'Storage is not durable. DATABASE_URL is not configured, so '
            'anything saved here is written to this instance&rsquo;s temporary '
            'filesystem and will be lost when it recycles.'
            '</div>').encode()
        body = body.replace(b"<body>", b"<body>" + banner, 1)
    return handler._send(body, resp.content_type, resp.status)


# --------------------------------------------------------------------------
# chrome
# --------------------------------------------------------------------------

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
.livebar .ro{color:var(--amb)}
.livebar .sp{margin-inline-start:auto;display:flex;gap:7px;align-items:center}
nav.jump{top:39px}
"""


def _bar(user: dict, run_id: str, stamp: str, page: str = "prices") -> str:
    # Three pages, one product. The bar is the only thing every page shares
    # before the stylesheet, so it is where "these belong together" is stated.
    P = ['<div class="livebar"><div class="wrap">']
    P.append('<span class="dot"></span>')
    for slug, href, label in (("prices", "/", "Competitors"),
                              ("trends", "/trends", "Trends"),
                              ("decisions", "/decisions", "Decisions")):
        P.append('<a class="lb%s" href="%s">%s</a>'
                 % (' on' if page == slug else '', href, label))
    if page == "trends":
        P.append('<span>Six markets scanned</span>')
    elif page == "decisions":
        P.append('<span>Competitor moves and market trends</span>')
    else:
        P.append(f'<span>Run <b>{run_id}</b></span>')
    P.append(f'<span>Rendered <b>{stamp}</b></span>')
    P.append('<span class="ro" title="A monitoring run contacts competitor sites for '
             'about an hour and is bound by the access policy, which cannot happen '
             'inside a serverless request.">hosted snapshot &mdash; re-run is local '
             'only</span>')
    P.append('<span class="sp">')
    if page == "trends":
        P.append('<a class="lb" href="/trends.json">JSON</a>')
    elif page == "prices":
        P.append('<a class="lb" href="/prices.csv">CSV</a>')
        P.append('<a class="lb" href="/prices.jsonl">JSONL</a>')
    if user.get("is_admin"):
        P.append('<a class="lb" href="/admin">Users</a>')
    P.append(f'<span>{user["display_name"]}</span>')
    P.append('<form method="post" action="/logout">'
             '<button type="submit">Sign out</button></form>')
    P.append('</span></div></div>')
    return "\n".join(P)


def _snapshot_note(run: dict | None) -> str:
    started = (run or {}).get("started_at") or "unknown"
    finished = (run or {}).get("finished_at") or "unfinished"
    return (
        '<div class="note"><b>This is a hosted snapshot.</b> The store was captured '
        f'at deploy time from a run started {started} and finished {finished}. '
        'Refresh re-renders that snapshot; it does not make it newer. Collecting '
        'fresh observations means running the Agent locally &mdash; that is the only '
        'path that contacts a competitor site, and it stays bound by the access '
        'policy.</div>')


TRENDS_NOTE = (
    '<div class="note"><b>This is a hosted snapshot.</b> The trends, offers and '
    'social signals below were gathered at deploy time. The clock on each one is '
    'real &mdash; it counts from when that signal was first seen, so it keeps '
    'ageing here rather than resetting to &ldquo;just now&rdquo;. A new scan is a '
    'local Agent run, which is also the only path that reads a source.</div>')


# --------------------------------------------------------------------------
# rendering
# --------------------------------------------------------------------------

def _stamp() -> str:
    return time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime())


def _prices(user: dict) -> str:
    """Render the price and match report. Cached for the life of a warm instance;
    the store cannot change under it, so a rebuild would only cost time."""
    if not _cache.get("prices"):
        t0 = time.time()
        from clara_monitor import competitors as comp, reporting, site
        from clara_monitor.store import Store

        store = Store(_writable_db())
        try:
            for c in comp.REGISTRY.values():
                store.upsert_competitor(c)
            run_id = store.latest_run_id() or "r1"
            # write=False: there is nowhere to persist report files, so every
            # report is built in memory.
            bundle = reporting.build_all(store, run_id, write=False)
            bundle["competitors"] = reporting.competitor_cards(store, run_id)
            bundle["offers"] = reporting.offers_report(store, run_id)
            bundle["actions"] = reporting.actions_report(store, run_id)
        finally:
            store.close()

        # Both halves attached, so the comparator's reading band can name the
        # decisions it leads to instead of degrading to "no cycle attached".
        bundle["intel"] = _intel()
        bundle["trends"] = _trend_bundle()
        html = site.render(bundle)
        html = html.replace("</style>", BAR_CSS + "</style>", 1)
        html = html.replace('<p class="lede">Every Clara product in the catalog',
                            _snapshot_note(bundle.get("run"))
                            + '<p class="lede">Every Clara product in the catalog', 1)
        _cache.update(prices=html, run_id=run_id, price=bundle["price"],
                      bundle=bundle,
                      prices_ms=int((time.time() - t0) * 1000))

    return _cache["prices"].replace(
        '<header class="top">',
        _bar(user, _cache["run_id"], _stamp(), "prices") + '<header class="top">', 1)


def _trend_bundle() -> dict:
    if not _cache.get("trend_bundle"):
        from clara_monitor import trend_store
        ts = trend_store.TrendStore(_writable_db())
        try:
            # Read only. `build` reads what the last local scan stored; it
            # fetches nothing, and there is nothing to seed — the store already
            # holds every signal and every first_seen_at from the bundle.
            _cache["trend_bundle"] = trend_store.build(ts)
        finally:
            ts.close()
    return _cache["trend_bundle"]


def _trends(user: dict) -> str:
    """Render the trends page.

    Not cached across requests: every card carries a relative clock, and serving a
    warm copy would freeze those clocks at whatever the first request saw. The
    bundle it is built from is cached; only the render is repeated.
    """
    from clara_monitor import trend_page
    html = trend_page.render(_trend_bundle(), _decision_items())
    html = html.replace("</style>", BAR_CSS + "</style>", 1)
    html = html.replace('<header class="top">',
                        _bar(user, _cache.get("run_id") or "r1", _stamp(), "trends")
                        + '<header class="top">', 1)
    return html.replace('<section id="feed">', TRENDS_NOTE + '<section id="feed">', 1)


def _intel() -> dict:
    """The intelligence cycle bundled at deploy time, read never run.

    A cycle compares the current evidence against the previous state and writes
    the result. Running one inside a serverless request would write that state to
    a filesystem thrown away moments later, and would stamp evidence collected
    days ago as though it had just been verified. So the cycle is computed on a
    machine with a real disk by `sync_deploy.py`, and this reads it.

    The consequence is stated on the page rather than hidden: the decisions are
    as current as the cycle in the bundle, and the bundle says when that was.
    """
    if _cache.get("intel") is None:
        path = Path(ROOT) / "data" / "intel.json"
        try:
            _cache["intel"] = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            _cache["intel"] = {}
    return _cache["intel"]


def _decision_items() -> list:
    """The reading band the separated Trends page annotates itself with.

    Not a page of its own any more — the mixed Decisions destination is retired
    (section 2) — but `trend_page.render` still takes these so a trend can name
    the comparison behind it. Built from the bundle `_prices` already assembled
    rather than assembling a second one.
    """
    if _cache.get("dec_items") is None:
        from clara_monitor import intel_sections
        if not _cache.get("bundle"):
            _prices({"display_name": "", "is_admin": False})
        b = _cache.get("bundle") or {}
        _cache["dec_items"] = intel_sections.decision_items(b, b.get("trends"))
    return _cache["dec_items"]


def _export(kind: str) -> bytes:
    from clara_monitor import reporting
    if not _cache.get("price"):
        _prices({"display_name": "", "is_admin": False})
    path = os.path.join(TMP_DIR, f"prices.{kind}")
    if kind == "csv":
        reporting.export_price_csv(_cache["price"], path)
    else:
        reporting.export_jsonl(_cache["price"], path)
    with open(path, "rb") as f:
        return f.read()


# --------------------------------------------------------------------------
# handler
# --------------------------------------------------------------------------

class handler(BaseHTTPRequestHandler):
    server_version = "ClaraHosted/2.1"

    # ---------- plumbing ----------

    def log_message(self, *args):
        pass

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
            self.send_header("Set-Cookie", f"{COOKIE}={set_cookie}; HttpOnly; "
                                           "Secure; SameSite=Lax; Path=/")
        if clear_cookie:
            self.send_header("Set-Cookie", f"{COOKIE}=; HttpOnly; Secure; "
                                           "SameSite=Lax; Path=/; Max-Age=0")
        self.end_headers()
        self.wfile.write(body)

    def _html(self, markup: str, code: int = 200, **kw):
        self._send(markup.encode("utf-8"), "text/html; charset=utf-8", code, **kw)

    def _redirect(self, to: str = "/", **kw):
        self.send_response(303)
        self.send_header("Location", to)
        self.send_header("Content-Length", "0")
        self.send_header("Cache-Control", "no-store")
        if kw.get("set_cookie"):
            self.send_header("Set-Cookie", f"{COOKIE}={kw['set_cookie']}; HttpOnly; "
                                           "Secure; SameSite=Lax; Path=/")
        if kw.get("clear_cookie"):
            self.send_header("Set-Cookie", f"{COOKIE}=; HttpOnly; Secure; "
                                           "SameSite=Lax; Path=/; Max-Age=0")
        self.end_headers()

    def _parts(self):
        """The path and query the visitor asked for.

        The catch-all rewrite replaces the request path with `/api/index`, so the
        original path rides in `__p` and is read back here. Without this every
        route rendered the same page, including the exports.
        """
        p = urllib.parse.urlsplit(self.path)
        q = urllib.parse.parse_qs(p.query)
        raw = (q.pop("__p", None) or [p.path])[0] or "/"
        if not raw.startswith("/"):
            raw = "/" + raw
        inner = urllib.parse.urlsplit(raw)
        if inner.query:
            q.update(urllib.parse.parse_qs(inner.query))
        return (inner.path.rstrip("/") or "/"), q

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

    def _form(self) -> dict:
        try:
            n = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            n = 0
        if n <= 0 or n > 100_000:
            return {}
        raw = self.rfile.read(n).decode("utf-8", "replace")
        return {k: v[0] for k, v in urllib.parse.parse_qs(raw).items()}

    # ---------- GET ----------

    def do_GET(self):
        route, q = self._parts()
        try:
            from clara_monitor import pages
            user = _verify(self._token())

            if route == "/logout":
                # Reached by a bookmarked link rather than the button. Clear the
                # cookie either way — a GET that leaves you signed in is a trap.
                return self._redirect("/login?m=" + urllib.parse.quote("Signed out."),
                                      clear_cookie=True)

            if route == "/login":
                if user:
                    return self._redirect("/overview")
                return self._html(pages.login_page(
                    error=(q.get("e") or [""])[0], notice=(q.get("m") or [""])[0],
                    next_url=(q.get("next") or ["/"])[0]))

            if not user:
                nxt = urllib.parse.quote(route, safe="/")
                return self._redirect(f"/login?next={nxt}")

            # --- the retired Decisions tab (section 2, 3.1) ---
            if route in ("/decisions", "/decisions.json"):
                return self._redirect("/overview?flash=" + urllib.parse.quote(
                    "The Decisions tab has been retired. Competitor findings "
                    "are on Overview and in Actions; pricing, marketing and "
                    "trend recommendations are no longer mixed into one page."))

            # --- the separated Market Trends module (3.1) ---
            if route in ("/trends", "/trends.json"):
                if not WITH_TRENDS:
                    return self._send(
                        b"Beauty Trends is a separate optional module and is "
                        b"not part of Competitor Intelligence (addendum 3.1). "
                        b"Set CLARA_WITH_TRENDS=1 to serve it here.",
                        "text/plain; charset=utf-8", 404)
                if route == "/trends.json":
                    return self._send(
                        json.dumps(_trend_bundle(), ensure_ascii=False).encode(),
                        "application/json; charset=utf-8")
                return self._html(_trends(user))

            # --- the old long report, read-only, as a migration aid ---
            if route == "/report":
                return self._html(_prices(user))

            # --- exports: section 1 keeps these supported ---
            if route == "/prices.csv":
                return self._send(_export("csv"), "text/csv; charset=utf-8")
            if route == "/prices.jsonl":
                return self._send(_export("jsonl"),
                                  "application/x-ndjson; charset=utf-8")
            if route == "/price.json":
                _prices(user)
                return self._send(json.dumps(_cache["price"],
                                             ensure_ascii=False).encode(),
                                  "application/json; charset=utf-8")

            # --- old entry points, pointed at where things live now ---
            if route in ("/", "/index", "/api/index", "/refresh"):
                return self._redirect("/overview")
            if route == "/admin":
                return self._redirect("/admin/users")
            if route == "/rerun":
                return self._redirect("/overview")
            if route == "/status.json":
                _prices(user)
                b = _trend_bundle()
                return self._send(json.dumps({
                    "run_id": _cache["run_id"],
                    "rendered_at": _stamp(),
                    "hosted": True,
                    "snapshot": True,
                    "prices_build_ms": _cache.get("prices_ms"),
                    "trends": b["counts"],
                    "rerun_available": False,
                    "rerun_reason": ("a monitoring run contacts competitor sites for "
                                     "about an hour and is bound by the access "
                                     "policy; it cannot run inside a serverless "
                                     "request"),
                    "user_management": "local only — see /admin/users",
                    "operational_storage": _engine_note(),
                }).encode(), "application/json; charset=utf-8")

            # --- everything else is the application (the shared router) ---
            return _app(self, user, route, q)
        except Exception as e:
            import traceback
            self._send((f"render failed: {type(e).__name__}: {e}\n\n"
                        + traceback.format_exc()).encode(),
                       "text/plain; charset=utf-8", 500)

    # ---------- POST ----------

    def do_POST(self):
        route, _ = self._parts()
        try:
            form = self._form()

            if route == "/login":
                a = _auth()
                username = (form.get("username") or "").strip().lower()
                u = a.get_user(username)
                from clara_monitor.auth import hash_password, verify_password
                if not u or not u["is_active"]:
                    # Spend the hashing cost anyway, so a missing account and a
                    # wrong password take the same time.
                    hash_password(form.get("password") or "", os.urandom(16))
                    ok = False
                else:
                    ok = verify_password(form.get("password") or "",
                                         u["pw_salt"], u["pw_hash"])
                if not ok:
                    return self._redirect("/login?e=" + urllib.parse.quote(
                        "Wrong username or password, or the account is disabled."))
                nxt = form.get("next") or "/"
                if not nxt.startswith("/"):
                    nxt = "/"
                return self._redirect(nxt, set_cookie=_issue(u["username"]))

            if route == "/logout":
                return self._redirect("/login?m=" + urllib.parse.quote("Signed out."),
                                      clear_cookie=True)

            if not _verify(self._token()):
                return self._redirect("/login")

            if route == "/refresh":
                return self._redirect("/overview")
            if route == "/rerun":
                return self._send(json.dumps({
                    "ok": False,
                    "reason": ("A collection run contacts competitor sites for "
                               "about an hour and is bound by the access "
                               "policy. That cannot happen inside a serverless "
                               "request."),
                    "run_locally": "python run_agent.py --run-id r2 --targets 2",
                    "then_import": "python ops_import.py --run-id r2",
                }).encode(), "application/json; charset=utf-8", 501)

            user = _verify(self._token())

            # Account writes are the one thing this host genuinely cannot do
            # durably, so they are refused with the reason rather than accepted
            # and discarded. Every other write goes to Postgres.
            if route.startswith("/admin/users/"):
                return self._send(json.dumps({
                    "ok": False, "reason": ACCOUNTS_READ_ONLY,
                }).encode(), "application/json; charset=utf-8", 501)

            # --- everything else is the application ---
            return _app(self, user, route, {}, form)
        except Exception as e:
            import traceback
            self._send((f"request failed: {type(e).__name__}: {e}\n\n"
                        + traceback.format_exc()).encode(),
                       "text/plain; charset=utf-8", 500)
