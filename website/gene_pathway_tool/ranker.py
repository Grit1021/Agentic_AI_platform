import json
import re
import math
import openai
import pandas as pd

from .config import OPENAI_API_KEY, GPT_MODEL, CATEGORY_CODES
from .pubmed import search_pubmed


def gpt_rank_pathways(enrichment_df: pd.DataFrame, disease_name: str,
                      disease_description: str, top_n: int = 30) -> pd.DataFrame:
    if enrichment_df.empty:
        return enrichment_df

    df = enrichment_df.sort_values('p_value').head(min(top_n * 2, len(enrichment_df))).copy()
    df['gpt_internal_id'] = [f"PW_{i:04d}" for i in range(len(df))]
    df['related_literature'] = [[] for _ in range(len(df))]
    df['gpt_rank'] = 999

    print(f"  GPT Per-Category Ranking: {len(df)} pathways...")

    print(f"  Searching PubMed for {len(df)} pathways...")
    for idx, (row_idx, row) in enumerate(df.iterrows()):
        pathway_name = row['name']
        _, pubmed_results = search_pubmed(pathway_name, disease_name, max_results=20)
        if pubmed_results:
            df.at[row_idx, 'related_literature'] = pubmed_results[:5]

    print(f"  PubMed search complete")

    for category in CATEGORY_CODES:
        cat_df = df[df['source'] == category].copy()
        if len(cat_df) == 0:
            continue

        print(f"  Ranking {category} ({len(cat_df)} pathways)")

        pathways_text = []
        for idx, (_, row) in enumerate(cat_df.iterrows(), 1):
            pw_desc = row.get('description', 'N/A')[:200]
            p_val = row.get('p_value', 1.0)
            if p_val < 1e-10:
                sig_level = "extremely significant"
            elif p_val < 1e-5:
                sig_level = "highly significant"
            elif p_val < 0.01:
                sig_level = "significant"
            else:
                sig_level = "marginally significant"

            lit = row.get('related_literature', [])
            lit_summary = f"{len(lit)} papers found. Top: {lit[0].get('title', 'N/A')[:50]}..." if lit else "No papers found"

            pathways_text.append(f"""
PATHWAY {row['gpt_internal_id']}:
- Name: {row['name']}
- Description: {pw_desc}
- P-value: {p_val:.2e} ({sig_level})
- PubMed Evidence: {lit_summary}
""")

        system_prompt = f"""You are an expert in {disease_name} pathology and biological pathway analysis.

Your task is to rank {category} pathways by synthesizing 4 information sources:
1. PATHWAY DESCRIPTION: Biological function and mechanisms
2. DISEASE PATHOLOGY: Known characteristics of {disease_name}
3. STATISTICAL SIGNIFICANCE: P-value from enrichment analysis
4. PUBMED LITERATURE: Scientific papers linking pathway to disease

IMPORTANT: You are ranking pathways ONLY WITHIN {category} category.
Rank 1 = BEST COMPREHENSIVE SCORE for {category}
"""

        user_prompt = f"""Rank these {len(cat_df)} {category} pathways by COMPREHENSIVE SCORE for {disease_name}.

Disease Context: {disease_description[:400] if disease_description else 'Not available'}

PATHWAYS in {category}:
{"".join(pathways_text)}

Return ONLY a JSON array of pathway IDs (best comprehensive score first within {category}):
["PW_0001", "PW_0002", ...]
"""

        try:
            client = openai.OpenAI(api_key=OPENAI_API_KEY)
            response = client.chat.completions.create(
                model=GPT_MODEL,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0,
                max_completion_tokens=1000
            )

            ranking_text = response.choices[0].message.content
            json_match = re.search(r'\[.*?\]', ranking_text, re.DOTALL)

            if json_match:
                ranked_ids = json.loads(json_match.group())
                rank_map = {pw_id: rank + 1 for rank, pw_id in enumerate(ranked_ids)}
                for pw_id, rank in rank_map.items():
                    mask = df['gpt_internal_id'] == pw_id
                    if mask.any():
                        df.loc[mask, 'gpt_rank'] = rank
            else:
                cat_indices = cat_df.index.tolist()
                for rank, idx in enumerate(cat_indices, 1):
                    df.loc[idx, 'gpt_rank'] = rank

        except Exception as e:
            print(f"  Ranking failed for {category}: {str(e)[:50]}")
            cat_indices = cat_df.index.tolist()
            for rank, idx in enumerate(cat_indices, 1):
                df.loc[idx, 'gpt_rank'] = rank

    df = df.sort_values(['source', 'gpt_rank'])
    df = df.drop(columns=['gpt_internal_id'])

    df['disease_connection'] = ''
    _generate_disease_connections(df, disease_name)

    print(f"  Per-Category GPT Ranking complete: {len(df)} pathways ranked")
    return df


def _generate_disease_connections(df: pd.DataFrame, disease_name: str):
    batch_size = 5
    sorted_df = df.sort_values('gpt_rank').head(20)

    for batch_start in range(0, len(sorted_df), batch_size):
        batch_end = min(batch_start + batch_size, len(sorted_df))
        batch_indices = sorted_df.index[batch_start:batch_end].tolist()

        batch_pathways = []
        for idx in batch_indices:
            row = df.loc[idx]
            pw_name = row.get('name', 'Unknown')
            pw_desc = row.get('description', 'N/A')[:150]
            p_val = row.get('p_value', 1.0)
            genes = row.get('intersections', [])[:5] if isinstance(row.get('intersections'), list) else []
            genes_str = ', '.join(genes) if genes else 'key genes'

            lit = row.get('related_literature', [])
            lit_refs = []
            for paper in lit[:3]:
                if isinstance(paper, dict):
                    pmid = paper.get('pmid', '')
                    if pmid:
                        lit_refs.append(f"[PMID:{pmid}]")

            batch_pathways.append({
                'idx': idx, 'name': pw_name, 'desc': pw_desc,
                'p_val': p_val, 'genes': genes_str, 'pmids': lit_refs
            })

        pathways_info = "\n".join([
            f"{i + 1}. {p['name']}: {p['desc']} (p={p['p_val']:.2e}, genes: {p['genes']})"
            for i, p in enumerate(batch_pathways)
        ])

        try:
            client = openai.OpenAI(api_key=OPENAI_API_KEY)
            batch_prompt = f"""For each pathway below, write a brief "{disease_name} Connection" explanation (2-3 sentences).

REQUIREMENTS:
1. Explain HOW this pathway mechanistically contributes to {disease_name}
2. Mention the key driver genes and their roles
3. Reference the p-value significance
4. Connect to hallmarks of the disease

PATHWAYS:
{pathways_info}

Return a JSON object with pathway names as keys and explanations as values:
{{
    "pathway_name_1": "Explanation 1...",
    "pathway_name_2": "Explanation 2...",
    ...
}}"""

            response = client.chat.completions.create(
                model=GPT_MODEL,
                messages=[
                    {"role": "system", "content": f"You are an expert in {disease_name} pathology. Provide mechanistic explanations linking pathways to disease."},
                    {"role": "user", "content": batch_prompt}
                ],
                temperature=0,
                max_completion_tokens=2000
            )

            response_text = response.choices[0].message.content
            if "```json" in response_text:
                json_start = response_text.find("```json") + 7
                json_end = response_text.find("```", json_start)
                response_text = response_text[json_start:json_end].strip()
            elif "```" in response_text:
                json_start = response_text.find("```") + 3
                json_end = response_text.find("```", json_start)
                response_text = response_text[json_start:json_end].strip()

            try:
                connections = json.loads(response_text)
                for pw in batch_pathways:
                    pw_name = pw['name']
                    explanation = connections.get(pw_name, '')
                    if not explanation:
                        for key, val in connections.items():
                            if key.lower() in pw_name.lower() or pw_name.lower() in key.lower():
                                explanation = val
                                break
                    if explanation:
                        pmid_refs = ' '.join(pw['pmids']) if pw['pmids'] else ''
                        if pmid_refs and pmid_refs not in explanation:
                            explanation = f"{explanation} {pmid_refs}"
                        df.at[pw['idx'], 'disease_connection'] = explanation
            except json.JSONDecodeError:
                pass

        except Exception:
            pass
