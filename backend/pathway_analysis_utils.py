from __future__ import annotations

import json
import requests
from typing import Dict, List, Optional, Tuple

import pandas as pd
import numpy as np
import torch
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from transformers import AutoTokenizer, AutoModel

# Global BioBERT model loading (cached)
_biobert_tokenizer = None
_biobert_model = None


def get_biobert_models():
    """Get or initialize BioBERT models (cached globally)."""
    global _biobert_tokenizer, _biobert_model
    if _biobert_tokenizer is None or _biobert_model is None:
        _biobert_tokenizer = AutoTokenizer.from_pretrained("dmis-lab/biobert-base-cased-v1.1")
        _biobert_model = AutoModel.from_pretrained("dmis-lab/biobert-base-cased-v1.1")
    return _biobert_tokenizer, _biobert_model


def sanitize_protein_list(protein_list: List[str]) -> List[str]:
    """Sanitize and normalize protein list input."""
    if isinstance(protein_list, list):
        return [str(p).strip() for p in protein_list if p]
    elif isinstance(protein_list, str):
        return [p.strip() for p in protein_list.split(",") if p.strip()]
    else:
        return []


def run_gprofiler_query(
    query: List[str],
    organism: str = "hsapiens",
    sources: List[str] = None,
    user_threshold: float = 0.05
) -> Tuple[Optional[Dict], Optional[pd.DataFrame]]:
    """
    Query g:Profiler for pathway enrichment analysis.
    
    Args:
        query: List of protein/gene identifiers
        organism: Target organism (default: hsapiens)
        sources: Pathway sources (default: GO:MF, GO:BP, REAC, KEGG, HP)
        user_threshold: P-value threshold for significance
        
    Returns:
        Tuple of (full_result_dict, significant_pathways_dataframe)
    """
    if sources is None:
        sources = ['GO:MF', 'GO:BP', 'REAC', 'KEGG', 'HP']
    
    url = "https://biit.cs.ut.ee/gprofiler/api/gost/profile/"
    payload = {
        "organism": organism,
        "query": query,
        "sources": sources,
        "user_threshold": user_threshold,
        "no_iea": True,
        "ordered": False,
        "significance_threshold_method": "fdr"
    }
    headers = {"Content-Type": "application/json"}
    
    try:
        response = requests.post(url, data=json.dumps(payload), headers=headers, timeout=30)
        response.raise_for_status()
        
        result = response.json()
        result_df = pd.DataFrame(result["result"])
        
        # Extract gene mappings
        genes_mapping = result["meta"]["genes_metadata"]["query"]["query_1"]["mapping"]
        genes_mapping = {v[0]: k for k, v in genes_mapping.items()}
        ordered_protein = result["meta"]["genes_metadata"]["query"]["query_1"]["ensgs"]
        ordered_protein = [genes_mapping.get(ensg, ensg) for ensg in ordered_protein]
        
        # Map intersections to protein names
        intersections = result_df["intersections"].values
        intersections_proteins = []
        for intersection in intersections:
            if intersection:
                temp = []
                for i, inter in enumerate(intersection):
                    if len(inter) > 0:
                        temp.append(ordered_protein[i])
                intersections_proteins.append(temp)
            else:
                intersections_proteins.append([])
        
        # Filter significant results
        significant_df = result_df[result_df['significant'] == True].copy()
        significant_df = significant_df.sort_values('p_value')
        significant_df = significant_df[["native", "name", "description", "p_value", "intersections", "intersection_size", "source"]].copy()
        significant_df["intersections"] = intersections_proteins
        
        return result, significant_df
        
    except Exception as e:
        print(f"Error querying g:Profiler: {e}")
        return None, None


def rank_pathways_tfidf(pathway_descriptions: List[str], enriched_disease_description: str) -> Dict[str, float]:
    """Rank pathways using TF-IDF similarity to enriched disease description."""
    if not pathway_descriptions or not enriched_disease_description:
        return {desc: 0.0 for desc in pathway_descriptions}
    
    corpus = [enriched_disease_description] + pathway_descriptions
    vectorizer = TfidfVectorizer(stop_words='english', max_features=5000)
    tfidf_matrix = vectorizer.fit_transform(corpus)
    
    query_vector = tfidf_matrix[0]
    pathway_vectors = tfidf_matrix[1:]
    similarities = cosine_similarity(query_vector, pathway_vectors)[0]
    
    return {desc: float(score) for desc, score in zip(pathway_descriptions, similarities)}


def get_biobert_embedding(text: str) -> np.ndarray:
    """Get BioBERT embedding for text."""
    tokenizer, model = get_biobert_models()
    
    inputs = tokenizer(text, return_tensors="pt", truncation=True, max_length=512, padding=True)
    with torch.no_grad():
        outputs = model(**inputs)
    
    # Use CLS token embedding
    cls_embedding = outputs.last_hidden_state[:, 0, :].numpy()
    return cls_embedding


def rank_pathways_biobert(pathway_descriptions: List[str], enriched_disease_description: str) -> Dict[str, float]:
    """Rank pathways using BioBERT embeddings and cosine similarity."""
    if not pathway_descriptions or not enriched_disease_description:
        return {desc: 0.0 for desc in pathway_descriptions}
    
    try:
        disease_embedding = get_biobert_embedding(enriched_disease_description)
        biobert_scores = {}
        
        for desc in pathway_descriptions:
            emb = get_biobert_embedding(desc)
            sim = cosine_similarity(disease_embedding, emb)[0][0]
            biobert_scores[desc] = float(sim)
        
        return biobert_scores
        
    except Exception as e:
        print(f"Error in BioBERT ranking: {e}")
        return {desc: 0.0 for desc in pathway_descriptions}


def get_pubmed_relevance(pub: Dict, disease_trait: str, pathway_name: str) -> float:
    """Calculate PubMed relevance score for a publication."""
    if not pub or "Title" not in pub or "Abstract" not in pub:
        return 0.0
    
    title = pub["Title"].split()
    abstract = pub["Abstract"].split()
    title_relevance = 0
    abstract_relevance = 0

    title = [word.lower() for word in title]
    abstract = [word.lower() for word in abstract]
    target = [term.lower() for term in disease_trait.split()]
    pathway_terms = [term.lower() for term in pathway_name.split()]

    # Title relevance scoring
    for term in target:
        if term in title:
            title_relevance += 2
        elif any(term in word for word in title):
            title_relevance += 1
            
    for term in pathway_terms:
        if term in title:
            title_relevance += 2
        elif any(term in word for word in title):
            title_relevance += 1

    # Abstract relevance scoring
    for term in target:
        if term in abstract:
            abstract_relevance += 1.5
        elif any(term in word for word in abstract):
            abstract_relevance += 0.75
            
    for term in pathway_terms:
        if term in abstract:
            abstract_relevance += 1.5
        elif any(term in word for word in abstract):
            abstract_relevance += 0.75

    total_relevance = (title_relevance * 2) + abstract_relevance
    max_possible_score = (len(target) + len(pathway_terms)) * 4 
    normalized_relevance = total_relevance / max_possible_score if max_possible_score > 0 else 0

    return float(normalized_relevance)


def rank_pathways_by_pubmed_relevance(
    ranked_significant_df: pd.DataFrame,
    disease_trait: str,
    query_agent,
    max_results: int = 80
) -> pd.DataFrame:
    """Rank pathways by PubMed relevance using query agent."""
    if ranked_significant_df is None or ranked_significant_df.empty:
        return ranked_significant_df
    
    pubmed_scores = []
    validated_publications = []
    number_of_publications = []
    
    for i in range(len(ranked_significant_df)):
        row = ranked_significant_df.iloc[i]
        name = row["name"]
        keywords = f"{name} {disease_trait}"
        
        try:
            publications = query_agent.act("PubMed", {"keywords": keywords, "max_results": max_results})
            if publications is None:
                publications = []
        except Exception as e:
            print(f"Warning: PubMed query failed for pathway '{name}': {e}")
            publications = []
        
        relevance_score = 0.0
        validated_pub = []
        
        for pub in publications:
            temp_relevance = get_pubmed_relevance(pub, disease_trait, name)
            relevance_score += temp_relevance
            if temp_relevance > 0.75:
                simplified_pub = {
                    "Title": pub.get("Title", ""),
                    "Abstract": pub.get("Abstract", ""),
                    "PMID": pub.get("PMID", "")
                }
                validated_pub.append(simplified_pub)
        
        validated_publications.append(validated_pub)
        number_of_publications.append(len(validated_pub))
        pubmed_scores.append(relevance_score)
    
    ranked_significant_df = ranked_significant_df.copy()
    ranked_significant_df["pubmed_relevance"] = pubmed_scores
    ranked_significant_df["validated_publications"] = validated_publications
    ranked_significant_df["num_publications"] = number_of_publications
    ranked_significant_df = ranked_significant_df.sort_values(by=["pubmed_relevance"], ascending=False)
    
    return ranked_significant_df


# Disease-specific keywords for common diseases
DISEASE_KEYWORD_MAP = {
    'alzheimer': ['alzheimer', 'amyloid', 'tau', 'neurofibrillary', 'apoe', 'beta-amyloid', 'app processing'],
    'ad': ['alzheimer', 'amyloid', 'tau', 'neurofibrillary', 'apoe', 'beta-amyloid', 'app processing'],
    'parkinson': ['parkinson', 'alpha-synuclein', 'synuclein', 'lewy body', 'dopamine', 'dopaminergic', 'substantia nigra'],
    'pd': ['parkinson', 'alpha-synuclein', 'synuclein', 'lewy body', 'dopamine', 'dopaminergic', 'substantia nigra'],
    'diabetes': ['diabetes', 'insulin', 'glucose', 'pancreatic', 'beta cell', 'glycemic'],
    'cancer': ['cancer', 'tumor', 'oncogene', 'metastasis', 'carcinoma', 'malignant'],
}

# Generic neurodegenerative keywords
COMMON_NEURO_KEYWORDS = [
    'neurodegeneration', 'neurodegenerative', 'dementia', 'cognitive', 'memory',
    'synaptic', 'neuronal', 'neuroinflammation', 'microglia', 'astrocyte',
    'blood-brain barrier', 'mitochondrial dysfunction', 'oxidative stress',
    'protein aggregation', 'autophagy', 'lysosomal', 'ubiquitin'
]

# General housekeeping keywords
GENERAL_KEYWORDS = [
    'metabolism', 'metabolic', 'biosynthesis', 'biosynthetic',
    'transcription', 'translation', 'ribosome', 'protein synthesis',
    'cell cycle', 'mitosis', 'dna replication',
    'housekeeping', 'maintenance', 'homeostasis'
]


def extract_disease_keywords(disease_name: str) -> List[str]:
    """
    Extract disease-specific keywords from disease name.
    
    Args:
        disease_name: Disease or trait name
        
    Returns:
        List of disease-specific keywords
    """
    disease_lower = disease_name.lower()
    
    # Check for known disease patterns
    for key, keywords in DISEASE_KEYWORD_MAP.items():
        if key in disease_lower:
            return keywords
    
    # For disease pairs (e.g., "AD_vs_PD" or "AD Module_5")
    # Extract keywords from both diseases
    combined_keywords = []
    for key, keywords in DISEASE_KEYWORD_MAP.items():
        if key in disease_lower:
            combined_keywords.extend(keywords)
    
    if combined_keywords:
        return combined_keywords
    
    # Default: use disease name words as keywords
    return [word.lower() for word in disease_name.split() if len(word) > 3]


def calculate_disease_specificity_score(
    pathway_name: str,
    pathway_description: str,
    disease_keywords: List[str],
    is_disease_pair: bool = False
) -> float:
    """
    Calculate disease specificity score for a single pathway.
    
    Args:
        pathway_name: Pathway name
        pathway_description: Pathway description
        disease_keywords: Disease-specific keywords
        is_disease_pair: Whether analyzing disease pair
        
    Returns:
        Disease specificity score (0-1, higher = more specific)
    """
    text = (pathway_name + " " + pathway_description).lower()
    
    # Count matches for different keyword categories
    disease_matches = sum(1 for keyword in disease_keywords if keyword in text)
    neuro_matches = sum(1 for keyword in COMMON_NEURO_KEYWORDS if keyword in text)
    general_matches = sum(1 for keyword in GENERAL_KEYWORDS if keyword in text)
    
    # Scoring logic
    if disease_matches > 0:
        # Disease-specific pathway: highest weight
        score = disease_matches * 0.5 + neuro_matches * 0.2 - general_matches * 0.1
    elif neuro_matches > 0:
        # Generic neurodegenerative: medium weight
        score = neuro_matches * 0.3 - general_matches * 0.1
    else:
        # General biological pathway: lowest weight
        score = -general_matches * 0.3
    
    # Normalize to 0-1
    score = max(0, min(1, (score + 0.5) / 2.0))
    
    return float(score)


def rank_pathways_by_disease_specificity(
    pathway_descriptions: List[str],
    disease_name: str,
    significant_df: pd.DataFrame,
    disease_keywords: List[str] = None
) -> Dict[str, float]:
    """
    Rank pathways by disease specificity.
    
    This is similar to TF-IDF and BioBERT ranking, but focuses on
    disease-specific vs generic biological processes.
    
    Args:
        pathway_descriptions: List of pathway description strings
        disease_name: Disease or trait name
        significant_df: DataFrame with pathway information
        disease_keywords: Optional disease-specific keywords
        
    Returns:
        Dictionary mapping pathway description to specificity score
    """
    if not pathway_descriptions:
        return {}
    
    # Extract keywords if not provided
    if disease_keywords is None:
        disease_keywords = extract_disease_keywords(disease_name)
    
    # Detect if disease pair
    is_disease_pair = '_vs_' in disease_name or 'JACCARD' in disease_name
    
    # Calculate specificity for each pathway
    specificity_scores = {}
    for desc in pathway_descriptions:
        # Find corresponding pathway in dataframe
        # Try multiple matching strategies to find the pathway name
        pathway_name = ""

        # Skip if desc is None or empty
        if not desc or (isinstance(desc, str) and not desc.strip()):
            specificity_scores[desc] = 0.0
            continue

        # Strategy 1: Exact match by description column
        if 'description' in significant_df.columns:
            matching_rows = significant_df[significant_df['description'] == desc]
            if not matching_rows.empty:
                pathway_name = matching_rows.iloc[0]['name']

        # Strategy 2: Case-insensitive match by description column
        if not pathway_name and 'description' in significant_df.columns:
            desc_lower = str(desc).lower().strip()
            matching_rows = significant_df[
                significant_df['description'].astype(str).str.lower().str.strip() == desc_lower
            ]
            if not matching_rows.empty:
                pathway_name = matching_rows.iloc[0]['name']

        # Strategy 3: Exact match by name column (in case desc is actually the name)
        if not pathway_name and 'name' in significant_df.columns:
            matching_rows = significant_df[significant_df['name'] == desc]
            if not matching_rows.empty:
                pathway_name = matching_rows.iloc[0]['name']

        # Strategy 4: Case-insensitive match by name column
        if not pathway_name and 'name' in significant_df.columns:
            desc_lower = str(desc).lower().strip()
            matching_rows = significant_df[
                significant_df['name'].astype(str).str.lower().str.strip() == desc_lower
            ]
            if not matching_rows.empty:
                pathway_name = matching_rows.iloc[0]['name']

        # Strategy 5: Partial match - check if desc is contained in description or name
        if not pathway_name:
            desc_lower = str(desc).lower().strip()
            # Try description column
            if 'description' in significant_df.columns:
                matching_rows = significant_df[
                    significant_df['description'].astype(str).str.lower().str.contains(desc_lower, na=False, regex=False)
                ]
                if not matching_rows.empty:
                    pathway_name = matching_rows.iloc[0]['name']

            # Try name column if still no match
            if not pathway_name and 'name' in significant_df.columns:
                matching_rows = significant_df[
                    significant_df['name'].astype(str).str.lower().str.contains(desc_lower, na=False, regex=False)
                ]
                if not matching_rows.empty:
                    pathway_name = matching_rows.iloc[0]['name']

        # Strategy 6: Use the description itself as the pathway name (fallback)
        # This ensures we still calculate a meaningful score even if all matching fails
        if not pathway_name:
            pathway_name = desc

        score = calculate_disease_specificity_score(
            pathway_name,
            desc,
            disease_keywords,
            is_disease_pair
        )
        specificity_scores[desc] = score

    return specificity_scores


def get_mesh_description(disease_name: str, mesh_id: str = None) -> str:
    """
    Get official MeSH description for a disease from NCBI E-utilities API.
    
    This provides consistent, reproducible disease descriptions instead of
    LLM-generated ones which may vary across runs.
    
    Args:
        disease_name: Disease name (used as fallback if MeSH ID fails)
        mesh_id: MeSH ID (e.g., "D000544" for Alzheimer's Disease)
        
    Returns:
        Official MeSH description if found, disease_name otherwise
    """
    import requests
    import xml.etree.ElementTree as ET
    import time
    
    # If no MeSH ID provided, try to search by disease name
    if not mesh_id:
        try:
            # Search for MeSH ID by disease name
            search_url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
            search_params = {
                "db": "mesh",
                "term": disease_name,
                "retmax": 1,
                "retmode": "json"
            }
            search_response = requests.get(search_url, params=search_params, timeout=10)
            search_data = search_response.json()
            
            if "esearchresult" in search_data and "idlist" in search_data["esearchresult"]:
                id_list = search_data["esearchresult"]["idlist"]
                if id_list:
                    mesh_id = id_list[0]
                    print(f"  Found MeSH ID: {mesh_id} for '{disease_name}'")
                else:
                    print(f"  No MeSH ID found for '{disease_name}', using disease name as description")
                    return disease_name
        except Exception as e:
            print(f"  Warning: MeSH search failed: {e}")
            return disease_name
    
    # Fetch MeSH description using E-utilities
    try:
        # Rate limiting: NCBI requests max 3 requests/second
        time.sleep(0.4)
        
        fetch_url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
        fetch_params = {
            "db": "mesh",
            "id": mesh_id,
            "retmode": "xml"
        }
        
        response = requests.get(fetch_url, params=fetch_params, timeout=10)
        response.raise_for_status()
        
        # Parse XML response
        root = ET.fromstring(response.content)
        
        # Extract MeSH term name
        descriptor_name = root.find(".//DescriptorName/String")
        term_name = descriptor_name.text if descriptor_name is not None else disease_name
        
        # Extract Scope Note (comprehensive description)
        scope_note = root.find(".//ScopeNote")
        description_parts = [f"{term_name}."]
        
        if scope_note is not None:
            description_parts.append(scope_note.text.strip())
        
        # Extract additional annotations
        annotations = root.findall(".//Annotation")
        for annotation in annotations[:2]:  # Limit to first 2 annotations
            if annotation.text:
                description_parts.append(annotation.text.strip())
        
        # Combine all parts
        full_description = " ".join(description_parts)
        
        print(f"  ✅ Retrieved MeSH description ({len(full_description)} chars)")
        return full_description
        
    except Exception as e:
        print(f"  ⚠️  Failed to fetch MeSH description: {e}")
        print(f"  Falling back to disease name: {disease_name}")
        return disease_name


def enrich_disease_description(disease_trait: str, llm_generate_func=None, 
                               mesh_id: str = None, use_mesh: bool = True) -> str:
    """
    Get disease description - preferably from MeSH official database.
    
    Args:
        disease_trait: Disease name
        llm_generate_func: LLM function (legacy, optional)
        mesh_id: MeSH ID if known (e.g., "D000544" for Alzheimer's Disease)
        use_mesh: If True, use MeSH API; if False, use LLM (default: True)
        
    Returns:
        Disease description string
        
    Recommended:
        Use MeSH (use_mesh=True) for reproducible, consistent descriptions
    """
    # Prefer MeSH official description for reproducibility
    if use_mesh:
        return get_mesh_description(disease_trait, mesh_id)
    
    # Fallback to LLM (legacy behavior, may vary across runs)
    if llm_generate_func is None:
        print("  Warning: No LLM function provided and use_mesh=False, using disease name")
        return disease_trait
    
    prompt = f"""
    Please provide a comprehensive description of the disease or trait: {disease_trait}
    
    Include:
    - Clinical manifestations
    - Pathophysiology
    - Risk factors
    - Treatment approaches
    - Associated molecular pathways
    
    Provide a detailed biomedical description suitable for pathway analysis.
    """
    
    try:
        return llm_generate_func(prompt, "You are a biomedical expert assistant.")
    except Exception as e:
        print(f"Error enriching disease description: {e}")
        return disease_trait



def combine_pathway_rankings(
    pathway_descriptions: List[str],
    enriched_description: str,
    significant_df: pd.DataFrame,
    llm_generate_func=None,
    disease_name: str = None,
    mesh_id: str = None  # NEW: MeSH ID for disease
) -> Tuple[str, pd.DataFrame]:
    """
    Combine TF-IDF, BioBERT, and Disease-Specificity rankings for pathway analysis.
    
    Args:
        pathway_descriptions: List of pathway descriptions
        enriched_description: Disease description (to be enriched)
        significant_df: DataFrame with pathway information
        llm_generate_func: LLM function for description enrichment (DEPRECATED, use MeSH instead)
        disease_name: Disease name for specificity calculation (optional)
        mesh_id: MeSH ID for disease (e.g., "D000544" for Alzheimer's Disease)
    
    Returns:
        Tuple of (enriched_description, ranked_dataframe_with_scores)
    """
    # Enrich disease description using MeSH (reproducible)
    # For Alzheimer's Disease: mesh_id="D000544"
    print(f"\n   🔍 combine_pathway_rankings CALLED: disease='{enriched_description}', mesh_id={mesh_id}")
    enriched_desc = enrich_disease_description(
        disease_trait=enriched_description,
        mesh_id=mesh_id,  # Pass MeSH ID if provided
        use_mesh=True  # Use MeSH official description (recommended)
    )
    print(f"   📝 Disease description: {enriched_desc[:150]}...")
    if "degenerative" in enriched_desc.lower():
        print(f"   ✅ MeSH official description detected!\n")
    else:
        print(f"   ⚠️  Simple disease name (MeSH may have failed)\n")
    
    # Get TF-IDF scores
    tfidf_scores = rank_pathways_tfidf(pathway_descriptions, enriched_desc)
    
    # Get BioBERT scores
    biobert_scores = rank_pathways_biobert(pathway_descriptions, enriched_desc)
    
    # Get Disease Specificity scores (if disease_name provided)
    if disease_name:
        disease_spec_scores = rank_pathways_by_disease_specificity(
            pathway_descriptions,
            disease_name,
            significant_df
        )
    else:
        disease_spec_scores = {desc: 0.0 for desc in pathway_descriptions}
    
    # Combine scores
    combined_scores = {}
    for desc in pathway_descriptions:
        tfidf_score = tfidf_scores.get(desc, 0.0)
        biobert_score = biobert_scores.get(desc, 0.0)
        disease_spec = disease_spec_scores.get(desc, 0.0)
        
        # New formula: (tfidf + biobert + disease_spec) / 3
        combined = (tfidf_score + biobert_score + disease_spec) / 3.0
        combined_scores[desc] = combined
    
    # Add scores to dataframe
    # Note: We only keep combined_score and disease_specificity in the final output
    # tfidf_score and biobert_score are intermediate values used to calculate combined_score
    significant_df = significant_df.copy()
    significant_df["disease_specificity"] = [disease_spec_scores.get(desc, 0.0) for desc in pathway_descriptions]
    significant_df["combined_score"] = [combined_scores.get(desc, 0.0) for desc in pathway_descriptions]
    significant_df["weighted_score"] = significant_df["combined_score"] * (1 - significant_df["p_value"])

    # Sort by weighted score
    ranked_df = significant_df.sort_values("weighted_score", ascending=False)

    return enriched_desc, ranked_df




