"""Offers Sweep Agent — visit every competitor and collect what they advertise.

The monitoring loop reads a competitor's page only when it is chasing a specific
Clara product, which is why 43 of 46 competitors had no offer data: nothing had
ever pointed at them. This agent inverts that. It goes to each competitor's own
storefront and reads what is being promoted, with no product matching involved,
so coverage is a function of how many brands are registered rather than how many
pairings exist.

Where it looks, and why only there:

    /                     the storefront banner is where a sale is announced
    /sale /offers         the conventional names for a promotions page
    /deals /promotions
    /collections/sale     Shopify's convention, which many of these brands use

A handful of paths per brand, tried in order, stopping at the first that yields a
promotion. That bounds the sweep at a few hundred fetches rather than a crawl, and
every one goes through `access.guarded_get`: robots honoured, one honest user
agent, no credentials, a refusal recorded as a refusal and never retried
differently.

**What counts as an offer.** Promotional wording the page printed, with the
mechanism it uses — bundle, percentage, coupon, free shipping, gift. A discount
*percentage* is only recorded where two real prices appeared on the same page,
which almost never happens on a storefront banner. So most rows here are honest
wording with `discount_percent` left empty, and the report says that rather than
multiplying a banner claim into a number nobody published.
"""

from __future__ import annotations

import re
from urllib.parse import urljoin, urlsplit

from .. import access, competitors as comp, extract
from ..money import detect_currency, parse_price
from .base import Agent
from .contracts import Confidence, Evidence, now_iso

# Tried in order. The storefront first, because a live sale is almost always on
# the banner, and a dedicated promotions page is the exception rather than the
# rule for brand sites.
PATHS = ("", "/sale", "/offers", "/deals", "/promotions", "/collections/sale",
         "/collections/all", "/en/sale")

# Wording that means a real commercial offer, not a newsletter widget or a
# shipping-policy line. Deliberately narrower than "the page says discount".
OFFER_PATTERNS = [
    ("percent_off", r"\b(\d{1,2})\s*%\s*(?:off|discount|sale|كسم|خصم)\b"
                    r"|\bsave\s+(\d{1,2})\s*%"),
    ("amount_off", r"\bsave\s+(?:sar|aed|usd|£|\$|€)\s?\d+"
                   r"|\b(?:sar|aed|usd|£|\$|€)\s?\d+\s+off\b"),
    ("coupon", r"\buse code\b|\bcoupon\b|\bpromo code\b|\bwith code\b"
               r"|\bكود\b"),
    ("bundle", r"\bbundle\b|\bset\b.{0,12}\bsave\b|\bbuy\s*\d\s*get\b"
               r"|\b2\s*for\s*1\b|\bkit\b.{0,12}\bsave\b"),
    ("free_gift", r"\bfree gift\b|\bgift with purchase\b|\bgwp\b"
                  r"|\bcomplimentary\b"),
    ("free_shipping", r"\bfree (?:shipping|delivery)\b|\bتوصيل مجاني\b"),
    ("clearance", r"\bclearance\b|\boutlet\b|\blast chance\b|\bfinal sale\b"),
    ("seasonal", r"\bblack friday\b|\bwhite friday\b|\bramadan\b|\beid\b"
                 r"|\bsummer sale\b|\bwinter sale\b|\bmid[- ]season\b"),
    ("new_customer", r"\bfirst order\b|\bnew customer\b|\bwelcome offer\b"
                     r"|\bsign up and save\b"),
]

# Lines that look promotional but are not an offer. Without this the sweep
# returns every site's cookie banner and loyalty-programme blurb.
NOT_AN_OFFER = re.compile(
    # policy and footer boilerplate
    r"\bprivacy\b|\bcookie\b|\bterms\b|\bunsubscribe\b|\bnewsletter\b"
    r"|\breturns? policy\b|\bshipping policy\b|\bcareers\b"
    # cart and navigation chrome — where the first sweep found its worst
    # rows. A subtotal widget is not an offer and neither is a page title.
    r"|\bskip to content\b|\bsubtotal\b|\bview bag\b"
    r"|\byour (?:bag|cart)\b|\bcheckout\b|\bnavigation\b"
    r"|\bmy account\b|\bsign in\b|\badd to (?:bag|cart)\b"
    r"|المجموع|الدفع|عند الخروج|عرض عرب", re.I)


def _looks_like_chrome(line: str) -> bool:
    """A header or a widget rather than a sentence a shopper reads.

    Three cheap shape tests. Several pipes means a breadcrumb or a title.
    HTML entities mean the text came from markup that was never prose. Mostly
    capitalised means a navigation bar. None of them is about the words.
    """
    if line.count("|") >= 2:
        return True
    if line.count("&") >= 3 or "&#x" in line or "&reg" in line.lower():
        return True
    words = line.split()
    if len(words) > 6:
        caps = sum(1 for w in words if w[:1].isupper())
        if caps / len(words) > 0.75:
            return True
    return False

MAX_SNIPPET = 220


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()



def _is_markup_residue(line: str) -> bool:
    """Framework attributes and inline JSON that survived tag stripping.

    `strip_html` removes tags but keeps what was inside attribute values and
    inline scripts, so a Vue or Alpine storefront leaks lines like
    `x-text="variantPrice" >£229.00` and an inline product feed leaks
    `"freeProductLabelTextV2":"Free"`. Both read as offers to a keyword filter.

    Shape, not vocabulary: an offer line a shopper reads contains no attribute
    syntax, no JSON punctuation and no template braces. Testing the shape catches
    the whole class rather than one framework at a time.
    """
    if '="' in line or "':" in line or '":' in line:
        return True
    if "{" in line or "}" in line or "[" in line and "]" in line:
        return True
    if line.count('"') >= 4 or line.count(">") >= 2:
        return True
    if "x-text" in line or "v-if" in line or "data-" in line:
        return True
    return False


def _snippets(page_text: str) -> list[tuple[str, str]]:
    """(mechanism, the sentence the page actually printed).

    Returns the surrounding sentence rather than the matched token, because "25%"
    on its own is not quotable and "25% off everything with code SUMMER" is.
    """
    out: list[tuple[str, str]] = []
    seen: set[str] = set()
    sentences = re.split(r"(?<=[.!?])\s+|\s{3,}|\n+", page_text)
    for raw in sentences:
        line = _clean(raw)
        if not line or len(line) < 6 or len(line) > 300:
            continue
        if (NOT_AN_OFFER.search(line) or _looks_like_chrome(line)
                or _is_markup_residue(line)):
            continue
        for mech, pat in OFFER_PATTERNS:
            if not re.search(pat, line, re.I):
                continue
            key = (mech, line.lower()[:80])
            if key in seen:
                continue
            seen.add(key)
            out.append((mech, line[:MAX_SNIPPET]))
            break
    return out


class OfferSweepAgent(Agent):
    name = "offer_sweep"
    prompt_file = "live_competitor_offers.md"

    def run_rules(self, keys: list[str] | None = None,
                  max_paths: int = 4) -> dict:
        targets = keys or sorted(comp.REGISTRY)
        allowed: set[str] = set()
        for c in comp.REGISTRY.values():
            allowed.update(c.all_domains())

        found, per_competitor, blocked = [], {}, []
        stamp = now_iso()

        for key in targets:
            c = comp.REGISTRY.get(key)
            if not c or not c.domains:
                continue
            base = f"https://{c.domains[0]}"
            hits, refusals, pages_read = [], [], 0

            for path in PATHS[:max_paths]:
                url = urljoin(base + "/", path.lstrip("/")) if path else base
                res = access.guarded_get(url, allowed_hosts=allowed,
                                         max_retries=1, timeout=22)
                if not res.ok:
                    refusals.append({"url": url,
                                     "signal": res.block_signal
                                     or f"HTTP {res.status}"})
                    continue
                pages_read += 1
                html_text = res.html or ""
                text = extract.strip_html(html_text)

                # The extractor's own promotion detector first — it is the same
                # one the monitoring loop uses, so a hit here is consistent with
                # what the rest of the system would have recorded.
                promo_text, mechanism = extract.detect_promotion(text)
                if (promo_text and not NOT_AN_OFFER.search(promo_text)
                        and not _looks_like_chrome(promo_text)
                        and not _is_markup_residue(promo_text)):
                    hits.append({
                        "mechanism": mechanism or "unknown",
                        "wording": _clean(promo_text)[:MAX_SNIPPET],
                        "url": url,
                        "via": "page promotion detector",
                    })

                for mech, line in _snippets(text)[:6]:
                    if any(h["wording"][:60] == line[:60] for h in hits):
                        continue
                    hits.append({"mechanism": mech, "wording": line, "url": url,
                                 "via": "offer wording on the page"})

                if hits:
                    # The currency the page trades in, for context on the
                    # wording. Not a price comparison — that needs a product.
                    cur = detect_currency(text)
                    if cur:
                        hits[-1]["currency_on_page"] = cur

                if hits:
                    # The storefront answered; no need to walk the rest.
                    break

            for h in hits[:8]:
                found.append({
                    "competitor_key": key,
                    "competitor": c.brand,
                    "tier": c.tier,
                    "segments": c.segments,
                    "mechanism": h["mechanism"],
                    "wording": h["wording"],
                    "url": h["url"],
                    "via": h["via"],
                    "currency_on_page": h.get("currency_on_page") or "",
                    # Almost never available on a banner, and never derived.
                    "discount_percent": None,
                    "discount_note": ("the page printed no before-and-after pair, "
                                      "so the advertised figure is the retailer's "
                                      "claim and is not restated as a saving"),
                    "observed_at": stamp,
                    "confidence": (Confidence.HIGH if c.tier == "brand_official"
                                   else Confidence.MEDIUM),
                })

            per_competitor[key] = {
                "competitor": c.brand,
                "offers": len(hits[:8]),
                "pages_read": pages_read,
                "refusals": refusals,
            }
            if not pages_read and refusals:
                blocked.append({"competitor": c.brand,
                                "signal": refusals[0]["signal"],
                                "url": refusals[0]["url"]})

        with_offers = [v["competitor"] for v in per_competitor.values()
                       if v["offers"]]
        readable = [v["competitor"] for v in per_competitor.values()
                    if v["pages_read"]]
        mechanisms: dict = {}
        for f in found:
            mechanisms[f["mechanism"]] = mechanisms.get(f["mechanism"], 0) + 1

        self.report.items_in = len(targets)
        self.report.items_out = len(found)
        self.report.blocked = blocked
        self.report.note(
            f"{len(readable)} of {len(targets)} storefronts answered; "
            f"{len(with_offers)} are advertising something; {len(found)} offer "
            f"line(s) collected")
        self.report.note(
            "no discount percentage was derived: a banner claim is not a "
            "before-and-after pair, and the sweep does not turn one into the "
            "other")
        if blocked:
            self.report.note(f"{len(blocked)} storefront(s) refused every path "
                             f"tried and are escalated rather than retried")

        return {
            "swept_at": stamp,
            "offers": found,
            "per_competitor": per_competitor,
            "with_offers": sorted(with_offers),
            "readable": sorted(readable),
            "blocked": blocked,
            "mechanisms": dict(sorted(mechanisms.items(), key=lambda kv: -kv[1])),
            "counts": {
                "competitors_tried": len(targets),
                "storefronts_read": len(readable),
                "competitors_advertising": len(with_offers),
                "offer_lines": len(found),
                "refused": len(blocked),
                "verifiable_discounts": 0,
            },
            "note": ("Each line is wording the competitor printed on its own "
                     "page, with the URL it was read from. A discount percentage "
                     "is recorded only where the page showed both a before and an "
                     "after price; a storefront banner almost never does, so the "
                     "percentages here are claims rather than measured savings."),
        }

    def refine(self, result, keys=None, max_paths=4):
        """No model pass. Every line is a quotation from a page; a rewrite would
        make it read better and stop being a quotation."""
        return None
