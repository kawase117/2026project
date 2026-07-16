"""RB probability verification for kakuban effects in Kamata7/Kamata1 Jugglers.

The primary RB metric is a pooled rate: sum(rb_count) / sum(games_normalized).
This avoids day-level simple-average distortion when game counts differ.
"""

from __future__ import annotations

import argparse
import ast
import sqlite3
import sys
import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd
from scipy.stats import kruskal, mannwhitneyu, spearmanr

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if __package__ in {None, ""}:
    sys.path.insert(0, str(PROJECT_ROOT))

from eda.core import DB_DIR, HALL_DBS, HALL_EVENT_DIGITS, MIN_GAMES as CORE_MIN_GAMES, _epsilon_squared
from eda.kamata7_verification_common import KAKUBAN_ORDER, compute_payout_rate
from eda.kamata7_lastdigit_lr_eda import build_floor_side_map, classify_seg

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

warnings.filterwarnings("ignore")

DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "eda" / "results" / "kakuban_rb_verification"
TARGET_SOURCE = PROJECT_ROOT / "eda" / "rb_probability_analysis.py"
SUPPORTED_HALLS = ["蒲田7", "蒲田1"]
SENSITIVITY_MIN_GAMES = [CORE_MIN_GAMES, 2000]
REMOVED_KAMATA1_MACHINES = set(range(2331, 2341))
REMOVED_KAMATA1_DATE = "20250817"

DD_BINS = [
    ("DD1-6", 1, 6),
    ("DD7-12", 7, 12),
    ("DD13-18", 13, 18),
    ("DD19-24", 19, 24),
    ("DD25-31", 25, 31),
]
DD_BIN_ORDER = [item[0] for item in DD_BINS]

KAMATA7_COMPARE_SEGMENTS = ["3F_R_A", "3F_L_A", "3F_L_N"]
KAMATA7_THEORY_BUCKET = {
    ("3F_R_A", "DD1-6"): "中間",
    ("3F_R_A", "DD7-12"): "中間",
    ("3F_R_A", "DD13-18"): "中間",
    ("3F_R_A", "DD19-24"): "中間",
    ("3F_R_A", "DD25-31"): "中間",
    ("3F_L_A", "DD1-6"): "中間",
    ("3F_L_A", "DD7-12"): "中間",
    ("3F_L_A", "DD13-18"): "中間",
    ("3F_L_A", "DD19-24"): "中間",
    ("3F_L_A", "DD25-31"): "中間",
    ("3F_L_N", "DD1-6"): "中間",
    ("3F_L_N", "DD7-12"): "中間",
    ("3F_L_N", "DD13-18"): "中間",
    ("3F_L_N", "DD19-24"): "中間",
    ("3F_L_N", "DD25-31"): "中間",
}


@dataclass(frozen=True)
class HallDiagnostics:
    hall: str
    db_path: Path
    db_size_bytes: int
    min_date: str
    max_date: str
    raw_rows: int
    layout_rows: int
    juggler_rows_min400: int
    juggler_machines_min400: int
    kamata1_removed_rows_all_time: int | None = None
    kamata1_removed_rows_on_or_after_removed_date: int | None = None
    kamata1_removed_rows_after_removed_date: int | None = None
    kamata1_removed_max_date: str | None = None


def _eval_ast_number(node: ast.AST) -> object:
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Dict):
        return {_eval_ast_number(k): _eval_ast_number(v) for k, v in zip(node.keys, node.values)}
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
        left = _eval_ast_number(node.left)
        right = _eval_ast_number(node.right)
        return float(left) / float(right)
    raise ValueError(f"unsupported TARGETS node: {ast.dump(node)}")


def load_juggler_patterns_from_targets() -> list[str]:
    """Read TARGETS from rb_probability_analysis.py without importing its top-level runner."""
    tree = ast.parse(TARGET_SOURCE.read_text(encoding="utf-8"))
    targets_node = None
    for node in tree.body:
        if isinstance(node, ast.Assign):
            names = [target.id for target in node.targets if isinstance(target, ast.Name)]
            if "TARGETS" in names:
                targets_node = node.value
                break
    if targets_node is None:
        raise RuntimeError(f"TARGETS not found in {TARGET_SOURCE}")
    targets = _eval_ast_number(targets_node)
    requested = [
        "アイムジャグラーEX-TP",
        "マイジャグラーV",
        "ファンキージャグラー2",
        "ゴーゴージャグラー3",
        "ミスタージャグラー",
        "ジャグラーガールズ",
        "ハッピージャグラーVIII",
    ]
    return [str(targets[label]["pattern"]) for label in requested]


def hall_db_path(hall: str) -> Path:
    if hall not in HALL_DBS:
        raise ValueError(f"unknown hall: {hall}")
    path = DB_DIR / HALL_DBS[hall]
    if not path.exists() or path.stat().st_size == 0:
        raise FileNotFoundError(f"real DB not found or empty: {path}")
    return path


def inspect_hall(hall: str, patterns: list[str]) -> HallDiagnostics:
    db_path = hall_db_path(hall)
    con = sqlite3.connect(db_path)
    try:
        tables = {row[0] for row in con.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        required = {"machine_detailed_results", "machine_layout"}
        missing = required - tables
        if missing:
            raise RuntimeError(f"{hall}: missing tables {sorted(missing)} in {db_path}")

        min_date, max_date, raw_rows = con.execute(
            "SELECT MIN(date), MAX(date), COUNT(*) FROM machine_detailed_results"
        ).fetchone()
        layout_rows = con.execute("SELECT COUNT(*) FROM machine_layout").fetchone()[0]
        where = " OR ".join(["machine_name LIKE ?"] * len(patterns))
        params = [f"%{pat}%" for pat in patterns]
        juggler_rows, juggler_machines = con.execute(
            f"""
            SELECT COUNT(*), COUNT(DISTINCT machine_number)
            FROM machine_detailed_results
            WHERE games_normalized >= ?
              AND rb_probability_decimal IS NOT NULL
              AND rb_probability_decimal > 0
              AND ({where})
            """,
            [CORE_MIN_GAMES, *params],
        ).fetchone()

        extra: dict[str, object] = {}
        if hall == "蒲田1":
            extra["kamata1_removed_rows_all_time"], _, extra["kamata1_removed_max_date"] = con.execute(
                """
                SELECT COUNT(*), MIN(date), MAX(date)
                FROM machine_detailed_results
                WHERE CAST(machine_number AS INTEGER) BETWEEN 2331 AND 2340
                """
            ).fetchone()
            extra["kamata1_removed_rows_on_or_after_removed_date"] = con.execute(
                """
                SELECT COUNT(*)
                FROM machine_detailed_results
                WHERE CAST(machine_number AS INTEGER) BETWEEN 2331 AND 2340
                  AND date >= ?
                """,
                (REMOVED_KAMATA1_DATE,),
            ).fetchone()[0]
            extra["kamata1_removed_rows_after_removed_date"] = con.execute(
                """
                SELECT COUNT(*)
                FROM machine_detailed_results
                WHERE CAST(machine_number AS INTEGER) BETWEEN 2331 AND 2340
                  AND date > ?
                """,
                (REMOVED_KAMATA1_DATE,),
            ).fetchone()[0]
    finally:
        con.close()

    return HallDiagnostics(
        hall=hall,
        db_path=db_path,
        db_size_bytes=int(db_path.stat().st_size),
        min_date=str(min_date),
        max_date=str(max_date),
        raw_rows=int(raw_rows),
        layout_rows=int(layout_rows),
        juggler_rows_min400=int(juggler_rows),
        juggler_machines_min400=int(juggler_machines),
        **extra,
    )


def load_base_frame(
    hall: str,
    patterns: list[str],
    *,
    min_games: int,
    exclude_removed_kamata1_all_time: bool = False,
) -> pd.DataFrame:
    db_path = hall_db_path(hall)
    where = " OR ".join(["m.machine_name LIKE ?"] * len(patterns))
    params: list[object] = [min_games, *[f"%{pat}%" for pat in patterns]]
    con = sqlite3.connect(db_path)
    try:
        frame = pd.read_sql_query(
            f"""
            SELECT
                m.date,
                m.machine_name,
                CAST(m.machine_number AS INTEGER) AS machine_number,
                CAST(m.games_normalized AS REAL) AS games,
                CAST(m.diff_coins_normalized AS REAL) AS diff,
                CAST(m.rb_count AS REAL) AS rb_count,
                CAST(m.rb_probability_decimal AS REAL) AS rb_prob
            FROM machine_detailed_results m
            WHERE m.games_normalized >= ?
              AND m.rb_probability_decimal IS NOT NULL
              AND m.rb_probability_decimal > 0
              AND ({where})
            """,
            con,
            params=params,
        )
        layout = pd.read_sql_query(
            """
            SELECT
                CAST(machine_number AS INTEGER) AS machine_number,
                section,
                CAST(section_min AS INTEGER) AS section_min,
                CAST(section_max AS INTEGER) AS section_max,
                CAST(rank_from_min AS REAL) AS rank_from_min,
                CAST(rank_from_max AS REAL) AS rank_from_max
            FROM machine_layout
            """,
            con,
        )
    finally:
        con.close()

    if frame.empty:
        return frame

    frame["date"] = frame["date"].astype(str)
    frame = frame.merge(layout.drop_duplicates("machine_number"), on="machine_number", how="inner")
    frame = frame.dropna(subset=["games", "diff", "rb_count", "rb_prob", "rank_from_min", "rank_from_max"]).copy()
    frame = frame[frame["games"] > 0].copy()
    frame["payout_rate"] = compute_payout_rate(frame)
    frame["dd"] = frame["date"].str[6:8].astype(int)
    frame["dd_bin"] = pd.Categorical(frame["dd"].map(dd_bin_label), categories=DD_BIN_ORDER, ordered=True)
    frame["kakuban_bucket"] = pd.Categorical(
        frame.apply(assign_kakuban_bucket, axis=1), categories=KAKUBAN_ORDER, ordered=True
    )
    frame["kakuban_distance"] = frame[["rank_from_min", "rank_from_max"]].min(axis=1)
    frame["hall"] = hall
    frame["min_games"] = int(min_games)
    frame["is_event_day"] = is_event_day(hall, frame["date"], frame["dd"])

    if hall == "蒲田7":
        before = len(frame)
        frame = frame[frame["date"].str[4:8] != "0707"].copy()
        frame = frame[frame["machine_number"] != 2026].copy()
        frame["exclusion_note"] = f"蒲田7: 0707 and machine_number=2026 excluded; removed_rows={before - len(frame)}"
        floor_side = build_floor_side_map()
        frame = frame.merge(floor_side, on="machine_number", how="inner")
        frame["seg"] = frame["machine_name"].map(classify_seg)
        frame["analysis_segment"] = (
            frame["floor"].astype(str) + "_" + frame["side"].astype(str) + "_" + frame["seg"].astype(str)
        )
    elif hall == "蒲田1":
        if exclude_removed_kamata1_all_time:
            frame = frame[~frame["machine_number"].isin(REMOVED_KAMATA1_MACHINES)].copy()
            variant = "removed_2331_2340_all_time"
        else:
            variant = "natural_removed_after_20250817"
        frame["exclusion_note"] = f"蒲田1: no shared exclusion module found; variant={variant}"
        frame["analysis_segment"] = np.where(frame["is_event_day"], "A_event", "A_non_event")
        frame["analysis_segment"] = pd.Series(frame["analysis_segment"], index=frame.index, dtype="object")
        frame.loc[:, "analysis_segment"] = "A_all"
    else:
        raise ValueError(f"unsupported hall: {hall}")

    return frame.reset_index(drop=True)


def is_event_day(hall: str, dates: pd.Series, dd: pd.Series) -> pd.Series:
    date_ts = pd.to_datetime(dates.astype(str), format="%Y%m%d", errors="coerce")
    event_digits = HALL_EVENT_DIGITS.get(hall, [])
    month_end = date_ts.dt.days_in_month
    mmdd_zorome = date_ts.dt.month == date_ts.dt.day
    return (dd.isin(event_digits) | (dd == month_end) | mmdd_zorome).astype(bool)


def dd_bin_label(dd: int) -> str:
    for label, lo, hi in DD_BINS:
        if lo <= int(dd) <= hi:
            return label
    return np.nan


def assign_kakuban_bucket(row: pd.Series) -> str:
    """Five directional edge buckets using section-relative ranks."""
    rmin = int(row["rank_from_min"])
    rmax = int(row["rank_from_max"])
    if rmin == 1:
        return "角1"
    if rmin == 2:
        return "角2"
    if rmax == 2:
        return "角N-1"
    if rmax == 1:
        return "角N"
    return "中間"


def _aggregate(frame: pd.DataFrame, group_cols: list[str]) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame()
    grouped = (
        frame.groupby(group_cols, observed=True, dropna=False)
        .agg(
            n=("rb_prob", "size"),
            n_dates=("date", "nunique"),
            n_machines=("machine_number", "nunique"),
            rb_count_sum=("rb_count", "sum"),
            games_sum=("games", "sum"),
            rb_rate_mean=("rb_prob", "mean"),
            diff_sum=("diff", "sum"),
            payout_rate_mean=("payout_rate", "mean"),
        )
        .reset_index()
    )
    grouped["rb_rate_pooled"] = grouped["rb_count_sum"] / grouped["games_sum"].replace(0, np.nan)
    grouped["rb_1_over_x_pooled"] = 1 / grouped["rb_rate_pooled"].replace(0, np.nan)
    grouped["rb_1_over_x_mean"] = 1 / grouped["rb_rate_mean"].replace(0, np.nan)
    grouped["payout_rate_pooled"] = (1 + grouped["diff_sum"] / (grouped["games_sum"] * 3)) * 100
    grouped["kakuban_bucket"] = pd.Categorical(grouped["kakuban_bucket"], categories=KAKUBAN_ORDER, ordered=True)
    sort_cols = [c for c in ["analysis_segment", "dd_bin", "kakuban_bucket"] if c in grouped.columns]
    return grouped.sort_values(sort_cols).reset_index(drop=True)


def _kruskal_by_bucket(frame: pd.DataFrame) -> dict[str, float]:
    groups = [
        grp["rb_prob"].dropna().to_numpy() for _, grp in frame.groupby("kakuban_bucket", observed=True) if len(grp) >= 5
    ]
    if len(groups) < 2:
        return {"kruskal_stat": np.nan, "kruskal_p": np.nan, "epsilon_sq": np.nan, "n_groups": len(groups)}
    stat, p_value = kruskal(*groups)
    n_total = sum(len(g) for g in groups)
    return {
        "kruskal_stat": float(stat),
        "kruskal_p": float(p_value),
        "epsilon_sq": float(_epsilon_squared(float(stat), len(groups), n_total)),
        "n_groups": float(len(groups)),
    }


def _angle1_test(frame: pd.DataFrame) -> dict[str, float | bool]:
    angle1 = frame.loc[frame["kakuban_bucket"].eq("角1"), "rb_prob"].dropna().to_numpy()
    others = frame.loc[~frame["kakuban_bucket"].eq("角1"), "rb_prob"].dropna().to_numpy()
    if len(angle1) < 5 or len(others) < 5:
        return {
            "angle1_vs_others_p": np.nan,
            "angle1_is_lower": False,
            "angle1_n": len(angle1),
            "others_n": len(others),
        }
    stat, p_value = mannwhitneyu(angle1, others, alternative="less")
    return {
        "angle1_vs_others_p": float(p_value),
        "angle1_is_lower": bool(np.nanmean(angle1) < np.nanmean(others)),
        "angle1_n": int(len(angle1)),
        "others_n": int(len(others)),
    }


def build_kakuban_summary(frame: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, object]]:
    summary = _aggregate(frame, ["hall", "min_games", "kakuban_bucket"])
    stats = _kruskal_by_bucket(frame)
    angle1 = _angle1_test(frame)
    if len(summary) >= 3:
        rho, rho_p = spearmanr(summary["rb_rate_pooled"], summary["payout_rate_mean"], nan_policy="omit")
    else:
        rho, rho_p = np.nan, np.nan
    stats.update(angle1)
    stats["spearman_rb_vs_payout_rho"] = float(rho) if pd.notna(rho) else np.nan
    stats["spearman_rb_vs_payout_p"] = float(rho_p) if pd.notna(rho_p) else np.nan
    stats["angle1_rb_rank"] = bucket_rank(summary, "角1", "rb_rate_pooled", ascending=False)
    stats["angle1_payout_rank"] = bucket_rank(summary, "角1", "payout_rate_mean", ascending=False)
    stats["angle1_lowest_rb"] = bool(bucket_rank(summary, "角1", "rb_rate_pooled", ascending=True) == 1)
    return summary, stats


def bucket_rank(frame: pd.DataFrame, bucket: str, value_col: str, *, ascending: bool) -> float:
    if frame.empty or bucket not in set(frame["kakuban_bucket"].astype(str)):
        return np.nan
    ranked = frame.sort_values(value_col, ascending=ascending).reset_index(drop=True)
    matches = ranked.index[ranked["kakuban_bucket"].astype(str).eq(bucket)].tolist()
    return float(matches[0] + 1) if matches else np.nan


def comparison_segments(hall: str, frame: pd.DataFrame) -> pd.DataFrame:
    if hall == "蒲田7":
        return frame[frame["analysis_segment"].isin(KAMATA7_COMPARE_SEGMENTS)].copy()
    if hall == "蒲田1":
        work = frame.copy()
        frames = []
        all_seg = work.copy()
        all_seg["analysis_segment"] = "A_all"
        frames.append(all_seg)
        event_seg = work[work["is_event_day"]].copy()
        event_seg["analysis_segment"] = "A_event"
        frames.append(event_seg)
        hot = work[work["section"].astype(str).eq("2236-2255") & work["is_event_day"]].copy()
        hot["analysis_segment"] = "A_event_section_2236-2255"
        frames.append(hot)
        return pd.concat(frames, ignore_index=True)
    raise ValueError(f"unsupported hall: {hall}")


def build_dd_cross_and_comparison(hall: str, frame: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    seg_frame = comparison_segments(hall, frame)
    cross = _aggregate(seg_frame, ["hall", "min_games", "analysis_segment", "dd_bin", "kakuban_bucket"])
    if cross.empty:
        return cross, pd.DataFrame()

    rows: list[dict[str, object]] = []
    for (segment, dd_bin), grp in cross.groupby(["analysis_segment", "dd_bin"], observed=True):
        eligible = grp[grp["n"] >= 5].copy()
        if eligible.empty:
            rows.append(
                {
                    "hall": hall,
                    "min_games": int(frame["min_games"].iloc[0]),
                    "analysis_segment": segment,
                    "dd_bin": dd_bin,
                    "rb_best_bucket": np.nan,
                    "payout_best_bucket": np.nan,
                    "matches_payout_best": False,
                    "theory_expected_bucket": theory_bucket(hall, str(segment), str(dd_bin)),
                    "matches_theory_expected": False,
                    "note": "no cell with n>=5",
                }
            )
            continue
        rb_row = eligible.sort_values(["rb_rate_pooled", "n"], ascending=[False, False]).iloc[0]
        payout_row = eligible.sort_values(["payout_rate_mean", "n"], ascending=[False, False]).iloc[0]
        expected = theory_bucket(hall, str(segment), str(dd_bin))
        rows.append(
            {
                "hall": hall,
                "min_games": int(frame["min_games"].iloc[0]),
                "analysis_segment": segment,
                "dd_bin": dd_bin,
                "rb_best_bucket": str(rb_row["kakuban_bucket"]),
                "rb_best_rate": float(rb_row["rb_rate_pooled"]),
                "rb_best_1_over_x": float(rb_row["rb_1_over_x_pooled"]),
                "rb_best_n": int(rb_row["n"]),
                "payout_best_bucket": str(payout_row["kakuban_bucket"]),
                "payout_best_rate": float(payout_row["payout_rate_mean"]),
                "payout_best_n": int(payout_row["n"]),
                "matches_payout_best": str(rb_row["kakuban_bucket"]) == str(payout_row["kakuban_bucket"]),
                "theory_expected_bucket": expected,
                "matches_theory_expected": bool(expected and str(rb_row["kakuban_bucket"]) == expected),
                "note": "",
            }
        )
    comparison = pd.DataFrame(rows)
    comparison["dd_bin"] = pd.Categorical(comparison["dd_bin"], categories=DD_BIN_ORDER, ordered=True)
    return cross, comparison.sort_values(["analysis_segment", "dd_bin"]).reset_index(drop=True)


def theory_bucket(hall: str, segment: str, dd_bin: str) -> str:
    if hall == "蒲田7":
        return KAMATA7_THEORY_BUCKET.get((segment, dd_bin), "")
    if hall == "蒲田1":
        if segment in {"A_event", "A_event_section_2236-2255"}:
            return "中間"
        return ""
    return ""


def write_csv(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False, encoding="utf-8-sig")


def _format_rate(rate: float) -> str:
    if pd.isna(rate) or rate <= 0:
        return "NaN"
    return f"{rate:.6f} (1/{1 / rate:.1f})"


def markdown_table(frame: pd.DataFrame, cols: list[str], *, max_rows: int = 30) -> str:
    if frame.empty:
        return "_no rows_"
    view = frame.loc[:, [c for c in cols if c in frame.columns]].head(max_rows).copy()
    headers = list(view.columns)
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join(["---"] * len(headers)) + " |",
    ]
    for _, row in view.iterrows():
        cells: list[str] = []
        for col in headers:
            value = row[col]
            if pd.isna(value):
                cells.append("NaN")
            elif isinstance(value, (float, np.floating)):
                cells.append(f"{float(value):.6g}")
            elif isinstance(value, (int, np.integer)):
                cells.append(str(int(value)))
            else:
                cells.append(str(value))
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def build_summary_markdown(
    hall: str,
    diagnostics: HallDiagnostics,
    stats_by_min_games: dict[int, dict[str, object]],
    summaries: dict[int, pd.DataFrame],
    comparisons: dict[int, pd.DataFrame],
    *,
    removed_variant_delta: pd.DataFrame | None = None,
) -> str:
    primary = stats_by_min_games[CORE_MIN_GAMES]
    if primary.get("angle1_lowest_rb") and primary.get("angle1_vs_others_p", np.nan) < 0.05:
        verdict = "Yes"
    elif primary.get("angle1_lowest_rb") or primary.get("spearman_rb_vs_payout_rho", np.nan) > 0:
        verdict = "部分的"
    else:
        verdict = "No"

    lines = [
        f"# {hall} kakuban RB probability verification",
        "",
        f"差枚ベースの角番効果はRB確率でも再現されるか: {verdict}",
        "",
        "## Input diagnostics",
        "",
        f"- DB: `{diagnostics.db_path}`",
        f"- DB size: {diagnostics.db_size_bytes:,} bytes",
        f"- machine_detailed_results range: {diagnostics.min_date} to {diagnostics.max_date} ({diagnostics.raw_rows:,} rows)",
        f"- machine_layout rows: {diagnostics.layout_rows:,}",
        f"- Juggler target rows at min_games={CORE_MIN_GAMES}: {diagnostics.juggler_rows_min400:,} rows, {diagnostics.juggler_machines_min400:,} machines",
    ]
    if hall == "蒲田1":
        lines += [
            "",
            "## Unconfirmed Item 1: Kamata1 shared exclusion logic",
            "",
            "- Search result: no Kamata1 equivalent of `prepare_base_frame()` that centralizes iron-machine/special-day exclusions was found.",
            "- Existing Kamata1 scripts include local handling; one robustness script states durable_machine_numbers is undefined/empty.",
            "- This script therefore applies no Kamata1 iron-machine or special-day exclusion beyond the explicit 2331-2340 sensitivity variant.",
            "",
            "## Unconfirmed Item 2: 2331-2340 removed machines",
            "",
            f"- Rows for 2331-2340 all-time: {diagnostics.kamata1_removed_rows_all_time:,}",
            f"- Max date for 2331-2340: {diagnostics.kamata1_removed_max_date}",
            f"- Rows on/after 2025-08-17: {diagnostics.kamata1_removed_rows_on_or_after_removed_date:,}",
            f"- Rows after 2025-08-17: {diagnostics.kamata1_removed_rows_after_removed_date:,}",
            "- Interpretation: data naturally stops after 2025-08-17; all-time hard exclusion is reported as a sensitivity check, not the primary filter.",
        ]
        if removed_variant_delta is not None and not removed_variant_delta.empty:
            lines += [
                "",
                "### 2331-2340 all-time exclusion sensitivity",
                "",
                markdown_table(
                    removed_variant_delta,
                    [
                        "kakuban_bucket",
                        "rb_rate_pooled_primary",
                        "rb_rate_pooled_exclude_all_time",
                        "rb_rate_delta",
                        "payout_rate_mean_primary",
                        "payout_rate_mean_exclude_all_time",
                        "payout_delta",
                    ],
                ),
            ]

    for min_games, stats in stats_by_min_games.items():
        summary = summaries[min_games]
        comparison = comparisons[min_games]
        match_rate = np.nan
        if not comparison.empty:
            valid = comparison[comparison["rb_best_bucket"].notna()]
            if not valid.empty:
                match_rate = float(valid["matches_payout_best"].mean())
        lines += [
            "",
            f"## min_games={min_games}",
            "",
            f"- Kruskal-Wallis p={stats.get('kruskal_p', np.nan):.6g}, epsilon_sq={stats.get('epsilon_sq', np.nan):.6g}, groups={stats.get('n_groups', np.nan)}",
            f"- Spearman(rb_rate_pooled vs payout_rate_mean): rho={stats.get('spearman_rb_vs_payout_rho', np.nan):.4g}, p={stats.get('spearman_rb_vs_payout_p', np.nan):.4g}",
            f"- 角1 vs others MWU(one-sided less): p={stats.get('angle1_vs_others_p', np.nan):.6g}, angle1_is_lower={stats.get('angle1_is_lower')}, angle1_lowest_rb={stats.get('angle1_lowest_rb')}",
            f"- DD×角番 best-bucket match rate (RB vs payout): {match_rate:.3f}"
            if pd.notna(match_rate)
            else "- DD×角番 best-bucket match rate (RB vs payout): NaN",
            "",
            "### Kakuban bucket summary",
            "",
            markdown_table(
                summary,
                [
                    "kakuban_bucket",
                    "n",
                    "n_dates",
                    "n_machines",
                    "rb_rate_pooled",
                    "rb_1_over_x_pooled",
                    "rb_rate_mean",
                    "payout_rate_mean",
                    "payout_rate_pooled",
                ],
            ),
            "",
            "### DD x kakuban comparison",
            "",
            markdown_table(
                comparison,
                [
                    "analysis_segment",
                    "dd_bin",
                    "rb_best_bucket",
                    "rb_best_1_over_x",
                    "payout_best_bucket",
                    "matches_payout_best",
                    "theory_expected_bucket",
                    "matches_theory_expected",
                    "note",
                ],
                max_rows=60,
            ),
        ]

    return "\n".join(lines) + "\n"


def analyze_hall(hall: str, patterns: list[str], output_root: Path) -> dict[str, object]:
    diagnostics = inspect_hall(hall, patterns)
    hall_dir = output_root / hall
    hall_dir.mkdir(parents=True, exist_ok=True)

    stats_by_min_games: dict[int, dict[str, object]] = {}
    summaries: dict[int, pd.DataFrame] = {}
    comparisons: dict[int, pd.DataFrame] = {}
    written: list[Path] = []

    for min_games in SENSITIVITY_MIN_GAMES:
        frame = load_base_frame(hall, patterns, min_games=min_games)
        summary, stats = build_kakuban_summary(frame)
        cross, comparison = build_dd_cross_and_comparison(hall, frame)
        summaries[min_games] = summary
        stats_by_min_games[min_games] = stats
        comparisons[min_games] = comparison

        paths = [
            hall_dir / f"kakuban_bucket_summary_min{min_games}.csv",
            hall_dir / f"dd_kakuban_cross_min{min_games}.csv",
            hall_dir / f"dd_kakuban_comparison_min{min_games}.csv",
        ]
        for data, path in zip([summary, cross, comparison], paths):
            write_csv(data, path)
            written.append(path)

    removed_delta = None
    if hall == "蒲田1":
        primary = summaries[CORE_MIN_GAMES].copy()
        variant_frame = load_base_frame(
            hall,
            patterns,
            min_games=CORE_MIN_GAMES,
            exclude_removed_kamata1_all_time=True,
        )
        variant_summary, _ = build_kakuban_summary(variant_frame)
        variant_path = hall_dir / f"kakuban_bucket_summary_min{CORE_MIN_GAMES}_exclude2331_2340_all_time.csv"
        write_csv(variant_summary, variant_path)
        written.append(variant_path)
        removed_delta = primary.merge(
            variant_summary,
            on="kakuban_bucket",
            how="outer",
            suffixes=("_primary", "_exclude_all_time"),
        )
        if not removed_delta.empty:
            removed_delta["rb_rate_delta"] = (
                removed_delta["rb_rate_pooled_exclude_all_time"] - removed_delta["rb_rate_pooled_primary"]
            )
            removed_delta["payout_delta"] = (
                removed_delta["payout_rate_mean_exclude_all_time"] - removed_delta["payout_rate_mean_primary"]
            )
            delta_path = hall_dir / "kamata1_2331_2340_sensitivity_delta.csv"
            write_csv(removed_delta, delta_path)
            written.append(delta_path)

    report = build_summary_markdown(
        hall,
        diagnostics,
        stats_by_min_games,
        summaries,
        comparisons,
        removed_variant_delta=removed_delta,
    )
    report_path = hall_dir / "summary.md"
    report_path.write_text(report, encoding="utf-8")
    written.append(report_path)

    return {
        "hall": hall,
        "diagnostics": diagnostics,
        "stats": stats_by_min_games,
        "summaries": summaries,
        "comparisons": comparisons,
        "written": written,
    }


def parse_halls(value: str) -> list[str]:
    if value == "all":
        return SUPPORTED_HALLS
    halls = [item.strip() for item in value.split(",") if item.strip()]
    unknown = [hall for hall in halls if hall not in SUPPORTED_HALLS]
    if unknown:
        raise argparse.ArgumentTypeError(f"unsupported hall(s): {unknown}; choose {SUPPORTED_HALLS} or all")
    return halls


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify kakuban effects using Juggler RB pooled probability.")
    parser.add_argument("--hall", type=parse_halls, default=SUPPORTED_HALLS, help="蒲田7, 蒲田1, comma-list, or all")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args(list(argv) if argv is not None else None)

    patterns = load_juggler_patterns_from_targets()
    all_written: list[Path] = []
    for hall in args.hall:
        result = analyze_hall(hall, patterns, args.output_dir)
        all_written.extend(result["written"])
        stats = result["stats"][CORE_MIN_GAMES]
        summary = result["summaries"][CORE_MIN_GAMES]
        angle1_rate = summary.loc[summary["kakuban_bucket"].astype(str).eq("角1"), "rb_rate_pooled"]
        angle1_text = _format_rate(float(angle1_rate.iloc[0])) if not angle1_rate.empty else "NaN"
        print(
            f"{hall}: angle1_rb={angle1_text}, "
            f"angle1_lowest_rb={stats.get('angle1_lowest_rb')}, "
            f"angle1_p={stats.get('angle1_vs_others_p')}, "
            f"spearman={stats.get('spearman_rb_vs_payout_rho')}"
        )

    print("written:")
    for path in all_written:
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
