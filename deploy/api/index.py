"""Vercel entrypoint for the Clara report — the same site as the local server.

This replaces an earlier entrypoint that served a different application: it
routed through `clara_monitor.app.router`, the five-tab operational app, while
the local server had gone back to `serve.py`. The hosted site and the local one
were therefore two different products with the same data behind them, which is
the most confusing possible failure — everything works, and nothing matches.

So this file does one thing: it makes `serve.Handler` runnable on Vercel. Three
platform facts have to be handled rather than hidden.

**The filesystem is read-only except `/tmp`.** The bundled SQLite snapshot ships
inside the deployment, and SQLite needs to open its database for writing even to
serve a page — a session write, a WAL file. So the snapshot is copied to `/tmp`
on first use, and a marker file records which bundle the copy came from, because
`shutil.copyfile` does not preserve mtime and a naive freshness check compares
the copy against itself and never refreshes.

**`/tmp` is per-instance and temporary.** A session created on one instance is
invisible to the next, and everything written there is lost when the instance
recycles. That is why sessions are signed tokens rather than rows: a cookie that
validates by signature works on any instance without shared storage.

**Nothing collects here.** A monitoring run contacts competitor sites for the
better part of an hour; a serverless request has seconds. So the hosted site
renders the stored cycle and never produces one. `/refresh` and `/rerun` are
present because the page shares one route table with the local server, and they
do nothing useful on this instance — collection stays a local job.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import shutil
import sys
import time
import urllib.parse
from http import cookies
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

TMP_DIR = "/tmp/clara"
TMP_DB = os.path.join(TMP_DIR, "monitor.sqlite3")
# Which bundle TMP_DB was copied from. Without this the freshness check compares
# the copy's own mtime against itself: `copyfile` does not carry mtime across, so
# the copy always looks newer than the source and never refreshes — and any write
# to the copy makes it look newer still.
TMP_MARK = os.path.join(TMP_DIR, "bundle.id")

BUNDLED_DB = ROOT / "data" / "monitor.sqlite3"


def _writable_db() -> Path:
    """The bundled snapshot, somewhere SQLite is allowed to open it."""
    if not BUNDLED_DB.exists():
        return BUNDLED_DB
    os.makedirs(TMP_DIR, exist_ok=True)
    stat = BUNDLED_DB.stat()
    want = f"{stat.st_size}:{int(stat.st_mtime)}"
    have = ""
    if os.path.exists(TMP_MARK):
        try:
            with open(TMP_MARK, encoding="utf-8") as f:
                have = f.read().strip()
        except OSError:
            have = ""
    if not os.path.exists(TMP_DB) or have != want:
        shutil.copyfile(BUNDLED_DB, TMP_DB)
        # A stale WAL beside a fresh copy describes the previous database.
        for suffix in ("-wal", "-shm"):
            leftover = TMP_DB + suffix
            if os.path.exists(leftover):
                os.remove(leftover)
        with open(TMP_MARK, "w", encoding="utf-8") as f:
            f.write(want)
    return Path(TMP_DB)


# The database has to be redirected before anything imports a module that binds
# it at import time.
_DB = _writable_db()
from clara_monitor import config as _config           # noqa: E402

_config.DB_PATH = _DB

import serve                                          # noqa: E402

serve.DB_PATH = _DB


# --------------------------------------------------------------------------
# sessions that survive an instance change
# --------------------------------------------------------------------------
# `/tmp` is per-instance, so a session row written on one instance is invisible
# to the next and a signed-in user would be logged out at random. A signed token
# validates anywhere without shared storage, which is what this platform can
# actually offer.

SESSION_HOURS = 12


def _secret() -> bytes:
    raw = os.environ.get("CLARA_SESSION_SECRET")
    if raw:
        return raw.encode("utf-8")
    # No secret configured: derive one from the deployment id so tokens at least
    # stay valid for the life of this deployment rather than one request.
    seed = (os.environ.get("VERCEL_DEPLOYMENT_ID")
            or os.environ.get("VERCEL_URL") or "clara-local")
    return hashlib.sha256(seed.encode("utf-8")).digest()


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _unb64(txt: str) -> bytes:
    return base64.urlsafe_b64decode(txt + "=" * (-len(txt) % 4))


def _issue(username: str) -> str:
    body = f"{username}|{int(time.time()) + SESSION_HOURS * 3600}"
    sig = hmac.new(_secret(), body.encode("utf-8"), hashlib.sha256).digest()
    return f"{_b64(body.encode('utf-8'))}.{_b64(sig)}"


def _verify(token: str | None) -> dict | None:
    if not token or "." not in token:
        return None
    body_b64, sig_b64 = token.rsplit(".", 1)
    try:
        body = _unb64(body_b64)
        sig = _unb64(sig_b64)
    except Exception:                                    # noqa: BLE001
        return None
    want = hmac.new(_secret(), body, hashlib.sha256).digest()
    if not hmac.compare_digest(sig, want):
        return None
    try:
        username, expires = body.decode("utf-8").rsplit("|", 1)
        if int(expires) < time.time():
            return None
    except ValueError:
        return None
    auth = serve._auth
    if not auth:
        return None
    u = auth.get_user(username)
    if not u or not u["is_active"]:
        return None
    # The same narrowed shape `Auth.session_user` returns, and deliberately not
    # the raw row: that carries `pw_hash` and `pw_salt`, and a password hash has
    # no business travelling in the request context where a page could reach it.
    from clara_monitor.auth import ROLE_ADMIN
    return {"username": u["username"], "role": u["role"],
            "display_name": u["display_name"] or u["username"],
            "is_admin": u["role"] == ROLE_ADMIN}


def _boot() -> None:
    """What `serve.main()` does, minus the socket and the printing."""
    if serve._auth is not None:
        return
    from clara_monitor.auth import Auth

    serve._auth = Auth(_DB)
    serve.STATE["run_id"] = os.environ.get("CLARA_RUN_ID", "r1")
    serve.Handler.run_id = serve.STATE["run_id"]


_boot()


class handler(serve.Handler):                            # noqa: N801
    """`serve.Handler`, with the three things a socket server gave it replaced.

    Vercel's Python runtime instantiates this per request, so the class name is
    the contract and has to stay lowercase.
    """

    # ---- the path the visitor actually asked for ----
    def _restore_path(self):
        """Undo the catch-all rewrite before serve.py parses the request.

        `vercel.json` rewrites every request to `/api/index?__p=/the/real/path`,
        so `self.path` arrives as the function name and the real route rides in
        `__p`. Without putting it back, every route resolves to the same one —
        which showed up as `/login` redirecting to `/login?next=/api/index`.
        """
        split = urllib.parse.urlsplit(self.path)
        query = urllib.parse.parse_qs(split.query)
        raw = (query.pop("__p", None) or [split.path])[0] or "/"
        if not raw.startswith("/"):
            raw = "/" + raw
        inner = urllib.parse.urlsplit(raw)
        merged = dict(query)
        if inner.query:
            merged.update(urllib.parse.parse_qs(inner.query))
        flat = urllib.parse.urlencode(
            [(k, v) for k, vals in merged.items() for v in vals])
        self.path = inner.path + (f"?{flat}" if flat else "")

    def do_GET(self):
        self._restore_path()
        return serve.Handler.do_GET(self)

    # ---- sessions ----
    def _token(self):
        raw = self.headers.get("Cookie")
        if not raw:
            return None
        jar = cookies.SimpleCookie()
        try:
            jar.load(raw)
        except cookies.CookieError:
            return None
        got = jar.get(serve.COOKIE)
        return got.value if got else None

    def _user(self):
        return _verify(self._token())

    # ---- logging ----
    def log_message(self, fmt, *args):
        """Nothing. The platform captures stdout, and one line per request
        buries the tracebacks that actually matter."""

    def log_error(self, fmt, *args):
        sys.stderr.write((fmt % args) + "\n")


# `serve.Handler.do_POST` calls `_auth.login` and then hands the returned token
# to the cookie. Here the cookie has to carry a signed token instead, so the
# login route is wrapped rather than reimplemented.
_orig_route_post = serve.Handler._route_post if hasattr(
    serve.Handler, "_route_post") else None


def _patched_login(self):
    """Issue a signed token on a successful login, keeping serve's own check."""
    form = self._form()
    token = serve._auth.login(form.get("username", ""),
                              form.get("password", ""),
                              self.headers.get("User-Agent", ""))
    nxt = form.get("next") or "/"
    if not nxt.startswith("/") or nxt.startswith("//"):
        nxt = "/"
    if not token:
        return self._redirect("/login?e=Wrong+username+or+password")
    user = serve._auth.session_user(token)
    signed = _issue(user["username"]) if user else None
    if not signed:
        return self._redirect("/login?e=Wrong+username+or+password")
    return self._redirect(nxt, set_cookie=signed)


def _do_post(self):
    self._restore_path()
    route = self.path.split("?", 1)[0].rstrip("/") or "/"
    if route == "/login":
        return _patched_login(self)
    return serve.Handler.do_POST(self)


handler.do_POST = _do_post
