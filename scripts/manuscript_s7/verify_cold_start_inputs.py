#!/usr/bin/env python3
"""Rebuild the 69 five-disease inputs from original network module tables."""

import csv
import hashlib
from collections import defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data" / "suppfig_s7"
METRICS = ("ranking_nfdr_metrics.csv", "rag_nfdr_metrics.csv",
           "rag_plus_nfdr_metrics.csv", "rag_plus_prompt_nfdr_metrics.csv")


def read_csv(path):
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def main():
    manifest = read_csv(DATA / "source_manifest_5.csv")
    recorded = read_csv(DATA / "gene_lists_69.csv")
    if len(manifest) != 5 or len(recorded) != 69:
        raise AssertionError("Unexpected five-disease input count")
    derived = []
    for entry in manifest:
        source = DATA / entry["source_file"]
        digest = hashlib.sha256(source.read_bytes()).hexdigest()
        if digest != entry["source_sha256"]:
            raise AssertionError("Source hash differs: " + source.name)
        groups = defaultdict(list)
        for row in read_csv(source):
            if (row["passes_all_filters"].lower() == "true"
                    and row["cluster_walktrap"] != "-1" and row["node"].strip()):
                groups[row["cluster_walktrap"]].append(row["node"].strip())
        count = 0
        for module, nodes in groups.items():
            unique = list(dict.fromkeys(nodes))
            if len(unique) < 10:
                continue
            derived.append({
                "disease": entry["disease"],
                "disease_name": entry["disease_name"],
                "mesh_id": entry["mesh_id"],
                "module_id": module,
                "gene_count": str(len(unique)),
                "genes": ";".join(unique),
                "source_file": entry["source_file"],
                "source_sha256": digest,
            })
            count += 1
        if count != int(entry["gene_list_count"]):
            raise AssertionError("Source module count differs: " + entry["disease"])
    if derived != recorded:
        raise AssertionError("Derived gene lists do not match the deposit")
    expected_pairs = {(r["disease"], r["module_id"]) for r in recorded}
    for filename in METRICS:
        pairs = {(r["disease"], r["module"]) for r in read_csv(DATA / filename)}
        if pairs != expected_pairs:
            raise AssertionError("Metrics do not share exact inputs: " + filename)
    if (DATA / "source_modules" / "D006333_modules.csv").read_bytes() != (
            ROOT / "data" / "source_modules" / "D006333_modules.csv").read_bytes():
        raise AssertionError("HF source differs from the main benchmark")
    print("Five original module tables reproduce 69 exact cold-start gene lists")
    print("All four memory metrics files use the same 69 disease/module inputs")


if __name__ == "__main__":
    main()
