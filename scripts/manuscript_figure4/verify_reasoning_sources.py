#!/usr/bin/env python3
"""Audit deposited Figure 4 reasoning-text sources against the S2 export."""

import csv
import hashlib
import tarfile
from collections import Counter
from pathlib import Path, PurePosixPath


ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data" / "figure4"


def rows(path):
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def main():
    records = rows(DATA / "Figure4_record_context_10701.csv")
    references = Counter(row["reasoning_file"] for row in records if row["reasoning_file"])
    manifest_rows = rows(DATA / "reasoning_source_manifest.csv")
    manifest = {row["reasoning_file"]: row for row in manifest_rows}
    if len(records) != 10701 or len(references) != 2127 or len(manifest) != 2127:
        raise AssertionError("Unexpected S2 record or reasoning-source count")
    if set(references) != set(manifest):
        raise AssertionError("Manifest does not cover every referenced source")
    for path, count in references.items():
        if int(manifest[path]["record_count"]) != count:
            raise AssertionError("Referenced-record count differs: " + path)
    archived = {path for path, row in manifest.items() if row["status"] == "archived"}
    missing = set(manifest) - archived
    if len(archived) != 2117 or len(missing) != 10:
        raise AssertionError("Unexpected archived/missing source coverage")
    with tarfile.open(DATA / "reasoning_sources.tar.gz", "r:gz") as archive:
        members = archive.getmembers()
        if {m.name for m in members} != archived:
            raise AssertionError("Archive members differ from manifest")
        for member in members:
            path = PurePosixPath(member.name)
            if member.isfile() is False or path.is_absolute() or ".." in path.parts:
                raise AssertionError("Unsafe reasoning source path")
            content = archive.extractfile(member).read()
            entry = manifest[member.name]
            if len(content) != int(entry["bytes"]):
                raise AssertionError("Reasoning file size differs: " + member.name)
            if hashlib.sha256(content).hexdigest() != entry["sha256"]:
                raise AssertionError("Reasoning file checksum differs: " + member.name)
    print("Figure 4: 10,701 records reference 2,127 reasoning files;")
    print("2,117 sources archived and verified; 10 historical paths unavailable")
    print("Records linked to unavailable paths:", sum(references[p] for p in missing))


if __name__ == "__main__":
    main()
