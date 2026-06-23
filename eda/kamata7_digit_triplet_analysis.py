from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from eda.core import load_hall_df


PROJECT_ROOT = Path(__file__).resolve().parents[1]
REPORT_DIR = PROJECT_ROOT / "eda" / "reports"
REPORT_PATH = REPORT_DIR / "kamata7_digit_triplet_analysis_report.md"
CSV_PATH = REPORT_DIR / "kamata7_triplet_candidates.csv"
HALL_NAME = "蒲田7"
MIN_DIGIT_N = 5
DIGITS = list(range(10))
TARGET_DOWS = ["月", "火", "水", "木", "金", "土", "日"]


@dataclass(frozen=True)
class AnalysisOutputs:
    raw: pd.DataFrame
    daily_digit: pd.DataFrame
    daily_top3: pd.DataFrame
    overall_top3_summary: pd.DataFrame
    dow_top3_summary: pd.DataFrame
    corr_all: pd.DataFrame
    corr_pairs_all: pd.DataFrame
    corr_test_all: pd.Series
    corr_by_dow: dict[str, dict[str, pd.DataFrame | pd.Series]]
    dd_triplets: pd.DataFrame
    candidates: pd.DataFrame


def is_consecutive_ring(digits: list[int] | tuple[int, ...] | pd.Series) -> bool:
    values = [int(d) % 10 for d in digits]
    if len(values) != len(set(values)):
        return False
    if len(values) < 2:
        return True

    sorted_values = sorted(values)
    if sorted_values[-1] - sorted_values[0] == len(sorted_values) - 1:
        return True

    for offset in range(10):
        rotated = sorted(((d - offset) % 10 for d in values))
        if rotated[-1] - rotated[0] == len(rotated) - 1:
            return True
    return False


def table_to_md(df: pd.DataFrame, float_digits: int = 1) -> str:
    if df.empty:
        return "該当なし"

    def _fmt(value: object) -> str:
        if pd.isna(value):
            return "NaN"
        if isinstance(value, (np.floating, float)):
            return f"{float(value):.{float_digits}f}"
        if isinstance(value, (np.integer, int)) and not isinstance(value, bool):
            return str(int(value))
        if isinstance(value, (np.bool_, bool)):
            return "True" if bool(value) else "False"
        return str(value)

    columns = [str(col) for col in df.columns]
    lines = [
        "| " + " | ".join(columns) + " |",
        "| " + " | ".join(["---"] * len(columns)) + " |",
    ]
    for _, row in df.iterrows():
        lines.append("| " + " | ".join(_fmt(row[col]) for col in df.columns) + " |")
    return "\n".join(lines)


def load_data() -> pd.DataFrame:
    df = load_hall_df(HALL_NAME).copy()
    df["date"] = df["date"].astype(str)
    df = df[df["date"].str[4:8] != "0707"].copy()
    df["machine_digit"] = pd.to_numeric(df["machine_digit"], errors="coerce")
    df["diff"] = pd.to_numeric(df["diff"], errors="coerce")
    df["games"] = pd.to_numeric(df["games"], errors="coerce")
    df = df.dropna(subset=["machine_digit", "diff", "games"]).copy()
    df["machine_digit"] = df["machine_digit"].astype(int)
    df["payout_rate"] = (1 + df["diff"] / (df["games"] * 3)) * 100
    df["hit104"] = (df["payout_rate"] >= 104.0).astype(int)

    if "day_of_week" in df.columns:
        df["dow"] = df["day_of_week"].astype(str)
    else:
        dates = pd.to_datetime(df["date"], format="%Y%m%d", errors="coerce")
        df["dow"] = dates.dt.day_name()

    df["dd"] = pd.to_numeric(df["date"].str[6:8], errors="coerce")
    df["dd_mod10"] = (df["dd"] % 10).astype("Int64")
    df = df.dropna(subset=["dd_mod10"]).copy()
    df["dd_mod10"] = df["dd_mod10"].astype(int)
    return df


def build_digit_group_summary(df: pd.DataFrame, group_cols: list[str]) -> pd.DataFrame:
    summary = (
        df.groupby(group_cols + ["machine_digit"], dropna=False)
        .agg(n=("diff", "size"), avg_diff=("diff", "mean"))
        .reset_index()
    )
    summary.loc[summary["n"] < MIN_DIGIT_N, "avg_diff"] = np.nan
    return summary


def _pick_top3(frame: pd.DataFrame) -> pd.Series:
    valid = frame.dropna(subset=["avg_diff"]).sort_values(
        ["avg_diff", "machine_digit"],
        ascending=[False, True],
    )
    top_digits = [int(d) for d in valid["machine_digit"].head(3).tolist()]
    while len(top_digits) < 3:
        top_digits.append(pd.NA)
    is_consecutive = bool(len([d for d in top_digits if pd.notna(d)]) == 3 and is_consecutive_ring([int(d) for d in top_digits if pd.notna(d)]))
    triplet_label = "-".join(str(int(d)) for d in top_digits if pd.notna(d))
    return pd.Series(
        {
            "top1": top_digits[0],
            "top2": top_digits[1],
            "top3": top_digits[2],
            "is_consecutive": is_consecutive,
            "triplet_label": triplet_label,
        }
    )


def build_condition_triplet_table(df: pd.DataFrame, group_cols: list[str]) -> pd.DataFrame:
    summary = build_digit_group_summary(df, group_cols)
    rows: list[pd.Series] = []
    for key, grp in summary.groupby(group_cols, dropna=False):
        top = _pick_top3(grp)
        if not isinstance(key, tuple):
            key = (key,)
        row = {col: val for col, val in zip(group_cols, key, strict=False)}
        row.update(top.to_dict())
        rows.append(pd.Series(row))
    if not rows:
        return pd.DataFrame(columns=[*group_cols, "top1", "top2", "top3", "is_consecutive", "triplet_label"])
    result = pd.DataFrame(rows)
    result["is_consecutive"] = result["is_consecutive"].map(lambda x: bool(x)).astype(object)
    return result[group_cols + ["top1", "top2", "top3", "is_consecutive", "triplet_label"]].sort_values(group_cols).reset_index(drop=True)


def build_daily_digit_matrix(df: pd.DataFrame) -> pd.DataFrame:
    daily = build_digit_group_summary(df, ["date", "dow", "dd_mod10"])
    pivot = (
        daily.pivot_table(index=["date", "dow", "dd_mod10"], columns="machine_digit", values="avg_diff", aggfunc="first")
        .reindex(columns=DIGITS)
        .reset_index()
        .sort_values(["date", "dow", "dd_mod10"])
        .reset_index(drop=True)
    )
    return pivot


def build_daily_top3_table(daily_digit: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for _, row in daily_digit.iterrows():
        values = {digit: row[digit] for digit in DIGITS if pd.notna(row[digit])}
        ranked = sorted(values.items(), key=lambda item: (-float(item[1]), int(item[0])))
        top_digits = [int(digit) for digit, _ in ranked[:3]]
        if len(top_digits) < 3:
            continue
        rows.append(
            {
                "date": row["date"],
                "dow": row["dow"],
                "dd_mod10": int(row["dd_mod10"]),
                "top1": top_digits[0],
                "top2": top_digits[1],
                "top3": top_digits[2],
                "is_consecutive": bool(is_consecutive_ring(top_digits)),
                "triplet_label": "-".join(str(d) for d in sorted(top_digits)),
            }
        )
    result = pd.DataFrame(rows)
    if not result.empty:
        result["is_consecutive"] = result["is_consecutive"].map(lambda x: bool(x)).astype(object)
    return result


def build_top3_day_summary(top3_table: pd.DataFrame, group_cols: list[str]) -> pd.DataFrame:
    if top3_table.empty:
        return pd.DataFrame(columns=[*group_cols, "n_days", "consecutive_days", "consecutive_rate", "top_triplet", "top_triplet_count", "top_triplet_rate"])

    rows: list[dict[str, object]] = []
    for key, grp in top3_table.groupby(group_cols, dropna=False):
        if not isinstance(key, tuple):
            key = (key,)
        counter = grp["triplet_label"].value_counts()
        top_triplet = counter.index[0]
        top_count = int(counter.iloc[0])
        n_days = int(len(grp))
        consec_days = int(grp["is_consecutive"].sum())
        row = {col: val for col, val in zip(group_cols, key, strict=False)}
        row.update(
            {
                "n_days": n_days,
                "consecutive_days": consec_days,
                "consecutive_rate": consec_days / n_days * 100 if n_days else np.nan,
                "top_triplet": top_triplet,
                "top_triplet_count": top_count,
                "top_triplet_rate": top_count / n_days * 100 if n_days else np.nan,
            }
        )
        rows.append(row)
    return pd.DataFrame(rows).sort_values(group_cols).reset_index(drop=True)


def build_corr_matrix(daily_digit: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.Series]:
    matrix = daily_digit.set_index(["date", "dow", "dd_mod10"])[DIGITS]
    corr = pd.DataFrame(index=DIGITS, columns=DIGITS, dtype=float)
    pair_rows: list[dict[str, object]] = []
    for i in DIGITS:
        for j in DIGITS:
            valid = matrix[[i, j]].dropna()
            corr_value = valid.iloc[:, 0].corr(valid.iloc[:, 1]) if len(valid) >= 2 else np.nan
            corr.loc[i, j] = corr_value
            if i < j:
                pair_rows.append(
                    {
                        "digit_a": i,
                        "digit_b": j,
                        "pair_label": f"{i}-{j}",
                        "n_days": int(len(valid)),
                        "pearson_r": corr_value,
                    }
                )
    for d in DIGITS:
        corr.loc[d, d] = 1.0
    pair_df = pd.DataFrame(pair_rows)
    adjacent_labels = {(i, (i + 1) % 10) if i < (i + 1) % 10 else ((i + 1) % 10, i) for i in DIGITS}
    adjacent = []
    nonadjacent = []
    for _, row in pair_df.iterrows():
        key = (int(row["digit_a"]), int(row["digit_b"]))
        if key in adjacent_labels:
            adjacent.append(row["pearson_r"])
        else:
            nonadjacent.append(row["pearson_r"])
    adjacent_series = pd.Series(adjacent, dtype=float).dropna()
    nonadjacent_series = pd.Series(nonadjacent, dtype=float).dropna()
    if len(adjacent_series) and len(nonadjacent_series):
        stat, p_value = stats.mannwhitneyu(adjacent_series, nonadjacent_series, alternative="greater")
    else:
        stat, p_value = np.nan, np.nan
    test = pd.Series(
        {
            "adjacent_n": int(len(adjacent_series)),
            "nonadjacent_n": int(len(nonadjacent_series)),
            "adjacent_mean": float(adjacent_series.mean()) if len(adjacent_series) else np.nan,
            "nonadjacent_mean": float(nonadjacent_series.mean()) if len(nonadjacent_series) else np.nan,
            "adjacent_median": float(adjacent_series.median()) if len(adjacent_series) else np.nan,
            "nonadjacent_median": float(nonadjacent_series.median()) if len(nonadjacent_series) else np.nan,
            "u_stat": float(stat) if not pd.isna(stat) else np.nan,
            "p_value": float(p_value) if not pd.isna(p_value) else np.nan,
        }
    )
    return corr, pair_df.sort_values(["pair_label"]).reset_index(drop=True), test


def build_corr_by_dow(df: pd.DataFrame, dows: list[str]) -> dict[str, dict[str, pd.DataFrame | pd.Series]]:
    results: dict[str, dict[str, pd.DataFrame | pd.Series]] = {}
    for dow in dows:
        subset = df[df["dow"] == dow].copy()
        if subset.empty:
            results[dow] = {
                "matrix": pd.DataFrame(index=DIGITS, columns=DIGITS, dtype=float),
                "pairs": pd.DataFrame(columns=["digit_a", "digit_b", "pair_label", "n_days", "pearson_r"]),
                "test": pd.Series(dtype=float),
            }
            continue
        matrix, pairs, test = build_corr_matrix(build_daily_digit_matrix(subset))
        results[dow] = {"matrix": matrix, "pairs": pairs, "test": test}
    return results


def build_dd_triplet_frequency(top3_table: pd.DataFrame) -> pd.DataFrame:
    if top3_table.empty:
        return pd.DataFrame(columns=["dd_mod10", "n_days", "top_triplet", "top_triplet_count", "top_triplet_rate", "consecutive_rate"])

    rows: list[dict[str, object]] = []
    for dd_mod10, grp in top3_table.groupby("dd_mod10", dropna=False):
        counter = grp["triplet_label"].value_counts()
        top_triplet = counter.index[0]
        top_count = int(counter.iloc[0])
        n_days = int(len(grp))
        consec_rate = float(grp["is_consecutive"].mean() * 100)
        rows.append(
            {
                "dd_mod10": int(dd_mod10),
                "n_days": n_days,
                "top_triplet": top_triplet,
                "top_triplet_count": top_count,
                "top_triplet_rate": top_count / n_days * 100 if n_days else np.nan,
                "consecutive_rate": consec_rate,
            }
        )
    return pd.DataFrame(rows).sort_values("dd_mod10").reset_index(drop=True)


def build_outputs(df: pd.DataFrame) -> AnalysisOutputs:
    daily_digit = build_daily_digit_matrix(df)
    daily_top3 = build_daily_top3_table(daily_digit)
    overall_top3_summary = build_top3_day_summary(daily_top3, ["dd_mod10"])
    dow_top3_summary = build_top3_day_summary(daily_top3, ["dow"])
    corr_all, corr_pairs_all, corr_test_all = build_corr_matrix(daily_digit)
    corr_by_dow = build_corr_by_dow(df, ["水", "土"])
    dd_triplets = build_dd_triplet_frequency(daily_top3)
    candidates = build_condition_triplet_table(df, ["dow", "dd_mod10"])
    return AnalysisOutputs(
        raw=df,
        daily_digit=daily_digit,
        daily_top3=daily_top3,
        overall_top3_summary=overall_top3_summary,
        dow_top3_summary=dow_top3_summary,
        corr_all=corr_all,
        corr_pairs_all=corr_pairs_all,
        corr_test_all=corr_test_all,
        corr_by_dow=corr_by_dow,
        dd_triplets=dd_triplets,
        candidates=candidates,
    )


def _corr_matrix_to_md(matrix: pd.DataFrame) -> str:
    if matrix.empty:
        return "該当なし"
    display = matrix.reset_index().rename(columns={"index": "digit"})
    return table_to_md(display, float_digits=2)


def build_report(outputs: AnalysisOutputs) -> str:
    df = outputs.raw
    lines: list[str] = [
        "# Kamata7 末尾連動パターン分析",
        "",
        "## データ概要",
        f"- 対象ホール: {HALL_NAME}",
        "- 7/7除外: `date[4:8] != 0707`",
        f"- 行数: {len(df):,}",
        f"- 日数: {df['date'].nunique():,}",
        f"- 平均payout_rate: {df['payout_rate'].mean():.2f}%",
        f"- hit104率: {df['hit104'].mean() * 100:.2f}%",
        "",
        "## Section 1: 日別 末尾Top3の連番率",
        "- 各日で末尾0-9の `avg_diff` を計算し、`n < 5` の末尾は NaN 扱い。",
        "- Top3 がリング連番かを判定。",
        "",
        "### 日数ベースの連番率",
        table_to_md(
            outputs.overall_top3_summary.rename(
                columns={
                    "dd_mod10": "dd_mod10",
                    "n_days": "n_days",
                    "consecutive_days": "consecutive_days",
                    "consecutive_rate": "consecutive_rate",
                    "top_triplet": "top_triplet",
                    "top_triplet_count": "top_triplet_count",
                    "top_triplet_rate": "top_triplet_rate",
                }
            ),
            float_digits=1,
        ),
        "",
        "### 曜日別 連番率",
        table_to_md(outputs.dow_top3_summary, float_digits=1),
        "",
        "## Section 2: 末尾ペア相関マトリクス",
        f"- 隣接 vs 非隣接の比較: adjacent_mean={outputs.corr_test_all.get('adjacent_mean', np.nan):.3f}, nonadjacent_mean={outputs.corr_test_all.get('nonadjacent_mean', np.nan):.3f}, p={outputs.corr_test_all.get('p_value', np.nan):.4f}",
        "",
        "### 10x10 Pearson相関",
        _corr_matrix_to_md(outputs.corr_all),
        "",
        "### ペア相関一覧",
        table_to_md(outputs.corr_pairs_all, float_digits=2),
        "",
        "### 隣接 vs 非隣接の検定",
        table_to_md(outputs.corr_test_all.to_frame().T, float_digits=3),
    ]

    for dow in ["水", "土"]:
        block = outputs.corr_by_dow.get(dow, {})
        matrix = block.get("matrix", pd.DataFrame()) if block else pd.DataFrame()
        pairs = block.get("pairs", pd.DataFrame()) if block else pd.DataFrame()
        test = block.get("test", pd.Series(dtype=float)) if block else pd.Series(dtype=float)
        lines.extend(
            [
                "",
                f"## Section 3: {dow}曜の末尾ペア相関",
                f"- adjacent_mean={test.get('adjacent_mean', np.nan):.3f}, nonadjacent_mean={test.get('nonadjacent_mean', np.nan):.3f}, p={test.get('p_value', np.nan):.4f}",
                "",
                _corr_matrix_to_md(matrix),
                "",
                table_to_md(pairs, float_digits=2),
                "",
                table_to_md(test.to_frame().T, float_digits=3),
            ]
        )

    lines.extend(
        [
            "",
            "## Section 4: dd_mod10別 トリプレット出現頻度",
            table_to_md(outputs.dd_triplets, float_digits=1),
            "",
            "## Section 5: 実戦用 並び候補テーブル",
            "- Top3 が連番を構成する場合に `is_consecutive=True` とする。",
            table_to_md(outputs.candidates, float_digits=1),
        ]
    )
    return "\n".join(lines).strip() + "\n"


def write_outputs(outputs: AnalysisOutputs) -> None:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    outputs.candidates.to_csv(CSV_PATH, index=False, encoding="utf-8-sig")
    REPORT_PATH.write_text(build_report(outputs), encoding="utf-8")


def main() -> None:
    df = load_data()
    outputs = build_outputs(df)
    write_outputs(outputs)
    print(f"Saved: {REPORT_PATH}")
    print(f"Saved: {CSV_PATH}")


if __name__ == "__main__":
    main()
