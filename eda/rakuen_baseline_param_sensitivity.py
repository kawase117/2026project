from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from eda.rakuen_split_walkforward import (  # noqa: E402
    DEFAULT_EVAL_DAYS,
    DEFAULT_MIN_GAMES,
    DEFAULT_TOP_KS,
    DEFAULT_WINDOW_DAYS,
    build_backtest_outputs,
)
from eda.section_lateral_expansion import (  # noqa: E402
    HALL_CONFIGS,
    _load_hall_frame,
    _markdown_table,
    _write_csv,
)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_OUTPUT_DIR = SCRIPT_DIR / "results" / "rakuen_baseline_param_sensitivity"
DEFAULT_WINDOW_SENSITIVITY = (30, 60, 90, 120, 180)
DEFAULT_MIN_GAMES_SENSITIVITY = (1000, 1500, 2000, 2500, 3000)
DEFAULT_TOP_K_SENSITIVITY = (1, 3, 5, 10, 15, 20)
BASELINE_TOP_K = 5
BASELINE_MIN_GAMES = 2000
BASELINE_WINDOW_DAYS = 90
MIN_GAMES_BASELINE_LOAD = min(DEFAULT_MIN_GAMES_SENSITIVITY)


@dataclass(frozen=True)
class SweepConfig:
    name: str
    parameter_name: str
    candidate_values: tuple[int, ...]
    fixed_window_days: int
    fixed_min_games: int
    fixed_top_ks: tuple[int, ...]
    variable: str


def _format_float(value: object, *, digits: int = 4) -> str:
    if value is None or pd.isna(value):
        return ""
    if isinstance(value, (int,)):
        return str(int(value))
    if isinstance(value, float):
        return f"{value:.{digits}f}"
    return str(value)


def _filter_frame(frame: pd.DataFrame, *, min_games: int) -> pd.DataFrame:
    return frame.loc[frame["games_normalized"].ge(min_games)].copy()


def _save_run_outputs(output_dir: Path, outputs: dict[str, pd.DataFrame]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    _write_csv(outputs["daily"], output_dir / "daily_results.csv")
    _write_csv(outputs["summary"], output_dir / "summary.csv")
    report = outputs["report"].iloc[0]["report"] if not outputs["report"].empty else ""
    (output_dir / "report.md").write_text(str(report), encoding="utf-8")


def _baseline_sweep_rows(
    *,
    summary: pd.DataFrame,
    sweep_name: str,
    parameter_name: str,
    parameter_value: int | None,
    fixed_window_days: int,
    fixed_min_games: int,
    fixed_top_ks: tuple[int, ...],
    run_dir: Path,
    reference_top_k: int,
) -> pd.DataFrame:
    baseline = summary.loc[summary["model"].eq("baseline")].copy()
    if baseline.empty:
        return pd.DataFrame(
            columns=[
                "sweep",
                "parameter",
                "parameter_value",
                "event_type",
                "top_k",
                "n_days",
                "precision",
                "lift",
                "diff_excess",
                "precision_delta_vs_baseline",
                "lift_delta_vs_baseline",
                "diff_excess_delta_vs_baseline",
                "fixed_window_days",
                "fixed_min_games",
                "fixed_top_ks",
                "run_dir",
            ]
        )

    reference = baseline.loc[baseline["event_type"].eq("all")].copy()
    if reference.empty:
        reference = baseline.copy()
    matched_reference = reference.loc[reference["top_k"].eq(int(reference_top_k))].copy()
    if matched_reference.empty:
        matched_reference = reference.sort_values(["top_k", "n_days"], ascending=[True, False]).copy()
    reference = matched_reference.iloc[0]

    rows: list[dict[str, object]] = []
    for _, row in baseline.iterrows():
        row_parameter_value = int(row["top_k"]) if parameter_name == "top_k" else int(parameter_value)
        rows.append(
            {
                "sweep": sweep_name,
                "parameter": parameter_name,
                "parameter_value": row_parameter_value,
                "event_type": row["event_type"],
                "top_k": int(row["top_k"]),
                "n_days": int(row["n_days"]),
                "precision": float(row["precision_mean"]),
                "lift": float(row["lift_mean"]),
                "diff_excess": float(row["diff_excess_mean"]),
                "precision_delta_vs_baseline": float(row["precision_mean"] - reference["precision_mean"]),
                "lift_delta_vs_baseline": float(row["lift_mean"] - reference["lift_mean"]),
                "diff_excess_delta_vs_baseline": float(row["diff_excess_mean"] - reference["diff_excess_mean"]),
                "fixed_window_days": int(fixed_window_days),
                "fixed_min_games": int(fixed_min_games),
                "fixed_top_ks": ",".join(str(value) for value in fixed_top_ks),
                "run_dir": str(run_dir),
            }
        )

    frame = pd.DataFrame(rows)
    frame = frame.sort_values(["event_type", "parameter_value", "top_k"]).reset_index(drop=True)
    return frame


def _best_all_scope_row(frame: pd.DataFrame) -> pd.Series | None:
    if frame.empty:
        return None
    scoped = frame.loc[frame["event_type"].eq("all")].copy()
    if scoped.empty:
        scoped = frame.copy()
    scoped = scoped.sort_values(
        ["precision", "lift", "diff_excess", "parameter_value"],
        ascending=[False, False, False, True],
        kind="mergesort",
    ).reset_index(drop=True)
    return scoped.iloc[0]


def _sweep_summary(frame: pd.DataFrame, *, parameter_name: str) -> pd.DataFrame:
    if frame.empty:
        return frame
    rows: list[dict[str, object]] = []
    for parameter_value, subset in frame.groupby("parameter_value", sort=True):
        best_row = _best_all_scope_row(subset)
        rows.append(
            {
                "parameter": parameter_name,
                "parameter_value": int(parameter_value),
                "best_event_type": "" if best_row is None else str(best_row["event_type"]),
                "best_top_k": "" if best_row is None else int(best_row["top_k"]),
                "best_precision": "" if best_row is None else float(best_row["precision"]),
                "best_lift": "" if best_row is None else float(best_row["lift"]),
                "best_diff_excess": "" if best_row is None else float(best_row["diff_excess"]),
            }
        )
    return pd.DataFrame(rows)


def _sweep_spread(frame: pd.DataFrame) -> dict[str, float]:
    if frame.empty:
        return {"precision_span": float("nan"), "lift_span": float("nan"), "diff_excess_span": float("nan")}
    return {
        "precision_span": float(frame["best_precision"].max() - frame["best_precision"].min()),
        "lift_span": float(frame["best_lift"].max() - frame["best_lift"].min()),
        "diff_excess_span": float(frame["best_diff_excess"].max() - frame["best_diff_excess"].min()),
    }


def _build_section_table(frame: pd.DataFrame, *, title: str) -> list[str]:
    lines = [title]
    if frame.empty:
        lines.append("No rows.")
        return lines
    lines.append(_markdown_table(frame, float_digits=4))
    return lines


def _build_report(
    *,
    output_root: Path,
    window_rows: pd.DataFrame,
    min_games_rows: pd.DataFrame,
    top_k_rows: pd.DataFrame,
    window_summary: pd.DataFrame,
    min_games_summary: pd.DataFrame,
    top_k_summary: pd.DataFrame,
    window_spread: dict[str, float],
    min_games_spread: dict[str, float],
    top_k_spread: dict[str, float],
    recommendation: dict[str, object],
) -> str:
    lines: list[str] = []
    lines.append("# Rakuen baseline parameter sensitivity")
    lines.append("")
    lines.append("## 1. 手法概要")
    lines.append(
        "- 楽園蒲田店の `rakuen_split_walkforward.py` を import して、baseline モデルだけを対象に単変数スイープを行った。"
    )
    lines.append(
        f"- 比較軸は `window_days={BASELINE_WINDOW_DAYS}` / `min_games={BASELINE_MIN_GAMES}` / `top_k={BASELINE_TOP_K}` を基準に、他の 2 変数を固定した 1 変数ずつの感度分析。"
    )
    lines.append(
        f"- 出力先は `{output_root.as_posix()}`。各候補は個別ディレクトリに保存し、集計結果は `precision` / `lift` / `diff_excess` の 3 指標で比較した。"
    )
    lines.append("")

    lines.append("## 2. window_days感度")
    lines.append(
        f"- 固定値: `min_games={BASELINE_MIN_GAMES}`, `top_k={BASELINE_TOP_K}`。候補は {list(DEFAULT_WINDOW_SENSITIVITY)}。"
    )
    lines.append("")
    lines.extend(_build_section_table(window_summary, title="### all scope summary"))
    lines.append("")
    lines.extend(_build_section_table(window_rows, title="### baseline rows"))
    lines.append("")

    lines.append("## 3. min_games感度")
    lines.append(
        f"- 固定値: `window_days={BASELINE_WINDOW_DAYS}`, `top_k={BASELINE_TOP_K}`。候補は {list(DEFAULT_MIN_GAMES_SENSITIVITY)}。"
    )
    lines.append("")
    lines.extend(_build_section_table(min_games_summary, title="### all scope summary"))
    lines.append("")
    lines.extend(_build_section_table(min_games_rows, title="### baseline rows"))
    lines.append("")

    lines.append("## 4. top_k感度")
    lines.append(
        f"- 固定値: `window_days={BASELINE_WINDOW_DAYS}`, `min_games={BASELINE_MIN_GAMES}`。候補は {list(DEFAULT_TOP_K_SENSITIVITY)}。"
    )
    lines.append("")
    lines.extend(_build_section_table(top_k_summary, title="### all scope summary"))
    lines.append("")
    lines.extend(_build_section_table(top_k_rows, title="### baseline rows"))
    lines.append("")

    lines.append("## 5. 推奨パラメータセットとその根拠")
    lines.append(
        f"- 推奨値: `window_days={recommendation['window_days']}`, `min_games={recommendation['min_games']}`, `top_k={recommendation['top_k']}`。"
    )
    lines.append(
        f"- 根拠: window は `{recommendation['window_reason']}`、min_games は `{recommendation['min_games_reason']}`、top_k は `{recommendation['top_k_reason']}`。"
    )
    lines.append(
        "- この結論は grid search ではなく、各変数を独立に振った単変数感度から組み立てた。交互作用は未検証なので、ここでの推奨は最有力候補という位置づけ。"
    )
    lines.append("")

    lines.append("## 6. 現行値(window=90,min_games=2000,top_k=3-5)との比較")
    lines.append(
        f"- 現行値は `window_days={BASELINE_WINDOW_DAYS}`, `min_games={BASELINE_MIN_GAMES}`, `top_k=3/5/10` の運用に相当する。"
    )
    lines.append(
        f"- 推奨値との差分は `window_days {BASELINE_WINDOW_DAYS} -> {recommendation['window_days']}`, `min_games {BASELINE_MIN_GAMES} -> {recommendation['min_games']}`, `top_k 3/5/10 -> {recommendation['top_k']}`。"
    )
    lines.append(
        f"- baseline の全体スコープでは、window の感度幅は precision `{window_spread['precision_span']:.4f}` / lift `{window_spread['lift_span']:.4f}` / diff_excess `{window_spread['diff_excess_span']:.4f}`、"
        f"min_games は precision `{min_games_spread['precision_span']:.4f}` / lift `{min_games_spread['lift_span']:.4f}` / diff_excess `{min_games_spread['diff_excess_span']:.4f}`、"
        f"top_k は precision `{top_k_spread['precision_span']:.4f}` / lift `{top_k_spread['lift_span']:.4f}` / diff_excess `{top_k_spread['diff_excess_span']:.4f}`。"
    )
    lines.append(
        "- 数値が最も動いたのは {0}。安定度が高かったのは {1}。".format(
            recommendation["most_sensitive"],
            recommendation["least_sensitive"],
        )
    )
    lines.append("")
    return "\n".join(lines).strip() + "\n"


def _run_sweep(
    *,
    base_frame: pd.DataFrame,
    output_root: Path,
    sweep: SweepConfig,
    eval_days: int,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    run_root = output_root / "runs" / sweep.name
    rows: list[pd.DataFrame] = []
    if sweep.variable == "top_k":
        frame = _filter_frame(base_frame, min_games=sweep.fixed_min_games)
        run_dir = run_root / ("top_ks_" + "_".join(str(value) for value in sweep.candidate_values))
        outputs = build_backtest_outputs(
            frame=frame,
            window_days=int(sweep.fixed_window_days),
            min_games=int(sweep.fixed_min_games),
            top_ks=tuple(int(value) for value in sweep.candidate_values),
            eval_days=eval_days,
        )
        _save_run_outputs(run_dir, outputs)
        rows.append(
            _baseline_sweep_rows(
                summary=outputs["summary"],
                sweep_name=sweep.name,
                parameter_name=sweep.parameter_name,
                parameter_value=None,
                fixed_window_days=int(sweep.fixed_window_days),
                fixed_min_games=int(sweep.fixed_min_games),
                fixed_top_ks=sweep.fixed_top_ks,
                run_dir=run_dir,
                reference_top_k=BASELINE_TOP_K,
            )
        )
    else:
        for candidate in sweep.candidate_values:
            if sweep.variable == "window_days":
                frame = _filter_frame(base_frame, min_games=sweep.fixed_min_games)
                run_dir = run_root / f"window_{candidate}"
                outputs = build_backtest_outputs(
                    frame=frame,
                    window_days=int(candidate),
                    min_games=int(sweep.fixed_min_games),
                    top_ks=sweep.fixed_top_ks,
                    eval_days=eval_days,
                )
            elif sweep.variable == "min_games":
                frame = _filter_frame(base_frame, min_games=int(candidate))
                run_dir = run_root / f"min_games_{candidate}"
                outputs = build_backtest_outputs(
                    frame=frame,
                    window_days=int(sweep.fixed_window_days),
                    min_games=int(candidate),
                    top_ks=sweep.fixed_top_ks,
                    eval_days=eval_days,
                )
            else:
                raise ValueError(f"unsupported sweep variable: {sweep.variable}")

            _save_run_outputs(run_dir, outputs)
            rows.append(
                _baseline_sweep_rows(
                    summary=outputs["summary"],
                    sweep_name=sweep.name,
                    parameter_name=sweep.parameter_name,
                    parameter_value=int(candidate),
                    fixed_window_days=int(sweep.fixed_window_days),
                    fixed_min_games=int(sweep.fixed_min_games),
                    fixed_top_ks=sweep.fixed_top_ks,
                    run_dir=run_dir,
                    reference_top_k=BASELINE_TOP_K,
                )
            )

    combined = pd.concat(rows, ignore_index=True) if rows else pd.DataFrame()
    summary = _sweep_summary(combined, parameter_name=sweep.parameter_name)
    return combined, summary


def _recommend(
    *,
    window_summary: pd.DataFrame,
    min_games_summary: pd.DataFrame,
    top_k_summary: pd.DataFrame,
    window_spread: dict[str, float],
    min_games_spread: dict[str, float],
    top_k_spread: dict[str, float],
) -> dict[str, object]:
    window_best = window_summary.sort_values(
        ["best_precision", "best_lift", "best_diff_excess", "parameter_value"],
        ascending=[False, False, False, True],
        kind="mergesort",
    ).iloc[0]
    min_games_best = min_games_summary.sort_values(
        ["best_precision", "best_lift", "best_diff_excess", "parameter_value"],
        ascending=[False, False, False, True],
        kind="mergesort",
    ).iloc[0]
    top_k_best = top_k_summary.sort_values(
        ["best_precision", "best_lift", "best_diff_excess", "parameter_value"],
        ascending=[False, False, False, True],
        kind="mergesort",
    ).iloc[0]

    sensitivity_scores = {
        "window_days": window_spread["precision_span"] + window_spread["lift_span"] + window_spread["diff_excess_span"],
        "min_games": min_games_spread["precision_span"]
        + min_games_spread["lift_span"]
        + min_games_spread["diff_excess_span"],
        "top_k": top_k_spread["precision_span"] + top_k_spread["lift_span"] + top_k_spread["diff_excess_span"],
    }

    return {
        "window_days": int(window_best["parameter_value"]),
        "min_games": int(min_games_best["parameter_value"]),
        "top_k": int(top_k_best["parameter_value"]),
        "window_reason": (
            f"all scope の best precision={_format_float(window_best['best_precision'])}, "
            f"lift={_format_float(window_best['best_lift'])}, diff_excess={_format_float(window_best['best_diff_excess'])}"
        ),
        "min_games_reason": (
            f"all scope の best precision={_format_float(min_games_best['best_precision'])}, "
            f"lift={_format_float(min_games_best['best_lift'])}, diff_excess={_format_float(min_games_best['best_diff_excess'])}"
        ),
        "top_k_reason": (
            f"all scope の best precision={_format_float(top_k_best['best_precision'])}, "
            f"lift={_format_float(top_k_best['best_lift'])}, diff_excess={_format_float(top_k_best['best_diff_excess'])}"
        ),
        "most_sensitive": max(sensitivity_scores.items(), key=lambda item: item[1])[0],
        "least_sensitive": min(sensitivity_scores.items(), key=lambda item: item[1])[0],
    }


def run(output_dir: Path = DEFAULT_OUTPUT_DIR, *, eval_days: int = DEFAULT_EVAL_DAYS) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    base_frame, _coords = _load_hall_frame(HALL_CONFIGS["rakuen"], min_games=MIN_GAMES_BASELINE_LOAD)

    window_sweep = SweepConfig(
        name="window_days",
        parameter_name="window_days",
        candidate_values=DEFAULT_WINDOW_SENSITIVITY,
        fixed_window_days=BASELINE_WINDOW_DAYS,
        fixed_min_games=BASELINE_MIN_GAMES,
        fixed_top_ks=(BASELINE_TOP_K,),
        variable="window_days",
    )
    min_games_sweep = SweepConfig(
        name="min_games",
        parameter_name="min_games",
        candidate_values=DEFAULT_MIN_GAMES_SENSITIVITY,
        fixed_window_days=BASELINE_WINDOW_DAYS,
        fixed_min_games=BASELINE_MIN_GAMES,
        fixed_top_ks=(BASELINE_TOP_K,),
        variable="min_games",
    )
    top_k_sweep = SweepConfig(
        name="top_k",
        parameter_name="top_k",
        candidate_values=DEFAULT_TOP_K_SENSITIVITY,
        fixed_window_days=BASELINE_WINDOW_DAYS,
        fixed_min_games=BASELINE_MIN_GAMES,
        fixed_top_ks=DEFAULT_TOP_KS,
        variable="top_k",
    )

    window_rows, window_summary = _run_sweep(
        base_frame=base_frame, output_root=output_dir, sweep=window_sweep, eval_days=eval_days
    )
    min_games_rows, min_games_summary = _run_sweep(
        base_frame=base_frame,
        output_root=output_dir,
        sweep=min_games_sweep,
        eval_days=eval_days,
    )
    top_k_rows, top_k_summary = _run_sweep(
        base_frame=base_frame, output_root=output_dir, sweep=top_k_sweep, eval_days=eval_days
    )

    window_spread = _sweep_spread(window_summary)
    min_games_spread = _sweep_spread(min_games_summary)
    top_k_spread = _sweep_spread(top_k_summary)

    _write_csv(window_rows, output_dir / "window_days_sensitivity.csv")
    _write_csv(min_games_rows, output_dir / "min_games_sensitivity.csv")
    _write_csv(top_k_rows, output_dir / "top_k_sensitivity.csv")

    recommendation = _recommend(
        window_summary=window_summary,
        min_games_summary=min_games_summary,
        top_k_summary=top_k_summary,
        window_spread=window_spread,
        min_games_spread=min_games_spread,
        top_k_spread=top_k_spread,
    )
    report = _build_report(
        output_root=output_dir,
        window_rows=window_rows,
        min_games_rows=min_games_rows,
        top_k_rows=top_k_rows,
        window_summary=window_summary,
        min_games_summary=min_games_summary,
        top_k_summary=top_k_summary,
        window_spread=window_spread,
        min_games_spread=min_games_spread,
        top_k_spread=top_k_spread,
        recommendation=recommendation,
    )
    (output_dir / "report.md").write_text(report, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Rakuen baseline parameter sensitivity analysis")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--eval-days", type=int, default=DEFAULT_EVAL_DAYS)
    args = parser.parse_args()
    run(output_dir=args.output_dir, eval_days=args.eval_days)


if __name__ == "__main__":
    main()
