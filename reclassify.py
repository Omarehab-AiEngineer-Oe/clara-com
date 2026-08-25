"""Apply the corrected classification to the store, and retire the pairings it
invalidates.

A shampoo that used to be classified as a device had been compared against a
2,299-riyal Airwrap. Fixing the classifier changes which competitors that product
is assigned, so any stored match against a competitor that is no longer assigned
is out of scope. Those are retired — the match row is dropped and a match_event
records why, so the trail survives — rather than left on the page as a comparison
nobody would stand behind.
"""

import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from clara_monitor import catalog, competitors as comp
from clara_monitor.config import DB_PATH
from clara_monitor.store import Store

APPLY = "--apply" in sys.argv

store = Store(DB_PATH)
before = {p.product_id: (p.segment, p.category, p.fmt) for p in store.get_products()}
fresh = catalog.load_from_seed()

reclassified, retired = [], []

for p in fresh:
    old = before.get(p.product_id)
    if old and old != (p.segment, p.category, p.fmt):
        reclassified.append((p.name, old, (p.segment, p.category, p.fmt)))

    assigned = comp.targets_for(p.fmt, p.category, p.segment, limit=2)
    for m in store.get_matches_for_product(p.product_id):
        if m.competitor_key not in assigned:
            retired.append((p.name, m.competitor_key, m.status,
                            p.segment, p.category))

print(f"reclassified products : {len(reclassified)}")
for name, old, new in reclassified[:20]:
    print(f"  {name[:44]:46} {old[0]}/{old[1]} -> {new[0]}/{new[1]}")

print(f"\nout-of-scope matches  : {len(retired)}")
for name, key, status, seg, cat in retired[:20]:
    print(f"  {name[:40]:42} x {key:12} ({status}) — now {seg}/{cat}")

if APPLY:
    for p in fresh:
        store.upsert_product(p)
        store.set_targets(p.product_id,
                          comp.targets_for(p.fmt, p.category, p.segment, limit=2))
    for name, key, status, seg, cat in retired:
        pid = next(x.product_id for x in fresh if x.name == name)
        store.add_match_event(
            "reclassify", pid, key, "retired", status, None,
            f"competitor no longer assigned after the product was reclassified "
            f"to {seg}/{cat}", [])
        store.db.execute(
            "DELETE FROM match WHERE clara_product_id=? AND competitor_key=?",
            (pid, key))
        store.db.execute(
            "DELETE FROM observation WHERE clara_product_id=? AND competitor_key=?",
            (pid, key))
    store.db.commit()
    print(f"\napplied: {len(fresh)} products updated, {len(retired)} pairings retired")
    print("history and match_events are untouched — the trail is intact")
else:
    print("\ndry run. add --apply to write")

store.close()
