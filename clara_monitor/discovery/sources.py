"""Discovering publishers from the articles we already fetched, and scoring them.

The loop, one hop at a time:

    a source we trust
      -> an article it published
        -> a publisher named or linked in that article
          -> that publisher's own feed
            -> validated
              -> scored
                -> activated, and the next scan reads it

Depth is what makes this compound and what makes it dangerous. Depth 0 is the
hand-curated seeds; depth 1 is a publisher found from a seed's article; depth 2
is a publisher found from *that* publisher's article. The default stops there,
because two hops from something a person chose is still traceable to that
choice, and three is not.

**Scoring, and why it is deliberately hard to pass.** `score_source` returns
0.0–1.0 from six weighted signals, and a discovered source needs 0.80 to
activate itself. The relevance component alone is capable of failing a perfectly
healthy feed, which is correct: a working feed about interiors is not a beauty
source, and the registry's value is entirely in what it excludes.

Nothing here trusts what it finds. A candidate is a row with a state and a
provenance record, not a source. Only the score promotes it, and the reason is
written down either way.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit

from .. import access, extract, trend_sources as ts
from .config import (ACTIVE, CANDIDATE, DISABLED, DISCOVERED, REJECTED,
                     VALIDATED, DiscoveryConfig)
from .feeds import (RELEVANT, discover_feeds, normalise_url,
                    registrable_domain, validate_feed)

# Hosts that are never a publisher: platforms, social, infrastructure. Without
# this the loop tries to add facebook.com as a beauty source on the first run.
NOT_A_PUBLISHER = {
    "facebook", "instagram", "twitter", "x", "tiktok", "youtube", "linkedin",
    "pinterest", "snapchat", "reddit", "whatsapp", "telegram", "threads",
    "google", "googleapis", "gstatic", "doubleclick", "amazonaws",
    "cloudfront", "akamai", "cloudflare", "wp", "gravatar", "shopify",
    "bit", "t", "goo", "ow", "buff", "lnkd", "dlvr", "feedburner",
    "wikipedia", "wikimedia", "archive", "github", "apple", "spotify",
    "paypal", "stripe", "mailchimp", "substack", "medium", "notion",
}

PUBLISHER_META = (
    ("og:site_name", r'property=["\']og:site_name["\'][^>]*content=["\']([^"\']+)'),
    ("og:site_name_rev", r'content=["\']([^"\']+)["\'][^>]*property=["\']og:site_name'),
    ("application_name", r'name=["\']application_name["\'][^>]*content=["\']([^"\']+)'),
)
LINKED_HOST_RE = re.compile(r"https?://([a-z0-9.-]+\.[a-z]{2,})", re.I)


def _is_publisher_host(host: str) -> bool:
    reg = registrable_domain(host)
    if not reg or "." not in reg:
        return False
    if reg.split(".")[0] in NOT_A_PUBLISHER:
        return False
    if len(reg) < 5:
        return False
    return True


def publisher_from_article(html: str, url: str) -> dict:
    """Name and domain for the site an article was read from.

    Tries the publisher's own declarations first — JSON-LD `publisher.name`,
    then OpenGraph `og:site_name` — and falls back to the domain. The name
    matters because the report has to be readable: "Example Beauty" is a source,
    `example.com` is a hostname.
    """
    domain = registrable_domain(url)
    name = ""

    for node in extract.jsonld_nodes(html or ""):
        pub = node.get("publisher")
        if isinstance(pub, dict) and pub.get("name"):
            name = str(pub["name"]).strip()
            break
        if isinstance(node.get("name"), str) and node.get("@type") in (
                "Organization", "NewsMediaOrganization", "WebSite"):
            name = node["name"].strip()
            break

    if not name:
        for _, pat in PUBLISHER_META:
            m = re.search(pat, html or "", re.I)
            if m:
                name = m.group(1).strip()
                break

    if not name:
        name = domain.split(".")[0].replace("-", " ").title()

    return {"name": name[:80], "domain": domain, "url": f"https://{domain}"}


def candidate_domains_from_signals(signals: list[dict], known: set,
                                   limit: int = 40) -> list[dict]:
    """Publishers referenced by articles we already hold.

    Reads the stored signals rather than re-fetching anything, so the cheap half
    of discovery costs nothing: the article URLs we have already collected name
    the publishers we have not.
    """
    seen: dict = {}
    for s in signals:
        for field in ("url", "summary", "title"):
            text = s.get(field) or ""
            for host in LINKED_HOST_RE.findall(text):
                reg = registrable_domain(host)
                if not reg or reg in known or not _is_publisher_host(reg):
                    continue
                hit = seen.setdefault(reg, {
                    "domain": reg, "mentions": 0, "from_signal": s.get("url"),
                    "parent_publisher": s.get("publisher"),
                    "example_title": (s.get("title") or "")[:120],
                })
                hit["mentions"] += 1
    ranked = sorted(seen.values(), key=lambda d: -d["mentions"])
    return ranked[:limit]


def harvest_from_articles(signals: list[dict], known: set, *, allowed: set,
                          budget: dict, sample: int = 15,
                          verbose: bool = True) -> list[dict]:
    """Fetch a sample of article pages and read them for other publishers.

    This is the step that gives the loop something to grow on. A feed summary is
    plain text — the links that name other publishers only exist in the article
    HTML, so without this the discoverer can only ever see the publishers it
    already has.

    Bounded on purpose: `sample` pages, one fetch each, against the shared
    request budget. Newest first, because a link in a recent article is more
    likely to point at a publisher that is currently active.
    """
    ranked = sorted(
        [s for s in signals if (s.get("url") or "").startswith("http")],
        key=lambda s: (s.get("published_at") or s.get("first_seen_at") or ""),
        reverse=True)

    seen: dict = {}
    fetched = 0
    for sig in ranked:
        if fetched >= sample or budget["used"] >= budget["max"]:
            break
        url = sig["url"]
        host = urlsplit(url).hostname or ""
        allow = set(allowed) | {host, host[4:] if host.startswith("www.")
                                else "www." + host}
        budget["used"] += 1
        res = access.guarded_get(url, allowed_hosts=allow, max_retries=1,
                                 timeout=20)
        if not res.ok:
            continue
        fetched += 1
        html = res.html or ""

        # Outbound links in the article body: this is the actual raw material.
        for linked in set(LINKED_HOST_RE.findall(html)):
            reg = registrable_domain(linked)
            if not reg or reg in known or not _is_publisher_host(reg):
                continue
            if reg == registrable_domain(url):
                continue
            hit = seen.setdefault(reg, {
                "domain": reg, "mentions": 0,
                "from_signal": url,
                "parent_publisher": sig.get("publisher"),
                "example_title": (sig.get("title") or "")[:120],
                "method": "outbound_link_in_article",
            })
            hit["mentions"] += 1

    if verbose:
        print(f"    read {fetched} article page(s); "
              f"{len(seen)} unknown publisher domain(s) linked from them",
              flush=True)
    return sorted(seen.values(), key=lambda d: -d["mentions"])


# --------------------------------------------------------------------------
# scoring
# --------------------------------------------------------------------------

SCORE_WEIGHTS = {
    "valid_feed": 0.30,
    "usable_articles": 0.15,
    "relevance": 0.25,
    "freshness": 0.15,
    "domain_consistency": 0.10,
    "uniqueness": 0.05,
}


def score_source(validation: dict, *, existing_titles: set | None = None,
                 history: dict | None = None) -> dict:
    """0.0–1.0, with the components shown.

    Relevance carries the heaviest weight after validity because it is the one
    thing a healthy feed can fail. Freshness is next: a beauty feed whose newest
    entry is a year old is a museum, not a source.
    """
    parts = {k: 0.0 for k in SCORE_WEIGHTS}
    notes = []

    if not validation.get("ok"):
        return {"score": 0.0, "components": parts,
                "notes": [validation.get("reason") or "validation failed"]}

    parts["valid_feed"] = 1.0

    usable = validation.get("usable") or 0
    parts["usable_articles"] = min(1.0, usable / 10.0)
    notes.append(f"{usable} usable entry/entries")

    relevant = validation.get("relevant") or 0
    ratio = (relevant / usable) if usable else 0.0
    parts["relevance"] = min(1.0, ratio * 1.25)
    # "In frame" rather than "on subject": the test is now the four product
    # families, so a well-run skincare publication scores zero here and the note
    # should say why rather than reading like a parsing failure.
    notes.append(f"{relevant}/{usable} entries inside the product frame "
                 f"({ratio:.0%})")

    newest = validation.get("newest_at") or ""
    try:
        d = datetime.fromisoformat(newest.replace("Z", "+00:00")) if newest else None
    except (ValueError, TypeError):
        d = None
    if d:
        if d.tzinfo is None:
            d = d.replace(tzinfo=timezone.utc)
        age = (datetime.now(timezone.utc) - d).days
        parts["freshness"] = (1.0 if age <= 7 else 0.75 if age <= 30
                              else 0.4 if age <= 90 else 0.1)
        notes.append(f"newest entry {age} day(s) old")
    else:
        parts["freshness"] = 0.25
        notes.append("no readable publication date")

    parts["domain_consistency"] = 1.0 if validation.get("same_domain") else 0.0

    titles = {t.strip().lower() for t in (validation.get("titles") or []) if t}
    if titles and existing_titles:
        dupes = len(titles & existing_titles)
        parts["uniqueness"] = max(0.0, 1.0 - (dupes / len(titles)))
        if dupes:
            notes.append(f"{dupes} of {len(titles)} headlines already held — "
                         f"likely syndicating a source we have")
    else:
        parts["uniqueness"] = 1.0

    if history:
        fails = history.get("failure_count") or 0
        if fails:
            notes.append(f"{fails} previous failure(s)")
            for k in parts:
                parts[k] *= max(0.4, 1.0 - fails * 0.15)

    total = sum(parts[k] * w for k, w in SCORE_WEIGHTS.items())
    return {"score": round(total, 3), "components":
            {k: round(v, 3) for k, v in parts.items()}, "notes": notes}


# --------------------------------------------------------------------------
# the run
# --------------------------------------------------------------------------

def _slug(domain: str) -> str:
    return "d_" + re.sub(r"[^a-z0-9]+", "_", domain.lower()).strip("_")[:40]


def run_source_discovery(store, trend_signals: list[dict], *,
                         cfg: DiscoveryConfig, run_id: str,
                         depth: int = 1, verbose: bool = True) -> dict:
    """One pass of publisher discovery, bounded on every axis.

    Bounds are checked before every fetch rather than after, so a run cannot
    overshoot its request budget by the width of one domain's path list.
    """
    sc = cfg.sources
    budget = {"used": 0, "max": sc.max_discovery_requests}
    known_domains = store.known_domains()
    known_feeds = store.known_feeds()
    existing_titles = {(s.get("title") or "").strip().lower()
                       for s in trend_signals if s.get("title")}

    allowed_seed = ts.allowed_hosts()

    log = []

    def say(msg):
        log.append(msg)
        if verbose:
            print(f"    {msg}", flush=True)

    # Cheap pass first: publishers already named in stored metadata.
    cands = candidate_domains_from_signals(trend_signals, known_domains)
    say(f"{len(cands)} unknown publisher domain(s) in stored metadata")

    # Then the expensive pass, which is where the material actually is. A feed
    # summary is plain text; the outbound links live in the article HTML.
    harvested = harvest_from_articles(
        trend_signals, known_domains, allowed=allowed_seed, budget=budget,
        sample=sc.article_sample, verbose=verbose)

    merged: dict = {c["domain"]: c for c in cands}
    for h in harvested:
        if h["domain"] in merged:
            merged[h["domain"]]["mentions"] += h["mentions"]
        else:
            merged[h["domain"]] = h
    cands = sorted(merged.values(), key=lambda d: -d["mentions"])
    say(f"{len(cands)} candidate publisher domain(s) in total")

    stats = {"domains_considered": 0, "feeds_proposed": 0, "validated": 0,
             "failed_validation": 0, "activated": 0, "candidates": 0,
             "rejected": 0, "rediscovered": 0, "requests": 0}

    for cand in cands:
        if stats["activated"] + stats["candidates"] >= sc.max_new_per_scan:
            say(f"stopping: hit max_new_per_scan={sc.max_new_per_scan}")
            break
        if budget["used"] >= budget["max"]:
            say(f"stopping: request budget {budget['max']} exhausted")
            break

        domain = cand["domain"]
        stats["domains_considered"] += 1
        # A publisher already in the registry under another feed path is not a
        # discovery. This is the check that was missing when the first real run
        # "found" seven of its own seeds.
        if store.source_exists(domain=domain):
            stats["rediscovered"] += 1
            continue
        if store.candidates_for_domain(domain) >= sc.max_candidates_per_domain:
            continue

        allow = set(allowed_seed) | {domain, "www." + domain}
        found = discover_feeds(domain, allowed=allow, budget=budget)
        stats["feeds_proposed"] += len(found["candidates"])

        provenance = {
            "source_key": None,
            "parent_publisher": cand.get("parent_publisher"),
            "article_url": cand.get("from_signal"),
            "discovery_method": cand.get("method", "article_publisher_link"),
            "mentions_in_corpus": cand.get("mentions"),
            "example_headline": cand.get("example_title"),
        }

        accepted = False
        for c in found["candidates"]:
            if budget["used"] >= budget["max"]:
                break
            feed_url = c["feed_url"]
            if feed_url in known_feeds:
                stats["rediscovered"] += 1
                continue

            result = validate_feed(feed_url, expect_domain=domain, allowed=allow,
                                   budget=budget,
                                   min_entries=sc.min_entries,
                                   min_relevant=sc.min_relevant_entries)
            store.record_validation(run_id, feed_url, result)
            if not result["ok"]:
                stats["failed_validation"] += 1
                continue

            stats["validated"] += 1
            scored = score_source(result, existing_titles=existing_titles)
            result["quality"] = scored["score"]

            prov = dict(provenance)
            prov["discovery_method"] = c["method"]
            row = store.add_candidate(
                key=_slug(domain), name=cand.get("parent_publisher") and
                domain.split(".")[0].replace("-", " ").title() or
                domain.split(".")[0].replace("-", " ").title(),
                url=f"https://{domain}", feed_url=feed_url, domain=domain,
                kind="discovered_press", market="GLOBAL", depth=depth,
                provenance=prov, run_id=run_id)

            store.db.execute(
                "UPDATE ds_source SET quality_score=?, confidence=?, "
                "article_count=?, relevant_count=? WHERE feed_url=?",
                (scored["score"], scored["score"], result["usable"],
                 result["relevant"], feed_url))
            store.db.commit()

            if scored["score"] >= sc.activation_threshold:
                store.set_status(feed_url, ACTIVE, quality=scored["score"],
                                 reason=("score %.2f >= %.2f: %s"
                                         % (scored["score"],
                                            sc.activation_threshold,
                                            "; ".join(scored["notes"]))),
                                 run_id=run_id)
                stats["activated"] += 1
                say(f"ACTIVATED  {domain:28} {scored['score']:.2f}  "
                    f"{result['usable']} usable, {result['relevant']} relevant")
            elif scored["score"] >= sc.candidate_threshold:
                store.set_status(feed_url, VALIDATED, quality=scored["score"],
                                 reason=("score %.2f: kept as a candidate, not "
                                         "scanned" % scored["score"]),
                                 run_id=run_id)
                stats["candidates"] += 1
                say(f"candidate  {domain:28} {scored['score']:.2f}  "
                    f"watching, not scanned")
            else:
                store.set_status(feed_url, REJECTED, quality=scored["score"],
                                 reason=("score %.2f < %.2f: %s"
                                         % (scored["score"],
                                            sc.candidate_threshold,
                                            "; ".join(scored["notes"]))),
                                 run_id=run_id)
                stats["rejected"] += 1
                say(f"rejected   {domain:28} {scored['score']:.2f}  "
                    f"{'; '.join(scored['notes'])[:60]}")

            known_feeds.add(feed_url)
            accepted = True
            break

        if not accepted and found["candidates"]:
            store.event(run_id, "rejected", domain=domain,
                        method="no_valid_feed",
                        detail=f"{len(found['candidates'])} candidate URL(s), "
                               f"none validated")

    stats["requests"] = budget["used"]
    store.mark("source_discovery", run_id)
    return {"stats": stats, "log": log, "run_id": run_id}


def to_source_objects(rows: list[dict]) -> list:
    """Registry rows as the `Source` objects the collector already understands.

    This is the join between the two halves of the system: discovery writes rows,
    the collector reads `Source` objects, and neither needs to know about the
    other's storage.
    """
    out = []
    for r in rows:
        out.append(ts.Source(
            key=r.get("key") or _slug(r.get("domain") or ""),
            publisher=r.get("name") or r.get("domain") or "",
            url=r.get("feed_url"),
            kind=r.get("kind") or "trade_press",
            market=r.get("market") or "GLOBAL",
            weight=2 if r.get("source_type") == "seed" else 1,
            note=("hand-curated seed" if r.get("source_type") == "seed"
                  else f"discovered, quality {r.get('quality_score')}"),
        ))
    return out
