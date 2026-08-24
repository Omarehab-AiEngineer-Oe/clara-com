"""What the model costs, and what this system actually spends.

Published prices belong in code rather than in a document, for one reason: a
price typed into a handbook has no expiry date and no source, so a year later
nobody can tell whether it is current or whether someone made it up. Here every
figure carries `as_of`, the page it came from, and the currency it was quoted in
— and the handbook renders this table rather than restating it.

**Prices change and these will go stale.** `staleness()` says how old the table
is, and the handbook prints that sentence next to the numbers. A stale price that
announces its age is usable; a stale price that looks fresh is a lie with a
number in it.

Two things are separated throughout, because conflating them is how model costs
get badly misjudged:

* **The list price** — what Google charges per million tokens. Known, published,
  and identical for everyone.
* **What this system spends** — which is nearly nothing, because the agents run
  their deterministic path by default and call the model only to *narrow* a
  result they already computed. That design decision is a cost decision as much
  as a correctness one, and the arithmetic below shows by how much.

The per-call sizes in `AGENT_CALLS` are **measured**, not estimated: each
one is the real prompt file plus the real serialised payload, counted. The
first version of this file estimated them by reading the code, and the
estimates were wrong by -59 per cent on the identity judge and +315 per
cent on website analysis, in part because they left out the agent prompt
file that every call prepends. `measured: True` marks a figure that came
from a measurement.

A token is roughly four characters of English, or about ¾ of a word. Arabic runs
closer to two or three characters per token, so an Arabic page costs more tokens
than an English page of the same length — which matters here, because a good
share of what this system reads is Arabic.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

# --------------------------------------------------------------------------
# the published table
# --------------------------------------------------------------------------

# When these figures were last checked against the vendor's own pricing page.
# Update this date whenever you update a number, and not otherwise.
AS_OF = date(2026, 5, 1)

SOURCE = "https://cloud.google.com/vertex-ai/generative-ai/pricing"

CURRENCY = "USD"

# Per one million tokens. `input` is everything sent — the prompt, the agent's
# instruction file, and the page text being judged. `output` is what comes back.
#
# Three details that catch people out:
#
#   * Output is several times the price of input on every model here. That is
#     the right way round for this system, which sends a lot and asks for a small
#     JSON verdict back.
#   * "Thinking" tokens, where a model produces reasoning before its answer, are
#     billed at the output rate. A schema-bound call like the ones here keeps
#     that small; an open-ended one does not.
#   * Cached input is cheaper, and only pays off when the same long prefix is
#     sent repeatedly. This system sends a different page every call, so caching
#     would not help and is not used.
MODELS = {
    "gemini-3.5-flash": {
        "input": Decimal("0.30"),
        "output": Decimal("2.50"),
        "cached_input": Decimal("0.075"),
        "note": "the configured default: fast, cheap, and adequate for a "
                "yes/no identity judgement with a schema on it",
    },
    "gemini-2.5-flash": {
        "input": Decimal("0.30"),
        "output": Decimal("2.50"),
        "cached_input": Decimal("0.075"),
        "note": "first fallback if the default is not served in this project",
    },
    "gemini-2.0-flash": {
        "input": Decimal("0.15"),
        "output": Decimal("0.60"),
        "cached_input": Decimal("0.0375"),
        "note": "second fallback; older and cheaper, kept so a run never stalls "
                "on model availability",
    },
    "gemini-3-pro": {
        "input": Decimal("1.25"),
        "output": Decimal("10.00"),
        "cached_input": Decimal("0.3125"),
        "note": "not used here. Listed so the choice of Flash is visible as a "
                "choice: Pro is roughly four times the price for a judgement "
                "this system deliberately keeps narrow",
    },
}

DEFAULT_MODEL = "gemini-3.5-flash"

# Rough characters per token, by script. Used to turn a page size into a token
# estimate. Arabic is the reason this is a table rather than a constant.
CHARS_PER_TOKEN = {
    "english": 4.0,
    "arabic": 2.5,
    "mixed": 3.2,
}


def staleness(today: date | None = None) -> dict:
    """How old this table is, in words the handbook can print.

    A price with no age on it is the problem this function exists to prevent.
    """
    today = today or datetime.now(timezone.utc).date()
    days = (today - AS_OF).days
    if days <= 45:
        state, advice = "current", "checked recently"
    elif days <= 180:
        state, advice = ("ageing",
                         "worth re-checking against the pricing page before "
                         "quoting these to anyone")
    else:
        state, advice = ("stale",
                         "treat these as indicative only and re-check the "
                         "pricing page before relying on them")
    return {"as_of": AS_OF.isoformat(), "days": days, "state": state,
            "advice": advice, "source": SOURCE,
            "sentence": (f"Prices checked {AS_OF.isoformat()}, {days} day(s) "
                         f"ago — {advice}.")}


# --------------------------------------------------------------------------
# arithmetic
# --------------------------------------------------------------------------

def estimate_tokens(chars: int, script: str = "mixed") -> int:
    """Characters to tokens. An estimate, and labelled as one everywhere."""
    per = CHARS_PER_TOKEN.get(script, CHARS_PER_TOKEN["mixed"])
    return int(round(chars / per))


def cost(input_tokens: int, output_tokens: int,
         model: str = DEFAULT_MODEL) -> Decimal:
    """USD for one call. Decimal throughout, like every other money value here."""
    m = MODELS.get(model) or MODELS[DEFAULT_MODEL]
    million = Decimal(1_000_000)
    return ((Decimal(int(input_tokens)) / million) * m["input"]
            + (Decimal(int(output_tokens)) / million) * m["output"])


def money(v: Decimal, places: int = 4) -> str:
    """Format a cost. Sub-cent amounts are the normal case here, so they show."""
    q = Decimal(10) ** -places
    s = f"{v.quantize(q):f}"
    return f"${s}"


# --------------------------------------------------------------------------
# what this system would actually spend
# --------------------------------------------------------------------------

# Superseded by AGENT_CALLS, which is measured per agent. Kept because
# run_estimate() and the model comparison still read it, and because it is
# the coarser three-line view that a summary sometimes wants. Each entry
# is one call: what is sent, what comes back, and how many happen per run.
#
# The output figures are small because every call is schema-bound — the model
# returns a verdict object, not prose. That is a correctness decision (a reply
# that must fit a schema cannot smuggle in an unsupported claim) which happens to
# also be the single biggest cost lever, since output costs roughly eight times
# input.
CALL_SHAPES = {
    "identity_judge": {
        "what": "Is this competitor product the same thing as this Clara "
                "product?",
        "input_chars": 3_200,
        "output_chars": 320,
        "per_run": 408,
        "script": "mixed",
        "note": "one per candidate pairing on a full monitoring run",
    },
    "agent_refine": {
        "what": "Narrow a finding the deterministic rules already produced",
        "input_chars": 18_000,
        "output_chars": 900,
        "per_run": 7,
        "script": "english",
        "note": "one per intelligence agent per cycle, and only when the "
                "rules produced something to narrow",
    },
    "website_narrow": {
        "what": "Reject or lower any website-analysis finding a reviewer would "
                "call a false positive",
        "input_chars": 14_000,
        "output_chars": 1_200,
        "per_run": 1,
        "script": "english",
        "note": "one per website-analysis run",
    },
}


def run_estimate(model: str = DEFAULT_MODEL) -> dict:
    """What a full run costs if every model call is made.

    The honest framing for the handbook: this is the *ceiling*, not the bill.
    Vertex has been unreachable for most of this system's life, every agent has
    run its deterministic path, and the actual spend over that period is zero.
    """
    rows, total_in, total_out, total = [], 0, 0, Decimal(0)
    for key, s in CALL_SHAPES.items():
        ti = estimate_tokens(s["input_chars"], s["script"]) * s["per_run"]
        to = estimate_tokens(s["output_chars"], s["script"]) * s["per_run"]
        c = cost(ti, to, model)
        rows.append({"key": key, "what": s["what"], "calls": s["per_run"],
                     "input_tokens": ti, "output_tokens": to,
                     "cost": c, "cost_text": money(c), "note": s["note"]})
        total_in += ti
        total_out += to
        total += c
    return {
        "model": model, "rows": rows,
        "input_tokens": total_in, "output_tokens": total_out,
        "total": total, "total_text": money(total),
        "daily_text": money(total),
        "monthly_text": money(total * 30),
        "yearly_text": money(total * 365),
        "note": "the ceiling for one full run with every model call made, not a "
                "bill — the deterministic path costs nothing and is what has "
                "actually been running",
    }


# --------------------------------------------------------------------------
# per agent
# --------------------------------------------------------------------------

# What each agent sends and receives, per model call, and how many calls a full
# run makes. The sizes come from the `payload` dict each agent actually builds
# in its `refine()`, and from the judge call in engine.py — not from a guess at
# "roughly a page".
#
# Six of the eleven entries never call a model at all. That is not an omission,
# and it is the most important column in the table: a system where most of the
# work is deterministic costs almost nothing to run and gives the same answer
# twice.
AGENT_CALLS = {
    "Competitor Discovery": {
        "runs_per_month": 30,
        "rides": "daily intelligence cycle",
        "module": "agents/discovery.py",
        "calls": True,
        "task": "Propose competitors missing from the known list",
        # 40 Clara product names, the known-competitor list, and what the rules
        # already found.
        "input_chars": 13_253,
        "output_chars": 778,
        "per_run": 1,
        "measured": True,
        "script": "english",
        "narrows": False,
        "note": "the one model pass that may ADD something — and what it adds "
                "arrives as POSSIBLE with UNVERIFIED confidence and no "
                "evidence, so Verification still has to establish it",
    },
    "Competitor Data Collection": {
        "runs_per_month": 4,
        "rides": "weekly monitoring crawl",
        "module": "agents/collection.py", "calls": False,
        "task": "Read price, availability and promotion wording off a page",
        "why_not": "extraction is JSON-LD, microdata and printed text. A model "
                   "asked to read a price can produce a plausible one; the "
                   "parser either finds it or reports that it did not.",
    },
    "Live Competitor Offers": {
        "runs_per_month": 30,
        "rides": "daily offer sweep",
        "module": "agents/offers.py", "calls": False,
        "task": "Decide which promotions are running, changed or expired",
        "why_not": "the lifecycle is a comparison between two stored states. A "
                   "model cannot know whether a page was readable yesterday, "
                   "and that is the whole question.",
    },
    "Competitor Verification": {
        "runs_per_month": 30,
        "rides": "daily intelligence cycle",
        "module": "agents/verification.py",
        "calls": True,
        "task": "Add a conflict, or downgrade a verdict the evidence does not "
                "support",
        "input_chars": 8_606,
        "output_chars": 1_661,
        "per_run": 1,
        "measured": True,
        "script": "english",
        "narrows": True,
        "note": "may downgrade and may add a conflict; may never upgrade a "
                "verdict or add evidence",
    },
    "Competitor Intelligence": {
        "runs_per_month": 30,
        "rides": "daily intelligence cycle",
        "module": "agents/intelligence.py",
        "calls": True,
        "task": "Tighten the wording of each impact and opportunity",
        "input_chars": 9_585,
        "output_chars": 3_122,
        "per_run": 1,
        "measured": True,
        "script": "english",
        "narrows": True,
        "note": "wording only: no new facts, no number that is not already "
                "present, no changed assessment",
    },
    "Action Recommendation": {
        "runs_per_month": 30,
        "rides": "daily intelligence cycle",
        "module": "agents/action.py",
        "calls": True,
        "task": "Make each action more specific about what to open and decide",
        "input_chars": 10_619,
        "output_chars": 2_323,
        "per_run": 1,
        "measured": True,
        "script": "english",
        "narrows": True,
        "note": "keeps every number exactly as given and may not add an action",
    },
    "Content Arrangement": {
        "runs_per_month": 30,
        "rides": "daily intelligence cycle",
        "module": "agents/arrangement.py", "calls": False,
        "task": "Order the sections and say what to show when one is empty",
        "why_not": "placement is a rule about which sections have content. "
                   "There is nothing here a model would judge better.",
    },
    "Trend Collection": {
        "runs_per_month": 30,
        "rides": "daily trend scan",
        "module": "agents/trend_collector.py", "calls": False,
        "task": "Match articles to subjects and measure how fast each moves",
        "why_not": "matching is a vocabulary of 86 patterns and the scoring is "
                   "arithmetic over publisher breadth, span and acceleration. "
                   "A model would make two scans incomparable.",
    },
    "Website Analysis": {
        "runs_per_month": 4,
        "rides": "run by hand, about weekly",
        "module": "web/orchestrator.py",
        "calls": True,
        "task": "Reject or lower any finding a reviewer would call a false "
                "positive",
        "input_chars": 58_066,
        "output_chars": 3_567,
        "per_run": 1,
        "measured": True,
        "script": "english",
        "narrows": True,
        "note": "may lower, caveat or reject with a reason; may not add a "
                "finding or raise anything",
    },
    "Competitor Intelligence Agent": {
        "runs_per_month": 0,
        "rides": "on demand, when someone asks",
        "module": "ops/agent.py", "calls": False,
        "task": "Answer questions about stored records, with citations",
        "why_not": "answers are assembled from database rows, so every sentence "
                   "has a record behind it. A model would answer more fluently "
                   "and could not cite what it had not read.",
    },
    "Search-query builder": {
        "module": "llm.py queries() via candidates.py",
        "calls": True,
        "task": "Write search queries to find one Clara product on one "
                "competitor's site",
        # Measured from QUERY_PROMPT with a real product interpolated.
        "input_chars": 1_050,
        "output_chars": 260,
        "measured": True,
        # Currently zero. `SearchProvider.candidates()` returns immediately when
        # `search_fn` is None, which it is — nothing in run_agent.py supplies
        # one. Listed at zero calls rather than omitted, because the code is
        # live and would fire once per product-competitor pairing the moment a
        # search function is configured. At 81 products across 46 competitors
        # that is a much larger number than anything else in this table, so it
        # is the one line to check before enabling search discovery.
        "per_run": 0,
        "runs_per_month": 4,
        "rides": "weekly monitoring crawl — dormant: needs a search_fn",
        "script": "english",
        "narrows": False,
        "note": "unreachable while search_fn is None; would become the largest "
                "cost line if enabled",
    },
    "Identity judge": {
        "runs_per_month": 4,
        "rides": "weekly monitoring crawl",
        "module": "engine.py + llm.py",
        "calls": True,
        "task": "Is this competitor product the same thing as this Clara "
                "product?",
        "input_chars": 1_297,
        "output_chars": 380,
        "per_run": 385,
        "measured": True,
        "script": "mixed",
        "narrows": False,
        "note": "not an agent, but the largest single cost: one call per "
                "candidate pairing, and the only place a model decides "
                "something the rules cannot",
    },
}


def agent_costs(model: str = DEFAULT_MODEL) -> dict:
    """Tokens and price per agent, per full run.

    The deterministic agents are returned alongside the priced ones on purpose.
    A cost table showing only what spends money implies the rest do not exist,
    when in fact they are most of the system and the reason the total is small.
    """
    priced, free = [], []
    total_in = total_out = 0
    total = Decimal(0)

    for name, a in AGENT_CALLS.items():
        if not a.get("calls"):
            free.append({"agent": name, "module": a["module"],
                         "task": a["task"], "why_not": a["why_not"]})
            continue
        ti = estimate_tokens(a["input_chars"], a["script"]) * a["per_run"]
        to = estimate_tokens(a["output_chars"], a["script"]) * a["per_run"]
        c = cost(ti, to, model)
        priced.append({
            "agent": name, "module": a["module"], "task": a["task"],
            "calls": a["per_run"], "input_tokens": ti, "output_tokens": to,
            "tokens": ti + to, "cost": c, "cost_text": money(c),
            # A dormant call site has per_run 0 — see the search-query builder.
            # Dividing by it is undefined, and the honest per-call figure there
            # is what it *would* cost, so it is priced for one call.
            "per_call_text": money(c / a["per_run"] if a["per_run"]
                                   else cost(estimate_tokens(a["input_chars"],
                                                             a["script"]),
                                             estimate_tokens(a["output_chars"],
                                                             a["script"]),
                                             model), 6),
            "dormant": a["per_run"] == 0,
            "narrows": a["narrows"], "note": a["note"],
        })
        total_in += ti
        total_out += to
        total += c

    priced.sort(key=lambda r: -r["cost"])
    for r in priced:
        r["share"] = (float(r["cost"] / total * 100) if total else 0.0)
    return {
        "model": model, "priced": priced, "deterministic": free,
        "input_tokens": total_in, "output_tokens": total_out,
        "tokens": total_in + total_out,
        "total": total, "total_text": money(total),
        "monthly_text": money(total * 30), "yearly_text": money(total * 365),
        "priced_count": len(priced), "free_count": len(free),
    }


# --------------------------------------------------------------------------
# infrastructure
# --------------------------------------------------------------------------

# Everything that costs money and is not a token. Each row says whether the
# figure is *known* (published list price) or *unverified* (I cannot read the
# account, so it is an estimate the reader must confirm).
#
# The `verify` field exists because two of these depend on which plan the
# account is on, and a cost document that silently guesses a plan produces a
# total that is confidently wrong.
INFRASTRUCTURE = {
    "vercel_hobby": {
        "line": "Vercel — Hobby plan",
        "monthly": Decimal("0"),
        "known": True,
        "what": "Hosting for the web application. Serverless Python functions, "
                "the shared router, and the login.",
        "verify": "",
    },
    "vercel_pro": {
        "line": "Vercel — Pro plan",
        "monthly": Decimal("20"),
        "known": False,
        "what": "The same hosting on a team account. The project sits under a "
                "team org, which usually means Pro.",
        "verify": "Confirm the plan and seat count at "
                  "vercel.com/account/plans — this is per seat, so two people "
                  "on the team doubles it.",
    },
    "postgres_free": {
        "line": "Managed PostgreSQL — free tier",
        "monthly": Decimal("0"),
        "known": False,
        "what": "Durable operational storage, required by section 9 so a "
                "deploy cannot reset resolutions, requests and audit records.",
        "verify": "Neon and Supabase both publish a free tier that would hold "
                  "this workload today. Confirm current limits before relying "
                  "on it.",
    },
    "postgres_paid": {
        "line": "Managed PostgreSQL — paid tier",
        "monthly": Decimal("19"),
        "known": False,
        "what": "The same, on a plan with backups and no cold-start pause.",
        "verify": "Roughly the entry paid tier at Neon or Supabase. Confirm "
                  "before budgeting.",
    },
    "domain": {
        "line": "clarahair.com",
        "monthly": Decimal("0"),
        "known": True,
        "what": "Already owned and paid for as the storefront. Not a cost this "
                "project introduces.",
        "verify": "",
    },
}

# What is genuinely free, listed because a cost document that omits them invites
# the question "and what about…" for each one.
FREE = [
    ("Local Python application", "no framework, no build step, no service in "
                                 "the request path"),
    ("SQLite", "the collection store; a file, no server"),
    ("Headless Chrome", "screenshots and the own-site render; already installed"),
    ("35 RSS and Atom feeds", "public, and read at a polite rate"),
    ("Competitor and retailer pages", "public pages, read within robots.txt"),
    ("Google Trends RSS", "public endpoint, no key"),
]


# --------------------------------------------------------------------------
# schedules
# --------------------------------------------------------------------------

# Which jobs exist, how often they plausibly run, and whether they cost anything.
# The important column is the last one: two of the five make no model call, so
# their frequency is free to raise.
JOBS = {
    "run_agent.py": {
        "what": "Full monitoring run — every competitor page, every pairing",
        "minutes": "~45",
        "model": True,
        "calls": "one identity judgement per candidate pairing (408 last run)",
    },
    "run_intel.py": {
        "what": "Intelligence cycle — findings, changes and decisions",
        "minutes": "<1",
        "model": True,
        "calls": "four narrowing passes, one per refining agent",
    },
    "run_trends.py": {
        "what": "Scan 35 feeds for market signals",
        "minutes": "1–3",
        "model": False,
        "calls": "none — matching is a 86-pattern vocabulary and the scoring is "
                 "arithmetic",
    },
    "run_offers.py": {
        "what": "Sweep 46 storefronts for live offers",
        "minutes": "3–6",
        "model": False,
        "calls": "none — offer wording is read off the page, and the lifecycle "
                 "is a comparison between two stored states",
    },
    "run_web_analysis.py": {
        "what": "Website Analysis — Clara against named competitors",
        "minutes": "minutes",
        "model": True,
        "calls": "one narrowing pass over the findings",
    },
}

# Plausible operating patterns, and what each costs. `full_runs_per_month` is the
# only figure that moves the total, because the full run carries the identity
# judge and the identity judge is almost all of the spend.
SCHEDULES = {
    "as_running": {
        "label": "Today, as actually running",
        "full_runs_per_month": 0,
        "cycles_per_month": 0,
        "note": "Vertex credentials have been expired for weeks. Every agent "
                "runs its deterministic path, every page says so, and no token "
                "has been billed.",
    },
    "light": {
        "label": "Full run weekly, trends and intelligence daily",
        "full_runs_per_month": 4,
        "cycles_per_month": 30,
        "note": "The pattern this system was built for. Prices do not move "
                "daily, so a weekly crawl and a daily cycle is the honest "
                "cadence.",
    },
    "daily": {
        "label": "Full run daily",
        "full_runs_per_month": 30,
        "cycles_per_month": 30,
        "note": "Every competitor page re-read every day. Roughly six times the "
                "model cost of the weekly pattern for evidence that is rarely "
                "six times fresher.",
    },
    "hourly_trends": {
        "label": "Full run weekly, trends hourly",
        "full_runs_per_month": 4,
        "cycles_per_month": 30,
        "trend_scans_per_month": 720,
        "note": "Trend scanning makes no model call, so raising it from daily to "
                "hourly costs nothing in tokens. The limit is politeness to the "
                "publishers, not money.",
    },
}


def cycle_cost(model: str = DEFAULT_MODEL) -> Decimal:
    """One intelligence cycle: the narrowing passes, without the identity judge.

    Separated from the full run because they run on different clocks. A cycle
    reads stored evidence and takes under a second; the full run goes out to
    forty-six websites and takes three quarters of an hour.
    """
    total = Decimal(0)
    for name, a in AGENT_CALLS.items():
        if not a.get("calls") or name == "Identity judge":
            continue
        ti = estimate_tokens(a["input_chars"], a["script"]) * a["per_run"]
        to = estimate_tokens(a["output_chars"], a["script"]) * a["per_run"]
        total += cost(ti, to, model)
    return total


def schedule_costs(model: str = DEFAULT_MODEL) -> list:
    """Model cost per day and per month for each operating pattern."""
    run = agent_costs(model)["total"]
    cyc = cycle_cost(model)
    out = []
    for key, s in SCHEDULES.items():
        monthly = (Decimal(s["full_runs_per_month"]) * run
                   + Decimal(s["cycles_per_month"]) * cyc)
        out.append({
            "key": key, "label": s["label"], "note": s["note"],
            "full_runs": s["full_runs_per_month"],
            "cycles": s["cycles_per_month"],
            "monthly": monthly, "monthly_text": money(monthly, 2),
            "daily": monthly / 30, "daily_text": money(monthly / 30, 4),
            "yearly_text": money(monthly * 12, 2),
        })
    return out


def total_cost(schedule: str = "light", *, vercel: str = "vercel_hobby",
               postgres: str = "postgres_free",
               model: str = DEFAULT_MODEL) -> dict:
    """The whole bill for one operating pattern, itemised.

    Defaults to the cheapest honest reading: the weekly pattern, Vercel Hobby,
    Postgres free tier. Anything above that has to be chosen, so nobody is
    surprised by a total that assumed a paid plan.
    """
    sched = next((s for s in schedule_costs(model) if s["key"] == schedule),
                 None)
    if sched is None:
        raise KeyError(f"no such schedule: {schedule}")

    lines = [{
        "line": f"Vertex AI — {sched['label'].lower()}",
        "monthly": sched["monthly"], "monthly_text": sched["monthly_text"],
        "known": True,
        "what": "Model calls. The identity judge is almost all of it.",
        "verify": staleness()["sentence"],
    }]
    for key in (vercel, postgres, "domain"):
        i = INFRASTRUCTURE[key]
        lines.append({"line": i["line"], "monthly": i["monthly"],
                      "monthly_text": money(i["monthly"], 2),
                      "known": i["known"], "what": i["what"],
                      "verify": i["verify"]})

    monthly = sum((l["monthly"] for l in lines), Decimal(0))
    unverified = [l["line"] for l in lines if not l["known"]]
    return {
        "schedule": sched, "lines": lines,
        "monthly": monthly, "monthly_text": money(monthly, 2),
        "daily_text": money(monthly / 30, 4),
        "yearly_text": money(monthly * 12, 2),
        "unverified": unverified,
        "confidence": ("every line is a published list price" if not unverified
                       else f"{len(unverified)} line(s) depend on a plan I "
                            f"cannot read from here: "
                            f"{', '.join(unverified)}"),
    }


def one_table(model: str = DEFAULT_MODEL, *, vercel: str = "vercel_hobby",
              postgres: str = "postgres_free") -> dict:
    """Every cost line in this application, flat, priced three ways.

    One table rather than thirteen. The `group` field lets the renderer put a
    band heading in without needing a second structure, and `is_total` marks the
    rows that are sums so a reader is never left adding a column by hand.

    Frequencies come from `runs_per_month` on each agent, because they do not
    share a clock: the identity judge rides the weekly crawl and the refiners
    ride the daily cycle, so one blended "per run" figure would be wrong for
    both.
    """
    rows = []
    month_total = Decimal(0)
    tok_run = tok_month = 0

    for name, a in AGENT_CALLS.items():
        freq = a.get("runs_per_month", 0)
        if a.get("calls"):
            ti = estimate_tokens(a["input_chars"], a["script"]) * a["per_run"]
            to = estimate_tokens(a["output_chars"], a["script"]) * a["per_run"]
            per_run = cost(ti, to, model)
            monthly = per_run * freq
            tok_run += ti + to
            tok_month += (ti + to) * freq
            month_total += monthly
            rows.append({
                "group": "Model — Vertex AI", "line": name,
                "detail": a["rides"], "calls": a["per_run"],
                "tokens": ti + to, "per_run": per_run,
                "per_run_text": money(per_run),
                "per_day_text": money(monthly / 30, 4),
                "per_month_text": money(monthly, 2),
                "monthly": monthly, "is_total": False, "known": True,
            })
        else:
            rows.append({
                "group": "Model — Vertex AI", "line": name,
                "detail": a["rides"] + " — deterministic, no model call",
                "calls": 0, "tokens": 0, "per_run": Decimal(0),
                "per_run_text": "$0.0000", "per_day_text": "$0.0000",
                "per_month_text": "$0.00", "monthly": Decimal(0),
                "is_total": False, "known": True,
            })

    rows.sort(key=lambda r: (-r["monthly"], r["line"]))
    rows.append({
        "group": "Model — Vertex AI", "line": "Model subtotal",
        "detail": f"{tok_month:,} tokens a month",
        "calls": sum(r["calls"] for r in rows), "tokens": tok_run,
        "per_run": Decimal(0), "per_run_text": "",
        "per_day_text": money(month_total / 30, 4),
        "per_month_text": money(month_total, 2), "monthly": month_total,
        "is_total": True, "known": True,
    })

    for key in (vercel, postgres, "domain"):
        i = INFRASTRUCTURE[key]
        month_total += i["monthly"]
        rows.append({
            "group": "Hosting and storage", "line": i["line"],
            "detail": i["what"] if i["known"]
                      else i["what"] + " ESTIMATE: " + i["verify"],
            "calls": 0, "tokens": 0, "per_run": Decimal(0), "per_run_text": "",
            "per_day_text": money(i["monthly"] / 30, 4),
            "per_month_text": money(i["monthly"], 2), "monthly": i["monthly"],
            "is_total": False, "known": i["known"],
        })

    rows.append({
        "group": "Total", "line": "EVERYTHING", "detail": "the whole application",
        "calls": 0, "tokens": tok_month, "per_run": Decimal(0),
        "per_run_text": "", "per_day_text": money(month_total / 30, 4),
        "per_month_text": money(month_total, 2), "monthly": month_total,
        "is_total": True, "known": all(r["known"] for r in rows),
    })

    return {
        "model": model, "rows": rows,
        "monthly": month_total, "monthly_text": money(month_total, 2),
        "daily_text": money(month_total / 30, 4),
        "yearly_text": money(month_total * 12, 2),
        "tokens_per_month": tok_month,
        "cadence": "weekly monitoring crawl, daily intelligence cycle, daily "
                   "trend scan and offer sweep",
        # Total rows inherit `known=False` from any estimate beneath them, which
        # is correct for the total and wrong for this list — "EVERYTHING" is not
        # a line whose plan needs checking.
        "unverified": [r["line"] for r in rows
                       if not r["known"] and not r["is_total"]],
        "staleness": staleness(),
    }


def compare_models() -> list:
    """The same run priced on each model, so the Flash choice is legible."""
    out = []
    for name in MODELS:
        e = run_estimate(name)
        out.append({"model": name, "note": MODELS[name]["note"],
                    "input_per_m": MODELS[name]["input"],
                    "output_per_m": MODELS[name]["output"],
                    "run_cost": e["total"], "run_text": e["total_text"],
                    "monthly_text": e["monthly_text"]})
    out.sort(key=lambda r: r["run_cost"])
    return out


def summary() -> dict:
    """Everything the handbook's token-price section needs, in one call."""
    est = run_estimate()
    return {
        "as_of": AS_OF.isoformat(),
        "source": SOURCE,
        "currency": CURRENCY,
        "staleness": staleness(),
        "models": MODELS,
        "default_model": DEFAULT_MODEL,
        "chars_per_token": CHARS_PER_TOKEN,
        "estimate": est,
        "comparison": compare_models(),
        "agents": agent_costs(),
        "infrastructure": INFRASTRUCTURE,
        "free": FREE,
        "jobs": JOBS,
        "schedules": schedule_costs(),
        "totals": {k: total_cost(k) for k in SCHEDULES},
    }
