import os
from typing import Any, Dict, List

import pandas as pd

from .module_loading import ensure_backend_paths

ensure_backend_paths()

import multi_agent_analysis_full as backend_predictor
from api_cost_tracker import cost_tracker
from reasoning_parser import (
    parse_reasoning_from_response,
    print_reasoning_summary,
    save_reasoning_to_file,
)

from .prompts import PathwayPromptTemplates, build_reasoning_audit_prompts


def install_refined_prompt_templates():
    """
    Point the bundled predictor module at refined prompt templates.

    The backend generator methods reference ``PathwayPromptTemplates`` as a
    module global. Installing this binding lets refined reuse the mature
    generator implementation while keeping prompt ownership inside refined/.
    """
    backend_predictor.PathwayPromptTemplates = PathwayPromptTemplates


class HypothesisGenerationAgent(backend_predictor.GPT5PathwayGenerator):
    """Initial pathway-hypothesis generation agent using refined prompts."""

    def __init__(self, *args, **kwargs):
        install_refined_prompt_templates()
        super().__init__(*args, **kwargs)

    def generate_posthoc_audit_trace(
        self,
        genes: List[str],
        disease_name: str,
        gpt_prediction: Dict[str, Any],
        validated_pathways_df: pd.DataFrame,
        matched_pathways_df: pd.DataFrame = None,
        feedback: str = None,
        benchmark_config: dict = None,
        file_identifier: str = None,
        iteration: int = None,
        categories: List[str] = None,
    ) -> Dict[str, Dict[str, str]]:
        """Generate post-hoc audit traces using refined prompt builders."""
        if not self.available:
            return {}

        if not file_identifier or iteration is None:
            print("   ⚠️  Skipping post-hoc audit trace: file_identifier or iteration missing")
            return {}

        pathway_details = gpt_prediction.get('pathway_details', {}) or {}
        predicted_pathways = (
            gpt_prediction.get('predicted_pathways', [])
            or gpt_prediction.get('generated_pathways', [])
            or []
        )

        if categories is None:
            categories = ['GO:BP', 'GO:MF', 'GO:CC', 'KEGG', 'REAC']

        audit_traces = {}

        for category in categories:
            generated_records = self._generated_records(
                predicted_pathways, pathway_details, category
            )
            if not generated_records:
                continue

            validated_records = self._df_records(validated_pathways_df, category)
            failed_records = self._failed_records(matched_pathways_df, category)

            prompts = build_reasoning_audit_prompts(
                disease_name=disease_name,
                iteration=iteration,
                category=category,
                genes=genes,
                generated_records=generated_records,
                validated_records=validated_records,
                failed_records=failed_records,
                feedback=feedback,
            )

            api_params = {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": prompts["system_prompt"]},
                    {"role": "user", "content": prompts["user_prompt"]},
                ],
                "max_completion_tokens": 5000,
            }

            if benchmark_config:
                for key in ["temperature", "top_p", "presence_penalty", "frequency_penalty", "n"]:
                    if key in benchmark_config:
                        api_params[key] = benchmark_config[key]

            try:
                response = self.client.chat.completions.create(**api_params)
                cost_tracker.track(response)
                response_text = response.choices[0].message.content or ""
                reasoning = parse_reasoning_from_response(response_text)
                if reasoning:
                    print_reasoning_summary(reasoning, prefix="      ")
                    reasoning_path = os.path.join(
                        os.path.dirname(file_identifier) if os.path.dirname(file_identifier) else ".",
                        f"{os.path.basename(file_identifier)}_{category.replace(':', '_')}_reasoning.md",
                    )
                    if save_reasoning_to_file(
                        reasoning, reasoning_path, iteration, file_identifier, category
                    ):
                        print(f"      💾 Post-hoc audit trace saved: {reasoning_path}")
                    audit_traces[category] = reasoning
            except Exception as e:
                print(f"      ⚠️  Post-hoc audit trace failed for {category}: {e}")

        return audit_traces

    @staticmethod
    def _df_records(df: pd.DataFrame, category: str, max_rows: int = 20) -> List[Dict[str, Any]]:
        if df is None or df.empty:
            return []
        sub = df[df.get('source', '') == category] if 'source' in df.columns else df
        cols = [
            c for c in ['native', 'name', 'p_value', 'source', 'gpt_key_genes', 'intersections']
            if c in sub.columns
        ]
        records = []
        for _, row in sub.head(max_rows).iterrows():
            rec = {}
            for col in cols:
                val = row.get(col)
                if isinstance(val, (list, tuple)):
                    val = ', '.join(map(str, val[:20]))
                rec[col] = str(val)[:500]
            records.append(rec)
        return records

    @staticmethod
    def _generated_records(
        predicted_pathways: List[str],
        pathway_details: Dict[str, Any],
        category: str,
        max_rows: int = 20,
    ) -> List[Dict[str, Any]]:
        records = []
        for name in predicted_pathways:
            detail = pathway_details.get(name, {})
            if detail.get('source') != category:
                continue
            records.append({
                'name': name,
                'id': detail.get('pathway_id') or detail.get('go_id') or '',
                'key_genes': detail.get('key_genes', []),
                'mechanism_in_module': (
                    detail.get('mechanism_in_module')
                    or detail.get('rationale')
                    or detail.get('description', '')
                ),
                'disease_relevance': detail.get('disease_relevance', ''),
            })
            if len(records) >= max_rows:
                break
        return records

    @classmethod
    def _failed_records(
        cls,
        matched_pathways_df: pd.DataFrame,
        category: str,
        max_rows: int = 20,
    ) -> List[Dict[str, Any]]:
        if (
            matched_pathways_df is None
            or matched_pathways_df.empty
            or 'p_value' not in matched_pathways_df.columns
        ):
            return []
        try:
            matched_sub = (
                matched_pathways_df[matched_pathways_df.get('source', '') == category]
                if 'source' in matched_pathways_df.columns
                else matched_pathways_df
            )
            failed_df = matched_sub[matched_sub['p_value'] >= 0.05].copy()
            return cls._df_records(failed_df, category, max_rows=max_rows)
        except Exception:
            return []


RefinedGPT5PathwayPredictor = HypothesisGenerationAgent
GPT5PathwayPredictor = HypothesisGenerationAgent
