#!/usr/bin/env python3
"""Recompute and snapshot the enrichment matrix used by the offline demo.

The historical run retained the original input genes and pathway-level counts,
but not the query-term intersection members. This script replays the original
g:Profiler request, stores the complete response, and resolves the returned
Ensembl identifiers to human-readable gene symbols. The browser demo is built
from this snapshot rather than from narrative gene mentions.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
from datetime import datetime, timezone
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parent
HISTORY_PATH = PROJECT_DIR / "web_app" / "run_history.json"
DEFAULT_OUTPUT_PATH = PROJECT_DIR / "demo_sources" / "gprofiler_profile.json"

PROFILE_REQUEST = {
    "organism": "hsapiens",
    "sources": ["GO:BP", "GO:MF", "GO:CC", "KEGG", "REAC"],
    "user_threshold": 1.0,
    "significance_threshold_method": "fdr",
    "no_evidences": False,
    "all_results": False,
    "ordered": False,
    "domain_scope": "annotated",
    "no_iea": False,
}


def select_demo_entry(history: list[dict]) -> dict:
    """Return the most recently completed historical run."""
    completed = [entry for entry in history if entry.get("status") == "completed"]
    if not completed:
        raise RuntimeError("No completed analysis is available for the offline demo.")
    return max(completed, key=lambda entry: str(entry.get("completed_at") or ""))


def input_sha256(genes: list[str]) -> str:
    canonical = "\n".join(str(gene).strip() for gene in genes) + "\n"
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def build_snapshot(history_path: Path = HISTORY_PATH) -> dict:
    try:
        from gprofiler import GProfiler
    except ImportError as exc:
        raise RuntimeError(
            "gprofiler-official is required; install the project requirements first."
        ) from exc

    history = json.loads(history_path.read_text(encoding="utf-8"))
    entry = select_demo_entry(history)
    genes = [str(gene).strip() for gene in entry.get("genes", []) if str(gene).strip()]
    if not genes:
        raise RuntimeError("The selected historical run has no saved input genes.")
    if len(genes) != int(entry.get("gene_count") or len(genes)):
        raise RuntimeError("Saved gene_count does not match the historical input list.")

    profile_client = GProfiler(
        return_dataframe=False,
        user_agent="GenePathwayAI-demo-recovery/1.0",
    )
    rows = profile_client.profile(query=genes, **PROFILE_REQUEST)
    profile_meta = profile_client.meta
    if not rows:
        raise RuntimeError("g:Profiler returned an empty enrichment matrix.")

    failed = profile_meta.get("genes_metadata", {}).get("failed", [])
    if failed:
        raise RuntimeError(f"g:Profiler could not map historical inputs: {failed}")

    convert_client = GProfiler(
        return_dataframe=False,
        user_agent="GenePathwayAI-demo-recovery/1.0",
    )
    conversions = convert_client.convert(
        organism=PROFILE_REQUEST["organism"],
        query=genes,
        target_namespace="ENSG",
    )
    conversion_meta = convert_client.meta

    symbol_by_id: dict[str, str] = {}
    gene_metadata: dict[str, dict] = {}
    for record in conversions:
        incoming = str(record.get("incoming") or "").strip()
        converted = str(record.get("converted") or incoming).strip()
        symbol = str(record.get("name") or "").strip()
        if not incoming:
            continue
        display_symbol = symbol if symbol and symbol.upper() != "N/A" else incoming
        symbol_by_id[incoming] = display_symbol
        if converted:
            symbol_by_id.setdefault(converted, display_symbol)
        gene_metadata[incoming] = {
            "ensembl_id": converted or incoming,
            "symbol": display_symbol,
            "description": str(record.get("description") or "").strip(),
            "namespaces": str(record.get("namespaces") or "").strip(),
        }

    mapped_symbols = sum(1 for gene in genes if symbol_by_id.get(gene, gene) != gene)
    for row in rows:
        intersections = [str(gene).strip() for gene in row.get("intersections", [])]
        intersections = [gene for gene in intersections if gene]
        if len(intersections) != int(row.get("intersection_size") or 0):
            raise RuntimeError(
                f"Intersection size mismatch for {row.get('source')} {row.get('native')}: "
                f"{row.get('intersection_size')} != {len(intersections)}"
            )
        row["intersection_gene_symbols"] = [
            symbol_by_id.get(gene, gene) for gene in intersections
        ]

    matrix_payload = json.dumps(
        rows,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")

    return {
        "schema_version": 1,
        "snapshot_generated_at": datetime.now(timezone.utc).isoformat(),
        "source": {
            "provider": "g:Profiler",
            "base_url": profile_client.base_url,
            "python_package": "gprofiler-official",
            "python_package_version": importlib.metadata.version("gprofiler-official"),
        },
        "request": PROFILE_REQUEST,
        "historical_run": {
            "session_id": entry.get("session_id"),
            "disease": entry.get("disease"),
            "disease_name": entry.get("disease_name"),
            "created_at": entry.get("created_at"),
            "completed_at": entry.get("completed_at"),
            "gene_count": len(genes),
            "input_sha256": input_sha256(genes),
        },
        "input_genes": genes,
        "gene_metadata": gene_metadata,
        "mapping_summary": {
            "input_count": len(genes),
            "failed_count": len(failed),
            "symbol_mapped_count": mapped_symbols,
        },
        "gprofiler_meta": profile_meta,
        "gconvert_meta": conversion_meta,
        "matrix_row_count": len(rows),
        "matrix_sha256": hashlib.sha256(matrix_payload).hexdigest(),
        "rows": rows,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--history", type=Path, default=HISTORY_PATH)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH)
    args = parser.parse_args()

    snapshot = build_snapshot(args.history)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = args.output.with_suffix(args.output.suffix + ".tmp")
    temporary_path.write_text(
        json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary_path.replace(args.output)

    version = snapshot.get("gprofiler_meta", {}).get("version", "unknown")
    timestamp = snapshot.get("gprofiler_meta", {}).get("timestamp", "unknown")
    print(
        f"Saved {snapshot['matrix_row_count']:,} g:Profiler rows to {args.output} "
        f"(data version {version}, timestamp {timestamp})."
    )


if __name__ == "__main__":
    main()
