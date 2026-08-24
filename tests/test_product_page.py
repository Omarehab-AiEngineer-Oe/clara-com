"""A page per product, and the six dimensions section 6.2 governs.

    Marketing campaigns · Advertising · SEO
    Social media · Copywriting or content generation · Customer acquisition

These six are IN as evidence and OUT as output. That is the line 6.2 already
draws and the reason the agent contracts state it as a verb rather than a topic:
reading a rival's promotion off their page and recording its wording is
evidence, proposing one is not. The tests here hold both halves — that the
observed side is populated from real matches, and that the produced side is
refused in writing on every page.

**Three of the six have no instrument at all.** No social reader, no acquisition
data, no SEO index — and §6 of the audit PRD independently puts SEO rank and
backlink intelligence out of scope. Those three must render as loudly as the
other three, because a small grey note is how "we never looked" becomes "there
is nothing there" in a reader's memory. A blank section would be the absence
rule broken on the page.

**Nothing is converted.** Prices group by the currency the storefront quotes,
and Clara's price appears only in the column quoting the same currency. A
currency is not a country, so this is not a world price map and the page says so.

    python tests/test_product_page.py
"""
from __future__ import annotations

import io
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import serve  # noqa: E402  (replaces sys.stdout, so import before wrapping)

_kept_stdout = sys.stdout
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8",
                              errors="replace")

from clara_monitor import product_data as pdata, product_page as ppage  # noqa: E402

PASS, FAIL = [], []


def ok(cond, label):
    (PASS if cond else FAIL).append(label)
    print(f"  {'PASS' if cond else 'FAIL'}  {label}")


def section(title):
    print(f"\n{title}")


BUNDLE = serve.build_bundle(serve.STATE["run_id"])
PRODUCTS = (BUNDLE.get("price") or {}).get("products") or []
# The product with the most USABLE counterparts, not the most matches. A
# crawl that expands coverage makes the max-matches product a mostly-
# withheld one, and the assertions below are about what a populated page
# renders.
RICH = max(PRODUCTS, key=lambda p: (pdata.partition(p)["trusted_n"]
                                    + pdata.partition(p)["qualified_n"],
                                    len(p.get("matches") or [])))
BARE = min(PRODUCTS, key=lambda p: len(p.get("matches") or []))

# ------------------------------------------------------------------ the six
section("The six dimensions are all present, on every product")

# Three, not six. SEO, social and acquisition were removed: §6.2 excludes
# all six as OUTPUT, and for those three there is also nothing to OBSERVE
# on a competitor product page. Carrying them as permanent placeholders
# made a deliberate exclusion look like an unfilled gap.
ok(len(pdata.DIMENSIONS) == 3,
   f"three observable dimensions ({len(pdata.DIMENSIONS)})")
ok([d["key"] for d in pdata.DIMENSIONS]
   == ["campaigns", "advertising", "content"],
   "in the order 6.2 lists them")
ok(all(k not in pdata.DIMENSION for k in ("seo", "social", "acquisition")),
   "and the three with nothing to observe are gone, not rendered empty")
ok(all(d.get("refuses") for d in pdata.DIMENSIONS),
   "every dimension states what it refuses to produce — the refusal is the "
   "point of 6.2 and an unstated one is not enforced")
ok(all(d.get("reads") for d in pdata.DIMENSIONS if d["collected"]),
   "every collected dimension states what it reads from")
ok(all(d.get("would_take") for d in pdata.DIMENSIONS if not d["collected"]),
   "and every uncollected one states what collecting it would take")

collected = [d["key"] for d in pdata.DIMENSIONS if d["collected"]]
missing = [d["key"] for d in pdata.DIMENSIONS if not d["collected"]]
ok(collected == ["campaigns", "advertising", "content"],
   "three are instrumented: campaigns, advertising, content")
ok(missing == [],
   "every remaining dimension is instrumented, so nothing is a placeholder")

ok(all(len(d["refuses"].split()) >= 6 for d in pdata.DIMENSIONS),
   "each dimension states what it refuses to produce, in a sentence")
ok(any("6.2" in d["refuses"] for d in pdata.DIMENSIONS),
   "and the set names 6.2 as the requirement behind the refusals")

# ------------------------------------------------------------------ pages
section("Every product in the catalogue has a page that renders")

failures, dim_counts, gap_counts = [], set(), set()
for p in PRODUCTS:
    try:
        v = pdata.build(BUNDLE, p["product_id"])
        h = ppage.render(v)
    except Exception as exc:                              # noqa: BLE001
        failures.append(f"{p['product_id']}: {type(exc).__name__}: {exc}")
        continue
    dim_counts.add(len(re.findall(r'<article class="dim', h)))
    gap_counts.add(len(re.findall(r'dstate not_collected', h)))
    if len(h) < 8000:
        failures.append(f"{p['product_id']}: page suspiciously short")

ok(not failures,
   f"all {len(PRODUCTS)} products render"
   + ("" if not failures else f" — {failures[:2]}"))
# Only dimensions with something render. SEO, social and acquisition have no
# instrument, so they are on no page — no information, no heading.
ok(dim_counts <= {0, 1, 2, 3},
   f"a page shows only the dimensions that have data {sorted(dim_counts)}")
ok(gap_counts == {0},
   "and never a not-collected placeholder")

# ------------------------------------------------------------------ observed
section("The observed half is drawn from real matches")

v = pdata.build(BUNDLE, RICH["product_id"])
h = ppage.render(v)
ok(v["product"]["product_id"] == RICH["product_id"], "the product resolves")
ok(v["family"] in ("styling_devices", "hair_scalp_care", "protect_style",
                   "hair_accessories", "unclassified"),
   "and carries its product family")

camp = v["campaigns"]
ok(all(c["wording"].strip() for c in camp),
   "every campaign row has wording — an empty promotion is not a campaign")
ok(all(c.get("url") for c in camp), "and a page it was read from")

st = v["storefront"]
ok("storefront" in ppage._dimension_body(v, "advertising").lower(),
   "the advertising block says the evidence is storefront-wide")
ok("never" in ppage._dimension_body(v, "advertising"),
   "and says explicitly that it is not product-level — a site banner attached "
   "to one dryer would be an invention")

content = v["content"]
ok(content["clara"]["name"] == RICH["name"], "Clara's row is Clara's product")
ok(content["clara"]["images_note"],
   "and the Clara image count carries the caveat that it counts the catalogue "
   "row rather than the page")
ok("CAPTCHA" in h,
   "the page states that Clara's own site was never read, so no copy score is "
   "implied")
ok(not re.search(r'\bscore\b\s*[:=]\s*\d', h),
   "and no copy score is given, because the comparison behind one does not "
   "exist yet")

# ------------------------------------------------------------------ record
section("The page holds everything the popup held, and then some")

# The popup is gone. Pressing a product opens its page, and that page has to
# carry the whole record — otherwise the change moved information out of reach
# instead of into one place.
# Always present: these come from Clara's own catalogue row.
for label in ("Clara price", "Product id", "Family", "On clarahair.com"):
    ok(label in h, f"the record shows: {label}")

# Conditional: present exactly when the product has the value. That is the
# rule — a field with nothing in it takes its label with it — so the test
# checks the correspondence rather than a fixed list.
for label, has in (("Rating", bool(RICH.get("rating"))),
                   ("Cheapest comparable rival",
                    bool(RICH.get("cheapest_rival"))),
                   ("Published specifications", bool(RICH.get("specs")))):
    ok((label in h) == has,
       f"{label} renders exactly when the product has it (has={has})")

ok("The record" in h and "Counterparts" in h,
   "both the catalogue record and the counterpart blocks are on the page")
blocks = re.findall(r'<article class="mblk', h)
usable_n = len(pdata.partition(RICH)["usable"])
ok(len(blocks) == usable_n,
   f"one block per USABLE counterpart, not per match "
   f"({len(blocks)} of {usable_n} usable, "
   f"{len(RICH.get('matches') or [])} total)")

# Nine fields the popup withheld to keep its embedded payload small. The payload
# is gone, so there is no reason left to hide the part of the record that says
# how far to trust the rest of it.
for label in ("Match score", "How it was read", "Extraction verdict",
              "Comparison basis", "Validated", "Images on the page"):
    ok(label in h, f"and a field the popup never showed: {label}")

ok("not published" not in h and "none stated" not in h,
   "an absent field takes its label with it -- a caption over a dash reads as "
   "a page that failed to load")

# The card is a link now, and the payload and modal are gone from the grid.
report_early = serve.render_report({"username": "t", "role": "admin",
                                    "display_name": "T"},
                                   serve.STATE["run_id"]).decode()
ok('<a class="pcard"' in report_early,
   "a product card is a link, so pressing it opens the page")
ok('button class="pcard"' not in report_early,
   "and is no longer a button that opens a popup")
ok("__CLARA__" not in report_early,
   "the embedded product payload is gone — it existed only to fill the popup")
ok("pc-page" not in report_early,
   "and the separate market-and-content link is gone: it was a grid child, so "
   "it landed in its own cell and broke the card layout")

# ------------------------------------------------------------------ refused
section("The produced half is refused in writing")

ok("Refused as output" in h,
   "each rendered dimension states its refusal on the page")
live_dims = [d for d in v["dimensions"] if d["state"] == "observed"]
ok(h.count("Refused as output") == len(live_dims),
   f"one refusal per rendered dimension ({len(live_dims)})")
for phrase in ("Proposing a campaign", "Writing Clara"):
    ok(phrase in h, f"refusal is specific: {phrase}")
for gone in ("Posting, or advising", "Acquisition planning", "Rank tracking"):
    ok(gone not in h,
       f"an uncollected dimension is absent entirely: {gone}")
ok("6.2" in h, "and 6.2 is named as the reason")

# ------------------------------------------------------------------ brief
section("The best-content answer is a brief, not content")

ok("What a person has to decide" in h,
   "the page answers 'what is the best content' with a decision list")
ok(all(b.get("observed") and b.get("decision") for b in v["brief"]),
   "every brief line has both an observation and the decision it forces")
ok(all(b["dimension"] in ("campaigns", "advertising", "content")
       for b in v["brief"]),
   "and only cites the three dimensions that have evidence")
ok("stays with a person" in h or "person's to write" in h
   or "leaves it with a person" in h,
   "the page says the sentence itself is a person's to write")

# A product with nothing observed must say so rather than show an empty list.
vb = pdata.build(BUNDLE, BARE["product_id"])
hb = ppage.render(vb)
ok(len(re.findall(r'<article class="dim', hb))
   == len([d for d in vb["dimensions"] if d["state"] == "observed"]),
   "a product with no matches renders no dimension it has no data for")
if not vb["brief"]:
    ok("What a person has to decide" not in hb,
       "an empty brief renders no heading at all")
else:
    ok(True, "this product had evidence, so the empty path is untested here")

# ------------------------------------------------------------------ markets
section("Prices by market, with nothing converted")

with_two = None
for p in PRODUCTS:
    vv = pdata.build(BUNDLE, p["product_id"])
    if len(vv["markets"]["priced"]) > 1:
        with_two = vv
        break
ok(with_two is not None, "at least one product was observed in two currencies")
if with_two:
    rows = with_two["markets"]["priced"]
    ok(rows[0]["is_clara_currency"],
       "Clara's own currency comes first")
    ok(sum(1 for r in rows if r["clara_price"]) == 1,
       "Clara's price is placed in exactly one column — the one quoting the "
       "same currency")
    ok(all(r["clara_price"] is None for r in rows if not r["comparable"]),
       "and never in a column it would have to be converted into")
    hh = ppage.render(with_two)
    ok("a currency is not a country" in hh,
       "the page says a currency is not a country, so a USD column is not "
       "'the American market'")
    ok("not converted" in hh or "does not apply" in hh,
       "and that no rate is applied")

unp = [pdata.build(BUNDLE, p["product_id"]) for p in PRODUCTS[:25]]
any_unpriced = next((x for x in unp if x["markets"]["unpriced"]), None)
if any_unpriced:
    hu = ppage.render(any_unpriced)
    ok("publish no price" in hu,
       "rivals with no published price are named, not dropped")
    ok(all(u["why"] for u in any_unpriced["markets"]["unpriced"]),
       "and each carries why there was no price")
else:
    ok(True, "no unpriced rival in the sample")

# ------------------------------------------------------------------ routing
section("The pages are reachable")

report = serve.render_report({"username": "t", "role": "admin",
                              "display_name": "T"},
                             serve.STATE["run_id"]).decode()
ids = set(re.findall(r'/product\?id=([A-Za-z0-9_-]+)', report))
ok(len(ids) == len(PRODUCTS),
   f"every one of the {len(PRODUCTS)} product cards links to its page "
   f"({len(ids)} found)")
ok(ids == {p["product_id"] for p in PRODUCTS},
   "and the ids match the catalogue exactly")

# The bar is injected by the route, not by the renderer, so this has to read
# what is actually served rather than the raw page.
served = serve.render_product({"username": "t", "role": "admin",
                               "display_name": "T"},
                              RICH["product_id"]).decode()
nav = re.findall(r'class="lb[^"]*" href="[^"]*">([^<]+)', served)
# Three pages now. Website audit was removed on instruction, so a nav of
# four would mean a dead link back to a page that no longer exists.
ok(nav[:3] == ["Competitors", "Trends", "Decisions"],
   f"a product page carries the same livebar as every other page {nav[:3]}")
ok("Website audit" not in nav, "and the removed page is not linked")
ok("<title>" in served, "and its own title")

missing_page = ppage.render(pdata.build(BUNDLE, "does-not-exist"))
ok("No such product" in missing_page,
   "an unknown id renders a page saying so, not a traceback")
ok("Back to all products" in missing_page, "with a way back")



# ------------------------------------------------------------------ validate
section("Notes are checked against the data beside them")

from clara_monitor import validate  # noqa: E402
from clara_monitor.config import DB_PATH  # noqa: E402

RANGE_NOTE = "price shown as a range; min and max kept, no midpoint computed"

# The defect this was written for: `repair_prices.py` corrected 17 prices after a
# parsing bug and carried the OLD warnings across, so each row ended up saying a
# range had been kept beside a single price and two null ends. The note described
# the very bug that had just been fixed.
stale_row = {"warnings": [RANGE_NOTE], "price_is_range": False,
             "price_min": None, "price_max": None, "selling_price": "2299"}
found = validate.check(stale_row)
ok(len(found) == 1, "a range note beside a single price is caught")
ok(found[0]["verdict"] == "stale",
   "and called stale, because the parse it describes was replaced")
ok("re-derived" in found[0]["why"], "with the reason recorded")

fixed, _ = validate.repair(stale_row)
ok(RANGE_NOTE not in fixed["warnings"], "repair drops the stale note")
ok(fixed["selling_price"] == "2299", "and touches nothing else")

# A genuine range keeps its note.
real_range = {"warnings": [RANGE_NOTE], "price_is_range": True,
              "price_min": "100", "price_max": "200"}
ok(validate.check(real_range) == [], "a true range note is left alone")

# Data that disagrees with itself is reported and NOT silently cleaned: deleting
# the note would hide the disagreement rather than resolve it.
half = {"warnings": [RANGE_NOTE], "price_is_range": True,
        "price_min": "100", "price_max": None}
f2 = validate.check(half)
ok(f2 and f2[0]["verdict"] == "contradicted",
   "a half-recorded range is contradicted, not stale")
kept, _ = validate.repair(half)
ok(RANGE_NOTE in kept["warnings"],
   "and its note is kept, because removing it would hide the disagreement")

ok(validate.is_price_note(RANGE_NOTE), "price notes are recognised as such")
ok(not validate.is_price_note("no usable product image found"),
   "and a note from another extractor is not, so it survives re-derivation")
ok(validate.is_price_note("selling price 9 exceeds regular price 5; "
                          "source disagreement flagged, "
                          "no positive discount computed"),
   "the interpolated discount note is matched by prefix")

# The live database must be clean, and stay clean.
live = validate.scan(DB_PATH)
ok(live["stale"] == 0,
   f"no stale note remains in the database ({live['stale']} found)")
ok(live["contradicted"] == 0,
   f"and no row contradicts itself ({live['contradicted']} found)")
ok(live["checked"] > 0, f"{live['checked']} observation(s) were checked")

# and the root cause is fixed, not just the data
repair_src = (ROOT / "repair_prices.py").read_text(encoding="utf-8")
ok("validate.is_price_note" in repair_src,
   "repair_prices drops the previous parse's price notes rather than merging "
   "them — otherwise the same 17 rows come back on the next fix")

# no match on any page now carries a note its own data denies
bad = []
for p in PRODUCTS:
    for m in p.get("matches") or []:
        for w in m.get("warnings") or []:
            if "range" in w and not m.get("price_is_range"):
                bad.append(f"{p['product_id']}/{m.get('competitor_key')}")
ok(not bad, f"no rendered match claims a range it does not have {bad[:3]}")

# ------------------------------------------------------------------ enhance
section("How this product could be improved")

vr = pdata.build(BUNDLE, RICH["product_id"])
hr = ppage.render(vr)
ok("How this product could be improved" in hr, "the section is on the page")
ok(all(x.get("change") and x.get("observed") and x.get("validate")
       for x in vr["enhancements"]),
   "every opportunity has an observation, a change and a way to check it")
ok(all(x["area"] in ("catalogue data", "product page", "proof",
                     "price position", "coverage", "data quality")
       for x in vr["enhancements"]),
   "and names which area it touches")

weights = [x["weight"] for x in vr["enhancements"]]
ok(weights == sorted(weights, reverse=True),
   "ordered by how much evidence stands behind it, not by appeal")

# Spec gaps are Clara-against-Clara. Rival specs are not in the match record, so
# a claim about how Clara compares on wattage would have nothing behind it.
fmt_counts = {}
for p in PRODUCTS:
    fmt_counts[p.get("fmt")] = fmt_counts.get(p.get("fmt"), 0) + 1
big_fmt = max((f for f in fmt_counts if f and f != "unknown"),
              key=lambda f: fmt_counts[f])
gap_product = next((p for p in PRODUCTS
                    if p.get("fmt") == big_fmt and pdata.spec_gaps(BUNDLE, p)),
                   None)
if gap_product:
    g = pdata.spec_gaps(BUNDLE, gap_product)[0]
    ok(g["peers_with"] <= g["peers"],
       "a spec gap counts peers that publish it out of peers that exist")
    ok(g["peers_with"] / g["peers"] >= pdata.PEER_SHARE,
       "and only counts as a gap above the peer-share threshold")
    ok(g["spec"] not in (gap_product.get("specs") or {}),
       "the flagged spec really is missing from this product")
else:
    ok(True, "no spec gap in the sample")

# The bug this had: three specs are set on every product as bool(re.search(...)),
# so a False means the page text did not mention the feature — not that the field
# is unpublished. Flagging those produced "Publish ionic on this product's page"
# for products that simply are not ionic.
ok(pdata.ALWAYS_SET == ("ionic", "bldc_motor", "cold_shot"),
   "the always-set booleans are named")
never = [g["spec"] for p in PRODUCTS for g in pdata.spec_gaps(BUNDLE, p)
         if g["spec"] in pdata.ALWAYS_SET]
ok(not never,
   f"and none of them is ever reported as a gap {sorted(set(never))[:3]}")

no_enh = next((p for p in PRODUCTS
               if not pdata.build(BUNDLE, p["product_id"])["enhancements"]),
              None)
if no_enh:
    hn = ppage.render(pdata.build(BUNDLE, no_enh["product_id"]))
    ok("How this product could be improved" not in hn,
       "a product with no opportunity renders no heading for one")
else:
    ok(True, "every product had an opportunity")

# ------------------------------------------------------------------ sources
section("Every source carries its own age")

srcs = vr["sources"]
ok(len(srcs) == 6, f"six sources are declared in the data ({len(srcs)})")
ok(all(s.get("source") and s.get("covers") and s.get("state") for s in srcs),
   "each names itself, what it covers and its state")
names = [s["source"] for s in srcs]
ok("Clara catalogue" in names and "Competitor product pages" in names
   and "Competitor storefronts" in names and "Change events" in names
   and "Clara's own pages" in names,
   "including the storefront sweep and Clara's own pages")

blocked = [s for s in srcs if s["state"] == "blocked"]
ok(len(blocked) == 1 and blocked[0]["source"] == "Clara's own pages",
   "the data still records that Clara's own pages returned nothing")
ok("CAPTCHA" in blocked[0]["note"], "with the reason, for anyone auditing")
ok(blocked[0]["source"] not in hr,
   "but it is not rendered: a source that gave nothing is a gap, and this "
   "page carries none")

read = [s for s in srcs if s["state"] == "read"]
ok(all(s["read_at"] for s in read), "a source marked read carries a date")
ok(any(s["state"] not in ("read", "blocked") for s in srcs)
   or all(s["n"] for s in read),
   "and a source that returned nothing says so rather than showing a zero row")

ok("Sources and freshness" in hr, "the table is on the page")
shown_rows = len(re.findall(r'class="s-read"', hr))
ok(shown_rows == len([x for x in srcs
                      if x["state"] == "read" and x["read_at"]]),
   f"only sources that returned something are rendered ({shown_rows})")
ok(len(re.findall(r'class="s-(?:none|blocked)"', hr)) == 0,
   "and no row reports a source that gave nothing")

# Each source carries its own stamp. They may agree — right after a full
# refresh they all will — so the property worth pinning is that every
# rendered source states its own date, not that the dates disagree. An
# earlier version asserted they differ, and a successful refresh broke it.
dates = {str(s["read_at"])[:10] for s in read if s["read_at"]}
ok(len(dates) >= 1 and all(len(d) == 10 for d in dates),
   f"every rendered source carries its own date {sorted(dates)}")
ok(all(s["read_at"] for s in read),
   "and none is rendered without one")


# ------------------------------------------------------------------ trust
section("Only what can be trusted reaches the page")

# The gate reads flags the extractor already wrote; it invents no judgement.
CLEAN = {"status": "confirmed_match", "extraction_verdict": "accepted",
         "stale": False, "competitor_price": "100", "warnings": []}
ok(pdata.trust(CLEAN)["level"] == "trusted", "a clean reading is trusted")
ok(pdata.trust(dict(CLEAN, warnings=["images missing"]))["level"]
   == "qualified",
   "a warning qualifies rather than disqualifies — a note about images says "
   "nothing about whether the price was read right")
ok(pdata.trust(dict(CLEAN, stale=True))["level"] == "withheld",
   "a stale reading is held back")
ok(pdata.trust(dict(CLEAN, status="no_match"))["level"] == "withheld",
   "so is a status with no counterpart")
ok(pdata.trust(dict(CLEAN, status="ambiguous"))["level"] == "withheld",
   "and an ambiguous one, because naming one candidate would be a guess")
ok(pdata.trust(dict(CLEAN, invalid_reason="page changed"))["level"]
   == "withheld", "and anything invalidated since")
ok(pdata.trust(dict(CLEAN, competitor_price=None))["level"] == "withheld",
   "and a match with no price, since there is no figure to state")
ok(pdata.trust(dict(CLEAN, extraction_verdict=""))["level"] == "withheld",
   "a missing verdict is withheld: how the figures were read is unknown")
ok(pdata.trust(dict(CLEAN, extraction_verdict="rejected"))["level"]
   == "withheld", "and an unaccepted extraction")

for bad in ({"status": "no_match"}, {"stale": True, "status": "blocked"}):
    v = pdata.trust(dict(CLEAN, **bad))
    ok(v["reasons"] and all(r.strip() for r in v["reasons"]),
       f"every withheld reading carries a reason {bad}")
ok(pdata.trust(CLEAN)["reasons"] == [], "and a trusted one carries none")

# The reasons are readable, not codes: this text goes on the page.
r = pdata.trust(dict(CLEAN, status="ambiguous"))["reasons"][0]
ok(len(r.split()) > 6 and "guess" in r,
   "a reason explains itself rather than naming a flag")

section("Nothing is dropped silently")

held = max(PRODUCTS, key=lambda p: pdata.partition(p)["withheld_n"])
v = pdata.build(BUNDLE, held["product_id"])
h = pp_render = ppage.render(v)
t = v["trust"]
ok(t["total"] == len(held.get("matches") or []),
   "the split accounts for every counterpart the product has")
ok(t["trusted_n"] + t["qualified_n"] + t["withheld_n"] == t["total"],
   "and each one lands in exactly one bucket")
# Removed on instruction: the page carries trusted figures and says nothing
# about what it declined. The reasons are still computed and still reachable
# through `product_data.partition`, so a figure can still be audited.
ok("What this page states" not in h,
   "the page does not report what it held back")
ok('class="wrow"' not in h, "and names no withheld counterpart")
ok(all(m["trust"]["reasons"] for m in t["withheld"]),
   "the reasons still exist in the data behind it")

# The gate has to reach the derived figures too, or a stale reading still
# drives a comparison that looks exactly like a good one.
usable_brands = {m["competitor_brand"] for m in t["usable"]}
shown = {r["brand"] for r in v["content"]["rows"]}
ok(shown <= usable_brands,
   "the content table shows only usable counterparts")
priced = {r["brand"] for row in v["markets"]["priced"] for r in row["rows"]}
ok(priced <= usable_brands, "so does the price comparison")
ok(len(re.findall(r'<article class="mblk', h)) == len(t["usable"]),
   "and there is one counterpart block per usable reading, no half-empty ones")

# A product where nothing survives says so, rather than looking quiet.
none_ok = next((p for p in PRODUCTS
                if pdata.partition(p)["total"]
                and not pdata.partition(p)["usable"]), None)
if none_ok:
    hn = ppage.render(pdata.build(BUNDLE, none_ok["product_id"]))
    heads_n = re.findall(r'<div class="sec-h"><h2>([^<]+)</h2>', hn)
    ok("Counterparts" not in heads_n and "Prices by market" not in heads_n,
       f"a product whose every counterpart failed renders neither heading {heads_n}")
    ok("The record" in hn,
       "but its own catalogue record still renders, because that is trusted")
else:
    ok(True, "no fully-withheld product in the catalogue")

# A qualified reading wears its caveat where the figures are.
qual = next((p for p in PRODUCTS
             if pdata.partition(p)["qualified_n"]), None)
if qual:
    hq = ppage.render(pdata.build(BUNDLE, qual["product_id"]))
    ok('class="qflag"' in hq,
       "a caveated counterpart carries the caveat beside its figures")
    ok("Stated with a caveat" in hq, "and says that is what it is")
else:
    ok(True, "no qualified reading in the catalogue")

# Across the catalogue the gate actually bites.
agg = {"trusted": 0, "qualified": 0, "withheld": 0}
for p in PRODUCTS:
    r = pdata.partition(p)
    agg["trusted"] += r["trusted_n"]
    agg["qualified"] += r["qualified_n"]
    agg["withheld"] += r["withheld_n"]
ok(agg["withheld"] > 0,
   f"the gate holds real records back {agg} — a gate that passes everything is "
   f"not a gate")
ok(agg["trusted"] + agg["qualified"] > 0,
   "and passes real ones through, so the pages are not empty")

section("The Arabic version is gone")

for f in ("i18n.py",):
    ok(not (ROOT / "clara_monitor" / f).exists(), f"clara_monitor/{f} deleted")
ok(not (ROOT / "tests" / "test_i18n.py").exists(), "tests/test_i18n.py deleted")
for f in ("serve.py", "clara_monitor/ui.py", "clara_monitor/cards.py",
          "clara_monitor/pages.py", "clara_monitor/product_page.py"):
    src = (ROOT / f).read_text(encoding="utf-8")
    ok("i18n" not in src, f"{f} has no translation call left")
ok("clara_lang" not in (ROOT / "serve.py").read_text(encoding="utf-8"),
   "the language cookie is gone")
ok("/lang" not in (ROOT / "serve.py").read_text(encoding="utf-8"),
   "and so is the route")

# The one thing kept: logical CSS properties. They are better CSS in any
# language and mirror nothing on their own.
ok("margin-inline-start" in (ROOT / "clara_monitor" / "ui.py")
   .read_text(encoding="utf-8"),
   "logical CSS properties are kept — they are correct CSS regardless of "
   "language and produce no Arabic anything")

print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
for f in FAIL:
    print(f"  FAILED  {f}")
sys.exit(1 if FAIL else 0)
