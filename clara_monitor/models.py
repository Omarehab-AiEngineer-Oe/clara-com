"""Normalized records. These field names are the vocabulary the agent,
the store, the reports and the generated site all share.

`NOT_PUBLISHED` is a real value, distinct from None. It means "we read the
page and the manufacturer does not state this" — never "we did not look".
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any

NOT_PUBLISHED = "not_published"

# Match statuses — exactly one per pair.
CONFIRMED = "confirmed_match"
PROBABLE = "probable_match"
AMBIGUOUS = "ambiguous"
NO_MATCH = "no_match"
BLOCKED = "blocked"

MATCH_STATUSES = (CONFIRMED, PROBABLE, AMBIGUOUS, NO_MATCH, BLOCKED)

# Comparison bases
STANDALONE = "standalone_product"
ATTACHMENT_OF_SYSTEM = "attachment_of_system"
BUNDLE = "bundle"


def _clean(d: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in d.items() if v is not None}


@dataclass
class ClaraProduct:
    product_id: str
    name: str
    url: str
    price: float | None
    currency: str
    rating: float | None
    rating_count: int | None
    image_url: str | None
    # Derived, used for matching and for competitor assignment.
    fmt: str = "unknown"            # multi_styler | dryer | air_brush | ...
    segment: str = "unknown"        # device | haircare | accessory
    category: str = "hair_styling_device"
    specs: dict[str, Any] = field(default_factory=dict)
    description_lang: str = "unknown"
    in_scope: bool = True

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass
class Candidate:
    """A competitor page considered during discovery."""
    url: str
    brand: str
    product_name: str
    host: str
    source_type: str
    fmt: str = "unknown"
    specs: dict[str, Any] = field(default_factory=dict)
    score: float = 0.0
    score_breakdown: dict[str, float] = field(default_factory=dict)
    disqualified: bool = False
    disqualified_reason: str | None = None
    evidence: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return _clean(asdict(self))


@dataclass
class Match:
    """The durable decision for one (Clara product, competitor) pair."""
    clara_product_id: str
    competitor_key: str
    competitor_brand: str
    status: str
    match_score: float
    comparison_basis: str = STANDALONE
    competitor_url: str | None = None
    competitor_product_name: str | None = None
    fingerprint: str | None = None
    evidence: list[str] = field(default_factory=list)
    rejected: list[dict] = field(default_factory=list)
    validated_at: str | None = None
    ttl_days: int = 30
    invalidated_at: str | None = None
    invalid_reason: str | None = None
    discovery_used: bool = False
    system_price: float | None = None       # for attachment_of_system
    separately_available: bool | None = None

    def as_dict(self) -> dict:
        return _clean(asdict(self))


@dataclass
class Observation:
    """One normalized snapshot of a matched competitor product."""
    clara_product_id: str
    competitor_key: str
    observed_at: str
    product_url: str
    competitor_brand: str
    competitor_product_name: str
    source_type: str
    variant: str = NOT_PUBLISHED
    current_price: float | str = NOT_PUBLISHED
    regular_price: float | str = NOT_PUBLISHED
    price_min: float | None = None          # set instead of current_price
    price_max: float | None = None          # when the site shows a range
    discount_amount: float | str = NOT_PUBLISHED
    discount_percent: float | str = NOT_PUBLISHED
    currency: str = "SAR"
    tax_basis: str = NOT_PUBLISHED          # e.g. "incl_vat" / "excl_vat"
    stock_status: str = NOT_PUBLISHED
    promotion_text: str = NOT_PUBLISHED
    promotion_mechanism: str = NOT_PUBLISHED
    primary_image_url: str | None = None
    is_stale: bool = False
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return _clean(asdict(self))


@dataclass
class Change:
    clara_product_id: str
    competitor_key: str
    change_type: str
    previous_value: Any
    new_value: Any
    delta_pct: float | None = None
    flagged: bool = False
    detected_at: str = ""

    def as_dict(self) -> dict:
        return _clean(asdict(self))


@dataclass
class Exception_:
    """An escalation. Every field here is what the human needs to act."""
    run_id: str
    clara_product_id: str
    competitor_key: str
    kind: str                   # blocked | ambiguous | repeated_failure | ...
    attempted: str
    observed: str
    why_unresolved: str
    recommended_action: str
    blocks_downstream: str = ""
    evidence: list[str] = field(default_factory=list)
    created_at: str = ""

    def as_dict(self) -> dict:
        return _clean(asdict(self))
