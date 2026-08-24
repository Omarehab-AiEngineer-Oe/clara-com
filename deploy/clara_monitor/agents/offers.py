"""Live Competitor Offers Agent.

The prompt's central rule is the one that makes this agent worth separating from
the others: **an old offer is not automatically a live offer.** Promotions expire
quietly. A page that ran "20% off" last week and says nothing today has not
changed its discount to 20% — it has stopped discounting, and a report that keeps
showing the old figure is worse than one that shows nothing.

So an offer never carries its own status forward. Every cycle re-derives it from
what was actually seen, and the derivation turns on a question most offer trackers
skip: *was the page even readable this time?*

    seen again, unchanged           -> ACTIVE
    seen again, different terms     -> CHANGED   (previous kept for the diff)
    page read cleanly, offer gone   -> EXPIRED
    page could not be read          -> UNKNOWN   (never EXPIRED — absence of
                                                  evidence is not evidence)
    no price or discount to stand on-> UNVERIFIED

That distinction between EXPIRED and UNKNOWN is the whole point. Marking an offer
expired because a site blocked the crawler would invent a competitor's pricing
decision out of a network failure.

Two further rules from the prompt are enforced in code rather than trusted to
care: an expiry date is recorded only when the page printed one, and a discount is
recorded only when the page showed both the before and after price. Neither is
ever computed to fill a gap.
"""

from __future__ import annotations

import hashlib
import json
import re

from ..money import to_decimal
from .base import Agent
from .contracts import (Confidence, Evidence, Offer, OfferStatus,
                        confidence_from_evidence, now_iso)

# Dates a page prints for itself. Anything not matching stays empty — the prompt
# says never guess an expiration date, and a guessed date is indistinguishable
# from a real one once it is stored.
_DATE_PATTERNS = (
    r"(?:until|till|ends?|valid\s+(?:un)?til|expires?\s+on)\s*[:\-]?\s*"
    r"(\d{1,2}[/\-.]\d{1,2}[/\-.]\d{2,4})",
    r"(?:until|till|ends?|valid\s+(?:un)?til|expires?\s+on)\s*[:\-]?\s*"
    r"(\d{1,2}\s+[A-Za-z]{3,9}\s+\d{4})",
    r"(?:حتى|ينتهي|صالح\s+حتى)\s*[:\-]?\s*(\d{1,2}[/\-.]\d{1,2}[/\-.]\d{2,4})",
)


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "")).strip().lower()


def offer_key(competitor: str, url: str, title: str) -> str:
    """A stable identity for one offer on one page.

    Deliberately excludes the price, so a discount that deepens from 10% to 25%
    is recognised as the same offer CHANGED rather than as one offer expiring and
    another appearing. Those are different facts and only one of them is true.
    """
    raw = f"{competitor}|{url}|{_norm(title)[:120]}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def _printed_expiry(text: str) -> str:
    for pat in _DATE_PATTERNS:
        m = re.search(pat, text or "", re.I)
        if m:
            return m.group(1)
    return ""


class LiveCompetitorOffersAgent(Agent):
    name = "live_competitor_offers"
    prompt_file = "live_competitor_offers.md"

    def run_rules(self, store, intel, run_id: str, cycle_id: str,
                  brand_names: dict | None = None) -> list[Offer]:
        names = brand_names or {}
        seen_now = self._observations(store, run_id)
        for o in seen_now:
            # One company, one name. The page payload spells it however the
            # page did; the registry spelling is what the rest of the report
            # uses, so a reader is not shown two competitors that are one.
            o["competitor_brand"] = names.get(o["competitor"],
                                              o["competitor_brand"])
        readable_urls = {o["url"] for o in seen_now if o["readable"]}
        stored = intel.offers()

        current: dict[str, Offer] = {}

        # ---- 1. what the pages show right now ----
        for o in seen_now:
            if not o["readable"]:
                continue
            title = o["promotion_text"] or self._implied_title(o)
            if not title:
                continue
            key = offer_key(o["competitor"], o["url"], title)
            prev = stored.get(key, {}).get("offer") or {}

            offer = Offer(
                competitor=o["competitor_brand"],
                product=o["product_name"],
                offer_title=title,
                offer_description=o["promotion_text"] or "",
                original_price=self._money(o["regular_price"]),
                current_price=self._money(o["selling_price"]),
                discount=self._discount(o),
                currency=o["currency"] or "",
                valid_from="",
                valid_until=_printed_expiry(
                    f"{o['promotion_text']} {o['stock_text_raw']}"),
                detected_at=prev.get("detected_at") or o["observed_at"] or now_iso(),
                last_seen_at=o["observed_at"] or now_iso(),
                source=o["url"],
                evidence=[Evidence(
                    url=o["url"], publisher=o["host"],
                    observed_at=o["observed_at"] or now_iso(),
                    kind=o["source_type"] or "unknown",
                    excerpt=(o["promotion_text"] or "")[:240])],
                offer_key=key,
                competitor_key=o["competitor"],
            )
            offer.confidence = confidence_from_evidence(offer.evidence)

            if not offer.current_price and not offer.discount:
                # A promotion banner with no price to stand on is a claim, not an
                # offer. It is recorded, but never as a live commercial fact.
                offer.status = OfferStatus.UNVERIFIED
                offer.confidence = Confidence.UNVERIFIED
                offer.change_note = ("the page showed promotional wording but no "
                                     "price the Agent could read")
            elif prev and self._differs(prev, offer):
                offer.status = OfferStatus.CHANGED
                offer.previous = {
                    "current_price": prev.get("current_price"),
                    "original_price": prev.get("original_price"),
                    "discount": prev.get("discount"),
                    "offer_title": prev.get("offer_title"),
                    "last_seen_at": prev.get("last_seen_at"),
                }
                offer.change_note = self._describe_change(prev, offer)
            else:
                offer.status = OfferStatus.ACTIVE

            current[key] = offer

        # ---- 2. what was stored but is not showing now ----
        for key, row in stored.items():
            if key in current:
                continue
            prev = row.get("offer") or {}
            url = prev.get("source") or ""
            was_live = row.get("status") in OfferStatus.LIVE

            offer = Offer(**{k: v for k, v in prev.items()
                             if k in Offer.__dataclass_fields__ and k != "evidence"})
            offer.evidence = []
            offer.offer_key = key

            if url in readable_urls:
                # The page was read cleanly this cycle and the offer is not on it.
                offer.status = OfferStatus.EXPIRED
                offer.change_note = (
                    "the page was read successfully on this cycle and no longer "
                    "carries this promotion")
                offer.confidence = Confidence.HIGH if was_live else Confidence.MEDIUM
            else:
                # Not readable. This says nothing about the offer.
                offer.status = OfferStatus.UNKNOWN
                offer.change_note = (
                    "the page was not readable on this cycle, so whether this "
                    "offer is still running has not been established")
                offer.confidence = Confidence.UNVERIFIED
            current[key] = offer

        out = list(current.values())
        out.sort(key=lambda o: (
            OfferStatus.ALL.index(o.status) if o.status in OfferStatus.ALL else 9,
            -(float(to_decimal(o.discount.rstrip("%")) or 0)),
        ))

        live = sum(1 for o in out if o.is_live())
        expired = sum(1 for o in out if o.status == OfferStatus.EXPIRED)
        unknown = sum(1 for o in out if o.status == OfferStatus.UNKNOWN)
        self.report.items_in = len(seen_now)
        self.report.items_out = len(out)
        self.report.note(
            f"{live} live, {expired} expired, {unknown} unknown "
            f"(unknown means the page could not be read, not that the offer ended)")
        return out

    # ---------------- helpers ----------------

    def _observations(self, store, run_id: str) -> list[dict]:
        """Every page looked at on this run, readable or not.

        The unreadable ones matter as much as the readable ones — they are what
        separates EXPIRED from UNKNOWN.
        """
        rows = store.db.execute("SELECT payload FROM observation").fetchall()
        out = []
        for r in rows:
            try:
                p = json.loads(r["payload"])
            except (ValueError, TypeError):
                continue
            url = p.get("canonical_url") or p.get("url") or ""
            if not url:
                continue
            errors = p.get("errors") or []
            out.append({
                "competitor": p.get("competitor_key") or "",
                "competitor_brand": p.get("competitor_brand")
                or p.get("brand") or p.get("competitor_key") or "",
                "product_name": p.get("product_name") or "",
                "url": url,
                "host": url.split("/")[2] if "://" in url else url,
                "observed_at": p.get("observed_at") or "",
                "run_id": p.get("run_id") or "",
                "source_type": p.get("source_type") or "",
                "promotion_text": p.get("promotion_text") or "",
                "promotion_mechanism": p.get("promotion_mechanism") or "",
                "selling_price": p.get("selling_price"),
                "regular_price": p.get("regular_price"),
                "discount_percent": p.get("discount_percent"),
                "currency": p.get("currency") or "",
                "stock_text_raw": p.get("stock_text_raw") or "",
                "readable": not errors and p.get("selling_price") is not None,
            })
        return out

    def _implied_title(self, o: dict) -> str:
        """An offer with no wording but a real before-and-after price."""
        if o["discount_percent"] is not None and o["regular_price"] is not None:
            return f"Price reduced from {o['regular_price']} {o['currency']}".strip()
        return ""

    def _money(self, value) -> str:
        return "" if value is None else str(value)

    def _discount(self, o: dict) -> str:
        """A discount only where the page printed both prices.

        §11's rule, restated here because this is the agent most tempted to break
        it: a percentage computed against anything other than a second real price
        on the same page is a number the retailer never published.
        """
        if o["discount_percent"] is None:
            return ""
        if o["regular_price"] is None or o["selling_price"] is None:
            return ""
        return f"{o['discount_percent']}%"

    def _differs(self, prev: dict, now: Offer) -> bool:
        return any([
            _norm(prev.get("current_price") or "") != _norm(now.current_price),
            _norm(prev.get("original_price") or "") != _norm(now.original_price),
            _norm(prev.get("discount") or "") != _norm(now.discount),
            _norm(prev.get("offer_title") or "") != _norm(now.offer_title),
        ])

    def _describe_change(self, prev: dict, now: Offer) -> str:
        bits = []
        if _norm(prev.get("current_price") or "") != _norm(now.current_price):
            bits.append(f"price {prev.get('current_price') or 'unknown'} "
                        f"-> {now.current_price or 'unknown'}")
        if _norm(prev.get("discount") or "") != _norm(now.discount):
            bits.append(f"discount {prev.get('discount') or 'none'} "
                        f"-> {now.discount or 'none'}")
        if _norm(prev.get("offer_title") or "") != _norm(now.offer_title):
            bits.append("offer wording changed")
        return "; ".join(bits) or "terms changed"

    def refine(self, result, store, intel, run_id, cycle_id,
               brand_names=None):
        """No model pass. Offer status is a question about what was on a page at a
        moment in time; a model has no access to that and could only guess."""
        return None
