# Manuscript Figure 2 source

`build_figure2_consistent_current.py` is the entry point for the audited Figure 2 A–E snapshot. It was adapted from the local pathway analysis source at `result/cross_disease_analysis_external/nfdr/build_figure2_consistent_current.py`. The three `generate_*.py` files in this folder are its imported helpers; the metric parser uses the local v6 fix for round-2 rows with no retained pathways. The builder requires all 567 disease–module pairs in both rounds, compares run-log candidate counts with prediction JSON, uses matched-term CSVs, and writes source inventories, audit tables, PDF, PNG and TIFF figures.

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

The `summarize_key_numbers.py` script defines its reported percentage as the mean of `nfdr_pct` across category rows with `new_matched > 0` within each disease, followed by an equal-weight mean across the 24 diseases. This archived snapshot gives 29.254% and 39.593% (rounded to 29.3% and 39.6%). The earlier README claim of 28.9% and 39.8% does not reproduce from this snapshot under that definition. The run logs contain rounded percentage fields for round 2, so keep the archived outputs and metric definition together when reporting exact values.

This procedure reproduces Figure 2 from the historical run outputs. It does not repeat OpenAI, g:Profiler or PubMed requests or reconstruct the upstream network communities from original GWAS data.
