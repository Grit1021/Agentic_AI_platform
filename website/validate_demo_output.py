#!/usr/bin/env python3
"""Validate that the bundled demo is fully traceable to its enrichment snapshot."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parent
SNAPSHOT_PATH = PROJECT_DIR / "demo_sources" / "gprofiler_profile.json"
DEMO_PATH = PROJECT_DIR / "web_app" / "offline_demo_data.js"
DEMO_PREFIX = "window.OFFLINE_DEMO_RESULT="


def read_demo(path=DEMO_PATH):
    source = path.read_text(encoding="utf-8").strip()
    if not source.startswith(DEMO_PREFIX) or not source.endswith(";"):
        raise AssertionError("offline_demo_data.js is not a valid bundled result assignment.")
    return json.loads(source[len(DEMO_PREFIX) : -1])


def main():
    snapshot = json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))
    demo = read_demo()
    rows = snapshot["rows"]
    rows_by_id = {(row["source"], row["native"]): row for row in rows}
    inputs = set(demo["input_genes"])

    canonical_rows = json.dumps(
        rows,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    actual_matrix_hash = hashlib.sha256(canonical_rows).hexdigest()
    assert actual_matrix_hash == snapshot["matrix_sha256"]
    assert actual_matrix_hash == demo["enrichment_provenance"]["matrix_sha256"]
    assert snapshot["historical_run"]["input_sha256"] == demo["enrichment_provenance"]["input_sha256"]
    assert snapshot["mapping_summary"]["failed_count"] == 0
    assert snapshot["mapping_summary"]["symbol_mapped_count"] == len(inputs) == 140

    for pathway in demo["pathways"]:
        source_key = (pathway["source"], pathway["native"])
        assert source_key in rows_by_id, f"Missing matrix row for {source_key}"
        row = rows_by_id[source_key]
        assert pathway["name"] == row["name"]
        assert pathway["p_value"] == row["p_value"]
        assert pathway["intersection_size"] == row["intersection_size"]
        assert pathway["intersection_gene_ids"] == row["intersections"]
        assert pathway["intersection_genes"] == row["intersection_gene_symbols"]
        assert len(pathway["intersection_gene_ids"]) == pathway["intersection_size"]
        assert set(pathway["intersection_gene_ids"]).issubset(inputs)
        assert pathway["description"] == pathway["disease_interpretation"]
        assert not pathway["pathway_description"].startswith(('"', '“', '”'))
        assert '" [' not in pathway["pathway_description"]
        interpretation_points = pathway.get("interpretation_points") or []
        assert [point.get("label") for point in interpretation_points] == [
            "Biological context",
            "Gene-level support",
            "Disease relevance",
        ]
        assert all(str(point.get("text") or "").strip() for point in interpretation_points)
        assert pathway.get("historical_interpretation_unverified") is not None
        assert str(pathway.get("cell_context") or "").strip()
        context_pmids = {
            str(pmid) for pmid in pathway.get("cell_context_pmids", []) if pmid
        }
        attached_pmids = {str(pmid) for pmid in pathway.get("pmids", []) if pmid}
        attached_pmids.update(
            str(record.get("pmid") or record.get("PMID"))
            for record in pathway.get("literature", [])
            if isinstance(record, dict) and (record.get("pmid") or record.get("PMID"))
        )
        assert context_pmids
        assert context_pmids.issubset(attached_pmids)
        context_provenance = pathway.get("cell_context_provenance") or {}
        assert context_provenance.get("scope") == "pathway-level"
        assert context_provenance.get("source_type") == "dedicated-pathway-interpretation-pass"
        assert (
            context_provenance.get("interpretation_pass_id")
            == "ad-module6-final-pathway-context-20260809-v2"
        )
        assert context_provenance.get("generated_at") == "2026-08-09"
        assert len(context_provenance.get("evidence_contract") or []) == 4
        assert "source_file" not in context_provenance
        assert "prompt_pass" not in context_provenance

    acute = next(
        pathway for pathway in demo["pathways"] if pathway["native"] == "GO:0002526"
    )
    assert acute["intersection_size"] == 4
    assert acute["intersection_gene_ids"] == [
        "ENSG00000197561",
        "ENSG00000228278",
        "ENSG00000229314",
        "ENSG00000257017",
    ]
    assert acute["intersection_genes"] == ["ELANE", "ORM2", "ORM1", "HP"]

    print(
        f"Validated {len(demo['pathways'])} demo pathways against "
        f"{snapshot['matrix_row_count']:,} g:Profiler rows; all intersections are input members."
    )
    print(
        "GO:0002526 true 4-gene intersection: "
        + ", ".join(acute["intersection_genes"])
    )


if __name__ == "__main__":
    main()
