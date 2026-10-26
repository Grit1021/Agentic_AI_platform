#!/usr/bin/env python3
"""Package the exact 567-pair, two-round artifacts and run logs for audit."""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import tarfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
MANIFEST = REPO_ROOT / "data" / "run_output_manifest_567.csv"


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def collect_paths(runs_root: Path) -> list[Path]:
    with MANIFEST.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    if len(rows) != 567 or len({(r["disease"], r["module_id"]) for r in rows}) != 567:
        raise ValueError("Expected 567 unique gene lists in run_output_manifest_567.csv")

    artifact_columns = [column for column in rows[0] if column.startswith("iter")]
    if len(artifact_columns) != 6:
        raise ValueError(f"Expected six artifact columns, found {artifact_columns}")
    paths = {Path(row[column]) for row in rows for column in artifact_columns}
    if len(paths) != 567 * 6:
        raise ValueError("Run artifact paths are not unique")

    for disease in sorted({row["disease"] for row in rows}):
        pattern = (
            f"result/memory_bank_external/iterative_feedback_{disease}/"
            f"{disease}_aggregated_*/run_log_*.txt"
        )
        logs = list(runs_root.glob(pattern))
        if len(logs) != 1:
            raise ValueError(f"Expected exactly one run log for {disease}; found {len(logs)}")
        paths.add(logs[0].relative_to(runs_root))

    missing = [path for path in paths if not (runs_root / path).is_file()]
    if missing:
        raise FileNotFoundError(f"Missing {len(missing)} files; first: {missing[0]}")
    if len(paths) != 567 * 6 + 24:
        raise ValueError(f"Expected 3,426 files; found {len(paths)}")
    return sorted(paths, key=lambda path: path.as_posix())


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs-root", required=True, type=Path)
    parser.add_argument("--archive", required=True, type=Path)
    parser.add_argument("--checksums", required=True, type=Path)
    args = parser.parse_args()
    root = args.runs_root.resolve()
    paths = collect_paths(root)

    args.archive.parent.mkdir(parents=True, exist_ok=True)
    args.checksums.parent.mkdir(parents=True, exist_ok=True)
    checksums = []
    with args.archive.open("wb") as output:
        with gzip.GzipFile(fileobj=output, mode="wb", filename="", mtime=0, compresslevel=6) as compressed:
            with tarfile.open(fileobj=compressed, mode="w") as archive:
                for relative in paths:
                    source = root / relative
                    checksums.append((relative.as_posix(), source.stat().st_size, file_hash(source)))
                    info = tarfile.TarInfo(relative.as_posix())
                    info.size = source.stat().st_size
                    info.mode = 0o644
                    info.mtime = 0
                    with source.open("rb") as handle:
                        archive.addfile(info, handle)

    with args.checksums.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(("path", "bytes", "sha256"))
        writer.writerows(checksums)
    print(f"Files: {len(paths)}")
    print(f"Archive: {args.archive} ({args.archive.stat().st_size} bytes)")
    print(f"Archive SHA-256: {file_hash(args.archive)}")
    print(f"Checksums: {args.checksums}")


if __name__ == "__main__":
    main()
