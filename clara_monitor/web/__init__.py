"""Website Analysis: what Clara's site says, what competitors say, what to change.

The third module, beside Prices and Trends, and deliberately separate from both.
Prices compares numbers on product pages. Trends measures what publishers are
covering. This compares *presentation* — the copy, the calls to action and the
images a visitor actually sees — and turns the difference into ranked, evidenced
recommendations.

    contracts   the six objects, the taxonomies, and absent-vs-not-observed
    collect     bounded page discovery through the one guarded network path
    rubric      one standard, applied identically to Clara and every competitor
    analyze     per-site reading: strengths, weak messages, missing elements
    compare     equivalent pages, gaps, and what Clara does better
    recommend   the seven required parts, priority and confidence
    orchestrator the eleven-step workflow
    store       six tables in the existing SQLite file
    page        the setup screen and the report
    export      Word, PDF and JSON

The rule that shapes every file: a page that could not be read never becomes a
missing feature. `PresenceState.NOT_OBSERVED` exists so the report can say "we
could not tell" in the one place where a confident guess would do the most
damage.
"""

from .contracts import (AccessStatus, AnalysisRun, Confidence, Evidence,
                        Finding, FindingCategory, FindingKind, ImageKind, Page,
                        PageType, PresenceState, Priority, Recommendation,
                        RunStatus, Website, WebsiteRole)
from .store import WebStore

__all__ = ["AccessStatus", "AnalysisRun", "Confidence", "Evidence", "Finding",
           "FindingCategory", "FindingKind", "ImageKind", "Page", "PageType",
           "PresenceState", "Priority", "Recommendation", "RunStatus",
           "Website", "WebsiteRole", "WebStore"]
