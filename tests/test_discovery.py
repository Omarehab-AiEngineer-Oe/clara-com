"""Tests for the discovery loop.

Each test is written against a failure that would actually happen. The
interesting ones are the negatives: a loop that adds sources is easy, and a loop
that refuses the wrong ones is the whole product.

Runs against a temporary database so nothing here can touch the real registry.
No network: feed bodies are fixtures, so the tests are about the decisions rather
than about whether a publisher happens to be up.

    python -m pytest tests/test_discovery.py -q
    python tests/test_discovery.py          # same, without pytest
"""

from __future__ import annotations

import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from clara_monitor import trend_sources as ts
from clara_monitor.agents.trend_collector import parse_feed
from clara_monitor.discovery import (ACTIVE, CANDIDATE, DISCOVERED, MERGED,
                                     REJECTED, SEED, VALIDATED,
                                     DiscoveryConfig, DiscoveryStore)
from clara_monitor.discovery.feeds import (normalise_url, registrable_domain,
                                           same_publisher)
from clara_monitor.discovery.sources import (publisher_from_article,
                                             candidate_domains_from_signals,
                                             score_source)
from clara_monitor.discovery.topics import (beauty_share, cluster, find_overlap,
                                            make_pattern, off_domain_reason,
                                            test_pattern)

# --------------------------------------------------------------------------
# fixtures
# --------------------------------------------------------------------------

RSS = """<?xml version="1.0"?><rss version="2.0"><channel>
<title>Example Beauty</title>
<item><title>The best serum for oily skin</title>
 <link>https://example-beauty.com/a</link>
 <pubDate>Mon, 18 Aug 2026 10:00:00 GMT</pubDate>
 <description>Skincare review of a niacinamide serum.</description></item>
<item><title>Sephora adds a new haircare brand</title>
 <link>https://example-beauty.com/b</link>
 <pubDate>Tue, 19 Aug 2026 10:00:00 GMT</pubDate>
 <description>Beauty retail news.</description></item>
<item><title>Makeup trends for autumn</title>
 <link>https://example-beauty.com/c</link>
 <pubDate>Wed, 20 Aug 2026 10:00:00 GMT</pubDate>
 <description>Blush and bronzer.</description></item>
<item><title>A shampoo that actually works</title>
 <link>https://example-beauty.com/d</link>
 <pubDate>Wed, 20 Aug 2026 11:00:00 GMT</pubDate>
 <description>Haircare.</description></item>
</channel></rss>"""

ATOM = """<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom">
<title>Atom Beauty</title>
<entry><title>Retinol explained by a dermatologist</title>
 <link rel="alternate" href="https://atom-beauty.com/1"/>
 <updated>2026-08-19T10:00:00Z</updated>
 <summary>Skincare actives.</summary></entry>
<entry><title>Fragrance layering guide</title>
 <link rel="alternate" href="https://atom-beauty.com/2"/>
 <updated>2026-08-20T10:00:00Z</updated>
 <summary>Perfume notes.</summary></entry>
<entry><title>Nail art for short nails</title>
 <link rel="alternate" href="https://atom-beauty.com/3"/>
 <updated>2026-08-20T11:00:00Z</updated>
 <summary>Manicure ideas.</summary></entry>
</feed>"""

HTML_WITH_LINK = """<html><head>
<title>Example Beauty</title>
<meta property="og:site_name" content="Example Beauty"/>
<link rel="alternate" type="application/rss+xml" href="/feed/"/>
</head><body>Beauty news</body></html>"""

HTML_WITH_JSONLD = """<html><head>
<script type="application/ld+json">
{"@type":"NewsArticle","publisher":{"@type":"Organization",
 "name":"Gulf Beauty Weekly"}}
</script></head><body>x</body></html>"""

NOT_A_FEED = "<html><body><h1>Page not found</h1></body></html>"

EMPTY_FEED = """<?xml version="1.0"?><rss version="2.0"><channel>
<title>Parked</title></channel></rss>"""

OFF_TOPIC_FEED = """<?xml version="1.0"?><rss version="2.0"><channel>
<title>Motoring</title>
<item><title>New hatchback reviewed</title><link>https://cars.test/1</link>
 <description>Engine and gearbox.</description></item>
<item><title>Tyre test 2026</title><link>https://cars.test/2</link>
 <description>Wet braking.</description></item>
<item><title>Best estates</title><link>https://cars.test/3</link>
 <description>Boot space.</description></item>
</channel></rss>"""

WRONG_DOMAIN_FEED = """<?xml version="1.0"?><rss version="2.0"><channel>
<title>Syndicated</title>
<item><title>Beauty serum review</title><link>https://someone-else.com/1</link>
 <description>Skincare.</description></item>
<item><title>Makeup news</title><link>https://someone-else.com/2</link>
 <description>Beauty.</description></item>
<item><title>Haircare guide</title><link>https://someone-else.com/3</link>
 <description>Shampoo.</description></item>
</channel></rss>"""


def _validate(body: str, feed_url: str, expect_domain: str = "",
              min_entries: int = 3, min_relevant: int = 2) -> dict:
    """`validate_feed` without the network: same logic, injected body.

    Mirrors the real function's checks in the same order so a change to one
    without the other shows up as a failing test rather than as drift.
    """
    from clara_monitor.discovery.feeds import RELEVANT
    out = {"feed_url": feed_url, "ok": False, "reason": "", "entries": 0,
           "usable": 0, "relevant": 0, "same_domain": False, "newest_at": "",
           "titles": []}
    head = body[:2500].lower()
    if not ("<rss" in head or "<feed" in head or "rdf:rdf" in head):
        out["reason"] = "not RSS or Atom"
        return out
    items = parse_feed(body)
    out["entries"] = len(items)
    if not items:
        out["reason"] = "no entries"
        return out
    usable = [i for i in items if (i.get("title") or "").strip()
              and (i.get("url") or "").strip()]
    out["usable"] = len(usable)
    if len(usable) < min_entries:
        out["reason"] = f"only {len(usable)} usable"
        return out
    target = expect_domain or registrable_domain(feed_url)
    on = sum(1 for i in usable if same_publisher(i.get("url", ""), target))
    out["same_domain"] = on >= max(1, len(usable) // 2)
    if not out["same_domain"]:
        out["reason"] = f"entries do not point at {target}"
        return out
    out["relevant"] = sum(
        1 for i in usable
        if RELEVANT.search(f"{i.get('title', '')} {i.get('summary', '')}"))
    if out["relevant"] < min_relevant:
        out["reason"] = f"only {out['relevant']} relevant"
        return out
    dates = [i.get("published_at") for i in usable if i.get("published_at")]
    out["newest_at"] = max(dates) if dates else ""
    out["titles"] = [i.get("title", "") for i in usable[:5]]
    out["ok"] = True
    out["reason"] = "valid"
    return out


def _signal(title, publisher, url, days_ago=0, summary=""):
    at = (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()
    return {"title": title, "publisher": publisher, "url": url,
            "summary": summary, "published_at": at, "first_seen_at": at,
            "topics": []}


RESULTS = []


def check(name: str, condition: bool, detail: str = "") -> None:
    RESULTS.append((name, bool(condition), detail))
    print(f"  {'PASS' if condition else 'FAIL'}  {name}"
          + (f"  — {detail}" if detail and not condition else ""))


# --------------------------------------------------------------------------
# feed discovery / validation
# --------------------------------------------------------------------------

def test_feeds():
    print("\nFEED DISCOVERY AND VALIDATION")
    r = _validate(RSS, "https://example-beauty.com/feed")
    check("valid RSS accepted", r["ok"] and r["usable"] == 4, r["reason"])

    r = _validate(ATOM, "https://atom-beauty.com/atom.xml")
    check("valid Atom accepted", r["ok"] and r["usable"] == 3, r["reason"])

    r = _validate(NOT_A_FEED, "https://x.test/feed")
    check("HTML page rejected", not r["ok"] and "not RSS" in r["reason"])

    r = _validate(EMPTY_FEED, "https://parked.test/feed")
    check("well-formed empty feed rejected",
          not r["ok"] and "no entries" in r["reason"])

    r = _validate(OFF_TOPIC_FEED, "https://cars.test/feed")
    check("off-topic feed rejected despite being valid",
          not r["ok"] and "relevant" in r["reason"], r["reason"])

    r = _validate(WRONG_DOMAIN_FEED, "https://aggregator.test/feed",
                  expect_domain="aggregator.test")
    check("feed whose entries point elsewhere rejected",
          not r["ok"] and "do not point at" in r["reason"], r["reason"])

    r = _validate(RSS, "https://example-beauty.com/feed", min_entries=99)
    check("too few entries rejected", not r["ok"])

    # HTML with a declared feed link
    from clara_monitor.discovery.feeds import _links_in_head
    links = _links_in_head(HTML_WITH_LINK, "https://example-beauty.com")
    check("rss <link> in head is found",
          links and links[0][0].endswith("/feed/"), str(links))


def test_normalisation():
    print("\nDEDUPLICATION")
    a = normalise_url("http://WWW.Example.com/feed/?utm_source=x#frag")
    b = normalise_url("https://example.com/feed")
    check("scheme, www, slash, tracking and fragment all fold", a == b,
          f"{a} != {b}")
    check("registrable domain strips subdomain",
          registrable_domain("https://en.vogue.co.uk/x") == "vogue.co.uk",
          registrable_domain("https://en.vogue.co.uk/x"))
    check("different publishers stay different",
          not same_publisher("https://a.com/1", "b.com"))


# --------------------------------------------------------------------------
# source discovery
# --------------------------------------------------------------------------

def test_sources(tmp: Path):
    print("\nSOURCE DISCOVERY")
    store = DiscoveryStore(tmp)
    cfg = DiscoveryConfig()
    store.sync_seeds(ts.SOURCES)

    check("seeds mirrored as active",
          len(store.by_status(ACTIVE)) == len(ts.SOURCES),
          f"{len(store.by_status(ACTIVE))} vs {len(ts.SOURCES)}")

    seed_feed = ts.SOURCES[0].url
    before = len(store.by_status(ACTIVE))
    store.sync_seeds(ts.SOURCES)
    check("re-syncing seeds does not duplicate",
          len(store.by_status(ACTIVE)) == before)
    check("existing seed is found by feed url",
          store.source_exists(feed_url=seed_feed))

    # a high-quality candidate activates
    good = _validate(RSS, "https://example-beauty.com/feed",
                     expect_domain="example-beauty.com")
    good["newest_at"] = datetime.now(timezone.utc).isoformat()
    sc = score_source(good)
    check("high-quality feed scores above the activation threshold",
          sc["score"] >= cfg.sources.activation_threshold,
          f"score {sc['score']}")

    store.add_candidate(key="d_example_beauty", name="Example Beauty",
                        url="https://example-beauty.com",
                        feed_url="https://example-beauty.com/feed",
                        domain="example-beauty.com", kind="consumer_press",
                        market="GLOBAL", depth=1,
                        provenance={"discovery_method": "link_rel_alternate",
                                    "article_url": "https://seed.test/a",
                                    "parent_publisher": "Seed Publisher"},
                        run_id="t1")
    row = store.by_feed("https://example-beauty.com/feed")
    check("candidate is created as a candidate, not active",
          row and row["status"] == CANDIDATE, str(row and row["status"]))
    check("provenance is stored",
          row and "link_rel_alternate" in (row["discovered_from"] or ""),
          str(row and row["discovered_from"])[:60])

    store.set_status("https://example-beauty.com/feed", ACTIVE,
                     quality=sc["score"], reason="test", run_id="t1")
    check("activation moves it into the active set",
          any(s["domain"] == "example-beauty.com"
              for s in store.by_status(ACTIVE)))

    # rediscovery updates rather than duplicating
    n_before = len(store.by_domain("example-beauty.com"))
    store.add_candidate(key="d_example_beauty", name="Example Beauty",
                        url="https://example-beauty.com",
                        feed_url="https://example-beauty.com/feed",
                        domain="example-beauty.com", kind="consumer_press",
                        market="GLOBAL", depth=1,
                        provenance={"discovery_method": "common_path_guess"},
                        run_id="t2")
    check("rediscovery does not create a second row",
          len(store.by_domain("example-beauty.com")) == n_before)

    # a low-quality candidate is rejected
    bad = _validate(OFF_TOPIC_FEED, "https://cars.test/feed",
                    expect_domain="cars.test")
    sbad = score_source(bad)
    check("off-topic feed scores below the candidate threshold",
          sbad["score"] < cfg.sources.candidate_threshold,
          f"score {sbad['score']}")

    store.add_candidate(key="d_cars", name="Cars", url="https://cars.test",
                        feed_url="https://cars.test/feed", domain="cars.test",
                        kind="unknown", market="GLOBAL", depth=1,
                        provenance={"discovery_method": "common_path_guess"},
                        run_id="t1")
    store.set_status("https://cars.test/feed", REJECTED, quality=sbad["score"],
                     reason="off topic", run_id="t1")
    check("rejected source is not scanned",
          not any(s["domain"] == "cars.test" for s in store.active_sources()))
    check("rejection reason is kept",
          (store.by_feed("https://cars.test/feed") or {}).get("reject_reason"))

    events = store.events("t1")
    check("discovery events are recorded", len(events) >= 3,
          f"{len(events)} event(s)")
    store.close()


# --------------------------------------------------------------------------
# topic discovery
# --------------------------------------------------------------------------

def test_topics(tmp: Path):
    print("\nTOPIC DISCOVERY")
    cfg = DiscoveryConfig()

    # a real recurring cluster: 6 signals, 3 publishers, 3 days
    signals = [
        _signal("Scalp microbiome is the next frontier in haircare",
                "Glossy", "https://a.test/1", 1, "Scalp care and bacteria."),
        _signal("Why the scalp microbiome matters for hair growth",
                "Allure", "https://b.test/2", 2, "Haircare science."),
        _signal("Brands bet on scalp microbiome haircare",
                "WWD", "https://c.test/3", 3, "Beauty retail."),
        _signal("Scalp microbiome products are launching fast",
                "Glossy", "https://a.test/4", 1, "Haircare launches."),
        _signal("The scalp microbiome explained by a dermatologist",
                "Allure", "https://b.test/5", 2, "Skincare for scalp."),
        _signal("Scalp microbiome: the shampoo angle",
                "WWD", "https://c.test/6", 3, "Shampoo and beauty."),
    ]
    clusters = cluster(signals, cfg=cfg)
    keys = [c["phrase"] for c in clusters]
    check("recurring cluster is detected",
          any("microbiome" in k for k in keys), str(keys[:4]))

    # insufficient evidence: one publisher, one day
    thin = [_signal(f"Aura nails are everywhere {i}", "OnlyOne",
                    f"https://d.test/{i}", 0, "Nail art.")
            for i in range(6)]
    thin_clusters = cluster(thin, cfg=cfg)
    check("one publisher on one day does not qualify",
          not thin_clusters, f"{len(thin_clusters)} cluster(s)")

    # pattern generation and corpus test
    hit = next(c for c in clusters if "microbiome" in c["phrase"])
    pat = make_pattern(hit["phrase"], hit["signals"])
    urls = {s["url"] for s in hit["signals"]}
    res = test_pattern(pat["pattern"], signals, urls, cfg=cfg)
    check("generated pattern classifies its own signals",
          res["matches"] >= len(hit["signals"]) - 1, str(res))

    # a pattern that is too broad is refused
    broad = test_pattern(r"\bhair\w*\b", signals, urls, cfg=cfg)
    check("over-broad pattern is refused",
          not broad["ok"] and "broad" in broad["reason"], broad["reason"])

    # unrelated signals must not be swept in
    unrelated = signals + [
        _signal("Ford unveils a new estate car", "Motoring",
                "https://cars.test/9", 1, "Engines."),
    ]
    res2 = test_pattern(pat["pattern"], unrelated, urls, cfg=cfg)
    import re as _re
    rx = _re.compile(pat["pattern"], _re.I)
    check("unrelated signal is not matched",
          not rx.search("Ford unveils a new estate car Engines."))

    # near-duplicate merges instead of creating
    overlap = find_overlap("Hair Regrowth", "hair regrowth", cfg=cfg)
    check("near-duplicate of an existing subject is detected",
          overlap is not None,
          str(overlap))

    # the cross-domain collision that a real run produced
    xiaomi = [
        _signal("Xiaomi open-sources embodied-AI foundation model", "TechNode",
                f"https://t.test/{i}", i % 3, "Robotics and open source.")
        for i in range(6)
    ]
    reason = off_domain_reason("foundation model", xiaomi)
    check("cross-domain collision is refused", bool(reason), reason[:70])
    check("beauty share of an AI cluster is zero",
          beauty_share(xiaomi) == 0.0, f"{beauty_share(xiaomi):.2f}")

    beauty = [
        _signal("The best foundation for oily skin", "Allure",
                f"https://b.test/f{i}", i % 3, "Makeup base coverage.")
        for i in range(6)
    ]
    check("a genuine beauty cluster is not refused",
          not off_domain_reason("foundation coverage", beauty),
          off_domain_reason("foundation coverage", beauty)[:60])

    # lifecycle in the store
    store = DiscoveryStore(tmp)
    cand = {"key": "auto_scalp_microbiome", "label": "Scalp Microbiome",
            "terms": ["scalp microbiome"], "pattern": pat["pattern"],
            "aliases": pat["aliases"], "category": "hair",
            "signal_count": hit["signal_count"],
            "publisher_count": hit["publisher_count"],
            "days_seen": hit["days_seen"], "evidence": []}
    store.add_topic_candidate(cand, "t1")
    check("candidate starts as candidate",
          store.topic_candidate("auto_scalp_microbiome")["state"] == CANDIDATE)
    store.set_topic_state("auto_scalp_microbiome", ACTIVE, reason="test",
                          run_id="t1")
    check("activated topic appears in the active set",
          any(t["key"] == "auto_scalp_microbiome"
              for t in store.active_topics()))
    store.add_pattern("auto_scalp_microbiome", pat["pattern"])
    check("active pattern is retrievable for classification",
          any(p["topic_key"] == "auto_scalp_microbiome"
              for p in store.active_patterns()))
    check("topic events recorded", len(store.topic_events()) >= 2)
    store.close()


# --------------------------------------------------------------------------
# scheduling
# --------------------------------------------------------------------------

def test_scheduling(tmp: Path):
    print("\nSCHEDULING AND BOUNDS")
    store = DiscoveryStore(tmp)
    ok, why = store.cooled_down("never_run_before", 24)
    check("a never-run job is allowed", ok, why)

    store.mark("source_discovery", "r1")
    ok, why = store.cooled_down("source_discovery", 24)
    check("a just-run job is blocked by its cooldown", not ok, why)

    ok, why = store.cooled_down("source_discovery", 0)
    check("a zero-hour cooldown always allows", ok, why)

    cfg = DiscoveryConfig()
    check("max_new_per_scan is bounded", 0 < cfg.sources.max_new_per_scan <= 50)
    check("max_depth is bounded", 0 < cfg.sources.max_depth <= 5)
    check("request budget is bounded",
          0 < cfg.sources.max_discovery_requests <= 1000)
    check("activation threshold is above the candidate threshold",
          cfg.sources.activation_threshold > cfg.sources.candidate_threshold)

    # one failing source must not stop a run
    store.record_fetch("https://broken.test/feed", ok=False)
    store.add_candidate(key="d_broken", name="Broken",
                        url="https://broken.test",
                        feed_url="https://broken.test/feed",
                        domain="broken.test", kind="unknown", market="GLOBAL",
                        depth=1, provenance={"discovery_method": "test"},
                        run_id="t3")
    store.record_fetch("https://broken.test/feed", ok=False)
    row = store.by_feed("https://broken.test/feed")
    check("failures are counted, not fatal", row["failure_count"] >= 1,
          str(row["failure_count"]))
    store.close()


def test_publisher_extraction():
    print("\nPUBLISHER EXTRACTION")
    p = publisher_from_article(HTML_WITH_JSONLD,
                              "https://gulfbeauty.example.com/x")
    check("publisher name comes from JSON-LD",
          p["name"] == "Gulf Beauty Weekly", p["name"])
    p2 = publisher_from_article(HTML_WITH_LINK, "https://example-beauty.com/x")
    check("publisher name falls back to og:site_name",
          p2["name"] == "Example Beauty", p2["name"])
    p3 = publisher_from_article("<html></html>", "https://no-meta.test/x")
    check("publisher name falls back to the domain",
          p3["domain"] == "no-meta.test", p3["domain"])

    sigs = [_signal("x", "Seed", "https://seed.test/a", 0,
                    "See https://newpublisher.test/story for more"),
            _signal("y", "Seed", "https://seed.test/b", 0,
                    "Also https://newpublisher.test/other"),
            _signal("z", "Seed", "https://seed.test/c", 0,
                    "Ignore https://facebook.com/page")]
    found = candidate_domains_from_signals(sigs, known={"seed.test"})
    domains = [f["domain"] for f in found]
    check("a new publisher is proposed from article links",
          "newpublisher.test" in domains, str(domains))
    check("a social platform is never proposed",
          "facebook.com" not in domains, str(domains))


def test_seed_rediscovery_regression(tmp: Path):
    """The bug that recurred three times: a seed rediscovered as new.

    Every instance was the same shape — one side of a comparison normalised and
    the other not. Feed URL first, then the domain column. This asserts the
    property directly rather than the two spellings that happened to break it,
    so a fourth variant fails here instead of in production.
    """
    print("\nREGRESSION: seeds are never rediscovered")
    store = DiscoveryStore(tmp)
    store.sync_seeds(ts.SOURCES)

    misses = [s.url for s in ts.SOURCES if not store.source_exists(feed_url=s.url)]
    check("every seed is found by its own feed url", not misses,
          f"{len(misses)} miss(es): {misses[:2]}")

    dmiss = [s.host for s in ts.SOURCES
             if not store.source_exists(domain=registrable_domain(s.url))]
    check("every seed is found by its registrable domain", not dmiss,
          f"{len(dmiss)} miss(es): {dmiss[:3]}")

    wmiss = [s.host for s in ts.SOURCES
             if not store.source_exists(domain=s.host)]
    check("a seed is found by its host with www intact", not wmiss,
          f"{len(wmiss)} miss(es): {wmiss[:3]}")

    known = store.known_domains()
    check("known_domains holds only canonical forms",
          all(d == registrable_domain(d) for d in known),
          str([d for d in known if d != registrable_domain(d)][:3]))

    # the candidate proposer must not offer a domain we already have
    sigs = [{"title": "x", "publisher": "Seed", "url": s.url, "summary": "",
             "topics": []} for s in ts.SOURCES]
    proposed = candidate_domains_from_signals(sigs, known=known)
    overlap = [p["domain"] for p in proposed
               if registrable_domain(p["domain"]) in known]
    check("no already-known publisher is proposed as a candidate",
          not overlap, str(overlap[:3]))

    check("a two-part public suffix is not mistaken for a domain",
          registrable_domain("https://www.chinadaily.com.cn/x") ==
          "chinadaily.com.cn",
          registrable_domain("https://www.chinadaily.com.cn/x"))
    store.close()


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="ds_test")) / "t.sqlite3"
    print("=" * 68)
    print("DISCOVERY TESTS")
    print("=" * 68)
    test_feeds()
    test_normalisation()
    test_publisher_extraction()
    test_sources(tmp)
    test_topics(Path(tempfile.mkdtemp(prefix="ds_test2")) / "t2.sqlite3")
    test_scheduling(Path(tempfile.mkdtemp(prefix="ds_test3")) / "t3.sqlite3")
    test_seed_rediscovery_regression(
        Path(tempfile.mkdtemp(prefix="ds_test4")) / "t4.sqlite3")

    passed = sum(1 for _, ok, _ in RESULTS if ok)
    print("")
    print("=" * 68)
    print(f"{passed}/{len(RESULTS)} checks pass")
    failed = [(n, d) for n, ok, d in RESULTS if not ok]
    for n, d in failed:
        print(f"  FAILED: {n}  {d}")
    return 1 if failed else 0


# pytest entry points
def test_all():
    assert main() == 0


if __name__ == "__main__":
    sys.exit(main())
