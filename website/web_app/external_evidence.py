"""Auditable external-gene evidence from linked PubMed records.

The submitted genes and their pathway intersection drive enrichment, ranking,
narratives and clusters.  This module builds a separate, explicitly non-ranking
layer from NCBI PubTator3 gene annotations on the pathway's linked papers.
PubTator identifiers are resolved through NCBI Gene and restricted to human
official symbols before anything is shown in the interface.

The layer is deliberately fail-soft: if either NCBI service is unavailable the
optional panel is omitted and the analysis result remains valid.
"""

from __future__ import annotations

import re
import time

import requests


MAX_EXTERNAL_EVIDENCE_GENES = 8
PUBTATOR_EXPORT_URL = (
    "https://www.ncbi.nlm.nih.gov/research/"
    "pubtator3-api/publications/export/biocjson"
)
NCBI_GENE_SUMMARY_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi"
GENE_SYMBOL_RE = re.compile(r"^[A-Z][A-Z0-9-]{1,24}$")


def _pmid(record):
    if not isinstance(record, dict):
        return ""
    return re.sub(r"\D", "", str(record.get("pmid") or record.get("PMID") or ""))


def _chunks(values, size):
    values = list(values or [])
    for start in range(0, len(values), size):
        yield values[start:start + size]


def _iter_bioc_documents(payload):
    """Yield documents from common BioC JSON response shapes."""
    if isinstance(payload, list):
        for item in payload:
            yield from _iter_bioc_documents(item)
        return
    if not isinstance(payload, dict):
        return
    documents = payload.get("documents")
    if isinstance(documents, list):
        for document in documents:
            if isinstance(document, dict):
                yield document
        return
    pubtator_documents = payload.get("PubTator3")
    if isinstance(pubtator_documents, list):
        for document in pubtator_documents:
            if isinstance(document, dict):
                yield document
        return
    if isinstance(payload.get("passages"), list):
        yield payload


def _pubtator_gene_ids(payload):
    """Return ``{pmid: {NCBI Gene IDs}}`` from a BioC JSON payload."""
    result = {}
    for document in _iter_bioc_documents(payload):
        pmid = re.sub(r"\D", "", str(document.get("id") or ""))
        if not pmid:
            continue
        gene_ids = set()
        for passage in document.get("passages") or []:
            if not isinstance(passage, dict):
                continue
            for annotation in passage.get("annotations") or []:
                if not isinstance(annotation, dict):
                    continue
                infons = annotation.get("infons") or {}
                if str(infons.get("type") or "").strip().lower() != "gene":
                    continue
                identifier = (
                    infons.get("identifier")
                    or infons.get("Identifier")
                    or infons.get("database_id")
                )
                for gene_id in re.findall(r"\d+", str(identifier or "")):
                    gene_ids.add(gene_id)
        result[pmid] = gene_ids
    return result


def _human_gene_symbols(payload):
    """Return ``{NCBI Gene ID: official human symbol}`` from ESummary JSON."""
    result = {}
    root = payload.get("result") if isinstance(payload, dict) else None
    if not isinstance(root, dict):
        return result
    uids = root.get("uids") or []
    for uid in uids:
        record = root.get(str(uid))
        if not isinstance(record, dict):
            continue
        organism = record.get("organism") if isinstance(record.get("organism"), dict) else {}
        try:
            taxid = int(record.get("taxid") or organism.get("taxid") or 0)
        except (TypeError, ValueError):
            continue
        if taxid != 9606:
            continue
        symbol = str(record.get("nomenclaturesymbol") or record.get("name") or "").strip().upper()
        if symbol and GENE_SYMBOL_RE.fullmatch(symbol):
            result[str(uid)] = symbol
    return result


def fetch_pubtator_gene_annotations(pmids, timeout=12, http_get=requests.get, sleep=time.sleep):
    """Fetch PubTator3 genes and normalize them to official human symbols.

    Returns ``{pmid: [symbols]}``.  Exceptions are contained because this
    optional corroboration layer must never block a pathway analysis.
    """
    unique_pmids = sorted(
        {re.sub(r"\D", "", str(value or "")) for value in (pmids or [])},
        key=lambda value: (len(value), value),
    )
    unique_pmids = [value for value in unique_pmids if value]
    if not unique_pmids:
        return {}

    try:
        ids_by_pmid = {}
        request_count = 0
        for batch in _chunks(unique_pmids, 100):
            if request_count:
                sleep(0.35)  # stay below NCBI's documented three requests/second
            response = http_get(
                PUBTATOR_EXPORT_URL,
                params={"pmids": ",".join(batch)},
                headers={"Accept": "application/json"},
                timeout=timeout,
            )
            request_count += 1
            response.raise_for_status()
            batch_result = _pubtator_gene_ids(response.json())
            for pmid, gene_ids in batch_result.items():
                ids_by_pmid.setdefault(pmid, set()).update(gene_ids)

        all_gene_ids = sorted(
            {gene_id for values in ids_by_pmid.values() for gene_id in values},
            key=lambda value: (len(value), value),
        )
        symbols_by_id = {}
        for batch in _chunks(all_gene_ids, 200):
            if request_count:
                sleep(0.35)
            response = http_get(
                NCBI_GENE_SUMMARY_URL,
                params={"db": "gene", "id": ",".join(batch), "retmode": "json"},
                timeout=timeout,
            )
            request_count += 1
            response.raise_for_status()
            symbols_by_id.update(_human_gene_symbols(response.json()))

        normalized = {}
        for pmid, gene_ids in ids_by_pmid.items():
            symbols = sorted({symbols_by_id[gene_id] for gene_id in gene_ids if gene_id in symbols_by_id})
            if symbols:
                normalized[pmid] = symbols
        return normalized
    except (requests.RequestException, ValueError, TypeError, AttributeError) as exc:
        print(f"[external-evidence] PubTator3 lookup skipped: {type(exc).__name__}: {str(exc)[:200]}")
        return {}


def build_external_evidence_genes(
    pathway,
    input_genes=None,
    annotations_by_pmid=None,
    max_genes=MAX_EXTERNAL_EVIDENCE_GENES,
):
    """Build a deterministic, auditable external-gene list for one pathway."""
    if not isinstance(pathway, dict):
        return []

    excluded = {
        str(gene or "").strip().upper()
        for gene in (input_genes or [])
        if str(gene or "").strip()
    }
    excluded.update(
        str(gene or "").strip().upper()
        for gene in (pathway.get("intersection_genes") or [])
        if str(gene or "").strip()
    )

    support = {}
    annotations_by_pmid = annotations_by_pmid or {}
    for paper in pathway.get("literature") or []:
        pmid = _pmid(paper)
        if not pmid:
            continue
        for raw_symbol in annotations_by_pmid.get(pmid) or []:
            symbol = str(raw_symbol or "").strip().upper()
            if not GENE_SYMBOL_RE.fullmatch(symbol) or symbol in excluded:
                continue
            support.setdefault(symbol, set()).add(pmid)

    ordered = sorted(support.items(), key=lambda item: (-len(item[1]), item[0]))
    entries = []
    for gene, pmids in ordered[:max(0, int(max_genes or 0))]:
        sorted_pmids = sorted(pmids, key=lambda value: (len(value), value))
        entries.append({
            "gene": gene,
            "categories": ["PubTator3 literature gene"],
            "evidence_count": len(sorted_pmids),
            "source_refs": [f"PMID:{pmid}" for pmid in sorted_pmids],
            "pmids": sorted_pmids,
        })
    return entries


def attach_external_evidence_genes(
    pathway_records,
    input_genes=None,
    max_genes=MAX_EXTERNAL_EVIDENCE_GENES,
    annotations_by_pmid=None,
):
    """Attach optional external evidence to pathway records in place."""
    pathways = [record for record in (pathway_records or []) if isinstance(record, dict)]
    if annotations_by_pmid is None:
        pmids = {
            _pmid(paper)
            for pathway in pathways
            for paper in (pathway.get("literature") or [])
            if _pmid(paper)
        }
        annotations_by_pmid = fetch_pubtator_gene_annotations(pmids)

    for pathway in pathways:
        entries = build_external_evidence_genes(
            pathway,
            input_genes=input_genes,
            annotations_by_pmid=annotations_by_pmid,
            max_genes=max_genes,
        )
        # Never leave stale evidence when a result is regenerated with a new
        # input list or literature snapshot.
        pathway.pop("external_evidence_genes", None)
        pathway.pop("external_evidence_note", None)
        pathway.pop("external_evidence_provenance", None)
        if not entries:
            continue
        pathway["external_evidence_genes"] = entries
        pathway["external_evidence_note"] = (
            "Genes annotated by NCBI PubTator3 in the linked pathway–disease papers, normalized "
            "to human NCBI Gene symbols, and excluding submitted and intersection genes. They "
            "are external corroboration and are not used for enrichment, ranking, narrative "
            "drivers or functional clusters."
        )
        pathway["external_evidence_provenance"] = {
            "scope": "pathway-level",
            "source": "NCBI PubTator3 gene annotations normalized through NCBI Gene",
            "selection": "linked pathway–disease literature; submitted and intersection genes excluded",
            "used_for_ranking": False,
        }
    return pathway_records
