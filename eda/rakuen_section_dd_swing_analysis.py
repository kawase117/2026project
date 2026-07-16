from __future__ import annotations

import argparse
import sqlite3
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import kruskal

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from eda.section_lateral_expansion import HALL_CONFIGS, _load_coords  # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
DEFAULT_DB_PATH = PROJECT_ROOT / "db" / "楽園蒲田店.db"
DEFAULT_OUTPUT_DIR = SCRIPT_DIR / "results" / "rakuen_section_dd_swing_analysis"
DEFAULT_MIN_GAMES = 2000
DEFAULT_MIN_CELL_N = 5
EVENT_DDS = frozenset(HALL_CONFIGS["rakuen"].event_dds)
STRONG_ZOROME = bool(HALL_CONFIGS["rakuen"].strong_zorome)


@dataclass(frozen=True)
class RakuenSectionAnalysis:
    raw: pd.DataFrame
    coords: pd.DataFrame
    matrix: pd.DataFrame
    section_metrics: pd.DataFrame
    kw_significance: pd.DataFrame
    swing_ranking: pd.DataFrame
    type_b_playbook: pd.DataFrame
    previous_event_responsive: pd.DataFrame
    section_order: pd.DataFrame


def _format_value(value: object, *, digits: int = 3) -> str:
    if value is None or pd.isna(value):
        return ""
    if isinstance(value, (float, np.floating)):
        return f"{float(value):.{digits}f}"
    if isinstance(value, (int, np.integer)):
        return str(int(value))
    return str(value)


def _markdown_table(frame: pd.DataFrame, *, columns: list[str] | None = None, float_digits: int = 3) -> str:
    work = frame.copy()
    if columns is not None:
        work = work.loc[:, columns]
    if work.empty:
        return "No rows."
    headers = [str(col) for col in work.columns]
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join(["---"] * len(headers)) + " |",
    ]
    for _, row in work.iterrows():
        lines.append("| " + " | ".join(_format_value(row[col], digits=float_digits) for col in work.columns) + " |")
    return "\n".join(lines)


def _write_csv(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False, encoding="utf-8-sig")


def _resolve_db_path(path: Path) -> Path:
    if path.exists():
        return path
    if path.parent.exists():
        for candidate in path.parent.glob("*楽園蒲田店.db"):
            return candidate
    raise FileNotFoundError(path)


def _load_raw_frame(db_path: Path, *, min_games: int) -> pd.DataFrame:
    with sqlite3.connect(db_path) as conn:
        raw = pd.read_sql_query(
            """
            SELECT
                date,
                machine_name,
                machine_number,
                games_normalized,
                diff_coins_normalized
            FROM machine_detailed_results
            """,
            conn,
        )

    work = raw.copy()
    work["date"] = work["date"].astype(str)
    work["date_dt"] = pd.to_datetime(work["date"], format="%Y%m%d", errors="coerce")
    work["machine_number"] = pd.to_numeric(work["machine_number"], errors="coerce")
    work["games_normalized"] = pd.to_numeric(work["games_normalized"], errors="coerce")
    work["diff_coins_normalized"] = pd.to_numeric(work["diff_coins_normalized"], errors="coerce")
    work = work.dropna(
        subset=["date_dt", "machine_number", "machine_name", "games_normalized", "diff_coins_normalized"]
    ).copy()
    work["machine_number"] = work["machine_number"].astype(int)
    work = work[work["games_normalized"].ge(int(min_games))].copy()
    work["dd"] = work["date_dt"].dt.day.astype(int)
    work["hit_flag"] = work["diff_coins_normalized"].gt(0).astype(int)
    return work.reset_index(drop=True)


def _prepare_frame(db_path: Path, *, min_games: int) -> tuple[pd.DataFrame, pd.DataFrame]:
    coords = _load_coords(HALL_CONFIGS["rakuen"].coords_paths)
    raw = _load_raw_frame(db_path, min_games=min_games)
    work = raw.merge(coords, on="machine_number", how="inner", validate="m:1")
    if work.empty:
        raise ValueError("No rows remained after joining Rakuen coordinates")
    work["floor"] = work["floor"].astype(str)
    work["section"] = work["section"].astype(str)
    work["section_size"] = pd.to_numeric(work["section_size"], errors="coerce").astype(int)
    work["is_event_dd"] = work["dd"].isin(sorted(EVENT_DDS))
    work = work.sort_values(["floor", "section_min", "section_max", "dd", "machine_number"]).reset_index(drop=True)
    return work, coords


def _section_order(coords: pd.DataFrame) -> pd.DataFrame:
    order = (
        coords.groupby(["section", "floor", "section_min", "section_max", "section_size"], as_index=False)
        .agg(machine_count=("machine_number", "nunique"))
        .sort_values(["floor", "section_min", "section_max", "section"], kind="mergesort")
        .reset_index(drop=True)
    )
    order["section_rank"] = np.arange(1, len(order) + 1)
    return order


def _build_matrix(frame: pd.DataFrame, section_order: pd.DataFrame) -> pd.DataFrame:
    summary = (
        frame.groupby(["section", "dd"], as_index=False)
        .agg(
            n=("diff_coins_normalized", "size"),
            avg_diff=("diff_coins_normalized", "mean"),
            hit_rate=("hit_flag", "mean"),
            avg_games=("games_normalized", "mean"),
        )
        .copy()
    )
    summary["hit_rate"] = summary["hit_rate"] * 100.0
    summary["is_event_dd"] = summary["dd"].isin(sorted(EVENT_DDS))

    dd_grid = pd.DataFrame({"dd": list(range(1, 32))})
    dd_grid["key"] = 1
    sections = section_order.loc[
        :, ["section", "floor", "section_min", "section_max", "section_size", "section_rank"]
    ].copy()
    sections["key"] = 1
    matrix = sections.merge(dd_grid, on="key", how="inner").drop(columns=["key"])
    matrix = matrix.merge(summary, on=["section", "dd"], how="left", validate="1:1")
    matrix["n"] = matrix["n"].fillna(0).astype(int)
    matrix["is_event_dd"] = matrix["dd"].isin(sorted(EVENT_DDS))
    matrix = matrix.sort_values(["section_rank", "dd"], kind="mergesort").reset_index(drop=True)
    return matrix


def _sign_change_count(values: list[float]) -> int:
    signs = [1 if value > 0 else -1 if value < 0 else 0 for value in values]
    compact = [sign for sign in signs if sign != 0]
    if len(compact) < 2:
        return 0
    return int(sum(left != right for left, right in zip(compact, compact[1:])))


def _kw_for_section(section_frame: pd.DataFrame, *, min_cell_n: int) -> dict[str, object]:
    groups: list[pd.Series] = []
    dd_used: list[int] = []
    dd_skipped: list[int] = []
    for dd_value, dd_frame in section_frame.groupby("dd", dropna=False):
        values = pd.to_numeric(dd_frame["diff_coins_normalized"], errors="coerce").dropna()
        if len(values) < int(min_cell_n):
            dd_skipped.append(int(dd_value))
            continue
        groups.append(values)
        dd_used.append(int(dd_value))
    if len(groups) < 2:
        return {
            "kw_groups": int(len(groups)),
            "kw_samples": 0,
            "kw_stat": float("nan"),
            "kw_p_value": float("nan"),
            "kw_epsilon_sq": float("nan"),
            "kw_dd_used": ",".join(map(str, dd_used)),
            "kw_dd_skipped": ",".join(map(str, dd_skipped)),
        }
    stat, p_value = kruskal(*groups)
    n_total = int(sum(len(values) for values in groups))
    epsilon_sq = float(stat / (n_total - 1)) if n_total > 1 else float("nan")
    return {
        "kw_groups": int(len(groups)),
        "kw_samples": n_total,
        "kw_stat": float(stat),
        "kw_p_value": float(p_value),
        "kw_epsilon_sq": epsilon_sq,
        "kw_dd_used": ",".join(map(str, dd_used)),
        "kw_dd_skipped": ",".join(map(str, dd_skipped)),
    }


def _section_metrics(frame: pd.DataFrame, matrix: pd.DataFrame, *, min_cell_n: int) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    matrix_valid = matrix[matrix["n"].ge(int(min_cell_n))].copy()

    for _, section_row in (
        matrix.loc[:, ["section", "floor", "section_min", "section_max", "section_size", "section_rank"]]
        .drop_duplicates()
        .sort_values(["section_rank"], kind="mergesort")
        .iterrows()
    ):
        section = section_row["section"]
        section_frame = frame[frame["section"].eq(section)].copy()
        cell_frame = matrix_valid[matrix_valid["section"].eq(section)].copy()
        kw = _kw_for_section(section_frame, min_cell_n=min_cell_n)

        section_avg_diff = float(pd.to_numeric(section_frame["diff_coins_normalized"], errors="coerce").mean())
        section_hit_rate = float(pd.to_numeric(section_frame["hit_flag"], errors="coerce").mean() * 100.0)
        cell_values = pd.to_numeric(cell_frame["avg_diff"], errors="coerce").dropna()
        valid_dd_n = int(len(cell_values))
        coverage = float(valid_dd_n / 31.0)

        if valid_dd_n > 0:
            cell_mean = float(cell_values.mean())
            cell_std = float(cell_values.std(ddof=1)) if valid_dd_n > 1 else float("nan")
            cell_min = float(cell_values.min())
            cell_max = float(cell_values.max())
            cell_swing = float(cell_max - cell_min)
            residuals = cell_values - section_avg_diff
            residual_mean = float(residuals.mean())
            residual_std = float(residuals.std(ddof=1)) if valid_dd_n > 1 else float("nan")
            residual_min = float(residuals.min())
            residual_max = float(residuals.max())
            residual_swing = float(residual_max - residual_min)
            max_abs_residual = float(np.abs(residuals).max())
            positive_rate = float((cell_values > 0).mean())
            negative_rate = float((cell_values < 0).mean())
            dominant_sign_rate = float(max(positive_rate, negative_rate))
            dominant_sign = "+" if positive_rate > negative_rate else "-" if negative_rate > positive_rate else "tie"
            sign_change_count = _sign_change_count(cell_values.tolist())
            best_dd_row = cell_frame.sort_values(
                ["avg_diff", "hit_rate", "n", "dd"], ascending=[False, False, False, True]
            ).iloc[0]
            worst_dd_row = cell_frame.sort_values(
                ["avg_diff", "hit_rate", "n", "dd"], ascending=[True, True, True, True]
            ).iloc[0]
            event_frame = cell_frame[cell_frame["is_event_dd"]].copy()
            event_cell_n = int(len(event_frame))
            event_avg_diff = float(event_frame["avg_diff"].mean()) if event_cell_n > 0 else float("nan")
            event_hit_rate = float(event_frame["hit_rate"].mean()) if event_cell_n > 0 else float("nan")
        else:
            cell_mean = float("nan")
            cell_std = float("nan")
            cell_min = float("nan")
            cell_max = float("nan")
            cell_swing = float("nan")
            residual_mean = float("nan")
            residual_std = float("nan")
            residual_min = float("nan")
            residual_max = float("nan")
            residual_swing = float("nan")
            max_abs_residual = float("nan")
            positive_rate = float("nan")
            negative_rate = float("nan")
            dominant_sign_rate = float("nan")
            dominant_sign = "unknown"
            sign_change_count = 0
            best_dd_row = pd.Series({"dd": np.nan, "avg_diff": np.nan, "hit_rate": np.nan, "n": np.nan})
            worst_dd_row = pd.Series({"dd": np.nan, "avg_diff": np.nan, "hit_rate": np.nan, "n": np.nan})
            event_cell_n = 0
            event_avg_diff = float("nan")
            event_hit_rate = float("nan")

        rows.append(
            {
                "section": section,
                "floor": section_row["floor"],
                "section_min": int(section_row["section_min"]),
                "section_max": int(section_row["section_max"]),
                "section_size": int(section_row["section_size"]),
                "section_rank": int(section_row["section_rank"]),
                "section_n": int(len(section_frame)),
                "section_avg_diff": section_avg_diff,
                "section_hit_rate": section_hit_rate,
                "valid_dd_n": valid_dd_n,
                "cell_coverage": coverage,
                "cell_avg_diff_mean": cell_mean,
                "cell_avg_diff_std": cell_std,
                "cell_avg_diff_min": cell_min,
                "cell_avg_diff_max": cell_max,
                "dd_swing_index": cell_swing,
                "residual_mean": residual_mean,
                "residual_std": residual_std,
                "residual_min": residual_min,
                "residual_max": residual_max,
                "residual_swing": residual_swing,
                "max_abs_residual": max_abs_residual,
                "positive_rate": positive_rate,
                "negative_rate": negative_rate,
                "dominant_sign_rate": dominant_sign_rate,
                "dominant_sign": dominant_sign,
                "sign_change_count": int(sign_change_count),
                "best_dd": int(best_dd_row["dd"]) if pd.notna(best_dd_row["dd"]) else np.nan,
                "best_dd_avg_diff": float(best_dd_row["avg_diff"]) if pd.notna(best_dd_row["avg_diff"]) else np.nan,
                "worst_dd": int(worst_dd_row["dd"]) if pd.notna(worst_dd_row["dd"]) else np.nan,
                "worst_dd_avg_diff": float(worst_dd_row["avg_diff"]) if pd.notna(worst_dd_row["avg_diff"]) else np.nan,
                "event_cell_n": event_cell_n,
                "event_cell_avg_diff": event_avg_diff,
                "event_cell_hit_rate": event_hit_rate,
                **kw,
            }
        )

    out = pd.DataFrame(rows)
    out["type_ab"] = "B"
    out["watching_flag"] = False
    return out.sort_values("section_rank", kind="mergesort").reset_index(drop=True)


def _classify_sections(section_metrics: pd.DataFrame) -> pd.DataFrame:
    work = section_metrics.copy()
    if work.empty:
        return work
    median_residual_std = float(work["residual_std"].median(skipna=True))
    q75_swing = float(work["dd_swing_index"].quantile(0.75))

    type_a_mask = work["dominant_sign_rate"].ge(0.90) & work["sign_change_count"].le(1)
    work["type_ab"] = np.where(type_a_mask, "A", "B")
    work["watching_flag"] = work["valid_dd_n"].lt(8) & work["dominant_sign_rate"].ge(0.65)
    work["type_reason"] = np.where(
        work["type_ab"].eq("A"),
        np.where(
            work["residual_std"].gt(median_residual_std),
            "same sign >=90% + few flips; magnitude spread is still wide",
            "same sign >=90% + few flips",
        ),
        np.where(
            work["watching_flag"],
            "low sample but repeated direction",
            np.where(
                work["dd_swing_index"].ge(q75_swing),
                "large DD swing / selective pattern",
                "mixed signs or concentrated DD effects",
            ),
        ),
    )
    work["dominant_sign_rate"] = work["dominant_sign_rate"].round(6)
    work["cell_avg_diff_std"] = work["cell_avg_diff_std"].round(6)
    work["dd_swing_index"] = work["dd_swing_index"].round(6)
    work["residual_std"] = work["residual_std"].round(6)
    work["residual_swing"] = work["residual_swing"].round(6)
    work["max_abs_residual"] = work["max_abs_residual"].round(6)
    work["cell_coverage"] = work["cell_coverage"].round(6)
    return work.sort_values(
        ["dd_swing_index", "kw_p_value", "section"], ascending=[False, True, True], kind="mergesort"
    ).reset_index(drop=True)


def _format_dd_cell_row(row: pd.Series) -> str:
    dd = int(row["dd"])
    avg_diff = float(row["avg_diff"])
    hit_rate = float(row["hit_rate"])
    event_tag = " event" if bool(row["is_event_dd"]) else ""
    return f"{dd}({avg_diff:+.1f}, {hit_rate:.1f}%{event_tag})"


def _build_playbook(
    section_metrics: pd.DataFrame, matrix: pd.DataFrame, previous_event_responsive: pd.DataFrame
) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    previous_map = (
        previous_event_responsive.set_index("section")[["event_lift_pp", "n"]].to_dict("index")
        if not previous_event_responsive.empty
        else {}
    )
    type_b_sections = section_metrics[section_metrics["type_ab"].eq("B")].copy()
    for _, section_row in type_b_sections.iterrows():
        section = section_row["section"]
        cell_frame = matrix[(matrix["section"].eq(section)) & (matrix["n"].ge(int(DEFAULT_MIN_CELL_N)))].copy()
        cell_frame = cell_frame.dropna(subset=["avg_diff", "hit_rate"]).copy()
        if cell_frame.empty:
            continue
        cell_frame = cell_frame.sort_values(
            ["avg_diff", "hit_rate", "n", "dd"], ascending=[False, False, False, True], kind="mergesort"
        )
        top = cell_frame.head(5).copy()
        bottom = (
            cell_frame.sort_values(
                ["avg_diff", "hit_rate", "n", "dd"], ascending=[True, True, False, True], kind="mergesort"
            )
            .head(5)
            .copy()
        )
        prev = previous_map.get(section, {})
        for direction, ranking_frame in [("target", top), ("avoid", bottom)]:
            for rank, (_, dd_row) in enumerate(ranking_frame.iterrows(), start=1):
                rows.append(
                    {
                        "section": section,
                        "floor": section_row["floor"],
                        "type_ab": section_row["type_ab"],
                        "watching_flag": bool(section_row["watching_flag"]),
                        "direction": direction,
                        "direction_rank": rank,
                        "dd": int(dd_row["dd"]),
                        "avg_diff": float(dd_row["avg_diff"]),
                        "hit_rate": float(dd_row["hit_rate"]),
                        "n": int(dd_row["n"]),
                        "is_event_dd": bool(dd_row["is_event_dd"]),
                        "dd_swing_index": float(section_row["dd_swing_index"]),
                        "kw_p_value": float(section_row["kw_p_value"]),
                        "kw_epsilon_sq": float(section_row["kw_epsilon_sq"]),
                        "prior_event_lift_pp": float(prev.get("event_lift_pp", float("nan"))),
                        "prior_event_n": int(prev.get("n", 0)) if prev else 0,
                    }
                )
    out = pd.DataFrame(rows)
    if out.empty:
        return out
    return out.sort_values(
        ["dd_swing_index", "section", "direction", "direction_rank"],
        ascending=[False, True, True, True],
        kind="mergesort",
    ).reset_index(drop=True)


def _load_previous_event_responsive() -> pd.DataFrame:
    path = PROJECT_ROOT / "eda" / "results" / "rakuen_segment_structure" / "step2_section_event_responsive.csv"
    if not path.exists():
        return pd.DataFrame(columns=["floor", "section", "hit_nonevent", "hit_event", "event_lift_pp", "n"])
    frame = pd.read_csv(path)
    frame["section"] = frame["section"].astype(str)
    return frame


def _section_detail_table(matrix: pd.DataFrame, section_name: str) -> pd.DataFrame:
    detail = matrix[matrix["section"].eq(section_name)].copy()
    if detail.empty:
        return detail
    detail = detail.loc[
        :,
        [
            "dd",
            "n",
            "avg_diff",
            "hit_rate",
            "is_event_dd",
            "avg_games",
        ],
    ].copy()
    detail["hit_rate"] = detail["hit_rate"].round(3)
    detail["avg_diff"] = detail["avg_diff"].round(3)
    detail["avg_games"] = detail["avg_games"].round(1)
    return detail.sort_values("dd", kind="mergesort").reset_index(drop=True)


def _build_report(analysis: RakuenSectionAnalysis, db_path: Path) -> str:
    frame = analysis.raw
    section_metrics = analysis.section_metrics
    matrix = analysis.matrix
    type_a = section_metrics[section_metrics["type_ab"].eq("A")].copy()
    type_b = section_metrics[section_metrics["type_ab"].eq("B")].copy()
    type_b_top10 = (
        type_b.sort_values(["dd_swing_index", "kw_p_value", "section"], ascending=[False, True, True], kind="mergesort")
        .head(10)
        .copy()
    )
    type_b_playbook = analysis.type_b_playbook

    lines: list[str] = []
    lines.append("# 楽園蒲田店 DD×セクション スイング分析")
    lines.append("")
    lines.append("## 1. 手法概要・Type A/B分類基準")
    lines.append(f"- DB: `{db_path}`")
    lines.append(f"- 対象期間: {frame['date_dt'].min().date()} 〜 {frame['date_dt'].max().date()}")
    lines.append(f"- 元データ行数: {len(frame):,}")
    lines.append(f"- セクション数: {analysis.section_order['section'].nunique():,}")
    lines.append(f"- DD軸: 1-31")
    lines.append(f"- 既定イベントDD: `{sorted(EVENT_DDS)}`")
    lines.append(f"- 強ゾロ目( month == day ): `{STRONG_ZOROME}`")
    lines.append(f"- フィルタ: `games_normalized >= {DEFAULT_MIN_GAMES}`")
    lines.append(f"- KW検定: セクション内で DD 群を比較。`n < {DEFAULT_MIN_CELL_N}` の DD セルは除外")
    lines.append(f"- ε²: `H / (n - 1)`")
    lines.append("- Type A = DD別avg_diffの符号がほぼ一貫し、`dd_swing_index` と `residual_std` が低い恒常型")
    lines.append("- Type B = DD別avg_diffの振れ幅が大きい、または符号反転・局所的な突出が見える DD選択型")
    lines.append("- watching = サンプルが薄いが、複数DDで同じ方向が繰り返し見えるため要観察")
    lines.append("")
    lines.append("### 集計の前提")
    lines.append(f"- セクション定義は `eda/section_lateral_expansion.py` の Rakuen 座標読み込みを再利用")
    lines.append(f"- DD×セクションのフルマトリクスは `{31 * len(analysis.section_order):,}` セル")
    lines.append(f"- 有効セル( KW / swing の主対象 ) は `n >= {DEFAULT_MIN_CELL_N}`")
    lines.append("")
    lines.append("### Type A/B 判定の定量ルール")
    criteria = pd.DataFrame(
        [
            {"metric": "dominant_sign_rate", "threshold": ">= 0.70", "meaning": "valid DD の大半が同じ符号"},
            {"metric": "sign_change_count", "threshold": "<= 2", "meaning": "DD順に見た符号反転が少ない"},
            {"metric": "cell_avg_diff_std", "threshold": "<= median", "meaning": "全セクション中央値以下のばらつき"},
            {"metric": "dd_swing_index", "threshold": "<= median", "meaning": "DD間スイングが大きすぎない"},
            {
                "metric": "residual_std",
                "threshold": "<= median",
                "meaning": "セクション平均を引いた残差の散らばりが小さい",
            },
        ]
    )
    lines.append(_markdown_table(criteria, float_digits=4))
    lines.append("")

    lines.append("## 2. 全セクションのDDスイングランキング")
    ranking = section_metrics.loc[
        :,
        [
            "section_rank",
            "floor",
            "section",
            "section_size",
            "section_n",
            "valid_dd_n",
            "cell_coverage",
            "section_avg_diff",
            "section_hit_rate",
            "dd_swing_index",
            "cell_avg_diff_std",
            "residual_std",
            "dominant_sign_rate",
            "sign_change_count",
            "kw_p_value",
            "kw_epsilon_sq",
            "type_ab",
            "watching_flag",
            "type_reason",
        ],
    ].copy()
    ranking["section_hit_rate"] = ranking["section_hit_rate"].round(3)
    ranking["section_avg_diff"] = ranking["section_avg_diff"].round(3)
    lines.append(_markdown_table(ranking, float_digits=4))
    lines.append("")

    lines.append("## 3. Type A（恒常型）一覧")
    if type_a.empty:
        lines.append("No Type A sections.")
    else:
        type_a_display = type_a.loc[
            :,
            [
                "section_rank",
                "floor",
                "section",
                "section_size",
                "section_avg_diff",
                "section_hit_rate",
                "dd_swing_index",
                "residual_std",
                "dominant_sign_rate",
                "sign_change_count",
                "kw_p_value",
                "watching_flag",
                "type_reason",
            ],
        ].copy()
        type_a_display["section_hit_rate"] = type_a_display["section_hit_rate"].round(3)
        type_a_display["section_avg_diff"] = type_a_display["section_avg_diff"].round(3)
        lines.append(_markdown_table(type_a_display, float_digits=4))
    lines.append("")

    lines.append("## 4. Type B（DD選択型）トップ10と狙い目DD")
    if type_b_top10.empty:
        lines.append("No Type B sections.")
    else:
        type_b_top10_rows: list[dict[str, object]] = []
        event_responsive_lookup = (
            analysis.previous_event_responsive.set_index("section").to_dict("index")
            if not analysis.previous_event_responsive.empty
            else {}
        )
        for _, row in type_b_top10.iterrows():
            detail = matrix[(matrix["section"].eq(row["section"])) & (matrix["n"].ge(int(DEFAULT_MIN_CELL_N)))].copy()
            detail = detail.dropna(subset=["avg_diff", "hit_rate"]).copy()
            top5 = detail.sort_values(
                ["avg_diff", "hit_rate", "n", "dd"], ascending=[False, False, False, True], kind="mergesort"
            ).head(5)
            bottom5 = detail.sort_values(
                ["avg_diff", "hit_rate", "n", "dd"], ascending=[True, True, False, True], kind="mergesort"
            ).head(5)
            event_count_top = int(top5["is_event_dd"].sum())
            event_count_bottom = int(bottom5["is_event_dd"].sum())
            prev = event_responsive_lookup.get(row["section"], {})
            type_b_top10_rows.append(
                {
                    "section": row["section"],
                    "floor": row["floor"],
                    "section_size": int(row["section_size"]),
                    "dd_swing_index": float(row["dd_swing_index"]),
                    "kw_p_value": float(row["kw_p_value"]),
                    "kw_epsilon_sq": float(row["kw_epsilon_sq"]),
                    "dominant_sign_rate": float(row["dominant_sign_rate"]),
                    "sign_change_count": int(row["sign_change_count"]),
                    "target_dd_top5": ", ".join(_format_dd_cell_row(r) for _, r in top5.iterrows()),
                    "avoid_dd_bottom5": ", ".join(_format_dd_cell_row(r) for _, r in bottom5.iterrows()),
                    "target_event_dds": event_count_top,
                    "avoid_event_dds": event_count_bottom,
                    "prior_event_lift_pp": float(prev.get("event_lift_pp", float("nan"))),
                }
            )
        type_b_top10_table = pd.DataFrame(type_b_top10_rows)
        lines.append(_markdown_table(type_b_top10_table, float_digits=4))
    lines.append("")

    lines.append("## 5. ユーザー指摘区画の個別検証（1106-1115, 1130-1134, 3117-3120）")
    for section_name in ["1106-1115", "1130-1134", "3117-3120"]:
        lines.append(f"### {section_name}")
        detail = _section_detail_table(matrix, section_name)
        if detail.empty:
            lines.append("No rows.")
            lines.append("")
            continue
        summary_row = section_metrics[section_metrics["section"].eq(section_name)].copy()
        if not summary_row.empty:
            summary = summary_row.iloc[0]
            lines.append(
                f"- Type: `{summary['type_ab']}` / watching: `{bool(summary['watching_flag'])}` / "
                f"DD swing: `{float(summary['dd_swing_index']):.3f}` / KW p: `{float(summary['kw_p_value']):.6f}` / "
                f"ε²: `{float(summary['kw_epsilon_sq']):.6f}` / sign consistency: `{float(summary['dominant_sign_rate']):.3f}`"
            )
            lines.append(
                f"- Best DD: `{int(summary['best_dd'])}` ({float(summary['best_dd_avg_diff']):+.3f}) / "
                f"Worst DD: `{int(summary['worst_dd'])}` ({float(summary['worst_dd_avg_diff']):+.3f})"
            )
        lines.append(_markdown_table(detail.head(31), float_digits=4))
        lines.append("")
    lines.append("")

    lines.append("## 6. イベント日との整合性")
    event_alignment_rows: list[dict[str, object]] = []
    previous_lookup = (
        analysis.previous_event_responsive.set_index("section").to_dict("index")
        if not analysis.previous_event_responsive.empty
        else {}
    )
    for _, row in type_b_top10.iterrows():
        detail = matrix[(matrix["section"].eq(row["section"])) & (matrix["n"].ge(int(DEFAULT_MIN_CELL_N)))].copy()
        detail = detail.dropna(subset=["avg_diff", "hit_rate"]).copy()
        top5 = detail.sort_values(
            ["avg_diff", "hit_rate", "n", "dd"], ascending=[False, False, False, True], kind="mergesort"
        ).head(5)
        bottom5 = detail.sort_values(
            ["avg_diff", "hit_rate", "n", "dd"], ascending=[True, True, False, True], kind="mergesort"
        ).head(5)
        prev = previous_lookup.get(row["section"], {})
        event_alignment_rows.append(
            {
                "section": row["section"],
                "floor": row["floor"],
                "type_ab": row["type_ab"],
                "top5_event_dd_count": int(top5["is_event_dd"].sum()),
                "bottom5_event_dd_count": int(bottom5["is_event_dd"].sum()),
                "prior_event_lift_pp": float(prev.get("event_lift_pp", float("nan"))),
                "prior_event_n": int(prev.get("n", 0)) if prev else 0,
                "type_reason": row["type_reason"],
            }
        )
    event_alignment = pd.DataFrame(event_alignment_rows)
    if event_alignment.empty:
        lines.append("No Type B rows.")
    else:
        lines.append(
            "- 既存の whole-period event-responsive 分析は `step2_section_event_responsive.csv` の `event_lift_pp` で参照"
        )
        lines.append("- ここでは Type B の上位セクションについて、DDベースの狙い目に event DD がどれだけ混ざるかを確認")
        lines.append(_markdown_table(event_alignment, float_digits=4))
    lines.append("")

    lines.append("## 7. 総括")
    if not type_b.empty:
        best_b = type_b.sort_values(
            ["dd_swing_index", "kw_p_value", "section"], ascending=[False, True, True], kind="mergesort"
        ).iloc[0]
        lines.append(
            f"- 最も DD 選択性が強いのは `{best_b['section']}` で、DD swing は `{float(best_b['dd_swing_index']):.3f}`。"
            f" KW p は `{float(best_b['kw_p_value']):.6f}`、sign consistency は `{float(best_b['dominant_sign_rate']):.3f}`。"
        )
    if not type_a.empty:
        stable = type_a.sort_values(
            ["cell_avg_diff_std", "dd_swing_index", "section"], ascending=[True, True, True], kind="mergesort"
        ).iloc[0]
        lines.append(
            f"- 最も恒常的なのは `{stable['section']}` で、DD swing `{float(stable['dd_swing_index']):.3f}`、"
            f"残差標準偏差 `{float(stable['residual_std']):.3f}`。"
        )
    lines.append(
        "- Type A は「セクションを知っていれば十分」、Type B は「狙うDDを選ぶ価値がある」候補として切り分けた。"
    )
    lines.append("- ただし KW p が弱いセクションでも、複数 DD で同じ方向が繰り返されるものは watching として残した。")
    lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def build_outputs(db_path: Path, output_dir: Path, *, min_games: int, min_cell_n: int) -> RakuenSectionAnalysis:
    resolved_db_path = _resolve_db_path(db_path)
    raw, coords = _prepare_frame(resolved_db_path, min_games=min_games)
    section_order = _section_order(coords)
    matrix = _build_matrix(raw, section_order)
    section_metrics = _section_metrics(raw, matrix, min_cell_n=min_cell_n)
    section_metrics = _classify_sections(section_metrics)
    kw_significance = section_metrics.loc[
        :,
        [
            "section",
            "floor",
            "section_rank",
            "section_size",
            "section_n",
            "valid_dd_n",
            "kw_groups",
            "kw_samples",
            "kw_stat",
            "kw_p_value",
            "kw_epsilon_sq",
            "kw_dd_used",
            "kw_dd_skipped",
            "type_ab",
            "watching_flag",
            "type_reason",
        ],
    ].copy()
    kw_significance["kw_p_value"] = kw_significance["kw_p_value"].round(6)
    kw_significance["kw_epsilon_sq"] = kw_significance["kw_epsilon_sq"].round(6)
    kw_significance["kw_stat"] = kw_significance["kw_stat"].round(6)
    swing_ranking = section_metrics.loc[
        :,
        [
            "section_rank",
            "floor",
            "section",
            "section_min",
            "section_max",
            "section_size",
            "section_n",
            "valid_dd_n",
            "cell_coverage",
            "section_avg_diff",
            "section_hit_rate",
            "cell_avg_diff_mean",
            "cell_avg_diff_std",
            "cell_avg_diff_min",
            "cell_avg_diff_max",
            "dd_swing_index",
            "residual_mean",
            "residual_std",
            "residual_min",
            "residual_max",
            "residual_swing",
            "max_abs_residual",
            "positive_rate",
            "negative_rate",
            "dominant_sign_rate",
            "dominant_sign",
            "sign_change_count",
            "best_dd",
            "best_dd_avg_diff",
            "worst_dd",
            "worst_dd_avg_diff",
            "event_cell_n",
            "event_cell_avg_diff",
            "event_cell_hit_rate",
            "kw_groups",
            "kw_samples",
            "kw_stat",
            "kw_p_value",
            "kw_epsilon_sq",
            "type_ab",
            "watching_flag",
            "type_reason",
        ],
    ].copy()
    for col in [
        "section_avg_diff",
        "section_hit_rate",
        "cell_avg_diff_mean",
        "cell_avg_diff_std",
        "cell_avg_diff_min",
        "cell_avg_diff_max",
        "dd_swing_index",
        "residual_mean",
        "residual_std",
        "residual_min",
        "residual_max",
        "residual_swing",
        "max_abs_residual",
        "positive_rate",
        "negative_rate",
        "dominant_sign_rate",
        "best_dd_avg_diff",
        "worst_dd_avg_diff",
        "event_cell_avg_diff",
        "event_cell_hit_rate",
        "kw_stat",
        "kw_p_value",
        "kw_epsilon_sq",
        "cell_coverage",
    ]:
        swing_ranking[col] = pd.to_numeric(swing_ranking[col], errors="coerce").round(6)
    previous_event_responsive = _load_previous_event_responsive()
    type_b_playbook = _build_playbook(section_metrics, matrix, previous_event_responsive)
    output_dir.mkdir(parents=True, exist_ok=True)

    _write_csv(matrix, output_dir / "dd_section_matrix.csv")
    _write_csv(kw_significance, output_dir / "section_kw_significance.csv")
    _write_csv(swing_ranking, output_dir / "section_dd_swing_ranking.csv")
    _write_csv(type_b_playbook, output_dir / "type_b_playbook.csv")

    analysis = RakuenSectionAnalysis(
        raw=raw,
        coords=coords,
        matrix=matrix,
        section_metrics=section_metrics,
        kw_significance=kw_significance,
        swing_ranking=swing_ranking,
        type_b_playbook=type_b_playbook,
        previous_event_responsive=previous_event_responsive,
        section_order=section_order,
    )
    report = _build_report(analysis, resolved_db_path)
    (output_dir / "report.md").write_text(report, encoding="utf-8")
    return analysis


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Rakuen DD x section swing analysis")
    parser.add_argument("--db-path", type=Path, default=DEFAULT_DB_PATH, help="SQLite database path")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR, help="Output directory")
    parser.add_argument("--min-games", type=int, default=DEFAULT_MIN_GAMES, help="Minimum normalized games")
    parser.add_argument("--min-cell-n", type=int, default=DEFAULT_MIN_CELL_N, help="Minimum DD-cell sample count")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    analysis = build_outputs(
        Path(args.db_path),
        Path(args.output_dir),
        min_games=int(args.min_games),
        min_cell_n=int(args.min_cell_n),
    )
    print(f"[OK] rows after filter/join: {len(analysis.raw):,}")
    print(f"[OK] sections: {analysis.section_order['section'].nunique():,}")
    print(f"[OK] dd_section_matrix rows: {len(analysis.matrix):,}")
    print(f"[OK] section_kw_significance rows: {len(analysis.kw_significance):,}")
    print(f"[OK] section_dd_swing_ranking rows: {len(analysis.swing_ranking):,}")
    print(f"[OK] type_b_playbook rows: {len(analysis.type_b_playbook):,}")
    print(f"[OK] report saved: {Path(args.output_dir) / 'report.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
