"""The intelligence-cycle sections, rendered onto the competitors page.

These used to be their own page. They belong here: someone looking at competitor
prices is exactly the person who needs to know what to do about them, what
promotions are running right now, and which companies were spotted but are not
yet being tracked. A separate page meant the tasks lived somewhere nobody had a
reason to open.

Three blocks:

    Live competitor offers   the only offers section: promotions confirmed
                             running, plus what ended and what could not be
                             confirmed, with the Clara product each competes with
    Decisions to make        every call someone has to make — from competitor
                             moves and from market trends, in one list
    Refused pairings         what the cycle would not compute, and why

The discovery watchlist was removed from the page at the operator's request.
Discovery still runs and still records what it finds in `reports/intel_*.json`;
it simply no longer takes up a section.

Every block carries when it was last updated — a relative clock for scanning,
with the absolute day in the tooltip so it can always be checked. Empty is a
legitimate state for all four and each says so in its own words, because "no
tasks" and "nobody looked" are opposite facts that a blank space cannot tell
apart.

.swbrand{background:var(--card);border:1px solid var(--line);border-radius:7px;
         padding:13px 15px}
.swbrand .sb{font-weight:700;font-size:14px;display:flex;gap:8px;
             align-items:baseline;flex-wrap:wrap;margin-bottom:8px}
.swbrand .sbn{font-size:11px;color:var(--ink3);font-weight:600}
.swline{display:flex;gap:9px;align-items:baseline;padding:7px 0;
        border-top:1px solid var(--line);font-size:12.5px;line-height:1.55}
.swline:first-of-type{border-top:0}
.swmech{font-size:9.5px;font-weight:700;letter-spacing:.03em;padding:2px 6px;
        border-radius:3px;background:var(--card3);color:var(--ink2);
        white-space:nowrap;flex:0 0 auto}
.swtext{color:var(--ink);flex:1 1 auto;min-width:0}
.swline a{font-size:11.5px;color:var(--rival);text-decoration:none;
          white-space:nowrap;flex:0 0 auto}
.swline a:hover{text-decoration:underline}
.swgrid{display:grid;grid-template-columns:repeat(auto-fit,minmax(340px,1fr));
        gap:11px;margin-top:14px}
"""

from __future__ import annotations

import html
from datetime import datetime, timezone

INTEL_CSS = """
.isec{padding:34px 0;border-top:1px solid var(--line)}
.iwrap{max-width:1220px;margin:0 auto;padding:0 22px}
.updated{font-size:11.5px;color:var(--ink3);white-space:nowrap}
.updated b{color:var(--ink2);font-weight:600}
.updated span[title]{border-bottom:1px dotted var(--line2);cursor:help}

.acard{background:var(--card);border:1px solid var(--line);
       border-inline-start:3px solid var(--clara);border-radius:6px;
       padding:15px 17px;margin-bottom:11px}
.acard .ah{display:flex;gap:9px;align-items:center;flex-wrap:wrap;margin-bottom:7px}
.acard .aw{font-size:14.5px;line-height:1.6;font-weight:600}
.acard .ab{font-size:12.5px;color:var(--ink2);line-height:1.6;margin-top:8px}
.acard .ae{font-size:12px;color:var(--ink3);line-height:1.6;margin-top:6px}
.acard .al{margin-top:9px;display:flex;gap:7px;flex-wrap:wrap}
.acard .al a{font-size:12px;color:var(--rival);text-decoration:none;
             border:1px solid var(--line2);border-radius:4px;padding:4px 9px}
.acard .al a:hover{border-color:var(--rival)}

.ipill{font-size:10px;font-weight:700;padding:2px 7px;border-radius:3px;
       letter-spacing:.02em;white-space:nowrap}
.iu-now{background:var(--bad-wash);color:var(--bad)}
.iu-this_week{background:var(--amb-wash);color:var(--amb)}
.iu-this_month{background:var(--rival-wash);color:var(--rival)}
.iu-watch{background:var(--card3);color:var(--ink3)}
.ic-HIGH{background:var(--ok-wash);color:var(--ok)}
.ic-MEDIUM{background:var(--amb-wash);color:var(--amb)}
.ic-LOW{background:var(--card3);color:var(--ink3)}
.ic-UNVERIFIED{background:var(--bad-wash);color:var(--bad)}

.lgrid{display:grid;grid-template-columns:repeat(auto-fit,minmax(290px,1fr));gap:12px}
.lcard{background:var(--card);border:1px solid var(--line);border-radius:6px;
       padding:14px 16px}
.lcard .lh{display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-bottom:6px}
.lcard .lb{font-weight:700;font-size:14.5px}
.lcard .lt{font-size:13px;line-height:1.55;margin-bottom:8px}
.lcard .lp{display:flex;gap:11px;align-items:baseline;flex-wrap:wrap}
.lcard .now{font-size:19px;font-weight:700;color:var(--clara)}
.lcard .was{font-size:12.5px;color:var(--ink3);text-decoration:line-through}
.lcard .cut{font-size:11.5px;font-weight:700;color:var(--ok);
            background:var(--ok-wash);padding:2px 7px;border-radius:3px}
.lcard .lm{font-size:11.5px;color:var(--ink3);margin-top:8px;line-height:1.55}
.lcard .lm a{color:var(--rival);text-decoration:none}

.iempty{background:var(--card2);border:1px dashed var(--line2);border-radius:6px;
        padding:16px 18px;font-size:13px;color:var(--ink2);line-height:1.65}
.iempty b{color:var(--ink)}

.origin{font-size:10px;font-weight:700;padding:2px 7px;border-radius:3px;
        letter-spacing:.02em;white-space:nowrap;background:var(--card3);
        color:var(--ink2)}
.origin.trend{background:var(--rival-wash);color:var(--rival)}
.acard.fromtrend{border-inline-start-color:var(--rival)}
"""

URGENCY_LABEL = {"now": "now", "this_week": "this week",
                 "this_month": "this month", "watch": "watch"}


def _e(v) -> str:
    return html.escape(str(v if v is not None else ""))


def _parse(stamp: str):
    if not stamp:
        return None
    try:
        dt = datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def ago(stamp: str) -> str:
    dt = _parse(stamp)
    if not dt:
        return "unknown"
    secs = (datetime.now(timezone.utc) - dt).total_seconds()
    if secs < 90:
        return "just now"
    if secs < 3600:
        return f"{int(secs // 60)} min ago"
    if secs < 86400:
        h = int(secs // 3600)
        return f"{h} hour{'s' if h != 1 else ''} ago"
    days = int(secs // 86400)
    if days == 1:
        return "yesterday"
    if days < 7:
        return f"{days} days ago"
    if days < 30:
        w = days // 7
        return f"{w} week{'s' if w != 1 else ''} ago"
    m = days // 30
    return f"{m} month{'s' if m != 1 else ''} ago"


def when(stamp: str) -> str:
    dt = _parse(stamp)
    return dt.strftime("%a %d %b %Y, %H:%M UTC") if dt else "unknown"


def updated(stamp: str, label: str = "updated") -> str:
    """The stamp that appears on every section and card.

    Relative for scanning, absolute in the tooltip, because a reader deciding
    whether to act on a price needs to know whether it is an hour old or a month
    old, and a relative clock alone cannot be checked.
    """
    return (f'<span class="updated"><b>{_e(label)}</b> '
            f'<span title="{_e(when(stamp))}">{_e(ago(stamp))}</span></span>')


# --------------------------------------------------------------------------

def _head(title: str, eyebrow: str, stamp: str) -> str:
    return ('<div class="shead"><h2>' + _e(title) + '</h2>'
            '<p class="eyebrow">' + _e(eyebrow) + ' &middot; '
            + updated(stamp) + '</p></div>')


def decision_items(bundle: dict, trends: dict | None = None) -> list[dict]:
    """Every call someone has to make, from both inputs, as plain data.

    Two inputs, one list. The cycle raises decisions from what competitors
    actually did; the trend scan raises them from what the market is moving on.
    Splitting them into two lists would split by *which subsystem noticed*, which
    is not a distinction a reader has any use for — so the origin rides on each
    item instead and both are ordered together.

    Returns data, not markup. `decisions_page` owns the layout; keeping the two
    apart is what lets the same list be counted in a tile and rendered in a card
    without the numbers drifting.
    """
    intel = bundle.get("intel") or {}
    cycle_rows = intel.get("actions_needed") or []
    trend_rows = _trend_steps(bundle, trends)

    pairs = ((bundle.get("intel") or {}).get("summary") or {})
    price_pairs = _price_pairs(bundle)
    brand_keys = _brand_keys(bundle)
    live_offers = _offers_by_competitor(bundle)

    items = []
    for a in cycle_rows:
        entity = a.get("entity") or ""
        pair = price_pairs.get(entity) or {}
        gap = pair.get("gap_percent")
        items.append({
            "origin": "competitor move",
            "trend": False,
            "urgency": a.get("urgency") or "watch",
            "owner": a.get("owner"),
            "confidence": a.get("confidence"),
            "entity": entity,
            # The drill-down keys. Without these a link back to the evidence is
            # a guess at a URL rather than a route to the row that argued for it.
            # A drill-down key, from the price pairing where one exists and from
            # the registry otherwise. A competitor decision that cannot reach its
            # own row is an assertion, so this falls back rather than giving up.
            "competitor_key": (pair.get("competitor_key")
                               or brand_keys.get(entity.strip().lower(), "")),
            "topic_key": "",
            "what": a.get("action"),
            "why": a.get("because"),
            "done": a.get("expected_outcome"),
            "links": a.get("links") or [],
            "note": "",
            # The insight: one sentence, and it has to be the one a reader would
            # repeat to someone else.
            "insight": _competitor_insight(entity, pair, a,
                                           live_offers.get(entity)),
            "gap_percent": gap,
            "metrics": (_competitor_metrics(pair)
                        or _offer_metrics(live_offers.get(entity))),
            "relevant": {
                "comparison": (f"{pair.get('clara_name')} vs "
                               f"{pair.get('competitor_product') or entity}"
                               if pair.get("clara_name") else ""),
                "trend": "",
            },
        })
    for st in trend_rows:
        items.append({
            "origin": "market trend",
            "trend": True,
            # A trend is a window, not an event, so it is never "now".
            "urgency": "this_month",
            "owner": st["owner"],
            "confidence": st["confidence"],
            "entity": st["topic"],
            "competitor_key": "",
            "topic_key": st.get("topic_key") or "",
            "what": st["step"],
            "why": st["why"],
            "done": "",
            "links": [l for l in (
                {"label": st.get("product"), "url": st.get("product_url")},
                {"label": st.get("source_publisher") or "source",
                 "url": st.get("source_url")},
            ) if l.get("url")],
            "note": (f'Seen in {st["markets"]} &middot; carried by '
                     f'{st["publishers"]} &middot; last moved '
                     f'{st["changed_ago"]}'),
            "insight": _trend_insight(st),
            "stage": st.get("stage"),
            "gap_percent": None,
            "metrics": _trend_metrics(st),
            "relevant": {
                "comparison": st.get("product") or "",
                "trend": st.get("topic") or "",
            },
        })

    from .ui import IMPACT_ORDER, impact_of
    for i in items:
        i["impact"], i["impact_why"] = impact_of(i)

    # Impact first, then urgency. A critical call that is technically due next
    # month still belongs above a routine one due this week.
    order = {"now": 0, "this_week": 1, "this_month": 2, "watch": 3}
    items.sort(key=lambda i: (IMPACT_ORDER.index(i["impact"]),
                              order.get(i["urgency"], 9),
                              -Confidence_rank(i["confidence"])))
    return items


def _brand_keys(bundle: dict) -> dict:
    """Competitor brand name -> registry key, lowercased for matching.

    A cycle names competitors by brand; the comparator addresses them by key.
    Without this map a decision about a competitor with no stored price pairing
    has nowhere to link, which is exactly the case where a reader most wants to
    go and look.
    """
    rows = (bundle.get("competitors") or {}).get("competitors") or []
    out: dict = {}
    for c in rows:
        key = c.get("key")
        if not key:
            continue
        for name in (c.get("brand"), key):
            if name:
                out.setdefault(str(name).strip().lower(), key)
    return out


def _price_pairs(bundle: dict) -> dict:
    """Competitor -> the Clara pairing and the gap, read off the price report.

    A gap appears only where a stored match holds and both sides publish the
    same currency, so a decision can never quote a converted figure.
    """
    out: dict = {}
    for prod in (bundle.get("price") or {}).get("products") or []:
        for m in prod.get("matches") or []:
            brand = m.get("competitor_brand")
            if not brand or brand in out:
                continue
            if m.get("status") not in ("confirmed_match", "probable_match"):
                continue
            pct = m.get("delta_pct_vs_clara")
            out[brand] = {
                "competitor_key": m.get("competitor_key") or "",
                "clara_name": prod.get("name"),
                "clara_price": prod.get("clara_price"),
                "currency": prod.get("currency") or "SAR",
                "competitor_product": m.get("competitor_product_name"),
                "competitor_price": m.get("competitor_price"),
                "competitor_currency": m.get("competitor_currency"),
                "gap_percent": (float(pct) if pct is not None
                                and m.get("same_currency") else None),
                "url": m.get("competitor_url"),
                "same_currency": bool(m.get("same_currency")),
            }
    return out


def _offers_by_competitor(bundle: dict) -> dict:
    """The live offer per competitor, strongest first.

    A decision about a promotion should be able to show the promotion's own
    numbers. Without this the card is a sentence with nothing under it, which is
    exactly the shape a reader learns to skip.
    """
    out: dict = {}
    for o in ((bundle.get("intel") or {}).get("live_competitor_offers") or []):
        name = o.get("competitor")
        if name and name not in out:
            out[name] = o
    return out


def _offer_metrics(offer: dict | None) -> list[dict]:
    """The numbers printed on a promotion. Only what was printed."""
    if not offer:
        return []
    out = []
    cur = offer.get("currency") or ""
    if offer.get("current_price"):
        out.append({"value": f"{offer['current_price']} {cur}".strip(),
                    "key": "Their offer price",
                    "note": (offer.get("product") or "")[:34], "tone": "hero"})
    if offer.get("original_price"):
        out.append({"value": f"{offer['original_price']} {cur}".strip(),
                    "key": "Printed was-price", "note": "on the same page",
                    "tone": "neutral"})
    if offer.get("discount"):
        out.append({"value": f"{offer['discount']}", "key": "Printed discount",
                    "note": "as advertised", "tone": "down"})
    if offer.get("status"):
        out.append({"value": str(offer["status"]).title(), "key": "Offer state",
                    "note": ("still on the page" if offer["status"] == "ACTIVE"
                             else "changed since last cycle"),
                    "tone": "neutral"})
    return out


def _competitor_insight(entity: str, pair: dict, action: dict,
                        offer: dict | None = None) -> str:
    """One sentence a reader would repeat to a colleague.

    Leads with the number where there is one, because that is what makes it
    repeatable. Where the currencies differ it says so rather than quoting a gap
    that does not exist.
    """
    gap = pair.get("gap_percent")
    if gap is not None and pair.get("clara_name"):
        # delta is the competitor measured against Clara, so a positive number
        # means they cost more. Stated as a multiple past +100%, because
        # "199% cheaper" is not a thing a person can picture.
        if gap > 0:
            mult = 1 + gap / 100.0
            how = (f"costs {mult:.1f}× Clara's price" if gap >= 100
                   else f"costs {gap:.0f}% more than Clara")
            return (f"{entity} {how} on the {pair['clara_name']} pairing — a "
                    f"price advantage Clara is not currently claiming anywhere.")
        return (f"{entity} sits {abs(gap):.0f}% below {pair['clara_name']} on a "
                f"like-for-like pairing — the price has to be answered or "
                f"defended.")
    if pair.get("competitor_price") and not pair.get("same_currency"):
        return (f"{entity} publishes in "
                f"{pair.get('competitor_currency') or 'another currency'}, so no "
                f"comparable gap exists — the decision is about the offer, not "
                f"the price.")
    if offer:
        cur = offer.get("currency") or ""
        same = cur.upper() == "SAR"
        return (f"{entity} is advertising “{offer.get('offer_title') or 'a promotion'}"
                f"” at {offer.get('current_price')} {cur} on "
                f"{offer.get('product') or 'its own page'}"
                + ("." if same else
                   f" — a different currency to Clara’s, so the price is not "
                   f"comparable and only the promotion itself is.")
                + " It was still there on the last read.")
    # Deliberately empty rather than an echo of "why now" below it. A card that
    # says the same sentence twice teaches the reader to skip both.
    return ""


def _competitor_metrics(pair: dict) -> list[dict]:
    """The numbers behind a competitor decision, with their direction."""
    out = []
    if pair.get("clara_price") is not None:
        out.append({"value": f"{pair['clara_price']} {pair.get('currency', '')}",
                    "key": "Clara price", "note": pair.get("clara_name", "")[:34],
                    "tone": "hero"})
    if pair.get("competitor_price") is not None:
        out.append({"value": f"{pair['competitor_price']} "
                             f"{pair.get('competitor_currency') or ''}",
                    "key": "Their price",
                    "note": (pair.get("competitor_product") or "")[:34],
                    "tone": "neutral"})
    gap = pair.get("gap_percent")
    if gap is not None:
        out.append({"value": f"{gap:+.0f}%",
                    "key": "Their price vs Clara",
                    "note": ("they cost more" if gap > 0 else "they cost less")
                            + ", same currency",
                    "tone": "up" if gap > 0 else "down"})
    elif pair.get("competitor_price") is not None:
        out.append({"value": "—", "key": "Their price vs Clara",
                    "note": "different currency; never converted",
                    "tone": "neutral"})
    return out


def _trend_insight(st: dict) -> str:
    stage = st.get("stage") or "emerging"
    pubs = st.get("publishers") or ""
    if stage in ("rising", "viral"):
        return (f"{st.get('topic')} is {stage} across {pubs} and hooks onto "
                f"{st.get('product')} — the window is open now rather than "
                f"later.")
    return (f"{st.get('topic')} is {stage}; it attaches to "
            f"{st.get('product')} but the evidence is still thin.")


def _trend_metrics(st: dict) -> list[dict]:
    out = []
    if st.get("score") is not None:
        out.append({"value": st["score"], "key": "Trend score",
                    "note": "of 100, five measured components", "tone": "hero"})
    if st.get("signal_count"):
        out.append({"value": st["signal_count"], "key": "Items",
                    "note": "articles behind it", "tone": "neutral"})
    if st.get("publisher_count"):
        out.append({"value": st["publisher_count"], "key": "Publishers",
                    "note": "independent sources", "tone": "neutral"})
    if st.get("stage"):
        out.append({"value": st["stage"].title(), "key": "Stage",
                    "note": "measured, not assigned", "tone": "neutral"})
    return out


def _trend_steps(bundle: dict, trends: dict | None) -> list[dict]:
    """The trend-derived half of the decisions list.

    Conservative on purpose: a subject earns a step only if it is not fading and
    there is a Clara product for it to attach to. A topic with no product to
    carry it produces nothing, which is why this list is short.
    """
    t = trends or {}
    products = (bundle.get("price") or {}).get("products") or []
    steps = []
    for topic in t.get("topics") or []:
        hook = TREND_HOOKS.get(topic.get("key"))
        if not hook or topic.get("stage") == "declining":
            continue
        hit = None
        for prod in products:
            name = (prod.get("name") or "").lower()
            if any(w in name for w in hook["match"]):
                hit = prod
                break
        if not hit:
            continue
        ev = (topic.get("evidence") or [{}])[0]
        steps.append({
            "step": hook["step"].format(product=hit.get("name")),
            "owner": hook["owner"],
            "topic": topic.get("label"),
            "topic_key": topic.get("key"),
            "score": ((topic.get("score") or {}).get("total")),
            "signal_count": topic.get("signal_count"),
            "publisher_count": topic.get("publisher_count"),
            "stage": topic.get("stage"),
            "why": topic.get("stage_why"),
            "confidence": topic.get("confidence"),
            "markets": ", ".join(topic.get("market_labels") or []),
            "publishers": ", ".join((topic.get("publishers") or [])[:3]),
            "source_url": ev.get("url"),
            "source_publisher": ev.get("publisher"),
            "changed_ago": topic.get("changed_ago"),
            "product": hit.get("name"),
            "product_url": hit.get("url"),
        })
    rank = {"viral": 0, "rising": 1, "emerging": 2, "mainstream": 3}
    steps.sort(key=lambda x: (rank.get(x["stage"], 9),
                              -Confidence_rank(x["confidence"])))
    return steps


def Confidence_rank(value: str) -> int:
    return {"UNVERIFIED": 0, "LOW": 1, "MEDIUM": 2, "HIGH": 3}.get(
        (value or "").upper(), 0)



def live_offers(bundle: dict) -> str:
    """The single offers section on the page.

    Takes the whole bundle rather than just the cycle, because a competitor's
    discount only means something next to the Clara product it competes with, and
    that pairing lives on the price report.
    """
    intel = bundle.get("intel") or {}
    pairs = _clara_pairs(bundle)
    rows = intel.get("live_competitor_offers") or []
    history = intel.get("offer_history") or []
    stamp = intel.get("updated_at") or ""
    unknown = [o for o in history if o.get("status") == "UNKNOWN"]

    P = ['<section id="live" class="isec"><div class="iwrap">']
    P.append(_head("Live competitor offers",
               f"{len(rows)} confirmed running", stamp))
    P.append('<p class="lede">An offer is here only if it was seen on the page on '
             'the last cycle. An old offer is never carried forward as live, and '
             'one whose page could not be read is held back rather than assumed to '
             'still be running.</p>')
    if not rows:
        P.append('<div class="iempty"><b>No promotion was confirmed running.</b> '
                 'That is not the same as no promotion existing &mdash; see the '
                 'unconfirmed count below.</div>')
    P.append('<div class="lgrid">')
    for o in rows:
        P.append('<div class="lcard">')
        P.append('<div class="lh">')
        P.append(f'<span class="lb">{_e(o.get("competitor"))}</span>')
        P.append(f'<span class="ipill ic-{_e(o.get("confidence"))}">'
                 f'{_e(o.get("status"))}</span>')
        P.append('</div>')
        P.append(f'<div class="lt">{_e(o.get("offer_title"))}</div>')
        P.append('<div class="lp">')
        if o.get("current_price"):
            P.append(f'<span class="now">{_e(o["current_price"])} '
                     f'{_e(o.get("currency"))}</span>')
        if o.get("original_price"):
            P.append(f'<span class="was">{_e(o["original_price"])}</span>')
        if o.get("discount"):
            P.append(f'<span class="cut">{_e(o["discount"])} off</span>')
        P.append('</div>')
        bits = []
        if o.get("product"):
            bits.append(f'On: {_e(o["product"])}')
        bits.append(_e(f'Page says it ends {o["valid_until"]}')
                    if o.get("valid_until") else 'No end date printed')
        P.append(f'<div class="lm">{" &middot; ".join(bits)}</div>')
        against = (pairs.get(o.get("competitor"))
                   or pairs.get(o.get("competitor_key")))
        if against:
            P.append('<div class="lm"><b>Against Clara:</b> '
                     f'{_e(against["name"])} at {_e(against["price"])} '
                     f'{_e(against["currency"])}'
                     + (f' &middot; {_e(against["gap"])}' if against.get("gap")
                        else '')
                     + '</div>')
        P.append(f'<div class="lm">{updated(o.get("last_seen_at"), "last seen")}'
                 + (f' &middot; <a href="{_e(o.get("source"))}" '
                    f'rel="nofollow noopener">open the page</a>'
                    if o.get("source") else '')
                 + '</div>')
        P.append('</div>')
    P.append('</div>')

    # Everything else, grouped by what is actually known rather than merged into
    # one list. "Ended" and "could not read the page" are opposite facts.
    ended = [o for o in history if o.get("status") == "EXPIRED"]
    unproven = [o for o in history if o.get("status") == "UNVERIFIED"]

    for rows_, title, blurb in (
        (ended, "Ended",
         "Seen on a readable page before, and gone from it now. Kept so a price "
         "claim made last week can be traced back."),
        (unknown, "Could not be confirmed",
         "The page was not readable on the last cycle, so whether these are still "
         "running has not been established. Nothing is claimed either way."),
        (unproven, "Wording only, no price",
         "The page carried promotional wording the Agent could read but no price "
         "behind it, so there is no offer to state."),
    ):
        if not rows_:
            continue
        P.append(f'<h3 style="margin-top:24px">{_e(title)} ({len(rows_)})</h3>')
        P.append(f'<p class="lede">{_e(blurb)}</p>')
        P.append('<div class="scroller"><table><thead><tr>'
                 '<th>Competitor</th><th>Offer</th><th>Last price</th>'
                 '<th>Last seen</th><th>What happened</th>'
                 '</tr></thead><tbody>')
        for o in rows_[:40]:
            link = (f'<a href="{_e(o.get("source"))}" rel="nofollow noopener">'
                    f'open</a>' if o.get("source") else '')
            P.append('<tr>')
            P.append(f'<td><b>{_e(o.get("competitor"))}</b></td>')
            P.append(f'<td>{_e(o.get("offer_title"))} {link}</td>')
            P.append(f'<td>{_e(o.get("current_price"))} '
                     f'{_e(o.get("currency"))}</td>')
            P.append(f'<td>{updated(o.get("last_seen_at"), "")}</td>')
            P.append(f'<td>{_e(o.get("change_note"))}</td>')
            P.append('</tr>')
        P.append('</tbody></table></div>')

    total = len(rows) + len(history)
    P.append(f'<div class="note"><b>{total} product-level offer(s) tracked</b> '
             f'&mdash; {len(rows)} confirmed running, {len(ended)} ended, '
             f'{len(unknown)} unconfirmed, {len(unproven)} without a readable '
             f'price. Every one was read from the competitor\'s own product page; '
             f'none is estimated.</div>')

    P.append(_storefront_offers(bundle))
    P.append('</div></section>')
    return "\n".join(P)


def _storefront_offers(bundle: dict) -> str:
    """What each brand is advertising on its own front page.

    A different kind of evidence from the block above, and labelled as such. The
    monitor only reads a rival page while chasing a specific Clara product, which
    is why most brands had no offer data at all. The sweep goes to the storefront
    directly, so coverage follows the registry rather than the pairings — broader,
    but with no product attached and therefore no price comparison.
    """
    sw = bundle.get("sweep") or {}
    by_brand = sw.get("by_competitor") or {}
    c = sw.get("counts") or {}
    if not sw:
        return ""

    P = ['<h3 style="margin-top:26px">What each brand is advertising on its '
         'storefront</h3>']
    P.append('<p class="lede">A separate sweep of every registered competitor\'s '
             'own front page, so coverage follows the registry rather than the '
             'product pairings. No product is attached to these, so they are '
             'wording rather than prices &mdash; and a banner claim is never '
             'turned into a verified saving.</p>')

    if not by_brand:
        P.append('<div class="iempty"><b>No sweep has run yet.</b> '
                 '<code>python run_offers.py</code> visits every registered '
                 'competitor and reads what it is promoting.</div>')
        return "\n".join(P)

    P.append(f'<div class="note"><b>{c.get("brands_advertising", 0)} of '
             f'{c.get("tried", 0)} brands are advertising something</b> &mdash; '
             f'{c.get("running", 0)} offer line(s) from '
             f'{c.get("storefronts_read", 0)} storefront(s) that answered. '
             f'{c.get("refused", 0)} refused every path tried and are escalated '
             f'rather than retried. {c.get("gone", 0)} line(s) have since '
             f'disappeared from a readable page; {c.get("unknown", 0)} could not '
             f'be re-checked.</div>')

    P.append('<div class="swgrid">')
    for brand, offers in sorted(by_brand.items(),
                                key=lambda kv: (-len(kv[1]), kv[0])):
        P.append('<div class="swbrand">')
        P.append(f'<div class="sb">{_e(brand)}'
                 f'<span class="sbn">{len(offers)} line(s)</span></div>')
        for o in offers[:5]:
            mech = (o.get("mechanism") or "offer").split(",")[0]
            P.append('<div class="swline">')
            P.append(f'<span class="swmech">{_e(mech.replace("_", " "))}</span>')
            P.append(f'<span class="swtext">{_e(o.get("wording"))}</span>')
            if o.get("url"):
                P.append(f'<a href="{_e(o["url"])}" rel="nofollow noopener">'
                         f'open</a>')
            P.append('</div>')
        if len(offers) > 5:
            P.append(f'<div class="swline"><span class="swtext np">and '
                     f'{len(offers) - 5} more line(s)</span></div>')
        P.append(f'<div class="swline">{updated(offers[0].get("last_seen_at"), "read")}'
                 f'</div>')
        P.append('</div>')
    P.append('</div>')

    mech = sw.get("mechanisms") or {}
    if mech:
        P.append('<div class="note"><b>Mechanisms in use:</b> '
                 + " &middot; ".join(f"{_e(k.replace('_', ' '))} ({v})"
                                     for k, v in list(mech.items())[:10])
                 + '. No discount percentage is recorded from any of these: a '
                 'storefront banner is not a before-and-after pair, and the '
                 'sweep does not turn one into the other.</div>')
    return "\n".join(P)


# --------------------------------------------------------------------------
# next steps — the join between the two pages
# --------------------------------------------------------------------------

# A trend only earns a step if it can be tied to something Clara actually sells
# or someone Clara actually competes with. The hook is what makes the difference
# between a step and a slogan.
TREND_HOOKS = {
    "hair_tools": {
        "match": ("dryer", "brush", "styler", "straighten", "curl"),
        "step": ("Put the moving claim on the {product} listing. The sources are "
                 "carrying this subject now, and that page currently argues on "
                 "price alone."),
        "owner": "marketing",
    },
    "dupe_culture": {
        "match": ("dryer", "brush", "styler"),
        "step": ("Write the comparison out explicitly on {product}: name the "
                 "premium device it replaces and show both prices. Value-seeking "
                 "is the subject moving, and Clara is on the right side of it."),
        "owner": "marketing",
    },
    "heat_protection": {
        "match": ("spray", "protect", "serum"),
        "step": ("Bundle {product} with a styling tool at checkout. Heat "
                 "protection is moving in the sources and it is the objection "
                 "every device page has to answer."),
        "owner": "product",
    },
    "bond_repair": {
        "match": ("mask", "serum", "conditioner", "repair"),
        "step": ("State the damage-repair claim on {product} with the "
                 "ingredient named. Bond repair is the counter-argument to heat "
                 "styling and Clara sells both sides of it."),
        "owner": "marketing",
    },
    "scalp_care": {
        "match": ("scalp", "shampoo", "serum", "oil"),
        "step": ("Give {product} a scalp-health line. Scalp care is the "
                 "fastest-growing part of haircare and it turns one device sale "
                 "into a repeat consumable sale."),
        "owner": "product",
    },
    "textured_hair": {
        "match": ("dryer", "brush", "curl", "diffuser"),
        "step": ("Decide whether {product} gets a textured-hair claim. Nothing "
                 "in the catalogue says anything about textured hair, and this "
                 "subject is moving in more than one market."),
        "owner": "product",
    },
    "halal_beauty": {
        "match": ("shampoo", "conditioner", "mask", "serum", "spray"),
        "step": ("Check whether {product} can carry a halal claim, and what "
                 "certification would cost. This is directly commercial in "
                 "Clara's own market."),
        "owner": "ops",
    },
    "price_promotion": {
        "match": ("dryer", "brush", "styler"),
        "step": ("Set the promotional floor for {product} before the next "
                 "seasonal window. Pricing and promotion is moving in the "
                 "sources and rivals are already discounting."),
        "owner": "pricing",
    },
    "social_commerce": {
        "match": ("dryer", "brush", "styler"),
        "step": ("Decide whether {product} gets a creator-led video as its lead "
                 "asset. Social commerce is where a hair tool is now discovered "
                 "and bought in one motion."),
        "owner": "marketing",
    },
    "mens_grooming": {
        "match": ("dryer", "brush", "trimmer"),
        "step": ("Assess whether {product} can be positioned for men as well. "
                 "It is an under-served buyer in the Gulf and the subject is "
                 "moving."),
        "owner": "product",
    },
    "retail_expansion": {
        "match": ("dryer", "brush", "styler"),
        "step": ("Check which retailers now carry the rivals to {product}, and "
                 "whether Clara is on the same shelf. Distribution is moving in "
                 "the sources, and where a rival appears next decides who Clara "
                 "gets compared against."),
        "owner": "sales",
    },
    "korean_beauty": {
        "match": ("dryer", "brush", "styler", "serum", "mask"),
        "step": ("Read the Korean styling claims the sources are carrying and "
                 "decide which one {product} can honestly make. K-beauty "
                 "vocabulary reaches the Gulf six to twelve months later, so "
                 "this is the cheap window."),
        "owner": "marketing",
    },
    "ai_personalisation": {
        "match": ("dryer", "brush", "styler"),
        "step": ("Decide whether {product} gets a hair-type selector on its "
                 "page. A diagnostic front-end turns a one-off tool purchase "
                 "into a routine, and it is a page change rather than a product "
                 "change."),
        "owner": "product",
    },
    "hair_growth": {
        "match": ("serum", "oil", "scalp", "shampoo"),
        "step": ("Decide whether {product} can carry a density or growth claim, "
                 "and what evidence would be needed to make it honestly. This is "
                 "the highest-intent demand in haircare."),
        "owner": "product",
    },
    "device_beauty_tech": {
        "match": ("dryer", "brush", "styler"),
        "step": ("Price {product} against the wider at-home device market, not "
                 "only against hair tools. Its buyers are the same people and "
                 "they compare across the whole category."),
        "owner": "pricing",
    },
    "longevity": {
        "match": ("serum", "mask", "oil", "treatment"),
        "step": ("Reframe {product} as hair health rather than hair styling on "
                 "its page. Wellness framing is where the pricing power sits."),
        "owner": "marketing",
    },
    "refill_sustainability": {
        "match": ("shampoo", "conditioner", "serum", "spray", "foam"),
        "step": ("Cost a refill format for {product}. Regulatory in Europe, "
                 "reputational everywhere else, and cheap to act on for a "
                 "consumables line."),
        "owner": "ops",
    },
    "clean_beauty": {
        "match": ("shampoo", "conditioner", "mask", "serum", "spray"),
        "step": ("List the full ingredient set on {product}. Transparency is a "
                 "claim Clara can make cheaply and cannot fake."),
        "owner": "product",
    },
    "blowout_styles": {
        "match": ("dryer", "brush", "styler"),
        "step": ("Show the specific finish on {product} — the look people buy a "
                 "tool to achieve — rather than the device on a plain "
                 "background."),
        "owner": "marketing",
    },
    "fragrance_hair": {
        "match": ("spray", "mist", "serum", "oil"),
        "step": ("Consider a scented variant of {product}. Hair fragrance is a "
                 "high-margin add-on with strong Gulf demand."),
        "owner": "product",
    },
}



def _clara_pairs(bundle: dict) -> dict:
    """Competitor brand -> the Clara product it faces, with the gap.

    Read off the price report, so a gap only appears where a stored match holds
    and both sides publish in the same currency. Nothing is converted.
    """
    out: dict = {}
    for prod in (bundle.get("price") or {}).get("products") or []:
        for m in prod.get("matches") or []:
            keys = [k for k in (m.get("competitor_brand"), m.get("competitor_key"))
                    if k]
            if not keys or any(k in out for k in keys):
                continue
            if m.get("status") not in ("confirmed_match", "probable_match"):
                continue
            # `delta_pct_vs_clara` is already computed on the match, and only
            # where both sides publish in the same currency. Recomputing it here
            # would be a second implementation of the same rule.
            pct = m.get("delta_pct_vs_clara")
            gap = ""
            if pct is not None and m.get("same_currency"):
                v = float(pct)
                gap = (f"Clara is {abs(v):.0f}% cheaper" if v > 0
                       else f"they are {abs(v):.0f}% cheaper")
            entry = {"name": prod.get("name"),
                     "price": prod.get("clara_price"),
                     "currency": prod.get("currency") or "SAR", "gap": gap}
            for k in keys:
                out[k] = entry
    return out


def refused(intel: dict) -> str:
    rows = intel.get("data_quality_warnings") or []
    if not rows:
        return ""
    stamp = intel.get("updated_at") or ""
    P = ['<section id="refused" class="isec"><div class="iwrap">']
    P.append(_head("Pairings this cycle refused",
                   f"{len(rows)} stored match(es) that do not hold", stamp))
    P.append('<p class="lede">A stored match says these two are the same product. '
             'Re-checking both sides says they are different kinds of product, so '
             'no price gap was computed from them. Each needs a person to '
             're-decide the pairing.</p>')
    P.append('<div class="scroller"><table><thead><tr>'
             '<th>Clara product</th><th>Reads as</th><th>Competitor product</th>'
             '<th>Reads as</th><th>Stored as</th></tr></thead><tbody>')
    for w in rows:
        P.append('<tr>')
        P.append(f'<td><b>{_e(w.get("clara_product"))}</b></td>')
        P.append(f'<td>{_e(w.get("clara_segment"))}</td>')
        P.append(f'<td>{_e(w.get("competitor_product"))}</td>')
        P.append(f'<td>{_e(w.get("competitor_segment"))}</td>')
        P.append(f'<td>{_e(w.get("stored_status"))}</td>')
        P.append('</tr>')
    P.append('</tbody></table></div></div></section>')
    return "\n".join(P)


def after_offers(bundle: dict) -> str:
    """What follows the offers and tasks: only the pairings the cycle refused.

    The watchlist block was removed at the operator's request. Discovery still
    runs and still records what it finds — `reports/intel_*.json` carries it — it
    simply no longer takes up a section on the page.
    """
    intel = bundle.get("intel") or {}
    if not intel:
        return ""
    return refused(intel)
