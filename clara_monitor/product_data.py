"""One Clara product, everything observed about it, and what was never looked at.

The comparator page shows 81 products as cards and opens a modal with the price
comparison. This builds the view behind a page per product, which is a different
job: a card answers "is this one worth opening", a page has to answer "what is
the market doing to this product, and what do we actually know".

Six dimensions were asked for, and they are the six section 6.2 removes from
this system:

    marketing campaigns, advertising, SEO, social media,
    copywriting or content generation, customer acquisition

They are included here as OBSERVATION and refused as OUTPUT, which is the line
6.2 already draws and the reason the agent contracts state it as a verb rather
than a topic: reading a rival's promotion off their page and recording its
wording is evidence, proposing one is not. So `campaigns` and `advertising`
carry what was read from competitor pages; `content` carries what their copy
does; and the three with no instrumentation say so.

**A dimension with no data says so in its own words.** Three of the six have
never been collected — there is no social account reader, no acquisition-channel
data and no SEO index in this system, and §6 of the audit PRD independently puts
SEO rank and backlink intelligence out of scope. Rendering those as empty
sections would make "we never looked" indistinguishable from "the market does
nothing here", which is the absence rule this whole system is built on. Each one
therefore reports its own state and what collecting it would take.
"""

from __future__ import annotations

from decimal import Decimal

from . import competitors as comp, scope
from .money import to_decimal

# Three of the six §6.2 dimensions, in the order they were asked for.
#
# SEO, social media and customer acquisition are not here. They were listed for
# a while as dimensions with no instrument, which read as a gap waiting to be
# filled — and they are not. Section 6.2 removes all six as OUTPUT; for those
# three there is also nothing to OBSERVE, because this system reads competitor
# product pages and none of the three is visible there. SEO is doubly excluded:
# rank and backlink data is out of scope by a second requirement.
#
# Keeping them as permanent "not collected" cards meant every product page
# carried three placeholders for work nobody intends to do. `state` is set per
# product at build time.
DIMENSIONS = (
    {
        "key": "campaigns",
        "label": "Marketing campaigns",
        "collected": True,
        "reads": "Promotion wording on the competitor's own product page, plus "
                 "the storefront sweep of every registered brand.",
        "refuses": "Proposing a campaign for Clara. Section 6.2 removes that "
                   "from this system, and nothing observed here is a plan.",
    },
    {
        "key": "advertising",
        "label": "Advertising",
        "collected": True,
        "reads": "The offer mechanisms a rival is running — a bundle, a gift, a "
                 "coupon, free shipping, a clearance — as written on the page.",
        "refuses": "Buying or planning media. No ad platform is read, so paid "
                   "placement is invisible to this system and is not guessed.",
    },
    {
        "key": "content",
        "label": "Copywriting and content",
        "collected": True,
        "reads": "How the rival's page is written and shown: the product name "
                 "as published, promotion wording, how many images and variants "
                 "the page carries, and what the page states about stock.",
        "refuses": "Writing Clara's copy. The system reports what a rival's page "
                   "says and where Clara's is silent; the sentence itself is a "
                   "person's to write, and 6.2 is what makes that explicit.",
    },
)

DIMENSION = {d["key"]: d for d in DIMENSIONS}


def _dec(v):
    try:
        return to_decimal(v)
    except Exception:                                     # noqa: BLE001
        return None


# --------------------------------------------------------------------------
# only what can be trusted
# --------------------------------------------------------------------------
# The product page carries figures a person may act on, so it states the
# trustworthy ones and nothing else. What "trustworthy" means here is not a
# judgement — every input is a flag the extractor already wrote down:
#
#   status              a counterpart was actually matched, not guessed at
#   extraction_verdict  the read was accepted rather than abandoned
#   stale               the reading is from this cycle
#   invalid_reason      nothing has since invalidated it
#   competitor_price    there is a number at all
#
# Withheld is not hidden. Every record that fails the gate is counted and its
# reason named, because a page that silently shows six of ten counterparts is a
# page asserting the market is smaller than it is — which is the same absence
# rule the rest of this system is built on. The difference the gate makes is
# that the six carry the figures and the four carry an explanation.

# Statuses where a counterpart was genuinely established.
TRUSTED_STATUS = ("confirmed_match", "probable_match")

# Verdicts where the extraction completed. `accepted_with_warnings` is trusted
# and flagged rather than dropped: a warning about stock wording says nothing
# about whether the price was read correctly, and throwing the price away
# because of it would lose good data to an unrelated caveat.
TRUSTED_VERDICT = ("accepted", "accepted_with_warnings")


def trust(match: dict) -> dict:
    """Whether a counterpart's figures can be stated, and why not if they cannot.

    Three levels, because two would force a choice between losing good data and
    presenting caveated data as clean:

        trusted     state the figures
        qualified   state them, with the caveat attached
        withheld    do not state them; say what is missing instead
    """
    reasons = []
    status = match.get("status") or ""
    verdict = match.get("extraction_verdict") or ""

    if status not in TRUSTED_STATUS:
        reasons.append({
            "no_match": "no counterpart was found on their site, so there is "
                        "nothing to compare",
            "ambiguous": "more than one candidate matched and none was "
                         "confirmed, so naming one would be a guess",
            "blocked": "their page could not be read on the last attempt",
        }.get(status, f"the match status is {status or 'unrecorded'}"))

    if verdict and verdict not in TRUSTED_VERDICT:
        reasons.append(f"the extraction was not accepted ({verdict})")
    elif not verdict and status in TRUSTED_STATUS:
        reasons.append("no extraction verdict was recorded, so how the figures "
                       "were read is unknown")

    if match.get("invalid_reason"):
        reasons.append(f"invalidated: {match['invalid_reason']}")

    if match.get("stale"):
        reasons.append("the reading is stale — it is older than the last cycle "
                       "and may no longer be what the page says")

    if status in TRUSTED_STATUS and not match.get("competitor_price"):
        reasons.append("their page publishes no price, so there is no figure "
                       "to state")

    if reasons:
        return {"level": "withheld", "reasons": reasons}

    if match.get("warnings"):
        return {"level": "qualified",
                "reasons": list(match["warnings"])}
    return {"level": "trusted", "reasons": []}


def partition(product: dict) -> dict:
    """Counterparts split by whether their figures can be stated.

    `usable` is what every figure, comparison and suggestion on the page is
    computed from. `withheld` is what the page has to account for instead of
    quietly shrinking around.
    """
    usable, withheld = [], []
    for m in product.get("matches") or []:
        verdict = trust(m)
        row = dict(m)
        row["trust"] = verdict
        (usable if verdict["level"] != "withheld" else withheld).append(row)
    return {
        "usable": usable,
        "withheld": withheld,
        "trusted_n": sum(1 for m in usable if m["trust"]["level"] == "trusted"),
        "qualified_n": sum(1 for m in usable
                           if m["trust"]["level"] == "qualified"),
        "withheld_n": len(withheld),
        "total": len(product.get("matches") or []),
    }


def find(bundle: dict, product_id: str) -> dict | None:
    """The product row from the price bundle, or None."""
    for p in (bundle.get("price") or {}).get("products") or []:
        if p.get("product_id") == product_id:
            return p
    return None


def neighbours(bundle: dict, product: dict) -> list:
    """Other Clara products in the same family, for moving between pages."""
    fam = scope.family_of(product.get("segment"), product.get("category"),
                          product.get("name"))
    out = []
    for p in (bundle.get("price") or {}).get("products") or []:
        if p["product_id"] == product["product_id"]:
            continue
        if scope.family_of(p.get("segment"), p.get("category"),
                           p.get("name")) == fam:
            out.append({"product_id": p["product_id"], "name": p["name"],
                        "clara_price": p.get("clara_price"),
                        "currency": p.get("currency")})
    return out[:8]


def markets(product: dict) -> list:
    """Prices per currency — which is as far as "around the world" honestly goes.

    A currency is not a country and this does not pretend otherwise. What was
    observed is a price on a storefront that quotes in some currency, so the
    rows are grouped by that and labelled by it. A match with no price is counted
    separately rather than left out, because most of them have no price and a
    table that silently drops them would imply the opposite.
    """
    buckets: dict = {}
    unpriced = []
    for m in product.get("matches") or []:
        price = _dec(m.get("competitor_price"))
        cur = (m.get("competitor_currency") or "").strip()
        if price is None or not cur:
            unpriced.append({
                "brand": m.get("competitor_brand"),
                "url": m.get("competitor_url"),
                "status": m.get("status"),
                "why": (m.get("invalid_reason")
                        or ("the page states no price" if not price
                            else "the page states no currency")),
            })
            continue
        row = buckets.setdefault(cur, {"currency": cur, "rows": [],
                                       "low": None, "high": None})
        row["rows"].append({
            "brand": m.get("competitor_brand"),
            "product": m.get("competitor_product_name"),
            "url": m.get("competitor_url"),
            "price": price,
            "availability": m.get("availability"),
            "observed_at": m.get("observed_at"),
            "stale": m.get("stale"),
            "status": m.get("status"),
            "same_currency": m.get("same_currency"),
            "multiple_of_clara": m.get("multiple_of_clara"),
            "delta_pct": m.get("delta_pct_vs_clara"),
        })
        row["low"] = price if row["low"] is None else min(row["low"], price)
        row["high"] = price if row["high"] is None else max(row["high"], price)

    clara_cur = (product.get("currency") or "").strip()
    out = []
    for cur, row in buckets.items():
        row["rows"].sort(key=lambda r: r["price"])
        row["n"] = len(row["rows"])
        # Clara's price only belongs in the column that quotes the same
        # currency. Converting is what would make this a world price map, and
        # converting is exactly what the system refuses to do.
        row["is_clara_currency"] = (cur == clara_cur)
        row["clara_price"] = product.get("clara_price") \
            if row["is_clara_currency"] else None
        row["comparable"] = row["is_clara_currency"]
        out.append(row)
    # Clara's own currency first, then by how much was observed.
    out.sort(key=lambda r: (not r["is_clara_currency"], -r["n"], r["currency"]))
    return [{"priced": out, "unpriced": unpriced}][0]


def campaign_rows(bundle: dict, product: dict) -> list:
    """Promotion wording read off the rival product pages for THIS product.

    Product-level, so it is the only campaign evidence that can be attributed to
    a comparison. The storefront sweep is broader but brand-level: a banner has
    no product behind it, which is the whole reason `offer_sweep` keeps the two
    apart, and mixing them here would attach a site-wide banner to one dryer.
    """
    rows = []
    for m in product.get("matches") or []:
        text = (m.get("promotion_text") or "").strip()
        if not text:
            continue
        rows.append({
            "brand": m.get("competitor_brand"),
            "wording": text,
            "url": m.get("competitor_url"),
            "observed_at": m.get("observed_at"),
            "discount_percent": m.get("discount_percent"),
            "regular_price": m.get("regular_price"),
            "price": m.get("competitor_price"),
            "currency": m.get("competitor_currency"),
        })
    return rows


def storefront_rows(bundle: dict, product: dict) -> dict:
    """Brand-level storefront advertising for the brands assigned to THIS product.

    Labelled as brand-level everywhere it is shown. It answers "what is this
    rival promoting at all", never "what is this rival promoting on this
    product", and the distinction is the difference between evidence and a
    plausible-sounding invention.
    """
    sweep = bundle.get("sweep") or {}
    by_brand = sweep.get("by_competitor") or {}
    assigned = {(m.get("competitor_key") or "")
                for m in product.get("matches") or []}
    assigned |= {k for k in (product.get("assigned_competitors") or [])}

    # `assigned_competitors` holds display names in some bundles and keys in
    # others; resolve both so a brand is not missed for being spelled twice.
    keys = set()
    for a in assigned:
        if not a:
            continue
        keys.add(a)
        c = comp.get(a)
        if c:
            keys.add(c.brand)

    rows, mechanisms = [], {}
    for brand, offers in by_brand.items():
        key = (offers[0].get("competitor_key") if offers else "") or ""
        if brand not in keys and key not in keys:
            continue
        for o in offers:
            for mech in (o.get("mechanism") or "").split(","):
                mech = mech.strip()
                if mech:
                    mechanisms[mech] = mechanisms.get(mech, 0) + 1
        rows.append({"brand": brand, "offers": offers})
    rows.sort(key=lambda r: (-len(r["offers"]), r["brand"]))
    return {"rows": rows,
            "mechanisms": sorted(mechanisms.items(), key=lambda kv: -kv[1]),
            "brands_swept": len(rows),
            "brands_assigned": len([k for k in keys if comp.get(k)])}


def content_rows(product: dict) -> dict:
    """What each rival's page does, and what Clara's row does not say.

    Everything here is a count or a published string. There is no score, because
    a score would need Clara's page read side by side and Clara's site answered
    a CAPTCHA on both website-analysis runs — so the comparison that would
    justify a score does not exist yet, and is reported as missing rather than
    approximated.
    """
    rows = []
    for m in product.get("matches") or []:
        rows.append({
            "brand": m.get("competitor_brand"),
            "published_name": m.get("competitor_product_name"),
            "name_words": len((m.get("competitor_product_name") or "").split()),
            "images": m.get("image_count"),
            "variants": m.get("variant_count"),
            "availability": m.get("availability"),
            "promotion": (m.get("promotion_text") or "").strip(),
            "method": m.get("method"),
            "url": m.get("competitor_url"),
            "status": m.get("status"),
        })
    rows.sort(key=lambda r: -(r["images"] or 0))

    stated = [r for r in rows if r["images"]]
    return {
        "rows": rows,
        "clara": {
            "name": product.get("name"),
            "name_words": len((product.get("name") or "").split()),
            "images": 1 if product.get("image_url") else 0,
            "images_note": ("the catalogue records one image per product, so "
                            "this is not a count of what the page shows"),
            "specs_published": len(product.get("specs") or {}),
            "rating": product.get("rating"),
            "rating_count": product.get("rating_count"),
            "language": product.get("description_lang"),
        },
        "rival_image_median": (
            sorted(r["images"] for r in stated)[len(stated) // 2]
            if stated else None),
        "rivals_with_images": len(stated),
        "rivals_total": len(rows),
    }


def brief(product: dict, mk: dict, camp: list, store: dict,
          content: dict) -> list:
    """What a person would need to decide, drawn only from what was observed.

    This is the answer to "what is the best content", and it is deliberately not
    content. Section 6.2 removes copywriting and content generation from this
    system, so what it produces is a brief: the observation, what is missing
    from Clara's side, and the decision that is a person's to make. Each line
    carries the evidence it came from, and a line with no evidence is not here.
    """
    out = []
    priced = mk.get("priced") or []
    comparable = [r for r in priced if r["comparable"]]
    clara = _dec(product.get("clara_price"))

    if comparable and clara:
        row = comparable[0]
        cheapest = row["rows"][0]
        if cheapest["price"] > clara:
            out.append({
                "dimension": "campaigns",
                "observed": f"The cheapest comparable rival in "
                            f"{row['currency']} is {cheapest['brand']} at "
                            f"{cheapest['price']}, against Clara at {clara}.",
                "decision": "Whether Clara's page states the price advantage "
                            "at all. The advantage is observed; saying it is a "
                            "copy decision and 6.2 leaves it with a person.",
                "evidence": cheapest["url"],
            })
        else:
            out.append({
                "dimension": "campaigns",
                "observed": f"{cheapest['brand']} is cheaper than Clara in "
                            f"{row['currency']}: {cheapest['price']} against "
                            f"{clara}.",
                "decision": "Whether the page argues value on something other "
                            "than price, and what the evidence for it is.",
                "evidence": cheapest["url"],
            })

    if store.get("mechanisms"):
        top = store["mechanisms"][:3]
        named = ", ".join(f"{k.replace('_', ' ')} ({v})" for k, v in top)
        out.append({
            "dimension": "advertising",
            "observed": f"Across the {store['brands_swept']} assigned brand(s) "
                        f"whose storefront answered, the recurring mechanisms "
                        f"are {named}. These are storefront-wide, not attached "
                        f"to this product.",
            "decision": "Whether Clara runs a mechanism the market treats as "
                        "standard. Running one is a commercial decision, and "
                        "6.2 puts the campaign itself outside this system.",
            "evidence": "storefront sweep",
        })

    if content.get("rival_image_median") is not None:
        med = content["rival_image_median"]
        out.append({
            "dimension": "content",
            "observed": f"Rival pages for this product carry a median of {med} "
                        f"image(s) ({content['rivals_with_images']} of "
                        f"{content['rivals_total']} state a count). Clara's "
                        f"catalogue row records "
                        f"{content['clara']['images']}, which counts the "
                        f"catalogue image and not the page.",
            "decision": "Whether Clara's product page shows as much as the "
                        "market does. This needs Clara's page read, and it has "
                        "not been: both website-analysis runs were stopped by a "
                        "CAPTCHA on clarahair.com.",
            "evidence": "match extraction",
        })

    if camp:
        out.append({
            "dimension": "content",
            "observed": f"{len(camp)} rival page(s) for this product carry "
                        f"promotion wording. The first reads: "
                        f"“{camp[0]['wording'][:120]}”",
            "decision": "What Clara's equivalent claim is, and whether there is "
                        "evidence for it. Writing the sentence is copywriting "
                        "and stays with a person.",
            "evidence": camp[0]["url"],
        })

    if mk.get("unpriced"):
        out.append({
            "dimension": "campaigns",
            "observed": f"{len(mk['unpriced'])} assigned rival(s) publish no "
                        f"price for this product, so no comparison was made "
                        f"for them.",
            "decision": "Whether a retail surface should be read instead. Until "
                        "then this is a gap in coverage and not a finding about "
                        "their pricing.",
            "evidence": "",
        })
    return out


def build(bundle: dict, product_id: str) -> dict:
    """The whole page view for one product."""
    product = find(bundle, product_id)
    if not product:
        return {"product": None, "product_id": product_id}

    # Everything below is computed from the counterparts whose figures can be
    # stated. A comparison built on a stale reading, or on a match nobody
    # confirmed, is a number that looks exactly like a good one — which is the
    # whole reason for the gate. The rest is carried through as `withheld` and
    # accounted for on the page rather than dropped.
    split = partition(product)
    usable = dict(product, matches=split["usable"])

    mk = markets(usable)
    camp = campaign_rows(bundle, usable)
    store = storefront_rows(bundle, usable)
    content = content_rows(usable)

    fam = scope.family_of(product.get("segment"), product.get("category"),
                          product.get("name"))

    # Per-dimension state, so the page never shows an empty section that could
    # be read as "the market does nothing here".
    dims = []
    for d in DIMENSIONS:
        row = dict(d)
        if not d["collected"]:
            row["state"] = "not_collected"
            row["count"] = 0
        elif d["key"] == "campaigns":
            row["state"] = "observed" if camp else "none_observed"
            row["count"] = len(camp)
        elif d["key"] == "advertising":
            row["state"] = "observed" if store["rows"] else "none_observed"
            row["count"] = sum(len(r["offers"]) for r in store["rows"])
        else:
            row["state"] = "observed" if content["rows"] else "none_observed"
            row["count"] = len(content["rows"])
        dims.append(row)

    return {
        "product": product,
        "product_id": product_id,
        "family": fam,
        "family_label": scope.family_label(fam),
        "markets": mk,
        "campaigns": camp,
        "storefront": store,
        "content": content,
        "dimensions": dims,
        "brief": brief(usable, mk, camp, store, content),
        "enhancements": enhancements(bundle, usable, mk, camp, content),
        "sources": sources(bundle, product),
        "trust": split,
        "neighbours": neighbours(bundle, product),
        "generated_at": (bundle.get("price") or {}).get("generated_at", ""),
    }


# --------------------------------------------------------------------------
# how this product could be improved
# --------------------------------------------------------------------------
# Every line below is arithmetic on observed data. None of it is a campaign, an
# advertisement or a sentence of copy: 6.2 removes those, and the difference is
# that a spec Clara does not publish is a fact about the catalogue, while the
# paragraph describing it is a person's to write.

SPEC_LABEL = {
    "power_w": "power in watts", "heat_settings": "heat settings",
    "ionic": "ionic", "attachment_count": "attachment count",
    "voltage": "voltage", "auto_off_min": "auto shut-off",
    "bldc_motor": "BLDC motor", "cold_shot": "cold shot",
    "temperatures_c": "temperature settings",
}

# A spec is only "usually published" once enough peers publish it. Below this
# there is no norm to be missing from — two products agreeing is not a standard.
PEER_MIN = 3
PEER_SHARE = 0.60

# `extract_specs` sets these three on every product, as `bool(re.search(...))`.
# They are therefore never absent, and a `False` means "the page text does not
# mention the feature" — which is not the same as "the field is unpublished".
# Treating False as a gap produced "Publish ionic on this product's page" for
# products that simply are not ionic. Since nothing here can separate "not
# ionic" from "ionic but unstated", they are excluded from gap detection rather
# than guessed at.
ALWAYS_SET = ("ionic", "bldc_motor", "cold_shot")


def spec_gaps(bundle: dict, product: dict) -> list:
    """Specs this product's own format-peers publish and it does not.

    An internal comparison, and deliberately so. Rival specs are not in the
    match record — only price, stock and page shape are — so a claim about how
    Clara compares on wattage would have nothing behind it. What can be measured
    is Clara against Clara: eleven other multi-stylers state their wattage and
    this one does not, which is a catalogue gap and needs no competitor at all.
    """
    fmt = product.get("fmt") or ""
    if not fmt or fmt == "unknown":
        return []
    peers = [p for p in (bundle.get("price") or {}).get("products") or []
             if p.get("fmt") == fmt and p["product_id"] != product["product_id"]]
    if len(peers) + 1 < PEER_MIN:
        return []

    def published(specs):
        return {k for k, v in (specs or {}).items()
                if v is not None and k not in ALWAYS_SET}

    mine = published(product.get("specs"))
    counts: dict = {}
    for p in peers:
        for k in published(p.get("specs")):
            counts[k] = counts.get(k, 0) + 1

    out = []
    for key, n in sorted(counts.items(), key=lambda kv: -kv[1]):
        if key in mine or key in ALWAYS_SET:
            continue
        if n / len(peers) < PEER_SHARE:
            continue
        out.append({"spec": key, "label": SPEC_LABEL.get(key, key),
                    "peers_with": n, "peers": len(peers)})
    return out


def enhancements(bundle: dict, product: dict, mk: dict, camp: list,
                 content: dict) -> list:
    """Concrete ways this product could be improved, each from observed data.

    Ordered by how much evidence stands behind it, not by how appealing it
    sounds. Each carries what was observed, the change, and how to tell whether
    the change worked — a suggestion with no way to check it is a wish, and §17
    of the audit PRD refuses those for the same reason.
    """
    out = []
    for g in spec_gaps(bundle, product):
        fmt_words = (product.get("fmt") or "").replace("_", " ")
        out.append({
            "area": "catalogue data",
            "observed": f"{g['peers_with']} of {g['peers']} other {fmt_words} "
                        f"product(s) publish {g['label']}; this one does not.",
            "change": f"Publish {g['label']} on this product's page.",
            "validate": "The field appears in the next catalogue read, and the "
                        "spec count on this page goes up by one.",
            "evidence": "Clara catalogue",
            "weight": g["peers_with"],
        })

    med = content.get("rival_image_median")
    if med and content["clara"]["images"] < med:
        out.append({
            "area": "product page",
            "observed": f"Rival pages for this product show a median of {med} "
                        f"image(s). Clara's catalogue row records "
                        f"{content['clara']['images']}.",
            "change": "Check how many images the live page actually shows. The "
                      "catalogue row counts one image, so this is a measurement "
                      "gap before it is a content gap.",
            "validate": "A read of Clara's own product page that is not stopped "
                        "by the CAPTCHA, giving a real count to compare.",
            "evidence": "match extraction",
            "weight": med,
        })

    variants = [r["variants"] for r in content["rows"] if r.get("variants")]
    if variants and max(variants) > 1:
        out.append({
            "area": "product page",
            "observed": f"A rival offers {max(variants)} purchasable option(s) "
                        f"on one page. Clara's record holds no option count for "
                        f"this product.",
            "change": "Record whether this product has variants, and publish "
                      "them if it does.",
            "validate": "An option count appears on the Clara row, so the "
                        "comparison becomes possible either way.",
            "evidence": "match extraction",
            "weight": max(variants),
        })

    rc = product.get("rating_count") or 0
    all_rc = [p.get("rating_count") or 0
              for p in (bundle.get("price") or {}).get("products") or []
              if p.get("rating_count")]
    if all_rc:
        median_rc = sorted(all_rc)[len(all_rc) // 2]
        if rc < median_rc:
            out.append({
                "area": "proof",
                "observed": f"This product has {rc} review(s). The median across "
                            f"the {len(all_rc)} rated product(s) in the "
                            f"catalogue is {median_rc}.",
                "change": "Collect more reviews on this product specifically.",
                "validate": "The review count rises above the catalogue median.",
                "evidence": "Clara catalogue",
                "weight": median_rc - rc,
            })

    priced = [r for r in (mk.get("priced") or []) if r["comparable"]]
    if priced and product.get("clara_price"):
        rows = priced[0]["rows"]
        clara = _dec(product["clara_price"])
        cheaper = [r for r in rows if clara is not None and r["price"] < clara]
        if cheaper:
            out.append({
                "area": "price position",
                "observed": f"{len(cheaper)} of {len(rows)} comparable rival(s) "
                            f"in {priced[0]['currency']} are cheaper than "
                            f"Clara, the lowest at {cheaper[0]['price']}.",
                "change": "Decide whether the gap is defensible on what the "
                          "page can prove — specs, warranty, reviews — or "
                          "whether the price is the thing to change.",
                "validate": "Either a published difference a buyer can check, "
                            "or a price move. Both are observable next run.",
                "evidence": cheaper[0].get("url") or "",
                "weight": len(cheaper) * 2,
            })

    unp = mk.get("unpriced") or []
    if unp:
        out.append({
            "area": "coverage",
            "observed": f"{len(unp)} assigned rival(s) publish no price for "
                        f"this product, so they are in no comparison.",
            "change": "Read a retail surface for those brands instead of their "
                      "own site.",
            "validate": "The comparable count on this page rises. Until it "
                        "does, this is a gap in what was looked at.",
            "evidence": "",
            "weight": len(unp),
        })

    warned = [r for r in (product.get("matches") or []) if r.get("warnings")]
    if warned:
        out.append({
            "area": "data quality",
            "observed": f"{len(warned)} counterpart record(s) carry a warning "
                        f"about how they were read.",
            "change": "Resolve the warning before the number is used in a "
                      "decision. `clara_monitor.validate` reports any note that "
                      "no longer matches its own data.",
            "validate": "The warning count on this page falls to zero, or each "
                        "remaining one is a fact about the source rather than "
                        "about the reading.",
            "evidence": "",
            "weight": len(warned),
        })

    out.sort(key=lambda r: -r["weight"])
    return out


def sources(bundle: dict, product: dict) -> list:
    """Every source that fed this page, and how fresh each one is.

    A page assembled from six sources of different ages, presenting one date, is
    the thing this replaces. Each row says what it covers, when it was last read
    and whether anything came back — because "read yesterday and empty" and
    "never read" lead to opposite actions and a single timestamp hides which one
    you are looking at.
    """
    rows = []
    price = bundle.get("price") or {}
    rows.append({
        "source": "Clara catalogue",
        "covers": "name, price, specs, rating, image",
        "read_at": price.get("generated_at", ""),
        "n": 1,
        "state": "read",
        "note": "",
    })

    matches = product.get("matches") or []
    seen = [m.get("observed_at") for m in matches if m.get("observed_at")]
    stale_n = sum(1 for m in matches if m.get("stale"))
    rows.append({
        "source": "Competitor product pages",
        "covers": "rival price, stock, promotion wording, page shape",
        "read_at": max(seen) if seen else "",
        "n": len(matches),
        "state": "read" if seen else ("no counterpart" if matches
                                      else "nothing assigned"),
        "note": (f"{stale_n} of {len(matches)} reading(s) marked stale"
                 if stale_n else ""),
    })

    offers = [o for o in (bundle.get("offers") or {}).get("offers") or []
              if o.get("clara_product") in (product.get("name"),
                                            product.get("product_id"))]
    rows.append({
        "source": "Product-level offers",
        "covers": "a rival offer tied to this product",
        "read_at": max((o.get("seen_at") or "") for o in offers)
        if offers else "",
        "n": len(offers),
        "state": "read" if offers else "none found",
        "note": "",
    })

    store = storefront_rows(bundle, product)
    stamps = [o.get("last_seen_at") for r in store["rows"]
              for o in r["offers"] if o.get("last_seen_at")]
    rows.append({
        "source": "Competitor storefronts",
        "covers": "brand-wide advertising, not tied to this product",
        "read_at": max(stamps) if stamps else "",
        "n": store["brands_swept"],
        "state": "read" if stamps else "no storefront answered",
        "note": "storefront-wide, so it is never attributed to this product",
    })

    changes = [c for c in (bundle.get("changes") or {}).get("changes") or []
               if c.get("clara_product_id") == product.get("product_id")]
    rows.append({
        "source": "Change events",
        "covers": "what moved since the previous run",
        "read_at": max((c.get("detected_at") or "") for c in changes)
        if changes else "",
        "n": len(changes),
        "state": "read" if changes else "nothing changed",
        "note": "",
    })

    # The one source that has never returned anything, for any product.
    rows.append({
        "source": "Clara's own pages",
        "covers": "Clara's copy, CTAs and trust signals — the other half of "
                  "every content comparison",
        "read_at": "",
        "n": 0,
        "state": "blocked",
        "note": "both website-analysis runs were stopped by a CAPTCHA on "
                "clarahair.com, so no content score is computed anywhere on "
                "this page",
    })
    return rows
