from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import kruskal, spearmanr

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from eda.core import MIN_GAMES, load_hall_df


PROJECT_ROOT = Path(__file__).resolve().parents[1]
REPORT_DIR = PROJECT_ROOT / "eda" / "reports"
REPORT_PATH = REPORT_DIR / "kamata7_section_relative_digit_report.md"
SUMMARY_PATH = REPORT_DIR / "kamata7_section_relative_digit_summary.csv"

HALL_NAME = "蒲田7"
EXCLUDE_DATE = "20260707"
FLOOR_ORDER = ["2F", "3F"]
SIDE_ORDER = ["L", "R"]
DIGIT_TYPES = ["raw_digit", "pos_from_left", "pos_from_right"]
DIGIT_ORDER = [str(i) for i in range(10)]
SEGMENT_KEYWORDS = ("ジャグラー", "ハナハナ", "クランキー", "ニューパルサー")


def assign_side(floor: str, machine_number: float) -> str:
    x = int(machine_number) % 100
    if floor == "2F":
        return "L" if x <= 17 else ("R" if x >= 19 else "E")
    elif floor == "3F":
        return "L" if x <= 17 else ("R" if x >= 23 else "E")
    return "E"


def _segment_from_name(machine_name: object) -> str:
    text = "" if pd.isna(machine_name) else str(machine_name)
    return "A" if any(keyword in text for keyword in SEGMENT_KEYWORDS) else "N"


def _ensure_floor(machine_number: object) -> str | None:
    if pd.isna(machine_number):
        return None
    mn = int(machine_number)
    if 2000 <= mn <= 2999:
        return "2F"
    if 3000 <= mn <= 3999:
        return "3F"
    return None


def _assign_sections_by_gap(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    out["date"] = out["date"].astype(str)
    out["machine_number"] = pd.to_numeric(out["machine_number"], errors="coerce")
    out = out.dropna(subset=["date", "machine_number"]).copy()
    out["machine_number"] = out["machine_number"].astype(int)

    parts: list[pd.DataFrame] = []
    for date, day_frame in out.sort_values(["date", "machine_number"]).groupby("date", sort=True):
        day = day_frame.sort_values("machine_number").copy()
        numbers = day["machine_number"].to_numpy(dtype=int)
        if len(numbers) == 0:
            continue
        section_break = np.zeros(len(numbers), dtype=int)
        if len(numbers) >= 2:
            section_break[1:] = (np.diff(numbers) >= 2).astype(int)
        day["section_id"] = np.cumsum(section_break) + 1
        day["rank_from_min"] = day.groupby("section_id", sort=True).cumcount() + 1
        day["section_size"] = day.groupby("section_id")["machine_number"].transform("size")
        day["rank_from_max"] = day["section_size"] - day["rank_from_min"] + 1
        parts.append(day)

    if not parts:
        return out.assign(section_id=pd.Series(dtype="Int64"), rank_from_min=pd.Series(dtype="Int64"), rank_from_max=pd.Series(dtype="Int64"), section_size=pd.Series(dtype="Int64"))
    return pd.concat(parts, ignore_index=True)


def _digit_series(frame: pd.DataFrame, digit_type: str) -> pd.Series:
    if digit_type == "raw_digit":
        values = pd.to_numeric(frame["machine_number"], errors="coerce") % 10
    elif digit_type == "pos_from_left":
        values = pd.to_numeric(frame["rank_from_min"], errors="coerce") % 10
    elif digit_type == "pos_from_right":
        values = pd.to_numeric(frame["rank_from_max"], errors="coerce") % 10
    else:
        raise ValueError(f"Unknown digit_type: {digit_type}")
    return values.astype("Int64").astype("string")


def _format_value(value: object, *, digits: int = 1) -> str:
    if pd.isna(value):
        return "NaN"
    if isinstance(value, (np.integer, int)):
        return str(int(value))
    if isinstance(value, (np.floating, float)):
        return f"{float(value):.{digits}f}"
    return str(value)


def _format_table(df: pd.DataFrame, *, float_digits: int = 1) -> str:
    if df.empty:
        return "_No rows_"
    frame = df.copy()
    columns = [str(col) for col in frame.columns]
    header = "| " + " | ".join(columns) + " |"
    separator = "| " + " | ".join(["---"] * len(columns)) + " |"
    rows = []
    for _, row in frame.iterrows():
        values = [_format_value(row[col], digits=float_digits) for col in frame.columns]
        rows.append("| " + " | ".join(values) + " |")
    return "\n".join([header, separator, *rows])


def _prepare_frame(*, exclude_date: str = EXCLUDE_DATE, min_games: int = MIN_GAMES) -> pd.DataFrame:
    print("Loading hall data...")
    df = load_hall_df(HALL_NAME).copy()
    df["date"] = df["date"].astype(str)
    df["machine_number"] = pd.to_numeric(df["machine_number"], errors="coerce")
    df["games"] = pd.to_numeric(df["games"], errors="coerce")
    df["diff"] = pd.to_numeric(df["diff"], errors="coerce")
    df["floor"] = df["machine_number"].map(_ensure_floor)
    df["side"] = df.apply(
        lambda row: assign_side(str(row["floor"]), float(row["machine_number"]))
        if pd.notna(row["machine_number"]) and pd.notna(row["floor"])
        else "E",
        axis=1,
    )
    df = df[df["floor"].isin(FLOOR_ORDER)].copy()

    before = len(df)
    if exclude_date:
        df = df[df["date"] != exclude_date].copy()
        print(f"Excluded {exclude_date}: {before - len(df):,} rows")

    before = len(df)
    df = df[df["games"] >= min_games].copy()
    print(f"Applied min_games >= {min_games}: {before - len(df):,} rows removed")

    df["segment"] = df["machine_name"].map(_segment_from_name)
    df = _assign_sections_by_gap(df)
    df = df[df["side"].isin(SIDE_ORDER) & df["segment"].eq("N")].copy()
    df["raw_digit"] = _digit_series(df, "raw_digit")
    df["pos_from_left"] = _digit_series(df, "pos_from_left")
    df["pos_from_right"] = _digit_series(df, "pos_from_right")
    return df


def _kruskal_result(frame: pd.DataFrame, digit_col: str) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame(columns=["digit", "n", "avg_diff"])

    work = frame.copy()
    work["digit"] = pd.Categorical(work[digit_col].astype(str), categories=DIGIT_ORDER, ordered=True)
    rows: list[dict[str, object]] = []
    for digit in DIGIT_ORDER:
        values = pd.to_numeric(work.loc[work["digit"].eq(digit), "diff"], errors="coerce").dropna().astype(float)
        if len(values) == 0:
            continue
        rows.append({"digit": digit, "n": int(len(values)), "avg_diff": float(values.mean())})
    table = pd.DataFrame(rows)
    if not table.empty:
        table["avg_diff"] = table["avg_diff"].round(1)
        table["digit"] = pd.Categorical(table["digit"], categories=DIGIT_ORDER, ordered=True)
        table = table.sort_values("digit").reset_index(drop=True)
        table["digit"] = table["digit"].astype(str)
    return table


def _kruskal_stats(frame: pd.DataFrame, digit_col: str) -> dict[str, object]:
    table = _kruskal_result(frame, digit_col)
    if table.empty:
        return {"H_stat": np.nan, "p_value": np.nan, "effect_range": np.nan, "n": 0, "table": table}

    groups: list[np.ndarray] = []
    work = frame.copy()
    work["digit"] = work[digit_col].astype(str)
    for digit in DIGIT_ORDER:
        values = pd.to_numeric(work.loc[work["digit"].eq(digit), "diff"], errors="coerce").dropna().astype(float)
        if len(values) > 0:
            groups.append(values.to_numpy(dtype=float))

    if len(groups) < 2:
        return {
            "H_stat": np.nan,
            "p_value": np.nan,
            "effect_range": float(table["avg_diff"].max() - table["avg_diff"].min()) if len(table) >= 2 else np.nan,
            "n": int(table["n"].sum()),
            "table": table,
        }

    try:
        test = kruskal(*groups)
        h_stat = float(test.statistic)
        p_value = float(test.pvalue)
    except ValueError:
        h_stat = np.nan
        p_value = np.nan

    return {
        "H_stat": h_stat,
        "p_value": p_value,
        "effect_range": float(table["avg_diff"].max() - table["avg_diff"].min()) if len(table) >= 2 else np.nan,
        "n": int(table["n"].sum()),
        "table": table,
    }


def _spearman_rank_corr(a_table: pd.DataFrame, b_table: pd.DataFrame) -> float:
    if a_table.empty or b_table.empty:
        return np.nan
    merged = a_table.merge(b_table, on="digit", how="inner", suffixes=("_a", "_b"))
    if len(merged) < 2:
        return np.nan
    return float(spearmanr(merged["avg_diff_a"], merged["avg_diff_b"]).correlation)


def _summary_rows(frame: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for floor in FLOOR_ORDER:
        for side in SIDE_ORDER:
            block = frame[(frame["floor"] == floor) & (frame["side"] == side)].copy()
            for digit_type in DIGIT_TYPES:
                stats = _kruskal_stats(block, digit_type)
                if int(stats["n"]) == 0:
                    print(f"Skipping empty group: floor={floor}, side={side}, digit_type={digit_type}")
                    continue
                rows.append(
                    {
                        "floor": floor,
                        "side": side,
                        "digit_type": digit_type,
                        "H_stat": stats["H_stat"],
                        "p_value": stats["p_value"],
                        "effect_range": stats["effect_range"],
                        "n": stats["n"],
                        "table": stats["table"],
                    }
                )
    return pd.DataFrame(rows)


def _side_table(frame: pd.DataFrame, side: str) -> pd.DataFrame:
    rows = []
    for digit_type in DIGIT_TYPES:
        block = frame[frame["side"] == side].copy()
        stats = _kruskal_stats(block, digit_type)
        if int(stats["n"]) == 0:
            continue
        rows.append(
            {
                "digit_type": digit_type,
                "H_stat": stats["H_stat"],
                "p_value": stats["p_value"],
                "effect_range": stats["effect_range"],
                "n": stats["n"],
            }
        )
    return pd.DataFrame(rows)


def _best_digit_for_side(frame: pd.DataFrame, side: str) -> str | None:
    block = frame[frame["side"] == side].copy()
    if block.empty:
        return None
    rows = []
    for digit_type in DIGIT_TYPES:
        stats = _kruskal_stats(block, digit_type)
        rows.append(
            {
                "digit_type": digit_type,
                "p_value": stats["p_value"],
                "effect_range": stats["effect_range"],
            }
        )
    table = pd.DataFrame(rows).dropna(subset=["p_value"])
    if table.empty:
        return None
    table = table.sort_values(["p_value", "effect_range"], ascending=[True, False])
    return str(table.iloc[0]["digit_type"])


def _best_modified_digit_for_side(frame: pd.DataFrame, side: str) -> str | None:
    block = frame[frame["side"] == side].copy()
    if block.empty:
        return None
    rows = []
    for digit_type in ("pos_from_left", "pos_from_right"):
        stats = _kruskal_stats(block, digit_type)
        rows.append(
            {
                "digit_type": digit_type,
                "p_value": stats["p_value"],
                "effect_range": stats["effect_range"],
            }
        )
    table = pd.DataFrame(rows).dropna(subset=["p_value"])
    if table.empty:
        return None
    table = table.sort_values(["p_value", "effect_range"], ascending=[True, False])
    return str(table.iloc[0]["digit_type"])


def _build_report(summary: pd.DataFrame, frame: pd.DataFrame) -> str:
    lines: list[str] = [
        "# Kamata7 section-relative digit report",
        "",
        f"- Data source: `load_hall_df(\"{HALL_NAME}\")`",
        f"- Filter: `date != {EXCLUDE_DATE}` and `games >= {MIN_GAMES}`",
        "- Scope: segment `N` only",
        "- Digit types: `raw_digit`, `pos_from_left`, `pos_from_right`",
        "",
    ]

    lines.append("## Section 1: 12パターンの比較表")
    lines.append(_format_table(summary[["floor", "side", "digit_type", "H_stat", "p_value", "effect_range", "n"]], float_digits=3))
    lines.append("")

    lines.append("## Section 2: R側の信号回復度")
    r_table = _side_table(frame, "R")
    lines.append(_format_table(r_table, float_digits=3))
    best_r = _best_digit_for_side(frame, "R")
    lines.append(f"- R側の最良digit_type: `{best_r}`")
    lines.append("")

    lines.append("## Section 3: L側の一貫性確認")
    l_raw = _table_for_side(frame, "L", "raw_digit")
    l_left = _table_for_side(frame, "L", "pos_from_left")
    l_right = _table_for_side(frame, "L", "pos_from_right")
    lines.append(_format_table(pd.DataFrame([_corr_row("raw vs pos_from_left", l_raw, l_left), _corr_row("raw vs pos_from_right", l_raw, l_right)]), float_digits=3))
    lines.append("")

    lines.append("## Section 4: R側の修正digitランキング")
    best_r_type = _best_modified_digit_for_side(frame, "R") or "pos_from_left"
    r_rank = _table_for_side(frame, "R", best_r_type)
    lines.append(f"- selected digit_type: `{best_r_type}`")
    lines.append(_format_table(r_rank, float_digits=1))
    lines.append("")

    lines.append("## Section 5: 結論")
    lines.extend([f"- {line}" for line in _build_conclusion(summary, frame)])
    lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _table_for_side(frame: pd.DataFrame, side: str, digit_type: str) -> pd.DataFrame:
    block = frame[frame["side"] == side].copy()
    table = _kruskal_result(block, digit_type)
    return table


def _corr_row(label: str, a_table: pd.DataFrame, b_table: pd.DataFrame) -> dict[str, object]:
    rho = _spearman_rank_corr(a_table, b_table)
    return {"comparison": label, "spearman_rho": rho}


def _build_conclusion(summary: pd.DataFrame, frame: pd.DataFrame) -> list[str]:
    rows: list[str] = []
    r_block = frame[frame["side"] == "R"].copy()
    l_block = frame[frame["side"] == "L"].copy()
    if r_block.empty or l_block.empty:
        return ["必要な側データが不足"]

    r_rows = []
    l_rows = []
    for digit_type in DIGIT_TYPES:
        r_stats = _kruskal_stats(r_block, digit_type)
        l_stats = _kruskal_stats(l_block, digit_type)
        r_rows.append({"digit_type": digit_type, "p_value": r_stats["p_value"], "effect_range": r_stats["effect_range"]})
        l_rows.append({"digit_type": digit_type, "p_value": l_stats["p_value"], "effect_range": l_stats["effect_range"]})
    best_r = pd.DataFrame(r_rows).dropna(subset=["p_value"]).sort_values(["p_value", "effect_range"], ascending=[True, False]).iloc[0]
    best_l = pd.DataFrame(l_rows).dropna(subset=["p_value"]).sort_values(["p_value", "effect_range"], ascending=[True, False]).iloc[0]

    rows.append(f"R側の最良digit_typeは `{best_r['digit_type']}` (p={_format_value(best_r['p_value'], digits=3)})")
    rows.append(f"L側の最良digit_typeは `{best_l['digit_type']}` (p={_format_value(best_l['p_value'], digits=3)})")

    l_raw = _table_for_side(frame, "L", "raw_digit")
    l_left = _table_for_side(frame, "L", "pos_from_left")
    r_raw = _table_for_side(frame, "R", "raw_digit")
    r_left = _table_for_side(frame, "R", "pos_from_left")
    r_right = _table_for_side(frame, "R", "pos_from_right")

    rows.append(f"L側 Spearman(raw, left) = {_format_value(_spearman_rank_corr(l_raw, l_left), digits=3)}")
    rows.append(f"R側 Spearman(raw, left) = {_format_value(_spearman_rank_corr(r_raw, r_left), digits=3)}")
    rows.append(f"R側 Spearman(raw, right) = {_format_value(_spearman_rank_corr(r_raw, r_right), digits=3)}")

    best_modified_r = pd.DataFrame(
        [
            {
                "digit_type": digit_type,
                "p_value": _kruskal_stats(r_block, digit_type)["p_value"],
                "effect_range": _kruskal_stats(r_block, digit_type)["effect_range"],
            }
            for digit_type in ("pos_from_left", "pos_from_right")
        ]
    ).dropna(subset=["p_value"])
    if not best_modified_r.empty:
        best_modified_r = best_modified_r.sort_values(["p_value", "effect_range"], ascending=[True, False]).iloc[0]
    if not best_modified_r.empty and float(best_modified_r["p_value"]) < 0.05:
        rows.append("R側は修正digitで末尾シグナル回復の可能性が高い")
    else:
        rows.append("R側の修正digitによる回復は弱いか、定義依存")

    if pd.notna(best_l["p_value"]) and float(best_l["p_value"]) < 0.05:
        rows.append("L側は raw_digit が依然として主信号である可能性が高い")
    return rows


def run_analysis(*, report_path: Path = REPORT_PATH, summary_path: Path = SUMMARY_PATH, exclude_date: str = EXCLUDE_DATE, min_games: int = MIN_GAMES) -> pd.DataFrame:
    frame = _prepare_frame(exclude_date=exclude_date, min_games=min_games)
    print("Classifying digit types and running Kruskal-Wallis tests...")
    summary = _summary_rows(frame)
    if summary.empty:
        raise ValueError("No analysis rows were produced")

    summary_out = summary.drop(columns=["table"]).copy()
    summary_out["H_stat"] = summary_out["H_stat"].astype(float)
    summary_out["p_value"] = summary_out["p_value"].astype(float)
    summary_out["effect_range"] = summary_out["effect_range"].astype(float)
    summary_out["n"] = summary_out["n"].astype(int)

    report = _build_report(summary, frame)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(report, encoding="utf-8")
    summary_out.to_csv(summary_path, index=False, encoding="utf-8-sig")
    print(f"Wrote report: {report_path}")
    print(f"Wrote summary: {summary_path}")
    return summary_out


def main() -> None:
    parser = argparse.ArgumentParser(description="Kamata7 section-relative digit analysis")
    parser.add_argument("--report-path", type=Path, default=REPORT_PATH)
    parser.add_argument("--summary-path", type=Path, default=SUMMARY_PATH)
    args = parser.parse_args()
    run_analysis(report_path=args.report_path, summary_path=args.summary_path)


if __name__ == "__main__":
    main()
