#!/usr/bin/env python3
"""Backfill label-mapped PubMed references into bundled completed examples.

The approved pathway ranks, statistics, narratives and cell-context text remain
unchanged. This script only adds a small structured reference set produced by
the same disease × displayed cell/tissue label × intersection-gene search used
for new server runs.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent
WEB_APP = ROOT / "web_app"
sys.path.insert(0, str(WEB_APP))

import cell_context  # noqa: E402
from archive_lock import sync_bundled_archives  # noqa: E402


def load_json(path: Path, default=None):
    if not path.exists():
        return default
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def dump_json(path: Path, payload):
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", default=str(WEB_APP / "offline_completed_examples.json"))
    parser.add_argument("--cache", default=str(ROOT / ".cell_context_pubmed_cache.json"))
    parser.add_argument("--diseases", default="", help="comma-separated example codes; default: all")
    parser.add_argument("--max-references", type=int, default=3)
    parser.add_argument("--replace", action="store_true")
    args = parser.parse_args()

    archive_path = Path(args.archive).resolve()
    cache_path = Path(args.cache).resolve()
    payload = load_json(archive_path)
    if not isinstance(payload, dict) or not isinstance(payload.get("examples"), dict):
        raise ValueError(f"Invalid completed-example archive: {archive_path}")
    cache = load_json(cache_path, {})
    if not isinstance(cache, dict):
        cache = {}

    requested = {
        code.strip().upper() for code in args.diseases.split(",") if code.strip()
    }
    examples = payload["examples"]
    for code, example in examples.items():
        if requested and code.upper() not in requested:
            continue
        result = example.get("result") or {}
        pathways = result.get("pathways") or []
        disease = example.get("disease") or example.get("title") or result.get("disease") or code
        genes = result.get("input_genes") or result.get("query_genes") or []
        before = sum(bool(record.get("cell_context_evidence")) for record in pathways)
        print(f"{code}: checking {len(pathways)} pathways ({before} already referenced)", flush=True)
        cell_context.attach_cell_context_evidence(
            pathways,
            disease,
            genes=genes,
            max_references=max(1, min(5, args.max_references)),
            replace=args.replace,
            search_cache=cache,
        )
        after = sum(bool(record.get("cell_context_evidence")) for record in pathways)
        print(f"{code}: {after}/{len(pathways)} pathways now have mapped references", flush=True)
        dump_json(cache_path, cache)

    # The pinned AD record is the source of truth for future archive rebuilds.
    if "AD" in examples:
        dump_json(WEB_APP / "pinned_ad_example.json", examples["AD"])
    sync_bundled_archives(WEB_APP, payload)
    print(f"Updated {archive_path} and synchronized bundled demo files", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
