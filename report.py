import os
import time
import pandas as pd
import numpy as np
from typing import List, Dict, Any

from .disease_connection import generate_disease_connection


def generate_pathway_summary(
    aggregated_pathways: pd.DataFrame,
    final_module_results: List[Dict[str, Any]],
    module_metadata: Dict[str, Any],
    disease_name: str,
    summary_dir: str,
) -> str:
    """
    Generate comprehensive pathway ranking summary text file.

    Parameters
    ----------
    aggregated_pathways : pd.DataFrame
        All aggregated pathways from Phase 2
    final_module_results : list
        Module results from Phase 2
    module_metadata : dict
        Per-module metadata
    disease_name : str
        Full disease name
    summary_dir : str
        Directory to save summary

    Returns
    -------
    str
        Path to the generated summary file
    """
    os.makedirs(summary_dir, exist_ok=True)
    summary_file = os.path.join(summary_dir, "summary_pathway_ranking.txt")

    # Score the aggregated pathways
    scored_pathways = _compute_composite_scores(aggregated_pathways)

    # Sort by composite score
    top_pathways = scored_pathways.sort_values('composite_score', ascending=False)

    with open(summary_file, 'w') as f:
        _write_header(f, disease_name)
        _write_scoring_methodology(f, disease_name)
        _write_top_pathways_table(f, top_pathways, disease_name)
        _write_category_table(f, top_pathways)
        _write_module_characterization(f, final_module_results, module_metadata, disease_name)
        _write_category_ranking(f, scored_pathways, disease_name)
        _write_module_summary(f, final_module_results, module_metadata)
        _write_overall_summary(f, scored_pathways, final_module_results)

    print(f"✅ Pathway ranking summary saved: {summary_file}")
    return summary_file


# ============================================================================
# SCORING
# ============================================================================

def _compute_composite_scores(df: pd.DataFrame) -> pd.DataFrame:
    """Compute per-category GPT composite scores."""
    scored = df.copy()

    if 'gpt_rank' in scored.columns and scored['gpt_rank'].notna().any():
        def calc_score(row):
            if pd.isna(row['gpt_rank']):
                return 0.0
            category = row.get('source', 'Unknown')
            cat_df = scored[scored['source'] == category]
            max_rank = cat_df['gpt_rank'].max()
            if max_rank > 0:
                return 1.0 - (row['gpt_rank'] - 1) / max_rank
            return 0.0

        scored['gpt_score'] = scored.apply(calc_score, axis=1)
        scored['composite_score'] = scored['gpt_score'] * 100
    else:
        if 'evidence_score' not in scored.columns:
            scored['evidence_score'] = scored['p_value'].apply(
                lambda p: min(-np.log10(p) if p > 0 else 10, 10) / 10
            )
        scored['composite_score'] = scored['evidence_score'] * 100

    return scored


# ============================================================================
# REPORT SECTIONS
# ============================================================================

def _write_header(f, disease_name):
    f.write("=" * 80 + "\n")
    f.write("COMPREHENSIVE PATHWAY-LEVEL ANALYSIS\n")
    f.write(f"GPT Auto-Ranking Version - {disease_name}\n")
    f.write(f"Generated: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
    f.write("=" * 80 + "\n\n")


def _write_scoring_methodology(f, disease_name):
    f.write("SCORING METHODOLOGY (GPT AUTO-RANKING VERSION):\n")
    f.write("=" * 80 + "\n")
    f.write("GPT Auto-Ranking Process:\n")
    f.write("  For each pathway, GPT analyzes 4 raw information sources:\n")
    f.write("  1. Pathway Description: Biological function from g:Profiler\n")
    f.write(f"  2. Disease Pathology: {disease_name} characteristics from MeSH/NCBI\n")
    f.write("  3. Statistical Significance: FDR-adjusted p-value\n")
    f.write(f"  4. PubMed Literature: Relevant papers linking pathway to {disease_name}\n\n")
    f.write("Final Composite Score: GPT_Score × 100 (0-100 scale)\n\n")


def _write_top_pathways_table(f, top_pathways, disease_name):
    f.write("PART 0: DETAILED PATHWAY STATISTICS TABLE\n")
    f.write("=" * 80 + "\n\n")

    f.write(f"| {'Pathway Name':<40} | {'p-value':>12} | {'GPT Score':>9} | "
            f"{'Source':<7} | {'Iter':>4} | {'Rank':>4} | "
            f"{'Key genes':<25} | {'Selected literatures (PMIDs)':<27} |\n")
    f.write(f"|{'-'*42}|{'-'*14}|{'-'*11}|{'-'*9}|{'-'*6}|{'-'*6}|"
            f"{'-'*27}|{'-'*29}|\n")

    for idx, (_, row) in enumerate(top_pathways.head(20).iterrows(), 1):
        name = row['name']
        display_name = name if len(name) <= 38 else name[:35] + "..."
        p_val = row['p_value']
        composite = row['composite_score']
        source = row.get('source', '?')
        iter_src = row.get('final_iteration', row.get('iteration', 'N/A'))
        gpt_rank_val = row.get('gpt_rank', 'N/A')
        iter_str = str(int(iter_src)) if pd.notna(iter_src) and iter_src != 'N/A' else 'N/A'
        rank_str = str(int(gpt_rank_val)) if pd.notna(gpt_rank_val) and gpt_rank_val != 'N/A' else 'N/A'
        key_genes, key_gene_list = _summarize_key_genes(row)
        lit_info = _summarize_literature(row)
        display_genes = key_genes if len(key_genes) <= 23 else key_genes[:20] + "..."
        display_lit = lit_info if len(lit_info) <= 25 else lit_info[:22] + "..."

        f.write(f"| {display_name:<40} | {p_val:>12.3e} | {composite:>9.1f} | "
                f"{source:<7} | {iter_str:>4} | {rank_str:>4} | "
                f"{display_genes:<25} | {display_lit:<27} |\n")

        # Disease connection
        connection = generate_disease_connection(
            pathway_name=row['name'],
            disease_name=disease_name,
            pathway_description=row.get('description', ''),
            evidence_score=composite / 100.0,
            source=source,
            p_value=p_val,
            key_genes=key_gene_list,
            intersection_genes=_split_gene_field(row.get('intersections', '')),
        )
        f.write(f"  └─ {disease_name} Connection: {connection}\n")

    f.write("\n" + "=" * 80 + "\n\n")


def _summarize_key_genes(row) -> tuple:
    """Return display text and gene list for GPT key genes or intersections."""
    gpt_key_genes = row.get('gpt_key_genes', '')
    genes_list = _split_gene_field(gpt_key_genes)
    if not genes_list:
        genes_list = _split_gene_field(row.get('key_genes', ''))
    if not genes_list:
        genes_list = _split_gene_field(row.get('intersections', ''))

    if not genes_list:
        return "N/A", []

    display = ', '.join(genes_list[:3])
    if len(genes_list) > 3:
        display += f" (+{len(genes_list) - 3})"
    return display, genes_list


def _split_gene_field(value) -> list:
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    if isinstance(value, tuple):
        return [str(v).strip() for v in value if str(v).strip()]
    if isinstance(value, str) and value and value.lower() not in {'nan', 'none'}:
        return [v.strip() for v in value.split(',') if v.strip()]
    return []


def _summarize_literature(row) -> str:
    """Extract PMID display text from literature_pmids or related_literature."""
    pmids_str = row.get('literature_pmids', None)
    if pmids_str is not None and pd.notna(pmids_str):
        pmids_str = str(pmids_str).strip()
        if pmids_str and pmids_str.lower() not in {'nan', 'none'}:
            return pmids_str

    related_lit = row.get('related_literature', None)
    if isinstance(related_lit, str) and related_lit and related_lit != '[]':
        try:
            import ast
            related_lit = ast.literal_eval(related_lit)
        except (ValueError, SyntaxError):
            related_lit = []

    if isinstance(related_lit, list) and related_lit:
        pmids = []
        for paper in related_lit[:5]:
            if isinstance(paper, dict):
                pmid = paper.get('pmid', paper.get('PMID', None))
                if pmid and pmid != 'N/A':
                    pmids.append(str(pmid))
        if pmids:
            return ', '.join(pmids)
        return f"{len(related_lit)} papers"

    num_pubs = row.get('num_publications', 0)
    try:
        if float(num_pubs) > 0:
            return f"{int(float(num_pubs))} papers"
    except (TypeError, ValueError):
        pass

    return "N/A"


def _write_category_table(f, top_pathways):
    f.write("TABLE 2: PATHWAYS BY CATEGORY (TOP RANKED IN EACH SOURCE)\n")
    f.write("-" * 80 + "\n\n")

    categories = {
        'GO:BP': 'Biological Process',
        'GO:MF': 'Molecular Function',
        'GO:CC': 'Cellular Component',
        'KEGG': 'KEGG Pathways',
        'REAC': 'Reactome Pathways',
    }

    for code, name in categories.items():
        cat_df = top_pathways[top_pathways['source'] == code]
        if len(cat_df) == 0:
            continue

        f.write(f"\n{'#' * 80}\n")
        f.write(f"# {code}: {name} ({len(cat_df)} pathways)\n")
        f.write(f"{'#' * 80}\n\n")

        f.write(f"| {'Rank':<4} | {'Pathway Name':<45} | {'p-value':<12} | "
                f"{'Composite':<9} |\n")
        f.write(f"|{'-'*6}|{'-'*47}|{'-'*14}|{'-'*11}|\n")

        for idx, (_, row) in enumerate(cat_df.head(10).iterrows(), 1):
            name_str = row['name'][:43] if len(row['name']) > 43 else row['name']
            f.write(f"| {idx:<4} | {name_str:<45} | {row['p_value']:<12.3e} | "
                    f"{row['composite_score']:<9.1f} |\n")

        f.write("\n")

    f.write("=" * 80 + "\n\n")


def _write_module_characterization(f, final_module_results, module_metadata, disease_name):
    f.write("PART 1: MODULE-SPECIFIC BIOLOGICAL CHARACTERIZATION\n")
    f.write("=" * 80 + "\n\n")

    module_groups = {res['module_id']: res for res in final_module_results}

    for m_id in sorted(module_groups.keys()):
        res = module_groups[m_id]
        f.write("-" * 80 + "\n")
        f.write(f"MODULE {m_id}: BIOLOGICAL CHARACTERIZATION\n")
        f.write("-" * 80 + "\n\n")

        val_count = len(res['filtered_pathways'])
        val_rate = res['validation_rate']
        f.write(f"Validated Pathways: {val_count}\n")
        f.write(f"Validation Rate: {val_rate:.1%}\n\n")

        module_pathways = res['filtered_pathways']
        if not module_pathways.empty:
            if 'gpt_rank' in module_pathways.columns:
                sorted_pw = module_pathways.sort_values('gpt_rank', ascending=True)
            else:
                sorted_pw = module_pathways.sort_values('p_value', ascending=True)

            f.write("TOP VALIDATED PATHWAYS:\n\n")
            for idx, (_, row) in enumerate(sorted_pw.head(10).iterrows(), 1):
                f.write(f"{idx}. {row['name']}\n")
                f.write(f"   p-value: {row['p_value']:.2e}\n")
                f.write(f"   Source: {row.get('source', 'Unknown')}\n\n")

    f.write("=" * 80 + "\n\n")


def _write_category_ranking(f, aggregated_pathways, disease_name):
    f.write("PART 2: COMPREHENSIVE PATHWAY RANKING\n")
    f.write("=" * 80 + "\n\n")

    categories = ['GO:BP', 'GO:MF', 'GO:CC', 'KEGG', 'REAC']
    category_names = {
        'GO:BP': 'Biological Process', 'GO:MF': 'Molecular Function',
        'GO:CC': 'Cellular Component', 'KEGG': 'KEGG Pathways',
        'REAC': 'Reactome Pathways',
    }

    if 'source' in aggregated_pathways.columns:
        for category in categories:
            cat_df = aggregated_pathways[aggregated_pathways['source'] == category].copy()
            if len(cat_df) == 0:
                continue

            if 'gpt_rank' in cat_df.columns:
                cat_df = cat_df.sort_values('gpt_rank')
            elif 'composite_score' in cat_df.columns:
                cat_df = cat_df.sort_values('composite_score', ascending=False)

            f.write("#" * 80 + "\n")
            f.write(f"# CATEGORY: {category} ({category_names[category]}) - {len(cat_df)} Pathways\n")
            f.write("#" * 80 + "\n\n")

            for idx, (_, row) in enumerate(cat_df.iterrows(), 1):
                f.write(f"Rank {idx}: {row['name']}\n")
                f.write(f"  P-Value: {row.get('p_value', 1.0):.2e}\n")
                if 'composite_score' in row and not pd.isna(row['composite_score']):
                    f.write(f"  GPT Composite Score: {row['composite_score']:.0f}/100\n")
                if 'module_id' in row:
                    f.write(f"  Module: {row['module_id']}\n")
                f.write("\n")

    f.write("=" * 80 + "\n\n")


def _write_module_summary(f, final_module_results, module_metadata):
    f.write("PART 3: MODULE-LEVEL SUMMARY\n")
    f.write("=" * 80 + "\n\n")

    module_groups = {res['module_id']: res for res in final_module_results}
    for m_id in sorted(module_groups.keys()):
        res = module_groups[m_id]
        f.write(f"### Module {m_id}\n")
        f.write(f"- Validated Pathways: {len(res['filtered_pathways'])}\n")
        f.write(f"- Validation Rate: {res['validation_rate']:.1%}\n\n")

    f.write("=" * 80 + "\n\n")


def _write_overall_summary(f, aggregated_pathways, final_module_results):
    f.write("PART 4: OVERALL ANALYSIS SUMMARY\n")
    f.write("=" * 80 + "\n\n")

    total = len(aggregated_pathways)
    unique = aggregated_pathways['name'].nunique()
    avg_rate = (
        sum(r['validation_rate'] for r in final_module_results) / len(final_module_results)
        if final_module_results else 0
    )

    f.write(
        f"Across {len(final_module_results)} modules, iterative analysis identified "
        f"{unique} unique pathways (total {total} instances) with "
        f"{avg_rate:.1%} average validation rate.\n\n"
    )

    if 'source' in aggregated_pathways.columns:
        source_counts = aggregated_pathways['source'].value_counts()
        if not source_counts.empty:
            dominant = source_counts.index[0]
            f.write(
                f"Dominant pathway source: {dominant} ({source_counts.iloc[0]} pathways, "
                f"{source_counts.iloc[0]/total*100:.1f}%)\n\n"
            )
