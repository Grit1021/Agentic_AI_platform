#!/usr/bin/env python3
"""Verify benchmark source inputs and the extracted 567-pair run bundle."""

from __future__ import annotations

import argparse
import csv
import hashlib
from collections import defaultdict
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_inputs() -> None:
    inputs = read_csv(REPO / "data" / "gene_lists_567.csv")
    sources = read_csv(REPO / "data" / "source_manifest.csv")
    assert len(inputs) == 567 and len(sources) == 24
    expected = {(r["disease"], r["module_id"]): r for r in inputs}
    assert len(expected) == 567

    for source in sources:
        path = REPO / "data" / source["source_file"]
        assert sha256(path) == source["source_sha256"], path
        modules: dict[str, dict[str, None]] = defaultdict(dict)
        for row in read_csv(path):
            if row["passes_all_filters"].lower() == "true" and row["cluster_walktrap"] != "-1":
                modules[row["cluster_walktrap"]][row["node"]] = None
        retained = {module: list(genes) for module, genes in modules.items() if len(genes) >= 10}
        assert len(retained) == int(source["gene_list_count"]), path
        for module, genes in retained.items():
            record = expected[(source["disease"], module)]
            assert record["mesh_id"] == source["mesh_id"]
            assert record["source_sha256"] == source["source_sha256"]
            assert record["gene_count"] == str(len(genes))
            assert record["genes"].split(";") == genes
    print("Inputs: 567 lists from 24 source files verified")


def verify_outputs(runs_root: Path) -> None:
    records = read_csv(REPO / "data" / "benchmark_run_outputs_567_sha256.csv")
    assert len(records) == 3426
    assert len({r["path"] for r in records}) == 3426
    for record in records:
        relative = Path(record["path"])
        assert not relative.is_absolute() and ".." not in relative.parts
        path = runs_root / relative
        assert path.is_file(), path
        assert path.stat().st_size == int(record["bytes"]), path
        assert sha256(path) == record["sha256"], path
    print("Run bundle: 3,426 files verified (3,402 artifacts and 24 logs)")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs-root", type=Path, default=REPO)
    args = parser.parse_args()
    verify_inputs()
    verify_outputs(args.runs_root)


if __name__ == "__main__":
    main()
