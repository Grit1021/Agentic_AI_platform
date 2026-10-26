#!/usr/bin/env python3
"""Audit Figure 4 source workbooks and rebuild numeric panels B--D.

This uses the deposited 10,701 record-level interpretations. The fine-grained
tags in Supplementary Table S3 are deposited source data: their original
manual/regex curation cannot be inferred completely from the broad tags in S2.
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter, defaultdict
from pathlib import Path

from openpyxl import load_workbook


ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data" / "figure4"
BROAD_TAGS = (
    "intestinal epithelial cells", "beta cells", "cardiomyocytes",
    "hepatocytes", "smooth muscle cells", "fibroblasts", "glial cells",
    "neurons", "epithelial cells", "endothelial cells", "immune cells",
)


def sheet_rows(path: Path, name: str) -> list[dict]:
    workbook = load_workbook(path, read_only=True, data_only=True)
    try:
        values = workbook[name].values
        columns = next(values)
        return [dict(zip(columns, row)) for row in values]
    finally:
        workbook.close()


def write_csv(path: Path, rows: list[dict]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def check(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def audit(s1_scope: list[dict], s1_inventory: list[dict], s2: list[dict],
          matrix: list[dict], c_rows: list[dict], d_rows: list[dict]) -> dict:
    with (ROOT / "data" / "gene_lists_567.csv").open(newline="", encoding="utf-8") as handle:
        benchmark_inputs = list(csv.DictReader(handle))
    inventory_keys = {(row["disease_abbreviation"], str(row["gene_list_number"]))
                      for row in s1_inventory}
    input_keys = {(row["disease"], row["module_id"]) for row in benchmark_inputs}
    check(len(s1_inventory) == len(inventory_keys) == len(input_keys) == 567,
          "S1 or benchmark input inventory does not contain 567 unique pairs")
    check(inventory_keys == input_keys, "S1 and benchmark input inventories differ")
    check(len(s2) == 10701, f"Expected 10,701 S2 records; found {len(s2)}")
    context_keys = {(row["disease"], str(row["gene_list_id"])) for row in s2}
    check(len(context_keys) == 543 and context_keys.issubset(input_keys),
          "S2 does not map to the expected 543 benchmark inputs")
    by_disease = Counter(row["disease"] for row in s2)
    check(len(by_disease) == 24, "Expected 24 diseases")
    scope_by_disease = {row["disease_abbreviation"]: row for row in s1_scope}
    check(len(scope_by_disease) == 24, "Expected 24 S1 disease rows")
    for disease in by_disease:
        scope = scope_by_disease[disease]
        check(scope["n_benchmark_gene_lists"] ==
              sum(key[0] == disease for key in input_keys),
              f"S1 benchmark count mismatch for {disease}")
        check(scope["n_gene_lists_with_validated_pathway"] ==
              sum(key[0] == disease for key in context_keys),
              f"S1 context coverage mismatch for {disease}")
        check(scope["n_validated_pathway_records"] == by_disease[disease],
              f"S1 record count mismatch for {disease}")
    check(len(matrix) == 24, "Expected 24 S2 disease matrix rows")
    broad = defaultdict(Counter)
    by_ad_pathway = Counter()
    ad_broad = defaultdict(Counter)
    for row in s2:
        tags = {tag.strip() for tag in (row["context_tags"] or "").split(";") if tag.strip()}
        check(tags.issubset(BROAD_TAGS), f"Unknown broad tag: {tags - set(BROAD_TAGS)}")
        for tag in tags:
            broad[row["disease"]][tag] += 1
        if row["disease"] == "AD":
            by_ad_pathway[row["pathway_id"]] += 1
            for tag in tags:
                ad_broad[row["pathway_id"]][tag] += 1

    check(sum(bool(row["cell_context_text"]) for row in s2) == 10689,
          "Context-text total differs from manuscript")
    check(sum(bool(row["context_tags"]) for row in s2) == 9384,
          "Parsed broad-tag total differs from S2")
    for row in matrix:
        disease = row["disease"]
        denominator = by_disease[disease]
        check(row["n_validated_pathway_records"] == denominator,
              f"S2 denominator mismatch for {disease}")
        for tag in BROAD_TAGS:
            count = broad[disease][tag]
            check(row[f"n__{tag}"] == count,
                  f"S2 broad count mismatch for {disease}/{tag}")
            check(abs(row[f"proportion__{tag}"] - count / denominator) < 1e-10,
                  f"S2 broad proportion mismatch for {disease}/{tag}")

    check(len(c_rows) == 340, f"Expected 340 S3 disease-tag rows; found {len(c_rows)}")
    for row in c_rows:
        disease = row["disease"]
        denominator = by_disease[disease]
        count = row["n_records_with_tag"]
        check(row["n_validated_pathway_records"] == denominator,
              f"S3 denominator mismatch for {disease}")
        check(0 <= count <= denominator, f"Invalid S3 count for {disease}")
        check(abs(row["proportion_of_records"] - count / denominator) < 0.00011,
              f"S3 proportion mismatch for {disease}/{row['cell_type_tag']}")
        tag = row["cell_type_tag"].lower()
        if row["tag_class"] == "broad" and tag in BROAD_TAGS:
            check(count == broad[disease][tag],
                  f"S3 broad count mismatch for {disease}/{tag}")
    selected = Counter(row["disease"] for row in c_rows
                       if str(row["shown_in_Figure_4C"]).lower() == "yes")
    check(selected == {"AD": 10, "PD": 5, "T2D": 5},
          f"Figure 4C display selection changed: {dict(selected)}")

    check(len(d_rows) == 11, f"Expected 11 recurrent AD pathways; found {len(d_rows)}")
    d_tags = [key for key in d_rows[0] if key not in
              {"pathway_name", "pathway_id", "n_validated_pathway_records"}]
    check(len(d_tags) == 10, "Expected ten Figure 4D tag columns")
    for row in d_rows:
        pathway = row["pathway_id"]
        n = by_ad_pathway[pathway]
        check(4 <= n <= 7 and row["n_validated_pathway_records"] == n,
              f"AD pathway count mismatch for {pathway}")
        for tag in d_tags:
            value = row[tag] or 0
            check(isinstance(value, int) and 0 <= value <= n,
                  f"Invalid Figure 4D value for {pathway}/{tag}")
            if tag.lower() in BROAD_TAGS:
                check(value == ad_broad[pathway][tag.lower()],
                      f"Figure 4D broad count mismatch for {pathway}/{tag}")
    return {
        "validated_pathway_records": len(s2),
        "diseases": len(by_disease),
        "benchmark_inputs": len(input_keys),
        "inputs_with_validated_pathway_context": len(context_keys),
        "records_with_context_text": 10689,
        "records_with_broad_tag": 9384,
        "figure4c_selected_tags": dict(selected),
        "figure4d_recurrent_ad_pathways": len(d_rows),
        "scope": "Broad Figure 4B counts independently recomputed from S2 records; Figure 4C and subtype Figure 4D counts audited from deposited S3 source tables.",
    }


def plot_panels(matrix: list[dict], c_rows: list[dict], d_rows: list[dict],
                out: Path) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np

    diseases = [row["disease"] for row in matrix]
    values = np.array([[row[f"proportion__{tag}"] for tag in BROAD_TAGS]
                       for row in matrix])
    fig, ax = plt.subplots(figsize=(13, 10))
    image = ax.imshow(values, aspect="auto", cmap="Blues", vmin=0, vmax=1)
    ax.set_xticks(range(len(BROAD_TAGS)), BROAD_TAGS, rotation=55, ha="right")
    ax.set_yticks(range(len(diseases)), diseases)
    fig.colorbar(image, ax=ax, label="Proportion of validated records")
    fig.tight_layout()
    fig.savefig(out / "Figure4B_recomputed.pdf")
    plt.close(fig)

    fig, axes = plt.subplots(1, 3, figsize=(16, 6))
    for ax, disease in zip(axes, ("AD", "PD", "T2D")):
        rows = sorted((row for row in c_rows if row["disease"] == disease
                       and str(row["shown_in_Figure_4C"]).lower() == "yes"),
                      key=lambda row: row["rank_within_disease"], reverse=True)
        ax.barh([row["cell_type_tag"] for row in rows],
                [row["n_records_with_tag"] for row in rows], color="#3979aa")
        ax.set_title(f"{disease} (n={rows[0]['n_validated_pathway_records']})")
        ax.set_xlabel("Validated records with tag")
    fig.tight_layout()
    fig.savefig(out / "Figure4C_from_S3.pdf")
    plt.close(fig)

    tags = [key for key in d_rows[0] if key not in
            {"pathway_name", "pathway_id", "n_validated_pathway_records"}]
    values = np.array([[row[tag] or 0 for tag in tags] for row in d_rows])
    fig, ax = plt.subplots(figsize=(13, 7))
    image = ax.imshow(values, aspect="auto", cmap="Blues", vmin=0, vmax=7)
    ax.set_xticks(range(len(tags)), tags, rotation=55, ha="right")
    ax.set_yticks(range(len(d_rows)), [row["pathway_name"] for row in d_rows])
    fig.colorbar(image, ax=ax, label="Validated records with tag")
    fig.tight_layout()
    fig.savefig(out / "Figure4D_from_S3.pdf")
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path,
                        default=ROOT / "output" / "figure4_reproduction")
    parser.add_argument("--no-plots", action="store_true")
    args = parser.parse_args()
    s1_book = DATA / "PathwayAI_Supp_Table_S1.xlsx"
    s2_book = DATA / "PathwayAI_Supp_Table_S2.xlsx"
    s3_book = DATA / "PathwayAI_Supp_Table_S3.xlsx"
    s1_scope = sheet_rows(s1_book, "Disease_scope_24")
    s1_inventory = sheet_rows(s1_book, "Gene_list_inventory_567")
    s2 = sheet_rows(s2_book, "Pathway_context_records_10701")
    matrix = sheet_rows(s2_book, "Disease_context_matrix_24")
    c_rows = sheet_rows(s3_book, "Fig4C_disease_tag_counts")
    d_rows = sheet_rows(s3_book, "Fig4D_AD_pathway_matrix")
    summary = audit(s1_scope, s1_inventory, s2, matrix, c_rows, d_rows)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    for name, rows in (("Figure4_record_context_10701.csv", s2),
                       ("Figure4B_broad_context_matrix.csv", matrix),
                       ("Figure4C_disease_tag_counts.csv", c_rows),
                       ("Figure4D_AD_pathway_matrix.csv", d_rows)):
        write_csv(args.output_dir / name, rows)
    (args.output_dir / "Figure4_audit.json").write_text(
        json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    if not args.no_plots:
        plot_panels(matrix, c_rows, d_rows, args.output_dir)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
