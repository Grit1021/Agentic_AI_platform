from typing import Any, List

from .module_loading import ensure_backend_paths

ensure_backend_paths()

from iterative_gpt_agent_framework import IterativeGPTAgentFramework

from .agents.feedback_agent import FeedbackAgent


class RefinedIterativeGPTAgentFramework(IterativeGPTAgentFramework):
    """Iterative framework wired to the refined Feedback Agent."""

    def __init__(self, *args, feedback_agent: FeedbackAgent = None, **kwargs):
        super().__init__(*args, **kwargs)
        self.feedback_agent = feedback_agent or FeedbackAgent()

    def _generate_feedback_prompt(
        self,
        iteration_feedback: Any,
        genes: List[str],
        disease_name: str,
        history: List[Any] = None,
    ) -> str:
        return self.feedback_agent.build_feedback_prompt(
            context=self,
            iteration_feedback=iteration_feedback,
            genes=genes,
            disease_name=disease_name,
            history=history,
        )

    def _generate_feedback_prompt_pvalue_only(
        self,
        iteration_feedback: Any,
        genes: List[str],
        disease_name: str,
        history: List[Any] = None,
    ) -> str:
        return self.feedback_agent.build_pvalue_only_feedback_prompt(
            context=self,
            iteration_feedback=iteration_feedback,
            genes=genes,
            disease_name=disease_name,
            history=history,
        )
