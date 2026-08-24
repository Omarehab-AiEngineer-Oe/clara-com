"""Users, passwords and sessions.

Security choices worth stating, because the easy version of each is wrong:

* Passwords are never stored. Each one is salted and run through scrypt, and
  comparison is constant-time. There is no reversible form of a password here.
* There is no default password. The first admin is created with a random one
  that is printed once to the console and never written to disk; if it is lost,
  a new admin is created rather than the old one recovered.
* Sessions are opaque random tokens held server-side with an expiry. The cookie
  carries the token only, so nothing about the user is client-editable.
* Only an admin can create or disable users, and an admin cannot remove their own
  admin rights or delete the last remaining admin — that would lock the tool.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS app_user (
  username TEXT PRIMARY KEY,
  display_name TEXT,
  role TEXT NOT NULL DEFAULT 'viewer',   -- admin | viewer
  pw_salt BLOB NOT NULL,
  pw_hash BLOB NOT NULL,
  is_active INTEGER NOT NULL DEFAULT 1,
  created_at TEXT,
  created_by TEXT,
  last_login_at TEXT
);

CREATE TABLE IF NOT EXISTS app_session (
  token TEXT PRIMARY KEY,
  username TEXT NOT NULL,
  created_at TEXT,
  expires_at TEXT,
  user_agent TEXT
);
"""

SESSION_HOURS = 12
SCRYPT_N = 2 ** 14
SCRYPT_R = 8
SCRYPT_P = 1
DKLEN = 64

ROLE_ADMIN = "admin"
ROLE_VIEWER = "viewer"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds")


def hash_password(password: str, salt: bytes | None = None) -> tuple[bytes, bytes]:
    salt = salt or os.urandom(16)
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt,
                            n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P, dklen=DKLEN)
    return salt, digest


def verify_password(password: str, salt: bytes, expected: bytes) -> bool:
    _, digest = hash_password(password, salt)
    return hmac.compare_digest(digest, expected)


class Auth:
    def __init__(self, db_path: Path):
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(db_path), check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)
        self.db.commit()

    def close(self) -> None:
        self.db.close()

    # ---------------- users ----------------

    def user_count(self) -> int:
        return self.db.execute("SELECT COUNT(*) FROM app_user").fetchone()[0]

    def admin_count(self) -> int:
        return self.db.execute(
            "SELECT COUNT(*) FROM app_user WHERE role=? AND is_active=1",
            (ROLE_ADMIN,)).fetchone()[0]

    def get_user(self, username: str) -> dict | None:
        r = self.db.execute("SELECT * FROM app_user WHERE username=?",
                            (username.strip().lower(),)).fetchone()
        return dict(r) if r else None

    def list_users(self) -> list[dict]:
        rows = self.db.execute(
            """SELECT username, display_name, role, is_active, created_at,
                      created_by, last_login_at
               FROM app_user ORDER BY role DESC, username""").fetchall()
        return [dict(r) for r in rows]

    def create_user(self, username: str, password: str, role: str = ROLE_VIEWER,
                    display_name: str = "", created_by: str = "system") -> dict:
        username = (username or "").strip().lower()
        if not username or len(username) < 3:
            raise ValueError("Username must be at least 3 characters")
        if not username.replace("_", "").replace(".", "").replace("-", "").isalnum():
            raise ValueError("Username accepts letters, numbers and . _ - only")
        if len(password or "") < 8:
            raise ValueError("Password must be at least 8 characters")
        if role not in (ROLE_ADMIN, ROLE_VIEWER):
            raise ValueError("Unknown role")
        if self.get_user(username):
            raise ValueError(f"User {username} already exists")

        salt, digest = hash_password(password)
        self.db.execute(
            """INSERT INTO app_user
               (username, display_name, role, pw_salt, pw_hash, is_active,
                created_at, created_by)
               VALUES (?,?,?,?,?,1,?,?)""",
            (username, display_name or username, role, salt, digest,
             _iso(_now()), created_by))
        self.db.commit()
        return {"username": username, "role": role,
                "display_name": display_name or username}

    def set_active(self, username: str, active: bool, actor: str) -> None:
        u = self.get_user(username)
        if not u:
            raise ValueError("No such user")
        if not active:
            if u["username"] == actor:
                raise ValueError("You cannot disable your own account")
            if u["role"] == ROLE_ADMIN and self.admin_count() <= 1:
                raise ValueError("The last remaining admin cannot be disabled")
        self.db.execute("UPDATE app_user SET is_active=? WHERE username=?",
                        (1 if active else 0, u["username"]))
        if not active:
            self.db.execute("DELETE FROM app_session WHERE username=?",
                            (u["username"],))
        self.db.commit()

    def set_role(self, username: str, role: str, actor: str) -> None:
        if role not in (ROLE_ADMIN, ROLE_VIEWER):
            raise ValueError("Unknown role")
        u = self.get_user(username)
        if not u:
            raise ValueError("No such user")
        if (u["role"] == ROLE_ADMIN and role != ROLE_ADMIN
                and self.admin_count() <= 1):
            raise ValueError("The last remaining admin cannot be removed")
        if u["username"] == actor and role != ROLE_ADMIN:
            raise ValueError("You cannot remove admin rights from your own account")
        self.db.execute("UPDATE app_user SET role=? WHERE username=?",
                        (role, u["username"]))
        self.db.commit()

    def reset_password(self, username: str, new_password: str) -> None:
        if len(new_password or "") < 8:
            raise ValueError("Password must be at least 8 characters")
        u = self.get_user(username)
        if not u:
            raise ValueError("No such user")
        salt, digest = hash_password(new_password)
        self.db.execute(
            "UPDATE app_user SET pw_salt=?, pw_hash=? WHERE username=?",
            (salt, digest, u["username"]))
        # Any existing session must not survive a password change.
        self.db.execute("DELETE FROM app_session WHERE username=?",
                        (u["username"],))
        self.db.commit()

    def delete_user(self, username: str, actor: str) -> None:
        u = self.get_user(username)
        if not u:
            raise ValueError("No such user")
        if u["username"] == actor:
            raise ValueError("You cannot delete your own account")
        if u["role"] == ROLE_ADMIN and self.admin_count() <= 1:
            raise ValueError("The last remaining admin cannot be deleted")
        self.db.execute("DELETE FROM app_session WHERE username=?", (u["username"],))
        self.db.execute("DELETE FROM app_user WHERE username=?", (u["username"],))
        self.db.commit()

    # ---------------- bootstrap ----------------

    def ensure_admin(self) -> tuple[str, str] | None:
        """Create the first admin if there is none.

        Returns (username, password) exactly once, for printing to the console.
        The password is random and is never persisted in readable form.
        """
        if self.admin_count() > 0:
            return None
        username = os.environ.get("CLARA_ADMIN_USER", "admin").strip().lower()
        password = os.environ.get("CLARA_ADMIN_PASSWORD") or secrets.token_urlsafe(12)
        existing = self.get_user(username)
        if existing:
            self.reset_password(username, password)
            self.set_role(username, ROLE_ADMIN, actor="system")
            self.db.execute("UPDATE app_user SET is_active=1 WHERE username=?",
                            (username,))
            self.db.commit()
        else:
            self.create_user(username, password, role=ROLE_ADMIN,
                             display_name="Administrator", created_by="system")
        return username, password

    # ---------------- login / sessions ----------------

    def login(self, username: str, password: str, user_agent: str = "") -> str | None:
        u = self.get_user(username)
        if not u or not u["is_active"]:
            # Still spend the hashing cost so a missing user and a wrong password
            # take the same time; otherwise timing reveals which names exist.
            hash_password(password or "", os.urandom(16))
            return None
        if not verify_password(password or "", u["pw_salt"], u["pw_hash"]):
            return None
        token = secrets.token_urlsafe(32)
        now = _now()
        self.db.execute(
            """INSERT INTO app_session (token, username, created_at, expires_at, user_agent)
               VALUES (?,?,?,?,?)""",
            (token, u["username"], _iso(now),
             _iso(now + timedelta(hours=SESSION_HOURS)), (user_agent or "")[:200]))
        self.db.execute("UPDATE app_user SET last_login_at=? WHERE username=?",
                        (_iso(now), u["username"]))
        self.db.commit()
        return token

    def session_user(self, token: str | None) -> dict | None:
        if not token:
            return None
        r = self.db.execute("SELECT * FROM app_session WHERE token=?",
                            (token,)).fetchone()
        if not r:
            return None
        try:
            if datetime.fromisoformat(r["expires_at"]) < _now():
                self.logout(token)
                return None
        except (TypeError, ValueError):
            return None
        u = self.get_user(r["username"])
        if not u or not u["is_active"]:
            return None
        return {"username": u["username"], "role": u["role"],
                "display_name": u["display_name"] or u["username"],
                "is_admin": u["role"] == ROLE_ADMIN}

    def logout(self, token: str | None) -> None:
        if token:
            self.db.execute("DELETE FROM app_session WHERE token=?", (token,))
            self.db.commit()

    def purge_expired(self) -> int:
        cur = self.db.execute("DELETE FROM app_session WHERE expires_at < ?",
                              (_iso(_now()),))
        self.db.commit()
        return cur.rowcount or 0
