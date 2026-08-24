"""Storage for the offer sweep.

Insert-once, keyed by competitor + the wording + the URL it was read from. The
same banner re-read on a later sweep updates `last_seen_at` and nothing else, so
`first_seen_at` stays true and the page can say how long a sale has been running
— which is the one thing a single sweep can never tell you.

Statuses here are deliberately thinner than the ones on `intel_offer`. That table
tracks an offer attached to a *product* whose price can be re-checked, so it can
distinguish EXPIRED from UNKNOWN. A storefront banner has no product behind it, so
the honest set is:

    RUNNING   seen on the most recent sweep
    GONE      the storefront was read on the latest sweep and this is not on it
    UNKNOWN   the storefront could not be read on the latest sweep

Same principle as the product-level table: a page we could not read never makes an
offer expired.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS swept_offer (
  offer_key      TEXT PRIMARY KEY,
  competitor_key TEXT NOT NULL,
  competitor     TEXT NOT NULL,
  mechanism      TEXT,
  wording        TEXT NOT NULL,
  url            TEXT,
  via            TEXT,
  currency       TEXT,
  confidence     TEXT,
  status         TEXT NOT NULL,
  first_seen_at  TEXT,
  last_seen_at   TEXT,
  sweep_id       TEXT
);
CREATE INDEX IF NOT EXISTS ix_swept_comp ON swept_offer(competitor_key);

CREATE TABLE IF NOT EXISTS swept_sweep (
  sweep_id   TEXT PRIMARY KEY,
  at         TEXT,
  tried      INTEGER,
  read       INTEGER,
  advertising INTEGER,
  lines      INTEGER,
  refused    INTEGER,
  payload    TEXT
);

CREATE TABLE IF NOT EXISTS swept_status (
  competitor_key TEXT PRIMARY KEY,
  competitor     TEXT,
  pages_read     INTEGER,
  offers         INTEGER,
  refusal        TEXT,
  checked_at     TEXT
);
"""

RUNNING, GONE, UNKNOWN = "RUNNING", "GONE", "UNKNOWN"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _key(competitor_key: str, wording: str, url: str) -> str:
    raw = f"{competitor_key}|{wording.strip().lower()[:120]}|{url}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


class OfferStore:
    def __init__(self, path: Path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(path), check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)
        self.db.commit()

    def close(self) -> None:
        self.db.close()

    def sweep_count(self) -> int:
        return self.db.execute("SELECT COUNT(*) FROM swept_sweep").fetchone()[0]

    def record(self, result: dict) -> dict:
        sweep_id = f"o{self.sweep_count() + 1}"
        stamp = result.get("swept_at") or _now()
        seen_keys = set()
        new = 0

        for o in result["offers"]:
            k = _key(o["competitor_key"], o["wording"], o["url"] or "")
            seen_keys.add(k)
            row = self.db.execute(
                "SELECT first_seen_at FROM swept_offer WHERE offer_key=?",
                (k,)).fetchone()
            if row:
                self.db.execute(
                    "UPDATE swept_offer SET last_seen_at=?, status=?, "
                    "sweep_id=? WHERE offer_key=?",
                    (stamp, RUNNING, sweep_id, k))
                continue
            new += 1
            self.db.execute(
                """INSERT INTO swept_offer
                   (offer_key, competitor_key, competitor, mechanism, wording,
                    url, via, currency, confidence, status, first_seen_at,
                    last_seen_at, sweep_id)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (k, o["competitor_key"], o["competitor"], o["mechanism"],
                 o["wording"], o["url"], o["via"], o.get("currency_on_page") or "",
                 o["confidence"], RUNNING, stamp, stamp, sweep_id))

        # Anything not seen this time: GONE only if the storefront was readable.
        per = result["per_competitor"]
        for r in self.db.execute("SELECT offer_key, competitor_key FROM swept_offer"):
            if r["offer_key"] in seen_keys:
                continue
            info = per.get(r["competitor_key"])
            if info is None:
                continue
            status = GONE if info["pages_read"] else UNKNOWN
            self.db.execute("UPDATE swept_offer SET status=? WHERE offer_key=?",
                            (status, r["offer_key"]))

        for key, info in per.items():
            self.db.execute(
                """INSERT OR REPLACE INTO swept_status
                   (competitor_key, competitor, pages_read, offers, refusal,
                    checked_at) VALUES (?,?,?,?,?,?)""",
                (key, info["competitor"], info["pages_read"], info["offers"],
                 (info["refusals"][0]["signal"] if info["refusals"] else ""),
                 stamp))

        c = result["counts"]
        self.db.execute(
            """INSERT OR REPLACE INTO swept_sweep
               (sweep_id, at, tried, read, advertising, lines, refused, payload)
               VALUES (?,?,?,?,?,?,?,?)""",
            (sweep_id, stamp, c["competitors_tried"], c["storefronts_read"],
             c["competitors_advertising"], c["offer_lines"], c["refused"],
             json.dumps({"mechanisms": result["mechanisms"],
                         "blocked": result["blocked"]}, ensure_ascii=False)))
        self.db.commit()
        return {"sweep_id": sweep_id, "new": new, "total": len(seen_keys)}

    # ---------------- read ----------------

    def last_sweep(self) -> dict | None:
        r = self.db.execute(
            "SELECT * FROM swept_sweep ORDER BY at DESC LIMIT 1").fetchone()
        return dict(r) if r else None

    def offers(self, status: str = RUNNING) -> list[dict]:
        return [dict(r) for r in self.db.execute(
            "SELECT * FROM swept_offer WHERE status=? "
            "ORDER BY competitor, mechanism", (status,))]

    def by_competitor(self) -> dict:
        out: dict = {}
        for r in self.db.execute(
                "SELECT * FROM swept_offer WHERE status=? ORDER BY mechanism",
                (RUNNING,)):
            d = dict(r)
            out.setdefault(d["competitor"], []).append(d)
        return out

    def status_rows(self) -> list[dict]:
        return [dict(r) for r in self.db.execute(
            "SELECT * FROM swept_status ORDER BY offers DESC, competitor")]

    def build(self) -> dict:
        """What the competitors page needs to show the sweep."""
        sweep = self.last_sweep() or {}
        running = self.offers(RUNNING)
        gone = self.offers(GONE)
        unknown = self.offers(UNKNOWN)
        mech: dict = {}
        for o in running:
            mech[o["mechanism"]] = mech.get(o["mechanism"], 0) + 1
        return {
            "sweep": sweep,
            "running": running,
            "gone": gone,
            "unknown": unknown,
            "by_competitor": self.by_competitor(),
            "status_rows": self.status_rows(),
            "mechanisms": dict(sorted(mech.items(), key=lambda kv: -kv[1])),
            "counts": {
                "running": len(running),
                "gone": len(gone),
                "unknown": len(unknown),
                "brands_advertising": len({o["competitor"] for o in running}),
                "storefronts_read": (sweep.get("read") or 0),
                "tried": (sweep.get("tried") or 0),
                "refused": (sweep.get("refused") or 0),
            },
        }
