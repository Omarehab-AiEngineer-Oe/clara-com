"""Sections 6.2 and 6.3: read each site, the same way, and record what is there.

One function does both Clara and the competitors, because section 6.3 requires
"the same analysis criteria" and the only reliable way to guarantee that is to
have no second code path. `role` never branches the analysis; it only labels the
output.

What comes out is a list of `Observation` rows — each holding what was visible
*and*, separately, what the rubric read into it — plus a per-site profile: the
page types covered, the content jobs the site's own words do, the image mix, the
CTA mix, and the phrases it repeats.

The profile is the unit of comparison. Comparing raw pages would compare two
sitemaps; comparing profiles compares two *presentations*, which is the question
the requirements actually ask.

Nothing here decides what Clara should do. Findings and recommendations are
`compare.py` and `recommend.py`, kept separate so an observation can be trusted
without agreeing with the conclusion drawn from it.
"""

from __future__ import annotations

from collections import Counter

from . import rubric
from .collect import text_of
from .contracts import (AccessStatus, Evidence, ImageKind, IMAGE_KIND_JOB,
                        ObservationType, Observation, PageType, PresenceState,
                        Website, key_of, now_iso)

# The image types that do a job for a beauty-tool buyer. `decorative` and
# `unclassified` are counted but never treated as content.
CONTENT_IMAGE_KINDS = (ImageKind.PRODUCT, ImageKind.LIFESTYLE,
                       ImageKind.USE_CASE, ImageKind.INSTRUCTIONAL,
                       ImageKind.RESULT, ImageKind.FEATURE_DETAIL,
                       ImageKind.SOCIAL_PROOF, ImageKind.TRUST)

# The four content jobs a comparison checks for on every page type.
CONTENT_JOBS = (ObservationType.SOCIAL_PROOF, ObservationType.TRUST,
                ObservationType.USE_CASE, ObservationType.OFFER)


def analyse_page(site: Website, page, html: str) -> list:
    """Every observation one page yields. Same rubric for every site."""
    if not html or page.status != AccessStatus.OK:
        return []

    obs: list = []
    body_text = text_of(html)

    def add(section: str, otype: str, observed: str, interpretation: str,
            quality: str = "", signals: list | None = None,
            image_kind: str = "", excerpt: str = "", image_url: str = ""):
        obs.append(Observation(
            obs_key=key_of(page.page_key, otype, observed[:120], image_url),
            page_key=page.page_key, site_key=site.key, section=section,
            obs_type=otype, observed=observed[:600],
            interpretation=interpretation, image_kind=image_kind,
            quality=quality, signals=list(signals or []),
            evidence=Evidence(url=page.url, section=section,
                              excerpt=(excerpt or observed)[:300],
                              image_url=image_url,
                              screenshot=page.screenshot,
                              observed_at=page.collected_at or now_iso())))

    # ---- headings: the page's own account of what it is offering
    heads = rubric.headings(html)
    for i, h in enumerate(heads[:24]):
        q, sig = rubric.copy_quality(h["text"])
        otype = (ObservationType.HEADLINE if h["level"] <= 2
                 else ObservationType.SUBHEAD)
        interp = {
            "strong": "makes a claim a visitor can check",
            "adequate": "understandable, but not distinctive",
            "weak": "occupies the position of a message without making one",
        }[q]
        add(rubric.section_for(html, h["text"]) if i else "top of page",
            otype, h["text"], interp, q, sig)

    # ---- the value proposition: the first heading that behaves like one
    vp = next((h for h in heads
               if rubric.VALUE_SIGNAL.search(h["text"])
               or rubric.SPECIFIC_COPY.search(h["text"])), None)
    if vp:
        add("top of page", ObservationType.VALUE_PROP, vp["text"],
            "names an audience or a checkable outcome, so it works as a value "
            "proposition", "strong",
            ["the first heading that commits to something"])
    elif heads:
        add("top of page", ObservationType.VALUE_PROP, heads[0]["text"],
            "the leading message does not name who it is for or what changes, "
            "so the page opens without a value proposition", "weak",
            ["no audience and no checkable outcome in any heading"])

    # ---- calls to action
    for c in rubric.extract_ctas(html, page.url)[:18]:
        q, sig = rubric.cta_quality(c["label"])
        interp = {
            "strong": "names the next action, so a visitor knows what happens",
            "adequate": "specific enough to be understood",
            "weak": "names the act of clicking rather than the outcome",
        }[q]
        add(rubric.section_for(html, c["label"]), ObservationType.CTA,
            c["label"], interp, q, sig)

    # ---- images
    for im in rubric.extract_images(html, page.url)[:40]:
        job = IMAGE_KIND_JOB.get(im["kind"], "")
        interp = (f"reads as {im['kind'].replace('_', ' ')}"
                  + (f" — {job}" if job else ""))
        if not im["has_alt"]:
            interp += "; no alt text, so a screen reader gets nothing from it"
        add(rubric.section_for(html, im["url"]) or "page body",
            ObservationType.IMAGE,
            im["alt"] or im["url"].rsplit("/", 1)[-1][:80],
            interp,
            "weak" if im["kind"] in (ImageKind.DECORATIVE,
                                     ImageKind.UNCLASSIFIED) else "adequate",
            im["signals"], image_kind=im["kind"],
            excerpt=im["alt"] or im["near"], image_url=im["url"])

    # ---- the four content jobs, from the page's own words
    for otype, hits in rubric.presence_scan(body_text).items():
        if not hits:
            continue
        add(rubric.section_for(html, hits[0]), otype,
            "; ".join(dict.fromkeys(h.strip() for h in hits))[:300],
            f"the page's own words do the {otype.replace('_', ' ')} job",
            "adequate", [f"{len(hits)} phrase(s) found in the visible text"],
            excerpt=hits[0])

    return obs


def profile_site(site: Website, pages: list, observations: list) -> dict:
    """What this site does, in a shape two sites can be compared on.

    Keyed by page type as well as summed across the site, because "no
    instructional images anywhere" and "no instructional images on the product
    page" are different findings and only the second one is usually actionable.
    """
    readable = [p for p in pages if p.status == AccessStatus.OK]
    by_page = {}
    for o in observations:
        by_page.setdefault(o.page_key, []).append(o)
    page_of = {p.page_key: p for p in pages}

    img_kinds = Counter()
    cta_q = Counter()
    copy_q = Counter()
    jobs: dict = {j: set() for j in CONTENT_JOBS}
    per_type: dict = {}

    for o in observations:
        pg = page_of.get(o.page_key)
        ptype = pg.page_type if pg else PageType.OTHER
        slot = per_type.setdefault(ptype, {
            "pages": set(), "image_kinds": Counter(), "cta_quality": Counter(),
            "copy_quality": Counter(), "jobs": set(), "weak_headlines": [],
            "weak_ctas": [], "value_prop": "", "value_prop_quality": "",
        })
        slot["pages"].add(o.page_key)

        if o.obs_type == ObservationType.IMAGE:
            img_kinds[o.image_kind] += 1
            slot["image_kinds"][o.image_kind] += 1
        elif o.obs_type == ObservationType.CTA:
            cta_q[o.quality] += 1
            slot["cta_quality"][o.quality] += 1
            if o.quality == "weak":
                slot["weak_ctas"].append({"text": o.observed,
                                          "section": o.section,
                                          "url": pg.url if pg else "",
                                          "why": (o.signals or [""])[0]})
        elif o.obs_type in (ObservationType.HEADLINE, ObservationType.SUBHEAD):
            copy_q[o.quality] += 1
            slot["copy_quality"][o.quality] += 1
            if o.quality == "weak":
                slot["weak_headlines"].append({"text": o.observed,
                                               "section": o.section,
                                               "url": pg.url if pg else "",
                                               "why": (o.signals or [""])[0]})
        elif o.obs_type == ObservationType.VALUE_PROP:
            slot["value_prop"] = o.observed
            slot["value_prop_quality"] = o.quality
        elif o.obs_type in jobs:
            jobs[o.obs_type].add(o.page_key)
            slot["jobs"].add(o.obs_type)

    for slot in per_type.values():
        slot["pages"] = len(slot["pages"])
        slot["jobs"] = sorted(slot["jobs"])
        slot["image_kinds"] = dict(slot["image_kinds"])
        slot["cta_quality"] = dict(slot["cta_quality"])
        slot["copy_quality"] = dict(slot["copy_quality"])
        slot["weak_headlines"] = slot["weak_headlines"][:6]
        slot["weak_ctas"] = slot["weak_ctas"][:6]

    # Phrases the site repeats. Section 6.2 asks for repeated content, and this
    # is the only signal here that needs the whole site rather than one page.
    all_heads = [o.observed for o in observations
                 if o.obs_type in (ObservationType.HEADLINE,
                                   ObservationType.SUBHEAD)]
    all_ctas = [o.observed for o in observations
                if o.obs_type == ObservationType.CTA]

    content_images = sum(v for k, v in img_kinds.items()
                         if k in CONTENT_IMAGE_KINDS)
    return {
        "site_key": site.key,
        "role": site.role,
        "name": site.name,
        "base_url": site.base_url,
        "access_status": site.access_status,
        "access_note": site.access_note,
        "pages_attempted": site.pages_attempted,
        "pages_read": len(readable),
        "pages_blocked": site.pages_blocked,
        "page_types": sorted({p.page_type for p in readable}),
        "page_type_counts": dict(Counter(p.page_type for p in readable)),
        "observations": len(observations),
        "image_kinds": dict(img_kinds),
        "content_images": content_images,
        "image_variety": len([k for k, v in img_kinds.items()
                              if k in CONTENT_IMAGE_KINDS and v]),
        "images_without_alt": sum(
            1 for o in observations
            if o.obs_type == ObservationType.IMAGE
            and "no alt text" in (o.interpretation or "")),
        "cta_quality": dict(cta_q),
        "copy_quality": dict(copy_q),
        "jobs_done": sorted(j for j, pk in jobs.items() if pk),
        "jobs_missing": sorted(j for j, pk in jobs.items() if not pk),
        "repeated_headlines": rubric.repetition(all_heads)[:6],
        "repeated_ctas": rubric.repetition(all_ctas, min_len=4)[:6],
        "by_page_type": per_type,
        "pages": [p.to_dict() for p in pages],
    }


def strengths_and_weaknesses(profile: dict) -> dict:
    """Section 6.2's last line: strengths, repeated content, weak messages, gaps.

    Stated about one site on its own terms, before any competitor is involved.
    A site can be weak in a way no competitor exposes, and that is still worth
    saying.
    """
    strong_copy = (profile["copy_quality"].get("strong") or 0)
    weak_copy = (profile["copy_quality"].get("weak") or 0)
    strong_cta = (profile["cta_quality"].get("strong") or 0)
    weak_cta = (profile["cta_quality"].get("weak") or 0)

    strengths, weaknesses = [], []

    if strong_copy and strong_copy >= weak_copy:
        strengths.append(
            f"{strong_copy} of {strong_copy + weak_copy} graded headlines make a "
            f"checkable claim rather than a generic one")
    if weak_copy > strong_copy:
        weaknesses.append(
            f"{weak_copy} headline(s) occupy the position of a message without "
            f"making one — more than the {strong_copy} that do")
    if strong_cta and strong_cta >= weak_cta:
        strengths.append(f"{strong_cta} call(s) to action name the next action")
    if weak_cta:
        weaknesses.append(
            f"{weak_cta} call(s) to action name the click rather than the "
            f"outcome")
    if profile["image_variety"] >= 5:
        strengths.append(
            f"{profile['image_variety']} distinct image types across the pages "
            f"read — the product is shown from more than one angle of interest")
    elif profile["pages_read"]:
        weaknesses.append(
            f"only {profile['image_variety']} distinct content image type(s) "
            f"across {profile['pages_read']} page(s) read")
    if profile["images_without_alt"]:
        weaknesses.append(
            f"{profile['images_without_alt']} image(s) carry no alt text, so a "
            f"screen reader and a search engine both get nothing from them")
    for r in profile["repeated_headlines"][:2]:
        weaknesses.append(
            f"“{r['text'][:70]}” appears {r['count']} times — repetition "
            f"reads as having one thing to say")
    for job in profile["jobs_missing"]:
        weaknesses.append(
            f"nothing on the pages read does the {job.replace('_', ' ')} job")

    return {"strengths": strengths[:8], "weaknesses": weaknesses[:10]}
