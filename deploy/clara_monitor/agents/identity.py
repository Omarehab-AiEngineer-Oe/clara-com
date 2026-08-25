"""Deciding when two records are the same competitor.

The orchestrator's rule is "never create duplicate competitors", using company
name, domain, product, entity identity and evidence. Getting this wrong is
expensive in both directions: a false merge hides a real new entrant behind an
existing name, and a false split reports the same company twice as if the market
had grown. So the test is ordered by how much a signal actually proves.

1. Registrable domain is decisive. `en-saudi.ounass.com` and `ounass.com` are one
   company; two different registrable domains are two companies until something
   else says otherwise.
2. A normalised brand name is strong but not decisive on its own, because retail
   suffixes and legal forms ("Ltd", "KSA", "Beauty") differ between sources.
3. Product overlap only ever corroborates. Two companies selling the same product
   are usually a brand and its retailer, which is the exact case that must NOT be
   merged.

Anything that lands between "same" and "different" is returned as a possible
duplicate for a human, never merged silently.
"""

from __future__ import annotations

import re
import unicodedata

# Suffixes that carry no identity. Stripped only from the end of a name, so
# "Beauty Bar" keeps its meaning while "Shark Beauty" folds to "shark".
_NOISE_TAIL = (
    "ltd", "limited", "llc", "inc", "co", "company", "corp", "corporation",
    "gmbh", "sa", "sarl", "bv", "plc", "trading", "est", "establishment",
    "group", "holding", "holdings", "international", "global",
    "ksa", "saudi", "arabia", "gulf", "me", "mena",
    "store", "stores", "shop", "official", "beauty", "cosmetics", "hair",
)

# Hosts that are a marketplace or a platform, never the brand itself. A record
# whose only domain is one of these is identified by name, not by host.
PLATFORM_HOSTS = {
    "amazon", "noon", "namshi", "shein", "aliexpress", "ebay", "temu",
    "instagram", "tiktok", "facebook", "snapchat", "youtube", "x", "twitter",
    "linktr", "shopify", "salla", "zid", "wordpress", "blogspot",
}

_MULTI_TLD = ("co.uk", "com.sa", "com.au", "co.jp", "com.tr", "com.br",
              "co.kr", "com.eg", "com.kw", "co.za", "com.mx")


def registrable_domain(value: str) -> str:
    """The part of a host that identifies the company.

    `https://en-saudi.ounass.com/women/` -> `ounass.com`
    """
    if not value:
        return ""
    v = value.strip().lower()
    v = re.sub(r"^[a-z]+://", "", v)
    v = v.split("/")[0].split("?")[0].split("#")[0]
    v = v.split("@")[-1].split(":")[0]
    if v.startswith("www."):
        v = v[4:]
    parts = [p for p in v.split(".") if p]
    if len(parts) < 2:
        return v
    for suffix in _MULTI_TLD:
        if v.endswith("." + suffix) and len(parts) >= 3:
            return ".".join(parts[-3:])
    return ".".join(parts[-2:])


def is_platform(domain: str) -> bool:
    reg = registrable_domain(domain)
    return reg.split(".")[0] in PLATFORM_HOSTS if reg else False


def normalise_name(value: str) -> str:
    """Fold a company name to a comparable key.

    Accents, punctuation, spacing and trailing corporate noise are removed. The
    result is not for display — it exists only so two spellings of one company
    collide.
    """
    if not value:
        return ""
    v = unicodedata.normalize("NFKD", value)
    v = "".join(ch for ch in v if not unicodedata.combining(ch))
    v = v.lower()
    v = re.sub(r"[^a-z0-9؀-ۿ ]+", " ", v)
    words = [w for w in v.split() if w]
    while len(words) > 1 and words[-1] in _NOISE_TAIL:
        words.pop()
    return "".join(words)


def identity_key(name: str = "", domains: list[str] | None = None) -> str:
    """The stable key a competitor is stored under.

    A real company domain wins, because it survives rebrands and translation. A
    marketplace host does not, because every brand on it would collapse into one
    record.
    """
    for d in domains or []:
        reg = registrable_domain(d)
        if reg and not is_platform(reg):
            return "d:" + reg
    n = normalise_name(name)
    return ("n:" + n) if n else ""


SAME = "same"
POSSIBLE = "possible"
DIFFERENT = "different"


def compare(a: dict, b: dict) -> tuple[str, str]:
    """Are these two records the same competitor?

    Returns (verdict, reason). `possible` means a person decides; it is never
    resolved by picking the more likely option, because the cost of a wrong merge
    is silent and permanent.
    """
    a_doms = {registrable_domain(d) for d in (a.get("domains") or []) if d}
    b_doms = {registrable_domain(d) for d in (b.get("domains") or []) if d}
    a_doms.discard("")
    b_doms.discard("")

    real_a = {d for d in a_doms if not is_platform(d)}
    real_b = {d for d in b_doms if not is_platform(d)}

    shared = real_a & real_b
    if shared:
        return SAME, f"same registrable domain: {sorted(shared)[0]}"

    na, nb = normalise_name(a.get("name", "")), normalise_name(b.get("name", ""))
    if na and na == nb:
        if real_a and real_b:
            # Same name, both with their own real domains. Usually a brand and a
            # local distributor of it — related, but not one record.
            return POSSIBLE, (f"identical name '{na}' but different domains "
                              f"({sorted(real_a)[0]} vs {sorted(real_b)[0]})")
        return SAME, f"identical normalised name: {na}"

    if na and nb and (na in nb or nb in na) and min(len(na), len(nb)) >= 5:
        return POSSIBLE, f"one name contains the other: '{na}' / '{nb}'"

    pa = {normalise_name(p) for p in (a.get("products") or []) if p}
    pb = {normalise_name(p) for p in (b.get("products") or []) if p}
    pa.discard("")
    pb.discard("")
    overlap = pa & pb
    if overlap and (na and nb) and (na[:4] == nb[:4]):
        return POSSIBLE, (f"similar names and a shared product "
                          f"({sorted(overlap)[0]})")

    return DIFFERENT, "no shared domain, name or identity signal"


def dedupe(records: list[dict]) -> tuple[list[dict], list[dict]]:
    """Fold a candidate list onto itself.

    Returns (kept, flagged). `kept` carries one record per identity with its
    domains and evidence merged; `flagged` holds the pairs a person must resolve.
    Merging keeps the first record's display name so an established spelling is
    not replaced by whatever a search result happened to print.
    """
    kept: list[dict] = []
    flagged: list[dict] = []

    for rec in records:
        merged_into = None
        for existing in kept:
            verdict, reason = compare(existing, rec)
            if verdict == SAME:
                existing.setdefault("domains", [])
                for d in rec.get("domains") or []:
                    if d not in existing["domains"]:
                        existing["domains"].append(d)
                existing.setdefault("evidence", [])
                existing["evidence"].extend(rec.get("evidence") or [])
                existing.setdefault("merged_from", []).append(
                    {"name": rec.get("name"), "reason": reason})
                merged_into = existing
                break
            if verdict == POSSIBLE:
                flagged.append({"a": existing.get("name"), "b": rec.get("name"),
                                "reason": reason})
        if merged_into is None:
            kept.append(dict(rec))

    return kept, flagged
