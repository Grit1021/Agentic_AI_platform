from typing import Any, List

from ..prompts import build_feedback_prompt, build_pvalue_only_feedback_prompt


class FeedbackAgent:
    """Builds biological and p-value-only feedback prompts between iterations."""

    def build_feedback_prompt(
        self,
        context: Any,
        iteration_feedback: Any,
        genes: List[str],
        disease_name: str,
        history: List[Any] = None,
    ) -> str:
        return build_feedback_prompt(
            context=context,
            iteration_feedback=iteration_feedback,
            genes=genes,
            disease_name=disease_name,
            history=history,
        )

    def build_pvalue_only_feedback_prompt(
        self,
        context: Any,
        iteration_feedback: Any,
        genes: List[str],
        disease_name: str,
        history: List[Any] = None,
    ) -> str:
        return build_pvalue_only_feedback_prompt(
            context=context,
            iteration_feedback=iteration_feedback,
            genes=genes,
            disease_name=disease_name,
            history=history,
        )
