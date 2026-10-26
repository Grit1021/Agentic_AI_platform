#!/usr/bin/env python3
"""Plan or launch the 24-disease benchmark from the deposited 567 inputs.

Planning is offline and makes no API calls. --execute starts the historical
orchestrator one disease at a time and incurs external API requests and costs.
"""

from __future__ import annotations

import argparse
import csv
import os
import subprocess
import sys
from collections import Counter
from pathlib import Path

from verify_benchmark_artifacts import verify_inputs


ROOT = Path(__file__).resolve().parents[1]


def rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--disease", help="Run or plan one abbreviation, e.g. AD")
    parser.add_argument("--execute", action="store_true",
                        help="Actually call the live external-service pipeline")
    parser.add_argument("--tag", default="live_benchmark",
                        help="Output tag passed to orchestrator")
    args = parser.parse_args()

    verify_inputs()

    inputs = rows(ROOT / "data" / "gene_lists_567.csv")
    sources = rows(ROOT / "data" / "source_manifest.csv")
    counts = Counter(row["disease"] for row in inputs)
    if len(inputs) != 567 or len(sources) != 24 or len(counts) != 24:
        raise SystemExit("Expected 567 lists from 24 diseases")
    for source in sources:
        disease = source["disease"]
        if counts[disease] != int(source["gene_list_count"]):
            raise SystemExit(f"Source manifest count mismatch: {disease}")
        if not (ROOT / "data" / source["source_file"]).is_file():
            raise SystemExit(f"Source CSV missing: {source['source_file']}")
    selection = [row for row in sources if not args.disease or
                 row["disease"] == args.disease.upper()]
    if not selection:
        raise SystemExit(f"Disease not in benchmark: {args.disease}")

    package_name = ROOT.name
    command = [sys.executable, "-m", f"{package_name}.orchestrator"]
    for source in selection:
        disease = source["disease"]
        print(f"{disease}: {counts[disease]} gene lists; "
              f"{source['source_file']}; model=gpt-5.1", flush=True)
        if args.execute:
            if not os.environ.get("OPENAI_API_KEY"):
                raise SystemExit("OPENAI_API_KEY is required for --execute")
            env = os.environ.copy()
            env["CURRENT_DISEASE"] = disease
            env["BENCHMARK_MODULES_DIR"] = str(ROOT / "data" / "source_modules")
            env["PYTHONPATH"] = str(ROOT.parent) + os.pathsep + env.get("PYTHONPATH", "")
            subprocess.run(command + ["--disease", disease, "--tag", args.tag],
                           cwd=ROOT.parent, env=env, check=True)
    if not args.execute:
        print(f"Dry run: {sum(counts[row['disease']] for row in selection)} inputs "
              f"in {len(selection)} diseases; no API calls made.")


if __name__ == "__main__":
    main()
