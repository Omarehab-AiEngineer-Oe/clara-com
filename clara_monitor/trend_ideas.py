"""Content and commercial ideas per trend — generated, and labelled as generated.

Every other number on the trends page is read from a publisher. Nothing in this
file is. These are suggestions built from the subject's own label and category,
and the page marks them as agent output before the first one appears.

That label is not a disclaimer to be skimmed past. A reader who mistakes
"3 TikTok ideas" for "3 TikTok ideas that are working" has been misled, and no
amount of usefulness makes that acceptable on a page whose whole argument is that
you can tell what is evidence and what is not.

**What is honest about them.** They are derived from the trend's own measured
properties — its category, its stage, its markets, its relevance to what Clara
sells — so a rising nail-art subject produces different ideas from a declining
skincare one. The formats are templates; the subject and the angle are not.

**What they are not.** Not tested, not ranked by performance, not based on any
engagement data. There is no engagement data here to base them on, which is
stated on the page rather than papered over.
"""

from __future__ import annotations

# Per-area angles. What a beauty subject in this area is usually *about* when
# someone makes content on it — the practical question a viewer has.
AREA_ANGLE = {
    "makeup": {
        "demo": "applying it on camera, one product at a time",
        "compare": "the expensive version against the affordable one",
        "teach": "why the technique works, not just the steps",
        "buy": "which product actually delivers the finish",
    },
    "skincare": {
        "demo": "the routine in real time, morning and night",
        "compare": "the active against the gentler alternative",
        "teach": "what the ingredient does and what it cannot do",
        "buy": "what to buy first if you only buy one thing",
    },
    "hair": {
        "demo": "the style start to finish, on unstyled hair",
        "compare": "the salon result against the at-home attempt",
        "teach": "why hair behaves this way and how heat changes it",
        "buy": "which tool the look actually needs",
    },
    "nails": {
        "demo": "the set built up layer by layer",
        "compare": "the salon set against the press-on version",
        "teach": "how to make it last past a week",
        "buy": "the kit that gets closest at home",
    },
    "fragrance": {
        "demo": "how it opens, and what it smells like four hours later",
        "compare": "the designer scent against the affordable alternative",
        "teach": "how the notes are built and why they fade in that order",
        "buy": "what to buy for the price of one designer bottle",
    },
    "beauty_tech": {
        "demo": "using it for two weeks, with the before and after",
        "compare": "the device against doing it by hand",
        "teach": "what the technology does and where the claim stops",
        "buy": "whether the device replaces a product or adds one",
    },
    "beauty_culture": {
        "demo": "the whole look, head to toe",
        "compare": "how the same aesthetic reads in two different markets",
        "teach": "where the aesthetic came from and what it replaced",
        "buy": "the shortest shopping list that gets the look",
    },
}
DEFAULT_ANGLE = AREA_ANGLE["beauty_culture"]

STAGE_FRAMING = {
    "emerging": "before it gets crowded",
    "rising": "while it is still climbing",
    "viral": "while everyone is searching for it",
    "mainstream": "with a take that is not the obvious one",
    "declining": "as a retrospective, or skip it",
}


def _angles(category: str) -> dict:
    return AREA_ANGLE.get(category, DEFAULT_ANGLE)


def content_ideas(topic: dict) -> dict:
    """The content set the brief asks for, built from this subject's own facts."""
    label = topic.get("label") or "this trend"
    cat = topic.get("category") or "beauty_culture"
    a = _angles(cat)
    stage = topic.get("stage") or "emerging"
    framing = STAGE_FRAMING.get(stage, "")
    markets = ", ".join(topic.get("market_labels") or []) or "your market"
    pubs = (topic.get("publishers") or ["the press"])[0]

    return {
        "tiktok": [
            f"{label}: {a['demo']} — no cuts, no voiceover, {framing}",
            f"{label} tested on three different people, same product",
            f"What {pubs} said about {label}, and whether it holds up on camera",
        ],
        "reels": [
            f"{label} in 15 seconds: {a['demo']}",
            f"{a['compare'].capitalize()} — {label}, split screen",
            f"Three ways to wear {label} for {markets}",
        ],
        "youtube": [
            f"{label} explained: {a['teach']}",
            f"I tried {label} for 14 days — what actually changed",
        ],
        "pinterest": [
            f"{label}: a saveable step-by-step, one image per step",
            f"{label} colour and finish reference board for {markets}",
        ],
        "hooks": [
            f"Everyone is doing {label} wrong, and it is one step",
            f"{label} is about to be everywhere — here is the version worth copying",
            f"I did not expect {label} to work on my hair. It did.",
        ],
        "educational": [
            f"{a['teach'].capitalize()} — {label}",
            f"The three mistakes people make with {label}",
            f"Where {label} came from, and who it does not suit",
        ],
        "product": [
            f"{a['buy'].capitalize()} for {label}",
            f"{label} on a budget: the cheapest set-up that works",
            f"What to skip when shopping for {label}",
        ],
        "basis": ("agent-generated from this subject's category, stage and "
                  "markets. Not tested, not ranked by performance, and not based "
                  "on engagement data — there is none here to base them on."),
    }


# What a subject in each area could actually be sold as. Kept per-area rather
# than per-topic because the commercial shape follows the category.
AREA_COMMERCIAL = {
    "makeup": ["colour cosmetics", "application tools and brushes",
               "shade-matching content", "affiliate on base products"],
    "skincare": ["single-active serums", "routine bundles",
                 "ingredient education content", "at-home device attach"],
    "hair": ["styling tools", "heat protection and repair consumables",
             "tool-plus-consumable bundles", "styling tutorial content"],
    "nails": ["press-on and at-home kits", "colour drops",
              "nail-art tutorial content", "affiliate on kits"],
    "fragrance": ["body and hair mists", "layering sets",
                  "affordable alternative positioning", "discovery sets"],
    "beauty_tech": ["at-home devices", "diagnostic front-end on product pages",
                    "subscription or routine model", "device review content"],
    "beauty_culture": ["aesthetic-led bundles", "regional positioning",
                       "audience-specific ranges", "editorial content"],
}


def commercial_ideas(topic: dict, clara_products: list | None = None) -> dict:
    """Where the money could be, with the evidence for it stated.

    Two halves kept apart: what the *measured* signal supports, and what is a
    suggestion. The brief says not to recommend a product because it is popular,
    so each line carries what makes it more than that.
    """
    cat = topic.get("category") or "beauty_culture"
    label = topic.get("label") or "this subject"
    rel = topic.get("clara_relevance") or "context"
    sc = topic.get("score") or {}
    comp = topic.get("competition") or {}
    counts = sc.get("counts") or {}

    evidence = []
    if counts.get("recent_7d"):
        evidence.append(f"{counts['recent_7d']} item(s) published in the last "
                        f"week against {counts.get('prior_21d', 0)} in the three "
                        f"before")
    if (sc.get("components") or {}).get("search"):
        evidence.append("rising search demand attached")
    if comp.get("publishers"):
        evidence.append(f"{comp['publishers']} publisher(s) covering it, which "
                        f"reads as {comp.get('level')} competition")
    if not evidence:
        evidence.append("thin evidence — treat this as a watch item, not a plan")

    fit = {
        "direct": f"Clara already sells into {label}; this is a positioning and "
                  f"pricing decision, not a new category.",
        "adjacent": f"Clara does not sell {label} but sells to the same buyer, so "
                    f"the attach is plausible without a new supply chain.",
        "context": f"Clara does not sell into {label}. Useful for reading where "
                   f"the market is going, not as a product decision.",
    }[rel]

    return {
        "categories": AREA_COMMERCIAL.get(cat, AREA_COMMERCIAL["beauty_culture"]),
        "evidence": evidence,
        "clara_fit": fit,
        "relevance": rel,
        "basis": ("the evidence lines are measured; the category list and the fit "
                  "note are agent suggestions"),
    }


# Which platform a subject is best read on, inferred from where its evidence
# actually came from. A suggestion, not a measurement — and never presented as
# where it is performing, because that would need engagement data.
KIND_PLATFORM = {
    "search_demand": ("Search", "people are typing it, so search and Pinterest "
                                "reward it first"),
    "consumer_press": ("Instagram and TikTok", "consumer press and short video "
                                               "move together"),
    "trade_press": ("LinkedIn and industry press", "a trade story lands with "
                                                   "buyers before consumers"),
    "retail_press": ("Retail and email", "a distribution story matters to "
                                         "shoppers at the point of sale"),
}


def best_platform(topic: dict) -> dict:
    kinds = {e.get("kind") for e in (topic.get("evidence") or []) if e.get("kind")}
    for k in ("search_demand", "consumer_press", "retail_press", "trade_press"):
        if k in kinds:
            name, why = KIND_PLATFORM[k]
            return {"platform": name, "why": why,
                    "basis": "inferred from where the evidence came from, not "
                             "from engagement data"}
    return {"platform": "unclear", "why": "no source kind recorded",
            "basis": "not established"}


AUDIENCE = {
    "makeup": "colour buyers, skewing younger and creator-led",
    "skincare": "routine buyers who read ingredients",
    "hair": "people choosing a tool to reproduce a look",
    "nails": "at-home and salon nail buyers, heavily visual",
    "fragrance": "gifting and self-purchase, strongest in the Gulf",
    "beauty_tech": "early adopters willing to pay for a claim",
    "beauty_culture": "the whole market; this is context rather than a segment",
}


def audience(topic: dict) -> dict:
    cat = topic.get("category") or "beauty_culture"
    return {"audience": AUDIENCE.get(cat, AUDIENCE["beauty_culture"]),
            "basis": "inferred from the category, not from customer data"}
