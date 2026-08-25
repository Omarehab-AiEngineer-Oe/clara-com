"""Account management, behind one interface the router can rely on.

The router should not know how a host stores users. Two hosts do it differently
and one of them cannot do it at all: the local server owns a real SQLite file and
can write, while a serverless instance writing to its own `/tmp` copy would make a
change no other instance can see and that vanishes on recycle. Section 2 names
that practice — ephemeral instance-local files for users — as no longer
appropriate, and the honest response is not to offer buttons that discard the
change.

So `Accounts` wraps the real `Auth`, `ReadOnlyAccounts` refuses with a reason, and
both expose the same five operations plus `writable`. The page renders controls
from `writable`; the refusal, when it happens, carries the reason to the screen.

This is also where `ops_user` is kept in step. Section 9.1 lists users among the
durable records, and an audit row naming an actor is only useful if that actor
still resolves to a person after their account is disabled — so every write here
mirrors into `ops_user` rather than leaving the operational identity behind.
"""

from __future__ import annotations

import secrets

from ..auth import ROLE_ADMIN, ROLE_VIEWER
from ..ops.schema import now_iso


class Accounts:
    """The writable implementation, over the local `Auth` store."""

    writable = True

    def __init__(self, auth, db=None):
        self.auth = auth
        self.db = db

    # ---- reading ----

    def list_users(self) -> list:
        return self.auth.list_users()

    # ---- writing ----

    def add_user(self, username: str, password: str | None, *,
                 display_name: str = "", role: str = "viewer",
                 by: str = "") -> str:
        """Create an account and return the password to show once."""
        pw = (password or "").strip() or secrets.token_urlsafe(9)
        self.auth.create_user(
            (username or "").strip().lower(), pw,
            role=(ROLE_ADMIN if role == "admin" else ROLE_VIEWER),
            display_name=display_name, created_by=by)
        self._mirror(username, role=role, display_name=display_name, by=by)
        return pw

    def set_active(self, username: str, active: bool, by: str = "") -> None:
        self.auth.set_active(username, active, by)
        self._touch(username, is_active=1 if active else 0)

    def set_role(self, username: str, role: str, by: str = "") -> None:
        self.auth.set_role(username, role, by)
        self._touch(username, role=role)

    def reset_password(self, username: str, by: str = "") -> str:
        pw = secrets.token_urlsafe(9)
        self.auth.reset_password(username, pw)
        return pw

    def delete_user(self, username: str, by: str = "") -> None:
        self.auth.delete_user(username, by)
        # The ops_user row is deliberately kept: audit events point at it, and
        # deleting it would leave a trail naming an actor that resolves to
        # nothing. It is marked inactive instead.
        self._touch(username, is_active=0)

    # ---- keeping ops_user in step (9.1) ----

    def _mirror(self, username: str, *, role: str, display_name: str,
                by: str) -> None:
        if self.db is None:
            return
        u = (username or "").strip().lower()
        with self.db.tx():
            if not self.db.row("SELECT username FROM ops_user WHERE username=?",
                               (u,)):
                self.db.exec(
                    "INSERT INTO ops_user (username,display_name,role,"
                    "is_active,created_at,created_by) VALUES (?,?,?,?,?,?)",
                    (u, display_name or None,
                     "admin" if role == "admin" else "viewer", 1, now_iso(),
                     by or None))

    def _touch(self, username: str, **fields) -> None:
        if self.db is None or not fields:
            return
        u = (username or "").strip().lower()
        sets = ", ".join(f"{k}=?" for k in fields)
        with self.db.tx():
            self.db.exec(f"UPDATE ops_user SET {sets} WHERE username=?",
                         tuple(fields.values()) + (u,))


class ReadOnlyAccounts:
    """A host that cannot durably write users. Refuses, and says why."""

    writable = False

    def __init__(self, users: list, why: str):
        self._users = users or []
        self.why = why

    def list_users(self) -> list:
        return self._users

    def _no(self, *_a, **_k):
        raise ValueError(self.why)

    add_user = set_active = set_role = reset_password = delete_user = _no
