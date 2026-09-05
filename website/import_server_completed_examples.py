#!/usr/bin/env python3
"""Merge server-exported narrative retries into the bundled completed examples.

Expected input files are ``CODE.json`` for AD, IBD, MS, T2D, PD, RA and ALS.
The server export is authoritative for pathway-level evidence; archive-only run
summaries and stable completed-example session IDs are retained.
"""

import argparse
import json
from pathlib import Path

from archive_lock import apply_pinned_ad, sync_bundled_archives


DISEASE_CODES = ('AD', 'IBD', 'MS', 'T2D', 'PD', 'RA', 'ALS')


def pathway_key(pathway):
    return str(
        pathway.get('pathway_id')
        or pathway.get('native')
        or pathway.get('name')
        or ''
    ).strip()


def load_json(path):
    with path.open(encoding='utf-8') as handle:
        return json.load(handle)


def dump_json(path, payload):
    with path.open('w', encoding='utf-8') as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write('\n')


def merge_example(example, exported, code):
    archived = example['result'].get('pathways') or []
    fresh = exported.get('pathways') or []
    fresh_by_key = {pathway_key(pathway): pathway for pathway in fresh}
    if len(fresh_by_key) != len(fresh):
        raise ValueError(f'{code}: duplicate or missing pathway identifiers in server export')

    merged = []
    for pathway in archived:
        key = pathway_key(pathway)
        if key not in fresh_by_key:
            raise ValueError(f'{code}: server export is missing {key!r}')
        record = dict(pathway)
        record.update(fresh_by_key[key])
        genes = [str(gene).strip() for gene in (record.get('intersection_genes') or []) if str(gene).strip()]
        record['intersection_size'] = len(genes) or int(record.get('intersection_size') or 0)
        narrative = record.get('pathway_narrative') or {}
        if narrative.get('generated') is not True:
            raise ValueError(
                f"{code}: {key} still uses fallback ({narrative.get('fallback_reason', 'unknown reason')})"
            )
        if not (record.get('pmids') or []):
            raise ValueError(f'{code}: {key} has no PubMed evidence')
        if not str(record.get('cell_context') or '').strip():
            raise ValueError(f'{code}: {key} has no cell/tissue context')
        merged.append(record)

    if len(merged) != len(fresh):
        unexpected = sorted(set(fresh_by_key) - {pathway_key(item) for item in archived})
        raise ValueError(f'{code}: unexpected server pathways: {unexpected}')

    example['result']['pathways'] = merged
    example['pathway_count'] = len(merged)
    analysis_date = (exported.get('metadata') or {}).get('analysis_date')
    if analysis_date:
        example['result']['completed_at'] = analysis_date


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--exports-dir', type=Path, default=Path('server_exports'))
    parser.add_argument('--web-app-dir', type=Path, default=Path('web_app'))
    parser.add_argument('--pinned-ad', type=Path, default=Path('web_app/pinned_ad_example.json'))
    parser.add_argument('--replace-pinned-ad', action='store_true',
                        help='explicitly allow a server export to replace the pinned AD archive')
    args = parser.parse_args()

    completed_json = args.web_app_dir / 'offline_completed_examples.json'
    payload = load_json(completed_json)
    examples = payload.get('examples') or {}
    update_codes = DISEASE_CODES if args.replace_pinned_ad else DISEASE_CODES[1:]
    for code in update_codes:
        if code not in examples:
            raise ValueError(f'archive is missing disease {code}')
        export_path = args.exports_dir / f'{code}.json'
        if not export_path.exists():
            raise FileNotFoundError(export_path)
        merge_example(examples[code], load_json(export_path), code)

    if not args.replace_pinned_ad:
        apply_pinned_ad(payload, args.pinned_ad)
        print('AD retained pinned module 6 archive (140 genes, 16 pathways)')

    sync_bundled_archives(args.web_app_dir, payload)

    total = sum(len(example['result']['pathways']) for example in examples.values())
    print(f'Updated {len(update_codes)} server-export diseases and {total} archived pathways.')


if __name__ == '__main__':
    main()
