#!/usr/bin/env python3
"""Restore archived functional-cluster members lost by the old driver filter.

Older completed results removed every narrative driver from the structured
``clusters`` array even when the prose explicitly placed that driver in a
functional cluster.  The rendering code is now fixed, but those already-saved
JSON records still need a data migration.

This migration is intentionally conservative: the archived prose is the
authority.  A missing driver is restored only when a sentence explicitly
enumerates it as a cluster/group/module member (for example ``formed by X and
Y``) or says that it ``anchors`` a named cluster.  Merely mentioning a driver
near a cluster is not enough.
"""

import argparse
import json
import re
from pathlib import Path


DISEASE_CODES = ('AD', 'IBD', 'MS', 'T2D', 'PD', 'RA', 'ALS')
GROUP_WORD = r'(?:cluster|group|module)'
MEMBERSHIP_VERB = (
    r'(?:includes?|including|comprises?|comprising|contains?|containing|'
    r'encompasses?|encompassing|consists?\s+of|consisting\s+of|'
    r'is\s+formed\s+by|formed\s+by|is\s+made\s+up\s+of|made\s+up\s+of|'
    r'is\s+exemplified\s+by|exemplified\s+by|is\s+represented\s+by|'
    r'represented\s+by)'
)
WEAK_LABEL_WORDS = {
    'a', 'an', 'the', 'first', 'second', 'third', 'fourth', 'final', 'finally',
    'another', 'additional', 'remaining', 'smaller', 'larger', 'notable', 'one',
    'closely', 'allied', 'more', 'oriented',
}
LABEL_STOPWORDS = WEAK_LABEL_WORDS | {'cluster', 'group', 'module', 'functional'}


def load_json(path):
    with path.open(encoding='utf-8') as handle:
        return json.load(handle)


def dump_json(path, payload):
    with path.open('w', encoding='utf-8') as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write('\n')


def _sentences(paragraphs):
    text = ' '.join(str(item).strip() for item in paragraphs or [] if str(item).strip())
    return [item.strip() for item in re.split(r'(?<=[.!?])\s+', text) if item.strip()]


def _symbol_pattern(symbol):
    return rf'(?<![A-Za-z0-9]){re.escape(symbol)}(?![A-Za-z0-9])'


def mentioned_symbols(text, symbols):
    """Return supplied symbols mentioned in *text*, preserving text order."""
    hits = []
    for symbol in symbols or []:
        clean = str(symbol).strip()
        if not clean:
            continue
        match = re.search(_symbol_pattern(clean), str(text), flags=re.IGNORECASE)
        if match:
            hits.append((match.start(), clean))
    return [symbol for _, symbol in sorted(hits)]


def _trim_member_span(value):
    """Stop an enumerated member list before its explanatory clause."""
    text = str(value or '')[:500]
    text = re.split(r'[.;:]', text, maxsplit=1)[0]
    text = re.split(
        r',\s*(?:which|who|whose|where|both|each|all\s+of\s+which|thereby|thus|'
        r'highlighting|indicating|reflecting|supporting|suggesting|underscoring|'
        r'making|acting|providing|linking|reinforcing|demonstrating|illustrating|'
        r'further)\b',
        text,
        maxsplit=1,
        flags=re.IGNORECASE,
    )[0]
    text = re.split(
        r'\s+(?:supports?|encodes?|functions?|acts?|provides?|links?|integrates?|'
        r'maintains?|helps?|serves?|contributes?|participates?|underlies?|represents?|'
        r'indicates?|suggests?|reinforces?|underscores?|highlights?|mediates?|promotes?|'
        r'facilitates?|controls?|modulates?|recruits?|positions?|stabilizes?|translates?|'
        r'governs?|is|are)\b',
        text,
        maxsplit=1,
        flags=re.IGNORECASE,
    )[0]
    # Parenthetical member lists often close immediately before the sentence
    # starts explaining what the group does.
    if ')' in text and '(' not in text.split(')', 1)[1]:
        text = text.split(')', 1)[0] + ')'
    return text.strip(' ,:')


def _clean_label(value):
    label = str(value or '').strip(' \t\n\r,:;()\"\'“”')
    label = re.sub(r'^(?:finally|within\s+[^,]+|among\s+[^,]+),\s*', '', label, flags=re.I)
    label = re.sub(r'^(?:a|an|the|one|another)\s+', '', label, flags=re.I)
    label = re.sub(
        r'^(?:first|second|third|fourth|final)\s*,?\s*'
        r'(?:(?:closely\s+allied|smaller|larger|more)\s*,?\s*)?',
        '',
        label,
        flags=re.I,
    )
    return label.strip(' \t\n\r,:;()\"\'“”')


def _label_tokens(value):
    return {
        token for token in re.findall(r'[A-Za-z0-9]+', str(value or '').lower())
        if token not in LABEL_STOPWORDS and len(token) > 2
    }


def _usable_new_label(value):
    tokens = _label_tokens(value)
    return bool(tokens and not tokens.issubset(WEAK_LABEL_WORDS))


def _label_with_group_type(label, evidence):
    """Preserve the prose's cluster/group/module suffix on recreated labels."""
    clean = str(label or '').strip()
    if re.search(rf'\b{GROUP_WORD}\s*$', clean, flags=re.IGNORECASE):
        return clean
    types = re.findall(r'\b(cluster|group|module)\b', str(evidence or ''), flags=re.IGNORECASE)
    return f"{clean} {types[-1].lower() if types else 'cluster'}".strip()


def extract_explicit_groups(sentence, intersection_genes):
    """Extract explicit group labels and enumerated members from one sentence.

    The result is deliberately narrower than general NLP.  It covers the
    sentence forms emitted by the narrative prompt while rejecting nearby
    mechanistic references such as "this cluster recruits PRKDC".
    """
    sentence = str(sentence or '').strip()
    groups = []

    # "GRN anchors a microglial ... cluster".  The anchor is itself a member;
    # the following explanation is not treated as a member list.
    anchor_re = re.compile(
        rf'(?P<gene>[A-Za-z0-9-]+)\s+(?:also\s+)?anchors?\s+'
        rf'(?:a|an|the)\s+(?P<label>[^,;:.]{{2,140}}?)\s+{GROUP_WORD}\b',
        flags=re.IGNORECASE,
    )
    for match in anchor_re.finditer(sentence):
        gene = mentioned_symbols(match.group('gene'), intersection_genes)
        if gene:
            groups.append({
                'label': _clean_label(match.group('label')),
                'genes': gene,
                'evidence': match.group(0),
                'kind': 'anchor',
            })

    # "A proteolytic ... cluster is formed by MMP8 and MMP9" and variants.
    named_re = re.compile(
        rf'(?P<label>(?:[^,;:.]|,(?!\s*(?:which|who|where))){{1,180}}?)\s+'
        rf'{GROUP_WORD}\s*(?:,\s*)?{MEMBERSHIP_VERB}\s+(?P<members>.+)',
        flags=re.IGNORECASE,
    )
    for match in named_re.finditer(sentence):
        member_span = _trim_member_span(match.group('members'))
        genes = mentioned_symbols(member_span, intersection_genes)
        if genes:
            groups.append({
                'label': _clean_label(match.group('label')),
                'genes': genes,
                'evidence': match.group(0)[:500],
                'kind': 'enumeration',
            })

    # "A basal cytoskeletal cluster (KRT15, KRT5 and KRT14) ...".
    parenthetical_re = re.compile(
        rf'(?P<label>[^,;:.()]{{1,140}}?)\s+{GROUP_WORD}\s*'
        rf'\((?P<members>[^)]{{1,300}})\)',
        flags=re.IGNORECASE,
    )
    for match in parenthetical_re.finditer(sentence):
        genes = mentioned_symbols(match.group('members'), intersection_genes)
        if genes:
            groups.append({
                'label': _clean_label(match.group('label')),
                'genes': genes,
                'evidence': match.group(0),
                'kind': 'parenthetical',
            })

    # "PRMT1, PRMT5 and PRMT6 constitute a group ..." or "X and Y form a
    # cluster".  Only the text before the grouping verb supplies members.
    leading_re = re.compile(
        rf'(?P<members>(?:[A-Za-z0-9-]+(?:\s*,\s*|\s+(?:and|together\s+with)\s+))+'
        rf'[A-Za-z0-9-]+)\s+(?:form|forms|constitute|constitutes|make\s+up)\s+'
        rf'(?:a|an|the)?\s*(?P<label>[^,;:.]{{0,100}}?)\s*{GROUP_WORD}\b',
        flags=re.IGNORECASE,
    )
    for match in leading_re.finditer(sentence):
        genes = mentioned_symbols(match.group('members'), intersection_genes)
        if genes:
            groups.append({
                'label': _clean_label(match.group('label')),
                'genes': genes,
                'evidence': match.group(0),
                'kind': 'leading-list',
            })

    # "CTSZ, CTSH and CTSD cluster functionally as lysosomal proteases".
    functional_re = re.compile(
        rf'(?P<members>(?:[A-Za-z0-9-]+(?:\s*,\s*|\s+and\s+))+'
        rf'[A-Za-z0-9-]+)\s+cluster\s+functionally\s+as\s+'
        rf'(?P<label>[^,;:.]{{1,140}})',
        flags=re.IGNORECASE,
    )
    for match in functional_re.finditer(sentence):
        genes = mentioned_symbols(match.group('members'), intersection_genes)
        if genes:
            groups.append({
                'label': _clean_label(match.group('label')),
                'genes': genes,
                'evidence': match.group(0),
                'kind': 'functional-list',
            })

    # Avoid duplicate captures of the same statement.
    unique = []
    seen = set()
    for group in groups:
        key = (group['label'].lower(), tuple(gene.upper() for gene in group['genes']))
        if key not in seen:
            seen.add(key)
            unique.append(group)
    return unique


def _best_existing_cluster(group, clusters):
    group_genes = {gene.upper() for gene in group['genes']}
    group_tokens = _label_tokens(group['label'])
    ranked = []
    for index, cluster in enumerate(clusters):
        cluster_genes = {
            str(gene).strip().upper() for gene in cluster.get('genes') or []
            if str(gene).strip()
        }
        overlap = len(group_genes & cluster_genes)
        context_overlap = len(mentioned_symbols(group.get('sentence'), cluster_genes))
        tokens = _label_tokens(cluster.get('label'))
        label_score = len(group_tokens & tokens) / max(1, len(group_tokens | tokens))
        ranked.append((overlap, context_overlap, label_score, -index, index))
    if not ranked:
        return None
    overlap, context_overlap, label_score, _, index = max(ranked)
    if label_score >= 0.35 or overlap >= 2 or context_overlap >= 2:
        return index
    # Ordinal-only labels such as "first" and "second, closely allied" carry
    # no semantic name.  For those only, non-driver member overlap safely
    # identifies the structured cluster intended by the prose.
    if overlap > 0 and not _usable_new_label(group['label']):
        return index
    return None


def backfill_pathway(pathway):
    """Backfill one pathway in place and return a structured change report."""
    narrative = pathway.get('pathway_narrative') or {}
    drivers = [str(gene).strip() for gene in narrative.get('driver_genes') or [] if str(gene).strip()]
    clusters = narrative.get('clusters') or []
    intersection = [
        str(gene).strip() for gene in pathway.get('intersection_genes') or [] if str(gene).strip()
    ]
    clustered = {
        str(gene).strip().upper() for cluster in clusters for gene in cluster.get('genes') or []
        if str(gene).strip()
    }
    missing = {gene.upper(): gene for gene in drivers if gene.upper() not in clustered}
    report = {'restored': [], 'created': [], 'unresolved': []}
    if not missing:
        return report

    candidates = []
    for sentence in _sentences(narrative.get('paragraphs')):
        for group in extract_explicit_groups(sentence, intersection):
            group['sentence'] = sentence
            eligible = [
                gene for gene in group['genes']
                if gene.upper() in missing
                and not re.search(
                    rf'{_symbol_pattern(gene)}[’\']s\s+(?:network\s+)?partners?\b',
                    group['evidence'],
                    flags=re.IGNORECASE,
                )
            ]
            if eligible:
                candidate = dict(group)
                candidate['eligible_genes'] = eligible
                candidates.append(candidate)

    priority = {
        'enumeration': 0,
        'parenthetical': 0,
        'anchor': 0,
        'functional-list': 1,
        'leading-list': 2,
    }
    candidates.sort(key=lambda item: priority.get(item.get('kind'), 9))

    claimed = set()
    for group in candidates:
        genes = [gene for gene in group['eligible_genes'] if gene.upper() not in claimed]
        if not genes:
            continue
        target = _best_existing_cluster(group, clusters)
        if target is not None:
            target_genes = clusters[target].setdefault('genes', [])
            present = {str(gene).strip().upper() for gene in target_genes}
            added = []
            for gene in genes:
                if gene.upper() not in present:
                    target_genes.append(gene)
                    present.add(gene.upper())
                    claimed.add(gene.upper())
                    added.append(gene)
            if added:
                report['restored'].append({
                    'label': clusters[target].get('label'),
                    'genes': added,
                    'evidence': group['evidence'],
                })
        elif _usable_new_label(group['label']):
            # A wholly driver-only group was deleted by the old filter.  Keep
            # only explicitly enumerated drivers here; other non-driver members
            # already belong to their existing structured cluster, if any.
            label = _label_with_group_type(group['label'], group['evidence'])
            clusters.append({'label': label, 'genes': list(genes)})
            claimed.update(gene.upper() for gene in genes)
            report['created'].append({
                'label': label,
                'genes': list(genes),
                'evidence': group['evidence'],
            })

    for upper, gene in missing.items():
        if upper not in claimed:
            report['unresolved'].append(gene)
    return report


def migrate_payload(payload, code=''):
    """Backfill every pathway in a server-export payload in place."""
    changes = []
    for pathway in payload.get('pathways') or []:
        report = backfill_pathway(pathway)
        if report['restored'] or report['created']:
            changes.append({
                'disease': code,
                'pathway_id': pathway.get('pathway_id') or pathway.get('native'),
                **report,
            })
    return changes


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--exports-dir', type=Path, default=Path('server_exports'))
    parser.add_argument('--apply', action='store_true', help='write changes; default is dry-run')
    parser.add_argument('--verbose', action='store_true')
    args = parser.parse_args()

    all_changes = []
    unresolved = 0
    for code in DISEASE_CODES:
        path = args.exports_dir / f'{code}.json'
        payload = load_json(path)
        changes = migrate_payload(payload, code)
        all_changes.extend(changes)
        unresolved += sum(len(item['unresolved']) for item in changes)
        if args.apply and changes:
            dump_json(path, payload)

    restored = sum(
        len(entry['genes']) for item in all_changes for entry in item['restored']
    )
    created = sum(len(item['created']) for item in all_changes)
    mode = 'APPLIED' if args.apply else 'DRY RUN'
    print(
        f'{mode}: {len(all_changes)} pathways changed; {restored} memberships restored; '
        f'{created} clusters recreated; {unresolved} other drivers intentionally unresolved.'
    )
    if args.verbose:
        print(json.dumps(all_changes, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
