import time
import json
import re
import pandas as pd
from typing import Optional, Dict, Any

from ..llm_client import LLMClient
from ..tools.pubmed import search_pubmed_for_pathway
from ..config import get_pubmed_disease_name


class BiologicalRankingAgent:
    """Biological relevance ranking layer for pathway candidates."""

    def rank_pathways(
        self,
        pathways_df: pd.DataFrame,
        disease_name: str,
        disease_description: str,
        query_agent,
        framework: 'IterativeGPTAgentFramework',
        batch_size: int = 20,
        top_n: int = 200,
        memory_context: str = None,
    ) -> pd.DataFrame:
        return gpt_rank_pathways(
            pathways_df=pathways_df,
            disease_name=disease_name,
            disease_description=disease_description,
            query_agent=query_agent,
            framework=framework,
            batch_size=batch_size,
            top_n=top_n,
            memory_context=memory_context,
        )


def gpt_rank_pathways(
    pathways_df: pd.DataFrame,
    disease_name: str,
    disease_description: str,
    query_agent,
    framework: 'IterativeGPTAgentFramework',
    batch_size: int = 20,
    top_n: int = 200,
    memory_context: str = None,
) -> pd.DataFrame:
    """
    GPT auto-ranks pathways by synthesizing 5 raw information sources WITHIN EACH CATEGORY.

    **PER-CATEGORY RANKING**: Pathways are ranked independently within each biological database
    (GO:BP, GO:MF, GO:CC, KEGG, REAC), then merged back. This ensures each category gets
    fair representation and avoids cross-category position bias.

    This is the REVISED approach: GPT analyzes raw information directly,
    without pre-computed TF-IDF or BioBERT scores.

    Parameters
    ----------
    pathways_df : pd.DataFrame
        DataFrame with pathway information (name, description, p_value, source, etc.)
    disease_name : str
        Disease name for context
    disease_description : str
        Disease description from NCBI
    query_agent : object
        Query agent for PubMed search (may be None)
    framework : IterativeGPTAgentFramework
        For GPT API access
    batch_size : int
        Pathways per GPT call (default: 20)
    top_n : int
        Maximum pathways to process
    memory_context : str, optional
        Memory bank context for cross-disease learning

    Returns
    -------
    pd.DataFrame
        Original pathways with 'gpt_rank' column.
        NOTE: gpt_rank is WITHIN-CATEGORY rank (e.g., Rank 1 in GO:BP, Rank 1 in KEGG).
    """
    print(f"  🤖 GPT Auto-Ranking (Raw Information): {len(pathways_df)} pathways...")

    # DO NOT re-filter here as it causes pathway count mismatch and NaN gpt_rank values

    print(f"     Ranking {len(pathways_df)} pathways via GPT")

    # Add INTERNAL pathway IDs for GPT tracking (NOT the g:Profiler native IDs!)
    # Use a unique name to avoid collision with g:Profiler's 'native' column
    pathways_df = pathways_df.copy()
    pathways_df['gpt_internal_id'] = [f"PW_{i:04d}" for i in range(len(pathways_df))]
    if 'related_literature' not in pathways_df.columns:
        pathways_df['related_literature'] = [[] for _ in range(len(pathways_df))]
        print("     Initialized 'related_literature' column (will be populated from PubMed)")

    # Get PubMed-searchable disease name
    pubmed_disease = get_pubmed_disease_name(disease_name)

    # ================================================================
    # PER-CATEGORY RANKING
    # ================================================================
    if 'source' in pathways_df.columns:
        preferred_categories = ['GO:BP', 'GO:MF', 'GO:CC', 'KEGG', 'REAC']
        observed = list(pathways_df['source'].dropna().unique())
        categories = [cat for cat in preferred_categories if cat in observed]
        categories.extend([cat for cat in observed if cat not in categories])
    else:
        categories = ['Unknown']
    all_category_results = []

    # System prompt for GPT
    system_prompt = (
        f"You are an expert in {pubmed_disease} pathology and biological pathway analysis. "
        "Rank pathways by synthesizing five evidence sources: pathway description, "
        "disease pathology, statistical significance, PubMed literature, and module "
        "gene composition. Rank pathways only within their source/category. Return "
        "ONLY a JSON array of pathway IDs from most relevant to least relevant."
    )
    llm = None
    planning_agent = _get_planning_agent(framework)

    for category in categories:
        if 'source' in pathways_df.columns:
            cat_pathways = pathways_df[pathways_df['source'] == category].copy()
        else:
            cat_pathways = pathways_df.copy()

        if len(cat_pathways) == 0:
            continue

        print(f"\n  📋 Category: {category} ({len(cat_pathways)} pathways)")

        # NO SHUFFLE - Keep g:Profiler's default p-value ordering
        # g:Profiler returns results sorted by p-value (ascending)

        # Rank in batches within this category
        all_rankings = {}

        for batch_start in range(0, len(cat_pathways), batch_size):
            batch_df = cat_pathways.iloc[batch_start:batch_start + batch_size]
            batch_num = batch_start // batch_size + 1
            total_batches = (len(cat_pathways) + batch_size - 1) // batch_size

            print(f"     Batch {batch_num}/{total_batches}: "
                  f"{len(batch_df)} pathways")

            literature_by_id = {}
            for display_idx, (_, row) in enumerate(batch_df.iterrows(), 1):
                pathway_name = row.get('name', 'Unknown')
                print(f"       Searching PubMed for pathway {display_idx}/{len(batch_df)}...", end="\r")
                try:
                    papers = search_pubmed_for_pathway(
                        pathway_name=pathway_name,
                        disease_name=pubmed_disease,
                        query_agent=query_agent,
                        max_results=60,
                        pathway_description=row.get('description', ''),
                        disease_description=disease_description,
                    )
                except Exception as e:
                    print(f"      ⚠️ PubMed search error for '{str(pathway_name)[:40]}...': {e}")
                    papers = []

                literature_entries = _format_literature_entries(papers)
                literature_by_id[row['gpt_internal_id']] = _format_pubmed_results(papers)
                _assign_related_literature(cat_pathways, row['gpt_internal_id'], literature_entries)

                if literature_entries:
                    print(
                        f"      📝 Added {len(literature_entries)} papers to "
                        f"pathway '{str(pathway_name)[:30]}...'          "
                    )
                else:
                    print(f"      ⚠️ No PubMed results for pathway '{str(pathway_name)[:40]}...'          ")

            print(f"       PubMed searches complete for batch {batch_num}     ")

            # Build user prompt with all 5 information sources
            user_prompt = _build_ranking_prompt(
                batch_df=batch_df,
                disease_name=pubmed_disease,
                disease_description=disease_description,
                memory_context=memory_context,
                literature_by_id=literature_by_id,
            )

            # Call GPT
            try:
                if planning_agent is not None:
                    response_text = planning_agent.t2t_generate(user_prompt, system_prompt)
                else:
                    if llm is None:
                        llm = LLMClient(model="gpt-5.1")
                    response_text = llm.generate(
                        system_prompt=system_prompt,
                        user_prompt=user_prompt,
                        max_tokens=2000,
                        temperature=0.3,
                    )

                # Parse ranking from response
                try:
                    ranking = _parse_ranking_response(
                        response_text, batch_df['gpt_internal_id'].tolist()
                    )
                    for rank, pw_id in enumerate(ranking, start=1):
                        all_rankings[pw_id] = batch_start + rank
                except (json.JSONDecodeError, ValueError):
                    print(f"       ⚠️  Could not parse GPT response, using p-value order")
                    # Fallback: use original order
                    for rank, pw_id in enumerate(batch_df['gpt_internal_id'], start=1):
                        all_rankings[pw_id] = batch_start + rank

            except Exception as e:
                print(f"       ❌ GPT ranking failed: {e}, using p-value order")
                # Fallback: use original order
                for rank, pw_id in enumerate(batch_df['gpt_internal_id'], start=1):
                    all_rankings[pw_id] = batch_start + rank

        # Apply rankings to this category
        cat_pathways['gpt_rank'] = cat_pathways['gpt_internal_id'].map(all_rankings)
        cat_pathways['gpt_rank'].fillna(len(cat_pathways), inplace=True)

        # Sort by rank within category
        cat_pathways = cat_pathways.sort_values('gpt_rank').reset_index(drop=True)

        all_category_results.append(cat_pathways)

        print(f"     ✅ {category}: Ranked {len(cat_pathways)} pathways")

    # Merge all categories back
    if all_category_results:
        pathways_df = pd.concat(all_category_results, ignore_index=True)
    else:
        pathways_df = pathways_df.drop(columns=['gpt_internal_id'])
        return pathways_df

    # Drop internal gpt_internal_id column (keep g:Profiler's native column!)
    pathways_df = pathways_df.drop(columns=['gpt_internal_id'])

    print(f"\n  ✅ Per-Category GPT Ranking complete: {len(pathways_df)} pathways ranked")
    if 'source' in pathways_df.columns:
        cat_counts = pathways_df['source'].value_counts()
        shown = [f"{cat}={cat_counts.get(cat, 0)}" for cat in categories if cat_counts.get(cat, 0) > 0]
        print(f"  📊 Category distribution: {', '.join(shown)}")
    non_null = pathways_df['related_literature'].apply(
        lambda x: isinstance(x, list) and len(x) > 0
    ).sum()
    print(f"  📚 related_literature column: {non_null}/{len(pathways_df)} pathways have literature data")

    return pathways_df


def _build_ranking_prompt(
    batch_df: pd.DataFrame,
    disease_name: str,
    disease_description: str,
    memory_context: str = None,
    literature_by_id: Optional[Dict[str, str]] = None,
) -> str:
    """Build the user prompt for GPT ranking with all information sources."""

    parts = []

    # Disease context
    parts.append(f"DISEASE: {disease_name}")
    if disease_description:
        parts.append(f"DISEASE DESCRIPTION: {disease_description[:500]}")
    parts.append("")

    # Memory context (if available)
    if memory_context:
        parts.append(memory_context)
        parts.append("")

    # Pathway information
    parts.append("PATHWAYS TO RANK:")
    parts.append("=" * 60)

    for idx, (_, row) in enumerate(batch_df.iterrows(), 1):
        p_val = row.get('p_value', 1.0)
        try:
            p_value_text = f"{float(p_val):.2e}"
        except (TypeError, ValueError):
            p_value_text = str(p_val)

        if isinstance(p_val, (int, float)):
            if p_val < 1e-10:
                sig_level = "extremely significant"
            elif p_val < 1e-5:
                sig_level = "highly significant"
            elif p_val < 0.01:
                sig_level = "significant"
            else:
                sig_level = "marginally significant"
        else:
            sig_level = "unknown significance"

        intersections = _format_intersection_genes(row.get('intersections', ''))
        pubmed_text = ""
        if literature_by_id:
            pubmed_text = literature_by_id.get(row['gpt_internal_id'], "")
        if not pubmed_text:
            pubmed_text = "No PubMed results found."

        parts.append(f"""
PATHWAY {idx}: {row['gpt_internal_id']}
═══════════════════════
Name: {row.get('name', 'Unknown')}
Description: {str(row.get('description', 'N/A'))[:300]}
Source: {row.get('source', 'Unknown')}
P-value: {p_value_text} ({sig_level})
Intersection size: {row.get('intersection_size', 'N/A')}
Module genes in pathway: {intersections}
PubMed literature:
{pubmed_text}
""")

    parts.append("=" * 60)
    parts.append("")
    parts.append(
        "Rank these pathways from MOST to LEAST relevant to "
        f"{disease_name}. Return ONLY a JSON array of pathway IDs. "
        "Example: [\"PW_0003\", \"PW_0001\", \"PW_0002\"]"
    )

    return "\n".join(parts)


def _get_planning_agent(framework):
    """Return the clean-path planning agent when available."""
    try:
        return framework.analyzer.base_analyzer.planning_agent
    except Exception:
        return None


def _assign_related_literature(df: pd.DataFrame, internal_id: str, entries: list):
    """Assign list-valued literature entries to matching rows safely."""
    if 'related_literature' not in df.columns:
        df['related_literature'] = [[] for _ in range(len(df))]

    matches = df.index[df['gpt_internal_id'] == internal_id].tolist()
    for row_idx in matches:
        df.at[row_idx, 'related_literature'] = entries


def _format_literature_entries(papers: list, top_k: int = 5) -> list:
    """Convert PubMed paper dicts into the clean related_literature shape."""
    if not papers:
        return []

    sorted_papers = sorted(
        papers,
        key=lambda paper: paper.get('relevance_score', paper.get('relevance', 0)),
        reverse=True,
    )[:top_k]

    entries = []
    for paper in sorted_papers:
        entries.append({
            'pmid': paper.get('pmid', paper.get('PMID', 'N/A')),
            'title': paper.get('title', paper.get('TI', 'N/A')),
            'journal': paper.get('journal', paper.get('JT', paper.get('TA', 'N/A'))),
            'relevance': paper.get('relevance_score', paper.get('relevance', 0)),
        })
    return entries


def _format_pubmed_results(papers: list, max_papers: int = 20) -> str:
    """Format PubMed papers for the GPT ranking prompt."""
    if not papers:
        return "No PubMed results found."

    sorted_papers = sorted(
        papers,
        key=lambda paper: paper.get('relevance_score', paper.get('relevance', 0)),
        reverse=True,
    )[:max_papers]

    lines = []
    for idx, paper in enumerate(sorted_papers, 1):
        pmid = paper.get('pmid', paper.get('PMID', 'N/A'))
        title = paper.get('title', paper.get('TI', 'N/A'))
        relevance = paper.get('relevance_score', paper.get('relevance', 0))
        lines.append(f"{idx}. PMID {pmid}: {title} (relevance={relevance})")
    return "\n".join(lines)


def _format_intersection_genes(intersections_raw) -> str:
    """Format module genes overlapping a pathway for prompt context."""
    genes_list = []
    if isinstance(intersections_raw, str) and intersections_raw:
        genes_list = [g.strip() for g in intersections_raw.split(',') if g.strip()]
    elif isinstance(intersections_raw, list) and intersections_raw:
        genes_list = [str(g) for g in intersections_raw]

    if not genes_list:
        return "N/A"

    display_genes = genes_list[:10]
    genes_text = ', '.join(display_genes)
    if len(genes_list) > 10:
        genes_text += f" ... ({len(genes_list)} total)"
    return f"{genes_text} ({len(genes_list)} of module genes overlap)"


def _parse_ranking_response(
    response_text: str, valid_ids: list
) -> list:
    """
    Parse GPT ranking response into ordered pathway IDs.

    Parameters
    ----------
    response_text : str
        Raw response from GPT
    valid_ids : list
        Valid pathway IDs to expect

    Returns
    -------
    List of pathway IDs in ranked order
    """
    text = response_text.strip()

    # Handle markdown code blocks
    if text.startswith("```"):
        lines = text.split("\n")
        lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()

    try:
        ranking = json.loads(text)
    except json.JSONDecodeError:
        json_match = re.search(r'\[.*?\]', text, re.DOTALL)
        if not json_match:
            raise
        ranking = json.loads(json_match.group())

    if not isinstance(ranking, list):
        raise ValueError("Expected a JSON array")

    # Validate and fill missing IDs
    ranked_ids = [pid for pid in ranking if pid in valid_ids]
    missing = [pid for pid in valid_ids if pid not in ranked_ids]
    ranked_ids.extend(missing)

    return ranked_ids
