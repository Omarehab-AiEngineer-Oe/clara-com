"""Persistence for the competitor-intelligence state.

The orchestrator's central rule is that existing data is not the source of truth
— it is the *previous state*, and the new state has to be computed from it plus
new evidence plus verified changes, minus whatever expired. That rule needs two
things the rest of the codebase did not have:

* A snapshot of the whole state at the end of each cycle, so "previous" is a real
  stored thing rather than whatever happens to be in the live tables now.
* Insert-only history for changes, verdicts and offers, so a later cycle can show
  what moved rather than only what currently is.

Everything here is additive: new tables on the same SQLite file, created with
`IF NOT EXISTS`, touching none of the monitoring tables. A cycle that crashes
halfway leaves the previous snapshot intact, because the new snapshot is written
once at the end rather than mutated in place.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from .contracts import OfferStatus, now_iso

SCHEMA = """
-- One row per completed cycle: the whole state as it stood at the end.
CREATE TABLE IF NOT EXISTS intel_snapshot (
  cycle_id     TEXT PRIMARY KEY,
  created_at   TEXT NOT NULL,
  state_json   TEXT NOT NULL,
  summary_json TEXT
);

-- The current record for each competitor identity.
CREATE TABLE IF NOT EXISTS intel_competitor (
  identity_key TEXT PRIMARY KEY,
  name         TEXT NOT NULL,
  domains_json TEXT,
  type         TEXT,
  profile_json TEXT,
  confidence   TEXT,
  status       TEXT,              -- active | dormant | removed
  relevance    TEXT,              -- direct | indirect | emerging | substitute | none
  first_seen_at TEXT,
  last_seen_at  TEXT,
  last_cycle_id TEXT
);

-- Insert-only: every typed difference between two states.
CREATE TABLE IF NOT EXISTS intel_change (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  cycle_id      TEXT NOT NULL,
  change_type   TEXT NOT NULL,
  entity        TEXT NOT NULL,
  field_name    TEXT,
  previous_value TEXT,
  new_value     TEXT,
  detail        TEXT,
  confidence    TEXT,
  evidence_json TEXT,
  detected_at   TEXT
);
CREATE INDEX IF NOT EXISTS ix_change_cycle ON intel_change(cycle_id);

-- Offers carry their own lifecycle, because an old offer is not a live offer.
CREATE TABLE IF NOT EXISTS intel_offer (
  offer_key     TEXT PRIMARY KEY,
  competitor    TEXT NOT NULL,
  product       TEXT,
  offer_json    TEXT NOT NULL,
  status        TEXT NOT NULL,
  first_seen_at TEXT,
  last_seen_at  TEXT,
  last_cycle_id TEXT
);

CREATE TABLE IF NOT EXISTS intel_offer_event (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  offer_key   TEXT NOT NULL,
  cycle_id    TEXT,
  at          TEXT,
  from_status TEXT,
  to_status   TEXT,
  note        TEXT
);

-- Insert-only: every verification verdict, including the negative ones.
CREATE TABLE IF NOT EXISTS intel_claim (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  cycle_id      TEXT NOT NULL,
  entity        TEXT,
  subject       TEXT,
  claim         TEXT,
  status        TEXT,
  confidence    TEXT,
  evidence_json TEXT,
  conflicts_json TEXT,
  reason        TEXT,
  recommended_action TEXT,
  checked_at    TEXT
);
CREATE INDEX IF NOT EXISTS ix_claim_cycle ON intel_claim(cycle_id);

CREATE TABLE IF NOT EXISTS intel_finding (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  cycle_id     TEXT NOT NULL,
  entity       TEXT,
  title        TEXT,
  threat_level TEXT,
  confidence   TEXT,
  finding_json TEXT
);

CREATE TABLE IF NOT EXISTS intel_action (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  cycle_id    TEXT NOT NULL,
  entity      TEXT,
  owner       TEXT,
  urgency     TEXT,
  action      TEXT,
  action_json TEXT
);

-- Discovery output kept whole, including the rejects, so a later cycle can see
-- that a company was already considered and dismissed.
CREATE TABLE IF NOT EXISTS intel_candidate (
  identity_key  TEXT NOT NULL,
  cycle_id      TEXT NOT NULL,
  name          TEXT,
  status        TEXT,
  confidence    TEXT,
  candidate_json TEXT,
  first_detected_at TEXT,
  PRIMARY KEY (identity_key, cycle_id)
);

CREATE TABLE IF NOT EXISTS intel_cycle (
  cycle_id    TEXT PRIMARY KEY,
  started_at  TEXT,
  finished_at TEXT,
  agents_json TEXT,
  notes       TEXT
);
"""



# --------------------------------------------------------------------------
# product names must survive the trip
# --------------------------------------------------------------------------
# One Clara product is named in Arabic, and decision text written by the
# intelligence cycle was found carrying a damaged copy of it: four letters
# substituted, everything else intact. The catalogue row and every other output
# were clean, so the damage happens somewhere on the way into this table.
#
# The cause is not found. The correct value is, though: a damaged copy is an
# 80%-plus character match to a catalogue name of the same length, which makes
# the original unambiguous. So the name is checked here, against the catalogue,
# at the moment it is written — and repaired rather than stored wrong.
#
# This is a guard, not a fix. It is the same reasoning `validate.py` applies to
# stale notes: where a value can be checked against a source of truth, check it
# there rather than trusting the path it arrived by.

_MIN_MATCH = 0.70


def _arabic(text: str) -> bool:
    return any("\u0600" <= c <= "\u06ff" for c in text or "")


def _catalogue_names() -> list[str]:
    """Arabic-named products, loaded once and cached on the function."""
    cached = getattr(_catalogue_names, "_cache", None)
    if cached is not None:
        return cached
    try:
        from ..catalog import load_from_seed
        names = [p.name for p in load_from_seed() if _arabic(p.name)]
    except Exception:                                     # noqa: BLE001
        names = []
    _catalogue_names._cache = names
    return names


def _runs(text: str) -> list[str]:
    """Maximal Arabic runs, spaces included, so a whole name comes out whole."""
    out, cur = [], []
    for ch in text or "":
        if "\u0600" <= ch <= "\u06ff" or (cur and ch == " "):
            cur.append(ch)
        elif cur:
            out.append("".join(cur))
            cur = []
    if cur:
        out.append("".join(cur))
    return out


def repair_names(text: str) -> tuple[str, list[str]]:
    """Replace any damaged copy of a catalogue name with the real one."""
    if not text or not _arabic(text):
        return text, []
    names = _catalogue_names()
    if not names:
        return text, []
    fixed, notes = text, []
    for run in _runs(text):
        stripped = run.strip()
        if len(stripped) < 10 or any(stripped in n for n in names):
            continue
        best, score = None, 0.0
        for n in names:
            if abs(len(stripped) - len(n)) > 2:
                continue
            same = sum(1 for a, b in zip(stripped, n) if a == b)
            r = same / max(len(stripped), len(n))
            if r > score:
                best, score = n, r
        if best and _MIN_MATCH <= score < 1.0:
            fixed = fixed.replace(stripped, best)
            notes.append(f"product name repaired from a {score:.0%} match to "
                         f"the catalogue")
    return fixed, notes

def _j(value) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


class IntelStore:
    def __init__(self, path: Path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(path), check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)
        self.db.commit()

    def close(self) -> None:
        self.db.close()

    # ---------------- cycles ----------------

    def start_cycle(self, cycle_id: str, notes: str = "") -> None:
        self.db.execute(
            """INSERT OR REPLACE INTO intel_cycle
               (cycle_id, started_at, finished_at, agents_json, notes)
               VALUES (?,?,NULL,NULL,?)""",
            (cycle_id, now_iso(), notes))
        self.db.commit()

    def finish_cycle(self, cycle_id: str, agents: dict) -> None:
        self.db.execute(
            "UPDATE intel_cycle SET finished_at=?, agents_json=? WHERE cycle_id=?",
            (now_iso(), _j(agents), cycle_id))
        self.db.commit()

    def cycles(self) -> list[dict]:
        return [dict(r) for r in self.db.execute(
            # rowid breaks the tie: two cycles run in the same second are
            # ordered by which was actually written second, not arbitrarily.
            "SELECT * FROM intel_cycle ORDER BY started_at DESC, rowid DESC")]

    # ---------------- snapshots ----------------

    def previous_state(self) -> dict | None:
        """The most recent completed snapshot, or None on a first-ever cycle."""
        r = self.db.execute(
            "SELECT state_json FROM intel_snapshot ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
        return json.loads(r["state_json"]) if r else None

    def save_snapshot(self, cycle_id: str, state: dict, summary: dict) -> None:
        self.db.execute(
            """INSERT OR REPLACE INTO intel_snapshot
               (cycle_id, created_at, state_json, summary_json) VALUES (?,?,?,?)""",
            (cycle_id, now_iso(), _j(state), _j(summary)))
        self.db.commit()

    def snapshot_count(self) -> int:
        return self.db.execute("SELECT COUNT(*) FROM intel_snapshot").fetchone()[0]

    # ---------------- competitors ----------------

    def competitors(self) -> dict[str, dict]:
        out = {}
        for r in self.db.execute("SELECT * FROM intel_competitor"):
            d = dict(r)
            d["domains"] = json.loads(d.pop("domains_json") or "[]")
            d["profile"] = json.loads(d.pop("profile_json") or "{}")
            out[d["identity_key"]] = d
        return out

    def put_competitor(self, rec: dict, cycle_id: str) -> None:
        existing = self.db.execute(
            "SELECT first_seen_at FROM intel_competitor WHERE identity_key=?",
            (rec["identity_key"],)).fetchone()
        first = (existing["first_seen_at"] if existing
                 else rec.get("first_seen_at") or now_iso())
        self.db.execute(
            """INSERT OR REPLACE INTO intel_competitor
               (identity_key,name,domains_json,type,profile_json,confidence,
                status,relevance,first_seen_at,last_seen_at,last_cycle_id)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (rec["identity_key"], rec.get("name", ""),
             _j(rec.get("domains") or []), rec.get("type", ""),
             _j(rec.get("profile") or {}), rec.get("confidence", ""),
             rec.get("status", "active"), rec.get("relevance", ""),
             first, rec.get("last_seen_at") or now_iso(), cycle_id))
        self.db.commit()

    def mark_competitor_status(self, identity_key: str, status: str) -> None:
        self.db.execute("UPDATE intel_competitor SET status=? WHERE identity_key=?",
                        (status, identity_key))
        self.db.commit()

    # ---------------- offers ----------------

    def offers(self) -> dict[str, dict]:
        out = {}
        for r in self.db.execute("SELECT * FROM intel_offer"):
            d = dict(r)
            d["offer"] = json.loads(d.pop("offer_json") or "{}")
            out[d["offer_key"]] = d
        return out

    def put_offer(self, offer: dict, cycle_id: str) -> str | None:
        """Store an offer and return the status it had before, if any."""
        key = offer["offer_key"]
        prev = self.db.execute(
            "SELECT status, first_seen_at FROM intel_offer WHERE offer_key=?",
            (key,)).fetchone()
        first = (prev["first_seen_at"] if prev
                 else offer.get("detected_at") or now_iso())
        self.db.execute(
            """INSERT OR REPLACE INTO intel_offer
               (offer_key,competitor,product,offer_json,status,first_seen_at,
                last_seen_at,last_cycle_id) VALUES (?,?,?,?,?,?,?,?)""",
            (key, offer.get("competitor", ""), offer.get("product", ""),
             _j(offer), offer.get("status", OfferStatus.UNKNOWN), first,
             offer.get("last_seen_at") or now_iso(), cycle_id))
        before = prev["status"] if prev else None
        if before != offer.get("status"):
            self.db.execute(
                """INSERT INTO intel_offer_event
                   (offer_key,cycle_id,at,from_status,to_status,note)
                   VALUES (?,?,?,?,?,?)""",
                (key, cycle_id, now_iso(), before, offer.get("status"),
                 offer.get("change_note", "")))
        self.db.commit()
        return before

    def offer_events(self, limit: int = 200) -> list[dict]:
        return [dict(r) for r in self.db.execute(
            "SELECT * FROM intel_offer_event ORDER BY id DESC LIMIT ?", (limit,))]

    # ---------------- changes, claims, findings, actions ----------------

    def add_change(self, cycle_id: str, c) -> None:
        d = c.to_dict() if hasattr(c, "to_dict") else dict(c)
        self.db.execute(
            """INSERT INTO intel_change
               (cycle_id,change_type,entity,field_name,previous_value,new_value,
                detail,confidence,evidence_json,detected_at)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (cycle_id, d.get("change_type"), d.get("entity"), d.get("field_name"),
             str(d.get("previous_value") or ""), str(d.get("new_value") or ""),
             d.get("detail"), d.get("confidence"), _j(d.get("evidence") or []),
             d.get("detected_at") or now_iso()))
        self.db.commit()

    def changes_for(self, cycle_id: str) -> list[dict]:
        rows = []
        for r in self.db.execute(
                "SELECT * FROM intel_change WHERE cycle_id=? ORDER BY id", (cycle_id,)):
            d = dict(r)
            d["evidence"] = json.loads(d.pop("evidence_json") or "[]")
            rows.append(d)
        return rows

    def add_claim(self, cycle_id: str, c) -> None:
        d = c.to_dict() if hasattr(c, "to_dict") else dict(c)
        self.db.execute(
            """INSERT INTO intel_claim
               (cycle_id,entity,subject,claim,status,confidence,evidence_json,
                conflicts_json,reason,recommended_action,checked_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (cycle_id, d.get("entity"), d.get("subject"), d.get("claim"),
             d.get("verification_status"), d.get("confidence"),
             _j(d.get("evidence") or []), _j(d.get("conflicts") or []),
             d.get("reason"), d.get("recommended_action"),
             d.get("checked_at") or now_iso()))
        self.db.commit()

    def claims_for(self, cycle_id: str) -> list[dict]:
        rows = []
        for r in self.db.execute(
                "SELECT * FROM intel_claim WHERE cycle_id=? ORDER BY id", (cycle_id,)):
            d = dict(r)
            d["evidence"] = json.loads(d.pop("evidence_json") or "[]")
            d["conflicts"] = json.loads(d.pop("conflicts_json") or "[]")
            rows.append(d)
        return rows

    def add_finding(self, cycle_id: str, f) -> None:
        d = f.to_dict() if hasattr(f, "to_dict") else dict(f)
        self.db.execute(
            """INSERT INTO intel_finding
               (cycle_id,entity,title,threat_level,confidence,finding_json)
               VALUES (?,?,?,?,?,?)""",
            (cycle_id, d.get("entity"), d.get("title"), d.get("threat_level"),
             d.get("confidence"), _j(d)))
        self.db.commit()

    def add_action(self, cycle_id: str, a) -> None:
        d = a.to_dict() if hasattr(a, "to_dict") else dict(a)
        # The one writer where damaged product names were found. Checked against
        # the catalogue here rather than trusted from upstream.
        for key in ("action", "because", "expected_outcome"):
            if d.get(key):
                fixed, notes = repair_names(d[key])
                if notes:
                    d[key] = fixed
                    d.setdefault("warnings", [])
                    if isinstance(d["warnings"], list):
                        d["warnings"].extend(notes)
        self.db.execute(
            """INSERT INTO intel_action
               (cycle_id,entity,owner,urgency,action,action_json)
               VALUES (?,?,?,?,?,?)""",
            (cycle_id, d.get("entity"), d.get("owner"), d.get("urgency"),
             d.get("action"), _j(d)))
        self.db.commit()

    # ---------------- candidates ----------------

    def put_candidate(self, cycle_id: str, cand) -> None:
        d = cand.to_dict() if hasattr(cand, "to_dict") else dict(cand)
        self.db.execute(
            """INSERT OR REPLACE INTO intel_candidate
               (identity_key,cycle_id,name,status,confidence,candidate_json,
                first_detected_at) VALUES (?,?,?,?,?,?,?)""",
            (d.get("identity_key") or d.get("competitor_name"), cycle_id,
             d.get("competitor_name"), d.get("status"), d.get("confidence"),
             _j(d), d.get("first_detected_at") or now_iso()))
        self.db.commit()

    def seen_candidates(self) -> dict[str, dict]:
        """Every identity discovery has ever considered, with its latest verdict.

        Used so a company dismissed as irrelevant in one cycle is not rediscovered
        and re-reported as news in the next.
        """
        out = {}
        for r in self.db.execute(
                "SELECT * FROM intel_candidate ORDER BY cycle_id"):
            d = dict(r)
            d["candidate"] = json.loads(d.pop("candidate_json") or "{}")
            out[d["identity_key"]] = d
        return out
