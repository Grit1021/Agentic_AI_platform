"""Pathway narrative interpretation.

Shared by the Flask application and by the offline archive builder
(``build_completed_examples.py``) so both produce identical prose from the same
rules. Keeping this in one module is what stops the web result page and the
bundled examples from drifting apart.

The structure follows the manuscript writing specification supplied for the
Alzheimer's disease worked example; see INTERPRETATION_DESIGN.md.
"""

import json
import os
import re


OPENAI_API_KEY = os.environ.get('OPENAI_API_KEY', '')
GPT_MODEL = os.environ.get('GPT_MODEL', 'gpt-5.1')


def _default_clean_definition(value):
    """Strip source-database bracket citations from an official definition."""
    text = str(value or '').strip()
    text = re.sub(r'^\s*["\u201c\u201d]+|["\u201c\u201d]+\s*$', '', text).strip()
    text = re.sub(r'\s*\[(?:GOC|PMID|ISBN|Reactome|KEGG)[^\]]*\]\s*$', '', text).strip()
    return text


clean_pathway_definition = _default_clean_definition


# ============================================================================
# PATHWAY NARRATIVE INTERPRETATION
#
# The labeled four-statement contract above stays as the ranking-evidence
# record. This section adds the reviewer-facing prose narrative: an opening
# overlap statement, notable-protein paragraphs, a functional-cluster
# paragraph, and a closing summary that names the driving proteins.
#
# The structure follows the manuscript writing specification supplied for the
# Alzheimer's disease worked example. Two adaptations were required for the
# web application:
#   * The specification cross-references a protein-protein interaction figure
#     per pathway. The web result page has no such figure, so figure
#     references are disabled unless NARRATIVE_FIGURE_REFERENCES is enabled.
#   * The specification was written against GO:BP terms. GO:MF, GO:CC, KEGG
#     and Reactome carry different semantics, so each database gets its own
#     organizing principle (see NARRATIVE_DATABASE_GUIDANCE).
# ============================================================================

# Enable only when the report actually renders a per-pathway interaction
# figure; otherwise the model would emit an unresolvable cross-reference.
NARRATIVE_FIGURE_REFERENCES = False

# Generate the complete result set. The web client decides how many pathways
# to highlight; keeping generation complete makes archived and live runs
# content-equivalent when the user raises the display limit.
NARRATIVE_MAX_PATHWAYS = int(os.environ.get('NARRATIVE_MAX_PATHWAYS', '25') or 25)
NARRATIVE_MAX_GENES_IN_PROMPT = 60

NARRATIVE_DATABASE_GUIDANCE = {
    'GO:BP': (
        "GO Biological Process terms describe a coordinated series of molecular events, not an "
        "ordered reaction map. Organize the notable genes into functional clusters (for example "
        "synaptic, neuroinflammatory, neurotrophic, proteostatic) and explain what each cluster "
        "contributes to the process. Do not invent a reaction order between the genes."
    ),
    'GO:MF': (
        "GO Molecular Function terms describe a biochemical activity carried by individual gene "
        "products. Explain which shared activity the intersection genes encode (catalysis, "
        "binding, transport, receptor activity), and which of them are the principal effectors of "
        "that activity in the disease. If the term is broad (for example protein binding or ion "
        "binding), state that the term is non-specific and that the enrichment constrains the "
        "activity class rather than a mechanism."
    ),
    'GO:CC': (
        "GO Cellular Component terms describe where gene products reside, not what they do. "
        "Explain which subcellular compartment or complex the products of the intersection genes share, whether "
        "that compartment is itself a site of disease pathology, and which encoded products are structural "
        "constituents versus transient residents. State explicitly that co-localization is not "
        "evidence of a shared mechanism."
    ),
    'KEGG': (
        "KEGG pathways are directed maps with an upstream-to-downstream order. Place the "
        "intersection genes on that map: upstream ligands and receptors, signal transduction, "
        "then downstream effectors and outputs. State which segment of the map the intersection "
        "concentrates in, whether the hits form a contiguous block along one branch or are "
        "scattered across the map, and name any documented cross-talk to adjacent KEGG maps that "
        "the intersection genes participate in."
    ),
    'REAC': (
        "Reactome is a hierarchy of events: a parent pathway contains sub-pathways, which contain "
        "individual reactions. State the level this term sits at and what its immediate parent "
        "event is. For each notable protein, say whether it acts as a catalyst, a substrate or "
        "product, or a component of a participating complex, and whether the intersection genes "
        "act within the same reaction step or across successive steps of the event chain."
    ),
}

NARRATIVE_DEFAULT_GUIDANCE = (
    "Describe what the annotated term groups together, then organize the intersection genes by "
    "their shared function."
)


def get_narrative_database_guidance(category):
    """Return the organizing principle for one source database."""
    key = str(category or '').strip().upper()
    if key.startswith('GO:BP'):
        key = 'GO:BP'
    elif key.startswith('GO:MF'):
        key = 'GO:MF'
    elif key.startswith('GO:CC'):
        key = 'GO:CC'
    elif key.startswith('KEGG'):
        key = 'KEGG'
    elif key.startswith('REAC') or key.startswith('REACTOME'):
        key = 'REAC'
    return NARRATIVE_DATABASE_GUIDANCE.get(key, NARRATIVE_DEFAULT_GUIDANCE)


NARRATIVE_STRUCTURE_RULES = """STRUCTURE (follow exactly, in this order):
1. Opening paragraph, one or two sentences: state that exactly {intersection_size} {disease}
   associated genes were significantly enriched in this pathway, name the pathway and its
   accession, and stop. The number must be {intersection_size}; do not round it, do not write
   "several", and do not interpret the pathway in general terms here.
2. One or two paragraphs on the notable genes. Group two or three genes per paragraph. For
   each, give its established molecular function and its documented link to {disease}, including a
   concrete quantitative or clinical fact when one is well established.
3. One paragraph that groups the remaining functionally related genes into named clusters, and
   introduces each cluster by its shared function.
4. Closing paragraph, two to four sentences: summarize what the pathway contributes to {disease},
   name the gene or genes that drive the association, and note any well-documented
   interaction between intersection genes.

EDITORIAL STYLE:
- Use direct, publication-ready scientific prose with a concrete subject and verb.
- Do not begin a paragraph or sentence with "Overall", "Taken together", "Collectively",
  "These findings suggest", or "The association appears to". State the conclusion directly.
- Prefer "The principal driver genes are ..." to hedged or formulaic driver language.
- Avoid repeating the same disease-context clause, pathway name, or conclusion across paragraphs.
- Refer to the submitted entities as genes. Use "protein" only when describing the molecular
  product or biochemical function of a specific gene.

HARD CONSTRAINTS:
- Use only the intersection genes supplied below. Never introduce a gene or protein symbol that
  is not in that list, not even a well-known disease gene, and not even as background context. A
  reader takes every symbol on this page as having been in the enriched intersection.
- Do not restate the adjusted P-value, the pathway size, or the rank. Those are displayed separately.
  The gene count in the opening sentence is the only permitted statistic.
- Do not reference any figure, panel or table.
- Write continuous scientific prose. No bullet points, no headings, no markdown emphasis.
- If the supplied evidence does not support a mechanistic claim for a protein, omit that protein
  rather than speculating.
- Say that the genes are "enriched in" the term. That is the established verb for
  over-representation results; "associated with" or "found in" understates what was tested.
- If the term name carries a regulation direction ("negative regulation of ...", "positive
  regulation of ..."), preserve that direction. Do not collapse it to the parent process.
- The test compares the submitted gene module against the annotated genome background, not against
  a control condition. Never describe the result as up- or down-regulation."""


def _narrative_tier_clause(tier):
    """Depth instruction derived from the reporting tier.

    Established practice for writing up GO results is to report the top few
    terms per category in full and to mention further terms only where they
    speak directly to the phenotype. Supporting terms therefore get a short
    treatment rather than being dropped.
    """
    if str(tier or '').strip().lower() == 'supporting':
        return (
            "This is a supporting term, not one of the leading results for its database. Write a "
            "short entry: the opening statement, one paragraph on whichever genes add something "
            "the leading terms did not already establish, and one closing sentence. Skip it "
            "entirely as a separate finding if it adds nothing beyond a term already covered."
        )
    return (
        "This is one of the leading results for its database. Write it in full."
    )


def _narrative_hierarchy_clause(hierarchy):
    """State where the term sits in the source ontology's graph.

    GO is a directed acyclic graph: broad parent terms sit above increasingly
    specific children, and a parent and its child can both reach significance
    from largely the same genes. Saying so is the difference between one
    finding reported at two resolutions and two independent findings.
    """
    if not isinstance(hierarchy, dict):
        return (
            "No ontology-graph context was supplied. Do not speculate about how specific or broad "
            "this term is relative to the other results."
        )
    parents = [str(name).strip() for name in hierarchy.get('parent_names_in_set') or [] if str(name).strip()]
    children = [str(name).strip() for name in hierarchy.get('child_names_in_set') or [] if str(name).strip()]
    if not parents and not children:
        return (
            "No other retained term sits directly above or below this one in the source ontology, "
            "so it can be read as an independent finding."
        )
    lines = []
    if parents:
        lines.append(
            f"Broader terms also retained in this report sit directly above it: {', '.join(parents[:4])}. "
            "This term is the more specific reading of that shared signal."
        )
    if children:
        lines.append(
            f"More specific terms also retained sit directly below it: {', '.join(children[:4])}. "
            "This term is the broader reading, and much of its intersection is the same genes."
        )
    lines.append(
        "Say so in one clause. Do not present a parent and its child as two independent findings."
    )
    return ' '.join(lines)


def _narrative_continuity_clause(discussed_genes):
    """Instruct the model to avoid repeating protein detail across pathways."""
    if not discussed_genes:
        return (
            "This is the first pathway in the report, so no protein has been introduced yet. "
            "Introduce each notable protein in full."
        )
    shown = ', '.join(list(discussed_genes)[:25])
    return (
        "These genes were already introduced in earlier pathways of this same report: "
        f"{shown}. If any of them appears again here, refer to it briefly and only from the "
        "perspective that is specific to the present pathway. Do not repeat its general "
        "function or its established disease link a second time. Spend the available space on "
        "genes that have not yet been discussed."
    )


def build_pathway_narrative_prompt(pathway, disease_name, discussed_genes=None):
    """Build the narrative prompt for one pathway."""
    name = str(pathway.get('name') or 'this pathway').strip()
    accession = str(pathway.get('pathway_id') or pathway.get('native') or '').strip()
    category = pathway.get('category') or pathway.get('source') or ''
    definition = clean_pathway_definition(pathway.get('pathway_description') or pathway.get('description') or '')
    all_genes = [str(gene).strip() for gene in (pathway.get('intersection_genes') or []) if str(gene).strip()]
    all_genes = list(dict.fromkeys(all_genes))
    genes = all_genes[:NARRATIVE_MAX_GENES_IN_PROMPT]
    literature_titles = []
    for record in (pathway.get('literature') or [])[:6]:
        if isinstance(record, dict):
            title = str(record.get('title') or '').strip()
            if title:
                literature_titles.append(title[:200])

    declared_size = int(pathway.get('intersection_size') or len(all_genes) or 0)
    prompt_limit_clause = (
        f"Full intersection size: {declared_size}. Only the first {len(genes)} resolved symbols "
        "are included below to control prompt length. The opening count must use the full "
        f"intersection size and therefore must be {declared_size}, not {len(genes)}."
        if len(all_genes) > len(genes) else
        f"Full intersection size: {declared_size}. The listed genes are the complete intersection; "
        f"the opening count must be {declared_size}."
    )

    figure_clause = (
        "Reference the accompanying protein-protein interaction figure in the opening sentence."
        if NARRATIVE_FIGURE_REFERENCES else
        "There is no figure. Refer to the intersection genes as the genes listed for this record."
    )

    return f"""Write the interpretation section for one enriched pathway in a {disease_name} pathway-analysis report.

PATHWAY
  Name: {name}
  Accession: {accession or 'not supplied'}
  Source database: {category or 'not supplied'}
  Official definition: {definition or 'not supplied'}
  Intersection genes supplied to the writer ({len(genes)}): {', '.join(genes) if genes else 'not supplied'}
  {prompt_limit_clause}
  Attached literature titles: {' | '.join(literature_titles) if literature_titles else 'none attached'}

SOURCE-DATABASE READING
{get_narrative_database_guidance(category)}

POSITION IN THE SOURCE ONTOLOGY
{_narrative_hierarchy_clause(pathway.get('hierarchy'))}

DEPTH
{_narrative_tier_clause(pathway.get('reporting_tier'))}

CONTINUITY
{_narrative_continuity_clause(discussed_genes)}

{NARRATIVE_STRUCTURE_RULES.format(disease=disease_name, intersection_size=declared_size)}
{figure_clause}

Return a JSON object:
{{
  "paragraphs": ["opening paragraph", "notable protein paragraph", "...", "closing paragraph"],
  "driver_genes": ["symbols of the one to three genes that drive the association"],
  "clusters": [{{"label": "cluster name", "genes": ["SYMBOL", "SYMBOL"]}}],
  "note": "omit any field you cannot fill rather than padding it"
}}"""


def fallback_pathway_narrative(pathway, disease_name):
    """Build a transparent narrative when the model is unavailable.

    The fallback states only what the structured record already proves. It
    makes no mechanistic claim about any individual protein, because no
    evidence for such a claim was retrieved.
    """
    name = str(pathway.get('name') or 'this pathway').strip()
    accession = str(pathway.get('pathway_id') or pathway.get('native') or '').strip()
    category = pathway.get('category') or pathway.get('source') or ''
    genes = [str(gene).strip() for gene in (pathway.get('intersection_genes') or []) if str(gene).strip()]
    genes = list(dict.fromkeys(genes))
    shown = ', '.join(genes[:12])
    if len(genes) > 12:
        shown += f", and {len(genes) - 12} further genes"

    opening = (
        f"{len(genes)} submitted {disease_name}-associated gene"
        f"{'' if len(genes) == 1 else 's'} were significantly enriched in {name}"
        f"{f' ({accession})' if accession else ''}."
    ) if genes else (
        f"{name}{f' ({accession})' if accession else ''} was retained as a statistically supported "
        f"result for {disease_name}, but the source record did not keep a structured "
        f"input-pathway intersection."
    )
    body = (
        f"The intersection comprises {shown}. Per-gene mechanistic interpretation was not "
        f"generated for this record, so no functional grouping or driver assignment is asserted here."
    ) if genes else (
        "Per-gene interpretation is unavailable for this record."
    )
    closing = (
        f"The reading of this result should rest on the {category or 'source'} definition and the "
        f"enrichment statistics shown alongside it."
    )
    return {
        'paragraphs': [opening, body, closing],
        'driver_genes': [],
        'clusters': [],
        'discussed_genes': [],
        'generated': False,
    }


# ----------------------------------------------------------------------------
# Narrative validation
#
# The reference specification is a writing guide, and its own worked example
# shows the failure mode this guards against: the GO:0016079 paragraph drifts
# from the enriched intersection into general Alzheimer's knowledge, naming
# TNF-alpha, IL-1beta, IL-6, synaptophysin, PSD-95 and BDNF as if they were
# part of the result. On a results page that is a factual error, because the
# reader takes every named protein as having been in the intersection.
#
# So the structure is taken from the specification and the sourcing is made
# stricter than the specification: any symbol-like token in the prose must be
# an intersection gene, and the count in the opening sentence must match the
# real intersection size.
# ----------------------------------------------------------------------------

# Tokens that look like gene symbols but are ordinary scientific vocabulary.
NARRATIVE_SYMBOL_STOPWORDS = {
    'GO', 'BP', 'MF', 'CC', 'KEGG', 'REAC', 'REACTOME', 'HGNC', 'PMID', 'FDR',
    'DNA', 'RNA', 'MRNA', 'CDNA', 'ATP', 'ADP', 'GTP', 'GDP', 'NAD', 'NADH',
    'NADP', 'NADPH', 'ROS', 'PH', 'ER', 'GWAS', 'QTL', 'EQTL', 'SNP', 'CNS',
    'PNS', 'CSF', 'BBB', 'AD', 'PD', 'ALS', 'MS', 'IBD', 'RA', 'T2D', 'MCI',
    'APOE4', 'II', 'III', 'IV', 'VI', 'VII', 'VIII', 'IX', 'XI', 'XII',
    'US', 'UK', 'WHO', 'NIH', 'EC', 'ID', 'IDS', 'OMIM', 'MONDO', 'MESH',
    'HLA', 'HSA', 'MHC', 'TCA', 'ERAD', 'UPR', 'NMDA', 'AMPA', 'GABA',
}

# Symbol-like tokens. Two shapes are matched: an all-caps run of three or more
# characters with an optional hyphenated suffix (BDNF, PSD-95, MMP9), and a
# short caps prefix carrying a number (IL-6, IL1B, CD68). Mixed-case protein
# names in prose (ApoE, tau, amyloid-beta) are deliberately not matched, so a
# writer can still refer to a protein by its common name.
NARRATIVE_SYMBOL_PATTERN = re.compile(
    r'\b(?:[A-Z][A-Z0-9]{2,}(?:-[A-Z0-9]{1,4})?|[A-Z]{2,4}-?\d+[A-Z0-9]*)\b'
)

NARRATIVE_NUMBER_WORDS = {
    1: 'one', 2: 'two', 3: 'three', 4: 'four', 5: 'five', 6: 'six', 7: 'seven',
    8: 'eight', 9: 'nine', 10: 'ten', 11: 'eleven', 12: 'twelve',
}


def find_unsupported_gene_symbols(text, allowed_symbols):
    """Return symbol-like tokens in the prose that are not intersection genes."""
    allowed = {str(symbol).strip().upper() for symbol in allowed_symbols or [] if str(symbol).strip()}
    found = []
    for token in NARRATIVE_SYMBOL_PATTERN.findall(str(text or '')):
        upper = token.upper()
        if upper in allowed or upper in NARRATIVE_SYMBOL_STOPWORDS:
            continue
        if upper not in found:
            found.append(upper)
    return found


def opening_states_intersection_size(opening, intersection_size):
    """Check that the opening sentence carries the true intersection size."""
    if not intersection_size:
        return True
    text = str(opening or '').lower()
    if re.search(rf'\b{intersection_size}\b', text):
        return True
    word = NARRATIVE_NUMBER_WORDS.get(int(intersection_size))
    return bool(word and re.search(rf'\b{word}\b', text))


def validate_narrative(payload, pathway):
    """Return a list of specification violations, empty when the prose is clean.

    Checks, in order of how badly each one misleads a reader:
      1. a named symbol that was never in the intersection;
      2. an opening protein count that contradicts the real intersection size;
      3. too few paragraphs to carry the specified structure;
      4. a driver protein that the prose never actually discusses.
    """
    problems = []
    paragraphs = payload.get('paragraphs') or []
    if len(paragraphs) < 3:
        problems.append(
            f"the narrative has {len(paragraphs)} paragraph(s); the required structure needs at "
            f"least three (opening, notable genes, closing)"
        )

    genes = [str(gene).strip() for gene in (pathway.get('intersection_genes') or []) if str(gene).strip()]
    body = '\n'.join(str(item) for item in paragraphs)
    if any(_narrative_pollution_marker(item) for item in paragraphs):
        problems.append("the prose contains serialized fields or model commentary")
    unsupported = find_unsupported_gene_symbols(body, genes)
    if unsupported:
        problems.append(
            "these symbols are not intersection genes and must not appear: "
            + ', '.join(unsupported[:8])
        )

    intersection_size = int(pathway.get('intersection_size') or len(genes) or 0)
    if paragraphs and not opening_states_intersection_size(paragraphs[0], intersection_size):
        problems.append(
            f"the opening sentence must state that {intersection_size} genes were enriched"
        )

    upper_body = body.upper()
    missing_drivers = [
        gene for gene in (payload.get('driver_genes') or [])
        if gene.upper() not in upper_body
    ]
    if missing_drivers:
        problems.append(
            "these genes are listed as drivers but never discussed in the prose: "
            + ', '.join(missing_drivers[:5])
        )
    return problems


NARRATIVE_POLLUTION_PATTERN = re.compile(
    r'(?:```|driver_genes\s*(?:[\"\'(:]|\[)|\"clusters\"\s*:|'
    r'incorrectly formatted|constraints in this environment|correctly formatted\s+(?:an?\s+)?response)',
    re.I,
)


def _narrative_pollution_marker(value):
    """Return the first model-meta/serialized-field marker in prose, if any."""
    return NARRATIVE_POLLUTION_PATTERN.search(str(value or ''))


def sanitize_narrative_paragraph(value):
    """Remove model protocol leakage while preserving a valid prose prefix.

    Older archived runs contain fragments such as ``driver_genes([`` and a
    model apology after an otherwise valid first sentence.  The archive stays
    immutable; both the server and client call the same conceptual sanitizer
    when presenting it.
    """
    text = str(value or '').strip()
    marker = _narrative_pollution_marker(text)
    if marker:
        text = text[:marker.start()].strip(' \t\n\r`{}[],:;')
    text = re.sub(
        r'\b(?:a\s+)?non-intersection pathway component\b',
        'pathway component',
        text,
        flags=re.I,
    )
    text = re.sub(
        r'\bsubmitted ([^.!?]{0,100}?)-associated proteins\b',
        r'submitted \1-associated genes',
        text,
        flags=re.I,
    )
    text = re.sub(r'\bproteins enriched in\b', 'genes enriched in', text, flags=re.I)
    text = re.sub(r'\bremaining proteins\b', 'remaining genes', text, flags=re.I)
    text = re.sub(r'\bthese proteins\b', 'these genes', text, flags=re.I)
    text = re.sub(r'\bthese (\d+) proteins\b', r'these \1 genes', text, flags=re.I)
    text = re.sub(r'\bassociated proteins\b', 'associated genes', text, flags=re.I)
    text = re.sub(r'\benriched proteins\b', 'enriched genes', text, flags=re.I)
    text = re.sub(r'\bintersection proteins\b', 'intersection genes', text, flags=re.I)
    text = re.sub(r'\bprotein module\b', 'gene module', text, flags=re.I)
    text = re.sub(
        r'\bthe proteins listed for this record\b',
        'the genes listed for this record',
        text,
        flags=re.I,
    )
    text = re.sub(r'\s+', ' ', text).strip()
    text = re.sub(
        r'^(?:(?:overall|taken together|collectively)\s*,?\s*)+',
        '',
        text,
        flags=re.I,
    ).strip()
    text = re.sub(
        r'\bThe association appears to be primarily driven by\b',
        'The principal driver genes are',
        text,
    )
    text = re.sub(
        r'\bindicates that this term captures a substantial component of\b',
        'highlights',
        text,
        flags=re.I,
    )
    text = re.sub(
        r'([.!?]\s+)(?:overall|taken together|collectively)\s*,?\s*([a-z])',
        lambda match: match.group(1) + match.group(2).upper(),
        text,
        flags=re.I,
    )
    if text:
        text = text[0].upper() + text[1:]
    return text if len(text) >= 8 else ''


def _safe_pathway_name(pathway):
    name = str(pathway.get('name') or 'this pathway').strip()
    if re.search(r'\bJAK[- ]STAT\b', name, re.I):
        return 'cytokine-receptor signal transduction'
    unsupported = find_unsupported_gene_symbols(name, pathway.get('intersection_genes') or [])
    for symbol in unsupported:
        name = re.sub(rf'\b{re.escape(symbol)}\b', 'the annotated', name, flags=re.I)
    return re.sub(r'\s+', ' ', name).strip()


def repair_narrative_candidate(payload, pathway, disease_name):
    """Apply deterministic safety repairs before accepting model prose."""
    candidate = dict(payload or {})
    original_paragraphs = candidate.get('paragraphs') or []
    paragraphs = [sanitize_narrative_paragraph(item) for item in original_paragraphs]
    paragraphs = [item for item in paragraphs if item]
    genes = [
        str(gene).strip() for gene in (pathway.get('intersection_genes') or [])
        if str(gene).strip()
    ]
    allowed = {gene.upper() for gene in genes}
    count = int(pathway.get('intersection_size') or len(genes) or 0)
    accession = str(pathway.get('pathway_id') or pathway.get('native') or '').strip()
    safe_name = _safe_pathway_name(pathway)
    opening = (
        f"{count} submitted {disease_name}-associated gene"
        f"{'' if count == 1 else 's'} were significantly enriched in {safe_name}"
        f"{f' ({accession})' if accession else ''}."
    )
    if paragraphs:
        paragraphs[0] = opening
    else:
        paragraphs = [opening]

    repaired_symbols = []
    replacements = {
        'IL-2': 'interleukin-2',
        'CD4': 'cluster-of-differentiation 4',
    }
    for index in range(1, len(paragraphs)):
        unsupported = find_unsupported_gene_symbols(paragraphs[index], genes)
        for symbol in unsupported:
            replacement = replacements.get(symbol, 'a background molecular factor')
            paragraphs[index] = re.sub(
                rf'\b{re.escape(symbol)}\b', replacement, paragraphs[index]
            )
            if symbol not in repaired_symbols:
                repaired_symbols.append(symbol)

    drivers = []
    for gene in candidate.get('driver_genes') or []:
        symbol = str(gene).strip()
        if symbol and symbol.upper() in allowed and symbol.upper() not in {g.upper() for g in drivers}:
            drivers.append(symbol)
    clusters = []
    for cluster in candidate.get('clusters') or []:
        if not isinstance(cluster, dict):
            continue
        label = str(cluster.get('label') or '').strip()
        members = [
            str(gene).strip() for gene in (cluster.get('genes') or [])
            if str(gene).strip().upper() in allowed
        ]
        if label and members:
            clusters.append({'label': label, 'genes': members})
    clusters = dedupe_narrative_clusters(clusters, drivers)
    clustered = {str(gene).upper() for cluster in clusters for gene in cluster.get('genes') or []}
    non_driver = [gene for gene in genes if gene.upper() not in {g.upper() for g in drivers}]
    missing = [gene for gene in non_driver if gene.upper() not in clustered]
    if missing and not clusters:
        clusters.append({'label': 'Additional intersection support', 'genes': missing})

    candidate.update({
        'paragraphs': paragraphs,
        'driver_genes': drivers,
        'clusters': clusters,
        'discussed_genes': mentioned_symbols(paragraphs, genes),
        'generated': bool(candidate.get('generated', True)),
        'deterministic_repair': {
            'unsupported_symbols_rephrased': repaired_symbols,
            'polluted_paragraphs_removed': max(0, len(original_paragraphs) - len(paragraphs)),
        },
    })
    return candidate


def dedupe_narrative_clusters(clusters, driver_genes=None):
    """Drop genes that repeat across clusters, and clusters left empty.

    Driver proteins are deliberately NOT excluded. A driver is normally also the
    most important member of its functional cluster, and seeding the seen-set
    with drivers stripped them out: a narrative naming "GRN and CTSC" as the
    lysosomal cluster rendered as no cluster at all, because both were drivers.
    The chips have to agree with the prose.
    """
    seen = set()
    cleaned = []
    for cluster in clusters or []:
        genes = []
        for gene in cluster.get('genes') or []:
            upper = str(gene).strip().upper()
            if not upper or upper in seen:
                continue
            seen.add(upper)
            genes.append(gene)
        if genes:
            cleaned.append({'label': cluster.get('label'), 'genes': genes})
    return cleaned


def _request_pathway_narrative(client, pathway, disease_name, discussed, correction=None, model=None):
    """One model call. Returns the parsed, intersection-filtered payload."""
    prompt = build_pathway_narrative_prompt(pathway, disease_name, discussed)
    if correction:
        prompt += (
            "\n\nA previous attempt violated the specification as follows:\n- "
            + "\n- ".join(correction)
            + "\nRewrite it so that none of these problems remain."
        )
    response = client.chat.completions.create(
        model=model or GPT_MODEL,
        messages=[
            {
                'role': 'system',
                'content': (
                    f"You are a {disease_name} pathology expert writing the results section of a "
                    f"pathway-analysis manuscript. You write continuous scientific prose and you "
                    f"never assert a claim the supplied evidence does not support."
                ),
            },
            {'role': 'user', 'content': prompt},
        ],
        max_completion_tokens=int(os.environ.get('NARRATIVE_MAX_COMPLETION_TOKENS', '6000') or 6000),
        response_format={
            'type': 'json_schema',
            'json_schema': {
                'name': 'pathway_narrative',
                'strict': True,
                'schema': {
                    'type': 'object',
                    'additionalProperties': False,
                    'properties': {
                        'paragraphs': {'type': 'array', 'items': {'type': 'string'}},
                        'driver_genes': {'type': 'array', 'items': {'type': 'string'}},
                        'clusters': {
                            'type': 'array',
                            'items': {
                                'type': 'object',
                                'additionalProperties': False,
                                'properties': {
                                    'label': {'type': 'string'},
                                    'genes': {'type': 'array', 'items': {'type': 'string'}},
                                },
                                'required': ['label', 'genes'],
                            },
                        },
                    },
                    'required': ['paragraphs', 'driver_genes', 'clusters'],
                },
            },
        },
    )
    parsed = parse_narrative_reply(response.choices[0].message.content)
    paragraphs = [str(item).strip() for item in (parsed.get('paragraphs') or []) if str(item).strip()]
    if not paragraphs:
        return None

    allowed = {
        str(gene).strip().upper()
        for gene in (pathway.get('intersection_genes') or [])
        if str(gene).strip()
    }
    driver_genes = [
        str(gene).strip() for gene in (parsed.get('driver_genes') or [])
        if str(gene).strip().upper() in allowed
    ]
    clusters = [
        {
            'label': str(cluster.get('label') or '').strip(),
            'genes': [
                str(gene).strip() for gene in (cluster.get('genes') or [])
                if str(gene).strip().upper() in allowed
            ],
        }
        for cluster in (parsed.get('clusters') or [])
        if isinstance(cluster, dict) and str(cluster.get('label') or '').strip()
    ]
    return repair_narrative_candidate({
        'paragraphs': paragraphs,
        'driver_genes': driver_genes,
        'clusters': dedupe_narrative_clusters(clusters, driver_genes),
        # Which proteins were actually introduced is read back out of the prose.
        # A reported list costs output tokens and can disagree with the paragraphs.
        'discussed_genes': mentioned_symbols(paragraphs, pathway.get('intersection_genes')),
        'generated': True,
    }, pathway, disease_name)


def mentioned_symbols(paragraphs, intersection_genes):
    """Return the intersection symbols that actually appear in the prose."""
    text = ' '.join(str(item) for item in (paragraphs or []))
    found = []
    for gene in intersection_genes or []:
        symbol = str(gene).strip()
        if symbol and re.search(rf'\b{re.escape(symbol)}\b', text):
            found.append(symbol)
    return found


def map_narrative_paragraph_pmids(paragraphs, literature, limit=2):
    """Link each narrative paragraph to genuinely related pathway papers.

    Archived literature is pathway-level rather than claim-level.  The mapping
    therefore uses only title/prose overlap (with extra weight for exact protein
    symbols) and emits an empty list when there is no match.  That makes the UI
    navigation useful without implying that an arbitrary rotated PMID supports
    a specific mechanistic sentence.
    """
    ignored = {
        'about', 'after', 'among', 'associated', 'context', 'disease', 'evidence',
        'from', 'into', 'multiple', 'pathway', 'process', 'related', 'relevant',
        'sclerosis', 'support', 'that', 'their', 'these', 'this', 'through', 'where',
        'with',
    }
    records = []
    for index, item in enumerate(literature or []):
        if not isinstance(item, dict):
            continue
        pmid = re.sub(r'\D', '', str(item.get('pmid') or item.get('PMID') or ''))
        title = str(item.get('title') or '').strip()
        if pmid and title:
            records.append((index, pmid, title))

    mappings = []
    for paragraph in paragraphs or []:
        text = str(paragraph or '')
        text_tokens = {
            token for token in re.findall(r'[a-zβ][a-z0-9β+\-]{3,}', text.lower())
            if token not in ignored
        }
        text_symbols = set(re.findall(r'\b[A-Z][A-Z0-9-]{2,}\b', text))
        scored = []
        for source_index, pmid, title in records:
            title_tokens = re.findall(r'[a-zβ][a-z0-9β+\-]{3,}', title.lower())
            title_symbols = re.findall(r'\b[A-Z][A-Z0-9-]{2,}\b', title)
            lexical_score = sum(
                1 for token in title_tokens if token not in ignored and token in text_tokens
            )
            symbol_score = sum(4 for symbol in title_symbols if symbol in text_symbols)
            score = lexical_score + symbol_score
            if score > 0:
                scored.append((-score, source_index, pmid))
        scored.sort()
        mappings.append([pmid for _, _, pmid in scored[:max(0, int(limit or 0))]])
    return mappings


def parse_narrative_reply(raw):
    """Parse the model reply, salvaging a truncated JSON object where possible.

    A reply that runs past the token budget is still mostly usable, because the
    paragraphs are written first. Discarding the whole call over a missing
    closing brace is what silently turned real narratives into fallbacks.
    """
    text = str(raw or '').strip()
    if not text:
        raise ValueError('empty narrative reply')
    try:
        payload = json.loads(text)
        if isinstance(payload, dict):
            payload['paragraphs'] = [
                clean for clean in (
                    sanitize_narrative_paragraph(item) for item in payload.get('paragraphs') or []
                ) if clean
            ]
        return payload
    except json.JSONDecodeError:
        pass
    match = re.search(r'"paragraphs"\s*:\s*\[(.*?)(?:\]|$)', text, re.S)
    if not match:
        raise ValueError('narrative reply was neither valid JSON nor recoverable')
    paragraphs = []
    for item in re.findall(r'"(?:[^"\\]|\\.)*"', match.group(1)):
        try:
            value = json.loads(item)
        except json.JSONDecodeError:
            continue
        if str(value).strip():
            paragraphs.append(value)
    if not paragraphs:
        raise ValueError('no paragraphs recovered from truncated narrative reply')
    print(f"     recovered {len(paragraphs)} paragraphs from a truncated narrative reply")
    return {
        'paragraphs': [
            clean for clean in (sanitize_narrative_paragraph(item) for item in paragraphs) if clean
        ],
        '_recovered_from_truncation': True,
    }


def generate_pathway_narratives(pathway_records, disease_name, max_pathways=None, model=None):
    """Generate specification-style narratives for the top-ranked pathways.

    Pathways are processed in the order the reader encounters them and the set
    of already-discussed proteins is carried forward, so a protein introduced
    under the first pathway is not re-explained under the third.

    Each narrative is validated against the specification (see
    validate_narrative). One correction round is allowed; prose that still
    names a protein outside the intersection is discarded in favour of the
    deterministic fallback, because a wrong protein on a results page is worse
    than no prose at all.
    """
    limit = NARRATIVE_MAX_PATHWAYS if max_pathways is None else max_pathways
    ordered = [record for record in (pathway_records or []) if isinstance(record, dict)][:limit]
    narratives = {}
    if not ordered:
        return narratives

    discussed = []
    discussed_seen = set()

    client = None
    if OPENAI_API_KEY:
        try:
            import openai
            client = openai.OpenAI(api_key=OPENAI_API_KEY)
        except Exception as exc:
            print(f"     narrative interpretation unavailable: {str(exc)[:80]}")
            client = None

    for record in ordered:
        key = str(record.get('pathway_id') or record.get('native') or record.get('name') or '')
        payload = None
        if client is not None:
            correction = None
            generation_attempts = 0
            for attempt in range(3):
                generation_attempts += 1
                try:
                    candidate = _request_pathway_narrative(
                        client, record, disease_name, discussed, correction, model=model
                    )
                except Exception as exc:
                    print(f"     narrative generation failed for {key or 'pathway'}: {str(exc)[:80]}")
                    continue
                if candidate is None:
                    break
                problems = validate_narrative(candidate, record)
                if not problems:
                    payload = candidate
                    payload['generation_attempts'] = generation_attempts
                    break
                print(
                    f"     narrative attempt {attempt + 1} for {key or 'pathway'} rejected: "
                    f"{problems[0][:110]}"
                )
                correction = problems

        if payload is None:
            payload = fallback_pathway_narrative(record, disease_name)

        # Persist the paragraph-to-paper relationship so clients do not have to
        # reconstruct it on every render. Old archives remain compatible via
        # the same conservative matcher in app.js.
        payload['paragraph_pmids'] = map_narrative_paragraph_pmids(
            payload.get('paragraphs'), record.get('literature')
        )

        for gene in payload.get('discussed_genes') or []:
            upper = gene.upper()
            if upper not in discussed_seen:
                discussed_seen.add(upper)
                discussed.append(gene)

        narratives[key] = payload

    return narratives
