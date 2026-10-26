#!/usr/bin/env python3
"""Build an audited, internally consistent Figure 2 snapshot.

The legacy Figure 2A-D summary CSV predates later AST and PS reruns, whereas
Figure 2E reads the current candidate-level JSON/CSV artifacts directly.  This
orchestrator rebuilds every panel from the same current source snapshot and
fails if the round-1 run-log counts disagree with the candidate JSON records.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import re
from copy import deepcopy
from pathlib import Path

os.environ.setdefault(
    "MPLCONFIGDIR", str(Path(__file__).resolve().parents[2] / "output" / ".mplconfig")
)

import matplotlib as mpl
import matplotlib.pyplot as plt
from matplotlib.colors import to_rgba
from matplotlib.lines import Line2D
from matplotlib.patches import FancyBboxPatch
import numpy as np
import pandas as pd
from PIL import Image
from PyPDF2 import PdfReader, PdfWriter, Transformation
from PyPDF2._page import PageObject


SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parents[1]
RUN_ROOT = Path(os.environ.get("BENCHMARK_RUN_ROOT", PROJECT_ROOT))
EXPANSION_DIR = PROJECT_ROOT / "data" / "source_modules"
OUTPUT_DIR = Path(os.environ.get(
    "BENCHMARK_FIGURE2_OUTPUT_DIR",
    PROJECT_ROOT / "output" / "figure2_consistent_current",
))
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot import {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


METRICS_MODULE = _load_module(
    "figure2_current_metrics",
    SCRIPT_DIR / "generate_nfdr_metrics_csv_24.py",
)
ABCD_MODULE = _load_module(
    "figure2_abcd",
    SCRIPT_DIR / "generate_pdf_figures_24.py",
)
E_MODULE = _load_module(
    "figure2e",
    SCRIPT_DIR / "generate_figure2e_overlap_support.py",
)
METRICS_MODULE.BASE_DIR = str(RUN_ROOT / "result" / "memory_bank_external")
E_MODULE.MEMBANK_DIR = RUN_ROOT / "result" / "memory_bank_external"
ABCD_MODULE.MEMBANK_DIR = str(E_MODULE.MEMBANK_DIR)


def _normalized_source(value: object) -> str:
    source = str(value or "").upper().strip()
    return {"REACTOME": "REAC"}.get(source, source)


def _current_round1_validation_counts() -> tuple[pd.DataFrame, pd.DataFrame]:
    """Read current round-1 JSON/matched files and hash every E input."""
    pattern = re.compile(r"(.+)_Module_(\d+)_iter1_gpt_prediction.json")
    count_rows: list[dict] = []
    inventory_rows: list[dict] = []
    prediction_files = sorted(
        E_MODULE.MEMBANK_DIR.glob(
            "iterative_feedback_*/gpt_led_analysis_ag2_hitl/"
            "*_iter1_gpt_prediction.json"
        )
    )
    for prediction_path in prediction_files:
        match = pattern.fullmatch(prediction_path.name)
        if not match:
            continue
        disease, module = match.group(1), int(match.group(2))
        stem = prediction_path.name.replace("_gpt_prediction.json", "")
        all_path = prediction_path.with_name(f"{stem}_gpt_matched_all.csv")
        fdr_path = prediction_path.with_name(
            f"{stem}_gpt_matched_fdr_p005.csv"
        )
        for kind, path in (
            ("prediction_json", prediction_path),
            ("matched_all_csv", all_path),
            ("matched_fdr_csv", fdr_path),
        ):
            if not path.exists():
                raise FileNotFoundError(path)
            inventory_rows.append({
                "disease": disease,
                "module": module,
                "kind": kind,
                "path": str(path),
                "bytes": path.stat().st_size,
                "sha256": _sha256(path),
            })

        matched_all = E_MODULE._read_csv(all_path)
        matched_fdr = E_MODULE._read_csv(fdr_path)
        for frame in (matched_all, matched_fdr):
            if len(frame) and "source" not in frame:
                raise KeyError(f"source missing from validation file for {disease} {module}")
        all_counts = (
            matched_all["source"].map(_normalized_source).value_counts()
            if len(matched_all)
            else pd.Series(dtype=int)
        )
        fdr_counts = (
            matched_fdr["source"].map(_normalized_source).value_counts()
            if len(matched_fdr)
            else pd.Series(dtype=int)
        )
        for category in ABCD_MODULE.CATEGORIES:
            count_rows.append({
                "disease": disease,
                "module": module,
                "category": category,
                "matched_rows": int(all_counts.get(category, 0)),
                "fdr_rows": int(fdr_counts.get(category, 0)),
            })

    counts = pd.DataFrame(count_rows)
    inventory = pd.DataFrame(inventory_rows)
    if counts[["disease", "module"]].drop_duplicates().shape[0] != 567:
        raise ValueError("Expected validation files for 567 round-1 pairs")
    if len(inventory) != 567 * 3:
        raise ValueError(f"Expected 1,701 E input files; found {len(inventory)}")
    return counts, inventory


def _audit_current_round1_validation(
    metrics: pd.DataFrame,
    validation_counts: pd.DataFrame,
) -> pd.DataFrame:
    """Audit current matched CSV counts without changing manuscript log rates.

    The matched-term files were updated after the logged benchmark snapshot for
    some pairs. Overwriting the log rates mixes two snapshots and changes the
    paper's Figure 2 statistics. Keep the discrepancy in the audit table.
    """
    round1 = metrics[metrics["iteration"].eq(1)].copy()
    audit = round1.merge(
        validation_counts,
        on=["disease", "module", "category"],
        how="left",
        validate="one_to_one",
    )
    if audit[["matched_rows", "fdr_rows"]].isna().any().any():
        raise ValueError("Missing current round-1 validation counts")
    audit = audit.rename(columns={
        "matched": "log_matched",
        "new_matched": "log_new_matched",
        "fdr_pct": "log_fdr_pct",
        "nfdr_pct": "log_nfdr_pct",
    })
    current_rate = np.where(
        audit["matched_rows"].gt(0),
        audit["fdr_rows"] / audit["matched_rows"] * 100.0,
        0.0,
    )
    audit["current_fdr_pct"] = current_rate
    audit["matched_row_difference"] = (
        audit["matched_rows"] - audit["log_new_matched"]
    )
    return audit


def build_current_metrics() -> tuple[
    pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame
]:
    """Reparse the latest 24 run logs and attach exact module sizes."""
    metric_rows: list[dict] = []
    size_rows: list[dict] = []
    source_rows: list[dict] = []

    for disease in METRICS_MODULE.DISEASES:
        log_value = METRICS_MODULE.find_latest_run_log(disease)
        if not log_value:
            raise FileNotFoundError(f"No run log for {disease}")
        log_path = Path(log_value)
        log_text = log_path.read_text(encoding="utf-8", errors="ignore")
        mesh_ids = sorted(set(re.findall(r"MeSH ID:\s*([A-Z]\d+)", log_text)))
        if len(mesh_ids) != 1:
            raise ValueError(
                f"Expected one MeSH ID in {log_path}; found {mesh_ids}"
            )
        mesh_id = mesh_ids[0]

        records = METRICS_MODULE.extract_category_data_from_log(
            str(log_path), disease
        )
        metric_rows.extend(row for row in records if row["iteration"] <= 2)

        expansion_path = EXPANSION_DIR / f"{mesh_id}_modules.csv"
        if not expansion_path.exists():
            raise FileNotFoundError(expansion_path)
        expansion = pd.read_csv(expansion_path)
        if "cluster_walktrap" not in expansion.columns:
            raise KeyError(f"cluster_walktrap missing from {expansion_path}")
        counts = expansion.groupby("cluster_walktrap").size()
        for module, count in counts.items():
            size_rows.append({
                "disease": disease,
                "module": int(module),
                "module_size": int(count),
            })

        source_rows.append({
            "disease": disease,
            "mesh_id": mesh_id,
            "run_log": str(log_path),
            "run_log_sha256": _sha256(log_path),
            "module_file": str(expansion_path),
            "module_file_sha256": _sha256(expansion_path),
        })

    metrics = pd.DataFrame(metric_rows).sort_values(
        ["disease", "module", "iteration", "category"]
    ).reset_index(drop=True)
    key = ["disease", "module", "iteration", "category"]
    if metrics.duplicated(key).any():
        duplicate_rows = metrics[metrics.duplicated(key, keep=False)]
        raise ValueError(f"Duplicate metric keys:\n{duplicate_rows}")

    sizes = pd.DataFrame(size_rows).drop_duplicates(["disease", "module"])
    round1_pairs = metrics.loc[
        metrics["iteration"].eq(1), ["disease", "module"]
    ].drop_duplicates()
    round2_pairs = metrics.loc[
        metrics["iteration"].eq(2), ["disease", "module"]
    ].drop_duplicates()
    if len(round1_pairs) != 567 or len(round2_pairs) != 567:
        raise ValueError(
            f"Expected 567 pairs in both rounds; found "
            f"round 1={len(round1_pairs)}, round 2={len(round2_pairs)}"
        )
    if set(map(tuple, round1_pairs.to_numpy())) != set(map(tuple, round2_pairs.to_numpy())):
        raise ValueError("Round 1 and round 2 disease/module keys differ")
    category_counts = metrics.groupby(["disease", "module", "iteration"]).size()
    if not category_counts.eq(5).all():
        raise ValueError("Expected five annotation categories per pair and round")
    pair_audit = round1_pairs.merge(
        sizes, on=["disease", "module"], how="left", validate="one_to_one"
    )
    if pair_audit["module_size"].isna().any():
        missing = pair_audit[pair_audit["module_size"].isna()]
        raise ValueError(f"Missing module sizes:\n{missing}")
    if len(pair_audit) != 567:
        raise ValueError(f"Expected 567 round-1 pairs; found {len(pair_audit)}")

    validation_counts, e_inventory = _current_round1_validation_counts()
    validation_audit = _audit_current_round1_validation(
        metrics, validation_counts
    )
    enriched = metrics.merge(
        sizes, on=["disease", "module"], how="left", validate="many_to_one"
    )
    return (
        metrics,
        enriched,
        pd.DataFrame(source_rows),
        validation_audit,
        e_inventory,
    )


def audit_round1_candidates(
    metrics: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Require exact category-level agreement between logs and Figure 2E."""
    records, pairs = E_MODULE.collect_round1_hypotheses()
    source_map = {
        "GO:BP": "GO:BP",
        "GO:MF": "GO:MF",
        "GO:CC": "GO:CC",
        "KEGG": "KEGG",
        "REAC": "REAC",
        "REACTOME": "REAC",
    }
    candidate_counts = records.copy()
    candidate_counts["category"] = (
        candidate_counts["predicted_source"]
        .fillna("")
        .astype(str)
        .str.upper()
        .str.strip()
        .map(source_map)
    )
    if candidate_counts["category"].isna().any():
        unknown = sorted(
            candidate_counts.loc[
                candidate_counts["category"].isna(), "predicted_source"
            ].astype(str).unique()
        )
        raise ValueError(f"Unknown predicted sources: {unknown}")
    candidate_counts = (
        candidate_counts.groupby(
            ["disease", "module", "category"], as_index=False
        )
        .size()
        .rename(columns={"size": "json_newgen"})
    )

    log_counts = metrics.loc[
        metrics["iteration"].eq(1),
        ["disease", "module", "category", "newgen"],
    ]
    audit = log_counts.merge(
        candidate_counts,
        on=["disease", "module", "category"],
        how="outer",
        validate="one_to_one",
        indicator=True,
    )
    audit["difference"] = audit["json_newgen"] - audit["newgen"]
    mismatch = audit[
        audit["_merge"].ne("both") | audit["difference"].ne(0)
    ]
    if len(mismatch):
        raise ValueError(f"Round-1 JSON/log mismatch:\n{mismatch}")

    log_total = int(log_counts["newgen"].sum())
    if log_total != len(records) or log_total != int(pairs["n_hypotheses"].sum()):
        raise ValueError(
            "Round-1 totals disagree: "
            f"logs={log_total}, records={len(records)}, "
            f"pair audit={int(pairs['n_hypotheses'].sum())}"
        )
    return records, pairs, audit.drop(columns="_merge")


def _prepare_ab_data(metrics: pd.DataFrame):
    iter1 = metrics[metrics["iteration"].eq(1)].copy()
    cat_data: dict[str, np.ndarray] = {}
    cat_disease_avgs: dict[str, list[float]] = {}
    for category in ABCD_MODULE.CATEGORIES:
        category_df = iter1[iter1["category"].eq(category)]
        valid = category_df[category_df["new_matched"].gt(0)]
        cat_data[category] = pd.to_numeric(
            valid["nfdr_pct"], errors="coerce"
        ).dropna().to_numpy()
        disease_means = []
        for disease in ABCD_MODULE.DISEASES:
            disease_df = valid[valid["disease"].eq(disease)]
            if len(disease_df):
                disease_means.append(
                    float(pd.to_numeric(
                        disease_df["nfdr_pct"], errors="coerce"
                    ).mean())
                )
        cat_disease_avgs[category] = disease_means
    return iter1, cat_data, cat_disease_avgs


def _reference_panel_a(
    ax: plt.Axes,
    cat_data: dict[str, np.ndarray],
    metrics: pd.DataFrame,
) -> None:
    """Panel A using the compact visual grammar of Figure2_2026_0712."""
    xgrid = np.linspace(0, 100, 500)
    ymax = 0.0
    for category in ABCD_MODULE.CATEGORIES:
        values = np.asarray(cat_data.get(category, []), dtype=float)
        values = values[np.isfinite(values)]
        values = values[(values > 0) & (values <= 100)]
        if len(np.unique(values)) < 3:
            continue
        kde = ABCD_MODULE.gaussian_kde(values, bw_method=0.28)
        density = kde(xgrid)
        ymax = max(ymax, float(np.nanmax(density)))
        color = ABCD_MODULE.CAT_COLORS[category]
        ax.fill_between(
            xgrid, density, color=color, alpha=0.12,
            linewidth=0, zorder=1,
        )
        ax.plot(xgrid, density, color=color, linewidth=1.25, zorder=3)

    y_limit = ymax * 1.18 if ymax > 0 else 0.024
    ax.set_xlim(0, 100)
    ax.set_ylim(0, y_limit)
    ax.set_xticks([0, 20, 40, 60, 80, 100])
    y_top = np.floor(y_limit / 0.006) * 0.006
    ax.set_yticks(np.arange(0, y_top + 0.003, 0.006))
    ax.set_yticklabels([f"{value:.3f}" for value in ax.get_yticks()])
    ax.set_xlabel("Pass rate (%)", fontsize=7.0, labelpad=2)
    ax.set_ylabel("Density | pass rate > 0", fontsize=6.8, labelpad=3)
    ax.grid(axis="both", color="#E5E5E5", linewidth=0.45, zorder=0)
    ax.set_axisbelow(True)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_linewidth(0.55)
    ax.spines["bottom"].set_linewidth(0.55)
    ax.tick_params(axis="both", labelsize=5.8, length=2.2, pad=1.5)

    rows = ABCD_MODULE._iter_category_record_summary(
        metrics, iteration=1
    )[1:]
    inset = ax.inset_axes([0.680, 0.565, 0.300, 0.335])
    inset.set_facecolor("white")
    positions = np.arange(len(rows))
    inset.bar(
        positions,
        [row["zero"] for row in rows],
        width=0.58,
        color=[ABCD_MODULE.CAT_COLORS[row["cat"]] for row in rows],
        alpha=0.92,
        edgecolor="white",
        linewidth=0.45,
        zorder=3,
    )
    for xpos, row in zip(positions, rows):
        inset.text(
            xpos, row["zero"] + 1.2, f"{row['zero']:.0f}",
            ha="center", va="bottom", fontsize=4.0,
            color="#333333", zorder=4,
        )
    inset.set_title(
        "Zero pass rate counts", fontsize=5.8, fontweight="normal", pad=2.0
    )
    inset.set_ylim(0, 55)
    inset.set_yticks([0, 25, 50])
    inset.set_xticks(positions)
    inset.set_xticklabels(
        [ABCD_MODULE.CAT_SHORT[row["cat"]] for row in rows],
        rotation=32, ha="right", fontsize=3.8,
    )
    inset.grid(axis="y", color="#E7E7E7", linewidth=0.38, zorder=0)
    inset.spines["top"].set_visible(False)
    inset.spines["right"].set_visible(False)
    inset.spines["left"].set_linewidth(0.42)
    inset.spines["bottom"].set_linewidth(0.42)
    inset.tick_params(axis="y", labelsize=3.8, length=1.6, pad=1)
    inset.tick_params(axis="x", length=0, pad=0.8)


def _reference_panel_b(
    ax: plt.Axes,
    cat_disease_avgs: dict[str, list[float]],
) -> None:
    """Panel B without the later explanatory legend or right-side means."""
    rng = np.random.default_rng(52)
    y_positions = np.arange(len(ABCD_MODULE.CATEGORIES))[::-1]
    for ypos, category in zip(y_positions, ABCD_MODULE.CATEGORIES):
        values = np.asarray(cat_disease_avgs[category], dtype=float)
        values = values[np.isfinite(values)]
        if not len(values):
            continue
        color = ABCD_MODULE.CAT_COLORS[category]
        ax.boxplot(
            values,
            vert=False,
            positions=[ypos],
            widths=0.48,
            patch_artist=True,
            showfliers=False,
            whis=(5, 95),
            boxprops=dict(
                facecolor=ABCD_MODULE._blend_with_white(color, 0.72),
                edgecolor=color,
                linewidth=0.80,
            ),
            medianprops=dict(color="#333333", linewidth=0.90),
            whiskerprops=dict(color=color, linewidth=0.70),
            capprops=dict(color=color, linewidth=0.70),
            zorder=3,
        )
        jitter = rng.normal(0, 0.052, len(values))
        ax.scatter(
            values,
            ypos + jitter,
            s=8.5,
            color=color,
            alpha=0.38,
            edgecolors="white",
            linewidths=0.18,
            zorder=4,
        )
        ax.scatter(
            [float(np.mean(values))], [ypos],
            marker="D", s=17, color="white", edgecolor="#2F6F9F",
            linewidth=0.8, zorder=5,
        )

    ax.set_yticks(y_positions)
    ax.set_yticklabels(
        ABCD_MODULE.CATEGORIES, fontsize=6.8, fontweight="bold"
    )
    ax.set_xlim(0, 56)
    ax.set_xticks([0, 20, 40])
    ax.set_xlabel("Pass rate (%)", fontsize=7.0, labelpad=2)
    ax.grid(axis="x", color="#E5E5E5", linewidth=0.45, zorder=0)
    ax.set_axisbelow(True)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_linewidth(0.55)
    ax.spines["bottom"].set_linewidth(0.55)
    ax.tick_params(axis="x", labelsize=5.8, length=2.2, pad=1.5)
    ax.tick_params(axis="y", length=0, pad=5)


def _reference_size_summary(
    ms_iter1: pd.DataFrame,
    size_edges: np.ndarray,
) -> tuple[list[dict], float, float]:
    clean = ms_iter1[
        ["disease", "module", "category", "module_size", "nfdr_pct"]
    ].dropna().copy()
    clean["module_size"] = pd.to_numeric(clean["module_size"], errors="coerce")
    clean["nfdr_pct"] = pd.to_numeric(clean["nfdr_pct"], errors="coerce")
    clean = clean.dropna(subset=["module_size", "nfdr_pct"])
    edges = np.asarray(size_edges, dtype=float)
    rows: list[dict] = []
    for category in ABCD_MODULE.CATEGORIES:
        subset = clean[clean["category"].eq(category)]
        means: list[float] = []
        counts: list[int] = []
        for index, (low, high) in enumerate(zip(edges[:-1], edges[1:])):
            if index < len(edges) - 2:
                mask = (
                    subset["module_size"].ge(low)
                    & subset["module_size"].lt(high)
                )
            else:
                mask = (
                    subset["module_size"].ge(low)
                    & subset["module_size"].le(high)
                )
            values = subset.loc[mask, "nfdr_pct"].to_numpy(dtype=float)
            means.append(float(np.nanmean(values)) if len(values) else np.nan)
            counts.append(int(np.isfinite(values).sum()))
        rows.append({"category": category, "means": means, "counts": counts})

    finite_means = np.asarray(
        [value for row in rows for value in row["means"] if np.isfinite(value)]
    )
    vmin = max(0.0, float(np.nanpercentile(finite_means, 5)) - 3.0)
    vmax = min(60.0, float(np.nanpercentile(finite_means, 95)) + 3.0)
    if vmax <= vmin:
        vmax = vmin + 1.0
    return rows, vmin, vmax


def _reference_panel_c(
    ax: plt.Axes,
    ms_iter1: pd.DataFrame,
    size_edges: np.ndarray,
) -> None:
    """Panel C matching the original Q1-Q4 heatmap-only presentation."""
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")
    rows, vmin, vmax = _reference_size_summary(ms_iter1, size_edges)
    low_color = np.asarray(to_rgba("#F4F8FB"))
    high_color = np.asarray(to_rgba("#2F6F9F"))

    def cell_color(value: float) -> tuple[tuple[float, ...], float]:
        fraction = float(np.clip((value - vmin) / (vmax - vmin), 0, 1))
        return tuple(low_color * (1 - fraction) + high_color * fraction), fraction

    ax.text(
        0.54, 0.875, "Quantiles of gene-list sizes (Q1-Q4)",
        ha="center", va="center", fontsize=6.8, color="#222222",
        transform=ax.transAxes,
    )
    cell_x = [0.265, 0.425, 0.585, 0.745]
    cell_w = 0.140
    cell_h = 0.076
    for index, xpos in enumerate(cell_x):
        ax.text(
            xpos + cell_w / 2, 0.755, f"Q{index + 1}",
            ha="center", va="center", fontsize=7.0,
            transform=ax.transAxes,
        )

    row_y = [0.630, 0.525, 0.420, 0.315, 0.210]
    for ypos, row in zip(row_y, rows):
        category = row["category"]
        ax.add_patch(plt.Rectangle(
            (0.115, ypos - cell_h / 2), 0.012, cell_h,
            transform=ax.transAxes,
            facecolor=ABCD_MODULE.CAT_COLORS[category], edgecolor="none",
        ))
        ax.text(
            0.137, ypos, category,
            ha="left", va="center", fontsize=6.8, fontweight="bold",
            color="#222222", transform=ax.transAxes,
        )
        for xpos, value, count in zip(cell_x, row["means"], row["counts"]):
            face, fraction = cell_color(value)
            main_color = "white" if fraction > 0.62 else "#222222"
            sub_color = "#EDF3F7" if fraction > 0.62 else "#5E6670"
            ax.add_patch(FancyBboxPatch(
                (xpos, ypos - cell_h / 2), cell_w, cell_h,
                boxstyle="round,pad=0.002,rounding_size=0.008",
                transform=ax.transAxes, facecolor=face,
                edgecolor="white", linewidth=0.45,
            ))
            ax.text(
                xpos + cell_w * 0.47, ypos,
                f"{value:.0f}%", ha="right", va="center",
                fontsize=6.3, fontweight="bold", color=main_color,
                transform=ax.transAxes,
            )
            ax.text(
                xpos + cell_w * 0.50, ypos,
                f"n={count}", ha="left", va="center",
                fontsize=4.25, color=sub_color, transform=ax.transAxes,
            )

    grad_x, grad_y, grad_w, grad_h = 0.265, 0.058, 0.280, 0.024
    for index in range(80):
        value = vmin + (vmax - vmin) * index / 79
        face, _ = cell_color(value)
        ax.add_patch(plt.Rectangle(
            (grad_x + grad_w * index / 80, grad_y), grad_w / 80, grad_h,
            transform=ax.transAxes, facecolor=face, edgecolor="none",
        ))
    ax.text(
        grad_x + grad_w / 2, grad_y + grad_h + 0.030,
        "Mean pass rate (%)", ha="center", va="bottom",
        fontsize=6.0, color="#333333", transform=ax.transAxes,
    )
    for value, fraction in (
        (vmin, 0.0), ((vmin + vmax) / 2, 0.5), (vmax, 1.0)
    ):
        ax.text(
            grad_x + grad_w * fraction, grad_y - 0.014, f"{value:.0f}",
            ha="center", va="top", fontsize=4.5, color="#666666",
            transform=ax.transAxes,
        )


def _reference_panel_d(ax: plt.Axes, metrics: pd.DataFrame) -> None:
    """Panel D with only the original radar, pass-rate and example cards."""
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")
    card_x = [0.010, 0.515]
    card_width = 0.475
    card_y = 0.055
    card_height = 0.790
    accents = ["#2E7D32", "#D64535"]

    for xpos, accent, example in zip(
        card_x, accents, ABCD_MODULE.CASE_EXAMPLES
    ):
        stats, mean_rate = ABCD_MODULE._case_category_stats(metrics, example)
        ax.add_patch(plt.Rectangle(
            (xpos, card_y), card_width, card_height,
            transform=ax.transAxes, facecolor="#FBFBFB",
            edgecolor="#D2D2D2", linewidth=0.55, zorder=1,
        ))
        ax.add_patch(plt.Rectangle(
            (xpos, card_y), 0.008, card_height,
            transform=ax.transAxes, facecolor=accent,
            edgecolor="none", zorder=2,
        ))
        disease_name = ABCD_MODULE.DISEASE_FULL_NAMES.get(
            example["disease"], example["disease"]
        ).rsplit(" (", 1)[0]
        ax.text(
            xpos + card_width / 2, card_y + card_height - 0.075,
            f"{disease_name} × {example['genes']} genes",
            ha="center", va="center", fontsize=6.6,
            color="#111111", transform=ax.transAxes, zorder=3,
        )

        ABCD_MODULE._draw_case_radar(
            ax, [xpos + 0.027, card_y + 0.115, 0.098, 0.430],
            stats, accent,
        )

        pass_x, pass_y, pass_w, pass_h = (
            xpos + 0.137, card_y + 0.055, 0.120, 0.535
        )
        ax.add_patch(plt.Rectangle(
            (pass_x, pass_y), pass_w, pass_h,
            transform=ax.transAxes, facecolor="white",
            edgecolor="#777777", linewidth=0.50, zorder=2,
        ))
        ax.text(
            pass_x + pass_w / 2, pass_y + pass_h - 0.055,
            "Pass rate (%)", ha="center", va="center",
            fontsize=5.2, color="#222222", transform=ax.transAxes, zorder=3,
        )
        line_x0, line_x1 = pass_x + 0.012, pass_x + pass_w - 0.012
        line_y = pass_y + pass_h - 0.115
        ax.add_patch(plt.Rectangle(
            (line_x0, line_y), line_x1 - line_x0, 0.009,
            transform=ax.transAxes, facecolor="#E8E8E8",
            edgecolor="none", zorder=2,
        ))
        ax.add_patch(plt.Rectangle(
            (line_x0, line_y),
            (line_x1 - line_x0) * mean_rate / 100.0, 0.009,
            transform=ax.transAxes, facecolor=accent,
            edgecolor="none", zorder=3,
        ))
        list_top = line_y - 0.070
        list_gap = 0.079
        for index, stat in enumerate(stats):
            ypos = list_top - index * list_gap
            category = stat["cat"]
            ax.add_patch(plt.Rectangle(
                (pass_x + 0.012, ypos - 0.004), 0.008, 0.004,
                transform=ax.transAxes,
                facecolor=ABCD_MODULE.CAT_COLORS[category],
                edgecolor="none", zorder=3,
            ))
            label = (
                f"{category} {stat['passed']}/{stat['matched']} "
                f"({stat['rate']:.0f}%)"
                if stat["matched"] > 0
                else f"{category} n/a"
            )
            ax.text(
                pass_x + 0.026, ypos, label,
                ha="left", va="center", fontsize=4.4,
                color="#222222", transform=ax.transAxes, zorder=3,
            )

        examples_x = xpos + 0.267
        examples_y = pass_y
        examples_w = card_width - 0.279
        examples_h = pass_h
        ax.add_patch(plt.Rectangle(
            (examples_x, examples_y), examples_w, examples_h,
            transform=ax.transAxes, facecolor="white",
            edgecolor="#777777", linewidth=0.50, zorder=2,
        ))
        ax.text(
            examples_x + examples_w / 2,
            examples_y + examples_h - 0.055,
            "Generated hypothesis examples",
            ha="center", va="center", fontsize=5.0,
            color="#222222", transform=ax.transAxes, zorder=3,
        )
        row_top = examples_y + examples_h - 0.125
        row_gap = 0.083
        for index, (name, supported, category, pathway_id) in enumerate(
            example["rows"]
        ):
            ypos = row_top - index * row_gap
            ax.text(
                examples_x + 0.013, ypos, str(index + 1),
                ha="center", va="center", fontsize=3.6,
                color="#555555", transform=ax.transAxes, zorder=3,
                bbox=dict(
                    boxstyle="circle,pad=0.12", facecolor="#F4F4F4",
                    edgecolor="#BDBDBD", linewidth=0.35,
                ),
            )
            short_category = ABCD_MODULE.CAT_SHORT.get(category, category)
            badge_w = 0.026 if len(short_category) <= 2 else 0.040
            badge_x = examples_x + 0.030
            ax.add_patch(FancyBboxPatch(
                (badge_x, ypos - 0.012), badge_w, 0.024,
                boxstyle="round,pad=0.001,rounding_size=0.003",
                transform=ax.transAxes,
                facecolor=to_rgba(ABCD_MODULE.CAT_COLORS[category], 0.12),
                edgecolor=ABCD_MODULE.CAT_COLORS[category],
                linewidth=0.35, zorder=3,
            ))
            ax.text(
                badge_x + badge_w / 2, ypos, short_category,
                ha="center", va="center", fontsize=3.0,
                color=ABCD_MODULE.CAT_COLORS[category],
                transform=ax.transAxes, zorder=4,
            )
            status = "√" if supported else "X"
            label = ABCD_MODULE._wrap_pathway_label(
                f"{pathway_id}: {name} ({status})", width=32
            )
            ax.text(
                badge_x + badge_w + 0.008, ypos + 0.013, label,
                ha="left", va="top", fontsize=3.05,
                linespacing=0.94, color="#111111",
                transform=ax.transAxes, zorder=3,
            )


def draw_abcd_landscape(
    metrics: pd.DataFrame,
    enriched: pd.DataFrame,
) -> plt.Figure:
    """Draw A-D with the content density of Figure2_2026_0712.pdf."""
    mpl.rcParams.update({
        "font.family": "sans-serif",
        "font.sans-serif": ["Arial", "Helvetica", "DejaVu Sans"],
        "pdf.fonttype": 42,
        "svg.fonttype": "none",
        "axes.linewidth": 0.65,
    })
    iter1, cat_data, cat_disease_avgs = _prepare_ab_data(metrics)
    ms_iter1 = enriched[
        enriched["iteration"].eq(1) & enriched["new_matched"].gt(0)
    ].copy()
    pair_sizes = (
        enriched.loc[
            enriched["iteration"].eq(1),
            ["disease", "module", "module_size"],
        ]
        .drop_duplicates(["disease", "module"])
    )
    size_edges = np.unique(np.percentile(
        pair_sizes["module_size"].astype(float), [0, 25, 50, 75, 100]
    ))

    fig = plt.figure(figsize=(11.33, 4.35), facecolor="white")
    ax_a = fig.add_axes([0.048, 0.585, 0.395, 0.270])
    ax_b = fig.add_axes([0.540, 0.585, 0.445, 0.270])
    ax_c = fig.add_axes([0.060, 0.045, 0.390, 0.365])
    ax_d = fig.add_axes([0.470, 0.035, 0.520, 0.395])

    _reference_panel_a(ax_a, cat_data, metrics)
    _reference_panel_b(ax_b, cat_disease_avgs)
    _reference_panel_c(ax_c, ms_iter1, size_edges=size_edges)
    _reference_panel_d(ax_d, iter1)

    label_style = dict(
        fontsize=11.0, fontweight="bold", ha="left", va="top"
    )
    title_style = dict(
        fontsize=9.0, fontweight="bold", ha="center", va="top"
    )
    fig.text(0.008, 0.955, "A", **label_style)
    fig.text(0.245, 0.940,
             "Statistical validation pass rate across all gene-disease contexts",
             **title_style)
    fig.text(0.495, 0.955, "B", **label_style)
    fig.text(0.765, 0.940,
             "Statistical validation pass rate at the disease level",
             **title_style)
    fig.text(0.006, 0.485, "C", **label_style)
    fig.text(0.255, 0.465,
             "Statistical validation pass rate stratified by gene-list size",
             **title_style)
    fig.text(0.430, 0.485, "D", **label_style)
    fig.text(0.735, 0.475, "Representative gene-disease contexts",
             **title_style)

    handles = [
        Line2D(
            [0], [0],
            color=ABCD_MODULE.CAT_COLORS[category],
            marker="o",
            markersize=4.2,
            markerfacecolor=ABCD_MODULE.CAT_COLORS[category],
            markeredgecolor="white",
            markeredgewidth=0.4,
            linewidth=1.6,
            label=category,
        )
        for category in ABCD_MODULE.CATEGORIES
    ]
    fig.legend(
        handles=handles,
        loc="upper center",
        bbox_to_anchor=(0.245, 0.885),
        ncol=5,
        frameon=False,
        fontsize=5.3,
        handlelength=1.10,
        columnspacing=0.70,
        handletextpad=0.3,
        borderaxespad=0,
    )
    return fig


def _save_figure_bundle(fig: plt.Figure, base: Path) -> None:
    fig.savefig(base.with_suffix(".pdf"), facecolor="white")
    fig.savefig(base.with_suffix(".svg"), facecolor="white")
    fig.savefig(base.with_suffix(".png"), dpi=600, facecolor="white")
    fig.savefig(
        base.with_suffix(".tiff"), dpi=600, facecolor="white",
        pil_kwargs={"compression": "tiff_lzw"},
    )


def _combine_pdf_and_rasters(abcd_base: Path, e_base: Path, full_base: Path) -> None:
    """Stack the two vector PDFs and matching 600-dpi rasters."""
    abcd_page = PdfReader(str(abcd_base.with_suffix(".pdf"))).pages[0]
    e_page = PdfReader(str(e_base.with_suffix(".pdf"))).pages[0]
    gap = 5.0
    width = max(float(abcd_page.mediabox.width), float(e_page.mediabox.width))
    height = (
        float(abcd_page.mediabox.height)
        + float(e_page.mediabox.height)
        + gap
    )
    page = PageObject.create_blank_page(width=width, height=height)
    e_copy = deepcopy(e_page)
    e_copy.add_transformation(Transformation().translate(0, 0))
    page.merge_page(e_copy)
    abcd_copy = deepcopy(abcd_page)
    abcd_copy.add_transformation(
        Transformation().translate(0, float(e_page.mediabox.height) + gap)
    )
    page.merge_page(abcd_copy)
    writer = PdfWriter()
    writer.add_page(page)
    with full_base.with_suffix(".pdf").open("wb") as handle:
        writer.write(handle)

    abcd_image = Image.open(abcd_base.with_suffix(".png")).convert("RGB")
    e_image = Image.open(e_base.with_suffix(".png")).convert("RGB")
    target_width = max(abcd_image.width, e_image.width)
    if abcd_image.width != target_width:
        new_height = round(abcd_image.height * target_width / abcd_image.width)
        abcd_image = abcd_image.resize((target_width, new_height))
    if e_image.width != target_width:
        new_height = round(e_image.height * target_width / e_image.width)
        e_image = e_image.resize((target_width, new_height))
    raster_gap = 24
    combined = Image.new(
        "RGB",
        (target_width, abcd_image.height + raster_gap + e_image.height),
        "white",
    )
    combined.paste(abcd_image, (0, 0))
    combined.paste(e_image, (0, abcd_image.height + raster_gap))
    combined.save(full_base.with_suffix(".png"), dpi=(600, 600))
    combined.save(
        full_base.with_suffix(".tiff"),
        dpi=(600, 600),
        compression="tiff_lzw",
    )


def main() -> None:
    (
        metrics,
        enriched,
        source_logs,
        validation_audit,
        e_inventory,
    ) = build_current_metrics()
    records, pairs, count_audit = audit_round1_candidates(metrics)

    metrics_path = OUTPUT_DIR / "Figure2_current_metrics_24_diseases.csv"
    enriched_path = OUTPUT_DIR / "Figure2_current_metrics_with_module_size.csv"
    source_logs_path = OUTPUT_DIR / "Figure2_current_source_files.csv"
    count_audit_path = OUTPUT_DIR / "Figure2_round1_candidate_count_audit.csv"
    validation_audit_path = (
        OUTPUT_DIR / "Figure2_round1_validation_snapshot_audit.csv"
    )
    e_inventory_path = OUTPUT_DIR / "Figure2E_source_file_inventory.csv"
    metrics.to_csv(metrics_path, index=False)
    enriched.to_csv(enriched_path, index=False)
    source_logs.to_csv(source_logs_path, index=False)
    count_audit.to_csv(count_audit_path, index=False)
    validation_audit.to_csv(validation_audit_path, index=False)
    e_inventory.to_csv(e_inventory_path, index=False)

    records = E_MODULE.add_cross_disease_sharing(records)
    outcomes, sharing, overlap = E_MODULE.summarize(records)
    sharing_validation, sharing_by_status, broad_distributions = (
        E_MODULE.summarize_sharing_validation(records)
    )
    records.to_csv(OUTPUT_DIR / "Figure2E_hypothesis_level_source_data.csv", index=False)
    outcomes.to_csv(OUTPUT_DIR / "Figure2E_outcome_summary.csv", index=False)
    overlap.to_csv(OUTPUT_DIR / "Figure2E_overlap_summary.csv", index=False)
    sharing.to_csv(OUTPUT_DIR / "Figure2E_cross_disease_sharing_summary.csv", index=False)
    sharing_validation.to_csv(
        OUTPUT_DIR / "Figure2E_sharing_by_validation_summary.csv", index=False
    )
    sharing_by_status.to_csv(
        OUTPUT_DIR / "Figure2E_sharing_prevalence_by_status.csv", index=False
    )
    broad_distributions.to_csv(
        OUTPUT_DIR / "Figure2E_broad_sharing_distributions.csv", index=False
    )

    abcd_base = OUTPUT_DIR / "Figure2ABCD_current_audited"
    abcd_fig = draw_abcd_landscape(metrics, enriched)
    _save_figure_bundle(abcd_fig, abcd_base)
    plt.close(abcd_fig)

    e_base = OUTPUT_DIR / "Figure2E_current_audited"
    e_fig = E_MODULE.draw_balanced_figure(outcomes, overlap)
    _save_figure_bundle(e_fig, e_base)
    plt.close(e_fig)

    full_base = OUTPUT_DIR / "Figure2_ABCDE_current_audited"
    _combine_pdf_and_rasters(abcd_base, e_base, full_base)

    valid_round1 = (
        enriched.loc[
            enriched["iteration"].eq(1),
            ["disease", "module", "module_size"],
        ]
        .drop_duplicates(["disease", "module"])
    )
    edges = np.unique(np.percentile(
        valid_round1["module_size"].astype(float), [0, 25, 50, 75, 100]
    ))
    manifest = {
        "snapshot": "current_memory_bank_external_audited_2026-07-20",
        "diseases": int(metrics["disease"].nunique()),
        "round1_gene_lists": int(len(pairs)),
        "round2_gene_lists": int(metrics.loc[
            metrics["iteration"].eq(2), ["disease", "module"]
        ].drop_duplicates().shape[0]),
        "round1_pathways": int(len(records)),
        "round1_status_counts": {
            key: int(value)
            for key, value in records["status"].value_counts().items()
        },
        "round1_log_json_category_mismatches": 0,
        "round1_matched_rows_current_csv": int(
            validation_audit["matched_rows"].sum()
        ),
        "round1_fdr_rows_current_csv": int(
            validation_audit["fdr_rows"].sum()
        ),
        "round1_log_current_csv_match_count_differences": int(
            validation_audit["matched_row_difference"].ne(0).sum()
        ),
        "figure2e_source_file_count": int(len(e_inventory)),
        "figure2e_cross_disease_key": (
            "predicted source + normalized generated pathway name"
        ),
        "figure2e_status_rule": (
            "same source + exact normalized pathway name"
        ),
        "figure2e_overlap_row_rule": (
            "same source + exact normalized pathway name"
        ),
        "figure2e_source_inventory_sha256": _sha256(e_inventory_path),
        "module_size_coverage": "567/567",
        "module_size_column": "cluster_walktrap",
        "panel_c_quartile_edges": [float(value) for value in edges],
        "metrics_sha256": _sha256(metrics_path),
        "enriched_metrics_sha256": _sha256(enriched_path),
    }
    (OUTPUT_DIR / "Figure2_current_snapshot_manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    print(json.dumps(manifest, indent=2, ensure_ascii=False))
    print(f"Outputs: {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
