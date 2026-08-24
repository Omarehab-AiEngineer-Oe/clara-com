"""Configuration for the discovery loop.

Every bound the loop obeys is here, in one place, because the dangerous failure
mode of a self-expanding system is not a bad source — it is an unbounded one. A
crawler that discovers ten publishers per publisher exhausts a politeness budget
and a disk in an afternoon.

The defaults are deliberately conservative. `max_new_sources_per_scan = 10` and
`max_discovery_depth = 2` mean a single run can grow the registry by a tenth and
can follow a chain two hops from something already trusted — enough to compound,
slow enough to inspect. Raise them once the discovery graph has been read a few
times and looks sane, not before.

Two thresholds do the real work. A candidate at 0.80 or better activates itself;
between 0.60 and 0.79 it is kept and watched but never scanned; below 0.60 it is
rejected with the reason recorded. The gap between the two is intentional: a
system that activates everything it does not reject has no opinion.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path

from ..config import DATA_DIR

CONFIG_PATH = DATA_DIR / "discovery_config.json"


@dataclass
class SourceDiscoveryConfig:
    """Bounds and thresholds for finding new publishers."""
    enabled: bool = True

    # Growth bounds. The registry can compound, but only slowly enough that a
    # person can still read what changed between two runs.
    max_new_per_scan: int = 10
    max_discovery_requests: int = 100
    max_depth: int = 2
    max_candidates_per_domain: int = 3

    # How many article pages to read per run looking for other publishers. This
    # is the expensive half of discovery and the only half that finds anything
    # new, so it is bounded here rather than left to grow with the corpus.
    article_sample: int = 15

    # Quality gates. The gap between the two is the point: everything that is
    # not rejected does not thereby become trusted.
    activation_threshold: float = 0.80
    candidate_threshold: float = 0.60

    cooldown_hours: int = 24
    revalidate_after_hours: int = 168      # a week
    disable_after_failures: int = 5

    # A feed has to actually carry the subject matter. Without this the loop
    # cheerfully adds a well-formed feed about motorbikes.
    min_relevant_entries: int = 2
    min_entries: int = 3


@dataclass
class TopicDiscoveryConfig:
    """Evidence a cluster needs before it becomes a subject."""
    enabled: bool = True

    # The three together are what separate a trend from one loud article. Any
    # one of them alone is satisfied by a single publisher writing twice.
    min_signals: int = 5
    min_publishers: int = 2
    min_days_seen: int = 2

    max_new_per_scan: int = 6
    cooldown_hours: int = 24

    # A generated pattern is tested against everything already collected. If it
    # matches more than this share of the corpus it is too broad to be a subject.
    max_corpus_match_ratio: float = 0.25
    min_pattern_precision: float = 0.60

    # Near-duplicate detection against the existing vocabulary.
    merge_similarity: float = 0.62


@dataclass
class DiscoveryConfig:
    enabled: bool = True
    sources: SourceDiscoveryConfig = field(default_factory=SourceDiscoveryConfig)
    topics: TopicDiscoveryConfig = field(default_factory=TopicDiscoveryConfig)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def load(cls, path: Path | None = None) -> "DiscoveryConfig":
        """File, then environment, then defaults.

        The environment override exists so a scheduled run can be tightened
        without editing a file the scheduler does not own — for example
        `CLARA_DISCOVERY_ENABLED=0` to freeze expansion during an investigation.
        """
        cfg = cls()
        p = path or CONFIG_PATH
        if p.exists():
            try:
                raw = json.loads(p.read_text(encoding="utf-8"))
            except (ValueError, OSError):
                raw = {}
            cfg.enabled = bool(raw.get("enabled", cfg.enabled))
            for section, obj in (("sources", cfg.sources), ("topics", cfg.topics)):
                for k, v in (raw.get(section) or {}).items():
                    if hasattr(obj, k):
                        setattr(obj, k, type(getattr(obj, k))(v))

        env = os.environ.get("CLARA_DISCOVERY_ENABLED")
        if env is not None:
            cfg.enabled = env.strip().lower() not in ("0", "false", "no", "")
        return cfg

    def save(self, path: Path | None = None) -> Path:
        p = path or CONFIG_PATH
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(self.to_dict(), indent=2), encoding="utf-8")
        return p


# States, named once so the store and the reports cannot drift apart.
SEED = "seed"
DISCOVERED = "discovered"

CANDIDATE = "candidate"
VALIDATED = "validated"
ACTIVE = "active"
REJECTED = "rejected"
MERGED = "merged"
DISABLED = "disabled"

SOURCE_STATES = (CANDIDATE, VALIDATED, ACTIVE, REJECTED, DISABLED)
TOPIC_STATES = (CANDIDATE, VALIDATED, ACTIVE, REJECTED, MERGED)
