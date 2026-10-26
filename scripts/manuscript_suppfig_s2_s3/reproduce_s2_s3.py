#!/usr/bin/env python3
"""Rebuild Supplementary Figures S2 and S3 counts from deposited S3 tags.

Counts summarize multi-label interpretation tags. The deposited workbook is
the source table; the original per-record fine-grained tag curation is not
available, so these plots are numerical reproductions of those source counts.
"""

from __future__ import annotations

import argparse
import csv
from collections import Counter, defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "data/figure4/Figure4C_disease_tag_counts.csv"


def write_csv(path: Path, rows: list[dict]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def plot_s2(rows: list[dict], path: Path) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    ordered = list(reversed(rows))
    fig, ax = plt.subplots(figsize=(9, 9))
    ax.barh([row["cell_type_tag"] for row in ordered],
            [row["n_records_with_tag"] for row in ordered], color="#427aa4")
    ax.set_xlabel("Validated pathway records with tag")
    ax.set_title("S2  Most frequent cell-type context tags across 24 diseases")
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)


def plot_s3(rows: list[dict], path: Path) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.backends.backend_pdf import PdfPages

    diseases = sorted({row["disease"] for row in rows})
    with PdfPages(path) as pdf:
        for start in range(0, len(diseases), 6):
            fig, axes = plt.subplots(2, 3, figsize=(15, 9))
            for ax, disease in zip(axes.flat, diseases[start:start + 6]):
                selection = sorted((row for row in rows if row["disease"] == disease),
                                   key=lambda row: row["rank_within_disease"], reverse=True)
                ax.barh([row["cell_type_tag"] for row in selection],
                        [100 * float(row["proportion_of_records"]) for row in selection],
                        color="#427aa4")
                ax.set_title(f"{selection[0]['disease_name']} (n={selection[0]['n_validated_pathway_records']})",
                             fontsize=9)
                ax.tick_params(labelsize=7)
                ax.set_xlim(0, 100)
                ax.set_xlabel("Percent of disease records", fontsize=8)
            for ax in list(axes.flat)[len(diseases[start:start + 6]):]:
                ax.axis("off")
            fig.suptitle("S3  Disease-level cell-type context counts", fontsize=13)
            fig.tight_layout()
            pdf.savefig(fig)
            plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path,
                        default=ROOT / "output/suppfig_s2_s3_reproduction")
    parser.add_argument("--no-plots", action="store_true")
    args = parser.parse_args()
    with SOURCE.open(newline="", encoding="utf-8") as handle:
        raw = list(csv.DictReader(handle))
    if len(raw) != 340 or len({row["disease"] for row in raw}) != 24:
        raise ValueError("Expected 340 tag-count rows from 24 diseases")
    seen = set()
    by_disease = defaultdict(list)
    global_counts = Counter()
    for row in raw:
        key = (row["disease"], row["cell_type_tag"])
        if key in seen:
            raise ValueError(f"Duplicate disease/tag count: {key}")
        seen.add(key)
        count = int(row["n_records_with_tag"])
        total = int(row["n_validated_pathway_records"])
        if not (0 < count <= total):
            raise ValueError(f"Invalid count for {key}")
        global_counts[row["cell_type_tag"]] += count
        by_disease[row["disease"]].append(row)
    s2 = [{"rank": rank, "cell_type_tag": tag, "n_records_with_tag": count}
          for rank, (tag, count) in enumerate(
              sorted(global_counts.items(), key=lambda item: (-item[1], item[0]))[:25], 1)]
    s3 = []
    for disease in sorted(by_disease):
        selected = sorted(by_disease[disease], key=lambda row: int(row["rank_within_disease"]))[:8]
        for row in selected:
            s3.append({"disease": disease, "disease_name": row["disease_name"],
                       "n_validated_pathway_records": int(row["n_validated_pathway_records"]),
                       "rank_within_disease": int(row["rank_within_disease"]),
                       "cell_type_tag": row["cell_type_tag"],
                       "n_records_with_tag": int(row["n_records_with_tag"]),
                       "proportion_of_records": row["proportion_of_records"]})
    if len(s3) != 185:
        raise ValueError(f"Expected 185 displayed S3 tag rows; found {len(s3)}")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    write_csv(args.output_dir / "Supplementary_Figure_S2_top25_counts.csv", s2)
    write_csv(args.output_dir / "Supplementary_Figure_S3_disease_top8_counts.csv", s3)
    if not args.no_plots:
        plot_s2(s2, args.output_dir / "Supplementary_Figure_S2_numeric_reproduction.pdf")
        plot_s3(s3, args.output_dir / "Supplementary_Figure_S3_numeric_reproduction.pdf")
    print(f"S2: {len(s2)} global tags; S3: {len(s3)} displayed disease-tag rows across 24 diseases")


if __name__ == "__main__":
    main()
