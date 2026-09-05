"""
Gene Pathway Analysis Web Application - Flask Backend
======================================================
Provides API endpoints for the interactive gene analysis workflow.
INTEGRATES with run_aggregated_disease_analysis_hitl.py for REAL analysis.
"""

import os
import sys
import json
import re
import copy
import hashlib
import tempfile
import uuid
import threading
import pandas as pd
import requests
from html import escape as html_escape
from io import BytesIO
from datetime import datetime, timedelta
from urllib.parse import urlencode
from flask import (
    Flask,
    Response,
    request,
    jsonify,
    send_file,
    send_from_directory,
    session,
    redirect,
    url_for,
)
from flask_cors import CORS
from werkzeug.middleware.proxy_fix import ProxyFix
from whitenoise import WhiteNoise
from quota_manager import QuotaExceeded, QuotaManager, QuotaUnavailable
import external_evidence

try:
    from authlib.integrations.flask_client import OAuth
except ImportError:
    OAuth = None

# ============================================================================
# ENVIRONMENT CONFIGURATION
# ============================================================================

# Load .env file if exists
env_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env')
if os.path.exists(env_file):
    print(f"📁 Loading environment from: {env_file}")
    with open(env_file) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                key, value = line.split('=', 1)
                os.environ[key.strip()] = value.strip()

# Check required environment variables
OPENAI_API_KEY = os.environ.get('OPENAI_API_KEY', '')
ENTREZ_EMAIL = os.environ.get('ENTREZ_EMAIL', '')
GPT_MODEL = os.environ.get('GPT_MODEL', 'gpt-5.1')
ALLOWED_GPT_MODELS = tuple(dict.fromkeys(
    model.strip()
    for model in os.environ.get(
        'ALLOWED_GPT_MODELS',
        'gpt-5.1,gpt-5-mini,gpt-4.1',
    ).split(',')
    if model.strip()
))
if GPT_MODEL not in ALLOWED_GPT_MODELS:
    ALLOWED_GPT_MODELS = (GPT_MODEL, *ALLOWED_GPT_MODELS)


def normalize_requested_model(value=None):
    """Return an explicitly allowed API model, never an arbitrary model ID."""
    model = str(value or GPT_MODEL).strip()
    if model not in ALLOWED_GPT_MODELS:
        raise ValueError(
            f"Unsupported OpenAI model '{model}'. Choose one of: "
            + ', '.join(ALLOWED_GPT_MODELS)
        )
    return model


UNSAFE_BIOMEDICAL_TEXT_PATTERNS = (
    re.compile(
        r'\b(?:how\s+to|steps?\s+to|instructions?\s+(?:for|to)|help\s+me)\b'
        r'.{0,80}\b(?:kill|murder|shoot|stab|bomb|explosive|poison|weapon|attack)\b',
        re.IGNORECASE | re.DOTALL,
    ),
    re.compile(
        r"\b(?:i\s+will|we\s+will|i(?:'m|\s+am)\s+going\s+to)\s+"
        r'(?:kill|murder|shoot|stab|bomb|attack|hurt)\b',
        re.IGNORECASE,
    ),
    re.compile(r'\b(?:kill\s+myself|suicide\s+method|how\s+to\s+die)\b', re.IGNORECASE),
    re.compile(
        r'\b(?:ignore|override)\s+(?:all\s+)?(?:previous|system|developer)\s+instructions?\b',
        re.IGNORECASE,
    ),
    re.compile(
        r'\b(?:reveal|print|return)\b.{0,40}'
        r'\b(?:api\s*key|secret|environment\s+variables?|system\s+prompt)\b',
        re.IGNORECASE | re.DOTALL,
    ),
)


def validate_biomedical_free_text(value, field_name='Field', max_length=1000):
    """Validate free text before it is stored or included in model prompts."""
    text = str(value or '').strip()
    if len(text) > max_length:
        return f'{field_name} is too long (maximum {max_length} characters)'
    if re.search(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', text):
        return f'{field_name} contains unsupported control characters'
    if any(pattern.search(text) for pattern in UNSAFE_BIOMEDICAL_TEXT_PATTERNS):
        return (
            f'{field_name} only accepts biomedical research context. '
            'Remove violent, threatening or unrelated instructions.'
        )
    return ''

if not OPENAI_API_KEY:
    print("⚠️  WARNING: OPENAI_API_KEY not set. GPT ranking will not work.")
    print("   Create a .env file with: OPENAI_API_KEY=sk-your-key-here")
if not ENTREZ_EMAIL:
    print("⚠️  WARNING: ENTREZ_EMAIL not set. PubMed search will not work.")
    print("   Create a .env file with: ENTREZ_EMAIL=your@email.com")

# Set Entrez email for Biopython
if ENTREZ_EMAIL:
    try:
        from Bio import Entrez
        Entrez.email = ENTREZ_EMAIL
        print(f"✅ Entrez email set: {ENTREZ_EMAIL}")
    except ImportError:
        print("⚠️  Biopython not installed. PubMed search disabled.")

# ============================================================================
# PATH CONFIGURATION FOR ANALYSIS IMPORTS
# ============================================================================

current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(current_dir)

# Only these browser assets are copied into WhiteNoise's public directory.
# Keeping the bundle explicit prevents archived result JSON, source files and
# runtime data from becoming public merely because they share this directory.
CACHE_BUSTED_ASSETS = (
    'app.js',
    'styles.css',
    'pathway_slider.css',
    'phosphor-icons.js',
    'favicon.svg',
    'admin.js',
    'admin.css',
    'components/page-fragment.js',
    'components/site-header.js',
    'components/workflow-navigation.js',
    'components/analysis-input.js',
    'components/analysis-runtime.js',
    'components/analysis-results.js',
    'components/run-history.js',
    'components/documentation-view.js',
    'components/product-tour.js',
    'components/site-footer.js',
    'examples/gene_list_examples.zip',
    'examples/hgnc_symbols.txt',
    'examples/ensembl_gene_ids.txt',
    'examples/mixed_identifiers.csv',
)

# A missing downloadable convenience bundle must not prevent the application
# from booting.  The individual example files remain available and the release
# package normally includes the zip as well; this guard only contains a
# packaging regression to the affected download link.
OPTIONAL_CACHE_BUSTED_ASSETS = {
    'examples/gene_list_examples.zip',
}


def _fingerprinted_asset_name(logical_path, digest):
    directory, filename = os.path.split(logical_path)
    stem, extension = os.path.splitext(filename)
    fingerprinted = f'{stem}.{digest}{extension}'
    return f'{directory}/{fingerprinted}' if directory else fingerprinted


def build_cache_busted_static_bundle():
    """Create a public, allowlisted bundle with content-addressed filenames."""
    bundle_root = tempfile.mkdtemp(prefix='genepathway-static-')
    asset_urls = {}
    release_hasher = hashlib.sha256()

    for logical_path in CACHE_BUSTED_ASSETS:
        source_path = os.path.join(current_dir, *logical_path.split('/'))
        if not os.path.isfile(source_path):
            if logical_path in OPTIONAL_CACHE_BUSTED_ASSETS:
                print(f"WARNING: optional static asset unavailable: {logical_path}")
                continue
            raise FileNotFoundError(
                f"Required static asset unavailable: {logical_path} ({source_path})"
            )
        with open(source_path, 'rb') as source_file:
            content = source_file.read()
        digest = hashlib.sha256(content).hexdigest()[:12]
        fingerprinted_path = _fingerprinted_asset_name(logical_path, digest)
        target_path = os.path.join(bundle_root, *fingerprinted_path.split('/'))
        os.makedirs(os.path.dirname(target_path), exist_ok=True)
        with open(target_path, 'wb') as target_file:
            target_file.write(content)
        source_stat = os.stat(source_path)
        os.utime(
            target_path,
            ns=(source_stat.st_atime_ns, source_stat.st_mtime_ns),
        )
        asset_urls[logical_path] = f'/assets/{fingerprinted_path}'
        release_hasher.update(f'{logical_path}:{digest}\n'.encode('utf-8'))

    return bundle_root, asset_urls, release_hasher.hexdigest()[:12]


STATIC_BUNDLE_ROOT, CACHE_BUSTED_ASSET_URLS, STATIC_ASSET_VERSION = (
    build_cache_busted_static_bundle()
)
src_dir = os.path.join(project_root, 'src')
utils_dir = os.path.join(src_dir, 'utils', 'Pathway_analysis')
with_iterative_dir = os.path.join(utils_dir, 'with_iterative')
wo_iterative_dir = os.path.join(utils_dir, 'wo_iterative')
pipeline_dir = os.path.join(src_dir, 'pipeline')

# Add all required paths
for path in [src_dir, utils_dir, with_iterative_dir, wo_iterative_dir, pipeline_dir]:
    if path not in sys.path:
        sys.path.insert(0, path)

print(f"📂 Project root: {project_root}")

# ============================================================================
# RUN HISTORY PERSISTENCE
# ============================================================================

# Elastic Beanstalk deploys the application tree read-only for the web worker.
# Keep runtime history in the instance's writable temporary volume unless an
# explicit durable location is configured.  This also lets export/history
# requests recover a completed background session after its in-memory entry is
# no longer available.
HISTORY_FILE = os.environ.get(
    'HISTORY_FILE',
    os.path.join('/tmp', 'genepathway_run_history.json'),
)
_history_lock = threading.Lock()

def load_history():
    """Load run history from JSON file."""
    with _history_lock:
        try:
            if os.path.exists(HISTORY_FILE):
                with open(HISTORY_FILE, 'r') as f:
                    return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
        return []

def save_history(history):
    """Save run history to JSON file."""
    with _history_lock:
        try:
            with open(HISTORY_FILE, 'w') as f:
                json.dump(history, f, indent=2, default=str)
        except IOError as e:
            print(f"⚠️ Failed to save history: {e}")

def save_run_to_history(session):
    """Save a completed analysis session to history."""
    history = load_history()
    entry = {
        'session_id': session.session_id,
        'disease': session.disease,
        'disease_name': session.disease_name,
        'genes': session.genes,
        'gene_count': len(session.genes),
        'model': session.model,
        'status': session.status,
        'created_at': session.created_at.isoformat(),
        'completed_at': datetime.now().isoformat(),
        'results': session.results,
        'messages': session.messages,
        'owner_id': session.owner_id,
        'owner_email': session.owner_email,
    }
    history = [h for h in history if h.get('session_id') != session.session_id]
    history.insert(0, entry)
    save_history(history)

# ============================================================================
# LEGACY EVIDENCE ASSESSMENT (kept only for backward compatibility)
# ============================================================================

def _legacy_compute_evidence_assessment(pathways, genes, disease_name):
    """Compute an evidence assessment inspired by TigerAI's ICES scoring system.
    
    Returns a dict with:
    - verdict: Insufficient/Weak/Moderate/Strong/Very Strong
    - ices_score: 0-6 composite score
    - category_scores: individual category scores (0-6)
    - summary_stats: counts and metadata
    """
    if not pathways:
        return {
            'verdict': 'Insufficient',
            'verdict_level': 0,
            'ices_score': 0.0,
            'category_scores': {
                'hgc': {'score': 0, 'label': 'Human Genetic Causality', 'description': 'No genetic evidence available'},
                'bio_coh': {'score': 0, 'label': 'Biological Coherence', 'description': 'No biological pathway data'},
                'func_evidence': {'score': 0, 'label': 'Functional Evidence', 'description': 'No functional evidence available'},
                'consistency': {'score': 0, 'label': 'Cross-Study Consistency', 'description': 'Insufficient data for consistency assessment'}
            },
            'summary_stats': {
                'total_pathways': 0,
                'significant_pathways': 0,
                'gene_coverage': 0,
                'literature_refs': 0,
                'categories_covered': 0
            }
        }
    
    cat_pathways = {}
    for p in pathways:
        cat = p.get('source') or p.get('category') or 'Other'
        if cat not in cat_pathways:
            cat_pathways[cat] = []
        cat_pathways[cat].append(p)
    
    def avg_score(items):
        scores = [p.get('gpt_score') or p.get('score') or 0 for p in items]
        return sum(scores) / len(scores) if scores else 0
    
    def max_score(items):
        scores = [p.get('gpt_score') or p.get('score') or 0 for p in items]
        return max(scores) if scores else 0
    
    def count_significant(items):
        return sum(1 for p in items if (p.get('p_value') or p.get('pvalue') or 1) < 0.05)
    
    def score_to_6(raw_score):
        return min(6.0, round(raw_score / 100 * 6, 1))
    
    gobp = cat_pathways.get('GO:BP', [])
    gomf = cat_pathways.get('GO:MF', [])
    gocc = cat_pathways.get('GO:CC', [])
    kegg = cat_pathways.get('KEGG', [])
    reac = cat_pathways.get('REAC', [])
    
    hgc_items = gobp + gomf
    hgc_raw = avg_score(hgc_items) if hgc_items else 0
    hgc_sig = count_significant(hgc_items)
    hgc_score = score_to_6(hgc_raw)
    if hgc_sig >= 5:
        hgc_score = min(6.0, hgc_score + 0.5)
    
    bio_items = gobp + gocc
    bio_raw = avg_score(bio_items) if bio_items else 0
    bio_score = score_to_6(bio_raw)
    if len(bio_items) >= 10:
        bio_score = min(6.0, bio_score + 0.3)
    
    func_items = kegg + reac
    func_raw = avg_score(func_items) if func_items else 0
    func_score = score_to_6(func_raw)
    if len(func_items) >= 5:
        func_score = min(6.0, func_score + 0.3)
    
    all_scores = [p.get('gpt_score') or p.get('score') or 0 for p in pathways]
    if len(all_scores) >= 3:
        mean_s = sum(all_scores) / len(all_scores)
        variance = sum((s - mean_s) ** 2 for s in all_scores) / len(all_scores)
        std_dev = variance ** 0.5
        cv = std_dev / mean_s if mean_s > 0 else 1
        consistency_score = min(6.0, round((1 - min(cv, 1)) * 6, 1))
    else:
        consistency_score = 0.0
    
    categories_covered = sum(1 for cat in ['GO:BP', 'GO:MF', 'GO:CC', 'KEGG', 'REAC'] if cat in cat_pathways)
    
    ices_score = round(
        hgc_score * 0.30 +
        bio_score * 0.25 +
        func_score * 0.25 +
        consistency_score * 0.20,
        1
    )
    
    if categories_covered >= 4:
        ices_score = min(6.0, ices_score + 0.3)
    
    if ices_score >= 5.0:
        verdict = 'Very Strong'
        verdict_level = 4
    elif ices_score >= 4.0:
        verdict = 'Strong'
        verdict_level = 3
    elif ices_score >= 3.0:
        verdict = 'Moderate'
        verdict_level = 2
    elif ices_score >= 2.0:
        verdict = 'Weak'
        verdict_level = 1
    else:
        verdict = 'Insufficient'
        verdict_level = 0
    
    total_lit = 0
    for p in pathways:
        if p.get('pmids'):
            total_lit += len(p['pmids'])
        if p.get('literature'):
            total_lit += len(p['literature'])
    
    all_intersection_genes = set()
    for p in pathways:
        if p.get('intersections'):
            all_intersection_genes.update(p['intersections'])
        elif p.get('intersection_genes'):
            all_intersection_genes.update(p['intersection_genes'])
    gene_coverage = round(len(all_intersection_genes) / len(genes) * 100, 1) if genes else 0
    
    def describe_category(name, score, count):
        if score >= 5:
            return f"Very strong {name.lower()} with {count} supporting pathways"
        elif score >= 4:
            return f"Strong {name.lower()} supported by {count} pathways"
        elif score >= 3:
            return f"Moderate {name.lower()} from {count} pathways"
        elif score >= 2:
            return f"Limited {name.lower()} with {count} pathways identified"
        elif count > 0:
            return f"Weak {name.lower()} - {count} pathways with low scores"
        else:
            return f"No {name.lower()} available"
    
    return {
        'verdict': verdict,
        'verdict_level': verdict_level,
        'ices_score': ices_score,
        'category_scores': {
            'hgc': {
                'score': hgc_score,
                'label': 'Human Genetic Causality',
                'abbr': 'HGC',
                'count': len(hgc_items),
                'description': describe_category('genetic evidence', hgc_score, len(hgc_items))
            },
            'bio_coh': {
                'score': bio_score,
                'label': 'Biological Coherence',
                'abbr': 'BIO_COH',
                'count': len(bio_items),
                'description': describe_category('biological coherence', bio_score, len(bio_items))
            },
            'func_evidence': {
                'score': func_score,
                'label': 'Functional Evidence',
                'abbr': 'FUNC',
                'count': len(func_items),
                'description': describe_category('functional evidence', func_score, len(func_items))
            },
            'consistency': {
                'score': consistency_score,
                'label': 'Cross-Study Consistency',
                'abbr': 'CONS',
                'count': len(pathways),
                'description': describe_category('cross-study consistency', consistency_score, len(pathways))
            }
        },
        'summary_stats': {
            'total_pathways': len(pathways),
            'significant_pathways': count_significant(pathways),
            'gene_count': len(genes),
            'gene_coverage': gene_coverage,
            'literature_refs': total_lit,
            'categories_covered': categories_covered,
            'top_pathway': pathways[0].get('name', 'N/A') if pathways else 'N/A',
            'strongest_category': max(cat_pathways.keys(), key=lambda c: avg_score(cat_pathways[c])) if cat_pathways else 'N/A'
        }
    }


def get_pathway_identifier(pathway):
    """Return the source-native pathway identifier carried by g:Profiler."""
    if not isinstance(pathway, dict):
        return ''
    value = (
        pathway.get('pathway_id')
        or pathway.get('native')
        or pathway.get('term_id')
        or pathway.get('id')
        or ''
    )
    return str(value).strip()


def clean_pathway_definition(value):
    """Remove database quotation wrappers while preserving source citations."""
    text = str(value or '').strip()
    text = re.sub(r'^\s*["“”]+\s*', '', text)
    text = re.sub(r'["“”]+(?=\s*\[[^\]]+\]\s*$)', '', text)
    text = re.sub(r'\s*["“”]+\s*$', '', text)
    return text.strip()


# A label may open its own line, or follow the previous statement inline after
# sentence punctuation. Requiring line starts collapsed a whole four-part
# interpretation into whichever section happened to be written first.
INTERPRETATION_LABEL_PATTERN = re.compile(
    r"(?mi)(?:^|(?<=[.;!?])[ \t]+|(?<=\n))\s*(?:\*\*)?(Pathway description|Biological context|"
    r"Intersection(?:-|\s)gene interpretation|Gene-level support|"
    r"Disease pathology(?: and relevance)?|Disease relevance|"
    r"PubMed literature synthesis|Cell(?:\s*/\s*tissue)? context)(?:\*\*)?\s*:\s*"
)


def parse_pathway_interpretation(value):
    """Parse the user-facing, labeled pathway interpretation contract."""
    text = str(value or '').strip()
    matches = list(INTERPRETATION_LABEL_PATTERN.finditer(text))
    points = []
    # Prose written before the first label is the opening statement; keep it
    # rather than silently dropping everything above the first match.
    if matches and matches[0].start() > 0:
        preamble = text[:matches[0].start()].strip()
        if preamble:
            points.append({'label': 'Disease pathology and relevance', 'text': preamble})
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        point_text = text[match.end():end].strip()
        point_text = re.sub(r'(?:\s*\[PMID:\d+\])+\s*$', '', point_text).strip()
        if not point_text:
            continue
        label = match.group(1)
        normalized_label = label.lower()
        if normalized_label.startswith('cell'):
            label = 'Cell/tissue context'
        elif normalized_label.startswith('intersection'):
            label = 'Intersection-gene interpretation'
        elif normalized_label.startswith('disease pathology'):
            label = 'Disease pathology and relevance'
        elif normalized_label.startswith('pubmed'):
            label = 'PubMed literature synthesis'
        points.append({'label': label, 'text': point_text})
    return points


def extract_pathway_cell_context(value):
    """Return only the pathway-level cell/tissue statement, if present."""
    for point in parse_pathway_interpretation(value):
        if point['label'] == 'Cell/tissue context':
            return point['text']
    return ''


def normalize_pathway_records(pathways):
    """Apply the pathway result contract before display, history, and export."""
    normalized = []
    for pathway in pathways or []:
        if not isinstance(pathway, dict):
            continue
        record = dict(pathway)
        record['pathway_id'] = get_pathway_identifier(record)
        if 'disease_interpretation' not in record:
            record['disease_interpretation'] = record.get('description', '')
        parsed_interpretation = parse_pathway_interpretation(
            record.get('disease_interpretation') or record.get('description')
        )
        existing_points = record.get('interpretation_points') or []
        if existing_points:
            record['interpretation_points'] = [
                point for point in existing_points
                if not (
                    isinstance(point, dict)
                    and str(point.get('label') or '').strip().lower()
                    in {'cell context', 'cell/tissue context'}
                )
            ]
        elif parsed_interpretation:
            record['interpretation_points'] = [
                point for point in parsed_interpretation
                if point['label'] != 'Cell/tissue context'
            ]
        if not record.get('cell_context'):
            record['cell_context'] = next(
                (
                    point['text'] for point in parsed_interpretation
                    if point['label'] == 'Cell/tissue context'
                ),
                '',
            )
        if record.get('cell_context') and not record.get('cell_context_provenance'):
            record['cell_context_provenance'] = {
                'scope': 'pathway-level',
                'source': 'pathway disease interpretation',
            }
        if 'pathway_description' not in record:
            record['pathway_description'] = record.get('source_description', '')
        record['pathway_description'] = clean_pathway_definition(record.get('pathway_description'))
        normalized.append(record)
    return normalized


def fallback_disease_interpretation(pathway_name, pathway_definition, genes, disease_name, literature=None):
    """Build a transparent non-empty interpretation when model prose is unavailable.

    The fallback intentionally omits cell/tissue context because no
    pathway-specific evidence was generated when the model output is absent.
    """
    definition = str(pathway_definition or '').strip()
    definition = re.sub(r'^\s*["“”]+|["“”]+\s*$', '', definition).strip()
    definition = re.sub(r'\s*\[(?:GOC|PMID|ISBN|Reactome|KEGG)[^\]]*\]\s*$', '', definition).strip()
    if not definition:
        definition = f"{pathway_name} is an annotated biological pathway, function or cellular context."

    clean_genes = list(dict.fromkeys(str(gene).strip() for gene in genes or [] if str(gene).strip()))
    shown_genes = clean_genes[:10]
    gene_text = ', '.join(shown_genes)
    if len(clean_genes) > len(shown_genes):
        gene_text += f", and {len(clean_genes) - len(shown_genes)} additional intersection genes"
    gene_statement = (
        f"The submitted module maps to this term through {gene_text}."
        if gene_text else
        "The source result did not retain a structured input–pathway intersection, so gene-level mechanism cannot be resolved here."
    )
    literature_count = len(literature or [])
    literature_statement = (
        f"{literature_count} pathway–disease PubMed records support biological ranking and mechanism-focused review."
        if literature_count else
        "No pathway–disease PubMed record was available for this pathway."
    )
    return (
        f"Disease pathology and relevance: This result prioritizes {pathway_name} for biological interpretation in {disease_name}.\n"
        f"Intersection-gene interpretation: {gene_statement}\n"
        f"PubMed literature synthesis: {literature_statement}"
    )


# ============================================================================
# PATHWAY NARRATIVE INTERPRETATION
#
# The generator lives in pathway_narrative.py so the offline archive builder
# (build_completed_examples.py) produces prose from exactly the same rules.
# ============================================================================

import cell_context as cell_context_module
import pathway_narrative
from pathway_narrative import (  # noqa: F401  (re-exported for callers/tests)
    NARRATIVE_DATABASE_GUIDANCE,
    NARRATIVE_FIGURE_REFERENCES,
    NARRATIVE_MAX_PATHWAYS,
    build_pathway_narrative_prompt,
    fallback_pathway_narrative,
    generate_pathway_narratives,
    get_narrative_database_guidance,
)

# The module ships a conservative definition cleaner; hand it the application's
# richer one so both paths strip identical citation artefacts.
pathway_narrative.clean_pathway_definition = clean_pathway_definition
pathway_narrative.OPENAI_API_KEY = OPENAI_API_KEY
pathway_narrative.GPT_MODEL = GPT_MODEL

cell_context_module.OPENAI_API_KEY = OPENAI_API_KEY
cell_context_module.GPT_MODEL = GPT_MODEL


def attach_pathway_narratives(pathways_list, disease_name, progress=None, model=None):
    """Attach the prose narrative to each pathway record, in display order.

    Narratives are generated in the order the reader encounters them so that
    the continuity rule (do not re-explain a protein introduced under an
    earlier pathway) matches what is actually on screen.
    """
    if not pathways_list:
        return pathways_list
    try:
        if progress:
            progress(
                f"Writing pathway interpretations for all {len(pathways_list)} pathways..."
            )
        narrative_kwargs = {'max_pathways': len(pathways_list)}
        if model:
            narrative_kwargs['model'] = model
        narratives = generate_pathway_narratives(
            pathways_list,
            disease_name,
            **narrative_kwargs,
        )
        for record in pathways_list:
            key = str(record.get('pathway_id') or record.get('native') or record.get('name') or '')
            payload = narratives.get(key)
            if payload:
                record['pathway_narrative'] = payload
        generated_count = sum(
            1 for payload in narratives.values() if payload.get('generated') is True
        )
        fallback_count = len(narratives) - generated_count
        if progress:
            progress(
                f"Pathway narratives complete: {generated_count} model-generated, "
                f"{fallback_count} fallback."
            )
    except Exception as exc:
        print(
            "     narrative attachment skipped: "
            f"{pathway_narrative.exception_summary(exc)}"
        )
    return pathways_list


def compute_run_summary(pathways, genes, disease_name='', mapping_summary=None):
    """Build the user-facing summary for one disease–gene-list run.

    Pathway validity is determined only by formal enrichment. Ranking and
    interpretation describe validated pathways; they do not create a separate
    causal or integrated-evidence verdict.
    """
    database_order = ['GO:BP', 'GO:MF', 'GO:CC', 'KEGG', 'REAC']
    grouped = {}
    for pathway in pathways or []:
        category = pathway.get('source') or pathway.get('category') or 'Other'
        grouped.setdefault(category, []).append(pathway)

    def pathway_pvalue(pathway):
        raw = pathway.get('p_value')
        if raw is None:
            raw = pathway.get('pvalue')
        try:
            return float(raw)
        except (TypeError, ValueError):
            return 1.0

    significant = [pathway for pathway in pathways or [] if pathway_pvalue(pathway) < 0.05]
    rankable = significant or list(pathways or [])

    active_databases = [name for name in database_order if grouped.get(name)]

    literature_pmids = set()
    for pathway in rankable:
        pathway_pmids = {
            str(value)
            for value in pathway.get('pmids', [])
            if value
        }
        for record in pathway.get('literature', []) or []:
            pmid = record.get('pmid') if isinstance(record, dict) else record
            if pmid:
                pathway_pmids.add(str(pmid))
        literature_pmids.update(pathway_pmids)

    supplied_mapping = mapping_summary if isinstance(mapping_summary, dict) else {}
    input_count = int(supplied_mapping.get('input_count') or len(genes or []))
    raw_mapped_count = (
        supplied_mapping.get('mapped_count')
        if supplied_mapping.get('mapped_count') is not None
        else supplied_mapping.get('symbol_mapped_count')
    )
    try:
        mapped_gene_count = int(raw_mapped_count)
    except (TypeError, ValueError):
        query_sizes = []
        for pathway in pathways or []:
            try:
                query_sizes.append(int(pathway.get('query_size')))
            except (TypeError, ValueError):
                continue
        mapped_gene_count = max(query_sizes) if query_sizes else input_count
    mapped_gene_count = min(max(mapped_gene_count, 0), input_count)
    failed_gene_count = max(input_count - mapped_gene_count, 0)
    mesh_id = disease_name_to_mesh_id(disease_name) if disease_name else ''

    return {
        'validation_status': 'Statistically validated' if significant else 'No statistically validated pathways',
        'fdr_threshold': 0.05,
        'significant_pathways': len(significant),
        'total_pathways': len(pathways or []),
        'categories_covered': len(active_databases),
        'literature_records': len(literature_pmids),
        'gene_count': len(genes or []),
        'mapped_gene_count': mapped_gene_count,
        'unmapped_gene_count': failed_gene_count,
        'disease_id': mesh_id,
        'mapping_summary': {
            'input_count': input_count,
            'mapped_count': mapped_gene_count,
            'failed_count': failed_gene_count,
        },
        'validity_definition': 'Functional enrichment with multiple-testing correction; adjusted P-value < 0.05',
        'interpretation_fields': [
            'ranked pathways',
            'driver genes and molecular functions',
            'cell/tissue context',
            'mechanistic themes',
            'disease-relevance strength'
        ]
    }

# ============================================================================
# REAL ANALYSIS IMPORTS
# ============================================================================

REAL_ANALYSIS_AVAILABLE = False
ANALYSIS_ERROR = None

def parse_reasoning_from_response(text):
    """Extract reasoning sections from GPT response text.
    
    Supports multiple formats:
    1. <REASONING> tags with Key: Value pairs (primary format)
    2. Markdown ## or ** headers with content below
    """
    if not text:
        return None
    
    import re
    
    reasoning_match = re.search(r'<REASONING>(.*?)</REASONING>', text, re.DOTALL | re.IGNORECASE)
    content = reasoning_match.group(1).strip() if reasoning_match else text.strip()
    
    known_keys = [
        'overall_strategy', 'strategy', 'gene_analysis', 'database_focus',
        'key_gene_functions', 'pathway_selection_rationale', 'biological_evidence',
        'cell_context', 'relevance_strength_with_disease',
        'learned_from_previous_iteration', 'learned_from_feedback',
        'pathway_guidance',
        'category_specific_adjustments', 'category_adjustments',
        'validation_reflection', 'failure_analysis', 'bottleneck_diagnosis'
    ]
    
    def normalize_key(k):
        return k.strip().lower().replace(' ', '_').replace('-', '_')
    
    key_pattern = '|'.join(re.escape(k) for k in known_keys)
    pattern = re.compile(
        r'(?:^|\n)\s*(?:\*\*)?(' + key_pattern + r')(?:\*\*)?[:\s]+(.+?)(?=\n\s*(?:\*\*)?(?:' + key_pattern + r')(?:\*\*)?[:\s]|\Z)',
        re.DOTALL | re.IGNORECASE
    )
    
    sections = {}
    for match in pattern.finditer(content):
        key = normalize_key(match.group(1))
        value = match.group(2).strip()
        if value and value not in ('N/A', 'Not provided', ''):
            sections[key] = value
    
    def is_na_value(val):
        cleaned = val.strip().rstrip('-').strip()
        if not cleaned:
            return True
        na_patterns = ['N/A', 'Not provided', 'N/A (First iteration or no feedback)',
                       'N/A (Iteration 2+ only)', 'N/A (first iteration)', 'N/A (iteration 2+ only)']
        return cleaned in na_patterns or cleaned.upper().startswith('N/A')
    
    def clean_value(val):
        return val.strip().rstrip('-').strip()
    
    if not sections:
        lines = content.split('\n')
        current_section = None
        current_content = []
        for line in lines:
            line_stripped = line.strip()
            if line_stripped.startswith('##') or (line_stripped.startswith('**') and line_stripped.endswith('**')):
                if current_section and current_content:
                    val = '\n'.join(current_content).strip()
                    if val and not is_na_value(val):
                        sections[normalize_key(current_section)] = clean_value(val)
                current_section = line_stripped.strip('#* ')
                current_content = []
            elif current_section:
                if not (line_stripped == '---' or line_stripped == '***' or line_stripped == '___'):
                    current_content.append(line)
        if current_section and current_content:
            val = '\n'.join(current_content).strip()
            if val and not is_na_value(val):
                sections[normalize_key(current_section)] = clean_value(val)
    
    return sections if sections else None

def disease_name_to_mesh_id(disease_name):
    """Simple MeSH ID lookup for common diseases."""
    mesh_map = {
        "alzheimer's disease": "D000544",
        "inflammatory bowel disease": "D015212",
        "parkinson's disease": "D010300",
        "multiple sclerosis": "D009103",
        "amyotrophic lateral sclerosis": "D000690",
        "rheumatoid arthritis": "D001172",
        "type 2 diabetes": "D003924",
    }
    return mesh_map.get(str(disease_name or '').lower(), '')

def get_disease_description_with_fallback(disease_name):
    """Return a basic disease description."""
    descriptions = {
        "alzheimer's disease": "A progressive neurodegenerative disorder characterized by cognitive decline and memory loss.",
        "inflammatory bowel disease": "Chronic inflammatory conditions of the gastrointestinal tract including Crohn's disease and ulcerative colitis.",
        "parkinson's disease": "A neurodegenerative disorder characterized by motor symptoms including tremor, rigidity, and bradykinesia.",
        "multiple sclerosis": "An autoimmune demyelinating disease of the central nervous system.",
        "amyotrophic lateral sclerosis": "A progressive neurodegenerative disease affecting motor neurons.",
        "rheumatoid arthritis": "A chronic autoimmune inflammatory disorder primarily affecting joints.",
        "type 2 diabetes": "A metabolic disorder characterized by insulin resistance and high blood sugar levels.",
    }
    desc = descriptions.get(disease_name.lower(), f"Analysis of {disease_name}-related pathways and mechanisms.")
    return desc, "builtin"


def summarize_gprofiler_gene_mapping(gprofiler_meta, input_genes):
    """Summarize identifiers mapped by the g:Profiler request.

    g:Profiler stores the canonical input-to-Ensembl mapping in response
    metadata even when the public result is returned as a DataFrame.  Keeping
    this summary avoids inferring mapping success from any single pathway
    source's annotation coverage.
    """
    genes = [str(gene).strip() for gene in input_genes or [] if str(gene).strip()]
    metadata = gprofiler_meta if isinstance(gprofiler_meta, dict) else {}
    genes_metadata = metadata.get('genes_metadata') or {}
    queries = genes_metadata.get('query') or {}
    mapped_inputs = set()
    for query_record in queries.values():
        mapping = query_record.get('mapping') if isinstance(query_record, dict) else {}
        if not isinstance(mapping, dict):
            continue
        for incoming, converted in mapping.items():
            if isinstance(converted, list) and any(str(value).strip() for value in converted):
                mapped_inputs.add(str(incoming).strip())

    failed_inputs = {
        str(value).strip()
        for value in genes_metadata.get('failed', []) or []
        if str(value).strip()
    }
    if not mapped_inputs:
        mapped_inputs = {gene for gene in genes if gene not in failed_inputs}

    mapped_count = min(len(mapped_inputs), len(genes))
    return {
        'input_count': len(genes),
        'mapped_count': mapped_count,
        'failed_count': max(len(genes) - mapped_count, 0),
    }

try:
    import openai
    from gprofiler import GProfiler
    REAL_ANALYSIS_AVAILABLE = True
    print("✅ Real analysis modules loaded (OpenAI + g:Profiler)")
except ImportError as e:
    ANALYSIS_ERROR = str(e)
    print(f"⚠️  Analysis modules not available: {e}")
    print("   Running in DEMO MODE with mock data")

if REAL_ANALYSIS_AVAILABLE and not OPENAI_API_KEY:
    print("⚠️  OpenAI API key not set - real analysis requires OPENAI_API_KEY secret")
    print("   Add it in the Secrets tab (lock icon in left sidebar)")

# ============================================================================
# GPT BENCHMARK CONFIG (for deterministic outputs)
# ============================================================================

GPT_BENCHMARK_CONFIG = {
    "model": GPT_MODEL,
    "temperature": 0,
    "top_p": 1.0,
    "presence_penalty": 0,
    "frequency_penalty": 0,
    "n": 1
}

# Disease abbreviation expansion
ABBREVIATION_EXPANSION = {
    "AD": "Alzheimer's Disease",
    "PD": "Parkinson's Disease",
    "IBD": "Inflammatory Bowel Disease",
    "MS": "Multiple Sclerosis",
    "ALS": "Amyotrophic Lateral Sclerosis",
    "RA": "Rheumatoid Arthritis",
    "T2D": "Type 2 Diabetes",
    "COPD": "Chronic Obstructive Pulmonary Disease",
}

# ============================================================================
# FLASK APP
# ============================================================================

app = Flask(__name__, static_folder=None)
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
app.wsgi_app = WhiteNoise(
    app.wsgi_app,
    root=STATIC_BUNDLE_ROOT,
    prefix='assets/',
    max_age=int(os.environ.get('STATIC_CACHE_MAX_AGE', '31536000')),
    immutable_file_test=lambda path, url: bool(
        re.search(r'\.[0-9a-f]{12}\.[^/]+$', url)
    ),
)

AUTH_ENABLED = os.environ.get('AUTH_ENABLED', 'true').strip().lower() in {'1', 'true', 'yes', 'on'}
ACCESS_MODE = os.environ.get('ACCESS_MODE', 'team').strip().lower()
if ACCESS_MODE not in {'team', 'public'}:
    ACCESS_MODE = 'team'
FLASK_SECRET_KEY = os.environ.get('FLASK_SECRET_KEY', '')
COGNITO_REGION = os.environ.get('COGNITO_REGION', '')
COGNITO_USER_POOL_ID = os.environ.get('COGNITO_USER_POOL_ID', '')
COGNITO_CLIENT_ID = os.environ.get('COGNITO_CLIENT_ID', '')
COGNITO_CLIENT_SECRET = os.environ.get('COGNITO_CLIENT_SECRET', '')
COGNITO_DOMAIN = os.environ.get('COGNITO_DOMAIN', '').rstrip('/')
APP_BASE_URL = os.environ.get('APP_BASE_URL', '').rstrip('/')
ALLOWED_EMAILS = {
    email.strip().lower()
    for email in os.environ.get('ALLOWED_EMAILS', '').split(',')
    if email.strip()
}
ADMIN_EMAILS = {
    email.strip().lower()
    for email in os.environ.get('ADMIN_EMAILS', '').split(',')
    if email.strip()
}
if not AUTH_ENABLED and not ADMIN_EMAILS:
    ADMIN_EMAILS = {'local@localhost'}
CORS_ALLOWED_ORIGINS = [
    origin.strip()
    for origin in os.environ.get('CORS_ALLOWED_ORIGINS', '').split(',')
    if origin.strip()
]

try:
    MAX_CONCURRENT_JOBS = max(1, int(os.environ.get('MAX_CONCURRENT_JOBS', '1')))
except (TypeError, ValueError):
    MAX_CONCURRENT_JOBS = 1

quota_manager = QuotaManager()
_job_slots = threading.BoundedSemaphore(MAX_CONCURRENT_JOBS)
_active_jobs = 0
_active_jobs_lock = threading.Lock()

app.secret_key = FLASK_SECRET_KEY or os.urandom(32)
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SECURE=AUTH_ENABLED,
    SESSION_COOKIE_SAMESITE='Lax',
    PERMANENT_SESSION_LIFETIME=timedelta(hours=8),
)

if CORS_ALLOWED_ORIGINS:
    CORS(app, origins=CORS_ALLOWED_ORIGINS, supports_credentials=True)

AUTH_CONFIG_READY = bool(
    not AUTH_ENABLED or (
        OAuth is not None
        and FLASK_SECRET_KEY
        and COGNITO_REGION
        and COGNITO_USER_POOL_ID
        and COGNITO_CLIENT_ID
        and COGNITO_CLIENT_SECRET
        and COGNITO_DOMAIN
        and APP_BASE_URL
        and (ACCESS_MODE == 'public' or ALLOWED_EMAILS)
    )
)

cognito_client = None
if AUTH_ENABLED and AUTH_CONFIG_READY:
    oauth = OAuth(app)
    cognito_issuer = (
        f'https://cognito-idp.{COGNITO_REGION}.amazonaws.com/'
        f'{COGNITO_USER_POOL_ID}'
    )
    cognito_client = oauth.register(
        name='cognito',
        client_id=COGNITO_CLIENT_ID,
        client_secret=COGNITO_CLIENT_SECRET,
        server_metadata_url=f'{cognito_issuer}/.well-known/openid-configuration',
        client_kwargs={'scope': 'openid email profile'},
    )

PUBLIC_PATHS = {
    '/login',
    '/auth/login',
    '/auth/callback',
    '/auth/logout',
    '/api/status',
    '/favicon.svg',
    '/components/site-footer.js',
}


def get_request_user() -> dict:
    """Return the authenticated identity, or a stable local-development user."""
    user = session.get('user')
    if isinstance(user, dict) and (user.get('sub') or user.get('email')):
        return user
    if not AUTH_ENABLED:
        return {
            'sub': 'local-development',
            'email': 'local@localhost',
            'name': 'Local development',
        }
    return {}


def get_request_owner_id() -> str:
    user = get_request_user()
    return str(user.get('sub') or user.get('email') or '').strip()


def get_request_email() -> str:
    user = get_request_user()
    return str(user.get('email') or '').strip().lower()


def user_has_access(user: dict) -> bool:
    email = str(user.get('email', '')).strip().lower() if isinstance(user, dict) else ''
    if not email:
        return False
    return ACCESS_MODE == 'public' or email in ALLOWED_EMAILS


def user_is_admin(user: dict) -> bool:
    email = str(user.get('email', '')).strip().lower() if isinstance(user, dict) else ''
    return bool(email and email in ADMIN_EMAILS and user_has_access(user))


def is_admin_request_path(path: str) -> bool:
    return path == '/admin' or path in {'/admin.html', '/admin.js', '/admin.css'} or path.startswith('/api/admin/')


def deny_admin_request():
    if request.path.startswith('/api/'):
        return jsonify({'error': 'Administrator access required'}), 403
    return Response('Not found', status=404, mimetype='text/plain')


@app.before_request
def require_team_login():
    """Fail closed unless a Cognito identity satisfies the active access mode."""
    if request.path in PUBLIC_PATHS:
        return None

    user = get_request_user()
    if not AUTH_ENABLED:
        if is_admin_request_path(request.path) and not user_is_admin(user):
            return deny_admin_request()
        return None

    if user_has_access(user):
        if is_admin_request_path(request.path) and not user_is_admin(user):
            return deny_admin_request()
        return None

    session.clear()
    if request.path.startswith('/api/'):
        return jsonify({
            'error': 'Authentication required',
            'login_url': '/login',
        }), 401

    next_path = request.full_path if request.query_string else request.path
    return redirect(url_for('login_page', next=next_path))


@app.after_request
def add_header(response):
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['Referrer-Policy'] = 'same-origin'
    return response

# ============================================================================
# GENE LISTS API
# ============================================================================

OPENTARGETS_GRAPHQL_URL = 'https://api.platform.opentargets.org/api/v4/graphql'
_disease_search_cache = {}
_disease_search_lock = threading.Lock()
_gene_search_cache = {}
_gene_search_lock = threading.Lock()
_associated_gene_cache = {}
_associated_gene_lock = threading.Lock()

@app.route('/api/disease-search', methods=['GET'])
def search_diseases():
    """Return Open Targets disease/phenotype matches for the input combobox."""
    query = re.sub(r'\s+', ' ', request.args.get('q', '')).strip()
    if len(query) < 2:
        return jsonify({'results': []})
    if len(query) > 80:
        return jsonify({'error': 'Disease query is too long', 'results': []}), 400
    query_error = validate_biomedical_free_text(query, 'Disease query', 80)
    if query_error:
        return jsonify({'error': query_error, 'code': 'unsafe_free_text', 'results': []}), 400

    cache_key = query.casefold()
    with _disease_search_lock:
        cached = _disease_search_cache.get(cache_key)
        if cached and datetime.now() - cached['created_at'] < timedelta(hours=12):
            return jsonify({'results': cached['results'], 'source': 'Open Targets', 'cached': True})

    graphql_query = """
    query DiseaseSearch($query: String!) {
      search(queryString: $query, entityNames: ["disease"], page: {index: 0, size: 8}) {
        hits { id name entity description }
      }
    }
    """
    try:
        upstream = requests.post(
            OPENTARGETS_GRAPHQL_URL,
            json={'query': graphql_query, 'variables': {'query': query}},
            timeout=8,
        )
        upstream.raise_for_status()
        payload = upstream.json()
        hits = payload.get('data', {}).get('search', {}).get('hits', [])
        results = [{
            'id': str(hit.get('id') or ''),
            'name': str(hit.get('name') or '').strip(),
            'description': str(hit.get('description') or '').strip(),
            'url': f"https://platform.opentargets.org/disease/{hit.get('id')}/associations",
        } for hit in hits if hit.get('id') and hit.get('name')]
        with _disease_search_lock:
            if len(_disease_search_cache) >= 128:
                _disease_search_cache.pop(next(iter(_disease_search_cache)))
            _disease_search_cache[cache_key] = {'created_at': datetime.now(), 'results': results}
        return jsonify({'results': results, 'source': 'Open Targets', 'cached': False})
    except (requests.RequestException, ValueError, TypeError) as exc:
        app.logger.warning('Open Targets disease search unavailable: %s', exc)
        return jsonify({'results': [], 'source': 'Open Targets', 'available': False})


def _normalize_open_targets_disease_id(value):
    """Return an Open Targets disease/phenotype identifier safe for GraphQL."""
    disease_id = str(value or '').strip().replace(':', '_')
    if not re.fullmatch(r'[A-Za-z][A-Za-z0-9]*_[A-Za-z0-9][A-Za-z0-9._-]{0,63}', disease_id):
        return ''
    return disease_id


@app.route('/api/open-targets/associated-genes', methods=['GET'])
def get_open_targets_associated_genes():
    """Return the top 100 or 200 disease-associated human genes by OT score."""
    disease_id = _normalize_open_targets_disease_id(request.args.get('disease_id', ''))
    if not disease_id:
        return jsonify({'error': 'Select an ontology-backed disease or phenotype first'}), 400

    try:
        limit = int(request.args.get('limit', '100'))
    except (TypeError, ValueError):
        limit = 0
    if limit not in {100, 200}:
        return jsonify({'error': 'Limit must be 100 or 200'}), 400

    cache_key = (disease_id, limit)
    with _associated_gene_lock:
        cached = _associated_gene_cache.get(cache_key)
        if cached and datetime.now() - cached['created_at'] < timedelta(hours=12):
            return jsonify({**cached['payload'], 'cached': True})

    graphql_query = """
    query DiseaseTopTargets($efoId: String!, $size: Int!) {
      disease(efoId: $efoId) {
        id
        name
        associatedTargets(
          page: {index: 0, size: $size}
          orderByScore: "score"
        ) {
          count
          rows {
            score
            target { id approvedSymbol approvedName }
          }
        }
      }
    }
    """
    try:
        upstream = requests.post(
            OPENTARGETS_GRAPHQL_URL,
            json={
                'query': graphql_query,
                'variables': {'efoId': disease_id, 'size': limit},
            },
            timeout=18,
        )
        upstream.raise_for_status()
        upstream_payload = upstream.json()
        disease = upstream_payload.get('data', {}).get('disease')
        if not disease:
            if upstream_payload.get('errors'):
                raise ValueError('Open Targets returned a GraphQL error')
            return jsonify({'error': 'Disease or phenotype was not found in Open Targets'}), 404

        associations = disease.get('associatedTargets') or {}
        genes = []
        seen_symbols = set()
        for row in associations.get('rows') or []:
            target = row.get('target') or {}
            symbol = str(target.get('approvedSymbol') or '').strip().upper()
            ensembl_id = str(target.get('id') or '').strip().upper()
            if not symbol or not ensembl_id.startswith('ENSG') or symbol in seen_symbols:
                continue
            try:
                score = float(row.get('score'))
            except (TypeError, ValueError):
                score = None
            seen_symbols.add(symbol)
            genes.append({
                'symbol': symbol,
                'ensembl_id': ensembl_id,
                'name': str(target.get('approvedName') or '').strip(),
                'association_score': score,
            })

        genes.sort(key=lambda item: (
            item['association_score'] is None,
            -(item['association_score'] or 0),
            item['symbol'],
        ))
        genes = genes[:limit]
        source_url = f'https://platform.opentargets.org/disease/{disease_id}/associations'
        payload = {
            'disease': {
                'id': str(disease.get('id') or disease_id),
                'name': str(disease.get('name') or '').strip(),
            },
            'genes': genes,
            'requested_limit': limit,
            'returned_count': len(genes),
            'total_associations': int(associations.get('count') or 0),
            'source': 'Open Targets Platform',
            'source_url': source_url,
            'ranking': 'overall association score',
            'cached': False,
        }
        with _associated_gene_lock:
            if len(_associated_gene_cache) >= 128:
                _associated_gene_cache.pop(next(iter(_associated_gene_cache)))
            _associated_gene_cache[cache_key] = {
                'created_at': datetime.now(),
                'payload': payload,
            }
        return jsonify(payload)
    except (requests.RequestException, ValueError, TypeError, KeyError) as exc:
        app.logger.warning(
            'Open Targets associated-gene query unavailable for %s: %s',
            disease_id,
            exc,
        )
        return jsonify({
            'error': 'Open Targets associated genes are temporarily unavailable',
            'source': 'Open Targets Platform',
            'available': False,
        }), 503


def _rank_gene_search_hits(hits, query):
    """Prioritize approved-looking symbol matches while retaining API relevance."""
    normalized_query = str(query or '').strip().upper()
    ranked = []
    for original_index, hit in enumerate(hits or []):
        symbol = str(hit.get('name') or '').strip().upper()
        ensembl_id = str(hit.get('id') or '').strip().upper()
        gene_name = str(hit.get('description') or '').strip()
        if not symbol or not ensembl_id.startswith('ENSG'):
            continue
        if symbol == normalized_query or ensembl_id == normalized_query:
            match_rank = 0
        elif symbol.startswith(normalized_query):
            match_rank = 1
        elif normalized_query in symbol:
            match_rank = 2
        elif normalized_query in gene_name.upper():
            match_rank = 3
        else:
            match_rank = 4
        secondary_penalty = int(bool(re.search(
            r'pseudogene|antisense|novel transcript', gene_name, flags=re.IGNORECASE
        )))
        ranked.append({
            'symbol': symbol,
            'name': gene_name,
            'ensembl_id': ensembl_id,
            'url': f'https://platform.opentargets.org/target/{ensembl_id}',
            '_sort': (match_rank, secondary_penalty, len(symbol), original_index),
        })
    ranked.sort(key=lambda item: item['_sort'])
    for item in ranked:
        item.pop('_sort', None)
    return ranked[:8]


@app.route('/api/gene-search', methods=['GET'])
def search_genes():
    """Return ranked Open Targets human gene candidates for the active token."""
    query = re.sub(r'\s+', ' ', request.args.get('q', '')).strip()
    if len(query) < 2:
        return jsonify({'results': []})
    if len(query) > 40 or not re.fullmatch(r'[A-Za-z0-9._-]+', query):
        return jsonify({'error': 'Invalid gene query', 'results': []}), 400

    cache_key = query.casefold()
    with _gene_search_lock:
        cached = _gene_search_cache.get(cache_key)
        if cached and datetime.now() - cached['created_at'] < timedelta(hours=12):
            return jsonify({'results': cached['results'], 'source': 'Open Targets', 'cached': True})

    graphql_query = """
    query TargetSearch($query: String!) {
      search(queryString: $query, entityNames: ["target"], page: {index: 0, size: 50}) {
        hits { id name entity description }
      }
    }
    """
    try:
        upstream = requests.post(
            OPENTARGETS_GRAPHQL_URL,
            json={'query': graphql_query, 'variables': {'query': query}},
            timeout=8,
        )
        upstream.raise_for_status()
        payload = upstream.json()
        hits = payload.get('data', {}).get('search', {}).get('hits', [])
        results = _rank_gene_search_hits(hits, query)
        with _gene_search_lock:
            if len(_gene_search_cache) >= 256:
                _gene_search_cache.pop(next(iter(_gene_search_cache)))
            _gene_search_cache[cache_key] = {'created_at': datetime.now(), 'results': results}
        return jsonify({'results': results, 'source': 'Open Targets', 'cached': False})
    except (requests.RequestException, ValueError, TypeError) as exc:
        app.logger.warning('Open Targets gene search unavailable: %s', exc)
        return jsonify({'results': [], 'source': 'Open Targets', 'available': False})

GENE_LISTS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'gene_lists.json')
COMPLETED_EXAMPLES_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    'offline_completed_examples.json',
)
_gene_lists_cache = None
_frontend_data_cache = None
_frontend_data_signature = None
_frontend_data_lock = threading.Lock()

def load_gene_lists():
    global _gene_lists_cache
    if _gene_lists_cache is None:
        try:
            with open(GENE_LISTS_FILE, 'r') as f:
                _gene_lists_cache = json.load(f)
        except Exception as e:
            print(f"⚠️  Could not load gene_lists.json: {e}")
            _gene_lists_cache = {}
    return _gene_lists_cache


def _reference_file_signature():
    """Return a cheap signature so deployed data updates do not require code edits."""
    signature = []
    for path in (GENE_LISTS_FILE, COMPLETED_EXAMPLES_FILE):
        try:
            stat = os.stat(path)
            signature.append((path, stat.st_mtime_ns, stat.st_size))
        except OSError:
            signature.append((path, None, None))
    return tuple(signature)


def load_frontend_reference_data():
    """Load backend-owned input examples and the completed-example catalog.

    The catalog deliberately excludes full analysis results. A selected result is
    fetched through its own endpoint so the homepage does not download every
    archived pathway record.
    """
    global _frontend_data_cache, _frontend_data_signature, _gene_lists_cache
    signature = _reference_file_signature()
    with _frontend_data_lock:
        if _frontend_data_cache is not None and signature == _frontend_data_signature:
            return _frontend_data_cache

        try:
            with open(GENE_LISTS_FILE, 'r', encoding='utf-8') as handle:
                gene_lists = json.load(handle)
        except (OSError, json.JSONDecodeError) as exc:
            app.logger.warning('Could not load frontend gene lists: %s', exc)
            gene_lists = {}

        try:
            with open(COMPLETED_EXAMPLES_FILE, 'r', encoding='utf-8') as handle:
                archive = json.load(handle)
        except (OSError, json.JSONDecodeError) as exc:
            app.logger.warning('Could not load completed-example archive: %s', exc)
            archive = {}

        examples = {}
        for raw_code, raw_example in (archive.get('examples') or {}).items():
            if not isinstance(raw_example, dict) or not raw_example.get('result'):
                continue
            code = str(raw_code or '').strip().upper()
            if not code:
                continue
            examples[code] = {
                key: raw_example.get(key)
                for key in (
                    'code', 'title', 'disease', 'subtitle', 'module',
                    'gene_count', 'pathway_count', 'session_id',
                )
                if raw_example.get(key) is not None
            }
            examples[code]['code'] = code

        default_code = str(archive.get('default') or '').strip().upper()
        if default_code not in examples:
            default_code = next(iter(examples), '')

        payload = {
            'schema_version': 1,
            'gene_lists': gene_lists,
            'completed_examples': {
                'default': default_code,
                'examples': examples,
            },
        }
        _gene_lists_cache = gene_lists
        _frontend_data_cache = payload
        _frontend_data_signature = signature
        return payload


def load_completed_example(code):
    """Return one full archived result from the backend-owned archive."""
    normalized_code = str(code or '').strip().upper()
    if not re.fullmatch(r'[A-Z0-9_-]{1,24}', normalized_code):
        return None
    try:
        with open(COMPLETED_EXAMPLES_FILE, 'r', encoding='utf-8') as handle:
            archive = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        app.logger.warning('Could not load completed example %s: %s', normalized_code, exc)
        return None
    example = (archive.get('examples') or {}).get(normalized_code)
    return example if isinstance(example, dict) and example.get('result') else None


@app.route('/api/frontend-data', methods=['GET'])
def get_frontend_data():
    """Return the batched, backend-owned reference data used by the homepage."""
    return jsonify(load_frontend_reference_data())


@app.route('/api/completed-examples/<code>', methods=['GET'])
def get_completed_example(code):
    """Return one completed example only when the reader opens it."""
    example = load_completed_example(code)
    if not example:
        return jsonify({'error': 'Completed example was not found'}), 404
    return jsonify(example)

@app.route('/api/gene-lists', methods=['GET'])
def get_gene_lists():
    """Return curated gene-list metadata, optionally including gene symbols."""
    data = load_gene_lists()
    include_genes = request.args.get('include_genes', '').strip().lower() in {
        '1', 'true', 'yes', 'on'
    }
    result = {}
    for disease_code, disease_data in data.items():
        result[disease_code] = {
            "name": disease_data.get("name", disease_data.get("label", disease_code)),
            "mesh_id": disease_data.get("mesh_id", ""),
            "lists": [
                dict({
                    "id": lst["id"],
                    "label": lst["label"],
                    "description": lst["description"],
                    "source": lst["source"],
                    "gene_count": len(lst["genes"])
                }, **({"genes": lst["genes"]} if include_genes else {}))
                for lst in disease_data.get("lists", [])
            ]
        }
    return jsonify(result)

@app.route('/api/gene-lists/<disease_code>/<list_id>', methods=['GET'])
def get_gene_list(disease_code, list_id):
    """Return genes for a specific disease + list combination."""
    data = load_gene_lists()
    disease_code = disease_code.upper()
    if disease_code not in data:
        return jsonify({"error": f"Disease '{disease_code}' not found"}), 404
    for lst in data[disease_code].get("lists", []):
        if lst["id"] == list_id:
            return jsonify({
                "disease_code": disease_code,
                "disease_name": data[disease_code].get("name", data[disease_code].get("label", disease_code)),
                "list_id": list_id,
                "label": lst["label"],
                "description": lst["description"],
                "source": lst["source"],
                "genes": lst["genes"],
                "gene_count": len(lst["genes"])
            })
    return jsonify({"error": f"List '{list_id}' not found for disease '{disease_code}'"}), 404

# ============================================================================
# SESSION STATE MANAGEMENT
# ============================================================================

class AnalysisSession:
    """Manages state for a single analysis session."""
    
    def __init__(
        self,
        session_id: str,
        genes: list,
        disease: str,
        owner_id: str = '',
        owner_email: str = '',
        disease_context: dict = None,
        model: str = None,
    ):
        self.session_id = session_id
        self.owner_id = owner_id
        self.owner_email = owner_email
        self.genes = genes
        self.disease = disease
        self.disease_context = disease_context or {}
        self.model = normalize_requested_model(model)
        self.disease_name = self.disease_context.get('name') or self._expand_disease_name(disease)
        self.disease_config = None  # Will be set by get_disease_config
        self.status = "initialized"
        self.current_phase = 0
        self.current_checkpoint = None
        self.checkpoint_data = {}
        self.messages = []
        self.results = {}
        self.created_at = datetime.now()
        self.waiting_for_user = False
        self.framework = None  # Analysis framework instance
        self.analysis_started_at = None
        self.progress_percent = 0
        self.progress_stage = "Queued"
        self.progress_detail = "Waiting for an analysis worker."
        self.progress_state = "queued"
        self.progress_updated_at = datetime.now()
        self._progress_lock = threading.Lock()
        
        # Iterative mode support
        self.use_iterative = False  # Whether to run 2 iterations
        self.current_iteration = 0   # Current iteration (1-2)
        self.retained_pathways = []  # FDR-filtered pathways from previous iteration
        
    def _expand_disease_name(self, disease: str) -> str:
        """Expand disease abbreviation to full name."""
        return ABBREVIATION_EXPANSION.get(disease.upper(), disease)
    
    def add_message(self, msg_type: str, content: str, data: dict = None):
        """Add a message to the chat history."""
        self.messages.append({
            "type": msg_type,
            "content": content,
            "data": data or {},
            "timestamp": datetime.now().isoformat()
        })

    def set_progress(
        self,
        percent: int,
        stage: str,
        detail: str = '',
        state: str = 'running',
    ):
        """Publish a monotonic pipeline milestone for the polling client."""
        with self._progress_lock:
            bounded = max(0, min(100, int(percent)))
            if state not in {'error', 'cancelled'}:
                bounded = max(self.progress_percent, bounded)
            self.progress_percent = bounded
            self.progress_stage = str(stage or self.progress_stage).strip()
            self.progress_detail = str(detail or '').strip()
            self.progress_state = state
            self.progress_updated_at = datetime.now()
    
    def to_dict(self) -> dict:
        """Convert session to JSON-serializable dictionary."""
        elapsed_from = self.analysis_started_at or self.created_at
        elapsed_seconds = max(0, int((datetime.now() - elapsed_from).total_seconds()))
        with self._progress_lock:
            progress = {
                "percent": self.progress_percent,
                "stage": self.progress_stage,
                "detail": self.progress_detail,
                "state": self.progress_state,
                "updated_at": self.progress_updated_at.isoformat(),
                "elapsed_seconds": elapsed_seconds,
            }
        return {
            "session_id": self.session_id,
            "genes": self.genes,
            "disease": self.disease,
            "disease_name": self.disease_name,
            "disease_context": self.disease_context,
            "model": self.model,
            "status": self.status,
            "current_phase": self.current_phase,
            "current_checkpoint": self.current_checkpoint,
            "waiting_for_user": self.waiting_for_user,
            "progress": progress,
            "messages": self.messages,
            "results": self.results,
            "real_analysis_available": REAL_ANALYSIS_AVAILABLE
        }

# Global session storage
sessions = {}

# ============================================================================
# CHECKPOINT DEFINITIONS
# ============================================================================

CHECKPOINTS = {
    "network_biology": {
        "name": "Module Annotation Query",
        "phase": 1,
        "description": "Annotate network-defined modules with biological functions",
        "suggested_questions": [
            "What biological process does this network-defined module most plausibly represent?",
            "What are the functions these {disease}-related genes implicated in?",
            "What biological support exists for this module? (tissue-level, organ-level, etc)",
            "Given these {disease} GWAS genes, what other genes are functionally connected in the human interactome?"
        ],
        "actions": ["query", "skip"]
    },
    "module_review": {
        "name": "Module Pathway Review",
        "phase": 1,
        "description": "Review GPT-ranked pathways for this module",
        "actions": ["approve", "modify", "skip", "quit"]
    },
    "pathway_query": {
        "name": "Gene Analysis Query",
        "phase": 1,
        "description": "Identify key genes and disease drivers in pathways",
        "suggested_questions": [
            "Which genes in these modules are both network-central and biologically plausible disease drivers?",
            "Highlight the genes which share the same biological support (same pathways)?",
            "In cases where the nearest gene to a GWAS locus lacks functional relevance, which distal candidates can be prioritized based on strong network connectivity to established disease mechanisms?",
            "What genes are most important in {pathway_name} for {disease}?"
        ],
        "actions": ["query", "skip"]
    },
    "aggregation_review": {
        "name": "Aggregation Review",
        "phase": 2,
        "description": "Review combined pathways from all modules",
        "actions": ["approve", "quit"]
    }
}

# ============================================================================
# STATIC FILE SERVING
# ============================================================================

PAGE_FRAGMENT_COMPONENTS = {
    'site-header': 'components/site-header.js',
    'workflow-navigation': 'components/workflow-navigation.js',
    'analysis-input': 'components/analysis-input.js',
    'analysis-runtime': 'components/analysis-runtime.js',
    'analysis-results': 'components/analysis-results.js',
    'run-history': 'components/run-history.js',
    'documentation-view': 'components/documentation-view.js',
    'product-tour': 'components/product-tour.js',
}
_page_fragment_cache = {}


def load_page_fragment_markup(tag_name, component_path):
    """Read the light-DOM template shared by local preview and server output."""
    cache_key = (tag_name, component_path)
    cached = _page_fragment_cache.get(cache_key)
    if cached is not None:
        return cached

    source_path = os.path.join(current_dir, *component_path.split('/'))
    with open(source_path, encoding='utf-8') as component_file:
        javascript = component_file.read()
    start_marker = f"window.definePageFragment('{tag_name}', String.raw`\n"
    end_marker = '\n`);'
    start_index = javascript.find(start_marker)
    end_index = javascript.rfind(end_marker)
    if start_index < 0 or end_index < start_index:
        raise RuntimeError(f'Invalid page fragment component: {component_path}')
    markup = javascript[start_index + len(start_marker):end_index]
    markup = markup.replace(r'\`', '`').replace(r'\${', '${')
    _page_fragment_cache[cache_key] = markup
    return markup


def hydrate_page_fragments(html):
    """Expand page fragments for the hosted response while retaining file preview."""
    for tag_name, component_path in PAGE_FRAGMENT_COMPONENTS.items():
        placeholder = f'<{tag_name}></{tag_name}>'
        if placeholder in html:
            html = html.replace(
                placeholder,
                load_page_fragment_markup(tag_name, component_path),
                1,
            )
    return html


def remove_hosted_fragment_loaders(html):
    """Avoid downloading local-preview fragment scripts after server hydration."""
    fragment_assets = ('components/page-fragment.js', *PAGE_FRAGMENT_COMPONENTS.values())
    for logical_path in fragment_assets:
        script_pattern = re.compile(
            r'\s*<script\s+src=["\']'
            + re.escape(logical_path)
            + r'(?:\?[^"\']*)?["\']></script>'
        )
        html = script_pattern.sub('', html, count=1)
    return html

def render_cache_busted_document(filename):
    """Serve HTML with every local asset URL replaced by its content hash."""
    source_path = os.path.join(current_dir, filename)
    with open(source_path, encoding='utf-8') as source_file:
        html = source_file.read()

    if filename == 'index.html':
        html = hydrate_page_fragments(html)
        html = remove_hosted_fragment_loaders(html)

    for logical_path, fingerprinted_url in CACHE_BUSTED_ASSET_URLS.items():
        asset_pattern = re.compile(
            rf'(?P<prefix>\b(?:src|href)=["\']){re.escape(logical_path)}'
            r'(?:\?[^"\']*)?'
        )
        html = asset_pattern.sub(
            lambda match: f'{match.group("prefix")}{fingerprinted_url}',
            html,
        )

    version_meta = f'<meta name="asset-version" content="{STATIC_ASSET_VERSION}">'
    html = html.replace('</head>', f'    {version_meta}\n</head>', 1)
    response = Response(html, mimetype='text/html')
    response.headers['X-Asset-Version'] = STATIC_ASSET_VERSION
    return response

@app.route('/login')
def login_page():
    if not AUTH_ENABLED:
        return redirect('/')

    user = get_request_user()
    if user_has_access(user):
        return redirect('/')
    return render_cache_busted_document('login.html')


@app.route('/auth/login')
def auth_login():
    if not AUTH_ENABLED:
        return redirect('/')
    if not AUTH_CONFIG_READY or cognito_client is None:
        return redirect('/login?error=setup')

    next_path = request.args.get('next', '/')
    if not next_path.startswith('/') or next_path.startswith('//'):
        next_path = '/'
    session['post_login_next'] = next_path
    callback_url = f'{APP_BASE_URL}/auth/callback'
    return cognito_client.authorize_redirect(callback_url)


@app.route('/auth/callback')
def auth_callback():
    if not AUTH_ENABLED:
        return redirect('/')
    if not AUTH_CONFIG_READY or cognito_client is None:
        return redirect('/login?error=setup')

    try:
        token = cognito_client.authorize_access_token()
        userinfo = token.get('userinfo') or {}
        email = str(userinfo.get('email', '')).strip().lower()
        email_verified = userinfo.get('email_verified')
        if not email or (ACCESS_MODE == 'team' and email not in ALLOWED_EMAILS):
            session.clear()
            return redirect('/login?error=not_allowed')
        if email_verified is False:
            session.clear()
            return redirect('/login?error=email_unverified')

        next_path = session.get('post_login_next', '/')
        session.clear()
        session.permanent = True
        session['user'] = {
            'sub': userinfo.get('sub'),
            'email': email,
            'name': userinfo.get('name') or email.split('@', 1)[0],
            'email_verified': email_verified is not False,
        }
        try:
            quota_manager.register_user(
                str(userinfo.get('sub') or email),
                email,
            )
        except QuotaUnavailable as exc:
            print(f'⚠️ Unable to register quota profile: {exc}')
        return redirect(next_path if next_path.startswith('/') else '/')
    except Exception as exc:
        print(f'⚠️ Cognito callback failed: {exc}')
        session.clear()
        return redirect('/login?error=login_failed')


@app.route('/auth/logout')
def auth_logout():
    session.clear()
    if AUTH_ENABLED and COGNITO_DOMAIN and COGNITO_CLIENT_ID and APP_BASE_URL:
        logout_query = urlencode({
            'client_id': COGNITO_CLIENT_ID,
            'logout_uri': f'{APP_BASE_URL}/login',
        })
        return redirect(f'{COGNITO_DOMAIN}/logout?{logout_query}')
    return redirect('/login' if AUTH_ENABLED else '/')


@app.route('/api/auth/me')
def auth_me():
    user = get_request_user()
    owner_id = get_request_owner_id()
    email = str(user.get('email') or '').strip().lower()
    if owner_id and email:
        try:
            quota_manager.register_user(owner_id, email)
        except QuotaUnavailable:
            pass
    payload = {
        'authenticated': bool(user),
        'email': email or None,
        'name': user.get('name'),
        'access_mode': ACCESS_MODE,
        'is_admin': user_is_admin(user),
    }
    if owner_id:
        try:
            payload['quota'] = get_quota_payload(owner_id, email)
        except QuotaUnavailable:
            payload['quota'] = {'enabled': quota_manager.enabled, 'available': False}
    return jsonify(payload)


@app.route('/')
def serve_index():
    return render_cache_busted_document('index.html')


@app.route('/admin')
def serve_admin():
    return render_cache_busted_document('admin.html')


STATIC_ASSET_ALLOWLIST = set(CACHE_BUSTED_ASSETS)


@app.route('/<path:path>')
def serve_static(path):
    if path not in STATIC_ASSET_ALLOWLIST:
        return Response('Not found', status=404, mimetype='text/plain')
    return send_from_directory(current_dir, path)

# ============================================================================
# API ENDPOINTS
# ============================================================================

def get_quota_payload(owner_id: str, email: str = '') -> dict:
    payload = quota_manager.status(owner_id, email or get_request_email())
    with _active_jobs_lock:
        active_jobs = _active_jobs
    payload.update({
        'available': True,
        'max_concurrent_jobs': MAX_CONCURRENT_JOBS,
        'active_jobs': active_jobs,
        'concurrency_available': active_jobs < MAX_CONCURRENT_JOBS,
    })
    return payload


def acquire_job_slot() -> bool:
    global _active_jobs
    acquired = _job_slots.acquire(blocking=False)
    if acquired:
        with _active_jobs_lock:
            _active_jobs += 1
    return acquired


def release_job_slot() -> None:
    global _active_jobs
    with _active_jobs_lock:
        _active_jobs = max(0, _active_jobs - 1)
    _job_slots.release()


def run_analysis_with_slot(analysis_session) -> None:
    try:
        run_analysis_workflow(analysis_session)
    finally:
        release_job_slot()


def get_owned_session(session_id: str):
    analysis_session = sessions.get(session_id)
    if not analysis_session:
        return None
    if not AUTH_ENABLED or analysis_session.owner_id == get_request_owner_id():
        return analysis_session
    return None


def add_analysis_progress_message(analysis_session, message: str) -> None:
    """Attach a log message and advance the matching late-pipeline milestone."""
    normalized = str(message or '').strip()
    lowered = normalized.casefold()
    if 'resolving cell/tissue context' in lowered:
        analysis_session.set_progress(72, 'Mapping cell and tissue context', normalized)
    elif 'linking cell/tissue context to pubmed' in lowered:
        analysis_session.set_progress(80, 'Linking supporting literature', normalized)
    elif 'writing pathway interpretations' in lowered:
        analysis_session.set_progress(88, 'Writing pathway interpretations', normalized)
    elif 'pathway narratives complete' in lowered:
        analysis_session.set_progress(94, 'Preparing the result', normalized)
    analysis_session.add_message('system', normalized)

@app.route('/api/status', methods=['GET'])
def get_status():
    """Get server status and configuration."""
    status = {
        "status": "ok",
        "auth_enabled": AUTH_ENABLED,
        "auth_ready": AUTH_CONFIG_READY,
        "static_assets": "whitenoise",
        "asset_version": STATIC_ASSET_VERSION,
    }

    user = get_request_user()
    if not AUTH_ENABLED or user_has_access(user):
        status.update({
        "real_analysis_available": REAL_ANALYSIS_AVAILABLE,
        "analysis_error": ANALYSIS_ERROR,
        "openai_configured": bool(OPENAI_API_KEY),
        "entrez_configured": bool(ENTREZ_EMAIL),
        "gpt_model": GPT_MODEL,
        "allowed_gpt_models": list(ALLOWED_GPT_MODELS),
        "access_mode": ACCESS_MODE,
        })
        owner_id = get_request_owner_id()
        if owner_id:
            try:
                status['quota'] = get_quota_payload(owner_id)
            except QuotaUnavailable:
                status['quota'] = {'enabled': quota_manager.enabled, 'available': False}
    return jsonify(status)


@app.route('/api/quota', methods=['GET'])
def get_quota_status():
    owner_id = get_request_owner_id()
    if not owner_id:
        return jsonify({'error': 'Authentication required'}), 401
    try:
        return jsonify(get_quota_payload(owner_id, get_request_email()))
    except QuotaUnavailable as exc:
        return jsonify({
            'error': str(exc),
            'enabled': quota_manager.enabled,
            'available': False,
        }), 503


def get_admin_managed_emails() -> list[str]:
    if ACCESS_MODE == 'team':
        return sorted(ALLOWED_EMAILS)
    return sorted(ALLOWED_EMAILS | ADMIN_EMAILS)


@app.route('/api/admin/users', methods=['GET'])
def get_admin_users():
    try:
        payload = quota_manager.admin_snapshot(get_admin_managed_emails())
    except QuotaUnavailable as exc:
        return jsonify({
            'error': str(exc),
            'enabled': quota_manager.enabled,
            'available': False,
        }), 503
    with _active_jobs_lock:
        active_jobs = _active_jobs
    payload.update({
        'available': True,
        'active_jobs': active_jobs,
        'max_concurrent_jobs': MAX_CONCURRENT_JOBS,
        'managed_user_count': len(payload.get('users', [])),
    })
    return jsonify(payload)


@app.route('/api/admin/users/<path:email>/quota', methods=['PUT'])
def update_admin_user_quota(email):
    normalized_email = str(email or '').strip().lower()
    if normalized_email not in set(get_admin_managed_emails()):
        return jsonify({'error': 'Managed user was not found'}), 404
    data = request.get_json(silent=True) or {}
    if 'daily_limit' not in data:
        return jsonify({'error': 'daily_limit is required'}), 400
    try:
        quota_manager.set_user_limit(normalized_email, data.get('daily_limit'))
        snapshot = quota_manager.admin_snapshot(get_admin_managed_emails())
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 400
    except QuotaUnavailable as exc:
        return jsonify({'error': str(exc), 'available': False}), 503
    user_payload = next(
        (user for user in snapshot.get('users', []) if user.get('email') == normalized_email),
        None,
    )
    return jsonify({'ok': True, 'user': user_payload})

@app.route('/api/analyze', methods=['POST'])
def start_analysis():
    """Start a new analysis session."""
    slot_acquired = False
    try:
        data = request.get_json(silent=True) or {}
        if not isinstance(data, dict):
            return jsonify({'error': 'Request body must be a JSON object'}), 400
        
        # Parse genes
        genes_input = data.get('genes', [])
        if isinstance(genes_input, str):
            import re
            genes = [g.strip().upper() for g in re.split(r'[,\n\s;]+', genes_input) if g.strip()]
        else:
            genes = [g.strip().upper() for g in genes_input if g.strip()]
        
        if len(genes) < 3:
            return jsonify({"error": "Please provide at least 3 genes"}), 400
        
        disease = str(data.get('disease', 'AD') or 'AD').strip()
        disease_error = validate_biomedical_free_text(disease, 'Disease context', 160)
        if disease_error:
            return jsonify({'error': disease_error, 'code': 'unsafe_free_text'}), 400
        raw_disease_context = data.get('disease_context') or {}
        disease_context = {
            key: str(raw_disease_context.get(key) or '').strip()[:500]
            for key in (
                'name', 'database', 'database_id', 'open_targets_id',
                'mesh_id', 'description', 'url'
            )
        } if isinstance(raw_disease_context, dict) else {}
        for key in ('name', 'description'):
            context_error = validate_biomedical_free_text(
                disease_context.get(key),
                f'Disease {key}',
                500,
            )
            if context_error:
                return jsonify({'error': context_error, 'code': 'unsafe_free_text'}), 400
        use_iterative = data.get('use_iterative', False)  # NEW: Iterative mode flag
        try:
            requested_model = normalize_requested_model(data.get('model'))
        except ValueError as exc:
            return jsonify({'error': str(exc), 'code': 'unsupported_model'}), 400

        owner = get_request_user()
        owner_id = get_request_owner_id()
        if not owner_id:
            return jsonify({'error': 'Authentication required'}), 401

        if not acquire_job_slot():
            quota = get_quota_payload(owner_id)
            return jsonify({
                'error': 'Another analysis is currently running. Please try again after it completes.',
                'code': 'concurrency_limit',
                'quota': quota,
            }), 429
        slot_acquired = True

        try:
            quota = quota_manager.reserve(owner_id, get_request_email())
            quota.update(get_quota_payload(owner_id))
        except QuotaExceeded as exc:
            release_job_slot()
            slot_acquired = False
            return jsonify({
                'error': str(exc),
                'code': f'{exc.scope}_daily_limit',
                'quota': exc.status,
            }), 429
        except QuotaUnavailable as exc:
            release_job_slot()
            slot_acquired = False
            return jsonify({
                'error': 'Analysis submissions are temporarily unavailable because usage limits cannot be verified.',
                'code': 'quota_unavailable',
                'detail': str(exc),
            }), 503
        
        # Create session
        session_id = uuid.uuid4().hex
        analysis_session = AnalysisSession(
            session_id,
            genes,
            disease,
            owner_id=owner_id,
            owner_email=str(owner.get('email') or '').strip().lower(),
            disease_context=disease_context,
            model=requested_model,
        )
        analysis_session.use_iterative = use_iterative  # Set iterative mode
        analysis_session.set_progress(
            1,
            'Queued',
            f'Analysis accepted for {len(genes)} submitted genes.',
            state='queued',
        )
        sessions[session_id] = analysis_session
        
        # Initial messages
        mode_text = " (Multiple Runs)" if use_iterative else ""
        analysis_session.add_message("system", f"🔬 Starting pathway analysis for {len(genes)} genes{mode_text}")
        analysis_session.add_message("system", f"📋 Disease context: {analysis_session.disease_name}")
        
        if REAL_ANALYSIS_AVAILABLE:
            analysis_session.add_message("system", "✅ Live hypothesis generation, statistical validation and literature retrieval enabled")
        else:
            analysis_session.add_message("system", f"⚠️ Analysis modules unavailable - using demo mode")
        
        # Start analysis thread
        thread = threading.Thread(target=run_analysis_with_slot, args=(analysis_session,))
        thread.daemon = True
        thread.start()
        slot_acquired = False  # The worker now owns and releases the slot.
        
        return jsonify({
            "session_id": session_id,
            "status": "started",
            "message": f"Analysis started for {len(genes)} genes",
            "real_analysis": REAL_ANALYSIS_AVAILABLE,
            "model": analysis_session.model,
            "quota": quota,
        })
        
    except Exception as e:
        if slot_acquired:
            release_job_slot()
        return jsonify({"error": str(e)}), 500


@app.route('/api/progress/<session_id>', methods=['GET'])
def get_progress(session_id):
    analysis_session = get_owned_session(session_id)
    if not analysis_session:
        return jsonify({"error": "Session not found"}), 404
    return jsonify(analysis_session.to_dict())


@app.route('/api/checkpoint/<session_id>', methods=['POST'])
def handle_checkpoint(session_id):
    analysis_session = get_owned_session(session_id)
    if not analysis_session:
        return jsonify({"error": "Session not found"}), 404
    
    if not analysis_session.waiting_for_user:
        return jsonify({"error": "Not waiting for user input"}), 400
    
    data = request.get_json()
    action = data.get('action', 'approve')
    action_data = data.get('data', {})
    
    analysis_session.add_message("user", f"Selected: {action.upper()}", {"action": action, "data": action_data})
    analysis_session.checkpoint_data['user_response'] = action
    analysis_session.checkpoint_data['user_data'] = action_data
    analysis_session.waiting_for_user = False
    
    return jsonify({"status": "received", "action": action})


@app.route('/api/query/<session_id>', methods=['POST'])
def handle_query(session_id):
    analysis_session = get_owned_session(session_id)
    if not analysis_session:
        return jsonify({"error": "Session not found"}), 404
    
    data = request.get_json(silent=True) or {}
    if not isinstance(data, dict):
        return jsonify({'error': 'Request body must be a JSON object'}), 400
    query = str(data.get('query', '') or '').strip()
    if not query:
        return jsonify({'error': 'Question is required'}), 400
    query_error = validate_biomedical_free_text(query, 'Question', 1000)
    if query_error:
        return jsonify({'error': query_error, 'code': 'unsafe_free_text'}), 400
    context = data.get('context', 'general')

    checkpoint_type = analysis_session.current_checkpoint
    checkpoint = CHECKPOINTS.get(checkpoint_type, {})
    if not analysis_session.waiting_for_user or 'query' not in checkpoint.get('actions', []):
        return jsonify({
            'error': 'This question checkpoint is no longer active.',
            'code': 'checkpoint_not_active',
        }), 409
    
    analysis_session.add_message("user", query)
    response = process_user_query(analysis_session, query, context)
    analysis_session.add_message("result", response['answer'], response.get('data'))

    # A successful answer completes query-enabled checkpoints. This keeps the
    # answer and the workflow transition in one server-side operation, so the
    # analysis cannot remain blocked waiting for a second Skip click.
    auto_advanced = bool(
        analysis_session.waiting_for_user
        and analysis_session.current_checkpoint == checkpoint_type
    )
    if auto_advanced:
        analysis_session.checkpoint_data['user_response'] = 'query'
        analysis_session.checkpoint_data['user_data'] = {
            'query': query,
            'auto_advanced': True,
        }
        analysis_session.waiting_for_user = False
        analysis_session.set_progress(
            max(4, analysis_session.progress_percent),
            'Continuing analysis',
            'Question answered. Starting the next analysis step.',
            state='running',
        )
    
    return jsonify({**response, 'auto_advanced': auto_advanced})


@app.route('/api/report/<session_id>', methods=['GET'])
def get_report(session_id):
    analysis_session = get_owned_session(session_id)
    if not analysis_session:
        return jsonify({"error": "Session not found"}), 404
    
    if analysis_session.status != "completed":
        return jsonify({"error": "Analysis not yet complete"}), 400
    
    report = generate_summary_report(analysis_session)
    return jsonify({"report": report})


def get_export_session(session_id):
    """Resolve a live, bundled-demo, or read-only completed history run."""
    owner_id = get_request_owner_id()
    active_session = sessions.get(session_id)
    if active_session and (
        not AUTH_ENABLED or active_session.owner_id == owner_id
    ):
        return active_session

    # The bundled example is self-contained so its exports continue to work in
    # a fresh AWS instance even when no mutable run-history file is deployed.
    demo_json_path = os.path.join(current_dir, 'offline_demo_data.json')
    try:
        if os.path.exists(demo_json_path):
            with open(demo_json_path, 'r', encoding='utf-8') as demo_file:
                demo_result = json.load(demo_file)
            if demo_result.get('session_id') == session_id:
                restored = AnalysisSession(
                    session_id,
                    list(
                        demo_result.get('input_genes')
                        or demo_result.get('query_genes')
                        or []
                    ),
                    demo_result.get('disease') or 'AD',
                    model=demo_result.get('model') or GPT_MODEL,
                )
                restored.disease_name = demo_result.get('disease_name') or restored.disease_name
                restored.status = 'completed'
                restored.results = demo_result
                restored.messages = [
                    {
                        'type': 'result',
                        'content': f"Database reasoning record - {record.get('category', 'Unknown')}",
                        'data': {
                            'reasoning': record.get('reasoning'),
                            'category': record.get('category'),
                            'iteration': record.get('iteration', 1),
                        },
                    }
                    for record in demo_result.get('reasoning_traces', [])
                    if record.get('reasoning')
                ]
                return restored
    except (OSError, json.JSONDecodeError, TypeError):
        # A missing optional demo export must not break normal history export.
        pass

    # Resolve every bundled completed example, not only the legacy AD demo.
    # This keeps exports and narrative regeneration available for all seven
    # diseases after a fresh deployment.
    completed_examples_path = os.path.join(current_dir, 'offline_completed_examples.json')
    try:
        if os.path.exists(completed_examples_path):
            with open(completed_examples_path, 'r', encoding='utf-8') as archive_file:
                archive = json.load(archive_file)
            for example in (archive.get('examples') or {}).values():
                result = example.get('result') or {}
                if result.get('session_id') != session_id:
                    continue
                current_user = get_request_user()
                restored = AnalysisSession(
                    session_id,
                    list(result.get('input_genes') or result.get('query_genes') or []),
                    result.get('disease') or example.get('code') or 'Unknown disease',
                    owner_id=owner_id,
                    owner_email=str(current_user.get('email') or '').strip().lower(),
                    model=result.get('model') or GPT_MODEL,
                )
                restored.disease_name = (
                    result.get('disease_name')
                    or example.get('disease')
                    or restored.disease_name
                )
                restored.status = 'completed'
                restored.results = result
                restored.messages = [
                    {
                        'type': 'result',
                        'content': f"Database reasoning record - {record.get('category', 'Unknown')}",
                        'data': {
                            'reasoning': record.get('reasoning'),
                            'category': record.get('category'),
                            'iteration': record.get('iteration', 1),
                        },
                    }
                    for record in result.get('reasoning_traces', [])
                    if record.get('reasoning')
                ]
                return restored
    except (OSError, json.JSONDecodeError, TypeError, AttributeError):
        pass

    for entry in load_history():
        if entry.get('session_id') != session_id:
            continue
        if AUTH_ENABLED and entry.get('owner_id') != owner_id:
            continue
        restored = AnalysisSession(
            session_id,
            list(entry.get('genes') or []),
            entry.get('disease') or entry.get('disease_name') or 'Unknown disease',
            owner_id=str(entry.get('owner_id') or ''),
            owner_email=str(entry.get('owner_email') or ''),
            model=entry.get('model') or GPT_MODEL,
        )
        restored.disease_name = entry.get('disease_name') or restored.disease_name
        restored.status = entry.get('status') or 'completed'
        restored.messages = list(entry.get('messages') or [])
        restored.results = dict(entry.get('results') or {})
        created_at = entry.get('created_at')
        if created_at:
            try:
                restored.created_at = datetime.fromisoformat(created_at)
            except (TypeError, ValueError):
                pass
        return restored
    return None


def retry_pathway_narratives_with_slot(analysis_session):
    """Regenerate narratives without rerunning enrichment or pathway ranking."""
    try:
        analysis_session.analysis_started_at = datetime.now()
        analysis_session.set_progress(
            12,
            'Preparing pathway records',
            'Loading the validated pathways from the completed result.',
        )
        pathways = normalize_pathway_records(
            copy.deepcopy(analysis_session.results.get('pathways') or [])
        )
        analysis_session.add_message(
            'system',
            f'Regenerating validated pathway narratives for all {len(pathways)} pathways...',
        )
        attach_pathway_narratives(
            pathways,
            analysis_session.disease_name,
            progress=lambda message: add_analysis_progress_message(analysis_session, message),
            model=analysis_session.model,
        )
        analysis_session.results['pathways'] = pathways
        generated = sum(
            1 for pathway in pathways
            if pathway.get('pathway_narrative', {}).get('generated') is True
        )
        fallback = len(pathways) - generated
        analysis_session.results['narrative_regeneration'] = {
            'generated': generated,
            'fallback': fallback,
            'total': len(pathways),
            'completed_at': datetime.now().isoformat(),
        }
        analysis_session.results['completed_at'] = datetime.now().isoformat()
        analysis_session.results['run_summary'] = compute_run_summary(
            pathways,
            analysis_session.genes,
            analysis_session.disease_name,
            analysis_session.results.get('mapping_summary'),
        )
        analysis_session.status = 'completed'
        analysis_session.set_progress(
            100,
            'Narrative regeneration complete',
            f'Prepared {generated} model-generated narratives; {fallback} used fallback text.',
            state='completed',
        )
        analysis_session.add_message(
            'system',
            f'Narrative regeneration complete: {generated} generated, {fallback} fallback.',
        )
        save_run_to_history(analysis_session)
    except Exception as exc:
        analysis_session.status = 'error'
        analysis_session.set_progress(
            analysis_session.progress_percent,
            'Narrative regeneration stopped',
            pathway_narrative.exception_summary(exc),
            state='error',
        )
        analysis_session.add_message(
            'error',
            f'Narrative regeneration failed: {pathway_narrative.exception_summary(exc)}',
        )
        import traceback
        traceback.print_exc()
    finally:
        release_job_slot()


@app.route('/api/retry-narratives/<session_id>', methods=['POST'])
def retry_pathway_narratives(session_id):
    """Create an owned retry session for a completed result's narratives."""
    slot_acquired = False
    source_session = get_export_session(session_id)
    if not source_session:
        return jsonify({'error': 'Completed result not found'}), 404
    if source_session.status != 'completed':
        return jsonify({'error': 'Analysis is not complete'}), 400

    owner = get_request_user()
    owner_id = get_request_owner_id()
    if not owner_id:
        return jsonify({'error': 'Authentication required'}), 401

    if not acquire_job_slot():
        return jsonify({
            'error': 'Another analysis is currently running. Please retry after it completes.',
            'code': 'concurrency_limit',
            'quota': get_quota_payload(owner_id),
        }), 429
    slot_acquired = True

    try:
        quota = quota_manager.reserve(owner_id, get_request_email())
        quota.update(get_quota_payload(owner_id))
    except QuotaExceeded as exc:
        release_job_slot()
        slot_acquired = False
        return jsonify({
            'error': str(exc),
            'code': f'{exc.scope}_daily_limit',
            'quota': exc.status,
        }), 429
    except QuotaUnavailable as exc:
        release_job_slot()
        slot_acquired = False
        return jsonify({
            'error': 'Narrative regeneration is unavailable because usage limits cannot be verified.',
            'code': 'quota_unavailable',
            'detail': str(exc),
        }), 503

    try:
        retry_session_id = f"narrative-{uuid.uuid4().hex}"
        retry_session = AnalysisSession(
            retry_session_id,
            list(source_session.genes),
            source_session.disease,
            owner_id=owner_id,
            owner_email=str(owner.get('email') or '').strip().lower(),
            disease_context=copy.deepcopy(source_session.disease_context),
            model=source_session.model,
        )
        retry_session.disease_name = source_session.disease_name
        retry_session.status = 'running'
        retry_session.set_progress(
            1,
            'Queued',
            'Narrative regeneration was accepted.',
            state='queued',
        )
        retry_session.results = copy.deepcopy(source_session.results)
        retry_session.results['session_id'] = retry_session_id
        retry_session.messages = copy.deepcopy(source_session.messages)
        retry_session.add_message('system', 'Starting pathway narrative regeneration...')
        sessions[retry_session_id] = retry_session

        thread = threading.Thread(
            target=retry_pathway_narratives_with_slot,
            args=(retry_session,),
        )
        thread.daemon = True
        thread.start()
        slot_acquired = False
        return jsonify({
            'session_id': retry_session_id,
            'status': 'started',
            'quota': quota,
        })
    except Exception as exc:
        if slot_acquired:
            release_job_slot()
        return jsonify({'error': pathway_narrative.exception_summary(exc)}), 500

@app.route('/api/export/<session_id>/<fmt>', methods=['GET'])
def export_data(session_id, fmt):
    session = get_export_session(session_id)
    if not session:
        return jsonify({"error": "Session not found"}), 404
    if session.status != "completed":
        return jsonify({"error": "Analysis not yet complete"}), 400

    pathways = normalize_pathway_records(session.results.get('pathways', []))

    if fmt in ('pdf', 'pdf-summary'):
        raw_limit = str(request.args.get('limit') or 'all').strip().lower()
        if raw_limit == 'all':
            pathways_per_database = None
        elif raw_limit in {'3', '5', '10'}:
            pathways_per_database = int(raw_limit)
        else:
            return jsonify({"error": "PDF pathway limit must be one of: all, 3, 5, 10"}), 400
        try:
            pdf_buffer = generate_full_export_pdf(
                session,
                summary_only=(fmt == 'pdf-summary'),
                pathways_per_database=pathways_per_database,
            )
        except ImportError:
            return jsonify({
                "error": "PDF export dependency is unavailable. Install the application requirements and retry."
            }), 503
        except Exception as exc:
            app.logger.exception("PDF export failed for session %s", session_id)
            return jsonify({
                "error": f"PDF report could not be generated: {str(exc)[:180]}"
            }), 500
        safe_disease = ''.join(
            character if character.isalnum() or character in ('-', '_') else '_'
            for character in session.disease_name
        ).strip('_') or 'analysis'
        filename = (
            f"GenePathwayAI_{safe_disease}_{'summary' if fmt == 'pdf-summary' else 'detailed'}_"
            f"{'all' if pathways_per_database is None else f'top{pathways_per_database}'}_{session_id[:8]}.pdf"
        )
        # Production uses Flask 3 (`download_name`). Keep the endpoint usable in
        # older local Flask environments as well, where the same argument was
        # named `attachment_filename`.
        import inspect
        send_file_parameters = inspect.signature(send_file).parameters
        filename_parameter = (
            'download_name'
            if 'download_name' in send_file_parameters
            else 'attachment_filename'
        )
        cache_parameter = 'max_age' if 'max_age' in send_file_parameters else 'cache_timeout'
        response = send_file(
            pdf_buffer,
            mimetype='application/pdf',
            as_attachment=True,
            **{filename_parameter: filename, cache_parameter: 0},
        )
        response.headers['Content-Length'] = str(len(pdf_buffer.getbuffer()))
        return response

    elif fmt == 'csv':
        import csv, io
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow([
            'Database', 'Pathway ID', 'Database Rank', 'Pathway',
            'Adjusted P-value', 'Pathway Size', 'Overlap Count',
            'Intersection Genes', 'GPT_Predicted', 'Description',
            'Pathway Narrative', 'Narrative Generated', 'Driving Genes',
            'Functional Clusters', 'External Corroborating Genes',
            'External Evidence PMIDs', 'Cell/Tissue Context',
            'Pathway-level Cell Context PMIDs (not claim-mapped)', 'PMIDs'
        ])
        database_ranks = {}
        for pw in pathways:
            category = pw.get('source') or pw.get('category', 'Other')
            database_ranks[category] = database_ranks.get(category, 0) + 1
            pmids = ';'.join(pw.get('pmids', []))
            narrative = pw.get('pathway_narrative') or {}
            narrative_text = '\n\n'.join(filter(None, (
                pathway_narrative.sanitize_narrative_paragraph(paragraph)
                for paragraph in narrative.get('paragraphs', [])
            )))
            driver_genes = ';'.join(
                str(gene).strip()
                for gene in narrative.get('driver_genes', [])
                if str(gene).strip()
            )
            clusters = '; '.join(
                f"{str(cluster.get('label') or 'Cluster').strip()}: "
                + '|'.join(
                    str(gene).strip()
                    for gene in cluster.get('genes', [])
                    if str(gene).strip()
                )
                for cluster in narrative.get('clusters', [])
                if isinstance(cluster, dict)
            )
            external_entries = (
                pw.get('external_evidence_genes')
                or pw.get('independent_evidence_genes')
                or []
            )
            external_genes = ';'.join(
                str(entry.get('gene') or '').strip()
                for entry in external_entries
                if isinstance(entry, dict) and str(entry.get('gene') or '').strip()
            )
            external_pmids = '; '.join(
                f"{str(entry.get('gene') or '').strip()}:"
                + '|'.join(
                    str(pmid).strip()
                    for pmid in entry.get('pmids', [])
                    if str(pmid).strip()
                )
                for entry in external_entries
                if isinstance(entry, dict) and entry.get('gene') and entry.get('pmids')
            )
            writer.writerow([
                category, get_pathway_identifier(pw) or 'ID unavailable',
                database_ranks[category], pw.get('name', ''),
                f"{pw.get('p_value', 1.0):.2e}",
                pw.get('term_size') or '',
                pw.get('intersection_size') or len(pw.get('intersection_genes') or []),
                ','.join(pw.get('intersection_genes') or []) or pw.get('genes', ''),
                pw.get('gpt_predicted', False),
                pw.get('description', '')[:200],
                narrative_text,
                narrative.get('generated') is True,
                driver_genes,
                clusters,
                external_genes,
                external_pmids,
                pw.get('cell_context', ''),
                ';'.join(str(pmid) for pmid in pw.get('cell_context_pmids', []) if pmid),
                pmids
            ])
        csv_text = output.getvalue()
        csv_filename = f"pathways_{session.disease_name.replace(' ', '_')}_{session_id[:8]}.csv"
        if request.args.get('download') == '1':
            return Response(
                csv_text,
                mimetype='text/csv',
                headers={'Content-Disposition': f'attachment; filename="{csv_filename}"'},
            )
        return jsonify({"data": csv_text, "filename": csv_filename, "mime": "text/csv"})

    elif fmt == 'json':
        non_result_fields = {'score', 'gpt_score', 'evidence_score', 'relevance_score'}

        def sanitize_public_value(value, field_name=''):
            if isinstance(value, dict):
                return {
                    key: sanitize_public_value(item, key)
                    for key, item in value.items()
                    if key not in non_result_fields
                }
            if isinstance(value, list):
                cleaned = [sanitize_public_value(item, field_name) for item in value]
                return [item for item in cleaned if item not in (None, '')]
            if isinstance(value, str) and field_name == 'paragraphs':
                return pathway_narrative.sanitize_narrative_paragraph(value)
            return value

        public_pathways = sanitize_public_value(pathways)
        export_obj = {
            "metadata": {
                "disease": session.disease_name,
                "gene_count": len(session.genes),
                "genes": session.genes,
                "analysis_date": datetime.now().isoformat(),
                "model": session.model,
                "mode": "Real Pipeline" if REAL_ANALYSIS_AVAILABLE else "Demo Mode"
            },
            "pathways": public_pathways,
            "reasoning": {}
        }
        for msg in session.messages:
            if msg.get('data') and msg['data'].get('reasoning'):
                cat = msg['data'].get('category', 'unknown')
                it = msg['data'].get('iteration', 1)
                key = f"{cat}_iter{it}"
                export_obj["reasoning"][key] = msg['data']['reasoning']
        import json
        json_text = json.dumps(export_obj, indent=2, ensure_ascii=False)
        json_filename = f"analysis_data_{session.disease_name.replace(' ', '_')}_{session_id[:8]}.json"
        if request.args.get('download') == '1':
            return Response(
                json_text,
                mimetype='application/json',
                headers={'Content-Disposition': f'attachment; filename="{json_filename}"'},
            )
        return jsonify({"data": json_text, "filename": json_filename, "mime": "application/json"})

    else:
        return jsonify({"error": f"Unknown format: {fmt}"}), 400


# ============================================================================
# REAL ANALYSIS FUNCTIONS
# ============================================================================

def get_disease_configuration(disease_name: str) -> dict:
    """Get disease configuration from MeSH/NCBI."""
    try:
        mesh_id = disease_name_to_mesh_id(disease_name)

        description, source = get_disease_description_with_fallback(disease_name)
        if not description:
            description = f"Analysis of {disease_name}-related pathways and mechanisms."
        
        disease_code = disease_name.split()[0].upper()[:5]
        for abbr, full in ABBREVIATION_EXPANSION.items():
            if full.lower() == disease_name.lower():
                disease_code = abbr
                break
        
        return {
            "mesh_id": mesh_id,
            "full_name": disease_name,
            "disease_code": disease_code,
            "description": description
        }
    except Exception as e:
        print(f"⚠️ Disease config error: {e}")
        return {
            "mesh_id": '',
            "full_name": disease_name,
            "disease_code": disease_name[:3].upper(),
            "description": f"Analysis of {disease_name}-related pathways."
        }


def run_real_pathway_analysis(session: AnalysisSession) -> list:
    """
    Run FULL pathway analysis pipeline:
    1. GPT predicts 50 pathways (5 categories × 10)
    2. g:Profiler enrichment analysis
    3. Match GPT predictions with g:Profiler results
    4. GPT Auto-Rank matched pathways with PubMed evidence
    
    Supports ITERATIVE MODE (2 iterations) when session.use_iterative = True
    """
    if not REAL_ANALYSIS_AVAILABLE:
        return generate_mock_pathways(session.disease)
    
    # =================================================================
    # ITERATIVE MODE: 2 iterations for more comprehensive analysis
    # =================================================================
    if session.use_iterative:
        return run_iterative_pathway_analysis(session)

    # =================================================================
    # SINGLE-SHOT MODE: Original logic (default)
    # =================================================================
    
    try:
        # Get disease config
        disease_config = get_disease_configuration(session.disease_name)
        session.disease_config = disease_config
        disease_description = disease_config.get('description', '')
        
        # ================================================================
        # STEP 1: GPT-5 Pathway Prediction (Hypothesis Generation)
        # ================================================================
        session.set_progress(
            12,
            'Generating pathway hypotheses',
            'Evaluating the submitted genes across five pathway databases.',
        )
        session.add_message("system", "🧠 Step 1: GPT-5 generating pathway predictions...")

        reasoning_by_category = {}  # Will store reasoning for each category
        try:
            predicted_pathways, pathway_details, reasoning_by_category = gpt_predict_pathways(
                genes=session.genes,
                disease_name=session.disease_name,
                disease_description=disease_description,
                iteration=1,
                model=session.model,
            )
            session.add_message("system", f"✅ GPT predicted {len(predicted_pathways)} pathways (5 categories × 10)")

            # Add reasoning panels for each category
            if reasoning_by_category:
                for category_code, reasoning_dict in reasoning_by_category.items():
                    session.add_message("result", f"🧠 AI Reasoning Path - {category_code}", data={
                        "reasoning": reasoning_dict,
                        "category": category_code,
                        "iteration": 1
                    })
                session.add_message("system", f"💭 Generated reasoning for {len(reasoning_by_category)} categories")

        except Exception as e:
            print(f"GPT prediction error: {e}")
            session.add_message("system", f"⚠️ Hypothesis generation failed: {str(e)[:50]}; continuing with enrichment results")
            predicted_pathways = []
            pathway_details = {}
        
        # ================================================================
        # STEP 2: g:Profiler Enrichment Analysis (FULL - no threshold)
        # ================================================================
        # Like original HITL script: get ALL pathways first for matching,
        # then filter by FDR after matching. This allows matched ≠ fdr_filtered.
        session.set_progress(
            28,
            'Running statistical validation',
            'Testing pathway enrichment and applying multiple-testing correction.',
        )
        session.add_message("system", "🔬 Step 2: Functional enrichment and statistical validation...")
        
        try:
            from gprofiler import GProfiler
            gp = GProfiler(return_dataframe=True)
            
            # Call g:Profiler WITHOUT FDR threshold (get all pathways)
            # CRITICAL: user_threshold=1.0 ensures we get non-significant pathways too
            enrichment_results = gp.profile(
                organism='hsapiens',
                query=session.genes,
                sources=['GO:BP', 'GO:MF', 'GO:CC', 'KEGG', 'REAC'],
                user_threshold=1.0,
                significance_threshold_method='fdr',
                # Retain g:Profiler's query–term intersection genes for each
                # pathway instead of reducing the result to a gene count.
                no_evidences=False
            )
            session.results['mapping_summary'] = summarize_gprofiler_gene_mapping(
                getattr(gp, 'meta', {}),
                session.genes,
            )
            
            if enrichment_results.empty:
                session.add_message("system", "⚠️ No pathway enrichment results were returned")
                return generate_mock_pathways(session.disease)
            
            # Debug: Check p-value distribution
            n_total = len(enrichment_results)
            n_sig = (enrichment_results['p_value'] < 0.05).sum()
            n_nonsig = n_total - n_sig
            print(f"DEBUG: g:Profiler returned {n_total} pathways. Sig (p<0.05): {n_sig}, Non-sig: {n_nonsig}")
            if n_nonsig > 0:
                print(f"DEBUG: Sample non-sig p-values: {enrichment_results[enrichment_results['p_value'] >= 0.05]['p_value'].head().tolist()}")
            
            session.add_message("system", f"✅ Enrichment analysis returned {n_total} pathways ({n_sig} significant)")
            
        except Exception as e:
            print(f"g:Profiler error: {e}")
            session.add_message("system", f"⚠️ Enrichment service error: {str(e)[:50]}. Using demo data.")
            return generate_mock_pathways(session.disease)
        
        # ================================================================
        # STEP 3: Match GPT Predictions with g:Profiler Results
        # ================================================================
        matched_pathways, category_stats = match_gpt_with_gprofiler_detailed(
            gpt_predictions=predicted_pathways,
            pathway_details=pathway_details,
            gprofiler_results=enrichment_results
        )
        
        # DEBUG: Print GPT predictions by category
        debug_output = ["\n=== DEBUG: GPT Predictions ==="]
        for cat in ['GO:BP', 'GO:MF', 'GO:CC', 'KEGG', 'REAC']:
            cat_preds = [name for name, details in pathway_details.items() if details.get('source') == cat]
            debug_output.append(f"{cat}: {len(cat_preds)} predictions")
            for pred in cat_preds[:5]:  # Show first 5
                debug_output.append(f"  - {pred}")
        debug_output.append("=" * 50)
        
        debug_text = "\n".join(debug_output)
        print(debug_text)
        
        # Also save to file for easy access
        try:
            debug_file = os.path.join(current_dir, 'debug_gpt_predictions.txt')
            with open(debug_file, 'w') as f:
                f.write(debug_text)
                f.write(f"\n\nTotal predictions: {len(pathway_details)}\n")
                f.write("\nFull prediction list:\n")
                for name, details in pathway_details.items():
                    f.write(f"  [{details.get('source')}] {name}\n")
        except Exception as e:
            print(f"Could not write debug file: {e}")
        
        # Display category statistics as HTML table
        session.set_progress(
            42,
            'Matching validated pathways',
            'Linking generated hypotheses to statistically supported enrichment records.',
        )
        session.add_message("system", "🔗 Step 3: Matching pathway hypotheses with enrichment results...")
        
        # Calculate stats for table
        stats_rows = []
        total_predicted = 0
        total_matched = 0
        total_validated = 0
        total_matched_records = 0
        total_validated_records = 0
        initial_hypotheses_by_database = {}
        hypothesis_validation_by_database = {}
        
        for cat in ['GO:BP', 'GO:MF', 'GO:CC', 'KEGG', 'REAC']:
            stat = category_stats.get(cat, {'predicted': 0, 'matched': 0, 'fdr_filtered': 0})
            
            initial_count = stat['predicted']
            match_count = stat['matched']
            validated_count = stat.get('fdr_filtered', 0)
            matched_records = stat.get('matched_records', match_count)
            validated_records = stat.get('fdr_records', validated_count)
            initial_hypotheses_by_database[cat] = int(initial_count)

            match_rate = (match_count / initial_count * 100) if initial_count > 0 else 0
            validation_rate = hypothesis_validation_rate(validated_count, match_count)
            hypothesis_validation_by_database[cat] = {
                'matched_hypotheses': int(match_count),
                'statistically_validated_hypotheses': int(validated_count),
                'matched_enrichment_records': int(matched_records),
                'statistically_validated_enrichment_records': int(validated_records),
            }
            
            stats_rows.append({
                'category': cat,
                'initial': initial_count,
                'match': match_count,
                'match_rate': f"{match_rate:.0f}%",
                'validated': validated_count,
                'validation_rate': f"{validation_rate:.0f}%",
                'term_matches': f"{validated_records}/{matched_records}",
            })

            total_predicted += initial_count
            total_matched += match_count
            total_validated += validated_count
            total_matched_records += matched_records
            total_validated_records += validated_records

        overall_match_rate = (total_matched / max(total_predicted, 1)) * 100
        overall_validation_rate = hypothesis_validation_rate(total_validated, total_matched)

        stats_html = '''<div class="stats-container">
        <h4><svg class="ph" aria-hidden="true" focusable="false"><use href="#ph-chart-bar"></use></svg> Hypothesis-level validation</h4>
        <table class="pathway-table stats-table">
            <thead>
                <tr>
                    <th>Database</th>
                    <th>Initial hypotheses</th>
                    <th>Matched hypotheses</th>
                    <th>Match rate</th>
                    <th>Statistically validated hypotheses</th>
                    <th>Validation rate</th>
                </tr>
            </thead>
            <tbody>'''
        
        for row in stats_rows:
            stats_html += f'''
                <tr>
                    <td><span class="category-badge {row['category'].replace(':', '-')}">{row['category']}</span></td>
                    <td>{row['initial']}</td>
                    <td><strong>{row['match']}</strong></td>
                    <td>{row['match_rate']}</td>
                    <td><strong>{row['validated']}</strong></td>
                    <td>{row['validation_rate']}</td>
                </tr>'''
        
        stats_html += f'''
            </tbody>
        </table>
        <div class="stats-summary">
            <strong>{total_predicted} generated → {total_matched} matched → {total_validated} statistically validated ({overall_validation_rate:.1f}% of matched hypotheses).</strong>
        </div>
        </div>'''
        
        session.add_message("system", stats_html)
        
        # If no matches, use top g:Profiler results directly
        if matched_pathways.empty:
            session.add_message("system", "⚠️ No generated hypotheses were validated; using the strongest enrichment results")
            matched_pathways = enrichment_results.sort_values('p_value').head(30)
        else:
            # CRITICAL: Filter for FDR significance (p < 0.05) for downstream analysis
            # This matches original HITL script behavior: "Using FDR-filtered pathways for downstream analysis"
            original_count = len(matched_pathways)
            matched_pathways = matched_pathways[matched_pathways['p_value'] < 0.05].copy()
            filtered_count = len(matched_pathways)
            
            if filtered_count < original_count:
                session.add_message(
                    "system",
                    f"📉 Enrichment-record gate: {original_count} matched records → "
                    f"{filtered_count} statistically significant records pass the corrected threshold"
                )
            
            if matched_pathways.empty:
                session.add_message("system", "⚠️ No matched pathways passed the corrected threshold; using the strongest supported enrichment results")
                matched_pathways = enrichment_results[enrichment_results['p_value'] < 0.05].sort_values('p_value').head(30)
        
        # Cell/tissue context is resolved here, after the FDR gate, so it
        # describes the pathways that actually survived rather than the
        # hypothesis set. See cell_context.py.
        validated_cell_context = {}
        try:
            validated_payload = [
                {
                    'name': row.get('name'),
                    'source': row.get('source'),
                    'genes': row.get('intersections') if isinstance(row.get('intersections'), list) else [],
                }
                for row in matched_pathways.to_dict('records')
                if row.get('name')
            ]
            if validated_payload:
                session.set_progress(
                    54,
                    'Mapping cell and tissue context',
                    f'Resolving context for {len(validated_payload)} validated pathways.',
                )
                session.add_message(
                    "system",
                    f"Resolving cell/tissue context for {len(validated_payload)} validated pathways..."
                )
            validated_cell_context = cell_context_module.generate_pathway_cell_context(
                validated_payload, session.disease_name, genes=session.genes, model=session.model
            )
            # The reasoning panel keeps its Cell Context slot, but the
            # pre-validation category summary written during hypothesis
            # generation is replaced with the post-validation per-pathway block.
            if validated_cell_context and reasoning_by_category:
                by_source = {}
                for row in matched_pathways.to_dict('records'):
                    source = row.get('source')
                    name = row.get('name')
                    if source and name:
                        by_source.setdefault(source, []).append(name)
                for category_code, reasoning_dict in reasoning_by_category.items():
                    if not isinstance(reasoning_dict, dict):
                        continue
                    block = cell_context_module.format_cell_context_lines(
                        validated_cell_context, by_source.get(category_code, [])
                    )
                    if block:
                        reasoning_dict['cell_context'] = block
        except Exception as exc:
            print(f"     cell context step skipped: {str(exc)[:100]}")

        # ================================================================
        # STEP 4: GPT Auto-Rank with 5 Evidence Sources
        # ================================================================
        session.set_progress(
            64,
            'Ranking validated pathways',
            f'Ranking {len(matched_pathways)} pathways using the available evidence.',
        )
        session.add_message("system", f"🤖 Step 4: GPT-5 ranking {len(matched_pathways)} pathways...")
        
        try:
            ranked_pathways = gpt_rank_pathways_direct(
                matched_pathways,
                session.disease_name,
                disease_description,
                top_n=30,
                model=session.model,
            )
        except Exception as e:
            print(f"GPT ranking error: {e}")
            ranked_pathways = matched_pathways.sort_values('p_value').head(30)
        
        # ================================================================
        # STEP 5: Select balanced pathways across categories
        # ================================================================
        # Aim for ~4 per category to get 20 total, balanced across all 5 sources
        pathways_list = []
        import math
        
        # Group by category
        categories_order = ['GO:BP', 'GO:MF', 'GO:CC', 'KEGG', 'REAC']
        per_category = {}
        
        for cat in categories_order:
            cat_df = ranked_pathways[ranked_pathways['source'] == cat] if 'source' in ranked_pathways.columns else pd.DataFrame()
            per_category[cat] = cat_df
        
        # Select top pathways from each category (balanced)
        pathways_per_cat = 4  # 4 per category = 20 total
        selected_rows = []
        
        for cat in categories_order:
            cat_df = per_category.get(cat, pd.DataFrame())
            if not cat_df.empty:
                selected_rows.extend(cat_df.head(pathways_per_cat).to_dict('records'))
        
        # If we don't have enough, add more from any category
        remaining = 20 - len(selected_rows)
        if remaining > 0 and not ranked_pathways.empty:
            already_selected = set(r.get('name', '') for r in selected_rows)
            for _, row in ranked_pathways.iterrows():
                if row.get('name', '') not in already_selected:
                    selected_rows.append(row.to_dict())
                    if len(selected_rows) >= 20:
                        break
        
        # Convert to output format grouped by category
        rank = 1
        for row in selected_rows[:20]:
            if isinstance(row, dict):
                p_val = row.get('p_value', 0.05)
            else:
                p_val = row.get('p_value', 0.05) if hasattr(row, 'get') else 0.05
            
            # Score: use -log10(p_value) * 10, capped at 100
            # Smaller p-value = higher score
            score = min(100, max(0, -10 * math.log10(float(p_val) + 1e-300)))
            is_gpt_predicted = row.get('gpt_validated', False) if isinstance(row, dict) else False
            
            # Get full literature list with PMIDs
            literature = row.get('related_literature', []) if isinstance(row, dict) else []
            pmid_list = []
            if literature and isinstance(literature, list):
                for lit in literature[:5]:  # Get up to 5 references
                    if isinstance(lit, dict):
                        pmid = lit.get('pmid', lit.get('PMID', ''))
                        if pmid:
                            pmid_list.append(str(pmid))
            
            # Use the model interpretation when available; otherwise emit a
            # transparent three-part fallback instead of an empty section.
            disease_connection = row.get('disease_connection', '') if isinstance(row, dict) else ''
            raw_original_desc = row.get('description', '') if isinstance(row, dict) else ''
            original_desc = '' if pd.isna(raw_original_desc) else clean_pathway_definition(raw_original_desc)
            intersection_genes = (
                [str(gene).strip() for gene in row.get('intersections', []) if str(gene).strip()]
                if isinstance(row, dict) and isinstance(row.get('intersections'), list)
                else []
            )
            if not disease_connection:
                disease_connection = fallback_disease_interpretation(
                    row.get('name', 'Unknown') if isinstance(row, dict) else 'Unknown',
                    original_desc,
                    intersection_genes,
                    session.disease_name,
                    literature,
                )
            final_description = disease_connection
            
            pathways_list.append({
                "name": row.get('name', 'Unknown') if isinstance(row, dict) else 'Unknown',
                "pathway_id": get_pathway_identifier(row) if isinstance(row, dict) else '',
                "native": get_pathway_identifier(row) if isinstance(row, dict) else '',
                "p_value": float(p_val),
                "score": round(score, 1),
                "category": row.get('source', 'GO:BP') if isinstance(row, dict) else 'GO:BP',
                "genes": ','.join(intersection_genes) if intersection_genes else str(row.get('intersection_size', 0) if isinstance(row, dict) else 0),
                "intersection_genes": intersection_genes,
                "intersection_size": int(row.get('intersection_size', len(intersection_genes))) if isinstance(row, dict) else len(intersection_genes),
                "term_size": int(row.get('term_size', 0) or 0) if isinstance(row, dict) else 0,
                "query_size": int(row.get('query_size', len(session.genes))) if isinstance(row, dict) else len(session.genes),
                "pathway_description": original_desc,
                # Post-validation cell context wins over the one embedded in the
                # interpretation contract; the general fallback is used only when
                # no pathway-specific statement came back.
                "cell_context": (
                    validated_cell_context.get(row.get('name') if isinstance(row, dict) else '')
                    or validated_cell_context.get('__general__', '')
                ),
                "cell_context_provenance": (
                    {
                        'scope': 'pathway-level',
                        'source': 'FDR-supported pathway cell context',
                        'stage': 'post-validation',
                        'claim_citation_scope': 'pending',
                    }
                    if validated_cell_context.get(row.get('name') if isinstance(row, dict) else '')
                    else (
                        {
                            'scope': 'run-level',
                            'source': 'general context for the input genes',
                            'stage': 'post-validation',
                            'claim_citation_scope': 'pending',
                        }
                        if validated_cell_context.get('__general__') else None
                    )
                ),
                "disease_interpretation": disease_connection,
                "description": final_description,  # Use disease connection or original
                "gpt_rank": rank,
                "gpt_predicted": is_gpt_predicted,
                "literature": literature[:5] if isinstance(literature, list) else [],  # Pass full objects
                "pmids": pmid_list  # Also pass extracted PMIDs for easy access
            })
            rank += 1

        session.set_progress(
            76,
            'Linking supporting literature',
            'Connecting pathway-level cell context to supporting PubMed records.',
        )
        progress_callback = lambda text: add_analysis_progress_message(session, text)
        cell_context_module.attach_cell_context_evidence(
            pathways_list,
            session.disease_name,
            genes=session.genes,
            progress=progress_callback,
        )
        session.set_progress(
            88,
            'Writing pathway interpretations',
            f'Preparing concise and detailed interpretations for {len(pathways_list)} pathways.',
        )
        attach_pathway_narratives(
            pathways_list,
            session.disease_name,
            progress=progress_callback,
            model=session.model,
        )
        # This optional layer uses PubTator3 annotations for the PubMed records
        # already linked to each pathway.  It is attached after ranking and
        # narrative generation so it cannot affect either.
        external_evidence.attach_external_evidence_genes(
            pathways_list,
            input_genes=session.genes,
        )
        session.set_progress(
            94,
            'Preparing the result',
            f'Assembled {len(pathways_list)} validated pathways and their evidence records.',
        )

        validated_by_database = {cat: 0 for cat in categories_order}
        for pathway in pathways_list:
            category = pathway.get('category', 'Other')
            if category in validated_by_database:
                validated_by_database[category] += 1
        session.results['validation_comparison'] = {
            'initial_hypotheses': int(total_predicted),
            'matched_hypotheses': int(total_matched),
            'statistically_validated_hypotheses': int(total_validated),
            'matched_enrichment_records': int(total_matched_records),
            'statistically_validated_enrichment_records': int(total_validated_records),
            'statistically_validated': len(pathways_list),
            'rounds': [{
                'round': 1,
                'generated_hypotheses': int(total_predicted),
                'matched_hypotheses': int(total_matched),
                'statistically_validated_hypotheses': int(total_validated),
                'validation_rate': hypothesis_validation_rate(total_validated, total_matched),
                'matched_enrichment_records': int(total_matched_records),
                'statistically_validated_enrichment_records': int(total_validated_records),
            }],
            'by_database': {
                category: {
                    'initial_hypotheses': initial_hypotheses_by_database.get(category, 0),
                    **hypothesis_validation_by_database.get(category, {}),
                    'statistically_validated': validated_by_database.get(category, 0)
                }
                for category in categories_order
            }
        }
        
        # Generate category distribution summary
        cat_dist = {}
        for p in pathways_list:
            cat = p['category']
            cat_dist[cat] = cat_dist.get(cat, 0) + 1
        
        dist_str = ", ".join([f"{cat}: {count}" for cat, count in sorted(cat_dist.items())])
        
        session.add_message("system", 
            f"✅ Analysis complete: {len(pathways_list)} pathways | {dist_str}")
        return pathways_list
        
    except Exception as e:
        print(f"❌ Real analysis failed: {e}")
        import traceback
        traceback.print_exc()
        session.add_message("system", f"⚠️ Analysis error: {str(e)[:100]}. Using demo data.")
        return generate_mock_pathways(session.disease)


def gpt_predict_pathways(genes: list, disease_name: str, disease_description: str, iteration: int = 1, model=None) -> tuple:
    """
    GPT-5 predicts 50 pathways (5 categories × 10) as hypothesis.
    NOW GENERATES PER-CATEGORY REASONING for each category.

    Returns:
        tuple: (all_pathways, pathway_details, reasoning_by_category)
        - reasoning_by_category: dict mapping category_code -> reasoning_dict
    """
    import openai
    import json
    import re
    import sys

    all_pathways = []
    pathway_details = {}
    reasoning_by_category = {}  # NEW: Store reasoning for each category

    # 5 categories, 10 each
    categories = [
        ('GO:BP', 'Biological Process'),
        ('GO:MF', 'Molecular Function'),
        ('GO:CC', 'Cellular Component'),
        ('KEGG', 'KEGG Pathway'),
        ('REAC', 'Reactome Pathway')
    ]
    
    # Detailed System Prompts (derived from pathway_prompt_templates.py)
    SYSTEM_PROMPTS = {
        'GO:BP': """You are an expert in interpreting disease-related biological processes using Gene Ontology Biological Process (GO:BP) terms.
Your role is to identify GO:BP terms that plausibly connect the input gene list to the specified disease context.
Constraints:
1. Use OFFICIAL GO:BP term names (e.g., "response to oxidative stress").
2. Do NOT fabricate IDs. If you provide an ID (GO:#######), ensure it is correct.
3. Select terms that accurately reflect the granularity of the input module.
4. Do NOT use generic terms like "Biological process" or "Cellular process" unless the module is extremely broad.
5. Prioritize specific terms (e.g., "Interleukin-23-mediated signaling") if supported by the genes.""",

        'GO:MF': """You are an expert in discovering disease-related molecular functions (GO:MF).
Your role is to identify molecular functions that explain HOW gene products contribute to disease mechanisms.
Constraints:
1. Use OFFICIAL GO:MF term names.
2. Distinguish between Activity (e.g., Kinase activity) and Binding (e.g., ATP binding).
3. Select terms that describe the dominant biochemical function of the key drivers.""",

        'GO:CC': """You are an expert in discovering disease-related cellular components (GO:CC).
Your role is to identify cellular locations or complexes relevant to the disease.
Constraints:
1. Use OFFICIAL GO:CC term names.
2. Focus on where the core interaction of the module occurs.""",

        'KEGG': """You are an expert in KEGG pathways.
Your role is to identify KEGG pathways that connect the input genes to the disease.
Constraints:
1. Use OFFICIAL KEGG pathway names (e.g., "mTOR signaling pathway").
2. Do NOT use abbreviated names or qualifiers not in the official name.
3. Ensure the pathway is biologically supported by the input genes.""",

        'REAC': """You are an expert in Reactome pathways.
Your role is to identify Reactome pathways that represent the biological consensus of the module.
Constraints:
1. Use OFFICIAL Reactome pathway names.
2. Avoid broad top-level terms (e.g., "Signal Transduction") if a specific sub-pathway applies.
3. Use exact capitalization and spelling."""
    }

    print(f"  🧠 GPT predicting pathways for {disease_name}...")
    sys.stdout.flush()
    
    for category_code, category_name in categories:
        print(f"     [{category_code}] Generating...", flush=True)
        
        system_prompt = SYSTEM_PROMPTS.get(category_code, f"You are an expert in {disease_name} and {category_name} pathways.")
        
        prompt = f"""TASK: Analyze the provided gene list as a functional module for {disease_name}.
Identify the top 10 {category_name} terms/pathways that best describe this module.

INPUT GENES: {', '.join(genes)}
DISEASE: {disease_name}
CONTEXT: {disease_description[:300] if disease_description else 'Not available'}

REQUIREMENTS:
1. Provide EXACTLY 10 terms/pathways.
2. Use EXACT OFFICIAL database names. This is CRITICAL for matching.
   - GO:BP example: "response to oxidative stress" (NOT "oxidative stress response")
   - KEGG example: "mTOR signaling pathway" (NOT "mTOR pathway")
3. Provide the official ID if possible (e.g., "GO:0006979", "KEGG:hsa04064").
4. Avoid extremely generic terms (e.g., "Signaling", "Disease", "Metabolic process") unless absolutely necessary.

RETURN FORMAT (JSON):
{{
  "pathways": [
    {{
      "name": "Official Name 1",
      "id": "ID1",
      "rationale": "Why this pathway..."
    }},
    ...
  ]
}}"""

        try:
            client = openai.OpenAI(api_key=OPENAI_API_KEY)
            response = client.chat.completions.create(
                model=model or GPT_MODEL,
                messages=[
                    {"role": "system", "content": system_prompt + " Always respond with valid JSON."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0,
                max_completion_tokens=2000
            )
            
            response_text = response.choices[0].message.content
            print(f"     [{category_code}] Got response: {len(response_text)} chars", flush=True)
            
            # Try to parse JSON
            # Handle markdown code blocks if present
            if "```json" in response_text:
                json_start = response_text.find("```json") + 7
                json_end = response_text.find("```", json_start)
                response_text = response_text[json_start:json_end].strip()
            elif "```" in response_text:
                json_start = response_text.find("```") + 3
                json_end = response_text.find("```", json_start)
                response_text = response_text[json_start:json_end].strip()
            
            try:
                parsed = json.loads(response_text)
            except json.JSONDecodeError:
                # Try to find JSON object in response
                json_match = re.search(r'\{.*"pathways".*\}', response_text, re.DOTALL)
                if json_match:
                    parsed = json.loads(json_match.group())
                else:
                    print(f"     [{category_code}] ⚠️ Could not parse JSON", flush=True)
                    continue
            
            for pw in parsed.get('pathways', []):
                name = pw.get('name', '') if isinstance(pw, dict) else str(pw)
                pw_id = pw.get('id', '') if isinstance(pw, dict) else ''
                
                if name and name not in all_pathways:
                    all_pathways.append(name)
                    pathway_details[name] = {
                        'name': name,
                        'id': pw_id,
                        'source': category_code,
                        'rationale': pw.get('rationale', '') if isinstance(pw, dict) else ''
                    }
            
            cat_count = len([p for p in all_pathways if pathway_details.get(p, {}).get('source') == category_code])
            print(f"     [{category_code}] ✅ {cat_count} pathways", flush=True)

            # ============================================================
            # Generate Category-Specific Reasoning (Iteration 1)
            # ============================================================
            try:
                genes_str = ', '.join(genes[:30]) + ("..." if len(genes) > 30 else "")
                reasoning_prompt = f"""Provide detailed reasoning for your pathway predictions in the {category_name} ({category_code}) category.

CONTEXT:
- Disease: {disease_name}
- Input Genes ({len(genes)} total): {genes_str}
- Category: {category_code} - {category_name}
- Pathways Predicted: {cat_count}

Your response must explain HOW you analyzed the genes and WHY you predicted specific pathways.
Write for a research user who needs an actionable and auditable explanation.

Respond using markdown ## headers for EACH section below. Include ALL sections even if N/A for this iteration.

## Overall Strategy
[3-4 sentences explaining your analytical approach. How did you map genes to {category_code} terms? What biological principles guided your predictions? Be specific about methodology, not generic statements.]

## Gene Analysis
[3-4 sentences. Inspect the gene list and describe the dominant functional themes you observe. Group genes by function (e.g., synaptic, immune, metabolic). What kind of network module does this gene set represent?]

## Database Focus
[2-3 sentences. Why is {category_code} appropriate for interpreting this gene module? What resolution or annotation level does it provide? How does it complement other categories?]

## Key Gene Functions
[3-4 sentences. Identify specific genes and their known annotations relevant to {category_code}. Reference gene families, protein complexes, or functional groups. Be concrete about which genes drive which predictions.]

## Pathway Selection Rationale
[3-4 sentences. Based on the gene functions identified above, explain which {category_code} terms you selected and why. What mechanistic bridge connects gene function to predicted pathways? How do predicted terms relate to each other thematically?]

## Biological Evidence
[2-3 sentences. What experimental or literature evidence supports these pathway predictions in the context of {disease_name}? Reference known disease mechanisms, omics findings, or model organism studies.]

## Learned from Previous Iteration
N/A (First iteration or no feedback)

## Pathway Guidance
N/A

## Category-Specific Adjustments
N/A

## Validation Reflection
N/A (Iteration 2+ only)

## Failure Analysis
N/A (Iteration 2+ only)

## Bottleneck Diagnosis
N/A (Iteration 2+ only)

## Cell Context
[2-3 sentences identifying the primary cell types, tissues, or anatomical structures where this module's genes are most active. Ground your pathway predictions to specific cellular contexts relevant to {disease_name}. For example, specify neuron subtypes for neurological diseases, or immune cell types for inflammatory diseases.]

## Relevance Strength with Disease
[High/Medium/Low] - [2-3 sentences assessing confidence. What mechanistic links connect your {category_code} predictions to {disease_name}? Consider biological plausibility and expected statistical validation.]

IMPORTANT: Provide DETAILED, SPECIFIC analysis. Reference actual biological mechanisms, gene functions, and disease pathways. Avoid generic statements like "analyzed genes" - explain HOW and WHY."""

                client_reasoning = openai.OpenAI(api_key=OPENAI_API_KEY)
                reasoning_response = client_reasoning.chat.completions.create(
                    model=model or GPT_MODEL,
                    messages=[
                        {"role": "system", "content": f"You are a bioinformatics expert explaining your reasoning for {category_name} pathway predictions. Write detailed, mechanistic explanations. Use ## markdown headers for each section."},
                        {"role": "user", "content": reasoning_prompt}
                    ],
                    temperature=0,
                    max_completion_tokens=16000
                )

                reasoning_text = reasoning_response.choices[0].message.content or ""
                category_reasoning = parse_reasoning_from_response(reasoning_text)

                if category_reasoning:
                    reasoning_by_category[category_code] = category_reasoning
                    print(f"     [{category_code}] 💭 Reasoning extracted", flush=True)
                else:
                    reasoning_by_category[category_code] = {
                        'overall_strategy': f"Generated {cat_count} {category_name} predictions for {disease_name}",
                        'relevance_strength_with_disease': 'Medium'
                    }
                    print(f"     [{category_code}] ⚠️ Using fallback reasoning", flush=True)

            except Exception as e:
                print(f"     [{category_code}] ⚠️ Reasoning error: {str(e)[:50]}", flush=True)
                reasoning_by_category[category_code] = {
                    'overall_strategy': f"Generated {cat_count} {category_name} predictions",
                    'relevance_strength_with_disease': 'Unknown'
                }

        except Exception as e:
            print(f"     [{category_code}] ❌ Error: {str(e)}", flush=True)
            import traceback
            traceback.print_exc()
            continue

    print(f"  ✅ GPT prediction complete: {len(all_pathways)} pathways", flush=True)
    print(f"  💭 Generated reasoning for {len(reasoning_by_category)} categories", flush=True)

    return all_pathways, pathway_details, reasoning_by_category


def gpt_predict_pathways_with_context(genes: list, disease_name: str, disease_description: str, retained_pathways: list, iteration: int = 2, model=None) -> tuple:
    """
    GPT-5 predicts NEW pathways using retained pathways as context.
    Used in iterative refinement mode (iterations 2+).
    NOW GENERATES PER-CATEGORY REASONING with iteration-specific fields.

    Returns:
        tuple: (all_pathways, pathway_details, reasoning_by_category)
    """
    import openai
    import json
    import re

    print(f"  🧠 GPT predicting with context ({len(retained_pathways)} retained pathways)...", flush=True)

    all_pathways = []
    pathway_details = {}
    reasoning_by_category = {}  # NEW: Store reasoning for each category
    
    # Get pathway names from retained list
    retained_names = []
    for p in retained_pathways:
        if isinstance(p, dict):
            name = p.get('name', p.get('pathway_name', ''))
            if name:
                retained_names.append(name)
    
    # Build context from retained pathways (max 20 for prompt size)
    context_pathways = retained_names[:20]
    context_str = "\n".join([f"  - {name}" for name in context_pathways]) if context_pathways else "No retained pathways yet."
    
    categories = {
        'GO:BP': 'Gene Ontology Biological Processes',
        'GO:MF': 'Gene Ontology Molecular Functions', 
        'GO:CC': 'Gene Ontology Cellular Components',
        'KEGG': 'KEGG Pathways',
        'REAC': 'Reactome Pathways'
    }
    
    system_prompt = f"""You are an expert bioinformatician with deep knowledge of {disease_name} pathology.

Your task: Generate NEW pathway predictions that are DIFFERENT from the already validated pathways provided.

CONTEXT - Previously Validated Pathways (DO NOT REPEAT):
{context_str}

Strategy:
1. Analyze new biological themes not covered by retained pathways
2. Explore complementary mechanisms in {disease_name}
3. Predict pathways that work synergistically with validated ones
4. Focus on statistically likely pathways based on gene set

CRITICAL: Avoid predicting pathways that overlap significantly with the retained list."""
    
    for category_code, category_name in categories.items():
        prompt = f"""For the disease {disease_name} and input genes, predict 10 NEW {category_name} pathways.

Disease Description: {disease_description[:300] if disease_description else 'Not available'}

INPUT GENES: {', '.join(genes[:50])}{'...' if len(genes) > 50 else ''}

PREVIOUSLY VALIDATED (DO NOT REPEAT):
{context_str}

Return EXACTLY in this JSON format:
{{
  "pathways": [
    {{"name": "exact pathway name", "id": "GO:XXXXX or pathway ID"}},
    ...
  ]
}}"""

        try:
            client = openai.OpenAI(api_key=OPENAI_API_KEY)
            response = client.chat.completions.create(
                model=model or GPT_MODEL,
                messages=[
                    {"role": "system", "content": system_prompt + " Always respond with valid JSON."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.1,  # Slightly higher for diversity
                max_completion_tokens=2000
            )
            
            response_text = response.choices[0].message.content
            
            # Handle markdown code blocks
            if "```json" in response_text:
                json_start = response_text.find("```json") + 7
                json_end = response_text.find("```", json_start)
                response_text = response_text[json_start:json_end].strip()
            elif "```" in response_text:
                json_start = response_text.find("```") + 3
                json_end = response_text.find("```", json_start)
                response_text = response_text[json_start:json_end].strip()
            
            try:
                parsed = json.loads(response_text)
            except json.JSONDecodeError:
                json_match = re.search(r'\{.*"pathways".*\}', response_text, re.DOTALL)
                if json_match:
                    parsed = json.loads(json_match.group())
                else:
                    continue
            
            for pw in parsed.get('pathways', []):
                name = pw.get('name', '') if isinstance(pw, dict) else str(pw)
                pw_id = pw.get('id', '') if isinstance(pw, dict) else ''
                
                # Skip if in retained list (duplicate)
                name_lower = name.lower().strip()
                if any(name_lower == r.lower().strip() for r in retained_names):
                    continue
                
                if name and name not in all_pathways:
                    all_pathways.append(name)
                    pathway_details[name] = {
                        'name': name,
                        'id': pw_id,
                        'source': category_code,
                        'iteration_type': 'new_prediction'
                    }

            cat_count = len([p for p in all_pathways if pathway_details.get(p, {}).get('source') == category_code])
            print(f"     [{category_code}] ✅ {cat_count} NEW pathways", flush=True)

            # ============================================================
            # Generate Category-Specific Reasoning (Iteration 2+)
            # ============================================================
            # Get retained pathways for THIS category
            cat_retained = [p.get('name', '') for p in retained_pathways if p.get('source') == category_code]
            cat_retained_str = "\n".join([f"  - {name}" for name in cat_retained[:10]]) if cat_retained else "None"

            print(f"     [{category_code}] 📊 Retained from iter 1: {len(cat_retained)} pathways", flush=True)
            if not cat_retained and len(retained_pathways) > 0:
                # Debug: show what sources are in retained pathways
                sources_in_retained = set(p.get('source', 'NO_SOURCE') for p in retained_pathways)
                print(f"     [{category_code}] ⚠️ No retained for {category_code}, but have: {sources_in_retained}", flush=True)

            try:
                reasoning_prompt = f"""Provide detailed reasoning for iteration 2 pathway predictions in {category_name} ({category_code}).

CONTEXT:
- Disease: {disease_name}
- Iteration: 2 (building on iteration 1 validated results)
- Category: {category_code}
- Retained {category_code} pathways from iteration 1 ({len(cat_retained)}):
{cat_retained_str}
- NEW predictions generated: {cat_count}

Explain HOW iteration 1 results inform iteration 2 predictions. Reflect on what worked and what didn't.
Write for a research user who needs to understand why predictions succeeded or failed.

Respond using markdown ## headers for EACH section below. Include ALL sections with substantive content.

## Overall Strategy
[3-4 sentences. First explain how you interpret the gene set's functional signature from iteration 1 validated pathways. Then explain your approach for generating NEW predictions while avoiding duplicates. What biological themes are you building upon vs exploring anew?]

## Gene Analysis
[3-4 sentences. Re-examine the gene list in light of iteration 1 results. Which functional clusters were validated? Which were not supported? How does this refine your understanding of the module's dominant biology?]

## Database Focus
[2-3 sentences. Why is {category_code} appropriate for this module given iteration 1 results? What resolution level works best? How does the category complement other validated categories?]

## Key Gene Functions
[3-4 sentences. Which specific genes drove successful predictions in iteration 1? What additional gene functions should you leverage for iteration 2? Reference gene families, protein complexes, or functional groups.]

## Pathway Selection Rationale
[3-4 sentences. Based on the refined gene analysis and iteration 1 feedback, explain which NEW {category_code} terms you selected and why. What mechanistic bridge connects gene function to predicted pathways? How do new predictions relate thematically to retained ones?]

## Biological Evidence
[2-3 sentences. What experimental or literature evidence supports these NEW pathway predictions in the context of {disease_name}? Reference known disease mechanisms, omics findings, or model organism studies that distinguish iteration 2 predictions from iteration 1.]

## Learned from Previous Iteration
[3-4 sentences. The retained {category_code} terms reveal core biological themes that validated well. What patterns emerged? What does this tell you about the module's functions? How does this guide iteration 2?]

## Pathway Guidance
[3-4 sentences. How do retained {category_code} pathways inform NEW predictions? What related but distinct pathways should you explore? What mechanistic connections guide your focus?]

## Category-Specific Adjustments
[3-4 sentences. Specific adjustments for {category_code} in iteration 2. What types of terms will you favor or avoid based on iteration 1 performance? Why?]

## Validation Reflection
[2-3 sentences. What distinguishes validated from non-validated {category_code} pathways? What characteristics led to success/failure?]

## Failure Analysis
[2-3 sentences. Why did certain {category_code} predictions fail in iteration 1? Were they too generic, poorly gene-supported, or thematically misaligned? What specific examples demonstrate this?]

## Bottleneck Diagnosis
[2-3 sentences. Did {category_code} underperform relative to other categories in iteration 1? If so, diagnose why and explain your correction strategy.]

## Cell Context
[2-3 sentences identifying the primary cell types, tissues, or anatomical structures where this module's genes are most active. Ground your pathway predictions to specific cellular contexts relevant to {disease_name}. How does the cellular context inform your iteration 2 predictions?]

## Relevance Strength with Disease
[High/Medium/Low] - [2-3 sentences assessing how NEW {category_code} predictions relate to {disease_name} pathophysiology. What mechanistic connections support your confidence?]

IMPORTANT: Provide DETAILED, MECHANISTIC analysis. Reference actual retained pathways, biological themes, and disease mechanisms. Avoid generic statements."""

                client_reasoning = openai.OpenAI(api_key=OPENAI_API_KEY)
                reasoning_response = client_reasoning.chat.completions.create(
                    model=model or GPT_MODEL,
                    messages=[
                        {"role": "system", "content": f"You are a bioinformatics expert explaining detailed iterative reasoning for {category_name} pathway predictions. Reference specific biological mechanisms and actual pathways. Avoid generic statements. Use ## markdown headers for each section."},
                        {"role": "user", "content": reasoning_prompt}
                    ],
                    temperature=0,
                    max_completion_tokens=16000
                )

                finish_reason = reasoning_response.choices[0].finish_reason
                reasoning_text = reasoning_response.choices[0].message.content or ""
                print(f"     [{category_code}] 📄 GPT finish_reason: {finish_reason}, response length: {len(reasoning_text)} chars", flush=True)
                if reasoning_text:
                    print(f"     [{category_code}] 📄 GPT response preview: {reasoning_text[:300]}...", flush=True)

                if not reasoning_text.strip():
                    print(f"     [{category_code}] ⚠️ GPT returned empty response, using fallback", flush=True)
                    reasoning_by_category[category_code] = {
                        'overall_strategy': f"Generated {cat_count} NEW {category_name} predictions based on {len(cat_retained)} retained pathways",
                        'learned_from_previous_iteration': f"Retained pathways ({', '.join(cat_retained[:3])}) indicate core biological themes",
                        'pathway_guidance': f"Built on validated {category_code} themes to explore related mechanisms",
                        'category_specific_adjustments': f'Focused on pathways mechanistically linked to retained terms',
                        'relevance_strength_with_disease': 'Medium - predictions built on validated iteration 1 patterns'
                    }
                else:
                    category_reasoning = parse_reasoning_from_response(reasoning_text)

                    if category_reasoning:
                        reasoning_by_category[category_code] = category_reasoning
                        print(f"     [{category_code}] 💭 Iter 2 reasoning extracted", flush=True)
                        parsed_count = sum(1 for v in category_reasoning.values() if v != "Not provided")
                        print(f"     [{category_code}] ✓ Parsed {parsed_count}/8 fields successfully", flush=True)
                    else:
                        print(f"     [{category_code}] ❌ Parser returned None!", flush=True)
                        print(f"     [{category_code}] Full response:\n{reasoning_text[:500]}", flush=True)
                        reasoning_by_category[category_code] = {
                            'overall_strategy': f"Generated {cat_count} NEW {category_name} predictions based on {len(cat_retained)} retained pathways",
                            'learned_from_previous_iteration': f"Retained pathways ({', '.join(cat_retained[:3])}) indicate core biological themes",
                            'pathway_guidance': f"Built on validated {category_code} themes to explore related mechanisms",
                            'category_specific_adjustments': f'Focused on pathways mechanistically linked to retained terms',
                            'relevance_strength_with_disease': 'Medium - predictions built on validated iteration 1 patterns'
                        }
                        print(f"     [{category_code}] ⚠️ Using fallback reasoning", flush=True)

            except Exception as e:
                print(f"     [{category_code}] ⚠️ Reasoning error: {str(e)[:50]}", flush=True)
                reasoning_by_category[category_code] = {
                    'overall_strategy': f"Generated {cat_count} NEW {category_name} predictions",
                    'learned_from_previous_iteration': 'Error during reasoning generation',
                    'relevance_strength_with_disease': 'Unknown'
                }

        except Exception as e:
            print(f"     [{category_code}] ❌ Error: {str(e)[:50]}", flush=True)
            continue

    print(f"  ✅ GPT context prediction complete: {len(all_pathways)} NEW pathways", flush=True)
    print(f"  💭 Generated reasoning for {len(reasoning_by_category)} categories", flush=True)

    return all_pathways, pathway_details, reasoning_by_category

def match_gpt_with_gprofiler(gpt_predictions: list, gprofiler_results: pd.DataFrame) -> pd.DataFrame:
    """
    Match GPT predictions with g:Profiler enrichment results.
    Uses fuzzy name matching and ID matching.
    """
    if not gpt_predictions or gprofiler_results.empty:
        return gprofiler_results.head(30) if not gprofiler_results.empty else pd.DataFrame()
    
    matched_rows = []
    gpt_predictions_lower = [p.lower().strip() for p in gpt_predictions]
    
    for idx, row in gprofiler_results.iterrows():
        gprofiler_name = str(row.get('name', '')).lower().strip()
        gprofiler_id = str(row.get('native', '')).lower().strip()
        
        is_match = False
        for gpt_pred in gpt_predictions_lower:
            # Exact match or substring match
            if (gpt_pred == gprofiler_name or 
                gpt_pred in gprofiler_name or 
                gprofiler_name in gpt_pred or
                gpt_pred in gprofiler_id):
                is_match = True
                break
        
        row_copy = row.copy()
        row_copy['gpt_validated'] = is_match
        
        if is_match:
            matched_rows.append(row_copy)
    
    if matched_rows:
        matched_df = pd.DataFrame(matched_rows)
        # Sort by p-value
        matched_df = matched_df.sort_values('p_value')
        return matched_df
    else:
        # No matches - return top g:Profiler results
        return gprofiler_results.sort_values('p_value').head(30)


def matches_gpt_prediction_enhanced(gpt_pred_name, gpt_pred_id, gprofiler_name, gprofiler_id):
    """
    Enhanced matching logic:
    1. ID Exact Match (if available)
    2. Name Exact Match (case-insensitive)
    3. Name Fuzzy Match (substring + length ratio <= 1.3)
    """
    gpt_name_norm = str(gpt_pred_name).lower().strip()
    gp_name_norm = str(gprofiler_name).lower().strip()
    
    # 1. ID Exact Match
    if gpt_pred_id and gprofiler_id:
        gpt_id_norm = str(gpt_pred_id).upper().strip()
        gp_id_norm = str(gprofiler_id).upper().strip()
        if gpt_id_norm == gp_id_norm:
            # print(f"DEBUG: ID Match: {gpt_pred_id} == {gprofiler_id}")
            return True
            
    # 2. Name Exact Match
    if gpt_name_norm == gp_name_norm:
        # print(f"DEBUG: Exact Name Match: {gpt_name_norm}")
        return True
        
    # 3. Name Fuzzy Match
    # Check if one is substring of another
    if gpt_name_norm in gp_name_norm or gp_name_norm in gpt_name_norm:
        # Length ratio check to avoid over-matching (e.g. "binding" matching "protein binding")
        len_gpt = len(gpt_name_norm)
        len_gp = len(gp_name_norm)
        
        if len_gpt > 0 and len_gp > 0:
            ratio = max(len_gpt, len_gp) / min(len_gpt, len_gp)
            if ratio <= 1.3:
                # print(f"DEBUG: Fuzzy Match: '{gpt_name_norm}' vs '{gp_name_norm}' (Ratio: {ratio:.2f})")
                return True
            # else:
            #     print(f"DEBUG: Fuzzy Fail: '{gpt_name_norm}' vs '{gp_name_norm}' (Ratio: {ratio:.2f} > 1.3)")
                
    return False


def hypothesis_validation_rate(validated_hypotheses: int, matched_hypotheses: int) -> float:
    """Return validated/matched as a percentage using unique hypotheses."""
    validated = max(int(validated_hypotheses or 0), 0)
    matched = max(int(matched_hypotheses or 0), 0)
    if matched == 0:
        return 0.0
    if validated > matched:
        raise ValueError("validated hypotheses cannot exceed matched hypotheses")
    return validated / matched * 100.0


def match_gpt_with_gprofiler_detailed(gpt_predictions: list, pathway_details: dict, 
                                       gprofiler_results: pd.DataFrame,
                                       retained_pathway_names: set = None) -> tuple:
    """
    Match GPT predictions with g:Profiler results using ENHANCED logic.

    A hypothesis may map to more than one enrichment record.  The returned
    DataFrame intentionally preserves all of those records for downstream
    ranking, while validation statistics count each GPT hypothesis at most
    once.  This keeps hypothesis-level rates bounded by 100% without throwing
    away biologically useful child/parent term matches.

    Matching is source-aware: a GO:BP hypothesis can only be validated by a
    GO:BP record, a KEGG hypothesis by KEGG, and so on.
    
    Args:
        retained_pathway_names: Set of pathway names that were retained from previous iteration.
                               Used to separate new matches from retained matches.
    
    Returns:
        tuple: (matched_df, category_stats)
    """
    categories = ['GO:BP', 'GO:MF', 'GO:CC', 'KEGG', 'REAC']
    
    # Default to empty set if not provided
    if retained_pathway_names is None:
        retained_pathway_names = set()
    
    # Initialize category statistics
    category_stats = {cat: {
        'predicted': 0,          # GPT hypotheses generated in this pass
        'matched': 0,            # Unique hypotheses with >=1 term match
        'fdr_filtered': 0,       # Unique hypotheses with >=1 adjusted-P < 0.05 match
        'new_matched': 0,        # Unique matched hypotheses not retained from a prior pass
        'new_fdr': 0,            # Unique statistically validated new hypotheses
        'matched_records': 0,    # All matching g:Profiler records (may exceed hypotheses)
        'fdr_records': 0,        # Significant matching g:Profiler records
        'new_matched_records': 0,
        'new_fdr_records': 0,
    } for cat in categories}

    
    # Count GPT predictions per category
    for pw_name, details in pathway_details.items():
        source = details.get('source', '')
        if source in category_stats:
            category_stats[source]['predicted'] += 1
    
    if not gpt_predictions or gprofiler_results.empty:
        return gprofiler_results.iloc[0:0].copy(), category_stats
    
    # Preserve every matching enrichment record for ranking, while collecting
    # unique hypothesis identities separately for rate calculations.
    gpt_matched_rows = []
    matched_hypotheses = {cat: set() for cat in categories}
    fdr_hypotheses = {cat: set() for cat in categories}
    new_matched_hypotheses = {cat: set() for cat in categories}
    new_fdr_hypotheses = {cat: set() for cat in categories}
    
    # Prepare GPT predictions for fast matching
    # Build gpt_pathway_ids dictionary
    gpt_pathway_ids = {}
    gpt_preds_lookup = []
    
    for gpt_pred, details in pathway_details.items():
        gpt_id = details.get('id', '')
        source = details.get('source', '')
        gpt_pathway_ids[gpt_pred] = gpt_id
        
        # Check if this prediction is NEW or RETAINED
        is_new_pred = gpt_pred not in retained_pathway_names
        
        normalized_name = re.sub(r'[^a-z0-9]+', ' ', gpt_pred.lower()).strip()
        hypothesis_key = (
            f"{source}|id:{str(gpt_id).strip().upper()}"
            if str(gpt_id).strip()
            else f"{source}|name:{normalized_name}"
        )

        gpt_preds_lookup.append({
            'name': gpt_pred,
            'id': gpt_id,
            'source': source,
            'is_new': is_new_pred,
            'key': hypothesis_key,
        })
            
    # 2. Find ALL matching g:Profiler pathways
    for idx, row in gprofiler_results.iterrows():
        gprofiler_name = str(row.get('name', ''))
        gprofiler_id = str(row.get('native', ''))
        gprofiler_source = row.get('source', '')
        
        # Skip if source not tracked
        if gprofiler_source not in category_stats:
            continue
        
        matched_items = []
        
        # Check against all GPT predictions
        for gpt_item in gpt_preds_lookup:
            if gpt_item['source'] != gprofiler_source:
                continue
            if matches_gpt_prediction_enhanced(
                gpt_item['name'], 
                gpt_item['id'], 
                gprofiler_name, 
                gprofiler_id
            ):
                matched_items.append(gpt_item)
        
        if matched_items:
            # Add to matched rows
            row_copy = row.copy()
            row_copy['gpt_validated'] = True
            row_copy['gpt_pred_match'] = matched_items[0]['name']
            row_copy['gpt_pred_matches'] = [item['name'] for item in matched_items]
            row_copy['is_new_prediction'] = any(item['is_new'] for item in matched_items)
            gpt_matched_rows.append(row_copy)

            stats = category_stats[gprofiler_source]
            stats['matched_records'] += 1
            matched_hypotheses[gprofiler_source].update(
                item['key'] for item in matched_items
            )

            new_items = [item for item in matched_items if item['is_new']]
            if new_items:
                stats['new_matched_records'] += 1
                new_matched_hypotheses[gprofiler_source].update(
                    item['key'] for item in new_items
                )

            if row.get('p_value', 1.0) < 0.05:
                stats['fdr_records'] += 1
                fdr_hypotheses[gprofiler_source].update(
                    item['key'] for item in matched_items
                )
                if new_items:
                    stats['new_fdr_records'] += 1
                    new_fdr_hypotheses[gprofiler_source].update(
                        item['key'] for item in new_items
                    )

    for category in categories:
        stats = category_stats[category]
        stats['matched'] = len(matched_hypotheses[category])
        stats['fdr_filtered'] = len(fdr_hypotheses[category])
        stats['new_matched'] = len(new_matched_hypotheses[category])
        stats['new_fdr'] = len(new_fdr_hypotheses[category])

    
    # Create matched DataFrame
    if gpt_matched_rows:
        matched_df = pd.DataFrame(gpt_matched_rows)
        matched_df = matched_df.sort_values('p_value')
        return matched_df, category_stats
    else:
        # No hypothesis match: keep the matching result empty.  The caller may
        # explicitly choose a statistically enriched fallback for the final
        # evidence view, but it must not be counted as hypothesis validation.
        empty_df = gprofiler_results.iloc[0:0].copy()
        empty_df['gpt_validated'] = pd.Series(dtype=bool)
        return empty_df, category_stats


def gpt_rank_pathways_direct(enrichment_df, disease_name, disease_description, top_n=30, model=None):
    """
    FULL VERSION: GPT-5 pathway ranking with PubMed literature search.
    
    *** PER-CATEGORY RANKING (aligned with reference script) ***
    
    5 Evidence Sources:
    1. Pathway Description (biological function)
    2. Disease Description (pathology)
    3. Gene-list–pathway Intersection Genes
    4. FDR-adjusted P-Value (enrichment strength)
    5. PubMed Literature (dynamic search results)
    
    Key Feature: Rankings are computed WITHIN each category (GO:BP, GO:MF, GO:CC, KEGG, REAC)
    to ensure balanced representation across all pathway sources.
    """
    import openai
    import math
    import json
    import re
    import numpy as np
    
    if enrichment_df.empty:
        return enrichment_df
    
    # Categories to rank independently
    categories = ['GO:BP', 'GO:MF', 'GO:CC', 'KEGG', 'REAC']
    
    # Take top pathways by p-value for ranking
    df = enrichment_df.sort_values('p_value').head(min(top_n * 2, len(enrichment_df))).copy()
    
    # Add internal IDs for GPT tracking
    df['gpt_internal_id'] = [f"PW_{i:04d}" for i in range(len(df))]
    
    # Initialize columns
    df['related_literature'] = [[] for _ in range(len(df))]
    df['gpt_rank'] = 999  # Default high rank
    
    print(f"  🤖 GPT Per-Category Ranking (5 Evidence Sources): {len(df)} pathways...")
    print(f"     Disease: {disease_name}")
    print(f"     Description: {disease_description[:100]}...")
    
    # ================================================================
    # STEP 1: PubMed Literature Search for each pathway
    # ================================================================
    print(f"  📚 Searching PubMed for {len(df)} pathways...")
    
    for idx, (row_idx, row) in enumerate(df.iterrows()):
        pathway_name = row['name']
        print(f"     [{idx+1}/{len(df)}] {pathway_name[:40]}...", end="\r")
        
        # Search PubMed
        pubmed_text, pubmed_results = search_pubmed_for_pathway_standalone(
            pathway_name, disease_name, max_results=20
        )
        
        # Store top 5 papers
        if pubmed_results:
            top_papers = pubmed_results[:5]
            df.at[row_idx, 'related_literature'] = top_papers
    
    print(f"  ✅ PubMed search complete for {len(df)} pathways                    ")
    
    # ================================================================
    # STEP 2: Per-Category GPT Ranking
    # ================================================================
    print(f"  🔀 Per-Category Ranking (ranking within each category separately)")
    
    all_ranked_pathways = []
    
    for category in categories:
        # Filter pathways for this category
        cat_df = df[df['source'] == category].copy()
        
        if len(cat_df) == 0:
            print(f"     {category}: No pathways, skipping")
            continue
        
        print(f"\n  📋 Category: {category} ({len(cat_df)} pathways)")
        
        # Build rich context for each pathway in this category
        pathways_text = []
        for idx, (_, row) in enumerate(cat_df.iterrows(), 1):
            pw_desc = row.get('description', 'N/A')[:200]
            p_val = row.get('p_value', 1.0)
            intersection_genes = row.get('intersections', [])
            if not isinstance(intersection_genes, list):
                intersection_genes = []
            intersection_summary = ', '.join(str(gene) for gene in intersection_genes[:20])
            if len(intersection_genes) > 20:
                intersection_summary += f", and {len(intersection_genes) - 20} additional genes"
            
            # Significance level
            if p_val < 1e-10:
                sig_level = "extremely significant"
            elif p_val < 1e-5:
                sig_level = "highly significant"
            elif p_val < 0.01:
                sig_level = "significant"
            else:
                sig_level = "marginally significant"
            
            # PubMed summary
            lit = row.get('related_literature', [])
            if lit:
                lit_summary = f"{len(lit)} papers found. Top: {lit[0].get('title', 'N/A')[:50]}..."
            else:
                lit_summary = "No papers found"
            
            pathway_info = f"""
PATHWAY {row['gpt_internal_id']}:
- Name: {row['name']}
- Description: {pw_desc}
- Intersection genes: {intersection_summary or 'No structured intersection retained'}
- FDR-adjusted P-value: {p_val:.2e} ({sig_level})
- PubMed Evidence: {lit_summary}
"""
            pathways_text.append(pathway_info)
        
        # System prompt for this category
        system_prompt = f"""You are an expert in {disease_name} pathology and biological pathway analysis.

Your task is to rank {category} pathways by synthesizing 5 information sources:
1. PATHWAY DESCRIPTION: Biological function and mechanisms
2. DISEASE PATHOLOGY: Known characteristics of {disease_name}
3. INTERSECTION GENES: Input genes contributing to the pathway enrichment
4. ENRICHMENT STRENGTH: FDR-adjusted P-value from enrichment analysis
5. PUBMED LITERATURE: Scientific papers linking pathway to disease

IMPORTANT: You are ranking pathways ONLY WITHIN {category} category. Do not compare with other categories.

Rank 1 = BEST COMPREHENSIVE SCORE for {category} (strongest synthesis across all 5 evidence dimensions)
"""
        
        user_prompt = f"""Rank these {len(cat_df)} {category} pathways by COMPREHENSIVE SCORE for {disease_name}.

Disease Context: {disease_description[:400] if disease_description else 'Not available'}

PATHWAYS in {category}:
{"".join(pathways_text)}

Return ONLY a JSON array of pathway IDs (best comprehensive score first within {category}):
["PW_0001", "PW_0002", ...]
"""
        
        try:
            client = openai.OpenAI(api_key=OPENAI_API_KEY)
            response = client.chat.completions.create(
                model=model or GPT_MODEL,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0,
                max_completion_tokens=1000
            )
            
            # Parse ranking
            ranking_text = response.choices[0].message.content
            json_match = re.search(r'\[.*?\]', ranking_text, re.DOTALL)
            
            if json_match:
                ranked_ids = json.loads(json_match.group())
                
                # Create rank mapping WITHIN CATEGORY
                rank_map = {pw_id: rank+1 for rank, pw_id in enumerate(ranked_ids)}
                
                # Apply ranks to this category's pathways in the main df
                for pw_id, rank in rank_map.items():
                    mask = df['gpt_internal_id'] == pw_id
                    if mask.any():
                        df.loc[mask, 'gpt_rank'] = rank
                
                print(f"     ✅ Ranked {len(ranked_ids)} pathways in {category}")
            else:
                print(f"     ⚠️ Could not parse GPT response for {category}, using p-value order")
                # Fallback: rank by p-value within category
                cat_indices = cat_df.index.tolist()
                for rank, idx in enumerate(cat_indices, 1):
                    df.loc[idx, 'gpt_rank'] = rank
                    
        except Exception as e:
            print(f"     ❌ GPT ranking failed for {category}: {str(e)[:50]}")
            # Fallback: rank by p-value within category
            cat_indices = cat_df.index.tolist()
            for rank, idx in enumerate(cat_indices, 1):
                df.loc[idx, 'gpt_rank'] = rank
    
    # Sort by GPT rank (within category, so mixed order across categories)
    df = df.sort_values(['source', 'gpt_rank'])
    
    # Drop internal ID column
    df = df.drop(columns=['gpt_internal_id'])
    
    # Report category distribution
    cat_counts = df['source'].value_counts()
    print(f"\n  📊 Category distribution: {', '.join([f'{cat}={cat_counts.get(cat, 0)}' for cat in categories if cat_counts.get(cat, 0) > 0])}")
    
    # Report literature coverage
    lit_count = df['related_literature'].apply(lambda x: len(x) if isinstance(x, list) else 0).sum()
    print(f"  📚 Total literature references: {lit_count}")
    print(f"  ✅ Per-Category GPT Ranking complete: {len(df)} pathways ranked")
    

    # ================================================================
    # STEP 3: Generate Disease Connection Explanations
    # ================================================================
    print(f"  📝 Generating disease connection explanations...")
    
    # Initialize disease_connection column
    df['disease_connection'] = ''
    
    # Generate in batches of 5 pathways to save API calls
    batch_size = 5
    sorted_df = df.sort_values('gpt_rank').head(20)  # Top 20 pathways
    
    for batch_start in range(0, len(sorted_df), batch_size):
        batch_end = min(batch_start + batch_size, len(sorted_df))
        batch_indices = sorted_df.index[batch_start:batch_end].tolist()
        
        # Build batch prompt
        batch_pathways = []
        for idx in batch_indices:
            row = df.loc[idx]
            pw_name = row.get('name', 'Unknown')
            pw_desc = row.get('description', 'N/A')[:150]
            p_val = row.get('p_value', 1.0)
            genes = row.get('intersections', [])[:5] if isinstance(row.get('intersections'), list) else []
            genes_str = ', '.join(genes) if genes else 'key genes'
            
            # Get literature titles
            lit = row.get('related_literature', [])
            lit_refs = []
            lit_titles = []
            for paper in lit[:3]:
                if isinstance(paper, dict):
                    pmid = paper.get('pmid', '')
                    title = str(paper.get('title', '')).strip()
                    if pmid:
                        lit_refs.append(f"[PMID:{pmid}]")
                    if title:
                        lit_titles.append(title[:180])
            
            batch_pathways.append({
                'idx': idx,
                'name': pw_name,
                'desc': pw_desc,
                'p_val': p_val,
                'genes': genes_str,
                'pmids': lit_refs,
                'literature_titles': lit_titles,
            })
        
        # Create prompt for batch
        pathways_info = "\n".join([
            (
                f"{i+1}. {p['name']}\n"
                f"   Official definition: {p['desc']}\n"
                f"   Input-pathway intersection genes: {p['genes']}\n"
                f"   Attached literature titles: {' | '.join(p['literature_titles']) or 'None attached'}"
            )
            for i, p in enumerate(batch_pathways)
        ])
        
        try:
            client = openai.OpenAI(api_key=OPENAI_API_KEY)
            
            batch_prompt = f"""For each pathway below, write a concise biological interpretation for {disease_name}.

REQUIREMENTS:
1. Return exactly four labeled statements: Disease pathology and relevance, Intersection-gene interpretation, PubMed literature synthesis, and Cell/tissue context. The official pathway description and FDR-adjusted enrichment result are displayed directly from their source records.
2. Use only the supplied official definition, intersection genes and literature titles. Never introduce a gene that is not in the intersection.
3. Explain biological mechanism or functional context; do not restate the enrichment P-value or gene count because those are displayed separately.
4. Distinguish direct pathway biology from a plausible disease connection. For Cell/tissue context, name only cells, tissues or anatomical regions directly supported by the pathway biology, intersection genes or attached literature. If the supplied evidence does not resolve this context, write "Not resolved from the supplied pathway-level evidence."
5. If the term is broad (for example, protein binding), explicitly state that limitation instead of forcing a specific mechanism.
6. Write 1-2 clear sentences per labeled statement, suitable for a scientific results page.

PATHWAYS:
{pathways_info}

Return a JSON object with pathway names as keys and explanations as values:
{{
    "pathway_name_1": "Disease pathology and relevance: ...\nIntersection-gene interpretation: ...\nPubMed literature synthesis: ...\nCell/tissue context: ...",
    "pathway_name_2": "Disease pathology and relevance: ...\nIntersection-gene interpretation: ...\nPubMed literature synthesis: ...\nCell/tissue context: ...",
    ...
}}"""
            
            response = client.chat.completions.create(
                model=model or GPT_MODEL,
                messages=[
                    {"role": "system", "content": f"You are an expert in {disease_name} pathology. Provide mechanistic explanations linking pathways to disease."},
                    {"role": "user", "content": batch_prompt}
                ],
                temperature=0,
                max_completion_tokens=2000
            )
            
            response_text = response.choices[0].message.content
            
            # Parse JSON response
            # Handle markdown code blocks
            if "```json" in response_text:
                json_start = response_text.find("```json") + 7
                json_end = response_text.find("```", json_start)
                response_text = response_text[json_start:json_end].strip()
            elif "```" in response_text:
                json_start = response_text.find("```") + 3
                json_end = response_text.find("```", json_start)
                response_text = response_text[json_start:json_end].strip()
            
            try:
                connections = json.loads(response_text)
                
                # Match responses to pathways
                for pw in batch_pathways:
                    pw_name = pw['name']
                    # Try exact match first, then partial match
                    explanation = connections.get(pw_name, '')
                    if not explanation:
                        # Try partial match
                        for key, val in connections.items():
                            if key.lower() in pw_name.lower() or pw_name.lower() in key.lower():
                                explanation = val
                                break
                    
                    if explanation:
                        # Add PMID references if available
                        pmid_refs = ' '.join(pw['pmids']) if pw['pmids'] else ''
                        if pmid_refs and pmid_refs not in explanation:
                            explanation = f"{explanation} {pmid_refs}"
                        df.at[pw['idx'], 'disease_connection'] = explanation
                        
            except json.JSONDecodeError:
                print(f"    ⚠️ Could not parse batch {batch_start//batch_size + 1} response")
                
        except Exception as e:
            print(f"    ⚠️ Batch {batch_start//batch_size + 1} error: {str(e)[:50]}")
    
    # Count successful generations
    success_count = (df['disease_connection'] != '').sum()
    print(f"  ✅ Generated {success_count} disease connection explanations")
    
    return df


# Retrieval lives in pubmed_search.py so the offline archive builder attaches
# literature through exactly the same query path as a live run.
import pubmed_search
from pubmed_search import search_pubmed_for_pathway_standalone  # noqa: F401

pubmed_search.ENTREZ_EMAIL = ENTREZ_EMAIL
pubmed_search.ABBREVIATION_EXPANSION = ABBREVIATION_EXPANSION


def gpt_rank_pathways_simple(pathways_df, disease_name, disease_description, query_agent, framework, batch_size=20, top_n=200, model=None):
    """
    Simplified GPT ranking for web interface.
    Uses GPT-5 to rank pathways.
    """
    if pathways_df.empty:
        return pathways_df
    
    try:
        import openai
        
        # Prepare pathway info
        pathways_df = pathways_df.copy()
        pathways_df['gpt_rank'] = range(1, len(pathways_df) + 1)  # Default sequential ranking
        
        # Take top pathways for GPT ranking
        top_pathways = pathways_df.head(min(50, len(pathways_df)))
        
        # Format for GPT
        pathway_text = "\n".join([
            f"{i+1}. {row['name']} (p={row['p_value']:.2e}, source={row.get('source', 'unknown')}): {row.get('description', '')[:100]}"
            for i, (_, row) in enumerate(top_pathways.iterrows())
        ])
        
        prompt = f"""Rank these pathways by relevance to {disease_name}.
        
Disease: {disease_name}
Description: {disease_description[:500]}

Pathways:
{pathway_text}

Return ONLY a JSON array of pathway numbers in order from most to least relevant.
Example: [3, 1, 7, 2, ...]"""

        # Call GPT-5
        client = openai.OpenAI(api_key=OPENAI_API_KEY)
        response = client.chat.completions.create(
            model=model or GPT_MODEL,
            messages=[
                {"role": "system", "content": f"You are an expert in {disease_name} pathology."},
                {"role": "user", "content": prompt}
            ],
            temperature=0,
            max_completion_tokens=500
        )
        
        # Parse ranking
        import re
        ranking_text = response.choices[0].message.content
        numbers = re.findall(r'\d+', ranking_text)
        
        if numbers:
            ranking_map = {int(n): i+1 for i, n in enumerate(numbers) if int(n) <= len(top_pathways)}
            for orig_rank, new_rank in ranking_map.items():
                if orig_rank-1 < len(pathways_df):
                    pathways_df.iloc[orig_rank-1, pathways_df.columns.get_loc('gpt_rank')] = new_rank
        
        # Sort by GPT rank
        pathways_df = pathways_df.sort_values('gpt_rank')
        return pathways_df
        
    except Exception as e:
        print(f"⚠️ GPT ranking failed: {e}")
        # Return with sequential ranking
        pathways_df['gpt_rank'] = range(1, len(pathways_df) + 1)
        return pathways_df


# ============================================================================
# ANALYSIS WORKFLOW
# ============================================================================

def run_analysis_workflow(session: AnalysisSession):
    """Run the complete analysis workflow with checkpoints."""
    try:
        session.status = "running"
        session.analysis_started_at = datetime.now()
        session.set_progress(
            3,
            'Preparing analysis',
            'Checking the disease context, gene identifiers and analysis settings.',
        )
        
        # ================================================================
        # PHASE 1: Module Collection
        # ================================================================
        session.current_phase = 1
        session.add_message("system", "📊 Phase 1: Pathway Enrichment Analysis")
        
        # Checkpoint A: Network Biology Query
        wait_for_checkpoint(session, "network_biology", {
            "genes": session.genes[:20],
            "total_genes": len(session.genes)
        })
        session.set_progress(
            8,
            'Starting pathway analysis',
            'The analysis inputs are confirmed.',
        )
        
        # Run REAL or mock pathway analysis
        import time
        if REAL_ANALYSIS_AVAILABLE:
            pathways = run_real_pathway_analysis(session)
        else:
            session.set_progress(30, 'Validating pathways', 'Running the demonstration enrichment workflow.')
            session.add_message("system", "⏳ Running enrichment analysis (demo mode)...")
            time.sleep(2)
            pathways = generate_mock_pathways(session.disease)
            session.add_message("system", f"✅ Found {len(pathways)} enriched pathways")
            session.set_progress(92, 'Preparing the result', f'Prepared {len(pathways)} validated pathways.')
        
        pathways = normalize_pathway_records(pathways)
        session.results['pathways'] = pathways
        
        # Checkpoint 1: Module Review
        wait_for_checkpoint(session, "module_review", {
            "pathways": pathways[:10],
            "total_pathways": len(pathways),
            "module_id": 1
        })
        session.set_progress(95, 'Reviewing validated pathways', 'The validated pathway set is ready.')
        
        if session.checkpoint_data.get('user_response') == 'quit':
            session.status = "cancelled"
            session.add_message("system", "❌ Analysis cancelled by user")
            return
        
        # Checkpoint B: Pathway Query
        top_pathway = pathways[0] if pathways else None
        wait_for_checkpoint(session, "pathway_query", {
            "top_pathway": top_pathway,
            "pathway_name": top_pathway['name'] if top_pathway else 'N/A'
        })
        session.set_progress(97, 'Finalizing the analysis', 'Applying the selected review actions.')
        
        # ================================================================
        # PHASE 2: Aggregation
        # ================================================================
        session.current_phase = 2
        session.add_message("system", "📊 Phase 2: Pathway Aggregation")
        time.sleep(1)
        
        wait_for_checkpoint(session, "aggregation_review", {
            "total_pathways": len(pathways),
            "unique_pathways": len(set(p['name'] for p in pathways))
        })
        session.set_progress(99, 'Building the report', 'Assembling pathways, interpretations and reasoning details.')
        
        if session.checkpoint_data.get('user_response') == 'quit':
            session.status = "cancelled"
            session.add_message("system", "❌ Analysis cancelled by user")
            return
        
        # ================================================================
        # COMPLETE
        # ================================================================
        session.results['disease'] = session.disease_name
        session.results['model'] = session.model
        session.results['gene_count'] = len(session.genes)
        # Preserve the submitted query so clients can verify that displayed
        # pathway intersections are members of the original input list.
        session.results['input_genes'] = list(session.genes)
        disease_config = session.disease_config or get_disease_configuration(session.disease_name)
        session.results['disease_context'] = {
            **session.disease_context,
            'name': session.disease_name,
            'mesh_id': session.disease_context.get('mesh_id') or disease_config.get('mesh_id', ''),
        }
        
        run_summary = compute_run_summary(
            session.results.get('pathways', []),
            session.genes,
            session.disease_name,
            session.results.get('mapping_summary'),
        )
        validation_comparison = session.results.get('validation_comparison') or {}
        if 'initial_hypotheses' in validation_comparison:
            run_summary['initial_hypotheses'] = validation_comparison['initial_hypotheses']
        session.results['run_summary'] = run_summary
        session.results['reasoning_traces'] = [
            {
                'reasoning': msg['data']['reasoning'],
                'category': msg['data'].get('category'),
                'iteration': msg['data'].get('iteration', 1)
            }
            for msg in session.messages
            if msg.get('data') and msg['data'].get('reasoning')
        ]
        session.results['created_at'] = session.created_at.isoformat()
        session.results['completed_at'] = datetime.now().isoformat()
        
        report = generate_summary_report(session)
        session.results['report'] = report
        session.add_message("result", "📝 Final Summary Report", {"report": report})

        session.status = "completed"
        session.set_progress(100, 'Analysis complete', 'The complete result is ready.', state='completed')
        session.add_message("system", "✅ Analysis complete!")

        save_run_to_history(session)
        print(f"💾 Run saved to history: {session.session_id}")
        
    except Exception as e:
        session.status = "error"
        session.set_progress(
            session.progress_percent,
            'Analysis stopped',
            str(e)[:240],
            state='error',
        )
        session.add_message("error", f"Analysis failed: {str(e)}")
        import traceback
        traceback.print_exc()


def wait_for_checkpoint(session: AnalysisSession, checkpoint_type: str, data: dict):
    """Wait for user input at a checkpoint."""
    import time
    
    checkpoint = CHECKPOINTS.get(checkpoint_type, {})
    session.current_checkpoint = checkpoint_type
    session.checkpoint_data = {"type": checkpoint_type, "data": data}
    session.waiting_for_user = True
    checkpoint_progress = max(4, session.progress_percent)
    progress_copy = {
        'network_biology': (
            'Confirm analysis context',
            'Review the submitted genes and disease context before analysis.',
        ),
        'module_review': (
            'Review validated pathways',
            'The statistically supported pathway set is ready for review.',
        ),
        'pathway_query': (
            'Review pathway interpretation',
            'Review the leading pathway before the final report is assembled.',
        ),
        'aggregation_review': (
            'Review final pathway set',
            'Confirm the combined validated pathways before report generation.',
        ),
    }
    progress_stage, progress_detail = progress_copy.get(
        checkpoint_type,
        ('Review required', 'Review the current analysis output.'),
    )
    session.set_progress(
        checkpoint_progress,
        progress_stage,
        progress_detail,
        state='waiting',
    )
    
    # Safe formatting
    format_data = {
        "disease": session.disease_name,
        "pathway_name": data.get('pathway_name', data.get('top_pathway', {}).get('name', 'selected pathway') if isinstance(data.get('top_pathway'), dict) else 'selected pathway'),
        **{k: v for k, v in data.items() if not isinstance(v, (dict, list))}
    }
    
    formatted_questions = []
    for q in checkpoint.get('suggested_questions', []):
        try:
            formatted_questions.append(q.format(**format_data))
        except KeyError:
            pass
    
    session.add_message("checkpoint", checkpoint.get('description', 'Checkpoint'), {
        "checkpoint_type": checkpoint_type,
        "name": checkpoint.get('name', checkpoint_type),
        "actions": checkpoint.get('actions', ['approve', 'skip']),
        "suggested_questions": formatted_questions,
        **data
    })
    
    # Wait for response (5 min timeout)
    timeout = 300
    start_time = time.time()
    while session.waiting_for_user and (time.time() - start_time) < timeout:
        time.sleep(0.5)
    
    if session.waiting_for_user:
        session.checkpoint_data['user_response'] = 'approve'
        session.waiting_for_user = False
        session.add_message("system", "⏰ Timeout - auto-approving")
    session.set_progress(
        checkpoint_progress,
        'Resuming analysis',
        'Review received. Continuing with the next analysis operation.',
    )


def process_user_query(session: AnalysisSession, query: str, context: str) -> dict:
    """Process user query, using GPT if available."""
    query_lower = query.lower()
    
    # Try GPT-powered response if API key available
    print(f"[DEBUG] Query received: {query[:50]}...")
    print(f"[DEBUG] OPENAI_API_KEY set: {bool(OPENAI_API_KEY)}, REAL_ANALYSIS_AVAILABLE: {REAL_ANALYSIS_AVAILABLE}")
    
    if OPENAI_API_KEY and REAL_ANALYSIS_AVAILABLE:
        try:
            import openai
            client = openai.OpenAI(api_key=OPENAI_API_KEY)

            
            # ================================================================
            # ENHANCED CONTEXT: Comprehensive analysis data for accurate QA
            # ================================================================
            
            # Gene context with symbols (not just IDs)
            gene_symbols = session.genes[:50]
            genes_context = ", ".join(gene_symbols)
            
            # Pathway context with categories and p-values
            pathways = session.results.get('pathways', [])
            if pathways:
                pathways_context = "\\n".join([
                    f"- {p['name']} (Cat: {p.get('category', 'N/A')}, p={p.get('p_value', 'N/A'):.2e}, Score: {p.get('score', 'N/A')})"
                    for p in pathways[:15]
                ])
                
                # Category distribution
                categories = {}
                for p in pathways:
                    cat = p.get('category', 'Unknown')
                    categories[cat] = categories.get(cat, 0) + 1
                category_summary = ", ".join([f"{k}: {v}" for k, v in categories.items()])
            else:
                pathways_context = "(Pathway analysis in progress)"
                category_summary = "N/A"
            
            # Module information if available
            module_context = ""
            if hasattr(session, 'module_pathways') and session.module_pathways:
                module_context = f"\\nAnalyzed {len(session.module_pathways)} network modules."
            
            # Retained pathways context
            retained_context = ""
            if hasattr(session, 'retained_pathways') and session.retained_pathways:
                retained_context = f"\\nRetained {len(session.retained_pathways)} statistically validated pathways from previous iterations."
            
            # Build comprehensive system prompt
            system_prompt = f"""You are an expert in {session.disease_name} genetics and pathway analysis. 
Provide specific, actionable insights based on the provided analysis data.
- Answer questions about network-central genes, disease drivers, and biological mechanisms
- Cite specific genes and pathways from the context when relevant
- Keep responses concise (<250 words) and well-structured
- Focus on biological plausibility and disease relevance"""

            user_content = f"""=== ANALYSIS CONTEXT ===
Disease: {session.disease_name}
Total Genes Analyzed: {len(session.genes)}
Key Genes: {genes_context}

Top Enriched Pathways:
{pathways_context}

Category Distribution: {category_summary}
{module_context}
{retained_context}

=== USER QUESTION ===
{query}"""
            
            response = client.chat.completions.create(
                model=session.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_content}
                ],
                temperature=0.3,
                max_completion_tokens=16000
            )
            
            answer = response.choices[0].message.content
            
            # Validate response is not empty
            if answer and len(answer.strip()) > 10:
                return {
                    "answer": answer,
                    "data": {"type": "gpt_response", "model": session.model}
                }
            else:
                print(f"GPT returned empty/short response: '{answer}'")
                # Fall through to pattern matching
        except Exception as e:
            print(f"GPT query failed: {e}")
    
    # Fallback to pattern matching
    if 'interactome' in query_lower or 'connected' in query_lower:
        return {
            "answer": f"These {session.disease_name}-associated genes show strong functional connections through protein-protein interactions in the human interactome. Key interactions likely involve {', '.join(session.genes[:3])} and their partners.",
            "data": {"type": "network_analysis"}
        }
    elif 'hub' in query_lower:
        top_genes = session.genes[:5]
        return {
            "answer": f"""Based on network topology and {session.disease_name} biology, likely hub genes include:

**Top Network Hubs:**
1. **{top_genes[0]}** - Often acts as a master regulator
2. **{top_genes[1]}** - High degree connectivity  
3. **{top_genes[2]}** - Bridges multiple pathways

These genes typically have high betweenness centrality and connect disparate functional modules.""",
            "data": {"type": "hub_analysis"}
        }
    elif 'centrality' in query_lower:
        return {
            "answer": f"Genes with high betweenness centrality often include major regulators like {session.genes[0]} and {session.genes[1]}, acting as bridges between different functional modules.",
            "data": {"type": "centrality_analysis"}
        }
    elif 'complex' in query_lower:
        return {
            "answer": f"These genes are known to form several key protein complexes, particularly those involved in {session.results.get('pathways', [{'name': 'signaling'}])[0]['name']} and related processes.",
            "data": {"type": "complex_analysis"}
        }
    else:
        # Provide a more informative generic response using available session data
        top_pathways = session.results.get('pathways', [])[:3] if session.results else []
        pathway_names = [p.get('name', 'Unknown') for p in top_pathways]
        
        if pathway_names:
            answer = f"""Based on the analysis of {len(session.genes)} genes associated with {session.disease_name}:

**Top Enriched Pathways:**
{chr(10).join([f'- {name}' for name in pathway_names])}

These pathways suggest key biological mechanisms that may be relevant to your query about "{query}"

For more specific questions, try asking about:
- Network interactions between specific genes
- Hub genes and their regulatory roles  
- Pathway enrichment details"""
        else:
            answer = f"""Your query about {session.disease_name} has been noted. 

The analysis is examining {len(session.genes)} genes for pathway enrichment. Once complete, you'll be able to explore:
- Top enriched biological pathways
- Gene-gene interaction networks
- Disease-relevant hub genes

Please wait for the analysis to complete for detailed insights."""
        
        return {
            "answer": answer,
            "data": {"type": "general"}
        }


# ============================================================================
# DATA GENERATION (fallback if real analysis unavailable)
# ============================================================================

def generate_mock_pathways(disease: str) -> list:
    """Generate demo pathway data."""
    if disease.upper() in ['AD', "ALZHEIMER'S"]:
        return [
            {"name": "Amyloid-beta binding", "p_value": 2.3e-12, "score": 87.2, "category": "GO:MF", "genes": "APOE,APP,CLU", "description": "Binding to amyloid-beta peptides"},
            {"name": "APOE signaling pathway", "p_value": 4.1e-10, "score": 81.5, "category": "KEGG", "genes": "APOE,ABCA7,LRP1", "description": "Apolipoprotein E signaling"},
            {"name": "Neuroinflammation", "p_value": 1.2e-9, "score": 78.3, "category": "REAC", "genes": "TREM2,CD33,MS4A6A", "description": "Neuroinflammatory response"},
            {"name": "Tau protein binding", "p_value": 8.5e-9, "score": 75.1, "category": "GO:MF", "genes": "MAPT,PSEN1,PSEN2", "description": "Tau protein binding and phosphorylation"},
            {"name": "Synaptic transmission", "p_value": 2.1e-8, "score": 72.4, "category": "GO:BP", "genes": "SYN1,DLG4,SNAP25", "description": "Synaptic vesicle exocytosis"},
            {"name": "Microglial activation", "p_value": 5.3e-8, "score": 69.8, "category": "GO:BP", "genes": "TREM2,AIF1,CX3CR1", "description": "Microglia activation and polarization"},
            {"name": "Cholesterol metabolism", "p_value": 1.8e-7, "score": 65.2, "category": "KEGG", "genes": "APOE,ABCA7,CLU", "description": "Brain cholesterol homeostasis"},
            {"name": "Protein phosphorylation", "p_value": 4.2e-7, "score": 61.5, "category": "GO:BP", "genes": "GSK3B,CDK5,DYRK1A", "description": "Protein kinase activity"},
        ]
    else:
        return [
            {"name": "Inflammatory response", "p_value": 1.5e-15, "score": 92.1, "category": "GO:BP", "genes": "TNF,IL1B,IL6", "description": "Inflammatory cytokine response"},
            {"name": "Cytokine signaling", "p_value": 3.2e-12, "score": 85.4, "category": "REAC", "genes": "JAK2,STAT3,IL23R", "description": "JAK-STAT signaling"},
            {"name": "NF-kB pathway", "p_value": 7.8e-11, "score": 81.2, "category": "KEGG", "genes": "NFKB1,RELA,IKBKG", "description": "NF-kappa B signaling"},
            {"name": "T cell activation", "p_value": 2.1e-10, "score": 77.8, "category": "GO:BP", "genes": "IL2RA,CD4,CTLA4", "description": "T cell receptor signaling"},
            {"name": "Autophagy", "p_value": 5.5e-9, "score": 73.5, "category": "KEGG", "genes": "ATG16L1,NOD2,IRGM", "description": "Autophagosome formation"},
            {"name": "Intestinal barrier", "p_value": 1.2e-8, "score": 70.2, "category": "GO:CC", "genes": "CDH1,TJP1,OCLN", "description": "Intestinal epithelial barrier"},
            {"name": "Th17 differentiation", "p_value": 3.8e-8, "score": 66.9, "category": "KEGG", "genes": "IL23R,RORC,IL17A", "description": "Th17 cell differentiation"},
            {"name": "Pattern recognition", "p_value": 8.1e-8, "score": 63.4, "category": "REAC", "genes": "NOD2,TLR4,MYD88", "description": "PRR signaling pathway"},
        ]


def generate_drug_targets(genes: list, pathways: list, model=None) -> list:
    """Generate drug target analysis using GPT-powered lookup based on pathway context."""
    
    # First try GPT-powered analysis if available
    if OPENAI_API_KEY and REAL_ANALYSIS_AVAILABLE:
        try:
            import openai
            client = openai.OpenAI(api_key=OPENAI_API_KEY)
            
            # Build context from pathways and genes
            pathway_context = "\\n".join([
                f"- {p.get('name', 'Unknown')}: {p.get('genes', '')[:80]}"
                for p in pathways[:10]
            ]) if pathways else "N/A"
            
            gene_list = ", ".join(genes[:30])
            
            prompt = f"""Based on the following pathway analysis and gene list, identify the top 5 druggable targets with existing or potential therapeutic compounds.

ENRICHED PATHWAYS:
{pathway_context}

KEY GENES:
{gene_list}

For each target, provide:
1. Gene symbol
2. Drug name (approved, investigational, or repurposing candidate)
3. Development status (FDA Approved, Phase 1/2/3, Preclinical)
4. Primary indication

Return as JSON array with keys: gene, drug, status, indication
Example: [{{"gene": "JAK2", "drug": "Tofacitinib", "status": "FDA Approved", "indication": "Rheumatoid Arthritis"}}]

Return ONLY the JSON array, no other text."""

            response = client.chat.completions.create(
                model=model or GPT_MODEL,
                messages=[
                    {"role": "system", "content": "You are a pharmaceutical expert. Provide accurate drug target information based on current knowledge of approved and investigational therapeutics."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.2,
                max_completion_tokens=600
            )
            
            import json
            result_text = response.choices[0].message.content.strip()
            
            # Extract JSON from response
            if '[' in result_text:
                json_start = result_text.index('[')
                json_end = result_text.rindex(']') + 1
                result_text = result_text[json_start:json_end]
            
            targets = json.loads(result_text)
            
            if targets and len(targets) > 0:
                print(f"   ✅ GPT identified {len(targets)} drug targets")
                return targets[:5]
                
        except Exception as e:
            print(f"   ⚠️ GPT drug target analysis failed: {e}")
    
    # Fallback to expanded known targets database
    known_targets = {
        # Alzheimer's Disease
        "APOE": ("APOE modulators", "Phase 2", "Alzheimer's Disease"),
        "APP": ("Aducanumab", "FDA Approved", "Alzheimer's Disease"),
        "BACE1": ("Verubecestat", "Phase 3 (discontinued)", "Alzheimer's Disease"),
        "TREM2": ("AL002", "Phase 2", "Alzheimer's Disease"),
        "PSEN1": ("Gamma-secretase inhibitors", "Phase 2", "Alzheimer's Disease"),
        "MAPT": ("Tau aggregation inhibitors", "Phase 2", "Alzheimer's Disease"),
        # Inflammatory/Autoimmune
        "TNF": ("Infliximab/Adalimumab", "FDA Approved", "Inflammatory diseases"),
        "IL23R": ("Ustekinumab/Risankizumab", "FDA Approved", "IBD/Psoriasis"),
        "JAK2": ("Tofacitinib/Ruxolitinib", "FDA Approved", "Rheumatoid Arthritis/MPN"),
        "JAK1": ("Upadacitinib", "FDA Approved", "Rheumatoid Arthritis"),
        "IL6": ("Tocilizumab", "FDA Approved", "Rheumatoid Arthritis"),
        "NOD2": ("Experimental", "Preclinical", "IBD"),
        # Cardiovascular
        "PCSK9": ("Evolocumab/Alirocumab", "FDA Approved", "Hypercholesterolemia"),
        "APOB": ("Mipomersen", "FDA Approved", "Familial Hypercholesterolemia"),
        "LPA": ("Pelacarsen", "Phase 3", "Cardiovascular Disease"),
        # Oncology
        "EGFR": ("Gefitinib/Osimertinib", "FDA Approved", "Lung Cancer"),
        "BRAF": ("Vemurafenib/Dabrafenib", "FDA Approved", "Melanoma"),
        "BCR-ABL": ("Imatinib", "FDA Approved", "CML"),
        "HER2": ("Trastuzumab", "FDA Approved", "Breast Cancer"),
        # Neurological
        "SOD1": ("Tofersen", "FDA Approved", "ALS"),
        "HTT": ("Risdiplam", "Phase 3", "Huntington's Disease"),
    }
    
    targets = []
    for gene in genes[:20]:
        gene_upper = gene.upper()
        if gene_upper in known_targets:
            drug, status, indication = known_targets[gene_upper]
            targets.append({
                "gene": gene,
                "drug": drug,
                "status": status,
                "indication": indication
            })
        if len(targets) >= 5:
            break
    
    # If still too few, add top genes as potential targets
    if len(targets) < 3:
        for gene in genes[:5]:
            if gene not in [t['gene'] for t in targets]:
                targets.append({
                    "gene": gene,
                    "drug": "Potential target (no approved drugs)",
                    "status": "Target identification",
                    "indication": "Under investigation"
                })
                if len(targets) >= 5:
                    break
    
    return targets[:5]


def generate_summary_report(session: AnalysisSession) -> str:
    """Generate a concise, user-facing analysis summary report."""
    pathways = session.results.get('pathways', [])

    report = f"""# Pathway Analysis Summary Report
## {session.disease_name}

**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
**Input Genes:** {len(session.genes)}
**Analysis Mode:** {'Real Pipeline' if REAL_ANALYSIS_AVAILABLE else 'Demo Mode'}
**GPT Model:** {session.model}

---

## Validated Pathways

| Database rank | Pathway | Pathway ID | Adjusted P-value | Category | Intersection genes |
|---------------|---------|------------|----------------|----------|--------------|
"""

    database_ranks = {}
    for pw in pathways:
        category = pw.get('source') or pw.get('category', 'Other')
        database_ranks[category] = database_ranks.get(category, 0) + 1
        report += (
            f"| {database_ranks[category]} | {pw.get('name', '')} | {get_pathway_identifier(pw) or 'ID unavailable'} | "
            f"{pw.get('p_value', 1.0):.2e} | {category} | {pw.get('genes', '')} |\n"
        )

    report += f"""
---

## Summary

This analysis retained **{len(pathways)} statistically validated pathways** across
**{len({pw.get('source') or pw.get('category', 'Other') for pw in pathways})} database channels**
for {session.disease_name}. Pathways are ranked only within their source
database.

---
*Generated by Gene Pathway Analysis Web Application*
"""

    return report


def polish_takeaway_text(value: str, max_sentences: int = 2, max_length: int = 450) -> str:
    """Return direct take-away prose without formulaic discourse openers."""
    text = pathway_narrative.sanitize_narrative_paragraph(value)
    text = re.sub(
        r'^(?:(?:overall|taken together|collectively)\s*,?\s*)+',
        '',
        text,
        flags=re.I,
    ).strip()
    if text:
        text = text[0].upper() + text[1:]
    sentences = re.split(r'(?<=[.!?])\s+', text)
    text = ' '.join(sentence.strip() for sentence in sentences[:max_sentences] if sentence.strip())
    if len(text) > max_length:
        text = text[:max_length - 3].rsplit(' ', 1)[0] + '...'
    return text


def normalize_cell_context_claim_evidence(pathway):
    """Keep only explicit cell-context claim/label-to-PMID mappings.

    Historical ``cell_context_pmids`` values are pathway-level retrieval sets.
    They are intentionally excluded here because they cannot demonstrate that
    one article supports every generated cell and tissue label.
    """
    raw = pathway.get('cell_context_evidence') or pathway.get('cell_context_claims') or []
    entries = raw if isinstance(raw, list) else raw.get('claims', []) if isinstance(raw, dict) else []
    normalized = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        claim = str(entry.get('claim') or entry.get('text') or entry.get('context') or '').strip()
        labels = entry.get('labels') or ([entry.get('label')] if entry.get('label') else [])
        labels = [str(label).strip() for label in labels if str(label).strip()]
        genes = [str(gene).strip() for gene in entry.get('genes') or [] if str(gene).strip()]
        raw_pmids = entry.get('pmids') or entry.get('citations') or entry.get('literature') or []
        if not isinstance(raw_pmids, list):
            raw_pmids = [raw_pmids]
        pmids = []
        for value in raw_pmids:
            if isinstance(value, dict):
                value = value.get('pmid') or value.get('PMID') or value.get('id')
            pmid = re.sub(r'\D', '', str(value or ''))
            if pmid and pmid not in pmids:
                pmids.append(pmid)
        if pmids and (claim or labels):
            normalized.append({'claim': claim, 'labels': labels, 'genes': genes, 'pmids': pmids})
    return normalized


def generate_full_export_pdf(
    session: AnalysisSession,
    summary_only: bool = False,
    pathways_per_database=None,
) -> BytesIO:
    """Build the take-away summary or detailed source-linked report."""
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER, TA_LEFT
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import (
        KeepTogether,
        PageBreak,
        Paragraph,
        SimpleDocTemplate,
        Spacer,
        Table,
        TableStyle,
    )

    all_pathways = normalize_pathway_records(session.results.get('pathways', []))
    pathways = []
    export_counts = {}
    for pathway in all_pathways:
        category = pathway.get('source') or pathway.get('category') or 'Other'
        export_counts[category] = export_counts.get(category, 0) + 1
        if pathways_per_database is None or export_counts[category] <= pathways_per_database:
            pathways.append(pathway)
    run_summary = compute_run_summary(
        all_pathways,
        session.genes,
        session.disease_name,
        session.results.get('mapping_summary'),
    )
    output = BytesIO()
    doc = SimpleDocTemplate(
        output,
        pagesize=A4,
        rightMargin=15 * mm,
        leftMargin=15 * mm,
        topMargin=19 * mm,
        bottomMargin=18 * mm,
        title=f"GenePathwayAI - {session.disease_name}",
        author="GenePathwayAI",
        subject="Pathway enrichment and biological interpretation report",
    )

    palette = {
        'ink': colors.HexColor('#18332f'),
        'body': colors.HexColor('#526965'),
        'green': colors.HexColor('#1f9d83'),
        'green_dark': colors.HexColor('#15755f'),
        'mint': colors.HexColor('#e9f6f2'),
        'line': colors.HexColor('#d5e3df'),
        'panel': colors.HexColor('#f5f8f7'),
        'white': colors.white,
    }

    base = getSampleStyleSheet()
    styles = {
        'title': ParagraphStyle(
            'ReportTitle', parent=base['Title'], fontName='Helvetica-Bold',
            fontSize=23, leading=27, textColor=palette['ink'], alignment=TA_LEFT,
            spaceAfter=5 * mm,
        ),
        'subtitle': ParagraphStyle(
            'ReportSubtitle', parent=base['Normal'], fontName='Helvetica',
            fontSize=10, leading=14, textColor=palette['body'], spaceAfter=4 * mm,
        ),
        'h1': ParagraphStyle(
            'ReportH1', parent=base['Heading1'], fontName='Helvetica-Bold',
            fontSize=15, leading=19, textColor=palette['ink'], spaceBefore=5 * mm,
            spaceAfter=3 * mm, keepWithNext=True,
        ),
        'h2': ParagraphStyle(
            'ReportH2', parent=base['Heading2'], fontName='Helvetica-Bold',
            fontSize=11.5, leading=15, textColor=palette['green_dark'],
            spaceBefore=4 * mm, spaceAfter=2 * mm, keepWithNext=True,
        ),
        'h3': ParagraphStyle(
            'ReportH3', parent=base['Heading3'], fontName='Helvetica-Bold',
            fontSize=9.5, leading=13, textColor=palette['ink'],
            spaceBefore=3 * mm, spaceAfter=1.5 * mm, keepWithNext=True,
        ),
        'body': ParagraphStyle(
            'ReportBody', parent=base['BodyText'], fontName='Helvetica',
            fontSize=8.6, leading=12.5, textColor=palette['body'],
            spaceAfter=2.2 * mm, allowWidows=1, allowOrphans=1,
        ),
        'small': ParagraphStyle(
            'ReportSmall', parent=base['BodyText'], fontName='Helvetica',
            fontSize=7.4, leading=10, textColor=palette['body'], spaceAfter=1.5 * mm,
        ),
        'metric': ParagraphStyle(
            'ReportMetric', parent=base['BodyText'], fontName='Helvetica-Bold',
            fontSize=15, leading=17, textColor=palette['green_dark'], alignment=TA_CENTER,
        ),
        'metric_label': ParagraphStyle(
            'ReportMetricLabel', parent=base['BodyText'], fontName='Helvetica',
            fontSize=7, leading=9, textColor=palette['body'], alignment=TA_CENTER,
        ),
        'table_header': ParagraphStyle(
            'ReportTableHeader', parent=base['BodyText'], fontName='Helvetica-Bold',
            fontSize=6.8, leading=8, textColor=palette['white'],
        ),
        'table_cell': ParagraphStyle(
            'ReportTableCell', parent=base['BodyText'], fontName='Helvetica',
            fontSize=6.7, leading=8.4, textColor=palette['ink'],
        ),
    }

    character_map = str.maketrans({
        '\u2013': '-', '\u2014': '-', '\u2011': '-', '\u2212': '-',
        '\u2018': "'", '\u2019': "'", '\u201c': '"', '\u201d': '"',
        '\u2192': '->', '\u2190': '<-', '\u2264': '<=', '\u2265': '>=',
        '\u03b1': 'alpha', '\u03b2': 'beta', '\u03b3': 'gamma', '\u03b4': 'delta',
        '\u03bc': 'micro', '\u00b7': ' / ', '\u00a0': ' ', '\u00b1': '+/-',
        '\u207a': '+', '\u207b': '-', '\u2070': '0', '\u00b9': '1',
        '\u00b2': '2', '\u00b3': '3', '\u2074': '4', '\u2075': '5',
        '\u2076': '6', '\u2077': '7', '\u2078': '8', '\u2079': '9',
        '\u2080': '0', '\u2081': '1', '\u2082': '2', '\u2083': '3',
        '\u2084': '4', '\u2085': '5', '\u2086': '6', '\u2087': '7',
        '\u2088': '8', '\u2089': '9',
    })

    def safe_text(value, preserve_lines=False):
        text = str(value or '').translate(character_map).replace('**', '').replace('__', '')
        # ReportLab paragraphs reject XML control characters. Real model and
        # literature responses can occasionally contain them, so sanitize at
        # the export boundary instead of letting the whole PDF request fail.
        text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', text)
        escaped = html_escape(text)
        return escaped.replace('\n', '<br/>') if preserve_lines else ' '.join(escaped.split())

    def intersection_genes(pathway):
        for field in ('intersection_genes', 'intersection_gene_symbols', 'intersections'):
            values = pathway.get(field)
            if isinstance(values, list):
                cleaned = [str(value).strip() for value in values if str(value).strip()]
                if cleaned:
                    return list(dict.fromkeys(cleaned))
        legacy = str(pathway.get('genes') or '').strip()
        if legacy and not legacy.isdigit():
            return list(dict.fromkeys(
                value.strip() for value in legacy.replace(';', ',').split(',') if value.strip()
            ))
        return []

    def pathway_url(pathway):
        pathway_id = get_pathway_identifier(pathway)
        category = pathway.get('source') or pathway.get('category') or ''
        if pathway_id.startswith('GO:'):
            return f"https://amigo.geneontology.org/amigo/term/{pathway_id}"
        if category == 'KEGG' or pathway_id.startswith(('KEGG:', 'hsa')):
            entry_id = pathway_id.replace('KEGG:', '')
            if entry_id.isdigit():
                entry_id = f"hsa{entry_id}"
            return f"https://www.kegg.jp/entry/{entry_id}"
        if category == 'REAC' or 'R-HSA-' in pathway_id:
            entry_id = pathway_id.replace('REAC:', '')
            return f"https://reactome.org/content/detail/{entry_id}"
        return ''

    def report_page(canvas, document):
        canvas.saveState()
        width, _ = A4
        canvas.setStrokeColor(palette['line'])
        canvas.setLineWidth(0.5)
        canvas.line(15 * mm, 13 * mm, width - 15 * mm, 13 * mm)
        canvas.setFont('Helvetica', 7)
        canvas.setFillColor(palette['body'])
        canvas.drawString(
            15 * mm,
            8.5 * mm,
            'GenePathwayAI / ' + ('Take-away summary' if summary_only else 'Detailed analysis report'),
        )
        canvas.drawRightString(width - 15 * mm, 8.5 * mm, f"Page {document.page}")
        canvas.restoreState()

    story = []
    story.append(Paragraph('GenePathwayAI', styles['subtitle']))
    story.append(Paragraph(
        'Take-away pathway summary' if summary_only else 'Detailed pathway analysis report',
        styles['title'],
    ))
    disease_id = run_summary.get('disease_id') or 'Not mapped'
    mapping = run_summary.get('mapping_summary') or {}
    mapped_count = mapping.get('mapped_count', run_summary.get('mapped_gene_count', len(session.genes)))
    input_count = mapping.get('input_count', len(session.genes))
    story.append(Paragraph(
        f"<b>Disease context:</b> {safe_text(session.disease_name)}<br/>"
        f"<b>NCBI MeSH ID:</b> {safe_text(disease_id)}<br/>"
        f"<b>Generated:</b> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}<br/>"
        f"<b>Gene mapping:</b> {safe_text(mapped_count)} of {safe_text(input_count)} input genes &nbsp;&nbsp; "
        f"<b>Model:</b> {safe_text(session.model)}",
        styles['subtitle'],
    ))

    metric_data = [[
        Paragraph(str(mapped_count), styles['metric']),
        Paragraph(str(run_summary['significant_pathways']), styles['metric']),
        Paragraph(str(run_summary['categories_covered']), styles['metric']),
    ], [
        Paragraph(f'mapped genes / {input_count} input', styles['metric_label']),
        Paragraph('statistically validated pathways', styles['metric_label']),
        Paragraph('database channels', styles['metric_label']),
    ]]
    metrics = Table(metric_data, colWidths=[doc.width / 3] * 3, rowHeights=[11 * mm, 9 * mm])
    metrics.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), palette['mint']),
        ('BOX', (0, 0), (-1, -1), 0.6, palette['line']),
        ('INNERGRID', (0, 0), (-1, -1), 0.4, palette['line']),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('LEFTPADDING', (0, 0), (-1, -1), 4),
        ('RIGHTPADDING', (0, 0), (-1, -1), 4),
    ]))
    story.extend([metrics, Spacer(1, 3 * mm)])
    story.append(Paragraph('1. Pipeline Output Summary', styles['h1']))
    table_rows = [[
        Paragraph('Database', styles['table_header']),
        Paragraph('ID', styles['table_header']),
        Paragraph('Rank', styles['table_header']),
        Paragraph('Pathway', styles['table_header']),
        Paragraph('Adjusted P-value', styles['table_header']),
        Paragraph('Pathway size', styles['table_header']),
        Paragraph('Overlap', styles['table_header']),
    ]]
    database_ranks = {}
    for pathway in pathways:
        category = pathway.get('source') or pathway.get('category') or 'Other'
        database_ranks[category] = database_ranks.get(category, 0) + 1
        genes = intersection_genes(pathway)
        intersection_count = len(genes) or pathway.get('intersection_size') or 'N/A'
        table_rows.append([
            Paragraph(safe_text(category), styles['table_cell']),
            Paragraph(safe_text(get_pathway_identifier(pathway) or 'ID unavailable'), styles['table_cell']),
            Paragraph(str(database_ranks[category]), styles['table_cell']),
            Paragraph(safe_text(pathway.get('name') or 'Unnamed pathway'), styles['table_cell']),
            Paragraph(f"{float(pathway.get('p_value', 1.0)):.2e}", styles['table_cell']),
            Paragraph(safe_text(pathway.get('term_size') or 'N/A'), styles['table_cell']),
            Paragraph(safe_text(intersection_count), styles['table_cell']),
        ])
    pathway_table = Table(
        table_rows,
        repeatRows=1,
        colWidths=[20 * mm, 29 * mm, 12 * mm, 51 * mm, 25 * mm, 21 * mm, 22 * mm],
        hAlign='LEFT',
    )
    pathway_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), palette['green_dark']),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [palette['white'], palette['panel']]),
        ('GRID', (0, 0), (-1, -1), 0.35, palette['line']),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('LEFTPADDING', (0, 0), (-1, -1), 4),
        ('RIGHTPADDING', (0, 0), (-1, -1), 4),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
    ]))
    story.extend([pathway_table, Spacer(1, 4 * mm)])

    story.append(PageBreak())
    story.append(Paragraph('2. Highlighted Pathways with Interpretations', styles['h1']))
    detail_pathways = pathways
    detail_ranks = {}
    for pathway in detail_pathways:
        pathway_id = get_pathway_identifier(pathway) or 'ID unavailable'
        category = pathway.get('source') or pathway.get('category') or 'Other'
        detail_ranks[category] = detail_ranks.get(category, 0) + 1
        database_rank = detail_ranks[category]
        url = pathway_url(pathway)
        title = f"{database_rank}. "
        if url:
            title += f"<font color=\"#1f9d83\"><link href=\"{url}\">{safe_text(pathway_id)}</link></font>"
        else:
            title += safe_text(pathway_id)
        title += f": {safe_text(pathway.get('name') or 'Unnamed pathway')}"
        title_flowable = Paragraph(title, styles['h2'])
        genes = intersection_genes(pathway)
        metadata = (
            f"<b>Database:</b> {safe_text(category)} &nbsp;&nbsp; "
            f"<b>Adjusted P-value:</b> {float(pathway.get('p_value', 1.0)):.3g} &nbsp;&nbsp; "
            f"<b>Pathway size:</b> {safe_text(pathway.get('term_size') or 'N/A')} &nbsp;&nbsp; "
            f"<b>Input overlap:</b> {len(genes) or pathway.get('intersection_size') or 'N/A'}"
        )
        metadata_flowable = Paragraph(metadata, styles['small'])

        if not summary_only:
            story.extend([title_flowable, metadata_flowable])

        pathway_description = pathway.get('pathway_description') or pathway.get('source_description')
        if pathway_description and not summary_only:
            story.append(Paragraph('<b>Pathway definition</b>', styles['h3']))
            story.append(Paragraph(safe_text(pathway_description, preserve_lines=True), styles['body']))

        narrative = pathway.get('pathway_narrative') or {}
        narrative_paragraphs = list(filter(None, (
            pathway_narrative.sanitize_narrative_paragraph(paragraph)
            for paragraph in narrative.get('paragraphs', [])
        )))
        interpretation_points = pathway.get('interpretation_points') or []
        interpretation = (
            pathway.get('disease_interpretation')
            or pathway.get('description')
            or pathway.get('reasoning')
        )
        if summary_only:
            takeaway = (
                narrative_paragraphs[-1]
                if narrative_paragraphs
                else str(interpretation or pathway.get('description') or '').strip()
            )
            summary_flowables = [title_flowable, metadata_flowable]
            if takeaway:
                takeaway = polish_takeaway_text(takeaway, max_sentences=2, max_length=450)
                summary_flowables.append(Paragraph(
                    safe_text(takeaway, preserve_lines=True),
                    styles['body'],
                ))
            summary_flowables.append(Spacer(1, 1.5 * mm))
            story.append(KeepTogether(summary_flowables))
            continue
        if narrative_paragraphs:
            story.append(Paragraph('<b>Pathway narrative</b>', styles['h3']))
            for paragraph in narrative_paragraphs:
                story.append(Paragraph(
                    safe_text(paragraph, preserve_lines=True),
                    styles['body'],
                ))
            driver_genes = [
                str(gene).strip()
                for gene in narrative.get('driver_genes', [])
                if str(gene).strip()
            ]
            if driver_genes:
                story.append(Paragraph(
                    f"<b>Driving genes:</b> {safe_text(', '.join(driver_genes))}",
                    styles['body'],
                ))
            clusters = [
                cluster for cluster in narrative.get('clusters', [])
                if isinstance(cluster, dict) and cluster.get('genes')
            ]
            if clusters:
                story.append(Paragraph('<b>Functional clusters</b>', styles['h3']))
                for cluster in clusters:
                    label = str(cluster.get('label') or 'Cluster').strip()
                    cluster_genes = ', '.join(
                        str(gene).strip()
                        for gene in cluster.get('genes', [])
                        if str(gene).strip()
                    )
                    story.append(Paragraph(
                        f"<b>{safe_text(label)}:</b> {safe_text(cluster_genes)}",
                        styles['body'],
                    ))
        elif interpretation_points:
            story.append(Paragraph('<b>Disease-related interpretation</b>', styles['h3']))
            for point in interpretation_points:
                if not isinstance(point, dict) or not point.get('text'):
                    continue
                story.append(Paragraph(
                    f"<b>{safe_text(point.get('label') or 'Biological interpretation')}:</b> "
                    f"{safe_text(point.get('text'))}",
                    styles['body'],
                ))
        elif interpretation:
            story.append(Paragraph('<b>Disease-related interpretation</b>', styles['h3']))
            story.append(Paragraph(safe_text(interpretation, preserve_lines=True), styles['body']))

        cell_context = pathway.get('cell_context') or extract_pathway_cell_context(interpretation)
        if cell_context:
            story.append(Paragraph('<b>Cell/tissue context</b>', styles['h3']))
            story.append(Paragraph(safe_text(cell_context), styles['body']))
            context_evidence = normalize_cell_context_claim_evidence(pathway)
            if context_evidence:
                story.append(Paragraph('<b>Claim-linked context evidence</b>', styles['small']))
                for item in context_evidence:
                    scope_parts = list(item['labels'])
                    if item.get('genes'):
                        scope_parts.append(', '.join(item['genes']))
                    scope = ' / '.join(scope_parts) or item['claim']
                    context_links = ', '.join(
                        f'<link href="https://pubmed.ncbi.nlm.nih.gov/{safe_text(pmid)}/" '
                        f'color="#15755f">PMID:{safe_text(pmid)}</link>'
                        for pmid in item['pmids']
                    )
                    story.append(Paragraph(
                        f'<b>{safe_text(scope)}:</b> {context_links}',
                        styles['small'],
                    ))
            else:
                archive_note = (
                    ' The archived pathway-level PMID set is not shown as direct support.'
                    if pathway.get('cell_context_pmids') else ''
                )
                story.append(Paragraph(
                    '<b>Evidence scope:</b> This is a pathway-level model mapping; '
                    f'no claim-level PMID mapping was archived.{archive_note}',
                    styles['small'],
                ))

        story.append(Paragraph('<b>Input-pathway intersection genes</b>', styles['h3']))
        story.append(Paragraph(
            safe_text(', '.join(genes) if genes else 'Not available in the source result.'),
            styles['body'],
        ))

        external_entries = (
            pathway.get('external_evidence_genes')
            or pathway.get('independent_evidence_genes')
            or []
        )
        external_entries = [
            entry for entry in external_entries
            if isinstance(entry, dict) and entry.get('gene')
        ]
        if external_entries:
            story.append(Paragraph('<b>External corroborating genes</b>', styles['h3']))
            external_note = (
                pathway.get('external_evidence_note')
                or pathway.get('independent_evidence_note')
                or 'External evidence; not used for enrichment or ranking.'
            )
            story.append(Paragraph(safe_text(external_note), styles['small']))
            for entry in external_entries:
                pmids_for_gene = [
                    str(pmid).strip() for pmid in entry.get('pmids', []) if str(pmid).strip()
                ]
                links = ', '.join(
                    f'<link href="https://pubmed.ncbi.nlm.nih.gov/{safe_text(pmid)}/" '
                    f'color="#5e4c94">PMID:{safe_text(pmid)}</link>'
                    for pmid in pmids_for_gene
                )
                suffix = f' — {links}' if links else ''
                story.append(Paragraph(
                    f"<b>{safe_text(entry.get('gene'))}</b>{suffix}",
                    styles['small'],
                ))

        literature = pathway.get('literature') or []
        pmids = list(dict.fromkeys(
            [str(value) for value in pathway.get('pmids', []) if value]
            + [
                str(record.get('pmid') or record.get('PMID'))
                for record in literature if isinstance(record, dict)
                and (record.get('pmid') or record.get('PMID'))
            ]
        ))
        if pmids:
            story.append(Paragraph('<b>Literature evidence</b>', styles['h3']))
            literature_by_pmid = {
                str(record.get('pmid') or record.get('PMID')): record
                for record in literature if isinstance(record, dict)
                and (record.get('pmid') or record.get('PMID'))
            }
            for pmid in pmids:
                record = literature_by_pmid.get(pmid, {})
                title_text = record.get('title') or f"PubMed record {pmid}"
                citation = safe_text(title_text)
                journal = record.get('journal')
                year = record.get('year')
                if journal or year:
                    citation += f" ({safe_text(journal)}{', ' if journal and year else ''}{safe_text(year)})"
                story.append(Paragraph(
                    f"<link href=\"https://pubmed.ncbi.nlm.nih.gov/{safe_text(pmid)}/\" "
                    f"color=\"#15755f\">PMID:{safe_text(pmid)}</link> - {citation}",
                    styles['small'],
                ))
        story.append(Spacer(1, 2 * mm))

    if not summary_only:
        story.append(PageBreak())
        story.append(Paragraph('3. Reasoning Details', styles['h1']))
        story.append(Paragraph(
            f"The analysis received {len(session.genes)} input identifiers. The complete submitted list is retained below for reproducibility.",
            styles['body'],
        ))
        story.append(Paragraph(safe_text(', '.join(session.genes)), styles['small']))

        provenance = session.results.get('enrichment_provenance') or {}
        if provenance:
            story.append(Paragraph('Enrichment provenance', styles['h2']))
            provenance_lines = [
                ('Provider', provenance.get('provider')),
                ('Data version', provenance.get('gprofiler_data_version')),
                ('Snapshot generated', provenance.get('snapshot_generated_at')),
                ('Input SHA-256', provenance.get('input_sha256')),
                ('Matrix SHA-256', provenance.get('matrix_sha256')),
            ]
            for label, value in provenance_lines:
                if value:
                    story.append(Paragraph(
                        f"<b>{safe_text(label)}:</b> {safe_text(value)}",
                        styles['small'],
                    ))

    doc.build(story, onFirstPage=report_page, onLaterPages=report_page)
    output.seek(0)
    return output


def generate_full_export_report(session: AnalysisSession) -> str:
    """Generate comprehensive export report with reasoning paths and full evidence."""
    pathways = session.results.get('pathways', [])
    
    genes_str = ', '.join(session.genes[:50])
    if len(session.genes) > 50:
        genes_str += f"... (+{len(session.genes) - 50} more)"
    
    report = f"""# Gene Pathway Analysis Report
## {session.disease_name}

**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}  
**Analysis Mode:** {'Real Pipeline' if REAL_ANALYSIS_AVAILABLE else 'Demo Mode'}  
**GPT Model:** {session.model}  
**Input Genes ({len(session.genes)}):** {genes_str}

---

## 1. Enriched Pathways ({len(pathways)} total)

| Database rank | Pathway | Pathway ID | Category | Adjusted P-value | Intersection genes |
|---------------|---------|------------|----------|----------------|--------------|
"""

    database_ranks = {}
    for pw in pathways:
        category = pw.get('source') or pw.get('category', 'Other')
        database_ranks[category] = database_ranks.get(category, 0) + 1
        report += (
            f"| {database_ranks[category]} | {pw.get('name', '')} | {get_pathway_identifier(pw) or 'ID unavailable'} | {category} | "
            f"{pw.get('p_value', 1.0):.2e} | {pw.get('genes', '')} |\n"
        )
    
    report += "\n---\n\n## 2. Pathway Details & Disease Connections\n\n"
    
    for i, pw in enumerate(pathways, 1):
        desc = pw.get('description', '')
        pmids = pw.get('pmids', [])
        report += f"### {i}. {pw.get('name', '')} ({get_pathway_identifier(pw) or 'ID unavailable'})\n\n"
        report += f"- **Pathway ID:** {get_pathway_identifier(pw) or 'ID unavailable'}  \n"
        report += f"- **Category:** {pw.get('category', '')}  \n"
        report += f"- **Adjusted P-value:** {pw.get('p_value', 1.0):.2e}  \n"
        report += f"- **Genes:** {pw.get('genes', '')}  \n"
        if desc:
            report += f"- **Disease Connection:** {desc}\n"
        if pmids:
            report += f"- **PubMed References:** {', '.join(['PMID:' + p for p in pmids[:5]])}\n"
        
        lit = pw.get('literature', [])
        if lit:
            report += "\n**Literature Evidence:**\n\n"
            for ref in lit[:5]:
                if isinstance(ref, dict):
                    title = ref.get('title', 'N/A')
                    pmid = ref.get('pmid', ref.get('PMID', ''))
                    report += f"  - {title} (PMID: {pmid})\n"
        report += "\n"

    reasoning_sections = []
    for msg in session.messages:
        if msg.get('data') and msg['data'].get('reasoning'):
            reasoning_sections.append(msg['data'])
    
    if reasoning_sections:
        report += "---\n\n## 3. AI Reasoning Paths\n\n"
        for section in reasoning_sections:
            cat = section.get('category', 'Unknown')
            iteration = section.get('iteration', 1)
            reasoning = section.get('reasoning', {})
            if not isinstance(reasoning, dict):
                reasoning = {'overall_strategy': str(reasoning)} if reasoning else {}
            
            report += f"### {cat} (Iteration {iteration})\n\n"
            
            field_labels = {
                'overall_strategy': 'Overall Strategy',
                'strategy': 'Strategy',
                'gene_analysis': 'Gene Analysis',
                'database_focus': 'Database Focus',
                'key_gene_functions': 'Key Gene Functions',
                'pathway_selection_rationale': 'Pathway Selection Rationale',
                'biological_evidence': 'Biological Evidence',
                'cell_context': 'Cell Context',
                'relevance_strength_with_disease': 'Disease Relevance',
                'learned_from_previous_iteration': 'Learned from Previous Iteration',
                'learned_from_feedback': 'Learned from Feedback',
                'pathway_guidance': 'Pathway Guidance',
                'category_specific_adjustments': 'Category-Specific Adjustments',
                'category_adjustments': 'Category Adjustments',
                'validation_reflection': 'Validation Reflection',
                'failure_analysis': 'Failure Analysis',
                'bottleneck_diagnosis': 'Bottleneck Diagnosis'
            }
            
            for key, label in field_labels.items():
                value = reasoning.get(key, '')
                if value and value not in ('Not provided', 'N/A', ''):
                    report += f"**{label}:**  \n{value}\n\n"
            
            report += "---\n\n"

    cat_dist = {}
    for p in pathways:
        cat = p.get('category', 'Unknown')
        cat_dist[cat] = cat_dist.get(cat, 0) + 1
    
    report += f"""---

## 4. Analysis Summary

- **Statistically validated pathways:** {len(pathways)}
- **Databases represented:** {len(cat_dist)}/5
- **Category Distribution:** {', '.join(f'{k}: {v}' for k, v in sorted(cat_dist.items()))}
- **Interpretation fields:** ranked pathways, driver genes and functions, cell/tissue context, mechanistic themes, and disease-relevance strength

---
*Generated by Gene Pathway Analysis Web Application*  
*Model: {session.model} | Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*
"""
    
    return report


# ============================================================================
# ITERATIVE PATHWAY ANALYSIS (2 iterations)
# ============================================================================

def run_iterative_pathway_analysis(session: AnalysisSession) -> list:
    """
    ITERATIVE MODE: Run 2 iterations of pathway analysis.
    
    Each iteration:
    - Iteration 1: Cold start (no context)
    - Iteration 2: Retain ALL FDR-filtered pathways + generate NEW predictions
    
    Follows the HITL script logic from run_aggregated_disease_analysis_hitl.py
    """
    import pandas as pd
    
    disease_config = get_disease_configuration(session.disease_name)
    session.disease_config = disease_config
    disease_description = disease_config.get('description', '')
    
    all_iterations_pathways = []
    final_matched_pathways = pd.DataFrame()
    initial_hypotheses_by_database = {}
    round_validation_summaries = []
    
    for iteration in range(1, 3):
        session.current_iteration = iteration
        round_label = "Initial Prompt" if iteration == 1 else "Refined Prompt"
        round_start = 12 if iteration == 1 else 42
        session.set_progress(
            round_start,
            f'{round_label} hypothesis generation',
            f'Generating pathway hypotheses for prompt pass {iteration} of 2.',
        )
        session.add_message("system", f"🔄 Multiple Runs: Round {iteration}/2 ({round_label}) {'─' * 40}")
        
        try:
            # ================================================================
            # STEP 1: GPT-5 Pathway Prediction
            # ================================================================
            reasoning_by_category = {}  # Will store reasoning for each category

            if iteration == 1:
                # Cold start: No context
                session.add_message("system", f"🧠 Step 1 (Initial Prompt): GPT-5 generating initial pathway hypotheses...")
                predicted_pathways, pathway_details, reasoning_by_category = gpt_predict_pathways(
                    genes=session.genes,
                    disease_name=session.disease_name,
                    disease_description=disease_description,
                    iteration=iteration,
                    model=session.model,
                )
                session.add_message("system", f"✅ GPT predicted {len(predicted_pathways)} pathways")
            else:
                # Warm start: Use retained pathways as context
                retained_count = len(session.retained_pathways)
                session.add_message("system",
                    f"🧠 Step 1 (Refined Prompt): GPT-5 generating refined pathway hypotheses ({retained_count} validated pathways as context)...")

                # Generate NEW predictions with context - now returns reasoning by category
                predicted_pathways, pathway_details, reasoning_by_category = gpt_predict_pathways_with_context(
                    genes=session.genes,
                    disease_name=session.disease_name,
                    disease_description=disease_description,
                    retained_pathways=session.retained_pathways,
                    iteration=iteration,
                    model=session.model,
                )
                session.add_message("system",
                    f"✅ GPT generated {len(predicted_pathways)} NEW predictions")

            # Display reasoning panels for each category
            if reasoning_by_category:
                for category_code, reasoning_dict in reasoning_by_category.items():
                    session.add_message("result", f"🧠 AI Reasoning Path - {category_code}", data={
                        "reasoning": reasoning_dict,
                        "category": category_code,
                        "iteration": iteration
                    })
                session.add_message("system", f"💭 Generated reasoning for {len(reasoning_by_category)} categories")
            
            # ================================================================
            # STEP 2: g:Profiler Enrichment
            # ================================================================
            session.set_progress(
                round_start + 10,
                f'{round_label} statistical validation',
                f'Validating prompt pass {iteration} against functional enrichment.',
            )
            session.add_message("system", "🔬 Step 2 (Statistical Validation): functional enrichment analysis...")
            
            from gprofiler import GProfiler
            gp = GProfiler(return_dataframe=True)
            
            enrichment_results = gp.profile(
                organism='hsapiens',
                query=session.genes,
                sources=['GO:BP', 'GO:MF', 'GO:CC', 'KEGG', 'REAC'],
                user_threshold=1.0,
                significance_threshold_method='fdr',
                # Retain the actual input genes annotated to each term.
                no_evidences=False
            )
            if not session.results.get('mapping_summary'):
                session.results['mapping_summary'] = summarize_gprofiler_gene_mapping(
                    getattr(gp, 'meta', {}),
                    session.genes,
                )
            
            if enrichment_results.empty:
                session.add_message("system", "⚠️ No pathway enrichment results were returned")
                continue
            
            n_sig = (enrichment_results['p_value'] < 0.05).sum()
            session.add_message("system",
                f"✅ Enrichment analysis returned {len(enrichment_results)} pathways ({n_sig} significant)")
            
            # ================================================================
            # STEP 3: Match GPT with g:Profiler
            # ================================================================
            # Build set of retained pathway names for tracking new vs retained matches
            retained_names = {p.get('name', '') for p in session.retained_pathways} if session.retained_pathways else set()
            
            matched_pathways, category_stats = match_gpt_with_gprofiler_detailed(
                gpt_predictions=predicted_pathways,
                pathway_details=pathway_details,
                gprofiler_results=enrichment_results,
                retained_pathway_names=retained_names  # Track new vs retained matches
            )

            if iteration == 1:
                initial_hypotheses_by_database = {
                    category: int(category_stats.get(category, {}).get('predicted', 0))
                    for category in ['GO:BP', 'GO:MF', 'GO:CC', 'KEGG', 'REAC']
                }

            
            session.set_progress(
                round_start + 18,
                f'{round_label} pathway matching',
                f'Matching prompt pass {iteration} to supported enrichment records.',
            )
            session.add_message("system", f"🔗 Step 3 (Cross-Validation): Matching hypotheses with enrichment results...")
            
            #  Filter by FDR < 0.05 (this is what we retain)
            fdr_filtered = matched_pathways[matched_pathways['p_value'] < 0.05].copy()
            
            # Display iteration statistics
            round_validation_summaries.append(
                display_iteration_stats(
                    session,
                    iteration,
                    category_stats,
                    len(session.retained_pathways),
                    len(predicted_pathways),
                    len(matched_pathways),
                    len(fdr_filtered),
                )
            )
            
            # ================================================================
            # STEP 4: Retain ALL FDR-filtered pathways for next iteration
            # ================================================================
            # CRITICAL: User specified to retain ALL filtered, not just top N
            session.retained_pathways = fdr_filtered.to_dict('records')
            
            session.add_message("system", 
                f"💾 Retained {len(session.retained_pathways)} statistically validated hypotheses for refined prompt")
            
            # Store for merging at end
            if not fdr_filtered.empty:
                all_iterations_pathways.append(fdr_filtered)
                final_matched_pathways = pd.concat([final_matched_pathways, fdr_filtered], 
                                                   ignore_index=True)
            
        except Exception as e:
            print(f"Round {iteration}/2 ({round_label}) error: {e}")
            import traceback
            traceback.print_exc()
            session.add_message("system", f"⚠️ Round {iteration}/2 ({round_label}) error: {str(e)[:100]}")
            continue
    
    # ================================================================
    # FINAL: Merge and rank all pathways from all iterations
    # ================================================================
    session.set_progress(
        66,
        'Merging prompt passes',
        'Combining supported pathways and removing duplicate records.',
    )
    session.add_message("system", "🎯 **Final Step**: Merging and ranking all iterations...")
    
    if final_matched_pathways.empty:
        session.add_message("system", "⚠️ No pathways validated across all iterations")
        return generate_mock_pathways(session.disease)
    
    # Remove duplicates (keep first occurrence)
    final_matched_pathways = final_matched_pathways.drop_duplicates(subset=['name'], keep='first')
    
    session.add_message("system", 
        f"✅ Total unique pathways from all iterations: {len(final_matched_pathways)}")
    
    # GPT Auto-Rank the merged pathways
    try:
        ranked_pathways = gpt_rank_pathways_direct(
            final_matched_pathways,
            session.disease_name,
            disease_description,
            top_n=30,
            model=session.model,
        )
    except Exception as e:
        print(f"GPT ranking error: {e}")
        ranked_pathways = final_matched_pathways.sort_values('p_value').head(30)
    
    # Convert to output format (same as single-shot mode)
    session.set_progress(
        70,
        'Ranking validated pathways',
        f'Ranking {len(ranked_pathways)} supported pathways and preparing the final selection.',
    )
    pathways_list = convert_pathways_to_output_format(
        ranked_pathways,
        session.disease_name,
        input_genes=session.genes,
        progress=lambda text: add_analysis_progress_message(session, text),
        model=session.model,
    )
    session.set_progress(
        94,
        'Preparing the result',
        f'Assembled {len(pathways_list)} validated pathways and their evidence records.',
    )

    validated_by_database = {category: 0 for category in ['GO:BP', 'GO:MF', 'GO:CC', 'KEGG', 'REAC']}
    for pathway in pathways_list:
        category = pathway.get('category', 'Other')
        if category in validated_by_database:
            validated_by_database[category] += 1
    session.results['validation_comparison'] = {
        'initial_hypotheses': sum(initial_hypotheses_by_database.values()),
        'matched_hypotheses': (
            round_validation_summaries[0]['matched_hypotheses']
            if round_validation_summaries else 0
        ),
        'statistically_validated_hypotheses': (
            round_validation_summaries[0]['statistically_validated_hypotheses']
            if round_validation_summaries else 0
        ),
        'statistically_validated': len(pathways_list),
        'rounds': round_validation_summaries,
        'by_database': {
            category: {
                'initial_hypotheses': initial_hypotheses_by_database.get(category, 0),
                'statistically_validated': validated_by_database.get(category, 0)
            }
            for category in ['GO:BP', 'GO:MF', 'GO:CC', 'KEGG', 'REAC']
        }
    }
    
    # Category distribution
    cat_dist = {}
    for p in pathways_list:
        cat = p['category']
        cat_dist[cat] = cat_dist.get(cat, 0) + 1
    
    dist_str = ", ".join([f"{cat}: {count}" for cat, count in sorted(cat_dist.items())])
    session.add_message("system", 
        f"✅ **Multiple Runs Complete**: {len(pathways_list)} pathways | {dist_str}")
    
    return pathways_list


def display_iteration_stats(session, iteration, category_stats, retained_count, 
                           new_predictions, matched_count, fdr_count):
    """Display generation, matching and statistical-validation counts by round."""
    stats_rows = []
    total_retained = 0
    total_new = 0
    total_matched = 0
    total_validated = 0
    total_matched_records = 0
    total_validated_records = 0
    
    for cat in ['GO:BP', 'GO:MF', 'GO:CC', 'KEGG', 'REAC']:
        stat = category_stats.get(cat, {'predicted': 0, 'matched': 0, 'fdr_filtered': 0, 
                                        'new_matched': 0, 'new_fdr': 0})
        
        # For iteration 1: retained = 0, For iteration 2-3: show retained
        if iteration == 1:
            cat_retained = 0
        else:
            # Count how many retained pathways are in this category
            cat_retained = sum(1 for p in session.retained_pathways 
                              if p.get('source') == cat)
        
        cat_new = stat['predicted']
        cat_total = cat_retained + cat_new
        if iteration == 1:
            cat_matched = stat.get('matched', 0)
            cat_validated = stat.get('fdr_filtered', 0)
            matched_records = stat.get('matched_records', cat_matched)
            validated_records = stat.get('fdr_records', cat_validated)
        else:
            cat_matched = stat.get('new_matched', 0)
            cat_validated = stat.get('new_fdr', 0)
            matched_records = stat.get('new_matched_records', cat_matched)
            validated_records = stat.get('new_fdr_records', cat_validated)

        match_rate = (cat_matched / cat_new * 100) if cat_new > 0 else 0
        validation_rate = hypothesis_validation_rate(cat_validated, cat_matched)
        
        stats_rows.append({
            'category': cat,
            'retained': cat_retained,
            'new_gen': cat_new,
            'match': cat_matched,
            'match_rate': f"{match_rate:.0f}%",
            'validated': cat_validated,
            'validation_rate': f"{validation_rate:.0f}%",
            'term_matches': f"{validated_records}/{matched_records}",
        })
        
        total_retained += cat_retained
        total_new += cat_new
        total_matched += cat_matched
        total_validated += cat_validated
        total_matched_records += matched_records
        total_validated_records += validated_records
    
    match_label = 'Initial matched hypotheses' if iteration == 1 else 'Newly matched hypotheses'
    validated_label = 'Initial statistically validated hypotheses' if iteration == 1 else 'Newly statistically validated hypotheses'
    rate_label = 'Validation rate'

    stats_html = f'''<div class="stats-container">
    <h4><svg class="ph" aria-hidden="true" focusable="false"><use href="#ph-chart-bar"></use></svg> Round {iteration}/2 Statistics ({'Initial Prompt' if iteration == 1 else 'Refined Prompt'})</h4>
    <table class="pathway-table stats-table">
        <thead>
            <tr>
                <th>Category</th>
                <th>Retained pathways</th>
                <th>{'Initial' if iteration == 1 else 'New'} hypotheses</th>
                <th>{match_label}</th>
                <th>Match rate</th>
                <th>{validated_label}</th>
                <th>{rate_label}</th>
            </tr>
        </thead>
        <tbody>'''
    
    for row in stats_rows:
        stats_html += f'''
            <tr>
                <td><span class="category-badge {row['category'].replace(':', '-')}">{row['category']}</span></td>
                <td>{row['retained']}</td>
                <td>{row['new_gen']}</td>
                <td><strong>{row['match']}</strong></td>
                <td>{row['match_rate']}</td>
                <td><strong>{row['validated']}</strong></td>
                <td>{row['validation_rate']}</td>
            </tr>'''

    validation_rate = hypothesis_validation_rate(total_validated, total_matched)
    stats_html += f'''
        </tbody>
    </table>
    <div class="stats-summary">
        <strong>Round {iteration}/2: {total_new} generated → {total_matched} matched → {total_validated} statistically validated ({validation_rate:.1f}% of matched hypotheses).</strong>
    </div>
    </div>'''
    
    session.add_message("system", stats_html)

    return {
        'round': int(iteration),
        'generated_hypotheses': int(total_new),
        'matched_hypotheses': int(total_matched),
        'statistically_validated_hypotheses': int(total_validated),
        'validation_rate': float(validation_rate),
        'matched_enrichment_records': int(total_matched_records),
        'statistically_validated_enrichment_records': int(total_validated_records),
    }



def convert_pathways_to_output_format(
    pathways_df,
    disease_name='the selected disease',
    input_genes=None,
    progress=None,
    model=None,
):
    """Convert DataFrame to output list format."""
    import math
    
    pathways_list = []
    
    # Select balanced pathways across categories
    categories_order = ['GO:BP', 'GO:MF', 'GO:CC', 'KEGG', 'REAC']
    per_category = {}
    
    for cat in categories_order:
        cat_df = pathways_df[pathways_df['source'] == cat] if 'source' in pathways_df.columns else pd.DataFrame()
        per_category[cat] = cat_df
    
    # Select top pathways from each category (balanced)
    pathways_per_cat = 4  # 4 per category = 20 total
    selected_rows = []
    
    for cat in categories_order:
        cat_df = per_category.get(cat, pd.DataFrame())
        if not cat_df.empty:
            selected_rows.extend(cat_df.head(pathways_per_cat).to_dict('records'))
    
    # If not enough, add more from any category
    remaining = 20 - len(selected_rows)
    if remaining > 0 and not pathways_df.empty:
        already_selected = set(r.get('name', '') for r in selected_rows)
        for _, row in pathways_df.iterrows():
            if row.get('name', '') not in already_selected:
                selected_rows.append(row.to_dict())
                if len(selected_rows) >= 20:
                    break
    
    # Convert to output format
    rank = 1
    for row in selected_rows[:20]:
        p_val = row.get('p_value', 0.05)
        # Inverted formula: lower p-values give higher scores (0-100 scale)
        # -log10(p_val) gives the significance, scaled to 0-100
        score = min(100, max(0, -10 * math.log10(float(p_val) + 1e-300)))
        
        # Extract PMIDs from literature
        literature = row.get('related_literature', []) if isinstance(row.get('related_literature'), list) else []
        pmid_list = []
        for lit in literature[:5]:
            if isinstance(lit, dict):
                pmid = lit.get('pmid', lit.get('PMID', ''))
                if pmid:
                    pmid_list.append(str(pmid))
        
        # Use the model interpretation when available; otherwise emit a
        # transparent three-part fallback instead of an empty section.
        disease_connection = row.get('disease_connection', '')
        raw_original_desc = row.get('description', '')
        original_desc = '' if pd.isna(raw_original_desc) else clean_pathway_definition(raw_original_desc)
        intersection_genes = (
            [str(gene).strip() for gene in row.get('intersections', []) if str(gene).strip()]
            if isinstance(row.get('intersections'), list)
            else []
        )
        if not disease_connection:
            disease_connection = fallback_disease_interpretation(
                row.get('name', 'Unknown'),
                original_desc,
                intersection_genes,
                disease_name,
                literature,
            )
        final_description = disease_connection

        pathways_list.append({
            "name": row.get('name', 'Unknown'),
            "pathway_id": get_pathway_identifier(row),
            "native": get_pathway_identifier(row),
            "p_value": float(p_val),
            "score": round(score, 1),
            "category": row.get('source', 'GO:BP'),
            "genes": ','.join(intersection_genes) if intersection_genes else str(row.get('intersection_size', 0)),
            "intersection_genes": intersection_genes,
            "intersection_size": int(row.get('intersection_size', len(intersection_genes))),
            "term_size": int(row.get('term_size', 0) or 0),
            "query_size": int(row.get('query_size', 0) or 0),
            "pathway_description": original_desc,
            "disease_interpretation": disease_connection,
            "description": final_description,  # Use disease connection or original
            "gpt_rank": rank,
            "gpt_predicted": row.get('gpt_validated', False),
            "literature": literature[:5],
            "pmids": pmid_list
        })
        rank += 1

    # Iterative mode now uses the same post-FDR pathway-level context contract
    # as the default single-shot path.  The helper is deliberately called only
    # after the final two-round merge and balanced selection, so context is not
    # generated for hypotheses that do not appear in the result.
    context_kwargs = {'genes': input_genes, 'progress': progress}
    narrative_kwargs = {'progress': progress}
    if model:
        context_kwargs['model'] = model
        narrative_kwargs['model'] = model
    cell_context_module.attach_cell_context(
        pathways_list,
        disease_name,
        **context_kwargs,
    )
    cell_context_module.attach_cell_context_evidence(
        pathways_list,
        disease_name,
        genes=input_genes,
        progress=progress,
    )
    attach_pathway_narratives(pathways_list, disease_name, **narrative_kwargs)
    external_evidence.attach_external_evidence_genes(
        pathways_list,
        input_genes=input_genes,
    )

    return pathways_list


# ============================================================================
# HISTORY API ENDPOINTS
# ============================================================================

@app.route('/api/history', methods=['GET'])
def get_history():
    """Get all run history entries (metadata only, no full results)."""
    owner_id = get_request_owner_id()
    history = [
        h for h in load_history()
        if not AUTH_ENABLED or h.get('owner_id') == owner_id
    ]
    entries = []
    for h in history:
        entries.append({
            'session_id': h.get('session_id'),
            'disease': h.get('disease'),
            'disease_name': h.get('disease_name'),
            'gene_count': h.get('gene_count', len(h.get('genes', []))),
            'genes_preview': ', '.join(h.get('genes', [])[:5]) + ('...' if len(h.get('genes', [])) > 5 else ''),
            'model': h.get('model', 'gpt-5.1'),
            'status': h.get('status', 'unknown'),
            'created_at': h.get('created_at'),
            'completed_at': h.get('completed_at')
        })
    return jsonify({"history": entries, "total": len(entries)})

@app.route('/api/history/<session_id>', methods=['GET'])
def get_history_entry(session_id):
    """Get full details of a history entry."""
    owner_id = get_request_owner_id()
    history = load_history()
    for h in history:
        if (
            h.get('session_id') == session_id
            and (not AUTH_ENABLED or h.get('owner_id') == owner_id)
        ):
            return jsonify(h)
    return jsonify({"error": "Not found"}), 404

@app.route('/api/history/<session_id>', methods=['DELETE'])
def delete_history_entry(session_id):
    """Delete a single history entry."""
    owner_id = get_request_owner_id()
    history = load_history()
    original_len = len(history)
    history = [
        h for h in history
        if not (
            h.get('session_id') == session_id
            and (not AUTH_ENABLED or h.get('owner_id') == owner_id)
        )
    ]
    if len(history) == original_len:
        return jsonify({"error": "Not found"}), 404
    save_history(history)
    return jsonify({"success": True, "remaining": len(history)})

@app.route('/api/history', methods=['DELETE'])
def clear_history():
    """Clear only the current user's history."""
    owner_id = get_request_owner_id()
    history = load_history()
    if AUTH_ENABLED:
        retained = [h for h in history if h.get('owner_id') != owner_id]
    else:
        retained = []
    removed = len(history) - len(retained)
    save_history(retained)
    return jsonify({"success": True, "removed": removed})

# ============================================================================
# MAIN
# ============================================================================

if __name__ == '__main__':
    print("=" * 60)
    print("🧬 Gene Pathway Analysis Web Application")
    print("=" * 60)
    print(f"Real Analysis: {'✅ Available' if REAL_ANALYSIS_AVAILABLE else '❌ Demo Mode'}")
    print(f"GPT Model: {GPT_MODEL}")
    print(f"OpenAI: {'✅ Configured' if OPENAI_API_KEY else '⚠️ Not set'}")
    print(f"Entrez: {'✅ Configured' if ENTREZ_EMAIL else '⚠️ Not set'}")
    print("=" * 60)
    port = int(os.environ.get('PORT', '5000'))
    print(f"Open http://0.0.0.0:{port} in your browser")
    print("=" * 60)
    
    app.run(host='0.0.0.0', port=port, debug=False, threaded=True)
