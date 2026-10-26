# Submitted main Figure 5: ASD case study

The local analysis named this ASD run `Figure6`, but the submitted manuscript
uses it as main Figure 5. The submitted PDF and editable PPTX are in
`data/manuscript_figures/submitted/`; the run-level pathway data are in
`data/figure5_asd/source_data_raw.json`. To audit the displayed data:

```bash
python scripts/manuscript_figure5/audit_asd.py
```

The script checks the 436-gene input, 60 validated pathways, per-database
counts, 60 cell-context statements, all 15 panel B pathway/P-value/overlap
rows, and the panel C neuron-projection-development pathway. It also checks
key labels in the exact submitted editable slide. The 100 generated-candidate
count appears in that slide, but the source snapshot contains the 60 validated
records rather than all 100 generated candidates. This is a source-data audit,
not a live model or g:Profiler rerun or an exact slide-layout generator.
