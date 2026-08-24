"""Section 8: append-only audit events, and the four provenance labels.

Two requirements, and both are about not being able to lie later.

**8.1 — the field list is the column list.** Actor and role, time, change type,
before and after, the product, the competitor, the match/observation/offer/source,
the related Action and Request, a note, an origin and a correlation ID. Every one
is a parameter of `Audit.record`, and `before`/`after` are required for any change
type that alters a value, because "someone changed the price" without saying from
what is not an audit trail.

**8.2 — corrections never erase.** A correction creates a new version or
observation and preserves the superseded record. `supersede_observation` and
`new_match_version` are the only two ways an operational value changes, and both
are inserts. There is no UPDATE in this module that overwrites an observed value.

**Append-only means no update path exists.** Not "we do not update audit rows" as
a convention — there is no function here that does it, and nothing anywhere in
`ops` writes `UPDATE ops_audit` or `DELETE FROM ops_audit`. A test asserts that
about the source of the whole package, because a convention that is only in a
docstring is one careless commit from being false.

The correlation ID is what makes a resolution readable afterwards. One save writes
several rows — a match version, an observation, an action transition, an audit
event — and they all carry the same correlation ID, so "what happened when Omar
resolved that match" is one query rather than a reconstruction.
"""

from __future__ import annotations

import hashlib
import secrets

from .db import Db, dumps, loads
from .schema import (PROVENANCE_DEFINITION, PROVENANCE_LABEL, Provenance,
                     now_iso)

# Change types that move a value. For these, `before` and `after` are required:
# an audit row that records a price change without the two prices is a note.
VALUE_CHANGES = {
    "match_resolved", "match_confirmed", "match_rejected",
    "no_counterpart_marked", "competitor_url_replaced", "source_replaced",
    "source_marked_unavailable", "manual_observation_entered",
    "user_role_changed", "action_transitioned", "request_transitioned",
}


def new_id(prefix: str = "") -> str:
    """A stable, sortable-enough opaque id.

    Generated in Python rather than by the database so the same value works on
    both engines and is known before the insert — which is what lets one
    transaction write a match version, an observation and an audit row that all
    reference each other.
    """
    raw = secrets.token_hex(8)
    return f"{prefix}{raw}" if prefix else raw


def correlation_id() -> str:
    return "c" + secrets.token_hex(8)


def provenance_badge(label: str) -> dict:
    """A provenance label with its definition, for display.

    Returned as data rather than markup so the same four definitions appear
    identically on a product page, an action card and an agent citation. Section
    10 asks for provenance displayed consistently across all views; one source
    for the words is how that is achieved rather than promised.
    """
    key = label if label in PROVENANCE_LABEL else Provenance.OBSERVED
    return {
        "key": key,
        "label": PROVENANCE_LABEL[key],
        "definition": PROVENANCE_DEFINITION[key],
        "human": key in (Provenance.HUMAN_CONFIRMED, Provenance.MANUAL),
        "automated": key in (Provenance.OBSERVED, Provenance.FEED),
    }


class Audit:
    """Writes audit events and the append-only version rows beside them.

    Every method must be called inside an open `db.tx()`. That is not a
    convenience — it is section 4's atomic-save rule, and `db.exec` enforces it.
    """

    def __init__(self, db: Db):
        self.db = db

    # ------------------------------------------------------------------
    # 8.1
    # ------------------------------------------------------------------

    def record(self, *, actor: str, actor_role: str, change_type: str,
               origin: str, before=None, after=None,
               clara_product_id: str = "", competitor_key: str = "",
               match_id: str = "", obs_id: str = "", offer_id: str = "",
               source_id: str = "", action_id: str = "", request_id: str = "",
               note: str = "", correlation: str = "") -> str:
        """One audit event. Append-only; there is no path that edits it later."""
        if change_type in VALUE_CHANGES and before is None and after is None:
            raise ValueError(
                f"{change_type} moves a value, so section 8.1 requires the "
                f"before and after; refusing to write an audit row that cannot "
                f"say what changed")
        event_id = new_id("ev")
        self.db.exec(
            "INSERT INTO ops_audit (event_id,at,actor,actor_role,change_type,"
            "before_value,after_value,clara_product_id,competitor_key,match_id,"
            "obs_id,offer_id,source_id,action_id,request_id,note,origin,"
            "correlation_id) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (event_id, now_iso(), actor, actor_role, change_type,
             dumps(before) if before is not None else None,
             dumps(after) if after is not None else None,
             clara_product_id or None, competitor_key or None,
             match_id or None, obs_id or None, offer_id or None,
             source_id or None, action_id or None, request_id or None,
             note or None, origin, correlation or correlation_id()))
        return event_id

    # ------------------------------------------------------------------
    # 8.2 — a correction creates a version, it does not overwrite
    # ------------------------------------------------------------------

    def new_match_version(self, match_id: str, *, status: str, provenance: str,
                          actor: str, reason: str = "",
                          confidence: str = "", competitor_product_name: str = "",
                          competitor_url: str = "", payload: dict | None = None
                          ) -> tuple[str, int, dict]:
        """Append a new state for a match and return the superseded one.

        The previous version row is marked `superseded_by` rather than replaced,
        so the history reads forwards: version 1 said probable, version 2 says
        confirmed because a person looked. Returns the before-value so the caller
        can put it straight into the audit row.
        """
        cur = self.db.row(
            "SELECT match_id,status,confidence,competitor_product_name,"
            "competitor_url,provenance,version FROM ops_match WHERE match_id=?",
            (match_id,))
        if not cur:
            raise KeyError(f"no such match: {match_id}")

        before = {
            "status": cur["status"], "confidence": cur["confidence"],
            "competitor_product_name": cur["competitor_product_name"],
            "competitor_url": cur["competitor_url"],
            "provenance": cur["provenance"],
        }
        version = int(cur["version"] or 1) + 1
        vid = new_id("mv")

        prev = self.db.row(
            "SELECT version_id FROM ops_match_version WHERE match_id=? "
            "ORDER BY version DESC LIMIT 1", (match_id,))
        if prev:
            self.db.exec(
                "UPDATE ops_match_version SET superseded_by=? WHERE version_id=?",
                (vid, prev["version_id"]))

        self.db.exec(
            "INSERT INTO ops_match_version (version_id,match_id,version,status,"
            "confidence,competitor_product_name,competitor_url,provenance,actor,"
            "at,reason,payload) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (vid, match_id, version, status,
             confidence or cur["confidence"],
             competitor_product_name or cur["competitor_product_name"],
             competitor_url or cur["competitor_url"],
             provenance, actor, now_iso(), reason,
             dumps(payload or {})))

        self.db.exec(
            "UPDATE ops_match SET status=?, confidence=?, "
            "competitor_product_name=?, competitor_url=?, provenance=?, "
            "version=?, updated_at=? WHERE match_id=?",
            (status, confidence or cur["confidence"],
             competitor_product_name or cur["competitor_product_name"],
             competitor_url or cur["competitor_url"], provenance, version,
             now_iso(), match_id))

        after = {
            "status": status, "confidence": confidence or cur["confidence"],
            "competitor_product_name": (competitor_product_name
                                        or cur["competitor_product_name"]),
            "competitor_url": competitor_url or cur["competitor_url"],
            "provenance": provenance,
        }
        return vid, version, {"before": before, "after": after}

    def supersede_observation(self, *, competitor_key: str, actor: str,
                              provenance: str, match_id: str = "",
                              cp_id: str = "", source_id: str = "",
                              source_url: str = "", price=None,
                              currency: str = "", was_price=None,
                              discount_pct=None, availability: str = "",
                              offer_wording: str = "", observed_at: str = "",
                              last_checked_at: str = "", note: str = "",
                              supersedes: str = "") -> tuple[str, dict]:
        """Insert a new observation; mark the one it replaces as superseded.

        Insert-only by design (8.2). A manually entered price does not overwrite
        the automatically observed one — it sits after it, with its own
        provenance, actor and observation date, and the page shows both.
        """
        if provenance == Provenance.MANUAL and not (actor and observed_at):
            raise ValueError(
                "a manually entered value requires an actor and an observation "
                "date (section 8.2)")

        prev = None
        if supersedes:
            prev = self.db.row(
                "SELECT * FROM ops_observation WHERE obs_id=?", (supersedes,))
        elif match_id:
            prev = self.db.row(
                "SELECT * FROM ops_observation WHERE match_id=? "
                "AND superseded_by IS NULL ORDER BY observed_at DESC LIMIT 1",
                (match_id,))

        obs_id = new_id("ob")
        self.db.exec(
            "INSERT INTO ops_observation (obs_id,competitor_key,cp_id,match_id,"
            "source_id,source_url,price,currency,price_min,price_max,was_price,"
            "discount_pct,availability,offer_wording,observed_at,"
            "last_checked_at,provenance,actor,note,created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (obs_id, competitor_key, cp_id or None, match_id or None,
             source_id or None, source_url or None,
             str(price) if price is not None else None, currency or None,
             None, None,
             str(was_price) if was_price is not None else None,
             str(discount_pct) if discount_pct is not None else None,
             availability or None, offer_wording or None,
             observed_at or now_iso(), last_checked_at or now_iso(),
             provenance, actor, note or None, now_iso()))

        if prev:
            self.db.exec(
                "UPDATE ops_observation SET superseded_by=? WHERE obs_id=?",
                (obs_id, prev["obs_id"]))

        before = ({k: prev.get(k) for k in
                   ("price", "currency", "availability", "offer_wording",
                    "provenance", "observed_at")} if prev else None)
        after = {"price": str(price) if price is not None else None,
                 "currency": currency or None,
                 "availability": availability or None,
                 "offer_wording": offer_wording or None,
                 "provenance": provenance,
                 "observed_at": observed_at or now_iso()}
        return obs_id, {"before": before, "after": after}

    # ------------------------------------------------------------------
    # reading
    # ------------------------------------------------------------------

    def history(self, *, match_id: str = "", action_id: str = "",
                request_id: str = "", competitor_key: str = "",
                clara_product_id: str = "", correlation: str = "",
                limit: int = 200) -> list:
        """The audit trail for one record, newest first."""
        where, args = [], []
        for col, val in (("match_id", match_id), ("action_id", action_id),
                         ("request_id", request_id),
                         ("competitor_key", competitor_key),
                         ("clara_product_id", clara_product_id),
                         ("correlation_id", correlation)):
            if val:
                where.append(f"{col}=?")
                args.append(val)
        sql = "SELECT * FROM ops_audit"
        if where:
            sql += " WHERE " + " OR ".join(where)
        sql += " ORDER BY at DESC, event_id DESC LIMIT ?"
        args.append(limit)
        rows = self.db.rows(sql, args)
        for r in rows:
            r["before_value"] = loads(r.get("before_value"), None)
            r["after_value"] = loads(r.get("after_value"), None)
        return rows

    def match_versions(self, match_id: str) -> list:
        rows = self.db.rows(
            "SELECT * FROM ops_match_version WHERE match_id=? "
            "ORDER BY version DESC", (match_id,))
        for r in rows:
            r["payload"] = loads(r.get("payload"), {})
            r["provenance_badge"] = provenance_badge(r.get("provenance"))
        return rows

    def observations(self, *, match_id: str = "", competitor_key: str = "",
                     include_superseded: bool = True, limit: int = 100) -> list:
        """Observation history. Superseded rows are included by default.

        Including them is the point of 8.2: a page that shows only the current
        value cannot show that it was corrected, and the correction is often the
        interesting part.
        """
        where, args = [], []
        if match_id:
            where.append("match_id=?")
            args.append(match_id)
        if competitor_key:
            where.append("competitor_key=?")
            args.append(competitor_key)
        if not include_superseded:
            where.append("superseded_by IS NULL")
        sql = "SELECT * FROM ops_observation"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY observed_at DESC, obs_id DESC LIMIT ?"
        args.append(limit)
        rows = self.db.rows(sql, args)
        for r in rows:
            r["provenance_badge"] = provenance_badge(r.get("provenance"))
            r["superseded"] = bool(r.get("superseded_by"))
        return rows
