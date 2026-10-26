# Manuscript Figure 2 source

`build_figure2_consistent_current.py` is the entry point for the audited Figure 2 A–E snapshot. It was adapted from the local pathway analysis source at `result/cross_disease_analysis_external/nfdr/build_figure2_consistent_current.py`. The three other Python files in this folder are its imported helpers. The builder checks coverage of all 567 disease–module pairs, compares run-log candidate counts with prediction JSON, uses current matched-term CSVs, and writes source inventories, audit tables, PDF, PNG and TIFF figures.

The complete historical run outputs are required and are not stored in this repository. Supply a local `Pathway_analysis` directory that contains `result/memory_bank_external/iterative_feedback_*`. The 24 upstream module CSVs are supplied in this repository's `data/source_modules/`.

```bash
python -m pip install numpy pandas matplotlib scipy pillow PyPDF2
BENCHMARK_RUN_ROOT=/path/to/Pathway_analysis \
  python scripts/locate_benchmark_outputs.py \
  --runs-root /path/to/Pathway_analysis
BENCHMARK_RUN_ROOT=/path/to/Pathway_analysis \
  python scripts/manuscript_figure2/build_figure2_consistent_current.py
```

The builder writes to `output/figure2_consistent_current/` by default. Set `BENCHMARK_FIGURE2_OUTPUT_DIR` to choose another directory. The helper scripts are included for provenance; run the builder to keep all panels on the same audited source snapshot.
