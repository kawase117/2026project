from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from eda.section_lateral_expansion import (  # noqa: E402
    HALL_CONFIGS,
    HallConfig,
    _load_hall_frame,
    _markdown_table,
    is_event_day,
)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_OUTPUT_DIR = SCRIPT_DIR / "results" / "rakuen_split_walkforward"
DEFAULT_WINDOW_DAYS = 90
DEFAULT_MIN_GAMES = 2000
DEFAULT_TOP_KS = (3, 5, 10)
DEFAULT_EVAL_DAYS = 120
MIN_SAME_TYPE_DATES = 10
WINDOW_EXPAND_STEP = 30


@dataclass(frozen=True)
class WalkForwardResult:
    date: str
    event_type: str
    model: str
    top_k: int
    precision: float
    lift: float
    diff_excess: float
    n_candidates: int


def _parse_top_ks(raw: str | tuple[int, ...]) -> tuple[int, ...]:
    if isinstance(raw, tuple):
        return tuple(int(value) for value in raw)
    values = [part.strip() for part in str(raw).split(",") if part.strip()]
    if not values:
        raise ValueError("top_ks cannot be empty")
    parsed = tuple(int(value) for value in values)
    if any(value <= 0 for value in parsed):
        raise ValueError("top_ks must contain positive integers")
    return parsed


def _normalize_eval_dates(frame: pd.DataFrame, *, eval_days: int) -> pd.Index:
    unique_dates = pd.Index(sorted(pd.Timestamp(value).normalize() for value in frame["date_dt"].dropna().unique()))
    if len(unique_dates) <= int(eval_days):
        return unique_dates
    return unique_dates[-int(eval_days) :]


def _event_label(target_dt: pd.Timestamp, cfg: HallConfig) -> str:
    return "event" if is_event_day(target_dt, cfg) else "nonevent"


def _build_training_windows(
    frame: pd.DataFrame,
    target_dt: pd.Timestamp,
    *,
    cfg: HallConfig,
    event_type: str,
    window_days: int,
) -> tuple[int, pd.DataFrame, pd.DataFrame]:
    first_date = pd.Timestamp(frame["date_dt"].min()).normalize()
    effective_window = int(window_days)
    history = pd.DataFrame()
    split_history = pd.DataFrame()

    while True:
        window_start = target_dt - pd.Timedelta(days=effective_window)
        history = frame[(frame["date_dt"].lt(target_dt)) & (frame["date_dt"].ge(window_start))].copy()
        if history.empty:
            if window_start <= first_date:
                return effective_window, history, split_history
            effective_window += WINDOW_EXPAND_STEP
            continue

        history["hit_flag"] = (pd.to_numeric(history["diff_coins_normalized"], errors="coerce") > 0).astype(int)
        split_history = history.loc[[is_event_day(pd.Timestamp(value), cfg) for value in history["date_dt"]]].copy()
        if event_type == "nonevent":
            split_history = history.loc[
                [not is_event_day(pd.Timestamp(value), cfg) for value in history["date_dt"]]
            ].copy()

        if split_history["date_dt"].nunique() >= MIN_SAME_TYPE_DATES or window_start <= first_date:
            return effective_window, history, split_history
        effective_window += WINDOW_EXPAND_STEP


def _score_sections(
    train: pd.DataFrame,
    actual: pd.DataFrame,
    *,
    top_k: int,
) -> dict[str, object]:
    if train.empty or actual.empty:
        return {}

    section_stats = (
        train.groupby(["floor", "section", "section_min", "section_max", "section_size"], as_index=False)
        .agg(
            train_rows=("machine_number", "size"),
            section_hit_rate=("hit_flag", "mean"),
            train_diff=("diff_coins_normalized", "mean"),
        )
        .copy()
    )
    section_stats = section_stats.dropna(subset=["section_hit_rate"]).copy()
    if section_stats.empty:
        return {}

    section_stats = section_stats.sort_values(
        ["section_hit_rate", "train_rows", "floor", "section_min", "section"],
        ascending=[False, False, True, True, True],
        kind="mergesort",
    ).reset_index(drop=True)

    recommended = section_stats.head(int(top_k)).copy()
    if recommended.empty:
        return {}

    actual["hit_flag"] = (pd.to_numeric(actual["diff_coins_normalized"], errors="coerce") > 0).astype(int)
    all_hit_rate = float(actual["hit_flag"].mean()) if not actual.empty else float("nan")
    all_diff = float(pd.to_numeric(actual["diff_coins_normalized"], errors="coerce").mean())

    recommended_actual = actual.merge(
        recommended.loc[:, ["floor", "section", "section_min", "section_max", "section_size"]],
        on=["floor", "section", "section_min", "section_max", "section_size"],
        how="inner",
        validate="m:1",
    )
    if recommended_actual.empty:
        return {}

    precision = float(recommended_actual["hit_flag"].mean())
    recommended_diff = float(pd.to_numeric(recommended_actual["diff_coins_normalized"], errors="coerce").mean())
    lift = float(precision / all_hit_rate) if pd.notna(all_hit_rate) and all_hit_rate > 0 else float("nan")
    diff_excess = (
        float(recommended_diff - all_diff) if pd.notna(recommended_diff) and pd.notna(all_diff) else float("nan")
    )

    return {
        "precision": precision,
        "lift": lift,
        "diff_excess": diff_excess,
        "n_candidates": int(len(recommended_actual)),
        "n_sections": int(len(recommended)),
        "model_hit_rate": all_hit_rate,
        "model_avg_diff": all_diff,
        "recommended_avg_diff": recommended_diff,
    }


def _evaluate_day(
    frame: pd.DataFrame,
    target_dt: pd.Timestamp,
    *,
    cfg: HallConfig,
    window_days: int,
    top_ks: tuple[int, ...],
) -> list[dict[str, object]]:
    event_type = _event_label(target_dt, cfg)
    _effective_window, history, split_history = _build_training_windows(
        frame,
        target_dt,
        cfg=cfg,
        event_type=event_type,
        window_days=window_days,
    )
    if history.empty:
        return []

    actual = frame.loc[frame["date_dt"].eq(target_dt)].copy()
    if actual.empty:
        return []

    baseline_train = history.copy()
    split_train = split_history.copy()
    if split_train.empty:
        return []

    rows: list[dict[str, object]] = []
    for model_name, train in (("split", split_train), ("baseline", baseline_train)):
        work_train = train.copy()
        work_train["hit_flag"] = (pd.to_numeric(work_train["diff_coins_normalized"], errors="coerce") > 0).astype(int)
        for top_k in top_ks:
            metrics = _score_sections(work_train, actual.copy(), top_k=int(top_k))
            if not metrics:
                continue
            rows.append(
                {
                    "date": target_dt.strftime("%Y-%m-%d"),
                    "event_type": event_type,
                    "model": model_name,
                    "top_k": int(top_k),
                    "precision": metrics["precision"],
                    "lift": metrics["lift"],
                    "diff_excess": metrics["diff_excess"],
                    "n_candidates": metrics["n_candidates"],
                }
            )
    return rows


def build_backtest_outputs(
    frame: pd.DataFrame | None = None,
    *,
    window_days: int = DEFAULT_WINDOW_DAYS,
    min_games: int = DEFAULT_MIN_GAMES,
    top_ks: tuple[int, ...] = DEFAULT_TOP_KS,
    eval_days: int = DEFAULT_EVAL_DAYS,
) -> dict[str, pd.DataFrame]:
    cfg = HALL_CONFIGS["rakuen"]
    if frame is None:
        frame, _coords = _load_hall_frame(cfg, min_games=min_games)
    work = frame.copy()
    work["date_dt"] = pd.to_datetime(work["date"], format="%Y%m%d", errors="coerce")
    work["machine_number"] = pd.to_numeric(work["machine_number"], errors="coerce")
    work["section_min"] = pd.to_numeric(work["section_min"], errors="coerce")
    work["section_max"] = pd.to_numeric(work["section_max"], errors="coerce")
    work["section_size"] = pd.to_numeric(work["section_size"], errors="coerce")
    work["games_normalized"] = pd.to_numeric(work["games_normalized"], errors="coerce")
    work["diff_coins_normalized"] = pd.to_numeric(work["diff_coins_normalized"], errors="coerce")
    work = work.dropna(
        subset=[
            "date_dt",
            "machine_number",
            "floor",
            "section",
            "section_min",
            "section_max",
            "section_size",
            "games_normalized",
            "diff_coins_normalized",
        ]
    ).copy()
    work["machine_number"] = work["machine_number"].astype(int)
    work["section_min"] = work["section_min"].astype(int)
    work["section_max"] = work["section_max"].astype(int)
    work["section_size"] = work["section_size"].astype(int)
    work = work.sort_values(["date_dt", "floor", "section_min", "machine_number"]).reset_index(drop=True)

    eval_dates = _normalize_eval_dates(work, eval_days=eval_days)
    daily_rows: list[dict[str, object]] = []
    for target_dt in eval_dates:
        daily_rows.extend(
            _evaluate_day(
                work,
                pd.Timestamp(target_dt),
                cfg=cfg,
                window_days=window_days,
                top_ks=top_ks,
            )
        )

    daily = pd.DataFrame(
        daily_rows,
        columns=["date", "event_type", "model", "top_k", "precision", "lift", "diff_excess", "n_candidates"],
    )
    if daily.empty:
        summary = pd.DataFrame(
            columns=["event_type", "model", "top_k", "n_days", "precision_mean", "lift_mean", "diff_excess_mean"]
        )
    else:
        summary_rows: list[dict[str, object]] = []
        for event_type, subset in (
            ("event", daily[daily["event_type"].eq("event")].copy()),
            ("nonevent", daily[daily["event_type"].eq("nonevent")].copy()),
            ("all", daily.copy()),
        ):
            for model_name in ("split", "baseline"):
                model_subset = subset[subset["model"].eq(model_name)].copy()
                for top_k in top_ks:
                    scoped = model_subset[model_subset["top_k"].eq(int(top_k))].copy()
                    if scoped.empty:
                        continue
                    summary_rows.append(
                        {
                            "event_type": event_type,
                            "model": model_name,
                            "top_k": int(top_k),
                            "n_days": int(len(scoped)),
                            "precision_mean": float(scoped["precision"].mean()),
                            "lift_mean": float(scoped["lift"].mean()),
                            "diff_excess_mean": float(scoped["diff_excess"].mean()),
                        }
                    )
        summary = pd.DataFrame(
            summary_rows,
            columns=["event_type", "model", "top_k", "n_days", "precision_mean", "lift_mean", "diff_excess_mean"],
        )
        summary = summary.sort_values(["event_type", "model", "top_k"]).reset_index(drop=True)

    report = build_report(daily, summary, top_ks=top_ks, eval_days=len(eval_dates), window_days=window_days)
    return {"daily": daily, "summary": summary, "report": pd.DataFrame({"report": [report]})}


def _comparison_frame(summary: pd.DataFrame, *, event_type: str, top_ks: tuple[int, ...]) -> pd.DataFrame:
    if summary.empty:
        return pd.DataFrame()
    scoped = summary[summary["event_type"].eq(event_type)].copy()
    if scoped.empty:
        return pd.DataFrame()
    split = scoped[scoped["model"].eq("split")].copy()
    baseline = scoped[scoped["model"].eq("baseline")].copy()
    if split.empty or baseline.empty:
        return pd.DataFrame()
    rows: list[dict[str, object]] = []
    for top_k in top_ks:
        split_row = split[split["top_k"].eq(int(top_k))]
        baseline_row = baseline[baseline["top_k"].eq(int(top_k))]
        if split_row.empty or baseline_row.empty:
            continue
        split_row = split_row.iloc[0]
        baseline_row = baseline_row.iloc[0]
        rows.append(
            {
                "top_k": int(top_k),
                "precision_split": float(split_row["precision_mean"]),
                "precision_baseline": float(baseline_row["precision_mean"]),
                "precision_delta": float(split_row["precision_mean"] - baseline_row["precision_mean"]),
                "lift_split": float(split_row["lift_mean"]),
                "lift_baseline": float(baseline_row["lift_mean"]),
                "lift_delta": float(split_row["lift_mean"] - baseline_row["lift_mean"]),
                "diff_excess_split": float(split_row["diff_excess_mean"]),
                "diff_excess_baseline": float(baseline_row["diff_excess_mean"]),
                "diff_excess_delta": float(split_row["diff_excess_mean"] - baseline_row["diff_excess_mean"]),
            }
        )
    return pd.DataFrame(rows)


def build_report(
    daily: pd.DataFrame,
    summary: pd.DataFrame,
    *,
    top_ks: tuple[int, ...],
    eval_days: int,
    window_days: int,
) -> str:
    lines: list[str] = []
    lines.append("# 楽園蒲田店 splitモデル walk-forwardバックテスト")
    lines.append("")
    lines.append("## 1. 手法概要")
    lines.append(f"- 対象ホール: `rakuen`。評価日は直近 `{eval_days}` 日、学習窓は基本 `{window_days}` 日です。")
    lines.append(
        "- event 判定は `day in event_dds` に加えて、楽園のみ強ゾロ目（`month == day`）を event として扱います。"
    )
    lines.append("- split モデルは、評価日と同じ event / nonevent 種別の履歴だけで section hit rate を学習します。")
    lines.append("- baseline モデルは、同じ履歴窓を使い、event / nonevent 分割をせずに全履歴を学習します。")
    lines.append(
        "- 各日について、section の `diff_coins_normalized > 0` 比率で上位 `top_k` section を推薦し、実績の precision, lift, 差枚優位を集計します。"
    )
    lines.append("")

    lines.append("## 2. 全体サマリー表")
    if summary.empty:
        lines.append("No rows.")
    else:
        lines.append(_markdown_table(summary, float_digits=4))
    lines.append("")

    lines.append("## 3. event/nonevent別の詳細")
    for event_type in ("event", "nonevent", "all"):
        scoped = summary[summary["event_type"].eq(event_type)].copy()
        lines.append(f"### {event_type}")
        if scoped.empty:
            lines.append("No rows.")
        else:
            lines.append(_markdown_table(scoped, float_digits=4))
        lines.append("")

    lines.append("## 4. split vs baseline比較")
    for event_type in ("event", "nonevent", "all"):
        comparison = _comparison_frame(summary, event_type=event_type, top_ks=top_ks)
        lines.append(f"### {event_type}")
        if comparison.empty:
            lines.append("No rows.")
        else:
            lines.append(_markdown_table(comparison, float_digits=4))
        lines.append("")

    lines.append("## 5. 蒲田1との比較所感")
    lines.append(
        "- 蒲田1で確立した「event 日は event 履歴のみ、nonevent 日は nonevent 履歴のみ」という分離を、楽園では strong_zorome を含む event 定義でそのまま適用しています。"
    )
    lines.append(
        "- baseline との比較で、event 側の上振れが split で強く出るか、nonevent 側で分離による劣化がないかを確認する前提の報告にしています。"
    )
    lines.append(
        "- 楽園は 10, 11, 22, 30 日に加えて強ゾロ目の寄与があるため、event 側の分離効果が蒲田1と同じ形にはならない可能性があります。"
    )
    lines.append("")
    return "\n".join(lines).strip() + "\n"


def run_backtest(
    frame: pd.DataFrame | None = None,
    *,
    output_dir: Path | None = None,
    window_days: int = DEFAULT_WINDOW_DAYS,
    min_games: int = DEFAULT_MIN_GAMES,
    top_ks: tuple[int, ...] = DEFAULT_TOP_KS,
) -> dict[str, pd.DataFrame]:
    outputs = build_backtest_outputs(
        frame,
        window_days=window_days,
        min_games=min_games,
        top_ks=top_ks,
    )
    outdir = output_dir or DEFAULT_OUTPUT_DIR
    outdir.mkdir(parents=True, exist_ok=True)
    outputs["daily"].to_csv(outdir / "daily_results.csv", index=False, encoding="utf-8-sig")
    outputs["summary"].to_csv(outdir / "summary.csv", index=False, encoding="utf-8-sig")
    (outdir / "report.md").write_text(outputs["report"].iloc[0]["report"], encoding="utf-8")
    return outputs


def main() -> None:
    parser = argparse.ArgumentParser(description="楽園蒲田店 splitモデル walk-forwardバックテスト")
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--window-days", type=int, default=DEFAULT_WINDOW_DAYS)
    parser.add_argument("--min-games", type=int, default=DEFAULT_MIN_GAMES)
    parser.add_argument("--top-ks", type=_parse_top_ks, default=DEFAULT_TOP_KS)
    args = parser.parse_args()

    run_backtest(
        frame=None,
        output_dir=args.output_dir,
        window_days=args.window_days,
        min_games=args.min_games,
        top_ks=tuple(args.top_ks),
    )


if __name__ == "__main__":
    main()
