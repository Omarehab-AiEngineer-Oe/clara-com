"""Section 9: durable operational storage, one data layer, two backends.

The requirement is specific and it is about survival, not about a product name:
operational data must survive restarts, serverless instance recycling and
redeployment, and deploy-time snapshots and instance-local files must not be the
system of record. PostgreSQL is the recommended production default.

So there is one data layer here and it speaks both dialects. `DATABASE_URL`
decides: set it and every operational write goes to Postgres; leave it unset and
they go to the local SQLite file. The same SQL runs on both, which is only
possible because the schema deliberately avoids anything the two disagree about —
no serial types, no `RETURNING`, no upsert syntax, no JSON operators. Keys are
generated in Python, JSON is stored as text, and timestamps are ISO strings.

That is a real constraint and it buys a real thing: the hosted deployment stops
being a snapshot. Right now the Vercel build ships a copy of the SQLite file, so
a resolution saved by a user is destroyed by the next deploy. Section 2 names that
exact practice as no longer appropriate, and this is the fix.

**Transactions are the point of the class.** Section 4's atomic-save rule says a
resolution must update the domain record, transition the Action and append the
audit event in one transaction, and that a partial save is not acceptable. So
`tx()` is the only way to write, it is a context manager, and it rolls back on any
exception. Nothing in `ops` calls `commit()` by hand.

**Placeholders differ, so they are generated.** SQLite wants `?` and Postgres
wants `%s`. Rather than writing every statement twice, queries are written with
`?` and rewritten once at execution. It is a small trick and it is the only
dialect-specific code in the module.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path

# --------------------------------------------------------------------------
# engines
# --------------------------------------------------------------------------

SQLITE = "sqlite"
POSTGRES = "postgres"


def database_url() -> str:
    """The configured Postgres URL, or empty for local SQLite.

    Read from the environment on every call rather than cached, so a deployment
    that injects it late still finds it.
    """
    for key in ("DATABASE_URL", "POSTGRES_URL", "POSTGRES_PRISMA_URL",
                "CLARA_DATABASE_URL"):
        v = (os.environ.get(key) or "").strip()
        if v.startswith(("postgres://", "postgresql://")):
            return v
    return ""


def _psycopg():
    """The Postgres driver, if installed. Absence is reported, never guessed."""
    try:
        import psycopg                     # psycopg 3
        return psycopg, 3
    except ImportError:
        pass
    try:
        import psycopg2                    # psycopg 2
        return psycopg2, 2
    except ImportError:
        return None, 0


def engine_status() -> dict:
    """Which backend is in use and whether it satisfies section 9.

    Put on the Admin page verbatim. A deployment that silently fell back to an
    ephemeral file while believing it was durable is the failure section 9 exists
    to prevent, so the answer is stated rather than assumed.
    """
    url = database_url()
    drv, ver = _psycopg()
    if url and drv:
        host = re.sub(r"//[^@]*@", "//", url).split("?")[0]
        return {"engine": POSTGRES, "durable": True, "driver": f"psycopg{ver}",
                "target": host,
                "why": "operational writes go to a managed PostgreSQL database, "
                       "so they survive restarts, instance recycling and "
                       "redeployment"}
    if url and not drv:
        return {"engine": SQLITE, "durable": False, "driver": "",
                "target": "local file",
                "why": "DATABASE_URL is set but no PostgreSQL driver is "
                       "installed, so writes are going to the local file "
                       "instead. Install psycopg[binary] — until then this "
                       "deployment does not meet the durability requirement."}
    return {"engine": SQLITE, "durable": False, "driver": "sqlite3",
            "target": "local file",
            "why": "no DATABASE_URL is configured, so operational writes go to "
                   "the local SQLite file. That is correct for local work and "
                   "does not meet section 9 for a hosted deployment, where an "
                   "instance-local file is not a system of record."}


# --------------------------------------------------------------------------
# the connection
# --------------------------------------------------------------------------

_PLACEHOLDER = re.compile(r"\?")


class Db:
    """One connection, two dialects, transactions only.

    Not thread-safe by design — each request or job takes its own. A shared
    connection with a lock would serialise the whole application on the slowest
    query, and the lock would not save us from a half-applied transaction.
    """

    def __init__(self, sqlite_path: Path | str | None = None,
                 url: str | None = None):
        self.url = url if url is not None else database_url()
        drv, ver = _psycopg()
        if self.url and drv:
            self.engine = POSTGRES
            self._drv = drv
            self.conn = (drv.connect(self.url, autocommit=False) if ver == 3
                         else drv.connect(self.url))
        else:
            self.engine = SQLITE
            self._drv = sqlite3
            path = Path(sqlite_path) if sqlite_path else None
            if path is None:
                from ..config import DB_PATH
                path = Path(DB_PATH)
            path.parent.mkdir(parents=True, exist_ok=True)
            self.conn = sqlite3.connect(str(path), isolation_level=None)
            self.conn.row_factory = sqlite3.Row
            self.conn.execute("PRAGMA journal_mode=WAL")
            # Foreign keys are off by default in SQLite, which would make the
            # foreign-key requirement in 9.2 decorative.
            self.conn.execute("PRAGMA foreign_keys=ON")
        self._depth = 0
        self._lock = threading.RLock()

    # ---------------- dialect ----------------

    def sql(self, q: str) -> str:
        """Rewrite a `?`-style query for the active engine.

        Two substitutions, in this order. A literal `%` in the SQL text is
        doubled first, because psycopg treats `%` as the start of a placeholder
        and refuses anything that is not one of its own — so an inline
        `LIKE 'ops_%'` would raise on Postgres while working perfectly on
        SQLite. Then `?` becomes `%s`.

        Escaping before substituting matters: doing it the other way round would
        double the `%` this method just inserted.
        """
        if self.engine == POSTGRES:
            return _PLACEHOLDER.sub("%s", q.replace("%", "%%"))
        return q

    def ddl(self, q: str) -> str:
        """Rewrite portable DDL for the active engine.

        The schema is written in SQLite's spelling because that is the local
        default, and the handful of words Postgres spells differently are
        translated here rather than maintained as a second schema file.
        """
        if self.engine != POSTGRES:
            return q
        out = q
        out = re.sub(r"\bINTEGER\s+PRIMARY\s+KEY\s+AUTOINCREMENT\b",
                     "BIGSERIAL PRIMARY KEY", out, flags=re.I)
        out = re.sub(r"\bBLOB\b", "BYTEA", out, flags=re.I)
        out = re.sub(r"\bAUTOINCREMENT\b", "", out, flags=re.I)
        return out

    # ---------------- reading ----------------

    def rows(self, q: str, args: tuple | list = ()) -> list:
        cur = self.conn.cursor()
        try:
            cur.execute(self.sql(q), tuple(args))
            cols = [d[0] for d in (cur.description or [])]
            return [dict(zip(cols, r)) for r in cur.fetchall()]
        finally:
            cur.close()

    def row(self, q: str, args: tuple | list = ()) -> dict | None:
        out = self.rows(q, args)
        return out[0] if out else None

    def value(self, q: str, args: tuple | list = (), default=None):
        r = self.row(q, args)
        return next(iter(r.values()), default) if r else default

    # ---------------- writing ----------------

    @contextmanager
    def tx(self):
        """The only way to write. Commits on success, rolls back on anything else.

        Re-entrant: a nested `tx()` joins the outer one rather than opening a
        second, so a resolution helper can be called from inside a larger
        transaction without splitting the atomic save that section 4 requires
        into two.
        """
        with self._lock:
            outer = self._depth == 0
            if outer and self.engine == SQLITE:
                self.conn.execute("BEGIN")
            self._depth += 1
            try:
                yield self
            except Exception:
                self._depth -= 1
                if self._depth == 0:
                    try:
                        self.conn.rollback()
                    except Exception:
                        pass
                raise
            else:
                self._depth -= 1
                if self._depth == 0:
                    self.conn.commit()

    def exec(self, q: str, args: tuple | list = ()) -> None:
        """One statement inside an open transaction.

        Refuses to run outside one. An operational write that quietly
        auto-committed would defeat the atomic-save rule in the one place it
        matters most, so this is a hard error rather than a warning.
        """
        if self._depth == 0:
            raise RuntimeError(
                "ops writes must run inside db.tx(): section 4 requires the "
                "domain update, the status transition and the audit event to "
                "commit together or not at all")
        cur = self.conn.cursor()
        try:
            cur.execute(self.sql(q), tuple(args))
        finally:
            cur.close()

    def exec_many(self, q: str, rows: list) -> None:
        if self._depth == 0:
            raise RuntimeError("ops writes must run inside db.tx()")
        if not rows:
            return
        cur = self.conn.cursor()
        try:
            cur.executemany(self.sql(q), [tuple(r) for r in rows])
        finally:
            cur.close()

    def script(self, ddl: str) -> None:
        """Schema only. Runs statement by statement so both engines accept it.

        Line comments are stripped before splitting. This is not tidiness: the
        schema's comments are prose, prose contains semicolons, and splitting a
        commented script on `;` cuts a statement in half mid-sentence. The first
        run of this failed with `near "this": syntax error` because a comment read
        "…stay in app_user; this is the…".
        """
        body = re.sub(r"--[^\n]*", "", self.ddl(ddl))
        cur = self.conn.cursor()
        try:
            for stmt in [s.strip() for s in body.split(";")]:
                if stmt:
                    cur.execute(stmt)
            self.conn.commit()
        finally:
            cur.close()

    def table_exists(self, name: str) -> bool:
        if self.engine == POSTGRES:
            return bool(self.value(
                "SELECT 1 FROM information_schema.tables "
                "WHERE table_schema='public' AND table_name=?", (name,)))
        return bool(self.value(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (name,)))

    def columns(self, name: str) -> set:
        if self.engine == POSTGRES:
            return {r["column_name"] for r in self.rows(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema='public' AND table_name=?", (name,))}
        return {r["name"] for r in self.rows(f"PRAGMA table_info({name})")}

    def close(self) -> None:
        try:
            self.conn.close()
        except Exception:
            pass


# --------------------------------------------------------------------------
# json helpers
# --------------------------------------------------------------------------

def dumps(v) -> str:
    """JSON as text. Stored as text on both engines deliberately.

    Postgres has jsonb and it is better, but using it would mean the two backends
    no longer accept the same statements, and a query that works locally and
    fails in production is a worse problem than a missing index.
    """
    return json.dumps(v, ensure_ascii=False, default=str)


def loads(v, fallback=None):
    if v in (None, "", b""):
        return fallback if fallback is not None else {}
    if isinstance(v, (dict, list)):
        return v
    try:
        return json.loads(v)
    except (ValueError, TypeError):
        return fallback if fallback is not None else {}
