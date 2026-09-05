"""Pathway-level cell/tissue context.

Mirrors the reference implementation's method, whose Cell_context field is
specified as:

    For each FDR-supported pathway, describe the most relevant disease
    cell/tissue context in the format: - Pathway Name: [cell/tissue context
    description]. If none were FDR-supported, summarize general context for the
    input genes.

Two properties of that specification matter and were previously not met here:

* It runs **after** statistical validation, over the pathways that actually
  survived FDR correction. The reasoning-stage Cell Context block runs during
  hypothesis generation, so it describes predicted pathways, some of which are
  then filtered out.
* It is **per pathway**, keyed by pathway name, rather than one statement per
  source database.

The rendered output format is unchanged: records still carry ``cell_context``
and the interface reads it exactly as before.
"""

import json
import os
import re


OPENAI_API_KEY = os.environ.get('OPENAI_API_KEY', '')
GPT_MODEL = os.environ.get('GPT_MODEL', 'gpt-5.1')

# Keep each response short enough that GPT-5 models can return one visible line
# for every pathway after spending tokens on internal reasoning.  The previous
# batch size of 25 regularly produced only the first few lines of a response.
CELL_CONTEXT_BATCH_SIZE = 8
CELL_CONTEXT_RETRY_BATCH_SIZE = 4

CELL_CONTEXT_PATTERNS = [
    ('Pyramidal neurons', r'\bpyramidal\s+neurons?\b'),
    ('Hippocampal neurons', r'\bhippocamp(?:us|al)[^.!?]{0,55}\bneurons?\b'),
    ('Cortical neurons', r'\b(?:cortical|cortex)[^.!?]{0,55}\bneurons?\b'),
    ('Excitatory neurons', r'\bexcitatory(?:[^.!?]{0,35})?\bneurons?\b'),
    ('Inhibitory neurons', r'\binhibitory(?:[^.!?]{0,35})?\bneurons?\b'),
    ('Glutamatergic neurons', r'\bglutamatergic\s+neurons?\b'),
    ('Dopaminergic neurons', r'\bdopaminergic\s+neurons?\b'),
    ('Motor neurons', r'\bmotor\s+neurons?\b'),
    ('Microglia', r'\bmicrogli(?:a|al)\b'),
    ('Astrocytes', r'\bastrocyt(?:e|es|ic)\b'),
    ('Neurons', r'\bneuron(?:s|al)?\b'),
    ('Oligodendrocytes', r'\boligodendro(?:cyte|cytes|cytic|glia)\b'),
    ('Endothelial cells', r'\bendothelial(?:\s+cells?)?\b'),
    ('Pericytes', r'\bpericytes?\b'),
    ('Monocytes', r'\bmonocytes?\b'),
    ('Macrophages', r'\bmacrophages?\b'),
    ('T cells', r'\bT[-\s]?cells?\b'),
    ('B cells', r'\bB[-\s]?cells?\b'),
    ('Dendritic cells', r'\bdendritic\s+cells?\b'),
    ('Epithelial cells', r'\bepithelial(?:\s+cells?)?\b'),
    ('Fibroblasts', r'\bfibroblasts?\b'),
    ('Adipocytes', r'\badipocytes?\b'),
    ('Hepatocytes', r'\bhepatocytes?\b'),
    ('Pancreatic β cells', r'\b(?:pancreatic\s+)?(?:beta|β)[-\s]?cells?\b'),
    ('Enterocytes', r'\benterocytes?\b'),
    ('Goblet cells', r'\bgoblet\s+cells?\b'),
    ('Smooth muscle cells', r'\bsmooth\s+muscle\s+cells?\b'),
    ('Hippocampus', r'\bhippocamp(?:us|al)\b'),
    ('Association cortex', r'\bassociation\s+cortex\b'),
    ('Entorhinal cortex', r'\bentorhinal\s+cortex\b'),
    ('Cortex', r'\bcort(?:ex|ical)\b'),
    ('Synapses', r'\bsynaps(?:e|es|tic)\b'),
]

CELL_CONTEXT_INSTRUCTION = (
    "For each FDR-supported pathway below, describe the most relevant {disease} "
    "cell/tissue context. Preserve the pathway identifier printed before each pathway "
    "and use this exact output format:\n"
    "- P1: [cell/tissue context description]\n"
    "- P2: [cell/tissue context description]\n\n"
    "Name only cells, tissues or anatomical structures that the pathway biology and its "
    "intersection genes actually support. Be specific: name neuron or glial subtypes for "
    "neurological disease, immune cell types for inflammatory disease, and the relevant "
    "organ compartment for metabolic disease. Write one or two sentences per pathway. "
    "If the evidence does not resolve a context for a pathway, write "
    "\"Not resolved from the supplied pathway-level evidence.\" for that pathway rather "
    "than guessing. Return one line per pathway and nothing else."
)

GENERAL_CONTEXT_INSTRUCTION = (
    "No pathway passed FDR correction. In two or three sentences, summarize the general "
    "{disease} cell/tissue context suggested by the input genes themselves. Do not name a "
    "pathway."
)


def _normalize(name):
    """Loose key so a returned label matches its pathway despite punctuation."""
    return re.sub(r'[^a-z0-9]+', '', str(name or '').lower())


def extract_cell_context_labels(text):
    """Return the same canonical cell/tissue labels used by the browser."""
    value = str(text or '')
    labels = [label for label, pattern in CELL_CONTEXT_PATTERNS if re.search(pattern, value, re.I)]
    has_specific_neuron = any(label != 'Neurons' and label.endswith('neurons') for label in labels)
    has_specific_cortex = 'Association cortex' in labels or 'Entorhinal cortex' in labels
    return [
        label for label in labels
        if (label != 'Neurons' or not has_specific_neuron)
        and (label != 'Cortex' or not has_specific_cortex)
    ]


def parse_cell_context_lines(text, pathway_names):
    """Map ``- Pathway Name: description`` lines back onto pathway names.

    Matching is done on a punctuation-insensitive key, and a returned label that
    matches no supplied pathway is discarded rather than guessed at.
    """
    names = list(pathway_names)
    lookup = {_normalize(name): name for name in names}
    resolved = {}

    def split_candidates(line):
        """Every usable colon in the line, as (label, description) pairs.

        A colon inside an unclosed parenthesis belongs to an accession such as
        "Apoptosis (KEGG:04210)" and is not a separator, so only colons at
        parenthesis depth zero are offered.
        """
        depth = 0
        for position, character in enumerate(line):
            if character == '(':
                depth += 1
            elif character == ')':
                depth = max(0, depth - 1)
            elif character == ':' and depth == 0:
                label = re.sub(r'\s*\([^)]*\)\s*$', '', line[:position]).strip()
                yield _normalize(label), line[position + 1:].strip()

    for raw_line in str(text or '').splitlines():
        line = raw_line.strip().lstrip('-*\u2022').strip()
        if not line:
            continue

        # The prompt gives every pathway a stable short identifier.  Prefer it
        # over matching model-rendered names, because long pathway names are
        # often abbreviated or paraphrased in otherwise valid model output.
        index_match = re.match(
            r'^\**\s*P(\d+)\s*\**\s*[:\uff1a\-\u2013\u2014]\s*(.+)$',
            line,
            flags=re.IGNORECASE,
        )
        if index_match:
            index = int(index_match.group(1)) - 1
            description = index_match.group(2).strip()
            if 0 <= index < len(names) and description:
                resolved.setdefault(names[index], description)
            continue

        if ':' not in line:
            continue
        name = None
        description = ''
        # Exact label matches first, so a colon inside an accession cannot win
        # over the real separator further along the line.
        for key, tail in split_candidates(line):
            if key and key in lookup and tail:
                name, description = lookup[key], tail
                break
        if name is None:
            for key, tail in split_candidates(line):
                if not key or not tail:
                    continue
                for candidate_key, candidate_name in lookup.items():
                    if candidate_key and (
                        key.startswith(candidate_key) or candidate_key.startswith(key)
                    ):
                        name, description = candidate_name, tail
                        break
                if name is not None:
                    break
        if name and description and name not in resolved:
            resolved[name] = description
    return resolved


def build_cell_context_prompt(pathways, disease_name):
    """Prompt for one batch of validated pathways."""
    lines = []
    for index, pathway in enumerate(pathways, 1):
        genes = ', '.join((pathway.get('genes') or [])[:15]) or 'not supplied'
        lines.append(
            f"P{index}. {pathway.get('name')}\n"
            f"   Source: {pathway.get('source') or 'not supplied'}\n"
            f"   Intersection genes: {genes}"
        )
    return (
        CELL_CONTEXT_INSTRUCTION.format(disease=disease_name)
        + "\n\nFDR-SUPPORTED PATHWAYS:\n"
        + "\n".join(lines)
    )


def _complete(prompt, disease_name, max_tokens, model=None):
    import openai
    client = openai.OpenAI(api_key=OPENAI_API_KEY)
    response = client.chat.completions.create(
        model=model or GPT_MODEL,
        messages=[
            {
                'role': 'system',
                'content': (
                    f"You are a {disease_name} pathology expert. You name cell and tissue "
                    f"contexts only where the supplied pathway evidence supports them."
                ),
            },
            {'role': 'user', 'content': prompt},
        ],
        temperature=0,
        max_completion_tokens=max_tokens,
    )
    return response.choices[0].message.content or ''


def generate_pathway_cell_context(validated_pathways, disease_name, genes=None, model=None):
    """Return {pathway name: cell/tissue context} for FDR-supported pathways.

    ``validated_pathways`` is a list of dicts with ``name``, optional ``source``
    and optional ``genes``. When the list is empty the reference specification
    calls for a general statement about the input genes instead; that is
    returned under the ``__general__`` key.
    """
    if not OPENAI_API_KEY:
        return {}

    def complete(prompt, max_tokens):
        if model:
            return _complete(prompt, disease_name, max_tokens, model=model)
        return _complete(prompt, disease_name, max_tokens)

    if not validated_pathways:
        gene_text = ', '.join([str(g).strip() for g in (genes or [])][:40])
        if not gene_text:
            return {}
        prompt = (
            GENERAL_CONTEXT_INSTRUCTION.format(disease=disease_name)
            + f"\n\nINPUT GENES: {gene_text}"
        )
        try:
            return {'__general__': complete(prompt, 300).strip()}
        except Exception as exc:
            print(f"     cell context (general) failed: {str(exc)[:80]}")
            return {}

    def resolve_batches(pathways, batch_size):
        batch_resolved = {}
        for start in range(0, len(pathways), batch_size):
            batch = pathways[start:start + batch_size]
            names = [pathway.get('name') for pathway in batch if pathway.get('name')]
            try:
                text = complete(
                    build_cell_context_prompt(batch, disease_name),
                    min(4000, 300 * len(batch) + 800),
                )
            except Exception as exc:
                print(f"     cell context batch failed: {str(exc)[:80]}")
                continue
            batch_resolved.update(parse_cell_context_lines(text, names))
        return batch_resolved

    resolved = resolve_batches(validated_pathways, CELL_CONTEXT_BATCH_SIZE)

    # A model can still omit a line even with small batches. Retry only the
    # missing pathways in tighter batches so final results do not silently lose
    # their Cell / Tissue Context sections.
    missing = [
        pathway for pathway in validated_pathways
        if pathway.get('name') and pathway.get('name') not in resolved
    ]
    if missing:
        resolved.update(resolve_batches(missing, CELL_CONTEXT_RETRY_BATCH_SIZE))

    # Last-resort single-pathway requests remove every remaining formatting and
    # length ambiguity.  A record remains empty only when the API call itself
    # fails or the model returns no usable answer.
    missing = [
        pathway for pathway in validated_pathways
        if pathway.get('name') and pathway.get('name') not in resolved
    ]
    if missing:
        resolved.update(resolve_batches(missing, 1))

    return resolved


def format_cell_context_lines(resolved, pathway_names=None):
    """Render resolved contexts back into the reference '- Name: text' block."""
    names = list(pathway_names) if pathway_names is not None else list(resolved)
    lines = [f"- {name}: {resolved[name]}" for name in names if resolved.get(name)]
    if not lines and resolved.get('__general__'):
        return resolved['__general__']
    return "\n".join(lines)


def attach_cell_context(pathway_records, disease_name, genes=None, progress=None, model=None):
    """Write post-validation cell context onto records, in place.

    Records that already carry a context from an earlier, more specific source
    are left alone; anything filled here is marked as post-validation so the
    provenance shown alongside it stays accurate.
    """
    records = [record for record in (pathway_records or []) if isinstance(record, dict)]
    if not records:
        return pathway_records
    try:
        if progress:
            progress(f"Resolving cell/tissue context for {len(records)} validated pathways...")
        payload = [
            {
                'name': record.get('name'),
                'source': record.get('source') or record.get('category'),
                'genes': record.get('intersection_genes') or [],
            }
            for record in records if record.get('name')
        ]
        kwargs = {'genes': genes}
        if model:
            kwargs['model'] = model
        resolved = generate_pathway_cell_context(payload, disease_name, **kwargs)
        if not resolved:
            return pathway_records
        general = resolved.get('__general__')
        for record in records:
            context = resolved.get(record.get('name')) or (general if general else '')
            if not context:
                continue
            record['cell_context'] = context
            record['cell_context_provenance'] = {
                'scope': 'pathway-level' if record.get('name') in resolved else 'run-level',
                'source': 'FDR-supported pathway cell context',
                'stage': 'post-validation',
                'claim_citation_scope': 'none',
                'citation_note': (
                    'Cell/tissue labels are model-mapped from the validated pathway and '
                    'intersection genes; no label- or claim-level PMID attribution was generated.'
                ),
            }
    except Exception as exc:
        print(f"     cell context attachment skipped: {str(exc)[:100]}")
    return pathway_records


def attach_cell_context_evidence(
    pathway_records,
    disease_name,
    genes=None,
    progress=None,
    max_references=3,
    replace=False,
    search_cache=None,
):
    """Attach a small label-mapped PubMed set to each resolved context.

    This pass runs after both statistical validation and context generation.
    It never converts the older pathway-level ``cell_context_pmids`` field into
    direct support. Only PubMed records whose title/abstract matches a displayed
    context label are written to ``cell_context_evidence``.
    """
    records = [record for record in (pathway_records or []) if isinstance(record, dict)]
    targets = [
        record for record in records
        if record.get('cell_context') and (replace or not record.get('cell_context_evidence'))
    ]
    if not targets:
        return pathway_records
    try:
        import pubmed_search
        if progress:
            progress(f"Linking cell/tissue context to PubMed for {len(targets)} pathways...")
        for record in targets:
            if replace:
                record.pop('cell_context_evidence', None)
                record.pop('cell_context_literature', None)
                provenance = record.get('cell_context_provenance')
                if isinstance(provenance, dict):
                    provenance.pop('reference_count', None)
                    provenance.pop('reference_method', None)
                    if provenance.get('claim_citation_scope') == 'label-mapped':
                        provenance['claim_citation_scope'] = 'none'
            labels = extract_cell_context_labels(record.get('cell_context'))[:4]
            if not labels:
                continue
            intersection_genes = record.get('intersection_genes') or record.get('genes') or []
            if isinstance(intersection_genes, str):
                intersection_genes = re.split(r'[,;|\s]+', intersection_genes)
            gene_list = [
                str(gene).strip().upper() for gene in intersection_genes
                if str(gene).strip()
            ]
            cache_key = json.dumps(
                [disease_name, labels, gene_list, record.get('name') or '', int(max_references)],
                ensure_ascii=False,
                separators=(',', ':'),
            )
            cached = search_cache.get(cache_key) if isinstance(search_cache, dict) else None
            if cached is not None:
                papers = cached
            else:
                _summary, papers = pubmed_search.search_pubmed_for_cell_context_standalone(
                    labels,
                    disease_name,
                    gene_list,
                    pathway_name=record.get('name') or '',
                    max_results=max_references,
                )
                if isinstance(search_cache, dict):
                    search_cache[cache_key] = papers
            if gene_list:
                papers = [
                    paper for paper in papers
                    if paper.get('query_basis') == 'disease-cell-gene'
                    and paper.get('matched_genes')
                ]
            if not papers:
                continue
            literature = []
            evidence = []
            for paper in papers[:max_references]:
                pmid = str(paper.get('pmid') or '').strip()
                matched_labels = [
                    str(label).strip() for label in paper.get('matched_labels') or []
                    if str(label).strip() in labels
                ]
                if not pmid or not matched_labels:
                    continue
                literature.append({
                    'pmid': pmid,
                    'title': str(paper.get('title') or '').strip(),
                    'journal': str(paper.get('journal') or '').strip(),
                    'year': str(paper.get('year') or '').strip(),
                })
                evidence.append({
                    'labels': matched_labels,
                    'genes': [str(gene).strip() for gene in paper.get('matched_genes') or [] if str(gene).strip()],
                    'pmids': [pmid],
                    'query_basis': paper.get('query_basis') or 'disease-cell-gene',
                })
            if not evidence:
                continue
            record['cell_context_literature'] = literature
            record['cell_context_evidence'] = evidence
            provenance = record.setdefault('cell_context_provenance', {})
            provenance.update({
                'claim_citation_scope': 'label-mapped',
                'reference_count': len(literature),
                'reference_method': (
                    'PubMed title/abstract search using disease, displayed cell/tissue '
                    'labels, and intersection genes; no broad fallback.'
                ),
            })
    except Exception as exc:
        print(f"     cell-context literature attachment skipped: {str(exc)[:100]}")
    return pathway_records
