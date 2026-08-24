"""Section 9.2: authorization enforced server-side. Hiding controls is not enough.

That sentence in the requirements is aimed at a specific, common bug: a page that
omits the Delete button for a viewer, and a POST handler that deletes anyway when
someone sends the request directly. Section 12 turns it into an acceptance
criterion — unauthorized users must not be able to perform administrative source,
user, Request or audit operations *through either UI or direct requests*.

So permission is checked in two places for different reasons, and the second one
is the one that matters:

* `can()` decides whether to render a control. This is presentation.
* `require()` decides whether an operation runs, and raises if not. Every
  operational function in `ops` calls it as its first statement, before it reads
  anything and long before it writes.

The design keeps them honest by making them the same table. `PERMISSIONS` is the
single source, so a control that renders is a control that works, and a control
that does not render cannot be invoked by hand either.

Roles are deliberately two. Section 11 puts "Basic User/Admin authorization" in
MVP and "expanded roles" in Phase 2, and inventing a middle tier now would mean
guessing at a boundary nobody has asked for yet.
"""

from __future__ import annotations

from dataclasses import dataclass

ROLE_ADMIN = "admin"
ROLE_USER = "viewer"          # the existing name for a non-admin in app_user

ROLE_LABEL = {ROLE_ADMIN: "Admin", ROLE_USER: "User"}


class Permission:
    """Every operation that needs a permission. Named, not inferred."""

    # Reading
    VIEW = "view"                                  # any signed-in user
    VIEW_AUDIT = "view_audit"

    # Actions (4)
    ACTION_RESOLVE = "action_resolve"
    ACTION_ASSIGN = "action_assign"
    ACTION_DISMISS = "action_dismiss"

    # Data corrections (4.2, 4.3)
    MATCH_RESOLVE = "match_resolve"
    OBSERVATION_MANUAL = "observation_manual"
    SOURCE_REPLACE = "source_replace"
    SOURCE_MARK_UNAVAILABLE = "source_mark_unavailable"
    VERIFICATION_REQUEST = "verification_request"

    # Administration
    SOURCE_APPROVE = "source_approve"
    FEED_REGISTER = "feed_register"
    FEED_APPROVE = "feed_approve"
    USER_MANAGE = "user_manage"
    REQUEST_ADMIN = "request_admin"
    RETENTION_MANAGE = "retention_manage"
    JOB_RUN = "job_run"

    # Requests (5)
    REQUEST_CREATE = "request_create"
    REQUEST_REPLY = "request_reply"

    # Agent (6)
    AGENT_ASK = "agent_ask"
    AGENT_ESCALATE = "agent_escalate"


# The single source of truth. A permission absent from a role's set is denied;
# there is no wildcard and no implicit inheritance, because "admin gets
# everything" is exactly the assumption that lets a new admin-only operation
# quietly become available to everyone.
PERMISSIONS: dict = {
    ROLE_USER: {
        Permission.VIEW,
        Permission.AGENT_ASK,
        Permission.AGENT_ESCALATE,
        Permission.REQUEST_CREATE,
        Permission.REQUEST_REPLY,
        # A user may do the operational work in front of them. Section 12's
        # first criterion is that *a user* can resolve each supported
        # ambiguous-match Action without leaving the application, so resolution
        # is not an admin power.
        Permission.ACTION_RESOLVE,
        Permission.MATCH_RESOLVE,
        Permission.OBSERVATION_MANUAL,
        Permission.SOURCE_REPLACE,
        Permission.VERIFICATION_REQUEST,
    },
    ROLE_ADMIN: {
        Permission.VIEW, Permission.VIEW_AUDIT,
        Permission.ACTION_RESOLVE, Permission.ACTION_ASSIGN,
        Permission.ACTION_DISMISS,
        Permission.MATCH_RESOLVE, Permission.OBSERVATION_MANUAL,
        Permission.SOURCE_REPLACE, Permission.SOURCE_MARK_UNAVAILABLE,
        Permission.VERIFICATION_REQUEST,
        Permission.SOURCE_APPROVE, Permission.FEED_REGISTER,
        Permission.FEED_APPROVE, Permission.USER_MANAGE,
        Permission.REQUEST_ADMIN, Permission.RETENTION_MANAGE,
        Permission.JOB_RUN,
        Permission.REQUEST_CREATE, Permission.REQUEST_REPLY,
        Permission.AGENT_ASK, Permission.AGENT_ESCALATE,
    },
}

# Why a denial happened, in words a person can act on. A 403 that says "denied"
# teaches nobody anything; one that names the role needed is a usable message.
DENIAL = {
    Permission.SOURCE_APPROVE: "approving a source is an admin operation",
    Permission.FEED_APPROVE: "approving a feed or API integration is an admin "
                             "operation",
    Permission.FEED_REGISTER: "registering a feed or API is an admin operation",
    Permission.USER_MANAGE: "managing users is an admin operation",
    Permission.REQUEST_ADMIN: "owning, answering and closing other people's "
                              "requests is an admin operation",
    Permission.VIEW_AUDIT: "the audit history is visible to admins",
    Permission.ACTION_ASSIGN: "assigning work to someone else is an admin "
                              "operation",
    Permission.ACTION_DISMISS: "dismissing an action without resolving it is an "
                               "admin operation",
    Permission.SOURCE_MARK_UNAVAILABLE: "marking a source permanently "
                                        "unavailable is an admin operation",
    Permission.RETENTION_MANAGE: "retention policy is an admin operation",
    Permission.JOB_RUN: "running a verification job is an admin operation",
}


class Denied(PermissionError):
    """Raised by `require`. Carries enough to render a 403 that explains itself."""

    def __init__(self, actor: "Actor", permission: str, detail: str = ""):
        self.actor = actor
        self.permission = permission
        self.detail = detail or DENIAL.get(
            permission, f"{permission} is not available to your role")
        super().__init__(
            f"{actor.username or 'anonymous'} ({ROLE_LABEL.get(actor.role, actor.role)}) "
            f"cannot {permission}: {self.detail}")


@dataclass(frozen=True)
class Actor:
    """Who is performing an operation. Every audited write needs one.

    Frozen on purpose: an actor that could be mutated mid-request is an actor that
    could be escalated mid-request, and the audit row would still name whoever it
    started as.
    """
    username: str
    role: str = ROLE_USER
    display_name: str = ""
    origin: str = "ui"

    @property
    def is_admin(self) -> bool:
        return self.role == ROLE_ADMIN

    @property
    def label(self) -> str:
        return self.display_name or self.username

    @classmethod
    def from_user(cls, user: dict | None, origin: str = "ui") -> "Actor":
        """Build from the session user dict the existing auth layer returns."""
        u = user or {}
        return cls(username=u.get("username") or "",
                   role=(ROLE_ADMIN if u.get("is_admin") or
                         u.get("role") == ROLE_ADMIN else ROLE_USER),
                   display_name=u.get("display_name") or "",
                   origin=origin)

    @classmethod
    def system(cls, origin: str = "job") -> "Actor":
        """The actor for an automated run. Never an admin.

        A scheduled collection is not a person and must not be able to perform
        an administrative operation. Giving it the user role means an automated
        path that tries to approve a feed fails loudly instead of silently
        acquiring a privilege nobody granted.
        """
        return cls(username="system", role=ROLE_USER,
                   display_name="Automated run", origin=origin)


def can(actor: Actor | None, permission: str) -> bool:
    """Whether to render a control. Presentation only — never the last word."""
    if actor is None or not actor.username:
        return False
    return permission in PERMISSIONS.get(actor.role, set())


def require(actor: Actor | None, permission: str, detail: str = "") -> Actor:
    """Whether an operation runs. Raises `Denied` if not.

    Called as the first statement of every operational function in `ops`, which
    is what makes section 12's "through either UI or direct requests" true: the
    check is on the operation, so it cannot be skipped by addressing the handler
    directly.
    """
    if actor is None or not actor.username:
        raise Denied(Actor(username="", role=ROLE_USER), permission,
                     "you are not signed in")
    if permission not in PERMISSIONS.get(actor.role, set()):
        raise Denied(actor, permission, detail)
    return actor


def own_or_admin(actor: Actor, owner_username: str, permission: str) -> Actor:
    """A record's own requester may act on it; otherwise the permission decides.

    Section 5 gives a requester real abilities on their own request — reply, and
    move a Waiting request back to In progress — without making them an admin.
    This is that rule, in one place, so "is it mine" is never re-implemented
    slightly differently.
    """
    if actor.username and actor.username == owner_username:
        return actor
    return require(actor, permission)


def visible_permissions(actor: Actor | None) -> dict:
    """Every permission and whether this actor has it. For the Admin page.

    Rendered as a table so a person can see what their role actually allows
    rather than discovering it by being refused.
    """
    have = PERMISSIONS.get(actor.role, set()) if actor else set()
    return {p: {"granted": p in have,
                "why": "" if p in have else DENIAL.get(p, "not in your role")}
            for p in sorted(
                {x for s in PERMISSIONS.values() for x in s})}
