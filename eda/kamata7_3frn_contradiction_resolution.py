from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from eda.kamata7_lastdigit_lr_eda import build_floor_side_map, build_summary, load_coords, load_results, run_kruskal
from eda.kamata7_verification_common import (
    REPORT_DIR,
    attach_seg,
    bootstrap_mean_ci,
    ensure_report_dir,
    epsilon_from_kruskal,
    mann_whitney,
    pct,
    prepare_base_frame,
    resample_stratified_kruskal,
    signed,
    table_to_markdown,
    write_text,
)

REPORT_PATH = REPORT_DIR / "kamata7_3frn_contradiction_resolution_report.md"
TARGET_GROUPS = ["3F_R_A", "3F_R_N", "3F_L_N", "3F_L_A"]


def _prepare_frame() -> pd.DataFrame:
    df = load_results().copy()
    df["date"] = df["date"].astype(str)
    df["last_digit"] = df["last_digit"].astype(str)
    df = df[df["date"].str[4:8] != "0707"].copy()
    df = df[df["machine_number"] != 2026].copy()
    df = df[df["last_digit"].isin([str(i) for i in range(10)])].copy()
    df = attach_seg(df)
    coords = load_coords().copy()
    coords = coords.drop_duplicates(subset=["machine_number"], keep="first")
    coords["kakuban_rank"] = np.where(
        pd.to_numeric(coords["rank_from_min"], errors="coerce") == 1,
        "角1",
        np.where(
            pd.to_numeric(coords["rank_from_min"], errors="coerce") == 2,
            "角2",
            np.where(
                pd.to_numeric(coords["rank_from_max"], errors="coerce") == 1,
                "角N",
                np.where(
                    pd.to_numeric(coords["rank_from_max"], errors="coerce") == 2,
                    "角N-1",
                    "中間",
                ),
            ),
        ),
    )
    df = df.merge(coords[["machine_number", "kakuban_rank"]], on="machine_number", how="inner")
    floor_side = build_floor_side_map()
    df = df.merge(floor_side, on="machine_number", how="inner")
    df["floor"] = df["floor"].astype(str)
    df["side"] = df["side"].astype(str)
    df["floor_side"] = df["floor"] + "_" + df["side"]
    df["group_key"] = df["floor_side"] + "_" + df["seg"]
    return df.reset_index(drop=True)


def _group_tables(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    summary = build_summary(df, ["floor", "side", "seg"])
    if not summary.empty and "mean_diff" in summary.columns:
        summary = summary.rename(columns={"mean_diff": "avg_diff"})
    kruskal_df = run_kruskal(df, ["floor", "side", "seg"])
    if summary.empty:
        return summary, kruskal_df
    summary = summary.copy()
    for idx, row in kruskal_df.iterrows():
        mask = (
            (summary["group_key"] == row["group_key"])
        )
        summary.loc[mask, "epsilon_sq"] = epsilon_from_kruskal(
            float(row["kruskal_stat"]),
            int(row["n_digits"]),
            int(row["total_n"]),
        )
        summary.loc[mask, "kruskal_p"] = float(row["p_value"])
    return summary, kruskal_df


def _effect_rows(df: pd.DataFrame, summary: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for group_key in TARGET_GROUPS:
        sub = df[df["group_key"] == group_key].copy()
        if sub.empty:
            continue
        groups = [g["diff_coins_normalized"].dropna().to_numpy() for _, g in sub.groupby("last_digit") if len(g) >= 10]
        if len(groups) < 2:
            continue
        stat, p_value = stats.kruskal(*groups)
        rows.append(
            {
                "group_key": group_key,
                "n_rows": len(sub),
                "n_digits": len(groups),
                "avg_diff": round(float(sub["diff_coins_normalized"].mean()), 1),
                "positive_rate": round(float((sub["diff_coins_normalized"] > 0).mean() * 100), 1),
                "kruskal_stat": round(float(stat), 3),
                "p_value": round(float(p_value), 6),
                "epsilon_sq": round(epsilon_from_kruskal(float(stat), len(groups), int(sum(len(g) for g in groups))), 6),
            }
        )
    out = pd.DataFrame(rows)
    return out


def _power_estimate(df: pd.DataFrame) -> pd.Series:
    source = df[df["group_key"] == "3F_L_N"].copy()
    power = resample_stratified_kruskal(
        source,
        digit_col="last_digit",
        value_col="diff_coins_normalized",
        target_n=15889,
        n_boot=1000,
        min_n_per_digit=10,
    )
    return pd.Series({"boot_power": power})


def _pairwise_recap(df: pd.DataFrame) -> pd.DataFrame:
    sub = df[df["group_key"].isin(["3F_R_N", "3F_R_A", "3F_L_N"])].copy()
    rows: list[dict[str, object]] = []
    for group_key, grp in sub.groupby("group_key"):
        summary_rows = grp.groupby("last_digit")["diff_coins_normalized"].agg(
            n="size",
            mean_diff="mean",
            median_diff="median",
        ).reset_index()
        rows.extend(
            {
                "group_key": group_key,
                "last_digit": r["last_digit"],
                "n": int(r["n"]),
                "mean_diff": round(float(r["mean_diff"]), 1),
                "median_diff": round(float(r["median_diff"]), 1),
            }
            for _, r in summary_rows.iterrows()
        )
    return pd.DataFrame(rows)


def _kakuban_kruskal(df: pd.DataFrame, scope: str) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    if scope == "3F_R_all":
        sub = df[df["floor_side"] == "3F_R"].copy()
    else:
        sub = df[df["group_key"] == scope].copy()
    if sub.empty:
        return pd.DataFrame(columns=["scope", "n", "n_groups", "kruskal_stat", "p_value", "epsilon_sq"])

    groups = [g["diff_coins_normalized"].dropna().to_numpy() for _, g in sub.groupby("kakuban_rank") if len(g) >= 10]
    if len(groups) < 2:
        return pd.DataFrame(columns=["scope", "n", "n_groups", "kruskal_stat", "p_value", "epsilon_sq"])
    stat, p_value = stats.kruskal(*groups)
    rows.append(
        {
            "scope": scope,
            "n": len(sub),
            "n_groups": len(groups),
            "kruskal_stat": round(float(stat), 3),
            "p_value": round(float(p_value), 6),
            "epsilon_sq": round(epsilon_from_kruskal(float(stat), len(groups), int(sum(len(g) for g in groups))), 6),
        }
    )
    return pd.DataFrame(rows)


def _kakuban_digit_cross(df: pd.DataFrame) -> pd.DataFrame:
    sub = df[df["group_key"] == "3F_R_N"].copy()
    if sub.empty:
        return pd.DataFrame(columns=["kakuban_rank", "last_digit", "n", "avg_diff", "positive_rate"])
    out = (
        sub.groupby(["kakuban_rank", "last_digit"], dropna=False)
        .agg(n=("diff_coins_normalized", "size"), avg_diff=("diff_coins_normalized", "mean"), positive_rate=("diff_coins_normalized", lambda s: (s > 0).mean() * 100))
        .reset_index()
    )
    out = out[out["n"] >= 10].copy()
    if out.empty:
        return out
    out["avg_diff"] = out["avg_diff"].round(1)
    out["positive_rate"] = out["positive_rate"].round(1)
    return out.sort_values(["kakuban_rank", "last_digit"]).reset_index(drop=True)


def build_report() -> str:
    df = _prepare_frame()
    summary, kw = _group_tables(df)
    effects = _effect_rows(df, summary)
    power = _power_estimate(df)
    recap = _pairwise_recap(df)
    kakuban_kw = pd.concat([
        _kakuban_kruskal(df, "3F_R_A"),
        _kakuban_kruskal(df, "3F_R_N"),
        _kakuban_kruskal(df, "3F_R_all"),
    ], ignore_index=True)
    kakuban_cross = _kakuban_digit_cross(df)
    digit_all = df[df["floor_side"] == "3F_R"].copy()
    digit_all_rows = []
    if not digit_all.empty:
        groups = [g["diff_coins_normalized"].dropna().to_numpy() for _, g in digit_all.groupby("last_digit") if len(g) >= 10]
        if len(groups) >= 2:
            stat, p_value = stats.kruskal(*groups)
            digit_all_rows.append(
                {
                    "scope": "3F_R_all_digit",
                    "n": len(digit_all),
                    "n_groups": len(groups),
                    "kruskal_stat": round(float(stat), 3),
                    "p_value": round(float(p_value), 6),
                    "epsilon_sq": round(epsilon_from_kruskal(float(stat), len(groups), int(sum(len(g) for g in groups))), 6),
                }
            )
    digit_all_df = pd.DataFrame(digit_all_rows)

    lines: list[str] = []
    lines.append("# 3F_R_N 結論衝突の解消")
    lines.append("")
    lines.append("## 前処理")
    lines.append(f"- rows={len(df):,}")
    lines.append(f"- dates={df['date'].nunique():,}")
    lines.append(f"- group_keys={', '.join(TARGET_GROUPS)}")
    lines.append("")
    lines.append("## Section 1: 検出力分析")
    lines.append(table_to_markdown(effects.sort_values("group_key").reset_index(drop=True)))
    lines.append("")
    lines.append(
        f"- bootstrap power (3F_L_N -> n=15,889): {power['boot_power']:.3f}  "
        "※ 参照効果量の仮定に依存する推定値"
    )
    lines.append("")
    lines.append("## Section 2: 二重ルール（末尾+角番）の再検証")
    lines.append("### 2a: 末尾別集計")
    lines.append(table_to_markdown(summary[summary["group_key"].isin(TARGET_GROUPS)].sort_values("group_key").reset_index(drop=True)))
    lines.append("")
    lines.append("### 2b: 角番位置別の Kruskal-Wallis")
    lines.append(table_to_markdown(kakuban_kw))
    lines.append("")
    lines.append("### 2c: 角番×末尾の交差表")
    lines.append(table_to_markdown(kakuban_cross))
    lines.append("")
    lines.append("### 2d: 3F_R 全体の末尾別 Kruskal-Wallis")
    lines.append(table_to_markdown(digit_all_df))
    lines.append("")
    lines.append("### 末尾集計の補足")
    lines.append(table_to_markdown(recap.sort_values(["group_key", "last_digit"]).reset_index(drop=True)))
    lines.append("")
    lines.append("## Section 3: 結論と推奨")
    if effects.empty:
        lines.append("- 有効なグループが不足したため、結論保留。")
    else:
        r_n = effects.loc[effects["group_key"] == "3F_R_N"].iloc[0]
        l_n = effects.loc[effects["group_key"] == "3F_L_N"].iloc[0]
        if power["boot_power"] < 0.5:
            conclusion = "(a) 3F_R_N は検出力不足であり、セグメント構造から除外すべきではない（データ蓄積を待つ）"
        else:
            conclusion = "(b) 3F_R_N は少なくとも 3F_L_N 級の実用的効果が確認できず、quickref から除外する現行方針を維持（ただし「シグナルが存在しない」とは断定しない）"
        lines.append(f"- 判定: {conclusion}")
        lines.append(f"- 3F_R_N: p={r_n['p_value']:.6f}, ε²={r_n['epsilon_sq']:.6f}, n={int(r_n['n_rows']):,}")
        lines.append(f"- 3F_L_N: p={l_n['p_value']:.6f}, ε²={l_n['epsilon_sq']:.6f}, n={int(l_n['n_rows']):,}")
        lines.append("- 3F_R_all_digit と 2b/2c の結果で、A機由来か N機寄与かを判定する。")
        lines.append("- 角番集中が見える場合のみ (c) を採用する。")
    return "\n".join(lines) + "\n"


def main() -> None:
    ensure_report_dir()
    report = build_report()
    write_text(REPORT_PATH, report)
    print(f"[OK] report saved: {REPORT_PATH}")


if __name__ == "__main__":
    main()
