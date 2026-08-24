"""The product frame: the four families, and everything they exclude.

    ١. أجهزة تصفيف الشعر — أدوات التصفيف والملحقات
    ٢. منتجات العناية بالشعر والفروة
    ٣. الحماية من الحرارة، الترطيب، اللمعان، التصفيف والتثبيت
    ٤. إكسسوارات الشعر

This file exists because the frame it replaced was "beauty", and every gate in
the system asked that question. Mascara launches, SPF rulings and gel-manicure
trends all entered the record as competitive signals — properly about beauty,
and about nothing Clara sells or can act on.

Three things are pinned here, and the third is the one that actually bites.

**The families claim what they should.** Both languages, singular and plural. A
vocabulary that matches "hair oil" and misses "hair oils" silently loses half its
coverage, and every one of those was a real defect in the first draft.

**Hair-adjacent is not in-frame.** Hair colour, wigs, transplants, salon
services, haircuts. All about hair; none of them a product in the catalogue. A
merely-topical filter lets all five back in, which is why they are refused by
name with the reason recorded.

**A refusal carries a reason.** `relevance` returns a verdict and a sentence, not
a boolean, and `unclear` is a third answer rather than a quiet no. A gate that
drops a signal without a reason is indistinguishable from a gate that never
fetched it.

    python tests/test_scope.py
"""
from __future__ import annotations

import io
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
_kept_stdout = sys.stdout
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8",
                              errors="replace")

from clara_monitor import scope  # noqa: E402

PASS, FAIL = [], []

# The business states its catalogue in Arabic; the pages render English. Both
# are pinned, because dropping the Arabic would lose the original wording and
# rendering it would put it on an English page.
FAMILY_AR = {f["key"]: f["ar"] for f in scope.FAMILIES}


def ok(cond, label):
    (PASS if cond else FAIL).append(label)
    print(f"  {'PASS' if cond else 'FAIL'}  {label}")


def section(title):
    print(f"\n{title}")


def verdict(text):
    return scope.relevance(text)["verdict"]


def fams(text):
    return set(scope.relevance(text)["families"])


# ------------------------------------------------------------------ shape
section("The four families")

ok(len(scope.FAMILIES) == 4, "four families, no more and no fewer")
ok([f["key"] for f in scope.FAMILIES] == [
    "styling_devices", "hair_scalp_care", "protect_style", "hair_accessories"],
   "in the order the business states them, devices first")
ok(all(f.get("ar") and f.get("en") and f.get("ar_scope")
       for f in scope.FAMILIES),
   "each family is named in Arabic and English, with its scope written out")
ok(len({c for f in scope.FAMILIES for c in f["categories"]})
   == sum(len(f["categories"]) for f in scope.FAMILIES),
   "no category is claimed by two families")
ok(scope.family_label("styling_devices") == "Styling devices and tools",
   "labels default to English — every page here is written in English, and an "
   "Arabic heading beside an English column reads as a fault, not a choice")
ok(scope.family_label("styling_devices", lang="ar")
   == FAMILY_AR["styling_devices"],
   "the business's own Arabic wording is kept as data and still available")
ok(scope.family_label("styling_devices", lang="en")
   == "Styling devices and tools", "and English is available")
ok(scope.family_label("nonsense") == "nonsense",
   "an unknown key is echoed rather than raising")
ok(scope.family_label("unclassified") == "Unclassified",
   "the unclassified bucket has a real label, not a blank")

# ------------------------------------------------------------------ products
section("Products land in the right family")

CASES = [
    ("device", "device", "Multi-Use Hair Dryer", "styling_devices"),
    ("device", "device", "Hair Straightener Pro", "styling_devices"),
    ("haircare", "shampoo", "Repair Shampoo", "hair_scalp_care"),
    ("haircare", "conditioner", "Leave-in Conditioner", "hair_scalp_care"),
    ("haircare", "mask", "Deep Hair Mask", "hair_scalp_care"),
    ("haircare", "scalp", "Scalp Scrub", "hair_scalp_care"),
    ("haircare", "oil", "Argan Hair Oil", "hair_scalp_care"),
    ("haircare", "heat_protect", "Heat Protection Spray", "protect_style"),
    ("haircare", "styling_spray", "Flexible Hairspray", "protect_style"),
    ("haircare", "styling_foam", "Volume Mousse", "protect_style"),
    ("haircare", "styling_wax", "Gloss Balm", "protect_style"),
    ("accessory", "accessory", "Wide-tooth Comb", "hair_accessories"),
    ("accessory", "bag", "Styling Tool Bag", "hair_accessories"),
]
for seg, cat, name, want in CASES:
    got = scope.family_of(seg, cat, name)
    ok(got == want, f"{name} -> {scope.family_label(want, lang='en')}"
                    + ("" if got == want else f" (got {got})"))

# The split the catalogue's own rules do not make.
ok(scope.family_of("accessory", "accessory", "Diffuser Attachment")
   == "styling_devices",
   "a diffuser is part of a dryer, so it sits with the devices")
ok(scope.family_of("accessory", "accessory", "Replacement Filter")
   == "styling_devices", "so does a spare filter")
ok(scope.family_of("accessory", "accessory", "Hair Clips Set")
   == "hair_accessories", "and a hair clip stays an accessory")
ok(scope.family_of("accessory", "bag", "Nozzle and Concentrator Set")
   == "styling_devices",
   "an attachment in a bag is still an attachment")

ok(scope.family_of("haircare", "perfume", "Hair Perfume") == "unclassified",
   "fragrance matches no family, so it is unclassified rather than forced")
ok(bool(scope.outside_frame_reason("perfume", "Hair Perfume")),
   "and the reason it is unclassified is stated")
ok(scope.family_of("", "", "") == "unclassified",
   "an empty product is unclassified, not a crash")
ok(scope.family_of("device", "", "Some Dryer") == "styling_devices",
   "a device with no category still resolves from its segment")

# ------------------------------------------------------------------ grouping
section("Grouping for a page")

items = [
    {"segment": "device", "category": "device", "name": "Dryer"},
    {"segment": "haircare", "category": "shampoo", "name": "Shampoo"},
    {"segment": "accessory", "category": "accessory", "name": "Comb"},
    {"segment": "haircare", "category": "perfume", "name": "Hair Perfume"},
]
groups = scope.group_by_family(items)
keys = [f["key"] for f, _ in groups]
ok(keys == ["styling_devices", "hair_scalp_care", "hair_accessories",
            "unclassified"],
   "families come out in reading order, empty ones omitted")
ok("protect_style" not in keys,
   "a family with nothing in it gets no heading — an empty heading reads as a "
   "section that failed to load")
ok(keys[-1] == "unclassified",
   "the unclassified bucket is last but never dropped: it is the visible gap")
ok(sum(len(v) for _, v in groups) == len(items),
   "every item is placed exactly once")
ok(scope.group_by_family([]) == [], "nothing in, nothing out")

# ------------------------------------------------------------------ text
section("Text inside the frame")

IN = [
    ("Dyson launches a quieter hair dryer", "styling_devices"),
    ("Shark dryer review", "styling_devices"),
    ("Revlon styler launch", "styling_devices"),
    ("Best styling tools of 2026", "styling_devices"),
    ("A new diffuser attachment", "styling_devices"),
    ("Blowout at home", "styling_devices"),
    ("Bond repair shampoos tested", "hair_scalp_care"),
    ("Hair oils for dry ends", "hair_scalp_care"),
    ("Scalp care is the new skincare", "hair_scalp_care"),
    ("Hair treatments that actually repair", "hair_scalp_care"),
    ("Heat protectant sprays compared", "protect_style"),
    ("Anti-frizz serum for humidity", "protect_style"),
    ("Setting sprays that hold a curl", "protect_style"),
    ("Wide-tooth combs and detangling brushes", "hair_accessories"),
    ("Heatless curling ribbons go viral", "hair_accessories"),
    ("استشوار جديد من كلارا", "styling_devices"),
    ("شامبو للفروة الحساسة", "hair_scalp_care"),
    ("أفضل واقي حراري للشعر", "protect_style"),
    ("مشط خشبي لفك التشابك", "hair_accessories"),
]
for text, want in IN:
    r = scope.relevance(text)
    ok(r["verdict"] == "in_scope" and want in r["families"],
       f"in frame ({scope.family_label(want, lang='en')}): {text}")

# Plurals. Every one of these was a real miss in the first draft: the pattern
# said "hair oil" and the headline said "hair oils".
for text in ("Hair oils", "Hair masks", "Hair serums", "Styling tools",
             "Hair dryers", "Straighteners", "Curlers", "Flat irons",
             "Hairsprays", "Mousses", "Hair treatments", "Scrunchies",
             "Headbands", "Hot brushes", "Air brushes", "Hair combs"):
    ok(verdict(text) == "in_scope", f"plural matches: {text}")

ok(fams("A heat protectant for use with a straightener")
   == {"styling_devices", "protect_style"},
   "a text naming two families reports both")

# Arabic attaches the definite article to every word of a phrase, so the bare
# form these patterns were written in is the form that almost never appears in
# running text. Nine of ten of these failed before the patterns allowed for it.
AR_FORMS = [
    ("مجفف الشعر الجديد", "styling_devices"),
    ("جهاز التصفيف", "styling_devices"),
    ("ماسك الشعر المغذي", "hair_scalp_care"),
    ("زيت الشعر", "hair_scalp_care"),
    ("الواقي الحراري للشعر", "protect_style"),
    ("بخاخ الشعر المثبت", "protect_style"),
    ("كريم التصفيف", "protect_style"),
    ("ربطة الشعر", "hair_accessories"),
    ("فرشاة الشعر الخشبية", "hair_accessories"),
]
for text, want in AR_FORMS:
    r = scope.relevance(text)
    ok(r["verdict"] == "in_scope" and want in r["families"],
       f"the definite article does not defeat the pattern: {text}")

AR_OUT = ["صبغة الشعر",
          "قص الشعر",
          "زراعة الشعر",
          "عطر الشعر",
          "واقي الشمس",
          "أحمر الشفاه"]
for text in AR_OUT:
    ok(verdict(text) == "out_of_scope",
       f"and it does not defeat an exclusion either: {text}")

# The bundle that was filed as a serum: the device noun in its name carried the
# article on both words, so it missed, and the spray in the same name won.
from clara_monitor import catalog as _cat  # noqa: E402

BUNDLE = ("الفرشاة الحرارية "
          "الثنائية و بخاخ "
          "الحماية و سيروم "
          "اللمعان")
ok(bool(_cat.DEVICE_NOUN.search(BUNDLE)),
   "a thermal brush written with the article is recognised as a device")
ok(_cat.classify_category(BUNDLE)[0] == "device",
   "so the bundle is a device, not the serum that shares its name")
ok(scope.family_of(*_cat.classify_category(BUNDLE), BUNDLE) == "styling_devices",
   "and it lands in the styling family on the page")

# ------------------------------------------------------------------ excluded
section("Beauty, and not hair")

for text in ("New mascara from Huda Beauty", "Gel manicure trend",
             "Sunscreen SPF ruling", "Retinol explained",
             "Lipstick shades for autumn", "Body lotion launch",
             "Eau de parfum release", "Nail art for short nails",
             "ماسكارا جديدة", "مانيكير جل"):
    r = scope.relevance(text)
    ok(r["verdict"] == "out_of_scope", f"refused: {text}")
    ok(bool(r["reason"]), f"  ...with a reason: {r['reason'][:44]}")

section("Hair-adjacent, and still not in frame")

ADJACENT = [
    ("A new permanent hair colour range", "colour"),
    ("Minoxidil regrowth study", "pharmaceutical"),
    ("Hair transplant clinic opens", "pharmaceutical"),
    ("Hair extensions and wigs retailer expands", "service"),
    ("Salon franchise booking software", "service"),
    ("Haircuts and shapes for spring", "service"),
    ("صبغة شعر جديدة", "colour"),
    ("باروكة شعر طبيعي", "service"),
]
for text, kind in ADJACENT:
    r = scope.relevance(text)
    ok(r["verdict"] == "out_of_scope",
       f"refused ({kind}): {text}")
ok("colour" in scope.relevance("A new hair dye range")["reason"],
   "the refusal names the excluded category rather than saying 'off domain'")

# The catalogue and the text gate must agree about fragrance, or the products
# page shows a Hair Perfume as unclassified while a hair-mist article is
# accepted as in frame.
ok(verdict("Hair perfume and mists") == "out_of_scope",
   "hair fragrance is out of frame in text, as it is in the catalogue")
ok("unclassified" in scope.relevance("hair mist launch")["reason"],
   "and the reason points at the same pending decision")

section("Cross-domain collisions")

for text in ("Xiaomi open-sources an embodied-AI foundation model",
             "Diffusion model checkpoint released", "GPU supply and datacentres",
             "Serum immunoglobulin assay"):
    ok(verdict(text) == "out_of_scope", f"collision refused: {text}")
ok("collision" in scope.relevance("foundation model training")["reason"],
   "and it is called a collision, not a category")

section("Unclear is a third answer")

ok(verdict("A short headline") == "unclear",
   "text naming nothing either way is unclear, not refused")
ok(verdict("") == "unclear", "empty text is unclear")
ok(verdict("Tumble dryer recall") == "unclear",
   "a laundry appliance is not a styling device")
ok(verdict("clothes dryer energy label") == "unclear", "nor is a clothes dryer")
ok(verdict("Reed diffuser launch") == "unclear",
   "nor is a home-fragrance diffuser")
ok(scope.in_frame("Hair dryer review") is True, "in_frame is true for in frame")
ok(scope.in_frame("A short headline") is False,
   "and false for unclear — a gate that admits what it cannot read is the "
   "generic gate this replaced")

# ------------------------------------------------------------------ share
section("Cluster share")

ok(scope.frame_share([]) == 0.0, "no texts, no share")
ok(scope.frame_share(["Hair dryer news", "Shampoo launch"]) == 1.0,
   "all in frame is 1.0")
ok(scope.frame_share(["Hair dryer news", "Mascara launch"]) == 0.5,
   "half in frame is 0.5")
ok(0 < scope.MIN_FRAME_SHARE <= 1, "the threshold is a share, not a count")

# ------------------------------------------------------------------ topics
section("Trend subjects: family, lens or out")

ok(scope.topic_frame("hair_tools", "Hair styling tools")["band"] == "family",
   "a product subject is a family")
ok(scope.topic_frame("hair_tools", "Hair styling tools")["family"]
   == "styling_devices", "and names which one")
ok(scope.topic_frame("price_promotion", "Pricing and promotion moves")["band"]
   == "lens",
   "pricing is a lens: it applies to the families without being one")
ok(scope.topic_frame("nail_art", "Nail art")["band"] == "out",
   "nail art is out")
ok(scope.topic_frame("device_beauty_tech", "Beauty devices and tech")["band"]
   == "family",
   "a subject whose label names no product can still be assigned by key")
ok(scope.topic_frame("smart_mirrors", "Smart mirrors")["band"] == "out",
   "a connected mirror is a device and not a Clara product")
ok(scope.topic_frame("korean_beauty", "K-beauty")["band"] == "lens",
   "a market is a lens, not a family, even when its pattern says haircare")
ok(all(scope.topic_frame(k, k)["band"] == "lens" for k in scope.LENS_TOPICS),
   "every named lens resolves as a lens")
ok(all(scope.topic_frame("", lbl)["band"] == "family"
       for lbl in ("Hair dryers", "Shampoo", "Heat protection", "Hair combs")),
   "an unnamed subject is still judged on its label")
ok(scope.topic_frame("", "")["band"] == "out",
   "a subject with nothing to judge is out, not a family")
for k, fam in scope.TOPIC_FAMILY_OVERRIDE.items():
    if fam:
        ok(fam in scope.FAMILY_KEYS, f"override {k} names a real family")

# ------------------------------------------------------------------ prose
section("The frame as prose")

ar = scope.frame_prose(lang="ar")
en = scope.frame_prose(lang="en")
ok(len(scope.frame_lines()) == 4, "four numbered lines")
ok(all(f["ar"] in ar for f in scope.FAMILIES),
   "the Arabic prose names all four families")
ok(all(f["en"] in en for f in scope.FAMILIES),
   "so does the English")
ok("makeup" in en and "hair colour" in en,
   "and both state what is outside, including the adjacent categories")
ok("مكياج" in ar, "in Arabic too")
ok(bool(scope.OVERLAP_NOTE) and "hydrat" in scope.OVERLAP_NOTE.lower(),
   "the families-2-and-3 overlap is written down rather than left to be noticed")

# the agent contracts must carry the same frame
contracts = list((ROOT / "prompts" / "agents").glob("*.md"))
ok(len(contracts) >= 10, f"{len(contracts)} agent contracts found")
missing = [c.name for c in contracts
           if "PRODUCT FRAME" not in c.read_text(encoding="utf-8")]
ok(not missing, f"every agent contract states the frame{
    '' if not missing else ': missing ' + ', '.join(missing)}")
one = contracts[0].read_text(encoding="utf-8")
ok(all(f["en"] in one for f in scope.FAMILIES),
   "naming all four families")
ok(not any(0x600 <= ord(ch) <= 0x6FF for c in contracts
           for ch in c.read_text(encoding="utf-8")),
   "and in English throughout — these are English specifications, and the four "
   "families read identically in one language")
ok("hair-adjacent" in one.lower(),
   "and warns about the hair-adjacent trap specifically")

print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
for f in FAIL:
    print(f"  FAILED  {f}")
sys.exit(1 if FAIL else 0)
