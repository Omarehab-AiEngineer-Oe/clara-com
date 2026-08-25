"""Trend Collection Agent — the one that makes the trends page live.

Everything the trends page shows is fetched by this agent on each scan. There is
no curated list of trends any more: there is a registry of sources, and whatever
those sources published is what the page says.

    fetch feeds -> parse -> gate to beauty -> attach to topics
                -> score momentum -> derive stage -> diff against last scan

**The gate matters more than it looks.** Google Trends publishes a country's
rising searches, not its rising *beauty* searches, so without a relevance gate the
page fills with football fixtures. A query only becomes evidence if it touches
beauty at all, and only becomes evidence *for a topic* if it matches that topic.
Queries that pass the beauty gate but match no topic are still counted — they are
how a subject nobody has a pattern for yet becomes visible.

**Stage is derived, never assigned.** The five stages come from three things the
scan can actually measure: how many distinct publishers carried the topic, over
how long, and whether this week is heavier than the weeks before it.

    emerging    one or two publishers, all of it recent
    rising      several publishers, and accelerating
    viral       many publishers inside a short window
    mainstream  sustained across many publishers over a long span
    declining   was heavier before than it is now

That is a real measurement of press and search attention. It is not a measurement
of sales, and the page says so — inferring commercial success from coverage is the
most common way a trend report becomes confidently wrong.

**Nothing is bypassed.** Every fetch goes through `access.guarded_get`. Publishers
that refuse are recorded with the signal and surfaced on the page, so a thin scan
reads as a thin scan rather than as a quiet market.
"""

from __future__ import annotations

import html as _html
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

from .. import access, trend_sources as ts
from .base import Agent
from .contracts import Confidence, Evidence, now_iso

EMERGING, RISING, VIRAL, MAINSTREAM, DECLINING = (
    "emerging", "rising", "viral", "mainstream", "declining")
STAGE_ORDER = [EMERGING, RISING, VIRAL, MAINSTREAM, DECLINING]

LOCAL, REGIONAL, GLOBAL_SPREAD, MOVING = "local", "regional", "global", "moving"

_NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "dc": "http://purl.org/dc/elements/1.1/",
    "ht": "https://trends.google.com/trending/rss",
    "content": "http://purl.org/rss/1.0/modules/content/",
}


# --------------------------------------------------------------------------
# parsing
# --------------------------------------------------------------------------

def _text(node, *paths) -> str:
    for path in paths:
        found = node.find(path, _NS)
        if found is not None and (found.text or "").strip():
            return (found.text or "").strip()
        if found is not None and found.get("href"):
            return found.get("href").strip()
    return ""


def _strip(markup: str) -> str:
    if not markup:
        return ""
    out = re.sub(r"<[^>]+>", " ", markup)
    out = _html.unescape(out)
    return re.sub(r"\s+", " ", out).strip()


def _when(raw: str) -> str:
    """A publication date the source printed, or empty. Never invented."""
    if not raw:
        return ""
    raw = raw.strip()
    try:
        dt = parsedate_to_datetime(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).isoformat(timespec="seconds")
    except (TypeError, ValueError, IndexError):
        pass
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(raw, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc).isoformat(timespec="seconds")
        except ValueError:
            continue
    return ""


def parse_feed(xml_text: str) -> list[dict]:
    """RSS 2.0, RDF and Atom, without a third-party dependency."""
    try:
        root = ET.fromstring(xml_text.strip())
    except ET.ParseError:
        # Some feeds ship a stray prolog or BOM; retry from the first tag.
        cut = xml_text.find("<?xml")
        if cut < 0:
            cut = xml_text.find("<")
        try:
            root = ET.fromstring(xml_text[cut:].strip())
        except (ET.ParseError, ValueError):
            return []

    items = []
    nodes = (root.findall(".//item")
             or root.findall(".//atom:entry", _NS)
             or root.findall(".//{http://purl.org/rss/1.0/}item"))
    for node in nodes:
        title = _text(node, "title", "atom:title")
        link = _text(node, "link", "atom:link[@rel='alternate']", "atom:link",
                     "guid")
        if not link:
            el = node.find("atom:link", _NS)
            link = el.get("href") if el is not None else ""
        summary = _strip(_text(node, "description", "atom:summary",
                               "content:encoded", "atom:content"))
        published = _when(_text(node, "pubDate", "atom:published", "atom:updated",
                                "dc:date"))

        # Google Trends items carry the search volume and the news stories that
        # drove the query. Both are real, published numbers.
        approx = _text(node, "ht:approx_traffic")
        picture_src = ""
        news_titles = []
        for nn in node.findall("ht:news_item", _NS):
            t = _text(nn, "ht:news_item_title")
            if t:
                news_titles.append(_strip(t))
            if not picture_src:
                picture_src = _text(nn, "ht:news_item_source")

        if title:
            items.append({
                "title": _strip(title),
                "url": (link or "").strip(),
                "summary": summary[:600],
                "published_at": published,
                "search_volume": approx,
                "driven_by": news_titles[:3],
                "attributed_source": picture_src,
            })
    return items


# --------------------------------------------------------------------------
# topic maths — module level, because two callers need it at two scopes
#
# The agent calls these over a single scan to report what that scan saw.
# `trend_store` calls the same functions over every signal ever collected,
# which is the only scope in which "rising" and "declining" are meaningful
# rather than a restatement of "recent".
# --------------------------------------------------------------------------

# --------------------------------------------------------------------------
# scoring
#
# The operator's weights. Social is listed and deliberately not scored: every
# platform that would supply it puts per-post metrics behind a login or an
# approved API, so a number here would be invented. Its weight is redistributed
# across the components that are measured, and every score says so.
# --------------------------------------------------------------------------

WEIGHTS = {
    "growth": 0.25,
    "social": 0.20,          # not measured — see MEASURED
    "search": 0.20,
    "cross_platform": 0.15,
    "commercial": 0.10,
    "novelty": 0.10,
}
MEASURED = ("growth", "search", "cross_platform", "commercial", "novelty")

# How much a category converts to an actual purchase decision for Clara.
COMMERCIAL_WEIGHT = {"direct": 100, "adjacent": 65, "context": 30}

LIFESPAN = {
    "viral": "weeks — spikes decay fast",
    "rising": "one to two quarters if it keeps gaining publishers",
    "emerging": "unknown; too thin to call",
    "mainstream": "years, but the upside is already priced in",
    "declining": "already past its window",
}


def _norm(value: float, ceiling: float) -> float:
    """0-100, clamped. A ceiling rather than a max over the set, so a score
    means the same thing between runs instead of drifting with the sample."""
    if ceiling <= 0:
        return 0.0
    return max(0.0, min(100.0, (value / ceiling) * 100.0))


def score_topic(topic: dict, group: list[dict], now) -> dict:
    """Every component, the total, and what the total is missing.

    Returns the components separately so the page can show the arithmetic. A
    single number with no breakdown is not auditable, and this one has a hole in
    it that a reader has to be told about.
    """
    from datetime import timedelta

    dates = []
    for g in group:
        d = _parse_iso(g.get("published_at"))
        if d:
            dates.append(d)

    recent = sum(1 for d in dates if (now - d) <= timedelta(days=7))
    prior = sum(1 for d in dates
                if timedelta(days=7) < (now - d) <= timedelta(days=28))

    # growth: this week against the three before it. A topic with nothing prior
    # cannot show acceleration, so it scores on volume alone and is capped.
    if prior:
        ratio = recent / prior
        growth = _norm(ratio, 3.0)
    else:
        growth = _norm(recent, 6.0) * 0.6

    search = _norm(sum(1 for g in group
                       if g.get("kind") == "search_demand"), 4.0)

    publishers = len({g.get("publisher") for g in group if g.get("publisher")})
    kinds = len({g.get("kind") for g in group if g.get("kind")})
    markets = len({g.get("market") for g in group if g.get("market")})
    cross = (_norm(publishers, 6.0) * 0.5 + _norm(kinds, 4.0) * 0.25
             + _norm(markets, 4.0) * 0.25)

    commercial = COMMERCIAL_WEIGHT.get(topic.get("clara_relevance"), 30)

    first = _parse_iso(topic.get("first_seen_at"))
    if first:
        age_days = max(0.0, (now - first).total_seconds() / 86400)
        novelty = _norm(max(0.0, 30.0 - age_days), 30.0)
    else:
        novelty = 50.0

    parts = {"growth": growth, "search": search, "cross_platform": cross,
             "commercial": commercial, "novelty": novelty}

    # Redistribute the unmeasured social weight across what is measured, so the
    # total stays on a 0-100 scale and is not silently deflated.
    live_weight = sum(WEIGHTS[k] for k in MEASURED)
    total = sum(parts[k] * (WEIGHTS[k] / live_weight) for k in MEASURED)

    return {
        "total": round(total),
        "components": {k: round(v) for k, v in parts.items()},
        "weights": WEIGHTS,
        "social": {
            "value": None,
            "state": "not measured",
            "why": ("per-post engagement sits behind a login or an approved API "
                    "on every platform that has it, and the agent does not work "
                    "around that. Its 20% is redistributed across the five "
                    "measured components rather than scored zero or guessed."),
        },
        "measured_components": len(MEASURED),
        "of_components": len(WEIGHTS),
        "counts": {"recent_7d": recent, "prior_21d": prior,
                   "publishers": publishers, "kinds": kinds,
                   "markets": markets},
    }


def confidence_score(topic: dict, group: list[dict]) -> dict:
    """0-100, from corroboration and dating rather than from enthusiasm."""
    publishers = len({g.get("publisher") for g in group if g.get("publisher")})
    dated = sum(1 for g in group if g.get("published_at"))
    kinds = len({g.get("kind") for g in group if g.get("kind")})
    best = max((g.get("weight") or 0) for g in group) if group else 0

    value = (_norm(publishers, 4.0) * 0.4
             + _norm(dated, max(1, len(group))) * 0.25
             + _norm(kinds, 3.0) * 0.2
             + _norm(best, 3.0) * 0.15)
    reasons = []
    if publishers < 2:
        reasons.append("only one publisher carries it")
    if dated < len(group):
        reasons.append(f"{len(group) - dated} item(s) carry no publication date")
    if kinds < 2:
        reasons.append("one kind of source only")
    return {"value": round(value),
            "why": "; ".join(reasons) or "corroborated across publishers, "
                                         "kinds and dates"}


def competition_level(group: list[dict]) -> dict:
    """A proxy, and labelled as one.

    Real competition would be how many brands sell into the subject. What is
    countable here is how many publishers already cover it, which is a proxy for
    how crowded the conversation is — not for how crowded the shelf is.
    """
    publishers = len({g.get("publisher") for g in group if g.get("publisher")})
    if publishers >= 6:
        level, note = "high", "widely covered; the conversation is crowded"
    elif publishers >= 3:
        level, note = "medium", "several publishers are on it"
    else:
        level, note = "low", "barely covered yet"
    return {"level": level, "note": note, "publishers": publishers,
            "basis": "proxy: publisher coverage, not shelf competition"}


def outlook(stage: str, sc: dict) -> dict:
    """7 / 30 / 90-180 day view. Prediction, and marked as prediction.

    Derived from the measured components rather than asserted: acceleration and
    breadth are what change over those horizons, so they are what the sentences
    are built from.
    """
    g = sc["components"]["growth"]
    x = sc["components"]["cross_platform"]
    c = sc["counts"]
    if stage == "viral":
        d7 = "likely still spiking; expect imitation content within days"
        d30 = "expect saturation and the first backlash pieces"
        d180 = "either becomes a standing category or is gone entirely"
    elif stage == "rising" and g >= 55:
        d7 = "more publishers likely to pick it up this week"
        d30 = "on this acceleration it reaches viral breadth"
        d180 = "strong candidate to become a standing category"
    elif stage == "rising":
        d7 = "steady; no reason to expect a step change in seven days"
        d30 = "likely to keep gaining publishers slowly"
        d180 = "becomes mainstream only if it crosses another market"
    elif stage == "emerging":
        d7 = "too thin to forecast a week out"
        d30 = f"watch whether it gets past {c['publishers']} publisher(s)"
        d180 = "either finds a second market or fades unnoticed"
    elif stage == "mainstream":
        d7 = "no change expected"
        d30 = "stable; the upside is already priced in"
        d180 = "watch for the counter-trend rather than the trend"
    else:
        d7 = "no new coverage expected"
        d30 = "likely to keep fading unless something revives it"
        d180 = "treat as historical unless it reappears"
    return {"next_7_days": d7, "next_30_days": d30, "next_3_6_months": d180,
            "basis": ("prediction, derived from the measured growth and breadth "
                      "components — not an observation"),
            "lifespan": LIFESPAN.get(stage, "unknown")}


def hidden_opportunity(sc: dict, comp: dict, topic: dict) -> dict:
    """High growth or search, low coverage, and worth something to Clara.

    Three conditions, all from measured components. A subject that is merely
    obscure is not an opportunity; it has to be moving and it has to matter.
    """
    growing = sc["components"]["growth"] >= 50 or sc["components"]["search"] >= 50
    uncrowded = comp["level"] in ("low", "medium")
    worth_it = topic.get("clara_relevance") in ("direct", "adjacent")
    is_hidden = growing and uncrowded and worth_it
    why = []
    if is_hidden:
        if sc["components"]["growth"] >= 50:
            why.append(f"{sc['counts']['recent_7d']} item(s) in the last week "
                       f"against {sc['counts']['prior_21d']} in the three before")
        if sc["components"]["search"] >= 50:
            why.append("rising search demand attached")
        why.append(f"only {comp['publishers']} publisher(s) covering it")
        why.append(f"{topic.get('clara_relevance')} relevance to what Clara sells")
    return {"is_hidden": is_hidden, "why": "; ".join(why)}


def _parse_iso(stamp):
    from datetime import datetime, timezone
    if not stamp:
        return None
    try:
        d = datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def build_topics(signals: list[dict], fetched_at: str) -> list[dict]:
    """Group the fetched signals by subject and measure each one."""
    by_topic: dict[str, list[dict]] = {}
    for s in signals:
        for key in (s.get("topics") or []):
            by_topic.setdefault(key, []).append(s)

    lookup = {t.key: t for t in ts.TOPICS}
    out = []
    for key, group in by_topic.items():
        topic = lookup.get(key)
        if not topic:
            continue

        publishers = sorted({g.get("publisher") or "" for g in group})
        markets = sorted({g.get("market") or "" for g in group})
        dates = [(g.get("published_at") or "") for g in group if (g.get("published_at") or "")]
        newest = max(dates) if dates else ""
        oldest = min(dates) if dates else ""

        stage, stage_why = stage_of(group, dates)
        spread = spread_of(markets)
        demand = [g for g in group if g.get("kind") == ts.SEARCH_DEMAND]

        group.sort(key=lambda g: (g.get("published_at") or "") or "", reverse=True)

        from datetime import datetime, timezone
        _now = datetime.now(timezone.utc)
        _topic_meta = {"clara_relevance": topic.clara_relevance,
                       "first_seen_at": oldest or fetched_at}
        _sc = score_topic(_topic_meta, group, _now)
        _cf = confidence_score(_topic_meta, group)
        _cp = competition_level(group)

        out.append({
            "key": key,
            "label": topic.label,
            "subcategory": getattr(topic, "subcategory", ""),
            "score": _sc,
            "confidence_score": _cf,
            "competition": _cp,
            "category": topic.category,
            "category_label": topic.category_label,
            "icon": topic.icon,
            "tags": list(topic.tags),
            # What this system could do about the subject. Suggestions from our
            # own playbook, labelled as such by the page — never market claims.
            "agent_can": list(topic.agent_can),
            "workflows": list(topic.workflows),
            "implement": topic.implement,
            "why_it_matters": topic.why_it_matters,
            "clara_relevance": topic.clara_relevance,
            "stage": stage,
            "stage_why": stage_why,
            "spread": spread,
            "markets": markets,
            "market_labels": [ts.MARKET_LABEL.get(m, m) for m in markets],
            "publishers": publishers,
            "publisher_count": len(publishers),
            "signal_count": len(group),
            "search_demand_signals": len(demand),
            "newest_published_at": newest,
            "oldest_published_at": oldest,
            "confidence": confidence_of(publishers, group),
            "outlook": outlook(stage, _sc),
            "hidden": hidden_opportunity(_sc, _cp, _topic_meta),
            "evidence": [{
                "title": g.get("title") or "", "url": g.get("url") or "",
                "publisher": g.get("publisher") or "", "published_at": (g.get("published_at") or ""),
                "market": g.get("market") or "", "kind": g.get("kind"),
                "summary": (g.get("summary") or "")[:240],
                "search_volume": g.get("search_volume") or "",
            } for g in group[:40]],   # the modal shows the full list, not a preview
            "last_checked_at": fetched_at,
        })

    out.sort(key=lambda t: (STAGE_ORDER.index(t["stage"]),
                            -t["publisher_count"], -t["signal_count"]))
    return out

def stage_of(group: list[dict], dates: list[str]) -> tuple[str, str]:
    """Derive the stage from publisher breadth, span and acceleration."""
    pubs = len({g.get("publisher") or "" for g in group})
    n = len(group)
    if not dates:
        return EMERGING, (f"{pubs} publisher(s), {n} item(s), none of them "
                          f"carrying a publication date")

    parsed = []
    for d in dates:
        try:
            parsed.append(datetime.fromisoformat(d))
        except ValueError:
            continue
    if not parsed:
        return EMERGING, f"{pubs} publisher(s), no readable dates"

    now = datetime.now(timezone.utc)
    span_days = max(1.0, (max(parsed) - min(parsed)).total_seconds() / 86400)
    recent = sum(1 for d in parsed if (now - d) <= timedelta(days=7))
    older = len(parsed) - recent
    recency_days = (now - max(parsed)).total_seconds() / 86400

    if recency_days > 30:
        return DECLINING, (f"nothing new for {recency_days:.0f} days across "
                           f"{pubs} publisher(s)")
    if pubs >= 6 and span_days > 45:
        return MAINSTREAM, (f"{pubs} publishers over {span_days:.0f} days — "
                            f"sustained rather than spiking")
    if pubs >= 4 and span_days <= 14:
        return VIRAL, (f"{pubs} publishers inside {span_days:.0f} days")
    if older and recent > older:
        return RISING, (f"{recent} item(s) in the last week against {older} "
                        f"before it, across {pubs} publisher(s)")
    if pubs >= 3:
        return RISING, f"{pubs} publishers carrying it, {n} items"
    return EMERGING, (f"{pubs} publisher(s), {n} item(s) — too thin to call "
                      f"more than early")

def spread_of(markets: list[str]) -> str:
    real = [m for m in markets if m != ts.GLOBAL]
    if len(markets) >= 5 or ts.GLOBAL in markets and len(real) >= 3:
        return GLOBAL_SPREAD
    if len(real) >= 3:
        return MOVING
    if len(real) == 2:
        return REGIONAL
    return LOCAL

def confidence_of(publishers: list[str], group: list[dict]) -> str:
    """Corroboration, not enthusiasm."""
    best = max(((g.get("weight") or 0) for g in group), default=0)
    if len(publishers) >= 3 and best >= 2:
        return Confidence.HIGH
    if len(publishers) >= 2:
        return Confidence.MEDIUM
    if best >= 2:
        return Confidence.LOW
    return Confidence.UNVERIFIED


# --------------------------------------------------------------------------
# the agent
# --------------------------------------------------------------------------

def active_source_list() -> list:
    """Seed feeds plus every discovered feed that earned activation.

    Falls back to the seeds alone if the discovery tables are not present, so a
    checkout that has never run discovery behaves exactly as before.
    """
    try:
        from ..config import DB_PATH
        from ..discovery.sources import to_source_objects
        from ..discovery.store import DiscoveryStore
    except Exception:
        return list(ts.SOURCES)
    try:
        ds = DiscoveryStore(DB_PATH)
    except Exception:
        return list(ts.SOURCES)
    try:
        ds.sync_seeds(ts.SOURCES)
        rows = ds.active_sources()
    finally:
        ds.close()
    return to_source_objects(rows) or list(ts.SOURCES)


class TrendCollectionAgent(Agent):
    name = "trend_collection"
    prompt_file = "trend_collection.md"

    def run_rules(self, store, scan_id: str,
                  sources: list | None = None) -> dict:
        srcs = sources if sources is not None else active_source_list()
        # Recomputed after the source list is known, so a discovered source's
        # host is on the allowlist before its first fetch rather than after.
        allowed = ts.allowed_hosts()
        allowed |= {h for s in srcs for h in
                    ({s.host, "www." + s.host} if s.host else set())}
        fetched_at = now_iso()

        signals: list[dict] = []
        source_status: list[dict] = []

        for src in srcs:
            res = access.guarded_get(src.url, allowed_hosts=allowed,
                                     max_retries=2, timeout=25)
            if not res.ok:
                source_status.append({
                    "key": src.key, "publisher": src.publisher, "url": src.url,
                    "ok": False, "signal": res.block_signal,
                    "items": 0, "kept": 0, "checked_at": fetched_at,
                    "what_to_do": ("open the feed by hand, or ask this publisher "
                                   "for access — nothing here is retried with "
                                   "different headers"),
                })
                self.report.blocked.append(
                    {"publisher": src.publisher, "signal": res.block_signal})
                continue

            items = parse_feed(res.html or "")
            kept = 0
            for it in items:
                blob = f"{it['title']} {it['summary']} {' '.join(it['driven_by'])}"
                if src.kind == ts.SEARCH_DEMAND and not ts.is_beauty(blob):
                    continue
                if src.kind != ts.SEARCH_DEMAND and not ts.is_beauty(blob):
                    continue
                topics = ts.topics_for(blob)
                signals.append({
                    "source_key": src.key,
                    "publisher": src.publisher,
                    "kind": src.kind,
                    "market": src.market,
                    "weight": src.weight,
                    "title": it["title"],
                    "url": it["url"] or src.url,
                    "summary": it["summary"],
                    "published_at": it["published_at"],
                    "search_volume": it["search_volume"],
                    "driven_by": it["driven_by"],
                    "topics": [t.key for t in topics],
                    "seen_at": fetched_at,
                })
                kept += 1

            source_status.append({
                "key": src.key, "publisher": src.publisher, "url": src.url,
                "ok": True, "signal": None, "items": len(items), "kept": kept,
                "checked_at": fetched_at, "what_to_do": "",
            })

        for publisher, url, signal in ts.REFUSED:
            source_status.append({
                "key": "refused_" + re.sub(r"\W+", "_", publisher.lower()),
                "publisher": publisher, "url": url, "ok": False,
                "signal": signal, "items": 0, "kept": 0,
                "checked_at": fetched_at,
                "what_to_do": ("this publisher refused automated access when it "
                               "was probed; it is listed so the sweep is not "
                               "read as complete"),
            })

        topics = build_topics(signals, fetched_at)
        untagged = [s for s in signals if not s["topics"]]

        readable = sum(1 for s in source_status if s["ok"])
        self.report.items_in = len(srcs)
        self.report.items_out = len(signals)
        self.report.note(
            f"{readable} of {len(srcs)} feeds answered; {len(signals)} beauty "
            f"signals kept; {len(topics)} topics have evidence")
        if len(srcs) - readable:
            self.report.note(
                f"{len(srcs) - readable} feed(s) refused or failed — the page "
                f"names them rather than implying the market was quiet there")

        return {
            "scan_id": scan_id,
            "fetched_at": fetched_at,
            "signals": signals,
            "topics": topics,
            "sources": source_status,
            "untagged": untagged[:60],
            "counts": {
                "feeds_tried": len(srcs),
                "feeds_read": readable,
                "signals": len(signals),
                "topics_with_evidence": len(topics),
                "untagged_signals": len(untagged),
            },
        }

    # ----------------------------------------------------------------------

    def refine(self, result, store, scan_id, sources=None):
        """No model pass on collection.

        Everything above is a headline a publisher printed, grouped by a pattern
        that is visible in the source. A model rewrite would make the page read
        better and make every line harder to trace back to the feed it came from.
        """
        return None
