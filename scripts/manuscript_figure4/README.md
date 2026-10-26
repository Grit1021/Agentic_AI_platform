# Reproduce the Figure 4 numeric panels

From a fresh checkout with Python 3.9, install the tested analysis versions and
run:

```bash
python -m pip install -r scripts/manuscript_figure4/requirements.txt
python scripts/manuscript_figure4/reproduce_figure4.py
```

Outputs appear in `output/figure4_reproduction/`: four CSV exports, an audit
JSON file, and three PDF panels. The panels reconstruct numerical displays;
the final manuscript's visual layout and Figure 4A schematic are not claimed.
Use `--no-plots` to audit and export tables without Matplotlib. Use
`--output-dir PATH` to write elsewhere.

The script checks 10,701 records over 24 diseases, 10,689 context statements,
9,384 broad-tagged records, all 24 x 11 broad-tag counts and proportions, the
Figure 4C top-tag selections (AD 10, PD 5, T2D 5), and the 11 recurrent AD
pathways in Figure 4D. It checks S3 subtypes for internal consistency but
cannot reconstruct their original curation from S2's broad tags alone. See
[`data/figure4/README.md`](../../data/figure4/README.md) for file provenance.
