from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd
from scipy.stats import chi2_contingency

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if __package__ in {None, ""}:
    sys.path.insert(0, str(PROJECT_ROOT))

from eda.core import HALL_DBS, load_hall_df
from eda.machine_name_significance_scan import (
    DEFAULT_MIN_ACTIVE_MACHINES as DEFAULT_MIN_ACTIVE_MACHINES_FROM_NAMESCAN,
    _cramers_v,
    _expected_selection_rate_percent,
    _prepare_frame,
)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

DEFAULT_HALLS = ["蒲田1", "蒲田7", "みとや"]
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "eda" / "results" / "machine_volatility_event_gap"
DEFAULT_CURRENTLY_INSTALLED_GRACE_DAYS = 30
DEFAULT_MIN_MACHINE_DAYS_VOLATILITY = 100
DEFAULT_MIN_GROUP_DAYS = 15
DEFAULT_VOLATILITY_TOP_PCT = 0.25
DEFAULT_MIN_ACTIVE_MACHINES = DEFAULT_MIN_ACTIVE_MACHINES_FROM_NAMESCAN
MACHINE_NAME_SIG_DIR = PROJECT_ROOT / "eda" / "results" / "machine_name_significance"

RANKING_COLUMNS = [
    "hall",
    "machine_name",
    "n_machine_days",
    "days_since_last_seen",
    "volatility_score",
    "hit104_rate",
    "bottom3_lift",
    "volatility_rank",
]

EVENT_GAP_COLUMNS = [
    "hall",
    "machine_name",
    "event_type",
    "n_event_days",
    "n_normal_days",
    "hit104_rate_event",
    "hit104_rate_normal",
    "hit104_gap",
    "hit104_chi2_p",
    "hit104_cramers_v",
    "bottom3_rate_event",
    "bottom3_rate_normal",
    "bottom3_gap",
    "bottom3_chi2_p",
    "bottom3_cramers_v",
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


def _parse_dates(frame: pd.DataFrame) -> pd.Series:
    return pd.to_datetime(frame["date"].astype(str), format="%Y%m%d", errors="coerce")


def _apply_currently_installed_filter(
    frame: pd.DataFrame,
    *,
    grace_days: int,
) -> pd.DataFrame:
    working = frame.copy()
    working["date_ts"] = _parse_dates(working)
    hall_max_date = working["date_ts"].max()
    if pd.isna(hall_max_date):
        return working.iloc[0:0].copy()

    last_seen = working.groupby("machine_name", dropna=False)["date_ts"].max().rename("machine_last_date")
    meta = last_seen.reset_index()
    meta["days_since_last_seen"] = (hall_max_date - meta["machine_last_date"]).dt.days
    working = working.merge(meta, on="machine_name", how="left")
    keep_mask = working["days_since_last_seen"].le(grace_days)
    return working.loc[keep_mask].copy()


def _current_selection_count(n_machines: int, volatility_top_pct: float) -> int:
    top_n = math.floor(n_machines * volatility_top_pct)
    return max(1, min(20, top_n))


def _safe_rate(values: pd.Series) -> float:
    numeric = pd.to_numeric(values, errors="coerce").dropna()
    if numeric.empty:
        return float("nan")
    return float(numeric.mean() * 100.0)


def _expected_bottom3_rate(frame: pd.DataFrame) -> float:
    if frame.empty:
        return float("nan")
    return float(_expected_selection_rate_percent(frame["n_active"]).mean())


def _machine_summary(frame: pd.DataFrame) -> pd.DataFrame:
    grouped = frame.groupby("machine_name", sort=True)
    summary = pd.DataFrame(
        {
            "n_machine_days": grouped.size(),
            "hit104_rate": grouped["hit104"].mean().mul(100.0),
            "bottom3_rate": grouped["bottom3_flag"].mean().mul(100.0),
            "payout_mean": grouped["payout_rate"].mean(),
            "payout_std": grouped["payout_rate"].std(),
            "expected_bottom3_rate": grouped["n_active"].apply(lambda s: _expected_selection_rate_percent(s).mean()),
            "days_since_last_seen": grouped["days_since_last_seen"].first(),
        }
    ).reset_index()
    summary["volatility_score"] = summary["payout_std"] / summary["payout_mean"]
    summary["bottom3_lift"] = summary["bottom3_rate"] / summary["expected_bottom3_rate"]
    summary["hall"] = frame["hall"].iloc[0] if "hall" in frame.columns and not frame.empty else ""
    summary["n_machine_days"] = summary["n_machine_days"].astype(int)
    summary["days_since_last_seen"] = summary["days_since_last_seen"].astype(int)
    summary = summary.loc[
        :,
        [
            "hall",
            "machine_name",
            "n_machine_days",
            "days_since_last_seen",
            "volatility_score",
            "hit104_rate",
            "bottom3_lift",
        ],
    ]
    summary = summary.sort_values(
        ["volatility_score", "machine_name"],
        ascending=[False, True],
        kind="mergesort",
    ).reset_index(drop=True)
    summary["volatility_rank"] = np.arange(1, len(summary) + 1, dtype=int)
    return summary.loc[:, RANKING_COLUMNS]


def _chi2_group_summary(
    frame: pd.DataFrame, event_col: str, flag_col: str, *, min_group_days: int
) -> dict[str, object]:
    event_counts = frame[event_col].fillna(0).astype(int)
    n_event_days = int(event_counts.sum())
    n_normal_days = int((1 - event_counts).sum())
    rate_event = float(frame.loc[event_counts.eq(1), flag_col].mean() * 100.0) if n_event_days else float("nan")
    rate_normal = float(frame.loc[event_counts.eq(0), flag_col].mean() * 100.0) if n_normal_days else float("nan")
    gap = rate_event - rate_normal if flag_col == "hit104" else rate_normal - rate_event

    if n_event_days < min_group_days or n_normal_days < min_group_days:
        return {
            "n_event_days": n_event_days,
            "n_normal_days": n_normal_days,
            "rate_event": rate_event,
            "rate_normal": rate_normal,
            "gap": gap,
            "p_value": float("nan"),
            "cramers_v": float("nan"),
            "note": f"skip: n_event_days={n_event_days}, n_normal_days={n_normal_days} < min_group_days",
        }

    crosstab = pd.crosstab(event_counts, frame[flag_col].fillna(0).astype(int)).reindex(
        index=[0, 1], columns=[0, 1], fill_value=0
    )
    if crosstab.to_numpy().sum() == 0 or (crosstab.sum(axis=0) == 0).any() or (crosstab.sum(axis=1) == 0).any():
        return {
            "n_event_days": n_event_days,
            "n_normal_days": n_normal_days,
            "rate_event": rate_event,
            "rate_normal": rate_normal,
            "gap": gap,
            "p_value": float("nan"),
            "cramers_v": float("nan"),
            "note": "insufficient contingency table",
        }

    chi2, p_value, _, expected = chi2_contingency(crosstab, correction=False)
    sparse_ratio = float((expected < 5).mean())
    note = ""
    if sparse_ratio > 0.2:
        note = f"warning: {sparse_ratio:.1%} of expected cells are below 5"
    return {
        "n_event_days": n_event_days,
        "n_normal_days": n_normal_days,
        "rate_event": rate_event,
        "rate_normal": rate_normal,
        "gap": gap,
        "p_value": float(p_value),
        "cramers_v": _cramers_v(float(chi2), int(crosstab.to_numpy().sum()), crosstab.shape[0], crosstab.shape[1]),
        "note": note,
    }


def _build_event_gap_table(
    hall: str,
    frame: pd.DataFrame,
    *,
    selected_machine_names: Iterable[str],
    min_group_days: int,
) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    selected = frame.loc[frame["machine_name"].astype(str).isin({str(name) for name in selected_machine_names})].copy()
    if selected.empty:
        return pd.DataFrame(columns=EVENT_GAP_COLUMNS)

    event_specs = [
        ("is_any_event", "is_any_event"),
        ("is_x_day", "is_x_day"),
        ("is_weekend", "is_weekend"),
    ]
    for machine_name, machine_frame in selected.groupby("machine_name", sort=True):
        machine_frame = machine_frame.copy()
        for event_type, event_col in event_specs:
            hit_summary = _chi2_group_summary(machine_frame, event_col, "hit104", min_group_days=min_group_days)
            bottom_summary = _chi2_group_summary(
                machine_frame, event_col, "bottom3_flag", min_group_days=min_group_days
            )
            note = "; ".join(part for part in [hit_summary["note"], bottom_summary["note"]] if part)
            rows.append(
                {
                    "hall": hall,
                    "machine_name": machine_name,
                    "event_type": event_type,
                    "n_event_days": int(hit_summary["n_event_days"]),
                    "n_normal_days": int(hit_summary["n_normal_days"]),
                    "hit104_rate_event": hit_summary["rate_event"],
                    "hit104_rate_normal": hit_summary["rate_normal"],
                    "hit104_gap": hit_summary["gap"],
                    "hit104_chi2_p": hit_summary["p_value"],
                    "hit104_cramers_v": hit_summary["cramers_v"],
                    "bottom3_rate_event": bottom_summary["rate_event"],
                    "bottom3_rate_normal": bottom_summary["rate_normal"],
                    "bottom3_gap": bottom_summary["gap"],
                    "bottom3_chi2_p": bottom_summary["p_value"],
                    "bottom3_cramers_v": bottom_summary["cramers_v"],
                    "note": note,
                }
            )

    event_gap = pd.DataFrame(rows, columns=EVENT_GAP_COLUMNS)
    event_gap = event_gap.sort_values(
        ["machine_name", "event_type"],
        ascending=[True, True],
        kind="mergesort",
    ).reset_index(drop=True)
    return event_gap


def _resolve_tokyo_ghoul_name(hall: str) -> str | None:
    candidates = [MACHINE_NAME_SIG_DIR / f"{hall}_machine_summary.csv"]
    candidates.extend(sorted(MACHINE_NAME_SIG_DIR.glob("*_machine_summary.csv")))
    seen: set[Path] = set()
    for path in candidates:
        if path in seen:
            continue
        seen.add(path)
        if not path.exists():
            continue
        try:
            df = pd.read_csv(path)
        except Exception:
            continue
        if "machine_name" not in df.columns:
            continue
        matches = df.loc[df["machine_name"].astype(str).str.contains("東京喰種", na=False), "machine_name"].astype(str)
        if not matches.empty:
            return matches.iloc[0]
    return None


def _build_summary_row(hall: str, ranking: pd.DataFrame, event_gap: pd.DataFrame) -> dict[str, object]:
    any_event = event_gap.loc[event_gap["event_type"].astype(str).eq("is_any_event")].copy()
    tested_any = any_event.loc[any_event["hit104_cramers_v"].notna()].copy()
    tested_bottom3 = any_event.loc[any_event["bottom3_cramers_v"].notna()].copy()

    tokyo_name = _resolve_tokyo_ghoul_name(hall)
    tokyo_row = ranking.loc[ranking["machine_name"].astype(str).eq(tokyo_name)].head(1)
    tokyo_any = any_event.loc[any_event["machine_name"].astype(str).eq(tokyo_name)].head(1)

    return {
        "hall": hall,
        "n_volatile_machines_tested": int(tested_any["machine_name"].nunique()),
        "pct_with_cramers_v_over_0.1(hit104, is_any_event)": float(
            (tested_any["hit104_cramers_v"].abs() >= 0.1).mean() * 100.0
        )
        if not tested_any.empty
        else float("nan"),
        "pct_with_cramers_v_over_0.1(bottom3, is_any_event)": float(
            (tested_bottom3["bottom3_cramers_v"].abs() >= 0.1).mean() * 100.0
        )
        if not tested_bottom3.empty
        else float("nan"),
        "tokyo_ghoul_machine_name": tokyo_name,
        "tokyo_ghoul_volatility_rank": int(tokyo_row["volatility_rank"].iloc[0])
        if not tokyo_row.empty
        else float("nan"),
        "tokyo_ghoul_hit104_gap_any_event": float(tokyo_any["hit104_gap"].iloc[0])
        if not tokyo_any.empty
        else float("nan"),
        "tokyo_ghoul_bottom3_gap_any_event": float(tokyo_any["bottom3_gap"].iloc[0])
        if not tokyo_any.empty
        else float("nan"),
    }


def build_hall_outputs(
    hall: str,
    raw: pd.DataFrame,
    *,
    currently_installed_grace_days: int = DEFAULT_CURRENTLY_INSTALLED_GRACE_DAYS,
    min_machine_days_volatility: int = DEFAULT_MIN_MACHINE_DAYS_VOLATILITY,
    min_group_days: int = DEFAULT_MIN_GROUP_DAYS,
    volatility_top_pct: float = DEFAULT_VOLATILITY_TOP_PCT,
    min_active_machines: int = DEFAULT_MIN_ACTIVE_MACHINES,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, object]]:
    frame = _prepare_frame(raw, shindai_exclude_days=0).copy()
    if "hall" not in frame.columns:
        frame["hall"] = hall
    frame = _apply_currently_installed_filter(frame, grace_days=currently_installed_grace_days)
    if frame.empty:
        empty_ranking = pd.DataFrame(columns=RANKING_COLUMNS)
        empty_event = pd.DataFrame(columns=EVENT_GAP_COLUMNS)
        return empty_ranking, empty_event, _build_summary_row(hall, empty_ranking, empty_event)

    frame = frame.loc[frame["n_active"] >= min_active_machines].copy()
    if frame.empty:
        empty_ranking = pd.DataFrame(columns=RANKING_COLUMNS)
        empty_event = pd.DataFrame(columns=EVENT_GAP_COLUMNS)
        return empty_ranking, empty_event, _build_summary_row(hall, empty_ranking, empty_event)

    summary = _machine_summary(frame)
    summary = summary.loc[summary["n_machine_days"] >= min_machine_days_volatility].copy()
    if summary.empty:
        empty_ranking = pd.DataFrame(columns=RANKING_COLUMNS)
        empty_event = pd.DataFrame(columns=EVENT_GAP_COLUMNS)
        return empty_ranking, empty_event, _build_summary_row(hall, empty_ranking, empty_event)
    ranking = summary.loc[:, RANKING_COLUMNS].copy()

    top_n = _current_selection_count(len(ranking), volatility_top_pct)
    selected_machine_names = set(ranking.head(top_n)["machine_name"].astype(str).tolist())
    tokyo_name = _resolve_tokyo_ghoul_name(hall)
    if tokyo_name:
        selected_machine_names.add(tokyo_name)
    event_gap = _build_event_gap_table(
        hall,
        frame,
        selected_machine_names=selected_machine_names,
        min_group_days=min_group_days,
    )
    summary_row = _build_summary_row(hall, ranking, event_gap)
    return ranking, event_gap, summary_row


def _print_hall_report(hall: str, ranking: pd.DataFrame, event_gap: pd.DataFrame) -> None:
    print(f"[{hall}] volatility top 10")
    if ranking.empty:
        print("  no eligible machines")
        return

    print(ranking.head(10).loc[:, ["machine_name", "volatility_score", "days_since_last_seen"]].to_string(index=False))
    any_event = event_gap.loc[event_gap["event_type"].astype(str).eq("is_any_event")].copy()
    any_event["gap_strength"] = any_event[["hit104_cramers_v", "bottom3_cramers_v"]].abs().max(axis=1)
    top_gap = (
        any_event.loc[any_event["gap_strength"].notna()]
        .sort_values(
            ["gap_strength", "machine_name"],
            ascending=[False, True],
            kind="mergesort",
        )
        .head(5)
    )
    print(f"[{hall}] is_any_event gap top 5")
    if top_gap.empty:
        print("  no eligible machines")
    else:
        print(
            top_gap.loc[
                :, ["machine_name", "hit104_gap", "bottom3_gap", "hit104_cramers_v", "bottom3_cramers_v"]
            ].to_string(index=False)
        )


def _write_hall_outputs(output_dir: Path, hall: str, ranking: pd.DataFrame, event_gap: pd.DataFrame) -> None:
    ranking.to_csv(output_dir / f"{hall}_volatility_ranking.csv", index=False)
    event_gap.to_csv(output_dir / f"{hall}_event_gap.csv", index=False)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Scan volatility vs event-axis gaps across machines.")
    parser.add_argument("--halls", type=_parse_halls, default=DEFAULT_HALLS)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument(
        "--currently-installed-grace-days",
        type=int,
        default=DEFAULT_CURRENTLY_INSTALLED_GRACE_DAYS,
    )
    parser.add_argument(
        "--min-machine-days-volatility",
        type=int,
        default=DEFAULT_MIN_MACHINE_DAYS_VOLATILITY,
    )
    parser.add_argument("--min-group-days", type=int, default=DEFAULT_MIN_GROUP_DAYS)
    parser.add_argument("--volatility-top-pct", type=float, default=DEFAULT_VOLATILITY_TOP_PCT)
    args = parser.parse_args(argv)

    output_dir = _ensure_output_dir(args.output_dir)
    summary_rows: list[dict[str, object]] = []

    for hall in args.halls:
        if hall not in HALL_DBS:
            raise ValueError(f"unknown hall: {hall}")
        raw = load_hall_df(hall)
        ranking, event_gap, summary_row = build_hall_outputs(
            hall,
            raw,
            currently_installed_grace_days=args.currently_installed_grace_days,
            min_machine_days_volatility=args.min_machine_days_volatility,
            min_group_days=args.min_group_days,
            volatility_top_pct=args.volatility_top_pct,
            min_active_machines=DEFAULT_MIN_ACTIVE_MACHINES,
        )
        _write_hall_outputs(output_dir, hall, ranking, event_gap)
        _print_hall_report(hall, ranking, event_gap)
        summary_rows.append(summary_row)

    summary = pd.DataFrame(summary_rows)
    summary.to_csv(output_dir / "summary_report.csv", index=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
