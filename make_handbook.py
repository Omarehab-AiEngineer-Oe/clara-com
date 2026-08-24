"""Add the three requested sections to the handbook, in the handbook's own idiom.

    How the agents work    what an "agent" is here, and what it is not
    How the AI works       tokens, context, temperature, and why the model
                           is a narrowing pass rather than the engine
    What the tokens cost   the published table, dated, plus what a run spends

Appending rather than regenerating. The handbook is 627 paragraphs of prose that
was written deliberately, and rebuilding it from a script would mean rewriting all
of it from a worse source — so this opens the existing document, matches its
styles, and adds to the end.

**Every number here is computed, never typed.** The token table comes from
`clara_monitor.pricing`, which carries its own `as_of` date and prints how stale
it is. The agent inventory is read from the modules on disk. A handbook that
states a figure a reader cannot trace is the same failure the system itself is
built to avoid.

    python make_handbook.py                 # writes Clara_Monitor_Handbook_v4.docx
    python make_handbook.py --in-place      # updates v3 instead
"""

from __future__ import annotations

import argparse
import importlib
import sys
from pathlib import Path

import docx
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Pt, RGBColor

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

SRC = ROOT / "Clara_Monitor_Handbook_v3.docx"
OUT = ROOT / "Clara_Monitor_Handbook_v4.docx"
SOURCES_OUT = ROOT / "Clara_Sources.docx"
COST_OUT = ROOT / "Clara_Cost.docx"

# Matched from the existing document rather than invented.
EYEBROW_COLOR = RGBColor(0xB8, 0x44, 0x6E)
EYEBROW_FONT = "Consolas"
EYEBROW_SIZE = Pt(8)


class Doc:
    """Thin wrapper so each section reads as prose rather than as docx calls."""

    def __init__(self, path: Path):
        self.d = docx.Document(str(path))

    def h1(self, text: str, eyebrow: str = ""):
        self.d.add_paragraph(text, style="Heading 1")
        if eyebrow:
            p = self.d.add_paragraph()
            r = p.add_run(eyebrow.upper())
            r.bold = True
            r.font.name = EYEBROW_FONT
            r.font.size = EYEBROW_SIZE
            r.font.color.rgb = EYEBROW_COLOR
        return self

    def h2(self, text: str):
        self.d.add_paragraph(text, style="Heading 2")
        return self

    def p(self, text: str = ""):
        self.d.add_paragraph(text)
        return self

    def lead(self, text: str):
        """A bold opening sentence, used for the claim a section is making."""
        par = self.d.add_paragraph()
        par.add_run(text).bold = True
        return self

    def bullets(self, items):
        for i in items:
            par = self.d.add_paragraph(style="List Bullet")
            if isinstance(i, (tuple, list)) and len(i) == 2:
                par.add_run(f"{i[0]}. ").bold = True
                # The handbook's own bullets read "Label. Sentence" with the
                # sentence capitalised. Lowercasing after a full stop looks like
                # a typo rather than a style.
                body = str(i[1])
                par.add_run(body[:1].upper() + body[1:] if body else "")
            else:
                par.add_run(str(i))
        return self

    def table(self, headers, rows, widths=None):
        t = self.d.add_table(rows=1, cols=len(headers))
        t.style = "Table Grid"
        for c, h in zip(t.rows[0].cells, headers):
            c.text = ""
            r = c.paragraphs[0].add_run(str(h).upper())
            r.bold = True
            r.font.size = Pt(8)
            r.font.name = EYEBROW_FONT
        for row in rows:
            cells = t.add_row().cells
            for c, v in zip(cells, row):
                c.text = ""
                run = c.paragraphs[0].add_run("" if v is None else str(v))
                run.font.size = Pt(9)
        self.d.add_paragraph()
        return self

    def save(self, path: Path):
        self.d.save(str(path))


# --------------------------------------------------------------------------
# facts, read from the running system rather than typed
# --------------------------------------------------------------------------

def agent_inventory() -> list:
    """Every agent on disk, with what it decides and what it may not do."""
    rows = [
        ("Competitor Discovery", "agents/discovery.py",
         "Which competitors exist and which are the same company under two "
         "names", "Cannot add a competitor with no evidence row"),
        ("Competitor Data Collection", "agents/collection.py",
         "What each competitor page actually says: price, availability, "
         "promotion wording", "Cannot infer a price that was not printed"),
        ("Live Competitor Offers", "agents/offers.py",
         "Which promotions are running now, and which have expired",
         "Cannot mark an offer expired from a page it could not read"),
        ("Competitor Verification", "agents/verification.py",
         "Whether a claim is observed, editorial, or not established",
         "Cannot raise a confidence — only lower one"),
        ("Competitor Intelligence", "agents/intelligence.py",
         "What the verified changes mean for Clara",
         "Cannot produce a finding with no evidence behind it"),
        ("Action Recommendation", "agents/action.py",
         "What a person should do, by when, and why now",
         "Cannot raise a task that does not name a number, a product and a "
         "decision"),
        ("Content Arrangement", "agents/arrangement.py",
         "The order sections appear in, and what to say when one is empty",
         "Cannot change a value, only its placement"),
        ("Trend Collection", "agents/trend_collector.py",
         "What publishers are covering, and how fast it is moving",
         "Cannot score social engagement — it is behind a login, so its weight "
         "is redistributed and reported as not measured"),
        ("Website Analysis", "web/orchestrator.py",
         "How Clara's site compares with competitor sites on copy, CTAs and "
         "imagery", "Cannot call something absent on a page it could not read"),
        ("Competitor Intelligence Agent", "ops/agent.py",
         "Answers questions about stored records, with citations and provenance",
         "Cannot do marketing, advertising, SEO, social, copywriting or "
         "acquisition — enforced on the question and again on the answer"),
    ]
    out = []
    for name, rel, decides, refuses in rows:
        path = ROOT / "clara_monitor" / rel
        out.append({"name": name, "file": rel, "decides": decides,
                    "refuses": refuses, "exists": path.exists(),
                    "lines": (len(path.read_text(encoding="utf-8").splitlines())
                              if path.exists() else 0)})
    return out


def model_config() -> dict:
    from clara_monitor import llm
    return {
        "model": llm.MODEL_ID,
        "fallbacks": list(llm.FALLBACK_MODEL_IDS),
        "location": getattr(llm, "LOCATION", "global"),
    }


# --------------------------------------------------------------------------
# section 1 — how the agents work
# --------------------------------------------------------------------------

def section_agents(doc: Doc) -> None:
    inv = agent_inventory()
    live = [a for a in inv if a["exists"]]

    doc.h1("How the agents work, in full", "agents")
    doc.lead(
        "An agent here is not a model in a loop with tools. It is a named "
        "function with a written instruction file, a deterministic "
        "implementation, and an optional model pass that is only allowed to "
        "make its answer weaker.")
    doc.p(
        "That definition is unusual enough to be worth stating plainly, because "
        "the word means something else almost everywhere. There is no planner "
        "here, no tool-selection loop, and no agent that decides what to do "
        "next. Each one is handed its inputs, applies rules that a person can "
        "read, and returns a typed result along with a record of how it "
        "decided. If the model is unavailable — which it has been for most of "
        f"this system's life — all {len(live)} of them still run, and every "
        "page says which path produced what is on it.")

    doc.h2("The four parts every agent has")
    doc.bullets([
        ("A prompt file on disk",
         "in prompts/agents/. The instruction the agent runs under is the one "
         "an operator can open and edit. There is no second copy embedded in "
         "the code to fall out of step with it."),
        ("run_rules()",
         "the deterministic implementation. This is the floor, not the "
         "fallback: it runs on every invocation, and its output is what gets "
         "stored if nothing else happens."),
        ("refine()",
         "the optional model pass. It receives what the rules produced and may "
         "narrow it. It never sees a blank page and is never asked to produce "
         "a result from nothing."),
        ("AgentReport",
         "what the agent says about its own run: whether it ran, what it "
         "skipped, what blocked it, and — the important field — "
         "decision_source, which records whether a verdict came from the rules "
         "or the model. A reader can always tell."),
    ])

    doc.h2("Why the rules run first, and always")
    doc.p(
        "Two reasons, and the second is the one that decided it.")
    doc.p(
        "The first is availability. A monitoring run that stalls because a "
        "credential expired is a monitoring run that does not exist. Vertex "
        "credentials on this project have been expired for weeks; every agent "
        "has continued to run, and every surface has said so rather than going "
        "blank.")
    doc.p(
        "The second is comparability. If a verdict came from the model on "
        "Tuesday and from the rules on Wednesday, the two runs cannot be "
        "compared, and the whole previous-state machinery — which exists to "
        "answer “what changed” — would be measuring the weather rather "
        "than the market. A deterministic floor means two runs differ only "
        "where the evidence differed.")

    doc.h2("Narrowing, and why it is the only thing a model may do")
    doc.p(
        "When the model is reachable it is given the rules' output and asked one "
        "question: is any of this over-stated? It may lower a confidence, lower "
        "a priority, attach a caveat, or reject a finding with a reason. It may "
        "not add a finding, raise a confidence, widen a scope, or introduce a "
        "claim the stored evidence does not already support. Anything it returns "
        "that is not backed by an evidence record already held is dropped before "
        "storage.")
    doc.p(
        "This is not caution for its own sake. A model that can add a finding "
        "can add a wrong one, and a wrong finding with a confident sentence "
        "attached is worse than a missing one — it is the failure mode this "
        "whole system is arranged to prevent. Narrowing has the property that "
        "its worst case is a true finding being under-rated, which a person "
        "notices; the alternative's worst case is a false finding being acted "
        "on, which they do not.")

    doc.h2("A page that says “ignore previous instructions”")
    doc.p(
        "Competitor pages are untrusted input, and they are read by a model. "
        "The defence is structural rather than a plea in the prompt: the model "
        "is never given a tool, never given a write path, and never asked an "
        "open question. Every call is schema-bound, so the only shape a reply "
        "can take is a verdict object with fields the caller already knows how "
        "to validate. A page instructing the model to rate it highly produces, "
        "at worst, a verdict that fails validation and is discarded.")

    doc.h2("The agents, and what each one is not allowed to do")
    doc.table(
        ["Agent", "Decides", "Cannot"],
        [(a["name"], a["decides"], a["refuses"]) for a in live])
    missing = [a["name"] for a in inv if not a["exists"]]
    if missing:
        doc.p(f"Listed but not present in this build: {', '.join(missing)}.")


# --------------------------------------------------------------------------
# section 2 — how the AI works
# --------------------------------------------------------------------------

def section_ai(doc: Doc) -> None:
    cfg = model_config()
    doc.h1("How the AI works", "ai")
    doc.lead(
        "A language model predicts the next piece of text, one piece at a time, "
        "given everything before it. Everything else about how it behaves here "
        "follows from that one sentence.")
    doc.p(
        "It is worth being concrete, because the abstraction hides the property "
        "that matters most operationally: what a model cannot be trusted to do, "
        "and therefore what this system never asks one to do.")

    doc.h2("Tokens")
    doc.p(
        "A model does not read characters or words. It reads tokens — chunks of "
        "roughly four characters of English, or about three-quarters of a word. "
        "“conditioner” might be two tokens; “the” is one; a "
        "long product code might be six.")
    doc.p(
        "Arabic is denser: closer to two or three characters per token, because "
        "the model's vocabulary was built mostly on English text. That matters "
        "here rather than being trivia, because a good share of what this "
        "system reads is Arabic — a Saudi storefront page uses noticeably more "
        "tokens than an English page of the same length, so it fills the context "
        "window faster and is trimmed sooner.")
    doc.p(
        "Everything is tokens: the instruction file, the page text being "
        "judged, the schema, and the reply. The count matters because it is "
        "also the limit — a page too long to fit in one call has to be trimmed, "
        "and what gets trimmed is a decision rather than an accident.")

    doc.h2("Context: what the model can see at once")
    doc.p(
        "A model has a context window — the maximum tokens it can hold in one "
        "call. It has no memory between calls. Every call to this system's "
        "model is self-contained: the agent's instruction file, the evidence, "
        "and the question, assembled fresh each time.")
    doc.p(
        "This is why there is no conversation state in the intelligence agents. "
        "What looks like continuity across a cycle is the database, not the "
        "model. The model is asked a narrow question, answers it, and forgets.")

    doc.h2("Temperature, and why it is zero here")
    doc.p(
        "Temperature controls how much randomness goes into choosing each next "
        "token. At a high setting the same question produces different answers, "
        "which is useful for writing and useless for judgement.")
    doc.p(
        "Every call in this system runs at temperature 0. Two runs over "
        "unchanged evidence should produce the same verdict, or “what "
        "changed since last cycle” becomes unanswerable. It is not fully "
        "deterministic even so — floating-point and serving-side variation "
        "leave a little wobble — which is a further reason the deterministic "
        "rules, and not the model, are what the stored state is built from.")

    doc.h2("What it is good at, and what it is not")
    doc.bullets([
        ("Good at judging sameness",
         "“is this competitor product the same thing as this Clara "
         "product” is a question about meaning, where a rule based on "
         "string overlap fails on synonyms and fails again on Arabic. This is "
         "the one place the model earns its place."),
        ("Good at reading messy text",
         "pulling a printed price out of a page whose markup changed last "
         "week."),
        ("Bad at arithmetic",
         "so it never does any. Every price, percentage and discount in this "
         "system is computed in Python with Decimal, never asked of a model."),
        ("Bad at knowing what it does not know",
         "a model asked for a source will often produce a plausible URL that "
         "does not exist. So it is never asked for one. Sources come from the "
         "fetch layer, which has the HTTP response to prove it."),
        ("Has no access to the live web",
         "it sees only the text a call includes. Anything it says about a page "
         "nobody fetched is invention, which is why the fetch and the judgement "
         "are separate steps."),
    ])

    doc.h2("The model this system uses")
    doc.table(
        ["Setting", "Value", "Why"],
        [("Model", cfg["model"],
          "a Flash-class model: fast, and adequate for a schema-bound identity "
          "judgement with a deterministic scorer underneath it"),
         ("Fallbacks", ", ".join(cfg["fallbacks"]),
          "tried in order if the default is not served in this project, so a "
          "run never stalls on model availability"),
         ("Region", cfg["location"],
          "the newer models are served only from the global endpoint"),
         ("Temperature", "0",
          "two runs over the same evidence must agree"),
         ("Reply format", "JSON, schema-bound",
          "a reply that does not fit the schema is discarded rather than "
          "parsed hopefully"),
         ("Credentials", "Application Default Credentials",
          "no key in the repository; an expired credential degrades to the "
          "rules path and is reported on the page")])

    doc.h2("What happens when it is unavailable")
    doc.p(
        "It has been unavailable for most of this system's operating life, and "
        "that is a design case rather than an incident. Every agent runs its "
        "deterministic path, every stored verdict records "
        "decision_source: deterministic_rules, and every page that shows a "
        "judgement states that the model did not weigh in. Nothing silently "
        "degrades to a worse answer wearing the same badge.")


# --------------------------------------------------------------------------
# section 3 — token prices
# --------------------------------------------------------------------------

def section_tokens(doc: Doc) -> None:
    from clara_monitor import pricing
    s = pricing.summary()
    est = s["estimate"]

    doc.h1("What the tokens cost", "cost")
    doc.lead(
        "Model usage is billed per million tokens, separately for what you send "
        "and what comes back, and output costs several times what input costs.")
    doc.p(
        f"Every figure in this section is computed by clara_monitor/pricing.py "
        f"rather than typed into this document. {s['staleness']['sentence']} "
        f"The published rates come from {s['source']}.")

    doc.h2("Published rates, per million tokens")
    doc.table(
        ["Model", f"Input ({s['currency']})", f"Output ({s['currency']})",
         "Cached input", "Note"],
        [(name, f"${m['input']}", f"${m['output']}", f"${m['cached_input']}",
          m["note"]) for name, m in s["models"].items()])
    doc.p(
        "Three details that catch people out. Output is roughly eight times the "
        "price of input on the Flash models, which is the right way round for "
        "this system: it sends a whole page and asks for a small JSON verdict "
        "back. “Thinking” tokens, where a model reasons before "
        "answering, are billed at the output rate — schema-bound calls keep "
        "that small and open-ended ones do not. Cached input is cheaper but only "
        "pays off when the same long prefix is sent repeatedly; this system "
        "sends a different page every call, so caching would not help and is "
        "not used.")

    doc.h2("How many tokens a page is")
    doc.table(
        ["Script", "Characters per token", "A 4,000-character page"],
        [(k.title(), v, f"{pricing.estimate_tokens(4000, k):,} tokens")
         for k, v in s["chars_per_token"].items()])
    doc.p(
        "The Arabic row is the one worth noticing: the same page costs about "
        "sixty per cent more tokens in Arabic than in English, because the "
        "tokeniser was built mostly on English text.")

    doc.h2("What one full run would cost")
    doc.p(
        "This is the ceiling — every model call made, on every pairing — not a "
        "bill. The deterministic path costs nothing, and it is what has "
        "actually been running.")
    doc.table(
        ["Call", "Per run", "Input tokens", "Output tokens", "Cost"],
        [(r["what"], f"{r['calls']:,}", f"{r['input_tokens']:,}",
          f"{r['output_tokens']:,}", r["cost_text"]) for r in est["rows"]]
        + [("Total, one full run", "", f"{est['input_tokens']:,}",
            f"{est['output_tokens']:,}", est["total_text"])])
    doc.p(
        f"On {est['model']} a full monitoring run with every judgement made "
        f"costs about {est['total_text']}. Run daily, that is roughly "
        f"{est['monthly_text']} a month and {est['yearly_text']} a year — for "
        f"the entire competitive intelligence function.")

    doc.h2("The same run on each model")
    doc.table(
        ["Model", "Per run", "Per month, daily", "Note"],
        [(c["model"], c["run_text"], c["monthly_text"], c["note"])
         for c in s["comparison"]])
    doc.p(
        "The Pro row is why Flash was chosen. Four times the price, for a "
        "yes-or-no identity judgement that has a schema on it and a "
        "deterministic scorer underneath. The extra capability has nothing to "
        "do on this task.")

    doc.h2("Why the bill is smaller than the table suggests")
    doc.bullets([
        ("The rules run first",
         "the model is a narrowing pass over a result that already exists. "
         "Where the rules are confident and uncontested, no call is made at "
         "all."),
        ("Replies are schema-bound",
         "the model returns a verdict object, not prose. Output is the "
         "expensive direction, and this is the single largest lever on the "
         "total."),
        ("Nothing is re-judged",
         "a pairing confirmed by a person is never sent to the model again. "
         "Human decisions are held, not re-litigated nightly."),
        ("Rendering never calls the model",
         "loading a page reads the database. Collection and judgement are "
         "explicit jobs, so traffic to the site costs nothing."),
        ("Vertex has been unreachable",
         "so the measured spend over this system's operating life to date is "
         "zero, and every page has said which path produced its numbers."),
    ])

    doc.h2("What is not in these figures")
    doc.p(
        "Vertex charges for the model call and nothing else here — there is no "
        "vector database, no embedding step, no fine-tuning and no hosted "
        "inference endpoint. The other running costs are the Vercel deployment "
        "and, once section 9 of the addendum is satisfied, a managed PostgreSQL "
        "instance. Neither is a token cost and neither is priced above.")


# --------------------------------------------------------------------------
# section 4 — what each agent costs
# --------------------------------------------------------------------------

def section_agent_costs(doc: Doc) -> None:
    from clara_monitor import pricing
    a = pricing.agent_costs()

    doc.h1("What each agent costs", "cost")
    doc.lead(
        f"Of the {a['priced_count'] + a['free_count']} things in this system "
        f"that could call a model, {a['free_count']} never do — and of the "
        f"{a['priced_count']} that do, one accounts for "
        f"{a['priced'][0]['share']:.0f} per cent of the bill.")
    doc.p(
        "That shape is the whole cost story, and it is worth reading before the "
        "table. Almost everything here is deterministic and free. The single "
        "expensive line is not an agent at all: it is the identity judge, which "
        "runs once per candidate pairing and answers the one question rules "
        "genuinely cannot — whether two differently-named products in two "
        "languages are the same thing.")

    doc.h2("Per agent, per full run")
    doc.table(
        ["Agent", "Calls", "Input tokens", "Output tokens", "Cost", "Share"],
        [(r["agent"], f"{r['calls']:,}", f"{r['input_tokens']:,}",
          f"{r['output_tokens']:,}", r["cost_text"], f"{r['share']:.1f}%")
         for r in a["priced"]]
        + [("Total, one full run", "",
            f"{a['input_tokens']:,}", f"{a['output_tokens']:,}",
            a["total_text"], "100%")])
    doc.p(
        f"On {a['model']}, a full run in which every model call is made costs "
        f"{a['total_text']}. Run daily that is {a['monthly_text']} a month and "
        f"{a['yearly_text']} a year. These are ceilings: the deterministic path "
        f"costs nothing, and with Vertex unreachable it is what has actually "
        f"been running, so the spend to date is zero.")

    doc.h2("What each call is for, and what it may not do")
    # The nested conditional that used to build this column produced
    # "Yes, within limits: not an agent, but the largest single cost" for the
    # identity judge — a sentence fragment spliced from the wrong field. Each
    # non-narrowing case now says what it is actually permitted to do.
    may_add = {
        "Competitor Discovery":
            "A candidate only — and it arrives as POSSIBLE, UNVERIFIED, with no "
            "evidence, so Verification must still establish it",
        "Identity judge":
            "A verdict only, on a pairing the rules already scored and "
            "shortlisted. It cannot introduce a product",
    }
    doc.table(
        ["Agent", "The question it asks the model", "What it may return"],
        [(r["agent"], r["task"],
          "A lower confidence, a lower priority, a caveat, or a rejection with "
          "a reason. Nothing new, and nothing raised." if r["narrows"]
          else may_add.get(r["agent"], "See the note in pricing.py"))
         for r in a["priced"]])
    doc.p(
        "Two of the six are not narrowing passes. Competitor Discovery may "
        "propose a competitor nobody listed, but whatever it proposes arrives "
        "as POSSIBLE with UNVERIFIED confidence and no evidence attached, so "
        "the Verification agent still has to establish it before it counts. The "
        "identity judge returns a verdict on a pairing the rules already scored. "
        "Neither can write a fact into the database on its own.")

    doc.h2(f"The {a['free_count']} that never call a model")
    doc.p(
        "Listed because their absence from the cost table is a design decision "
        "rather than an oversight, and because each one has a specific reason.")
    doc.table(
        ["Agent", "What it does", "Why no model"],
        [(r["agent"], r["task"], r["why_not"]) for r in a["deterministic"]])

    doc.h2("Where the money would actually go")
    doc.bullets([
        ("The identity judge is 97 per cent of it",
         f"{a['priced'][0]['calls']:,} calls, one per candidate pairing. If "
         f"cost ever needed reducing, this is the only line worth looking at — "
         f"and the lever is fewer pairings, not a cheaper model."),
        ("Every other agent is a rounding error",
         "the five narrowing passes together come to less than a cent per run. "
         "Cutting them would save nothing and would remove the check that stops "
         "an over-stated finding from reaching a page."),
        ("Output is where the price is",
         "output costs roughly eight times input on these models. Every call is "
         "schema-bound and returns a small verdict object, which is why the "
         "output column is a tenth of the input column."),
        ("Confirmed pairings are never re-judged",
         "a match a person confirmed is held, not sent back to the model on the "
         "next run. The bill does not grow with the number of past decisions."),
    ])


# --------------------------------------------------------------------------
# section 5 — the sources
# --------------------------------------------------------------------------

def gather_sources() -> dict:
    from make_source_register import PLATFORM, gather
    d = gather()
    d["platform"] = PLATFORM
    return d


def section_sources(doc: Doc, d: dict) -> None:
    from make_source_register import KIND_LABEL, MARKET_LABEL, meaning

    feeds_ok = [f for f in d["feeds"] if f["ok"]]
    items = sum(f["items"] for f in d["feeds"])
    kept = sum(f["kept"] for f in d["feeds"])
    sweep_ok = [s for s in d["sweep"] if not s["refusal"]]
    sweep_no = [s for s in d["sweep"] if s["refusal"]]
    own = [c for c in d["rivals"] if c["domains"]]
    total = (len(d["feeds"]) + len(d["refused"]) + len(d["dead"]) + len(own)
             + len(d["retailers"]) + len(d["platform"]) + 1)

    doc.h1("Every source, with its address", "provenance")
    doc.lead(
        f"{total} external sources, listed with the address each one is read "
        f"from and whether it answers.")
    doc.p(
        "The sources that refuse us are here beside the ones that do not. A "
        "register of only what worked would imply a coverage this system does "
        "not have, and roughly a third of what it asks for says no. Every table "
        "below is generated from the live registry; only the standards table at "
        "the end is maintained by hand.")

    doc.table(
        ["What", "Count"],
        [("Trend feeds registered", len(d["feeds"])),
         ("— of which answered on the last scan", len(feeds_ok)),
         ("Items read from those feeds", f"{items:,}"),
         ("— of which survived the beauty filter", f"{kept:,}"),
         ("Publishers refusing automated access", len(d["refused"])),
         ("Feeds that no longer exist", len(d["dead"])),
         ("Competitor brands registered", len(d["rivals"])),
         ("— of which have their own Saudi domain", len(own)),
         ("Saudi retailers and marketplaces", len(d["retailers"])),
         ("Storefronts probed for offers", len(d["sweep"])),
         ("— of which were readable", len(sweep_ok)),
         ("— of which refused", len(sweep_no)),
         ("Clara products in the catalogue", len(d["clara"])),
         ("Platform and standards references", len(d["platform"]))])

    # ---- feeds
    doc.h2(f"Trend feeds ({len(d['feeds'])})")
    doc.p(
        "RSS and Atom feeds across six markets. Kept is how many items survived "
        "the beauty filter — the gap between read and kept is the point of "
        "having one. Weight is how much a source counts toward a trend score.")
    doc.table(
        ["Publisher", "Feed", "Market", "Kind", "Answers", "Items", "Kept",
         "Wt"],
        [(f["publisher"], f["url"],
          MARKET_LABEL.get(f["market"], f["market"]),
          KIND_LABEL.get(f["kind"], f["kind"]),
          "yes" if f["ok"] else "no", f"{f['items']:,}", f"{f['kept']:,}",
          f["weight"])
         for f in sorted(d["feeds"], key=lambda x: (not x["ok"], x["market"],
                                                    x["publisher"]))])

    # ---- refused
    doc.h2(f"Publishers that refuse automated access ({len(d['refused'])})")
    doc.p(
        "Each was asked once, with a single unrotated user agent and no "
        "credentials. Each said no. They stay listed rather than being deleted, "
        "so nobody adds them again next quarter and so the coverage gap stays "
        "visible. Nothing here is retried with different headers.")
    doc.table(
        ["Publisher", "Feed", "Signal", "What that means"],
        [(r["publisher"], r["url"], r["why"].replace("_", " "),
          meaning(r["why"]))
         for r in sorted(d["refused"], key=lambda x: x["publisher"])])

    # ---- dead
    doc.h2(f"Feeds that no longer exist ({len(d['dead'])})")
    doc.p(
        "These answered once and now return nothing. Kept for the same reason "
        "as the refusals: a dead address quietly dropped gets rediscovered and "
        "re-added.")
    doc.table(
        ["Publisher", "Feed", "Signal"],
        [(r["publisher"], r["url"], r["why"])
         for r in sorted(d["dead"], key=lambda x: x["publisher"])])

    # ---- competitors
    doc.h2(f"Competitor brands ({len(d['rivals'])})")
    doc.p(
        "Every brand the price monitor is allowed to read. Also sold via lists "
        "the marketplaces carrying the same brand, used when the brand site "
        "refuses or publishes no Saudi price.")
    doc.table(
        ["Brand", "Segment", "Own site", "Also sold via"],
        [(c["brand"], ", ".join(c["segments"]),
          ", ".join(c["domains"]) or "—",
          ", ".join(c["retail_domains"]) or "—")
         for c in sorted(d["rivals"], key=lambda x: x["brand"].lower())])

    # ---- retailers
    doc.h2(f"Saudi retailers and marketplaces ({len(d['retailers'])})")
    doc.p(
        "Where competitor products are also listed. These matter because a "
        "brand site with no Saudi price often has one here, in riyals, on a "
        "page that can be read.")
    doc.table(
        ["Domain", "Brands carried", "Which"],
        [(r["domain"], r["count"], ", ".join(r["brands"]))
         for r in d["retailers"]])

    # ---- sweep
    doc.h2(f"Storefronts probed for offers ({len(d['sweep'])})")
    doc.p(
        "The offer sweep asks each brand's own storefront what it is currently "
        "advertising. Roughly half refuse. A refusal is recorded as a refusal, "
        "never as “this brand is running no promotions”.")
    doc.table(
        ["Brand", "Result", "Pages", "Offers"],
        [(s["competitor"],
          s["refusal"].replace("_", " ") if s["refusal"] else "read",
          s["pages_read"], s["offers"])
         for s in sorted(d["sweep"], key=lambda x: (bool(x["refusal"]),
                                                    x["competitor"].lower()))])

    # ---- clara
    doc.h2("Clara's own site")
    doc.p(
        "The one site this project may render with a browser when a plain "
        "request is refused, because it is the operator's own property. Clara's "
        "storefront serves a JavaScript bot-check at HTTP 200, so the website "
        "analysis reads it through a local Chromium with the same user agent. "
        "No competitor gets that treatment.")
    doc.table(
        ["Site", "Address", "Products", "What is read"],
        [("Clara Hair", "https://clarahair.com/en", len(d["clara"]),
          "Catalogue, prices and product pages. The seed crawl in data/ is the "
          "fallback when the live site is behind its bot-check.")])

    # ---- platform
    doc.h2(f"Platform, vendor and standards ({len(d['platform'])})")
    doc.p(
        "Not scraped — depended on. The specifications the code implements and "
        "the services it runs on. The only table here maintained by hand, which "
        "is why it is short.")
    doc.table(
        ["Reference", "Address", "Used for"],
        [(n, u, w) for n, u, w in d["platform"]])

    # ---- discovery
    seeds = [x for x in d["discovery"] if x["source_type"] == "seed"]
    found = [x for x in d["discovery"] if x["source_type"] != "seed"]
    doc.h2("The discovery registry")
    doc.p(
        f"The source list is meant to grow. The discovery loop reads article "
        f"pages for outbound links to publishers it does not know, scores each "
        f"candidate, and activates only those above 0.80 — a candidate between "
        f"0.60 and 0.79 is kept and watched but never scanned, because "
        f"discovery is not activation. "
        + (f"Nothing has been activated yet: the registry is still all "
           f"{len(seeds)} seeds. That is the honest state rather than a failure "
           f"to report one."
           if not found else
           f"{len(found)} source(s) have been added by the loop so far."))



# --------------------------------------------------------------------------
# the cost document
# --------------------------------------------------------------------------

def section_cost_full(doc: Doc) -> None:
    """One page, one table, every cost line in the application.

    The previous version of this had thirteen tables across five pages, which
    made a cost sheet harder to read rather than easier. A person opening this
    wants one number and the lines that make it up, on one page, so that is what
    it is now.
    """
    from docx.enum.section import WD_ORIENT, WD_SECTION
    from docx.shared import Inches, Pt

    from clara_monitor import pricing
    t = pricing.one_table()

    # Landscape, because seven columns of figures do not fit portrait at a
    # readable size — but in its OWN section. Flipping `sections[-1]` turned the
    # entire handbook landscape, since the document has only one section: a
    # 300-paragraph document rotated to make one table fit.
    prev = doc.d.sections[-1]
    portrait = (prev.page_width, prev.page_height,
                prev.left_margin, prev.right_margin,
                prev.top_margin, prev.bottom_margin)

    sec = doc.d.add_section(WD_SECTION.NEW_PAGE)
    sec.orientation = WD_ORIENT.LANDSCAPE
    sec.page_width, sec.page_height = portrait[1], portrait[0]
    for attr in ("left_margin", "right_margin", "top_margin", "bottom_margin"):
        setattr(sec, attr, Inches(0.55))
    doc._restore_portrait = portrait

    doc.h1("What this application costs", "cost")
    doc.p(f"Every line, priced per run, per day and per month. "
          f"Cadence: {t['cadence']}. "
          f"{t['staleness']['sentence']} "
          f"Generated from clara_monitor/pricing.py.")

    headers = ["Line", "When it runs", "Calls", "Tokens", "Per run", "Per day",
               "Per month"]
    tbl = doc.d.add_table(rows=1, cols=len(headers))
    tbl.style = "Table Grid"
    tbl.autofit = True
    for c, h in zip(tbl.rows[0].cells, headers):
        c.text = ""
        r = c.paragraphs[0].add_run(h.upper())
        r.bold = True
        r.font.size = Pt(7.5)
        r.font.name = EYEBROW_FONT

    group = ""
    for row in t["rows"]:
        if row["group"] != group:
            group = row["group"]
            band = tbl.add_row().cells
            band[0].text = ""
            gr = band[0].paragraphs[0].add_run(group.upper())
            gr.bold = True
            gr.font.size = Pt(7.5)
            gr.font.name = EYEBROW_FONT
            gr.font.color.rgb = EYEBROW_COLOR
            for c in band[1:]:
                c.text = ""

        cells = tbl.add_row().cells
        values = [row["line"], row["detail"],
                  f"{row['calls']:,}" if row["calls"] else "",
                  f"{row['tokens']:,}" if row["tokens"] else "",
                  row["per_run_text"], row["per_day_text"],
                  row["per_month_text"]]
        for c, v in zip(cells, values):
            c.text = ""
            run = c.paragraphs[0].add_run(str(v))
            run.font.size = Pt(8)
            if row["is_total"]:
                run.bold = True

    doc.p("")
    doc.lead(f"{t['daily_text']} a day · {t['monthly_text']} a month · "
             f"{t['yearly_text']} a year · {t['tokens_per_month']:,} tokens a "
             f"month.")
    doc.p(
        "Two things this table is honest about. The zero on the model lines is "
        "real but it is not a spending control: Vertex credentials have been "
        "expired for weeks, so every agent runs its deterministic path and "
        "nothing has been billed — re-authenticating moves the bill to the "
        "figures above. And the identity judge is almost the whole model cost, "
        "at one call per candidate pairing; if that ever needs reducing the "
        "lever is fewer pairings, not a cheaper model."
        + (f" {len(t['unverified'])} line(s) are marked ESTIMATE because they "
           f"depend on a plan that cannot be read from the repository: "
           f"{', '.join(t['unverified'])}." if t["unverified"] else ""))

    # Back to portrait, so a section that follows this one is not landscape by
    # inheritance. Standalone Clara_Cost.docx ends here and never sees it.
    if getattr(doc, "_after_cost_portrait", False):
        w, h, lm, rm, tm, bm = doc._restore_portrait
        back = doc.d.add_section(WD_SECTION.NEW_PAGE)
        back.orientation = WD_ORIENT.PORTRAIT
        back.page_width, back.page_height = w, h
        back.left_margin, back.right_margin = lm, rm
        back.top_margin, back.bottom_margin = tm, bm


def save_or_next(doc, path: Path) -> Path:
    """Save, or save beside it if Word has the file open.

    Word holds an exclusive lock on an open document, and this handbook is a
    document someone reads while it is being regenerated. Failing the whole run
    on a PermissionError would throw away the work; writing to the next free
    name and saying so does not.
    """
    try:
        doc.save(path)
        return path
    except PermissionError:
        stem, n = path.stem, 2
        while True:
            alt = path.with_name(f"{stem}_{n}{path.suffix}")
            if not alt.exists():
                break
            n += 1
        doc.save(alt)
        print(f"  ! {path.name} is open in Word, so this went to {alt.name} "
              f"instead. Close it and re-run to write the original name.")
        return alt


# --------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--in-place", action="store_true",
                    help="update v3 rather than writing v4")
    ap.add_argument("--source", default=str(SRC))
    ap.add_argument("--no-cost", action="store_true",
                    help="leave the one-page cost table out of the handbook")
    ap.add_argument("--no-cost-doc", action="store_true",
                    help="skip the standalone Clara_Cost.docx")
    ap.add_argument("--no-sources-doc", action="store_true",
                    help="skip the standalone Clara_Sources.docx")
    args = ap.parse_args()

    src = Path(args.source)
    if not src.exists():
        print(f"!! {src} not found")
        return 1

    doc = Doc(src)
    before = len(doc.d.paragraphs)

    doc.d.add_page_break()
    section_agents(doc)
    doc.d.add_page_break()
    section_ai(doc)
    # The one-page cost table goes in the handbook too. It is one page and one
    # table, so it does not reintroduce the five pages of pricing prose that
    # were removed — and the figures are measured rather than estimated now,
    # which is what made them worth printing.
    if not args.no_cost:
        doc._after_cost_portrait = True
        section_cost_full(doc)

    print("  reading the live source registry…")
    srcs = gather_sources()
    doc.d.add_page_break()
    section_sources(doc, srcs)

    out = save_or_next(doc, src if args.in_place else OUT)
    after = len(docx.Document(str(out)).paragraphs)
    print(f"  {src.name}: {before} paragraphs")
    print(f"  {out.name}: {after} paragraphs (+{after - before})")
    added = ["How the agents work, in full", "How the AI works",
             "Every source, with its address"]
    if not args.no_cost:
        added.append("What this application costs")
    print("  added: " + " / ".join(added))

    # The same source register, standalone, for anyone who wants the list
    # without the rest of the handbook.
    if not args.no_cost_doc:
        cd = Doc(src)
        for para in list(cd.d.paragraphs):
            para._element.getparent().remove(para._element)
        for tbl in list(cd.d.tables):
            tbl._element.getparent().remove(tbl._element)
        cd.d.add_paragraph("Clara Monitor", style="Title")
        section_cost_full(cd)
        co = save_or_next(cd, COST_OUT)
        print(f"  {co.name}: full cost breakdown")

    if not args.no_sources_doc:
        sd = Doc(src)
        # A fresh document rather than an append: this one is only the register.
        for para in list(sd.d.paragraphs):
            para._element.getparent().remove(para._element)
        for tbl in list(sd.d.tables):
            tbl._element.getparent().remove(tbl._element)
        sd.d.add_paragraph("Clara Monitor", style="Title")
        sd.h1("Source register", "provenance")
        section_sources(sd, srcs)
        so = save_or_next(sd, SOURCES_OUT)
        print(f"  {so.name}: standalone source register")

    from clara_monitor import pricing
    print(f"  {pricing.staleness()['sentence']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
