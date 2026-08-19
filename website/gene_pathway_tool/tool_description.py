"""
Tool descriptions and registration metadata for ToolUniverse and Biomni integration.

ToolUniverse: https://github.com/mims-harvard/ToolUniverse
Biomni: https://github.com/snap-stanford/Biomni

Both platforms expect Python function-level tools with structured descriptions.
"""

TOOL_UNIVERSE_DESCRIPTION = {
    "name": "GenePathwayAI",
    "description": (
        "AI-powered gene pathway analysis tool that combines GPT-5.1 pathway prediction, "
        "g:Profiler enrichment analysis, PubMed literature search, and iterative refinement "
        "to identify disease-relevant biological pathways from a gene list. "
        "Returns ranked pathways with statistical significance, literature evidence, "
        "AI reasoning paths, and drug target candidates."
    ),
    "category": "Genomics & Pathway Analysis",
    "input_type": "gene_list",
    "output_type": "pathway_analysis_report",
    "parameters": {
        "genes": {
            "type": "list[str]",
            "description": "List of gene symbols (e.g., ['APOE', 'APP', 'PSEN1']). Accepts HGNC gene symbols.",
            "required": True
        },
        "disease_name": {
            "type": "str",
            "description": "Name of the disease to analyze (e.g., 'Alzheimer\\'s Disease'). Used for GPT context and PubMed search.",
            "required": True
        },
        "mode": {
            "type": "str",
            "description": "Analysis mode: 'single' (one-shot) or 'iterative' (2 iterations with refinement). Default: 'single'.",
            "required": False,
            "default": "single",
            "enum": ["single", "iterative"]
        },
        "top_n": {
            "type": "int",
            "description": "Maximum number of pathways to return. Default: 30.",
            "required": False,
            "default": 30
        },
        "include_drug_targets": {
            "type": "bool",
            "description": "Whether to include drug target analysis. Default: True.",
            "required": False,
            "default": True
        },
        "include_reasoning": {
            "type": "bool",
            "description": "Whether to include per-category AI reasoning paths. Default: True.",
            "required": False,
            "default": True
        }
    },
    "output_schema": {
        "pathways": "List of ranked pathways with: name, p_value, score, category (GO:BP/GO:MF/GO:CC/KEGG/REAC), genes, description, gpt_rank, literature (PubMed refs), pmids",
        "reasoning": "Per-category AI reasoning: overall_strategy, gene_analysis, database_focus, key_gene_functions, pathway_selection_rationale, biological_evidence, cell_context, relevance_strength_with_disease",
        "drug_targets": "List of drug targets with: gene, drug, status (FDA Approved/Phase X/Preclinical), indication",
        "category_stats": "Matching statistics: predicted, matched, fdr_filtered per category",
        "metadata": "Analysis metadata: disease config, gene count, mode"
    },
    "dependencies": ["openai", "gprofiler-official", "biopython", "pandas"],
    "env_vars": ["OPENAI_API_KEY", "ENTREZ_EMAIL"],
    "example_usage": """
from gene_pathway_tool import analyze_gene_pathways

result = analyze_gene_pathways(
    genes=["APOE", "APP", "PSEN1", "MAPT", "TREM2", "BIN1", "CLU", "ABCA7"],
    disease_name="Alzheimer's Disease",
    mode="iterative"
)

for pw in result["pathways"][:5]:
    print(f"{pw['gpt_rank']}. {pw['name']} (p={pw['p_value']:.2e}, {pw['category']})")
    print(f"   {pw['description']}")
"""
}


BIOMNI_TOOL_DESCRIPTION = {
    "tool_name": "gene_pathway_analysis",
    "tool_description": (
        "Analyze a list of disease-associated genes to identify enriched biological pathways. "
        "Uses GPT-5.1 for pathway prediction and ranking, g:Profiler for statistical enrichment, "
        "and PubMed for literature evidence. Supports single-shot and iterative refinement modes. "
        "Returns ranked pathways across 5 categories (GO:BP, GO:MF, GO:CC, KEGG, Reactome) "
        "with disease connection explanations, AI reasoning paths, and drug target candidates."
    ),
    "input_description": (
        "A JSON object with: "
        "'genes' (required, list of HGNC gene symbols), "
        "'disease_name' (required, string), "
        "'mode' (optional, 'single' or 'iterative', default 'single'), "
        "'top_n' (optional, int, default 30)"
    ),
    "output_description": (
        "A JSON object containing: "
        "'pathways' (ranked list with name, p_value, score, category, description, literature), "
        "'reasoning' (per-category AI analysis), "
        "'drug_targets' (druggable genes with compounds), "
        "'category_stats' (matching statistics), "
        "'metadata' (analysis info)"
    ),
    "function_name": "analyze_gene_pathways",
    "module_path": "gene_pathway_tool",
    "example_input": {
        "genes": ["APOE", "APP", "PSEN1", "MAPT", "TREM2"],
        "disease_name": "Alzheimer's Disease",
        "mode": "single"
    }
}


def get_tooluniverse_registration():
    """Return ToolUniverse-compatible tool registration dict."""
    return TOOL_UNIVERSE_DESCRIPTION


def get_biomni_registration():
    """Return Biomni-compatible tool registration dict."""
    return BIOMNI_TOOL_DESCRIPTION


def register_as_mcp_tool():
    """
    Generate MCP (Model Context Protocol) tool specification for remote registration.

    ToolUniverse supports SMCP (Standardized MCP) for remote tool registration.
    This returns the MCP-compatible specification.
    """
    return {
        "name": "gene_pathway_analysis",
        "description": TOOL_UNIVERSE_DESCRIPTION["description"],
        "inputSchema": {
            "type": "object",
            "properties": {
                "genes": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of HGNC gene symbols"
                },
                "disease_name": {
                    "type": "string",
                    "description": "Disease name for context"
                },
                "mode": {
                    "type": "string",
                    "enum": ["single", "iterative"],
                    "default": "single",
                    "description": "Analysis mode"
                },
                "top_n": {
                    "type": "integer",
                    "default": 30,
                    "description": "Max pathways to return"
                }
            },
            "required": ["genes", "disease_name"]
        }
    }
