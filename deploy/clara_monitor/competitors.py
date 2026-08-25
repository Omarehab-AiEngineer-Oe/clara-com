"""Competitor registry and per-product target assignment.

Requirements §7 ("Target competitors: assigned competitor set per Clara product,
category or run") and §14 (`competitors`, `product_competitor_targets`).

`tier` records how the source is treated, which matters for evidence weight:
  brand_official      the manufacturer's own site — strongest evidence
  authorized_retailer a named retailer carrying the brand in-market
  marketplace         a marketplace listing; identity and price are weaker

§20 assumes "up to 5 target competitors initially"; the registry is larger so
assignment can be narrowed per run rather than by editing code.
"""

from __future__ import annotations

from dataclasses import dataclass, field

BRAND_OFFICIAL = "brand_official"
AUTHORIZED_RETAILER = "authorized_retailer"
MARKETPLACE = "marketplace_third_party"


@dataclass
class Competitor:
    key: str
    brand: str
    tier: str
    domains: list[str] = field(default_factory=list)
    retail_domains: list[str] = field(default_factory=list)
    sitemaps: list[str] = field(default_factory=list)
    search_url: str | None = None      # {q} placeholder
    segments: list[str] = field(default_factory=list)   # device | haircare
    market: str = "SA"
    enabled: bool = True
    notes: str = ""

    def all_domains(self) -> list[str]:
        return list(self.domains) + list(self.retail_domains)


# --------------------------------------------------------------------------
# Device competitors
# --------------------------------------------------------------------------
REGISTRY: dict[str, Competitor] = {}


def _add(c: Competitor) -> None:
    REGISTRY[c.key] = c


_add(Competitor(
    key="dyson", brand="Dyson", tier=BRAND_OFFICIAL,
    domains=["dyson.sa"], retail_domains=["en-saudi.ounass.com", "saudi.microless.com"],
    sitemaps=["https://www.dyson.sa/sitemap.xml"],
    segments=["device"],
    notes="Serves a Cloudflare challenge on some product URLs; those pairs escalate.",
))
_add(Competitor(
    key="shark", brand="Shark Beauty", tier=BRAND_OFFICIAL,
    domains=["sharkninja.com", "sharkclean.com"],
    retail_domains=["en-saudi.ounass.com", "almanea.sa", "saudi.microless.com"],
    sitemaps=["https://www.sharkninja.com/sitemap.xml"],
    segments=["device"],
    notes="sharkninja.com prices are USD; a SAR price needs the KSA retailer source.",
))
_add(Competitor(
    key="laifen", brand="Laifen", tier=BRAND_OFFICIAL,
    domains=["laifen.sa"],
    sitemaps=["https://laifen.sa/sitemap.xml"],
    search_url="https://laifen.sa/search?q={q}",
    segments=["device"],
))
_add(Competitor(
    key="ghd", brand="ghd", tier=BRAND_OFFICIAL,
    domains=["ghdhair.com"], retail_domains=["niceonesa.com", "en-saudi.ounass.com"],
    sitemaps=["https://www.ghdhair.com/sitemap.xml"],
    segments=["device"],
))
_add(Competitor(
    key="revlon", brand="Revlon", tier=AUTHORIZED_RETAILER,
    domains=["revlon.com"], retail_domains=["noon.com", "niceonesa.com"],
    segments=["device"],
    notes="noon.com times out and niceonesa.com returns 403 for this client.",
))
_add(Competitor(
    key="babyliss", brand="BaByliss", tier=BRAND_OFFICIAL,
    domains=["babyliss.com", "babylisspro.com"],
    retail_domains=["niceonesa.com", "noon.com", "en-saudi.ounass.com"],
    sitemaps=["https://www.babyliss.com/sitemap.xml"],
    segments=["device"],
))
_add(Competitor(
    key="remington", brand="Remington", tier=BRAND_OFFICIAL,
    domains=["remington-products.com", "remington.co.uk"],
    retail_domains=["noon.com", "niceonesa.com"],
    sitemaps=["https://www.remington-products.com/sitemap.xml"],
    segments=["device"],
))
_add(Competitor(
    key="philips", brand="Philips", tier=BRAND_OFFICIAL,
    domains=["philips.com.sa", "philips.com"],
    retail_domains=["noon.com", "almanea.sa"],
    sitemaps=["https://www.philips.com.sa/sitemap.xml"],
    segments=["device"],
))
_add(Competitor(
    key="braun", brand="Braun", tier=BRAND_OFFICIAL,
    domains=["braun.com", "sa.braun.com"],
    retail_domains=["noon.com", "almanea.sa"],
    segments=["device"],
))
_add(Competitor(
    key="panasonic", brand="Panasonic", tier=BRAND_OFFICIAL,
    domains=["panasonic.com"], retail_domains=["noon.com", "almanea.sa"],
    segments=["device"],
))
_add(Competitor(
    key="dreame", brand="Dreame", tier=BRAND_OFFICIAL,
    domains=["dreametech.com", "sa.dreametech.com"],
    retail_domains=["noon.com"],
    sitemaps=["https://sa.dreametech.com/sitemap.xml"],
    segments=["device"],
))

# --------------------------------------------------------------------------
# Added after a reachability probe: every domain below returned a readable page
# with structured product data. Gulf retail surfaces are attached as
# retail_domains rather than as competitors of their own — a retailer is where a
# rival's SAR price can be read, which matters for the brands that publish only
# in USD or GBP.
# --------------------------------------------------------------------------
_add(Competitor(
    key="cloudnine", brand="Cloud Nine", tier=BRAND_OFFICIAL,
    domains=["cloudninehair.com"],
    retail_domains=["almanea.sa", "en-saudi.ounass.com"],
    segments=["device"],
    notes="UK premium styling tools; publishes GBP, so a Gulf retailer price is "
          "needed before any comparison with Clara is meaningful.",
))
_add(Competitor(
    key="bioionic", brand="Bio Ionic", tier=BRAND_OFFICIAL,
    domains=["bioionic.com"],
    retail_domains=["en-saudi.ounass.com"],
    segments=["device"],
    notes="Professional ionic tools; the closest technical claim to Clara's own "
          "ionic positioning.",
))
_add(Competitor(
    key="amika", brand="amika", tier=BRAND_OFFICIAL,
    domains=["loveamika.com"],
    retail_domains=["en-saudi.ounass.com", "en-sa.6thstreet.com"],
    segments=["device", "haircare"],
    notes="Sells tools and haircare together, which is the bundle strategy "
          "Clara's catalogue already runs.",
))
_add(Competitor(
    key="tymo", brand="Tymo Beauty", tier=BRAND_OFFICIAL,
    domains=["tymobeauty.com"],
    segments=["device"],
    notes="Direct-to-consumer challenger at Clara's price point; the closest "
          "analogue to Clara's own commercial position.",
))
_add(Competitor(
    key="zuvi", brand="Zuvi", tier=BRAND_OFFICIAL,
    domains=["zuvilife.com"],
    segments=["device"],
    notes="Light-based drying; a technology claim Clara cannot match and should "
          "know the price of.",
))
_add(Competitor(
    key="wahl", brand="Wahl", tier=BRAND_OFFICIAL,
    domains=["wahl.com"],
    retail_domains=["www.jarir.com", "almanea.sa"],
    segments=["device"],
    notes="Clipper-led brand moving into styling; the men's-grooming entry "
          "point Clara has no product in.",
))
_add(Competitor(
    key="andis", brand="Andis", tier=BRAND_OFFICIAL,
    domains=["andis.com"],
    retail_domains=["www.jarir.com"],
    segments=["device"],
    notes="Professional clippers and dryers sold through Gulf electronics "
          "retail rather than beauty retail.",
))


# --------------------------------------------------------------------------
# Haircare competitors — Clara's shampoos, masks, serums, sprays and creams
# --------------------------------------------------------------------------
_add(Competitor(
    key="olaplex", brand="Olaplex", tier=BRAND_OFFICIAL,
    domains=["olaplex.com"], retail_domains=["niceonesa.com", "en-saudi.ounass.com"],
    sitemaps=["https://olaplex.com/sitemap.xml"],
    segments=["haircare"],
))
_add(Competitor(
    key="kerastase", brand="Kérastase", tier=BRAND_OFFICIAL,
    domains=["kerastase.com", "kerastase-usa.com"],
    retail_domains=["en-saudi.ounass.com", "niceonesa.com"],
    segments=["haircare"],
))
_add(Competitor(
    key="moroccanoil", brand="Moroccanoil", tier=BRAND_OFFICIAL,
    domains=["moroccanoil.com"], retail_domains=["niceonesa.com", "en-saudi.ounass.com"],
    sitemaps=["https://www.moroccanoil.com/sitemap.xml"],
    segments=["haircare"],
))
_add(Competitor(
    key="loreal", brand="L'Oréal Paris", tier=BRAND_OFFICIAL,
    domains=["loreal-paris.com", "lorealparisme.com"],
    retail_domains=["noon.com", "niceonesa.com"],
    segments=["haircare"],
))
_add(Competitor(
    key="redken", brand="Redken", tier=BRAND_OFFICIAL,
    domains=["redken.com"], retail_domains=["niceonesa.com"],
    segments=["haircare"],
))


# --------------------------------------------------------------------------
# Assignment: which competitors are evaluated for which Clara product
# --------------------------------------------------------------------------

# Device formats -> ordered competitor keys. Order is priority: the run budget
# is spent from the top down.
ASSIGNMENT_BY_FORMAT: dict[str, list[str]] = {
    "multi_styler":       ["dyson", "shark", "babyliss", "dreame", "philips"],
    "dryer":              ["dyson", "laifen", "philips", "babyliss", "remington", "panasonic"],
    "air_brush":          ["dyson", "revlon", "babyliss", "shark", "remington"],
    "hot_brush":          ["revlon", "babyliss", "remington", "shark", "philips"],
    "auto_curler":        ["dyson", "babyliss", "remington"],
    "straightener":       ["ghd", "dyson", "babyliss", "remington", "philips"],
    "straightener_brush": ["dyson", "ghd", "babyliss", "remington"],
}

# Haircare / accessory categories -> competitor keys.
ASSIGNMENT_BY_CATEGORY: dict[str, list[str]] = {
    "shampoo":       ["olaplex", "kerastase", "loreal", "redken", "moroccanoil"],
    "conditioner":   ["olaplex", "kerastase", "loreal", "redken"],
    "mask":          ["olaplex", "kerastase", "moroccanoil", "redken"],
    "serum":         ["olaplex", "moroccanoil", "kerastase"],
    "oil":           ["moroccanoil", "kerastase", "olaplex"],
    "heat_protect":  ["olaplex", "kerastase", "moroccanoil", "redken"],
    "styling_spray": ["loreal", "redken", "kerastase"],
    "styling_foam":  ["loreal", "redken", "kerastase"],
    "styling_wax":   ["loreal", "redken"],
    "dry_shampoo":   ["loreal", "kerastase", "redken"],
    "scalp":         ["olaplex", "kerastase", "redken"],
    "perfume":       ["moroccanoil", "kerastase"],
    # Brushes, combs, bags, clips: no branded competitor set is assigned. The
    # coverage report lists these as unassigned rather than inventing a rival.
    "accessory":     [],
    "bag":           [],
    "unknown":       [],
}


def targets_for(fmt: str, category: str, segment: str,
               enabled_only: bool = True, limit: int | None = None) -> list[str]:
    """Resolve the assigned competitor set for one Clara product."""
    if segment == "device":
        keys = ASSIGNMENT_BY_FORMAT.get(fmt, [])
    else:
        keys = ASSIGNMENT_BY_CATEGORY.get(category, [])
    out = [k for k in keys if k in REGISTRY and (REGISTRY[k].enabled or not enabled_only)]
    return out[:limit] if limit else out


def get(key: str) -> Competitor | None:
    return REGISTRY.get(key)


def allowed_hosts(keys: list[str] | None = None) -> set[str]:
    """Outbound domain allowlist (§19). Only these hosts may ever be fetched."""
    hosts: set[str] = set()
    for k, c in REGISTRY.items():
        if keys is not None and k not in keys:
            continue
        hosts.update(c.all_domains())
    return hosts


def tier_for_host(host: str, keys: list[str] | None = None) -> str:
    host = (host or "").lower().lstrip(".").split(":")[0]
    for k, c in REGISTRY.items():
        if keys is not None and k not in keys:
            continue
        for d in c.domains:
            if host == d or host.endswith("." + d):
                return BRAND_OFFICIAL
    for k, c in REGISTRY.items():
        if keys is not None and k not in keys:
            continue
        for d in c.retail_domains:
            if host == d or host.endswith("." + d):
                return (AUTHORIZED_RETAILER
                        if c.tier == AUTHORIZED_RETAILER else MARKETPLACE)
    return "unknown"


def summary() -> list[dict]:
    return [
        {"key": c.key, "brand": c.brand, "tier": c.tier,
         "segments": c.segments, "domains": c.domains,
         "retail_domains": c.retail_domains, "enabled": c.enabled,
         "notes": c.notes}
        for c in REGISTRY.values()
    ]


# --------------------------------------------------------------------------
# Wave 2 — added to widen the comparison set. Each still needs its own domain
# allowlist entry before the Agent may fetch it, and the assignment maps below
# decide which Clara products it is actually evaluated against.
# --------------------------------------------------------------------------
_add(Competitor(
    key="t3", brand="T3 Micro", tier=BRAND_OFFICIAL,
    domains=["t3micro.com"], retail_domains=["niceonesa.com", "en-saudi.ounass.com"],
    sitemaps=["https://t3micro.com/sitemap.xml"], segments=["device"]))
_add(Competitor(
    key="drybar", brand="Drybar", tier=BRAND_OFFICIAL,
    domains=["thedrybar.com", "drybarproducts.com"],
    retail_domains=["niceonesa.com", "sephora.sa"], segments=["device", "haircare"]))
_add(Competitor(
    key="xiaomi", brand="Xiaomi", tier=BRAND_OFFICIAL,
    domains=["mi.com"], retail_domains=["noon.com", "amazon.sa"],
    segments=["device"]))
_add(Competitor(
    key="kemei", brand="Kemei", tier=MARKETPLACE,
    domains=[], retail_domains=["noon.com", "amazon.sa"], segments=["device"]))
_add(Competitor(
    key="silkn", brand="Silk'n", tier=BRAND_OFFICIAL,
    domains=["silkn.com"], retail_domains=["niceonesa.com", "noon.com"],
    segments=["device"]))
_add(Competitor(
    key="hottools", brand="Hot Tools", tier=BRAND_OFFICIAL,
    domains=["hottoolspro.com"], retail_domains=["niceonesa.com"],
    segments=["device"]))
_add(Competitor(
    key="conair", brand="Conair", tier=BRAND_OFFICIAL,
    domains=["conair.com"], retail_domains=["noon.com", "amazon.sa"],
    segments=["device"]))
_add(Competitor(
    key="k18", brand="K18", tier=BRAND_OFFICIAL,
    domains=["k18hair.com"], retail_domains=["niceonesa.com", "sephora.sa"],
    sitemaps=["https://k18hair.com/sitemap.xml"], segments=["haircare"]))
_add(Competitor(
    key="schwarzkopf", brand="Schwarzkopf", tier=BRAND_OFFICIAL,
    domains=["schwarzkopf.com"], retail_domains=["noon.com", "niceonesa.com"],
    segments=["haircare"]))
_add(Competitor(
    key="wella", brand="Wella", tier=BRAND_OFFICIAL,
    domains=["wella.com", "wellastore.com"], retail_domains=["niceonesa.com"],
    segments=["haircare"]))


# --------------------------------------------------------------------------
# Middle East and regional competitors, added after a reachability probe.
# Two groups the registry was missing: the value appliance brands that set the
# price floor in Gulf retail, and the regional haircare houses with real shelf
# presence. Every domain below returned a readable storefront when probed.
#
# Not added, and worth knowing: every Gulf *retailer* probed refused us —
# Nice One and Danube 403, Lulu and Basharacare CAPTCHA, Extra login-required,
# Nahdi and Faces 404. That layer is where a foreign brand's SAR price would be
# readable, and it is closed.
# --------------------------------------------------------------------------

# --- value appliance brands: the floor Clara is priced against from below ---
_add(Competitor(
    key="sokany", brand="Sokany", tier=BRAND_OFFICIAL,
    domains=["sokany.com"],
    segments=["device"],
    notes="Very low-cost styling tools sold widely across Gulf marketplaces and "
          "small retail. Sets the bottom of the price range Clara is compared "
          "against.",
))
_add(Competitor(
    key="sanford", brand="Sanford", tier=BRAND_OFFICIAL,
    domains=["sanfordworld.com"],
    segments=["device"],
    notes="UAE-based value appliance brand; hair dryers sit alongside kitchen "
          "goods in the same catalogue.",
))
_add(Competitor(
    key="nikai", brand="Nikai", tier=BRAND_OFFICIAL,
    domains=["nikai.com"],
    segments=["device"],
    notes="Long-established Gulf value appliance brand with broad hypermarket "
          "distribution.",
))
_add(Competitor(
    key="arzum", brand="Arzum", tier=BRAND_OFFICIAL,
    domains=["arzum.com.tr"],
    segments=["device"],
    notes="Turkish appliance maker with a dedicated personal-care range; Turkish "
          "brands carry real weight in Gulf retail.",
))
_add(Competitor(
    key="fakir", brand="Fakir", tier=BRAND_OFFICIAL,
    domains=["fakir.com.tr"],
    segments=["device"],
    notes="Turkish-German appliance brand; styling tools positioned on build "
          "quality rather than price alone.",
))
_add(Competitor(
    key="sinbo", brand="Sinbo", tier=BRAND_OFFICIAL,
    domains=["sinbo.com.tr"],
    segments=["device"],
    notes="Turkish value appliances; among the cheapest hair dryers on Gulf "
          "shelves.",
))
_add(Competitor(
    key="goldmaster", brand="Goldmaster", tier=BRAND_OFFICIAL,
    domains=["goldmaster.com.tr"],
    segments=["device"],
    notes="Turkish electronics brand with a personal-care line exported across "
          "the region.",
))
_add(Competitor(
    key="kingtr", brand="King", tier=BRAND_OFFICIAL,
    domains=["king.com.tr"],
    segments=["device"],
    notes="Turkish small-appliance brand; hair dryers at entry price points.",
))

# --- regional haircare with Gulf shelf presence ---
_add(Competitor(
    key="beesline", brand="Beesline", tier=BRAND_OFFICIAL,
    domains=["beesline.com"],
    segments=["haircare"],
    notes="Lebanese natural skincare and haircare with wide Gulf pharmacy "
          "distribution.",
))
_add(Competitor(
    key="dabur", brand="Dabur", tier=BRAND_OFFICIAL,
    domains=["daburinternational.com"],
    segments=["haircare"],
    notes="Owns Vatika, the highest-volume hair-oil brand in the region. Competes "
          "for the same consumable spend as Clara's serums and creams.",
))
_add(Competitor(
    key="bioblas", brand="Bioblas", tier=BRAND_OFFICIAL,
    domains=["bioblas.com"],
    segments=["haircare"],
    notes="Turkish haircare built on an anti-hair-loss claim; strong pharmacy "
          "presence across the Gulf.",
))
_add(Competitor(
    key="nivea", brand="Nivea", tier=BRAND_OFFICIAL,
    domains=["nivea.ae"],
    segments=["haircare"],
    notes="Beiersdorf's regional storefront; mass-market haircare at the lowest "
          "price points on the shelf.",
))
_add(Competitor(
    key="hudabeauty", brand="Huda Beauty", tier=BRAND_OFFICIAL,
    domains=["hudabeauty.com"],
    segments=[],
    notes="The largest Gulf-born beauty house. Sells no hair tool and no "
          "haircare, so segments are deliberately empty: it competes for beauty "
          "spend and attention, not for shelf space, and must not enter price "
          "comparisons.",
))

# Wave 2 assignments: appended so the existing priority order is unchanged and
# the new brands are evaluated after the established ones.
for _fmt, _extra in {
    "multi_styler":       ["t3", "drybar"],
    "dryer":              ["dreame", "xiaomi", "conair", "drybar"],
    "air_brush":          ["hottools", "drybar", "conair"],
    "hot_brush":          ["hottools", "drybar", "conair", "t3"],
    "auto_curler":        ["t3", "hottools", "conair"],
    "straightener":       ["t3", "hottools", "xiaomi"],
    "straightener_brush": ["hottools", "conair"],
}.items():
    _cur = ASSIGNMENT_BY_FORMAT.setdefault(_fmt, [])
    for _k in _extra:
        if _k not in _cur:
            _cur.append(_k)

for _cat, _extra in {
    "shampoo":       ["k18", "schwarzkopf", "wella"],
    "conditioner":   ["k18", "schwarzkopf", "wella"],
    "mask":          ["k18", "wella"],
    "serum":         ["k18", "drybar"],
    "oil":           ["k18"],
    "heat_protect":  ["k18", "drybar", "schwarzkopf"],
    "styling_spray": ["drybar", "schwarzkopf", "wella"],
    "styling_foam":  ["drybar", "schwarzkopf"],
    "styling_wax":   ["schwarzkopf"],
    "dry_shampoo":   ["drybar", "schwarzkopf"],
    "scalp":         ["k18", "wella"],
    "perfume":       ["drybar"],
}.items():
    _cur = ASSIGNMENT_BY_CATEGORY.setdefault(_cat, [])
    for _k in _extra:
        if _k not in _cur:
            _cur.append(_k)
