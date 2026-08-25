"""Competitor Verification Agent.

The gate between "something was found" and "something is known". Everything
important passes through here before it can be reported as intelligence, and the
prompt sets the standard: never upgrade weak evidence into a verified fact, never
hide a contradiction, never fabricate evidence, and be stricter with offers than
with anything else because offers expire fastest.

Six checks run on every claim, and the verdict is the *worst* result among them
rather than the best — one fatal problem is not offset by five clean checks:

    source      is what it was read from credible for this kind of claim?
    recency     is the evidence recent enough for what is being asserted?
    entity      is the evidence actually about this company and product?
    conflict    does anything already known contradict it?
    currency    is the claim about now, or about something that has passed?
    sufficiency is there enough here at all?

Recency is deliberately claim-dependent. A company's country of origin does not
go stale; a price does, quickly; an offer does fastest of all. Applying one
freshness rule to all three would either reject good structural facts or accept
stale prices, and the second failure is the dangerous one.

This agent may raise a confidence — it is the only one that may — but only up to
the ceiling its own verdict allows, and only from evidence it can see.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from .base import Agent
from .contracts import (Claim, Confidence, Evidence, VerificationStatus,
                        confidence_from_evidence, now_iso)

# How old evidence may be before it stops supporting a claim of this kind.
MAX_AGE_DAYS = {
    "offer": 3,
    "pricing": 14,
    "product": 60,
    "feature": 90,
    "identity": 365,
    "relevance": 180,
    "market_claim": 180,
}
DEFAULT_MAX_AGE_DAYS = 60

# Which source tiers can carry which claim. A marketplace listing is fine for
# "this product is sold here" and not fine for "this is the brand's price".
MIN_TIER_FOR = {
    "pricing": 1,
    "offer": 1,
    "identity": 1,
    "product": 1,
    "feature": 1,
    "relevance": 0,
    "market_claim": 2,
}


def _age_days(stamp: str) -> float | None:
    if not stamp:
        return None
    try:
        dt = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - dt).total_seconds() / 86400.0


class CompetitorVerificationAgent(Agent):
    name = "competitor_verification"
    prompt_file = "competitor_verification.md"

    def run_rules(self, claims: list[Claim],
                  known_entities: dict | None = None) -> list[Claim]:
        known = known_entities or {}
        out = []
        for claim in claims:
            out.append(self._verify(claim, known))
        self.report.items_in = len(claims)
        self.report.items_out = len(out)
        tally: dict[str, int] = {}
        for c in out:
            tally[c.verification_status] = tally.get(c.verification_status, 0) + 1
        self.report.note("verdicts: " + ", ".join(
            f"{k} {v}" for k, v in sorted(tally.items(), key=lambda kv: -kv[1])))
        return out

    # ---------------- one claim ----------------

    def _verify(self, claim: Claim, known: dict) -> Claim:
        claim.checked_at = now_iso()
        subject = claim.subject or "market_claim"
        conflicts = list(claim.conflicts)
        reasons = []
        verdict = VerificationStatus.VERIFIED

        def worse(new_verdict: str, why: str) -> None:
            nonlocal verdict
            reasons.append(why)
            order = [VerificationStatus.VERIFIED,
                     VerificationStatus.PARTIALLY_VERIFIED,
                     VerificationStatus.UNVERIFIED,
                     VerificationStatus.EXPIRED,
                     VerificationStatus.CONTRADICTED,
                     VerificationStatus.INVALID]
            if order.index(new_verdict) > order.index(verdict):
                verdict = new_verdict

        # --- sufficiency ---
        if not claim.evidence:
            claim.verification_status = VerificationStatus.UNVERIFIED
            claim.confidence = Confidence.UNVERIFIED
            claim.reason = ("no evidence was attached, so there is nothing to "
                            "check; this cannot become a fact")
            claim.recommended_action = ("read a source for this claim, or drop it "
                                        "from the report")
            return claim

        # --- source credibility ---
        best_tier = max(e.weight() for e in claim.evidence)
        needed = MIN_TIER_FOR.get(subject, 1)
        if best_tier < needed:
            worse(VerificationStatus.PARTIALLY_VERIFIED,
                  f"the strongest source is weaker than a {subject} claim needs")

        # --- recency ---
        limit = MAX_AGE_DAYS.get(subject, DEFAULT_MAX_AGE_DAYS)
        ages = [a for a in (_age_days(e.observed_at) for e in claim.evidence)
                if a is not None]
        if not ages:
            worse(VerificationStatus.PARTIALLY_VERIFIED,
                  "no evidence carries a readable timestamp, so its age is unknown")
        else:
            freshest = min(ages)
            if freshest > limit:
                if subject in ("offer", "pricing"):
                    worse(VerificationStatus.EXPIRED,
                          f"the freshest evidence is {freshest:.0f} days old and a "
                          f"{subject} claim goes stale after {limit}")
                else:
                    worse(VerificationStatus.PARTIALLY_VERIFIED,
                          f"the freshest evidence is {freshest:.0f} days old "
                          f"(limit {limit})")

        # --- entity match ---
        entity_norm = (claim.entity or "").strip().lower()
        if entity_norm:
            hosts = " ".join(e.url.lower() for e in claim.evidence)
            excerpts = " ".join(e.excerpt.lower() for e in claim.evidence)
            head = entity_norm.split()[0] if entity_norm.split() else entity_norm
            if head and head not in hosts and head not in excerpts:
                worse(VerificationStatus.PARTIALLY_VERIFIED,
                      f"nothing in the evidence names '{claim.entity}', so it may "
                      f"be about a different company")

        # --- conflicts against what is already known ---
        prior = known.get(entity_norm) or {}
        for field_name, prior_value in (prior.get("facts") or {}).items():
            asserted = (prior.get("asserted") or {}).get(field_name)
            if asserted and prior_value and str(asserted) != str(prior_value):
                conflicts.append(
                    f"{field_name}: stored '{prior_value}' vs claimed '{asserted}'")
        if conflicts:
            worse(VerificationStatus.CONTRADICTED,
                  "the claim conflicts with something already established")

        # --- corroboration ---
        hosts = {e.url.split("/")[2] if "://" in e.url else e.url
                 for e in claim.evidence}
        if subject in ("market_claim", "relevance") and len(hosts) < 2:
            worse(VerificationStatus.PARTIALLY_VERIFIED,
                  "a market-level claim rests on a single source")

        claim.verification_status = verdict
        claim.conflicts = conflicts
        ceiling = VerificationStatus.CEILING[verdict]
        claim.confidence = self.cap_confidence(
            confidence_from_evidence(claim.evidence), ceiling)
        claim.reason = ("; ".join(reasons) if reasons
                        else "source, recency, entity and conflict checks all passed")
        claim.recommended_action = self._advice(verdict, subject)
        return claim

    def _advice(self, verdict: str, subject: str) -> str:
        if verdict == VerificationStatus.VERIFIED:
            return "usable as intelligence"
        if verdict == VerificationStatus.PARTIALLY_VERIFIED:
            return ("report it, but say what is unconfirmed; a second independent "
                    "source would settle it")
        if verdict == VerificationStatus.EXPIRED:
            return (f"re-read the source before using this {subject}; the stored "
                    f"evidence is too old to stand behind")
        if verdict == VerificationStatus.CONTRADICTED:
            return ("do not publish either version until a person decides which "
                    "source is right")
        if verdict == VerificationStatus.INVALID:
            return "discard"
        return "hold it out of the report until a source is read"

    def refine(self, result, claims, known_entities=None):
        """The model may add conflicts and lower confidence. It may not raise one.

        A verification agent that can be talked upward is not a verification
        agent, so the merge below only ever takes the worse of the two verdicts.
        """
        if not self.model_available() or not result:
            return None
        payload = {"claims": [
            {"entity": c.entity, "subject": c.subject, "claim": c.claim,
             "evidence": [e.to_dict() for e in c.evidence],
             "rules_verdict": c.verification_status}
            for c in result[:40]]}
        schema = {
            "type": "object",
            "properties": {"reviews": {"type": "array", "items": {
                "type": "object",
                "properties": {
                    "claim": {"type": "string"},
                    "conflicts": {"type": "array", "items": {"type": "string"}},
                    "downgrade_to": {"type": "string"},
                    "reason": {"type": "string"},
                },
                "required": ["claim"]}}},
            "required": ["reviews"],
        }
        out = self.ask_model(
            "Review these verdicts. You may add a conflict or downgrade a verdict "
            "where the evidence does not support it. You may not upgrade any "
            "verdict and you may not add evidence.", payload, schema)
        if not out:
            return None
        by_text = {c.claim: c for c in result}
        changed = 0
        for review in out.get("reviews") or []:
            c = by_text.get(review.get("claim"))
            if not c:
                continue
            for conflict in review.get("conflicts") or []:
                if conflict not in c.conflicts:
                    c.conflicts.append(conflict)
                    changed += 1
            down = (review.get("downgrade_to") or "").upper()
            if down in VerificationStatus.ALL:
                ceiling = VerificationStatus.CEILING[down]
                if Confidence.rank(ceiling) < Confidence.rank(c.confidence):
                    c.verification_status = down
                    c.confidence = ceiling
                    c.reason = (c.reason + "; model review: "
                                + (review.get("reason") or "downgraded"))
                    changed += 1
        if changed:
            self.report.note(f"model review changed {changed} verdicts, all downward")
        return result
