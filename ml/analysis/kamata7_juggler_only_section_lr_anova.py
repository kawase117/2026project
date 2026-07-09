from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

if __package__ is None or __package__ == "":
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from ml.analysis.kamata_corner_mirror_analysis import (  # noqa: E402
    _read_coordinates,
    _read_machine_master_flags,
    _read_raw_results,
    infer_hall_name,
)
from ml.analysis.kamata_kakuban_section_residual_eda import _section_size_group  # noqa: E402

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB_7 = PROJECT_ROOT / "db" / "マルハンメガシティ2000-蒲田7.db"
DEFAULT_COORDS_7_3F = PROJECT_ROOT / "Heatmap" / "3F_floor_coordinates_kamata7.csv"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "ml" / "analysis" / "results" / "kamata7_kakuban_section_lr_interaction"
DEFAULT_OUTPUT_FILE = DEFAULT_OUTPUT_DIR / "kamata7_juggler_only_f_values.csv"
MIN_GAMES = 500
EXCLUDED_MACHINE_NUMBERS = {2026}
EXCLUDED_MMDD = {"0707"}


def _resolve_default_db7() -> Path:
    candidates = [
        path for path in (PROJECT_ROOT / "db").glob("*蒲田7*.db") if path.is_file() and path.stat().st_size > 0
    ]
    if candidates:
        return sorted(candidates, key=lambda path: path.stat().st_size, reverse=True)[0]
    return DEFAULT_DB_7


def _calc_pay_rate(games_sum: pd.Series, diff_sum: pd.Series) -> pd.Series:
    denom = pd.to_numeric(games_sum, errors="coerce") * 3
    denom = denom.replace(0, np.nan)
    return ((denom + pd.to_numeric(diff_sum, errors="coerce")) / denom) * 100


def _assign_section_side_lr(frame: pd.DataFrame) -> pd.Series:
    side_lr = pd.Series("R", index=frame.index, dtype="string")
    if frame.empty or "section" not in frame.columns or "X" not in frame.columns:
        return side_lr

    for section, section_frame in frame.groupby("section", dropna=False, sort=False):
        if pd.isna(section):
            continue
        x_values = pd.to_numeric(section_frame["X"], errors="coerce")
        valid = x_values.dropna()
        if valid.empty:
            continue
        median_x = float(valid.median())
        side_lr.loc[section_frame.index] = np.where(x_values < median_x, "L", "R")
    return side_lr


def _anova_f_value(frame: pd.DataFrame, group_col: str) -> float:
    if frame.empty or group_col not in frame.columns or "pay_rate" not in frame.columns:
        return float("nan")

    groups: list[np.ndarray] = []
    for _, group in frame.dropna(subset=[group_col, "pay_rate"]).groupby(group_col, sort=True):
        values = pd.to_numeric(group["pay_rate"], errors="coerce").dropna().astype(float).to_numpy()
        if len(values) > 0:
            groups.append(values)

    if len(groups) < 2 or any(len(values) < 2 for values in groups):
        return float("nan")

    try:
        return float(stats.f_oneway(*groups).statistic)
    except ValueError:
        return float("nan")


def build_juggler_only_frame(*, db_path: Path, coords_path: Path) -> pd.DataFrame:
    hall_name = infer_hall_name(coords_path, floor="3F")
    raw = _read_raw_results(db_path)
    coords = _read_coordinates(coords_path, hall_name=hall_name, floor="3F")
    machine_master = _read_machine_master_flags(db_path)

    raw["date"] = pd.to_datetime(raw["date"], format="%Y%m%d", errors="coerce")
    raw["machine_number"] = pd.to_numeric(raw["machine_number"], errors="coerce")
    raw["diff_coins_normalized"] = pd.to_numeric(raw["diff_coins_normalized"], errors="coerce")
    raw["games_normalized"] = pd.to_numeric(raw["games_normalized"], errors="coerce")
    raw = raw.dropna(subset=["date", "machine_number", "diff_coins_normalized", "games_normalized"]).copy()
    raw["machine_number"] = raw["machine_number"].astype(int)
    raw["date"] = raw["date"].dt.normalize()
    raw["mmdd"] = raw["date"].dt.strftime("%m%d")

    coords = coords.copy()
    coords["section"] = coords["section"].fillna("unknown").astype(str)
    section_size_lookup = coords.groupby("section", dropna=False)["machine_number"].nunique()

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

    for column in ("jug_flag", "hana_flag", "bt_flag"):
        merged[column] = pd.to_numeric(merged[column], errors="coerce").fillna(0).astype(int)
    merged["machine_name"] = merged["machine_name"].astype(str)
    merged["section"] = merged["section"].fillna("unknown").astype(str)
    merged["section_size"] = merged["section"].map(section_size_lookup)
    merged["section_size"] = pd.to_numeric(merged["section_size"], errors="coerce").astype("Int64")
    merged["section_size_group"] = merged["section_size"].map(_section_size_group)
    merged["pay_rate"] = _calc_pay_rate(merged["games_normalized"], merged["diff_coins_normalized"])

    is_juggler = merged["jug_flag"].eq(1) | merged["machine_name"].str.contains("ジャグ", na=False)
    merged = merged[
        merged["games_normalized"].ge(MIN_GAMES)
        & merged["machine_number"].ne(2026)
        & merged["mmdd"].ne("0707")
        & is_juggler
    ].copy()
    if merged.empty:
        raise ValueError("No juggler-only rows remained after applying the filters")

    merged["side_lr"] = _assign_section_side_lr(merged)
    return merged.reset_index(drop=True)


def build_juggler_only_f_values(frame: pd.DataFrame) -> pd.DataFrame:
    work = frame.copy()
    section_size_f = _anova_f_value(work, "section_size_group")
    lr_f = _anova_f_value(work, "side_lr")
    return pd.DataFrame(
        [
            {
                "hall": "蒲田7",
                "floor": "3F",
                "population": "juggler_only",
                "n_rows": int(len(work)),
                "n_sections": int(work["section"].nunique(dropna=True)) if "section" in work.columns else 0,
                "n_machines": int(work["machine_number"].nunique(dropna=True))
                if "machine_number" in work.columns
                else 0,
                "section_size_f": section_size_f,
                "lr_f": lr_f,
                "section_size_better": bool(section_size_f > lr_f)
                if not (pd.isna(section_size_f) or pd.isna(lr_f))
                else pd.NA,
            }
        ]
    )


def run_juggler_only_anova(*, db_path: Path, coords_path: Path, output_file: Path) -> pd.DataFrame:
    frame = build_juggler_only_frame(db_path=db_path, coords_path=coords_path)
    summary = build_juggler_only_f_values(frame)
    output_file.parent.mkdir(parents=True, exist_ok=True)
    summary.to_csv(output_file, index=False, encoding="utf-8-sig")
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="蒲田7 3F ジャグラー専用 section_size vs LR ANOVA")
    parser.add_argument("--db", type=Path, default=_resolve_default_db7(), help="Database path")
    parser.add_argument("--coords-3f", type=Path, default=DEFAULT_COORDS_7_3F, help="3F coordinates CSV")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_FILE, help="Output CSV path")
    args = parser.parse_args(argv)

    summary = run_juggler_only_anova(db_path=args.db, coords_path=args.coords_3f, output_file=args.output)
    row = summary.iloc[0]
    print(f"[OK] wrote {args.output}")
    print(
        f"n_rows={int(row['n_rows'])} n_sections={int(row['n_sections'])} "
        f"section_size_f={row['section_size_f']} lr_f={row['lr_f']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
