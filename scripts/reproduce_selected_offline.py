#!/usr/bin/env python3
"""Reproduce the selected offline Figure 2, Figure 4, and Figure S7 analyses.

Install the requirements in the three manuscript script directories first.
This script makes no model or external-service calls.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tarfile
from pathlib import Path, PurePosixPath


ROOT = Path(__file__).resolve().parents[1]
ARCHIVE = ROOT / "data" / "benchmark_run_outputs_567.tar.gz"
COMMANDS = (
    "scripts/verify_benchmark_artifacts.py",
    "scripts/manuscript_figure2/build_figure2_consistent_current.py",
    "scripts/manuscript_figure2/summarize_key_numbers.py",
    "scripts/manuscript_figure4/verify_reasoning_sources.py",
    "scripts/manuscript_figure4/reproduce_figure4.py",
    "scripts/manuscript_s7/verify_cold_start_inputs.py",
    "scripts/manuscript_s7/verify_historical_sources.py",
    "scripts/manuscript_s7/verify_memory_inventory.py",
    "scripts/manuscript_s7/reproduce_s7.py",
)


def extract_historical_outputs() -> None:
    """Extract the documented result files while rejecting unsafe TAR entries."""
    with tarfile.open(ARCHIVE, "r:gz") as archive:
        members = archive.getmembers()
        if len(members) != 3426 or len({m.name for m in members}) != len(members):
            raise ValueError("Expected 3,426 unique historical output files")
        for member in members:
            relative = PurePosixPath(member.name)
            if (not member.isfile() or relative.is_absolute() or ".." in relative.parts
                    or relative.parts[:2] != ("result", "memory_bank_external")):
                raise ValueError(f"Unsafe or unexpected archive entry: {member.name}")
            target = ROOT.joinpath(*relative.parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.extractfile(member) as source, target.open("wb") as destination:
                shutil.copyfileobj(source, destination)
    print("Extracted 3,426 historical output files", flush=True)


def main() -> None:
    extract_historical_outputs()
    for relative in COMMANDS:
        print(f"\nRunning {relative}", flush=True)
        subprocess.run([sys.executable, str(ROOT / relative)], cwd=ROOT, check=True)
    print("\nSelected offline reproduction completed.", flush=True)


if __name__ == "__main__":
    main()
