# Benchmark gene lists

`gene_lists_567.csv` contains the 567 disease–gene-list inputs used for the 24-disease pathway benchmark. Each row represents one disease and one network module. The `genes` field is a semicolon-separated list of Ensembl gene IDs from the source file's `node` column; `gene_count` counts distinct IDs in that list.

The unmodified upstream files are in `source_modules/` (one `*_modules.csv` per disease). `source_manifest.csv` maps disease abbreviations to MeSH IDs, records the number of retained lists, and provides SHA-256 checksums for the source files. The derived table repeats the source path and checksum on each row so an input can be traced back to its original file.

## Source and selection

The source files were copied from the local network expansion output at:

```text
Genetic_AI_Agent/src/utils/Network_expansion/outputs/disease_pair_expansion/{mesh_id}_modules.csv
```

The pathway analysis runner reads these files and selects rows where `passes_all_filters` is true and `cluster_walktrap` is not `-1`. It groups rows by `cluster_walktrap` within each disease and analyses modules with at least 10 rows. The exported `genes` list preserves the distinct, nonempty `node` IDs in source order. Applying this rule to the 24 included diseases yields exactly 567 lists. These IDs are the actual pathway input identifiers; they have not been converted to HGNC symbols.

For example, the Alzheimer disease input is `source_modules/D000544_modules.csv`; its retained modules appear in `gene_lists_567.csv` under `disease=AD`.

The 567 input lists are distinct from the 543 lists that produced at least one final validated pathway in a later figure-specific analysis.

## Run-output locations

`run_output_manifest_567.csv` maps every input to six relative paths in the historical two-round run tree: prediction JSON, matched-term CSV and FDR-supported CSV for each round. `benchmark_run_outputs_567.tar.gz` contains all 3,402 mapped artifacts plus the 24 run logs used for the Figure 2 metrics. The paths are relative to the repository root after extracting the archive. `benchmark_run_outputs_567_sha256.csv` provides a SHA-256 checksum and byte count for each archived file. The archive itself has SHA-256 `4e158f65738ff315160044fd8c932e5a426b8117e36ef14569fd9f79c6c5bb04`.

The archive contains the historical computational outputs needed to reconstruct Figure 2 and recalculate the manuscript's initial and refined pass rates. Some first-round matched-term CSV files reflect a later validation snapshot than the run logs; the Figure 2 builder writes a comparison audit and keeps the logged rates for manuscript statistics. It does not contain every intermediate product from the larger 781 MB local run directory. Rebuild the curated archive from that directory with `scripts/package_benchmark_outputs.py`, and validate extracted files with `scripts/verify_benchmark_artifacts.py`. See [`scripts/manuscript_figure2/README.md`](../scripts/manuscript_figure2/README.md) for the exact reproduction commands and statistical definition.
