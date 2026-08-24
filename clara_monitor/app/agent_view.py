"""The Competitor Intelligence Agent panel (3.1, 6, 7).

Section 3.1 is specific about the shape: "a persistent header control opening a
right-side panel so it can inherit the current record context". It is not a tab
and not a page. That matters — an agent on its own page has to be told what you
were looking at, and being told is where the context gets lost. A panel that
opens over the product you are reading already knows.

So this renders into the shell on every page, and the conversation carries the
record it was opened from: ask "why is this price stale?" while a product is on
screen and the question resolves against that product.

**The panel does not answer anything itself.** Every word comes from
`ops.agent.IntelligenceAgent`, which reads stored records, cites them, states
what is missing, and refuses anything in 6.2 — marketing, advertising, SEO,
social media, copywriting, customer acquisition. This module renders the answer,
the citations with their provenance, and the gaps. It has no access to a
generative path around the scope check, which is what makes section 12's
"no marketing behaviour" criterion structural rather than a matter of prompting.

**A gap ends in an escalation, not an apology.** Section 6.3 says the agent must
offer Send Request when human investigation is required and must not pretend the
question has been resolved. So whenever the answer records a gap, the escalate
form is shown right there, and it carries the conversation summary, the citations
and the missing-evidence explanation into the Request (7, and section 12's sixth
criterion).
"""

from __future__ import annotations

import urllib.parse

from ..ops import REQUEST_TYPE_LABEL, RequestType
from ..ops.agent import EXCLUSIONS, IN_SCOPE
from .shell import e, ff, prov, when

# Questions worth one click, chosen to be answerable from stored records. Each
# is phrased the way `_answer` routes, so a first-time reader gets a real answer
# rather than a shrug that teaches them the panel is useless.
STARTERS_GLOBAL = [
    "What needs a person right now?",
    "How fresh is the price evidence?",
    "Which sources could not be read?",
    "Where is competitor data missing?",
]
STARTERS_BY_KIND = {
    "product": ["What is this product compared against?",
                "Why is there no price for this product?",
                "How old is the evidence for this product?"],
    "competitor": ["What has been observed from this competitor?",
                   "What offers is this competitor running?",
                   "Which of their sources still work?"],
    "match": ["Why is this match undecided?",
              "What is the price difference here?",
              "Who confirmed this match?"],
    "action": ["What is blocking this action?",
               "What evidence is there for this action?"],
}

CTX_LABEL = {"product": "Clara product", "competitor": "Competitor",
             "match": "Competitor match", "action": "Action",
             "observation": "Price observation", "source": "Data source"}


def _q(path: str, query: dict, **over) -> str:
    """A link back to the same page with the panel state changed."""
    out = {}
    for k, v in (query or {}).items():
        if isinstance(v, list):
            v = v[0] if v else None
        if v not in (None, ""):
            out[k] = v
    for k, v in over.items():
        if v is None:
            out.pop(k, None)
        else:
            out[k] = v
    return path + (("?" + urllib.parse.urlencode(out)) if out else "")


def render_panel(*, path: str, query: dict, conversation: dict | None,
                 ctx_kind: str = "", ctx_id: str = "", ctx_label: str = "",
                 error: str = "", actor=None) -> str:
    """The right-side panel. Rendered into the shell, not into a page."""
    close = _q(path, query, agent=None, ctx=None, ctxid=None, c=None)
    P = ['<aside class="ag" aria-label="Competitor Intelligence Agent">']

    # ---- header: what it is, and what record it is looking at ----
    P.append('<div class="ag-h"><div>')
    P.append('<h2>Intelligence Agent</h2>')
    if ctx_kind:
        P.append(f'<div class="ctx">Reading '
                 f'{e(CTX_LABEL.get(ctx_kind, ctx_kind))}: '
                 f'{e(ctx_label or ctx_id)}</div>')
    else:
        P.append('<div class="ctx">Reading the whole store</div>')
    P.append('</div>')
    P.append(f'<a class="b b-sm" href="{e(close)}" aria-label="Close the '
             f'agent panel">Close</a>')
    P.append("</div>")

    # 6.2, stated on the panel whether or not a conversation is in progress. It
    # used to appear only on the empty state, so the moment you asked anything
    # the exclusions scrolled away — and a reader who cannot see what the agent
    # refuses will read a refusal as a malfunction.
    P.append(
        '<details class="ag-scope"><summary>Scope: what this agent will '
        'not do</summary><div class="ag-scope-b">'
        '<b>Excluded (addendum 6.2)</b><ul>'
        + "".join(f"<li>{e(x)}</li>" for x in EXCLUSIONS)
        + "</ul>"
        "<p>Asking for any of these is declined rather than attempted, and the "
        "check runs on the answer as well as the question. What it does cover "
        "is competitor products, matches, prices and differences, offers, "
        "availability, provenance, freshness and what is unresolved.</p>"
        "</div></details>")

    # ---- transcript ----
    P.append('<div class="ag-scroll">')
    if error:
        P.append(f'<div class="flash err" role="alert">{e(error)}</div>')

    msgs = (conversation or {}).get("messages") or []
    if not msgs:
        P.append(_intro(ctx_kind))
    else:
        for m in msgs:
            P.append(_message(m))
        conv_req = (conversation or {}).get("request")
        if conv_req:
            P.append(f'<div class="note good">This conversation was escalated '
                     f'to request <a href="/requests/'
                     f'{e(conv_req["request_id"])}">'
                     f'{e(conv_req.get("subject") or conv_req["request_id"])}'
                     f'</a> ({e(conv_req.get("status"))}).</div>')
        elif _has_gap(msgs):
            P.append(_escalate_form(conversation, path, query))
    P.append("</div>")

    # ---- ask ----
    P.append(_ask_form(path, query, conversation, ctx_kind, ctx_id))
    P.append("</aside>")
    return "".join(P)


def _intro(ctx_kind: str) -> str:
    """What it answers, what it will not, and something to click."""
    P = ['<div class="scoped">']
    P.append("<b>What this agent answers</b><br>"
             + "<br>".join("• " + e(s) for s in IN_SCOPE))
    P.append("<br><br><b>What it will not do</b><br>"
             + e(", ".join(EXCLUSIONS))
             + ". Those are outside competitor intelligence (6.2), and asking "
               "for them is declined rather than attempted — see Scope above, "
               "which stays available while you work.")
    P.append("<br><br>Answers are grounded in stored records and cite them. "
             "Where the evidence is missing, stale or conflicting, it says so "
             "and offers to raise a request.")
    P.append("</div>")

    starters = STARTERS_BY_KIND.get(ctx_kind, []) + STARTERS_GLOBAL
    P.append('<div style="display:flex;flex-direction:column;gap:6px">')
    for s in starters[:5]:
        P.append('<button class="b b-sm" type="submit" name="question" '
                 f'value="{e(s)}" form="ag-ask">{e(s)}</button>')
    P.append("</div>")
    return "".join(P)


def _message(m: dict) -> str:
    if m.get("role") == "user":
        return (f'<div class="msg you"><div class="who">You · '
                f'{when(m.get("at"))}</div>'
                f'<div class="bd">{e(m.get("body"))}</div></div>')

    P = [f'<div class="msg agent"><div class="who">Agent · '
         f'{when(m.get("at"))}</div>'
         f'<div class="bd">{e(m.get("body"))}</div>']

    cites = m.get("citations") or []
    if cites:
        P.append('<div class="cites">')
        for c in cites:
            P.append(_citation(c))
        P.append("</div>")

    for g in (m.get("gaps") or []):
        P.append(f'<div class="gap"><b>Missing:</b> {e(g.get("what"))}'
                 f' — {e(g.get("why"))}'
                 + (f'<br>Suggested: {e(g["suggest"])}' if g.get("suggest")
                    else "")
                 + "</div>")
    if not cites and not (m.get("gaps") or []):
        P.append('<div class="ev">No record was cited for this reply.</div>')
    P.append("</div>")
    return "".join(P)


def _citation(c: dict) -> str:
    """A cited record, openable, with its provenance (6.3)."""
    kind = c.get("record_kind") or ""
    rid = c.get("record_id") or ""
    href = {"product": f"/products/{rid}", "competitor": f"/competitors/{rid}",
            "action": f"/actions/{rid}", "request": f"/requests/{rid}"}.get(kind)
    label = c.get("label") or f"{kind} {rid}"
    P = ['<div class="cite"><span>']
    if href:
        P.append(f'<a href="{e(href)}">{e(label)}</a>')
    else:
        P.append(e(label))
    P.append(f'<div class="cm">{e(kind)}'
             + (f' · observed {when(c.get("observed_at"), date_only=True)}'
                if c.get("observed_at") else "")
             + "</div>")
    if c.get("url"):
        P.append(f'<div class="cm"><a href="{e(c["url"])}" '
                 f'rel="nofollow noopener">{e(c["url"][:44])}</a></div>')
    P.append("</span>")
    if c.get("provenance"):
        P.append(prov(c["provenance"], short=True))
    P.append("</div>")
    return "".join(P)


def _has_gap(msgs: list) -> bool:
    return any(m.get("gaps") for m in msgs if m.get("role") == "agent")


def _escalate_form(conversation: dict, path: str, query: dict) -> str:
    """6.3 and 7: offer Send Request rather than pretend it was answered."""
    cid = (conversation or {}).get("conversation_id") or ""
    return (
        '<div class="note warn">'
        'This could not be answered from the stored records. Raising a request '
        'sends the conversation, the records cited and the missing-evidence '
        'note to an admin.'
        f'<form method="post" action="/agent/escalate" style="margin-top:9px">'
        f'<input type="hidden" name="conversation_id" value="{e(cid)}">'
        f'<input type="hidden" name="back" value="{e(_q(path, query))}">'
        + ff("request_type", "Request type", kind="select",
             value=RequestType.MANUAL_VERIFICATION,
             options=[(k, v) for k, v in REQUEST_TYPE_LABEL.items()])
        + ff("extra", "Anything to add", kind="textarea", rows=2,
             hint="Optional. The conversation and citations are attached "
                  "automatically.")
        + '<div class="fbar">'
          '<button class="b b-pri" type="submit">Send Request</button>'
          "</div></form></div>")


def _ask_form(path: str, query: dict, conversation: dict | None,
              ctx_kind: str, ctx_id: str) -> str:
    cid = (conversation or {}).get("conversation_id") or ""
    return (
        f'<div class="ag-f"><form method="post" action="/agent/ask" id="ag-ask">'
        f'<input type="hidden" name="conversation_id" value="{e(cid)}">'
        f'<input type="hidden" name="ctx" value="{e(ctx_kind)}">'
        f'<input type="hidden" name="ctxid" value="{e(ctx_id)}">'
        f'<input type="hidden" name="back" value="{e(_q(path, query))}">'
        '<label for="ag-q" style="font-size:11px;font-weight:700;'
        'text-transform:uppercase;letter-spacing:.03em;color:var(--ink3)">'
        'Ask about the stored competitor records</label>'
        '<textarea id="ag-q" name="question" required '
        'placeholder="Why is this price stale? Which sources failed? '
        'What is undecided?"></textarea>'
        '<div class="fbar" style="margin-top:8px">'
        '<button class="b b-pri" type="submit">Ask</button>'
        + (f'<a class="b b-sm" href="{e(_q(path, query, c=None))}">'
           'New conversation</a>' if cid else "")
        + "</div></form></div>")


# --------------------------------------------------------------------------
# a full-page transcript, for reading an escalated conversation later
# --------------------------------------------------------------------------

def render_conversation(conv: dict) -> str:
    """A conversation on its own page, so a Request can link back to it."""
    from .shell import kv, page_head, panel
    P = ['<div class="wrap narrow">']
    P.append(page_head(
        conv.get("title") or "Agent conversation",
        "The conversation a request was escalated from, as it was stored.",
        trail=[("Requests", "/requests"),
               (conv["conversation_id"], None)]))
    rows = [("Started", when(conv.get("started_at"))),
            ("Last message", when(conv.get("last_at"))),
            ("Asked by", e(conv.get("username")))]
    if conv.get("context_kind"):
        rows.append(("Context",
                     f'{e(CTX_LABEL.get(conv["context_kind"], conv["context_kind"]))}'
                     f' {e(conv.get("context_id") or "")}'))
    if conv.get("request"):
        r = conv["request"]
        rows.append(("Escalated to",
                     f'<a href="/requests/{e(r["request_id"])}">'
                     f'{e(r.get("subject") or r["request_id"])}</a>'))
    P.append(panel("Conversation", kv(rows)))
    body = "".join(_message(m) for m in (conv.get("messages") or []))
    P.append(panel("Transcript",
                   '<div style="display:flex;flex-direction:column;gap:12px">'
                   + body + "</div>"))
    P.append("</div>")
    return "".join(P)
