"""
ToolUniverse adapter for GenePathwayAI.

Wraps the analyze_gene_pathways function as a ToolUniverse-compatible BaseTool
with @register_tool decorator for automatic discovery.

Usage:
    # Option 1: Import to register tool, then use via ToolUniverse
    from gene_pathway_tool.tooluniverse_adapter import GenePathwayAnalysisTool
    from tooluniverse import ToolUniverse
    tu = ToolUniverse()
    tu.load_tools()
    result = tu.run({
        "name": "gene_pathway_analysis",
        "arguments": {
            "genes": ["APOE", "APP", "PSEN1", "MAPT", "TREM2"],
            "disease_name": "Alzheimer's Disease",
            "mode": "single"
        }
    })

    # Option 2: Use directly without ToolUniverse framework
    tool = GenePathwayAnalysisTool()
    result = tool.run({
        "genes": ["APOE", "APP", "PSEN1"],
        "disease_name": "Alzheimer's Disease"
    })
"""

try:
    from tooluniverse.tool_registry import register_tool
    from tooluniverse.base_tool import BaseTool
    HAS_TOOLUNIVERSE = True
except ImportError:
    HAS_TOOLUNIVERSE = False

    def register_tool(name, config=None):
        def decorator(cls):
            cls._tool_config = config
            return cls
        return decorator

    class BaseTool:
        def run(self, arguments):
            raise NotImplementedError

from typing import Dict, Any

TOOL_CONFIG = {
    "name": "gene_pathway_analysis",
    "type": "GenePathwayAnalysisTool",
    "description": (
        "AI-powered gene pathway analysis tool. Combines GPT-5.1 pathway prediction, "
        "g:Profiler statistical enrichment, PubMed literature search, and iterative refinement "
        "to identify disease-relevant biological pathways from a gene list. Returns ranked pathways "
        "with p-values, literature evidence, AI reasoning paths, and drug target candidates. "
        "Supports 5 pathway categories: GO:BP, GO:MF, GO:CC, KEGG, and Reactome."
    ),
    "parameter": {
        "type": "object",
        "properties": {
            "genes": {
                "type": "array",
                "items": {"type": "string"},
                "description": "List of HGNC gene symbols to analyze (e.g., ['APOE', 'APP', 'PSEN1', 'MAPT', 'TREM2'])"
            },
            "disease_name": {
                "type": "string",
                "description": "Disease name for analysis context (e.g., 'Alzheimer\\'s Disease', 'Inflammatory Bowel Disease')"
            },
            "mode": {
                "type": "string",
                "enum": ["single", "iterative"],
                "default": "single",
                "description": "Analysis mode: 'single' (one-shot, faster) or 'iterative' (2 iterations with FDR-filtered refinement, more thorough)"
            },
            "top_n": {
                "type": "integer",
                "default": 30,
                "description": "Maximum number of pathways to return (default: 30)"
            },
            "include_drug_targets": {
                "type": "boolean",
                "default": True,
                "description": "Whether to include drug target analysis identifying druggable genes with existing or potential therapeutic compounds"
            },
            "include_reasoning": {
                "type": "boolean",
                "default": True,
                "description": "Whether to include per-category AI reasoning paths explaining pathway predictions"
            }
        },
        "required": ["genes", "disease_name"]
    }
}


@register_tool('GenePathwayAnalysisTool', config=TOOL_CONFIG)
class GenePathwayAnalysisTool(BaseTool):
    """
    GenePathwayAI - AI-powered gene pathway analysis for disease research.

    Pipeline:
    1. GPT-5.1 predicts 50 pathways (5 categories x 10) with detailed reasoning
    2. g:Profiler performs statistical enrichment analysis
    3. Cross-validation matches GPT predictions against g:Profiler results
    4. GPT Auto-Rank with 4 evidence sources (pathway description, disease pathology, p-value, PubMed literature)
    5. Drug target identification (GPT + known targets database)

    Supports diseases: Alzheimer's, Parkinson's, IBD, MS, ALS, RA, T2D, and custom diseases.
    """

    def run(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        from .pipeline import analyze_gene_pathways

        genes = arguments.get("genes", [])
        disease_name = arguments.get("disease_name", "")

        if not genes:
            return {
                "success": False,
                "error": "No genes provided. Please supply a list of HGNC gene symbols.",
                "example": "genes: ['APOE', 'APP', 'PSEN1', 'MAPT', 'TREM2']"
            }

        if not disease_name:
            return {
                "success": False,
                "error": "No disease_name provided. Please specify the disease context.",
                "example": "disease_name: 'Alzheimer\\'s Disease'"
            }

        if isinstance(genes, str):
            genes = [g.strip() for g in genes.replace(',', ' ').split() if g.strip()]

        try:
            result = analyze_gene_pathways(
                genes=genes,
                disease_name=disease_name,
                mode=arguments.get("mode", "single"),
                top_n=arguments.get("top_n", 30),
                include_drug_targets=arguments.get("include_drug_targets", True),
                include_reasoning=arguments.get("include_reasoning", True)
            )

            result["success"] = True
            result["summary"] = {
                "total_pathways": len(result.get("pathways", [])),
                "total_drug_targets": len(result.get("drug_targets", [])),
                "categories_covered": list(set(
                    p.get("category", "") for p in result.get("pathways", [])
                )),
                "top_pathway": result["pathways"][0]["name"] if result.get("pathways") else "None",
                "analysis_mode": arguments.get("mode", "single")
            }

            return result

        except Exception as e:
            return {
                "success": False,
                "error": f"Analysis failed: {str(e)}",
                "partial_results": {}
            }
