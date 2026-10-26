#!/usr/bin/env python3
"""Print explicitly defined Figure 2 benchmark counts and matched-unit rates."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd


REPO = Path(__file__).resolve().parents[2]


def summarize(path: Path) -> dict:
    data = pd.read_csv(path)
    keys = ["disease", "module", "iteration", "category"]
    if data.duplicated(keys).any():
        raise ValueError("Duplicate disease/module/round/category rows")
    rounds = {}
    for iteration in (1, 2):
        rows = data[data["iteration"].eq(iteration)].copy()
        pairs = rows[["disease", "module"]].drop_duplicates()
        if len(pairs) != 567 or len(rows) != 567 * 5:
            raise ValueError(f"Round {iteration}: expected 567 pairs and 2,835 category rows")
        matched = rows[rows["new_matched"].gt(0)]
        per_disease = matched.groupby("disease")["nfdr_pct"].mean()
        if len(per_disease) != 24:
            raise ValueError(f"Round {iteration}: expected 24 disease means")
        rounds[str(iteration)] = {
            "disease_module_pairs": len(pairs),
            "category_rows": len(rows),
            "categories_with_new_matches": len(matched),
            "disease_macro_mean_new_match_fdr_percent": round(float(per_disease.mean()), 3),
        }
    return {"diseases": int(data["disease"].nunique()), "rounds": rounds}


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
