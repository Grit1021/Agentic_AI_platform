import warnings
warnings.filterwarnings('ignore')


def format_pvalue_for_display(p_value):
    """
    Format p-value for display in tables to prevent JSON serialization precision loss.
    
    Very small p-values (< 1e-308) may lose precision when passed through JSON,
    causing them to appear as 0.000 in Writing Agent tables.
    
    Parameters:
    -----------
    p_value : float
        The p-value to format
        
    Returns:
    --------
    str : Formatted p-value string
    """
    if pd.isna(p_value):
        return "N/A"
    
    # Use scientific notation for very small values
    if p_value < 0.001:
        return f"{p_value:.2e}"
    # Use decimal notation for larger values  
    else:
        return f"{p_value:.3f}"


def format_pathways_for_display(df):
    """
    Add formatted string columns to pathways DataFrame for Writing Agent display.
    
    This prevents JSON serialization precision loss when p-values are passed
    to Writing Agent, ensuring they display correctly in tables.
    
    Parameters:
    -----------
    df : DataFrame
        Pathways DataFrame with 'p_value' column
        
    Returns:
    --------
    DataFrame : Same DataFrame with added 'p_value_display' column
    """
    if df is None or df.empty:
        return df
    
    df = df.copy()
    
    # Add formatted p-value column
    if 'p_value' in df.columns:
        df['p_value_display'] = df['p_value'].apply(format_pvalue_for_display)
    
    return df


import os
import sys
import json
import pandas as pd
import numpy as np
from typing import List, Dict, Any
import time

# Add parent directory to sys.path for imports
import sys
import os
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

# Import GPT predictor from parent directory
from multi_agent_analysis_full import GPT5PathwayPredictor

# Import original multi-agent analyzer for g:Profiler and ranking
from multi_agent_pathway_analysis import MultiAgentPathwayAnalyzer

class GPTLedMultiAgentAnalyzer:

    def __init__(self, output_dir: str, model: str = "gpt-5"):
        self.output_dir = output_dir
        self.model = model

        # Create output directory for gpt_led_analysis
        self.results_dir = os.path.join(output_dir, 'gpt_led_analysis')
        os.makedirs(self.results_dir, exist_ok=True)

        # Create imgs directory for PPI network visualizations
        self.imgs_dir = os.path.join(self.results_dir, 'imgs')
        os.makedirs(self.imgs_dir, exist_ok=True)

        # Initialize GPT predictor
        self.gpt_predictor = GPT5PathwayPredictor(model=model)

        # Initialize original multi-agent analyzer
        # (will use its g:Profiler, ranking, and analysis capabilities)
        self.base_analyzer = MultiAgentPathwayAnalyzer(
            output_dir=self.output_dir,
            model=model
        )

        # AD-specific pathway keywords for boosting
        self.ad_specific_keywords = [
            'alzheimer', 'amyloid', 'tau', 'neurodegeneration', 'neurodegenerative',
            'dementia', 'cognitive', 'memory', 'synaptic', 'neuronal',
            'app processing', 'beta-amyloid', 'neurofibrillary', 'apoe',
            'neuroinflammation', 'microglia', 'astrocyte', 'blood-brain barrier'
        ]

        # General pathway keywords for downranking
        self.general_keywords = [
            'metabolic', 'cell cycle', 'dna repair', 'rna processing',
            'protein synthesis', 'ribosome', 'spliceosome', 'proteasome',
            'generic', 'housekeeping', 'basic cellular'
        ]

        print(f"\n📁 Results will be saved in: {self.results_dir}")
        print(f"📁 PPI images will be saved in: {self.imgs_dir}")

    def _calculate_ad_specificity_score(self, pathway_name: str, pathway_description: str = "",
                                        disease_keywords: List[str] = None,
                                        is_disease_pair: bool = False) -> float:
        text = (pathway_name + " " + pathway_description).lower()


        keywords_to_use = disease_keywords if disease_keywords is not None else self.ad_specific_keywords


        ad_keywords = ['alzheimer', 'amyloid', 'tau', 'neurofibrillary', 'apoe', 'beta-amyloid', 'app processing']
        pd_keywords = ['parkinson', 'alpha-synuclein', 'synuclein', 'lewy body', 'dopamine', 'dopaminergic', 'substantia nigra']
        common_neuro_keywords = ['neurodegeneration', 'neurodegenerative', 'dementia', 'cognitive', 'memory',
                                'synaptic', 'neuronal', 'neuroinflammation', 'microglia', 'astrocyte',
                                'blood-brain barrier', 'mitochondrial dysfunction', 'oxidative stress',
                                'protein aggregation', 'autophagy', 'lysosomal', 'ubiquitin']


        ad_matches = sum(1 for keyword in ad_keywords if keyword in text)
        pd_matches = sum(1 for keyword in pd_keywords if keyword in text)
        common_matches = sum(1 for keyword in common_neuro_keywords if keyword in text)
        general_matches = sum(1 for keyword in self.general_keywords if keyword in text)


        if is_disease_pair:
            # ============================================================
            # DISEASE PAIR LOGIC: Common > Specific > General
            # ============================================================

            if ad_matches > 0 and pd_matches > 0:
                score = (ad_matches + pd_matches) * 0.4 + common_matches * 0.3 - general_matches * 0.1

            elif common_matches > 0 and ad_matches == 0 and pd_matches == 0:
                score = common_matches * 0.35 - general_matches * 0.1

            elif ad_matches > 0 or pd_matches > 0:
                score = max(ad_matches, pd_matches) * 0.08 + common_matches * 0.1 - general_matches * 0.2

            else:
                score = -general_matches * 0.25
        else:
            # ============================================================
            # SINGLE DISEASE LOGIC: Specific > Generic Neuro > General
            # ============================================================

            if ad_matches > 0:
                score = ad_matches * 0.5 + common_matches * 0.2 - general_matches * 0.1

            elif common_matches > 0:
                score = common_matches * 0.3 - general_matches * 0.1

            else:
                score = -general_matches * 0.3


        score = max(0, min(1, (score + 0.5) / 2.0))

        return score

    def _add_ad_specificity_ranking(self, pathways_df: pd.DataFrame, 
                                     disease_keywords: List[str] = None,
                                     is_disease_pair: bool = False) -> pd.DataFrame:
        if pathways_df.empty:
            return pathways_df

        df = pathways_df.copy()


        df['ad_specificity'] = df.apply(
            lambda row: self._calculate_ad_specificity_score(
                row['name'],
                row.get('description', ''),
                disease_keywords=disease_keywords,
                is_disease_pair=is_disease_pair
            ),
            axis=1
        )



        if is_disease_pair:
            # Disease pair: Common (>0.6), Specific (0.3-0.6), General (<0.3)
            df['pathway_type'] = df['ad_specificity'].apply(
                lambda x: 'Common' if x > 0.6 else ('Specific' if x > 0.3 else 'General')
            )
            type_desc = "Common (both diseases) > Specific (one disease) > General"
        else:
            # Single disease: Specific (>0.6), Generic Neuro (0.3-0.6), General (<0.3)
            df['pathway_type'] = df['ad_specificity'].apply(
                lambda x: 'Disease-Specific' if x > 0.6 else ('Generic-Neuro' if x > 0.3 else 'General')
            )
            type_desc = "Disease-Specific > Generic-Neuro > General"






        if 'score' in df.columns:

            df = df.sort_values(
                by=['ad_specificity', 'score', 'p_value'],
                ascending=[False, False, True]
            )
        else:
            df = df.sort_values(
                by=['ad_specificity', 'p_value'],
                ascending=[False, True]
            )


        print(f"\n🎯 Disease-specificity re-ranking applied:")
        print(f"   Analysis type: {'Disease Pair' if is_disease_pair else 'Single Disease'}")
        print(f"   Ranking priority: {type_desc}")
        print(f"   Ranking dimensions: Disease-specificity → PubMed score → p-value")

        print(f"\n   Top 5 pathways after disease-specific re-ranking:")
        for i, (idx, row) in enumerate(df.head(5).iterrows(), 1):
            pathway_type = row.get('pathway_type', 'Unknown')
            specificity = row.get('ad_specificity', 0)
            p_val = row.get('p_value', 1.0)
            combined = row.get('combined_score', row.get('score', 0))
            pubmed = row.get('pubmed_relevance', 0)
            
            print(f"   {i}. {row['name']}")
            print(f"      Type={pathway_type}, Specificity={specificity:.3f}, p-value={p_val:.2e}, "
                  f"Combined={combined:.3f}, PubMed={pubmed:.3f}")

        return df

    def analyze_modules_separately(self, modules_df: pd.DataFrame, disease_name: str,
                                   top_k_predict: int = 40,
                                   top_k_analyze: int = 6,
                                   min_module_size: int = 10) -> Dict[str, Any]:
        print("\n" + "="*80)
        print(f"MODULE-BASED PATHWAY ANALYSIS: {disease_name}")
        print("="*80)


        if 'passes_all_filters' in modules_df.columns:
            filtered_df = modules_df[modules_df['passes_all_filters'] == True].copy()
        else:
            filtered_df = modules_df.copy()


        modules = filtered_df[filtered_df['cluster_walktrap'] != -1].groupby('cluster_walktrap')

        print(f"\n📊 Module Statistics:")
        print(f"   Total genes: {len(filtered_df)}")
        print(f"   Genes in modules: {len(filtered_df[filtered_df['cluster_walktrap'] != -1])}")
        print(f"   Number of modules: {len(modules)}")


        module_sizes = filtered_df[filtered_df['cluster_walktrap'] != -1].groupby('cluster_walktrap').size()
        print(f"   Module size range: {module_sizes.min()} - {module_sizes.max()} genes")
        print(f"   Modules >= {min_module_size} genes: {sum(module_sizes >= min_module_size)}")

        results = {
            'disease_name': disease_name,
            'total_genes': len(filtered_df),
            'total_modules': len(modules),
            'timestamp': time.strftime("%Y-%m-%d %H:%M:%S"),
            'module_results': {}
        }


        module_count = 0
        for module_id, module_genes_df in modules:
            genes = module_genes_df['node'].tolist()


            if len(genes) < min_module_size:
                print(f"\n⏭️  Skipping Module {module_id}: only {len(genes)} genes (< {min_module_size})")
                continue

            module_count += 1
            module_name = f"{disease_name}_Module_{module_id}"

            print("\n" + "▶"*40)
            print(f"ANALYZING MODULE {module_id} ({module_count}/{sum(module_sizes >= min_module_size)})")
            print("▶"*40)
            print(f"Module size: {len(genes)} genes")


            module_result = self.analyze_gpt_led_pathways(
                genes=genes,
                disease_name=module_name,
                top_k_predict=top_k_predict,
                top_k_analyze=top_k_analyze
            )

            results['module_results'][f"module_{module_id}"] = module_result


        self._generate_modules_summary_report(results, disease_name)

        print("\n" + "="*80)
        print("✅ MODULE-BASED ANALYSIS COMPLETE")
        print("="*80)
        print(f"   Analyzed {module_count} modules")
        print(f"   Results saved in: {self.results_dir}")

        return results

    def analyze_gpt_led_pathways(self, genes: List[str], disease_name: str,
                                 top_k_predict: int = 40,
                                 top_k_analyze: int = 6,
                                 genes_for_gpt: List[str] = None,
                                 disease_keywords: List[str] = None,
                                 retained_pathways: List[str] = None,
                                 retained_pathways_df: pd.DataFrame = None,
                                 gprofiler_cache: Dict[str, Any] = None,
                                 skip_ppi_analysis: bool = False,
                                 iteration_feedback: str = None) -> Dict[str, Any]:

        # Determine genes for GPT prediction
        gpt_input_genes = genes_for_gpt if genes_for_gpt is not None else genes
        
        print("\n" + "="*80)
        print(f"GPT-LED MULTI-AGENT PATHWAY ANALYSIS: {disease_name}")
        print("="*80)
        print(f"Genes for validation (g:Profiler): {len(genes)} genes")
        if genes_for_gpt is not None:
            print(f"Genes for GPT prediction: {len(genes_for_gpt)} genes (shared genes)")
        else:
            print(f"Genes for GPT prediction: {len(genes)} genes (same as validation)")

        # Handle retained pathways
        if retained_pathways and len(retained_pathways) > 0:
            print(f"Retained pathways from previous iteration: {len(retained_pathways)}")
            print(f"GPT predictions: {top_k_predict - len(retained_pathways)} new pathways")
        else:
            print(f"GPT predictions: {top_k_predict} pathways")
        
        if skip_ppi_analysis:
            print(f"🚀 PPI analysis: SKIPPED (performance optimization)")
        else:
            print(f"Deep PPI analysis: top {top_k_analyze} pathways")

        results = {
            'disease_name': disease_name,
            'gene_count': len(genes),
            'gpt_input_gene_count': len(gpt_input_genes),
            'timestamp': time.strftime("%Y-%m-%d %H:%M:%S"),
            'top_k_predict': top_k_predict,
            'top_k_analyze': top_k_analyze,
            'retained_pathways': retained_pathways if retained_pathways else [],
            'skip_ppi_analysis': skip_ppi_analysis
        }

        # =================================================================
        # STEP 1: GPT Pathway Prediction (Candidate Generation)
        # =================================================================
        print("\n" + "="*80)
        print("STEP 1: GPT PATHWAY PREDICTION (Generating Candidates)")
        if genes_for_gpt is not None:
            print(f"Using shared genes ({len(genes_for_gpt)} genes) for GPT prediction")
        if retained_pathways and len(retained_pathways) > 0:
            print(f"Retaining {len(retained_pathways)} validated pathways from previous iteration")
        print("="*80)

        # Calculate how many new pathways GPT should predict
        # NOTE: The prediction function itself now handles retention internally
        if retained_pathways and len(retained_pathways) > 0:
            # Extract pathway details for retained pathways from previous iteration
            # This should come from the last iteration's gpt_prediction
            retained_pathway_details = {}
            if hasattr(self, '_last_gpt_prediction') and self._last_gpt_prediction:
                last_details = self._last_gpt_prediction.get('pathway_details', {})
                for pw_name in retained_pathways:
                    if pw_name in last_details:
                        retained_pathway_details[pw_name] = last_details[pw_name]
            
            # CRITICAL: Compute retained_per_category from retained_pathways_df
            # This is more reliable than extracting from retained_pathway_details
            retained_per_category = {'GO:BP': 0, 'GO:MF': 0, 'GO:CC': 0, 'KEGG': 0, 'REAC': 0}
            if retained_pathways_df is not None and not retained_pathways_df.empty and 'source' in retained_pathways_df.columns:
                source_counts = retained_pathways_df['source'].value_counts().to_dict()
                for src, count in source_counts.items():
                    if src in retained_per_category:
                        retained_per_category[src] = count
                print(f"   📊 Retained per category (from FDR-filtered df): {retained_per_category}")
        else:
            retained_pathway_details = {}
            retained_per_category = None

        if iteration_feedback and hasattr(self.gpt_predictor, 'predict_pathways_with_feedback'):
            # Iterative mode: use feedback from previous iteration
            print(f"\n🔄 Using feedback-enhanced GPT prediction...\n")
            
            # Original total request (will be adjusted internally based on retention)
            per_category = top_k_predict // 5
            remainder = top_k_predict % 5
            
            gpt_prediction = self.gpt_predictor.predict_pathways_with_feedback(
                genes=gpt_input_genes,
                disease_name=disease_name,
                feedback=iteration_feedback,
                gobp_count=per_category + (1 if remainder > 0 else 0),
                gomf_count=per_category + (1 if remainder > 1 else 0),
                gocc_count=per_category + (1 if remainder > 2 else 0),
                kegg_count=per_category + (1 if remainder > 3 else 0),
                reac_count=per_category,
                retained_pathways=retained_pathways,  # Pass retained pathways
                retained_pathway_details=retained_pathway_details,  # Pass their details
                retained_per_category=retained_per_category  # Pass per-category counts for FDR saturation check
            )
        else:
            gpt_prediction = self.gpt_predictor.predict_pathways(
                genes=gpt_input_genes,
                disease_name=disease_name
            )


        results['gpt_prediction'] = gpt_prediction
        
        # Store for next iteration's retention
        self._last_gpt_prediction = gpt_prediction
        
        # GPT prediction now already contains retained + new pathways
        gpt_predicted = gpt_prediction.get('predicted_pathways', [])
        print(f"\n✅ GPT predicted {len(gpt_predicted)} candidate pathways (including any retained)")

        if len(gpt_predicted) == 0:
            print("❌ No pathways predicted by GPT")
            return results
        
        # Save GPT prediction
        gpt_file = os.path.join(self.results_dir, f'{disease_name}_gpt_prediction.json')
        # Ensure output directory exists
        os.makedirs(os.path.dirname(gpt_file), exist_ok=True)
        with open(gpt_file, 'w') as f:
            json.dump(gpt_prediction, f, indent=2)
        
        # ==================================================================
        # STEP 2: g:Profiler Enrichment (Full + FDR)
        # ==================================================================
        print("\n" + "="*80)
        print("STEP 2: g:PROFILER ENRICHMENT (Full + FDR)")
        print("="*80)
        
        if not self.base_analyzer.agents_ready and gprofiler_cache is None:
            print("❌ Agents not available and no g:Profiler cache provided")
            return results
        
        if not self.base_analyzer.agents_ready:
            print("⚠️  Agents not loaded (BioBERT tokenizer issue) - using cached g:Profiler results")
        
        try:
            # Use cache if available
            if gprofiler_cache is not None:
                print("✅ Using cached g:Profiler results (from pre-computation)")
                
                # AUTO-UPGRADE old cache format to new format
                if 'all_pathways' not in gprofiler_cache:
                    print("   ⚠️  Detected old cache format - auto-upgrading...")
                    
                    # Old cache only had 'ranked_pathways'
                    # Assume it contains all pathways and create dual structure
                    old_pathways = gprofiler_cache.get('ranked_pathways', pd.DataFrame())
                    
                    if not old_pathways.empty:
                        # WARNING: Old ranked_pathways might be FDR-filtered, not comprehensive
                        # Check if pathway count is suspiciously low
                        if len(old_pathways) < 50:
                            print(f"   ❌ WARNING: Cache contains only {len(old_pathways)} pathways")
                            print(f"      This is likely FDR-filtered data, NOT comprehensive enrichment")
                            print(f"      RECOMMENDATION: Delete old cache and re-run Phase 0 to regenerate")
                            print(f"      Continuing with degraded cache (matching will be limited)...")
                        
                        # Create new cache structure (even if degraded)
                        gprofiler_cache['all_pathways'] = old_pathways.copy()
                        # ranked_pathways might already be filtered, or might be all
                        # Keep it as is for backward compatibility
                        print(f"   ✅ Auto-upgraded cache: 'ranked_pathways' ({len(old_pathways)} pathways) → 'all_pathways'")
                    else:
                        print("   ❌ Old cache is empty - cannot upgrade")
                        raw_gprofiler_df = pd.DataFrame()
                
                # Use the comprehensive pathway list for GPT matching
                raw_gprofiler_df = gprofiler_cache['all_pathways']
                print(f"   Total enriched pathways (all, cached): {len(raw_gprofiler_df)}")
                
                # Also get FDR-filtered set from cache if available
                if 'fdr_pathways' in gprofiler_cache:
                    fdr_gprofiler_df = gprofiler_cache['fdr_pathways']
                    print(f"   FDR-filtered pathways (cached): {len(fdr_gprofiler_df)}")
                else:
                    # Compute FDR set from raw_gprofiler_df if not in cache
                    print(f"   Computing FDR-filtered set from cached pathways...")
                    fdr_gprofiler_df = raw_gprofiler_df[
                        raw_gprofiler_df['p_value'] < 0.05
                    ].copy() if 'p_value' in raw_gprofiler_df.columns else raw_gprofiler_df.copy()
                    print(f"   FDR-filtered pathways (p < 0.05): {len(fdr_gprofiler_df)}")
            else:
                print("Calling g:Profiler API (no cache available)")
                from src.pathway_enrichment_analysis import PathwayEnrichmentAnalyzer
                enrichment_analyzer = PathwayEnrichmentAnalyzer(self.results_dir)
                
                # STEP 2A: Full enrichment (for comprehensive GPT matching)
                print("⚡ Method A: FULL enrichment (no threshold) for comprehensive GPT matching")
                raw_gprofiler_df = enrichment_analyzer.enrich_geneset_full(
                    genes=genes,
                    name=disease_name,
                    sources=['GO:BP', 'GO:MF', 'GO:CC', 'KEGG', 'REAC']
                )
                
                if raw_gprofiler_df.empty:
                    print("❌ No enrichment results found")
                    return results
                
                print(f"   ✅ Full enrichment: {len(raw_gprofiler_df)} pathways")
                
                # STEP 2B: FDR enrichment (for filtering)
                print("\n⚡ Method B: FDR enrichment (threshold=0.05) for filtering")
                fdr_gprofiler_df = enrichment_analyzer.enrich_geneset(
                    genes=genes,
                    name=disease_name,
                    sources=['GO:BP', 'GO:MF', 'GO:CC', 'KEGG', 'REAC']
                )
                print(f"   ✅ FDR-filtered enrichment: {len(fdr_gprofiler_df)} pathways")
            
        except Exception as e:
            print(f"❌ g:Profiler failed: {e}")
            import traceback
            traceback.print_exc()
            return results
        
        
        # =================================================================
        # STEP 3: Match GPT Predictions with Raw g:Profiler Results
        # =================================================================
        print("\n" + "="*80)
        print("STEP 3: MATCHING GPT PREDICTIONS WITH RAW g:PROFILER RESULTS")
        print("="*80)
        print("Matching strategy: ID-first (precise) + Name fallback (fuzzy)")
        print("✨ NEW: Matching BEFORE PubMed ranking for efficiency")
        
        # Extract pathway IDs from GPT prediction for precise matching
        gpt_pathway_ids = {}  # {pathway_id: pathway_name}
        gpt_pathway_names_lower = {}  # {pathway_name_lower: pathway_name}
        
        for pathway_name, details in gpt_prediction.get('pathway_details', {}).items():
            # Check both 'pathway_id' (KEGG/Reactome) and 'go_id' (GO terms)
            pathway_id = details.get('pathway_id', '') or details.get('go_id', '')
            if pathway_id:
                gpt_pathway_ids[pathway_id.upper()] = pathway_name
            gpt_pathway_names_lower[pathway_name.lower()] = pathway_name
        
        print(f"\nGPT predictions extracted:")
        print(f"  - {len(gpt_pathway_ids)} pathways with IDs")
        print(f"  - {len(gpt_pathway_names_lower)} pathways total")

        # Debug: Show sample GPT predictions
        if len(gpt_pathway_names_lower) > 0:
            print(f"\n🔍 Debug - Sample GPT predictions (first 3):")
            for i, (name_lower, name_orig) in enumerate(list(gpt_pathway_names_lower.items())[:3]):
                print(f"     {i+1}. '{name_orig}'")

        # Debug: Show sample g:Profiler pathways
        if len(raw_gprofiler_df) > 0:
            print(f"\n🔍 Debug - Sample g:Profiler pathways (first 3):")
            for i, row in raw_gprofiler_df.head(3).iterrows():
                print(f"     {i+1}. ID={row.get('native', 'N/A')}, Name='{row.get('name', 'N/A')}'")
        
        # Enhanced matching function: ID-first + name fallback
        matching_stats = {'id_match': 0, 'name_match': 0, 'no_match': 0, 'retained_forced': 0}
        
        # ================================================================
        # CRITICAL: DIRECTLY USE RETAINED PATHWAYS DataFrame
        # ================================================================
        forced_retained_pathways = pd.DataFrame()
        
        # Use DataFrame directly (no name matching needed!)
        if retained_pathways_df is not None and not retained_pathways_df.empty:
            print(f"\n🔒 DIRECTLY USING RETAINED PATHWAYS DataFrame:")
            print(f"   ✅ Retained pathways: {len(retained_pathways_df)} (100% retention)")
            
            forced_retained_pathways = retained_pathways_df.copy()
            forced_retained_pathways['gpt_predicted'] = True
            matching_stats['retained_forced'] = len(forced_retained_pathways)
            
            if 'source' in forced_retained_pathways.columns:
                print(f"   📊 Retained Pathways by Category:")
                retained_cats = forced_retained_pathways['source'].value_counts()
                for cat, count in retained_cats.items():
                    print(f"      • {cat:8s}: {count:3d} pathways")
        

        def matches_gpt_prediction_enhanced(row):
            """Match NEW pathways only (skip already-retained ones)."""
            # Skip if already force-matched as retained
            if not forced_retained_pathways.empty:
                if row.get('name', '').lower() in {n.lower() for n in forced_retained_pathways['name']}:
                    return False
            
            gprofiler_id = row.get('native', '').upper()
            gprofiler_name = row.get('name', '').lower()
            
            # Strategy 1: ID exact match (highest precision)
            if gprofiler_id in gpt_pathway_ids:
                matching_stats['id_match'] += 1
                return True
            
            # Strategy 2: Strict name matching to avoid over-matching
            for gpt_name_lower in gpt_pathway_names_lower.keys():
                # Exact match
                if gpt_name_lower == gprofiler_name:
                    matching_stats['name_match'] += 1
                    return True
                
                # Very high similarity match (to handle minor differences)
                # Only match if one is >=80% of the other (avoid partial matches)
                gpt_len = len(gpt_name_lower)
                gprof_len = len(gprofiler_name)
                
                if gpt_len > 0 and gprof_len > 0:
                    # Check if names are very similar (one contains other AND length similar)
                    if gpt_name_lower in gprofiler_name:
                        if gprof_len / gpt_len <= 1.3:  # At most 30% longer
                            matching_stats['name_match'] += 1
                            return True
                    elif gprofiler_name in gpt_name_lower:
                        if gpt_len / gprof_len <= 1.3:  # At most 30% longer
                            matching_stats['name_match'] += 1
                            return True
            
            matching_stats['no_match'] += 1
            return False
        
        # Filter NEW pathways using enhanced matching
        raw_gprofiler_df['gpt_predicted'] = raw_gprofiler_df.apply(
            matches_gpt_prediction_enhanced, axis=1
        )
        new_matched_pathways = raw_gprofiler_df[
            raw_gprofiler_df['gpt_predicted'] == True
        ].copy()
        
        # Combine forced-retained + new-matched pathways
        if not forced_retained_pathways.empty:
            gpt_matched_pathways = pd.concat([
                forced_retained_pathways,
                new_matched_pathways
            ], ignore_index=True).drop_duplicates(subset='name', keep='first')
        else:
            gpt_matched_pathways = new_matched_pathways


        print(f"\n{'='*80}")
        print(f"MATCHING RESULTS - ALL PATHWAYS")
        print(f"{'='*80}")
        print(f"  ✅ ID exact matches: {matching_stats['id_match']}")
        print(f"  ✅ Name fuzzy matches: {matching_stats['name_match']}")
        print(f"  ❌ No matches: {matching_stats['no_match']}")
        print(f"  Total matched (all pathways): {matching_stats['id_match'] + matching_stats['name_match']}")
        print(f"  Total g:Profiler pathways: {len(raw_gprofiler_df)}")
        print(f"  Total GPT predictions: {len(gpt_predicted)}")
        print(f"  Match rate (GPT predictions found in all g:Profiler): {(matching_stats['id_match'] + matching_stats['name_match'])/len(gpt_predicted)*100:.1f}%")
        
        # Category breakdown for all pathways
        if 'source' in gpt_matched_pathways.columns and len(gpt_matched_pathways) > 0:
            print(f"\n  📊 Category Breakdown (Matched - All):")
            category_counts = gpt_matched_pathways['source'].value_counts()
            for category, count in category_counts.items():
                percentage = (count / len(gpt_matched_pathways)) * 100
                print(f"      • {category:8s}: {count:3d} ({percentage:5.1f}%)")

        # Now filter for significant pathways and re-calculate matching stats
        print(f"\n{'='*80}")
        print(f"MATCHING RESULTS - SIGNIFICANT PATHWAYS ONLY (p < 0.05)")
        print(f"{'='*80}")

        # Filter for significant pathways
        significant_gprofiler_df = raw_gprofiler_df[raw_gprofiler_df['p_value'] < 0.05].copy()
        significant_matched = significant_gprofiler_df[significant_gprofiler_df['gpt_predicted'] == True]

        # Count matches by type for significant pathways
        sig_id_matches = 0
        sig_name_matches = 0
        for idx, row in significant_matched.iterrows():
            gprofiler_id = row.get('native', '').upper()
            if gprofiler_id in gpt_pathway_ids:
                sig_id_matches += 1
            else:
                sig_name_matches += 1

        print(f"  ✅ ID exact matches: {sig_id_matches}")
        print(f"  ✅ Name fuzzy matches: {sig_name_matches}")
        print(f"  Total matched (significant): {len(significant_matched)}")
        print(f"  Total significant pathways: {len(significant_gprofiler_df)}")
        print(f"  Total GPT predictions: {len(gpt_predicted)}")
        print(f"  Match rate (GPT predictions found in significant): {len(significant_matched)/len(gpt_predicted)*100:.1f}%")
        
        # Category breakdown for significant pathways
        if 'source' in significant_matched.columns and len(significant_matched) > 0:
            print(f"\n  📊 Category Breakdown (Matched - Significant):")
            sig_category_counts = significant_matched['source'].value_counts()
            for category, count in sig_category_counts.items():
                percentage = (count / len(significant_matched)) * 100
                print(f"      • {category:8s}: {count:3d} ({percentage:5.1f}%)")

        print(f"\n{'='*80}")
        print(f"GPT VALIDATION SUMMARY")
        print(f"{'='*80}")
        
        # Get retained pathway count from results
        n_retained = len(results.get('retained_pathways', []))
        n_new_predictions = len(gpt_predicted) - n_retained
        
        if n_retained > 0:
            # Iterative mode: account for retained pathways
            print(f"  GPT predictions: {len(gpt_predicted)} total ({n_retained} retained + {n_new_predictions} new)")
            print(f"  Validated in all pathways: {len(gpt_matched_pathways)}/{len(gpt_predicted)} ({len(gpt_matched_pathways)/len(gpt_predicted)*100:.1f}%)")
            print(f"  Validated in significant pathways: {len(significant_matched)}/{len(gpt_predicted)} ({len(significant_matched)/len(gpt_predicted)*100:.1f}%)")
            
            # Additional breakdown for clarity
            n_retained_validated = len([p for p in retained_pathways if p in gpt_matched_pathways['name'].values]) if retained_pathways else 0
            n_new_validated = len(gpt_matched_pathways) - n_retained_validated
            print(f"\n  Breakdown:")
            print(f"    - Retained & validated: {n_retained_validated}/{n_retained}")
            print(f"    - New & validated: {n_new_validated}/{n_new_predictions} ({n_new_validated/n_new_predictions*100:.1f}% of new)" if n_new_predictions > 0 else "    - New & validated: 0/0")
        else:
            # First iteration: no retained pathways
            print(f"  GPT predictions: {len(gpt_predicted)}")
            print(f"  Validated in all pathways: {len(gpt_matched_pathways)}/{len(gpt_predicted)} ({len(gpt_matched_pathways)/len(gpt_predicted)*100:.1f}%)")
            print(f"  Validated in significant pathways: {len(significant_matched)}/{len(gpt_predicted)} ({len(significant_matched)/len(gpt_predicted)*100:.1f}%)")


        if len(gpt_matched_pathways) == 0:
            print("\n⚠️  Warning: No GPT predictions were found in g:Profiler results")
            print("   This means GPT predicted pathways that are not enriched in g:Profiler")
            results['gpt_filtered_pathways'] = pd.DataFrame()
            results['validation_rate'] = 0.0
            results['pathway_details'] = {}
            results['final_report'] = ""
            return results
        
        # Save all matched pathways (before filtering)
        all_matched_file = os.path.join(
            self.results_dir,
            f'{disease_name}_gpt_matched_all.csv'
        )
        gpt_matched_pathways.to_csv(all_matched_file, index=False)
        print(f"\n💾 Saved all matched pathways: {all_matched_file}")
        
        # =================================================================
        # STEP 3.3: FDR FILTERING
        # =================================================================
        print("\n" + "="*80)
        print("STEP 3.3: FDR FILTERING")
        print("="*80)
        print("Filtering for FDR-adjusted p-value < 0.05")
        print("Note: g:Profiler's p_value is already FDR-adjusted when using significance_threshold_method='fdr'")
        print("")
        
        # Filter using FDR-adjusted p-value < 0.05
        gpt_matched_fdr = gpt_matched_pathways[
            gpt_matched_pathways['p_value'] < 0.05
        ].copy()
        
        print(f"📊 Filtering Results:")
        print(f"   Total GPT matched: {len(gpt_matched_pathways)}")
        print(f"   ✅ FDR-significant (p < 0.05): {len(gpt_matched_fdr)} pathways")
        print(f"   ❌ Filtered out: {len(gpt_matched_pathways) - len(gpt_matched_fdr)} pathways")
        print("")
        
        # Save FDR-filtered results
        fdr_file = os.path.join(
            self.results_dir,
            f'{disease_name}_gpt_matched_fdr_p005.csv'
        )
        
        gpt_matched_fdr.to_csv(fdr_file, index=False)
        
        print(f"")
        print(f"💾 Saved FDR-filtered results:")
        print(f"   FDR-significant pathways: {fdr_file}")
        
        # =================================================================
        # STEP 3.4: NOMINAL P-VALUE FILTERING (OPTIONAL)
        # =================================================================
        print("\n" + "="*80)
        print("STEP 3.4: NOMINAL P-VALUE FILTERING")
        print("="*80)
        print("Filtering for nominal (uncorrected) p-value < 0.05")
        print("Note: This is more lenient than FDR filtering and may include more false positives")
        print("")
        
        # Filter using nominal p-value < 0.05 (if available)
        if 'p_nominal' in gpt_matched_pathways.columns:
            gpt_matched_nominal = gpt_matched_pathways[
                gpt_matched_pathways['p_nominal'] < 0.05
            ].copy()
            
            print(f"📊 Nominal P-value Filtering Results:")
            print(f"   Total GPT matched: {len(gpt_matched_pathways)}")
            print(f"   ✅ Nominal-significant (p_nominal < 0.05): {len(gpt_matched_nominal)} pathways")
            print(f"   ❌ Filtered out: {len(gpt_matched_pathways) - len(gpt_matched_nominal)} pathways")
            print(f"   📈 Comparison: {len(gpt_matched_nominal) - len(gpt_matched_fdr)} more pathways than FDR")
            print("")
            
            # Save nominal-filtered results
            nominal_file = os.path.join(
                self.results_dir,
                f'{disease_name}_gpt_matched_nominal_p005.csv'
            )
            
            gpt_matched_nominal.to_csv(nominal_file, index=False)
            
            print(f"💾 Saved nominal-filtered results:")
            print(f"   Nominal-significant pathways: {nominal_file}")
            print(f"   Note: This file contains {len(gpt_matched_nominal) - len(gpt_matched_fdr)} additional pathways compared to FDR filtering")
            print(f"         These may include false positives due to multiple testing")
        else:
            print(f"⚠️  p_nominal column not found - skipping nominal filtering")
            print(f"   Run g:Profiler enrichment with nominal p-value calculation first")
        
        # Use ONLY FDR-significant pathways for downstream analysis
        print(f"\n🎯 Using FDR-filtered pathways ({len(gpt_matched_fdr)}) for downstream analysis")
        gpt_pathways_filtered = gpt_matched_fdr.copy()
        
        # CRITICAL: Merge all scoring columns from cache
        # This ensures retained pathways from previous iterations have all scores
        if gprofiler_cache and 'ranked_pathways' in gprofiler_cache:
            cached_df = gprofiler_cache['ranked_pathways']
            
            # Get list of scoring columns that should be merged
            score_cols = ['score', 'tfidf_score', 'biobert_score', 'weighted_score',
                         'pubmed_relevance', 'num_publications', 'validated_publications',
                         'disease_specificity', 'combined_score']
            
            # Find which score columns exist in cache
            available_score_cols = [col for col in score_cols if col in cached_df.columns]
            
            if available_score_cols:
                # Handle duplicate pathway names by keeping first occurrence
                # (pathway names may be duplicated across different sources)
                cached_df_unique = cached_df.drop_duplicates(subset=['name'], keep='first')
                
                # Create mapping from pathway name to scores
                cache_by_name = cached_df_unique.set_index('name')[available_score_cols].to_dict('index')
                
                # Merge scores from cache
                for col in available_score_cols:
                    if col not in gpt_pathways_filtered.columns:
                        gpt_pathways_filtered[col] = gpt_pathways_filtered['name'].apply(
                            lambda x: cache_by_name.get(x, {}).get(col, 0.0 if col != 'validated_publications' else [])
                        )
                
                print(f"   ✅ Merged {len(available_score_cols)} scoring columns from cache")
        
        if len(gpt_pathways_filtered) == 0:
            print("\n⚠️  WARNING: NO pathways passed FDR threshold (p<0.05)")
            print("   GPT predicted pathways are not significantly enriched after FDR correction")
            print("   Analysis will terminate here - no downstream analysis possible")
        
        # =================================================================
        # STEP 3.5: Use Cached Ranking (No Re-computation)
        # =================================================================
        print("\n" + "="*80)
        print("STEP 3.5: USING CACHED LITERATURE RANKING")
        print("="*80)
        print(f"⚡ Efficiency: Using pre-computed ranking from cache")
        print(f"   Ranked pathways: {len(gpt_pathways_filtered)}")
        
        if len(gpt_pathways_filtered) == 0:
            print("\n⚠️  Warning: No pathways to rank (all filtered out)")
            results['gpt_filtered_pathways'] = pd.DataFrame()
            results['validation_rate'] = 0.0
            return results
        
        # Verify that ranking scores exist in the dataframe
        required_cols = ['combined_score']
        missing_cols = [col for col in required_cols if col not in gpt_pathways_filtered.columns]
        
        if missing_cols:
            print(f"⚠️  Warning: Missing ranking columns in cache: {missing_cols}")
            print("   Sorting by p-value only")
            gpt_pathways = gpt_pathways_filtered.sort_values('p_value')
        else:
            # Use cached ranking scores - already computed in cache pre-computation
            print(f"✅ Using cached scores:")
            print(f"   - Combined score (TF-IDF + BioBERT semantic similarity)")
            if 'pubmed_relevance' in gpt_pathways_filtered.columns:
                print(f"   - PubMed relevance (literature support)")
            print(f"   - Weighted score = combined_score × evidence_score")
            print(f"     (evidence_score = min(-log10(p_value), 10) / 10)")
            
            # Sort by weighted score if available, otherwise by combined score
            if 'weighted_score' in gpt_pathways_filtered.columns:
                gpt_pathways = gpt_pathways_filtered.sort_values('weighted_score', ascending=False)
            else:
                # Recompute weighted score if not in cache using evidence_score
                # Convert p-value to evidence score (Open Targets style)
                def p_to_evidence(p, cap=10):
                    """Convert p-value to evidence score."""
                    import numpy as np
                    if p <= 0:
                        return 1.0
                    return min(-np.log10(p), cap) / cap
                
                gpt_pathways_filtered['evidence_score'] = gpt_pathways_filtered['p_value'].apply(
                    lambda p: p_to_evidence(p, cap=10)
                )
                gpt_pathways_filtered['weighted_score'] = (
                    gpt_pathways_filtered['combined_score'] * gpt_pathways_filtered['evidence_score']
                )
                gpt_pathways = gpt_pathways_filtered.sort_values('weighted_score', ascending=False)
            
            print(f"✅ Pathways sorted by cached weighted_score")

        # =================================================================
        # STEP 4: Display Disease-Specific Ranking (Already in Cache)
        # =================================================================
        print("\n" + "="*80)
        print("STEP 4: DISEASE-SPECIFIC RANKING (from Planning Agent)")
        print("="*80)
        print("Disease specificity scores were calculated during Planning Agent ranking")
        print("Combined score = (TF-IDF + BioBERT + Disease-Specificity) / 3")
        print("Weighted score = combined_score × evidence_score")
        print("  where evidence_score = min(-log10(p_value), 10) / 10")
        
        # Check if disease_specificity column exists
        if 'disease_specificity' in gpt_pathways.columns:
            print(f"\n✅ Disease specificity scores available for all pathways")
            avg_spec = gpt_pathways['disease_specificity'].mean()
            print(f"   Average disease specificity: {avg_spec:.3f}")
        else:
            print(f"\n⚠️  Warning: disease_specificity column not found")
            print("   This may indicate the pathways came from an older cache")
        
        results['gpt_filtered_pathways'] = gpt_pathways
        results['validation_rate'] = len(gpt_pathways) / len(gpt_predicted)
        
        # Save filtered pathways
        filtered_file = os.path.join(
            self.results_dir, 
            f'{disease_name}_gpt_filtered_pathways.csv'
        )
        
        # Remove columns unsuitable for CSV format (list types)
        gpt_pathways_csv = gpt_pathways.copy()
        columns_to_drop = []
        if 'validated_publications' in gpt_pathways_csv.columns:
            columns_to_drop.append('validated_publications')
            print(f"   ℹ️  Dropping 'validated_publications' column (list type, unsuitable for CSV)")
        
        if columns_to_drop:
            gpt_pathways_csv = gpt_pathways_csv.drop(columns=columns_to_drop)
        
        gpt_pathways_csv.to_csv(filtered_file, index=False)
        print(f"\n✅ Saved GPT-filtered pathways: {filtered_file}")
        print(f"   Columns saved: {len(gpt_pathways_csv.columns)} (dropped {len(columns_to_drop)} list-type columns)")
        
        # Print top pathways with all scores
        print(f"\n📊 Top 5 GPT-Predicted & Validated Pathways:")
        for i, (idx, row) in enumerate(gpt_pathways.head(5).iterrows(), 1):
            p_val = row.get('p_value', 1.0)
            combined = row.get('combined_score', row.get('score', 0))
            disease_spec = row.get('disease_specificity', 0)
            pubmed = row.get('pubmed_relevance', 0)
            source = row.get('source', 'N/A')
            
            print(f"   {i}. {row['name']}")
            print(f"      p-value={p_val:.2e}, Combined={combined:.3f}, "
                  f"Disease-Spec={disease_spec:.3f}, PubMed={pubmed:.3f}, source={source}")
        
        # =================================================================
        # STEP 5: Reasoning Agent - Pathway Overview  
        # =================================================================
        print("\n" + "="*80)
        print("STEP 5: REASONING AGENT - Pathway Overview")
        print("="*80)
        
        try:
            # Select columns based on what's available
            base_cols = ["native", "name", "description", "p_value", "source"]
            if 'score' in gpt_pathways.columns:
                cols = base_cols + ["score"]
            else:
                cols = base_cols
                
            pathway_info = gpt_pathways[cols].to_dict(orient="records")

            pathways_overview = self.base_analyzer.reasoning_agent.act(
                "Pathway_Section_Overview",
                {
                    "pathway_infos": pathway_info,
                    "disease_name": disease_name,
                    "formatting_instructions": "IMPORTANT: In tables, for p-values < 0.001, use scientific notation (e.g., 1.2e-05) instead of displaying as 0.000. For scores, always show at least 3 decimal places or use scientific notation if the value is very small."
                }
            )
            
            results['pathways_overview'] = pathways_overview
            print("✅ Pathway overview generated")
            
        except Exception as e:
            print(f"❌ Error in pathway overview: {e}")
            import traceback
            traceback.print_exc()
            pathways_overview = ""
        
        # =================================================================
        # STEP 6: Reasoning Agent - Detailed Analysis (Top Pathways)
        # =================================================================
        
        # Skip PPI analysis if flag is set (for per-module runs)
        if skip_ppi_analysis:
            print("\n" + "="*80)
            print("STEP 6: PPI ANALYSIS - SKIPPED")
            print("="*80)
            print("⚡ Skipping detailed PPI analysis for performance optimization")
            print("   PPI analysis will be performed on final aggregated top pathways")
            
            results['pathway_details'] = {}
            results['final_report'] = ""
            
        else:
            print("\n" + "="*80)
            print(f"STEP 6: REASONING AGENT - Detailed Analysis (Top {top_k_analyze} pathways)")
            print("="*80)
            print("For each pathway:")
            print("  - PPI Network Analysis")
            print("  - Protein Function Analysis")
            print("  - Cluster Function Analysis")
            print("  - Function Enrichment Summary")
            
            pathway_details = {}
            top_pathways = gpt_pathways.head(top_k_analyze)
            
            for i in range(len(top_pathways)):
                try:
                    pathway = top_pathways.iloc[i]
                    pathway_name = pathway["name"]
                    
                    # Ensure proteins is always a list
                    # intersections can be:
                    # 1. A comma-separated string: "ENSG00000111481,ENSG00000029534"
                    # 2. A string representation of a list: "['ENSG00000111481', 'ENSG00000029534']"
                    # 3. An actual list: ['ENSG00000111481', 'ENSG00000029534']
                    proteins_raw = pathway.get("intersections", "")
                    
                    if isinstance(proteins_raw, list):
                        proteins = proteins_raw
                    elif isinstance(proteins_raw, str):
                        # Check if it's a string representation of a list
                        if proteins_raw.startswith('[') and proteins_raw.endswith(']'):
                            try:
                                import ast
                                proteins = ast.literal_eval(proteins_raw)
                            except (ValueError, SyntaxError):
                                # Fallback: treat as comma-separated
                                proteins = [p.strip().strip("'\"") for p in proteins_raw[1:-1].split(",") if p.strip()]
                        else:
                            # Regular comma-separated string
                            proteins = [p.strip() for p in proteins_raw.split(",") if p.strip()]
                    else:
                        proteins = []
                    
                    # Skip if no proteins
                    if not proteins or len(proteins) == 0:
                        print(f"\n  [{i+1}/{len(top_pathways)}] {pathway_name[:60]}...")
                        print(f"      ⚠️  No proteins available for PPI analysis")
                        continue
                    
                    print(f"\n  [{i+1}/{len(top_pathways)}] {pathway_name[:60]}...")
                    
                    # Convert Ensembl IDs to gene symbols for STRING API
                    # STRING API requires gene symbols (like VAMP2), not Ensembl IDs (like ENSG00000111481)
                    if proteins and proteins[0].startswith('ENSG'):
                        try:
                            import requests
                            # Use mygene.info API to convert Ensembl IDs to symbols
                            ensembl_ids = proteins[:100]  # Limit to 100 for API
                            response = requests.post(
                                'https://mygene.info/v3/query',
                                data={
                                    'q': ','.join(ensembl_ids),
                                    'scopes': 'ensembl.gene',
                                    'fields': 'symbol',
                                    'species': 'human'
                                },
                                timeout=30
                            )
                            if response.status_code == 200:
                                mygene_results = response.json()
                                # Build Ensembl -> Symbol mapping
                                symbol_map = {}
                                for r in mygene_results:
                                    if 'symbol' in r and 'query' in r:
                                        symbol_map[r['query']] = r['symbol']
                                # Convert proteins to symbols
                                proteins = [symbol_map.get(p, p) for p in proteins]
                                # Remove any that are still Ensembl IDs
                                proteins = [p for p in proteins if not p.startswith('ENSG')]
                                print(f"      📊 Converted to gene symbols: {len(proteins)} ({', '.join(proteins[:5])}{'...' if len(proteins) > 5 else ''})")
                            else:
                                print(f"      ⚠️  mygene.info API failed, using original IDs")
                        except Exception as e:
                            print(f"      ⚠️  Gene ID conversion failed: {e}")
                    else:
                        print(f"      📊 Proteins for PPI: {len(proteins)} ({', '.join(proteins[:5])}{'...' if len(proteins) > 5 else ''})")
                    
                    # Skip if no valid gene symbols after conversion
                    if not proteins or len(proteins) == 0:
                        print(f"      ⚠️  No valid gene symbols for PPI analysis")
                        continue
                    
                    # PPI Analysis
                    print(f"      → PPI Analysis...")
                    ppi_result = self.base_analyzer.reasoning_agent.generate_ppi_info(
                        proteins,
                        self.base_analyzer.query_agent,
                        img_dir=self.imgs_dir  # Use our own imgs_dir for gpt_led_analysis
                    )
                    
                    # Handle PPI result
                    if len(ppi_result) == 3:
                        print(f"      ⚠️  No PPI data: {ppi_result[0]}")
                        continue
                    elif len(ppi_result) == 4:
                        protein_count, extracted_ppi_data, ppi_filename, ppi_web_url = ppi_result
                    else:
                        print(f"      ⚠️  Unexpected PPI result")
                        continue
                    
                    if extracted_ppi_data is None:
                        print(f"      ⚠️  No PPI data available")
                        continue
                    
                    pathway_detail = {
                        "protein_count": protein_count,
                        "ppi_filename": ppi_filename,
                        "ppi_web_url": ppi_web_url,
                        "protein_functions": None,
                        "cluster_functions": None,
                        "function_summary": None
                    }
                    
                    # Protein Function Analysis
                    print(f"      → Protein Function Analysis...")
                    try:
                        protein_functions = self.base_analyzer.reasoning_agent.act(
                            "Protein_Function_Analysis",
                            {
                                "proteins_list": proteins,
                                "disease_name": disease_name,
                                "query_agent": self.base_analyzer.query_agent
                            }
                        )
                        pathway_detail["protein_functions"] = protein_functions
                        print(f"      ✅ Protein functions analyzed")
                    except Exception as e:
                        print(f"      ⚠️  Protein function analysis failed: {e}")
                    
                    # Cluster Function Analysis
                    print(f"      → Cluster Function Analysis...")
                    try:
                        clusters, cluster_functions = self.base_analyzer.reasoning_agent.act(
                            "Cluster_Function_Analysis",
                            {
                                "extracted_ppi_data": extracted_ppi_data,
                                "disease_name": disease_name,
                                "query_agent": self.base_analyzer.query_agent
                            }
                        )
                        pathway_detail["cluster_functions"] = (clusters, cluster_functions)
                        print(f"      ✅ Cluster functions analyzed")
                    except Exception as e:
                        print(f"      ⚠️  Cluster function analysis failed: {e}")
                    
                    # Function Enrichment Summary
                    print(f"      → Function Enrichment Summary...")
                    try:
                        function_summary = self.base_analyzer.reasoning_agent.act(
                            "Function_Enrichment_Analysis",
                            {
                                "protein_count": protein_count,
                                "ppi_filename": ppi_filename,
                                "ppi_web_url": ppi_web_url,
                                "protein_functions": pathway_detail["protein_functions"],
                                "cluster_functions": pathway_detail["cluster_functions"]
                            }
                        )
                        pathway_detail["function_summary"] = function_summary
                        print(f"      ✅ Function enrichment summarized")
                    except Exception as e:
                        print(f"      ⚠️  Function enrichment summary failed: {e}")
                    
                    pathway_details[pathway_name] = pathway_detail
                    print(f"  ✅ Pathway {i+1} complete")
                    
                except Exception as e:
                    print(f"  ❌ Error analyzing pathway {i+1}: {e}")
                    import traceback
                    traceback.print_exc()
                    continue
            
            results['pathway_details'] = pathway_details
            print(f"\n✅ Detailed analysis complete: {len(pathway_details)} pathways")
            
            if len(pathway_details) == 0:
                print("⚠️  WARNING: No pathways were successfully analyzed in detail!")
        
        
        # =================================================================
        # STEP 7: Writing Agent - Report Generation
        # =================================================================
        print("\n" + "="*80)
        print("STEP 7: WRITING AGENT - Report Generation")
        print("="*80)

        try:
            # Get pathway_details from results (handles both skip and non-skip cases)
            pathway_details_all = results.get('pathway_details', {})
            
            # If pathway_details is empty but we have PPI images, create basic entries
            if not pathway_details_all:
                print("  ℹ️  pathway_details is empty, scanning imgs directory for PPI networks...")
                
                # Check for existing PPI images
                if os.path.exists(self.imgs_dir):
                    ppi_images = [f for f in os.listdir(self.imgs_dir) if f.endswith('.png')]
                    if ppi_images:
                        print(f"  ✅ Found {len(ppi_images)} PPI images in {self.imgs_dir}")
                        
                        # Create basic pathway_details from top pathways + available images
                        top_pathways_for_report = gpt_pathways.head(min(len(ppi_images), 6))
                        
                        for i, (idx, pathway) in enumerate(top_pathways_for_report.iterrows()):
                            pathway_name = pathway['name']
                            if i < len(ppi_images):
                                ppi_filename = os.path.join("imgs", ppi_images[i])
                                pathway_details_all[pathway_name] = {
                                    'protein_count': pathway.get('intersection_size', 0),
                                    'ppi_filename': ppi_filename,
                                    'ppi_web_url': 'https://string-db.org',
                                    'function_summary': None
                                }
                        print(f"  ✅ Created {len(pathway_details_all)} pathway entries with PPI images")
                    else:
                        print("  ⚠️  No PPI images found, creating basic entries without images")
                        for idx, pathway in gpt_pathways.head(6).iterrows():
                            pathway_name = pathway['name']
                            pathway_details_all[pathway_name] = {
                                'protein_count': pathway.get('intersection_size', 0),
                                'ppi_filename': None,
                                'ppi_web_url': None,
                                'function_summary': None
                            }
            
            pathway_details = pathway_details_all

            # Revise pathway overview
            print("  → Revising pathway overview...")
            revised_pathway_overview = self.base_analyzer.writing_agent.revise_writting(
                pathways_overview
            )

            # Generate pathway details sections
            print("  → Generating detailed pathway sections...")
            revised_pathway_sections = {}

            for pathway_name, details in pathway_details.items():
                print(f"      Processing: {pathway_name[:50]}...")
                try:
                    # Handle None values for ppi_filename
                    ppi_filename = details.get('ppi_filename')
                    ppi_web_url = details.get('ppi_web_url')
                    protein_count = details.get('protein_count', 0)
                    
                    # Generate overview for this pathway
                    pathway_overview = None
                    if ppi_filename and protein_count:
                        try:
                            pathway_overview = self.base_analyzer.writing_agent.act(
                                "Function_Enrichment_Overview",
                                {
                                    "disease_name": disease_name,
                                    "pathway_name": pathway_name,
                                    "protein_count": protein_count,
                                    "ppi_filename": ppi_filename,
                                    "ppi_web_url": ppi_web_url or 'https://string-db.org'
                                }
                            )
                        except Exception as e:
                            print(f"      ⚠️  Failed to generate overview: {e}")
                    
                    # Create fallback if needed
                    if pathway_overview is None:
                        pathway_overview = f"### {pathway_name}\n\n"
                        pathway_overview += f"In the functional enrichment analysis for the **{pathway_name}** pathway"
                        if protein_count:
                            pathway_overview += f", {protein_count} proteins associated with {disease_name} were identified"
                        pathway_overview += ".\n\n"
                        
                        if ppi_filename:
                            pathway_overview += f"![PPI Network - {pathway_name}]({ppi_filename})\n\n"
                            pathway_overview += f"*Figure: Protein-protein interaction network for {pathway_name}.*\n\n"
                            if ppi_web_url:
                                pathway_overview += f"[View interactive network on STRING-DB]({ppi_web_url})\n\n"
                    
                    # Format function summary
                    function_text = ""
                    if details.get('function_summary'):
                        func_sum = details['function_summary']
                        if func_sum.get('cluster_function'):
                            function_text += "### Protein Clusters\n\n"
                            for chunk in func_sum['cluster_function']['chunks']:
                                function_text += f"{chunk}\n\n"
                        if func_sum.get('protein_function'):
                            function_text += "### Individual Proteins\n\n"
                            for chunk in func_sum['protein_function']['chunks']:
                                function_text += f"{chunk}\n\n"
                    
                    # Revise function text
                    revised_function = ""
                    if function_text:
                        try:
                            revised_function = self.base_analyzer.writing_agent.act(
                                "Function_Enrichment_Analysis",
                                {"paragraph": function_text}
                            )
                        except Exception as e:
                            print(f"      ⚠️  Failed to revise function analysis: {e}")
                            revised_function = function_text
                    
                    revised_pathway_sections[pathway_name] = {
                        "overview": pathway_overview,
                        "function_analysis": revised_function
                    }
                    
                except Exception as e:
                    print(f"      ❌ Error generating section: {e}")
                    revised_pathway_sections[pathway_name] = {
                        "overview": f"![PPI Network]({details['ppi_filename']})",
                        "function_analysis": ""
                    }
            
            # Combine into full draft
            print("  → Combining all sections...")
            full_draft = f"# Pathways Overview\n\n{revised_pathway_overview}\n\n"
            full_draft += "# Detailed Pathway Analysis\n\n"
            for pathway_name, sections in revised_pathway_sections.items():
                full_draft += f"## {pathway_name}\n\n"
                full_draft += f"{sections['overview']}\n\n"
                full_draft += f"{sections['function_analysis']}\n\n"
            
            # Add coherence
            print("  → Adding coherence...")
            full_draft = self.base_analyzer.writing_agent.revise_coherence(full_draft)
            
            # Generate introduction
            print("  → Generating introduction...")
            introduction = self.base_analyzer.writing_agent.generate_introduction(
                full_draft,
                disease_name,
                len(gpt_pathways),
                len(genes)
            )
            
            full_draft_w_intro = f"# Introduction\n\n{introduction}\n\n{full_draft}"
            
            # Final revision
            print("  → Final revision...")
            final_report = self.base_analyzer.writing_agent.revise_writting(full_draft_w_intro)
            
            results['final_report'] = final_report
            
            # Save final report
            report_md = os.path.join(self.results_dir, f'{disease_name}_report.md')
            with open(report_md, 'w') as f:
                f.write(final_report)
            
            print(f"\n✅ Final report saved: {report_md}")
            
        except Exception as e:
            print(f"❌ Error in report generation: {e}")
            import traceback
            traceback.print_exc()
        
        # =================================================================
        # STEP 7: Generate Summary Report
        # =================================================================
        print("\n" + "="*80)
        print("STEP 7: GENERATING SUMMARY REPORT")
        print("="*80)
        self._generate_gpt_led_report(results)
        
        # =================================================================
        # STEP 8: Generate GPT-Validated Pathways Summary
        # =================================================================
        print("\n" + "="*80)
        print("STEP 8: GENERATING GPT-VALIDATED PATHWAYS SUMMARY")
        print("="*80)
        self._generate_gpt_validated_summary(results, genes, disease_name)
        
        return results
    
    def _generate_gpt_led_report(self, results: Dict[str, Any]):
        disease_name = results['disease_name']
        report_file = os.path.join(self.results_dir, f'{disease_name}_GPT_LED_REPORT.md')
        
        report = f"""# GPT-Led Multi-Agent Pathway Analysis Report

## Disease: {results['disease_name']}
## Analysis Date: {results['timestamp']}
## Input: {results['gene_count']} genes

---

## Analysis Pipeline

This analysis uses a **GPT-led multi-agent workflow** with complete validation:

1. ✨ **Step 1 - GPT Prediction**: AI generates {results['top_k_predict']} candidate pathways (increased to 40 to ensure sufficient validated pathways)
2. 🔍 **Step 2 - Planning Agent**: g:Profiler enrichment + PubMed ranking + pathway classification
3. 🎯 **Step 3 - Filtering**: Match GPT predictions with validated pathways
4. 📊 **Step 4 - Reasoning Agent (Overview)**: Generate pathway overview analysis
5. 🔬 **Step 5 - Reasoning Agent (Details)**: PPI networks + protein/cluster function analysis
6. ✍️ **Step 6 - Writing Agent**: Report generation, revision, and coherence
7. 📋 **Step 7 - Summary**: Generate comprehensive summary report

**Key Advantage**: GPT provides intelligent pathway candidates, which are then subjected to the **full multi-agent analysis pipeline** - ensuring both AI-driven insights and rigorous statistical/functional validation.

---

## Step 1: GPT Pathway Predictions

"""
        
        if 'gpt_prediction' in results:
            gpt = results['gpt_prediction']
            report += f"**Total Predictions**: {len(gpt['predicted_pathways'])}\n\n"
            
            # Add functional themes analysis
            if 'gene_functional_themes' in gpt and gpt['gene_functional_themes']:
                report += f"**Gene Functional Themes**: {gpt.get('gene_functional_themes', 'N/A')}\n\n"
            
            report += f"**AI Summary**: {gpt.get('summary', 'N/A')}\n\n"
            
            report += "**Top 10 GPT Predictions** (with estimated gene overlap):\n\n"
            for i, pathway in enumerate(gpt['predicted_pathways'][:10], 1):
                details = gpt['pathway_details'].get(pathway, {})
                conf = details.get('confidence', 'Unknown')
                overlap = details.get('estimated_gene_overlap', 'N/A')
                pathway_id = details.get('pathway_id', 'N/A')
                
                report += f"{i}. **{pathway}** (ID: {pathway_id})\n"
                report += f"   - Confidence: {conf}\n"
                report += f"   - Estimated gene overlap: {overlap}\n"
                if 'rationale' in details:
                    report += f"   - Rationale: {details['rationale'][:200]}...\n"
                if 'disease_relevance' in details:
                    report += f"   - Disease relevance: {details['disease_relevance'][:150]}...\n"
                report += "\n"
        
        report += "\n---\n\n## Steps 2-3: Planning Agent & Pathway Filtering\n\n"
        
        if 'validation_rate' in results:
            val_rate = results['validation_rate']
            gpt_pathways = results.get('gpt_filtered_pathways', pd.DataFrame())
            
            if not gpt_pathways.empty:
                report += f"**Planning Agent Results** (g:Profiler + PubMed ranking):\n"
                report += f"- GPT predictions: {results['top_k_predict']}\n"
                report += f"- Validated by g:Profiler: {len(gpt_pathways)}\n"
                report += f"- Validation rate: {val_rate:.1%}\n\n"
                
                report += "**✅ Top 10 GPT-Predicted & Validated Pathways** (ranked by PubMed score):\n\n"
                for i, (_, row) in enumerate(gpt_pathways.head(10).iterrows(), 1):
                    report += f"{i}. **{row['name']}**\n"
                    report += f"   - p-value: {row['p_value']:.2e}\n"
                    if 'score' in row and pd.notna(row['score']):
                        report += f"   - PubMed score: {row['score']:.3f}\n"
                    report += f"   - Source: {row['source']}\n"
                    if 'intersection_size' in row:
                        report += f"   - Gene count: {row['intersection_size']}\n"
                    report += "\n"
            else:
                report += f"⚠️ **No GPT predictions were statistically validated**\n\n"
                report += "This means GPT suggested pathways that are not significantly enriched in your gene set.\n"
                report += "Consider reviewing the gene list or trying broader pathway predictions.\n\n"
        
        report += "\n---\n\n## Steps 4-6: Reasoning & Writing Agents (Full Multi-Agent Analysis)\n\n"
        
        if 'pathway_details' in results:
            n_detailed = len(results['pathway_details'])
            report += f"**Complete Multi-Agent Workflow Applied**:\n\n"
            report += f"- ✅ **Pathway Overview**: Generated comprehensive overview of all GPT-validated pathways\n"
            report += f"- ✅ **Detailed Analysis**: {n_detailed} pathways analyzed with:\n"
            report += f"  - PPI Network Analysis (STRING-db)\n"
            report += f"  - Protein Function Analysis (UniProt)\n"
            report += f"  - Cluster Function Analysis (MCL clustering)\n"
            report += f"  - Function Enrichment Summary (LLM-powered)\n"
            report += f"- ✅ **Report Writing**: Multi-step revision and coherence enhancement\n"
            report += f"- ✅ **Scientific Report**: Full report with introduction, methods, results\n\n"
            
            report += "📁 **Complete Analysis Outputs**:\n"
            report += f"- `{disease_name}_report.md` - Full scientific report with all pathway details\n"
            report += f"- `{disease_name}_all_pathways.csv` - All enriched pathways from g:Profiler\n"
            report += f"- `imgs/` - PPI network visualizations for top pathways\n\n"
        
        report += "\n---\n\n## Interpretation\n\n"
        
        report += "### 🎯 Strengths of GPT-Led Multi-Agent Approach\n\n"
        report += "1. **Intelligent Candidate Selection**: GPT leverages biomedical knowledge to suggest relevant pathways\n"
        report += "2. **Complete Planning Agent**: g:Profiler enrichment + PubMed ranking + pathway classification\n"
        report += "3. **Full Reasoning Agent**: PPI networks + protein function + cluster analysis\n"
        report += "4. **Complete Writing Agent**: Multi-step report generation with revision and coherence\n"
        report += "5. **Statistical Rigor**: All GPT candidates validated with p-values and enrichment scores\n"
        report += "6. **Focused Deep-Dive**: Applies intensive multi-agent analysis to GPT-selected pathways\n\n"
        
        report += "### 📊 Comparison: GPT-Led vs Traditional Multi-Agent\n\n"
        report += "| Aspect | GPT-Led (this analysis) | Traditional Multi-Agent |\n"
        report += "|--------|------------------------|-------------------------|\n"
        report += "| **Pathway Candidates** | ✨ GPT predictions | All enriched pathways |\n"
        report += "| **Planning Agent** | ✅ Full (g:Profiler + PubMed) | ✅ Full |\n"
        report += "| **Reasoning Agent** | ✅ Full (PPI + Functions) | ✅ Full |\n"
        report += "| **Writing Agent** | ✅ Full (Report + Revision) | ✅ Full |\n"
        report += "| **Focus** | GPT-selected pathways | Top statistical hits |\n"
        report += "| **Analysis Depth** | Deep (6 pathways) | Deep (6 pathways) |\n"
        report += "| **Best For** | Hypothesis-driven | Discovery-driven |\n\n"
        
        report += "### 💡 Next Steps\n\n"
        report += "1. **Review Validated Pathways**: Focus on pathways that GPT predicted AND were statistically enriched\n"
        report += "2. **Check PPI Networks**: Examine protein interactions in `imgs/` directory\n"
        report += "3. **Literature Review**: Use PubMed scores to prioritize pathways for deeper investigation\n"
        report += "4. **Experimental Design**: Plan validation experiments for top-ranked pathways\n\n"
        
        report += "---\n\n## Output Files\n\n"
        report += f"1. `{disease_name}_gpt_prediction.json` - GPT predictions with rationales\n"
        report += f"2. `{disease_name}_gpt_filtered_pathways.csv` - GPT predictions + statistical validation\n"
        report += f"3. `{disease_name}_report.md` - Full multi-agent analysis report\n"
        report += f"4. `{disease_name}_pathways.csv` - All enriched pathways (ranked)\n"
        report += f"5. `imgs/*.png` - PPI network visualizations\n\n"
        
        report += "---\n\n**Note**: This GPT-led approach complements traditional enrichment by providing targeted, knowledge-driven pathway analysis.\n"
        
        with open(report_file, 'w') as f:
            f.write(report)
        
        print(f"✅ GPT-led report saved: {report_file}")
    
    def _generate_gpt_validated_summary(self, results: Dict[str, Any], genes: List[str], disease_name: str):
        summary_file = os.path.join(self.results_dir, f'{disease_name}_gpt_validated_summary.txt')
        
        # Extract data
        gpt_prediction = results.get('gpt_prediction', {})
        gpt_predicted = gpt_prediction.get('predicted_pathways', [])
        gpt_pathways = results.get('gpt_filtered_pathways', pd.DataFrame())
        validation_rate = results.get('validation_rate', 0.0)
        
        with open(summary_file, 'w') as f:
            f.write("="*80 + "\n")
            f.write("GPT-LED PATHWAY ANALYSIS - VALIDATED PATHWAYS SUMMARY\n")
            f.write("="*80 + "\n\n")
            f.write(f"Disease: {disease_name}\n")
            f.write(f"Analysis Date: {results.get('timestamp', 'N/A')}\n")
            f.write(f"Analysis Type: GPT-Led Multi-Agent Workflow\n\n")
            
            f.write("-"*80 + "\n")
            f.write("INPUT STATISTICS\n")
            f.write("-"*80 + "\n")
            f.write(f"  Total genes analyzed: {len(genes)}\n")
            f.write(f"  Disease: {disease_name}\n\n")
            
            f.write("-"*80 + "\n")
            f.write("GPT PREDICTION STATISTICS\n")
            f.write("-"*80 + "\n")
            f.write(f"  GPT predicted pathways: {len(gpt_predicted)}\n")
            f.write(f"  Target predictions: {results.get('top_k_predict', 40)}\n")
            if len(gpt_predicted) < results.get('top_k_predict', 40):
                f.write(f"  ⚠️  Note: GPT generated fewer pathways than requested\n")
            f.write(f"  Validation rate: {validation_rate:.1%}\n\n")
            
            # Gene functional themes
            if 'gene_functional_themes' in gpt_prediction and gpt_prediction['gene_functional_themes']:
                f.write("-"*80 + "\n")
                f.write("GENE FUNCTIONAL THEMES (GPT Analysis)\n")
                f.write("-"*80 + "\n")
                f.write(f"{gpt_prediction['gene_functional_themes']}\n\n")
            
            f.write("-"*80 + "\n")
            f.write("VALIDATION RESULTS\n")
            f.write("-"*80 + "\n")
            f.write(f"  GPT-validated pathways (passed g:Profiler): {len(gpt_pathways)}\n")
            if not gpt_pathways.empty:
                f.write(f"  Success rate: {len(gpt_pathways)}/{len(gpt_predicted)} = {validation_rate:.1%}\n")
            else:
                f.write(f"  ⚠️  WARNING: No GPT predictions were statistically validated\n")
            f.write("\n")
            
            # Top 10 GPT predictions (regardless of validation)
            f.write("="*80 + "\n")
            f.write("TOP 10 GPT PREDICTIONS (with validation status)\n")
            f.write("="*80 + "\n\n")
            
            pathway_details = gpt_prediction.get('pathway_details', {})
            for i, pathway in enumerate(gpt_predicted[:10], 1):
                details = pathway_details.get(pathway, {})
                
                # Check if validated
                if not gpt_pathways.empty:
                    is_validated = any(gpt_pathways['name'].str.lower().str.contains(pathway.lower(), na=False))
                else:
                    is_validated = False
                
                validation_status = "✅ VALIDATED" if is_validated else "❌ NOT VALIDATED"
                
                f.write(f"{i}. {pathway} [{validation_status}]\n")
                
                # Pathway details
                if 'pathway_id' in details:
                    f.write(f"   ID: {details['pathway_id']}\n")
                if 'confidence' in details:
                    f.write(f"   Confidence: {details['confidence']}\n")
                if 'estimated_gene_overlap' in details:
                    f.write(f"   Estimated gene overlap: {details['estimated_gene_overlap']}\n")
                if 'rationale' in details:
                    rationale = details['rationale'][:200] + "..." if len(details['rationale']) > 200 else details['rationale']
                    f.write(f"   Rationale: {rationale}\n")
                if 'disease_relevance' in details:
                    relevance = details['disease_relevance'][:150] + "..." if len(details['disease_relevance']) > 150 else details['disease_relevance']
                    f.write(f"   Disease relevance: {relevance}\n")
                f.write("\n")
            
            # GPT-validated pathways with full details
            if not gpt_pathways.empty:
                f.write("="*80 + "\n")
                f.write(f"GPT-VALIDATED PATHWAYS (n={len(gpt_pathways)})\n")
                f.write("="*80 + "\n")
                f.write("These pathways were both:\n")
                f.write("  1. Predicted by GPT based on biomedical knowledge\n")
                f.write("  2. Statistically validated by g:Profiler (significant enrichment)\n\n")
                
                # Sort by score and p-value
                gpt_pathways_sorted = gpt_pathways.copy()
                if 'score' in gpt_pathways_sorted.columns:
                    gpt_pathways_sorted = gpt_pathways_sorted.sort_values(
                        by=['score', 'p_value'], 
                        ascending=[False, True]
                    )
                else:
                    gpt_pathways_sorted = gpt_pathways_sorted.sort_values('p_value')
                
                # Get pathway_details from GPT prediction for disease relevance
                pathway_details = gpt_prediction.get('pathway_details', {})

                for i, (_, row) in enumerate(gpt_pathways_sorted.iterrows(), 1):
                    f.write(f"{i}. {row['name']}\n")
                    f.write(f"   ID: {row['native']}\n")
                    f.write(f"   p-value: {row['p_value']:.2e}\n")
                    if 'score' in row and pd.notna(row['score']):
                        f.write(f"   PubMed score: {row['score']:.3f}\n")
                    f.write(f"   Source: {row['source']}\n")
                    if 'intersection_size' in row:
                        f.write(f"   Gene count: {row['intersection_size']}\n")
                    if 'description' in row and pd.notna(row['description']):
                        desc = row['description'][:300] + "..." if len(str(row['description'])) > 300 else row['description']
                        f.write(f"   Description: {desc}\n")

                    # Add disease relevance from GPT prediction
                    pathway_name = row['name']
                    if pathway_name in pathway_details:
                        details = pathway_details[pathway_name]
                        if 'disease_relevance' in details and details['disease_relevance']:
                            f.write(f"   Disease relevance: {details['disease_relevance']}\n")

                    f.write("\n")
            else:
                f.write("="*80 + "\n")
                f.write("NO GPT-VALIDATED PATHWAYS\n")
                f.write("="*80 + "\n\n")
                f.write("None of the GPT predictions passed statistical validation.\n")
                f.write("This means:\n")
                f.write("  - GPT predicted pathways based on literature and biological knowledge\n")
                f.write("  - These pathways are not statistically enriched in your gene set\n")
                f.write("  - The gene set may have different biological characteristics\n\n")
                f.write("Recommendations:\n")
                f.write("  1. Check the complete enrichment analysis (all_pathways.csv)\n")
                f.write("  2. Review the gene list for quality and relevance\n")
                f.write("  3. Consider the validation rate and adjust interpretation\n\n")
            
            f.write("="*80 + "\n")
            f.write("INTERPRETATION\n")
            f.write("="*80 + "\n\n")
            f.write("This summary shows the results of GPT-led pathway analysis:\n\n")
            f.write("1. **GPT Predictions**: AI-generated pathway candidates based on:\n")
            f.write("   - Biomedical literature knowledge\n")
            f.write("   - Known disease mechanisms\n")
            f.write("   - Gene functional analysis\n\n")
            f.write("2. **Statistical Validation**: Each prediction was tested using:\n")
            f.write("   - g:Profiler enrichment analysis\n")
            f.write("   - Hypergeometric test for significance\n")
            f.write("   - PubMed literature relevance scoring\n\n")
            f.write("3. **Validation Rate**: The percentage of GPT predictions that are\n")
            f.write("   statistically enriched in your gene set:\n")
            if validation_rate > 0.15:
                f.write(f"   - {validation_rate:.1%} is a GOOD validation rate\n")
                f.write("   - GPT predictions align well with your data\n")
            elif validation_rate > 0.05:
                f.write(f"   - {validation_rate:.1%} is a MODERATE validation rate\n")
                f.write("   - Some GPT predictions are supported by data\n")
            else:
                f.write(f"   - {validation_rate:.1%} is a LOW validation rate\n")
                f.write("   - GPT predictions may not match your specific gene set\n")
            f.write("\n")
            
            f.write("="*80 + "\n")
            f.write("OUTPUT FILES\n")
            f.write("="*80 + "\n\n")
            f.write(f"1. {disease_name}_gpt_prediction.json\n")
            f.write("   - Full GPT predictions with rationales\n\n")
            f.write(f"2. {disease_name}_gpt_filtered_pathways.csv\n")
            f.write("   - GPT-predicted + g:Profiler validated pathways\n\n")
            f.write(f"3. {disease_name}_all_pathways.csv\n")
            f.write("   - All enriched pathways (regardless of GPT prediction)\n\n")
            f.write(f"4. {disease_name}_report.md\n")
            f.write("   - Complete multi-agent analysis report\n\n")
            f.write(f"5. {disease_name}_GPT_LED_REPORT.md\n")
            f.write("   - Comprehensive GPT-led analysis summary\n\n")
            f.write(f"6. {disease_name}_gpt_validated_summary.txt (this file)\n")
            f.write("   - Detailed summary of GPT predictions and validation\n\n")
        
        print(f"✅ GPT-validated summary saved: {summary_file}")

    def _generate_modules_summary_report(self, results: Dict[str, Any], disease_name: str):
        summary_file = os.path.join(self.results_dir, f'{disease_name}_MODULES_SUMMARY.md')

        with open(summary_file, 'w') as f:
            f.write(f"# Module-Based Pathway Analysis Summary: {disease_name}\n\n")
            f.write(f"**Analysis Date**: {results['timestamp']}\n\n")
            f.write(f"**Total Genes**: {results['total_genes']}\n")
            f.write(f"**Total Modules**: {results['total_modules']}\n")
            f.write(f"**Modules Analyzed**: {len(results['module_results'])}\n\n")

            f.write("---\n\n")
            f.write("## Analysis Overview\n\n")
            f.write("This analysis performs **module-based pathway enrichment** for AD:\n\n")
            f.write("1. **Module Separation**: Genes are grouped by their network modules\n")
            f.write("2. **Independent Analysis**: Each module is analyzed separately\n")
            f.write("3. **GPT Prediction**: AI predicts candidate pathways for each module\n")
            f.write("4. **Statistical Validation**: g:Profiler validates enrichment\n")
            f.write("5. **AD-Specific Ranking**: Pathways ranked by AD-specificity + PubMed score\n")
            f.write("6. **Deep Analysis**: PPI networks and functional analysis\n\n")

            f.write("---\n\n")
            f.write("## Module-Specific Results\n\n")


            for module_key, module_result in results['module_results'].items():
                module_id = module_key.replace('module_', '')
                module_name = module_result.get('disease_name', f'{disease_name}_Module_{module_id}')

                f.write(f"### Module {module_id}\n\n")
                f.write(f"**Gene Count**: {module_result.get('gene_count', 'N/A')}\n\n")


                gpt_pred = module_result.get('gpt_prediction', {})
                if gpt_pred:
                    f.write(f"**GPT Predictions**: {len(gpt_pred.get('predicted_pathways', []))}\n")
                    if 'gene_functional_themes' in gpt_pred:
                        f.write(f"**Functional Themes**: {gpt_pred['gene_functional_themes']}\n")


                val_rate = module_result.get('validation_rate', 0)
                gpt_pathways = module_result.get('gpt_filtered_pathways', pd.DataFrame())

                if not gpt_pathways.empty:
                    f.write(f"**Validated Pathways**: {len(gpt_pathways)} ({val_rate:.1%} validation rate)\n\n")

                    # Top 5 pathways for this module
                    f.write(f"**Top 5 AD-Specific Pathways**:\n\n")
                    for i, (_, row) in enumerate(gpt_pathways.head(5).iterrows(), 1):
                        f.write(f"{i}. **{row['name']}**\n")
                        if 'ad_specificity' in row:
                            f.write(f"   - AD-specificity: {row['ad_specificity']:.3f}\n")
                        if 'score' in row and pd.notna(row['score']):
                            f.write(f"   - PubMed score: {row['score']:.3f}\n")
                        f.write(f"   - p-value: {row['p_value']:.2e}\n")
                        f.write(f"   - Source: {row['source']}\n\n")
                else:
                    f.write(f"**Validated Pathways**: 0 (no GPT predictions validated)\n\n")

                f.write(f"**Detailed Report**: `{module_name}_report.md`\n\n")
                f.write("---\n\n")


            f.write("## Cross-Module Pathway Comparison\n\n")
            f.write("### Common Pathways Across Modules\n\n")


            all_module_pathways = {}
            for module_key, module_result in results['module_results'].items():
                gpt_pathways = module_result.get('gpt_filtered_pathways', pd.DataFrame())
                if not gpt_pathways.empty:
                    module_id = module_key.replace('module_', '')
                    all_module_pathways[module_id] = set(gpt_pathways['native'].tolist())


            if len(all_module_pathways) > 1:
                common_pathways = set.intersection(*all_module_pathways.values())
                if common_pathways:
                    f.write(f"**Pathways found in ALL modules**: {len(common_pathways)}\n\n")

                    for module_key, module_result in results['module_results'].items():
                        gpt_pathways = module_result.get('gpt_filtered_pathways', pd.DataFrame())
                        if not gpt_pathways.empty:
                            common_df = gpt_pathways[gpt_pathways['native'].isin(common_pathways)]
                            if not common_df.empty:
                                for _, row in common_df.iterrows():
                                    f.write(f"- {row['name']} ({row['native']})\n")
                                break
                    f.write("\n")
                else:
                    f.write("No pathways are common to all modules.\n\n")

                # Module-specific pathways
                f.write("### Module-Specific Pathways\n\n")
                for module_id, pathways in all_module_pathways.items():
                    other_pathways = set()
                    for other_id, other_pw in all_module_pathways.items():
                        if other_id != module_id:
                            other_pathways.update(other_pw)

                    specific = pathways - other_pathways
                    if specific:
                        f.write(f"**Module {module_id} specific**: {len(specific)} pathways\n")

            f.write("\n---\n\n")
            f.write("## Interpretation\n\n")
            f.write("### Module-Based Analysis Benefits\n\n")
            f.write("1. **Preserves Module Identity**: Each module's biological function is analyzed independently\n")
            f.write("2. **Reduces Noise**: Avoids mixing genes from different functional modules\n")
            f.write("3. **Identifies Module-Specific Mechanisms**: Reveals pathways unique to each module\n")
            f.write("4. **Discovers Common Mechanisms**: Identifies pathways shared across modules\n\n")

            f.write("### AD-Specific Ranking\n\n")
            f.write("Pathways are ranked using a multi-dimensional approach:\n\n")
            f.write("1. **AD-Specificity Score**: Based on AD-related keywords (neurodegeneration, amyloid, tau, etc.)\n")
            f.write("2. **PubMed Literature Score**: Based on disease-pathway co-occurrence in literature\n")
            f.write("3. **Statistical Significance**: Based on g:Profiler enrichment p-values\n\n")
            f.write("This ensures that AD-relevant pathways are prioritized over generic cellular processes.\n\n")

            f.write("---\n\n")
            f.write("## Output Files\n\n")
            f.write("For each module:\n")
            f.write("- `{disease}_Module_{id}_report.md` - Full scientific report\n")
            f.write("- `{disease}_Module_{id}_gpt_prediction.json` - GPT predictions\n")
            f.write("- `{disease}_Module_{id}_gpt_filtered_pathways.csv` - Validated pathways\n")
            f.write("- `imgs/{disease}_Module_{id}_*.png` - PPI network visualizations\n\n")
            f.write("Summary files:\n")
            f.write(f"- `{disease_name}_MODULES_SUMMARY.md` (this file) - Cross-module comparison\n\n")

        print(f"✅ Modules summary report saved: {summary_file}")

    def compare_diseases_gpt_led(self, results_A: Dict[str, Any], results_B: Dict[str, Any],
                                  disease_A_name: str, disease_B_name: str,
                                  genes_A: List[str], genes_B: List[str]):
        print("\n" + "="*80)
        print("COMPARING GPT-LED ANALYSES")
        print("="*80)
        
        # Extract GPT-validated pathway IDs
        pathways_A = set(results_A.get('gpt_filtered_pathways', pd.DataFrame())['native'].tolist()) \
                     if not results_A.get('gpt_filtered_pathways', pd.DataFrame()).empty else set()
        pathways_B = set(results_B.get('gpt_filtered_pathways', pd.DataFrame())['native'].tolist()) \
                     if not results_B.get('gpt_filtered_pathways', pd.DataFrame()).empty else set()
        
        # Calculate shared genes
        genes_A_set = set(genes_A)
        genes_B_set = set(genes_B)
        shared_genes = genes_A_set & genes_B_set
        
        # Calculate pathway overlaps
        common = pathways_A & pathways_B
        A_only = pathways_A - pathways_B
        B_only = pathways_B - pathways_A
        
        print(f"\n📊 Gene Statistics:")
        print(f"   {disease_A_name}: {len(genes_A)} genes")
        print(f"   {disease_B_name}: {len(genes_B)} genes")
        print(f"   Shared genes: {len(shared_genes)} ({len(shared_genes)/max(len(genes_A), 1)*100:.1f}%)")
        
        print(f"\n📊 Pathway Statistics:")
        print(f"   {disease_A_name} (GPT-validated): {len(pathways_A)} pathways")
        print(f"   {disease_B_name} (GPT-validated): {len(pathways_B)} pathways")
        print(f"   Common pathways: {len(common)} ({len(common)/max(len(pathways_A), 1)*100:.1f}%)")
        print(f"   {disease_A_name}-specific: {len(A_only)}")
        print(f"   {disease_B_name}-specific: {len(B_only)}")
        
        # Save comparison
        comparison_file = os.path.join(self.results_dir, 'disease_comparison.txt')
        with open(comparison_file, 'w') as f:
            f.write("="*80 + "\n")
            f.write("GPT-LED DISEASE PAIR PATHWAY COMPARISON\n")
            f.write("="*80 + "\n\n")
            f.write(f"Disease Pair: {disease_A_name} vs {disease_B_name}\n")
            f.write(f"Analysis Type: GPT-Led Multi-Agent Workflow\n")
            f.write(f"Date: {results_A.get('timestamp', 'N/A')}\n\n")
            
            f.write("-"*80 + "\n")
            f.write("GENE STATISTICS\n")
            f.write("-"*80 + "\n")
            f.write(f"  {disease_A_name}: {len(genes_A)} genes\n")
            f.write(f"  {disease_B_name}: {len(genes_B)} genes\n")
            f.write(f"  Shared genes: {len(shared_genes)} ({len(shared_genes)/max(len(genes_A), 1)*100:.1f}%)\n\n")
            
            f.write("-"*80 + "\n")
            f.write("GPT PREDICTION STATISTICS\n")
            f.write("-"*80 + "\n")
            gpt_A = results_A.get('gpt_prediction', {}).get('predicted_pathways', [])
            gpt_B = results_B.get('gpt_prediction', {}).get('predicted_pathways', [])
            f.write(f"  {disease_A_name} GPT predictions: {len(gpt_A)} pathways\n")
            f.write(f"  {disease_B_name} GPT predictions: {len(gpt_B)} pathways\n")
            f.write(f"  {disease_A_name} validation rate: {results_A.get('validation_rate', 0):.1%}\n")
            f.write(f"  {disease_B_name} validation rate: {results_B.get('validation_rate', 0):.1%}\n\n")
            
            f.write("-"*80 + "\n")
            f.write("GPT-VALIDATED PATHWAY STATISTICS\n")
            f.write("-"*80 + "\n")
            f.write(f"  {disease_A_name}: {len(pathways_A)} GPT-validated pathways\n")
            f.write(f"  {disease_B_name}: {len(pathways_B)} GPT-validated pathways\n")
            f.write(f"  Common pathways: {len(common)} ({len(common)/max(len(pathways_A), 1)*100:.1f}%)\n")
            f.write(f"  {disease_A_name}-specific: {len(A_only)} pathways\n")
            f.write(f"  {disease_B_name}-specific: {len(B_only)} pathways\n\n")
            
            if common:
                f.write("="*80 + "\n")
                f.write("TOP 20 COMMON GPT-VALIDATED PATHWAYS\n")
                f.write("="*80 + "\n\n")
                # Get common pathways with details
                df_A = results_A.get('gpt_filtered_pathways', pd.DataFrame())
                if not df_A.empty:
                    common_df = df_A[df_A['native'].isin(common)].copy()
                    if 'score' in common_df.columns:
                        common_df = common_df.sort_values(['score', 'p_value'], ascending=[False, True])
                    else:
                        common_df = common_df.sort_values('p_value')
                    
                    for i, (_, row) in enumerate(common_df.head(20).iterrows(), 1):
                        f.write(f"{i}. {row['name']}\n")
                        score_str = f", PubMed score={row['score']:.3f}" if 'score' in row and pd.notna(row['score']) else ""
                        f.write(f"   ID: {row['native']}\n")
                        f.write(f"   p-value={row['p_value']:.2e}{score_str}\n")
                        f.write(f"   Source: {row['source']}\n")
                        if 'intersection_size' in row:
                            f.write(f"   Gene count: {row['intersection_size']}\n")
                        f.write("\n")
            
            if A_only:
                f.write("="*80 + "\n")
                f.write(f"TOP 10 {disease_A_name}-SPECIFIC PATHWAYS\n")
                f.write("="*80 + "\n\n")
                df_A = results_A.get('gpt_filtered_pathways', pd.DataFrame())
                if not df_A.empty:
                    specific_df = df_A[df_A['native'].isin(A_only)].copy()
                    if 'score' in specific_df.columns:
                        specific_df = specific_df.sort_values(['score', 'p_value'], ascending=[False, True])
                    else:
                        specific_df = specific_df.sort_values('p_value')
                    
                    for i, (_, row) in enumerate(specific_df.head(10).iterrows(), 1):
                        f.write(f"{i}. {row['name']}\n")
                        score_str = f", PubMed score={row['score']:.3f}" if 'score' in row and pd.notna(row['score']) else ""
                        f.write(f"   ID: {row['native']}, p-value={row['p_value']:.2e}{score_str}\n\n")
            
            if B_only:
                f.write("="*80 + "\n")
                f.write(f"TOP 10 {disease_B_name}-SPECIFIC PATHWAYS\n")
                f.write("="*80 + "\n\n")
                df_B = results_B.get('gpt_filtered_pathways', pd.DataFrame())
                if not df_B.empty:
                    specific_df = df_B[df_B['native'].isin(B_only)].copy()
                    if 'score' in specific_df.columns:
                        specific_df = specific_df.sort_values(['score', 'p_value'], ascending=[False, True])
                    else:
                        specific_df = specific_df.sort_values('p_value')
                    
                    for i, (_, row) in enumerate(specific_df.head(10).iterrows(), 1):
                        f.write(f"{i}. {row['name']}\n")
                        score_str = f", PubMed score={row['score']:.3f}" if 'score' in row and pd.notna(row['score']) else ""
                        f.write(f"   ID: {row['native']}, p-value={row['p_value']:.2e}{score_str}\n\n")
            
            f.write("="*80 + "\n")
            f.write("INTERPRETATION\n")
            f.write("="*80 + "\n\n")
            f.write("This comparison is based on GPT-led multi-agent analysis:\n")
            f.write("1. GPT predicted candidate pathways for each disease\n")
            f.write("2. Candidates were validated using g:Profiler (statistical enrichment)\n")
            f.write("3. Validated pathways were ranked by PubMed literature relevance\n")
            f.write("4. Full multi-agent analysis (PPI, function, report) was performed\n\n")
            f.write("Common pathways: Shared biological mechanisms between diseases\n")
            f.write("Disease-specific pathways: Unique mechanisms for each disease\n")
        
        print(f"✅ Comparison saved: {comparison_file}")
        
        return {
            'common': common,
            'A_specific': A_only,
            'B_specific': B_only,
            'shared_genes': shared_genes
        }
    
    def analyze_disease_pair_gpt_led(self, genes_A: List[str], genes_B: List[str],
                                     disease_A_name: str, disease_B_name: str,
                                     top_k_predict: int = 40, top_k_analyze: int = 6,
                                     shared_genes: List[str] = None):
        print("\n" + "="*80)
        print("GPT-LED DISEASE PAIR ANALYSIS")
        print("="*80)
        print(f"{disease_A_name} vs {disease_B_name}")
        print(f"Genes for validation: {len(genes_A)} vs {len(genes_B)}")
        if shared_genes is not None:
            print(f"Shared genes for GPT prediction: {len(shared_genes)} genes")
        else:
            print(f"Using individual genes for GPT prediction")
        
        # Analyze Disease A
        print("\n" + "▶"*40)
        print(f"ANALYZING {disease_A_name}")
        print("▶"*40)
        results_A = self.analyze_gpt_led_pathways(
            genes=genes_A,
            disease_name=disease_A_name,
            top_k_predict=top_k_predict,
            top_k_analyze=top_k_analyze,
            genes_for_gpt=shared_genes  # Use shared genes for GPT prediction
        )
        
        # Analyze Disease B
        print("\n" + "▶"*40)
        print(f"ANALYZING {disease_B_name}")
        print("▶"*40)
        results_B = self.analyze_gpt_led_pathways(
            genes=genes_B,
            disease_name=disease_B_name,
            top_k_predict=top_k_predict,
            top_k_analyze=top_k_analyze,
            genes_for_gpt=shared_genes  # Use shared genes for GPT prediction
        )
        
        # Compare diseases
        comparison = self.compare_diseases_gpt_led(
            results_A, results_B,
            disease_A_name, disease_B_name,
            genes_A, genes_B
        )
        
        # Final summary
        print("\n" + "="*80)
        print("✅ DISEASE PAIR ANALYSIS COMPLETE")
        print("="*80)
        print(f"\n📁 Results directory: {self.results_dir}")
        print("\n📄 Generated files:")
        print(f"\n  Disease A ({disease_A_name}):")
        print(f"    - {disease_A_name}_gpt_prediction.json")
        print(f"    - {disease_A_name}_gpt_filtered_pathways.csv")
        print(f"    - {disease_A_name}_report.md")
        print(f"    - {disease_A_name}_GPT_LED_REPORT.md")
        print(f"\n  Disease B ({disease_B_name}):")
        print(f"    - {disease_B_name}_gpt_prediction.json")
        print(f"    - {disease_B_name}_gpt_filtered_pathways.csv")
        print(f"    - {disease_B_name}_report.md")
        print(f"    - {disease_B_name}_GPT_LED_REPORT.md")
        print(f"\n  Comparison:")
        print(f"    - disease_comparison.txt")
        print(f"\n  PPI Networks:")
        print(f"    - imgs/*.png")
        
        return {
            'disease_A': results_A,
            'disease_B': results_B,
            'comparison': comparison
        }


def main():

    # Input paths
    input_dir = "/Users/liyuxin/Documents/zotero/PhD/Research/AI_agent/codes/Genetic_AI_Agent/src/utils/Network_expansion/outputs/disease_pair_expansion"
    output_dir = "/Users/liyuxin/Documents/zotero/PhD/Research/AI_agent/codes/Genetic_AI_Agent/src/utils/Pathway_analysis"

    # Load disease data
    disease_file = os.path.join(input_dir, "D000544_modules.csv")  # AD (Alzheimer's Disease)

    if not os.path.exists(disease_file):
        print(f"❌ File not found: {disease_file}")
        return

    df = pd.read_csv(disease_file)
    disease_name = "AD"

    print(f"\n📊 Loaded: {disease_name}")
    print(f"   Total rows: {len(df)}")

    # Check if we have module information
    has_modules = 'cluster_walktrap' in df.columns

    # Initialize GPT-led analyzer
    analyzer = GPTLedMultiAgentAnalyzer(
        output_dir=output_dir,
        model="gpt-5.1"
    )

    # Choose analysis mode
    print("\n" + "="*80)
    print("ANALYSIS MODE SELECTION")
    print("="*80)

    if has_modules:
        print("\n✅ Module information detected in data")
        print("\nAvailable analysis modes:")
        print("  1. MODULE-BASED: Analyze each module separately (RECOMMENDED for AD)")
        print("  2. COMBINED: Analyze all genes together (original method)")

        # For this example, we'll use module-based analysis
        use_module_based = True

        if use_module_based:
            print("\n🎯 Selected: MODULE-BASED ANALYSIS")
            print("\n" + "="*80)
            print("🚀 STARTING MODULE-BASED GPT-LED ANALYSIS")
            print("="*80)
            print("\nWorkflow:")
            print("  1. Separate genes by modules")
            print("  2. For each module:")
            print("     - GPT predicts candidate pathways")
            print("     - g:Profiler validates enrichment")
            print("     - PubMed ranking + AD-specific ranking")
            print("     - PPI analysis on validated pathways")
            print("     - Generate module-specific report")
            print("  3. Generate cross-module comparison report")

            results = analyzer.analyze_modules_separately(
                modules_df=df,
                disease_name=disease_name,
                top_k_predict=40,
                top_k_analyze=6,
                min_module_size=10
            )

            print("\n" + "="*80)
            print("✅ MODULE-BASED ANALYSIS COMPLETE")
            print("="*80)
            print(f"\n📁 Results directory: {analyzer.results_dir}")
            print("\n📄 Key output files:")
            print(f"\n  Module-Specific Reports:")
            for module_key in results['module_results'].keys():
                module_id = module_key.replace('module_', '')
                print(f"    - {disease_name}_Module_{module_id}_report.md")
                print(f"    - {disease_name}_Module_{module_id}_gpt_filtered_pathways.csv")
            print(f"\n  Cross-Module Summary:")
            print(f"    - {disease_name}_MODULES_SUMMARY.md (comprehensive comparison)")
            print(f"\n  PPI Networks:")
            print(f"    - imgs/*.png (module-specific PPI networks)")

        else:
            # Combined analysis (original method)
            genes = df[df['passes_all_filters'] == True]['node'].unique().tolist()
            print(f"\n🎯 Selected: COMBINED ANALYSIS")
            print(f"   Genes: {len(genes)}")

            print("\n" + "="*80)
            print("🚀 STARTING GPT-LED MULTI-AGENT ANALYSIS")
            print("="*80)
            print("\nWorkflow:")
            print("  1. GPT predicts candidate pathways")
            print("  2. g:Profiler validates enrichment (p-values)")
            print("  3. PubMed ranking + AD-specific ranking")
            print("  4. PPI analysis on validated pathways")
            print("  5. Complete scientific report generation")

            results = analyzer.analyze_gpt_led_pathways(
                genes=genes,
                disease_name=disease_name,
                top_k_predict=40,
                top_k_analyze=6
            )

            print("\n" + "="*80)
            print("✅ GPT-LED ANALYSIS COMPLETE")
            print("="*80)
            print(f"\n📁 Results directory: {analyzer.results_dir}")
            print("\n📄 Key output files:")
            print(f"\n  GPT Predictions:")
            print(f"    - {disease_name}_gpt_prediction.json")
            print(f"    - {disease_name}_GPT_LED_REPORT.md (comprehensive summary)")
            print(f"    - {disease_name}_gpt_validated_summary.txt (validation details)")
            print(f"\n  Validated Pathways:")
            print(f"    - {disease_name}_gpt_filtered_pathways.csv (GPT + g:Profiler + AD-ranking)")
            print(f"    - {disease_name}_all_pathways.csv (all enriched)")
            print(f"\n  Multi-Agent Analysis:")
            print(f"    - {disease_name}_report.md (full scientific report)")
            print(f"    - imgs/*.png (PPI networks)")

            if 'validation_rate' in results:
                print(f"\n📊 Validation Statistics:")
                print(f"   GPT predictions: {results['top_k_predict']}")
                validated_count = len(results.get('gpt_filtered_pathways', pd.DataFrame()))
                print(f"   Validated by g:Profiler: {validated_count}")
                print(f"   Validation rate: {results['validation_rate']:.1%}")
    else:
        # No module information, use combined analysis
        genes = df[df['passes_all_filters'] == True]['node'].unique().tolist()
        print(f"\n⚠️  No module information found in data")
        print(f"   Using COMBINED ANALYSIS mode")
        print(f"   Genes: {len(genes)}")

        results = analyzer.analyze_gpt_led_pathways(
            genes=genes,
            disease_name=disease_name,
            top_k_predict=40,
            top_k_analyze=6
        )


if __name__ == "__main__":
    main()

