"""Sections 6 and 7: the Competitor Intelligence Agent — read-only and grounded.

This agent answers questions about stored competitor-intelligence records. It is
narrower than it looks, and the narrowness is the requirement.

**6.2 — the exclusions are enforced, not requested.** No marketing campaigns, no
advertising, no SEO, no social media, no copywriting or content generation, no
customer acquisition. Section 12 makes it an acceptance criterion: agent answers
must contain none of that behaviour. So the check runs in two places — on the
question, so an out-of-scope request is declined before any model sees it, and on
the answer, so a model that wandered is caught on the way out. A prompt asking
nicely is not enforcement.

**6.3 — grounded, cited, and honest about gaps.** Every answer is built from rows
this database holds, each answer carries citations to those rows, and each cited
value carries its provenance so the reader can tell an automated observation from
a value a person typed. When the evidence is missing, stale, inaccessible or
conflicting, the answer says which of those it is. That distinction is the whole
value: "SAR 249, human-confirmed on 18 August" and "SAR 249, automatically
observed six weeks ago from a source that has failed nine times since" are not the
same claim.

**7 — the escalation path is the point.** An agent that cannot answer and says
something anyway is worse than useless. So when evidence is insufficient, the
answer names the gap and offers Send Request, prefilled with the conversation
summary, the citations and the missing-evidence explanation. `escalate()` is that
handoff, and it records the conversation separately from any data change an admin
later makes — section 7's last line.

**Read-only.** Nothing in this module writes to a domain table. It writes
conversations, messages and citations, and it creates Requests. It never changes
a price, a match or a source, which is why it needs no permission beyond
`AGENT_ASK`.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

from .audit import Audit, new_id, provenance_badge
from .authz import Actor, Permission, require
from .db import Db, dumps, loads
from .requests import Requests
from .schema import (ChangeType, MATCH_STATUS_LABEL, Origin, PROVENANCE_LABEL,
                     Provenance, RequestType, SourceStatus, now_iso)

# A price older than this is reported as stale rather than as current. Not a
# guess: the collection cycle runs daily, so a value untouched for two weeks has
# survived roughly fourteen chances to be re-read.
STALE_DAYS = 14

# --------------------------------------------------------------------------
# 6.2 — the exclusions
# --------------------------------------------------------------------------

# Section 6.2's exclusions, verbatim and in its order. This tuple is the
# requirement; everything below enforces it.
EXCLUSIONS = ("Marketing campaigns", "Advertising", "SEO", "Social media",
              "Copywriting or content generation", "Customer acquisition")

# One enforced pattern per exclusion, labelled with 6.2's own words, so a
# refusal names the requirement it is honouring rather than an approximation of
# it. "Marketing campaigns" used to be caught by the copywriting pattern and
# refused as "copywriting or content generation", which told the reader the
# wrong thing — and "plan a campaign around the airwrap" was not caught at all,
# because the old pattern needed a writing verb in front of a noun.
#
# Each pattern matches the *ask*, not the topic. "What does their campaign say?"
# is a legitimate question about observed evidence and stays in scope; "plan a
# campaign" does not. Verbs and possessives are what separate them, so the
# patterns are built around those rather than around keywords.
#
# Order matters: the first match wins, so the more specific exclusions come
# before the general ones.
OUT_OF_SCOPE = (
    # --- 1. Marketing campaigns ---
    (re.compile(
        r"(?:\b(?:write|draft|generate|create|compose|produce|make|build|plan|"
        r"design|give me|suggest|propose|come up with|brainstorm|recommend|"
        r"ideas? for|help (?:me|us) with)\b[^.?!]{0,50}"
        r"\b(?:campaign|promo(?:tion)?s?|marketing|go.to.market|launch plan|"
        r"positioning|messaging|brand strategy)\b"
        r"|\b(?:marketing|promotional|ad(?:vertising)?|launch|seasonal)\s+"
        r"campaign\b"
        r"|\bcampaign\s+(?:for|around|about|plan|calendar|idea)"
        r"|\bour\s+(?:marketing|campaign|promotion)\b"
        r"|\bhow (?:should|do|can) (?:we|i|clara)\b[^.?!]{0,40}"
        r"\b(?:market|promote|advertise|position|respond commercially)\b)",
        re.I),
     "marketing campaigns",
     "Marketing campaigns are outside this module. This agent explains stored "
     "competitor evidence — prices, matches, offers as written, availability, "
     "provenance and freshness — and does not plan what Clara should do about "
     "it."),

    # --- 2. Advertising ---
    (re.compile(r"\b(?:ad ?spend|ad ?budget|media buy(?:ing)?|ppc|"
                r"google ads|meta ads|tiktok ads|paid (?:search|social|media|"
                r"ads?)|cpc|cpm|roas|bid (?:strategy|cap)|"
                r"advertis\w+ (?:budget|strategy|copy|plan|spend|creative))\b",
                re.I),
     "advertising",
     "Advertising planning, budgets and buying are outside this module."),

    # --- 3. SEO ---
    (re.compile(r"\b(?:seo|search engine optimi[sz]\w*|keyword research|"
                r"keyword strategy|backlink\w*|link building|serp|"
                r"rank(?:ing)? (?:higher|better|above|on google)|"
                r"outrank|meta description for|title tag for|"
                r"schema markup for|sitemap for|canonical\w* for)\b", re.I),
     "SEO",
     "Search optimisation is outside this module. It reports what competitors "
     "publish; it does not advise on how to rank against them."),

    # --- 4. Social media ---
    (re.compile(r"\b(?:instagram|tiktok|snapchat|twitter|x\.com|facebook|"
                r"youtube|pinterest|linkedin|whatsapp status|influencer\w*|"
                r"hashtag\w*|ugc|creator brief|"
                r"social (?:media|post|strategy|calendar|content))\b", re.I),
     "social media",
     "Social media planning is outside this module. Competitor evidence here "
     "comes from their own pages and approved sources."),

    # --- 5. Copywriting or content generation ---
    (re.compile(r"\b(?:write|draft|generate|create|compose|produce|"
                r"give me|suggest|come up with|brainstorm|rewrite|reword|"
                r"ideas? for)\b[^.?!]{0,40}"
                r"\b(?:caption|copy|headline|tagline|slogan|ad|advert\w*|"
                r"post|tweet|reel|story|content|blog|article|newsletter|"
                r"email|script|hook|product description|landing page|"
                r"press release)\b", re.I),
     "copywriting or content generation",
     "Writing copy, captions, posts, descriptions or other content is outside "
     "what this agent does."),

    # --- 6. Customer acquisition ---
    (re.compile(r"\b(?:customer acquisition|acquire (?:new )?customers|"
                r"lead gen\w*|sales funnel|funnel|"
                r"conversion rate optimi[sz]\w*|cro\b|growth (?:strategy|"
                r"hack\w*|loop)|retention (?:strategy|plan)|"
                r"loyalty programme?|referral programme?|"
                r"customer journey|cac\b|ltv\b)", re.I),
     "customer acquisition",
     "Acquisition, funnels and retention programmes are outside this module. "
     "The addendum removes them from Competitor Intelligence deliberately, so "
     "that what this agent says can be traced to a stored observation."),
)

# Which pattern enforces which of 6.2's six. Asserted by the test suite, so an
# exclusion cannot be listed on screen without something actually refusing it.
EXCLUSION_ENFORCED_AS = {
    "Marketing campaigns": "marketing campaigns",
    "Advertising": "advertising",
    "SEO": "SEO",
    "Social media": "social media",
    "Copywriting or content generation": "copywriting or content generation",
    "Customer acquisition": "customer acquisition",
}

# The label each pattern refuses under, for a panel that lists them.
OUT_OF_SCOPE_LABELS = tuple(label for _p, label, _m in OUT_OF_SCOPE)

# What it CAN do (6.1), shown when a question is declined, so the decline is
# useful rather than merely a refusal.
IN_SCOPE = (
    "explain a competitor product and how it is matched to a Clara product",
    "explain a price, a price difference, an offer, availability, and the "
    "history of what was observed and when",
    "identify where a value came from, whether the source is readable, how "
    "fresh it is and when it was last checked",
    "explain match confidence, who confirmed it, which values were entered by "
    "hand, and what is still open as an Action",
    "answer what is unresolved, what data is missing, and what needs verifying",
)


def scope_check(text: str) -> dict:
    """Whether a question or an answer is inside 6.1 and clear of 6.2.

    Run on the way in and on the way out. Running it on the answer as well is
    what makes section 12's criterion testable: the agent cannot produce
    marketing content even if a model tries to, because the reply is inspected
    before it is stored or shown.
    """
    for pattern, label, message in OUT_OF_SCOPE:
        m = pattern.search(text or "")
        if m:
            return {"ok": False, "excluded": label, "matched": m.group(0),
                    "message": message}
    return {"ok": True, "excluded": "", "matched": "", "message": ""}


# --------------------------------------------------------------------------
# freshness and conflict
# --------------------------------------------------------------------------

def _age_days(iso: str | None) -> float | None:
    if not iso:
        return None
    try:
        t = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
    except ValueError:
        return None
    if t.tzinfo is None:
        t = t.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - t).total_seconds() / 86400.0


def freshness(iso: str | None) -> dict:
    """How much weight a value's age allows. Stated, never assumed."""
    d = _age_days(iso)
    if d is None:
        return {"state": "unknown", "days": None,
                "why": "no observation date is recorded, so its age cannot be "
                       "established"}
    if d <= 2:
        return {"state": "fresh", "days": round(d, 1),
                "why": "observed within the last two days"}
    if d <= STALE_DAYS:
        return {"state": "recent", "days": round(d, 1),
                "why": f"observed {round(d)} day(s) ago"}
    return {"state": "stale", "days": round(d, 1),
            "why": f"last observed {round(d)} day(s) ago, past the {STALE_DAYS}-"
                   f"day window, so it should be treated as historical rather "
                   f"than current"}


class Answer:
    """One reply: text, citations, gaps, and whether it should be escalated."""

    def __init__(self):
        self.parts: list = []
        self.citations: list = []
        self.gaps: list = []
        self.declined = ""
        self.decision_source = "deterministic_rules"

    def say(self, text: str) -> "Answer":
        if text:
            self.parts.append(text)
        return self

    def cite(self, kind: str, record_id: str, label: str, *, url: str = "",
             provenance: str = "", observed_at: str = "") -> "Answer":
        self.citations.append({
            "record_kind": kind, "record_id": record_id, "label": label,
            "url": url, "provenance": provenance, "observed_at": observed_at,
            "provenance_badge": provenance_badge(provenance) if provenance
            else None,
        })
        return self

    def gap(self, what: str, why: str, suggest: str = "") -> "Answer":
        self.gaps.append({"what": what, "why": why, "suggest": suggest})
        return self

    @property
    def text(self) -> str:
        return "\n\n".join(self.parts)

    @property
    def needs_human(self) -> bool:
        return bool(self.gaps)

    def to_dict(self) -> dict:
        return {"text": self.text, "citations": self.citations,
                "gaps": self.gaps, "declined": self.declined,
                "needs_human": self.needs_human,
                "decision_source": self.decision_source,
                "in_scope": IN_SCOPE}


class IntelligenceAgent:
    """Read-only, grounded, scope-limited, and able to hand over to a person."""

    name = "competitor_intelligence_agent"

    def __init__(self, db: Db, *, llm=None):
        self.db = db
        self.llm = llm
        self.audit = Audit(db)
        self.requests = Requests(db)

    # ------------------------------------------------------------------
    # conversations
    # ------------------------------------------------------------------

    def start(self, actor: Actor, *, context_kind: str = "",
              context_id: str = "", title: str = "") -> str:
        require(actor, Permission.AGENT_ASK)
        cid = new_id("cv")
        with self.db.tx():
            self.db.exec(
                "INSERT INTO ops_conversation (conversation_id,username,"
                "context_kind,context_id,started_at,last_at,title) "
                "VALUES (?,?,?,?,?,?,?)",
                (cid, actor.username, context_kind or None, context_id or None,
                 now_iso(), now_iso(), title or None))
        return cid

    def ask(self, conversation_id: str, question: str, actor: Actor, *,
            context_kind: str = "", context_id: str = "") -> dict:
        """Answer from stored records. Declines out of scope before answering."""
        require(actor, Permission.AGENT_ASK)

        gate = scope_check(question)
        ans = Answer()
        if not gate["ok"]:
            ans.declined = gate["excluded"]
            ans.say(gate["message"])
            ans.say("What this agent does cover:\n"
                    + "\n".join(f"• {s}" for s in IN_SCOPE))
        else:
            ans = self._answer(question, context_kind, context_id)
            # 6.2 again, on the way out. A model that drifted is caught here.
            out = scope_check(ans.text)
            if not out["ok"]:
                ans = Answer()
                ans.declined = out["excluded"]
                ans.say("The answer this agent produced strayed outside its "
                        "scope (" + out["excluded"] + "), so it has been "
                        "withheld rather than shown. Ask about the stored "
                        "competitor records instead — prices, matches, offers, "
                        "sources, freshness or open actions.")

        with self.db.tx():
            self.db.exec(
                "INSERT INTO ops_message (message_id,conversation_id,at,role,"
                "body,grounded,gaps,decision_source) VALUES (?,?,?,?,?,?,?,?)",
                (new_id("ms"), conversation_id, now_iso(), "user", question,
                 1, None, None))
            mid = new_id("ms")
            self.db.exec(
                "INSERT INTO ops_message (message_id,conversation_id,at,role,"
                "body,grounded,gaps,decision_source) VALUES (?,?,?,?,?,?,?,?)",
                (mid, conversation_id, now_iso(), "agent", ans.text,
                 1 if ans.citations else 0, dumps(ans.gaps),
                 ans.decision_source))
            for c in ans.citations:
                self.db.exec(
                    "INSERT INTO ops_citation (citation_id,message_id,"
                    "record_kind,record_id,label,url,provenance,observed_at) "
                    "VALUES (?,?,?,?,?,?,?,?)",
                    (new_id("ct"), mid, c["record_kind"], c["record_id"],
                     c["label"], c.get("url") or None,
                     c.get("provenance") or None,
                     c.get("observed_at") or None))
            self.db.exec("UPDATE ops_conversation SET last_at=?, title=COALESCE("
                         "title,?) WHERE conversation_id=?",
                         (now_iso(), question[:80], conversation_id))

        out = ans.to_dict()
        out["message_id"] = mid
        out["conversation_id"] = conversation_id
        return out

    # ------------------------------------------------------------------
    # 6.1 — answering from records
    # ------------------------------------------------------------------

    def _answer(self, q: str, context_kind: str, context_id: str) -> Answer:
        """Route the question to the records that can answer it.

        Deterministic routing on purpose. A model would classify intent better,
        but the platform must work with Vertex unreachable, and an agent whose
        answers depend on model availability cannot be relied on for an audit
        question.
        """
        low = (q or "").lower()

        # The record in front of the user answers first. 6.3 requires inheriting
        # the current page context, and the common case is a question about the
        # thing already on screen.
        if context_kind == "match" and context_id:
            return self._on_match(context_id, low)
        if context_kind == "competitor" and context_id:
            return self._on_competitor(context_id, low)
        if context_kind == "product" and context_id:
            return self._on_product(context_id, low)
        if context_kind == "action" and context_id:
            return self._on_action(context_id, low)

        if re.search(r"\b(?:unresolved|open|outstanding|pending|to ?do|queue|"
                     r"needs? (?:attention|work)|ambiguous)\b", low):
            return self._on_open_work()
        if re.search(r"\b(?:stale|fresh|old|last (?:checked|updated|observed)|"
                     r"how current|out of date)\b", low):
            return self._on_freshness()
        if re.search(r"\b(?:source|readable|unreadable|blocked|captcha|403|"
                     r"provenance|where did|came from)\b", low):
            return self._on_sources()
        if re.search(r"\b(?:missing|no data|gap|not collected|absent)\b", low):
            return self._on_missing()

        named = self._find_competitor(low)
        if named:
            return self._on_competitor(named, low)
        return self._overview(low)

    def _on_match(self, match_id: str, low: str) -> Answer:
        a = Answer()
        m = self.db.row("SELECT * FROM ops_match WHERE match_id=?", (match_id,))
        if not m:
            return a.gap("the match record",
                         f"no match with id {match_id} is stored",
                         "check the link, or send a request to have it looked at")

        pb = provenance_badge(m.get("provenance"))
        a.say(f"{m.get('clara_product_name') or m['clara_product_id']} is matched "
              f"to {m.get('competitor_product_name') or 'a product'} at "
              f"{m['competitor_key']}. The match is "
              f"{MATCH_STATUS_LABEL.get(m['status'], m['status']).lower()}"
              + (f", confidence {m['confidence']}" if m.get("confidence") else "")
              + f", and that status is {pb['label'].lower()} — {pb['definition']}")
        if m.get("confirmed_by"):
            a.say(f"{m['confirmed_by']} confirmed it on {m.get('confirmed_at')}"
                  + (f", noting: {m['note']}" if m.get("note") else "."))
        a.cite("match", match_id,
               f"match {m.get('clara_product_name')} ↔ {m['competitor_key']}",
               url=m.get("competitor_url") or "",
               provenance=m.get("provenance") or "")

        obs = self.audit.observations(match_id=match_id, limit=6)
        if not obs:
            a.gap("any price or availability observation for this match",
                  "the match exists but nothing has been observed against it, "
                  "so there is no price to report",
                  "request manual verification, or enter the value by hand from "
                  "the action queue")
        else:
            cur = obs[0]
            fr = freshness(cur.get("observed_at"))
            b = provenance_badge(cur.get("provenance"))
            a.say(f"The current value is "
                  f"{cur.get('price') or 'no price'} "
                  f"{cur.get('currency') or ''}".strip()
                  + f", {b['label'].lower()}, and {fr['why']}."
                  + (f" Availability: {cur['availability']}."
                     if cur.get("availability") else "")
                  + (f" Offer wording read on the page: “{cur['offer_wording']}”."
                     if cur.get("offer_wording") else ""))
            a.cite("observation", cur["obs_id"],
                   f"{cur.get('price')} {cur.get('currency')} observed "
                   f"{cur.get('observed_at')}",
                   url=cur.get("source_url") or "",
                   provenance=cur.get("provenance") or "",
                   observed_at=cur.get("observed_at") or "")
            if fr["state"] == "stale":
                a.gap("a current price",
                      f"the newest observation is {fr['days']} days old, which "
                      f"is past the {STALE_DAYS}-day window",
                      "request verification so the value is re-read")
            superseded = [o for o in obs if o.get("superseded")]
            if superseded:
                a.say(f"{len(superseded)} earlier observation(s) were superseded "
                      f"rather than deleted, so the history is intact: "
                      + "; ".join(
                          f"{o.get('price')} {o.get('currency')} "
                          f"({provenance_badge(o.get('provenance'))['label'].lower()}, "
                          f"{o.get('observed_at')})" for o in superseded[:3]))
            self._flag_conflict(a, obs)

        self._append_open_actions(a, match_id=match_id)
        return a

    def _on_competitor(self, key: str, low: str) -> Answer:
        a = Answer()
        c = self.db.row("SELECT * FROM ops_competitor WHERE competitor_key=?",
                        (key,))
        matches = self.db.rows(
            "SELECT * FROM ops_match WHERE competitor_key=? ORDER BY status",
            (key,))
        name = (c or {}).get("brand") or key

        if not matches:
            a.say(f"{name} is registered but no Clara product is currently "
                  f"matched to it, so there is nothing to compare.")
            a.gap(f"any match for {name}",
                  "no counterpart product has been assigned",
                  "send a request to have a counterpart identified")
        else:
            by_status: dict = {}
            for m in matches:
                by_status.setdefault(m["status"], []).append(m)
            a.say(f"{name} has {len(matches)} match(es): "
                  + ", ".join(f"{len(v)} "
                              f"{MATCH_STATUS_LABEL.get(k, k).lower()}"
                              for k, v in sorted(by_status.items())) + ".")
            for m in matches[:5]:
                a.cite("match", m["match_id"],
                       f"{m.get('clara_product_name')} ↔ "
                       f"{m.get('competitor_product_name') or 'unnamed'}",
                       url=m.get("competitor_url") or "",
                       provenance=m.get("provenance") or "")

        obs = self.audit.observations(competitor_key=key,
                                      include_superseded=False, limit=8)
        if obs:
            currencies = {o.get("currency") for o in obs if o.get("currency")}
            a.say("Most recent observed values: "
                  + "; ".join(
                      f"{o.get('price')} {o.get('currency')} "
                      f"({provenance_badge(o.get('provenance'))['label'].lower()}, "
                      f"{freshness(o.get('observed_at'))['state']})"
                      for o in obs[:4]) + ".")
            if len(currencies) > 1:
                # Section 10: cross-currency stays visible and explicitly
                # non-comparable. The agent must not do the arithmetic either.
                a.say(f"These are in {len(currencies)} different currencies "
                      f"({', '.join(sorted(c for c in currencies if c))}). They "
                      f"are shown as observed and are not comparable with each "
                      f"other or with Clara's SAR prices: no conversion policy "
                      f"has been approved, so no conversion is applied.")
            for o in obs[:4]:
                a.cite("observation", o["obs_id"],
                       f"{o.get('price')} {o.get('currency')} "
                       f"on {o.get('observed_at')}",
                       url=o.get("source_url") or "",
                       provenance=o.get("provenance") or "",
                       observed_at=o.get("observed_at") or "")
        else:
            a.gap(f"observed prices for {name}",
                  "no current observation is stored for this competitor",
                  "request verification, or enter a value by hand")

        srcs = self.db.rows("SELECT * FROM ops_source WHERE competitor_key=?",
                            (key,))
        bad = [s for s in srcs
               if s["status"] in (SourceStatus.UNREADABLE,
                                  SourceStatus.UNAVAILABLE)]
        if bad:
            a.say(f"{len(bad)} of {len(srcs)} source(s) for {name} cannot "
                  f"currently be read: "
                  + "; ".join(f"{s['url']} — {s.get('status_reason') or s['status']}"
                              for s in bad[:3])
                  + ". Anything those pages would have said is absent from the "
                    "figures above; it is not recorded as a competitor without "
                    "that information.")
            for s in bad[:3]:
                a.cite("source", s["source_id"], s["url"], url=s["url"],
                       provenance=Provenance.OBSERVED)
        self._append_open_actions(a, competitor_key=key)
        return a

    def _on_product(self, product_id: str, low: str) -> Answer:
        a = Answer()
        matches = self.db.rows(
            "SELECT * FROM ops_match WHERE clara_product_id=?", (product_id,))
        if not matches:
            a.gap("any competitor match for this product",
                  "no competitor has been assigned to it yet",
                  "send a request to have competitors assigned")
            return a
        name = matches[0].get("clara_product_name") or product_id
        a.say(f"{name} is compared against {len(matches)} competitor(s): "
              + ", ".join(sorted({m["competitor_key"] for m in matches})) + ".")
        for m in matches:
            obs = self.audit.observations(match_id=m["match_id"],
                                          include_superseded=False, limit=1)
            o = obs[0] if obs else None
            if o:
                fr = freshness(o.get("observed_at"))
                a.say(f"{m['competitor_key']}: {o.get('price')} "
                      f"{o.get('currency')} — "
                      f"{provenance_badge(o.get('provenance'))['label'].lower()}, "
                      f"{fr['why']}. Match is "
                      f"{MATCH_STATUS_LABEL.get(m['status'], m['status']).lower()}.")
                a.cite("observation", o["obs_id"],
                       f"{m['competitor_key']} {o.get('price')} "
                       f"{o.get('currency')}",
                       url=o.get("source_url") or "",
                       provenance=o.get("provenance") or "",
                       observed_at=o.get("observed_at") or "")
            else:
                a.say(f"{m['competitor_key']}: no price observed.")
                a.gap(f"a price for {m['competitor_key']}",
                      "the match exists but nothing has been observed",
                      "request verification for this competitor")
            a.cite("match", m["match_id"],
                   f"match against {m['competitor_key']}",
                   provenance=m.get("provenance") or "")
        self._append_open_actions(a, clara_product_id=product_id)
        return a

    def _on_action(self, action_id: str, low: str) -> Answer:
        a = Answer()
        r = self.db.row("SELECT * FROM ops_action WHERE action_id=?",
                        (action_id,))
        if not r:
            return a.gap("the action record", f"no action with id {action_id}")
        a.say(f"This is a {r['action_type'].replace('_', ' ')} action, "
              f"currently {r['status'].replace('_', ' ')}. Reason: "
              f"{r.get('reason')}."
              + (f" Last attempt {r.get('last_attempt_at')}"
                 f"{', which failed: ' + r['failure_reason'] if r.get('failure_reason') else ''}."
                 if r.get("last_attempt_at") else ""))
        a.cite("action", action_id, r.get("reason") or "action")
        if r.get("match_id"):
            sub = self._on_match(r["match_id"], low)
            a.parts += sub.parts
            a.citations += sub.citations
            a.gaps += sub.gaps
        return a

    def _on_open_work(self) -> Answer:
        a = Answer()
        rows = self.db.rows(
            "SELECT action_type, status, COUNT(*) AS n FROM ops_action "
            "WHERE status IN ('open','in_progress','waiting') "
            "GROUP BY action_type, status")
        if not rows:
            a.say("Nothing is waiting on a person. Every action raised so far "
                  "has been resolved or dismissed.")
            return a
        total = sum(r["n"] for r in rows)
        a.say(f"{total} action(s) are still open: "
              + "; ".join(f"{r['n']} {r['action_type'].replace('_',' ')} "
                          f"({r['status'].replace('_',' ')})" for r in rows) + ".")
        for r in self.db.rows(
                "SELECT action_id, action_type, reason, competitor_key, "
                "clara_product_name FROM ops_action "
                "WHERE status IN ('open','in_progress','waiting') "
                "ORDER BY CASE priority WHEN 'high' THEN 0 WHEN 'medium' THEN 1 "
                "ELSE 2 END, created_at LIMIT 6"):
            a.cite("action", r["action_id"],
                   f"{r['action_type'].replace('_',' ')}: "
                   f"{(r.get('reason') or '')[:70]}")
        return a

    def _on_freshness(self) -> Answer:
        a = Answer()
        rows = self.audit.observations(include_superseded=False, limit=400)
        if not rows:
            return a.gap("any observation at all",
                         "nothing has been collected into the operational "
                         "database yet",
                         "run a collection and import it, or enter values by hand")
        buckets: dict = {"fresh": 0, "recent": 0, "stale": 0, "unknown": 0}
        stale_rows = []
        for o in rows:
            f = freshness(o.get("observed_at"))
            buckets[f["state"]] += 1
            if f["state"] == "stale":
                stale_rows.append((o, f))
        a.say(f"Of {len(rows)} current observation(s): {buckets['fresh']} "
              f"observed in the last two days, {buckets['recent']} within "
              f"{STALE_DAYS} days, {buckets['stale']} older than that, and "
              f"{buckets['unknown']} with no recorded date.")
        if stale_rows:
            a.say("The oldest are: " + "; ".join(
                f"{o.get('competitor_key')} {o.get('price')} "
                f"{o.get('currency')} ({f['days']} days)"
                for o, f in sorted(stale_rows, key=lambda t: -(t[1]['days'] or 0))[:4]))
            for o, _ in stale_rows[:4]:
                a.cite("observation", o["obs_id"],
                       f"{o.get('competitor_key')} {o.get('price')} "
                       f"{o.get('currency')}",
                       url=o.get("source_url") or "",
                       provenance=o.get("provenance") or "",
                       observed_at=o.get("observed_at") or "")
            a.gap(f"current values for {len(stale_rows)} observation(s)",
                  f"each is older than the {STALE_DAYS}-day window, so they "
                  f"describe what was true, not what is",
                  "request verification for the ones that matter")
        return a

    def _on_sources(self) -> Answer:
        a = Answer()
        rows = self.db.rows("SELECT * FROM ops_source ORDER BY status, url")
        if not rows:
            return a.gap("any source record",
                         "no sources have been registered yet")
        by = {}
        for s in rows:
            by.setdefault(s["status"], []).append(s)
            a_ = None
        a.say(f"{len(rows)} source(s) are registered: "
              + "; ".join(f"{len(v)} {k.replace('_',' ')}"
                          for k, v in sorted(by.items())) + ".")
        broken = (by.get(SourceStatus.UNREADABLE, []) +
                  by.get(SourceStatus.UNAVAILABLE, []))
        if broken:
            a.say("Cannot be read at present: " + "; ".join(
                f"{s['url']} — {s.get('status_reason') or s['status']}"
                for s in broken[:5])
                + ". Values those pages would supply are missing from the "
                  "figures, and are reported as missing rather than as zero or "
                  "as an absence at the competitor.")
            for s in broken[:5]:
                a.cite("source", s["source_id"], s["url"], url=s["url"])
            a.gap(f"readable sources for {len(broken)} URL(s)",
                  "each has failed or been marked unavailable",
                  "supply an alternative source, or record the value by hand")
        feeds = self.db.rows("SELECT * FROM ops_feed")
        if feeds:
            ok = sum(1 for f in feeds if f.get("is_approved"))
            a.say(f"{len(feeds)} feed/API integration(s) registered, {ok} "
                  f"approved. Only approved integrations may supply values, "
                  f"because the provenance label would otherwise claim an "
                  f"approval that does not exist.")
        return a

    def _on_missing(self) -> Answer:
        a = Answer()
        no_obs = self.db.rows(
            "SELECT m.* FROM ops_match m WHERE NOT EXISTS "
            "(SELECT 1 FROM ops_observation o WHERE o.match_id=m.match_id "
            "AND o.superseded_by IS NULL)")
        amb = self.db.value(
            "SELECT COUNT(*) FROM ops_match WHERE status=?", ("ambiguous",), 0)
        a.say(f"{len(no_obs)} match(es) have no current observation, and {amb} "
              f"match(es) are still ambiguous.")
        for m in no_obs[:6]:
            a.cite("match", m["match_id"],
                   f"{m.get('clara_product_name')} ↔ {m['competitor_key']} — "
                   f"no price observed",
                   provenance=m.get("provenance") or "")
        if no_obs:
            a.gap(f"prices for {len(no_obs)} match(es)",
                  "the match exists but nothing has ever been observed against "
                  "it, so the comparison is blank rather than equal",
                  "request verification, or enter the values by hand")
        return a

    def _overview(self, low: str) -> Answer:
        a = Answer()
        counts = {
            "competitors": self.db.value(
                "SELECT COUNT(*) FROM ops_competitor", (), 0),
            "matches": self.db.value("SELECT COUNT(*) FROM ops_match", (), 0),
            "confirmed": self.db.value(
                "SELECT COUNT(*) FROM ops_match WHERE status=?",
                ("confirmed",), 0),
            "observations": self.db.value(
                "SELECT COUNT(*) FROM ops_observation "
                "WHERE superseded_by IS NULL", (), 0),
            "actions": self.db.value(
                "SELECT COUNT(*) FROM ops_action WHERE status IN "
                "('open','in_progress','waiting')", (), 0),
        }
        if not any(counts.values()):
            a.gap("any operational record",
                  "the operational database is empty — no competitors, matches "
                  "or observations have been imported yet",
                  "import a completed collection run, then ask again")
            a.say("There is nothing stored for me to answer from yet. I only "
                  "answer from records this database holds, so rather than "
                  "describe what is probably true, I am telling you it is empty.")
            return a
        a.say(f"Stored: {counts['competitors']} competitor(s), "
              f"{counts['matches']} match(es) of which {counts['confirmed']} are "
              f"confirmed, {counts['observations']} current observation(s), and "
              f"{counts['actions']} open action(s).")
        a.say("Ask about a specific competitor, product, match, price, source, "
              "or what is still open, and I will answer from those records with "
              "citations. What I cannot do is anything in section 6.2 — "
              "campaigns, advertising, SEO, social, copywriting or acquisition.")
        return a

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------

    def _flag_conflict(self, a: Answer, obs: list) -> None:
        """6.3: say when the evidence conflicts, rather than picking a side.

        Two unsuperseded observations for the same match with different prices is
        a conflict, not a value. Reporting the newer one silently would hide the
        disagreement, and the disagreement is usually the thing worth acting on.
        """
        live = [o for o in obs if not o.get("superseded")]
        prices = {(o.get("price"), o.get("currency")) for o in live
                  if o.get("price")}
        if len(prices) > 1:
            a.say("The evidence conflicts: "
                  + "; ".join(
                      f"{o.get('price')} {o.get('currency')} "
                      f"({provenance_badge(o.get('provenance'))['label'].lower()}, "
                      f"{o.get('observed_at')})" for o in live[:4])
                  + ". Two current observations disagree and neither supersedes "
                    "the other, so I am not choosing between them.")
            a.gap("agreement between current observations",
                  "more than one live observation exists with a different price",
                  "have someone confirm which is correct; the confirmation will "
                  "supersede the other")

    def _append_open_actions(self, a: Answer, **filters) -> None:
        where = [f"{k}=?" for k, v in filters.items() if v]
        args = [v for v in filters.values() if v]
        if not where:
            return
        rows = self.db.rows(
            "SELECT action_id, action_type, reason, status FROM ops_action "
            "WHERE status IN ('open','in_progress','waiting') AND "
            + " AND ".join(where) + " ORDER BY created_at", args)
        if not rows:
            return
        a.say(f"{len(rows)} action(s) are still open on this: "
              + "; ".join(f"{r['action_type'].replace('_',' ')} "
                          f"({r['status'].replace('_',' ')})" for r in rows) + ".")
        for r in rows[:4]:
            a.cite("action", r["action_id"],
                   f"{r['action_type'].replace('_',' ')}: "
                   f"{(r.get('reason') or '')[:60]}")

    def _find_competitor(self, low: str) -> str:
        for r in self.db.rows(
                "SELECT competitor_key, brand FROM ops_competitor"):
            for cand in (r.get("brand") or "", r["competitor_key"]):
                if cand and len(cand) > 2 and cand.lower() in low:
                    return r["competitor_key"]
        return ""

    # ------------------------------------------------------------------
    # section 7 — escalation
    # ------------------------------------------------------------------

    def escalate(self, conversation_id: str, actor: Actor, *,
                 request_type: str = "", subject: str = "",
                 extra: str = "") -> str:
        """Turn a conversation into a Request, carrying what it could not answer.

        Section 12 requires the Request to contain the summary, the citations and
        the missing-evidence explanation. All three are assembled from the stored
        conversation rather than retyped, because retyping is where the citation
        that made the question answerable gets lost.
        """
        require(actor, Permission.AGENT_ESCALATE)
        conv = self.db.row(
            "SELECT * FROM ops_conversation WHERE conversation_id=?",
            (conversation_id,))
        if not conv:
            raise KeyError("no such conversation")
        if conv["username"] != actor.username and not actor.is_admin:
            require(actor, Permission.REQUEST_ADMIN,
                    "this conversation belongs to another user")

        msgs = self.db.rows(
            "SELECT * FROM ops_message WHERE conversation_id=? ORDER BY at ASC",
            (conversation_id,))
        cites = self.db.rows(
            "SELECT c.* FROM ops_citation c JOIN ops_message m "
            "ON m.message_id=c.message_id WHERE m.conversation_id=? "
            "ORDER BY c.citation_id", (conversation_id,))
        gaps = []
        for m in msgs:
            gaps += loads(m.get("gaps"), []) or []

        transcript = "\n".join(
            f"{'You' if m['role'] == 'user' else 'Agent'}: {m['body']}"
            for m in msgs)
        gap_text = ("\n".join(
            f"• {g['what']} — {g['why']}"
            + (f" (suggested: {g['suggest']})" if g.get("suggest") else "")
            for g in gaps) or "• the agent did not record a specific gap")
        cite_text = ("\n".join(
            f"• {c['record_kind']} {c['record_id']}: {c.get('label') or ''}"
            + (f" — {c['url']}" if c.get("url") else "")
            + (f" [{PROVENANCE_LABEL.get(c.get('provenance'), '')}]"
               if c.get("provenance") else "")
            for c in cites[:12]) or "• the agent had no records to cite")

        description = (
            "Escalated from an agent conversation because the stored evidence "
            "was not sufficient to answer.\n\n"
            f"WHAT IS MISSING\n{gap_text}\n\n"
            f"RECORDS THE AGENT CITED\n{cite_text}\n\n"
            f"CONVERSATION\n{transcript[:4000]}"
            + (f"\n\nADDED BY THE REQUESTER\n{extra.strip()}"
               if extra.strip() else ""))

        first_q = next((m["body"] for m in msgs if m["role"] == "user"), "")
        ctx = {"kind": "conversation", "conversation_id": conversation_id,
               "gaps": gaps,
               "citations": [{k: c.get(k) for k in
                              ("record_kind", "record_id", "label", "url",
                               "provenance")} for c in cites[:12]]}
        if conv.get("context_kind") and conv.get("context_id"):
            ctx[f"{conv['context_kind']}_id"] = conv["context_id"]
            ctx["kind"] = conv["context_kind"]
        for c in cites:
            if c["record_kind"] == "match" and not ctx.get("match_id"):
                ctx["match_id"] = c["record_id"]
            if c["record_kind"] == "action" and not ctx.get("action_id"):
                ctx["action_id"] = c["record_id"]

        rid = self.requests.create(
            request_type=request_type or RequestType.MANUAL_VERIFICATION,
            subject=(subject or f"Agent could not answer: {first_q[:70]}"),
            description=description, actor=actor, context=ctx,
            conversation_id=conversation_id,
            action_id=ctx.get("action_id", ""), origin=Origin.AGENT)

        with self.db.tx():
            self.audit.record(
                actor=actor.username, actor_role=actor.role,
                change_type=ChangeType.CONVERSATION_ESCALATED,
                origin=Origin.AGENT,
                after={"request_id": rid, "gaps": len(gaps),
                       "citations": len(cites)},
                request_id=rid, match_id=ctx.get("match_id", ""),
                action_id=ctx.get("action_id", ""),
                note="agent conversation escalated to a request")
        return rid

    # ------------------------------------------------------------------
    # reading conversations
    # ------------------------------------------------------------------

    def conversation(self, conversation_id: str, actor: Actor) -> dict | None:
        conv = self.db.row(
            "SELECT * FROM ops_conversation WHERE conversation_id=?",
            (conversation_id,))
        if not conv:
            return None
        if conv["username"] != actor.username and not actor.is_admin:
            require(actor, Permission.REQUEST_ADMIN,
                    "this conversation belongs to another user")
        msgs = self.db.rows(
            "SELECT * FROM ops_message WHERE conversation_id=? ORDER BY at ASC",
            (conversation_id,))
        for m in msgs:
            m["gaps"] = loads(m.get("gaps"), [])
            m["citations"] = self.db.rows(
                "SELECT * FROM ops_citation WHERE message_id=?",
                (m["message_id"],))
            for c in m["citations"]:
                c["provenance_badge"] = (provenance_badge(c["provenance"])
                                         if c.get("provenance") else None)
        conv["messages"] = msgs
        conv["request"] = self.db.row(
            "SELECT request_id, subject, status FROM ops_request "
            "WHERE conversation_id=?", (conversation_id,))
        return conv
