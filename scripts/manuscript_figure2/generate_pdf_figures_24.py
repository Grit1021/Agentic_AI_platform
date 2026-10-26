#!/usr/bin/env python
"""
Generate publication-quality PDF/PNG figures for the 24-disease validation analysis.

Outputs (saved to ../pdf/):
  1. nfdr_trend_composite.pdf/.png/.svg   — 5-panel composite (3 top + 2 bottom)
  2. gpt_fdr_performance_overview.pdf/.png/.svg — Zero-shot overview (box + stacked bar)

Data source: cross_disease_24_nfdr_metrics_v5.csv
"""

import os
import json
import textwrap
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from matplotlib.colors import to_rgba
from scipy.stats import gaussian_kde

# ── Paths ────────────────────────────────────────────────────────────────
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, "..", ".."))
RUN_ROOT = os.environ.get("BENCHMARK_RUN_ROOT", PROJECT_ROOT)
CSV_PATH = os.path.join(SCRIPT_DIR, "cross_disease_24_nfdr_metrics_v5.csv")
MODSIZE_CSV = os.path.join(SCRIPT_DIR, "nfdr_with_module_size_external.csv")
OUTPUT_DIR = os.environ.get("BENCHMARK_FIGURE2_OUTPUT_DIR", os.path.join(PROJECT_ROOT, "output", "figure2_consistent_current"))
# Per-(disease, module) GPT predictions + g:Profiler matched files (Panel 2D).
MEMBANK_DIR = os.path.join(RUN_ROOT, "result", "memory_bank_external")
os.makedirs(OUTPUT_DIR, exist_ok=True)

# ── Constants ────────────────────────────────────────────────────────────
DISEASES = ['AD', 'AF', 'AIT', 'ALS', 'AST', 'CAD', 'CD', 'CKD', 'COPD', 'CRC',
            'HCC', 'HF', 'HTN', 'IBD', 'MDD', 'MS', 'OSA', 'PD', 'PS', 'PSP',
            'RA', 'SLE', 'T2D', 'TB']

DISEASE_COLORS = {
    'AD': '#E94F37', 'ALS': '#8E44AD', 'AST': '#3F51B5', 'CAD': '#27AE60',
    'COPD': '#795548', 'CKD': '#00838F', 'IBD': '#2E86AB', 'MS': '#00BCD4',
    'OSA': '#607D8B', 'PD': '#9C27B0', 'PSP': '#E91E63', 'RA': '#FF9800',
    'T2D': '#4CAF50', 'TB': '#D32F2F', 'HCC': '#FF6F00', 'CRC': '#1976D2',
    'AF': '#FFC107', 'AIT': '#009688', 'CD': '#673AB7', 'HF': '#C62828',
    'HTN': '#1565C0', 'MDD': '#6A1B9A', 'PS': '#EF6C00', 'SLE': '#AD1457',
}

DISEASE_FULL_NAMES = {
    'AD': "Alzheimer's disease (AD)",
    'AF': 'Atrial fibrillation (AF)',
    'AIT': 'Autoimmune thyroiditis (AIT)',
    'ALS': 'Amyotrophic lateral sclerosis (ALS)',
    'AST': 'Asthma (AST)',
    'CAD': 'Coronary artery disease (CAD)',
    'CD': "Crohn's disease (CD)",
    'CKD': 'Chronic kidney disease (CKD)',
    'COPD': 'Chronic obstructive pulmonary disease (COPD)',
    'CRC': 'Colorectal cancer (CRC)',
    'HCC': 'Hepatocellular carcinoma (HCC)',
    'HF': 'Heart failure (HF)',
    'HTN': 'Hypertension (HTN)',
    'IBD': 'Inflammatory bowel disease (IBD)',
    'MDD': 'Major depressive disorder (MDD)',
    'MS': 'Multiple sclerosis (MS)',
    'OSA': 'Obstructive sleep apnea (OSA)',
    'PD': "Parkinson's disease (PD)",
    'PS': 'Psoriasis (PS)',
    'PSP': 'Progressive supranuclear palsy (PSP)',
    'RA': 'Rheumatoid arthritis (RA)',
    'SLE': 'Systemic lupus erythematosus (SLE)',
    'T2D': 'Type 2 diabetes (T2D)',
    'TB': 'Tuberculosis (TB)',
}

CATEGORIES = ['GO:BP', 'GO:MF', 'GO:CC', 'KEGG', 'REAC']

CAT_COLORS = {
    'GO:BP': '#7E57C2', 'GO:MF': '#26A69A', 'GO:CC': '#42A5F5',
    'KEGG': '#FFA726', 'REAC': '#EF5350',
}

CAT_SHORT = {
    'GO:BP': 'BP', 'GO:MF': 'MF', 'GO:CC': 'CC',
    'KEGG': 'KEGG', 'REAC': 'REAC',
}


def get_valid_modules_per_iter(full_df, category):
    """Get per-iteration valid (disease, module) pairs independently."""
    cat_df = full_df[full_df['category'] == category]
    iter1 = cat_df[(cat_df['iteration'] == 1) & (cat_df['new_matched'] > 0)]
    valid_iter1 = set(zip(iter1['disease'], iter1['module']))
    iter2 = cat_df[(cat_df['iteration'] == 2) & (cat_df['new_matched'] > 0)]
    valid_iter2 = set(zip(iter2['disease'], iter2['module']))
    return {1: valid_iter1, 2: valid_iter2}


# ═══════════════════════════════════════════════════════════════════════
#  Panel 2D support: case-study gene lists (disease-module pairs)
# ═══════════════════════════════════════════════════════════════════════
#
# Curated example gene lists spanning the validation-pass range. Each row is a
# REAL GPT-generated pathway name and the database category implied by the GPT
# output order (10 terms each for GO:BP, GO:MF, GO:CC, KEGG and Reactome).
# `nfdr` is retained as the source-column name, but is displayed as the
# pair-level statistical validation pass rate (category mean) from the metrics CSV.
CASE_EXAMPLES = [
    dict(label='High-pass example', disease='IBD', module=91, genes=207,
         nfdr=79, tier='high',
         rows=[('regulation of inflammatory response', True, 'GO:BP',
                'GO:0050727'),
               ('response to bacterium', True, 'GO:BP', 'GO:0009617'),
               ('endocytosis', True, 'GO:BP', 'GO:0006897'),
               ('Cytokine-cytokine receptor interaction', False, 'KEGG',
                'hsa04060'),
               ('Interleukin-23 signaling', False, 'REAC',
                'R-HSA-9020933')]),
    dict(label='Intermediate-pass example', disease='RA', module=86, genes=175,
         nfdr=45, tier='mid',
         rows=[('regulation of cell cycle', True, 'GO:BP', 'GO:0051726'),
               ('chromatin binding', True, 'GO:MF', 'GO:0003682'),
               ('cytosol', True, 'GO:CC', 'GO:0005829'),
               ('RNA splicing', False, 'GO:BP', 'GO:0008380'),
               ('Endocytosis', False, 'KEGG', 'hsa04144')]),
]


def load_pair_pathway_status(disease, module, iteration=1):
    """Map each GPT-generated pathway name -> 'sig' | 'broad' | 'none'.

    'sig'   : matched a g:Profiler term significant at FDR < 0.05
    'broad' : matched an enriched term, but not FDR-significant
    'none'  : not found among enriched terms
    Returns {} if the source files are missing.
    """
    base = os.path.join(MEMBANK_DIR, f"iterative_feedback_{disease}",
                        "gpt_led_analysis_ag2_hitl")
    pj = os.path.join(
        base, f"{disease}_Module_{module}_iter{iteration}_gpt_prediction.json")
    if not os.path.exists(pj):
        return {}
    try:
        with open(pj) as fh:
            pred = json.load(fh)
    except Exception:
        return {}
    det = pred.get('pathway_details', {})

    def _ids_names(suffix):
        p = os.path.join(
            base,
            f"{disease}_Module_{module}_iter{iteration}_gpt_matched_{suffix}.csv")
        if not os.path.exists(p) or os.path.getsize(p) < 150:
            return set(), set()
        try:
            d = pd.read_csv(p)
            ids = set(d['native'].dropna()) if 'native' in d else set()
            nms = (set(d['name'].astype(str).str.lower())
                   if 'name' in d else set())
            return ids, nms
        except Exception:
            return set(), set()

    all_ids, all_nm = _ids_names('all')
    sig_ids, sig_nm = _ids_names('fdr_p005')
    status = {}
    for name, meta in det.items():
        gid = meta.get('go_id', '') if isinstance(meta, dict) else ''
        nl = str(name).lower()
        if (gid and gid in sig_ids) or nl in sig_nm:
            status[name] = 'sig'
        elif (gid and gid in all_ids) or nl in all_nm:
            status[name] = 'broad'
        else:
            status[name] = 'none'
    return status


def _case_category_stats(metrics_df, ex):
    """Per-database validation counts for a displayed disease-module case."""
    if metrics_df is None or len(metrics_df) == 0:
        return [], ex['nfdr']

    sub = metrics_df[
        (metrics_df['disease'] == ex['disease']) &
        (metrics_df['module'] == ex['module']) &
        (metrics_df['iteration'] == 1)
    ]
    stats = []
    included_rates = []
    for cat in CATEGORIES:
        row = sub[sub['category'] == cat]
        if len(row) == 0:
            stats.append(dict(cat=cat, matched=0, passed=0, rate=np.nan))
            continue
        matched = int(row['new_matched'].iloc[0])
        rate = float(row['nfdr_pct'].iloc[0]) if matched > 0 else np.nan
        passed = int(round(rate * matched / 100.0)) if matched > 0 else 0
        if matched > 0:
            included_rates.append(rate)
        stats.append(dict(cat=cat, matched=matched, passed=passed, rate=rate))

    mean_rate = float(np.mean(included_rates)) if included_rates else ex['nfdr']
    return stats, mean_rate


def _wrap_pathway_label(label, width=23):
    """Wrap pathway names inside compact case-study boxes."""
    lines = textwrap.wrap(
        label, width=width, break_long_words=False, break_on_hyphens=False)
    if len(lines) <= 2:
        return "\n".join(lines)
    return "\n".join([lines[0], textwrap.shorten(
        " ".join(lines[1:]), width=width, placeholder="...")])


def _single_line_pathway_label(label, width=42):
    """Compact pathway label for one-line name plus separate ID display."""
    return textwrap.shorten(label, width=width, placeholder="...")


def _two_line_full_pathway_label(label, width=24):
    """Wrap a full pathway name into two balanced lines without ellipses."""
    words = str(label).split()
    if len(words) <= 1:
        return str(label)
    lines = textwrap.wrap(
        str(label), width=width, break_long_words=False,
        break_on_hyphens=False)
    if len(lines) <= 2:
        return "\n".join(lines)

    best_i, best_score = 1, float('inf')
    for i in range(1, len(words)):
        first = " ".join(words[:i])
        second = " ".join(words[i:])
        score = max(len(first), len(second)) + abs(len(first) - len(second)) * 0.35
        if score < best_score:
            best_i, best_score = i, score
    return " ".join(words[:best_i]) + "\n" + " ".join(words[best_i:])


def _cluster_bootstrap_mean_ci(values, clusters, rng, n_boot=2000):
    """Percentile 95% CI for a mean using clustered bootstrap resampling."""
    values = np.asarray(values, dtype=float)
    clusters = np.asarray(clusters)
    ok = np.isfinite(values)
    values, clusters = values[ok], clusters[ok]
    if len(values) == 0:
        return np.nan, np.nan, np.nan

    mean = float(np.mean(values))
    unique_clusters = pd.unique(clusters)
    if len(unique_clusters) <= 1:
        return mean, mean, mean

    grouped_values = [values[clusters == cid] for cid in unique_clusters]
    boot_means = np.empty(n_boot, dtype=float)
    for bi in range(n_boot):
        sampled = rng.integers(0, len(grouped_values), len(grouped_values))
        boot_means[bi] = np.mean(np.concatenate(
            [grouped_values[idx] for idx in sampled]))

    ci_low, ci_high = np.percentile(boot_means, [2.5, 97.5])
    return mean, max(0.0, float(ci_low)), min(100.0, float(ci_high))


def _hierarchical_gene_list_bootstrap_mean_ci(frame, value_col, rng,
                                              n_boot=3000):
    """95% CI for a mean with disease -> gene-list clustered resampling.

    The plotted unit is a paired validation record, but records from the same
    disease and gene list are correlated across pathway categories. The
    bootstrap therefore samples diseases first, then samples gene lists within
    each selected disease, preserving all selected category records together.
    """
    sub = frame[['disease', 'module', value_col]].copy()
    sub[value_col] = pd.to_numeric(sub[value_col], errors='coerce')
    sub = sub.dropna(subset=[value_col, 'disease', 'module'])
    if len(sub) == 0:
        return np.nan, np.nan, np.nan

    mean = float(sub[value_col].mean())
    disease_groups = []
    for _, disease_df in sub.groupby('disease', sort=False):
        gene_list_groups = [
            g[value_col].to_numpy(dtype=float)
            for _, g in disease_df.groupby('module', sort=False)
            if len(g) > 0
        ]
        if gene_list_groups:
            disease_groups.append(gene_list_groups)

    if len(disease_groups) <= 1:
        return mean, mean, mean

    boot_means = np.empty(n_boot, dtype=float)
    n_diseases = len(disease_groups)
    for bi in range(n_boot):
        sampled_diseases = rng.integers(0, n_diseases, n_diseases)
        sampled_values = []
        for disease_idx in sampled_diseases:
            gene_lists = disease_groups[disease_idx]
            sampled_gene_lists = rng.integers(
                0, len(gene_lists), len(gene_lists))
            sampled_values.extend(gene_lists[idx] for idx in sampled_gene_lists)
        boot_means[bi] = np.mean(np.concatenate(sampled_values))

    ci_low, ci_high = np.percentile(boot_means, [2.5, 97.5])
    return mean, max(0.0, float(ci_low)), min(100.0, float(ci_high))


def _blend_with_white(color, amount=0.66):
    """Return a low-saturation tint for Nature-style result bars."""
    rgba = np.array(to_rgba(color))
    white = np.array([1.0, 1.0, 1.0, rgba[3]])
    return tuple(rgba * (1 - amount) + white * amount)


def _iter_category_record_summary(combined_df, iteration):
    """Record-level summary rows for one round/iteration."""
    sub = combined_df[
        (combined_df['iteration'] == iteration) &
        (combined_df['new_matched'] > 0)
    ].copy()
    sub['nfdr_pct'] = pd.to_numeric(sub['nfdr_pct'], errors='coerce')
    sub = sub.dropna(subset=['nfdr_pct'])

    rows = [dict(
        label='Overall', cat=None, n=len(sub),
        mean=float(sub['nfdr_pct'].mean()),
        zero=float((sub['nfdr_pct'] == 0).mean() * 100),
    )]
    for cat in CATEGORIES:
        s = sub[sub['category'] == cat]
        rows.append(dict(
            label=CAT_SHORT[cat], cat=cat, n=len(s),
            mean=float(s['nfdr_pct'].mean()),
            zero=float((s['nfdr_pct'] == 0).mean() * 100),
        ))
    return rows


def _panel2a_density_plot(ax, cat_data, combined_df):
    """Panel 2A: zero-shot validation-pass distributions by database."""
    xgrid = np.linspace(0, 100, 500)
    ymax = 0.0
    for cat in CATEGORIES:
        vals = np.asarray(cat_data.get(cat, []), dtype=float)
        vals = vals[np.isfinite(vals)]
        vals = vals[(vals > 0) & (vals <= 100)]
        if len(np.unique(vals)) < 3:
            continue
        kde = gaussian_kde(vals, bw_method=0.28)
        y = kde(xgrid)
        ymax = max(ymax, float(np.nanmax(y)))
        ax.fill_between(xgrid, y, color=CAT_COLORS[cat], alpha=0.115,
                        linewidth=0, zorder=1)
        ax.plot(xgrid, y, color=CAT_COLORS[cat], linewidth=1.45,
                label=CAT_SHORT[cat], zorder=3)

    ax.set_xlim(0, 100)
    y_limit = ymax * 1.18 if ymax > 0 else 0.04
    ax.set_ylim(0, y_limit)
    ax.set_xticks([0, 20, 40, 60, 80, 100])
    if y_limit <= 0.022:
        y_step = 0.004
        y_top = np.floor(y_limit / y_step) * y_step
        yticks = np.arange(0, y_top + y_step / 2, y_step)
    else:
        yticks = np.linspace(0, y_limit, 5)
    ax.set_yticks(yticks)
    ax.set_yticklabels([f'{v:.3f}' for v in yticks])
    ax.set_xlabel('Validation pass rate (%)', fontsize=7.6)
    ax.set_ylabel('Density (non-zero pass rates)', fontsize=7.2, labelpad=3)
    ax.set_title('Pathway-category validation profiles',
                 fontsize=8.8, fontweight='bold', pad=5)
    ax.text(0.01, 0.89, 'gene list-category records, round 1',
            transform=ax.transAxes, ha='left', va='center',
            fontsize=5.9, color='#666666')
    ax.grid(axis='both', color='#E8E8E8', linewidth=0.48, zorder=0)
    ax.set_axisbelow(True)
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)
    ax.spines['left'].set_linewidth(0.65)
    ax.spines['bottom'].set_linewidth(0.65)
    ax.tick_params(axis='x', labelsize=6.8)
    ax.tick_params(axis='y', labelsize=6.4, length=2.4, pad=2)

    rows = _iter_category_record_summary(combined_df, iteration=1)[1:]
    inset_bounds = [0.665, 0.625, 0.300, 0.265]
    ax.add_patch(plt.Rectangle(
        (0.642, 0.526), 0.348, 0.420,
        transform=ax.transAxes, facecolor='white', edgecolor='none',
        zorder=7))
    inset = ax.inset_axes(inset_bounds)
    inset.set_zorder(8)
    inset.set_facecolor('white')
    inset.patch.set_alpha(1.0)
    x = np.arange(len(rows))
    inset.bar(x, [r['zero'] for r in rows], width=0.58,
              color=[CAT_COLORS[r['cat']] for r in rows],
              alpha=0.92, edgecolor='white', linewidth=0.55, zorder=3)
    for xi, r in zip(x, rows):
        inset.text(xi, r['zero'] + 1.6, f"{r['zero']:.0f}",
                   ha='center', va='bottom', fontsize=4.8,
                   color='#333333', zorder=5)
    inset.text(0.02, 1.05, 'Zero-pass gene lists (%)',
               transform=inset.transAxes, ha='left', va='bottom',
               fontsize=5.2, fontweight='bold', color='#222222')
    inset.set_ylim(0, 55)
    inset.set_yticks([0, 25, 50])
    inset.set_ylabel('')
    inset.set_xticks(x)
    inset.set_xticklabels([CAT_SHORT[r['cat']] for r in rows],
                          rotation=35, ha='right', fontsize=4.6)
    for label in inset.get_xticklabels():
        label.set_bbox(dict(facecolor='white', edgecolor='none', pad=0.12))
    inset.grid(axis='y', color='#E7E7E7', linewidth=0.42, zorder=0)
    inset.spines['top'].set_visible(False)
    inset.spines['right'].set_visible(False)
    inset.spines['left'].set_linewidth(0.48)
    inset.spines['bottom'].set_linewidth(0.48)
    inset.tick_params(axis='y', labelsize=4.7, length=2, pad=1)
    inset.tick_params(axis='x', length=0, pad=1)


def _panel2b_category_boxplot(ax, cat_disease_avgs):
    """Panel 2B: disease-level zero-shot pass-rate variation by category."""
    from matplotlib.patches import FancyBboxPatch

    rng = np.random.default_rng(52)
    y_positions = np.arange(len(CATEGORIES))[::-1]
    all_values = []

    for yi, cat in zip(y_positions, CATEGORIES):
        vals = np.asarray(cat_disease_avgs[cat], dtype=float)
        vals = vals[np.isfinite(vals)]
        all_values.append(vals)
        if len(vals) == 0:
            continue
        ax.boxplot(
            vals, vert=False, positions=[yi], widths=0.48,
            patch_artist=True, showfliers=False, whis=(5, 95),
            boxprops=dict(facecolor=_blend_with_white(CAT_COLORS[cat], 0.72),
                          edgecolor=CAT_COLORS[cat], linewidth=0.95),
            medianprops=dict(color='#333333', linewidth=1.05),
            whiskerprops=dict(color=CAT_COLORS[cat], linewidth=0.85),
            capprops=dict(color=CAT_COLORS[cat], linewidth=0.85),
            zorder=3)
        jitter = rng.normal(0, 0.052, len(vals))
        ax.scatter(vals, yi + jitter, s=10.5, color=CAT_COLORS[cat],
                   alpha=0.38, edgecolors='white', linewidths=0.22,
                   zorder=4)
        mean = float(np.mean(vals))
        ax.scatter([mean], [yi], marker='D', s=18, color='white',
                   edgecolor='#2F6F9F', linewidth=0.9, zorder=5)
        ax.text(53.0, yi + 0.16, f'{mean:.1f}%',
                ha='right', va='center', fontsize=6.3,
                color='#2F6F9F', fontweight='bold')
        ax.text(53.0, yi - 0.16, f'n={len(vals)}',
                ha='right', va='center', fontsize=5.2,
                color='#666666')

    ax.set_yticks(y_positions)
    ax.set_yticklabels([CAT_SHORT[c] for c in CATEGORIES],
                       fontsize=7.2, fontweight='bold')
    ax.set_xlim(0, 56)
    ax.set_xticks([0, 20, 40])
    ax.set_xlabel('Disease-mean pass rate (%)', fontsize=7.6)
    ax.set_title('Disease-level validation by pathway category',
                 fontsize=8.8, fontweight='bold', pad=5)
    legend_x, legend_y = 0.012, 0.895
    ax.add_patch(FancyBboxPatch(
        (legend_x, legend_y), 0.245, 0.070,
        boxstyle='round,pad=0.006,rounding_size=0.010',
        transform=ax.transAxes, facecolor='white',
        edgecolor='#E2E2E2', linewidth=0.45, zorder=6))
    ax.scatter([legend_x + 0.022], [legend_y + 0.038],
               s=13, color='#9DBBD0', alpha=0.80, edgecolors='white',
               linewidths=0.25, transform=ax.transAxes, zorder=7)
    ax.text(legend_x + 0.040, legend_y + 0.038, 'disease',
            transform=ax.transAxes, ha='left', va='center',
            fontsize=5.45, color='#555555', zorder=7)
    ax.scatter([legend_x + 0.120], [legend_y + 0.038],
               marker='D', s=17, color='white', edgecolor='#2F6F9F',
               linewidth=0.8, transform=ax.transAxes, zorder=7)
    ax.text(legend_x + 0.140, legend_y + 0.038, 'category mean',
            transform=ax.transAxes, ha='left', va='center',
            fontsize=5.45, color='#555555', zorder=7)
    ax.grid(axis='x', color='#E5E5E5', linewidth=0.55, zorder=0)
    ax.set_axisbelow(True)
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)
    ax.spines['left'].set_linewidth(0.65)
    ax.spines['bottom'].set_linewidth(0.65)
    ax.tick_params(axis='x', labelsize=6.8)
    ax.tick_params(axis='y', length=0)


def _draw_size_strata_panel(ax, ms_iter1, size_edges=None):
    """Panel 2C: compact size-stratified validation summary.

    size_edges should be computed once from unique gene lists so category rows
    do not implicitly reweight the gene-list size quartiles.
    """
    from matplotlib.patches import FancyBboxPatch

    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis('off')

    clean = ms_iter1[
        ['disease', 'module', 'category', 'module_size', 'nfdr_pct']
    ].dropna().copy()
    if len(clean) == 0:
        ax.text(0.5, 0.5, 'Module-size data\nnot available',
                transform=ax.transAxes, ha='center', va='center',
                fontsize=10, color='#999999')
        return

    clean['module_size'] = pd.to_numeric(clean['module_size'],
                                         errors='coerce')
    clean['nfdr_pct'] = pd.to_numeric(clean['nfdr_pct'], errors='coerce')
    clean = clean.dropna(subset=['module_size', 'nfdr_pct'])
    edges = (
        np.unique(np.asarray(size_edges, dtype=float))
        if size_edges is not None
        else np.unique(np.percentile(
            clean[['disease', 'module', 'module_size']]
            .drop_duplicates()['module_size'],
            [0, 25, 50, 75, 100],
        ))
    )
    if len(edges) < 3:
        ax.text(0.5, 0.5, 'Insufficient module-size range',
                transform=ax.transAxes, ha='center', va='center',
                fontsize=10, color='#999999')
        return

    bin_labels = []
    for j, (lo, hi) in enumerate(zip(edges[:-1], edges[1:])):
        lo_i = int(np.ceil(lo))
        hi_i = int(
            np.floor(hi)
            if j == len(edges) - 2
            else np.ceil(hi) - 1
        )
        if hi_i < lo_i:
            hi_i = int(np.floor(hi))
        bin_labels.append(f'{lo_i}-{hi_i}')

    rows = []
    for cat in CATEGORIES:
        sub = clean[clean['category'] == cat]
        means, counts = [], []
        for j, (lo, hi) in enumerate(zip(edges[:-1], edges[1:])):
            if j < len(edges) - 2:
                mask = (sub['module_size'] >= lo) & (sub['module_size'] < hi)
            else:
                mask = (sub['module_size'] >= lo) & (sub['module_size'] <= hi)
            vals = sub.loc[mask, 'nfdr_pct'].to_numpy(dtype=float)
            means.append(float(np.nanmean(vals)) if len(vals) else np.nan)
            counts.append(int(np.isfinite(vals).sum()))
        rows.append(dict(cat=cat, means=means, counts=counts,
                         delta=means[-1] - means[0]
                         if np.isfinite(means[-1]) and np.isfinite(means[0])
                         else np.nan))

    all_means = np.array([v for row in rows for v in row['means']
                          if np.isfinite(v)])
    vmin = max(0.0, float(np.nanpercentile(all_means, 5)) - 3.0)
    vmax = min(60.0, float(np.nanpercentile(all_means, 95)) + 3.0)
    if vmax <= vmin:
        vmax = vmin + 1.0
    low = np.array(to_rgba('#F4F8FB'))
    high = np.array(to_rgba('#2F6F9F'))

    def _rate_color(value):
        t = np.clip((value - vmin) / (vmax - vmin), 0, 1)
        return tuple(low * (1 - t) + high * t), t

    ax.text(0.012, 1.035, 'Gene-list size-stratified validation',
            ha='left', va='top', transform=ax.transAxes,
            fontsize=8.9, fontweight='bold', color='#111111',
            clip_on=False)
    ax.text(0.012, 0.775,
            'Gene-list length control',
            ha='left', va='top', transform=ax.transAxes,
            fontsize=5.4, color='#555555', linespacing=0.92)

    x0, x_gap, cell_w = 0.180, 0.145, 0.124
    y0, y_gap, cell_h = 0.580, 0.095, 0.082

    # Compact size-axis strip: it tells readers that the rows compare the
    # same quartile progression for every pathway category.
    guide_left = x0 + 0.005
    guide_right = x0 + 3 * x_gap + cell_w - 0.006
    strip_x = guide_left - 0.018
    strip_y = 0.650
    strip_w = guide_right - guide_left + 0.036
    strip_h = 0.155
    ax.add_patch(FancyBboxPatch(
        (strip_x, strip_y), strip_w, strip_h,
        boxstyle='round,pad=0.004,rounding_size=0.010',
        transform=ax.transAxes, facecolor='#F3F6F8',
        edgecolor='#E1E7EB', linewidth=0.50, zorder=1))
    ax.text((guide_left + guide_right) / 2, strip_y + strip_h - 0.030,
            'size quartiles (genes)',
            ha='center', va='bottom', transform=ax.transAxes,
            fontsize=6.0, fontweight='bold', color='#333333', zorder=3)
    guide_y = strip_y + 0.062
    ax.annotate('', xy=(guide_right, guide_y),
                xytext=(guide_left, guide_y),
                xycoords=ax.transAxes, textcoords=ax.transAxes,
                arrowprops=dict(arrowstyle='-|>', color='#9BAAB5',
                                lw=0.8, shrinkA=0, shrinkB=0),
                zorder=3)
    ax.text(guide_left, guide_y + 0.019, 'small',
            ha='left', va='bottom', transform=ax.transAxes,
            fontsize=4.9, color='#66737D', zorder=3)
    ax.text(guide_right, guide_y + 0.019, 'large',
            ha='right', va='bottom', transform=ax.transAxes,
            fontsize=4.9, color='#66737D', zorder=3)

    for j, label in enumerate(bin_labels):
        cx = x0 + j * x_gap + cell_w / 2
        ax.text(cx, strip_y + 0.018, f'Q{j + 1}\n{label}',
                ha='center', va='bottom', transform=ax.transAxes,
                fontsize=5.9, color='#333333', linespacing=0.90)

    delta_x = 0.865
    delta_header_y = strip_y
    delta_header_h = strip_h
    ax.add_patch(FancyBboxPatch(
        (delta_x - 0.053, delta_header_y), 0.106, delta_header_h,
        boxstyle='round,pad=0.004,rounding_size=0.010',
        transform=ax.transAxes, facecolor='#FAFAFA',
        edgecolor='#E0E0E0', linewidth=0.50, zorder=1))
    ax.text(delta_x, delta_header_y + 0.028, 'Q4 - Q1\ntrend (pp)',
            ha='center', va='bottom', transform=ax.transAxes,
            fontsize=5.8, fontweight='bold', color='#333333',
            linespacing=0.92)

    for i, row in enumerate(rows):
        y = y0 - i * y_gap
        cat = row['cat']
        ax.add_patch(plt.Rectangle(
            (0.064, y - cell_h / 2), 0.012, cell_h,
            transform=ax.transAxes, facecolor=CAT_COLORS[cat],
            edgecolor='none', zorder=2))
        ax.text(0.088, y, CAT_SHORT[cat],
                ha='left', va='center', transform=ax.transAxes,
                fontsize=6.6, fontweight='bold', color='#333333')

        for j, value in enumerate(row['means']):
            x = x0 + j * x_gap
            if np.isfinite(value):
                face, t = _rate_color(value)
                text_col = 'white' if t > 0.64 else '#202020'
                sub_col = '#F0F4F7' if t > 0.64 else '#5F6670'
                ax.add_patch(FancyBboxPatch(
                    (x, y - cell_h / 2), cell_w, cell_h,
                    boxstyle='round,pad=0.003,rounding_size=0.010',
                    transform=ax.transAxes, facecolor=face,
                    edgecolor='white', linewidth=0.75, zorder=2))
                ax.text(x + cell_w * 0.505, y, f'{value:.0f}%',
                        ha='right', va='center', transform=ax.transAxes,
                        fontsize=6.7, fontweight='bold', color=text_col,
                        zorder=3)
                ax.text(x + cell_w * 0.535, y,
                        f'n={row["counts"][j]}',
                        ha='left', va='center', transform=ax.transAxes,
                        fontsize=4.55, color=sub_col, zorder=3)
            else:
                ax.add_patch(FancyBboxPatch(
                    (x, y - cell_h / 2), cell_w, cell_h,
                    boxstyle='round,pad=0.003,rounding_size=0.010',
                    transform=ax.transAxes, facecolor='#F5F5F5',
                    edgecolor='white', linewidth=0.75, zorder=2))
                ax.text(x + cell_w / 2, y, 'n/a',
                        ha='center', va='center', transform=ax.transAxes,
                        fontsize=5.8, color='#777777', zorder=3)

        delta = row['delta']
        if np.isfinite(delta):
            if delta > 2.5:
                dcol = '#2F6F9F'
                dface = '#EAF3F8'
            elif delta < -2.5:
                dcol = '#B65B4D'
                dface = '#F8ECE8'
            else:
                dcol = '#6A6A6A'
                dface = '#F2F2F2'
            ax.add_patch(FancyBboxPatch(
                (delta_x - 0.053, y - 0.030), 0.106, 0.060,
                boxstyle='round,pad=0.003,rounding_size=0.010',
                transform=ax.transAxes, facecolor=dface,
                edgecolor='white', linewidth=0.55, zorder=2))
            ax.text(delta_x, y, f'{delta:+.1f} pp',
                    ha='center', va='center', transform=ax.transAxes,
                    fontsize=5.6, fontweight='bold', color=dcol, zorder=3)

    # Compact color key. The numbers in cells carry the quantitative reading;
    # the gradient mainly helps readers scan high and low strata quickly.
    grad_x, grad_y, grad_w, grad_h = 0.180, 0.073, 0.230, 0.024
    for k in range(60):
        value = vmin + (vmax - vmin) * k / 59
        face, _ = _rate_color(value)
        ax.add_patch(plt.Rectangle(
            (grad_x + grad_w * k / 60, grad_y), grad_w / 60, grad_h,
            transform=ax.transAxes, facecolor=face, edgecolor='none',
            zorder=2))
    ax.text(grad_x, grad_y + grad_h + 0.018, 'Mean pass rate (%)',
            ha='left', va='bottom', transform=ax.transAxes,
            fontsize=5.7, color='#555555')
    for value, xoff in [(vmin, 0), ((vmin + vmax) / 2, 0.5), (vmax, 1)]:
        ax.text(grad_x + grad_w * xoff, grad_y - 0.014, f'{value:.0f}',
                ha='center', va='top', transform=ax.transAxes,
                fontsize=5.0, color='#666666')
    ax.text(0.500, 0.072,
            'Opposite Q4-Q1 signs indicate validation is not a single gene-count artifact.',
            ha='left', va='center', transform=ax.transAxes,
            fontsize=5.7, color='#666666')


def _draw_case_radar(ax, bounds, stats, accent):
    """Draw a compact five-database radar plot inside Panel 2D."""
    parent = ax.get_position()
    fig_bounds = [
        parent.x0 + bounds[0] * parent.width,
        parent.y0 + bounds[1] * parent.height,
        bounds[2] * parent.width,
        bounds[3] * parent.height,
    ]
    rax = ax.figure.add_axes(fig_bounds, projection='polar')
    rax.set_zorder(3)
    labels = ['BP', 'MF', 'CC', 'KEGG', 'REAC']
    angles = np.linspace(0, 2 * np.pi, len(labels), endpoint=False)
    vals = []
    for stat in stats:
        vals.append(0.0 if np.isnan(stat['rate']) else stat['rate'] / 100.0)
    angles_closed = np.r_[angles, angles[0]]
    vals_closed = np.r_[vals, vals[0]]

    rax.set_theta_offset(np.pi / 2)
    rax.set_theta_direction(-1)
    rax.plot(angles_closed, vals_closed, color=accent, linewidth=1.0)
    rax.fill(angles_closed, vals_closed, color=accent, alpha=0.18)
    rax.set_ylim(0, 1.0)
    rax.set_xticks(angles)
    rax.set_xticklabels([])
    rax.set_yticks([0.5, 1.0])
    rax.set_yticklabels(['50', '100'], fontsize=3.2, color='#777777')
    rax.tick_params(axis='x', length=0, pad=0)
    rax.tick_params(axis='y', pad=-2)
    outer_labels = [
        ('BP', 0.50, 1.045, 'center', 'bottom'),
        ('MF', 1.030, 0.52, 'left', 'center'),
        ('CC', 0.74, -0.040, 'center', 'top'),
        ('KEGG', 0.22, -0.040, 'center', 'top'),
        ('REAC', -0.030, 0.52, 'right', 'center'),
    ]
    for label, lx, ly, ha, va in outer_labels:
        rax.text(lx, ly, label, transform=rax.transAxes,
                 ha=ha, va=va, fontsize=3.55, color='#555555',
                 clip_on=False, zorder=6)
    rax.grid(color='#D8D8D8', linewidth=0.45)
    rax.spines['polar'].set_color('#BDBDBD')
    rax.set_facecolor('white')
    return rax


def _draw_case_examples_panel(ax, metrics_df=None):
    """Panel 2D: compact high/low examples for generated-term validation."""
    from matplotlib.patches import FancyBboxPatch

    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis('off')

    tier_color = {'low': '#C0392B', 'mid': '#E08E0B', 'high': '#2E7D32'}

    ax.text(0.010, 0.955,
            'Disease-gene-list pairs with category pass counts and '
            'top GPT-ranked pathway terms',
            fontsize=6.3, color='#555555', ha='left', va='top',
            transform=ax.transAxes)

    case_xs = [0.010, 0.505]
    case_w = 0.480
    case_y = 0.055
    case_h = 0.835

    for ci, ex in enumerate(CASE_EXAMPLES):
        box_x = case_xs[ci]
        accent = tier_color[ex['tier']]
        stats, mean_rate = _case_category_stats(metrics_df, ex)

        ax.add_patch(plt.Rectangle(
            (box_x, case_y), case_w, case_h, transform=ax.transAxes,
            facecolor='#FBFBFB', edgecolor='#D7D7D7', linewidth=0.65,
            zorder=1))
        ax.add_patch(plt.Rectangle(
            (box_x, case_y), 0.008, case_h, transform=ax.transAxes,
            facecolor=accent, edgecolor='none', zorder=2))

        disease_name = DISEASE_FULL_NAMES.get(ex['disease'], ex['disease'])
        ax.text(box_x + 0.022, case_y + case_h - 0.045,
                f"{disease_name}\ngene list {ex['module']} · {ex['genes']} genes",
                fontsize=5.7, color='#4D4D4D', ha='left', va='top',
                linespacing=0.95, transform=ax.transAxes, zorder=3)
        ax.text(box_x + case_w - 0.020, case_y + case_h - 0.055,
                f"{mean_rate:.0f}%", fontsize=11.5, fontweight='bold',
                color=accent, ha='right', va='top',
                transform=ax.transAxes, zorder=3)
        ax.text(box_x + case_w - 0.020, case_y + case_h - 0.135,
                'mean pass rate', fontsize=5.7, color='#777777',
                ha='right', va='top', transform=ax.transAxes, zorder=3)

        radar_x = box_x + 0.034
        _draw_case_radar(ax, [radar_x, case_y + 0.082, 0.082, 0.386],
                         stats, accent)

        # Middle box: category-level fractions used in the mean.
        mid_x, mid_w = box_x + 0.128, 0.132
        mid_y, mid_h = case_y + 0.060, 0.650
        ax.add_patch(plt.Rectangle(
            (mid_x, mid_y), mid_w, mid_h, transform=ax.transAxes,
            facecolor='white', edgecolor='#7A7A7A', linewidth=0.55, zorder=2))
        ax.text(mid_x + 0.012, mid_y + mid_h - 0.030,
                'Category pass\ncounts',
                fontsize=5.55, fontweight='bold', color='#333333',
                ha='left', va='top', linespacing=0.92,
                transform=ax.transAxes, zorder=3)
        bx0, bx1 = mid_x + 0.012, mid_x + mid_w - 0.014
        by = mid_y + mid_h - 0.118
        ax.add_patch(plt.Rectangle((bx0, by - 0.005), bx1 - bx0, 0.010,
                     transform=ax.transAxes, facecolor='#ECECEC',
                     edgecolor='none', zorder=2))
        ax.add_patch(plt.Rectangle(
            (bx0, by - 0.005), (bx1 - bx0) * mean_rate / 100.0, 0.010,
            transform=ax.transAxes, facecolor=accent, edgecolor='none',
            zorder=3))

        list_top = mid_y + mid_h - 0.160
        list_gap = (mid_h - 0.205) / len(CATEGORIES)
        for si, stat in enumerate(stats):
            ly = list_top - si * list_gap
            ax.add_patch(plt.Rectangle(
                (mid_x + 0.012, ly - 0.006), 0.007, 0.007,
                transform=ax.transAxes, facecolor=CAT_COLORS[stat['cat']],
                edgecolor='none', zorder=3))
            if stat['matched'] > 0:
                label = (f"{CAT_SHORT[stat['cat']]}: {stat['passed']}/"
                         f"{stat['matched']} ({stat['rate']:.0f}%)")
                color = '#333333'
            else:
                label = f"{CAT_SHORT[stat['cat']]}: n/a"
                color = '#8A8A8A'
            ax.text(mid_x + 0.024, ly, label, fontsize=5.35,
                    color=color, ha='left', va='center',
                    transform=ax.transAxes, zorder=3)

        # Right box: representative GPT-ranked generated terms.
        right_x, right_w = box_x + 0.270, case_w - 0.279
        right_y, right_h = case_y + 0.060, 0.650
        ax.add_patch(plt.Rectangle(
            (right_x, right_y), right_w, right_h, transform=ax.transAxes,
            facecolor='white', edgecolor='#7A7A7A', linewidth=0.55, zorder=2))
        ax.text(right_x + 0.012, right_y + right_h - 0.040,
                'GPT ranking',
                fontsize=5.9, fontweight='bold', color='#333333',
                ha='left', va='center', transform=ax.transAxes, zorder=3)
        term_top = right_y + right_h - 0.120
        term_gap = (right_h - 0.190) / len(ex['rows'])
        for ri, (name, _expected, cat, pathway_id) in enumerate(ex['rows']):
            ry = term_top - ri * term_gap
            cat_label = CAT_SHORT.get(cat, cat)
            cat_w = 0.027 if len(cat_label) <= 2 else 0.042
            cat_x = right_x + 0.027
            term_x = cat_x + cat_w + 0.008
            full_name = _two_line_full_pathway_label(name, width=24)
            ax.text(right_x + 0.013, ry, f'{ri + 1}',
                    fontsize=5.2, fontweight='bold', color='#555555',
                    ha='center', va='center', transform=ax.transAxes, zorder=3,
                    bbox=dict(boxstyle='circle,pad=0.14', facecolor='#F2F2F2',
                              edgecolor='#BDBDBD', linewidth=0.40))
            ax.add_patch(FancyBboxPatch(
                (cat_x, ry - 0.015), cat_w, 0.030,
                boxstyle='round,pad=0.001,rounding_size=0.004',
                transform=ax.transAxes, facecolor=to_rgba(CAT_COLORS[cat], 0.12),
                edgecolor=CAT_COLORS[cat], linewidth=0.40, zorder=3))
            ax.text(cat_x + cat_w / 2, ry, cat_label,
                    fontsize=3.85, fontweight='bold', color=CAT_COLORS[cat],
                    ha='center', va='center', transform=ax.transAxes, zorder=4)
            ax.text(term_x, ry + 0.030, full_name, fontsize=3.35,
                    color='#333333', ha='left', va='top',
                    linespacing=0.98, transform=ax.transAxes, zorder=3)
            ax.text(term_x, ry - 0.033, pathway_id, fontsize=3.45,
                    color='#777777', ha='left', va='center',
                    transform=ax.transAxes, zorder=3)


# ═══════════════════════════════════════════════════════════════════════
#  Figure 3: nfdr_trend_composite  (3-panel: 3A density, 3B scatter, 3C cases)
# ═══════════════════════════════════════════════════════════════════════

ITER1_COLOR = '#9FB0BC'   # faded grey-blue (iteration 1)
ITER2_COLOR = '#2F6F9F'   # solid blue      (iteration 2)

# Fig 3C: feedback case studies (low iter1 -> high iter2). Each displayed row
# is a REAL GPT-generated pathway name; the ✓/✗ status is re-derived from the
# matched files at render time (with the bundled flag as fallback).
CASE_ITER = [
    dict(disease='AF', module=16, genes=11, i1=11, i2=81,
         note='generic guesses → ion-channel anchors',
         iter1=[('chromatin binding', False),
                ('extracellular matrix organization', False),
                ('small GTPase activity', False),
                ('structural constituent of muscle', False)],
         iter2=[('voltage-gated ion channel activity', True),
                ('potassium ion transmembrane transporter activity', True),
                ('ion channel regulator activity', True),
                ('calmodulin binding', True)]),
    dict(disease='COPD', module=7, genes=67, i1=10, i2=71,
         note='keeps mitochondrial hit → expands OXPHOS family',
         iter1=[('Mitochondrion', True),
                ('epithelial cell differentiation', False),
                ('JAK-STAT cascade', False),
                ('cytokine-mediated signaling pathway', False)],
         iter2=[('oxidative phosphorylation', True),
                ('electron transfer activity', True),
                ('NADH dehydrogenase (ubiquinone) activity', True),
                ('ATP synthase activity, coupled to transmembrane '
                 'movement of ions, rotational mechanism', True)]),
]

# Compact display labels for long pathway names (Fig 3C).
_LABEL_OVERRIDE = {
    'potassium ion transmembrane transporter activity':
        'K+ transmembrane transporter',
    'ATP synthase activity, coupled to transmembrane '
    'movement of ions, rotational mechanism': 'ATP synthase activity',
    'voltage-gated ion channel activity': 'voltage-gated ion channel',
    'NADH dehydrogenase (ubiquinone) activity': 'NADH dehydrogenase activity',
}


def _valid_iter_rows(combined_df, iteration):
    """Iteration rows restricted to that iteration's validated (disease,
    module, category) set, with numeric nfdr_pct."""
    valid = {c: get_valid_modules_per_iter(combined_df, c)[iteration]
             for c in CATEGORIES}
    sub = combined_df[combined_df['iteration'] == iteration].copy()
    sub['nfdr_pct'] = pd.to_numeric(sub['nfdr_pct'], errors='coerce')
    sub = sub.dropna(subset=['nfdr_pct'])
    sub = sub[sub.apply(
        lambda r: (r['disease'], r['module']) in valid.get(r['category'], set()),
        axis=1)]
    return sub


def _disease_means(combined_df, iteration):
    """Disease-mean nFDR = mean over categories of per-category disease means."""
    sub = _valid_iter_rows(combined_df, iteration)
    dcat = sub.groupby(['disease', 'category'])['nfdr_pct'].mean().reset_index()
    return dcat.groupby('disease')['nfdr_pct'].mean()


def _cat_arrays_and_means(combined_df, category):
    """Per-category: (iter1 module values, iter2 module values, m1, m2)
    where m1/m2 are disease-mean nFDRs."""
    valid = get_valid_modules_per_iter(combined_df, category)
    cat_df = combined_df[combined_df['category'] == category]
    arrs, means = {}, {}
    for it in (1, 2):
        s = cat_df[cat_df['iteration'] == it].copy()
        s['nfdr_pct'] = pd.to_numeric(s['nfdr_pct'], errors='coerce')
        s = s.dropna(subset=['nfdr_pct'])
        s = s[s.apply(lambda r: (r['disease'], r['module']) in valid[it], axis=1)]
        arrs[it] = s['nfdr_pct'].values
        means[it] = s.groupby('disease')['nfdr_pct'].mean().mean()
    return arrs[1], arrs[2], means[1], means[2]


def _paired_module_records(combined_df, category=None):
    """Paired iteration-1/2 module-category records with valid matched terms."""
    sub = combined_df if category is None else combined_df[
        combined_df['category'] == category]
    keys = ['disease', 'module', 'category']
    i1 = sub[(sub['iteration'] == 1) & (sub['new_matched'] > 0)][
        keys + ['nfdr_pct']].copy()
    i2 = sub[(sub['iteration'] == 2) & (sub['new_matched'] > 0)][
        keys + ['nfdr_pct']].copy()
    paired = i1.merge(i2, on=keys, suffixes=('_i1', '_i2'))
    paired['nfdr_pct_i1'] = pd.to_numeric(
        paired['nfdr_pct_i1'], errors='coerce')
    paired['nfdr_pct_i2'] = pd.to_numeric(
        paired['nfdr_pct_i2'], errors='coerce')
    paired = paired.dropna(subset=['nfdr_pct_i1', 'nfdr_pct_i2'])
    paired['delta'] = paired['nfdr_pct_i2'] - paired['nfdr_pct_i1']
    return paired


PASS_BIN_LABELS = ['0', '1-20', '20-40', '40-60', '60-80', '80-100']
PASS_BIN_COLORS = ['#F2F4F7', '#E2E9F0', '#C8D8E7',
                   '#9EBBD5', '#6F99BF', '#2F6F9F']


def _bin_distribution(values):
    """Return percentage distribution across fixed validation pass-rate bins."""
    bins = [-0.1, 0, 20, 40, 60, 80, 100]
    binned = pd.cut(values, bins=bins, labels=PASS_BIN_LABELS,
                    include_lowest=True)
    return (binned.value_counts(normalize=True)
            .reindex(PASS_BIN_LABELS, fill_value=0).to_numpy() * 100)


def _panel3a_feedback_result_bars(ax, combined_df):
    """Panel 3A: direct before/after result bars, matching clinical result panels."""
    rng = np.random.default_rng(2406)
    paired_all = _paired_module_records(combined_df)

    def summarize_row(label, cat, paired):
        before, before_lo, before_hi = (
            _hierarchical_gene_list_bootstrap_mean_ci(
                paired, 'nfdr_pct_i1', rng))
        after, after_lo, after_hi = (
            _hierarchical_gene_list_bootstrap_mean_ci(
                paired, 'nfdr_pct_i2', rng))
        return dict(
            label=label, cat=cat,
            before=before, before_ci=(before_lo, before_hi),
            after=after, after_ci=(after_lo, after_hi),
            delta=float(paired['delta'].mean()),
            n=len(paired),
            improved=int((paired['delta'] > 0).sum()),
        )

    rows = [summarize_row('Overall', None, paired_all)]
    for cat in CATEGORIES:
        paired = _paired_module_records(combined_df, cat)
        rows.append(summarize_row(CAT_SHORT[cat], cat, paired))

    y = np.arange(len(rows))[::-1]
    off = 0.16
    h = 0.26
    before_col = '#D9D9D9'
    after_col = ITER2_COLOR
    stat_x = 62.4
    stat_box = dict(facecolor='white', edgecolor='none',
                    alpha=0.94, pad=0.28)

    for yi, row in zip(y, rows):
        cat = row['cat']
        ax.barh(yi + off, row['before'], height=h, color=before_col,
                edgecolor='white', linewidth=0.6, zorder=3)
        ax.barh(yi - off, row['after'], height=h, color=after_col,
                edgecolor='white', linewidth=0.6, zorder=3)
        before_xerr = [[row['before'] - row['before_ci'][0]],
                       [row['before_ci'][1] - row['before']]]
        after_xerr = [[row['after'] - row['after_ci'][0]],
                      [row['after_ci'][1] - row['after']]]
        ax.errorbar(row['before'], yi + off, xerr=before_xerr, fmt='none',
                    ecolor='#777777', elinewidth=0.75, capsize=1.8, zorder=4)
        ax.errorbar(row['after'], yi - off, xerr=after_xerr, fmt='none',
                    ecolor='#1F4F73', elinewidth=0.75, capsize=1.8, zorder=4)
        label_box = dict(facecolor='white', edgecolor='none',
                         alpha=0.86, pad=0.25)
        ax.text(row['before'] + 2.0, yi + off + 0.18,
                f"{row['before']:.0f}%",
                ha='left', va='center', fontsize=6.0, color='#555555',
                bbox=label_box, zorder=6, clip_on=False)
        ax.text(row['after'] + 1.6, yi - off - 0.18,
                f"{row['after']:.0f}%",
                ha='left', va='center', fontsize=6.3,
                fontweight='bold', color=after_col,
                bbox=label_box, zorder=6, clip_on=False)
        ax.text(stat_x, yi + 0.09, f"{row['delta']:+.1f} pp",
                ha='left', va='center', fontsize=6.6,
                fontweight='bold', color=after_col, bbox=stat_box,
                zorder=7, clip_on=False)
        ax.text(stat_x, yi - 0.18,
                f"{row['improved']}/{row['n']} paired validation tests improved",
                ha='left', va='center', fontsize=5.35, color='#555555',
                bbox=stat_box, zorder=7, clip_on=False)

    ax.set_yticks(y)
    ax.set_yticklabels([r['label'] for r in rows], fontsize=7.4)
    ax.set_xlim(0, 78)
    ax.set_xticks([0, 20, 40, 60])
    ax.set_xlabel('Validation pass rate (%)', fontsize=7.8)
    ax.set_title('Category-wise pass-rate shift',
                 fontsize=9.0, fontweight='bold', pad=6)
    ax.grid(axis='x', color='#E6E6E6', linewidth=0.55, zorder=0)
    ax.set_axisbelow(True)
    ax.axvspan(60.35, 78, color='white', zorder=1.2)
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)
    ax.spines['left'].set_linewidth(0.65)
    ax.spines['bottom'].set_linewidth(0.65)
    ax.tick_params(axis='x', labelsize=7.0)
    ax.tick_params(axis='y', length=0)

    legend_y = y[0] + 0.46
    ax.plot([0.8, 2.7], [legend_y, legend_y], color=before_col,
            linewidth=4.0, solid_capstyle='butt', clip_on=False, zorder=8)
    ax.text(3.1, legend_y, 'initial GPT', ha='left', va='center',
            fontsize=5.8, color='#666666', clip_on=False, zorder=8)
    ax.plot([12.0, 13.9], [legend_y, legend_y], color=after_col,
            linewidth=4.0, solid_capstyle='butt', clip_on=False, zorder=8)
    ax.text(14.3, legend_y, 'feedback-refined GPT', ha='left', va='center',
            fontsize=5.8, color=after_col, fontweight='bold',
            clip_on=False, zorder=8)
    ax.text(27.8, legend_y, 'whiskers: 95% hierarchical bootstrap CI',
            ha='left', va='center', fontsize=5.35, color='#666666',
            clip_on=False, zorder=8)
    ax.text(stat_x, 1.055, 'Round 2 - Round 1',
            transform=ax.get_xaxis_transform(), fontsize=6.5,
            color='#333333', ha='left', va='center',
            fontweight='bold', bbox=stat_box, clip_on=False, zorder=7)


def _panel3a_category_bin_bars(ax, combined_df):
    """Panel 3A: category-resolved iteration-1/2 pass-rate-bin distributions."""
    paired_all = _paired_module_records(combined_df)
    mean1 = paired_all['nfdr_pct_i1'].mean()
    mean2 = paired_all['nfdr_pct_i2'].mean()
    mean_delta = paired_all['delta'].mean()
    improved = int((paired_all['delta'] > 0).sum())

    row_gap = 1.05
    bar_gap = 0.22
    bar_h = 0.27
    y_centers = np.arange(len(CATEGORIES))[::-1] * row_gap

    for row, cat in enumerate(CATEGORIES):
        paired = _paired_module_records(combined_df, cat)
        y_mid = y_centers[row]
        y_iter1 = y_mid + bar_gap / 2
        y_iter2 = y_mid - bar_gap / 2
        dist1 = _bin_distribution(paired['nfdr_pct_i1'])
        dist2 = _bin_distribution(paired['nfdr_pct_i2'])

        for y, dist in [(y_iter1, dist1), (y_iter2, dist2)]:
            left = 0.0
            for pct, color in zip(dist, PASS_BIN_COLORS):
                ax.barh(y, pct, left=left, height=bar_h, color=color,
                        edgecolor='white', linewidth=0.45)
                if pct >= 9:
                    txt_color = 'white' if color == PASS_BIN_COLORS[-1] else '#333333'
                    ax.text(left + pct / 2, y, f'{pct:.0f}',
                            ha='center', va='center', fontsize=5.6,
                            color=txt_color)
                left += pct

        c_mean1 = paired['nfdr_pct_i1'].mean()
        c_mean2 = paired['nfdr_pct_i2'].mean()
        c_delta = paired['delta'].mean()
        c_up = int((paired['delta'] > 0).sum())
        ax.text(-7.3, y_mid, CAT_SHORT[cat], ha='right', va='center',
                fontsize=7.2, fontweight='bold', color='#303030')
        ax.text(103.0, y_mid + 0.02,
                f'{c_mean1:.0f}→{c_mean2:.0f}%  {c_delta:+.1f} pp',
                ha='left', va='center', fontsize=6.4, fontweight='bold',
                color=ITER2_COLOR)
        ax.text(103.0, y_mid - 0.30,
                f'{c_up}/{len(paired)} improved',
                ha='left', va='center', fontsize=5.8, color='#555555')

    top_y = y_centers[0] + 0.50
    ax.text(50, top_y + 0.42,
            f'mean {mean1:.0f}→{mean2:.0f}%  ({mean_delta:+.1f} pp)',
            ha='center', va='bottom', fontsize=8.0,
            fontweight='bold', color=ITER2_COLOR)
    ax.text(50, top_y + 0.12,
            f'{improved}/{len(paired_all)} paired tests improved',
            ha='center', va='bottom', fontsize=6.8, color='#444444')
    ax.text(-1.7, top_y, 'Round 1', ha='right', va='center',
            fontsize=6.4, color='#555555')
    ax.text(-1.7, top_y - bar_gap, 'Round 2', ha='right', va='center',
            fontsize=6.4, color='#555555')
    for y_mid in y_centers:
        ax.text(-1.7, y_mid + bar_gap / 2, '1', ha='right', va='center',
                fontsize=5.9, color='#777777')
        ax.text(-1.7, y_mid - bar_gap / 2, '2', ha='right', va='center',
                fontsize=5.9, color='#777777')

    ax.set_title('Category-wise redistribution across validation pass-rate bins',
                 fontsize=10.4, fontweight='bold', pad=5)
    ax.set_xlim(-11, 124)
    ax.set_ylim(y_centers[-1] - 0.48, top_y + 0.78)
    ax.set_xticks([0, 25, 50, 75, 100])
    ax.set_xlabel('')
    ax.set_yticks([])
    ax.grid(axis='x', color='#E4E4E4', linewidth=0.5)
    ax.set_axisbelow(True)
    for side in ['top', 'right', 'left']:
        ax.spines[side].set_visible(False)
    ax.spines['bottom'].set_linewidth(0.75)


def _panel3a_category_summary_matrix(ax, combined_df):
    """Panel 3A: category matrix aligned with the zero-shot size panel."""
    from matplotlib.patches import FancyBboxPatch

    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis('off')

    paired_all = _paired_module_records(combined_df)
    mean1 = paired_all['nfdr_pct_i1'].mean()
    mean2 = paired_all['nfdr_pct_i2'].mean()
    mean_delta = paired_all['delta'].mean()
    improved = int((paired_all['delta'] > 0).sum())

    rows = []
    for cat in CATEGORIES:
        paired = _paired_module_records(combined_df, cat)
        rows.append(dict(
            cat=cat,
            means=[paired['nfdr_pct_i1'].mean(),
                   paired['nfdr_pct_i2'].mean()],
            counts=[len(paired), len(paired)],
            delta=paired['delta'].mean(),
            meta=f'{int((paired["delta"] > 0).sum())}/{len(paired)} improved',
        ))

    all_means = np.array([v for row in rows for v in row['means']
                          if np.isfinite(v)])
    vmin = max(0.0, float(np.nanpercentile(all_means, 5)) - 3.0)
    vmax = min(70.0, float(np.nanpercentile(all_means, 95)) + 3.0)
    if vmax <= vmin:
        vmax = vmin + 1.0
    low = np.array(to_rgba('#F4F8FB'))
    high = np.array(to_rgba('#2F6F9F'))

    def _rate_color(value):
        t = np.clip((value - vmin) / (vmax - vmin), 0, 1)
        return tuple(low * (1 - t) + high * t), t

    ax.text(0.012, 0.985, 'Feedback gains are category-consistent',
            ha='left', va='top', transform=ax.transAxes,
            fontsize=10.4, fontweight='bold', color='#111111')
    ax.text(0.012, 0.905,
            f'mean {mean1:.0f}->{mean2:.0f}% ({mean_delta:+.1f} pp); '
            f'{improved}/{len(paired_all)} paired validation tests improved',
            ha='left', va='top', transform=ax.transAxes,
            fontsize=7.0, color='#555555')

    x0, x_gap, cell_w = 0.245, 0.180, 0.132
    y0, y_gap, cell_h = 0.712, 0.116, 0.088
    col_labels = [('Round 1', 'before feedback'),
                  ('Round 2', 'after feedback')]
    for j, (main, sub) in enumerate(col_labels):
        cx = x0 + j * x_gap + cell_w / 2
        ax.text(cx, 0.825, f'{main}\n{sub}',
                ha='center', va='bottom', transform=ax.transAxes,
                fontsize=6.1, color='#333333', linespacing=0.90)
    ax.text(x0 + 0.5 * x_gap + cell_w / 2, 0.900,
            'Category mean pass rate',
            ha='center', va='bottom', transform=ax.transAxes,
            fontsize=6.5, fontweight='bold', color='#333333')

    arrow_y = 0.776
    ax.annotate('', xy=(x0 + x_gap - 0.020, arrow_y),
                xytext=(x0 + cell_w + 0.020, arrow_y),
                xycoords=ax.transAxes, textcoords=ax.transAxes,
                arrowprops=dict(arrowstyle='-|>', lw=0.8,
                                color='#9A9A9A', mutation_scale=7.5))

    delta_x = 0.725
    ax.text(delta_x, 0.825, 'Round 2 - 1\n(pp)',
            ha='center', va='bottom', transform=ax.transAxes,
            fontsize=6.1, color='#333333', linespacing=0.90)

    for i, row in enumerate(rows):
        y = y0 - i * y_gap
        cat = row['cat']
        ax.add_patch(plt.Rectangle(
            (0.070, y - cell_h / 2), 0.010, cell_h,
            transform=ax.transAxes, facecolor=CAT_COLORS[cat],
            edgecolor='none', zorder=2))
        ax.text(0.095, y, CAT_SHORT[cat],
                ha='left', va='center', transform=ax.transAxes,
                fontsize=7.0, fontweight='bold', color='#333333')

        for j, value in enumerate(row['means']):
            x = x0 + j * x_gap
            face, t = _rate_color(value)
            text_col = 'white' if t > 0.64 else '#202020'
            sub_col = '#F0F4F7' if t > 0.64 else '#5F6670'
            ax.add_patch(FancyBboxPatch(
                (x, y - cell_h / 2), cell_w, cell_h,
                boxstyle='round,pad=0.002,rounding_size=0.010',
                transform=ax.transAxes, facecolor=face,
                edgecolor='white', linewidth=0.75, zorder=2))
            ax.text(x + cell_w * 0.505, y, f'{value:.0f}%',
                    ha='right', va='center', transform=ax.transAxes,
                    fontsize=7.0, fontweight='bold', color=text_col,
                    zorder=3)
            ax.text(x + cell_w * 0.535, y,
                    f'n={row["counts"][j]}',
                    ha='left', va='center', transform=ax.transAxes,
                    fontsize=4.75, color=sub_col, zorder=3)

        delta = row['delta']
        dcol = ITER2_COLOR if delta > 0 else '#B65B4D'
        ax.text(delta_x, y + 0.016, f'{delta:+.1f}',
                ha='left', va='center', transform=ax.transAxes,
                fontsize=6.3, fontweight='bold', color=dcol)
        ax.text(delta_x, y - 0.024, row['meta'],
                ha='left', va='center', transform=ax.transAxes,
                fontsize=5.3, color='#555555')

    grad_x, grad_y, grad_w, grad_h = x0, 0.070, 0.235, 0.024
    for k in range(60):
        value = vmin + (vmax - vmin) * k / 59
        face, _ = _rate_color(value)
        ax.add_patch(plt.Rectangle(
            (grad_x + grad_w * k / 60, grad_y), grad_w / 60, grad_h,
            transform=ax.transAxes, facecolor=face, edgecolor='none',
            zorder=2))
    ax.text(grad_x, grad_y + grad_h + 0.018, 'Mean pass rate (%)',
            ha='left', va='bottom', transform=ax.transAxes,
            fontsize=5.8, color='#555555')
    for value, xoff in [(vmin, 0), ((vmin + vmax) / 2, 0.5), (vmax, 1)]:
        ax.text(grad_x + grad_w * xoff, grad_y - 0.014, f'{value:.0f}',
                ha='center', va='top', transform=ax.transAxes,
                fontsize=5.1, color='#666666')
    ax.text(0.545, 0.072,
            'Round 2 - 1 reports feedback-associated pass-rate gain.',
            ha='left', va='center', transform=ax.transAxes,
            fontsize=5.8, color='#666666')


def _panel3b_scatter(ax, combined_df, ax_stats=None):
    """Panel 3B: restrained forest/strip plot of category-level gains."""
    paired = _paired_module_records(combined_df)
    rng = np.random.default_rng(7)
    data = [paired.loc[paired['category'] == cat, 'delta'].to_numpy()
            for cat in CATEGORIES]
    y_pos = np.arange(len(CATEGORIES))[::-1]
    stats_rows = []

    ax.axvspan(0, 105, color=ITER2_COLOR, alpha=0.045, zorder=0)
    ax.axvspan(-105, 0, color='#B6403A', alpha=0.028, zorder=0)
    ax.axvline(0, color='#4D4D4D', linestyle='--', linewidth=0.85, zorder=2)
    for y in y_pos:
        ax.axhline(y, color='#E8E8E8', linewidth=0.45, zorder=0)

    for y, (cat, vals) in zip(y_pos, zip(CATEGORIES, data)):
        vals = np.asarray(vals, dtype=float)
        jitter = rng.normal(0, 0.060, len(vals))
        ax.scatter(vals, y + jitter, s=7.5, color='#4D4D4D',
                   edgecolors='none', alpha=0.16, zorder=3)
        mean = float(np.nanmean(vals))
        sem = float(np.nanstd(vals, ddof=1) / np.sqrt(len(vals)))
        ci = 1.96 * sem
        up_pct = float(np.mean(vals > 0) * 100)
        stats_rows.append((y, mean, up_pct))
        ax.errorbar(mean, y, xerr=ci, fmt='s', markersize=5.4,
                    color=ITER2_COLOR, markerfacecolor='white',
                    markeredgecolor=ITER2_COLOR, markeredgewidth=1.0,
                    ecolor=ITER2_COLOR, elinewidth=1.05, capsize=2.4,
                    zorder=5)

    n_up = int((paired['delta'] > 0).sum())
    ax.set_xlim(-105, 105)
    ax.set_ylim(-0.65, len(CATEGORIES) - 0.35)
    ax.set_xticks([-100, -50, 0, 50, 100])
    ax.set_yticks(y_pos)
    ax.set_yticklabels([CAT_SHORT[c] for c in CATEGORIES],
                       fontweight='bold')
    ax.set_xlabel('Validation pass-rate gain (round 2 - round 1, pp)')
    ax.set_title('Paired-test gain distribution by category',
                 fontsize=10.5, fontweight='bold', pad=6)
    ax.text(0.5, -0.205,
            f'{n_up}/{len(paired)} paired validation tests improved; '
            f'mean gain {paired["delta"].mean():+.1f} pp',
            transform=ax.transAxes, ha='center', va='top', fontsize=8.6,
            fontweight='bold', color=ITER2_COLOR)
    ax.text(0.5, -0.285,
            'paired test = same disease, gene list and pathway category in both rounds',
            transform=ax.transAxes, ha='center', va='top', fontsize=6.0,
            color='#666666')
    ax.grid(axis='x', color='#E2E2E2', linewidth=0.5, alpha=0.8)
    ax.set_axisbelow(True)
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)

    if ax_stats is not None:
        ax_stats.set_ylim(ax.get_ylim())
        ax_stats.set_xlim(0, 1)
        ax_stats.axis('off')
        ax_stats.axvline(0.02, color='#D0D0D0', linewidth=0.65)
        ax_stats.text(0.08, 1.02, 'category mean gain',
                      transform=ax_stats.transAxes, ha='left', va='bottom',
                      fontsize=6.4, fontweight='bold', color='#333333')
        ax_stats.text(0.08, 0.96, 'validation tests\nimproved',
                      transform=ax_stats.transAxes, ha='left', va='bottom',
                      fontsize=5.45, color='#666666', linespacing=0.95)
        y_transform = ax_stats.get_yaxis_transform()
        for y, mean, up_pct in stats_rows:
            ax_stats.text(0.08, y + 0.13, f'{mean:+.1f} pp',
                          transform=y_transform, ha='left', va='center',
                          fontsize=6.4, fontweight='bold',
                          color=ITER2_COLOR)
            ax_stats.text(0.08, y - 0.15, f'{up_pct:.0f}% improved',
                          transform=y_transform, ha='left', va='center',
                          fontsize=5.7, color='#555555')


def _panel3c_disease_scatter(ax, combined_df):
    """Panel 3C: paired scatter of the 24 disease-mean pass rates."""
    d1, d2 = _disease_means(combined_df, 1), _disease_means(combined_df, 2)
    both = pd.DataFrame({'i1': d1, 'i2': d2}).dropna()
    hi = max(both.values.max() * 1.06, 72)

    ax.plot([0, hi], [0, hi], color='#9A9A9A', linestyle='--',
            linewidth=1.0, zorder=2)
    ax.fill_between([0, hi], [0, hi], [hi, hi], color='#2E7D32',
                    alpha=0.05, zorder=0)
    n_up = int((both.i2 > both.i1).sum())
    for dis, row in both.iterrows():
        up = row.i2 > row.i1
        ax.scatter(row.i1, row.i2, s=28,
                   color=(ITER2_COLOR if up else '#C62828'),
                   edgecolors='white', linewidths=0.5, alpha=0.92, zorder=5)

    notable = {'TB': (6, -4), 'HF': (5, 3), 'OSA': (5, -12),
               'ALS': (5, 5), 'AF': (5, 4)}
    for dis, (dx, dy) in notable.items():
        if dis in both.index:
            label = textwrap.fill(DISEASE_FULL_NAMES.get(dis, dis), width=21)
            ax.annotate(label, (both.loc[dis, 'i1'], both.loc[dis, 'i2']),
                        xytext=(dx, dy), textcoords='offset points',
                        fontsize=5.9, fontweight='bold', color='#333333',
                        ha='left' if dx >= 0 else 'right',
                        bbox=dict(facecolor='white', edgecolor='none',
                                  alpha=0.78, pad=0.6))

    ax.set_xlim(0, hi)
    ax.set_ylim(0, hi)
    ax.set_aspect('equal')
    ax.set_xlabel('Round 1 disease-mean pass rate (%)')
    ax.set_ylabel('Round 2 disease-mean pass rate (%)')
    ax.set_title('Disease-level feedback response', fontsize=10.5,
                 fontweight='bold', pad=6)
    ax.text(0.56, 0.955, 'above diagonal = improved after feedback',
            transform=ax.transAxes, ha='left', va='top',
            fontsize=6.7, color='#2E7D32',
            bbox=dict(facecolor='white', edgecolor='none', alpha=0.78, pad=0.15))
    ax.text(0.5, -0.205, f'{n_up}/{len(both)} diseases improved',
            transform=ax.transAxes, ha='center', va='top', fontsize=8.6,
            fontweight='bold', color=ITER2_COLOR)
    ax.grid(True, color='#E2E2E2', linewidth=0.5, alpha=0.7)
    ax.set_axisbelow(True)
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)


def _iteration_category_stats(metrics_df, disease, module, iteration):
    """Category-level pass fractions for one disease-module iteration."""
    sub = metrics_df[
        (metrics_df['disease'] == disease) &
        (metrics_df['module'] == module) &
        (metrics_df['iteration'] == iteration)
    ]
    stats, included = [], []
    for cat in CATEGORIES:
        row = sub[sub['category'] == cat]
        if len(row) == 0:
            stats.append(dict(cat=cat, matched=0, passed=0, rate=np.nan))
            continue
        matched = int(row['new_matched'].iloc[0])
        rate = float(row['nfdr_pct'].iloc[0]) if matched > 0 else np.nan
        passed = int(round(rate * matched / 100.0)) if matched > 0 else 0
        if matched > 0:
            included.append(rate)
        stats.append(dict(cat=cat, matched=matched, passed=passed, rate=rate))
    mean_rate = float(np.mean(included)) if included else np.nan
    return stats, mean_rate


def _draw_feedback_radar(ax, bounds, stats1, stats2):
    """Compact two-iteration radar plot inside Panel 3C."""
    parent = ax.get_position()
    fig_bounds = [
        parent.x0 + bounds[0] * parent.width,
        parent.y0 + bounds[1] * parent.height,
        bounds[2] * parent.width,
        bounds[3] * parent.height,
    ]
    rax = ax.figure.add_axes(fig_bounds, projection='polar')
    rax.set_zorder(3)
    labels = ['BP', 'MF', 'CC', 'KEGG', 'REAC']
    angles = np.linspace(0, 2 * np.pi, len(labels), endpoint=False)

    def _vals(stats):
        return np.array([0.0 if np.isnan(s['rate']) else s['rate'] / 100.0
                         for s in stats])

    for vals, color, alpha, lw in [
            (_vals(stats1), ITER1_COLOR, 0.18, 1.0),
            (_vals(stats2), ITER2_COLOR, 0.16, 1.4)]:
        rax.plot(np.r_[angles, angles[0]], np.r_[vals, vals[0]],
                 color=color, linewidth=lw)
        rax.fill(np.r_[angles, angles[0]], np.r_[vals, vals[0]],
                 color=color, alpha=alpha)

    rax.set_theta_offset(np.pi / 2)
    rax.set_theta_direction(-1)
    rax.set_ylim(0, 1.0)
    rax.set_xticks(angles)
    rax.set_xticklabels(labels, fontsize=5.2, color='#555555')
    rax.set_yticks([0.5, 1.0])
    rax.set_yticklabels(['50', '100'], fontsize=5.0, color='#777777')
    rax.tick_params(pad=-1.2)
    rax.grid(color='#D8D8D8', linewidth=0.45)
    rax.spines['polar'].set_color('#BDBDBD')
    rax.set_facecolor('white')
    return rax


def _ranked_gpt_entries(disease, module, iteration, terms):
    """Return displayed terms with original GPT rank, ID and FDR status."""
    cat_by_rank = ['GO:BP'] * 10 + ['GO:MF'] * 10 + ['GO:CC'] * 10 + \
        ['KEGG'] * 10 + ['REAC'] * 10
    base = os.path.join(MEMBANK_DIR, f"iterative_feedback_{disease}",
                        "gpt_led_analysis_ag2_hitl")
    path = os.path.join(
        base, f"{disease}_Module_{module}_iter{iteration}_gpt_prediction.json")
    try:
        with open(path) as fh:
            pred = json.load(fh)
        details = pred.get('pathway_details', {})
    except Exception:
        details = {}
    names = list(details.keys())
    lower_to_name = {str(name).lower(): name for name in names}
    pathway_status = load_pair_pathway_status(
        disease, module, iteration=iteration)

    entries = []
    for term in terms:
        name = lower_to_name.get(str(term).lower(), term)
        rank = names.index(name) + 1 if name in names else len(entries) + 1
        meta = details.get(name, {})
        cat = meta.get('source') if isinstance(meta, dict) else None
        if cat not in CATEGORIES:
            cat = cat_by_rank[rank - 1] if rank <= len(cat_by_rank) else 'GO:BP'
        native_id = ''
        if isinstance(meta, dict):
            native_id = meta.get('go_id') or meta.get('pathway_id') or ''
        entries.append(dict(
            rank=rank, name=_LABEL_OVERRIDE.get(name, name), cat=cat,
            native_id=native_id or 'ID not reported',
            status=pathway_status.get(name, 'none')))
    return sorted(entries, key=lambda item: item['rank'])


def _panel3c_cases(ax, combined_df):
    """Panel 3D: one feedback case with before/after GPT rankings."""
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis('off')

    ex = dict(
        disease='RA', module=59, genes=28,
        note='one retained term plus newly FDR-supported candidates',
        iter1=[
            'cell adhesion',
            'angiogenesis',
            'nucleus',
            'MAPK signaling pathway',
            'Integrin cell surface interactions',
        ],
        iter2=[
            'nucleus',
            'negative regulation of apoptotic process',
            'transcription coactivator activity',
            'transcription regulator complex',
            'Gene expression (Transcription)',
        ],
    )
    stats1, mean1 = _iteration_category_stats(
        combined_df, ex['disease'], ex['module'], 1)
    stats2, mean2 = _iteration_category_stats(
        combined_df, ex['disease'], ex['module'], 2)
    entries1 = _ranked_gpt_entries(
        ex['disease'], ex['module'], 1, ex['iter1'])
    entries2 = _ranked_gpt_entries(
        ex['disease'], ex['module'], 2, ex['iter2'])
    for entry in entries2:
        if entry['name'].lower() == 'nucleus':
            entry['name'] = 'nucleus (retained)'

    ax.add_patch(plt.Rectangle(
        (0.010, 0.035), 0.982, 0.920, transform=ax.transAxes,
        facecolor='#FBFBFB', edgecolor='#E2E2E2', linewidth=0.8, zorder=1))
    ax.add_patch(plt.Rectangle(
        (0.010, 0.035), 0.012, 0.920, transform=ax.transAxes,
        facecolor='#2E7D32', edgecolor='none', zorder=2))

    ax.text(0.500, 0.932, 'Traceable feedback case',
            fontsize=10.0, fontweight='bold', color='#111111',
            ha='center', va='center', transform=ax.transAxes, zorder=3)
    ax.text(0.035, 0.892,
            'RA gene list: round-1 outcome and second-pass refinement',
            fontsize=6.5, color='#333333', ha='left', va='center',
            transform=ax.transAxes,
            bbox=dict(boxstyle='round,pad=0.28', facecolor='white',
                      edgecolor='#4D4D4D', linewidth=0.7))
    ax.text(0.035, 0.832,
            f"{DISEASE_FULL_NAMES.get(ex['disease'], ex['disease'])}\n"
            f"gene list {ex['module']} · {ex['genes']} genes",
            fontsize=6.9, color='#555555', ha='left', va='center',
            linespacing=1.05, transform=ax.transAxes)
    ax.text(0.820, 0.913, f"{mean1:.0f}%",
            fontsize=11.0, fontweight='bold', color='#2E7D32',
            ha='right', va='center', transform=ax.transAxes)
    ax.annotate('', xy=(0.905, 0.913), xytext=(0.842, 0.913),
                xycoords=ax.transAxes, textcoords=ax.transAxes,
                arrowprops=dict(arrowstyle='-|>', color='#2E7D32',
                                lw=0.90, mutation_scale=7.5,
                                shrinkA=0, shrinkB=0))
    ax.text(0.925, 0.913, f"{mean2:.0f}%",
            fontsize=11.0, fontweight='bold', color='#2E7D32',
            ha='left', va='center', transform=ax.transAxes)
    ax.text(0.965, 0.872, 'mean over matched categories',
            fontsize=5.9, color='#777777', ha='right', va='center',
            transform=ax.transAxes)

    _draw_feedback_radar(ax, [0.070, 0.392, 0.145, 0.286], stats1, stats2)
    ax.text(0.152, 0.340, 'category pass-rate profile',
            fontsize=6.2, color='#666666', ha='center', va='center',
            transform=ax.transAxes)
    ax.plot([0.090, 0.122], [0.302, 0.302], color=ITER1_COLOR, linewidth=1.2,
            transform=ax.transAxes)
    ax.text(0.130, 0.302, 'round 1', fontsize=6.1, color='#666666',
            va='center', transform=ax.transAxes)
    ax.plot([0.090, 0.122], [0.270, 0.270], color=ITER2_COLOR, linewidth=1.4,
            transform=ax.transAxes)
    ax.text(0.130, 0.270, 'round 2', fontsize=6.1, color='#666666',
            va='center', transform=ax.transAxes)

    def _draw_mean_box(x0, y0, w, h, title, stats, mean_rate, color):
        ax.add_patch(plt.Rectangle(
            (x0, y0), w, h, transform=ax.transAxes,
            facecolor='white', edgecolor='#707070', linewidth=0.7, zorder=2))
        ax.text(x0 + 0.018, y0 + h - 0.036,
                f"{title}: {mean_rate:.0f}%",
                fontsize=7.0, fontweight='bold', color=color,
                ha='left', va='center', transform=ax.transAxes, zorder=3)
        bx0, bx1 = x0 + 0.018, x0 + w - 0.020
        by = y0 + h - 0.065
        ax.add_patch(plt.Rectangle(
            (bx0, by - 0.005), bx1 - bx0, 0.010,
            transform=ax.transAxes, facecolor='#ECECEC',
            edgecolor='none', zorder=2))
        ax.add_patch(plt.Rectangle(
            (bx0, by - 0.005), (bx1 - bx0) * mean_rate / 100.0, 0.010,
            transform=ax.transAxes, facecolor=color, edgecolor='none',
            zorder=3))
        y = y0 + h - 0.098
        gap = 0.041
        for s in stats:
            if s['matched'] == 0 or np.isnan(s['rate']):
                label = f"{s['cat']}: n/a"
                txt_color = '#8A8A8A'
            else:
                label = (f"{s['cat']}: {s['passed']}/{s['matched']} "
                         f"pass ({s['rate']:.0f}%)")
                txt_color = '#333333'
            ax.add_patch(plt.Rectangle(
                (x0 + 0.018, y - 0.006), 0.009, 0.009,
                transform=ax.transAxes, facecolor=CAT_COLORS[s['cat']],
                edgecolor='none', zorder=3))
            ax.text(x0 + 0.034, y, label, fontsize=5.8, color=txt_color,
                    ha='left', va='center', transform=ax.transAxes, zorder=3)
            y -= gap

    def _draw_ranking_box(x0, y0, w, h, title, entries, color):
        from matplotlib.patches import FancyBboxPatch

        ax.add_patch(plt.Rectangle(
            (x0, y0), w, h, transform=ax.transAxes,
            facecolor='white', edgecolor='#707070', linewidth=0.7, zorder=2))
        ax.text(x0 + 0.018, y0 + h - 0.036, title,
                fontsize=7.0, fontweight='bold', color=color,
                ha='left', va='center', transform=ax.transAxes, zorder=3)
        y = y0 + h - 0.083
        gap = (h - 0.105) / max(len(entries), 1)
        for entry in entries:
            cat_label = CAT_SHORT.get(entry['cat'], entry['cat'])
            tag_w = 0.038 if len(cat_label) <= 2 else 0.056
            tag_h = 0.025
            tag_x = x0 + 0.044
            ax.text(x0 + 0.020, y, str(entry['rank']),
                    fontsize=5.6, fontweight='bold', color='#555555',
                    ha='center', va='center', transform=ax.transAxes, zorder=3,
                    bbox=dict(boxstyle='circle,pad=0.16', facecolor='#F2F2F2',
                              edgecolor='#BDBDBD', linewidth=0.45))
            ax.add_patch(FancyBboxPatch(
                (tag_x, y - tag_h / 2), tag_w, tag_h,
                boxstyle='round,pad=0.0015,rounding_size=0.0045',
                transform=ax.transAxes,
                facecolor=to_rgba(CAT_COLORS[entry['cat']], 0.13),
                edgecolor=CAT_COLORS[entry['cat']], linewidth=0.50, zorder=3))
            ax.text(tag_x + tag_w / 2, y, cat_label,
                    fontsize=4.55, fontweight='bold',
                    color=CAT_COLORS[entry['cat']], ha='center', va='center',
                    transform=ax.transAxes, zorder=4)
            tx = tag_x + tag_w + 0.010
            status_label = {
                'sig': 'FDR+', 'broad': 'FDR-', 'none': 'unmatched'
            }.get(entry.get('status'), 'unmatched')
            status_color = {
                'sig': '#2E7D32', 'broad': '#A04A4A', 'none': '#777777'
            }.get(entry.get('status'), '#777777')
            ax.text(tx, y + 0.006,
                    _single_line_pathway_label(entry['name'], width=40),
                    fontsize=4.8, color='#333333', ha='left', va='center',
                    transform=ax.transAxes, zorder=3)
            ax.text(tx, y - 0.013, entry['native_id'], fontsize=4.45,
                    color='#777777', ha='left', va='center',
                    transform=ax.transAxes, zorder=3)
            ax.text(x0 + w - 0.012, y, status_label,
                    fontsize=4.45, fontweight='bold', color=status_color,
                    ha='right', va='center', transform=ax.transAxes, zorder=4)
            y -= gap

    mean_x, mean_w = 0.245, 0.325
    rank_x, rank_w = 0.595, 0.390
    row_h = 0.312
    _draw_mean_box(mean_x, 0.535, mean_w, row_h,
                   'Round 1 before feedback', stats1, mean1, '#A04A4A')
    _draw_ranking_box(rank_x, 0.535, rank_w, row_h,
                      'Round 1 candidate examples', entries1, '#A04A4A')
    _draw_mean_box(mean_x, 0.150, mean_w, row_h,
                   'Round 2 after feedback', stats2, mean2, '#2E7D32')
    _draw_ranking_box(rank_x, 0.150, rank_w, row_h,
                      'FDR-supported round 2 examples', entries2, '#2E7D32')

    ax.text(0.785, 0.493, 'feedback',
            transform=ax.transAxes, ha='center', va='center',
            fontsize=5.7, color='#8A8A8A')


def generate_nfdr_trend_composite(combined_df):
    """Generate the feedback-improvement composite figure."""
    plt.rcParams.update({
        'font.family': 'sans-serif',
        'font.sans-serif': ['Arial', 'Helvetica', 'DejaVu Sans'],
        'pdf.fonttype': 42,
        'ps.fonttype': 42,
        'svg.fonttype': 'none',
        'axes.linewidth': 0.8,
        'axes.labelsize': 9.5,
        'xtick.labelsize': 8.4,
        'ytick.labelsize': 8.4,
    })

    fig = plt.figure(figsize=(13.2, 8.8))
    fig.patch.set_facecolor('white')
    outer = fig.add_gridspec(
        2, 2, height_ratios=[0.98, 1.14], width_ratios=[1.0, 1.0],
        hspace=0.35, wspace=0.24,
        left=0.068, right=0.982, top=0.890, bottom=0.075)
    axA = fig.add_subplot(outer[0, 0])
    gsB = outer[0, 1].subgridspec(
        1, 2, width_ratios=[0.80, 0.20], wspace=0.16)
    axB = fig.add_subplot(gsB[0, 0])
    axBstats = fig.add_subplot(gsB[0, 1])
    axC = fig.add_subplot(outer[1, 0])
    axD = fig.add_subplot(outer[1, 1])

    _panel3a_feedback_result_bars(axA, combined_df)
    _panel3b_scatter(axB, combined_df, axBstats)
    _panel3c_disease_scatter(axC, combined_df)
    _panel3c_cases(axD, combined_df)

    label_kw = dict(fontsize=12.5, fontweight='bold',
                    ha='left', va='bottom')
    fig.text(0.030, 0.890, 'a', **label_kw)
    fig.text(0.520, 0.890, 'b', **label_kw)
    fig.text(0.030, 0.455, 'c', **label_kw)
    fig.text(0.520, 0.455, 'd', **label_kw)

    fig.suptitle('Statistical feedback makes GPT pathway hypotheses more reliable',
                 x=0.5, y=0.965,
                 ha='center', fontsize=12.4, fontweight='bold')

    for fmt in ['pdf', 'png', 'svg']:
        fpath = os.path.join(OUTPUT_DIR, f'nfdr_trend_composite.{fmt}')
        fig.savefig(fpath, dpi=600 if fmt == 'png' else 300,
                    bbox_inches='tight', pad_inches=0.055, facecolor='white')
        print(f"  ✅ {fpath}")
    plt.close(fig)


# ═══════════════════════════════════════════════════════════════════════
#  Figure 2: gpt_fdr_performance_overview  (4-panel: 2A–2D)
# ═══════════════════════════════════════════════════════════════════════

def generate_fdr_performance_overview(combined_df):
    """Generate the zero-shot (iter 1) validation overview as a 4-panel figure."""
    import matplotlib.gridspec as gridspec

    plt.rcParams.update({
        'font.family': 'sans-serif',
        'font.sans-serif': ['Arial', 'Helvetica', 'DejaVu Sans'],
        'pdf.fonttype': 42, 'ps.fonttype': 42, 'svg.fonttype': 'none',
        'axes.linewidth': 0.75, 'axes.labelsize': 8.2,
        'xtick.labelsize': 7.6, 'ytick.labelsize': 7.6,
    })

    iter1_df = combined_df[combined_df['iteration'] == 1].copy()
    grid_color = '#D9D9D9'

    # ── Compute valid modules per category ────────────────────────────
    valid_modules = {}
    for cat in CATEGORIES:
        cat_df = iter1_df[iter1_df['category'] == cat]
        valid = cat_df[cat_df['new_matched'] > 0]
        valid_modules[cat] = set(zip(valid['disease'], valid['module']))

    all_dm_pairs = set()
    for cat in CATEGORIES:
        all_dm_pairs |= valid_modules[cat]
    num_modules = len(all_dm_pairs)
    num_diseases = len(DISEASES)
    total_evaluated = sum(len(valid_modules[c]) for c in CATEGORIES)

    # ── Collect per-category module-level validation-pass arrays ──────
    cat_data = {}
    cat_disease_avgs = {}
    for cat in CATEGORIES:
        cat_df = iter1_df[iter1_df['category'] == cat]
        valid = valid_modules[cat]
        cat_df = cat_df[cat_df.apply(
            lambda r: (r['disease'], r['module']) in valid, axis=1)]
        cat_data[cat] = pd.to_numeric(
            cat_df['nfdr_pct'], errors='coerce').dropna().values
        d_avgs = []
        for disease in DISEASES:
            d_df = cat_df[cat_df['disease'] == disease]
            if len(d_df) > 0:
                d_avgs.append(
                    pd.to_numeric(d_df['nfdr_pct'], errors='coerce').mean())
        cat_disease_avgs[cat] = d_avgs

    overall_avg_all = np.mean(
        [np.mean(cat_disease_avgs[c]) for c in CATEGORIES
         if cat_disease_avgs[c]])

    # ── Figure layout ─────────────────────────────────────────────────
    fig = plt.figure(figsize=(7.6, 9.85))
    fig.patch.set_facecolor('white')
    gs = gridspec.GridSpec(
        4, 1,
        height_ratios=[1.05, 0.92, 1.06, 1.58],
        hspace=0.40,
        left=0.116, right=0.986, top=0.890, bottom=0.055)
    ax_a = fig.add_subplot(gs[0, 0])
    ax_b = fig.add_subplot(gs[1, 0])
    ax_c = fig.add_subplot(gs[2, 0])
    ax_d = fig.add_subplot(gs[3, 0])

    # ══════════════════════════════════════════════════════════════════
    #  Panels 2A–2B — Distribution + category-level summary
    # ══════════════════════════════════════════════════════════════════
    _panel2a_density_plot(ax_a, cat_data, combined_df)
    _panel2b_category_boxplot(ax_b, cat_disease_avgs)

    # ══════════════════════════════════════════════════════════════════
    #  Panel 2C — Validation pass rate vs. gene-list size
    # ══════════════════════════════════════════════════════════════════
    if os.path.exists(MODSIZE_CSV):
        ms_df = pd.read_csv(MODSIZE_CSV)
        ms_iter1 = ms_df[
            (ms_df['iteration'] == 1) & (ms_df['new_matched'] > 0)].copy()
    else:
        ms_iter1 = pd.DataFrame()

    _draw_size_strata_panel(ax_c, ms_iter1)

    # ══════════════════════════════════════════════════════════════════
    #  Panel 2D — Example gene lists: fluent names, variable validation
    # ══════════════════════════════════════════════════════════════════
    # Two real disease-module pairs spanning the validation-pass range. Each shows the
    # actual GPT-generated pathway names and whether each is statistically
    # enriched (FDR < 0.05) for that specific gene list. The same fluent term
    # (e.g. "vesicle-mediated transport") validates for one gene list but not
    # another — biological specificity, not naming, is the limiting factor.
    _draw_case_examples_panel(ax_d, iter1_df)
    ax_d.set_title('Representative validation outcomes',
                   fontsize=8.9, fontweight='bold', pad=5)

    # ── Panel labels ──────────────────────────────────────────────────
    label_pos = {
        'a': (-0.060, 1.045),
        'b': (-0.060, 1.045),
        'c': (-0.060, 1.045),
        'd': (-0.030, 1.035),
    }
    for ax, lbl in [(ax_a, 'a'), (ax_b, 'b'), (ax_c, 'c'), (ax_d, 'd')]:
        ax.text(*label_pos[lbl], lbl, transform=ax.transAxes,
                fontsize=11.2, fontweight='bold', ha='left', va='bottom')

    # ── Shared ontology colour key (top, spans all four panels) ────────
    from matplotlib.lines import Line2D
    cat_handles = [
        Line2D([0], [0], color=CAT_COLORS[c], marker='o', markersize=6,
               markerfacecolor=CAT_COLORS[c], markeredgecolor='white',
               markeredgewidth=0.5, linewidth=2.2, label=c)
        for c in CATEGORIES]
    fig.legend(handles=cat_handles, loc='upper center',
               bbox_to_anchor=(0.5, 0.942), ncol=5, frameon=False,
               fontsize=7.8, handlelength=1.55, columnspacing=1.7,
               handletextpad=0.45)

    fig.suptitle('Statistical validation of GPT-generated pathway hypotheses',
                 x=0.5, y=0.982, ha='center',
                 fontsize=10.8, fontweight='bold')

    # ── Save ──────────────────────────────────────────────────────────
    for fmt in ['pdf', 'png', 'svg']:
        fpath = os.path.join(
            OUTPUT_DIR, f'gpt_fdr_performance_overview.{fmt}')
        fig.savefig(fpath, dpi=600 if fmt == 'png' else 300,
                    bbox_inches='tight', pad_inches=0.045,
                    facecolor='white')
        print(f"  ✅ {fpath}")
    plt.close(fig)



# ═══════════════════════════════════════════════════════════════════════
#  Main
# ═══════════════════════════════════════════════════════════════════════

def main():
    print("=" * 70)
    print("Generating 24-Disease PDF Figures")
    print("=" * 70)

    df = pd.read_csv(CSV_PATH)
    print(f"Input: {len(df)} records, {len(DISEASES)} diseases")
    print(f"Output: {OUTPUT_DIR}\n")

    print("[1/2] nfdr_trend_composite (5-panel) ...")
    generate_nfdr_trend_composite(df)

    print("\n[2/2] gpt_fdr_performance_overview ...")
    generate_fdr_performance_overview(df)

    print(f"\n{'='*70}")
    print("✅ Done!")
    print(f"{'='*70}")


if __name__ == '__main__':
    main()
