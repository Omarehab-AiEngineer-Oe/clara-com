"""The competitor-intelligence agent layer.

Seven specialists behind one orchestrator, each with a prompt in `prompts/agents/`
and a deterministic implementation of the same contract in this package. The
shared vocabulary lives in `contracts.py`, so "VERIFIED" and "ACTIVE" mean one
thing across all of them.
"""

from .action import ActionRecommendationAgent
from .arrangement import ContentArrangementAgent
from .collection import CompetitorDataCollectionAgent
from .discovery import CompetitorDiscoveryAgent
from .intelligence import CompetitorIntelligenceAgent
from .offers import LiveCompetitorOffersAgent
from .orchestrator import Orchestrator
from .store import IntelStore
from .verification import CompetitorVerificationAgent

__all__ = [
    "Orchestrator", "IntelStore",
    "CompetitorDiscoveryAgent", "CompetitorDataCollectionAgent",
    "LiveCompetitorOffersAgent", "CompetitorVerificationAgent",
    "CompetitorIntelligenceAgent", "ActionRecommendationAgent",
    "ContentArrangementAgent",
]
