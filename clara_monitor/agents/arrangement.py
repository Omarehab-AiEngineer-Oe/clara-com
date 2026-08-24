"""Content Arrangement Agent.

The last step before anything is rendered. It decides which of the four sections
each piece of intelligence belongs in, and what order things appear in inside
them:

    Product Competitors      a competitor tied to a specific Clara product
    Competitors              a company relevant to Clara but not pinned to one SKU
    Live Competitor Offers   promotions established as running right now
    Actions Needed           what a person has to do

Its prompt was described by the orchestrator rather than supplied, so this is
written from that description and swaps out cleanly: add
`prompts/agents/content_arrangement.md` and the model pass runs under it.

The routing rule that matters is the one for offers. A promotion only reaches
"Live Competitor Offers" if its status is ACTIVE or CHANGED — never UNKNOWN, and
never EXPIRED. Everything else goes to a clearly separate history block, because
a section titled *live* that contains an offer nobody has confirmed is running is
simply lying to the reader in a way they cannot detect.

Ordering is by what a person needs first, not by what the pipeline produced last:
urgency, then threat, then confidence, then recency. Alphabetical ordering is
avoided everywhere — it puts BaByliss above Dyson regardless of which one just
undercut Clara.
"""

from __future__ import annotations

from .base import Agent
from .contracts import (Action, Confidence, Finding, Offer, OfferStatus,
                        ThreatLevel, now_iso)

SECTION_PRODUCT_COMPETITORS = "product_competitors"
SECTION_COMPETITORS = "competitors"
SECTION_LIVE_OFFERS = "live_competitor_offers"
SECTION_ACTIONS = "actions_needed"
SECTION_OFFER_HISTORY = "offer_history"
SECTION_WATCHLIST = "watchlist"

URGENCY_ORDER = {"now": 0, "this_week": 1, "this_month": 2, "watch": 3}


class ContentArrangementAgent(Agent):
    name = "content_arrangement"
    prompt_file = "content_arrangement.md"

    def run_rules(self, profiles: list, offers: list[Offer],
                  findings: list[Finding], actions: list[Action],
                  candidates: list, pair_index: dict | None = None) -> dict:
        pairs = pair_index or {}

        product_competitors, competitors = [], []
        for p in profiles:
            entry = p.to_dict() if hasattr(p, "to_dict") else dict(p)
            name = entry.get("competitor")
            tied = [prod for prod in entry.get("products") or []
                    if prod.get("competes_with")]
            entry["clara_products_faced"] = sorted({
                c for prod in tied for c in prod.get("competes_with") or []})
            entry["section_reason"] = (
                "tied to a specific Clara product by a stored match" if tied
                else "relevant to the category, but no product-level match holds")
            (product_competitors if tied else competitors).append(entry)

        # A discovered company that is not yet a tracked competitor is neither of
        # the above. It gets its own block rather than being padded into one.
        watchlist = []
        for c in candidates:
            d = c.to_dict() if hasattr(c, "to_dict") else dict(c)
            if d.get("status") in ("NEW", "POSSIBLE"):
                watchlist.append(d)

        live, history = [], []
        for o in offers:
            d = o.to_dict() if hasattr(o, "to_dict") else dict(o)
            if d.get("status") in OfferStatus.LIVE:
                live.append(d)
            else:
                history.append(d)

        # ---- ordering ----
        threat_by_entity = {f.entity: f.threat_level for f in findings}

        def comp_rank(entry: dict) -> tuple:
            name = entry.get("competitor")
            return (ThreatLevel.ORDER.get(threat_by_entity.get(name, ThreatLevel.NONE), 9),
                    -Confidence.rank(entry.get("confidence", "")),
                    -len(entry.get("clara_products_faced") or []),
                    (name or "").lower())

        product_competitors.sort(key=comp_rank)
        competitors.sort(key=comp_rank)

        def offer_rank(d: dict) -> tuple:
            pct = d.get("discount") or ""
            try:
                size = float(str(pct).rstrip("%") or 0)
            except ValueError:
                size = 0.0
            return (0 if d.get("status") == OfferStatus.ACTIVE else 1,
                    -size, -Confidence.rank(d.get("confidence", "")),
                    d.get("competitor") or "")

        live.sort(key=offer_rank)
        history.sort(key=lambda d: (d.get("last_seen_at") or ""), reverse=True)

        actions_out = [a.to_dict() if hasattr(a, "to_dict") else dict(a)
                       for a in actions]
        actions_out.sort(key=lambda a: (URGENCY_ORDER.get(a.get("urgency"), 9),
                                        -Confidence.rank(a.get("confidence", ""))))

        layout = {
            "generated_at": now_iso(),
            "section_order": [
                SECTION_ACTIONS, SECTION_LIVE_OFFERS,
                SECTION_PRODUCT_COMPETITORS, SECTION_COMPETITORS,
                SECTION_WATCHLIST, SECTION_OFFER_HISTORY,
            ],
            SECTION_ACTIONS: actions_out,
            SECTION_LIVE_OFFERS: live,
            SECTION_PRODUCT_COMPETITORS: product_competitors,
            SECTION_COMPETITORS: competitors,
            SECTION_WATCHLIST: watchlist,
            SECTION_OFFER_HISTORY: history,
            "section_notes": {
                SECTION_ACTIONS:
                    "What a person has to do, most urgent first. An empty list "
                    "means nothing verified this cycle required a response.",
                SECTION_LIVE_OFFERS:
                    "Only promotions established as running right now. An offer "
                    "whose page could not be read this cycle is not here — it is "
                    "in the history block marked unknown.",
                SECTION_PRODUCT_COMPETITORS:
                    "Competitors tied to a specific Clara product by a stored "
                    "match, ordered by the threat they currently pose.",
                SECTION_COMPETITORS:
                    "Companies relevant to the category with no product-level "
                    "match holding today.",
                SECTION_WATCHLIST:
                    "Discovered but not yet tracked. Each needs a person to "
                    "assign it or rule it out.",
                SECTION_OFFER_HISTORY:
                    "Offers that ended, changed away, or could not be confirmed. "
                    "Kept so a claim made last week can be traced.",
            },
        }

        self.report.items_in = (len(profiles) + len(offers) + len(actions))
        self.report.items_out = sum(len(layout[s]) for s in layout["section_order"])
        self.report.note(
            f"{len(live)} offers placed live, {len(history)} held back as history "
            f"or unconfirmed")
        return layout

    def refine(self, result, *args, **kwargs):
        """No model pass. Section routing is a rule about evidence status, and a
        model that reorders sections by what reads well would put an unconfirmed
        offer on the live shelf."""
        return None
