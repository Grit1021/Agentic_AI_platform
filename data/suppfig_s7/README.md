# Supplementary Figure S7 derived metrics

These four UTF-8 CSVs are unchanged copies of the historical memory-transfer
experiment's compact `*_nfdr_metrics.csv` exports. The source directories in
the project working archive were `result/comparison/with_ranking/`,
`with_rag/`, `with_rag_plus/`, and `with_rag_plus_user_prompt/`, respectively.
They are deposited so the 30 plotted pass-rate bars can be audited without
rerunning paid model calls or external enrichment services. They are derived
metrics, not the original model responses, 7,182-entry memory bank, retrieval
traces, gene-list inputs, or enrichment result files.

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

Run `python scripts/manuscript_s7/reproduce_s7.py` from any location. See the
[script guide](../../scripts/manuscript_s7/README.md) for outputs and options.
