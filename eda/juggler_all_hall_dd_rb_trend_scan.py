"""
全ジャグラー機種 × 全ホール × DD(日付の日) を、RB確率(rb_probability_decimal)を
指標にスキャンする。各 (hall, machine_name) について

  - 全体期間 DD別RB確率プロファイル
  - 直近60日(約2か月)ウィンドウ DD別RB確率プロファイル

の両方を作り、DDランキングのSpearman一致度で「固定的な強いDD」なのか
「直近で変化している(ランダム化/トレンド変更)」なのかを判定する。

ホール横断でのプール集計は行わない（ホールごとに独立した戦略が前提）。
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

DEFAULT_HALLS = list(HALL_DBS.keys())
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "eda" / "results" / "juggler_dd_rb_trend"
MIN_GAMES = 2000
RECENT_WINDOW_DAYS = 60  # 「直近二か月」
DD_LEVELS = list(range(1, 32))
MIN_CELL_N_FOR_DD = 5
MIN_MACHINE_DAYS_FULL = 150
MIN_MACHINE_DAYS_RECENT = 30
MIN_COMMON_DD_LEVELS = 8
EFFECT_SIZE_THRESHOLD = 0.02  # RB確率は分散が小さいため diff 系より緩い閾値

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


def _parse_halls(value: str) -> list[str]:
    halls = [item.strip() for item in value.split(",") if item.strip()]
    if not halls:
        raise argparse.ArgumentTypeError("halls must not be empty")
    return halls


def _ensure_output_dir(output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir


def load_jug_frame(hall_name: str) -> pd.DataFrame:
    """ホール内の全ジャグラー系機種の台レベルデータをRB確率付きで読み込む。"""
    if hall_name not in HALL_DBS:
        raise ValueError(f"不明なホール: {hall_name!r}. 利用可能: {list(HALL_DBS)}")

    db_path = DB_DIR / HALL_DBS[hall_name]
    conn = sqlite3.connect(db_path)
    query = f"""
    SELECT
        m.date,
        m.machine_name,
        m.machine_number,
        m.games_normalized      AS games,
        m.rb_count              AS rb_count,
        m.rb_probability_decimal AS rb_prob,
        m.diff_coins_normalized AS diff
    FROM machine_detailed_results m
    WHERE m.games_normalized >= {MIN_GAMES}
      AND m.machine_name LIKE '%ジャグラー%'
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
        return row, pd.concat(profiles, ignore_index=True) if profiles else pd.DataFrame(columns=PROFILE_COLUMNS)

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
                "verdict": "recent_insufficient",
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

    full_vec = full_profile.set_index("dd")["rb_rate_pooled"].where(
        full_profile.set_index("dd")["n"] >= min_cell_n_for_dd
    )
    recent_vec = recent_profile.set_index("dd")["rb_rate_pooled"].where(
        recent_profile.set_index("dd")["n"] >= min_cell_n_for_dd
    )
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
        verdict = "weak_or_mixed"
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


POOLED_PROFILE_COLUMNS = ["hall", "period", "dd", "n", "rb_rate_pooled", "rb_rate_mean"]
POOLED_SUMMARY_COLUMNS = [
    "hall",
    "full_range",
    "full_n",
    "full_kruskal_p",
    "full_effect_size",
    "full_top_dd",
    "full_top3_dd",
    "recent_range",
    "recent_n",
    "recent_kruskal_p",
    "recent_effect_size",
    "recent_top_dd",
    "recent_top3_dd",
    "n_common_dd_levels",
    "spearman_rho",
    "spearman_p",
    "verdict",
]
FIVE_SERIES_DD = {5, 15, 25}


def _top_n_dd(profile: pd.DataFrame, *, min_cell_n: int, top_n: int = 3) -> list:
    valid = profile.loc[profile["n"] >= min_cell_n, ["dd", "rb_rate_pooled"]].dropna()
    if valid.empty:
        return []
    return [int(d) for d in valid.sort_values("rb_rate_pooled", ascending=False)["dd"].head(top_n).tolist()]


def build_hall_pooled_dd_profile(
    hall: str,
    raw: pd.DataFrame,
    *,
    recent_window_days: int = RECENT_WINDOW_DAYS,
    min_cell_n_for_dd: int = MIN_CELL_N_FOR_DD,
    min_common_dd_levels: int = MIN_COMMON_DD_LEVELS,
) -> tuple[dict, pd.DataFrame]:
    """全ジャグラー機種をホール内で合算し、DD別RB確率を見る（「5のつく日」仮説の検証用）。"""
    if raw.empty:
        row = {c: np.nan for c in POOLED_SUMMARY_COLUMNS}
        row["hall"] = hall
        row["verdict"] = "empty"
        return row, pd.DataFrame(columns=POOLED_PROFILE_COLUMNS)

    max_date = raw["date_ts"].max()
    recent_start = max_date - pd.Timedelta(days=recent_window_days - 1)
    recent_frame = raw.loc[raw["date_ts"] >= recent_start].copy()

    full_profile = _dd_profile(raw, hall=hall, machine_name="ALL_JUG", period="full")[
        ["dd", "n", "rb_rate_pooled", "rb_rate_mean"]
    ].copy()
    full_profile.insert(0, "period", "full")
    full_profile.insert(0, "hall", hall)

    recent_profile = _dd_profile(recent_frame, hall=hall, machine_name="ALL_JUG", period="recent60d")[
        ["dd", "n", "rb_rate_pooled", "rb_rate_mean"]
    ].copy()
    recent_profile.insert(0, "period", "recent60d")
    recent_profile.insert(0, "hall", hall)

    full_stats = _kruskal_on_rb(raw, min_cell_n=min_cell_n_for_dd)
    recent_stats = _kruskal_on_rb(recent_frame, min_cell_n=min_cell_n_for_dd)

    full_vec = full_profile.set_index("dd")["rb_rate_pooled"].where(
        full_profile.set_index("dd")["n"] >= min_cell_n_for_dd
    )
    recent_vec = recent_profile.set_index("dd")["rb_rate_pooled"].where(
        recent_profile.set_index("dd")["n"] >= min_cell_n_for_dd
    )
    common_mask = full_vec.notna() & recent_vec.notna()
    n_common = int(common_mask.sum())

    rho, p_rho = np.nan, np.nan
    if n_common >= min_common_dd_levels:
        rho, p_rho = spearmanr(full_vec.loc[common_mask].to_numpy(), recent_vec.loc[common_mask].to_numpy())

    full_has_signal = pd.notna(full_stats["p_value"]) and full_stats["effect_size"] >= EFFECT_SIZE_THRESHOLD
    recent_has_signal = pd.notna(recent_stats["p_value"]) and recent_stats["effect_size"] >= EFFECT_SIZE_THRESHOLD
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
        verdict = "weak_or_mixed"

    row = {
        "hall": hall,
        "full_range": _format_range(raw),
        "full_n": int(len(raw)),
        "full_kruskal_p": full_stats["p_value"],
        "full_effect_size": full_stats["effect_size"],
        "full_top_dd": _top_dd(full_profile, min_cell_n=min_cell_n_for_dd),
        "full_top3_dd": _top_n_dd(full_profile, min_cell_n=min_cell_n_for_dd),
        "recent_range": _format_range(recent_frame),
        "recent_n": int(len(recent_frame)),
        "recent_kruskal_p": recent_stats["p_value"],
        "recent_effect_size": recent_stats["effect_size"],
        "recent_top_dd": _top_dd(recent_profile, min_cell_n=min_cell_n_for_dd),
        "recent_top3_dd": _top_n_dd(recent_profile, min_cell_n=min_cell_n_for_dd),
        "n_common_dd_levels": n_common,
        "spearman_rho": float(rho) if pd.notna(rho) else np.nan,
        "spearman_p": float(p_rho) if pd.notna(p_rho) else np.nan,
        "verdict": verdict,
    }
    profile = pd.concat([full_profile, recent_profile], ignore_index=True)
    return row, profile


def _print_pooled_report(pooled_summary: pd.DataFrame) -> None:
    print(f"\n{'=' * 70}")
    print("ホール単位で全ジャグラー機種を合算したDD別RB確率（5のつく日仮説の検証）")
    print('=' * 70)
    if pooled_summary.empty:
        print("no data")
        return
    cols = [
        "hall",
        "full_n",
        "full_effect_size",
        "full_top_dd",
        "full_top3_dd",
        "recent_n",
        "recent_effect_size",
        "recent_top_dd",
        "recent_top3_dd",
        "spearman_rho",
        "verdict",
    ]
    print(pooled_summary.loc[:, cols].to_string(index=False))


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
        description="全ジャグラー機種×全ホール×DD別 RB確率スキャン（全体期間 vs 直近60日）"
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
    pooled_rows = []
    pooled_profiles = []

    for hall in args.halls:
        if hall not in HALL_DBS:
            raise ValueError(f"unknown hall: {hall}")
        raw = load_jug_frame(hall)
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

        pooled_row, pooled_profile = build_hall_pooled_dd_profile(
            hall,
            raw,
            recent_window_days=args.recent_window_days,
            min_cell_n_for_dd=args.min_cell_n_for_dd,
            min_common_dd_levels=args.min_common_dd_levels,
        )
        pooled_rows.append(pooled_row)
        pooled_profiles.append(pooled_profile)

    all_summary = (
        pd.concat(all_summaries, ignore_index=True) if all_summaries else pd.DataFrame(columns=SUMMARY_COLUMNS)
    )
    all_profile = pd.concat(all_profiles, ignore_index=True) if all_profiles else pd.DataFrame(columns=PROFILE_COLUMNS)
    _write_csv(all_summary, output_dir / "all_halls_summary.csv")
    _write_csv(all_profile, output_dir / "all_halls_dd_profile.csv")

    pooled_summary = pd.DataFrame(pooled_rows, columns=POOLED_SUMMARY_COLUMNS)
    pooled_profile = (
        pd.concat(pooled_profiles, ignore_index=True)
        if pooled_profiles
        else pd.DataFrame(columns=POOLED_PROFILE_COLUMNS)
    )
    _write_csv(pooled_summary, output_dir / "all_halls_pooled_summary.csv")
    _write_csv(pooled_profile, output_dir / "all_halls_pooled_dd_profile.csv")
    _print_pooled_report(pooled_summary)

    print(f"\n{'=' * 70}")
    print("verdict別カウント（ホール横断で件数のみ集計。判定はホール内で独立に実施）")
    print('=' * 70)
    if not all_summary.empty:
        print(all_summary["verdict"].value_counts().to_string())

    print(f"\nwritten: {output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
