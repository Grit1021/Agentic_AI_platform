#!/usr/bin/env python3
"""Rebuild Figure 3's numerical panels from the archived 567 benchmark runs.

The submitted editable slide is deposited separately. This script exports the
data behind panels A--C and a new, clearly labelled numerical rendering. The
bootstrap follows the caption's disease -> gene-list resampling hierarchy.
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
CATEGORIES = ("GO:BP", "GO:MF", "GO:CC", "KEGG", "REAC")
SOURCE = ROOT / "output/figure2_consistent_current/Figure2_current_metrics_24_diseases.csv"


def write_csv(path: Path, rows: list[dict]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def prepare(source: Path):
    data = pd.read_csv(source)
    required = {"disease", "module", "iteration", "category", "new_matched", "nfdr_pct"}
    if not required.issubset(data.columns):
        raise ValueError(f"Missing metric columns: {sorted(required - set(data.columns))}")
    if len(data) != 567 * 5 * 2:
        raise ValueError(f"Expected 5,670 benchmark rows; found {len(data)}")
    keys = ["disease", "module", "category", "iteration"]
    if data.duplicated(keys).any() or set(data.iteration) != {1, 2}:
        raise ValueError("Benchmark keys or prompt-pass labels are invalid")
    diseases = sorted(data.disease.unique())
    if len(diseases) != 24:
        raise ValueError("Expected 24 diseases")
    arrays = {}
    for disease in diseases:
        subset = data[data.disease == disease]
        modules = sorted(subset.module.unique())
        cube = np.full((len(modules), len(CATEGORIES), 2), np.nan)
        module_idx = {module: idx for idx, module in enumerate(modules)}
        for row in subset.itertuples(index=False):
            if row.new_matched > 0:
                cube[module_idx[row.module], CATEGORIES.index(row.category), row.iteration - 1] = row.nfdr_pct
        arrays[disease] = cube
    return data, diseases, arrays


def disease_rates(cube: np.ndarray) -> np.ndarray:
    with np.errstate(invalid="ignore"):
        numerators = np.nansum(cube, axis=0)
        denominators = np.sum(np.isfinite(cube), axis=0)
        return np.divide(numerators, denominators,
                         out=np.full_like(numerators, np.nan), where=denominators > 0)


def macro_rates(diseases: list[str], arrays: dict) -> np.ndarray:
    means = np.stack([disease_rates(arrays[disease]) for disease in diseases])
    if not np.isfinite(means).all():
        raise ValueError("At least one disease/database/prompt pass has no matched terms")
    per_database = means.mean(axis=0)
    overall = means.mean(axis=1).mean(axis=0)
    return np.vstack((overall, per_database))


def bootstrap_intervals(diseases: list[str], arrays: dict,
                        repeats: int, seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    simulations = np.empty((repeats, len(CATEGORIES) + 1, 2))
    for repeat in range(repeats):
        selected = rng.integers(0, len(diseases), len(diseases))
        sampled_disease_rates = []
        for index in selected:
            cube = arrays[diseases[index]]
            draws = rng.integers(0, len(cube), len(cube))
            sampled_disease_rates.append(disease_rates(cube[draws]))
        means = np.stack(sampled_disease_rates)
        simulations[repeat, 0] = np.nanmean(means, axis=1).mean(axis=0)
        simulations[repeat, 1:] = np.nanmean(means, axis=0)
    return np.percentile(simulations, [2.5, 97.5], axis=0)


def plot(bar_rows: list[dict], disease_rows: list[dict], case_rows: list[dict],
         output: Path) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(1, 3, figsize=(15, 5), gridspec_kw={"width_ratios": [1.1, 1, 1]})
    names = ["Overall", *CATEGORIES]
    y = np.arange(len(names))
    for pass_no, offset, color, label in ((1, -0.18, "#aeb8c2", "Initial"),
                                          (2, 0.18, "#377da5", "Refined")):
        rows = [row for row in bar_rows if row["pass"] == pass_no]
        center = np.array([row["mean_percent"] for row in rows])
        lower = np.array([row["ci95_lower_percent"] for row in rows])
        upper = np.array([row["ci95_upper_percent"] for row in rows])
        axes[0].barh(y + offset, center, height=0.33, color=color, label=label)
        axes[0].errorbar(center, y + offset, xerr=[center - lower, upper - center],
                         fmt="none", ecolor="#263445", capsize=2, lw=0.8)
    axes[0].set_yticks(y, names)
    axes[0].invert_yaxis()
    axes[0].set_xlabel("Pass rate (%)")
    axes[0].legend(frameon=False)
    axes[0].set_title("A  Disease-macro rates")

    axes[1].scatter([row["initial_percent"] for row in disease_rows],
                    [row["refined_percent"] for row in disease_rows], s=24, color="#377da5")
    axes[1].plot([0, 75], [0, 75], color="#999999", lw=0.8)
    axes[1].set(xlim=(0, 75), ylim=(0, 75), xlabel="Initial pass rate (%)",
                ylabel="Refined pass rate (%)", title="B  Each point is one disease")
    for row in disease_rows:
        if row["disease"] == "TB":
            axes[1].annotate("TB", (row["initial_percent"], row["refined_percent"]),
                             xytext=(4, 4), textcoords="offset points", fontsize=7)

    categories = list(CATEGORIES)
    x = np.arange(len(categories))
    for pass_no, offset, color, label in ((1, -0.18, "#aeb8c2", "Initial"),
                                          (2, 0.18, "#377da5", "Refined")):
        rows = sorted((row for row in case_rows if row["pass"] == pass_no),
                      key=lambda row: CATEGORIES.index(row["database"]))
        axes[2].bar(x + offset, [row["pass_rate_percent"] for row in rows],
                    width=0.35, color=color, label=label)
    axes[2].set_xticks(x, categories, rotation=40, ha="right")
    axes[2].set(ylabel="Pass rate (%)", title="C  Crohn's disease, 116 genes")
    fig.tight_layout()
    fig.savefig(output, bbox_inches="tight")
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--metrics", type=Path, default=SOURCE)
    parser.add_argument("--output-dir", type=Path,
                        default=ROOT / "output/figure3_reproduction")
    parser.add_argument("--bootstrap", type=int, default=3000)
    parser.add_argument("--seed", type=int, default=2406)
    parser.add_argument("--no-plot", action="store_true")
    args = parser.parse_args()
    if args.bootstrap < 1:
        parser.error("--bootstrap must be positive")
    data, diseases, arrays = prepare(args.metrics)
    rates = macro_rates(diseases, arrays)
    if not (abs(rates[0, 0] - 28.871) < 0.001 and abs(rates[0, 1] - 39.795) < 0.001):
        raise ValueError(f"Figure 3 macro rates disagree with manuscript: {rates[0]}")
    intervals = bootstrap_intervals(diseases, arrays, args.bootstrap, args.seed)
    bar_rows = []
    for index, category in enumerate(("Overall",) + CATEGORIES):
        for prompt_pass in (1, 2):
            col = prompt_pass - 1
            bar_rows.append({"database": category, "pass": prompt_pass,
                             "mean_percent": round(float(rates[index, col]), 6),
                             "ci95_lower_percent": round(float(intervals[0, index, col]), 6),
                             "ci95_upper_percent": round(float(intervals[1, index, col]), 6)})
    disease_rows = []
    for disease in diseases:
        values = disease_rates(arrays[disease]).mean(axis=0)
        disease_rows.append({"disease": disease,
                             "initial_percent": round(float(values[0]), 6),
                             "refined_percent": round(float(values[1]), 6)})
    if sum(row["refined_percent"] > row["initial_percent"] for row in disease_rows) != 23:
        raise ValueError("Expected improvement in 23 of 24 diseases")
    case = data[(data.disease == "CD") & (data.module == 75)].copy()
    if len(case) != 10:
        raise ValueError("Crohn's disease 116-gene example was not found")
    case_rows = []
    for row in case.itertuples(index=False):
        case_rows.append({"disease": "CD", "module": 75, "database": row.category,
                          "pass": row.iteration, "new_matched": row.new_matched,
                          "pass_rate_percent": row.nfdr_pct})
    args.output_dir.mkdir(parents=True, exist_ok=True)
    write_csv(args.output_dir / "Figure3_A_macro_rates_and_bootstrap.csv", bar_rows)
    write_csv(args.output_dir / "Figure3_B_disease_rates.csv", disease_rows)
    write_csv(args.output_dir / "Figure3_C_Crohn116_rates.csv", case_rows)
    if not args.no_plot:
        plot(bar_rows, disease_rows, case_rows,
             args.output_dir / "Figure3_numerical_reproduction.pdf")
    print("Figure 3: 12 macro bars, 24 disease pairs, 10 Crohn's example rates verified")


if __name__ == "__main__":
    main()
