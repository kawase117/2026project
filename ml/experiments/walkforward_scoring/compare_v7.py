from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from .config import RESULTS_DIR


VARIANT_ORDER = ("v6a_hit_an", "v6b_seg_weights", "v7_lift_weights")
VARIANT_LABELS = {
    "v6a_hit_an": "v6a",
    "v6b_seg_weights": "v6b",
    "v7_lift_weights": "v7",
}

SUMMARY_METRICS = ("avg_diff", "avg_diff_vs_other", "win_rate", "payout_rate", "hit@50", "lift@50", "n_test_days")
SPLIT_METRICS = ("avg_diff_vs_other", "lift@50")
EVENT_METRICS = ("avg_diff", "win_rate")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Compare v7 walk-forward results against v6 baselines")
    parser.add_argument("--results-dir", type=Path, default=RESULTS_DIR)
    return parser


def _load_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    return pd.read_csv(path, encoding="utf-8-sig")


def _display_variant(variant: str) -> str:
    return VARIANT_LABELS.get(variant, variant)


def _ordered_variants(available: pd.DataFrame) -> list[str]:
    present = set(available["variant"].astype(str).unique()) if not available.empty and "variant" in available.columns else set()
    return [variant for variant in VARIANT_ORDER if variant in present]


def _format_cell(metric: str, value: object) -> str:
    if pd.isna(value):
        return "n/a"
    if isinstance(value, str):
        return value
    numeric = float(value)
    if metric in {"win_rate", "payout_rate"}:
        return f"{numeric:.1f}%"
    if metric == "n_test_days":
        return f"{int(round(numeric))}"
    if metric == "lift@50":
        return f"{numeric:.2f}"
    if metric in {"avg_diff", "avg_diff_vs_other"}:
        return f"{numeric:.1f}"
    return f"{numeric:.2f}"


def _render_metric_table(frame: pd.DataFrame) -> str:
    if frame.empty:
        return "No data."
    out = frame.copy()
    for column in out.columns[1:]:
        out[column] = [ _format_cell(str(metric), value) for metric, value in zip(out.iloc[:, 0], out[column]) ]
    return out.to_string(index=False)


def _build_summary_table(daily_results: pd.DataFrame) -> pd.DataFrame:
    if daily_results.empty:
        return pd.DataFrame(columns=["metric"])
    grouped = (
        daily_results.groupby("variant", as_index=True)
        .agg(
            avg_diff=("avg_diff", "mean"),
            avg_diff_vs_other=("avg_diff_vs_other", "mean"),
            win_rate=("win_rate", "mean"),
            payout_rate=("payout_rate", "mean"),
            **{"hit@50": ("hit@50", "mean"), "lift@50": ("lift@50", "mean")},
            n_test_days=("test_date", "nunique"),
        )
    )
    ordered = [variant for variant in VARIANT_ORDER if variant in grouped.index]
    table = grouped.reindex(ordered)
    table.index = [_display_variant(index) for index in table.index]
    return table.T.reset_index(names="metric")


def _build_split_table(daily_results: pd.DataFrame, *, metric_columns: tuple[str, ...]) -> pd.DataFrame:
    if daily_results.empty or "split_period" not in daily_results.columns:
        return pd.DataFrame(columns=["metric"])
    grouped = (
        daily_results.groupby(["variant", "split_period"], as_index=False)
        .agg(
            avg_diff=("avg_diff", "mean"),
            avg_diff_vs_other=("avg_diff_vs_other", "mean"),
            win_rate=("win_rate", "mean"),
            payout_rate=("payout_rate", "mean"),
            **{"hit@50": ("hit@50", "mean"), "lift@50": ("lift@50", "mean")},
            n_test_days=("test_date", "nunique"),
        )
    )
    data: dict[str, list[object]] = {"metric": list(metric_columns)}
    for variant in VARIANT_ORDER:
        v_rows = grouped[grouped["variant"].eq(variant)]
        if v_rows.empty:
            continue
        by_period = v_rows.set_index("split_period")
        for period in ("front", "back"):
            col_name = f"{_display_variant(variant)}({period[0].upper()})"
            data[col_name] = [by_period.at[period, metric] if period in by_period.index else pd.NA for metric in metric_columns]
    return pd.DataFrame(data)


def _build_event_table(daily_results: pd.DataFrame) -> pd.DataFrame:
    if daily_results.empty or "event_type" not in daily_results.columns:
        return pd.DataFrame(columns=["metric"])
    grouped = (
        daily_results.groupby(["variant", "event_type"], as_index=False)
        .agg(
            avg_diff=("avg_diff", "mean"),
            avg_diff_vs_other=("avg_diff_vs_other", "mean"),
            win_rate=("win_rate", "mean"),
            payout_rate=("payout_rate", "mean"),
            **{"hit@50": ("hit@50", "mean"), "lift@50": ("lift@50", "mean")},
            n_test_days=("test_date", "nunique"),
        )
    )
    rows: dict[str, list[object]] = {"metric": list(EVENT_METRICS)}
    for variant in VARIANT_ORDER:
        for event_type in ("event", "non_event"):
            suffix = "event" if event_type == "event" else "non"
            col_name = f"{_display_variant(variant)}({suffix})"
            subset = grouped[(grouped["variant"].eq(variant)) & (grouped["event_type"].eq(event_type))]
            rows[col_name] = [subset.iloc[0][metric] if not subset.empty else pd.NA for metric in EVENT_METRICS]
    return pd.DataFrame(rows)


def _build_segment_table(segment_daily_results: pd.DataFrame) -> pd.DataFrame:
    if segment_daily_results.empty or "segment" not in segment_daily_results.columns:
        return pd.DataFrame(columns=["segment", "v6a", "v6b", "v7", "diff_v7_v6a", "v7_better"])
    grouped = (
        segment_daily_results.groupby(["segment", "variant"], as_index=False)
        .agg(avg_diff=("avg_diff", "mean"))
    )
    rows: list[dict[str, object]] = []
    for segment in sorted(grouped["segment"].astype(str).unique()):
        row: dict[str, object] = {"segment": segment}
        for variant in VARIANT_ORDER:
            subset = grouped[(grouped["segment"].astype(str).eq(segment)) & (grouped["variant"].eq(variant))]
            row[_display_variant(variant)] = float(subset["avg_diff"].iloc[0]) if not subset.empty else pd.NA
        if pd.notna(row.get("v7")) and pd.notna(row.get("v6a")):
            row["diff_v7_v6a"] = float(row["v7"]) - float(row["v6a"])
            row["v7_better"] = "○" if row["diff_v7_v6a"] > 0 else "×"
        else:
            row["diff_v7_v6a"] = pd.NA
            row["v7_better"] = "n/a"
        rows.append(row)
    return pd.DataFrame(rows)


def _overall_summary(daily_results: pd.DataFrame) -> pd.DataFrame:
    if daily_results.empty:
        return pd.DataFrame()
    grouped = (
        daily_results.groupby("variant", as_index=False)
        .agg(
            avg_diff=("avg_diff", "mean"),
            avg_diff_vs_other=("avg_diff_vs_other", "mean"),
            win_rate=("win_rate", "mean"),
            payout_rate=("payout_rate", "mean"),
            **{"hit@50": ("hit@50", "mean"), "lift@50": ("lift@50", "mean")},
            n_test_days=("test_date", "nunique"),
        )
        .set_index("variant")
    )
    ordered = [variant for variant in VARIANT_ORDER if variant in grouped.index]
    if not ordered:
        return pd.DataFrame()
    grouped = grouped.reindex(ordered)
    grouped.index = [_display_variant(index) for index in grouped.index]
    table = grouped.T.reset_index(names="metric")
    return table


def _pairwise_eval(summary: pd.DataFrame, split_table: pd.DataFrame) -> str:
    if summary.empty or "metric" not in summary.columns:
        return "v6a維持"

    summary_indexed = summary.set_index("metric")
    if "avg_diff_vs_other" not in summary_indexed.index:
        return "v6a維持"

    v6a_col = "v6a"
    v7_col = "v7"
    if v6a_col not in summary_indexed.columns or v7_col not in summary_indexed.columns:
        return "v6a維持"

    v7_better_overall = float(summary_indexed.at["avg_diff_vs_other", v7_col]) > float(summary_indexed.at["avg_diff_vs_other", v6a_col])

    if split_table.empty or "metric" not in split_table.columns:
        return "追加検証必要" if v7_better_overall else "v6a維持"

    split_indexed = split_table.set_index("metric")
    front_col = "v7(F)"
    back_col = "v7(B)"
    front_base = "v6a(F)"
    back_base = "v6a(B)"
    if not all(col in split_indexed.columns for col in [front_col, back_col, front_base, back_base]):
        return "追加検証必要" if v7_better_overall else "v6a維持"

    front_better = float(split_indexed.at["avg_diff_vs_other", front_col]) > float(split_indexed.at["avg_diff_vs_other", front_base])
    back_better = float(split_indexed.at["avg_diff_vs_other", back_col]) > float(split_indexed.at["avg_diff_vs_other", back_base])

    if v7_better_overall and front_better and back_better:
        return "v7採用"
    if v7_better_overall and (front_better or back_better):
        return "追加検証必要"
    return "v6a維持"


def _render_section(title: str, body: str) -> str:
    return "\n".join([title, "", body.rstrip(), ""])


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    results_dir: Path = args.results_dir
    daily_path = results_dir / "daily_results.csv"
    segment_path = results_dir / "segment_daily_results.csv"

    daily_results = _load_csv(daily_path)
    if daily_results.empty:
        raise SystemExit(f"missing or empty daily_results.csv: {daily_path}")

    segment_daily_results = _load_csv(segment_path)
    summary = _overall_summary(daily_results)
    split_table = _build_split_table(daily_results, metric_columns=SPLIT_METRICS)
    event_table = _build_event_table(daily_results)
    segment_table = _build_segment_table(segment_daily_results)
    conclusion = _pairwise_eval(summary, split_table)

    unique_dates = daily_results["test_date"].nunique() if "test_date" in daily_results.columns else 0
    windows = ", ".join(str(value) for value in sorted(daily_results["window"].dropna().unique())) if "window" in daily_results.columns else ""
    window_text = f"Window: {windows}" if windows else "Window: n/a"

    lines = [
        "========================================",
        "v7 vs v6a/v6b Walk-Forward Backtest 比較",
        "========================================",
        "",
        f"テスト期間: {daily_results['test_date'].min()} 〜 {daily_results['test_date'].max()} ({unique_dates}日)",
        window_text,
        "",
        "注: v7 は 2F_R_N を除外するため hit@K は参考値。主指標は avg_diff_vs_other。",
        "",
        "--- 全期間サマリー ---",
        _render_metric_table(summary if not summary.empty else pd.DataFrame()),
        "",
        "--- Front/Back Split ---",
        _render_metric_table(split_table if not split_table.empty else pd.DataFrame()),
        "",
        "--- Event/Non-Event 分割 ---",
        _render_metric_table(event_table if not event_table.empty else pd.DataFrame()),
        "",
    ]

    if segment_table.empty:
        lines.extend(["--- セグメント別 avg_diff (v7 vs v6a) ---", "No segment_daily_results.csv available.", ""])
    else:
        lines.extend(["--- セグメント別 avg_diff (v7 vs v6a) ---", _render_metric_table(segment_table), ""])

    lines.extend(
        [
            "--- 結論 ---",
            f"v7はv6aに対して {'改善' if conclusion == 'v7採用' else '悪化' if conclusion == 'v6a維持' else '同等/要確認'}",
            f"Front/Back安定性: {'安定' if conclusion == 'v7採用' else '不安定' if conclusion == 'v6a維持' else '要追加検証'}",
            f"推奨: {conclusion}",
            "",
        ]
    )

    output = "\n".join(lines).rstrip() + "\n"
    print(output, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
