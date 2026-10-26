#!/usr/bin/env python3
"""Compare freshly rebuilt manuscript figure tables to deposited snapshots."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PAIRS = {
    "figure3_reproduction": (
        "Figure3_A_macro_rates_and_bootstrap.csv",
        "Figure3_B_disease_rates.csv",
        "Figure3_C_Crohn116_rates.csv",
    ),
    "suppfig_s2_s3_reproduction": (
        "Supplementary_Figure_S2_top25_counts.csv",
        "Supplementary_Figure_S3_disease_top8_counts.csv",
    ),
    "suppfig_s4_s6_reproduction": (
        "Supplementary_Figure_S4_tissue_top20.csv",
        "Supplementary_Figure_S6_AD_pathway_tissue_matrix.csv",
    ),
}


def main() -> None:
    count = 0
    for output_dir, filenames in PAIRS.items():
        for filename in filenames:
            rebuilt = ROOT / "output" / output_dir / filename
            deposited = ROOT / "data/manuscript_figures/source_tables" / filename
            if rebuilt.read_bytes() != deposited.read_bytes():
                raise ValueError(f"Rebuilt table differs from deposited source: {filename}")
            count += 1
    print(f"Verified {count} rebuilt figure tables byte for byte")


if __name__ == "__main__":
    main()
