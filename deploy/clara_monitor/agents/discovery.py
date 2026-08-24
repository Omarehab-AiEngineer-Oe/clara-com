"""Competitor Discovery Agent.

Its only job is to surface competitors that are missing, newly relevant or newly
emerging — not to restate the ones already known. The prompt is explicit that a
company mentioned somewhere is not a competitor: there has to be a reasonable
competitive relationship, and a weak similarity is not direct competition.

Four discovery routes, ordered by how much each one actually proves:

1. **Brands already in collected evidence.** Every page the monitor read carries a
   `brand` in its structured data. A brand appearing there that is not in the
   registry is a real find backed by a URL the Agent genuinely fetched — the
   strongest and cheapest route, because the evidence already exists.
2. **Brand index pages** on hosts the allowlist already covers, read through the
   single guarded path with robots respected. Hosts that refuse are recorded as
   blocked and handed to a person; nothing is worked around.
3. **Adjacent brands in a competitor's own catalogue** — a retailer listing a
   hair-tool brand Clara does not track is that brand competing for the same
   shelf.
4. **The model with search**, when Vertex is reachable. This is the only route
   that can find a company nobody has read a page from yet, and when the model is
   unavailable the agent says so rather than returning a thin list as if the
   market had been swept.

Every candidate carries where it came from, so a reader can tell a brand found in
a fetched page from one the model proposed.
"""

from __future__ import annotations

import json
import re

from .. import access, competitors as comp, extract
from .base import Agent
from .contracts import (Confidence, DiscoveryCandidate, DiscoveryStatus,
                        Evidence, confidence_from_evidence, now_iso)
from .identity import DIFFERENT, POSSIBLE, SAME, compare, identity_key, normalise_name

# What makes a brand relevant to Clara at all. A company has to sell into one of
# these to be a competitor rather than merely a company that exists.
DEVICE_WORDS = ("hair dryer", "blow dry", "blowdry", "straightener", "flat iron",
                "curler", "curling", "styler", "styling", "hot brush", "air brush",
                "airstyler", "diffuser", "hair tool")
CARE_WORDS = ("shampoo", "conditioner", "hair mask", "hair oil", "serum",
              "treatment", "scalp", "keratin", "bond repair", "haircare")

TYPE_DIRECT = "direct"
TYPE_INDIRECT = "indirect"
TYPE_EMERGING = "emerging"
TYPE_NEW_ENTRANT = "new_entrant"
TYPE_COMPETITOR_PRODUCT = "competitor_product"
TYPE_SUBSTITUTE = "substitute"

CANDIDATE_SCHEMA = {
    "type": "object",
    "properties": {
        "candidates": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "competitor_name": {"type": "string"},
                    "domain": {"type": "string"},
                    "type": {"type": "string"},
                    "relevant_products": {"type": "array", "items": {"type": "string"}},
                    "target_customer": {"type": "string"},
                    "why_competitive": {"type": "string"},
                    "confidence": {"type": "string"},
                    "status": {"type": "string"},
                },
                "required": ["competitor_name", "why_competitive", "status"],
            },
        }
    },
    "required": ["candidates"],
}


def _segment_of(text: str) -> str:
    low = (text or "").lower()
    if any(w in low for w in DEVICE_WORDS):
        return "device"
    if any(w in low for w in CARE_WORDS):
        return "haircare"
    return ""


class CompetitorDiscoveryAgent(Agent):
    name = "competitor_discovery"
    prompt_file = "competitor_discovery.md"

    def run_rules(self, store, intel, clara_products: list, live: bool = False,
                  brand_index_urls: list[str] | None = None) -> list[DiscoveryCandidate]:
        known = self._known_records(store)
        seen_before = intel.seen_candidates()
        found: dict[str, DiscoveryCandidate] = {}

        self._from_collected_evidence(store, found)
        self._from_competitor_catalogues(store, found)
        if live:
            self._from_brand_indexes(brand_index_urls or [], found)
        else:
            self.report.note(
                "Live brand-index reading was not requested, so discovery used "
                "evidence already collected. No new page was fetched.")

        # ---- classify each candidate against what is already known ----
        out: list[DiscoveryCandidate] = []
        for cand in found.values():
            rec = {"name": cand.competitor_name,
                   "domains": [cand.domain] if cand.domain else [],
                   "products": cand.relevant_products}

            status, dup_of, why = DiscoveryStatus.NEW, "", ""
            for k in known:
                verdict, reason = compare(k, rec)
                if verdict == SAME:
                    status, dup_of, why = DiscoveryStatus.EXISTING, k["key"], reason
                    break
                if verdict == POSSIBLE:
                    status, dup_of, why = DiscoveryStatus.DUPLICATE, k["key"], reason

            if status == DiscoveryStatus.NEW:
                if not self._is_relevant(cand):
                    status = DiscoveryStatus.IRRELEVANT
                    why = ("no hair-tool or haircare product was seen for this "
                           "brand, so no competitive relationship is established")
                elif Confidence.rank(cand.confidence) < Confidence.rank(Confidence.MEDIUM):
                    status = DiscoveryStatus.POSSIBLE
                    why = "found in one source only; needs a second before it counts"

            prior = seen_before.get(cand.identity_key)
            if prior and status == DiscoveryStatus.NEW:
                # Already considered in an earlier cycle. It is not news again.
                status = DiscoveryStatus.EXISTING
                why = (f"already assessed in cycle {prior['cycle_id']} as "
                       f"{prior['status']}")
                cand.first_detected_at = (prior.get("first_detected_at")
                                          or cand.first_detected_at)

            cand.status = status
            cand.duplicate_of = dup_of
            cand.notes = why
            out.append(cand)

        self.report.items_in = len(known)
        self.report.items_out = len(out)
        new_count = sum(1 for c in out if c.status == DiscoveryStatus.NEW)
        self.report.note(f"{len(out)} candidates considered, {new_count} new")

        if not self.model_available():
            self.report.note(
                "Vertex is unavailable, so the search-backed route did not run. "
                "A company that has never appeared in a page the monitor read "
                "cannot be discovered by the deterministic routes — treat this "
                "sweep as incomplete rather than as an empty market.")
        return out

    # ---------------- routes ----------------

    def _known_records(self, store) -> list[dict]:
        recs = []
        for c in store.get_competitors():
            doms = []
            for fld in ("domains", "retail_domains"):
                raw = c.get(fld)
                if isinstance(raw, str):
                    try:
                        raw = json.loads(raw)
                    except (ValueError, TypeError):
                        raw = [raw]
                doms.extend(raw or [])
            recs.append({"key": c["key"], "name": c.get("brand") or c["key"],
                         "domains": doms, "products": []})
        return recs

    def _add(self, found: dict, name: str, domain: str, product: str,
             ev: Evidence, source_route: str) -> None:
        """Merge one sighting into the candidate set."""
        name = (name or "").strip()
        if not name or len(name) < 2:
            return
        key = identity_key(name, [domain] if domain else [])
        if not key:
            return
        cand = found.get(key)
        if cand is None:
            cand = DiscoveryCandidate(
                competitor_name=name, domain=domain, identity_key=key,
                first_detected_at=now_iso(), notes=source_route)
            found[key] = cand
        if product and product not in cand.relevant_products:
            cand.relevant_products.append(product)
        if not any(e.url == ev.url for e in cand.evidence):
            cand.evidence.append(ev)
        cand.confidence = confidence_from_evidence(cand.evidence)
        seg = _segment_of(f"{name} {product}")
        if seg and not cand.target_customer:
            cand.target_customer = (
                "Saudi buyers of hair styling tools" if seg == "device"
                else "Saudi buyers of haircare products")
        if not cand.type:
            cand.type = TYPE_DIRECT if seg == "device" else (
                TYPE_INDIRECT if seg == "haircare" else TYPE_SUBSTITUTE)
        if not cand.why_competitive and seg:
            cand.why_competitive = (
                f"Sells {seg.replace('haircare', 'haircare products')} into the "
                f"same market and category Clara sells into; seen on {ev.publisher}.")

    def _from_collected_evidence(self, store, found: dict) -> None:
        """Brands the monitor has already read on a real page."""
        rows = store.db.execute(
            "SELECT clara_product_id, competitor_key, observed_at, payload "
            "FROM observation").fetchall()
        n = 0
        for r in rows:
            try:
                p = json.loads(r["payload"])
            except (ValueError, TypeError):
                continue
            brand = (p.get("brand") or "").strip()
            url = p.get("canonical_url") or p.get("url") or ""
            if not brand or not url:
                continue
            host = url.split("/")[2] if "://" in url else url
            ev = Evidence(url=url, publisher=host,
                          observed_at=p.get("observed_at") or r["observed_at"] or "",
                          kind=p.get("source_type") or "unknown",
                          excerpt=(p.get("product_name") or "")[:200])
            self._add(found, brand, host, p.get("product_name") or "", ev,
                      "seen in a page the monitor already read")
            n += 1
        self.report.note(f"{n} stored observations scanned for brands")

    def _from_competitor_catalogues(self, store, found: dict) -> None:
        """Brands listed inside a competitor's own catalogue rows."""
        rows = store.db.execute(
            "SELECT competitor_key, canonical_url, product_name, brand, last_seen_at "
            "FROM competitor_product").fetchall()
        for r in rows:
            brand = (r["brand"] or "").strip()
            if not brand:
                continue
            url = r["canonical_url"] or ""
            host = url.split("/")[2] if "://" in url else url
            ev = Evidence(url=url, publisher=host,
                          observed_at=r["last_seen_at"] or "",
                          kind="authorized_retailer",
                          excerpt=(r["product_name"] or "")[:200])
            self._add(found, brand, host, r["product_name"] or "", ev,
                      "listed in a competitor catalogue")

    def _from_brand_indexes(self, urls: list[str], found: dict) -> None:
        """Read brand index pages through the one guarded path.

        Nothing here works around a refusal: a blocked host is recorded on the
        report and escalated, exactly as the access policy requires.
        """
        allowed = set()
        for c in comp.REGISTRY.values():
            allowed.update(c.all_domains())
        for url in urls:
            res = access.guarded_get(url, allowed_hosts=allowed)
            if not res.ok:
                self.report.blocked.append(
                    {"url": url, "signal": res.block_signal,
                     "what_to_do": "open this page by hand and list the hair-tool "
                                   "brands it carries"})
                continue
            html = res.text or ""
            nodes = extract.jsonld_nodes(html)
            brands = set()
            for node in nodes:
                b = node.get("brand")
                if isinstance(b, dict):
                    b = b.get("name")
                if isinstance(b, str):
                    brands.add(b.strip())
                for item in (node.get("itemListElement") or []):
                    if isinstance(item, dict):
                        nb = (item.get("item") or {}).get("brand") if isinstance(
                            item.get("item"), dict) else None
                        if isinstance(nb, dict):
                            nb = nb.get("name")
                        if isinstance(nb, str):
                            brands.add(nb.strip())
            host = url.split("/")[2] if "://" in url else url
            for b in brands:
                ev = Evidence(url=url, publisher=host, observed_at=now_iso(),
                              kind="authorized_retailer",
                              excerpt="listed in the brand index")
                self._add(found, b, "", "", ev, "brand index page")
            self.report.note(f"{len(brands)} brands read from {host}")

    # ---------------- relevance ----------------

    def _is_relevant(self, cand: DiscoveryCandidate) -> bool:
        """A reasonable competitive relationship, not a passing mention."""
        blob = " ".join([cand.competitor_name, *cand.relevant_products]).lower()
        return bool(_segment_of(blob)) or cand.type in (
            TYPE_DIRECT, TYPE_INDIRECT, TYPE_EMERGING, TYPE_NEW_ENTRANT)

    # ---------------- model pass ----------------

    def refine(self, result, store, intel, clara_products, live=False,
               brand_index_urls=None):
        """Let the model add candidates it can support and downgrade weak ones.

        Anything it returns arrives as POSSIBLE with UNVERIFIED confidence and no
        evidence, because a model assertion is not a source. The Verification
        Agent decides whether it becomes anything more.
        """
        if not self.model_available():
            return None
        payload = {
            "clara_products": [
                {"name": p.name, "category": getattr(p, "category", ""),
                 "format": getattr(p, "product_format", "")}
                for p in clara_products[:40]],
            "known_competitors": sorted({c["name"] for c in self._known_records(store)}),
            "already_found": [c.competitor_name for c in result],
            "market": "Saudi Arabia",
        }
        out = self.ask_model(
            "Identify competitors that are missing from the known list. Return only "
            "companies with a real competitive relationship to these products.",
            payload, CANDIDATE_SCHEMA)
        if not out:
            return None
        existing = {c.identity_key for c in result}
        added = 0
        for raw in out.get("candidates") or []:
            name = (raw.get("competitor_name") or "").strip()
            if not name:
                continue
            key = identity_key(name, [raw.get("domain") or ""])
            if not key or key in existing:
                continue
            result.append(DiscoveryCandidate(
                competitor_name=name, domain=raw.get("domain") or "",
                type=raw.get("type") or TYPE_DIRECT,
                relevant_products=raw.get("relevant_products") or [],
                target_customer=raw.get("target_customer") or "",
                why_competitive=raw.get("why_competitive") or "",
                evidence=[],                       # a model claim is not a source
                first_detected_at=now_iso(),
                confidence=Confidence.UNVERIFIED,
                status=DiscoveryStatus.POSSIBLE,
                identity_key=key,
                notes="proposed by the model; no page has been read for it yet"))
            existing.add(key)
            added += 1
        if added:
            self.report.note(f"model proposed {added} further candidates, all "
                             f"POSSIBLE until a source is read")
        return result
