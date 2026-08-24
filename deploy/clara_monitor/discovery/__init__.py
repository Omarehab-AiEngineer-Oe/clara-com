"""The self-expanding half of the trend system.

Two loops, both bounded, both auditable, neither allowed to trust itself:

    sources   a trusted feed -> an article -> a publisher we did not know ->
              its feed -> validated -> scored -> activated -> scanned next time
    topics    uncategorised signals -> clustered -> evidence gate -> pattern ->
              tested against the whole corpus -> merged or activated ->
              history reclassified

The hand-curated `trend_sources.py` and `trend_topics.py` remain the seed and are
never written to. Discovery adds rows to the database; the active set is the seed
plus whatever earned its place. Disabling every discovered row returns the system
to the original 35 feeds and 86 patterns with one UPDATE, which is the property
that makes automatic expansion safe to switch on.
"""

from .config import (ACTIVE, CANDIDATE, DISABLED, DISCOVERED, MERGED, REJECTED,
                     SEED, VALIDATED, DiscoveryConfig)
from .feeds import discover_feeds, normalise_url, registrable_domain, validate_feed
from .sources import run_source_discovery, score_source, to_source_objects
from .store import DiscoveryStore
from .topics import cluster, make_pattern, run_topic_discovery, test_pattern

__all__ = [
    "DiscoveryConfig", "DiscoveryStore",
    "discover_feeds", "validate_feed", "normalise_url", "registrable_domain",
    "run_source_discovery", "score_source", "to_source_objects",
    "run_topic_discovery", "cluster", "make_pattern", "test_pattern",
    "SEED", "DISCOVERED", "CANDIDATE", "VALIDATED", "ACTIVE", "REJECTED",
    "MERGED", "DISABLED",
]
