"""Section 6.1: find the pages, read them, and record what happened either way.

Everything here goes through `access.guarded_get`, the project's only network
path. That is not a convention — it is what keeps robots.txt honoured, the User-
Agent unrotated, and credentials absent. The requirements are explicit that
autonomy does not authorise bypassing login, CAPTCHA or access controls, and the
shape of this module is what makes that true rather than merely stated: there is
no second fetch function to reach for.

**Browser rendering, and the one place it may read past a block.** Section 7 step
4 allows choosing browser rendering per page. For every competitor it is strictly
a re-render: `guarded_get` must already have succeeded, so robots allowed the path
and the host answered a plain public request, and the browser only adds a
screenshot and the post-JavaScript DOM to a page we were permitted to read. A
competitor that refused stays refused — working around another company's access
control is exactly what the requirements forbid.

The exception is **Clara's own site, and only Clara's own site.** Clara's
storefront serves a JavaScript bot-check at HTTP 200, so a plain fetch reads an
empty interstitial and this module cannot analyse the website it exists to
analyse. Rendering your own property in your own browser engine is not bypassing
anyone's controls. It is still narrow: robots is still honoured (a
robots-disallowed path is never rendered), no credentials or cookies are
injected, no CAPTCHA is solved, the User-Agent is the same one every other
request here sends, and `still_blocked()` checks the rendered document — if it is
itself a bot wall, the page stays blocked and goes to a human. `Collector._may_render`
is the single predicate that decides this, so the answer is auditable in one
place rather than threaded through call sites as a flag that could be passed by
accident.

**A blocked page is a result.** It gets a row, a reason and a place in the
coverage section, and the run continues. Section 13 requires that a blocked page
does not stop the remaining analysis, and the failure mode being guarded against
is worse than a crash: a competitor whose pages all CAPTCHA'd, silently recorded
as a competitor with no social proof and no trust marks.
"""

from __future__ import annotations

import html as _html
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.parse import urljoin, urlsplit

from .. import access
from .contracts import (AccessStatus, BLOCK_REASON, EXCLUDE_EXT, EXCLUDE_PATH,
                        Page, PageType, Website, WebsiteRole, classify_page,
                        key_of, normalise_url, now_iso, registrable_host,
                        same_site)

# --------------------------------------------------------------------------
# bounds
# --------------------------------------------------------------------------

# Section 6.1 asks for an administrator-defined page limit. These are the
# defaults; the setup screen can lower them. Deliberately small: this module
# exists to compare a handful of benchmark pages properly, not to crawl a site.
DEFAULT_PAGE_LIMIT = 12
MAX_PAGE_LIMIT = 40
DISCOVERY_DEPTH = 2
LINKS_PER_PAGE = 60
FETCH_TIMEOUT = 25

# At most this many pages of any one type, per site. Comparison needs breadth of
# page type, not depth in one: three product pages tell you roughly what one
# product page tells you and cost three times the budget.
PER_TYPE_CAP = 3

# Which page types are worth spending a limited budget on, in order. Discovery
# fills the budget from the top: a home page and a product page tell you more
# than nine policy pages.
TYPE_PRIORITY = (PageType.HOME, PageType.PRODUCT, PageType.CATEGORY,
                 PageType.ABOUT, PageType.FAQ, PageType.BLOG,
                 PageType.CONTACT, PageType.LANDING, PageType.OTHER,
                 PageType.POLICY)


# --------------------------------------------------------------------------
# html reading
# --------------------------------------------------------------------------

_SCRIPTY = re.compile(
    r"<(script|style|noscript|template|svg|iframe)\b[^>]*>.*?</\1>",
    re.I | re.S)
_COMMENT = re.compile(r"<!--.*?-->", re.S)
_TAG = re.compile(r"<[^>]+>")


def safe_print(msg: str) -> None:
    """Print without dying on a character the console cannot encode.

    Clara's storefront has Arabic slugs, and this ran on a cp1252 console. A
    progress line is not worth losing a nine-page collection run to, so
    unencodable characters are replaced rather than raised.
    """
    try:
        print(msg, flush=True)
    except UnicodeEncodeError:
        enc = (getattr(sys.stdout, "encoding", None) or "ascii")
        print(msg.encode(enc, "replace").decode(enc, "replace"), flush=True)


def strip_chrome(html: str) -> str:
    """Everything that is not visible page text, removed."""
    h = _COMMENT.sub(" ", html or "")
    return _SCRIPTY.sub(" ", h)


def text_of(fragment: str) -> str:
    """Visible text from a fragment, whitespace collapsed."""
    t = _TAG.sub(" ", strip_chrome(fragment or ""))
    return re.sub(r"\s+", " ", _html.unescape(t)).strip()


def title_of(html: str) -> str:
    m = re.search(r"<title[^>]*>(.*?)</title>", html or "", re.I | re.S)
    if m:
        return text_of(m.group(1))[:200]
    m = re.search(r'property=["\']og:title["\'][^>]*content=["\']([^"\']+)',
                  html or "", re.I)
    return _html.unescape(m.group(1)).strip()[:200] if m else ""


def site_name_of(html: str, url: str) -> str:
    """What the site calls itself, if it says. Falls back to the host."""
    for pat in (r'property=["\']og:site_name["\'][^>]*content=["\']([^"\']+)',
                r'content=["\']([^"\']+)["\'][^>]*property=["\']og:site_name'):
        m = re.search(pat, html or "", re.I)
        if m:
            name = _html.unescape(m.group(1)).strip()
            if 1 < len(name) < 60:
                return name
    host = registrable_host(url)
    return host.split(".")[0].replace("-", " ").title() if host else url


def links_in(html: str, base_url: str) -> list:
    """Same-site content links, normalised and de-duplicated, in page order."""
    out, seen = [], set()
    for m in re.finditer(r'<a\b[^>]*href=["\']([^"\'#]+)', strip_chrome(html or ""),
                         re.I):
        raw = m.group(1).strip()
        if raw.lower().startswith(("mailto:", "tel:", "javascript:", "data:")):
            continue
        url = normalise_url(urljoin(base_url, raw))
        if not url or url in seen or not same_site(url, base_url):
            continue
        path = urlsplit(url).path or "/"
        if EXCLUDE_EXT.search(path) or EXCLUDE_PATH.search(path + "/"):
            continue
        seen.add(url)
        out.append(url)
        if len(out) >= LINKS_PER_PAGE:
            break
    return out


# --------------------------------------------------------------------------
# the browser layer
# --------------------------------------------------------------------------

CHROME_CANDIDATES = (
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    "/usr/bin/google-chrome", "/usr/bin/chromium",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
)


def find_browser() -> str:
    """A local Chromium, or empty. Screenshots are best-effort by requirement."""
    for name in ("chrome", "chromium", "google-chrome", "msedge"):
        p = shutil.which(name)
        if p:
            return p
    for c in CHROME_CANDIDATES:
        if Path(c).exists():
            return c
    return ""


def browser_status() -> dict:
    """Whether screenshots are technically possible, stated rather than assumed.

    Sections 8 and 13 both qualify screenshots with "where technically possible".
    This is that qualification, made explicit and put on the page, so an absent
    screenshot is a known limitation rather than a silent omission.
    """
    exe = find_browser()
    return {
        "available": bool(exe),
        "engine": Path(exe).stem if exe else "",
        "why": ("a local Chromium was found, so high-priority findings can carry "
                "a screenshot" if exe else
                "no local Chromium was found, so evidence is text excerpts and "
                "URLs only; findings say so rather than implying a screenshot "
                "was declined"),
    }


def render_dom(url: str, *, timeout: int = 40) -> dict:
    """The post-JavaScript DOM of a page, via a local headless browser.

    Section 7 step 4 allows choosing browser rendering per page. This is that
    path, and it exists because of a real problem: Clara's own storefront serves
    a JavaScript bot-check at HTTP 200, so the plain guarded fetch reads an empty
    interstitial and the module cannot analyse the site it exists to analyse.

    **Who this is allowed for is decided by the caller, and it is Clara only.**
    See `Collector.fetch`. Rendering your own website in your own browser engine
    is looking at your own property; doing it to a competitor that refused a
    plain request would be working around their access control, which the
    requirements forbid outright. There is no flag anywhere that turns this on
    for a competitor.

    What it still does not do: no credentials, no cookie injection, no CAPTCHA
    solving, no retry with a different identity. It sends the same User-Agent as
    every other request this project makes. If the rendered DOM is still a
    bot-check, the page stays blocked and goes to a human.
    """
    exe = find_browser()
    if not exe:
        return {"ok": False, "why": "no local browser"}
    profile = Path(tempfile.mkdtemp(prefix="clara-dom-"))
    args = [
        exe, "--headless=new", "--disable-gpu", "--no-first-run",
        "--no-default-browser-check", "--disable-extensions", "--mute-audio",
        f"--user-data-dir={profile}",
        f"--user-agent={access.USER_AGENT}",
        "--window-size=1280,1800",
        "--virtual-time-budget=8000",
        "--dump-dom", url,
    ]
    try:
        r = subprocess.run(args, capture_output=True, timeout=timeout)
        dom = (r.stdout or b"").decode("utf-8", "replace")
        if len(dom) < 500:
            return {"ok": False, "why": "the browser returned an empty document"}
        return {"ok": True, "html": dom}
    except subprocess.TimeoutExpired:
        return {"ok": False, "why": f"the browser did not finish in {timeout}s"}
    except OSError as e:
        return {"ok": False, "why": f"{type(e).__name__}: {e}"}
    finally:
        shutil.rmtree(profile, ignore_errors=True)


def still_blocked(html: str) -> str:
    """Whether a rendered document is itself a bot wall.

    The browser path must not be able to launder a block into a success. If what
    came back is an interstitial, this says so and the page stays blocked.
    """
    head = (html or "")[:6000].lower()
    for needle, why in (
            ("recaptcha", "the rendered page is still a reCAPTCHA challenge"),
            ("hcaptcha", "the rendered page is still an hCaptcha challenge"),
            ("cf-challenge", "the rendered page is still a Cloudflare challenge"),
            ("checking your browser", "the rendered page is still a bot check"),
            ("captcha", "the rendered page still mentions a CAPTCHA gate"),
            ("enable javascript to continue",
             "the rendered page still demands JavaScript it did not run")):
        if needle in head:
            return why
    if len(re.sub(r"\s+", " ", _TAG.sub(" ", head)).strip()) < 200:
        return "the rendered page carried almost no text"
    return ""


def render_with_browser(url: str, out_dir: Path, *, width: int = 1280,
                        height: int = 1800, timeout: int = 40) -> dict:
    """Screenshot and post-JavaScript DOM for a page we were ALREADY allowed to read.

    Called only after `guarded_get` returned ok for this exact URL. That ordering
    is the whole safety argument: robots has been consulted, the host answered a
    plain public request, and this adds a picture of what a visitor sees. The
    same User-Agent is passed so the site sees one identity from us, not two.
    """
    exe = find_browser()
    if not exe:
        return {"ok": False, "why": "no local browser"}

    out_dir.mkdir(parents=True, exist_ok=True)
    shot = out_dir / f"{key_of(url)}.png"
    profile = Path(tempfile.mkdtemp(prefix="clara-shot-"))
    args = [
        exe, "--headless=new", "--disable-gpu", "--hide-scrollbars",
        "--no-first-run", "--no-default-browser-check", "--disable-extensions",
        "--disable-background-networking", "--mute-audio",
        f"--user-data-dir={profile}",
        f"--user-agent={access.USER_AGENT}",
        f"--window-size={width},{height}",
        f"--screenshot={shot}",
        "--virtual-time-budget=6000",
        url,
    ]
    try:
        r = subprocess.run(args, capture_output=True, timeout=timeout)
        ok = shot.exists() and shot.stat().st_size > 2000
        return {
            "ok": ok,
            "screenshot": str(shot) if ok else "",
            "why": "" if ok else
                   (r.stderr or b"").decode("utf-8", "replace")[-160:] or
                   "the browser produced no usable image",
        }
    except subprocess.TimeoutExpired:
        return {"ok": False, "why": f"the browser did not finish in {timeout}s"}
    except OSError as e:
        return {"ok": False, "why": f"{type(e).__name__}: {e}"}
    finally:
        shutil.rmtree(profile, ignore_errors=True)


# --------------------------------------------------------------------------
# collection
# --------------------------------------------------------------------------

def _status_from(res) -> tuple[str, str]:
    """Translate a FetchResult into an access status plus a readable reason."""
    if res.ok:
        return AccessStatus.OK, ""
    if res.blocked:
        why = BLOCK_REASON.get(res.block_signal or "",
                               res.block_signal or "blocked")
        return AccessStatus.BLOCKED, why
    if res.status == 404:
        return AccessStatus.NOT_FOUND, "the server answered 404"
    if res.status:
        return AccessStatus.ERROR, f"the server answered {res.status}"
    return AccessStatus.ERROR, "; ".join(res.evidence[-2:]) or "no response"


class Collector:
    """Discovery and collection for one website.

    Holds the fetched HTML in memory for the analyser and writes a `Page` row for
    every URL attempted, readable or not.
    """

    def __init__(self, *, page_limit: int = DEFAULT_PAGE_LIMIT,
                 shots_dir: Path | None = None, want_shots: bool = True,
                 per_type_cap: int = PER_TYPE_CAP,
                 allow_own_site_render: bool = True, verbose: bool = False):
        self.page_limit = max(1, min(int(page_limit or DEFAULT_PAGE_LIMIT),
                                     MAX_PAGE_LIMIT))
        self.shots_dir = shots_dir
        self.want_shots = want_shots and bool(find_browser())
        self.per_type_cap = max(1, int(per_type_cap or PER_TYPE_CAP))
        # Clara's own site only. See `_may_render`.
        self.allow_own_site_render = bool(allow_own_site_render)
        self.verbose = verbose
        self.html: dict = {}          # page_key -> html
        self.blocked: list = []       # for the human-action list

    def say(self, msg: str) -> None:
        if self.verbose:
            safe_print(f"    {msg}")

    def _may_render(self, site: Website) -> bool:
        """Whether a browser may read a page the plain request could not.

        Clara's own site: yes — it is the operator's property and the module
        exists to analyse it. Any competitor: no, unconditionally. Kept as a
        one-line predicate so the answer is auditable in one place rather than
        being an argument threaded through four call sites where it could be
        passed True by accident.
        """
        return bool(self.allow_own_site_render
                    and site.role == WebsiteRole.CLARA
                    and find_browser())

    # ---------------- one page ----------------

    def fetch(self, site: Website, url: str, depth: int = 0,
              shot: bool = False) -> Page:
        url = normalise_url(url)
        pk = key_of(site.key, url)
        page = Page(page_key=pk, site_key=site.key, url=url, depth=depth,
                    collected_at=now_iso())

        if EXCLUDE_PATH.search((urlsplit(url).path or "/") + "/"):
            page.status = AccessStatus.SKIPPED
            page.page_type = PageType.EXCLUDED
            page.status_note = ("excluded by policy: account, cart, checkout or "
                                "search pages are not content and are where a "
                                "fetch would start touching an account")
            return page

        host = urlsplit(url).hostname or ""
        allowed = {host, host.removeprefix("www."), "www." + host.removeprefix("www.")}
        res = access.guarded_get(url, allowed_hosts=allowed, max_retries=1,
                                 timeout=FETCH_TIMEOUT)
        page.http_status = res.status
        page.status, page.status_note = _status_from(res)

        # The one exception, and it is scoped to Clara's own site. Clara's
        # storefront serves a JavaScript bot-check at HTTP 200, so without this
        # the module cannot read the website it exists to analyse. Robots was
        # already consulted by the fetch above and is still respected: a
        # robots_disallowed block is never rendered. No credentials, no CAPTCHA
        # solving, same User-Agent — and if the rendered DOM is still a wall, the
        # page stays blocked.
        if page.status == AccessStatus.BLOCKED and self._may_render(site) \
                and res.block_signal != access.BLOCK_ROBOTS:
            out = render_dom(url)
            wall = still_blocked(out.get("html", "")) if out.get("ok") else ""
            if out.get("ok") and not wall:
                page.status = AccessStatus.OK
                page.render_method = "browser"
                page.status_note = (
                    f"the plain request was met with a bot-check "
                    f"({res.block_signal}); read with a local browser instead, "
                    f"which is permitted here because this is Clara's own site")
                res = type(res)(url=url, ok=True, status=res.status,
                                html=out["html"], final_url=url)
                self.say(f"rendered (own site): {url}")
            else:
                page.status_note += (
                    f"; the browser could not read it either: "
                    f"{wall or out.get('why', 'unknown')}")

        if page.status == AccessStatus.BLOCKED:
            # Terminal. Recorded for a human and never retried differently.
            self.blocked.append({
                "site": site.name, "url": url, "signal": res.block_signal,
                "why": page.status_note,
                "what_a_human_can_do": (
                    "open this URL in a normal browser and read the section by "
                    "hand, or ask the site owner for access. Nothing in this "
                    "system will attempt it again with different headers."),
                "at": now_iso()})
            self.say(f"blocked: {url} ({page.status_note})")
            return page

        if page.status != AccessStatus.OK:
            self.say(f"{page.status.lower()}: {url} ({page.status_note})")
            return page

        body = res.html or ""
        self.html[pk] = body
        page.title = title_of(body)
        page.page_type = classify_page(url, page.title, body[:4000])
        page.word_count = len(text_of(body).split())

        # Browser re-render, only for a page the guarded path already read.
        if shot and self.want_shots and self.shots_dir:
            out = render_with_browser(url, self.shots_dir)
            if out.get("ok"):
                page.screenshot = out["screenshot"]
                page.render_method = "browser"
            else:
                page.status_note = (page.status_note or "") + \
                    f" (no screenshot: {out.get('why', 'unknown')})"
        self.say(f"read: {url} [{page.page_type}] {page.word_count} words")
        return page

    # ---------------- one site ----------------

    def collect_site(self, site: Website, *, specific: list | None = None) -> list:
        """The home page, then a bounded, prioritised walk of same-site links.

        Specific pages, when the user supplied them, are collected first and
        always — section 6.1 says they must be included or prioritised, and a
        page the user named being crowded out by discovery would make the input
        pointless.
        """
        pages: list = []
        seen: set = set()

        def take(url: str, depth: int, shot: bool) -> Page | None:
            u = normalise_url(url)
            if not u or u in seen:
                return None
            seen.add(u)
            site.pages_attempted += 1
            p = self.fetch(site, u, depth, shot=shot)
            if p.status == AccessStatus.OK:
                site.pages_read += 1
            elif p.status == AccessStatus.BLOCKED:
                site.pages_blocked += 1
            pages.append(p)
            return p

        # The base URL first: it decides the site's own access status and gives
        # the site its name.
        root = take(site.base_url, 0, shot=True)
        if root is not None:
            if root.status == AccessStatus.OK:
                site.access_status = AccessStatus.OK
                site.name = site_name_of(self.html.get(root.page_key, ""),
                                         site.base_url) or site.name
            else:
                site.access_status = root.status
                site.access_note = root.status_note

        # Pages the user named.
        for u in (specific or []):
            if len(pages) >= self.page_limit:
                break
            if same_site(u, site.base_url):
                take(u, 0, shot=True)

        # Then discovery, breadth-first, prioritised by page type.
        frontier = []
        if root is not None and root.page_key in self.html:
            frontier = [(u, 1) for u in links_in(self.html[root.page_key],
                                                 site.base_url)]

        # Breadth of page *type* comes before type priority. The first real run
        # of this spent its entire budget on eight locale copies of ghd's home
        # page — /au, /dk, /de, /es — every one classified home, every one the
        # same page. A budget of ten pages buys nothing if it buys ten of the
        # same thing, so the scarcest type wins each pick and the frontier is
        # re-ranked after every take, because taking a page changes what is
        # scarce.
        def rank(item):
            ptype = classify_page(item[0])
            return (sum(1 for p in pages if p.page_type == ptype),
                    TYPE_PRIORITY.index(ptype)
                    if ptype in TYPE_PRIORITY else 99,
                    item[1], len(item[0]))

        while frontier and len(pages) < self.page_limit:
            frontier.sort(key=rank)
            url, d = frontier.pop(0)
            ptype = classify_page(url)
            if ptype == PageType.EXCLUDED or d > DISCOVERY_DEPTH:
                continue
            if sum(1 for p in pages if p.page_type == ptype) >= self.per_type_cap:
                continue
            # One screenshot per page type: a limited budget should not be spent
            # photographing nine variants of one layout.
            shot_kinds = {p.page_type for p in pages if p.screenshot}
            p = take(url, d, shot=ptype not in shot_kinds)
            if p is not None and p.status == AccessStatus.OK \
                    and d < DISCOVERY_DEPTH and p.page_key in self.html:
                known = {u for u, _ in frontier} | seen
                frontier.extend(
                    (u, d + 1) for u in links_in(self.html[p.page_key],
                                                 site.base_url)
                    if u not in known)

        if site.access_status == AccessStatus.OK and site.pages_read == 0:
            site.access_status = AccessStatus.ERROR
            site.access_note = "the base URL answered but no page could be read"
        return pages


def website_from_url(url: str, role: str, name: str = "") -> Website:
    u = normalise_url(url)
    host = registrable_host(u)
    return Website(key=key_of(role, host or u), role=role,
                   name=name or (host.split(".")[0].title() if host else u),
                   base_url=u)


def validate_inputs(clara_url: str, competitor_urls: list) -> tuple[list, list]:
    """Section 7 step 1. Returns (usable urls, complaints).

    A bad URL is reported rather than guessed at. Silently correcting a typo into
    a different real website is worse than refusing it.
    """
    problems = []

    def check(raw: str, label: str) -> str:
        u = (raw or "").strip()
        if not u:
            return ""
        if not u.lower().startswith(("http://", "https://")):
            u = "https://" + u
        n = normalise_url(u)
        host = urlsplit(n).hostname or ""
        if not n or "." not in host or " " in host:
            problems.append(f"{label}: {raw!r} is not a usable website address")
            return ""
        return n

    clara = check(clara_url, "Clara URL")
    if not clara:
        problems.append("A Clara URL is required.")

    rivals, seen = [], set()
    for i, raw in enumerate(competitor_urls or [], 1):
        u = check(raw, f"Competitor {i}")
        if not u:
            continue
        h = registrable_host(u)
        if h == registrable_host(clara):
            problems.append(f"Competitor {i}: {h} is Clara's own site, skipped")
            continue
        if h in seen:
            problems.append(f"Competitor {i}: {h} was given twice, kept once")
            continue
        seen.add(h)
        rivals.append(u)

    if clara and not rivals:
        problems.append("At least one competitor URL is required.")
    return ([clara] + rivals if clara and rivals else []), problems
