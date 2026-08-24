"""Section 9.2, last line: import completed scans into the durable database.

"Redeployment must never reset operational records." That is the requirement this
module exists to satisfy, and it names the exact bug it is fixing: the current
hosted deployment ships a copy of the SQLite file at build time, so anything a
person did through the application is destroyed by the next deploy.

The fix has a shape worth stating, because the obvious version is wrong. You
cannot simply copy the collection database over the operational one — that would
overwrite the human decisions with the automated guesses that preceded them. The
collection run is *evidence*; the operational database holds evidence **and**
resolutions, and the resolutions win.

So the import obeys three rules:

**A human decision is never overwritten by an automated one.** A match a person
confirmed stays confirmed, even if the next scan proposes something else. Where
the scan disagrees with a confirmed match it raises an Action instead — which is
the correct outcome, because a scan disagreeing with a person is exactly the thing
someone should look at.

**Observations are appended, never replaced.** Section 8.2 again. A new scan adds
an observation and supersedes the previous automated one; it does not touch a
manually entered value, which sits alongside with its own provenance.

**Everything imported is attributable.** An `ops_import` row records where it came
from, when, by whom and what it contained, so "why did this price change" has an
answer that includes "because run r7 was imported on Tuesday".

Idempotent: importing the same run twice changes nothing the second time.
"""

from __future__ import annotations

from .actions import Actions
from .audit import Audit, correlation_id, new_id
from .authz import Actor
from .db import Db, dumps, loads
from .schema import (ActionType, ChangeType, MatchStatus, Origin, Provenance,
                     SourceStatus, now_iso)

# How the collection layer's match statuses map onto the operational ones.
STATUS_MAP = {
    "confirmed_match": MatchStatus.CONFIRMED,
    "probable_match": MatchStatus.PROBABLE,
    "ambiguous": MatchStatus.AMBIGUOUS,
    "no_match": MatchStatus.NO_COUNTERPART,
    "blocked": MatchStatus.UNREADABLE,
    "invalidated": MatchStatus.REJECTED,
}

# Statuses a person set. An import may not move a match out of one of these.
HUMAN_HELD = (MatchStatus.CONFIRMED, MatchStatus.NO_COUNTERPART,
              MatchStatus.REJECTED)

# The provenance labels that mean "a person put this value here" (8.2). This is
# the real test of whether an import may touch a match, and status alone is not
# a substitute for it: replacing an unreadable source is a human decision that
# leaves the status where it was, so guarding on status let the next import
# revert the URL a person had just corrected.
HUMAN_SET = (Provenance.HUMAN_CONFIRMED, Provenance.MANUAL)


def match_key(clara_product_id: str, competitor_key: str) -> str:
    """One match per Clara product per competitor. Stable across imports.

    Deliberately excludes the competitor product name and URL: if those changed,
    that is a change to an existing match, not a new match. Keying on them would
    create a second row every time a competitor renamed a product, and the
    history would fork.
    """
    return f"mt{abs(hash((clara_product_id, competitor_key))) % (10 ** 15):015d}"


class Importer:
    """Fold a completed collection run into the durable operational database."""

    def __init__(self, db: Db):
        self.db = db
        self.audit = Audit(db)
        self.actions = Actions(db)

    def import_bundle(self, bundle: dict, *, actor: Actor | None = None,
                      run_id: str = "", source: str = "collection_run",
                      verbose: bool = False) -> dict:
        """Import competitors, matches, sources and observations from a bundle.

        Takes the report bundle the existing pipeline already builds, so nothing
        in the collection layer has to change to feed this.
        """
        actor = actor or Actor.system(Origin.IMPORT)
        run = run_id or ((bundle.get("price") or {}).get("run_id") or "unknown")
        already = self.db.row(
            "SELECT import_id FROM ops_import WHERE source=? AND run_id=?",
            (source, run))
        if already:
            return {"skipped": True, "why": f"run {run} was already imported",
                    "import_id": already["import_id"]}

        corr = correlation_id()
        counts = {"products": 0, "competitors": 0, "matches_new": 0,
                  "matches_updated": 0, "matches_held": 0, "observations": 0,
                  "sources": 0, "actions": 0, "conflicts": 0}

        # Competitors first: matches reference them.
        for c in ((bundle.get("competitors") or {}).get("competitors") or []):
            if self._upsert_competitor(c, actor):
                counts["competitors"] += 1

        # The catalogue, before the matches that point at it. A Clara
        # product with no competitor assigned still has to be listable,
        # because that is the coverage gap someone needs to close.
        with self.db.tx():
            for prod in ((bundle.get("price") or {}).get("products")
                         or []):
                if self._upsert_product(prod, actor):
                    counts["products"] += 1

        for prod in ((bundle.get("price") or {}).get("products") or []):
            for m in (prod.get("matches") or []):
                out = self._import_match(prod, m, actor, corr, verbose)
                for k, v in out.items():
                    counts[k] = counts.get(k, 0) + v

        import_id = new_id("im")
        with self.db.tx():
            self.db.exec(
                "INSERT INTO ops_import (import_id,source,run_id,at,actor,"
                "counts,note) VALUES (?,?,?,?,?,?,?)",
                (import_id, source, run, now_iso(), actor.username,
                 dumps(counts),
                 "collection evidence imported; human resolutions preserved"))
        counts["import_id"] = import_id
        counts["skipped"] = False
        return counts

    # ------------------------------------------------------------------

    def _upsert_product(self, prod: dict, actor: Actor) -> bool:
        """Fold one Clara catalogue product into ops_product. True if new.

        The catalogue is descriptive rather than observed — it is Clara's own
        product list, not a competitor reading — so it carries the OBSERVED
        label and is refreshed in place. Nothing here is a value a person
        resolved, so there is no human decision to protect: the rule that
        matters in `_import_match` does not apply.
        """
        pid = prod.get("product_id") or ""
        if not pid:
            return False
        cur = self.db.row(
            "SELECT clara_product_id, first_seen_at FROM ops_product "
            "WHERE clara_product_id=?", (pid,))
        now = now_iso()
        fields = (
            prod.get("name") or "", prod.get("url") or "",
            prod.get("image_url") or "", prod.get("segment") or "",
            prod.get("category") or "", prod.get("fmt") or "",
            str(prod.get("clara_price")) if prod.get("clara_price") is not None
            else None,
            prod.get("currency") or "", prod.get("rating"),
            prod.get("rating_count"), dumps(prod.get("specs") or {}),
            prod.get("description_lang") or "")
        if cur:
            self.db.exec(
                "UPDATE ops_product SET name=?, url=?, image_url=?, segment=?, "
                "category=?, product_format=?, price=?, currency=?, rating=?, "
                "rating_count=?, specs=?, language=?, last_seen_at=?, "
                "updated_at=? WHERE clara_product_id=?",
                fields + (now, now, pid))
            return False
        self.db.exec(
            "INSERT INTO ops_product (clara_product_id,name,url,image_url,"
            "segment,category,product_format,price,currency,rating,"
            "rating_count,specs,language,provenance,first_seen_at,last_seen_at,"
            "created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (pid,) + fields + (Provenance.OBSERVED, now, now, now, now))
        return True

    def _upsert_competitor(self, c: dict, actor: Actor) -> bool:
        key = c.get("key")
        if not key:
            return False
        exists = self.db.row(
            "SELECT competitor_key FROM ops_competitor WHERE competitor_key=?",
            (key,))
        with self.db.tx():
            if exists:
                self.db.exec(
                    "UPDATE ops_competitor SET brand=?, segments=?, profile=?, "
                    "updated_at=? WHERE competitor_key=?",
                    (c.get("brand") or key, dumps(c.get("segments") or []),
                     dumps(c.get("profile") or {}), now_iso(), key))
                return False
            self.db.exec(
                "INSERT INTO ops_competitor (competitor_key,brand,home_url,"
                "segments,profile,created_at,updated_at) VALUES (?,?,?,?,?,?,?)",
                (key, c.get("brand") or key,
                 (c.get("sites") or [None])[0],
                 dumps(c.get("segments") or []),
                 dumps(c.get("profile") or {}), now_iso(), now_iso()))
        return True

    def _import_match(self, prod: dict, m: dict, actor: Actor, corr: str,
                      verbose: bool) -> dict:
        out = {"matches_new": 0, "matches_updated": 0, "matches_held": 0,
               "observations": 0, "sources": 0, "actions": 0, "conflicts": 0}
        pid = prod.get("product_id") or ""
        ckey = m.get("competitor_key") or m.get("competitor_brand") or ""
        if not pid or not ckey:
            return out

        mid = match_key(pid, ckey)
        incoming = STATUS_MAP.get(m.get("status") or "", MatchStatus.PROBABLE)
        cur = self.db.row("SELECT * FROM ops_match WHERE match_id=?", (mid,))
        url = m.get("competitor_url") or ""
        cp_name = m.get("competitor_product_name") or ""

        with self.db.tx():
            source_id = ""
            if url:
                source_id, created = self._upsert_source(
                    ckey, url, m, actor)
                # Counted only when a row is created. Counting every
                # upsert reported 39 sources for four URLs, and
                # section 12 requires a summary count to reconcile
                # with the records behind it.
                out["sources"] += 1 if created else 0

            if not cur:
                self.db.exec(
                    "INSERT INTO ops_match (match_id,clara_product_id,"
                    "clara_product_name,competitor_key,competitor_product_name,"
                    "competitor_url,status,confidence,score,provenance,"
                    "candidates,version,created_at,updated_at) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (mid, pid, prod.get("name"), ckey, cp_name, url, incoming,
                     self._confidence(m), m.get("match_score"),
                     Provenance.OBSERVED, dumps(m.get("candidates") or []),
                     1, now_iso(), now_iso()))
                self.db.exec(
                    "INSERT INTO ops_match_version (version_id,match_id,version,"
                    "status,confidence,competitor_product_name,competitor_url,"
                    "provenance,actor,at,reason) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    (new_id("mv"), mid, 1, incoming, self._confidence(m),
                     cp_name, url, Provenance.OBSERVED, actor.username,
                     now_iso(), "first observed by an automated run"))
                self.audit.record(
                    actor=actor.username, actor_role=actor.role,
                    change_type=ChangeType.MATCH_RESOLVED, origin=Origin.IMPORT,
                    before=None,
                    after={"status": incoming, "competitor_url": url,
                           "provenance": Provenance.OBSERVED},
                    match_id=mid, clara_product_id=pid, competitor_key=ckey,
                    source_id=source_id,
                    note="imported from a collection run", correlation=corr)
                out["matches_new"] += 1

            elif cur["provenance"] in HUMAN_SET:
                # A person decided this. The import does not get to undo it.
                out["matches_held"] += 1
                disagrees = (
                    incoming != cur["status"]
                    or (url and cur.get("competitor_url")
                        and url != cur["competitor_url"]))
                if disagrees:
                    out["conflicts"] += 1
                    self.actions.open(
                        action_type=ActionType.VERIFICATION_FAILED,
                        reason=(f"An automated run disagrees with a "
                                f"human-confirmed match: the run says "
                                f"{incoming}"
                                + (f" at {url}" if url else "")
                                + f", the confirmed record says {cur['status']}"
                                + (f" at {cur['competitor_url']}"
                                   if cur.get("competitor_url") else "")
                                + ". The confirmation stands until a person "
                                  "reviews it."),
                        priority="high", clara_product_id=pid,
                        clara_product_name=prod.get("name") or "",
                        competitor_key=ckey, match_id=mid,
                        source_id=source_id,
                        evidence=[{"url": url, "note": "what the run observed"}],
                        actor=actor, origin=Origin.IMPORT,
                        correlation=corr)
                    out["actions"] += 1

            elif (incoming != cur["status"] or cp_name != (
                    cur.get("competitor_product_name") or "")
                    or url != (cur.get("competitor_url") or "")):
                _, _, delta = self.audit.new_match_version(
                    mid, status=incoming, provenance=Provenance.OBSERVED,
                    actor=actor.username,
                    reason="re-observed by an automated run",
                    confidence=self._confidence(m),
                    competitor_product_name=cp_name, competitor_url=url)
                self.audit.record(
                    actor=actor.username, actor_role=actor.role,
                    change_type=ChangeType.MATCH_RESOLVED, origin=Origin.IMPORT,
                    before=delta["before"], after=delta["after"],
                    match_id=mid, clara_product_id=pid, competitor_key=ckey,
                    source_id=source_id, note="re-observed", correlation=corr)
                out["matches_updated"] += 1

            # The observation, appended.
            if m.get("competitor_price") is not None:
                obs_id, _ = self.audit.supersede_observation(
                    competitor_key=ckey, actor=actor.username,
                    provenance=Provenance.OBSERVED, match_id=mid,
                    source_id=source_id, source_url=url,
                    price=m.get("competitor_price"),
                    currency=m.get("competitor_currency") or "",
                    was_price=m.get("regular_price"),
                    discount_pct=m.get("discount_percent"),
                    availability=m.get("availability") or "",
                    offer_wording=m.get("promotion_text") or "",
                    observed_at=m.get("observed_at") or now_iso(),
                    note="imported from a collection run")
                out["observations"] += 1

            # Ambiguity is work for a person (4.2), so it becomes an Action.
            if incoming == MatchStatus.AMBIGUOUS:
                self.actions.open(
                    action_type=ActionType.AMBIGUOUS_MATCH,
                    reason=(f"{prod.get('name')} has more than one plausible "
                            f"counterpart at {ckey}; a person needs to choose."),
                    priority="medium", clara_product_id=pid,
                    clara_product_name=prod.get("name") or "",
                    competitor_key=ckey, match_id=mid, source_id=source_id,
                    candidates=self._candidates(m),
                    evidence=[{"url": url, "note": cp_name}] if url else [],
                    actor=actor, origin=Origin.IMPORT,
                    correlation=corr)
                out["actions"] += 1
            elif incoming == MatchStatus.UNREADABLE:
                self.actions.open(
                    action_type=ActionType.UNREADABLE_SOURCE,
                    reason=(f"The page for {cp_name or ckey} could not be read, "
                            f"so there is no current value for "
                            f"{prod.get('name')}."),
                    priority="high", clara_product_id=pid,
                    clara_product_name=prod.get("name") or "",
                    competitor_key=ckey, match_id=mid, source_id=source_id,
                    failure_reason=(m.get("invalid_reason")
                                    or "the page was not readable"),
                    evidence=[{"url": url, "note": "the URL that failed"}],
                    actor=actor, origin=Origin.IMPORT,
                    correlation=corr)
                out["actions"] += 1
        return out

    def _upsert_source(self, ckey: str, url: str, m: dict,
                       actor: Actor) -> tuple[str, bool]:
        row = self.db.row(
            "SELECT source_id, fail_count FROM ops_source WHERE url=? "
            "AND competitor_key=?", (url, ckey))
        readable = m.get("status") != "blocked"
        if row:
            self.db.exec(
                "UPDATE ops_source SET status=?, last_attempt_at=?, "
                "last_ok_at=COALESCE(?, last_ok_at), fail_count=?, "
                "last_failure=? WHERE source_id=?",
                (SourceStatus.ACTIVE if readable else SourceStatus.UNREADABLE,
                 now_iso(), now_iso() if readable else None,
                 (row["fail_count"] or 0) + (0 if readable else 1),
                 None if readable else (m.get("invalid_reason") or "unreadable"),
                 row["source_id"]))
            return row["source_id"], False
        sid = new_id("sc")
        self.db.exec(
            "INSERT INTO ops_source (source_id,competitor_key,url,kind,status,"
            "status_reason,is_approved,added_by,added_at,last_attempt_at,"
            "last_ok_at,fail_count,last_failure) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (sid, ckey, url, "page",
             SourceStatus.ACTIVE if readable else SourceStatus.UNREADABLE,
             "observed by an automated run", 0, actor.username, now_iso(),
             now_iso(), now_iso() if readable else None,
             0 if readable else 1,
             None if readable else (m.get("invalid_reason") or "unreadable")))
        return sid, True

    @staticmethod
    def _confidence(m: dict) -> str:
        s = m.get("status")
        if s == "confirmed_match":
            return "HIGH"
        if s == "probable_match":
            return "MEDIUM"
        if s == "ambiguous":
            return "LOW"
        return "UNVERIFIED"

    @staticmethod
    def _candidates(m: dict) -> list:
        """The choices a person picks between (4.2).

        A candidate with no URL cannot be checked, so it is not offered: an
        option a person cannot verify is a coin toss dressed as a decision.
        """
        cands = m.get("candidates") or []
        out = []
        for c in cands:
            if isinstance(c, dict) and c.get("url"):
                out.append({"name": c.get("name") or c.get("title") or "unnamed",
                            "url": c["url"], "price": c.get("price"),
                            "currency": c.get("currency"),
                            "score": c.get("score"),
                            "why": c.get("why") or ""})
        if not out and m.get("competitor_url"):
            out.append({"name": m.get("competitor_product_name") or "the observed product",
                        "url": m["competitor_url"],
                        "price": m.get("competitor_price"),
                        "currency": m.get("competitor_currency"),
                        "score": m.get("match_score"),
                        "why": "the only counterpart the run observed"})
        return out


def sync_users(db: Db, auth_users: list, actor: Actor | None = None) -> int:
    """Mirror the authentication users into `ops_user`.

    9.1 lists users, roles and account state among the durable records. The
    passwords stay where they are; this is the operational identity that audit
    rows point at, so a name in an audit trail resolves to a person even after
    that person's account is disabled.
    """
    actor = actor or Actor.system(Origin.IMPORT)
    n = 0
    with db.tx():
        for u in auth_users or []:
            name = u.get("username")
            if not name:
                continue
            role = "admin" if (u.get("is_admin") or u.get("role") == "admin") \
                else "viewer"
            exists = db.row("SELECT username, role FROM ops_user WHERE username=?",
                            (name,))
            if exists:
                if exists["role"] != role:
                    db.exec("UPDATE ops_user SET role=?, display_name=?, "
                            "is_active=? WHERE username=?",
                            (role, u.get("display_name") or name,
                             1 if u.get("is_active", 1) else 0, name))
                    db.exec(
                        "INSERT INTO ops_role_grant (grant_id,username,role,"
                        "granted_at,granted_by,note) VALUES (?,?,?,?,?,?)",
                        (new_id("gr"), name, role, now_iso(), actor.username,
                         "synchronised from the authentication store"))
                    Audit(db).record(
                        actor=actor.username, actor_role=actor.role,
                        change_type=ChangeType.USER_ROLE_CHANGED,
                        origin=Origin.IMPORT,
                        before={"role": exists["role"]}, after={"role": role},
                        note=f"role for {name} synchronised")
                continue
            db.exec(
                "INSERT INTO ops_user (username,display_name,role,is_active,"
                "created_at,created_by,last_login_at) VALUES (?,?,?,?,?,?,?)",
                (name, u.get("display_name") or name, role,
                 1 if u.get("is_active", 1) else 0,
                 u.get("created_at") or now_iso(), u.get("created_by") or "sync",
                 u.get("last_login_at")))
            db.exec("INSERT INTO ops_role_grant (grant_id,username,role,"
                    "granted_at,granted_by,note) VALUES (?,?,?,?,?,?)",
                    (new_id("gr"), name, role, now_iso(), actor.username,
                     "initial synchronisation"))
            n += 1
    return n
