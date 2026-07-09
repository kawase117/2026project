"""
みとや大森町 台選びフロー推薦スクリプト
=======================================
Phase 10-11b 検証結果に基づくルールベース推薦。

使い方:
  python eda/mitoya_recommend.py --dd 24
  python eda/mitoya_recommend.py --dd 7 --top 30
  python eda/mitoya_recommend.py --dd 15        # 非イベント日
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from eda.mitoya_prompt_common import (
    DB_PATH,
    X_DDS,
    connect_mitoya_db,
    load_mitoya_frame,
    add_debut_phase,
    add_event_category,
)

# ---- セグメント定義 (Phase 10) ----
SEGMENT_SECTIONS = {
    "h_jug": ["641-657", "658-674", "675-691"],
    "h_nonjug": [
        "501-522",
        "523-539",
        "540-556",
        "557-573",
        "574-590",
        "591-607",
        "608-623",
        "624-640",
    ],
    "v_jug": ["712-722", "723-733", "734-744"],
    "v_nonjug": ["692-700", "701-711", "745-755"],
    "mixed_805": ["805-815"],
}
SECTION_TO_SEGMENT = {sec: seg for seg, secs in SEGMENT_SECTIONS.items() for sec in secs}
AVOID_SEGMENTS = {"v_nonjug"}


def _corner_bucket(rank_from_aisle: int) -> str:
    if rank_from_aisle == 1:
        return "corner1"
    if rank_from_aisle <= 4:
        return "corner2-4"
    if rank_from_aisle <= 9:
        return "corner5-9"
    return "corner10+"


def _load_data() -> pd.DataFrame:
    df = load_mitoya_frame(join_layout=True)
    df = df[df["games"] >= 1000].copy()
    df = add_event_category(df)
    df = add_debut_phase(df)
    df["segment"] = df["section"].map(SECTION_TO_SEGMENT).fillna("unknown")
    df["corner_bucket"] = df["rank_from_aisle"].apply(lambda r: _corner_bucket(int(r)) if pd.notna(r) else "unknown")
    return df


def _score_machine(
    row: pd.Series,
    dd: int,
    is_xdds: bool,
    section_baselines: dict[str, float],
) -> float:
    segment = row["segment"]
    corner_bucket = row["corner_bucket"]
    section = row["section"]

    if segment in AVOID_SEGMENTS:
        return -9999.0

    score = 0.0
    score += section_baselines.get(section, 0.0) * 0.1

    if segment == "h_jug":
        # 重みは eda/mitoya_recommend_optimize.py の walk-forward 最適化結果
        # (eda/results/mitoya_optimize_best.json, lift@10_avg=255.4) と同期させている
        corner_bonus = {
            "corner1": 500,
            "corner2-4": 250,
            "corner5-9": 0,
            "corner10+": 0,
        }
        score += corner_bonus.get(corner_bucket, 0)
        if is_xdds:
            score += 100
        section_rank_bonus = {
            "641-657": 80,
            "675-691": 40,
            "658-674": 10,
        }
        score += section_rank_bonus.get(section, 0)

    elif segment == "h_nonjug":
        if is_xdds:
            score += 300
            corner_bonus_xdds = {
                "corner1": 300,
                "corner2-4": 200,
                "corner5-9": 50,
                "corner10+": 0,
            }
            score += corner_bonus_xdds.get(corner_bucket, 0)
        else:
            if corner_bucket == "corner1":
                # 非イベント日のcorner1はavg_diff -160の罠（mitoya_theory.md 2.1節）。
                # 最適化結果でも-100が最良だったため、ボーナスではなくペナルティを課す。
                score -= 100

        if dd == 24 and corner_bucket == "corner1" and section != "523-539":
            score += 200

    elif segment == "v_jug":
        if is_xdds:
            score += 100
        section_rank_bonus = {
            "723-733": 20,
            "734-744": 10,
            "712-722": 5,
        }
        score += section_rank_bonus.get(section, 0)

    elif segment == "mixed_805":
        debut = row.get("debut_phase", "unknown")
        if is_xdds and debut == "debut":
            score += 300
        elif is_xdds and debut == "growth":
            score -= 100

    return score


def recommend(dd: int, top_n: int = 50) -> pd.DataFrame:
    df = _load_data()
    is_xdds = dd in X_DDS

    section_baselines = dict(df.groupby("section")["diff"].mean())

    latest_date = df["date"].max()
    latest = df[df["date"] == latest_date].copy()
    if latest.empty:
        print(f"最新日 {latest_date} にデータがありません")
        return pd.DataFrame()

    latest["score"] = latest.apply(
        lambda row: _score_machine(row, dd, is_xdds, section_baselines),
        axis=1,
    )

    result = (
        latest[latest["segment"] != "v_nonjug"].sort_values("score", ascending=False).head(top_n).reset_index(drop=True)
    )
    result.index += 1

    cols = [
        "machine_number",
        "machine_name",
        "section",
        "segment",
        "rank_from_aisle",
        "corner_bucket",
        "debut_phase",
        "score",
    ]
    return result[[c for c in cols if c in result.columns]]


def _format_factors(row: pd.Series, dd: int, is_xdds: bool) -> str:
    factors = []
    seg = row["segment"]
    cb = row["corner_bucket"]

    if seg == "h_jug" and cb == "corner1":
        factors.append("h_jug角番1(+463)")
    elif seg == "h_jug" and cb == "corner2-4":
        factors.append("h_jug角番2-4(+150)")
    if seg == "h_nonjug" and is_xdds and cb == "corner1":
        factors.append("h_nonjug角番1×X_DDS(+639)")
    if seg == "h_nonjug" and dd == 24 and cb == "corner1" and row["section"] != "523-539":
        factors.append("DD24特殊(+1147)")
    if seg == "h_nonjug" and not is_xdds and cb == "corner1":
        factors.append("角番1罠(-160)")
    if seg == "mixed_805" and is_xdds and row.get("debut_phase") == "debut":
        factors.append("debut×X_DDS(+409)")
    if is_xdds:
        factors.append("X_DDS日")

    return " / ".join(factors) if factors else ""


def main():
    parser = argparse.ArgumentParser(description="みとや大森町 台選び推薦")
    parser.add_argument("--dd", type=int, required=True, help="日付の日 (1-31)")
    parser.add_argument("--top", type=int, default=50, help="推薦台数 (default: 50)")
    parser.add_argument("--md", action="store_true", help="Markdown テーブルで出力")
    args = parser.parse_args()

    is_xdds = args.dd in X_DDS
    event_label = "X_DDS日" if is_xdds else "非イベント日"
    print(f"\n{'=' * 60}")
    print(f"  みとや大森町 台選び推薦 - DD={args.dd} ({event_label})")
    print(f"{'=' * 60}\n")

    if args.dd == 24:
        print("DD=24 特殊日: h_nonjug corner1 に boost (+1147, 523-539除外)")
    if not is_xdds:
        print("非イベント日: h_jug corner1 のみ有効。h_nonjug corner1 は罠。")
    print()

    result = recommend(args.dd, args.top)
    if result.empty:
        print("推薦台なし")
        return

    result["factors"] = result.apply(
        lambda row: _format_factors(row, args.dd, is_xdds),
        axis=1,
    )

    if args.md:
        header = "| # | 台番号 | 機種名 | section | segment | 角番 | corner | debut | score | factors |"
        sep = "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |"
        print(header)
        print(sep)
        for idx, row in result.iterrows():
            print(
                f"| {idx} | {row['machine_number']} | {row['machine_name']} "
                f"| {row['section']} | {row['segment']} "
                f"| {row.get('rank_from_aisle', '')} | {row['corner_bucket']} "
                f"| {row.get('debut_phase', '')} | {row['score']:.0f} "
                f"| {row['factors']} |"
            )
    else:
        display_cols = [
            "machine_number",
            "machine_name",
            "section",
            "segment",
            "rank_from_aisle",
            "corner_bucket",
            "score",
            "factors",
        ]
        display_cols = [c for c in display_cols if c in result.columns]
        pd.set_option("display.max_columns", 20)
        pd.set_option("display.width", 160)
        pd.set_option("display.max_colwidth", 25)
        print(result[display_cols].to_string())

    print(f"\n--- 推薦台数: {len(result)} / セグメント分布 ---")
    print(result["segment"].value_counts().to_string())
    print()


if __name__ == "__main__":
    main()
