# Submitted-figure provenance (2026-10-26 archive)

`submitted/` preserves the five main figures as final PDF plus editable PPTX,
and Supplementary Figures S1--S7 as the image assets used by the submitted
supplementary document. `source_tables/` holds the newly reconstructed Figure
3 and S2/S3/S4/S6 numerical tables. `SHA256SUMS.csv` fixes the file versions. Run
`python scripts/verify_manuscript_figure_archive.py` to verify them.

The source project used the filename `Figure6_ASD...` for the ASD case study,
but the submitted manuscript places that image as **main Figure 5**. An older
local file called `Figure5_2026_0712` depicts the six-strategy memory result;
that result is **Supplementary Figure S7** in the submitted manuscript. This
archive follows submitted figure numbers.

| Submitted figure | Deposited computation/source | What is reproducible offline |
| --- | --- | --- |
| Main 1 | Final editable slide; framework code in repository | Diagram content and editable artwork; no single exact slide-generation script was found. |
| Main 2 | 567 inputs, 3,426 historical files, Figure 2 builder | Source statistics and numerical plots; final slide is preserved. |
| Main 3 | Same historical metrics; `scripts/manuscript_figure3/reproduce_figure3.py` | 12 disease-macro bars, 24 paired disease points, Crohn's 116-gene example, and a declared two-level bootstrap. The numerical plot is newly rendered and may differ from final slide geometry. |
| Main 4 | S2's 10,701 records, S3 source tables, Figure 4 auditor | Broad cell-context matrix exactly recalculated; fine tag totals audited from S3. The original fine-tag curation is not recovered. |
| Main 5 (ASD) | `data/figure5_asd/source_data_raw.json`, top-15 CSV, final editable slide | 436 input genes, 60 validated pathways, five database counts, 60 cell-context statements, panel B rankings and panel C focal-pathway statistics audited. The full live run's 100 generated candidates and API/model traces are not deposited. |
| S1 | Final PNG | Explanatory schematic and its printed counts are preserved; exact generator was not found. |
| S2 | S3 disease-level tag-count table | All 25 displayed global cell-type tag counts reconstructed by summing per-disease counts. |
| S3 | S3 disease-level tag-count table | Top eight or fewer available tags per disease, for all 24 diseases, recalculated. |
| S4 | S2 pathway-specific Cell Context text | All 20 printed tissue-context counts independently reconstructed by explicit regex rules. |
| S5 | S3 contains the 11 Figure 4D pathways; final PNG has 23 | Final artwork preserved. The other 12 pathways' original fine-grained cell-type assignments and original curation code were not found. |
| S6 | S2 pathway-specific Cell Context text | All 23 recurrent AD pathways and seven displayed tissue-context tags reconstructed by explicit regex rules; three distinctive rows are asserted in code. |
| S7 | Five-disease metric CSVs, 25 source logs, historical parsers | All 30 bars and 60 bootstrap interval endpoints reproduced; original retrieval and model-call traces remain unavailable. |

The S2/S3 and S4/S6 scripts are in `scripts/manuscript_suppfig_s2_s3/` and
`scripts/manuscript_suppfig_s4_s6/`. They write CSV source tables and new PDF
renderings to `output/`. S4/S6 use a documented text-tag reconstruction,
not a claimed copy of the original tag-curation code. Supplementary images
are the exact final images; the newly rendered PDFs can differ in layout.

The 10 missing Figure 4 historical reasoning Markdown files and Figure S7
live retrieval/model traces remain separately documented in the relevant
source manifests and READMEs. They have not been replaced by older runs.
