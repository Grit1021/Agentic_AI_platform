import os
import sys
import time
import json
import argparse
import pandas as pd

if __package__ in (None, ""):
    package_parent = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if package_parent not in sys.path:
        sys.path.insert(0, package_parent)
    __package__ = "refined"

from . import config as cfg
from .agents import BiologicalRankingAgent, StatisticalValidationAgent
from .module_loading import ensure_backend_paths
from .report import generate_pathway_summary
from .visualization import generate_category_plots, generate_rate_variation_plots


# ============================================================================
# TEE LOGGER (stdout → terminal + file)
# ============================================================================

class Tee:
    """Redirect stdout to both terminal and a log file."""

    def __init__(self, filename):
        self.terminal = sys.stdout
        self.log = open(filename, 'w')

    def write(self, message):
        self.terminal.write(message)
        self.log.write(message)
        self.log.flush()

    def flush(self):
        self.terminal.flush()
        self.log.flush()

    def close(self):
        self.log.close()


# ============================================================================
# PIPELINE ORCHESTRATOR
# ============================================================================

class PipelineOrchestrator:
    """
    Orchestrates the full pathway analysis pipeline:
      Phase 1: Module pathway collection
      Phase 2: Per-module iteration (iter 2 & 3)
      Phase 3: Drug target analysis
      Finalization: Report generation, plots, memory bank storage
    """

    def __init__(self, enable_memory_bank: bool = True):
        self.config = None
        self.framework = None
        self.memory_bank = None
        self.enable_memory_bank = enable_memory_bank
        self.memory_bank_enabled = False
        self.ag2_workflow = None
        self.interactive_agent = None
        self.query_agent_for_ranking = None
        self.biological_ranking_agent = BiologicalRankingAgent()
        self.statistical_validation_agent = StatisticalValidationAgent()

        # Results
        self.all_module_pathways = []
        self.final_module_results = []
        self.module_metadata = {}
        self.selected_modules = []
        self.modules = []
        self.aggregated_pathways = pd.DataFrame()

        # Directories
        self.phase1_dir = ""
        self.phase2_dir = ""
        self.summary_dir = ""

    def run(self, tag_suffix: str = ""):
        """
        Run the full aggregated disease analysis pipeline.

        Parameters
        ----------
        tag_suffix : str
            Optional tag to append to output directory name
        """
        # ── Step 1: Setup ──
        self._setup(tag_suffix)

        # ── Step 2: Initialize Memory Bank ──
        if self.enable_memory_bank:
            self._init_memory_bank()
        else:
            print(f"\n{'=' * 80}")
            print("MEMORY BANK DISABLED")
            print(f"{'=' * 80}")
            self.memory_bank = None
            self.memory_bank_enabled = False

        # ── Step 3: Phase 1 — Module Pathway Collection ──
        self._phase1_collect(tag_suffix)

        # ── Step 4: Phase 2 — Per-Module Iteration ──
        self._phase2_iterate()

        # ── Step 5: Aggregate Results ──
        self._aggregate()

        # ── Step 6: Phase 3 — Drug Target Analysis ──
        self._phase3_drug_targets()

        # ── Step 7: Generate Reports & Plots ──
        self._finalize()

        # ── Step 8: Memory Bank Finalization ──
        self._finalize_memory_bank()

        # ── Step 9: Cache Statistics ──
        self._print_cache_stats()

        print(f"\n{'=' * 80}")
        print(f"✅ ANALYSIS COMPLETE")
        print(f"{'=' * 80}")
        print(f"   Disease: {self.config['full_name']}")
        print(f"   Modules analyzed: {len(self.final_module_results)}")
        print(f"   Results directory: {self.summary_dir}")

    def _print_cache_stats(self):
        """Print cache hit/miss statistics for all cache layers."""
        print(f"\n{'=' * 80}")
        print("CACHE STATISTICS")
        print(f"{'=' * 80}")

        # LLM response cache
        try:
            from .llm_client import LLMClient
            temp_client = LLMClient(enable_cache=True)
            temp_client.print_cache_stats()
        except Exception:
            pass

        # PubMed cache
        try:
            from .tools.pubmed import get_pubmed_cache_stats
            pm_stats = get_pubmed_cache_stats()
            print(f"   📊 PubMed Cache: {pm_stats['hits']} hits / "
                  f"{pm_stats['misses']} misses ({pm_stats['hit_rate_pct']}% hit rate)")
        except Exception:
            pass

        # g:Profiler cache
        try:
            from .tools.gprofiler_cache import gprofiler_cache
            gp_stats = gprofiler_cache.stats
            print(f"   📊 g:Profiler Cache: {gp_stats['hits']} hits / "
                  f"{gp_stats['misses']} misses ({gp_stats['hit_rate_pct']}% hit rate)")
        except Exception:
            pass

    # ========================================================================
    # SETUP
    # ========================================================================

    def _setup(self, tag_suffix: str):
        """Initialize disease config, framework, and AG2 agents."""

        # --- Disease Config ---
        self.config = cfg.get_disease_config()
        disease_code = self.config['disease_code']
        disease_name = self.config['full_name']

        print(f"\n{'=' * 80}")
        print(f"AGGREGATED DISEASE ANALYSIS: {disease_name}")
        print(f"{'=' * 80}")
        print(f"   Disease Code: {disease_code}")
        print(f"   MeSH ID: {self.config['mesh_id']}")
        print(f"   Feedback Mode: {cfg.FEEDBACK_MODE}")

        # --- Framework ---
        backend_paths = ensure_backend_paths()
        parent_dir = backend_paths["parent_dir"]

        from .framework import RefinedIterativeGPTAgentFramework
        from .agents.hypothesis_generation_agent import (
            HypothesisGenerationAgent,
            install_refined_prompt_templates,
        )

        install_refined_prompt_templates()

        results_base = os.path.join(
            parent_dir, f"iterative_feedback_{disease_code}"
        )
        os.makedirs(results_base, exist_ok=True)

        self.query_agent_for_ranking = self._init_query_agent_for_ranking()

        self.framework = RefinedIterativeGPTAgentFramework(
            model="gpt-5.1",
            results_dir=results_base,
            max_iterations=2,
            gpt_rank_function=self.biological_ranking_agent.rank_pathways,
            disease_description=self.config['description'],
            query_agent=self.query_agent_for_ranking,
            pathway_generator_class=HypothesisGenerationAgent,
            feedback_mode=cfg.FEEDBACK_MODE,
        )
        self.framework.analyzer.ad_specific_keywords = self.config["keywords"]

        try:
            from gpt_pathway_deep_analysis_autorank_hitl import (
                GPTLedMultiAgentAnalyzer as GPTLedMultiAgentAnalyzerAutorank,
            )

            autorank_analyzer = GPTLedMultiAgentAnalyzerAutorank(
                output_dir=self.framework.results_dir,
                model="gpt-5.1",
                gpt_predictor_class=HypothesisGenerationAgent,
            )
            autorank_analyzer.ad_specific_keywords = self.config["keywords"]
            self.framework.analyzer = autorank_analyzer
            print("   ✅ Using gpt_pathway_deep_analysis_autorank_hitl analyzer")
        except Exception as e:
            print(f"   ⚠️  Autorank analyzer unavailable: {e}")

        # --- Load Gene Modules ---
        self.modules = self._load_disease_modules(
            pathway_analysis_dir=parent_dir,
            mesh_id=self.config['mesh_id'],
            disease_code=disease_code,
        )

        if not self.modules:
            raise ValueError(f"No gene modules found for {disease_code}")

        print(f"   Loaded {len(self.modules)} gene modules")

        # --- AG2 (optional) ---
        self._init_ag2(disease_name)

    def _init_query_agent_for_ranking(self):
        """Initialize a query agent compatible with the clean autorank path."""
        try:
            from pipeline import InteractiveQueryAgent, GPT5_LLM_CONFIG, AG2_AVAILABLE

            if AG2_AVAILABLE and InteractiveQueryAgent:
                agent = InteractiveQueryAgent(llm_config=GPT5_LLM_CONFIG)
                print("   ✅ QueryAgent initialized for GPT ranking")
                return agent
        except Exception as e:
            print(f"   ⚠️  QueryAgent initialization failed: {e}")

        class DirectPubMedQueryAgent:
            """Sentinel object; refined PubMed search uses Entrez directly."""

            pass

        print("   ℹ️  Using direct PubMed search fallback for GPT ranking")
        return DirectPubMedQueryAgent()

    def _load_disease_modules(self, pathway_analysis_dir: str, mesh_id: str, disease_code: str):
        """
        Load gene modules exactly like the clean script.

        The clean implementation reads Network_expansion outputs, applies the
        passes_all_filters quality gate when available, excludes cluster -1, and
        groups by cluster_walktrap.
        """
        input_dir = os.path.join(
            os.path.dirname(pathway_analysis_dir),
            "Network_expansion",
            "outputs",
            "disease_pair_expansion",
        )
        disease_file = os.path.join(input_dir, f"{mesh_id}_modules.csv")

        if not os.path.exists(disease_file):
            raise FileNotFoundError(
                f"Module file not found for {disease_code} ({mesh_id}): {disease_file}"
            )

        df = pd.read_csv(disease_file)
        has_modules = 'cluster_walktrap' in df.columns

        print(f"📊 Loaded {disease_code} data")
        print(f"   Total rows: {len(df)}")
        print(f"   Has module info: {has_modules}")

        if not has_modules:
            raise ValueError(f"No cluster_walktrap module information found in {disease_file}")

        if 'passes_all_filters' in df.columns:
            filtered_df = df[df['passes_all_filters'] == True].copy()
            print(f"   ✅ Applied passes_all_filters: {len(df)} → {len(filtered_df)} genes")
        else:
            filtered_df = df.copy()
            print("   ⚠️  Warning: passes_all_filters column not found, using all genes")

        module_df = filtered_df[filtered_df['cluster_walktrap'] != -1].copy()
        modules = list(module_df.groupby('cluster_walktrap'))
        module_sizes = module_df.groupby('cluster_walktrap').size()

        print(" 📊 Module Statistics:")
        print(f"   Total genes: {len(filtered_df)}")
        print(f"   Genes in modules: {len(module_df)}")
        print(f"   Number of modules: {len(modules)}")

        if len(module_sizes) > 0:
            print(f"   Module size range: {module_sizes.min()} - {module_sizes.max()} genes")
            print(f"   Modules >= 10 genes: {sum(module_sizes >= 10)}")
        else:
            print("   ⚠️  No modules after filtering")

        return modules

    def _init_ag2(self, disease_name: str):
        """Initialize AG2 human-in-the-loop workflow (optional)."""
        try:
            from pipeline.ag2_config import AG2Config, set_interactive_mode
            from pipeline.ag2_pathway_agents import AG2PathwayWorkflow

            set_interactive_mode(False)  # Non-interactive by default

            ag2_config = AG2Config(
                model="gpt-5.1",
                disease_name=disease_name,
                fdr_threshold=0.05,
                checkpoint_after_collection=True,
                checkpoint_after_aggregation=True,
                checkpoint_after_drug_analysis=True,
                max_iterations=self.framework.max_iterations,
            )
            self.ag2_workflow = AG2PathwayWorkflow(
                config=ag2_config, enable_human_review=True
            )
            print("✅ AG2 workflow initialized")
        except Exception as e:
            print(f"⚠️  AG2 not available: {e}")
            self.ag2_workflow = None

    # ========================================================================
    # MEMORY BANK
    # ========================================================================

    def _init_memory_bank(self):
        """Initialize PathwayMemoryBank for cross-disease learning."""
        print(f"\n{'=' * 80}")
        print("INITIALIZING MEMORY BANK")
        print(f"{'=' * 80}")

        db_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "pathway_knowledge.db",
        )

        try:
            from pathway_memory_bank import PathwayMemoryBank
            self.memory_bank = PathwayMemoryBank(db_path=db_path)

            stats = self.memory_bank.get_statistics()
            print(f"   📊 Diseases analyzed: {stats['num_diseases']}")
            print(f"   📊 Pathway experiences: {stats['num_experiences']}")
            if 'num_unique_pathways' in stats:
                print(f"   📊 Unique pathways: {stats['num_unique_pathways']}")
            print(f"\n   ℹ️  STORAGE ONLY MODE: retrieval disabled")

            self.memory_bank_enabled = True
        except Exception as e:
            print(f"   ⚠️  Memory Bank init failed: {e}")
            self.memory_bank = None
            self.memory_bank_enabled = False

    def _finalize_memory_bank(self):
        """Store disease analysis and export knowledge summaries."""
        if not self.memory_bank_enabled or self.memory_bank is None:
            return

        print(f"\n{'=' * 80}")
        print("FINALIZING MEMORY BANK")
        print(f"{'=' * 80}")

        try:
            total_pathways = sum(
                len(r.get('filtered_pathways', pd.DataFrame()))
                for r in self.final_module_results
            )

            self.memory_bank.store_disease_analysis(
                disease_id=self.config['mesh_id'],
                disease_name=self.config['full_name'],
                description=self.config['description'],
                num_modules=len(self.final_module_results),
                total_pathways=total_pathways,
                category=None,
                metadata={
                    'disease_code': self.config['disease_code'],
                    'run_timestamp': time.strftime("%Y%m%d_%H%M%S"),
                    'avg_validation_rate': sum(
                        r.get('validation_rate', 0) for r in self.final_module_results
                    ) / len(self.final_module_results) if self.final_module_results else 0,
                },
            )
            print(f"   💾 Stored disease analysis: {self.config['full_name']}")

            # Export summaries
            mb_summary = os.path.join(
                self.summary_dir,
                f"memory_bank_summary_{self.config['disease_code']}.txt"
            )
            self.memory_bank.export_knowledge_summary(mb_summary)

            network_path = os.path.join(
                self.summary_dir,
                f"disease_pathway_network_{self.config['disease_code']}.json"
            )
            self.memory_bank.export_disease_pathway_network(network_path)

            self.memory_bank.close()
            print("   ✅ Memory Bank finalized and closed")

        except Exception as e:
            import traceback
            print(f"   ⚠️  Memory Bank finalization failed: {e}")
            traceback.print_exc()

    # ========================================================================
    # PHASE 1: MODULE PATHWAY COLLECTION
    # ========================================================================

    def _phase1_collect(self, tag_suffix: str = ""):
        """Collect pathways from each gene module via g:Profiler + GPT ranking."""
        disease_code = self.config['disease_code']
        disease_name = self.config['full_name']
        disease_description = self.config['description']

        print(f"\n{'=' * 80}")
        print("PHASE 1: MODULE PATHWAY COLLECTION")
        print(f"{'=' * 80}")

        min_module_size = 10

        # Select modules
        if cfg.TEST_MODE:
            self.selected_modules = [
                (mid, mdf) for mid, mdf in self.modules
                if len(mdf) >= min_module_size and mid in cfg.TEST_MODULES
            ]
            if not self.selected_modules:
                sorted_mods = sorted(
                    [(mid, mdf) for mid, mdf in self.modules if len(mdf) >= min_module_size],
                    key=lambda x: len(x[1]), reverse=True,
                )
                self.selected_modules = sorted_mods[:2]
        else:
            self.selected_modules = [
                (mid, mdf) for mid, mdf in self.modules
                if len(mdf) >= min_module_size
            ]

        print(f" Processing {len(self.selected_modules)} modules (size >= {min_module_size})")

        # Create directories
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        aggregated_base = os.path.join(
            self.framework.base_results_dir,
            f"{disease_code}_aggregated_{timestamp}{tag_suffix}",
        )
        self.phase1_dir = os.path.join(aggregated_base, "phase1_module_collection")
        self.phase2_dir = os.path.join(aggregated_base, "phase2_module_iteration")
        os.makedirs(self.phase1_dir, exist_ok=True)
        os.makedirs(self.phase2_dir, exist_ok=True)

        # Import refined adapters
        from .pathway_collection import run_module_pathway_collection
        from .memory import store_module_pathways_in_memory

        # Collect pathways per module
        for idx, (module_id, module_genes_df) in enumerate(self.selected_modules, 1):
            genes = module_genes_df['node'].unique().tolist()

            print(f"\n{'▶' * 40}")
            print(f"MODULE {module_id} ({idx}/{len(self.selected_modules)})")
            print(f"{'▶' * 40}\n")

            module_phase2_dir = os.path.join(self.phase2_dir, f"Module_{module_id}")
            os.makedirs(module_phase2_dir, exist_ok=True)

            module_result = run_module_pathway_collection(
                genes=genes,
                module_id=module_id,
                framework=self.framework,
                disease_name=disease_name,
                gprofiler_cache=None,
                use_gpt_autorank=True,
                gpt_rank_function=self.biological_ranking_agent.rank_pathways,
                disease_description=disease_description,
                disease_code=disease_code,
                module_phase2_dir=module_phase2_dir,
                memory_context=None,
            )

            module_result = self.statistical_validation_agent.save_phase1_iter1_outputs(
                module_result=module_result,
                module_id=module_id,
                disease_code=disease_code,
                phase1_dir=self.phase1_dir,
                gpt_led_dir=self.framework.analyzer.results_dir,
            )

            # Store to Memory Bank
            if self.memory_bank_enabled and self.memory_bank is not None:
                try:
                    filtered = module_result.get('filtered_pathways', pd.DataFrame())
                    if not filtered.empty:
                        store_module_pathways_in_memory(
                            memory_bank=self.memory_bank,
                            disease_id=self.config['mesh_id'],
                            disease_name=disease_name,
                            module_id=module_id,
                            iteration=1,
                            pathways_df=filtered,
                            top_k=50,
                        )
                except Exception as e:
                    print(f"   ⚠️  Memory Bank storage failed: {e}")

            self.all_module_pathways.append(module_result)
            self.module_metadata[f"Module_{module_id}"] = {
                'module_id': module_id,
                'module_size': len(genes),
                'pathway_count': len(module_result.get('filtered_pathways', pd.DataFrame())),
                'validation_rate': module_result.get('validation_rate', 0.0),
            }

        print(f" ✅ Phase 1 complete: {len(self.all_module_pathways)} modules collected")

    # ========================================================================
    # PHASE 2: PER-MODULE ITERATION
    # ========================================================================

    def _phase2_iterate(self):
        """Run iterative refinement (iter 2 & 3) for each module."""
        disease_code = self.config['disease_code']

        print(f"\n{'=' * 80}")
        print("PHASE 2: PER-MODULE ITERATION")
        print(f"{'=' * 80}")

        for idx, module_result in enumerate(self.all_module_pathways, 1):
            module_id = module_result['module_id']
            module_size = module_result['module_size']

            print(f"\n{'▶' * 40}")
            print(f"ITERATING MODULE {module_id} ({idx}/{len(self.all_module_pathways)})")
            print(f"{'▶' * 40}")

            module_results_dir = os.path.join(self.phase2_dir, f"Module_{module_id}")
            os.makedirs(module_results_dir, exist_ok=True)
            self.framework.results_dir = module_results_dir

            # Get genes
            module_genes = []
            for m_id, m_df in self.selected_modules:
                if str(m_id) == str(module_id):
                    module_genes = m_df['node'].tolist()
                    break

            if not module_genes:
                print(f"❌ Could not find genes for Module {module_id}")
                continue

            try:
                final_result = self.framework.run_iterative_analysis_from_initial_results(
                    genes=module_genes,
                    disease_name=f"{disease_code}_Module_{module_id}",
                    initial_results=module_result,
                )

                final_filtered = final_result.get('gpt_filtered_pathways', pd.DataFrame())
                if not isinstance(final_filtered, pd.DataFrame):
                    final_filtered = pd.DataFrame()

                if 'iteration' not in final_filtered.columns or final_filtered.empty:
                    validation_details = final_result.get('validation_details', {})
                    if isinstance(validation_details, dict) and 'gpt_filtered_pathways' in validation_details:
                        fallback_filtered = validation_details['gpt_filtered_pathways']
                        if isinstance(fallback_filtered, pd.DataFrame):
                            final_filtered = fallback_filtered
                            print(f"   📝 Using pathways from validation_details: {len(final_filtered)} pathways")

                print(f"   📊 Final pathways for Module {module_id}: {len(final_filtered)} pathways")

                if not final_filtered.empty:
                    if 'module_id' not in final_filtered.columns:
                        final_filtered['module_id'] = f"Module_{module_id}"
                    if 'module_size' not in final_filtered.columns:
                        final_filtered['module_size'] = module_size

                wrapped = {
                    'module_id': module_id,
                    'module_name': f"{disease_code}_Module_{module_id}",
                    'module_size': module_size,
                    'genes': module_genes,
                    'filtered_pathways': final_filtered,
                    'gpt_prediction': final_result.get('gpt_predicted', {}),
                    'validation_rate': final_result.get('validation_rate', 0.0),
                    'user_feedback': 'APPROVE',
                    'iteration_results': final_result.get('iteration_results', []),
                }

                if not wrapped['iteration_results']:
                    wrapped['iteration_results'] = self._extract_iteration_results_from_history(final_result)

                self.final_module_results.append(wrapped)

            except Exception as e:
                print(f"❌ Iteration failed for Module {module_id}: {e}")
                import traceback
                traceback.print_exc()
                self.final_module_results.append(module_result)

        print(f" ✅ Phase 2 complete: {len(self.final_module_results)} modules iterated")

    @staticmethod
    def _extract_iteration_results_from_history(final_result: dict) -> list:
        """Recover category_stats from iteration_history for plotting/report parity."""
        iteration_history = final_result.get('iteration_history', [])
        if not iteration_history:
            return []

        iteration_results = []
        print(f"   📊 Extracting category_stats from {len(iteration_history)} iterations...")

        for idx, hist_item in enumerate(iteration_history, 1):
            if not hasattr(hist_item, 'validation_details'):
                print(f"      Iter {idx}: ❌ no validation_details attribute")
                continue

            val_details = hist_item.validation_details
            cat_stats = None

            if isinstance(val_details, dict):
                cat_stats = val_details.get('category_stats', None)
                if cat_stats is None and 'fdr' in val_details and 'fdr_total' in val_details:
                    cat_stats = val_details

            if cat_stats is not None:
                iteration_results.append({'category_stats': cat_stats})
                fdr_total = cat_stats.get('fdr_total', 'N/A') if isinstance(cat_stats, dict) else 'N/A'
                print(f"      Iter {idx}: ✅ category_stats found (FDR total: {fdr_total})")
            else:
                print(f"      Iter {idx}: ❌ category_stats NOT in validation_details")

        print(f"   📈 Collected {len(iteration_results)} iterations with category stats for plotting")
        return iteration_results

    # ========================================================================
    # AGGREGATION
    # ========================================================================

    def _aggregate(self):
        """Aggregate final pathways from latest iteration CSV files."""
        disease_code = self.config['disease_code']

        print(f"\n{'=' * 80}")
        print("AGGREGATING FINAL MODULE PATHWAYS")
        print(f"{'=' * 80}")

        module_ids = [r['module_id'] for r in self.final_module_results]

        gpt_led_dir = os.path.join(
            self.framework.base_results_dir, "gpt_led_analysis_ag2_hitl"
        )

        if os.path.exists(gpt_led_dir):
            all_csv = []
            for mid in module_ids:
                latest_iter, latest_file = 0, None
                for i in range(1, 10):
                    path = os.path.join(
                        gpt_led_dir,
                        f"{disease_code}_Module_{mid}_iter{i}_gpt_filtered_pathways.csv"
                    )
                    if os.path.exists(path):
                        latest_iter, latest_file = i, path

                if latest_file:
                    try:
                        df = pd.read_csv(latest_file)
                        df['module_id'] = f"Module_{mid}"
                        df['final_iteration'] = latest_iter
                        all_csv.append(df)
                        print(f"   ✅ Module {mid} iter{latest_iter}: {len(df)} pathways")
                    except Exception as e:
                        print(f"   ⚠️  Module {mid}: {e}")

            if all_csv:
                self.aggregated_pathways = pd.concat(all_csv, ignore_index=True)
            else:
                from .pathway_collection import aggregate_module_pathways
                self.aggregated_pathways = aggregate_module_pathways(self.final_module_results)
        else:
            from .pathway_collection import aggregate_module_pathways
            self.aggregated_pathways = aggregate_module_pathways(self.final_module_results)

        if self.aggregated_pathways.empty:
            print("❌ No pathways to aggregate - analysis stopped")
            return

        # Save
        agg_file = os.path.join(os.path.dirname(self.phase1_dir), "final_aggregated_pathways.csv")
        self.aggregated_pathways.to_csv(agg_file, index=False)
        print(f" ✅ Total aggregated: {len(self.aggregated_pathways)} pathways")

    # ========================================================================
    # PHASE 3: DRUG TARGET ANALYSIS
    # ========================================================================

    def _phase3_drug_targets(self):
        """Run drug target analysis using AG2 workflow."""
        if self.ag2_workflow is None or self.aggregated_pathways.empty:
            return

        disease_code = self.config['disease_code']

        modules_info = []
        for mod in self.final_module_results:
            if isinstance(mod, dict) and 'genes' in mod:
                pathways_df = mod.get('filtered_pathways', pd.DataFrame())
                pathway_names = []
                if hasattr(pathways_df, 'empty') and not pathways_df.empty and 'name' in pathways_df.columns:
                    pathway_names = pathways_df.head(10)['name'].tolist()

                modules_info.append({
                    'module_id': str(mod.get('module_id', 'Unknown')),
                    'genes': mod.get('genes', []),
                    'pathways': pathway_names,
                })

        drug_results = self.ag2_workflow.run_drug_target_analysis(
            self.aggregated_pathways, modules_info=modules_info
        )

        if drug_results:
            drug_file = os.path.join(
                os.path.dirname(self.phase1_dir), "drug_target_analysis.json"
            )
            with open(drug_file, 'w') as f:
                json.dump(drug_results, f, indent=2, default=str)
            print(f"💾 Drug target analysis saved: {drug_file}")

    # ========================================================================
    # FINALIZE: REPORTS & PLOTS
    # ========================================================================

    def _finalize(self):
        """Generate summary reports and visualization plots."""
        if self.aggregated_pathways.empty:
            return

        disease_name = self.config['full_name']

        # Update module metadata
        for res in self.final_module_results:
            m_id = res['module_id']
            if f"Module_{m_id}" in self.module_metadata:
                self.module_metadata[f"Module_{m_id}"]['final_pathway_count'] = len(res['filtered_pathways'])
                self.module_metadata[f"Module_{m_id}"]['final_validation_rate'] = res['validation_rate']

        # Save metadata
        meta_file = os.path.join(os.path.dirname(self.phase1_dir), "final_module_metadata.json")
        with open(meta_file, 'w') as f:
            json.dump(self.module_metadata, f, indent=2)

        # Summary report
        self.summary_dir = os.path.join(
            os.path.dirname(self.phase1_dir), "summary_iterative"
        )
        generate_pathway_summary(
            aggregated_pathways=self.aggregated_pathways,
            final_module_results=self.final_module_results,
            module_metadata=self.module_metadata,
            disease_name=disease_name,
            summary_dir=self.summary_dir,
        )

        # Plots
        print(f"\n{'=' * 80}")
        print("GENERATING VISUALIZATION PLOTS")
        print(f"{'=' * 80}")

        try:
            n_cat = generate_category_plots(self.final_module_results, self.summary_dir)
            n_rate = generate_rate_variation_plots(self.final_module_results, self.summary_dir)
            print(f"   📊 Generated {n_cat} category plots, {n_rate} rate plots")
        except Exception as e:
            print(f"   ⚠️  Plot generation failed: {e}")


# ============================================================================
# CLI ENTRY POINT
# ============================================================================

def main():
    """Command-line entry point for the refined pipeline."""
    parser = argparse.ArgumentParser(description='Run Aggregated Disease Analysis (Refined)')
    parser.add_argument('--disease', type=str, help='Disease code or name')
    parser.add_argument('--tag', type=str, help='Tag to append to output directory')
    parser.add_argument('--test', action='store_true', help='Enable test mode')
    parser.add_argument('--no-memory', action='store_true', help='Disable memory bank')
    args = parser.parse_args()

    # Apply CLI overrides
    if args.disease:
        cfg.CURRENT_DISEASE = args.disease
    if args.test:
        cfg.TEST_MODE = True
        print("⚠️  TEST MODE ENABLED (via CLI)")

    tag_suffix = f"_{args.tag}" if args.tag else ""

    # Setup logging
    run_timestamp = time.strftime("%Y%m%d_%H%M%S")
    config = cfg.get_disease_config()
    disease_code = config['disease_code']

    base_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        f"iterative_feedback_{disease_code}",
    )
    log_dir = os.path.join(base_dir, f"{disease_code}_aggregated_{run_timestamp}{tag_suffix}")
    os.makedirs(log_dir, exist_ok=True)

    log_file = os.path.join(log_dir, f"run_log_{run_timestamp}.txt")
    tee = Tee(log_file)
    sys.stdout = tee

    print(f"{'=' * 80}")
    print(f"📝 LOGGING ENABLED → {log_file}")
    print(f"{'=' * 80}\n")

    try:
        pipeline = PipelineOrchestrator(enable_memory_bank=not args.no_memory)
        pipeline.run(tag_suffix=tag_suffix)
    finally:
        try:
            from api_cost_tracker import cost_tracker as _ct
            _ct.print_summary()
        except ImportError:
            pass
        sys.stdout = tee.terminal
        tee.close()


if __name__ == "__main__":
    main()
