import json
from typing import Any, Dict, List


def build_reasoning_audit_prompts(
    *,
    disease_name: str,
    iteration: int,
    category: str,
    genes: List[str],
    generated_records: List[Dict[str, Any]],
    validated_records: List[Dict[str, Any]],
    failed_records: List[Dict[str, Any]],
    feedback: str = None,
) -> Dict[str, str]:
    """Build the system/user prompts for post-hoc reasoning trace generation."""
    gene_list_text = ', '.join(map(str, genes[:200]))
    if len(genes) > 200:
        gene_list_text += f", ... ({len(genes)} genes total)"

    system_prompt = (
        "You are a scientific audit assistant for pathway analysis. "
        "Summarize the evidence already produced by a pathway-generation run. "
        "Do not generate new pathway candidates. Do not claim access to hidden model reasoning."
    )

    user_prompt = f"""
Generate a post-hoc audit trace for one completed pathway-generation iteration.

Important:
- The pathway candidates have already been generated as JSON.
- g:Profiler/FDR validation has already been performed.
- This audit trace is an externalized summary of generated records and validation outcomes.
- It must not introduce new pathway candidates or change the generated pathway list.

Disease/module: {disease_name}
Iteration: {iteration}
Database category: {category}
Input genes ({len(genes)}): {gene_list_text}

Previous validation feedback used for this generation, if any:
{feedback or 'N/A'}

Generated JSON pathway records for this category:
{json.dumps(generated_records, indent=2)}

FDR-supported generated pathways for this category:
{json.dumps(validated_records, indent=2)}

Generated pathways that matched g:Profiler but did not pass FDR for this category:
{json.dumps(failed_records, indent=2)}

Return exactly one <REASONING> block using these fields:

<REASONING>
Strategy: [2-3 sentences summarizing the observed generation strategy from the JSON records, not hidden model thinking]
Gene_analysis: [2-3 sentences on module gene signals visible from key_genes and intersections]
Database_focus: [1-2 sentences explaining how {category} shaped the generated terms]
Key_gene_functions: [2-3 sentences naming dominant gene functions or protein classes supported by generated/validated records]
Pathway_selection_rationale: [2-3 sentences explaining why the generated pathway family was biologically plausible]
Biological_evidence: [1-2 sentences linking validated pathways to disease biology]
Learned_from_feedback: [2-3 sentences; use N/A for iteration 1 if no feedback]
Pathway_guidance: [2-3 sentences on what FDR-supported pathways suggest for interpretation or the next iteration]
Category_adjustments: [1-2 sentences on category-specific lessons]
Validation_reflection: [1-2 sentences comparing FDR-supported and failed generated terms]
Failure_analysis: [1-3 sentences naming failed terms and likely reasons for failure; use N/A if none]
Bottleneck_diagnosis: [1-2 sentences diagnosing specificity, annotation granularity or module-support bottlenecks]
Cell_context: [1-2 sentences on plausible disease-relevant cell/tissue context supported by validated pathways and genes; mark as interpretive if evidence is indirect]
Relevance_strength_with_disease: [High/Medium/Low] - [brief justification based on validated pathway support]
</REASONING>
"""

    return {
        "system_prompt": system_prompt,
        "user_prompt": user_prompt,
    }
