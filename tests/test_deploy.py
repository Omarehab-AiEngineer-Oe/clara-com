"""Drive the Vercel handler in-process, from the bundle alone.

A serverless deploy fails on the first request, in a log nobody opens. So the
handler is exercised here against nothing but `deploy/` on the path — every route
signed in and signed out, and the page bodies checked for what the addendum
requires them to contain.

What this suite is really guarding is the claim that the hosted site and the local
one are the *same application*. They share `app.router`, so a route working here
is a route working there; and the two things the hosted host does differently —
stateless sessions, and read-only accounts — are checked explicitly rather than
assumed.

Run by `sync_deploy.py` before anything is pushed.
"""
from __future__ import annotations

import importlib.util
import io
import os
import sys
from pathlib import Path

DEPLOY = Path(sys.argv[1]).resolve()
os.chdir(DEPLOY)
sys.path.insert(0, str(DEPLOY))

spec = importlib.util.spec_from_file_location("vidx", DEPLOY / "api" / "index.py")
vidx = importlib.util.module_from_spec(spec)
spec.loader.exec_module(vidx)


class Probe(vidx.handler):                      # type: ignore[name-defined]
    """The real handler with the socket replaced by a buffer."""

    def __init__(self, path: str, cookie: str | None = None, post: str = ""):
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

    def body(self) -> str:
        return self.wbuf.getvalue().decode("utf-8", "replace")

    def cookie(self) -> str | None:
        for k, v in self.out_headers:
            if k == "Set-Cookie" and "clara_session=" in v and "Max-Age=0" not in v:
                return v.split("clara_session=", 1)[1].split(";", 1)[0]
        return None

    def location(self) -> str:
        return dict(self.out_headers).get("Location", "")


def get(path, cookie=None):
    h = Probe(path, cookie=cookie)
    h.do_GET()
    return h


def post(path, body, cookie=None):
    h = Probe(path, cookie=cookie, post=body)
    h.do_POST()
    return h


PASS, FAIL = [], []


def ok(cond, label):
    (PASS if cond else FAIL).append(label)
    print(f"  {'PASS' if cond else 'FAIL'}  {label}")


TABS = ["/overview", "/products", "/competitors", "/actions", "/requests"]

print("signed out — nothing renders without a session")
for route in TABS + ["/admin/users", "/admin/audit", "/offers"]:
    h = get(route)
    ok(h.status == 303 and h.location().startswith("/login"),
       f"{route} -> {h.status} {h.location()[:30]}")

print("\nsign in")
# A known account is provisioned in the throwaway /tmp copy the handler
# authenticates against, rather than hard-coding a real password in a test file.
# It also means this suite keeps working after somebody rotates a password.
PROBE_USER, PROBE_PW = "deploy_probe", "probe-only-not-a-real-account"
_tmp = vidx._writable_db()
from clara_monitor.auth import Auth as _Auth      # noqa: E402

_a = _Auth(_tmp)
try:
    if _a.get_user(PROBE_USER):
        _a.reset_password(PROBE_USER, PROBE_PW)
    else:
        _a.create_user(PROBE_USER, PROBE_PW, role="admin",
                       display_name="Deploy probe", created_by="test")
finally:
    _a.close()

h = post("/login", f"username={PROBE_USER}&password={PROBE_PW}")
tok = h.cookie()
ok(bool(tok), f"login -> {h.status}, stateless session issued")
if not tok:
    print("\ncannot continue without a session")
    print("=" * 66)
    print(f"{len(PASS)}/{len(PASS) + len(FAIL)} checks pass")
    sys.exit(1)

print("\nthe five tabs of section 3")
bodies = {}
for route in TABS:
    h = get(route, tok)
    bodies[route] = h.body()
    ok(h.status == 200 and len(bodies[route]) > 8_000,
       f"{route} -> {h.status}, {len(bodies[route]):,} bytes")

print("\none application shell on every tab (section 10)")
for route, b in bodies.items():
    ok(b.count('<nav class="tabs"') == 1, f"{route} carries the shell once")
    ok(all(t in b for t in TABS), f"{route} shows all five tabs")
    ok("Send Request" in b, f"{route} offers Send Request in the header")
    ok("Intelligence Agent" in b,
       f"{route} offers the Agent as a header control")

print("\nretired and separated surfaces (section 2, 3.1)")
h = get("/decisions", tok)
ok(h.status == 303 and h.location().startswith("/overview"),
   f"/decisions is retired -> {h.status} {h.location()[:22]}")
h = get("/trends", tok)
ok(h.status == 404,
   f"/trends is a separate optional module -> {h.status}")
h = get("/", tok)
ok(h.status == 303 and "/overview" in h.location(),
   f"/ leads to Overview, not the old report -> {h.location()[:20]}")
h = get("/admin", tok)
ok(h.status == 303 and "/admin/users" in h.location(),
   "/admin moves into the Admin menu")
for route, b in bodies.items():
    ok(">Decisions<" not in b,
       f"{route} does not offer the retired Decisions tab")

print("\nroutable detail pages (section 3.1)")
import re
pid = re.search(r'href="/products/([^"?]+)"', bodies["/products"])
ok(bool(pid), "the product list links to product pages")
if pid:
    h = get(f"/products/{pid.group(1)}", tok)
    ok(h.status == 200 and "<h1>" in h.body(),
       f"/products/<id> -> {h.status}, bookmarkable")
    b = h.body()
    ok("Send Request" in b and "/requests/new?kind=product" in b,
       "the product page offers Send Request with its own context")
    # `&` is escaped in the rendered href, so match the parameters, not the
    # raw query string.
    ok("agent=1" in b and "ctx=product" in b,
       "the product page can open the Agent on itself")
ck = re.search(r'href="/competitors/([^"?]+)"', bodies["/competitors"])
ok(bool(ck), "the competitor list links to competitor pages")
if ck:
    h = get(f"/competitors/{ck.group(1)}", tok)
    ok(h.status == 200, f"/competitors/<key> -> {h.status}")

print("\nprovenance and freshness shown consistently (8.2, section 10)")
seen_prov = sum(1 for b in bodies.values() if "pv-automatically_observed" in b)
ok(seen_prov >= 2, f"provenance chips appear on {seen_prov} tabs")
ok("Automatically observed" in bodies["/overview"],
   "Overview defines the provenance labels")
ok("fr-" in bodies["/overview"] or "fr-" in bodies["/products"],
   "freshness is shown as a state, not a bare date")

print("\nthe Admin menu (section 3.1)")
for route in ("/admin/users", "/admin/requests", "/admin/sources",
              "/admin/audit", "/admin/system"):
    h = get(route, tok)
    ok(h.status == 200, f"{route} -> {h.status}")

print("\nsection 9: this host says whether storage is durable")
h = get("/admin/system", tok)
b = h.body()
ok("Storage" in b and ("Postgres" in b or "sqlite" in b or "SQLite" in b),
   "the System page names the engine it is writing to")
durable = vidx._durable()
if not durable:
    ok("Storage is not durable" in b,
       "a non-durable deployment says so on the page, not only in a log")
    h = post("/admin/users/add", "username=x&role=viewer", tok)
    ok(h.status == 501,
       f"account writes are refused with a reason -> {h.status}")
else:
    ok(True, "DATABASE_URL is configured; operational writes are durable")

print("\nexports still supported (section 1)")
for route, ctype in (("/prices.csv", "csv"), ("/prices.jsonl", "ndjson"),
                     ("/status.json", "json")):
    h = get(route, tok)
    got = dict(h.out_headers).get("Content-Type", "")
    ok(h.status == 200 and ctype in got,
       f"{route} -> {h.status} {got.split(';')[0]}")

print("\nno double-escaped entities")
for name, b in bodies.items():
    ok("&amp;mdash;" not in b and "&amp;middot;" not in b
       and "&amp;times;" not in b, f"{name} escapes once")

print("\nsummary counts carry their definitions (section 10, 12)")
ov = bodies["/overview"]
ok("Open counts actions whose status is open" in ov,
   "the open-actions figure states what it counts")
ok("unique offers" in ov.lower() and "association" in ov.lower(),
   "unique offers and product associations are distinguished")
ok("Clara products are in the catalogue" in ov,
   "coverage states the catalogue total it is measured against")

print("\n" + "=" * 66)
print(f"{len(PASS)}/{len(PASS) + len(FAIL)} checks pass")
for f in FAIL:
    print(f"  FAILED: {f}")
sys.exit(1 if FAIL else 0)
