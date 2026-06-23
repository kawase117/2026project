"""角番概念の比較実験: 通路角番 vs 両端角番

3つの角番グルーピングを比較し、どれが店舗の設定投入パターンを
最もよく説明するか検証する。

概念A: 通路角番 (rank_from_aisle)
  - メイン通路から数えた位置番号でグルーピング
  - 各台は1つの角番のみ

概念B: 両端角番 (rank_from_min OR rank_from_max)
  - 台番号の両端から数えた位置番号でグルーピング
  - 1台が2つの角番に所属（例: 角番2と角番8）
  - 集計時に重複カウントされる

概念C: min角番 (rank_from_min のみ、既存手法)
  - section_min側からの位置番号でグルーピング
  - ベースライン比較用

評価指標:
  - 角番別の機械割平均・104%超え率
  - Kruskal-Wallis H検定 + ε²（効果量）
  - セグメント×フロア別の結果
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

from eda.core import _bootstrap_ci, _epsilon_squared, load_hall_df
from eda.kamata7_lastdigit_lr_eda import build_floor_side_map, classify_seg, load_coords
from eda.kamata7_verification_common import (
    HALL,
    ANNIVERSARY_MMDD,
    REPORT_DIR,
    compute_payout_rate,
    ensure_report_dir,
    table_to_markdown,
    write_text,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
MAX_KAKUBAN = 11


def prepare_data() -> pd.DataFrame:
    df = load_hall_df(HALL).copy()
    df["date"] = df["date"].astype(str)
    df["machine_number"] = pd.to_numeric(df["machine_number"], errors="coerce")
    df["games"] = pd.to_numeric(df["games"], errors="coerce")
    df["diff"] = pd.to_numeric(df["diff"], errors="coerce")
    df["payout_rate"] = compute_payout_rate(df)

    mmdd = df["date"].str[4:8]
    df = df[mmdd != ANNIVERSARY_MMDD].copy()
    df = df[df["machine_number"] != 2026].copy()
    df = df.dropna(subset=["machine_number", "games", "diff"]).copy()
    df["machine_number"] = df["machine_number"].astype(int)
    df["hit104"] = (df["payout_rate"] >= 104.0).astype(int)

    coords = load_coords().copy()
    coords = coords.drop_duplicates(subset=["machine_number"], keep="first")
    coord_cols = [
        "machine_number", "section", "section_min", "section_max",
        "rank_from_min", "rank_from_max", "rank_from_aisle",
    ]
    coords = coords[coord_cols]
    for col in ["rank_from_min", "rank_from_max", "rank_from_aisle",
                "section_min", "section_max"]:
        coords[col] = pd.to_numeric(coords[col], errors="coerce")

    df = df.merge(coords, on="machine_number", how="inner")
    df["section_size"] = df["section_max"] - df["section_min"] + 1

    floor_side = build_floor_side_map()
    df = df.merge(floor_side, on="machine_number", how="inner")
    df["floor_side"] = df["floor"].astype(str) + "_" + df["side"].astype(str)

    if "machine_name" in df.columns:
        df["machine_name"] = df["machine_name"].astype(str)
        df["seg"] = df["machine_name"].map(classify_seg)

    return df.reset_index(drop=True)


def aggregate_by_kakuban(
    df: pd.DataFrame,
    kakuban_col: str,
    max_k: int = MAX_KAKUBAN,
) -> pd.DataFrame:
    sub = df[df[kakuban_col] <= max_k].copy()
    sub["kaku"] = sub[kakuban_col].astype(int)
    agg = sub.groupby("kaku").agg(
        n=("payout_rate", "size"),
        payout_mean=("payout_rate", "mean"),
        payout_median=("payout_rate", "median"),
        hit104_rate=("hit104", "mean"),
        diff_mean=("diff", "mean"),
    ).reset_index()
    agg["hit104_rate"] = agg["hit104_rate"] * 100
    return agg


def expand_dual_kakuban(df: pd.DataFrame, max_k: int = MAX_KAKUBAN) -> pd.DataFrame:
    """両端角番: 各行を rank_from_min と rank_from_max の2行に展開"""
    rows_min = df.copy()
    rows_min["kakuban_dual"] = rows_min["rank_from_min"].astype(int)

    rows_max = df.copy()
    rows_max["kakuban_dual"] = rows_max["rank_from_max"].astype(int)

    combined = pd.concat([rows_min, rows_max], ignore_index=True)
    combined = combined[combined["kakuban_dual"] <= max_k]
    combined = combined.drop_duplicates(
        subset=["date", "machine_number", "kakuban_dual"], keep="first"
    )
    return combined


def kruskal_test(df: pd.DataFrame, kakuban_col: str, max_k: int = MAX_KAKUBAN):
    sub = df[df[kakuban_col] <= max_k].copy()
    groups = [g["payout_rate"].values for _, g in sub.groupby(kakuban_col) if len(g) >= 5]
    if len(groups) < 2:
        return None, None, None
    H, p = stats.kruskal(*groups)
    n = sum(len(g) for g in groups)
    eps2 = _epsilon_squared(H, len(groups), n)
    return H, p, eps2


def run_experiment_for_segment(
    df: pd.DataFrame,
    label: str,
) -> dict:
    results = {}

    # 概念A: 通路角番
    agg_aisle = aggregate_by_kakuban(df, "rank_from_aisle")
    H_a, p_a, eps2_a = kruskal_test(df, "rank_from_aisle")
    results["aisle"] = {
        "agg": agg_aisle, "H": H_a, "p": p_a, "eps2": eps2_a,
    }

    # 概念B: 両端角番
    df_dual = expand_dual_kakuban(df)
    agg_dual = aggregate_by_kakuban(df_dual, "kakuban_dual")
    H_b, p_b, eps2_b = kruskal_test(df_dual, "kakuban_dual")
    results["dual"] = {
        "agg": agg_dual, "H": H_b, "p": p_b, "eps2": eps2_b,
    }

    # 概念C: min角番（ベースライン）
    agg_min = aggregate_by_kakuban(df, "rank_from_min")
    H_c, p_c, eps2_c = kruskal_test(df, "rank_from_min")
    results["min"] = {
        "agg": agg_min, "H": H_c, "p": p_c, "eps2": eps2_c,
    }

    return results


def format_stat(H, p, eps2) -> str:
    if H is None:
        return "N/A (insufficient data)"
    return f"H={H:.2f}, p={p:.4f}, ε²={eps2:.4f}"


def build_report(all_results: dict) -> str:
    lines = [
        "# 角番概念比較実験: 通路角番 vs 両端角番 vs min角番",
        "",
        "## 実験設計",
        "",
        "- **概念A (通路角番)**: rank_from_aisle でグルーピング。各台は1つの角番。",
        "- **概念B (両端角番)**: rank_from_min=K OR rank_from_max=K でグルーピング。1台が2つの角番に所属。",
        "- **概念C (min角番)**: rank_from_min のみ。ベースライン。",
        f"- **角番範囲**: 1〜{MAX_KAKUBAN}",
        "- **除外**: 7/7（全台設定6）、台番号2026（鉄台）",
        "",
        "## 効果量サマリー",
        "",
        "| セグメント | 通路角番 ε² | 両端角番 ε² | min角番 ε² | 最強概念 |",
        "| --- | --- | --- | --- | --- |",
    ]

    for label, res in all_results.items():
        eps_a = res["aisle"]["eps2"]
        eps_b = res["dual"]["eps2"]
        eps_c = res["min"]["eps2"]
        vals = {"通路": eps_a, "両端": eps_b, "min": eps_c}
        valid = {k: v for k, v in vals.items() if v is not None}
        if valid:
            best = max(valid, key=valid.get)
            eps_strs = [f"{v:.4f}" if v is not None else "N/A" for v in [eps_a, eps_b, eps_c]]
        else:
            best = "N/A"
            eps_strs = ["N/A", "N/A", "N/A"]
        lines.append(f"| {label} | {eps_strs[0]} | {eps_strs[1]} | {eps_strs[2]} | {best} |")

    lines.append("")

    for label, res in all_results.items():
        lines.append(f"## {label}")
        lines.append("")

        for concept_key, concept_name in [("aisle", "通路角番"), ("dual", "両端角番"), ("min", "min角番")]:
            r = res[concept_key]
            lines.append(f"### {concept_name}")
            lines.append("")
            lines.append(f"**Kruskal-Wallis**: {format_stat(r['H'], r['p'], r['eps2'])}")
            lines.append("")
            lines.append(table_to_markdown(r["agg"], float_digits=2))
            lines.append("")

    return "\n".join(lines)


def main() -> None:
    ensure_report_dir()
    df = prepare_data()

    all_results = {}

    # 全体
    all_results["全体"] = run_experiment_for_segment(df, "全体")

    # セグメント別
    if "seg" in df.columns:
        for seg in ["A", "N"]:
            sub = df[df["seg"] == seg]
            if len(sub) >= 100:
                all_results[f"seg_{seg}"] = run_experiment_for_segment(sub, f"seg_{seg}")

    # フロア×サイド別
    for fs in sorted(df["floor_side"].unique()):
        sub = df[df["floor_side"] == fs]
        if len(sub) >= 100:
            all_results[fs] = run_experiment_for_segment(sub, fs)

    # フロア×サイド×セグメント別
    if "seg" in df.columns:
        for fs in sorted(df["floor_side"].unique()):
            for seg in ["A", "N"]:
                sub = df[(df["floor_side"] == fs) & (df["seg"] == seg)]
                if len(sub) >= 100:
                    label = f"{fs}_{seg}"
                    all_results[label] = run_experiment_for_segment(sub, label)

    report = build_report(all_results)
    report_path = REPORT_DIR / "kamata7_kakuban_concept_experiment_report.md"
    write_text(report_path, report)
    print(f"Report: {report_path}")
    print(f"Segments analyzed: {len(all_results)}")

    print("\n=== 効果量サマリー ===")
    for label, res in all_results.items():
        eps_a = res["aisle"]["eps2"]
        eps_b = res["dual"]["eps2"]
        eps_c = res["min"]["eps2"]
        vals = {"通路": eps_a, "両端": eps_b, "min": eps_c}
        valid = {k: v for k, v in vals.items() if v is not None}
        best = max(valid, key=valid.get) if valid else "N/A"
        print(f"  {label:20s}  通路={eps_a or 0:.4f}  両端={eps_b or 0:.4f}  min={eps_c or 0:.4f}  -> {best}")


if __name__ == "__main__":
    main()
