#!/usr/bin/env python3
"""Verify all deposited final figure files and the ASD source-data snapshot."""

from __future__ import annotations

import csv
import hashlib
from pathlib import Path
from zipfile import ZipFile


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "data/manuscript_figures/SHA256SUMS.csv"


def main() -> None:
    with MANIFEST.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    expected = {
        *(f"data/manuscript_figures/submitted/Main_Figure_{n}.{ext}"
          for n in range(1, 6) for ext in ("pdf", "pptx")),
        *(f"data/manuscript_figures/submitted/Supplementary_Figure_S{n}.png"
          for n in range(1, 8)),
        "data/figure5_asd/source_data_raw.json",
        "data/figure5_asd/panel_b_top15.csv",
        *(f"data/manuscript_figures/source_tables/{name}.csv" for name in (
            "Figure3_A_macro_rates_and_bootstrap",
            "Figure3_B_disease_rates",
            "Figure3_C_Crohn116_rates",
            "Supplementary_Figure_S2_top25_counts",
            "Supplementary_Figure_S3_disease_top8_counts",
            "Supplementary_Figure_S4_tissue_top20",
            "Supplementary_Figure_S6_AD_pathway_tissue_matrix",
        )),
    }
    if len(rows) != 26 or {row["relative_path"] for row in rows} != expected:
        raise ValueError("Figure archive manifest does not list the 26 expected files")
    for row in rows:
        path = ROOT / row["relative_path"]
        content = path.read_bytes()
        if len(content) != int(row["bytes"]):
            raise ValueError(f"Figure archive size mismatch: {path.name}")
        if hashlib.sha256(content).hexdigest() != row["sha256"]:
            raise ValueError(f"Figure archive SHA-256 mismatch: {path.name}")
        if path.suffix == ".pptx":
            with ZipFile(path) as archive:
                if archive.testzip() is not None or "ppt/slides/slide1.xml" not in archive.namelist():
                    raise ValueError(f"Invalid editable figure deck: {path.name}")
        elif path.suffix == ".pdf" and not content.startswith(b"%PDF"):
            raise ValueError(f"Invalid PDF header: {path.name}")
        elif path.suffix == ".png" and not content.startswith(b"\x89PNG\r\n\x1a\n"):
            raise ValueError(f"Invalid PNG header: {path.name}")
    print("Verified 5 final main figures (PDF + editable PPTX), 7 submitted supplementary images, 2 ASD source files, and 7 numerical tables")


if __name__ == "__main__":
    main()
