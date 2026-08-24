"""Finding a publisher's feed, and proving it is one.

Two functions with very different jobs. `discover_feeds` proposes candidates;
`validate_feed` refuses most of them. The asymmetry is the point — proposing is
cheap guesswork and accepting is a commitment the next scan has to live with.

**Discovery order, cheapest and most authoritative first.**

1. `<link rel="alternate" type="application/rss+xml">` in the page head. This is
   the publisher declaring its own feed, so it outranks everything below.
2. Feed URLs written into the page body — common on sites whose head is built by
   JavaScript.
3. `robots.txt`, which occasionally names a feed and always names sitemaps.
4. Sitemap index, for a `sitemap-feed`-style entry.
5. Conventional paths, tried last because they are pure guesswork: a `/feed` that
   answers is not evidence that the publisher meant it as their feed.

**Validation, and why HTTP 200 is not enough.** A URL earns a place only if the
body parses as RSS or Atom, carries enough entries to be worth scanning, those
entries have titles and links, the links point at the domain we think we are
talking to, and something in it touches the subject matter. Every one of those
has been observed failing on its own: WordPress serves a valid empty feed at
`/feed` on a parked domain; a CDN serves the homepage with a 200 for any path; a
syndication feed on a beauty domain carries nothing but motoring.

Nothing here fetches outside `access.guarded_get`, so robots, the politeness
delay and the block detection all still apply. A refusal is recorded as a
refusal, and no path is retried with different headers.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from urllib.parse import urljoin, urlsplit, urlunsplit

from .. import access, scope, trend_sources as ts
from ..agents.trend_collector import parse_feed

# Guesses, tried only after the publisher has been given every chance to declare
# its own feed. Ordered by how often each actually turns out to be the real one.
COMMON_PATHS = (
    "/feed", "/feed/", "/rss", "/rss.xml", "/atom.xml", "/feed.xml",
    "/index.xml", "/rss/news", "/feeds/posts/default", "/?feed=rss2",
    "/blog/feed", "/news/feed", "/en/feed",
)

LINK_RE = re.compile(
    r"""<link[^>]+?rel=["']?alternate["']?[^>]*?>""", re.I | re.S)
TYPE_RE = re.compile(r"""type=["']?(application/(?:rss|atom)\+xml)["']?""", re.I)
HREF_RE = re.compile(r"""href=["']([^"']+)["']""", re.I)
BODY_FEED_RE = re.compile(
    r"""https?://[^\s"'<>]+?(?:/feed/?|/rss(?:\.xml)?|/atom\.xml|feed\.xml)""",
    re.I)

# Whether a feed is a source at all, judged by the product frame: does it
# publish about the four families?
#
# The pattern that used to live here accepted any beauty word — skincare,
# makeup, nails, SPF, "wellness" — so a pure-skincare feed and a nail-art feed
# both registered as competitor sources and then filled the corpus with signals
# nothing in Clara's catalogue can act on.
#
# Counted per entry rather than applied all-or-nothing: a trade publication
# covers hair among other things and is still the right place to read about it.
# `min_relevant` below is what decides how much coverage makes a source.
RELEVANT = scope.IN_SCOPE

MAX_PATHS_PER_DOMAIN = 8


# --------------------------------------------------------------------------
# normalisation — the whole defence against rediscovering the same feed
# --------------------------------------------------------------------------

TRACKING = re.compile(r"^(utm_|fbclid|gclid|mc_cid|mc_eid|ref|source$)", re.I)


def normalise_url(url: str) -> str:
    """One canonical spelling per feed.

    Scheme, host case, `www.`, the trailing slash, tracking parameters and the
    fragment are all ways of writing the same feed, and every one of them has
    been seen in the wild. Without this the registry accumulates six rows for
    one publisher and the dedup check passes every time.
    """
    if not url:
        return ""
    u = url.strip()
    if not re.match(r"^https?://", u, re.I):
        u = "https://" + u.lstrip("/")
    parts = urlsplit(u)
    host = (parts.hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    if parts.port and parts.port not in (80, 443):
        host = f"{host}:{parts.port}"
    path = re.sub(r"/{2,}", "/", parts.path or "/")
    if len(path) > 1 and path.endswith("/"):
        path = path[:-1]
    keep = []
    for kv in (parts.query or "").split("&"):
        if not kv or "=" not in kv:
            if kv and not TRACKING.match(kv):
                keep.append(kv)
            continue
        k, _, v = kv.partition("=")
        if not TRACKING.match(k):
            keep.append(f"{k}={v}")
    return urlunsplit(("https", host, path or "/", "&".join(sorted(keep)), ""))


def registrable_domain(url_or_host: str) -> str:
    """The part that identifies the publisher. `en.vogue.co.uk` -> `vogue.co.uk`."""
    if not url_or_host:
        return ""
    host = url_or_host
    if "://" in host:
        host = urlsplit(host).hostname or ""
    host = host.lower().split(":")[0]
    if host.startswith("www."):
        host = host[4:]
    parts = [p for p in host.split(".") if p]
    if len(parts) < 3:
        return ".".join(parts)
    # Two-part public suffixes. `chinadaily.com.cn` collapsed to `com.cn`
    # without `com.cn` here, which put a suffix into the domain registry as
    # though it were a publisher.
    for suffix in ("co.uk", "com.sa", "com.au", "co.jp", "com.tr", "com.br",
                   "co.kr", "com.eg", "com.kw", "co.za", "com.mx", "co.in",
                   "com.hk", "co.nz", "com.cn", "com.sg", "com.my", "co.id",
                   "com.ph", "com.pk", "com.ng", "co.il", "com.ar", "com.co",
                   "org.uk", "ac.uk", "gov.uk", "net.au", "org.au"):
        if host.endswith("." + suffix):
            return ".".join(parts[-3:])
    return ".".join(parts[-2:])


def same_publisher(a: str, b: str) -> bool:
    return bool(a) and registrable_domain(a) == registrable_domain(b)


# --------------------------------------------------------------------------
# discovery
# --------------------------------------------------------------------------

def _fetch(url: str, allowed: set, budget: dict) -> tuple[str, str]:
    """One guarded fetch, counted against the run's request budget."""
    if budget["used"] >= budget["max"]:
        return "", "budget exhausted"
    budget["used"] += 1
    res = access.guarded_get(url, allowed_hosts=allowed, max_retries=1,
                             timeout=20)
    if not res.ok:
        return "", (res.block_signal or f"HTTP {res.status}")
    return (res.html or ""), ""


def _links_in_head(html: str, base: str) -> list[tuple[str, str]]:
    out = []
    for tag in LINK_RE.findall(html or ""):
        if not TYPE_RE.search(tag):
            continue
        m = HREF_RE.search(tag)
        if not m:
            continue
        out.append((urljoin(base, m.group(1)), "link_rel_alternate"))
    return out


def _links_in_body(html: str) -> list[tuple[str, str]]:
    return [(u, "feed_url_in_page") for u in
            dict.fromkeys(BODY_FEED_RE.findall(html or ""))][:6]


def _from_robots(text: str, base: str) -> list[tuple[str, str]]:
    out = []
    for line in (text or "").splitlines():
        low = line.strip().lower()
        if low.startswith("sitemap:"):
            url = line.split(":", 1)[1].strip()
            if re.search(r"feed|rss|atom", url, re.I):
                out.append((url, "robots_sitemap"))
        elif re.search(r"(?:allow|disallow):\s*/(?:feed|rss)", low):
            out.append((urljoin(base, low.split(":", 1)[1].strip()),
                        "robots_hint"))
    return out[:4]


def _from_sitemap(xml_text: str) -> list[tuple[str, str]]:
    try:
        root = ET.fromstring((xml_text or "").strip())
    except ET.ParseError:
        return []
    out = []
    for loc in root.iter():
        if not loc.tag.endswith("loc") or not (loc.text or "").strip():
            continue
        u = loc.text.strip()
        if re.search(r"feed|rss|atom", u, re.I):
            out.append((u, "sitemap"))
    return out[:4]


def discover_feeds(domain_or_url: str, *, allowed: set | None = None,
                   budget: dict | None = None,
                   try_common: bool = True) -> dict:
    """Candidate feed URLs for a publisher, best-evidence first.

    Returns the candidates and the trail of how each was proposed, so a source
    that later turns out to be junk can be traced back to the method that
    suggested it.
    """
    b = budget or {"used": 0, "max": 40}
    base = domain_or_url if "://" in domain_or_url else f"https://{domain_or_url}"
    host = urlsplit(base).hostname or domain_or_url
    allow = set(allowed or set())
    allow |= {host, host[4:] if host.startswith("www.") else "www." + host}

    found: list[tuple[str, str]] = []
    tried: list[dict] = []

    html, err = _fetch(base, allow, b)
    tried.append({"url": base, "ok": not err, "error": err})
    if html:
        found += _links_in_head(html, base)
        if not found:
            found += _links_in_body(html)

    if not found:
        robots, err = _fetch(urljoin(base + "/", "robots.txt"), allow, b)
        tried.append({"url": "robots.txt", "ok": not err, "error": err})
        hints = _from_robots(robots, base)
        for url, method in hints:
            if re.search(r"sitemap", method):
                sm, e2 = _fetch(url, allow, b)
                tried.append({"url": url, "ok": not e2, "error": e2})
                found += _from_sitemap(sm)
            else:
                found.append((url, method))

    if not found and try_common:
        for path in COMMON_PATHS[:MAX_PATHS_PER_DOMAIN]:
            found.append((urljoin(base + "/", path.lstrip("/")),
                          "common_path_guess"))

    # dedup on the normalised form, keeping the first (best-evidence) method
    seen, ordered = set(), []
    for url, method in found:
        n = normalise_url(url)
        if not n or n in seen:
            continue
        seen.add(n)
        ordered.append({"feed_url": n, "method": method})

    return {"domain": registrable_domain(base), "candidates": ordered,
            "tried": tried, "requests_used": b["used"]}


# --------------------------------------------------------------------------
# validation
# --------------------------------------------------------------------------

def validate_feed(feed_url: str, *, expect_domain: str = "",
                  allowed: set | None = None, budget: dict | None = None,
                  min_entries: int = 3, min_relevant: int = 2) -> dict:
    """Is this actually a usable feed for this publisher?

    Every rejection reason below has been observed on a real URL that returned
    HTTP 200, which is why none of them is skipped.
    """
    b = budget or {"used": 0, "max": 40}
    host = urlsplit(feed_url).hostname or ""
    allow = set(allowed or set())
    allow |= {host, host[4:] if host.startswith("www.") else "www." + host}

    out = {"feed_url": feed_url, "ok": False, "reason": "", "entries": 0,
           "usable": 0, "relevant": 0, "same_domain": False, "newest_at": "",
           "titles": []}

    body, err = _fetch(feed_url, allow, b)
    if err:
        out["reason"] = f"fetch failed: {err}"
        return out
    head = body[:2500].lower()
    if not ("<rss" in head or "<feed" in head or "rdf:rdf" in head):
        out["reason"] = "not RSS or Atom — the body is something else"
        return out

    items = parse_feed(body)
    out["entries"] = len(items)
    if not items:
        out["reason"] = "parses as a feed but contains no entries"
        return out

    usable = [i for i in items if (i.get("title") or "").strip()
              and (i.get("url") or "").strip()]
    out["usable"] = len(usable)
    if len(usable) < min_entries:
        out["reason"] = (f"only {len(usable)} entry/entries have both a title "
                         f"and a link; {min_entries} needed")
        return out

    target = expect_domain or registrable_domain(feed_url)
    on_domain = sum(1 for i in usable if same_publisher(i.get("url", ""), target))
    out["same_domain"] = on_domain >= max(1, len(usable) // 2)
    if not out["same_domain"]:
        out["reason"] = (f"entries do not point at {target} — this looks like a "
                         f"syndication feed for someone else")
        return out

    blob = " ".join(f"{i.get('title', '')} {i.get('summary', '')}"
                    for i in usable)
    out["relevant"] = sum(
        1 for i in usable
        if RELEVANT.search(f"{i.get('title', '')} {i.get('summary', '')}"))
    if out["relevant"] < min_relevant:
        out["reason"] = (f"only {out['relevant']} of {len(usable)} entries touch "
                         f"the subject matter; a well-formed feed about "
                         f"something else is still not a source")
        return out

    dates = [i.get("published_at") for i in usable if i.get("published_at")]
    out["newest_at"] = max(dates) if dates else ""
    out["titles"] = [i.get("title", "")[:90] for i in usable[:5]]
    out["ok"] = True
    out["reason"] = (f"{len(usable)} usable entry/entries, {out['relevant']} "
                     f"relevant, on {target}")
    return out
