import math
import pandas as pd

from .config import get_disease_configuration, CATEGORY_CODES
from .gpt_predictor import gpt_predict_pathways, gpt_predict_pathways_with_context
from .gprofiler_client import run_gprofiler_enrichment
from .matcher import match_gpt_with_gprofiler_detailed
from .ranker import gpt_rank_pathways
from .drug_targets import generate_drug_targets


def convert_pathways_to_output_format(pathways_df: pd.DataFrame) -> list:
    pathways_list = []
    categories_order = ['GO:BP', 'GO:MF', 'GO:CC', 'KEGG', 'REAC']
    per_category = {}

    for cat in categories_order:
        cat_df = pathways_df[pathways_df['source'] == cat] if 'source' in pathways_df.columns else pd.DataFrame()
        per_category[cat] = cat_df

    pathways_per_cat = 4
    selected_rows = []

    for cat in categories_order:
        cat_df = per_category.get(cat, pd.DataFrame())
        if not cat_df.empty:
            selected_rows.extend(cat_df.head(pathways_per_cat).to_dict('records'))

    remaining = 20 - len(selected_rows)
    if remaining > 0 and not pathways_df.empty:
        already_selected = set(r.get('name', '') for r in selected_rows)
        for _, row in pathways_df.iterrows():
            if row.get('name', '') not in already_selected:
                selected_rows.append(row.to_dict())
                if len(selected_rows) >= 20:
                    break

    rank = 1
    for row in selected_rows[:20]:
        p_val = row.get('p_value', 0.05)
        score = min(100, max(0, -10 * math.log10(float(p_val) + 1e-300)))

        literature = row.get('related_literature', []) if isinstance(row.get('related_literature'), list) else []
        pmid_list = []
        for lit in literature[:5]:
            if isinstance(lit, dict):
                pmid = lit.get('pmid', lit.get('PMID', ''))
                if pmid:
                    pmid_list.append(str(pmid))

        disease_connection = row.get('disease_connection', '')
        raw_original_desc = row.get('description', '')
        original_desc = '' if pd.isna(raw_original_desc) else str(raw_original_desc).strip()
        final_description = disease_connection if disease_connection else original_desc
        intersection_genes = (
            [str(gene).strip() for gene in row.get('intersections', []) if str(gene).strip()]
            if isinstance(row.get('intersections'), list)
            else []
        )
        pathway_id = str(
            row.get('pathway_id') or row.get('native') or row.get('term_id') or row.get('id') or ''
        ).strip()

        pathways_list.append({
            "name": row.get('name', 'Unknown'),
            "pathway_id": pathway_id,
            "p_value": float(p_val),
            "score": round(score, 1),
            "category": row.get('source', 'GO:BP'),
            "genes": ','.join(intersection_genes) if intersection_genes else str(row.get('intersection_size', 0)),
            "intersection_genes": intersection_genes,
            "pathway_description": original_desc,
            "disease_interpretation": disease_connection,
            "description": final_description,
            "gpt_rank": rank,
            "gpt_predicted": row.get('gpt_validated', False),
            "literature": literature[:5],
            "pmids": pmid_list
        })
        rank += 1

    return pathways_list


def analyze_gene_pathways(
    genes: list,
    disease_name: str,
    mode: str = "single",
    top_n: int = 30,
    include_drug_targets: bool = True,
    include_reasoning: bool = True
) -> dict:
    """
    Main entry point for GenePathwayAI analysis.

    Runs the full AI-powered pathway analysis pipeline:
    1. GPT predicts 50 pathways (5 categories x 10)
    2. g:Profiler enrichment analysis
    3. Match GPT predictions with g:Profiler results
    4. GPT Auto-Rank matched pathways with PubMed evidence
    5. (Optional) Drug target identification

    Args:
        genes: List of gene symbols (e.g., ["APOE", "APP", "PSEN1", ...])
        disease_name: Disease name (e.g., "Alzheimer's Disease")
        mode: "single" for single-shot analysis, "iterative" for 2-iteration refinement
        top_n: Maximum number of pathways to return (default: 30)
        include_drug_targets: Whether to include drug target analysis (default: True)
        include_reasoning: Whether to include AI reasoning paths (default: True)

    Returns:
        dict with keys:
            - pathways: List of ranked pathways with scores, p-values, literature
            - reasoning: Dict of per-category AI reasoning (if include_reasoning=True)
            - drug_targets: List of drug target candidates (if include_drug_targets=True)
            - category_stats: Matching statistics per category
            - metadata: Analysis metadata (disease config, gene count, mode)
    """
    if not genes:
        return {"error": "No genes provided", "pathways": [], "reasoning": {}, "drug_targets": []}

    if isinstance(genes, str):
        genes = [g.strip() for g in genes.replace(',', ' ').split() if g.strip()]

    disease_config = get_disease_configuration(disease_name)
    disease_description = disease_config.get('description', '')

    result = {
        "pathways": [],
        "reasoning": {},
        "drug_targets": [],
        "category_stats": {},
        "metadata": {
            "disease": disease_name,
            "disease_config": disease_config,
            "gene_count": len(genes),
            "mode": mode,
            "genes": genes[:50]
        }
    }

    if mode == "iterative":
        pathways, reasoning, stats = _run_iterative_analysis(
            genes, disease_name, disease_description, top_n
        )
    else:
        pathways, reasoning, stats = _run_single_analysis(
            genes, disease_name, disease_description, top_n
        )

    result["pathways"] = pathways
    result["category_stats"] = stats

    if include_reasoning:
        result["reasoning"] = reasoning

    if include_drug_targets and pathways:
        result["drug_targets"] = generate_drug_targets(genes, pathways)

    return result


def _run_single_analysis(genes, disease_name, disease_description, top_n):
    print(f"=== Single-Shot Analysis: {disease_name} ({len(genes)} genes) ===")

    predicted_pathways, pathway_details, reasoning_by_category = gpt_predict_pathways(
        genes=genes,
        disease_name=disease_name,
        disease_description=disease_description,
        iteration=1
    )

    enrichment_results = run_gprofiler_enrichment(genes)
    if enrichment_results.empty:
        return [], reasoning_by_category, {}

    matched_pathways, category_stats = match_gpt_with_gprofiler_detailed(
        gpt_predictions=predicted_pathways,
        pathway_details=pathway_details,
        gprofiler_results=enrichment_results
    )

    if matched_pathways.empty:
        matched_pathways = enrichment_results.sort_values('p_value').head(top_n)
    else:
        original_count = len(matched_pathways)
        matched_pathways = matched_pathways[matched_pathways['p_value'] < 0.05].copy()
        if matched_pathways.empty:
            matched_pathways = enrichment_results[enrichment_results['p_value'] < 0.05].sort_values('p_value').head(top_n)

    ranked_pathways = gpt_rank_pathways(matched_pathways, disease_name, disease_description, top_n=top_n)
    pathways_list = convert_pathways_to_output_format(ranked_pathways)

    print(f"=== Single-Shot Analysis Complete: {len(pathways_list)} pathways ===")
    return pathways_list, reasoning_by_category, category_stats


def _run_iterative_analysis(genes, disease_name, disease_description, top_n):
    print(f"=== Iterative Analysis (2 iterations): {disease_name} ({len(genes)} genes) ===")

    all_reasoning = {}
    all_stats = {}
    retained_pathways = []
    final_matched = pd.DataFrame()

    for iteration in range(1, 3):
        print(f"\n--- Iteration {iteration}/2 ---")

        if iteration == 1:
            predicted_pathways, pathway_details, reasoning_by_category = gpt_predict_pathways(
                genes=genes,
                disease_name=disease_name,
                disease_description=disease_description,
                iteration=iteration
            )
        else:
            predicted_pathways, pathway_details, reasoning_by_category = gpt_predict_pathways_with_context(
                genes=genes,
                disease_name=disease_name,
                disease_description=disease_description,
                retained_pathways=retained_pathways,
                iteration=iteration
            )

        all_reasoning[f"iteration_{iteration}"] = reasoning_by_category

        enrichment_results = run_gprofiler_enrichment(genes)
        if enrichment_results.empty:
            continue

        retained_names = {p.get('name', '') for p in retained_pathways} if retained_pathways else set()

        matched_pathways, category_stats = match_gpt_with_gprofiler_detailed(
            gpt_predictions=predicted_pathways,
            pathway_details=pathway_details,
            gprofiler_results=enrichment_results,
            retained_pathway_names=retained_names
        )

        all_stats[f"iteration_{iteration}"] = category_stats

        fdr_filtered = matched_pathways[matched_pathways['p_value'] < 0.05].copy()
        retained_pathways = fdr_filtered.to_dict('records')

        if not fdr_filtered.empty:
            final_matched = pd.concat([final_matched, fdr_filtered], ignore_index=True)

    if final_matched.empty:
        return [], all_reasoning, all_stats

    final_matched = final_matched.drop_duplicates(subset=['name'], keep='first')

    ranked_pathways = gpt_rank_pathways(final_matched, disease_name, disease_description, top_n=top_n)
    pathways_list = convert_pathways_to_output_format(ranked_pathways)

    print(f"=== Iterative Analysis Complete: {len(pathways_list)} pathways ===")
    return pathways_list, all_reasoning, all_stats
