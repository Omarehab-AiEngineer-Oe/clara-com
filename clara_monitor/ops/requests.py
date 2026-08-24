"""Section 5: Send Request — eight types, five statuses, context that prefills.

The whole feature exists so that "I cannot resolve this myself" has somewhere to
go other than a person's memory. Three parts, and each one is a requirement.

**5.1 — eight types, and no ninth.** They are in `RequestType` and validated on
creation. A free-text category would collapse into forty spellings of the same
thing within a month, which is why `OTHER` exists and is the only escape hatch.

**5.2 — context prefills, and it is not re-entered.** Section 12 requires that
Send Request opened from a supported record contains the correct record context
without re-entry. So `context_for()` reads the record and returns the prefilled
subject, the linked ids and a human summary. The user types the question, not the
identifiers — and the identifiers are the part a human gets wrong.

**5.3 — five statuses and a transition table.** `REQUEST_TRANSITIONS` in
`schema.py` is that table as data, and `transition()` is the only way status
changes. The rule that matters most is the small one: a requester replying to a
Waiting request returns it to In progress by itself. Without that the request sits
in Waiting after the requester has already answered, and the admin never learns
they can proceed.

**Conversation messages and data changes are recorded separately.** Section 7 is
explicit about this, and it is a genuine distinction: what an admin *said* in a
reply is a message, and what an admin *changed* is an audited domain write. Mixing
them would let a persuasive reply look like a correction.
"""

from __future__ import annotations

from .audit import Audit, correlation_id, new_id
from .authz import Actor, Permission, own_or_admin, require
from .db import Db, dumps, loads
from .schema import (ChangeType, Origin, REQUEST_STATUS_LABEL,
                     REQUEST_STATUS_MEANING, REQUEST_TRANSITIONS,
                     REQUEST_TYPE_LABEL, REQUESTER_TRANSITIONS, RequestStatus,
                     RequestType, now_iso)

OPEN_STATES = (RequestStatus.NEW, RequestStatus.IN_PROGRESS,
               RequestStatus.WAITING)

# Which record kinds a Request may be attached to (5.2). Named so an unknown kind
# is refused rather than stored as a dangling reference.
CONTEXT_KINDS = ("product", "competitor", "match", "observation", "offer",
                 "action", "source", "conversation")

# The type a record most likely needs, so the form opens on the right one. A
# default that is usually right removes a decision; a default that is always
# "Other" removes the taxonomy.
DEFAULT_TYPE_FOR = {
    "match": RequestType.REVIEW_MATCH,
    "observation": RequestType.VERIFY_PRICE,
    "offer": RequestType.VERIFY_PRICE,
    "source": RequestType.REVIEW_SOURCE,
    "competitor": RequestType.ADD_COMPETITOR,
    "product": RequestType.INVESTIGATE_MISSING,
    "action": RequestType.MANUAL_VERIFICATION,
    "conversation": RequestType.OTHER,
}


class Requests:
    """Create, read, answer and transition Requests."""

    def __init__(self, db: Db):
        self.db = db
        self.audit = Audit(db)

    # ------------------------------------------------------------------
    # 5.2 context
    # ------------------------------------------------------------------

    def context_for(self, kind: str, record_id: str) -> dict:
        """Everything the form needs prefilled, read from the record itself.

        Returns the linked ids AND a human-readable summary. The summary matters:
        a request that says "match m3f9a" is unreadable to the admin who receives
        it, and an admin who has to look up what a request is about will look it
        up wrongly some of the time.
        """
        if kind not in CONTEXT_KINDS:
            return {"kind": "", "ok": False,
                    "why": f"{kind!r} is not a record a request can attach to"}

        ctx = {"kind": kind, "record_id": record_id, "ok": True,
               "suggested_type": DEFAULT_TYPE_FOR.get(kind, RequestType.OTHER)}

        if kind == "match":
            r = self.db.row("SELECT * FROM ops_match WHERE match_id=?",
                            (record_id,))
            if not r:
                return {"kind": kind, "ok": False, "why": "no such match"}
            ctx.update(
                match_id=r["match_id"],
                clara_product_id=r.get("clara_product_id"),
                competitor_key=r.get("competitor_key"),
                subject=(f"Review the match between "
                         f"{r.get('clara_product_name') or r['clara_product_id']} "
                         f"and {r.get('competitor_product_name') or r['competitor_key']}"),
                summary=(f"Clara product: {r.get('clara_product_name')}\n"
                         f"Competitor: {r.get('competitor_key')}\n"
                         f"Their product: {r.get('competitor_product_name')}\n"
                         f"Their URL: {r.get('competitor_url')}\n"
                         f"Current status: {r.get('status')} "
                         f"(confidence {r.get('confidence')}, "
                         f"provenance {r.get('provenance')})"),
                url=r.get("competitor_url"))
        elif kind == "observation":
            r = self.db.row("SELECT * FROM ops_observation WHERE obs_id=?",
                            (record_id,))
            if not r:
                return {"kind": kind, "ok": False, "why": "no such observation"}
            ctx.update(
                competitor_key=r.get("competitor_key"),
                match_id=r.get("match_id"),
                subject=(f"Verify {r.get('price')} {r.get('currency')} for "
                         f"{r.get('competitor_key')}"),
                summary=(f"Observed: {r.get('price')} {r.get('currency')} on "
                         f"{r.get('observed_at')}\n"
                         f"Availability: {r.get('availability')}\n"
                         f"Offer: {r.get('offer_wording') or 'none'}\n"
                         f"Provenance: {r.get('provenance')}\n"
                         f"Source: {r.get('source_url')}"),
                url=r.get("source_url"))
        elif kind == "offer":
            # An offer's record IS the observation that carried its wording —
            # there is no separate offer table, because a promotion is something
            # read off a page at a moment in time, and 8.2 keeps those
            # insert-only. So this reads the observation and frames it as the
            # offer, which is what the reader raising the request is looking at.
            r = self.db.row("SELECT * FROM ops_observation WHERE obs_id=?",
                            (record_id,))
            if not r:
                return {"kind": kind, "ok": False, "why": "no such offer"}
            wording = (r.get("offer_wording") or "").strip()
            others = self.db.value(
                "SELECT COUNT(*) FROM ops_observation WHERE competitor_key=? "
                "AND offer_wording=? AND superseded_by IS NULL",
                (r.get("competitor_key"), r.get("offer_wording")), 0)
            ctx.update(
                competitor_key=r.get("competitor_key"),
                match_id=r.get("match_id"),
                obs_id=r.get("obs_id"),
                subject=(f"Review the offer "
                         f"\"{wording[:60] or 'with no wording recorded'}\" at "
                         f"{r.get('competitor_key')}"),
                summary=(f"Offer: {wording or 'none recorded'}\n"
                         f"Competitor: {r.get('competitor_key')}\n"
                         f"Price alongside it: {r.get('price')} "
                         f"{r.get('currency') or ''}\n"
                         f"Observed: {r.get('observed_at')}\n"
                         f"Provenance: {r.get('provenance')}\n"
                         f"Products carrying this offer: {others}\n"
                         f"Source: {r.get('source_url')}"),
                url=r.get("source_url"))
        elif kind == "source":
            r = self.db.row("SELECT * FROM ops_source WHERE source_id=?",
                            (record_id,))
            if not r:
                return {"kind": kind, "ok": False, "why": "no such source"}
            ctx.update(
                competitor_key=r.get("competitor_key"),
                subject=f"Review the data source {r.get('url')}",
                summary=(f"URL: {r.get('url')}\n"
                         f"Status: {r.get('status')} — "
                         f"{r.get('status_reason') or 'no reason recorded'}\n"
                         f"Failures: {r.get('fail_count')}\n"
                         f"Last read successfully: {r.get('last_ok_at') or 'never'}"),
                url=r.get("url"))
        elif kind == "action":
            r = self.db.row("SELECT * FROM ops_action WHERE action_id=?",
                            (record_id,))
            if not r:
                return {"kind": kind, "ok": False, "why": "no such action"}
            ctx.update(
                action_id=r["action_id"], match_id=r.get("match_id"),
                competitor_key=r.get("competitor_key"),
                clara_product_id=r.get("clara_product_id"),
                subject=f"Help resolve: {(r.get('reason') or '')[:80]}",
                summary=(f"Action type: {r.get('action_type')}\n"
                         f"Reason: {r.get('reason')}\n"
                         f"Status: {r.get('status')}\n"
                         f"Last attempt: {r.get('last_attempt_at')}\n"
                         f"Failure: {r.get('failure_reason') or 'none recorded'}"))
        elif kind == "competitor":
            r = self.db.row("SELECT * FROM ops_competitor WHERE competitor_key=?",
                            (record_id,))
            name = (r or {}).get("brand") or record_id
            ctx.update(competitor_key=record_id,
                       subject=f"Review competitor {name}",
                       summary=f"Competitor: {name}\n"
                               f"Home: {(r or {}).get('home_url') or 'unknown'}",
                       url=(r or {}).get("home_url"))
        elif kind == "product":
            r = self.db.row("SELECT * FROM ops_product WHERE clara_product_id=?",
                            (record_id,))
            if not r:
                # Fall back to the name a match carries, so a request can still
                # be raised about a product the catalogue import has not reached.
                r = self.db.row(
                    "SELECT clara_product_id, clara_product_name AS name "
                    "FROM ops_match WHERE clara_product_id=? LIMIT 1",
                    (record_id,))
            name = (r or {}).get("name") or record_id
            assigned = self.db.value(
                "SELECT COUNT(*) FROM ops_match WHERE clara_product_id=?",
                (record_id,), 0)
            ctx.update(clara_product_id=record_id,
                       subject=f"Investigate missing competitor data for {name}",
                       summary=(f"Clara product: {name} ({record_id})\n"
                                f"Clara price: {(r or {}).get('price')} "
                                f"{(r or {}).get('currency') or ''}\n"
                                f"Competitors assigned: {assigned}"),
                       url=(r or {}).get("url"))
        elif kind == "conversation":
            ctx.update(conversation_id=record_id,
                       subject="Escalated from an agent conversation",
                       summary="See the conversation summary attached below.")
        else:
            ctx.update(subject=f"Request about {kind} {record_id}",
                       summary=f"{kind}: {record_id}")
        return ctx

    # ------------------------------------------------------------------
    # 5.1, 5.2 creation
    # ------------------------------------------------------------------

    def create(self, *, request_type: str, subject: str, description: str,
               actor: Actor, priority: str = "medium", detail_level: str = "",
               context: dict | None = None, action_id: str = "",
               conversation_id: str = "", origin: str = Origin.UI) -> str:
        require(actor, Permission.REQUEST_CREATE)
        if request_type not in REQUEST_TYPE_LABEL:
            raise ValueError(
                f"{request_type!r} is not one of the eight request types")
        if not (subject or "").strip():
            raise ValueError("a request needs a subject")
        if not (description or "").strip():
            raise ValueError("a request needs a description of what is being asked")

        ctx = dict(context or {})
        request_id = new_id("rq")
        corr = correlation_id()
        with self.db.tx():
            self.db.exec(
                "INSERT INTO ops_request (request_id,request_type,subject,"
                "description,requester,status,priority,detail_level,context,"
                "action_id,conversation_id,created_at,updated_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (request_id, request_type, subject.strip(), description.strip(),
                 actor.username, RequestStatus.NEW, priority,
                 detail_level or None, dumps(ctx), action_id or None,
                 conversation_id or None, now_iso(), now_iso()))
            self._status_entry(request_id, actor, "", RequestStatus.NEW,
                               "submitted")
            self.db.exec(
                "INSERT INTO ops_request_message (message_id,request_id,at,"
                "author,author_role,body,is_response) VALUES (?,?,?,?,?,?,?)",
                (new_id("rm"), request_id, now_iso(), actor.username,
                 actor.role, description.strip(), 0))
            if action_id:
                self.db.exec("UPDATE ops_action SET request_id=?, updated_at=? "
                             "WHERE action_id=?",
                             (request_id, now_iso(), action_id))
            self.audit.record(
                actor=actor.username, actor_role=actor.role,
                change_type=ChangeType.REQUEST_CREATED, origin=origin,
                after={"request_type": request_type, "subject": subject.strip(),
                       "status": RequestStatus.NEW},
                request_id=request_id, action_id=action_id,
                match_id=ctx.get("match_id") or "",
                competitor_key=ctx.get("competitor_key") or "",
                clara_product_id=ctx.get("clara_product_id") or "",
                note=subject.strip()[:200], correlation=corr)
        return request_id

    # ------------------------------------------------------------------
    # 5.3 workflow
    # ------------------------------------------------------------------

    def transition(self, request_id: str, to_status: str, actor: Actor, *,
                   note: str = "", resolution: str = "",
                   closure_reason: str = "") -> None:
        """Move a request. The transition table is the only authority.

        The requester gets exactly one transition of their own — Waiting back to
        In progress — because 5.3 gives them that and nothing else. Everything
        else needs the admin permission.
        """
        cur = self._get(request_id)
        frm = cur["status"]
        if to_status not in REQUEST_STATUS_LABEL:
            raise ValueError(f"{to_status!r} is not one of the five statuses")
        if to_status not in REQUEST_TRANSITIONS.get(frm, ()):
            raise ValueError(
                f"{REQUEST_STATUS_LABEL[frm]} cannot move to "
                f"{REQUEST_STATUS_LABEL[to_status]}. From here: "
                + ", ".join(REQUEST_STATUS_LABEL[s]
                            for s in REQUEST_TRANSITIONS.get(frm, ()))
                or "nowhere")

        requester_allowed = to_status in REQUESTER_TRANSITIONS.get(frm, ())
        if requester_allowed:
            own_or_admin(actor, cur["requester"], Permission.REQUEST_ADMIN)
        else:
            require(actor, Permission.REQUEST_ADMIN)

        if to_status == RequestStatus.RESOLVED and not (resolution or "").strip():
            raise ValueError(
                "resolving a request needs the answer or the corrective action "
                "that was supplied — a status change on its own is not a "
                "resolution")
        if to_status == RequestStatus.CLOSED and not (closure_reason or note or "").strip():
            raise ValueError("closing a request needs a closure reason")

        corr = correlation_id()
        with self.db.tx():
            self.db.exec(
                "UPDATE ops_request SET status=?, updated_at=?, resolution=?, "
                "closure_reason=?, resolved_at=?, closed_at=?, owner=? "
                "WHERE request_id=?",
                (to_status, now_iso(),
                 resolution.strip() or cur.get("resolution"),
                 (closure_reason or note).strip() or cur.get("closure_reason"),
                 now_iso() if to_status == RequestStatus.RESOLVED
                 else cur.get("resolved_at"),
                 now_iso() if to_status == RequestStatus.CLOSED
                 else cur.get("closed_at"),
                 cur.get("owner") or (actor.username if actor.is_admin else None),
                 request_id))
            self._status_entry(request_id, actor, frm, to_status, note)
            self.audit.record(
                actor=actor.username, actor_role=actor.role,
                change_type=ChangeType.REQUEST_TRANSITIONED, origin=actor.origin,
                before={"status": frm}, after={"status": to_status},
                request_id=request_id, action_id=cur.get("action_id") or "",
                note=note or resolution or closure_reason, correlation=corr)

    def take(self, request_id: str, actor: Actor) -> None:
        """An admin takes ownership. Moves New to In progress in one step."""
        require(actor, Permission.REQUEST_ADMIN)
        cur = self._get(request_id)
        with self.db.tx():
            self.db.exec("UPDATE ops_request SET owner=?, updated_at=? "
                         "WHERE request_id=?",
                         (actor.username, now_iso(), request_id))
            self.audit.record(
                actor=actor.username, actor_role=actor.role,
                change_type=ChangeType.REQUEST_ASSIGNED, origin=actor.origin,
                before={"owner": cur.get("owner")},
                after={"owner": actor.username}, request_id=request_id)
        if cur["status"] == RequestStatus.NEW:
            self.transition(request_id, RequestStatus.IN_PROGRESS, actor,
                            note=f"taken by {actor.label}")

    def reply(self, request_id: str, body: str, actor: Actor, *,
              is_response: bool = True) -> str:
        """Add a message. A requester reply to Waiting returns it to In progress.

        That auto-transition is 5.3's rule and it is easy to leave out. Without
        it, a requester answers the question and the request stays in Waiting
        forever, because nothing told the admin the wait was over.
        """
        cur = self._get(request_id)
        own_or_admin(actor, cur["requester"], Permission.REQUEST_REPLY)
        if not (body or "").strip():
            raise ValueError("a reply needs a body")

        mid = new_id("rm")
        with self.db.tx():
            self.db.exec(
                "INSERT INTO ops_request_message (message_id,request_id,at,"
                "author,author_role,body,is_response) VALUES (?,?,?,?,?,?,?)",
                (mid, request_id, now_iso(), actor.username, actor.role,
                 body.strip(), 1 if is_response else 0))
            self.db.exec("UPDATE ops_request SET updated_at=? WHERE request_id=?",
                         (now_iso(), request_id))
            self.audit.record(
                actor=actor.username, actor_role=actor.role,
                change_type=ChangeType.REQUEST_ANSWERED, origin=actor.origin,
                after={"message_id": mid, "excerpt": body.strip()[:160]},
                request_id=request_id, note="reply added")

        if cur["status"] == RequestStatus.WAITING \
                and actor.username == cur["requester"]:
            self.transition(request_id, RequestStatus.IN_PROGRESS, actor,
                            note="the requester supplied the information asked for")
        return mid

    def _status_entry(self, request_id: str, actor: Actor, frm: str, to: str,
                      note: str) -> None:
        self.db.exec(
            "INSERT INTO ops_request_status (entry_id,request_id,at,actor,"
            "from_status,to_status,note) VALUES (?,?,?,?,?,?,?)",
            (new_id("rs"), request_id, now_iso(), actor.username, frm or None,
             to, note or None))

    # ------------------------------------------------------------------
    # reading
    # ------------------------------------------------------------------

    def _get(self, request_id: str) -> dict:
        r = self.db.row("SELECT * FROM ops_request WHERE request_id=?",
                        (request_id,))
        if not r:
            raise KeyError(f"no such request: {request_id}")
        return r

    SORTS = {
        "urgency": ("CASE status WHEN 'new' THEN 0 WHEN 'in_progress' THEN 1 "
                    "WHEN 'waiting_for_information' THEN 2 WHEN 'resolved' "
                    "THEN 3 ELSE 4 END, updated_at DESC"),
        "newest": "created_at DESC",
        "oldest": "created_at ASC",
        "updated": "updated_at DESC",
        "type": "request_type ASC, updated_at DESC",
    }
    SORT_LABEL = {"urgency": "Needs attention first", "newest": "Newest first",
                  "oldest": "Oldest first", "updated": "Recently updated",
                  "type": "By type"}

    def list(self, *, actor: Actor, mine: bool = False, status: str = "",
             request_type: str = "", owner: str = "", q: str = "",
             sort: str = "urgency", limit: int = 100, offset: int = 0) -> dict:
        """My Requests for a user; the whole queue for an admin.

        A non-admin is scoped to their own rows here, in the query, not by
        filtering afterwards. Server-side scoping is the same principle as
        server-side authorization: a listing that fetches everything and hides
        most of it has already leaked it.
        """
        where, args = [], []
        if mine or not actor.is_admin:
            where.append("requester=?")
            args.append(actor.username)
        if status == "open":
            where.append("status IN (?,?,?)")
            args += list(OPEN_STATES)
        elif status:
            where.append("status=?")
            args.append(status)
        if request_type:
            where.append("request_type=?")
            args.append(request_type)
        if owner == "unowned":
            where.append("(owner IS NULL OR owner='')")
        elif owner:
            where.append("owner=?")
            args.append(owner)
        if q:
            where.append("(subject LIKE ? OR description LIKE ?)")
            args += [f"%{q}%", f"%{q}%"]

        clause = (" WHERE " + " AND ".join(where)) if where else ""
        total = self.db.value(f"SELECT COUNT(*) FROM ops_request{clause}", args, 0)
        order = self.SORTS.get(sort) or self.SORTS["urgency"]
        rows = self.db.rows(
            f"SELECT * FROM ops_request{clause} ORDER BY {order} "
            f"LIMIT ? OFFSET ?", args + [limit, offset])
        for r in rows:
            self._decorate(r)
        return {"rows": rows, "total": total, "limit": limit,
                "offset": offset, "sort": sort, "counts": self.counts(actor)}

    def counts(self, actor: Actor) -> dict:
        scope = "" if actor.is_admin else " WHERE requester=?"
        args = [] if actor.is_admin else [actor.username]
        by_status = {r["status"]: r["n"] for r in self.db.rows(
            f"SELECT status, COUNT(*) AS n FROM ops_request{scope} "
            f"GROUP BY status", args)}
        return {
            "by_status": by_status,
            "open": sum(by_status.get(s, 0) for s in OPEN_STATES),
            "open_definition": "requests that are new, in progress or waiting "
                               "for information",
            "mine_open": self.db.value(
                "SELECT COUNT(*) FROM ops_request WHERE requester=? "
                "AND status IN (?,?,?)",
                [actor.username] + list(OPEN_STATES), 0),
            "unowned": self.db.value(
                "SELECT COUNT(*) FROM ops_request WHERE status IN (?,?,?) "
                "AND (owner IS NULL OR owner='')", list(OPEN_STATES), 0)
            if actor.is_admin else 0,
            "waiting_on_me": self.db.value(
                "SELECT COUNT(*) FROM ops_request WHERE requester=? "
                "AND status=?", (actor.username, RequestStatus.WAITING), 0),
        }

    def get(self, request_id: str, actor: Actor) -> dict | None:
        r = self.db.row("SELECT * FROM ops_request WHERE request_id=?",
                        (request_id,))
        if not r:
            return None
        if not actor.is_admin and r["requester"] != actor.username:
            require(actor, Permission.REQUEST_ADMIN,
                    "this request belongs to another user")
        self._decorate(r)
        r["messages"] = self.db.rows(
            "SELECT * FROM ops_request_message WHERE request_id=? "
            "ORDER BY at ASC, message_id ASC", (request_id,))
        r["status_history"] = self.db.rows(
            "SELECT * FROM ops_request_status WHERE request_id=? "
            "ORDER BY at ASC, entry_id ASC", (request_id,))
        r["audit"] = self.audit.history(request_id=request_id)
        if r.get("action_id"):
            r["action"] = self.db.row(
                "SELECT * FROM ops_action WHERE action_id=?", (r["action_id"],))
        if r.get("conversation_id"):
            r["conversation"] = self.db.rows(
                "SELECT * FROM ops_message WHERE conversation_id=? "
                "ORDER BY at ASC", (r["conversation_id"],))
        return r

    def _decorate(self, r: dict) -> None:
        r["context"] = loads(r.get("context"), {})
        r["type_label"] = REQUEST_TYPE_LABEL.get(r["request_type"],
                                                 r["request_type"])
        r["status_label"] = REQUEST_STATUS_LABEL.get(r["status"], r["status"])
        r["status_meaning"] = REQUEST_STATUS_MEANING.get(r["status"], "")
        r["next_statuses"] = [
            {"key": s, "label": REQUEST_STATUS_LABEL[s]}
            for s in REQUEST_TRANSITIONS.get(r["status"], ())]
        r["is_open"] = r["status"] in OPEN_STATES
