#!/usr/bin/env python3
"""Recalculate the manuscript's Figure 2/3 disease-macro pass rates."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd


REPO = Path(__file__).resolve().parents[2]
CATEGORIES = ("GO:BP", "GO:MF", "GO:CC", "KEGG", "REAC")
PAPER_ROUNDED_OVERALL = {1: 28.9, 2: 39.8}
PAPER_ROUNDED_INITIAL_DATABASE = {
    "GO:BP": 28.7, "GO:MF": 29.0, "GO:CC": 27.1,
    "KEGG": 32.8, "REAC": 26.8,
}


def summarize(path: Path) -> dict:
    data = pd.read_csv(path)
    keys = ["disease", "module", "iteration", "category"]
    if data.duplicated(keys).any():
        raise ValueError("Duplicate disease/module/round/category rows")
    rounds = {}
    disease_rates = {}
    for iteration in (1, 2):
        rows = data[data["iteration"].eq(iteration)].copy()
        pairs = rows[["disease", "module"]].drop_duplicates()
        if len(pairs) != 567 or len(rows) != 567 * 5:
            raise ValueError(f"Round {iteration}: expected 567 pairs and 2,835 category rows")
        matched = rows[rows["new_matched"].gt(0)].copy()
        matched["nfdr_pct"] = pd.to_numeric(matched["nfdr_pct"], errors="raise")
        # Paper: gene lists -> disease/database -> five database means per
        # disease -> equal-weight mean over 24 diseases. Zero-match rows have
        # no defined term-level denominator and are excluded.
        disease_database = matched.groupby(["disease", "category"])["nfdr_pct"].mean()
        if len(disease_database) != 24 * len(CATEGORIES):
            raise ValueError(f"Round {iteration}: missing disease/database mean")
        per_disease = disease_database.groupby(level="disease").mean()
        disease_rates[iteration] = per_disease
        overall = round(float(per_disease.mean()), 3)
        if round(overall, 1) != PAPER_ROUNDED_OVERALL[iteration]:
            raise ValueError(
                f"Round {iteration}: {overall}% disagrees with paper "
                f"{PAPER_ROUNDED_OVERALL[iteration]}%"
            )
        database_means = {
            category: round(float(disease_database.xs(category, level="category").mean()), 3)
            for category in CATEGORIES
        }
        if iteration == 1:
            for category, expected in PAPER_ROUNDED_INITIAL_DATABASE.items():
                if round(database_means[category], 1) != expected:
                    raise ValueError(f"{category}: {database_means[category]}% disagrees with paper {expected}%")
        rounds[str(iteration)] = {
            "disease_module_pairs": len(pairs),
            "category_rows": len(rows),
            "categories_with_new_matches": len(matched),
            "disease_macro_mean_new_match_fdr_percent": overall,
            "database_disease_macro_percent": database_means,
        }
    improvement = disease_rates[2] > disease_rates[1]
    if int(improvement.sum()) != 23 or improvement["TB"]:
        raise ValueError("Disease-level refinement pattern disagrees with paper")
    return {
        "diseases": int(data["disease"].nunique()),
        "rounds": rounds,
        "diseases_improved_after_feedback": int(improvement.sum()),
        "exception": "TB",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--metrics", type=Path,
        default=REPO / "output" / "figure2_consistent_current" / "Figure2_current_metrics_24_diseases.csv",
    )
    args = parser.parse_args()
    print(json.dumps(summarize(args.metrics), indent=2))


if __name__ == "__main__":
    main()
