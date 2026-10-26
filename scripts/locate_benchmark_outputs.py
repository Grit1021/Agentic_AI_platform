#!/usr/bin/env python3
"""Map the 567 benchmark inputs to their two-round run artifacts."""

from __future__ import annotations

import argparse
import csv
import os
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
INPUT_CSV = REPO_ROOT / "data" / "gene_lists_567.csv"
ARTIFACTS = (
    "iter1_gpt_prediction.json",
    "iter1_gpt_matched_all.csv",
    "iter1_gpt_matched_fdr_p005.csv",
    "iter2_gpt_prediction.json",
    "iter2_gpt_matched_all.csv",
    "iter2_gpt_matched_fdr_p005.csv",
)


def make_manifest(runs_root: Path) -> tuple[list[dict[str, str]], list[str]]:
    """Return paths relative to the run root, plus any missing files."""
    with INPUT_CSV.open(newline="", encoding="utf-8") as handle:
        inputs = list(csv.DictReader(handle))
    if len(inputs) != 567 or len({(r["disease"], r["module_id"]) for r in inputs}) != 567:
        raise ValueError("Expected 567 unique disease/module inputs")

    records: list[dict[str, str]] = []
    missing: list[str] = []
    for item in inputs:
        disease, module = item["disease"], item["module_id"]
        folder = Path("result") / "memory_bank_external" / f"iterative_feedback_{disease}" / "gpt_led_analysis_ag2_hitl"
        stem = f"{disease}_Module_{module}_"
        record = {
            "disease": disease,
            "mesh_id": item["mesh_id"],
            "module_id": module,
            "gene_count": item["gene_count"],
        }
        for suffix in ARTIFACTS:
            path = folder / f"{stem}{suffix}"
            column = suffix.replace(".", "_")
            record[column] = path.as_posix()
            if not (runs_root / path).is_file():
                missing.append(path.as_posix())
        records.append(record)
    return records, missing


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--runs-root", type=Path,
        default=Path(os.environ.get("BENCHMARK_RUN_ROOT", REPO_ROOT)),
        help="Pathway_analysis directory containing result/memory_bank_external",
    )
    parser.add_argument("--output", type=Path, help="Write a relative-path CSV manifest")
    args = parser.parse_args()
    records, missing = make_manifest(args.runs_root)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(records[0]), lineterminator="\n")
            writer.writeheader()
            writer.writerows(records)
    found = len(records) * len(ARTIFACTS) - len(missing)
    print(f"Inputs: {len(records)} across {len({r['disease'] for r in records})} diseases")
    print(f"Run artifacts: {found}/{len(records) * len(ARTIFACTS)} found under {args.runs_root}")
    if missing:
        print("First missing paths:")
        for path in missing[:10]:
            print(f"  {path}")
    return 1 if missing else 0


if __name__ == "__main__":
    raise SystemExit(main())
