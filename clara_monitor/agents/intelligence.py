"""Competitor Intelligence Agent.

Reads verified changes and says what they mean for Clara: competitive impact,
threat level, opportunity, strategic significance, and how the position differs
from the previous state.

Its prompt was described by the orchestrator rather than supplied, so the
behaviour here is written from that description and is easy to replace: drop a
`prompts/agents/competitor_intelligence.md` in and the model pass runs under it
without touching this file.

Two rules shape the scoring:

* **Nothing unverified becomes a finding.** A change that did not clear
  verification is not analysed at all — analysing it would launder an unproven
  claim into a threat assessment, which is how a rumour ends up in a pricing
  decision.
* **Threat is about Clara specifically, not about how impressive the competitor
  is.** Dyson launching anything is interesting; Dyson undercutting a Clara dryer
  it already outsells is a threat. The score therefore leans on the *direction and
  size of the gap against Clara's own price*, not on brand prestige.
"""

from __future__ import annotations

from decimal import Decimal

from ..money import to_decimal
from .base import Agent
from .contracts import (ChangeType, Confidence, Evidence, Finding, ThreatLevel,
                        VerificationStatus, evidence_list)

# The floor a change has to clear before it is analysed at all.
ANALYSABLE = (VerificationStatus.VERIFIED, VerificationStatus.PARTIALLY_VERIFIED)

# Starting threat by what happened. Adjusted afterwards by the actual numbers.
BASE_THREAT = {
    ChangeType.NEW_COMPETITOR: ThreatLevel.MODERATE,
    ChangeType.PRICE_CHANGED: ThreatLevel.MODERATE,
    ChangeType.NEW_OFFER: ThreatLevel.MODERATE,
    ChangeType.NEW_PRODUCT: ThreatLevel.MODERATE,
    ChangeType.POSITIONING_CHANGED: ThreatLevel.LOW,
    ChangeType.OFFER_CHANGED: ThreatLevel.LOW,
    ChangeType.COMPETITOR_CHANGED: ThreatLevel.LOW,
    ChangeType.PRODUCT_CHANGED: ThreatLevel.LOW,
    ChangeType.FEATURE_CHANGED: ThreatLevel.LOW,
    ChangeType.OFFER_EXPIRED: ThreatLevel.NONE,
    ChangeType.RELEVANCE_CHANGED: ThreatLevel.LOW,
    ChangeType.REMOVED_COMPETITOR: ThreatLevel.NONE,
}


def _raise(level: str, steps: int = 1) -> str:
    order = [ThreatLevel.NONE, ThreatLevel.LOW, ThreatLevel.MODERATE,
             ThreatLevel.HIGH, ThreatLevel.CRITICAL]
    return order[min(len(order) - 1, order.index(level) + steps)]


class CompetitorIntelligenceAgent(Agent):
    name = "competitor_intelligence"
    prompt_file = "competitor_intelligence.md"

    def run_rules(self, changes: list, verdicts: dict,
                  price_context: dict | None = None) -> list[Finding]:
        ctx = price_context or {}
        findings: list[Finding] = []
        skipped = 0

        for ch in changes:
            key = f"{ch.change_type}|{ch.entity}|{ch.field_name}"
            verdict = verdicts.get(key)
            if verdict and verdict not in ANALYSABLE:
                skipped += 1
                continue
            if not verdict and Confidence.rank(ch.confidence) < Confidence.rank(
                    Confidence.MEDIUM):
                skipped += 1
                continue

            f = self._assess(ch, ctx)
            if f:
                findings.append(f)

        findings.sort(key=lambda f: (ThreatLevel.ORDER.get(f.threat_level, 9),
                                     -Confidence.rank(f.confidence)))
        self.report.items_in = len(changes)
        self.report.items_out = len(findings)
        self.report.skipped = skipped
        self.report.note(
            f"{skipped} changes were not analysed because they did not clear "
            f"verification; an unproven change is not turned into a threat")
        return findings

    # ---------------- assessment ----------------

    def _assess(self, ch, ctx: dict) -> Finding | None:
        entity = ch.entity
        threat = BASE_THREAT.get(ch.change_type, ThreatLevel.LOW)
        impact_bits, opportunity, significance = [], "", ""

        gap = self._gap_against_clara(ch, ctx)

        if ch.change_type == ChangeType.PRICE_CHANGED:
            old, new = to_decimal(ch.previous_value), to_decimal(ch.new_value)
            if old and new and old > 0:
                move = (new - old) / old * 100
                direction = "down" if move < 0 else "up"
                impact_bits.append(
                    f"{entity} moved this price {direction} by "
                    f"{abs(move):.0f}% ({old} -> {new}).")
                if move <= -15:
                    threat = _raise(threat)
                    impact_bits.append(
                        "A cut of that size is a deliberate move, not a rounding "
                        "adjustment.")
                if move >= 10:
                    opportunity = (
                        f"{entity} raising price widens the gap Clara can advertise "
                        f"against, without Clara changing anything.")
                    threat = ThreatLevel.LOW
        elif ch.change_type == ChangeType.NEW_OFFER:
            impact_bits.append(f"{entity} started a promotion: {ch.new_value}.")
            threat = _raise(threat) if gap and gap < 0 else threat
        elif ch.change_type == ChangeType.OFFER_EXPIRED:
            impact_bits.append(
                f"{entity} has stopped running {ch.previous_value}.")
            opportunity = ("Their price is back to list while Clara's position is "
                           "unchanged — the comparison is more favourable today "
                           "than it was last cycle.")
        elif ch.change_type == ChangeType.NEW_COMPETITOR:
            impact_bits.append(
                f"{entity} was not in the tracked set before this cycle.")
            significance = ("A new name in the same category changes who Clara is "
                            "compared against on a shelf and in search.")
        elif ch.change_type == ChangeType.NEW_PRODUCT:
            impact_bits.append(f"{entity} added {ch.new_value} to its range.")
        elif ch.change_type == ChangeType.POSITIONING_CHANGED:
            impact_bits.append(
                f"{entity} changed how it presents itself: "
                f"{ch.previous_value} -> {ch.new_value}.")
            significance = ("Positioning moves precede pricing moves more often "
                            "than they follow them.")
        elif ch.change_type == ChangeType.REMOVED_COMPETITOR:
            impact_bits.append(f"{entity} is no longer being tracked.")
        else:
            impact_bits.append(
                f"{entity}: {ch.field_name or 'record'} changed from "
                f"{ch.previous_value or 'unknown'} to {ch.new_value or 'unknown'}.")

        if gap is not None:
            if gap < 0:
                impact_bits.append(
                    f"That leaves them about {abs(gap):.0f}% below the Clara "
                    f"product they compete with.")
                if abs(gap) >= 25:
                    threat = _raise(threat)
            else:
                impact_bits.append(
                    f"They remain about {gap:.0f}% above the Clara product they "
                    f"compete with.")
                opportunity = opportunity or (
                    "Clara is still the cheaper option in this pairing; the "
                    "comparison is worth stating explicitly in the listing.")

        if not significance:
            significance = (
                "Directly relevant to Clara's pricing position."
                if ch.change_type in (ChangeType.PRICE_CHANGED, ChangeType.NEW_OFFER)
                else "Background: worth knowing, not worth reacting to on its own.")

        return Finding(
            title=self._title(ch),
            entity=entity,
            change_type=ch.change_type,
            competitive_impact=" ".join(impact_bits),
            threat_level=threat,
            opportunity=opportunity,
            strategic_significance=significance,
            versus_previous=(f"Previously {ch.previous_value or 'not recorded'}; "
                             f"now {ch.new_value or 'not recorded'}."),
            confidence=ch.confidence,
            evidence=evidence_list([e for e in (ch.evidence or [])]),
            change_keys=[f"{ch.change_type}|{ch.entity}|{ch.field_name}"],
        )

    def _title(self, ch) -> str:
        label = ch.change_type.replace("_", " ").lower()
        base = f"{ch.entity}: {label}"
        if ch.field_name:
            base += f" ({ch.field_name})"
        return base

    def _gap_against_clara(self, ch, ctx: dict) -> float | None:
        """How this competitor's price compares with the Clara product it faces.

        Negative means the competitor is cheaper. Returns None rather than zero
        when there is nothing comparable, because "no gap established" and "no
        gap" are different facts.
        """
        pair = (ctx.get("pairs") or {}).get(ch.entity)
        if not pair:
            return None
        clara = to_decimal(pair.get("clara_price"))
        rival = to_decimal(ch.new_value) or to_decimal(pair.get("competitor_price"))
        if not clara or not rival or clara <= 0:
            return None
        if pair.get("clara_currency") != pair.get("competitor_currency"):
            # §11: currency is never converted, so a cross-currency pair has no
            # comparable gap. Saying nothing is correct here.
            return None
        return float((rival - clara) / clara * 100)

    def refine(self, result, changes, verdicts, price_context=None):
        """Optional model pass, kept narrow: it may sharpen the wording of impact
        and opportunity, never change a threat level or a confidence."""
        if not self.model_available() or not result:
            return None
        payload = {"findings": [
            {"title": f.title, "impact": f.competitive_impact,
             "opportunity": f.opportunity} for f in result[:25]]}
        schema = {
            "type": "object",
            "properties": {"findings": {"type": "array", "items": {
                "type": "object",
                "properties": {"title": {"type": "string"},
                               "competitive_impact": {"type": "string"},
                               "opportunity": {"type": "string"}},
                "required": ["title"]}}},
            "required": ["findings"],
        }
        out = self.ask_model(
            "Tighten the wording of each impact and opportunity. Add no new facts, "
            "no numbers that are not already present, and change no assessment.",
            payload, schema)
        if not out:
            return None
        by_title = {f.title: f for f in result}
        for row in out.get("findings") or []:
            f = by_title.get(row.get("title"))
            if not f:
                continue
            if row.get("competitive_impact"):
                f.competitive_impact = row["competitive_impact"]
            if row.get("opportunity"):
                f.opportunity = row["opportunity"]
        return result
