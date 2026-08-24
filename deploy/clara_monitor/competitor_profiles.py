"""Commercial profile for each competitor — the business view, not the plumbing.

The registry in `competitors.py` says where a brand may be fetched from. This says
what the brand *is* in the market: who it sells to, roughly what it charges in
Saudi, how it usually discounts, and what it is known for.

These are editorial fields, maintained by a human, and the site labels them as
such. They are kept apart from anything the Agent observed, so a profile written
here can never be mistaken for a price the Agent actually read.
"""

from __future__ import annotations

from dataclasses import dataclass, field

TIER_PREMIUM = "premium"
TIER_MID = "mid_market"
TIER_VALUE = "value"
TIER_PRO = "professional"


@dataclass
class Profile:
    key: str
    origin: str = ""
    founded: str = ""
    positioning: str = ""
    price_tier: str = TIER_MID
    sar_band: str = ""            # typical Saudi street band for the range
    known_for: list[str] = field(default_factory=list)
    ksa_presence: str = ""
    discount_habit: str = ""
    audience: str = ""
    threat_to_clara: str = ""     # low | medium | high
    threat_note: str = ""

    def as_dict(self) -> dict:
        return {
            "key": self.key, "origin": self.origin, "founded": self.founded,
            "positioning": self.positioning, "price_tier": self.price_tier,
            "sar_band": self.sar_band, "known_for": self.known_for,
            "ksa_presence": self.ksa_presence, "discount_habit": self.discount_habit,
            "audience": self.audience, "threat_to_clara": self.threat_to_clara,
            "threat_note": self.threat_note,
        }


PROFILES: dict[str, Profile] = {}


def _p(p: Profile) -> None:
    PROFILES[p.key] = p


# --------------------------------------------------------------------------
# Devices — premium
# --------------------------------------------------------------------------
_p(Profile(
    key="dyson", origin="United Kingdom", founded="1991",
    positioning="The reference point for premium hair styling tools",
    price_tier=TIER_PREMIUM, sar_band="1,500 – 2,700",
    known_for=["Coanda airflow curling", "110,000 rpm digital motor",
               "Heat held under 150 °C", "MyDyson app pairing"],
    ksa_presence="Own store dyson.sa + Ounass + Microless",
    discount_habit="Rarely cuts price; adds a case or comb instead of discounting",
    audience="Premium buyer who wants the best regardless of price",
    threat_to_clara="medium",
    threat_note="Not a price competitor, but it sets the expectation for what a "
                "styling tool should do. Every Clara multi-styler is mentally "
                "compared against it."))

_p(Profile(
    key="shark", origin="United States", founded="2003 (SharkNinja)",
    positioning="The cheaper Dyson alternative with measurable specifications",
    price_tier=TIER_PREMIUM, sar_band="1,300 – 1,600",
    known_for=["FlexStyle bends from dryer to styler", "Heat regulated 1,000×/sec",
               "5 functions in one tool", "Storage case included"],
    ksa_presence="Ounass + Almanea + Microless (no official Saudi store)",
    discount_habit="Seasonal 20–30% cuts and limited editions",
    audience="Wants the Dyson experience on a smaller budget",
    threat_to_clara="high",
    threat_note="The narrowest price gap to Clara in the upper tier. The Glossy "
                "edition at SAR 677 is the most exposed price point in the range."))

_p(Profile(
    key="ghd", origin="United Kingdom", founded="2001",
    positioning="The professional benchmark for straighteners",
    price_tier=TIER_PRO, sar_band="1,200 – 1,900",
    known_for=["Single optimum 185 °C", "ultra-zone predictive technology",
               "Heat read 250×/sec", "Claims 70% stronger hair"],
    ksa_presence="Nice One + Ounass",
    discount_habit="Frequent 20–31% cuts through Nice One",
    audience="Salons and professionals, plus buyers wanting one tool that lasts",
    threat_to_clara="medium",
    threat_note="The opposite philosophy to Clara: one fixed temperature versus "
                "three settings and more control. Clara offers more features for "
                "16% of the price."))

_p(Profile(
    key="t3", origin="United States", founded="2004",
    positioning="Premium styling tools with design-led appeal",
    price_tier=TIER_PREMIUM, sar_band="700 – 1,700",
    known_for=["HeatCore technology", "Light, refined build",
               "Interchangeable barrels"],
    ksa_presence="Ounass + Nice One (intermittent stock)",
    discount_habit="Major seasonal sales only",
    audience="Design- and brand-conscious buyer",
    threat_to_clara="low",
    threat_note="Limited Saudi presence; worth watching rather than answering."))

_p(Profile(
    key="drybar", origin="United States", founded="2010",
    positioning="Retail arm of an American blow-dry salon chain",
    price_tier=TIER_PREMIUM, sar_band="550 – 1,300",
    known_for=["Brush Crush heated brush", "Buttercup dryer",
               "Distinctive yellow identity"],
    ksa_presence="Nice One + Sephora (selective)",
    discount_habit="Bundles and set offers",
    audience="Wants a salon result at home",
    threat_to_clara="low",
    threat_note="Same promise as Clara — salon result at home — but at a higher "
                "price and thinner availability."))

# --------------------------------------------------------------------------
# Devices — mid market and value (Clara's real price neighbourhood)
# --------------------------------------------------------------------------
_p(Profile(
    key="laifen", origin="China", founded="2019",
    positioning="Direct mid-price rival that publishes its numbers",
    price_tier=TIER_MID, sar_band="286 – 719",
    known_for=["110,000 rpm motor", "22 m/s air speed", "407 g weight",
               "2-year warranty stated", "Independent Saudi store"],
    ksa_presence="Official Saudi store laifen.sa — the same model as Clara",
    discount_habit="Standing ~10% off the listed price",
    audience="Buyer who compares specifications number by number",
    threat_to_clara="high",
    threat_note="Clara's real competitor: same price band, same direct-to-consumer "
                "channel — but it publishes rpm, weight and warranty where Clara "
                "publishes adjectives."))

_p(Profile(
    key="babyliss", origin="France", founded="1961",
    positioning="Long-established styling brand spanning every price tier",
    price_tier=TIER_MID, sar_band="150 – 900",
    known_for=["Very wide range", "BaBylissPRO professional line",
               "Titanium and ceramic barrels"],
    ksa_presence="Noon + Nice One + Ounass",
    discount_habit="Frequent and deep cuts, up to 40%",
    audience="Broad, from budget to professional",
    threat_to_clara="high",
    threat_note="Overlaps Clara's whole range and discounts hard. The most "
                "dangerous competitor on the direct price decision."))

_p(Profile(
    key="remington", origin="United States", founded="1937",
    positioning="Value for money across a wide range",
    price_tier=TIER_VALUE, sar_band="120 – 600",
    known_for=["Keratin and argan-oil coatings", "Low prices",
               "Large straightener and dryer range"],
    ksa_presence="Noon + Nice One",
    discount_habit="Near-permanent discount",
    audience="Price-sensitive buyer",
    threat_to_clara="medium",
    threat_note="Pressures Clara from below, particularly on heated brushes and "
                "straighteners."))

_p(Profile(
    key="revlon", origin="United States", founded="1932",
    positioning="Owner of the One-Step volumising brush category",
    price_tier=TIER_VALUE, sar_band="110 – 320",
    known_for=["One-Step Volumizer, the global best seller", "1,100 W",
               "Very low price for the function"],
    ksa_presence="Noon + Nice One + Amazon.sa",
    discount_habit="Already cheap; discounts often",
    audience="A shopper's first styling tool",
    threat_to_clara="high",
    threat_note="The only competitor that sells below Clara for the same function. "
                "The Sleek Hot Brush at SAR 295 faces a price starting from 218."))

_p(Profile(
    key="philips", origin="Netherlands", founded="1891",
    positioning="Trusted household appliance brand with wide distribution",
    price_tier=TIER_MID, sar_band="150 – 800",
    known_for=["ThermoProtect technology", "Wide retail availability",
               "Strong reliability reputation"],
    ksa_presence="Own store philips.com.sa + Noon + Almanea",
    discount_habit="Regular seasonal cuts",
    audience="Buyer who trusts the big established brands",
    threat_to_clara="medium",
    threat_note="Distribution strength outweighs product strength in this category, "
                "but brand trust still converts."))

_p(Profile(
    key="braun", origin="Germany", founded="1921",
    positioning="German engineering focused on personal care",
    price_tier=TIER_MID, sar_band="150 – 700",
    known_for=["Functional design", "Durability reputation",
               "Stronger in hair removal than styling"],
    ksa_presence="Noon + Almanea",
    discount_habit="Seasonal cuts",
    audience="Values engineering and durability",
    threat_to_clara="low",
    threat_note="Its styling presence is weaker than its other categories."))

_p(Profile(
    key="panasonic", origin="Japan", founded="1918",
    positioning="Japanese technology focused on hair health",
    price_tier=TIER_MID, sar_band="200 – 900",
    known_for=["nanoe ion technology", "Japanese build quality"],
    ksa_presence="Noon + Almanea",
    discount_habit="Limited discounting",
    audience="Interested in hair health and technology",
    threat_to_clara="low",
    threat_note="Its Saudi range is relatively narrow."))

_p(Profile(
    key="dreame", origin="China", founded="2017",
    positioning="Fast-rising Chinese player with aggressive pricing",
    price_tier=TIER_MID, sar_band="300 – 900",
    known_for=["High-speed motors", "Aggressive pricing",
               "Fast entry into new categories"],
    ksa_presence="Saudi store + Noon",
    discount_habit="Strong launch discounts",
    audience="Wants high specifications at a mid price",
    threat_to_clara="high",
    threat_note="The same pattern as Laifen: published numbers and a price that "
                "sits directly on Clara's."))

_p(Profile(
    key="xiaomi", origin="China", founded="2010",
    positioning="Low-cost smart devices carried by a large ecosystem",
    price_tier=TIER_VALUE, sar_band="100 – 500",
    known_for=["Very low pricing", "Connected device ecosystem",
               "Wide availability on Noon"],
    ksa_presence="Mi stores + Noon + Amazon.sa",
    discount_habit="Permanently low price",
    audience="Budget buyer",
    threat_to_clara="medium",
    threat_note="Pressures the simpler categories — dryers and brushes — from "
                "below."))

_p(Profile(
    key="kemei", origin="China", founded="1997",
    positioning="Very low-cost devices with broad informal distribution",
    price_tier=TIER_VALUE, sar_band="40 – 200",
    known_for=["Cheapest tier in the market", "Huge range",
               "Available everywhere"],
    ksa_presence="Noon + Amazon.sa + local shops",
    discount_habit="Already at floor price",
    audience="The most price-sensitive shopper",
    threat_to_clara="low",
    threat_note="Not competing for the same buyer; useful as a reference for the "
                "market's price floor."))

_p(Profile(
    key="silkn", origin="Israel / Netherlands", founded="2006",
    positioning="Technology-led at-home beauty devices",
    price_tier=TIER_MID, sar_band="300 – 1,200",
    known_for=["Focus on laser and treatment devices",
               "Limited styling line"],
    ksa_presence="Nice One + Noon",
    discount_habit="Frequent discounts",
    audience="Interested in at-home beauty devices",
    threat_to_clara="low",
    threat_note="Overlap with Clara is small; mostly a different category."))

_p(Profile(
    key="hottools", origin="United States", founded="1980s",
    positioning="Professional styling tools for salons",
    price_tier=TIER_PRO, sar_band="250 – 800",
    known_for=["Professional heated brushes", "Titanium barrels",
               "Popular with stylists"],
    ksa_presence="Nice One + salon supply retailers",
    discount_habit="Limited discounting",
    audience="Stylists and advanced home users",
    threat_to_clara="medium",
    threat_note="Competes with Clara's heated brushes carrying professional "
                "credibility."))

_p(Profile(
    key="conair", origin="United States", founded="1959",
    positioning="Parent of Revlon tools; broad budget coverage",
    price_tier=TIER_VALUE, sar_band="100 – 400",
    known_for=["Very large range", "Low prices", "InfinitiPro line"],
    ksa_presence="Noon + Amazon.sa",
    discount_habit="Near-permanent discount",
    audience="Budget buyer",
    threat_to_clara="medium",
    threat_note="Together with Revlon it applies double pressure to the lower end "
                "of Clara's range."))

# --------------------------------------------------------------------------
# Haircare
# --------------------------------------------------------------------------
_p(Profile(
    key="olaplex", origin="United States", founded="2014",
    positioning="Created the bond-repair category",
    price_tier=TIER_PREMIUM, sar_band="120 – 300",
    known_for=["Patented bond-building technology",
               "Numbered range from No.0 to No.9", "Very high recommendation rate"],
    ksa_presence="Nice One + Ounass + Sephora",
    discount_habit="Limited discounts, frequent bundles",
    audience="Damaged or colour-treated hair",
    threat_to_clara="high",
    threat_note="The benchmark repair products are measured against. Clara's serum "
                "and mask are compared to it."))

_p(Profile(
    key="kerastase", origin="France", founded="1964",
    positioning="L'Oréal's luxury salon haircare",
    price_tier=TIER_PREMIUM, sar_band="150 – 450",
    known_for=["In-salon diagnosis", "A range per hair type",
               "Premium packaging"],
    ksa_presence="Ounass + Nice One + salons",
    discount_habit="Rarely discounts",
    audience="Luxury consumer",
    threat_to_clara="medium",
    threat_note="Sets the price ceiling for haircare rather than competing with "
                "Clara directly on price."))

_p(Profile(
    key="moroccanoil", origin="Israel / Canada", founded="2006",
    positioning="Created the argan-oil hair category",
    price_tier=TIER_PREMIUM, sar_band="130 – 350",
    known_for=["The original treatment oil", "Instantly recognisable scent",
               "Blue and gold packaging"],
    ksa_presence="Nice One + Ounass + Sephora",
    discount_habit="Seasonal cuts and bundles",
    audience="Looking for shine and moisture",
    threat_to_clara="high",
    threat_note="Clara's shine serum and oils compete in a category this brand "
                "created."))

_p(Profile(
    key="loreal", origin="France", founded="1909",
    positioning="The widest-distributed haircare brand in the world",
    price_tier=TIER_VALUE, sar_band="25 – 120",
    known_for=["Available in every store", "Low prices",
               "Very large marketing spend"],
    ksa_presence="Every pharmacy and supermarket + Noon",
    discount_habit="Frequent discounts and 1+1 offers",
    audience="Mass market",
    threat_to_clara="medium",
    threat_note="Pushes shampoo and spray prices down from below by a wide margin."))

_p(Profile(
    key="redken", origin="United States", founded="1960",
    positioning="L'Oréal's professional salon haircare",
    price_tier=TIER_PRO, sar_band="100 – 250",
    known_for=["Protein and amino-acid focus",
               "Professional styling products"],
    ksa_presence="Nice One + salons",
    discount_habit="Limited discounting",
    audience="Advanced users and salons",
    threat_to_clara="low",
    threat_note="Its primary channel is salons rather than direct sale."))

_p(Profile(
    key="k18", origin="United States", founded="2020",
    positioning="Biomimetic peptide repair in four minutes",
    price_tier=TIER_PREMIUM, sar_band="180 – 400",
    known_for=["The well-known leave-in mask", "Fast-repair promise",
               "Strong growth through TikTok"],
    ksa_presence="Nice One + Sephora",
    discount_habit="Rare discounts",
    audience="Follows haircare trends",
    threat_to_clara="high",
    threat_note="The fastest-rising brand in repair; it is resetting expectations "
                "for how quickly a result should show."))

_p(Profile(
    key="schwarzkopf", origin="Germany", founded="1898",
    positioning="Widely distributed haircare and home colour",
    price_tier=TIER_VALUE, sar_band="30 – 150",
    known_for=["Gliss and Got2b", "Strength in home colour"],
    ksa_presence="Supermarkets + pharmacies + Noon",
    discount_habit="Frequent offers",
    audience="Mass market",
    threat_to_clara="low",
    threat_note="Weighted towards colour rather than styling or advanced care."))

_p(Profile(
    key="wella", origin="Germany", founded="1880",
    positioning="Professional salon care and colour",
    price_tier=TIER_PRO, sar_band="60 – 250",
    known_for=["Wellaplex", "Strength in the salon channel"],
    ksa_presence="Salons + Nice One",
    discount_habit="Limited discounting",
    audience="Salons and professionals",
    threat_to_clara="low",
    threat_note="A different channel from Clara's."))


# --------------------------------------------------------------------------
# Added alongside the seven competitors that came out of the reachability probe.
# Editorial, like everything else in this file: publicly stated positioning only.
# No Saudi price band is asserted for a brand whose Gulf pricing has not been
# read — that is the one number a reader would act on, and guessing it would be
# worse than leaving it blank.
# --------------------------------------------------------------------------
_p(Profile(
    key="cloudnine", origin="United Kingdom", founded="2008",
    positioning="Salon-grade heat control sold on hair health rather than power",
    price_tier=TIER_PREMIUM,
    known_for=["Variable temperature control", "Mineral-infused plates",
               "Salon distribution"],
    ksa_presence="Sold through Gulf luxury retail rather than a local storefront",
    discount_habit="Rarely discounts; runs gift-with-purchase instead",
    audience="Buyers who have been told heat damages hair and want a tool that "
             "answers that objection",
    threat_to_clara="medium",
    threat_note="Competes on the damage argument, which is the strongest "
                "objection to any styling tool Clara sells.",
))
_p(Profile(
    key="bioionic", origin="United States", founded="2000",
    positioning="Professional ionic and moisture technology, salon-first",
    price_tier=TIER_PRO,
    known_for=["Ionic technology", "Moisturising heat claims",
               "Stylist endorsement"],
    ksa_presence="Available through Gulf luxury retail",
    discount_habit="Professional pricing, infrequent consumer promotions",
    audience="Stylists and buyers copying a salon routine",
    threat_to_clara="medium",
    threat_note="Its ionic claim is the closest technical overlap with Clara's "
                "own ionic range, so the two get compared directly.",
))
_p(Profile(
    key="amika", origin="United States", founded="2007",
    positioning="Colourful, ingredient-led haircare with tools alongside",
    price_tier=TIER_MID,
    known_for=["Bold packaging", "Sea buckthorn formulations",
               "Tools and haircare sold together"],
    ksa_presence="Stocked by Gulf beauty e-commerce",
    discount_habit="Frequent bundle offers and set pricing",
    audience="Younger buyers who buy a routine rather than a single product",
    threat_to_clara="high",
    threat_note="Sells devices and consumables as one basket, which is exactly "
                "the bundle strategy Clara's own catalogue runs.",
))
_p(Profile(
    key="tymo", origin="United States", founded="2018",
    positioning="Direct-to-consumer styling tools at a fraction of premium prices",
    price_tier=TIER_VALUE,
    known_for=["Heated straightening brushes", "Aggressive online pricing",
               "Heavy creator marketing"],
    ksa_presence="Reaches the Gulf mainly through marketplaces rather than "
                 "a local store",
    discount_habit="Near-permanent discounting and bundle pricing",
    audience="Value-seeking buyers looking for a premium alternative",
    threat_to_clara="high",
    threat_note="The closest analogue to Clara's own commercial position: same "
                "argument, same price band, same buyer.",
))
_p(Profile(
    key="zuvi", origin="China", founded="2019",
    positioning="Light-based drying — infrared instead of high heat",
    price_tier=TIER_PREMIUM,
    known_for=["Halo light-drying technology", "Low-heat claims",
               "Design-led launch"],
    ksa_presence="No dedicated Gulf storefront identified",
    discount_habit="Occasional launch pricing; holds list otherwise",
    audience="Early adopters willing to pay for a technology claim",
    threat_to_clara="medium",
    threat_note="Holds a technology claim Clara cannot match, which sets the "
                "ceiling of what a dryer can be sold on.",
))
_p(Profile(
    key="wahl", origin="United States", founded="1919",
    positioning="Clipper heritage extended into wider personal grooming",
    price_tier=TIER_MID,
    known_for=["Professional clippers", "Durability", "Barber distribution"],
    ksa_presence="Widely available through Gulf electronics and pharmacy retail",
    discount_habit="Regular retailer-led promotions",
    audience="Men, and households buying one grooming tool for everyone",
    threat_to_clara="low",
    threat_note="Barely overlaps on product, but owns the men's-grooming entry "
                "point Clara has nothing in.",
))
_p(Profile(
    key="andis", origin="United States", founded="1922",
    positioning="Professional grooming tools built for trade use",
    price_tier=TIER_PRO,
    known_for=["Barber and salon clippers", "Motor durability",
               "Trade channel strength"],
    ksa_presence="Sold through Gulf electronics retail rather than beauty retail",
    discount_habit="Trade pricing; rare consumer discounting",
    audience="Barbers, salons and serious home users",
    threat_to_clara="low",
    threat_note="A trade-channel brand rather than a shelf rival, but it sets "
                "the durability expectation buyers bring to any motor claim.",
))


# --------------------------------------------------------------------------
# Middle East and regional additions. Editorial, like the rest of this file:
# publicly stated positioning only. No Saudi price band is asserted for a brand
# whose Gulf pricing has not been read — that is the number a reader would act
# on, and guessing it would be worse than leaving it blank.
# --------------------------------------------------------------------------
_p(Profile(
    key="sokany", origin="China / Gulf distribution",
    positioning="Lowest-price styling tools, sold on price alone",
    price_tier=TIER_VALUE,
    known_for=["Very low prices", "Marketplace ubiquity", "Broad range"],
    ksa_presence="Widely available through marketplaces and small retail",
    discount_habit="Permanently low; discounting is the default state",
    audience="First-time buyers and gift purchases at the lowest price point",
    threat_to_clara="high",
    threat_note="Sets the floor of the category. A buyer comparing Clara with "
                "Sokany is asking why Clara costs several times more, and that "
                "question has to be answerable on the page.",
))
_p(Profile(
    key="sanford", origin="United Arab Emirates",
    positioning="Value household and personal-care appliances",
    price_tier=TIER_VALUE,
    known_for=["Broad appliance catalogue", "Gulf distribution", "Low prices"],
    ksa_presence="Gulf electronics and hypermarket retail",
    discount_habit="Retailer-led promotions rather than brand campaigns",
    audience="Households buying one affordable tool",
    threat_to_clara="medium",
    threat_note="Competes on price in the same aisles, without a styling story.",
))
_p(Profile(
    key="nikai", origin="United Arab Emirates", founded="1985",
    positioning="Long-established Gulf value appliance brand",
    price_tier=TIER_VALUE,
    known_for=["Hypermarket distribution", "Recognised regional name",
               "Entry pricing"],
    ksa_presence="Broad hypermarket presence",
    discount_habit="Frequent retailer promotions",
    audience="Price-first buyers who want a familiar regional name",
    threat_to_clara="medium",
    threat_note="Brand familiarity in the Gulf is its advantage over an "
                "unknown import at the same price.",
))
_p(Profile(
    key="arzum", origin="Türkiye", founded="1966",
    positioning="Turkish appliances with a dedicated personal-care range",
    price_tier=TIER_MID,
    known_for=["Personal-care line", "Turkish manufacturing", "Design range"],
    ksa_presence="Turkish brands carry real weight in Gulf retail",
    discount_habit="Seasonal campaigns",
    audience="Mid-market buyers who want more than entry quality",
    threat_to_clara="medium",
    threat_note="Occupies the mid band Clara sells into, with a manufacturing "
                "story Clara does not have.",
))
_p(Profile(
    key="fakir", origin="Türkiye / Germany", founded="1933",
    positioning="Turkish-German engineering, sold on build quality",
    price_tier=TIER_MID,
    known_for=["German engineering heritage", "Durability", "Motor quality"],
    ksa_presence="Available through Gulf appliance retail",
    discount_habit="Holds price; occasional bundles",
    audience="Buyers who distrust the cheapest option",
    threat_to_clara="medium",
    threat_note="Answers the durability objection with heritage, which is the "
                "argument Clara has to win on specification instead.",
))
_p(Profile(
    key="sinbo", origin="Türkiye",
    positioning="Entry-price Turkish appliances",
    price_tier=TIER_VALUE,
    known_for=["Very low prices", "Wide range", "Regional export"],
    ksa_presence="Present across Gulf value retail",
    discount_habit="Permanently low",
    audience="Lowest-price buyers",
    threat_to_clara="low",
    threat_note="Competes below Clara's floor rather than against it.",
))
_p(Profile(
    key="goldmaster", origin="Türkiye",
    positioning="Turkish electronics with a personal-care line",
    price_tier=TIER_VALUE,
    known_for=["Broad electronics range", "Export distribution"],
    ksa_presence="Regional export retail",
    discount_habit="Retailer-led",
    audience="Price-led buyers",
    threat_to_clara="low",
    threat_note="A shelf-share rival rather than a positioning rival.",
))
_p(Profile(
    key="kingtr", origin="Türkiye",
    positioning="Turkish small appliances at entry price points",
    price_tier=TIER_VALUE,
    known_for=["Entry pricing", "Domestic Turkish strength"],
    ksa_presence="Regional export retail",
    discount_habit="Retailer-led",
    audience="Entry-level buyers",
    threat_to_clara="low",
    threat_note="Low overlap with Clara's positioning, real overlap on shelf.",
))
_p(Profile(
    key="beesline", origin="Lebanon", founded="1993",
    positioning="Natural skincare and haircare, pharmacy-led",
    price_tier=TIER_MID,
    known_for=["Natural formulations", "Pharmacy distribution",
               "Regional trust"],
    ksa_presence="Wide Gulf pharmacy presence",
    discount_habit="Pharmacy promotions and bundles",
    audience="Buyers who prefer a regional natural brand",
    threat_to_clara="medium",
    threat_note="Competes for the same consumable spend as Clara's haircare, "
                "with a regional-trust advantage Clara can only match on price "
                "or claim.",
))
_p(Profile(
    key="dabur", origin="India", founded="1884",
    positioning="Mass-market haircare; owns Vatika",
    price_tier=TIER_VALUE,
    known_for=["Vatika hair oil", "Highest regional volume", "Ubiquity"],
    ksa_presence="Every grocery and pharmacy channel in the region",
    discount_habit="Constant multipack and price promotions",
    audience="Everyday haircare buyers across every income band",
    threat_to_clara="high",
    threat_note="The default haircare purchase in the region. Clara's serums "
                "and creams are compared against Vatika's price whether or not "
                "the products are alike.",
))
_p(Profile(
    key="bioblas", origin="Türkiye",
    positioning="Anti-hair-loss haircare, pharmacy-led",
    price_tier=TIER_MID,
    known_for=["Hair-loss claim", "Pharmacy presence", "Herbal formulations"],
    ksa_presence="Strong Gulf pharmacy distribution",
    discount_habit="Pharmacy promotions",
    audience="Buyers with a specific hair-loss concern",
    threat_to_clara="medium",
    threat_note="Owns the hair-loss claim in Gulf pharmacy, which is the "
                "highest-intent demand in haircare and one Clara makes no claim "
                "on.",
))
_p(Profile(
    key="nivea", origin="Germany", founded="1911",
    positioning="Mass-market personal care at the lowest shelf prices",
    price_tier=TIER_VALUE,
    known_for=["Global recognition", "Lowest price points", "Total ubiquity"],
    ksa_presence="Every retail channel in the Gulf",
    discount_habit="Frequent multipack and retailer promotions",
    audience="Everyone; the default option when nothing else is chosen",
    threat_to_clara="medium",
    threat_note="Not a styling rival, but it anchors what a Gulf shopper "
                "expects a bottle of haircare to cost.",
))
_p(Profile(
    key="hudabeauty", origin="United Arab Emirates", founded="2013",
    positioning="Gulf-born global beauty house, creator-led",
    price_tier=TIER_PREMIUM,
    known_for=["Creator-led growth", "Regional pride", "Global distribution"],
    ksa_presence="Sephora and Gulf beauty e-commerce",
    discount_habit="Rarely discounts; launches instead",
    audience="Gulf beauty buyers who follow creators",
    threat_to_clara="low",
    threat_note="Sells no hair tool and no haircare, so it takes beauty spend "
                "and attention rather than shelf space. Included for context, "
                "and excluded from price comparison by design.",
))


def get(key: str) -> Profile | None:
    return PROFILES.get(key)


def as_dict(key: str) -> dict:
    p = PROFILES.get(key)
    return p.as_dict() if p else {}


def summary() -> list[dict]:
    return [p.as_dict() for p in PROFILES.values()]
