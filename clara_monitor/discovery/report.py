"""The discovery dashboard: what grew, what was refused, and why.

A self-expanding system that cannot explain itself is not an asset. Every block
here answers a question a person will actually ask when the registry has doubled
and they want to know whether to trust it:

    how many sources, and how many did we choose versus find
    which candidates are waiting, and which were refused and for what
    which subjects came out of the uncategorised pile
    is the blind spot actually shrinking
    who found whom
"""

from __future__ import annotations

import json

from .config import (ACTIVE, CANDIDATE, DISABLED, DISCOVERED, MERGED, REJECTED,
                     SEED, VALIDATED)


def source_growth(store) -> str:
    c = store.source_counts()
    active = store.by_status(ACTIVE)
    seeds = [s for s in active if s["source_type"] == SEED]
    found = [s for s in active if s["source_type"] == DISCOVERED]
    L = ["SOURCE GROWTH", ""]
    L.append(f"  Seed sources:        {len(seeds):4}")
    L.append(f"  Discovered active:   {len(found):4}")
    L.append(f"  Active total:        {len(active):4}")
    L.append(f"  Pending candidates:  {c.get(VALIDATED, 0):4}")
    L.append(f"  Rejected:            {c.get(REJECTED, 0):4}")
    L.append(f"  Disabled:            {c.get(DISABLED, 0):4}")
    if found:
        L.append("")
        L.append("  Discovered and activated:")
        for s in found:
            L.append(f"    {s['name'][:26]:28} {s['domain'][:26]:28} "
                     f"q={s['quality_score']:.2f}  depth {s['depth']}")
    pending = store.by_status(VALIDATED)
    if pending:
        L.append("")
        L.append("  Waiting (validated, not scanned):")
        for s in pending:
            L.append(f"    {s['domain'][:30]:32} q={s['quality_score']:.2f}  "
                     f"{(s['reject_reason'] or '')[:44]}")
    rejected = store.by_status(REJECTED)
    if rejected:
        L.append("")
        L.append("  Refused, with the reason:")
        for s in rejected[:12]:
            L.append(f"    {s['domain'][:30]:32} {(s['reject_reason'] or '')[:60]}")
    return "\n".join(L)


def topic_growth(store, seed_count: int) -> str:
    c = store.topic_counts()
    active = store.active_topics()
    hist = store.classification_history(3)
    L = ["TOPIC GROWTH", ""]
    L.append(f"  Seed topics:         {seed_count:4}")
    L.append(f"  Discovered active:   {c.get(ACTIVE, 0):4}")
    L.append(f"  Candidates:          {c.get(CANDIDATE, 0):4}")
    L.append(f"  Merged into existing:{c.get(MERGED, 0):4}")
    L.append(f"  Rejected:            {c.get(REJECTED, 0):4}")
    if active:
        L.append("")
        L.append("  Discovered subjects now classifying:")
        for t in active:
            L.append(f"    {t['label'][:34]:36} {t['signal_count']:3} signals / "
                     f"{t['publisher_count']} pubs / {t['days_seen']}d  "
                     f"precision {t.get('precision_est') or 0:.0%}")
    if hist:
        L.append("")
        L.append("  Uncategorised, run over run:")
        for h in reversed(hist):
            L.append(f"    {str(h['at'])[:16]}  "
                     f"{h['uncategorised_before']:3} -> "
                     f"{h['uncategorised_after']:3} of {h['signals_total']:3}")
    return "\n".join(L)


def discovery_chain(store) -> str:
    """Who found whom. Indented by hop distance from a hand-chosen seed."""
    rows = store.discovery_chain()
    by_parent: dict = {}
    seeds = []
    for r in rows:
        prov = r.get("discovered_from") or {}
        parent = prov.get("parent_publisher") or prov.get("source_key")
        if r["source_type"] == SEED:
            seeds.append(r)
        else:
            by_parent.setdefault(parent or "(unattributed)", []).append(r)

    L = ["DISCOVERY CHAIN", ""]
    if not by_parent:
        L.append("  Nothing discovered yet — every source is hand-chosen.")
        return "\n".join(L)

    for parent, children in sorted(by_parent.items(),
                                   key=lambda kv: -len(kv[1])):
        L.append(f"  {parent}")
        for ch in children:
            mark = {ACTIVE: "active", VALIDATED: "waiting",
                    REJECTED: "refused", CANDIDATE: "candidate"}.get(
                        ch["status"], ch["status"])
            q = ch.get("quality_score")
            L.append(f"    -> {ch['domain'][:30]:32} {mark:10} "
                     f"{'q=%.2f' % q if q is not None else ''}")
    return "\n".join(L)


def full_report(store, seed_source_count: int, seed_topic_count: int) -> str:
    return "\n\n".join([
        source_growth(store),
        topic_growth(store, seed_topic_count),
        discovery_chain(store),
    ])
