"""A page per Clara product: prices by market, and the six 6.2 dimensions.

Same design layer as the other pages — `site.CSS` tokens, `ui.SHARED_CSS`
components, the livebar injected above `<header class="top">`.

**Only trusted information reaches this page, and a section with none is not
rendered at all** — no heading, no empty state, no placeholder. A field with no
value is dropped rather than labelled "not published", and a counterpart whose
reading failed the trust gate does not appear.

The consequence is worth naming where the code lives. A page showing three
counterparts instead of five now looks like a market of three, and there is
nothing on the page to say otherwise. The trust reasons are still computed and
still available in `product_data.partition` and in `/status.json`; they are
simply not rendered. Anyone auditing a figure has to go there rather than read
it here.

The six dimensions are shown as OBSERVATION and refused as OUTPUT — the line
section 6.2 draws. The three with no instrument (SEO, social, acquisition) are
not rendered, for the same reason as everything else on this page: no
information, no heading.
"""

from __future__ import annotations

from . import ui
from .ui import e

EXTRA_CSS = """
.ppage{max-width:1180px;margin:0 auto;padding:26px 22px 60px}
.psec{margin-top:30px}

/* the head: image, name, price, family */
.phead{display:grid;grid-template-columns:168px 1fr;gap:20px;
  background:var(--card);border:1px solid var(--line);border-radius:11px;
  padding:18px 20px}
@media (max-width:640px){.phead{grid-template-columns:1fr}}
.phead img{width:100%;border-radius:8px;background:var(--card2)}
.phead .ph-none{width:100%;aspect-ratio:1;border-radius:8px;
  background:var(--card2);border:1px dashed var(--line2);display:flex;
  align-items:center;justify-content:center;font-size:11.5px;color:var(--ink4)}
.phead h1{margin:0 0 6px;font-size:22px;line-height:1.25;letter-spacing:-.02em}
.phead .ph-sub{font-size:12px;color:var(--ink3);display:flex;gap:8px;
  flex-wrap:wrap;align-items:baseline;margin-bottom:12px}
.phead .ph-price{font-size:27px;font-weight:700;letter-spacing:-.02em;
  font-variant-numeric:tabular-nums}
.phead .ph-price span{font-size:13px;font-weight:600;color:var(--ink3)}
.phead .ph-specs{display:flex;flex-wrap:wrap;gap:5px;margin-top:12px}
.phead .ph-specs span{font-size:11px;background:var(--card2);
  border:1px solid var(--line2);border-radius:4px;padding:2px 7px;
  color:var(--ink2)}

/* the record: what the popup used to hold, now on the page */
.kvg{display:grid;grid-template-columns:repeat(auto-fit,minmax(168px,1fr));
  gap:1px;background:var(--line);border:1px solid var(--line);
  border-radius:6px;overflow:hidden;margin-top:14px}
.kvg>div{background:var(--card);padding:10px 12px}
.kvg .k{font-size:9px;letter-spacing:.1em;text-transform:uppercase;
  color:var(--ink3);font-weight:650}
.kvg .v{font-size:13px;margin-top:4px;overflow-wrap:anywhere;line-height:1.5}
.kvg .v .np{color:var(--ink4);font-style:italic}

.mblk{background:var(--card);border:1px solid var(--line);
  border-inline-start:3px solid var(--rival);border-radius:8px;
  padding:15px 17px;margin-top:13px}
.mblk.confirmed_match{border-inline-start-color:var(--ok)}
.mblk.ambiguous{border-inline-start-color:var(--amb)}
.mblk.blocked{border-inline-start-color:var(--bad)}
.mblk.no_match{border-inline-start-color:var(--no)}
.mblk h3{margin:0;font-size:16px;display:flex;gap:9px;align-items:baseline;
  flex-wrap:wrap;letter-spacing:-.01em}
.mblk h3 a{font-size:12.5px;font-weight:500;color:var(--rival)}
.mblk .mnote{font-size:12.5px;color:var(--ink3);line-height:1.6;margin-top:7px;
  background:var(--card2);border-radius:6px;padding:9px 11px}
.mblk .mwarn{font-size:12.5px;color:var(--bad);line-height:1.6;margin-top:7px}

/* the trust split */
.tbar{display:flex;flex-wrap:wrap;gap:8px;margin-top:14px}
.tpill{font-size:11.5px;font-weight:650;border-radius:999px;padding:3px 11px;
  border:1px solid var(--line2);background:var(--card2);color:var(--ink3)}
.tpill.t{background:var(--clara-wash);border-color:var(--clara);
  color:var(--clara)}
.tpill.q{background:var(--card);border-color:var(--amb);color:var(--ink2)}
.tpill.w{border-style:dashed}
.wheld{margin-top:14px;border:1px dashed var(--line2);border-radius:9px;
  background:var(--card2);padding:14px 16px}
.wheld h3{margin:0 0 4px;font-size:14px;font-weight:680}
.wheld .wsub{font-size:12.5px;line-height:1.6;color:var(--ink3);
  margin-bottom:10px}
.wrow{border-top:1px solid var(--line);padding:10px 0 0;margin-top:10px}
.wrow:first-of-type{border-top:0;margin-top:0;padding-top:0}
.wrow b{font-size:13px}
.wrow ul{margin:5px 0 0;padding-inline-start:18px}
.wrow li{font-size:12.5px;line-height:1.6;color:var(--ink2)}
.qflag{font-size:11.5px;line-height:1.6;color:var(--ink3);margin-top:8px;
  border-inline-start:2px solid var(--amb);padding-inline-start:9px}

/* markets */
.mkt{display:grid;grid-template-columns:repeat(auto-fit,minmax(330px,1fr));
  gap:13px;margin-top:14px}
.mkcard{background:var(--card);border:1px solid var(--line);border-radius:10px;
  overflow:hidden}
.mkcard>header{padding:13px 15px;border-bottom:1px solid var(--line);
  display:flex;gap:9px;align-items:baseline;flex-wrap:wrap}
.mkcard .mkc{font-size:16px;font-weight:700;letter-spacing:.01em}
.mkcard .mkn{font-size:11px;font-weight:650;color:var(--ink3);
  background:var(--card2);border:1px solid var(--line2);border-radius:999px;
  padding:1px 8px}
.mkcard .mkwarn{font-size:11px;color:var(--ink3);flex:1 1 100%;line-height:1.5}
.mkrow{padding:11px 15px;border-top:1px solid var(--line);display:flex;
  gap:10px;align-items:baseline;font-size:13px}
.mkrow:first-of-type{border-top:0}
.mkrow .b{font-weight:650;flex:1 1 auto;min-width:0;overflow-wrap:anywhere}
.mkrow .p{font-variant-numeric:tabular-nums;font-weight:700;white-space:nowrap}
.mkrow .d{font-size:11px;color:var(--ink3);white-space:nowrap}
.mkrow.clara{background:var(--clara-wash)}
.mkrow.clara .b{color:var(--clara)}

/* the six dimensions */
.dims{display:grid;gap:13px;margin-top:14px}
.dim{background:var(--card);border:1px solid var(--line);border-radius:10px;
  padding:16px 18px}
.dim.gap{border-style:dashed;background:var(--card2)}
.dim>header{display:flex;gap:9px;align-items:baseline;flex-wrap:wrap;
  margin-bottom:10px}
.dim h3{margin:0;font-size:15.5px;font-weight:680;letter-spacing:-.01em}
.dim .dn{font-size:11px;font-weight:650;color:var(--ink3);
  background:var(--card2);border:1px solid var(--line2);border-radius:999px;
  padding:1px 8px;font-variant-numeric:tabular-nums}
.dim .dstate{font-size:9.5px;font-weight:700;text-transform:uppercase;
  letter-spacing:.05em;border-radius:3px;padding:2px 6px}
.dstate.observed{background:var(--clara-wash);color:var(--clara);
  border:1px solid var(--clara)}
.dstate.none_observed{background:var(--card2);color:var(--ink3);
  border:1px solid var(--line2)}
.dstate.not_collected{background:transparent;color:var(--ink4);
  border:1px dashed var(--line2)}
.dim .dreads{font-size:12.5px;line-height:1.6;color:var(--ink2)}
.dim .drefuse{font-size:12px;line-height:1.6;color:var(--ink3);
  border-inline-start:2px solid var(--line2);padding-inline-start:10px;
  margin-top:10px}
.dim .drefuse b{color:var(--ink2)}
.dbody{margin-top:12px}
.dline{border-top:1px solid var(--line);padding:11px 0;font-size:13px;
  line-height:1.6}
.dline:first-child{border-top:0;padding-top:0}
.dline .dl-b{font-weight:650}
.dline q{color:var(--ink);quotes:"\\201C" "\\201D"}
.dline .dl-m{font-size:11px;color:var(--ink4);margin-top:4px;display:flex;
  gap:4px 10px;flex-wrap:wrap}
.dtable{width:100%;border-collapse:collapse;font-size:12.5px;margin-top:6px}
.dtable th{text-align:start;font-size:10.5px;text-transform:uppercase;
  letter-spacing:.04em;color:var(--ink3);font-weight:650;padding:6px 8px;
  border-bottom:1px solid var(--line)}
.dtable td{padding:8px;border-bottom:1px solid var(--line);
  vertical-align:top}
.dtable td.n{font-variant-numeric:tabular-nums;white-space:nowrap}
.dtable tr.clara td{background:var(--clara-wash);font-weight:650}
.mechs{display:flex;flex-wrap:wrap;gap:4px;margin-top:8px}
.mechs span{font-size:10px;background:var(--card3);color:var(--ink2);
  border-radius:3px;padding:2px 6px}

/* the brief */
.brief{display:grid;gap:11px;margin-top:14px}
.bcard{background:var(--card);border:1px solid var(--line);border-radius:9px;
  padding:14px 16px}
.bcard .bd{font-size:9.5px;font-weight:700;text-transform:uppercase;
  letter-spacing:.05em;color:var(--ink3);margin-bottom:7px}
.bcard .bo{font-size:13.5px;line-height:1.6;color:var(--ink)}
.bcard .bx{font-size:12.5px;line-height:1.6;color:var(--ink2);margin-top:8px;
  background:var(--card2);border-radius:6px;padding:9px 11px}
.bcard .bx b{color:var(--ink)}
.bcard a{font-size:11px;color:var(--rival)}

/* how this product could be improved */
.enh{display:grid;gap:11px;margin-top:14px}
.ecard{background:var(--card);border:1px solid var(--line);border-radius:9px;
  padding:14px 16px;display:grid;grid-template-columns:120px 1fr;gap:14px}
@media (max-width:620px){.ecard{grid-template-columns:1fr;gap:8px}}
.ecard .earea{font-size:9.5px;font-weight:700;text-transform:uppercase;
  letter-spacing:.05em;color:var(--ink3);padding-top:2px}
.ecard .eobs{font-size:12.5px;line-height:1.6;color:var(--ink3)}
.ecard .echange{font-size:14px;line-height:1.5;font-weight:620;color:var(--ink);
  margin-bottom:7px}
.ecard .eval{font-size:12px;line-height:1.6;color:var(--ink2);margin-top:9px;
  background:var(--card2);border-radius:6px;padding:9px 11px}
.ecard .eval b{color:var(--ink)}
.ecard a{font-size:11px;color:var(--rival)}

/* sources and freshness */
.srct{width:100%;border-collapse:collapse;font-size:12.5px;margin-top:14px}
.srct th{text-align:start;font-size:10px;text-transform:uppercase;
  letter-spacing:.05em;color:var(--ink3);font-weight:650;padding:7px 9px;
  border-bottom:1px solid var(--line)}
.srct td{padding:10px 9px;border-bottom:1px solid var(--line);
  vertical-align:top;line-height:1.55}
.srct td.n{font-variant-numeric:tabular-nums;white-space:nowrap}
.srct .s-read{color:var(--ok);font-weight:650}
.srct .s-none{color:var(--ink4)}
.srct .s-blocked{color:var(--bad);font-weight:650}
.srct .snote{font-size:11.5px;color:var(--ink3);margin-top:3px}

/* siblings */
.sibs{display:flex;flex-wrap:wrap;gap:7px;margin-top:12px}
.sibs a{font-size:12px;background:var(--card);border:1px solid var(--line);
  border-radius:6px;padding:6px 10px;text-decoration:none;color:var(--ink2)}
.sibs a:hover{border-color:var(--clara);color:var(--clara)}
"""

STATE_LABEL = {"observed": "observed", "none_observed": "none observed",
               "not_collected": "not collected"}


def render(view: dict) -> str:
    """One product page. `view` comes from `product_data.build`."""
    from .site import CSS

    p = view.get("product")
    P = [f'<title>{e((p or {}).get("name") or "Product")} — Clara</title>',
         '<meta name="viewport" content="width=device-width, initial-scale=1">',
         f'<style>{CSS}{ui.SHARED_CSS}{EXTRA_CSS}</style>']
    P.append(_header(view))
    P.append('<div class="ppage">')

    if not p:
        P.append(ui.nothing(
            "No such product.",
            f"Nothing in the catalogue has the id "
            f"{view.get('product_id') or '(none given)'}. The catalogue is "
            f"built from the last run, so a product added since then will not "
            f"be here yet."))
        P.append('<div class="sibs"><a href="/">Back to all products</a></div>')
        P.append('</div>')
        return "\n".join(P)

    P.append(_head(view))
    P.append(_record(view))
    P.append(_matches(view))
    P.append(_markets(view))
    P.append(_dimensions(view))
    P.append(_brief(view))
    P.append(_enhance(view))
    P.append(_sources(view))
    P.append(_siblings(view))
    P.append('</div>')
    return "\n".join(P)


def _header(view: dict) -> str:
    """The same header shape as the other pages, so the bar sits above it."""
    p = view.get("product") or {}
    P = ['<header class="top"><div class="wrap"><div class="hrow"><div>']
    P.append('<p class="eyebrow">Clara product</p>')
    P.append(f'<h1>{e(p.get("name") or "Not found")}</h1>')
    P.append('</div><div class="hmeta">')
    if view.get("family_label"):
        P.append(f'<span>{e(view["family_label"])}</span>')
    P.append('<span><a href="/">all products</a></span>')
    P.append('</div></div></div></header>')
    return "".join(P)


def _head(view: dict) -> str:
    p = view["product"]
    P = ['<section class="psec"><div class="phead">']
    if p.get("image_url"):
        P.append(f'<div><img src="{e(p["image_url"])}" alt="" '
                 f'loading="lazy"></div>')
    else:
        P.append('<div><div class="ph-none">no image</div></div>')
    P.append('<div>')
    P.append(f'<h1>{e(p["name"])}</h1>')
    P.append('<div class="ph-sub">')
    P.append(f'<span>{e(view.get("family_label"))}</span>')
    P.append(f'<span>&middot; {e(p.get("fmt") or "").replace("_", " ")}</span>')
    if p.get("rating"):
        P.append(f'<span>&middot; {e(p["rating"])} '
                 f'({e(p.get("rating_count") or 0)} reviews)</span>')
    P.append(f'<span>&middot; <a href="{e(p.get("url"))}" '
             f'rel="nofollow noopener">product page</a></span>')
    P.append('</div>')
    if p.get("clara_price"):
        P.append(f'<div class="ph-price">{e(p["clara_price"])} '
                 f'<span>{e(p.get("currency"))}</span></div>')
    else:
        P.append('<div class="ph-price"><span>no price published</span></div>')
    if p.get("specs"):
        P.append('<div class="ph-specs">')
        for k, v in (p["specs"] or {}).items():
            P.append(f'<span>{e(str(k).replace("_", " "))}: {e(v)}</span>')
        P.append('</div>')
    P.append('</div></div></section>')
    return "".join(P)


# Display labels. The stored values are left exactly as they are; only what a
# reader sees is renamed.
STOCK_LABEL = {"in_stock": "in stock", "out_of_stock": "out of stock",
               "preorder": "pre-order", "unknown": "not published",
               "not_published": "not published"}
SPEC_LABEL = {"power_w": "power (W)", "heat_settings": "heat settings",
              "ionic": "ionic", "attachment_count": "attachments",
              "voltage": "voltage", "auto_off_min": "auto shut-off (min)",
              "bldc_motor": "BLDC motor", "cold_shot": "cold shot",
              "temperatures_c": "temperatures (°C)"}
STATUS_LABEL = {"confirmed_match": "confirmed", "probable_match": "probable",
                "ambiguous": "needs a decision", "no_match": "no counterpart",
                "blocked": "site unavailable",
                "invalidated": "no longer valid"}


# The sentinel a missing field returns. `_kv` drops any field carrying it, so
# nothing on the page is a label over a blank.
_EMPTY = "\u0000empty"


def _np(text: str = "not published") -> str:
    return _EMPTY


def _kv(key: str, value: str) -> str:
    """A field and its value, or nothing at all.

    An empty value takes its label with it. A grid of captions over dashes reads
    as a page that failed to load, and it makes a reader hunt for the fields
    that do have something in them.
    """
    if not value or value == _EMPTY:
        return ""
    """A field label and its value. The label is translated, the value is data."""
    return (f'<div><div class="k">{e(key)}</div>'
            f'<div class="v">{value}</div></div>')


def _record(view: dict) -> str:
    """Everything the catalogue holds about this product.

    This was the popup. It is on the page now because a popup that holds half
    the answer, beside a link that holds the other half, makes a reader carry
    the join — and the join is the whole point.

    Absent values render as "not published" rather than as a zero or a blank,
    which is the same rule the store follows: a field the page did not state is
    not a field with the value nothing.
    """
    p = view["product"]
    P = ['<section class="psec">']
    P.append(ui.section_head(
        "The record", "as read from clarahair.com",
        "What the catalogue holds for this product. A field the page does not "
        "state is not listed."))
    P.append('<div class="kvg">')
    P.append(_kv("Clara price",
                 f'{e(p.get("clara_price"))} {e(p.get("currency"))}'
                 if p.get("clara_price") else _np()))
    P.append(_kv("Product id", e(p.get("product_id"))))
    P.append(_kv("Family", e(view.get("family_label"))))
    P.append(_kv("Segment and category",
                 f'{e(p.get("segment"))} &middot; {e(p.get("category"))}'))
    P.append(_kv("Format", e((p.get("fmt") or "").replace("_", " "))
                 if p.get("fmt") else _np()))
    P.append(_kv("Rating",
                 f'{e(p.get("rating"))} from {e(p.get("rating_count") or 0)} '
                 f'review(s)' if p.get("rating") else _np("no reviews")))
    P.append(_kv("Page language",
                 e(p.get("description_lang")) if p.get("description_lang")
                 else _np("not detected")))
    P.append(_kv("Assigned competitors",
                 e(", ".join(p.get("assigned_competitors") or []))
                 if p.get("assigned_competitors")
                 else _np("none assigned")))
    # The usable count, not the raw one. Saying "2 counterparts observed" over a
    # page that shows none — because both failed the trust gate — is the exact
    # inconsistency the gate exists to remove.
    usable_n = len((view.get("trust") or {}).get("usable") or [])
    P.append(_kv("Counterparts observed", str(usable_n) if usable_n else _np()))
    ch = p.get("cheapest_rival")
    P.append(_kv("Cheapest comparable rival",
                 (f'{e(ch.get("brand"))} &middot; {e(ch.get("price"))} '
                  f'{e(ch.get("currency"))}'
                  + (f' ({e(ch["multiple_of_clara"])}&times; Clara)'
                     if ch.get("multiple_of_clara") else ""))
                 if ch else _np("no comparable price")))
    P.append(_kv("On clarahair.com",
                 f'<a href="{e(p.get("url"))}" rel="nofollow noopener">'
                 f'open the product page</a>' if p.get("url") else _np()))
    specs = {k: v for k, v in (p.get("specs") or {}).items()
             if v is not None and v is not False}
    # The join goes through e(), so the separator has to be a character rather
    # than an entity or it arrives on the page spelled out.
    P.append(_kv("Published specifications",
                 e(" · ".join(f"{SPEC_LABEL.get(k, k)}: {v}"
                                   for k, v in specs.items()))
                 if specs else _np("none published")))
    P.append('</div></section>')
    return "".join(P)


def _matches(view: dict) -> str:
    """Every counterpart, with every field recorded for it.

    More than the popup showed. The extraction method, the match score, the
    verdict, the validation stamp and any warning were all held back from the
    browser to keep the embedded payload small; the payload is gone, so there is
    no longer a reason to hide the part of the record that says how much to
    trust the rest of it.
    """
    p = view["product"]
    # Usable only, and nothing at all if none are. The trust reasons still exist
    # in `product_data.partition` for anyone auditing a figure; they are not on
    # the page.
    matches = (view.get("trust") or {}).get("usable") or []
    if not matches:
        return ""
    P = ['<section class="psec">']
    P.append(ui.section_head(
        "Counterparts", f"{len(matches)}",
        "One block per rival product the Agent matched to this one, with the "
        "whole record: what was read, how it was read, and how far it can be "
        "trusted."))


    for m in matches:
        P.append(f'<article class="mblk {e(m.get("status"))}">')
        P.append('<h3>')
        P.append(e(m.get("competitor_brand")))
        P.append(ui.badge("low", STATUS_LABEL.get(m.get("status"),
                                                 m.get("status") or "")))
        if m.get("competitor_url"):
            P.append(f'<a href="{e(m["competitor_url"])}" '
                     f'rel="nofollow noopener">'
                     f'{e(m.get("competitor_product_name") or "open page")}'
                     f'</a>')
        P.append('</h3>')

        if m.get("trust", {}).get("level") == "qualified":
            P.append('<div class="qflag"><b>Stated with a caveat.</b> '
                     + e("; ".join(m["trust"]["reasons"])) + '</div>')

        if m.get("separately_available") is False:
            P.append('<div class="mnote">This item is part of a full system and '
                     'is not sold separately, so the price shown is for the '
                     'whole system.</div>')

        P.append('<div class="kvg">')
        if m.get("price_is_range"):
            P.append(_kv("Price range",
                         f'{e(m.get("price_min"))} &ndash; '
                         f'{e(m.get("price_max"))} '
                         f'{e(m.get("competitor_currency"))}'))
        else:
            P.append(_kv("Price",
                         f'{e(m.get("competitor_price"))} '
                         f'{e(m.get("competitor_currency"))}'
                         if m.get("competitor_price") else _np()))
        if m.get("price_from"):
            P.append(_kv("Price basis", 'stated as "from" — the page gives a '
                                        'starting price, not the price'))
        P.append(_kv("Price before discount",
                     e(m["regular_price"]) if m.get("regular_price")
                     else _np("not stated")))
        P.append(_kv("Discount",
                     f'{e(m["discount_percent"])}%' if m.get("discount_percent")
                     else _np("none stated")))
        if m.get("same_currency"):
            delta = m.get("delta_pct_vs_clara")
            if delta:
                direction = ("higher by " if float(delta) > 0 else "lower by ")
                P.append(_kv("Versus Clara",
                             f'{e(direction)}{e(str(delta).lstrip("-"))}%'
                             + (f' &middot; {e(m["multiple_of_clara"])}&times;'
                                if m.get("multiple_of_clara") else "")))
            else:
                P.append(_kv("Versus Clara", _np("not computed")))
        else:
            P.append(_kv("Versus Clara",
                         _np("different currency — not converted")))
        # `not_published` and `unknown` are real readings — the page states no
        # stock — but they are readings of an absence, so the field goes rather
        # than sitting there as a label over nothing.
        stock = m.get("availability")
        P.append(_kv("Availability",
                     e(STOCK_LABEL.get(stock, stock))
                     if stock and stock not in ("not_published", "unknown")
                     else _np()))
        P.append(_kv("Current offer",
                     e(m["promotion_text"]) if (m.get("promotion_text") or "").strip()
                     else _np("none on the page")))
        P.append(_kv("Options available",
                     str(m["variant_count"]) if m.get("variant_count")
                     else _np("not stated")))
        P.append(_kv("Images on the page",
                     str(m["image_count"]) if m.get("image_count")
                     else _np("not counted")))
        P.append(_kv("Comparison basis",
                     e((m.get("comparison_basis") or "").replace("_", " "))
                     if m.get("comparison_basis") else _np()))
        P.append(_kv("Match score",
                     e(m["match_score"]) if m.get("match_score") is not None
                     else _np()))
        P.append(_kv("How it was read",
                     e((m.get("method") or "").replace("_", " "))
                     if m.get("method") else _np()))
        P.append(_kv("Extraction verdict",
                     e(m.get("extraction_verdict")) if m.get("extraction_verdict")
                     else _np()))
        P.append(_kv("Last seen",
                     e(str(m.get("observed_at") or "")[:10])
                     + (" &middot; stale reading" if m.get("stale") else "")
                     if m.get("observed_at") else _np()))
        P.append(_kv("Validated",
                     e(str(m.get("validated_at") or "")[:10])
                     if m.get("validated_at") else _np("not validated")))
        P.append('</div>')

        if m.get("invalid_reason"):
            P.append(f'<div class="mwarn"><b>Invalidated:</b> '
                     f'{e(m["invalid_reason"])}</div>')
        for w in m.get("warnings") or []:
            P.append(f'<div class="mwarn">{e(w)}</div>')
        P.append('</article>')
    P.append('</section>')
    return "".join(P)


def _markets(view: dict) -> str:
    """Prices grouped by the currency the rival storefront quotes in.

    A currency is not a country, and the heading says so rather than letting a
    column of USD prices read as "the American market". Clara's price is only
    placed in the column that quotes the same currency: putting it anywhere else
    would need a conversion, and a converted comparison is the one thing this
    system has refused from the start.
    """
    mk = view["markets"]
    priced = mk.get("priced") or []
    unpriced = mk.get("unpriced") or []

    if not priced:
        return ""
    P = ['<section class="psec">']
    P.append(ui.section_head(
        "Prices by market",
        f"{len(priced)} currency/currencies observed",
        "Grouped by the currency each storefront quotes in — a currency is not "
        "a country, and nothing here is converted. Clara's price appears only "
        "in the column that quotes the same currency, because a comparison "
        "across currencies would need a rate this system does not apply."))

    P.append('<div class="mkt">')
    for row in priced:
        P.append('<div class="mkcard"><header>')
        P.append(f'<span class="mkc">{e(row["currency"])}</span>')
        P.append(f'<span class="mkn">{row["n"]}</span>')
        if not row["comparable"]:
            P.append('<span class="mkwarn">Clara does not publish in this '
                     'currency, so these are shown as read and not compared '
                     'with Clara\'s price.</span>')
        P.append('</header>')
        if row.get("clara_price"):
            P.append('<div class="mkrow clara">'
                     '<span class="b">Clara</span>'
                     f'<span class="p">{e(row["clara_price"])}</span>'
                     '<span class="d">published</span></div>')
        for r in row["rows"]:
            P.append('<div class="mkrow">')
            P.append(f'<span class="b">{e(r["brand"])}')
            if r.get("multiple_of_clara"):
                P.append(f' <span class="d">&times;{e(r["multiple_of_clara"])} '
                         f'Clara</span>')
            P.append('</span>')
            P.append(f'<span class="p">{e(r["price"])}</span>')
            bits = []
            if r.get("availability"):
                bits.append(str(r["availability"]).replace("_", " "))
            if r.get("stale"):
                bits.append("stale reading")
            P.append(f'<span class="d">{e(" &middot; ".join(bits))}</span>'
                     if bits else '<span class="d"></span>')
            P.append('</div>')
        P.append('</div>')
    P.append('</div>')

    P.append('</section>')
    return "".join(P)


def _dimensions(view: dict) -> str:
    """The six, each with what was read, what is refused, and the evidence."""
    # Only the dimensions that have something. The three with no instrument
    # (SEO, social, acquisition) are not rendered.
    live = [d for d in view["dimensions"] if d["state"] == "observed"]
    if not live:
        return ""
    P = ['<section class="psec">']
    P.append(ui.section_head(
        "What competitors do, as observed",
        # Plain text, not entities: section_head escapes what it is given, so an
        # &middot; here reaches the page as the literal characters.
        " · ".join(d["label"].lower() for d in live),
        "Section 6.2 removes these from this system as OUTPUT and leaves them "
        "in as EVIDENCE. The line is the verb: reading a rival's promotion off "
        "their page and recording its wording is evidence; proposing one is "
        "not. Each block below states what it refuses to produce."))
    P.append('<div class="dims">')
    for d in live:
        P.append('<article class="dim"><header>')
        P.append(f'<h3>{e(d["label"])}</h3>')
        P.append(f'<span class="dstate {e(d["state"])}">'
                 f'{e(STATE_LABEL.get(d["state"], d["state"]))}</span>')
        if d["count"]:
            P.append(f'<span class="dn">{d["count"]}</span>')
        P.append('</header>')

        P.append(f'<div class="dreads"><b>Read from:</b> {e(d["reads"])}</div>')
        P.append('<div class="dbody">')
        P.append(_dimension_body(view, d["key"]))
        P.append('</div>')
        P.append(f'<div class="drefuse"><b>Refused as output:</b> '
                 f'{e(d["refuses"])}</div>')
        P.append('</article>')
    P.append('</div></section>')
    return "".join(P)


def _dimension_body(view: dict, key: str) -> str:
    if key == "campaigns":
        rows = view["campaigns"]
        if not rows:
            return ('<div class="dline"><span class="dl-b">No promotion '
                    'wording was on any assigned rival page for this product '
                    'when it was last read.</span> That is a reading, not an '
                    'absence of activity: a campaign running anywhere other '
                    'than the product page is invisible here.</div>')
        P = []
        for r in rows:
            P.append('<div class="dline">')
            P.append(f'<span class="dl-b">{e(r["brand"])}</span> '
                     f'<q>{e(r["wording"])}</q>')
            bits = [f'read {e(str(r.get("observed_at") or "")[:10])}']
            if r.get("discount_percent"):
                bits.append(f'{e(r["discount_percent"])}% off stated')
            if r.get("regular_price") and r.get("price") \
                    and str(r["regular_price"]) != str(r["price"]):
                bits.append(f'was {e(r["regular_price"])}, now {e(r["price"])} '
                            f'{e(r.get("currency") or "")}')
            P.append(f'<div class="dl-m">{" &middot; ".join(bits)}'
                     + (f' &middot; <a href="{e(r["url"])}" '
                        f'rel="nofollow noopener">page</a>' if r.get("url")
                        else "")
                     + '</div>')
            P.append('</div>')
        return "".join(P)

    if key == "advertising":
        st = view["storefront"]
        if not st["rows"]:
            return ('<div class="dline">No storefront for an assigned brand '
                    'answered the last sweep, so there is no advertising '
                    'evidence for this product\'s rivals. A refusal is a '
                    'result and is not retried into a blank.</div>')
        P = [f'<div class="dline"><span class="dl-b">Storefront-wide, not '
             f'product-level.</span> These are read from the brand\'s front '
             f'page, so they say what the brand is promoting at all — never '
             f'what it is promoting on this product.</div>']
        if st["mechanisms"]:
            P.append('<div class="mechs">')
            for m, n in st["mechanisms"]:
                P.append(f'<span>{e(m.replace("_", " "))} &times;{n}</span>')
            P.append('</div>')
        for r in st["rows"]:
            P.append('<div class="dline">')
            P.append(f'<span class="dl-b">{e(r["brand"])}</span> '
                     f'<span class="dl-m">{len(r["offers"])} line(s)</span>')
            for o in r["offers"][:2]:
                P.append(f'<div class="dl-m"><q>'
                         f'{e((o.get("wording") or "")[:150])}</q></div>')
            P.append('</div>')
        return "".join(P)

    # content
    c = view["content"]
    if not c["rows"]:
        return ('<div class="dline">No rival page was read for this product, '
                'so there is nothing to compare its copy against.</div>')
    P = ['<table class="dtable"><thead><tr>'
         f'<th>{e("Page")}</th>'
         f'<th>{e("Name as published")}</th>'
         f'<th>{e("Words")}</th>'
         f'<th>{e("Images")}</th>'
         f'<th>{e("Variants")}</th></tr></thead><tbody>']
    cl = c["clara"]
    P.append('<tr class="clara"><td>Clara</td>'
             f'<td>{e(cl["name"])}</td>'
             f'<td class="n">{cl["name_words"]}</td>'
             f'<td class="n">{cl["images"]}*</td>'
             f'<td class="n">&mdash;</td></tr>')
    for r in c["rows"]:
        P.append('<tr>')
        P.append(f'<td>{e(r["brand"])}</td>')
        P.append(f'<td>{e(r["published_name"])}</td>')
        P.append(f'<td class="n">{r["name_words"]}</td>')
        P.append(f'<td class="n">{e(r["images"]) if r["images"] else "&mdash;"}'
                 f'</td>')
        P.append(f'<td class="n">'
                 f'{e(r["variants"]) if r["variants"] else "&mdash;"}</td>')
        P.append('</tr>')
    P.append('</tbody></table>')
    P.append(f'<div class="dl-m">* {e(cl["images_note"])}. Clara\'s page has '
             f'not been read: both website-analysis runs were stopped by a '
             f'CAPTCHA on clarahair.com, so no score is given here and none '
             f'is implied.</div>')
    return "".join(P)


def _brief(view: dict) -> str:
    """The answer to "what is the best content" — as a brief, not as content."""
    rows = view["brief"]
    if not rows:
        return ""
    P = ['<section class="psec">']
    P.append(ui.section_head(
        "What a person has to decide",
        f"{len(rows)} line(s), each from observed evidence",
        "This is where a request for “the best content” lands. "
        "Section 6.2 removes copywriting and content generation from this "
        "system, so what it produces is the observation and the decision that "
        "follows from it — never the sentence. Every line below names the "
        "evidence it came from, and a line with no evidence is not here."))
    P.append('<div class="brief">')
    for r in rows:
        P.append('<div class="bcard">')
        P.append(f'<div class="bd">{e(r["dimension"])}</div>')
        P.append(f'<div class="bo">{e(r["observed"])}</div>')
        P.append(f'<div class="bx"><b>The decision:</b> {e(r["decision"])}'
                 '</div>')
        if r.get("evidence", "").startswith("http"):
            P.append(f'<a href="{e(r["evidence"])}" rel="nofollow noopener">'
                     f'evidence</a>')
        elif r.get("evidence"):
            P.append(f'<div class="dl-m">from {e(r["evidence"])}</div>')
        P.append('</div>')
    P.append('</div></section>')
    return "".join(P)


def _enhance(view: dict) -> str:
    """How this product could be improved, each line from observed data.

    Not a campaign and not a sentence of copy — 6.2 removes both. The difference
    is that a spec the catalogue does not publish is a measurable fact and
    publishing it is a data action, while the paragraph describing the product is
    a person's to write. Every row carries a way to tell whether the change
    worked, because a suggestion with no check on it is a wish.
    """
    rows = view.get("enhancements") or []
    if not rows:
        return ""
    P = ['<section class="psec">']
    P.append(ui.section_head(
        "How this product could be improved",
        f"{len(rows)} opportunity/opportunities",
        "Each row is arithmetic on what was observed, ordered by how much "
        "evidence stands behind it. None of them is copy or a campaign: what is "
        "proposed is a change to the product, its data or its coverage, and how "
        "to tell afterwards whether it worked."))
    P.append('<div class="enh">')
    for r in rows:
        P.append('<div class="ecard">')
        P.append(f'<div class="earea">{e(r["area"])}</div>')
        P.append('<div>')
        P.append(f'<div class="echange">{e(r["change"])}</div>')
        P.append(f'<div class="eobs">{e(r["observed"])}</div>')
        P.append(f'<div class="eval"><b>How to tell it worked:</b> '
                 f'{e(r["validate"])}</div>')
        if str(r.get("evidence", "")).startswith("http"):
            P.append(f'<a href="{e(r["evidence"])}" rel="nofollow noopener">'
                     f'evidence</a>')
        elif r.get("evidence"):
            P.append(f'<div class="eobs" style="margin-top:6px">from '
                     f'{e(r["evidence"])}</div>')
        P.append('</div></div>')
    P.append('</div></section>')
    return "".join(P)


def _sources(view: dict) -> str:
    """Every source behind this page, with its own age.

    Six sources of different ages under one date at the top of a page is how a
    three-day-old price gets read as current. Each row carries its own stamp,
    how much came back, and — where it matters — why the number beside it is
    smaller than a reader might expect. "Read and empty" and "never read" are
    different rows here, because they lead to opposite actions.
    """
    # Only sources that returned something. A row saying a source was never
    # read is information about a gap, and this page carries none.
    rows = [r for r in (view.get("sources") or [])
            if r["state"] == "read" and r["read_at"]]
    if not rows:
        return ""
    fresh = rows
    P = ['<section class="psec">']
    P.append(ui.section_head(
        "Sources and freshness",
        f"{len(rows)} source(s)",
        "What was read to build this page, and when. Every figure above comes "
        "from one of these rows, and each has its own age — a single date at the "
        "top of a page is how a stale reading gets used as a current one."))
    P.append('<table class="srct"><thead><tr>'
             f'<th>{e("Source")}</th>'
             f'<th>{e("What it covers")}</th>'
             f'<th>{e("Rows")}</th>'
             f'<th>{e("Last read")}</th>'
             f'<th>{e("State")}</th></tr></thead><tbody>')
    for r in rows:
        cls = ("s-read" if r["state"] == "read"
               else "s-blocked" if r["state"] == "blocked" else "s-none")
        P.append('<tr>')
        P.append(f'<td><b>{e(r["source"])}</b></td>')
        P.append(f'<td>{e(r["covers"])}'
                 + (f'<div class="snote">{e(r["note"])}</div>'
                    if r.get("note") else "")
                 + '</td>')
        P.append(f'<td class="n">{r["n"]}</td>')
        P.append(f'<td class="n">{e(str(r["read_at"])[:10])}</td>')
        P.append(f'<td class="n"><span class="{cls}">'
                 f'{e(r["state"])}</span></td>')
        P.append('</tr>')
    P.append('</tbody></table>')
    return "".join(P) + '</section>'


def _siblings(view: dict) -> str:
    sibs = view.get("neighbours") or []
    if not sibs:
        return ""
    P = ['<section class="psec">']
    P.append(ui.section_head(
        "Others in this family", f"{len(sibs)}",
        "Same product family, so the same competitor set and the same "
        "comparison applies."))
    P.append('<div class="sibs">')
    for s in sibs:
        P.append(f'<a href="/product?id={e(s["product_id"])}">'
                 f'{e(s["name"])}</a>')
    P.append('</div>')
    P.append('<div class="sibs" style="margin-top:14px">'
             '<a href="/">&larr; all products and prices</a></div>')
    P.append('</section>')
    return "".join(P)
