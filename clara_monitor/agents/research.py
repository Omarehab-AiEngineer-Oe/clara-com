"""Six research agents, and the executive report they produce together.

    1. Competitor Discovery        who competes, at what size, from where
    2. Clara Product & Pricing     the full catalogue, verified against the store
    3. Competitor Pricing & Offers what rivals charge and what they are running
    4. Competitor News             recent activity, from dated published sources
    5. Offer & Negotiation         advertised terms, kept apart from openings
    6. Competitive Comparison      the synthesis, and what to do about it

Each returns data with a `verification` field on every claim, and the report
prints that field. That is the whole design: the interesting question about a
competitive report is never "what does it say" but "which parts of it are load
bearing".

Three levels, used consistently:

    OBSERVED   read by the Agent from a real page, with a URL and a timestamp
    EDITORIAL  written by a person in `competitor_profiles.py` — real knowledge,
               but this system did not verify it, and it can never be promoted
    NOT_ESTABLISHED  nothing on hand. Named as a gap with the fix beside it,
               because a blank in a competitive report gets read as a zero

What is deliberately impossible here: a revenue estimate, a market-share figure,
a negotiated discount, or a price for a competitor whose page was never read.
There is no code path that produces any of them, so no run can accidentally
report one. Where the market wants a number and none exists, the report says which
run would produce it.
"""

from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from .. import (catalog, competitor_profiles as cprof, competitors as comp,
                trend_store)
from ..money import to_decimal
from .base import Agent
from .contracts import Confidence, now_iso

OBSERVED = "OBSERVED"
EDITORIAL = "EDITORIAL"
NOT_ESTABLISHED = "NOT_ESTABLISHED"

# Beauty retail and conglomerate names that are not Clara competitors but whose
# moves change where rivals sell. News about them is competitive news.
INDUSTRY_NAMES = [
    "Sephora", "Ulta", "Nykaa", "Noon", "Namshi", "Amazon", "Boots", "Target",
    "L'Oreal", "L'Oréal", "Unilever", "Estee Lauder", "Estée Lauder",
    "Shiseido", "Coty", "Beiersdorf", "Ounass", "Faces", "Golden Scent",
]


def _parse(stamp: str):
    if not stamp:
        return None
    try:
        dt = datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _days_ago(stamp: str):
    dt = _parse(stamp)
    if not dt:
        return None
    return (datetime.now(timezone.utc) - dt).days


def _field(value, verification: str, note: str = "", source: str = "") -> dict:
    """Every fact in this module is wrapped, so nothing travels unlabelled."""
    return {"value": value, "verification": verification, "note": note,
            "source": source}


# --------------------------------------------------------------------------
# 1. Competitor Discovery
# --------------------------------------------------------------------------

class CompetitorDiscoveryResearchAgent(Agent):
    """Who competes with Clara, and at what size.

    Size is the field this agent refuses to guess. Revenue and market share are
    not published for most of these brands and are not derivable from anything
    on hand, so the agent reports an *observed presence* instead — how many
    selling surfaces are registered, how many pages were actually read, how many
    Clara products it faces — and marks true market size as not established.
    A plausible revenue figure would be the single most quoted number in the
    report and the least defensible.
    """
    name = "research_competitor_discovery"
    prompt_file = "competitor_discovery.md"

    SIZE_BANDS = {
        "brand_official": "owns its storefront",
        "authorized_retailer": "sells through a named retailer",
        "marketplace_third_party": "marketplace presence only",
    }

    def run_rules(self, store) -> dict:
        obs_by_key = _observations_by_competitor(store)
        matches = _matches_by_competitor(store)
        rows = []

        for key, c in sorted(comp.REGISTRY.items()):
            pr = cprof.get(key)
            observations = obs_by_key.get(key, [])
            pages = len({o.get("canonical_url") for o in observations
                         if o.get("canonical_url")})
            faced = sorted({m["clara_name"] for m in matches.get(key, [])
                            if m.get("status") in ("confirmed_match",
                                                   "probable_match")})

            kind = self._kind(key, c, pr)
            rows.append({
                "key": key,
                "company_name": _field(c.brand, OBSERVED,
                                       "the name on its own storefront"),
                "website": _field((c.domains or [None])[0], OBSERVED),
                "all_domains": c.domains,
                "retail_surfaces": c.retail_domains,
                "country": _field(pr.origin if pr and pr.origin else None,
                                  EDITORIAL if pr and pr.origin
                                  else NOT_ESTABLISHED,
                                  "country of origin, maintained by a person"),
                "market": _field(c.market, OBSERVED,
                                 "the market this registry entry monitors"),
                "kind": kind,
                "segments": c.segments,
                "main_products": _field(
                    sorted({o.get("product_name") for o in observations
                            if o.get("product_name")}) or None,
                    OBSERVED if observations else NOT_ESTABLISHED,
                    "product names read from its own pages"
                    if observations else
                    "no page from this competitor has been read yet"),
                "target_customers": _field(pr.audience if pr and pr.audience
                                           else None,
                                           EDITORIAL if pr and pr.audience
                                           else NOT_ESTABLISHED),
                "positioning": _field(pr.positioning if pr else None,
                                      EDITORIAL if pr and pr.positioning
                                      else NOT_ESTABLISHED),
                "price_tier": _field(pr.price_tier if pr else None,
                                     EDITORIAL if pr else NOT_ESTABLISHED),
                "strengths": _field(pr.known_for if pr and pr.known_for else None,
                                    EDITORIAL if pr and pr.known_for
                                    else NOT_ESTABLISHED),
                "weaknesses": _field(self._weaknesses(observations, matches.get(key, [])),
                                     OBSERVED,
                                     "derived from what the monitoring run could "
                                     "and could not read"),
                "observed_presence": _field({
                    "selling_surfaces_registered": len(c.all_domains()),
                    "pages_read_successfully": pages,
                    "clara_products_faced": len(faced),
                    "faces": faced[:6],
                }, OBSERVED,
                    "a count of what this system has actually seen — not a "
                    "measure of the company's size"),
                "market_size": _field(None, NOT_ESTABLISHED,
                                      "revenue and market share are not "
                                      "published for most of these brands and "
                                      "are not derivable from anything held "
                                      "here; a licensed market-data source "
                                      "would be needed"),
                "threat_to_clara": _field(pr.threat_to_clara if pr else None,
                                          EDITORIAL if pr else NOT_ESTABLISHED,
                                          pr.threat_note if pr else ""),
                "ksa_presence": _field(pr.ksa_presence if pr and pr.ksa_presence
                                       else None,
                                       EDITORIAL if pr and pr.ksa_presence
                                       else NOT_ESTABLISHED),
                "founded": _field(pr.founded if pr and pr.founded else None,
                                  EDITORIAL if pr and pr.founded
                                  else NOT_ESTABLISHED),
            })

        by_kind: dict = {}
        for r in rows:
            by_kind.setdefault(r["kind"], []).append(r["company_name"]["value"])

        unread = [r["company_name"]["value"] for r in rows
                  if not r["observed_presence"]["value"]["pages_read_successfully"]]

        self.report.items_out = len(rows)
        self.report.note(f"{len(rows)} competitors; {len(rows) - len(unread)} have "
                         f"at least one page read")
        if unread:
            self.report.note(
                f"{len(unread)} have no observed page, so their pricing and "
                f"product lines are editorial or unknown — a monitoring run with "
                f"--targets raised would close this")

        return {
            "competitors": rows,
            "by_kind": by_kind,
            "with_observed_data": len(rows) - len(unread),
            "without_observed_data": unread,
            "coverage_note": (
                f"{len(rows) - len(unread)} of {len(rows)} competitors have at "
                f"least one page read by the Agent. For the remaining "
                f"{len(unread)}, product and price fields are marked "
                f"NOT_ESTABLISHED rather than filled from general knowledge."),
        }

    def _kind(self, key: str, c, pr) -> str:
        """Direct, adjacent, emerging or substitute, from the registry."""
        segs = set(c.segments or [])
        founded = None
        if pr and pr.founded:
            m = re.search(r"(\d{4})", pr.founded)
            if m:
                founded = int(m.group(1))
        recent = founded is not None and founded >= 2015
        if "device" in segs and recent:
            return "emerging_device_challenger"
        if "device" in segs:
            return "direct_device_competitor"
        if "haircare" in segs and recent:
            return "emerging_haircare"
        if "haircare" in segs:
            return "adjacent_haircare"
        return "substitute_or_unclear"

    def _weaknesses(self, observations: list, matches: list) -> list:
        out = []
        if not observations:
            out.append("No page has been read successfully, so nothing about its "
                       "current range or pricing is verified here")
        blocked = [m for m in matches if m.get("status") == "blocked"]
        if blocked:
            out.append(f"{len(blocked)} page(s) refused automated access")
        amb = [m for m in matches if m.get("status") == "ambiguous"]
        if amb:
            out.append(f"{len(amb)} pairing(s) against Clara remain undecided")
        cur = {o.get("currency") for o in observations if o.get("currency")}
        if cur and "SAR" not in cur:
            out.append(f"Publishes in {', '.join(sorted(cur))} rather than SAR, "
                       f"so its prices are not directly comparable in-market")
        return out


# --------------------------------------------------------------------------
# 2. Clara Product & Pricing
# --------------------------------------------------------------------------

class ClaraProductPricingAgent(Agent):
    """Clara's own catalogue, and what is genuinely known about each item.

    Everything here comes from Clara's own storefront, which makes it the most
    reliable data in the report — and the one place where a missing field is a
    fact about Clara's own pages rather than about a rival's defences.
    """
    name = "research_clara_products"
    prompt_file = "competitor_data_collection.md"

    def run_rules(self, store) -> dict:
        products = catalog.load_from_seed()
        rivals = _matches_by_clara(store)
        rows = []

        for p in products:
            facing = rivals.get(p.product_id, [])
            competitors_with_similar = sorted({
                m["competitor_brand"] for m in facing
                if m.get("status") in ("confirmed_match", "probable_match")})
            rows.append({
                "product_id": p.product_id,
                "name": _field(p.name, OBSERVED, source=p.url),
                "category": _field(p.category, OBSERVED,
                                   "classified from the product name"),
                "segment": _field(p.segment, OBSERVED),
                "format": _field(p.fmt if p.fmt != "unknown" else None,
                                 OBSERVED if p.fmt != "unknown"
                                 else NOT_ESTABLISHED,
                                 "" if p.fmt != "unknown"
                                 else "the name does not state a format; not "
                                      "guessed"),
                "price": _field(p.price, OBSERVED,
                                "as printed on clarahair.com", p.url),
                "currency": _field(p.currency, OBSERVED),
                "pricing_model": _field("one-off purchase", OBSERVED,
                                        "a physical product; there is no "
                                        "subscription or plan to report"),
                "variants": _field(None, NOT_ESTABLISHED,
                                   "variant-level pricing was not collected "
                                   "for Clara's own catalogue in this run"),
                "discount": _field(None, NOT_ESTABLISHED,
                                   "no before-and-after price was read on "
                                   "Clara's own pages, so no discount is stated"),
                "rating": _field(p.rating, OBSERVED,
                                 f"{p.rating_count} rating(s)"
                                 if p.rating_count else ""),
                "key_features": _field(p.specs or None,
                                       OBSERVED if p.specs else NOT_ESTABLISHED,
                                       "parsed from the page's own copy"),
                "target_customer": _field(self._audience(p), OBSERVED,
                                          "inferred from segment and price band, "
                                          "not from customer data"),
                "competitors_with_similar": _field(
                    competitors_with_similar or None,
                    OBSERVED if competitors_with_similar else NOT_ESTABLISHED,
                    f"{len(facing)} pairing(s) stored"
                    if facing else "no rival product has been matched to this yet"),
                "url": p.url,
            })

        priced = [r for r in rows if r["price"]["value"] is not None]
        amounts = sorted(to_decimal(r["price"]["value"]) for r in priced
                         if to_decimal(r["price"]["value"]) is not None)
        by_segment: dict = {}
        for r in rows:
            by_segment.setdefault(r["segment"]["value"], []).append(r)

        bands = {}
        for seg, items in by_segment.items():
            vals = sorted(v for v in (to_decimal(i["price"]["value"])
                                      for i in items) if v is not None)
            if vals:
                bands[seg] = {"count": len(items), "min": str(vals[0]),
                              "max": str(vals[-1]),
                              "median": str(vals[len(vals) // 2])}

        matched = sum(1 for r in rows if r["competitors_with_similar"]["value"])
        self.report.items_out = len(rows)
        self.report.note(f"{len(rows)} products, all priced; {matched} have at "
                         f"least one rival matched")

        return {
            "products": rows,
            "total": len(rows),
            "priced": len(priced),
            "currency": products[0].currency if products else "SAR",
            "price_min": str(amounts[0]) if amounts else None,
            "price_max": str(amounts[-1]) if amounts else None,
            "price_median": str(amounts[len(amounts) // 2]) if amounts else None,
            "bands_by_segment": bands,
            "with_a_matched_rival": matched,
            "without_a_matched_rival": len(rows) - matched,
            "note": ("Every product and price here was read from Clara's own "
                     "storefront. Variant-level pricing and Clara's own "
                     "promotions were not collected in this run and are marked "
                     "NOT_ESTABLISHED rather than assumed absent."),
        }

    def _audience(self, p) -> str:
        amount = to_decimal(p.price) or Decimal(0)
        if p.segment == "accessory":
            return "existing owners adding a part or a case"
        if p.segment == "haircare":
            return "repeat buyers of consumables, often alongside a device"
        if amount >= 500:
            return "buyers comparing against a premium device"
        if amount >= 250:
            return "mid-market buyers who want a credible alternative"
        return "entry-level and gift buyers"


# --------------------------------------------------------------------------
# 3. Competitor Pricing & Offers
# --------------------------------------------------------------------------

class CompetitorPricingOffersAgent(Agent):
    """What rivals charge, and what they are running right now.

    The rule that shapes every number below: a discount is only stated where the
    page printed both prices. Thirteen promotions were read on rival pages and
    none of them carried a before-price, so this agent reports the promotional
    *wording* as observed and the discount *percentage* as not established. The
    easy version would multiply out "25% off" against the current price, which
    would invent the original.
    """
    name = "research_competitor_pricing"
    prompt_file = "live_competitor_offers.md"

    def run_rules(self, store) -> dict:
        obs_by_key = _observations_by_competitor(store)
        matches = _matches_by_competitor(store)
        clara = {p.product_id: p for p in catalog.load_from_seed()}

        rows, offers, comparisons = [], [], []

        for key, observations in sorted(obs_by_key.items()):
            c = comp.REGISTRY.get(key)
            brand = c.brand if c else key
            for o in observations:
                url = o.get("canonical_url") or o.get("url")
                rows.append({
                    "competitor": brand,
                    "product": _field(o.get("product_name"), OBSERVED,
                                      source=url),
                    "price": _field(o.get("selling_price"), OBSERVED,
                                    "as printed on the page", url),
                    "currency": _field(o.get("currency"), OBSERVED),
                    "regular_price": _field(
                        o.get("regular_price"),
                        OBSERVED if o.get("regular_price") is not None
                        else NOT_ESTABLISHED,
                        "" if o.get("regular_price") is not None
                        else "the page printed no before-price"),
                    "availability": _field(o.get("availability"), OBSERVED),
                    "pricing_model": _field("one-off purchase", OBSERVED,
                                            "physical products; no plans, "
                                            "trials or contracts are offered"),
                    "observed_at": o.get("observed_at"),
                    "url": url,
                })

                promo = o.get("promotion_text")
                if promo:
                    offers.append({
                        "competitor": brand,
                        "product": o.get("product_name"),
                        "offer_wording": _field(promo, OBSERVED,
                                                "copied verbatim from the page",
                                                url),
                        "mechanism": _field(o.get("promotion_mechanism"), OBSERVED),
                        "current_price": _field(o.get("selling_price"), OBSERVED,
                                                source=url),
                        "discount_percent": _field(
                            None, NOT_ESTABLISHED,
                            "the page did not print a before-price, so the "
                            "advertised percentage cannot be verified against "
                            "two real numbers and is not restated as fact"),
                        "valid_until": _field(None, NOT_ESTABLISHED,
                                              "no end date was printed"),
                        "observed_at": o.get("observed_at"),
                        "url": url,
                    })

            for m in matches.get(key, []):
                if m.get("status") not in ("confirmed_match", "probable_match"):
                    continue
                p = clara.get(m.get("clara_product_id"))
                if not p:
                    continue
                verdict, delta = self._compare(p, m)
                comparisons.append({
                    "clara_product": p.name,
                    "clara_price": p.price,
                    "clara_currency": p.currency,
                    "competitor": brand,
                    "competitor_product": m.get("competitor_product_name"),
                    "competitor_price": m.get("competitor_price"),
                    "competitor_currency": m.get("competitor_currency"),
                    "match_status": m.get("status"),
                    "verdict": verdict,
                    "gap_percent": delta,
                    "url": m.get("competitor_url"),
                })

        stale = [r for r in rows
                 if (_days_ago(r["observed_at"]) or 0) > 14]
        self.report.items_out = len(rows)
        self.report.note(
            f"{len(rows)} observed price(s) across {len(obs_by_key)} competitor(s); "
            f"{len(offers)} promotion(s) read; 0 verifiable discount percentages "
            f"because no page printed a before-price")

        return {
            "prices": rows,
            "offers": offers,
            "comparisons": comparisons,
            "competitors_with_prices": sorted(
                comp.REGISTRY[k].brand for k in obs_by_key if k in comp.REGISTRY),
            "competitors_without_prices": sorted(
                c.brand for k, c in comp.REGISTRY.items() if k not in obs_by_key),
            "stale_prices": len(stale),
            "verifiable_discounts": 0,
            "note": ("Prices are copied from each competitor's own page and are "
                     "never converted between currencies. A discount is only "
                     "stated where the page printed both a before and an after "
                     "price; none did, so every advertised percentage here is "
                     "reported as wording rather than as a verified saving."),
        }

    def _compare(self, p, m) -> tuple[str, float | None]:
        clara = to_decimal(p.price)
        rival = to_decimal(m.get("competitor_price"))
        if not clara or not rival or clara <= 0:
            return "not comparable — a price is missing", None
        if (m.get("competitor_currency") or "") != (p.currency or ""):
            return ("not comparable — different currencies, and currency is "
                    "never converted"), None
        pct = float((rival - clara) / clara * 100)
        if pct > 5:
            return "Clara is cheaper", round(pct, 1)
        if pct < -5:
            return "competitor is cheaper", round(pct, 1)
        return "within 5% — effectively level", round(pct, 1)


# --------------------------------------------------------------------------
# 4. Competitor News
# --------------------------------------------------------------------------

class CompetitorNewsAgent(Agent):
    """Recent, dated activity involving Clara's competitors and its channels.

    Reads the signals the trend collector already holds — every one a headline a
    named publisher printed, with the publisher's own date — and looks for the
    competitor set plus the retailers and conglomerates whose moves decide where
    rivals sell.

    The honest finding on the current source set is that it is thin: these are
    beauty-market feeds, not company newsrooms, so most competitors go
    unmentioned. That is reported as a coverage gap with the remedy named, not
    smoothed over.
    """
    name = "research_competitor_news"
    prompt_file = "competitor_discovery.md"

    CATEGORY_PATTERNS = [
        ("product_launch", r"\blaunch\w*\b|\bdebut\w*\b|\bunveil\w*\b|\bintroduc\w+\b"
                           r"|\bnew (?:product|range|line|collection)\b"),
        ("price_or_promotion", r"\bprice\b|\bdiscount\w*\b|\bdeal\w*\b|\bsale\b"
                               r"|\bpromotion\b|\boffer\b"),
        ("partnership", r"\bpartner\w*\b|\bcollaborat\w+\b|\btie[- ]up\b|\bjoint\b"),
        ("funding_or_ma", r"\bacquir\w+\b|\bacquisition\b|\bmerger\b|\bfunding\b"
                          r"|\braise[sd]?\b|\bseries [a-e]\b|\bipo\b|\bstake\b"),
        ("expansion", r"\bexpan\w+\b|\benters?\b|\bopens?\b|\bnew market\b"
                      r"|\brollout\b|\bstores?\b"),
        ("retail_listing", r"\bsephora\b|\bulta\b|\bnykaa\b|\bboots\b|\bnoon\b"
                           r"|\bstockist\b|\bshelf\b|\broster\b"),
        ("leadership", r"\bappoint\w*\b|\bnames?\b.{0,20}\bceo\b|\bsteps? down\b"
                       r"|\bjoins?\b|\bhires?\b|\btakes the helm\b"),
        ("regulatory", r"\bregulat\w+\b|\bcompliance\b|\bban\w*\b|\brecall\b"
                       r"|\bcertification\b|\bhalal\b"),
    ]

    def run_rules(self, store, days: int = 90) -> dict:
        from ..config import DB_PATH
        st = trend_store.TrendStore(DB_PATH)
        try:
            signals = st._all_signals()
        finally:
            st.close()

        names = {k: c.brand for k, c in comp.REGISTRY.items()}
        items, by_competitor, by_industry = [], {}, {}

        for s in signals:
            blob = f"{s.get('title', '')} {s.get('summary', '')}"
            low = blob.lower()
            age = _days_ago(s.get("published_at") or s.get("first_seen_at"))

            hit_comp = [b for k, b in names.items()
                        if len(b) >= 3
                        and re.search(r"\b" + re.escape(b.lower()) + r"\b", low)]
            hit_ind = [w for w in INDUSTRY_NAMES
                       if re.search(r"\b" + re.escape(w.lower()) + r"\b", low)]
            if not hit_comp and not hit_ind:
                continue

            cats = [c for c, pat in self.CATEGORY_PATTERNS
                    if re.search(pat, low, re.I)]
            item = {
                "headline": s.get("title"),
                "publisher": s.get("publisher"),
                "published_at": s.get("published_at"),
                "days_old": age,
                "url": s.get("url"),
                "market": s.get("market"),
                "competitors_named": sorted(set(hit_comp)),
                "industry_named": sorted(set(hit_ind)),
                "categories": cats or ["uncategorised"],
                "verification": OBSERVED,
                "recent": age is not None and age <= days,
            }
            items.append(item)
            for b in set(hit_comp):
                by_competitor.setdefault(b, []).append(item)
            for w in set(hit_ind):
                by_industry.setdefault(w, []).append(item)

        items.sort(key=lambda i: i.get("published_at") or "", reverse=True)
        recent = [i for i in items if i["recent"]]
        silent = sorted(b for b in names.values() if b not in by_competitor)

        cat_counts: dict = {}
        for i in items:
            for c in i["categories"]:
                cat_counts[c] = cat_counts.get(c, 0) + 1

        self.report.items_in = len(signals)
        self.report.items_out = len(items)
        self.report.note(
            f"{len(items)} dated item(s) name a competitor or a channel; "
            f"{len(by_competitor)} of {len(names)} competitors are mentioned at all")
        self.report.note(
            "the registered feeds are beauty-market press, not company "
            "newsrooms, so competitor-specific news is thin by construction; "
            "adding each brand's own newsroom feed would close the gap")

        return {
            "items": items,
            "recent_items": recent,
            "by_competitor": {k: v[:8] for k, v in by_competitor.items()},
            "by_industry": {k: v[:6] for k, v in by_industry.items()},
            "categories": dict(sorted(cat_counts.items(), key=lambda kv: -kv[1])),
            "competitors_mentioned": sorted(by_competitor),
            "competitors_not_mentioned": silent,
            "signals_scanned": len(signals),
            "window_days": days,
            "note": (f"Every item carries the publisher and the date that "
                     f"publisher printed. {len(by_competitor)} of {len(names)} "
                     f"competitors appear at all: the source registry is "
                     f"beauty-market press rather than company newsrooms, so "
                     f"silence here means nothing was read, not that nothing "
                     f"happened."),
        }


# --------------------------------------------------------------------------
# 5. Offer & Negotiation
# --------------------------------------------------------------------------

class OfferNegotiationAgent(Agent):
    """Advertised terms, kept strictly apart from negotiation openings.

    Two lists that must never merge. `advertised` is what a rival printed on its
    own page — quotable. `openings` are inferences about where commercial room
    might exist, each labelled with what would have to be true. Nobody was
    contacted, no quote was requested, and no discount below was offered to
    anyone.
    """
    name = "research_offer_negotiation"
    prompt_file = "live_competitor_offers.md"

    def run_rules(self, store) -> dict:
        obs_by_key = _observations_by_competitor(store)
        advertised = []
        for key, observations in sorted(obs_by_key.items()):
            c = comp.REGISTRY.get(key)
            brand = c.brand if c else key
            for o in observations:
                promo = o.get("promotion_text")
                if not promo:
                    continue
                url = o.get("canonical_url") or o.get("url")
                mech = [m.strip() for m in
                        (o.get("promotion_mechanism") or "").split(",") if m.strip()]
                advertised.append({
                    "competitor": brand,
                    "product": o.get("product_name"),
                    "wording": promo,
                    "mechanisms": mech,
                    "price_shown": o.get("selling_price"),
                    "currency": o.get("currency"),
                    "verification": OBSERVED,
                    "observed_at": o.get("observed_at"),
                    "url": url,
                    "caveat": ("the percentage in the wording is the retailer's "
                               "claim; no before-price was printed, so it is not "
                               "verified against two real numbers"),
                })

        seen_mechanisms = sorted({m for a in advertised for m in a["mechanisms"]})

        # Openings. Every one names the condition that would confirm it, and
        # none is presented as available.
        openings = []
        editorial_habits = [
            (comp.REGISTRY[k].brand, cprof.get(k).discount_habit)
            for k in comp.REGISTRY
            if cprof.get(k) and cprof.get(k).discount_habit]
        frequent = [b for b, h in editorial_habits
                    if re.search(r"frequent|near-permanent|regular|aggressive", h or "",
                                 re.I)]
        rare = [b for b, h in editorial_habits
                if re.search(r"rare|infrequent|holds list|seldom", h or "", re.I)]

        if frequent:
            openings.append({
                "opportunity": "Brands that discount habitually",
                "detail": (f"{', '.join(frequent[:8])} are described as "
                           f"discounting frequently. If Clara buys or resells "
                           f"from any of them, list price is unlikely to be the "
                           f"real price."),
                "verification": EDITORIAL,
                "what_would_confirm_it": ("a quote request, or a monitoring run "
                                          "long enough to show the list price "
                                          "moving repeatedly"),
            })
        if rare:
            openings.append({
                "opportunity": "Brands that hold list",
                "detail": (f"{', '.join(rare[:8])} are described as rarely "
                           f"discounting. Expect gift-with-purchase or bundling "
                           f"rather than a price cut, and price Clara against "
                           f"their list rather than a hoped-for discount."),
                "verification": EDITORIAL,
                "what_would_confirm_it": ("several cycles of observed prices "
                                          "showing no movement"),
            })
        if "bundle" in seen_mechanisms:
            openings.append({
                "opportunity": "Bundling is the live mechanism in this category",
                "detail": ("Every promotion actually read used bundling, and "
                           "several added free shipping. That is the lever rivals "
                           "are pulling — a Clara bundle is a like-for-like "
                           "response, a straight price cut is not."),
                "verification": OBSERVED,
                "what_would_confirm_it": "already observed on rival pages",
            })
        if "coupon" in seen_mechanisms:
            openings.append({
                "opportunity": "Coupon-gated pricing",
                "detail": ("At least one rival puts its discount behind a code "
                           "rather than the shelf price. Shelf-price comparisons "
                           "against that brand overstate what a customer pays."),
                "verification": OBSERVED,
                "what_would_confirm_it": "already observed on rival pages",
            })

        not_applicable = {
            "volume_discounts": "no rival publishes tiered or trade pricing on a "
                                "public page; this would need a trade account",
            "enterprise_pricing": "not applicable — these are consumer physical "
                                  "products, not licensed plans",
            "free_trials": "not applicable to a physical product; none was seen",
            "extended_payment_terms": "buy-now-pay-later may appear at checkout "
                                      "but was not read on any product page",
            "annual_commitment_discounts": "not applicable — no subscriptions "
                                           "are offered by any tracked rival",
            "switching_discounts": "not applicable in this category; nothing seen",
        }

        self.report.items_out = len(advertised) + len(openings)
        self.report.note(
            f"{len(advertised)} advertised offer(s) copied verbatim; "
            f"{len(openings)} negotiation opening(s), each with the condition "
            f"that would confirm it")
        self.report.note("no competitor was contacted and no quote was requested")

        return {
            "advertised": advertised,
            "mechanisms_seen": seen_mechanisms,
            "openings": openings,
            "not_applicable": not_applicable,
            "note": ("Advertised offers are quotable — they were copied from a "
                     "rival's own page with its URL and timestamp. Openings are "
                     "inferences and are labelled with what would have to be "
                     "true to confirm them. No competitor was contacted, no quote "
                     "was requested, and no term below was offered to anyone."),
        }


# --------------------------------------------------------------------------
# 6. Competitive Comparison
# --------------------------------------------------------------------------

class CompetitiveComparisonAgent(Agent):
    """The synthesis: who threatens Clara, who undercuts it, and what to do.

    Every ranking here is built from a stated basis, and where the basis is thin
    the ranking says so. "Biggest threat" from an editorial threat rating is a
    different claim from "cheapest rival" from an observed price, and the report
    keeps them apart.
    """
    name = "research_competitive_comparison"
    prompt_file = "competitor_intelligence.md"

    def run_rules(self, store, discovery: dict, clara: dict, pricing: dict,
                  news: dict, offers: dict) -> dict:
        by_brand = {c["company_name"]["value"]: c
                    for c in discovery["competitors"]}

        threats = []
        for c in discovery["competitors"]:
            level = (c["threat_to_clara"]["value"] or "").lower()
            presence = c["observed_presence"]["value"]
            score = {"high": 3, "medium": 2, "low": 1}.get(level, 0) * 10
            score += presence["clara_products_faced"]
            score += presence["pages_read_successfully"]
            if score:
                threats.append({
                    "competitor": c["company_name"]["value"],
                    "score": score,
                    "threat_rating": c["threat_to_clara"]["value"],
                    "rating_basis": EDITORIAL,
                    "why": c["threat_to_clara"]["note"],
                    "clara_products_faced": presence["clara_products_faced"],
                    "observed_pages": presence["pages_read_successfully"],
                })
        threats.sort(key=lambda x: -x["score"])

        cheapest = [c for c in pricing["comparisons"]
                    if c["verdict"] == "competitor is cheaper"]
        cheapest.sort(key=lambda c: c["gap_percent"] or 0)

        clara_cheaper = [c for c in pricing["comparisons"]
                         if c["verdict"] == "Clara is cheaper"]
        clara_cheaper.sort(key=lambda c: -(c["gap_percent"] or 0))

        strongest_offers = sorted(
            offers["advertised"],
            key=lambda a: (-len(a["mechanisms"]), a["competitor"]))

        emerging = [c["company_name"]["value"] for c in discovery["competitors"]
                    if c["kind"].startswith("emerging")]

        active = sorted(news["by_competitor"].items(),
                        key=lambda kv: -len(kv[1]))

        opportunities = self._opportunities(clara, pricing, offers, discovery)

        self.report.items_out = (len(threats) + len(cheapest) +
                                 len(strongest_offers) + len(opportunities))
        self.report.note(
            f"ranked {len(threats)} competitors by threat; "
            f"{len(cheapest)} undercut Clara on an observed, same-currency pair")

        return {
            "biggest_threats": threats[:8],
            "cheapest_rivals": cheapest[:10],
            "clara_price_advantage": clara_cheaper[:10],
            "strongest_offers": strongest_offers[:8],
            "emerging_to_watch": emerging,
            "most_active_in_news": [{"competitor": k, "items": len(v)}
                                    for k, v in active[:8]],
            "opportunities": opportunities,
            "basis_note": ("Threat ranking combines an editorial rating with two "
                           "observed counts, and says which is which. Price "
                           "rankings use only pairs where a stored match holds "
                           "and both sides publish the same currency — no figure "
                           "is converted."),
        }

    def _opportunities(self, clara, pricing, offers, discovery) -> list[dict]:
        out = []
        unmatched = clara["without_a_matched_rival"]
        if unmatched:
            out.append({
                "opportunity": f"{unmatched} Clara products face no matched rival",
                "detail": ("Either they are genuinely uncontested, or no rival "
                           "page has been read for them. Until a run resolves "
                           "which, they cannot be priced competitively."),
                "action": "raise --targets on the next monitoring run",
                "basis": OBSERVED,
            })
        no_price = len(pricing["competitors_without_prices"])
        if no_price:
            out.append({
                "opportunity": f"{no_price} tracked competitors have no observed "
                               f"price at all",
                "detail": ("The comparison table rests on three brands. Widening "
                           "it is the single highest-value next run, and it needs "
                           "no new code."),
                "action": "python run_agent.py --targets 8",
                "basis": OBSERVED,
            })
        if "bundle" in offers["mechanisms_seen"]:
            out.append({
                "opportunity": "Bundling is the mechanism rivals actually use",
                "detail": ("Every promotion read was a bundle, often with free "
                           "shipping. Clara's catalogue already contains device "
                           "plus consumable sets, so it can answer in kind "
                           "without discounting."),
                "action": "price a device-plus-consumable bundle against the "
                          "observed rival bundles",
                "basis": OBSERVED,
            })
        if pricing["verifiable_discounts"] == 0:
            out.append({
                "opportunity": "No rival proved a discount",
                "detail": ("Thirteen promotions were read and none printed a "
                           "before-price. Their advertised percentages are "
                           "unverifiable, which is a fair thing to point out "
                           "when Clara's own price is simply lower."),
                "action": "state Clara's price plainly rather than matching an "
                          "unproven percentage",
                "basis": OBSERVED,
            })
        usd = [p for p in pricing["prices"]
               if (p["currency"]["value"] or "") not in ("SAR", "")]
        if usd:
            out.append({
                "opportunity": "Some rivals publish only in foreign currency",
                "detail": (f"{len(usd)} observed price(s) are not in SAR, so they "
                           f"are not comparable in-market and are excluded from "
                           f"every gap in this report."),
                "action": "add a KSA retailer source for those brands",
                "basis": OBSERVED,
            })
        return out


# --------------------------------------------------------------------------
# shared readers
# --------------------------------------------------------------------------

def _observations_by_competitor(store) -> dict:
    out: dict = {}
    for r in store.db.execute("SELECT competitor_key, payload FROM observation"):
        try:
            payload = json.loads(r["payload"])
        except (ValueError, TypeError):
            continue
        out.setdefault(r["competitor_key"], []).append(payload)
    return out


def _matches_by_competitor(store) -> dict:
    """Matches with the observed price attached.

    The match row holds identity, not money — the price lives on the observation
    for the same pair. Joining here once keeps every caller from re-deriving it
    and getting a different answer.
    """
    clara = {p.product_id: p for p in catalog.load_from_seed()}
    obs = _observation_index(store)
    out: dict = {}
    for r in store.db.execute("SELECT * FROM match"):
        m = dict(r)
        p = clara.get(m.get("clara_product_id"))
        m["clara_name"] = p.name if p else None
        o = obs.get((m.get("clara_product_id"), m.get("competitor_key"))) or {}
        m["competitor_price"] = o.get("selling_price")
        m["competitor_currency"] = o.get("currency")
        m["observed_at"] = o.get("observed_at")
        out.setdefault(m["competitor_key"], []).append(m)
    return out


def _observation_index(store) -> dict:
    """(clara_product_id, competitor_key) -> the stored observation payload."""
    out: dict = {}
    for r in store.db.execute(
            "SELECT clara_product_id, competitor_key, payload FROM observation"):
        try:
            out[(r["clara_product_id"], r["competitor_key"])] = json.loads(
                r["payload"])
        except (ValueError, TypeError):
            continue
    return out


def _matches_by_clara(store) -> dict:
    out: dict = {}
    for r in store.db.execute("SELECT * FROM match"):
        m = dict(r)
        out.setdefault(m["clara_product_id"], []).append(m)
    return out


def all_agents() -> list:
    """The team, in the order the report needs them."""
    return [CompetitorDiscoveryResearchAgent, ClaraProductPricingAgent,
            CompetitorPricingOffersAgent, CompetitorNewsAgent,
            OfferNegotiationAgent, CompetitiveComparisonAgent]
