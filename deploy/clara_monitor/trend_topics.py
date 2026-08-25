"""The subject vocabulary the collector reads with.

Twenty topics covered hair tools and haircare, which is what Clara sells. That
is too narrow to answer "what is happening in beauty" — a trend that starts in
nails or fragrance and crosses into hair is invisible until it has already
crossed. This widens the vocabulary to the whole category so the collector can
see a subject arrive before it reaches Clara's shelf.

**This file is a reading aid, not data.** Every entry is a pattern that decides
which real article counts as evidence for which subject. Not one number, date or
claim originates here. If a topic below has no evidence, it does not appear on
the page at all — an empty pattern produces an empty subject, not an assertion
that the subject is quiet.

Seven areas, matching how the market actually talks about itself:

    makeup      skincare    hair      nails
    fragrance   beauty_tech beauty_culture

`relevance` is Clara's stake in the subject, and it is deliberately honest:
`direct` is what Clara sells, `adjacent` is the same buyer or the same basket,
and `context` is the wider market that sets expectations. Most of the vocabulary
below is `context`, because most of beauty is not hair tools — and a trend report
that pretended otherwise would be a worse instrument for spotting a crossover.
"""

from __future__ import annotations

# key, label, category, subcategory, pattern, why it matters, relevance, tags
SPEC: list[tuple] = [

    # ---------------------------------------------------------------- makeup
    ("skin_tints", "Skin tints and skin-first base", "makeup", "base",
     r"\bskin tint\b|\bserum foundation\b|\bskin[- ]?first\b|\btinted serum\b",
     "The base category moved from coverage to skin-finish, which is the same "
     "shift that turned haircare from styling to health.", "context",
     ["Base", "Lightweight", "Gen Z"]),
    ("foundation", "Foundation formulas", "makeup", "base",
     r"\bfoundation\b(?!\s*(?:model|year))|\bfull coverage\b|\bmatte base\b",
     "The largest makeup category by spend; formula shifts here move the whole "
     "aisle.", "context", ["Base", "Mass market"]),
    ("concealer", "Concealer", "makeup", "base",
     r"\bconcealer\b|\bunder[- ]eye\b.{0,18}\b(?:brighten|cover)\b",
     "Highest repeat-purchase item in makeup and a reliable entry price point.",
     "context", ["Base", "Repeat purchase"]),
    ("blush", "Blush and flush", "makeup", "colour",
     r"\bblush\b|\bcream blush\b|\bliquid blush\b|\bflushed\b.{0,14}\bcheek",
     "The colour category that has grown fastest through short video, because "
     "the before-and-after is instant.", "context", ["Colour", "Viral format"]),
    ("bronzer_contour", "Bronzer and contour", "makeup", "colour",
     r"\bbronzer\b|\bcontour\b|\bsculpt\w*\b.{0,12}\bface\b|\bbronzing\b",
     "Technique-led, which means it sells tools and brushes alongside product.",
     "context", ["Colour", "Technique-led"]),
    ("highlighter", "Highlighter and glow", "makeup", "colour",
     r"\bhighlighter\b|\bstrobing\b|\bglow drops\b|\bliquid glow\b",
     "The finish that defines an aesthetic era; it flips between dewy and matte "
     "faster than any other category.", "context", ["Colour", "Finish"]),
    ("lip_products", "Lip oils, glosses and stains", "makeup", "lips",
     r"\blip oil\b|\blip gloss\b|\blip stain\b|\blip liner\b|\blip balm\b"
     r"|\bplumping\b.{0,10}\blip",
     "The cheapest way into a trend, so it is where a new aesthetic shows up "
     "first.", "context", ["Lips", "Entry price"]),
    ("eye_makeup", "Eye makeup", "makeup", "eyes",
     r"\beyeliner\b|\beyeshadow\b|\bmascara\b|\blash(?:es)? \b|\bsmokey eye\b"
     r"|\bgraphic liner\b",
     "The most technique-dependent category, and therefore the most tutorial "
     "driven.", "context", ["Eyes", "Tutorial"]),
    ("brows", "Brows", "makeup", "eyes",
     r"\bbrow lamination\b|\beyebrow\b|\bbrow gel\b|\blaminated brows\b"
     r"|\bfluffy brows\b",
     "Brow shape dates a look faster than anything else on the face.",
     "context", ["Eyes", "Service-led"]),
    ("makeup_technique", "Makeup techniques", "makeup", "technique",
     r"\bunderpainting\b|\bdraping\b|\bbaking\b.{0,10}\bmakeup\b|\bcolour theory\b"
     r"|\bmakeup hack\b|\bapplication technique\b",
     "A technique spreads faster than a product and needs no supply chain, so "
     "it is the earliest visible signal of a shift.", "context",
     ["Technique", "Early signal"]),
    ("makeup_aesthetic", "Makeup aesthetics", "makeup", "aesthetic",
     r"\bclean girl\b|\blatte makeup\b|\bmob wife\b|\bcoquette\b|\bdouyin makeup\b"
     r"|\bstrawberry makeup\b|\btomato girl\b|\bespresso makeup\b|\bsoft glam\b",
     "Aesthetics are the packaging a whole basket is sold in — they move "
     "categories together rather than one at a time.", "context",
     ["Aesthetic", "Cross-category"]),
    ("colour_trend", "Colour of the season", "makeup", "colour",
     r"\bcolou?r of the year\b|\bpantone\b|\bseasonal shade\b"
     r"|\bshade of the season\b",
     "Colour calls are announced in advance, which makes them the rare trend "
     "with a publication date attached.", "context", ["Colour", "Seasonal"]),
    ("no_makeup", "No-makeup and minimal", "makeup", "aesthetic",
     r"\bno[- ]makeup\b|\bminimal makeup\b|\bbare[- ]faced\b|\bskinimalism\b"
     r"|\bless is more\b.{0,14}\bbeauty\b",
     "Every minimalist wave moves money out of colour and into skincare and "
     "tools — including hair tools.", "adjacent", ["Aesthetic", "Minimal"]),
    ("celebrity_look", "Celebrity-led looks", "makeup", "aesthetic",
     r"\bcelebrity\b.{0,20}\b(?:look|makeup|hair)\b|\bred carpet\b"
     r"|\bmet gala\b|\bgot the look\b",
     "A named person compresses a trend cycle from months to days.",
     "context", ["Celebrity", "Fast cycle"]),

    # -------------------------------------------------------------- skincare
    ("ingredient_actives", "Actives and ingredient claims", "skincare",
     "ingredient",
     r"\bretinol\b|\bretinal\b|\bniacinamide\b|\bsalicylic\b|\bglycolic\b"
     r"|\bazelaic\b|\btranexamic\b|\bvitamin c\b|\bpeptide[s]?\b|\bceramide[s]?\b",
     "Ingredient literacy is the strongest buying driver in skincare and it is "
     "spreading into haircare claims.", "adjacent",
     ["Ingredients", "High intent"]),
    ("exosomes_pdrn", "Exosomes, PDRN and next-gen actives", "skincare",
     "ingredient",
     r"\bexosome[s]?\b|\bpdrn\b|\bpolynucleotide[s]?\b|\bgrowth factor[s]?\b"
     r"|\bstem cell\b.{0,12}\bskin\b",
     "Clinic ingredients moving to retail — the pattern that produced retinol "
     "and then bond repair.", "context", ["Ingredients", "Clinic to shelf"]),
    ("snail_fermented", "Snail mucin, ferments and K-actives", "skincare",
     "ingredient",
     r"\bsnail mucin\b|\bferment(?:ed|ation)\b.{0,14}\bskin\b|\bgalactomyces\b"
     r"|\bbee venom\b|\bcentella\b|\bcica\b",
     "Korean ingredient stories cross into the Gulf faster than Korean brands "
     "do.", "context", ["Ingredients", "K-beauty"]),
    ("serums", "Serums", "skincare", "format",
     r"\bserum\b(?!\s*foundation)|\bampoule\b|\bessence\b",
     "The highest-margin skincare format and the one Clara's haircare range "
     "most resembles.", "adjacent", ["Format", "Margin"]),
    ("moisturizers", "Moisturisers and barrier creams", "skincare", "format",
     r"\bmoisturi[sz]er\b|\bface cream\b|\bbarrier cream\b|\brich cream\b",
     "The volume base of skincare; formula shifts here signal where the "
     "category's centre of gravity sits.", "context", ["Format", "Volume"]),
    ("sunscreen", "Sunscreen", "skincare", "format",
     r"\bsunscreen\b|\bspf\b|\buv filter\b|\bsun care\b|\bsuncare\b",
     "The fastest-growing skincare subcategory globally and a year-round "
     "purchase in the Gulf.", "context", ["Format", "Fast growing"]),
    ("cleansers", "Cleansers and cleansing routines", "skincare", "format",
     r"\bcleanser\b|\bdouble cleans\w+\b|\boil cleans\w+\b|\bcleansing balm\b"
     r"|\bmicellar\b",
     "Routine steps are how a category adds units without adding buyers.",
     "context", ["Format", "Routine"]),
    ("masks", "Masks and treatments", "skincare", "format",
     r"\bsheet mask\b|\bface mask\b|\bovernight mask\b|\bclay mask\b"
     r"|\bpeel[- ]off\b",
     "The category that converts a trend into a low-cost trial.", "context",
     ["Format", "Trial"]),
    ("acne_care", "Acne and blemish care", "skincare", "concern",
     r"\bacne\b|\bblemish\b|\bbreakout\b|\bpimple patch\b|\bspot treatment\b"
     r"|\bfungal acne\b",
     "The highest-intent skincare concern and the least price-sensitive.",
     "context", ["Concern", "High intent"]),
    ("anti_aging", "Anti-ageing and longevity skin", "skincare", "concern",
     r"\banti[- ]ag\w+\b|\bfine lines\b|\bwrinkle\b|\bfirming\b|\bcollagen\b"
     r"|\bskin longevity\b",
     "Where the pricing power is, and increasingly framed as health rather "
     "than cosmetics.", "adjacent", ["Concern", "Premium"]),
    ("skin_barrier", "Skin barrier", "skincare", "concern",
     r"\bskin barrier\b|\bbarrier repair\b|\bover[- ]exfoliat\w+\b"
     r"|\bcompromised skin\b|\bmoisture barrier\b",
     "The correction to a decade of actives, and the same argument bond repair "
     "makes in hair.", "adjacent", ["Concern", "Correction"]),
    ("korean_skincare", "Korean skincare", "skincare", "regional",
     r"\bk[- ]beauty\b|\bkorean skincare\b|\bglass skin\b|\b10[- ]step\b"
     r"|\bolive young\b",
     "Sets the vocabulary the Gulf adopts six to twelve months later.",
     "context", ["Regional", "Leading indicator"]),
    ("japanese_skincare", "Japanese skincare", "skincare", "regional",
     r"\bj[- ]beauty\b|\bjapanese skincare\b|\bmochi skin\b|\bshiseido\b"
     r"|\bhada labo\b",
     "The minimalist counterweight to Korean maximalism; drives format "
     "simplification.", "context", ["Regional", "Minimal"]),
    ("dermatology", "Dermatology and clinical trends", "skincare", "clinical",
     r"\bderm(?:atologist)?[- ]approved\b|\bskin cycling\b|\bslugging\b"
     r"|\bmicroneedling\b|\bchemical peel\b|\bclinical trial\b.{0,14}\bskin\b",
     "Clinic language is the credibility currency of the whole category.",
     "context", ["Clinical", "Credibility"]),
    ("injectables", "Injectables and tweakments", "skincare", "clinical",
     r"\bbotox\b|\bfiller[s]?\b|\bbaby botox\b|\btweakment\b|\bskin booster\b"
     r"|\bprofhilo\b",
     "Normalising injectables resets what topical products are expected to "
     "achieve.", "context", ["Clinical", "Normalising"]),
    ("home_skin_devices", "At-home skincare devices", "skincare", "device",
     r"\bled mask\b|\bmicrocurrent\b|\bred light therapy\b|\bat[- ]home device\b"
     r"|\bradiofrequency\b|\bcryo\w*\b.{0,10}\bface\b",
     "Directly adjacent to Clara: the same buyer, the same price band, the same "
     "at-home promise.", "adjacent", ["Devices", "Same buyer"]),

    # ------------------------------------------------------------------ hair
    ("haircuts", "Haircuts and shapes", "hair", "cut",
     r"\bbob\b(?!\s*(?:dylan|marley))|\bcurtain bangs\b|\bwolf cut\b"
     r"|\bbutterfly cut\b|\bshag\b|\bblunt cut\b|\bpixie\b|\blayers\b",
     "A cut decides which styling tool a person needs next.", "direct",
     ["Cut", "Drives tools"]),
    ("hair_colour", "Hair colour", "hair", "colour",
     r"\bbalayage\b|\bmoney piece\b|\bcopper hair\b|\bbrunette\b"
     r"|\bhair colou?r\b|\bhighlights\b|\btoner\b|\bgloss(?:ing)?\b.{0,10}\bhair",
     "Colour damages hair, which is what creates the repair and protection "
     "purchase.", "direct", ["Colour", "Drives repair"]),
    ("heatless_styling", "Heatless styling", "hair", "technique",
     r"\bheatless curl\w*\b|\bovernight curl\w*\b|\bno[- ]heat\b.{0,12}\bhair\b"
     r"|\bhair rollers?\b|\bsilk wrap\b",
     "The direct argument against Clara's core product, and the objection its "
     "pages have to answer.", "direct", ["Technique", "Counter-trend"]),
    ("hair_treatments", "Hair treatments and repair", "hair", "treatment",
     r"\bbond (?:repair|builder)\b|\bkeratin treatment\b|\bhair botox\b"
     r"|\bprotein treatment\b|\bhair gloss\b|\bolaplex\b|\bk18\b",
     "The counter-argument to heat styling, and a category Clara already sells "
     "into.", "direct", ["Treatment", "Objection"]),
    ("hair_oils", "Hair oils", "hair", "treatment",
     r"\bhair oil\b|\bargan oil\b|\brosemary oil\b|\bscalp oil\b|\bhair serum\b"
     r"|\bvatika\b",
     "The default haircare purchase across the Middle East by volume.",
     "direct", ["Treatment", "Gulf volume"]),
    ("protective_styles", "Protective styles", "hair", "technique",
     r"\bprotective style\w*\b|\bbraids?\b|\btwists?\b|\bwig\b|\bweave\b"
     r"|\bsew[- ]in\b|\bsilk press\b",
     "A large segment with its own tool needs that Clara's range does not "
     "address at all.", "direct", ["Technique", "Under-served"]),
    ("viral_hairstyles", "Viral hairstyles", "hair", "style",
     r"\bslick(?:ed)? back\b|\bclaw clip\b|\bbubble braid\b|\bheadband\b"
     r"|\bhalf up\b|\bhair bow\b|\bbouncy blow\w*\b",
     "The look a buyer is trying to reproduce when they pick a tool.",
     "direct", ["Style", "Purchase trigger"]),

    # ----------------------------------------------------------------- nails
    ("nail_colour", "Nail colour", "nails", "colour",
     r"\bnail colou?r\b|\bnail polish\b|\bmani(?:cure)?\b.{0,14}\bshade\b"
     r"|\bred nails\b|\bmilky nails\b|\bchocolate nails\b",
     "Nail colour turns over faster than any other beauty category, which "
     "makes it an early read on where a palette is going.", "context",
     ["Colour", "Fast cycle"]),
    ("nail_shape", "Nail shapes", "nails", "shape",
     r"\balmond nails\b|\bsquoval\b|\bcoffin nails\b|\bballerina nails\b"
     r"|\bshort nails\b|\bnail shape\b",
     "Shape is a slower cycle than colour and marks a real aesthetic change.",
     "context", ["Shape", "Slow cycle"]),
    ("nail_art", "Nail art", "nails", "art",
     r"\bnail art\b|\bchrome nails\b|\baura nails\b|\bfrench (?:tip|manicure)\b"
     r"|\bcat eye nails\b|\bglazed (?:donut )?nails\b",
     "The most screenshot-driven beauty category and a reliable aesthetic "
     "leading indicator.", "context", ["Art", "Visual"]),
    ("nails_diy", "Press-ons and DIY nails", "nails", "diy",
     r"\bpress[- ]on nails\b|\bgel[- ]?x\b|\bat[- ]home (?:mani|gel)\w*\b"
     r"|\bnail kit\b|\bdip powder\b",
     "The same at-home substitution that built Clara's category, running in "
     "nails.", "adjacent", ["DIY", "Same pattern"]),
    ("nails_luxury", "Luxury and salon nails", "nails", "luxury",
     r"\bluxury (?:nails|manicure)\b|\bnail salon\b|\bnail artist\b"
     r"|\bcouture nails\b",
     "The premium end that sets what at-home kits are measured against.",
     "context", ["Luxury", "Benchmark"]),

    # ------------------------------------------------------------- fragrance
    ("fragrance_trends", "Fragrance trends", "fragrance", "trend",
     r"\bfragrance\b|\bperfume\b|\beau de parfum\b|\bfrag\w*\b.{0,10}\blaunch\b",
     "The fastest-growing beauty category by value worldwide and the strongest "
     "single category in the Gulf.", "adjacent", ["Category", "Gulf strength"]),
    ("perfume_layering", "Perfume layering", "fragrance", "technique",
     r"\blayering\b.{0,14}\b(?:fragrance|perfume|scent)\b|\bscent layering\b"
     r"|\bfragrance wardrobe\b",
     "A technique that multiplies units per buyer without a new product.",
     "context", ["Technique", "Units per buyer"]),
    ("body_mists", "Body mists and hair mists", "fragrance", "format",
     r"\bbody mist\b|\bhair mist\b|\bbody spray\b|\bscented mist\b",
     "The cheapest fragrance entry point, and hair mist is a format Clara "
     "could sell tomorrow.", "direct", ["Format", "Adjacent product"]),
    ("fragrance_dupes", "Fragrance dupes and alternatives", "fragrance",
     "behaviour",
     r"\bdupe\b.{0,16}\b(?:fragrance|perfume|scent)\b|\bsmells like\b"
     r"|\baffordable alternative\b.{0,14}\bperfume\b|\binspired by\b.{0,12}\bscent",
     "The value argument, running in the category where brand premium is "
     "highest.", "adjacent", ["Behaviour", "Value"]),
    ("fragrance_notes", "Fragrance ingredients and notes", "fragrance",
     "ingredient",
     r"\bambroxan\b|\boud\b|\bgourmand\b|\bvanilla\b.{0,12}\b(?:note|scent)\b"
     r"|\bmusk\b|\bpistachio\b.{0,12}\bscent\b|\bsaffron\b.{0,12}\bperfume\b",
     "Note-led buying is how fragrance became searchable, and oud makes it "
     "regionally specific.", "context", ["Ingredients", "Searchable"]),
    ("celebrity_fragrance", "Celebrity and brand fragrance", "fragrance",
     "brand",
     r"\bcelebrity fragrance\b|\bfragrance launch\b|\bsigns?\b.{0,16}\bfragrance deal\b"
     r"|\bfragrance line\b",
     "Launch-driven, so it is the fragrance signal with an actual date.",
     "context", ["Brand", "Dated"]),

    # ---------------------------------------------------------- beauty tech
    ("ai_beauty", "AI beauty tools", "beauty_tech", "ai",
     r"\bai\b.{0,16}\bbeauty\b|\bai skin analysis\b|\bai[- ]powered\b.{0,16}\bskin\b"
     r"|\bbeauty ai\b|\balgorithm\w*\b.{0,14}\bbeauty\b",
     "Changes how a product is chosen, which is upstream of what is bought.",
     "adjacent", ["AI", "Upstream"]),
    ("skin_analysis", "Skin and hair analysis tech", "beauty_tech", "analysis",
     r"\bskin analysis\b|\bskin diagnos\w+\b|\bhair analysis\b"
     r"|\bscalp scanner\b|\bskin scan\b|\btrichoscop\w+\b",
     "A diagnostic front-end turns a one-off purchase into a routine.",
     "adjacent", ["Analysis", "Routine"]),
    ("virtual_tryon", "Virtual try-on and AR", "beauty_tech", "ar",
     r"\bvirtual try[- ]?on\b|\bar\b.{0,14}\b(?:beauty|makeup)\b"
     r"|\btry[- ]?on\b.{0,12}\bfilter\b|\bsnap\w*\b.{0,10}\btry[- ]?on\b",
     "Removes the main objection to buying colour and tools online.",
     "adjacent", ["AR", "Conversion"]),
    ("smart_mirrors", "Smart mirrors and connected devices", "beauty_tech",
     "device",
     r"\bsmart mirror\b|\bconnected (?:device|beauty)\b|\bbluetooth\b.{0,14}\bbeauty\b"
     r"|\bapp[- ]connected\b.{0,14}\b(?:device|tool)\b",
     "Where a hair tool stops being an appliance and becomes a platform.",
     "adjacent", ["Devices", "Platform"]),
    ("personalisation", "Personalised beauty", "beauty_tech", "personalisation",
     r"\bpersonalis\w+\b.{0,14}\bbeauty\b|\bpersonaliz\w+\b.{0,14}\bbeauty\b"
     r"|\bcustom(?:ised|ized)\b.{0,14}\b(?:formula|routine|shade)\b"
     r"|\bbespoke\b.{0,12}\bbeauty\b",
     "The commercial argument for collecting data at all.", "adjacent",
     ["Personalisation", "Data"]),
    ("beauty_apps", "Beauty apps and platforms", "beauty_tech", "app",
     r"\bbeauty app\b|\bskincare app\b|\brouting app\b|\bbeauty platform\b"
     r"|\bshade finder\b",
     "Where discovery happens before a retailer is ever opened.", "context",
     ["Apps", "Discovery"]),

    # ------------------------------------------------------- beauty culture
    ("clean_girl", "Clean girl and quiet luxury", "beauty_culture", "aesthetic",
     r"\bclean girl\b|\bquiet luxury\b|\bold money\b.{0,12}\baesthetic\b"
     r"|\beffortless\b.{0,14}\bbeauty\b|\bthat girl\b",
     "The aesthetic that made slick-back hair and a glossy finish default, "
     "which is directly Clara's territory.", "direct",
     ["Aesthetic", "Hair-relevant"]),
    ("genz_beauty", "Gen Z beauty behaviour", "beauty_culture", "audience",
     r"\bgen z\b.{0,16}\bbeauty\b|\byoung(?:er)? consumers?\b.{0,16}\bbeauty\b"
     r"|\bteen\b.{0,12}\bskincare\b|\bsephora kids\b",
     "Sets the discovery channel and the price expectation for everything "
     "else.", "adjacent", ["Audience", "Discovery"]),
    ("mens_beauty", "Men's beauty and grooming", "beauty_culture", "audience",
     r"\bmen'?s (?:beauty|grooming|skincare)\b|\bmale grooming\b"
     r"|\bmen'?s haircare\b|\bbeard care\b",
     "An under-served buyer in the Gulf with no Clara product aimed at them.",
     "adjacent", ["Audience", "Under-served"]),
    ("luxury_beauty", "Luxury beauty", "beauty_culture", "tier",
     r"\bluxury beauty\b|\bprestige beauty\b|\bhigh[- ]end\b.{0,14}\bbeauty\b"
     r"|\bpremiumisation\b",
     "Sets the ceiling Clara is priced against.", "adjacent",
     ["Tier", "Ceiling"]),
    ("affordable_beauty", "Affordable beauty and dupes", "beauty_culture",
     "tier",
     r"\bdupe\b|\baffordable beauty\b|\bdrugstore\b|\bbudget beauty\b"
     r"|\bvalue for money\b.{0,14}\bbeauty\b|\bcheaper alternative\b",
     "Clara's entire commercial position, running as a cultural movement.",
     "direct", ["Tier", "Clara's position"]),
    ("mena_beauty", "MENA beauty", "beauty_culture", "regional",
     r"\bmiddle east\w*\b.{0,16}\bbeauty\b|\bgcc\b.{0,14}\bbeauty\b"
     r"|\bsaudi\b.{0,16}\b(?:beauty|market)\b|\bgulf\b.{0,14}\bbeauty\b"
     r"|\bmena\b.{0,12}\bbeauty\b|\bhalal beauty\b|\bmodest beauty\b",
     "Clara's home market. Anything here is first-order, not context.",
     "direct", ["Regional", "Home market"]),
    ("african_beauty", "African and textured beauty", "beauty_culture",
     "regional",
     r"\bafrican beauty\b|\btextured hair\b|\bcurly hair\b|\bcoily\b|\b4c hair\b"
     r"|\bnigeria\b.{0,14}\bbeauty\b|\bafro\b",
     "The fastest-growing haircare segment globally and one Clara says nothing "
     "about.", "direct", ["Regional", "Gap"]),
    ("beauty_retail", "Beauty retail and distribution", "beauty_culture",
     "channel",
     r"\bsephora\b|\bulta\b|\bnykaa\b|\bboots\b|\bdouglas\b|\bharrods\b"
     r"|\bbeauty retail\w*\b|\bstockist\b|\bshelf space\b|\bopens? (?:its )?first store\b",
     "Where a rival appears next decides who Clara is compared against.",
     "adjacent", ["Channel", "Shelf"]),
    ("social_commerce_beauty", "Social commerce", "beauty_culture", "channel",
     r"\btiktok shop\b|\bsocial commerce\b|\blive\w*\s*(?:stream)?\s*shopping\b"
     r"|\bcreator[- ]led\b|\bshoppable\b|\binfluencer\b.{0,14}\bsales?\b",
     "Where a beauty product is now discovered and bought in one motion.",
     "adjacent", ["Channel", "Discovery"]),
    ("sustainability_beauty", "Sustainability and refills",
     "beauty_culture", "values",
     r"\brefill\w*\b|\bsustainab\w+\b.{0,14}\bbeauty\b|\brecyclab\w+\b"
     r"|\bpackaging waste\b|\bcircular\b.{0,12}\bbeauty\b|\bwaterless\b",
     "Regulatory in Europe, reputational elsewhere, cheap to act on for "
     "consumables.", "adjacent", ["Values", "Regulatory"]),
    ("clean_beauty_claims", "Clean beauty and transparency",
     "beauty_culture", "values",
     r"\bclean beauty\b|\bingredient transparency\b|\bsulfate[- ]free\b"
     r"|\bparaben[- ]free\b|\bnon[- ]toxic\b|\bfragrance[- ]free\b",
     "A claim Clara can make cheaply on consumables and cannot fake.",
     "adjacent", ["Values", "Claim"]),
    ("wellness_beauty", "Wellness and ingestible beauty", "beauty_culture",
     "values",
     r"\bingestible\b|\bbeauty supplement\b|\bcollagen\b.{0,12}\bdrink\b"
     r"|\bwellness\b.{0,14}\bbeauty\b|\bgut[- ]skin\b|\blongevity\b",
     "Reframes beauty as health, which is where the pricing power moves.",
     "context", ["Values", "Pricing power"]),
]


def build(topic_cls) -> list:
    """Turn the spec into Topic objects.

    Takes the class rather than importing it, so this module stays free of a
    circular import back into `trend_sources`.
    """
    out = []
    for (key, label, category, subcategory, pattern, why, relevance,
         tags) in SPEC:
        t = topic_cls(key=key, label=label, category=category, pattern=pattern,
                      why_it_matters=why, clara_relevance=relevance,
                      tags=list(tags))
        t.subcategory = subcategory
        out.append(t)
    return out


AREA_LABEL = {
    "makeup": "Makeup",
    "skincare": "Skincare",
    "hair": "Hair",
    "nails": "Nails",
    "fragrance": "Fragrance",
    "beauty_tech": "Beauty tech",
    "beauty_culture": "Beauty culture",
}
AREA_ICON = {
    "makeup": "💄", "skincare": "🧴", "hair": "💇", "nails": "💅",
    "fragrance": "🌸", "beauty_tech": "🤖", "beauty_culture": "🌍",
}
