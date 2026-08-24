"""Decimal money handling.

Requirements §11: "Preserve raw price text and normalized decimal values; never
use floating-point arithmetic." Every price in this project is a Decimal or the
raw string it came from — no float ever touches a price.

§13 also governs what happens when a price cannot be resolved: keep the raw
text, mark the price unresolved, lower confidence. Returning 0.0 or None-as-zero
is never correct.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

TWO = Decimal("0.01")

# ISO code, symbol and common written forms per currency we accept.
CURRENCY_TOKENS = {
    "SAR": ("sar", "s.r", "sr", "ر.س", "ريال", "riyal", "﷼"),
    "AED": ("aed", "د.إ", "dirham"),
    "USD": ("usd", "$", "us$"),
    "GBP": ("gbp", "£"),
    "EUR": ("eur", "€"),
    "KWD": ("kwd", "د.ك"),
    "QAR": ("qar", "ر.ق"),
    "BHD": ("bhd"),
    "EGP": ("egp"),
}

# Two forms, each fenced by lookarounds so neither can match a slice of a longer
# number. The grouped-thousands form requires at least one separator group: with
# `*` it happily matched "229" inside "2299", which then read as a 9-to-229 range.
# The whole thing is wrapped in a non-capturing group because it is interpolated
# into larger patterns, where a bare top-level `|` would rebind the alternation.
_NUM = (r"(?:"
        r"(?<![\d.,٫٬])\d{1,3}(?:[,٬\s]\d{3})+(?:[.٫]\d{1,2})?(?![\d])"
        r"|(?<![\d.,٫٬])\d+(?:[.٫]\d{1,2})?(?![\d])"
        r")")
_ARABIC_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")

RANGE_SEPARATORS = r"(?:-|–|—|to|إلى|الى)"


@dataclass
class Price:
    """A parsed price. `raw` is always kept; `amount` may be None."""
    raw: str
    amount: Decimal | None = None
    currency: str | None = None
    is_range: bool = False
    minimum: Decimal | None = None
    maximum: Decimal | None = None
    from_price: bool = False          # "from SAR 199"
    unresolved: bool = False
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "raw": self.raw,
            "amount": str(self.amount) if self.amount is not None else None,
            "currency": self.currency,
            "is_range": self.is_range,
            "minimum": str(self.minimum) if self.minimum is not None else None,
            "maximum": str(self.maximum) if self.maximum is not None else None,
            "from_price": self.from_price,
            "unresolved": self.unresolved,
            "notes": self.notes,
        }


def to_decimal(value) -> Decimal | None:
    """Parse to Decimal without ever going through float."""
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, float):
        # A float reached us from a JSON payload. repr() round-trips the shortest
        # exact decimal representation, which is the closest we can honestly get.
        return Decimal(repr(value))
    s = str(value).strip().translate(_ARABIC_DIGITS)
    s = s.replace("٫", ".").replace("٬", "").replace(",", "").replace(" ", "")
    s = re.sub(r"[^\d.\-]", "", s)
    if not s or s in ("-", ".", "-."):
        return None
    try:
        return Decimal(s)
    except InvalidOperation:
        return None


def detect_currency(text: str) -> str | None:
    low = (text or "").lower()
    for code, tokens in CURRENCY_TOKENS.items():
        if code.lower() in low:
            return code
        for t in tokens:
            if t and t in low:
                return code
    return None


def parse_price(text, currency_hint: str | None = None) -> Price:
    """Parse a displayed price, preserving the raw text.

    Handles ranges ("SAR 199 - 249") and "from" prices explicitly rather than
    collapsing them to one number, per §11.
    """
    raw = "" if text is None else str(text).strip()
    p = Price(raw=raw)
    if not raw:
        p.unresolved = True
        p.notes.append("empty price text")
        return p

    p.currency = detect_currency(raw) or currency_hint
    norm = raw.translate(_ARABIC_DIGITS)

    if re.search(r"\b(from|starting at|starts at|ابتداء|يبدأ)\b", norm, re.I):
        p.from_price = True

    nums = re.findall(_NUM, norm)
    values = [v for v in (to_decimal(n) for n in nums) if v is not None and v > 0]

    if not values:
        p.unresolved = True
        p.notes.append("no numeric value found in price text; raw text preserved")
        return p

    if len(values) >= 2 and re.search(
            rf"{_NUM}\s*{RANGE_SEPARATORS}\s*{_NUM}", norm, re.I):
        p.is_range = True
        p.minimum, p.maximum = min(values[:2]), max(values[:2])
        p.notes.append("price shown as a range; min and max kept, no midpoint computed")
        return p

    if p.from_price:
        p.minimum = min(values)
        p.amount = min(values)
        p.notes.append("'from' price: applies to the cheapest variant only")
        return p

    p.amount = values[0]
    return p


def discount(regular: Decimal | None, selling: Decimal | None) -> tuple[Decimal | None, Decimal | None, list[str]]:
    """(amount, percent, warnings) computed only from two real prices.

    §13: "Sale price > regular price -> warn; do not calculate a positive
    discount." A discount is never invented from a single price.
    """
    notes: list[str] = []
    if regular is None or selling is None:
        return None, None, notes
    if regular <= 0:
        notes.append("regular price is not positive; no discount computed")
        return None, None, notes
    if selling > regular:
        notes.append(
            f"selling price {selling} exceeds regular price {regular}; "
            "source disagreement flagged, no positive discount computed")
        return None, None, notes
    if selling == regular:
        return None, None, notes
    amount = (regular - selling).quantize(TWO, rounding=ROUND_HALF_UP)
    percent = ((regular - selling) / regular * Decimal(100)).quantize(
        TWO, rounding=ROUND_HALF_UP)
    return amount, percent, notes


def pct_change(old: Decimal | None, new: Decimal | None) -> Decimal | None:
    if old is None or new is None or old == 0:
        return None
    return ((new - old) / old * Decimal(100)).quantize(TWO, rounding=ROUND_HALF_UP)


def fmt(amount: Decimal | None, currency: str | None = None) -> str:
    if amount is None:
        return "unresolved"
    q = amount.quantize(TWO, rounding=ROUND_HALF_UP)
    s = f"{q:,.2f}"
    if s.endswith(".00"):
        s = s[:-3]
    return f"{currency} {s}" if currency else s
