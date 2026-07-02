from typing import Any, List

import pandas as pd


def build_feedback_prompt(
    context: Any,
    iteration_feedback: Any,
    genes: List[str],
    disease_name: str,
    history: List[Any] = None,
) -> str:
    """
    Build the full biological feedback prompt used for the next iteration.

    ``context`` is the refined framework instance. It provides the existing
    hindsight generator used to add concise disease-pathway relevance notes.
    """
    validated = iteration_feedback.validated_pathways
    predicted = iteration_feedback.predicted_pathways
    not_validated = [p for p in predicted if p not in validated]
    gpt_pathways_df = iteration_feedback.validation_details.get(
        'gpt_filtered_pathways', pd.DataFrame()
    )

    high_quality_pathways = _ordered_pathways(gpt_pathways_df, validated, use_gpt_rank=True)
    base_disease_name = _base_disease_name(disease_name)

    n_matched_all = iteration_feedback.validation_details.get('n_matched_all', 0)
    n_fdr_filtered = iteration_feedback.validation_details.get('n_validated', len(validated))
    validation_rate = iteration_feedback.validation_rate

    feedback = f"""# Iteration {iteration_feedback.iteration} Feedback

## Validation Results

- **Predicted**: {len(predicted)} pathways
- **Matched (all p-values)**: {n_matched_all} pathways
- **FDR Validated (p<0.05)**: {n_fdr_filtered} pathways ({validation_rate:.1%} validation rate)

**Key Focus**: Predict pathways with clear mechanistic links to **{base_disease_name}** pathogenesis.

"""

    feedback += f"## ✅ High-Quality {base_disease_name}-Relevant Pathways (Keep & Expand)\n"
    if high_quality_pathways:
        feedback += (
            f"These pathways are statistically significant AND relevant to "
            f"{base_disease_name}:\n\n"
        )
        for i, pathway in enumerate(high_quality_pathways[:10], 1):
            feedback += f"{i}. **{pathway}**\n"
            if not gpt_pathways_df.empty:
                pw_row = gpt_pathways_df[gpt_pathways_df['name'] == pathway]
                if not pw_row.empty and hasattr(context, 'hindsight_generator'):
                    disease_context = context.hindsight_generator._get_pathway_disease_context(
                        pathway, disease_name, pw_row
                    )
                    if disease_context and disease_context.get('relevance'):
                        feedback += (
                            f"   - **Why disease-relevant**: "
                            f"{disease_context['relevance']}\n"
                        )
            feedback += "\n"
    else:
        feedback += (
            f"None - need to improve pathway quality and "
            f"{base_disease_name} relevance\n"
        )

    if high_quality_pathways:
        feedback += _retention_section(high_quality_pathways, gpt_pathways_df, detailed=True)
        feedback += f"""

## 💡 Disease-Relevant Pathway Expansion Examples

**Examples of good disease-relevant variations:**
- If "Sphingolipid metabolism" validated → try "Glycosphingolipid metabolism", "Ceramide metabolism"
- If "Autophagy" validated → try "Macroautophagy", "Chaperone-mediated autophagy"
- If "Proteasome degradation" validated → try "Ubiquitin-proteasome system", "Protein ubiquitination"
- If "Golgi apparatus" validated → try "Golgi membrane", "cis-Golgi network", "trans-Golgi network"

**CRITICAL**: Focus on pathways with established or hypothesized links to {base_disease_name} pathogenesis.
Avoid generic housekeeping pathways unless they have specific {base_disease_name} relevance.
"""

    feedback += _not_validated_section(
        not_validated,
        iteration_feedback.validation_details.get('gpt_matched_all', pd.DataFrame()),
        include_failure_reasoning=True,
        base_disease_name=base_disease_name,
    )

    feedback += f"""

## Core Guidance

Focus on the **validated** and **filtered** results above. For the next iteration:

1. **Keep validated pathways** - They show both statistical enrichment and {base_disease_name} relevance
2. **Expand in related directions** - Explore sub-pathways or related mechanisms of validated pathways
3. **Prioritize disease correlation** - Every pathway must have a clear mechanistic link to {base_disease_name}

For each predicted pathway, explain:
- **WHY** it is relevant to {base_disease_name} pathogenesis
- **WHICH** input genes serve as key drivers

---

## Category-Specific Guidance

### GO:BP (Biological Process)
Identify biological processes that connect the input genes to {base_disease_name} mechanisms. Cite specific genes as evidence. Use EXACT GO term names (ID format: GO:#######).

### GO:MF (Molecular Function)
Identify molecular activities (binding, catalysis, transport) dysregulated in {base_disease_name}. Explain how this activity contributes to disease pathology. Use EXACT GO term names (ID format: GO:#######).

### GO:CC (Cellular Component)
Identify cellular locations implicated in {base_disease_name} pathology. Explain how dysfunction at this location drives disease. Use EXACT GO term names (ID format: GO:#######).

### KEGG Pathways
Map functional signals to OFFICIAL KEGG pathway names. Prioritize disease-specific pathways and signaling cascades relevant to {base_disease_name} over generic metabolism. Use EXACT KEGG names (ID format: hsa#####).

### Reactome Pathways
Identify mechanistically detailed pathways from Reactome's hierarchy. Prefer specific child pathways over broad parent categories. Use EXACT Reactome names (ID format: R-HSA-######).

**Key**: For ALL categories, use database-official nomenclature to ensure g:Profiler matching.

"""

    feedback += _target_prediction_section(
        f" with clear mechanistic links to **{base_disease_name}**"
    )
    return feedback


def build_pvalue_only_feedback_prompt(
    context: Any,
    iteration_feedback: Any,
    genes: List[str],
    disease_name: str,
    history: List[Any] = None,
) -> str:
    """Build the p-value-only ablation feedback prompt."""
    validated = iteration_feedback.validated_pathways
    predicted = iteration_feedback.predicted_pathways
    not_validated = [p for p in predicted if p not in validated]
    gpt_pathways_df = iteration_feedback.validation_details.get(
        'gpt_filtered_pathways', pd.DataFrame()
    )

    high_quality_pathways = _ordered_pathways(gpt_pathways_df, validated, use_gpt_rank=False)
    n_matched_all = iteration_feedback.validation_details.get('n_matched_all', 0)
    n_fdr_filtered = iteration_feedback.validation_details.get('n_validated', len(validated))
    validation_rate = iteration_feedback.validation_rate

    feedback = f"""# Iteration {iteration_feedback.iteration} Feedback

## Validation Results

- **Predicted**: {len(predicted)} pathways
- **Matched (all p-values)**: {n_matched_all} pathways
- **FDR Validated (p<0.05)**: {n_fdr_filtered} pathways ({validation_rate:.1%} validation rate)

"""

    feedback += "## ✅ FDR-Validated Pathways\n"
    if high_quality_pathways:
        feedback += "These pathways passed FDR validation (p<0.05):\n\n"
        for i, pathway in enumerate(high_quality_pathways[:10], 1):
            if not gpt_pathways_df.empty:
                pw_row = gpt_pathways_df[gpt_pathways_df['name'] == pathway]
                if not pw_row.empty:
                    p_val = pw_row['p_value'].values[0]
                    source = pw_row['source'].values[0] if 'source' in pw_row.columns else ''
                    feedback += f"{i}. **{pathway}** (p={p_val:.2e}, {source})\n"
                else:
                    feedback += f"{i}. **{pathway}**\n"
            else:
                feedback += f"{i}. **{pathway}**\n"
    else:
        feedback += "None validated in previous iteration.\n"

    if high_quality_pathways:
        feedback += _retention_section(high_quality_pathways, gpt_pathways_df, detailed=False)

    feedback += _not_validated_section(
        not_validated,
        iteration_feedback.validation_details.get('gpt_matched_all', pd.DataFrame()),
        include_failure_reasoning=False,
        base_disease_name=_base_disease_name(disease_name),
    )

    feedback += """\n## Guidance for Next Iteration

1. **Keep retained pathways** listed above with exact names
2. **Improve statistical significance** - aim for p<0.05 FDR-adjusted
3. **Replace non-validated pathways** with new predictions

## Naming Format Requirements

- GO:BP / GO:MF / GO:CC: Use EXACT GO term names (ID format: GO:#######)
- KEGG: Use OFFICIAL KEGG pathway names (ID format: hsa#####)
- Reactome: Use EXACT Reactome names (ID format: R-HSA-######)

**Key**: Use database-official nomenclature to ensure g:Profiler matching.

"""
    feedback += _target_prediction_section("")
    return feedback


def _ordered_pathways(gpt_pathways_df: pd.DataFrame, validated: list, use_gpt_rank: bool) -> list:
    if gpt_pathways_df.empty:
        return validated
    if use_gpt_rank and 'gpt_rank' in gpt_pathways_df.columns:
        return gpt_pathways_df.sort_values(by='gpt_rank', ascending=True)['name'].tolist()
    if 'p_value' in gpt_pathways_df.columns:
        return gpt_pathways_df.sort_values(by='p_value', ascending=True)['name'].tolist()
    return gpt_pathways_df['name'].tolist() if 'name' in gpt_pathways_df.columns else validated


def _base_disease_name(disease_name: str) -> str:
    if '_Module_' in disease_name:
        return disease_name.split('_Module_')[0]
    return disease_name.split('_')[0]


def _retention_section(high_quality_pathways: list, gpt_pathways_df: pd.DataFrame, detailed: bool) -> str:
    section = f"""\n\n## 🔒 CRITICAL: Retained Pathways (MUST Keep with Exact Names & IDs)

You MUST predict the following {min(len(high_quality_pathways), 10)} pathways in the next iteration using EXACTLY the same names and IDs as listed below. DO NOT rename or modify these pathway names.

**Retained Pathways:**
"""
    for i, pathway_name in enumerate(high_quality_pathways[:10], 1):
        if not gpt_pathways_df.empty:
            pw_row = gpt_pathways_df[gpt_pathways_df['name'] == pathway_name]
            if not pw_row.empty:
                pw_id = pw_row['native'].values[0] if 'native' in pw_row.columns else 'N/A'
                source = pw_row['source'].values[0] if 'source' in pw_row.columns else 'N/A'
                section += f"{i}. **{pathway_name}** (ID: {pw_id}, Source: {source})\n"
            else:
                section += f"{i}. **{pathway_name}**\n"
        else:
            section += f"{i}. **{pathway_name}**\n"

    if detailed:
        section += """

**CRITICAL INSTRUCTIONS:**
- Use EXACTLY the same pathway names as listed above (character-for-character match)
- Use the EXACT IDs provided (do not change GO IDs, KEGG IDs, or Reactome IDs)
- These pathways have been validated with both statistical significance AND high disease relevance
- DO NOT "optimize" or "improve" these names - exact retention is required for tracking

"""
    else:
        section += """
**CRITICAL INSTRUCTIONS:**
- Use EXACTLY the same pathway names as listed above (character-for-character match)
- Use the EXACT IDs provided
- DO NOT rename or modify these pathway names

"""
    return section


def _not_validated_section(
    not_validated: list,
    gpt_matched_all_df: pd.DataFrame,
    include_failure_reasoning: bool,
    base_disease_name: str,
) -> str:
    section = "\n## ❌ Not Validated Pathways\n"
    if not_validated:
        for i, pathway in enumerate(not_validated[:15], 1):
            p_info = ""
            if not gpt_matched_all_df.empty and 'name' in gpt_matched_all_df.columns:
                pw_row = gpt_matched_all_df[gpt_matched_all_df['name'] == pathway]
                if not pw_row.empty:
                    p_val = pw_row['p_value'].values[0] if 'p_value' in pw_row.columns else None
                    source = pw_row['source'].values[0] if 'source' in pw_row.columns else ''
                    p_info = f" (p={p_val:.2e}, {source})" if p_val is not None else f" ({source})"
            section += f"{i}. {pathway}{p_info}\n"

        if len(not_validated) > 15:
            section += f"... and {len(not_validated) - 15} more\n"

        if include_failure_reasoning:
            section += (
                "\n**Why these failed**: These pathways were predicted but did not "
                "pass FDR validation (p≥0.05). "
            )
            section += (
                "Consider why they failed — were they too generic, lacking specific "
                f"module gene support, or mechanistically distant from {base_disease_name}?\n"
            )
    else:
        section += "No data available on failed predictions.\n"
    return section


def _target_prediction_section(disease_modifier: str) -> str:
    return f"""
## Target Predictions for Next Iteration

Predict **50 pathways total** (10 per category){disease_modifier}:
- 10 GO:BP (Biological Process) terms
- 10 GO:MF (Molecular Function) terms
- 10 GO:CC (Cellular Component) terms
- 10 KEGG pathways
- 10 Reactome pathways

**Important**: The retained pathways listed above count toward your 10-per-category quota. Generate new predictions to fill remaining slots.
"""
