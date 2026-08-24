"""Load the in-scope Clara catalog.

Two sources: the seed crawl in data/, and a live re-crawl of clarahair.com
via the same guarded fetch every other read uses. Format classification and
spec extraction are derived from the product's own page text, so a product
whose description is not in English is recorded as such rather than guessed
at — that fact is itself reportable.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from .access import guarded_get
from .config import CLARA_DEVICE_IDS, SEED_CATALOG
from .models import ClaraProduct

CLARA_HOSTS = {"clarahair.com"}

# Format classification. Order matters: the first pattern to match wins, so
# the more specific formats are tested before the general ones.
# Word boundaries are load-bearing here: without \b, "hair brush" contains the
# substring "air brush" and every hot brush in the catalog is misread as an
# air-styling brush. Patterns are also deliberately noun-based — matching the
# verb "straighten" made a 2000 W dryer classify as a straightener because its
# copy said "straighten & style with the dryer nozzle".
# Clara-side and competitor-side naming both have to resolve here. Competitors
# rarely use Clara's words: an Airwrap and a FlexStyle are the same format as a
# "Multi-Use Hair Dryer" but share no vocabulary with it, so the model names are
# listed explicitly rather than left to be inferred. A competitor product whose
# format cannot be read is left "unknown" and disqualified — never guessed.
FORMAT_RULES = [
    ("straightener_brush", r"\bdual slim brush\b|\bstraightener\s*\+\s*brush\b"
                           r"|\bstraightening brush\b|\bairstrait\b"
                           r"|ستريتنر\s*\+?\s*فرشاة"),
    ("multi_styler", r"\bmulti[- ]?styler\b|\bmulti[- ]?use hair dryer\b"
                     r"|\bairwrap\b|\bflexstyle\b|\bair styling\b"
                     r"|\bstyling (?:&|and) drying system\b|\bstyling system\b"
                     r"|\b\d\s*[- ]?in[- ]\s*\d\b|متعدد الاستخدام"),
    ("auto_curler", r"\bauto\w*\s+(?:wavy|curl)|\bwavy hair curler\b"
                    r"|\bcurling device\b|\bcurling iron\b|\bcurler\b|تمويج"),
    ("air_brush", r"\bairglow\b|\bair brush\b|\bair hair brush\b"
                  r"|\bair styling brush\b|\bhot air brush\b"
                  r"|فرشاة الشعر الهوائية"),
    ("hot_brush", r"\bhot brush\b|\bthermal brush\b|\bionic (?:hair )?brush\b"
                  r"|\bvolumi[sz]er\b|\bone[- ]step\b"
                  r"|\bblow[- ]?dry brush\b|فرشاة (?:ال)?حرارية"),
    ("straightener", r"\bstraightener\b|\bflat iron\b|\bhair straightening iron\b"
                     r"|\bcorrale\b|\bplatinum\+|\bsmart styler\b"
                     r"|\bمملس\b|بلاتينيوم"),
    ("dryer", r"\bhair ?dryer\b|\bblow[- ]?dry\w*\b|\bblow dryer\b"
              r"|\bsupersonic\b|\bhigh[- ]speed hair dryer\b|استشوار|مجفف"),
]

# Segment and category for the whole catalog, not just the devices. §7 wants the
# full Clara catalog loaded; §14's product_competitor_targets then decides which
# products get a competitor set. Accessories deliberately resolve to categories
# with no assigned rival rather than being force-matched to one.
CATEGORY_RULES = [
    ("device",    "device",        r"\bdryer\b|\bstraightener\b|\bcurler\b"
                                   r"|\bstyler\b|\bairglow\b|استشوار|مملس|فرشاة (?:ال)?حرارية"),
    ("haircare",  "shampoo",       r"\bshampoo\b|شامبو"),
    ("haircare",  "conditioner",   r"\bconditioner\b|\bleave[- ]?in\b|بلسم"),
    ("haircare",  "mask",          r"\bmask\b|\bmasque\b|ماسك|قناع"),
    ("haircare",  "serum",         r"\bserum\b|سيروم"),
    ("haircare",  "oil",           r"\bhair oil\b|\bargan\b|زيت"),
    ("haircare",  "heat_protect",  r"\bheat protect\w*\b|\bprotection (?:&|and) "
                                   r"(?:hydration|repair)\b|\brepair (?:&|and) protection\b"
                                   r"|واقي (?:ال)?حراري|الحماية"),
    ("haircare",  "styling_spray", r"\bhairspray\b|\bhair spray\b|\bsetting spray\b"
                                   r"|\bshine spray\b|\bflexible hairspray\b|بخاخ"),
    ("haircare",  "styling_foam",  r"\bfoam\b|\bmousse\b|رغوة"),
    ("haircare",  "styling_wax",   r"\bwax\b|\bpomade\b|\bgloss balm\b|واكس"),
    ("haircare",  "dry_shampoo",   r"\bdry shampoo\b|شامبو (?:ال)?جاف"),
    ("haircare",  "scalp",         r"\bscalp\b|\bexfoliat\w*\b|\bscrub\b|فروة|مقشر"),
    ("haircare",  "perfume",       r"\bperfume\b|\bfragrance\b|عطر"),
    ("accessory", "bag",           r"\bbag\b|\bpouch\b|\borganizer\b|\bcase\b|حقيبة|شنطة"),
    ("accessory", "accessory",     r"\bcomb\b|\bclips?\b|\bmassager\b|\bpatch\b|\bcap\b"
                                   r"|\bmascara\b|\bbrush\b|مشط|بنس|فرشاة"),
]


# Parts and add-ons. If one of these is in the product NAME it is an accessory,
# whatever the surrounding copy says about the appliance it attaches to.
ACCESSORY_ONLY = re.compile(
    r"\bdiffuser\b|\bbarrel\b|\battachment\b|\bnozzle\b|\bcomb\b|\bclips?\b|\bmassager\b|\bpatch\b|\bcap\b|\bbag\b|\bpouch\b|\borganizer\b|\bmascara\b"
    r"|ديفيوزر|مشط|بنس|حقيبة|شنطة", re.I)


# Product nouns that settle the question on their own. If one of these is in the
# NAME the item is a consumable, whatever device-shaped wording sits beside it —
# "2-in-1", "3-in-1", "multi" and "system" all appear in bottle names too.
CONSUMABLE_ONLY = re.compile(
    r"\bshampoo\b|\bconditioner\b|\bleave[- ]?in\b|\bmasque\b|\bhair mask\b"
    r"|\bserum\b|\bhair oil\b|\bhairspray\b|\bhair spray\b|\bshine spray\b"
    r"|\bsetting spray\b|\bmousse\b|\bpomade\b|\bheat protect\w*\b"
    r"|\bdry shampoo\b|\bscrub\b|\bperfume\b|\bfragrance\b"
    r"|شامبو|بلسم|ماسك|سيروم|بخاخ|رغوة|واكس|عطر", re.I)


# Arabic attaches the definite article to every word of a phrase, so "فرشاة
# حرارية" and "الفرشاة الحرارية" are the same noun spelled two ways and only the
# first was matched. A real bundle — a dual thermal brush sold with a protect
# spray and a shine serum — therefore missed the device test, matched "بخاخ" in
# the consumable test, and was filed as a serum. Single words need no such care:
# without a word boundary, "استشوار" already matches inside "الاستشوار".
#
# The device nouns, for one question only: "is there an actual appliance named in
# this name?" It is deliberately not CATEGORY_RULES[0] verbatim — that row has no
# heated-brush terms, and an "Air Hair Brush & Hair Shine Spray Set" is a device
# with a bottle in the box, not a bottle. Bare "brush" stays out, because that is
# a hairbrush and belongs to the accessory rules.
DEVICE_NOUN = re.compile(
    r"\bdryer\b|\bstraightener\b|\bcurler\b|\bstyler\b|\bairglow\b"
    r"|\bblow[- ]?dry\w*\b|\bflat iron\b"
    r"|\b(?:air|hot|ionic|thermal|volumiz\w+)\s+(?:hair\s+)?brush\b"
    r"|استشوار|مملس|فرشاة (?:ال)?حرارية", re.I)


def _category_from(text: str) -> tuple[str, str] | None:
    low = (text or "").lower()
    if not low.strip():
        return None
    for segment, category, pat in CATEGORY_RULES:
        if re.search(pat, low):
            return segment, category
    return None


def classify_category(name: str, description: str = "") -> tuple[str, str]:
    """(segment, category), resolved from the NAME before the description.

    Order matters. A shampoo whose page copy mentions the multi-styler was being
    classified as a device and then compared against a 2,299-riyal Airwrap. The
    name is the reliable signal, so both the device test and the category test
    run against it first; the description is only a fallback for products the
    name leaves unresolved.
    """
    # 0. an explicit part or add-on in the name
    if ACCESSORY_ONLY.search(name or ""):
        hit = _category_from(name)
        return hit if hit and hit[0] == "accessory" else ("accessory", "accessory")
    # 1. a consumable noun with NO device format beside it settles the question.
    #    Both together is a bundle, not a bottle: "Multi-Use Hair Dryer, Repair &
    #    Protection" leads with a dryer and must stay a device, while "2-in-1
    #    Conditioner & Leave-In" has no device in it at all and was only reading
    #    as one because "2-in-1" looks like a multi-styler.
    if CONSUMABLE_ONLY.search(name or "") and not DEVICE_NOUN.search(name or ""):
        hit = _category_from(name)
        return hit if hit and hit[0] == "haircare" else ("haircare", "haircare")
    # 2. the name says it is a device
    if classify_format(name) != "unknown":
        return "device", "hair_styling_device"
    # 3. the name says which non-device category it is
    hit = _category_from(name)
    if hit:
        return hit
    # 4. fall back to the description for a device format
    if classify_format(name, description) != "unknown":
        return "device", "hair_styling_device"
    # 5. and finally the description for a category
    hit = _category_from(f"{name} {description}")
    return hit or ("unknown", "unknown")


SPEC_PATTERNS = {
    "power_w": r"(\d{2,4})\s*(?:watts?|w\b|واط)",
    "voltage": r"(\d{2,3}\s*-\s*\d{2,3}\s*V|\d{3}\s*(?:volts?|فولت))",
    "heat_settings": r"(\w+|\d)\s*heat (?:degrees|settings|levels)|(\d)\s*درجات? حرارة",
    "auto_off_min": r"(?:after|بعد)\s*(\d{2})\s*(?:min|minutes|دقيقة)",
    "attachment_count": r"(\d)\s*(?:styling )?attachments|(\d)\s*رؤوس",
}

_NUM_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6}


def classify_format(text: str, description: str = "") -> str:
    """Classify on the product name first; fall back to the description.

    The name is the reliable signal. Description copy routinely mentions other
    formats — a dryer's page talks about straightening, a straightener's page
    talks about curls — so letting the description win produces confident
    misclassification and therefore the wrong assigned competitors.
    """
    for source in (text, f"{text} {description}"):
        low = (source or "").lower()
        if not low.strip():
            continue
        for fmt, pat in FORMAT_RULES:
            if re.search(pat, low):
                return fmt
    return "unknown"


def detect_language(text: str) -> str:
    """Which language the /en/ storefront actually served."""
    if not text:
        return "unknown"
    arabic = len(re.findall(r"[؀-ۿ]", text))
    latin = len(re.findall(r"[A-Za-z]", text))
    if arabic > 40 and arabic > latin:
        return "ar"
    if latin > 40:
        return "en"
    return "unknown"


def extract_specs(text: str) -> dict:
    specs: dict = {}
    low = text.lower()

    m = re.search(SPEC_PATTERNS["power_w"], low)
    if m:
        specs["power_w"] = int(m.group(1))

    m = re.search(SPEC_PATTERNS["voltage"], text, re.I)
    if m:
        specs["voltage"] = re.sub(r"\s+", "", m.group(1))

    # heat settings: numeric, worded, or the Arabic form
    m = re.search(r"(\d)\s*heat (?:degrees|settings|levels)", low)
    if m:
        specs["heat_settings"] = int(m.group(1))
    else:
        m = re.search(r"(one|two|three|four|five|six)\s+(?:heat|temperature)", low)
        if m:
            specs["heat_settings"] = _NUM_WORDS[m.group(1)]
        else:
            m = re.search(r"(\d)\s*درجات? حرارة", text)
            if m:
                specs["heat_settings"] = int(m.group(1))

    temps = re.findall(r"\b(1[5-9]\d|2[0-2]\d)\s*(?:°|º)?\s*[cC]?\b", text)
    temps = sorted({int(t) for t in temps if 140 <= int(t) <= 230})
    if temps:
        specs["temperatures_c"] = temps

    m = re.search(r"(\d)\s*(?:styling )?attachments", low) or re.search(r"(\d)\s*رؤوس", text)
    if m:
        specs["attachment_count"] = int(m.group(1))

    m = re.search(SPEC_PATTERNS["auto_off_min"], low)
    if m:
        specs["auto_off_min"] = int(m.group(1))

    specs["ionic"] = bool(re.search(r"ionic|negative ion|أيوني", low))
    specs["bldc_motor"] = bool(re.search(r"bldc|brushless", low))
    specs["cold_shot"] = bool(re.search(r"cold air|cool shot|الهواء البارد", low))
    return specs


def _from_seed_record(rec: dict) -> ClaraProduct:
    desc = rec.get("description") or ""
    name = rec.get("name") or ""
    blob = f"{name} {desc}"
    fmt = classify_format(name, desc)
    segment, category = classify_category(name, desc)
    return ClaraProduct(
        product_id=rec["url"].rstrip("/").split("/")[-1],
        name=name,
        url=rec["url"],
        price=rec.get("price"),
        currency=rec.get("currency") or "SAR",
        rating=rec.get("rating"),
        rating_count=rec.get("rating_count"),
        image_url=rec.get("image"),
        fmt=fmt,
        segment=segment,
        category=category,
        specs=extract_specs(blob),
        description_lang=detect_language(desc),
    )


def load_from_seed(path: Path = SEED_CATALOG,
                   scope: list[str] | None = None) -> list[ClaraProduct]:
    """Load the Clara catalog. `scope=None` loads every product (§7), not only
    the device lineup — the price report covers the whole catalog."""
    records = json.loads(path.read_text(encoding="utf-8"))
    by_id: dict[str, ClaraProduct] = {}
    for rec in records:
        if not rec.get("name"):
            continue
        p = _from_seed_record(rec)
        # keep the richest description per product id
        prev = by_id.get(p.product_id)
        if prev is None or len(str(p.specs)) > len(str(prev.specs)):
            by_id[p.product_id] = p
    if scope:
        out = []
        for pid in scope:
            if pid in by_id:
                p = by_id[pid]
                p.in_scope = True
                out.append(p)
        return out
    return sorted(by_id.values(),
                  key=lambda p: (p.segment != "device", -(p.price or 0)))


# --- live refresh ----------------------------------------------------------

_JSONLD = re.compile(r'<script type="application/ld\+json">(.*?)</script>', re.S)


def _strip(html: str) -> str:
    html = re.sub(r"<[^>]+>", " ", html)
    for a, b in (("&nbsp;", " "), ("&amp;", "&"), ("&quot;", '"'),
                 ("&#039;", "'"), ("&lt;", "<"), ("&gt;", ">")):
        html = html.replace(a, b)
    return re.sub(r"\s+", " ", html).strip()


def parse_clara_page(url: str, html: str) -> ClaraProduct | None:
    prod = None
    for blob in _JSONLD.findall(html):
        try:
            j = json.loads(blob)
        except json.JSONDecodeError:
            continue
        nodes = j.get("@graph", [j]) if isinstance(j, dict) else []
        for n in nodes:
            if isinstance(n, dict) and n.get("@type") == "Product":
                prod = n
    if not prod:
        return None

    i = html.rfind('id="product-details-tab"')
    desc = ""
    if i > -1:
        desc = re.split(r"Search Home Categories Account", _strip(html[i:i + 12000]))[0][:6000]

    offers = prod.get("offers") or {}
    rating = prod.get("aggregateRating") or {}
    blob = f"{prod.get('name','')} {desc}"
    fmt = classify_format(prod.get("name", ""), desc)
    segment, category = classify_category(prod.get("name", ""), desc)
    return ClaraProduct(
        product_id=url.rstrip("/").split("/")[-1],
        name=prod.get("name") or "",
        url=url,
        price=offers.get("price"),
        currency=offers.get("priceCurrency") or "SAR",
        rating=round(rating["ratingValue"], 2) if rating.get("ratingValue") else None,
        rating_count=rating.get("ratingCount"),
        image_url=prod.get("image"),
        fmt=fmt,
        segment=segment,
        category=category,
        specs=extract_specs(blob),
        description_lang=detect_language(desc),
    )


def refresh_from_site(products: list[ClaraProduct]) -> tuple[list[ClaraProduct], list[dict]]:
    """Re-read each Clara product page through the access gate.

    Returns (refreshed products, problems). A blocked or 404 Clara page is a
    problem to escalate, not a reason to drop the product from scope.
    """
    out, problems = [], []
    for p in products:
        res = guarded_get(p.url, CLARA_HOSTS)
        if res.blocked:
            problems.append({"product_id": p.product_id, "kind": "blocked",
                             "signal": res.block_signal, "evidence": res.evidence})
            out.append(p)
            continue
        if not res.ok or not res.html:
            problems.append({"product_id": p.product_id, "kind": "unreadable",
                             "signal": f"http_{res.status}", "evidence": res.evidence})
            out.append(p)
            continue
        fresh = parse_clara_page(p.url, res.html)
        if fresh is None:
            problems.append({"product_id": p.product_id, "kind": "no_product_data",
                             "signal": "no Product JSON-LD on page", "evidence": res.evidence})
            out.append(p)
            continue
        fresh.in_scope = p.in_scope
        out.append(fresh)
    return out, problems
