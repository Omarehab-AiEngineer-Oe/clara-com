"""Turn a competitor product page into a normalized Observation.

Rules from section 10 of the instruction that are enforced here:
  * a field the page does not state becomes NOT_PUBLISHED, never 0 and never a guess
  * a price range is recorded as min and max, never a midpoint
  * a discount is only recorded if the page shows both prices, or states it
  * stock is never inferred from the absence of an out-of-stock message
"""

from __future__ import annotations

import json
import re
import urllib.parse

from .models import NOT_PUBLISHED, Observation
from .store import utcnow

_JSONLD = re.compile(r'<script type="application/ld\+json">(.*?)</script>', re.S)

_IN_STOCK = ("instock", "in_stock", "in stock", "available")
_OUT_STOCK = ("outofstock", "out_of_stock", "out of stock", "sold out", "unavailable")

_PROMO_PATTERNS = [
    ("bundle", r"\b(bundle|set of|kit|combo)\b"),
    ("gift_with_purchase", r"\b(free gift|complimentary|gift with purchase|worth SAR)\b"),
    ("coupon", r"\b(coupon|promo code|use code)\b"),
    ("installments", r"\b(tamara|tabby|madfu|installments?)\b"),
    ("percent_off", r"\b(\d{1,2})\s*%\s*(off|discount)\b"),
    ("free_shipping", r"\bfree (shipping|delivery)\b"),
]


def _strip(html: str) -> str:
    html = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html, flags=re.S | re.I)
    html = re.sub(r"<[^>]+>", " ", html)
    for a, b in (("&nbsp;", " "), ("&amp;", "&"), ("&quot;", '"'),
                 ("&#039;", "'"), ("&lt;", "<"), ("&gt;", ">")):
        html = html.replace(a, b)
    return re.sub(r"\s+", " ", html).strip()


def _jsonld_products(html: str) -> list[dict]:
    found = []
    for blob in _JSONLD.findall(html):
        try:
            j = json.loads(blob)
        except json.JSONDecodeError:
            continue
        stack = [j]
        while stack:
            n = stack.pop()
            if isinstance(n, dict):
                t = n.get("@type")
                types = t if isinstance(t, list) else [t]
                if "Product" in types:
                    found.append(n)
                stack.extend(v for v in n.values() if isinstance(v, (dict, list)))
            elif isinstance(n, list):
                stack.extend(n)
    return found


def _first_offer(prod: dict) -> dict:
    off = prod.get("offers")
    if isinstance(off, list):
        return off[0] if off else {}
    return off or {}


def _num(v) -> float | None:
    if v is None:
        return None
    try:
        return float(str(v).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def _detect_promotion(text: str) -> tuple[str, str]:
    low = text.lower()
    hits = []
    mech = []
    for name, pat in _PROMO_PATTERNS:
        m = re.search(pat, low, re.I)
        if m:
            mech.append(name)
            hits.append(m.group(0).strip())
    if not hits:
        return NOT_PUBLISHED, NOT_PUBLISHED
    return "; ".join(dict.fromkeys(hits))[:300], ",".join(dict.fromkeys(mech))


def _detect_stock(prod: dict, text: str) -> str:
    avail = str(_first_offer(prod).get("availability") or "").lower()
    if any(k in avail for k in _OUT_STOCK):
        return "out_of_stock"
    if any(k in avail for k in _IN_STOCK):
        return "in_stock"
    low = text.lower()
    for k in _OUT_STOCK:
        if k in low:
            return "out_of_stock"
    # An "Add to cart" button alone is not a stated stock status.
    if re.search(r"\bin stock\b", low):
        return "in_stock"
    return NOT_PUBLISHED


def _detect_variant(prod: dict, text: str) -> str:
    for key in ("color", "size", "model"):
        v = prod.get(key)
        if isinstance(v, str) and v.strip():
            return v.strip()[:120]
    name = prod.get("name") or ""
    m = re.search(r"\(([^)]{3,60})\)\s*$", name)
    if m:
        return m.group(1)
    m = re.search(r"\b(complete long|complete|lite|special|premium|mini|se lite|se)\b",
                  name, re.I)
    if m:
        return m.group(1)
    return NOT_PUBLISHED


def observe_from_html(
    clara_product_id: str,
    competitor_key: str,
    competitor_brand: str,
    url: str,
    html: str,
    source_type: str,
    currency: str = "SAR",
) -> Observation:
    text = _strip(html)
    prods = _jsonld_products(html)
    prod = prods[0] if prods else {}
    offer = _first_offer(prod)
    notes: list[str] = []

    name = (prod.get("name") or "").strip()
    if not name:
        m = re.search(r"<title>(.*?)</title>", html, re.S | re.I)
        name = _strip(m.group(1))[:160] if m else NOT_PUBLISHED
        notes.append("product name taken from <title>; no Product JSON-LD name present")

    # --- price -------------------------------------------------------------
    current = _num(offer.get("price"))
    low_p, high_p = _num(offer.get("lowPrice")), _num(offer.get("highPrice"))
    price_min = price_max = None
    if current is None and (low_p is not None or high_p is not None):
        price_min, price_max = low_p, high_p
        notes.append("site shows a price range; min and max recorded, no midpoint computed")

    regular = None
    for key in ("regular_price", "listPrice", "highPrice"):
        regular = regular or _num(prod.get(key)) or _num(offer.get(key))
    if regular is None:
        m = re.search(r'"(?:regular_price|was_price|compare_at_price)"\s*:\s*"?([\d.,]+)', html)
        if m:
            regular = _num(m.group(1))

    disc_amt = disc_pct = NOT_PUBLISHED
    if current is not None and regular is not None and regular > current > 0:
        disc_amt = round(regular - current, 2)
        disc_pct = round((regular - current) / regular * 100, 1)
    elif current is not None and regular is not None and regular <= current:
        notes.append("a was-price was present but is not above the current price; "
                     "no discount recorded")

    tax_basis = NOT_PUBLISHED
    low_text = text.lower()
    if "incl" in low_text and "vat" in low_text:
        tax_basis = "incl_vat"
    elif "excl" in low_text and "vat" in low_text:
        tax_basis = "excl_vat"

    cur = offer.get("priceCurrency") or currency
    if cur != currency:
        notes.append(f"page currency is {cur}, run currency is {currency}; not converted")

    # --- image -------------------------------------------------------------
    img = prod.get("image")
    if isinstance(img, list):
        img = img[0] if img else None
    if isinstance(img, dict):
        img = img.get("url")
    if not img:
        m = re.search(r'<meta[^>]+property="og:image"[^>]+content="([^"]+)"', html, re.I)
        img = m.group(1) if m else None
    if img and img.startswith("//"):
        img = "https:" + img

    promo_text, promo_mech = _detect_promotion(text)

    return Observation(
        clara_product_id=clara_product_id,
        competitor_key=competitor_key,
        observed_at=utcnow(),
        product_url=url,
        competitor_brand=competitor_brand,
        competitor_product_name=name or NOT_PUBLISHED,
        source_type=source_type,
        variant=_detect_variant(prod, text),
        current_price=current if current is not None else NOT_PUBLISHED,
        regular_price=regular if regular is not None else NOT_PUBLISHED,
        price_min=price_min,
        price_max=price_max,
        discount_amount=disc_amt,
        discount_percent=disc_pct,
        currency=cur,
        tax_basis=tax_basis,
        stock_status=_detect_stock(prod, text),
        promotion_text=promo_text,
        promotion_mechanism=promo_mech,
        primary_image_url=img,
        notes=notes,
    )


def page_signals(html: str) -> dict:
    """Identity + spec signals used for fingerprinting and candidate scoring."""
    text = _strip(html)
    prods = _jsonld_products(html)
    prod = prods[0] if prods else {}
    name = (prod.get("name") or "").strip()
    if not name:
        m = re.search(r"<title>(.*?)</title>", html, re.S | re.I)
        name = _strip(m.group(1)) if m else ""

    brand = prod.get("brand")
    if isinstance(brand, dict):
        brand = brand.get("name")
    if not brand:
        m = re.search(r'<meta[^>]+property="og:site_name"[^>]+content="([^"]+)"', html, re.I)
        brand = m.group(1) if m else ""

    from .catalog import classify_format, extract_specs
    blob = f"{name} {text[:6000]}"
    # Format comes from the product NAME, with only a short lead of body text as
    # fallback. A wide window pulls in cross-links and copy about other formats:
    # a FlexStyle page that mentions "straightener" further down was being
    # classified as a straightener and then disqualified as a format mismatch.
    fmt = classify_format(name, text[:700])
    return {
        "name": name,
        "brand": (brand or "").strip(),
        "fmt": fmt,
        "specs": extract_specs(blob),
        "is_listing_page": bool(
            re.search(r'"@type"\s*:\s*"(CollectionPage|SearchResultsPage)"', html)
        ) or not prods and bool(re.search(r"\b(\d+)\s+products?\b", text, re.I)),
        "text_head": text[:400],
    }


def host_of(url: str) -> str:
    return urllib.parse.urlsplit(url).netloc.lower()
