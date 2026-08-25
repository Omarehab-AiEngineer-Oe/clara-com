"""One rubric, applied identically to Clara and to every competitor.

Section 10 asks for "copy, CTA and image analysis using one common rubric", and
the word *one* is doing real work. If Clara were judged by a different standard
than the competitors, every comparison downstream would be an artefact of the
scoring rather than a fact about the websites. So there is a single set of tests
here and no site-specific branch anywhere in the file.

The rubric is deterministic and readable. That is a deliberate trade: a model
would judge prose better, but the platform has to work with Vertex unavailable,
and a verdict that changes depending on whether a model answered makes two runs
incomparable. So the rules are the floor, they state which signal fired, and a
model may later narrow a verdict — never widen one.

What the rubric can and cannot see, stated plainly because the report repeats it:

* It reads visible text, link and button labels, image filenames, alt text and
  surrounding captions. That is what a visitor sees, which is the right surface.
* It cannot judge taste, brand fit or photographic quality. Where it says an
  image type is missing, it means no image on the page presents itself as that
  type — not that the images present are bad.
* Every verdict carries the signal that produced it, so a reader can disagree
  with the rule instead of arguing with a score.
"""

from __future__ import annotations

import html as _html
import re
from urllib.parse import urljoin, urlsplit

from .contracts import (ImageKind, ObservationType, key_of)

# --------------------------------------------------------------------------
# copy: what makes a headline weak
# --------------------------------------------------------------------------

# Phrases that occupy the position of a value proposition without making a
# claim. Not "bad writing" — specifically interchangeable: true of any brand in
# any category, therefore telling the visitor nothing.
GENERIC_COPY = re.compile(
    r"\b(?:welcome(?: to)?|shop now|our products?|best quality|high quality|"
    r"premium quality|top quality|the best|number one|no\.?\s*1|leading|"
    r"world[- ]class|state[- ]of[- ]the[- ]art|cutting[- ]edge|innovative|"
    r"revolutionary|game[- ]chang\w+|unique|exclusive|amazing|awesome|"
    r"exceptional|unparalleled|luxur\w+ experience|for everyone|"
    r"customer satisfaction|we care|passion for beauty|your beauty journey|"
    r"discover more|learn more|find out more|read more|click here|see more)\b",
    re.I)

# The opposite: language that commits to something checkable.
SPECIFIC_COPY = re.compile(
    r"(?:\d+\s*(?:%|percent|w\b|watts?|°|degrees?|hours?|minutes?|mins?|"
    r"seconds?|secs?|days?|weeks?|months?|years?|ml\b|g\b|kg\b|rpm|"
    r"attachments?|settings?|speeds?|heat levels?|pieces?|in\s?1|sar\b|usd\b)"
    r"|\b(?:ionic|ceramic|tourmaline|keratin|argan|biotin|sulfate[- ]free|"
    r"paraben[- ]free|silicone[- ]free|vegan|cruelty[- ]free|dermatologist|"
    r"clinically|salon[- ]grade|professional[- ]grade|bldc|brushless|"
    r"cold shot|auto[- ]?wrap|coanda)\b)", re.I)

# A value proposition says who it is for or what changes. Either is enough.
VALUE_SIGNAL = re.compile(
    r"\b(?:for (?:curly|straight|wavy|fine|thick|coarse|coloured|colored|"
    r"damaged|dry|oily|frizzy|textured|afro|4[abc]|3[abc]) hair|"
    r"without (?:heat damage|frizz|breakage)|in (?:under )?\d+ (?:minutes?|mins?)|"
    r"reduces?|protects?|repairs?|restores?|strengthens?|smooths?|"
    r"cuts? drying time|no (?:heat damage|frizz))\b", re.I)


def normalise_text(t: str) -> str:
    return re.sub(r"\s+", " ", _html.unescape(t or "")).strip()


def copy_quality(text: str) -> tuple[str, list]:
    """strong / adequate / weak, plus the signals that decided it."""
    t = normalise_text(text)
    sig: list = []
    if not t:
        return "weak", ["empty"]
    words = t.split()

    generic = GENERIC_COPY.findall(t)
    specific = SPECIFIC_COPY.findall(t)
    value = VALUE_SIGNAL.findall(t)

    if generic:
        sig.append(f"interchangeable phrasing: {generic[0].strip().lower()!r} "
                   f"could sit on any brand's page")
    if specific:
        sig.append(f"a checkable detail: {str(specific[0]).strip().lower()!r}")
    if value:
        sig.append("names an audience or an outcome")
    if len(words) <= 2:
        sig.append(f"only {len(words)} word(s) — too short to make a claim")
    if len(words) > 45:
        sig.append(f"{len(words)} words in one block — a visitor scans, not reads")

    score = len(specific) + 2 * len(value) - (1 if generic else 0)
    if len(words) <= 2:
        score -= 1
    if score >= 2:
        return "strong", sig
    if score >= 1 or (not generic and len(words) >= 4):
        return "adequate", sig
    return "weak", sig or ["no specific claim, audience or outcome"]


# --------------------------------------------------------------------------
# ctas
# --------------------------------------------------------------------------

# A CTA that names the next action.
CTA_STRONG = re.compile(
    r"\b(?:add to (?:cart|bag|basket)|buy (?:now|it)|order now|check ?out|"
    r"book (?:a |an )?\w+|start (?:your |the )?\w+|get (?:yours|started|the)|"
    r"choose (?:your|a)|build (?:your|a)|find (?:your|the right)|"
    r"take the quiz|compare|watch the|see how|download|subscribe|"
    r"join|sign up|try|shop (?:the |all )?\w+)\b", re.I)

# A CTA that names only the act of clicking.
CTA_WEAK = re.compile(
    r"^\s*(?:more|read more|learn more|find out more|see more|discover|"
    r"discover more|click here|here|details|view|view all|explore|"
    r"continue|next|go|submit|ok|yes|no|shop|shop now|see all|all)\s*$", re.I)

CTA_TAG = re.compile(
    r"<(?:a|button)\b([^>]*)>(.*?)</(?:a|button)>", re.I | re.S)


def cta_quality(label: str) -> tuple[str, list]:
    t = normalise_text(label)
    if not t:
        return "weak", ["no label"]
    if CTA_WEAK.match(t):
        return "weak", [f"{t!r} names the click, not the outcome — a visitor "
                        f"cannot tell what happens next"]
    if CTA_STRONG.search(t):
        return "strong", [f"{t!r} names the next action"]
    if len(t.split()) >= 2:
        return "adequate", [f"{t!r} is specific enough to be understood"]
    return "weak", [f"{t!r} is a single generic word"]


def extract_ctas(html: str, base_url: str) -> list:
    """Link and button labels that behave like calls to action.

    Navigation and footer links are excluded by position, because a nav item is
    not a call to action and counting it as one would drown the real ones.
    """
    from .collect import strip_chrome
    body = strip_chrome(html or "")
    # Drop nav, header and footer regions before looking for CTAs.
    body = re.sub(r"<(nav|header|footer)\b[^>]*>.*?</\1>", " ", body,
                  flags=re.I | re.S)

    out, seen = [], set()
    for m in CTA_TAG.finditer(body):
        attrs, inner = m.group(1) or "", m.group(2) or ""
        label = normalise_text(re.sub(r"<[^>]+>", " ", inner))
        if not label or len(label) > 48:
            continue
        low = label.lower()
        if low in seen:
            continue
        cls = (re.search(r'class=["\']([^"\']*)', attrs, re.I) or [None, ""])[1]
        href = (re.search(r'href=["\']([^"\']*)', attrs, re.I) or [None, ""])[1]
        looks_like = bool(
            re.search(r"\b(btn|button|cta|add-to|addto|shop|buy|checkout|"
                      r"primary|action)\b", cls, re.I)
            or m.group(0)[:8].lower().startswith("<button")
            or CTA_STRONG.search(label) or CTA_WEAK.match(label))
        if not looks_like:
            continue
        seen.add(low)
        out.append({"label": label,
                    "href": urljoin(base_url, href) if href else "",
                    "css": cls[:60]})
        if len(out) >= 25:
            break
    return out


# --------------------------------------------------------------------------
# images
# --------------------------------------------------------------------------

IMAGE_HINTS = {
    ImageKind.INSTRUCTIONAL: re.compile(
        r"\b(?:how[- ]to|howto|step[- ]?\d|steps?|tutorial|guide|instruction|"
        r"manual|usage|use[- ]?guide|diagram)\b", re.I),
    ImageKind.RESULT: re.compile(
        r"\b(?:before[- ]?(?:and[- ]?)?after|before[- ]?after|b-?a|result|"
        r"transformation|day-?\d+|week-?\d+|outcome)\b", re.I),
    ImageKind.SOCIAL_PROOF: re.compile(
        r"\b(?:review|rating|testimonial|customer|ugc|as[- ]seen|press|"
        r"featured[- ]in|influencer|stars?)\b", re.I),
    ImageKind.TRUST: re.compile(
        r"\b(?:warrant\w+|guarantee|secure|payment|visa|mastercard|mada|"
        r"tabby|tamara|apple[- ]?pay|badge|certif\w+|authentic|iso|ce[- ]mark|"
        r"free[- ]?(?:shipping|delivery)|return|refund)\b", re.I),
    ImageKind.USE_CASE: re.compile(
        r"\b(?:curly|straight|wavy|fine|thick|coarse|textured|afro|"
        r"short[- ]hair|long[- ]hair|bob|hair[- ]type|for[- ]\w+[- ]hair|"
        r"occasion|everyday|travel)\b", re.I),
    ImageKind.FEATURE_DETAIL: re.compile(
        r"\b(?:detail|closeup|close[- ]up|zoom|nozzle|attachment|barrel|"
        r"bristle|motor|filter|button|display|cross[- ]?section|exploded|"
        r"tech(?:nology)?|spec)\b", re.I),
    ImageKind.LIFESTYLE: re.compile(
        r"\b(?:lifestyle|model|bathroom|mirror|salon|home|editorial|campaign|"
        r"portrait|hero|banner|shot)\b", re.I),
    ImageKind.PRODUCT: re.compile(
        r"\b(?:product|pack(?:shot|aging)?|bottle|box|kit|set|white[- ]?bg|"
        r"transparent|front|back|side|render)\b", re.I),
    ImageKind.DECORATIVE: re.compile(
        r"\b(?:icon|logo|sprite|pattern|texture|divider|arrow|placeholder|"
        r"spacer|bg|background|blob|shape|ornament|flag|payment-?icon)\b", re.I),
}

IMG_TAG = re.compile(r"<img\b([^>]*)>", re.I)
ATTR = re.compile(r'([a-zA-Z_:-]+)\s*=\s*["\']([^"\']*)["\']')

# Below this, an image is furniture rather than content.
MIN_CONTENT_PX = 120


def classify_image(src: str, alt: str, near: str = "",
                   width: int | None = None, height: int | None = None) -> tuple:
    """An image kind, plus the signal that decided it.

    Reads the filename, the alt text and the nearby caption — what a visitor and
    a screen reader are given. It cannot look at pixels, and the report says so:
    "no instructional images" means nothing on the page *presents itself* as one.
    """
    hay = " ".join([src or "", alt or "", near or ""])
    name = (urlsplit(src or "").path or "").rsplit("/", 1)[-1]

    small = ((width is not None and width < MIN_CONTENT_PX) or
             (height is not None and height < MIN_CONTENT_PX))
    if small:
        return ImageKind.DECORATIVE, [f"declared {width}x{height} — furniture size"]

    # Ordered by how specific the evidence is: a "how-to" filename is a stronger
    # claim than a "hero" one, so instructional is tested before lifestyle.
    for kind in (ImageKind.INSTRUCTIONAL, ImageKind.RESULT,
                 ImageKind.SOCIAL_PROOF, ImageKind.TRUST, ImageKind.USE_CASE,
                 ImageKind.FEATURE_DETAIL, ImageKind.DECORATIVE,
                 ImageKind.PRODUCT, ImageKind.LIFESTYLE):
        m = IMAGE_HINTS[kind].search(hay)
        if m:
            return kind, [f"{m.group(0).lower()!r} in "
                          f"{'the alt text' if alt and m.group(0).lower() in alt.lower() else 'the filename or caption'}"]
    if alt and len(alt.split()) >= 3:
        return ImageKind.PRODUCT, [f"described alt text, no type marker: {alt[:48]!r}"]
    if name:
        return ImageKind.UNCLASSIFIED, [f"nothing in {name!r} or the alt text "
                                        f"says what this image is for"]
    return ImageKind.UNCLASSIFIED, ["no filename or alt text to read"]


def extract_images(html: str, base_url: str) -> list:
    """Meaningful images, with alt text, declared size and nearby caption."""
    from .collect import strip_chrome
    body = strip_chrome(html or "")
    out, seen = [], set()
    for m in IMG_TAG.finditer(body):
        a = dict(ATTR.findall(m.group(1) or ""))
        src = (a.get("src") or a.get("data-src") or a.get("data-original")
               or (a.get("srcset") or "").split(" ")[0] or "")
        if not src or src.startswith("data:"):
            continue
        url = urljoin(base_url, src)
        if url in seen:
            continue
        seen.add(url)

        def num(k):
            try:
                return int(re.sub(r"[^0-9]", "", a.get(k) or "") or 0) or None
            except ValueError:
                return None

        # 220 characters after the tag: enough to catch a caption, not enough to
        # swallow the next section's copy.
        near = normalise_text(re.sub(r"<[^>]+>", " ",
                                     body[m.end():m.end() + 220]))[:160]
        alt = normalise_text(a.get("alt") or "")
        kind, sig = classify_image(url, alt, near, num("width"), num("height"))
        out.append({"url": url, "alt": alt, "near": near, "kind": kind,
                    "signals": sig, "has_alt": bool(alt),
                    "width": num("width"), "height": num("height")})
        if len(out) >= 60:
            break
    return out


# --------------------------------------------------------------------------
# structure: headings, value props, proof and trust
# --------------------------------------------------------------------------

HEADING = re.compile(r"<h([1-6])\b[^>]*>(.*?)</h\1>", re.I | re.S)

SOCIAL_PROOF_TEXT = re.compile(
    r"\b(?:\d[\d,.]*\s*(?:reviews?|ratings?|customers?|users?|sold)|"
    r"\d(?:\.\d)?\s*(?:/\s*5|out of 5|stars?)|verified (?:buyer|purchase)|"
    r"testimonial|what (?:our )?customers? say|as seen in|featured in|"
    r"trustpilot|reviews?\b)", re.I)

TRUST_TEXT = re.compile(
    r"\b(?:free (?:shipping|delivery|returns?)|money[- ]back|"
    r"\d+[- ](?:day|month|year)s? (?:warranty|guarantee|returns?)|"
    r"warranty|guarantee|secure (?:payment|checkout)|authorised dealer|"
    r"authentic|original product|cash on delivery|tabby|tamara|mada|"
    r"easy returns?|refund polic)", re.I)

USE_CASE_TEXT = re.compile(
    r"\b(?:for (?:curly|straight|wavy|fine|thick|coarse|coloured|colored|"
    r"damaged|dry|oily|frizzy|textured|afro|all|short|long|thin) hair|"
    r"hair type|suited (?:to|for)|ideal for|works? (?:on|for)|"
    r"which \w+ is right|find your)\b", re.I)

OFFER_TEXT = re.compile(
    r"(?:\b\d{1,2}\s*%\s*(?:off|discount)|\bsave\s+\d|\bbundle\b|"
    r"\bfree gift\b|\buse code\b|\bpromo code\b|\bsale\b|\boffer ends\b)", re.I)


def headings(html: str) -> list:
    out = []
    for m in HEADING.finditer(strip := (html or "")):
        level = int(m.group(1))
        text = normalise_text(re.sub(r"<[^>]+>", " ", m.group(2)))
        if text and len(text) < 240:
            out.append({"level": level, "text": text})
        if len(out) >= 60:
            break
    return out


def section_for(html: str, needle: str) -> str:
    """A human-readable name for where on the page something sits.

    The nearest preceding heading, or the region if there is none. "Where on
    Clara's website" is a required field on every finding, and a URL alone does
    not answer it.
    """
    if not html or not needle:
        return "page body"
    i = html.find(needle[:60])
    if i < 0:
        return "page body"
    before = html[:i]
    hs = HEADING.findall(before)
    if hs:
        text = normalise_text(re.sub(r"<[^>]+>", " ", hs[-1][1]))
        if text:
            return f"under “{text[:60]}”"
    for region, label in (("<footer", "footer"), ("<header", "header"),
                          ("<nav", "navigation")):
        if before.rfind(region) > before.rfind("</" + region[1:]):
            return label
    return "above the first heading" if not hs else "page body"


def presence_scan(text: str) -> dict:
    """Which of the four content jobs the page's own words actually do."""
    return {
        ObservationType.SOCIAL_PROOF: [m.group(0) for m in
                                       SOCIAL_PROOF_TEXT.finditer(text)][:6],
        ObservationType.TRUST: [m.group(0) for m in
                               TRUST_TEXT.finditer(text)][:6],
        ObservationType.USE_CASE: [m.group(0) for m in
                                  USE_CASE_TEXT.finditer(text)][:6],
        ObservationType.OFFER: [m.group(0) for m in
                               OFFER_TEXT.finditer(text)][:6],
    }


def repetition(strings: list, *, min_len: int = 12) -> list:
    """Phrases repeated across a site. Section 6.2 asks for repeated content.

    Compared on a normalised form so casing and punctuation do not hide a
    duplicate, and reported with a count rather than a flag, because twice is a
    pattern and six times is a problem.
    """
    seen: dict = {}
    for s in strings:
        t = normalise_text(s).lower().rstrip(".!:;")
        if len(t) < min_len:
            continue
        seen.setdefault(t, {"text": normalise_text(s), "count": 0})
        seen[t]["count"] += 1
    return sorted([v for v in seen.values() if v["count"] > 1],
                  key=lambda d: -d["count"])
