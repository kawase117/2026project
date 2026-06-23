"""
蒲田七 Q5×角番 立ち回りバックテスト (2026-04-01以降)

角番号の定義 (Instinct: floor-corner-number-distance-rule):
  各セクション内での入口/主通路からの距離ランク。

戦略: DD（日付の日）ごとに最強角番が変わるため、当日のDDに対応した
      最強角番の台を狙う（DD-bin可変角番戦略）。

最強角番の出典:
  Pattern1 (NA) : kamata7_kakuban_dd_cross_eda の kakuban_dd_cross.csv
  Pattern2 (RL) : kamata7_kakuban_rl_eda の kakuban_dd_cross.csv

2パターン:
  Pattern1 (2F3FNA / 2FAなし): 2F_N, 3F_A  ← DD別に最強角番が変動
  Pattern2 (2F3FRL): 2F_L, 2F_R, 3F_L, 3F_R  ← DD別に最強角番が変動
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import numpy as np
import pandas as pd

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from eda.cross_hall_pattern_verification import (
    WINDOW_MONTHS,
    assign_period,
)
from ml.analysis.kamata_corner_mirror_analysis import _read_machine_master_flags

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DB_PATH = PROJECT_ROOT / "db" / "マルハンメガシティ2000-蒲田7.db"
COORDS_2F = PROJECT_ROOT / "Heatmap" / "2F_floor_coordinates_kamata7.csv"
COORDS_3F = PROJECT_ROOT / "Heatmap" / "3F_floor_coordinates_kamata7.csv"

TEST_START = "20260401"
MIN_GAMES = 1000

# 除外セクション
EXCLUDED_2F = [(2187, 2195)]
EXCLUDED_3F = [(3191, 3208), (3209, 3217), (3400, 3401)]

# 角番号の方向が逆転するセクション（rank_from_max を使う）
REVERSED_SECTIONS = {"2330-2351", "3191-3208", "3341-3362"}

# DD別最強角番ルックアップテーブル
# (segment_key) -> {dd: best_kakuban}
# 出典: kamata7_kakuban_dd_cross_eda / kamata7_kakuban_rl_eda の kakuban_dd_cross.csv

DD_BEST_KAKUBAN: dict[str, dict[int, int]] = {
    "2F_N": {
        1:11, 2:16, 3:20, 4:7, 5:20, 6:17, 7:6, 8:20, 9:20,
        10:19, 11:19, 12:20, 13:14, 14:18, 15:20, 16:15, 17:18,
        18:20, 19:20, 20:20, 21:13, 22:6, 23:20, 24:20, 25:20,
        26:19, 27:14, 28:7, 29:7, 30:20, 31:19,
    },
    "3F_A": {
        1:20, 2:7, 3:20, 4:20, 5:18, 6:19, 7:17, 8:10, 9:17,
        10:19, 11:17, 12:16, 13:17, 14:20, 15:5, 16:20, 17:19,
        18:19, 19:8, 20:18, 21:19, 22:18, 23:5, 24:6, 25:17,
        26:8, 27:20, 28:17, 29:19, 30:20, 31:18,
    },
    "2F_L": {
        1:14, 2:7, 3:6, 4:13, 5:5, 6:13, 7:10, 8:14, 9:13,
        10:14, 11:6, 12:14, 13:14, 14:6, 15:14, 16:13, 17:5,
        18:13, 19:4, 20:13, 21:7, 22:8, 23:11, 24:6, 25:11,
        26:14, 27:11, 28:7, 29:6, 30:8, 31:2,
    },
    "2F_R": {
        1:11, 2:6, 3:20, 4:11, 5:20, 6:17, 7:6, 8:20, 9:20,
        10:19, 11:19, 12:9, 13:6, 14:5, 15:20, 16:15, 17:18,
        18:20, 19:20, 20:20, 21:13, 22:12, 23:20, 24:20, 25:20,
        26:19, 27:14, 28:9, 29:7, 30:12, 31:19,
    },
    "3F_L": {
        1:14, 2:6, 3:5, 4:15, 5:6, 6:15, 7:8, 8:10, 9:15,
        10:4, 11:16, 12:16, 13:13, 14:16, 15:15, 16:5, 17:15,
        18:6, 19:8, 20:7, 21:15, 22:2, 23:5, 24:6, 25:16,
        26:6, 27:7, 28:14, 29:7, 30:11, 31:11,
    },
    "3F_R": {
        1:20, 2:8, 3:20, 4:20, 5:18, 6:19, 7:17, 8:5, 9:17,
        10:19, 11:17, 12:10, 13:17, 14:20, 15:6, 16:20, 17:19,
        18:19, 19:8, 20:18, 21:19, 22:11, 23:6, 24:12, 25:7,
        26:8, 27:20, 28:12, 29:4, 30:20, 31:18,
    },
}


def _load_results() -> pd.DataFrame:
    with sqlite3.connect(DB_PATH) as conn:
        df = pd.read_sql_query(
            "SELECT date, machine_number, machine_name, "
            "diff_coins_normalized, games_normalized "
            "FROM machine_detailed_results",
            conn,
        )
    df["date"] = pd.to_datetime(df["date"], format="%Y%m%d", errors="coerce")
    df = df.dropna(subset=["date"])
    df = df[df["games_normalized"] >= MIN_GAMES].copy()
    df["floor"] = df["machine_number"].apply(lambda x: "2F" if x < 3000 else "3F")
    return df


def _load_coords() -> pd.DataFrame:
    c2 = pd.read_csv(COORDS_2F)
    c3 = pd.read_csv(COORDS_3F)
    c2["floor"] = "2F"
    c3["floor"] = "3F"
    coords = pd.concat([c2, c3], ignore_index=True)
    for col in ("X", "Y", "rank_from_min", "rank_from_max", "machine_number"):
        coords[col] = pd.to_numeric(coords[col], errors="coerce")
    return coords


def _is_excluded(mn: int, floor: str) -> bool:
    if floor == "2F":
        return any(lo <= mn <= hi for lo, hi in EXCLUDED_2F)
    return any(lo <= mn <= hi for lo, hi in EXCLUDED_3F)


def _assign_kakuban(coords: pd.DataFrame) -> pd.DataFrame:
    """セクション方向に応じて正しい角番号を選択する。"""
    out = coords.copy()
    out["kakuban"] = out.apply(
        lambda r: r["rank_from_max"] if str(r["section"]) in REVERSED_SECTIONS else r["rank_from_min"],
        axis=1,
    )
    out["kakuban"] = pd.to_numeric(out["kakuban"], errors="coerce")
    return out


def _assign_side(floor: str, x: float) -> str:
    if floor == "2F":
        if x <= 17:
            return "L"
        if x >= 19:
            return "R"
    elif floor == "3F":
        if x <= 17:
            return "L"
        if x >= 23:
            return "R"
    return "E"


def _kakuban_group(k: float) -> str:
    if pd.isna(k):
        return "不明"
    k = int(k)
    if k == 1:
        return "角番1"
    if k <= 4:
        return "角番2-4"
    if k <= 9:
        return "角番5-9★"
    return "角番10+"


def _get_q5_names(df: pd.DataFrame, train_period: int) -> set[str]:
    train = df[df["period"] == train_period].copy()
    agg = train.groupby("machine_name", as_index=False).agg(
        diff_sum=("diff_coins_normalized", "sum")
    )
    if agg.empty:
        return set()
    agg["quintile"] = pd.qcut(agg["diff_sum"], 5, labels=False, duplicates="drop") + 1
    qmax = agg["quintile"].max()
    return set(agg.loc[agg["quintile"] == qmax, "machine_name"])


def _metrics(df: pd.DataFrame, n_days: int) -> dict:
    if df.empty:
        return {
            "n_total": 0,
            "n_days": 0,
            "avg_machines_per_day": 0.0,
            "win_rate": float("nan"),
            "avg_diff": float("nan"),
            "total_diff": float("nan"),
        }
    actual_days = int(df["date"].nunique())
    return {
        "n_total": len(df),
        "n_days": actual_days,
        "avg_machines_per_day": len(df) / n_days,   # 全日数で割る（ゼロ日も分母）
        "win_rate": float((df["diff_coins_normalized"] > 0).mean()),
        "avg_diff": float(df["diff_coins_normalized"].mean()),
        "total_diff": float(df["diff_coins_normalized"].sum()),
    }


def _print_metrics(label: str, d: dict) -> None:
    if d["n_total"] == 0:
        print(f"  {label}: データなし")
        return
    print(
        f"  {label}: "
        f"勝率={d['win_rate']:.1%}  平均差枚={d['avg_diff']:+.0f}  "
        f"合計差枚={d['total_diff']:+,.0f}  "
        f"1日平均={d['avg_machines_per_day']:.1f}台  日数={d['n_days']}"
    )


def _print_kakuban_breakdown(df: pd.DataFrame, n_days: int) -> None:
    """角番グループ別の内訳を表示する。"""
    for grp in ["角番1", "角番2-4", "角番5-9★", "角番10+"]:
        sub = df[df["kakuban_group"] == grp]
        d = _metrics(sub, n_days)
        if d["n_total"] > 0:
            print(
                f"      {grp}: 勝率={d['win_rate']:.1%}  "
                f"平均差枚={d['avg_diff']:+.0f}  1日平均={d['avg_machines_per_day']:.1f}台"
            )


def main() -> None:
    print("=" * 65)
    print("蒲田七 Q5×角番 バックテスト (テスト期間: 2026-04-01以降)")
    print("角番号: 各セクション入口からの距離ランク  ★=5-9が最強帯")
    print("=" * 65)

    df = _load_results()
    df["period"] = assign_period(df["date"], WINDOW_MONTHS)

    period_map = df.groupby("period")["date"].agg(["min", "max"])
    print("\n=== 期間分割 ===")
    print(period_map.to_string())

    test_start_dt = pd.Timestamp(TEST_START)
    test_periods = df[df["date"] >= test_start_dt]["period"].unique()
    if len(test_periods) == 0:
        print("テスト期間のデータなし")
        return
    test_period = int(test_periods.min())
    train_period = test_period - 1

    print(
        f"\n学習期間: period={train_period}  "
        f"({period_map.loc[train_period,'min'].date()} ~ {period_map.loc[train_period,'max'].date()})"
    )
    print(
        f"テスト期間: period={test_period}  "
        f"({period_map.loc[test_period,'min'].date()} ~ {period_map.loc[test_period,'max'].date()})"
    )
    n_days = int((df["period"] == test_period).sum() > 0 and df[df["period"] == test_period]["date"].nunique())
    n_days = int(df[df["period"] == test_period]["date"].nunique())

    q5_names = _get_q5_names(df, train_period)
    print(f"\n=== Q5機種 ({len(q5_names)}種) ===")
    for n in sorted(q5_names):
        print(f"  {n}")

    test_df = df[df["period"] == test_period].copy()
    print(f"\nテストデータ: {len(test_df):,}行  日数={n_days}")

    # 座標マージ
    coords = _load_coords()
    coords = coords[
        ~coords.apply(lambda r: _is_excluded(int(r["machine_number"]), r["floor"]), axis=1)
    ].copy()
    coords = _assign_kakuban(coords)
    coords["side"] = coords.apply(lambda r: _assign_side(r["floor"], r["X"]), axis=1)

    coord_cols = ["machine_number", "X", "Y", "kakuban", "section", "side"]
    test_df = test_df.merge(coords[coord_cols], on="machine_number", how="inner")
    test_df["dd"] = test_df["date"].dt.day

    # A/N判定
    machine_master = _read_machine_master_flags(DB_PATH)
    test_df = test_df.merge(
        machine_master,
        left_on="machine_name",
        right_on="machine_name_normalized",
        how="left",
    )
    for col in ("jug_flag", "hana_flag", "bt_flag"):
        test_df[col] = pd.to_numeric(test_df.get(col, 0), errors="coerce").fillna(0).astype(int)
    is_a = (test_df["jug_flag"] == 1) | (test_df["hana_flag"] == 1)
    is_a_2f = is_a | (test_df["bt_flag"] == 1)
    test_df["machine_type_segment"] = np.where(
        test_df["floor"] == "2F",
        np.where(is_a_2f, "A", "N"),
        np.where(is_a, "A", "N"),
    )

    # Q5フィルタ
    q5_df = test_df[test_df["machine_name"].isin(q5_names)].copy()
    print(f"\nQ5機種（全角番）: {len(q5_df):,}行")

    def _filter_dd_kakuban(base_df: pd.DataFrame, seg_key: str) -> pd.DataFrame:
        """各行のDDに対応した最強角番のみ残す。"""
        lookup = DD_BEST_KAKUBAN[seg_key]
        mask = base_df.apply(lambda r: r["kakuban"] == lookup.get(int(r["dd"])), axis=1)
        return base_df[mask].copy()

    # ─────────────────────────────────────────────────────────────
    print("\n" + "=" * 65)
    print("【Pattern 1: 2F3FNA (2FAは除外) / DD別最強角番】")
    print("=" * 65)

    p1_parts = []
    for seg_key, floor, mtype in [("2F_N", "2F", "N"), ("3F_A", "3F", "A")]:
        seg_all = q5_df[(q5_df["floor"] == floor) & (q5_df["machine_type_segment"] == mtype)]
        seg = _filter_dd_kakuban(seg_all, seg_key)
        label = f"{floor}_{mtype} (DD別角番)"
        _print_metrics(label, _metrics(seg, n_days))
        if not seg.empty:
            machines = seg["machine_name"].value_counts().head(4)
            print(f"    └ 機種: {', '.join(f'{nm}({c})' for nm, c in machines.items())}")
            p1_parts.append(seg)

    print()
    if p1_parts:
        _print_metrics("Pattern1 合計", _metrics(pd.concat(p1_parts, ignore_index=True), n_days))

    # ─────────────────────────────────────────────────────────────
    print("\n" + "=" * 65)
    print("【Pattern 2: 2F3FRL / DD別最強角番】")
    print("=" * 65)

    p2_parts = []
    for seg_key, floor, side in [
        ("2F_L", "2F", "L"), ("2F_R", "2F", "R"),
        ("3F_L", "3F", "L"), ("3F_R", "3F", "R"),
    ]:
        seg_all = q5_df[(q5_df["floor"] == floor) & (q5_df["side"] == side)]
        seg = _filter_dd_kakuban(seg_all, seg_key)
        label = f"{floor}_{side} (DD別角番)"
        _print_metrics(label, _metrics(seg, n_days))
        if not seg.empty:
            machines = seg["machine_name"].value_counts().head(4)
            print(f"    └ 機種: {', '.join(f'{nm}({c})' for nm, c in machines.items())}")
            p2_parts.append(seg)

    print()
    if p2_parts:
        _print_metrics("Pattern2 合計", _metrics(pd.concat(p2_parts, ignore_index=True), n_days))

    # ─────────────────────────────────────────────────────────────
    print("\n" + "=" * 65)
    print("【参考: ベースライン比較】")
    print("=" * 65)
    _print_metrics("全台 (フィルタなし)", _metrics(test_df, n_days))
    _print_metrics("Q5機種のみ (角番なし)", _metrics(q5_df, n_days))
    _print_metrics("Q5×角番1のみ (最弱帯/参考)", _metrics(q5_df[q5_df["kakuban"] == 1], n_days))


if __name__ == "__main__":
    main()
