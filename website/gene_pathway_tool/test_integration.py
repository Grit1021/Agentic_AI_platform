"""
Test script to verify GenePathwayAI deployment readiness for ToolUniverse and Biomni.

Run: python -m gene_pathway_tool.test_integration
"""

import json
import sys


def test_core_imports():
    print("1. Testing core module imports...")
    from gene_pathway_tool import analyze_gene_pathways, get_disease_configuration
    from gene_pathway_tool.config import CATEGORIES, CATEGORY_CODES, SYSTEM_PROMPTS
    from gene_pathway_tool.reasoning_parser import parse_reasoning_from_response
    from gene_pathway_tool.pipeline import convert_pathways_to_output_format
    print("   OK: All core modules import successfully")
    return True


def test_disease_config():
    print("2. Testing disease configuration...")
    from gene_pathway_tool.config import get_disease_configuration, ABBREVIATION_EXPANSION

    diseases = [
        "Alzheimer's Disease", "Parkinson's Disease",
        "Inflammatory Bowel Disease", "Multiple Sclerosis",
        "Amyotrophic Lateral Sclerosis", "Rheumatoid Arthritis",
        "Type 2 Diabetes"
    ]

    for disease in diseases:
        config = get_disease_configuration(disease)
        assert config["mesh_id"], f"Missing mesh_id for {disease}"
        assert config["full_name"] == disease
        assert config["disease_code"], f"Missing disease_code for {disease}"

    print(f"   OK: {len(diseases)} disease configs validated")
    print(f"   OK: {len(ABBREVIATION_EXPANSION)} abbreviation expansions available")
    return True


def test_reasoning_parser():
    print("3. Testing reasoning parser...")
    from gene_pathway_tool.reasoning_parser import parse_reasoning_from_response

    test_input = """## Overall Strategy
Analyzed gene-disease relationships using functional annotation databases.

## Gene Analysis
The gene set shows strong enrichment in neuroinflammation pathways.

## Learned from Previous Iteration
N/A (First iteration or no feedback)

## Cell Context
Primary affected cell types include cortical neurons and microglia.

## Relevance Strength with Disease
High - Strong mechanistic links to disease hallmarks."""

    result = parse_reasoning_from_response(test_input)
    assert result is not None, "Parser returned None"
    assert "overall_strategy" in result, "Missing overall_strategy"
    assert "cell_context" in result, "Missing cell_context"
    assert "learned_from_previous_iteration" not in result, "N/A field should be filtered"
    print(f"   OK: Parser extracted {len(result)} sections (N/A fields filtered)")
    return True


def test_tooluniverse_adapter():
    print("4. Testing ToolUniverse adapter...")
    from gene_pathway_tool.tooluniverse_adapter import GenePathwayAnalysisTool, TOOL_CONFIG

    assert TOOL_CONFIG["name"] == "gene_pathway_analysis"
    assert TOOL_CONFIG["type"] == "GenePathwayAnalysisTool"
    assert "parameter" in TOOL_CONFIG
    assert "properties" in TOOL_CONFIG["parameter"]

    props = TOOL_CONFIG["parameter"]["properties"]
    assert "genes" in props
    assert "disease_name" in props
    assert "mode" in props
    assert props["genes"]["type"] == "array"
    assert props["mode"]["enum"] == ["single", "iterative"]
    assert TOOL_CONFIG["parameter"]["required"] == ["genes", "disease_name"]

    tool = GenePathwayAnalysisTool()

    result = tool.run({"genes": [], "disease_name": "Test"})
    assert result["success"] is False
    assert "error" in result

    result = tool.run({"genes": ["APOE"], "disease_name": ""})
    assert result["success"] is False

    print("   OK: ToolUniverse adapter validated")
    print(f"   OK: Tool config has {len(props)} parameters")
    print(f"   OK: Required params: {TOOL_CONFIG['parameter']['required']}")
    return True


def test_biomni_adapter():
    print("5. Testing Biomni adapter...")
    from gene_pathway_tool.biomni_adapter import (
        analyze_gene_pathways_biomni,
        BIOMNI_TOOL_DESCRIPTION,
        BIOMNI_TEST_PROMPTS
    )

    assert isinstance(BIOMNI_TOOL_DESCRIPTION, list)
    assert len(BIOMNI_TOOL_DESCRIPTION) == 1

    desc = BIOMNI_TOOL_DESCRIPTION[0]
    assert "description" in desc
    assert "name" in desc
    assert desc["name"] == "analyze_gene_pathways_biomni"
    assert "required_parameters" in desc
    assert "optional_parameters" in desc
    assert len(desc["required_parameters"]) == 2
    assert len(desc["optional_parameters"]) == 4

    req_names = [p["name"] for p in desc["required_parameters"]]
    assert "genes" in req_names
    assert "disease_name" in req_names

    opt_names = [p["name"] for p in desc["optional_parameters"]]
    assert "mode" in opt_names
    assert "top_n" in opt_names

    for param in desc["required_parameters"] + desc["optional_parameters"]:
        assert "name" in param
        assert "description" in param
        assert "type" in param

    assert len(BIOMNI_TEST_PROMPTS) >= 3

    print("   OK: Biomni adapter validated")
    print(f"   OK: Tool description: {len(desc['required_parameters'])} required, {len(desc['optional_parameters'])} optional params")
    print(f"   OK: {len(BIOMNI_TEST_PROMPTS)} test prompts available")
    return True


def test_mcp_spec():
    print("6. Testing MCP specification...")
    from gene_pathway_tool.tool_description import register_as_mcp_tool

    spec = register_as_mcp_tool()
    assert spec["name"] == "gene_pathway_analysis"
    assert "inputSchema" in spec
    assert spec["inputSchema"]["type"] == "object"
    assert "genes" in spec["inputSchema"]["properties"]
    assert "disease_name" in spec["inputSchema"]["properties"]
    assert spec["inputSchema"]["required"] == ["genes", "disease_name"]

    spec_json = json.dumps(spec, indent=2)
    assert len(spec_json) > 100

    print("   OK: MCP spec validated")
    print(f"   OK: MCP JSON schema size: {len(spec_json)} chars")
    return True


def test_package_metadata():
    print("7. Testing package metadata...")
    import gene_pathway_tool

    assert hasattr(gene_pathway_tool, '__version__')
    assert gene_pathway_tool.__version__ == "1.0.0"
    assert hasattr(gene_pathway_tool, 'analyze_gene_pathways')
    assert hasattr(gene_pathway_tool, 'get_disease_configuration')

    print(f"   OK: Package version {gene_pathway_tool.__version__}")
    print(f"   OK: Exports: {gene_pathway_tool.__all__}")
    return True


def main():
    print("=" * 60)
    print("GenePathwayAI Deployment Readiness Tests")
    print("=" * 60)
    print()

    tests = [
        test_core_imports,
        test_disease_config,
        test_reasoning_parser,
        test_tooluniverse_adapter,
        test_biomni_adapter,
        test_mcp_spec,
        test_package_metadata,
    ]

    passed = 0
    failed = 0

    for test in tests:
        try:
            if test():
                passed += 1
            else:
                failed += 1
                print(f"   FAIL: {test.__name__}")
        except Exception as e:
            failed += 1
            print(f"   FAIL: {test.__name__}: {e}")
        print()

    print("=" * 60)
    print(f"Results: {passed}/{passed + failed} tests passed")
    if failed == 0:
        print("STATUS: READY FOR DEPLOYMENT")
    else:
        print(f"STATUS: {failed} TESTS FAILED")
    print("=" * 60)

    print()
    print("Deployment Checklist:")
    print("-" * 40)
    print("[ToolUniverse]")
    print("  1. pip install gene-pathway-tool[tooluniverse]")
    print("  2. from gene_pathway_tool.tooluniverse_adapter import GenePathwayAnalysisTool")
    print("  3. OR: Submit PR to mims-harvard/ToolUniverse")
    print("     - Copy tooluniverse_adapter.py to tooluniverse/tools/")
    print("     - Register in __init__.py (4 locations)")
    print()
    print("[Biomni]")
    print("  1. pip install gene-pathway-tool[biomni]")
    print("  2. Copy biomni_adapter.py function to biomni/tool/genomics.py")
    print("  3. Copy BIOMNI_TOOL_DESCRIPTION to biomni/tool/tool_description/genomics.py")
    print("  4. Include test prompts and submit PR")
    print()
    print("[MCP Remote]")
    print("  1. Deploy as MCP server (FastAPI/Flask)")
    print("  2. Use register_as_mcp_tool() for tool spec")
    print("  3. Register with ToolUniverse SMCP")

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
