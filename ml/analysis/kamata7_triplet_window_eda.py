from __future__ import annotations

import argparse
import math
import sqlite3
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

if __package__ is None or __package__ == "":
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from ml.analysis.kamata_weekday_event_axis_eda import (  # noqa: E402
    DEFAULT_COORDS_7_2F,
    DEFAULT_COORDS_7_3F,
    DEFAULT_DB_7,
    SegmentSpec,
    _build_segment_frame,
    infer_hall_name,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "ml" / "analysis" / "results" / "kamata7_triplet_window_eda"
DEFAULT_REPORT_PATH = DEFAULT_OUTPUT_DIR / "report.md"
WINDOW_SIZE_DEFAULT = 3
EDGE_RATIO_LEFT = 1 / 3
EDGE_RATIO_RIGHT = 2 / 3
EXCLUDED_MACHINE_NUMBERS = {2026}
EXCLUDED_DATE_KEYS = {"20250707"}


@dataclass(frozen=True)
class HallSpec:
    hall_slug: str
    hall_name: str
    floor: str
    db_path: Path
    coords_path: Path


def _resolve_default_db7() -> Path:
    candidates = [
        path
        for path in (PROJECT_ROOT / "db").glob("*蒲田7*.db")
        if path.is_file() and path.stat().st_size > 0
    ]
    if candidates:
        return sorted(candidates, key=lambda path: path.stat().st_size, reverse=True)[0]
    return Path(DEFAULT_DB_7)


def _load_day_type_frame(db_path: Path) -> pd.DataFrame:
    with sqlite3.connect(db_path) as conn:
        table_exists = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='daily_hall_summary' LIMIT 1"
        ).fetchone()
        if not table_exists:
            return pd.DataFrame(columns=["date", "weekday_nth", "day_of_week", "is_saturday"])

        columns = [row[1] for row in conn.execute("PRAGMA table_info(daily_hall_summary)")]
        select_cols = ["date"]
        if "weekday_nth" in columns:
            select_cols.append("weekday_nth")
        if "day_of_week" in columns:
            select_cols.append("day_of_week")

        frame = pd.read_sql_query(f"SELECT {', '.join(select_cols)} FROM daily_hall_summary", conn)

    if frame.empty:
        return pd.DataFrame(columns=["date", "weekday_nth", "day_of_week", "is_saturday"])

    work = frame.copy()
    work["date"] = pd.to_datetime(work["date"], format="%Y%m%d", errors="coerce")
    if "weekday_nth" not in work.columns:
        work["weekday_nth"] = pd.NA
    if "day_of_week" not in work.columns:
        work["day_of_week"] = pd.NA
    work["is_saturday"] = (
        work["weekday_nth"].astype(str).str.startswith("土", na=False)
        | work["day_of_week"].astype(str).eq("Sat")
        | work["date"].dt.dayofweek.eq(5)
    )
    work["date_key"] = work["date"].dt.strftime("%Y%m%d")
    return work.dropna(subset=["date"]).reset_index(drop=True)


def _build_saturday_date_keys(db_path: Path) -> set[str]:
    frame = _load_day_type_frame(db_path)
    if frame.empty:
        return set()
    return set(frame.loc[frame["is_saturday"], "date_key"].dropna().astype(str))


def _format_float(value: object, digits: int = 2) -> str:
    if pd.isna(value):
        return "nan"
    return f"{float(value):.{digits}f}"


def _safe_ttest_1samp(values: pd.Series) -> tuple[float, float]:
    numeric = pd.to_numeric(values, errors="coerce").dropna().astype(float)
    if len(numeric) < 2 or np.isclose(float(numeric.std(ddof=1)), 0.0):
        return float("nan"), float("nan")
    result = stats.ttest_1samp(numeric, popmean=0.0, alternative="greater")
    return float(result.statistic), float(result.pvalue)


def _safe_wilcoxon(values: pd.Series) -> tuple[float, float]:
    numeric = pd.to_numeric(values, errors="coerce").dropna().astype(float)
    if len(numeric) == 0 or np.allclose(numeric, 0.0) or np.isclose(float(numeric.std(ddof=1)), 0.0):
        return float("nan"), float("nan")
    try:
        result = stats.wilcoxon(numeric, alternative="greater", zero_method="wilcox")
        return float(result.statistic), float(result.pvalue)
    except ValueError:
        return float("nan"), float("nan")


def _section_size_group(section_size: int) -> str:
    if section_size <= 8:
        return "small"
    if section_size <= 14:
        return "medium"
    return "large"


def _position_bin(relative_start: float) -> str:
    if relative_start <= EDGE_RATIO_LEFT:
        return "left_edge"
    if relative_start <= EDGE_RATIO_RIGHT:
        return "middle"
    return "right_edge"


def _build_hall_specs(
    *,
    db_path: Path,
    coords_2f: Path,
    coords_3f: Path,
) -> list[HallSpec]:
    return [
        HallSpec(
            hall_slug="kamata7",
            hall_name=infer_hall_name(coords_2f, floor="2F"),
            floor="2F",
            db_path=db_path,
            coords_path=coords_2f,
        ),
        HallSpec(
            hall_slug="kamata7",
            hall_name=infer_hall_name(coords_3f, floor="3F"),
            floor="3F",
            db_path=db_path,
            coords_path=coords_3f,
        ),
    ]


def _build_segment_source_frame(spec: HallSpec, *, min_games: int = 0) -> pd.DataFrame:
    frame = _build_segment_frame(
        SegmentSpec(
            hall_slug=spec.hall_slug,
            hall_name=spec.hall_name,
            floor=spec.floor,
            db_path=spec.db_path,
            coords_path=spec.coords_path,
        )
    ).copy()
    if frame.empty:
        return frame

    frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
    frame["rank_from_min"] = pd.to_numeric(frame["rank_from_min"], errors="coerce")
    frame["rank_from_max"] = pd.to_numeric(frame["rank_from_max"], errors="coerce")
    frame["diff_coins_normalized"] = pd.to_numeric(frame["diff_coins_normalized"], errors="coerce")
    frame["games_normalized"] = pd.to_numeric(frame["games_normalized"], errors="coerce")
    frame["section"] = frame["section"].fillna("unknown").astype(str)
    frame["segment_key"] = frame["segment_key"].astype(str)
    frame = frame.dropna(
        subset=[
            "date",
            "segment_key",
            "section",
            "rank_from_min",
            "diff_coins_normalized",
            "games_normalized",
            "machine_number",
        ]
    ).copy()
    frame["rank_from_min"] = frame["rank_from_min"].astype(int)
    frame["rank_from_max"] = frame["rank_from_max"].astype(int)
    frame["machine_number"] = pd.to_numeric(frame["machine_number"], errors="coerce").astype(int)
    frame["date_key"] = frame["date"].dt.strftime("%Y%m%d")
    frame = frame[~frame["machine_number"].isin(EXCLUDED_MACHINE_NUMBERS)].copy()
    frame = frame[~frame["date_key"].isin(EXCLUDED_DATE_KEYS)].copy()
    frame = frame[frame["games_normalized"].ge(int(min_games))].copy()
    return frame.reset_index(drop=True)


def _build_all_segment_frames(
    *,
    db_path: Path,
    coords_2f: Path,
    coords_3f: Path,
    min_games: int = 0,
) -> pd.DataFrame:
    parts: list[pd.DataFrame] = []
    for spec in _build_hall_specs(db_path=db_path, coords_2f=coords_2f, coords_3f=coords_3f):
        part = _build_segment_source_frame(spec, min_games=min_games)
        if not part.empty:
            parts.append(part)
    if not parts:
        return pd.DataFrame()
    return pd.concat(parts, ignore_index=True)


def build_triplet_window_frame(frame: pd.DataFrame, window_size: int = WINDOW_SIZE_DEFAULT) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame(
            columns=[
                "date",
                "segment_key",
                "floor",
                "section",
                "section_size",
                "section_size_group",
                "window_size",
                "window_start_rank",
                "window_end_rank",
                "window_center_rank",
                "window_position_ratio",
                "start_position_bin",
                "distance_to_nearest_edge",
                "touches_edge",
                "near_edge_band",
                "window_machine_numbers",
                "window_machine_names",
                "window_sum_diff",
                "window_mean_diff",
                "window_sum_games",
                "window_mean_games",
                "section_sum_diff",
                "section_mean_diff",
                "section_sum_games",
                "section_mean_games",
                "window_excess",
            ]
        )

    work = frame.copy()
    work["date"] = pd.to_datetime(work["date"], errors="coerce")
    work["rank_from_min"] = pd.to_numeric(work["rank_from_min"], errors="coerce")
    work["diff_coins_normalized"] = pd.to_numeric(work["diff_coins_normalized"], errors="coerce")
    work["games_normalized"] = pd.to_numeric(work["games_normalized"], errors="coerce")
    work = work.dropna(
        subset=[
            "date",
            "segment_key",
            "floor",
            "section",
            "rank_from_min",
            "diff_coins_normalized",
            "games_normalized",
        ]
    ).copy()
    work["rank_from_min"] = work["rank_from_min"].astype(int)
    work["section"] = work["section"].astype(str)
    work["segment_key"] = work["segment_key"].astype(str)
    work["machine_number"] = pd.to_numeric(work["machine_number"], errors="coerce").astype(int)

    rows: list[dict[str, object]] = []
    group_cols = ["segment_key", "floor", "section", "date"]
    for (segment_key, floor, section, date), group in work.groupby(group_cols, dropna=False, sort=True):
        ordered = group.sort_values(["rank_from_min", "machine_number"]).reset_index(drop=True)
        section_size = int(ordered["machine_number"].nunique())
        if section_size < window_size:
            continue

        section_sum_diff = float(ordered["diff_coins_normalized"].sum())
        section_mean_diff = float(ordered["diff_coins_normalized"].mean())
        section_sum_games = float(ordered["games_normalized"].sum())
        section_mean_games = float(ordered["games_normalized"].mean())
        section_sd_diff = float(ordered["diff_coins_normalized"].std(ddof=1)) if len(ordered) >= 2 else float("nan")

        for start in range(0, section_size - window_size + 1):
            window = ordered.iloc[start : start + window_size].copy()
            window_sum_diff = float(window["diff_coins_normalized"].sum())
            window_mean_diff = float(window["diff_coins_normalized"].mean())
            window_sum_games = float(window["games_normalized"].sum())
            window_mean_games = float(window["games_normalized"].mean())
            start_rank = int(window.iloc[0]["rank_from_min"])
            end_rank = int(window.iloc[-1]["rank_from_min"])
            center_rank = float(window["rank_from_min"].mean())
            relative_start = 0.0 if section_size == window_size else start / (section_size - window_size)
            distance_to_nearest_edge = int(min(start_rank - 1, section_size - end_rank))
            row = {
                "date": date,
                "segment_key": segment_key,
                "floor": floor,
                "section": section,
                "section_size": section_size,
                "section_size_group": _section_size_group(section_size),
                "section_sd_diff": section_sd_diff,
                "window_size": window_size,
                "window_start_rank": start_rank,
                "window_end_rank": end_rank,
                "window_center_rank": center_rank,
                "window_position_ratio": float(relative_start),
                "start_position_bin": _position_bin(float(relative_start)),
                "distance_to_nearest_edge": distance_to_nearest_edge,
                "touches_edge": distance_to_nearest_edge == 0,
                "near_edge_band": distance_to_nearest_edge <= 1,
                "window_machine_numbers": ",".join(str(int(value)) for value in window["machine_number"].tolist()),
                "window_machine_names": ",".join(str(value) for value in window["machine_name"].tolist()),
                "window_sum_diff": window_sum_diff,
                "window_mean_diff": window_mean_diff,
                "window_sum_games": window_sum_games,
                "window_mean_games": window_mean_games,
                "section_sum_diff": section_sum_diff,
                "section_mean_diff": section_mean_diff,
                "section_sum_games": section_sum_games,
                "section_mean_games": section_mean_games,
                "window_excess": window_mean_diff - section_mean_diff,
            }
            rows.append(row)

    out = pd.DataFrame(rows)
    if out.empty:
        return out
    out["section_size"] = out["section_size"].astype(int)
    out["window_size"] = out["window_size"].astype(int)
    out["window_start_rank"] = out["window_start_rank"].astype(int)
    out["window_end_rank"] = out["window_end_rank"].astype(int)
    out["distance_to_nearest_edge"] = out["distance_to_nearest_edge"].astype(int)
    out["touches_edge"] = out["touches_edge"].astype(bool)
    out["near_edge_band"] = out["near_edge_band"].astype(bool)
    out["date"] = pd.to_datetime(out["date"], errors="coerce").dt.strftime("%Y-%m-%d")
    return out.sort_values(["segment_key", "date", "section", "window_start_rank"]).reset_index(drop=True)


def summarize_segment_windows(window_frame: pd.DataFrame) -> pd.DataFrame:
    columns = [
        "segment_key",
        "n_windows",
        "n_dates",
        "n_sections",
        "mean_window_diff",
        "median_window_diff",
        "mean_excess",
        "median_excess",
        "sd_excess",
        "positive_excess_rate",
        "corner_window_rate",
        "near_edge_rate",
        "mean_start_ratio",
        "mean_distance_to_edge",
        "t_stat",
        "t_pvalue",
        "wilcoxon_stat",
        "wilcoxon_pvalue",
        "corner_mean_excess",
        "interior_mean_excess",
        "corner_minus_interior",
        "corner_vs_interior_pvalue",
        "mde_95_at_n20",
        "mde_95_at_n50",
        "required_windows_for_plus100_at_95pct",
    ]
    if window_frame.empty:
        return pd.DataFrame(columns=columns)

    rows: list[dict[str, object]] = []
    for segment_key, group in window_frame.groupby("segment_key", dropna=False, sort=True):
        excess = pd.to_numeric(group["window_excess"], errors="coerce").dropna().astype(float)
        window_diff = pd.to_numeric(group["window_mean_diff"], errors="coerce").dropna().astype(float)
        corner = group[group["touches_edge"]]
        interior = group[~group["touches_edge"]]
        t_stat, t_pvalue = _safe_ttest_1samp(excess)
        wilcoxon_stat, wilcoxon_pvalue = _safe_wilcoxon(excess)
        sd_excess = float(excess.std(ddof=1)) if len(excess) >= 2 else float("nan")
        corner_excess = pd.to_numeric(corner["window_excess"], errors="coerce").dropna().astype(float)
        interior_excess = pd.to_numeric(interior["window_excess"], errors="coerce").dropna().astype(float)
        if len(corner_excess) and len(interior_excess):
            try:
                _u_stat, corner_vs_interior_pvalue = stats.mannwhitneyu(
                    corner_excess,
                    interior_excess,
                    alternative="greater",
                )
                corner_vs_interior_pvalue = float(corner_vs_interior_pvalue)
            except ValueError:
                corner_vs_interior_pvalue = float("nan")
        else:
            corner_vs_interior_pvalue = float("nan")

        mde_95_at_n20 = 1.96 * sd_excess / math.sqrt(20) if not pd.isna(sd_excess) else float("nan")
        mde_95_at_n50 = 1.96 * sd_excess / math.sqrt(50) if not pd.isna(sd_excess) else float("nan")
        required_windows_for_plus100_at_95pct = (
            (1.96 * sd_excess / 100.0) ** 2 if not pd.isna(sd_excess) else float("nan")
        )
        rows.append(
            {
                "segment_key": segment_key,
                "n_windows": int(len(group)),
                "n_dates": int(group["date"].nunique()),
                "n_sections": int(group["section"].nunique()),
                "mean_window_diff": float(window_diff.mean()) if len(window_diff) else float("nan"),
                "median_window_diff": float(window_diff.median()) if len(window_diff) else float("nan"),
                "mean_excess": float(excess.mean()) if len(excess) else float("nan"),
                "median_excess": float(excess.median()) if len(excess) else float("nan"),
                "sd_excess": sd_excess,
                "positive_excess_rate": float((excess > 0).mean() * 100) if len(excess) else float("nan"),
                "corner_window_rate": float(group["touches_edge"].mean() * 100),
                "near_edge_rate": float(group["near_edge_band"].mean() * 100),
                "mean_start_ratio": float(pd.to_numeric(group["window_position_ratio"], errors="coerce").mean()),
                "mean_distance_to_edge": float(pd.to_numeric(group["distance_to_nearest_edge"], errors="coerce").mean()),
                "t_stat": t_stat,
                "t_pvalue": t_pvalue,
                "wilcoxon_stat": wilcoxon_stat,
                "wilcoxon_pvalue": wilcoxon_pvalue,
                "corner_mean_excess": float(corner_excess.mean()) if len(corner_excess) else float("nan"),
                "interior_mean_excess": float(interior_excess.mean()) if len(interior_excess) else float("nan"),
                "corner_minus_interior": (
                    float(corner_excess.mean() - interior_excess.mean())
                    if len(corner_excess) and len(interior_excess)
                    else float("nan")
                ),
                "corner_vs_interior_pvalue": corner_vs_interior_pvalue,
                "mde_95_at_n20": mde_95_at_n20,
                "mde_95_at_n50": mde_95_at_n50,
                "required_windows_for_plus100_at_95pct": required_windows_for_plus100_at_95pct,
            }
        )
    return pd.DataFrame(rows).sort_values("segment_key").reset_index(drop=True)


def summarize_start_position_bins(window_frame: pd.DataFrame) -> pd.DataFrame:
    columns = [
        "segment_key",
        "start_position_bin",
        "n_windows",
        "share_windows",
        "mean_window_excess",
        "median_window_excess",
        "mean_start_ratio",
        "corner_rate",
    ]
    if window_frame.empty:
        return pd.DataFrame(columns=columns)

    rows: list[dict[str, object]] = []
    total_windows_by_segment = window_frame.groupby("segment_key")["segment_key"].count().to_dict()
    for (segment_key, start_position_bin), group in window_frame.groupby(["segment_key", "start_position_bin"], dropna=False, sort=True):
        total = int(total_windows_by_segment.get(segment_key, len(window_frame)))
        excess = pd.to_numeric(group["window_excess"], errors="coerce").dropna().astype(float)
        rows.append(
            {
                "segment_key": segment_key,
                "start_position_bin": start_position_bin,
                "n_windows": int(len(group)),
                "share_windows": float(len(group) / total * 100) if total else float("nan"),
                "mean_window_excess": float(excess.mean()) if len(excess) else float("nan"),
                "median_window_excess": float(excess.median()) if len(excess) else float("nan"),
                "mean_start_ratio": float(pd.to_numeric(group["window_position_ratio"], errors="coerce").mean()),
                "corner_rate": float(group["touches_edge"].mean() * 100),
            }
        )
    out = pd.DataFrame(rows)
    if out.empty:
        return pd.DataFrame(columns=columns)
    out["start_position_bin"] = pd.Categorical(
        out["start_position_bin"],
        categories=["left_edge", "middle", "right_edge"],
        ordered=True,
    )
    return out.sort_values(["segment_key", "start_position_bin"]).reset_index(drop=True)


def summarize_weekday_comparison(
    saturday_window_frame: pd.DataFrame,
    non_saturday_window_frame: pd.DataFrame,
) -> pd.DataFrame:
    columns = [
        "segment_key",
        "saturday_n_windows",
        "saturday_mean_excess",
        "saturday_median_excess",
        "non_saturday_n_windows",
        "non_saturday_mean_excess",
        "non_saturday_median_excess",
        "mean_excess_gap",
        "mannwhitney_u_stat",
        "mannwhitney_pvalue",
    ]
    if saturday_window_frame.empty and non_saturday_window_frame.empty:
        return pd.DataFrame(columns=columns)

    segment_keys = sorted(
        set(pd.Series(saturday_window_frame.get("segment_key", pd.Series(dtype="object"))).dropna().astype(str))
        | set(pd.Series(non_saturday_window_frame.get("segment_key", pd.Series(dtype="object"))).dropna().astype(str))
    )
    rows: list[dict[str, object]] = []
    for segment_key in segment_keys:
        saturday_excess = pd.to_numeric(
            saturday_window_frame.loc[saturday_window_frame["segment_key"].eq(segment_key), "window_excess"],
            errors="coerce",
        ).dropna().astype(float)
        non_saturday_excess = pd.to_numeric(
            non_saturday_window_frame.loc[non_saturday_window_frame["segment_key"].eq(segment_key), "window_excess"],
            errors="coerce",
        ).dropna().astype(float)
        if len(saturday_excess) and len(non_saturday_excess):
            try:
                mannwhitney_u_stat, mannwhitney_pvalue = stats.mannwhitneyu(
                    saturday_excess,
                    non_saturday_excess,
                    alternative="greater",
                )
                mannwhitney_u_stat = float(mannwhitney_u_stat)
                mannwhitney_pvalue = float(mannwhitney_pvalue)
            except ValueError:
                mannwhitney_u_stat = float("nan")
                mannwhitney_pvalue = float("nan")
        else:
            mannwhitney_u_stat = float("nan")
            mannwhitney_pvalue = float("nan")
        rows.append(
            {
                "segment_key": segment_key,
                "saturday_n_windows": int(len(saturday_excess)),
                "saturday_mean_excess": float(saturday_excess.mean()) if len(saturday_excess) else float("nan"),
                "saturday_median_excess": float(saturday_excess.median()) if len(saturday_excess) else float("nan"),
                "non_saturday_n_windows": int(len(non_saturday_excess)),
                "non_saturday_mean_excess": float(non_saturday_excess.mean()) if len(non_saturday_excess) else float("nan"),
                "non_saturday_median_excess": float(non_saturday_excess.median()) if len(non_saturday_excess) else float("nan"),
                "mean_excess_gap": (
                    float(saturday_excess.mean() - non_saturday_excess.mean())
                    if len(saturday_excess) and len(non_saturday_excess)
                    else float("nan")
                ),
                "mannwhitney_u_stat": mannwhitney_u_stat,
                "mannwhitney_pvalue": mannwhitney_pvalue,
            }
        )
    out = pd.DataFrame(rows)
    if out.empty:
        return pd.DataFrame(columns=columns)
    return out.sort_values("segment_key").reset_index(drop=True)


def build_report(
    *,
    window_frame: pd.DataFrame,
    segment_summary: pd.DataFrame,
    position_summary: pd.DataFrame,
    comparison_summary: pd.DataFrame,
) -> str:
    lines: list[str] = [
        "# Kamata7 3台連続ウィンドウ分析（土曜限定）",
        "",
        "## 前提",
        "- 対象は `machine_detailed_results` の閉店後最終実績のみ。",
        "- 土曜抽出は `daily_hall_summary` の `weekday_nth` 優先、`day_of_week='Sat'` と日付曜日のフォールバックも併用。",
        "- 途中経過データは存在しないため、1000G時点の実測検出は扱わない。",
        "- 3台連続は各セクション内の `rank_from_min` 順で sliding window(size=3) を作成。",
        "- 鉄台 2026 と 2025-07-07 は除外済み。",
        "",
        "## データ概要",
        f"- window rows: {len(window_frame):,}",
        f"- segments: {window_frame['segment_key'].nunique() if not window_frame.empty else 0}",
        f"- sections: {window_frame[['segment_key', 'section']].drop_duplicates().shape[0] if not window_frame.empty else 0}",
        "",
        "## 1. 連続3台の差枚優位性",
        "各ウィンドウの `window_mean_diff - section_mean_diff` を 0 に対して t検定 / Wilcoxon で検定。",
        "",
        segment_summary.to_string(index=False) if not segment_summary.empty else "No rows.",
        "",
        "## 2. 起点位置分析",
        "起点位置は `window_start_rank` をセクションサイズで 3分割した bin で可視化。",
        "left_edge は角番寄り、middle は中腹、right_edge は反対側の角番寄り。",
        "",
        position_summary.to_string(index=False) if not position_summary.empty else "No rows.",
        "",
        "## 3. 土曜 vs 非土曜比較",
        "土曜の3台連続が曜日固有のシグナルかを確認するため、非土曜（月〜金・日）と `window_excess` を比較。",
        "",
        comparison_summary.to_string(index=False) if not comparison_summary.empty else "No rows.",
        "",
        "## 4. 理論メモ",
        "- 1ウィンドウあたりのノイズは `sd_excess` で表現できる。",
        "- +100枚の差を 95% 水準で検出するための必要ウィンドウ数は `((1.96 * sd_excess) / 100)^2`。",
        "- 水曜末尾との比較も同じ式で行える。必要サンプル数は分散の二乗に比例するため、",
        "  3台連続の分散が大きいほど検出は難しく、逆に小さいほど少数サンプルで見える。",
        "",
    ]
    return "\n".join(lines).rstrip() + "\n"


def write_outputs(
    *,
    output_dir: Path,
    window_frame: pd.DataFrame,
    segment_summary: pd.DataFrame,
    position_summary: pd.DataFrame,
    comparison_summary: pd.DataFrame,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    window_frame.to_csv(output_dir / "triplet_window_detail.csv", index=False, encoding="utf-8-sig")
    segment_summary.to_csv(output_dir / "triplet_window_segment_summary.csv", index=False, encoding="utf-8-sig")
    position_summary.to_csv(output_dir / "triplet_window_position_summary.csv", index=False, encoding="utf-8-sig")
    comparison_summary.to_csv(output_dir / "triplet_window_weekday_compare.csv", index=False, encoding="utf-8-sig")
    (output_dir / "report.md").write_text(
        build_report(
            window_frame=window_frame,
            segment_summary=segment_summary,
            position_summary=position_summary,
            comparison_summary=comparison_summary,
        ),
        encoding="utf-8",
    )


def run_analysis(
    *,
    db_path: Path = Path(DEFAULT_DB_7),
    coords_2f: Path = Path(DEFAULT_COORDS_7_2F),
    coords_3f: Path = Path(DEFAULT_COORDS_7_3F),
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    min_games: int = 0,
    window_size: int = WINDOW_SIZE_DEFAULT,
) -> dict[str, pd.DataFrame]:
    saturday_date_keys = _build_saturday_date_keys(db_path)
    base_frame = _build_all_segment_frames(
        db_path=db_path,
        coords_2f=coords_2f,
        coords_3f=coords_3f,
        min_games=min_games,
    )
    if base_frame.empty:
        saturday_base_frame = base_frame.copy()
        non_saturday_base_frame = base_frame.copy()
    else:
        work = base_frame.copy()
        work["date_key"] = pd.to_datetime(work["date"], errors="coerce").dt.strftime("%Y%m%d")
        saturday_base_frame = work[work["date_key"].isin(saturday_date_keys)].copy()
        non_saturday_base_frame = work[~work["date_key"].isin(saturday_date_keys)].copy()

    window_frame = build_triplet_window_frame(saturday_base_frame, window_size=window_size)
    non_saturday_window_frame = build_triplet_window_frame(non_saturday_base_frame, window_size=window_size)
    segment_summary = summarize_segment_windows(window_frame)
    position_summary = summarize_start_position_bins(window_frame)
    comparison_summary = summarize_weekday_comparison(window_frame, non_saturday_window_frame)
    write_outputs(
        output_dir=output_dir,
        window_frame=window_frame,
        segment_summary=segment_summary,
        position_summary=position_summary,
        comparison_summary=comparison_summary,
    )
    return {
        "base_frame": base_frame,
        "window_frame": window_frame,
        "non_saturday_window_frame": non_saturday_window_frame,
        "segment_summary": segment_summary,
        "position_summary": position_summary,
        "comparison_summary": comparison_summary,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Kamata7 3台連続ウィンドウ分析")
    parser.add_argument("--db-path", type=Path, default=Path(DEFAULT_DB_7), help="Path to the Kamata7 SQLite DB")
    parser.add_argument("--coords-2f", type=Path, default=Path(DEFAULT_COORDS_7_2F), help="2F coordinates CSV")
    parser.add_argument("--coords-3f", type=Path, default=Path(DEFAULT_COORDS_7_3F), help="3F coordinates CSV")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR, help="Output directory")
    parser.add_argument("--min-games", type=int, default=0, help="Optional minimum games filter")
    parser.add_argument("--window-size", type=int, default=WINDOW_SIZE_DEFAULT, help="Sliding window size")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    result = run_analysis(
        db_path=args.db_path,
        coords_2f=args.coords_2f,
        coords_3f=args.coords_3f,
        output_dir=args.output_dir,
        min_games=args.min_games,
        window_size=args.window_size,
    )
    print(f"Saved: {args.output_dir / 'report.md'}")
    print(f"Rows: {len(result['window_frame'])}")
    print(f"Segments: {result['segment_summary']['segment_key'].nunique() if not result['segment_summary'].empty else 0}")


if __name__ == "__main__":
    main()
