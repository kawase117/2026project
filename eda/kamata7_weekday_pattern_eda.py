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

from eda.kamata7_verification_common import (
    DOW_ORDER,
    REPORT_DIR,
    attach_floor_side,
    attach_seg,
    cohen_d,
    ensure_report_dir,
    epsilon_from_kruskal,
    mann_whitney,
    prepare_base_frame,
    table_to_markdown,
    write_text,
)
from eda.kamata7_lastdigit_lr_eda import load_coords

REPORT_PATH = REPORT_DIR / "kamata7_weekday_pattern_eda_report.md"


def _prepare_frame() -> pd.DataFrame:
    df = prepare_base_frame(include_floor_side=True)
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
    df["day_of_week"] = pd.Categorical(df["day_of_week"], categories=DOW_ORDER, ordered=True)
    return df.reset_index(drop=True)


def _weekday_stats(df: pd.DataFrame, group_cols: list[str], min_n: int = 10) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for key, grp in df.groupby(group_cols, dropna=False):
        if isinstance(key, tuple):
            row = {col: val for col, val in zip(group_cols, key)}
        else:
            row = {group_cols[0]: key}
        row.update(
            {
                "n": len(grp),
                "avg_diff": round(float(grp["diff"].mean()), 1),
                "plus_rate": round(float(grp["plus"].mean() * 100), 1),
                "hit104_rate": round(float(grp["hit104"].mean() * 100), 1),
            }
        )
        rows.append(row)
    out = pd.DataFrame(rows)
    if not out.empty and "day_of_week" in out.columns:
        out["day_of_week"] = pd.Categorical(out["day_of_week"], categories=DOW_ORDER, ordered=True)
        out = out.sort_values([c for c in ["day_of_week", *group_cols] if c in out.columns]).reset_index(drop=True)
    return out[out["n"] >= min_n].reset_index(drop=True) if not out.empty else out


def _kw_weekday(df: pd.DataFrame) -> pd.DataFrame:
    groups = [g["diff"].to_numpy() for _, g in df.groupby("day_of_week") if len(g) >= 10]
    if len(groups) < 2:
        return pd.DataFrame(columns=["kruskal_stat", "p_value", "epsilon_sq", "n_groups", "total_n"])
    stat, p_value = stats.kruskal(*groups)
    return pd.DataFrame(
        [
            {
                "kruskal_stat": round(float(stat), 3),
                "p_value": round(float(p_value), 6),
                "epsilon_sq": round(epsilon_from_kruskal(float(stat), len(groups), int(sum(len(g) for g in groups))), 6),
                "n_groups": len(groups),
                "total_n": int(sum(len(g) for g in groups)),
            }
        ]
    )


def _weekday_group_kw(df: pd.DataFrame, category_col: str, category_order: list[str], min_n: int = 10) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for dow in DOW_ORDER:
        sub = df[df["day_of_week"] == dow]
        groups = [g["diff"].to_numpy() for _, g in sub.groupby(category_col) if len(g) >= min_n]
        if len(groups) < 2:
            continue
        stat, p_value = stats.kruskal(*groups)
        rows.append(
            {
                "day_of_week": dow,
                "kruskal_stat": round(float(stat), 3),
                "p_value": round(float(p_value), 6),
                "epsilon_sq": round(epsilon_from_kruskal(float(stat), len(groups), int(sum(len(g) for g in groups))), 6),
                "n_groups": len(groups),
                "total_n": int(sum(len(g) for g in groups)),
            }
        )
    out = pd.DataFrame(rows)
    if not out.empty:
        out["day_of_week"] = pd.Categorical(out["day_of_week"], categories=DOW_ORDER, ordered=True)
        out = out.sort_values("day_of_week").reset_index(drop=True)
    return out


def _top_combos(df: pd.DataFrame, cols: list[str], min_n: int = 15, topn: int = 10) -> pd.DataFrame:
    out = (
        df.groupby(cols, dropna=False)
        .agg(n=("diff", "size"), avg_diff=("diff", "mean"), plus_rate=("plus", "mean"), hit104_rate=("hit104", "mean"))
        .reset_index()
    )
    out = out[out["n"] >= min_n].copy()
    if out.empty:
        return out
    out["avg_diff"] = out["avg_diff"].round(0)
    out["plus_rate"] = (out["plus_rate"] * 100).round(1)
    out["hit104_rate"] = (out["hit104_rate"] * 100).round(1)
    return out.sort_values(["avg_diff", "n"], ascending=[False, False]).head(topn).reset_index(drop=True)


def _event_fake_table(df: pd.DataFrame) -> pd.DataFrame:
    full = _weekday_stats(df[df["is_x_day"] == 1], ["day_of_week", "kakuban_rank"], min_n=1)
    non_event = _weekday_stats(df[df["is_x_day"] == 0], ["day_of_week", "kakuban_rank"], min_n=1)
    merged = full.merge(
        non_event[["day_of_week", "kakuban_rank", "avg_diff", "plus_rate", "hit104_rate"]].rename(
            columns={"avg_diff": "avg_diff_non", "plus_rate": "plus_rate_non", "hit104_rate": "hit104_rate_non"}
        ),
        on=["day_of_week", "kakuban_rank"],
        how="outer",
    )
    merged["delta_diff"] = merged["avg_diff"] - merged["avg_diff_non"]
    merged["delta_plus"] = merged["plus_rate"] - merged["plus_rate_non"]
    merged["delta_hit104"] = merged["hit104_rate"] - merged["hit104_rate_non"]
    return merged.sort_values("delta_diff", ascending=False).reset_index(drop=True)


def build_report() -> str:
    df = _prepare_frame()
    weekday_baseline = _weekday_stats(df, ["day_of_week"], min_n=1)
    weekday_kw = _kw_weekday(df)
    weekday_seg = _weekday_stats(df, ["day_of_week", "seg"], min_n=1)
    weekday_kak = _weekday_stats(df, ["day_of_week", "kakuban_rank"], min_n=1)
    weekday_digit = _weekday_stats(df, ["day_of_week", "machine_digit"], min_n=1)
    weekday_digit_n = _weekday_stats(df[df["seg"] == "N"], ["day_of_week", "machine_digit"], min_n=1)
    weekday_kak_kw = _weekday_group_kw(df, "kakuban_rank", ["角1", "角2", "中間", "角N-1", "角N"])
    weekday_digit_kw = _weekday_group_kw(df, "machine_digit", [str(i) for i in range(10)])
    non_event = df[df["is_x_day"] == 0].copy()
    event_fake = _event_fake_table(df)

    weekday_top = _top_combos(df, ["day_of_week", "kakuban_rank"], min_n=20, topn=10)
    weekday_tail_top = _top_combos(df, ["day_of_week", "machine_digit"], min_n=20, topn=10)

    lines: list[str] = []
    lines.append("# 曜日パターンのEDA再検証")
    lines.append("")
    lines.append("## Section 1: 曜日別ベースライン")
    lines.append(table_to_markdown(weekday_baseline))
    lines.append("")
    lines.append(table_to_markdown(weekday_kw))
    lines.append("")
    lines.append("## Section 2: 曜日 × セグメント(A/N) × 角番")
    lines.append(table_to_markdown(weekday_seg))
    lines.append("")
    lines.append(table_to_markdown(weekday_kak))
    lines.append("")
    lines.append(table_to_markdown(weekday_kak_kw))
    lines.append("")
    lines.append(table_to_markdown(weekday_top))
    lines.append("")
    lines.append("## Section 3: 曜日 × 末尾 の交互作用")
    lines.append(table_to_markdown(weekday_digit))
    lines.append("")
    lines.append(table_to_markdown(weekday_digit_n))
    lines.append("")
    lines.append(table_to_markdown(weekday_digit_kw))
    lines.append("")
    lines.append(table_to_markdown(weekday_tail_top))
    lines.append("")
    lines.append("## Section 4: フェイク検出")
    lines.append(table_to_markdown(event_fake.head(20)))
    lines.append("")
    lines.append("### 参考: 非イベント日ベースライン")
    lines.append(table_to_markdown(_weekday_stats(non_event, ["day_of_week"], min_n=1)))
    lines.append("")
    return "\n".join(lines) + "\n"


def main() -> None:
    ensure_report_dir()
    write_text(REPORT_PATH, build_report())
    print(f"[OK] report saved: {REPORT_PATH}")


if __name__ == "__main__":
    main()
