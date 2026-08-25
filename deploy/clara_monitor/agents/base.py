"""What every competitor-intelligence agent inherits.

Each agent is a prompt plus a deterministic implementation of the same contract,
and that pairing is deliberate rather than a fallback bolted on afterwards. The
requirements already say validation and storage integrity must not depend only on
free-form model judgement, so the rules path is the floor: it runs whether or not
Vertex answers, and the model, when it is reachable, refines within the same
output shape instead of replacing it.

Three things this base guarantees for every agent:

* **The decision source is recorded on every output.** A reader can always tell
  whether a verdict came from the model or the rules, which matters because the
  two are not equally good and pretending otherwise would be the exact dishonesty
  the evidence discipline forbids.
* **A model reply can only narrow, never widen.** The model may lower a
  confidence, add a conflict or reject a candidate. It cannot mint evidence, and
  anything it returns that is not backed by an `Evidence` record already held is
  dropped.
* **Failure is recorded, not swallowed.** An agent that could not run says so in
  its own report rather than returning an empty result that reads like "nothing
  found".
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path

from .contracts import Confidence, DecisionSource, Evidence, now_iso

PROMPT_DIR = Path(__file__).resolve().parent.parent.parent / "prompts" / "agents"


@dataclass
class AgentReport:
    """What an agent returns about its own run, alongside its output.

    `ran` false with a reason is a valid, useful result. It is how the orchestrator
    distinguishes "this competitor has no offers" from "the offers agent could not
    read anything", which are opposite facts that an empty list would blur.
    """
    agent: str
    ran: bool = True
    decision_source: str = DecisionSource.RULES
    started_at: str = ""
    finished_at: str = ""
    items_in: int = 0
    items_out: int = 0
    skipped: int = 0
    blocked: list[dict] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    error: str = ""

    def note(self, text: str) -> None:
        if text and text not in self.notes:
            self.notes.append(text)

    def to_dict(self) -> dict:
        return {
            "agent": self.agent, "ran": self.ran,
            "decision_source": self.decision_source,
            "started_at": self.started_at, "finished_at": self.finished_at,
            "items_in": self.items_in, "items_out": self.items_out,
            "skipped": self.skipped, "blocked": self.blocked,
            "notes": self.notes, "error": self.error,
        }


class Agent:
    """Base class. Subclasses implement `run_rules` and may implement `refine`."""

    name = "agent"
    prompt_file = ""

    def __init__(self, llm=None, verbose: bool = False):
        self.llm = llm
        self.verbose = verbose
        self.report = AgentReport(agent=self.name)

    # ---------------- prompt ----------------

    @property
    def prompt(self) -> str:
        """The instruction this agent was written to follow.

        Loaded from disk rather than embedded so the prompt the operator edits is
        the prompt the agent runs, with no second copy to fall out of step.
        """
        if not self.prompt_file:
            return ""
        path = PROMPT_DIR / self.prompt_file
        return path.read_text(encoding="utf-8") if path.exists() else ""

    # ---------------- model ----------------

    def model_available(self) -> bool:
        if not self.llm:
            return False
        try:
            return bool(self.llm.model_status().get("available"))
        except Exception:
            return False

    def ask_model(self, task: str, payload: dict, schema: dict) -> dict | None:
        """One bounded model call, or None.

        The prompt is always the agent's own instruction file plus the task, so a
        model call cannot quietly run under different rules from the ones the
        operator can read.
        """
        if not self.model_available():
            return None
        try:
            text = json.dumps(payload, ensure_ascii=False, default=str)[:24000]
            out = self.llm.structured(
                system=self.prompt, prompt=f"{task}\n\n{text}", schema=schema)
            if out:
                self.report.decision_source = DecisionSource.MODEL
            return out
        except Exception as e:
            self.report.note(f"model call failed, rules used instead: "
                             f"{type(e).__name__}: {e}")
            return None

    # ---------------- evidence discipline ----------------

    @staticmethod
    def keep_only_supported(claims: list[str], evidence: list[Evidence]) -> list[str]:
        """Drop any claim the held evidence cannot support.

        The test is deliberately crude — a claim survives only if there is at
        least one evidence record to attach it to. It exists to stop an empty
        evidence list from carrying a confident sentence, not to judge prose.
        """
        return list(claims) if evidence else []

    @staticmethod
    def cap_confidence(value: str, ceiling: str) -> str:
        """Never let a confidence exceed what the verdict allows."""
        return value if Confidence.rank(value) <= Confidence.rank(ceiling) else ceiling

    # ---------------- lifecycle ----------------

    def run(self, *args, **kwargs):
        self.report.started_at = now_iso()
        t0 = time.time()
        try:
            result = self.run_rules(*args, **kwargs)
            refined = self.refine(result, *args, **kwargs)
            if refined is not None:
                result = refined
        except Exception as e:
            import traceback
            self.report.ran = False
            self.report.error = f"{type(e).__name__}: {e}"
            self.report.note(traceback.format_exc().strip().splitlines()[-1])
            result = self.empty()
        self.report.finished_at = now_iso()
        self.report.note(f"took {time.time() - t0:.1f}s")
        return result

    def run_rules(self, *args, **kwargs):
        raise NotImplementedError

    def refine(self, result, *args, **kwargs):
        """Optional model pass over the deterministic result. Default: none."""
        return None

    def empty(self):
        return []
