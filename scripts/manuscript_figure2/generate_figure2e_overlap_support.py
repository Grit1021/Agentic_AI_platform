#!/usr/bin/env python3
"""Generate Figure 2E: cross-disease generality and overlap support.

The panel quantifies how often generated pathways recur across diseases,
decomposes their validation outcomes, and compares gene-list overlap strength
for FDR-supported versus matched but non-significant hypotheses.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

import matplotlib as mpl
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.patches import FancyBboxPatch
import numpy as np
import pandas as pd


SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parents[1]
RUN_ROOT = Path(os.environ.get("BENCHMARK_RUN_ROOT", PROJECT_ROOT))
MEMBANK_DIR = RUN_ROOT / "result" / "memory_bank_external"
OUTPUT_DIR = Path(os.environ.get(
    "BENCHMARK_FIGURE2_OUTPUT_DIR", PROJECT_ROOT / "output" / "figure2_consistent_current"
))
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

COLORS = {
    "FDR+": "#2E7D32",
    # Match the orange accent used for the RA example in panel D.
    "FDR-": "#E08E0B",
    "unmatched": "#A7ADB3",
    "ink": "#151515",
    "grid": "#E3E5E7",
}

def _read_csv(path: Path) -> pd.DataFrame:
    try:
        if not path.exists() or path.stat().st_size < 20:
            return pd.DataFrame()
        return pd.read_csv(path)
    except Exception:
        return pd.DataFrame()


def _normalize_source(value: object) -> str:
    source = str(value or "").upper().strip()
    return {
        "REACTOME": "REAC",
        "GO_BP": "GO:BP",
        "GO_MF": "GO:MF",
        "GO_CC": "GO:CC",
    }.get(source, source)


def _normalize_name(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "").lower()).strip()


def collect_round1_hypotheses() -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return hypothesis-level records and a disease-module audit table."""
    records: list[dict] = []
    pair_records: list[dict] = []
    pattern = re.compile(r"(.+)_Module_(\d+)_iter1_gpt_prediction.json")

    prediction_files = sorted(
        MEMBANK_DIR.glob(
            "iterative_feedback_*/gpt_led_analysis_ag2_hitl/"
            "*_iter1_gpt_prediction.json"
        )
    )
    for prediction_path in prediction_files:
        match = pattern.fullmatch(prediction_path.name)
        if not match:
            continue
        disease, module = match.group(1), int(match.group(2))
        prediction = json.loads(prediction_path.read_text(encoding="utf-8"))
        details = prediction.get("pathway_details") or {}
        names = (
            prediction.get("generated_pathways")
            or prediction.get("predicted_pathways")
            or list(details)
        )

        stem = prediction_path.name.replace("_gpt_prediction.json", "")
        matched_all = _read_csv(
            prediction_path.with_name(f"{stem}_gpt_matched_all.csv")
        )
        matched_fdr = _read_csv(
            prediction_path.with_name(f"{stem}_gpt_matched_fdr_p005.csv")
        )

        def source_name_keys(frame: pd.DataFrame) -> set[tuple[str, str]]:
            if "source" not in frame or "name" not in frame:
                return set()
            return set(zip(
                frame["source"].map(_normalize_source),
                frame["name"].map(_normalize_name),
            ))

        all_keys = source_name_keys(matched_all)
        fdr_keys = source_name_keys(matched_fdr)
        pair_counts = {"FDR+": 0, "FDR-": 0, "unmatched": 0}

        for rank, name in enumerate(names, start=1):
            metadata = details.get(name, {}) if isinstance(details, dict) else {}
            native_id = (
                str(
                    metadata.get("go_id")
                    or metadata.get("pathway_id")
                    or ""
                )
                if isinstance(metadata, dict)
                else ""
            )
            name_lower = _normalize_name(name)
            predicted_source = _normalize_source(
                metadata.get("source", "") if isinstance(metadata, dict) else ""
            )
            match_key = (predicted_source, name_lower)

            # Candidate-level validation uses one transparent rule throughout:
            # exact normalized pathway name within the predicted database.
            # Model-supplied IDs are retained for audit only, not matching.
            if match_key in fdr_keys:
                status = "FDR+"
            elif match_key in all_keys:
                status = "FDR-"
            else:
                status = "unmatched"
            pair_counts[status] += 1

            row = None
            if status != "unmatched" and not matched_all.empty:
                source_mask = (
                    matched_all["source"].map(_normalize_source).eq(
                        predicted_source
                    )
                    if "source" in matched_all
                    else pd.Series(True, index=matched_all.index)
                )
                name_mask = (
                    matched_all["name"].map(_normalize_name).eq(name_lower)
                    if "name" in matched_all
                    else pd.Series(False, index=matched_all.index)
                )
                # Overlap metrics use a transparent same-source, exact-name
                # match. Model-supplied IDs are not used here because their
                # mapping to generated names is not sufficiently stable.
                hits = matched_all[source_mask & name_mask]
                if len(hits):
                    row = hits.sort_values("p_value").iloc[0]

            record = {
                "disease": disease,
                "module": module,
                "rank": rank,
                "hypothesis": name,
                "native_id": native_id,
                "predicted_source": predicted_source,
                "status": status,
                "source_consistent_overlap_match": row is not None,
            }
            if row is not None:
                for column in (
                    "source", "p_value", "term_size", "query_size",
                    "intersection_size", "precision", "recall"
                ):
                    record[column] = row.get(column, np.nan)
            records.append(record)

        pair_records.append({
            "disease": disease,
            "module": module,
            "n_hypotheses": len(names),
            **pair_counts,
        })

    return pd.DataFrame(records), pd.DataFrame(pair_records)


def add_cross_disease_sharing(records: pd.DataFrame) -> pd.DataFrame:
    """Add an operational disease-generality measure to each hypothesis.

    A pathway is keyed by predicted ontology source plus normalized name.
    Generated IDs are intentionally not used because the model-supplied IDs
    are not sufficiently stable to define biological recurrence.
    """
    records = records.copy()
    records["normalized_name"] = (
        records["hypothesis"].fillna("").astype(str).str.lower()
        .str.replace(r"\s+", " ", regex=True).str.strip()
    )
    records["normalized_source"] = (
        records["predicted_source"].fillna("").astype(str).str.upper().str.strip()
    )
    records["source_name_key"] = (
        records["normalized_source"] + ":" + records["normalized_name"]
    )

    records["pathway_key"] = records["source_name_key"]
    disease_counts = records.groupby("pathway_key")["disease"].nunique()
    records["diseases_sharing_pathway"] = records["pathway_key"].map(
        disease_counts
    ).astype(int)
    return records


def summarize(
    records: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    total = len(records)
    outcome_rows = []
    for status in ("FDR+", "FDR-", "unmatched"):
        n = int(records["status"].eq(status).sum())
        outcome_rows.append({
            "status": status,
            "n": n,
            "percent": n / total * 100,
        })

    sharing_bins = pd.cut(
        records["diseases_sharing_pathway"],
        bins=[0, 1, 5, 11, 24],
        labels=["1", "2-5", "6-11", "12-24"],
    )
    sharing_rows = []
    for label in ["1", "2-5", "6-11", "12-24"]:
        n = int(sharing_bins.astype(str).eq(label).sum())
        sharing_rows.append({
            "diseases": label,
            "n": n,
            "percent": n / total * 100,
        })

    matched = records[records["status"].isin(["FDR+", "FDR-"])].copy()
    metrics = {
        "Cross-disease prevalence": ("diseases_sharing_pathway", 1.0),
        "Overlapping genes": ("intersection_size", 1.0),
        "Gene-list coverage (%)": ("precision", 100.0),
    }
    overlap_rows = []
    for metric_label, (column, scale) in metrics.items():
        for status in ("FDR-", "FDR+"):
            values = pd.to_numeric(
                matched.loc[matched["status"].eq(status), column],
                errors="coerce",
            ).dropna().to_numpy(dtype=float) * scale
            q1, median, q3 = np.percentile(values, [25, 50, 75])
            overlap_rows.append({
                "metric": metric_label,
                "status": status,
                "n": len(values),
                "q1": q1,
                "median": median,
                "q3": q3,
            })
    return (
        pd.DataFrame(outcome_rows),
        pd.DataFrame(sharing_rows),
        pd.DataFrame(overlap_rows),
    )


def summarize_sharing_validation(
    records: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Return supporting tables that prevent causal overinterpretation."""
    records = records.copy()
    records["sharing_bin"] = pd.cut(
        records["diseases_sharing_pathway"],
        bins=[0, 1, 5, 11, 24],
        labels=["1", "2-5", "6-11", "12-24"],
    )

    matched = records[records["status"].isin(["FDR+", "FDR-"])].copy()
    bin_rows = []
    for label in ["1", "2-5", "6-11", "12-24"]:
        group = matched[matched["sharing_bin"].astype(str).eq(label)]
        supported = int(group["status"].eq("FDR+").sum())
        bin_rows.append({
            "diseases": label,
            "matched_hypotheses": len(group),
            "fdr_supported": supported,
            "fdr_supported_percent_of_matched": supported / len(group) * 100,
        })

    status_rows = []
    for status in ["FDR+", "FDR-"]:
        values = records.loc[
            records["status"].eq(status), "diseases_sharing_pathway"
        ].to_numpy(dtype=float)
        q1, median, q3 = np.percentile(values, [25, 50, 75])
        status_rows.append({
            "status": status,
            "n": len(values),
            "q1_diseases": q1,
            "median_diseases": median,
            "q3_diseases": q3,
        })

    broad = records.assign(broad=records["diseases_sharing_pathway"].ge(12))
    distribution_rows = []
    for level, group_columns in [
        ("disease-module context", ["disease", "module"]),
        ("disease", ["disease"]),
    ]:
        fractions = broad.groupby(group_columns)["broad"].mean() * 100
        q1, median, q3 = np.percentile(fractions, [25, 50, 75])
        distribution_rows.append({
            "aggregation_level": level,
            "n": len(fractions),
            "q1_percent_shared_in_12plus_diseases": q1,
            "median_percent_shared_in_12plus_diseases": median,
            "q3_percent_shared_in_12plus_diseases": q3,
            "minimum_percent": fractions.min(),
            "maximum_percent": fractions.max(),
        })

    return (
        pd.DataFrame(bin_rows),
        pd.DataFrame(status_rows),
        pd.DataFrame(distribution_rows),
    )


def _fmt_value(metric: str, value: float) -> str:
    if metric in {"Cross-disease prevalence", "Overlapping genes"}:
        return f"{value:,.0f}"
    if metric == "Gene-list coverage (%)":
        return f"{value:.1f}%"
    return f"{value:.2f}%"


def draw_balanced_figure(
    outcomes: pd.DataFrame,
    overlap: pd.DataFrame,
) -> plt.Figure:
    mpl.rcParams.update({
        "font.family": "sans-serif",
        "font.sans-serif": ["Arial", "Helvetica", "DejaVu Sans"],
        "font.size": 6.2,
        "pdf.fonttype": 42,
        "ps.fonttype": 42,
        "svg.fonttype": "none",
        "axes.linewidth": 0.65,
    })

    # Same width as the supplied Figure 2 PDF (816 pt = 11.33 in), with a
    # compact height that better balances the two-row A-D block above it.
    fig = plt.figure(figsize=(11.33, 2.65), facecolor="white")
    grid = fig.add_gridspec(
        1, 2, width_ratios=[0.82, 1.48],
        left=0.065, right=0.900, top=0.555, bottom=0.110, wspace=0.17,
    )
    ax_left = fig.add_subplot(grid[0, 0])
    right_grid = grid[0, 1].subgridspec(3, 1, hspace=0.76)
    right_axes = [fig.add_subplot(right_grid[i, 0]) for i in range(3)]

    fig.text(0.018, 0.935, "E", fontsize=11.2, fontweight="bold",
             ha="left", va="top", color=COLORS["ink"])
    fig.text(
        0.065, 0.935,
        "Generated pathways recur across diseases; non-significant matches show weak gene-list overlap",
        fontsize=8.6, fontweight="bold", ha="left", va="top",
        color=COLORS["ink"],
    )
    fig.text(
        0.225, 0.742, "Validation outcomes",
        fontsize=6.8, fontweight="bold", ha="center", va="top",
        color=COLORS["ink"],
    )
    fig.text(
        0.661, 0.742, "Cross-disease generality and source-consistent overlap",
        fontsize=6.8, fontweight="bold", ha="center", va="top",
        color=COLORS["ink"],
    )

    # One shared, fully spelled-out status key replaces repeated y-axis labels.
    # This prevents the labels from colliding with metric titles at final size.
    status_handles = [
        Line2D(
            [0], [0], color=COLORS[status], linewidth=3.6,
            marker="o", markersize=4.2, markerfacecolor=COLORS[status],
            markeredgecolor="white", markeredgewidth=0.55,
        )
        for status in ("FDR+", "FDR-")
    ]
    fig.legend(
        status_handles,
        ["FDR-supported", "Matched, not significant"],
        loc="upper center", bbox_to_anchor=(0.661, 0.682),
        ncol=2, frameon=False, fontsize=5.7,
        handlelength=2.05, handletextpad=0.60, columnspacing=1.6,
        borderaxespad=0,
    )

    # Left: validation outcome decomposition.
    ax_left.set_xlim(0, 100)
    ax_left.set_ylim(0, 1)
    ax_left.axis("off")
    left = 0.0
    y_bar, height = 0.57, 0.23
    labels = {
        "FDR+": "FDR-supported",
        "FDR-": "Matched, not\nsignificant",
        "unmatched": "No exact database\nmatch",
    }
    for _, row in outcomes.iterrows():
        status = row["status"]
        width = float(row["percent"])
        ax_left.barh(
            y_bar, width, left=left, height=height,
            color=COLORS[status], edgecolor="white", linewidth=1.0,
        )
        ax_left.text(
            left + width / 2, y_bar,
            f"{width:.1f}%\n{int(row['n']):,}",
            ha="center", va="center", fontsize=5.9,
            color="white" if status != "unmatched" else "#222222",
            fontweight="bold", linespacing=1.05,
        )
        left += width

    x_positions = [0.0, 32.0, 68.0]
    for x, (_, row) in zip(x_positions, outcomes.iterrows()):
        status = row["status"]
        ax_left.add_patch(FancyBboxPatch(
            (x, 0.225), 2.4, 0.115,
            boxstyle="round,pad=0.01,rounding_size=0.015",
            facecolor=COLORS[status], edgecolor="none",
        ))
        ax_left.text(
            x + 3.3, 0.282, labels[status],
            fontsize=5.0, ha="left", va="center",
            color=COLORS["ink"], linespacing=1.0,
        )

    # Right: metric-specific median/IQR glyphs.
    metric_order = [
        ("Cross-disease prevalence", (0, 24), [0, 6, 12, 18, 24]),
        ("Overlapping genes", (0, 40), [0, 10, 20, 30, 40]),
        ("Gene-list coverage (%)", (0, 45), [0, 10, 20, 30, 40]),
    ]
    for ax, (metric, xlim, ticks) in zip(right_axes, metric_order):
        sub = overlap[overlap["metric"].eq(metric)].set_index("status")
        ax.set_facecolor("white")
        ax.set_xlim(*xlim)
        ax.set_ylim(-0.18, 1.18)
        ax.set_yticks([])
        ax.set_xticks(ticks)
        ax.tick_params(axis="x", labelsize=5.3, length=2.0, pad=1.3)
        ax.grid(axis="x", color=COLORS["grid"], linewidth=0.55, zorder=0)
        ax.spines[["top", "right", "left"]].set_visible(False)
        ax.spines["bottom"].set_color("#AEB3B7")
        ax.spines["bottom"].set_linewidth(0.55)
        title = (
            "Diseases sharing the pathway (of 24)"
            if metric == "Cross-disease prevalence" else metric
        )
        ax.set_title(title, fontsize=5.8, fontweight="bold",
                     loc="left", pad=2.4)

        for y, status in [(0.18, "FDR-"), (0.82, "FDR+")]:
            row = sub.loc[status]
            ax.plot(
                [row["q1"], row["q3"]], [y, y],
                color=COLORS[status], linewidth=3.6,
                solid_capstyle="round", alpha=0.55, zorder=2,
            )
            ax.scatter(
                row["median"], y, s=27, color=COLORS[status],
                edgecolor="white", linewidth=0.7, zorder=3,
            )
            label = (
                f"{_fmt_value(metric, row['median'])} "
                f"[{_fmt_value(metric, row['q1'])}-"
                f"{_fmt_value(metric, row['q3'])}]"
            )
            ax.text(
                xlim[1] * 1.015, y, label,
                ha="left", va="center", fontsize=5.3,
                color=COLORS[status], fontweight="bold", clip_on=False,
            )

    return fig


def main() -> None:
    records, _pairs = collect_round1_hypotheses()
    records = add_cross_disease_sharing(records)
    outcomes, sharing, overlap = summarize(records)
    sharing_validation, sharing_by_status, broad_distributions = (
        summarize_sharing_validation(records)
    )

    records.to_csv(OUTPUT_DIR / "Figure2E_hypothesis_level_source_data.csv",
                   index=False)
    outcomes.to_csv(OUTPUT_DIR / "Figure2E_outcome_summary.csv", index=False)
    sharing.to_csv(OUTPUT_DIR / "Figure2E_cross_disease_sharing_summary.csv",
                   index=False)
    overlap.to_csv(OUTPUT_DIR / "Figure2E_overlap_summary.csv", index=False)
    sharing_validation.to_csv(
        OUTPUT_DIR / "Figure2E_sharing_by_validation_summary.csv", index=False
    )
    sharing_by_status.to_csv(
        OUTPUT_DIR / "Figure2E_sharing_prevalence_by_status.csv", index=False
    )
    broad_distributions.to_csv(
        OUTPUT_DIR / "Figure2E_broad_sharing_distributions.csv", index=False
    )

    fig = draw_balanced_figure(
        outcomes,
        overlap,
    )
    base = OUTPUT_DIR / "Figure2E_weak_overlap_numerical_support_balanced_fonts"
    # Preserve the fixed 11.33-inch canvas so the panel matches the supplied
    # Figure 2 width (approximately 816 pt) when appended beneath panels A-D.
    fig.savefig(base.with_suffix(".pdf"), facecolor="white")
    fig.savefig(base.with_suffix(".svg"), facecolor="white")
    fig.savefig(base.with_suffix(".png"), dpi=600, facecolor="white")
    fig.savefig(base.with_suffix(".tiff"), dpi=600, facecolor="white")
    plt.close(fig)

    print(outcomes.to_string(index=False))
    print(sharing.to_string(index=False))
    print(overlap.to_string(index=False))
    print(sharing_validation.to_string(index=False))
    print(sharing_by_status.to_string(index=False))
    print(broad_distributions.to_string(index=False))
    print(f"Saved Figure 2E bundle to {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
