"""Access control gate.

Every network read in this project goes through `guarded_get`. There is no
second path, deliberately: the constraint that autonomy must not bypass a
login, a CAPTCHA, an access restriction, a site's terms or a technical
control is enforced here in code, not left to a prompt to remember.

What this module will not do, by construction:

  * fetch a host that is not in the run's allowlist
  * fetch a path robots.txt disallows for our agent
  * send credentials, cookies or an Authorization header
  * vary the User-Agent to look like a different client
  * retry a 401/403/429/CAPTCHA response by any means
  * follow a redirect into a login page and keep going

Each of those returns a Blocked result carrying the signal that caused it.
The caller's only legal response is to escalate.
"""

from __future__ import annotations

import re
import time
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser
from dataclasses import dataclass, field

# One honest identity, used everywhere, never rotated.
USER_AGENT = (
    "ClaraCatalogMonitor/1.0 "
    "(competitor catalog monitoring; contact: ecommerce@clarahair.com)"
)

TIMEOUT = 45
MIN_INTERVAL_PER_HOST = 2.0   # politeness floor, seconds

# Blocking signals we classify rather than work around.
BLOCK_LOGIN = "login_required"
BLOCK_CAPTCHA = "captcha_challenge"
BLOCK_FORBIDDEN = "http_forbidden"
BLOCK_UNAUTHORIZED = "http_unauthorized"
BLOCK_RATE_LIMIT = "rate_limited"
BLOCK_ROBOTS = "robots_disallowed"
BLOCK_NOT_ALLOWLISTED = "host_not_in_allowlist"
BLOCK_PAYWALL = "paywall"
BLOCK_GEO = "geo_restricted"
BLOCK_UNAVAILABLE = "http_unavailable"
BLOCK_TRANSPORT = "transport_error"

_LOGIN_MARKERS = (
    "sign in to continue", "please log in", "please sign in",
    "login required", "create an account to view",
    "sign in to see price", "log in to view price",
)
# A genuine interstitial: these strings only appear on a challenge page.
_HARD_CHALLENGE_MARKERS = (
    "cf-challenge", "cf_chl_opt", "/cdn-cgi/challenge",
    "checking your browser before accessing", "verify you are human",
    "are you a human", "unusual traffic from your computer",
    "px-captcha", "please enable javascript and cookies to continue",
)
# Challenge-page titles.
_CHALLENGE_TITLES = ("just a moment", "attention required", "access denied",
                     "security check")
# Ambiguous on their own: a shop that embeds reCAPTCHA on its newsletter form
# contains these strings on every normal product page. They only indicate a
# block when the page ALSO looks like a challenge rather than a product page.
_SOFT_CAPTCHA_MARKERS = ("captcha", "recaptcha", "hcaptcha", "turnstile")

_PAYWALL_MARKERS = ("subscribe to read", "subscriber-only", "paywall")
_GEO_MARKERS = ("not available in your country", "not available in your region")

_last_hit: dict[str, float] = {}
_robots_cache: dict[str, urllib.robotparser.RobotFileParser | None] = {}


@dataclass
class FetchResult:
    url: str
    ok: bool
    status: int | None = None
    html: str | None = None
    final_url: str | None = None
    blocked: bool = False
    block_signal: str | None = None
    retry_after: float | None = None
    evidence: list[str] = field(default_factory=list)

    @property
    def host(self) -> str:
        return urllib.parse.urlsplit(self.final_url or self.url).netloc.lower()


def _blocked(url: str, signal: str, evidence: list[str], status: int | None = None) -> FetchResult:
    return FetchResult(
        url=url, ok=False, status=status, blocked=True,
        block_signal=signal, evidence=evidence,
    )


def host_allowed(url: str, allowed_hosts: set[str]) -> bool:
    host = urllib.parse.urlsplit(url).netloc.lower()
    if not host:
        return False
    host = host.split(":")[0]
    for d in allowed_hosts:
        d = d.lower()
        if host == d or host.endswith("." + d):
            return True
    return False


def _robots_for(scheme: str, host: str) -> urllib.robotparser.RobotFileParser | None:
    """Fetch and cache robots.txt. A robots.txt we cannot read is treated as
    permissive for public product pages, which is the standard reading — but
    an explicit Disallow is always honoured."""
    key = f"{scheme}://{host}"
    if key in _robots_cache:
        return _robots_cache[key]
    rp = urllib.robotparser.RobotFileParser()
    rp.set_url(f"{key}/robots.txt")
    try:
        req = urllib.request.Request(
            f"{key}/robots.txt", headers={"User-Agent": USER_AGENT}
        )
        with urllib.request.urlopen(req, timeout=20) as r:
            rp.parse(r.read().decode("utf-8", "replace").splitlines())
    except Exception:
        rp = None
    _robots_cache[key] = rp
    return rp


def robots_allows(url: str) -> tuple[bool, str]:
    parts = urllib.parse.urlsplit(url)
    rp = _robots_for(parts.scheme or "https", parts.netloc.lower())
    if rp is None:
        return True, "robots.txt not retrievable; treated as permissive for public pages"
    if rp.can_fetch(USER_AGENT, url) or rp.can_fetch("*", url):
        return True, "robots.txt allows this path"
    return False, f"robots.txt disallows {parts.path or '/'} for our agent"


def _looks_like_a_challenge_page(html: str) -> bool:
    """A challenge interstitial has no product payload and almost no text.

    Used to corroborate the ambiguous captcha markers, so that a normal
    product page which merely embeds a captcha widget for some unrelated
    form is not misread as a block. Over-blocking is not a safe default: it
    manufactures false escalations and hides readable data.
    """
    low = html.lower()
    m = re.search(r"<title[^>]*>(.*?)</title>", low, re.S)
    if m and any(t in m.group(1) for t in _CHALLENGE_TITLES):
        return True
    if "application/ld+json" in low and '"product"' in low:
        return False
    text = re.sub(r"<(script|style)\b[^>]*>.*?</(?:script|style)>", " ", html,
                  flags=re.S | re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return len(text) < 2000


def _detect_block_in_body(html: str) -> tuple[str | None, str | None]:
    low = html[:400_000].lower()

    for m in _HARD_CHALLENGE_MARKERS:
        if m in low:
            return BLOCK_CAPTCHA, m
    m = re.search(r"<title[^>]*>(.*?)</title>", low, re.S)
    if m:
        title = m.group(1).strip()
        for t in _CHALLENGE_TITLES:
            if t in title:
                return BLOCK_CAPTCHA, f"page title: {title[:60]!r}"

    for m in _LOGIN_MARKERS:
        if m in low:
            return BLOCK_LOGIN, m
    for m in _PAYWALL_MARKERS:
        if m in low:
            return BLOCK_PAYWALL, m
    for m in _GEO_MARKERS:
        if m in low:
            return BLOCK_GEO, m

    for m in _SOFT_CAPTCHA_MARKERS:
        if m in low and _looks_like_a_challenge_page(html):
            return BLOCK_CAPTCHA, f"{m} + page has no product payload"
    return None, None


def _throttle(host: str) -> None:
    last = _last_hit.get(host)
    if last is not None:
        wait = MIN_INTERVAL_PER_HOST - (time.time() - last)
        if wait > 0:
            time.sleep(wait)
    _last_hit[host] = time.time()


# §17 retry policy. Temporary failures only, bounded, with backoff and jitter.
# A retry never changes the request to be more aggressive or less identifiable —
# same URL, same single User-Agent, same headers. Permanent failures (404/410)
# and every blocking signal are terminal on the first response.
MAX_RETRIES = 3
BACKOFF_BASE = 1.5
BACKOFF_CAP = 20.0
RETRYABLE_STATUS = (500, 502, 503, 504, 507, 509)
RETRYABLE_SIGNALS = (BLOCK_TRANSPORT, BLOCK_UNAVAILABLE)

# Rate limiting is retryable only by waiting the period the site asked for, and
# only if that period is short enough to honour inside the run.
MAX_HONOURED_RETRY_AFTER = 60.0

# Set when a host returns systemic rate-limit/access failures: the target is
# paused for the rest of the run rather than hammered (§17).
_paused_hosts: dict[str, str] = {}


def _parse_retry_after(headers) -> float | None:
    if not headers:
        return None
    ra = headers.get("Retry-After")
    if not ra:
        return None
    try:
        return float(ra.strip())
    except (TypeError, ValueError):
        pass
    try:
        from email.utils import parsedate_to_datetime
        from datetime import datetime, timezone
        when = parsedate_to_datetime(ra)
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        return max(0.0, (when - datetime.now(timezone.utc)).total_seconds())
    except Exception:
        return None


def host_paused(url: str) -> str | None:
    host = urllib.parse.urlsplit(url).netloc.lower()
    return _paused_hosts.get(host)


def pause_host(url: str, reason: str) -> None:
    host = urllib.parse.urlsplit(url).netloc.lower()
    _paused_hosts.setdefault(host, reason)


def reset_pauses() -> None:
    _paused_hosts.clear()


def guarded_get(url: str, allowed_hosts: set[str],
                max_retries: int = MAX_RETRIES,
                timeout: int | None = None) -> FetchResult:
    """The only way this project reads a competitor page.

    Retries temporary timeout/network/5xx failures up to `max_retries` with
    exponential backoff and jitter, honouring Retry-After. Returns a
    FetchResult; `blocked=True` is terminal for the caller — escalate it, and
    never call again with different headers or credentials.
    """
    paused = host_paused(url)
    if paused:
        return _blocked(url, BLOCK_RATE_LIMIT,
                        [f"target paused for this run after: {paused}"])

    attempt = 0
    last: FetchResult | None = None
    while True:
        res = _guarded_get_once(url, allowed_hosts, timeout)
        last = res
        if res.ok or not res.blocked:
            if attempt:
                res.evidence.append(f"succeeded on attempt {attempt + 1}")
            return res

        retryable = res.block_signal in RETRYABLE_SIGNALS or (
            res.status in RETRYABLE_STATUS)
        rate_limited = res.block_signal == BLOCK_RATE_LIMIT

        if attempt >= max_retries - 1 or not (retryable or rate_limited):
            if rate_limited:
                pause_host(url, f"HTTP 429 after {attempt + 1} attempt(s)")
            res.evidence.append(
                f"not retried further after {attempt + 1} attempt(s): "
                f"{'retry budget spent' if retryable or rate_limited else 'failure is not transient'}")
            return res

        wait = min(BACKOFF_CAP, BACKOFF_BASE ** (attempt + 1))
        if rate_limited:
            ra = res.retry_after
            if ra is not None:
                if ra > MAX_HONOURED_RETRY_AFTER:
                    pause_host(url, f"Retry-After {ra:.0f}s exceeds the run budget")
                    res.evidence.append(
                        f"site asked for {ra:.0f}s; longer than this run will wait, "
                        f"target paused instead of retried")
                    return res
                wait = ra
        # Deterministic jitter from the URL: spreads retries without Math.random
        # style nondeterminism that would make a run irreproducible.
        jitter = (abs(hash(url)) % 1000) / 1000.0
        time.sleep(wait + jitter)
        attempt += 1


def _guarded_get_once(url: str, allowed_hosts: set[str],
                      timeout: int | None = None) -> FetchResult:
    if not host_allowed(url, allowed_hosts):
        return _blocked(
            url, BLOCK_NOT_ALLOWLISTED,
            [f"{urllib.parse.urlsplit(url).netloc} is not in the configured allowlist"],
        )

    allowed, why = robots_allows(url)
    if not allowed:
        return _blocked(url, BLOCK_ROBOTS, [why])

    host = urllib.parse.urlsplit(url).netloc.lower()
    _throttle(host)

    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "en",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout or TIMEOUT) as r:
            final_url = r.geturl()
            status = r.status
            raw = r.read()
    except urllib.error.HTTPError as e:
        code = e.code
        if code == 401:
            return _blocked(url, BLOCK_UNAUTHORIZED, ["HTTP 401 — authentication required"], code)
        if code == 403:
            return _blocked(url, BLOCK_FORBIDDEN, ["HTTP 403 — access refused by the site"], code)
        if code == 429:
            secs = _parse_retry_after(e.headers)
            r = _blocked(
                url, BLOCK_RATE_LIMIT,
                [f"HTTP 429 — rate limited by the site "
                 f"(Retry-After: {f'{secs:.0f}s' if secs is not None else 'unset'})"],
                code)
            r.retry_after = secs
            return r
        if code in (451, 452):
            return _blocked(url, BLOCK_GEO, [f"HTTP {code} — access restricted for legal/regional reasons"], code)
        if code in (404, 410):
            return FetchResult(url=url, ok=False, status=code,
                               evidence=[f"HTTP {code} — page no longer exists"])
        return _blocked(url, BLOCK_UNAVAILABLE, [f"HTTP {code} from the site"], code)
    except Exception as e:  # transport, DNS, TLS, timeout
        return _blocked(url, BLOCK_TRANSPORT, [f"{type(e).__name__}: {e}"])

    html = raw.decode("utf-8", "replace")

    # A redirect that landed us on a login/challenge page is still a block.
    if final_url != url:
        low_url = final_url.lower()
        if any(t in low_url for t in ("/login", "/signin", "/account/login", "/challenge")):
            return _blocked(
                url, BLOCK_LOGIN,
                [f"request redirected to an authentication page: {final_url}"], status,
            )

    signal, marker = _detect_block_in_body(html)
    if signal:
        return _blocked(url, signal, [f"page body contains blocking marker: {marker!r}"], status)

    return FetchResult(url=url, ok=True, status=status, html=html, final_url=final_url,
                       evidence=[f"HTTP {status}, {len(html)} chars read from {final_url}"])
