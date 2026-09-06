#!/usr/bin/env python
"""Google Cloud Run entrypoint for the hosted Clara application.

Cloud Run has the same shape as the serverless host `deploy/api/index.py` was
written for: instances are ephemeral and independent, the filesystem is
throwaway, and the only durable storage is the managed Postgres behind
`DATABASE_URL`. So this file deliberately adds no second application — it loads
the existing handler and serves it over a plain `ThreadingHTTPServer` on the
port Cloud Run provides. Every route, session rule and durability banner is the
one already tested by `tests/test_deploy.py`.

Two Cloud Run specifics are handled here:

1. THE BUNDLED SNAPSHOT ARRIVES BY VOLUME, NOT BY GIT. `data/monitor.sqlite3`
   holds password hashes and is gitignored, so an image built by CI does not
   contain it. The deploy workflow mounts a Cloud Storage bucket read-only at
   `deploy/data`; the bundle is uploaded there from a machine that has run a
   collection (see deploy/gcp/README.md). Because `_writable_db` in the handler
   re-copies whenever the source mtime changes, uploading a fresh snapshot to
   the bucket refreshes a running service without a redeploy.

2. THE SERVICE MUST START EVEN WHEN THE BUCKET IS EMPTY. A crash-looping
   container tells you nothing; instead a plain page says exactly which file is
   missing and how to upload it, and the real application is swapped in on the
   next request once the bundle appears.
"""

from __future__ import annotations

import importlib.util
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
DEPLOY = os.path.dirname(HERE)
if DEPLOY not in sys.path:
    sys.path.insert(0, DEPLOY)

BUNDLED_DB = os.path.join(DEPLOY, "data", "monitor.sqlite3")

_lock = threading.Lock()
_real_handler: type | None = None


def _load_handler() -> type:
    """Import deploy/api/index.py (not a package) and return its handler."""
    global _real_handler
    with _lock:
        if _real_handler is None:
            spec = importlib.util.spec_from_file_location(
                "clara_hosted_index", os.path.join(DEPLOY, "api", "index.py"))
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            _real_handler = mod.handler
    return _real_handler


SETUP_PAGE = """<!doctype html>
<html><head><meta charset="utf-8"><title>Clara &mdash; bundle missing</title>
<style>body{font:15px/1.6 system-ui,sans-serif;max-width:44em;margin:8vh auto;
padding:0 24px;color:#1c2430}code,pre{background:#f2f4f7;border-radius:4px;
padding:2px 5px}pre{padding:12px 14px;overflow-x:auto}h1{font-size:1.3em}</style>
</head><body>
<h1>The collection bundle is not here yet</h1>
<p>The service is running, but <code>deploy/data/monitor.sqlite3</code> is
missing. The snapshot holds account credentials, so it is never committed to
git and never baked into a CI image &mdash; it is served from the Cloud
Storage bucket mounted at <code>deploy/data</code>.</p>
<p>From a machine that has run a collection:</p>
<pre>python sync_deploy.py
gcloud storage cp deploy/data/monitor.sqlite3 deploy/data/intel.json gs://YOUR_BUNDLE_BUCKET/</pre>
<p>Then reload this page &mdash; the application picks the bundle up on the
next request, no redeploy needed. If no bucket is mounted at all, see
<code>deploy/gcp/README.md</code> for the one-time setup.</p>
</body></html>"""


class SetupNeeded(BaseHTTPRequestHandler):
    """Served until the bundle exists; swaps the real handler in when it does."""

    server_version = "ClaraHosted/2.1"

    def log_message(self, *args):
        pass

    def _respond(self):
        if os.path.exists(BUNDLED_DB):
            # The bundle arrived since this instance started. Route every
            # subsequent request to the real application and re-point this one.
            self.server.RequestHandlerClass = _load_handler()
            self.send_response(303)
            self.send_header("Location", self.path or "/")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        body = SETUP_PAGE.encode("utf-8")
        self.send_response(503)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Retry-After", "30")
        self.end_headers()
        self.wfile.write(body)

    do_GET = _respond
    do_POST = _respond
    do_HEAD = _respond


def main() -> None:
    port = int(os.environ.get("PORT", "8080"))
    cls = _load_handler() if os.path.exists(BUNDLED_DB) else SetupNeeded
    server = ThreadingHTTPServer(("0.0.0.0", port), cls)
    print(f"clara hosted: serving on :{port} "
          f"({'bundle loaded' if cls is not SetupNeeded else 'awaiting bundle'})",
          flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
