# Audit Supplementary Figure S7

From a fresh checkout with Python 3.9, install the tested plotting versions and
run:

```bash
python -m pip install -r scripts/manuscript_s7/requirements.txt
python scripts/manuscript_s7/reproduce_s7.py
```

The script reads the four unchanged [derived metric CSVs](../../data/suppfig_s7/README.md)
and writes `output/suppfig_s7_reproduction/`:

- `Supplementary_Figure_S7_values.csv`: all 30 calculated bars, the reported
  one-decimal values, input and valid-observation counts, and reconstructed
  95% bootstrap intervals;
- `Supplementary_Figure_S7_audit.json`: cohort, calculation, and scope notes;
- `Supplementary_Figure_S7_numeric_reproduction.pdf`: grouped bar plot.

`--no-plot` omits Matplotlib and the PDF. `--output-dir PATH`, `--bootstrap N`,
and `--seed N` control the generated files and bootstrap. The default is 3,000
resamples with the original seed of 2406. NumPy is required for the original
bootstrap algorithm; Matplotlib is needed only for drawing.

All 30 reported bars are checked against the deposited metrics. The four
memory strategies and initial prompt have first-round rows for 69 inputs;
the refined control prompt has second-round rows for 62 inputs. The plotted
denominators are smaller where `new_matched = 0`. The CSVs support the
numerical Figure S7 comparison and its original error-bar calculation but do
not reconstruct raw model/service generation or memory-bank construction.
The reproduced 30 means and 60 interval endpoints were compared directly
against the original plotting function and matched to six decimal places.
