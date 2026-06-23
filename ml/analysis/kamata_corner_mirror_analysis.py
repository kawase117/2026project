from __future__ import annotations

import argparse
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd
from scipy.stats import kruskal


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB_1 = PROJECT_ROOT / "db" / "マルハンメガシティ2000-蒲田1.db"
DEFAULT_DB_7 = PROJECT_ROOT / "db" / "マルハンメガシティ2000-蒲田7.db"
DEFAULT_COORDS_1 = PROJECT_ROOT / "Heatmap" / "2F_floor_coordinates_kamata1.csv"
DEFAULT_COORDS_7 = PROJECT_ROOT / "Heatmap" / "2F_floor_coordinates_kamata7.csv"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "ml" / "analysis" / "results" / "kamata_corner_mirror"

DEFAULT_AXIS_BIN_SIZES = (8, 10, 15, 20)
DEFAULT_GRID_SIZES = (3, 4, 5)
DEFAULT_MIN_CORR_GAP = 0.10
DEFAULT_MIN_SUPPORT_RATE = 0.75
DEFAULT_H2_START = pd.Timestamp("2025-07-07")
DEFAULT_H2_END = pd.Timestamp("2025-12-31")
WEEKDAY_NAME_TO_INDEX = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6,
}

REQUIRED_COORD_COLUMNS = {"hall_name", "floor", "machine_number", "X", "Y", "rank_from_min", "rank_from_max"}


@dataclass(frozen=True)
class HallSpec:
    hall_name: str
    db_path: Path
    coords_path: Path


def _read_date_bounds(db_path: Path) -> tuple[pd.Timestamp, pd.Timestamp]:
    with sqlite3.connect(db_path) as conn:
        row = conn.execute("SELECT MIN(date), MAX(date) FROM machine_detailed_results").fetchone()
    if row is None or row[0] is None or row[1] is None:
        raise ValueError(f"No dates found in {db_path}")
    return (
        pd.to_datetime(row[0], format="%Y%m%d", errors="raise"),
        pd.to_datetime(row[1], format="%Y%m%d", errors="raise"),
    )


def _read_raw_results(db_path: Path) -> pd.DataFrame:
    with sqlite3.connect(db_path) as conn:
        frame = pd.read_sql_query(
            """
            SELECT date, machine_number, machine_name, diff_coins_normalized, games_normalized
            FROM machine_detailed_results
            """,
            conn,
        )
    if frame.empty:
        raise ValueError(f"machine_detailed_results returned no rows in {db_path}")
    return frame


def _read_machine_master_flags(db_path: Path) -> pd.DataFrame:
    with sqlite3.connect(db_path) as conn:
        tables = pd.read_sql_query("SELECT name FROM sqlite_master WHERE type='table'", conn)["name"].tolist()
        if "machine_master" not in tables:
            return pd.DataFrame(columns=["machine_name_normalized", "jug_flag", "hana_flag", "bt_flag"])
        cols = pd.read_sql_query("PRAGMA table_info(machine_master)", conn)["name"].tolist()
        select_cols = ["machine_name_normalized"]
        for col in ("jug_flag", "hana_flag", "bt_flag"):
            if col in cols:
                select_cols.append(col)
        master = pd.read_sql_query(f"SELECT {', '.join(select_cols)} FROM machine_master", conn)
    if master.empty:
        return pd.DataFrame(columns=["machine_name_normalized", "jug_flag", "hana_flag", "bt_flag"])
    for col in ("jug_flag", "hana_flag", "bt_flag"):
        if col not in master.columns:
            master[col] = 0
        master[col] = pd.to_numeric(master[col], errors="coerce").fillna(0).astype(int)
    master["machine_name_normalized"] = master["machine_name_normalized"].astype(str)
    return master[["machine_name_normalized", "jug_flag", "hana_flag", "bt_flag"]].drop_duplicates()


def _read_coordinates(coords_path: Path, hall_name: str, floor: str) -> pd.DataFrame:
    coords = pd.read_csv(coords_path)
    missing = REQUIRED_COORD_COLUMNS - set(coords.columns)
    if missing - {"rank_from_min", "rank_from_max"}:
        raise ValueError(f"Missing coordinate columns in {coords_path}: {sorted(missing)}")
    coords = coords[(coords["hall_name"] == hall_name) & (coords["floor"] == floor)].copy()
    if coords.empty:
        raise ValueError(f"No coordinates found for hall={hall_name!r}, floor={floor!r}")
    if coords["machine_number"].duplicated().any():
        dupes = sorted(coords.loc[coords["machine_number"].duplicated(), "machine_number"].unique().tolist())
        raise ValueError(f"Duplicate machine_number values in {coords_path}: {dupes}")
    if "rank_from_min" not in coords.columns or "rank_from_max" not in coords.columns:
        if "section" in coords.columns:
            coords["rank_from_min"] = coords.groupby("section", dropna=False)["machine_number"].transform(
                lambda s: s.rank(method="first", ascending=True)
            )
            coords["rank_from_max"] = coords.groupby("section", dropna=False)["machine_number"].transform(
                lambda s: s.rank(method="first", ascending=False)
            )
        else:
            coords["rank_from_min"] = coords["machine_number"].rank(method="first", ascending=True)
            coords["rank_from_max"] = coords["machine_number"].rank(method="first", ascending=False)
    for column in ("machine_number", "X", "Y", "rank_from_min", "rank_from_max"):
        coords[column] = pd.to_numeric(coords[column], errors="coerce")
    coords = coords.dropna(subset=["machine_number", "X", "Y"]).copy()
    coords["machine_number"] = coords["machine_number"].astype(int)
    return coords


def infer_hall_name(coords_path: Path, floor: str = "2F") -> str:
    coords = pd.read_csv(coords_path, usecols=["hall_name", "floor"])
    floor_coords = coords[coords["floor"] == floor].copy()
    unique = floor_coords["hall_name"].dropna().astype(str).unique().tolist()
    if not unique:
        raise ValueError(f"Could not infer hall_name from {coords_path} for floor={floor!r}")
    if len(unique) > 1:
        raise ValueError(f"Multiple hall_name values found in {coords_path} for floor={floor!r}: {unique}")
    return unique[0]


def _normalize_series(values: pd.Series) -> pd.Series:
    numeric = pd.to_numeric(values, errors="coerce")
    valid = numeric.dropna()
    if valid.empty:
        return pd.Series(np.nan, index=values.index, dtype=float)
    lower = float(valid.min())
    upper = float(valid.max())
    if np.isclose(lower, upper):
        return pd.Series(0.0, index=values.index, dtype=float)
    return (numeric - lower) / (upper - lower)


def _zscore(values: pd.Series) -> pd.Series:
    numeric = pd.to_numeric(values, errors="coerce")
    valid = numeric.dropna()
    if valid.empty:
        return pd.Series(np.nan, index=values.index, dtype=float)
    mean = float(valid.mean())
    std = float(valid.std(ddof=0))
    if np.isclose(std, 0.0):
        return pd.Series(0.0, index=values.index, dtype=float)
    return (numeric - mean) / std


def _bin_index(values: pd.Series, bins: int) -> pd.Series:
    clipped = pd.to_numeric(values, errors="coerce").clip(0.0, 0.999999999)
    out = np.floor(clipped * bins).astype("Int64")
    return out.fillna(-1).astype(int)


def compare_profile_series(left: Iterable[float], right: Iterable[float]) -> float:
    left_arr = np.asarray(list(left), dtype=float)
    right_arr = np.asarray(list(right), dtype=float)
    mask = np.isfinite(left_arr) & np.isfinite(right_arr)
    if mask.sum() < 2:
        return float("nan")
    left_sel = left_arr[mask]
    right_sel = right_arr[mask]
    if np.isclose(left_sel.std(ddof=0), 0.0) or np.isclose(right_sel.std(ddof=0), 0.0):
        return float("nan")
    return float(np.corrcoef(left_sel, right_sel)[0, 1])


def compute_machine_residuals(frame: pd.DataFrame) -> pd.DataFrame:
    return compute_machine_metric_residuals(
        frame,
        metric_col="diff_coins_normalized",
        mean_col="machine_name_mean_diff",
        residual_col="residual_diff",
    )


def compute_machine_metric_residuals(
    frame: pd.DataFrame,
    *,
    metric_col: str,
    mean_col: str,
    residual_col: str,
) -> pd.DataFrame:
    work = frame.copy()
    work[mean_col] = work.groupby("machine_name")[metric_col].transform("mean")
    work[residual_col] = work[metric_col] - work[mean_col]
    return work


def _hall_display_label_from_coords(coords_path: Path) -> str:
    stem = coords_path.stem.lower()
    if "kamata1" in stem:
        return "蒲田1"
    if "kamata7" in stem:
        return "蒲田7"
    return coords_path.stem


def _resolve_hall_label(hall_name: str, coords_path: Path | None = None) -> str:
    if "蒲田1" in hall_name:
        return "蒲田1"
    if "蒲田7" in hall_name:
        return "蒲田7"
    if coords_path is not None:
        return _hall_display_label_from_coords(coords_path)
    return hall_name


def _attach_kakuban_compat(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    if out.empty:
        out["kakuban"] = pd.Series(dtype="Int64")
        out["kakuban_min"] = pd.Series(dtype="Int64")
        out["kakuban_max"] = pd.Series(dtype="Int64")
        out["kakuban_rule"] = pd.Series(dtype="object")
        out["excluded_from_corr"] = pd.Series(dtype="bool")
        out["is_isolated"] = pd.Series(dtype="bool")
        return out

    if "rank_from_min" in out.columns:
        out["kakuban_min"] = pd.to_numeric(out["rank_from_min"], errors="coerce").astype("Int64")
    elif "kakuban_min" in out.columns:
        out["kakuban_min"] = pd.to_numeric(out["kakuban_min"], errors="coerce").astype("Int64")
    elif "kakuban" in out.columns:
        out["kakuban_min"] = pd.to_numeric(out["kakuban"], errors="coerce").astype("Int64")
    else:
        out["kakuban_min"] = pd.Series(pd.NA, index=out.index, dtype="Int64")

    if "rank_from_max" in out.columns:
        out["kakuban_max"] = pd.to_numeric(out["rank_from_max"], errors="coerce").astype("Int64")
    elif "kakuban_max" in out.columns:
        out["kakuban_max"] = pd.to_numeric(out["kakuban_max"], errors="coerce").astype("Int64")
    elif "kakuban" in out.columns:
        out["kakuban_max"] = pd.to_numeric(out["kakuban"], errors="coerce").astype("Int64")
    else:
        out["kakuban_max"] = pd.Series(pd.NA, index=out.index, dtype="Int64")

    out["kakuban"] = out["kakuban_min"]
    out["kakuban_rule"] = "rank_from_min"
    out["excluded_from_corr"] = False
    out["is_isolated"] = False
    return out


def assign_kakuban(
    frame: pd.DataFrame,
    *,
    hall_label: str,
    floor: str,
    exclude_isolated: bool = True,
) -> pd.DataFrame:
    """Compatibility wrapper that chooses one side for legacy callers."""
    out = _attach_kakuban_compat(frame)
    if out.empty:
        return out

    if "section" not in out.columns:
        out["section"] = None

    section_to_side = {
        ("蒲田7", "2F", "2330-2351"): "max",
        ("蒲田7", "3F", "3191-3208"): "max",
        ("蒲田7", "3F", "3341-3362"): "max",
        ("蒲田7", "3F", "3400-3401"): "min",
    }
    isolated_sections = {("蒲田7", "3F", "3400-3401")}

    kakuban_values = []
    kakuban_rules = []
    isolated_flags = []
    for section in out["section"].astype(str).tolist():
        side = section_to_side.get((hall_label, floor, section), "min")
        if side == "max":
            kakuban_values.append(out.loc[out["section"].astype(str).eq(section), "kakuban_max"])
            kakuban_rules.append("rank_from_max")
        else:
            kakuban_values.append(out.loc[out["section"].astype(str).eq(section), "kakuban_min"])
            kakuban_rules.append("rank_from_min")
        isolated_flags.append((hall_label, floor, section) in isolated_sections)

    # Populate by row using the per-section choice above.
    out["kakuban_rule"] = "rank_from_min"
    out["is_isolated"] = False
    for (section, side, is_isolated) in zip(out["section"].astype(str).tolist(), [section_to_side.get((hall_label, floor, s), "min") for s in out["section"].astype(str).tolist()], isolated_flags, strict=False):
        mask = out["section"].astype(str).eq(section)
        out.loc[mask, "kakuban"] = out.loc[mask, "kakuban_max" if side == "max" else "kakuban_min"]
        out.loc[mask, "kakuban_rule"] = f"rank_from_{side}"
        out.loc[mask, "is_isolated"] = is_isolated

    out["excluded_from_corr"] = out["is_isolated"] if exclude_isolated else False
    out["kakuban"] = pd.to_numeric(out["kakuban"], errors="coerce").astype("Int64")
    out["excluded_from_corr"] = out["excluded_from_corr"].astype(bool)
    out["is_isolated"] = out["is_isolated"].astype(bool)
    return out


def _normalize_weekday_filter(weekday: str | int | None) -> tuple[str | None, int | None]:
    if weekday is None:
        return None, None
    if isinstance(weekday, int):
        if weekday < 0 or weekday > 6:
            raise ValueError(f"weekday must be between 0 and 6, got {weekday}")
        names = list(WEEKDAY_NAME_TO_INDEX.keys())
        return names[weekday], weekday
    normalized = str(weekday).strip().lower()
    if normalized not in WEEKDAY_NAME_TO_INDEX:
        raise ValueError(f"Unsupported weekday filter: {weekday!r}")
    return normalized, WEEKDAY_NAME_TO_INDEX[normalized]


def _build_merged_frame(
    *,
    db_path: Path,
    coords_path: Path,
    hall_name: str,
    floor: str = "2F",
    min_games: int = 1500,
    date_range: tuple[pd.Timestamp | str, pd.Timestamp | str] | None = None,
    weekday: str | int | None = None,
) -> pd.DataFrame:
    raw = _read_raw_results(db_path)
    coords = _read_coordinates(coords_path, hall_name=hall_name, floor=floor)
    machine_master = _read_machine_master_flags(db_path)
    weekday_name, weekday_index = _normalize_weekday_filter(weekday)

    raw["date"] = pd.to_datetime(raw["date"], format="%Y%m%d", errors="coerce")
    raw["machine_number"] = pd.to_numeric(raw["machine_number"], errors="coerce")
    raw["diff_coins_normalized"] = pd.to_numeric(raw["diff_coins_normalized"], errors="coerce")
    raw["games_normalized"] = pd.to_numeric(raw["games_normalized"], errors="coerce")
    raw = raw.dropna(subset=["date", "machine_number", "machine_name", "diff_coins_normalized", "games_normalized"]).copy()
    raw["machine_number"] = raw["machine_number"].astype(int)
    raw["machine_name"] = raw["machine_name"].astype(str)

    merged = raw.merge(coords, on="machine_number", how="inner", validate="many_to_one")
    if merged.empty:
        raise ValueError(f"No rows remained after joining {db_path.name} and {coords_path.name}")

    if not machine_master.empty:
        merged = merged.merge(
            machine_master,
            left_on="machine_name",
            right_on="machine_name_normalized",
            how="left",
            validate="many_to_one",
        )
    else:
        merged["machine_name_normalized"] = merged["machine_name"]
        merged["jug_flag"] = 0
        merged["hana_flag"] = 0
        merged["bt_flag"] = 0

    for col in ("jug_flag", "hana_flag", "bt_flag"):
        merged[col] = pd.to_numeric(merged[col], errors="coerce").fillna(0).astype(int)
    merged["machine_name_normalized"] = merged["machine_name_normalized"].fillna(merged["machine_name"]).astype(str)
    merged["machine_type_segment"] = np.where((merged["jug_flag"] == 1) | (merged["hana_flag"] == 1), "A", "N")

    if date_range is not None:
        start, end = pd.to_datetime(date_range[0]), pd.to_datetime(date_range[1])
        merged = merged[(merged["date"] >= start) & (merged["date"] <= end)].copy()

    if weekday_index is not None:
        merged = merged[merged["date"].dt.dayofweek == weekday_index].copy()

    merged = merged[merged["games_normalized"] >= min_games].copy()
    if merged.empty:
        raise ValueError(
            f"No rows remained after applying min_games={min_games}"
            + (f" and weekday={weekday_name!r}" if weekday_name is not None else "")
            + f" for hall={hall_name!r}"
        )

    merged["X"] = pd.to_numeric(merged["X"], errors="coerce")
    merged["Y"] = pd.to_numeric(merged["Y"], errors="coerce")
    merged = merged.dropna(subset=["X", "Y"]).copy()

    merged["x_norm"] = _normalize_series(merged["X"])
    merged["y_norm"] = _normalize_series(merged["Y"])
    merged = compute_machine_residuals(merged)
    merged = compute_machine_metric_residuals(
        merged,
        metric_col="games_normalized",
        mean_col="machine_name_mean_games",
        residual_col="residual_games",
    )

    return merged


def load_hall_frame(
    *,
    db_path: Path,
    coords_path: Path,
    hall_name: str,
    floor: str = "2F",
    min_games: int = 1500,
    date_range: tuple[pd.Timestamp | str, pd.Timestamp | str] | None = None,
    weekday: str | int | None = None,
) -> pd.DataFrame:
    coords = _read_coordinates(coords_path, hall_name=hall_name, floor=floor)
    merged = _build_merged_frame(
        db_path=db_path,
        coords_path=coords_path,
        hall_name=hall_name,
        floor=floor,
        min_games=min_games,
        date_range=date_range,
        weekday=weekday,
    )

    group_columns = [
        "hall_name",
        "floor",
        "machine_number",
        "machine_name",
        "machine_name_normalized",
        "jug_flag",
        "hana_flag",
        "bt_flag",
        "machine_type_segment",
        "X",
        "Y",
        "rank_from_min",
        "rank_from_max",
        "x_norm",
        "y_norm",
    ]
    for optional_column in ("section", "section_min", "section_max"):
        if optional_column in merged.columns:
            group_columns.append(optional_column)

    machine_frame = (
        merged.groupby(group_columns, as_index=False)
        .agg(
            date=("date", "min"),
            mean_diff=("diff_coins_normalized", "mean"),
            machine_name_mean_diff=("machine_name_mean_diff", "mean"),
            machine_name_mean_games=("machine_name_mean_games", "mean"),
            residual_diff=("residual_diff", "mean"),
            residual_games=("residual_games", "mean"),
            mean_games=("games_normalized", "mean"),
            n_rows=("date", "size"),
        )
        .sort_values("machine_number")
        .reset_index(drop=True)
    )
    machine_frame = _attach_kakuban_compat(machine_frame)

    expected_numbers = set(coords["machine_number"].astype(int).tolist())
    actual_numbers = set(machine_frame["machine_number"].astype(int).tolist())
    missing = sorted(expected_numbers - actual_numbers)
    if missing:
        raise ValueError(f"Join/filter removed coordinates unexpectedly for hall={hall_name!r}, floor={floor!r}: {missing[:10]}")

    return machine_frame


def load_hall_daily_frame(
    *,
    db_path: Path,
    coords_path: Path,
    hall_name: str,
    floor: str = "2F",
    min_games: int = 1500,
    date_range: tuple[pd.Timestamp | str, pd.Timestamp | str] | None = None,
    weekday: str | int | None = None,
) -> pd.DataFrame:
    merged = _build_merged_frame(
        db_path=db_path,
        coords_path=coords_path,
        hall_name=hall_name,
        floor=floor,
        min_games=min_games,
        date_range=date_range,
        weekday=weekday,
    )
    machine_level = merged.sort_values(["machine_number", "date"]).drop_duplicates(subset=["machine_number"]).copy()
    assigned = _attach_kakuban_compat(machine_level)
    assigned = merged.merge(
        assigned[["machine_number", "kakuban", "kakuban_rule", "excluded_from_corr", "is_isolated"]],
        on="machine_number",
        how="left",
        validate="many_to_one",
    )
    sort_columns = ["date", "section", "kakuban", "machine_number"]
    for column in sort_columns:
        if column not in assigned.columns:
            assigned[column] = pd.NA
    return assigned.sort_values(sort_columns).reset_index(drop=True)


def _daily_dispersion_stat(frame: pd.DataFrame, *, value_col: str) -> float:
    if frame.empty:
        return float("nan")
    daily_stats: list[float] = []
    for _, day_frame in frame.groupby("date", dropna=False, sort=False):
        group_means = day_frame.groupby("kakuban", dropna=False)[value_col].mean()
        if group_means.empty:
            continue
        daily_stats.append(float(group_means.var(ddof=0)))
    if not daily_stats:
        return float("nan")
    return float(np.mean(daily_stats))


def compute_kakuban_dispersion_test(
    daily_frame: pd.DataFrame,
    *,
    value_col: str,
    n_permutations: int = 1000,
    seed: int = 42,
) -> dict[str, object]:
    work = daily_frame.copy()
    if "excluded_from_corr" in work.columns:
        work = work[~work["excluded_from_corr"]].copy()
    work = work.dropna(subset=["machine_number", "kakuban", value_col, "date"]).copy()
    if work.empty:
        raise ValueError("daily_frame has no rows after filtering")

    label_map = work[["machine_number", "kakuban"]].drop_duplicates()
    if label_map["machine_number"].duplicated().any():
        dupes = sorted(label_map.loc[label_map["machine_number"].duplicated(), "machine_number"].astype(int).unique().tolist())
        raise ValueError(f"Duplicate machine_number values found in daily_frame: {dupes}")
    if label_map.groupby("machine_number")["kakuban"].nunique().gt(1).any():
        raise ValueError("machine_number -> kakuban mapping is not one-to-one")

    observed_stat = _daily_dispersion_stat(work, value_col=value_col)
    if not np.isfinite(observed_stat):
        raise ValueError("Could not compute observed dispersion statistic")

    unique_labels = label_map["kakuban"].to_numpy(copy=True)
    machine_numbers = label_map["machine_number"].to_numpy(copy=True)
    rng = np.random.default_rng(seed)
    perm_stats = np.empty(n_permutations, dtype=float)
    for idx in range(n_permutations):
        shuffled = rng.permutation(unique_labels)
        perm_map = pd.DataFrame({"machine_number": machine_numbers, "kakuban": shuffled})
        permuted = work.drop(columns=["kakuban"]).merge(perm_map, on="machine_number", how="left", validate="many_to_one")
        perm_stats[idx] = _daily_dispersion_stat(permuted, value_col=value_col)

    p_value = (1.0 + float(np.sum(perm_stats >= observed_stat))) / (n_permutations + 1.0)
    return {
        "observed_stat": float(observed_stat),
        "null_mean": float(np.mean(perm_stats)),
        "null_std": float(np.std(perm_stats, ddof=0)),
        "p_value": float(p_value),
        "n_days": int(work["date"].nunique()),
        "n_machines": int(label_map["machine_number"].nunique()),
        "n_permutations": int(n_permutations),
    }


def build_axis_profile(
    frame: pd.DataFrame,
    *,
    bins: int = 10,
    reflect_x: bool = False,
    value_col: str = "residual_diff",
) -> pd.DataFrame:
    work = frame.copy()
    work["x_axis"] = 1.0 - pd.to_numeric(work["x_norm"], errors="coerce") if reflect_x else pd.to_numeric(work["x_norm"], errors="coerce")
    work["x_axis"] = work["x_axis"].clip(0.0, 0.999999999)
    work["bin_index"] = _bin_index(work["x_axis"], bins)
    profile = (
        work.groupby("bin_index", as_index=False)
        .agg(mean_residual=(value_col, "mean"), machine_count=("machine_number", "nunique"), mean_x=("x_axis", "mean"))
        .set_index("bin_index")
        .reindex(range(bins))
        .reset_index()
    )
    profile["bin_center"] = (profile["bin_index"] + 0.5) / bins
    profile["sample_count"] = profile["machine_count"]
    profile["zscore"] = _zscore(profile["mean_residual"])
    profile["axis"] = "x_reflected" if reflect_x else "x_forward"
    return profile


def build_grid_profile(
    frame: pd.DataFrame,
    *,
    x_bins: int = 5,
    y_bins: int = 5,
    reflect_x: bool = False,
    reflect_y: bool = False,
    value_col: str = "residual_diff",
) -> pd.DataFrame:
    work = frame.copy()
    work["x_axis"] = (1.0 - pd.to_numeric(work["x_norm"], errors="coerce") if reflect_x else pd.to_numeric(work["x_norm"], errors="coerce")).clip(0.0, 0.999999999)
    work["y_axis"] = (1.0 - pd.to_numeric(work["y_norm"], errors="coerce") if reflect_y else pd.to_numeric(work["y_norm"], errors="coerce")).clip(0.0, 0.999999999)
    work["x_bin"] = _bin_index(work["x_axis"], x_bins)
    work["y_bin"] = _bin_index(work["y_axis"], y_bins)
    profile = (
        work.groupby(["y_bin", "x_bin"], as_index=False)
        .agg(mean_residual=(value_col, "mean"), machine_count=("machine_number", "nunique"), mean_x=("x_axis", "mean"), mean_y=("y_axis", "mean"))
        .set_index(["y_bin", "x_bin"])
        .reindex(pd.MultiIndex.from_product([range(y_bins), range(x_bins)], names=["y_bin", "x_bin"]))
        .reset_index()
    )
    profile["bin_index"] = profile["y_bin"] * x_bins + profile["x_bin"]
    profile["sample_count"] = profile["machine_count"]
    profile["zscore"] = _zscore(profile["mean_residual"])
    profile["orientation"] = (
        ("x_reflected" if reflect_x else "x_forward")
        + "_"
        + ("y_reflected" if reflect_y else "y_forward")
    )
    return profile


def summarize_axis_correlations(hall1: pd.DataFrame, hall7: pd.DataFrame, *, bins: int) -> pd.DataFrame:
    forward_1 = build_axis_profile(hall1, bins=bins, reflect_x=False)
    forward_7 = build_axis_profile(hall7, bins=bins, reflect_x=False)
    reflected_7 = build_axis_profile(hall7, bins=bins, reflect_x=True)
    return pd.DataFrame(
        [
            {
                "dimension": "x",
                "orientation": "forward",
                "corr": compare_profile_series(forward_1["zscore"], forward_7["zscore"]),
                "hall1_bins": bins,
                "hall7_bins": bins,
            },
            {
                "dimension": "x",
                "orientation": "x_reflected",
                "corr": compare_profile_series(forward_1["zscore"], reflected_7["zscore"]),
                "hall1_bins": bins,
                "hall7_bins": bins,
            },
        ]
    )


def summarize_grid_correlations(hall1: pd.DataFrame, hall7: pd.DataFrame, *, x_bins: int, y_bins: int) -> pd.DataFrame:
    patterns = [("forward", False, False), ("x_reflected", True, False), ("y_reflected", False, True), ("xy_reflected", True, True)]
    grid_1 = build_grid_profile(hall1, x_bins=x_bins, y_bins=y_bins, reflect_x=False, reflect_y=False)
    rows = []
    for orientation, rx, ry in patterns:
        grid_7 = build_grid_profile(hall7, x_bins=x_bins, y_bins=y_bins, reflect_x=rx, reflect_y=ry)
        rows.append(
            {
                "dimension": "xy",
                "orientation": orientation,
                "corr": compare_profile_series(grid_1["zscore"], grid_7["zscore"]),
                "x_bins": x_bins,
                "y_bins": y_bins,
            }
        )
    return pd.DataFrame(rows)


def summarize_sensitivity_stability(
    *,
    hall1_all: pd.DataFrame,
    hall7_all: pd.DataFrame,
    hall1_common: pd.DataFrame,
    hall7_common: pd.DataFrame,
    axis_bins: Iterable[int] = DEFAULT_AXIS_BIN_SIZES,
    grid_sizes: Iterable[int] = DEFAULT_GRID_SIZES,
    min_corr_gap: float = DEFAULT_MIN_CORR_GAP,
    min_support_rate: float = DEFAULT_MIN_SUPPORT_RATE,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    rows: list[dict[str, object]] = []
    configs: list[dict[str, object]] = []
    for period, left, right in (("all", hall1_all, hall7_all), ("common", hall1_common, hall7_common)):
        for bins in axis_bins:
            forward = build_axis_profile(left, bins=bins, reflect_x=False)
            forward_right = build_axis_profile(right, bins=bins, reflect_x=False)
            reflected = build_axis_profile(right, bins=bins, reflect_x=True)
            corr_forward = compare_profile_series(forward["zscore"], forward_right["zscore"])
            corr_reflected = compare_profile_series(forward["zscore"], reflected["zscore"])
            gap = corr_reflected - corr_forward
            configs.append(
                {
                    "period": period,
                    "dimension": "x",
                    "config_label": f"{bins} bins",
                    "bins_x": bins,
                    "bins_y": np.nan,
                    "forward_corr": corr_forward,
                    "reflected_corr": corr_reflected,
                    "corr_gap": gap,
                    "support_flag": int(np.isfinite(gap) and gap >= min_corr_gap),
                    "preferred_orientation": "x_reflected" if gap > 0 else "forward",
                    "sparse_bin_count": int((forward["sample_count"].fillna(0) <= 2).sum() + (forward_right["sample_count"].fillna(0) <= 2).sum()),
                    "empty_bin_count": int((forward["sample_count"].fillna(0) == 0).sum() + (forward_right["sample_count"].fillna(0) == 0).sum()),
                    "min_bin_count": int(min(forward["sample_count"].fillna(0).min(), forward_right["sample_count"].fillna(0).min())),
                    "median_bin_count": float(np.nanmedian([forward["sample_count"].fillna(0).median(), forward_right["sample_count"].fillna(0).median()])),
                }
            )
        for size in grid_sizes:
            forward = build_grid_profile(left, x_bins=size, y_bins=size, reflect_x=False, reflect_y=False)
            forward_right = build_grid_profile(right, x_bins=size, y_bins=size, reflect_x=False, reflect_y=False)
            x_reflected = build_grid_profile(right, x_bins=size, y_bins=size, reflect_x=True, reflect_y=False)
            y_reflected = build_grid_profile(right, x_bins=size, y_bins=size, reflect_x=False, reflect_y=True)
            xy_reflected = build_grid_profile(right, x_bins=size, y_bins=size, reflect_x=True, reflect_y=True)
            corr_forward = compare_profile_series(forward["zscore"], forward_right["zscore"])
            for orientation, block in [("x_reflected", x_reflected), ("y_reflected", y_reflected), ("xy_reflected", xy_reflected)]:
                corr_reflected = compare_profile_series(forward["zscore"], block["zscore"])
                gap = corr_reflected - corr_forward
                configs.append(
                    {
                        "period": period,
                        "dimension": "xy",
                        "config_label": f"{size}x{size}",
                        "bins_x": size,
                        "bins_y": size,
                        "forward_corr": corr_forward,
                        "reflected_corr": corr_reflected,
                        "corr_gap": gap,
                        "support_flag": int(np.isfinite(gap) and gap >= min_corr_gap),
                        "preferred_orientation": orientation if gap > 0 else "forward",
                        "sparse_bin_count": int((forward["sample_count"].fillna(0) <= 2).sum() + (block["sample_count"].fillna(0) <= 2).sum()),
                        "empty_bin_count": int((forward["sample_count"].fillna(0) == 0).sum() + (block["sample_count"].fillna(0) == 0).sum()),
                        "min_bin_count": int(min(forward["sample_count"].fillna(0).min(), block["sample_count"].fillna(0).min())),
                        "median_bin_count": float(np.nanmedian([forward["sample_count"].fillna(0).median(), block["sample_count"].fillna(0).median()])),
                    }
                )

    detail = pd.DataFrame(configs)
    if detail.empty:
        return detail, pd.DataFrame()
    detail["support_flag"] = detail["support_flag"].astype(int)
    detail["corr_sign"] = np.sign(detail["corr_gap"].fillna(0.0)).astype(int)

    summary_rows: list[dict[str, object]] = []
    for period in detail["period"].dropna().unique().tolist():
        block = detail[detail["period"] == period].copy()
        for dimension in block["dimension"].dropna().unique().tolist():
            sub = block[block["dimension"] == dimension].copy()
            positive_rate = float((sub["corr_gap"] >= min_corr_gap).mean())
            sign_mode = int(sub["corr_sign"].mode().iloc[0]) if not sub["corr_sign"].mode().empty else 0
            sign_consistency = float((sub["corr_sign"] == sign_mode).mean())
            summary_rows.append(
                {
                    "period": period,
                    "dimension": dimension,
                    "n_configs": int(len(sub)),
                    "support_rate": positive_rate,
                    "sign_consistency_rate": sign_consistency,
                    "median_corr_gap": float(sub["corr_gap"].median()),
                    "mean_corr_gap": float(sub["corr_gap"].mean()),
                    "best_corr_gap": float(sub["corr_gap"].max()),
                    "worst_corr_gap": float(sub["corr_gap"].min()),
                    "min_bin_count": int(sub["min_bin_count"].min()),
                    "median_bin_count": float(sub["median_bin_count"].median()),
                    "sparse_bin_count": int(sub["sparse_bin_count"].sum()),
                    "empty_bin_count": int(sub["empty_bin_count"].sum()),
                }
            )
    summary = pd.DataFrame(summary_rows)
    if not summary.empty:
        pivot = summary.pivot(index="dimension", columns="period", values="support_rate")
        for dimension in pivot.index:
            vals = pivot.loc[dimension].dropna()
            summary.loc[summary["dimension"] == dimension, "periods_supported"] = int((vals >= min_support_rate).sum())
            summary.loc[summary["dimension"] == dimension, "mirror_candidate"] = bool(
                (vals >= min_support_rate).all() and summary.loc[summary["dimension"] == dimension, "support_rate"].min() >= min_support_rate
            )
        summary["stability_score"] = summary["support_rate"] * summary["sign_consistency_rate"]
        summary["periods_supported"] = summary["periods_supported"].fillna(0).astype(int)
        summary["mirror_candidate"] = summary["mirror_candidate"].fillna(False).astype(bool)
    summary["min_corr_gap_threshold"] = min_corr_gap
    summary["min_support_rate_threshold"] = min_support_rate
    return detail, summary


def summarize_kakuban_correlations(
    *,
    frames: list[tuple[str, str, str, pd.DataFrame]],
    exclude_isolated: bool = True,
) -> pd.DataFrame:
    rows: list[dict[str, object]] = []

    def _append_row(
        hall: str,
        floor: str,
        period: str,
        frame: pd.DataFrame,
        *,
        row_type: str,
        machine_type_segment: str | None = None,
        n_excluded_isolated: int = 0,
    ) -> None:
        segment_key = f"{floor}_{machine_type_segment}" if machine_type_segment else None
        rows.append(
            {
                "hall": hall,
                "floor": floor,
                "period": period,
                "row_type": row_type,
                "machine_type_segment": machine_type_segment,
                "segment_key": segment_key,
                "n_machines": int(len(frame)),
                "n_excluded_isolated": int(n_excluded_isolated),
                "corr_diff": compare_profile_series(frame["kakuban"], frame["residual_diff"]),
                "corr_games": compare_profile_series(frame["kakuban"], frame["residual_games"]),
            }
        )

    for hall, floor, period, frame in frames:
        work = frame.copy()
        if exclude_isolated and "excluded_from_corr" in work.columns:
            work = work[~work["excluded_from_corr"]].copy()
        work = work[pd.notna(work["kakuban"])].copy()
        work["kakuban"] = pd.to_numeric(work["kakuban"], errors="coerce")
        work = work.dropna(subset=["kakuban", "residual_diff", "residual_games"])
        excluded_count = int(frame["excluded_from_corr"].sum()) if "excluded_from_corr" in frame.columns else 0
        _append_row(hall, floor, period, work, row_type="floor", n_excluded_isolated=excluded_count)
        if "machine_type_segment" in work.columns:
            for machine_type_segment, segment_frame in work.groupby("machine_type_segment", dropna=False, sort=True):
                if pd.isna(machine_type_segment):
                    continue
                _append_row(
                    hall,
                    floor,
                    period,
                    segment_frame,
                    row_type="segment",
                    machine_type_segment=str(machine_type_segment),
                    n_excluded_isolated=excluded_count,
                )
    return pd.DataFrame(rows)


def _compute_kakuban_group_effect(
    frame: pd.DataFrame,
    *,
    group_col: str,
    value_col: str,
    min_group_size: int = 2,
) -> dict[str, object]:
    work = frame.copy()
    work = work.dropna(subset=[group_col, value_col]).copy()
    if work.empty:
        return {
            "epsilon_sq_raw": np.nan,
            "epsilon_sq": np.nan,
            "h_stat": np.nan,
            "p_value": np.nan,
            "n_rows": 0,
            "n_groups": 0,
            "n_machines": int(frame["machine_number"].nunique()) if "machine_number" in frame.columns else 0,
            "low_sample": True,
            "gradient": np.nan,
        }

    grouped_values: list[np.ndarray] = []
    grouped_means: list[tuple[object, float]] = []
    grouped_sizes: list[int] = []
    for label, group in work.groupby(group_col, dropna=False, sort=True):
        values = pd.to_numeric(group[value_col], errors="coerce").dropna().to_numpy(dtype=float)
        if values.size == 0:
            continue
        grouped_values.append(values)
        grouped_means.append((label, float(np.mean(values))))
        grouped_sizes.append(int(values.size))

    n_rows = int(sum(grouped_sizes))
    n_groups = int(len(grouped_values))
    n_machines = int(work["machine_number"].nunique()) if "machine_number" in work.columns else int(work.shape[0])
    low_sample = bool(n_groups < 2 or any(size < min_group_size for size in grouped_sizes))
    if n_groups < 2 or n_rows <= n_groups:
        return {
            "epsilon_sq_raw": np.nan,
            "epsilon_sq": np.nan,
            "h_stat": np.nan,
            "p_value": np.nan,
            "n_rows": n_rows,
            "n_groups": n_groups,
            "n_machines": n_machines,
            "low_sample": True,
            "gradient": np.nan,
        }

    try:
        h_stat, p_value = kruskal(*grouped_values)
    except ValueError:
        return {
            "epsilon_sq_raw": np.nan,
            "epsilon_sq": np.nan,
            "h_stat": np.nan,
            "p_value": np.nan,
            "n_rows": n_rows,
            "n_groups": n_groups,
            "n_machines": n_machines,
            "low_sample": True,
            "gradient": np.nan,
        }

    epsilon_raw = float((h_stat - n_groups + 1) / (n_rows - n_groups))
    epsilon = float(max(0.0, epsilon_raw)) if np.isfinite(epsilon_raw) else np.nan
    if grouped_means:
        ordered_means = sorted(grouped_means, key=lambda item: item[0])
        gradient = float(ordered_means[-1][1] - ordered_means[0][1]) if len(ordered_means) >= 2 else np.nan
    else:
        gradient = np.nan
    return {
        "epsilon_sq_raw": epsilon_raw,
        "epsilon_sq": epsilon,
        "h_stat": float(h_stat),
        "p_value": float(p_value),
        "n_rows": n_rows,
        "n_groups": n_groups,
        "n_machines": n_machines,
        "low_sample": low_sample,
        "gradient": gradient,
    }


def summarize_section_kakuban_epsilon(
    frame: pd.DataFrame,
    *,
    value_col: str = "residual_diff",
    min_group_size: int = 2,
) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame(
            columns=[
                "row_type",
                "section",
                "machine_type_segment",
                "epsilon_sq_raw",
                "epsilon_sq",
                "h_stat",
                "p_value",
                "n_rows",
                "n_groups",
                "n_machines",
                "low_sample",
                "gradient",
            ]
        )

    work = frame.copy()
    work = work.dropna(subset=["section", "kakuban", value_col]).copy()
    if work.empty:
        return pd.DataFrame(
            columns=[
                "row_type",
                "section",
                "machine_type_segment",
                "epsilon_sq_raw",
                "epsilon_sq",
                "h_stat",
                "p_value",
                "n_rows",
                "n_groups",
                "n_machines",
                "low_sample",
                "gradient",
            ]
        )

    work["section"] = work["section"].astype(str).str.strip()
    work["kakuban"] = pd.to_numeric(work["kakuban"], errors="coerce")
    if "machine_type_segment" not in work.columns:
        work["machine_type_segment"] = pd.NA

    rows: list[dict[str, object]] = []
    for section, section_frame in work.groupby("section", dropna=False, sort=True):
        section_effect = _compute_kakuban_group_effect(
            section_frame,
            group_col="kakuban",
            value_col=value_col,
            min_group_size=min_group_size,
        )
        rows.append(
            {
                "row_type": "section",
                "section": section,
                "machine_type_segment": pd.NA,
                **section_effect,
            }
        )
        if "machine_type_segment" not in section_frame.columns:
            continue
        for machine_type_segment, segment_frame in section_frame.groupby("machine_type_segment", dropna=False, sort=True):
            if pd.isna(machine_type_segment):
                continue
            segment_effect = _compute_kakuban_group_effect(
                segment_frame,
                group_col="kakuban",
                value_col=value_col,
                min_group_size=min_group_size,
            )
            rows.append(
                {
                    "row_type": "segment",
                    "section": section,
                    "machine_type_segment": str(machine_type_segment),
                    **segment_effect,
                }
            )

    out = pd.DataFrame(rows)
    if out.empty:
        return out
    out["low_sample"] = out["low_sample"].astype(bool)
    return out.sort_values(["section", "row_type", "machine_type_segment"], na_position="last").reset_index(drop=True)


def summarize_floor_segment_kakuban_epsilon(
    frame: pd.DataFrame,
    *,
    value_col: str = "residual_diff",
    min_group_size: int = 2,
) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame(
            columns=[
                "row_type",
                "section",
                "machine_type_segment",
                "epsilon_sq_raw",
                "epsilon_sq",
                "h_stat",
                "p_value",
                "n_rows",
                "n_groups",
                "n_machines",
                "low_sample",
                "gradient",
            ]
        )

    work = frame.copy()
    work = work.dropna(subset=["machine_type_segment", "kakuban", value_col]).copy()
    if work.empty:
        return pd.DataFrame(
            columns=[
                "row_type",
                "section",
                "machine_type_segment",
                "epsilon_sq_raw",
                "epsilon_sq",
                "h_stat",
                "p_value",
                "n_rows",
                "n_groups",
                "n_machines",
                "low_sample",
                "gradient",
            ]
        )

    work["machine_type_segment"] = work["machine_type_segment"].astype(str).str.strip()
    work["kakuban"] = pd.to_numeric(work["kakuban"], errors="coerce")

    rows: list[dict[str, object]] = []
    for machine_type_segment, segment_frame in work.groupby("machine_type_segment", dropna=False, sort=True):
        if pd.isna(machine_type_segment):
            continue
        segment_effect = _compute_kakuban_group_effect(
            segment_frame,
            group_col="kakuban",
            value_col=value_col,
            min_group_size=min_group_size,
        )
        rows.append(
            {
                "row_type": "floor_segment",
                "section": pd.NA,
                "machine_type_segment": str(machine_type_segment),
                **segment_effect,
            }
        )

    out = pd.DataFrame(rows)
    if out.empty:
        return out
    out["low_sample"] = out["low_sample"].astype(bool)
    return out.sort_values(["machine_type_segment"], na_position="last").reset_index(drop=True)


def _build_kakuban_cat3_work(frame: pd.DataFrame, *, value_col: str) -> pd.DataFrame:
    if frame.empty or value_col not in frame.columns:
        return pd.DataFrame()

    work = frame.copy()
    work = work.dropna(subset=["section", "kakuban", value_col]).copy()
    if work.empty:
        return pd.DataFrame()

    work["section"] = work["section"].astype(str).str.strip()
    work["kakuban"] = pd.to_numeric(work["kakuban"], errors="coerce")
    work["kakuban_max"] = work.groupby("section")["kakuban"].transform("max")
    work["kakuban_cat3"] = np.select(
        [work["kakuban"].eq(1), work["kakuban"].eq(work["kakuban_max"])],
        ["near", "far"],
        default="mid",
    )
    work["kakuban_cat3"] = pd.Categorical(work["kakuban_cat3"], categories=["near", "mid", "far"], ordered=True)
    return work


def _summarize_section_kakuban_cat3_value(frame: pd.DataFrame, *, value_col: str) -> pd.DataFrame:
    work = _build_kakuban_cat3_work(frame, value_col=value_col)
    if work.empty:
        return pd.DataFrame(
            columns=["section", "kakuban_cat3", "mean_value", "n", "n_machines", "kakuban_min", "kakuban_max", "value_col"]
        )

    out = (
        work.groupby(["section", "kakuban_cat3"], as_index=False)
        .agg(
            mean_value=(value_col, "mean"),
            n=("machine_number", "size"),
            n_machines=("machine_number", "nunique"),
            kakuban_min=("kakuban", "min"),
            kakuban_max=("kakuban", "max"),
        )
        .sort_values(["section", "kakuban_cat3"])
        .reset_index(drop=True)
    )
    out["kakuban_cat3"] = out["kakuban_cat3"].astype(str)
    out["value_col"] = value_col
    return out


def summarize_section_kakuban_cat3(frame: pd.DataFrame, *, value_col: str = "residual_diff") -> pd.DataFrame:
    out = _summarize_section_kakuban_cat3_value(frame, value_col=value_col)
    if out.empty:
        if value_col == "residual_diff":
            return pd.DataFrame(columns=["section", "kakuban_cat3", "mean_residual_diff", "n", "n_machines", "kakuban_min", "kakuban_max"])
        return out
    if value_col == "residual_diff":
        out = out.rename(columns={"mean_value": "mean_residual_diff"}).drop(columns=["value_col"])
    return out


def _summarize_floor_segment_kakuban_cat3_value(frame: pd.DataFrame, *, value_col: str) -> pd.DataFrame:
    columns = [
        "value_col",
        "kakuban_cat3_near_mean",
        "kakuban_cat3_near_n",
        "kakuban_cat3_mid_mean",
        "kakuban_cat3_mid_n",
        "kakuban_cat3_far_mean",
        "kakuban_cat3_far_n",
        "epsilon_sq_3cat",
        "p_value_3cat",
        "low_sample",
        "n_rows_total",
        "n_groups",
        "n_machines",
    ]
    if frame.empty or value_col not in frame.columns:
        return pd.DataFrame(columns=columns)

    work = _build_kakuban_cat3_work(frame, value_col=value_col)
    if work.empty:
        return pd.DataFrame(columns=columns)

    effect = _compute_kakuban_group_effect(
        work,
        group_col="kakuban_cat3",
        value_col=value_col,
        min_group_size=2,
    )

    rows: dict[str, object] = {
        "value_col": value_col,
        "epsilon_sq_3cat": effect["epsilon_sq"],
        "p_value_3cat": effect["p_value"],
        "low_sample": bool(effect["low_sample"]),
        "n_rows_total": int(effect["n_rows"]),
        "n_groups": int(effect["n_groups"]),
        "n_machines": int(effect["n_machines"]),
    }
    for label in ("near", "mid", "far"):
        subset = work[work["kakuban_cat3"].astype(str) == label]
        values = pd.to_numeric(subset["residual_diff"], errors="coerce").dropna()
        n = int(values.size)
        rows[f"kakuban_cat3_{label}_mean"] = float(values.mean()) if n else np.nan
        rows[f"kakuban_cat3_{label}_n"] = n

    return pd.DataFrame([rows], columns=columns)


def summarize_floor_segment_kakuban_cat3(frame: pd.DataFrame, *, value_col: str = "residual_diff") -> pd.DataFrame:
    out = _summarize_floor_segment_kakuban_cat3_value(frame, value_col=value_col)
    if out.empty:
        if value_col == "residual_diff":
            return pd.DataFrame(
                columns=[
                    "kakuban_cat3_near_mean",
                    "kakuban_cat3_near_n",
                    "kakuban_cat3_mid_mean",
                    "kakuban_cat3_mid_n",
                    "kakuban_cat3_far_mean",
                    "kakuban_cat3_far_n",
                    "epsilon_sq_3cat",
                    "p_value_3cat",
                    "low_sample",
                    "n_rows_total",
                    "n_groups",
                    "n_machines",
                ]
            )
        return out
    if value_col == "residual_diff":
        out = out.drop(columns=["value_col"])
    return out


def summarize_section_kakuban_fixed_effects(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame(
            columns=[
                "section",
                "kakuban",
                "n",
                "n_machine_names",
                "top_machine_name",
                "top_machine_name_count",
                "machine_name_share",
                "mean_residual_diff",
            ]
        )

    work = frame.copy()
    work = work.dropna(subset=["section", "kakuban", "machine_name", "residual_diff"]).copy()
    if work.empty:
        return pd.DataFrame(
            columns=[
                "section",
                "kakuban",
                "n",
                "n_machine_names",
                "top_machine_name",
                "top_machine_name_count",
                "machine_name_share",
                "mean_residual_diff",
            ]
        )

    work["section"] = work["section"].astype(str).str.strip()
    work["kakuban"] = pd.to_numeric(work["kakuban"], errors="coerce")

    rows: list[dict[str, object]] = []
    for (section, kakuban), group in work.groupby(["section", "kakuban"], dropna=False, sort=True):
        name_counts = group["machine_name"].astype(str).value_counts(dropna=False)
        top_machine_name = str(name_counts.index[0]) if not name_counts.empty else ""
        top_machine_name_count = int(name_counts.iloc[0]) if not name_counts.empty else 0
        n = int(len(group))
        rows.append(
            {
                "section": section,
                "kakuban": int(kakuban) if pd.notna(kakuban) else pd.NA,
                "n": n,
                "n_machine_names": int(group["machine_name"].nunique()),
                "top_machine_name": top_machine_name,
                "top_machine_name_count": top_machine_name_count,
                "machine_name_share": float(top_machine_name_count / n) if n else np.nan,
                "mean_residual_diff": float(group["residual_diff"].mean()),
            }
        )

    out = pd.DataFrame(rows)
    if out.empty:
        return out
    return out.sort_values(["section", "kakuban"]).reset_index(drop=True)


def _pick_comparable_sections(
    frame: pd.DataFrame,
    *,
    target_section: str,
    min_size_ratio: float = 0.7,
    max_size_ratio: float = 1.3,
) -> list[str]:
    if "section" not in frame.columns:
        return []
    section_stats = (
        frame.groupby("section", dropna=False)
        .agg(section_size=("machine_number", "nunique"), mean_x=("X", "mean"))
        .reset_index()
    )
    target = section_stats[section_stats["section"] == target_section]
    if target.empty:
        return []
    target_size = float(target["section_size"].iloc[0])
    floor_median_x = float(section_stats["mean_x"].median())
    candidates = section_stats[
        (section_stats["section"] != target_section)
        & (section_stats["mean_x"] >= floor_median_x)
        & (section_stats["section_size"] >= max(1, int(np.floor(target_size * min_size_ratio))))
        & (section_stats["section_size"] <= max(1, int(np.ceil(target_size * max_size_ratio))))
    ].copy()
    candidates["size_delta"] = (candidates["section_size"] - target_size).abs()
    return candidates.sort_values(["size_delta", "mean_x"], ascending=[True, False])["section"].tolist()


def build_kakuban_detail_frame(
    frame: pd.DataFrame,
    *,
    hall_label: str,
    floor: str,
    exclude_isolated: bool = True,
) -> pd.DataFrame:
    assigned = _attach_kakuban_compat(frame)
    columns = ["machine_number", "section", "X", "Y", "kakuban", "residual_diff", "residual_games", "mean_games", "excluded_from_corr"]
    for column in columns:
        if column not in assigned.columns:
            assigned[column] = np.nan
    return assigned[columns].sort_values(["section", "kakuban", "machine_number"]).reset_index(drop=True)


def build_kakuban_descriptive_comparison(
    frame: pd.DataFrame,
    *,
    hall_label: str,
    floor: str,
    period: str,
    target_sections: list[str],
) -> pd.DataFrame:
    assigned = _attach_kakuban_compat(frame)
    rows: list[pd.DataFrame] = []
    for target_section in target_sections:
        comparison_sections = [target_section] + _pick_comparable_sections(assigned, target_section=target_section)
        subset = assigned[assigned["section"].isin(comparison_sections)].copy()
        if subset.empty:
            continue
        subset["block_role"] = np.where(subset["section"] == target_section, "target", "comparison")
        summary = (
            subset.groupby(["block_role", "section", "kakuban"], as_index=False)
            .agg(mean_residual_diff=("residual_diff", "mean"), mean_residual_games=("residual_games", "mean"), n_machines=("machine_number", "nunique"))
        )
        summary["hall"] = hall_label
        summary["floor"] = floor
        summary["period"] = period
        summary["target_section"] = target_section
        rows.append(summary)
    if not rows:
        return pd.DataFrame()
    return pd.concat(rows, ignore_index=True)


def _format_date_key(value: pd.Timestamp | str) -> str:
    return pd.to_datetime(value).strftime("%Y%m%d")


def _summarize_machine_name_transitions(
    *,
    db_path: Path,
    machine_numbers: list[int],
    section_lookup: pd.DataFrame,
    date_range: tuple[pd.Timestamp | str, pd.Timestamp | str],
) -> pd.DataFrame:
    if not machine_numbers:
        return pd.DataFrame(
            columns=[
                "section",
                "position",
                "machine_number",
                "segment_id",
                "machine_name",
                "segment_start",
                "segment_end",
                "n_days",
                "avg_diff",
                "avg_games",
                "segment_count",
                "change_count",
                "dominant_segment_share",
            ]
        )

    machine_numbers = [int(number) for number in sorted(set(machine_numbers))]
    placeholders = ", ".join(["?"] * len(machine_numbers))
    start_key = _format_date_key(date_range[0])
    end_key = _format_date_key(date_range[1])
    query = f"""
        WITH ordered AS (
            SELECT
                machine_number,
                date,
                machine_name,
                diff_coins_normalized,
                games_normalized,
                CASE
                    WHEN machine_name = LAG(machine_name) OVER (
                        PARTITION BY machine_number ORDER BY date
                    ) THEN 0 ELSE 1
                END AS is_new_segment
            FROM machine_detailed_results
            WHERE machine_number IN ({placeholders})
              AND date BETWEEN ? AND ?
        ),
        segmented AS (
            SELECT
                *,
                SUM(is_new_segment) OVER (
                    PARTITION BY machine_number ORDER BY date
                ) AS segment_id
            FROM ordered
        )
        SELECT
            machine_number,
            segment_id,
            machine_name,
            MIN(date) AS segment_start,
            MAX(date) AS segment_end,
            COUNT(*) AS n_days,
            AVG(diff_coins_normalized) AS avg_diff,
            AVG(games_normalized) AS avg_games
        FROM segmented
        GROUP BY machine_number, segment_id, machine_name
        ORDER BY machine_number, segment_start
    """

    with sqlite3.connect(db_path) as conn:
        transitions = pd.read_sql_query(query, conn, params=[*machine_numbers, start_key, end_key])

    if transitions.empty:
        return pd.DataFrame(
            columns=[
                "section",
                "position",
                "machine_number",
                "segment_id",
                "machine_name",
                "segment_start",
                "segment_end",
                "n_days",
                "avg_diff",
                "avg_games",
                "segment_count",
                "change_count",
                "dominant_segment_share",
            ]
        )

    transitions["segment_id"] = pd.to_numeric(transitions["segment_id"], errors="coerce").astype("Int64")
    transitions["n_days"] = pd.to_numeric(transitions["n_days"], errors="coerce").astype("Int64")
    transitions["segment_start"] = pd.to_datetime(transitions["segment_start"], format="%Y%m%d", errors="coerce")
    transitions["segment_end"] = pd.to_datetime(transitions["segment_end"], format="%Y%m%d", errors="coerce")
    transitions["machine_number"] = pd.to_numeric(transitions["machine_number"], errors="coerce").astype("Int64")
    transitions["avg_diff"] = pd.to_numeric(transitions["avg_diff"], errors="coerce")
    transitions["avg_games"] = pd.to_numeric(transitions["avg_games"], errors="coerce")

    segment_stats = (
        transitions.groupby("machine_number", as_index=False)
        .agg(
            segment_count=("segment_id", "nunique"),
            max_segment_days=("n_days", "max"),
            total_days=("n_days", "sum"),
        )
        .assign(
            change_count=lambda df: df["segment_count"] - 1,
            dominant_segment_share=lambda df: df["max_segment_days"] / df["total_days"],
        )
    )
    transitions = transitions.merge(segment_stats[["machine_number", "segment_count", "change_count", "dominant_segment_share"]], on="machine_number", how="left")

    lookup = section_lookup.copy()
    lookup["machine_number"] = pd.to_numeric(lookup["machine_number"], errors="coerce").astype("Int64")
    lookup["section"] = lookup["section"].astype(str)
    if "kakuban_cat3" in lookup.columns:
        lookup["position"] = lookup["kakuban_cat3"].astype(str)
    elif "position" not in lookup.columns:
        lookup["position"] = pd.NA

    out = transitions.merge(lookup[["machine_number", "section", "position"]], on="machine_number", how="left")
    out = out[
        [
            "section",
            "position",
            "machine_number",
            "segment_id",
            "machine_name",
            "segment_start",
            "segment_end",
            "n_days",
            "avg_diff",
            "avg_games",
            "segment_count",
            "change_count",
            "dominant_segment_share",
        ]
    ].sort_values(["section", "position", "machine_number", "segment_start"]).reset_index(drop=True)
    return out


def run_analysis(
    *,
    hall1: HallSpec,
    hall7: HallSpec,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    min_games: int = 1500,
    x_bins: int = 10,
    y_bins: int = 5,
    weekday: str | int | None = None,
    n_permutations: int = 1000,
    seed: int = 42,
) -> dict[str, pd.DataFrame]:
    output_dir.mkdir(parents=True, exist_ok=True)
    weekday_name, _ = _normalize_weekday_filter(weekday)
    output_prefix = f"{weekday_name}_" if weekday_name is not None else ""
    hall1_label = _resolve_hall_label(hall1.hall_name)
    hall7_label = _resolve_hall_label(hall7.hall_name)

    hall1_all = load_hall_frame(
        db_path=hall1.db_path,
        coords_path=hall1.coords_path,
        hall_name=hall1.hall_name,
        min_games=min_games,
        weekday=weekday_name,
    )
    hall7_all = load_hall_frame(
        db_path=hall7.db_path,
        coords_path=hall7.coords_path,
        hall_name=hall7.hall_name,
        min_games=min_games,
        weekday=weekday_name,
    )

    start1, end1 = _read_date_bounds(hall1.db_path)
    start7, end7 = _read_date_bounds(hall7.db_path)
    common_range = (max(start1, start7), min(end1, end7))

    hall1_common = load_hall_frame(
        db_path=hall1.db_path,
        coords_path=hall1.coords_path,
        hall_name=hall1.hall_name,
        min_games=min_games,
        date_range=common_range,
        weekday=weekday_name,
    )
    hall7_common = load_hall_frame(
        db_path=hall7.db_path,
        coords_path=hall7.coords_path,
        hall_name=hall7.hall_name,
        min_games=min_games,
        date_range=common_range,
        weekday=weekday_name,
    )

    hall7_3f_coords = PROJECT_ROOT / "Heatmap" / "3F_floor_coordinates_kamata7.csv"
    hall7_3f_name = infer_hall_name(hall7_3f_coords, floor="3F")
    hall7_3f = HallSpec(hall_name=hall7_3f_name, db_path=hall7.db_path, coords_path=hall7_3f_coords)
    hall7_3f_all = load_hall_frame(
        db_path=hall7_3f.db_path,
        coords_path=hall7_3f.coords_path,
        hall_name=hall7_3f.hall_name,
        floor="3F",
        min_games=min_games,
        weekday=weekday_name,
    )
    hall7_3f_h2 = load_hall_frame(
        db_path=hall7_3f.db_path,
        coords_path=hall7_3f.coords_path,
        hall_name=hall7_3f.hall_name,
        floor="3F",
        min_games=min_games,
        date_range=(DEFAULT_H2_START, DEFAULT_H2_END),
        weekday=weekday_name,
    )

    axis_all = summarize_axis_correlations(hall1_all, hall7_all, bins=x_bins)
    axis_common = summarize_axis_correlations(hall1_common, hall7_common, bins=x_bins)
    grid_all = summarize_grid_correlations(hall1_all, hall7_all, x_bins=max(2, x_bins // 2), y_bins=y_bins)
    grid_common = summarize_grid_correlations(hall1_common, hall7_common, x_bins=max(2, x_bins // 2), y_bins=y_bins)
    stability_detail, stability_summary = summarize_sensitivity_stability(
        hall1_all=hall1_all,
        hall7_all=hall7_all,
        hall1_common=hall1_common,
        hall7_common=hall7_common,
    )

    hall1_h2 = load_hall_frame(
        db_path=hall1.db_path,
        coords_path=hall1.coords_path,
        hall_name=hall1.hall_name,
        floor="2F",
        min_games=min_games,
        date_range=(DEFAULT_H2_START, DEFAULT_H2_END),
        weekday=weekday_name,
    )
    hall7_h2 = load_hall_frame(
        db_path=hall7.db_path,
        coords_path=hall7.coords_path,
        hall_name=hall7.hall_name,
        floor="2F",
        min_games=min_games,
        date_range=(DEFAULT_H2_START, DEFAULT_H2_END),
        weekday=weekday_name,
    )

    kakuban_period_frames: list[tuple[str, str, str, pd.DataFrame]] = []
    kakuban_detail_frames: list[tuple[str, str, pd.DataFrame]] = []
    kakuban_assigned_frames: dict[tuple[str, str, str], pd.DataFrame] = {}
    kakuban_assigned_daily_frames: dict[tuple[str, str], pd.DataFrame] = {}
    for hall_label, floor, hall_spec, frame_all, frame_h2 in [
        (hall1_label, "2F", hall1, hall1_all, hall1_h2),
        (hall7_label, "2F", hall7, hall7_all, hall7_h2),
        (hall7_label, "3F", hall7_3f, hall7_3f_all, hall7_3f_h2),
    ]:
        for period, frame in (("all", frame_all), ("2025H2", frame_h2)):
            assigned = _attach_kakuban_compat(frame)
            kakuban_assigned_frames[(hall_label, floor, period)] = assigned
            kakuban_period_frames.append((hall_label, floor, period, assigned))
            if period == "all":
                kakuban_detail_frames.append((hall_label, floor, build_kakuban_detail_frame(assigned, hall_label=hall_label, floor=floor)))
        daily_assigned = load_hall_daily_frame(
            db_path=hall_spec.db_path,
            coords_path=hall_spec.coords_path,
            hall_name=hall_spec.hall_name,
            floor=floor,
            min_games=min_games,
            weekday=None,
        )
        kakuban_assigned_daily_frames[(hall_label, floor)] = daily_assigned

    kakuban_corr = summarize_kakuban_correlations(frames=kakuban_period_frames, exclude_isolated=True)
    if not kakuban_corr.empty:
        kakuban_corr = kakuban_corr[["hall", "floor", "period", "row_type", "machine_type_segment", "segment_key", "n_machines", "corr_diff", "corr_games", "n_excluded_isolated"]]

    kakuban_dispersion = pd.DataFrame()
    if weekday_name is not None:
        dispersion_rows: list[dict[str, object]] = []

        def _add_dispersion_rows(*, hall_label: str, floor: str, period: str, daily_frame: pd.DataFrame) -> None:
            work = daily_frame.copy()
            if "excluded_from_corr" in work.columns:
                work = work[~work["excluded_from_corr"]].copy()
            row_frames: list[tuple[str, pd.DataFrame, str | None]] = [("floor", work, None)]
            if "machine_type_segment" in work.columns:
                for machine_type_segment, segment_frame in work.groupby("machine_type_segment", dropna=False, sort=True):
                    if pd.isna(machine_type_segment):
                        continue
                    row_frames.append(("segment", segment_frame.copy(), str(machine_type_segment)))
            for row_type, subset, machine_type_segment in row_frames:
                if subset.empty:
                    continue
                segment_key = f"{floor}_{machine_type_segment}" if machine_type_segment else None
                for value_col in ("residual_diff", "residual_games"):
                    result = compute_kakuban_dispersion_test(
                        subset,
                        value_col=value_col,
                        n_permutations=n_permutations,
                        seed=seed,
                    )
                    dispersion_rows.append(
                        {
                            "hall": hall_label,
                            "floor": floor,
                            "period": period,
                            "row_type": row_type,
                            "machine_type_segment": machine_type_segment,
                            "segment_key": segment_key,
                            "value_col": value_col,
                            **result,
                        }
                    )

        for hall_label, floor, hall_spec in [
            (hall1_label, "2F", hall1),
            (hall7_label, "2F", hall7),
            (hall7_label, "3F", hall7_3f),
        ]:
            daily_all = load_hall_daily_frame(
                db_path=hall_spec.db_path,
                coords_path=hall_spec.coords_path,
                hall_name=hall_spec.hall_name,
                floor=floor,
                min_games=min_games,
                weekday=weekday_name,
            )
            _add_dispersion_rows(hall_label=hall_label, floor=floor, period="all", daily_frame=daily_all)

            daily_h2 = load_hall_daily_frame(
                db_path=hall_spec.db_path,
                coords_path=hall_spec.coords_path,
                hall_name=hall_spec.hall_name,
                floor=floor,
                min_games=min_games,
                date_range=(DEFAULT_H2_START, DEFAULT_H2_END),
                weekday=weekday_name,
            )
            _add_dispersion_rows(hall_label=hall_label, floor=floor, period="2025H2", daily_frame=daily_h2)

        kakuban_dispersion = pd.DataFrame(dispersion_rows)

    kakuban_descriptive = pd.concat(
        [
            build_kakuban_descriptive_comparison(hall7_h2, hall_label=hall7_label, floor="2F", period="2025H2", target_sections=["2330-2351"]),
            build_kakuban_descriptive_comparison(hall7_3f_h2, hall_label=hall7_label, floor="3F", period="2025H2", target_sections=["3341-3362"]),
        ],
        ignore_index=True,
    )

    section_kakuban_epsilon_frames: list[pd.DataFrame] = []
    section_kakuban_epsilon_daily_frames: list[pd.DataFrame] = []
    floor_segment_kakuban_epsilon_frames: list[pd.DataFrame] = []
    floor_segment_kakuban_epsilon_daily_frames: list[pd.DataFrame] = []
    segment_kakuban_epsilon_frames: list[pd.DataFrame] = []
    section_kakuban_cat3_frames: list[pd.DataFrame] = []
    floor_segment_kakuban_cat3_frames: list[pd.DataFrame] = []
    section_kakuban_cat3_games_frames: list[pd.DataFrame] = []
    floor_segment_kakuban_cat3_games_frames: list[pd.DataFrame] = []
    near_far_transition_frames: list[pd.DataFrame] = []
    section_kakuban_fixed_effect_frames: list[pd.DataFrame] = []
    for hall_label, floor, period in [
        (hall1_label, "2F", "all"),
        (hall7_label, "2F", "all"),
        (hall7_label, "3F", "all"),
    ]:
        file_slug = "kamata1" if hall_label == hall1_label else "kamata7"
        assigned = kakuban_assigned_frames[(hall_label, floor, period)].copy()
        daily_assigned = kakuban_assigned_daily_frames[(hall_label, floor)].copy()

        for suffix, frame, collector, writer in [
            ("", assigned, section_kakuban_epsilon_frames, f"kamata_section_kakuban_epsilon_{file_slug}_{floor}.csv"),
            ("_daily", daily_assigned, section_kakuban_epsilon_daily_frames, f"kamata_section_kakuban_epsilon_daily_{file_slug}_{floor}.csv"),
        ]:
            work = frame[frame["excluded_from_corr"].eq(False)].copy() if "excluded_from_corr" in frame.columns else frame.copy()
            if work.empty:
                continue
            epsilon = summarize_section_kakuban_epsilon(work, value_col="residual_diff", min_group_size=2)
            if epsilon.empty:
                continue
            epsilon.insert(0, "hall", hall_label)
            epsilon.insert(1, "floor", floor)
            epsilon.insert(2, "period", period + suffix)
            collector.append(epsilon)
            epsilon.to_csv(output_dir / writer, index=False, encoding="utf-8-sig")

            if suffix == "":
                segment_epsilon = epsilon[epsilon["row_type"].eq("segment")].copy()
                if not segment_epsilon.empty:
                    segment_kakuban_epsilon_frames.append(segment_epsilon)
                    segment_epsilon.to_csv(output_dir / f"kamata_segment_kakuban_epsilon_{file_slug}_{floor}.csv", index=False, encoding="utf-8-sig")

            floor_segment = summarize_floor_segment_kakuban_epsilon(work, value_col="residual_diff", min_group_size=2)
            if not floor_segment.empty:
                floor_segment.insert(0, "hall", hall_label)
                floor_segment.insert(1, "floor", floor)
                floor_segment.insert(2, "period", period + suffix)
                if suffix == "":
                    floor_segment_kakuban_epsilon_frames.append(floor_segment)
                    floor_segment.to_csv(output_dir / f"kamata_floor_segment_kakuban_epsilon_{file_slug}_{floor}.csv", index=False, encoding="utf-8-sig")
                else:
                    floor_segment_kakuban_epsilon_daily_frames.append(floor_segment)
                    floor_segment.to_csv(output_dir / f"kamata_floor_segment_kakuban_epsilon_daily_{file_slug}_{floor}.csv", index=False, encoding="utf-8-sig")

        if hall_label == hall7_label and floor == "3F":
            cat3_work = daily_assigned.copy()
            cat3_work = cat3_work[cat3_work["excluded_from_corr"].eq(False)].copy() if "excluded_from_corr" in cat3_work.columns else cat3_work.copy()
            cat3_work = cat3_work[cat3_work["machine_type_segment"].eq("A")].copy() if "machine_type_segment" in cat3_work.columns else cat3_work.copy()
            if not cat3_work.empty:
                cat3_section_lookup = (
                    _build_kakuban_cat3_work(cat3_work, value_col="residual_diff")[["section", "machine_number", "kakuban_cat3"]]
                    .drop_duplicates()
                    .copy()
                )

                cat3_by_section = summarize_section_kakuban_cat3(cat3_work)
                if not cat3_by_section.empty:
                    cat3_by_section.insert(0, "hall", hall_label)
                    cat3_by_section.insert(1, "floor", floor)
                    cat3_by_section.insert(2, "period", "all_daily")
                    cat3_by_section.to_csv(output_dir / "kamata7_3F_typeA_kakuban_cat3_by_section.csv", index=False, encoding="utf-8-sig")
                    section_kakuban_cat3_frames.append(cat3_by_section)

                cat3_global = summarize_floor_segment_kakuban_cat3(cat3_work)
                if not cat3_global.empty:
                    cat3_global.insert(0, "hall", hall_label)
                    cat3_global.insert(1, "floor", floor)
                    cat3_global.insert(2, "period", "all_daily")
                    floor_segment_kakuban_cat3_frames.append(cat3_global)
                    cat3_global.to_csv(output_dir / "kamata7_3F_typeA_kakuban_cat3_global.csv", index=False, encoding="utf-8-sig")

                games_section_frames: list[pd.DataFrame] = []
                games_global_frames: list[pd.DataFrame] = []
                for value_col in ("residual_games", "games_normalized"):
                    by_section_games = _summarize_section_kakuban_cat3_value(cat3_work, value_col=value_col)
                    if not by_section_games.empty:
                        by_section_games.insert(0, "hall", hall_label)
                        by_section_games.insert(1, "floor", floor)
                        by_section_games.insert(2, "period", "all_daily")
                        games_section_frames.append(by_section_games)
                    global_games = _summarize_floor_segment_kakuban_cat3_value(cat3_work, value_col=value_col)
                    if not global_games.empty:
                        global_games.insert(0, "hall", hall_label)
                        global_games.insert(1, "floor", floor)
                        global_games.insert(2, "period", "all_daily")
                        games_global_frames.append(global_games)

                if games_section_frames:
                    section_games = pd.concat(games_section_frames, ignore_index=True)
                    section_games.to_csv(output_dir / "kamata7_3F_typeA_kakuban_cat3_by_section_games.csv", index=False, encoding="utf-8-sig")
                    section_kakuban_cat3_games_frames.append(section_games)
                else:
                    section_games = pd.DataFrame()

                if games_global_frames:
                    global_games = pd.concat(games_global_frames, ignore_index=True)
                    global_games.to_csv(output_dir / "kamata7_3F_typeA_kakuban_cat3_global_games.csv", index=False, encoding="utf-8-sig")
                    floor_segment_kakuban_cat3_games_frames.append(global_games)
                else:
                    global_games = pd.DataFrame()

                transition_rows = _summarize_machine_name_transitions(
                    db_path=hall7_3f.db_path,
                    machine_numbers=cat3_section_lookup.loc[cat3_section_lookup["kakuban_cat3"].isin(["near", "far"]), "machine_number"].dropna().astype(int).tolist(),
                    section_lookup=cat3_section_lookup.loc[cat3_section_lookup["kakuban_cat3"].isin(["near", "far"])].copy(),
                    date_range=(pd.to_datetime(cat3_work["date"].min()), pd.to_datetime(cat3_work["date"].max())),
                )
                if not transition_rows.empty:
                    transition_rows.to_csv(output_dir / "kamata7_3F_typeA_near_far_machine_transitions.csv", index=False, encoding="utf-8-sig")
                    near_far_transition_frames.append(transition_rows)
                    fixed_share_count = int((transition_rows.groupby("machine_number")["dominant_segment_share"].max() >= 0.8).sum())
                    print(
                        "[cat3 follow-up] near/far transitions:",
                        f"machines={transition_rows['machine_number'].nunique()}",
                        f"fixed_share_ge_0.8={fixed_share_count}",
                        f"segment_count_values={transition_rows.groupby('machine_number')['segment_count'].max().value_counts().sort_index().to_dict()}",
                    )

        if assigned.empty:
            continue
        assigned = assigned[assigned["excluded_from_corr"].eq(False)].copy()
        if assigned.empty:
            continue

        cat3 = summarize_section_kakuban_cat3(assigned)
        if not cat3.empty:
            cat3.insert(0, "hall", hall_label)
            cat3.insert(1, "floor", floor)
            cat3.insert(2, "period", period)
            section_kakuban_cat3_frames.append(cat3)
            cat3.to_csv(output_dir / f"kamata_section_kakuban_cat3_{file_slug}_{floor}.csv", index=False, encoding="utf-8-sig")

        fixed_effects = summarize_section_kakuban_fixed_effects(assigned)
        if not fixed_effects.empty:
            fixed_effects.insert(0, "hall", hall_label)
            fixed_effects.insert(1, "floor", floor)
            fixed_effects.insert(2, "period", period)
            section_kakuban_fixed_effect_frames.append(fixed_effects)
            fixed_effects.to_csv(output_dir / f"kamata_section_kakuban_fixed_effects_{file_slug}_{floor}.csv", index=False, encoding="utf-8-sig")

    summary = pd.concat(
        [
            axis_all.assign(period="all"),
            axis_common.assign(period="common"),
            grid_all.assign(period="all"),
            grid_common.assign(period="common"),
        ],
        ignore_index=True,
    )
    summary["min_games"] = min_games
    summary["hall1"] = hall1.hall_name
    summary["hall7"] = hall7.hall_name
    summary["common_start"] = _format_date_key(common_range[0])
    summary["common_end"] = _format_date_key(common_range[1])

    hall1_all.to_csv(output_dir / "kamata1_machine_frame_all.csv", index=False, encoding="utf-8-sig")
    hall7_all.to_csv(output_dir / "kamata7_machine_frame_all.csv", index=False, encoding="utf-8-sig")
    hall1_common.to_csv(output_dir / "kamata1_machine_frame_common.csv", index=False, encoding="utf-8-sig")
    hall7_common.to_csv(output_dir / "kamata7_machine_frame_common.csv", index=False, encoding="utf-8-sig")
    axis_all.to_csv(output_dir / f"{output_prefix}kamata_corner_mirror_axis_all.csv", index=False, encoding="utf-8-sig")
    axis_common.to_csv(output_dir / f"{output_prefix}kamata_corner_mirror_axis_common.csv", index=False, encoding="utf-8-sig")
    grid_all.to_csv(output_dir / f"{output_prefix}kamata_corner_mirror_grid_all.csv", index=False, encoding="utf-8-sig")
    grid_common.to_csv(output_dir / f"{output_prefix}kamata_corner_mirror_grid_common.csv", index=False, encoding="utf-8-sig")
    stability_detail.to_csv(output_dir / f"{output_prefix}kamata_corner_mirror_sensitivity_detail.csv", index=False, encoding="utf-8-sig")
    stability_summary.to_csv(output_dir / f"{output_prefix}kamata_corner_mirror_stability_summary.csv", index=False, encoding="utf-8-sig")
    summary.to_csv(output_dir / f"{output_prefix}kamata_corner_mirror_summary.csv", index=False, encoding="utf-8-sig")
    if not kakuban_corr.empty:
        kakuban_corr.to_csv(output_dir / f"{output_prefix}kamata_corner_mirror_kakuban_correlation.csv", index=False, encoding="utf-8-sig")
    if weekday_name is not None:
        kakuban_dispersion.to_csv(output_dir / f"{output_prefix}kamata_corner_mirror_kakuban_dispersion.csv", index=False, encoding="utf-8-sig")
    for hall_label, floor, detail_frame in kakuban_detail_frames:
        file_slug = "kamata1" if hall_label == hall1_label else "kamata7"
        detail_frame[["machine_number", "section", "X", "Y", "kakuban", "residual_diff", "residual_games", "mean_games"]].to_csv(
            output_dir / f"{output_prefix}kamata_corner_mirror_kakuban_{file_slug}_{floor}.csv",
            index=False,
            encoding="utf-8-sig",
        )
    if not kakuban_descriptive.empty:
        kakuban_descriptive.to_csv(output_dir / f"{output_prefix}kamata_corner_mirror_kakuban_right_block_descriptive.csv", index=False, encoding="utf-8-sig")

    _maybe_save_plot(summary, output_dir)
    _print_summary(summary)

    return {
        "hall1_all": hall1_all,
        "hall7_all": hall7_all,
        "hall1_common": hall1_common,
        "hall7_common": hall7_common,
        "axis_all": axis_all,
        "axis_common": axis_common,
        "grid_all": grid_all,
        "grid_common": grid_common,
        "stability_detail": stability_detail,
        "stability_summary": stability_summary,
        "kakuban_corr": kakuban_corr,
        "kakuban_dispersion": kakuban_dispersion,
        "kakuban_descriptive": kakuban_descriptive,
        "section_kakuban_epsilon": pd.concat(section_kakuban_epsilon_frames, ignore_index=True) if section_kakuban_epsilon_frames else pd.DataFrame(),
        "section_kakuban_epsilon_daily": pd.concat(section_kakuban_epsilon_daily_frames, ignore_index=True) if section_kakuban_epsilon_daily_frames else pd.DataFrame(),
        "floor_segment_kakuban_epsilon": pd.concat(floor_segment_kakuban_epsilon_frames, ignore_index=True) if floor_segment_kakuban_epsilon_frames else pd.DataFrame(),
        "floor_segment_kakuban_epsilon_daily": pd.concat(floor_segment_kakuban_epsilon_daily_frames, ignore_index=True) if floor_segment_kakuban_epsilon_daily_frames else pd.DataFrame(),
        "segment_kakuban_epsilon": pd.concat(segment_kakuban_epsilon_frames, ignore_index=True) if segment_kakuban_epsilon_frames else pd.DataFrame(),
        "section_kakuban_cat3": pd.concat(section_kakuban_cat3_frames, ignore_index=True) if section_kakuban_cat3_frames else pd.DataFrame(),
        "floor_segment_kakuban_cat3": pd.concat(floor_segment_kakuban_cat3_frames, ignore_index=True) if floor_segment_kakuban_cat3_frames else pd.DataFrame(),
        "section_kakuban_cat3_games": pd.concat(section_kakuban_cat3_games_frames, ignore_index=True) if section_kakuban_cat3_games_frames else pd.DataFrame(),
        "floor_segment_kakuban_cat3_games": pd.concat(floor_segment_kakuban_cat3_games_frames, ignore_index=True) if floor_segment_kakuban_cat3_games_frames else pd.DataFrame(),
        "near_far_machine_transitions": pd.concat(near_far_transition_frames, ignore_index=True) if near_far_transition_frames else pd.DataFrame(),
        "section_kakuban_fixed_effects": pd.concat(section_kakuban_fixed_effect_frames, ignore_index=True) if section_kakuban_fixed_effect_frames else pd.DataFrame(),
        "summary": summary,
    }

def _maybe_save_plot(summary: pd.DataFrame, output_dir: Path) -> None:
    try:
        import matplotlib.pyplot as plt
    except Exception:
        return
    x_summary = summary[summary["dimension"] == "x"].copy()
    xy_summary = summary[summary["dimension"] == "xy"].copy()
    fig, axes = plt.subplots(2, 1, figsize=(10, 8), constrained_layout=True)
    for ax, block, title in [
        (axes[0], x_summary, "1D X-axis correlations"),
        (axes[1], xy_summary, "2D X/Y correlations"),
    ]:
        if block.empty:
            ax.set_axis_off()
            continue
        labels = [f"{period}-{orientation}" for period, orientation in zip(block["period"], block["orientation"])]
        ax.bar(labels, block["corr"], color=["#7c3aed" if "reflected" in orientation else "#0f766e" for orientation in block["orientation"]])
        ax.axhline(0.0, color="black", linewidth=0.8)
        ax.set_title(title)
        ax.set_ylim(-1.05, 1.05)
        ax.tick_params(axis="x", rotation=20)
        ax.grid(True, axis="y", alpha=0.2)
    fig.suptitle("Kamata corner mirror analysis")
    fig.savefig(output_dir / "kamata_corner_mirror_profiles.png", dpi=160)
    plt.close(fig)


def _print_summary(summary: pd.DataFrame) -> None:
    print("=" * 80)
    print("Kamata1 / Kamata7 corner mirror summary")
    print("=" * 80)
    for period in ("all", "common"):
        block = summary[summary["period"] == period].copy()
        print(f"\n[{period}]")
        print(block[["dimension", "orientation", "corr"]].to_string(index=False))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Kamata1 / Kamata7 corner mirror analysis")
    parser.add_argument("--db1", type=Path, default=DEFAULT_DB_1)
    parser.add_argument("--db7", type=Path, default=DEFAULT_DB_7)
    parser.add_argument("--coords1", type=Path, default=DEFAULT_COORDS_1)
    parser.add_argument("--coords7", type=Path, default=DEFAULT_COORDS_7)
    parser.add_argument("--min-games", type=int, default=1500)
    parser.add_argument("--x-bins", type=int, default=10)
    parser.add_argument("--y-bins", type=int, default=5)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--weekday", type=str, default=None, help="Optional weekday filter such as Tuesday")
    parser.add_argument("--n-permutations", type=int, default=1000)
    parser.add_argument("--seed", type=int, default=42)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    hall1_name = infer_hall_name(args.coords1, floor="2F")
    hall7_name = infer_hall_name(args.coords7, floor="2F")
    hall1 = HallSpec(hall_name=hall1_name, db_path=args.db1, coords_path=args.coords1)
    hall7 = HallSpec(hall_name=hall7_name, db_path=args.db7, coords_path=args.coords7)
    run_analysis(
        hall1=hall1,
        hall7=hall7,
        output_dir=args.output_dir,
        min_games=args.min_games,
        x_bins=args.x_bins,
        y_bins=args.y_bins,
        weekday=args.weekday,
        n_permutations=args.n_permutations,
        seed=args.seed,
    )


if __name__ == "__main__":
    main()
