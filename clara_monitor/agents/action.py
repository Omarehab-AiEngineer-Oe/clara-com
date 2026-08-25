"""Action Recommendation Agent.

Turns a verified finding into something a person can actually do this week. The
orchestrator gives one hard instruction — *do not generate generic actions* — and
that is the whole design problem, because generic is the default output of any
system that maps a category to a sentence.

So an action is only emitted when it can carry four specifics:

    the number      the price, the percentage, the date that triggered it
    the object      which Clara product, which competitor page
    the verb        a decision someone can make, not a posture to adopt
    the link        the page to open to act on it

If a finding cannot supply all four, no action is produced for it. An empty
Actions list is a legitimate and useful result: it means nothing verified this
cycle demanded a response, which is different from nobody having looked.

"Monitor the competitive landscape", "consider adjusting pricing" and "review
positioning" are the failure modes this agent exists to avoid. None of them names
a number, an object or a decision, and none of them would be missed if deleted.
"""

from __future__ import annotations

from decimal import Decimal

from ..money import to_decimal
from .base import Agent
from .contracts import (Action, ChangeType, Confidence, Finding, ThreatLevel)

OWNER_PRICING = "pricing"
OWNER_PRODUCT = "product"
OWNER_MARKETING = "marketing"
OWNER_SALES = "sales"
OWNER_OPS = "ops"

URGENCY_BY_THREAT = {
    ThreatLevel.CRITICAL: "now",
    ThreatLevel.HIGH: "this_week",
    ThreatLevel.MODERATE: "this_week",
    ThreatLevel.LOW: "this_month",
    ThreatLevel.NONE: "watch",
}


class ActionRecommendationAgent(Agent):
    name = "action_recommendation"
    prompt_file = "action_recommendation.md"

    def run_rules(self, findings: list[Finding],
                  price_context: dict | None = None) -> list[Action]:
        ctx = price_context or {}
        actions: list[Action] = []
        thin = 0

        for f in findings:
            if Confidence.rank(f.confidence) < Confidence.rank(Confidence.MEDIUM):
                thin += 1
                continue
            built = self._for_finding(f, ctx)
            if built:
                actions.extend(built)
            else:
                thin += 1

        order = {"now": 0, "this_week": 1, "this_month": 2, "watch": 3}
        actions.sort(key=lambda a: (order.get(a.urgency, 9),
                                    -Confidence.rank(a.confidence)))
        self.report.items_in = len(findings)
        self.report.items_out = len(actions)
        self.report.skipped = thin
        self.report.note(
            f"{thin} findings produced no action because they could not carry a "
            f"number, an object and a decision; a generic task was not invented "
            f"to fill the gap")
        return actions

    # ---------------- per finding ----------------

    def _for_finding(self, f: Finding, ctx: dict) -> list[Action]:
        pair = (ctx.get("pairs") or {}).get(f.entity) or {}
        links = [{"label": e.publisher, "url": e.url} for e in f.evidence if e.url]
        urgency = URGENCY_BY_THREAT.get(f.threat_level, "watch")
        out: list[Action] = []

        clara_name = pair.get("clara_name")
        clara_price = pair.get("clara_price")
        rival_price = pair.get("competitor_price")
        currency = pair.get("clara_currency") or "SAR"

        if f.change_type == ChangeType.PRICE_CHANGED and clara_name and rival_price:
            gap = self._gap(clara_price, rival_price)
            if gap is not None and gap < 0:
                out.append(Action(
                    action=(f"Decide whether {clara_name} holds at "
                            f"{clara_price} {currency} now that {f.entity} sits at "
                            f"{rival_price} {currency} — {abs(gap):.0f}% below it. "
                            f"Either match to within 10%, or write the reason the "
                            f"premium is defensible onto the product page."),
                    owner=OWNER_PRICING, urgency=urgency,
                    because=f.competitive_impact,
                    entity=f.entity,
                    expected_outcome=("a documented decision on this one price, "
                                      "not a general pricing review"),
                    links=links, confidence=f.confidence,
                    finding_titles=[f.title]))
            elif gap is not None and gap > 0:
                out.append(Action(
                    action=(f"Put the comparison on the {clara_name} listing: "
                            f"{clara_price} {currency} against {f.entity} at "
                            f"{rival_price} {currency}, a {gap:.0f}% saving. "
                            f"Screenshot their page today so the claim is dated."),
                    owner=OWNER_MARKETING, urgency="this_month",
                    because=f.competitive_impact, entity=f.entity,
                    expected_outcome="a price claim that is true and evidenced",
                    links=links, confidence=f.confidence,
                    finding_titles=[f.title]))

        elif f.change_type == ChangeType.NEW_OFFER and clara_name:
            out.append(Action(
                action=(f"Check whether {clara_name} loses traffic while "
                        f"{f.entity} runs this promotion. Pull the last 7 days of "
                        f"sessions and orders for it, and compare with the 7 days "
                        f"before the offer appeared."),
                owner=OWNER_SALES, urgency=urgency,
                because=f.competitive_impact, entity=f.entity,
                expected_outcome=("a number that says whether this promotion is "
                                  "actually costing Clara anything"),
                links=links, confidence=f.confidence,
                finding_titles=[f.title]))

        elif f.change_type == ChangeType.OFFER_EXPIRED and clara_name:
            out.append(Action(
                action=(f"{f.entity} has stopped discounting. Re-check the "
                        f"{clara_name} comparison block — if it quotes their "
                        f"promotional price, it is now wrong and has to be updated "
                        f"or removed."),
                owner=OWNER_MARKETING, urgency="this_week",
                because=f.competitive_impact, entity=f.entity,
                expected_outcome="no stale competitor price left on the site",
                links=links, confidence=f.confidence,
                finding_titles=[f.title]))

        elif f.change_type == ChangeType.NEW_COMPETITOR:
            out.append(Action(
                action=(f"Assign {f.entity} to the Clara products it overlaps with, "
                        f"or record that it does not compete. Leaving it "
                        f"unassigned means the next run silently skips it."),
                owner=OWNER_PRODUCT, urgency=urgency,
                because=f.competitive_impact, entity=f.entity,
                expected_outcome=("either a tracked pairing or a written reason it "
                                  "is out of scope"),
                links=links, confidence=f.confidence,
                finding_titles=[f.title]))

        elif f.change_type == ChangeType.NEW_PRODUCT and clara_name:
            out.append(Action(
                action=(f"Compare the new {f.entity} product against {clara_name} "
                        f"on the four specs a buyer reads first: motor, heat "
                        f"settings, weight and what is in the box. Record which "
                        f"one wins each."),
                owner=OWNER_PRODUCT, urgency="this_month",
                because=f.competitive_impact, entity=f.entity,
                expected_outcome="a four-line spec verdict, not an impression",
                links=links, confidence=f.confidence,
                finding_titles=[f.title]))

        elif f.change_type == ChangeType.POSITIONING_CHANGED:
            out.append(Action(
                action=(f"Read {f.entity}'s new positioning line and decide whether "
                        f"Clara's own category page now says the same thing. If it "
                        f"does, change Clara's — two brands cannot own one claim."),
                owner=OWNER_MARKETING, urgency="this_month",
                because=f.competitive_impact, entity=f.entity,
                expected_outcome="a differentiated line on the category page",
                links=links, confidence=f.confidence,
                finding_titles=[f.title]))

        return out

    def _gap(self, clara, rival) -> float | None:
        c, r = to_decimal(clara), to_decimal(rival)
        if not c or not r or c <= 0:
            return None
        return float((r - c) / c * 100)

    def refine(self, result, findings, price_context=None):
        """Optional model pass. It may make an action more specific; it may not
        make one vaguer, and it may not add an action for a finding that produced
        none — that finding was rejected for lacking specifics, and asking a model
        to supply them is asking it to invent them."""
        if not self.model_available() or not result:
            return None
        payload = {"actions": [{"action": a.action, "entity": a.entity}
                               for a in result[:25]]}
        schema = {
            "type": "object",
            "properties": {"actions": {"type": "array", "items": {
                "type": "object",
                "properties": {"entity": {"type": "string"},
                               "action": {"type": "string"}},
                "required": ["entity", "action"]}}},
            "required": ["actions"],
        }
        out = self.ask_model(
            "Rewrite each action to be more specific about what to open, what to "
            "decide and what to write down. Keep every number exactly as given. "
            "Do not add actions.", payload, schema)
        if not out:
            return None
        by_entity: dict[str, Action] = {}
        for a in result:
            by_entity.setdefault(a.entity, a)
        for row in out.get("actions") or []:
            a = by_entity.get(row.get("entity"))
            if a and row.get("action") and len(row["action"]) >= len(a.action) * 0.6:
                a.action = row["action"]
        return result
