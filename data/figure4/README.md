# Figure 4 deposited source data

These files are copied from the JASA supplementary tables prepared on 2026-10-23.
The three XLSX files are unchanged copies of Supplementary Tables S1-S3.
The four UTF-8 CSV files are value exports of the S2 record and disease
matrix sheets and the S3 Figure 4C/D sheets; formatting and workbook README
sheets are not part of the CSV exports.

| File | Content |
| --- | --- |
| `PathwayAI_Supp_Table_S1.xlsx` | 24-disease scope and 567-list inventory. |
| `PathwayAI_Supp_Table_S2.xlsx` | 10,701 pathway-level cell-context records, broad tags, run audit, disease matrix, and global summary. |
| `PathwayAI_Supp_Table_S3.xlsx` | Disease-level detailed tag counts and the recurrent AD pathway matrix used for Figure 4C/D. |
| `Figure4_record_context_10701.csv` | S2 `Pathway_context_records_10701`. |
| `Figure4B_broad_context_matrix.csv` | S2 `Disease_context_matrix_24`. |
| `Figure4C_disease_tag_counts.csv` | S3 `Fig4C_disease_tag_counts`. |
| `Figure4D_AD_pathway_matrix.csv` | S3 `Fig4D_AD_pathway_matrix`. |

`scripts/manuscript_figure4/reproduce_figure4.py` recomputes every Figure 4B
broad-tag count and proportion from the record-level S2 table. It validates
the S3 denominators, proportions, broad tags, display selection, and AD
pathway counts, then exports the source sheets as CSV and renders numerical
versions of Figure 4B-D. S3 fine-grained cell-type tags were curated from the
free-text records and supplied as deposited derived data. The script does not
claim to regenerate every subtype assignment from raw reasoning files or the
final manuscript artwork. Figure 4A is a four-record explanatory schematic.

The 567 benchmark inputs live in `../gene_lists_567.csv`; the Figure 4
record-level dataset covers the 543 gene lists with a validated pathway. These
cell-context tags are multi-label interpretations and are not cell abundance
or independent biological validation.
