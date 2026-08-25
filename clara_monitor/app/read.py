"""Read models for the five tabs. Every number on screen is defined here.

Section 10 asks for two things this module exists to make possible: "define every
summary count and reconcile summary totals with detailed records", and "prioritize
Needs attention, freshness and incomplete coverage above descriptive report
metrics". Section 12 turns the first into a test.

So no page computes a count. Each one is a function here, each returns the number
**and the sentence that defines it**, and each definition names the rows it counts
so a reader can click through and land on exactly that set. Where a count and a
list could disagree, they are built from the same query.

Two definitions are worth stating up front, because they are the ones that are
easy to get quietly wrong.

**A price movement** is a change in price between the two most recent
observations of the same match. It is *verified* when the newer of the two is
human-confirmed or came from an approved feed — that is 8.2's vocabulary, not a
new one. Both numbers are reported, because "3 verified movements" alone invites
the reader to assume there were only three.

**An offer** is counted twice, on purpose. `unique` counts distinct offer wording
per competitor; `associations` counts the product-level rows carrying it. Section
12 requires those to be clearly distinguished, because one promotion spanning
nine products is one offer and nine associations, and reporting nine offers is a
nine-fold overstatement of what a competitor is running.

Everything reads from `ops_*` — the durable operational tables — because section 1
makes the application database the system of record. Nothing here reads a report
file.
"""

from __future__ import annotations

from ..ops import (ACTION_STATUS_LABEL, ACTION_TYPE_LABEL, ActionStatus,
                   MATCH_STATUS_LABEL, MatchStatus, Provenance,
                   REQUEST_STATUS_LABEL, RequestStatus)
from ..ops.agent import freshness
from ..ops.db import Db, loads

# A price with an age past this is not treated as current. The same window the
# agent uses, imported rather than restated so the two cannot drift.
from ..ops.agent import STALE_DAYS

OPEN_ACTION_SQL = ("status IN ('" + "','".join(
    (ActionStatus.OPEN, ActionStatus.IN_PROGRESS, ActionStatus.WAITING)) + "')")

VERIFIED_PROV = (Provenance.HUMAN_CONFIRMED, Provenance.FEED)

# Which match statuses mean "this product is not actually being compared".
UNCOVERED = (MatchStatus.AMBIGUOUS, MatchStatus.UNREADABLE,
             MatchStatus.NO_COUNTERPART, MatchStatus.REJECTED)


# --------------------------------------------------------------------------
# navigation counts
# --------------------------------------------------------------------------

def tab_counts(db: Db, actor) -> dict:
    """The numbers on the tabs. Open work, and requests needing this reader."""
    actions = db.value(f"SELECT COUNT(*) FROM ops_action WHERE {OPEN_ACTION_SQL}",
                       (), 0) or 0
    if getattr(actor, "is_admin", False):
        reqs = db.value(
            "SELECT COUNT(*) FROM ops_request WHERE status IN (?,?)",
            (RequestStatus.NEW, RequestStatus.IN_PROGRESS), 0) or 0
    else:
        # A user's badge counts what is waiting on *them*, not the global queue:
        # a number you cannot act on is noise on a tab you visit every day.
        reqs = db.value(
            "SELECT COUNT(*) FROM ops_request WHERE requester=? "
            "AND status IN (?,?)",
            (actor.username, RequestStatus.WAITING, RequestStatus.RESOLVED),
            0) or 0
    return {"actions": actions, "requests": reqs}


# --------------------------------------------------------------------------
# freshness and coverage
# --------------------------------------------------------------------------

def latest_observations(db: Db) -> list:
    """The current observation for every match that has one.

    "Current" means not superseded. `supersede_observation` maintains that chain,
    so this is the set of values the application would show as today's prices.
    """
    return db.rows(
        "SELECT o.* FROM ops_observation o WHERE o.superseded_by IS NULL "
        "ORDER BY o.observed_at DESC")


def freshness_summary(db: Db) -> dict:
    """How old the current values are, in the four states of `ops.agent`."""
    rows = latest_observations(db)
    buckets = {"fresh": 0, "recent": 0, "stale": 0, "unknown": 0}
    newest = ""
    for r in rows:
        f = freshness(r.get("observed_at"))
        buckets[f["state"]] = buckets.get(f["state"], 0) + 1
        if (r.get("observed_at") or "") > newest:
            newest = r.get("observed_at") or ""
    total = sum(buckets.values())
    return {
        "buckets": buckets, "total": total, "newest": newest,
        "stale_days": STALE_DAYS,
        "definition": (
            f"Counts the current (not superseded) observation of each match: "
            f"{total} in total. Fresh is within two days, recent is within "
            f"{STALE_DAYS} days, stale is older than that, and age unknown "
            f"means no observation date was recorded."),
    }


def coverage_summary(db: Db) -> dict:
    """Incomplete coverage, which section 10 ranks above descriptive metrics."""
    products = db.value("SELECT COUNT(*) FROM ops_product", (), 0) or 0
    with_match = db.value(
        "SELECT COUNT(DISTINCT clara_product_id) FROM ops_match", (), 0) or 0
    comparable = db.value(
        "SELECT COUNT(DISTINCT m.clara_product_id) FROM ops_match m "
        "JOIN ops_observation o ON o.match_id = m.match_id "
        "WHERE o.superseded_by IS NULL AND o.price IS NOT NULL "
        "AND m.status IN (?,?)",
        (MatchStatus.CONFIRMED, MatchStatus.PROBABLE), 0) or 0
    unassigned = max(0, products - with_match)
    return {
        "products": products, "with_match": with_match,
        "comparable": comparable, "unassigned": unassigned,
        "priced_gap": max(0, with_match - comparable),
        "definition": (
            f"{products} Clara products are in the catalogue. {with_match} have "
            f"at least one competitor match of any status; {unassigned} have "
            f"none at all. {comparable} have a confirmed or probable match with "
            f"a current price, which is the only set where a comparison can "
            f"actually be made."),
    }


# --------------------------------------------------------------------------
# price movement
# --------------------------------------------------------------------------

IN_STOCK_WORDS = ("in_stock", "instock", "in stock", "available",
                  "availability_in_stock", "http://schema.org/instock")
OUT_WORDS = ("out_of_stock", "outofstock", "out of stock", "sold_out",
             "soldout", "sold out", "unavailable",
             "http://schema.org/outofstock")


def _in_stock(v: str) -> bool:
    return (v or "").strip().lower() in IN_STOCK_WORDS


def _out_of_stock(v: str) -> bool:
    return (v or "").strip().lower() in OUT_WORDS


def _num(v):
    try:
        return float(str(v).replace(",", ""))
    except (TypeError, ValueError, AttributeError):
        return None


def price_movements(db: Db, *, limit: int = 40) -> dict:
    """Changes in price between a match's two most recent observations.

    Deliberately built from observations rather than from a "previous price"
    column, because 8.2 forbids overwriting: the earlier value is still a row,
    so the movement is a fact in the data rather than a derived guess.
    """
    rows = db.rows(
        "SELECT o.*, m.clara_product_id, m.clara_product_name, "
        "m.competitor_key, m.status AS match_status "
        "FROM ops_observation o LEFT JOIN ops_match m ON m.match_id=o.match_id "
        "WHERE o.match_id IS NOT NULL ORDER BY o.match_id, o.observed_at DESC")
    by_match: dict = {}
    for r in rows:
        by_match.setdefault(r["match_id"], []).append(r)

    moves = []
    for mid, obs in by_match.items():
        if len(obs) < 2:
            continue
        new, old = obs[0], obs[1]
        a, b = _num(new.get("price")), _num(old.get("price"))
        if a is None or b is None or a == b:
            continue
        if (new.get("currency") or "") != (old.get("currency") or ""):
            # Cross-currency is not a movement, it is a different measurement.
            continue
        moves.append({
            "match_id": mid, "clara_product_id": new.get("clara_product_id"),
            "clara_product_name": new.get("clara_product_name"),
            "competitor_key": new.get("competitor_key"),
            "currency": new.get("currency"), "new_price": a, "old_price": b,
            "delta": a - b, "delta_pct": ((a - b) / b * 100.0) if b else None,
            "observed_at": new.get("observed_at"),
            "previous_at": old.get("observed_at"),
            "provenance": new.get("provenance"),
            "verified": new.get("provenance") in VERIFIED_PROV,
            "source_url": new.get("source_url"),
            "freshness": freshness(new.get("observed_at")),
        })
    moves.sort(key=lambda m: (m["observed_at"] or ""), reverse=True)
    verified = [m for m in moves if m["verified"]]
    return {
        "rows": moves[:limit], "total": len(moves), "verified": len(verified),
        "verified_rows": verified[:limit],
        "definition": (
            f"A movement is a change in price between the two most recent "
            f"observations of the same match, in the same currency: "
            f"{len(moves)} in total. {len(verified)} are verified, meaning the "
            f"newer observation is human-confirmed or came from an approved "
            f"feed rather than only automatically observed."),
    }


# --------------------------------------------------------------------------
# offers
# --------------------------------------------------------------------------

def offers(db: Db, *, competitor: str = "", limit: int = 200,
           offset: int = 0) -> dict:
    """Promotions read on competitor pages, counted two ways (12).

    One promotion running across nine products is one offer and nine
    associations. Reporting nine offers would overstate what the competitor is
    actually running by nine times, so both numbers are returned and the caller
    is expected to show both.
    """
    args: list = []
    where = ["o.superseded_by IS NULL", "o.offer_wording IS NOT NULL",
             "o.offer_wording <> ''"]
    if competitor:
        where.append("o.competitor_key=?")
        args.append(competitor)
    sql = ("SELECT o.*, m.clara_product_id, m.clara_product_name "
           "FROM ops_observation o "
           "LEFT JOIN ops_match m ON m.match_id=o.match_id "
           "WHERE " + " AND ".join(where) + " ORDER BY o.observed_at DESC")
    rows = db.rows(sql, tuple(args))

    grouped: dict = {}
    for r in rows:
        key = ((r.get("competitor_key") or ""),
               (r.get("offer_wording") or "").strip().lower())
        g = grouped.setdefault(key, {
            "competitor_key": r.get("competitor_key"),
            "wording": (r.get("offer_wording") or "").strip(),
            "products": [], "observed_at": r.get("observed_at"),
            "provenance": r.get("provenance"), "source_url": r.get("source_url"),
            "currency": r.get("currency"),
            # The observation that carried this wording. 5.2 lets a Request
            # attach to an offer, and this is the record it attaches to — there
            # is no separate offer table, because a promotion is something read
            # off a page at a moment in time.
            "obs_id": r.get("obs_id"),
        })
        if r.get("clara_product_id"):
            g["products"].append({
                "clara_product_id": r["clara_product_id"],
                "name": r.get("clara_product_name"),
                "price": r.get("price"), "currency": r.get("currency"),
                "match_id": r.get("match_id"), "obs_id": r.get("obs_id"),
            })
        if (r.get("observed_at") or "") > (g["observed_at"] or ""):
            g["observed_at"] = r.get("observed_at")

    uniq = list(grouped.values())
    for g in uniq:
        g["association_count"] = len(g["products"])
        g["freshness"] = freshness(g["observed_at"])
    uniq.sort(key=lambda g: (g["observed_at"] or ""), reverse=True)
    active = [g for g in uniq if g["freshness"]["state"] in ("fresh", "recent")]
    return {
        "rows": uniq[offset:offset + limit], "unique": len(uniq),
        "associations": len(rows), "active": len(active),
        "total": len(uniq), "limit": limit, "offset": offset,
        "definition": (
            f"{len(uniq)} unique offers — distinct promotion wording per "
            f"competitor — carried by {len(rows)} product-level associations. "
            f"One promotion spanning several products is one offer and several "
            f"associations. {len(active)} are active, meaning last observed "
            f"within {STALE_DAYS} days."),
    }


# --------------------------------------------------------------------------
# products
# --------------------------------------------------------------------------

PRODUCT_SORTS = {
    "attention": "attention",
    "name": "name",
    "price_desc": "price desc",
    "price_asc": "price asc",
    "coverage": "coverage",
    "freshness": "freshness",
}


def product_rows(db: Db) -> list:
    """Every Clara product with its matches, observations and attention state.

    Assembled in Python rather than in one wide join because the attention state
    depends on the *set* of a product's matches, and because the same assembled
    row feeds the list, the counts and the detail page — which is how a count
    and the list beneath it are kept from disagreeing.
    """
    products = db.rows("SELECT * FROM ops_product ORDER BY name")
    known = {p["clara_product_id"] for p in products}

    # A match may point at a product the catalogue import has not reached. It is
    # still real work, so it appears rather than being silently dropped.
    for r in db.rows(
            "SELECT DISTINCT clara_product_id, clara_product_name "
            "FROM ops_match"):
        if r["clara_product_id"] not in known:
            products.append({
                "clara_product_id": r["clara_product_id"],
                "name": r.get("clara_product_name") or r["clara_product_id"],
                "provenance": Provenance.OBSERVED, "orphan": True,
            })

    matches: dict = {}
    for m in db.rows("SELECT * FROM ops_match"):
        matches.setdefault(m["clara_product_id"], []).append(m)

    obs: dict = {}
    for o in db.rows("SELECT * FROM ops_observation WHERE superseded_by IS NULL"):
        if o.get("match_id"):
            obs[o["match_id"]] = o

    open_actions: dict = {}
    for a in db.rows(f"SELECT * FROM ops_action WHERE {OPEN_ACTION_SQL}"):
        if a.get("clara_product_id"):
            open_actions.setdefault(a["clara_product_id"], []).append(a)

    out = []
    for p in products:
        pid = p["clara_product_id"]
        ms = matches.get(pid, [])
        acts = open_actions.get(pid, [])
        rivals = []
        for m in ms:
            o = obs.get(m["match_id"])
            rivals.append({
                "match": m, "observation": o,
                "price": _num((o or {}).get("price")),
                "currency": (o or {}).get("currency") or "",
                "availability": ((o or {}).get("availability") or "").strip(),
                "freshness": freshness((o or {}).get("observed_at")),
                "provenance": ((o or {}).get("provenance")
                               or m.get("provenance")),
            })
        priced = [r for r in rivals
                  if r["price"] is not None
                  and r["match"]["status"] in (MatchStatus.CONFIRMED,
                                               MatchStatus.PROBABLE)]
        clara_price = _num(p.get("price"))
        cur = p.get("currency") or ""
        same_cur = [r for r in priced if r["currency"] == cur]
        cheapest = min(same_cur, key=lambda r: r["price"]) if same_cur else None

        # Attention, in priority order. The reason is carried with the flag
        # because "needs attention" without a reason is not actionable.
        attention, why = "", ""
        if acts:
            attention, why = "action", (
                f"{len(acts)} open action{'s' if len(acts) > 1 else ''} on this "
                f"product")
        elif not ms:
            attention, why = "unassigned", "no competitor is assigned"
        elif any(r["match"]["status"] == MatchStatus.UNREADABLE for r in rivals):
            attention, why = "unreadable", "a source could not be read"
        elif any(r["match"]["status"] == MatchStatus.AMBIGUOUS for r in rivals):
            attention, why = "ambiguous", "a match needs a decision"
        elif priced and all(r["freshness"]["state"] == "stale" for r in priced):
            attention, why = "stale", "every current price is stale"
        elif not priced:
            attention, why = "no_price", (
                "matches exist but none has a usable current price")

        out.append({
            "product": p, "product_id": pid,
            "name": p.get("name") or pid,
            "clara_price": clara_price, "currency": cur,
            "segment": p.get("segment") or "", "category": p.get("category") or "",
            "image_url": p.get("image_url") or "", "url": p.get("url") or "",
            "rivals": rivals, "priced": priced, "cheapest": cheapest,
            "match_count": len(ms), "priced_count": len(priced),
            "open_actions": acts, "attention": attention, "attention_why": why,
            "gap_pct": ((cheapest["price"] - clara_price) / clara_price * 100.0
                        if cheapest and clara_price else None),
            "freshest": max((r["freshness"] for r in rivals),
                            key=lambda f: {"fresh": 3, "recent": 2, "stale": 1,
                                           "unknown": 0}[f["state"]],
                            default=freshness(None)),
            "cross_currency": bool(priced) and any(
                r["currency"] != cur for r in priced),
            # Section 3 lists availability among the Products tab's contents, so
            # it is summarised on the row rather than only on the detail page.
            # Counted over the rivals that have a current observation, because
            # "0 in stock" and "nobody looked" are different facts.
            "in_stock": sum(1 for r in rivals if _in_stock(r["availability"])),
            "out_of_stock": sum(1 for r in rivals
                                if _out_of_stock(r["availability"])),
            "availability_known": sum(1 for r in rivals if r["availability"]),
        })
    return out


def product_list(db: Db, *, q: str = "", attention: str = "",
                 status: str = "", competitor: str = "", segment: str = "",
                 sort: str = "attention", limit: int = 50,
                 offset: int = 0) -> dict:
    rows = product_rows(db)
    all_rows = rows

    if q:
        low = q.lower()
        rows = [r for r in rows
                if low in (r["name"] or "").lower()
                or low in (r["product_id"] or "").lower()]
    if attention:
        rows = ([r for r in rows if r["attention"]] if attention == "any"
                else [r for r in rows if r["attention"] == attention])
    if status:
        rows = [r for r in rows
                if any(x["match"]["status"] == status for x in r["rivals"])]
    if competitor:
        rows = [r for r in rows
                if any(x["match"]["competitor_key"] == competitor
                       for x in r["rivals"])]
    if segment:
        rows = [r for r in rows if r["segment"] == segment]

    ATTN_RANK = {"action": 0, "unreadable": 1, "ambiguous": 2, "stale": 3,
                 "no_price": 4, "unassigned": 5, "": 9}
    if sort == "name":
        rows.sort(key=lambda r: (r["name"] or "").lower())
    elif sort == "price_desc":
        rows.sort(key=lambda r: (r["clara_price"] is None,
                                 -(r["clara_price"] or 0)))
    elif sort == "price_asc":
        rows.sort(key=lambda r: (r["clara_price"] is None,
                                 r["clara_price"] or 0))
    elif sort == "coverage":
        rows.sort(key=lambda r: (r["priced_count"], r["match_count"]))
    elif sort == "freshness":
        order = {"stale": 0, "unknown": 1, "recent": 2, "fresh": 3}
        rows.sort(key=lambda r: order[r["freshest"]["state"]])
    else:
        # Needs attention first (10), then the least-covered.
        rows.sort(key=lambda r: (ATTN_RANK.get(r["attention"], 9),
                                 r["priced_count"], (r["name"] or "").lower()))

    counts = {"total": len(all_rows), "matched": len(rows)}
    for key in ("action", "unreadable", "ambiguous", "stale", "no_price",
                "unassigned"):
        counts[key] = sum(1 for r in all_rows if r["attention"] == key)
    counts["attention"] = sum(1 for r in all_rows if r["attention"])
    counts["clear"] = counts["total"] - counts["attention"]
    return {"rows": rows[offset:offset + limit], "total": len(rows),
            "limit": limit, "offset": offset, "counts": counts,
            "definition": (
                f"{counts['total']} products in the catalogue, "
                f"{counts['attention']} needing attention and "
                f"{counts['clear']} with nothing outstanding. Attention means "
                f"an open action, no competitor assigned, an unreadable source, "
                f"an undecided match, no usable price, or every price stale.")}


def product_detail(db: Db, product_id: str) -> dict | None:
    """One product, everything about it, as a routable record (3.1)."""
    for r in product_rows(db):
        if r["product_id"] == product_id:
            break
    else:
        return None

    hist: dict = {}
    for o in db.rows(
            "SELECT o.*, m.competitor_key FROM ops_observation o "
            "LEFT JOIN ops_match m ON m.match_id=o.match_id "
            "WHERE m.clara_product_id=? ORDER BY o.observed_at DESC",
            (product_id,)):
        hist.setdefault(o["match_id"], []).append(o)
    r["observation_history"] = hist
    r["specs"] = loads(r["product"].get("specs"), {}) or {}
    r["audit"] = db.rows(
        "SELECT * FROM ops_audit WHERE clara_product_id=? "
        "ORDER BY at DESC LIMIT 60", (product_id,))
    r["requests"] = db.rows(
        "SELECT request_id, request_type, subject, status, requester, created_at "
        "FROM ops_request WHERE context LIKE ? ORDER BY created_at DESC LIMIT 20",
        (f'%"clara_product_id": "{product_id}"%',))
    r["all_actions"] = db.rows(
        "SELECT * FROM ops_action WHERE clara_product_id=? "
        "ORDER BY created_at DESC LIMIT 40", (product_id,))
    return r


# --------------------------------------------------------------------------
# competitors
# --------------------------------------------------------------------------

def competitor_rows(db: Db) -> list:
    comps = db.rows("SELECT * FROM ops_competitor ORDER BY brand")
    known = {c["competitor_key"] for c in comps}
    for r in db.rows("SELECT DISTINCT competitor_key FROM ops_match"):
        if r["competitor_key"] and r["competitor_key"] not in known:
            comps.append({"competitor_key": r["competitor_key"],
                          "brand": r["competitor_key"], "orphan": True})

    m_by: dict = {}
    for m in db.rows("SELECT * FROM ops_match"):
        m_by.setdefault(m["competitor_key"], []).append(m)
    o_by: dict = {}
    for o in db.rows("SELECT * FROM ops_observation WHERE superseded_by IS NULL"):
        o_by.setdefault(o["competitor_key"], []).append(o)
    s_by: dict = {}
    for s in db.rows("SELECT * FROM ops_source"):
        s_by.setdefault(s["competitor_key"], []).append(s)
    a_by: dict = {}
    for a in db.rows(f"SELECT * FROM ops_action WHERE {OPEN_ACTION_SQL}"):
        a_by.setdefault(a.get("competitor_key"), []).append(a)
    f_by: dict = {}
    for f in db.rows("SELECT * FROM ops_feed"):
        f_by.setdefault(f.get("competitor_key"), []).append(f)

    out = []
    for c in comps:
        key = c["competitor_key"]
        ms = m_by.get(key, [])
        os_ = o_by.get(key, [])
        srcs = s_by.get(key, [])
        prices = [_num(o.get("price")) for o in os_]
        prices = [p for p in prices if p is not None]
        newest = max((o.get("observed_at") or "") for o in os_) if os_ else ""
        offer_wordings = {(o.get("offer_wording") or "").strip().lower()
                          for o in os_ if (o.get("offer_wording") or "").strip()}
        broken = [s for s in srcs
                  if s.get("status") in ("unreadable", "unavailable")]
        out.append({
            "competitor": c, "key": key,
            "brand": c.get("brand") or key,
            "home_url": c.get("home_url") or "",
            "segments": [s for s in (c.get("segments") or "").split(",") if s],
            "matches": ms, "match_count": len(ms),
            "compared": sum(1 for m in ms if m["status"] in (
                MatchStatus.CONFIRMED, MatchStatus.PROBABLE)),
            "undecided": sum(1 for m in ms
                             if m["status"] == MatchStatus.AMBIGUOUS),
            "observations": os_, "observed_count": len(os_),
            "price_min": min(prices) if prices else None,
            "price_max": max(prices) if prices else None,
            "currencies": sorted({(o.get("currency") or "") for o in os_
                                  if o.get("currency")}),
            "sources": srcs, "source_count": len(srcs),
            "broken_sources": broken,
            "feeds": f_by.get(key, []),
            "offers_unique": len(offer_wordings),
            "offer_associations": sum(
                1 for o in os_ if (o.get("offer_wording") or "").strip()),
            "open_actions": a_by.get(key, []),
            "last_observed_at": newest,
            "freshness": freshness(newest),
            "in_stock": sum(1 for o in os_
                            if (o.get("availability") or "").lower()
                            in ("in_stock", "instock", "in stock", "available")),
        })
    return out


COMPETITOR_SORTS = {
    "attention": "Needs attention first",
    "name": "Name",
    "observed": "Most observed",
    "freshness": "Oldest evidence",
    "coverage": "Least compared",
    "offers": "Most offers",
}


def competitor_list(db: Db, *, q: str = "", segment: str = "",
                    coverage: str = "", sort: str = "attention",
                    limit: int = 50, offset: int = 0) -> dict:
    rows = competitor_rows(db)
    all_rows = rows
    if q:
        low = q.lower()
        rows = [r for r in rows if low in (r["brand"] or "").lower()
                or low in (r["key"] or "").lower()]
    if segment:
        rows = [r for r in rows if segment in r["segments"]]
    if coverage == "attention":
        rows = [r for r in rows if r["open_actions"] or r["broken_sources"]]
    elif coverage == "unread":
        rows = [r for r in rows if r["broken_sources"]]
    elif coverage == "nothing_observed":
        rows = [r for r in rows if not r["observed_count"]]
    elif coverage == "observed":
        rows = [r for r in rows if r["observed_count"]]

    if sort == "name":
        rows.sort(key=lambda r: (r["brand"] or "").lower())
    elif sort == "observed":
        rows.sort(key=lambda r: -r["observed_count"])
    elif sort == "freshness":
        order = {"stale": 0, "unknown": 1, "recent": 2, "fresh": 3}
        rows.sort(key=lambda r: order[r["freshness"]["state"]])
    elif sort == "coverage":
        rows.sort(key=lambda r: (r["compared"], r["match_count"]))
    elif sort == "offers":
        rows.sort(key=lambda r: -r["offers_unique"])
    else:
        rows.sort(key=lambda r: (not (r["open_actions"] or r["broken_sources"]),
                                 -r["observed_count"],
                                 (r["brand"] or "").lower()))
    counts = {
        "total": len(all_rows),
        "observed": sum(1 for r in all_rows if r["observed_count"]),
        "attention": sum(1 for r in all_rows
                         if r["open_actions"] or r["broken_sources"]),
        "broken": sum(1 for r in all_rows if r["broken_sources"]),
    }
    counts["silent"] = counts["total"] - counts["observed"]
    return {"rows": rows[offset:offset + limit], "total": len(rows),
            "limit": limit, "offset": offset, "counts": counts,
            "definition": (
                f"{counts['total']} competitors are on record. "
                f"{counts['observed']} have at least one current observation; "
                f"{counts['silent']} have none. {counts['attention']} need "
                f"attention because of an open action or a source that could "
                f"not be read.")}


def competitor_detail(db: Db, key: str) -> dict | None:
    for r in competitor_rows(db):
        if r["key"] == key:
            break
    else:
        return None
    r["profile"] = loads(r["competitor"].get("profile"), {}) or {}
    r["products"] = db.rows(
        "SELECT * FROM ops_competitor_product WHERE competitor_key=? "
        "ORDER BY name", (key,))
    r["offers"] = offers(db, competitor=key)
    r["audit"] = db.rows(
        "SELECT * FROM ops_audit WHERE competitor_key=? "
        "ORDER BY at DESC LIMIT 60", (key,))
    r["observation_history"] = db.rows(
        "SELECT * FROM ops_observation WHERE competitor_key=? "
        "ORDER BY observed_at DESC LIMIT 80", (key,))
    r["all_actions"] = db.rows(
        "SELECT * FROM ops_action WHERE competitor_key=? "
        "ORDER BY created_at DESC LIMIT 40", (key,))
    return r


# --------------------------------------------------------------------------
# the overview
# --------------------------------------------------------------------------

def overview(db: Db, actor) -> dict:
    """Section 3's Overview, in the order section 10 asks for.

    Attention, freshness and incomplete coverage first; descriptive metrics
    after. Every figure carries the sentence that defines it and a link to the
    records it counts, so nothing on this page is a number the reader has to
    take on trust.
    """
    fresh_s = freshness_summary(db)
    cov = coverage_summary(db)
    moves = price_movements(db)
    off = offers(db)
    prod = product_list(db, limit=0)

    action_counts = db.rows(
        "SELECT status, COUNT(*) AS n FROM ops_action GROUP BY status")
    by_status = {r["status"]: r["n"] for r in action_counts}
    by_type = {r["action_type"]: r["n"] for r in db.rows(
        f"SELECT action_type, COUNT(*) AS n FROM ops_action "
        f"WHERE {OPEN_ACTION_SQL} GROUP BY action_type")}
    open_actions = sum(by_status.get(s, 0) for s in (
        ActionStatus.OPEN, ActionStatus.IN_PROGRESS, ActionStatus.WAITING))

    req_rows = db.rows(
        "SELECT status, COUNT(*) AS n FROM ops_request GROUP BY status")
    req_by = {r["status"]: r["n"] for r in req_rows}
    mine_open = db.value(
        "SELECT COUNT(*) FROM ops_request WHERE requester=? "
        "AND status NOT IN (?,?)",
        (actor.username, RequestStatus.CLOSED, RequestStatus.RESOLVED), 0) or 0
    needs_me = db.value(
        "SELECT COUNT(*) FROM ops_request WHERE requester=? AND status=?",
        (actor.username, RequestStatus.WAITING), 0) or 0

    return {
        "freshness": fresh_s, "coverage": cov, "movements": moves,
        "offers": off, "products": prod,
        "actions": {
            "open": open_actions, "by_status": by_status, "by_type": by_type,
            "unassigned": db.value(
                f"SELECT COUNT(*) FROM ops_action WHERE {OPEN_ACTION_SQL} "
                f"AND (assignee IS NULL OR assignee='')", (), 0) or 0,
            "high": db.value(
                f"SELECT COUNT(*) FROM ops_action WHERE {OPEN_ACTION_SQL} "
                f"AND priority='high'", (), 0) or 0,
            "mine": db.value(
                f"SELECT COUNT(*) FROM ops_action WHERE {OPEN_ACTION_SQL} "
                f"AND assignee=?", (actor.username,), 0) or 0,
            "definition": (
                "Open counts actions whose status is open, in progress or "
                "waiting — everything still requiring a person. Resolved and "
                "dismissed actions are excluded."),
        },
        "requests": {
            "by_status": req_by,
            "open": sum(req_by.get(s, 0) for s in (
                RequestStatus.NEW, RequestStatus.IN_PROGRESS,
                RequestStatus.WAITING)),
            "mine_open": mine_open, "needs_me": needs_me,
            "unowned": db.value(
                "SELECT COUNT(*) FROM ops_request WHERE status=? "
                "AND (owner IS NULL OR owner='')",
                (RequestStatus.NEW,), 0) or 0,
            "definition": (
                "Open counts requests that are New, In progress or Waiting for "
                "information. Needs you counts requests you raised that are "
                "waiting on your reply."),
        },
        "recent_actions": db.rows(
            f"SELECT * FROM ops_action WHERE {OPEN_ACTION_SQL} "
            f"ORDER BY CASE priority WHEN 'high' THEN 0 WHEN 'medium' THEN 1 "
            f"ELSE 2 END, created_at DESC LIMIT 8"),
        "recent_audit": db.rows(
            "SELECT * FROM ops_audit ORDER BY at DESC LIMIT 10"),
        "last_import": db.row("SELECT * FROM ops_import ORDER BY at DESC"),
        "labels": {"action_status": ACTION_STATUS_LABEL,
                   "action_type": ACTION_TYPE_LABEL,
                   "match_status": MATCH_STATUS_LABEL,
                   "request_status": REQUEST_STATUS_LABEL},
    }
