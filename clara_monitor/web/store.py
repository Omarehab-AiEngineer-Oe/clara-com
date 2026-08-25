"""Storage for Website Analysis: the six objects section 9 names.

Same SQLite file as everything else, and deliberately so — the requirements say
to use the existing application's storage and run-artifact approach, and a
separate service is not required. Six tables, prefixed `wa_`, that no existing
table touches.

Two rules the schema enforces rather than hopes for.

**A page row exists even when the page did not answer.** `status` carries OK,
BLOCKED, NOT_FOUND, ERROR or SKIPPED, so the coverage section is computed from
what was attempted rather than from what happened to succeed. A page that
CAPTCHA'd and left no row would silently become a page nobody ever tried.

**Runs are immutable once finished.** A finished run is an artifact with a date
on it, and re-running writes a new run rather than editing an old one. That is
what makes two runs comparable later, and it is why `run_id` is on every row.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from .contracts import (AccessStatus, PRIORITY_ORDER, Page, RunStatus, Website,
                        now_iso)

SCHEMA = """
CREATE TABLE IF NOT EXISTS wa_run (
  run_id        TEXT PRIMARY KEY,
  status        TEXT NOT NULL,
  clara_url     TEXT,
  inputs        TEXT,          -- the full input set, as given
  page_limit    INTEGER,
  started_at    TEXT,
  finished_at   TEXT,
  warnings      TEXT,
  agent_version TEXT,
  decision_source TEXT,
  requested_by  TEXT,
  summary       TEXT
);

CREATE TABLE IF NOT EXISTS wa_site (
  run_id        TEXT NOT NULL,
  site_key      TEXT NOT NULL,
  role          TEXT NOT NULL,
  name          TEXT,
  base_url      TEXT,
  access_status TEXT,
  access_note   TEXT,
  pages_attempted INTEGER DEFAULT 0,
  pages_read    INTEGER DEFAULT 0,
  pages_blocked INTEGER DEFAULT 0,
  PRIMARY KEY (run_id, site_key)
);

CREATE TABLE IF NOT EXISTS wa_page (
  run_id      TEXT NOT NULL,
  page_key    TEXT NOT NULL,
  site_key    TEXT NOT NULL,
  url         TEXT NOT NULL,
  title       TEXT,
  page_type   TEXT,
  status      TEXT NOT NULL,
  status_note TEXT,
  http_status INTEGER,
  collected_at TEXT,
  screenshot  TEXT,
  render_method TEXT,
  word_count  INTEGER DEFAULT 0,
  depth       INTEGER DEFAULT 0,
  PRIMARY KEY (run_id, page_key)
);
CREATE INDEX IF NOT EXISTS ix_wa_page_site ON wa_page(run_id, site_key);

CREATE TABLE IF NOT EXISTS wa_observation (
  run_id   TEXT NOT NULL,
  obs_key  TEXT NOT NULL,
  page_key TEXT NOT NULL,
  site_key TEXT NOT NULL,
  section  TEXT,
  obs_type TEXT NOT NULL,
  observed TEXT,
  interpretation TEXT,
  image_kind TEXT,
  quality  TEXT,
  signals  TEXT,
  evidence TEXT,
  PRIMARY KEY (run_id, obs_key)
);
CREATE INDEX IF NOT EXISTS ix_wa_obs_page ON wa_observation(run_id, page_key);
CREATE INDEX IF NOT EXISTS ix_wa_obs_type ON wa_observation(run_id, obs_type);

CREATE TABLE IF NOT EXISTS wa_finding (
  run_id      TEXT NOT NULL,
  finding_key TEXT NOT NULL,
  category    TEXT NOT NULL,
  kind        TEXT NOT NULL,
  title       TEXT,
  clara_url   TEXT,
  clara_section TEXT,
  clara_state TEXT,
  observed    TEXT,
  competitor  TEXT,
  competitor_url TEXT,
  competitor_example TEXT,
  why         TEXT,
  confidence  TEXT,
  confidence_why TEXT,
  priority    TEXT,
  priority_why TEXT,
  page_type   TEXT,
  evidence    TEXT,
  PRIMARY KEY (run_id, finding_key)
);
CREATE INDEX IF NOT EXISTS ix_wa_find_pri ON wa_finding(run_id, priority);

CREATE TABLE IF NOT EXISTS wa_recommendation (
  run_id      TEXT NOT NULL,
  rec_key     TEXT NOT NULL,
  finding_key TEXT NOT NULL,
  what        TEXT,
  where_at    TEXT,
  who         TEXT,
  why         TEXT,
  action      TEXT,
  priority    TEXT,
  confidence  TEXT,
  owner       TEXT,
  effort      TEXT,
  complete    INTEGER DEFAULT 0,
  missing_parts TEXT,
  evidence    TEXT,
  PRIMARY KEY (run_id, rec_key)
);
CREATE INDEX IF NOT EXISTS ix_wa_rec_pri ON wa_recommendation(run_id, priority);
"""


def _j(v) -> str:
    return json.dumps(v, ensure_ascii=False, default=str)


def _u(v, fallback=None):
    if not v:
        return fallback if fallback is not None else []
    try:
        return json.loads(v)
    except (ValueError, TypeError):
        return fallback if fallback is not None else []


class WebStore:
    def __init__(self, db_path: Path | str):
        self.db = sqlite3.connect(str(db_path))
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript(SCHEMA)
        self.db.commit()

    def close(self) -> None:
        self.db.close()

    # ---------------- runs ----------------

    def next_run_id(self) -> str:
        n = self.db.execute("SELECT COUNT(*) FROM wa_run").fetchone()[0]
        return f"w{n + 1}"

    def open_run(self, run) -> None:
        self.db.execute(
            "INSERT OR REPLACE INTO wa_run (run_id,status,clara_url,inputs,"
            "page_limit,started_at,finished_at,warnings,agent_version,"
            "decision_source,requested_by,summary) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (run.run_id, run.status, run.clara_url,
             _j({"competitor_urls": run.competitor_urls,
                 "specific_pages": run.specific_pages,
                 "audience": run.audience,
                 "brand_guidelines": run.brand_guidelines,
                 "business_goals": run.business_goals}),
             run.page_limit, run.started_at, run.finished_at,
             _j(run.warnings), run.agent_version, run.decision_source,
             run.requested_by, _j({})))
        self.db.commit()

    def set_status(self, run_id: str, status: str) -> None:
        self.db.execute("UPDATE wa_run SET status=? WHERE run_id=?",
                        (status, run_id))
        self.db.commit()

    def close_run(self, run, summary: dict) -> None:
        self.db.execute(
            "UPDATE wa_run SET status=?, finished_at=?, warnings=?, summary=?, "
            "decision_source=? WHERE run_id=?",
            (run.status, run.finished_at or now_iso(), _j(run.warnings),
             _j(summary), run.decision_source, run.run_id))
        self.db.commit()

    def runs(self) -> list:
        rows = self.db.execute(
            "SELECT * FROM wa_run ORDER BY started_at DESC").fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["inputs"] = _u(d.get("inputs"), {})
            d["warnings"] = _u(d.get("warnings"), [])
            d["summary"] = _u(d.get("summary"), {})
            out.append(d)
        return out

    def latest_run_id(self) -> str | None:
        r = self.db.execute(
            "SELECT run_id FROM wa_run WHERE status=? "
            "ORDER BY started_at DESC LIMIT 1", (RunStatus.DONE,)).fetchone()
        if r:
            return r["run_id"]
        r = self.db.execute("SELECT run_id FROM wa_run "
                            "ORDER BY started_at DESC LIMIT 1").fetchone()
        return r["run_id"] if r else None

    # ---------------- sites and pages ----------------

    def put_site(self, run_id: str, s: Website) -> None:
        self.db.execute(
            "INSERT OR REPLACE INTO wa_site (run_id,site_key,role,name,base_url,"
            "access_status,access_note,pages_attempted,pages_read,pages_blocked)"
            " VALUES (?,?,?,?,?,?,?,?,?,?)",
            (run_id, s.key, s.role, s.name, s.base_url, s.access_status,
             s.access_note, s.pages_attempted, s.pages_read, s.pages_blocked))
        self.db.commit()

    def put_page(self, run_id: str, p: Page) -> None:
        self.db.execute(
            "INSERT OR REPLACE INTO wa_page (run_id,page_key,site_key,url,title,"
            "page_type,status,status_note,http_status,collected_at,screenshot,"
            "render_method,word_count,depth) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (run_id, p.page_key, p.site_key, p.url, p.title, p.page_type,
             p.status, p.status_note, p.http_status, p.collected_at,
             p.screenshot, p.render_method, p.word_count, p.depth))
        self.db.commit()

    def put_observations(self, run_id: str, rows: list) -> None:
        self.db.executemany(
            "INSERT OR REPLACE INTO wa_observation (run_id,obs_key,page_key,"
            "site_key,section,obs_type,observed,interpretation,image_kind,"
            "quality,signals,evidence) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            [(run_id, o.obs_key, o.page_key, o.site_key, o.section, o.obs_type,
              o.observed, o.interpretation, o.image_kind, o.quality,
              _j(o.signals), _j(o.evidence.to_dict() if o.evidence else None))
             for o in rows])
        self.db.commit()

    def put_findings(self, run_id: str, rows: list) -> None:
        self.db.executemany(
            "INSERT OR REPLACE INTO wa_finding (run_id,finding_key,category,kind,"
            "title,clara_url,clara_section,clara_state,observed,competitor,"
            "competitor_url,competitor_example,why,confidence,confidence_why,"
            "priority,priority_why,page_type,evidence) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            [(run_id, f.finding_key, f.category, f.kind, f.title, f.clara_url,
              f.clara_section, f.clara_state, f.observed, f.competitor,
              f.competitor_url, f.competitor_example, f.why, f.confidence,
              f.confidence_why, f.priority, f.priority_why, f.page_type,
              _j([e.to_dict() if hasattr(e, "to_dict") else e
                  for e in f.evidence]))
             for f in rows])
        self.db.commit()

    def put_recommendations(self, run_id: str, rows: list) -> None:
        self.db.executemany(
            "INSERT OR REPLACE INTO wa_recommendation (run_id,rec_key,finding_key,"
            "what,where_at,who,why,action,priority,confidence,owner,effort,"
            "complete,missing_parts,evidence) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            [(run_id, r.rec_key, r.finding_key, r.what, r.where, r.who, r.why,
              r.action, r.priority, r.confidence, r.owner, r.effort,
              1 if r.complete else 0, _j(r.missing_parts()),
              _j([e.to_dict() if hasattr(e, "to_dict") else e
                  for e in r.evidence]))
             for r in rows])
        self.db.commit()

    # ---------------- reading ----------------

    def sites(self, run_id: str) -> list:
        return [dict(r) for r in self.db.execute(
            "SELECT * FROM wa_site WHERE run_id=? ORDER BY role DESC, name",
            (run_id,)).fetchall()]

    def pages(self, run_id: str, site_key: str | None = None) -> list:
        sql = "SELECT * FROM wa_page WHERE run_id=?"
        args = [run_id]
        if site_key:
            sql += " AND site_key=?"
            args.append(site_key)
        sql += " ORDER BY site_key, depth, url"
        return [dict(r) for r in self.db.execute(sql, args).fetchall()]

    def observations(self, run_id: str, page_key: str | None = None,
                     obs_type: str | None = None) -> list:
        sql = "SELECT * FROM wa_observation WHERE run_id=?"
        args = [run_id]
        if page_key:
            sql += " AND page_key=?"
            args.append(page_key)
        if obs_type:
            sql += " AND obs_type=?"
            args.append(obs_type)
        out = []
        for r in self.db.execute(sql, args).fetchall():
            d = dict(r)
            d["signals"] = _u(d.get("signals"), [])
            d["evidence"] = _u(d.get("evidence"), None) or None
            out.append(d)
        return out

    def findings(self, run_id: str) -> list:
        rows = [dict(r) for r in self.db.execute(
            "SELECT * FROM wa_finding WHERE run_id=?", (run_id,)).fetchall()]
        for d in rows:
            d["evidence"] = _u(d.get("evidence"), [])
        rows.sort(key=lambda d: (PRIORITY_ORDER.index(d["priority"])
                                 if d.get("priority") in PRIORITY_ORDER else 9,
                                 d.get("category") or ""))
        return rows

    def recommendations(self, run_id: str) -> list:
        rows = [dict(r) for r in self.db.execute(
            "SELECT * FROM wa_recommendation WHERE run_id=?",
            (run_id,)).fetchall()]
        for d in rows:
            d["evidence"] = _u(d.get("evidence"), [])
            d["missing_parts"] = _u(d.get("missing_parts"), [])
            d["where"] = d.pop("where_at", "")
            d["complete"] = bool(d.get("complete"))
        rows.sort(key=lambda d: (PRIORITY_ORDER.index(d["priority"])
                                 if d.get("priority") in PRIORITY_ORDER else 9,
                                 d.get("what") or ""))
        return rows

    def run(self, run_id: str) -> dict | None:
        for r in self.runs():
            if r["run_id"] == run_id:
                return r
        return None
