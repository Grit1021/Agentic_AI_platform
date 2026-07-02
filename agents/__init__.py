from .biological_ranking_agent import BiologicalRankingAgent, gpt_rank_pathways
from .feedback_agent import FeedbackAgent
from .statistical_validation_agent import StatisticalValidationAgent

__all__ = [
    "BiologicalRankingAgent",
    "FeedbackAgent",
    "HypothesisGenerationAgent",
    "StatisticalValidationAgent",
    "gpt_rank_pathways",
]


def __getattr__(name):
    if name == "HypothesisGenerationAgent":
        from .hypothesis_generation_agent import HypothesisGenerationAgent

        return HypothesisGenerationAgent
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
