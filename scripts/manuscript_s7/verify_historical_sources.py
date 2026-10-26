#!/usr/bin/env python3
"""Rebuild the four Figure S7 metric CSVs from archived original run logs."""

import csv
import hashlib
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path, PurePosixPath


ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data" / "suppfig_s7"
ARCHIVE = DATA / "historical_sources.tar.gz"
MANIFEST = DATA / "historical_sources_manifest.csv"
GROUPS = (
    ("with_ranking", "generate_ranking_nfdr_metrics_csv.py", "ranking_nfdr_metrics.csv"),
    ("with_rag", "generate_rag_nfdr_metrics_csv.py", "rag_nfdr_metrics.csv"),
    ("with_rag_plus", "generate_rag_plus_nfdr_metrics_csv.py", "rag_plus_nfdr_metrics.csv"),
    ("with_rag_plus_user_prompt", "generate_rag_plus_prompt_nfdr_metrics_csv.py", "rag_plus_prompt_nfdr_metrics.csv"),
)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def main():
    with MANIFEST.open(newline="", encoding="utf-8") as handle:
        expected = {row["archive_path"]: row for row in csv.DictReader(handle)}
    if len(expected) != 30 or sum(r["kind"] == "run_log" for r in expected.values()) != 25:
        raise AssertionError("Expected 25 logs and five historical scripts")

    with tempfile.TemporaryDirectory(prefix="s7-original-logs-") as temporary:
        destination = Path(temporary)
        with tarfile.open(ARCHIVE, "r:gz") as archive:
            members = archive.getmembers()
            if set(m.name for m in members) != set(expected):
                raise AssertionError("Source archive and manifest file lists differ")
            for member in members:
                relative = PurePosixPath(member.name)
                if (not member.isfile() or relative.is_absolute() or ".." in relative.parts
                        or relative.parts[:2] != ("result", "comparison")):
                    raise AssertionError("Unsafe archive member: " + member.name)
                content = archive.extractfile(member).read()
                row = expected[member.name]
                if len(content) != int(row["bytes"]) or digest(content) != row["sha256"]:
                    raise AssertionError("Source checksum mismatch: " + member.name)
                target = destination.joinpath(*relative.parts)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(content)

        base = destination / "result" / "comparison"
        for group, script_name, output_name in GROUPS:
            script = base / group / script_name
            run = subprocess.run([sys.executable, str(script)], cwd=base / group,
                                 text=True, capture_output=True, check=False)
            if run.returncode:
                raise RuntimeError("Historical generator failed: %s\n%s" %
                                   (script_name, run.stderr[-2500:]))
            rebuilt = (base / group / output_name).read_bytes()
            deposited = (DATA / output_name).read_bytes()
            if rebuilt != deposited:
                raise AssertionError("Rebuilt CSV differs from deposit: " + output_name)
            print(output_name, "byte-for-byte match; rows", rebuilt.count(b"\n") - 1)
    print("Verified 25 original logs, five scripts, and four exact metric CSV rebuilds")


if __name__ == "__main__":
    main()
