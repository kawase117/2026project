from __future__ import annotations

import argparse
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import chi2_contingency, kruskal

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if __package__ in {None, ""}:
    sys.path.insert(0, str(PROJECT_ROOT))

from eda.core import HALL_DBS, _epsilon_squared, compute_debut_features, load_hall_df, scan_dimension

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


COINS_PER_GAME = 3
DEFAULT_HALLS = ["蒲田1", "蒲田7", "みとや"]
DEFAULT_OUTPUT_DIR = Path(__file__).resolve().parents[1] / "results" / "machine_name_significance"
DEFAULT_SHINDAI_EXCLUDE_DAYS = 30
DEFAULT_MIN_MACHINE_DAYS = 30
DEFAULT_MIN_ACTIVE_MACHINES = 6

MACHINE_SUMMARY_COLUMNS = [
    "hall",
    "machine_name",
    "n_units",
    "n_machine_days",
    "avg_diff",
    "plus_rate",
    "hit104_rate",
    "avg_payout_rate",
    "top3_rate",
    "expected_top3_rate",
    "top3_lift",
    "bottom3_rate",
    "expected_bottom3_rate",
    "bottom3_lift",
    "tier",
]

SIGNIFICANCE_COLUMNS = [
    "hall",
    "metric",
    "test",
    "statistic",
    "p_value",
    "effect_size",
    "n_groups",
    "n_obs",
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


def _payout_rate(frame: pd.DataFrame) -> pd.Series:
    games = pd.to_numeric(frame["games"], errors="coerce")
    diff = pd.to_numeric(frame["diff"], errors="coerce")
    denom = games * COINS_PER_GAME
    return np.where(denom.gt(0), ((denom + diff) / denom) * 100.0, np.nan)


def _apply_shindai_filter(frame: pd.DataFrame, shindai_exclude_days: int) -> pd.DataFrame:
    if shindai_exclude_days <= 0:
        return frame.copy()

    keep_mask = (
        frame["pre_existing"].fillna(False)
        | frame["days_since_debut"].isna()
        | (frame["days_since_debut"] >= shindai_exclude_days)
    )
    return frame.loc[keep_mask].copy()


def _prepare_frame(raw: pd.DataFrame, *, shindai_exclude_days: int) -> pd.DataFrame:
    derived_cols = {"debut_date", "days_since_debut", "pre_existing", "machine_count"}
    if derived_cols.issubset(set(raw.columns)):
        frame = raw.copy()
    else:
        frame = compute_debut_features(raw)
    frame = _apply_shindai_filter(frame, shindai_exclude_days)

    frame = frame.copy()
    frame["plus"] = (pd.to_numeric(frame["diff"], errors="coerce") > 0).astype(int)
    frame["year_month"] = frame["date"].astype(str).str[:6]
    frame["payout_rate"] = _payout_rate(frame)
    frame["hit104"] = (frame["payout_rate"] >= 104.0).astype(int)

    ordered = frame.sort_values(
        ["date", "diff", "machine_number"],
        ascending=[True, False, True],
        kind="mergesort",
    ).copy()
    ordered["rank"] = ordered.groupby("date").cumcount() + 1
    ordered["n_active"] = ordered.groupby("date")["machine_number"].transform("nunique")
    ordered["top3_flag"] = (ordered["rank"] <= 3).astype(int)
    ordered["bottom3_flag"] = (ordered["rank"] > (ordered["n_active"] - 3)).astype(int)
    return ordered.reset_index(drop=True)


def _expected_selection_rate_percent(n_active: pd.Series) -> pd.Series:
    n_active = pd.to_numeric(n_active, errors="coerce")
    expected = np.where(n_active.gt(0), np.minimum(3.0 / n_active, 1.0) * 100.0, np.nan)
    return pd.Series(expected, index=n_active.index)


def _safe_group_mask(frame: pd.DataFrame, min_machine_days: int) -> pd.Series:
    counts = frame.groupby("machine_name")["machine_number"].transform("size")
    return counts >= min_machine_days


def _kruskal_summary(
    frame: pd.DataFrame,
    *,
    hall: str,
    metric: str,
    value_col: str,
    min_machine_days: int,
) -> dict[str, object]:
    eligible = frame.loc[_safe_group_mask(frame, min_machine_days)].copy()
    if eligible.empty:
        return {
            "hall": hall,
            "metric": metric,
            "test": "kruskal",
            "statistic": np.nan,
            "p_value": np.nan,
            "effect_size": np.nan,
            "n_groups": 0,
            "n_obs": 0,
            "note": "no eligible machine groups",
        }

    groups = [
        pd.to_numeric(group[value_col], errors="coerce").dropna().to_numpy()
        for _, group in eligible.groupby("machine_name")
        if len(group) >= min_machine_days
    ]
    groups = [group for group in groups if len(group) > 0]
    if len(groups) < 2:
        return {
            "hall": hall,
            "metric": metric,
            "test": "kruskal",
            "statistic": np.nan,
            "p_value": np.nan,
            "effect_size": np.nan,
            "n_groups": len(groups),
            "n_obs": int(sum(len(group) for group in groups)),
            "note": "fewer than two eligible groups",
        }

    statistic, p_value = kruskal(*groups)
    n_groups = len(groups)
    n_obs = int(sum(len(group) for group in groups))
    effect_size = _epsilon_squared(float(statistic), n_groups, n_obs)
    return {
        "hall": hall,
        "metric": metric,
        "test": "kruskal",
        "statistic": float(statistic),
        "p_value": float(p_value),
        "effect_size": float(effect_size),
        "n_groups": n_groups,
        "n_obs": n_obs,
        "note": "",
    }


def _cramers_v(chi2: float, n_obs: int, n_rows: int, n_cols: int) -> float:
    if n_obs <= 0 or n_rows <= 1 or n_cols <= 1:
        return float("nan")
    denom = min(n_rows - 1, n_cols - 1)
    if denom <= 0:
        return float("nan")
    return float(np.sqrt(chi2 / (n_obs * denom)))


def _cramers_v_bias_corrected(chi2: float, n_obs: int, n_rows: int, n_cols: int) -> float:
    if n_obs <= 1 or n_rows <= 1 or n_cols <= 1:
        return float("nan")
    phi2 = chi2 / n_obs
    phi2_tilde = max(0.0, phi2 - (n_rows - 1) * (n_cols - 1) / (n_obs - 1))
    r_tilde = n_rows - (n_rows - 1) ** 2 / (n_obs - 1)
    c_tilde = n_cols - (n_cols - 1) ** 2 / (n_obs - 1)
    denom = min(r_tilde - 1, c_tilde - 1)
    if denom <= 0:
        return 0.0
    return float(np.sqrt(phi2_tilde / denom))


def _chi2_summary(
    frame: pd.DataFrame,
    *,
    hall: str,
    metric: str,
    flag_col: str,
    min_machine_days: int,
    min_active_machines: int,
) -> dict[str, object]:
    eligible_days = frame.loc[frame["n_active"] >= min_active_machines].copy()
    if eligible_days.empty:
        return {
            "hall": hall,
            "metric": metric,
            "test": "chi2",
            "statistic": np.nan,
            "p_value": np.nan,
            "effect_size": np.nan,
            "n_groups": 0,
            "n_obs": 0,
            "note": f"no days with n_active >= {min_active_machines}",
        }

    eligible = eligible_days.loc[_safe_group_mask(eligible_days, min_machine_days)].copy()
    if eligible.empty:
        return {
            "hall": hall,
            "metric": metric,
            "test": "chi2",
            "statistic": np.nan,
            "p_value": np.nan,
            "effect_size": np.nan,
            "n_groups": 0,
            "n_obs": 0,
            "note": "no eligible machine groups",
        }

    contingency = pd.crosstab(eligible["machine_name"], eligible[flag_col])
    if contingency.empty or contingency.shape[0] < 2 or contingency.to_numpy().sum() == 0:
        return {
            "hall": hall,
            "metric": metric,
            "test": "chi2",
            "statistic": np.nan,
            "p_value": np.nan,
            "effect_size": np.nan,
            "n_groups": int(contingency.shape[0]),
            "n_obs": int(contingency.to_numpy().sum()),
            "note": "insufficient contingency table",
        }

    contingency = contingency.reindex(columns=[0, 1], fill_value=0)
    if (contingency.sum(axis=0) == 0).any() or (contingency.sum(axis=1) == 0).any():
        return {
            "hall": hall,
            "metric": metric,
            "test": "chi2",
            "statistic": np.nan,
            "p_value": np.nan,
            "effect_size": np.nan,
            "n_groups": int(contingency.shape[0]),
            "n_obs": int(contingency.to_numpy().sum()),
            "note": "insufficient contingency table",
        }
    chi2, p_value, _, expected = chi2_contingency(contingency, correction=False)
    sparse_ratio = float((expected < 5).mean())
    note = ""
    if sparse_ratio > 0.2:
        note = f"warning: {sparse_ratio:.1%} of expected cells are below 5"
        warnings.warn(f"{hall} {metric}: {note}", RuntimeWarning)

    n_obs = int(contingency.to_numpy().sum())
    effect_size = _cramers_v(float(chi2), n_obs, contingency.shape[0], contingency.shape[1])
    return {
        "hall": hall,
        "metric": metric,
        "test": "chi2",
        "statistic": float(chi2),
        "p_value": float(p_value),
        "effect_size": float(effect_size),
        "n_groups": int(contingency.shape[0]),
        "n_obs": n_obs,
        "note": note,
    }


def build_hall_outputs(
    hall: str,
    raw: pd.DataFrame,
    *,
    shindai_exclude_days: int = DEFAULT_SHINDAI_EXCLUDE_DAYS,
    min_machine_days: int = DEFAULT_MIN_MACHINE_DAYS,
    min_active_machines: int = DEFAULT_MIN_ACTIVE_MACHINES,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    frame = _prepare_frame(raw, shindai_exclude_days=shindai_exclude_days)
    frame = frame.loc[frame["n_active"] >= min_active_machines].copy()
    if frame.empty:
        empty_summary = pd.DataFrame(columns=MACHINE_SUMMARY_COLUMNS)
        empty_significance = pd.DataFrame(columns=SIGNIFICANCE_COLUMNS)
        return empty_summary, empty_significance

    scan = scan_dimension(hall, ["machine_name"], min_n=min_machine_days, df=frame)
    if scan.empty:
        empty_summary = pd.DataFrame(columns=MACHINE_SUMMARY_COLUMNS)
        empty_significance = pd.DataFrame(columns=SIGNIFICANCE_COLUMNS)
        return empty_summary, empty_significance

    allowed_names = set(scan["machine_name"].astype(str))
    working = frame.loc[frame["machine_name"].astype(str).isin(allowed_names)].copy()

    # Build per-machine aggregates on the filtered frame.
    grouped = working.groupby("machine_name", sort=True)
    machine_days = grouped.size().rename("n_machine_days")
    n_units = grouped["machine_number"].nunique().rename("n_units")
    hit104_rate = grouped["hit104"].mean().mul(100.0).rename("hit104_rate")
    avg_payout_rate = grouped["payout_rate"].mean().rename("avg_payout_rate")
    top3_rate = grouped["top3_flag"].mean().mul(100.0).rename("top3_rate")
    expected_top3_rate = (
        grouped["n_active"].apply(lambda s: _expected_selection_rate_percent(s).mean()).rename("expected_top3_rate")
    )
    bottom3_rate = grouped["bottom3_flag"].mean().mul(100.0).rename("bottom3_rate")
    expected_bottom3_rate = (
        grouped["n_active"].apply(lambda s: _expected_selection_rate_percent(s).mean()).rename("expected_bottom3_rate")
    )

    # Selection lifts are computed per machine from the observed rate / expected rate.
    top3_lift = (top3_rate / expected_top3_rate).rename("top3_lift")
    bottom3_lift = (bottom3_rate / expected_bottom3_rate).rename("bottom3_lift")

    summary = (
        scan.loc[:, ["machine_name", "avg_diff", "plus_rate", "tier"]]
        .merge(n_units.reset_index(), on="machine_name", how="left")
        .merge(machine_days.reset_index(), on="machine_name", how="left")
        .merge(hit104_rate.reset_index(), on="machine_name", how="left")
        .merge(avg_payout_rate.reset_index(), on="machine_name", how="left")
        .merge(top3_rate.reset_index(), on="machine_name", how="left")
        .merge(expected_top3_rate.reset_index(), on="machine_name", how="left")
        .merge(top3_lift.reset_index(), on="machine_name", how="left")
        .merge(bottom3_rate.reset_index(), on="machine_name", how="left")
        .merge(expected_bottom3_rate.reset_index(), on="machine_name", how="left")
        .merge(bottom3_lift.reset_index(), on="machine_name", how="left")
    )

    summary.insert(0, "hall", hall)
    summary = summary.loc[:, MACHINE_SUMMARY_COLUMNS]
    summary = summary.sort_values(["avg_diff", "machine_name"], ascending=[False, True], kind="mergesort").reset_index(
        drop=True
    )

    significance_rows = [
        _kruskal_summary(frame, hall=hall, metric="hit104_rate", value_col="hit104", min_machine_days=min_machine_days),
        _kruskal_summary(
            frame, hall=hall, metric="avg_payout_rate", value_col="payout_rate", min_machine_days=min_machine_days
        ),
        _chi2_summary(
            frame,
            hall=hall,
            metric="top3_selection",
            flag_col="top3_flag",
            min_machine_days=min_machine_days,
            min_active_machines=min_active_machines,
        ),
        _chi2_summary(
            frame,
            hall=hall,
            metric="bottom3_selection",
            flag_col="bottom3_flag",
            min_machine_days=min_machine_days,
            min_active_machines=min_active_machines,
        ),
    ]
    significance = pd.DataFrame(significance_rows, columns=SIGNIFICANCE_COLUMNS)
    return summary, significance


def _write_csv(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False, encoding="utf-8-sig")


def _print_hall_report(hall: str, summary: pd.DataFrame, significance: pd.DataFrame) -> None:
    print(f"\n=== {hall} ===")
    for _, row in significance.iterrows():
        statistic = row["statistic"]
        p_value = row["p_value"]
        effect_size = row["effect_size"]
        note = row["note"]
        stat_text = "NaN" if pd.isna(statistic) else f"{statistic:.4f}"
        p_text = "NaN" if pd.isna(p_value) else f"{p_value:.4g}"
        eff_text = "NaN" if pd.isna(effect_size) else f"{effect_size:.4f}"
        line = f"{row['metric']}: {row['test']} stat={stat_text}, p={p_text}, effect={eff_text}, n_groups={int(row['n_groups'])}, n_obs={int(row['n_obs'])}"
        if isinstance(note, str) and note:
            line += f", note={note}"
        print(line)

    def _top_frame(metric: str, ascending: bool) -> pd.DataFrame:
        cols = ["machine_name", metric, "n_machine_days", "tier"]
        return (
            summary.loc[:, cols]
            .sort_values([metric, "machine_name"], ascending=[ascending, True], kind="mergesort")
            .head(5)
        )

    print("top3_lift 上位5:")
    print(_top_frame("top3_lift", False).to_string(index=False))
    print("bottom3_lift 上位5:")
    print(_top_frame("bottom3_lift", False).to_string(index=False))
    print("hit104_rate 上位5:")
    print(_top_frame("hit104_rate", False).to_string(index=False))
    print("hit104_rate 下位5:")
    print(_top_frame("hit104_rate", True).to_string(index=False))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="機種別×ホールの104%超え率・Top3/Bottom3有意差スキャン")
    parser.add_argument(
        "--halls", type=_parse_halls, default=DEFAULT_HALLS, help="カンマ区切りのホール名。default: 蒲田1,蒲田7,みとや"
    )
    parser.add_argument("--all-halls", action="store_true", help="HALL_DBS の全ホールを対象にする")
    parser.add_argument(
        "--shindai-exclude-days", type=int, default=DEFAULT_SHINDAI_EXCLUDE_DAYS, help="新台除外日数。0で除外なし"
    )
    parser.add_argument("--min-machine-days", type=int, default=DEFAULT_MIN_MACHINE_DAYS, help="機種の最小サンプル日数")
    parser.add_argument(
        "--min-active-machines", type=int, default=DEFAULT_MIN_ACTIVE_MACHINES, help="chi2用の最低稼働台数"
    )
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR, help="出力先ディレクトリ")
    args = parser.parse_args(argv)

    halls = list(HALL_DBS.keys()) if args.all_halls else args.halls
    output_dir = _ensure_output_dir(args.output_dir)

    all_significance: list[pd.DataFrame] = []
    had_any_output = False

    for hall in halls:
        if hall not in HALL_DBS:
            raise ValueError(f"unknown hall: {hall}")
        raw = load_hall_df(hall)
        summary, significance = build_hall_outputs(
            hall,
            raw,
            shindai_exclude_days=args.shindai_exclude_days,
            min_machine_days=args.min_machine_days,
            min_active_machines=args.min_active_machines,
        )
        if summary.empty and significance.empty:
            print(f"{hall}: no rows")
            continue

        had_any_output = True
        _write_csv(summary, output_dir / f"{hall}_machine_summary.csv")
        all_significance.append(significance)
        _print_hall_report(hall, summary, significance)

    if not had_any_output:
        return 1

    significance_df = (
        pd.concat(all_significance, ignore_index=True)
        if all_significance
        else pd.DataFrame(columns=SIGNIFICANCE_COLUMNS)
    )
    _write_csv(significance_df, output_dir / "significance_summary.csv")
    print(f"\nwritten: {output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
