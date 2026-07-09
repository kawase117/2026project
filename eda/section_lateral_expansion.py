from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ml.experiments.walkforward_scoring.scoring_model import classify_seg  # noqa: E402
from ml.experiments.walkforward_scoring.walk_forward_engine import load_machine_data  # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
DEFAULT_OUTPUT_DIR = SCRIPT_DIR / "results" / "section_lateral_expansion"
DEFAULT_WINDOW_DAYS = 90
DEFAULT_EVAL_DAYS = 60
DEFAULT_MIN_GAMES = 1000
DEFAULT_TOP_KS = (1, 3, 5, 10)
DEFAULT_TOP_MACHINES_PER_SECTION = 5
KAMATA1_MIN_GAMES_SENSITIVITY = (1000, 2000, 3000)


@dataclass(frozen=True)
class HallConfig:
    label: str
    db_path: Path
    coords_paths: tuple[Path, ...]
    exclude_machine: int | None
    exclude_mmdd: str | None
    event_dds: frozenset[int]


HALL_CONFIGS: dict[str, HallConfig] = {
    "kamata7": HallConfig(
        label="蒲田7",
        db_path=PROJECT_ROOT / "db" / "マルハンメガシティ2000-蒲田7.db",
        coords_paths=(
            PROJECT_ROOT / "Heatmap" / "2F_floor_coordinates_kamata7.csv",
            PROJECT_ROOT / "Heatmap" / "3F_floor_coordinates_kamata7.csv",
        ),
        exclude_machine=2026,
        exclude_mmdd="0707",
        event_dds=frozenset({1, 7, 11, 17, 21, 22, 27, 31}),
    ),
    "kamata1": HallConfig(
        label="蒲田1",
        db_path=PROJECT_ROOT / "db" / "マルハンメガシティ2000-蒲田1.db",
        coords_paths=(PROJECT_ROOT / "Heatmap" / "2F_floor_coordinates_kamata1.csv",),
        exclude_machine=None,
        exclude_mmdd=None,
        event_dds=frozenset({1, 7, 11, 17, 21, 22, 27, 31}),
    ),
    "rakuen": HallConfig(
        label="楽園蒲田店",
        db_path=PROJECT_ROOT / "db" / "楽園蒲田店.db",
        coords_paths=(
            PROJECT_ROOT / "Heatmap" / "honkan1F_floor_coordinates_rakuen.csv",
            PROJECT_ROOT / "Heatmap" / "honkan2F_floor_coordinates_rakuen.csv",
            PROJECT_ROOT / "Heatmap" / "honkan3F_floor_coordinates_rakuen.csv",
            PROJECT_ROOT / "Heatmap" / "shinkan1F_floor_coordinates_rakuen.csv",
            PROJECT_ROOT / "Heatmap" / "shinkan2F_floor_coordinates_rakuen.csv",
        ),
        exclude_machine=None,
        exclude_mmdd=None,
        event_dds=frozenset({1, 4, 7, 14, 17, 24, 27, 30}),
    ),
    "mitoya": HallConfig(
        label="みとや大森町店",
        db_path=PROJECT_ROOT / "db" / "みとや大森町店.db",
        coords_paths=(PROJECT_ROOT / "Heatmap" / "mitoya_omorimachi_floor_coordinates.csv",),
        exclude_machine=None,
        exclude_mmdd=None,
        event_dds=frozenset({1, 4, 7, 14, 17, 24, 27, 30}),
    ),
}

HALL_ORDER = tuple(HALL_CONFIGS.keys())
HALL_SORT_INDEX = {cfg.label: idx for idx, cfg in enumerate(HALL_CONFIGS.values())}


@dataclass(frozen=True)
class HallArtifacts:
    hall: str
    label: str
    frame: pd.DataFrame
    coords: pd.DataFrame
    section_eval: pd.DataFrame
    summary: pd.DataFrame
    mini_audit: pd.DataFrame
    top5_changes: int
    top3_changes: int


def _format_value(value: object, *, float_digits: int = 3) -> str:
    if value is None or pd.isna(value):
        return ""
    if isinstance(value, (float, np.floating)):
        return f"{float(value):.{float_digits}f}"
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
        lines.append(
            "| " + " | ".join(_format_value(row[col], float_digits=float_digits) for col in work.columns) + " |"
        )
    return "\n".join(lines)


def _select_eval_dates(frame: pd.DataFrame, *, eval_days: int, day_filter: frozenset[int] | None = None) -> pd.Index:
    unique_dates = pd.Index(sorted(pd.Timestamp(value).normalize() for value in frame["date_dt"].dropna().unique()))
    if day_filter is not None:
        unique_dates = unique_dates[unique_dates.day.isin(day_filter)]
    return unique_dates[-int(eval_days) :] if len(unique_dates) > int(eval_days) else unique_dates


def _parse_int_list(raw: str) -> tuple[int, ...]:
    values = [part.strip() for part in str(raw).split(",") if part.strip()]
    return tuple(int(value) for value in values)


def _parse_hall_list(raw: str) -> tuple[str, ...]:
    value = str(raw).strip().lower()
    if value in {"", "all"}:
        return HALL_ORDER
    halls = [part.strip().lower() for part in raw.split(",") if part.strip()]
    invalid = [hall for hall in halls if hall not in HALL_CONFIGS]
    if invalid:
        raise ValueError(f"unknown hall(s): {', '.join(invalid)}")
    return tuple(dict.fromkeys(halls))


def _safe_spearman(x: pd.Series, y: pd.Series) -> tuple[float, float]:
    valid = pd.DataFrame({"x": pd.to_numeric(x, errors="coerce"), "y": pd.to_numeric(y, errors="coerce")}).dropna()
    if len(valid) < 3:
        return float("nan"), float("nan")
    if valid["x"].nunique(dropna=True) < 2 or valid["y"].nunique(dropna=True) < 2:
        return float("nan"), float("nan")
    rho, p_value = spearmanr(valid["x"], valid["y"])
    if pd.isna(rho) or pd.isna(p_value):
        return float("nan"), float("nan")
    return float(rho), float(p_value)


def _write_csv(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False, encoding="utf-8-sig")


def _infer_lr(coords: pd.DataFrame) -> pd.Series:
    out = pd.Series("Unknown", index=coords.index, dtype="string")
    if coords.empty or "section" not in coords.columns or "X" not in coords.columns:
        return out
    x = pd.to_numeric(coords["X"], errors="coerce")
    section_nunique = x.groupby(coords["section"]).transform("nunique")
    section_median_x = x.groupby(coords["section"]).transform("median")
    floor_median_x = x.median()
    valid = x.notna() & section_median_x.notna()
    vertical = valid & (section_nunique == 1)
    normal = valid & ~vertical
    out.loc[normal & (x <= section_median_x)] = "L"
    out.loc[normal & (x > section_median_x)] = "R"
    out.loc[vertical & (x <= floor_median_x)] = "L"
    out.loc[vertical & (x > floor_median_x)] = "R"
    return out


def _load_coords(paths: Iterable[Path]) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for path in paths:
        frame = pd.read_csv(path)
        required = {
            "floor",
            "machine_number",
            "X",
            "Y",
            "section",
            "section_min",
            "section_max",
            "rank_from_min",
            "rank_from_max",
        }
        missing = required - set(frame.columns)
        if missing:
            raise ValueError(f"{path} missing columns: {', '.join(sorted(missing))}")
        frame["machine_number"] = pd.to_numeric(frame["machine_number"], errors="coerce")
        frame["section_min"] = pd.to_numeric(frame["section_min"], errors="coerce")
        frame["section_max"] = pd.to_numeric(frame["section_max"], errors="coerce")
        frame["rank_from_min"] = pd.to_numeric(frame["rank_from_min"], errors="coerce")
        frame["rank_from_max"] = pd.to_numeric(frame["rank_from_max"], errors="coerce")
        frame["X"] = pd.to_numeric(frame["X"], errors="coerce")
        frame["Y"] = pd.to_numeric(frame["Y"], errors="coerce")
        if "display_x" in frame.columns:
            frame["display_x"] = pd.to_numeric(frame["display_x"], errors="coerce")
        if "display_y" in frame.columns:
            frame["display_y"] = pd.to_numeric(frame["display_y"], errors="coerce")
        frame = frame.dropna(
            subset=["machine_number", "section_min", "section_max", "rank_from_min", "rank_from_max"]
        ).copy()
        frame["machine_number"] = frame["machine_number"].astype(int)
        frame["section_min"] = frame["section_min"].astype(int)
        frame["section_max"] = frame["section_max"].astype(int)
        frame["rank_from_min"] = frame["rank_from_min"].astype(int)
        frame["rank_from_max"] = frame["rank_from_max"].astype(int)
        frame["floor"] = frame["floor"].astype(str)
        frame["section"] = frame["section"].astype(str)
        frame["section_size"] = (
            frame.groupby("section", dropna=False)["machine_number"].transform("nunique").astype(int)
        )
        frame["lr"] = _infer_lr(frame)
        frame["kakuban"] = frame["rank_from_min"].astype(int)
        frames.append(frame)

    coords = pd.concat(frames, ignore_index=True)
    duplicated = coords[coords.duplicated(subset=["machine_number"], keep=False)].copy()
    if not duplicated.empty:
        dup_keys = ", ".join(str(value) for value in sorted(duplicated["machine_number"].unique().tolist()))
        raise ValueError(f"duplicate machine_number values in coordinates: {dup_keys}")
    return coords.drop_duplicates(subset=["machine_number"]).reset_index(drop=True)


def _load_hall_frame(cfg: HallConfig, *, min_games: int) -> tuple[pd.DataFrame, pd.DataFrame]:
    raw = load_machine_data(cfg.db_path).copy()
    raw["date"] = raw["date"].astype(str)
    raw["date_dt"] = pd.to_datetime(raw["date"], format="%Y%m%d", errors="coerce")
    raw["machine_number"] = pd.to_numeric(raw["machine_number"], errors="coerce")
    raw["games_normalized"] = pd.to_numeric(raw["games_normalized"], errors="coerce")
    raw["diff_coins_normalized"] = pd.to_numeric(raw["diff_coins_normalized"], errors="coerce")
    raw = raw.dropna(
        subset=["date_dt", "machine_number", "machine_name", "games_normalized", "diff_coins_normalized"]
    ).copy()
    raw["machine_number"] = raw["machine_number"].astype(int)
    if cfg.exclude_machine is not None:
        raw = raw[raw["machine_number"].ne(int(cfg.exclude_machine))].copy()
    if cfg.exclude_mmdd is not None:
        raw = raw[raw["date"].str[4:8].ne(str(cfg.exclude_mmdd))].copy()
    raw = raw[raw["games_normalized"].ge(int(min_games))].copy()
    if raw.empty:
        raise ValueError(f"No rows remained after filtering for {cfg.label}")

    coords = _load_coords(cfg.coords_paths)
    work = raw.merge(coords, on="machine_number", how="inner", validate="m:1")
    if work.empty:
        raise ValueError(f"No rows remained after joining coordinates for {cfg.label}")

    work["hall"] = cfg.label
    work["hall_key"] = next(key for key, item in HALL_CONFIGS.items() if item.label == cfg.label)
    work["machine_name"] = work["machine_name"].astype(str)
    work["seg"] = work["machine_name"].map(classify_seg)
    work["hist_threshold"] = np.where(work["seg"].eq("A"), 104.0, 106.0)
    denom = work["games_normalized"] * 3.0
    work["payout_rate"] = ((denom + work["diff_coins_normalized"]) / denom) * 100.0
    work["hit_flag"] = work["payout_rate"].ge(work["hist_threshold"]).astype(int)
    work = work.sort_values(["date_dt", "section", "machine_number"]).reset_index(drop=True)
    return work, coords


def _build_history_scores(train: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    section_scores = (
        train.groupby(["section", "floor", "section_min", "section_max", "section_size"], as_index=False)
        .agg(
            section_score=("hit_flag", "mean"),
            section_train_n=("date_dt", "nunique"),
            section_train_machines=("machine_number", "nunique"),
        )
        .copy()
    )
    machine_scores = (
        train.groupby(["section", "machine_number", "machine_name"], as_index=False)
        .agg(
            machine_score=("hit_flag", "mean"),
            machine_train_n=("date_dt", "nunique"),
            machine_train_avg_diff=("diff_coins_normalized", "mean"),
            machine_train_hit_rate=("hit_flag", "mean"),
        )
        .copy()
    )
    return section_scores, machine_scores


def _score_day(
    frame: pd.DataFrame,
    target_dt: pd.Timestamp,
    *,
    window_days: int,
    top_machines_per_section: int,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    actual = frame[frame["date_dt"].eq(target_dt)].copy()
    if actual.empty:
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

    window_start = target_dt - pd.Timedelta(days=int(window_days))
    train = frame[(frame["date_dt"].lt(target_dt)) & (frame["date_dt"].ge(window_start))].copy()
    if train.empty:
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

    section_scores, machine_scores = _build_history_scores(train)

    section_eval = (
        actual.groupby(["section", "floor", "section_min", "section_max", "section_size"], as_index=False)
        .agg(
            section_hit_rate=("hit_flag", "mean"),
            section_actual_n=("machine_number", "size"),
        )
        .copy()
    )
    section_eval = section_eval.merge(
        section_scores,
        on=["section", "floor", "section_min", "section_max", "section_size"],
        how="left",
        validate="1:1",
    )
    section_eval["section_score"] = pd.to_numeric(section_eval["section_score"], errors="coerce")
    section_eval = section_eval.sort_values(
        ["section_score", "section_min", "section"],
        ascending=[False, True, True],
        na_position="last",
    ).reset_index(drop=True)
    section_eval["section_rank"] = np.arange(1, len(section_eval) + 1)
    section_eval["section_delta_pp"] = (section_eval["section_hit_rate"] - section_eval["section_score"]) * 100.0
    section_eval["hall"] = actual["hall"].iloc[0]
    section_eval["test_date"] = target_dt.strftime("%Y-%m-%d")
    section_eval["window_days"] = int(window_days)
    section_eval["section_rho"], section_eval["section_p"] = _safe_spearman(
        section_eval["section_score"], section_eval["section_hit_rate"]
    )

    machine_eval = actual.merge(
        machine_scores, on=["section", "machine_number", "machine_name"], how="left", validate="1:1"
    )
    machine_eval["machine_score"] = pd.to_numeric(machine_eval["machine_score"], errors="coerce")
    machine_eval = machine_eval.sort_values(
        ["section", "machine_score", "machine_number"], ascending=[True, False, True], na_position="last"
    ).copy()
    machine_eval["machine_rank_in_section"] = machine_eval.groupby("section", dropna=False).cumcount() + 1
    machine_eval = machine_eval[machine_eval["machine_rank_in_section"] <= int(top_machines_per_section)].copy()
    machine_eval["section_score"] = machine_eval["section"].map(
        section_eval.set_index("section")["section_score"].to_dict()
    )
    machine_eval["section_rank"] = machine_eval["section"].map(
        section_eval.set_index("section")["section_rank"].to_dict()
    )
    machine_eval["section_hit_rate"] = machine_eval["section"].map(
        section_eval.set_index("section")["section_hit_rate"].to_dict()
    )
    machine_eval["section_delta_pp"] = machine_eval["section"].map(
        section_eval.set_index("section")["section_delta_pp"].to_dict()
    )
    machine_eval["actual_hit_flag"] = machine_eval["hit_flag"].astype(int)

    global_eval = actual.merge(
        machine_scores, on=["section", "machine_number", "machine_name"], how="left", validate="1:1"
    )
    global_eval["machine_score"] = pd.to_numeric(global_eval["machine_score"], errors="coerce")
    global_eval["actual_hit_flag"] = global_eval["hit_flag"].astype(int)

    return section_eval, machine_eval.reset_index(drop=True), global_eval


def _section_summary_for_top_k(
    *,
    section_eval: pd.DataFrame,
    actual: pd.DataFrame,
    machine_eval: pd.DataFrame,
    global_eval: pd.DataFrame,
    top_k: int,
) -> dict[str, object]:
    if section_eval.empty:
        return {
            "section_rho": float("nan"),
            "section_p": float("nan"),
            "section_baseline_rate": float("nan"),
            "section_top_rate": float("nan"),
            "section_lift": float("nan"),
            "machine_baseline_rate": float("nan"),
            "selected_machine_rate": float("nan"),
            "selected_machine_lift": float("nan"),
            "n_machines_per_day": float("nan"),
            "global_hist_rate": float("nan"),
            "global_hist_lift": float("nan"),
        }

    ranked = (
        section_eval.sort_values(
            ["section_score", "section_min", "section"],
            ascending=[False, True, True],
            na_position="last",
        )
        .head(int(top_k))
        .copy()
    )
    if ranked.empty:
        return {
            "section_rho": float("nan"),
            "section_p": float("nan"),
            "section_baseline_rate": float("nan"),
            "section_top_rate": float("nan"),
            "section_lift": float("nan"),
            "machine_baseline_rate": float("nan"),
            "selected_machine_rate": float("nan"),
            "selected_machine_lift": float("nan"),
            "n_machines_per_day": float("nan"),
            "global_hist_rate": float("nan"),
            "global_hist_lift": float("nan"),
        }

    section_rho, section_p = _safe_spearman(ranked["section_score"], ranked["section_hit_rate"])
    section_baseline_rate = float(section_eval["section_hit_rate"].mean())
    section_top_rate = float(ranked["section_hit_rate"].mean())
    section_lift = float(section_top_rate / section_baseline_rate) if section_baseline_rate > 0 else float("nan")

    selected_machines = machine_eval[machine_eval["section"].isin(ranked["section"])].copy()
    machine_baseline_rate = float(actual["hit_flag"].mean())
    selected_machine_rate = (
        float(selected_machines["actual_hit_flag"].mean()) if not selected_machines.empty else float("nan")
    )
    selected_machine_lift = (
        float(selected_machine_rate / machine_baseline_rate) if machine_baseline_rate > 0 else float("nan")
    )

    global_count = int(len(selected_machines))
    global_selected = (
        global_eval.sort_values(["machine_score", "machine_number"], ascending=[False, True], na_position="last")
        .head(global_count)
        .copy()
    )
    global_hist_rate = float(global_selected["actual_hit_flag"].mean()) if not global_selected.empty else float("nan")
    global_hist_lift = float(global_hist_rate / machine_baseline_rate) if machine_baseline_rate > 0 else float("nan")

    return {
        "section_rho": section_rho,
        "section_p": section_p,
        "section_baseline_rate": section_baseline_rate,
        "section_top_rate": section_top_rate,
        "section_lift": section_lift,
        "machine_baseline_rate": machine_baseline_rate,
        "selected_machine_rate": selected_machine_rate,
        "selected_machine_lift": selected_machine_lift,
        "n_machines_per_day": float(global_count),
        "global_hist_rate": global_hist_rate,
        "global_hist_lift": global_hist_lift,
    }


def _evaluate_hall(
    hall: str,
    *,
    min_games: int,
    window_days: int,
    eval_days: int,
    top_ks: tuple[int, ...],
    top_machines_per_section: int,
    eval_day_filter: frozenset[int] | None = None,
) -> HallArtifacts:
    cfg = HALL_CONFIGS[hall]
    frame, coords = _load_hall_frame(cfg, min_games=min_games)
    eval_dates = _select_eval_dates(frame, eval_days=eval_days, day_filter=eval_day_filter)
    if len(eval_dates) == 0:
        raise ValueError(f"No evaluation dates available for {cfg.label}")

    section_rows: list[pd.DataFrame] = []
    summary_rows: list[dict[str, object]] = []
    machine_rows: list[pd.DataFrame] = []
    day_top3: list[tuple[str, ...]] = []
    day_top5: list[tuple[str, ...]] = []

    for target_dt in eval_dates:
        section_eval, machine_eval, global_eval = _score_day(
            frame,
            pd.Timestamp(target_dt),
            window_days=window_days,
            top_machines_per_section=top_machines_per_section,
        )
        if section_eval.empty:
            continue

        section_rows.append(section_eval)
        if len(section_eval) >= 3:
            day_top3.append(tuple(section_eval.head(3)["section"].astype(str).tolist()))
        if len(section_eval) >= 5:
            day_top5.append(tuple(section_eval.head(5)["section"].astype(str).tolist()))

        actual = frame[frame["date_dt"].eq(pd.Timestamp(target_dt))].copy()
        for top_k in top_ks:
            summary = _section_summary_for_top_k(
                section_eval=section_eval,
                actual=actual,
                machine_eval=machine_eval,
                global_eval=global_eval,
                top_k=int(top_k),
            )
            summary_rows.append(
                {
                    "hall": cfg.label,
                    "top_k": int(top_k),
                    "eval_days": int(len(eval_dates)),
                    **summary,
                }
            )

        if not machine_eval.empty:
            machine_rows.append(
                machine_eval.assign(
                    hall=hall,
                    test_date=pd.Timestamp(target_dt).strftime("%Y-%m-%d"),
                    window_days=int(window_days),
                )
            )

    section_all = pd.concat(section_rows, ignore_index=True) if section_rows else pd.DataFrame()
    summary_all = pd.DataFrame(summary_rows)
    machine_all = pd.concat(machine_rows, ignore_index=True) if machine_rows else pd.DataFrame()
    if section_all.empty:
        raise ValueError(f"No section evaluation rows were produced for {cfg.label}")

    section_eval = section_all.loc[
        :,
        [
            "hall",
            "test_date",
            "section",
            "floor",
            "section_size",
            "section_score",
            "section_hit_rate",
            "section_rank",
            "section_delta_pp",
        ],
    ].copy()
    section_eval["section_delta_pp"] = section_eval["section_delta_pp"].round(3)
    section_eval["section_score"] = section_eval["section_score"].round(6)
    section_eval["section_hit_rate"] = section_eval["section_hit_rate"].round(6)
    section_eval = section_eval.sort_values(
        ["hall", "test_date", "section_rank", "section"], ascending=[True, True, True, True]
    ).reset_index(drop=True)

    mini_audit = (
        section_all.groupby(["hall", "section", "floor", "section_size"], as_index=False)
        .agg(
            section_min=("section_min", "first"),
            section_max=("section_max", "first"),
            section_score_mean=("section_score", "mean"),
            section_score_std=("section_score", "std"),
            n_eval_days=("test_date", "nunique"),
        )
        .copy()
    )
    mini_audit = mini_audit[mini_audit["section_size"].le(4)].copy()
    mini_audit["section_score_mean"] = mini_audit["section_score_mean"].round(6)
    mini_audit["section_score_std"] = mini_audit["section_score_std"].round(6)
    mini_audit = mini_audit.sort_values(
        ["section_size", "section_score_std", "section"], ascending=[True, False, True]
    ).reset_index(drop=True)

    top3_changes = _count_top_set_changes(day_top3)
    top5_changes = _count_top_set_changes(day_top5)

    return HallArtifacts(
        hall=hall,
        label=cfg.label,
        frame=frame,
        coords=coords,
        section_eval=section_eval,
        summary=summary_all,
        mini_audit=mini_audit,
        top5_changes=top5_changes,
        top3_changes=top3_changes,
    )


def _count_top_set_changes(sets: list[tuple[str, ...]]) -> int:
    if len(sets) < 2:
        return 0
    changes = 0
    prev = sets[0]
    for current in sets[1:]:
        if current != prev:
            changes += 1
        prev = current
    return changes


def _floor_summary_for_rakuen(
    artifact: HallArtifacts,
    *,
    top_ks: tuple[int, ...],
) -> pd.DataFrame:
    coord_floor = artifact.coords.loc[:, ["machine_number", "floor"]].copy()
    frame = artifact.frame.merge(coord_floor, on="machine_number", how="left", suffixes=("", "_coord"))
    if frame.empty:
        return pd.DataFrame()

    rows: list[dict[str, object]] = []
    for floor in sorted(frame["floor"].dropna().astype(str).unique().tolist()):
        floor_frame = frame[frame["floor"].astype(str).eq(floor)].copy()
        if floor_frame.empty:
            continue
        unique_dates = pd.Index(
            sorted(pd.Timestamp(value).normalize() for value in floor_frame["date_dt"].dropna().unique())
        )
        eval_dates = unique_dates[-DEFAULT_EVAL_DAYS:] if len(unique_dates) > DEFAULT_EVAL_DAYS else unique_dates
        section_rows: list[pd.DataFrame] = []
        summary_rows: list[dict[str, object]] = []
        for target_dt in eval_dates:
            section_eval, machine_eval, global_eval = _score_day(
                floor_frame,
                pd.Timestamp(target_dt),
                window_days=DEFAULT_WINDOW_DAYS,
                top_machines_per_section=DEFAULT_TOP_MACHINES_PER_SECTION,
            )
            if section_eval.empty:
                continue
            section_rows.append(section_eval)
            actual = floor_frame[floor_frame["date_dt"].eq(pd.Timestamp(target_dt))].copy()
            for top_k in top_ks:
                summary = _section_summary_for_top_k(
                    section_eval=section_eval,
                    actual=actual,
                    machine_eval=machine_eval,
                    global_eval=global_eval,
                    top_k=int(top_k),
                )
                rows.append(
                    {
                        "floor": floor,
                        "top_k": int(top_k),
                        "eval_days": int(len(eval_dates)),
                        **summary,
                    }
                )
    out = pd.DataFrame(rows)
    if out.empty:
        return out
    summary = (
        out.groupby(["floor", "top_k"], as_index=False)
        .agg(
            eval_days=("eval_days", "max"),
            section_rho=("section_rho", "mean"),
            section_p=("section_p", "mean"),
            section_baseline_rate=("section_baseline_rate", "mean"),
            section_top_rate=("section_top_rate", "mean"),
            section_lift=("section_lift", "mean"),
            machine_baseline_rate=("machine_baseline_rate", "mean"),
            selected_machine_rate=("selected_machine_rate", "mean"),
            selected_machine_lift=("selected_machine_lift", "mean"),
            global_hist_rate=("global_hist_rate", "mean"),
            global_hist_lift=("global_hist_lift", "mean"),
        )
        .sort_values(["floor", "top_k"])
        .reset_index(drop=True)
    )
    return summary


def _build_report(
    *,
    artifacts: list[HallArtifacts],
    hall_summary: pd.DataFrame,
    mini_audit: pd.DataFrame,
    floor_summary: pd.DataFrame,
    kamata1_min_games_summary: pd.DataFrame | None,
    kamata1_event_only_summary: pd.DataFrame | None,
    top_ks: tuple[int, ...],
) -> str:
    lines: list[str] = []
    lines.append("# セクション予測 横展開検証レポート")
    lines.append("")
    lines.append("## 1. データ概要")
    data_rows = []
    for artifact in artifacts:
        floors = ", ".join(dict.fromkeys(artifact.coords["floor"].astype(str).tolist()))
        data_rows.append(
            {
                "hall": artifact.label,
                "machines": int(artifact.coords["machine_number"].nunique()),
                "sections": int(artifact.coords["section"].nunique()),
                "eval_days": int(artifact.section_eval["test_date"].nunique()),
                "floors": floors,
            }
        )
    lines.append(_markdown_table(pd.DataFrame(data_rows), float_digits=3))
    lines.append("")

    lines.append("## 2. ミニセクション監査")
    if mini_audit.empty:
        lines.append("No mini sections were found.")
    else:
        audit_display = mini_audit.loc[
            :,
            [
                "hall",
                "section",
                "floor",
                "section_min",
                "section_max",
                "section_size",
                "section_score_mean",
                "section_score_std",
                "n_eval_days",
            ],
        ].copy()
        lines.append(_markdown_table(audit_display.head(80), float_digits=4))
    lines.append("")
    mini_effect_rows = []
    for artifact in artifacts:
        all_rows = artifact.section_eval.copy()
        all_rows["section_score"] = pd.to_numeric(all_rows["section_score"], errors="coerce")
        all_rows["section_hit_rate"] = pd.to_numeric(all_rows["section_hit_rate"], errors="coerce")
        all_valid = all_rows.dropna(subset=["section_score", "section_hit_rate"])
        no_mini = (
            all_valid[~all_valid["section"].isin(artifact.mini_audit["section"])]
            if not artifact.mini_audit.empty
            else all_valid
        )
        rho_all, _ = _safe_spearman(all_valid["section_score"], all_valid["section_hit_rate"])
        rho_no_mini, _ = _safe_spearman(no_mini["section_score"], no_mini["section_hit_rate"])
        mini_effect_rows.append(
            {
                "hall": artifact.label,
                "section_rho_all": rho_all,
                "section_rho_no_mini": rho_no_mini,
                "delta_rho": rho_no_mini - rho_all if not (pd.isna(rho_no_mini) or pd.isna(rho_all)) else float("nan"),
            }
        )
    lines.append(_markdown_table(pd.DataFrame(mini_effect_rows), float_digits=4))
    lines.append("")

    lines.append("## 3. ホール別評価サマリー")
    summary_display = hall_summary.loc[
        :,
        [
            "hall",
            "top_k",
            "eval_days",
            "section_rho",
            "section_p",
            "section_baseline_rate",
            "section_top_rate",
            "section_lift",
            "machine_baseline_rate",
            "selected_machine_rate",
            "selected_machine_lift",
            "global_hist_rate",
            "global_hist_lift",
        ],
    ].copy()
    for col in ["section_rho", "section_p", "section_lift", "selected_machine_lift", "global_hist_lift"]:
        summary_display[col] = summary_display[col].round(4)
    for col in [
        "section_baseline_rate",
        "section_top_rate",
        "machine_baseline_rate",
        "selected_machine_rate",
        "global_hist_rate",
    ]:
        summary_display[col] = (summary_display[col] * 100.0).round(1)
    lines.append(_markdown_table(summary_display, float_digits=4))
    lines.append("")

    lines.append("## 4. Spearman相関の比較")
    rho_rows = (
        hall_summary.sort_values(["hall", "section_rho", "section_lift"], ascending=[True, False, False])
        .drop_duplicates(subset=["hall"], keep="first")
        .loc[:, ["hall", "top_k", "section_rho"]]
        .rename(columns={"top_k": "best_top_k", "section_rho": "best_section_rho"})
        .sort_values(["best_section_rho", "hall"], ascending=[False, True])
        .reset_index(drop=True)
    )
    lines.append(_markdown_table(rho_rows, float_digits=4))
    lines.append("")

    lines.append("## 5. セクション順位の安定性")
    stability_rows = []
    for artifact in artifacts:
        daily = artifact.section_eval.copy()
        daily["section_rank"] = pd.to_numeric(daily["section_rank"], errors="coerce")
        daily = daily.dropna(subset=["section_rank"]).copy()
        top3_unique = int(
            daily.sort_values(["test_date", "section_rank"])
            .groupby("test_date")
            .head(3)
            .groupby("test_date")["section"]
            .apply(lambda s: tuple(s.tolist()))
            .nunique()
        )
        top5_unique = int(
            daily.sort_values(["test_date", "section_rank"])
            .groupby("test_date")
            .head(5)
            .groupby("test_date")["section"]
            .apply(lambda s: tuple(s.tolist()))
            .nunique()
        )
        stability_rows.append(
            {
                "hall": artifact.label,
                "top3_changes": artifact.top3_changes,
                "top3_unique_sets": top3_unique,
                "top5_changes": artifact.top5_changes,
                "top5_unique_sets": top5_unique,
            }
        )
    lines.append(_markdown_table(pd.DataFrame(stability_rows), float_digits=4))
    lines.append("")

    lines.append("## 6. 楽園のフロア別分析")
    if floor_summary.empty:
        lines.append("No floor summary rows.")
    else:
        lines.append(_markdown_table(floor_summary, float_digits=4))
    lines.append("")

    lines.append("## 7. 結論と推奨")
    if not hall_summary.empty:
        best_rows = (
            hall_summary.sort_values(["hall", "section_lift", "section_rho"], ascending=[True, False, False])
            .groupby("hall", as_index=False)
            .head(1)
            .reset_index(drop=True)
        )
        for _, row in best_rows.iterrows():
            lines.append(
                f"- {row['hall']}: best top_k={int(row['top_k'])}, "
                f"section_lift={float(row['section_lift']):.3f}, section_rho={float(row['section_rho']):.3f}"
            )
    if not mini_effect_rows:
        lines.append("- ミニセクションの効果は判定できませんでした。")
    else:
        strongest_drop = min(
            mini_effect_rows,
            key=lambda row: row["delta_rho"] if pd.notna(row["delta_rho"]) else float("inf"),
        )
        lines.append(
            f"- ミニセクション除外で相関が最も改善したのは {strongest_drop['hall']} "
            f"(delta_rho={_format_value(strongest_drop['delta_rho'], float_digits=4)})"
        )
    if not floor_summary.empty:
        rakuen_rows = floor_summary.copy()
        best_floor = rakuen_rows.sort_values(["section_lift", "section_rho"], ascending=[False, False]).head(1)
        if not best_floor.empty:
            row = best_floor.iloc[0]
            lines.append(
                f"- 楽園では floor={row['floor']} / top_k={int(row['top_k'])} が最も強い。 "
                f"全体統合よりフロア別の方が有利かを優先検討すべき。"
            )
    lines.append("")

    if kamata1_min_games_summary is not None or kamata1_event_only_summary is not None:
        lines.append("## 8. 蒲田1 感度分析")
        lines.append("")
        if kamata1_min_games_summary is not None and not kamata1_min_games_summary.empty:
            lines.append("### 8a. min_games 感度")
            min_games_display = kamata1_min_games_summary.loc[
                :,
                [
                    "min_games",
                    "top_k",
                    "section_rho",
                    "section_lift",
                    "n_machines_per_day_avg",
                ],
            ].copy()
            lines.append(_markdown_table(min_games_display, float_digits=4))
            lines.append("")
        if kamata1_event_only_summary is not None and not kamata1_event_only_summary.empty:
            lines.append("### 8b. イベント日限定")
            event_display = kamata1_event_only_summary.loc[
                :,
                [
                    "event_filter",
                    "top_k",
                    "section_rho",
                    "section_lift",
                    "eval_days",
                ],
            ].copy()
            lines.append(_markdown_table(event_display, float_digits=4))
            lines.append("")
        lines.append("### 8c. 解釈")
        lines.append("- min_games を上げることで section_rho が改善するか")
        lines.append("- イベント日限定でセクション予測力が向上するか")
        lines.append("")
    return "\n".join(lines)


def _aggregate_summary(raw_summary: pd.DataFrame) -> pd.DataFrame:
    agg_cols = {
        "eval_days": ("eval_days", "max"),
        "section_rho": ("section_rho", "mean"),
        "section_p": ("section_p", "mean"),
        "section_baseline_rate": ("section_baseline_rate", "mean"),
        "section_top_rate": ("section_top_rate", "mean"),
        "section_lift": ("section_lift", "mean"),
        "machine_baseline_rate": ("machine_baseline_rate", "mean"),
        "selected_machine_rate": ("selected_machine_rate", "mean"),
        "selected_machine_lift": ("selected_machine_lift", "mean"),
        "global_hist_rate": ("global_hist_rate", "mean"),
        "global_hist_lift": ("global_hist_lift", "mean"),
    }
    n_col = "n_machines_per_day" if "n_machines_per_day" in raw_summary.columns else "n_machines_per_day_avg"
    agg_cols["n_machines_per_day_avg"] = (n_col, "mean")
    group_cols = ["hall", "top_k"] if "hall" in raw_summary.columns else ["top_k"]
    return raw_summary.groupby(group_cols, as_index=False).agg(**agg_cols).copy()


def _build_kamata1_sensitivity_outputs(
    *,
    window_days: int,
    eval_days: int,
    top_ks: tuple[int, ...],
    top_machines_per_section: int,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    kama1_min_games_rows: list[pd.DataFrame] = []
    kama1_event_rows: list[pd.DataFrame] = []
    kama1_base_summary: pd.DataFrame | None = None
    kama1_cfg = HALL_CONFIGS["kamata1"]

    for min_games in KAMATA1_MIN_GAMES_SENSITIVITY:
        artifact = _evaluate_hall(
            "kamata1",
            min_games=min_games,
            window_days=window_days,
            eval_days=eval_days,
            top_ks=top_ks,
            top_machines_per_section=top_machines_per_section,
        )
        summary = _aggregate_summary(artifact.summary)
        summary["min_games"] = int(min_games)
        kama1_min_games_rows.append(summary)
        if min_games == DEFAULT_MIN_GAMES:
            kama1_base_summary = summary.copy()

    event_artifact = _evaluate_hall(
        "kamata1",
        min_games=DEFAULT_MIN_GAMES,
        window_days=window_days,
        eval_days=eval_days,
        top_ks=top_ks,
        top_machines_per_section=top_machines_per_section,
        eval_day_filter=kama1_cfg.event_dds,
    )
    event_summary = _aggregate_summary(event_artifact.summary)
    event_summary["event_filter"] = "event_only"

    if kama1_base_summary is None:
        kama1_base_summary = _aggregate_summary(
            _evaluate_hall(
                "kamata1",
                min_games=DEFAULT_MIN_GAMES,
                window_days=window_days,
                eval_days=eval_days,
                top_ks=top_ks,
                top_machines_per_section=top_machines_per_section,
            ).summary
        )

    kama1_base_summary["event_filter"] = "all"
    kama1_event_rows.append(kama1_base_summary)
    kama1_event_rows.append(event_summary)

    kama1_min_games_summary = (
        pd.concat(kama1_min_games_rows, ignore_index=True) if kama1_min_games_rows else pd.DataFrame()
    )
    kama1_event_only_summary = pd.concat(kama1_event_rows, ignore_index=True) if kama1_event_rows else pd.DataFrame()

    if not kama1_min_games_summary.empty:
        kama1_min_games_summary = kama1_min_games_summary.loc[
            :,
            [
                "min_games",
                "top_k",
                "eval_days",
                "section_rho",
                "section_p",
                "section_lift",
                "machine_baseline_rate",
                "selected_machine_rate",
                "selected_machine_lift",
                "n_machines_per_day_avg",
            ],
        ].copy()
        kama1_min_games_summary = kama1_min_games_summary.sort_values(["min_games", "top_k"]).reset_index(drop=True)

    if not kama1_event_only_summary.empty:
        kama1_event_only_summary = kama1_event_only_summary.loc[
            :,
            [
                "hall",
                "top_k",
                "eval_days",
                "section_rho",
                "section_p",
                "section_lift",
                "machine_baseline_rate",
                "selected_machine_rate",
                "selected_machine_lift",
                "n_machines_per_day_avg",
                "event_filter",
            ],
        ].copy()
        kama1_event_only_summary = kama1_event_only_summary.sort_values(["event_filter", "top_k"]).reset_index(
            drop=True
        )

    return kama1_min_games_summary, kama1_event_only_summary


def build_outputs(
    *,
    halls: tuple[str, ...],
    output_dir: Path,
    min_games: int,
    window_days: int,
    eval_days: int,
    top_ks: tuple[int, ...],
    top_machines_per_section: int,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, str]:
    artifacts: list[HallArtifacts] = []
    for hall in halls:
        cfg = HALL_CONFIGS[hall]
        print(f"[INFO] {cfg.label}: loading {cfg.db_path.name}")
        artifact = _evaluate_hall(
            hall,
            min_games=min_games,
            window_days=window_days,
            eval_days=eval_days,
            top_ks=top_ks,
            top_machines_per_section=top_machines_per_section,
        )
        print(f"[SMOKE] {cfg.label} seg counts")
        print(artifact.frame["seg"].value_counts(dropna=False).sort_index().to_string())
        artifacts.append(artifact)

    section_eval_all = (
        pd.concat([artifact.section_eval for artifact in artifacts], ignore_index=True) if artifacts else pd.DataFrame()
    )
    hall_summary = (
        pd.concat([artifact.summary for artifact in artifacts], ignore_index=True) if artifacts else pd.DataFrame()
    )
    mini_audit = (
        pd.concat([artifact.mini_audit for artifact in artifacts], ignore_index=True) if artifacts else pd.DataFrame()
    )
    kamata1_min_games_summary = pd.DataFrame()
    kamata1_event_only_summary = pd.DataFrame()

    if hall_summary.empty:
        raise ValueError("No hall summary rows were produced")

    hall_summary = (
        hall_summary.groupby(["hall", "top_k"], as_index=False)
        .agg(
            eval_days=("eval_days", "max"),
            section_rho=("section_rho", "mean"),
            section_p=("section_p", "mean"),
            section_baseline_rate=("section_baseline_rate", "mean"),
            section_top_rate=("section_top_rate", "mean"),
            section_lift=("section_lift", "mean"),
            machine_baseline_rate=("machine_baseline_rate", "mean"),
            selected_machine_rate=("selected_machine_rate", "mean"),
            selected_machine_lift=("selected_machine_lift", "mean"),
            n_machines_per_day_avg=("n_machines_per_day", "mean"),
            global_hist_rate=("global_hist_rate", "mean"),
            global_hist_lift=("global_hist_lift", "mean"),
        )
        .copy()
    )
    hall_summary["hall_sort"] = hall_summary["hall"].map(HALL_SORT_INDEX)
    hall_summary = (
        hall_summary.sort_values(["hall_sort", "top_k", "hall"]).drop(columns=["hall_sort"]).reset_index(drop=True)
    )
    hall_summary["section_rho"] = hall_summary["section_rho"].round(6)
    hall_summary["section_p"] = hall_summary["section_p"].round(6)
    for col in [
        "section_baseline_rate",
        "section_top_rate",
        "machine_baseline_rate",
        "selected_machine_rate",
        "global_hist_rate",
    ]:
        hall_summary[col] = hall_summary[col].round(6)
    for col in ["section_lift", "selected_machine_lift", "global_hist_lift"]:
        hall_summary[col] = hall_summary[col].round(6)
    hall_summary["n_machines_per_day_avg"] = hall_summary["n_machines_per_day_avg"].round(6)

    if not mini_audit.empty:
        mini_audit["hall_sort"] = mini_audit["hall"].map(HALL_SORT_INDEX)
        mini_audit = (
            mini_audit.sort_values(
                ["hall_sort", "section_size", "section_score_std", "section"],
                ascending=[True, True, False, True],
            )
            .drop(columns=["hall_sort"])
            .reset_index(drop=True)
        )

    floor_summary = pd.DataFrame()
    rakuen_artifacts = next((artifact for artifact in artifacts if artifact.hall == "rakuen"), None)
    if rakuen_artifacts is not None:
        floor_summary = _floor_summary_for_rakuen(rakuen_artifacts, top_ks=top_ks)
        if not floor_summary.empty:
            floor_summary = floor_summary.sort_values(["floor", "top_k"]).reset_index(drop=True)
            for col in ["section_rho", "section_p", "section_lift", "selected_machine_lift", "global_hist_lift"]:
                floor_summary[col] = floor_summary[col].round(6)
            for col in [
                "section_baseline_rate",
                "section_top_rate",
                "machine_baseline_rate",
                "selected_machine_rate",
                "global_hist_rate",
            ]:
                floor_summary[col] = floor_summary[col].round(6)

    selected_halls = set(halls)
    if "kamata1" in selected_halls:
        kamata1_min_games_summary, kamata1_event_only_summary = _build_kamata1_sensitivity_outputs(
            window_days=window_days,
            eval_days=eval_days,
            top_ks=top_ks,
            top_machines_per_section=top_machines_per_section,
        )
        if not kamata1_min_games_summary.empty:
            _write_csv(kamata1_min_games_summary, output_dir / "kamata1_min_games_sensitivity.csv")
        if not kamata1_event_only_summary.empty:
            _write_csv(kamata1_event_only_summary, output_dir / "kamata1_event_only.csv")

    report = _build_report(
        artifacts=artifacts,
        hall_summary=hall_summary,
        mini_audit=mini_audit,
        floor_summary=floor_summary,
        kamata1_min_games_summary=kamata1_min_games_summary,
        kamata1_event_only_summary=kamata1_event_only_summary,
        top_ks=top_ks,
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    section_eval_path = output_dir / "hall_section_eval.csv"
    hall_summary_path = output_dir / "hall_summary.csv"
    mini_audit_path = output_dir / "mini_section_audit.csv"
    report_path = output_dir / "report.md"

    _write_csv(section_eval_all, section_eval_path)
    _write_csv(hall_summary, hall_summary_path)
    _write_csv(mini_audit, mini_audit_path)
    report_path.write_text(report, encoding="utf-8")
    return section_eval_all, hall_summary, mini_audit, report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Section lateral expansion evaluation")
    parser.add_argument("--hall", type=str, default="all", help="Comma-separated hall keys or all")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR, help="Output directory")
    parser.add_argument("--min-games", type=int, default=DEFAULT_MIN_GAMES, help="Minimum normalized games")
    parser.add_argument("--window-days", type=int, default=DEFAULT_WINDOW_DAYS, help="History window in days")
    parser.add_argument("--eval-days", type=int, default=DEFAULT_EVAL_DAYS, help="Number of evaluation days")
    parser.add_argument("--top-ks", type=str, default="1,3,5,10", help="Comma-separated top-k list")
    parser.add_argument(
        "--top-machines-per-section",
        type=int,
        default=DEFAULT_TOP_MACHINES_PER_SECTION,
        help="Top machines per selected section",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    halls = _parse_hall_list(args.hall)
    top_ks = _parse_int_list(args.top_ks) or DEFAULT_TOP_KS
    output_dir = Path(args.output_dir)

    section_eval_all, hall_summary, mini_audit, _ = build_outputs(
        halls=halls,
        output_dir=output_dir,
        min_games=int(args.min_games),
        window_days=int(args.window_days),
        eval_days=int(args.eval_days),
        top_ks=top_ks,
        top_machines_per_section=int(args.top_machines_per_section),
    )
    print(f"[OK] section_eval rows: {len(section_eval_all)}")
    print(f"[OK] hall_summary rows: {len(hall_summary)}")
    print(f"[OK] mini_section_audit rows: {len(mini_audit)}")
    print(f"[OK] report saved: {output_dir / 'report.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
