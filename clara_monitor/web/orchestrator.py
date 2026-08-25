"""Section 7: the eleven steps, in order, with step 10 doing real work.

    1  validate URLs and optional inputs
    2  create an analysis run
    3  discover or load the selected Clara and competitor pages
    4  choose normal page extraction or browser rendering for each page
    5  collect visible copy, CTAs, images, page structure and screenshots
    6  normalise pages and observations into common categories
    7  analyse Clara and each competitor independently
    8  compare equivalent pages, sections and themes
    9  generate findings and prioritised recommendations
    10 validate evidence coverage and mark blocked or uncertain items
    11 store and publish the final report

Step 10 is the one that would be easy to skip and expensive to skip. It is where
a finding that claims absence on a page nobody read gets demoted, and where a
High-priority finding without a screenshot is either given one or has its
limitation recorded. A pipeline without that step produces a confident report and
no way to tell which parts of it to believe.

Like every other agent here, this runs its deterministic path whether or not
Vertex answers, and records which one it used. A model, when reachable, may only
narrow: lower a confidence, add a caveat, drop an unsupported claim. It cannot
mint a finding, because a finding with no evidence row behind it is exactly what
the requirements forbid.
"""

from __future__ import annotations

import json
from pathlib import Path

from . import analyze, compare, recommend
from .collect import (Collector, browser_status, find_browser, safe_print,
                      validate_inputs, website_from_url)
from .contracts import (AccessStatus, AnalysisRun, Confidence, Evidence,
                        Finding, FindingCategory, FindingKind, PresenceState,
                        Priority, RunStatus, WebsiteRole, key_of,
                        never_upgrade, now_iso)
from .store import WebStore

AGENT_VERSION = "website-analysis/1.0"

NARROW_SCHEMA = {
    "type": "object",
    "properties": {
        "adjustments": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "finding_key": {"type": "string"},
                    "lower_confidence_to": {
                        "type": "string",
                        "enum": ["MEDIUM", "LOW", "UNVERIFIED"]},
                    "lower_priority_to": {
                        "type": "string", "enum": ["MEDIUM", "LOW"]},
                    "caveat": {"type": "string"},
                    "drop": {"type": "boolean"},
                    "reason": {"type": "string"},
                },
                "required": ["finding_key", "reason"],
            },
        },
    },
    "required": ["adjustments"],
}


class WebsiteAnalysisAgent:
    """The whole module's entry point. One call, one run, one stored report."""

    name = "website_analysis"

    def __init__(self, db_path: Path | str, *, llm=None, verbose: bool = True,
                 shots_dir: Path | None = None):
        self.db_path = Path(db_path)
        self.llm = llm
        self.verbose = verbose
        self.shots_dir = Path(shots_dir) if shots_dir else \
            self.db_path.parent / "screenshots"
        self.store = WebStore(self.db_path)

    def close(self) -> None:
        self.store.close()

    def say(self, msg: str) -> None:
        if self.verbose:
            safe_print(msg)

    # ------------------------------------------------------------------
    # the run
    # ------------------------------------------------------------------

    def run(self, *, clara_url: str, competitor_urls: list,
            specific_pages: list | None = None, audience: str = "",
            brand_guidelines: str = "", business_goals: str = "",
            page_limit: int = 12, requested_by: str = "",
            want_screenshots: bool = True, run_id: str | None = None) -> dict:

        # ---- 1. validate
        urls, problems = validate_inputs(clara_url, competitor_urls)
        run = AnalysisRun(
            run_id=run_id or self.store.next_run_id(),
            clara_url=clara_url, competitor_urls=list(competitor_urls or []),
            specific_pages=list(specific_pages or []), audience=audience,
            brand_guidelines=brand_guidelines, business_goals=business_goals,
            page_limit=page_limit, requested_by=requested_by,
            agent_version=AGENT_VERSION)
        for p in problems:
            run.warn(p)

        # ---- 2. create the run
        self.store.open_run(run)
        self.say(f"\nWebsite Analysis {run.run_id}")

        if not urls:
            run.status = RunStatus.FAILED
            run.finished_at = now_iso()
            run.warn("The run stopped before collection: a Clara URL and at "
                     "least one competitor URL are both required.")
            self.store.close_run(run, {"stopped_before_collection": True})
            self.say("  stopped: " + "; ".join(run.warnings))
            return self.report(run.run_id)

        shots = browser_status()
        if not shots["available"]:
            run.warn("Screenshot evidence is unavailable in this environment: "
                     + shots["why"])
        self.say(f"  screenshots: {shots['why']}")

        # ---- 3, 4, 5. discover, choose a method per page, collect
        run.status = RunStatus.COLLECTING
        self.store.set_status(run.run_id, run.status)

        clara_site = website_from_url(urls[0], WebsiteRole.CLARA, "Clara")
        rival_sites = [website_from_url(u, WebsiteRole.COMPETITOR)
                       for u in urls[1:]]

        collector = Collector(page_limit=page_limit, shots_dir=self.shots_dir,
                              want_shots=want_screenshots,
                              verbose=self.verbose)
        pages_by_site: dict = {}
        for site in [clara_site] + rival_sites:
            self.say(f"  {site.base_url}")
            mine = [u for u in (specific_pages or [])]
            pages = collector.collect_site(site, specific=mine)
            pages_by_site[site.key] = pages
            for p in pages:
                self.store.put_page(run.run_id, p)
            self.store.put_site(run.run_id, site)
            self.say(f"    {site.pages_read} read, {site.pages_blocked} blocked, "
                     f"{site.pages_attempted} attempted")
            if site.access_status != AccessStatus.OK:
                run.warn(f"{site.name} ({site.base_url}) could not be read: "
                         f"{site.access_note or site.access_status}")

        for b in collector.blocked:
            run.warn(f"blocked: {b['url']} — {b['why']}")

        # ---- 6, 7. normalise into common categories, analyse each site alone
        run.status = RunStatus.ANALYSING
        self.store.set_status(run.run_id, run.status)

        profiles: dict = {}
        for site in [clara_site] + rival_sites:
            obs: list = []
            for p in pages_by_site[site.key]:
                obs += analyze.analyse_page(site, p,
                                            collector.html.get(p.page_key, ""))
            if obs:
                self.store.put_observations(run.run_id, obs)
            prof = analyze.profile_site(site, pages_by_site[site.key], obs)
            prof.update(analyze.strengths_and_weaknesses(prof))
            profiles[site.key] = prof
            self.say(f"  {site.name}: {len(obs)} observation(s), "
                     f"{prof['image_variety']} image type(s), "
                     f"{len(prof['jobs_done'])}/4 content job(s)")

        # ---- 8, 9. compare, then recommend
        run.status = RunStatus.COMPARING
        self.store.set_status(run.run_id, run.status)

        clara_prof = profiles[clara_site.key]
        rival_profs = [profiles[s.key] for s in rival_sites]
        findings = compare.compare_all(clara_prof, rival_profs)
        self.say(f"  {len(findings)} finding(s) before validation")

        # ---- 10. validate evidence coverage
        findings, notes = self.validate(findings, clara_prof, rival_profs,
                                        want_screenshots and shots["available"])
        for n in notes:
            run.warn(n)

        findings = self.refine(findings, run)
        recs = recommend.recommend(findings)
        gate = recommend.completeness(recs)
        if gate["incomplete"]:
            run.warn(f"{len(gate['incomplete'])} recommendation(s) are missing a "
                     f"required part; they are shown on the report as incomplete "
                     f"rather than hidden.")

        # ---- 11. store and publish
        self.store.put_findings(run.run_id, findings)
        self.store.put_recommendations(run.run_id, recs)

        run.status = RunStatus.DONE
        run.finished_at = now_iso()
        summary = self._summary(clara_prof, rival_profs, findings, recs, gate,
                               shots)
        self.store.close_run(run, summary)
        self.say(f"  done: {summary['findings']} finding(s), "
                 f"{summary['high']} high priority, "
                 f"{summary['recommendations']} recommendation(s)")
        return self.report(run.run_id)

    # ------------------------------------------------------------------
    # step 10
    # ------------------------------------------------------------------

    def validate(self, findings: list, clara: dict, rivals: list,
                 shots_possible: bool) -> tuple[list, list]:
        """Every finding must be supportable by evidence the run actually holds.

        Three gates, and each one demotes rather than deletes. A demoted finding
        with its reason attached is more useful than a missing one, because the
        reason is often the thing worth acting on.
        """
        notes: list = []
        kept: list = []

        readable = {p["url"] for prof in [clara] + list(rivals)
                    for p in (prof.get("pages") or [])
                    if p.get("status") == AccessStatus.OK}
        shot_for = {p["url"]: p.get("screenshot") or ""
                    for prof in [clara] + list(rivals)
                    for p in (prof.get("pages") or [])}

        demoted_absence = 0
        no_evidence = 0
        no_shot = 0

        for f in findings:
            # Gate 1: no evidence, no finding. The one hard rule.
            if not f.evidence:
                no_evidence += 1
                continue

            # Gate 2: absence may only be claimed about a page that was read.
            if f.clara_state == PresenceState.ABSENT and f.clara_url \
                    and f.clara_url not in readable:
                f.clara_state = PresenceState.NOT_OBSERVED
                f.confidence = never_upgrade(f.confidence, Confidence.LOW)
                f.confidence_why = (
                    "demoted at validation: this claims something is absent from "
                    "a Clara page that was not readable in this run, so it is "
                    "recorded as not observed rather than as missing")
                f.priority = (Priority.LOW if f.priority == Priority.HIGH
                              else f.priority)
                demoted_absence += 1

            # Gate 3: a High-priority finding should carry a screenshot where
            # that is technically possible. Where it is not, the limitation is
            # written onto the finding rather than left as a silent absence.
            if f.priority == Priority.HIGH:
                have = any(getattr(e, "screenshot", "") or
                           (isinstance(e, dict) and e.get("screenshot"))
                           for e in f.evidence)
                if not have:
                    shot = shot_for.get(f.clara_url, "")
                    if shot:
                        for e in f.evidence:
                            if getattr(e, "url", "") == f.clara_url:
                                e.screenshot = shot
                                have = True
                                break
                if not have:
                    no_shot += 1
                    f.evidence.append(Evidence(
                        url=f.clara_url, section=f.clara_section,
                        excerpt="",
                        note=("no screenshot: " +
                              ("this page was not photographed in this run"
                               if shots_possible else
                               "screenshots are unavailable in this "
                               "environment"))))
            kept.append(f)

        if no_evidence:
            notes.append(f"{no_evidence} candidate finding(s) were dropped for "
                         f"carrying no evidence row.")
        if demoted_absence:
            notes.append(f"{demoted_absence} finding(s) claimed something was "
                         f"absent from a page that could not be read; each was "
                         f"demoted to 'not observed'.")
        if no_shot:
            notes.append(f"{no_shot} high-priority finding(s) have no screenshot; "
                         f"each says so on its own evidence.")

        # Re-sort: gate 2 changed some priorities.
        from .contracts import PRIORITY_ORDER
        kept.sort(key=lambda f: (PRIORITY_ORDER.index(f.priority),
                                 f.kind == FindingKind.STRENGTH, f.category))
        return kept, notes

    # ------------------------------------------------------------------
    # the model pass: may only narrow
    # ------------------------------------------------------------------

    def refine(self, findings: list, run: AnalysisRun) -> list:
        """One bounded model call that can lower, caveat or drop. Never add.

        Deliberately given only the findings, not the raw pages: the model's job
        here is to catch a rule that fired on something a person would call a
        false positive, and it cannot do that job by inventing new material.
        """
        if not self.llm or not findings:
            return findings
        try:
            if not bool(self.llm.model_status().get("available")):
                return findings
        except Exception:
            return findings

        payload = {
            "context": {"audience": run.audience,
                        "brand_guidelines": run.brand_guidelines,
                        "business_goals": run.business_goals},
            "findings": [{"finding_key": f.finding_key, "title": f.title,
                          "category": f.category, "kind": f.kind,
                          "observed": f.observed[:300], "why": f.why[:300],
                          "confidence": f.confidence, "priority": f.priority,
                          "clara_state": f.clara_state}
                         for f in findings[:60]],
        }
        task = ("You may only NARROW. For any finding that a careful reviewer "
                "would call a false positive, over-stated, or unsupported by its "
                "own observation, return a lower confidence, a lower priority, a "
                "caveat, or drop=true — with a reason. Do not add findings. Do "
                "not raise any confidence or priority. Return {} if every "
                "finding looks fair.")
        try:
            out = self.llm.structured(
                system=(Path(__file__).resolve().parents[2] / "prompts" /
                        "agents" / "website_analysis.md").read_text(
                            encoding="utf-8")
                if (Path(__file__).resolve().parents[2] / "prompts" / "agents" /
                    "website_analysis.md").exists() else "",
                prompt=f"{task}\n\n{json.dumps(payload, ensure_ascii=False)[:24000]}",
                schema=NARROW_SCHEMA)
        except Exception as e:
            run.warn(f"the model pass did not run ({type(e).__name__}); the "
                     f"deterministic gradings stand unchanged")
            return findings

        adjustments = (out or {}).get("adjustments") or []
        if not adjustments:
            return findings

        by_key = {f.finding_key: f for f in findings}
        dropped, lowered = 0, 0
        for a in adjustments:
            f = by_key.get(a.get("finding_key"))
            if not f:
                continue
            if a.get("drop"):
                f.priority = Priority.LOW
                f.confidence = Confidence.UNVERIFIED
                f.confidence_why = (f"the model pass rejected this: "
                                    f"{a.get('reason', '')[:200]}")
                dropped += 1
                continue
            if a.get("lower_confidence_to"):
                before = f.confidence
                f.confidence = never_upgrade(f.confidence,
                                             a["lower_confidence_to"])
                if f.confidence != before:
                    f.confidence_why = (f.confidence_why + " | model lowered: "
                                        + a.get("reason", "")[:200])
                    lowered += 1
            if a.get("lower_priority_to") and \
                    a["lower_priority_to"] in (Priority.MEDIUM, Priority.LOW):
                if f.priority == Priority.HIGH or \
                        (f.priority == Priority.MEDIUM
                         and a["lower_priority_to"] == Priority.LOW):
                    f.priority = a["lower_priority_to"]
                    f.priority_why += f" | model lowered: {a.get('reason','')[:160]}"
            if a.get("caveat"):
                f.why = (f.why + f" (caveat: {a['caveat'][:200]})").strip()

        run.decision_source = "vertex_gemini_narrowed_rules"
        run.warn(f"the model pass narrowed {lowered} finding(s) and rejected "
                 f"{dropped}; no finding was added or raised, which the pass is "
                 f"not permitted to do.")
        # A rejected finding is kept at UNVERIFIED rather than deleted, so a
        # reader can see what was rejected and disagree.
        return findings

    # ------------------------------------------------------------------
    # reading
    # ------------------------------------------------------------------

    def _summary(self, clara: dict, rivals: list, findings: list, recs: list,
                 gate: dict, shots: dict) -> dict:
        from collections import Counter
        pri = Counter(f.priority for f in findings)
        return {
            "clara": {k: clara.get(k) for k in
                      ("name", "base_url", "pages_read", "pages_attempted",
                       "pages_blocked", "access_status", "image_variety",
                       "jobs_done", "jobs_missing")},
            "competitors": [{k: r.get(k) for k in
                             ("name", "base_url", "pages_read", "pages_blocked",
                              "access_status")} for r in rivals],
            "findings": len(findings),
            "high": pri.get(Priority.HIGH, 0),
            "medium": pri.get(Priority.MEDIUM, 0),
            "low": pri.get(Priority.LOW, 0),
            "gaps": sum(1 for f in findings if f.kind == FindingKind.GAP),
            "strengths": sum(1 for f in findings
                             if f.kind == FindingKind.STRENGTH),
            "limitations": sum(1 for f in findings
                              if f.kind == FindingKind.LIMITATION),
            "recommendations": len(recs),
            "completeness": gate,
            "screenshots": shots,
            "pages_read": sum(p.get("pages_read") or 0
                              for p in [clara] + list(rivals)),
            "pages_blocked": sum(p.get("pages_blocked") or 0
                                 for p in [clara] + list(rivals)),
        }

    def report(self, run_id: str | None = None) -> dict:
        """Everything the report page and the exports need, from storage."""
        rid = run_id or self.store.latest_run_id()
        if not rid:
            return {"run": None, "runs": []}
        run = self.store.run(rid) or {}
        return {
            "run": run,
            "runs": [{k: r[k] for k in ("run_id", "status", "clara_url",
                                        "started_at", "finished_at")}
                     for r in self.store.runs()],
            "sites": self.store.sites(rid),
            "pages": self.store.pages(rid),
            "findings": self.store.findings(rid),
            "recommendations": self.store.recommendations(rid),
            "summary": run.get("summary") or {},
            "warnings": run.get("warnings") or [],
            "browser": browser_status(),
            "generated_at": now_iso(),
        }
