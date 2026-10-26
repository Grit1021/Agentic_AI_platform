#!/usr/bin/env python
"""
生成跨疾病 NFDR Metrics CSV 文件 - 24 diseases (external memory bank) - v6

从 memory_bank_external 中每个disease的run_log文件提取NFDR数据，
生成汇总CSV文件供绘图使用。

v6 修复:
  - 修复了 v5 中 7 列格式表格仅在 iteration==1 时被解析的 bug。
    当 iter2 中 Retained 全为 0 时，run_log 会输出 7 列格式而非 11 列格式，
    v5 的 `current_iteration == 1` 限制导致这些 iter2 数据被跳过。
  - 修复后，所有 567 个 gene lists 在 iter1 和 iter2 中完全对齐。
  - 增加了 iter1/iter2 对齐验证。
"""

import os
import re
import glob
import pandas as pd
from pathlib import Path

# Configuration
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

    注意: 当 iter2 中所有 category 的 Retained=0 时，run_log 也会输出 7 列格式。
    此时 matched == new_matched, fdr_pct == nfdr_pct (因为没有保留的旧 pathway)。
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

        # 尝试匹配 7 列格式
        # v6 修复: 去掉了 current_iteration == 1 的限制，
        # 因为 iter2 中 Retained=0 的模块也会输出 7 列格式。
        # 当 7 列格式出现在 iter2 中时，说明没有保留旧 pathway，
        # 所以 matched == new_matched, fdr_pct == nfdr_pct。
        match_7 = pattern_7col.match(line.strip())
        if match_7 and current_module is not None:
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
                'new_matched': matched,  # 7列格式: all matched are new
                'fdr_pct': fdr_pct,
                'nfdr_pct': fdr_pct  # 7列格式: FDR% = NFDR%
            })

    return records


def main():
    print("=" * 70)
    print("生成跨疾病 NFDR Metrics CSV 文件 (24 diseases, external) - v6")
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

    # ── v6: iter1/iter2 对齐验证 ──
    print("\n" + "=" * 70)
    print("iter1/iter2 对齐验证")
    print("=" * 70)
    iter1_gl = set()
    iter2_gl = set()
    for _, row in combined_df.iterrows():
        key = (row['disease'], row['module'])
        if row['iteration'] == 1:
            iter1_gl.add(key)
        elif row['iteration'] == 2:
            iter2_gl.add(key)

    iter1_count = len(combined_df[combined_df['iteration'] == 1])
    iter2_count = len(combined_df[combined_df['iteration'] == 2])
    print(f"  Iter1: {len(iter1_gl)} gene lists × 5 databases = {iter1_count} 行")
    print(f"  Iter2: {len(iter2_gl)} gene lists × 5 databases = {iter2_count} 行")

    missing_in_iter2 = iter1_gl - iter2_gl
    missing_in_iter1 = iter2_gl - iter1_gl
    if missing_in_iter2:
        print(f"  ⚠️  Iter2 缺少 {len(missing_in_iter2)} 个 gene lists:")
        for d, m in sorted(missing_in_iter2):
            print(f"      {d} module {m}")
    if missing_in_iter1:
        print(f"  ⚠️  Iter1 缺少 {len(missing_in_iter1)} 个 gene lists:")
        for d, m in sorted(missing_in_iter1):
            print(f"      {d} module {m}")
    if not missing_in_iter2 and not missing_in_iter1:
        print(f"  ✅ 完全对齐! {len(iter1_gl)} gene lists 在两轮中均有数据")

    # Save CSV
    output_filename = f"cross_disease_{num_diseases}_nfdr_metrics_v6.csv"
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
        iter1_n = len(disease_df[disease_df['iteration'] == 1])
        iter2_n = len(disease_df[disease_df['iteration'] == 2])
        status = "✅" if iter1_n == iter2_n else "⚠️"
        print(f"  {status} {disease:6s}: {len(disease_df):4d} 条记录, {modules:2d} 个模块 (iter1={iter1_n}, iter2={iter2_n})")
    print("=" * 70)


if __name__ == '__main__':
    main()
