"""
モンキーターンV・スマスロ北斗の拳について、ホール別×機種別の
DD(日付の日)ごとの RB 確率(rb_probability_decimal)をスキャンする。

  - 全期間 DD別RB確率プロファイル
  - 直近60日(既定)ウィンドウ DD別RB確率プロファイル

の二軸を比較し、DD ランキングの Spearman 相関と Kruskal-Wallis 効果量で
「最近だけ強いDD」「安定して強いDD」などの傾向を判定する。
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import kruskal, spearmanr

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if __package__ in {None, ""}:
    sys.path.insert(0, str(PROJECT_ROOT))

from eda.core import DB_DIR, HALL_DBS, _epsilon_squared

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

warnings.filterwarnings("ignore")

TARGET_MACHINES = ["モンキーターンV", "スマスロ北斗の拳"]
DEFAULT_HALLS = list(HALL_DBS.keys())
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "eda" / "results" / "monkey_hokuto_dd_rb_trend"
MIN_GAMES = 2000
RECENT_WINDOW_DAYS = 60
DD_LEVELS = list(range(1, 32))
MIN_CELL_N_FOR_DD = 5
MIN_MACHINE_DAYS_FULL = 150
MIN_MACHINE_DAYS_RECENT = 30
MIN_COMMON_DD_LEVELS = 8
EFFECT_SIZE_THRESHOLD = 0.02

PROFILE_COLUMNS = [
    "hall",
    "machine_name",
    "period",
    "dd",
    "n",
    "rb_rate_pooled",
    "rb_rate_mean",
]

SUMMARY_COLUMNS = [
    "hall",
    "machine_name",
    "full_range",
    "full_n",
    "full_kruskal_p",
    "full_effect_size",
    "full_top_dd",
    "recent_range",
    "recent_n",
    "recent_kruskal_p",
    "recent_effect_size",
    "recent_top_dd",
    "n_common_dd_levels",
    "spearman_rho",
    "spearman_p",
    "verdict",
    "note",
]

VERDICT_ORDER = ["no_signal", "recent_drift", "stable_dd_bias", "faded", "insufficient"]


def _parse_halls(value: str) -> list[str]:
    halls = [item.strip() for item in value.split(",") if item.strip()]
    if not halls:
        raise argparse.ArgumentTypeError("halls must not be empty")
    return halls


def _ensure_output_dir(output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir


def load_target_machine_frame(hall_name: str) -> pd.DataFrame:
    """対象2機種の機械レベルデータを RB 確率つきで読み込む。"""
    if hall_name not in HALL_DBS:
        raise ValueError(f"unknown hall: {hall_name!r}. available={list(HALL_DBS)}")

    db_path = DB_DIR / HALL_DBS[hall_name]
    conn = sqlite3.connect(db_path)
    query = f"""
    SELECT
        m.date,
        m.machine_name,
        m.machine_number,
        m.games_normalized       AS games,
        m.rb_count               AS rb_count,
        m.rb_probability_decimal AS rb_prob,
        m.diff_coins_normalized  AS diff
    FROM machine_detailed_results m
    WHERE m.games_normalized >= {MIN_GAMES}
      AND m.machine_name IN ('モンキーターンV', 'スマスロ北斗の拳')
      AND m.rb_probability_decimal IS NOT NULL
      AND m.rb_probability_decimal > 0
    """
    df = pd.read_sql_query(query, conn)
    conn.close()

    if df.empty:
        return df

    df["date_ts"] = pd.to_datetime(df["date"].astype(str), format="%Y%m%d", errors="coerce")
    df = df.loc[df["date_ts"].notna()].copy()
    df["dd"] = df["date_ts"].dt.day
    df["hall"] = hall_name
    return df


def _format_range(frame: pd.DataFrame) -> str:
    if frame.empty:
        return "empty"
    dates = frame["date_ts"].dropna()
    if dates.empty:
        return "empty"
    return f"{dates.min().date()}~{dates.max().date()}"


def _dd_profile(frame: pd.DataFrame, *, hall: str, machine_name: str, period: str) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame(columns=PROFILE_COLUMNS)
    grouped = frame.groupby("dd").agg(
        n=("rb_prob", "size"),
        rb_sum=("rb_count", "sum"),
        games_sum=("games", "sum"),
        rb_rate_mean=("rb_prob", "mean"),
    )
    grouped = grouped.reindex(DD_LEVELS)
    grouped["rb_rate_pooled"] = grouped["rb_sum"] / grouped["games_sum"].replace(0, np.nan)
    grouped = grouped.reset_index().rename(columns={"index": "dd"})
    grouped["hall"] = hall
    grouped["machine_name"] = machine_name
    grouped["period"] = period
    return grouped[PROFILE_COLUMNS]


def _kruskal_on_rb(frame: pd.DataFrame, *, min_cell_n: int) -> dict:
    groups = []
    for _, sub in frame.groupby("dd"):
        vals = sub["rb_prob"].dropna().to_numpy()
        if len(vals) >= min_cell_n:
            groups.append(vals)
    if len(groups) < 2:
        return {"p_value": np.nan, "effect_size": np.nan, "n_groups": len(groups)}
    stat, p_value = kruskal(*groups)
    n_obs = sum(len(g) for g in groups)
    eps_sq = _epsilon_squared(float(stat), len(groups), n_obs)
    return {"p_value": float(p_value), "effect_size": float(eps_sq), "n_groups": len(groups)}


def _top_dd(profile: pd.DataFrame, *, min_cell_n: int) -> object:
    valid = profile.loc[profile["n"] >= min_cell_n, ["dd", "rb_rate_pooled"]].dropna()
    if valid.empty:
        return np.nan
    return int(valid.loc[valid["rb_rate_pooled"].idxmax(), "dd"])


def analyze_machine(
    hall: str,
    machine_name: str,
    machine_frame: pd.DataFrame,
    *,
    recent_window_days: int,
    min_machine_days_full: int,
    min_machine_days_recent: int,
    min_cell_n_for_dd: int,
    min_common_dd_levels: int,
) -> tuple[dict, pd.DataFrame]:
    max_date = machine_frame["date_ts"].max()
    recent_start = max_date - pd.Timedelta(days=recent_window_days - 1)
    recent_frame = machine_frame.loc[machine_frame["date_ts"] >= recent_start].copy()

    full_n = int(len(machine_frame))
    recent_n = int(len(recent_frame))

    row = {
        "hall": hall,
        "machine_name": machine_name,
        "full_range": _format_range(machine_frame),
        "full_n": full_n,
        "recent_range": _format_range(recent_frame),
        "recent_n": recent_n,
    }
    profiles = []

    if full_n < min_machine_days_full:
        row.update(
            {
                "full_kruskal_p": np.nan,
                "full_effect_size": np.nan,
                "full_top_dd": np.nan,
                "recent_kruskal_p": np.nan,
                "recent_effect_size": np.nan,
                "recent_top_dd": np.nan,
                "n_common_dd_levels": np.nan,
                "spearman_rho": np.nan,
                "spearman_p": np.nan,
                "verdict": "insufficient",
                "note": f"full_n={full_n} < {min_machine_days_full}",
            }
        )
        empty_profiles = pd.DataFrame(columns=PROFILE_COLUMNS)
        return row, pd.concat(profiles, ignore_index=True) if profiles else empty_profiles

    full_profile = _dd_profile(machine_frame, hall=hall, machine_name=machine_name, period="full")
    full_stats = _kruskal_on_rb(machine_frame, min_cell_n=min_cell_n_for_dd)
    full_top_dd = _top_dd(full_profile, min_cell_n=min_cell_n_for_dd)
    profiles.append(full_profile)

    row["full_kruskal_p"] = full_stats["p_value"]
    row["full_effect_size"] = full_stats["effect_size"]
    row["full_top_dd"] = full_top_dd

    if recent_n < min_machine_days_recent:
        row.update(
            {
                "recent_kruskal_p": np.nan,
                "recent_effect_size": np.nan,
                "recent_top_dd": np.nan,
                "n_common_dd_levels": np.nan,
                "spearman_rho": np.nan,
                "spearman_p": np.nan,
                "verdict": "insufficient",
                "note": f"recent_n={recent_n} < {min_machine_days_recent}",
            }
        )
        return row, pd.concat(profiles, ignore_index=True)

    recent_profile = _dd_profile(recent_frame, hall=hall, machine_name=machine_name, period="recent60d")
    recent_stats = _kruskal_on_rb(recent_frame, min_cell_n=min_cell_n_for_dd)
    recent_top_dd = _top_dd(recent_profile, min_cell_n=min_cell_n_for_dd)
    profiles.append(recent_profile)

    row["recent_kruskal_p"] = recent_stats["p_value"]
    row["recent_effect_size"] = recent_stats["effect_size"]
    row["recent_top_dd"] = recent_top_dd

    full_indexed = full_profile.set_index("dd")
    recent_indexed = recent_profile.set_index("dd")
    full_vec = full_indexed["rb_rate_pooled"].where(full_indexed["n"] >= min_cell_n_for_dd)
    recent_vec = recent_indexed["rb_rate_pooled"].where(recent_indexed["n"] >= min_cell_n_for_dd)
    common_mask = full_vec.notna() & recent_vec.notna()
    n_common = int(common_mask.sum())
    row["n_common_dd_levels"] = n_common

    note_parts = []
    rho, p_rho = np.nan, np.nan
    if n_common < min_common_dd_levels:
        note_parts.append(f"n_common_dd_levels={n_common} < {min_common_dd_levels}")
    else:
        rho, p_rho = spearmanr(full_vec.loc[common_mask].to_numpy(), recent_vec.loc[common_mask].to_numpy())
    row["spearman_rho"] = float(rho) if pd.notna(rho) else np.nan
    row["spearman_p"] = float(p_rho) if pd.notna(p_rho) else np.nan

    full_has_signal = pd.notna(row["full_effect_size"]) and row["full_effect_size"] >= EFFECT_SIZE_THRESHOLD
    recent_has_signal = pd.notna(row["recent_effect_size"]) and row["recent_effect_size"] >= EFFECT_SIZE_THRESHOLD
    stable = pd.notna(rho) and rho >= 0.4

    if not full_has_signal and not recent_has_signal:
        verdict = "no_signal"
    elif full_has_signal and recent_has_signal and stable:
        verdict = "stable_dd_bias"
    elif recent_has_signal and (not full_has_signal or not stable):
        verdict = "recent_drift"
    elif full_has_signal and not recent_has_signal:
        verdict = "faded"
    else:
        verdict = "no_signal"
    row["verdict"] = verdict
    row["note"] = "; ".join(note_parts)

    return row, pd.concat(profiles, ignore_index=True)


def build_hall_outputs(
    hall: str,
    raw: pd.DataFrame,
    *,
    recent_window_days: int = RECENT_WINDOW_DAYS,
    min_machine_days_full: int = MIN_MACHINE_DAYS_FULL,
    min_machine_days_recent: int = MIN_MACHINE_DAYS_RECENT,
    min_cell_n_for_dd: int = MIN_CELL_N_FOR_DD,
    min_common_dd_levels: int = MIN_COMMON_DD_LEVELS,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    if raw.empty:
        return pd.DataFrame(columns=SUMMARY_COLUMNS), pd.DataFrame(columns=PROFILE_COLUMNS)

    summary_rows = []
    profile_frames = []
    for machine_name, machine_frame in raw.groupby("machine_name", sort=True):
        row, profiles = analyze_machine(
            hall,
            str(machine_name),
            machine_frame.copy(),
            recent_window_days=recent_window_days,
            min_machine_days_full=min_machine_days_full,
            min_machine_days_recent=min_machine_days_recent,
            min_cell_n_for_dd=min_cell_n_for_dd,
            min_common_dd_levels=min_common_dd_levels,
        )
        summary_rows.append(row)
        if not profiles.empty:
            profile_frames.append(profiles)

    summary = pd.DataFrame(summary_rows, columns=SUMMARY_COLUMNS)
    summary = summary.sort_values(["machine_name"], kind="mergesort").reset_index(drop=True)
    profile = pd.concat(profile_frames, ignore_index=True) if profile_frames else pd.DataFrame(columns=PROFILE_COLUMNS)
    return summary, profile


def _write_csv(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False, encoding="utf-8-sig")


def _print_hall_report(hall: str, summary: pd.DataFrame) -> None:
    print(f"\n=== {hall} ===")
    if summary.empty:
        print("no eligible machines")
        return
    cols = [
        "machine_name",
        "full_n",
        "full_effect_size",
        "full_top_dd",
        "recent_n",
        "recent_effect_size",
        "recent_top_dd",
        "spearman_rho",
        "verdict",
    ]
    print(summary.loc[:, cols].to_string(index=False))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="モンキーターンV・スマスロ北斗の拳のホール別DD別RB確率スキャン (全期間 vs 直近60日)"
    )
    parser.add_argument("--halls", type=_parse_halls, default=DEFAULT_HALLS)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--recent-window-days", type=int, default=RECENT_WINDOW_DAYS)
    parser.add_argument("--min-machine-days-full", type=int, default=MIN_MACHINE_DAYS_FULL)
    parser.add_argument("--min-machine-days-recent", type=int, default=MIN_MACHINE_DAYS_RECENT)
    parser.add_argument("--min-cell-n-for-dd", type=int, default=MIN_CELL_N_FOR_DD)
    parser.add_argument("--min-common-dd-levels", type=int, default=MIN_COMMON_DD_LEVELS)
    args = parser.parse_args(argv)

    output_dir = _ensure_output_dir(args.output_dir)
    all_summaries = []
    all_profiles = []

    for hall in args.halls:
        if hall not in HALL_DBS:
            raise ValueError(f"unknown hall: {hall}")
        raw = load_target_machine_frame(hall)
        summary, profile = build_hall_outputs(
            hall,
            raw,
            recent_window_days=args.recent_window_days,
            min_machine_days_full=args.min_machine_days_full,
            min_machine_days_recent=args.min_machine_days_recent,
            min_cell_n_for_dd=args.min_cell_n_for_dd,
            min_common_dd_levels=args.min_common_dd_levels,
        )
        _write_csv(summary, output_dir / f"{hall}_summary.csv")
        _write_csv(profile, output_dir / f"{hall}_dd_profile.csv")
        _print_hall_report(hall, summary)
        all_summaries.append(summary)
        all_profiles.append(profile)

    all_summary = (
        pd.concat(all_summaries, ignore_index=True) if all_summaries else pd.DataFrame(columns=SUMMARY_COLUMNS)
    )
    all_profile = pd.concat(all_profiles, ignore_index=True) if all_profiles else pd.DataFrame(columns=PROFILE_COLUMNS)
    _write_csv(all_summary, output_dir / "all_halls_summary.csv")
    _write_csv(all_profile, output_dir / "all_halls_dd_profile.csv")

    verdict_counts = (
        all_summary["verdict"].value_counts().reindex(VERDICT_ORDER, fill_value=0)
        if not all_summary.empty
        else pd.Series(0, index=VERDICT_ORDER, dtype="int64")
    )

    print(f"\n{'=' * 70}")
    print("verdict breakdown")
    print("=" * 70)
    print(verdict_counts.to_string())
    insufficient_n = int(verdict_counts.get("insufficient", 0))
    print(f"\ninsufficient n={insufficient_n}")
    print(f"summary_rows={len(all_summary)}")
    print(f"\nwritten: {output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
