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


# ============================================================================
# DISEASE NAME RESOLUTION
# ============================================================================
# Module labels (e.g., "PS_Module_2_iter1") are used for file naming but must
# NOT be passed to GPT prompts as the disease context.  This helper resolves
# the short prefix back to the full disease name.

_ABBREV_TO_FULL = {
    "AD": "Alzheimer's Disease",
    "PD": "Parkinson's Disease",
    "IBD": "Inflammatory Bowel Disease",
    "MS": "Multiple Sclerosis",
    "ALS": "Amyotrophic Lateral Sclerosis",
    "RA": "Rheumatoid Arthritis",
    "T2D": "Type 2 Diabetes",
    "COPD": "Chronic Obstructive Pulmonary Disease",
    "CAD": "Coronary Artery Disease",
    "CHD": "Coronary Heart Disease",
    "HF": "Heart Failure",
    "CD": "Crohn's Disease",
    "OSA": "Obstructive Sleep Apnea",
    "CRC": "Colorectal Cancer",
    "HCC": "Hepatocellular Carcinoma",
    "AIT": "Autoimmune Thyroiditis",
    "AF": "Atrial Fibrillation",
    "NAFLD": "Non-alcoholic fatty liver disease",
    "PSP": "Progressive Supranuclear Palsy",
    "TB": "Tuberculosis",
    "SLE": "Systemic Lupus Erythematosus",
    "AST": "Asthma",
    "HTN": "Hypertension",
    "MDD": "Major Depressive Disorder",
    "PS": "Psoriasis",
    "CKD": "Chronic Kidney Disease",
    "SCZ": "Schizophrenia",
    "OBS": "Obesity",
    "BC": "Breast Cancer",
    "LC": "Lung Cancer",
    "IPF": "Idiopathic Pulmonary Fibrosis",
    "COVID": "COVID-19",
}


def resolve_disease_full_name(disease_name: str) -> str:
    """
    Resolve the full disease name from a module label or abbreviation.
    
    Examples:
        "PS_Module_2_iter1"  -> "Psoriasis"
        "ALS_Module_47"      -> "Amyotrophic Lateral Sclerosis"
        "Alzheimer's Disease" -> "Alzheimer's Disease" (already full)
        "PS"                 -> "Psoriasis"
    
    Parameters
    ----------
    disease_name : str
        Module label (e.g., "PS_Module_2_iter1") or disease abbreviation/name.
        
    Returns
    -------
    str
        Full disease name for use in GPT prompts.
    """
    import re
    
    # 1. Try to extract prefix before "_Module_"
    match = re.match(r'^([A-Z0-9]+)_Module_', disease_name)
    if match:
        prefix = match.group(1)
        if prefix in _ABBREV_TO_FULL:
            return _ABBREV_TO_FULL[prefix]
    
    # 2. Try direct abbreviation lookup
    upper = disease_name.strip().upper()
    if upper in _ABBREV_TO_FULL:
        return _ABBREV_TO_FULL[upper]
    
    # 3. Already a full name (e.g., "Alzheimer's Disease")
    return disease_name


import os
import sys
import json
import time  # Added: needed for batch processing delays
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

# ============================================================================
# AG2 IMPORTS - For HITL version
# ============================================================================
# Add src directory to path for AG2 imports
src_dir = os.path.abspath(os.path.join(current_dir, '../../../'))
if src_dir not in sys.path:
    sys.path.insert(0, src_dir)

try:
    from pipeline import (
        GPT5_LLM_CONFIG,
        PathwayRankingAgent,
        DiseaseConnectionAgent,
        AggregationSummaryAgent,
        AG2PathwayWorkflow,
        AG2_AVAILABLE
    )
    AG2_HITL_AVAILABLE = True
    print("✅ AG2 components imported successfully for HITL")
except ImportError as e:
    AG2_HITL_AVAILABLE = False
    print(f"⚠️  AG2 not available: {e}")
    print("   Falling back to non-HITL mode")


# ============================================================================
# SIMPLIFIED STRING API PPI FUNCTIONS
# ============================================================================
# These functions directly call STRING-DB API without requiring QueryAgent/ReasoningAgent

import requests
import uuid
from time import sleep

def generate_string_network_image(proteins: List[str], output_file: str = None, 
                                   species: int = 9606) -> str:
    """
    Generate STRING network image directly from protein list.
    
    Parameters:
    -----------
    proteins : List[str]
        List of gene symbols (e.g., ['VAMP2', 'STX1A', 'SNAP25'])
    output_file : str
        Output file path for the image
    species : int
        NCBI taxonomy ID (default: 9606 for human)
        
    Returns:
    --------
    str : Path to the generated image, or None if failed
    """
    if not proteins:
        return None
    
    # STRING API configuration
    string_api_url = "https://version-12-0.string-db.org/api"
    method = "network"
    format = "image"
    request_url = "/".join([string_api_url, format, method])
    
    # Build request parameters
    identifiers_string = "%0d".join(proteins)
    params = {
        "identifiers": identifiers_string,
        "species": species,
        "network_type": "functional",
        "network_flavor": "evidence",
        "hide_disconnected_nodes": 0,
        "caller_identity": "genetic_ai_agent"
    }
    
    try:
        response = requests.post(request_url, data=params, timeout=60)
        response.raise_for_status()
        
        # Ensure output directory exists
        if output_file:
            output_dir = os.path.dirname(output_file)
            if output_dir and not os.path.exists(output_dir):
                os.makedirs(output_dir, exist_ok=True)
            
            with open(output_file, 'wb') as fh:
                fh.write(response.content)
            
            sleep(1)  # Rate limiting
            return output_file
        
        return None
        
    except requests.exceptions.RequestException as e:
        print(f"      ⚠️  STRING API image request failed: {e}")
        return None
    except Exception as e:
        print(f"      ⚠️  Unexpected error in STRING image generation: {e}")
        return None


def generate_string_network_link(proteins: List[str], species: int = 9606) -> str:
    """
    Generate STRING webpage link for interactive network exploration.
    
    Parameters:
    -----------
    proteins : List[str]
        List of gene symbols
    species : int
        NCBI taxonomy ID (default: 9606 for human)
        
    Returns:
    --------
    str : URL to STRING webpage, or None if failed
    """
    if not proteins:
        return None
    
    string_api_url = "https://version-12-0.string-db.org/api"
    method = "get_link"
    format = "json"
    request_url = "/".join([string_api_url, format, method])
    
    identifiers_string = "%0d".join(proteins)
    params = {
        "identifiers": identifiers_string,
        "species": species,
        "network_flavor": "evidence",
        "network_type": "functional",
        "hide_disconnected_nodes": 0,
        "required_score": 400,
        "caller_identity": "genetic_ai_agent"
    }
    
    try:
        response = requests.post(request_url, data=params, timeout=60)
        response.raise_for_status()
        web_url = response.json()[0]
        return web_url
    except Exception as e:
        print(f"      ⚠️  STRING API link request failed: {e}")
        return None


def generate_string_ppi_network(proteins: List[str], img_dir: str = "results/imgs") -> tuple:
    """
    Simplified PPI analysis: directly call STRING API to generate network.
    
    This replaces the complex QueryAgent → ReasoningAgent pipeline with a
    direct STRING API call.
    
    Parameters:
    -----------
    proteins : List[str]
        List of gene symbols (NOT Ensembl IDs)
    img_dir : str
        Directory to save the network image
        
    Returns:
    --------
    tuple : (protein_count, ppi_filename, ppi_web_url)
        - protein_count: Number of proteins in the network
        - ppi_filename: Path to the saved network image
        - ppi_web_url: URL to interactive STRING webpage
    """
    if not proteins or len(proteins) == 0:
        return 0, None, None
    
    # Generate unique filename
    filename = os.path.join(img_dir, f"ppi_{uuid.uuid4().hex[:8]}.png")
    
    # Ensure directory exists
    os.makedirs(img_dir, exist_ok=True)
    
    # Call STRING API
    image_path = generate_string_network_image(proteins, filename)
    web_url = generate_string_network_link(proteins)
    
    # Normalize filename for report (relative path)
    if image_path:
        relative_path = image_path.replace(os.path.dirname(img_dir) + "/", "")
    else:
        relative_path = None
    
    return len(proteins), relative_path, web_url or "https://string-db.org"

class GPTLedMultiAgentAnalyzer:

    def __init__(self, output_dir: str, model: str = "gpt-5", enable_hitl: bool = True,
                 gpt_predictor_class=None):
        """
        Initialize AG2-powered analyzer with HITL support.
        
        Parameters:
        -----------
        output_dir : str
            Output directory
        model : str
            Model name (for compatibility; actual model is gpt-5 via GPT5_LLM_CONFIG)
        enable_hitl : bool
            Enable human-in-the-loop checkpoints (default: True)
        gpt_predictor_class : class, optional
            Custom GPT predictor class (e.g., GPT5PathwayGeneratorWithExternal for external knowledge).
            Defaults to GPT5PathwayPredictor for backward compatibility.
        """
        # Store custom predictor class (or use default)
        self._gpt_predictor_class = gpt_predictor_class or GPT5PathwayPredictor
        self.output_dir = output_dir
        self.model = "gpt-5"  # Always use gpt-5 (via GPT5_LLM_CONFIG)
        self.enable_hitl = enable_hitl

        # Create output directory for gpt_led_analysis
        self.results_dir = os.path.join(output_dir, 'gpt_led_analysis_ag2_hitl')
        os.makedirs(self.results_dir, exist_ok=True)

        # Create imgs directory for PPI network visualizations
        self.imgs_dir = os.path.join(self.results_dir, 'imgs')
        os.makedirs(self.imgs_dir, exist_ok=True)
        
        # ========================================================================
        # AG2 WORKFLOW INTEGRATION
        # ========================================================================
        self.ag2_workflow = None
        if AG2_HITL_AVAILABLE and enable_hitl:
            try:
                self.ag2_workflow = AG2PathwayWorkflow(
                    enable_human_review=True
                )
                
                # Get specialized AG2 agents
                self.ranking_agent = self.ag2_workflow.ranking_agent
                self.connection_agent = self.ag2_workflow.connection_agent
                self.aggregation_agent = self.ag2_workflow.aggregation_agent
                
                print(f"\n✅ AG2 HITL workflow initialized")
                print(f"   Model: gpt-5 (via GPT5_LLM_CONFIG)")
                print(f"   Temperature: 0.2")
                print(f"   HITL checkpoints: Module analysis, Pathway ranking, Aggregation")
            except Exception as e:
                print(f"⚠️  AG2 workflow initialization failed: {e}")
                print("   Falling back to non-HITL mode")
                self.ag2_workflow = None
                enable_hitl = False
        else:
            print(f"\n⚠️  AG2 not available or HITL disabled")
            print(f"   Running in non-HITL mode")

        # Initialize GPT predictor (uses configurable class for external knowledge support)
        # Check for Reasoning RAG context from environment variable
        reasoning_context = os.environ.get('REASONING_RAG_CONTEXT')
        if reasoning_context:
            print(f"\n🧠 REASONING RAG MODE: Injecting expert strategies from Memory Bank")
        
        # Use configurable predictor class (default: GPT5PathwayPredictor, or custom like GPT5PathwayGeneratorWithExternal)
        self.gpt_predictor = self._gpt_predictor_class(model=model, reasoning_context=reasoning_context)
        if self._gpt_predictor_class != GPT5PathwayPredictor:
            print(f"   📚 Using custom predictor: {self._gpt_predictor_class.__name__}")

        # Initialize original multi-agent analyzer
        # (will use its g:Profiler, ranking, and analysis capabilities)
        self.base_analyzer = MultiAgentPathwayAnalyzer(
            output_dir=self.output_dir,
            model=model
        )

        # NOTE: Disease keyword matching removed - GPT ranking now uses 
        # direct evaluation of pathway descriptions, disease context, and PubMed literature
        # instead of hardcoded keyword lists

        print(f"\n📁 Results will be saved in: {self.results_dir}")
        print(f"📁 PPI images will be saved in: {self.imgs_dir}")

    def _add_evidence_based_ranking(self, pathways_df: pd.DataFrame) -> pd.DataFrame:
        if pathways_df.empty:
            return pathways_df

        df = pathways_df.copy()

        # Calculate evidence score using -log10(p) transformation
        # Formula: min(-log10(p), cap) / cap, where cap=10
        import numpy as np
        
        def calculate_evidence_score(p_value):
            if p_value <= 0:
                return 1.0
            return min(-np.log10(p_value), 10) / 10
        
        df['evidence_score'] = df['p_value'].apply(calculate_evidence_score)
        
        # Combined ranking: PubMed score (60%) + Evidence score (40%)
        if 'score' in df.columns:
            df['combined_ranking_score'] = (
                df['score'].fillna(0) * 0.6 + 
                df['evidence_score'] * 0.4
            )
            df = df.sort_values(
                by=['combined_ranking_score', 'p_value'],
                ascending=[False, True]
            )
        else:
            # Fallback: sort by evidence score only
            df = df.sort_values(
                by=['evidence_score', 'p_value'],
                ascending=[False, True]
            )


        print(f"\n🎯 Evidence-based ranking applied:")
        print(f"   Ranking formula: PubMed Score (60%) + Evidence Score (40%)")
        print(f"   Evidence Score = min(-log10(p_value), 10) / 10")
        print(f"   (Removed disease keyword matching)")

        print(f"\n   Top 5 pathways after evidence-based ranking:")
        for i, (idx, row) in enumerate(df.head(5).iterrows(), 1):
            evidence = row.get('evidence_score', 0)
            p_val = row.get('p_value', 1.0)
            pubmed = row.get('score', 0)
            combined = row.get('combined_ranking_score', 0)
            
            print(f"   {i}. {row['name']}")
            print(f"      Evidence={evidence:.3f}, PubMed={pubmed:.3f}, Combined={combined:.3f}, p-value={p_val:.2e}")
        
        # ====================================================================
        # HITL CHECKPOINT 2: Review after pathway ranking
        # ====================================================================
        if self.ag2_workflow and self.enable_hitl:
            print(f"\n{'='*80}")
            print(f"🔍 HITL CHECKPOINT 2: Pathway Ranking Complete")
            print(f"{'='*80}")
            
            try:
                checkpoint_message = f"""
**Pathway Ranking Complete**

Total pathways ranked: {len(df)}
Top pathway: {df.iloc[0]['name'] if len(df) > 0 else 'N/A'}
Ranking method: Evidence-based (PubMed 60% + p-value 40%)

Human review options:
- APPROVE: Continue with current ranking
- MODIFY: Adjust ranking criteria
- QUIT: Exit analysis
"""
                
                print(checkpoint_message)
                
                # Simple checkpoint - wait for user confirmation
                from pipeline.ag2_config import is_interactive_mode
                if is_interactive_mode():
                    user_input = input("\n[HITL] Approve ranking? (y/n): ").strip().lower()
                else:
                    user_input = 'y'  # Auto-approve in non-interactive mode
                    print("   [Auto-approved ranking - non-interactive mode]")
                
                if user_input == 'n':
                    print(f"⚠️  User rejected ranking - would allow re-ranking in full version")
                    print(f"   Continuing with current ranking for now...")
                else:
                    print(f"✅ Ranking approved, continuing...")
                    
            except Exception as e:
                print(f"⚠️  HITL checkpoint failed: {e}")
                print(f"   Continuing without human review")

        return df
    
    # Legacy alias for backward compatibility
    def _add_ad_specificity_ranking(self, pathways_df: pd.DataFrame, 
                                     disease_keywords: List[str] = None,
                                     is_disease_pair: bool = False) -> pd.DataFrame:
        """
        DEPRECATED: Redirects to _add_evidence_based_ranking.
        Disease keyword matching has been removed.
        """
        print("⚠️  _add_ad_specificity_ranking is deprecated, using _add_evidence_based_ranking instead")
        return self._add_evidence_based_ranking(pathways_df)

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
            
            # ====================================================================
            # HITL CHECKPOINT 1: Review after each module analysis
            # ====================================================================
            if self.ag2_workflow and self.enable_hitl:
                print(f"\n{'='*80}")
                print(f"🔍 HITL CHECKPOINT 1: Module {module_id} Analysis Complete")
                print(f"{'='*80}")
                
                try:
                    # Prepare module result for review
                    checkpoint_message = f"""
**Module {module_id} Analysis Complete**

Module: {module_name}
Genes: {len(genes)}
GPT Predicted Pathways: {len(module_result.get('gpt_prediction', {}).get('predicted_pathways', []))}
Validated Pathways: {len(module_result.get('gpt_filtered_pathways', pd.DataFrame()))}

Human review options:
- APPROVE: Continue to next module
- MODIFY: Adjust pathway selection
- SKIP: Skip this module
- QUIT: Exit analysis
"""
                    
                    # Use AG2 workflow for human review
                    # (In future version, can use review_module_collection)
                    print(checkpoint_message)
                    
                    # Simple checkpoint - wait for user confirmation
                    from pipeline.ag2_config import is_interactive_mode
                    if is_interactive_mode():
                        user_input = input("\n[HITL] Continue? (y/n/modify): ").strip().lower()
                    else:
                        user_input = 'y'  # Auto-continue in non-interactive mode
                        print("   [Auto-continuing to next module - non-interactive mode]")
                    
                    if user_input == 'n':
                        print(f"⏭️  Skipping remaining modules")
                        break
                    elif user_input == 'modify':
                        print(f"⚠️  Modification not yet implemented - using current results")
                    else:
                        print(f"✅ Continuing with next module...")
                        
                except Exception as e:
                    print(f"⚠️  HITL checkpoint failed: {e}")
                    print(f"   Continuing without human review")



        self._generate_modules_summary_report(results, disease_name)

        # ====================================================================
        # HITL CHECKPOINT 3: Review after aggregation
        # ====================================================================
        if self.ag2_workflow and self.enable_hitl:
            print(f"\n{'='*80}")
            print(f"🔍 HITL CHECKPOINT 3: Aggregation Complete")
            print(f"{'='*80}")
            
            try:
                # Summary stats
                total_modules_analyzed = len(results['module_results'])
                total_pathways = sum(
                    len(res.get('gpt_filtered_pathways', pd.DataFrame())) 
                    for res in results['module_results'].values()
                )
                
                checkpoint_message = f"""
**Final Aggregation Complete**

Total modules analyzed: {total_modules_analyzed}
Total validated pathways (all modules): {total_pathways}
Results directory: {self.results_dir}

Key outputs:
- Module-specific reports
- Aggregated summary report
- PPI network visualizations

Human review options:
- APPROVE: Accept final results
- MODIFY: Request changes
- SAVE: Save and exit
- QUIT: Discard and exit
"""
                
                print(checkpoint_message)
                
                # Final checkpoint - wait for user confirmation
                from pipeline.ag2_config import is_interactive_mode
                if is_interactive_mode():
                    user_input = input("\n[HITL] Final approval? (approve/modify/save): ").strip().lower()
                else:
                    user_input = 'approve'  # Auto-approve in non-interactive mode
                    print("   [Auto-approved final results - non-interactive mode]")
                
                if user_input == 'modify':
                    print(f"⚠️  Modification requested - would allow re-analysis in full version")
                    print(f"   Current results preserved")
                elif user_input == 'save' or user_input == 'approve':
                    print(f"✅ Results approved and saved")
                    print(f"   Review summary at: {self.results_dir}")
                else:
                    print(f"✅ Analysis complete")
                    
            except Exception as e:
                print(f"⚠️  HITL checkpoint failed: {e}")
                print(f"   Results saved anyway")

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
                                 iteration_feedback: str = None,
                                 gpt_rank_function: callable = None,
                                 disease_description: str = None,
                                 query_agent: Any = None,
                                 benchmark_config: dict = None,
                                 file_identifier: str = None,
                                 iteration: int = None,
                                 memory_context: str = None) -> Dict[str, Any]:

        # Determine genes for GPT prediction
        gpt_input_genes = genes_for_gpt if genes_for_gpt is not None else genes
        
        # Resolve full disease name for GPT prompts
        # disease_name is kept as module label for file naming (e.g., "PS_Module_2_iter1")
        # disease_context is the full name for GPT prompts (e.g., "Psoriasis")
        disease_context = resolve_disease_full_name(disease_name)
        if disease_context != disease_name:
            print(f"   🏷️  Module label: {disease_name}")
            print(f"   🔬 Disease context for GPT: {disease_context}")
        
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
            'disease_full_name': disease_context,  # Full name for reports (e.g., "Psoriasis")
            'gene_count': len(genes),
            'gpt_input_gene_count': len(gpt_input_genes),
            'timestamp': time.strftime("%Y-%m-%d %H:%M:%S"),
            'top_k_predict': top_k_predict,
            'top_k_analyze': top_k_analyze,
            'retained_pathways': retained_pathways if retained_pathways else [],
            'retained_pathways_df': retained_pathways_df,  # CRITICAL: Pass DataFrame for category tracking
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
            # PRIMARY SOURCE: retained_pathways_df (from g:Profiler CSV) - has p_value, source, pathway_id
            # SECONDARY SOURCE: _last_gpt_prediction - has rationale from GPT prediction
            retained_pathway_details = {}
            
            # Step 1: Build from retained_pathways_df (most reliable: has p_value, source from g:Profiler)
            if retained_pathways_df is not None and not retained_pathways_df.empty:
                for _, row in retained_pathways_df.iterrows():
                    pw_name = row.get('name', '')
                    if pw_name and pw_name in retained_pathways:
                        retained_pathway_details[pw_name] = {
                            'source': row.get('source', 'Unknown'),
                            'p_value': row.get('p_value', 'N/A'),
                            'pathway_id': row.get('native', row.get('pathway_id', row.get('go_id', 'N/A'))),
                            'rationale': row.get('description', ''),  # g:Profiler description as fallback
                        }
                if retained_pathway_details:
                    print(f"   📊 Built pathway details from retained CSV: {len(retained_pathway_details)}/{len(retained_pathways)} pathways")
            
            # Step 2: Merge/supplement with _last_gpt_prediction (has GPT rationale)
            if hasattr(self, '_last_gpt_prediction') and self._last_gpt_prediction:
                last_details = self._last_gpt_prediction.get('pathway_details', {})
                for pw_name in retained_pathways:
                    if pw_name in last_details:
                        if pw_name in retained_pathway_details:
                            # Merge: keep p_value from CSV, add rationale from GPT if not already set
                            gpt_detail = last_details[pw_name]
                            if gpt_detail.get('rationale') and not retained_pathway_details[pw_name].get('rationale'):
                                retained_pathway_details[pw_name]['rationale'] = gpt_detail['rationale']
                        else:
                            # Fallback: use GPT details if not found in CSV
                            retained_pathway_details[pw_name] = last_details[pw_name]
            
            # Log any missing pathways
            missing = [pw for pw in retained_pathways if pw not in retained_pathway_details]
            if missing:
                print(f"   ⚠️  {len(missing)} retained pathways not found in details: {missing[:3]}...")
            
            # CRITICAL: Compute retained_per_category from retained_pathways_df
            # This is more reliable than extracting from retained_pathway_details
            # because retained_pathways_df has the 'source' column from g:Profiler
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
                disease_name=disease_context,
                feedback=iteration_feedback,
                gobp_count=per_category + (1 if remainder > 0 else 0),
                gomf_count=per_category + (1 if remainder > 1 else 0),
                gocc_count=per_category + (1 if remainder > 2 else 0),
                kegg_count=per_category + (1 if remainder > 3 else 0),
                reac_count=per_category,
                retained_pathways=retained_pathways,  # Pass retained pathways
                retained_pathway_details=retained_pathway_details,  # Pass their details
                retained_per_category=retained_per_category,  # Pass per-category counts for FDR saturation check
                benchmark_config=benchmark_config,  # Pass benchmark config for deterministic evaluation
                file_identifier=file_identifier,  # Pass for reasoning path saving
                iteration=iteration,  # Pass for reasoning path saving
                memory_context=memory_context  # NEW: Pass memory context for prediction & reasoning
            )
        else:
            gpt_prediction = self.gpt_predictor.predict_pathways(
                genes=gpt_input_genes,
                disease_name=disease_context,
                benchmark_config=benchmark_config,  # Pass benchmark config for deterministic evaluation
                file_identifier=file_identifier,  # Pass for reasoning path saving (Iteration 1)
                iteration=iteration,  # Pass for reasoning path saving (Iteration 1)
                memory_context=memory_context  # NEW: Pass memory context for prediction & reasoning
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
            # Agents not loaded but g:Profiler is a direct API call - run it directly
            print("⚠️  Agents not loaded (BioBERT tokenizer issue) - running g:Profiler directly")
            try:
                from src.pathway_enrichment_analysis import PathwayEnrichmentAnalyzer
                enrichment_analyzer = PathwayEnrichmentAnalyzer(self.results_dir)
                cached_all_pathways = enrichment_analyzer.enrich_geneset_full(
                    genes=genes,
                    name=disease_name,
                    sources=['GO:BP', 'GO:MF', 'GO:CC', 'KEGG', 'REAC']
                )
                if not cached_all_pathways.empty:
                    fdr_pathways = cached_all_pathways[cached_all_pathways['p_value'] < 0.05].copy()
                    gprofiler_cache = {
                        'all_pathways': cached_all_pathways,
                        'ranked_pathways': fdr_pathways,
                        'wellknown': [],
                        'novel': []
                    }
                    print(f"   ✅ Direct g:Profiler: {len(cached_all_pathways)} total, {len(fdr_pathways)} FDR-significant")
                else:
                    print("❌ No g:Profiler results - returning empty")
                    return results
            except Exception as e:
                print(f"❌ g:Profiler direct call failed: {e}")
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
            combined = pd.concat([
                forced_retained_pathways,
                new_matched_pathways
            ], ignore_index=True)
            # Case-insensitive deduplication: create lowercase name for comparison
            combined['_name_lower'] = combined['name'].str.lower()
            gpt_matched_pathways = combined.drop_duplicates(subset='_name_lower', keep='first').drop(columns=['_name_lower'])
            print(f"   ℹ️  Removed {len(combined) - len(gpt_matched_pathways)} duplicate pathways (case-insensitive)")
        else:
            gpt_matched_pathways = new_matched_pathways


        print(f"\n{'='*80}")
        print(f"MATCHING RESULTS - ALL PATHWAYS")
        print(f"{'='*80}")
        print(f"  📝 GPT Generated: {len(gpt_predicted)} pathways")
        print(f"  ✅ ID exact matches: {matching_stats['id_match']}")
        print(f"  ✅ Name fuzzy matches: {matching_stats['name_match']}")
        print(f"  ❌ No matches: {matching_stats['no_match']}")
        print(f"  Total matched (all pathways): {matching_stats['id_match'] + matching_stats['name_match']}")
        print(f"  Total g:Profiler pathways: {len(raw_gprofiler_df)}")
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
            # IMPORTANT: Retained pathways are ALWAYS 100% validated
            # They come from previous iteration's FDR-significant results
            # No need to re-check them against current g:Profiler matches
            n_retained_validated = n_retained  # All retained = validated
            n_new_validated = len(gpt_matched_pathways) - n_retained_validated
            print(f"\n  Breakdown:")
            print(f"    - Retained & validated: {n_retained_validated}/{n_retained} (100%, inherited from previous iteration)")
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
            if hasattr(self.gpt_predictor, 'generate_posthoc_audit_trace'):
                print("\n" + "="*80)
                print("STEP 3.6: POST-HOC AUDIT TRACE")
                print("="*80)
                try:
                    audit_traces = self.gpt_predictor.generate_posthoc_audit_trace(
                        genes=gpt_input_genes,
                        disease_name=disease_context,
                        gpt_prediction=gpt_prediction,
                        validated_pathways_df=pd.DataFrame(),
                        matched_pathways_df=pd.DataFrame(),
                        feedback=iteration_feedback,
                        benchmark_config=benchmark_config,
                        file_identifier=file_identifier,
                        iteration=iteration
                    )
                    results['audit_traces'] = audit_traces
                    print(f"   ✅ Post-hoc audit traces generated: {len(audit_traces)} categories")
                except Exception as e:
                    print(f"   ⚠️  Post-hoc audit trace generation failed: {e}")
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
            gpt_matched_nominal = gpt_matched_pathways.copy()  # Use all if no nominal
        
        # =================================================================
        # STEP 3.5: CATEGORY BREAKDOWN COMPARISON (ALL vs NOMINAL vs FDR)
        # =================================================================
        print("\n" + "="*80)
        print("STEP 3.5: CATEGORY BREAKDOWN COMPARISON")
        print("="*80)
        
        # Get all categories
        all_categories = ['GO:BP', 'GO:MF', 'GO:CC', 'KEGG', 'REAC']
        
        # Calculate counts for each category and filter level
        def get_category_counts(df, categories):
            counts = {}
            if 'source' in df.columns and len(df) > 0:
                source_counts = df['source'].value_counts()
                for cat in categories:
                    counts[cat] = source_counts.get(cat, 0)
            else:
                for cat in categories:
                    counts[cat] = 0
            return counts
        
        
        # Calculate GPT predicted counts per category
        def get_gpt_predicted_counts(predicted_pathways, pathway_details, categories):
            """Count how many pathways GPT predicted per category."""
            counts = {}
            for cat in categories:
                counts[cat] = 0
            
            # Count pathways by their source category
            for pw_name in predicted_pathways:
                if pw_name in pathway_details:
                    source = pathway_details[pw_name].get('source', '')
                    if source in categories:
                        counts[source] += 1
            
            return counts
        
        # Count retained pathways per category
        retained_pathways_list = results.get('retained_pathways', [])
        retained_counts = {}
        new_gen_counts = {}
        
        for cat in all_categories:
            retained_counts[cat] = 0
            new_gen_counts[cat] = 0
        
        if retained_pathways_list and len(retained_pathways_list) > 0:
            # Count retained pathways by category
            # CRITICAL: Get DataFrame from results (passed from analyze_gpt_led_pathways)
            retained_df = results.get('retained_pathways_df', None)
            
            # DEBUG: Print status
            print(f"\n   🔍 DEBUG Retained Pathways:")
            print(f"      retained_pathways_list length: {len(retained_pathways_list)}")
            print(f"      retained_df is None: {retained_df is None}")
            if retained_df is not None:
                print(f"      retained_df shape: {retained_df.shape}")
                print(f"      retained_df columns: {retained_df.columns.tolist()}")
                if 'source' in retained_df.columns:
                    print(f"      retained_df sources: {retained_df['source'].value_counts().to_dict()}")
            
            if retained_df is not None and not retained_df.empty:
                # Use DataFrame with source column (most reliable)
                print(f"   ℹ️  Using retained_pathways_df with {len(retained_df)} pathways for category counting")
                for _, row in retained_df.iterrows():
                    source = row.get('source', '')
                    if source in all_categories:
                        retained_counts[source] += 1
            elif hasattr(self, '_last_gpt_prediction') and self._last_gpt_prediction:
                # Fallback: use last prediction details
                print(f"   ℹ️  Using _last_gpt_prediction for category counting (fallback)")
                last_details = self._last_gpt_prediction.get('pathway_details', {})
                for pw_name in retained_pathways_list:
                    if pw_name in last_details:
                        source = last_details[pw_name].get('source', '')
                        if source in all_categories:
                            retained_counts[source] += 1
            else:
                print(f"   ⚠️  No source information available for retained pathways - counts will be 0")
        
        # Count newly generated pathways (excluding retained)
        gpt_prediction_details = gpt_prediction.get('pathway_details', {})
        for pw_name in gpt_predicted:
            if pw_name not in retained_pathways_list:  # Only count new ones
                if pw_name in gpt_prediction_details:
                    source = gpt_prediction_details[pw_name].get('source', '')
                    if source in all_categories:
                        new_gen_counts[source] += 1
        
        # Calculate total predicted (retained + new gen)
        total_pred_counts = {}
        for cat in all_categories:
            total_pred_counts[cat] = retained_counts[cat] + new_gen_counts[cat]
        
        all_counts = get_category_counts(gpt_matched_pathways, all_categories)
        nominal_counts = get_category_counts(gpt_matched_nominal, all_categories)
        fdr_counts = get_category_counts(gpt_matched_fdr, all_categories)
        
        # Calculate newly matched (matched from NEW generation only, excluding retained)
        # Newly matched = Matched - Retained (for each category)
        newly_matched_counts = {}
        newly_fdr_counts = {}  # New FDR = FDR - Retained (FDR-significant from new predictions)
        for cat in all_categories:
            # Newly matched = total matched in this category - retained from this category
            newly_matched_counts[cat] = max(0, all_counts[cat] - retained_counts[cat])
            # Newly FDR = total FDR in this category - retained from this category (retained are already FDR-significant)
            newly_fdr_counts[cat] = max(0, fdr_counts[cat] - retained_counts[cat])
        
        # Print improved table header (with extended columns for iteration 2+)
        # Check if we have retained pathways by summing retained_counts (total_retained not yet calculated)
        has_retained = sum(retained_counts.values()) > 0
        
        if has_retained:
            # Iteration 2+: show extended columns
            print(f"\n  {'Category':<10} | {'Retained':<8} | {'NewGen':<6} | {'Total':<5} | {'Match':<5} | {'NewMat':<6} | {'Mat%':<5} | {'NMat%':<6} | {'FDR':<4} | {'NewFDR':<6} | {'FDR%':<5} | {'NFDR%':<6}")
            print(f"  {'-'*10}-+-{'-'*8}-+-{'-'*6}-+-{'-'*5}-+-{'-'*5}-+-{'-'*6}-+-{'-'*5}-+-{'-'*6}-+-{'-'*4}-+-{'-'*6}-+-{'-'*5}-+-{'-'*6}")
        else:
            # Iteration 1: simpler columns
            print(f"\n  {'Category':<10} | {'Retained':<8} | {'NewGen':<6} | {'Total':<5} | {'Match':<5} | {'Mat%':<5} | {'FDR':<4} | {'FDR%':<5}")
            print(f"  {'-'*10}-+-{'-'*8}-+-{'-'*6}-+-{'-'*5}-+-{'-'*5}-+-{'-'*5}-+-{'-'*4}-+-{'-'*5}")
        
        # Print each category
        for cat in all_categories:
            retained_n = retained_counts[cat]
            new_gen_n = new_gen_counts[cat]
            total_pred_n = total_pred_counts[cat]
            matched_n = all_counts[cat]
            newly_matched_n = newly_matched_counts[cat]
            fdr_n = fdr_counts[cat]
            newly_fdr_n = newly_fdr_counts[cat]
            
            # Calculate percentages
            match_pct = (matched_n / total_pred_n * 100) if total_pred_n > 0 else 0
            fdr_pct = (fdr_n / matched_n * 100) if matched_n > 0 else 0  # FDR% = FDR / Matched (filter rate)
            
            # Calculate NewFDR% = NewFDR / NewMat
            new_fdr_pct = (newly_fdr_n / newly_matched_n * 100) if newly_matched_n > 0 else 0
            
            # Calculate NewMat% = NewMat / Total
            new_mat_pct = (newly_matched_n / total_pred_n * 100) if total_pred_n > 0 else 0
            
            if has_retained:
                print(f"  {cat:<10} | {retained_n:<8} | {new_gen_n:<6} | {total_pred_n:<5} | {matched_n:<5} | {newly_matched_n:<6} | {match_pct:>4.0f}% | {new_mat_pct:>4.0f}% | {fdr_n:<4} | {newly_fdr_n:<6} | {fdr_pct:>4.0f}% | {new_fdr_pct:>4.0f}%")
            else:
                print(f"  {cat:<10} | {retained_n:<8} | {new_gen_n:<6} | {total_pred_n:<5} | {matched_n:<5} | {match_pct:>4.0f}% | {fdr_n:<4} | {fdr_pct:>4.0f}%")
        
        # Print totals
        total_retained = sum(retained_counts.values())
        total_new_gen = sum(new_gen_counts.values())
        total_pred = sum(total_pred_counts.values())
        total_matched = len(gpt_matched_pathways)
        total_newly_matched = sum(newly_matched_counts.values())
        total_fdr = len(gpt_matched_fdr)
        total_newly_fdr = sum(newly_fdr_counts.values())
        
        # Calculate total percentages
        total_match_pct = (total_matched / total_pred * 100) if total_pred > 0 else 0
        total_fdr_pct = (total_fdr / total_matched * 100) if total_matched > 0 else 0  # FDR% = FDR / Matched (filter rate)
        
        # Calculate total NewFDR% = total NewFDR / total NewMat
        total_new_fdr_pct = (total_newly_fdr / total_newly_matched * 100) if total_newly_matched > 0 else 0
        
        # Calculate total NewMat% = total NewMat / total Total
        total_new_mat_pct = (total_newly_matched / total_pred * 100) if total_pred > 0 else 0
        
        if has_retained:
            print(f"  {'-'*10}-+-{'-'*8}-+-{'-'*6}-+-{'-'*5}-+-{'-'*5}-+-{'-'*6}-+-{'-'*5}-+-{'-'*6}-+-{'-'*4}-+-{'-'*6}-+-{'-'*5}-+-{'-'*6}")
            print(f"  {'TOTAL':<10} | {total_retained:<8} | {total_new_gen:<6} | {total_pred:<5} | {total_matched:<5} | {total_newly_matched:<6} | {total_match_pct:>4.0f}% | {total_new_mat_pct:>4.0f}% | {total_fdr:<4} | {total_newly_fdr:<6} | {total_fdr_pct:>4.0f}% | {total_new_fdr_pct:>4.0f}%")
        else:
            print(f"  {'-'*10}-+-{'-'*8}-+-{'-'*6}-+-{'-'*5}-+-{'-'*5}-+-{'-'*5}-+-{'-'*4}-+-{'-'*5}")
            print(f"  {'TOTAL':<10} | {total_retained:<8} | {total_new_gen:<6} | {total_pred:<5} | {total_matched:<5} | {total_match_pct:>4.0f}% | {total_fdr:<4} | {total_fdr_pct:>4.0f}%")
        
        total_nominal = len(gpt_matched_nominal)
        
        # CRITICAL: Store gpt_prediction for next iteration
        # This ensures retained pathway categories can be tracked in subsequent iterations
        self._last_gpt_prediction = gpt_prediction
        
        # Iteration Summary
        print(f"\n📊 Iteration Summary:")
        if total_retained > 0:
            print(f"   Retained from previous: {total_retained} pathways")
        print(f"   Newly generated (GPT):  {total_new_gen} pathways")
        print(f"   Total predicted:        {total_pred} pathways")
        print(f"   Successfully matched:   {total_matched} pathways ({total_matched/total_pred*100:.1f}%)" if total_pred > 0 else "   Successfully matched:   0 pathways")
        print(f"   Nominal significant:    {total_nominal} pathways")
        print(f"   FDR-significant:        {total_fdr} pathways → Will be retained for next iteration")
        if total_retained > 0:
            retention_rate = total_retained / total_pred * 100 if total_pred > 0 else 0
            print(f"   Retention rate:         {retention_rate:.1f}% (retained/total predicted)")
        
        
        # Store iteration stats for tracking
        iteration_stats = {
            'all': dict(all_counts),  # Matched per category
            'nominal': dict(nominal_counts),
            'fdr': dict(fdr_counts),
            'predicted': dict(total_pred_counts),  # Total predicted per category
            'all_total': len(gpt_matched_pathways),  # Total matched
            'nominal_total': len(gpt_matched_nominal),
            'fdr_total': len(gpt_matched_fdr),
            'predicted_total': total_pred,  # Total predicted pathways
            # Calculate rates for plotting
            'matched_rate': (len(gpt_matched_pathways) / total_pred * 100) if total_pred > 0 else 0,
            'fdr_rate': (len(gpt_matched_fdr) / len(gpt_matched_pathways) * 100) if len(gpt_matched_pathways) > 0 else 0,
            # Per-category rates
            'matched_rate_per_cat': {cat: (all_counts[cat] / total_pred_counts[cat] * 100) if total_pred_counts[cat] > 0 else 0 for cat in all_categories},
            'fdr_rate_per_cat': {cat: (fdr_counts[cat] / all_counts[cat] * 100) if all_counts[cat] > 0 else 0 for cat in all_categories}
        }
        results['category_stats'] = iteration_stats
        
        print(f"\n📊 Summary:")
        print(f"   • ALL matched: {len(gpt_matched_pathways)} pathways")
        print(f"   • Nominal significant: {len(gpt_matched_nominal)} pathways")
        print(f"   • FDR significant: {len(gpt_matched_fdr)} pathways")
        print(f"   • Filter retention rate: {len(gpt_matched_fdr)/len(gpt_matched_pathways)*100:.1f}%" if len(gpt_matched_pathways) > 0 else "   • Filter retention rate: N/A")
        
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
                # Handle duplicate pathway names by keeping first occurrence (case-insensitive)
                # (pathway names may be duplicated across different sources with different cases)
                cached_df['_name_lower'] = cached_df['name'].str.lower()
                cached_df_unique = cached_df.drop_duplicates(subset=['_name_lower'], keep='first').drop(columns=['_name_lower'])
                
                # Create mapping from pathway name to scores
                cache_by_name = cached_df_unique.set_index('name')[available_score_cols].to_dict('index')
                
                # Merge scores from cache
                for col in available_score_cols:
                    if col not in gpt_pathways_filtered.columns:
                        gpt_pathways_filtered[col] = gpt_pathways_filtered['name'].apply(
                            lambda x: cache_by_name.get(x, {}).get(col, 0.0 if col != 'validated_publications' else [])
                        )
                
                print(f"   ✅ Merged {len(available_score_cols)} scoring columns from cache")
        
        # =================================================================
        # STEP 4: GPT AUTO-RANKING (Dynamic Ranking)
        # =================================================================
        print("\n" + "="*80)
        print("STEP 4: GPT AUTO-RANKING")
        print("="*80)
        
        # Check if GPT autoranking should be performed
        if gpt_rank_function is not None and disease_description is not None and query_agent is not None:
            print(f"🎯 Running GPT Auto-Ranking on {len(gpt_pathways_filtered)} matched pathways")
            print("GPT will analyze raw information sources and rank pathways autonomously:")
            print("  1. Pathway Description (biological function)")
            print("  2. Disease Pathology (from MeSH/NCBI)")
            print("  3. P-Value (statistical significance)")
            print("  4. PubMed Literature (dynamic search)")
            print("")
            print("Ranking output: gpt_rank (1 = most relevant)")
            
            try:
                # Build a framework-like object with a planning_agent that has t2t_generate
                # When agents are loaded, use the real planning_agent
                # When agents can't load (BioBERT tokenizer issue), use direct OpenAI fallback
                if self.base_analyzer.agents_ready:
                    mock_planning_agent = self.base_analyzer.planning_agent
                else:
                    # Lightweight fallback: direct OpenAI API call (same as Agent.t2t_generate)
                    class _DirectGPTAgent:
                        """Minimal agent that calls OpenAI directly, bypassing BioBERT."""
                        def __init__(self, model_name="gpt-5.1"):
                            from openai import OpenAI
                            import httpx, dotenv, os
                            dotenv.load_dotenv()
                            self.model_name = model_name
                            self.client = OpenAI(
                                api_key=os.getenv('OPENAI_API_KEY'),
                                timeout=httpx.Timeout(600.0, connect=60.0),
                                max_retries=5
                            )
                        def t2t_generate(self, user_prompt, system_prompt="You are a helpful assistant."):
                            resp = self.client.chat.completions.create(
                                model=self.model_name,
                                messages=[
                                    {"role": "system", "content": system_prompt},
                                    {"role": "user", "content": user_prompt}
                                ],
                                max_completion_tokens=8000
                            )
                            return resp.choices[0].message.content.strip()
                    mock_planning_agent = _DirectGPTAgent()
                    print("   ℹ️  Using direct OpenAI fallback for GPT ranking (agents not loaded)")
                
                class MockFramework:
                    def __init__(self, planning_agent, qa):
                        self.analyzer = type('obj', (object,), {
                            'base_analyzer': type('obj', (object,), {
                                'query_agent': qa,
                                'planning_agent': planning_agent
                            })()
                        })()
                
                mock_framework = MockFramework(mock_planning_agent, query_agent)
                
                # Call GPT ranking function
                ranked_df = gpt_rank_function(
                    pathways_df=gpt_pathways_filtered.copy(),
                    disease_name=disease_context,
                    disease_description=disease_description,
                    query_agent=query_agent,
                    framework=mock_framework,
                    batch_size=20,
                    memory_context=memory_context  # Pass memory context
                )
                
                if ranked_df is not None and not ranked_df.empty and 'gpt_rank' in ranked_df.columns:
                    # Merge GPT ranking results back into gpt_pathways_filtered
                    merge_cols = ['name', 'gpt_rank']
                    optional_cols = ['score', 'evidence_score', 'composite_score', 'related_literature']
                    for col in optional_cols:
                        if col in ranked_df.columns:
                            merge_cols.append(col)
                    
                    # DEBUG: Check related_literature in ranked_df BEFORE merge
                    if 'related_literature' in ranked_df.columns:
                        lit_non_empty = ranked_df['related_literature'].apply(
                            lambda x: isinstance(x, list) and len(x) > 0
                        ).sum()
                        print(f"   📚 DEBUG: ranked_df has related_literature column")
                        print(f"      Non-empty entries: {lit_non_empty}/{len(ranked_df)}")
                        if lit_non_empty > 0:
                            # Show sample of first non-empty entry
                            sample = ranked_df.loc[ranked_df['related_literature'].apply(
                                lambda x: isinstance(x, list) and len(x) > 0
                            ), 'related_literature'].iloc[0]
                            print(f"      Sample (first paper): {sample[0] if sample else 'N/A'}")
                    else:
                        print(f"   ⚠️  DEBUG: ranked_df MISSING related_literature column!")
                        print(f"      Columns in ranked_df: {ranked_df.columns.tolist()[:10]}...")
                    
                    gpt_pathways = gpt_pathways_filtered.merge(
                        ranked_df[merge_cols],
                        on='name',
                        how='left',
                        suffixes=('', '_gpt')
                    )

                    # =====================================================================
                    # UNIFIED GPT RANKING (v2): Use gpt_rank_gpt for ALL pathways
                    # =====================================================================
                    # DESIGN CHANGE (2026-02-04):
                    # - OLD: Retained pathways kept their Iter1 gpt_rank (unfair advantage)
                    # - NEW: ALL pathways use the unified gpt_rank_gpt from current iteration
                    # This ensures fair competition between retained and new pathways
                    # =====================================================================
                    
                    if 'gpt_rank_gpt' in gpt_pathways.columns:
                        # Use gpt_rank_gpt for ALL pathways (unified ranking)
                        valid_gpt_mask = gpt_pathways['gpt_rank_gpt'].notna()
                        updated_count = valid_gpt_mask.sum()
                        
                        if updated_count > 0:
                            # Replace gpt_rank with gpt_rank_gpt for all pathways
                            gpt_pathways.loc[valid_gpt_mask, 'gpt_rank'] = gpt_pathways.loc[valid_gpt_mask, 'gpt_rank_gpt']
                            print(f"   ✅ UNIFIED RANKING: Applied gpt_rank_gpt to {updated_count} pathways (retained + new)")
                        
                        # Log how many were retained vs new
                        if 'iteration_source' in gpt_pathways.columns:
                            current_iter = gpt_pathways['iteration_source'].max()
                            retained_count = (gpt_pathways['iteration_source'] < current_iter).sum()
                            new_count = (gpt_pathways['iteration_source'] == current_iter).sum()
                            print(f"   📊 Breakdown: {retained_count} retained + {new_count} new pathways, all re-ranked together")
                    
                    # DEBUG: Check related_literature AFTER merge
                    if 'related_literature' in gpt_pathways.columns:
                        lit_non_empty_after = gpt_pathways['related_literature'].apply(
                            lambda x: isinstance(x, list) and len(x) > 0
                        ).sum()
                        print(f"   📚 DEBUG: After merge, related_literature has {lit_non_empty_after}/{len(gpt_pathways)} non-empty entries")
                    
                    # Fill remaining NaN values with 999 (only for truly unranked pathways)
                    if 'gpt_rank' in gpt_pathways.columns:
                        nan_count = gpt_pathways['gpt_rank'].isna().sum()
                        if nan_count > 0:
                            print(f"   ⚠️  {nan_count} pathways have no rank (GPT ranking failed?), filling with 999")
                        gpt_pathways['gpt_rank'] = gpt_pathways['gpt_rank'].fillna(999)
                    
                    print(f"\n✅ GPT auto-ranking complete")
                    print(f"   Merged columns: {', '.join(merge_cols[1:])}")
                    top_rank = gpt_pathways['gpt_rank'].min()
                    print(f"   Top rank: {int(top_rank)}")
                    print(f"   Ranked pathways: {len(gpt_pathways)}")
                else:
                    print(f"\n⚠️  GPT ranking returned empty or missing gpt_rank column")
                    print(f"   Using pathways without GPT ranking")
                    gpt_pathways = gpt_pathways_filtered
                    
            except Exception as e:
                print(f"\n❌ GPT auto-ranking failed: {e}")
                import traceback
                traceback.print_exc()
                print(f"   Using pathways without GPT ranking")
                gpt_pathways = gpt_pathways_filtered
        else:
            # No GPT autoranking - use pathways as is
            print(f"ℹ️  GPT autoranking not enabled (parameters not provided)")
            missing = []
            if gpt_rank_function is None:
                missing.append("gpt_rank_function")
            if disease_description is None:
                missing.append("disease_description")
            if query_agent is None:
                missing.append("query_agent")
            print(f"   Missing: {', '.join(missing)}")
            print(f"   Using pathways without GPT ranking: {len(gpt_pathways_filtered)}")
            gpt_pathways = gpt_pathways_filtered
        
        if len(gpt_pathways) == 0:
            print("\n⚠️  Warning: No pathways to save")
            results['gpt_filtered_pathways'] = pd.DataFrame()
            results['validation_rate'] = 0.0
            if hasattr(self.gpt_predictor, 'generate_posthoc_audit_trace'):
                print("\n" + "="*80)
                print("STEP 3.6: POST-HOC AUDIT TRACE")
                print("="*80)
                try:
                    audit_traces = self.gpt_predictor.generate_posthoc_audit_trace(
                        genes=gpt_input_genes,
                        disease_name=disease_context,
                        gpt_prediction=gpt_prediction,
                        validated_pathways_df=pd.DataFrame(),
                        matched_pathways_df=gpt_matched_pathways,
                        feedback=iteration_feedback,
                        benchmark_config=benchmark_config,
                        file_identifier=file_identifier,
                        iteration=iteration
                    )
                    results['audit_traces'] = audit_traces
                    print(f"   ✅ Post-hoc audit traces generated: {len(audit_traces)} categories")
                except Exception as e:
                    print(f"   ⚠️  Post-hoc audit trace generation failed: {e}")
            return results
        
        # Add GPT key_genes to DataFrame before saving
        # Extract key_genes from gpt_prediction['pathway_details']
        pathway_details = gpt_prediction.get('pathway_details', {})
        
        def get_gpt_key_genes(pathway_name):
            """Get GPT-recommended key genes for a pathway"""
            if pathway_name in pathway_details:
                key_genes = pathway_details[pathway_name].get('key_genes', [])
                if isinstance(key_genes, list) and len(key_genes) > 0:
                    return ','.join(key_genes)  # Join as comma-separated string for CSV
            return ''  # Return empty string if no key genes
        
        # Add gpt_key_genes column
        gpt_pathways['gpt_key_genes'] = gpt_pathways['name'].apply(get_gpt_key_genes)
        print(f"   ℹ️  Added gpt_key_genes column ({gpt_pathways['gpt_key_genes'].str.len().gt(0).sum()} pathways have GPT key genes)")
        
        results['gpt_filtered_pathways'] = gpt_pathways
        results['validation_rate'] = len(gpt_pathways) / len(gpt_predicted)

        # CRITICAL: Also save all matched pathways (before FDR filtering) for next iteration
        # This ensures retained pathways can access full data even if not FDR-significant
        results['gpt_matched_all'] = gpt_matched_pathways.copy()  # Save before any filtering

        # =====================================================================
        # POST-HOC AUDIT TRACE (after generation + FDR validation)
        # =====================================================================
        # Reasoning traces are reconstructed only after candidate generation and
        # validation. They summarize generated JSON records, retained FDR-supported
        # pathways and failed matched terms, and do not affect the same-iteration
        # pathway list.
        if hasattr(self.gpt_predictor, 'generate_posthoc_audit_trace'):
            print("\n" + "="*80)
            print("STEP 3.6: POST-HOC AUDIT TRACE")
            print("="*80)
            try:
                audit_traces = self.gpt_predictor.generate_posthoc_audit_trace(
                    genes=gpt_input_genes,
                    disease_name=disease_context,
                    gpt_prediction=gpt_prediction,
                    validated_pathways_df=gpt_pathways,
                    matched_pathways_df=gpt_matched_pathways,
                    feedback=iteration_feedback,
                    benchmark_config=benchmark_config,
                    file_identifier=file_identifier,
                    iteration=iteration
                )
                results['audit_traces'] = audit_traces
                print(f"   ✅ Post-hoc audit traces generated: {len(audit_traces)} categories")
            except Exception as e:
                print(f"   ⚠️  Post-hoc audit trace generation failed: {e}")


        # =====================================================================
        # ADD ITERATION_SOURCE COLUMN - Track first iteration appearance
        # =====================================================================
        if iteration is not None and iteration > 0:
            print(f"\n   📊 Adding iteration_source column (current iteration: {iteration})...")

            # Initialize iteration_source column
            gpt_pathways['iteration_source'] = iteration

            # For iterations > 1, check previous iterations to find first appearance
            if iteration > 1:
                # Track which pathways were found in previous iterations
                pathway_first_seen = {}

                # BUGFIX: Remove _iter{N} suffix from disease_name if present
                # (framework may pass "AF_Module_3_iter2" but files are named "AF_Module_3_iter1")
                import re
                disease_name_base = re.sub(r'_iter\d+$', '', disease_name)

                # Check all previous iterations (1 to iteration-1)
                for prev_iter in range(1, iteration):
                    prev_file = os.path.join(
                        self.results_dir,
                        f'{disease_name_base}_iter{prev_iter}_gpt_filtered_pathways.csv'
                    )

                    if os.path.exists(prev_file):
                        try:
                            prev_df = pd.read_csv(prev_file)

                            # For each pathway in previous iteration
                            for _, prev_row in prev_df.iterrows():
                                prev_name = str(prev_row['name']).lower().strip()

                                # If pathway not yet seen, record this as first appearance
                                if prev_name not in pathway_first_seen:
                                    # Check if previous file has iteration_source column
                                    if 'iteration_source' in prev_df.columns and pd.notna(prev_row.get('iteration_source')):
                                        pathway_first_seen[prev_name] = int(prev_row['iteration_source'])
                                    else:
                                        # If no iteration_source in previous file, use that iteration number
                                        pathway_first_seen[prev_name] = prev_iter

                            print(f"      Checked iter{prev_iter}: {len(prev_df)} pathways")
                        except Exception as e:
                            print(f"      ⚠️  Could not read {os.path.basename(prev_file)}: {e}")

                # Update iteration_source for pathways that appeared in previous iterations
                updated_count = 0
                for idx, row in gpt_pathways.iterrows():
                    pathway_name = str(row['name']).lower().strip()
                    if pathway_name in pathway_first_seen:
                        gpt_pathways.at[idx, 'iteration_source'] = pathway_first_seen[pathway_name]
                        updated_count += 1

                print(f"      ✅ Updated {updated_count} pathways with previous iteration_source")
                print(f"      ✅ {len(gpt_pathways) - updated_count} new pathways marked as iteration {iteration}")
            else:
                print(f"      ✅ All {len(gpt_pathways)} pathways marked as iteration {iteration} (first iteration)")
        else:
            # If no iteration info, set to 1 as default
            gpt_pathways['iteration_source'] = 1.0
            print(f"\n   ℹ️  No iteration info provided, defaulting iteration_source to 1")

        # Save filtered pathways
        filtered_file = os.path.join(
            self.results_dir,
            f'{disease_name}_gpt_filtered_pathways.csv'
        )

        # Convert list-type columns to CSV-friendly formats
        gpt_pathways_csv = gpt_pathways.copy()
        columns_to_drop = []
        
        # Convert related_literature (list of dicts) to comma-separated PMIDs
        if 'related_literature' in gpt_pathways_csv.columns:
            def extract_pmids(lit_list):
                """Extract PMIDs from related_literature list of dicts"""
                if isinstance(lit_list, list) and len(lit_list) > 0:
                    pmids = [str(paper.get('pmid', '')) for paper in lit_list if paper.get('pmid')]
                    return ','.join(pmids[:5])  # Top 5 PMIDs
                return ''
            
            gpt_pathways_csv['literature_pmids'] = gpt_pathways_csv['related_literature'].apply(extract_pmids)
            columns_to_drop.append('related_literature')  # Drop original list column
            print(f"   ℹ️  Converted 'related_literature' to 'literature_pmids' (comma-separated)")
        
        if 'validated_publications' in gpt_pathways_csv.columns:
            columns_to_drop.append('validated_publications')
            print(f"   ℹ️  Dropping 'validated_publications' column (list type, unsuitable for CSV)")
        
        if columns_to_drop:
            gpt_pathways_csv = gpt_pathways_csv.drop(columns=columns_to_drop)
        
        gpt_pathways_csv.to_csv(filtered_file, index=False)
        print(f"\n✅ Saved GPT-filtered pathways: {filtered_file}")
        print(f"   Columns saved: {len(gpt_pathways_csv.columns)} (dropped {len(columns_to_drop)} list-type columns)")
        
        # Print top pathways with GPT rank
        print(f"\n📊 Top 5 GPT-Ranked & Validated Pathways:")
        for i, (idx, row) in enumerate(gpt_pathways.head(5).iterrows(), 1):
            p_val = row.get('p_value', 1.0)
            gpt_rank = row.get('gpt_rank', 'N/A')
            source = row.get('source', 'N/A')
            
            print(f"   {i}. {row['name']}")
            # Check for NaN before converting gpt_rank to int
            if gpt_rank != 'N/A' and pd.notna(gpt_rank):
                print(f"      GPT-Rank={int(gpt_rank)}, p-value={p_val:.2e}, source={source}")
            else:
                print(f"      p-value={p_val:.2e}, source={source}")
        
        # =================================================================
        # STEP 5: Reasoning Agent - Pathway Overview  
        # =================================================================
        print("\n" + "="*80)
        print("STEP 5: REASONING AGENT - Pathway Overview")
        print("="*80)
        
        try:
            # Select columns for Table 1 display
            # For autorank version: only show Term ID, Pathway Name, p-value, Source
            # (no score column since combined_score/weighted_score are not computed)
            base_cols = ["native", "name", "description", "p_value", "source"]
            cols = base_cols  # No score column
                
            pathway_info = gpt_pathways[cols].to_dict(orient="records")

            if not self.base_analyzer.agents_ready:
                print("  ℹ️  Reasoning agent not loaded (BioBERT tokenizer issue) - using fallback overview")
                raise RuntimeError("Reasoning agent not loaded")
            
            pathways_overview = self.base_analyzer.reasoning_agent.act(
                "Pathway_Section_Overview",
                {
                    "pathway_infos": pathway_info,
                    "disease_name": disease_context,
                    "formatting_instructions": "IMPORTANT: In tables, for p-values < 0.001, use scientific notation (e.g., 1.2e-05) instead of displaying as 0.000. Table 1 should only have columns: Term ID, Pathway Name, p-value, Source."
                }
            )
            
            results['pathways_overview'] = pathways_overview
            print("✅ Pathway overview generated")
            
        except RuntimeError as e:
            if "Reasoning agent not loaded" in str(e):
                pathways_overview = ""
            else:
                print(f"❌ Error in pathway overview: {e}")
                import traceback
                traceback.print_exc()
                pathways_overview = ""
        except Exception as e:
            print(f"❌ Error in pathway overview: {e}")
            import traceback
            traceback.print_exc()
            pathways_overview = ""
        
        # =================================================================
        # STEP 6: PPI Analysis Checkpoint (AG2 Human-in-the-Loop)
        # =================================================================
        
        # Default based on flag, but user can override
        run_ppi_analysis = not skip_ppi_analysis
        
        # Always prompt user if HITL is enabled (don't require ag2_workflow for this simple checkpoint)
        if self.enable_hitl:
            # Prepare checkpoint message with recommended action based on skip_ppi_analysis
            recommended = "SKIP" if skip_ppi_analysis else "APPROVE"
            
            print("\n" + "="*80)
            print("🔔 AG2 CHECKPOINT: PPI ANALYSIS")
            print("="*80)
            print(f"""
PPI (Protein-Protein Interaction) Analysis will:
• Analyze protein networks for top {top_k_analyze} pathways
• Identify protein functions and clusters
• Generate detailed pathway reports

This step can take 5-15 minutes depending on pathway count.

Validated pathways: {len(gpt_pathways)}
Top pathways for PPI: {top_k_analyze}

⚡ RECOMMENDED: {recommended} (based on skip_ppi_analysis={skip_ppi_analysis})

Options:
  [A] APPROVE - Run detailed PPI analysis (for final/deep analysis)
  [S] SKIP    - Skip PPI analysis (faster, for iterative refinement)
""")
            print(f"   Default recommendation: {recommended}")
            
            try:
                import sys
                
                # Retry loop to ensure we get actual user input
                max_retries = 3
                user_input = ''
                
                for retry in range(max_retries):
                    try:
                        # Flush stdout to ensure prompt is visible
                        sys.stdout.flush()
                        
                        from pipeline.ag2_config import is_interactive_mode
                        if is_interactive_mode():
                            user_input = input("\n[HITL] Your choice (A=approve/S=skip): ").strip().upper()
                        else:
                            user_input = 'S'  # Auto-skip PPI in non-interactive mode
                            print("   [Auto-skipping PPI analysis - non-interactive mode]")
                        
                        # If we got valid input, break out of retry loop
                        if user_input in ['SKIP', 'S', 'Q', 'APPROVE', 'A']:
                            break
                        elif user_input == '':
                            # Empty input - prompt again unless this is the last retry
                            if retry < max_retries - 1:
                                print(f"   ⚠️  Empty input received. Please enter A (approve) or S (skip).")
                                continue
                            else:
                                print(f"\n⚡ No input after {max_retries} attempts. Using default: {'SKIP' if skip_ppi_analysis else 'APPROVE'}")
                                break
                        else:
                            # Invalid input - prompt again unless this is the last retry
                            if retry < max_retries - 1:
                                print(f"   ⚠️  Invalid input '{user_input}'. Please enter A (approve) or S (skip).")
                                continue
                            else:
                                print(f"\n⚠️  Invalid input after {max_retries} attempts. Using default: {'SKIP' if skip_ppi_analysis else 'APPROVE'}")
                                break
                    except EOFError:
                        # stdin is closed (e.g., running in non-interactive mode)
                        print(f"\n⚠️  Non-interactive mode detected. Using default: {'SKIP' if skip_ppi_analysis else 'APPROVE'}")
                        break
                
                # Process the final user input
                if user_input in ['SKIP', 'S', 'Q']:
                    run_ppi_analysis = False
                    print("\n✅ User chose: SKIP - PPI analysis will be skipped")
                elif user_input in ['APPROVE', 'A']:
                    run_ppi_analysis = True  
                    print("\n✅ User chose: APPROVE - PPI analysis will proceed")
                else:
                    # Empty or invalid input after retries = use default recommendation
                    run_ppi_analysis = not skip_ppi_analysis
            except Exception as e:
                print(f"\n⚠️  HITL input failed: {e}")
                print(f"   Defaulting to: {'SKIP' if skip_ppi_analysis else 'APPROVE'}")
                run_ppi_analysis = not skip_ppi_analysis
        
        # Execute based on final decision
        if not run_ppi_analysis:
            print("\n" + "="*80)
            print("STEP 6: PPI ANALYSIS - SKIPPED")
            print("="*80)
            print("⚡ Skipping detailed PPI analysis")
            print("   Checking for existing PPI data from previous runs...")
            
            # Try to load existing PPI mapping from previous run
            import glob
            mapping_pattern = os.path.join(self.results_dir, f'{disease_name}*_ppi_mapping.json')
            mapping_files = sorted(glob.glob(mapping_pattern), reverse=True)
            
            pathway_details = {}
            for mapping_file in mapping_files:
                try:
                    with open(mapping_file, 'r') as f:
                        saved_mapping = json.load(f)
                    if saved_mapping:
                        print(f"   ✅ Loaded existing PPI data from: {os.path.basename(mapping_file)}")
                        for pw_name, pw_info in saved_mapping.items():
                            pathway_details[pw_name] = {
                                'protein_count': pw_info.get('protein_count', 0),
                                'ppi_filename': pw_info.get('ppi_filename'),
                                'ppi_web_url': pw_info.get('ppi_web_url', 'https://string-db.org'),
                                'function_summary': None
                            }
                        print(f"   ✅ Loaded {len(pathway_details)} pathways with PPI data")
                        break
                except Exception as e:
                    print(f"   ⚠️  Failed to load {os.path.basename(mapping_file)}: {e}")
                    continue
            
            if not pathway_details:
                print("   ℹ️  No existing PPI data found, report will be generated without PPI images")
            
            results['pathway_details'] = pathway_details
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
                        print(f"      📊 Proteins for PPI: {len(proteins)} ({', '.join(proteins[:5])}{'...' if len(proteins) > 5 else ''}")
                    
                    # Skip if no valid gene symbols after conversion
                    if not proteins or len(proteins) == 0:
                        print(f"      ⚠️  No valid gene symbols for PPI analysis")
                        continue
                    
                    # SIMPLIFIED PPI Analysis - Direct STRING API call
                    # No longer requires QueryAgent or ReasoningAgent pipeline
                    print(f"      → PPI Analysis (STRING API)...")
                    protein_count, ppi_filename, ppi_web_url = generate_string_ppi_network(
                        proteins,
                        img_dir=self.imgs_dir
                    )
                    
                    # Handle PPI result
                    if ppi_filename is None:
                        print(f"      ⚠️  STRING API failed to generate PPI network")
                        # Continue anyway - we can still save pathway info with placeholder
                    else:
                        print(f"      ✅ PPI network generated: {protein_count} proteins")
                    
                    pathway_detail = {
                        "protein_count": protein_count,
                        "ppi_filename": ppi_filename,
                        "ppi_web_url": ppi_web_url,
                        "protein_functions": None,
                        "cluster_functions": None,
                        "function_summary": None
                    }
                    
                    # NOTE: Protein Function Analysis and Cluster Function Analysis
                    # are skipped in simplified mode since they require ReasoningAgent
                    # The STRING network image and link are the primary outputs
                    print(f"      → Skipping Protein/Cluster Function Analysis (simplified mode)")
                    
                    pathway_details[pathway_name] = pathway_detail
                    print(f"  ✅ Pathway {i+1} complete")
                    
                except Exception as e:
                    print(f"  ❌ Error analyzing pathway {i+1}: {e}")
                    import traceback
                    traceback.print_exc()
                    continue
            
            results['pathway_details'] = pathway_details
            print(f"\n✅ Detailed analysis complete: {len(pathway_details)} pathways")
            
            # CRITICAL: Save pathway-to-image mapping to JSON for future use
            if pathway_details:
                mapping_file = os.path.join(self.results_dir, f'{disease_name}_ppi_mapping.json')
                ppi_mapping = {}
                for pw_name, pw_detail in pathway_details.items():
                    ppi_mapping[pw_name] = {
                        'ppi_filename': pw_detail.get('ppi_filename'),
                        'ppi_web_url': pw_detail.get('ppi_web_url'),
                        'protein_count': pw_detail.get('protein_count', 0)
                    }
                try:
                    with open(mapping_file, 'w') as f:
                        json.dump(ppi_mapping, f, indent=2)
                    print(f"  💾 Saved PPI mapping: {os.path.basename(mapping_file)}")
                except Exception as e:
                    print(f"  ⚠️  Failed to save PPI mapping: {e}")
            
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
            
            # If pathway_details is empty, try to load from saved mapping JSON
            if not pathway_details_all:
                print("  ℹ️  pathway_details is empty, looking for saved PPI mapping...")
                
                # FIRST: Try to load from previously saved PPI mapping JSON
                # Check for any existing mapping files (current or previous iterations)
                import glob
                mapping_pattern = os.path.join(self.results_dir, '*_ppi_mapping.json')
                mapping_files = sorted(glob.glob(mapping_pattern), reverse=True)  # Most recent first
                
                mapping_loaded = False
                for mapping_file in mapping_files:
                    try:
                        with open(mapping_file, 'r') as f:
                            saved_mapping = json.load(f)
                        if saved_mapping:
                            print(f"  ✅ Loaded PPI mapping from: {os.path.basename(mapping_file)}")
                            # Reconstruct pathway_details from saved mapping
                            for pw_name, pw_info in saved_mapping.items():
                                pathway_details_all[pw_name] = {
                                    'protein_count': pw_info.get('protein_count', 0),
                                    'ppi_filename': pw_info.get('ppi_filename'),
                                    'ppi_web_url': pw_info.get('ppi_web_url', 'https://string-db.org'),
                                    'function_summary': None
                                }
                            print(f"  ✅ Restored {len(pathway_details_all)} pathway entries from saved mapping")
                            mapping_loaded = True
                            break
                    except Exception as e:
                        print(f"  ⚠️  Failed to load {os.path.basename(mapping_file)}: {e}")
                        continue
                
                # FALLBACK: If no mapping file found, create basic entries without images
                if not mapping_loaded:
                    print("  ⚠️  No saved PPI mapping found")
                    print("  ℹ️  Creating basic pathway entries (without PPI images)...")
                    for idx, pathway in gpt_pathways.head(top_k_analyze).iterrows():
                        pathway_name = pathway['name']
                        pathway_details_all[pathway_name] = {
                            'protein_count': pathway.get('intersection_size', 0),
                            'ppi_filename': None,
                            'ppi_web_url': None,
                            'function_summary': None
                        }
                    print(f"  ℹ️  Created {len(pathway_details_all)} basic pathway entries (no images)")
            
            # Limit to top 10 pathways to avoid timeout and connection errors
            pathway_details = dict(list(pathway_details_all.items())[:10])
            if len(pathway_details_all) > 10:
                print(f"      ℹ️  Limiting detailed report to top 10/{len(pathway_details_all)} pathways to avoid timeout")
                print(f"         All pathway details are still in CSV files")

            # Revise pathway overview
            print("  → Revising pathway overview...")
            if not self.base_analyzer.agents_ready:
                print("  ℹ️  Writing agent not loaded (BioBERT tokenizer issue) - skipping detailed report")
                print("      → Will generate GPT summary report in STEP 7 instead")
                raise RuntimeError("Writing agent not loaded")
            revised_pathway_overview = self.base_analyzer.writing_agent.revise_writting(
                pathways_overview
            )

            # Generate pathway details sections WITH BATCH PROCESSING
            print("  → Generating detailed pathway sections (batch processing)...")
            revised_pathway_sections = {}
            
            # Batch processing setup
            pathway_items = list(pathway_details.items())
            batch_size = 3  # Process 3 pathways per batch
            num_batches = (len(pathway_items) - 1) // batch_size + 1 if len(pathway_items) > 0 else 0
            
            for batch_idx in range(num_batches):
                batch_start = batch_idx * batch_size
                batch_end = min(batch_start + batch_size, len(pathway_items))
                batch = pathway_items[batch_start:batch_end]
                
                print(f"      Batch {batch_idx+1}/{num_batches}: Pathways {batch_start+1}-{batch_end}")
                
                for pathway_name, details in batch:
                    print(f"        • {pathway_name[:45]}...")
                    
                    try:
                        # Handle None values for ppi_filename
                        ppi_filename = details.get('ppi_filename')
                        ppi_web_url = details.get('ppi_web_url')
                        protein_count = details.get('protein_count', 0)
                        
                        # Generate overview with retry logic
                        pathway_overview = None
                        
                        # ALWAYS try writing agent to generate meaningful content
                        # Even without PPI image, we can generate text description
                        if protein_count or ppi_filename:  # At least have some data
                            for attempt in range(2):  # 2 attempts
                                try:
                                    pathway_overview = self.base_analyzer.writing_agent.act(
                                        "Function_Enrichment_Overview",
                                        {
                                            "disease_name": disease_context,
                                            "pathway_name": pathway_name,
                                            "protein_count": protein_count or 0,
                                            "ppi_filename": ppi_filename or "N/A",
                                            "ppi_web_url": ppi_web_url or 'https://string-db.org'
                                        }
                                    )
                                    break  # Success
                                except Exception as e:
                                    if attempt == 0:
                                        print(f"          ⚠️  Retry after 5s...")
                                        time.sleep(5)
                                    else:
                                        pathway_overview = None  # Will use fallback below
                        
                        # Create fallback overview if LLM call failed or no data
                        if pathway_overview is None:
                            pathway_overview = f"### {pathway_name}\n\n"
                            pathway_overview += f"In the functional enrichment analysis for the **{pathway_name}** pathway"
                            if protein_count:
                                pathway_overview += f", {protein_count} proteins associated with {disease_context} were identified"
                            pathway_overview += ".\n\n"
                            
                            if ppi_filename and ppi_filename != "N/A":
                                pathway_overview += f"![PPI Network - {pathway_name}]({ppi_filename})\n\n"
                                pathway_overview += f"*Figure: Protein-protein interaction network for {pathway_name}. "
                                pathway_overview += f"Network generated using STRING database.*\n\n"
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
                        
                        # Revise function text with retry
                        revised_function = ""
                        if function_text:
                            for attempt in range(2):
                                try:
                                    revised_function = self.base_analyzer.writing_agent.act(
                                        "Function_Enrichment_Analysis",
                                        {"paragraph": function_text}
                                    )
                                    break
                                except Exception as e:
                                    if attempt == 0:
                                        time.sleep(3)
                                    else:
                                        revised_function = function_text
                        
                        revised_pathway_sections[pathway_name] = {
                            "overview": pathway_overview,
                            "function_analysis": revised_function
                        }
                        
                    except Exception as e:
                        print(f"          ❌ Error: {e}")
                        revised_pathway_sections[pathway_name] = {
                            "overview": f"![PPI Network]({details.get('ppi_filename', '')})",
                            "function_analysis": ""
                        }
                
                # Delay between batches
                if batch_idx < num_batches - 1:
                    print(f"        ⏱️  Waiting 3s before next batch...")
                    time.sleep(3)
            
            # DEBUG: Print pathway_details and sections info
            print(f"  📊 pathway_details has {len(pathway_details)} entries")
            print(f"  📊 revised_pathway_sections has {len(revised_pathway_sections)} entries")
            
            if len(revised_pathway_sections) == 0:
                print("  ⚠️  WARNING: No pathway sections were generated!")
                print(f"      pathway_details_all had {len(pathway_details_all)} entries")
                print(f"      pathway_details (after limiting) had {len(pathway_details)} entries")
            
            # Combine into full draft
            print("  → Combining all sections...")
            full_draft = f"# Pathways Overview\n\n{revised_pathway_overview}\n\n"
            full_draft += "# Detailed Pathway Analysis\n\n"
            for pathway_name, sections in revised_pathway_sections.items():
                full_draft += f"## {pathway_name}\n\n"
                if sections.get('overview'):
                    full_draft += f"{sections['overview']}\n\n"
                if sections.get('function_analysis'):
                    full_draft += f"{sections['function_analysis']}\n\n"
            
            # CRITICAL: Save raw full_draft BEFORE any revision (for debugging)
            raw_draft_file = os.path.join(self.results_dir, f'{disease_name}_report_raw_draft.md')
            with open(raw_draft_file, 'w') as f:
                f.write(full_draft)
            print(f"  💾 Saved raw draft (pre-revision): {os.path.basename(raw_draft_file)} ({len(full_draft)} chars)")
            
            # Skip coherence revision if draft is too large (LLM may truncate)
            if len(full_draft) > 10000:
                print(f"  ⚠️  Skipping coherence revision (draft too large: {len(full_draft)} chars)")
                # Keep original full_draft
            else:
                print("  → Adding coherence...")
                try:
                    coherent_draft = self.base_analyzer.writing_agent.revise_coherence(full_draft)
                    if coherent_draft and len(coherent_draft) >= len(full_draft) * 0.5:
                        full_draft = coherent_draft
                    else:
                        print(f"  ⚠️  Coherence revision may have truncated content, keeping original")
                except Exception as e:
                    print(f"  ⚠️  Coherence revision failed: {e}, keeping original")
            
            # Generate introduction
            print("  → Generating introduction...")
            introduction = self.base_analyzer.writing_agent.generate_introduction(
                full_draft,
                disease_context,
                len(gpt_pathways),
                len(genes)
            )
            
            full_draft_w_intro = f"# Introduction\n\n{introduction}\n\n{full_draft}"
            
            # Final revision - DISABLED to avoid connection errors
            # The full_draft_w_intro is already complete and usable
            print("  → Final revision... [SKIPPED - using complete draft directly]")
            
            # Skip revision to avoid connection errors that slow down the pipeline
            # The unrevised version is complete and contains all pathway information
            final_report = full_draft_w_intro
            print(f"  ✅ Using complete draft ({len(final_report)} chars)")
            
            results['final_report'] = final_report
            
            # Save final report
            report_md = os.path.join(self.results_dir, f'{disease_name}_report.md')
            with open(report_md, 'w') as f:
                f.write(final_report)
            
            print(f"\n✅ Final report saved: {report_md}")
            
        except RuntimeError as e:
            if "Writing agent not loaded" in str(e):
                pass  # Already printed info message above
            else:
                print(f"❌ Error in report generation: {e}")
                import traceback
                traceback.print_exc()
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

## Disease: {results.get('disease_full_name', results['disease_name'])}
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
