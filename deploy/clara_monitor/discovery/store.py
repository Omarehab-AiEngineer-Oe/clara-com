"""Persistence for the discovery loop, and the migration that adds it.

Additive by construction: every table is new and created with `IF NOT EXISTS`,
nothing existing is altered, and no existing row is rewritten. A database that
has never seen this code gains eight tables and loses nothing; the 219 signals,
the 86 seed patterns and the 35 seed feeds are untouched.

The design decision worth stating is that **the registry is not the seed file.**
`trend_sources.py` stays the seed and is never written to by the agent. The
registry mirrors those seeds as rows so that everything — seed and discovered
alike — can carry state, provenance and a quality score in one place. Active
sources are the union, computed at read time:

    seed rows (always trusted)  +  discovered rows with state = active

That split is what lets discovery be reversible. Disabling every discovered
source returns the system exactly to the hand-curated 35, with one UPDATE.

Every table that records a decision keeps the evidence for it. `source_discovery_event`
answers "why is this here", `source_validation_run` answers "what did we check",
and `topic_candidate.evidence_json` holds the signals that argued for a subject.
A discovery loop nobody can audit is a rumour mill.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .config import (ACTIVE, CANDIDATE, DISABLED, DISCOVERED, MERGED, REJECTED,
                     SEED, VALIDATED)

SCHEMA = """
-- ------------------------------------------------------------------ sources
CREATE TABLE IF NOT EXISTS ds_source (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  key             TEXT UNIQUE,          -- stable slug; seed rows reuse the seed key
  name            TEXT NOT NULL,
  url             TEXT,                 -- the publisher's site
  feed_url        TEXT UNIQUE NOT NULL,   -- fetchable, as served
  feed_key        TEXT,                  -- normalised; the dedup identity
  domain          TEXT NOT NULL,
  source_type     TEXT NOT NULL,        -- seed | discovered
  kind            TEXT,                 -- trade_press | consumer_press | ...
  market          TEXT,
  status          TEXT NOT NULL,        -- candidate | validated | active |
                                        -- rejected | disabled
  discovered_from TEXT,                 -- JSON provenance
  discovered_at   TEXT,
  depth           INTEGER DEFAULT 0,
  last_checked_at TEXT,
  last_success_at TEXT,
  failure_count   INTEGER DEFAULT 0,
  article_count   INTEGER DEFAULT 0,
  relevant_count  INTEGER DEFAULT 0,
  duplicate_count INTEGER DEFAULT 0,
  quality_score   REAL,
  confidence      REAL,
  enabled         INTEGER DEFAULT 1,
  reject_reason   TEXT,
  notes           TEXT
);
CREATE INDEX IF NOT EXISTS ix_ds_source_domain ON ds_source(domain);
CREATE INDEX IF NOT EXISTS ix_ds_source_status ON ds_source(status);

CREATE TABLE IF NOT EXISTS ds_source_event (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  at          TEXT NOT NULL,
  run_id      TEXT,
  source_key  TEXT,
  feed_url    TEXT,
  domain      TEXT,
  event       TEXT NOT NULL,   -- candidate_created | validated | activated |
                               -- rejected | disabled | rediscovered | scored
  method      TEXT,            -- how it was found
  parent_key  TEXT,            -- the source whose article led here
  article_url TEXT,
  detail      TEXT,
  payload     TEXT
);
CREATE INDEX IF NOT EXISTS ix_ds_event_run ON ds_source_event(run_id);

CREATE TABLE IF NOT EXISTS ds_validation_run (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  at           TEXT NOT NULL,
  run_id       TEXT,
  feed_url     TEXT NOT NULL,
  ok           INTEGER,
  reason       TEXT,
  entries      INTEGER,
  usable       INTEGER,
  relevant     INTEGER,
  same_domain  INTEGER,
  newest_at    TEXT,
  quality      REAL,
  payload      TEXT
);

-- ------------------------------------------------------------------- topics
CREATE TABLE IF NOT EXISTS ds_topic_candidate (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  key             TEXT UNIQUE NOT NULL,
  label           TEXT NOT NULL,
  terms_json      TEXT,          -- the cluster's own vocabulary
  pattern         TEXT,          -- generated regex
  aliases_json    TEXT,
  category        TEXT,
  state           TEXT NOT NULL, -- candidate | validated | active | rejected |
                                 -- merged
  signal_count    INTEGER,
  publisher_count INTEGER,
  days_seen       INTEGER,
  first_seen_at   TEXT,
  last_seen_at    TEXT,
  created_at      TEXT,
  decided_at      TEXT,
  merged_into     TEXT,
  reject_reason   TEXT,
  precision_est   REAL,
  corpus_ratio    REAL,
  evidence_json   TEXT           -- the signals that argued for it
);

CREATE TABLE IF NOT EXISTS ds_topic_event (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  at            TEXT NOT NULL,
  run_id        TEXT,
  candidate_key TEXT,
  event         TEXT NOT NULL,  -- clustered | validated | activated |
                                -- rejected | merged | pattern_tested
  detail        TEXT,
  payload       TEXT
);

CREATE TABLE IF NOT EXISTS ds_topic_pattern (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  topic_key     TEXT NOT NULL,
  pattern       TEXT NOT NULL,
  source        TEXT,           -- seed | discovered
  added_at      TEXT,
  matched_count INTEGER DEFAULT 0,
  enabled       INTEGER DEFAULT 1,
  UNIQUE(topic_key, pattern)
);

CREATE TABLE IF NOT EXISTS ds_classification_run (
  id                  INTEGER PRIMARY KEY AUTOINCREMENT,
  at                  TEXT NOT NULL,
  run_id              TEXT,
  signals_total       INTEGER,
  uncategorised_before INTEGER,
  uncategorised_after  INTEGER,
  retagged            INTEGER,
  topics_active       INTEGER,
  detail              TEXT
);

-- Cooldowns live in the database rather than in a lockfile so a scheduled run
-- and a manual run cannot disagree about when discovery last happened.
CREATE TABLE IF NOT EXISTS ds_state (
  name    TEXT PRIMARY KEY,
  value   TEXT,
  at      TEXT
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _parse(stamp: str):
    if not stamp:
        return None
    try:
        d = datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def _j(value) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def _norm(url: str) -> str:
    from .feeds import normalise_url
    return normalise_url(url)


def _reg(host_or_url: str) -> str:
    """The canonical domain. Every write and every lookup goes through this.

    Patching each comparison site individually is what produced three rounds of
    the same normalisation bug, so the column itself is canonical now and there
    is no second spelling for a comparison to miss.
    """
    from .feeds import registrable_domain
    return registrable_domain(host_or_url)


class DiscoveryStore:
    def __init__(self, path: Path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(path), check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)
        self._migrate()
        self.db.commit()

    def _migrate(self) -> None:
        """Additive migration. Safe to run on a database that predates it.

        `feed_key` was added after the first real run exposed the dedup bug, so
        existing rows are backfilled from their `feed_url` rather than being
        rewritten or dropped.
        """
        cols = {r[1] for r in self.db.execute("PRAGMA table_info(ds_source)")}
        if "feed_key" not in cols:
            self.db.execute("ALTER TABLE ds_source ADD COLUMN feed_key TEXT")
        from .feeds import normalise_url
        for r in self.db.execute(
                "SELECT id, feed_url FROM ds_source "
                "WHERE feed_key IS NULL OR feed_key=''").fetchall():
            self.db.execute("UPDATE ds_source SET feed_key=? WHERE id=?",
                            (normalise_url(r["feed_url"]), r["id"]))
        self.db.commit()
        # The index goes on after the column exists and is backfilled. Creating
        # it inside SCHEMA would fail on any database that predates the column,
        # because executescript runs before this method.
        # Canonicalise the domain column. Written as-served before this, which
        # is what let four seed publishers be rediscovered.
        for r in self.db.execute("SELECT id, domain FROM ds_source").fetchall():
            canon = _reg(r["domain"])
            if canon and canon != r["domain"]:
                self.db.execute("UPDATE ds_source SET domain=? WHERE id=?",
                                (canon, r["id"]))
        self.db.commit()

        # Collapse rows that the pre-migration dedup let through: the same feed
        # under two spellings. A seed row always wins over a discovered one,
        # because the seed is what a person actually chose.
        dupes = self.db.execute(
            "SELECT feed_key FROM ds_source WHERE feed_key IS NOT NULL "
            "GROUP BY feed_key HAVING COUNT(*) > 1").fetchall()
        for d in dupes:
            rows = self.db.execute(
                "SELECT id, source_type FROM ds_source WHERE feed_key=? "
                "ORDER BY CASE source_type WHEN 'seed' THEN 0 ELSE 1 END, id",
                (d["feed_key"],)).fetchall()
            for extra in rows[1:]:
                self.db.execute("DELETE FROM ds_source WHERE id=?",
                                (extra["id"],))
        if dupes:
            self.db.commit()

        try:
            self.db.execute("CREATE UNIQUE INDEX IF NOT EXISTS "
                            "ix_ds_source_feedkey ON ds_source(feed_key)")
        except sqlite3.Error:
            pass
        self.db.commit()

    def close(self) -> None:
        self.db.close()

    # ---------------- seeding ----------------

    def sync_seeds(self, seed_sources: list) -> dict:
        """Mirror the hand-curated feeds into the registry.

        Idempotent, and never destructive: a seed row already present has its
        name and kind refreshed and nothing else, so a run cannot reset the
        counters a seed has accumulated. Seeds are always `active` — they were
        chosen by a person and discovery has no authority to demote them.
        """
        added = 0
        for s in seed_sources:
            from .feeds import normalise_url
            key = normalise_url(s.url)
            row = self.db.execute(
                "SELECT id FROM ds_source WHERE feed_url=? OR feed_key=?",
                (s.url, key)).fetchone()
            if row:
                self.db.execute(
                    "UPDATE ds_source SET name=?, kind=?, market=?, "
                    "source_type=?, status=?, enabled=1, feed_key=? "
                    "WHERE id=?",
                    (s.publisher, s.kind, s.market, SEED, ACTIVE, key,
                     row["id"]))
                continue
            self.db.execute(
                """INSERT INTO ds_source
                   (key, name, url, feed_url, feed_key, domain, source_type, kind,
                    market, status, discovered_at, depth, quality_score,
                    confidence, enabled, notes)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,1,?)""",
                (s.key, s.publisher, f"https://{s.host}", s.url, key,
                 _reg(s.host), SEED,
                 s.kind, s.market, ACTIVE, _now(), 0, 1.0, 1.0,
                 "hand-curated seed"))
            added += 1
        self.db.commit()
        return {"seeds": len(seed_sources), "inserted": added}

    # ---------------- lookups / dedup ----------------

    def by_feed(self, feed_url: str) -> dict | None:
        """Look up by either spelling: as served, or normalised."""
        from .feeds import normalise_url
        key = normalise_url(feed_url)
        r = self.db.execute(
            "SELECT * FROM ds_source WHERE feed_url=? OR feed_key=?",
            (feed_url, key)).fetchone()
        return dict(r) if r else None

    def by_domain(self, domain: str) -> list[dict]:
        """Match on the canonical domain, whatever spelling was passed in."""
        return [dict(r) for r in self.db.execute(
            "SELECT * FROM ds_source WHERE domain=?", (_reg(domain),))]

    def source_exists(self, feed_url: str = "", domain: str = "") -> bool:
        """Either identity is enough.

        A publisher already in the registry under some other feed path is not a
        discovery, whatever URL was proposed — which is what the domain check is
        for.
        """
        if feed_url and self.by_feed(feed_url):
            return True
        if domain and self.by_domain(domain):
            return True
        return False

    def known_domains(self) -> set:
        """Canonical domains only, so a caller cannot compare two spellings."""
        return {_reg(r[0]) for r in
                self.db.execute("SELECT DISTINCT domain FROM ds_source") if r[0]}

    def known_feeds(self) -> set:
        """Both spellings, so a check against either one hits."""
        out = set()
        for r in self.db.execute(
                "SELECT feed_url, feed_key FROM ds_source"):
            if r[0]:
                out.add(r[0])
            if r[1]:
                out.add(r[1])
        return out

    def candidates_for_domain(self, domain: str) -> int:
        return self.db.execute(
            "SELECT COUNT(*) FROM ds_source WHERE domain=? AND source_type=?",
            (_reg(domain), DISCOVERED)).fetchone()[0]

    # ---------------- writing sources ----------------

    def add_candidate(self, *, key: str, name: str, url: str, feed_url: str,
                      domain: str, kind: str, market: str, depth: int,
                      provenance: dict, run_id: str) -> dict:
        existing = self.by_feed(feed_url)
        if existing:
            # Rediscovery is information, not a duplicate row: it says this
            # publisher keeps turning up, which is mild evidence for it.
            self.db.execute(
                "UPDATE ds_source SET last_checked_at=? WHERE feed_url=?",
                (_now(), feed_url))
            self.event(run_id, "rediscovered", source_key=existing["key"],
                       feed_url=feed_url, domain=domain,
                       method=provenance.get("discovery_method"),
                       parent_key=provenance.get("source_key"),
                       article_url=provenance.get("article_url"),
                       detail="already in the registry; metadata refreshed")
            self.db.commit()
            return existing

        self.db.execute(
            """INSERT INTO ds_source
               (key, name, url, feed_url, feed_key, domain, source_type, kind,
                market, status, discovered_from, discovered_at, depth, enabled)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,1)""",
            (key, name, url, feed_url, _norm(feed_url), _reg(domain),
             DISCOVERED, kind, market,
             CANDIDATE, _j(provenance), _now(), depth))
        self.event(run_id, "candidate_created", source_key=key,
                   feed_url=feed_url, domain=domain,
                   method=provenance.get("discovery_method"),
                   parent_key=provenance.get("source_key"),
                   article_url=provenance.get("article_url"),
                   detail=f"found via {provenance.get('discovery_method')}")
        self.db.commit()
        return self.by_feed(feed_url) or {}

    def set_status(self, feed_url: str, status: str, *, quality: float | None = None,
                   reason: str = "", run_id: str = "") -> None:
        self.db.execute(
            "UPDATE ds_source SET status=?, quality_score=COALESCE(?,quality_score),"
            " reject_reason=?, enabled=? WHERE feed_url=?",
            (status, quality, reason, 0 if status in (REJECTED, DISABLED) else 1,
             feed_url))
        row = self.by_feed(feed_url) or {}
        self.event(run_id, {ACTIVE: "activated", VALIDATED: "validated",
                            REJECTED: "rejected", DISABLED: "disabled"}
                   .get(status, "scored"),
                   source_key=row.get("key"), feed_url=feed_url,
                   domain=row.get("domain"),
                   detail=reason or f"status -> {status}",
                   payload={"quality_score": quality})
        self.db.commit()

    def record_fetch(self, feed_url: str, *, ok: bool, articles: int = 0,
                     relevant: int = 0, duplicates: int = 0) -> None:
        if ok:
            self.db.execute(
                "UPDATE ds_source SET last_checked_at=?, last_success_at=?, "
                "failure_count=0, article_count=article_count+?, "
                "relevant_count=relevant_count+?, duplicate_count=duplicate_count+? "
                "WHERE feed_url=?",
                (_now(), _now(), articles, relevant, duplicates, feed_url))
        else:
            self.db.execute(
                "UPDATE ds_source SET last_checked_at=?, "
                "failure_count=failure_count+1 WHERE feed_url=?",
                (_now(), feed_url))
        self.db.commit()

    def event(self, run_id: str, event: str, **kw) -> None:
        self.db.execute(
            """INSERT INTO ds_source_event
               (at, run_id, source_key, feed_url, domain, event, method,
                parent_key, article_url, detail, payload)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (_now(), run_id, kw.get("source_key"), kw.get("feed_url"),
             kw.get("domain"), event, kw.get("method"), kw.get("parent_key"),
             kw.get("article_url"), kw.get("detail"),
             _j(kw.get("payload") or {})))

    def record_validation(self, run_id: str, feed_url: str, result: dict) -> None:
        self.db.execute(
            """INSERT INTO ds_validation_run
               (at, run_id, feed_url, ok, reason, entries, usable, relevant,
                same_domain, newest_at, quality, payload)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (_now(), run_id, feed_url, 1 if result.get("ok") else 0,
             result.get("reason"), result.get("entries"), result.get("usable"),
             result.get("relevant"), 1 if result.get("same_domain") else 0,
             result.get("newest_at"), result.get("quality"), _j(result)))
        self.db.commit()

    # ---------------- reading sources ----------------

    def active_sources(self) -> list[dict]:
        """Seed rows plus discovered rows that earned activation."""
        return [dict(r) for r in self.db.execute(
            "SELECT * FROM ds_source WHERE enabled=1 AND status=? "
            "ORDER BY source_type, name", (ACTIVE,))]

    def by_status(self, status: str) -> list[dict]:
        return [dict(r) for r in self.db.execute(
            "SELECT * FROM ds_source WHERE status=? ORDER BY name", (status,))]

    def source_counts(self) -> dict:
        out = {"seed": 0, "discovered": 0, "active": 0, "candidate": 0,
               "validated": 0, "rejected": 0, "disabled": 0}
        for r in self.db.execute(
                "SELECT source_type, status, COUNT(*) n FROM ds_source "
                "GROUP BY 1,2"):
            out[r["source_type"]] = out.get(r["source_type"], 0) + r["n"]
            out[r["status"]] = out.get(r["status"], 0) + r["n"]
        return out

    def discovery_chain(self) -> list[dict]:
        """Who found whom, for the audit graph."""
        rows = []
        for r in self.db.execute(
                "SELECT key, name, domain, source_type, status, depth, "
                "discovered_from, quality_score FROM ds_source ORDER BY depth, name"):
            d = dict(r)
            try:
                d["discovered_from"] = json.loads(d["discovered_from"] or "{}")
            except (ValueError, TypeError):
                d["discovered_from"] = {}
            rows.append(d)
        return rows

    def events(self, run_id: str | None = None, limit: int = 200) -> list[dict]:
        if run_id:
            q = ("SELECT * FROM ds_source_event WHERE run_id=? "
                 "ORDER BY id DESC LIMIT ?")
            args = (run_id, limit)
        else:
            q = "SELECT * FROM ds_source_event ORDER BY id DESC LIMIT ?"
            args = (limit,)
        return [dict(r) for r in self.db.execute(q, args)]

    # ---------------- topics ----------------

    def add_topic_candidate(self, cand: dict, run_id: str) -> dict:
        existing = self.db.execute(
            "SELECT * FROM ds_topic_candidate WHERE key=?",
            (cand["key"],)).fetchone()
        if existing:
            self.db.execute(
                """UPDATE ds_topic_candidate
                   SET signal_count=?, publisher_count=?, days_seen=?,
                       last_seen_at=?, terms_json=?, pattern=?,
                       evidence_json=? WHERE key=?""",
                (cand["signal_count"], cand["publisher_count"],
                 cand["days_seen"], cand.get("last_seen_at"),
                 _j(cand.get("terms") or []), cand.get("pattern"),
                 _j(cand.get("evidence") or []), cand["key"]))
            self.db.commit()
            return dict(existing)
        self.db.execute(
            """INSERT INTO ds_topic_candidate
               (key, label, terms_json, pattern, aliases_json, category, state,
                signal_count, publisher_count, days_seen, first_seen_at,
                last_seen_at, created_at, evidence_json)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (cand["key"], cand["label"], _j(cand.get("terms") or []),
             cand.get("pattern"), _j(cand.get("aliases") or []),
             cand.get("category") or "beauty_culture", CANDIDATE,
             cand["signal_count"], cand["publisher_count"], cand["days_seen"],
             cand.get("first_seen_at"), cand.get("last_seen_at"), _now(),
             _j(cand.get("evidence") or [])))
        self.topic_event(run_id, cand["key"], "clustered",
                         f"{cand['signal_count']} signal(s) from "
                         f"{cand['publisher_count']} publisher(s) over "
                         f"{cand['days_seen']} day(s)")
        self.db.commit()
        return self.topic_candidate(cand["key"]) or {}

    def topic_candidate(self, key: str) -> dict | None:
        r = self.db.execute("SELECT * FROM ds_topic_candidate WHERE key=?",
                            (key,)).fetchone()
        if not r:
            return None
        d = dict(r)
        d["terms"] = json.loads(d.pop("terms_json") or "[]")
        d["aliases"] = json.loads(d.pop("aliases_json") or "[]")
        d["evidence"] = json.loads(d.pop("evidence_json") or "[]")
        return d

    def set_topic_state(self, key: str, state: str, *, reason: str = "",
                        merged_into: str = "", precision: float | None = None,
                        corpus_ratio: float | None = None,
                        run_id: str = "") -> None:
        self.db.execute(
            """UPDATE ds_topic_candidate
               SET state=?, decided_at=?, reject_reason=?, merged_into=?,
                   precision_est=COALESCE(?,precision_est),
                   corpus_ratio=COALESCE(?,corpus_ratio)
               WHERE key=?""",
            (state, _now(), reason, merged_into, precision, corpus_ratio, key))
        self.topic_event(run_id, key,
                         {ACTIVE: "activated", VALIDATED: "validated",
                          REJECTED: "rejected", MERGED: "merged"}.get(state, state),
                         reason or f"state -> {state}")
        self.db.commit()

    def topic_event(self, run_id: str, key: str, event: str, detail: str = "",
                    payload: dict | None = None) -> None:
        self.db.execute(
            """INSERT INTO ds_topic_event
               (at, run_id, candidate_key, event, detail, payload)
               VALUES (?,?,?,?,?,?)""",
            (_now(), run_id, key, event, detail, _j(payload or {})))

    def topics_by_state(self, state: str) -> list[dict]:
        out = []
        for r in self.db.execute(
                "SELECT key FROM ds_topic_candidate WHERE state=? "
                "ORDER BY signal_count DESC", (state,)):
            c = self.topic_candidate(r["key"])
            if c:
                out.append(c)
        return out

    def active_topics(self) -> list[dict]:
        return self.topics_by_state(ACTIVE)

    def topic_counts(self) -> dict:
        out = {s: 0 for s in (CANDIDATE, VALIDATED, ACTIVE, REJECTED, MERGED)}
        for r in self.db.execute(
                "SELECT state, COUNT(*) n FROM ds_topic_candidate GROUP BY 1"):
            out[r["state"]] = r["n"]
        return out

    def add_pattern(self, topic_key: str, pattern: str, source: str = DISCOVERED,
                    matched: int = 0) -> None:
        self.db.execute(
            """INSERT OR IGNORE INTO ds_topic_pattern
               (topic_key, pattern, source, added_at, matched_count)
               VALUES (?,?,?,?,?)""",
            (topic_key, pattern, source, _now(), matched))
        self.db.commit()

    def active_patterns(self) -> list[dict]:
        return [dict(r) for r in self.db.execute(
            "SELECT p.* FROM ds_topic_pattern p "
            "JOIN ds_topic_candidate c ON c.key = p.topic_key "
            "WHERE p.enabled=1 AND c.state=?", (ACTIVE,))]

    def record_classification(self, run_id: str, before: int, after: int,
                              total: int, retagged: int, topics: int,
                              detail: str = "") -> None:
        self.db.execute(
            """INSERT INTO ds_classification_run
               (at, run_id, signals_total, uncategorised_before,
                uncategorised_after, retagged, topics_active, detail)
               VALUES (?,?,?,?,?,?,?,?)""",
            (_now(), run_id, total, before, after, retagged, topics, detail))
        self.db.commit()

    def classification_history(self, limit: int = 20) -> list[dict]:
        return [dict(r) for r in self.db.execute(
            "SELECT * FROM ds_classification_run ORDER BY id DESC LIMIT ?",
            (limit,))]

    def topic_events(self, limit: int = 100) -> list[dict]:
        return [dict(r) for r in self.db.execute(
            "SELECT * FROM ds_topic_event ORDER BY id DESC LIMIT ?", (limit,))]

    # ---------------- cooldowns ----------------

    def mark(self, name: str, value: str = "") -> None:
        self.db.execute(
            "INSERT OR REPLACE INTO ds_state (name, value, at) VALUES (?,?,?)",
            (name, value, _now()))
        self.db.commit()

    def last_run(self, name: str):
        r = self.db.execute("SELECT at FROM ds_state WHERE name=?",
                            (name,)).fetchone()
        return _parse(r["at"]) if r else None

    def cooled_down(self, name: str, hours: int) -> tuple[bool, str]:
        """Whether enough time has passed, and how long is left if not."""
        last = self.last_run(name)
        if not last:
            return True, "never run"
        due = last + timedelta(hours=hours)
        now = datetime.now(timezone.utc)
        if now >= due:
            return True, f"last ran {(now - last).total_seconds() / 3600:.1f}h ago"
        left = (due - now).total_seconds() / 3600
        return False, f"{left:.1f}h left of the {hours}h cooldown"
