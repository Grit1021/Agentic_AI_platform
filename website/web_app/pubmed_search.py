"""PubMed retrieval for pathway-disease evidence.

Shared by the Flask application and by the offline archive builder
(``build_completed_examples.py``) so a backfilled archive carries exactly the
literature a live run would have attached: same query construction, same
relevance ordering, same abstract-only filter.
"""

import os
import re
import time


ENTREZ_EMAIL = os.environ.get('ENTREZ_EMAIL', '')

# Module-name suffixes such as "T2D_Module_117_iter1" are stripped back to the
# disease before querying; the caller may extend this map.
ABBREVIATION_EXPANSION = {
    'AD': "Alzheimer's disease",
    'ALS': 'Amyotrophic lateral sclerosis',
    'IBD': 'Inflammatory bowel disease',
    'MS': 'Multiple sclerosis',
    'PD': "Parkinson's disease",
    'RA': 'Rheumatoid arthritis',
    'T2D': 'Type 2 diabetes',
}


def search_pubmed_for_pathway_standalone(pathway_name: str, disease_name: str, max_results: int = 20):
    """
    Search PubMed for papers linking pathway to disease using Biopython Entrez.
    Standalone version for web app (no framework dependency).
    """
    try:
        from Bio import Entrez, Medline
        import time
        
        Entrez.email = ENTREZ_EMAIL or "researcher@example.com"
        
        # Clean disease name (remove module info if present)
        if "_Module_" in disease_name:
            disease_name = ABBREVIATION_EXPANSION.get(
                disease_name.split("_")[0].upper(), 
                disease_name.split("_")[0]
            )
        
        # Build query
        query = f'("{pathway_name}") AND ("{disease_name}")'
        
        try:
            handle = Entrez.esearch(db="pubmed", term=query, retmax=max_results, sort="relevance")
            record = Entrez.read(handle)
            handle.close()
        except Exception as e:
            time.sleep(1)  # Retry after delay
            handle = Entrez.esearch(db="pubmed", term=query, retmax=max_results, sort="relevance")
            record = Entrez.read(handle)
            handle.close()
        
        ids = record.get("IdList", [])
        if not ids:
            return "No PubMed results found", []
        
        # Fetch paper details
        handle = Entrez.efetch(db="pubmed", id=ids, rettype="medline", retmode="text")
        records = list(Medline.parse(handle))
        handle.close()
        
        # Filter: only papers with abstracts
        paper_list = []
        seen_titles = set()
        
        for i, rec in enumerate(records, 1):
            abstract = rec.get("AB", "")
            title = rec.get("TI", "No title")
            
            # Skip if no abstract or duplicate
            if not abstract or title.lower() in seen_titles:
                continue
            
            seen_titles.add(title.lower())
            
            paper_list.append({
                'pmid': rec.get("PMID", "N/A"),
                'title': title,
                'journal': rec.get("JT", rec.get("TA", "Unknown")),
                'year': rec.get("DP", "")[:4] if rec.get("DP") else "N/A",
                'relevance_score': 1.0 - (i / (len(records) + 1))
            })
        
        summary = f"Found {len(paper_list)} papers (of {len(ids)} total)"
        return summary, paper_list
        
    except ImportError:
        return "PubMed search unavailable (Biopython not installed)", []
    except Exception as e:
        return f"PubMed error: {str(e)[:50]}", []


CELL_CONTEXT_ALIASES = {
    'Pyramidal neurons': ('pyramidal neuron', 'pyramidal neurons'),
    'Hippocampal neurons': ('hippocampal neuron', 'hippocampal neurons'),
    'Cortical neurons': ('cortical neuron', 'cortical neurons'),
    'Excitatory neurons': ('excitatory neuron', 'excitatory neurons'),
    'Inhibitory neurons': ('inhibitory neuron', 'inhibitory neurons'),
    'Glutamatergic neurons': ('glutamatergic neuron', 'glutamatergic neurons'),
    'Dopaminergic neurons': ('dopaminergic neuron', 'dopaminergic neurons'),
    'Motor neurons': ('motor neuron', 'motor neurons'),
    'Microglia': ('microglia', 'microglial'),
    'Astrocytes': ('astrocyte', 'astrocytes', 'astrocytic'),
    'Neurons': ('neuron', 'neurons', 'neuronal'),
    'Oligodendrocytes': ('oligodendrocyte', 'oligodendrocytes', 'oligodendroglial'),
    'Endothelial cells': ('endothelial cell', 'endothelial cells', 'endothelium'),
    'Pericytes': ('pericyte', 'pericytes'),
    'Monocytes': ('monocyte', 'monocytes'),
    'Macrophages': ('macrophage', 'macrophages'),
    'T cells': ('T cell', 'T cells', 'T-cell'),
    'B cells': ('B cell', 'B cells', 'B-cell'),
    'Dendritic cells': ('dendritic cell', 'dendritic cells'),
    'Epithelial cells': ('epithelial cell', 'epithelial cells', 'epithelium'),
    'Fibroblasts': ('fibroblast', 'fibroblasts'),
    'Adipocytes': ('adipocyte', 'adipocytes', 'adipose'),
    'Hepatocytes': ('hepatocyte', 'hepatocytes', 'hepatic'),
    'Pancreatic β cells': ('pancreatic beta cell', 'pancreatic beta cells', 'islet beta cell'),
    'Enterocytes': ('enterocyte', 'enterocytes'),
    'Goblet cells': ('goblet cell', 'goblet cells'),
    'Smooth muscle cells': ('smooth muscle cell', 'smooth muscle cells'),
    'Hippocampus': ('hippocampus', 'hippocampal'),
    'Association cortex': ('association cortex',),
    'Entorhinal cortex': ('entorhinal cortex',),
    'Cortex': ('cortex', 'cortical'),
    'Synapses': ('synapse', 'synapses', 'synaptic'),
}


def _clean_disease_name(disease_name):
    value = str(disease_name or '').strip()
    if '_Module_' in value:
        prefix = value.split('_')[0].upper()
        value = ABBREVIATION_EXPANSION.get(prefix, prefix)
    return value


def _tiab_clause(terms):
    unique = []
    for term in terms:
        cleaned = str(term or '').strip().replace('"', '')
        if cleaned and cleaned.lower() not in {value.lower() for value in unique}:
            unique.append(cleaned)
    return ' OR '.join(f'"{term}"[Title/Abstract]' for term in unique)


def _contains_term(text, term):
    return bool(re.search(rf'(?<![A-Za-z0-9]){re.escape(term)}(?![A-Za-z0-9])', text, re.I))


def search_pubmed_for_cell_context_standalone(
    cell_labels,
    disease_name,
    genes,
    pathway_name='',
    max_results=3,
):
    """Retrieve a few auditable disease × cell-context references.

    The query requires a disease term, one extracted cell/tissue label, and one
    supplied intersection gene in title/abstract. Every returned record carries
    the exact labels and genes found in its title/abstract, so callers can bind
    a PMID to a specific chip instead of to the whole generated block. A broad
    disease × cell or pathway-name fallback is intentionally not used: absence
    is safer than presenting indirect literature as gene-linked support.
    """
    labels = [str(label).strip() for label in (cell_labels or []) if str(label).strip()]
    labels = list(dict.fromkeys(labels))[:4]
    symbols = [
        str(gene).strip().upper() for gene in (genes or [])
        if re.fullmatch(r'[A-Z][A-Z0-9-]{2,14}', str(gene).strip().upper())
    ]
    symbols = list(dict.fromkeys(symbols))[:10]
    disease = _clean_disease_name(disease_name)
    if not labels or not disease:
        return 'Cell-context PubMed query unavailable', []

    alias_terms = []
    for label in labels:
        alias_terms.extend(CELL_CONTEXT_ALIASES.get(label, (label,)))
    disease_clause = _tiab_clause([disease])
    context_clause = _tiab_clause(alias_terms)
    gene_clause = _tiab_clause(symbols)
    strict_query = f'({disease_clause}) AND ({context_clause})'
    if gene_clause:
        strict_query += f' AND ({gene_clause})'

    strict_basis = 'disease-cell-gene' if gene_clause else 'disease-cell'
    queries = [(strict_basis, strict_query)]

    try:
        from Bio import Entrez, Medline
        Entrez.email = ENTREZ_EMAIL or 'researcher@example.com'
        Entrez.api_key = os.environ.get('ENTREZ_API_KEY') or None
        request_pause = 0.12 if Entrez.api_key else 0.34
        for query_basis, query in queries:
            try:
                handle = Entrez.esearch(
                    db='pubmed', term=query,
                    retmax=max(30, int(max_results) * 10), sort='relevance',
                )
                ids = Entrez.read(handle).get('IdList', [])
                handle.close()
            except Exception:
                time.sleep(0.4)
                handle = Entrez.esearch(
                    db='pubmed', term=query,
                    retmax=max(30, int(max_results) * 10), sort='relevance',
                )
                ids = Entrez.read(handle).get('IdList', [])
                handle.close()
            if not ids:
                continue
            time.sleep(request_pause)
            handle = Entrez.efetch(db='pubmed', id=ids, rettype='medline', retmode='text')
            records = list(Medline.parse(handle))
            handle.close()
            time.sleep(request_pause)

            papers = []
            seen_pmids = set()
            for record in records:
                title = str(record.get('TI') or '').strip()
                abstract = str(record.get('AB') or '').strip()
                pmid = str(record.get('PMID') or '').strip()
                searchable = f'{title} {abstract}'
                if not title or not abstract or not pmid or pmid in seen_pmids:
                    continue
                matched_labels = [
                    label for label in labels
                    if any(_contains_term(searchable, alias) for alias in CELL_CONTEXT_ALIASES.get(label, (label,)))
                ]
                matched_genes = [symbol for symbol in symbols if _contains_term(searchable, symbol)]
                if not matched_labels:
                    continue
                if query_basis == 'disease-cell-gene' and symbols and not matched_genes:
                    continue
                title_labels = [
                    label for label in matched_labels
                    if any(_contains_term(title, alias) for alias in CELL_CONTEXT_ALIASES.get(label, (label,)))
                ]
                title_genes = [symbol for symbol in matched_genes if _contains_term(title, symbol)]
                disease_in_title = _contains_term(title, disease)
                # A paper that only mentions the disease, cell type and gene in
                # a broad abstract can be a differential-diagnosis or review
                # false positive. Require the title to anchor the disease, or
                # both the displayed context and an intersection gene.
                if not disease_in_title and not (title_labels and title_genes):
                    continue
                score = (
                    (8 if disease_in_title else 0)
                    + 5 * len(title_labels)
                    + 5 * len(title_genes)
                    + 2 * len(matched_labels)
                    + 2 * len(matched_genes)
                )
                seen_pmids.add(pmid)
                papers.append({
                    'pmid': pmid,
                    'title': title,
                    'journal': record.get('JT', record.get('TA', 'Unknown')),
                    'year': str(record.get('DP') or '')[:4] or 'N/A',
                    'matched_labels': matched_labels,
                    'matched_genes': matched_genes,
                    'query_basis': query_basis,
                    '_relevance_score': score,
                })
            if papers:
                papers.sort(key=lambda paper: paper['_relevance_score'], reverse=True)
                papers = papers[:int(max_results)]
                for paper in papers:
                    paper.pop('_relevance_score', None)
                return f'Found {len(papers)} cell-context references', papers
        return 'No claim-mappable cell-context references found', []
    except ImportError:
        return 'PubMed search unavailable (Biopython not installed)', []
    except Exception as exc:
        return f'PubMed error: {str(exc)[:80]}', []
