"""The vocabulary of the Website Analysis module.

Six objects, named once, so the collector, the analyser, the comparator, the
report and the exports cannot drift into private dialects:

    AnalysisRun    one execution, its inputs, limits and warnings
    Website        Clara or a competitor, with its access status
    Page           one URL that was attempted, whether or not it answered
    Observation    something visible on a page, plus what it was read to mean
    Finding        a gap or a strength, located, evidenced, graded
    Recommendation what to do about a finding, and how urgently

Two distinctions carry most of the honesty in this module.

**Absent is not the same as not observed.** A competitor page that CAPTCHA'd is
not a competitor without social proof. `PresenceState` keeps the three answers
apart — `PRESENT`, `ABSENT` and `NOT_OBSERVED` — and a comparison may only claim
absence when the relevant page was actually read. This is the single rule most
likely to produce a confidently wrong recommendation if it is dropped.

**Interpretation is separated from observation.** Every `Observation` holds the
text or the image it saw *and*, separately, what the rubric read into it. The
first is a fact about a page; the second is this system's judgement, and a reader
can disagree with the second without doubting the first.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from urllib.parse import urlsplit, urlunsplit


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# --------------------------------------------------------------------------
# states
# --------------------------------------------------------------------------

class RunStatus:
    PENDING = "PENDING"
    COLLECTING = "COLLECTING"
    ANALYSING = "ANALYSING"
    COMPARING = "COMPARING"
    DONE = "DONE"
    FAILED = "FAILED"


class AccessStatus:
    """Why a page or a site did or did not answer.

    `BLOCKED` is terminal and goes to a human. Nothing in this module retries a
    block with different headers, a rotated agent or any credential — the access
    policy is not negotiable and a blocked page is a fact to report, not an
    obstacle to route around.
    """
    OK = "OK"
    BLOCKED = "BLOCKED"            # CAPTCHA, login wall, 403, robots
    NOT_FOUND = "NOT_FOUND"
    ERROR = "ERROR"
    SKIPPED = "SKIPPED"            # excluded by policy, e.g. cart or checkout
    NOT_ATTEMPTED = "NOT_ATTEMPTED"


BLOCK_REASON = {
    "robots_disallowed": "robots.txt disallows this path for our agent",
    "captcha": "the page served a CAPTCHA or bot-check interstitial",
    "login_required": "the content sits behind a sign-in",
    "forbidden": "the server answered 403 to a plain public request",
    "rate_limited": "the host rate-limited this run and was paused",
}


class PresenceState:
    """The three answers a comparison is allowed to give."""
    PRESENT = "PRESENT"
    WEAK = "WEAK"
    ABSENT = "ABSENT"
    NOT_OBSERVED = "NOT_OBSERVED"


PRESENCE_LABEL = {
    PresenceState.PRESENT: "present",
    PresenceState.WEAK: "present but weak",
    PresenceState.ABSENT: "not on the page",
    PresenceState.NOT_OBSERVED: "not observed",
}


class Priority:
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


PRIORITY_ORDER = (Priority.HIGH, Priority.MEDIUM, Priority.LOW)
PRIORITY_LABEL = {Priority.HIGH: "High", Priority.MEDIUM: "Medium",
                  Priority.LOW: "Low"}


class Confidence:
    """Same ladder, same rule, as the rest of the platform: only ever lowered."""
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    UNVERIFIED = "UNVERIFIED"


CONF_ORDER = (Confidence.HIGH, Confidence.MEDIUM, Confidence.LOW,
              Confidence.UNVERIFIED)


def never_upgrade(current: str, proposed: str) -> str:
    """Take the weaker of the two. A refinement may only lower confidence."""
    try:
        return proposed if CONF_ORDER.index(proposed) > CONF_ORDER.index(current) \
            else current
    except ValueError:
        return current


# --------------------------------------------------------------------------
# taxonomies
# --------------------------------------------------------------------------

class PageType:
    HOME = "home"
    PRODUCT = "product"
    CATEGORY = "category"
    ABOUT = "about"
    CONTACT = "contact"
    BLOG = "blog"
    FAQ = "faq"
    POLICY = "policy"
    LANDING = "landing"
    OTHER = "other"
    EXCLUDED = "excluded"


PAGE_TYPE_LABEL = {
    PageType.HOME: "Home", PageType.PRODUCT: "Product",
    PageType.CATEGORY: "Category or collection", PageType.ABOUT: "About",
    PageType.CONTACT: "Contact", PageType.BLOG: "Editorial or blog",
    PageType.FAQ: "FAQ or help", PageType.POLICY: "Policy",
    PageType.LANDING: "Campaign or landing", PageType.OTHER: "Other",
    PageType.EXCLUDED: "Excluded by policy",
}

# Comparison happens between equal page types. A "home vs product" comparison is
# not a comparison, it is a category error dressed as an insight.
COMPARABLE_TYPES = (PageType.HOME, PageType.PRODUCT, PageType.CATEGORY,
                    PageType.ABOUT, PageType.FAQ, PageType.BLOG,
                    PageType.CONTACT)


class ImageKind:
    """The image taxonomy the requirements name, unchanged."""
    PRODUCT = "product"
    LIFESTYLE = "lifestyle"
    USE_CASE = "use_case"
    INSTRUCTIONAL = "instructional"
    RESULT = "result"
    FEATURE_DETAIL = "feature_detail"
    SOCIAL_PROOF = "social_proof"
    TRUST = "trust"
    DECORATIVE = "decorative"
    UNCLASSIFIED = "unclassified"


IMAGE_KIND_LABEL = {
    ImageKind.PRODUCT: "Product shot",
    ImageKind.LIFESTYLE: "Lifestyle",
    ImageKind.USE_CASE: "Use case",
    ImageKind.INSTRUCTIONAL: "Instructional / how-to",
    ImageKind.RESULT: "Result / before-after",
    ImageKind.FEATURE_DETAIL: "Feature detail",
    ImageKind.SOCIAL_PROOF: "Social proof",
    ImageKind.TRUST: "Trust mark",
    ImageKind.DECORATIVE: "Decorative",
    ImageKind.UNCLASSIFIED: "Not classifiable from the page",
}

# What an image type is *for*. Used to explain a gap rather than merely count it:
# "no instructional images" means nothing until you say what they would do.
IMAGE_KIND_JOB = {
    ImageKind.PRODUCT: "shows the buyer what arrives",
    ImageKind.LIFESTYLE: "places the product in the buyer's life",
    ImageKind.USE_CASE: "answers 'is this for me and my hair'",
    ImageKind.INSTRUCTIONAL: "removes the fear of not knowing how to use it",
    ImageKind.RESULT: "shows the outcome the buyer is actually paying for",
    ImageKind.FEATURE_DETAIL: "makes a spec believable rather than claimed",
    ImageKind.SOCIAL_PROOF: "shows other people already chose it",
    ImageKind.TRUST: "answers 'is it safe to buy here'",
    ImageKind.DECORATIVE: "carries no information the buyer needs",
}


class ObservationType:
    HEADLINE = "headline"
    SUBHEAD = "subhead"
    BODY = "body"
    VALUE_PROP = "value_prop"
    CTA = "cta"
    IMAGE = "image"
    SOCIAL_PROOF = "social_proof"
    TRUST = "trust"
    USE_CASE = "use_case"
    OFFER = "offer"
    NAV = "nav"
    STRUCTURE = "structure"


OBS_TYPE_LABEL = {
    ObservationType.HEADLINE: "Headline", ObservationType.SUBHEAD: "Subhead",
    ObservationType.BODY: "Body copy",
    ObservationType.VALUE_PROP: "Value proposition",
    ObservationType.CTA: "Call to action", ObservationType.IMAGE: "Image",
    ObservationType.SOCIAL_PROOF: "Social proof",
    ObservationType.TRUST: "Trust element", ObservationType.USE_CASE: "Use case",
    ObservationType.OFFER: "Offer", ObservationType.NAV: "Navigation",
    ObservationType.STRUCTURE: "Page structure",
}


class FindingCategory:
    """What kind of thing was found. Drives grouping on the report."""
    COPY = "copy"
    CTA = "cta"
    IMAGERY = "imagery"
    SOCIAL_PROOF = "social_proof"
    TRUST = "trust"
    USE_CASE = "use_case"
    STRUCTURE = "structure"
    COVERAGE = "coverage"


CATEGORY_LABEL = {
    FindingCategory.COPY: "Copy and messaging",
    FindingCategory.CTA: "Calls to action",
    FindingCategory.IMAGERY: "Imagery",
    FindingCategory.SOCIAL_PROOF: "Social proof",
    FindingCategory.TRUST: "Trust and reassurance",
    FindingCategory.USE_CASE: "Use cases",
    FindingCategory.STRUCTURE: "Page structure",
    FindingCategory.COVERAGE: "Coverage and access",
}


class FindingKind:
    GAP = "gap"                    # a competitor has it, Clara does not
    WEAKNESS = "weakness"          # Clara has it, but it is thin
    STRENGTH = "strength"          # Clara does it better
    LIMITATION = "limitation"      # we could not tell, and that matters
    REPETITION = "repetition"      # Clara says the same thing repeatedly


KIND_LABEL = {
    FindingKind.GAP: "Gap", FindingKind.WEAKNESS: "Weak",
    FindingKind.STRENGTH: "Strength", FindingKind.LIMITATION: "Limitation",
    FindingKind.REPETITION: "Repetition",
}


class WebsiteRole:
    CLARA = "clara"
    COMPETITOR = "competitor"


# --------------------------------------------------------------------------
# url helpers
# --------------------------------------------------------------------------

# Pages excluded by default. Not content, and several of them are exactly the
# places where fetching would start touching an account.
EXCLUDE_PATH = re.compile(
    r"/(?:cart|basket|checkout|account|login|signin|sign-in|register|signup|"
    r"sign-up|logout|wishlist|my-account|orders?|customer|password|reset|"
    r"track(?:ing)?-?order|compare|search|admin|wp-admin|wp-login|feed|rss|"
    r"cdn-cgi|apple-app-site-association)(?:/|$|\?)", re.I)

EXCLUDE_EXT = re.compile(
    r"\.(?:png|jpe?g|gif|webp|avif|svg|ico|css|js|mjs|json|xml|txt|pdf|zip|"
    r"woff2?|ttf|eot|mp4|webm|mp3|wav|csv|xlsx?|docx?)$", re.I)

# Deliberately does NOT include `variant`: on most storefronts `?variant=` is a
# different product page, not the same page decorated, and collapsing them would
# merge two pages into one row.
TRACKING_PARAM = re.compile(
    r"^(?:utm_[a-z_]*|gclid|gbraid|wbraid|fbclid|msclkid|ttclid|igshid|mc_[a-z]+|"
    r"_ga|_gl|yclid|dclid|srsltid|sc_[a-z]+|pk_[a-z]+|mtm_[a-z]+|"
    r"campaign|referrer|aff(?:iliate)?_[a-z]+)$",
    re.I)


def normalise_url(url: str) -> str:
    """One canonical form, so the same page is never collected twice.

    Drops the fragment and tracking parameters, lowercases the host, strips a
    trailing slash. Keeps genuine query parameters, because on many storefronts
    `?variant=` is a different page rather than the same page decorated.
    """
    if not url:
        return ""
    p = urlsplit(url.strip())
    host = (p.hostname or "").lower()
    if not host:
        return ""
    if p.port and p.port not in (80, 443):
        host = f"{host}:{p.port}"
    path = re.sub(r"/{2,}", "/", p.path or "/")
    if len(path) > 1:
        path = path.rstrip("/")
    keep = [kv for kv in (p.query or "").split("&")
            if kv and not TRACKING_PARAM.match(kv.split("=")[0])]
    return urlunsplit((p.scheme.lower() or "https", host, path or "/",
                       "&".join(sorted(keep)), ""))


def registrable_host(url: str) -> str:
    return (urlsplit(url).hostname or "").lower().removeprefix("www.")


def same_site(a: str, b: str) -> bool:
    return bool(registrable_host(a)) and registrable_host(a) == registrable_host(b)


def key_of(*parts) -> str:
    raw = "|".join(str(p or "") for p in parts)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def classify_page(url: str, title: str = "", html_hint: str = "") -> str:
    """What kind of page this is, from its URL and title.

    URL-shape classification, deliberately. A model could read the page and do
    better, but this has to work with Vertex unavailable, and a page type that
    changes depending on whether a model answered would make two runs
    incomparable.
    """
    p = urlsplit(url)
    path = (p.path or "/").lower().rstrip("/")
    t = (title or "").lower()

    if EXCLUDE_PATH.search(path + "/"):
        return PageType.EXCLUDED
    if not path or path == "/":
        return PageType.HOME
    seg = [s for s in path.split("/") if s]
    # A locale root is the home page. Every localised storefront has one, and
    # classifying /en as "other" mis-sorts the most important page on the site.
    if len(seg) == 1 and re.fullmatch(
            r"[a-z]{2}(?:[-_][a-z]{2})?|[a-z]{2}-[a-z]{2}\.html?", seg[0], re.I):
        return PageType.HOME

    def has(*words):
        return any(w in path for w in words) or any(w in t for w in words)

    if has("/policy", "privacy", "terms", "refund", "shipping-policy",
           "return-policy", "cookie"):
        return PageType.POLICY
    if has("/faq", "help", "support", "question"):
        return PageType.FAQ
    if has("/about", "who-we-are", "our-story", "brand"):
        return PageType.ABOUT
    if has("/contact", "reach-us"):
        return PageType.CONTACT
    if has("/blog", "/news", "/article", "/journal", "/magazine", "/guide",
           "/tips"):
        return PageType.BLOG
    if has("/landing", "/lp/", "/promo", "/campaign", "/offer"):
        return PageType.LANDING
    # Product before category: a product URL usually carries an id or a long slug
    if has("/product", "/p/", "/item", "/products/"):
        return PageType.PRODUCT
    if has("/collection", "/category", "/shop", "/catalog", "/c/", "/all-"):
        return PageType.CATEGORY
    if len(seg) >= 2 and re.search(r"(?:^|[-/])(?:p|id)?\d{4,}$", seg[-1]):
        return PageType.PRODUCT
    if len(seg) == 1 and len(seg[0]) > 24:
        return PageType.PRODUCT
    return PageType.OTHER


# --------------------------------------------------------------------------
# records
# --------------------------------------------------------------------------

@dataclass
class Evidence:
    """Where an observation came from. No evidence, no finding."""
    url: str
    section: str = ""
    excerpt: str = ""
    image_url: str = ""
    screenshot: str = ""
    observed_at: str = field(default_factory=now_iso)
    note: str = ""

    def to_dict(self) -> dict:
        return dict(url=self.url, section=self.section, excerpt=self.excerpt,
                    image_url=self.image_url, screenshot=self.screenshot,
                    observed_at=self.observed_at, note=self.note)


@dataclass
class Website:
    key: str
    role: str
    name: str
    base_url: str
    access_status: str = AccessStatus.NOT_ATTEMPTED
    access_note: str = ""
    pages_attempted: int = 0
    pages_read: int = 0
    pages_blocked: int = 0

    def to_dict(self) -> dict:
        return dict(key=self.key, role=self.role, name=self.name,
                    base_url=self.base_url, access_status=self.access_status,
                    access_note=self.access_note,
                    pages_attempted=self.pages_attempted,
                    pages_read=self.pages_read,
                    pages_blocked=self.pages_blocked)


@dataclass
class Page:
    page_key: str
    site_key: str
    url: str
    title: str = ""
    page_type: str = PageType.OTHER
    status: str = AccessStatus.NOT_ATTEMPTED
    status_note: str = ""
    http_status: int | None = None
    collected_at: str = ""
    screenshot: str = ""
    render_method: str = "http"        # http | browser
    word_count: int = 0
    depth: int = 0

    @property
    def readable(self) -> bool:
        return self.status == AccessStatus.OK

    def to_dict(self) -> dict:
        return dict(page_key=self.page_key, site_key=self.site_key, url=self.url,
                    title=self.title, page_type=self.page_type,
                    status=self.status, status_note=self.status_note,
                    http_status=self.http_status, collected_at=self.collected_at,
                    screenshot=self.screenshot, render_method=self.render_method,
                    word_count=self.word_count, depth=self.depth)


@dataclass
class Observation:
    """Something visible, and separately what it was read to mean.

    `observed` is a fact about the page. `interpretation` is this system's
    reading of it. They are separate fields because a reader must be able to
    accept the first and reject the second.
    """
    obs_key: str
    page_key: str
    site_key: str
    section: str
    obs_type: str
    observed: str
    interpretation: str = ""
    image_kind: str = ""
    quality: str = ""                # strong | adequate | weak
    signals: list = field(default_factory=list)
    evidence: Evidence | None = None

    def to_dict(self) -> dict:
        return dict(obs_key=self.obs_key, page_key=self.page_key,
                    site_key=self.site_key, section=self.section,
                    obs_type=self.obs_type, observed=self.observed,
                    interpretation=self.interpretation,
                    image_kind=self.image_kind, quality=self.quality,
                    signals=list(self.signals),
                    evidence=self.evidence.to_dict() if self.evidence else None)


@dataclass
class Finding:
    finding_key: str
    category: str
    kind: str
    title: str
    clara_url: str = ""
    clara_section: str = ""
    clara_state: str = PresenceState.NOT_OBSERVED
    observed: str = ""               # what is actually on Clara's page
    competitor: str = ""
    competitor_url: str = ""
    competitor_example: str = ""
    why: str = ""
    confidence: str = Confidence.MEDIUM
    confidence_why: str = ""
    priority: str = Priority.MEDIUM
    priority_why: str = ""
    evidence: list = field(default_factory=list)
    page_type: str = ""

    def to_dict(self) -> dict:
        return dict(
            finding_key=self.finding_key, category=self.category,
            kind=self.kind, title=self.title, clara_url=self.clara_url,
            clara_section=self.clara_section, clara_state=self.clara_state,
            observed=self.observed, competitor=self.competitor,
            competitor_url=self.competitor_url,
            competitor_example=self.competitor_example, why=self.why,
            confidence=self.confidence, confidence_why=self.confidence_why,
            priority=self.priority, priority_why=self.priority_why,
            page_type=self.page_type,
            evidence=[e.to_dict() if isinstance(e, Evidence) else e
                      for e in self.evidence])


@dataclass
class Recommendation:
    """The seven parts section 6.7 requires, each its own field.

    Kept as separate fields rather than one paragraph so the report cannot ship a
    recommendation with a part quietly missing — an empty field is visible, a
    missing clause in prose is not.
    """
    rec_key: str
    finding_key: str
    what: str                        # what is missing, weak or better
    where: str                       # where on Clara's site
    who: str = ""                    # which competitor does it better
    why: str = ""                    # why it matters
    action: str = ""                 # what Clara should do
    priority: str = Priority.MEDIUM
    confidence: str = Confidence.MEDIUM
    owner: str = ""
    effort: str = ""
    evidence: list = field(default_factory=list)

    @property
    def complete(self) -> bool:
        """Whether every required part is present. The report shows this."""
        return all([self.what, self.where, self.why, self.action,
                    self.priority, self.confidence])

    def missing_parts(self) -> list:
        parts = {"what": self.what, "where": self.where, "why": self.why,
                 "action": self.action, "priority": self.priority,
                 "confidence": self.confidence}
        return [k for k, v in parts.items() if not v]

    def to_dict(self) -> dict:
        return dict(rec_key=self.rec_key, finding_key=self.finding_key,
                    what=self.what, where=self.where, who=self.who,
                    why=self.why, action=self.action, priority=self.priority,
                    confidence=self.confidence, owner=self.owner,
                    effort=self.effort, complete=self.complete,
                    missing_parts=self.missing_parts(),
                    evidence=[e.to_dict() if isinstance(e, Evidence) else e
                              for e in self.evidence])


@dataclass
class AnalysisRun:
    run_id: str
    status: str = RunStatus.PENDING
    clara_url: str = ""
    competitor_urls: list = field(default_factory=list)
    specific_pages: list = field(default_factory=list)
    audience: str = ""
    brand_guidelines: str = ""
    business_goals: str = ""
    page_limit: int = 12
    started_at: str = field(default_factory=now_iso)
    finished_at: str = ""
    warnings: list = field(default_factory=list)
    agent_version: str = ""
    decision_source: str = "deterministic_rules"
    requested_by: str = ""

    def warn(self, text: str) -> None:
        if text and text not in self.warnings:
            self.warnings.append(text)

    def to_dict(self) -> dict:
        return dict(run_id=self.run_id, status=self.status,
                    clara_url=self.clara_url,
                    competitor_urls=list(self.competitor_urls),
                    specific_pages=list(self.specific_pages),
                    audience=self.audience,
                    brand_guidelines=self.brand_guidelines,
                    business_goals=self.business_goals,
                    page_limit=self.page_limit, started_at=self.started_at,
                    finished_at=self.finished_at,
                    warnings=list(self.warnings),
                    agent_version=self.agent_version,
                    decision_source=self.decision_source,
                    requested_by=self.requested_by)
