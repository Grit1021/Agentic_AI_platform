import os
from typing import List, Dict, Any


# Category definitions used across visualizations
ALL_CATEGORIES = ['GO:BP', 'GO:MF', 'GO:CC', 'KEGG', 'REAC']
CATEGORY_COLORS = {
    'GO:BP': '#2ecc71',  # Green
    'GO:MF': '#3498db',  # Blue
    'GO:CC': '#9b59b6',  # Purple
    'KEGG': '#e74c3c',   # Red
    'REAC': '#f39c12',   # Orange
}


def generate_category_plots(
    final_module_results: List[Dict[str, Any]],
    summary_dir: str,
) -> int:
    """
    Generate category breakdown plots for each module showing pathway count across iterations.

    Parameters
    ----------
    final_module_results : list
        List of module result dicts from Phase 2
    summary_dir : str
        Directory to save plots

    Returns
    -------
    int
        Number of plots generated
    """
    import matplotlib.pyplot as plt
    import matplotlib
    matplotlib.use('Agg')

    plots_generated = 0

    for res in final_module_results:
        module_id = res.get('module_id', 'Unknown')
        iteration_data = _extract_iteration_data(res)

        if len(iteration_data) < 2:
            print(f"   ℹ️  Module {module_id}: Not enough iterations ({len(iteration_data)})")
            continue

        # Create plot
        fig, ax = plt.subplots(figsize=(10, 6))
        iterations = list(range(1, len(iteration_data) + 1))

        for cat in ALL_CATEGORIES:
            counts = [iter_data.get(cat, 0) for iter_data in iteration_data]
            ax.plot(
                iterations, counts, marker='o', linewidth=2, markersize=8,
                label=cat, color=CATEGORY_COLORS.get(cat, '#7f8c8d'),
            )

        ax.set_xlabel('Iteration', fontsize=12, fontweight='bold')
        ax.set_ylabel('FDR-Significant Pathway Count', fontsize=12, fontweight='bold')
        ax.set_title(
            f'Module {module_id}: Pathway Category Changes Across Iterations',
            fontsize=14, fontweight='bold',
        )
        ax.legend(fontsize=10, loc='best', title='Category')
        ax.grid(True, alpha=0.3, linestyle='--')
        ax.set_xticks(iterations)
        ax.set_ylim(bottom=0)

        plot_file = os.path.join(summary_dir, f'module_{module_id}_category_breakdown.png')
        plt.savefig(plot_file, dpi=300, bbox_inches='tight')
        plt.close()

        print(f"   ✅ Module {module_id} category plot saved")
        plots_generated += 1

    return plots_generated


def generate_rate_variation_plots(
    final_module_results: List[Dict[str, Any]],
    summary_dir: str,
) -> int:
    """
    Generate rate variation plots (matched rate & FDR rate) per module.

    Parameters
    ----------
    final_module_results : list
        List of module result dicts from Phase 2
    summary_dir : str
        Directory to save plots

    Returns
    -------
    int
        Number of plots generated
    """
    import matplotlib.pyplot as plt
    import matplotlib
    matplotlib.use('Agg')

    plots_generated = 0

    for res in final_module_results:
        module_id = res.get('module_id', 'Unknown')
        iteration_results = res.get('iteration_results', [])

        if not iteration_results:
            continue

        # Extract rate data
        matched_rates, fdr_rates = _extract_rates(iteration_results)

        if len(matched_rates) < 2:
            continue

        iterations = list(range(1, len(matched_rates) + 1))

        # Overall rate plot
        fig, axes = plt.subplots(1, 2, figsize=(14, 5))

        # Plot 1: Matched Rate
        ax1 = axes[0]
        ax1.plot(iterations, matched_rates, marker='o', linewidth=2, markersize=10,
                 color='#27ae60', label='Matched Rate')
        ax1.set_xlabel('Iteration', fontsize=12, fontweight='bold')
        ax1.set_ylabel('Matched Rate (%)', fontsize=12, fontweight='bold')
        ax1.set_title('Overall Matched Rate', fontsize=14, fontweight='bold')
        ax1.grid(True, alpha=0.3, linestyle='--')
        ax1.set_xticks(iterations)
        ax1.set_ylim(0, 110)
        ax1.axhline(y=100, color='gray', linestyle='--', alpha=0.5)
        ax1.legend(fontsize=10)

        # Annotations
        for i in range(1, len(matched_rates)):
            delta = matched_rates[i] - matched_rates[i-1]
            color = '#27ae60' if delta > 0 else '#e74c3c'
            ax1.annotate(
                f'{delta:+.1f}%', xy=(iterations[i], matched_rates[i]),
                xytext=(0, 15), textcoords='offset points',
                ha='center', fontsize=9, color=color, fontweight='bold',
            )

        # Plot 2: FDR Rate
        ax2 = axes[1]
        ax2.plot(iterations, fdr_rates, marker='s', linewidth=2, markersize=10,
                 color='#3498db', label='FDR Rate')
        ax2.set_xlabel('Iteration', fontsize=12, fontweight='bold')
        ax2.set_ylabel('FDR Rate (%)', fontsize=12, fontweight='bold')
        ax2.set_title('FDR Filtering Rate', fontsize=14, fontweight='bold')
        ax2.grid(True, alpha=0.3, linestyle='--')
        ax2.set_xticks(iterations)
        ax2.set_ylim(0, 110)
        ax2.axhline(y=100, color='gray', linestyle='--', alpha=0.5)
        ax2.legend(fontsize=10)

        for i in range(1, len(fdr_rates)):
            delta = fdr_rates[i] - fdr_rates[i-1]
            color = '#27ae60' if delta > 0 else '#e74c3c'
            ax2.annotate(
                f'{delta:+.1f}%', xy=(iterations[i], fdr_rates[i]),
                xytext=(0, 15), textcoords='offset points',
                ha='center', fontsize=9, color=color, fontweight='bold',
            )

        plt.suptitle(
            f'Module {module_id}: Rate Variation Across Iterations',
            fontsize=16, fontweight='bold', y=1.02,
        )
        plt.tight_layout()

        rate_plot_file = os.path.join(summary_dir, f'module_{module_id}_rate_variation.png')
        plt.savefig(rate_plot_file, dpi=300, bbox_inches='tight')
        plt.close()

        print(f"   ✅ Module {module_id} rate variation plot saved")
        plots_generated += 1

    return plots_generated


# ============================================================================
# HELPERS
# ============================================================================

def _extract_iteration_data(res: dict) -> list:
    """Extract FDR category counts from iteration results."""
    iteration_results = res.get('iteration_results', [])

    if not iteration_results:
        # Try fallback from validation_details
        validation_details = res.get('validation_details', {})
        if isinstance(validation_details, dict) and 'iteration_history' in validation_details:
            iteration_results = []
            for hist_item in validation_details['iteration_history']:
                if hasattr(hist_item, 'validation_details'):
                    cat_stats = hist_item.validation_details.get('category_stats', None)
                    if cat_stats:
                        iteration_results.append({'category_stats': cat_stats})

    data = []
    for iter_result in iteration_results:
        cat_stats = iter_result.get('category_stats', {})
        fdr_counts = cat_stats.get('fdr', {})
        if fdr_counts:
            data.append(fdr_counts)

    return data


def _extract_rates(iteration_results: list):
    """Extract matched rates and FDR rates from iteration results."""
    matched_rates = []
    fdr_rates = []

    for iter_result in iteration_results:
        cat_stats = iter_result.get('category_stats', {})

        matched_rate = cat_stats.get('matched_rate', None)
        fdr_rate = cat_stats.get('fdr_rate', None)

        if matched_rate is None:
            all_total = cat_stats.get('all_total', 0)
            predicted_total = cat_stats.get('predicted_total', 50)
            matched_rate = (all_total / predicted_total * 100) if predicted_total > 0 else 0

        if fdr_rate is None:
            all_total = cat_stats.get('all_total', 0)
            fdr_total = cat_stats.get('fdr_total', 0)
            fdr_rate = (fdr_total / all_total * 100) if all_total > 0 else 0

        matched_rates.append(matched_rate)
        fdr_rates.append(fdr_rate)

    return matched_rates, fdr_rates
