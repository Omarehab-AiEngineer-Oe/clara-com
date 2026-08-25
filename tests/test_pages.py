"""Checks for the three-page layer: data -> insight -> decision -> action.

Two kinds of thing are asserted here, and the second kind is the one that has
actually caught bugs.

**Shape.** Every decision carries the six parts the page promises, the impact
ladder is hard to top out, and the three pages draw on one stylesheet.

**Properties that survive the data changing.** A drill-down link must resolve to
something that exists; a page must not invent a currency conversion; a metric
must not be reported as measured when it was not. These are written against the
live bundle rather than a fixture, because a fixture agrees with whatever the
code did when it was written — which is exactly how the seed-rediscovery bug
survived three rounds of green tests.

Run directly: `python tests/test_pages.py`
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from clara_monitor import (decisions_page, intel_sections as isec,  # noqa: E402
                          scan_layer, site, trend_page, ui)

PASS, FAIL = [], []


def ok(cond, label: str):
    (PASS if cond else FAIL).append(label)
    print(f"  {'PASS' if cond else 'FAIL'}  {label}")


def section(name: str):
    print(f"\n{name}\n" + "-" * len(name))


# --------------------------------------------------------------------------
# impact: the ladder must be hard to top out
# --------------------------------------------------------------------------

def test_impact():
    section("impact")
    cases = [
        ({"urgency": "now", "confidence": "HIGH", "gap_percent": -44}, "critical"),
        ({"urgency": "this_week", "confidence": "HIGH"}, "high"),
        ({"urgency": "this_month", "confidence": "HIGH", "stage": "rising"}, "high"),
        ({"urgency": "this_month", "confidence": "MEDIUM"}, "medium"),
        ({"urgency": "watch", "confidence": "LOW"}, "low"),
        ({}, "low"),
    ]
    for item, want in cases:
        got, why = ui.impact_of(item)
        ok(got == want, f"{item or 'empty'} -> {want} (got {got})")
    # A page where everything is critical has no hierarchy, so the top rung must
    # need more than one strong signal.
    lvl, _ = ui.impact_of({"urgency": "now"})
    ok(lvl != "critical", "urgency alone does not reach critical")
    lvl, _ = ui.impact_of({"confidence": "HIGH", "gap_percent": -90})
    ok(lvl != "critical", "a big gap with no urgency does not reach critical")
    ok(ui.impact_of({})[1], "an unremarkable item still explains itself")


def test_ordering():
    section("ordering")
    items = [
        {"urgency": "this_week", "confidence": "LOW", "impact": "low",
         "what": "b", "trend": False},
        {"urgency": "this_month", "confidence": "HIGH", "impact": "critical",
         "what": "a", "trend": False},
    ]
    order = sorted(items, key=lambda i: ui.IMPACT_ORDER.index(i["impact"]))
    ok(order[0]["what"] == "a",
       "a critical call due this month outranks a low one due this week")


# --------------------------------------------------------------------------
# the shared layer
# --------------------------------------------------------------------------

def test_shared_css():
    section("one design layer, three pages")
    need = set(re.findall(r"var\((--[a-z0-9-]+)\)", ui.SHARED_CSS))
    for name, css in (("comparator", site.CSS), ("trends", trend_page.CSS)):
        have = set(re.findall(r"(--[a-z0-9-]+)\s*:", css))
        missing = sorted(need - have)
        ok(not missing, f"{name} defines every token SHARED_CSS uses "
                        f"{'' if not missing else missing}")
    need2 = set(re.findall(r"var\((--[a-z0-9-]+)\)", decisions_page.EXTRA_CSS))
    have = set(re.findall(r"(--[a-z0-9-]+)\s*:", site.CSS))
    ok(not (need2 - have), "the decisions page defines every token it uses")

    ok("bx-critical" in ui.SHARED_CSS and "bx-HIGH" in ui.SHARED_CSS,
       "impact and confidence badges live in one place")
    for page in (site, trend_page, decisions_page):
        src = Path(page.__file__).read_text(encoding="utf-8")
        ok(".bx-critical{" not in src,
           f"{Path(page.__file__).name} does not redefine a shared badge")


def test_components():
    section("components")
    ok(ui.metrics([]) == "", "an empty metric strip renders nothing at all")
    ok(ui.metrics(["", None]) == "", "a strip of empty metrics renders nothing")
    ok(ui.insight("") == "", "an empty insight renders nothing")
    ok(ui.crosslinks(["", None]) == "", "an empty crosslink row renders nothing")
    ok("&lt;b&gt;" in ui.metric("<b>", "k"), "a metric value is escaped")
    ok("&lt;i&gt;" in ui.insight("<i>"), "an insight is escaped")
    ok('rel="nofollow noopener"' in ui.crosslink("u", "l", external=True),
       "an external link carries nofollow noopener")
    ok('rel=' not in ui.crosslink("/x", "l"), "an internal link does not")


# --------------------------------------------------------------------------
# properties against the live bundle
# --------------------------------------------------------------------------

def _bundle():
    import serve
    return serve.build_bundle(serve.STATE["run_id"])


def test_decision_shape(bundle):
    section("every decision carries what the page promises")
    items = isec.decision_items(bundle, bundle.get("trends"))
    ok(bool(items), f"{len(items)} decision(s) were raised")
    required = ("what", "insight", "metrics", "relevant", "impact",
                "impact_why", "confidence", "urgency", "owner")
    for key in required:
        missing = [i for i in items if key not in i]
        ok(not missing, f"every decision has '{key}'")

    ok(all(i["impact"] in ui.IMPACT_ORDER for i in items),
       "every impact is on the ladder")
    ok(all(i["urgency"] in ui.URGENCY_ORDER for i in items),
       "every urgency is on the ladder")
    # ordering is the page's whole hierarchy claim
    ranks = [ui.IMPACT_ORDER.index(i["impact"]) for i in items]
    ok(ranks == sorted(ranks), "decisions come out ordered by impact")

    # a decision must be traceable, or it is an assertion
    untraceable = [i for i in items
                   if not i.get("competitor_key") and not i.get("topic_key")
                   and not i.get("links")]
    ok(not untraceable,
       f"every decision can be traced back {[i['entity'] for i in untraceable]}")

    # and it must not say the same sentence twice
    echoes = [i for i in items if i.get("insight")
              and i["insight"] == i.get("why")]
    ok(not echoes, "no decision states its insight and its reason identically")


def test_links_resolve(bundle):
    section("drill-down links resolve to something that exists")
    trends = bundle.get("trends") or {}
    items = isec.decision_items(bundle, trends)
    topic_keys = {t["key"] for t in (trends.get("topics") or [])}
    comp_keys = {c["key"] for c in
                 ((bundle.get("competitors") or {}).get("competitors") or [])}

    bad_t = [i["topic_key"] for i in items
             if i.get("topic_key") and i["topic_key"] not in topic_keys]
    ok(not bad_t, f"every topic_key names a real subject {bad_t}")
    bad_c = [i["competitor_key"] for i in items
             if i.get("competitor_key") and i["competitor_key"] not in comp_keys]
    ok(not bad_c, f"every competitor_key names a real competitor {bad_c}")

    # and the pages must actually emit them
    dec = decisions_page.render(bundle, trends)
    emitted_t = set(re.findall(r"\?trend=([^\"&#]+)", dec))
    emitted_c = set(re.findall(r"\?focus=([^\"&#]+)", dec))
    ok(emitted_t <= topic_keys, f"no dangling ?trend= on the page {emitted_t - topic_keys}")
    ok(emitted_c <= comp_keys, f"no dangling ?focus= on the page {emitted_c - comp_keys}")
    ok(bool(emitted_t or emitted_c), "the decisions page emits drill-down links")

    comp = site.render(bundle)
    ok('data-key=' in comp, "competitor cards carry the key ?focus= looks up")
    ok('/decisions' in comp, "the comparator links back to the decisions")
    tr = trend_page.render(trends, items)
    ok('/decisions' in tr, "the trends page links back to the decisions")
    ok('/#prices' in tr or '"/"' in tr, "the trends page links to the comparator")
    ok('/trends' in dec and '/#' in dec,
       "the decisions page links to both of the others")


def test_no_invented_numbers(bundle):
    section("no invented numbers")
    rows = scan_layer._pairings(bundle)
    ok(all(r["pct"] is not None for r in rows), "every ranked pairing has a gap")
    # the property that matters: a cross-currency pairing is never ranked
    all_matches = [m for p in (bundle.get("price") or {}).get("products") or []
                   for m in (p.get("matches") or [])]
    cross = [m for m in all_matches
             if m.get("status") in ("confirmed_match", "probable_match")
             and m.get("competitor_price") and not m.get("same_currency")]
    ranked_urls = {r["url"] for r in rows}
    leaked = [m for m in cross if m.get("competitor_url") in ranked_urls]
    ok(not leaked, f"no cross-currency pairing reaches a ranking {len(leaked)}")
    if cross:
        band = scan_layer.comparator_band(bundle)
        ok("different currencies" in band,
           f"the {len(cross)} excluded pairing(s) are declared, not dropped")

    # the trend score must never claim to have measured social engagement
    for t in (bundle.get("trends") or {}).get("topics") or []:
        soc = ((t.get("score") or {}).get("social") or {})
        if soc:
            ok(soc.get("state") == "not measured" and soc.get("value") is None,
               f"{t['key']}: social engagement is reported as not measured")
            break
    tr = trend_page.render(bundle.get("trends") or {},
                           isec.decision_items(bundle, bundle.get("trends")))
    ok("not measured" in tr, "the trends page says so on the page itself")


def test_degrades_honestly():
    section("a build with no cycle says so rather than guessing")
    mini = {"price": {"products": []},
            "competitors": {"total": 0, "competitors": []}}
    band = scan_layer.comparator_band(mini)
    ok("/decisions" not in band,
       "no link to a decisions page that has nothing behind it")
    ok("has not been run" in band or "not run" in band,
       "the missing cycle is stated")
    ok("Nothing changed" not in band,
       "an unrun comparison is never reported as 'nothing changed'")

    page = decisions_page.render(mini)
    ok("Nothing is waiting on a decision" in page,
       "the empty decisions page explains which half is empty")
    ok(len(isec.decision_items(mini, None)) == 0,
       "no decision is invented from an empty bundle")

    band2 = scan_layer.trends_band({}, [])
    ok("enough evidence yet" in band2, "an empty trend scan says so")


def test_hierarchy(bundle):
    section("visual hierarchy is enforced, not decorated")
    page = decisions_page.render(bundle, bundle.get("trends"))
    heroes = page.count('class="dc hero"') + page.count('class="dc trend hero"')
    total = len(re.findall(r'class="dc(?: trend)?(?: hero)?"', page))
    ok(heroes <= decisions_page.HERO_COUNT,
       f"at most {decisions_page.HERO_COUNT} cards get the hero treatment "
       f"({heroes} of {total})")
    if total > decisions_page.HERO_COUNT:
        ok(heroes == decisions_page.HERO_COUNT,
           "the hero band is filled when there are enough decisions")
    ok("&amp;mdash;" not in page and "&amp;middot;" not in page,
       "no double-escaped entity on the decisions page")
    for name, html in (("comparator", site.render(bundle)),
                       ("trends", trend_page.render(
                           bundle.get("trends") or {},
                           isec.decision_items(bundle, bundle.get("trends"))))):
        ok("&amp;mdash;" not in html and "&amp;middot;" not in html,
           f"no double-escaped entity on the {name} page")


if __name__ == "__main__":
    test_impact()
    test_ordering()
    test_shared_css()
    test_components()
    test_degrades_honestly()

    try:
        b = _bundle()
    except Exception as exc:                      # noqa: BLE001
        print(f"\n!! could not build the live bundle: {exc}")
        print("   the shape checks above still ran; the property checks did not.")
        b = None

    if b is not None:
        test_decision_shape(b)
        test_links_resolve(b)
        test_no_invented_numbers(b)
        test_hierarchy(b)

    print("\n" + "=" * 68)
    print(f"{len(PASS)}/{len(PASS) + len(FAIL)} checks pass")
    for f in FAIL:
        print(f"  FAILED: {f}")
    sys.exit(1 if FAIL else 0)
