"""Run configuration for the competitor catalog monitor.

Nothing in the pipeline is allowed to widen this at runtime. The domain
allowlist in particular is a compliance control, not a hint: `access.py`
refuses any host that is not listed here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
REPORT_DIR = ROOT / "reports"
DB_PATH = DATA_DIR / "monitor.sqlite3"
SEED_CATALOG = DATA_DIR / "clara_catalog_seed.json"

MARKET = "SA"
CURRENCY = "SAR"

# --- Clara scope -----------------------------------------------------------
# The devices in scope for catalog monitoring, keyed by Salla product id.
# Accessories and consumables are out of scope for competitor matching.
CLARA_DEVICE_IDS = [
    "p628350933",    # Glossy Multi-Use Hair Dryer
    "p1268166868",   # Multi-Use Hair Dryer
    "p2109273391",   # Powerful Hair Dryer
    "p2102476809",   # Dual Slim Brush
    "p2002321110",   # AirGlow
    "p1375123245",   # Automatic Wavy Hair Curler
    "p318913744",    # Slim Ionic Hair Brush
    "p244927265",    # Advanced Hair Dryer
    "p105025164",    # Sleek Hot Brush
    "p425866025",    # Platinum Hair Straightener
]

# --- Competitor scope ------------------------------------------------------
# source_type is part of the contract: a marketplace listing is never
# silently treated as the brand's own price.
COMPETITORS = {
    "dyson": {
        "brand": "Dyson",
        "domains": ["dyson.sa"],
        "source_type": "brand_official",
    },
    "shark": {
        "brand": "Shark Beauty",
        "domains": ["sharkninja.com", "sharkclean.com"],
        "retail_domains": ["ounass.com", "en-saudi.ounass.com", "almanea.sa"],
        "source_type": "brand_official",
    },
    "laifen": {
        "brand": "Laifen",
        "domains": ["laifen.sa"],
        "source_type": "brand_official",
    },
    "ghd": {
        "brand": "ghd",
        "domains": ["ghdhair.com"],
        "retail_domains": ["niceonesa.com", "en-saudi.ounass.com"],
        "source_type": "brand_official",
    },
    "revlon": {
        "brand": "Revlon",
        "domains": ["revlon.com"],
        "retail_domains": ["noon.com", "niceonesa.com"],
        "source_type": "authorized_retailer",
    },
}

# Which competitors are assigned to which Clara device format.
# The pipeline reads assignments per product; this is the default map.
ASSIGNMENT_BY_FORMAT = {
    "multi_styler": ["dyson", "shark"],
    "dryer": ["dyson", "laifen"],
    "air_brush": ["dyson", "revlon"],
    "hot_brush": ["revlon", "shark"],
    "auto_curler": ["dyson"],
    "straightener": ["ghd", "dyson"],
    "straightener_brush": ["dyson", "ghd"],
}


@dataclass
class RunConfig:
    run_id: str
    market: str = MARKET
    currency: str = CURRENCY

    # A stored match is refreshed, not re-discovered, inside this window.
    ttl_days: int = 30

    # An observation older than this is labelled stale rather than current.
    observation_stale_days: int = 7

    # Hard ceiling on candidate pages read per (product, competitor) pair.
    discovery_budget: int = 6

    # Classification thresholds. Format mismatch disqualifies regardless.
    confirm_threshold: float = 0.80
    probable_threshold: float = 0.60
    # Two candidates within this margin of each other cannot be separated.
    ambiguity_margin: float = 0.07

    # Change reporting: below this the move is recorded but not flagged.
    price_change_flag_pct: float = 5.0
    # Above this a price move is treated as implausible and escalated.
    price_sanity_pct: float = 60.0

    scope_product_ids: list[str] = field(default_factory=lambda: list(CLARA_DEVICE_IDS))
    competitors: dict = field(default_factory=lambda: dict(COMPETITORS))

    def allowed_hosts(self) -> set[str]:
        hosts: set[str] = set()
        for spec in self.competitors.values():
            hosts.update(spec.get("domains", []))
            hosts.update(spec.get("retail_domains", []))
        return hosts

    def source_type_for_host(self, host: str) -> str:
        host = host.lower().lstrip(".")
        for spec in self.competitors.values():
            for d in spec.get("domains", []):
                if host == d or host.endswith("." + d):
                    return "brand_official"
        for spec in self.competitors.values():
            for d in spec.get("retail_domains", []):
                if host == d or host.endswith("." + d):
                    return "marketplace_third_party"
        return "unknown"
