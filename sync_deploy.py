"""Rebuild the Vercel bundle from the live tree.

The deploy folder used to be a hand-copied subset of `clara_monitor`, and it
drifted: by the time the Decisions page existed, the bundle was missing eight
modules and still shipping the two-page site. A hand-copied subset always drifts,
because nothing fails when you forget a file — the deployed site simply stays
old.

So the copy is derived instead. Everything the pages import comes across, the
SQLite snapshot comes across, and the most recent intelligence cycle comes across
as JSON.

That last point is the important one. **The serverless instance never runs a
cycle.** A cycle compares the current evidence against the previous state and
writes the result; running one per cold start would write a new cycle on a
throwaway filesystem and date-stamp old evidence as if it were new. So the cycle
is computed here, on a machine with a real disk, and the deployed page reads it
and says when it was computed. The page is a snapshot that knows it is one.

Usage:
    python sync_deploy.py            # rebuild the bundle
    python sync_deploy.py --deploy   # rebuild, then `vercel --prod`
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DEPLOY = ROOT / "deploy"
SRC = ROOT / "clara_monitor"

# Everything the three pages reach, directly or transitively. Listed rather than
# globbed so adding a module is a decision: a file that lands in the bundle
# without anyone choosing it is how the last drift started.
MODULES = [
    "__init__.py", "access.py", "auth.py", "cards.py", "catalog.py",
    "competitor_profiles.py", "competitors.py", "config.py",
    "decisions_page.py", "discovery.py", "engine.py", "extract.py",
    "intel_sections.py", "llm.py", "matching.py", "models.py", "money.py",
    "observe.py", "pages.py", "pipeline.py", "report.py", "reporting.py",
    "scan_layer.py", "site.py", "store.py", "trend_ideas.py", "trend_page.py",
    "trend_sources.py", "trend_store.py", "trend_topics.py", "ui.py",
]

# The agent layer. The page renders a stored cycle rather than running one, but
# the contracts and the store are still imported to read it.
PACKAGES = {
    "agents": ["__init__.py", "action.py", "arrangement.py", "base.py",
               "collection.py", "contracts.py", "discovery.py", "identity.py",
               "intelligence.py", "offer_store.py", "offer_sweep.py",
               "offers.py", "orchestrator.py", "state.py", "store.py",
               "trend_collector.py", "verification.py"],
    "discovery": ["__init__.py", "config.py", "feeds.py", "report.py",
                  "sources.py", "store.py", "topics.py"],
    # The operational domain (the addendum's sections 4-9) and the application
    # that renders it. Both go across whole: the hosted site runs the same
    # router as the local one, so a file missing here is a route that 500s only
    # in production.
    "ops": ["__init__.py", "actions.py", "agent.py", "audit.py", "authz.py",
            "db.py", "ingest.py", "requests.py", "schema.py"],
    "app": ["__init__.py", "accounts.py", "actions_view.py", "admin_view.py",
            "agent_view.py", "competitors.py", "overview.py", "products.py",
            "read.py", "requests_view.py", "router.py", "shell.py"],
}


def sync_code() -> tuple[int, list[str]]:
    dst = DEPLOY / "clara_monitor"
    dst.mkdir(parents=True, exist_ok=True)

    # Anything in the bundle that is no longer in the list is stale code being
    # served. Removing it is the point of deriving the copy.
    keep = set(MODULES) | set(PACKAGES)
    removed = []
    for existing in dst.iterdir():
        if existing.name == "__pycache__":
            shutil.rmtree(existing, ignore_errors=True)
            continue
        if existing.name not in keep:
            removed.append(existing.name)
            (shutil.rmtree if existing.is_dir() else Path.unlink)(existing)

    n = 0
    missing = []
    for name in MODULES:
        s = SRC / name
        if not s.exists():
            missing.append(name)
            continue
        shutil.copy2(s, dst / name)
        n += 1
    for pkg, files in PACKAGES.items():
        pd = dst / pkg
        pd.mkdir(exist_ok=True)
        shutil.rmtree(pd / "__pycache__", ignore_errors=True)
        for f in files:
            s = SRC / pkg / f
            if not s.exists():
                missing.append(f"{pkg}/{f}")
                continue
            shutil.copy2(s, pd / f)
            n += 1
    if removed:
        print(f"  removed {len(removed)} stale file(s): {', '.join(removed)}")
    if missing:
        print(f"  !! {len(missing)} listed file(s) do not exist: {missing}")
    return n, missing


def sync_data() -> dict:
    """The SQLite snapshot and the most recent completed cycle."""
    out = {}
    src_db = ROOT / "data" / "monitor.sqlite3"
    dst_db = DEPLOY / "data" / "monitor.sqlite3"
    dst_db.parent.mkdir(parents=True, exist_ok=True)

    # Checkpoint the write-ahead log FIRST. The store runs in WAL mode, so
    # recent writes live in `monitor.sqlite3-wal` until they are folded back
    # into the main file — and copying only the main file silently ships a
    # snapshot that predates them. That is how a bundle ends up missing the
    # very import it was rebuilt for: no error, just older data.
    import sqlite3 as _sq
    con = _sq.connect(str(src_db))
    try:
        con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    finally:
        con.close()

    shutil.copy2(src_db, dst_db)
    # Any stale -wal/-shm beside the destination would be read in preference to
    # the file just copied.
    for suffix in ("-wal", "-shm"):
        stale = dst_db.with_name(dst_db.name + suffix)
        if stale.exists():
            stale.unlink()
    out["db_mb"] = round(dst_db.stat().st_size / 1e6, 2)

    # The newest completed cycle, by the id the store recorded rather than by
    # filename order — c10 sorts before c2 as a string.
    sys.path.insert(0, str(ROOT))
    from clara_monitor.agents.store import IntelStore
    from clara_monitor.config import DB_PATH

    st = IntelStore(DB_PATH)
    try:
        done = [c for c in st.cycles() if c.get("finished_at")]
    finally:
        st.close()
    if not done:
        out["cycle"] = None
        return out

    cid = done[0]["cycle_id"]
    src = ROOT / "reports" / f"intel_{cid}.json"
    if not src.exists():
        out["cycle"] = f"{cid} (no report file)"
        return out

    dst = DEPLOY / "data" / "intel.json"
    payload = json.loads(src.read_text(encoding="utf-8"))
    # Stamped so the page can say when this was computed, not when it was read.
    payload["_bundled_at"] = datetime.now(timezone.utc).isoformat(
        timespec="seconds")
    dst.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    out["cycle"] = cid
    out["cycle_mb"] = round(dst.stat().st_size / 1e6, 2)
    out["actions"] = len(payload.get("actions_needed") or [])
    out["offers"] = len(payload.get("live_competitor_offers") or [])
    return out


def probe() -> list[str]:
    """Drive the real serverless handler against the bundle alone.

    Rendering the pages is not the same as serving them: the handler has its own
    stale-API risk, and the last drift was exactly that — `api/index.py` calling a
    `TrendStore.seed()` that had been gone for weeks. Every route, signed in and
    signed out, before anything is pushed.
    """
    r = subprocess.run([sys.executable, str(ROOT / "tests" / "test_deploy.py"),
                        str(DEPLOY)], capture_output=True, text=True,
                       env={"PYTHONIOENCODING": "utf-8", "PATH": ""})
    tail = (r.stdout or "").rstrip().splitlines()
    print("  " + "\n  ".join(tail[-2:]) if tail else "  no output")
    if r.returncode != 0:
        bad = [l.strip() for l in tail if l.strip().startswith("FAILED:")]
        return bad or (r.stderr or "unknown").strip().splitlines()[-1:]
    return []


def verify() -> list[str]:
    """Import the bundle in isolation and render all three pages from it.

    A deploy that imports a module the bundle does not contain fails on the first
    request, in a log nobody reads. Better to fail here.
    """
    script = (
        "import json,sys,pathlib\n"
        "sys.path.insert(0, sys.argv[1])\n"
        "from clara_monitor import (site, trend_page, reporting,\n"
        "                           trend_store, intel_sections, ops)\n"
        "from clara_monitor import app as opsapp\n"
        "from clara_monitor.store import Store\n"
        "db = pathlib.Path(sys.argv[1])/'data'/'monitor.sqlite3'\n"
        "s = Store(db)\n"
        "run = s.latest_run_id() or 'r1'\n"
        "b = reporting.build_all(s, run, write=False)\n"
        "b['competitors'] = reporting.competitor_cards(s, run)\n"
        "b['offers'] = reporting.offers_report(s, run)\n"
        "b['actions'] = reporting.actions_report(s, run)\n"
        "s.close()\n"
        "ts = trend_store.TrendStore(db)\n"
        "b['trends'] = trend_store.build(ts)\n"
        "ts.close()\n"
        "p = pathlib.Path(sys.argv[1])/'data'/'intel.json'\n"
        "b['intel'] = json.loads(p.read_text(encoding='utf-8')) if p.exists() else {}\n"
        "d = intel_sections.decision_items(b, b['trends'])\n"
        "print('prices   ', len(site.render(b)))\n"
        "print('trends   ', len(trend_page.render(b['trends'], d)))\n"
        "print('decisions raised', len(d))\n"
        # The application itself, from the bundle alone. A missing ops/ or
        # app/ file is a route that 500s only in production, so it is
        # caught here rather than by the first visitor.
        "db = ops.connect(pathlib.Path(sys.argv[1])/'data'/'monitor.sqlite3')\n"
        "u = {'username':'probe','display_name':'p','is_admin':True,"
        "'role':'admin'}\n"
        "for route in ('/overview','/products','/competitors',"
        "'/actions','/requests','/offers','/admin/audit',"
        "'/admin/system'):\n"
        "    r = opsapp.handle(opsapp.Request(method='GET', path=route,"
        " user=u, db=db))\n"
        "    assert r.status == 200, (route, r.status)\n"
        "print('app', '8 routes render')\n"
        "print('ops products', db.value('SELECT COUNT(*) FROM ops_product'))\n"
        "db.close()\n"
    )
    r = subprocess.run([sys.executable, "-c", script, str(DEPLOY)],
                       capture_output=True, text=True, cwd=str(DEPLOY),
                       env={"PYTHONIOENCODING": "utf-8", "PATH": ""})
    print((r.stdout or "").rstrip())
    if r.returncode != 0:
        return [(r.stderr or "").strip().splitlines()[-1]]
    return []


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--deploy", action="store_true",
                    help="run `vercel --prod` after a clean rebuild")
    args = ap.parse_args()

    print("code")
    n, missing = sync_code()
    print(f"  {n} file(s) copied")

    print("data")
    info = sync_data()
    for k, v in info.items():
        print(f"  {k}: {v}")

    print("verify (importing the bundle on its own)")
    errs = verify()
    if not errs:
        print("  the application and the legacy pages render from "
              "the bundle alone")
        print("serve (driving the real handler on every route)")
        errs = probe()
    if errs or missing:
        for e in errs:
            print(f"  !! {e}")
        print("\nbundle is not deployable; fix the above first.")
        return 1

    if args.deploy:
        print("\nvercel --prod")
        r = subprocess.run(["vercel", "--prod", "--yes"], cwd=str(DEPLOY),
                           shell=True)
        return r.returncode
    print("\nready. `python sync_deploy.py --deploy` to push it.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
