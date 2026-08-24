"""Section 6.4: compare like with like, and never claim absence you did not check.

Two rules govern this file, and both are requirements rather than preferences.

**Compare equivalent page types, or say there is no equivalent.** Section 6.4
asks for equivalent page types or the same customer question. So a gap is only
raised where Clara and the competitor both have a readable page of the same type.
Where the competitor has a page type Clara does not have at all, that is itself a
finding — but a different one, and it says so.

**Never claim an element is absent when the page could not be accessed.** This is
stated explicitly in 6.4 and it is the rule most likely to produce a confidently
wrong recommendation if it slips. So `clara_state` and every competitor claim run
through `PresenceState`, and the only path to `ABSENT` is a page that was read and
did not contain the thing. A blocked page produces a `LIMITATION` finding — "we
could not tell" — which is a worse headline and a better report.

Everything here compares *profiles*, not pages, because two sites never have the
same URLs. What they can have is the same page type answering the same customer
question, and that is the unit.
"""

from __future__ import annotations

from collections import Counter

from .analyze import CONTENT_IMAGE_KINDS, CONTENT_JOBS
from .contracts import (AccessStatus, Confidence, Evidence, Finding,
                        FindingCategory, FindingKind, IMAGE_KIND_JOB,
                        IMAGE_KIND_LABEL, ImageKind, OBS_TYPE_LABEL,
                        ObservationType, PAGE_TYPE_LABEL, PageType,
                        PresenceState, Priority, key_of)

# Which job maps to which finding category, so a gap lands in the right group.
JOB_CATEGORY = {
    ObservationType.SOCIAL_PROOF: FindingCategory.SOCIAL_PROOF,
    ObservationType.TRUST: FindingCategory.TRUST,
    ObservationType.USE_CASE: FindingCategory.USE_CASE,
    ObservationType.OFFER: FindingCategory.COPY,
}

# What each job is for, in the buyer's terms. A gap has to explain itself.
JOB_MATTERS = {
    ObservationType.SOCIAL_PROOF:
        "a first-time visitor has no reason to believe the product works until "
        "someone other than the brand says so",
    ObservationType.TRUST:
        "a Saudi shopper buying a 400–800 SAR device wants to know about "
        "warranty, returns and payment before adding to cart, not after",
    ObservationType.USE_CASE:
        "hair type decides whether a styling tool works at all, so a visitor "
        "who cannot find their hair type assumes the product is not for them",
    ObservationType.OFFER:
        "a visible offer is the most common reason a browsing visitor becomes a "
        "buying one on the same session",
}

# Image types whose absence is worth a finding, and why. Ordered by how directly
# each one answers a purchase objection.
IMAGE_GAP_PRIORITY = (ImageKind.RESULT, ImageKind.USE_CASE,
                      ImageKind.INSTRUCTIONAL, ImageKind.SOCIAL_PROOF,
                      ImageKind.FEATURE_DETAIL, ImageKind.TRUST,
                      ImageKind.LIFESTYLE)


def _ev(url: str, section: str, excerpt: str, shot: str = "") -> Evidence:
    return Evidence(url=url, section=section, excerpt=excerpt[:300],
                    screenshot=shot)


def _page_of_type(profile: dict, ptype: str) -> dict | None:
    """A readable page of this type on this site, preferring the shallowest."""
    cands = [p for p in profile.get("pages") or []
             if p.get("page_type") == ptype and p.get("status") == AccessStatus.OK]
    if not cands:
        return None
    return sorted(cands, key=lambda p: (p.get("depth") or 0,
                                        -(p.get("word_count") or 0)))[0]


def shared_page_types(clara: dict, rival: dict) -> list:
    """Page types both sites have, readable, in comparison-priority order."""
    a = {p["page_type"] for p in clara.get("pages") or []
         if p.get("status") == AccessStatus.OK}
    b = {p["page_type"] for p in rival.get("pages") or []
         if p.get("status") == AccessStatus.OK}
    order = (PageType.PRODUCT, PageType.HOME, PageType.CATEGORY,
             PageType.ABOUT, PageType.FAQ, PageType.BLOG, PageType.CONTACT)
    return [t for t in order if t in a and t in b]


# --------------------------------------------------------------------------
# the four content jobs
# --------------------------------------------------------------------------

def _job_findings(clara: dict, rival: dict, ptype: str) -> list:
    """For one shared page type: which jobs the rival does and Clara does not."""
    out = []
    cp, rp = _page_of_type(clara, ptype), _page_of_type(rival, ptype)
    if not cp or not rp:
        return out

    c_slot = (clara.get("by_page_type") or {}).get(ptype) or {}
    r_slot = (rival.get("by_page_type") or {}).get(ptype) or {}
    c_jobs = set(c_slot.get("jobs") or [])
    r_jobs = set(r_slot.get("jobs") or [])

    for job in CONTENT_JOBS:
        label = OBS_TYPE_LABEL.get(job, job).lower()
        if job in r_jobs and job not in c_jobs:
            out.append(Finding(
                finding_key=key_of("job", ptype, job, rival["site_key"]),
                category=JOB_CATEGORY.get(job, FindingCategory.COPY),
                kind=FindingKind.GAP,
                title=f"No {label} on Clara's {PAGE_TYPE_LABEL[ptype].lower()} "
                      f"page, where {rival['name']} has it",
                clara_url=cp["url"], clara_section="page body",
                # ABSENT is legitimate here: Clara's page of this type was read.
                clara_state=PresenceState.ABSENT,
                observed=f"the visible text of Clara's "
                         f"{PAGE_TYPE_LABEL[ptype].lower()} page contains no "
                         f"{label}",
                competitor=rival["name"], competitor_url=rp["url"],
                competitor_example=f"{rival['name']}'s "
                                   f"{PAGE_TYPE_LABEL[ptype].lower()} page does",
                why=JOB_MATTERS.get(job, ""),
                confidence=Confidence.MEDIUM,
                confidence_why="both pages were read in full; the test is on "
                               "visible text, so an element rendered only by "
                               "JavaScript after load could be missed",
                page_type=ptype,
                evidence=[_ev(cp["url"], "page body",
                              f"read {cp.get('word_count', 0)} words; no {label} "
                              f"phrasing present", cp.get("screenshot", "")),
                          _ev(rp["url"], "page body",
                              f"{label} phrasing present",
                              rp.get("screenshot", ""))]))
        elif job in c_jobs and job not in r_jobs:
            out.append(Finding(
                finding_key=key_of("strength", ptype, job, rival["site_key"]),
                category=JOB_CATEGORY.get(job, FindingCategory.COPY),
                kind=FindingKind.STRENGTH,
                title=f"Clara does {label} on its "
                      f"{PAGE_TYPE_LABEL[ptype].lower()} page and "
                      f"{rival['name']} does not",
                clara_url=cp["url"], clara_section="page body",
                clara_state=PresenceState.PRESENT,
                observed=f"Clara's page does the {label} job",
                competitor=rival["name"], competitor_url=rp["url"],
                competitor_example=f"not present on {rival['name']}'s "
                                   f"equivalent page",
                why="worth keeping and worth saying louder — it is a difference "
                    "a visitor comparing the two would notice",
                confidence=Confidence.MEDIUM,
                confidence_why="visible-text comparison on both pages",
                priority=Priority.LOW,
                priority_why="a strength to preserve, not a task",
                page_type=ptype,
                evidence=[_ev(cp["url"], "page body", f"{label} present",
                              cp.get("screenshot", ""))]))
    return out


# --------------------------------------------------------------------------
# imagery
# --------------------------------------------------------------------------

def _image_findings(clara: dict, rival: dict, ptype: str) -> list:
    """Section 6.5's last line: image types the rival uses and Clara does not."""
    out = []
    cp, rp = _page_of_type(clara, ptype), _page_of_type(rival, ptype)
    if not cp or not rp:
        return out

    c_kinds = ((clara.get("by_page_type") or {}).get(ptype) or {}).get(
        "image_kinds") or {}
    r_kinds = ((rival.get("by_page_type") or {}).get(ptype) or {}).get(
        "image_kinds") or {}

    for kind in IMAGE_GAP_PRIORITY:
        rival_has = (r_kinds.get(kind) or 0)
        clara_has = (c_kinds.get(kind) or 0)
        if rival_has >= 1 and clara_has == 0:
            out.append(Finding(
                finding_key=key_of("img", ptype, kind, rival["site_key"]),
                category=FindingCategory.IMAGERY, kind=FindingKind.GAP,
                title=f"No {IMAGE_KIND_LABEL[kind].lower()} images on Clara's "
                      f"{PAGE_TYPE_LABEL[ptype].lower()} page",
                clara_url=cp["url"], clara_section="image set",
                clara_state=PresenceState.ABSENT,
                observed=f"none of the images on Clara's page present "
                         f"themselves as {IMAGE_KIND_LABEL[kind].lower()} — by "
                         f"filename, alt text or caption",
                competitor=rival["name"], competitor_url=rp["url"],
                competitor_example=f"{rival['name']} uses {rival_has} on the "
                                   f"equivalent page",
                why=f"this image type {IMAGE_KIND_JOB.get(kind, 'does a job no other type does')}",
                confidence=Confidence.LOW,
                confidence_why="image type is read from filename, alt text and "
                               "caption, not from the picture itself; an "
                               "unlabelled image of this type would be missed",
                page_type=ptype,
                evidence=[_ev(cp["url"], "image set",
                              f"{sum(c_kinds.values())} image(s) classified, "
                              f"none as {kind}", cp.get("screenshot", "")),
                          _ev(rp["url"], "image set",
                              f"{rival_has} image(s) classified as {kind}",
                              rp.get("screenshot", ""))]))

    # Variety, not just type-by-type presence.
    c_var = len([k for k, v in c_kinds.items()
                 if k in CONTENT_IMAGE_KINDS and v])
    r_var = len([k for k, v in r_kinds.items()
                 if k in CONTENT_IMAGE_KINDS and v])
    if r_var >= c_var + 2:
        out.append(Finding(
            finding_key=key_of("imgvar", ptype, rival["site_key"]),
            category=FindingCategory.IMAGERY, kind=FindingKind.WEAKNESS,
            title=f"Clara's {PAGE_TYPE_LABEL[ptype].lower()} page shows the "
                  f"product in {c_var} way(s); {rival['name']} shows it in {r_var}",
            clara_url=cp["url"], clara_section="image set",
            clara_state=PresenceState.WEAK,
            observed=f"{c_var} distinct content image type(s) against "
                     f"{r_var} on the equivalent page",
            competitor=rival["name"], competitor_url=rp["url"],
            competitor_example=", ".join(
                IMAGE_KIND_LABEL[k].lower() for k in r_kinds
                if k in CONTENT_IMAGE_KINDS and r_kinds[k])[:120],
            why="each image type answers a different question; a page with one "
                "type answers one question repeatedly",
            confidence=Confidence.LOW,
            confidence_why="type is inferred from labelling, so variety is a "
                           "lower bound rather than a measurement",
            page_type=ptype,
            evidence=[_ev(cp["url"], "image set",
                          f"types present: {', '.join(sorted(k for k in c_kinds if c_kinds[k])) or 'none'}",
                          cp.get("screenshot", ""))]))
    return out


# --------------------------------------------------------------------------
# copy and ctas
# --------------------------------------------------------------------------

def _copy_findings(clara: dict, rival: dict, ptype: str) -> list:
    out = []
    cp, rp = _page_of_type(clara, ptype), _page_of_type(rival, ptype)
    if not cp or not rp:
        return out
    c_slot = (clara.get("by_page_type") or {}).get(ptype) or {}
    r_slot = (rival.get("by_page_type") or {}).get(ptype) or {}

    # The value proposition, compared where the rival has a better one.
    cq = c_slot.get("value_prop_quality")
    rq = r_slot.get("value_prop_quality")
    if cq == "weak" and rq == "strong":
        out.append(Finding(
            finding_key=key_of("vp", ptype, rival["site_key"]),
            category=FindingCategory.COPY, kind=FindingKind.WEAKNESS,
            title=f"Clara's {PAGE_TYPE_LABEL[ptype].lower()} page opens without "
                  f"a value proposition",
            clara_url=cp["url"], clara_section="top of page",
            clara_state=PresenceState.WEAK,
            observed=f"the leading message is “{(c_slot.get('value_prop') or '')[:110]}” "
                     f"— it names neither an audience nor an outcome",
            competitor=rival["name"], competitor_url=rp["url"],
            competitor_example=f"“{(r_slot.get('value_prop') or '')[:110]}”",
            why="the first screen decides whether a visitor stays; a message "
                "that could sit on any brand's page gives them no reason to",
            confidence=Confidence.MEDIUM,
            confidence_why="graded by the same rubric on both pages; the rubric "
                           "reads phrasing, not brand fit",
            page_type=ptype,
            evidence=[_ev(cp["url"], "top of page",
                          c_slot.get("value_prop") or "", cp.get("screenshot", "")),
                      _ev(rp["url"], "top of page",
                          r_slot.get("value_prop") or "", rp.get("screenshot", ""))]))

    # Weak headlines on Clara's own page. Not comparative — 6.6 asks for these
    # on their own merits, and the fix does not depend on a competitor.
    for w in (c_slot.get("weak_headlines") or [])[:3]:
        out.append(Finding(
            finding_key=key_of("weakcopy", w["url"], w["text"][:60]),
            category=FindingCategory.COPY, kind=FindingKind.WEAKNESS,
            title=f"Weak headline: “{w['text'][:60]}”",
            clara_url=w["url"], clara_section=w["section"],
            clara_state=PresenceState.WEAK, observed=w["text"][:200],
            why=w["why"] or "the phrasing makes no claim a visitor can check",
            confidence=Confidence.MEDIUM,
            confidence_why="the rubric reads phrasing; it cannot judge brand "
                           "voice, so a deliberate house style may read as weak",
            page_type=ptype,
            evidence=[_ev(w["url"], w["section"], w["text"])]))

    for w in (c_slot.get("weak_ctas") or [])[:3]:
        out.append(Finding(
            finding_key=key_of("weakcta", w["url"], w["text"][:40]),
            category=FindingCategory.CTA, kind=FindingKind.WEAKNESS,
            title=f"Weak call to action: “{w['text'][:40]}”",
            clara_url=w["url"], clara_section=w["section"],
            clara_state=PresenceState.WEAK, observed=w["text"][:120],
            why=w["why"] or "a visitor cannot tell what happens after the click",
            confidence=Confidence.HIGH,
            confidence_why="the label was read directly off the page",
            page_type=ptype,
            evidence=[_ev(w["url"], w["section"], w["text"])]))
    return out


# --------------------------------------------------------------------------
# repetition, structure, coverage
# --------------------------------------------------------------------------

def _site_level_findings(clara: dict, rivals: list) -> list:
    out = []

    for r in (clara.get("repeated_headlines") or [])[:2]:
        out.append(Finding(
            finding_key=key_of("rep", r["text"][:60]),
            category=FindingCategory.COPY, kind=FindingKind.REPETITION,
            title=f"“{r['text'][:56]}” appears on {r['count']} pages",
            clara_url=clara["base_url"], clara_section="across the site",
            clara_state=PresenceState.PRESENT,
            observed=f"the same heading appears {r['count']} times across the "
                     f"{clara['pages_read']} page(s) read",
            why="a visitor who sees the same line on three pages concludes "
                "there is one thing to say, and stops reading",
            confidence=Confidence.HIGH,
            confidence_why="counted directly from the collected pages",
            priority=Priority.LOW,
            priority_why="cheap to fix, and it is presentation rather than a "
                         "missing capability",
            evidence=[_ev(clara["base_url"], "across the site", r["text"])]))

    # Page types a competitor has and Clara does not. Structural, and separate
    # from a content gap, because the fix is a page rather than a paragraph.
    clara_types = {p["page_type"] for p in clara.get("pages") or []
                   if p.get("status") == AccessStatus.OK}
    for rv in rivals:
        rival_types = {p["page_type"] for p in rv.get("pages") or []
                       if p.get("status") == AccessStatus.OK}
        for t in (PageType.FAQ, PageType.BLOG, PageType.ABOUT):
            if t in rival_types and t not in clara_types:
                sample = _page_of_type(rv, t)
                out.append(Finding(
                    finding_key=key_of("ptype", t, rv["site_key"]),
                    category=FindingCategory.STRUCTURE, kind=FindingKind.GAP,
                    title=f"No {PAGE_TYPE_LABEL[t].lower()} page was found on "
                          f"Clara's site; {rv['name']} has one",
                    clara_url=clara["base_url"], clara_section="site structure",
                    # Not ABSENT: discovery was bounded, so "not found within the
                    # page limit" is the honest claim and a person can settle it
                    # in one look.
                    clara_state=PresenceState.NOT_OBSERVED,
                    observed=f"no {PAGE_TYPE_LABEL[t].lower()} page appeared "
                             f"within the {clara['pages_attempted']} page(s) "
                             f"this run attempted — it may exist and not be "
                             f"linked from the pages walked",
                    competitor=rv["name"],
                    competitor_url=(sample or {}).get("url", rv["base_url"]),
                    competitor_example=f"{rv['name']} publishes one",
                    why={
                        PageType.FAQ: "an FAQ answers the objections that "
                                      "otherwise become abandoned carts and "
                                      "support messages",
                        PageType.BLOG: "editorial content is how a beauty brand "
                                       "gets found for a question rather than a "
                                       "brand name",
                        PageType.ABOUT: "a first-time buyer of a 400+ SAR device "
                                        "wants to know who is selling it",
                    }[t],
                    confidence=Confidence.LOW,
                    confidence_why="bounded discovery: absence here means not "
                                   "linked from the pages walked, not proven "
                                   "missing",
                    priority=Priority.LOW,
                    priority_why="verify by hand before acting — one look "
                                 "settles whether the page exists",
                    evidence=[_ev(clara["base_url"], "site structure",
                                  f"page types found: "
                                  f"{', '.join(sorted(clara_types))}")]))
    return out


def _coverage_findings(clara: dict, rivals: list) -> list:
    """Where the analysis could not see. Section 8 requires this as a section.

    These are findings, not footnotes, because a competitor whose product pages
    all CAPTCHA'd will otherwise read as a competitor with no product content —
    the exact error 6.4 forbids.
    """
    out = []
    for prof in [clara] + list(rivals):
        blocked = [p for p in prof.get("pages") or []
                   if p.get("status") == AccessStatus.BLOCKED]
        if prof.get("access_status") != AccessStatus.OK:
            out.append(Finding(
                finding_key=key_of("cov-site", prof["site_key"]),
                category=FindingCategory.COVERAGE, kind=FindingKind.LIMITATION,
                title=f"{prof['name']} could not be read at all",
                clara_url=clara["base_url"] if prof["role"] != "clara" else prof["base_url"],
                clara_section="coverage",
                clara_state=PresenceState.NOT_OBSERVED,
                observed=f"{prof['base_url']} returned "
                         f"{prof.get('access_status')}: "
                         f"{prof.get('access_note') or 'no detail'}",
                competitor=prof["name"] if prof["role"] != "clara" else "",
                competitor_url=prof["base_url"],
                why="nothing in this report describes this site. No gap or "
                    "strength involving it can be claimed, and none is.",
                confidence=Confidence.HIGH,
                confidence_why="the access result is a direct observation",
                priority=Priority.HIGH,
                priority_why="a human decision: read it manually, or drop it "
                             "from the comparison and say so",
                evidence=[_ev(prof["base_url"], "coverage",
                              prof.get("access_note") or "no response")]))
        elif blocked:
            out.append(Finding(
                finding_key=key_of("cov-pages", prof["site_key"]),
                category=FindingCategory.COVERAGE, kind=FindingKind.LIMITATION,
                title=f"{len(blocked)} page(s) on {prof['name']} were blocked",
                clara_url=prof["base_url"], clara_section="coverage",
                clara_state=PresenceState.NOT_OBSERVED,
                observed="; ".join(
                    f"{p['url']} ({p.get('status_note') or 'blocked'})"
                    for p in blocked[:4]),
                competitor=prof["name"] if prof["role"] != "clara" else "",
                competitor_url=prof["base_url"],
                why="anything on those pages is absent from this comparison. "
                    "Where a gap depends on them it is reported as not "
                    "observed rather than as missing.",
                confidence=Confidence.HIGH,
                confidence_why="each block was recorded at fetch time with its "
                               "own signal",
                priority=Priority.MEDIUM,
                priority_why="read the listed pages by hand to close the gap "
                             "in coverage",
                evidence=[_ev(p["url"], "coverage",
                              p.get("status_note") or "blocked")
                          for p in blocked[:4]]))
    return out


# --------------------------------------------------------------------------
# priority
# --------------------------------------------------------------------------

def grade(f: Finding, *, rival_count: int = 1, corroborated: int = 1) -> Finding:
    """Priority from the kind of finding, the evidence, and how many rivals agree.

    Corroboration is what separates "one competitor does this" from "everyone
    does this and Clara does not". The second is a much stronger signal and it is
    the only route to HIGH for a content gap.
    """
    if f.priority_why:                      # already graded deliberately
        return f

    score = 0
    why = []

    if f.kind == FindingKind.GAP:
        score += 2
        why.append("a competitor has something Clara does not")
    elif f.kind == FindingKind.WEAKNESS:
        score += 1
        why.append("Clara has it but it is thin")

    if f.category in (FindingCategory.TRUST, FindingCategory.SOCIAL_PROOF):
        score += 2
        why.append("trust and proof act directly on whether a visitor buys")
    elif f.category in (FindingCategory.CTA, FindingCategory.USE_CASE):
        score += 1
        why.append("it sits on the path to the next action")

    if corroborated >= 2 and rival_count >= 2:
        score += 2
        why.append(f"{corroborated} of {rival_count} competitors do it")

    if f.confidence == Confidence.HIGH:
        score += 1
        why.append("read directly off the page")
    elif f.confidence in (Confidence.LOW, Confidence.UNVERIFIED):
        score -= 1
        why.append("the evidence is indirect")

    if f.clara_state == PresenceState.NOT_OBSERVED:
        score -= 2
        why.append("Clara's own state was not observed, so this needs checking "
                   "before it is acted on")

    f.priority = (Priority.HIGH if score >= 5 else
                  Priority.MEDIUM if score >= 3 else Priority.LOW)
    f.priority_why = "; ".join(why) or "no strong signal either way"
    return f


def compare_all(clara: dict, rivals: list) -> list:
    """Every finding this run produced, deduplicated and graded.

    Corroboration is counted across rivals *before* grading, so a gap three
    competitors share is graded as such rather than three times as a single
    competitor's habit.
    """
    if clara.get("access_status") != AccessStatus.OK:
        # No Clara pages means no comparison is possible. Say that, once, rather
        # than emitting a page of findings derived from nothing.
        return _coverage_findings(clara, rivals)

    readable_rivals = [r for r in rivals
                       if r.get("access_status") == AccessStatus.OK]
    raw: list = []
    for rv in readable_rivals:
        for ptype in shared_page_types(clara, rv):
            raw += _job_findings(clara, rv, ptype)
            raw += _image_findings(clara, rv, ptype)
            raw += _copy_findings(clara, rv, ptype)
    raw += _site_level_findings(clara, readable_rivals)
    raw += _coverage_findings(clara, rivals)

    # Deduplicate on what the finding is *about*, not on which rival raised it,
    # then record how many rivals raised it.
    def subject(f: Finding) -> str:
        return "|".join([f.category, f.kind, f.page_type or "",
                         (f.title.split(";")[0][:70]
                          if f.kind != FindingKind.GAP else ""),
                         f.clara_url, f.observed[:60]])

    groups: dict = {}
    for f in raw:
        groups.setdefault(subject(f), []).append(f)

    out = []
    for members in groups.values():
        keep = members[0]
        others = [m.competitor for m in members[1:] if m.competitor]
        if others:
            named = [keep.competitor] + others
            keep.competitor = ", ".join(dict.fromkeys(n for n in named if n))
            keep.competitor_example = (
                f"{len(set(named))} of {len(readable_rivals)} competitors read: "
                f"{keep.competitor_example}")
        out.append(grade(keep, rival_count=len(readable_rivals),
                         corroborated=len({m.competitor for m in members
                                           if m.competitor}) or 1))

    from .contracts import PRIORITY_ORDER
    out.sort(key=lambda f: (PRIORITY_ORDER.index(f.priority),
                            f.kind == FindingKind.STRENGTH,
                            f.category))
    return out
