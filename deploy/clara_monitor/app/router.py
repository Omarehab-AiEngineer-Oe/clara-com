"""One route table for the whole application.

`serve.py` and the serverless entrypoint are two very different hosts — a
threaded local server with a real disk, and a cold serverless instance with
neither. The addendum applies to both equally, so neither may own the routes: if
each host wired its own, the local site and the hosted one would drift into two
applications that merely look alike, and the deployed one would be the one nobody
tested.

So both call `handle(Request) -> Response` and do nothing else. What a host still
owns is authentication and transport; everything after "who is this" is here.

Three conventions run through the file.

**A GET renders, a POST writes and redirects.** Every write ends in a redirect
carrying a flash message, so a resolution cannot be replayed by refreshing the
page — and the redirect target is the record that changed, so the reader sees the
result rather than a confirmation screen.

**Authorization failures are answers, not crashes.** `ops.authz.Denied` carries a
sentence naming the role needed, and it is rendered as a 403 page with that
sentence. Section 9.2 requires the refusal to happen on the server; this is where
that refusal becomes something a person can read.

**Routing is explicit, and unknown paths 404.** There is no catch-all that
renders the old report page, because a stale route quietly serving the retired
surface is how section 2's "no longer appropriate" list survives a rewrite.
"""

from __future__ import annotations

import urllib.parse

from ..ops import Actor, engine_status
from ..ops.actions import Actions
from ..ops.agent import IntelligenceAgent
from ..ops.authz import Denied, Permission, can, require
from ..ops.requests import Requests
from ..ops.schema import SCHEMA_VERSION, SourceStatus, schema_version
from . import (actions_view, admin_view, agent_view, competitors, overview,
               products, read, requests_view)
from .shell import TABS, e, one, page, panel, qs

PAGE_SIZE = 50
AUDIT_PAGE = 60


class Request:
    """What a host hands the router once it knows who is asking."""

    def __init__(self, *, method: str, path: str, query: dict | None = None,
                 form: dict | None = None, user: dict, db, auth=None,
                 llm=None):
        self.method = (method or "GET").upper()
        self.path = "/" + (path or "/").strip("/")
        self.query = query or {}
        self.form = form or {}
        self.user = user
        self.db = db
        self.auth = auth
        self.llm = llm
        self.actor = Actor.from_user(user, origin="ui")

    def q(self, key: str, default: str = "") -> str:
        return one(self.query, key, default)

    def f(self, key: str, default: str = "") -> str:
        v = self.form.get(key)
        if isinstance(v, list):
            v = v[0] if v else None
        return str(v).strip() if v not in (None, "") else default

    @property
    def page_no(self) -> int:
        try:
            return max(1, int(self.q("page", "1")))
        except ValueError:
            return 1

    @property
    def offset(self) -> int:
        return (self.page_no - 1) * PAGE_SIZE


class Response:
    def __init__(self, body: str = "", *, status: int = 200,
                 content_type: str = "text/html; charset=utf-8",
                 location: str = "", headers: dict | None = None):
        self.body = body
        self.status = status
        self.content_type = content_type
        self.location = location
        self.headers = headers or {}

    @classmethod
    def see(cls, location: str, *, tone: str = "ok", message: str = "") -> "Response":
        """A redirect after a write, carrying what happened."""
        if message:
            sep = "&" if "?" in location else "?"
            location = (f"{location}{sep}flash={urllib.parse.quote(message)}"
                        f"&tone={urllib.parse.quote(tone)}")
        return cls(status=303, location=location)


# --------------------------------------------------------------------------
# entry point
# --------------------------------------------------------------------------

def handle(req: Request) -> Response:
    try:
        return _route(req)
    except Denied as exc:
        return _denied(req, exc)
    except KeyError as exc:
        return _simple(req, "Not found", str(exc) or "no such record",
                       status=404)


def _route(req: Request) -> Response:
    path, method = req.path, req.method

    if method == "POST":
        return _post(req, path)

    if path in ("/", "/overview"):
        return _overview(req)
    if path == "/products":
        return _products(req)
    if path.startswith("/products/"):
        return _product(req, path[len("/products/"):])
    if path == "/competitors":
        return _competitors(req)
    if path.startswith("/competitors/"):
        return _competitor(req, path[len("/competitors/"):])
    if path == "/offers":
        return _offers(req)
    if path == "/actions":
        return _actions(req)
    if path.startswith("/actions/"):
        return _action(req, path[len("/actions/"):])
    if path == "/requests":
        return _requests(req)
    if path == "/requests/new":
        return _request_new(req)
    if path.startswith("/requests/"):
        return _request(req, path[len("/requests/"):])
    if path.startswith("/conversations/"):
        return _conversation(req, path[len("/conversations/"):])
    if path == "/admin/requests":
        return _requests(req, force_all=True)
    if path == "/admin/users":
        return _admin_users(req)
    if path == "/admin/sources":
        return _admin_sources(req)
    if path == "/admin/audit":
        return _admin_audit(req)
    if path == "/admin/system":
        return _admin_system(req)
    return _simple(req, "Not found",
                   f"There is no page at {path}. The application has five "
                   "tabs; the header has all of them.", status=404)


def _post(req: Request, path: str) -> Response:
    parts = path.strip("/").split("/")

    if parts[:1] == ["actions"] and len(parts) == 3:
        return _action_post(req, parts[1], parts[2])
    if path == "/requests/new":
        return _request_create(req)
    if parts[:1] == ["requests"] and len(parts) == 3:
        return _request_post(req, parts[1], parts[2])
    if path == "/agent/ask":
        return _agent_ask(req)
    if path == "/agent/escalate":
        return _agent_escalate(req)
    if path.startswith("/admin/users/"):
        return _admin_users_post(req, parts[-1])
    if path == "/admin/sources/approve":
        return _admin_source_approve(req)
    if path == "/admin/feeds/add":
        return _admin_feed_add(req)
    if path == "/admin/feeds/approve":
        return _admin_feed_approve(req)
    return _simple(req, "Not found", f"Nothing accepts a POST at {path}.",
                   status=404)


# --------------------------------------------------------------------------
# rendering helpers
# --------------------------------------------------------------------------

def _flash(req: Request):
    msg = req.q("flash")
    if not msg:
        return None
    tone = req.q("tone", "ok")
    return ("ok" if tone == "ok" else "err", msg)


def _render(req: Request, title: str, body: str, active: str = "", *,
            status: int = 200, ctx_kind: str = "", ctx_id: str = "",
            ctx_label: str = "") -> Response:
    """Wrap a page in the shell, with the Agent panel if it is open."""
    counts = read.tab_counts(req.db, req.actor)
    panel_html = ""
    if req.q("agent") == "1":
        panel_html = _agent_panel(req, ctx_kind, ctx_id, ctx_label)
    agent_href = req.path + qs(req.query, agent="1",
                               ctx=ctx_kind or None, ctxid=ctx_id or None)
    return Response(page(title, body, user=req.user, active=active,
                         counts=counts, agent_panel=panel_html,
                         agent_href=agent_href, flash=_flash(req)),
                    status=status)


def _agent_panel(req: Request, ctx_kind: str, ctx_id: str,
                 ctx_label: str) -> str:
    """The panel, with whatever record the page is showing (3.1)."""
    if not can(req.actor, Permission.AGENT_ASK):
        return ""
    agent = IntelligenceAgent(req.db, llm=req.llm)
    # An explicit ctx in the URL wins: it is what the reader clicked.
    kind = req.q("ctx") or ctx_kind
    rid = req.q("ctxid") or ctx_id
    conv = None
    cid = req.q("c")
    if cid:
        try:
            conv = agent.conversation(cid, req.actor)
        except Denied:
            conv = None
    return agent_view.render_panel(
        path=req.path, query=req.query, conversation=conv, ctx_kind=kind,
        ctx_id=rid, ctx_label=ctx_label or _label_for(req, kind, rid),
        error=req.q("agent_error"), actor=req.actor)


def _label_for(req: Request, kind: str, rid: str) -> str:
    if not (kind and rid):
        return ""
    if kind == "product":
        return req.db.value(
            "SELECT name FROM ops_product WHERE clara_product_id=?",
            (rid,), rid) or rid
    if kind == "competitor":
        return req.db.value(
            "SELECT brand FROM ops_competitor WHERE competitor_key=?",
            (rid,), rid) or rid
    return rid


def _simple(req: Request, title: str, message: str, *,
            status: int = 200) -> Response:
    body = ('<div class="wrap narrow">'
            f'<div class="ph"><h1>{e(title)}</h1></div>'
            f'<p class="lede">{e(message)}</p>'
            '<div class="fbar">'
            + "".join(f'<a class="b" href="{e(href)}">{e(label)}</a>'
                      for _k, href, label, _w in TABS)
            + "</div></div>")
    return _render(req, title, body, status=status)


def _denied(req: Request, exc: Denied) -> Response:
    body = ('<div class="wrap narrow">'
            '<div class="ph"><h1>Not permitted</h1></div>'
            f'<div class="flash err" role="alert">{e(str(exc))}</div>'
            '<p class="lede">This is refused on the server, not merely hidden '
            'on the page. If you need it done, send a request and an admin can '
            'do it.</p>'
            '<div class="fbar">'
            '<a class="b b-pri" href="/requests/new">Send Request</a>'
            '<a class="b" href="/overview">Back to Overview</a>'
            "</div></div>")
    return _render(req, "Not permitted", body, status=403)


def _competitor_options(db) -> list:
    return [(r["competitor_key"], r.get("brand") or r["competitor_key"])
            for r in db.rows("SELECT competitor_key, brand FROM ops_competitor "
                             "ORDER BY brand")]


def _segment_options(db) -> list:
    return [r["segment"] for r in db.rows(
        "SELECT DISTINCT segment FROM ops_product WHERE segment IS NOT NULL "
        "AND segment <> '' ORDER BY segment")]


# --------------------------------------------------------------------------
# the five tabs
# --------------------------------------------------------------------------

def _overview(req: Request) -> Response:
    ov = read.overview(req.db, req.actor)
    return _render(req, "Overview", overview.render(ov, user=req.user),
                   "overview")


def _products(req: Request) -> Response:
    data = read.product_list(
        req.db, q=req.q("q"), attention=req.q("attention"),
        status=req.q("status"), competitor=req.q("competitor"),
        segment=req.q("segment"), sort=req.q("sort", "attention"),
        limit=PAGE_SIZE, offset=req.offset)
    body = products.render_list(data, query=req.query,
                                competitors=_competitor_options(req.db),
                                segments=_segment_options(req.db))
    return _render(req, "Products", body, "products")


def _product(req: Request, pid: str) -> Response:
    pid = urllib.parse.unquote(pid)
    d = read.product_detail(req.db, pid)
    if not d:
        return _simple(req, "No such product",
                       f"Nothing in the catalogue has the id {pid}.",
                       status=404)
    body = products.render_detail(d, query=req.query)
    return _render(req, d["name"], body, "products",
                   ctx_kind="product", ctx_id=pid, ctx_label=d["name"])


def _competitors(req: Request) -> Response:
    data = read.competitor_list(
        req.db, q=req.q("q"), segment=req.q("segment"),
        coverage=req.q("coverage"), sort=req.q("sort", "attention"),
        limit=PAGE_SIZE, offset=req.offset)
    segs = sorted({s for r in read.competitor_rows(req.db)
                   for s in r["segments"]})
    body = competitors.render_list(data, query=req.query, segments=segs)
    return _render(req, "Competitors", body, "competitors")


def _competitor(req: Request, key: str) -> Response:
    key = urllib.parse.unquote(key)
    d = read.competitor_detail(req.db, key)
    if not d:
        return _simple(req, "No such competitor",
                       f"No competitor is recorded under the key {key}.",
                       status=404)
    body = competitors.render_detail(
        d, query=req.query, can_admin=can(req.actor, Permission.SOURCE_APPROVE))
    return _render(req, d["brand"], body, "competitors",
                   ctx_kind="competitor", ctx_id=key, ctx_label=d["brand"])


def _offers(req: Request) -> Response:
    """3.1: offers are contextual, with an optional filtered view. This is it."""
    data = read.offers(req.db, competitor=req.q("competitor"),
                       limit=PAGE_SIZE, offset=req.offset)
    from .shell import (applied, filter_bar, page_head, pager,
                        send_request_btn, stat, stats)
    P = ['<div class="wrap">']
    P.append(page_head(
        "Offers",
        "Promotions read on competitor pages. Not a main tab — offers belong "
        "beside the products and competitors they affect, and this is the "
        "filtered view of all of them.",
        trail=[("Competitors", "/competitors"), ("Offers", None)]))
    P.append(stats([
        stat(data["unique"], "Unique offers",
             "Distinct promotion wording per competitor."),
        stat(data["associations"], "Product associations",
             "Product-level rows carrying those offers."),
        stat(data["active"], "Active", "Observed recently enough to still run.",
             tone="good" if data["active"] else "calm"),
    ]))
    P.append(f'<p class="note">{e(data["definition"])}</p>')
    body = (filter_bar("/offers",
                       [("competitor", "Competitor",
                         [("", "Every competitor")]
                         + _competitor_options(req.db))], req.query)
            + applied("/offers", req.query, {"competitor": "Competitor"}))
    if not data["rows"]:
        from .shell import empty
        body += empty("No offer on record",
                      "No promotion wording has been observed for this filter.",
                      '<a class="b" href="/offers">Clear filters</a>')
    else:
        rows = []
        from .shell import badges, fresh, money, pill, prov, when
        for g in data["rows"]:
            prods = "".join(
                f'<li><a href="/products/{e(p["clara_product_id"])}">'
                f'{e(p["name"] or p["clara_product_id"])}</a> — '
                f'{money(p["price"], p["currency"])}</li>'
                for p in g["products"][:10])
            rows.append(
                f'<div class="opt-row"><h3>{e(g["wording"])}</h3>'
                f'<div class="oh">'
                f'<a href="/competitors/{e(g["competitor_key"])}">'
                f'{e(g["competitor_key"])}</a> · observed '
                f'{when(g["observed_at"])} '
                + badges(fresh(g["freshness"]["state"], g["freshness"]["why"],
                               g["freshness"].get("days")),
                         prov(g["provenance"], short=True),
                         pill(f'{g["association_count"]} product'
                              f'{"s" if g["association_count"] != 1 else ""}',
                              "quiet"))
                + " " + send_request_btn("offer", g.get("obs_id") or "",
                                         label="Verify this offer", small=True)
                + "</div>"
                + (f'<ul class="hist">{prods}</ul>' if prods else "")
                + "</div>")
        body += '<div class="opts">' + "".join(rows) + "</div>"
        body += pager("/offers", req.query, data["total"], data["limit"],
                      data["offset"], "offers")
    P.append(panel("", body, flush=True))
    P.append("</div>")
    return _render(req, "Offers", "".join(P), "competitors")


def _actions(req: Request) -> Response:
    # An empty status means "still needs a person", not "everything": the queue
    # is a worklist, and defaulting it to include resolved rows would bury the
    # open ones. "all" is the explicit way to see the rest.
    status = req.q("status")
    assignee = req.q("assignee")
    if assignee == "none":
        assignee = "unassigned"
    elif assignee == "me":
        assignee = req.actor.username
    q = Actions(req.db).queue(
        status="" if status == "all" else (status or "open"),
        action_type=req.q("type"), assignee=assignee,
        priority=req.q("priority"), competitor_key=req.q("competitor"),
        q=req.q("q"), sort=req.q("sort", "urgency"),
        limit=PAGE_SIZE, offset=req.offset)
    assignees = [r["assignee"] for r in req.db.rows(
        "SELECT DISTINCT assignee FROM ops_action WHERE assignee IS NOT NULL "
        "AND assignee <> '' ORDER BY assignee")]
    body = actions_view.render_queue(
        q, query=req.query, user=req.user, assignees=assignees,
        competitors=_competitor_options(req.db))
    return _render(req, "Actions", body, "actions")


def _action(req: Request, aid: str) -> Response:
    aid = urllib.parse.unquote(aid)
    a = Actions(req.db).get(aid)
    if not a:
        return _simple(req, "No such action",
                       f"No action is recorded with the id {aid}. It may have "
                       "been resolved and removed by a retention policy.",
                       status=404)
    body = actions_view.render_detail(
        a, user=req.user, actor=req.actor, query=req.query,
        error=req.q("error"), tried=req.q("tried"))
    return _render(req, a.get("type_label") or "Action", body, "actions",
                   ctx_kind="action", ctx_id=aid,
                   ctx_label=(a.get("reason") or "")[:50])


def _requests(req: Request, *, force_all: bool = False) -> Response:
    scope = "all" if force_all else req.q("scope")
    mine = not (scope == "all" and req.actor.is_admin)
    rq = Requests(req.db)
    data = rq.list(actor=req.actor, mine=mine, status=req.q("status"),
                   request_type=req.q("type"), owner=req.q("owner"),
                   q=req.q("q"), sort=req.q("sort", "urgency"),
                   limit=PAGE_SIZE, offset=req.offset)
    counts = rq.counts(req.actor)
    query = dict(req.query)
    if force_all:
        query["scope"] = "all"
    body = requests_view.render_list(data, query=query, user=req.user,
                                     actor=req.actor, counts=counts)
    return _render(req, "Requests", body, "requests")


def _request_new(req: Request) -> Response:
    kind, rid = req.q("kind"), req.q("id")
    ctx = ({"kind": "", "ok": False} if not kind
           else Requests(req.db).context_for(kind, rid))
    body = requests_view.render_new(ctx=ctx, user=req.user)
    return _render(req, "Send Request", body, "requests")


def _request(req: Request, rid: str) -> Response:
    rid = urllib.parse.unquote(rid)
    r = Requests(req.db).get(rid, req.actor)
    if not r:
        return _simple(req, "No such request",
                       f"No request is recorded with the id {rid}, or it "
                       "belongs to someone else.", status=404)
    body = requests_view.render_detail(r, user=req.user, actor=req.actor,
                                       error=req.q("error"))
    return _render(req, r.get("subject") or "Request", body, "requests")


def _conversation(req: Request, cid: str) -> Response:
    conv = IntelligenceAgent(req.db).conversation(urllib.parse.unquote(cid),
                                                 req.actor)
    if not conv:
        return _simple(req, "No such conversation",
                       "That conversation is not on record.", status=404)
    return _render(req, "Agent conversation",
                   agent_view.render_conversation(conv), "requests")


# --------------------------------------------------------------------------
# actions: writes (4)
# --------------------------------------------------------------------------

def _action_post(req: Request, aid: str, verb: str) -> Response:
    acts = Actions(req.db)
    back = f"/actions/{urllib.parse.quote(aid)}"
    try:
        if verb == "resolve":
            option = req.f("option")
            fields = {k: req.f(k) for k in req.form
                      if k not in ("option", "note")}
            out = acts.resolve(aid, option=option, actor=req.actor,
                               note=req.f("note"), **fields)
            return Response.see(
                back, message=f"Saved: {out.get('summary') or option}. "
                              "The change, the transition and the audit event "
                              "were written together.")
        if verb == "claim":
            acts.claim(aid, req.actor)
            return Response.see(back, message="You own this action.")
        if verb == "assign":
            acts.assign(aid, req.f("assignee"), req.actor)
            return Response.see(back,
                                message=f"Assigned to {req.f('assignee')}.")
        if verb == "schedule":
            acts.schedule(aid, req.actor, priority=req.f("priority"),
                          due_date=req.f("due_date"))
            return Response.see(back, message="Scheduling saved.")
        if verb == "dismiss":
            acts.dismiss(aid, req.actor, req.f("reason"))
            return Response.see(back, message="Dismissed without changing any "
                                              "value. The reason is audited.")
    except Denied:
        raise
    except (ValueError, KeyError) as exc:
        return Response.see(back + f"?error={urllib.parse.quote(str(exc))}"
                                   f"&tried={urllib.parse.quote(req.f('option'))}",
                            tone="err", message=str(exc))
    return _simple(req, "Not found", f"Actions do not accept {verb}.",
                   status=404)


# --------------------------------------------------------------------------
# requests: writes (5)
# --------------------------------------------------------------------------

def _request_create(req: Request) -> Response:
    rq = Requests(req.db)
    kind, rid = req.f("kind"), req.f("id")
    ctx = rq.context_for(kind, rid) if kind else {}
    ctx = {k: v for k, v in (ctx or {}).items() if k != "ok"}
    if req.f("evidence"):
        ctx["evidence"] = req.f("evidence")
    try:
        new_id = rq.create(
            request_type=req.f("request_type") or "other",
            subject=req.f("subject"), description=req.f("description"),
            actor=req.actor, priority=req.f("priority", "medium"),
            detail_level=req.f("detail_level"), context=ctx)
    except Denied:
        raise
    except ValueError as exc:
        form = {k: req.f(k) for k in req.form}
        body = requests_view.render_new(
            ctx=rq.context_for(kind, rid) if kind else {"kind": "", "ok": False},
            form=form, errors={"subject": str(exc), "description": str(exc)},
            user=req.user)
        return _render(req, "Send Request", body, "requests", status=400)
    return Response.see(f"/requests/{new_id}",
                        message="Request sent. It is New until an admin picks "
                                "it up.")


def _request_post(req: Request, rid: str, verb: str) -> Response:
    rq = Requests(req.db)
    back = f"/requests/{urllib.parse.quote(rid)}"
    try:
        if verb == "reply":
            rq.reply(rid, req.f("body"), req.actor)
            return Response.see(back, message="Reply added.")
        if verb == "take":
            rq.take(rid, req.actor)
            return Response.see(back, message="You own this request.")
        if verb == "status":
            to = req.f("to_status")
            rq.transition(rid, to, req.actor, note=req.f("note"),
                          resolution=req.f("resolution"),
                          closure_reason=req.f("closure_reason"))
            from ..ops import REQUEST_STATUS_LABEL
            return Response.see(
                back, message=f"Moved to "
                              f"{REQUEST_STATUS_LABEL.get(to, to)}.")
    except Denied:
        raise
    except (ValueError, KeyError) as exc:
        return Response.see(back, tone="err", message=str(exc))
    return _simple(req, "Not found", f"Requests do not accept {verb}.",
                   status=404)


# --------------------------------------------------------------------------
# the agent (6, 7)
# --------------------------------------------------------------------------

def _safe_back(raw: str, fallback: str = "/overview") -> str:
    """Only same-site paths. A `back` parameter is attacker-supplied input."""
    if not raw.startswith("/") or raw.startswith("//"):
        return fallback
    return raw


def _agent_ask(req: Request) -> Response:
    agent = IntelligenceAgent(req.db, llm=req.llm)
    question = req.f("question")
    back = _safe_back(req.f("back"))
    cid = req.f("conversation_id")
    kind, rid = req.f("ctx"), req.f("ctxid")
    if not question:
        return Response.see(back, tone="err",
                            message="Ask a question first.")
    if not cid:
        cid = agent.start(req.actor, context_kind=kind, context_id=rid,
                          title=question[:80])
    agent.ask(cid, question, req.actor, context_kind=kind, context_id=rid)
    sep = "&" if "?" in back else "?"
    return Response(status=303,
                    location=f"{back}{sep}agent=1&c={urllib.parse.quote(cid)}"
                             + (f"&ctx={urllib.parse.quote(kind)}" if kind else "")
                             + (f"&ctxid={urllib.parse.quote(rid)}" if rid else ""))


def _agent_escalate(req: Request) -> Response:
    agent = IntelligenceAgent(req.db, llm=req.llm)
    cid = req.f("conversation_id")
    try:
        rid = agent.escalate(cid, req.actor,
                             request_type=req.f("request_type"),
                             extra=req.f("extra"))
    except Denied:
        raise
    except (ValueError, KeyError) as exc:
        return Response.see(_safe_back(req.f("back")), tone="err",
                            message=str(exc))
    return Response.see(f"/requests/{rid}",
                        message="Raised from the conversation, with its "
                                "summary, citations and the missing evidence "
                                "attached.")


# --------------------------------------------------------------------------
# admin (3.1, 8, 9)
# --------------------------------------------------------------------------

def _admin_users(req: Request) -> Response:
    require(req.actor, Permission.USER_MANAGE)
    users = req.auth.list_users() if req.auth else []
    ops_users = req.db.rows("SELECT * FROM ops_user ORDER BY username")
    pw = None
    if req.q("pw_user") and req.q("pw"):
        pw = (req.q("pw_user"), req.q("pw"))
    body = admin_view.render_users(
        users=users, ops_users=ops_users, user=req.user, new_password=pw,
        error=req.q("error"), notice=req.q("notice"),
        read_only="" if req.auth and getattr(req.auth, "writable", True)
        else "User management is read-only in this deployment: writes would go "
             "to storage no other instance can see.")
    return _render(req, "Users", body)


def _admin_users_post(req: Request, verb: str) -> Response:
    require(req.actor, Permission.USER_MANAGE)
    if not req.auth:
        return Response.see("/admin/users", tone="err",
                            message="User management is unavailable here.")
    from ..ops.audit import Audit
    from ..ops.schema import ChangeType, Origin
    audit = Audit(req.db)
    name = req.f("username")
    try:
        if verb == "add":
            pw = req.auth.add_user(
                name, req.f("password") or None,
                display_name=req.f("display_name"),
                role=req.f("role", "viewer"), by=req.user["username"])
            with req.db.tx():
                audit.record(actor=req.actor.username,
                             actor_role=req.actor.role,
                             change_type=ChangeType.USER_CREATED,
                             origin=Origin.UI,
                             after={"username": name, "role": req.f("role")},
                             note=f"user {name} created")
            return Response.see(
                f"/admin/users?pw_user={urllib.parse.quote(name)}"
                f"&pw={urllib.parse.quote(pw)}",
                message=f"{name} added.")
        if verb in ("disable", "enable"):
            req.auth.set_active(name, verb == "enable", by=req.user["username"])
            with req.db.tx():
                audit.record(actor=req.actor.username,
                             actor_role=req.actor.role,
                             change_type=ChangeType.USER_DISABLED,
                             origin=Origin.UI,
                             before={"is_active": verb == "disable"},
                             after={"is_active": verb == "enable"},
                             note=f"user {name} {verb}d")
            return Response.see("/admin/users", message=f"{name} {verb}d.")
        if verb == "role":
            role = req.f("role", "viewer")
            req.auth.set_role(name, role, by=req.user["username"])
            with req.db.tx():
                audit.record(actor=req.actor.username,
                             actor_role=req.actor.role,
                             change_type=ChangeType.USER_ROLE_CHANGED,
                             origin=Origin.UI, after={"role": role},
                             note=f"user {name} role set to {role}")
            return Response.see("/admin/users",
                                message=f"{name} is now {role}.")
        if verb == "reset":
            pw = req.auth.reset_password(name, by=req.user["username"])
            return Response.see(
                f"/admin/users?pw_user={urllib.parse.quote(name)}"
                f"&pw={urllib.parse.quote(pw)}",
                message=f"New password generated for {name}.")
        if verb == "delete":
            req.auth.delete_user(name, by=req.user["username"])
            return Response.see("/admin/users", message=f"{name} deleted.")
    except Exception as exc:  # auth raises ValueError with a readable reason
        return Response.see("/admin/users", tone="err", message=str(exc))
    return _simple(req, "Not found", f"Users do not accept {verb}.", status=404)


def _admin_sources(req: Request) -> Response:
    require(req.actor, Permission.SOURCE_APPROVE)
    where, args = [], []
    if req.q("q"):
        where.append("(url LIKE ? OR competitor_key LIKE ?)")
        args += [f"%{req.q('q')}%", f"%{req.q('q')}%"]
    st = req.q("status")
    if st == "unapproved":
        where.append("is_approved=0")
    elif st:
        where.append("status=?")
        args.append(st)
    sql = "SELECT * FROM ops_source"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY CASE status WHEN 'unreadable' THEN 0 ELSE 1 END, url"
    rows = req.db.rows(sql, tuple(args))
    all_n = req.db.value("SELECT COUNT(*) FROM ops_source", (), 0) or 0
    counts = {
        "total": all_n, "filtered": len(rows),
        "readable": req.db.value("SELECT COUNT(*) FROM ops_source WHERE status=?",
                                 (SourceStatus.ACTIVE,), 0) or 0,
        "broken": req.db.value(
            "SELECT COUNT(*) FROM ops_source WHERE status IN (?,?)",
            (SourceStatus.UNREADABLE, SourceStatus.UNAVAILABLE), 0) or 0,
        "approved": req.db.value(
            "SELECT COUNT(*) FROM ops_source WHERE is_approved=1", (), 0) or 0,
        "feeds": req.db.value("SELECT COUNT(*) FROM ops_feed", (), 0) or 0,
    }
    feeds = req.db.rows("SELECT * FROM ops_feed ORDER BY is_approved DESC, name")
    body = admin_view.render_sources(sources=rows[:200], feeds=feeds,
                                     counts=counts, query=req.query)
    return _render(req, "Sources & feeds", body)


def _admin_source_approve(req: Request) -> Response:
    require(req.actor, Permission.SOURCE_APPROVE)
    from ..ops.audit import Audit
    from ..ops.schema import ChangeType, Origin, now_iso
    sid = req.f("source_id")
    row = req.db.row("SELECT * FROM ops_source WHERE source_id=?", (sid,))
    if not row:
        return Response.see("/admin/sources", tone="err",
                            message="No such source.")
    with req.db.tx():
        req.db.exec("UPDATE ops_source SET is_approved=1, status_reason=? "
                    "WHERE source_id=?",
                    (f"approved by {req.actor.username} on {now_iso()}", sid))
        Audit(req.db).record(
            actor=req.actor.username, actor_role=req.actor.role,
            change_type=ChangeType.SOURCE_ADDED, origin=Origin.UI,
            before={"is_approved": False}, after={"is_approved": True},
            source_id=sid, competitor_key=row.get("competitor_key") or "",
            note=f"source approved: {row.get('url')}")
    return Response.see("/admin/sources", message="Source approved.")


def _admin_feed_add(req: Request) -> Response:
    require(req.actor, Permission.FEED_REGISTER)
    from ..ops.audit import Audit, new_id
    from ..ops.schema import ChangeType, Origin, now_iso
    name, endpoint = req.f("name"), req.f("endpoint")
    if not (name and endpoint):
        return Response.see("/admin/sources", tone="err",
                            message="A feed needs a name and an endpoint.")
    approve = bool(req.f("approve")) and can(req.actor, Permission.FEED_APPROVE)
    fid = new_id("fd")
    with req.db.tx():
        req.db.exec(
            "INSERT INTO ops_feed (feed_id,competitor_key,name,endpoint,kind,"
            "is_approved,approved_by,approved_at,registered_by,registered_at,"
            "status,note) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (fid, req.f("competitor_key") or None, name, endpoint,
             req.f("kind", "api"), 1 if approve else 0,
             req.actor.username if approve else None,
             now_iso() if approve else None, req.actor.username, now_iso(),
             "registered", None))
        Audit(req.db).record(
            actor=req.actor.username, actor_role=req.actor.role,
            change_type=(ChangeType.FEED_APPROVED if approve
                         else ChangeType.FEED_REGISTERED),
            origin=Origin.UI,
            after={"name": name, "endpoint": endpoint,
                   "is_approved": approve},
            competitor_key=req.f("competitor_key"),
            note=f"feed {name} registered")
    return Response.see("/admin/sources",
                        message=f"{name} registered"
                                + (" and approved." if approve else
                                   ". It is unusable until approved."))


def _admin_feed_approve(req: Request) -> Response:
    require(req.actor, Permission.FEED_APPROVE)
    from ..ops.audit import Audit
    from ..ops.schema import ChangeType, Origin, now_iso
    fid = req.f("feed_id")
    row = req.db.row("SELECT * FROM ops_feed WHERE feed_id=?", (fid,))
    if not row:
        return Response.see("/admin/sources", tone="err",
                            message="No such feed.")
    with req.db.tx():
        req.db.exec("UPDATE ops_feed SET is_approved=1, approved_by=?, "
                    "approved_at=? WHERE feed_id=?",
                    (req.actor.username, now_iso(), fid))
        Audit(req.db).record(
            actor=req.actor.username, actor_role=req.actor.role,
            change_type=ChangeType.FEED_APPROVED, origin=Origin.UI,
            before={"is_approved": False}, after={"is_approved": True},
            competitor_key=row.get("competitor_key") or "",
            note=f"feed {row.get('name')} approved")
    return Response.see("/admin/sources", message="Feed approved.")


def _admin_audit(req: Request) -> Response:
    require(req.actor, Permission.VIEW_AUDIT)
    where, args = [], []
    if req.q("q"):
        like = f"%{req.q('q')}%"
        where.append("(note LIKE ? OR actor LIKE ? OR match_id LIKE ? "
                     "OR action_id LIKE ? OR request_id LIKE ? "
                     "OR clara_product_id LIKE ? OR competitor_key LIKE ?)")
        args += [like] * 7
    for key, col in (("change_type", "change_type"), ("actor", "actor"),
                     ("origin", "origin")):
        if req.q(key):
            where.append(f"{col}=?")
            args.append(req.q(key))
    clause = (" WHERE " + " AND ".join(where)) if where else ""
    total = req.db.value(f"SELECT COUNT(*) FROM ops_audit{clause}",
                         tuple(args), 0) or 0
    offset = (req.page_no - 1) * AUDIT_PAGE
    rows = req.db.rows(
        f"SELECT * FROM ops_audit{clause} ORDER BY at DESC, event_id DESC "
        f"LIMIT {AUDIT_PAGE} OFFSET {offset}", tuple(args))
    change_types = [r["change_type"] for r in req.db.rows(
        "SELECT DISTINCT change_type FROM ops_audit ORDER BY change_type")]
    actors = [r["actor"] for r in req.db.rows(
        "SELECT DISTINCT actor FROM ops_audit ORDER BY actor")]
    body = admin_view.render_audit(rows=rows, total=total, query=req.query,
                                   limit=AUDIT_PAGE, offset=offset,
                                   change_types=change_types, actors=actors)
    return _render(req, "Audit history", body)


def _admin_system(req: Request) -> Response:
    require(req.actor, Permission.USER_MANAGE)
    names = ["ops_product", "ops_competitor", "ops_competitor_product",
             "ops_match", "ops_match_version", "ops_observation", "ops_source",
             "ops_feed", "ops_action", "ops_action_activity", "ops_request",
             "ops_request_message", "ops_request_status", "ops_conversation",
             "ops_message", "ops_citation", "ops_audit", "ops_job",
             "ops_user", "ops_import"]
    tables = {}
    for n in names:
        if req.db.table_exists(n):
            tables[n] = req.db.value(f"SELECT COUNT(*) FROM {n}", (), 0) or 0
    body = admin_view.render_system(
        engine=engine_status(),
        schema={"version": schema_version(req.db), "target": SCHEMA_VERSION,
                "applied": ""},
        imports=req.db.rows("SELECT * FROM ops_import ORDER BY at DESC LIMIT 20"),
        retention=req.db.rows("SELECT * FROM ops_retention ORDER BY scope"),
        jobs=req.db.rows("SELECT * FROM ops_job ORDER BY requested_at DESC "
                         "LIMIT 20"),
        tables=tables)
    return _render(req, "System", body)
