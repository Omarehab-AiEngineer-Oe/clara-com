"""Where live trend evidence comes from, and the vocabulary used to read it.

The trends page used to be a curated file. This is what replaces it: a registry of
sources the Agent fetches itself on every scan, plus the topic vocabulary it
matches against what comes back.

**Why feeds.** A publisher that ships RSS is explicitly inviting automated
reading, which is the exact opposite of a login-walled platform. That makes feeds
the one surface where continuous collection is both technically possible and
clearly permitted, so it is the surface this uses. Every fetch still goes through
`access.guarded_get`: robots checked, one honest user agent, no credentials, and a
refusal recorded as a refusal.

**Two kinds of source, and they prove different things.**

* `search_demand` — Google Trends publishes its rising queries per country as RSS.
  This is the closest thing to real consumer demand available without a login: it
  is what people typed, not what an editor decided to write about. Filtered to
  beauty-relevant queries, because the feed covers everything.
* `trade_press` / `consumer_press` — what the industry and its readers are being
  told. Slower than search, but it carries the *why*, and a topic that appears
  across several unconnected publishers is corroborated in a way a single article
  is not.

**What is deliberately absent.** No source here needs an account, and none is
scraped against its terms. Publishers that refused during probing are listed in
`REFUSED`, and feeds that returned 404 or HTML are listed in `DEAD` — a
publisher saying no and a feed that no longer exists are different facts, and
both belong on the page rather than quietly dropped.

Scope is the six markets the operator named: Middle East, China, South Korea,
UK, US and Global. Korea is the thinnest — four Korean press feeds were probed
and all four failed — so Korean coverage is search demand plus one trade
outlet, and the page states that gap.

The topic vocabulary below is a *reading aid*, not data. It decides which real
article counts as evidence for which subject. Every fact on the trends page is a
headline a named publisher actually published, with its own URL and date.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from urllib.parse import urlsplit

# The six markets in scope. Deliberately not thirteen: the operator named these
# six, and a page covering markets nobody asked about spreads its evidence thin
# while answering a question nobody had.
ME, CN, KR, UK, US, GLOBAL = "ME", "CN", "KR", "UK", "US", "GLOBAL"

MARKET_LABEL = {
    ME: "Middle East",
    CN: "China",
    KR: "South Korea",
    UK: "United Kingdom",
    US: "United States",
    GLOBAL: "Global",
}
# Clara's own market first, then the markets whose trends reach it, then global.
MARKET_ORDER = [ME, KR, CN, UK, US, GLOBAL]
MARKETS = set(MARKET_ORDER)

SEARCH_DEMAND = "search_demand"
TRADE_PRESS = "trade_press"
CONSUMER_PRESS = "consumer_press"
RETAIL_PRESS = "retail_press"


@dataclass
class Source:
    key: str
    publisher: str
    url: str
    kind: str
    market: str
    weight: int = 2          # evidence weight, as in contracts.SOURCE_TIER_WEIGHT
    note: str = ""

    @property
    def host(self) -> str:
        return (urlsplit(self.url).hostname or "").lower()


# --------------------------------------------------------------------------
# the registry — every one of these answered during probing
# --------------------------------------------------------------------------

SOURCES: list[Source] = [
    # --- search demand, per market -----------------------------------------
    # What people typed, which is the closest thing to real consumer demand
    # available without a login.
    Source("gt_sa", "Google Trends — Saudi Arabia",
           "https://trends.google.com/trending/rss?geo=SA", SEARCH_DEMAND, ME, 3,
           "rising searches in Clara's home market"),
    Source("gt_ae", "Google Trends — United Arab Emirates",
           "https://trends.google.com/trending/rss?geo=AE", SEARCH_DEMAND, ME, 3),
    Source("gt_eg", "Google Trends — Egypt",
           "https://trends.google.com/trending/rss?geo=EG", SEARCH_DEMAND, ME, 3),
    Source("gt_kw", "Google Trends — Kuwait",
           "https://trends.google.com/trending/rss?geo=KW", SEARCH_DEMAND, ME, 3),
    Source("gt_kr", "Google Trends — South Korea",
           "https://trends.google.com/trending/rss?geo=KR", SEARCH_DEMAND, KR, 3),
    Source("gt_hk", "Google Trends — Hong Kong",
           "https://trends.google.com/trending/rss?geo=HK", SEARCH_DEMAND, CN, 3,
           "Hong Kong stands in for Chinese-language demand; Google is not "
           "available on the mainland and no substitute is implied"),
    Source("gt_tw", "Google Trends — Taiwan",
           "https://trends.google.com/trending/rss?geo=TW", SEARCH_DEMAND, CN, 3,
           "second Chinese-language reading, for corroboration"),
    Source("gt_gb", "Google Trends — United Kingdom",
           "https://trends.google.com/trending/rss?geo=GB", SEARCH_DEMAND, UK, 3),
    Source("gt_us", "Google Trends — United States",
           "https://trends.google.com/trending/rss?geo=US", SEARCH_DEMAND, US, 3),

    # --- Middle East --------------------------------------------------------
    Source("cosmome", "Cosmopolitan Middle East",
           "https://www.cosmopolitanme.com/rss", CONSUMER_PRESS, ME, 2),
    Source("emirateswoman", "Emirates Woman",
           "https://emirateswoman.com/feed/", CONSUMER_PRESS, ME, 2),
    Source("bazaararabia", "Harper's Bazaar Arabia",
           "https://www.harpersbazaararabia.com/rss", CONSUMER_PRESS, ME, 2),
    Source("imagesretailme", "Images Retail ME",
           "https://www.imagesretailme.com/feed/", RETAIL_PRESS, ME, 2,
           "Gulf retail trade press — where a brand opens, and with whom"),
    Source("saudigazette", "Saudi Gazette",
           "https://saudigazette.com.sa/rssFeed/74", CONSUMER_PRESS, ME, 2),

    # --- China --------------------------------------------------------------
    Source("technode", "TechNode", "https://technode.com/feed/",
           TRADE_PRESS, CN, 2, "Chinese tech and commerce, incl. beauty retail"),
    Source("scmp", "South China Morning Post",
           "https://www.scmp.com/rss/5/feed", CONSUMER_PRESS, CN, 2),
    Source("pandaily", "Pandaily", "https://pandaily.com/feed/", TRADE_PRESS, CN, 2),
    Source("chinadaily", "China Daily",
           "http://www.chinadaily.com.cn/rss/lifestyle_rss.xml",
           CONSUMER_PRESS, CN, 2),

    # --- South Korea --------------------------------------------------------
    # The thinnest of the six. Four Korean press feeds were probed and all four
    # returned 404 or HTML, so this is Google Trends plus one trade outlet. The
    # page states the gap rather than implying a full sweep.
    Source("koreatech", "KoreaTechDesk", "https://koreatechdesk.com/feed/",
           TRADE_PRESS, KR, 1),

    # --- United Kingdom -----------------------------------------------------
    Source("dazed", "Dazed", "https://www.dazeddigital.com/rss",
           CONSUMER_PRESS, UK, 2),
    Source("retailgazette", "Retail Gazette",
           "https://www.retailgazette.co.uk/feed/", RETAIL_PRESS, UK, 2),
    Source("stylist", "Stylist", "https://www.stylist.co.uk/feed",
           CONSUMER_PRESS, UK, 2),

    # --- United States ------------------------------------------------------
    Source("beautyindependent", "Beauty Independent",
           "https://www.beautyindependent.com/feed/", TRADE_PRESS, US, 2),
    Source("glossy", "Glossy", "https://www.glossy.co/feed/", TRADE_PRESS, US, 2),
    Source("allure", "Allure", "https://www.allure.com/feed/rss",
           CONSUMER_PRESS, US, 2),
    Source("retaildive", "Retail Dive",
           "https://www.retaildive.com/feeds/news/", RETAIL_PRESS, US, 2),
    Source("modernretail", "Modern Retail",
           "https://www.modernretail.co/feed/", RETAIL_PRESS, US, 2),
    Source("popsugar", "PopSugar Beauty",
           "https://www.popsugar.com/beauty/feed", CONSUMER_PRESS, US, 2),
    Source("nytstyle", "The New York Times — Style",
           "https://rss.nytimes.com/services/xml/rss/nyt/FashionandStyle.xml",
           CONSUMER_PRESS, US, 2),

    # --- Global -------------------------------------------------------------
    Source("premiumbeauty", "Premium Beauty News",
           "https://www.premiumbeautynews.com/spip.php?page=backend",
           TRADE_PRESS, GLOBAL, 2),
    Source("wwd", "WWD", "https://wwd.com/feed/", TRADE_PRESS, GLOBAL, 2),
    Source("bof", "The Business of Fashion",
           "https://www.businessoffashion.com/feed/", TRADE_PRESS, GLOBAL, 2),
    Source("vogue", "Vogue", "https://www.vogue.com/feed/rss",
           CONSUMER_PRESS, GLOBAL, 2),
    Source("elle", "Elle", "https://www.elle.com/rss/beauty.xml/",
           CONSUMER_PRESS, GLOBAL, 2),
    Source("bazaar", "Harper's Bazaar",
           "https://www.harpersbazaar.com/rss/all.xml/", CONSUMER_PRESS,
           GLOBAL, 2),
]

# Feeds that no longer exist. A 404 or a 410 is the publisher saying the feed is
# gone, which is a different fact from a refusal and is reported as its own thing.
DEAD = [
    ("Cosmetics Business", "https://www.cosmeticsbusiness.com/rss/news", "HTTP 404"),
    ("Cosmetics Design Europe",
     "https://www.cosmeticsdesign-europe.com/Info/RSS", "HTTP 410"),
    ("Cosmetics Design USA", "https://www.cosmeticsdesign.com/Info/RSS", "HTTP 410"),
    ("Gulf News lifestyle", "https://gulfnews.com/rss", "HTTP 404"),
    ("Zawya", "https://www.zawya.com/en/rss", "HTTP 404"),
    ("Trade Arabia retail", "http://www.tradearabia.com/rss/RETAIL.xml", "HTTP 404"),
    ("Korea Herald", "http://www.koreaherald.com/common/rss_xml.php?ct=105",
     "returns HTML, not a feed"),
    ("Korea JoongAng Daily",
     "https://koreajoongangdaily.joins.com/xmls/joins.xml", "HTTP 404"),
    ("Chosun English", "https://english.chosun.com/rss/", "HTTP 404"),
    ("Korea Times", "https://www.koreatimes.co.kr/www/rss/culture.xml", "HTTP 404"),
    ("The Grocer", "https://www.thegrocer.co.uk/latest-news/rss", "HTTP 404"),
    ("Marie Claire", "https://www.marieclaire.com/feed/all.rss/", "HTTP 404"),
    ("Sixth Tone", "https://www.sixthtone.com/rss", "returns HTML, not a feed"),
]

# Publishers that refused automated access during probing. Kept visible so the
# page can state what it could not read rather than implying a full sweep.
REFUSED = [
    ("Byrdie", "https://www.byrdie.com/rss", "http_forbidden"),
    ("Happi", "https://www.happi.com/rss/", "http_forbidden"),
    ("Arab News", "https://www.arabnews.com/rss.xml", "http_forbidden"),
    ("Arabian Business", "https://www.arabianbusiness.com/feed", "http_forbidden"),
    ("BeautyMatter", "https://beautymatter.com/rss.xml", "transport_error"),
    ("Vogue Business", "https://www.voguebusiness.com/feed/rss", "transport_error"),
    ("Jing Daily", "https://jingdaily.com/feed/", "rate_limited"),
    ("Beauty Packaging", "https://www.beautypackaging.com/rss/", "http_forbidden"),
    ("Global Cosmetic Industry", "https://www.gcimagazine.com/rss",
     "http_forbidden"),
    ("Chain Store Age", "https://chainstoreage.com/rss.xml", "http_forbidden"),
    ("Fashion Network", "https://ww.fashionnetwork.com/rss/news.xml",
     "http_forbidden"),
    ("Perfumer & Flavorist", "https://www.perfumerflavorist.com/rss",
     "http_forbidden"),
    ("Drapers", "https://www.drapersonline.com/feed", "paywall"),
    ("Refinery29", "https://www.refinery29.com/en-us/rss.xml", "paywall"),
    ("Refinery29 UK", "https://www.refinery29.com/en-gb/rss.xml", "paywall"),
    ("Reddit r/HaircareScience", "https://www.reddit.com/r/HaircareScience/.rss",
     "robots_disallowed"),
    ("Reddit r/beauty", "https://www.reddit.com/r/beauty/.rss",
     "robots_disallowed"),
]


# Hosts belonging to sources the discovery loop activated. The access gate
# refuses anything not on the allowlist, so an activated source that is not
# listed here is a source that can never actually be read.
DYNAMIC_HOSTS: set = set()


def register_dynamic_hosts(hosts) -> int:
    DYNAMIC_HOSTS.clear()
    for h in hosts or []:
        if not h:
            continue
        h = h.lower()
        DYNAMIC_HOSTS.add(h)
        DYNAMIC_HOSTS.add(h[4:] if h.startswith("www.") else "www." + h)
    return len(DYNAMIC_HOSTS)


def allowed_hosts() -> set[str]:
    """The allowlist for a trend scan. Nothing outside it is fetchable."""
    hosts: set[str] = set(DYNAMIC_HOSTS)
    for s in SOURCES:
        h = s.host
        if not h:
            continue
        hosts.add(h)
        hosts.add(h[4:] if h.startswith("www.") else "www." + h)
    return hosts


# --------------------------------------------------------------------------
# topic vocabulary — a reading aid, not data
# --------------------------------------------------------------------------

DEVICE = "device"
INGREDIENT = "ingredient"
TECHNIQUE = "technique"
BEHAVIOUR = "behaviour"
CHANNEL = "channel"
CATEGORY = "category"


# One glyph per category, for scanning a grid rather than reading it.
CATEGORY_ICON = {
    "makeup": "💄", "skincare": "🧴", "hair": "💇", "nails": "💅",
    "fragrance": "🌸", "beauty_tech": "🤖", "beauty_culture": "🌍",
    "device": "🔧",
    "ingredient": "🧪",
    "technique": "✨",
    "behaviour": "👥",
    "channel": "🛒",
    "category": "📦",
}
CATEGORY_LABEL = {
    "makeup": "Makeup", "skincare": "Skincare", "hair": "Hair",
    "nails": "Nails", "fragrance": "Fragrance",
    "beauty_tech": "Beauty tech", "beauty_culture": "Beauty culture",
    "device": "Devices",
    "ingredient": "Ingredients",
    "technique": "Techniques",
    "behaviour": "Behaviour",
    "channel": "Channels",
    "category": "Categories",
}


@dataclass
class Topic:
    """A subject the agent can recognise in what it reads.

    Two halves, deliberately separated. `pattern`, `category` and `why_it_matters`
    describe the subject. `agent_can`, `workflows` and `implement` describe what
    *this system* could do about it — suggestions from our own playbook, labelled
    as such in the popup, never presented as market findings.
    """
    key: str
    label: str
    category: str
    pattern: str
    why_it_matters: str = ""
    clara_relevance: str = ""      # direct | adjacent | context
    tags: list = field(default_factory=list)
    agent_can: list = field(default_factory=list)
    workflows: list = field(default_factory=list)
    implement: str = ""
    subcategory: str = ""
    _rx: re.Pattern | None = field(default=None, repr=False, compare=False)

    @property
    def icon(self) -> str:
        return CATEGORY_ICON.get(self.category, "📦")

    @property
    def category_label(self) -> str:
        return CATEGORY_LABEL.get(self.category, self.category)

    def matches(self, text: str) -> bool:
        if self._rx is None:
            self._rx = re.compile(self.pattern, re.I)
        return bool(self._rx.search(text or ""))


TOPICS: list[Topic] = [
    Topic("hair_tools", "Hair styling tools", DEVICE,
          r"\bhair dryer\b|\bhairdryer\b|\bblow[- ]?dry\w*\b|\bstraighten\w*\b"
          r"|\bflat iron\b|\bcurling (?:iron|wand)\b|\bhot brush\b|\bair ?styler\b"
          r"|\bairwrap\b|\bflexstyle\b|\bstyling tool\b|\bhair tool\b",
          "Clara's core category. Anything moving here moves Clara's shelf.",
          "direct",
          tags=['Devices', 'Core category', 'Dyson rivals'],
          agent_can=[
              "Read a rival's tool page and pull its price, specs and stock",
              'Match it to the Clara product it competes with',
              'Detect a price move or a new promotion between runs',
              'Flag when a page cannot be read instead of guessing',
          ],
          workflows=[
              'Re-price a Clara dryer against every rival read this week',
              'Alert when a tracked rival cuts price by more than 15%',
              'Compare specs on the four lines a buyer reads first',
          ],
          implement='This is the monitoring loop that already runs. Point `run_agent.py` at a competitor and the Gemini judge decides identity while the deterministic gate decides format; the price is copied from the page, never derived.'),
    Topic("scalp_care", "Scalp care", CATEGORY,
          r"\bscalp\b|\bfollicle\b|\bdandruff\b|\bscalp serum\b|\bscalp massage\b",
          "The fastest-growing part of haircare in most markets, and the bridge "
          "between a device sale and a repeat consumable sale.", "adjacent",
          tags=['Haircare', 'Repeat purchase', 'Fast growing'],
          agent_can=[
              'Track which rivals have added a scalp line and at what price',
              'Read the claims their pages make, verbatim',
              'Watch search demand for scalp terms in the Gulf',
          ],
          workflows=[
              'List every scalp product a tracked rival sells, with prices',
              'Draft a scalp-health line for a Clara product page',
              'Watch scalp search demand in Saudi and the UAE weekly',
          ],
          implement='Add scalp keywords to the topic vocabulary and let the trend collector pick them up; the Vertex model can then draft page copy from the evidence rather than from its own knowledge.'),
    Topic("hair_growth", "Hair growth and density", CATEGORY,
          r"\bhair growth\b|\bhair loss\b|\bthinning hair\b|\bregrowth\b"
          r"|\bminoxidil\b|\brosemary oil\b|\bdensity\b",
          "High-intent, high-margin demand that pulls people into haircare.",
          "adjacent",
          tags=['Haircare', 'High intent', 'Regulated claims'],
          agent_can=[
              'Collect what rivals claim about growth and density, word for word',
              'Separate a marketing claim from a cited study',
              'Track how often the subject appears across publishers',
          ],
          workflows=[
              'Audit rival growth claims and note which cite evidence',
              'Check what a density claim would require before Clara makes one',
          ],
          implement="Growth claims are regulated, so the useful output is a verbatim collection with sources, not a summary. The Verification Agent's rules already refuse to upgrade a single-source claim."),
    Topic("bond_repair", "Bond repair and damage", INGREDIENT,
          r"\bbond (?:repair|builder)\b|\bolaplex\b|\bk18\b|\bpeptide\b"
          r"|\bkeratin\b|\bheat damage\b|\bhair repair\b",
          "The counter-argument to heat styling — and therefore the objection "
          "Clara's device pages have to answer.", "direct",
          tags=['Ingredients', 'Objection handling', 'Olaplex', 'K18'],
          agent_can=[
              'Read the bond-repair claims on rival haircare pages',
              'Track price bands for the repair category',
              'Spot a new ingredient name entering the conversation',
          ],
          workflows=[
              'Build the answer to the heat-damage objection from rival copy',
              "Price Clara's repair range against Olaplex and K18",
          ],
          implement='Pair this with the device pages: the collector supplies the claims, and the decisions page hooks them onto the Clara product that needs the objection answered.'),
    Topic("heat_protection", "Heat protection", INGREDIENT,
          r"\bheat protect\w*\b|\bthermal protect\w*\b|\bheat shield\b",
          "Sells alongside every styling tool. A device brand that ignores it "
          "leaves the attachment sale to someone else.", "direct",
          tags=['Ingredients', 'Attach rate', 'Bundles'],
          agent_can=[
              'Find which rivals bundle protection with a tool, and at what price',
              'Read the protection claim each one makes',
          ],
          workflows=[
              "Design a tool-plus-protection bundle priced against a rival's",
              'Check every Clara device page mentions heat protection',
          ],
          implement="A page-content check the agent can run over Clara's own catalogue, not just competitors — the same extractor works on clarahair.com."),
    Topic("textured_hair", "Textured and curly hair", CATEGORY,
          r"\btextured hair\b|\bcurly hair\b|\bcoily\b|\bafro\b|\b4c hair\b"
          r"|\bcurl pattern\b|\bprotective style\b",
          "The fastest-growing haircare segment in Africa and Brazil, and the "
          "one Clara's tools currently say nothing about.", "direct",
          tags=['Haircare', 'Under-served', 'Africa', 'Brazil'],
          agent_can=[
              'Track which rivals make textured-hair claims and where',
              'Collect the vocabulary those markets actually use',
          ],
          workflows=[
              'Assess whether a Clara tool can honestly claim textured-hair use',
              'Collect the terms used in this segment before writing copy',
          ],
          implement="Vocabulary first: add the segment's own terms to the topic patterns so the collector recognises it, then let the model draft from real copy rather than assumption."),
    Topic("blowout_styles", "Blowout and salon-at-home", TECHNIQUE,
          r"\bblowout\b|\bbouncy blow\w*\b|\bsalon at home\b|\bat[- ]home blow\w*\b"
          r"|\bglass hair\b|\bslick back\b",
          "The specific look people buy a styling tool to achieve.", "direct",
          tags=['Techniques', 'Visual', 'Creator-led'],
          agent_can=[
              'Track which finishes rivals lead their imagery with',
              'Watch search demand for named looks per market',
          ],
          workflows=[
              'Pick the finish each Clara device should show on its main image',
              'Track which look is rising in Saudi search this month',
          ],
          implement='Google Trends per country is already collected; filter it to named looks and the demand side becomes readable without any social login.'),
    Topic("korean_beauty", "K-beauty", CATEGORY,
          r"\bk[- ]beauty\b|\bkorean (?:beauty|skincare|haircare)\b|\bglass skin\b",
          "Sets the aesthetic vocabulary that reaches the Gulf 6–12 months later.",
          "context",
          tags=['Categories', 'Leading indicator', 'Korea'],
          agent_can=[
              'Read Korean trade coverage as it publishes',
              'Track which claims cross into Gulf publishers, and when',
          ],
          workflows=[
              'Watch for a Korean claim appearing in Gulf press',
              'Shortlist Korean vocabulary Clara could adopt early',
          ],
          implement='Korea is the thinnest market in the registry — four Korean feeds were probed and all four failed. Treat this as a lead indicator with known gaps, not a full reading.'),
    Topic("ai_personalisation", "AI and personalisation", TECHNIQUE,
          r"\bai[- ](?:powered|driven|based)\b|\bskin analysis\b|\bhair diagnos\w*\b"
          r"|\bpersonalis\w+\b|\bpersonaliz\w+\b|\bvirtual try[- ]?on\b",
          "Changes how a device is sold: a diagnostic front-end turns a "
          "one-off tool purchase into a routine.", "adjacent",
          tags=['Techniques', 'Conversion', 'On-page'],
          agent_can=[
              'Track which rivals ship a diagnostic or hair-type selector',
              'Read what inputs those tools ask for',
          ],
          workflows=[
              'Spec a hair-type selector for a Clara device page',
              'Compare the questions rival diagnostics ask',
          ],
          implement='Gemini on Vertex can run the recommendation itself: the selector collects hair type and the model maps it to a Clara product from the catalogue, with the reasoning shown.'),
    Topic("dupe_culture", "Dupes and value-seeking", BEHAVIOUR,
          r"\bdupe\b|\bdupes\b|\baffordable alternative\b|\bcheaper version\b"
          r"|\bvalue for money\b",
          "Clara's whole commercial position is being the credible alternative "
          "to a 2,299 SAR device.", "direct",
          tags=['Behaviour', "Clara's position", 'Value'],
          agent_can=[
              'Hold both prices and show the real gap',
              'Refuse to state a gap across two currencies',
              'Date every comparison to the page it was read from',
          ],
          workflows=[
              'Generate an evidenced price comparison for a product page',
              "Screenshot and date a rival's price for a claim",
          ],
          implement='This is the sharpest use of the price report: the gap is already computed only where a stored match holds and both sides publish the same currency.'),
    Topic("social_commerce", "Social commerce", CHANNEL,
          r"\btiktok shop\b|\bsocial commerce\b|\blive ?stream\w* (?:shopping|commerce)\b"
          r"|\bcreator[- ]led\b|\bshoppable\b",
          "Where a hair tool is now discovered and bought in one motion.",
          "adjacent",
          tags=['Channels', 'Discovery', 'Creator'],
          agent_can=[
              'Read what platforms publish themselves about formats and reach',
              'Read the public Meta Ad Library for what rivals pay to say',
          ],
          workflows=[
              'Collect the ad angles rivals are running publicly',
              'Track which creator format rivals lead with',
          ],
          implement='Only public surfaces. Per-post and per-creator data needs an approved API the operator does not hold, and the agent will not work around a login to get it.'),
    Topic("clean_beauty", "Clean and ingredient transparency", INGREDIENT,
          r"\bclean beauty\b|\bingredient transparency\b|\bsulfate[- ]free\b"
          r"|\bparaben[- ]free\b|\bnon[- ]toxic\b",
          "A claim Clara can make cheaply on consumables, and cannot fake.",
          "adjacent",
          tags=['Ingredients', 'Transparency', 'Cheap to act on'],
          agent_can=[
              'Read the ingredient lists rivals publish',
              'Note which claims are certified and which are wording',
          ],
          workflows=[
              "Compare Clara's ingredient disclosure against rivals'",
              'List the claims rivals make without certification',
          ],
          implement='A structured-data read: most ingredient lists are in the page markup already, so the existing extractor gets them without any new capability.'),
    Topic("halal_beauty", "Halal and modest beauty", CATEGORY,
          r"\bhalal\b|\bmodest beauty\b|\bwudu[- ]?friendly\b|\bhijab\w*\b",
          "Directly commercial in Clara's own market and in Southeast Asia.",
          "direct",
          tags=['Categories', 'Saudi', 'Certification'],
          agent_can=[
              'Track which rivals carry a halal claim in this market',
              'Read published certification requirements and deadlines',
          ],
          workflows=[
              'Check which Clara consumables could carry a halal claim',
              'Track rivals adding the claim in Saudi and Indonesia',
          ],
          implement="Certification is documentary, so the agent's job is to collect the published requirement and the rivals who meet it — not to judge eligibility."),
    Topic("mens_grooming", "Men's grooming", CATEGORY,
          r"\bmen'?s grooming\b|\bmale grooming\b|\bbeard\b|\bmen'?s haircare\b",
          "An under-served buyer for styling tools in the Gulf.", "adjacent",
          tags=['Categories', 'Gulf', 'Under-served'],
          agent_can=[
              'Track rival tools positioned for men and their prices',
              "Watch search demand for men's terms per market",
          ],
          workflows=[
              'Assess whether a Clara tool can be positioned for men',
              'Price against the clipper-led brands entering styling',
          ],
          implement='Wahl and Andis are already in the registry for this reason; the monitoring loop covers them with no new work.'),
    Topic("fragrance_hair", "Hair fragrance and mists", CATEGORY,
          r"\bhair (?:mist|perfume|fragrance)\b|\bscented hair\b",
          "A high-margin add-on with strong Gulf demand.", "adjacent",
          tags=['Categories', 'High margin', 'Gulf'],
          agent_can=[
              'Track rival hair mists and their price bands',
              'Watch fragrance search demand in the Gulf',
          ],
          workflows=[
              'Size a scented variant against rival hair mists',
              'Track Gulf fragrance demand alongside haircare',
          ],
          implement="Straight price monitoring: add the rivals' mist pages to the seed list and the existing loop reads them."),
    Topic("longevity", "Longevity and wellness beauty", CATEGORY,
          r"\blongevity\b|\bskin ?longevity\b|\bwellness beauty\b|\bsupplement\w*\b"
          r"|\bcollagen\b|\bingestible\b",
          "Reframes haircare as health, which is where the pricing power is.",
          "context",
          tags=['Categories', 'Pricing power', 'Wellness'],
          agent_can=[
              'Track how rivals frame haircare as health rather than styling',
              'Collect the claims and where each is made',
          ],
          workflows=[
              'Reframe a Clara product page around hair health',
              'Compare wellness framing across rival ranges',
          ],
          implement='A copy-and-positioning read rather than a price one; the model drafts from collected rival copy with each source attached.'),
    Topic("refill_sustainability", "Refills and sustainability", BEHAVIOUR,
          r"\brefill\w*\b|\bsustainab\w+\b|\brecyclab\w+\b|\bpackaging waste\b"
          r"|\bcircular\b",
          "Regulatory in Europe, reputational elsewhere, and cheap to act on "
          "for a consumables line.", "adjacent",
          tags=['Behaviour', 'Regulatory', 'Europe'],
          agent_can=[
              'Track which rivals offer refills and at what saving',
              'Read published packaging rules as they change',
          ],
          workflows=[
              'Cost a refill format against rival refill pricing',
              'Track the regulatory requirement per market',
          ],
          implement='Two different reads — rival pricing from product pages, and rules from trade press — and the page keeps them separate.'),
    Topic("retail_expansion", "Retail and distribution moves", CHANNEL,
          r"\bopens? (?:its )?(?:first )?stores?\b|\bexpand\w* into\b|\benters? the\b"
          r"|\bdistribution deal\b|\bwholesale\b|\bstocks?\b.{0,20}\bsephora\b"
          r"|\bsephora\b|\bulta\b|\bboots\b|\bnykaa\b|\bnoon\b|\bnamshi\b",
          "Where a rival appears next determines who Clara is compared against.",
          "adjacent",
          tags=['Channels', 'Distribution', 'Shelf'],
          agent_can=[
              'Detect a rival appearing at a new retailer',
              'Track which retailers stock which rivals in the Gulf',
          ],
          workflows=[
              'Map rival distribution across Gulf retail',
              'Alert when a rival enters a retailer Clara sells through',
          ],
          implement='The registry already holds retail domains per brand, so a new retailer showing a tracked brand is detectable as a COMPETITOR_CHANGED event.'),
    Topic("price_promotion", "Pricing and promotion moves", BEHAVIOUR,
          r"\bprice (?:cut|rise|increase|drop)\b|\bdiscount\w*\b|\bpromotion\b"
          r"|\bblack friday\b|\bwhite friday\b|\bsingles'? day\b|\bramadan\b",
          "Reads directly onto Clara's own price page.", "direct",
          tags=['Behaviour', 'Pricing', 'Seasonal'],
          agent_can=[
              'Detect a new promotion and when it ends',
              'Distinguish an offer that ended from a page it could not read',
              'Record a discount only where both prices were printed',
          ],
          workflows=[
              'Set a promotional floor before a seasonal window',
              'Track which rivals discount and how deeply',
          ],
          implement="The Live Offers Agent already does this, including the distinction between EXPIRED and UNKNOWN that stops a blocked page from being reported as a rival's pricing decision."),
    Topic("device_beauty_tech", "Beauty devices and tech", DEVICE,
          r"\bbeauty (?:device|tech)\b|\bled mask\b|\bmicrocurrent\b"
          r"|\bat[- ]home device\b|\bipl\b|\blaser hair remov\w*\b",
          "The wider device market Clara sits inside; its buyers are the same "
          "people.", "adjacent",
          tags=['Devices', 'Adjacent', 'At-home'],
          agent_can=[
              'Track at-home device prices beyond hair tools',
              'Read the technology claims those categories make',
          ],
          workflows=[
              'Price a Clara device against the wider at-home category',
              'Track which technology claims are spreading',
          ],
          implement='Widen the competitor registry rather than the code: the same extractor reads an LED mask page as easily as a dryer page.'),
]

# The hair-and-tools vocabulary above is what Clara sells. This widens it to the
# whole category, so a subject that starts in nails or fragrance is visible
# before it crosses into hair rather than after.
from . import trend_topics as _tt  # noqa: E402

TOPICS.extend(_tt.build(Topic))

# Keys must be unique: two patterns under one key would silently merge two
# subjects into one card.
_seen: set = set()
for _t in TOPICS:
    assert _t.key not in _seen, f"duplicate topic key: {_t.key}"
    _seen.add(_t.key)


# A query or headline has to touch beauty at all before any topic is applied.
# Without this the Google Trends feeds flood the page with football fixtures.
BEAUTY_GATE = re.compile(
    r"\bbeauty\b|\bcosmetic\w*\b|\bskincare\b|\bhaircare\b|\bhair\b|\bmakeup\b"
    r"|\bfragrance\b|\bperfume\b|\bshampoo\b|\bconditioner\b|\bsalon\b"
    r"|\bserum\b|\bmoisturis\w+\b|\bmoisturiz\w+\b|\bsunscreen\b|\bspf\b"
    r"|\bnail\w*\b|\blipstick\b|\bmascara\b|\bfoundation\b|\bblush\b"
    r"|\bdyson\b|\bghd\b|\bolaplex\b|\bsephora\b|\bulta\b|\bnykaa\b"
    r"|\bl'?oreal\b|\bestee lauder\b|\bshiseido\b|\bunilever\b|\bp&g\b"
    r"|جمال|شعر|بشرة|عناية|مكياج|عطر|شامبو|صالون", re.I)


# Subjects the discovery loop found and activated. Held at runtime rather than
# written into `trend_topics.py`: the file is the hand-curated seed and stays
# that way, so reverting to it is a matter of not loading these.
DYNAMIC: list = []


def register_dynamic(rows: list) -> int:
    """Add discovered subjects to the live vocabulary for this process.

    Takes plain dicts from the discovery store — key, label, pattern, category —
    so this module never imports the database layer. Replaces the previous set
    rather than appending, so calling it twice cannot double-count a subject.
    """
    DYNAMIC.clear()
    seen = {t.key for t in TOPICS}
    for r in rows:
        key = r.get("key")
        pattern = r.get("pattern")
        if not key or not pattern or key in seen:
            continue
        t = Topic(key=key, label=r.get("label") or key,
                  category=r.get("category") or "beauty_culture",
                  pattern=pattern,
                  why_it_matters=(r.get("why_it_matters")
                                  or "Discovered automatically from recurring "
                                     "uncategorised signals."),
                  clara_relevance=r.get("clara_relevance") or "context",
                  tags=list(r.get("tags") or ["Discovered"]))
        t.subcategory = "discovered"
        DYNAMIC.append(t)
        seen.add(key)
    return len(DYNAMIC)


def all_topics() -> list:
    """Seed vocabulary plus whatever discovery has activated."""
    return list(TOPICS) + list(DYNAMIC)


def topics_for(text: str) -> list[Topic]:
    """Which subjects this headline is evidence for. May be none."""
    return [t for t in all_topics() if t.matches(text)]


def is_beauty(text: str) -> bool:
    return bool(BEAUTY_GATE.search(text or ""))
