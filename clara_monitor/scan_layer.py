"""The band that turns each page's data into an insight and names the decision.

Three pages, one sentence each, in the same order every time:

    data  ->  insight  ->  decision  ->  action

Competitors and Trends both had the data and the action. Neither had the middle
two, so a reader arrived at a table of 97 pairings or 44 subjects and had to
derive the point themselves — which in practice means nobody does.

This module renders the missing middle on both pages, using the same components
as the Decisions page, and every callout ends with a link into the decision it
leads to. That link is the join: it is what makes the three pages one product
rather than three screens that happen to share a stylesheet.

Nothing here computes anything new. It reads the same stored evidence the tables
below it read, and where a number cannot be compared — a different currency, an
unread page — it says so rather than producing a comparison that does not exist.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

from . import intel_sections as isec
from .ui import (badge, callout, crosslink, crosslinks, e, insight, metric,
                 metrics, nothing, section_head)

TOP_N = 3


def _dec(v):
    try:
        return Decimal(str(v))
    except (InvalidOperation, TypeError, ValueError):
        return None


# --------------------------------------------------------------------------
# the comparator band
# --------------------------------------------------------------------------

def _pairings(bundle: dict) -> list[dict]:
    """Every comparable pairing, flattened, with the gap in one direction.

    Only same-currency pairings appear. A pairing where the two sides publish in
    different currencies is not a comparison, and converting it would invent a
    number, so it is counted separately and excluded from every ranking below.
    """
    rows, skipped = [], 0
    for prod in (bundle.get("price") or {}).get("products") or []:
        clara = _dec(prod.get("clara_price"))
        for m in prod.get("matches") or []:
            if m.get("status") not in ("confirmed_match", "probable_match"):
                continue
            their = _dec(m.get("competitor_price"))
            if clara is None or their is None:
                continue
            if not m.get("same_currency"):
                skipped += 1
                continue
            pct = _dec(m.get("delta_pct_vs_clara"))
            if pct is None:
                continue
            rows.append({
                "clara_name": prod.get("name") or "",
                "clara_price": clara,
                "currency": prod.get("currency") or "SAR",
                "brand": m.get("competitor_brand") or "",
                "key": m.get("competitor_key") or "",
                "their_name": m.get("competitor_product_name") or "",
                "their_price": their,
                "pct": float(pct),
                "status": m.get("status"),
                "url": m.get("competitor_url") or "",
                "observed_at": m.get("observed_at"),
            })
    rows.sort(key=lambda r: r["pct"], reverse=True)
    for r in rows:
        r["skipped_pairings"] = skipped
    return rows


def _pick(rows: list, keys: tuple, limit: int, *, positive: bool) -> list:
    """The strongest rows, made distinct on each key in turn.

    A ranking that shows the same brand three times has spent three slots on one
    fact. So: take the strongest row per brand; if that does not fill the list
    (only two competitors currently have an observed price, so it usually does
    not), fall back to the strongest row per Clara product, then to whatever is
    left. Three cards, three facts, in the order that makes them different.
    """
    side = [r for r in rows if (r["pct"] > 0 if positive else r["pct"] < 0)]
    out: list = []
    for key in keys:
        seen = {r[key] for r in out}
        for r in side:
            if len(out) >= limit:
                return out
            if r in out or r[key] in seen:
                continue
            seen.add(r[key])
            out.append(r)
    for r in side:
        if len(out) >= limit:
            break
        if r not in out:
            out.append(r)
    return out


def _win_callout(r: dict, dec: bool = True) -> str:
    mult = 1 + r["pct"] / 100.0
    how = (f"{mult:.1f}× Clara's price" if r["pct"] >= 100
           else f"{r['pct']:.0f}% more than Clara")
    body = (f"{r['brand']} asks {r['their_price']} {r['currency']} for its "
            f"counterpart — {how}. Clara publishes "
            f"{r['clara_price']} {r['currency']}. Both prices were read off the "
            f"live pages in the same currency; nothing was converted.")
    return callout(
        f"{r['clara_name']} beats {r['brand']}",
        body, tone="win",
        badges=badge("clara", f"+{r['pct']:.0f}%") + badge(
            "HIGH" if r["status"] == "confirmed_match" else "MEDIUM",
            "confirmed pairing" if r["status"] == "confirmed_match"
            else "probable pairing"),
        links=crosslinks([
            crosslink(f"/?focus={e(r['key'])}#competitors", r["brand"],
                      icon="▤") if r["key"] else "",
            crosslink(r["url"], "their page", icon="↗", external=True)
            if r["url"] else "",
            crosslink("/decisions", "What to do with this", icon="→",
                      primary=True) if dec else "",
        ]))


def _risk_callout(r: dict, dec: bool = True) -> str:
    body = (f"{r['brand']} is at {r['their_price']} {r['currency']} against "
            f"Clara's {r['clara_price']} — {abs(r['pct']):.0f}% below, on a "
            f"pairing the system holds as "
            f"{'confirmed' if r['status'] == 'confirmed_match' else 'probable'}. "
            f"This is the number a shopper comparing the two will see.")
    return callout(
        f"{r['brand']} undercuts {r['clara_name']}",
        body, tone="risk",
        badges=badge("rival", f"{r['pct']:.0f}%") + badge(
            "HIGH" if r["status"] == "confirmed_match" else "MEDIUM",
            "confirmed pairing" if r["status"] == "confirmed_match"
            else "probable pairing"),
        links=crosslinks([
            crosslink(f"/?focus={e(r['key'])}#competitors", r["brand"],
                      icon="▤") if r["key"] else "",
            crosslink(r["url"], "their page", icon="↗", external=True)
            if r["url"] else "",
            crosslink("/decisions", "Decide on this price", icon="→",
                      primary=True) if dec else "",
        ]))


def _change_callouts(bundle: dict) -> list[str]:
    """What actually moved since the previous cycle.

    Deliberately reads the cycle's own comparison rather than re-deriving it: the
    previous state is not the source of truth, and a change is only a change if
    the cycle verified it against what was stored.
    """
    intel = bundle.get("intel") or {}
    summary = intel.get("summary") or {}
    by_type = summary.get("changes_by_type") or {}
    out = []

    for f in (intel.get("findings") or [])[:TOP_N]:
        tone = ("risk" if (f.get("threat_level") or "").upper() == "HIGH"
                else "win" if f.get("opportunity") else "")
        links = [crosslink(ev.get("url"),
                           ev.get("publisher") or ev.get("label") or "the page",
                           icon="↗", external=True)
                 for ev in (f.get("evidence") or [])[:2] if ev.get("url")]
        links.append(crosslink("/decisions", "The decision this raises",
                               icon="→", primary=True))
        links = [l for l in links if l]
        out.append(callout(
            f.get("title") or "Change",
            f.get("competitive_impact") or f.get("strategic_significance") or "",
            tone=tone,
            badges=badge((f.get("confidence") or "UNVERIFIED").upper())
                   + badge("quiet", (f.get("change_type") or "").replace("_", " ").lower()),
            links=crosslinks(links)))

    if not summary:
        # No cycle in this bundle at all. Saying "nothing changed" here would be
        # a claim about evidence that was never compared.
        return [callout(
            "No intelligence cycle is attached to this build",
            "Change detection compares the current evidence against the previous "
            "state, and that comparison has not been run for this snapshot. The "
            "prices and pairings above are real; the change column simply has "
            "nothing behind it yet.",
            badges=badge("UNVERIFIED", "not run"))]

    if not out:
        counted = ", ".join(f"{v} {k.replace('_', ' ').lower()}"
                            for k, v in by_type.items()) or "nothing"
        out.append(callout(
            "Nothing changed on the competitors this cycle",
            f"The cycle compared every stored competitor against the previous "
            f"state and recorded {counted}. An empty result here is a real "
            f"finding: it means the pages that were readable said the same thing "
            f"they said last time, not that the check was skipped.",
            badges=badge("quiet", f"cycle {summary.get('cycle_id') or ''}")))
    return out


def comparator_band(bundle: dict) -> str:
    """The band at the top of the comparator: what this scan actually says."""
    rows = _pairings(bundle)
    intel = bundle.get("intel") or {}
    trends = bundle.get("trends") or {}
    decisions = isec.decision_items(bundle, trends)
    skipped = rows[0]["skipped_pairings"] if rows else 0

    # Deduped so three cards say three things. Wins by competitor, because the
    # useful fact is the breadth of who Clara beats rather than three products
    # beating the same brand; risks by Clara product, because a competitor that
    # undercuts three different products has undercut three different products.
    wins = _pick(rows, ("brand", "clara_name"), TOP_N, positive=True)
    risks = _pick(list(reversed(rows)), ("clara_name", "brand"), TOP_N,
                  positive=False)

    P = ['<section class="sec" id="takeaway"><div class="wrap">']
    P.append(section_head(
        "What this scan says",
        f"{len(rows)} comparable pairing(s)",
        "The tables below are the evidence. This is the reading of them: where "
        "Clara is ahead on price, where a competitor is ahead, and what moved "
        "since the last cycle. Every line ends at the decision it leads to."))

    # The headline numbers, in the same strip shape the decisions use.
    ahead = sum(1 for r in rows if r["pct"] > 0)
    behind = sum(1 for r in rows if r["pct"] < 0)
    widest = max((r["pct"] for r in rows), default=None)
    worst = min((r["pct"] for r in rows), default=None)
    P.append(metrics([
        metric(ahead, "Pairings Clara wins", "cheaper than the rival", "up"),
        metric(behind, "Pairings Clara loses", "the rival is cheaper", "down"),
        metric(f"+{widest:.0f}%" if widest is not None else "—",
               "Widest advantage", "same currency", "up"),
        metric(f"{worst:.0f}%" if worst is not None else "—",
               "Deepest undercut", "same currency", "down"),
        metric(len(decisions), "Decisions raised", "waiting on a person",
               "hero") if intel else "",
    ]))

    if not rows:
        P.append(nothing(
            "No comparable pairing was observed in this run.",
            "A pairing needs both prices read off live pages in the same "
            "currency. Until one exists there is no price reading to give, and "
            "an invented one would be worse than none."))
    else:
        P.append('<div class="cgrid2" style="margin-top:16px">')
        P.append('<div>')
        P.append(f'<h3 style="font-size:14px;margin:0 0 9px">Where Clara wins'
                 f'{badge("clara", f"{ahead}")}</h3>')
        for r in wins:
            P.append(_win_callout(r, bool(intel)))
        if not wins:
            P.append(nothing("No pairing has Clara ahead on price.",
                             "Every comparable rival observed in this run is at "
                             "or below Clara's price."))
        P.append('</div><div>')
        P.append(f'<h3 style="font-size:14px;margin:0 0 9px">Where Clara is '
                 f'undercut{badge("rival", f"{behind}")}</h3>')
        for r in risks:
            P.append(_risk_callout(r, bool(intel)))
        if not risks:
            P.append(nothing("No comparable rival is below Clara's price.",
                             "On every same-currency pairing observed, Clara is "
                             "at or under the rival."))
        P.append('</div></div>')

    P.append('<h3 style="font-size:14px;margin:22px 0 9px">What changed since '
             'the last cycle</h3>')
    P.append('<div class="cgrid2">')
    for c in _change_callouts(bundle):
        P.append(c)
    P.append('</div>')

    brands = sorted({r["brand"] for r in rows if r["brand"]})
    tracked = ((bundle.get("competitors") or {}).get("total") or 0)
    if rows and tracked:
        P.append(f'<div class="note"><b>These rankings rest on '
                 f'{e(len(brands))} competitor(s) with an observed price</b> '
                 f'&mdash; {e(", ".join(brands))} &mdash; out of {e(tracked)} '
                 f'tracked. The rest either refuse automated access, publish no '
                 f'price on a readable page, or have no counterpart product '
                 f'assigned yet. So this is the reading of what was observed, '
                 f'not a reading of the whole market, and widening it means '
                 f'widening the scan rather than reinterpreting these numbers.'
                 f'</div>')

    if skipped:
        P.append(f'<div class="note"><b>{e(skipped)} pairing(s) were left out of '
                 f'these rankings</b> because the two sides publish in different '
                 f'currencies. Currency is never converted here, so those are '
                 f'listed in the tables with their own currency and no gap.</div>')

    P.append(crosslinks([
        crosslink("/decisions", f"{len(decisions)} decision(s) waiting",
                  icon="→", primary=True) if intel else "",
        crosslink("/trends", "What the market is moving on",
                  icon="↗") if trends else "",
        crosslink("#prices", "Straight to the product tables", icon="▤"),
    ]))
    P.append('</div></section>')
    return "\n".join(P)


# --------------------------------------------------------------------------
# the trends band
# --------------------------------------------------------------------------

RISING = ("rising", "viral")


def trends_band(trends: dict, decisions: list | None = None) -> str:
    """The band at the top of the trends page: what is moving, and why it matters.

    A grid of 44 subjects is data. This says which are climbing, which are
    falling, which are new, and what each of those three facts is worth — then
    hands the reader the decision.
    """
    topics = trends.get("topics") or []
    decisions = decisions or []
    dec_topics = {d.get("topic_key") for d in decisions if d.get("topic_key")}

    by_stage = trends.get("by_stage") or {}
    up = [t for t in topics if t.get("stage") in RISING]
    down = [t for t in topics if t.get("stage") == "declining"]
    # A subject is "first recorded" when its own last change was its first
    # sighting. Careful with the word "new": that can mean the market moved, or
    # it can mean the vocabulary widened and reached something already collected.
    # The scan's own new-signal count is what tells the two apart, so it is
    # reported rather than glossed.
    new = [t for t in topics if t.get("last_change_kind") == "first_seen"]
    fresh_signals = ((trends.get("scan") or {}).get("signals_new"))
    # `hidden` is a verdict object, always present. Only its answer counts.
    hidden = [t for t in topics if (t.get("hidden") or {}).get("is_hidden")]
    hooked = [t for t in topics if t.get("key") in dec_topics]

    up.sort(key=lambda t: -((t.get("score") or {}).get("total") or 0))
    down.sort(key=lambda t: -((t.get("score") or {}).get("total") or 0))

    P = ['<section class="sec" id="takeaway"><div class="wrap">']
    P.append(section_head(
        "What is moving, and what it is worth",
        f"{len(topics)} subject(s) with evidence",
        "Stage is measured, not assigned: it comes from how many independent "
        "publishers are carrying a subject, over how long, and whether the rate "
        "is climbing. Below, each group says what the movement means and where "
        "it goes next."))

    P.append(metrics([
        metric(len(up), "Climbing", "rising or viral", "up"),
        metric(len(down), "Cooling", "publishers moving on", "down"),
        metric(len(new), "First recorded",
               ("vocabulary reached them" if fresh_signals == 0
                else "newly recorded subjects"), "neutral"),
        metric(len(hidden), "Low competition", "few publishers, still returning",
               "neutral"),
        metric(len(hooked), "Carry a decision",
               "attached to a Clara product", "hero"),
    ]))

    if not topics:
        P.append(nothing(
            "No subject has enough evidence yet.",
            "A subject needs several items from more than one publisher before "
            "it is shown at all. Run a scan and check back."))
        P.append('</div></section>')
        return "\n".join(P)

    def group(title: str, rows: list, tone: str, meaning: str, count_badge: str):
        if not rows:
            return
        P.append(f'<h3 style="font-size:14px;margin:22px 0 9px">{e(title)}'
                 f'{badge(count_badge, str(len(rows)))}</h3>')
        P.append(f'<p class="sec-lede" style="margin-bottom:12px">{e(meaning)}</p>')
        P.append('<div class="cgrid2">')
        for t in rows[:TOP_N]:
            sc = (t.get("score") or {}).get("total")
            has_dec = t.get("key") in dec_topics
            body = (f"{t.get('publisher_count') or 0} independent publisher(s), "
                    f"{t.get('signal_count') or 0} item(s), across "
                    f"{len(t.get('markets') or [])} market(s). Last moved "
                    f"{t.get('changed_ago') or 'unknown'}. "
                    + (t.get("stage_why") or ""))
            links = [
                crosslink(f"/trends?trend={e(t.get('key'))}",
                          "Open the full record", icon="▤", primary=True),
            ]
            if has_dec:
                links.append(crosslink("/decisions",
                                       "The decision it raises", icon="→",
                                       primary=True))
            else:
                links.append(crosslink("/decisions", "See all decisions",
                                       icon="→"))
            P.append(callout(
                t.get("label") or t.get("key") or "",
                body, tone=tone,
                badges=badge("quiet", f"score {sc}" if sc is not None
                             else "unscored")
                       + badge((t.get("confidence") or "UNVERIFIED").upper())
                       + (badge("clara", "carries a decision") if has_dec else ""),
                links=crosslinks(links)))
        P.append('</div>')

    group("Climbing", up, "win",
          "More publishers are carrying these, and faster than before. A "
          "climbing subject is a window rather than an event — acting while "
          "it is open is the whole value, which is why these are the ones that "
          "turn into decisions.", "clara")
    group("Cooling", down, "risk",
          "Publishers have moved on. This is not a reason to abandon a product; "
          "it is a reason not to build new content around the subject now, and a "
          "reason to check anything already built on it.", "rival")
    first_lede = (
        "Recorded here for the first time. Evidence is thin by definition — "
        "shown so it is not rediscovered as news next cycle, not because it is "
        "ready to act on.")
    if fresh_signals == 0:
        first_lede += (" The last scan added no new items, so these are subjects "
                       "the vocabulary reached for the first time rather than "
                       "things the market has just started saying.")
    elif fresh_signals:
        first_lede += (f" The last scan added {fresh_signals} new item(s), so "
                       f"some of this is genuinely new coverage.")
    group("First recorded on this page", new, "", first_lede, "quiet")

    group("Low competition, real movement", hidden[:TOP_N], "",
          "Few publishers are on these, but the ones that are keep returning. "
          "That combination is the only one where being early is worth anything "
          "— a crowded subject is not an opportunity, it is a queue.", "clara")

    P.append(crosslinks([
        crosslink("/decisions", f"{len(decisions)} decision(s) waiting",
                  icon="→", primary=True),
        crosslink("/", "Clara vs. the competition", icon="▤"),
        crosslink("#report", "The ranked lists", icon="↓"),
    ]))
    P.append('</div></section>')
    return "\n".join(P)
