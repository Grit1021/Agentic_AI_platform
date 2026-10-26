#!/usr/bin/env python
"""
生成跨疾病 NFDR Metrics CSV 文件 - 24 diseases (external memory bank)

从 memory_bank_external 中每个disease的run_log文件提取NFDR数据，
生成汇总CSV文件供绘图使用。
"""

import os
import re
import glob
import pandas as pd

# Configuration
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
RUN_ROOT = Path(os.environ.get("BENCHMARK_RUN_ROOT", PROJECT_ROOT))
BASE_DIR = str(RUN_ROOT / "result" / "memory_bank_external")
OUTPUT_DIR = str(Path(os.environ.get(
    "BENCHMARK_FIGURE2_OUTPUT_DIR", PROJECT_ROOT / "output" / "figure2_consistent_current"
)))

# All 24 diseases in the external memory bank
DISEASES = sorted([
    'AD', 'AF', 'AIT', 'ALS', 'AST', 'CAD', 'CD', 'CKD', 'COPD', 'CRC',
    'HCC', 'HF', 'HTN', 'IBD', 'MDD', 'MS', 'OSA', 'PD', 'PS', 'PSP',
    'RA', 'SLE', 'T2D', 'TB',
])


def find_latest_run_log(disease):
    """查找最新的run_log文件"""
    pattern = os.path.join(BASE_DIR, f"iterative_feedback_{disease}", f"{disease}_aggregated_*", f"run_log_*.txt")
    matches = glob.glob(pattern)
    if not matches:
        return None
    return max(matches, key=os.path.getmtime)


def extract_category_data_from_log(log_path, disease_code):
    """
    从 run_log 文件提取 category breakdown 数据

    Iteration 1 格式 (7列):
      Category   | Retained | NewGen | Total | Match | Mat%  | FDR  | FDR%
      GO:BP      | 0        | 10     | 10    | 13    |  130% | 3    |   23%

    Iteration 2/3 格式 (11列):
      Category   | Retained | NewGen | Total | Match | NewMat | Mat%  | NMat%  | FDR  | NewFDR | FDR%  | NFDR%
      GO:BP      | 2        | 8      | 10    | 8     | 6      |   80% |   60% | 6    | 4      |   75% |   67%
    """
    if not os.path.exists(log_path):
        print(f"  ⚠️  文件不存在: {log_path}")
        return []

    with open(log_path, 'r', encoding='utf-8', errors='ignore') as f:
        content = f.read()

    records = []

    # Iteration 1 格式 (7列)
    pattern_7col = re.compile(
        r'^\s*(GO:BP|GO:MF|GO:CC|KEGG|REAC)\s*\|\s*(\d+)\s*\|\s*(\d+)\s*\|\s*(\d+)\s*\|\s*(\d+)\s*\|\s*(\d+)%\s*\|\s*(\d+)\s*\|\s*(\d+)%\s*$'
    )

    # Iteration 2/3 格式 (11列)
    pattern_11col = re.compile(
        r'^\s*(GO:BP|GO:MF|GO:CC|KEGG|REAC)\s*\|\s*(\d+)\s*\|\s*(\d+)\s*\|\s*(\d+)\s*\|\s*(\d+)\s*\|\s*(\d+)\s*\|\s*(\d+)%\s*\|\s*(\d+)%\s*\|\s*(\d+)\s*\|\s*(\d+)\s*\|\s*(\d+)%\s*\|\s*(\d+)%'
    )

    lines = content.split('\n')
    current_module = None
    current_iteration = 1

    for i, line in enumerate(lines):
        # 检测模块开始 - Phase 1
        module_match = re.search(r'MODULE\s+(\d+)\s*\(\d+/\d+\)', line)
        if module_match:
            current_module = int(module_match.group(1))
            current_iteration = 1

        # 检测 Phase 2 模块开始
        phase2_module_match = re.search(r'ITERATING MODULE\s+(\d+)', line)
        if phase2_module_match:
            current_module = int(phase2_module_match.group(1))

        # 检测迭代开始 (Phase 2)
        iter_match = re.search(r'ITERATION\s+(\d+)/\d+', line, re.IGNORECASE)
        if iter_match:
            current_iteration = int(iter_match.group(1))

        # 尝试匹配 11 列格式 (Iteration 2/3)
        match_11 = pattern_11col.match(line.strip())
        if match_11 and current_module is not None:
            category = match_11.group(1)
            retained = int(match_11.group(2))
            newgen = int(match_11.group(3))
            matched = int(match_11.group(5))
            new_matched = int(match_11.group(6))
            nfdr_pct = int(match_11.group(12))
            fdr_pct = int(match_11.group(11))

            records.append({
                'disease': disease_code,
                'module': current_module,
                'iteration': current_iteration,
                'category': category,
                'retained': retained,
                'newgen': newgen,
                'matched': matched,
                'new_matched': new_matched,
                'fdr_pct': fdr_pct,
                'nfdr_pct': nfdr_pct
            })
            continue

        # 尝试匹配 7 列格式 (Iteration 1)
        match_7 = pattern_7col.match(line.strip())
        if match_7 and current_module is not None and current_iteration == 1:
            category = match_7.group(1)
            retained = int(match_7.group(2))
            newgen = int(match_7.group(3))
            matched = int(match_7.group(5))
            fdr_pct = int(match_7.group(8))

            records.append({
                'disease': disease_code,
                'module': current_module,
                'iteration': current_iteration,
                'category': category,
                'retained': retained,
                'newgen': newgen,
                'matched': matched,
                'new_matched': matched,  # Iter 1: all matched are new
                'fdr_pct': fdr_pct,
                'nfdr_pct': fdr_pct  # Iter 1: FDR% = NFDR%
            })

    return records


def main():
    print("=" * 70)
    print("生成跨疾病 NFDR Metrics CSV 文件 (24 diseases, external)")
    print("=" * 70)

    all_records = []
    max_iteration = 2

    for disease in DISEASES:
        log_path = find_latest_run_log(disease)
        if log_path is None:
            print(f"  ⚠️  {disease}: 未找到run_log文件")
            continue

        print(f"  {disease}: {os.path.basename(log_path)}")
        records = extract_category_data_from_log(log_path, disease)
        # Only keep iterations <= max_iteration
        records = [r for r in records if r['iteration'] <= max_iteration]
        all_records.extend(records)
        print(f"    → {len(records)} 条记录")

    if not all_records:
        print("\n❌ 未提取到任何数据")
        return

    combined_df = pd.DataFrame(all_records)
    num_diseases = combined_df['disease'].nunique()

    print(f"\n合并后总记录: {len(combined_df)}")
    print(f"疾病 ({num_diseases}): {sorted(combined_df['disease'].unique())}")
    print(f"Categories: {sorted(combined_df['category'].unique())}")

    # Save CSV
    output_filename = f"cross_disease_{num_diseases}_nfdr_metrics_v5.csv"
    output_path = os.path.join(OUTPUT_DIR, output_filename)
    combined_df.to_csv(output_path, index=False)
    print(f"\n✅ 数据已保存: {output_path}")

    # Print summary
    print("\n" + "=" * 70)
    print("数据统计摘要")
    print("=" * 70)
    for disease in sorted(combined_df['disease'].unique()):
        disease_df = combined_df[combined_df['disease'] == disease]
        modules = disease_df['module'].nunique()
        print(f"  {disease:6s}: {len(disease_df):4d} 条记录, {modules:2d} 个模块")
    print("=" * 70)


if __name__ == '__main__':
    main()
