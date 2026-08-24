"""Persistence: matches, current observations, append-only history,
changes and exceptions.

Two rules the schema enforces rather than trusts:
  * history and exceptions are insert-only — no update path exists
  * invalidating a match keeps the prior decision and its reason
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .models import (
    Change, ClaraProduct, Exception_, Match, Observation,
    CONFIRMED, PROBABLE,
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS clara_product (
  product_id TEXT PRIMARY KEY,
  name TEXT, url TEXT, price REAL, currency TEXT,
  rating REAL, rating_count INTEGER, image_url TEXT,
  fmt TEXT, category TEXT, specs TEXT,
  description_lang TEXT, in_scope INTEGER,
  updated_at TEXT
);

CREATE TABLE IF NOT EXISTS match (
  clara_product_id TEXT NOT NULL,
  competitor_key TEXT NOT NULL,
  competitor_brand TEXT,
  status TEXT NOT NULL,
  match_score REAL,
  comparison_basis TEXT,
  competitor_url TEXT,
  competitor_product_name TEXT,
  fingerprint TEXT,
  evidence TEXT,
  rejected TEXT,
  validated_at TEXT,
  ttl_days INTEGER,
  invalidated_at TEXT,
  invalid_reason TEXT,
  discovery_used INTEGER,
  system_price REAL,
  separately_available INTEGER,
  PRIMARY KEY (clara_product_id, competitor_key)
);

CREATE TABLE IF NOT EXISTS observation (
  clara_product_id TEXT NOT NULL,
  competitor_key TEXT NOT NULL,
  observed_at TEXT NOT NULL,
  payload TEXT NOT NULL,
  PRIMARY KEY (clara_product_id, competitor_key)
);

-- insert-only. Every match decision ever written, including invalidations, so
-- that replacing an invalid match never erases why it was invalidated.
CREATE TABLE IF NOT EXISTS match_history (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  clara_product_id TEXT NOT NULL,
  competitor_key TEXT NOT NULL,
  recorded_at TEXT NOT NULL,
  status TEXT,
  match_score REAL,
  competitor_url TEXT,
  competitor_product_name TEXT,
  fingerprint TEXT,
  invalidated_at TEXT,
  invalid_reason TEXT,
  payload TEXT
);

-- insert-only
CREATE TABLE IF NOT EXISTS observation_history (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id TEXT,
  clara_product_id TEXT NOT NULL,
  competitor_key TEXT NOT NULL,
  observed_at TEXT NOT NULL,
  payload TEXT NOT NULL
);

-- insert-only
CREATE TABLE IF NOT EXISTS change_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id TEXT,
  clara_product_id TEXT,
  competitor_key TEXT,
  change_type TEXT,
  previous_value TEXT,
  new_value TEXT,
  delta_pct REAL,
  flagged INTEGER,
  detected_at TEXT
);

-- insert-only
CREATE TABLE IF NOT EXISTS exception_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id TEXT,
  clara_product_id TEXT,
  competitor_key TEXT,
  kind TEXT,
  attempted TEXT,
  observed TEXT,
  why_unresolved TEXT,
  recommended_action TEXT,
  blocks_downstream TEXT,
  evidence TEXT,
  created_at TEXT,
  resolved_at TEXT
);

CREATE TABLE IF NOT EXISTS run (
  run_id TEXT PRIMARY KEY,
  started_at TEXT, finished_at TEXT,
  config TEXT, summary TEXT
);

-- §14 competitors + product_competitor_targets: assignment is data, not code.
CREATE TABLE IF NOT EXISTS competitor (
  key TEXT PRIMARY KEY,
  brand TEXT, tier TEXT, market TEXT,
  domains TEXT, retail_domains TEXT, sitemaps TEXT,
  segments TEXT, enabled INTEGER, notes TEXT, updated_at TEXT
);

CREATE TABLE IF NOT EXISTS product_competitor_target (
  clara_product_id TEXT NOT NULL,
  competitor_key TEXT NOT NULL,
  priority INTEGER,
  assigned_by TEXT,
  assigned_at TEXT,
  PRIMARY KEY (clara_product_id, competitor_key)
);

-- §14 competitor_products: the stable current competitor identity.
CREATE TABLE IF NOT EXISTS competitor_product (
  competitor_key TEXT NOT NULL,
  canonical_url TEXT NOT NULL,
  source_product_id TEXT, sku TEXT,
  product_name TEXT, brand TEXT, category_path TEXT,
  first_seen_at TEXT, last_seen_at TEXT,
  PRIMARY KEY (competitor_key, canonical_url)
);

CREATE TABLE IF NOT EXISTS competitor_variant (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  competitor_key TEXT, canonical_url TEXT,
  option_key TEXT, sku TEXT, price TEXT, currency TEXT,
  availability TEXT, source TEXT, observed_at TEXT
);

CREATE TABLE IF NOT EXISTS competitor_image (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  competitor_key TEXT, canonical_url TEXT,
  position INTEGER, url TEXT, role TEXT, observed_at TEXT
);

-- §14 match_events: insert-only lifecycle log.
CREATE TABLE IF NOT EXISTS match_event (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id TEXT,
  clara_product_id TEXT, competitor_key TEXT,
  event TEXT,                -- created|confirmed|probable|invalidated|ambiguous|no_match|reviewed|reactivated
  from_status TEXT, to_status TEXT,
  reason TEXT, evidence TEXT, created_at TEXT
);

-- §14 errors: per-pair failures that did not stop the run.
CREATE TABLE IF NOT EXISTS error_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id TEXT, clara_product_id TEXT, competitor_key TEXT,
  stage TEXT, method TEXT, signal TEXT, detail TEXT, created_at TEXT
);

-- §14 source_hints: reusable, reviewable discovery/parsing mappings.
CREATE TABLE IF NOT EXISTS source_hint (
  competitor_key TEXT NOT NULL,
  hint_key TEXT NOT NULL,
  hint_value TEXT,
  confirmed_at TEXT,
  PRIMARY KEY (competitor_key, hint_key)
);
"""


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _j(v: Any) -> str:
    return json.dumps(v, ensure_ascii=False)


class Store:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)
        # Additive migration: a column introduced after a database was created.
        cols = {r[1] for r in self.db.execute("PRAGMA table_info(clara_product)")}
        if "segment" not in cols:
            self.db.execute("ALTER TABLE clara_product ADD COLUMN segment TEXT")
        self.db.commit()

    def close(self) -> None:
        self.db.close()

    # ---------------- Clara catalog ----------------

    def upsert_product(self, p: ClaraProduct) -> None:
        self.db.execute(
            """INSERT INTO clara_product
               (product_id,name,url,price,currency,rating,rating_count,image_url,
                fmt,segment,category,specs,description_lang,in_scope,updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(product_id) DO UPDATE SET
                 name=excluded.name, url=excluded.url, price=excluded.price,
                 currency=excluded.currency, rating=excluded.rating,
                 rating_count=excluded.rating_count, image_url=excluded.image_url,
                 fmt=excluded.fmt, segment=excluded.segment,
                 category=excluded.category, specs=excluded.specs,
                 description_lang=excluded.description_lang,
                 in_scope=excluded.in_scope, updated_at=excluded.updated_at""",
            (p.product_id, p.name, p.url, p.price, p.currency, p.rating,
             p.rating_count, p.image_url, p.fmt, p.segment, p.category, _j(p.specs),
             p.description_lang, int(p.in_scope), utcnow()),
        )
        self.db.commit()

    def get_products(self, ids: list[str] | None = None) -> list[ClaraProduct]:
        if ids:
            q = "SELECT * FROM clara_product WHERE product_id IN (%s)" % ",".join("?" * len(ids))
            rows = self.db.execute(q, ids).fetchall()
            order = {pid: i for i, pid in enumerate(ids)}
            rows = sorted(rows, key=lambda r: order.get(r["product_id"], 999))
        else:
            rows = self.db.execute(
                "SELECT * FROM clara_product WHERE in_scope=1 ORDER BY price DESC"
            ).fetchall()
        return [
            ClaraProduct(
                product_id=r["product_id"], name=r["name"], url=r["url"],
                price=r["price"], currency=r["currency"], rating=r["rating"],
                rating_count=r["rating_count"], image_url=r["image_url"],
                fmt=r["fmt"], segment=(r["segment"] or "unknown"),
                category=r["category"],
                specs=json.loads(r["specs"] or "{}"),
                description_lang=r["description_lang"], in_scope=bool(r["in_scope"]),
            )
            for r in rows
        ]

    # ---------------- matches ----------------

    def get_match(self, product_id: str, competitor_key: str) -> Match | None:
        r = self.db.execute(
            "SELECT * FROM match WHERE clara_product_id=? AND competitor_key=?",
            (product_id, competitor_key),
        ).fetchone()
        if not r:
            return None
        return Match(
            clara_product_id=r["clara_product_id"], competitor_key=r["competitor_key"],
            competitor_brand=r["competitor_brand"], status=r["status"],
            match_score=r["match_score"] or 0.0, comparison_basis=r["comparison_basis"],
            competitor_url=r["competitor_url"],
            competitor_product_name=r["competitor_product_name"],
            fingerprint=r["fingerprint"],
            evidence=json.loads(r["evidence"] or "[]"),
            rejected=json.loads(r["rejected"] or "[]"),
            validated_at=r["validated_at"], ttl_days=r["ttl_days"] or 30,
            invalidated_at=r["invalidated_at"], invalid_reason=r["invalid_reason"],
            discovery_used=bool(r["discovery_used"]),
            system_price=r["system_price"],
            separately_available=(None if r["separately_available"] is None
                                  else bool(r["separately_available"])),
        )

    def get_matches_for_product(self, product_id: str) -> list[Match]:
        rows = self.db.execute(
            "SELECT competitor_key FROM match WHERE clara_product_id=?", (product_id,)
        ).fetchall()
        out = []
        for r in rows:
            m = self.get_match(product_id, r["competitor_key"])
            if m:
                out.append(m)
        return out

    def put_match(self, m: Match) -> None:
        self.db.execute(
            """INSERT INTO match
               (clara_product_id,competitor_key,competitor_brand,status,match_score,
                comparison_basis,competitor_url,competitor_product_name,fingerprint,
                evidence,rejected,validated_at,ttl_days,invalidated_at,invalid_reason,
                discovery_used,system_price,separately_available)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(clara_product_id,competitor_key) DO UPDATE SET
                 competitor_brand=excluded.competitor_brand,
                 status=excluded.status, match_score=excluded.match_score,
                 comparison_basis=excluded.comparison_basis,
                 competitor_url=excluded.competitor_url,
                 competitor_product_name=excluded.competitor_product_name,
                 fingerprint=excluded.fingerprint, evidence=excluded.evidence,
                 rejected=excluded.rejected, validated_at=excluded.validated_at,
                 ttl_days=excluded.ttl_days, invalidated_at=excluded.invalidated_at,
                 invalid_reason=excluded.invalid_reason,
                 discovery_used=excluded.discovery_used,
                 system_price=excluded.system_price,
                 separately_available=excluded.separately_available""",
            (m.clara_product_id, m.competitor_key, m.competitor_brand, m.status,
             m.match_score, m.comparison_basis, m.competitor_url,
             m.competitor_product_name, m.fingerprint, _j(m.evidence), _j(m.rejected),
             m.validated_at, m.ttl_days, m.invalidated_at, m.invalid_reason,
             int(m.discovery_used), m.system_price,
             None if m.separately_available is None else int(m.separately_available)),
        )
        # Append-only: the current row above is replaced on re-discovery, so the
        # decision trail — including the reason a prior match was invalidated —
        # is preserved here instead.
        self.db.execute(
            """INSERT INTO match_history
               (clara_product_id,competitor_key,recorded_at,status,match_score,
                competitor_url,competitor_product_name,fingerprint,
                invalidated_at,invalid_reason,payload)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (m.clara_product_id, m.competitor_key, utcnow(), m.status, m.match_score,
             m.competitor_url, m.competitor_product_name, m.fingerprint,
             m.invalidated_at, m.invalid_reason, _j(m.as_dict())),
        )
        self.db.commit()

    def match_history_for(self, product_id: str, competitor_key: str,
                          limit: int = 20) -> list[dict]:
        rows = self.db.execute(
            """SELECT recorded_at,status,match_score,competitor_url,
                      competitor_product_name,fingerprint,invalidated_at,invalid_reason
               FROM match_history
               WHERE clara_product_id=? AND competitor_key=?
               ORDER BY id DESC LIMIT ?""",
            (product_id, competitor_key, limit),
        ).fetchall()
        return [dict(r) for r in rows]

    def invalidations_for(self, product_id: str, competitor_key: str) -> list[dict]:
        """Every recorded invalidation for this pair, newest first."""
        rows = self.db.execute(
            """SELECT recorded_at,status,competitor_url,competitor_product_name,
                      invalid_reason
               FROM match_history
               WHERE clara_product_id=? AND competitor_key=?
                 AND invalid_reason IS NOT NULL
               ORDER BY id DESC""",
            (product_id, competitor_key),
        ).fetchall()
        return [dict(r) for r in rows]

    def match_is_valid(self, m: Match, ttl_days: int, allowed_hosts: set[str]) -> tuple[bool, str]:
        """Section 5 of the agent instruction, in code."""
        if m.status not in (CONFIRMED, PROBABLE):
            return False, f"status is {m.status}, not a usable match"
        if m.invalidated_at:
            return False, f"previously invalidated: {m.invalid_reason}"
        if not m.competitor_url:
            return False, "no competitor_url stored"
        from .access import host_allowed
        if not host_allowed(m.competitor_url, allowed_hosts):
            return False, "stored competitor host is no longer in the allowlist"
        if not m.validated_at:
            return False, "never validated"
        try:
            when = datetime.fromisoformat(m.validated_at)
        except ValueError:
            return False, "validated_at unparseable"
        if when < datetime.now(timezone.utc) - timedelta(days=ttl_days):
            return False, f"validated_at is older than ttl_days={ttl_days}"
        if self.open_exceptions_for(m.clara_product_id, m.competitor_key):
            return False, "an unresolved exception is open against this pair"
        return True, "stored match is within ttl and still allowlisted"

    def invalidate_match(self, m: Match, reason: str) -> None:
        m.invalidated_at = utcnow()
        m.invalid_reason = reason
        self.put_match(m)

    # ---------------- observations & history ----------------

    def get_observation(self, product_id: str, competitor_key: str) -> dict | None:
        r = self.db.execute(
            "SELECT payload FROM observation WHERE clara_product_id=? AND competitor_key=?",
            (product_id, competitor_key),
        ).fetchone()
        return json.loads(r["payload"]) if r else None

    def put_observation(self, run_id: str, o: Observation) -> None:
        # The engine attaches the full §10 field set as `payload`; persist that
        # when present so nothing is lost to the narrower dataclass shape.
        full = getattr(o, "payload", None)
        payload = _j(full if isinstance(full, dict) else o.as_dict())
        self.db.execute(
            """INSERT INTO observation (clara_product_id,competitor_key,observed_at,payload)
               VALUES (?,?,?,?)
               ON CONFLICT(clara_product_id,competitor_key) DO UPDATE SET
                 observed_at=excluded.observed_at, payload=excluded.payload""",
            (o.clara_product_id, o.competitor_key, o.observed_at, payload),
        )
        # append-only history
        self.db.execute(
            """INSERT INTO observation_history
               (run_id,clara_product_id,competitor_key,observed_at,payload)
               VALUES (?,?,?,?,?)""",
            (run_id, o.clara_product_id, o.competitor_key, o.observed_at, payload),
        )
        self.db.commit()

    def history_for(self, product_id: str, competitor_key: str, limit: int = 20) -> list[dict]:
        rows = self.db.execute(
            """SELECT run_id,observed_at,payload FROM observation_history
               WHERE clara_product_id=? AND competitor_key=?
               ORDER BY id DESC LIMIT ?""",
            (product_id, competitor_key, limit),
        ).fetchall()
        return [
            {"run_id": r["run_id"], "observed_at": r["observed_at"],
             **json.loads(r["payload"])}
            for r in rows
        ]

    # ---------------- changes ----------------

    def add_change(self, run_id: str, c: Change) -> None:
        self.db.execute(
            """INSERT INTO change_log
               (run_id,clara_product_id,competitor_key,change_type,previous_value,
                new_value,delta_pct,flagged,detected_at)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (run_id, c.clara_product_id, c.competitor_key, c.change_type,
             _j(c.previous_value), _j(c.new_value), c.delta_pct,
             int(c.flagged), c.detected_at or utcnow()),
        )
        self.db.commit()

    def changes_for_run(self, run_id: str) -> list[dict]:
        rows = self.db.execute(
            "SELECT * FROM change_log WHERE run_id=? ORDER BY flagged DESC, id",
            (run_id,),
        ).fetchall()
        return [
            {**dict(r),
             "previous_value": json.loads(r["previous_value"]),
             "new_value": json.loads(r["new_value"])}
            for r in rows
        ]

    # ---------------- exceptions ----------------

    def add_exception(self, e: Exception_) -> None:
        self.db.execute(
            """INSERT INTO exception_log
               (run_id,clara_product_id,competitor_key,kind,attempted,observed,
                why_unresolved,recommended_action,blocks_downstream,evidence,created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (e.run_id, e.clara_product_id, e.competitor_key, e.kind, e.attempted,
             e.observed, e.why_unresolved, e.recommended_action, e.blocks_downstream,
             _j(e.evidence), e.created_at or utcnow()),
        )
        self.db.commit()

    def open_exceptions_for(self, product_id: str, competitor_key: str) -> list[dict]:
        rows = self.db.execute(
            """SELECT * FROM exception_log
               WHERE clara_product_id=? AND competitor_key=? AND resolved_at IS NULL""",
            (product_id, competitor_key),
        ).fetchall()
        return [dict(r) for r in rows]

    def exceptions_for_run(self, run_id: str) -> list[dict]:
        rows = self.db.execute(
            "SELECT * FROM exception_log WHERE run_id=? ORDER BY id", (run_id,)
        ).fetchall()
        return [{**dict(r), "evidence": json.loads(r["evidence"] or "[]")} for r in rows]

    def consecutive_failures(self, product_id: str, competitor_key: str) -> int:
        rows = self.db.execute(
            """SELECT DISTINCT run_id FROM exception_log
               WHERE clara_product_id=? AND competitor_key=?
               ORDER BY id DESC LIMIT 5""",
            (product_id, competitor_key),
        ).fetchall()
        return len(rows)

    # ---------------- competitors & targets (§14) ----------------

    def upsert_competitor(self, c) -> None:
        self.db.execute(
            """INSERT INTO competitor
               (key,brand,tier,market,domains,retail_domains,sitemaps,segments,
                enabled,notes,updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(key) DO UPDATE SET
                 brand=excluded.brand, tier=excluded.tier, market=excluded.market,
                 domains=excluded.domains, retail_domains=excluded.retail_domains,
                 sitemaps=excluded.sitemaps, segments=excluded.segments,
                 enabled=excluded.enabled, notes=excluded.notes,
                 updated_at=excluded.updated_at""",
            (c.key, c.brand, c.tier, c.market, _j(c.domains), _j(c.retail_domains),
             _j(c.sitemaps), _j(c.segments), int(c.enabled), c.notes, utcnow()),
        )
        self.db.commit()

    def get_competitors(self) -> list[dict]:
        rows = self.db.execute("SELECT * FROM competitor ORDER BY key").fetchall()
        out = []
        for r in rows:
            d = dict(r)
            for k in ("domains", "retail_domains", "sitemaps", "segments"):
                d[k] = json.loads(d.get(k) or "[]")
            d["enabled"] = bool(d.get("enabled"))
            out.append(d)
        return out

    def set_targets(self, product_id: str, keys: list[str],
                    assigned_by: str = "assignment_rules") -> None:
        for i, k in enumerate(keys):
            self.db.execute(
                """INSERT INTO product_competitor_target
                   (clara_product_id,competitor_key,priority,assigned_by,assigned_at)
                   VALUES (?,?,?,?,?)
                   ON CONFLICT(clara_product_id,competitor_key) DO UPDATE SET
                     priority=excluded.priority, assigned_by=excluded.assigned_by,
                     assigned_at=excluded.assigned_at""",
                (product_id, k, i, assigned_by, utcnow()),
            )
        self.db.commit()

    def get_targets(self, product_id: str) -> list[str]:
        rows = self.db.execute(
            """SELECT competitor_key FROM product_competitor_target
               WHERE clara_product_id=? ORDER BY priority""", (product_id,)).fetchall()
        return [r["competitor_key"] for r in rows]

    # ---------------- competitor products, variants, images ----------------

    def upsert_competitor_product(self, competitor_key: str, ex) -> None:
        url = ex.canonical_url or ex.url
        now = utcnow()
        self.db.execute(
            """INSERT INTO competitor_product
               (competitor_key,canonical_url,source_product_id,sku,product_name,
                brand,category_path,first_seen_at,last_seen_at)
               VALUES (?,?,?,?,?,?,?,?,?)
               ON CONFLICT(competitor_key,canonical_url) DO UPDATE SET
                 source_product_id=excluded.source_product_id,
                 sku=excluded.sku, product_name=excluded.product_name,
                 brand=excluded.brand, category_path=excluded.category_path,
                 last_seen_at=excluded.last_seen_at""",
            (competitor_key, url, ex.source_product_id, ex.sku, ex.product_name,
             ex.brand, _j(ex.category_path), now, now),
        )
        # Variants and images are replaced per observation: they describe the page
        # as it is now, while observation_history keeps the trail over time.
        self.db.execute(
            "DELETE FROM competitor_variant WHERE competitor_key=? AND canonical_url=?",
            (competitor_key, url))
        for v in ex.variants:
            self.db.execute(
                """INSERT INTO competitor_variant
                   (competitor_key,canonical_url,option_key,sku,price,currency,
                    availability,source,observed_at)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (competitor_key, url, v.get("option_key"), v.get("sku"),
                 v.get("price"), v.get("currency"), v.get("availability"),
                 v.get("source"), now))
        self.db.execute(
            "DELETE FROM competitor_image WHERE competitor_key=? AND canonical_url=?",
            (competitor_key, url))
        for im in ex.images:
            self.db.execute(
                """INSERT INTO competitor_image
                   (competitor_key,canonical_url,position,url,role,observed_at)
                   VALUES (?,?,?,?,?,?)""",
                (competitor_key, url, im.get("position"), im.get("url"),
                 im.get("role"), now))
        self.db.commit()

    def get_competitor_product(self, competitor_key: str, url: str) -> dict | None:
        r = self.db.execute(
            "SELECT * FROM competitor_product WHERE competitor_key=? AND canonical_url=?",
            (competitor_key, url)).fetchone()
        if not r:
            return None
        d = dict(r)
        d["category_path"] = json.loads(d.get("category_path") or "[]")
        d["variants"] = [dict(x) for x in self.db.execute(
            "SELECT * FROM competitor_variant WHERE competitor_key=? AND canonical_url=?",
            (competitor_key, url)).fetchall()]
        d["images"] = [dict(x) for x in self.db.execute(
            """SELECT * FROM competitor_image WHERE competitor_key=? AND canonical_url=?
               ORDER BY position""", (competitor_key, url)).fetchall()]
        return d

    # ---------------- match events (§14, §15) ----------------

    def add_match_event(self, run_id: str, product_id: str, competitor_key: str,
                        event: str, from_status: str | None, to_status: str | None,
                        reason: str, evidence: list[str] | None = None) -> None:
        self.db.execute(
            """INSERT INTO match_event
               (run_id,clara_product_id,competitor_key,event,from_status,to_status,
                reason,evidence,created_at)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (run_id, product_id, competitor_key, event, from_status, to_status,
             reason, _j(evidence or []), utcnow()))
        self.db.commit()

    def match_events_for(self, product_id: str, competitor_key: str) -> list[dict]:
        rows = self.db.execute(
            """SELECT * FROM match_event
               WHERE clara_product_id=? AND competitor_key=? ORDER BY id DESC""",
            (product_id, competitor_key)).fetchall()
        return [{**dict(r), "evidence": json.loads(r["evidence"] or "[]")} for r in rows]

    def match_events_for_run(self, run_id: str) -> list[dict]:
        rows = self.db.execute(
            "SELECT * FROM match_event WHERE run_id=? ORDER BY id", (run_id,)).fetchall()
        return [{**dict(r), "evidence": json.loads(r["evidence"] or "[]")} for r in rows]

    # ---------------- errors (§17) ----------------

    def add_error(self, run_id: str, product_id: str, competitor_key: str,
                  stage: str, method: str, signal: str, detail: str) -> None:
        self.db.execute(
            """INSERT INTO error_log
               (run_id,clara_product_id,competitor_key,stage,method,signal,detail,created_at)
               VALUES (?,?,?,?,?,?,?,?)""",
            (run_id, product_id, competitor_key, stage, method, signal,
             detail[:2000], utcnow()))
        self.db.commit()

    def errors_for_run(self, run_id: str) -> list[dict]:
        rows = self.db.execute(
            "SELECT * FROM error_log WHERE run_id=? ORDER BY id", (run_id,)).fetchall()
        return [dict(r) for r in rows]

    # ---------------- source hints (§21) ----------------

    def put_hint(self, competitor_key: str, key: str, value) -> None:
        self.db.execute(
            """INSERT INTO source_hint (competitor_key,hint_key,hint_value,confirmed_at)
               VALUES (?,?,?,?)
               ON CONFLICT(competitor_key,hint_key) DO UPDATE SET
                 hint_value=excluded.hint_value, confirmed_at=excluded.confirmed_at""",
            (competitor_key, key, _j(value), utcnow()))
        self.db.commit()

    def get_hints(self, competitor_key: str) -> dict:
        rows = self.db.execute(
            "SELECT hint_key,hint_value FROM source_hint WHERE competitor_key=?",
            (competitor_key,)).fetchall()
        return {r["hint_key"]: json.loads(r["hint_value"] or "null") for r in rows}

    # ---------------- resume (§16) ----------------

    def completed_pairs(self, run_id: str) -> set[tuple[str, str]]:
        """Pairs already finished in this run, so a resumed run does not repeat
        completed valid refreshes (§16)."""
        rows = self.db.execute(
            """SELECT DISTINCT clara_product_id, competitor_key FROM match_event
               WHERE run_id=?""", (run_id,)).fetchall()
        return {(r["clara_product_id"], r["competitor_key"]) for r in rows}

    def run_in_progress(self) -> str | None:
        r = self.db.execute(
            "SELECT run_id FROM run WHERE finished_at IS NULL ORDER BY started_at DESC LIMIT 1"
        ).fetchone()
        return r["run_id"] if r else None

    # ---------------- runs ----------------

    def start_run(self, run_id: str, config: dict) -> None:
        self.db.execute(
            "INSERT OR REPLACE INTO run (run_id,started_at,config) VALUES (?,?,?)",
            (run_id, utcnow(), _j(config)),
        )
        self.db.commit()

    def finish_run(self, run_id: str, summary: dict) -> None:
        self.db.execute(
            "UPDATE run SET finished_at=?, summary=? WHERE run_id=?",
            (utcnow(), _j(summary), run_id),
        )
        self.db.commit()

    def get_run(self, run_id: str) -> dict | None:
        r = self.db.execute("SELECT * FROM run WHERE run_id=?", (run_id,)).fetchone()
        if not r:
            return None
        return {**dict(r), "config": json.loads(r["config"] or "{}"),
                "summary": json.loads(r["summary"] or "{}")}

    def latest_run_id(self) -> str | None:
        r = self.db.execute(
            "SELECT run_id FROM run ORDER BY started_at DESC LIMIT 1"
        ).fetchone()
        return r["run_id"] if r else None
