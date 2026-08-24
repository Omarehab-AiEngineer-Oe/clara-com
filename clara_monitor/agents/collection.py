"""Competitor Data Collection Agent.

Turns a competitor identity into a normalised profile: company, products,
pricing, features, target market, positioning, strengths, weaknesses and recent
changes. It collects only what is supported by evidence.

The prompt's hardest rule to keep honestly is *do not invent missing values, use
"unknown"* — because a profile with empty strings still reads as a complete
profile, and empty strings are exactly what a generator produces when it has
nothing. So this agent draws from three clearly separated wells and labels every
field with which one it came from:

* **observed** — read by the monitor from a real page, with a URL and a timestamp.
* **editorial** — written by a person in `competitor_profiles.py`. Genuine
  knowledge, but not something the Agent verified, so it can never be promoted
  above MEDIUM and is marked on the page as editorial.
* **unknown** — nothing established. Kept as the literal string, because the gap
  is itself intelligence: it tells the operator where to point the next run.

Pricing deserves its own note. Money is only ever copied from what a page printed,
never derived, never converted between currencies, and a range stays a range with
its own minimum and maximum rather than collapsing to a midpoint that no customer
can actually pay.
"""

from __future__ import annotations

import json
from decimal import Decimal

from .. import competitor_profiles as profiles
from ..money import to_decimal
from .base import Agent
from .contracts import (Confidence, CompetitorProfile, Evidence,
                        confidence_from_evidence, now_iso)

UNKNOWN = "unknown"


def _u(value) -> str:
    """Empty means not established, and says so."""
    v = (value or "")
    if isinstance(v, str):
        v = v.strip()
    return v if v else UNKNOWN


class CompetitorDataCollectionAgent(Agent):
    name = "competitor_data_collection"
    prompt_file = "competitor_data_collection.md"

    def run_rules(self, store, competitor_keys: list[str],
                  clara_products: list) -> list[CompetitorProfile]:
        registry = {c["key"]: c for c in store.get_competitors()}
        clara_by_id = {p.product_id: p for p in clara_products}
        out: list[CompetitorProfile] = []

        for key in competitor_keys:
            reg = registry.get(key)
            if not reg:
                self.report.skipped += 1
                continue

            observations = self._observations(store, key)
            matches = self._matches(store, key)
            evidence = self._evidence(observations)

            prof = CompetitorProfile(competitor=reg.get("brand") or key)
            prof.company = self._company(reg, key, observations)
            prof.products = self._products(observations, matches, clara_by_id)
            prof.pricing = self._pricing(observations)
            prof.features = self._features(observations)
            prof.target_customers = self._targets(key, reg)
            prof.positioning = self._positioning(key)
            prof.strengths, prof.weaknesses = self._swot(key, observations, matches)
            prof.recent_changes = self._recent_changes(store, key)
            prof.evidence = evidence
            prof.confidence = confidence_from_evidence(evidence)

            out.append(prof)

        self.report.items_in = len(competitor_keys)
        self.report.items_out = len(out)
        observed = sum(1 for p in out if p.evidence)
        self.report.note(
            f"{observed} of {len(out)} profiles have at least one observed page; "
            f"the rest are editorial only and capped at MEDIUM")
        return out

    # ---------------- sources ----------------

    def _observations(self, store, key: str) -> list[dict]:
        rows = store.db.execute(
            "SELECT payload FROM observation WHERE competitor_key=?", (key,)).fetchall()
        out = []
        for r in rows:
            try:
                out.append(json.loads(r["payload"]))
            except (ValueError, TypeError):
                continue
        return out

    def _matches(self, store, key: str) -> list[dict]:
        # `rejected` holds a JSON list of reasons rather than a flag, so an empty
        # list — not zero — is what "not rejected" looks like in this column.
        return [dict(r) for r in store.db.execute(
            "SELECT * FROM match WHERE competitor_key=? "
            "AND COALESCE(rejected,'[]') IN ('[]','','null')", (key,))]

    def _evidence(self, observations: list[dict]) -> list[Evidence]:
        ev, seen = [], set()
        for o in observations:
            url = o.get("canonical_url") or o.get("url") or ""
            if not url or url in seen:
                continue
            seen.add(url)
            host = url.split("/")[2] if "://" in url else url
            ev.append(Evidence(
                url=url, publisher=host,
                observed_at=o.get("observed_at") or "",
                kind=o.get("source_type") or "unknown",
                excerpt=(o.get("product_name") or "")[:200]))
        return ev

    # ---------------- sections ----------------

    def _company(self, reg: dict, key: str, observations: list[dict]) -> dict:
        p = profiles.get(key)
        doms = reg.get("domains")
        if isinstance(doms, str):
            try:
                doms = json.loads(doms)
            except (ValueError, TypeError):
                doms = [doms]
        return {
            "company_name": _u(reg.get("brand")),
            "domain": (doms or [UNKNOWN])[0] if doms else UNKNOWN,
            "all_domains": doms or [],
            "description": _u(p.positioning if p else ""),
            "description_source": "editorial" if p and p.positioning else "unknown",
            "market": _u(reg.get("market")),
            "origin": _u(p.origin if p else ""),
            "founded": _u(p.founded if p else ""),
            "ksa_presence": _u(p.ksa_presence if p else ""),
            "source_tier": _u(reg.get("tier")),
            "pages_read": len({o.get("canonical_url") for o in observations
                               if o.get("canonical_url")}),
        }

    def _products(self, observations: list[dict], matches: list[dict],
                  clara_by_id: dict) -> list[dict]:
        by_url: dict[str, dict] = {}
        for o in observations:
            url = o.get("canonical_url") or o.get("url")
            if not url:
                continue
            by_url[url] = {
                "product_name": _u(o.get("product_name")),
                "category": _u(o.get("category_path")),
                "url": url,
                "status": ("in_stock" if o.get("availability") == "in_stock"
                           else _u(o.get("availability"))),
                "sku": _u(o.get("sku")),
                "images": len(o.get("images") or []),
                "variants": o.get("variant_count") or 0,
                "observed_at": _u(o.get("observed_at")),
                "source": "observed",
            }
        for m in matches:
            url = m.get("competitor_url")
            if not url:
                continue
            entry = by_url.setdefault(url, {
                "product_name": _u(m.get("competitor_product_name")),
                "category": UNKNOWN, "url": url, "status": UNKNOWN,
                "sku": UNKNOWN, "images": 0, "variants": 0,
                "observed_at": UNKNOWN, "source": "matched",
            })
            clara = clara_by_id.get(m.get("clara_product_id"))
            entry.setdefault("competes_with", [])
            if clara and clara.name not in entry["competes_with"]:
                entry["competes_with"].append(clara.name)
            entry["match_status"] = m.get("status")
            entry["comparison_basis"] = m.get("comparison_basis")
        return list(by_url.values())

    def _pricing(self, observations: list[dict]) -> list[dict]:
        """Prices exactly as the page printed them.

        A range keeps both ends. A "from" price is flagged. Nothing is averaged,
        rounded or converted — those are all ways of producing a number no
        customer was ever shown.
        """
        rows = []
        for o in observations:
            price = o.get("selling_price")
            if price is None and not o.get("price_min"):
                continue
            rows.append({
                "product": _u(o.get("product_name")),
                "url": o.get("canonical_url") or o.get("url") or UNKNOWN,
                "currency": _u(o.get("currency")),
                "selling_price": price if price is not None else UNKNOWN,
                "regular_price": o.get("regular_price")
                if o.get("regular_price") is not None else UNKNOWN,
                "price_min": o.get("price_min") if o.get("price_min") is not None
                else UNKNOWN,
                "price_max": o.get("price_max") if o.get("price_max") is not None
                else UNKNOWN,
                "is_range": bool(o.get("price_is_range")),
                "is_from_price": bool(o.get("price_from")),
                "discount_percent": o.get("discount_percent")
                if o.get("discount_percent") is not None else UNKNOWN,
                "pricing_model": "one_off_purchase",
                "free_plan": "not_applicable",
                "trial": "not_applicable",
                "observed_at": _u(o.get("observed_at")),
                "source": "observed",
            })
        rows.sort(key=lambda r: (to_decimal(r["selling_price"]) or Decimal(0)),
                  reverse=True)
        return rows

    def _features(self, observations: list[dict]) -> list[dict]:
        """Only specifications the page actually stated.

        The monitor stores the product name and category rather than a spec
        sheet, so what is derivable here is thin and honest about it: format and
        variant count, plus whatever the page's own naming carries.
        """
        out, seen = [], set()
        for o in observations:
            name = o.get("product_name") or ""
            url = o.get("canonical_url") or o.get("url") or ""
            if not name or name in seen:
                continue
            seen.add(name)
            feats = []
            low = name.lower()
            for token, label in (
                    ("ionic", "ionic"), ("bldc", "BLDC motor"),
                    ("cordless", "cordless"), ("titanium", "titanium plates"),
                    ("ceramic", "ceramic plates"), ("tourmaline", "tourmaline"),
                    ("infrared", "infrared"), ("diffuser", "diffuser included"),
                    ("professional", "professional line")):
                if token in low:
                    feats.append(label)
            if o.get("variant_count"):
                feats.append(f"{o['variant_count']} purchasable variants")
            if feats:
                out.append({"product": name, "features": feats, "url": url,
                            "source": "observed",
                            "note": "read from the product page's own naming and "
                                    "variant data, not from a spec sheet"})
        return out

    def _targets(self, key: str, reg: dict) -> list[dict]:
        p = profiles.get(key)
        segs = reg.get("segments")
        if isinstance(segs, str):
            try:
                segs = json.loads(segs)
            except (ValueError, TypeError):
                segs = [segs]
        return [{
            "customer_segment": _u(p.audience if p else ""),
            "segment_source": "editorial" if p and p.audience else "unknown",
            "categories": segs or [],
            "geography": _u(reg.get("market")),
            "price_tier": _u(p.price_tier if p else ""),
            "typical_band_sar": _u(p.sar_band if p else ""),
        }]

    def _positioning(self, key: str) -> dict:
        p = profiles.get(key)
        if not p:
            return {"value_proposition": UNKNOWN, "marketing_angle": UNKNOWN,
                    "differentiation": UNKNOWN, "source": "unknown"}
        return {
            "value_proposition": _u(p.positioning),
            "marketing_angle": _u(", ".join(p.known_for)),
            "differentiation": _u(p.threat_note),
            "discount_habit": _u(p.discount_habit),
            "source": "editorial",
        }

    def _swot(self, key: str, observations: list[dict],
              matches: list[dict]) -> tuple[list[str], list[str]]:
        p = profiles.get(key)
        strengths, weaknesses = [], []
        if p:
            strengths.extend(p.known_for)
        priced = [o for o in observations if o.get("selling_price") is not None]
        if priced:
            strengths.append(
                f"Publishes a readable price on {len(priced)} page(s), so it can be "
                f"compared and shopped directly")
        blocked = [o for o in observations if o.get("errors")]
        if blocked:
            weaknesses.append(
                f"{len(blocked)} page(s) did not return clean data on the last run")
        unresolved = [m for m in matches if m.get("status") == "ambiguous"]
        if unresolved:
            weaknesses.append(
                f"{len(unresolved)} pairing(s) against Clara remain undecided")
        if not observations:
            weaknesses.append(
                "No page from this competitor has been read successfully, so "
                "everything above is editorial rather than observed")
        return strengths, weaknesses

    def _recent_changes(self, store, key: str) -> list[dict]:
        rows = store.db.execute(
            "SELECT * FROM change_log WHERE competitor_key=? ORDER BY rowid DESC "
            "LIMIT 25", (key,)).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            out.append({
                "type": d.get("change_type") or d.get("kind") or UNKNOWN,
                "field": d.get("field") or UNKNOWN,
                "from": d.get("old_value") if d.get("old_value") is not None else UNKNOWN,
                "to": d.get("new_value") if d.get("new_value") is not None else UNKNOWN,
                "at": d.get("detected_at") or d.get("observed_at") or UNKNOWN,
                "source": "observed",
            })
        return out

    def refine(self, result, store, competitor_keys, clara_products):
        """No model pass.

        Everything above is a copy of something already stored with its source
        attached. A model rewrite could only make it read better while making it
        less traceable, which is the wrong trade for a profile that feeds pricing
        decisions.
        """
        return None
