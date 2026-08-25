"""The Admin menu (3.1): Users, Requests, Sources & feeds, Audit, System.

Section 3.1 puts these behind a menu rather than in the business navigation, and
the reason is editorial: they are administration, and a person doing the daily
work of clearing actions should not have to walk past user management to reach
them. The five tabs are the product; this is its plumbing.

`audit_line` lives here and is used by the product, competitor and action pages
too. That is deliberate — section 8.1 lists the fields an audit event must carry,
and rendering them in one function means a change history looks the same wherever
it is shown, including the before-and-after pair, which is the part most likely to
be quietly dropped.

**Authorization is checked on the operation, not here.** Every page in this module
is reachable only with the matching permission, but the refusal happens in
`ops.authz` at the point of the write. Section 9.2 is explicit that hiding
controls in the UI is insufficient, so this module hides them *as well*, never
*instead*.
"""

from __future__ import annotations

from ..ops import (PROVENANCE_DEFINITION, PROVENANCE_LABEL, SourceStatus)
from ..ops.db import loads
from .shell import (applied, badges, e, empty, ff, filter_bar, kv, page_head,
                    pager, panel, pill, stat, stats, when)

CHANGE_LABEL = {
    "match_resolved": "Match resolved", "match_confirmed": "Match confirmed",
    "match_rejected": "Match rejected",
    "no_counterpart_marked": "Marked no counterpart",
    "competitor_url_replaced": "Competitor URL replaced",
    "source_replaced": "Source replaced", "source_added": "Source added",
    "source_marked_unavailable": "Source marked unavailable",
    "verification_requested": "Verification requested",
    "manual_observation_entered": "Value entered by hand",
    "feed_registered": "Feed registered", "feed_approved": "Feed approved",
    "action_created": "Action raised",
    "action_transitioned": "Action moved", "action_assigned": "Action assigned",
    "request_created": "Request raised", "request_transitioned": "Request moved",
    "request_answered": "Request answered", "request_assigned": "Request owned",
    "user_created": "User created", "user_role_changed": "Role changed",
    "user_disabled": "User disabled",
    "conversation_escalated": "Conversation escalated",
}

ORIGIN_LABEL = {"ui": "in the application", "agent": "via the agent",
                "job": "by a job", "import": "by an import",
                "cli": "from the command line"}


# --------------------------------------------------------------------------
# the shared audit renderer (8.1)
# --------------------------------------------------------------------------

def audit_line(a: dict) -> str:
    """One audit event with 8.1's fields, including before and after.

    The before/after pair is the whole point of an audit trail — an entry saying
    only that something changed is a timestamp, not a record — so it is rendered
    whenever it exists rather than only on the audit page.
    """
    before = loads(a.get("before_value"), None)
    after = loads(a.get("after_value"), None)
    delta = ""
    if before or after:
        keys = sorted(set((before or {}).keys()) | set((after or {}).keys()))
        parts = []
        for k in keys:
            b = (before or {}).get(k)
            f = (after or {}).get(k)
            if b == f:
                continue
            if k == "provenance":
                b = PROVENANCE_LABEL.get(b, b)
                f = PROVENANCE_LABEL.get(f, f)
            parts.append(f'{k}: {b if b not in (None, "") else "—"} → '
                         f'{f if f not in (None, "") else "—"}')
        delta = " · ".join(parts[:6])

    where = []
    if a.get("clara_product_id"):
        where.append(f'<a href="/products/{e(a["clara_product_id"])}">product</a>')
    if a.get("competitor_key"):
        where.append(f'<a href="/competitors/{e(a["competitor_key"])}">'
                     f'{e(a["competitor_key"])}</a>')
    if a.get("action_id"):
        where.append(f'<a href="/actions/{e(a["action_id"])}">action</a>')
    if a.get("request_id"):
        where.append(f'<a href="/requests/{e(a["request_id"])}">request</a>')

    return ('<li>'
            f'<div class="when">{when(a.get("at"))} · '
            f'{e(a.get("actor") or "system")}'
            + (f' ({e(a.get("actor_role"))})' if a.get("actor_role") else "")
            + f' · {e(ORIGIN_LABEL.get(a.get("origin"), a.get("origin") or ""))}'
            + "</div>"
            f'<div class="what">'
            f'{e(CHANGE_LABEL.get(a.get("change_type"), a.get("change_type")))}'
            + (f' — {" · ".join(where)}' if where else "")
            + "</div>"
            + (f'<div class="delta">{e(delta)}</div>' if delta else "")
            + (f'<div class="ev">{e(a.get("note"))}</div>' if a.get("note")
               else "")
            + "</li>")


# --------------------------------------------------------------------------
# Users
# --------------------------------------------------------------------------

def render_users(*, users: list, ops_users: list, user: dict,
                 new_password: tuple | None = None, error: str = "",
                 notice: str = "", read_only: str = "") -> str:
    P = ['<div class="wrap">']
    P.append(page_head(
        "Users",
        "Accounts, roles and account state. A disabled account's sessions end "
        "immediately, and the last remaining admin cannot be removed.",
        trail=[("Admin", None), ("Users", None)]))

    if new_password:
        who, pw = new_password
        P.append(panel(
            f"Password for {who}",
            f'<code class="mono" style="font-size:16px;padding:7px 12px;'
            f'background:var(--card2);border-radius:5px;display:inline-block">'
            f'{e(pw)}</code>'
            '<p class="note" style="margin-top:10px">Copy it now and send it '
            'over a secure channel. It is not stored in readable form and will '
            'not be shown again; if it is lost, reset it below.</p>'))
    if error:
        P.append(f'<div class="flash err" role="alert">{e(error)}</div>')
    if notice:
        P.append(f'<div class="flash ok" role="status">{e(notice)}</div>')
    if read_only:
        P.append(f'<div class="flash err">{e(read_only)}</div>')

    by_name = {u.get("username"): u for u in ops_users}

    if not read_only:
        form = ('<form method="post" action="/admin/users/add">'
                '<div class="form-grid">'
                + ff("username", "Username", required=True, placeholder="sara.a")
                + ff("display_name", "Display name", placeholder="Sara Ahmed")
                + ff("password", "Password", kind="password",
                     hint="Leave blank and a strong one is generated and shown "
                          "once.")
                + ff("role", "Role", kind="select",
                     options=[("viewer", "User"), ("admin", "Admin")],
                     hint="A user resolves actions, asks the agent and raises "
                          "requests. An admin also owns requests, approves "
                          "sources and reads the audit history.")
                + "</div>"
                '<div class="fbar">'
                '<button class="b b-pri" type="submit">Add user</button>'
                "</div></form>")
        P.append(panel("Add a user", form))

    rows = []
    for u in users:
        me = u["username"] == user["username"]
        ops_u = by_name.get(u["username"], {})
        acts = []
        if not read_only:
            def form(action, label, extra="", danger=False):
                return (f'<form method="post" action="{action}" '
                        f'style="display:inline">'
                        f'<input type="hidden" name="username" '
                        f'value="{e(u["username"])}">{extra}'
                        f'<button class="b b-sm{" b-danger" if danger else ""}" '
                        f'type="submit">{e(label)}</button></form> ')
            acts.append(form("/admin/users/disable", "Disable") if u["is_active"]
                        else form("/admin/users/enable", "Enable"))
            acts.append(form(
                "/admin/users/role",
                "Make user" if u["role"] == "admin" else "Make admin",
                f'<input type="hidden" name="role" value='
                f'"{"viewer" if u["role"] == "admin" else "admin"}">'))
            acts.append(form("/admin/users/reset", "New password"))
            if not me:
                acts.append(form("/admin/users/delete", "Delete", danger=True))
        rows.append(
            '<tr><td>'
            f'<span class="ttl">{e(u["username"])}</span>'
            + (' <span class="pl pl-clara">you</span>' if me else "")
            + f'<div class="sub">{e(u.get("display_name") or "")}</div></td>'
            f'<td>{pill("Admin" if u["role"] == "admin" else "User", "clara" if u["role"] == "admin" else "quiet")}</td>'
            f'<td>{pill("Active", "ok") if u["is_active"] else pill("Disabled", "no")}</td>'
            f'<td><div class="sub">{when(u.get("last_login_at"))}</div></td>'
            f'<td><div class="sub">{when(ops_u.get("created_at"), date_only=True)}</div></td>'
            f'<td>{"".join(acts) or "<span class=\'na\'>managed locally</span>"}</td>'
            "</tr>")
    body = ('<div class="scroll"><table class="t"><thead><tr>'
            '<th>User</th><th>Role</th><th>State</th><th>Last sign-in</th>'
            '<th>On record since</th><th>Manage</th></tr></thead><tbody>'
            + "".join(rows) + "</tbody></table></div>")
    P.append(panel(f"Users ({len(users)})", body, flush=True,
                   note="every change here is an audit event"))
    P.append("</div>")
    return "".join(P)


# --------------------------------------------------------------------------
# Sources and feeds (4.3, 9.1)
# --------------------------------------------------------------------------

SOURCE_FILTER = [("", "Any state"), (SourceStatus.ACTIVE, "Readable"),
                 (SourceStatus.UNREADABLE, "Unreadable"),
                 (SourceStatus.UNAVAILABLE, "Unavailable"),
                 (SourceStatus.PENDING_VERIFICATION, "Verification requested"),
                 ("unapproved", "Not approved")]


def render_sources(*, sources: list, feeds: list, counts: dict, query: dict,
                   error: str = "", notice: str = "") -> str:
    P = ['<div class="wrap">']
    P.append(page_head(
        "Sources & feeds",
        "Every page a value has been read from, and every approved integration. "
        "A source is a record with a state, not a link — which is what lets an "
        "unreadable one become an action rather than a silent gap.",
        trail=[("Admin", None), ("Sources & feeds", None)]))
    if error:
        P.append(f'<div class="flash err" role="alert">{e(error)}</div>')
    if notice:
        P.append(f'<div class="flash ok" role="status">{e(notice)}</div>')

    P.append(stats([
        stat(counts["total"], "Sources", "Pages registered for a competitor.",
             tone="calm"),
        stat(counts["readable"], "Readable", "Last attempt succeeded.",
             tone="good"),
        stat(counts["broken"], "Broken",
             "Marked unreadable or unavailable — no current value can come "
             "from them.", tone="hot" if counts["broken"] else "good"),
        stat(counts["approved"], "Approved",
             "Explicitly approved for collection.", tone="calm"),
        stat(counts["feeds"], "Feeds & APIs",
             "Registered integrations; values from them are labelled Approved "
             "feed/API.", tone="calm"),
    ]))

    body = (filter_bar("/admin/sources",
                       [("q", "Search", None, "URL or competitor"),
                        ("status", "State", SOURCE_FILTER)], query)
            + applied("/admin/sources", query,
                      {"q": "Search", "status": "State"}))
    if not sources:
        body += empty("No source matches",
                      "Nothing here matches these filters.",
                      '<a class="b" href="/admin/sources">Clear filters</a>')
    else:
        rows = []
        for s in sources:
            st = s.get("status") or "active"
            rows.append(
                '<tr><td>'
                f'<a class="ttl" href="{e(s.get("url"))}" '
                f'rel="nofollow noopener">{e((s.get("url") or "")[:80])}</a>'
                f'<div class="sub">'
                + (f'<a href="/competitors/{e(s.get("competitor_key"))}">'
                   f'{e(s.get("competitor_key"))}</a>'
                   if s.get("competitor_key") else "no competitor")
                + f' · {e(s.get("kind") or "page")}</div></td>'
                '<td>' + badges(
                    pill(st.replace("_", " ").title(),
                         "ok" if st == SourceStatus.ACTIVE
                         else "bad" if st == SourceStatus.UNREADABLE
                         else "amb" if st == SourceStatus.PENDING_VERIFICATION
                         else "no"),
                    pill("approved", "ok") if s.get("is_approved")
                    else pill("not approved", "quiet"))
                + (f'<div class="ev">{e(s.get("status_reason") or "")}</div>'
                   if s.get("status_reason") else "")
                + "</td>"
                f'<td class="num">{s.get("fail_count") or 0}</td>'
                f'<td><div class="sub">{when(s.get("last_ok_at"))}</div>'
                + (f'<div class="ev">{e(s.get("last_failure"))}</div>'
                   if s.get("last_failure") else "")
                + "</td>"
                '<td class="num">'
                + (f'<form method="post" action="/admin/sources/approve" '
                   f'style="display:inline">'
                   f'<input type="hidden" name="source_id" '
                   f'value="{e(s["source_id"])}">'
                   f'<button class="b b-sm" type="submit">Approve</button>'
                   f'</form>' if not s.get("is_approved") else "")
                + "</td></tr>")
        body += ('<div class="scroll"><table class="t"><thead><tr>'
                 '<th>URL</th><th>State</th><th>Failures</th>'
                 '<th>Last read</th><th></th></tr></thead><tbody>'
                 + "".join(rows) + "</tbody></table></div>")
        body += pager("/admin/sources", query, counts["filtered"], 200, 0,
                      "sources")
    P.append(panel("", body, flush=True))

    # ---- feeds ----
    fbody = []
    if feeds:
        rows = []
        for f in feeds:
            rows.append(
                '<tr><td>'
                f'<span class="ttl">{e(f.get("name"))}</span>'
                f'<div class="sub">{e((f.get("endpoint") or "")[:70])}</div></td>'
                f'<td><div class="sub">'
                + (f'<a href="/competitors/{e(f["competitor_key"])}">'
                   f'{e(f["competitor_key"])}</a>' if f.get("competitor_key")
                   else "any competitor")
                + f' · {e(f.get("kind") or "api")}</div></td>'
                '<td>' + (pill("Approved", "ok") if f.get("is_approved")
                          else pill("Awaiting approval", "amb")) + "</td>"
                f'<td><div class="sub">{e(f.get("registered_by") or "")} '
                f'{when(f.get("registered_at"), date_only=True)}</div>'
                + (f'<div class="ev">approved by {e(f["approved_by"])} '
                   f'{when(f.get("approved_at"), date_only=True)}</div>'
                   if f.get("approved_by") else "")
                + "</td>"
                '<td class="num">'
                + (f'<form method="post" action="/admin/feeds/approve" '
                   f'style="display:inline">'
                   f'<input type="hidden" name="feed_id" '
                   f'value="{e(f["feed_id"])}">'
                   f'<button class="b b-sm b-pri" type="submit">Approve</button>'
                   f'</form>' if not f.get("is_approved") else "")
                + "</td></tr>")
        fbody.append('<div class="scroll"><table class="t"><thead><tr>'
                     '<th>Feed or API</th><th>For</th><th>State</th>'
                     '<th>Registered</th><th></th></tr></thead><tbody>'
                     + "".join(rows) + "</tbody></table></div>")
    else:
        fbody.append(empty(
            "No feed or API is registered",
            "A feed is an administratively approved integration. Values from "
            "one carry the Approved feed/API provenance label, which is why "
            "registering and approving are separate steps."))
    fbody.append('<form method="post" action="/admin/feeds/add" '
                 'style="padding:16px;border-top:1px solid var(--line)">'
                 '<div class="form-grid">'
                 + ff("name", "Name", required=True,
                      placeholder="Competitor price API")
                 + ff("endpoint", "Endpoint", kind="url", required=True,
                      placeholder="https://api.example/prices")
                 + ff("competitor_key", "Competitor key",
                      hint="Leave blank if it covers more than one.")
                 + ff("kind", "Kind", kind="select",
                      options=[("api", "API"), ("feed", "Feed"),
                               ("file", "File drop")])
                 + ff("approve", "Approve now", kind="select",
                      options=[("1", "Yes"), ("", "No — register only")])
                 + "</div>"
                 '<div class="fbar">'
                 '<button class="b b-pri" type="submit">Register</button>'
                 "</div></form>")
    P.append(panel(f"Approved feeds and APIs ({len(feeds)})",
                   "".join(fbody), flush=True))
    P.append("</div>")
    return "".join(P)


# --------------------------------------------------------------------------
# Audit history (8)
# --------------------------------------------------------------------------

def render_audit(*, rows: list, total: int, query: dict, limit: int,
                 offset: int, change_types: list, actors: list) -> str:
    P = ['<div class="wrap">']
    P.append(page_head(
        "Audit history",
        "Who changed what, when, and from what to what. Append-only: nothing "
        "here can be edited or deleted through the application, and a "
        "correction adds a record rather than replacing one.",
        trail=[("Admin", None), ("Audit history", None)]))

    body = (filter_bar("/admin/audit",
                       [("q", "Search", None, "Note, actor or record id"),
                        ("change_type", "Change",
                         [("", "Any change")]
                         + [(c, CHANGE_LABEL.get(c, c)) for c in change_types]),
                        ("actor", "Actor",
                         [("", "Anyone")] + [(a, a) for a in actors]),
                        ("origin", "Origin",
                         [("", "Any origin")]
                         + [(k, v) for k, v in ORIGIN_LABEL.items()])],
                       query)
            + applied("/admin/audit", query,
                      {"q": "Search", "change_type": "Change",
                       "actor": "Actor", "origin": "Origin"}))
    if not rows:
        body += empty("No audit event matches",
                      "Nothing recorded matches these filters.",
                      '<a class="b" href="/admin/audit">Clear filters</a>')
    else:
        body += ('<div class="panel-b"><ul class="hist">'
                 + "".join(audit_line(a) for a in rows) + "</ul></div>")
        body += pager("/admin/audit", query, total, limit, offset, "events")
    P.append(panel("", body, flush=True))

    P.append(panel(
        "The four provenance labels",
        kv([(PROVENANCE_LABEL[k], e(PROVENANCE_DEFINITION[k]))
            for k in PROVENANCE_LABEL]),
        note="section 8.2; every displayable value carries one"))
    P.append("</div>")
    return "".join(P)


# --------------------------------------------------------------------------
# System (9)
# --------------------------------------------------------------------------

def render_system(*, engine: dict, schema: dict, imports: list,
                  retention: list, jobs: list, tables: dict) -> str:
    P = ['<div class="wrap">']
    P.append(page_head(
        "System",
        "Where operational data is stored, what version the schema is at, and "
        "what has been imported into it.",
        trail=[("Admin", None), ("System", None)]))

    durable = engine.get("durable")
    P.append(panel(
        "Storage",
        kv([("Engine", e(engine.get("engine"))),
            ("Driver", e(engine.get("driver"))),
            ("Target", e(engine.get("target"))),
            ("Durable for hosting",
             pill("Yes", "ok") if durable else pill("No", "bad")),
            ("Schema version", e(schema.get("version"))),
            ("Migrations applied", e(schema.get("applied") or "none this start"))])
        + f'<p class="note {"good" if durable else "bad"}">'
        + e(engine.get("why") or "") + "</p>",
        note="section 9: operational writes must survive restarts and "
             "redeployment"))

    P.append(panel(
        "Durable records",
        kv([(name.replace("ops_", "").replace("_", " ").capitalize(), str(n))
            for name, n in tables.items()]),
        note="section 9.1's checklist, as row counts"))

    if imports:
        rows = []
        for im in imports:
            counts = loads(im.get("counts"), {}) or {}
            summary = ", ".join(f"{k.replace('_', ' ')} {v}"
                                for k, v in counts.items()
                                if isinstance(v, int) and v)
            rows.append(
                f'<li><div class="when">{when(im.get("at"))} · '
                f'{e(im.get("actor") or "system")}</div>'
                f'<div class="what">run {e(im.get("run_id") or "unknown")} '
                f'from {e(im.get("source"))}</div>'
                f'<div class="ev">{e(summary)}</div></li>')
        P.append(panel(f"Imports ({len(imports)})",
                       '<ul class="hist">' + "".join(rows) + "</ul>",
                       note="an import never overwrites a human decision"))
    else:
        P.append(panel("Imports",
                       '<p class="note warn">No collection run has been '
                       'imported yet.</p>'))

    if retention:
        P.append(panel(
            "Retention policy",
            kv([(r["scope"].capitalize(),
                 (f'{r["keep_days"]} days' if r.get("keep_days")
                  else "kept indefinitely")
                 + f'<div class="ev">{e(r.get("policy") or "")}</div>')
                for r in retention]),
            note="section 9.2"))

    if jobs:
        rows = []
        for j in jobs:
            rows.append(
                f'<li><div class="when">{when(j.get("requested_at"))} · '
                f'{e(j.get("requested_by") or "system")}</div>'
                f'<div class="what">{e(j.get("job_type"))} — '
                f'{e(j.get("status"))}</div>'
                + (f'<div class="ev">{e(j.get("last_error"))}</div>'
                   if j.get("last_error") else "")
                + (f'<div class="ev">'
                   f'<a href="/actions/{e(j["action_id"])}">action</a></div>'
                   if j.get("action_id") else "")
                + "</li>")
        P.append(panel(f"Verification jobs ({len(jobs)})",
                       '<ul class="hist">' + "".join(rows) + "</ul>",
                       note="a durable database-backed job table; section 9.2 "
                            "does not require a distributed queue for MVP"))
    P.append("</div>")
    return "".join(P)
