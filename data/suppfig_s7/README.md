# Supplementary Figure S7 derived metrics

These four UTF-8 CSVs are unchanged copies of the historical memory-transfer
experiment's compact `*_nfdr_metrics.csv` exports. The source directories in
the project working archive were `result/comparison/with_ranking/`,
`with_rag/`, `with_rag_plus/`, and `with_rag_plus_user_prompt/`, respectively.
They are deposited so the 30 plotted pass-rate bars can be audited without
rerunning paid model calls or external enrichment services. The metric CSVs
are derived values rather than original model responses or full memory and
retrieval traces. The original gene-list inputs are deposited separately
below.

The 69 exact gene-list inputs are now also deposited in `gene_lists_69.csv`
with their five unchanged upstream network-community tables in
`source_modules/`. `source_manifest_5.csv` supplies disease names, MeSH IDs,
counts, relative source paths, and SHA-256 hashes. The selection rule is
`passes_all_filters = true`, `cluster_walktrap != -1`, and at least ten
distinct nonempty `node` IDs. `genes` preserves distinct Ensembl IDs in
source order, separated by semicolons. The five module counts are 2, 2, 7,
15, and 43 for CARDI, HF, INSUL, MELAN, and OBESI. Run
`verify_cold_start_inputs.py` to rebuild the table and check exact module
identity against all four metric files. The HF source is byte-identical to
the HF table in the main 567-list benchmark.

| Deposited CSV | Source group | Rows | SHA-256 |
| --- | --- | ---: | --- |
| `ranking_nfdr_metrics.csv` | initial (`control`, iteration 1), raw memory (`experimental`, iteration 1), refined (`control`, iteration 2) | 1,325 | `36df242f1c01e88eb8553561157c5bf7f139c8191c1f2feeb6938ac9736191f8` |
| `rag_nfdr_metrics.csv` | semantic RAG | 680 | `cec1ee7af4170224b9c9c3260c7582ac4d87191489c0e29b97e405e76c7b0cda` |
| `rag_plus_nfdr_metrics.csv` | RAG+ | 675 | `01f5f5386e28d110a50e24c7ef38e5e8b50e0b69625119d37ab3626171b0a63b` |
| `rag_plus_prompt_nfdr_metrics.csv` | RAG+ prompt | 665 | `d09a0cec208043a322587e58b0941f7cceeb12f8eeabcd15ffc29e27dba595ac` |

Each source contains the same 69 disease/module inputs: CARDI 2, HF 2, INSUL
7, MELAN 15, and OBESI 43. Each observed prompt round has five category
rows per input. The ranking CSV has both control and experimental rounds; the
three RAG CSVs have a single strategy each. The second round is absent for
some inputs, most notably seven of the 69 control inputs. The plotted bars also
exclude category rows where `new_matched = 0`, so their effective denominators
vary. The exact denominator for each of the 30 bars is written by the
reproduction script.

The pass-rate definition is the simple mean of `nfdr_pct` over available rows
with `new_matched > 0` for each strategy/category. This calculation matches
all 30 one-decimal bars in the submitted Supplementary Figure S7. The script
also implements the historical 3,000-draw two-level bootstrap of diseases,
then valid modules within disease, with the original NumPy seed of 2406 and
one random generator shared across all 30 bars. The algorithm was traced to
the historical `plot_memory_effect_by_category.py` (SHA-256
`1e8e2c2580028bf0f875f942d22905683ea7e4f30dbbc86f7831122caa903eaf`).
All 30 means and 60 confidence-interval endpoints matched that original
function to within the six-decimal precision of the exported audit CSV.

`historical_sources.tar.gz` contains the 25 original run logs selected by the
four historical metric generators, those four unmodified generator scripts,
and the unmodified original S7 plotting script. The per-file sizes and SHA-256
hashes are in `historical_sources_manifest.csv`. The 25 logs total 25.9 MB
before compression. A credential-pattern scan found no API keys, bearer
tokens, emails, or private keys in these selected files. Historical local
machine paths remain visible in the log text. Run
`python scripts/manuscript_s7/verify_historical_sources.py` to check archive
hashes and regenerate the four deposited CSVs byte for byte. This verifies
the run-log-to-metric stage; it does not rerun memory retrieval, model
generation, or enrichment.

`memory_bank_rebuilt.db` is an unchanged copy of the local **pathway
inventory** used to audit the manuscript's 7,182 count (SHA-256
`f0fbde2e77565463c122cad9ba02453c4dcba95d3bc0cae886f342999068bcfd`).
`memory_pathway_inventory_7182.csv` is its plain-text export (SHA-256
`fd9eb1ed36d2c79f9f909e5de0257c80c39a24784efe6b6564d0581e04fed9eb`).
Each row has `mesh_code`, `disease_name`, `module_id`, `iteration`,
`pathway_source`, `pathway_id`, `pathway_name`, and `p_value`. The unit is one
distinct validated pathway per disease (source and pathway ID distinguish
pathways), not a complete retrievable experience with full reasoning trace
and embedding. `verify_memory_inventory.py` checks the 7,182 keys against
17,231 FDR-supported rows across 24 diseases in the existing benchmark
output archive. This check passed with exact key-set equality.

Run `python scripts/manuscript_s7/reproduce_s7.py` from any location. See the
[script guide](../../scripts/manuscript_s7/README.md) for outputs and options.
