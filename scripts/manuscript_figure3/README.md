# Main Figure 3 numerical reproduction

After the Figure 2 builder writes
`output/figure2_consistent_current/Figure2_current_metrics_24_diseases.csv`,
run:

```bash
python scripts/manuscript_figure3/reproduce_figure3.py
```

The script excludes records with `new_matched = 0`, averages gene-list rates
within disease and database, and gives each of the 24 diseases equal weight.
It verifies 28.871% initial and 39.795% refined overall rates and improvement
in 23 diseases. The 95% intervals use seed 2406 and 3,000 disease-then-list
bootstrap replicates. The output contains CSVs for the 12 Figure 3A bars, 24
Figure 3B disease pairs, and 10 Figure 3C Crohn's disease database rates,
plus a numerical PDF rendering. These intervals implement the submitted
caption's resampling description; they are not asserted to be pixel-identical
to the final editable slide.
