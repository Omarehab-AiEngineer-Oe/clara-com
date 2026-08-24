"""إطار المنتجات — the product frame every page and every agent works inside.

Clara sells four families of thing, and nothing else:

    ١. أجهزة تصفيف الشعر: أدوات التصفيف والملحقات
    ٢. منتجات العناية بالشعر والفروة
    ٣. منتجات الحماية من الحرارة، الترطيب، اللمعان، التصفيف والتثبيت
    ٤. إكسسوارات الشعر

Everything here exists because "beauty" was the wrong frame. The discovery gates
accepted any article containing a beauty word, so a mascara launch, a sunscreen
SPF ruling and a gel-manicure trend all entered the corpus as competitive
signals. None of them are: Clara does not sell them, cannot act on them, and a
recommendation drawn from them cannot be validated against anything Clara ships.
A frame that admits everything ranks nothing.

So this module is the single place that answers three questions, and every gate
in the system asks it rather than keeping its own copy:

    which family does this product belong to      family_of()
    is this text about something Clara sells      relevance()
    how should a page group what it shows         FAMILIES, in order

**Out of scope is stated, never silent.** `relevance()` returns a reason, not a
boolean, and the reason names the family the text missed. A dropped signal with
no reason is indistinguishable from a signal that was never fetched, and the
absence rule the audit agent works under (§15) applies just as much here: "we
did not look at makeup" is information, "makeup is irrelevant" asserted with
nothing behind it is not.

**The frame is not a synonym for hair.** Hair loss pharmaceuticals, transplant
clinics, salon franchising and hair colour services are all about hair and none
of them are a product Clara sells. They are refused by name, with the reason
given, because a merely-topical filter would let all four back in.
"""

from __future__ import annotations

import re

# --------------------------------------------------------------------------
# the four families
# --------------------------------------------------------------------------
# Order is the reading order used by every page, and it is deliberate: the
# devices are the business, the care and styling ranges are what a device owner
# buys next, and the accessories are the smallest basket. A page that lists them
# alphabetically buries the first family under the fourth.

FAMILIES = (
    {
        "key": "styling_devices",
        "ar": "أجهزة وأدوات التصفيف",
        "en": "Styling devices and tools",
        "ar_scope": "أجهزة تصفيف الشعر مثل أدوات التصفيف والملحقات",
        "en_scope": "Hair styling devices, styling tools and their attachments",
        # Device attachments live here rather than with the accessories: a
        # diffuser is part of a dryer, and the person deciding about it is
        # deciding about the dryer.
        "categories": ("device", "attachment"),
    },
    {
        "key": "hair_scalp_care",
        "ar": "العناية بالشعر والفروة",
        "en": "Hair and scalp care",
        "ar_scope": "منتجات العناية بالشعر والفروة",
        "en_scope": "Products that wash, treat or nourish hair and scalp",
        "categories": ("shampoo", "conditioner", "mask", "serum", "oil",
                       "scalp", "dry_shampoo"),
    },
    {
        "key": "protect_style",
        "ar": "الحماية والتصفيف والتثبيت",
        "en": "Protection, styling and hold",
        "ar_scope": "منتجات الحماية من الحرارة، الترطيب، اللمعان والتصفيف والتثبيت",
        "en_scope": "Heat protection, hydration, shine, styling and hold",
        "categories": ("heat_protect", "styling_spray", "styling_foam",
                       "styling_wax", "shine"),
    },
    {
        "key": "hair_accessories",
        "ar": "إكسسوارات الشعر",
        "en": "Hair accessories",
        "ar_scope": "إكسسوارات الشعر",
        "en_scope": "Combs, clips, caps, bags and other hair accessories",
        "categories": ("accessory", "bag"),
    },
)

FAMILY_KEYS = tuple(f["key"] for f in FAMILIES)
FAMILY = {f["key"]: f for f in FAMILIES}

# Where an item that is inside the business but outside all four families goes.
# It is a real bucket with a real label, not a silent discard: a product Clara
# sells that no family claims is a gap in this file, and a page that shows it as
# unclassified is what makes that gap visible.
UNCLASSIFIED = {
    "key": "unclassified",
    "ar": "غير مصنّف",
    "en": "Unclassified",
    "ar_scope": "لا تطابق أي عائلة — يحتاج قراراً بشرياً",
    "en_scope": "Matching none of the four families — needs a human decision",
    "categories": (),
}

# Families 2 and 3 overlap in the language brands use: a leave-in conditioner is
# hydration, and hydration is named in family 3. The split is by what the product
# DOES, not by the word: wash-and-treat is care, protect-and-finish is styling.
# Recorded here because the overlap is real and a reader will notice it.
OVERLAP_NOTE = (
    "Hydration appears in both families as brands use it: a mask hydrates in the "
    "shower and a heat protectant hydrates before a dryer. The split is by "
    "function — wash-and-treat products are care, protect-and-finish products "
    "are styling — so a leave-in is care and a heat-protect spray is styling.")


# --------------------------------------------------------------------------
# product -> family
# --------------------------------------------------------------------------
_CATEGORY_FAMILY = {}
for _f in FAMILIES:
    for _c in _f["categories"]:
        _CATEGORY_FAMILY[_c] = _f["key"]

# An accessory that is part of an appliance. Checked against the product NAME,
# because the surrounding copy of a diffuser page is all about the dryer it fits
# and would carry it into the wrong family.
ATTACHMENT_NOUN = re.compile(
    r"\bdiffuser\b|\bbarrel\b|\battachment\b|\bnozzle\b|\bconcentrator\b"
    r"|\bstyling head\b|\bbrush head\b|\bspare (?:filter|head)\b|\bfilter\b"
    r"|ديفيوزر|فوهة|رأس|ملحق|فلتر", re.I)

# Things Clara's catalogue has carried that none of the four families claim.
# Named individually with a reason, because "unclassified" on its own tells a
# reader nothing about whether it is a gap in the frame or genuinely outside it.
OUTSIDE_FRAME = (
    ("perfume", "a fragrance is not a hair product in any of the four families"),
    ("makeup", "makeup is not in the frame"),
    ("skincare", "skincare is not in the frame"),
)


def family_of(segment: str = "", category: str = "", name: str = "") -> str:
    """The family key for a product, or `unclassified`.

    `category` decides it. `name` is consulted for one question only — whether
    an accessory is a device attachment (family 1) or a hair accessory
    (family 4) — because the catalogue's category rules do not separate them and
    a nozzle sitting next to a hair clip makes both cards harder to read.
    """
    category = (category or "").strip().lower()
    segment = (segment or "").strip().lower()

    if category in ("accessory", "bag") and ATTACHMENT_NOUN.search(name or ""):
        return "styling_devices"
    if category in _CATEGORY_FAMILY:
        return _CATEGORY_FAMILY[category]
    # A device whose category the catalogue left as its segment name.
    if segment == "device":
        return "styling_devices"
    if segment == "accessory":
        return ("styling_devices" if ATTACHMENT_NOUN.search(name or "")
                else "hair_accessories")
    return "unclassified"


def family_label(key: str, *, lang: str = "en") -> str:
    """The display name of a family.

    English by default, because every page in this site is written in English and
    a family heading in Arabic beside an English column header reads as a
    rendering fault rather than a choice. The Arabic is kept as data: it is how
    the business states its own catalogue, and `frame_prose(lang="ar")` returns
    it for anyone who needs the original wording.
    """
    f = FAMILY.get(key) or (UNCLASSIFIED if key in ("", "unclassified")
                            else None)
    if not f:
        return key
    return f.get(lang) or f.get("en") or key


def outside_frame_reason(category: str = "", name: str = "") -> str:
    """Why an in-catalogue product sits outside all four families, or ''."""
    blob = f"{category} {name}".lower()
    for term, reason in OUTSIDE_FRAME:
        if term in blob:
            return reason
    return ""


def group_by_family(items, key=None) -> list[tuple[dict, list]]:
    """Items bucketed into the four families, in reading order.

    Returns `(family, items)` pairs and **keeps empty families out** — a page
    with a heading over nothing reads as a section that failed to load. What it
    does not do is drop the unclassified bucket: those are products Clara sells
    that the frame does not describe, and hiding them would hide the gap.
    """
    if key is None:
        def key(item):
            if isinstance(item, dict):
                return family_of(item.get("segment", ""),
                                 item.get("category", ""),
                                 item.get("name", ""))
            return family_of(getattr(item, "segment", ""),
                             getattr(item, "category", ""),
                             getattr(item, "name", ""))
    buckets: dict[str, list] = {k: [] for k in FAMILY_KEYS}
    buckets["unclassified"] = []
    for item in items:
        buckets.setdefault(key(item) or "unclassified", []).append(item)
    out = []
    for k in FAMILY_KEYS:
        if buckets.get(k):
            out.append((FAMILY[k], buckets[k]))
    if buckets.get("unclassified"):
        out.append((UNCLASSIFIED, buckets["unclassified"]))
    for k, items_ in buckets.items():
        if k not in FAMILY_KEYS and k != "unclassified" and items_:
            out.append(({"key": k, "ar": k, "en": k, "ar_scope": "",
                         "en_scope": "", "categories": ()}, items_))
    return out


# --------------------------------------------------------------------------
# text -> is this about something Clara sells?
# --------------------------------------------------------------------------
# Used by the feed gate, the topic gate and the agents. One vocabulary, so a
# subject accepted at ingest cannot be rejected at classification for a reason
# that was never written down.

# Family 1. Device nouns and the styling formats, including competitor model
# names, which share no vocabulary with Clara's own wording.
_DEVICES = (r"\bhair ?dryers?\b|\bblow[- ]?dry\w*\b|\bblow[- ]?outs?\b"
            r"|\bstraighteners?\b|\bflat irons?\b"
            r"|\bcurling (?:iron|wand|tong)\w*\b|\bcurlers?\b"
            r"|\bhair ?stylers?\b|\bmulti[- ]?stylers?\b|\bstyling tools?\b"
            r"|\bhot (?:air )?brush(?:es)?\b|\bair ?brush(?:es)?\b"
            r"|\bblow[- ]?dry brush(?:es)?\b"
            r"|\bthermal brush(?:es)?\b|\bvolumi[sz]ers?\b"
            r"|\bairwrap\b|\bflexstyle\b|\bsupersonic\b|\bairstrait\b"
            r"|\bcorrale\b|\bairglow\b|\bhair tools?\b|\bstyling devices?\b"
            # Bare "dryer" and "styler": a competitor headline says "Shark's new
            # dryer", never "Shark's new hair dryer", so requiring the noun
            # phrase lost most of the coverage that names a rival product. The
            # lookbehinds are the appliances that share the word — a laundry
            # story is not a competitive signal.
            r"|(?<!tumble )(?<!clothes )(?<!spin )(?<!laundry )\bdryer\b"
            r"|(?<!nail )\bstyler\b"
            # A diffuser is a dryer attachment, unless it is the home-fragrance
            # kind, which beauty press covers too.
            r"|(?<!aroma )(?<!reed )(?<!room )\bdiffuser\b"
            # Arabic attaches the definite article to every word of a phrase, so
            # "مجفف شعر" and "مجفف الشعر" are the same noun and only the first
            # was being matched — which is the form that almost never appears in
            # running text. `(?:ال)?` between the words fixes the whole class.
            # Single words need no help: with no word boundary to satisfy,
            # "استشوار" already matches inside "الاستشوار".
            r"|استشوار|مجفف (?:ال)?شعر|مملس|مموج"
            r"|فرشاة (?:ال)?حرارية|فرشاة (?:ال)?هوائية"
            r"|فرشاة (?:ال)?شعر (?:ال)?هوائية"
            r"|أداة (?:ال)?تصفيف|جهاز (?:ال)?تصفيف|مكواة (?:ال)?شعر")

# Family 2. Wash, treat, nourish — and the scalp explicitly, because scalp care
# is named in the frame and is routinely filed under skincare elsewhere.
_CARE = (r"\bshampoos?\b|\bconditioners?\b|\bleave[- ]?ins?\b"
         r"|\bhair masks?\b|\bmasques?\b|\bhair serums?\b|\bhair oils?\b"
         r"|\bscalp\b|\bdry shampoos?\b"
         r"|\bhair treatments?\b|\bbond (?:builder|repair)\w*\b|\bkeratin\b"
         r"|\bhaircare\b|\bhair care\b|\bhair growth\b|\bhair fall\b"
         r"|\bhair loss\b|\bhair density\b|\bhair porosity\b"
         r"|\bhair (?:damage|breakage|split ends)\b|\bdeep condition\w*\b"
         r"|شامبو|بلسم|ماسك (?:ال)?شعر|قناع (?:ال)?شعر|سيروم (?:ال)?شعر|زيت (?:ال)?شعر|فروة"
         r"|العناية بالشعر|تساقط (?:ال)?شعر|كيراتين")

# Family 3. Protect, hydrate, shine, style, hold.
_PROTECT = (r"\bheat protect\w*\b|\bthermal protect\w*\b|\bhairsprays?\b"
            r"|\bhair sprays?\b|\bsetting sprays?\b|\bshine sprays?\b"
            r"|\bmousses?\b|\bstyling (?:cream|foam|gel|wax|paste)s?\b"
            r"|\bpomades?\b|\bhair gels?\b|\bhair wax(?:es)?\b"
            r"|\bcurl creams?\b|\bhair hold\b|\bhold spray\b"
            r"|\banti[- ]?frizz\b|\bhumidity (?:resist|protect)\w*\b"
            r"|\bhair shine\b|\bfrizz control\b"
            r"|واقي (?:ال)?حراري|حماية (?:ال)?حرارية|بخاخ (?:ال)?شعر|مثبت (?:ال)?شعر|رغوة (?:ال)?شعر"
            r"|واكس (?:ال)?شعر|جل (?:ال)?شعر|كريم (?:ال)?تصفيف|لمعان|ترطيب (?:ال)?شعر")

# Family 4.
_ACCESSORY = (r"\bhair (?:clip|clips|combs?|brush(?:es)?|bands?|ties?"
              r"|pins?|claws?|clamps?|rollers?|rods?)\b"
              r"|\bscrunchies?\b|\bheadbands?\b|\bhair accessor\w*\b"
              r"|\bwide[- ]tooth combs?\b|\bdetangl\w+ brush(?:es)?\b"
              r"|\bbonnets?\b|\bshower caps?\b|\bhair towels?\b"
              r"|\btool (?:bag|pouch|case)s?\b"
              # Heatless styling is a product family here, not a technique: the
              # things sold for it are bands, rods and curling ribbons.
              r"|\bheatless (?:styl|curl)\w*\b|\bcurl(?:ing)? ribbons?\b"
              r"|مشط|فرشاة (?:ال)?شعر|بنس|ربطة (?:ال)?شعر|طوق (?:ال)?شعر|إكسسوارات (?:ال)?شعر"
              r"|اكسسوارات (?:ال)?شعر|حقيبة (?:ال)?أدوات|بكرات (?:ال)?شعر")

FAMILY_PATTERN = {
    "styling_devices": re.compile(_DEVICES, re.I),
    "hair_scalp_care": re.compile(_CARE, re.I),
    "protect_style": re.compile(_PROTECT, re.I),
    "hair_accessories": re.compile(_ACCESSORY, re.I),
}

IN_SCOPE = re.compile("|".join((_DEVICES, _CARE, _PROTECT, _ACCESSORY)), re.I)

# Hair-adjacent, and outside the frame all the same. Every one of these is about
# hair, which is exactly why a topical filter is not enough: Clara sells none of
# them and cannot act on any of them.
ADJACENT = (
    (re.compile(r"\bminoxidil\b|\bfinasteride\b|\bdutasteride\b"
                r"|\bhair (?:transplant|restoration surgery)\b|\bfue\b"
                r"|\bprp (?:therapy|treatment)\b|\bdermatolog\w+ prescri\w+\b"
                r"|مينوكسيديل|زراعة (?:ال)?شعر", re.I),
     "a pharmaceutical or clinical hair treatment, not a product Clara sells"),
    (re.compile(r"\bhair (?:colour|color|dye|bleach|toner|highlights)\b"
                r"|\bhair colo(?:u)?rant\b|\bpermanent (?:wave|colour|color)\b"
                r"|\brelaxer\b|\bkeratin treatment (?:salon|service)\b"
                r"|صبغة|صبغات|سحب (?:ال)?لون", re.I),
     "hair colour is a category Clara does not sell"),
    (re.compile(r"\bsalon (?:franchise|chain|booking|software|appointment)\w*\b"
                r"|\bbarbershop\b|\bstylist (?:hiring|training|certification)\b"
                r"|\bhair (?:extension|extensions|wig|wigs|weave|toupee)\b"
                r"|\bhaircuts?\b|\bhair (?:cutting|trim)\b"
                r"|باروكة|وصلات (?:ال)?شعر|حجز (?:ال)?صالون|قص (?:ال)?شعر", re.I),
     "a service or category outside the four product families"),
    # Clara's catalogue contains a Hair Perfume, and none of the four families
    # names fragrance. Refused here rather than folded into family 3, so the
    # text gate and the catalogue agree: the product shows on the products page
    # as unclassified with this same reason, which is a decision waiting for a
    # person rather than a silent widening of the frame.
    (re.compile(r"\bhair (?:perfume|fragrance|mist|mists)\b"
                r"|\bfragrance for hair\b|عطر (?:ال)?شعر|بخاخ (?:ال)?عطر", re.I),
     "hair fragrance is not one of the four families — Clara's Hair Perfume is "
     "unclassified for the same reason, pending a decision"),
)

# Beauty, and nothing to do with hair. These were the false positives that made
# the old frame useless.
NON_HAIR_BEAUTY = re.compile(
    r"\bmascara\b|\blipstick\b|\blip gloss\b|\bblush\b|\bbronzer\b"
    r"|\bconcealer\b|\bfoundation (?:shade|stick|match)\w*\b|\beyeliner\b"
    r"|\beyeshadow\b|\bmakeup\b|\bsunscreen\b|\bspf\b|\bretinol\b"
    r"|\bniacinamide\b|\bhyaluronic\b|\bmoisturi[sz]er\b|\bcleanser\b"
    r"|\bskincare\b|\bskin care\b|\bserum for (?:skin|face)\b|\bfacial\b"
    r"|\bmanicure\b|\bpedicure\b|\bnail (?:polish|art|salon)\b|\bgel nails\b"
    r"|\bbody (?:lotion|wash|scrub)\b|\bdeodorant\b|\bshower gel\b"
    r"|\beau de (?:parfum|toilette)\b|\bfragrance (?:launch|house|note)\w*\b"
    r"|مكياج|أحمر (?:ال)?شفاه|ماسكارا|واقي (?:ال)?شمس|بشرة|مانيكير|أظافر|عطور", re.I)

# Cross-domain collisions: a beauty word that means something else somewhere
# else. Refused outright, not scored — no amount of corroboration makes a
# foundation model relevant to a hair dryer.
COLLISION = re.compile(
    r"\b(?:foundation|language|diffusion|base|reward|world|embodied)\s+model"
    r"|\bmodel\s+(?:training|weights|inference|checkpoint)"
    r"|\bfoundation\s+(?:models|layer|stone|repair fund)"
    r"|\bserum\s+(?:antibod|immunoglob|albumin)"
    r"|\bmask\s+(?:r-?cnn|token)|\bdiffusion\s+(?:model|transformer)"
    r"|\bopen[- ]?source|\brobotic|\bhumanoid|\bsemiconductor|\bdatacent"
    r"|\bfoundry\b|\bchipset\b|\bllm\b|\bgpu\b", re.I)

# Context that keeps a general term inside the frame. "Retail" and "pricing" are
# not hair words, but a retail story about a dryer is in scope, and the device
# pattern above will have caught it — these are for stories where the product is
# implied by the brand rather than named.
BRAND_IN_FRAME = re.compile(
    r"\bdyson\b|\bshark (?:beauty|flexstyle|style)\w*\b|\bghd\b|\bbabyliss\b"
    r"|\bremington\b|\bt3 micro\b|\brevlon (?:one[- ]step|salon)\b"
    r"|\bolaplex\b|\bk[eé]rastase\b|\bmoroccanoil\b|\bouai\b|\bamika\b"
    r"|\bbriogeo\b|\bliving proof\b|\btymo\b|\blaifen\b|\bclara ?hair\b"
    r"|\bwahl\b|\bhot tools\b|\bdrybar\b", re.I)


_SEPARATOR = re.compile(r"[-_/+]+")


def _normalise(text: str) -> str:
    """Slug separators become spaces before anything is matched.

    Half of what this module reads is a URL. `/collections/hair-dryers` is the
    clearest statement a page makes about what it sells, and none of the patterns
    below would match it with the hyphen in place — writing every term twice, once
    hyphenated, is the alternative and it would rot on the first term someone
    forgot. Doing it here also fixes the lookbehinds for free: "tumble-dryer"
    becomes "tumble dryer" and is excluded exactly as the spaced form is.
    """
    return _SEPARATOR.sub(" ", text or "")


def relevance(text: str) -> dict:
    """Is this text about something inside the frame? With the reason.

    Returns `{verdict, reason, families}` where verdict is one of:

        in_scope        a family's vocabulary is present
        out_of_scope    it is about beauty, or hair, but not a Clara product
        unclear         nothing either way — kept, and reported as unread

    `unclear` is not a rejection. A headline of four words may name nothing at
    all, and treating silence as a refusal quietly loses the signals worth
    reading. It is the caller's decision what to do with an unclear item; what
    this function guarantees is that the decision is made against a written
    reason rather than a boolean nobody can argue with.
    """
    blob = _normalise(text)
    if not blob.strip():
        return {"verdict": "unclear", "reason": "no text to judge",
                "families": []}

    if COLLISION.search(blob):
        return {"verdict": "out_of_scope",
                "reason": "a known cross-domain collision — the phrase belongs "
                          "to another field and shares a word with beauty",
                "families": []}

    families = [k for k, rx in FAMILY_PATTERN.items() if rx.search(blob)]
    if families:
        return {"verdict": "in_scope",
                "reason": "names " + " and ".join(
                    family_label(k, lang="en").lower() for k in families),
                "families": families}

    for rx, reason in ADJACENT:
        if rx.search(blob):
            return {"verdict": "out_of_scope", "reason": reason,
                    "families": []}

    if BRAND_IN_FRAME.search(blob):
        return {"verdict": "in_scope",
                "reason": "names a brand that competes inside the frame, though "
                          "no product family is named",
                "families": []}

    if NON_HAIR_BEAUTY.search(blob):
        return {"verdict": "out_of_scope",
                "reason": "beauty, but not hair — none of the four families "
                          "covers it",
                "families": []}

    return {"verdict": "unclear",
            "reason": "no product family and no excluded category recognised",
            "families": []}


def in_frame(text: str) -> bool:
    """Convenience for the gates that only need the verdict.

    `unclear` counts as out: a gate that admits everything it cannot read is the
    generic-beauty gate this module replaced. Callers that want to keep unclear
    items should use `relevance()` and say so.
    """
    return relevance(text)["verdict"] == "in_scope"


# The share of a cluster that must be in frame before it can become a subject.
# One in-frame article in a cluster of ten is a coincidence, not a subject.
MIN_FRAME_SHARE = 0.60


def frame_share(texts) -> float:
    """Share of the given texts that are inside the frame."""
    texts = list(texts)
    if not texts:
        return 0.0
    return sum(1 for t in texts if in_frame(t)) / len(texts)


# --------------------------------------------------------------------------
# trend subjects -> where they sit relative to the frame
# --------------------------------------------------------------------------
# The trend vocabulary was written for beauty, so most of its 86 subjects are not
# about a Clara product. Sorting them needs a third answer, because two of the
# bands are genuinely useful and only one is noise:
#
#   family   the subject IS one of the four families
#   lens     a commercial pattern that applies TO the families — pricing,
#            dupes, retail expansion, social commerce. Not a product category,
#            and in frame when read against a Clara product. Kept separate
#            because a lens with no product attached is a market observation
#            with nothing to act on.
#   out      about beauty, or hair, and not about anything Clara sells
#
# Collapsing lens into family would put "pricing moves" beside "hair dryers" as
# though they were the same kind of thing. Collapsing it into out would throw
# away the pricing intelligence the whole system was built to produce.

LENS_TOPICS = {
    "price_promotion": "how the frame is priced and discounted",
    "dupe_culture": "cheaper alternatives to in-frame products",
    "affordable_beauty": "value positioning against in-frame products",
    "luxury_beauty": "premium positioning against in-frame products",
    "retail_expansion": "where in-frame products are sold",
    "beauty_retail": "where in-frame products are sold",
    "social_commerce": "how in-frame products are sold and discovered",
    "social_commerce_beauty": "how in-frame products are sold and discovered",
    "refill_sustainability": "packaging and refills for in-frame products",
    "sustainability_beauty": "packaging and refills for in-frame products",
    "genz_beauty": "who buys in-frame products",
    "mena_beauty": "the regional market for in-frame products",
    "african_beauty": "hair types the frame has to serve",
    "textured_hair": "hair types the frame has to serve",
    "protective_styles": "hair routines the frame has to serve",
    "viral_hairstyles": "styling outcomes in-frame products are bought for",
    "halal_beauty": "claims in-frame products are asked to make",
    "clean_beauty": "claims in-frame products are asked to make",
    "clean_beauty_claims": "claims in-frame products are asked to make",
    "ingredient_actives": "claims in-frame products are asked to make",
    # These three read as families because their patterns mention haircare, but
    # each is an audience or a market rather than a product category.
    "korean_beauty": "a market whose haircare formats reach the frame",
    "mens_beauty": "an audience the frame has to serve",
    "mens_grooming": "an audience the frame has to serve",
}

# Subjects whose label names no product but which are squarely one family.
TOPIC_FAMILY_OVERRIDE = {
    "device_beauty_tech": "styling_devices",
    "smart_mirrors": "",       # a connected mirror is not a Clara product
    "hair_tools": "styling_devices",
    "blowout_styles": "styling_devices",
    "heatless_styling": "hair_accessories",
    "scalp_care": "hair_scalp_care",
    "hair_growth": "hair_scalp_care",
    "hair_oils": "hair_scalp_care",
    "hair_treatments": "hair_scalp_care",
    "bond_repair": "hair_scalp_care",
    "heat_protection": "protect_style",
}


def topic_frame(key: str = "", label: str = "", pattern: str = "",
                clara_relevance: str = "") -> dict:
    """Where a trend subject sits: `{band, family, reason}`.

    `band` is family, lens or out. The overrides are consulted first because a
    subject's label is a name, not a description — "Beauty devices and tech" is
    the styling-devices family and says so nowhere in its own words.
    """
    if key in TOPIC_FAMILY_OVERRIDE:
        fam = TOPIC_FAMILY_OVERRIDE[key]
        if fam:
            return {"band": "family", "family": fam,
                    "reason": f"assigned to {family_label(fam, lang='en')}"}
        return {"band": "out", "family": "",
                "reason": "not a product in any of the four families"}

    if key in LENS_TOPICS:
        return {"band": "lens", "family": "",
                "reason": LENS_TOPICS[key]}

    verdict = relevance(f"{label} {pattern}")
    if verdict["verdict"] == "in_scope" and verdict["families"]:
        return {"band": "family", "family": verdict["families"][0],
                "reason": verdict["reason"]}
    if verdict["verdict"] == "in_scope":
        return {"band": "lens", "family": "", "reason": verdict["reason"]}
    return {"band": "out", "family": "", "reason": verdict["reason"]}


# --------------------------------------------------------------------------
# the frame, as prose, for the agents and the pages
# --------------------------------------------------------------------------
def frame_lines(*, lang: str = "ar") -> list[str]:
    """The four families as numbered lines, for a page or a prompt."""
    if lang == "ar":
        return [f"{i}. {f['ar']} — {f['ar_scope']}"
                for i, f in enumerate(FAMILIES, 1)]
    return [f"{i}. {f['en']} — {f['en_scope']}"
            for i, f in enumerate(FAMILIES, 1)]


def frame_prose(*, lang: str = "en") -> str:
    """One paragraph naming the frame and what falls outside it."""
    lines = "\n".join(f"    {ln}" for ln in frame_lines(lang=lang))
    if lang == "ar":
        return ("الإطار — كل بحث وكل توصية داخل هذه العائلات الأربع فقط:\n\n"
                f"{lines}\n\n"
                "خارج الإطار: المكياج، العناية بالبشرة، الأظافر، العطور، "
                "صبغات الشعر، خدمات الصالون، الوصلات والباروكات، وأدوية "
                "تساقط الشعر. ما يخرج من الإطار يُذكر سببه ولا يُحذف بصمت.")
    return ("THE FRAME — every search, every comparison and every "
            "recommendation sits inside these four families and nowhere else:\n\n"
            f"{lines}\n\n"
            "Outside the frame: makeup, skincare, nails, fragrance, hair "
            "colour, salon services, extensions and wigs, and hair-loss "
            "pharmaceuticals. Hair-adjacent is not in-frame — Clara sells none "
            "of those and no recommendation drawn from them can be validated "
            "against anything Clara ships. Anything refused is refused with its "
            "reason recorded, never dropped silently.")
