import pandas as pd


def run_gprofiler_enrichment(genes: list, threshold: float = 1.0) -> pd.DataFrame:
    try:
        from gprofiler import GProfiler
        gp = GProfiler(return_dataframe=True)

        enrichment_results = gp.profile(
            organism='hsapiens',
            query=genes,
            sources=['GO:BP', 'GO:MF', 'GO:CC', 'KEGG', 'REAC'],
            user_threshold=threshold,
            significance_threshold_method='fdr',
            # Keep the query–term intersection so the UI can show the actual
            # input genes supporting each enriched pathway.
            no_evidences=False
        )

        if enrichment_results.empty:
            print("  No pathways from g:Profiler")
            return pd.DataFrame()

        n_total = len(enrichment_results)
        n_sig = (enrichment_results['p_value'] < 0.05).sum()
        print(f"  g:Profiler returned {n_total} pathways. Sig (p<0.05): {n_sig}")

        return enrichment_results

    except ImportError:
        print("  g:Profiler not available (gprofiler-official not installed)")
        return pd.DataFrame()
    except Exception as e:
        print(f"  g:Profiler error: {e}")
        return pd.DataFrame()
