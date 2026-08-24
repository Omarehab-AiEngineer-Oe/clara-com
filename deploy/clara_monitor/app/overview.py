"""The Overview tab (3): what is unresolved, how old it is, what moved.

Section 3 lists the required contents — "freshness, collection coverage,
unresolved Actions, verified price movements, active offers, request attention,
and shortcuts to the affected records" — and section 10 fixes the order:
attention, freshness and incomplete coverage come before descriptive metrics.

The old page led with how many products and competitors existed. Those are
inventory, not information: they are the same number every morning, and a page
that opens with them teaches the reader that the top of the page is not worth
reading. So this one opens with the work.

Every number here is a link. "Shortcuts to the affected records" is the
requirement, and the implementation of it is that no figure is a dead end — each
one carries the filter that produces exactly the rows it counted, which is also
how section 12's reconciliation criterion is met in practice rather than in
principle.
"""

from __future__ import annotations

from ..ops import ACTION_TYPE_LABEL, REQUEST_STATUS_LABEL
from .shell import (agent_btn, badges, e, empty, fresh, kv, money, page_head,
                    panel, pill, prov, send_request_btn, stat, stats, when)

PRIORITY_TONE = {"high": "solid", "medium": "amb", "low": "quiet"}


def render(ov: dict, *, user: dict) -> str:
    P = ['<div class="wrap">']
    P.append(page_head(
        "Overview",
        "What needs a person, how current the evidence is, and what changed. "
        "Every figure on this page links to the records it counts.",
        acts=send_request_btn(primary=True) + agent_btn("", "",
                                                        label="Ask the Agent",
                                                        small=False)))

    P.append(_attention(ov))
    P.append('<div class="cols"><div>')
    P.append(_actions(ov))
    P.append(_movements(ov))
    P.append(_offers(ov))
    P.append('</div><div>')
    P.append(_freshness(ov))
    P.append(_coverage(ov))
    P.append(_requests(ov))
    P.append(_agent_scope())
    P.append(_provenance_key())
    P.append(_collection(ov))
    P.append('</div></div></div>')
    return "".join(P)


# --------------------------------------------------------------------------

def _attention(ov: dict) -> str:
    """The first thing on the page: what is not resolved."""
    a, r, prod = ov["actions"], ov["requests"], ov["products"]["counts"]
    cards = [
        stat(a["open"], "Open actions",
             "Open, in progress or waiting — still needs a person.",
             tone="hot" if a["open"] else "good", href="/actions"),
        stat(a["high"], "High priority", "Open actions marked high priority.",
             tone="hot" if a["high"] else "calm",
             href="/actions?priority=high"),
        stat(prod["attention"], "Products needing attention",
             "An open action, no competitor, an unreadable source, an "
             "undecided match, no usable price, or every price stale.",
             tone="warn" if prod["attention"] else "good",
             href="/products?attention=any"),
        stat(r["open"], "Open requests",
             "New, in progress, or waiting for information.",
             tone="warn" if r["open"] else "calm", href="/requests?scope=all"),
        stat(r["needs_me"], "Waiting on you",
             "Requests you raised that need your reply before they can move.",
             tone="hot" if r["needs_me"] else "calm",
             href="/requests?status=waiting_for_information"),
    ]
    return panel("Needs attention", stats(cards),
                 note="the work this application exists to clear")


def _actions(ov: dict) -> str:
    a = ov["actions"]
    if not a["open"]:
        body = empty("Nothing is waiting for a person",
                     "No action is open, in progress or waiting. When a scan "
                     "finds an undecided match or a source it cannot read, the "
                     "action appears here and can be resolved in place.",
                     '<a class="b" href="/actions?status=">See resolved '
                     'actions</a>')
        return panel("Unresolved actions", body, flush=True)

    rows = []
    for x in ov["recent_actions"]:
        rows.append(
            '<tr><td>'
            f'<a class="ttl" href="/actions/{e(x["action_id"])}">'
            f'{e(ACTION_TYPE_LABEL.get(x["action_type"], x["action_type"]))}</a>'
            f'<div class="sub">{e((x.get("reason") or "")[:140])}</div>'
            '</td><td>'
            + badges(pill((x.get("priority") or "medium").title(),
                          PRIORITY_TONE.get(x.get("priority"), "quiet")),
                     pill(x.get("assignee") or "Unassigned",
                          "quiet" if x.get("assignee") else "amb"))
            + '</td><td class="num">'
            f'<a class="b b-sm" href="/actions/{e(x["action_id"])}">Resolve</a>'
            '</td></tr>')

    by_type = " · ".join(
        f"{ACTION_TYPE_LABEL.get(k, k)}: {v}" for k, v in
        sorted(a["by_type"].items(), key=lambda kv: -kv[1]))
    body = ('<div class="scroll"><table class="t">'
            '<thead><tr><th>What needs deciding</th><th>Priority</th>'
            '<th></th></tr></thead><tbody>' + "".join(rows)
            + '</tbody></table></div>'
            f'<div class="pager"><span>{a["open"]} open · '
            f'{a["unassigned"]} unassigned · {a["mine"]} assigned to you</span>'
            '<span class="pnav">'
            '<a class="b b-sm" href="/actions">Open the queue</a></span></div>'
            # 10: define every summary count. The figure above and this sentence
            # come from the same place, so they cannot drift apart.
            f'<div class="panel-b"><p class="note">{e(a["definition"])}</p>'
            '</div>')
    return panel("Unresolved actions", body, note=by_type, flush=True)


def _movements(ov: dict) -> str:
    m = ov["movements"]
    if not m["total"]:
        return panel(
            "Verified price movements",
            empty("No movement to report",
                  "A movement needs two observations of the same match in the "
                  "same currency, with different prices. Once a second scan has "
                  "run, changes appear here with the two dates behind them.",
                  '<a class="b" href="/products">Browse products</a>'),
            note=m["definition"], flush=True)

    rows = []
    for x in m["rows"][:10]:
        up = (x["delta"] or 0) > 0
        arrow = "↑" if up else "↓"
        tone = "lose" if up else "win"
        pct = (f'{x["delta_pct"]:+.1f}%' if x["delta_pct"] is not None else "")
        rows.append(
            '<tr><td>'
            f'<a class="ttl" href="/products/{e(x["clara_product_id"])}">'
            f'{e(x["clara_product_name"] or x["clara_product_id"])}</a>'
            f'<div class="sub">at '
            f'<a href="/competitors/{e(x["competitor_key"])}">'
            f'{e(x["competitor_key"])}</a></div>'
            '</td><td class="num">'
            f'<span class="{tone}">{arrow} {pct}</span>'
            f'<div class="sub">{money(x["old_price"], x["currency"])} &rarr; '
            f'{money(x["new_price"], x["currency"])}</div>'
            '</td><td>'
            + badges(prov(x["provenance"], short=True),
                     fresh(x["freshness"]["state"], x["freshness"]["why"],
                           x["freshness"].get("days")))
            + f'<div class="sub">{when(x["previous_at"], date_only=True)} &rarr; '
              f'{when(x["observed_at"], date_only=True)}</div>'
            '</td></tr>')
    head = stats([
        stat(m["verified"], "Verified movements",
             "The newer observation is human-confirmed or from an approved "
             "feed.", tone="good" if m["verified"] else "calm"),
        stat(m["total"], "All movements",
             "Including those only automatically observed.", tone="calm"),
    ])
    body = (f'<div class="panel-b">{head}</div>'
            '<div class="scroll"><table class="t"><thead><tr>'
            '<th>Product</th><th>Change</th><th>Evidence</th>'
            '</tr></thead><tbody>' + "".join(rows) + '</tbody></table></div>')
    return panel("Verified price movements", body, note=m["definition"],
                 flush=True)


def _offers(ov: dict) -> str:
    o = ov["offers"]
    if not o["unique"]:
        return panel("Active offers",
                     empty("No offer is on record",
                           "An offer is promotion wording read on a competitor "
                           "page. None has been observed yet.",
                           '<a class="b" href="/competitors">'
                           'See competitors</a>'), flush=True)
    rows = []
    for g in o["rows"][:8]:
        names = ", ".join(
            (p["name"] or p["clara_product_id"])[:40] for p in g["products"][:3])
        more = (f" +{len(g['products']) - 3} more"
                if len(g["products"]) > 3 else "")
        rows.append(
            '<tr><td>'
            f'<div class="ttl">{e(g["wording"][:150])}</div>'
            f'<div class="sub">{e(names)}{e(more)}</div>'
            '</td><td>'
            f'<a href="/competitors/{e(g["competitor_key"])}">'
            f'{e(g["competitor_key"])}</a></td>'
            '<td class="num">'
            f'{g["association_count"]}<div class="sub">products</div></td>'
            '<td>' + badges(
                fresh(g["freshness"]["state"], g["freshness"]["why"],
                      g["freshness"].get("days")),
                prov(g["provenance"], short=True)) + '</td>'
            '<td class="num">'
            + send_request_btn("offer", g.get("obs_id") or "", label="Verify",
                              small=True)
            + '</td></tr>')
    head = stats([
        stat(o["unique"], "Unique offers",
             "Distinct promotion wording per competitor.", tone="calm"),
        stat(o["associations"], "Product associations",
             "Product-level rows carrying those offers. One promotion across "
             "several products is one offer and several associations.",
             tone="calm"),
        stat(o["active"], "Active",
             "Last observed recently enough to still be running.",
             tone="good" if o["active"] else "calm"),
    ])
    body = (f'<div class="panel-b">{head}</div>'
            '<div class="scroll"><table class="t"><thead><tr>'
            '<th>Offer</th><th>Competitor</th><th>Reach</th><th>Evidence</th>'
            '<th></th></tr></thead><tbody>' + "".join(rows) + '</tbody></table></div>'
            '<div class="pager"><span>' + e(o["definition"]) + '</span>'
            '<span class="pnav"><a class="b b-sm" href="/offers">'
            'All offers</a></span></div>')
    return panel("Active offers", body, flush=True)


def _freshness(ov: dict) -> str:
    f = ov["freshness"]
    b = f["buckets"]
    body = stats([
        stat(b.get("fresh", 0), "Fresh", "Within two days.",
             tone="good", href="/products?sort=freshness"),
        stat(b.get("recent", 0), "Recent",
             f"Within {f['stale_days']} days.", tone="calm",
             href="/products?sort=freshness"),
        stat(b.get("stale", 0), "Stale",
             f"Older than {f['stale_days']} days — historical, not current.",
             tone="hot" if b.get("stale") else "calm",
             href="/products?attention=stale"),
        stat(b.get("unknown", 0), "Age unknown",
             "No observation date was recorded, so age cannot be established.",
             tone="warn" if b.get("unknown") else "calm"),
    ])
    note = ""
    if f["newest"]:
        note = "newest observation " + when(f["newest"])
    return panel("Freshness", body + f'<p class="note">{e(f["definition"])}</p>',
                 note=note)


def _coverage(ov: dict) -> str:
    c = ov["coverage"]
    body = stats([
        stat(c["comparable"], "Comparable",
             "Confirmed or probable match with a current price — the only set "
             "where a comparison can be made.", tone="good",
             href="/products?status=confirmed"),
        stat(c["unassigned"], "No competitor",
             "In the catalogue with no match of any status.",
             tone="warn" if c["unassigned"] else "calm",
             href="/products?attention=unassigned"),
        stat(c["priced_gap"], "Matched, not priced",
             "Has a match, but no confirmed or probable match with a current "
             "price.", tone="warn" if c["priced_gap"] else "calm",
             href="/products?attention=no_price"),
    ])
    return panel("Collection coverage",
                 body + f'<p class="note">{e(c["definition"])}</p>')


def _requests(ov: dict) -> str:
    r = ov["requests"]
    rows = []
    for status, label in REQUEST_STATUS_LABEL.items():
        n = r["by_status"].get(status, 0)
        if not n:
            continue
        rows.append((label,
                     f'<a href="/requests?scope=all&status={e(status)}">{n}</a>'))
    body = (kv(rows) if rows else
            '<p class="note">No request has been raised yet. Send Request is in '
            'the header, and on every product, competitor, action and price.</p>')
    if r["unowned"]:
        body += (f'<p class="note warn">{r["unowned"]} new request'
                 f'{"s" if r["unowned"] > 1 else ""} '
                 f'{"have" if r["unowned"] > 1 else "has"} no owner yet.</p>')
    body += f'<p class="note">{e(r["definition"])}</p>'
    acts = ('<a class="b b-sm" href="/requests">My Requests</a>'
            + send_request_btn(label="New", small=True))
    return panel("Request attention", body, acts=acts)


def _agent_scope() -> str:
    """6.1 and 6.2, on the page — not only inside the panel.

    Section 1 removes campaigns, advertising, SEO, social media, copywriting and
    customer acquisition from this module, not merely from the agent's replies.
    That is a statement about what the product is for, so it belongs somewhere a
    reader can find without opening the assistant and asking it something it
    refuses.
    """
    from ..ops.agent import EXCLUSIONS, IN_SCOPE
    excluded = "".join(f'<li>{e(x)}</li>' for x in EXCLUSIONS)
    body = (
        '<p class="note good"><b>In scope.</b> '
        + e("; ".join(IN_SCOPE)) + '.</p>'
        '<div class="note bad" style="margin-top:8px">'
        '<b>Excluded (6.2)</b>'
        f'<ul class="ex-list">{excluded}</ul>'
        'Asking for any of these is declined rather than attempted, and the '
        'check runs on the answer as well as the question — so the exclusion '
        'holds even if a reply starts to drift.</div>'
        '<p class="note" style="margin-top:8px">The addendum removes these from '
        'Competitor Intelligence deliberately, so that everything the agent '
        'says can be traced back to a stored observation.</p>')
    return panel("What the Intelligence Agent covers", body,
                 note="addendum sections 6.1 and 6.2")


def _provenance_key() -> str:
    """8.2's four labels, defined on the page a reader starts from.

    Section 6.3 requires the Agent to distinguish observed, human-confirmed,
    manually entered and feed values; section 10 requires provenance displayed
    consistently. Both assume the reader knows what the four labels mean, so the
    application says so somewhere rather than assuming it.
    """
    from ..ops import PROVENANCE_DEFINITION, PROVENANCE_LABEL
    rows = [(PROVENANCE_LABEL[k], e(PROVENANCE_DEFINITION[k]))
            for k in PROVENANCE_LABEL]
    return panel("What the provenance labels mean", kv(rows),
                 note="every value in this application carries one")


def _collection(ov: dict) -> str:
    imp = ov["last_import"]
    if not imp:
        return panel(
            "Collection",
            '<p class="note warn">No collection run has been imported into the '
            'operational database yet. Until one is, the tabs read from an '
            'empty store — the pages are not wrong, there is simply nothing '
            'recorded.</p>')
    from ..ops.db import loads
    counts = loads(imp.get("counts"), {}) or {}
    rows = [("Run", e(imp.get("run_id") or "unknown")),
            ("Imported", when(imp.get("at"))),
            ("By", e(imp.get("actor") or "system"))]
    for key in ("products", "competitors", "matches_new", "matches_updated",
                "matches_held", "observations", "sources", "actions",
                "conflicts"):
        if counts.get(key):
            rows.append((key.replace("_", " ").capitalize(), e(counts[key])))
    return panel("Last collection import", kv(rows),
                 note="human resolutions are never overwritten by an import")
