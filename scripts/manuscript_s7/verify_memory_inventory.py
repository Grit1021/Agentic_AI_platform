#!/usr/bin/env python3
"""Check the 7,182-pathway memory inventory against archived FDR outputs."""

import csv
import io
import sqlite3
import tarfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data" / "suppfig_s7"


def key(code, row):
    pathway_id = (row.get("native") or "").strip()
    if not pathway_id or pathway_id.lower() == "nan":
        pathway_id = (row.get("name") or "").strip()
    return code, (row.get("source") or "").strip(), pathway_id


def main():
    source_codes = set()
    with (ROOT / "data" / "source_manifest.csv").open(newline="", encoding="utf-8") as handle:
        source_codes = {row["disease"] for row in csv.DictReader(handle)}
    if len(source_codes) != 24:
        raise AssertionError("Expected 24 source diseases")

    archived = set()
    raw_rows = 0
    with tarfile.open(ROOT / "data" / "benchmark_run_outputs_567.tar.gz", "r:gz") as archive:
        for member in archive:
            if not (member.isfile() and member.name.endswith("_gpt_matched_fdr_p005.csv")):
                continue
            parts = Path(member.name).parts
            disease_parts = [x for x in parts if x.startswith("iterative_feedback_")]
            if len(disease_parts) != 1:
                raise AssertionError("Cannot identify disease in " + member.name)
            code = disease_parts[0].removeprefix("iterative_feedback_")
            if code not in source_codes:
                raise AssertionError("Unexpected disease in " + member.name)
            with io.TextIOWrapper(archive.extractfile(member), encoding="utf-8-sig", newline="") as handle:
                for row in csv.DictReader(handle):
                    raw_rows += 1
                    archived.add(key(code, row))
    if len(archived) != 7182:
        raise AssertionError("Archived FDR rows do not yield 7,182 unique pathways")

    with (DATA / "memory_pathway_inventory_7182.csv").open(newline="", encoding="utf-8") as handle:
        csv_rows = list(csv.DictReader(handle))
    csv_keys = {(r["mesh_code"], r["pathway_source"], r["pathway_id"]) for r in csv_rows}
    if len(csv_rows) != 7182 or csv_keys != archived:
        raise AssertionError("Deposited memory inventory differs from archived FDR sources")

    uri = (DATA / "memory_bank_rebuilt.db").resolve().as_uri() + "?mode=ro"
    with sqlite3.connect(uri, uri=True) as connection:
        db_rows = connection.execute("SELECT mesh_code, pathway_source, pathway_id FROM pathway_experiences").fetchall()
    if len(db_rows) != 7182 or set(db_rows) != archived:
        raise AssertionError("Deposited SQLite inventory differs from archived FDR sources")
    print("Memory inventory: 24 diseases,", raw_rows,
          "FDR rows, 7,182 unique disease/source/pathway records verified")


if __name__ == "__main__":
    main()
