"""The vocabulary every competitor-intelligence agent shares.

One module holds the enums and record shapes so that seven agents cannot drift
into seven slightly different meanings of "verified" or "active". The rules that
are stated as prose in the agent prompts are enforced here as code wherever they
can be, because a rule that lives only in a prompt is a rule that a bad model day
can ignore:

* `Confidence.never_upgrade` makes "never convert LOW or UNVERIFIED information
  into facts" mechanical — a later step can lower a confidence but cannot raise
  one, whatever it claims.
* `OfferStatus` has no default of ACTIVE. An offer that was not re-observed this
  run comes back UNKNOWN, never carried forward as live.
* `Evidence` cannot be constructed without a source. There is no field to hold an
  unsourced assertion, so an agent that has nothing to cite has nothing to store.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# --------------------------------------------------------------------------
# confidence
# --------------------------------------------------------------------------

class Confidence:
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    UNVERIFIED = "UNVERIFIED"

    ORDER = {UNVERIFIED: 0, LOW: 1, MEDIUM: 2, HIGH: 3}
    ALL = (HIGH, MEDIUM, LOW, UNVERIFIED)

    @classmethod
    def rank(cls, value: str) -> int:
        return cls.ORDER.get((value or "").upper(), 0)

    @classmethod
    def weakest(cls, *values: str) -> str:
        """The lowest confidence among the inputs.

        A finding is only as good as its weakest supporting claim, so combining
        evidence lowers confidence rather than raising it.
        """
        vals = [v for v in values if v]
        if not vals:
            return cls.UNVERIFIED
        return min(vals, key=cls.rank)

    @classmethod
    def never_upgrade(cls, current: str, proposed: str) -> str:
        """Apply a proposed confidence, but only downward.

        The prompts say weak evidence is never upgraded into a verified fact.
        This is where that stops being advice: only the Verification Agent may
        raise a confidence, and it does so by constructing the record afresh
        from its own evidence rather than by calling this.
        """
        if cls.rank(proposed) < cls.rank(current):
            return proposed
        return current

    @classmethod
    def is_fact(cls, value: str) -> bool:
        """Whether a value may be stated without a hedge."""
        return cls.rank(value) >= cls.ORDER[cls.MEDIUM]


# --------------------------------------------------------------------------
# statuses
# --------------------------------------------------------------------------

class DiscoveryStatus:
    NEW = "NEW"
    EXISTING = "EXISTING"
    POSSIBLE = "POSSIBLE"
    DUPLICATE = "DUPLICATE"
    IRRELEVANT = "IRRELEVANT"
    ALL = (NEW, EXISTING, POSSIBLE, DUPLICATE, IRRELEVANT)


class OfferStatus:
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    CHANGED = "CHANGED"
    UNKNOWN = "UNKNOWN"
    UNVERIFIED = "UNVERIFIED"
    ALL = (ACTIVE, EXPIRED, CHANGED, UNKNOWN, UNVERIFIED)

    # Only these reach the "Live Competitor Offers" section.
    LIVE = (ACTIVE, CHANGED)


class VerificationStatus:
    VERIFIED = "VERIFIED"
    PARTIALLY_VERIFIED = "PARTIALLY_VERIFIED"
    UNVERIFIED = "UNVERIFIED"
    CONTRADICTED = "CONTRADICTED"
    EXPIRED = "EXPIRED"
    INVALID = "INVALID"
    DUPLICATE = "DUPLICATE"
    ALL = (VERIFIED, PARTIALLY_VERIFIED, UNVERIFIED, CONTRADICTED, EXPIRED,
           INVALID, DUPLICATE)

    # What each verdict permits the claim to become.
    CEILING = {
        VERIFIED: Confidence.HIGH,
        PARTIALLY_VERIFIED: Confidence.MEDIUM,
        UNVERIFIED: Confidence.UNVERIFIED,
        CONTRADICTED: Confidence.UNVERIFIED,
        EXPIRED: Confidence.UNVERIFIED,
        INVALID: Confidence.UNVERIFIED,
        DUPLICATE: Confidence.UNVERIFIED,
    }


class ChangeType:
    NEW_COMPETITOR = "NEW_COMPETITOR"
    REMOVED_COMPETITOR = "REMOVED_COMPETITOR"
    COMPETITOR_CHANGED = "COMPETITOR_CHANGED"
    NEW_PRODUCT = "NEW_PRODUCT"
    PRODUCT_CHANGED = "PRODUCT_CHANGED"
    FEATURE_CHANGED = "FEATURE_CHANGED"
    PRICE_CHANGED = "PRICE_CHANGED"
    NEW_OFFER = "NEW_OFFER"
    OFFER_CHANGED = "OFFER_CHANGED"
    OFFER_EXPIRED = "OFFER_EXPIRED"
    POSITIONING_CHANGED = "POSITIONING_CHANGED"
    RELEVANCE_CHANGED = "RELEVANCE_CHANGED"

    ALL = (NEW_COMPETITOR, REMOVED_COMPETITOR, COMPETITOR_CHANGED, NEW_PRODUCT,
           PRODUCT_CHANGED, FEATURE_CHANGED, PRICE_CHANGED, NEW_OFFER,
           OFFER_CHANGED, OFFER_EXPIRED, POSITIONING_CHANGED, RELEVANCE_CHANGED)

    # How loudly each type asks for attention when nothing else distinguishes
    # two changes. Lower sorts first.
    WEIGHT = {
        NEW_COMPETITOR: 1, PRICE_CHANGED: 2, NEW_OFFER: 3, NEW_PRODUCT: 4,
        POSITIONING_CHANGED: 5, OFFER_CHANGED: 6, COMPETITOR_CHANGED: 7,
        PRODUCT_CHANGED: 8, FEATURE_CHANGED: 9, OFFER_EXPIRED: 10,
        RELEVANCE_CHANGED: 11, REMOVED_COMPETITOR: 12,
    }


class ThreatLevel:
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MODERATE = "MODERATE"
    LOW = "LOW"
    NONE = "NONE"
    ORDER = {CRITICAL: 0, HIGH: 1, MODERATE: 2, LOW: 3, NONE: 4}


class DecisionSource:
    MODEL = "vertex_gemini"
    RULES = "deterministic_rules"


# --------------------------------------------------------------------------
# evidence
# --------------------------------------------------------------------------

# How much weight a source carries. The tiers mirror `competitors.py`, because
# an intelligence claim inherits the credibility of where it was read.
SOURCE_TIER_WEIGHT = {
    "brand_official": 3,
    "authorized_retailer": 2,
    "trade_press": 2,
    "research_firm": 2,
    "marketplace_third_party": 1,
    "unknown": 0,
}


@dataclass
class Evidence:
    """One thing that was actually read, and where.

    There is deliberately no constructor path that produces evidence without a
    source. `observed_at` is when the Agent read it, not when the source says it
    was published — those are different facts and conflating them is how an old
    page becomes "fresh evidence".
    """
    url: str
    publisher: str
    observed_at: str
    kind: str = "unknown"          # a SOURCE_TIER_WEIGHT key
    excerpt: str = ""
    http_status: int | None = None

    def weight(self) -> int:
        return SOURCE_TIER_WEIGHT.get(self.kind, 0)

    def to_dict(self) -> dict:
        return asdict(self)


def confidence_from_evidence(evidence: list[Evidence]) -> str:
    """Derive a confidence from what was actually read.

    Two independent sources, or one first-party source, is enough for HIGH. One
    weaker source is MEDIUM. Anything thinner stays LOW, and nothing at all is
    UNVERIFIED. This is the only place a confidence is minted, so the levels mean
    the same thing on every page.
    """
    if not evidence:
        return Confidence.UNVERIFIED
    hosts = {e.url.split("/")[2] if "://" in e.url else e.url for e in evidence}
    best = max(e.weight() for e in evidence)
    if best >= 3 or (len(hosts) >= 2 and best >= 2):
        return Confidence.HIGH
    if best >= 2 or len(hosts) >= 2:
        return Confidence.MEDIUM
    return Confidence.LOW


# --------------------------------------------------------------------------
# records
# --------------------------------------------------------------------------

@dataclass
class DiscoveryCandidate:
    """The Discovery Agent's output shape, field for field as specified."""
    competitor_name: str
    domain: str = ""
    type: str = ""                 # direct | indirect | emerging | new_entrant |
                                   # competitor_product | substitute
    relevant_products: list[str] = field(default_factory=list)
    target_customer: str = ""
    why_competitive: str = ""
    evidence: list[Evidence] = field(default_factory=list)
    first_detected_at: str = ""
    confidence: str = Confidence.UNVERIFIED
    status: str = DiscoveryStatus.POSSIBLE
    identity_key: str = ""
    duplicate_of: str = ""
    notes: str = ""

    def to_dict(self) -> dict:
        d = asdict(self)
        d["evidence"] = [e.to_dict() for e in self.evidence]
        return d


@dataclass
class CompetitorProfile:
    """The Data Collection Agent's output shape.

    Every scalar defaults to "unknown" rather than "" so the difference between
    *not established* and *established as empty* survives into the report. The
    prompt says do not invent missing values; an empty string quietly reads as a
    value, "unknown" does not.
    """
    competitor: str
    company: dict = field(default_factory=dict)
    products: list[dict] = field(default_factory=list)
    pricing: list[dict] = field(default_factory=list)
    features: list[dict] = field(default_factory=list)
    target_customers: list[dict] = field(default_factory=list)
    positioning: dict = field(default_factory=dict)
    strengths: list[str] = field(default_factory=list)
    weaknesses: list[str] = field(default_factory=list)
    recent_changes: list[dict] = field(default_factory=list)
    evidence: list[Evidence] = field(default_factory=list)
    confidence: str = Confidence.UNVERIFIED

    def to_dict(self) -> dict:
        d = asdict(self)
        d["evidence"] = [e.to_dict() for e in self.evidence]
        return d


@dataclass
class Offer:
    """The Live Offers Agent's output shape.

    `status` has no default of ACTIVE, and `valid_until` stays empty unless the
    page printed one. Both of those are the prompt's explicit rules — never
    assume an offer is still live, never guess an expiry.
    """
    competitor: str
    product: str = ""
    offer_title: str = ""
    offer_description: str = ""
    original_price: str = ""
    current_price: str = ""
    discount: str = ""
    currency: str = ""
    valid_from: str = ""
    valid_until: str = ""
    detected_at: str = ""
    last_seen_at: str = ""
    source: str = ""
    evidence: list[Evidence] = field(default_factory=list)
    confidence: str = Confidence.UNVERIFIED
    status: str = OfferStatus.UNKNOWN
    offer_key: str = ""
    competitor_key: str = ""
    previous: dict | None = None
    change_note: str = ""

    def is_live(self) -> bool:
        return self.status in OfferStatus.LIVE

    def to_dict(self) -> dict:
        d = asdict(self)
        d["evidence"] = [e.to_dict() for e in self.evidence]
        return d


@dataclass
class Claim:
    """One assertion submitted for verification, and the verdict on it."""
    claim: str
    entity: str
    subject: str = ""              # identity | product | pricing | offer |
                                   # feature | relevance | market_claim
    verification_status: str = VerificationStatus.UNVERIFIED
    confidence: str = Confidence.UNVERIFIED
    evidence: list[Evidence] = field(default_factory=list)
    conflicts: list[str] = field(default_factory=list)
    reason: str = ""
    recommended_action: str = ""
    checked_at: str = ""

    def to_dict(self) -> dict:
        d = asdict(self)
        d["evidence"] = [e.to_dict() for e in self.evidence]
        return d


@dataclass
class Change:
    """A typed difference between the previous state and the new one."""
    change_type: str
    entity: str
    field_name: str = ""
    previous_value: str = ""
    new_value: str = ""
    detail: str = ""
    confidence: str = Confidence.UNVERIFIED
    evidence: list[Evidence] = field(default_factory=list)
    detected_at: str = ""

    def to_dict(self) -> dict:
        d = asdict(self)
        d["evidence"] = [e.to_dict() for e in self.evidence]
        return d


@dataclass
class Finding:
    """The Intelligence Agent's assessment of a verified change."""
    title: str
    entity: str
    change_type: str = ""
    competitive_impact: str = ""
    threat_level: str = ThreatLevel.NONE
    opportunity: str = ""
    strategic_significance: str = ""
    versus_previous: str = ""
    confidence: str = Confidence.UNVERIFIED
    evidence: list[Evidence] = field(default_factory=list)
    change_keys: list[str] = field(default_factory=list)
    # True when the finding restates a condition that is still true rather than
    # reporting something that just happened. Both belong on a task list; only
    # one belongs in "what changed".
    standing: bool = False

    def to_dict(self) -> dict:
        d = asdict(self)
        d["evidence"] = [e.to_dict() for e in self.evidence]
        return d


@dataclass
class Action:
    """A specific thing for a person to do, tied to the signal that caused it."""
    action: str
    owner: str = ""                # product | pricing | marketing | sales | ops
    urgency: str = ""              # now | this_week | this_month | watch
    because: str = ""
    entity: str = ""
    expected_outcome: str = ""
    links: list[dict] = field(default_factory=list)
    confidence: str = Confidence.UNVERIFIED
    finding_titles: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def evidence_list(raw: list) -> list[Evidence]:
    """Rebuild Evidence objects from stored dicts, tolerating partial rows."""
    out = []
    for e in raw or []:
        if isinstance(e, Evidence):
            out.append(e)
        elif isinstance(e, dict):
            out.append(Evidence(
                url=e.get("url", ""), publisher=e.get("publisher", ""),
                observed_at=e.get("observed_at", ""), kind=e.get("kind", "unknown"),
                excerpt=e.get("excerpt", ""), http_status=e.get("http_status")))
    return out
