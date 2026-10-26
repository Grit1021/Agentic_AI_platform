#!/usr/bin/env python3
"""Reconstruct S4/S6 tissue counts directly from deposited context statements.

This is a transparent reconstruction of the submitted plots' keyword tags,
not a recovered copy of the original tag-curation script. Every tag is matched
once per validated pathway record. The 20 S4 counts are checked against the
numbers printed in the submitted image.
"""

from __future__ import annotations

import argparse
import csv
import re
from collections import Counter, defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "data/figure4/Figure4_record_context_10701.csv"

# Patterns are applied to the original pathway-specific Cell Context text.
TISSUE_PATTERNS = (
    ("vasculature", r"\bvasculature\b|\bvascular\b|\bblood vessels?\b"),
    ("airway", r"\bairway\b|\bbronchial\b"),
    ("colon/intestine", r"\bcolon\b|\bcolonic\b|\bcolorectal\b|\bintestinal\b|\bgut\b|\bbowel\b"),
    ("kidney", r"\bkidney\b|\brenal\b"),
    ("cortex", r"\bcortex\b|\bcortical\b"),
    ("brain/central nervous system", r"\bbrain\b|\bcerebral\b|\bCNS\b|\bcentral nervous system\b"),
    ("mucosa", r"\bmucosal?\b"),
    ("synovium", r"\bsynovial\b|\bsynovium\b"),
    ("atrium", r"\batrium\b|\batrial\b"),
    ("hippocampus", r"\bhippocampus\b|\bhippocampal\b"),
    ("liver", r"\bliver\b|\bhepatic\b"),
    ("adipose tissue", r"\badipose\b|\bfat tissue\b"),
    ("stroma", r"\bstroma\b|\bstromal\b"),
    ("lamina propria", r"\blamina propria\b"),
    ("thyroid", r"\bthyroid\b"),
    ("lung", r"\blung\b|\bpulmonary\b"),
    ("pancreas", r"\bpancreas\b|\bpancreatic\b|\bislet\b"),
    ("lymph node", r"\blymph nodes?\b"),
    ("alveoli", r"\balveolar\b|\balveoli\b"),
    ("skeletal muscle", r"\bskeletal muscle\b"),
)
S4_SUBMITTED_COUNTS = (1334, 1290, 1278, 824, 609, 517, 514, 498, 460, 425,
                       395, 392, 385, 368, 347, 341, 309, 286, 273, 265)
S6_EXTRA_PATTERNS = (
    ("Synaptic terminals", r"\bsynaptic terminals?\b|\bpresynaptic terminals?\b|\bpostsynaptic terminals?\b"),
    ("Grey matter", r"\bgr[ae]y matter\b"),
    ("Plaque-associated regions", r"\bsurrounding amyloid plaques\b"),
)
S6_COLUMNS = ("Hippocampus", "Cortex", "Brain / CNS", "Synaptic terminals",
              "Vasculature", "Grey matter", "Plaque-associated regions")
S6_PATTERNS = (TISSUE_PATTERNS[9][1], TISSUE_PATTERNS[4][1],
               TISSUE_PATTERNS[5][1], S6_EXTRA_PATTERNS[0][1],
               TISSUE_PATTERNS[0][1], S6_EXTRA_PATTERNS[1][1],
               S6_EXTRA_PATTERNS[2][1])
S6_PATHWAY_ORDER = (
    "GO:0006897", "GO:0005886", "GO:0045202", "GO:0016192", "KEGG:04140",
    "GO:0005794", "KEGG:04141", "GO:0050839", "GO:0098978", "GO:0005764",
    "GO:0014069", "REAC:R-HSA-422475", "REAC:R-HSA-112316", "GO:0006914",
    "GO:0005509", "GO:0030054", "GO:0005783", "GO:0005768", "GO:0043005",
    "GO:0005515", "GO:0048167", "GO:0099504", "GO:0031625",
)


def write_csv(path: Path, rows: list[dict]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def plot_s4(rows: list[dict], path: Path) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(10, 8))
    displayed = list(reversed(rows))
    ax.barh([row["tissue_context"] for row in displayed],
            [row["n_records_with_tag"] for row in displayed], color="#397f7b")
    ax.set_xlabel("Validated pathway records mentioning tissue context")
    ax.set_title("S4  Tissue contexts across validated pathways")
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)


def plot_s6(rows: list[dict], path: Path) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np

    values = np.array([[row[column] for column in S6_COLUMNS] for row in rows])
    fig, ax = plt.subplots(figsize=(11, 10))
    image = ax.imshow(values, aspect="auto", cmap="BuGn", vmin=0, vmax=7)
    ax.set_xticks(range(len(S6_COLUMNS)), S6_COLUMNS, rotation=40, ha="right")
    ax.set_yticks(range(len(rows)),
                  [f"{row['pathway_name']} [{row['pathway_id']}]" for row in rows])
    for y in range(len(rows)):
        for x in range(len(S6_COLUMNS)):
            if values[y, x]:
                ax.text(x, y, str(values[y, x]), ha="center", va="center", fontsize=7)
    fig.colorbar(image, ax=ax, label="Validated records carrying the tag")
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path,
                        default=ROOT / "output/suppfig_s4_s6_reproduction")
    parser.add_argument("--no-plots", action="store_true")
    args = parser.parse_args()
    with SOURCE.open(newline="", encoding="utf-8") as handle:
        records = list(csv.DictReader(handle))
    if len(records) != 10701:
        raise ValueError("Expected 10,701 deposited context records")
    patterns = [(label, re.compile(pattern, re.I)) for label, pattern in TISSUE_PATTERNS]
    counts = Counter()
    for record in records:
        context = record["cell_context_text"] or ""
        for label, pattern in patterns:
            if pattern.search(context):
                counts[label] += 1
    ordered = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    if [count for _, count in ordered] != list(S4_SUBMITTED_COUNTS):
        raise ValueError(f"S4 counts do not match the numbers printed in the figure: {ordered}")
    s4 = [{"rank": index, "tissue_context": label, "n_records_with_tag": count}
          for index, (label, count) in enumerate(ordered, 1)]

    ad = defaultdict(list)
    for record in records:
        if record["disease"] == "AD":
            ad[record["pathway_id"]].append(record)
    if len({pathway for pathway, group in ad.items() if len(group) >= 3}) != 23:
        raise ValueError("Expected 23 recurrent AD pathways for S6")
    s6_regex = [re.compile(pattern, re.I) for pattern in S6_PATTERNS]
    s6 = []
    for pathway in S6_PATHWAY_ORDER:
        group = ad[pathway]
        if len(group) < 3:
            raise ValueError(f"S6 pathway lacks three records: {pathway}")
        row = {"pathway_id": pathway, "pathway_name": group[0]["pathway_name"],
               "n_validated_pathway_records": len(group)}
        for label, pattern in zip(S6_COLUMNS, s6_regex):
            row[label] = sum(bool(pattern.search(record["cell_context_text"] or ""))
                             for record in group)
        s6.append(row)
    expected_spot_checks = {
        "GO:0006897": [5, 5, 0, 1, 0, 0, 0],
        "GO:0005886": [6, 6, 0, 0, 0, 1, 0],
        "GO:0099504": [3, 3, 0, 2, 0, 0, 1],
    }
    for row in s6:
        if row["pathway_id"] in expected_spot_checks and [row[x] for x in S6_COLUMNS] != expected_spot_checks[row["pathway_id"]]:
            raise ValueError(f"S6 source-text counts changed: {row['pathway_id']}")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    write_csv(args.output_dir / "Supplementary_Figure_S4_tissue_top20.csv", s4)
    write_csv(args.output_dir / "Supplementary_Figure_S6_AD_pathway_tissue_matrix.csv", s6)
    if not args.no_plots:
        plot_s4(s4, args.output_dir / "Supplementary_Figure_S4_numeric_reproduction.pdf")
        plot_s6(s6, args.output_dir / "Supplementary_Figure_S6_numeric_reproduction.pdf")
    print("S4: all 20 printed tissue counts matched; S6: 23 recurrent AD pathways x 7 tags reconstructed")


if __name__ == "__main__":
    main()
