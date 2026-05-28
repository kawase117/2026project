from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy.stats import pearsonr

from ml.last_digit import zorome_strategy_simulation as zsim
from ml.last_digit.tail_ltr_split_rule_nextday_gpu import _prepare_split_dataset


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Post-analysis for zorome strategy effectiveness.")
    p.add_argument("--db-path", required=True, help="DB path.")
    p.add_argument(
        "--input-dir",
        default="db/experiments/zorome_strategy_plan_run_20260527",
        help="Directory containing phase_summary and phase csv outputs.",
    )
    p.add_argument(
        "--output-dir",
        default="db/experiments/zorome_strategy_plan_run_20260527",
        help="Directory to write analysis outputs.",
    )
    p.add_argument("--train-windows", default="60,90,120,180,full", help="Windows for correction diagnosis.")
    p.add_argument("--eval-window-days", type=int, default=61, help="Eval window days.")
    return p


def _parse_windows(raw: str) -> list[int | None]:
    out: list[int | None] = []
    for token in [t.strip() for t in str(raw).split(",") if t.strip()]:
        if token.lower() == "full":
            out.append(None)
        else:
            out.append(int(token))
    return out


def _window_name(w: int | None) -> str:
    return "full" if w is None else str(int(w))


def _slice_train(df_train: pd.DataFrame, sim_start: pd.Timestamp, w: int | None) -> pd.DataFrame:
    if w is None:
        return df_train.copy()
    start = sim_start - pd.Timedelta(days=int(w))
    return df_train[df_train["date"] >= start].copy()


def _lookup_direction(
    corr: pd.DataFrame, *, weekday: str, expert: str, digit: int
) -> tuple[str, float | None]:
    row = corr[
        (corr["weekday"] == weekday)
        & (corr["group_key"].astype(str) == str(expert))
        & (pd.to_numeric(corr["last_digit"], errors="coerce") == int(digit))
    ]
    if row.empty:
        return "no_data", None
    value = pd.to_numeric(row["correction"], errors="coerce").iloc[0]
    if not np.isfinite(value):
        return "no_data", None
    v = float(value)
    if v > 0:
        return "prefer_zorome", v
    if v < 0:
        return "avoid_zorome", v
    return "neutral", v


def _json_dump(path: Path, payload: dict[str, Any]) -> None:
    def convert(v: Any) -> Any:
        if isinstance(v, dict):
            return {str(k): convert(val) for k, val in v.items()}
        if isinstance(v, list):
            return [convert(x) for x in v]
        if isinstance(v, (np.integer, np.floating)):
            v = v.item()
        if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
            return None
        return v

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(convert(payload), ensure_ascii=False, indent=2), encoding="utf-8")


def _build_phase1_win_details(input_dir: Path, output_dir: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    df = pd.read_csv(input_dir / "phase1_daily_best_window.csv", encoding="utf-8-sig")
    for c in ("strategy_A_mean", "strategy_B_mean", "zorome_correction"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df["B_minus_A"] = df["strategy_B_mean"] - df["strategy_A_mean"]
    win = df[df["B_minus_A"] > 0].copy()

    out = win[
        ["date", "B_minus_A", "correction_direction", "zorome_correction", "expert_used", "target_digit"]
    ].rename(columns={"zorome_correction": "correction"})
    out = out.sort_values("date").reset_index(drop=True)
    out.to_csv(output_dir / "phase1_win_days_detail.csv", index=False, encoding="utf-8-sig")
    return df, out


def _build_win_lose_pattern(df_all: pd.DataFrame, output_dir: Path) -> None:
    df = df_all.copy()
    df["B_minus_A"] = pd.to_numeric(df["B_minus_A"], errors="coerce")
    df["is_win"] = (df["B_minus_A"] > 0).astype(int)
    df["weekday"] = pd.to_datetime(df["date"]).dt.day_name()

    def table_for(col: str) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for key, g in df.groupby(col, sort=True):
            win = int(g["is_win"].sum())
            lose = int((g["is_win"] == 0).sum())
            rows.append(
                {
                    col: str(key),
                    "win_days": win,
                    "lose_or_tie_days": lose,
                    "win_rate": float(win / len(g)) if len(g) > 0 else None,
                }
            )
        return rows

    payload = {
        "overall": {
            "n_days": int(len(df)),
            "n_win_days": int(df["is_win"].sum()),
            "n_lose_or_tie_days": int((df["is_win"] == 0).sum()),
            "mean_b_minus_a": float(df["B_minus_A"].mean()),
        },
        "weekday_distribution": table_for("weekday"),
        "expert_distribution": table_for("expert_used"),
        "digit_distribution": table_for("target_digit"),
    }
    _json_dump(output_dir / "win_lose_pattern_analysis.json", payload)


def _build_correction_diagnosis(
    *,
    db_path: Path,
    output_dir: Path,
    windows: list[int | None],
    eval_window_days: int,
) -> None:
    df_m = zsim.load_machine_level_data(db_path)
    sim_start, sim_end = zsim.define_window(df_m, window_days=int(eval_window_days))
    df_train = df_m[df_m["date"] < sim_start].copy()
    df_test = df_m[(df_m["date"] >= sim_start) & (df_m["date"] <= sim_end)].copy()

    pred_args = zsim.build_parser().parse_args(["--db-path", str(db_path)])
    split_data, _src_latest, _target = _prepare_split_dataset(
        db_path=str(db_path),
        db_glob=str(pred_args.db_glob),
        a_weight=float(pred_args.a_weight),
        non_a_weight=float(pred_args.non_a_weight),
        enable_digit_lag_bundle=bool(pred_args.enable_digit_lag_bundle),
    )
    test_dates = sorted(pd.to_datetime(df_test["date"]).drop_duplicates().tolist())
    preds = zsim.generate_test_predictions(
        data=split_data,
        test_dates=test_dates,
        args=pred_args,
        model_params=zsim._parse_model_params(pred_args),
    )

    rows: list[dict[str, Any]] = []
    for w in windows:
        train_slice = _slice_train(df_train, sim_start, w)
        corr = zsim.compute_zorome_correction_table(
            train_slice,
            min_zorome_n=int(pred_args.min_zorome_train_n),
            min_nonzorome_n=int(pred_args.min_nonzorome_train_n),
        )
        corr_vals = pd.to_numeric(corr["correction"], errors="coerce")
        filled = int(corr_vals.notna().sum())
        n_total = int(len(corr))

        direction_counter = {"prefer_zorome": 0, "avoid_zorome": 0, "neutral": 0, "no_data": 0}
        for dt in test_dates:
            day_p = preds[preds["date"] == dt].copy()
            pick = zsim.select_highest_confidence_expert(day_p)
            if pick is None:
                direction_counter["no_data"] += 1
                continue
            expert, digit, _conf = pick
            direction, _value = _lookup_direction(
                corr,
                weekday=pd.Timestamp(dt).day_name(),
                expert=str(expert),
                digit=int(digit),
            )
            direction_counter[direction] += 1

        rows.append(
            {
                "train_window": _window_name(w),
                "n_cells_total": n_total,
                "n_cells_filled": filled,
                "fill_rate": float(filled / n_total) if n_total > 0 else np.nan,
                "mean_abs_correction": float(np.nanmean(np.abs(corr_vals))) if n_total > 0 else np.nan,
                "std_correction": float(np.nanstd(corr_vals, ddof=0)) if n_total > 0 else np.nan,
                "min_correction": float(np.nanmin(corr_vals)) if corr_vals.notna().any() else np.nan,
                "max_correction": float(np.nanmax(corr_vals)) if corr_vals.notna().any() else np.nan,
                "prefer_count": int(direction_counter["prefer_zorome"]),
                "avoid_count": int(direction_counter["avoid_zorome"]),
                "neutral_count": int(direction_counter["neutral"]),
                "no_data_count": int(direction_counter["no_data"]),
                "n_eval_days": int(len(test_dates)),
            }
        )

    out = pd.DataFrame(rows).sort_values(
        by="train_window",
        key=lambda s: s.map(lambda x: 999999 if str(x) == "full" else int(x)),
    )
    out.to_csv(output_dir / "correction_diagnosis_by_window.csv", index=False, encoding="utf-8-sig")


def _build_phase2_detailed(input_dir: Path, output_dir: Path) -> pd.DataFrame:
    df = pd.read_csv(input_dir / "phase2_participation_daily.csv", encoding="utf-8-sig")
    total_days = int(len(df))
    result_rows: list[dict[str, Any]] = []
    for s in ("D", "E", "F"):
        p_col = f"participated_{s}"
        d_col = f"diff_{s}"
        p = pd.to_numeric(df[p_col], errors="coerce").fillna(0).astype(int)
        x = pd.to_numeric(df[d_col], errors="coerce").fillna(0.0)
        part = x[p == 1]
        n_part = int((p == 1).sum())

        result_rows.append(
            {
                "strategy": s,
                "n_days": total_days,
                "n_participated": n_part,
                "coverage": float(n_part / total_days) if total_days > 0 else np.nan,
                "mean_diff_per_calendar_day": float(x.mean()) if total_days > 0 else np.nan,
                "effective_win_rate": float(((x > 0).sum()) / total_days) if total_days > 0 else np.nan,
                "mean_diff_per_bet": float(part.mean()) if n_part > 0 else np.nan,
                "mean_diff_per_bet_from_calendar": float(x.mean() * total_days / n_part) if n_part > 0 else np.nan,
                "win_rate_per_bet": float((part > 0).mean()) if n_part > 0 else np.nan,
                "median_diff_per_bet": float(part.median()) if n_part > 0 else np.nan,
                "max_loss_day": float(part.min()) if n_part > 0 else np.nan,
                "max_profit_day": float(part.max()) if n_part > 0 else np.nan,
            }
        )
    out = pd.DataFrame(result_rows)
    out.to_csv(output_dir / "phase2_detailed_comparison.csv", index=False, encoding="utf-8-sig")
    return out


def _build_lag4_investigation(input_dir: Path, output_dir: Path) -> dict[str, Any]:
    ts = pd.read_csv(input_dir / "phase3_correction_timeseries.csv", encoding="utf-8-sig")
    ts["date"] = pd.to_datetime(ts["date"], errors="coerce")
    ts = ts.sort_values("date").reset_index(drop=True)
    ts["correction"] = pd.to_numeric(ts["correction"], errors="coerce")
    clean = ts.dropna(subset=["correction"]).copy().reset_index(drop=True)
    clean["cycle_day_4"] = (clean.index % 4) + 1

    corr_series = clean["correction"].to_numpy(dtype=float)
    if len(corr_series) > 4:
        r, p = pearsonr(corr_series[:-4], corr_series[4:])
    else:
        r, p = (np.nan, np.nan)

    by_cycle = (
        clean.groupby("cycle_day_4", sort=True)["correction"]
        .agg(["count", "mean", "std", "median"])
        .reset_index()
        .rename(
            columns={
                "count": "n_rows",
                "mean": "mean_correction",
                "std": "std_correction",
                "median": "median_correction",
            }
        )
    )
    by_cycle["metric"] = "cycle_day_summary"
    by_cycle["lag4_corr"] = np.nan
    by_cycle["lag4_pvalue"] = np.nan

    lag_row = pd.DataFrame(
        [
            {
                "cycle_day_4": "lag4_test",
                "n_rows": int(len(corr_series)),
                "mean_correction": np.nan,
                "std_correction": np.nan,
                "median_correction": np.nan,
                "metric": "lag4_pearson",
                "lag4_corr": float(r) if np.isfinite(r) else np.nan,
                "lag4_pvalue": float(p) if np.isfinite(p) else np.nan,
            }
        ]
    )
    out = pd.concat([by_cycle, lag_row], ignore_index=True)
    out.to_csv(output_dir / "periodicity_lag4_investigation.csv", index=False, encoding="utf-8-sig")

    return {
        "lag4_corr": float(r) if np.isfinite(r) else None,
        "lag4_pvalue": float(p) if np.isfinite(p) else None,
        "cycle_means": {f"cycle_day_{int(rw['cycle_day_4'])}": float(rw["mean_correction"]) for _, rw in by_cycle.iterrows()},
    }


def _build_hypothesis_summary(
    *,
    win_detail: pd.DataFrame,
    phase2_detail: pd.DataFrame,
    lag4_result: dict[str, Any],
    output_dir: Path,
) -> None:
    n_win = int(len(win_detail))
    prefer_count = int((win_detail["correction_direction"] == "prefer_zorome").sum())
    avoid_count = int((win_detail["correction_direction"] == "avoid_zorome").sum())
    no_data_count = int((win_detail["correction_direction"] == "no_data").sum())

    prefer_ratio = float(prefer_count / n_win) if n_win > 0 else np.nan
    if n_win > 0 and prefer_ratio >= 0.7:
        verdict = "selective_injection_supported"
    else:
        verdict = "random_noise_not_rejected"

    d_row = phase2_detail[phase2_detail["strategy"] == "D"].iloc[0].to_dict()
    e_row = phase2_detail[phase2_detail["strategy"] == "E"].iloc[0].to_dict()

    lines = [
        "# Zorome Strategy Effectiveness Summary",
        "",
        "## Hypothesis Check",
        f"- B>A win days: {n_win}",
        f"- prefer_zorome among win days: {prefer_count}/{n_win} ({prefer_ratio:.2%})" if n_win > 0 else "- prefer_zorome among win days: NA",
        f"- avoid_zorome among win days: {avoid_count}",
        f"- no_data among win days: {no_data_count}",
        f"- Verdict: **{verdict}**",
        "",
        "## Strategy D vs E",
        f"- D mean_diff_per_calendar_day: {float(d_row['mean_diff_per_calendar_day']):.3f}",
        f"- D coverage: {float(d_row['coverage']):.4f}",
        f"- E mean_diff_per_calendar_day: {float(e_row['mean_diff_per_calendar_day']):.3f}",
        f"- E coverage: {float(e_row['coverage']):.4f}",
        "",
        "## Lag-4 Periodicity",
        f"- lag4 Pearson r: {lag4_result.get('lag4_corr')}",
        f"- lag4 Pearson p-value: {lag4_result.get('lag4_pvalue')}",
        "- Conclusion follows phase3_periodicity_report.json (`non_periodic`) unless p<0.05 in lag4 test.",
    ]
    (output_dir / "hypothesis_verdict_summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    args = build_parser().parse_args()
    db_path = Path(args.db_path)
    input_dir = Path(args.input_dir)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    all_days_df, win_detail = _build_phase1_win_details(input_dir, output_dir)
    _build_win_lose_pattern(all_days_df, output_dir)
    _build_correction_diagnosis(
        db_path=db_path,
        output_dir=output_dir,
        windows=_parse_windows(args.train_windows),
        eval_window_days=int(args.eval_window_days),
    )
    phase2_detail = _build_phase2_detailed(input_dir, output_dir)
    lag4 = _build_lag4_investigation(input_dir, output_dir)
    _build_hypothesis_summary(
        win_detail=win_detail,
        phase2_detail=phase2_detail,
        lag4_result=lag4,
        output_dir=output_dir,
    )
    print("Done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
