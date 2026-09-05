#!/usr/bin/env python3
"""Build the Figure 6 Alzheimer's disease completed example from real run data.

This is intentionally a focused archive builder. It replaces only the AD
completed example, preserves every other disease example, and mirrors the same
AD result into the legacy offline-demo fallback.
"""

from __future__ import annotations

import argparse
import ast
import collections
import csv
import json
import math
import re
import urllib.request
from pathlib import Path


MODULE_ID = "11"
RUN_ID = "AD_aggregated_20260808_070136"
FDR_THRESHOLD = 0.05
DATABASE_ORDER = ("GO:BP", "GO:MF", "GO:CC", "KEGG", "REAC")

FIGURE6_LITERATURE = [
    {
        "pmid": "35379992",
        "title": "New insights into the genetic etiology of Alzheimer's disease and related dementias",
        "journal": "Nature Genetics",
        "year": "2022",
    },
    {
        "pmid": "34493870",
        "title": "A genome-wide association study with 1,126,563 individuals identifies new risk loci for Alzheimer's disease",
        "journal": "Nature Genetics",
        "year": "2021",
    },
    {
        "pmid": "31042697",
        "title": "Single-cell transcriptomic analysis of Alzheimer's disease",
        "journal": "Nature",
        "year": "2019",
    },
    {
        "pmid": "39048816",
        "title": "Single-cell multiregion dissection of Alzheimer's disease",
        "journal": "Nature",
        "year": "2024",
    },
    {
        "pmid": "39578645",
        "title": "Spatial and single-nucleus transcriptomic analysis of genetic and sporadic forms of Alzheimer's disease",
        "journal": "Nature Genetics",
        "year": "2024",
    },
    {
        "pmid": "39402332",
        "title": "SEA-AD is a multimodal cellular atlas and resource for Alzheimer's disease",
        "journal": "Nature Aging",
        "year": "2024",
    },
]


def parse_args() -> argparse.Namespace:
    script_dir = Path(__file__).resolve().parent
    source_root = script_dir.parents[1]
    ai_agent_root = source_root.parents[4]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, default=source_root)
    parser.add_argument(
        "--context-xlsx",
        type=Path,
        default=(
            ai_agent_root
            / "Paper/Genetic_Agentic-system/paper_v5_260805/supplementary/"
            "Supplementary_Table_3_AD_pathway_context_evidence_aligned_20260818.xlsx"
        ),
    )
    parser.add_argument("--web-app", type=Path, default=script_dir / "web_app")
    parser.add_argument("--symbol-cache", type=Path, default=script_dir / ".ensembl_symbol_cache.json")
    parser.add_argument("--offline-symbols", action="store_true", help="do not query g:Profiler for missing symbols")
    parser.add_argument(
        "--replace-pinned-ad",
        action="store_true",
        help="explicitly replace the protected AD Featured/Completed example",
    )
    return parser.parse_args()


def parse_list(value) -> list[str]:
    text = str(value or "").strip()
    if not text or text in {"[]", "nan"}:
        return []
    parsed = ast.literal_eval(text)
    return [str(item).strip() for item in parsed if str(item).strip()]


def clean_definition(value) -> str:
    text = str(value or "").strip()
    text = re.sub(r'^\s*["“”]+|["“”]+\s*$', "", text).strip()
    text = re.sub(r"\s*\[(?:GOC|PMID|ISBN|Reactome|KEGG|Wikipedia)[^\]]*\]\s*$", "", text).strip()
    return text


def normalize_name(value) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).strip()


def load_symbol_cache(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def refresh_symbols(ensembl_ids: list[str], cache: dict[str, str]) -> None:
    missing = [gene_id for gene_id in ensembl_ids if gene_id not in cache]
    if not missing:
        return
    payload = json.dumps({
        "organism": "hsapiens",
        "target": "ENSG",
        "query": missing,
    }).encode("utf-8")
    request = urllib.request.Request(
        "https://biit.cs.ut.ee/gprofiler/api/convert/convert/",
        data=payload,
        headers={"Content-Type": "application/json", "User-Agent": "GenePathwayAI-archive-builder"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=90) as response:
        result = json.loads(response.read().decode("utf-8"))
    for record in result.get("result") or []:
        incoming = str(record.get("incoming") or "").strip()
        symbol = str(record.get("name") or "").strip()
        if incoming and symbol and symbol.lower() not in {"none", "nan"}:
            cache[incoming] = symbol


def worksheet_records(sheet) -> list[dict]:
    rows = sheet.iter_rows(values_only=True)
    headers = [str(value or "").strip() for value in next(rows)]
    return [
        {headers[index]: values[index] for index in range(len(headers))}
        for values in rows
    ]


def load_context_and_independent_evidence(path: Path):
    import openpyxl

    workbook = openpyxl.load_workbook(path, read_only=True, data_only=True)
    context_records = [
        record for record in worksheet_records(workbook["AD_pathway_contexts_310"])
        if str(record.get("module_id") or "").strip() == MODULE_ID
        and str(record.get("latest_run") or "").strip() == RUN_ID
    ]
    contexts = {
        str(record.get("pathway_id") or "").strip(): {
            "text": str(record.get("cell_context_text") or "").strip(),
            "tags": [tag.strip() for tag in str(record.get("context_tags") or "").split(";") if tag.strip()],
            "parsed": bool(record.get("parsed_context_tag_available")),
            "mapping_method": str(record.get("mapping_method") or "").strip(),
            "reasoning_file": str(record.get("reasoning_file") or "").strip(),
        }
        for record in context_records
    }
    independent = []
    for record in worksheet_records(workbook["Evidence_provenance"]):
        if normalize_name(record.get("Pathway")) != "endocytosis":
            continue
        independent.append({
            "gene": str(record.get("Gene") or "").strip(),
            "categories": [
                value.strip() for value in str(record.get("Evidence_category") or "").split(";") if value.strip()
            ],
            "cell_sets": [
                value.strip() for value in str(record.get("Atlas_cell_sets") or "").split(";")
                if value.strip() and value.strip() != "—"
            ],
            "source_refs": [
                value.strip() for value in str(record.get("Source_refs") or "").split(";") if value.strip()
            ],
        })
    independent.sort(key=lambda record: record["gene"])
    return contexts, independent


def parse_reasoning_bullets(path: Path, heading: str) -> dict[str, str]:
    text = path.read_text(encoding="utf-8")
    match = re.search(rf"^## {re.escape(heading)}\s*$\n(.*?)(?=^## |\Z)", text, flags=re.MULTILINE | re.DOTALL)
    if not match:
        return {}
    bullets = {}
    for line in match.group(1).splitlines():
        line = line.strip()
        if not line.startswith("- ") or ":" not in line:
            continue
        label, body = line[2:].split(":", 1)
        bullets[normalize_name(label)] = body.strip()
    return bullets


def load_biological_evidence(source_root: Path) -> dict[tuple[str, str], str]:
    reasoning_dir = source_root / f"iterative_feedback_AD/{RUN_ID}/phase2_module_iteration/Module_11"
    filename_by_source = {
        "GO:BP": "GO_BP",
        "GO:MF": "GO_MF",
        "GO:CC": "GO_CC",
        "KEGG": "KEGG",
        "REAC": "REAC",
    }
    evidence = {}
    for source, filename_part in filename_by_source.items():
        path = reasoning_dir / f"AD_Module_11_iter2_{filename_part}_reasoning.md"
        for name, text in parse_reasoning_bullets(path, "Biological Evidence").items():
            evidence[(source, name)] = text
    return evidence


def annotate_hierarchy(records: list[dict]) -> None:
    by_id = {record["pathway_id"]: record for record in records if record.get("pathway_id")}
    for record in records:
        parents = [parent for parent in record.get("parents") or [] if parent in by_id]
        record["hierarchy"] = {
            "parents_in_set": parents,
            "parent_names_in_set": [by_id[parent]["name"] for parent in parents],
            "children_in_set": [],
            "child_names_in_set": [],
        }
    for record in records:
        for parent_id in record["hierarchy"]["parents_in_set"]:
            parent = by_id[parent_id]
            parent["hierarchy"]["children_in_set"].append(record["pathway_id"])
            parent["hierarchy"]["child_names_in_set"].append(record["name"])


def build_pathway_records(rows, symbol_cache, contexts, independent_evidence, biological_evidence):
    rank_by_source = collections.Counter()
    tier_by_source = collections.Counter()
    records = []
    for row in rows:
        source = str(row.get("source") or "").strip()
        native = str(row.get("native") or "").strip()
        name = str(row.get("name") or "Unknown pathway").strip()
        ensembl_ids = parse_list(row.get("intersections"))
        symbols = [symbol_cache.get(gene_id) or gene_id for gene_id in ensembl_ids]
        p_value = float(row["p_value"])
        intersection_size = int(float(row.get("intersection_size") or len(ensembl_ids)))
        term_size = int(float(row.get("term_size") or 0))
        rank_by_source[source] += 1
        tier_by_source[source] += 1
        context = contexts.get(native) or {}
        biology = biological_evidence.get((source, normalize_name(name)), "")
        if not context.get("text"):
            raise RuntimeError(f"Missing pathway-level cell context for {source} {native} {name}")
        if not biology:
            raise RuntimeError(f"Missing archived biological evidence for {source} {native} {name}")

        key_genes = [gene.strip() for gene in str(row.get("gpt_key_genes") or "").split(",") if gene.strip()]
        driver_genes = [gene for gene in key_genes if gene in symbols][:6]
        opening = (
            f"Exactly {intersection_size} Alzheimer's Disease-associated proteins were significantly enriched "
            f"in the {name} pathway ({native})."
        )
        paragraphs = [
            {"text": opening, "pmids": []},
            {"text": biology, "pmids": []},
        ]
        literature = []
        pmids = []
        clusters = []
        independent = []
        if native == "GO:0006897":
            literature = FIGURE6_LITERATURE
            pmids = [record["pmid"] for record in literature]
            independent = independent_evidence
            paragraphs[1]["pmids"] = pmids
            paragraphs.append({
                "text": (
                    "Endocytic handling of APP and lipoprotein receptors couples neuronal receptor cycling to "
                    "microglial uptake and clearance, linking the top-ranked GO:BP terms into one trafficking axis."
                ),
                "pmids": pmids,
            })

        description = clean_definition(row.get("description"))
        gene_text = (
            f"The enrichment calculation used {intersection_size} input–pathway intersection genes: "
            f"{', '.join(symbols)}."
        )
        literature_text = (
            "Six independent AD genetics and brain cell-atlas sources support the evidence markers shown below."
            if literature else
            "No pathway-specific PubMed records were archived for this source result; the interpretation is retained from the server reasoning trace."
        )
        record = {
            "name": name,
            "p_value": p_value,
            "category": source,
            "source": source,
            "native": native,
            "pathway_id": native,
            "significant": True,
            "score": round(-math.log10(max(p_value, 1e-300)), 4),
            "gpt_rank": rank_by_source[source],
            "gpt_predicted": str(row.get("gpt_predicted") or "").lower() == "true",
            "iteration_source": int(float(row.get("iteration_source") or 1)),
            "reporting_tier": "primary" if tier_by_source[source] <= 3 else "supporting",
            "term_size": term_size,
            "query_size": int(float(row.get("query_size") or 0)),
            "intersection_size": intersection_size,
            "resolved_symbol_count": sum(not gene.startswith("ENSG") for gene in symbols),
            "unresolved_gene_count": sum(gene.startswith("ENSG") for gene in symbols),
            "intersection_gene_ids": ensembl_ids,
            "intersection_genes": symbols,
            "genes": ",".join(symbols),
            "parents": parse_list(row.get("parents")),
            "description": description,
            "pathway_description": description,
            "disease_interpretation": biology,
            "interpretation_points": [
                {"label": "Biological context", "text": biology},
                {"label": "Intersection-gene interpretation", "text": gene_text},
                {"label": "Disease pathology and relevance", "text": biology},
                {"label": "Cell / Tissue Context", "text": context["text"]},
                {"label": "PubMed literature synthesis", "text": literature_text},
            ],
            "cell_context": context["text"],
            "cell_context_tags": context.get("tags") or [],
            "cell_context_pmids": [],
            "cell_context_provenance": {
                "scope": "pathway-level",
                "disease": "Alzheimer's disease",
                "disease_id": "MeSH:D000544",
                "module": "Module 11",
                "run_id": RUN_ID,
                "source_type": "server-reasoning-archive",
                "reasoning_file": context.get("reasoning_file") or "",
                "mapping_method": context.get("mapping_method") or "",
                "parsed_context_tag_available": bool(context.get("parsed")),
            },
            "literature": literature,
            "pmids": pmids,
            "pathway_narrative": {
                "generated": True,
                "source": "archived-server-reasoning",
                "paragraphs": paragraphs,
                "driver_genes": driver_genes,
                "clusters": clusters,
            },
            "enrichment_source": {
                "run_id": RUN_ID,
                "module_id": 11,
                "source_file": "final_aggregated_pathways.csv",
                "fdr_threshold": FDR_THRESHOLD,
            },
        }
        if independent:
            record["independent_evidence_genes"] = independent
            record["independent_evidence_note"] = (
                "Cross-module AD genetics and cell-atlas evidence; these markers are not used in the 19/694 enrichment calculation."
            )
        records.append(record)

    records.sort(key=lambda record: (DATABASE_ORDER.index(record["source"]), record["gpt_rank"]))
    annotate_hierarchy(records)
    return records


def build_example(records: list[dict], all_symbols: list[str]) -> dict:
    counts = collections.Counter(record["source"] for record in records)
    parsed_context_count = sum(bool(record.get("cell_context_provenance", {}).get("parsed_context_tag_available")) for record in records)
    result = {
        "pathways": records,
        "disease": "Alzheimer's disease",
        "disease_name": "Alzheimer's disease",
        "gene_count": 152,
        "input_genes": all_symbols,
        "query_genes": all_symbols,
        "enrichment_provenance": {
            "run_id": RUN_ID,
            "gene_list": "AD_gene_list_11",
            "module_id": 11,
            "source_file": "final_aggregated_pathways.csv",
            "fdr_threshold": FDR_THRESHOLD,
            "ranking_basis": "final aggregated output order within each source database",
        },
        "run_summary": {
            "validation_status": "Statistically validated",
            "significant_pathways": 25,
            "total_pathways": 25,
            "ranked_pathways": 25,
            "categories_covered": 5,
            "gene_count": 152,
            "mapped_gene_count": sum(not gene.startswith("ENSG") for gene in all_symbols),
            "unmapped_gene_count": sum(gene.startswith("ENSG") for gene in all_symbols),
            "disease_id": "D000544",
            "prompt_rounds": 2,
            "parsed_context_pathways": parsed_context_count,
            "context_text_pathways": 25,
            "pubmed_articles": len(FIGURE6_LITERATURE),
            "cell_context_pathways": 25,
            "cell_context_summary": [
                {"label": "Neurons", "count": 21, "total": 25},
                {"label": "Glial cells", "count": 14, "total": 25},
                {"label": "Endothelial cells", "count": 4, "total": 25},
                {"label": "Immune cells", "count": 1, "total": 25},
            ],
            "source_counts": dict(counts),
        },
        "mapping_summary": {
            "input_count": 152,
            "mapped_count": sum(not gene.startswith("ENSG") for gene in all_symbols),
            "failed_count": sum(gene.startswith("ENSG") for gene in all_symbols),
        },
        "disease_context": {"name": "Alzheimer's disease", "mesh_id": "D000544"},
        "validation_comparison": {
            "initial_hypotheses": None,
            "statistically_validated": 25,
            "rounds": [
                {"round": 1, "label": "Initial prompt"},
                {"round": 2, "label": "Feedback-refined prompt"},
            ],
            "by_database": {
                source: {"initial_hypotheses": None, "statistically_validated": counts[source]}
                for source in DATABASE_ORDER
            },
        },
        # Preserve the historical demo session ID so server-side PDF/CSV/JSON
        # export routes remain backward compatible after the archive refresh.
        "session_id": "85bd55b2",
        "created_at": "2026-08-08T07:01:36",
        "completed_at": "2026-08-08T09:10:24",
        "demo_mode": True,
        "archive_version": "figure6-ad-module11-20260823",
        "reasoning_traces": [],
    }
    return {
        "code": "AD",
        "title": "Alzheimer's disease",
        "disease": "Alzheimer's disease",
        "subtitle": "Alzheimer's disease — AD gene list 11 (module 11, n=152) · 25 validated pathways",
        "module": "Alzheimer's disease — AD gene list 11 (module 11, n=152)",
        "gene_count": 152,
        "pathway_count": 25,
        "session_id": result["session_id"],
        "result": result,
    }


def write_json_and_js(path_json: Path, path_js: Path, variable: str, payload) -> None:
    path_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    path_js.write_text(f"window.{variable} = " + json.dumps(payload, ensure_ascii=False, indent=2) + ";\n", encoding="utf-8")


def main() -> None:
    args = parse_args()
    if not args.replace_pinned_ad:
        raise SystemExit(
            "AD Featured/Completed example is pinned to module 6. "
            "Pass --replace-pinned-ad only when an intentional archive migration is approved."
        )
    csv_path = args.source_root / f"iterative_feedback_AD/{RUN_ID}/final_aggregated_pathways.csv"
    with csv_path.open(encoding="utf-8") as handle:
        rows = [
            row for row in csv.DictReader(handle)
            if str(row.get("module_id") or "").strip() == MODULE_ID
            and float(row.get("p_value") or 1) < FDR_THRESHOLD
        ]
    if len(rows) != 25:
        raise RuntimeError(f"Expected 25 validated Module 11 pathways, found {len(rows)}")

    all_ensembl = sorted({gene_id for row in rows for gene_id in parse_list(row.get("intersections"))})
    if len(all_ensembl) != 152:
        raise RuntimeError(f"Expected 152 unique input genes across the retained pathways, found {len(all_ensembl)}")
    symbol_cache = load_symbol_cache(args.symbol_cache)
    if not args.offline_symbols:
        refresh_symbols(all_ensembl, symbol_cache)
    args.symbol_cache.write_text(json.dumps(symbol_cache, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    contexts, independent_evidence = load_context_and_independent_evidence(args.context_xlsx)
    if len(contexts) != 25:
        raise RuntimeError(f"Expected 25 Module 11 pathway contexts, found {len(contexts)}")
    if len(independent_evidence) != 8:
        raise RuntimeError(f"Expected 8 Figure 6 independent evidence markers, found {len(independent_evidence)}")
    biology = load_biological_evidence(args.source_root)
    records = build_pathway_records(rows, symbol_cache, contexts, independent_evidence, biology)
    all_symbols = [symbol_cache.get(gene_id) or gene_id for gene_id in all_ensembl]
    example = build_example(records, all_symbols)

    completed_json = args.web_app / "offline_completed_examples.json"
    completed_payload = json.loads(completed_json.read_text(encoding="utf-8"))
    completed_payload["examples"]["AD"] = example
    write_json_and_js(
        completed_json,
        args.web_app / "offline_completed_examples.js",
        "OFFLINE_COMPLETED_EXAMPLES",
        completed_payload,
    )
    write_json_and_js(
        args.web_app / "offline_demo_data.json",
        args.web_app / "offline_demo_data.js",
        "OFFLINE_DEMO_RESULT",
        example["result"],
    )

    endocytosis = next(record for record in records if record["pathway_id"] == "GO:0006897")
    print(f"Updated AD archive: {len(records)} pathways across {len(set(record['source'] for record in records))} databases")
    print(
        "Endocytosis: "
        f"rank #{endocytosis['gpt_rank']} GO:BP, p={endocytosis['p_value']:.8g}, "
        f"overlap={endocytosis['intersection_size']}/{endocytosis['term_size']}"
    )
    print(
        f"Contexts: {example['result']['run_summary']['parsed_context_pathways']}/25 parsed tags, "
        f"{example['result']['run_summary']['context_text_pathways']}/25 context text"
    )
    print(f"Symbol mapping: {len(symbol_cache)}/152 cached")


if __name__ == "__main__":
    main()
