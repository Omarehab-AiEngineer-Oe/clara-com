"""Turning uncategorised signals into subjects, without inventing any.

113 of 219 signals matched none of the 86 hand-written patterns. That is the
vocabulary's blind spot, and it is where the next subject already is — the
articles exist, they were fetched and stored, and nothing in the file knows what
to call them.

The pipeline:

    uncategorised signals
      -> normalise the titles
        -> extract n-grams that look like a subject
          -> cluster by shared phrase
            -> require evidence: signals, publishers, days
              -> generate a pattern
                -> test the pattern against the whole corpus
                  -> check it is not a near-duplicate of something we have
                    -> activate, and reclassify history

**The evidence gate is the whole design.** A cluster needs `min_signals` items
from `min_publishers` distinct publishers seen across `min_days_seen` days. All
three, not any. One publisher writing five times is a publisher with a
preoccupation; five publishers writing once each on the same day is a press
release. Only both together is a trend.

**Pattern testing is what stops a bad subject.** A generated pattern is run
against every stored signal before it is allowed to exist. If it matches more
than a quarter of the corpus it is too broad to mean anything and is rejected —
`\\bhair\\b` would "classify" almost everything and improve the uncategorised
count while destroying the taxonomy.

**Merging beats creating.** A candidate is compared against the existing
vocabulary by token overlap before it can become a subject of its own, so
"hair regrowth" merges into "hair growth and density" rather than sitting beside
it. The comparison is deterministic and the score is recorded, so a merge can be
argued with.

No LLM is required anywhere here. If Vertex is available it could suggest a
nicer label, but the decision to create, merge or reject is arithmetic, which is
what makes it auditable.
"""

from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone

from .. import scope, trend_sources as ts
from .config import ACTIVE, CANDIDATE, MERGED, REJECTED, VALIDATED, DiscoveryConfig

# Words that carry no subject. Deliberately long: a cluster keyed on "best" or
# "new" is a headline convention, not a topic.
STOP = set("""
a an the and or but if then than that this these those of in on at to for from
with without by as is are was were be been being it its it's their there here
how what why when who whom which while into onto over under about after before
you your we our i me my he she they them his her not no yes do does did done
can could will would should may might must have has had more most less least
best worst top new news now next last first second third very much many some
any all every each other another same different such just only also too still
get gets got make makes made take takes look looks looking say says said
know knows need needs want wants use uses using try tries tried
one two three four five six seven eight nine ten
year years month months week weeks day days time times
things thing way ways lot lots kind sort type
according reveals reveal launches launch announces announce says
exclusive interview review guide roundup edit shopping shop buy
""".split())

# A subject in this domain almost always contains one of these. Requiring it
# stops the clusterer keying on "red carpet dress" in a fashion feed.
DOMAIN_WORDS = set("""
beauty cosmetic cosmetics skincare skin haircare hair makeup fragrance perfume
scent nail nails salon serum shampoo conditioner mask cleanser moisturiser
moisturizer sunscreen spf retinol niacinamide peptide ceramide collagen
acne blemish barrier scalp follicle keratin bond repair gloss balayage
blonde brunette curl curls curly coily styling styler dryer straightener
lipstick lip gloss blush bronzer highlighter concealer foundation mascara
brow brows lash lashes liner eyeshadow
oil oils treatment treatments routine ingredient ingredients formula formulas
derm dermatologist clinic clinical injectable filler botox laser led
microbiome probiotic exosome exosomes ferment fermented
grooming wellness supplement supplements ingestible
""".split())

MIN_TERM_LEN = 4


def normalise(text: str) -> list[str]:
    """Title to comparable tokens. Case, punctuation and plurals folded."""
    low = (text or "").lower()
    low = re.sub(r"https?://\S+", " ", low)
    low = re.sub(r"[^a-z0-9؀-ۿ ]+", " ", low)
    words = []
    for w in low.split():
        if len(w) < MIN_TERM_LEN or w in STOP or w.isdigit():
            continue
        if len(w) > 4 and w.endswith("s") and not w.endswith("ss"):
            w = w[:-1]
        words.append(w)
    return words


def phrases(tokens: list[str]) -> list[str]:
    """Unigrams and bigrams that could name a subject.

    A phrase qualifies only if it touches the domain vocabulary — that single
    condition removes almost all of the noise a naive n-gram counter produces.
    """
    out = []
    for w in tokens:
        if w in DOMAIN_WORDS:
            out.append(w)
    for a, b in zip(tokens, tokens[1:]):
        if a in DOMAIN_WORDS or b in DOMAIN_WORDS:
            out.append(f"{a} {b}")
    return out


# The subject gate, and the strictest one in the system. A feed earns its place
# by publishing about the frame sometimes; a *subject* has to be inside the
# frame, because a subject is what the trends page organises itself around and
# what a recommendation is eventually hung on.
#
# This used to test for "beauty" and that was the wrong question. It admitted
# retinol, SPF rulings and gel manicures as competitive subjects — all properly
# about beauty, none of them something Clara sells or can act on. The frame in
# `scope` is the four product families and nothing else, so that is what is
# asked here. Both patterns are kept as names so the older callers and the
# stored rejection reasons still resolve.
OFF_DOMAIN = scope.COLLISION
STRICT_BEAUTY = scope.IN_SCOPE

MIN_BEAUTY_SHARE = scope.MIN_FRAME_SHARE
MIN_FRAME_SHARE = scope.MIN_FRAME_SHARE


def beauty_share(signals: list[dict]) -> float:
    """Share of a cluster whose articles are inside the product frame."""
    return frame_share(signals)


def frame_share(signals: list[dict]) -> float:
    """Share of a cluster whose articles are inside the product frame."""
    if not signals:
        return 0.0
    return scope.frame_share(f"{s.get('title', '')} {s.get('summary', '')}"
                             for s in signals)


def off_domain_reason(phrase: str, signals: list[dict]) -> str:
    """Why this cluster is not a subject inside the frame, or '' if it is one.

    Checked before the evidence gate is even consulted: a cluster about
    semiconductors does not become relevant by being well corroborated, and
    neither does a cluster about mascara.

    The phrase is judged first and on its own terms. A phrase naming an excluded
    category — hair colour, wigs, minoxidil, a salon service — is refused with
    that category named, because "off domain" on its own would leave a reader
    unable to tell a mis-scoped subject from a broken one.
    """
    if scope.COLLISION.search(phrase):
        return (f"'{phrase}' is a known cross-domain collision — the phrase "
                f"belongs to another field and shares a word with beauty")

    verdict = scope.relevance(phrase)
    if verdict["verdict"] == "out_of_scope":
        return f"'{phrase}' is outside the product frame: {verdict['reason']}"

    share = frame_share(signals)
    if share < scope.MIN_FRAME_SHARE:
        return (f"only {share:.0%} of the {len(signals)} clustered article(s) "
                f"are about the four product families "
                f"({scope.MIN_FRAME_SHARE:.0%} needed) — the phrase matched "
                f"inside coverage of something Clara does not sell")
    return ""


def _parse(stamp: str):
    if not stamp:
        return None
    try:
        d = datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def cluster(signals: list[dict], *, cfg: DiscoveryConfig) -> list[dict]:
    """Group uncategorised signals by the phrase they share.

    Bigrams are preferred over unigrams when both qualify: "scalp microbiome" is
    a subject and "scalp" is a category, and the more specific key produces the
    more useful pattern.
    """
    tc = cfg.topics
    by_phrase: dict = defaultdict(list)

    for s in signals:
        blob = f"{s.get('title', '')} {s.get('summary', '')}"
        toks = normalise(blob)
        for ph in set(phrases(toks)):
            by_phrase[ph].append(s)

    # Prefer bigrams: drop a unigram whose signals are already covered by a
    # bigram containing it, so "scalp" does not compete with "scalp microbiome".
    bigrams = {p for p in by_phrase if " " in p}
    covered: set = set()
    for bg in bigrams:
        for s in by_phrase[bg]:
            covered.add(s.get("url"))

    clusters = []
    for phrase, items in by_phrase.items():
        if " " not in phrase:
            remaining = [i for i in items if i.get("url") not in covered]
            if len(remaining) < len(items):
                items = remaining
        if len(items) < tc.min_signals:
            continue
        pubs = {i.get("publisher") for i in items if i.get("publisher")}
        if len(pubs) < tc.min_publishers:
            continue
        days = {(_parse(i.get("published_at") or i.get("first_seen_at")) or
                 datetime.now(timezone.utc)).date() for i in items}
        if len(days) < tc.min_days_seen:
            continue

        dates = [d for d in (_parse(i.get("published_at")) for i in items) if d]
        clusters.append({
            "phrase": phrase,
            "signals": items,
            "signal_count": len(items),
            "publishers": sorted(pubs),
            "publisher_count": len(pubs),
            "days_seen": len(days),
            "first_seen_at": (min(dates).isoformat() if dates else ""),
            "last_seen_at": (max(dates).isoformat() if dates else ""),
        })

    clusters.sort(key=lambda c: (-c["publisher_count"], -c["signal_count"]))
    return clusters


def label_for(phrase: str, cluster_signals: list[dict]) -> str:
    """A human label. The phrase, title-cased, plus the most common co-word."""
    base = phrase.strip()
    counts = Counter()
    for s in cluster_signals:
        for w in normalise(f"{s.get('title', '')}"):
            if w not in base.split():
                counts[w] += 1
    extra = [w for w, n in counts.most_common(6)
             if w in DOMAIN_WORDS and n >= max(2, len(cluster_signals) // 3)]
    label = base.title()
    if extra:
        label = f"{label} ({extra[0]})"
    return label[:70]


def make_pattern(phrase: str, cluster_signals: list[dict]) -> dict:
    """A regex for the phrase plus close variants seen in the cluster itself.

    Aliases are only ever taken from the cluster's own headlines, never invented:
    a pattern that matches wording no publisher used is a pattern that will never
    fire.
    """
    parts = phrase.split()
    if len(parts) == 2:
        a, b = parts
        core = rf"\b{re.escape(a)}\w*\s+{re.escape(b)}\w*\b"
        reversed_ = rf"\b{re.escape(b)}\w*\s+{re.escape(a)}\w*\b"
        pattern = f"{core}|{reversed_}"
        aliases = [phrase, f"{b} {a}"]
    else:
        pattern = rf"\b{re.escape(phrase)}\w*\b"
        aliases = [phrase]

    # Variants actually present in the cluster's headlines.
    seen_alias = set(aliases)
    for s in cluster_signals[:20]:
        title = (s.get("title") or "").lower()
        for m in re.finditer(pattern, title, re.I):
            frag = m.group(0).strip()
            if frag and frag not in seen_alias:
                seen_alias.add(frag)
    return {"pattern": pattern, "aliases": sorted(seen_alias)[:8]}


def test_pattern(pattern: str, all_signals: list[dict], cluster_urls: set,
                 *, cfg: DiscoveryConfig) -> dict:
    """Run a candidate pattern over the whole corpus before trusting it.

    Two failure modes it catches. Too broad: matches a quarter of everything, so
    it is a category word rather than a subject. Too imprecise: most of what it
    matches is not what the cluster was about, so the pattern found a different
    thing than the one that motivated it.
    """
    tc = cfg.topics
    try:
        rx = re.compile(pattern, re.I)
    except re.error as e:
        return {"ok": False, "reason": f"pattern does not compile: {e}",
                "matches": 0, "ratio": 0.0, "precision": 0.0}

    matches = []
    for s in all_signals:
        blob = f"{s.get('title', '')} {s.get('summary', '')}"
        if rx.search(blob):
            matches.append(s)

    total = max(1, len(all_signals))
    ratio = len(matches) / total
    in_cluster = sum(1 for m in matches if m.get("url") in cluster_urls)
    precision = in_cluster / max(1, len(matches))

    if ratio > tc.max_corpus_match_ratio:
        return {"ok": False, "matches": len(matches), "ratio": round(ratio, 3),
                "precision": round(precision, 3),
                "reason": (f"matches {ratio:.0%} of the corpus — too broad to be "
                           f"a subject rather than a category")}
    if precision < tc.min_pattern_precision:
        return {"ok": False, "matches": len(matches), "ratio": round(ratio, 3),
                "precision": round(precision, 3),
                "reason": (f"only {precision:.0%} of matches are the signals that "
                           f"motivated it — the pattern found something else")}
    return {"ok": True, "matches": len(matches), "ratio": round(ratio, 3),
            "precision": round(precision, 3),
            "reason": (f"{len(matches)} match(es), {ratio:.0%} of corpus, "
                       f"{precision:.0%} precision")}


def similarity(a: str, b: str) -> float:
    """Token overlap, for near-duplicate detection. Deterministic on purpose."""
    ta = set(normalise(a))
    tb = set(normalise(b))
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def find_overlap(label: str, phrase: str, *, cfg: DiscoveryConfig) -> dict | None:
    """Does the existing vocabulary already cover this?

    Checked two ways: label similarity, and whether an existing pattern already
    fires on the candidate phrase. The second catches the case where the names
    look different but the regexes do the same job.
    """
    best = None
    for t in ts.TOPICS:
        sim = max(similarity(label, t.label), similarity(phrase, t.label))
        if t.matches(phrase):
            sim = max(sim, 0.75)
        if sim >= cfg.topics.merge_similarity and (not best or sim > best["score"]):
            best = {"key": t.key, "label": t.label, "score": round(sim, 3)}
    return best


def run_topic_discovery(store, trend_store_obj, *, cfg: DiscoveryConfig,
                        run_id: str, verbose: bool = True) -> dict:
    """Cluster, validate, decide, and reclassify history.

    Returns the before/after uncategorised counts, because the only honest test
    of whether this works is whether the blind spot got smaller.
    """
    all_signals = trend_store_obj._all_signals()
    uncat = [s for s in all_signals if not (s.get("topics") or [])]
    before = len(uncat)
    log = []

    def say(msg):
        log.append(msg)
        if verbose:
            print(f"    {msg}", flush=True)

    say(f"{before} of {len(all_signals)} signal(s) uncategorised")

    clusters = cluster(uncat, cfg=cfg)
    say(f"{len(clusters)} cluster(s) meet the evidence gate "
        f"({cfg.topics.min_signals} signals / {cfg.topics.min_publishers} "
        f"publishers / {cfg.topics.min_days_seen} days)")

    stats = {"clusters": len(clusters), "candidates": 0, "activated": 0,
             "merged": 0, "rejected": 0}

    for c in clusters[:cfg.topics.max_new_per_scan * 3]:
        if stats["activated"] >= cfg.topics.max_new_per_scan:
            say(f"stopping: hit max_new_per_scan={cfg.topics.max_new_per_scan}")
            break

        phrase = c["phrase"]
        key = "auto_" + re.sub(r"[^a-z0-9]+", "_", phrase).strip("_")[:40]
        label = label_for(phrase, c["signals"])
        pat = make_pattern(phrase, c["signals"])
        cluster_urls = {s.get("url") for s in c["signals"]}

        cand = {
            "key": key, "label": label, "terms": [phrase] + pat["aliases"],
            "pattern": pat["pattern"], "aliases": pat["aliases"],
            "category": "beauty_culture",
            "signal_count": c["signal_count"],
            "publisher_count": c["publisher_count"],
            "days_seen": c["days_seen"],
            "first_seen_at": c["first_seen_at"],
            "last_seen_at": c["last_seen_at"],
            "evidence": [{"title": s.get("title"), "publisher": s.get("publisher"),
                          "url": s.get("url"),
                          "published_at": s.get("published_at")}
                         for s in c["signals"][:8]],
        }
        store.add_topic_candidate(cand, run_id)
        stats["candidates"] += 1

        # Domain check first. A cluster about semiconductors does not become a
        # beauty subject by being well corroborated, so this runs before the
        # overlap and pattern tests rather than after them.
        off = off_domain_reason(phrase, c["signals"])
        if off:
            store.set_topic_state(key, REJECTED, reason=off, run_id=run_id)
            stats["rejected"] += 1
            say(f"rejected   {phrase[:30]:32} {off[:56]}")
            continue

        overlap = find_overlap(label, phrase, cfg=cfg)
        if overlap:
            store.set_topic_state(
                key, MERGED,
                reason=(f"near-duplicate of the existing subject "
                        f"'{overlap['label']}' (overlap {overlap['score']}) — "
                        f"merged rather than added"),
                merged_into=overlap["key"], run_id=run_id)
            stats["merged"] += 1
            say(f"merged     {phrase[:30]:32} -> {overlap['label'][:28]} "
                f"({overlap['score']})")
            continue

        test = test_pattern(pat["pattern"], all_signals, cluster_urls, cfg=cfg)
        store.topic_event(run_id, key, "pattern_tested", test["reason"], test)
        if not test["ok"]:
            store.set_topic_state(key, REJECTED, reason=test["reason"],
                                  precision=test.get("precision"),
                                  corpus_ratio=test.get("ratio"), run_id=run_id)
            stats["rejected"] += 1
            say(f"rejected   {phrase[:30]:32} {test['reason'][:52]}")
            continue

        store.set_topic_state(key, VALIDATED, reason=test["reason"],
                              precision=test["precision"],
                              corpus_ratio=test["ratio"], run_id=run_id)
        store.set_topic_state(key, ACTIVE,
                              reason=(f"{c['signal_count']} signal(s) from "
                                      f"{c['publisher_count']} publisher(s) over "
                                      f"{c['days_seen']} day(s); {test['reason']}"),
                              run_id=run_id)
        store.add_pattern(key, pat["pattern"], matched=test["matches"])
        stats["activated"] += 1
        say(f"ACTIVATED  {phrase[:30]:32} {c['signal_count']} signals / "
            f"{c['publisher_count']} pubs / {c['days_seen']}d")

    # Reclassify with the widened vocabulary and measure the blind spot.
    retag = trend_store_obj.retag()
    after_signals = trend_store_obj._all_signals()
    after = sum(1 for s in after_signals if not (s.get("topics") or []))
    store.record_classification(
        run_id, before, after, len(after_signals), retag.get("retagged", 0),
        len(store.active_topics()),
        detail=f"{stats['activated']} new subject(s) activated this run")
    say(f"uncategorised {before} -> {after} of {len(after_signals)}")

    store.mark("topic_discovery", run_id)
    return {"stats": stats, "before": before, "after": after,
            "total": len(after_signals), "log": log, "run_id": run_id}
