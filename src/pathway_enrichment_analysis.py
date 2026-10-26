"""
Pathway Enrichment Analysis for Disease Pair Modules

对两个疾病的network expansion结果进行pathway enrichment分析，
比较疾病间的生物学通路差异和共性。
"""

import os
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
from collections import Counter
import warnings
warnings.filterwarnings('ignore')

try:
    from gprofiler import GProfiler
    GPROFILER_AVAILABLE = True
except ImportError:
    print("⚠️  Warning: gprofiler-official not installed")
    print("   Install with: pip install gprofiler-official")
    GPROFILER_AVAILABLE = False


class PathwayEnrichmentAnalyzer:
    """
    Pathway enrichment analysis for disease pair modules.
    """

    def __init__(self, output_dir):
        self.output_dir = output_dir

        if GPROFILER_AVAILABLE:
            # Initialize with SSL/TLS configuration
            import ssl
            import urllib3

            # Try to create GProfiler with better SSL handling
            try:
                # Disable SSL warnings (only for g:Profiler connection issues)
                urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

                self.gp = GProfiler(return_dataframe=True)
                print("✅ g:Profiler initialized successfully")
            except Exception as e:
                print(f"⚠️  g:Profiler initialization warning: {e}")
                self.gp = GProfiler(return_dataframe=True)
        else:
            self.gp = None

        # Create enrichment output directory
        self.enrichment_dir = os.path.join(output_dir, 'pathway_enrichment')
        os.makedirs(self.enrichment_dir, exist_ok=True)

    def load_modules(self, disease_A_file, disease_B_file):
        """Load module data for both diseases."""
        print("\n" + "="*80)
        print("LOADING DATA")
        print("="*80)

        self.df_A = pd.read_csv(disease_A_file)
        self.df_B = pd.read_csv(disease_B_file)

        print(f"Disease A: {len(self.df_A)} total genes")
        print(f"Disease B: {len(self.df_B)} total genes")

        # Check for required columns
        required_cols = ['node', 'cluster_walktrap', 'passes_all_filters']
        for col in required_cols:
            if col not in self.df_A.columns or col not in self.df_B.columns:
                raise ValueError(f"Missing required column: {col}")

        # Count significant genes
        sig_A = (self.df_A['passes_all_filters'] == True).sum()
        sig_B = (self.df_B['passes_all_filters'] == True).sum()

        print(f"Disease A: {sig_A} genes in significant modules")
        print(f"Disease B: {sig_B} genes in significant modules")

    def get_significant_genes(self, df):
        """Extract genes from significant modules."""
        sig_genes = df[df['passes_all_filters'] == True]['node'].unique()
        return sig_genes.tolist()

    def enrich_geneset(self, genes, name, sources=['GO:BP', 'KEGG', 'REAC'], max_retries=3):
        """
        Run g:Profiler enrichment for a gene set with retry logic.

        Parameters:
        -----------
        genes : list
            List of gene symbols
        name : str
            Name of the gene set
        sources : list
            Data sources to query
        max_retries : int
            Maximum number of retry attempts (default: 3)
        """
        import time

        if not GPROFILER_AVAILABLE:
            print(f"⚠️  Skipping enrichment for {name} (gprofiler not available)")
            return pd.DataFrame()

        if len(genes) == 0:
            print(f"⚠️  Warning: No genes for {name}")
            return pd.DataFrame()

        print(f"  Enriching {name}: {len(genes)} genes...", end=" ")

        # Retry logic with exponential backoff
        for attempt in range(max_retries):
            try:
                enrichment = self.gp.profile(
                    organism='hsapiens',
                    query=genes,
                    sources=sources,
                    user_threshold=0.05,
                    significance_threshold_method='fdr'
                )

                if enrichment is not None and len(enrichment) > 0:
                    enrichment['geneset'] = name
                    enrichment['geneset_size'] = len(genes)
                    print(f"✅ {len(enrichment)} significant terms")
                    return enrichment
                else:
                    print("⚪ No significant enrichment")
                    return pd.DataFrame()

            except Exception as e:
                error_msg = str(e).lower()
                # Check if it's a temporary server error
                is_temporary = any(keyword in error_msg for keyword in [
                    'temporarily unavailable', 'solr', '500', 'timeout',
                    'connection', 'server error', 'service unavailable'
                ])

                if is_temporary and attempt < max_retries - 1:
                    wait_time = (2 ** attempt) * 5  # Exponential backoff: 5s, 10s, 20s
                    print(f"\n  ⚠️  g:Profiler temporary error (attempt {attempt + 1}/{max_retries}): {e}")
                    print(f"  ⏳ Retrying in {wait_time}s...")
                    time.sleep(wait_time)
                else:
                    # Final attempt failed or non-temporary error
                    print(f"\n  ❌ Error after {attempt + 1} attempts: {e}")
                    return pd.DataFrame()

        # Should not reach here, but just in case
        print(f"\n  ❌ Failed after {max_retries} attempts")
        return pd.DataFrame()

    def enrich_geneset_full(self, genes, name, sources=['GO:BP', 'GO:MF', 'GO:CC', 'KEGG', 'REAC'], max_retries=3):
        """
        Run g:Profiler enrichment for a gene set - FULL VERSION with retry logic and caching.

        Returns ALL enrichment results without significance filtering.
        Useful for matching with GPT predictions that might not be statistically significant.

        Parameters:
        -----------
        genes : list
            List of gene symbols
        name : str
            Name of the gene set
        sources : list
            Data sources to query (default: all 5 channels)
        max_retries : int
            Maximum number of retry attempts (default: 3)

        Returns:
        --------
        pd.DataFrame : All enrichment results (no p-value filtering)
        """
        import time
        import hashlib
        import json

        if not GPROFILER_AVAILABLE:
            print(f"⚠️  Skipping enrichment for {name} (gprofiler not available)")
            return pd.DataFrame()

        if len(genes) == 0:
            print(f"⚠️  Warning: No genes for {name}")
            return pd.DataFrame()



        print(f"  Enriching {name}: {len(genes)} genes (FULL - no threshold)...", end=" ")

        # Retry logic with exponential backoff
        for attempt in range(max_retries):
            try:
                enrichment = self.gp.profile(
                    organism='hsapiens',
                    query=genes,
                    sources=sources,
                    user_threshold=1.0,  # No filtering - return all results
                    significance_threshold_method='fdr',
                    no_evidences=False
                )

                if enrichment is not None and len(enrichment) > 0:
                    enrichment['geneset'] = name
                    enrichment['geneset_size'] = len(genes)

                    # Calculate nominal p-values using hypergeometric test
                    from scipy.stats import hypergeom

                    def calculate_nominal_pvalue(row):
                        """
                        Calculate nominal (uncorrected) p-value using hypergeometric test.

                        Hypergeometric test formula:
                        P(X >= k) where:
                        - M = effective_domain_size (total genes in background)
                        - n = term_size (genes in this pathway)
                        - N = query_size (genes in your query)
                        - k = intersection_size (overlap between query and pathway)
                        """
                        M = row['effective_domain_size']
                        n = row['term_size']
                        N = row['query_size']
                        k = row['intersection_size']

                        # hypergeom.sf(k-1, M, n, N) = P(X >= k)
                        p_nominal = hypergeom.sf(k - 1, M, n, N)
                        return p_nominal

                    enrichment['p_nominal'] = enrichment.apply(calculate_nominal_pvalue, axis=1)

                    # Calculate overall statistics
                    total_count = len(enrichment)

                    # Count based on FDR-adjusted p-value
                    fdr_significant_count = (enrichment['p_value'] < 0.05).sum()
                    fdr_not_significant_count = total_count - fdr_significant_count

                    # Count based on nominal p-value
                    nominal_significant_count = (enrichment['p_nominal'] < 0.05).sum()

                    # Print overall statistics
                    print(f"✅ {total_count} total terms")
                    print(f"   - FDR p<0.05: {fdr_significant_count}, p≥0.05: {fdr_not_significant_count}")
                    print(f"   - Nominal p<0.05: {nominal_significant_count}")

                    # Print statistics by source/category
                    if 'source' in enrichment.columns:
                        print(f"\n   📊 Breakdown by Category:")
                        for source in sorted(enrichment['source'].unique()):
                            source_df = enrichment[enrichment['source'] == source]
                            source_total = len(source_df)
                            source_fdr_sig = (source_df['p_value'] < 0.05).sum()
                            source_nominal_sig = (source_df['p_nominal'] < 0.05).sum()

                            # Get effective_domain_size (background N for hypergeometric test)
                            # This should be the same for all terms in this category
                            if 'effective_domain_size' in source_df.columns:
                                domain_size = source_df['effective_domain_size'].iloc[0]
                                domain_info = f", N={domain_size:,d}"
                            else:
                                domain_info = ""

                            print(f"   • {source:8s}: {source_total:4d} total, "
                                  f"FDR<0.05: {source_fdr_sig:3d}, "
                                  f"Nominal<0.05: {source_nominal_sig:3d}{domain_info}")

                    print(f"   - Columns: 'p_value' (FDR-adjusted), 'p_nominal' (uncorrected)")

                    return enrichment
                else:
                    print("⚪ No enrichment results")
                    return pd.DataFrame()

            except Exception as e:
                error_msg = str(e).lower()

                # Check if it's an SSL/TLS error
                is_ssl_error = any(keyword in error_msg for keyword in [
                    'ssl', 'tls', 'certificate', 'handshake', 'eof occurred'
                ])

                # Check if it's a temporary server error (500, SOLR, timeout, etc.)
                is_temporary = any(keyword in error_msg for keyword in [
                    'temporarily unavailable', 'solr', '500', 'timeout',
                    'connection', 'server error', 'service unavailable'
                ])

                if (is_ssl_error or is_temporary) and attempt < max_retries - 1:
                    wait_time = (2 ** attempt) * 5  # Exponential backoff: 5s, 10s, 20s

                    if is_ssl_error:
                        print(f"\n  ⚠️  SSL/TLS connection error (attempt {attempt + 1}/{max_retries})")
                        print(f"     Error: {str(e)[:100]}")
                        print(f"  💡 Tip: This may be due to network/firewall issues or SSL certificate problems")
                    else:
                        print(f"\n  ⚠️  g:Profiler temporary error (attempt {attempt + 1}/{max_retries}): {e}")

                    print(f"  ⏳ Retrying in {wait_time}s...")
                    time.sleep(wait_time)
                else:
                    # Final attempt failed or non-temporary error
                    print(f"\n  ❌ Error after {attempt + 1} attempts: {e}")

                    if is_ssl_error:
                        print(f"\n  🔧 SSL/TLS Troubleshooting:")
                        print(f"     1. Check your internet connection")
                        print(f"     2. Try updating SSL certificates: pip install --upgrade certifi")
                        print(f"     3. Check if a firewall/proxy is blocking the connection")
                        print(f"     4. Try again later (g:Profiler server may be temporarily down)")

                    return pd.DataFrame()

        # Should not reach here, but just in case
        print(f"\n  ❌ Failed after {max_retries} attempts")
        return pd.DataFrame()


    def enrich_by_module(self, df, disease_name, min_module_size=10):
        """
        Enrich each significant module separately.
        """
        results = []

        # Get significant modules
        sig_data = df[df['passes_all_filters'] == True]
        sig_modules = sig_data['cluster_walktrap'].unique()

        print(f"\n  Processing {len(sig_modules)} significant modules...")

        for module_id in sig_modules:
            module_df = df[df['cluster_walktrap'] == module_id]
            module_genes = module_df['node'].tolist()

            if len(module_genes) < min_module_size:
                continue

            # Module metadata
            module_seeds = module_df['is_seed'].sum() if 'is_seed' in module_df.columns else 0

            enrichment = self.enrich_geneset(
                genes=module_genes,
                name=f"{disease_name}_M{module_id}"
            )

            if len(enrichment) > 0:
                enrichment['disease'] = disease_name
                enrichment['module_id'] = module_id
                enrichment['module_size'] = len(module_genes)
                enrichment['module_seeds'] = module_seeds
                results.append(enrichment)

        if results:
            return pd.concat(results, ignore_index=True)
        else:
            return pd.DataFrame()

    def run_comprehensive_analysis(self, disease_A_name='Disease_A',
                                   disease_B_name='Disease_B'):
        """
        Run comprehensive pathway enrichment analysis.
        """
        results = {}

        # 1. Disease-level enrichment
        print("\n" + "="*80)
        print("1. DISEASE-LEVEL ENRICHMENT")
        print("="*80)

        genes_A = self.get_significant_genes(self.df_A)
        genes_B = self.get_significant_genes(self.df_B)

        print(f"Disease A significant genes: {len(genes_A)}")
        print(f"Disease B significant genes: {len(genes_B)}")

        results['disease_A'] = self.enrich_geneset(genes_A, disease_A_name)
        results['disease_B'] = self.enrich_geneset(genes_B, disease_B_name)

        # 2. Shared genes enrichment
        print("\n" + "="*80)
        print("2. SHARED GENES ENRICHMENT")
        print("="*80)

        shared_genes = list(set(genes_A) & set(genes_B))
        print(f"Shared genes: {len(shared_genes)}")

        results['shared'] = self.enrich_geneset(shared_genes, 'Shared_Genes')

        # 3. Disease-specific genes
        print("\n" + "="*80)
        print("3. DISEASE-SPECIFIC GENES ENRICHMENT")
        print("="*80)

        A_specific = list(set(genes_A) - set(genes_B))
        B_specific = list(set(genes_B) - set(genes_A))

        print(f"{disease_A_name} specific genes: {len(A_specific)}")
        print(f"{disease_B_name} specific genes: {len(B_specific)}")

        results['A_specific'] = self.enrich_geneset(A_specific, f'{disease_A_name}_Specific')
        results['B_specific'] = self.enrich_geneset(B_specific, f'{disease_B_name}_Specific')

        # 4. Module-level enrichment
        print("\n" + "="*80)
        print("4. MODULE-LEVEL ENRICHMENT")
        print("="*80)

        print(f"\n{disease_A_name}:")
        results['modules_A'] = self.enrich_by_module(self.df_A, disease_A_name)

        print(f"\n{disease_B_name}:")
        results['modules_B'] = self.enrich_by_module(self.df_B, disease_B_name)

        return results

    def save_results(self, results, disease_A_name, disease_B_name):
        """Save enrichment results to CSV files."""
        print("\n" + "="*80)
        print("SAVING RESULTS")
        print("="*80)

        saved_files = []

        for key, df in results.items():
            if df is not None and len(df) > 0:
                output_file = os.path.join(
                    self.enrichment_dir,
                    f'enrichment_{key}.csv'
                )
                df.to_csv(output_file, index=False)
                print(f"✅ Saved: {os.path.basename(output_file)} ({len(df)} terms)")
                saved_files.append(output_file)
            else:
                print(f"⚪ Skipped: enrichment_{key}.csv (no data)")

        return saved_files

    def compare_pathways(self, results):
        """
        Compare pathways between two diseases.
        """
        print("\n" + "="*80)
        print("PATHWAY COMPARISON")
        print("="*80)

        enrichment_A = results['disease_A']
        enrichment_B = results['disease_B']

        if len(enrichment_A) == 0 or len(enrichment_B) == 0:
            print("⚠️  Warning: One or both diseases have no enrichment results")
            return None

        # Get pathway IDs
        pathways_A = set(enrichment_A['native'].tolist())
        pathways_B = set(enrichment_B['native'].tolist())

        # Find overlaps
        common = pathways_A & pathways_B
        A_only = pathways_A - pathways_B
        B_only = pathways_B - pathways_A

        print(f"\nDisease A pathways: {len(pathways_A)}")
        print(f"Disease B pathways: {len(pathways_B)}")
        print(f"Common pathways: {len(common)} ({len(common)/max(len(pathways_A), 1)*100:.1f}% of A)")
        print(f"A-specific pathways: {len(A_only)}")
        print(f"B-specific pathways: {len(B_only)}")

        # Top common pathways
        if common:
            print("\n📊 Top 10 Common Pathways:")
            common_df_A = enrichment_A[enrichment_A['native'].isin(common)].sort_values('p_value')
            for i, (_, row) in enumerate(common_df_A.head(10).iterrows(), 1):
                print(f"  {i}. {row['name'][:70]}")
                print(f"     p={row['p_value']:.2e}, source={row['source']}")

        # Save comparison
        comparison_file = os.path.join(self.enrichment_dir, 'pathway_comparison.txt')
        with open(comparison_file, 'w') as f:
            f.write("PATHWAY COMPARISON SUMMARY\n")
            f.write("="*80 + "\n\n")
            f.write(f"Disease A pathways: {len(pathways_A)}\n")
            f.write(f"Disease B pathways: {len(pathways_B)}\n")
            f.write(f"Common pathways: {len(common)}\n")
            f.write(f"A-specific: {len(A_only)}\n")
            f.write(f"B-specific: {len(B_only)}\n\n")

            if common:
                f.write("TOP COMMON PATHWAYS:\n")
                f.write("-"*80 + "\n")
                for i, (_, row) in enumerate(common_df_A.head(20).iterrows(), 1):
                    f.write(f"{i}. {row['name']}\n")
                    f.write(f"   ID: {row['native']}, p={row['p_value']:.2e}\n\n")

        print(f"\n✅ Saved: {os.path.basename(comparison_file)}")

        return {
            'common': common,
            'A_specific': A_only,
            'B_specific': B_only
        }

    def visualize_enrichment(self, results, disease_A_name, disease_B_name):
        """
        Create visualization of enrichment results.
        """
        print("\n" + "="*80)
        print("CREATING VISUALIZATIONS")
        print("="*80)

        fig = plt.figure(figsize=(18, 12))

        # 1. Number of enriched terms per geneset
        ax1 = plt.subplot(2, 3, 1)
        data = {
            disease_A_name: len(results['disease_A']),
            disease_B_name: len(results['disease_B']),
            'Shared': len(results['shared']),
            f'{disease_A_name}\nSpecific': len(results['A_specific']),
            f'{disease_B_name}\nSpecific': len(results['B_specific'])
        }
        bars = ax1.bar(range(len(data)), list(data.values()), color=['#3498db', '#e74c3c', '#2ecc71', '#9b59b6', '#f39c12'])
        ax1.set_xticks(range(len(data)))
        ax1.set_xticklabels(data.keys(), rotation=45, ha='right')
        ax1.set_ylabel('Number of Enriched Terms', fontsize=12)
        ax1.set_title('Pathway Enrichment Summary', fontsize=14, fontweight='bold')
        ax1.grid(axis='y', alpha=0.3)

        # Add value labels on bars
        for bar in bars:
            height = bar.get_height()
            if height > 0:
                ax1.text(bar.get_x() + bar.get_width()/2., height,
                        f'{int(height)}',
                        ha='center', va='bottom', fontsize=10)

        # 2. Top pathways for Disease A
        ax2 = plt.subplot(2, 3, 2)
        if len(results['disease_A']) > 0:
            top_A = results['disease_A'].sort_values('p_value').head(15)
            y_pos = range(len(top_A))
            ax2.barh(y_pos, -np.log10(top_A['p_value']), color='#3498db', alpha=0.7)
            ax2.set_yticks(y_pos)
            ax2.set_yticklabels([name[:50] + '...' if len(name) > 50 else name
                                 for name in top_A['name']], fontsize=8)
            ax2.set_xlabel('-log10(p-value)', fontsize=11)
            ax2.set_title(f'Top Pathways: {disease_A_name}', fontsize=13, fontweight='bold')
            ax2.invert_yaxis()
            ax2.grid(axis='x', alpha=0.3)
        else:
            ax2.text(0.5, 0.5, 'No enrichment data',
                    ha='center', va='center', transform=ax2.transAxes)

        # 3. Top pathways for Disease B
        ax3 = plt.subplot(2, 3, 3)
        if len(results['disease_B']) > 0:
            top_B = results['disease_B'].sort_values('p_value').head(15)
            y_pos = range(len(top_B))
            ax3.barh(y_pos, -np.log10(top_B['p_value']), color='#e74c3c', alpha=0.7)
            ax3.set_yticks(y_pos)
            ax3.set_yticklabels([name[:50] + '...' if len(name) > 50 else name
                                 for name in top_B['name']], fontsize=8)
            ax3.set_xlabel('-log10(p-value)', fontsize=11)
            ax3.set_title(f'Top Pathways: {disease_B_name}', fontsize=13, fontweight='bold')
            ax3.invert_yaxis()
            ax3.grid(axis='x', alpha=0.3)
        else:
            ax3.text(0.5, 0.5, 'No enrichment data',
                    ha='center', va='center', transform=ax3.transAxes)

        # 4. Pathway source distribution
        ax4 = plt.subplot(2, 3, 4)
        all_enrichments = []
        if len(results['disease_A']) > 0:
            all_enrichments.append(results['disease_A'].assign(disease=disease_A_name))
        if len(results['disease_B']) > 0:
            all_enrichments.append(results['disease_B'].assign(disease=disease_B_name))

        if all_enrichments:
            combined = pd.concat(all_enrichments)
            source_counts = combined.groupby(['disease', 'source']).size().unstack(fill_value=0)
            source_counts.plot(kind='bar', ax=ax4, stacked=True,
                             color=['#3498db', '#e74c3c', '#2ecc71'])
            ax4.set_ylabel('Number of Terms', fontsize=11)
            ax4.set_xlabel('Disease', fontsize=11)
            ax4.set_title('Pathway Source Distribution', fontsize=13, fontweight='bold')
            ax4.legend(title='Source', bbox_to_anchor=(1.05, 1), loc='upper left')
            ax4.tick_params(axis='x', rotation=45)
            ax4.grid(axis='y', alpha=0.3)
        else:
            ax4.text(0.5, 0.5, 'No enrichment data',
                    ha='center', va='center', transform=ax4.transAxes)

        # 5. Top shared pathways
        ax5 = plt.subplot(2, 3, 5)
        if len(results['shared']) > 0:
            top_shared = results['shared'].sort_values('p_value').head(15)
            y_pos = range(len(top_shared))
            ax5.barh(y_pos, -np.log10(top_shared['p_value']), color='#2ecc71', alpha=0.7)
            ax5.set_yticks(y_pos)
            ax5.set_yticklabels([name[:50] + '...' if len(name) > 50 else name
                                 for name in top_shared['name']], fontsize=8)
            ax5.set_xlabel('-log10(p-value)', fontsize=11)
            ax5.set_title('Top Shared Gene Pathways', fontsize=13, fontweight='bold')
            ax5.invert_yaxis()
            ax5.grid(axis='x', alpha=0.3)
        else:
            ax5.text(0.5, 0.5, 'No shared enrichment',
                    ha='center', va='center', transform=ax5.transAxes)

        # 6. Module count comparison
        ax6 = plt.subplot(2, 3, 6)
        if len(results['modules_A']) > 0 and len(results['modules_B']) > 0:
            module_stats = pd.DataFrame({
                'Disease A': [results['modules_A']['module_id'].nunique(),
                             len(results['modules_A'])],
                'Disease B': [results['modules_B']['module_id'].nunique(),
                             len(results['modules_B'])]
            }, index=['Enriched\nModules', 'Total\nPathways'])

            module_stats.plot(kind='bar', ax=ax6, color=['#3498db', '#e74c3c'])
            ax6.set_ylabel('Count', fontsize=11)
            ax6.set_title('Module-Level Enrichment', fontsize=13, fontweight='bold')
            ax6.legend(title='Disease')
            ax6.tick_params(axis='x', rotation=0)
            ax6.grid(axis='y', alpha=0.3)
        else:
            ax6.text(0.5, 0.5, 'No module enrichment data',
                    ha='center', va='center', transform=ax6.transAxes)

        plt.tight_layout()

        # Save
        viz_file = os.path.join(self.enrichment_dir, 'enrichment_overview.png')
        plt.savefig(viz_file, dpi=300, bbox_inches='tight')
        plt.close()

        print(f"✅ Saved: {os.path.basename(viz_file)}")
