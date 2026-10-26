#!/usr/bin/env python3
"""Audit Supplementary Figure S7 from deposited per-module metric exports."""

import argparse
import csv
import json
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data" / "suppfig_s7"
CATEGORIES = ("GO:BP", "GO:MF", "GO:CC", "KEGG", "REAC")
STRATEGIES = (
    ("Initial prompt", "ranking_nfdr_metrics.csv", "control", 1),
    ("Raw memory", "ranking_nfdr_metrics.csv", "experimental", 1),
    ("Semantic RAG", "rag_nfdr_metrics.csv", None, 1),
    ("RAG+", "rag_plus_nfdr_metrics.csv", None, 1),
    ("RAG+ prompt", "rag_plus_prompt_nfdr_metrics.csv", None, 1),
    ("Refined prompt", "ranking_nfdr_metrics.csv", "control", 2),
)
REPORTED_BARS = {
    "Initial prompt": (24.5, 25.3, 26.9, 31.5, 28.2),
    "Raw memory": (27.7, 29.8, 33.2, 35.6, 28.5),
    "Semantic RAG": (26.4, 26.9, 32.6, 33.3, 25.5),
    "RAG+": (26.3, 28.9, 30.5, 31.8, 28.2),
    "RAG+ prompt": (25.2, 30.5, 28.8, 29.4, 32.1),
    "Refined prompt": (43.4, 47.6, 47.8, 42.5, 50.2),
}
EXPECTED_PAIR_COUNTS = {"CARDI": 2, "HF": 2, "INSUL": 7, "MELAN": 15, "OBESI": 43}


def read_source(path):
    with path.open(newline="", encoding="utf-8-sig") as handle:
        rows = list(csv.DictReader(handle))
    required = {"disease", "module", "iteration", "category", "new_matched", "nfdr_pct"}
    if not rows or not required.issubset(rows[0]):
        raise ValueError("Missing required fields in " + str(path))
    for row in rows:
        row["iteration"] = int(row["iteration"])
        row["new_matched"] = int(row["new_matched"])
        row["nfdr_pct"] = float(row["nfdr_pct"])
        if row["category"] not in CATEGORIES or not 0 <= row["nfdr_pct"] <= 100:
            raise ValueError("Invalid category or percentage in " + str(path))
    keys = [(r["disease"], r["module"], r["iteration"], r["category"], r.get("condition")) for r in rows]
    if len(keys) != len(set(keys)):
        raise ValueError("Duplicate disease/module/round/category in " + str(path))
    return rows


def bootstrap(valid_rows, repeats, rng):
    """Mirror the historical plot's disease -> valid-module bootstrap.

    Reference: plot_memory_effect_by_category.py, SHA-256
    1e8e2c2580028bf0f875f942d22905683ea7e4f30dbbc86f7831122caa903eaf.
    """
    disease_groups = {}
    for row in valid_rows:
        modules = disease_groups.setdefault(row["disease"], {})
        modules.setdefault(row["module"], []).append(row["nfdr_pct"])
    groups = [[np.asarray(values, dtype=float) for values in modules.values()]
              for modules in disease_groups.values()]
    if len(groups) <= 1:
        value = float(np.mean([r["nfdr_pct"] for r in valid_rows]))
        return value, value
    boot_means = np.empty(repeats, dtype=float)
    for index in range(repeats):
        sampled_diseases = rng.integers(0, len(groups), len(groups))
        sampled_values = []
        for disease_index in sampled_diseases:
            modules = groups[disease_index]
            sampled_modules = rng.integers(0, len(modules), len(modules))
            sampled_values.extend(modules[module_index] for module_index in sampled_modules)
        boot_means[index] = np.mean(np.concatenate(sampled_values))
    low, high = np.percentile(boot_means, [2.5, 97.5])
    return max(0.0, float(low)), min(100.0, float(high))


def write_csv(path, fieldnames, rows):
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def make_plot(summary, output_dir):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(11, 5.6))
    x = np.arange(len(CATEGORIES))
    width = 0.14
    colors = ("#7f8c8d", "#4285a8", "#78adbf", "#8d78ac", "#c98f64", "#285842")
    lookup = {(r["strategy"], r["category"]): r for r in summary}
    for index, (strategy, _, _, _) in enumerate(STRATEGIES):
        records = [lookup[(strategy, category)] for category in CATEGORIES]
        heights = np.array([r["pass_rate_pct"] for r in records])
        lo = np.array([r["bootstrap_95_lower_pct"] for r in records])
        hi = np.array([r["bootstrap_95_upper_pct"] for r in records])
        xpos = x + (index - 2.5) * width
        ax.bar(xpos, heights, width, color=colors[index], label=strategy)
        ax.errorbar(xpos, heights, yerr=[heights - lo, hi - heights], fmt="none",
                    ecolor="#333333", elinewidth=0.8, capsize=2)
    ax.set_xticks(x)
    ax.set_xticklabels(CATEGORIES)
    ax.set_ylabel("FDR pass rate (%)")
    ax.set_ylim(0, max(r["bootstrap_95_upper_pct"] for r in summary) + 8)
    ax.legend(ncol=3, loc="upper center", bbox_to_anchor=(0.5, -0.12), frameon=False)
    ax.spines[["top", "right"]].set_visible(False)
    ax.grid(axis="y", color="#e9e9e9", linewidth=0.6)
    ax.set_axisbelow(True)
    fig.tight_layout()
    fig.savefig(output_dir / "Supplementary_Figure_S7_numeric_reproduction.pdf", bbox_inches="tight")
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "output" / "suppfig_s7_reproduction")
    parser.add_argument("--bootstrap", type=int, default=3000)
    parser.add_argument("--seed", type=int, default=2406)
    parser.add_argument("--no-plot", action="store_true")
    args = parser.parse_args()
    if args.bootstrap < 1:
        parser.error("--bootstrap must be positive")

    source_rows = {filename: read_source(DATA / filename) for _, filename, _, _ in STRATEGIES}
    source_pairs = {}
    for filename, rows in source_rows.items():
        pairs = {(r["disease"], r["module"]) for r in rows}
        counts = Counter(disease for disease, _ in pairs)
        if dict(counts) != EXPECTED_PAIR_COUNTS:
            raise AssertionError("69-pair cohort mismatch in " + filename)
        source_pairs[filename] = pairs
    if len(set(frozenset(p) for p in source_pairs.values())) != 1:
        raise AssertionError("Sources do not share the same 69 disease/module inputs")
    all_pairs = defaultdict(list)
    for disease, module in sorted(next(iter(source_pairs.values()))):
        all_pairs[disease].append(module)

    summary = []
    rng = np.random.default_rng(args.seed)
    selections = {}
    for strategy, filename, condition, iteration in STRATEGIES:
        rows = [r for r in source_rows[filename]
                if r["iteration"] == iteration and (condition is None or r.get("condition") == condition)]
        round_pairs = {(r["disease"], r["module"]) for r in rows}
        if len(rows) != 5 * len(round_pairs):
            raise AssertionError("Incomplete category rows for " + strategy)
        selections[strategy] = (rows, len(round_pairs), filename)
    # The historical plotting function iterated categories first, then strategies,
    # using one seeded NumPy generator throughout all 30 interval calculations.
    for index, category in enumerate(CATEGORIES):
        for strategy, _, _, _ in STRATEGIES:
            rows, round_pair_count, filename = selections[strategy]
            valid_rows = [r for r in rows
                          if r["category"] == category and r["new_matched"] > 0]
            values = [r["nfdr_pct"] for r in valid_rows]
            result = float(np.mean(values))
            if abs(result - REPORTED_BARS[strategy][index]) >= 0.05000001:
                raise AssertionError("Reported S7 bar mismatch: %s %s %.4f" %
                                     (strategy, category, result))
            lo, hi = bootstrap(valid_rows, args.bootstrap, rng)
            summary.append({
                "strategy": strategy,
                "category": category,
                "input_pairs": sum(map(len, all_pairs.values())),
                "round_pairs_present": round_pair_count,
                "valid_n_new_matched_gt_0": len(valid_rows),
                "pass_rate_pct": round(result, 6),
                "reported_bar_pct": REPORTED_BARS[strategy][index],
                "bootstrap_95_lower_pct": round(lo, 6),
                "bootstrap_95_upper_pct": round(hi, 6),
                "source_file": "data/suppfig_s7/" + filename,
            })

    args.output_dir.mkdir(parents=True, exist_ok=True)
    write_csv(args.output_dir / "Supplementary_Figure_S7_values.csv", list(summary[0]), summary)
    audit = {
        "cohort_pair_counts": EXPECTED_PAIR_COUNTS,
        "bar_calculation": "Unweighted mean of nfdr_pct after excluding new_matched=0; one row per available disease/module/category.",
        "bootstrap": "Historical Figure S7 two-level bootstrap: after filtering new_matched=0, diseases with replacement, then valid modules within each selected disease; NumPy default_rng shared across category-major/strategy-minor bar order.",
        "bootstrap_seed": args.seed,
        "bootstrap_repeats": args.bootstrap,
        "historical_bootstrap_script_sha256": "1e8e2c2580028bf0f875f942d22905683ea7e4f30dbbc86f7831122caa903eaf",
        "reported_bars_matched": 30,
        "round_pairs_present": {name: next(r["round_pairs_present"] for r in summary if r["strategy"] == name)
                                for name, _, _, _ in STRATEGIES},
        "limits": "Deposited CSVs are derived metrics. Original model/API responses, memory bank construction, and retrieval traces are not reconstructed.",
    }
    (args.output_dir / "Supplementary_Figure_S7_audit.json").write_text(
        json.dumps(audit, indent=2) + "\n", encoding="utf-8")
    if not args.no_plot:
        make_plot(summary, args.output_dir)
    print("Matched all 30 reported S7 bars; 69 shared input pairs; output:", args.output_dir)
    print("Available prompt-round pairs:", audit["round_pairs_present"])


if __name__ == "__main__":
    main()
