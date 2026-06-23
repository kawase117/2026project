"""
蒲田一 複合セグメント推薦スクリプト
====================================
分析結果に基づく複合ルール:
  - A型: 全体 + Mid島（12-13台）を別セグメントとして強調
  - N型: Left×非Mid（Small/Large）と Right×Large のみ採用
       （Mid_N=-265, R_N_small/mid は回避）

使い方:
  python eda/kamata1_composite_recommend.py --dd 18
  python eda/kamata1_composite_recommend.py --dd 17 --dd 18
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from eda.cross_hall_pattern_verification import WINDOW_MONTHS, assign_period
from ml.analysis.kamata_corner_mirror_analysis import _read_machine_master_flags

# ---- 定数 ----
DB = PROJECT_ROOT / "db" / "マルハンメガシティ2000-蒲田1.db"
COORD = PROJECT_ROOT / "Heatmap" / "2F_floor_coordinates_kamata1.csv"
OUT_DIR = PROJECT_ROOT / "ml" / "analysis" / "results" / "kamata1_composite_eda"
MIN_GAMES = 1000
MIN_EDA_N = 5   # 小セグメントを拾うため緩め（全期間集計なのでノイズリスク低）
MAX_KAKUBAN = 20


def _size_cat(n: int) -> str:
    if n <= 11:
        return "Small"
    if n <= 13:
        return "Mid"
    return "Large"


def _load_base() -> tuple[pd.DataFrame, pd.DataFrame]:
    with sqlite3.connect(DB) as conn:
        df = pd.read_sql(
            "SELECT date, machine_number, machine_name, diff_coins_normalized, games_normalized"
            " FROM machine_detailed_results",
            conn,
        )
    df["date"] = pd.to_datetime(df["date"], format="%Y%m%d", errors="coerce")
    df = df.dropna(subset=["date"])
    df = df[df["games_normalized"] >= MIN_GAMES].copy()
    df["period"] = assign_period(df["date"], WINDOW_MONTHS)

    coords = pd.read_csv(COORD)
    coords["kakuban"] = coords["rank_from_min"].astype(int)
    coords["side"] = coords["X"].apply(
        lambda x: "L" if x <= 17 else ("R" if x >= 19 else "M")
    )
    sec_size = coords.groupby("section")["machine_number"].transform("count")
    coords["size_cat"] = sec_size.apply(_size_cat)

    return df, coords


def _get_q5_names(df: pd.DataFrame, train_period: int) -> set[str]:
    train = df[df["period"] == train_period]
    agg = train.groupby("machine_name", as_index=False).agg(
        diff_sum=("diff_coins_normalized", "sum")
    )
    agg["q"] = pd.qcut(agg["diff_sum"], 5, labels=False, duplicates="drop") + 1
    return set(agg.loc[agg["q"] == agg["q"].max(), "machine_name"])


def _build_mtype_map(db: Path) -> dict[str, str]:
    mm = _read_machine_master_flags(db)
    return mm.set_index("machine_name_normalized").apply(
        lambda r: "A" if (
            r.get("jug_flag", 0) or r.get("hana_flag", 0) or r.get("bt_flag", 0)
        ) else "N",
        axis=1,
    ).to_dict()


def _compute_eda(seg_df: pd.DataFrame) -> pd.DataFrame:
    """角番 × DD の mean_residual クロステーブルを計算する。"""
    overall = seg_df["diff_coins_normalized"].mean()
    seg_df = seg_df.copy()
    seg_df["residual"] = seg_df["diff_coins_normalized"] - overall
    seg_df["dd"] = seg_df["date"].dt.day

    rows = []
    for (kakuban, dd), grp in seg_df.groupby(["kakuban", "dd"]):
        if len(grp) < MIN_EDA_N:
            continue
        rows.append({
            "kakuban": int(kakuban),
            "dd": int(dd),
            "mean_residual": grp["residual"].mean(),
            "median_residual": grp["residual"].median(),
            "n": len(grp),
        })
    return pd.DataFrame(rows)


# ---- セグメント定義 ----
# (label, mtype_filter, side_filter, size_cat_filter)
SEGMENTS: list[tuple[str, str | None, str | None, list[str] | None]] = [
    ("2F_A",          "A", None, None),
    ("2F_A_Mid",      "A", None, ["Mid"]),
    ("2F_N_L_nonMid", "N", "L",  ["Small", "Large"]),
    ("2F_N_R_Large",  "N", "R",  ["Large"]),
]


def build_eda_tables(
    df: pd.DataFrame,
    coords: pd.DataFrame,
    test_period: int,
    mtype_map: dict[str, str],
) -> dict[str, pd.DataFrame]:
    # EDAは全期間を使う（test_period限定だと小セグメントでセル数が不足する）
    all_df = df.copy()
    all_df["mtype"] = all_df["machine_name"].map(mtype_map).fillna("N")

    merged = all_df.merge(
        coords[["machine_number", "kakuban", "side", "size_cat"]],
        on="machine_number",
        how="left",
    ).dropna(subset=["kakuban"])

    result: dict[str, pd.DataFrame] = {}
    for label, mt, side, sizes in SEGMENTS:
        sub = merged.copy()
        if mt:
            sub = sub[sub["mtype"] == mt]
        if side:
            sub = sub[sub["side"] == side]
        if sizes:
            sub = sub[sub["size_cat"].isin(sizes)]
        eda = _compute_eda(sub)
        result[label] = eda
        print(f"  EDA [{label}]: {len(eda)}セル, 台数={sub['machine_number'].nunique()}")
    return result


def recommend(
    dd_today: int,
    eda_tables: dict[str, pd.DataFrame],
    merged_coords: pd.DataFrame,
) -> pd.DataFrame:
    rows = []
    for label, mt, side, sizes in SEGMENTS:
        eda = eda_tables[label]
        if eda.empty:
            continue
        dd_eda = eda[eda["dd"] == dd_today].sort_values("mean_residual", ascending=False)

        seg = merged_coords.copy()
        if mt:
            seg = seg[seg["mtype"] == mt]
        if side:
            seg = seg[seg["side"] == side]
        if sizes:
            seg = seg[seg["size_cat"].isin(sizes)]
        q5 = seg[seg["is_q5"]]

        for _, row in dd_eda.iterrows():
            kk = int(row["kakuban"])
            mr = float(row["mean_residual"])
            n = int(row["n"])
            hits = q5[q5["kakuban"] == kk]
            if not hits.empty:
                for _, h in hits.iterrows():
                    rows.append({
                        "machine_number": int(h["machine_number"]),
                        "machine_name": h["machine_name"],
                        "seg_key": label,
                        "kakuban": kk,
                        "mean_residual": mr,
                        "n": n,
                        "section": h["section"],
                        "size_cat": h["size_cat"],
                    })

    if not rows:
        return pd.DataFrame()

    all_r = pd.DataFrame(rows)
    best = (
        all_r.sort_values("mean_residual", ascending=False)
        .drop_duplicates("machine_number", keep="first")
        .sort_values("mean_residual", ascending=False)
        .reset_index(drop=True)
    )
    best.index += 1
    best["mean_residual"] = best["mean_residual"].apply(lambda x: f"{x:+.0f}")
    return best


def main(dd_list: list[int]) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    print("=== データ読み込み ===")
    df, coords = _load_base()

    test_start = pd.Timestamp("20260401")
    test_period = int(df[df["date"] >= test_start]["period"].min())
    train_period = test_period - 1
    print(f"train_period={train_period}, test_period={test_period}")

    q5_names = _get_q5_names(df, train_period)
    print(f"Q5機種 ({len(q5_names)}種): {sorted(q5_names)}")

    latest_date = df["date"].max()
    latest_df = (
        df[df["date"] == latest_date][["machine_number", "machine_name"]]
        .drop_duplicates("machine_number")
    )
    print(f"DB最終日: {latest_date.date()}")

    mtype_map = _build_mtype_map(DB)

    merged_coords = (
        coords[["machine_number", "kakuban", "side", "size_cat", "section"]]
        .merge(latest_df, on="machine_number", how="left")
    )
    merged_coords["mtype"] = merged_coords["machine_name"].map(mtype_map).fillna("N")
    merged_coords["is_q5"] = merged_coords["machine_name"].isin(q5_names)

    print("\n=== EDA計算 ===")
    eda_tables = build_eda_tables(df, coords, test_period, mtype_map)

    for label, eda in eda_tables.items():
        path = OUT_DIR / f"kamata1_{label}_composite_eda.csv"
        eda.to_csv(path, index=False)

    for dd in dd_list:
        print(f"\n{'='*65}")
        print(f"DD={dd} 蒲田一（複合セグメント）推薦台 TOP50")
        print(f"{'='*65}")
        top = recommend(dd, eda_tables, merged_coords).head(50)
        if top.empty:
            print("  候補なし")
            continue
        top.columns = ["台番号", "機種名", "セグメント", "角番", "期待残差", "n", "セクション", "島サイズ"]
        print(top.to_csv(sep="\t", index=True, index_label="順位"))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dd", type=int, action="append", default=[])
    args = parser.parse_args()
    dd_list = args.dd if args.dd else [17, 18]
    main(dd_list)
