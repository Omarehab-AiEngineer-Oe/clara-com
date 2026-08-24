"""Match lifecycle: fingerprint, refresh, revalidate, discover, score, classify.

The order enforced here is the order in section 4 of the instruction. There is
no code path that reaches discovery without first failing the stored-match
validity test, which is what keeps discovery the exceptional case.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Protocol

from .access import guarded_get
from .config import DATA_DIR, RunConfig
from .models import (
    AMBIGUOUS, ATTACHMENT_OF_SYSTEM, BLOCKED, CONFIRMED, NO_MATCH, PROBABLE,
    STANDALONE, Candidate, ClaraProduct, Match,
)
from .observe import host_of, page_signals
from .store import utcnow

CANDIDATE_SEEDS = DATA_DIR / "candidate_seeds.json"

_STOP = {
    "the", "and", "with", "for", "hair", "styling", "styler", "system", "set",
    "professional", "smart", "new", "edition", "limited", "official",
}


# --------------------------------------------------------------------------
# fingerprinting
# --------------------------------------------------------------------------

def _tokens(s: str) -> set[str]:
    toks = re.findall(r"[a-z0-9]+", (s or "").lower())
    return {t for t in toks if t not in _STOP and len(t) > 1}


def fingerprint(brand: str, product_name: str) -> str:
    """Identity signature of a competitor product page."""
    toks = sorted(_tokens(brand) | _tokens(product_name))
    return "|".join(toks[:12])


def fingerprint_drift(stored: str | None, current: str) -> float:
    """0.0 = identical, 1.0 = nothing in common."""
    if not stored:
        return 1.0
    a, b = set(stored.split("|")), set(current.split("|"))
    if not a or not b:
        return 1.0
    return 1.0 - len(a & b) / len(a | b)


DRIFT_TOLERANCE = 0.55


# --------------------------------------------------------------------------
# candidate discovery
# --------------------------------------------------------------------------

class SearchProvider(Protocol):
    """Discovery hook.

    In production this is backed by the agent's Google Search tool, restricted
    to the competitor's own domains. `SeedSearchProvider` below is the offline
    equivalent so a run is reproducible without a live search call.
    """

    def candidates(self, product: ClaraProduct, competitor_key: str,
                   allowed_domains: list[str], budget: int) -> list[str]: ...


class SeedSearchProvider:
    def __init__(self, path: Path = CANDIDATE_SEEDS):
        self.map: dict = {}
        if path.exists():
            self.map = json.loads(path.read_text(encoding="utf-8"))

    def candidates(self, product: ClaraProduct, competitor_key: str,
                   allowed_domains: list[str], budget: int) -> list[str]:
        by_product = self.map.get(product.product_id, {})
        urls = by_product.get(competitor_key, [])
        if not urls:
            urls = self.map.get("_by_format", {}).get(product.fmt, {}).get(competitor_key, [])
        return list(urls)[:budget]


class CallableSearchProvider:
    """Wraps any callable(query, domains, budget) -> list[url], e.g. the LLM's
    search tool. Queries are built from the Clara product's own attributes."""

    def __init__(self, fn: Callable[[str, list[str], int], list[str]]):
        self.fn = fn

    def build_queries(self, product: ClaraProduct, competitor_key: str) -> list[str]:
        fmt = product.fmt.replace("_", " ")
        specs = product.specs or {}
        qs = [f"{competitor_key} {fmt}"]
        if specs.get("attachment_count"):
            qs.append(f"{competitor_key} {fmt} {specs['attachment_count']} attachments")
        if specs.get("power_w"):
            qs.append(f"{competitor_key} {fmt} {specs['power_w']}W")
        qs.append(f"{competitor_key} {fmt} Saudi Arabia price")
        return qs

    def candidates(self, product: ClaraProduct, competitor_key: str,
                   allowed_domains: list[str], budget: int) -> list[str]:
        found: list[str] = []
        for q in self.build_queries(product, competitor_key):
            if len(found) >= budget:
                break
            for u in self.fn(q, allowed_domains, budget - len(found)):
                if u not in found:
                    found.append(u)
        return found[:budget]


# --------------------------------------------------------------------------
# scoring
# --------------------------------------------------------------------------

# Formats that legitimately correspond, with the basis that must be recorded.
FORMAT_EQUIVALENCE = {
    ("multi_styler", "multi_styler"): (1.00, STANDALONE),
    ("dryer", "dryer"): (1.00, STANDALONE),
    ("air_brush", "air_brush"): (1.00, STANDALONE),
    ("hot_brush", "hot_brush"): (1.00, STANDALONE),
    ("auto_curler", "auto_curler"): (1.00, STANDALONE),
    ("straightener", "straightener"): (1.00, STANDALONE),
    ("straightener_brush", "straightener_brush"): (1.00, STANDALONE),
    # A Clara standalone device against one attachment of a modular system.
    ("air_brush", "multi_styler"): (0.80, ATTACHMENT_OF_SYSTEM),
    ("auto_curler", "multi_styler"): (0.80, ATTACHMENT_OF_SYSTEM),
    ("hot_brush", "multi_styler"): (0.80, ATTACHMENT_OF_SYSTEM),
    ("straightener_brush", "straightener"): (0.85, STANDALONE),
    ("straightener", "straightener_brush"): (0.85, STANDALONE),
    ("dryer", "multi_styler"): (0.75, ATTACHMENT_OF_SYSTEM),
    ("hot_brush", "air_brush"): (0.85, STANDALONE),
    ("air_brush", "hot_brush"): (0.85, STANDALONE),
}

SPEC_KEYS = ("power_w", "heat_settings", "ionic", "attachment_count", "voltage")


def _spec_overlap(a: dict, b: dict) -> tuple[float, list[str]]:
    """Agreement across specs both sides publish. Specs only one side
    publishes neither help nor hurt — they are reported as gaps instead."""
    notes, agree, compared = [], 0.0, 0
    for k in SPEC_KEYS:
        av, bv = a.get(k), b.get(k)
        if av is None or bv is None:
            continue
        compared += 1
        if isinstance(av, bool) or isinstance(bv, bool):
            if bool(av) == bool(bv):
                agree += 1
                notes.append(f"{k}: both {av}")
            else:
                notes.append(f"{k}: Clara {av} vs competitor {bv}")
            continue
        if isinstance(av, (int, float)) and isinstance(bv, (int, float)):
            hi = max(abs(av), abs(bv)) or 1
            ratio = 1.0 - abs(av - bv) / hi
            agree += max(0.0, ratio)
            notes.append(f"{k}: Clara {av} vs competitor {bv}")
            continue
        if str(av).lower() == str(bv).lower():
            agree += 1
            notes.append(f"{k}: both {av}")
        else:
            notes.append(f"{k}: Clara {av} vs competitor {bv}")
    if compared == 0:
        return 0.5, ["no specification published by both sides; spec score neutral"]
    return agree / compared, notes


def _price_plausibility(clara_price: float | None, comp_price: float | None) -> float:
    """A competitor at 30x Clara's price is unlikely to be the same product
    class. This is a weak signal by design: price is never evidence of a
    match, only of implausibility."""
    if not clara_price or not comp_price:
        return 0.5
    r = comp_price / clara_price
    if r <= 0:
        return 0.5
    if 0.25 <= r <= 8.0:
        return 1.0
    if r <= 15.0:
        return 0.5
    return 0.0


def score_candidate(product: ClaraProduct, cand: Candidate,
                    comp_price: float | None = None) -> Candidate:
    key = (product.fmt, cand.fmt)
    if key not in FORMAT_EQUIVALENCE:
        cand.disqualified = True
        cand.disqualified_reason = (
            f"format mismatch: Clara is {product.fmt}, candidate is {cand.fmt}"
        )
        cand.score = 0.0
        cand.evidence.append(cand.disqualified_reason)
        return cand

    fmt_score, basis = FORMAT_EQUIVALENCE[key]
    spec_score, spec_notes = _spec_overlap(product.specs, cand.specs)
    name_signal = 1.0 if cand.product_name and cand.product_name != "not_published" else 0.4
    price_score = _price_plausibility(product.price, comp_price)

    cand.score_breakdown = {
        "format": round(fmt_score, 3),
        "specs": round(spec_score, 3),
        "name": round(name_signal, 3),
        "price_plausibility": round(price_score, 3),
    }
    cand.score = round(
        0.45 * fmt_score + 0.30 * spec_score + 0.15 * name_signal + 0.10 * price_score, 3
    )
    cand.evidence.append(f"format basis: {basis} ({product.fmt} vs {cand.fmt})")
    cand.evidence.extend(spec_notes)
    cand.evidence.append(f"score {cand.score} = " + ", ".join(
        f"{k} {v}" for k, v in cand.score_breakdown.items()))
    return cand


def comparison_basis_for(product: ClaraProduct, cand: Candidate) -> str:
    return FORMAT_EQUIVALENCE.get((product.fmt, cand.fmt), (0.0, STANDALONE))[1]


# --------------------------------------------------------------------------
# classification
# --------------------------------------------------------------------------

@dataclass
class Decision:
    status: str
    score: float
    winner: Candidate | None
    rejected: list[Candidate]
    evidence: list[str]


def classify(product: ClaraProduct, candidates: list[Candidate],
             cfg: RunConfig) -> Decision:
    live = [c for c in candidates if not c.disqualified]
    rejected = [c for c in candidates if c.disqualified]
    ev: list[str] = []

    if not live:
        ev.append(
            f"{len(candidates)} candidate(s) read; none passed the format test"
            if candidates else "discovery returned no candidate pages"
        )
        return Decision(NO_MATCH, 0.0, None, rejected, ev)

    live.sort(key=lambda c: c.score, reverse=True)
    best = live[0]
    runner = live[1] if len(live) > 1 else None

    if runner and (best.score - runner.score) < cfg.ambiguity_margin:
        ev.append(
            f"top two candidates cannot be separated: "
            f"{best.product_name} ({best.score}) vs {runner.product_name} "
            f"({runner.score}), margin {round(best.score - runner.score, 3)} "
            f"< {cfg.ambiguity_margin}"
        )
        return Decision(AMBIGUOUS, best.score, best, live[1:] + rejected, ev)

    if best.source_type == "marketplace_third_party" and best.score < cfg.confirm_threshold:
        ev.append("only third-party evidence available and score below confirm threshold")
        return Decision(AMBIGUOUS, best.score, best, live[1:] + rejected, ev)

    if best.score >= cfg.confirm_threshold:
        # confirmed_match requires format agreement. Where a Clara device
        # corresponds to one attachment inside a competitor's modular system the
        # formats do not fully agree, however well the specs line up, so that
        # basis is capped at probable_match rather than promoted on score alone.
        if comparison_basis_for(product, best) == ATTACHMENT_OF_SYSTEM:
            ev.append(
                f"score {best.score} would meet the confirm threshold, but "
                f"comparison_basis is attachment_of_system: the competitor item is "
                f"part of a larger system and is not sold separately, so formats do "
                f"not fully agree; capped at probable_match"
            )
            return Decision(PROBABLE, best.score, best, live[1:] + rejected, ev)
        ev.append(f"score {best.score} >= confirm threshold {cfg.confirm_threshold}")
        return Decision(CONFIRMED, best.score, best, live[1:] + rejected, ev)

    if best.score >= cfg.probable_threshold:
        ev.append(
            f"score {best.score} between {cfg.probable_threshold} and "
            f"{cfg.confirm_threshold}; specification evidence incomplete"
        )
        return Decision(PROBABLE, best.score, best, live[1:] + rejected, ev)

    ev.append(f"best score {best.score} below probable threshold {cfg.probable_threshold}")
    return Decision(NO_MATCH, best.score, None, live + rejected, ev)


# --------------------------------------------------------------------------
# refresh
# --------------------------------------------------------------------------

@dataclass
class RefreshResult:
    ok: bool
    blocked: bool = False
    block_signal: str | None = None
    html: str | None = None
    signals: dict | None = None
    invalid_reason: str | None = None
    evidence: list[str] = None  # type: ignore[assignment]

    def __post_init__(self):
        if self.evidence is None:
            self.evidence = []


def refresh_match(match: Match, cfg: RunConfig) -> RefreshResult:
    """Re-read the stored URL and confirm it is still the same product.

    This does not re-decide the match. It either confirms the stored decision
    still holds, or reports why it no longer does.
    """
    res = guarded_get(match.competitor_url or "", cfg.allowed_hosts())

    if res.blocked:
        return RefreshResult(ok=False, blocked=True, block_signal=res.block_signal,
                             evidence=res.evidence)

    if res.status in (404, 410):
        return RefreshResult(ok=False, invalid_reason=f"competitor_url returns HTTP {res.status}",
                             evidence=res.evidence)

    if not res.ok or not res.html:
        return RefreshResult(ok=False, invalid_reason=f"page unreadable (HTTP {res.status})",
                             evidence=res.evidence)

    sig = page_signals(res.html)

    if sig["is_listing_page"]:
        return RefreshResult(ok=False, invalid_reason="stored URL now resolves to a "
                             "category or search page, not a product page",
                             evidence=res.evidence)

    current_fp = fingerprint(sig["brand"] or match.competitor_brand, sig["name"])
    drift = fingerprint_drift(match.fingerprint, current_fp)
    if drift > DRIFT_TOLERANCE:
        return RefreshResult(
            ok=False,
            invalid_reason=(
                f"identity fingerprint drifted {round(drift, 2)} > {DRIFT_TOLERANCE}: "
                f"stored {match.competitor_product_name!r}, page now {sig['name']!r}"
            ),
            evidence=res.evidence,
        )

    stored_brand = _tokens(match.competitor_brand)
    page_brand = _tokens(sig["brand"] or "") | _tokens(sig["name"])
    if stored_brand and page_brand and not (stored_brand & page_brand):
        return RefreshResult(ok=False,
                             invalid_reason=f"page brand {sig['brand']!r} does not match "
                                            f"stored brand {match.competitor_brand!r}",
                             evidence=res.evidence)

    return RefreshResult(ok=True, html=res.html, signals=sig,
                         evidence=res.evidence + [
                             f"fingerprint drift {round(drift, 2)} within tolerance"])


# --------------------------------------------------------------------------
# discovery
# --------------------------------------------------------------------------

def discover(product: ClaraProduct, competitor_key: str, cfg: RunConfig,
             provider: SearchProvider) -> tuple[list[Candidate], list[dict], list[str]]:
    """Read candidate pages for one pair. Returns (candidates, blocks, log)."""
    spec = cfg.competitors.get(competitor_key, {})
    domains = list(spec.get("domains", [])) + list(spec.get("retail_domains", []))
    budget = cfg.discovery_budget

    urls = provider.candidates(product, competitor_key, domains, budget)
    log = [f"discovery budget {budget}; {len(urls)} candidate URL(s) proposed for "
           f"{competitor_key} within {domains}"]

    candidates: list[Candidate] = []
    blocks: list[dict] = []

    for url in urls[:budget]:
        res = guarded_get(url, cfg.allowed_hosts())
        if res.blocked:
            blocks.append({"url": url, "signal": res.block_signal, "evidence": res.evidence})
            log.append(f"BLOCKED {url} — {res.block_signal}")
            continue
        if not res.ok or not res.html:
            log.append(f"unreadable {url} — HTTP {res.status}")
            continue

        sig = page_signals(res.html)
        if sig["is_listing_page"]:
            log.append(f"skipped {url} — listing page, not a product page")
            continue

        host = host_of(res.final_url or url)
        cand = Candidate(
            url=res.final_url or url,
            brand=sig["brand"] or spec.get("brand", competitor_key),
            product_name=sig["name"] or "not_published",
            host=host,
            source_type=cfg.source_type_for_host(host),
            fmt=sig["fmt"],
            specs=sig["specs"],
            evidence=[f"page read: {res.final_url or url}"],
        )

        from .observe import observe_from_html
        obs = observe_from_html(product.product_id, competitor_key, cand.brand,
                                cand.url, res.html, cand.source_type, cfg.currency)
        comp_price = obs.current_price if isinstance(obs.current_price, (int, float)) else None
        candidates.append(score_candidate(product, cand, comp_price))
        log.append(f"scored {cand.product_name!r} = {candidates[-1].score}")

    return candidates, blocks, log
