import os
import sys
import pandas as pd
import numpy as np
from typing import Dict, Any, List
from collections import Counter

# Add parent directory to path for importing pathway_analysis_utils
current_dir = os.path.dirname(os.path.abspath(__file__))
utils_dir = os.path.dirname(os.path.dirname(current_dir))  # Go up to /utils
if utils_dir not in sys.path:
    sys.path.insert(0, utils_dir)


def infer_biological_theme(pathways_df: pd.DataFrame, top_n: int = 10) -> str:
    """
    Infer biological theme from a module's top pathways.
    
    Parameters:
    -----------
    pathways_df : DataFrame
        DataFrame with pathway names
    top_n : int
        Number of top pathways to analyze
        
    Returns:
    --------
    str : Inferred theme (e.g., "Synaptic function", "Mitochondrial dynamics")
    """
    if pathways_df.empty:
        return "Unknown"
    
    # Get top pathways
    top_pathways = pathways_df.head(top_n)['name'].tolist() if 'name' in pathways_df.columns else []
    
    # Define theme keywords
    theme_keywords = {
        'Synaptic function': ['synapse', 'synaptic', 'neurotransmitter', 'vesicle'],
        'Mitochondrial dynamics': ['mitochondri', 'oxidative phosphorylation', 'electron transport', 'ATP'],
        'Immune response': ['immune', 'inflammation', 'cytokine', 'interferon'],
        'Cell cycle regulation': ['cell cycle', 'mitosis', 'G1/S', 'G2/M', 'checkpoint'],
        'Protein degradation': ['proteasome', 'ubiquitin', 'autophagy', 'lysosome'],
        'RNA processing': ['RNA', 'ribosome', 'splicing', 'transcription', 'translation'],
        'Lipid metabolism': ['lipid', 'fatty acid', 'cholesterol', 'glycolipid'],
        'Signal transduction': ['signaling', 'kinase', 'phosphorylation', 'MAPK', 'receptor'],
        'DNA repair': ['DNA repair', 'damage', 'replication', 'recombination'],
        'Membrane trafficking': ['transport', 'trafficking', 'endocytosis', 'exocytosis', 'Golgi']
    }
    
    # Count theme matches
    theme_scores = {}
    pathway_text = ' '.join([p.lower() for p in top_pathways])
    
    for theme, keywords in theme_keywords.items():
        score = sum(1 for kw in keywords if kw in pathway_text)
        if score > 0:
            theme_scores[theme] = score
    
    # Return top theme
    if theme_scores:
        return max(theme_scores, key=theme_scores.get)
    else:
        return "Mixed biological processes"


def run_module_pathway_collection(
    genes: List[str],
    module_id: int,
    framework,
    disease_name: str = "AD",
    gprofiler_cache: Dict[str, Any] = None,
    use_gpt_autorank: bool = False,  # NEW: Use GPT auto-ranking instead of Planning Agent
    gpt_rank_function = None,  # NEW: Function for GPT ranking if use_gpt_autorank=True
    disease_description: str = "",  # NEW: For GPT autorank (from MeSH/NCBI)
    disease_code: str = None,  # NEW: Short code for filenames (e.g. "AD", "IBD")
    benchmark_config: dict = None,  # NEW: LLM benchmark config for deterministic outputs
    module_phase2_dir: str = None,  # NEW: Phase2 module directory for reasoning files (e.g., "phase2_module_iteration/Module_X")
    memory_context: str = None  # NEW: Memory bank context for GPT ranking
) -> Dict[str, Any]:
    """
    Run Steps 1-4 for a single module to collect filtered pathways.
    
    This function executes:
    - Step 1: GPT prediction
    - Step 2: g:Profiler enrichment (using cached results if provided)
    - Step 3: GPT matching
    - Step 4: Dual FDR filtering + ranking (Planning Agent OR GPT autorank)
    
    CRITICAL: Preserves ranking scores and both p-value types!
    
    Parameters:
    -----------
    genes : List[str]
        Gene list for this module
    module_id : int
        Module identifier
    framework : IterativeGPTAgentFramework
        Framework instance with cached rankings
    disease_name : str
        Disease name (default "AD")
    gprofiler_cache : dict, optional
        Pre-computed g:Profiler cache with planning agent rankings
        If None, will call g:Profiler for this module
    use_gpt_autorank : bool
        If True, use GPT auto-ranking instead of Planning Agent (default: False)
    gpt_rank_function : callable, optional
        Function for GPT ranking if use_gpt_autorank=True
        Signature: gpt_rank_function(pathways_df, disease_name, ...) -> ranked_df
    disease_description : str
        Disease description for GPT autorank (extracted from MeSH/NCBI)
    disease_code : str, optional
        Short disease code for filenames (e.g. "AD", "IBD"). 
        If None, derived from disease_name or defaults to "AD".
        
    Returns:
    --------
    dict with keys:
        - module_id: int
        - module_size: int  
        - filtered_pathways: DataFrame (with both p-values + ranking scores)
        - biological_theme: str
        - gpt_prediction: dict
        - validation_rate: float
    """
    # Determine prefix for filenames
    if disease_code:
        prefix = disease_code
    else:
        # Try to extract from disease_name if it looks like "AD_Module..."
        if "_Module_" in disease_name:
            prefix = disease_name.split("_Module_")[0]
        else:
            # Use first word or default
            prefix = disease_name.split(" ")[0] if " " in disease_name else disease_name
            
    module_name = f"{prefix}_Module_{module_id}"
    
    print(f"{'='*80}")
    print(f"COLLECTING PATHWAYS FOR MODULE {module_id}")
    print(f"{'='*80}")
    print(f"Module size: {len(genes)} genes")
    
    # Execute Steps 1-4 using the analyzer
    # If no cache provided, create one with planning agent ranking
    if gprofiler_cache is None:
        print(f"\n🔬 Creating g:Profiler cache with Planning Agent ranking...")
        print(f"   This will execute the full 6-stage workflow for {len(genes)} genes")
        
        try:
            # Import required modules
            from src.pathway_enrichment_analysis import PathwayEnrichmentAnalyzer
            
            # Create enrichment analyzer
            enrichment_analyzer = PathwayEnrichmentAnalyzer(framework.analyzer.output_dir)
            
            # Get FULL g:Profiler results (no filtering)
            cached_all_pathways = enrichment_analyzer.enrich_geneset_full(
                genes=genes,
                name=module_name,
                sources=['GO:BP', 'GO:MF', 'GO:CC', 'KEGG', 'REAC']
            )
            
            if not cached_all_pathways.empty:
                print(f"   ✅ g:Profiler: {len(cached_all_pathways)} pathways")
                
                # ================================================================
                # STEP 4: RANKING (Planning Agent OR GPT Autorank)
                # ================================================================
                
                if use_gpt_autorank and gpt_rank_function is not None:
                    # ============================================================
                    # OPTION A: GPT AUTO-RANKING (DEFERRED)
                    # ============================================================
                    # For GPT Autorank: DON'T rank here!
                    # Ranking happens AFTER GPT prediction + matching
                    # This ensures we only rank GPT-predicted pathways, not all g:Profiler results
                    
                    print(f"   📦 Creating g:Profiler cache (GPT Autorank mode)")
                    print(f"      - Cached {len(cached_all_pathways)} pathways for matching")
                    print(f"      - GPT autorank will run AFTER GPT prediction + matching")
                    
                    # Store raw g:Profiler results without ranking
                    ranked_pathways_df = None  # Will be set after GPT autorank on matched pathways
                    wellknown_pathways = []
                    novel_pathways = []
                else:
                    # ============================================================
                    # OPTION B: PLANNING AGENT 6-STAGE RANKING (Original)
                    # ============================================================
                    print(f"   🎯 Running Planning Agent 6-stage ranking...")
                    # act() returns 3 values: (ranked_pubmed_df, wellknown_pathways, novel_pathways)
                    (ranked_pubmed_df, wellknown_pathways, novel_pathways) = framework.analyzer.base_analyzer.planning_agent.act(
                        protein_list=genes,
                        disease_trait=disease_name,
                        top=1000,  # Get all significant pathways
                        query_agent=framework.analyzer.base_analyzer.query_agent
                    )

                    # Add disease_specificity scoring OUTSIDE of Planning Agent
                    print(f"   📊 Adding disease-specificity scoring (external to Planning Agent)...")
                    if ranked_pubmed_df is not None and not ranked_pubmed_df.empty:
                        try:
                            # Import from pathway_analysis_utils (path already configured at module level)
                            from pathway_analysis_utils import rank_pathways_by_disease_specificity
                            
                            # Extract base disease name (e.g., "AD" from "AD_Module_6")
                            base_disease_name = disease_name.split('_')[0] if '_Module_' in disease_name else disease_name
                            
                            # Get pathway descriptions for disease specificity scoring
                            pathway_descriptions = ranked_pubmed_df["description"].tolist()
                            
                            # Calculate disease specificity scores
                            disease_spec_scores = rank_pathways_by_disease_specificity(
                                pathway_descriptions=pathway_descriptions,
                                disease_name=base_disease_name,
                                significant_df=ranked_pubmed_df
                            )
                            
                            # Add disease_specificity column to DataFrame
                            ranked_pubmed_df = ranked_pubmed_df.copy()
                            ranked_pubmed_df["disease_specificity"] = [
                                disease_spec_scores.get(desc, 0.0) for desc in pathway_descriptions
                            ]
                            
                            # Recalculate combined_score with disease_specificity
                            # combined_score = (TF-IDF + BioBERT + disease_specificity) / 3
                            # But Planning Agent already has score = (TF-IDF + BioBERT) / 2
                            # So we need to add disease_specificity and recompute
                            if 'score' in ranked_pubmed_df.columns:
                                # Expand the combined score to include disease_specificity
                                # Original: score = (tfidf + biobert) / 2
                                # New: combined_score = (tfidf + biobert + disease_spec) / 3
                                # But we don't have tfidf and biobert separately, so approximate:
                                # combined_score ≈ (score * 2 + disease_spec) / 3
                                ranked_pubmed_df["combined_score"] = (
                                    ranked_pubmed_df["score"] * 2 + ranked_pubmed_df["disease_specificity"]
                                ) / 3.0
                            else:
                                ranked_pubmed_df["combined_score"] = ranked_pubmed_df["disease_specificity"]
                            
                            # Recalculate weighted_score
                            ranked_pubmed_df["weighted_score"] = (
                                ranked_pubmed_df["combined_score"] * (1 - ranked_pubmed_df["p_value"])
                            )
                            
                            print(f"   ✅ Disease-specificity added (avg: {ranked_pubmed_df['disease_specificity'].mean():.3f})")
                            
                        except ImportError as e:
                            print(f"   ⚠️  Import error for pathway_analysis_utils: {e}")
                            print(f"   sys.path: {sys.path[:3]}...")  # Show first 3 paths
                            # Fallback: rename score to combined_score
                            if 'score' in ranked_pubmed_df.columns:
                                ranked_pubmed_df["combined_score"] = ranked_pubmed_df["score"]
                        except Exception as e:
                            print(f"   ⚠️  Could not add disease_specificity: {e}")
                            import traceback
                            traceback.print_exc()
                            # Fallback: rename score to combined_score
                            if 'score' in ranked_pubmed_df.columns:
                                ranked_pubmed_df["combined_score"] = ranked_pubmed_df["score"]

                    ranked_pathways_df = ranked_pubmed_df

                if ranked_pathways_df is not None and not ranked_pathways_df.empty:
                    print(f"   ✅ Planning Agent ranked {len(ranked_pathways_df)} FDR-significant pathways")
                    print(f"   📋 Planning Agent columns: {list(ranked_pathways_df.columns)}")
                    
                    # CRITICAL FIX: Identify ONLY numeric score columns
                    # Exclude metadata columns (IDs, descriptions, gene lists, etc.)
                    metadata_cols = {
                        'name', 'native', 'description', 'p_value', 'source', 
                        'term_size', 'query_size', 'intersection_size', 'effective_domain_size',
                        'precision', 'recall', 'query', 'parents', 'intersections', 'evidences',
                        'geneset', 'geneset_size', 'significant', 'gpt_predicted',
                        'fdr_corrected_p', 'validated_publications'  # These are lists/bools, not scores
                    }
                    
                    # Score columns are numeric columns not in metadata
                    score_cols_to_merge = []
                    for col in ranked_pathways_df.columns:
                        if col not in metadata_cols:
                            # Check if it's numeric
                            if pd.api.types.is_numeric_dtype(ranked_pathways_df[col]):
                                score_cols_to_merge.append(col)
                    
                    print(f"   📊 Numeric score columns to merge: {score_cols_to_merge}")
                    
                    # Merge scores using pandas merge (much more efficient)
                    # Keep ALL rows from cached_all_pathways (left join)
                    merge_df = ranked_pathways_df[['name'] + score_cols_to_merge].copy()
                    
                    # Merge with left join - keeps all cached_all_pathways rows
                    cached_all_pathways = cached_all_pathways.merge(
                        merge_df,
                        on='name',
                        how='left',
                        suffixes=('', '_ranked')
                    )
                    
                    # Fill NaN values (pathways not ranked by planning agent) with 0.0
                    for col in score_cols_to_merge:
                        if col in cached_all_pathways.columns:
                            cached_all_pathways[col] = cached_all_pathways[col].fillna(0.0)
                    
                    ranked_count = cached_all_pathways[score_cols_to_merge[0]].gt(0).sum() if score_cols_to_merge else 0
                    print(f"   ✅ Scores assigned to {ranked_count}/{len(cached_all_pathways)} pathways")
                    print(f"   ✅ All pathways now have score columns (unranked set to 0.0)")
                else:
                    print(f"   ⚠️  No FDR-significant pathways from Planning Agent")
                    # Set default scores
                    for col in ['combined_score', 'disease_specificity', 'weighted_score', 'pubmed_relevance', 'num_publications']:
                        cached_all_pathways[col] = 0.0
                    cached_all_pathways['validated_publications'] = [[] for _ in range(len(cached_all_pathways))]
                
                # Create cache dictionary with BOTH all pathways and ranked pathways
                gprofiler_cache = {
                    'all_pathways': cached_all_pathways,  # ALL pathways (no filtering)
                    'ranked_pathways': ranked_pathways_df if ranked_pathways_df is not None else cached_all_pathways,  # FDR-significant + ranked
                    'wellknown': wellknown_pathways if ranked_pathways_df is not None else [],
                    'novel': novel_pathways if ranked_pathways_df is not None else []
                }
                
                print(f"   ✅ Cache created with planning agent rankings")
                print(f"      - all_pathways: {len(cached_all_pathways)} total pathways")
                print(f"      - ranked_pathways: {len(gprofiler_cache['ranked_pathways'])} Planning Agent ranked pathways")
            else:
                print(f"   ⚠️  No g:Profiler results")
                gprofiler_cache = None
                
        except Exception as e:
            print(f"   ⚠️  Cache creation failed: {e}")
            import traceback
            traceback.print_exc()
            gprofiler_cache = None
    
    # Run pathway analysis for this module
    # Naming: {prefix}_Module_{id}_iter{N} - includes disease, module, and iteration
    # Use prefix (e.g. "AD" or "IBD") for filenames
    module_name_iter1 = f"{prefix}_Module_{module_id}_iter1"  # Phase 1 = Iteration 1

    # Determine reasoning file save directory
    # If module_phase2_dir is provided, save to phase2_module_iteration/Module_X/
    # Otherwise, fallback to gpt_led_analysis_ag2_hitl/
    if module_phase2_dir:
        reasoning_save_dir = module_phase2_dir
        print(f"   💾 Reasoning files will be saved to: {reasoning_save_dir}")
    else:
        reasoning_save_dir = framework.analyzer.results_dir
        print(f"   💾 Reasoning files will be saved to (fallback): {reasoning_save_dir}")

    results = framework.analyzer.analyze_gpt_led_pathways(
        genes=genes,
        disease_name=module_name_iter1,
        top_k_predict=50,  # GPT predicts 50 pathways (10 per category)
        top_k_analyze=6,   # Analyze top 6 (not used if skip_ppi_analysis=True)
        gprofiler_cache=gprofiler_cache,  # Pass cache with planning agent rankings
        skip_ppi_analysis=True,  # Skip PPI for Phase 1
        gpt_rank_function=gpt_rank_function if use_gpt_autorank else None,  # Pass GPT autorank function
        disease_description=disease_description if use_gpt_autorank else None,  # Pass disease description
        query_agent=framework.query_agent if use_gpt_autorank else None,  # Pass query agent from framework
        benchmark_config=benchmark_config,  # Pass benchmark config for deterministic evaluation
        file_identifier=os.path.join(reasoning_save_dir, module_name_iter1),  # Save reasoning to phase2 module dir
        iteration=1,  # Explicitly set iteration 1 for Phase 1
        memory_context=memory_context  # Pass memory context
    )
    
    # Extract filtered pathways
    filtered_pathways = results.get('gpt_filtered_pathways', pd.DataFrame())
    
    # Extract key_genes from GPT prediction if available
    gpt_prediction = results.get('gpt_predicted', {})
    pathway_details = gpt_prediction.get('pathway_details', {})
    
    if not filtered_pathways.empty and pathway_details:
        # Create a mapping of pathway name to key_genes
        key_genes_map = {}
        for pw_name, details in pathway_details.items():
            if 'key_genes' in details:
                key_genes_map[pw_name] = details['key_genes']
        
        # Add key_genes column if mapping exists
        if key_genes_map:
            filtered_pathways['key_genes'] = filtered_pathways['name'].map(key_genes_map)
            # Fill NaNs with empty lists
            filtered_pathways['key_genes'] = filtered_pathways['key_genes'].apply(lambda x: x if isinstance(x, list) else [])
            print(f"   ✅ Added key_genes to {len(filtered_pathways)} pathways")
    
    # Extract related_literature from validated_publications if available
    if not filtered_pathways.empty and 'validated_publications' in filtered_pathways.columns:
        def extract_top_5_literature(validated_pubs):
            """Extract top 5 papers from validated_publications."""
            if not isinstance(validated_pubs, list) or len(validated_pubs) == 0:
                return []
            
            # Take top 5 from the list (already sorted by relevance during PubMed ranking)
            top_5 = validated_pubs[:5]
            
            # Format as structured data
            literature_list = []
            for pub in top_5:
                if isinstance(pub, dict):
                    literature_list.append({
                        'pmid': pub.get('pmid', 'N/A'),
                        'title': pub.get('title', 'N/A'),
                        'journal': pub.get('journal', ''),
                        'relevance': pub.get('relevance_score', 0)
                    })
            
            return literature_list
        
        filtered_pathways['related_literature'] = filtered_pathways['validated_publications'].apply(extract_top_5_literature)
        print(f"   ✅ Added related_literature (top 5 papers) to {len(filtered_pathways)} pathways")
    
    if filtered_pathways.empty:
        print(f"⚠️  No filtered pathways for Module {module_id}")
        return {
            'module_id': module_id,
            'module_size': len(genes),
            'filtered_pathways': pd.DataFrame(),
            'biological_theme': "Unknown",
            'gpt_prediction': {},
            'validation_rate': 0.0
        }
    
    
    # Verify dual p-values exist
    if 'p_value' not in filtered_pathways.columns:
        print(f"⚠️  Warning: 'p_value' (FDR-corrected) column missing!")
    
    # Check for FDR p-value (might be in 'significant' flag or separate column)
    if 'fdr_p_value' not in filtered_pathways.columns and 'significant' in filtered_pathways.columns:
        # Use 'significant' flag as FDR indicator
        filtered_pathways['fdr_corrected'] = filtered_pathways['significant']
    
    
    # Verify planning agent scores exist
    required_scores = ['score', 'weighted_score']
    missing_scores = [col for col in required_scores if col not in filtered_pathways.columns]
    if missing_scores:
        print(f"⚠️  Warning: Missing planning agent scores: {missing_scores}")
    
    # Add module metadata
    filtered_pathways = filtered_pathways.copy()
    filtered_pathways['module_id'] = f"Module_{module_id}"
    filtered_pathways['module_size'] = len(genes)
    
    print(f"✅ Collected {len(filtered_pathways)} filtered pathways")
    print(f"   Validation rate: {results.get('validation_rate', 0):.1%}")
    
    # Print category breakdown
    if 'source' in filtered_pathways.columns and len(filtered_pathways) > 0:
        print(f"\n   📊 Category Breakdown (Matched Pathways):")
        category_counts = filtered_pathways['source'].value_counts()
        for category, count in category_counts.items():
            percentage = (count / len(filtered_pathways)) * 100
            print(f"      • {category:8s}: {count:3d} ({percentage:5.1f}%)")
    
    # GPT Autoranking now happens in  Step 4 of analyze_gpt_led_pathways method
    # No need for separate ranking step here

    
    
    return {
        'module_id': module_id,
        'module_name': f"{disease_name}_Module_{module_id}",  # Added module_name
        'module_size': len(genes),
        'genes': genes,  # CRITICAL: Include genes for per-module drug target analysis
        'filtered_pathways': filtered_pathways,  # Use GPT-ranked filtered_pathways, not original!
        'gpt_prediction': results.get('gpt_predicted', {}),
        'validation_rate': results.get('validation_rate', 0.0),
        'gprofiler_cache': gprofiler_cache,  # CRITICAL: Pass cache to iterations 2-3
        'user_feedback': 'APPROVE',  # Default to approved
        # CRITICAL: Include category_stats for Iteration 1 to be included in plots
        'category_stats': results.get('category_stats', None)
    }


def aggregate_module_pathways(all_module_pathways: List[Dict[str, Any]]) -> pd.DataFrame:
    """
    Aggregate pathways from all modules (simple concatenation, no deduplication).
    
    Design: Keep all pathway instances with module origins tracked.
    
    Parameters:
    -----------
    all_module_pathways : List[Dict]
        List of results from run_module_pathway_collection()
        
    Returns:
    --------
    DataFrame with columns:
        - All original pathway columns (name, description, p_value, etc.)
        - module_id: str (e.g., "Module_5")
        - module_size: int
        - biological_theme: str
        - Planning agent scores: score, tfidf_score, biobert_score, weighted_score
    """
    print(f"\n{'='*80}")
    print(f"AGGREGATING PATHWAYS FROM ALL MODULES")
    print(f"{'='*80}")
    
    all_pathways_list = []
    
    for module_data in all_module_pathways:
        module_id = module_data['module_id']
        filtered_pathways = module_data['filtered_pathways']
        
        if not filtered_pathways.empty:
            all_pathways_list.append(filtered_pathways)
            print(f"  Module {module_id}: {len(filtered_pathways)} pathways")
    
    if not all_pathways_list:
        print("⚠️  No pathways to aggregate!")
        return pd.DataFrame()
    
    # Reset index on each DataFrame before concatenation to fix InvalidIndexError
    # Different modules may have inconsistent indices or duplicate columns
    cleaned_list = []
    for df in all_pathways_list:
        df_clean = df.reset_index(drop=True)
        # Remove duplicate columns if any
        df_clean = df_clean.loc[:, ~df_clean.columns.duplicated()]
        cleaned_list.append(df_clean)
    
    # Simple concatenation (no deduplication)
    try:
        aggregated_df = pd.concat(cleaned_list, ignore_index=True, sort=False)
    except Exception as e:
        print(f"⚠️  pd.concat failed: {e}")
        print("   Attempting fallback with common columns only...")
        # Fallback: only keep common columns
        common_cols = set(cleaned_list[0].columns)
        for df in cleaned_list[1:]:
            common_cols &= set(df.columns)
        common_cols = list(common_cols)
        if 'name' in common_cols:
            cleaned_list = [df[common_cols].reset_index(drop=True) for df in cleaned_list]
            aggregated_df = pd.concat(cleaned_list, ignore_index=True, sort=False)
        else:
            print("❌ Cannot aggregate - no common columns")
            return pd.DataFrame()
    
    print(f"\n✅ Aggregated total: {len(aggregated_df)} pathway instances")
    print(f"   From {len(all_module_pathways)} modules")
    
    # Verify critical columns
    required_cols = ['module_id', 'p_value', 'score']
    missing_cols = [col for col in required_cols if col not in aggregated_df.columns]
    if missing_cols:
        print(f"⚠️  Warning: Missing required columns: {missing_cols}")
    
    # Count unique pathways (just for info, not used in filtering)
    if 'name' in aggregated_df.columns:
        unique_pathways = aggregated_df['name'].nunique()
        print(f"   Unique pathway names: {unique_pathways}")
        print(f"   Average instances per pathway: {len(aggregated_df) / unique_pathways:.1f}")
    
    # Print category breakdown for aggregated pathways
    if 'source' in aggregated_df.columns and len(aggregated_df) > 0:
        print(f"\n   📊 Category Breakdown (Aggregated):")
        category_counts = aggregated_df['source'].value_counts()
        for category in ['GO:BP', 'GO:MF', 'GO:CC', 'KEGG', 'REAC']:
            count = category_counts.get(category, 0)
            percentage = (count / len(aggregated_df)) * 100 if len(aggregated_df) > 0 else 0
            print(f"      • {category:8s}: {count:3d} pathways ({percentage:5.1f}%)")
        
        # Show any other categories
        other_categories = set(category_counts.index) - {'GO:BP', 'GO:MF', 'GO:CC', 'KEGG', 'REAC'}
        if other_categories:
            print(f"\n      Other categories:")
            for category in other_categories:
                count = category_counts[category]
                percentage = (count / len(aggregated_df)) * 100
                print(f"      • {category:8s}: {count:3d} pathways ({percentage:5.1f}%)")
    
    # Fix retained pathway ranks before returning
    aggregated_df = fix_retained_pathway_ranks(aggregated_df)
    
    return aggregated_df


def fix_retained_pathway_ranks(aggregated_df):
    """
    Fix gpt_rank=999 issue for retained pathways.
    
    For pathways that appear multiple times across modules, preserve the first
    valid gpt_rank encountered (not 999).
    
    Parameters:
    -----------
    aggregated_df : pd.DataFrame
        Aggregated pathways from all modules
        
    Returns:
    --------
    pd.DataFrame with corrected gpt_ranks
    """
    import pandas as pd
    import numpy as np
    
    if 'gpt_rank' not in aggregated_df.columns or 'name' not in aggregated_df.columns:
        return aggregated_df
    
    print(f"\n🔧 Fixing retained pathway ranks...")
    
    # Build pathway history: name -> first valid gpt_rank
    pathway_ranks = {}
    
    for _, row in aggregated_df.iterrows():
        name_lower = str(row['name']).lower()
        current_rank = row.get('gpt_rank', np.nan)
        
        # Record first valid rank we encounter
        if name_lower not in pathway_ranks:
            if pd.notna(current_rank) and current_rank != 999:
                pathway_ranks[name_lower] = current_rank
        else:
            # Already have this pathway, but maybe update if we find valid rank
            prev_rank = pathway_ranks[name_lower]
            if (pd.isna(prev_rank) or prev_rank == 999) and pd.notna(current_rank) and current_rank != 999:
                pathway_ranks[name_lower] = current_rank
    
    # Apply fixes
    fixed_count = 0
    for idx, row in aggregated_df.iterrows():
        name_lower = str(row['name']).lower()
        current_rank = row.get('gpt_rank', np.nan)
        
        if (pd.isna(current_rank) or current_rank == 999) and name_lower in pathway_ranks:
            valid_rank = pathway_ranks[name_lower]
            if pd.notna(valid_rank) and valid_rank != 999:
                aggregated_df.at[idx, 'gpt_rank'] = valid_rank
                fixed_count += 1
    
    if fixed_count > 0:
        print(f"   ✅ Fixed {fixed_count} pathways: rank=999 -> inherited rank")
    
    return aggregated_df
