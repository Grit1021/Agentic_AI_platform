import inspect
from typing import Optional, List

from .llm_client import LLMClient


def generate_disease_connection(
    pathway_name: str,
    disease_name: str = "Alzheimer's Disease",
    connection_agent=None,
    pathway_description: str = "",
    evidence_score: float = None,
    source: str = None,
    p_value: float = None,
    key_genes: Optional[List[str]] = None,
    intersection_genes: Optional[List[str]] = None,
    module_id: str = None,
) -> str:
    """
    Generate mechanistic connection integrating enrichment analysis and network topology.

    Uses AG2 DiseaseConnectionAgent if available, otherwise falls back to GPT prompt.

    Parameters
    ----------
    pathway_name : str
        Pathway name
    disease_name : str
        Disease name
    connection_agent : object, optional
        AG2 agent for explanations
    pathway_description : str
        Optional pathway description
    evidence_score : float, optional
        Evidence strength 0-1
    source : str, optional
        Pathway source (GO:BP, KEGG, etc.)
    p_value : float, optional
        Enrichment p-value from g:Profiler
    key_genes : list, optional
        Key genes identified by GPT
    intersection_genes : list, optional
        Genes in module overlapping with pathway
    module_id : str, optional
        Module ID from network analysis

    Returns
    -------
    str
        Mechanistic explanation
    """
    # Try AG2 agent first (if available)
    if connection_agent is not None and hasattr(connection_agent, 'explain_connection'):
        try:
            explanation = _try_ag2_agent(
                connection_agent, pathway_name, disease_name,
                pathway_description, evidence_score, source,
                p_value, key_genes, intersection_genes, module_id
            )
            return explanation
        except Exception as e:
            print(f"⚠️  AG2 explanation failed for '{pathway_name}': {e}")

    # Fallback: GPT prompt
    return _generate_via_llm(
        pathway_name, disease_name, pathway_description,
        evidence_score, source, p_value, key_genes,
        intersection_genes, module_id
    )


def _try_ag2_agent(
    agent, pathway_name, disease_name, pathway_description,
    evidence_score, source, p_value, key_genes,
    intersection_genes, module_id
) -> str:
    """Try to use AG2 DiseaseConnectionAgent."""
    sig = inspect.signature(agent.explain_connection)

    if 'key_genes' in sig.parameters:
        explanation = agent.explain_connection(
            pathway_name=pathway_name,
            disease_name=disease_name,
            pathway_description=pathway_description,
            evidence_score=evidence_score,
            source=source,
            p_value=p_value,
            key_genes=key_genes,
            intersection_genes=intersection_genes,
            module_id=module_id,
        )
    else:
        explanation = agent.explain_connection(
            pathway_name=pathway_name,
            disease_name=disease_name,
            pathway_description=pathway_description,
            evidence_score=evidence_score,
            source=source,
        )

    # Handle dict responses from AG2
    if isinstance(explanation, dict):
        for key in ['explanation', 'text', 'content']:
            if key in explanation:
                return explanation[key]
        return str(explanation)

    return explanation


def _generate_via_llm(
    pathway_name, disease_name, pathway_description,
    evidence_score, source, p_value, key_genes,
    intersection_genes, module_id
) -> str:
    """Generate disease connection via GPT prompt."""
    try:
        llm = LLMClient(model="gpt-5.1", timeout=60.0)

        # Build enrichment context
        enrichment_context = ""
        if p_value is not None:
            sig_level = (
                "extremely significant" if p_value < 1e-10
                else "highly significant" if p_value < 1e-5
                else "significant"
            )
            enrichment_context += f"\nEnrichment P-value: {p_value:.2e} ({sig_level})"

        # Build network topology context
        network_context = ""
        if module_id:
            network_context += f"\nModule: {module_id} (co-expressed gene network)"

        if intersection_genes and len(intersection_genes) > 0:
            gene_list = ", ".join(intersection_genes[:10])
            if len(intersection_genes) > 10:
                gene_list += f" ... ({len(intersection_genes)} total)"
            network_context += f"\nEnriched genes: {gene_list}"

        if key_genes and len(key_genes) > 0:
            key_gene_list = ", ".join(key_genes[:5])
            network_context += f"\nKey driver genes: {key_gene_list}"

        prompt = f"""Explain the mechanistic connection between the pathway "{pathway_name}" and {disease_name} in 1-2 concise sentences.

PATHWAY INFORMATION:
Pathway: {pathway_name}
Description: {pathway_description[:200] if pathway_description else 'N/A'}
Source: {source or 'Unknown'}
{enrichment_context}
{network_context}

REQUIREMENTS:
1. Integrate BOTH enrichment statistics AND network topology
2. Focus on mechanistic connections to {disease_name} hallmarks
3. Be specific and mechanistic. Start directly with explanation.

{disease_name} Connection:"""

        print(f"   🤖 Generating {disease_name} connection for: {pathway_name[:50]}...")

        explanation = llm.generate(
            system_prompt=(
                "You are a biomedical expert. Provide a single concise sentence "
                "explaining the mechanistic connection."
            ),
            user_prompt=prompt,
            max_tokens=200,
            temperature=0.7,
        )

        # Clean up common prefixes
        for prefix in [
            "The mechanistic connection is that ",
            "Mechanistically, ",
            "This pathway connects through ",
        ]:
            if explanation.lower().startswith(prefix.lower()):
                explanation = explanation[len(prefix):]
                break

        # Ensure starts with capital
        if explanation:
            explanation = explanation[0].upper() + explanation[1:]

        print(f"   ✅ {disease_name} connection generated ({len(explanation)} chars)")
        return explanation

    except Exception as e:
        import traceback
        print(f"❌ LLM disease connection generation failed for '{pathway_name}':")
        traceback.print_exc()

        # Final fallback: evidence-based template
        if evidence_score and evidence_score > 0.7:
            return (
                f"Strong statistical enrichment (evidence score: {evidence_score:.2f}) "
                f"suggests involvement in {disease_name} pathology through "
                f"{pathway_name.lower()} mechanisms."
            )
        return (
            f"Pathway enriched in {disease_name}-related genes; "
            f"mechanistic connection requires further investigation."
        )
