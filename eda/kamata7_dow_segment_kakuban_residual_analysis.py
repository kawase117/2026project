from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import kruskal, ttest_1samp

if __package__ is None or __package__ == "":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ml.analysis.kamata_kakuban_section_residual_eda import (  # noqa: E402
    DEFAULT_MIN_GAMES_ANALYSIS,
    DEFAULT_MIN_SECTION_SIZE,
    SegmentSpec,
    _df_to_markdown,
    _expand_dual_kakuban,
    _prepare_segment_frame,
    _write_csv,
    infer_hall_name,
)
from ml.experiments.walkforward_scoring.scoring_model import load_coords_bundle  # noqa: E402


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = PROJECT_ROOT / "db" / "マルハンメガシティ2000-蒲田7.db"
DEFAULT_COORDS_2F = PROJECT_ROOT / "Heatmap" / "2F_floor_coordinates_kamata7.csv"
DEFAULT_COORDS_3F = PROJECT_ROOT / "Heatmap" / "3F_floor_coordinates_kamata7.csv"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "eda" / "reports" / "kamata7_dow_segment_kakuban_residual"
DEFAULT_REPORT_PATH = DEFAULT_OUTPUT_DIR / "summary_report.md"
DEFAULT_MIN_GAMES = 2000
TARGET_DATE = pd.Timestamp("2026-06-16")
WEEKDAY_LABELS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
KAKUBAN_GROUPS = [
    (1, 1, "K1"),
    (2, 2, "K2"),
    (3, 4, "K3-4"),
    (5, 9, "K5-9"),
    (10, 14, "K10-14"),
    (15, None, "K15+"),
]


@dataclass(frozen=True)
class RunConfig:
    db_path: Path
    coords_2f: Path
    coords_3f: Path
    hall_name_2f: str
    hall_name_3f: str


def _weekday_label(value: object) -> str:
    if pd.isna(value):
        return ""
    if isinstance(value, pd.Timestamp):
        return WEEKDAY_LABELS[value.dayofweek]
    text = str(value).strip()
    if text in WEEKDAY_LABELS:
        return text
    mapping = {
        "Monday": "Mon",
        "Tuesday": "Tue",
        "Wednesday": "Wed",
        "Thursday": "Thu",
        "Friday": "Fri",
        "Saturday": "Sat",
        "Sunday": "Sun",
    }
    return mapping.get(text, text[:1] if text else "")


def _bonferroni_adjust(p_values: pd.Series) -> pd.Series:
    numeric = pd.to_numeric(p_values, errors="coerce")
    out = pd.Series(np.nan, index=p_values.index, dtype=float)
    valid = numeric.dropna()
    if valid.empty:
        return out
    adjusted = np.minimum(valid.to_numpy(dtype=float) * len(valid), 1.0)
    out.loc[valid.index] = adjusted
    return out


def _safe_ttest_1samp(values: pd.Series, popmean: float = 0.0) -> tuple[float, float]:
    numeric = pd.to_numeric(values, errors="coerce").dropna().astype(float)
    if len(numeric) < 2 or numeric.nunique() < 2:
        return float("nan"), float("nan")
    try:
        result = ttest_1samp(numeric, popmean=popmean, nan_policy="omit")
    except ValueError:
        return float("nan"), float("nan")
    stat = float(result.statistic) if result.statistic is not None else float("nan")
    pval = float(result.pvalue) if result.pvalue is not None else float("nan")
    return stat, pval


def _safe_kruskal(groups: list[pd.Series]) -> float:
    clean = [pd.to_numeric(group, errors="coerce").dropna().astype(float) for group in groups if len(group.dropna()) > 0]
    if len(clean) < 2:
        return float("nan")
    try:
        return float(kruskal(*clean).pvalue)
    except ValueError:
        return float("nan")


def _kakuban_group(value: object) -> str:
    if pd.isna(value):
        return ""
    n = int(value)
    for start, end, label in KAKUBAN_GROUPS:
        if end is None:
            if n >= start:
                return label
        elif start <= n <= end:
            return label
    return ""


def _clean_base_frame(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    out["date"] = pd.to_datetime(out["date"], errors="coerce")
    out["machine_number"] = pd.to_numeric(out["machine_number"], errors="coerce")
    out["diff_coins_normalized"] = pd.to_numeric(out["diff_coins_normalized"], errors="coerce")
    out["games_normalized"] = pd.to_numeric(out["games_normalized"], errors="coerce")
    out = out.dropna(subset=["date", "machine_number", "diff_coins_normalized", "games_normalized"]).copy()
    out["machine_number"] = out["machine_number"].astype(int)
    out["date"] = out["date"].dt.normalize()
    out["mmdd"] = out["date"].dt.strftime("%m%d")
    out["weekday"] = out["date"].dt.dayofweek.map(lambda x: _weekday_label(WEEKDAY_LABELS[int(x)]))
    return out


def _attach_segment_columns(frame: pd.DataFrame, *, coords_2f: Path, coords_3f: Path) -> pd.DataFrame:
    coords = load_coords_bundle(str(coords_2f), str(coords_3f))[["machine_number", "floor", "lr"]].copy()
    coords["machine_number"] = pd.to_numeric(coords["machine_number"], errors="coerce").astype("Int64")
    merged = frame.merge(coords, on="machine_number", how="left", validate="m:1")
    merged["segment_floor"] = merged["section"].astype(str).str.slice(0, 1).map({"2": "2F", "3": "3F"})
    if "base_floor" in merged.columns:
        merged["segment_floor"] = merged["segment_floor"].fillna(merged["base_floor"])
    elif "floor_x" in merged.columns:
        merged["segment_floor"] = merged["segment_floor"].fillna(merged["floor_x"])
    elif "floor" in merged.columns:
        merged["segment_floor"] = merged["segment_floor"].fillna(merged["floor"])
    merged["segment_floor"] = merged["segment_floor"].astype(str)
    merged["segment_lr"] = merged["lr"].fillna("Unknown").astype(str)
    merged["segment6"] = (
        merged["segment_floor"].astype(str)
        + "_"
        + merged["segment_lr"].astype(str)
        + "_"
        + merged["machine_type_segment"].astype(str)
    )
    merged = merged[merged["segment_lr"].isin(["L", "R"])].copy()
    merged = merged[merged["segment_floor"].isin(["2F", "3F"])].copy()
    merged = merged[~merged["segment6"].str.contains("Unknown", na=False)].copy()
    return merged


def _build_run_frame(spec: SegmentSpec, *, min_games: int, min_section_size: int) -> pd.DataFrame:
    frame = _prepare_segment_frame(spec, min_games=min_games, min_section_size=min_section_size).copy()
    if frame.empty:
        return frame
    frame = _clean_base_frame(frame)
    frame = frame[frame["mmdd"].ne("0707")].copy()
    frame = frame[frame["machine_number"].ne(2026)].copy()
    frame = frame.dropna(subset=["section", "rank_from_min", "rank_from_max", "machine_type_segment"]).copy()
    frame["rank_from_min"] = pd.to_numeric(frame["rank_from_min"], errors="coerce").astype("Int64")
    frame["rank_from_max"] = pd.to_numeric(frame["rank_from_max"], errors="coerce").astype("Int64")
    frame["machine_type_segment"] = frame["machine_type_segment"].astype(str)
    if "floor" in frame.columns:
        frame["base_floor"] = frame["floor"].astype(str)
    frame = _attach_segment_columns(frame, coords_2f=DEFAULT_COORDS_2F, coords_3f=DEFAULT_COORDS_3F)
    frame["residual"] = pd.to_numeric(frame["residual"], errors="coerce")
    frame["residual_eligible"] = frame["residual_eligible"].astype(bool)
    return frame.reset_index(drop=True)


def _expand_kakuban(frame: pd.DataFrame, rank_basis: str) -> pd.DataFrame:
    work = _expand_dual_kakuban(frame).copy()
    work["kakuban"] = pd.to_numeric(work["kakuban"], errors="coerce").astype("Int64")
    work = work[work["kakuban"].notna()].copy()
    work["kakuban"] = work["kakuban"].astype(int)
    work["kakuban_group"] = work["kakuban"].map(_kakuban_group)
    work["rank_basis"] = rank_basis
    return work[work["kakuban_group"].ne("")].copy()


def _build_task1(frame: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    work = frame[frame["residual_eligible"] & frame["residual"].notna()].copy()
    if work.empty:
        empty_detail = pd.DataFrame(
            columns=["weekday", "segment6", "rank_basis", "kakuban_group", "n", "mean_residual", "median_residual", "std_residual", "mean_games"]
        )
        empty_kw = pd.DataFrame(
            columns=["weekday", "segment6", "rank_basis", "n_groups", "n_rows", "kruskal_p", "kruskal_q", "min_group_n", "max_group_n"]
        )
        return empty_detail, empty_kw

    detail_rows: list[dict[str, object]] = []
    kw_rows: list[dict[str, object]] = []
    for rank_basis in ("rank_from_min", "rank_from_max"):
        expanded = _expand_kakuban(work, rank_basis)
        if expanded.empty:
            continue
        for (weekday, segment6), block in expanded.groupby(["weekday", "segment6"], sort=True):
            groups: list[pd.Series] = []
            sizes: list[int] = []
            for kakuban_group, gdf in block.groupby("kakuban_group", sort=True):
                residual = pd.to_numeric(gdf["residual"], errors="coerce").dropna().astype(float)
                groups.append(residual)
                sizes.append(int(len(residual)))
                detail_rows.append(
                    {
                        "weekday": weekday,
                        "segment6": segment6,
                        "rank_basis": rank_basis,
                        "kakuban_group": kakuban_group,
                        "n": int(len(residual)),
                        "mean_residual": float(residual.mean()) if len(residual) else np.nan,
                        "median_residual": float(residual.median()) if len(residual) else np.nan,
                        "std_residual": float(residual.std(ddof=1)) if len(residual) > 1 else np.nan,
                        "mean_games": float(pd.to_numeric(gdf["games_normalized"], errors="coerce").mean()),
                    }
                )
            kw_rows.append(
                {
                    "weekday": weekday,
                    "segment6": segment6,
                    "rank_basis": rank_basis,
                    "n_groups": int(len(groups)),
                    "n_rows": int(len(block)),
                    "kruskal_p": _safe_kruskal(groups),
                    "min_group_n": int(min(sizes)) if sizes else 0,
                    "max_group_n": int(max(sizes)) if sizes else 0,
                }
            )

    detail = pd.DataFrame(detail_rows)
    kw = pd.DataFrame(kw_rows)
    if not kw.empty:
        kw["kruskal_q"] = np.nan
        for rank_basis, group_df in kw.groupby("rank_basis"):
            kw.loc[group_df.index, "kruskal_q"] = _bonferroni_adjust(group_df["kruskal_p"])
        kw = kw.sort_values(["rank_basis", "kruskal_q", "weekday", "segment6"], na_position="last").reset_index(drop=True)
    if not detail.empty:
        detail = detail.sort_values(["rank_basis", "weekday", "segment6", "kakuban_group"], na_position="last").reset_index(drop=True)
    return detail, kw


def _build_task2(frame: pd.DataFrame) -> pd.DataFrame:
    work = frame[frame["residual_eligible"] & frame["residual"].notna()].copy()
    if work.empty:
        return pd.DataFrame(
            columns=[
                "segment6",
                "rank_basis",
                "kakuban_group",
                "weekday",
                "n",
                "all_weekday_mean_residual",
                "weekday_mean_residual",
                "weekday_specific_effect",
                "t_stat",
                "p_value",
                "q_value",
                "significant",
            ]
        )

    rows: list[dict[str, object]] = []
    for rank_basis in ("rank_from_min", "rank_from_max"):
        expanded = _expand_kakuban(work, rank_basis)
        if expanded.empty:
            continue
        for (segment6, kakuban_group), block in expanded.groupby(["segment6", "kakuban_group"], sort=True):
            base = pd.to_numeric(block["residual"], errors="coerce").dropna().astype(float)
            if base.empty:
                continue
            base_mean = float(base.mean())
            adjusted = block.assign(adjusted_residual=pd.to_numeric(block["residual"], errors="coerce") - base_mean)
            for weekday, weekday_df in adjusted.groupby("weekday", sort=True):
                values = pd.to_numeric(weekday_df["adjusted_residual"], errors="coerce").dropna().astype(float)
                t_stat, p_value = _safe_ttest_1samp(values, 0.0)
                rows.append(
                    {
                        "segment6": segment6,
                        "rank_basis": rank_basis,
                        "kakuban_group": kakuban_group,
                        "weekday": weekday,
                        "n": int(len(values)),
                        "all_weekday_mean_residual": base_mean,
                        "weekday_mean_residual": float(pd.to_numeric(weekday_df["residual"], errors="coerce").mean()),
                        "weekday_specific_effect": float(values.mean()) if len(values) else np.nan,
                        "t_stat": t_stat,
                        "p_value": p_value,
                    }
                )

    out = pd.DataFrame(rows)
    if out.empty:
        return out
    out["q_value"] = np.nan
    for group_cols, group_df in out.groupby(["rank_basis", "segment6", "kakuban_group"]):
        out.loc[group_df.index, "q_value"] = _bonferroni_adjust(group_df["p_value"])
    out["significant"] = pd.to_numeric(out["q_value"], errors="coerce").lt(0.05)
    out = out.sort_values(["rank_basis", "segment6", "kakuban_group", "q_value", "weekday"], na_position="last").reset_index(drop=True)
    return out


def _build_task3(frame: pd.DataFrame) -> pd.DataFrame:
    work = frame[frame["residual_eligible"] & frame["residual"].notna()].copy()
    if work.empty:
        return pd.DataFrame(
            columns=[
                "target_date",
                "weekday",
                "machine_type_segment",
                "rank_basis",
                "kakuban_group",
                "n",
                "mean_residual",
                "median_residual",
                "std_residual",
                "t_stat",
                "p_value",
                "q_value",
            ]
        )

    work = work[work["date"].eq(TARGET_DATE)].copy()
    work = work[work["weekday"].eq("Tue")].copy()
    rows: list[dict[str, object]] = []
    for rank_basis in ("rank_from_min", "rank_from_max"):
        expanded = _expand_kakuban(work, rank_basis)
        if expanded.empty:
            continue
        focus = expanded[expanded["kakuban"].eq(6)].copy()
        if focus.empty:
            continue
        for machine_type_segment, block in focus.groupby("machine_type_segment", sort=True):
            values = pd.to_numeric(block["residual"], errors="coerce").dropna().astype(float)
            t_stat, p_value = _safe_ttest_1samp(values, 0.0)
            rows.append(
                {
                    "target_date": TARGET_DATE.strftime("%Y-%m-%d"),
                    "weekday": "Tue",
                    "machine_type_segment": machine_type_segment,
                    "rank_basis": rank_basis,
                    "kakuban_group": "K6",
                    "n": int(len(values)),
                    "mean_residual": float(values.mean()) if len(values) else np.nan,
                    "median_residual": float(values.median()) if len(values) else np.nan,
                    "std_residual": float(values.std(ddof=1)) if len(values) > 1 else np.nan,
                    "t_stat": t_stat,
                    "p_value": p_value,
                }
            )

    out = pd.DataFrame(rows)
    if out.empty:
        return out
    out["q_value"] = np.nan
    for machine_type_segment, group_df in out.groupby("machine_type_segment"):
        out.loc[group_df.index, "q_value"] = _bonferroni_adjust(group_df["p_value"])
    out = out.sort_values(["machine_type_segment", "rank_basis"], na_position="last").reset_index(drop=True)
    return out


def _sig_rows(df: pd.DataFrame, q_col: str) -> pd.DataFrame:
    if df.empty or q_col not in df.columns:
        return df.iloc[0:0].copy()
    return df[pd.to_numeric(df[q_col], errors="coerce").lt(0.05)].copy()


def _build_report(*, task1_detail: pd.DataFrame, task1_kw: pd.DataFrame, task2: pd.DataFrame, task3: pd.DataFrame) -> str:
    sig1 = _sig_rows(task1_kw, "kruskal_q")
    sig2 = _sig_rows(task2, "q_value")
    sig3 = _sig_rows(task3, "q_value")

    lines = [
        "# Kamata7 weekday x segment x kakuban residual report",
        "",
        "## Assumptions",
        "",
        f"- Residual = `diff_coins_normalized - section_mean`.",
        f"- Filter: `games_normalized >= {DEFAULT_MIN_GAMES}`, `7/7` excluded, `machine_number != 2026`.",
        "- `segment6 = floor + '_' + lr + '_' + classify_seg(machine_name)` where `floor` comes from the section prefix and `lr` is taken from the heatmap coordinates.",
        "- Bonferroni correction is applied within each task family.",
        "",
        "## Task 1",
        "",
        "Weekday x 6-segment x kakuban-group residual summary.",
        "",
        _df_to_markdown(task1_detail.head(60)),
        "",
        "### Task 1 KW tests",
        "",
        _df_to_markdown(sig1 if not sig1.empty else task1_kw.head(60)),
        "",
        "## Task 2",
        "",
        "Weekday-specific effect after subtracting the all-weekday mean residual inside each segment x kakuban-group.",
        "",
        _df_to_markdown(sig2 if not sig2.empty else task2.head(60)),
        "",
        "## Task 3",
        "",
        "Tuesday 2026-06-16 focus on kakuban 6.",
        "",
        _df_to_markdown(sig3 if not sig3.empty else task3.head(60)),
        "",
        "## Notes",
        "",
        "- If a table is empty, the filter path or sample size was too small for that slice.",
        "- `task1_kw_test.csv` and `task2_weekday_specific_effect.csv` use Bonferroni-adjusted q-values.",
    ]
    return "\n".join(lines).rstrip() + "\n"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Kamata7 weekday segment kakuban residual EDA.")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--coords-2f", dest="coords_2f", type=Path, default=DEFAULT_COORDS_2F)
    parser.add_argument("--coords-3f", dest="coords_3f", type=Path, default=DEFAULT_COORDS_3F)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--report-path", type=Path, default=DEFAULT_REPORT_PATH)
    parser.add_argument("--min-games", type=int, default=DEFAULT_MIN_GAMES)
    parser.add_argument("--min-section-size", type=int, default=DEFAULT_MIN_SECTION_SIZE)
    return parser


def run_analysis(*, config: RunConfig, output_dir: Path, report_path: Path, min_games: int, min_section_size: int) -> dict[str, pd.DataFrame]:
    output_dir.mkdir(parents=True, exist_ok=True)

    specs = [
        SegmentSpec(
            hall_slug="kamata7",
            hall_name=config.hall_name_2f,
            floor="2F",
            db_path=config.db_path,
            coords_path=config.coords_2f,
        ),
        SegmentSpec(
            hall_slug="kamata7",
            hall_name=config.hall_name_3f,
            floor="3F",
            db_path=config.db_path,
            coords_path=config.coords_3f,
        ),
    ]

    frames = []
    for spec in specs:
        frame = _build_run_frame(spec, min_games=min_games, min_section_size=min_section_size)
        if not frame.empty:
            frames.append(frame)
    combined = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()

    task1_detail, task1_kw = _build_task1(combined)
    task2 = _build_task2(combined)
    task3 = _build_task3(combined)

    _write_csv(task1_detail, output_dir / "task1_residual_dow_segment_kakuban.csv")
    _write_csv(task1_kw, output_dir / "task1_kw_test.csv")
    _write_csv(task2, output_dir / "task2_weekday_specific_effect.csv")
    _write_csv(task3, output_dir / "task3_tuesday_kaku6_residual.csv")

    report = _build_report(task1_detail=task1_detail, task1_kw=task1_kw, task2=task2, task3=task3)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(report, encoding="utf-8")

    return {
        "task1_detail": task1_detail,
        "task1_kw": task1_kw,
        "task2": task2,
        "task3": task3,
    }


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    config = RunConfig(
        db_path=args.db,
        coords_2f=args.coords_2f,
        coords_3f=args.coords_3f,
        hall_name_2f=infer_hall_name(args.coords_2f, floor="2F"),
        hall_name_3f=infer_hall_name(args.coords_3f, floor="3F"),
    )
    run_analysis(
        config=config,
        output_dir=args.output_dir,
        report_path=args.report_path,
        min_games=args.min_games,
        min_section_size=args.min_section_size,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
