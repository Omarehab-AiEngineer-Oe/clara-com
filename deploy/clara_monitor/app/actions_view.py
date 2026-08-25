"""The Actions workspace (3, 4): the queue, and both resolutions, in place.

This is the tab section 2 was written for. The old behaviour was a report section
listing what a person ought to go and do, with an outbound link and a paragraph of
instructions — and section 2 names that specifically: "using outbound links and
instructional text as the complete resolution workflow for human Actions" is no
longer appropriate. Section 12's first two criteria say a user must be able to
resolve each supported action **without leaving the application**.

So every option in `ops.actions.RESOLUTION_OPTIONS` has a form here, on the
action's own page, and submitting it performs the resolution. There is nowhere
else to go.

Three details matter more than they look.

**The page renders only the options this action accepts, and the server checks
again.** Both read `RESOLUTION_OPTIONS`, so a control that should not exist is
absent, and a hand-written POST for it is refused rather than silently accepted —
section 12's last criterion is about exactly that.

**An option the reader's role cannot perform is shown, disabled, with the
reason.** Hiding it would teach the reader the option does not exist; saying
"marking a source permanently unavailable is an admin operation" teaches them who
to ask. The words come from `ops.authz.DENIAL`, so the page and the refusal
message agree.

**Every form states what saving will do.** A resolution writes a domain change, a
status transition and an audit event in one transaction, and the reader is told
which record they are about to change before they change it.
"""

from __future__ import annotations

from ..ops import (ACTION_STATUS_LABEL, ACTION_TYPE_LABEL, ActionStatus,
                   MATCH_STATUS_LABEL)
from ..ops.actions import (Actions, OPTION_LABEL, OPTION_PERMISSION,
                          RESOLUTION_OPTIONS)
from ..ops.authz import DENIAL, can
from .shell import (agent_btn, applied, badges, confidence, e, empty, ff,
                    filter_bar, kv, money, page_head, pager, panel, pill,
                    prov, send_request_btn, stat, stats, when)

STATUS_TONE = {ActionStatus.OPEN: "solid", ActionStatus.IN_PROGRESS: "info",
               ActionStatus.WAITING: "amb", ActionStatus.RESOLVED: "ok",
               ActionStatus.DISMISSED: "no"}
PRIORITY_TONE = {"high": "solid", "medium": "amb", "low": "quiet"}

STATUS_FILTER = ([("", "Open (needs a person)")]
                 + [(k, v) for k, v in ACTION_STATUS_LABEL.items()]
                 + [("all", "Every status")])

# What each option's form asks for, and what saving it does. Written here rather
# than in the template so the two workflows of 4.2 and 4.3 can be read as a
# whole, in the order a person meets them.
OPTION_HELP = {
    "select_candidate":
        "Choose the competitor product this Clara product should be compared "
        "against. The match becomes confirmed by you, with your name and the "
        "time recorded against it.",
    "enter_url":
        "The right counterpart is not among the candidates. Give its URL and "
        "the match is confirmed against that page instead.",
    "confirm_counterpart":
        "The counterpart already recorded is correct. Confirming it changes the "
        "match from a machine guess to a human-confirmed value, which an import "
        "may not later overwrite.",
    "no_counterpart":
        "This competitor does not sell anything comparable. Recording that is a "
        "real answer: it stops the pair being raised again and keeps the "
        "coverage figures honest.",
    "note_only":
        "Record what you found without changing any value. The action closes "
        "and the note stays with it.",
    "select_alternative_source":
        "Use a source already registered for this competitor that can still be "
        "read.",
    "enter_source_url":
        "Register a different page for this competitor and point the match at "
        "it.",
    "request_verification":
        "Queue a verification job for this source. The action moves to Waiting "
        "rather than Resolved, because nothing has been proven yet.",
    "manual_observation":
        "Record what you can see on the page yourself. It is stored as a new "
        "observation labelled Manually entered — it does not overwrite the "
        "automated reading, it supersedes it and both stay on record.",
    "select_feed":
        "Use an approved feed or API for this competitor instead of reading "
        "their page.",
    "register_feed":
        "Register a new feed or API. It is unusable until approved, and "
        "approval is an admin operation.",
    "mark_source_unavailable":
        "Record that this source cannot be used, with the reason. The gap stays "
        "visible in coverage rather than looking like a value nobody collected.",
}


# --------------------------------------------------------------------------
# the queue
# --------------------------------------------------------------------------

def render_queue(q: dict, *, query: dict, user: dict, assignees: list,
                 competitors: list) -> str:
    c = q["counts"]
    P = ['<div class="wrap">']
    P.append(page_head(
        "Actions",
        "Everything still needing a person: undecided matches, sources that "
        "could not be read, stale prices, missing data and failed "
        "verifications. Each one is resolved on its own page, in place.",
        acts=send_request_btn(primary=True)))

    P.append(stats([
        stat(c["open"], "Open", c["open_definition"],
             tone="hot" if c["open"] else "good", href="/actions"),
        stat(c["high"], "High priority", "Open actions marked high priority.",
             tone="hot" if c["high"] else "calm",
             href="/actions?priority=high"),
        stat(c["unassigned"], "Unassigned", "Open, with nobody owning it.",
             tone="warn" if c["unassigned"] else "calm",
             href="/actions?assignee=none"),
        stat(c["by_status"].get(ActionStatus.RESOLVED, 0), "Resolved",
             "Closed with a recorded outcome and an audit event.",
             tone="good", href="/actions?status=resolved"),
    ]))

    if c["by_type"]:
        P.append('<p class="note">'
                 + e(" · ".join(
                     f"{ACTION_TYPE_LABEL.get(k, k)}: {v}"
                     for k, v in sorted(c["by_type"].items(),
                                        key=lambda kv: -kv[1])))
                 + "</p>")

    fields = [
        ("q", "Search", None, "Reason, product or competitor"),
        ("status", "Status", STATUS_FILTER),
        ("type", "Type",
         [("", "Any type")] + [(k, v) for k, v in ACTION_TYPE_LABEL.items()]),
        ("priority", "Priority",
         [("", "Any"), ("high", "High"), ("medium", "Medium"), ("low", "Low")]),
        ("assignee", "Owner",
         [("", "Anyone"), ("none", "Unassigned"), ("me", "Me")]
         + [(a, a) for a in assignees]),
        ("competitor", "Competitor",
         [("", "Any competitor")] + [(k, n) for k, n in competitors]),
        ("sort", "Sort", [(k, v) for k, v in Actions.SORT_LABEL.items()]),
    ]
    body = (filter_bar("/actions", fields, query)
            + applied("/actions", query,
                      {"q": "Search", "status": "Status", "type": "Type",
                       "priority": "Priority", "assignee": "Owner",
                       "competitor": "Competitor"}))

    if not q["rows"]:
        body += empty(
            "Nothing here needs a person",
            "No action matches these filters. When a collection run finds an "
            "undecided match, a source it cannot read, or a price too old to "
            "rely on, it appears here with the controls that resolve it.",
            '<a class="b" href="/actions?status=all">Show every status</a>')
    else:
        body += ('<div class="scroll"><table class="t"><thead><tr>'
                 '<th>What needs deciding</th><th>About</th><th>Priority</th>'
                 '<th>Status</th><th>Owner</th><th></th>'
                 '</tr></thead><tbody>')
        for r in q["rows"]:
            body += _queue_row(r, user)
        body += '</tbody></table></div>'
        body += pager("/actions", query, q["total"], q["limit"], q["offset"],
                      "actions")

    P.append(panel("", body, flush=True))
    P.append("</div>")
    return "".join(P)


def _queue_row(r: dict, user: dict) -> str:
    open_ = r.get("is_open")
    about = []
    if r.get("clara_product_id"):
        about.append(f'<a href="/products/{e(r["clara_product_id"])}">'
                     f'{e(r.get("clara_product_name") or r["clara_product_id"])}'
                     f'</a>')
    if r.get("competitor_key"):
        about.append(f'<a href="/competitors/{e(r["competitor_key"])}">'
                     f'{e(r["competitor_key"])}</a>')
    return (f'<tr{" class=\'attn\'" if open_ and r.get("priority") == "high" else ""}>'
            '<td>'
            f'<a class="ttl" href="/actions/{e(r["action_id"])}">'
            f'{e(r.get("type_label") or r["action_type"])}</a>'
            f'<div class="sub">{e((r.get("reason") or "")[:150])}</div></td>'
            f'<td><div class="sub">{" · ".join(about) or "—"}</div></td>'
            f'<td>{pill((r.get("priority") or "medium").title(), PRIORITY_TONE.get(r.get("priority"), "quiet"))}</td>'
            f'<td>{pill(r.get("status_label") or r["status"], STATUS_TONE.get(r["status"], "quiet"))}'
            + (f'<div class="sub">{when(r.get("resolved_at"))}</div>'
               if r.get("resolved_at") else "")
            + '</td>'
            f'<td><div class="sub">{e(r.get("assignee") or "unassigned")}</div></td>'
            '<td class="num">'
            f'<a class="b b-sm{" b-pri" if open_ else ""}" '
            f'href="/actions/{e(r["action_id"])}">'
            + ("Resolve" if open_ else "Open") + '</a></td></tr>')


# --------------------------------------------------------------------------
# the detail page: 4.1's fields, then the resolution controls
# --------------------------------------------------------------------------

def render_detail(a: dict, *, user: dict, actor, query: dict,
                  error: str = "", tried: str = "") -> str:
    P = ['<div class="wrap">']
    title = a.get("type_label") or a["action_type"]
    acts = (send_request_btn("action", a["action_id"], label="Send Request",
                             primary=True)
            + agent_btn("action", a["action_id"], label="Ask the Agent",
                        small=False)
            + '<a class="b" href="/actions">Back to the queue</a>')
    P.append(page_head(title, acts=acts,
                       trail=[("Actions", "/actions"), (title, None)]))
    P.append(badges(
        pill(a.get("status_label") or a["status"],
             STATUS_TONE.get(a["status"], "quiet")),
        pill((a.get("priority") or "medium").title() + " priority",
             PRIORITY_TONE.get(a.get("priority"), "quiet")),
        pill(a.get("assignee") or "Unassigned",
             "quiet" if a.get("assignee") else "amb")))

    if a.get("reason"):
        P.append(f'<p class="lede">{e(a["reason"])}</p>')
    if a.get("ask"):
        P.append(f'<p class="note">{e(a["ask"])}</p>')
    if error:
        P.append(f'<div class="flash err" role="alert">{e(error)}</div>')

    P.append('<div class="cols"><div>')
    if a.get("is_open"):
        P.append(_resolution(a, actor, tried))
    else:
        P.append(_outcome(a))
    P.append(_evidence(a))
    P.append('</div><div>')
    P.append(_context(a))
    P.append(_ownership(a, actor))
    P.append(_activity(a))
    P.append(_audit(a))
    P.append('</div></div></div>')
    return "".join(P)


def _resolution(a: dict, actor, tried: str) -> str:
    """One form per permitted option (4.2, 4.3). Nothing links outward."""
    options = RESOLUTION_OPTIONS.get(a["action_type"], ())
    blocks = []
    for opt in options:
        perm = OPTION_PERMISSION.get(opt)
        allowed = can(actor, perm)
        blocks.append(_option_form(a, opt, allowed, perm, tried))
    note = ("saving writes the data change, the action transition and the audit "
            "event in one transaction")
    return panel("Resolve this action", '<div class="opts">'
                 + "".join(blocks) + "</div>", note=note, flush=True)


def _option_form(a: dict, opt: str, allowed: bool, perm: str,
                 tried: str) -> str:
    """One resolution option, its fields, and what saving it will do."""
    label = OPTION_LABEL.get(opt, opt)
    P = [f'<div class="opt-row" id="opt-{e(opt)}">',
         f'<h3>{e(label)}</h3>',
         f'<div class="oh">{e(OPTION_HELP.get(opt, ""))}</div>']

    if not allowed:
        P.append('<p class="note warn">You cannot perform this: '
                 + e(DENIAL.get(perm, "it needs a role you do not have"))
                 + '. Send a request and an admin can do it.</p>')
        P.append(send_request_btn("action", a["action_id"],
                                  label="Ask an admin", small=True))
        P.append("</div>")
        return "".join(P)

    fields = _fields_for(a, opt)
    if fields is None:
        P.append('<p class="note warn">There is nothing to choose from for '
                 'this option yet.</p></div>')
        return "".join(P)

    P.append(f'<form method="post" action="/actions/{e(a["action_id"])}/resolve">')
    P.append(f'<input type="hidden" name="option" value="{e(opt)}">')
    if fields:
        P.append('<div class="form-grid">' + fields + "</div>")
    P.append(ff("note", "Resolution note",
                kind="textarea", wide=True, rows=2,
                hint="Kept with the action and written into the audit event. "
                     "Say what you saw, not what you assumed.",
                required=(opt == "note_only")))
    P.append('<div class="fbar">'
             f'<button class="b b-pri" type="submit">{e(label)}</button>'
             f'<span class="hint">{e(_will_do(a, opt))}</span>'
             '</div>')
    P.append("</form></div>")
    return "".join(P)


def _will_do(a: dict, opt: str) -> str:
    """What record this is about to change. Stated before it changes."""
    target = []
    if a.get("match"):
        m = a["match"]
        target.append(f'match {m.get("clara_product_name") or m["match_id"]} ↔ '
                      f'{m.get("competitor_key")}')
    if a.get("source"):
        target.append(f'source {(a["source"].get("url") or "")[:50]}')
    what = " and ".join(target) or "this action"
    if opt == "request_verification":
        return f"Queues a job and moves this action to Waiting. Concerns {what}."
    return f"Resolves this action and updates {what}."


def _fields_for(a: dict, opt: str) -> str | None:
    """The inputs each option needs. Field names match `Actions.resolve`."""
    if opt in ("confirm_counterpart", "no_counterpart", "note_only"):
        return ""

    if opt == "select_candidate":
        cands = a.get("candidates") or []
        if not cands:
            return None
        rows = []
        for i, c in enumerate(cands):
            rows.append(
                '<label class="cand">'
                f'<input type="radio" name="candidate_index" value="{i}"'
                + (' required' if i == 0 else '') + '>'
                '<span class="cb">'
                f'<span class="cn">{e(c.get("name") or "unnamed")}</span>'
                + (f'<span class="cu">{e(c.get("url"))}</span>'
                   if c.get("url") else "")
                + (f'<span class="cw">{money(c.get("price"), c.get("currency") or "")}'
                   + (f' · score {c["score"]}' if c.get("score") is not None
                      else "")
                   + (f' · {e(c["why"])}' if c.get("why") else "")
                   + "</span>")
                + "</span></label>")
        return ('<div class="ff fw"><label>Candidate products</label>'
                '<div class="cands">' + "".join(rows) + "</div>"
                '<span class="hint">Only candidates with a URL are offered: an '
                'option you cannot check is a guess, not a decision.</span>'
                "</div>")

    if opt == "enter_url":
        return (ff("competitor_url", "Competitor product URL", kind="url",
                   required=True, wide=True,
                   placeholder="https://competitor.example/product/…",
                   hint="The page showing the product Clara should be compared "
                        "against.")
                + ff("competitor_product_name", "Their product name",
                     hint="Optional, but it makes every later view readable."))

    if opt == "select_alternative_source":
        alts = a.get("alternative_sources") or []
        if not alts:
            return None
        opts = [(s["source_id"],
                 f'{(s.get("url") or "")[:70]}'
                 + (" (approved)" if s.get("is_approved") else ""))
                for s in alts]
        return ff("source_id", "Alternative source", kind="select",
                  options=opts, required=True, wide=True,
                  hint="Sources already registered for this competitor that can "
                       "still be read. Approved ones are listed first.")

    if opt == "enter_source_url":
        return ff("source_url", "New source URL", kind="url", required=True,
                  wide=True, placeholder="https://competitor.example/…",
                  hint="Registered as a source for this competitor, and the "
                       "match is pointed at it.")

    if opt == "request_verification":
        return ff("source_url", "URL to verify", kind="url", wide=True,
                  value=(a.get("source") or {}).get("url") or "",
                  hint="Leave as-is to re-verify the source that failed, or "
                       "give a different one.")

    if opt == "manual_observation":
        # 4.3 lists six fields; all six are here, and the two dates are separate.
        return (ff("price", "Price",
                   hint="The number as shown, without the currency symbol.")
                + ff("currency", "Currency",
                     placeholder="SAR",
                     hint="Required with a price. Values in different "
                          "currencies are kept visible but never converted.")
                + ff("availability", "Availability",
                     placeholder="in_stock / out_of_stock")
                + ff("was_price", "Was price",
                     hint="Optional, if the page shows a struck-through price.")
                + ff("discount_pct", "Discount %", hint="Optional.")
                + ff("offer_wording", "Offer wording", wide=True,
                     hint="Copy the promotion exactly as written on the page.")
                + ff("observed_at", "Observed date", kind="date",
                     required=True,
                     hint="The date the value was true on their page.")
                + ff("last_checked_at", "Last-checked date", kind="date",
                     hint="Leave blank for today. Separate from Observed: you "
                          "may be recording a price you read earlier and "
                          "re-checked today.")
                + ff("source_url", "Page you read it from", kind="url",
                     wide=True,
                     hint="Stored with the value so the evidence stays beside "
                          "it."))

    if opt == "select_feed":
        feeds = [f for f in (a.get("feeds") or []) if f.get("is_approved")]
        if not feeds:
            return None
        return ff("feed_id", "Approved feed or API", kind="select",
                  options=[(f["feed_id"],
                            f'{f.get("name")} — {(f.get("endpoint") or "")[:50]}')
                           for f in feeds],
                  required=True, wide=True,
                  hint="Only approved integrations are offered; approval is an "
                       "admin operation.")

    if opt == "register_feed":
        return (ff("feed_name", "Name", required=True,
                   placeholder="Competitor price API")
                + ff("feed_endpoint", "Endpoint", kind="url", required=True,
                     placeholder="https://api.example/prices")
                + ff("feed_kind", "Kind", kind="select",
                     options=[("api", "API"), ("feed", "Feed"),
                              ("file", "File drop")])
                + ff("approve", "Approve now", kind="select",
                     options=[("", "No — register only"),
                              ("1", "Yes — approve on registration")],
                     hint="Approving requires an admin role; a non-admin "
                          "registration stays unapproved and unusable until "
                          "an admin approves it."))

    if opt == "mark_source_unavailable":
        return ff("reason", "Why it cannot be used", kind="textarea",
                  required=True, wide=True, rows=2,
                  hint="Recorded on the source and in the audit event. The gap "
                       "stays visible in coverage rather than looking like a "
                       "value nobody collected.")
    return ""


def _outcome(a: dict) -> str:
    """A resolved action: what was decided, by whom, and what it changed."""
    out = a.get("outcome") or {}
    rows = [("Status", pill(a.get("status_label") or a["status"],
                            STATUS_TONE.get(a["status"], "quiet"))),
            ("Resolved by", e(a.get("resolved_by") or "")),
            ("Resolved at", when(a.get("resolved_at"))),
            ("Outcome", e(out.get("summary") or out.get("kind") or "")),
            ("Note", e(a.get("resolution_note") or ""))]
    for k, v in out.items():
        if k in ("summary", "kind") or v in (None, "", [], {}):
            continue
        rows.append((k.replace("_", " ").capitalize(),
                     prov(v) if k == "provenance" else e(v)))
    body = kv(rows)
    if a["status"] == ActionStatus.WAITING:
        body += ('<p class="note warn">This action is Waiting, not Resolved: '
                 'verification was requested and nothing has been proven yet.'
                 '</p>')
    return panel("Outcome", body,
                 note="the action is closed; the change it made is in the audit "
                      "trail below")


def _evidence(a: dict) -> str:
    """The pages the agent could not read or could not choose between."""
    parts = []
    ev = a.get("evidence") or []
    if ev:
        rows = []
        for x in ev:
            url = x.get("url") if isinstance(x, dict) else str(x)
            note = x.get("note") if isinstance(x, dict) else ""
            rows.append('<li><div class="what">'
                        + (f'<a href="{e(url)}" rel="nofollow noopener">'
                           f'{e(url)}</a>' if url else e(note))
                        + "</div>"
                        + (f'<div class="ev">{e(note)}</div>'
                           if note and url else "")
                        + "</li>")
        parts.append('<ul class="hist">' + "".join(rows) + "</ul>")
    if a.get("failure_reason"):
        parts.append(f'<p class="note bad">Last failure: '
                     f'{e(a["failure_reason"])}'
                     + (f' (attempted {when(a.get("last_attempt_at"))})'
                        if a.get("last_attempt_at") else "")
                     + "</p>")
    obs = a.get("observations") or []
    if obs:
        rows = []
        for o in obs[:12]:
            rows.append(
                f'<li><div class="when">{when(o.get("observed_at"))}</div>'
                f'<div class="what">{money(o.get("price"), o.get("currency"))}'
                + (f' · {e(o.get("availability"))}' if o.get("availability")
                   else "")
                + "</div>"
                + '<div class="ev">'
                + badges(prov(o.get("provenance"), short=True),
                         pill("superseded", "quiet") if o.get("superseded_by")
                         else pill("current", "ok"))
                + "</div></li>")
        parts.append('<h3 style="font-size:13px;margin:12px 0 4px">'
                     'Observations on this match</h3>'
                     '<ul class="hist">' + "".join(rows) + "</ul>")
    if not parts:
        return ""
    return panel("Evidence", "".join(parts),
                 note="what was tried, and what came back")


def _context(a: dict) -> str:
    """4.1's context fields: product, competitor, match, source, candidates."""
    rows = []
    if a.get("clara_product_id"):
        rows.append(("Clara product",
                     f'<a href="/products/{e(a["clara_product_id"])}">'
                     f'{e(a.get("clara_product_name") or a["clara_product_id"])}'
                     f'</a>'))
    if a.get("competitor_key"):
        rows.append(("Competitor",
                     f'<a href="/competitors/{e(a["competitor_key"])}">'
                     f'{e(a["competitor_key"])}</a>'))
    m = a.get("match")
    if m:
        rows.append(("Match status",
                     badges(pill(MATCH_STATUS_LABEL.get(m["status"],
                                                        m["status"]), "quiet"),
                            confidence(m.get("confidence")),
                            prov(m.get("provenance"), short=True))))
        if m.get("competitor_product_name"):
            rows.append(("Their product", e(m["competitor_product_name"])))
        if m.get("competitor_url"):
            rows.append(("Their URL",
                         f'<a href="{e(m["competitor_url"])}" '
                         f'rel="nofollow noopener">'
                         f'{e(m["competitor_url"][:60])}</a>'))
    s = a.get("source")
    if s:
        rows.append(("Source",
                     f'<a href="{e(s.get("url"))}" rel="nofollow noopener">'
                     f'{e((s.get("url") or "")[:60])}</a>'))
        rows.append(("Source state",
                     e(s.get("status") or "")
                     + (f' — {e(s.get("status_reason"))}'
                        if s.get("status_reason") else "")))
    rows += [("Created", when(a.get("created_at"))),
             ("Created by", e(a.get("created_by") or "system")),
             ("Last attempt", when(a.get("last_attempt_at"))),
             ("Due", when(a.get("due_date"), date_only=True)
              if a.get("due_date") else "")]
    if a.get("request_id"):
        rows.append(("Related request",
                     f'<a href="/requests/{e(a["request_id"])}">'
                     f'{e(a["request_id"])}</a>'))
    rows.append(("Action id", f'<span class="mono">{e(a["action_id"])}</span>'))
    return panel("Context", kv(rows))


def _ownership(a: dict, actor) -> str:
    """Claim, assign and dismiss. Assign and dismiss are admin operations."""
    if not a.get("is_open"):
        return ""
    P = []
    aid = e(a["action_id"])
    if (a.get("assignee") or "") != actor.username:
        P.append(f'<form method="post" action="/actions/{aid}/claim">'
                 '<button class="b b-pri" type="submit">Take this action</button>'
                 "</form>")
    if can(actor, "action_assign"):
        P.append(f'<form method="post" action="/actions/{aid}/assign">'
                 + ff("assignee", "Assign to", value=a.get("assignee") or "",
                      hint="A username. Recorded as an audit event.")
                 + '<div class="fbar">'
                   '<button class="b" type="submit">Assign</button></div>'
                   "</form>")
        # 4.1's priority and optional due date. Displayed below as well, but a
        # field nothing can write is a column rather than a field.
        P.append(f'<form method="post" action="/actions/{aid}/schedule">'
                 + ff("priority", "Priority", kind="select",
                      value=a.get("priority") or "medium",
                      options=[("high", "High"), ("medium", "Medium"),
                               ("low", "Low")])
                 + ff("due_date", "Due date", kind="date",
                      value=(a.get("due_date") or "")[:10],
                      hint="Optional. Clear it to remove the date.")
                 + '<div class="fbar">'
                   '<button class="b" type="submit">Save scheduling</button>'
                   "</div></form>")
    if can(actor, "action_dismiss"):
        P.append(f'<form method="post" action="/actions/{aid}/dismiss">'
                 + ff("reason", "Dismiss without resolving", kind="textarea",
                      required=True, rows=2,
                      hint="Use this only when the action should never have "
                           "been raised. Dismissing does not change any value, "
                           "and the reason is audited.")
                 + '<div class="fbar"><button class="b b-danger" '
                   'type="submit">Dismiss</button></div></form>')
    if not P:
        return ""
    return panel("Ownership", "".join(P))


def _activity(a: dict) -> str:
    """4.1's chronological activity history."""
    acts = a.get("activity") or []
    if not acts:
        return ""
    rows = []
    for x in acts:
        rows.append(
            f'<li><div class="when">{when(x.get("at"))} · '
            f'{e(x.get("actor") or "system")}</div>'
            f'<div class="what">{e(OPTION_LABEL.get(x.get("kind"), x.get("kind")))}'
            "</div>"
            + (f'<div class="ev">{e(x.get("detail"))}</div>'
               if x.get("detail") else "")
            + (f'<div class="delta">{e(x.get("from_value"))} &rarr; '
               f'{e(x.get("to_value"))}</div>'
               if x.get("to_value") else "")
            + "</li>")
    return panel(f"Activity ({len(acts)})",
                 '<ul class="hist">' + "".join(rows) + "</ul>")


def _audit(a: dict) -> str:
    rows = a.get("audit") or []
    if not rows:
        return ""
    from .admin_view import audit_line
    return panel(f"Audit events ({len(rows)})",
                 '<ul class="hist">'
                 + "".join(audit_line(x) for x in rows[:25]) + "</ul>",
                 note="append-only, with before and after values")
