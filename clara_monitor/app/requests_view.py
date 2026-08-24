"""The Requests tab (5): eight types, five statuses, context that prefills.

Section 3 splits this tab by role — "My Requests for users; queue, ownership,
responses, and administration controls for admins" — and 5.3 gives the workflow
exactly five states with exactly one set of permitted next steps. Both are
rendered from `ops.schema.REQUEST_TRANSITIONS`, so the buttons a page offers and
the transitions the server accepts are the same list rather than two lists that
agree today.

The prefill is the part worth being careful about. Section 5.2 says opening Send
Request from a supported record must prefill that context, and section 12 turns it
into a criterion: the form "contains the correct record context without
re-entry". So the new-request form is rendered from `Requests.context_for`, which
reads the record itself and returns both the linked ids and a readable summary.
The summary matters as much as the ids: a request that says "match mt0000123" is
unreadable to the admin who receives it, and an admin who has to look up what a
request is about will look it up wrongly some of the time.

The status a requester can move is deliberately narrow. A requester replying to a
Waiting request returns it to In progress — that is the one transition 5.3 gives
them, and the page offers no other.
"""

from __future__ import annotations

from ..ops import (REQUEST_STATUS_LABEL, REQUEST_STATUS_MEANING,
                   REQUEST_TRANSITIONS, REQUEST_TYPE_LABEL, RequestStatus)
from ..ops.db import loads
from ..ops.requests import Requests
from .shell import (applied, badges, e, empty, ff, filter_bar, kv, page_head,
                    pager, panel, pill, send_request_btn, stat, stats, when)

STATUS_TONE = {RequestStatus.NEW: "solid", RequestStatus.IN_PROGRESS: "info",
               RequestStatus.WAITING: "amb", RequestStatus.RESOLVED: "ok",
               RequestStatus.CLOSED: "no"}

PRIORITY_TONE = {"high": "solid", "medium": "amb", "low": "quiet"}

# Which record kinds a request can attach to (5.2), and what to call them.
CONTEXT_LABEL = {
    "product": "Clara product", "competitor": "Competitor",
    "match": "Competitor match", "observation": "Price observation",
    "source": "Data source", "action": "Action",
    "conversation": "Agent conversation",
}

DETAIL_LEVELS = [("", "No preference"),
                 ("brief", "A short answer is enough"),
                 ("full", "Explain the evidence in full"),
                 ("corrected", "Correct the data, not just the answer")]


# --------------------------------------------------------------------------
# the list
# --------------------------------------------------------------------------

def render_list(data: dict, *, query: dict, user: dict, actor,
                counts: dict) -> str:
    scope = (query.get("scope") or [""])[0] if isinstance(
        query.get("scope"), list) else (query.get("scope") or "")
    admin_view = bool(actor.is_admin and scope == "all")
    title = "Request administration" if admin_view else "My Requests"

    P = ['<div class="wrap">']
    P.append(page_head(
        title,
        ("Every request raised in the application, with its owner and status."
         if admin_view else
         "Questions you have raised, and the answers to them. A request is how "
         "something the application cannot answer reaches a person."),
        acts=send_request_btn(label="Send Request", primary=True)
             + (f'<a class="b" href="/requests?scope='
                f'{"" if admin_view else "all"}">'
                + ("Only mine" if admin_view else "Every request") + "</a>"
                if actor.is_admin else "")))

    by_status = counts.get("by_status") or {}
    cards = [
        stat(counts.get("open", 0), "Open",
             counts.get("open_definition", ""),
             tone="warn" if counts.get("open") else "good"),
        stat(counts.get("waiting_on_me", 0), "Waiting on you",
             "Requests you raised that cannot move until you reply.",
             tone="hot" if counts.get("waiting_on_me") else "calm",
             href="/requests?status=waiting_for_information"),
        stat(by_status.get(RequestStatus.RESOLVED, 0), "Resolved",
             "An answer or corrective action has been supplied.",
             tone="good"),
    ]
    if admin_view:
        cards.append(stat(counts.get("unowned", 0), "Unowned",
                          "New, with no admin owning it yet.",
                          tone="hot" if counts.get("unowned") else "good"))
    P.append(stats(cards))

    fields = [("q", "Search", None, "Subject or description"),
              ("status", "Status",
               [("", "Any status")]
               + [(k, v) for k, v in REQUEST_STATUS_LABEL.items()]),
              ("type", "Type",
               [("", "Any type")]
               + [(k, v) for k, v in REQUEST_TYPE_LABEL.items()]),
              ("sort", "Sort",
               [(k, v) for k, v in Requests.SORT_LABEL.items()])]
    if actor.is_admin:
        fields.append(("scope", "Scope",
                       [("", "Mine"), ("all", "Everyone's")]))
    path = "/requests"
    body = (filter_bar(path, fields, query)
            + applied(path, query, {"q": "Search", "status": "Status",
                                    "type": "Type"}))

    if not data["rows"]:
        body += empty(
            "No request here yet" if not admin_view else "No request matches",
            ("Send Request is in the header of every page, and beside every "
             "product, competitor, price and action. Use it when the evidence "
             "on screen does not answer the question."
             if not admin_view else
             "No request matches these filters."),
            send_request_btn(label="Send a request", primary=True))
    else:
        body += ('<div class="scroll"><table class="t"><thead><tr>'
                 '<th>Subject</th><th>Type</th><th>Status</th>'
                 + ("<th>Requester</th><th>Owner</th>" if admin_view else
                    "<th>Owner</th>")
                 + '<th>Updated</th><th></th></tr></thead><tbody>')
        for r in data["rows"]:
            body += _row(r, admin_view)
        body += "</tbody></table></div>"
        body += pager(path, query, data["total"], data["limit"],
                      data["offset"], "requests")

    P.append(panel("", body, flush=True))
    P.append(_workflow_key())
    P.append("</div>")
    return "".join(P)


def _row(r: dict, admin_view: bool) -> str:
    ctx = loads(r.get("context"), {}) or {}
    where = []
    if ctx.get("clara_product_id"):
        where.append(f'<a href="/products/{e(ctx["clara_product_id"])}">'
                     'product</a>')
    if ctx.get("competitor_key"):
        where.append(f'<a href="/competitors/{e(ctx["competitor_key"])}">'
                     'competitor</a>')
    if r.get("action_id"):
        where.append(f'<a href="/actions/{e(r["action_id"])}">action</a>')
    attn = (' class="attn"' if r["status"] in (RequestStatus.NEW,
                                               RequestStatus.WAITING) else "")
    cells = (f'<tr{attn}><td>'
             f'<a class="ttl" href="/requests/{e(r["request_id"])}">'
             f'{e(r.get("subject") or "(no subject)")}</a>'
             + (f'<div class="sub">about {" · ".join(where)}</div>'
                if where else "")
             + '</td>'
             f'<td><div class="sub">'
             f'{e(REQUEST_TYPE_LABEL.get(r["request_type"], r["request_type"]))}'
             '</div></td>'
             f'<td>{pill(REQUEST_STATUS_LABEL.get(r["status"], r["status"]), STATUS_TONE.get(r["status"], "quiet"), title=REQUEST_STATUS_MEANING.get(r["status"], ""))}</td>')
    if admin_view:
        cells += f'<td><div class="sub">{e(r.get("requester"))}</div></td>'
    cells += (f'<td><div class="sub">{e(r.get("owner") or "unowned")}</div></td>'
              f'<td><div class="sub">{when(r.get("updated_at"))}</div></td>'
              '<td class="num">'
              f'<a class="b b-sm" href="/requests/{e(r["request_id"])}">Open</a>'
              "</td></tr>")
    return cells


def _workflow_key() -> str:
    """5.3's table, on the page. The workflow is not folklore."""
    rows = []
    for status, label in REQUEST_STATUS_LABEL.items():
        nxt = ", ".join(REQUEST_STATUS_LABEL[s]
                        for s in REQUEST_TRANSITIONS.get(status, ()))
        rows.append((label, e(REQUEST_STATUS_MEANING.get(status, ""))
                     + (f'<div class="ev">Can move to: {e(nxt)}</div>'
                        if nxt else "")))
    return panel("The five statuses", kv(rows),
                 note="the page and the server read this same table")


# --------------------------------------------------------------------------
# the new-request form (5.2)
# --------------------------------------------------------------------------

def render_new(*, ctx: dict, form: dict | None = None, errors: dict | None = None,
               user: dict) -> str:
    form = form or {}
    errors = errors or {}
    ok = ctx.get("ok")
    P = ['<div class="wrap narrow">']
    P.append(page_head(
        "Send Request",
        "Ask a person to look at something. The request carries the record you "
        "opened it from, so nobody has to work out what it is about.",
        trail=[("Requests", "/requests"), ("New", None)]))

    if ctx.get("kind") and not ok:
        P.append(f'<div class="flash err" role="alert">'
                 f'{e(ctx.get("why") or "that record could not be found")}. '
                 f'The request can still be sent — describe it below.</div>')

    body = ['<form method="post" action="/requests/new">']
    if ok:
        body.append(f'<input type="hidden" name="kind" value="{e(ctx["kind"])}">'
                    f'<input type="hidden" name="id" '
                    f'value="{e(ctx.get("record_id") or "")}">')
    body.append('<div class="form-grid">')
    body.append(ff("request_type", "Request type", kind="select", required=True,
                   value=form.get("request_type")
                   or ctx.get("suggested_type") or "other",
                   options=[(k, v) for k, v in REQUEST_TYPE_LABEL.items()],
                   error=errors.get("request_type", ""),
                   hint="Eight types; pick the closest. The suggestion comes "
                        "from the record you opened this from."))
    body.append(ff("priority", "Priority", kind="select",
                   value=form.get("priority") or "medium",
                   options=[("high", "High"), ("medium", "Medium"),
                            ("low", "Low")]))
    body.append(ff("subject", "Subject", required=True, wide=True,
                   value=form.get("subject") or ctx.get("subject") or "",
                   error=errors.get("subject", ""),
                   hint="One line. This is what an admin sees in the queue."))
    body.append(ff("description", "What are you asking for?", kind="textarea",
                   required=True, wide=True, rows=6,
                   value=form.get("description") or "",
                   error=errors.get("description", ""),
                   hint="What you saw, what you expected, and what you want "
                        "done. This becomes the first message on the request."))
    body.append(ff("detail_level", "Preferred response", kind="select",
                   value=form.get("detail_level") or "",
                   options=DETAIL_LEVELS))
    body.append(ff("evidence", "Evidence reference", wide=True,
                   value=form.get("evidence") or "",
                   hint="Optional: a URL or a record id you want looked at."))
    body.append("</div>")
    body.append('<div class="fbar">'
                '<button class="b b-pri" type="submit">Send request</button>'
                '<a class="b" href="/requests">Cancel</a>'
                '<span class="hint">Created as New, awaiting triage.</span>'
                "</div>")
    body.append("</form>")
    P.append(panel("The request", "".join(body)))

    if ok:
        P.append(_context_panel(ctx))
    else:
        P.append(panel("Context",
                       '<p class="note">This request is not attached to a '
                       'record. Opening Send Request from a product, '
                       'competitor, price, source or action attaches it '
                       'automatically.</p>'))
    P.append("</div>")
    return "".join(P)


def _context_panel(ctx: dict) -> str:
    """What the request will carry. Shown, not merely posted."""
    rows = [("Record", e(CONTEXT_LABEL.get(ctx["kind"], ctx["kind"])))]
    links = {
        "clara_product_id": ("Clara product", "/products/"),
        "competitor_key": ("Competitor", "/competitors/"),
        "action_id": ("Action", "/actions/"),
    }
    for key, (label, base) in links.items():
        if ctx.get(key):
            rows.append((label, f'<a href="{base}{e(ctx[key])}">'
                                f'{e(ctx[key])}</a>'))
    for key, label in (("match_id", "Match"), ("conversation_id",
                                               "Conversation")):
        if ctx.get(key):
            rows.append((label, f'<span class="mono">{e(ctx[key])}</span>'))
    if ctx.get("url"):
        rows.append(("Source URL", f'<a href="{e(ctx["url"])}" '
                                   f'rel="nofollow noopener">'
                                   f'{e(ctx["url"][:70])}</a>'))
    body = kv(rows)
    if ctx.get("summary"):
        body += ('<h3 style="font-size:13px;margin:14px 0 5px">'
                 'Attached summary</h3>'
                 f'<pre class="note" style="white-space:pre-wrap">'
                 f'{e(ctx["summary"])}</pre>')
    return panel("Context attached to this request", body,
                 note="prefilled from the record; no re-entry needed")


# --------------------------------------------------------------------------
# the detail page
# --------------------------------------------------------------------------

def render_detail(r: dict, *, user: dict, actor, error: str = "") -> str:
    P = ['<div class="wrap narrow">']
    P.append(page_head(
        r.get("subject") or "Request",
        trail=[("Requests", "/requests"), (r["request_id"], None)],
        acts='<a class="b" href="/requests">Back</a>'))
    P.append(badges(
        pill(REQUEST_STATUS_LABEL.get(r["status"], r["status"]),
             STATUS_TONE.get(r["status"], "quiet"),
             title=REQUEST_STATUS_MEANING.get(r["status"], "")),
        pill(REQUEST_TYPE_LABEL.get(r["request_type"], r["request_type"]),
             "quiet"),
        pill((r.get("priority") or "medium").title(),
             PRIORITY_TONE.get(r.get("priority"), "quiet"))))
    P.append(f'<p class="note">'
             f'{e(REQUEST_STATUS_MEANING.get(r["status"], ""))}</p>')
    if error:
        P.append(f'<div class="flash err" role="alert">{e(error)}</div>')

    P.append(_conversation(r))
    P.append(_reply_form(r, actor))
    P.append(_admin_controls(r, actor))
    P.append(_facts(r))
    P.append(_status_history(r))
    P.append("</div>")
    return "".join(P)


def _conversation(r: dict) -> str:
    msgs = r.get("messages") or []
    if not msgs:
        return ""
    out = []
    for m in msgs:
        out.append(
            f'<div class="msg {"agent" if m.get("is_response") else "you"}">'
            f'<div class="who">{e(m.get("author"))}'
            + (f' · {e(m.get("author_role"))}' if m.get("author_role") else "")
            + f' · {when(m.get("at"))}</div>'
            f'<div class="bd">{e(m.get("body"))}</div></div>')
    return panel(f"Conversation ({len(msgs)})",
                 '<div style="display:flex;flex-direction:column;gap:12px">'
                 + "".join(out) + "</div>")


def _reply_form(r: dict, actor) -> str:
    """Replying, and the one transition a requester is given (5.3)."""
    is_requester = r.get("requester") == actor.username
    if not (is_requester or actor.is_admin):
        return ""
    if r["status"] == RequestStatus.CLOSED and not actor.is_admin:
        return panel("Reply",
                     '<p class="note">This request is closed. An admin can '
                     'reopen it if there is more to do.</p>')
    hint = "Added to the conversation."
    if is_requester and r["status"] == RequestStatus.WAITING:
        hint = ("This request is waiting on you. Replying returns it to In "
                "progress — that is the one transition a requester has.")
    body = (f'<form method="post" action="/requests/{e(r["request_id"])}/reply">'
            + ff("body", "Your reply", kind="textarea", required=True, rows=4,
                 wide=True, hint=hint)
            + ('<div class="fbar">'
               '<button class="b b-pri" type="submit">Send reply</button>'
               "</div></form>"))
    return panel("Reply", body)


def _admin_controls(r: dict, actor) -> str:
    """Ownership and the permitted transitions — from the transition table."""
    if not actor.is_admin:
        return ""
    P = []
    rid = e(r["request_id"])
    if not r.get("owner"):
        P.append(f'<form method="post" action="/requests/{rid}/take">'
                 '<button class="b b-pri" type="submit">Take ownership</button>'
                 "</form>")
    else:
        P.append(f'<p class="note">Owned by {e(r["owner"])}.</p>')

    allowed = REQUEST_TRANSITIONS.get(r["status"], ())
    if allowed:
        P.append(f'<form method="post" action="/requests/{rid}/status">')
        P.append('<div class="form-grid">')
        P.append(ff("to_status", "Move to", kind="select", required=True,
                    options=[(s, REQUEST_STATUS_LABEL[s]) for s in allowed],
                    hint="Only the transitions section 5.3 permits from "
                         f"{REQUEST_STATUS_LABEL.get(r['status'], r['status'])} "
                         "are offered."))
        P.append(ff("note", "Note", hint="Recorded in the status history."))
        P.append(ff("resolution", "Resolution", kind="textarea", wide=True,
                    rows=3,
                    value=r.get("resolution") or "",
                    hint="Required when resolving: what was answered or "
                         "corrected."))
        P.append(ff("closure_reason", "Closure reason", wide=True,
                    value=r.get("closure_reason") or "",
                    hint="Used when closing."))
        P.append("</div>")
        P.append('<div class="fbar">'
                 '<button class="b" type="submit">Change status</button>'
                 '<span class="hint">Writes the transition, the history entry '
                 'and the audit event together.</span></div></form>')
    return panel("Administration", "".join(P),
                 note="admin-only; enforced on the server, not by hiding this")


def _facts(r: dict) -> str:
    ctx = loads(r.get("context"), {}) or {}
    rows = [("Requester", e(r.get("requester"))),
            ("Owner", e(r.get("owner") or "unowned")),
            ("Created", when(r.get("created_at"))),
            ("Updated", when(r.get("updated_at"))),
            ("Resolved", when(r.get("resolved_at"))
             if r.get("resolved_at") else ""),
            ("Closed", when(r.get("closed_at")) if r.get("closed_at") else ""),
            ("Preferred response",
             e(dict(DETAIL_LEVELS).get(r.get("detail_level") or "", ""))),
            ("Resolution", e(r.get("resolution") or "")),
            ("Closure reason", e(r.get("closure_reason") or "")),
            ("Request id", f'<span class="mono">{e(r["request_id"])}</span>')]
    if r.get("action_id"):
        rows.append(("Action",
                     f'<a href="/actions/{e(r["action_id"])}">'
                     f'{e(r["action_id"])}</a>'))
    if ctx.get("clara_product_id"):
        rows.append(("Clara product",
                     f'<a href="/products/{e(ctx["clara_product_id"])}">'
                     f'{e(ctx["clara_product_id"])}</a>'))
    if ctx.get("competitor_key"):
        rows.append(("Competitor",
                     f'<a href="/competitors/{e(ctx["competitor_key"])}">'
                     f'{e(ctx["competitor_key"])}</a>'))
    if ctx.get("url"):
        rows.append(("Source URL",
                     f'<a href="{e(ctx["url"])}" rel="nofollow noopener">'
                     f'{e(ctx["url"][:60])}</a>'))
    body = kv(rows)
    if ctx.get("summary"):
        body += (f'<pre class="note" style="white-space:pre-wrap;margin-top:12px">'
                 f'{e(ctx["summary"])}</pre>')
    if ctx.get("citations"):
        cites = "".join(
            f'<li><div class="what">{e(c.get("label") or c.get("record_id"))}'
            "</div>"
            + (f'<div class="ev"><a href="{e(c["url"])}" '
               f'rel="nofollow noopener">{e(c["url"][:60])}</a></div>'
               if c.get("url") else "")
            + "</li>"
            for c in ctx["citations"])
        body += ('<h3 style="font-size:13px;margin:14px 0 5px">'
                 'Citations carried from the conversation</h3>'
                 f'<ul class="hist">{cites}</ul>')
    if ctx.get("gaps"):
        body += ('<h3 style="font-size:13px;margin:14px 0 5px">'
                 'Missing evidence the Agent reported</h3>'
                 + "".join(f'<div class="gap">{e(g.get("what"))} — '
                           f'{e(g.get("why"))}</div>' for g in ctx["gaps"]))
    return panel("Request", body)


def _status_history(r: dict) -> str:
    hist = r.get("status_history") or []
    if not hist:
        return ""
    rows = []
    for h in hist:
        rows.append(
            f'<li><div class="when">{when(h.get("at"))} · '
            f'{e(h.get("actor") or "system")}</div>'
            f'<div class="what">'
            + (f'{e(REQUEST_STATUS_LABEL.get(h.get("from_status"), h.get("from_status")))} &rarr; '
               if h.get("from_status") else "")
            + f'{e(REQUEST_STATUS_LABEL.get(h["to_status"], h["to_status"]))}'
            "</div>"
            + (f'<div class="ev">{e(h.get("note"))}</div>'
               if h.get("note") else "")
            + "</li>")
    return panel("Status history", '<ul class="hist">' + "".join(rows) + "</ul>")
