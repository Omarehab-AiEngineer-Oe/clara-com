"""The Competitors tab (3), and the routable competitor page (3.1).

Section 3 asks for the competitor directory, competitor products, source
coverage, observed prices, offers, commercial profile, approved sources and
change history. All nine appear here, and one of them is separated on purpose.

**The commercial profile is kept apart from what was observed.** The profile is a
maintained note — positioning, typical price band, discount habit, audience. The
observations are readings from their pages. Putting them in one block would let a
maintained sentence be read as this morning's price, so they sit in two panels
with two headings, and the profile panel says what it is.

**A source is a record with a state, not a link.** Section 4.3 exists because
sources break, so a competitor's sources are listed with their status, failure
count, last successful read and approval state — and each broken one carries the
action that fixes it. A page that lists URLs without saying which of them worked
this morning is a page that hides the actual problem.
"""

from __future__ import annotations

from ..ops import (ACTION_STATUS_LABEL, ACTION_TYPE_LABEL,
                   MATCH_STATUS_LABEL, SourceStatus)
from .shell import (agent_btn, applied, badges, confidence, e, empty,
                    filter_bar, fresh, kv, money, page_head, pager, panel,
                    pill, prov, send_request_btn, stat, stats, when)
from .products import STATUS_TONE
from .read import COMPETITOR_SORTS

SOURCE_TONE = {
    SourceStatus.ACTIVE: "ok", SourceStatus.UNREADABLE: "bad",
    SourceStatus.UNAVAILABLE: "no", SourceStatus.PENDING_VERIFICATION: "amb",
    SourceStatus.APPROVED_FEED: "clara",
}
SOURCE_LABEL = {
    SourceStatus.ACTIVE: "Readable", SourceStatus.UNREADABLE: "Unreadable",
    SourceStatus.UNAVAILABLE: "Unavailable",
    SourceStatus.PENDING_VERIFICATION: "Verification requested",
    SourceStatus.APPROVED_FEED: "Approved feed",
}

COVERAGE_FILTER = [
    ("", "Any coverage"), ("attention", "Needs attention"),
    ("unread", "Has an unreadable source"),
    ("observed", "Has current observations"),
    ("nothing_observed", "Nothing observed yet"),
]


# --------------------------------------------------------------------------
# the directory
# --------------------------------------------------------------------------

def render_list(data: dict, *, query: dict, segments: list) -> str:
    c = data["counts"]
    P = ['<div class="wrap">']
    P.append(page_head(
        "Competitors",
        "Who Clara is compared against, what has actually been read from them, "
        "and which of their sources still work.",
        acts=send_request_btn(label="Send Request", primary=True)))

    P.append(stats([
        stat(c["total"], "On record", "Every competitor in the directory.",
             tone="calm", href="/competitors"),
        stat(c["observed"], "With current observations",
             "At least one observation that has not been superseded.",
             tone="good", href="/competitors?coverage=observed"),
        stat(c["silent"], "Nothing observed",
             "In the directory, but no current reading exists.",
             tone="warn" if c["silent"] else "calm",
             href="/competitors?coverage=nothing_observed"),
        stat(c["broken"], "With a broken source",
             "At least one source marked unreadable or unavailable.",
             tone="hot" if c["broken"] else "good",
             href="/competitors?coverage=unread"),
    ]))
    P.append(f'<p class="note">{e(data["definition"])}</p>')

    fields = [("q", "Search", None, "Brand or key"),
              ("segment", "Segment",
               [("", "Any segment")] + [(s, s.replace("_", " "))
                                        for s in segments]),
              ("coverage", "Coverage", COVERAGE_FILTER),
              ("sort", "Sort", [(k, v) for k, v in COMPETITOR_SORTS.items()])]
    body = (filter_bar("/competitors", fields, query)
            + applied("/competitors", query,
                      {"q": "Search", "segment": "Segment",
                       "coverage": "Coverage"}))

    if not data["rows"]:
        body += empty("No competitor matches these filters",
                      f"{c['total']} competitors are on record; none matches "
                      "every filter above.",
                      '<a class="b" href="/competitors">Clear filters</a>')
    else:
        body += ('<div class="scroll"><table class="t"><thead><tr>'
                 '<th>Competitor</th><th>Compared</th><th>Observed prices</th>'
                 '<th>Offers</th><th>Sources</th><th>Evidence</th>'
                 '</tr></thead><tbody>')
        for r in data["rows"]:
            body += _list_row(r)
        body += '</tbody></table></div>'
        body += pager("/competitors", query, data["total"], data["limit"],
                      data["offset"], "competitors")

    P.append(panel("", body, flush=True))
    P.append("</div>")
    return "".join(P)


def _list_row(r: dict) -> str:
    attn = ' class="attn"' if (r["open_actions"] or r["broken_sources"]) else ""

    if r["price_min"] is None:
        band = '<span class="na">nothing observed</span>'
    else:
        cur = ", ".join(r["currencies"]) or ""
        band = (money(r["price_min"], cur) if r["price_min"] == r["price_max"]
                else f'{money(r["price_min"])}–{money(r["price_max"], cur)}')
        band += f'<div class="sub">{r["observed_count"]} current</div>'
        if len(r["currencies"]) > 1:
            band += ('<div class="sub"><span class="na">mixed currencies — '
                     'not comparable</span></div>')

    srcs = ""
    if r["source_count"]:
        broken = len(r["broken_sources"])
        srcs = (f'{r["source_count"]}'
                + (f'<div class="sub"><span class="lose">{broken} broken'
                   f'</span></div>' if broken else
                   '<div class="sub">all readable</div>'))
    else:
        srcs = '<span class="na">none</span>'
    if r["feeds"]:
        srcs += f'<div class="sub">{len(r["feeds"])} feed/API</div>'

    offers = ('<span class="na">none</span>' if not r["offers_unique"]
              else f'{r["offers_unique"]}<div class="sub">'
                   f'{r["offer_associations"]} associations</div>')

    return (f'<tr{attn}><td>'
            f'<a class="ttl" href="/competitors/{e(r["key"])}">'
            f'{e(r["brand"])}</a>'
            f'<div class="sub">{e(", ".join(r["segments"]) or r["key"])}</div>'
            '</td>'
            f'<td class="num">{r["compared"]}<div class="sub">of '
            f'{r["match_count"]} matches</div>'
            + (f'<div class="sub"><span class="lose">{r["undecided"]} '
               f'undecided</span></div>' if r["undecided"] else "")
            + '</td>'
            f'<td class="num">{band}</td>'
            f'<td class="num">{offers}</td>'
            f'<td class="num">{srcs}</td>'
            '<td>' + badges(
                fresh(r["freshness"]["state"], r["freshness"]["why"],
                      r["freshness"].get("days")),
                pill(f'{len(r["open_actions"])} open',
                     "solid") if r["open_actions"] else "")
            + '</td></tr>')


# --------------------------------------------------------------------------
# the detail page
# --------------------------------------------------------------------------

def render_detail(d: dict, *, query: dict, can_admin: bool = False) -> str:
    key = d["key"]
    acts = (send_request_btn("competitor", key, label="Send Request",
                             primary=True)
            + agent_btn("competitor", key, label="Ask the Agent", small=False)
            + (f'<a class="b" href="{e(d["home_url"])}" '
               f'rel="nofollow noopener">Open their site</a>'
               if d["home_url"] else ""))
    P = ['<div class="wrap">']
    P.append(page_head(d["brand"], acts=acts,
                       trail=[("Competitors", "/competitors"),
                              (d["brand"], None)]))
    P.append(badges(
        pill(", ".join(d["segments"]) or "unclassified", "quiet"),
        fresh(d["freshness"]["state"], d["freshness"]["why"],
              d["freshness"].get("days")),
        pill(f'{len(d["open_actions"])} open action'
             f'{"s" if len(d["open_actions"]) != 1 else ""}', "solid")
        if d["open_actions"] else pill("No open action", "ok")))

    if d["broken_sources"]:
        P.append(f'<p class="note bad">{len(d["broken_sources"])} of '
                 f'{d["source_count"]} sources could not be read. Until one is '
                 f'replaced or a value is entered by hand, prices from this '
                 f'competitor are not current.</p>')

    P.append('<div class="cols"><div>')
    P.append(_observed(d))
    P.append(_matches(d))
    P.append(_offers(d))
    P.append(_their_products(d))
    P.append('</div><div>')
    P.append(_sources(d, can_admin))
    P.append(_profile(d))
    P.append(_actions_panel(d))
    P.append(_audit(d))
    P.append('</div></div></div>')
    return "".join(P)


def _observed(d: dict) -> str:
    """What was actually read from them. Kept apart from the profile."""
    obs = d["observations"]
    if not obs:
        return panel(
            "Observed prices",
            empty("Nothing has been read from this competitor",
                  "No current observation exists, so there is no price, "
                  "availability or offer to report. That is a collection gap "
                  "rather than a finding about their pricing.",
                  send_request_btn("competitor", d["key"],
                                   label="Request collection", primary=True)),
            flush=True)
    rows = []
    for o in sorted(obs, key=lambda x: (x.get("observed_at") or ""),
                    reverse=True):
        f = __import__("clara_monitor.ops.agent", fromlist=["freshness"]) \
            .freshness(o.get("observed_at"))
        rows.append(
            '<tr><td>'
            + (f'<a class="ttl" href="/products/'
               f'{e(_product_of(d, o))}">{e(_product_name(d, o))}</a>'
               if _product_of(d, o) else
               '<span class="na">not linked to a Clara product</span>')
            + '</td>'
            f'<td class="num">{money(o.get("price"), o.get("currency"))}'
            + (f'<div class="sub">was '
               f'{money(o.get("was_price"), o.get("currency"))}</div>'
               if o.get("was_price") else "")
            + '</td>'
            f'<td>{e(o.get("availability") or "not recorded")}</td>'
            '<td>' + badges(prov(o.get("provenance"), short=True),
                            fresh(f["state"], f["why"], f.get("days")))
            + f'<div class="ev">{when(o.get("observed_at"))}'
            + (f' · <a href="{e(o["source_url"])}" rel="nofollow noopener">'
               f'source</a>' if o.get("source_url") else "")
            + '</div></td>'
            '<td class="num">'
            + send_request_btn("observation", o["obs_id"], label="Verify",
                              small=True)
            + '</td></tr>')
    body = ('<div class="scroll"><table class="t"><thead><tr>'
            '<th>Clara product</th><th>Their price</th><th>Availability</th>'
            '<th>Evidence</th><th></th></tr></thead><tbody>'
            + "".join(rows) + '</tbody></table></div>')
    return panel(f"Observed prices ({len(obs)})", body,
                 note="current observations only; superseded values are in the "
                      "history below", flush=True)


def _product_of(d: dict, o: dict) -> str:
    for m in d["matches"]:
        if m["match_id"] == o.get("match_id"):
            return m.get("clara_product_id") or ""
    return ""


def _product_name(d: dict, o: dict) -> str:
    for m in d["matches"]:
        if m["match_id"] == o.get("match_id"):
            return m.get("clara_product_name") or m.get("clara_product_id") or ""
    return ""


def _matches(d: dict) -> str:
    ms = d["matches"]
    if not ms:
        return ""
    rows = []
    for m in sorted(ms, key=lambda x: (x["status"],
                                       x.get("clara_product_name") or "")):
        rows.append(
            '<tr><td>'
            f'<a class="ttl" href="/products/{e(m["clara_product_id"])}">'
            f'{e(m.get("clara_product_name") or m["clara_product_id"])}</a>'
            f'<div class="sub">'
            f'{e(m.get("competitor_product_name") or "their product not named")}'
            '</div></td>'
            '<td>' + badges(
                pill(MATCH_STATUS_LABEL.get(m["status"], m["status"]),
                     STATUS_TONE.get(m["status"], "quiet")),
                confidence(m.get("confidence")),
                prov(m.get("provenance"), short=True))
            + (f'<div class="ev">version {m.get("version")} · '
               f'{when(m.get("updated_at"))}</div>')
            + '</td>'
            '<td class="num">'
            + send_request_btn("match", m["match_id"], label="Review",
                              small=True)
            + '</td></tr>')
    body = ('<div class="scroll"><table class="t"><thead><tr>'
            '<th>Clara product</th><th>Match</th><th></th>'
            '</tr></thead><tbody>' + "".join(rows) + '</tbody></table></div>')
    return panel(f"Matched against Clara ({len(ms)})", body, flush=True)


def _offers(d: dict) -> str:
    o = d["offers"]
    if not o["unique"]:
        return ""
    rows = []
    for g in o["rows"]:
        prods = "".join(
            f'<li><a href="/products/{e(p["clara_product_id"])}">'
            f'{e(p["name"] or p["clara_product_id"])}</a> — '
            f'{money(p["price"], p["currency"])}</li>'
            for p in g["products"][:12])
        rows.append(
            f'<div class="opt-row"><h3>{e(g["wording"])}</h3>'
            f'<div class="oh">'
            + badges(fresh(g["freshness"]["state"], g["freshness"]["why"],
                           g["freshness"].get("days")),
                     prov(g["provenance"], short=True),
                     pill(f'{g["association_count"]} product'
                          f'{"s" if g["association_count"] != 1 else ""}',
                          "quiet"))
            + f' observed {when(g["observed_at"])} '
            + send_request_btn("offer", g.get("obs_id") or "",
                               label="Verify this offer", small=True)
            + '</div>'
            + (f'<ul class="hist">{prods}</ul>' if prods else "")
            + "</div>")
    return panel(f"Offers ({o['unique']} unique)",
                 '<div class="opts">' + "".join(rows) + "</div>",
                 note=o["definition"], flush=True)


def _their_products(d: dict) -> str:
    ps = d.get("products") or []
    if not ps:
        return ""
    rows = []
    for p in ps[:60]:
        rows.append(
            '<li><div class="what">'
            + (f'<a href="{e(p["url"])}" rel="nofollow noopener">'
               f'{e(p.get("name") or p["url"])}</a>' if p.get("url")
               else e(p.get("name") or p["cp_id"]))
            + '</div>'
            '<div class="ev">' + badges(prov(p.get("provenance"), short=True))
            + f' first seen {when(p.get("first_seen_at"), date_only=True)}'
            f' · last seen {when(p.get("last_seen_at"), date_only=True)}'
            '</div></li>')
    return panel(f"Their products on record ({len(ps)})",
                 '<ul class="hist">' + "".join(rows) + "</ul>")


def _sources(d: dict, can_admin: bool) -> str:
    """Source coverage, with its state — the thing 4.3 acts on."""
    srcs = d["sources"]
    if not srcs and not d["feeds"]:
        return panel("Sources",
                     '<p class="note warn">No source is registered for this '
                     'competitor, so nothing can be collected from them.</p>')
    rows = []
    for s in sorted(srcs, key=lambda x: (x.get("status") != "unreadable",
                                         x.get("url") or "")):
        st = s.get("status") or "active"
        rows.append(
            '<li>'
            + badges(pill(SOURCE_LABEL.get(st, st), SOURCE_TONE.get(st, "quiet")),
                     pill("approved", "ok") if s.get("is_approved")
                     else pill("not approved", "quiet"))
            + f'<div class="what"><a href="{e(s.get("url"))}" '
              f'rel="nofollow noopener">{e((s.get("url") or "")[:80])}</a></div>'
            + '<div class="ev">'
            + f'last read {when(s.get("last_ok_at"))}'
            + f' · last tried {when(s.get("last_attempt_at"))}'
            + (f' · {s.get("fail_count")} failures' if s.get("fail_count")
               else "")
            + (f'<br>{e(s.get("last_failure"))}' if s.get("last_failure")
               else "")
            + '</div>'
            + '<div class="ev">'
            + send_request_btn("source", s["source_id"], label="Review source",
                              small=True)
            + '</div></li>')
    for f in d["feeds"]:
        rows.append(
            '<li>' + badges(
                pill("Feed/API", "clara"),
                pill("approved", "ok") if f.get("is_approved")
                else pill("awaiting approval", "amb"))
            + f'<div class="what">{e(f.get("name"))}</div>'
            f'<div class="ev">{e((f.get("endpoint") or "")[:80])}<br>'
            f'registered by {e(f.get("registered_by") or "unknown")} '
            f'{when(f.get("registered_at"))}'
            + (f' · approved by {e(f["approved_by"])}' if f.get("approved_by")
               else "")
            + '</div></li>')
    acts = ('<a class="b b-sm" href="/admin/sources">Manage</a>'
            if can_admin else "")
    return panel(f"Sources ({len(srcs)}"
                 + (f" + {len(d['feeds'])} feed/API" if d["feeds"] else "")
                 + ")", '<ul class="hist">' + "".join(rows) + "</ul>",
                 acts=acts)


def _profile(d: dict) -> str:
    """The maintained commercial note. Never mixed with observations.

    The heading and the note say what this is. A maintained sentence about a
    competitor's discount habit is useful; a reader mistaking it for a price
    read this morning is not, and separate panels are the only reliable way to
    keep the two apart.
    """
    prof = d.get("profile") or {}
    if not prof:
        return panel("Commercial profile",
                     '<p class="note">No profile note is maintained for this '
                     'competitor.</p>')
    rows = []
    for k, v in prof.items():
        if v in (None, "", [], {}):
            continue
        if isinstance(v, (list, tuple)):
            v = ", ".join(str(x) for x in v)
        rows.append((k.replace("_", " ").capitalize(), e(v)))
    return panel("Commercial profile", kv(rows),
                 note="a maintained note, not an observation")


def _actions_panel(d: dict) -> str:
    acts = d.get("all_actions") or []
    if not acts:
        return panel("Actions", '<p class="note good">No action has been '
                                'raised on this competitor.</p>')
    rows = []
    for a in acts:
        rows.append(
            f'<li><div class="when">{when(a.get("created_at"))}</div>'
            f'<div class="what"><a href="/actions/{e(a["action_id"])}">'
            f'{e(ACTION_TYPE_LABEL.get(a["action_type"], a["action_type"]))}</a>'
            f' — {e(ACTION_STATUS_LABEL.get(a["status"], a["status"]))}</div>'
            f'<div class="ev">{e((a.get("reason") or "")[:150])}</div></li>')
    return panel(f"Actions ({len(acts)})",
                 '<ul class="hist">' + "".join(rows) + "</ul>",
                 acts=f'<a class="b b-sm" href="/actions?competitor='
                      f'{e(d["key"])}">In the queue</a>')


def _audit(d: dict) -> str:
    rows = d.get("audit") or []
    if not rows:
        return ""
    from .admin_view import audit_line
    return panel(f"Change history ({len(rows)})",
                 '<ul class="hist">'
                 + "".join(audit_line(a) for a in rows[:25]) + "</ul>",
                 note="append-only")
