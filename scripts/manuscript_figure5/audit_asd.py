#!/usr/bin/env python3
"""Audit the submitted ASD figure against its preserved pathway-level run data.

The submitted editable PowerPoint is the exact visual source. This script
regenerates the 15-row biological-ranking source table and checks the major
numerical labels in that slide. It does not repeat the original model/API run.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
from collections import Counter
from pathlib import Path
from xml.etree import ElementTree
from zipfile import ZipFile


ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data/figure5_asd/source_data_raw.json"
DEPOSITED = ROOT / "data/figure5_asd/panel_b_top15.csv"
SLIDE = ROOT / "data/manuscript_figures/submitted/Main_Figure_5.pptx"
DATABASES = ("GO:BP", "GO:MF", "GO:CC", "KEGG", "REAC")
COUNTS = {"GO:BP": 21, "GO:MF": 12, "GO:CC": 12, "KEGG": 9, "REAC": 6}


def source_rows(pathways: list[dict]) -> list[dict]:
    selected = []
    for database in DATABASES:
        ordered = sorted((p for p in pathways if p["category"] == database),
                         key=lambda p: p["gpt_rank"])
        for rank, pathway in enumerate(ordered[:3], start=1):
            selected.append({
                "within_database_rank": rank,
                "database": database,
                "pathway": pathway["name"],
                "pathway_id": pathway["pathway_id"],
                "adjusted_p_value": pathway["p_value"],
                "minus_log10_adjusted_p": -math.log10(pathway["p_value"]),
                "intersection_genes": pathway["intersection_size"],
                "term_size": pathway["term_size"],
            })
    return sorted(selected, key=lambda row: (row["within_database_rank"],
                                             DATABASES.index(row["database"])))


def slide_text(path: Path) -> str:
    with ZipFile(path) as archive:
        slide = ElementTree.fromstring(archive.read("ppt/slides/slide1.xml"))
    return " ".join(node.text for node in slide.iter()
                    if node.tag.endswith("}t") and node.text)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path,
                        default=ROOT / "output/figure5_asd_audit")
    args = parser.parse_args()
    data = json.loads(DATA.read_text(encoding="utf-8"))
    pathways = data["pathways"]
    if data["metadata"]["gene_count"] != 436 or len(data["metadata"]["genes"]) != 436:
        raise ValueError("ASD gene-list size disagrees with the submitted figure")
    if len(pathways) != 60 or Counter(p["category"] for p in pathways) != COUNTS:
        raise ValueError("ASD validated-pathway totals disagree with the submitted figure")
    if sum(bool(p.get("cell_context")) for p in pathways) != 60:
        raise ValueError("Not all 60 pathways carry a cell/tissue context statement")
    if len(data["reasoning"]) != 10:
        raise ValueError("Expected two rounds of five database reasoning records")
    rows = source_rows(pathways)
    with DEPOSITED.open(newline="", encoding="utf-8") as handle:
        original = list(csv.DictReader(handle))
    if len(original) != 15:
        raise ValueError("Deposited panel B source does not contain 15 rows")
    for recomputed, deposited in zip(rows, original):
        for key in ("within_database_rank", "database", "pathway", "pathway_id",
                    "intersection_genes", "term_size"):
            if str(recomputed[key]) != deposited[key]:
                raise ValueError(f"Panel B source mismatch in {key}: {recomputed[key]}")
        if not math.isclose(recomputed["adjusted_p_value"],
                            float(deposited["adjusted_p_value"]), rel_tol=1e-12):
            raise ValueError("Panel B adjusted P-value changed")
    focal = next(p for p in pathways if p["pathway_id"] == "GO:0031175")
    if (focal["gpt_rank"] != 2 or focal["intersection_size"] != 81
            or focal["term_size"] != 1010
            or not math.isclose(focal["p_value"], 5.40e-25, rel_tol=0.01)):
        raise ValueError("Figure 5C focal pathway values changed")
    text = slide_text(SLIDE)
    for phrase in ("436 input genes", "431 / 436", "100", "60 / 60",
                   "neuron projection development", "chromatin organization",
                   "histone methyltransferase activity", "postsynapse",
                   "Long-term potentiation"):
        if phrase not in text:
            raise ValueError(f"Submitted slide lacks expected text: {phrase}")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    out = args.output_dir / "Figure5_ASD_panelB_recomputed.csv"
    with out.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    report = {
        "as_run_id": "7ccbdf6d369e4318bb116ccdf87d97b2",
        "input_genes": 436,
        "validated_pathways": 60,
        "validated_by_database": COUNTS,
        "pathways_with_cell_context": 60,
        "panel_b_rows": len(rows),
        "panel_c_pathway": "GO:0031175",
        "panel_c_overlap": 81,
        "status": "source data and displayed labels verified; no live API rerun",
    }
    (args.output_dir / "Figure5_ASD_audit.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
