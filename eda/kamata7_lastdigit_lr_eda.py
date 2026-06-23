from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pandas as pd
from scipy import stats

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DB_PATH = PROJECT_ROOT / "db" / "マルハンメガシティ2000-蒲田7.db"
COORDS_2F = PROJECT_ROOT / "Heatmap" / "2F_floor_coordinates_kamata7.csv"
COORDS_3F = PROJECT_ROOT / "Heatmap" / "3F_floor_coordinates_kamata7.csv"

MIN_GAMES = 1000
A_KEYWORDS = ["ジャグラー", "ハナハナ", "クランキー", "ニューパルサー"]
DIGITS = [str(i) for i in range(10)]

EXCLUDED_2F_SECTION_MIN = {2187}
EXCLUDED_3F_SECTION_MIN = {3191, 3209, 3400}


def assign_side(floor: str, x: float) -> str:
    if floor == "2F":
        return "L" if x <= 17 else ("R" if x >= 19 else "E")
    if floor == "3F":
        return "L" if x <= 17 else ("R" if x >= 23 else "E")
    return "E"


def classify_seg(name: str) -> str:
    return "A" if any(keyword in str(name) for keyword in A_KEYWORDS) else "N"


def load_coords() -> pd.DataFrame:
    c2 = pd.read_csv(COORDS_2F)
    c3 = pd.read_csv(COORDS_3F)
    coords = pd.concat([c2, c3], ignore_index=True)

    for col in ["machine_number", "X", "Y", "display_x", "display_y", "section_min", "section_max", "rank_from_min", "rank_from_max"]:
        coords[col] = pd.to_numeric(coords[col], errors="coerce")

    coords["floor"] = coords["floor"].astype(str)
    coords["section"] = coords["section"].astype(str)
    return coords


def build_floor_side_map() -> pd.DataFrame:
    coords = load_coords()

    sec_x_span = coords.groupby("section")["X"].nunique()
    vertical_sections = sec_x_span[sec_x_span == 1].index
    coords = coords[~coords["section"].isin(vertical_sections)].copy()

    coords = coords[~(
        (coords["floor"] == "2F") & (coords["section_min"].isin(EXCLUDED_2F_SECTION_MIN))
    )].copy()
    coords = coords[~(
        (coords["floor"] == "3F") & (coords["section_min"].isin(EXCLUDED_3F_SECTION_MIN))
    )].copy()

    coords["side"] = coords.apply(lambda r: assign_side(str(r["floor"]), float(r["X"])), axis=1)
    coords = coords[coords["side"] != "E"].copy()

    floor_side_map = (
        coords[["machine_number", "floor", "side"]]
        .dropna(subset=["machine_number", "floor", "side"])
        .drop_duplicates(subset=["machine_number"])
        .copy()
    )
    floor_side_map["machine_number"] = floor_side_map["machine_number"].astype(int)
    return floor_side_map


def load_results() -> pd.DataFrame:
    with sqlite3.connect(DB_PATH) as conn:
        df = pd.read_sql_query(
            """
            SELECT date, machine_number, machine_name,
                   last_digit, games_normalized, diff_coins_normalized
            FROM machine_detailed_results
            WHERE games_normalized >= ?
            """,
            conn,
            params=(MIN_GAMES,),
        )

    df["machine_number"] = pd.to_numeric(df["machine_number"], errors="coerce")
    df["last_digit"] = df["last_digit"].astype(str)
    df["machine_name"] = df["machine_name"].astype(str)
    df["seg"] = df["machine_name"].map(classify_seg)
    return df.dropna(subset=["machine_number"]).copy()


def build_summary(df: pd.DataFrame, group_cols: list[str]) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for key, grp in df.groupby(group_cols, dropna=False):
        if grp.empty:
            continue
        if isinstance(key, tuple):
            group_key = "_".join(str(v) for v in key)
        else:
            group_key = str(key)

        summary = grp.groupby("last_digit")["diff_coins_normalized"].agg(
            n="size",
            mean_diff="mean",
            median_diff="median",
            q75_diff=lambda s: s.quantile(0.75),
            positive_rate=lambda s: (s > 0).mean() * 100,
        ).reset_index()
        summary["group_key"] = group_key
        rows.append(summary)

    if not rows:
        return pd.DataFrame(columns=["group_key", "last_digit", "n", "mean_diff", "median_diff", "q75_diff", "positive_rate"])

    summary_df = pd.concat(rows, ignore_index=True)
    summary_df["last_digit_order"] = pd.Categorical(summary_df["last_digit"], categories=DIGITS, ordered=True)
    summary_df = summary_df.sort_values(["group_key", "last_digit_order"]).drop(columns=["last_digit_order"])
    return summary_df[["group_key", "last_digit", "n", "mean_diff", "median_diff", "q75_diff", "positive_rate"]]


def run_kruskal(df: pd.DataFrame, group_cols: list[str]) -> pd.DataFrame:
    results: list[dict[str, object]] = []
    for key, grp in df.groupby(group_cols, dropna=False):
        if grp.empty:
            continue
        if isinstance(key, tuple):
            group_key = "_".join(str(v) for v in key)
        else:
            group_key = str(key)

        digit_groups = [
            g["diff_coins_normalized"].values
            for _, g in grp.groupby("last_digit")
            if len(g) >= 10
        ]
        if len(digit_groups) < 2:
            continue

        stat, p_value = stats.kruskal(*digit_groups)
        results.append(
            {
                "group_key": group_key,
                "kruskal_stat": round(float(stat), 3),
                "p_value": round(float(p_value), 6),
                "n_digits": len(digit_groups),
                "total_n": int(sum(len(g) for g in digit_groups)),
            }
        )

    if not results:
        return pd.DataFrame(columns=["group_key", "kruskal_stat", "p_value", "n_digits", "total_n"])

    return pd.DataFrame(results).sort_values(["p_value", "group_key"]).reset_index(drop=True)


def print_summary_table(title: str, df: pd.DataFrame) -> None:
    print(f"\n=== {title} ===")
    if df.empty:
        print("データなし")
        return
    print(df.to_string(index=False))


def print_significant_digit_breakdown(summary: pd.DataFrame, kw_df: pd.DataFrame) -> None:
    sig_keys = kw_df.loc[kw_df["p_value"] < 0.05, "group_key"].tolist()
    print("\n=== 有意グループの末尾内訳 ===")
    if not sig_keys:
        print("該当なし")
        return

    for key in sig_keys:
        sub = summary[summary["group_key"] == key].sort_values(["mean_diff", "last_digit"], ascending=[False, True])
        if sub.empty:
            continue
        best = sub.iloc[0]
        worst = sub.iloc[-1]
        print(f"[{key}]")
        print(f"  best  末尾={best['last_digit']}  mean={best['mean_diff']:+.0f}  n={int(best['n'])}")
        print(f"  worst 末尾={worst['last_digit']}  mean={worst['mean_diff']:+.0f}  n={int(worst['n'])}")
        print(sub.to_string(index=False))


def build_baseline_comparison(lr_kw: pd.DataFrame, baseline_kw: pd.DataFrame) -> pd.DataFrame:
    lr = lr_kw.copy()
    bl = baseline_kw.copy()
    if lr.empty and bl.empty:
        return pd.DataFrame(columns=["floor_seg", "best_group_key", "kw_stat_lr_split", "kw_p_lr_split", "kw_stat_baseline", "kw_p_baseline", "delta_p"])

    lr["floor_seg"] = lr["group_key"].str.replace(r"_[LR]_", "_", regex=True)
    bl["floor_seg"] = bl["group_key"]

    if not lr.empty:
        lr = lr.loc[lr.groupby("floor_seg")["p_value"].idxmin()].copy()
        lr = lr.rename(
            columns={
                "group_key": "best_group_key",
                "kruskal_stat": "kw_stat_lr_split",
                "p_value": "kw_p_lr_split",
            }
        )

    if not bl.empty:
        bl = bl.rename(
            columns={
                "kruskal_stat": "kw_stat_baseline",
                "p_value": "kw_p_baseline",
            }
        )

    merged = lr.merge(
        bl[["floor_seg", "kw_stat_baseline", "kw_p_baseline"]],
        on="floor_seg",
        how="outer",
    )
    merged["delta_p"] = merged["kw_p_baseline"] - merged["kw_p_lr_split"]
    cols = ["floor_seg", "best_group_key", "kw_stat_lr_split", "kw_p_lr_split", "kw_stat_baseline", "kw_p_baseline", "delta_p"]
    for col in cols:
        if col not in merged.columns:
            merged[col] = pd.NA
    return merged[cols].sort_values(["delta_p", "floor_seg"], ascending=[False, True]).reset_index(drop=True)


def main() -> None:
    df = load_results()
    floor_side_map = build_floor_side_map()

    df = df.merge(floor_side_map, on="machine_number", how="inner")
    df = df.dropna(subset=["floor", "side"])
    df["floor_seg"] = df["floor"].astype(str) + "_" + df["seg"].astype(str)
    df["group_key"] = df["floor"].astype(str) + "_" + df["side"].astype(str) + "_" + df["seg"].astype(str)
    df = df[df["last_digit"].isin(DIGITS)].copy()

    summary_lr = build_summary(df, ["floor", "side", "seg"])
    kw_lr = run_kruskal(df, ["floor", "side", "seg"])
    kw_baseline = run_kruskal(df, ["floor", "seg"])

    print_summary_table("各 group_key × last_digit 基本集計", summary_lr)
    print_summary_table("Kruskal-Wallis (L/R 分割あり)", kw_lr)
    print_significant_digit_breakdown(summary_lr, kw_lr)

    baseline_compare = build_baseline_comparison(kw_lr, kw_baseline)
    print_summary_table("ベースラインとの比較", baseline_compare)


if __name__ == "__main__":
    main()
