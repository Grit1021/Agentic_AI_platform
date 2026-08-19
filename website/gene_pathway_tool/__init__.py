"""
GenePathwayAI Tool - AI-powered gene pathway analysis module.

Standalone Python module for integration with ToolUniverse, Biomni,
or any platform that accepts Python function-level tools.

Usage:
    from gene_pathway_tool import analyze_gene_pathways

    result = analyze_gene_pathways(
        genes=["APOE", "APP", "PSEN1", "MAPT", "TREM2"],
        disease_name="Alzheimer's Disease",
        mode="single"  # or "iterative" for 2-iteration refinement
    )

    # result["pathways"] - Ranked pathways with scores, p-values, literature
    # result["reasoning"] - Per-category AI reasoning paths
    # result["drug_targets"] - Drug target candidates
    # result["category_stats"] - Matching statistics
    # result["metadata"] - Analysis metadata
"""

from .pipeline import analyze_gene_pathways
from .config import get_disease_configuration

__version__ = "1.0.0"
__all__ = ["analyze_gene_pathways", "get_disease_configuration"]
