#!/usr/bin/env python3
"""Build web_app/offline_completed_examples.js from real pipeline runs.

Reads the aggregated output of the iterative-feedback pipeline
(``iterative_feedback_<CODE>/<CODE>_aggregated_*/final_aggregated_pathways.csv``)
and converts one network module per disease into the archived-result format the
web application ships, then optionally writes the docx-style narrative for each
pathway using the same generator the live server uses.

Run it from the repository root with the API key exported:

    export OPENAI_API_KEY=sk-...
    python build_completed_examples.py --source ../.. --out web_app/offline_completed_examples.js

Useful flags:

    --dry-run             convert only; skip narrative generation and the
                          Ensembl->symbol lookup (no network, no API cost)
    --pubmed              attach literature. Whatever the original run already
                          retrieved is reused first; only the remainder is
                          queried against PubMed. Needs ENTREZ_EMAIL set.
    --diseases AD,T2D     restrict the run
    --modules T2D=83      override the automatic module choice
    --max-pathways 20     how many ranked pathways to keep per disease
    --narrative-top 12    how many of those get a generated narrative

Literature
----------
The aggregated CSV declares a related_literature column but never fills it, so
the PubMed hits those runs paid for survive only in the per-module files.
--pubmed reads those back first and queries NCBI only for what is genuinely
missing, caching every answer so a rebuild costs nothing.

Module choice
-------------
By default each disease uses the module with the most FDR-significant pathways,
breaking ties on the number of source databases covered and then on module size.
That maximises what the archived example can actually demonstrate. Print the
choice with --list-modules before committing to it, and pin anything you
disagree with through --modules.
"""

from __future__ import annotations

import argparse
import ast
import collections
import csv
import glob
import json
import os
import re
import sys

from archive_lock import apply_pinned_ad, sync_bundled_archives

csv.field_size_limit(10 ** 8)

DISEASE_TITLES = {
    'AD': ("Alzheimer's disease", "Alzheimer's Disease"),
    'ALS': ('Amyotrophic lateral sclerosis', 'Amyotrophic Lateral Sclerosis'),
    'IBD': ('Inflammatory bowel disease', 'Inflammatory Bowel Disease'),
    'MS': ('Multiple sclerosis', 'Multiple Sclerosis'),
    'PD': ("Parkinson's disease", "Parkinson's Disease"),
    'RA': ('Rheumatoid arthritis', 'Rheumatoid Arthritis'),
    'T2D': ('Type 2 diabetes', 'Type 2 Diabetes'),
}

DATABASE_ORDER = ['GO:BP', 'GO:MF', 'GO:CC', 'KEGG', 'REAC']
FDR_THRESHOLD = 0.05


# ---------------------------------------------------------------------------
# Reading the pipeline output
# ---------------------------------------------------------------------------

def find_aggregated_csv(source_root, code):
    """Return the newest aggregated CSV for one disease, or None."""
    pattern = os.path.join(
        source_root, f'iterative_feedback_{code}', f'{code}_aggregated_*',
        'final_aggregated_pathways.csv',
    )
    matches = sorted(glob.glob(pattern))
    return matches[-1] if matches else None


def parse_float(value, default=None):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def parse_list(value):
    """The CSV stores Python list literals; fall back to an empty list."""
    text = str(value or '').strip()
    if not text or text in ('[]', 'nan'):
        return []
    try:
        parsed = ast.literal_eval(text)
    except (ValueError, SyntaxError):
        return []
    return list(parsed) if isinstance(parsed, (list, tuple)) else []


def load_rows(path):
    with open(path, encoding='utf-8') as handle:
        return list(csv.DictReader(handle))


def summarize_modules(rows):
    """Score every module so the most demonstrable one can be picked."""
    modules = collections.defaultdict(
        lambda: {'significant': 0, 'databases': set(), 'size': 0, 'total': 0}
    )
    for row in rows:
        module_id = str(row.get('module_id') or '').strip() or '?'
        entry = modules[module_id]
        entry['total'] += 1
        entry['size'] = max(entry['size'], int(parse_float(row.get('module_size'), 0) or 0))
        if (parse_float(row.get('p_value'), 1.0) or 1.0) < FDR_THRESHOLD:
            entry['significant'] += 1
            entry['databases'].add(row.get('source'))
    return modules


def choose_module(modules):
    ranked = sorted(
        modules.items(),
        key=lambda item: (
            -item[1]['significant'],
            -len(item[1]['databases']),
            -item[1]['size'],
        ),
    )
    return ranked[0][0] if ranked else None


# ---------------------------------------------------------------------------
# Ensembl -> HGNC symbol
# ---------------------------------------------------------------------------

class SymbolResolver:
    """Resolve Ensembl gene IDs to HGNC symbols, with an on-disk cache.

    The aggregated CSV stores intersections as Ensembl IDs. The interface and
    the narrative both talk about proteins by symbol, so the mapping has to
    happen here. g:Profiler's convert endpoint is used because the pipeline
    already depends on it; results are cached so repeat runs need no network.
    """

    def __init__(self, cache_path, enabled=True):
        self.cache_path = cache_path
        self.enabled = enabled
        self.cache = {}
        if cache_path and os.path.exists(cache_path):
            try:
                with open(cache_path, encoding='utf-8') as handle:
                    self.cache = json.load(handle)
            except (OSError, ValueError):
                self.cache = {}

    def resolve(self, ensembl_ids):
        unknown = [gid for gid in ensembl_ids if gid not in self.cache]
        if unknown and self.enabled:
            self._lookup(unknown)
        # An unresolved ID keeps its Ensembl form: the interface links those to
        # Ensembl, so nothing is lost and nothing is invented.
        return [self.cache.get(gid) or gid for gid in ensembl_ids]

    def _lookup(self, ensembl_ids):
        try:
            from gprofiler import GProfiler
        except ImportError:
            print('  ! gprofiler-official not installed; keeping Ensembl IDs', file=sys.stderr)
            self.enabled = False
            return
        try:
            profiler = GProfiler(return_dataframe=False)
            for start in range(0, len(ensembl_ids), 500):
                chunk = ensembl_ids[start:start + 500]
                for record in profiler.convert(
                    organism='hsapiens', query=chunk, target_namespace='ENTREZGENE_ACC'
                ):
                    incoming = record.get('incoming')
                    symbol = record.get('name')
                    if incoming and symbol and symbol not in ('None', 'nan'):
                        self.cache[incoming] = symbol
        except Exception as exc:  # network or service failure
            print(f'  ! symbol lookup failed ({str(exc)[:70]}); keeping Ensembl IDs', file=sys.stderr)
            self.enabled = False

    def save(self):
        if not self.cache_path:
            return
        try:
            with open(self.cache_path, 'w', encoding='utf-8') as handle:
                json.dump(self.cache, handle, indent=0, sort_keys=True)
        except OSError:
            pass


# ---------------------------------------------------------------------------
# Literature
# ---------------------------------------------------------------------------

LITERATURE_COLUMNS = ('literature_pmids', 'validated_publications')


def harvest_existing_literature(source_root, code):
    """Recover PubMed hits that the original run already paid for.

    The aggregated CSV creates a related_literature column but never fills it,
    so anything the run retrieved survives only in the per-module files. This
    reads those back before any new query is issued, keyed by pathway accession
    and, as a fallback, by pathway name.
    """
    harvested = {}
    pattern = os.path.join(source_root, f'iterative_feedback_{code}', '*', '*.csv')
    for path in glob.glob(pattern):
        name = os.path.basename(path)
        if not any(marker in name for marker in ('gpt_filtered_pathways', 'gpt_matched')):
            continue
        try:
            rows = load_rows(path)
        except (OSError, csv.Error):
            continue
        for row in rows:
            pmids = []
            for column in LITERATURE_COLUMNS:
                raw = str(row.get(column) or '').strip()
                if raw and raw not in ('[]', 'nan'):
                    pmids.extend(re.findall(r'\d{6,9}', raw))
            if not pmids:
                continue
            for key in (row.get('native'), row.get('name')):
                key = str(key or '').strip()
                if key:
                    harvested.setdefault(key, [])
                    for pmid in pmids:
                        if pmid not in harvested[key]:
                            harvested[key].append(pmid)
    return harvested


class LiteratureBackfill:
    """Attach pathway-disease literature to converted records.

    Order of preference: whatever the original run already retrieved, then a
    fresh PubMed query for the remainder. Results are cached on disk so a
    repeated build issues no new NCBI traffic.
    """

    def __init__(self, cache_path, harvested, enabled, max_results=5):
        self.cache_path = cache_path
        self.harvested = harvested or {}
        self.enabled = enabled
        self.max_results = max_results
        self.cache = {}
        self.stats = {'reused': 0, 'fetched': 0, 'empty': 0, 'failed': 0}
        if cache_path and os.path.exists(cache_path):
            try:
                with open(cache_path, encoding='utf-8') as handle:
                    self.cache = json.load(handle)
            except (OSError, ValueError):
                self.cache = {}

    def attach(self, record, disease_name):
        accession = record.get('pathway_id') or ''
        name = record.get('name') or ''

        reused = self.harvested.get(accession) or self.harvested.get(name)
        if reused:
            record['literature'] = [{'pmid': pmid, 'title': '', 'journal': '', 'year': ''}
                                    for pmid in reused[:self.max_results]]
            record['pmids'] = [pmid for pmid in reused[:self.max_results]]
            record['literature_provenance'] = 'recovered from the original run'
            self.stats['reused'] += 1
            return

        if not self.enabled:
            return

        key = f'{disease_name}||{name}'
        if key in self.cache:
            papers = self.cache[key]
        else:
            papers = self._search(name, disease_name)
            if papers is None:
                self.stats['failed'] += 1
                return
            self.cache[key] = papers

        if papers:
            record['literature'] = papers[:self.max_results]
            record['pmids'] = [str(paper.get('pmid')) for paper in papers[:self.max_results]]
            record['literature_provenance'] = 'retrieved by literature backfill'
            self.stats['fetched'] += 1
        else:
            self.stats['empty'] += 1

    def _search(self, pathway_name, disease_name):
        try:
            import pubmed_search
        except ImportError:
            print('  ! pubmed_search module not importable; skipping backfill', file=sys.stderr)
            self.enabled = False
            return None
        try:
            _summary, papers = pubmed_search.search_pubmed_for_pathway_standalone(
                pathway_name, disease_name, max_results=self.max_results
            )
            return papers or []
        except Exception as exc:
            print(f'  ! PubMed backfill failed for {pathway_name[:40]!r}: {str(exc)[:60]}', file=sys.stderr)
            return None

    def save(self):
        if not self.cache_path:
            return
        try:
            with open(self.cache_path, 'w', encoding='utf-8') as handle:
                json.dump(self.cache, handle, ensure_ascii=False, indent=0, sort_keys=True)
        except OSError:
            pass


# ---------------------------------------------------------------------------
# Conversion
# ---------------------------------------------------------------------------

def clean_definition(value):
    text = str(value or '').strip()
    text = re.sub(r'^\s*["“”]+|["“”]+\s*$', '', text).strip()
    text = re.sub(r'\s*\[(?:GOC|PMID|ISBN|Reactome|KEGG)[^\]]*\]\s*$', '', text).strip()
    return text


def build_pathway_records(rows, resolver, max_pathways):
    """Convert significant CSV rows into the web application's record shape."""
    significant = [
        row for row in rows
        if (parse_float(row.get('p_value'), 1.0) or 1.0) < FDR_THRESHOLD
    ]
    # Rank within database the way the interface groups them, then interleave so
    # the archive keeps every database represented instead of one dominating.
    by_database = collections.defaultdict(list)
    for row in significant:
        by_database[row.get('source') or 'Other'].append(row)
    for database in by_database:
        by_database[database].sort(
            key=lambda row: (
                parse_float(row.get('gpt_rank'), 9e9) or 9e9,
                parse_float(row.get('p_value'), 1.0) or 1.0,
            )
        )

    ordered = []
    depth = 0
    while len(ordered) < max_pathways:
        added = False
        for database in DATABASE_ORDER:
            bucket = by_database.get(database) or []
            if depth < len(bucket):
                ordered.append(bucket[depth])
                added = True
                if len(ordered) >= max_pathways:
                    break
        if not added:
            break
        depth += 1

    # Reporting tier. Writing guidance for GO results is to report the top three
    # terms per category in full and to add further terms only when they speak
    # directly to the phenotype. The tier drives narrative depth, not inclusion.
    tier_counter = collections.Counter()

    records = []
    for rank, row in enumerate(ordered, 1):
        ensembl = [str(g).strip() for g in parse_list(row.get('intersections')) if str(g).strip()]
        symbols = resolver.resolve(ensembl)
        p_value = parse_float(row.get('p_value'), 1.0) or 1.0
        declared_size = int(parse_float(row.get('intersection_size'), len(ensembl)) or len(ensembl))
        database = row.get('source') or 'Other'
        tier_counter[database] += 1
        tier = 'primary' if tier_counter[database] <= 3 else 'supporting'
        records.append({
            'name': row.get('name') or 'Unknown pathway',
            'pathway_id': row.get('native') or '',
            'native': row.get('native') or '',
            'source': row.get('source') or '',
            'category': row.get('source') or '',
            'p_value': p_value,
            'significant': True,
            'pathway_description': clean_definition(row.get('description')),
            'description': clean_definition(row.get('description')),
            'term_size': int(parse_float(row.get('term_size'), 0) or 0),
            'query_size': int(parse_float(row.get('query_size'), 0) or 0),
            # intersection_size is the enrichment fact: the count the P-value was
            # computed on. symbols is what survived Ensembl->symbol resolution.
            # Both are kept, and the gap is recorded, so no text can quote one
            # number while the gene list shows another.
            'intersection_size': declared_size,
            'resolved_symbol_count': len(symbols),
            'unresolved_gene_count': max(0, declared_size - len(symbols)),
            'intersection_genes': symbols,
            'intersection_gene_ids': ensembl,
            'genes': ','.join(symbols),
            'parents': [str(x).strip() for x in parse_list(row.get('parents')) if str(x).strip()],
            'reporting_tier': tier,
            'gpt_rank': rank,
            'gpt_predicted': str(row.get('gpt_predicted') or '').strip().lower() == 'true',
            # These runs carried no PubMed retrieval, so the literature evidence
            # dimension is genuinely empty rather than omitted.
            'literature': [],
            'pmids': [],
        })
    annotate_hierarchy(records)
    return records


def annotate_hierarchy(records):
    """Flag parent/child relationships that exist inside the retained set.

    GO is a directed acyclic graph: a broad parent term and one of its specific
    children can both reach significance off largely the same genes. Reporting
    them as two independent findings overstates the result, so each record
    carries the retained terms that sit directly above and below it.
    """
    by_id = {record['pathway_id']: record for record in records if record.get('pathway_id')}
    for record in records:
        parents_in_set = [pid for pid in record.get('parents') or [] if pid in by_id]
        record['hierarchy'] = {
            'parents_in_set': parents_in_set,
            'parent_names_in_set': [by_id[pid]['name'] for pid in parents_in_set],
            'children_in_set': [],
            'child_names_in_set': [],
        }
    for record in records:
        for parent_id in record['hierarchy']['parents_in_set']:
            parent = by_id[parent_id]
            parent['hierarchy']['children_in_set'].append(record['pathway_id'])
            parent['hierarchy']['child_names_in_set'].append(record['name'])


def build_example(code, csv_path, module_id, resolver, max_pathways, narrative_top, generate, literature=None):
    rows = [
        row for row in load_rows(csv_path)
        if str(row.get('module_id') or '').strip() == str(module_id)
    ]
    if not rows:
        return None

    title, disease_name = DISEASE_TITLES.get(code, (code, code))
    module_size = max(int(parse_float(row.get('module_size'), 0) or 0) for row in rows)
    records = build_pathway_records(rows, resolver, max_pathways)
    if not records:
        return None

    # Literature first: the narrative prompt reads attached titles, so the
    # backfill has to land before generation.
    if literature is not None:
        for record in records:
            literature.attach(record, disease_name)

    if generate:
        import pathway_narrative
        print(f'  generating narratives for the top {min(len(records), narrative_top)} pathways...')
        narratives = pathway_narrative.generate_pathway_narratives(
            records, disease_name, max_pathways=narrative_top
        )
        for record in records:
            payload = narratives.get(record['pathway_id'])
            if payload:
                record['pathway_narrative'] = payload

    databases = collections.Counter(record['source'] for record in records)
    return {
        'code': code,
        'title': title,
        'subtitle': f'Archived completed {code} result',
        'disease': disease_name,
        'module': f'{title} — module {module_id} (n={module_size})',
        'gene_count': module_size,
        'pathway_count': len(records),
        'session_id': f'run-{code.lower()}-module-{module_id}',
        'result': {
            'session_id': f'run-{code.lower()}-module-{module_id}',
            'disease': code,
            'disease_name': disease_name,
            'gene_count': module_size,
            'pathways': records,
            'run_summary': {
                'validation_status': 'Statistically validated',
                'fdr_threshold': FDR_THRESHOLD,
                'significant_pathways': len(records),
                'total_pathways': len(records),
                'categories_covered': len(databases),
                'literature_records': sum(len(record.get('literature') or []) for record in records),
                'gene_count': module_size,
            },
        },
    }


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--source', default='../..', help='directory holding the iterative_feedback_* folders')
    parser.add_argument('--out', default='web_app/offline_completed_examples.js')
    parser.add_argument('--diseases', default=','.join(DISEASE_TITLES))
    parser.add_argument('--modules', default='', help='pin modules, e.g. T2D=83,AD=105')
    parser.add_argument('--max-pathways', type=int, default=20)
    parser.add_argument('--narrative-top', type=int, default=12)
    parser.add_argument('--dry-run', action='store_true', help='no narrative generation, no symbol lookup')
    parser.add_argument('--list-modules', action='store_true', help='print module scores and exit')
    parser.add_argument('--symbol-cache', default='.ensembl_symbol_cache.json')
    parser.add_argument('--pubmed', action='store_true',
                        help='query PubMed for pathways the original run left without literature')
    parser.add_argument('--pubmed-cache', default='.pubmed_cache.json')
    parser.add_argument('--pubmed-max', type=int, default=5)
    parser.add_argument('--pinned-ad', default='web_app/pinned_ad_example.json',
                        help='canonical AD Featured/Completed example retained across rebuilds')
    parser.add_argument('--replace-pinned-ad', action='store_true',
                        help='explicitly allow this build to replace the pinned AD archive')
    args = parser.parse_args()

    codes = [code.strip().upper() for code in args.diseases.split(',') if code.strip()]
    pinned = {}
    for item in args.modules.split(','):
        if '=' in item:
            code, module_id = item.split('=', 1)
            pinned[code.strip().upper()] = module_id.strip()

    generate = not (args.dry_run or args.list_modules)
    if generate and not os.environ.get('OPENAI_API_KEY'):
        print('OPENAI_API_KEY is not set. Export it, or pass --dry-run to convert without narratives.')
        return 1

    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'web_app'))
    resolver = SymbolResolver(args.symbol_cache, enabled=not (args.dry_run or args.list_modules))

    if args.pubmed and not os.environ.get('ENTREZ_EMAIL'):
        print('ENTREZ_EMAIL is not set; NCBI requires it for programmatic access.')
        return 1

    examples = {}
    for code in codes:
        csv_path = find_aggregated_csv(args.source, code)
        if not csv_path:
            print(f'{code:5s} no aggregated CSV under {args.source}/iterative_feedback_{code}/ — skipped')
            continue
        rows = load_rows(csv_path)
        modules = summarize_modules(rows)

        if args.list_modules:
            ranked = sorted(
                modules.items(),
                key=lambda item: (-item[1]['significant'], -len(item[1]['databases']), -item[1]['size']),
            )[:5]
            print(f'{code:5s} {len(modules)} modules in {os.path.basename(os.path.dirname(csv_path))}')
            for module_id, entry in ranked:
                print(f'        module {module_id:>4s}  significant={entry["significant"]:3d}  '
                      f'databases={len(entry["databases"])}  size={entry["size"]}')
            continue

        module_id = pinned.get(code) or choose_module(modules)
        entry = modules.get(str(module_id), {})
        print(f'{code:5s} module {module_id} '
              f'({entry.get("significant", 0)} significant pathways, '
              f'{len(entry.get("databases", ()))} databases, n={entry.get("size", 0)})'
              f'{"  [pinned]" if code in pinned else ""}')

        harvested = harvest_existing_literature(args.source, code)
        if harvested:
            print(f'        recovered literature for {len(harvested)} pathway keys from the original run')
        literature = LiteratureBackfill(
            args.pubmed_cache, harvested,
            enabled=args.pubmed and not args.list_modules,
            max_results=args.pubmed_max,
        )

        example = build_example(
            code, csv_path, module_id, resolver,
            args.max_pathways, args.narrative_top, generate, literature,
        )
        literature.save()
        if any(literature.stats.values()):
            print(f'        literature: {literature.stats["reused"]} reused, '
                  f'{literature.stats["fetched"]} fetched, '
                  f'{literature.stats["empty"]} none found, '
                  f'{literature.stats["failed"]} failed')
        if example:
            examples[code] = example
        else:
            print(f'{code:5s} module {module_id} produced no significant pathways — skipped')

    if args.list_modules:
        return 0

    resolver.save()
    if not examples:
        print('No examples were built; the output file was left untouched.')
        return 1

    payload = {
        'default': 'AD' if 'AD' in examples else sorted(examples)[0],
        'examples': examples,
    }
    if 'AD' in codes and not args.replace_pinned_ad:
        apply_pinned_ad(payload, args.pinned_ad)
        print('AD    retained pinned module 6 archive (140 genes, 16 pathways)')

    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    out_path = os.path.abspath(args.out)
    if os.path.basename(out_path) == 'offline_completed_examples.js':
        sync_bundled_archives(os.path.dirname(out_path), payload)
    else:
        with open(out_path, 'w', encoding='utf-8') as handle:
            handle.write('window.OFFLINE_COMPLETED_EXAMPLES = ')
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write(';\n')

    narrated = sum(
        1 for example in examples.values()
        for record in example['result']['pathways']
        if record.get('pathway_narrative')
    )
    total = sum(len(example['result']['pathways']) for example in examples.values())
    size_mb = os.path.getsize(out_path) / 1e6
    print(f'\nWrote {args.out}: {len(examples)} diseases, {total} pathways, '
          f'{narrated} with a narrative, {size_mb:.1f} MB')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
