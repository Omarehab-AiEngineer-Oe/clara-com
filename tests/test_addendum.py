"""Section 12's acceptance criteria, one test each, against a real database.

The addendum ends with eleven criteria and an approval gate. This file is the
criteria, in their order, phrased as the addendum phrases them — so a failure here
names the requirement it breaks rather than the function that raised.

It runs against a temporary SQLite database seeded from the collection store, so
it exercises the real importer, the real resolution handlers, the real
transaction boundary and the real router. Nothing is mocked: a test that passes
against a stub would tell us the stub is correct.

    python tests/test_addendum.py
"""
from __future__ import annotations

import io
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8",
                              errors="replace")

from clara_monitor import app as opsapp, ops, reporting          # noqa: E402
from clara_monitor.config import DB_PATH                          # noqa: E402
from clara_monitor.ops.actions import Actions, RESOLUTION_OPTIONS  # noqa: E402
from clara_monitor.ops.agent import IntelligenceAgent             # noqa: E402
from clara_monitor.ops.authz import Actor, Denied                 # noqa: E402
from clara_monitor.ops.ingest import Importer                     # noqa: E402
from clara_monitor.ops.requests import Requests                   # noqa: E402
from clara_monitor.ops.schema import (ActionStatus, ActionType,    # noqa: E402
                                      MatchStatus, Provenance,
                                      RequestStatus)
from clara_monitor.store import Store                             # noqa: E402

PASS, FAIL = [], []


def ok(cond, label):
    (PASS if cond else FAIL).append(label)
    print(f"  {'PASS' if cond else 'FAIL'}  {label}")


def section(n, title):
    print(f"\n{n}. {title}")


# --------------------------------------------------------------------------
# a real database, seeded from the real collection store
# --------------------------------------------------------------------------

TMP = Path(tempfile.mkdtemp(prefix="clara-addendum-"))
DB_FILE = TMP / "ops.sqlite3"

ADMIN = Actor(username="an_admin", role="admin", origin="ui")
USER = Actor(username="a_user", role="viewer", origin="ui")
ADMIN_U = {"username": "an_admin", "display_name": "An Admin",
           "is_admin": True, "role": "admin"}
USER_U = {"username": "a_user", "display_name": "A User",
          "is_admin": False, "role": "viewer"}


def seed():
    store = Store(DB_PATH)
    try:
        run = store.latest_run_id() or "r1"
        bundle = reporting.build_all(store, run, write=False)
        bundle["competitors"] = reporting.competitor_cards(store, run)
    finally:
        store.close()
    db = ops.connect(DB_FILE)
    out = Importer(db).import_bundle(bundle, run_id=run)
    return db, out


db, imported = seed()
print(f"seeded from run {imported.get('import_id')}: "
      f"{imported.get('products')} products, {imported.get('matches_new')} "
      f"matches, {imported.get('observations')} observations, "
      f"{imported.get('actions')} actions")


def get(path, user=ADMIN_U, **query):
    return opsapp.handle(opsapp.Request(method="GET", path=path, query=query,
                                        user=user, db=db))


def post(path, user=ADMIN_U, **form):
    return opsapp.handle(opsapp.Request(method="POST", path=path, form=form,
                                        user=user, db=db))


_MATCHES = db.rows("SELECT * FROM ops_match WHERE competitor_url IS NOT NULL "
                   "AND competitor_url <> '' ORDER BY match_id")
_next = [0]


def an_action(action_type, **over):
    """Open one action of a given type, on a match of its own.

    A fresh match per action on purpose: actions are deduplicated on what they
    are about, so reusing one match would refresh the previous action instead of
    opening a new one, and each criterion needs its own to resolve.
    """
    m = _MATCHES[_next[0] % len(_MATCHES)]
    _next[0] += 1
    src = db.row("SELECT * FROM ops_source WHERE competitor_key=? LIMIT 1",
                 (m["competitor_key"],))
    fields = dict(
        action_type=action_type, reason=f"a {action_type} raised by the tests",
        priority="high", clara_product_id=m["clara_product_id"],
        clara_product_name=m.get("clara_product_name") or "",
        competitor_key=m["competitor_key"], match_id=m["match_id"],
        source_id=(src or {}).get("source_id") or "",
        actor=Actor.system("import"),
        candidates=[{"name": m.get("competitor_product_name") or "their product",
                     "url": m["competitor_url"], "why": "the observed page"}],
        evidence=[{"url": m["competitor_url"], "note": "the URL involved"}])
    fields.update(over)
    return Actions(db).open(**fields), m


# --------------------------------------------------------------------------

section(1, "A user can resolve each supported ambiguous-match Action "
           "without leaving the application")

amb_options = RESOLUTION_OPTIONS[ActionType.AMBIGUOUS_MATCH]
ok(set(amb_options) == {"select_candidate", "enter_url", "confirm_counterpart",
                        "no_counterpart", "note_only"},
   f"4.2's five outcomes are the options offered: {', '.join(amb_options)}")

for option in amb_options:
    aid, m = an_action(ActionType.AMBIGUOUS_MATCH)
    page = get(f"/actions/{aid}", USER_U)
    rendered = f'id="opt-{option}"' in page.body
    fields = {"select_candidate": {"candidate_index": "0"},
              "enter_url": {"competitor_url": "https://rival.example/p/1",
                            "competitor_product_name": "Their model"},
              }.get(option, {})
    r = post(f"/actions/{aid}/resolve", USER_U, option=option,
             note="resolved by the acceptance test", **fields)
    row = db.row("SELECT status, resolved_by FROM ops_action WHERE action_id=?",
                 (aid,))
    closed = row["status"] in (ActionStatus.RESOLVED, ActionStatus.WAITING)
    ok(rendered and r.status == 303 and closed,
       f"a non-admin user resolved it with '{option}' in-app "
       f"(form shown: {rendered}, status: {row['status']})")

section(2, "A user can resolve or progress each unreadable-source Action using "
           "an alternative source, new URL, verification request, manual "
           "observation, or approved feed/API")

unread_options = RESOLUTION_OPTIONS[ActionType.UNREADABLE_SOURCE]
for option in ("enter_source_url", "request_verification",
               "manual_observation", "mark_source_unavailable",
               "register_feed"):
    ok(option in unread_options, f"4.3 offers '{option}'")

# Each of the five, on its own action.
cases = [
    ("enter_source_url", {"source_url": "https://rival.example/alt"}, ADMIN_U),
    ("request_verification", {"source_url": "https://rival.example/alt"},
     ADMIN_U),
    ("manual_observation", {"price": "1299", "currency": "SAR",
                            "availability": "in_stock",
                            "offer_wording": "15% off with code SPRING",
                            "observed_at": "2026-08-18",
                            "last_checked_at": "2026-08-20",
                            "source_url": "https://rival.example/p"}, ADMIN_U),
    ("register_feed", {"feed_name": "Rival price API",
                       "feed_endpoint": "https://api.rival.example/prices",
                       "feed_kind": "api", "approve": "1"}, ADMIN_U),
    ("mark_source_unavailable", {"reason": "their edge returns 403 to everyone"},
     ADMIN_U),
]
for option, fields, who in cases:
    aid, _m = an_action(ActionType.UNREADABLE_SOURCE,
                        failure_reason="HTTP 403 from their edge")
    page = get(f"/actions/{aid}", who)
    rendered = f'id="opt-{option}"' in page.body
    r = post(f"/actions/{aid}/resolve", who, option=option,
             note="progressed by the acceptance test", **fields)
    row = db.row("SELECT status FROM ops_action WHERE action_id=?", (aid,))
    ok(rendered and r.status == 303
       and row["status"] in (ActionStatus.RESOLVED, ActionStatus.WAITING),
       f"'{option}' resolved or progressed it in-app -> {row['status']}")
    if option == "request_verification":
        ok(row["status"] == ActionStatus.WAITING,
           "requesting verification moves it to Waiting, not Resolved — "
           "nothing has been proven yet")
    if option == "manual_observation":
        o = db.row("SELECT * FROM ops_observation WHERE provenance=? "
                   "ORDER BY created_at DESC", (Provenance.MANUAL,))
        ok(o["provenance"] == Provenance.MANUAL and o["actor"] == "an_admin"
           and o["observed_at"].startswith("2026-08-18")
           and o["last_checked_at"].startswith("2026-08-20")
           and o["offer_wording"] and o["availability"] and o["currency"],
           "4.3's six fields are all recorded, with observed and last-checked "
           "kept separate")

section(3, "Every saved resolution produces one consistent domain update, "
           "Action transition, and audit event")

aid, m = an_action(ActionType.AMBIGUOUS_MATCH)
before_audit = db.value("SELECT COUNT(*) FROM ops_audit")
before_ver = db.value("SELECT COUNT(*) FROM ops_match_version WHERE match_id=?",
                      (m["match_id"],))
post(f"/actions/{aid}/resolve", ADMIN_U, option="confirm_counterpart",
     note="confirmed by the acceptance test")
after = db.row("SELECT status, provenance, confirmed_by, version FROM ops_match "
               "WHERE match_id=?", (m["match_id"],))
ok(after["status"] == MatchStatus.CONFIRMED
   and after["provenance"] == Provenance.HUMAN_CONFIRMED
   and after["confirmed_by"] == "an_admin",
   "the domain record was updated, and carries the actor who did it")
ok(db.value("SELECT status FROM ops_action WHERE action_id=?", (aid,))
   == ActionStatus.RESOLVED, "the action transitioned")
ok(db.value("SELECT COUNT(*) FROM ops_audit") > before_audit,
   "an audit event was appended")
ok(db.value("SELECT COUNT(*) FROM ops_match_version WHERE match_id=?",
            (m["match_id"],)) > before_ver,
   "a new version was appended rather than the old one overwritten")

# The atomic-save rule: a failing resolution must leave nothing behind.
aid2, m2 = an_action(ActionType.AMBIGUOUS_MATCH)
snap = (db.value("SELECT COUNT(*) FROM ops_audit"),
        db.value("SELECT COUNT(*) FROM ops_observation"),
        db.value("SELECT status FROM ops_match WHERE match_id=?",
                 (m2["match_id"],)))
r = post(f"/actions/{aid2}/resolve", ADMIN_U, option="enter_url",
         competitor_url="", note="this should fail")
now = (db.value("SELECT COUNT(*) FROM ops_audit"),
       db.value("SELECT COUNT(*) FROM ops_observation"),
       db.value("SELECT status FROM ops_match WHERE match_id=?",
                (m2["match_id"],)))
ok(snap == now
   and db.value("SELECT status FROM ops_action WHERE action_id=?", (aid2,))
   == ActionStatus.OPEN,
   "a rejected resolution wrote nothing at all — no partial save")

section(4, "Send Request opened from a supported record contains the correct "
           "record context without re-entry")

pid = db.value("SELECT clara_product_id FROM ops_product WHERE name IS NOT NULL "
               "LIMIT 1")
pname = db.value("SELECT name FROM ops_product WHERE clara_product_id=?", (pid,))
page = get("/requests/new", ADMIN_U, kind="product", id=pid)
import html as _html
ok(_html.escape(pname)[:24] in page.body
   and "Context attached to this request" in page.body,
   "the form is prefilled with the product it was opened from")

ck = db.value("SELECT competitor_key FROM ops_competitor LIMIT 1")
for kind, rid in (("product", pid), ("competitor", ck),
                  ("match", db.value("SELECT match_id FROM ops_match LIMIT 1")),
                  ("source", db.value("SELECT source_id FROM ops_source LIMIT 1")),
                  ("observation",
                   db.value("SELECT obs_id FROM ops_observation LIMIT 1"))):
    ctx = Requests(db).context_for(kind, rid)
    ok(ctx.get("ok") and ctx.get("subject") and ctx.get("summary"),
       f"a request opened from a {kind} carries a readable subject and summary")

r = post("/requests/new", USER_U, kind="product", id=pid,
         request_type="investigate_missing_competitor_data",
         subject="No competitor assigned",
         description="Please assign a competitor to this product.",
         priority="high")
rid = r.location.split("/requests/")[1].split("?")[0]
saved = db.row("SELECT * FROM ops_request WHERE request_id=?", (rid,))
ok(pid in (saved.get("context") or ""),
   "the created request stores the record it was raised from")

section(5, "Users can view their Requests and admins can manage all five "
           "statuses and responses")

mine = get("/requests", USER_U)
ok("My Requests" in mine.body and "No competitor assigned" in mine.body,
   "a user sees their own requests")
others = Requests(db).list(actor=USER, mine=False)
ok(all(row["requester"] == "a_user" for row in others["rows"]),
   "a non-admin is scoped to their own rows in the query, not by hiding them")
ok("Request administration" in get("/admin/requests", ADMIN_U).body,
   "an admin gets the whole queue")

walk = [(RequestStatus.IN_PROGRESS, ADMIN_U), (RequestStatus.WAITING, ADMIN_U)]
for to, who in walk:
    post(f"/requests/{rid}/status", who, to_status=to, note="triage")
    ok(db.value("SELECT status FROM ops_request WHERE request_id=?", (rid,)) == to,
       f"an admin moved it to {to}")
post(f"/requests/{rid}/reply", USER_U, body="Here is the detail you asked for.")
ok(db.value("SELECT status FROM ops_request WHERE request_id=?", (rid,))
   == RequestStatus.IN_PROGRESS,
   "a requester reply on a Waiting request returns it to In progress — 5.3's "
   "one requester transition")
for to in (RequestStatus.RESOLVED, RequestStatus.CLOSED):
    post(f"/requests/{rid}/status", ADMIN_U, to_status=to,
         resolution="A competitor was assigned.", closure_reason="done")
    ok(db.value("SELECT status FROM ops_request WHERE request_id=?", (rid,)) == to,
       f"an admin moved it to {to}")
ok(db.value("SELECT COUNT(*) FROM ops_request_status WHERE request_id=?",
            (rid,)) >= 5,
   "every transition is recorded in the status history")

# A transition the table forbids must be refused.
try:
    Requests(db).transition(rid, RequestStatus.WAITING, ADMIN)
    refused = False
except ValueError:
    refused = True
ok(refused, "a transition 5.3 does not permit is refused, not merely unbuttoned")

section(6, "An Agent conversation can be escalated into a Request with its "
           "summary, citations, and missing-evidence explanation")

agent = IntelligenceAgent(db)
cid = agent.start(USER, context_kind="product", context_id=pid)
answer = agent.ask(cid, "Where is competitor data missing?", USER)
ok(bool(answer["gaps"]) or bool(answer["citations"]),
   "the agent answered from records, reporting gaps or citations")
new_rid = agent.escalate(cid, USER,
                         request_type="investigate_missing_competitor_data")
esc = db.row("SELECT * FROM ops_request WHERE request_id=?", (new_rid,))
desc = esc.get("description") or ""
for part in ("WHAT IS MISSING", "RECORDS THE AGENT CITED", "CONVERSATION"):
    ok(part in desc, f"the request carries the {part.lower()} section")
ok(esc.get("conversation_id") == cid,
   "the request links back to the conversation it came from")
ok(db.value("SELECT COUNT(*) FROM ops_audit WHERE change_type=?",
            ("conversation_escalated",)) >= 1,
   "the escalation is itself an audit event")

section(7, "Agent answers contain no marketing, campaign, advertising, SEO, "
           "social-media, copywriting, or customer-acquisition behaviour")

from clara_monitor.ops.agent import (EXCLUSION_ENFORCED_AS,  # noqa: E402
                                     EXCLUSIONS, scope_check)

# 6.2 lists six exclusions. Each must be enforced, and each must be reachable —
# an exclusion listed on screen that nothing actually refuses is a promise.
PROBES = {
    "Marketing campaigns": [
        "plan a campaign around the airwrap",
        "draft a marketing campaign for the new styler",
        "build a promotion for the dryer",
        "how should we market against dyson",
        "suggest positioning for clara",
    ],
    "Advertising": [
        "what should our ad spend be against shark",
        "plan a media buy for next quarter",
        "increase the google ads budget",
    ],
    "SEO": [
        "how do we rank higher than dyson on google",
        "do keyword research for hair dryers",
        "build backlinks for the product pages",
    ],
    "Social media": [
        "suggest hashtags for our tiktok",
        "plan an influencer push",
        "write a social calendar for next month",
    ],
    "Copywriting or content generation": [
        "draft a product description for the styler",
        "compose a newsletter about our prices",
        "rewrite this headline",
    ],
    "Customer acquisition": [
        "give me a customer acquisition funnel",
        "design a loyalty programme",
        "improve our conversion rate optimisation",
    ],
}

reached = set()
for exclusion, questions in PROBES.items():
    refused_all = True
    for q in questions:
        out = agent.ask(cid, q, USER)
        body = out["text"].lower()
        # Refused, and no trace of the thing having been produced anyway.
        clean = bool(out["declined"]) and not any(
            w in body for w in ("here is a caption", "here's a caption",
                                "step 1", "hashtag:", "subject line",
                                "headline:", "cta"))
        if not clean:
            refused_all = False
            print(f"       not refused: {q!r} -> {out['declined'] or 'NONE'}")
        else:
            reached.add(out["declined"])
    ok(refused_all, f"every phrasing of “{exclusion}” is refused "
                    f"({len(questions)} probes)")

ok(set(EXCLUSION_ENFORCED_AS.values()) <= reached,
   "all six of 6.2's exclusions are reachable by the enforcement, none is "
   f"decorative (unreached: "
   f"{sorted(set(EXCLUSION_ENFORCED_AS.values()) - reached) or 'none'})")

# The scope check runs on the ANSWER as well as the question (6.2, and 12's
# criterion). Proven by feeding an out-of-scope string through the outbound
# check directly, which is the path a drifting model would take.
ok(not scope_check("Here is a campaign plan you could run")["ok"],
   "the outbound check would withhold a reply that drifted into a campaign")

# In-scope questions must still be answerable. An exclusion that swallows
# legitimate evidence questions has broken the tab it lives in.
IN_SCOPE_ASKS = [
    "what does their promotion say",
    "which competitor discounts most often",
    "why is this price stale",
    "what offers is shark running",
    "how fresh is the price evidence",
    "which sources could not be read",
    "what is the price difference against dyson",
    "who confirmed this match",
    "show me the offer wording observed at amika",
]
blocked = [q for q in IN_SCOPE_ASKS if not scope_check(q)["ok"]]
ok(not blocked,
   f"in-scope evidence questions are not caught by the exclusions "
   f"({len(IN_SCOPE_ASKS)} probes, blocked: {blocked or 'none'})")

section(8, "Every manually changed intelligence value shows actor, time, "
           "before, after, note, and provenance")

# Correct a value that already had one, so there is a before as well as an
# after. The first observation of anything has no predecessor, and requiring one
# would be testing the wrong thing.
aid, m_over = an_action(
    ActionType.STALE_PRICE,
    match_id=db.value("SELECT m.match_id FROM ops_match m "
                      "JOIN ops_observation o ON o.match_id=m.match_id "
                      "WHERE o.superseded_by IS NULL LIMIT 1"))
post(f"/actions/{aid}/resolve", ADMIN_U, option="manual_observation",
     price="999", currency="SAR", availability="in_stock",
     observed_at="2026-08-19", last_checked_at="2026-08-20",
     note="corrected by hand from their page")
man = db.row("SELECT * FROM ops_observation WHERE provenance=? "
             "ORDER BY created_at DESC, obs_id DESC", (Provenance.MANUAL,))
ok(bool(man) and man["actor"] and man["observed_at"] and man["note"],
   "the manual observation carries its actor, observation date and note")
ev = db.row("SELECT * FROM ops_audit WHERE change_type=? "
            "ORDER BY at DESC", ("manual_observation_entered",))
ok(bool(ev) and ev["actor"] and ev["at"] and ev["after_value"]
   and ev["note"] is not None,
   "the audit event carries 8.1's actor, time, after value and note")
ok(ev["before_value"] is not None,
   "and the before value it replaced, so the change is legible")
man_pid = db.value("SELECT clara_product_id FROM ops_match WHERE match_id=?",
                   (man["match_id"],))
page = get(f"/products/{man_pid}", ADMIN_U)
ok("Manually entered" in page.body or "Manual" in page.body,
   "a manually entered value is labelled as such on its product page")
ok("pv-manually_entered" in page.body,
   "and the label carries 8.2's definition, from one shared source")

section(9, "Operational records remain unchanged and available after an "
           "application restart and a deployment")

counts_before = {t: db.value(f"SELECT COUNT(*) FROM {t}")
                 for t in ("ops_action", "ops_request", "ops_audit",
                           "ops_observation", "ops_match", "ops_conversation")}
resolved_before = db.value(
    "SELECT COUNT(*) FROM ops_match WHERE provenance=?",
    (Provenance.HUMAN_CONFIRMED,))
db.close()
# A restart: a brand-new connection to the same durable store.
db = ops.connect(DB_FILE)
counts_after = {t: db.value(f"SELECT COUNT(*) FROM {t}")
                for t in counts_before}
ok(counts_before == counts_after,
   f"every operational record survived the restart ({sum(counts_after.values())} "
   f"rows)")

# A deployment: the collection run is imported again over the top.
store = Store(DB_PATH)
try:
    run = store.latest_run_id() or "r1"
    bundle = reporting.build_all(store, run, write=False)
    bundle["competitors"] = reporting.competitor_cards(store, run)
finally:
    store.close()
again = Importer(db).import_bundle(bundle, run_id=run + "-redeploy")
ok(db.value("SELECT COUNT(*) FROM ops_match WHERE provenance=?",
            (Provenance.HUMAN_CONFIRMED,)) >= resolved_before,
   f"a re-import did not overwrite the {resolved_before} human-confirmed "
   f"match(es) — {again.get('matches_held')} were held")
ok(db.value("SELECT COUNT(*) FROM ops_request") == counts_before["ops_request"],
   "and it did not touch the requests")
ok(db.value("SELECT COUNT(*) FROM ops_audit") > counts_before["ops_audit"],
   "the import is itself audited rather than silent")

section(10, "Summary counts reconcile with their detailed records and clearly "
            "distinguish unique offers from product-level associations")

from clara_monitor.app import read                                # noqa: E402

offers = read.offers(db)
assoc = db.value(
    "SELECT COUNT(*) FROM ops_observation WHERE superseded_by IS NULL "
    "AND offer_wording IS NOT NULL AND offer_wording <> ''")
ok(offers["associations"] == assoc,
   f"the association count matches the rows behind it ({assoc})")
ok(offers["unique"] <= offers["associations"],
   f"unique offers ({offers['unique']}) are distinguished from associations "
   f"({offers['associations']})")
ok("unique offers" in offers["definition"]
   and "association" in offers["definition"],
   "the definition on the page says which is which")

plist = read.product_list(db, limit=10_000)
ok(plist["counts"]["total"]
   == db.value("SELECT COUNT(*) FROM ops_product")
   + db.value("SELECT COUNT(*) FROM (SELECT DISTINCT clara_product_id "
              "FROM ops_match WHERE clara_product_id NOT IN "
              "(SELECT clara_product_id FROM ops_product)) x"),
   f"the product total reconciles with the catalogue ({plist['counts']['total']})")
ok(plist["counts"]["attention"] + plist["counts"]["clear"]
   == plist["counts"]["total"],
   "needs-attention and clear partition the catalogue exactly")

acount = Actions(db).counts()
ok(acount["open"] == db.value(
    "SELECT COUNT(*) FROM ops_action WHERE status IN (?,?,?)",
    (ActionStatus.OPEN, ActionStatus.IN_PROGRESS, ActionStatus.WAITING)),
   f"the open-actions figure matches the queue ({acount['open']})")
ok(bool(acount["open_definition"]),
   "and it states what it counts")

filtered = read.product_list(db, attention="any", limit=10_000)
ok(filtered["total"] == plist["counts"]["attention"],
   "the attention figure and the filtered list it links to agree "
   f"({filtered['total']})")

section(11, "Unauthorized users cannot perform administrative source, user, "
            "Request or audit operations through either UI or direct requests")

ok('href="/admin/users"' not in get("/overview", USER_U).body.split(
    "</header>")[0],
   "a non-admin is not shown the Admin menu")
for path, form in (("/admin/sources/approve", {"source_id": "anything"}),
                   ("/admin/feeds/approve", {"feed_id": "anything"}),
                   ("/admin/users/add", {"username": "x", "role": "admin"})):
    r = post(path, USER_U, **form)
    ok(r.status == 403, f"a direct POST to {path} is refused -> {r.status}")
for path in ("/admin/audit", "/admin/users", "/admin/sources", "/admin/system"):
    r = get(path, USER_U)
    ok(r.status == 403, f"a direct GET of {path} is refused -> {r.status}")

# An admin-only resolution option, attempted by a user through a hand-made POST.
aid, _m = an_action(ActionType.UNREADABLE_SOURCE)
r = post(f"/actions/{aid}/resolve", USER_U, option="mark_source_unavailable",
         reason="trying it on")
ok(r.status == 403,
   f"an admin-only resolution option is refused to a user -> {r.status}")
ok(db.value("SELECT status FROM ops_action WHERE action_id=?", (aid,))
   == ActionStatus.OPEN, "and the action was not touched")
page = get(f"/actions/{aid}", USER_U)
ok("admin operation" in page.body,
   "the page shows the option, disabled, naming the role it needs")

# A request belonging to someone else: refused with a reason, not returned.
try:
    Requests(db).get(new_rid, Actor(username="a_stranger", role="viewer"))
    leaked = True
except Denied:
    leaked = False
ok(not leaked, "a user cannot read another user's request")

# The audit table has no update or delete path anywhere in ops (8.2: audit
# events are append-only and cannot be edited through ordinary workflows).
#
# Checked against the parsed source rather than the raw text, so the prose in
# `audit.py` explaining that no such statement exists does not read as one.
import ast                                                        # noqa: E402

ops_dir = ROOT / "clara_monitor" / "ops"
bad = []
for f in sorted(ops_dir.glob("*.py")):
    tree = ast.parse(f.read_text(encoding="utf-8"))
    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                             ast.AsyncFunctionDef)):
            body = getattr(node, "body", None) or []
            if (body and isinstance(body[0], ast.Expr)
                    and isinstance(body[0].value, ast.Constant)
                    and isinstance(body[0].value.value, str)):
                docstrings.add(id(body[0].value))
    for node in ast.walk(tree):
        if (isinstance(node, ast.Constant) and isinstance(node.value, str)
                and id(node) not in docstrings):
            low = " ".join(node.value.lower().split())
            for stmt in ("update ops_audit", "delete from ops_audit"):
                if stmt in low:
                    bad.append(f"{f.name}:{node.lineno} {stmt}")
ok(not bad,
   f"no statement in ops/ can edit or delete an audit event{' ' + str(bad) if bad else ''}")

section(12, "Requirements with no §12 criterion of their own")

# These are addendum requirements that section 12 does not turn into a
# criterion, so nothing else here would notice if they regressed. Each one was
# genuinely missing on a first pass, which is why they are pinned.

# --- 4.1: priority and optional due date are FIELDS, not columns ---
aid, _m = an_action(ActionType.MISSING_DATA)
r = post(f"/actions/{aid}/schedule", ADMIN_U, priority="low",
         due_date="2026-09-15")
row = db.row("SELECT priority, due_date FROM ops_action WHERE action_id=?",
             (aid,))
ok(r.status == 303 and row["priority"] == "low"
   and (row["due_date"] or "").startswith("2026-09-15"),
   "4.1's priority and optional due date can be set, not merely displayed")
# Selected by change type, not by "most recent": `at` has second precision, so
# the action's creation and its scheduling can tie and either may sort first.
ev = db.row("SELECT before_value, after_value FROM ops_audit "
            "WHERE action_id=? AND change_type=? ORDER BY event_id DESC",
            (aid, "action_assigned"))
ok(ev and "due_date" in (ev.get("after_value") or "")
   and "due_date" in (ev.get("before_value") or ""),
   "and the change is audited with its before and after")
ok(f'action="/actions/{aid}/schedule"' in get(f"/actions/{aid}", ADMIN_U).body,
   "the control is on the action's page")
r = post(f"/actions/{aid}/schedule", USER_U, priority="high")
ok(r.status == 403, f"scheduling someone's work is an admin operation -> {r.status}")

# --- 5.2: a Request may link to an offer ---
obs = db.value("SELECT obs_id FROM ops_observation WHERE offer_wording "
               "IS NOT NULL AND offer_wording <> '' LIMIT 1")
if obs:
    ctx = Requests(db).context_for("offer", obs)
    ok(ctx.get("ok") and ctx.get("subject") and ctx.get("summary"),
       "5.2's 'offer' is a record a request can attach to, with a readable "
       "subject")
    ok(ctx.get("competitor_key") and ctx.get("obs_id") == obs,
       "and it carries the competitor and the observation behind the offer")
    page = get("/requests/new", ADMIN_U, kind="offer", id=obs)
    ok("Context attached to this request" in page.body,
       "opening Send Request from an offer prefills it")
    for path in ("/offers", "/overview"):
        ok("kind=offer" in get(path, ADMIN_U).body,
           f"{path} offers Send Request on an offer")
else:
    ok(False, "no offer in the seeded data to test 5.2's offer context")

# --- 10: sorting, on every list, and URL-persisted ---
from clara_monitor.app.read import COMPETITOR_SORTS                # noqa: E402

for path, sorts in (
        ("/products", ["attention", "name", "coverage", "freshness",
                       "price_desc", "price_asc"]),
        ("/competitors", list(COMPETITOR_SORTS)),
        ("/actions", list(Actions.SORTS)),
        ("/requests", list(Requests.SORTS))):
    statuses = {get(path, ADMIN_U, sort=s).status for s in sorts}
    ok(statuses == {200},
       f"{path} sorts by {len(sorts)} orderings, all rendering ({statuses})")
    ok('name="sort"' in get(path, ADMIN_U).body,
       f"{path} offers the sort control section 10 asks for")

# A sort the query does not know must not 500, and must not be silently
# reflected back into the SQL.
ok(get("/actions", ADMIN_U, sort="'; DROP TABLE ops_action--").status == 200
   and db.table_exists("ops_action"),
   "an unknown sort falls back rather than reaching the query")

# --- 3: the Products tab shows availability ---
body = get("/products", ADMIN_U).body
ok("<th>Availability</th>" in body,
   "section 3 lists availability among the Products tab's contents")
ok("not recorded" in body or "in stock" in body,
   "and it distinguishes 'nothing recorded' from 'nothing in stock'")

# --- 3: every tab is searchable and filterable ---
for path in ("/products", "/competitors", "/actions", "/requests"):
    b = get(path, ADMIN_U).body
    ok('role="search"' in b and 'type="search"' in b,
       f"{path} is searchable and filterable")

# --- 10: filter state is in the URL, so a filtered list is a link ---
r = get("/products", ADMIN_U, attention="unassigned")
ok(r.status == 200 and "Filtered by" in r.body,
   "an applied filter is shown and removable, and lives in the URL")

# --- 6.2: the exclusions are visible, not only enforced ---
# A refusal a reader could not anticipate reads as a malfunction, so the six are
# stated where they can be found without asking the agent something it declines.
ov = get("/overview", ADMIN_U).body
ok("What the Intelligence Agent covers" in ov,
   "the website states the agent's scope outside the panel")
ok(all(x in ov for x in EXCLUSIONS),
   "and lists all six of 6.2's exclusions on the page")

panel_body = get("/overview", ADMIN_U, agent="1").body
ok("Scope: what this agent will not do" in panel_body,
   "the panel carries the exclusions at all times, not only before you ask")
ok(all(x in panel_body for x in EXCLUSIONS),
   "and all six are in the panel")

# With a conversation in progress the exclusions must still be on screen — this
# is the case that regressed: they used to live only on the empty state.
live = get("/overview", ADMIN_U, agent="1", c=cid).body
ok("Scope: what this agent will not do" in live
   and all(x in live for x in EXCLUSIONS),
   "the exclusions stay visible once a conversation has started")

# --- 1 and 6.2: every agent prompt carries them ---
prompt_files = sorted((ROOT / "prompts").glob("*.md")) + \
    sorted((ROOT / "prompts" / "agents").glob("*.md"))
missing = []
for f in prompt_files:
    text = f.read_text(encoding="utf-8")
    absent = [x for x in EXCLUSIONS if x.lower() not in text.lower()]
    if absent:
        missing.append(f"{f.name}: {absent}")
ok(not missing,
   f"all {len(prompt_files)} agent prompts carry 6.2's exclusions"
   + (f" — missing: {missing}" if missing else ""))


# --------------------------------------------------------------------------

db.close()
shutil.rmtree(TMP, ignore_errors=True)

print("\n" + "=" * 70)
print(f"{len(PASS)}/{len(PASS) + len(FAIL)} checks pass")
for f in FAIL:
    print(f"  FAILED: {f}")
sys.exit(1 if FAIL else 0)
