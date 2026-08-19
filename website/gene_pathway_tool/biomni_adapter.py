"""
Biomni adapter for GenePathwayAI.

Provides the function and tool description in Biomni's expected format
for integration into biomni/tool/ and biomni/tool/tool_description/.

Usage (after copying to Biomni repo):
    1. Copy analyze_gene_pathways_biomni() to biomni/tool/genomics.py (or new file)
    2. Copy BIOMNI_TOOL_DESCRIPTION to biomni/tool/tool_description/genomics.py
    3. Create test prompt and submit PR

Standalone usage:
    from gene_pathway_tool.biomni_adapter import analyze_gene_pathways_biomni
    result = analyze_gene_pathways_biomni(
        genes=["APOE", "APP", "PSEN1"],
        disease_name="Alzheimer's Disease"
    )
"""

from typing import List, Optional


def analyze_gene_pathways_biomni(
    genes: List[str],
    disease_name: str,
    mode: str = "single",
    top_n: int = 30,
    include_drug_targets: bool = True,
    include_reasoning: bool = True,
) -> dict:
    """
    AI-powered gene pathway analysis combining GPT prediction, g:Profiler enrichment,
    PubMed literature search, and iterative refinement.

    Identifies disease-relevant biological pathways from a gene list across 5 categories:
    GO:BP, GO:MF, GO:CC, KEGG, and Reactome. Returns ranked pathways with statistical
    significance, literature evidence, AI reasoning paths, and drug target candidates.

    Args:
        genes: List of HGNC gene symbols (e.g., ["APOE", "APP", "PSEN1", "MAPT"])
        disease_name: Disease name for analysis context (e.g., "Alzheimer's Disease")
        mode: "single" for one-shot analysis or "iterative" for 2-iteration refinement
        top_n: Maximum number of pathways to return (default: 30)
        include_drug_targets: Include drug target analysis (default: True)
        include_reasoning: Include AI reasoning paths (default: True)

    Returns:
        dict with keys:
            pathways: Ranked list with name, p_value, score, category, description, literature
            reasoning: Per-category AI analysis (overall_strategy, gene_analysis, etc.)
            drug_targets: Druggable genes with compounds and development status
            category_stats: Matching statistics per pathway category
            metadata: Analysis metadata (disease config, gene count, mode)
    """
    from .pipeline import analyze_gene_pathways

    return analyze_gene_pathways(
        genes=genes,
        disease_name=disease_name,
        mode=mode,
        top_n=top_n,
        include_drug_targets=include_drug_targets,
        include_reasoning=include_reasoning,
    )


BIOMNI_TOOL_DESCRIPTION = [
    {
        "description": (
            "AI-powered gene pathway analysis combining GPT-5.1 pathway prediction, "
            "g:Profiler statistical enrichment, PubMed literature search, and iterative "
            "refinement. Identifies disease-relevant biological pathways from a gene list "
            "across 5 categories (GO:BP, GO:MF, GO:CC, KEGG, Reactome). Returns ranked "
            "pathways with p-values, literature evidence, AI reasoning paths, and drug "
            "target candidates."
        ),
        "name": "analyze_gene_pathways_biomni",
        "required_parameters": [
            {
                "default": None,
                "description": "List of HGNC gene symbols to analyze (e.g., ['APOE', 'APP', 'PSEN1', 'MAPT', 'TREM2'])",
                "name": "genes",
                "type": "List[str]",
            },
            {
                "default": None,
                "description": "Disease name for analysis context (e.g., 'Alzheimer\\'s Disease', 'Inflammatory Bowel Disease')",
                "name": "disease_name",
                "type": "str",
            },
        ],
        "optional_parameters": [
            {
                "default": "single",
                "description": "Analysis mode: 'single' (one-shot, faster) or 'iterative' (2 iterations with FDR-filtered refinement)",
                "name": "mode",
                "type": "str",
            },
            {
                "default": 30,
                "description": "Maximum number of pathways to return",
                "name": "top_n",
                "type": "int",
            },
            {
                "default": True,
                "description": "Whether to include drug target analysis identifying druggable genes",
                "name": "include_drug_targets",
                "type": "bool",
            },
            {
                "default": True,
                "description": "Whether to include per-category AI reasoning paths",
                "name": "include_reasoning",
                "type": "bool",
            },
        ],
    }
]


BIOMNI_TEST_PROMPTS = [
    "Analyze the following Alzheimer's disease genes and identify the top enriched pathways: APOE, APP, PSEN1, MAPT, TREM2, BIN1, CLU, ABCA7, CD33, CR1",
    "Use gene pathway analysis to find pathways related to Inflammatory Bowel Disease for genes: NOD2, IL23R, ATG16L1, IRGM, IL10, TNF, CARD9",
    "Perform iterative gene pathway analysis for Parkinson's disease genes SNCA, LRRK2, PARK7, PINK1, PRKN and identify drug targets",
]
