"""Conditional candidate discovery (§8).

Discovery is never the default path — `pipeline.py` only calls in here when a
stored match is missing or has failed validation. Every provider records why
discovery was triggered, the queries used, the candidate sources and the stop
reason, per §8's last bullet.

Three providers, tried in order of cost:
  SeedProvider      curated URLs — free, reproducible, used for fixtures
  SitemapProvider   the competitor's own sitemap, keyword-filtered — no search API
  LlmQueryProvider  Vertex-built queries handed to a search callable

All candidate URLs are normalized, deduplicated and capped per pair.
"""

from __future__ import annotations

import gzip
import io
import json
import re
import urllib.parse
from dataclasses import dataclass, field
from pathlib import Path

from . import competitors as comp
from .access import guarded_get
from .config import DATA_DIR

CANDIDATE_SEEDS = DATA_DIR / "candidate_seeds.json"

_STOP = {
    "the", "and", "with", "for", "hair", "your", "clara", "set", "kit",
    "professional", "new", "use", "pro",
}

# URL path fragments that are never a product page.
_NON_PRODUCT = re.compile(
    r"/(cart|checkout|account|login|blog|articles?|news|press|about|contact|"
    r"policy|policies|terms|privacy|faq|help|support|store-locator|"
    r"gift-?cards?|search|collections?/all|sitemap)(/|$|\?)", re.I)

_PRODUCT_HINT = re.compile(r"/(products?|p|shop|item|dp)(/|-)", re.I)


@dataclass
class DiscoveryLog:
    trigger: str
    provider_chain: list[str] = field(default_factory=list)
    queries: list[str] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)
    candidates_considered: list[str] = field(default_factory=list)
    stop_reason: str = ""
    blocks: list[dict] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "trigger": self.trigger,
            "provider_chain": self.provider_chain,
            "queries": self.queries,
            "sources": self.sources,
            "candidates_considered": self.candidates_considered,
            "stop_reason": self.stop_reason,
            "blocks": self.blocks,
        }


def normalize_url(url: str) -> str:
    """Drop tracking params and fragments so duplicates collapse."""
    try:
        p = urllib.parse.urlsplit(url)
    except ValueError:
        return url
    keep = [(k, v) for k, v in urllib.parse.parse_qsl(p.query)
            if not k.lower().startswith(("utm_", "gclid", "fbclid", "srsltid",
                                         "variant", "_pos", "_sid", "_ss"))]
    return urllib.parse.urlunsplit(
        (p.scheme or "https", p.netloc.lower(), p.path.rstrip("/") or "/",
         urllib.parse.urlencode(keep), ""))


def looks_like_product_url(url: str) -> bool:
    path = urllib.parse.urlsplit(url).path
    if not path or path == "/":
        return False
    if _NON_PRODUCT.search(path):
        return False
    return True


def keywords_for(product) -> list[str]:
    """Query tokens built from the Clara product's own attributes (§8)."""
    toks: list[str] = []
    fmt = (getattr(product, "fmt", "") or "").replace("_", " ")
    if fmt and fmt != "unknown":
        toks.extend(fmt.split())
    cat = getattr(product, "category", "") or ""
    if cat and cat not in ("unknown", "hair_styling_device"):
        toks.extend(cat.replace("_", " ").split())
    name = (getattr(product, "name", "") or "").lower()
    for t in re.findall(r"[a-z]{3,}", name):
        if t not in _STOP:
            toks.append(t)
    seen, out = set(), []
    for t in toks:
        if t not in seen:
            seen.add(t)
            out.append(t)
    return out[:8]


# --------------------------------------------------------------------------
# Providers
# --------------------------------------------------------------------------

class SeedProvider:
    """Curated candidate URLs, keyed by product id then by format."""

    name = "seed"

    def __init__(self, path: Path = CANDIDATE_SEEDS):
        self.map: dict = {}
        if path.exists():
            try:
                self.map = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                self.map = {}

    def candidates(self, product, competitor_key: str, budget: int,
                   log: DiscoveryLog) -> list[str]:
        urls = (self.map.get(product.product_id, {}).get(competitor_key)
                or self.map.get("_by_format", {})
                        .get(getattr(product, "fmt", ""), {})
                        .get(competitor_key)
                or [])
        if urls:
            log.sources.append(f"seed:{competitor_key}")
        return list(urls)[:budget]


class SitemapProvider:
    """Read the competitor's own sitemap and keyword-filter product URLs.

    This is real discovery with no search API: the sitemap is a source the site
    publishes for exactly this purpose, and it stays inside the allowlist.
    """

    name = "sitemap"
    MAX_SITEMAP_BYTES = 6_000_000
    MAX_URLS_SCANNED = 40_000
    MAX_NESTED_SITEMAPS = 4
    # Sitemaps are an optimisation, not the point of the run: they get a short
    # timeout, no retries, and one chance per competitor. A slow or missing
    # sitemap must not spend the run's whole time budget.
    SITEMAP_TIMEOUT = 12
    SITEMAP_RETRIES = 1

    def __init__(self):
        self._cache: dict[str, list[str]] = {}
        self._given_up: set[str] = set()

    def _fetch_sitemap(self, url: str, hosts: set[str], depth: int = 0) -> list[str]:
        if depth > 2 or url in self._cache:
            return self._cache.get(url, [])
        res = guarded_get(url, hosts, max_retries=self.SITEMAP_RETRIES,
                          timeout=self.SITEMAP_TIMEOUT)
        if not res.ok or not res.html:
            self._cache[url] = []
            return []
        body = res.html
        if url.endswith(".gz"):
            try:
                body = gzip.decompress(body.encode("latin-1", "ignore")).decode(
                    "utf-8", "replace")
            except Exception:
                pass
        locs = re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", body)
        # A sitemap index points at more sitemaps; follow a bounded number.
        if "<sitemapindex" in body:
            nested: list[str] = []
            for child in locs[: self.MAX_NESTED_SITEMAPS]:
                nested.extend(self._fetch_sitemap(child, hosts, depth + 1))
            self._cache[url] = nested[: self.MAX_URLS_SCANNED]
            return self._cache[url]
        self._cache[url] = locs[: self.MAX_URLS_SCANNED]
        return self._cache[url]

    def candidates(self, product, competitor_key: str, budget: int,
                   log: DiscoveryLog) -> list[str]:
        c = comp.get(competitor_key)
        if not c or not c.sitemaps or competitor_key in self._given_up:
            return []
        hosts = set(c.all_domains())
        kws = keywords_for(product)
        log.queries.extend(kws[:4])

        pool: list[str] = []
        for sm in c.sitemaps:
            got = self._fetch_sitemap(sm, hosts, 0)
            if got:
                log.sources.append(f"sitemap:{sm} ({len(got)} urls)")
            pool.extend(got)

        if not pool:
            self._given_up.add(competitor_key)
            log.sources.append(f"sitemap:{competitor_key} unavailable; not retried "
                               f"again this run")
            return []

        scored: list[tuple[int, str]] = []
        for u in pool:
            if not looks_like_product_url(u):
                continue
            low = u.lower()
            hits = sum(1 for k in kws if k in low)
            if hits == 0:
                continue
            if _PRODUCT_HINT.search(urllib.parse.urlsplit(u).path):
                hits += 1
            scored.append((hits, u))

        scored.sort(key=lambda t: (-t[0], len(t[1])))
        return [u for _, u in scored[:budget]]


class LlmQueryProvider:
    """Vertex-built queries handed to a search callable.

    `search_fn(query, domains, limit) -> list[url]` is supplied by the caller —
    in the ADK agent this is the Google Search sub-agent, restricted to the
    competitor's own domains.
    """

    name = "llm_search"

    def __init__(self, judge=None, search_fn=None):
        self.judge = judge
        self.search_fn = search_fn

    def candidates(self, product, competitor_key: str, budget: int,
                   log: DiscoveryLog) -> list[str]:
        if self.search_fn is None:
            return []
        c = comp.get(competitor_key)
        if not c:
            return []
        domains = c.all_domains()

        queries: list[str] = []
        if self.judge is not None and getattr(self.judge, "available", False):
            queries = self.judge.queries(
                {"name": product.name, "format": getattr(product, "fmt", ""),
                 "category": getattr(product, "category", ""),
                 "specs": getattr(product, "specs", {})},
                c.brand, domains)
        if not queries:
            fmt = (getattr(product, "fmt", "") or "").replace("_", " ")
            queries = [f"{c.brand} {fmt}".strip()]

        log.queries.extend(queries)
        found: list[str] = []
        for q in queries:
            if len(found) >= budget:
                break
            try:
                for u in self.search_fn(q, domains, budget - len(found)) or []:
                    if u not in found:
                        found.append(u)
            except Exception as e:
                log.blocks.append({"query": q, "signal": f"search_failed: {e}"})
        if found:
            log.sources.append(f"llm_search:{competitor_key}")
        return found[:budget]


# --------------------------------------------------------------------------
# Chain
# --------------------------------------------------------------------------

class DiscoveryChain:
    """Run providers cheapest-first until the budget is met."""

    def __init__(self, providers=None, judge=None, search_fn=None):
        self.providers = providers or [
            SeedProvider(),
            SitemapProvider(),
            LlmQueryProvider(judge=judge, search_fn=search_fn),
        ]

    def candidates(self, product, competitor_key: str, budget: int,
                   trigger: str) -> tuple[list[str], DiscoveryLog]:
        log = DiscoveryLog(trigger=trigger)
        found: list[str] = []
        for prov in self.providers:
            if len(found) >= budget:
                log.stop_reason = "candidate budget reached"
                break
            log.provider_chain.append(prov.name)
            try:
                got = prov.candidates(product, competitor_key,
                                      budget - len(found), log)
            except Exception as e:
                log.blocks.append({"provider": prov.name,
                                   "signal": f"{type(e).__name__}: {e}"})
                continue
            for u in got:
                n = normalize_url(u)
                if n not in found:
                    found.append(n)
        if not log.stop_reason:
            log.stop_reason = ("all providers exhausted" if not found
                               else f"{len(found)} candidate(s) collected")
        log.candidates_considered = list(found)
        return found[:budget], log
