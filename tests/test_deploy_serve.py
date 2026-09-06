"""The hosted site must be the same site as the local one.

It was not. `deploy/api/index.py` routed through `clara_monitor.app.router` —
the five-tab operational application — while the local server had gone back to
`serve.py`'s Competitors / Trends / Decisions pages. Same data, two different
products, and nothing anywhere said so. That is the worst kind of drift: every
page works, and none of them matches what you were shown locally.

So this drives the real serverless handler against the built bundle and checks
the route table is the one `serve.py` defines: the same pages, the same
redirects, and none of the routes that were deleted.

    python tests/test_deploy_serve.py deploy
"""
from __future__ import annotations

import importlib.util
import io
import os
import sys
from pathlib import Path

DEPLOY = Path(sys.argv[1] if len(sys.argv) > 1 else "deploy").resolve()
ROOT = DEPLOY.parent
# Kept alive on purpose: importing the entrypoint pulls in `serve`, which
# replaces sys.stdout, and letting the displaced wrapper be collected closes the
# buffer underneath this one.
_kept_stdout = sys.stdout
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8",
                              errors="replace")
_own_stdout = sys.stdout

os.chdir(DEPLOY)
sys.path.insert(0, str(DEPLOY))

spec = importlib.util.spec_from_file_location("vidx", DEPLOY / "api" / "index.py")
vidx = importlib.util.module_from_spec(spec)
spec.loader.exec_module(vidx)
# The entrypoint imports `serve`, which installs its own stdout wrapper over the
# same buffer. Both the displaced wrapper and the replacement are kept
# referenced: whichever is collected takes the shared buffer down with it, and
# every print after that raises.
_serve_stdout = sys.stdout
sys.stdout = _own_stdout

PASS, FAIL = [], []


def ok(cond, label):
    (PASS if cond else FAIL).append(label)
    print(f"  {'PASS' if cond else 'FAIL'}  {label}")


def section(title):
    print(f"\n{title}")


class Probe(vidx.handler):                       # type: ignore[name-defined]
    """The real handler with the socket replaced by a buffer."""

    def __init__(self, path, cookie=None, post=""):
        self.path = path
        self.wbuf = io.BytesIO()
        self.wfile = self.wbuf
        self.rfile = io.BytesIO(post.encode())
        hdr = {"Cookie": f"clara_session={cookie}" if cookie else "",
               "Content-Length": str(len(post))}
        self.headers = {k: v for k, v in hdr.items() if v}
        self.status = None
        self.out_headers = []
        self.client_address = ("127.0.0.1", 0)
        self.requestline = f"GET {path}"
        self.request_version = "HTTP/1.1"
        self.command = "POST" if post else "GET"

    def send_response(self, code, message=None):
        self.status = code

    def send_header(self, k, v):
        self.out_headers.append((k, v))

    def end_headers(self):
        pass

    def log_message(self, *a):
        pass

    def body(self):
        return self.wbuf.getvalue().decode("utf-8", "replace")

    def cookie(self):
        for k, v in self.out_headers:
            if k == "Set-Cookie" and "clara_session=" in v \
                    and "Max-Age=0" not in v:
                return v.split("clara_session=", 1)[1].split(";", 1)[0]
        return None

    def location(self):
        return dict(self.out_headers).get("Location", "")


def _rewritten(path):
    """The form Vercel actually delivers.

    `vercel.json` rewrites every request to `/api/index?__p=/the/real/path`, so
    a probe that passes a clean path tests something the platform never sends.
    That gap let a real break through: every route resolved to the same one in
    production while this suite passed.
    """
    import urllib.parse
    split = urllib.parse.urlsplit(path)
    q = f"&{split.query}" if split.query else ""
    return f"/api/index?__p={urllib.parse.quote(split.path)}{q}"


def get(path, cookie=None, raw=False):
    h = Probe(path if raw else _rewritten(path), cookie=cookie)
    h.do_GET()
    return h


def post(path, body, cookie=None, raw=False):
    h = Probe(path if raw else _rewritten(path), cookie=cookie, post=body)
    h.do_POST()
    return h


# ------------------------------------------------------------------ signed out
section("Signed out, every page sends you to the login")

r = get("/login")
ok(r.status == 200, f"/login renders ({r.status})")
ok("Sign in" in r.body(), "and offers a sign-in form")

for path in ("/", "/trends", "/decisions", "/product?id=x", "/status.json"):
    r = get(path)
    ok(r.status == 303 and r.location().startswith("/login"),
       f"{path} redirects to the login ({r.status})")

# ------------------------------------------------------------------ signed in
section("Signed in, the pages are the ones serve.py defines")

users = []
try:
    from clara_monitor.auth import Auth
    a = Auth(vidx._DB)
    users = [u["username"] for u in a.list_users()]
    a.close()
except Exception as exc:                                  # noqa: BLE001
    print(f"  (could not list users: {exc})")

ok(bool(users), f"the bundled snapshot carries {len(users)} user(s)")

# A signed token is issued directly: the password is not in the bundle in any
# readable form, which is the point of it.
token = vidx._issue(users[0]) if users else None
ok(bool(token), "a session token can be signed")
ok(vidx._verify(token) is not None if token else False,
   "and verifies back to a real user")
ok(vidx._verify("nonsense.token") is None, "a forged token does not verify")
ok(vidx._verify(None) is None, "and neither does no token")

if token:
    PAGES = {
        "/": ("Competitors", "Clara products and prices"),
        "/trends": ("Trends", None),
        "/decisions": ("Decisions", None),
    }
    for path, (label, marker) in PAGES.items():
        r = get(path, cookie=token)
        ok(r.status == 200, f"{path} renders signed in ({r.status})")
        body = r.body()
        ok(len(body) > 20000, f"{path} is a full page ({len(body)} bytes)")
        nav = "Competitors" in body and "Trends" in body \
            and "Decisions" in body
        ok(nav, f"{path} carries the three-page navigation")
        ok("Website audit" not in body,
           f"{path} does not link the deleted audit page")
        if marker:
            ok(marker in body, f"{path} contains {marker!r}")

    # a product page, using a real id from the bundle
    pid = None
    try:
        import serve as _serve
        b = _serve.build_bundle(_serve.STATE["run_id"])
        prods = (b.get("price") or {}).get("products") or []
        pid = prods[0]["product_id"] if prods else None
        ok(len(prods) > 0, f"the bundle carries {len(prods)} product(s)")
    except Exception as exc:                              # noqa: BLE001
        ok(False, f"could not read the bundled catalogue: {exc}")

    if pid:
        r = get(f"/product?id={pid}", cookie=token)
        ok(r.status == 200, f"a product page renders ({r.status})")
        ok("The record" in r.body(), "and shows the catalogue record")

    # exports
    for path, kind in (("/status.json", "json"), ("/prices.csv", "csv"),
                       ("/trends.json", "json"),
                       ("/decisions.json", "json")):
        r = get(path, cookie=token)
        ok(r.status == 200, f"{path} serves ({r.status})")

# ------------------------------------------------------------------ deleted
section("Routes that no longer exist do not answer")

if token:
    for path in ("/audit", "/audit.json", "/audit.csv"):
        r = get(path, cookie=token)
        ok(r.status == 404,
           f"{path} is gone ({r.status})")
    # the five-tab application's own routes
    for path in ("/products", "/actions", "/requests", "/overview"):
        r = get(path, cookie=token)
        ok(r.status == 404,
           f"{path} belonged to the removed application ({r.status})")

# ------------------------------------------------------------------ login flow
section("The login issues a signed token, not a stored session")

r = post("/login", "username=nobody&password=wrong")
ok(r.status == 303 and "e=" in r.location(),
   "a wrong password is refused with a message")
ok(r.cookie() is None, "and sets no cookie")

section("The catch-all rewrite is undone before routing")

r = get("/login")
ok(r.status == 200,
   "a rewritten /api/index?__p=/login resolves to the login page, not to a "
   f"redirect back onto itself ({r.status})")
ok("next=/api/index" not in r.body() and "next=/api/index" not in r.location(),
   "and nothing leaks the function name as the route")
if token:
    r = get("/trends", cookie=token)
    ok(r.status == 200 and len(r.body()) > 20000,
       "a rewritten /trends resolves to the trends page, not the default one")
    r2 = get("/decisions", cookie=token)
    ok(r2.body() != r.body(),
       "two different routes return two different pages — the symptom of a "
       "missed rewrite is that they do not")

src = (DEPLOY / "api" / "index.py").read_text(encoding="utf-8")
ok("hmac" in src and "compare_digest" in src,
   "the token is signed and compared in constant time")
# An import, not a mention: the docstring explains what this file replaced, and
# naming it there is the point rather than a leak.
import re as _re
ok(not _re.search(r"^\s*(from|import)\s+clara_monitor\.app", src, _re.M),
   "the entrypoint imports nothing from the removed application")
ok("import serve" in src,
   "it serves serve.py's route table, the same one the local server uses")

print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
for f in FAIL:
    print(f"  FAILED  {f}")
sys.exit(1 if FAIL else 0)
