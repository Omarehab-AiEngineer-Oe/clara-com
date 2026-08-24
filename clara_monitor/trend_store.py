"""Persistence for live trend scans, and the accumulation that makes them useful.

A single RSS scan sees only a recent window — ten to thirty items per feed. That
is enough to know what published today and nowhere near enough to say whether a
subject is rising or fading. So nothing here is computed from one scan: every
signal is stored, and every topic is measured across everything ever collected.

That accumulation is what makes three things honest:

* **Stage.** Rising and declining are comparisons, so they need a before. With one
  scan the best a system can say is "recent" or "old"; with history it can say
  this week is heavier than the weeks before it, and show the counts.
* **Last updated.** The page can distinguish *first seen*, *last confirmed* and
  *last changed*, which are three different facts that one timestamp blurs. A
  topic re-confirmed today with nothing new is not the same as one that gained
  four publishers today.
* **Absence.** A topic that stops appearing does not vanish. It ages visibly and
  eventually reads as declining, which is information — silently dropping it would
  look like it never existed.

Signals are insert-once and keyed by URL, so re-reading a feed never duplicates
anything and `first_seen_at` survives every later scan.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import trend_ideas as ideas, trend_sources as ts
from .agents import trend_collector as tc

SCHEMA = """
CREATE TABLE IF NOT EXISTS tscan (
  scan_id     TEXT PRIMARY KEY,
  started_at  TEXT,
  finished_at TEXT,
  feeds_tried INTEGER,
  feeds_read  INTEGER,
  signals_new INTEGER,
  signals_total INTEGER,
  topics      INTEGER,
  notes       TEXT
);

-- One row per article or query, insert-once. The URL is the identity, so a feed
-- re-read never duplicates and first_seen_at is never overwritten.
CREATE TABLE IF NOT EXISTS tsignal (
  url          TEXT PRIMARY KEY,
  source_key   TEXT,
  publisher    TEXT,
  kind         TEXT,
  market       TEXT,
  weight       INTEGER,
  title        TEXT,
  summary      TEXT,
  published_at TEXT,
  search_volume TEXT,
  driven_by    TEXT,
  topics_json  TEXT,
  first_seen_at TEXT,
  last_seen_at  TEXT,
  scan_id      TEXT
);
CREATE INDEX IF NOT EXISTS ix_signal_seen ON tsignal(first_seen_at);

CREATE TABLE IF NOT EXISTS ttopic (
  key            TEXT PRIMARY KEY,
  label          TEXT,
  stage          TEXT,
  spread         TEXT,
  signal_count   INTEGER,
  publisher_count INTEGER,
  markets_json   TEXT,
  confidence     TEXT,
  first_seen_at  TEXT,
  last_confirmed_at TEXT,
  last_changed_at   TEXT,
  last_change_kind  TEXT,
  last_change_note  TEXT,
  payload_json   TEXT
);

CREATE TABLE IF NOT EXISTS ttopic_event (
  id        INTEGER PRIMARY KEY AUTOINCREMENT,
  topic_key TEXT,
  scan_id   TEXT,
  at        TEXT,
  kind      TEXT,
  detail    TEXT
);
CREATE INDEX IF NOT EXISTS ix_tevent_topic ON ttopic_event(topic_key);

CREATE TABLE IF NOT EXISTS tsource_status (
  key         TEXT PRIMARY KEY,
  publisher   TEXT,
  url         TEXT,
  ok          INTEGER,
  signal      TEXT,
  items       INTEGER,
  kept        INTEGER,
  checked_at  TEXT,
  what_to_do  TEXT
);
"""

CHANGE_FIRST = "first_seen"
CHANGE_STAGE = "stage_moved"
CHANGE_EVIDENCE = "new_evidence"
CHANGE_SPREAD = "spread_widened"
CHANGE_QUIET = "went_quiet"

CHANGE_LABEL = {
    CHANGE_FIRST: "first seen",
    CHANGE_STAGE: "stage moved",
    CHANGE_EVIDENCE: "new evidence",
    CHANGE_SPREAD: "spread wider",
    CHANGE_QUIET: "gone quiet",
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds")


def _parse(stamp: str):
    if not stamp:
        return None
    try:
        dt = datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def ago(stamp: str, now: datetime | None = None) -> str:
    """A relative clock counting from a real timestamp.

    Returns "unknown" rather than a friendly guess when there is nothing to count
    from. "Just now" on a missing date is the most quietly wrong thing a freshness
    label can say.
    """
    dt = _parse(stamp)
    if not dt:
        return "unknown"
    secs = ((now or _now()) - dt).total_seconds()
    if secs < 90:
        return "just now"
    if secs < 3600:
        return f"{int(secs // 60)} min ago"
    if secs < 86400:
        h = int(secs // 3600)
        return f"{h} hour{'s' if h != 1 else ''} ago"
    days = int(secs // 86400)
    if days == 1:
        return "yesterday"
    if days < 7:
        return f"{days} days ago"
    if days < 30:
        w = days // 7
        return f"{w} week{'s' if w != 1 else ''} ago"
    m = days // 30
    return f"{m} month{'s' if m != 1 else ''} ago"


def when(stamp: str) -> str:
    """The absolute day and time, for a reader who wants the actual date."""
    dt = _parse(stamp)
    return dt.strftime("%a %d %b %Y, %H:%M UTC") if dt else "unknown"


def freshness_bucket(stamp: str, now: datetime | None = None) -> str:
    dt = _parse(stamp)
    if not dt:
        return "unknown"
    secs = ((now or _now()) - dt).total_seconds()
    if secs < 3600:
        return "last_hour"
    if secs < 86400:
        return "today"
    if secs < 7 * 86400:
        return "this_week"
    if secs < 30 * 86400:
        return "this_month"
    return "older"


# A badge is only ever set from a stored timestamp, so it cannot appear on a
# subject that has not actually moved.
NEW_WITHIN_HOURS = 48
UPDATED_WITHIN_DAYS = 7

MOMENTUM = {
    "emerging": ("\u2197", "building"),
    "rising": ("\u2197", "rising"),
    "viral": ("\u2191", "spiking"),
    "mainstream": ("\u2192", "steady"),
    "declining": ("\u2198", "cooling"),
}


def badge_for(topic: dict, now: datetime) -> tuple[str, str]:
    """(code, label) — NEW, UPDATED, or nothing.

    NEW wins over UPDATED: a subject seen for the first time yesterday is new,
    not updated, even though both are technically true.
    """
    first = _parse(topic.get("first_seen_at"))
    changed = _parse(topic.get("last_changed_at"))
    if first and (now - first) <= timedelta(hours=NEW_WITHIN_HOURS):
        return "NEW", "New"
    if changed and (now - changed) <= timedelta(days=UPDATED_WITHIN_DAYS):
        return "UPDATED", "Updated"
    return "", ""


def related_for(topic: dict, others: list[dict], limit: int = 4) -> list[dict]:
    """The nearest other subjects, and why each one is near.

    Ranked by category, then shared markets, then shared publishers. The reason
    is returned with the match because "related" with no explanation is the kind
    of recommendation nobody trusts twice.
    """
    mine_m = set(topic.get("markets") or [])
    mine_p = set(topic.get("publishers") or [])
    scored = []
    for o in others:
        if o.get("key") == topic.get("key"):
            continue
        score, why = 0, []
        if o.get("category") and o.get("category") == topic.get("category"):
            score += 3
            why.append("same category")
        shared_m = mine_m & set(o.get("markets") or [])
        if shared_m:
            score += 2 * len(shared_m)
            why.append(f"{len(shared_m)} shared market(s)")
        shared_p = mine_p & set(o.get("publishers") or [])
        if shared_p:
            score += len(shared_p)
            why.append(f"{len(shared_p)} shared publisher(s)")
        if not score:
            continue
        scored.append((score, {
            "key": o.get("key"), "label": o.get("label"),
            "stage": o.get("stage"), "icon": o.get("icon"),
            "why": ", ".join(why),
        }))
    scored.sort(key=lambda x: -x[0])
    return [d for _, d in scored[:limit]]


class TrendStore:
    def __init__(self, path: Path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(path), check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)
        self.db.commit()

    def close(self) -> None:
        self.db.close()

    # ---------------- scans ----------------

    def last_scan(self) -> dict | None:
        r = self.db.execute(
            "SELECT * FROM tscan WHERE finished_at IS NOT NULL "
            "ORDER BY finished_at DESC LIMIT 1").fetchone()
        return dict(r) if r else None

    def scans(self, limit: int = 30) -> list[dict]:
        return [dict(r) for r in self.db.execute(
            "SELECT * FROM tscan ORDER BY started_at DESC LIMIT ?", (limit,))]

    def scan_count(self) -> int:
        return self.db.execute("SELECT COUNT(*) FROM tscan").fetchone()[0]

    def signal_count(self) -> int:
        return self.db.execute("SELECT COUNT(*) FROM tsignal").fetchone()[0]

    # ---------------- ingest ----------------

    def record(self, result: dict) -> dict:
        """Store one scan's output and recompute every topic over all history."""
        scan_id = result["scan_id"]
        stamp = _iso(_now())

        self.db.execute(
            "INSERT OR REPLACE INTO tscan (scan_id, started_at) VALUES (?,?)",
            (scan_id, result.get("fetched_at") or stamp))

        new_signals = 0
        for s in result["signals"]:
            url = s["url"]
            if not url:
                continue
            row = self.db.execute(
                "SELECT first_seen_at FROM tsignal WHERE url=?", (url,)).fetchone()
            if row:
                self.db.execute(
                    "UPDATE tsignal SET last_seen_at=?, scan_id=? WHERE url=?",
                    (stamp, scan_id, url))
                continue
            new_signals += 1
            self.db.execute(
                """INSERT INTO tsignal
                   (url, source_key, publisher, kind, market, weight, title,
                    summary, published_at, search_volume, driven_by, topics_json,
                    first_seen_at, last_seen_at, scan_id)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (url, s["source_key"], s["publisher"], s["kind"], s["market"],
                 s["weight"], s["title"], s["summary"], s["published_at"],
                 s["search_volume"], json.dumps(s["driven_by"], ensure_ascii=False),
                 json.dumps(s["topics"]), stamp, stamp, scan_id))

        for st in result["sources"]:
            self.db.execute(
                """INSERT OR REPLACE INTO tsource_status
                   (key, publisher, url, ok, signal, items, kept, checked_at,
                    what_to_do) VALUES (?,?,?,?,?,?,?,?,?)""",
                (st["key"], st["publisher"], st["url"], 1 if st["ok"] else 0,
                 st["signal"], st["items"], st["kept"], st["checked_at"],
                 st["what_to_do"]))
        self.db.commit()

        # Re-tag first: the vocabulary may have widened since these signals
        # were collected, and a topic that exists in the file but not in any
        # stored row is a subject the page cannot see.
        self.retag()

        # Recompute over EVERYTHING, not just this scan.
        accumulated = self._all_signals()
        topics = tc.build_topics(accumulated, stamp)
        changes = self._apply_topics(topics, scan_id, stamp)

        self.db.execute(
            """UPDATE tscan SET finished_at=?, feeds_tried=?, feeds_read=?,
               signals_new=?, signals_total=?, topics=? WHERE scan_id=?""",
            (stamp, result["counts"]["feeds_tried"], result["counts"]["feeds_read"],
             new_signals, len(accumulated), len(topics), scan_id))
        self.db.commit()

        return {"scan_id": scan_id, "new_signals": new_signals,
                "total_signals": len(accumulated), "topics": len(topics),
                "changes": changes}

    def load_discovered(self) -> int:
        """Register the subjects discovery activated, before any tagging.

        Retagging against the seed-only vocabulary would leave every discovered
        subject matching nothing — the exact blind spot the loop exists to
        close. Imported lazily so the trend store keeps working in a checkout
        where discovery has never run.
        """
        try:
            from .discovery.store import DiscoveryStore
        except Exception:
            return 0
        try:
            ds = DiscoveryStore(self.db_path) if hasattr(self, "db_path") else None
        except Exception:
            ds = None
        if ds is None:
            from .config import DB_PATH
            try:
                ds = DiscoveryStore(DB_PATH)
            except Exception:
                return 0
        try:
            rows = ds.active_topics()
            hosts = {r.get("domain") for r in ds.active_sources()}
        finally:
            ds.close()
        n = ts.register_dynamic(rows)
        ts.register_dynamic_hosts(hosts)
        return n

    def retag(self) -> dict:
        """Re-match every stored signal against the current vocabulary.

        Topics are attached at ingest, which means a signal collected last week
        carries last week's vocabulary. Widening the pattern set therefore does
        nothing to history until this runs — 217 signals would sit there matching
        20 subjects while the file defined 86.

        Re-tagging never changes what a signal *is*: the title, the publisher and
        the date are untouched. It only re-answers "which subjects is this
        evidence for", which is a question about the vocabulary, not about the
        signal.
        """
        discovered = self.load_discovered()
        changed = 0
        rows = self.db.execute(
            "SELECT url, title, summary, driven_by, topics_json FROM tsignal"
        ).fetchall()
        for r in rows:
            blob = " ".join([r["title"] or "", r["summary"] or "",
                             " ".join(json.loads(r["driven_by"] or "[]"))])
            keys = sorted(t.key for t in ts.topics_for(blob))
            before = sorted(json.loads(r["topics_json"] or "[]"))
            if keys == before:
                continue
            self.db.execute("UPDATE tsignal SET topics_json=? WHERE url=?",
                            (json.dumps(keys), r["url"]))
            changed += 1
        self.db.commit()
        return {"signals": len(rows), "retagged": changed,
                "discovered_topics_loaded": discovered}

    def _all_signals(self) -> list[dict]:
        out = []
        for r in self.db.execute("SELECT * FROM tsignal"):
            d = dict(r)
            d["topics"] = json.loads(d.pop("topics_json") or "[]")
            d["driven_by"] = json.loads(d.pop("driven_by") or "[]")
            out.append(d)
        return out

    def _apply_topics(self, topics: list[dict], scan_id: str,
                      stamp: str) -> list[dict]:
        """Write the recomputed topics and record exactly what moved."""
        changes = []
        seen_keys = set()

        for t in topics:
            key = t["key"]
            seen_keys.add(key)
            prev = self.db.execute("SELECT * FROM ttopic WHERE key=?",
                                   (key,)).fetchone()

            kind, note = "", ""
            if not prev:
                kind, note = CHANGE_FIRST, (
                    f"first appeared with {t['signal_count']} item(s) from "
                    f"{t['publisher_count']} publisher(s)")
            elif prev["stage"] != t["stage"]:
                kind = CHANGE_STAGE
                note = f"{prev['stage']} to {t['stage']} — {t['stage_why']}"
            elif (prev["signal_count"] or 0) < t["signal_count"]:
                gained = t["signal_count"] - (prev["signal_count"] or 0)
                kind = CHANGE_EVIDENCE
                note = (f"{gained} new item(s); now {t['publisher_count']} "
                        f"publisher(s)")
            elif prev["spread"] != t["spread"]:
                kind = CHANGE_SPREAD
                note = f"{prev['spread']} to {t['spread']}"

            first = prev["first_seen_at"] if prev else stamp
            last_changed = (stamp if kind
                            else (prev["last_changed_at"] if prev else stamp))
            change_kind = kind or (prev["last_change_kind"] if prev else "")
            change_note = note or (prev["last_change_note"] if prev else "")

            self.db.execute(
                """INSERT OR REPLACE INTO ttopic
                   (key,label,stage,spread,signal_count,publisher_count,
                    markets_json,confidence,first_seen_at,last_confirmed_at,
                    last_changed_at,last_change_kind,last_change_note,payload_json)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (key, t["label"], t["stage"], t["spread"], t["signal_count"],
                 t["publisher_count"], json.dumps(t["markets"]), t["confidence"],
                 first, stamp, last_changed, change_kind, change_note,
                 json.dumps(t, ensure_ascii=False)))

            if kind:
                self.db.execute(
                    """INSERT INTO ttopic_event (topic_key, scan_id, at, kind, detail)
                       VALUES (?,?,?,?,?)""", (key, scan_id, stamp, kind, note))
                changes.append({"topic": t["label"], "kind": kind, "note": note})

        # A topic with no evidence this time is not deleted — it ages in place.
        for r in self.db.execute("SELECT key,label,last_confirmed_at FROM ttopic"):
            if r["key"] in seen_keys:
                continue
            age = _parse(r["last_confirmed_at"])
            if age and (_now() - age) > timedelta(days=30):
                self.db.execute(
                    "UPDATE ttopic SET stage=?, last_change_kind=?, "
                    "last_change_note=?, last_changed_at=? WHERE key=?",
                    ("declining", CHANGE_QUIET,
                     "no new evidence for over a month", stamp, r["key"]))
                changes.append({"topic": r["label"], "kind": CHANGE_QUIET,
                                "note": "no new evidence for over a month"})

        self.db.commit()
        return changes

    # ---------------- read ----------------

    def topics(self) -> list[dict]:
        out = []
        for r in self.db.execute("SELECT * FROM ttopic"):
            d = json.loads(r["payload_json"] or "{}")
            d.update({
                "first_seen_at": r["first_seen_at"],
                "last_confirmed_at": r["last_confirmed_at"],
                "last_changed_at": r["last_changed_at"],
                "last_change_kind": r["last_change_kind"],
                "last_change_note": r["last_change_note"],
                "stage": r["stage"], "spread": r["spread"],
            })
            out.append(d)
        return out

    def events(self, limit: int = 60) -> list[dict]:
        return [dict(r) for r in self.db.execute(
            "SELECT * FROM ttopic_event ORDER BY id DESC LIMIT ?", (limit,))]

    def sources(self) -> list[dict]:
        return [dict(r) for r in self.db.execute(
            "SELECT * FROM tsource_status ORDER BY ok DESC, kept DESC, publisher")]

    def events_by_topic(self) -> dict:
        """Every recorded change, grouped by the topic it belongs to.

        The page shows a topic's own history inside that topic rather than in a
        shared log, so the grouping happens here once instead of in the renderer.
        """
        out: dict = {}
        for r in self.db.execute(
                "SELECT * FROM ttopic_event ORDER BY id DESC"):
            d = dict(r)
            out.setdefault(d["topic_key"], []).append(d)
        return out

    def uncategorised(self, limit: int = 120) -> list[dict]:
        """Signals that matched no topic.

        Kept visible because the gap between "signals collected" and "signals
        that map to a subject" is real, and hiding it would make the page look
        like it read less than it did. It is also where the next topic starts.
        """
        out = []
        for r in self.db.execute(
                "SELECT * FROM tsignal WHERE topics_json IN ('[]','', 'null') "
                "OR topics_json IS NULL "
                "ORDER BY COALESCE(published_at, first_seen_at) DESC LIMIT ?",
                (limit,)):
            d = dict(r)
            d.pop("topics_json", None)
            d["driven_by"] = json.loads(d.pop("driven_by") or "[]")
            out.append(d)
        return out

    def recent_signals(self, limit: int = 40) -> list[dict]:
        out = []
        for r in self.db.execute(
                "SELECT * FROM tsignal ORDER BY COALESCE(published_at, first_seen_at) "
                "DESC LIMIT ?", (limit,)):
            d = dict(r)
            d["topics"] = json.loads(d.pop("topics_json") or "[]")
            d["driven_by"] = json.loads(d.pop("driven_by") or "[]")
            out.append(d)
        return out


# --------------------------------------------------------------------------

def build(store: TrendStore) -> dict:
    """Assemble what the trends page renders."""
    now = _now()
    topics = store.topics()
    scan = store.last_scan() or {}
    sources = store.sources()
    events = store.events()

    events_by_topic = store.events_by_topic()
    for t in topics:
        own = events_by_topic.get(t.get("key")) or []
        t["history"] = [{
            "kind": e.get("kind"),
            "label": CHANGE_LABEL.get(e.get("kind"), e.get("kind")),
            "detail": e.get("detail"),
            "at": e.get("at"),
            "ago": ago(e.get("at"), now),
            "when": when(e.get("at")),
        } for e in own]
        t["ago"] = ago(t.get("last_confirmed_at"), now)
        t["checked_when"] = when(t.get("last_confirmed_at"))
        t["changed_ago"] = ago(t.get("last_changed_at"), now)
        t["changed_when"] = when(t.get("last_changed_at"))
        t["first_when"] = when(t.get("first_seen_at"))
        t["first_ago"] = ago(t.get("first_seen_at"), now)
        t["bucket"] = freshness_bucket(t.get("last_changed_at"), now)
        t["newest_ago"] = ago(t.get("newest_published_at"), now)
        t["change_label"] = CHANGE_LABEL.get(t.get("last_change_kind"), "")
        # Agent-generated, and every consumer of these labels them as such.
        t["ideas"] = ideas.content_ideas(t)
        t["commercial"] = ideas.commercial_ideas(t)
        t["platform"] = ideas.best_platform(t)
        t["audience"] = ideas.audience(t)
        t["badge"], t["badge_label"] = badge_for(t, now)
        arrow, word = MOMENTUM.get(t.get("stage"), ("\u2192", "steady"))
        t["momentum"] = arrow
        t["momentum_label"] = word
        for e in t.get("evidence") or []:
            e["ago"] = ago(e.get("published_at"), now)
            e["when"] = when(e.get("published_at"))

    # Relations are computed after every topic has its own fields, so a related
    # chip can show the other subject's stage without a second pass.
    for t in topics:
        t["related"] = related_for(t, topics)

    stage_rank = {s: i for i, s in enumerate(tc.STAGE_ORDER)}
    topics.sort(key=lambda t: (stage_rank.get(t.get("stage"), 9),
                               -(t.get("publisher_count") or 0),
                               -(t.get("signal_count") or 0)))

    uncat = store.uncategorised()
    for u in uncat:
        u["ago"] = ago(u.get("published_at") or u.get("first_seen_at"), now)
        u["when"] = when(u.get("published_at") or u.get("first_seen_at"))
        u["market_label"] = ts.MARKET_LABEL.get(u.get("market"), u.get("market"))

    feed = store.recent_signals(40)
    for s in feed:
        s["ago"] = ago(s.get("published_at") or s.get("first_seen_at"), now)
        s["when"] = when(s.get("published_at") or s.get("first_seen_at"))
        s["market_label"] = ts.MARKET_LABEL.get(s.get("market"), s.get("market"))

    labels = {t["key"]: t.get("label") for t in topics}
    for e in events:
        e["ago"] = ago(e.get("at"), now)
        e["when"] = when(e.get("at"))
        e["label"] = CHANGE_LABEL.get(e.get("kind"), e.get("kind"))
        # Events store the topic key; a reader needs the name.
        e["topic_label"] = labels.get(e.get("topic_key"), e.get("topic_key"))

    for s in sources:
        s["ago"] = ago(s.get("checked_at"), now)
        s["when"] = when(s.get("checked_at"))

    market_counts: dict[str, int] = {}
    for t in topics:
        for m in t.get("markets") or []:
            market_counts[m] = market_counts.get(m, 0) + 1

    by_stage: dict[str, int] = {}
    for t in topics:
        by_stage[t["stage"]] = by_stage.get(t["stage"], 0) + 1

    changed_recently = [t for t in topics
                        if t.get("bucket") in ("last_hour", "today", "this_week")]

    return {
        "generated_at": _iso(now),
        "generated_when": when(_iso(now)),
        "scan": scan,
        "scan_ago": ago(scan.get("finished_at"), now) if scan else "never",
        "scan_when": when(scan.get("finished_at")) if scan else "never",
        "topics": topics,
        "uncategorised": uncat,
        "feed": feed,
        "events": events,
        "sources": sources,
        "market_counts": market_counts,
        "market_order": [m for m in ts.MARKET_ORDER if m in market_counts],
        "market_label": ts.MARKET_LABEL,
        "by_stage": by_stage,
        "counts": {
            "topics": len(topics),
            "signals": store.signal_count(),
            "scans": store.scan_count(),
            "feeds_read": (scan.get("feeds_read") or 0) if scan else 0,
            "feeds_tried": (scan.get("feeds_tried") or 0) if scan else 0,
            "markets": len(market_counts),
            "publishers": len({p for t in topics for p in t.get("publishers") or []}),
            "changed_recently": len(changed_recently),
            "uncategorised": len(uncat),
        },
        "refused": [{"publisher": p, "url": u, "signal": s}
                    for p, u, s in ts.REFUSED],
        "dead": [{"publisher": p, "url": u, "signal": s} for p, u, s in ts.DEAD],
    }
