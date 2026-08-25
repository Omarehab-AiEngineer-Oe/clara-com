"""Vertex AI (Gemini) judgement layer.

Requirements §9A: matching stores "score, rule/model version, evidence,
conflicts, decision source and timestamps". This module is the model-backed
decision source; `matching.py` holds the deterministic one. Whichever produced a
decision is recorded on the match as `match_method` / `match_version`, so a run
is always auditable back to how each call was decided.

§6 also constrains this: "validation and storage integrity must not depend only
on free-form model judgment." So the model is used to judge *identity* and to
build discovery queries; it never writes a price, a stock status or a stored
record, and its verdict is bounded by the deterministic format gate.

Auth: Vertex AI with Application Default Credentials, pinned to the `global`
location because the gemini-3 series is only served there. If credentials are
missing or expired the module reports itself unavailable and the caller falls
back to deterministic scoring — a run never stalls on the model, and the
fallback is recorded rather than hidden.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from functools import cached_property

MODEL_ID = os.environ.get("CLARA_VERTEX_MODEL", "gemini-3.5-flash")
FALLBACK_MODEL_IDS = ("gemini-2.5-flash", "gemini-2.0-flash")
LOCATION = os.environ.get("CLARA_VERTEX_LOCATION", "global")

DECISION_SOURCE_MODEL = "vertex_gemini"
DECISION_SOURCE_RULES = "deterministic_rules"
RULES_VERSION = "rules_v1"

# Bounded, so a malformed model reply cannot become a stored decision.
VERDICT_SCHEMA = {
    "type": "object",
    "properties": {
        "same_product": {"type": "boolean"},
        "confidence": {"type": "number"},
        "identity_evidence": {"type": "array", "items": {"type": "string"}},
        "conflicts": {"type": "array", "items": {"type": "string"}},
        "comparison_basis": {
            "type": "string",
            "enum": ["standalone_product", "attachment_of_system", "bundle", "unclear"],
        },
        "reasoning": {"type": "string"},
    },
    "required": ["same_product", "confidence", "identity_evidence",
                 "conflicts", "comparison_basis", "reasoning"],
}

JUDGE_PROMPT = """You judge whether a competitor product is the same product as a Clara product.

You are given both products' published attributes only. Decide identity, not value.

Rules you must follow:
- Price is NEVER evidence of identity. Two devices at the same price are not the same product.
- Format and function must agree. A hot-air brush is not a straightener. A standalone device is not one attachment of a modular system.
- If the competitor item is one attachment inside a larger system that is not sold separately, set comparison_basis to attachment_of_system.
- Base every claim on the attributes given. Do not use outside knowledge of these products.
- If the attributes are too thin to decide, say so: same_product false with low confidence and the conflicts that made it undecidable.
- confidence is 0.0 to 1.0 and must reflect the evidence actually present, not how plausible the pairing feels.

CLARA PRODUCT
{clara}

COMPETITOR CANDIDATE
{candidate}
"""

QUERY_PROMPT = """Build search queries to find one Clara product on a specific competitor's website.

Return 2 to 4 short queries, one per line, no numbering and no commentary.
Use the competitor's own naming conventions, not Clara's wording.
Include the product format and any distinguishing specification.
Do not include the word "Clara".

CLARA PRODUCT
{clara}

COMPETITOR
brand: {brand}
domains: {domains}
"""


@dataclass
class Verdict:
    same_product: bool
    confidence: float
    identity_evidence: list[str] = field(default_factory=list)
    conflicts: list[str] = field(default_factory=list)
    comparison_basis: str = "unclear"
    reasoning: str = ""
    decision_source: str = DECISION_SOURCE_MODEL
    model_version: str = MODEL_ID

    def as_dict(self) -> dict:
        return {
            "same_product": self.same_product,
            "confidence": round(float(self.confidence), 3),
            "identity_evidence": self.identity_evidence,
            "conflicts": self.conflicts,
            "comparison_basis": self.comparison_basis,
            "reasoning": self.reasoning,
            "decision_source": self.decision_source,
            "model_version": self.model_version,
        }


class VertexJudge:
    """Wraps the Vertex AI client. Construction never raises; check `available`."""

    def __init__(self, model_id: str = MODEL_ID, location: str = LOCATION,
                 project: str | None = None):
        self.model_id = model_id
        self.location = location
        self._project = project
        self._unavailable_reason: str | None = None
        self._calls = 0
        self._failures = 0
        self._probed: bool | None = None

    @cached_property
    def project(self) -> str | None:
        if self._project:
            return self._project
        for var in ("GOOGLE_CLOUD_PROJECT", "GCLOUD_PROJECT", "CLARA_GCP_PROJECT"):
            if os.environ.get(var):
                return os.environ[var]
        try:
            import google.auth
            _, proj = google.auth.default()
            return proj
        except Exception as e:
            self._unavailable_reason = f"no credentials: {type(e).__name__}: {e}"
            return None

    @cached_property
    def client(self):
        """A google.genai Client pinned to Vertex AI and the global location."""
        try:
            from google.genai import Client
        except ImportError as e:
            self._unavailable_reason = f"google-genai not installed: {e}"
            return None
        proj = self.project
        if not proj:
            return None
        try:
            return Client(vertexai=True, project=proj, location=self.location)
        except Exception as e:
            self._unavailable_reason = f"client init failed: {type(e).__name__}: {e}"
            return None

    def probe(self) -> bool:
        """One cheap call, cached. A constructed client proves nothing: credentials
        are only exercised when a request is actually made, so reporting
        availability without probing overstates it."""
        if self._probed is None:
            txt = self._generate("Reply with exactly: OK")
            self._probed = bool(txt)
        return self._probed

    @property
    def available(self) -> bool:
        if self.client is None:
            return False
        if self._probed is None:
            return self.probe()
        return self._probed and self._unavailable_reason is None

    @property
    def status(self) -> dict:
        return {
            "configured_model": self.model_id,
            "location": self.location,
            "project": self._project or (self.project if not self._unavailable_reason else None),
            "available": bool(self._probed) if self._probed is not None else None,
            "probed": self._probed is not None,
            "unavailable_reason": self._unavailable_reason,
            "calls": self._calls,
            "failures": self._failures,
        }

    # ---------------- raw call ----------------

    def _generate(self, prompt: str, schema: dict | None = None) -> str | None:
        c = self.client
        if c is None:
            return None
        cfg: dict = {"temperature": 0}
        if schema:
            cfg["response_mime_type"] = "application/json"
            cfg["response_schema"] = schema
        models = [self.model_id, *FALLBACK_MODEL_IDS]
        last_err: str | None = None
        for m in models:
            try:
                self._calls += 1
                r = c.models.generate_content(model=m, contents=prompt, config=cfg)
                if m != self.model_id:
                    self.model_id = m       # remember what actually served
                return r.text
            except Exception as e:
                last_err = f"{type(e).__name__}: {str(e)[:200]}"
                self._failures += 1
                # Auth problems will not be fixed by trying another model.
                if "Reauthentication" in last_err or "credentials" in last_err.lower():
                    break
        self._unavailable_reason = last_err
        return None

    def structured(self, system: str, prompt: str, schema: dict) -> dict | None:
        """A schema-bound call for the intelligence agents.

        Same discipline as `judge`: the reply must fit the schema or it is
        discarded. The agent's own instruction file is prepended as `system` so a
        call always runs under the prompt the operator can read on disk.
        """
        if not self.available:
            return None
        head = (system or "").strip()
        full = (head + "\n\n" + prompt) if head else prompt
        raw = self._generate(full, schema)
        if not raw:
            return None
        try:
            out = json.loads(raw)
        except (ValueError, TypeError):
            m = re.search(r"\{.*\}", raw, re.S)
            if not m:
                return None
            try:
                out = json.loads(m.group(0))
            except (ValueError, TypeError):
                return None
        return out if isinstance(out, dict) else None

    def model_status(self) -> dict:
        """Status with a real probe behind it, for callers deciding whether to ask.

        `status()` reports the cached probe and can answer `available: None`
        before anything has been tried; this one commits to a boolean.
        """
        self.available
        return self.status

    # ---------------- identity judgement ----------------

    def judge(self, clara: dict, candidate: dict) -> Verdict | None:
        """Return a model Verdict, or None when the model is unavailable."""
        txt = self._generate(
            JUDGE_PROMPT.format(
                clara=json.dumps(clara, ensure_ascii=False, indent=1),
                candidate=json.dumps(candidate, ensure_ascii=False, indent=1),
            ),
            VERDICT_SCHEMA,
        )
        if not txt:
            return None
        try:
            data = json.loads(txt)
        except json.JSONDecodeError:
            m = re.search(r"\{.*\}", txt, re.S)
            if not m:
                return None
            try:
                data = json.loads(m.group(0))
            except json.JSONDecodeError:
                return None
        try:
            conf = float(data.get("confidence", 0))
        except (TypeError, ValueError):
            conf = 0.0
        return Verdict(
            same_product=bool(data.get("same_product")),
            confidence=max(0.0, min(1.0, conf)),
            identity_evidence=[str(x) for x in (data.get("identity_evidence") or [])][:8],
            conflicts=[str(x) for x in (data.get("conflicts") or [])][:8],
            comparison_basis=str(data.get("comparison_basis") or "unclear"),
            reasoning=str(data.get("reasoning") or "")[:600],
            model_version=self.model_id,
        )

    # ---------------- discovery queries ----------------

    def queries(self, clara: dict, brand: str, domains: list[str]) -> list[str]:
        txt = self._generate(QUERY_PROMPT.format(
            clara=json.dumps(clara, ensure_ascii=False, indent=1),
            brand=brand, domains=", ".join(domains),
        ))
        if not txt:
            return []
        out = []
        for line in txt.splitlines():
            line = re.sub(r"^\s*[-*\d.)\s]+", "", line).strip().strip('"')
            if 3 < len(line) < 160:
                out.append(line)
        return out[:4]


_singleton: VertexJudge | None = None


def judge_singleton() -> VertexJudge:
    global _singleton
    if _singleton is None:
        _singleton = VertexJudge()
    return _singleton
