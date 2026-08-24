"""The operational application: Actions, Requests, the Agent, audit and provenance.

This package is the addendum. The existing modules collect evidence; this one is
where a person does something about it — resolves an ambiguous match, replaces an
unreadable source, asks a question, escalates it, and leaves an audit trail behind
every one of those.

    db          one data layer, SQLite locally and PostgreSQL when configured
    schema      section 9.1's durable records, as numbered migrations
    audit       section 8: append-only events and the four provenance labels
    authz       section 9.2: authorization enforced on the server, not the page
    actions     section 4: the work queue and both inline resolution workflows
    requests    section 5: eight types, five statuses, context prefill
    agent       sections 6 and 7: read-only, grounded, scope-limited, escalating
    ingest      importing completed scans so a redeploy cannot reset them

The rule the whole package is built to keep: **an operational write is one
transaction.** The domain record, the status transition and the audit event commit
together or not at all. `db.exec` refuses to run outside a transaction, which
turns that rule from a convention into a constraint.
"""

from .audit import Audit, provenance_badge
from .authz import Actor, Permission, can, require
from .db import Db, database_url, engine_status
from .schema import (ACTION_STATUS_LABEL, ACTION_TYPE_LABEL, ActionStatus,
                     ActionType, ChangeType, MATCH_STATUS_LABEL, MatchStatus,
                     Origin, PROVENANCE_DEFINITION, PROVENANCE_LABEL,
                     Provenance, REQUEST_STATUS_LABEL, REQUEST_STATUS_MEANING,
                     REQUEST_TRANSITIONS, REQUEST_TYPE_LABEL, RequestStatus,
                     RequestType, SourceStatus, connect, migrate, now_iso)

__all__ = [
    "Actor", "Audit", "Db", "Permission", "ACTION_STATUS_LABEL",
    "ACTION_TYPE_LABEL", "ActionStatus", "ActionType", "ChangeType",
    "MATCH_STATUS_LABEL", "MatchStatus", "Origin", "PROVENANCE_DEFINITION",
    "PROVENANCE_LABEL", "Provenance", "REQUEST_STATUS_LABEL",
    "REQUEST_STATUS_MEANING", "REQUEST_TRANSITIONS", "REQUEST_TYPE_LABEL",
    "RequestStatus", "RequestType", "SourceStatus", "can", "connect",
    "database_url", "engine_status", "migrate", "now_iso", "provenance_badge",
    "require",
]
