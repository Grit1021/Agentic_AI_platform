# Manuscript Figure 2 source

`build_figure2_consistent_current.py` is the entry point for the Figure 2 A–E reconstruction. It was adapted from the local pathway analysis source at `result/cross_disease_analysis_external/nfdr/build_figure2_consistent_current.py`. The three `generate_*.py` files in this folder are its imported helpers; the metric parser uses the local v6 fix for round-2 rows with no retained pathways. The builder requires all 567 disease–module pairs in both rounds, compares run-log candidate counts with prediction JSON, audits matched-term CSVs, and writes source inventories, audit tables, PDF, PNG and TIFF figures. The figure rates use the historical run logs because some round-1 matched-term files reflect a later snapshot; `Figure2_round1_validation_snapshot_audit.csv` records that difference without replacing the paper's logged rates.

The curated historical run outputs are in `data/benchmark_run_outputs_567.tar.gz`. The 24 upstream module CSVs are in `data/source_modules/`. Starting from a fresh clone:

```bash
python -m pip install -r scripts/manuscript_figure2/requirements.txt
tar -xzf data/benchmark_run_outputs_567.tar.gz -C .
python scripts/verify_benchmark_artifacts.py
python scripts/locate_benchmark_outputs.py
python scripts/manuscript_figure2/build_figure2_consistent_current.py
python scripts/manuscript_figure2/summarize_key_numbers.py
```

The builder writes to `output/figure2_consistent_current/` by default. Set `BENCHMARK_FIGURE2_OUTPUT_DIR` to choose another directory. `BENCHMARK_RUN_ROOT` can instead point to an extracted run tree elsewhere. The helper scripts are included for provenance; run the builder to keep all panels on the same audited source snapshot.

`summarize_key_numbers.py` implements the manuscript's aggregation: omit database rows with no newly matched term; average gene-list `nfdr_pct` within each disease and database; average the five database values within each disease; then average the 24 diseases equally. It yields **28.871% (28.9%)** for the initial prompt and **39.795% (39.8%)** for the refined prompt. The initial per-database means round to KEGG 32.8%, GO:MF 29.0%, GO:BP 28.7%, GO:CC 27.1%, and Reactome 26.8%, matching Figure 2 in the manuscript. The script checks both overall values against the paper. These calculations use the rounded rates written in the historical run logs; the audit table makes differences from later matched-term files visible.

This procedure reconstructs the Figure 2 panels and paper-reported pass rates from the historical run outputs. It does not repeat OpenAI, g:Profiler or PubMed requests or reconstruct the upstream network communities from original GWAS data. After the builder, `python scripts/manuscript_figure2/generate_pdf_figures_24.py` can render an auxiliary feedback figure from the generated metric CSV. Its layout is not the manuscript's final Figure 3.
