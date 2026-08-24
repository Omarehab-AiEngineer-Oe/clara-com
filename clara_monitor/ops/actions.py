"""Section 4: the work queue, and both resolution workflows, resolved in-app.

The requirement this replaces is worth naming, because it explains the shape of
the file. The old behaviour was: an ambiguous match produced an escalation entry
in a JSON report, and the page offered an outbound link and some instructional
text. Section 2 lists that as no longer appropriate — "using outbound links and
instructional text as the complete resolution workflow for human Actions" — and
section 12's first two criteria require that a user can resolve each supported
Action *without leaving the application*.

So every resolution is a function here, and each one ends in the same place:

    one domain update + one Action transition + one audit event, one transaction

That is 4's atomic save rule, and it is not advisory. `db.exec` refuses to run
outside a transaction, `_resolve` opens exactly one, and every writer goes through
it. A partial save is not possible rather than merely discouraged.

**4.2, ambiguous matches** — five outcomes: pick a candidate, supply a different
URL, confirm the counterpart, mark No counterpart, add a note. Each records the
resulting match status, the actor, the time, and the before and after values.

**4.3, unreadable sources** — seven outcomes: choose an approved or suggested
alternative, enter a new URL, request verification, enter the observation by hand,
register or select an approved feed/API where the role permits, or mark the source
unavailable with a reason. Manual entry takes price, currency, availability, offer
wording, observed date and last-checked date, because 4.3 lists all six.

**Actions are deduplicated on what they are about.** `dedupe_key` is unique, so a
nightly run that finds the same ambiguous match for the ninth night does not
produce a ninth Action. It updates the existing one's evidence and last attempt.
A queue that grows by one row per night per problem is a queue nobody opens.
"""

from __future__ import annotations

from .audit import Audit, correlation_id, new_id, provenance_badge
from .authz import Actor, Denied, Permission, own_or_admin, require
from .db import Db, dumps, loads
from .schema import (ACTION_STATUS_LABEL, ACTION_TYPE_LABEL,
                     ACTION_OPEN_STATES, ActionStatus, ActionType, ChangeType,
                     MATCH_STATUS_LABEL, MatchStatus, Origin, Provenance,
                     SourceStatus, now_iso)

PRIORITY_ORDER = ("high", "medium", "low")

# What each Action type is asking a person to do. Shown beside the queue item,
# because "ambiguous_match" is a category, not an instruction.
ACTION_ASK = {
    ActionType.AMBIGUOUS_MATCH:
        "Decide which competitor product this Clara product should be compared "
        "against, or record that there is no counterpart.",
    ActionType.UNREADABLE_SOURCE:
        "Give this competitor a source that can be read, or record the value by "
        "hand so the comparison is not simply blank.",
    ActionType.STALE_PRICE:
        "This price has not been re-observed recently enough to rely on. "
        "Confirm it, replace it, or record that the source stopped working.",
    ActionType.MISSING_DATA:
        "A field the comparison needs was never collected. Supply it or record "
        "why it cannot be supplied.",
    ActionType.VERIFICATION_FAILED:
        "A verification attempt did not succeed. Decide whether to retry with a "
        "different source or record the failure.",
}

# The outcomes each type accepts. Used by the page to render only valid controls
# and by the server to refuse anything else — one list, both purposes, so the two
# cannot disagree.
RESOLUTION_OPTIONS = {
    ActionType.AMBIGUOUS_MATCH: (
        "select_candidate", "enter_url", "confirm_counterpart",
        "no_counterpart", "note_only"),
    ActionType.UNREADABLE_SOURCE: (
        "select_alternative_source", "enter_source_url", "request_verification",
        "manual_observation", "select_feed", "register_feed",
        "mark_source_unavailable", "note_only"),
    ActionType.STALE_PRICE: (
        "manual_observation", "request_verification", "enter_source_url",
        "mark_source_unavailable", "note_only"),
    ActionType.MISSING_DATA: (
        "manual_observation", "enter_source_url", "request_verification",
        "note_only"),
    ActionType.VERIFICATION_FAILED: (
        "select_alternative_source", "enter_source_url", "request_verification",
        "manual_observation", "mark_source_unavailable", "note_only"),
}

OPTION_LABEL = {
    "select_candidate": "Select one of the candidate products",
    "enter_url": "Enter a different competitor URL",
    "confirm_counterpart": "Confirm the selected counterpart",
    "no_counterpart": "Mark No counterpart",
    "note_only": "Add a note only",
    "select_alternative_source": "Choose an alternative approved source",
    "enter_source_url": "Enter a new source URL",
    "request_verification": "Request source verification",
    "manual_observation": "Enter competitor data manually",
    "select_feed": "Select an approved feed or API",
    "register_feed": "Register a feed or API",
    "mark_source_unavailable": "Mark this source unavailable",
}

# Which permission each outcome needs. Checked server-side on the operation, so a
# hand-crafted POST is refused exactly as the hidden button would have been.
OPTION_PERMISSION = {
    "select_candidate": Permission.MATCH_RESOLVE,
    "enter_url": Permission.MATCH_RESOLVE,
    "confirm_counterpart": Permission.MATCH_RESOLVE,
    "no_counterpart": Permission.MATCH_RESOLVE,
    "note_only": Permission.ACTION_RESOLVE,
    "select_alternative_source": Permission.SOURCE_REPLACE,
    "enter_source_url": Permission.SOURCE_REPLACE,
    "request_verification": Permission.VERIFICATION_REQUEST,
    "manual_observation": Permission.OBSERVATION_MANUAL,
    "select_feed": Permission.FEED_REGISTER,
    "register_feed": Permission.FEED_REGISTER,
    "mark_source_unavailable": Permission.SOURCE_MARK_UNAVAILABLE,
}


class Actions:
    """The Actions workspace. Reads the queue, and performs every resolution."""

    def __init__(self, db: Db):
        self.db = db
        self.audit = Audit(db)

    # ------------------------------------------------------------------
    # creating
    # ------------------------------------------------------------------

    def open(self, *, action_type: str, reason: str, priority: str = "medium",
             clara_product_id: str = "", clara_product_name: str = "",
             competitor_key: str = "", match_id: str = "", source_id: str = "",
             candidates: list | None = None, evidence: list | None = None,
             failure_reason: str = "", dedupe_key: str = "",
             actor: Actor | None = None, origin: str = Origin.JOB,
             correlation: str = "") -> str:
        """Create an Action, or refresh the existing one for the same subject.

        Idempotent on `dedupe_key`. A collection run that finds the same problem
        every night must not produce a row every night: it updates the evidence
        and the last-attempt time on the Action already open, which is also what
        makes "how long has this been broken" answerable.
        """
        actor = actor or Actor.system(origin)
        key = dedupe_key or "|".join([action_type, clara_product_id or "",
                                      competitor_key or "", match_id or "",
                                      source_id or ""])
        existing = self.db.row(
            "SELECT action_id,status FROM ops_action WHERE dedupe_key=?", (key,))

        with self.db.tx():
            if existing:
                if existing["status"] in ACTION_OPEN_STATES:
                    self.db.exec(
                        "UPDATE ops_action SET evidence=?, last_attempt_at=?, "
                        "failure_reason=?, candidates=?, updated_at=? "
                        "WHERE action_id=?",
                        (dumps(evidence or []), now_iso(), failure_reason or None,
                         dumps(candidates or []), now_iso(),
                         existing["action_id"]))
                    self._activity(existing["action_id"], actor, "reobserved",
                                   "the same condition was found again on a "
                                   "later run")
                    return existing["action_id"]
                # Resolved before and back again: a new Action, and the old one
                # stays resolved so the history is not rewritten.
                reopened = True
            else:
                reopened = False

            action_id = new_id("ac")
            if reopened:
                # Uniquified with the new id rather than a timestamp. `now_iso()`
                # has second precision, so two reopens inside the same second
                # produced the same key and the second one died on the unique
                # index — taking its whole transaction with it.
                key = f"{key}|{action_id}"
            self.db.exec(
                "INSERT INTO ops_action (action_id,action_type,reason,priority,"
                "status,clara_product_id,clara_product_name,competitor_key,"
                "match_id,source_id,candidates,evidence,last_attempt_at,"
                "failure_reason,dedupe_key,created_at,created_by) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (action_id, action_type, reason, priority, ActionStatus.OPEN,
                 clara_product_id or None, clara_product_name or None,
                 competitor_key or None, match_id or None, source_id or None,
                 dumps(candidates or []), dumps(evidence or []), now_iso(),
                 failure_reason or None, key, now_iso(), actor.username))
            self._activity(action_id, actor, "created", reason)
            self.audit.record(
                actor=actor.username, actor_role=actor.role,
                change_type=ChangeType.ACTION_CREATED, origin=origin,
                after={"action_type": action_type, "status": ActionStatus.OPEN,
                       "reason": reason},
                clara_product_id=clara_product_id, competitor_key=competitor_key,
                match_id=match_id, source_id=source_id, action_id=action_id,
                note=reason, correlation=correlation)
        return action_id

    def _activity(self, action_id: str, actor: Actor, kind: str,
                  detail: str = "", from_value: str = "",
                  to_value: str = "") -> None:
        """One line of an Action's chronological history (4.1)."""
        self.db.exec(
            "INSERT INTO ops_action_activity (activity_id,action_id,at,actor,"
            "kind,detail,from_value,to_value) VALUES (?,?,?,?,?,?,?,?)",
            (new_id("aa"), action_id, now_iso(), actor.username, kind,
             detail or None, from_value or None, to_value or None))

    # ------------------------------------------------------------------
    # status and ownership
    # ------------------------------------------------------------------

    def assign(self, action_id: str, assignee: str, actor: Actor) -> None:
        require(actor, Permission.ACTION_ASSIGN)
        cur = self._get(action_id)
        with self.db.tx():
            self.db.exec("UPDATE ops_action SET assignee=?, status=?, "
                         "updated_at=? WHERE action_id=?",
                         (assignee or None,
                          ActionStatus.IN_PROGRESS
                          if cur["status"] == ActionStatus.OPEN
                          else cur["status"], now_iso(), action_id))
            self._activity(action_id, actor, "assigned", "",
                           cur.get("assignee") or "", assignee)
            self.audit.record(
                actor=actor.username, actor_role=actor.role,
                change_type=ChangeType.ACTION_ASSIGNED, origin=actor.origin,
                before={"assignee": cur.get("assignee")},
                after={"assignee": assignee}, action_id=action_id,
                match_id=cur.get("match_id") or "",
                competitor_key=cur.get("competitor_key") or "")

    def schedule(self, action_id: str, actor: Actor, *, priority: str = "",
                 due_date: str = "") -> None:
        """Set an Action's priority and its optional due date (4.1).

        4.1 lists priority and due date among the fields an Action carries, and a
        field nothing can write is a column rather than a field. Both are audited
        with their before and after values, because "who moved this to high
        priority" is exactly the kind of question a queue provokes.
        """
        require(actor, Permission.ACTION_ASSIGN)
        cur = self._get(action_id)
        if priority and priority not in PRIORITY_ORDER:
            raise ValueError(
                f"{priority!r} is not a priority; use one of "
                f"{', '.join(PRIORITY_ORDER)}")
        before = {"priority": cur.get("priority"),
                  "due_date": cur.get("due_date")}
        after = {"priority": priority or cur.get("priority"),
                 "due_date": due_date or None}
        if before == after:
            return
        with self.db.tx():
            self.db.exec(
                "UPDATE ops_action SET priority=?, due_date=?, updated_at=? "
                "WHERE action_id=?",
                (after["priority"], after["due_date"], now_iso(), action_id))
            detail = []
            if before["priority"] != after["priority"]:
                detail.append(f"priority {before['priority']} -> "
                              f"{after['priority']}")
            if before["due_date"] != after["due_date"]:
                detail.append(f"due {before['due_date'] or 'none'} -> "
                              f"{after['due_date'] or 'none'}")
            self._activity(action_id, actor, "scheduled", "; ".join(detail))
            self.audit.record(
                actor=actor.username, actor_role=actor.role,
                change_type=ChangeType.ACTION_ASSIGNED, origin=actor.origin,
                before=before, after=after, action_id=action_id,
                match_id=cur.get("match_id") or "",
                competitor_key=cur.get("competitor_key") or "",
                clara_product_id=cur.get("clara_product_id") or "",
                note="; ".join(detail) or "scheduling changed")

    def claim(self, action_id: str, actor: Actor) -> None:
        """Take an Action yourself. A user may always do this to unowned work."""
        require(actor, Permission.ACTION_RESOLVE)
        cur = self._get(action_id)
        if cur.get("assignee") and cur["assignee"] != actor.username:
            require(actor, Permission.ACTION_ASSIGN,
                    "this action is already assigned to someone else")
        with self.db.tx():
            self.db.exec("UPDATE ops_action SET assignee=?, status=?, "
                         "updated_at=? WHERE action_id=?",
                         (actor.username, ActionStatus.IN_PROGRESS, now_iso(),
                          action_id))
            self._activity(action_id, actor, "claimed", "",
                           cur.get("status") or "", ActionStatus.IN_PROGRESS)
            self.audit.record(
                actor=actor.username, actor_role=actor.role,
                change_type=ChangeType.ACTION_TRANSITIONED, origin=actor.origin,
                before={"status": cur["status"], "assignee": cur.get("assignee")},
                after={"status": ActionStatus.IN_PROGRESS,
                       "assignee": actor.username},
                action_id=action_id)

    def dismiss(self, action_id: str, actor: Actor, reason: str) -> None:
        """Close without resolving. Admin only, and the reason is required."""
        require(actor, Permission.ACTION_DISMISS)
        if not (reason or "").strip():
            raise ValueError("dismissing an action requires a reason")
        cur = self._get(action_id)
        with self.db.tx():
            self.db.exec(
                "UPDATE ops_action SET status=?, resolution_note=?, "
                "resolved_at=?, resolved_by=?, updated_at=? WHERE action_id=?",
                (ActionStatus.DISMISSED, reason, now_iso(), actor.username,
                 now_iso(), action_id))
            self._activity(action_id, actor, "dismissed", reason,
                           cur["status"], ActionStatus.DISMISSED)
            self.audit.record(
                actor=actor.username, actor_role=actor.role,
                change_type=ChangeType.ACTION_TRANSITIONED, origin=actor.origin,
                before={"status": cur["status"]},
                after={"status": ActionStatus.DISMISSED}, action_id=action_id,
                note=reason)

    # ------------------------------------------------------------------
    # 4.2 and 4.3 — resolution
    # ------------------------------------------------------------------

    def resolve(self, action_id: str, *, option: str, actor: Actor,
                note: str = "", **fields) -> dict:
        """Perform one resolution. One transaction, one audit event, always.

        The single entry point for both workflows. Validating the option against
        the Action's own type here means an option that does not belong to this
        kind of Action is refused at the operation, not merely absent from the
        page.
        """
        cur = self._get(action_id)
        allowed = RESOLUTION_OPTIONS.get(cur["action_type"], ())
        if option not in allowed:
            label = ACTION_TYPE_LABEL.get(cur["action_type"],
                                          cur["action_type"]).lower()
            raise ValueError(
                f"{option!r} is not a resolution for "
                f"{'an' if label[:1] in 'aeiou' else 'a'} {label} action; "
                f"valid options are {', '.join(allowed)}")
        require(actor, OPTION_PERMISSION.get(option, Permission.ACTION_RESOLVE))

        corr = correlation_id()
        # ONE transaction for the domain update, the transition and the audit.
        with self.db.tx():
            handler = getattr(self, f"_do_{option}")
            outcome = handler(cur, actor, corr, note, fields)
            self._finish(cur, actor, option, note, outcome, corr)
        return outcome

    def _finish(self, cur: dict, actor: Actor, option: str, note: str,
                outcome: dict, corr: str) -> None:
        """The transition and the audit event. Inside the caller's transaction."""
        status = (ActionStatus.WAITING if outcome.get("awaiting_verification")
                  else ActionStatus.RESOLVED)
        self.db.exec(
            "UPDATE ops_action SET status=?, resolution_note=?, outcome=?, "
            "resolved_at=?, resolved_by=?, updated_at=?, assignee=? "
            "WHERE action_id=?",
            (status, note or None, dumps(outcome),
             now_iso() if status == ActionStatus.RESOLVED else None,
             actor.username if status == ActionStatus.RESOLVED else None,
             now_iso(), cur.get("assignee") or actor.username,
             cur["action_id"]))
        self._activity(cur["action_id"], actor, option,
                       note or OPTION_LABEL.get(option, option),
                       cur["status"], status)
        self.audit.record(
            actor=actor.username, actor_role=actor.role,
            change_type=ChangeType.ACTION_TRANSITIONED, origin=actor.origin,
            before={"status": cur["status"]},
            after={"status": status, "option": option,
                   "outcome": outcome.get("summary", "")},
            action_id=cur["action_id"], match_id=cur.get("match_id") or "",
            competitor_key=cur.get("competitor_key") or "",
            source_id=cur.get("source_id") or "",
            clara_product_id=cur.get("clara_product_id") or "",
            note=note, correlation=corr)

    # ---- 4.2 ambiguous matches ----

    def _do_select_candidate(self, cur, actor, corr, note, f) -> dict:
        """Pick one of the candidates. The match becomes confirmed by a person."""
        idx = f.get("candidate_index")
        cands = loads(cur.get("candidates"), [])
        try:
            chosen = cands[int(idx)]
        except (TypeError, ValueError, IndexError):
            raise ValueError("select a candidate from the list shown")
        if not cur.get("match_id"):
            raise ValueError("this action has no match to resolve")

        vid, ver, delta = self.audit.new_match_version(
            cur["match_id"], status=MatchStatus.CONFIRMED,
            provenance=Provenance.HUMAN_CONFIRMED, actor=actor.username,
            reason=note or "a person selected this candidate",
            confidence="HIGH",
            competitor_product_name=chosen.get("name") or "",
            competitor_url=chosen.get("url") or "",
            payload={"selected_from": len(cands), "candidate": chosen})
        self.db.exec("UPDATE ops_match SET confirmed_by=?, confirmed_at=?, "
                     "note=? WHERE match_id=?",
                     (actor.username, now_iso(), note or None, cur["match_id"]))
        self.audit.record(
            actor=actor.username, actor_role=actor.role,
            change_type=ChangeType.MATCH_RESOLVED, origin=actor.origin,
            before=delta["before"], after=delta["after"],
            match_id=cur["match_id"], action_id=cur["action_id"],
            competitor_key=cur.get("competitor_key") or "",
            clara_product_id=cur.get("clara_product_id") or "",
            note=note or "candidate selected", correlation=corr)
        return {"kind": "match_confirmed", "match_id": cur["match_id"],
                "version": ver, "version_id": vid,
                "provenance": Provenance.HUMAN_CONFIRMED,
                "summary": f"confirmed against {chosen.get('name') or 'the selected product'}"}

    def _do_enter_url(self, cur, actor, corr, note, f) -> dict:
        """A different competitor URL, supplied by hand."""
        url = (f.get("competitor_url") or "").strip()
        if not url.lower().startswith(("http://", "https://")):
            raise ValueError("enter a full competitor URL beginning with https://")
        if not cur.get("match_id"):
            raise ValueError("this action has no match to resolve")

        vid, ver, delta = self.audit.new_match_version(
            cur["match_id"], status=MatchStatus.CONFIRMED,
            provenance=Provenance.HUMAN_CONFIRMED, actor=actor.username,
            reason=note or "a person supplied the counterpart URL",
            confidence="HIGH",
            competitor_product_name=(f.get("competitor_product_name") or "").strip(),
            competitor_url=url, payload={"entered_by_hand": True})
        source_id = self._ensure_source(
            cur.get("competitor_key") or "", url, actor,
            kind="human_supplied", approved=False)
        self.db.exec("UPDATE ops_match SET confirmed_by=?, confirmed_at=?, "
                     "note=? WHERE match_id=?",
                     (actor.username, now_iso(), note or None, cur["match_id"]))
        self.audit.record(
            actor=actor.username, actor_role=actor.role,
            change_type=ChangeType.URL_REPLACED, origin=actor.origin,
            before=delta["before"], after=delta["after"],
            match_id=cur["match_id"], action_id=cur["action_id"],
            source_id=source_id, competitor_key=cur.get("competitor_key") or "",
            clara_product_id=cur.get("clara_product_id") or "",
            note=note or "counterpart URL entered by hand", correlation=corr)
        return {"kind": "url_replaced", "match_id": cur["match_id"],
                "version": ver, "url": url, "source_id": source_id,
                "provenance": Provenance.HUMAN_CONFIRMED,
                "summary": f"counterpart set to {url}"}

    def _do_confirm_counterpart(self, cur, actor, corr, note, f) -> dict:
        """Confirm what the system already proposed. Provenance becomes human."""
        if not cur.get("match_id"):
            raise ValueError("this action has no match to resolve")
        vid, ver, delta = self.audit.new_match_version(
            cur["match_id"], status=MatchStatus.CONFIRMED,
            provenance=Provenance.HUMAN_CONFIRMED, actor=actor.username,
            reason=note or "a person reviewed the evidence and confirmed it",
            confidence="HIGH", payload={"confirmed_existing": True})
        self.db.exec("UPDATE ops_match SET confirmed_by=?, confirmed_at=?, "
                     "note=? WHERE match_id=?",
                     (actor.username, now_iso(), note or None, cur["match_id"]))
        self.audit.record(
            actor=actor.username, actor_role=actor.role,
            change_type=ChangeType.MATCH_CONFIRMED, origin=actor.origin,
            before=delta["before"], after=delta["after"],
            match_id=cur["match_id"], action_id=cur["action_id"],
            competitor_key=cur.get("competitor_key") or "",
            clara_product_id=cur.get("clara_product_id") or "",
            note=note or "counterpart confirmed", correlation=corr)
        return {"kind": "match_confirmed", "match_id": cur["match_id"],
                "version": ver, "provenance": Provenance.HUMAN_CONFIRMED,
                "summary": "existing counterpart confirmed by a person"}

    def _do_no_counterpart(self, cur, actor, corr, note, f) -> dict:
        """There is no equivalent product. A real answer, not a failure."""
        if not cur.get("match_id"):
            raise ValueError("this action has no match to resolve")
        vid, ver, delta = self.audit.new_match_version(
            cur["match_id"], status=MatchStatus.NO_COUNTERPART,
            provenance=Provenance.HUMAN_CONFIRMED, actor=actor.username,
            reason=note or "a person determined there is no counterpart",
            confidence="HIGH", payload={"no_counterpart": True})
        self.audit.record(
            actor=actor.username, actor_role=actor.role,
            change_type=ChangeType.NO_COUNTERPART, origin=actor.origin,
            before=delta["before"], after=delta["after"],
            match_id=cur["match_id"], action_id=cur["action_id"],
            competitor_key=cur.get("competitor_key") or "",
            clara_product_id=cur.get("clara_product_id") or "",
            note=note or "no counterpart", correlation=corr)
        return {"kind": "no_counterpart", "match_id": cur["match_id"],
                "version": ver, "provenance": Provenance.HUMAN_CONFIRMED,
                "summary": "recorded as having no counterpart, so it will not be "
                           "re-raised as ambiguous"}

    def _do_note_only(self, cur, actor, corr, note, f) -> dict:
        if not (note or "").strip():
            raise ValueError("a note is required when resolving with a note only")
        return {"kind": "note", "summary": note[:160],
                "provenance": Provenance.MANUAL}

    # ---- 4.3 unreadable sources ----

    def _do_select_alternative_source(self, cur, actor, corr, note, f) -> dict:
        source_id = (f.get("source_id") or "").strip()
        row = self.db.row("SELECT * FROM ops_source WHERE source_id=?",
                          (source_id,))
        if not row:
            raise ValueError("choose one of the listed alternative sources")
        before = self._source_before(cur.get("source_id"))
        with_match = cur.get("match_id")
        self.db.exec("UPDATE ops_source SET status=?, status_reason=? "
                     "WHERE source_id=?",
                     (SourceStatus.ACTIVE,
                      f"selected as the alternative by {actor.username}",
                      source_id))
        if cur.get("source_id") and cur["source_id"] != source_id:
            self.db.exec("UPDATE ops_source SET status=?, status_reason=? "
                         "WHERE source_id=?",
                         (SourceStatus.UNREADABLE,
                          note or "replaced by an alternative source",
                          cur["source_id"]))
        if with_match and row.get("url"):
            # A version, not a bare UPDATE. Writing the URL straight onto the
            # match left its provenance saying "automatically observed" while a
            # person had in fact chosen it — so the next import saw no human
            # decision to protect and reverted the choice. 8.2 wants the change
            # recorded; the import needs it recorded to know to leave it alone.
            self._retarget_match(with_match, row["url"], actor,
                                 note or "alternative source selected")
        self.audit.record(
            actor=actor.username, actor_role=actor.role,
            change_type=ChangeType.SOURCE_REPLACED, origin=actor.origin,
            before=before, after={"source_id": source_id, "url": row.get("url"),
                                  "status": SourceStatus.ACTIVE},
            source_id=source_id, action_id=cur["action_id"],
            match_id=with_match or "", competitor_key=cur.get("competitor_key") or "",
            note=note or "alternative source selected", correlation=corr)
        return {"kind": "source_replaced", "source_id": source_id,
                "url": row.get("url"), "provenance": Provenance.HUMAN_CONFIRMED,
                "summary": f"source replaced with {row.get('url')}"}

    def _do_enter_source_url(self, cur, actor, corr, note, f) -> dict:
        url = (f.get("source_url") or "").strip()
        if not url.lower().startswith(("http://", "https://")):
            raise ValueError("enter a full source URL beginning with https://")
        before = self._source_before(cur.get("source_id"))
        source_id = self._ensure_source(cur.get("competitor_key") or "", url,
                                        actor, kind="human_supplied",
                                        approved=False)
        if cur.get("source_id") and cur["source_id"] != source_id:
            self.db.exec("UPDATE ops_source SET status=?, status_reason=? "
                         "WHERE source_id=?",
                         (SourceStatus.UNREADABLE,
                          note or "replaced by a hand-entered source",
                          cur["source_id"]))
        if cur.get("match_id"):
            self._retarget_match(cur["match_id"], url, actor,
                                 note or "source URL entered by hand")
        self.audit.record(
            actor=actor.username, actor_role=actor.role,
            change_type=ChangeType.SOURCE_ADDED, origin=actor.origin,
            before=before, after={"source_id": source_id, "url": url,
                                  "status": SourceStatus.ACTIVE},
            source_id=source_id, action_id=cur["action_id"],
            match_id=cur.get("match_id") or "",
            competitor_key=cur.get("competitor_key") or "",
            note=note or "source URL entered by hand", correlation=corr)
        return {"kind": "source_added", "source_id": source_id, "url": url,
                "provenance": Provenance.HUMAN_CONFIRMED,
                "summary": f"new source recorded: {url}"}

    def _do_request_verification(self, cur, actor, corr, note, f) -> dict:
        """Queue a durable verification job (9.2) and leave the Action waiting.

        The Action does NOT become resolved. Asking for verification is not the
        same as having verified, and a queue that marks a request as done because
        the request was made is a queue that lies.
        """
        job_id = new_id("jb")
        self.db.exec(
            "INSERT INTO ops_job (job_id,job_type,payload,status,requested_by,"
            "requested_at,action_id) VALUES (?,?,?,?,?,?,?)",
            (job_id, "verify_source",
             dumps({"source_id": cur.get("source_id"),
                    "url": f.get("source_url") or "",
                    "competitor_key": cur.get("competitor_key"),
                    "match_id": cur.get("match_id"),
                    "note": note}),
             "queued", actor.username, now_iso(), cur["action_id"]))
        if cur.get("source_id"):
            self.db.exec("UPDATE ops_source SET status=?, status_reason=? "
                         "WHERE source_id=?",
                         (SourceStatus.PENDING_VERIFICATION,
                          f"verification requested by {actor.username}",
                          cur["source_id"]))
        self.audit.record(
            actor=actor.username, actor_role=actor.role,
            change_type=ChangeType.VERIFICATION_REQUESTED, origin=actor.origin,
            after={"job_id": job_id, "status": "queued"},
            source_id=cur.get("source_id") or "", action_id=cur["action_id"],
            competitor_key=cur.get("competitor_key") or "",
            note=note or "verification requested", correlation=corr)
        return {"kind": "verification_requested", "job_id": job_id,
                "awaiting_verification": True,
                "summary": "a verification job is queued; this action stays open "
                           "until it reports back"}

    def _do_manual_observation(self, cur, actor, corr, note, f) -> dict:
        """4.3's six fields, entered by hand, stored as a new observation.

        Never an overwrite. 8.2 requires that a correction preserve the record it
        supersedes, so this inserts and marks the previous observation superseded,
        and the page shows both with their provenance side by side.
        """
        price = (f.get("price") or "").strip()
        currency = (f.get("currency") or "").strip().upper()
        observed_at = (f.get("observed_at") or "").strip() or now_iso()
        if not price and not (f.get("availability") or f.get("offer_wording")):
            raise ValueError(
                "enter at least a price, an availability or an offer wording")
        if price and not currency:
            raise ValueError(
                "a price needs its currency: cross-currency values are kept "
                "visible but never converted, so an unlabelled price cannot be "
                "compared or stored")

        obs_id, delta = self.audit.supersede_observation(
            competitor_key=cur.get("competitor_key") or "",
            actor=actor.username, provenance=Provenance.MANUAL,
            match_id=cur.get("match_id") or "",
            source_id=cur.get("source_id") or "",
            source_url=(f.get("source_url") or "").strip(),
            price=price or None, currency=currency,
            was_price=(f.get("was_price") or "").strip() or None,
            discount_pct=(f.get("discount_pct") or "").strip() or None,
            availability=(f.get("availability") or "").strip(),
            offer_wording=(f.get("offer_wording") or "").strip(),
            observed_at=observed_at,
            # 4.3 lists last-checked separately from observed: a person may be
            # recording a price they read last Tuesday and checked again today,
            # and collapsing the two loses which of the dates the value is from.
            last_checked_at=(f.get("last_checked_at") or "").strip(),
            note=note)
        self.audit.record(
            actor=actor.username, actor_role=actor.role,
            change_type=ChangeType.MANUAL_OBSERVATION, origin=actor.origin,
            before=delta["before"], after=delta["after"],
            obs_id=obs_id, action_id=cur["action_id"],
            match_id=cur.get("match_id") or "",
            competitor_key=cur.get("competitor_key") or "",
            clara_product_id=cur.get("clara_product_id") or "",
            source_id=cur.get("source_id") or "",
            note=note or "value entered by hand", correlation=corr)
        return {"kind": "manual_observation", "obs_id": obs_id,
                "provenance": Provenance.MANUAL,
                "summary": (f"{price} {currency}".strip() or
                            (f.get("availability") or "recorded by hand"))}

    def _do_select_feed(self, cur, actor, corr, note, f) -> dict:
        feed_id = (f.get("feed_id") or "").strip()
        row = self.db.row("SELECT * FROM ops_feed WHERE feed_id=?", (feed_id,))
        if not row:
            raise ValueError("choose one of the registered feeds")
        if not row.get("is_approved"):
            raise ValueError(
                "that feed is registered but not approved; an unapproved "
                "integration cannot supply values, because its provenance label "
                "would claim an approval that does not exist")
        self.db.exec("UPDATE ops_action SET source_id=?, updated_at=? "
                     "WHERE action_id=?",
                     (cur.get("source_id"), now_iso(), cur["action_id"]))
        self.audit.record(
            actor=actor.username, actor_role=actor.role,
            change_type=ChangeType.FEED_REGISTERED, origin=actor.origin,
            after={"feed_id": feed_id, "endpoint": row.get("endpoint")},
            action_id=cur["action_id"],
            competitor_key=cur.get("competitor_key") or "",
            note=note or "approved feed selected as the source",
            correlation=corr)
        return {"kind": "feed_selected", "feed_id": feed_id,
                "provenance": Provenance.FEED,
                "summary": f"values will come from {row.get('name')}"}

    def _do_register_feed(self, cur, actor, corr, note, f) -> dict:
        """Register a feed. Registration is not approval — approval is separate."""
        name = (f.get("feed_name") or "").strip()
        endpoint = (f.get("feed_endpoint") or "").strip()
        if not name or not endpoint.lower().startswith(("http://", "https://")):
            raise ValueError("a feed needs a name and a full endpoint URL")
        feed_id = new_id("fd")
        approve = bool(f.get("approve")) and actor.is_admin
        self.db.exec(
            "INSERT INTO ops_feed (feed_id,competitor_key,name,endpoint,kind,"
            "is_approved,approved_by,approved_at,registered_by,registered_at,"
            "status,note) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (feed_id, cur.get("competitor_key"), name, endpoint,
             (f.get("feed_kind") or "api"), 1 if approve else 0,
             actor.username if approve else None,
             now_iso() if approve else None,
             actor.username, now_iso(),
             "approved" if approve else "pending_approval", note or None))
        self.audit.record(
            actor=actor.username, actor_role=actor.role,
            change_type=(ChangeType.FEED_APPROVED if approve
                         else ChangeType.FEED_REGISTERED),
            origin=actor.origin,
            after={"feed_id": feed_id, "name": name, "endpoint": endpoint,
                   "is_approved": approve},
            action_id=cur["action_id"],
            competitor_key=cur.get("competitor_key") or "",
            note=note or "feed registered", correlation=corr)
        return {"kind": "feed_registered", "feed_id": feed_id,
                "approved": approve, "provenance": Provenance.FEED,
                "awaiting_verification": not approve,
                "summary": (f"{name} registered and approved" if approve
                            else f"{name} registered and awaiting admin approval")}

    def _do_mark_source_unavailable(self, cur, actor, corr, note, f) -> dict:
        reason = (f.get("reason") or note or "").strip()
        if not reason:
            raise ValueError("marking a source unavailable requires a reason")
        sid = cur.get("source_id")
        if not sid:
            raise ValueError("this action has no source attached")
        before = self._source_before(sid)
        self.db.exec("UPDATE ops_source SET status=?, status_reason=?, note=? "
                     "WHERE source_id=?",
                     (SourceStatus.UNAVAILABLE, reason, note or None, sid))
        if cur.get("match_id"):
            self.audit.new_match_version(
                cur["match_id"], status=MatchStatus.UNREADABLE,
                provenance=Provenance.HUMAN_CONFIRMED, actor=actor.username,
                reason=f"source marked unavailable: {reason}")
        self.audit.record(
            actor=actor.username, actor_role=actor.role,
            change_type=ChangeType.SOURCE_UNAVAILABLE, origin=actor.origin,
            before=before,
            after={"status": SourceStatus.UNAVAILABLE, "reason": reason},
            source_id=sid, action_id=cur["action_id"],
            match_id=cur.get("match_id") or "",
            competitor_key=cur.get("competitor_key") or "",
            note=reason, correlation=corr)
        return {"kind": "source_unavailable", "source_id": sid,
                "provenance": Provenance.HUMAN_CONFIRMED,
                "summary": f"source marked unavailable: {reason}"}

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------

    def _retarget_match(self, match_id: str, url: str, actor: Actor,
                        reason: str) -> None:
        """Point a match at a URL a person chose, and record that they chose it.

        The match keeps its status — replacing an unreadable source does not by
        itself decide that the counterpart is right — but its provenance becomes
        human-confirmed, because the URL now is. That distinction is what stops
        the next import reverting the correction: the import's rule is that a
        human decision is never overwritten by an automated one, and it can only
        honour that for decisions the record admits to.
        """
        current = self.db.row("SELECT status, confidence FROM ops_match "
                              "WHERE match_id=?", (match_id,))
        if not current:
            return
        self.audit.new_match_version(
            match_id, status=current["status"],
            provenance=Provenance.HUMAN_CONFIRMED, actor=actor.username,
            reason=reason, confidence=current.get("confidence") or "",
            competitor_url=url, payload={"source_chosen_by_hand": True})

    def _get(self, action_id: str) -> dict:
        row = self.db.row("SELECT * FROM ops_action WHERE action_id=?",
                          (action_id,))
        if not row:
            raise KeyError(f"no such action: {action_id}")
        return row

    def _source_before(self, source_id: str | None) -> dict | None:
        if not source_id:
            return None
        r = self.db.row("SELECT source_id,url,status,status_reason "
                        "FROM ops_source WHERE source_id=?", (source_id,))
        return dict(r) if r else None

    def _ensure_source(self, competitor_key: str, url: str, actor: Actor, *,
                       kind: str = "page", approved: bool = False) -> str:
        """One source row per URL per competitor. Inside the caller's transaction."""
        # `COALESCE(competitor_key,'') = ?` rather than a NULL-matching pair of
        # parameters: Postgres cannot type a bare `? IS NULL`, and the coalesce
        # says the same thing in one dialect-neutral expression.
        found = self.db.row(
            "SELECT source_id FROM ops_source WHERE url=? AND "
            "COALESCE(competitor_key,'') = ?",
            (url, competitor_key or ""))
        if found:
            self.db.exec("UPDATE ops_source SET status=?, status_reason=? "
                         "WHERE source_id=?",
                         (SourceStatus.ACTIVE, "re-selected by a person",
                          found["source_id"]))
            return found["source_id"]
        sid = new_id("sc")
        self.db.exec(
            "INSERT INTO ops_source (source_id,competitor_key,url,kind,status,"
            "status_reason,is_approved,added_by,added_at) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (sid, competitor_key or None, url, kind, SourceStatus.ACTIVE,
             f"added by {actor.username}", 1 if approved else 0,
             actor.username, now_iso()))
        return sid

    # ------------------------------------------------------------------
    # reading the queue
    # ------------------------------------------------------------------

    # Section 10 asks for sorting alongside filters. Written as data so the page
    # and the query cannot offer different orderings.
    SORTS = {
        "urgency": ("CASE status WHEN 'open' THEN 0 WHEN 'in_progress' THEN 1 "
                    "WHEN 'waiting' THEN 2 ELSE 3 END, "
                    "CASE priority WHEN 'high' THEN 0 WHEN 'medium' THEN 1 "
                    "ELSE 2 END, created_at DESC"),
        "oldest": "created_at ASC",
        "newest": "created_at DESC",
        "due": "CASE WHEN due_date IS NULL THEN 1 ELSE 0 END, due_date ASC",
        "type": "action_type ASC, created_at DESC",
        "owner": ("CASE WHEN assignee IS NULL OR assignee='' THEN 0 ELSE 1 END, "
                  "assignee ASC, created_at DESC"),
    }
    SORT_LABEL = {"urgency": "Most urgent first", "oldest": "Oldest first",
                  "newest": "Newest first", "due": "Due soonest",
                  "type": "By type", "owner": "Unassigned first"}

    def queue(self, *, status: str = "", action_type: str = "",
              assignee: str = "", competitor_key: str = "", priority: str = "",
              q: str = "", sort: str = "urgency", limit: int = 200,
              offset: int = 0) -> dict:
        """The Actions workspace list. Filters mirror the URL exactly (10)."""
        where, args = [], []
        if priority:
            where.append("priority=?")
            args.append(priority)
        if status == "open":
            where.append("status IN (?,?,?)")
            args += list(ACTION_OPEN_STATES)
        elif status:
            where.append("status=?")
            args.append(status)
        if action_type:
            where.append("action_type=?")
            args.append(action_type)
        if assignee == "unassigned":
            where.append("(assignee IS NULL OR assignee='')")
        elif assignee:
            where.append("assignee=?")
            args.append(assignee)
        if competitor_key:
            where.append("competitor_key=?")
            args.append(competitor_key)
        if q:
            where.append("(clara_product_name LIKE ? OR competitor_key LIKE ? "
                         "OR reason LIKE ?)")
            like = f"%{q}%"
            args += [like, like, like]

        clause = (" WHERE " + " AND ".join(where)) if where else ""
        total = self.db.value(f"SELECT COUNT(*) FROM ops_action{clause}",
                              args, 0)
        order = self.SORTS.get(sort) or self.SORTS["urgency"]
        rows = self.db.rows(
            f"SELECT * FROM ops_action{clause} ORDER BY {order} "
            f"LIMIT ? OFFSET ?", args + [limit, offset])
        for r in rows:
            self._decorate(r)
        return {"rows": rows, "total": total, "limit": limit,
                "offset": offset, "sort": sort, "counts": self.counts()}

    def counts(self) -> dict:
        by_status = {r["status"]: r["n"] for r in self.db.rows(
            "SELECT status, COUNT(*) AS n FROM ops_action GROUP BY status")}
        by_type = {r["action_type"]: r["n"] for r in self.db.rows(
            "SELECT action_type, COUNT(*) AS n FROM ops_action "
            "WHERE status IN (?,?,?) GROUP BY action_type",
            list(ACTION_OPEN_STATES))}
        return {
            "by_status": by_status, "by_type": by_type,
            # Defined, so section 10's "define every summary count" holds and the
            # Overview tile and this list can never disagree.
            "open": sum(by_status.get(s, 0) for s in ACTION_OPEN_STATES),
            "open_definition": "actions whose status is open, in progress or "
                               "waiting — everything still requiring a person",
            "unassigned": self.db.value(
                "SELECT COUNT(*) FROM ops_action WHERE status IN (?,?,?) "
                "AND (assignee IS NULL OR assignee='')",
                list(ACTION_OPEN_STATES), 0),
            "high": self.db.value(
                "SELECT COUNT(*) FROM ops_action WHERE status IN (?,?,?) "
                "AND priority='high'", list(ACTION_OPEN_STATES), 0),
        }

    def get(self, action_id: str) -> dict | None:
        row = self.db.row("SELECT * FROM ops_action WHERE action_id=?",
                          (action_id,))
        if not row:
            return None
        self._decorate(row)
        row["activity"] = self.db.rows(
            "SELECT * FROM ops_action_activity WHERE action_id=? "
            "ORDER BY at ASC, activity_id ASC", (action_id,))
        row["audit"] = self.audit.history(action_id=action_id)
        if row.get("match_id"):
            row["match"] = self.db.row(
                "SELECT * FROM ops_match WHERE match_id=?", (row["match_id"],))
            row["match_versions"] = self.audit.match_versions(row["match_id"])
            row["observations"] = self.audit.observations(
                match_id=row["match_id"], limit=20)
        if row.get("source_id"):
            row["source"] = self.db.row(
                "SELECT * FROM ops_source WHERE source_id=?",
                (row["source_id"],))
        # `source_id <> ?` with an empty-string sentinel rather than
        # `(source_id<>? OR ? IS NULL)`. Postgres cannot infer the type of a
        # bare parameter compared with IS NULL and refuses the statement; SQLite
        # accepts it, so the bug only appears on the engine section 9 actually
        # requires. An id is never empty, so the sentinel excludes nothing.
        row["alternative_sources"] = self.db.rows(
            "SELECT * FROM ops_source WHERE competitor_key=? AND status IN (?,?) "
            "AND source_id<>? ORDER BY is_approved DESC, added_at",
            (row.get("competitor_key"), SourceStatus.ACTIVE,
             SourceStatus.APPROVED_FEED, row.get("source_id") or ""))
        row["feeds"] = self.db.rows(
            "SELECT * FROM ops_feed WHERE competitor_key=? OR competitor_key "
            "IS NULL ORDER BY is_approved DESC, name",
            (row.get("competitor_key"),))
        return row

    def _decorate(self, r: dict) -> None:
        r["candidates"] = loads(r.get("candidates"), [])
        r["evidence"] = loads(r.get("evidence"), [])
        r["outcome"] = loads(r.get("outcome"), {})
        r["type_label"] = ACTION_TYPE_LABEL.get(r["action_type"],
                                                r["action_type"])
        r["status_label"] = ACTION_STATUS_LABEL.get(r["status"], r["status"])
        r["ask"] = ACTION_ASK.get(r["action_type"], "")
        r["options"] = [{"key": o, "label": OPTION_LABEL[o],
                         "permission": OPTION_PERMISSION.get(o)}
                        for o in RESOLUTION_OPTIONS.get(r["action_type"], ())]
        r["is_open"] = r["status"] in ACTION_OPEN_STATES
