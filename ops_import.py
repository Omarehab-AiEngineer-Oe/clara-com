#!/usr/bin/env python
"""Fold a completed collection run into the durable operational database.

    python ops_import.py                       # the latest run, locally
    python ops_import.py --run-id r2
    DATABASE_URL=postgres://... python ops_import.py     # into the hosted store
    python ops_import.py --status              # what is in there now

This is the seam section 9.2 asks for: "import completed scans into the durable
database or write them there directly; redeployment must never reset operational
records."

The separation it implements is the whole point. Collection is slow, contacts
competitor sites, and is bound by the access policy, so it runs on a machine with
a real disk. The operational database holds the results *and* the decisions people
made about them, and it lives somewhere that survives a deploy. This moves the
first into the second without letting the first overwrite the second.

**A human decision is never overwritten by an automated one.** A match somebody
confirmed stays confirmed even if tonight's scan proposes something else; where
the scan disagrees, an Action is raised instead. That is the correct outcome — a
scan contradicting a person is exactly the thing a person should look at.

**Importing the same run twice does nothing the second time.** So this is safe in
a deploy script, a cron job, or a nervous second run by hand.
"""

from __future__ import annotations

import argparse
import io
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8",
                              errors="replace")

from clara_monitor import ops, reporting
from clara_monitor.config import DB_PATH
from clara_monitor.ops.ingest import Importer, sync_users
from clara_monitor.ops.schema import schema_version
from clara_monitor.store import Store


def collection_bundle(run_id: str = "") -> tuple[dict, str]:
    """Build the report bundle the importer reads, from the collection store."""
    store = Store(DB_PATH)
    try:
        run = run_id or store.latest_run_id() or "r1"
        bundle = reporting.build_all(store, run, write=False)
        bundle["competitors"] = reporting.competitor_cards(store, run)
        bundle["offers"] = reporting.offers_report(store, run)
        bundle["actions"] = reporting.actions_report(store, run)
    finally:
        store.close()
    return bundle, run


def show_status(db) -> None:
    e = ops.engine_status()
    print(f"engine   {e['engine']} — {e['target']}")
    print(f"durable  {'yes' if e.get('durable') else 'no'}")
    if not e.get("durable"):
        print(f"         {e.get('why', '')}")
    print(f"schema   v{schema_version(db)}")
    rows = [
        ("Clara products", "ops_product"), ("Competitors", "ops_competitor"),
        ("Matches", "ops_match"), ("Observations", "ops_observation"),
        ("Sources", "ops_source"), ("Feeds & APIs", "ops_feed"),
        ("Actions", "ops_action"), ("Requests", "ops_request"),
        ("Conversations", "ops_conversation"), ("Audit events", "ops_audit"),
        ("Imports", "ops_import"),
    ]
    print("")
    for label, table in rows:
        if db.table_exists(table):
            print(f"  {label:<16} {db.value(f'SELECT COUNT(*) FROM {table}', (), 0)}")
    last = db.row("SELECT * FROM ops_import ORDER BY at DESC")
    if last:
        print(f"\nlast import      run {last.get('run_id')} at {last.get('at')} "
              f"by {last.get('actor')}")
    else:
        print("\nno collection run has been imported yet")


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Import a collection run into the operational database.")
    ap.add_argument("--run-id", default="",
                    help="which run to import; the latest one by default")
    ap.add_argument("--status", action="store_true",
                    help="show what the operational database holds, and exit")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    db = ops.connect(DB_PATH, verbose=not args.quiet)
    try:
        engine = ops.engine_status()
        if not args.quiet:
            print(f"target: {engine['engine']} — {engine['target']}")
            if not engine.get("durable"):
                print("  note: this is the local file, not a hosted store. Set "
                      "DATABASE_URL to import into managed Postgres.")

        if args.status:
            show_status(db)
            return 0

        bundle, run = collection_bundle(args.run_id)
        products = len((bundle.get("price") or {}).get("products") or [])
        if not args.quiet:
            print(f"run {run}: {products} products in the collection store")

        out = Importer(db).import_bundle(bundle, run_id=run)
        if out.get("skipped"):
            print(f"nothing to do: {out.get('why')}")
            return 0

        from clara_monitor.auth import Auth
        auth = Auth(DB_PATH)
        try:
            n = sync_users(db, auth.list_users())
        finally:
            auth.close()

        print("imported:")
        for key in ("products", "competitors", "matches_new", "matches_updated",
                    "matches_held", "observations", "sources", "actions",
                    "conflicts"):
            if out.get(key):
                print(f"  {key.replace('_', ' '):<18} {out[key]}")
        if n:
            print(f"  {'users mirrored':<18} {n}")
        if out.get("matches_held"):
            print(f"\n  {out['matches_held']} match(es) were left as a person set "
                  f"them. An import never overwrites a human decision.")
        if out.get("conflicts"):
            print(f"  {out['conflicts']} disagreement(s) between the run and a "
                  f"confirmed match were raised as Actions rather than applied.")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
