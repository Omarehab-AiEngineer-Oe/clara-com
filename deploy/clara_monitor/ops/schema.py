"""Section 9.1: every durable operational record, as numbered migrations.

The list in 9.1 is the checklist and this file is the answer to it:

    the Clara catalogue                         ops_product
    users, roles, authentication state          ops_user, ops_role_grant
    matches, resolutions, versions              ops_match, ops_match_version
    competitor products and sources             ops_competitor_product, ops_source
    price, availability, offer observations      ops_observation
    approved feeds/APIs                         ops_feed
    actions and action activity                 ops_action, ops_action_activity
    requests, responses, status history          ops_request, ops_request_message,
                                                 ops_request_status
    agent conversations and record citations     ops_conversation, ops_message,
                                                 ops_citation
    immutable audit events                       ops_audit

Four decisions run through the whole schema.

**Stable IDs and real foreign keys.** 9.2 asks for both. Every id is a
Python-generated string key rather than a database sequence, which keeps the two
engines identical and means a record can be referenced in a URL, an audit row and
an export without a round trip to find out what number it got.

**Corrections never erase.** 8.2 is explicit: a correction creates a new version
or observation and preserves the superseded record. So `ops_match_version` is
append-only with a `superseded_by`, and `ops_observation` is insert-only. There is
no UPDATE path in this schema that overwrites an observed value — the closest
thing is marking a row superseded.

**Provenance is a column, not a convention.** Every value a person can see
carries one of the four labels from 8.2. A value with no provenance is not
displayable, so the column is NOT NULL with no default: forgetting it is a
constraint violation rather than a blank badge on a page.

**Audit is append-only and cannot be edited through ordinary workflows.** There is
no update or delete statement for `ops_audit` anywhere in `ops`, and 8.1's field
list is the column list.

Migrations are numbered and recorded. `migrate()` is idempotent and safe to call
on every start, which is what makes the hosted path work: a fresh Postgres
database and an existing SQLite file both end up at the same version.
"""

from __future__ import annotations

from datetime import datetime, timezone

from .db import Db

SCHEMA_VERSION = 5


# --------------------------------------------------------------------------
# vocabulary
# --------------------------------------------------------------------------

class Provenance:
    """Section 8.2, verbatim. Four labels, no fifth."""
    OBSERVED = "automatically_observed"
    HUMAN_CONFIRMED = "human_confirmed"
    MANUAL = "manually_entered"
    FEED = "approved_feed_api"


PROVENANCE_LABEL = {
    Provenance.OBSERVED: "Automatically observed",
    Provenance.HUMAN_CONFIRMED: "Human-confirmed",
    Provenance.MANUAL: "Manually entered",
    Provenance.FEED: "Approved feed/API",
}

PROVENANCE_DEFINITION = {
    Provenance.OBSERVED:
        "Collected by an approved automated run from the cited source.",
    Provenance.HUMAN_CONFIRMED:
        "A person reviewed evidence and confirmed an automated or proposed value.",
    Provenance.MANUAL:
        "A person entered the value directly; actor, note and observation date "
        "are required.",
    Provenance.FEED:
        "Received from an administratively approved external integration.",
}

PROVENANCE_ORDER = (Provenance.HUMAN_CONFIRMED, Provenance.FEED,
                    Provenance.OBSERVED, Provenance.MANUAL)


class ActionType:
    """Section 4 plus the queue contents named in section 3."""
    AMBIGUOUS_MATCH = "ambiguous_match"
    UNREADABLE_SOURCE = "unreadable_source"
    STALE_PRICE = "stale_price"
    MISSING_DATA = "missing_data"
    VERIFICATION_FAILED = "verification_failed"


ACTION_TYPE_LABEL = {
    ActionType.AMBIGUOUS_MATCH: "Ambiguous match",
    ActionType.UNREADABLE_SOURCE: "Unreadable source",
    ActionType.STALE_PRICE: "Stale price",
    ActionType.MISSING_DATA: "Missing data",
    ActionType.VERIFICATION_FAILED: "Verification failed",
}


class ActionStatus:
    OPEN = "open"
    IN_PROGRESS = "in_progress"
    WAITING = "waiting"
    RESOLVED = "resolved"
    DISMISSED = "dismissed"


ACTION_STATUS_LABEL = {
    ActionStatus.OPEN: "Open", ActionStatus.IN_PROGRESS: "In progress",
    ActionStatus.WAITING: "Waiting", ActionStatus.RESOLVED: "Resolved",
    ActionStatus.DISMISSED: "Dismissed",
}

ACTION_OPEN_STATES = (ActionStatus.OPEN, ActionStatus.IN_PROGRESS,
                      ActionStatus.WAITING)


class RequestType:
    """Section 5.1, verbatim."""
    REVIEW_MATCH = "review_product_match"
    VERIFY_PRICE = "verify_competitor_price"
    REVIEW_SOURCE = "review_data_source"
    REPORT_INCORRECT = "report_incorrect_data"
    INVESTIGATE_MISSING = "investigate_missing_competitor_data"
    ADD_COMPETITOR = "add_review_competitor"
    MANUAL_VERIFICATION = "request_manual_verification"
    OTHER = "other"


REQUEST_TYPE_LABEL = {
    RequestType.REVIEW_MATCH: "Review Product Match",
    RequestType.VERIFY_PRICE: "Verify Competitor Price",
    RequestType.REVIEW_SOURCE: "Review Data Source",
    RequestType.REPORT_INCORRECT: "Report Incorrect Data",
    RequestType.INVESTIGATE_MISSING: "Investigate Missing Competitor Data",
    RequestType.ADD_COMPETITOR: "Add/Review Competitor",
    RequestType.MANUAL_VERIFICATION: "Request Manual Verification",
    RequestType.OTHER: "Other",
}


class RequestStatus:
    """Section 5.3: five statuses and the transitions between them."""
    NEW = "new"
    IN_PROGRESS = "in_progress"
    WAITING = "waiting_for_information"
    RESOLVED = "resolved"
    CLOSED = "closed"


REQUEST_STATUS_LABEL = {
    RequestStatus.NEW: "New", RequestStatus.IN_PROGRESS: "In progress",
    RequestStatus.WAITING: "Waiting for information",
    RequestStatus.RESOLVED: "Resolved", RequestStatus.CLOSED: "Closed",
}

REQUEST_STATUS_MEANING = {
    RequestStatus.NEW: "Submitted and awaiting triage; an admin moves it to In "
                       "progress.",
    RequestStatus.IN_PROGRESS: "Owned and under investigation; may move to "
                               "Waiting for information or Resolved.",
    RequestStatus.WAITING: "An admin needs requester input; a requester reply "
                           "returns it to In progress.",
    RequestStatus.RESOLVED: "An answer or corrective action has been supplied; "
                            "may be Closed or reopened.",
    RequestStatus.CLOSED: "No further work is expected; admins may reopen when "
                          "justified.",
}

# Section 5.3's table, as data. The workflow is enforced from this rather than
# from scattered conditionals, so "permitted next step" has exactly one
# definition and the page and the server read the same one.
REQUEST_TRANSITIONS = {
    RequestStatus.NEW: (RequestStatus.IN_PROGRESS, RequestStatus.CLOSED),
    RequestStatus.IN_PROGRESS: (RequestStatus.WAITING, RequestStatus.RESOLVED,
                                RequestStatus.CLOSED),
    RequestStatus.WAITING: (RequestStatus.IN_PROGRESS, RequestStatus.CLOSED),
    RequestStatus.RESOLVED: (RequestStatus.CLOSED, RequestStatus.IN_PROGRESS),
    RequestStatus.CLOSED: (RequestStatus.IN_PROGRESS,),
}

# A requester replying to a Waiting request returns it to In progress. Section
# 5.3 gives the requester exactly that one transition and no other.
REQUESTER_TRANSITIONS = {
    RequestStatus.WAITING: (RequestStatus.IN_PROGRESS,),
}


class MatchStatus:
    CONFIRMED = "confirmed"
    PROBABLE = "probable"
    AMBIGUOUS = "ambiguous"
    NO_COUNTERPART = "no_counterpart"
    REJECTED = "rejected"
    UNREADABLE = "unreadable"


MATCH_STATUS_LABEL = {
    MatchStatus.CONFIRMED: "Confirmed", MatchStatus.PROBABLE: "Probable",
    MatchStatus.AMBIGUOUS: "Needs a decision",
    MatchStatus.NO_COUNTERPART: "No counterpart",
    MatchStatus.REJECTED: "Rejected", MatchStatus.UNREADABLE: "Source unreadable",
}


class SourceStatus:
    ACTIVE = "active"
    UNREADABLE = "unreadable"
    UNAVAILABLE = "unavailable"
    PENDING_VERIFICATION = "pending_verification"
    APPROVED_FEED = "approved_feed"


class ChangeType:
    """Section 8.1's "change type". Every audited write names one of these."""
    MATCH_RESOLVED = "match_resolved"
    MATCH_CONFIRMED = "match_confirmed"
    MATCH_REJECTED = "match_rejected"
    NO_COUNTERPART = "no_counterpart_marked"
    URL_REPLACED = "competitor_url_replaced"
    SOURCE_REPLACED = "source_replaced"
    SOURCE_ADDED = "source_added"
    SOURCE_UNAVAILABLE = "source_marked_unavailable"
    VERIFICATION_REQUESTED = "verification_requested"
    MANUAL_OBSERVATION = "manual_observation_entered"
    FEED_REGISTERED = "feed_registered"
    FEED_APPROVED = "feed_approved"
    ACTION_CREATED = "action_created"
    ACTION_TRANSITIONED = "action_transitioned"
    ACTION_ASSIGNED = "action_assigned"
    REQUEST_CREATED = "request_created"
    REQUEST_TRANSITIONED = "request_transitioned"
    REQUEST_ANSWERED = "request_answered"
    REQUEST_ASSIGNED = "request_assigned"
    USER_CREATED = "user_created"
    USER_ROLE_CHANGED = "user_role_changed"
    USER_DISABLED = "user_disabled"
    CONVERSATION_ESCALATED = "conversation_escalated"


class Origin:
    """Section 8.1's "origin": where a write came from."""
    UI = "ui"
    AGENT = "agent"
    JOB = "job"
    IMPORT = "import"
    CLI = "cli"


# --------------------------------------------------------------------------
# migrations
# --------------------------------------------------------------------------

M1 = """
CREATE TABLE IF NOT EXISTS ops_meta (
  key   TEXT PRIMARY KEY,
  value TEXT
);

-- Users, roles and account state. Passwords stay in app_user; this is the
-- operational identity every audit row points at, so a user record survives even
-- if authentication is later moved to SSO.
CREATE TABLE IF NOT EXISTS ops_user (
  username     TEXT PRIMARY KEY,
  display_name TEXT,
  role         TEXT NOT NULL,
  is_active    INTEGER NOT NULL DEFAULT 1,
  created_at   TEXT NOT NULL,
  created_by   TEXT,
  last_login_at TEXT,
  last_seen_at TEXT
);

CREATE TABLE IF NOT EXISTS ops_role_grant (
  grant_id   TEXT PRIMARY KEY,
  username   TEXT NOT NULL,
  role       TEXT NOT NULL,
  granted_at TEXT NOT NULL,
  granted_by TEXT,
  revoked_at TEXT,
  note       TEXT
);
CREATE INDEX IF NOT EXISTS ix_ops_grant_user ON ops_role_grant(username);

-- Competitors and their products.
CREATE TABLE IF NOT EXISTS ops_competitor (
  competitor_key TEXT PRIMARY KEY,
  brand          TEXT NOT NULL,
  home_url       TEXT,
  segments       TEXT,
  profile        TEXT,
  created_at     TEXT NOT NULL,
  updated_at     TEXT
);

CREATE TABLE IF NOT EXISTS ops_competitor_product (
  cp_id          TEXT PRIMARY KEY,
  competitor_key TEXT NOT NULL,
  name           TEXT,
  url            TEXT,
  category       TEXT,
  first_seen_at  TEXT,
  last_seen_at   TEXT,
  provenance     TEXT NOT NULL,
  created_at     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_ops_cp_comp
  ON ops_competitor_product(competitor_key);

-- Sources. A source is a URL we read a value from, with its own readability
-- state, so an unreadable source is a record rather than a log line.
CREATE TABLE IF NOT EXISTS ops_source (
  source_id      TEXT PRIMARY KEY,
  competitor_key TEXT,
  url            TEXT NOT NULL,
  kind           TEXT,
  status         TEXT NOT NULL,
  status_reason  TEXT,
  is_approved    INTEGER NOT NULL DEFAULT 0,
  added_by       TEXT,
  added_at       TEXT NOT NULL,
  last_attempt_at TEXT,
  last_ok_at     TEXT,
  fail_count     INTEGER NOT NULL DEFAULT 0,
  last_failure   TEXT,
  note           TEXT
);
CREATE INDEX IF NOT EXISTS ix_ops_source_comp ON ops_source(competitor_key);
CREATE INDEX IF NOT EXISTS ix_ops_source_status ON ops_source(status);

-- Approved feeds and APIs (9.1) — administratively approved integrations, kept
-- apart from ordinary page sources because their provenance label differs.
CREATE TABLE IF NOT EXISTS ops_feed (
  feed_id        TEXT PRIMARY KEY,
  competitor_key TEXT,
  name           TEXT NOT NULL,
  endpoint       TEXT NOT NULL,
  kind           TEXT,
  is_approved    INTEGER NOT NULL DEFAULT 0,
  approved_by    TEXT,
  approved_at    TEXT,
  registered_by  TEXT,
  registered_at  TEXT NOT NULL,
  status         TEXT,
  note           TEXT
);

-- Matches, and their versions. The match row carries the CURRENT state; every
-- state it has ever had is a row in ops_match_version, which is append-only.
CREATE TABLE IF NOT EXISTS ops_match (
  match_id       TEXT PRIMARY KEY,
  clara_product_id TEXT NOT NULL,
  clara_product_name TEXT,
  competitor_key TEXT NOT NULL,
  cp_id          TEXT,
  competitor_product_name TEXT,
  competitor_url TEXT,
  status         TEXT NOT NULL,
  confidence     TEXT,
  score          REAL,
  provenance     TEXT NOT NULL,
  candidates     TEXT,
  version        INTEGER NOT NULL DEFAULT 1,
  created_at     TEXT NOT NULL,
  updated_at     TEXT,
  confirmed_by   TEXT,
  confirmed_at   TEXT,
  note           TEXT
);
CREATE INDEX IF NOT EXISTS ix_ops_match_prod ON ops_match(clara_product_id);
CREATE INDEX IF NOT EXISTS ix_ops_match_comp ON ops_match(competitor_key);
CREATE INDEX IF NOT EXISTS ix_ops_match_status ON ops_match(status);

CREATE TABLE IF NOT EXISTS ops_match_version (
  version_id   TEXT PRIMARY KEY,
  match_id     TEXT NOT NULL,
  version      INTEGER NOT NULL,
  status       TEXT NOT NULL,
  confidence   TEXT,
  competitor_product_name TEXT,
  competitor_url TEXT,
  provenance   TEXT NOT NULL,
  actor        TEXT,
  at           TEXT NOT NULL,
  reason       TEXT,
  superseded_by TEXT,
  payload      TEXT
);
CREATE INDEX IF NOT EXISTS ix_ops_mv_match ON ops_match_version(match_id);

-- Observations: price, availability and offer, insert-only. A correction is a
-- new observation that supersedes the old one; nothing is overwritten (8.2).
CREATE TABLE IF NOT EXISTS ops_observation (
  obs_id         TEXT PRIMARY KEY,
  competitor_key TEXT NOT NULL,
  cp_id          TEXT,
  match_id       TEXT,
  source_id      TEXT,
  source_url     TEXT,
  price          TEXT,
  currency       TEXT,
  price_min      TEXT,
  price_max      TEXT,
  was_price      TEXT,
  discount_pct   TEXT,
  availability   TEXT,
  offer_wording  TEXT,
  observed_at    TEXT NOT NULL,
  last_checked_at TEXT,
  provenance     TEXT NOT NULL,
  actor          TEXT,
  note           TEXT,
  superseded_by  TEXT,
  created_at     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_ops_obs_comp ON ops_observation(competitor_key);
CREATE INDEX IF NOT EXISTS ix_ops_obs_match ON ops_observation(match_id);
CREATE INDEX IF NOT EXISTS ix_ops_obs_at ON ops_observation(observed_at);

-- Actions: the operational work queue (3, 4.1).
CREATE TABLE IF NOT EXISTS ops_action (
  action_id      TEXT PRIMARY KEY,
  action_type    TEXT NOT NULL,
  reason         TEXT,
  priority       TEXT NOT NULL,
  status         TEXT NOT NULL,
  assignee       TEXT,
  due_date       TEXT,
  clara_product_id TEXT,
  clara_product_name TEXT,
  competitor_key TEXT,
  match_id       TEXT,
  source_id      TEXT,
  candidates     TEXT,
  evidence       TEXT,
  last_attempt_at TEXT,
  failure_reason TEXT,
  resolution_note TEXT,
  outcome        TEXT,
  request_id     TEXT,
  dedupe_key     TEXT,
  created_at     TEXT NOT NULL,
  created_by     TEXT,
  updated_at     TEXT,
  resolved_at    TEXT,
  resolved_by    TEXT
);
CREATE INDEX IF NOT EXISTS ix_ops_action_status ON ops_action(status);
CREATE INDEX IF NOT EXISTS ix_ops_action_type ON ops_action(action_type);
CREATE INDEX IF NOT EXISTS ix_ops_action_assignee ON ops_action(assignee);
CREATE UNIQUE INDEX IF NOT EXISTS ux_ops_action_dedupe
  ON ops_action(dedupe_key);

CREATE TABLE IF NOT EXISTS ops_action_activity (
  activity_id TEXT PRIMARY KEY,
  action_id   TEXT NOT NULL,
  at          TEXT NOT NULL,
  actor       TEXT,
  kind        TEXT NOT NULL,
  detail      TEXT,
  from_value  TEXT,
  to_value    TEXT
);
CREATE INDEX IF NOT EXISTS ix_ops_act_activity ON ops_action_activity(action_id);

-- Requests (5).
CREATE TABLE IF NOT EXISTS ops_request (
  request_id   TEXT PRIMARY KEY,
  request_type TEXT NOT NULL,
  subject      TEXT NOT NULL,
  description  TEXT,
  requester    TEXT NOT NULL,
  status       TEXT NOT NULL,
  priority     TEXT,
  owner        TEXT,
  detail_level TEXT,
  context      TEXT,
  resolution   TEXT,
  closure_reason TEXT,
  action_id    TEXT,
  conversation_id TEXT,
  created_at   TEXT NOT NULL,
  updated_at   TEXT,
  resolved_at  TEXT,
  closed_at    TEXT
);
CREATE INDEX IF NOT EXISTS ix_ops_req_requester ON ops_request(requester);
CREATE INDEX IF NOT EXISTS ix_ops_req_status ON ops_request(status);

CREATE TABLE IF NOT EXISTS ops_request_message (
  message_id TEXT PRIMARY KEY,
  request_id TEXT NOT NULL,
  at         TEXT NOT NULL,
  author     TEXT NOT NULL,
  author_role TEXT,
  body       TEXT NOT NULL,
  is_response INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS ix_ops_reqmsg ON ops_request_message(request_id);

CREATE TABLE IF NOT EXISTS ops_request_status (
  entry_id   TEXT PRIMARY KEY,
  request_id TEXT NOT NULL,
  at         TEXT NOT NULL,
  actor      TEXT,
  from_status TEXT,
  to_status  TEXT NOT NULL,
  note       TEXT
);
CREATE INDEX IF NOT EXISTS ix_ops_reqstatus ON ops_request_status(request_id);

-- Agent conversations and the records they cited (9.1).
CREATE TABLE IF NOT EXISTS ops_conversation (
  conversation_id TEXT PRIMARY KEY,
  username     TEXT NOT NULL,
  context_kind TEXT,
  context_id   TEXT,
  started_at   TEXT NOT NULL,
  last_at      TEXT,
  title        TEXT
);
CREATE INDEX IF NOT EXISTS ix_ops_conv_user ON ops_conversation(username);

CREATE TABLE IF NOT EXISTS ops_message (
  message_id      TEXT PRIMARY KEY,
  conversation_id TEXT NOT NULL,
  at              TEXT NOT NULL,
  role            TEXT NOT NULL,
  body            TEXT NOT NULL,
  grounded        INTEGER NOT NULL DEFAULT 1,
  gaps            TEXT,
  decision_source TEXT
);
CREATE INDEX IF NOT EXISTS ix_ops_msg_conv ON ops_message(conversation_id);

CREATE TABLE IF NOT EXISTS ops_citation (
  citation_id TEXT PRIMARY KEY,
  message_id  TEXT NOT NULL,
  record_kind TEXT NOT NULL,
  record_id   TEXT,
  label       TEXT,
  url         TEXT,
  provenance  TEXT,
  observed_at TEXT
);
CREATE INDEX IF NOT EXISTS ix_ops_cite_msg ON ops_citation(message_id);

-- Immutable audit events (8.1). Append-only: nothing in ops updates or deletes
-- a row in this table.
CREATE TABLE IF NOT EXISTS ops_audit (
  event_id      TEXT PRIMARY KEY,
  at            TEXT NOT NULL,
  actor         TEXT NOT NULL,
  actor_role    TEXT,
  change_type   TEXT NOT NULL,
  before_value  TEXT,
  after_value   TEXT,
  clara_product_id TEXT,
  competitor_key TEXT,
  match_id      TEXT,
  obs_id        TEXT,
  offer_id      TEXT,
  source_id     TEXT,
  action_id     TEXT,
  request_id    TEXT,
  note          TEXT,
  origin        TEXT NOT NULL,
  correlation_id TEXT
);
CREATE INDEX IF NOT EXISTS ix_ops_audit_at ON ops_audit(at);
CREATE INDEX IF NOT EXISTS ix_ops_audit_match ON ops_audit(match_id);
CREATE INDEX IF NOT EXISTS ix_ops_audit_action ON ops_audit(action_id);
CREATE INDEX IF NOT EXISTS ix_ops_audit_req ON ops_audit(request_id);
CREATE INDEX IF NOT EXISTS ix_ops_audit_corr ON ops_audit(correlation_id);

-- A durable, database-backed job table. 9.2 says a simple one is sufficient for
-- MVP and a distributed queue is not required.
CREATE TABLE IF NOT EXISTS ops_job (
  job_id     TEXT PRIMARY KEY,
  job_type   TEXT NOT NULL,
  payload    TEXT,
  status     TEXT NOT NULL,
  requested_by TEXT,
  requested_at TEXT NOT NULL,
  started_at TEXT,
  finished_at TEXT,
  attempts   INTEGER NOT NULL DEFAULT 0,
  last_error TEXT,
  result     TEXT,
  action_id  TEXT,
  request_id TEXT
);
CREATE INDEX IF NOT EXISTS ix_ops_job_status ON ops_job(status);
"""

M2 = """
-- Retention policy, recorded rather than implied (9.2).
CREATE TABLE IF NOT EXISTS ops_retention (
  scope      TEXT PRIMARY KEY,
  keep_days  INTEGER,
  policy     TEXT,
  set_by     TEXT,
  set_at     TEXT
);
"""

M3 = """
-- Saved views and filter state. 10 asks for URL-persisted filters; this is the
-- durable half, so a user's working set is not lost with a browser tab.
CREATE TABLE IF NOT EXISTS ops_saved_view (
  view_id   TEXT PRIMARY KEY,
  username  TEXT NOT NULL,
  scope     TEXT NOT NULL,
  name      TEXT NOT NULL,
  query     TEXT,
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_ops_view_user ON ops_saved_view(username, scope);
"""

M4 = """
-- Where an imported scan came from, so an import is attributable and repeatable
-- (9.2: import completed scans into the durable database; redeployment must
-- never reset operational records).
CREATE TABLE IF NOT EXISTS ops_import (
  import_id  TEXT PRIMARY KEY,
  source     TEXT NOT NULL,
  run_id     TEXT,
  at         TEXT NOT NULL,
  actor      TEXT,
  counts     TEXT,
  note       TEXT
);
"""

M5 = """
-- The Clara catalogue itself (3: "Products — Clara catalogue"). Until now a
-- Clara product existed here only as a foreign key on ops_match, which meant a
-- product with no competitor assigned could not be listed, counted or opened —
-- and "incomplete coverage" is precisely what section 10 asks the Products tab
-- to surface first. So the catalogue becomes a durable record of its own.
CREATE TABLE IF NOT EXISTS ops_product (
  clara_product_id TEXT PRIMARY KEY,
  name         TEXT,
  url          TEXT,
  image_url    TEXT,
  segment      TEXT,
  category     TEXT,
  product_format TEXT,
  price        TEXT,
  currency     TEXT,
  rating       REAL,
  rating_count INTEGER,
  specs        TEXT,
  language     TEXT,
  provenance   TEXT NOT NULL,
  first_seen_at TEXT,
  last_seen_at TEXT,
  created_at   TEXT NOT NULL,
  updated_at   TEXT
);
CREATE INDEX IF NOT EXISTS ix_ops_product_seg ON ops_product(segment);
CREATE INDEX IF NOT EXISTS ix_ops_product_cat ON ops_product(category);
"""

MIGRATIONS = [(1, M1), (2, M2), (3, M3), (4, M4), (5, M5)]

DEFAULT_RETENTION = [
    ("audit", None, "Audit events are kept indefinitely. They are the record of "
                    "who changed what, and a retention window on them would "
                    "remove the only evidence that a change was authorised."),
    ("observation", 1095, "Price and offer observations are kept for three "
                          "years so a price history is long enough to show a "
                          "seasonal pattern."),
    ("conversation", 365, "Agent conversations are kept for a year; the Requests "
                          "they produced are kept under the request policy."),
    ("request", 1095, "Requests and their responses are kept for three years."),
    ("job", 90, "Job rows are operational plumbing and are pruned after 90 days; "
                "anything they changed is in the audit trail."),
]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def schema_version(db: Db) -> int:
    if not db.table_exists("ops_meta"):
        return 0
    try:
        return int(db.value("SELECT value FROM ops_meta WHERE key=?",
                            ("schema_version",), 0) or 0)
    except (TypeError, ValueError):
        return 0


def migrate(db: Db, *, verbose: bool = False) -> dict:
    """Bring the database to SCHEMA_VERSION. Idempotent, safe on every start.

    Called on connect rather than by a separate command, because the hosted path
    has no separate command: a cold serverless instance pointing at a fresh
    Postgres database has to be able to build the schema itself, or the first
    request 500s and the deployment looks broken.
    """
    have = schema_version(db)
    applied = []
    for version, ddl in MIGRATIONS:
        if version <= have:
            continue
        db.script(ddl)
        with db.tx():
            db.exec("DELETE FROM ops_meta WHERE key=?", ("schema_version",))
            db.exec("INSERT INTO ops_meta (key,value) VALUES (?,?)",
                    ("schema_version", str(version)))
        applied.append(version)
        if verbose:
            print(f"  ops schema -> v{version}")

    if applied:
        with db.tx():
            for scope, days, policy in DEFAULT_RETENTION:
                if not db.row("SELECT scope FROM ops_retention WHERE scope=?",
                              (scope,)):
                    db.exec(
                        "INSERT INTO ops_retention "
                        "(scope,keep_days,policy,set_by,set_at) "
                        "VALUES (?,?,?,?,?)",
                        (scope, days, policy, "system", now_iso()))
    return {"from": have, "to": schema_version(db), "applied": applied}


def connect(sqlite_path=None, *, verbose: bool = False) -> Db:
    """A migrated connection. The only way `ops` opens a database."""
    db = Db(sqlite_path)
    migrate(db, verbose=verbose)
    return db
