"""The Products tab (3), and the routable product page (3.1).

Section 3 asks the Products tab for the Clara catalogue, assigned competitors,
match status and confidence, prices, availability, freshness, provenance,
attention state, searchable and filterable. Section 3.1 adds the part that
changes the shape of the code: product profiles "must become routable detail
pages rather than modal-only views".

That is not a cosmetic change. A modal cannot be linked, so it cannot be the
target of an Overview shortcut, the subject of a Request, an Agent citation, or a
bookmark someone returns to tomorrow. `/products/<id>` can be all four, and the
Send Request and Ask the Agent controls on the page carry that id, which is what
makes 5.2's prefill and 6.3's inherited context work without the reader retyping
anything.

Two things on the detail page are deliberate.

**Evidence sits beside the value it supports** (10). A competitor's price is
rendered with its provenance, its freshness, its observation date and a link to
the page it was read from — in the same row, not in a footnote. A number whose
source is elsewhere on the page is a number the reader has to trust.

**Cross-currency observations stay visible but are marked non-comparable** (10).
They are not hidden and they are not silently converted; the row says the
comparison cannot be made, because a converted price with no approved conversion
policy is a number the application invented.
"""

from __future__ import annotations

from ..ops import MATCH_STATUS_LABEL, MatchStatus
from .shell import (agent_btn, applied, badges, confidence, e, empty,
                    filter_bar, fresh, kv, money, page_head, pager, panel,
                    pill, prov, send_request_btn, stat, stats, when)

STATUS_TONE = {
    MatchStatus.CONFIRMED: "ok", MatchStatus.PROBABLE: "info",
    MatchStatus.AMBIGUOUS: "amb", MatchStatus.NO_COUNTERPART: "no",
    MatchStatus.REJECTED: "no", MatchStatus.UNREADABLE: "bad",
}

ATTENTION_LABEL = {
    "action": "Open action", "unreadable": "Source unreadable",
    "ambiguous": "Match undecided", "stale": "Prices stale",
    "no_price": "No usable price", "unassigned": "No competitor",
}
ATTENTION_TONE = {"action": "solid", "unreadable": "bad", "ambiguous": "amb",
                  "stale": "bad", "no_price": "amb", "unassigned": "no"}

ATTENTION_FILTER = [
    ("", "Any state"), ("any", "Needs attention (any reason)"),
    ("action", "Has an open action"), ("unreadable", "Source unreadable"),
    ("ambiguous", "Match undecided"), ("stale", "Every price stale"),
    ("no_price", "No usable price"), ("unassigned", "No competitor assigned"),
]

SORTS = [("attention", "Needs attention first"), ("name", "Name"),
         ("coverage", "Least covered"), ("freshness", "Oldest evidence"),
         ("price_desc", "Clara price, high to low"),
         ("price_asc", "Clara price, low to high")]


def attention_badge(row: dict) -> str:
    if not row["attention"]:
        return pill("Clear", "ok", title="Nothing outstanding on this product")
    return pill(ATTENTION_LABEL.get(row["attention"], row["attention"]),
                ATTENTION_TONE.get(row["attention"], "quiet"),
                title=row["attention_why"])


# --------------------------------------------------------------------------
# the list
# --------------------------------------------------------------------------

def render_list(data: dict, *, query: dict, competitors: list,
                segments: list) -> str:
    c = data["counts"]
    P = ['<div class="wrap">']
    P.append(page_head(
        "Products",
        "The Clara catalogue and what each product faces. Products needing "
        "attention are listed first.",
        acts=send_request_btn(primary=True)))

    P.append(stats([
        stat(c["total"], "In the catalogue", "Every Clara product on record.",
             tone="calm", href="/products"),
        stat(c["attention"], "Needing attention",
             "An open action, no competitor, an unreadable source, an "
             "undecided match, no usable price, or every price stale.",
             tone="warn" if c["attention"] else "good",
             href="/products?attention=any"),
        stat(c["unassigned"], "No competitor",
             "In the catalogue with no match of any status.",
             tone="warn" if c["unassigned"] else "calm",
             href="/products?attention=unassigned"),
        stat(c["action"], "With an open action",
             "At least one action still requiring a person.",
             tone="hot" if c["action"] else "calm",
             href="/products?attention=action"),
        stat(c["clear"], "Clear", "Nothing outstanding.", tone="good"),
    ]))
    P.append(f'<p class="note">{e(data["definition"])}</p>')

    fields = [
        ("q", "Search", None, "Product name or id"),
        ("attention", "Attention", ATTENTION_FILTER),
        ("status", "Match status",
         [("", "Any status")] + [(k, v) for k, v in MATCH_STATUS_LABEL.items()]),
        ("competitor", "Competitor",
         [("", "Any competitor")] + [(k, n) for k, n in competitors]),
        ("segment", "Segment",
         [("", "Any segment")] + [(s, s.replace("_", " ")) for s in segments]),
        ("sort", "Sort", SORTS),
    ]
    body = (filter_bar("/products", fields, query)
            + applied("/products", query,
                      {"q": "Search", "attention": "Attention",
                       "status": "Status", "competitor": "Competitor",
                       "segment": "Segment"}))

    if not data["rows"]:
        body += empty(
            "No product matches these filters",
            "The catalogue has "
            f"{c['total']} products; none of them matches every filter above. "
            "Clear the filters to see the whole list.",
            '<a class="b" href="/products">Clear filters</a>')
    else:
        body += '<div class="scroll"><table class="t"><thead><tr>'
        body += ('<th>Product</th><th>Clara price</th><th>Competitors</th>'
                 '<th>Cheapest rival</th><th>Availability</th>'
                 '<th>Evidence</th><th>State</th>'
                 '</tr></thead><tbody>')
        for r in data["rows"]:
            body += _list_row(r)
        body += '</tbody></table></div>'
        body += pager("/products", query, data["total"], data["limit"],
                      data["offset"], "products")

    P.append(panel("", body, flush=True))
    P.append("</div>")
    return "".join(P)


def _availability(r: dict) -> str:
    """What the rivals' stock looks like, or an honest blank (3).

    "Nothing recorded" and "nothing in stock" are different facts, and a column
    that renders both as an empty cell has merged them.
    """
    if not r["rivals"]:
        return '<span class="na">no competitor</span>'
    if not r["availability_known"]:
        return '<span class="na">not recorded</span>'
    parts = []
    if r["in_stock"]:
        parts.append(pill(f'{r["in_stock"]} in stock', "ok"))
    if r["out_of_stock"]:
        parts.append(pill(f'{r["out_of_stock"]} out', "bad"))
    unknown = r["match_count"] - r["availability_known"]
    if unknown > 0:
        parts.append(pill(f'{unknown} unknown', "quiet"))
    return badges(*parts)


def _list_row(r: dict) -> str:
    attn = ' class="attn"' if r["attention"] else ""
    img = (f'<img class="thumb" src="{e(r["image_url"])}" alt="" '
           f'loading="lazy">' if r["image_url"] else '<div class="thumb"></div>')

    cheapest = r["cheapest"]
    if cheapest:
        gap = r["gap_pct"]
        if gap is None:
            cheap = money(cheapest["price"], cheapest["currency"])
        else:
            tone = "win" if gap > 0 else "lose"
            word = "above Clara" if gap > 0 else "below Clara"
            cheap = (f'{money(cheapest["price"], cheapest["currency"])}'
                     f'<div class="sub"><span class="{tone}">'
                     f'{abs(gap):.0f}% {word}</span></div>'
                     f'<div class="bar"><i class="{"" if gap > 0 else "over"}" '
                     f'style="width:{min(100, max(4, 100 - abs(gap))):.0f}%">'
                     f'</i></div>')
        cheap += (f'<div class="sub">at '
                  f'{e(cheapest["match"]["competitor_key"])}</div>')
    elif r["cross_currency"]:
        cheap = ('<span class="na">not comparable</span>'
                 '<div class="sub">priced in another currency</div>')
    else:
        cheap = '<span class="na">no rival price</span>'

    statuses = {}
    for x in r["rivals"]:
        s = x["match"]["status"]
        statuses[s] = statuses.get(s, 0) + 1
    st_badges = badges(*[
        pill(f'{MATCH_STATUS_LABEL.get(s, s)} {n}' if n > 1
             else MATCH_STATUS_LABEL.get(s, s), STATUS_TONE.get(s, "quiet"))
        for s, n in sorted(statuses.items(), key=lambda kv: -kv[1])])

    provs = sorted({x["provenance"] for x in r["rivals"] if x["provenance"]})
    ev = badges(fresh(r["freshest"]["state"], r["freshest"]["why"],
                      r["freshest"].get("days")),
                *[prov(p, short=True) for p in provs])

    return (f'<tr{attn}><td><div class="row">{img}<div>'
            f'<a class="ttl" href="/products/{e(r["product_id"])}">'
            f'{e(r["name"])}</a>'
            f'<div class="sub">{e(r["segment"] or "unclassified")}'
            + (f' · {e(r["category"].replace("_", " "))}'
               if r["category"] else "")
            + f'</div></div></div></td>'
            f'<td class="num">{money(r["clara_price"], r["currency"])}</td>'
            f'<td>{r["match_count"] or "<span class=\'na\'>none</span>"}'
            f'{st_badges}</td>'
            f'<td class="num">{cheap}</td>'
            f'<td>{_availability(r)}</td>'
            f'<td>{ev}</td>'
            f'<td>{attention_badge(r)}'
            + (f'<div class="sub">{e(r["attention_why"])}</div>'
               if r["attention"] else "")
            + '</td></tr>')


# --------------------------------------------------------------------------
# the detail page
# --------------------------------------------------------------------------

def render_detail(d: dict, *, query: dict) -> str:
    pid = d["product_id"]
    P = ['<div class="wrap">']
    acts = (send_request_btn("product", pid, label="Send Request", primary=True)
            + agent_btn("product", pid, label="Ask the Agent", small=False)
            + (f'<a class="b" href="{e(d["url"])}" rel="nofollow noopener">'
               'Open on clarahair.com</a>' if d["url"] else ""))
    P.append(page_head(
        d["name"], acts=acts,
        trail=[("Products", "/products"), (d["name"], None)]))

    P.append(badges(attention_badge(d),
                    pill(d["segment"] or "unclassified", "quiet"),
                    fresh(d["freshest"]["state"], d["freshest"]["why"],
                          d["freshest"].get("days")),
                    prov(d["product"].get("provenance"))))

    if d["attention"]:
        P.append(f'<p class="note warn">Needs attention: '
                 f'{e(d["attention_why"])}.</p>')

    P.append('<div class="cols"><div>')
    P.append(_counterparts(d))
    P.append(_history(d))
    P.append('</div><div>')
    P.append(_facts(d))
    P.append(_open_work(d))
    P.append(_requests_panel(d))
    P.append(_audit(d))
    P.append('</div></div></div>')
    return "".join(P)


def _counterparts(d: dict) -> str:
    """Every competitor this product is compared against, with its evidence."""
    if not d["rivals"]:
        return panel(
            "Competitors",
            empty("No competitor is assigned",
                  "Nothing is being compared against this product, so there is "
                  "no price gap to report. Raise a request to have a competitor "
                  "assigned, or ask the Agent what is known about it.",
                  send_request_btn("product", d["product_id"],
                                   label="Request a competitor", primary=True)
                  + agent_btn("product", d["product_id"])),
            flush=True)

    cur = d["currency"]
    rows = []
    for x in sorted(d["rivals"],
                    key=lambda r: (r["price"] is None, r["price"] or 0)):
        m, o = x["match"], x["observation"]
        comparable = bool(x["price"] is not None and x["currency"] == cur)
        if x["price"] is None:
            price_cell = '<span class="na">no price recorded</span>'
        elif not comparable:
            # 10: visible, but explicitly non-comparable. Not hidden, not
            # silently converted — there is no approved conversion policy.
            price_cell = (f'{money(x["price"], x["currency"])}'
                          '<div class="sub"><span class="na">not comparable — '
                          f'priced in {e(x["currency"])}, Clara in '
                          f'{e(cur or "an unknown currency")}</span></div>')
        else:
            gap = ((x["price"] - d["clara_price"]) / d["clara_price"] * 100.0
                   if d["clara_price"] else None)
            price_cell = money(x["price"], x["currency"])
            if gap is not None:
                tone = "win" if gap > 0 else "lose"
                price_cell += (f'<div class="sub"><span class="{tone}">'
                               f'{gap:+.0f}% vs Clara</span></div>')

        ev = []
        if o:
            ev.append(('Observed', when(o.get("observed_at"))))
            if o.get("last_checked_at"):
                ev.append(('Last checked', when(o.get("last_checked_at"))))
            if o.get("availability"):
                ev.append(('Availability', e(o["availability"])))
            if o.get("offer_wording"):
                ev.append(('Offer', e(o["offer_wording"])))
            if o.get("was_price"):
                ev.append(('Was', money(o.get("was_price"), o.get("currency"))))
            if o.get("note"):
                ev.append(('Note', e(o["note"])))
        if m.get("competitor_url"):
            ev.append(('Source',
                       f'<a href="{e(m["competitor_url"])}" '
                       f'rel="nofollow noopener">{e(m["competitor_url"][:70])}'
                       f'</a>'))
        if m.get("confirmed_by"):
            ev.append(('Confirmed by',
                       f'{e(m["confirmed_by"])} on {when(m.get("confirmed_at"))}'))
        if m.get("note"):
            ev.append(('Match note', e(m["note"])))

        rows.append(
            '<tr><td>'
            f'<a class="ttl" href="/competitors/{e(m["competitor_key"])}">'
            f'{e(m["competitor_key"])}</a>'
            f'<div class="sub">'
            f'{e(m.get("competitor_product_name") or "product not named")}</div>'
            '</td>'
            f'<td class="num">{price_cell}</td>'
            '<td>' + badges(
                pill(MATCH_STATUS_LABEL.get(m["status"], m["status"]),
                     STATUS_TONE.get(m["status"], "quiet")),
                confidence(m.get("confidence")),
                prov(x["provenance"], short=True),
                fresh(x["freshness"]["state"], x["freshness"]["why"],
                      x["freshness"].get("days")))
            + f'<div class="ev">{kv(ev)}</div></td>'
            '<td class="num">'
            + send_request_btn("match", m["match_id"], label="Ask", small=True)
            + '</td></tr>')

    note = ("evidence sits beside the value it supports; a price in another "
            "currency is shown but not compared")
    body = ('<div class="scroll"><table class="t"><thead><tr>'
            '<th>Competitor</th><th>Their price</th>'
            '<th>Status, provenance and evidence</th><th></th>'
            '</tr></thead><tbody>' + "".join(rows) + '</tbody></table></div>')
    return panel(f"Competitors ({len(d['rivals'])})", body, note=note,
                 flush=True)


def _history(d: dict) -> str:
    """Every observation ever recorded, because none was overwritten (8.2)."""
    hist = d.get("observation_history") or {}
    total = sum(len(v) for v in hist.values())
    if not total:
        return ""
    items = []
    for mid, obs in hist.items():
        key = obs[0].get("competitor_key") if obs else ""
        for o in obs:
            superseded = bool(o.get("superseded_by"))
            items.append((o.get("observed_at") or "",
                          '<li>'
                          f'<div class="when">{when(o.get("observed_at"))}'
                          f' · {e(key)}</div>'
                          f'<div class="what">'
                          f'{money(o.get("price"), o.get("currency"))}'
                          + (f' · {e(o.get("availability"))}'
                             if o.get("availability") else "")
                          + (f' · offer: {e(o.get("offer_wording"))}'
                             if o.get("offer_wording") else "")
                          + '</div>'
                          + '<div class="ev">'
                          + badges(prov(o.get("provenance"), short=True),
                                   pill("superseded", "quiet") if superseded
                                   else pill("current", "ok"))
                          + (f' {e(o.get("note"))}' if o.get("note") else "")
                          + '</div></li>'))
    items.sort(key=lambda t: t[0], reverse=True)
    body = '<ul class="hist">' + "".join(h for _, h in items[:40]) + "</ul>"
    return panel(f"Observation history ({total})", body,
                 note="a correction adds an observation; nothing is overwritten")


def _facts(d: dict) -> str:
    p = d["product"]
    rows = [("Clara price", money(d["clara_price"], d["currency"])),
            ("Product id", f'<span class="mono">{e(d["product_id"])}</span>'),
            ("Segment", e(d["segment"])),
            ("Category", e((d["category"] or "").replace("_", " "))),
            ("Format", e((p.get("product_format") or "").replace("_", " "))),
            ("Rating", (f'{p["rating"]} from {p.get("rating_count") or 0} '
                        f'ratings') if p.get("rating") else ""),
            ("First seen", when(p.get("first_seen_at"), date_only=True)),
            ("Last seen", when(p.get("last_seen_at"), date_only=True)),
            ("Provenance", prov(p.get("provenance"))),
            ("Comparable rivals",
             f'{d["priced_count"]} of {d["match_count"]}'
             if d["match_count"] else '<span class="na">none</span>')]
    for k, v in (d.get("specs") or {}).items():
        rows.append((k.replace("_", " ").capitalize(),
                     e("yes" if v is True else "no" if v is False else v)))
    img = (f'<img class="thumb lg" src="{e(d["image_url"])}" alt="" '
           f'loading="lazy">' if d["image_url"] else "")
    return panel("This product",
                 (f'<div class="row">{img}<div>' if img else "<div>")
                 + kv(rows) + "</div>" + ("</div>" if img else ""))


def _open_work(d: dict) -> str:
    acts = d.get("all_actions") or []
    if not acts:
        return panel("Actions",
                     '<p class="note good">No action has ever been raised on '
                     'this product.</p>')
    from ..ops import ACTION_STATUS_LABEL, ACTION_TYPE_LABEL
    rows = []
    for a in acts:
        rows.append(
            f'<li><div class="when">{when(a.get("created_at"))}</div>'
            f'<div class="what"><a href="/actions/{e(a["action_id"])}">'
            f'{e(ACTION_TYPE_LABEL.get(a["action_type"], a["action_type"]))}</a>'
            f' — {e(ACTION_STATUS_LABEL.get(a["status"], a["status"]))}</div>'
            f'<div class="ev">{e((a.get("reason") or "")[:160])}</div></li>')
    return panel(f"Actions ({len(acts)})",
                 '<ul class="hist">' + "".join(rows) + "</ul>",
                 acts=f'<a class="b b-sm" href="/actions?q={e(d["product_id"])}">'
                      'In the queue</a>')


def _requests_panel(d: dict) -> str:
    reqs = d.get("requests") or []
    body = ""
    if reqs:
        from ..ops import REQUEST_STATUS_LABEL, REQUEST_TYPE_LABEL
        rows = []
        for r in reqs:
            rows.append(
                f'<li><div class="when">{when(r.get("created_at"))} · '
                f'{e(r.get("requester"))}</div>'
                f'<div class="what"><a href="/requests/{e(r["request_id"])}">'
                f'{e(r.get("subject") or "")}</a></div>'
                f'<div class="ev">'
                f'{e(REQUEST_TYPE_LABEL.get(r["request_type"], r["request_type"]))}'
                f' · {e(REQUEST_STATUS_LABEL.get(r["status"], r["status"]))}'
                '</div></li>')
        body = '<ul class="hist">' + "".join(rows) + "</ul>"
    else:
        body = ('<p class="note">No request has been raised about this '
                'product.</p>')
    return panel("Requests", body,
                 acts=send_request_btn("product", d["product_id"],
                                       label="Send Request", small=True))


def _audit(d: dict) -> str:
    """8.1's fields, on the record they describe."""
    rows = d.get("audit") or []
    if not rows:
        return ""
    from .admin_view import audit_line
    return panel(f"Change history ({len(rows)})",
                 '<ul class="hist">'
                 + "".join(audit_line(a) for a in rows[:25]) + "</ul>",
                 note="append-only; corrections preserve what they replaced")
