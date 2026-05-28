#!/usr/bin/env python3
"""Analyze probability distribution differences between 2F and 3F using evaluation results."""

import json
from pathlib import Path
from typing import Any
import pandas as pd
import numpy as np

def load_segment_results(base_dir: Path, feature_profile: str) -> dict[str, Any]:
    """Load layer1 results for all segments under a feature profile."""
    segments = ["2F_A", "2F_N", "3F_A", "3F_N"]
    results = {}

    for segment in segments:
        result_file = base_dir / f"layer1_{segment}_result.json"
        if result_file.exists():
            with open(result_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                results[segment] = data
        else:
            print(f"Warning: {result_file} not found")

    return results


def analyze_probability_distribution(results: dict[str, Any]) -> pd.DataFrame:
    """Analyze probability distribution characteristics from hit_at_k metrics.

    Theory: hit_at_k patterns reveal probability distribution properties:
    - hit_at_1 high, hit_at_3/5 similar → concentrated on few machines (spread distribution)
    - hit_at_1 low, hit_at_3 high → distributed across top-3 (dispersed distribution)
    - AUC high but hit_at_1 low → good relative ordering but weak absolute confidence
    """
    analysis = []

    for segment, data in sorted(results.items()):
        floor = segment[:2]  # "2F" or "3F"
        region = segment[3]   # "A" or "N"

        if not isinstance(data, dict):
            continue

        for target, metrics in data.items():
            # Skip non-target keys
            if not isinstance(metrics, dict) or not target.startswith("target_"):
                continue

            hit_1 = metrics.get("hit_at_1", 0)
            hit_3 = metrics.get("hit_at_3", 0)
            hit_5 = metrics.get("hit_at_5", 0)
            auc = metrics.get("auc", 0)
            n_eval_days = metrics.get("n_eval_days", 0)
            base_rate = metrics.get("base_rate", 0)

            # Distribution characteristics
            # If hit_3 ≈ hit_1, probabilities are concentrated on 1 machine
            # If hit_3 >> hit_1, probabilities are dispersed across top-3
            dispersion_ratio = (hit_3 - hit_1) / max(0.01, hit_1)  # how much broader top-3 is vs top-1

            # AUC vs hit_at_1: if AUC high but hit_at_1 low → good ranking but not confident
            ranking_quality = auc / max(0.01, hit_1)  # relative ordering vs absolute confidence

            analysis.append({
                "segment": segment,
                "floor": floor,
                "target": target,
                "hit_at_1": hit_1,
                "hit_at_3": hit_3,
                "hit_at_5": hit_5,
                "auc": auc,
                "base_rate": base_rate,
                "dispersion_ratio": dispersion_ratio,
                "ranking_quality": ranking_quality,
                "n_eval_days": n_eval_days,
            })

    return pd.DataFrame(analysis)


def print_analysis(df: pd.DataFrame) -> None:
    """Print detailed analysis."""
    print("=" * 120)
    print("確率分布分析: 2F vs 3F")
    print("=" * 120)

    print("\n【指標の意味】")
    print("  hit_at_1       : 正解が予測上位1位に入る率 → 最も確信度の高い予測")
    print("  hit_at_3       : 正解が予測上位3位に入る率 → 相対的順序付けの精度")
    print("  dispersion_ratio: (hit_at_3 - hit_at_1) / hit_at_1")
    print("                   小さい(1～3) → 確率が1機種に集中")
    print("                   大きい(5～10+) → 確率が3機種に分散")
    print("  ranking_quality : AUC / hit_at_1")
    print("                   大きい(3～5+) → ランキングは正確だが絶対値が不確実")
    print("                   小さい(1～2) → 絶対値の確信度も相対順序も一致\n")

    # Aggregate by floor
    print("\n【フロア別集計】")
    print("=" * 120)

    for floor in ["2F", "3F"]:
        floor_data = df[df["floor"] == floor]
        print(f"\n{floor}:")
        print("-" * 120)

        for _, row in floor_data.iterrows():
            target_short = row["target"].replace("target_is_", "")
            print(
                f"  {row['segment']:6s} {target_short:8s}: "
                f"hit@1={row['hit_at_1']:5.1%}  hit@3={row['hit_at_3']:5.1%}  "
                f"AUC={row['auc']:.4f}  "
                f"dispersion={row['dispersion_ratio']:6.2f}  "
                f"ranking_quality={row['ranking_quality']:5.2f}"
            )

    # Comparative analysis
    print("\n\n【2F vs 3F 比較】")
    print("=" * 120)

    for target in df["target"].unique():
        target_short = target.replace("target_is_", "")
        print(f"\n{target_short}:")
        print("-" * 120)

        data_2f = df[(df["floor"] == "2F") & (df["target"] == target)]
        data_3f = df[(df["floor"] == "3F") & (df["target"] == target)]

        if len(data_2f) > 0 and len(data_3f) > 0:
            hit_1_2f = data_2f["hit_at_1"].mean()
            hit_1_3f = data_3f["hit_at_1"].mean()
            auc_2f = data_2f["auc"].mean()
            auc_3f = data_3f["auc"].mean()
            dispersion_2f = data_2f["dispersion_ratio"].mean()
            dispersion_3f = data_3f["dispersion_ratio"].mean()
            ranking_2f = data_2f["ranking_quality"].mean()
            ranking_3f = data_3f["ranking_quality"].mean()

            print(f"  2F: hit@1={hit_1_2f:.1%}  AUC={auc_2f:.4f}  dispersion={dispersion_2f:6.2f}  ranking_quality={ranking_2f:5.2f}")
            print(f"  3F: hit@1={hit_1_3f:.1%}  AUC={auc_3f:.4f}  dispersion={dispersion_3f:6.2f}  ranking_quality={ranking_3f:5.2f}")
            print(f"  Δ : hit@1={hit_1_3f-hit_1_2f:+.1%}  AUC={auc_3f-auc_2f:+.4f}  dispersion={dispersion_3f-dispersion_2f:+6.2f}")

            # Interpretation
            print(f"\n  解釈:")
            if dispersion_2f < dispersion_3f:
                print(f"    → 2F は確率が {dispersion_2f:.1f} で少数機種に集中 (「多くの機種に0.5」ではなく「決まった機種に確信」)")
                print(f"    → 3F は確率が {dispersion_3f:.1f} で分散している (エンジニアリング特徴量で区別化)")
            else:
                print(f"    → 2F と 3F の確率分散はほぼ同程度")

            if ranking_2f > ranking_3f:
                print(f"    → 2F: AUC={auc_2f:.4f} だがhit@1={hit_1_2f:.1%} → ランキングは正確だが絶対値が曖昧")
                print(f"    → 3F: AUC={auc_3f:.4f} でhit@1={hit_1_3f:.1%} → ランキングも絶対値も区別化")
            else:
                print(f"    → 両セグメント共に相対順序と絶対値が一致している傾向")


def compare_baseline_vs_rich(
    baseline_dir: Path,
    rich_dir: Path,
) -> None:
    """Compare baseline6 vs rich_all probability distributions."""
    print("\n\n" + "=" * 120)
    print("baseline6 vs rich_all の確率分布比較")
    print("=" * 120)

    baseline_results = load_segment_results(baseline_dir, "baseline6")
    rich_results = load_segment_results(rich_dir, "rich_all")

    baseline_df = analyze_probability_distribution(baseline_results)
    rich_df = analyze_probability_distribution(rich_results)

    # Merge for comparison
    comparison = baseline_df.merge(
        rich_df,
        on=["segment", "floor", "target"],
        suffixes=("_baseline6", "_rich_all"),
    )

    print("\nセグメント別 AUC と hit@1 の変化:")
    print("-" * 120)

    for target in comparison["target"].unique():
        target_short = target.replace("target_is_", "")
        target_data = comparison[comparison["target"] == target]

        print(f"\n{target_short}:")
        for _, row in target_data.iterrows():
            auc_change = row["auc_rich_all"] - row["auc_baseline6"]
            hit_1_change = row["hit_at_1_rich_all"] - row["hit_at_1_baseline6"]
            dispersion_change = row["dispersion_ratio_rich_all"] - row["dispersion_ratio_baseline6"]

            print(
                f"  {row['segment']:6s}: "
                f"AUC {row['auc_baseline6']:.4f} → {row['auc_rich_all']:.4f} ({auc_change:+.4f})  "
                f"hit@1 {row['hit_at_1_baseline6']:.1%} → {row['hit_at_1_rich_all']:.1%} ({hit_1_change:+.1%})  "
                f"dispersion {row['dispersion_ratio_baseline6']:.2f} → {row['dispersion_ratio_rich_all']:.2f} ({dispersion_change:+.2f})"
            )

    print("\n\n【仮説検証】")
    print("=" * 120)
    print("""
ユーザーの仮説:
  「2F は多くの機種にランダムに近い確率で分散」
  「3F は比較的決まった機種に入りやすい」

分析結果から検証:
  - dispersion_ratio が小さい → 確率が少数機種に集中
  - dispersion_ratio が大きい → 確率が複数機種に分散
  - ranking_quality が大きい → AUC は高いが hit@1 は低い（相対順序は正確、絶対値は不確実）

期待される結果:
  - 2F: dispersion_ratio 小 (1～3) → 「決まった機種に入る」
  - 3F: dispersion_ratio 大 (5～10+) → 「複数機種に分散」
  - rich_all 導入後:
    - 2F: dispersion_ratio 悪化（機種の区別が曖昧になるノイズ）
    - 3F: dispersion_ratio 改善（エンジニアリング特徴量で区別化）
""")


def main():
    # baseline6 results
    baseline_dir = Path("ml/machine_type/v2/output/auto_explore_20260526_100706/baseline_tune")

    # rich_all results (task1 = rich_all)
    rich_dir = Path("ml/machine_type/v2/output/auto_explore_20260526_100706/task1_tune_rich_all")

    if not baseline_dir.exists():
        print(f"ERROR: baseline dir not found: {baseline_dir}")
        return

    if not rich_dir.exists():
        print(f"ERROR: rich_all dir not found: {rich_dir}")
        return

    # Analyze baseline6
    print("\n【baseline6 の確率分布分析】")
    baseline_results = load_segment_results(baseline_dir, "baseline6")
    baseline_df = analyze_probability_distribution(baseline_results)
    print_analysis(baseline_df)

    # Analyze rich_all
    print("\n\n【rich_all の確率分布分析】")
    rich_results = load_segment_results(rich_dir, "rich_all")
    rich_df = analyze_probability_distribution(rich_results)
    print_analysis(rich_df)

    # Compare
    compare_baseline_vs_rich(baseline_dir, rich_dir)

    print("\n" + "=" * 120)


if __name__ == "__main__":
    main()
