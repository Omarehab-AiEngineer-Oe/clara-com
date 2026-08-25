"""Method selection (§9), field extraction (§10-12) and validation (§13).

The method ladder is followed in the order the requirements set, and the method
actually used plus the reason it was chosen are recorded on every observation:

  1  JSON-LD / embedded structured data   when complete enough for required fields
  2  direct HTTP + HTML parser            server-rendered pages
  3  permitted public page API / XHR      when the page relies on a stable endpoint
  4  browser automation                   only for JS rendering / dynamic variants
  stop  human escalation                  login, CAPTCHA, blocks, repeated low confidence

Browser automation is declared unavailable here rather than silently skipped, so
a pair that genuinely needs it escalates instead of returning thin data.
Validation is deterministic: accepted / accepted_with_warnings / rejected.
"""

from __future__ import annotations

import json
import re
import urllib.parse
from dataclasses import dataclass, field
from decimal import Decimal

from .money import Price, discount, parse_price, to_decimal

METHOD_STRUCTURED = "json_ld_structured_data"
METHOD_HTTP_PARSER = "http_html_parser"
METHOD_PAGE_API = "public_page_api"
METHOD_BROWSER = "browser_automation"

ACCEPTED = "accepted"
ACCEPTED_WITH_WARNINGS = "accepted_with_warnings"
REJECTED = "rejected"

UNKNOWN = "unknown"
IN_STOCK = "in_stock"
OUT_OF_STOCK = "out_of_stock"
PREORDER = "preorder"

_JSONLD = re.compile(r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
                     re.S | re.I)

_PLACEHOLDER_IMG = re.compile(
    r"(placeholder|no[-_]?image|default[-_]product|blank|spacer|pixel|"
    r"1x1|loading|lazy[-_]?load|swatch-fallback)", re.I)
_TRACKING_IMG = re.compile(r"(doubleclick|googletagmanager|facebook\.com/tr|"
                           r"analytics|\.gif\?|/pixel)", re.I)
_IMG_EXT = re.compile(r"\.(jpe?g|png|webp|avif)(\?|$)", re.I)

_STOCK_IN = ("instock", "in_stock", "in stock", "available", "متوفر", "add to cart",
             "add to bag", "buy now")
_STOCK_OUT = ("outofstock", "out_of_stock", "out of stock", "sold out",
              "unavailable", "غير متوفر", "نفذت", "notify me when")
_STOCK_PRE = ("preorder", "pre-order", "backorder", "coming soon")

_PROMO_RULES = [
    ("bundle", r"\b(bundle|set of|kit|combo|pack of)\b"),
    ("gift_with_purchase", r"\b(free gift|complimentary|gift with purchase|worth (?:sar|aed|usd))\b"),
    ("coupon", r"\b(coupon|promo code|use code|discount code)\b"),
    ("installments", r"\b(tamara|tabby|madfu|installments?|interest[- ]free)\b"),
    ("percent_off", r"\b\d{1,2}\s*%\s*(?:off|discount)\b"),
    ("free_shipping", r"\bfree (?:shipping|delivery)\b"),
    ("clearance", r"\b(clearance|final sale|last chance)\b"),
]


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------

def strip_html(html: str) -> str:
    html = re.sub(r"<(script|style|noscript)\b[^>]*>.*?</(?:script|style|noscript)>",
                  " ", html, flags=re.S | re.I)
    html = re.sub(r"<[^>]+>", " ", html)
    for a, b in (("&nbsp;", " "), ("&amp;", "&"), ("&quot;", '"'), ("&#39;", "'"),
                 ("&#039;", "'"), ("&lt;", "<"), ("&gt;", ">"), ("&apos;", "'")):
        html = html.replace(a, b)
    return re.sub(r"\s+", " ", html).strip()


def jsonld_nodes(html: str) -> list[dict]:
    out: list[dict] = []
    for blob in _JSONLD.findall(html):
        blob = blob.strip()
        try:
            j = json.loads(blob)
        except json.JSONDecodeError:
            # Some shops emit several JSON objects in one tag.
            for m in re.finditer(r"\{.*?\}(?=\s*[,\]]|\s*$)", blob, re.S):
                try:
                    out.append(json.loads(m.group(0)))
                except json.JSONDecodeError:
                    continue
            continue
        stack = [j]
        while stack:
            n = stack.pop()
            if isinstance(n, dict):
                out.append(n)
                stack.extend(v for v in n.values() if isinstance(v, (dict, list)))
            elif isinstance(n, list):
                stack.extend(n)
    return out


def _types(node: dict) -> list[str]:
    t = node.get("@type")
    if isinstance(t, list):
        return [str(x) for x in t]
    return [str(t)] if t else []


def find_product_node(html: str) -> dict | None:
    best = None
    for n in jsonld_nodes(html):
        if "Product" in _types(n) or "ProductGroup" in _types(n):
            if best is None or len(json.dumps(n)) > len(json.dumps(best)):
                best = n
    return best


def _offers(node: dict) -> list[dict]:
    off = node.get("offers")
    if isinstance(off, list):
        return [o for o in off if isinstance(o, dict)]
    if isinstance(off, dict):
        if "Offer" in _types(off) or "offers" not in off:
            return [off]
        inner = off.get("offers")
        if isinstance(inner, list):
            return [o for o in inner if isinstance(o, dict)]
        return [off]
    return []


def meta_content(html: str, prop: str) -> str | None:
    m = re.search(
        rf'<meta[^>]+(?:property|name)=["\']{re.escape(prop)}["\'][^>]+content=["\']([^"\']+)["\']',
        html, re.I)
    if m:
        return m.group(1)
    m = re.search(
        rf'<meta[^>]+content=["\']([^"\']+)["\'][^>]+(?:property|name)=["\']{re.escape(prop)}["\']',
        html, re.I)
    return m.group(1) if m else None


# --------------------------------------------------------------------------
# images (§12)
# --------------------------------------------------------------------------

def _abs_url(u: str, base: str) -> str:
    if u.startswith("//"):
        return "https:" + u
    if u.startswith(("http://", "https://")):
        return u
    return urllib.parse.urljoin(base, u)


def _best_from_srcset(srcset: str) -> str | None:
    """Prefer the highest declared width in a srcset (§12)."""
    best, best_w = None, -1
    for part in srcset.split(","):
        part = part.strip()
        if not part:
            continue
        bits = part.split()
        url = bits[0]
        w = -1
        if len(bits) > 1:
            m = re.match(r"(\d+)[wx]", bits[1])
            if m:
                w = int(m.group(1))
        if w > best_w:
            best, best_w = url, w
    return best


def extract_images(html: str, base_url: str, node: dict | None) -> list[dict]:
    """Ordered main/gallery images, placeholders and pixels rejected (§12)."""
    ordered: list[str] = []

    def push(u: str | None):
        if not u:
            return
        u = _abs_url(u.strip(), base_url)
        if not _IMG_EXT.search(u) and "cdn" not in u.lower():
            return
        if _PLACEHOLDER_IMG.search(u) or _TRACKING_IMG.search(u):
            return
        if u not in ordered:
            ordered.append(u)

    if node:
        img = node.get("image")
        if isinstance(img, str):
            push(img)
        elif isinstance(img, list):
            for i in img:
                push(i if isinstance(i, str) else (i or {}).get("url"))
        elif isinstance(img, dict):
            push(img.get("url"))

    push(meta_content(html, "og:image"))

    # Gallery: lazy-load attributes first, then srcset, then src.
    for m in re.finditer(r"<img\b[^>]*>", html, re.I):
        tag = m.group(0)
        for attr in ("data-zoom-image", "data-large_image", "data-src",
                     "data-original", "data-lazy"):
            am = re.search(rf'{attr}=["\']([^"\']+)["\']', tag, re.I)
            if am:
                push(am.group(1))
                break
        sm = re.search(r'(?:data-srcset|srcset)=["\']([^"\']+)["\']', tag, re.I)
        if sm:
            push(_best_from_srcset(sm.group(1)))
        im = re.search(r'\bsrc=["\']([^"\']+)["\']', tag, re.I)
        if im:
            push(im.group(1))
        if len(ordered) >= 12:
            break

    return [{"position": i, "url": u, "role": "main" if i == 0 else "gallery"}
            for i, u in enumerate(ordered[:12])]


# --------------------------------------------------------------------------
# variants (§11)
# --------------------------------------------------------------------------

def extract_variants(html: str, node: dict | None, currency_hint: str | None) -> list[dict]:
    """Real purchasable option combinations only — never a Cartesian product."""
    out: list[dict] = []
    seen: set[str] = set()

    if node:
        for off in _offers(node):
            name = off.get("name") or off.get("sku") or off.get("itemOffered", {}) \
                if isinstance(off.get("itemOffered"), dict) else off.get("name")
            if isinstance(name, dict):
                name = name.get("name")
            price = parse_price(off.get("price"), currency_hint)
            key = f"{name}|{price.amount}"
            if key in seen:
                continue
            seen.add(key)
            out.append({
                "option_key": str(name) if name else UNKNOWN,
                "sku": off.get("sku"),
                "price": str(price.amount) if price.amount is not None else None,
                "currency": off.get("priceCurrency") or price.currency or currency_hint,
                "availability": map_stock_text(str(off.get("availability") or "")),
                "source": "json_ld_offer",
            })

    if node and isinstance(node.get("hasVariant"), list):
        for v in node["hasVariant"]:
            if not isinstance(v, dict):
                continue
            offs = _offers(v)
            price = parse_price(offs[0].get("price") if offs else None, currency_hint)
            key = f"{v.get('name')}|{price.amount}"
            if key in seen:
                continue
            seen.add(key)
            out.append({
                "option_key": v.get("name") or v.get("sku") or UNKNOWN,
                "sku": v.get("sku"),
                "price": str(price.amount) if price.amount is not None else None,
                "currency": (offs[0].get("priceCurrency") if offs else None)
                            or currency_hint,
                "availability": map_stock_text(
                    str(offs[0].get("availability") if offs else "")),
                "size": v.get("size"), "color": v.get("color"),
                "source": "json_ld_has_variant",
            })

    # Salla / Shopify style option payloads embedded in the page.
    for m in re.finditer(r'"options?"\s*:\s*(\[\{.{0,4000}?\}\])', html, re.S):
        try:
            opts = json.loads(m.group(1))
        except json.JSONDecodeError:
            continue
        for o in opts if isinstance(opts, list) else []:
            if not isinstance(o, dict):
                continue
            for d in (o.get("details") or o.get("values") or []):
                if not isinstance(d, dict):
                    continue
                nm = d.get("name") or d.get("value")
                if not nm or str(nm) in seen:
                    continue
                seen.add(str(nm))
                out.append({
                    "option_key": str(nm),
                    "sku": d.get("sku"),
                    "price": None,
                    "currency": currency_hint,
                    "availability": OUT_OF_STOCK if d.get("is_out") else UNKNOWN,
                    "source": "embedded_options",
                })
        break

    return out[:40]


# --------------------------------------------------------------------------
# stock (§10, §13)
# --------------------------------------------------------------------------

def map_stock_text(text: str) -> str:
    low = (text or "").lower()
    if not low.strip():
        return UNKNOWN
    for k in _STOCK_PRE:
        if k in low:
            return PREORDER
    for k in _STOCK_OUT:
        if k in low:
            return OUT_OF_STOCK
    for k in _STOCK_IN:
        if k in low:
            return IN_STOCK
    return UNKNOWN


def detect_stock(node: dict | None, page_text: str) -> tuple[str, str]:
    """(status, raw wording). Unknown wording maps to unknown and keeps the raw."""
    if node:
        for off in _offers(node):
            avail = str(off.get("availability") or "")
            if avail:
                return map_stock_text(avail), avail
    m = re.search(r"(out of stock|sold out|in stock|unavailable|pre-?order|"
                  r"غير متوفر|متوفر)", page_text, re.I)
    if m:
        return map_stock_text(m.group(1)), m.group(1)
    return UNKNOWN, ""


def detect_promotion(page_text: str) -> tuple[str, str]:
    hits, mech = [], []
    for name, pat in _PROMO_RULES:
        m = re.search(pat, page_text, re.I)
        if m:
            mech.append(name)
            hits.append(m.group(0).strip())
    if not hits:
        return "", ""
    return "; ".join(dict.fromkeys(hits))[:300], ",".join(dict.fromkeys(mech))


# --------------------------------------------------------------------------
# the extraction result
# --------------------------------------------------------------------------

@dataclass
class Extraction:
    url: str
    method: str
    method_rationale: str
    fallbacks_tried: list[str] = field(default_factory=list)
    product_name: str | None = None
    brand: str | None = None
    source_product_id: str | None = None
    sku: str | None = None
    category_path: list[str] = field(default_factory=list)
    canonical_url: str | None = None
    selling: Price | None = None
    regular: Price | None = None
    sale: Price | None = None
    discount_amount: Decimal | None = None
    discount_percent: Decimal | None = None
    currency: str | None = None
    availability: str = UNKNOWN
    stock_text_raw: str = ""
    promotion_text: str = ""
    promotion_mechanism: str = ""
    variants: list[dict] = field(default_factory=list)
    images: list[dict] = field(default_factory=list)
    confidence: float = 0.0
    verdict: str = REJECTED
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "url": self.url, "method": self.method,
            "method_rationale": self.method_rationale,
            "fallbacks_tried": self.fallbacks_tried,
            "product_name": self.product_name, "brand": self.brand,
            "source_product_id": self.source_product_id, "sku": self.sku,
            "category_path": self.category_path,
            "canonical_url": self.canonical_url,
            "selling_price": str(self.selling.amount) if self.selling and self.selling.amount is not None else None,
            "selling_price_raw": self.selling.raw if self.selling else None,
            "regular_price": str(self.regular.amount) if self.regular and self.regular.amount is not None else None,
            "sale_price": str(self.sale.amount) if self.sale and self.sale.amount is not None else None,
            "price_is_range": bool(self.selling and self.selling.is_range),
            "price_min": str(self.selling.minimum) if self.selling and self.selling.minimum is not None else None,
            "price_max": str(self.selling.maximum) if self.selling and self.selling.maximum is not None else None,
            "price_from": bool(self.selling and self.selling.from_price),
            "discount_amount": str(self.discount_amount) if self.discount_amount is not None else None,
            "discount_percent": str(self.discount_percent) if self.discount_percent is not None else None,
            "currency": self.currency,
            "availability": self.availability,
            "stock_text_raw": self.stock_text_raw,
            "promotion_text": self.promotion_text,
            "promotion_mechanism": self.promotion_mechanism,
            "variant_count": len(self.variants),
            "variants": self.variants,
            "image_count": len(self.images),
            "images": self.images,
            "confidence": round(self.confidence, 3),
            "verdict": self.verdict,
            "warnings": self.warnings,
            "errors": self.errors,
        }


def extract(url: str, html: str, currency_hint: str | None = None,
            allowed_host_check=None) -> Extraction:
    """Run the §9 ladder and return a validated Extraction."""
    text = strip_html(html)
    node = find_product_node(html)
    fallbacks: list[str] = []

    if node:
        method = METHOD_STRUCTURED
        rationale = ("Product JSON-LD present and contained the required identity "
                     "fields, so structured data was used (§9 priority 1).")
    else:
        fallbacks.append(METHOD_STRUCTURED)
        method = METHOD_HTTP_PARSER
        rationale = ("No Product JSON-LD on the page; fell back to parsing the "
                     "server-rendered HTML (§9 priority 2).")

    ex = Extraction(url=url, method=method, method_rationale=rationale,
                    fallbacks_tried=fallbacks)

    # ---- identity ----
    name = None
    if node:
        name = node.get("name")
        b = node.get("brand")
        ex.brand = (b.get("name") if isinstance(b, dict) else b) or None
        ex.sku = node.get("sku") or node.get("mpn")
        ex.source_product_id = node.get("productID") or node.get("sku") or node.get("mpn")
        cat = node.get("category")
        if isinstance(cat, str):
            ex.category_path = [c.strip() for c in re.split(r"[>/|]", cat) if c.strip()]
        elif isinstance(cat, list):
            ex.category_path = [str(c) for c in cat]
    if not name:
        name = meta_content(html, "og:title")
    if not name:
        m = re.search(r"<h1[^>]*>(.*?)</h1>", html, re.S | re.I)
        name = strip_html(m.group(1)) if m else None
    if not name:
        m = re.search(r"<title>(.*?)</title>", html, re.S | re.I)
        name = strip_html(m.group(1)) if m else None
    ex.product_name = (name or "").strip()[:250] or None
    if not ex.brand:
        ex.brand = meta_content(html, "og:site_name")

    m = re.search(r'<link[^>]+rel=["\']canonical["\'][^>]+href=["\']([^"\']+)["\']',
                  html, re.I)
    ex.canonical_url = _abs_url(m.group(1), url) if m else url

    # ---- prices (§11, all Decimal) ----
    sell_raw = reg_raw = sale_raw = None
    if node:
        offs = _offers(node)
        if offs:
            o = offs[0]
            sell_raw = o.get("price")
            if o.get("lowPrice") or o.get("highPrice"):
                sell_raw = f"{o.get('lowPrice')} - {o.get('highPrice')}"
            ex.currency = o.get("priceCurrency") or currency_hint
            spec = o.get("priceSpecification")
            if isinstance(spec, dict):
                reg_raw = spec.get("price") or reg_raw
            elif isinstance(spec, list):
                for s in spec:
                    if isinstance(s, dict) and "regular" in str(s.get("@type", "")).lower():
                        reg_raw = s.get("price")

    if sell_raw is None:
        m = re.search(r'"(?:selling_price|sale_price|price)"\s*:\s*"?([\d.,]+)', html)
        if m:
            sell_raw = m.group(1)
    if reg_raw is None:
        m = re.search(r'"(?:regular_price|compare_at_price|was_price|listPrice)"'
                      r'\s*:\s*"?([\d.,]+)', html)
        if m:
            reg_raw = m.group(1)

    if sell_raw is None:
        m = re.search(r"((?:SAR|AED|USD|GBP|EUR|ر\.س|﷼)\s*[\d.,]+)", text)
        if m:
            sell_raw = m.group(1)
            ex.method_rationale += (" Price was read from visible page text; no "
                                    "structured price field was present.")

    ex.selling = parse_price(sell_raw, currency_hint) if sell_raw is not None else None
    ex.regular = parse_price(reg_raw, currency_hint) if reg_raw is not None else None
    if not ex.currency:
        ex.currency = ((ex.selling.currency if ex.selling else None)
                       or currency_hint)

    sell_amt = ex.selling.amount if ex.selling else None
    reg_amt = ex.regular.amount if ex.regular else None
    amt, pct, dnotes = discount(reg_amt, sell_amt)
    ex.discount_amount, ex.discount_percent = amt, pct
    ex.warnings.extend(dnotes)

    # ---- stock, promo, variants, images ----
    ex.availability, ex.stock_text_raw = detect_stock(node, text)
    ex.promotion_text, ex.promotion_mechanism = detect_promotion(text)
    ex.variants = extract_variants(html, node, ex.currency)
    ex.images = extract_images(html, url, node)

    # A variant-selected price takes precedence over the parent display price.
    if ex.variants:
        vp = [to_decimal(v["price"]) for v in ex.variants if v.get("price")]
        vp = [v for v in vp if v is not None]
        if vp and sell_amt is not None and min(vp) != sell_amt and len(set(vp)) > 1:
            ex.warnings.append(
                f"variant prices span {min(vp)}-{max(vp)} {ex.currency or ''}".strip()
                + "; parent display price kept as selling_price and the range recorded")

    return validate(ex, allowed_host_check)


# --------------------------------------------------------------------------
# validation (§13)
# --------------------------------------------------------------------------

def validate(ex: Extraction, allowed_host_check=None) -> Extraction:
    """Deterministic verdict. Confidence is supporting metadata, not a substitute."""
    hard: list[str] = []

    if not ex.product_name:
        hard.append("missing product name")

    if not ex.url or not ex.url.startswith(("http://", "https://")):
        hard.append("invalid product URL")
    elif allowed_host_check is not None and not allowed_host_check(ex.url):
        hard.append("product URL is off the approved domain allowlist")

    if ex.selling is None:
        ex.warnings.append("no price found on the page; price unresolved")
    elif ex.selling.amount is None and not ex.selling.is_range:
        ex.warnings.append(
            f"price could not be parsed; raw text kept: {ex.selling.raw[:80]!r}")
        ex.warnings.extend(ex.selling.notes)
    else:
        ex.warnings.extend(ex.selling.notes)
        if not ex.currency:
            # §13: price without currency is unresolved unless a default is explicit.
            ex.warnings.append("price present without a currency; treated as unresolved")

    if ex.availability == UNKNOWN:
        ex.warnings.append("stock wording not recognised; mapped to unknown and raw kept")

    if not ex.images:
        ex.warnings.append("no usable product image found")

    # ---- confidence ----
    score = 0.0
    if ex.method == METHOD_STRUCTURED:
        score += 0.40
    else:
        score += 0.20
    if ex.product_name:
        score += 0.15
    if ex.selling and (ex.selling.amount is not None or ex.selling.is_range):
        score += 0.20
    if ex.currency:
        score += 0.10
    if ex.availability != UNKNOWN:
        score += 0.08
    if ex.images:
        score += 0.07
    ex.confidence = min(1.0, score)

    if hard:
        ex.errors.extend(hard)
        ex.verdict = REJECTED
    elif ex.warnings:
        ex.verdict = ACCEPTED_WITH_WARNINGS
    else:
        ex.verdict = ACCEPTED
    return ex


def browser_required(ex: Extraction) -> bool:
    """§9 step 4: only a genuinely thin page justifies a browser.

    Browser automation is not wired up in this build. A pair that reaches here
    escalates for a human rather than storing thin data as if it were complete.
    """
    return (ex.verdict == REJECTED
            or (ex.selling is None and not ex.variants and ex.confidence < 0.5))
