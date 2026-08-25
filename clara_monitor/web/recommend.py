"""Section 6.7: turn a finding into something a person can actually do.

The requirement lists seven parts every recommendation must contain, and they are
seven separate fields on the record rather than one paragraph. That is the whole
design decision here: a missing clause in prose is invisible, an empty field is
not. `Recommendation.complete` reports it, and the report page shows any
recommendation that is short a part rather than hiding it.

    what        what is missing, weak or better than competitors
    where       where it appears on Clara's website
    who         which competitor provides the better example, when applicable
    why         why the change is important
    action      what Clara should do
    priority    High, Medium or Low
    confidence  and the evidence behind it

The action is the hard part and the part most easily faked. A recommendation that
says "improve the headline" has not recommended anything. So each action names the
element, the page and the section, and states the change in terms someone could
brief to a writer or a designer without coming back to ask what was meant.

Nothing in this file invents a fact. Every action is built from the finding's own
observation, and where the finding's Clara state is `NOT_OBSERVED` the action is
"go and check", never "go and add" — because adding something that is already
there is the most expensive way to be wrong.
"""

from __future__ import annotations

from .contracts import (Confidence, FindingCategory, FindingKind, ImageKind,
                        IMAGE_KIND_JOB, IMAGE_KIND_LABEL, OBS_TYPE_LABEL,
                        ObservationType, PAGE_TYPE_LABEL, PRIORITY_ORDER,
                        PresenceState, Priority, Recommendation, key_of)

# Who does this kind of work. Named so a recommendation has an addressee rather
# than being everyone's problem and therefore nobody's.
OWNER = {
    FindingCategory.COPY: "content",
    FindingCategory.CTA: "content and web",
    FindingCategory.IMAGERY: "design and content",
    FindingCategory.SOCIAL_PROOF: "marketing",
    FindingCategory.TRUST: "web and operations",
    FindingCategory.USE_CASE: "product and content",
    FindingCategory.STRUCTURE: "web",
    FindingCategory.COVERAGE: "whoever owns this analysis",
}

# Rough effort, so a High-priority recommendation nobody can schedule is not
# ranked above a Medium one that ships this week.
EFFORT = {
    FindingCategory.COPY: "a writing task on an existing page",
    FindingCategory.CTA: "a copy change on an existing button",
    FindingCategory.IMAGERY: "new photography or a shoot brief",
    FindingCategory.SOCIAL_PROOF: "a collection process plus a page module",
    FindingCategory.TRUST: "a policy statement plus a page module",
    FindingCategory.USE_CASE: "a content block, no new photography needed",
    FindingCategory.STRUCTURE: "a new page",
    FindingCategory.COVERAGE: "a manual read, minutes",
}


def _where(f) -> str:
    """The 'where' field. A URL alone does not answer it; a section does."""
    bits = []
    if f.page_type:
        bits.append(f"the {PAGE_TYPE_LABEL.get(f.page_type, f.page_type).lower()} page")
    if f.clara_section and f.clara_section not in ("page body", ""):
        bits.append(f.clara_section)
    elif f.clara_section == "page body":
        bits.append("in the page body")
    where = ", ".join(bits) or "Clara's site"
    return f"{where} — {f.clara_url}" if f.clara_url else where


def _action_for_job(f, job_label: str) -> str:
    cat = f.category
    if cat == FindingCategory.SOCIAL_PROOF:
        return ("Add a review or rating module to this page, above the fold if "
                "the count is respectable and below the buy box if it is not. "
                "Start with the reviews already on the storefront rather than "
                "waiting for a collection programme — a real count of 15 beats "
                "no count.")
    if cat == FindingCategory.TRUST:
        return ("Put warranty length, the returns window and the accepted "
                "payment methods next to the price, as text a visitor can read "
                "without clicking through to a policy page. These are the three "
                "questions a Saudi buyer asks before adding a device to cart.")
    if cat == FindingCategory.USE_CASE:
        return ("Add a short hair-type block naming which hair types this suits "
                "and which it does not — being explicit about the second is what "
                "makes the first believable. One line per type is enough.")
    return (f"Add the {job_label} that the equivalent competitor page carries, "
            f"stated in Clara's own terms rather than copied.")


def _action_for_image(f) -> str:
    kind = next((k for k in IMAGE_KIND_LABEL
                 if IMAGE_KIND_LABEL[k].lower() in (f.title or "").lower()), "")
    job = IMAGE_KIND_JOB.get(kind, "")
    specific = {
        ImageKind.RESULT: ("Shoot a before-and-after pair on one model, same "
                           "lighting and same crop, and label it with the "
                           "styling time. Unlabelled result shots read as stock."),
        ImageKind.USE_CASE: ("Shoot the product on two or three distinct hair "
                             "types and label each image with the type. The "
                             "label is what does the work — an unlabelled model "
                             "shot is a lifestyle image."),
        ImageKind.INSTRUCTIONAL: ("Add a numbered three- or four-step sequence "
                                  "showing setup and first use. It can be shot "
                                  "on a phone; clarity matters more than "
                                  "production."),
        ImageKind.SOCIAL_PROOF: ("Add customer photographs with permission, or a "
                                 "screenshot of a real review, placed beside the "
                                 "claim it supports."),
        ImageKind.FEATURE_DETAIL: ("Shoot close-ups of the parts the copy makes "
                                   "claims about — the nozzle, the barrel, the "
                                   "controls — so a spec becomes visible rather "
                                   "than asserted."),
        ImageKind.TRUST: ("Show the payment marks, warranty badge and returns "
                          "statement as a small row near the buy button."),
        ImageKind.LIFESTYLE: ("Add one in-context shot so the product is seen "
                              "somewhere other than on white."),
    }.get(kind)
    if specific:
        return (specific + (f" This image type {job}." if job else ""))
    return ("Widen the image set on this page so it answers more than one "
            "question: what arrives, how it is used, and what the result looks "
            "like.")


def _action_for_copy(f) -> str:
    if f.kind == FindingKind.REPETITION:
        return ("Rewrite all but one instance of this line. Give each page a "
                "heading about that page's own subject — the repetition is "
                "costing three chances to say something.")
    if "value proposition" in (f.title or "").lower():
        return ("Replace the leading message with one that names the audience or "
                "the outcome: who this is for, or what changes for them. One "
                "sentence, containing at least one thing a visitor could check "
                "— a hair type, a time, a number.")
    return ("Rewrite this headline to make one checkable claim. Replace the "
            "interchangeable phrasing with a specific detail from the product "
            "itself, or with the hair type it suits.")


def _action_for_cta(f) -> str:
    return ("Relabel this control with the action it performs — what the visitor "
            "gets, not the act of clicking. If the destination is a product "
            "page, say so; if it adds to cart, say that. Keep it under four "
            "words.")


def _action_for_structure(f) -> str:
    return ("Confirm by hand whether this page exists and is simply not linked "
            "from the pages walked. If it exists, link it from the footer and "
            "the relevant product pages. If it does not, brief it — the "
            "competitor example is a reasonable scope reference.")


def _action_for_coverage(f) -> str:
    return ("Open the listed URL(s) in a normal browser and read the relevant "
            "section by hand, then re-run this analysis with those pages "
            "supplied directly as specific pages. Nothing in this system will "
            "retry them with different headers, and it should not.")


def action_for(f) -> str:
    """What Clara should do. Built from the finding, never from a template alone."""
    if f.clara_state == PresenceState.NOT_OBSERVED \
            and f.category != FindingCategory.COVERAGE:
        return ("Check this on the live page first — the analysis did not observe "
                "Clara's own state here, so the gap is unconfirmed. If it is "
                "genuinely missing, "
                + action_for_confirmed(f)[0].lower() + action_for_confirmed(f)[1:])
    return action_for_confirmed(f)


def action_for_confirmed(f) -> str:
    cat = f.category
    if cat == FindingCategory.IMAGERY:
        return _action_for_image(f)
    if cat == FindingCategory.CTA:
        return _action_for_cta(f)
    if cat == FindingCategory.COPY:
        return _action_for_copy(f)
    if cat == FindingCategory.STRUCTURE:
        return _action_for_structure(f)
    if cat == FindingCategory.COVERAGE:
        return _action_for_coverage(f)
    label = {
        FindingCategory.SOCIAL_PROOF: "social proof",
        FindingCategory.TRUST: "trust information",
        FindingCategory.USE_CASE: "use-case content",
    }.get(cat, "content")
    return _action_for_job(f, label)


def what_for(f) -> str:
    """The 'what': missing, weak, or better than competitors."""
    prefix = {
        FindingKind.GAP: "Missing",
        FindingKind.WEAKNESS: "Weak",
        FindingKind.STRENGTH: "Better than competitors",
        FindingKind.REPETITION: "Repeated",
        FindingKind.LIMITATION: "Not observed",
    }.get(f.kind, "Finding")
    return f"{prefix}: {f.title}"


def recommend(findings: list) -> list:
    """One recommendation per finding, with every required part filled.

    Strengths get a recommendation too, and deliberately: section 6.4 asks what
    Clara does better, and "keep doing this, and say it louder" is an action. A
    strength with no action attached is a compliment, not a finding.
    """
    out = []
    for f in findings:
        rec = Recommendation(
            rec_key=key_of("rec", f.finding_key),
            finding_key=f.finding_key,
            what=what_for(f),
            where=_where(f),
            who=(f"{f.competitor} — {f.competitor_url}"
                 if f.competitor and f.competitor_url
                 else f.competitor or ""),
            why=f.why or "",
            action=("Keep this and make it more prominent — it is a difference a "
                    "visitor comparing the two sites would notice, and it is "
                    "currently not being claimed anywhere."
                    if f.kind == FindingKind.STRENGTH else action_for(f)),
            priority=f.priority,
            confidence=f.confidence,
            owner=OWNER.get(f.category, ""),
            effort=EFFORT.get(f.category, ""),
            evidence=list(f.evidence),
        )
        out.append(rec)

    out.sort(key=lambda r: (PRIORITY_ORDER.index(r.priority)
                            if r.priority in PRIORITY_ORDER else 9,
                            0 if r.complete else 1))
    return out


def top_priorities(recs: list, findings: list, limit: int = 5) -> list:
    """Section 8's "Top Priorities": the few things to do first.

    Deliberately capped and deliberately mixed-source: a list of five that is all
    imagery is a list about imagery, not about what to do first. So at most two
    per category, which forces the list to span the actual problem.
    """
    by_key = {f.finding_key: f for f in findings}
    seen_cat: dict = {}
    out = []
    for r in recs:
        f = by_key.get(r.finding_key)
        if not f or f.kind == FindingKind.STRENGTH:
            continue
        cat = f.category
        if seen_cat.get(cat, 0) >= 2:
            continue
        seen_cat[cat] = seen_cat.get(cat, 0) + 1
        out.append({"rec": r, "finding": f})
        if len(out) >= limit:
            break
    return out


def completeness(recs: list) -> dict:
    """Section 13 asks that every recommendation state all its parts.

    Reported rather than assumed. If this ever shows an incomplete row, the
    report shows it too — a quality gate that hides its own failures is not one.
    """
    incomplete = [r for r in recs if not r.complete]
    return {
        "total": len(recs),
        "complete": len(recs) - len(incomplete),
        "incomplete": [{"what": r.what[:80], "missing": r.missing_parts()}
                       for r in incomplete],
        "with_competitor_example": sum(1 for r in recs if r.who),
        "with_evidence": sum(1 for r in recs if r.evidence),
    }
