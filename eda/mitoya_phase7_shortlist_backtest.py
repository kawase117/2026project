from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from eda.cross_hall_pattern_verification import COINS_PER_GAME, WINDOW_MONTHS, assign_period
from eda.mitoya_phase7_shortlist import TARGET_SECTIONS, build_shortlist_table
from eda.mitoya_prompt_common import ensure_results_dir, load_mitoya_frame, render_markdown_table

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


OUTPUT_DIR = Path(__file__).resolve().parents[1] / "tmp" / "mitoya_phase7_shortlist_backtest"
MIN_GAMES = 1000
TOP_N_VALUES = (1, 2, 3, 4, 5)
X_DD_DAYS = {4, 7, 14, 17, 24, 27}
SHORTLIST_MIN_N = 50


def load_data(min_games: int = MIN_GAMES) -> pd.DataFrame:
    df = load_mitoya_frame(join_layout=True).copy()
    df = df.loc[df["games"] >= min_games].copy()
    df["date_dt"] = pd.to_datetime(df["date"], format="%Y%m%d", errors="coerce")
    df["period"] = assign_period(df["date_dt"], WINDOW_MONTHS)
    df["is_xdds"] = df["date_dt"].dt.day.isin(X_DD_DAYS)
    return df


def _prepare_frame(df: pd.DataFrame) -> pd.DataFrame:
    prepared = df.copy()
    if "date_dt" not in prepared.columns:
        prepared["date_dt"] = pd.to_datetime(prepared["date"], format="%Y%m%d", errors="coerce")
    if "period" not in prepared.columns:
        prepared["period"] = assign_period(prepared["date_dt"], WINDOW_MONTHS)
    if "is_xdds" not in prepared.columns:
        prepared["is_xdds"] = prepared["date_dt"].dt.day.isin(X_DD_DAYS)
    return prepared


def _build_period_plan(
    df: pd.DataFrame,
    *,
    sections: list[str] | None = None,
    max_top_n: int = 3,
) -> list[dict[str, object]]:
    prepared = _prepare_frame(df)
    target_sections = [str(section) for section in (sections or TARGET_SECTIONS)]
    periods = sorted(prepared["period"].dropna().unique())
    plan: list[dict[str, object]] = []
    for period_train, period_test in zip(periods[:-1], periods[1:], strict=True):
        train = prepared.loc[prepared["period"] == period_train].copy()
        test = prepared.loc[prepared["period"] == period_test].copy()
        latest_test_date = test["date_dt"].max()
        latest_test = test.loc[test["date_dt"] == latest_test_date].copy()
        available_machine_names = set(
            latest_test.loc[latest_test["section"].astype(str).isin(target_sections), "machine_name"].astype(str)
        )
        shortlist_max = build_shortlist_table(
            train,
            sections=target_sections,
            top_n=max_top_n,
            available_machine_names=available_machine_names,
        ).copy()
        plan.append(
            {
                "period_train": float(period_train),
                "period_test": float(period_test),
                "train": train,
                "test": test,
                "shortlist_max": shortlist_max,
            }
        )
    return plan


def _limit_shortlist(shortlist: pd.DataFrame, top_n: int) -> pd.DataFrame:
    if shortlist.empty:
        return shortlist.copy()
    limited = shortlist.groupby("section", as_index=False, sort=False).head(top_n).reset_index(drop=True)
    limited = limited.loc[limited["best_n"] >= SHORTLIST_MIN_N].copy()
    return limited.reset_index(drop=True)


def _empty_metrics(prefix: str) -> dict[str, float]:
    return {
        f"{prefix}_avg_diff": float("nan"),
        f"{prefix}_payout_rate": float("nan"),
        f"{prefix}_win_rate": float("nan"),
        f"{prefix}_n_machine_days": float("nan"),
    }


def _summarize_group(df: pd.DataFrame, prefix: str) -> dict[str, float]:
    if df.empty:
        return _empty_metrics(prefix)
    total_games = df["games"].sum()
    payout_rate = float("nan")
    if total_games > 0:
        payout_rate = ((total_games * COINS_PER_GAME + df["diff"].sum()) / (total_games * COINS_PER_GAME)) * 100
    return {
        f"{prefix}_avg_diff": df["diff"].mean(),
        f"{prefix}_payout_rate": payout_rate,
        f"{prefix}_win_rate": (df["diff"] > 0).mean(),
        f"{prefix}_n_machine_days": float(len(df)),
    }


def _skip_row() -> dict[str, float]:
    row: dict[str, float] = {}
    for prefix in ("Shortlist", "Target"):
        row.update(_empty_metrics(prefix))
    row["Shortlist_vs_Target_diff"] = float("nan")
    return row


def summarize_pair(
    test_df: pd.DataFrame,
    shortlist: pd.DataFrame,
    *,
    sections: list[str],
    skip_if_missing_shortlist: bool,
) -> dict[str, float]:
    if test_df.empty:
        return _skip_row()

    target_df = test_df.loc[test_df["section"].astype(str).isin([str(section) for section in sections])].copy()
    if target_df.empty:
        return _skip_row()

    shortlist_df = _filter_shortlist(target_df, shortlist)
    if skip_if_missing_shortlist and shortlist_df.empty:
        return _skip_row()

    row: dict[str, float] = {}
    row.update(_summarize_group(shortlist_df, "Shortlist"))
    row.update(_summarize_group(target_df, "Target"))
    row["Shortlist_vs_Target_diff"] = row["Shortlist_avg_diff"] - row["Target_avg_diff"]
    return row


def _filter_shortlist(test_df: pd.DataFrame, shortlist: pd.DataFrame) -> pd.DataFrame:
    if shortlist.empty or test_df.empty:
        return test_df.iloc[0:0].copy()
    keys = shortlist.loc[:, ["section", "machine_name"]].drop_duplicates()
    return test_df.merge(keys, on=["section", "machine_name"], how="inner")


def _frame_rows_from_plan(
    plan: list[dict[str, object]],
    *,
    sections: list[str],
    top_n: int,
    xday_only: bool = False,
) -> list[dict[str, float]]:
    rows: list[dict[str, float]] = []
    for item in plan:
        test = item["test"].copy()
        if xday_only:
            test = test.loc[test["is_xdds"]].copy()
        shortlist = _limit_shortlist(item["shortlist_max"].copy(), top_n)
        row = {
            "period_train": float(item["period_train"]),
            "period_test": float(item["period_test"]),
        }
        if xday_only:
            row["n_xdds_dates"] = float(test["date_dt"].dt.normalize().nunique())
        row.update(
            summarize_pair(
                test,
                shortlist,
                sections=sections,
                skip_if_missing_shortlist=shortlist.empty,
            )
        )
        rows.append(row)
    return rows


def build_period_summary(
    df: pd.DataFrame,
    *,
    sections: list[str] | None = None,
    top_n: int = 3,
    xday_only: bool = False,
) -> pd.DataFrame:
    target_sections = [str(section) for section in (sections or TARGET_SECTIONS)]
    plan = _build_period_plan(df, sections=target_sections, max_top_n=top_n)
    rows = _frame_rows_from_plan(plan, sections=target_sections, top_n=top_n, xday_only=xday_only)

    columns = [
        "period_train",
        "period_test",
        "Shortlist_avg_diff",
        "Shortlist_payout_rate",
        "Shortlist_win_rate",
        "Shortlist_n_machine_days",
        "Target_avg_diff",
        "Target_payout_rate",
        "Target_win_rate",
        "Target_n_machine_days",
        "Shortlist_vs_Target_diff",
    ]
    if xday_only:
        columns = ["period_train", "period_test", "n_xdds_dates"] + columns[2:]
    return pd.DataFrame(rows, columns=columns)


def build_shortlist_period_table(
    df: pd.DataFrame,
    *,
    sections: list[str] | None = None,
    top_n: int = 3,
) -> pd.DataFrame:
    target_sections = [str(section) for section in (sections or TARGET_SECTIONS)]
    plan = _build_period_plan(df, sections=target_sections, max_top_n=top_n)
    frames: list[pd.DataFrame] = []
    for item in plan:
        shortlist = _limit_shortlist(item["shortlist_max"].copy(), top_n)
        if shortlist.empty:
            continue
        shortlist["period_train"] = float(item["period_train"])
        shortlist["period_test"] = float(item["period_test"])
        frames.append(shortlist)

    if not frames:
        return pd.DataFrame(
            columns=[
                "period_train",
                "period_test",
                "section",
                "machine_name",
                "best_phase",
                "best_avg_diff",
                "best_plus_rate",
                "phase_count",
                "positive_phase_count",
                "best_n",
                "avg_rank_from_aisle",
                "rank",
            ]
        )
    return pd.concat(frames, ignore_index=True)


def build_top_n_sensitivity_table(
    df: pd.DataFrame,
    *,
    sections: list[str] | None = None,
    top_n_values: tuple[int, ...] = TOP_N_VALUES,
) -> pd.DataFrame:
    target_sections = [str(section) for section in (sections or TARGET_SECTIONS)]
    plan = _build_period_plan(df, sections=target_sections, max_top_n=max(top_n_values))
    rows: list[dict[str, float]] = []
    for top_n in top_n_values:
        period_rows = _frame_rows_from_plan(plan, sections=target_sections, top_n=top_n, xday_only=False)
        xdds_rows = _frame_rows_from_plan(plan, sections=target_sections, top_n=top_n, xday_only=True)
        for scope_name, frame_rows in (("全体", period_rows), ("X_DDS日", xdds_rows)):
            means = _mean_metrics(pd.DataFrame(frame_rows))
            rows.append(
                {
                    "top_n": int(top_n),
                    "scope": scope_name,
                    "Shortlist_avg_diff": means.get("Shortlist_avg_diff", float("nan")),
                    "Target_avg_diff": means.get("Target_avg_diff", float("nan")),
                    "Shortlist_vs_Target_diff": means.get("Shortlist_vs_Target_diff", float("nan")),
                    "Shortlist_payout_rate": means.get("Shortlist_payout_rate", float("nan")),
                    "Target_payout_rate": means.get("Target_payout_rate", float("nan")),
                    "Shortlist_win_rate": means.get("Shortlist_win_rate", float("nan")),
                    "Target_win_rate": means.get("Target_win_rate", float("nan")),
                }
            )
    return pd.DataFrame(rows)


def build_section_fixed_summary(
    df: pd.DataFrame,
    *,
    sections: list[str] | None = None,
    top_n: int = 1,
) -> pd.DataFrame:
    target_sections = [str(section) for section in (sections or TARGET_SECTIONS)]
    plan = _build_period_plan(df, sections=target_sections, max_top_n=top_n)
    rows: list[dict[str, float]] = []
    for section in target_sections:
        section_plan = [
            item for item in plan if not item["train"].loc[item["train"]["section"].astype(str) == section].empty
        ]
        if not section_plan:
            continue
        for scope_name in ("全体", "X_DDS日"):
            frame_rows: list[dict[str, float]] = []
            for item in section_plan:
                train = item["train"].loc[item["train"]["section"].astype(str) == section].copy()
                test = item["test"].loc[item["test"]["section"].astype(str) == section].copy()
                if scope_name == "X_DDS日":
                    test = test.loc[test["is_xdds"]].copy()
                shortlist = build_shortlist_table(train, sections=[section], top_n=top_n)
                frame_rows.append(
                    summarize_pair(
                        test,
                        shortlist,
                        sections=[section],
                        skip_if_missing_shortlist=shortlist.empty,
                    )
                )
            means = _mean_metrics(pd.DataFrame(frame_rows))
            rows.append(
                {
                    "section": section,
                    "scope": scope_name,
                    "Shortlist_avg_diff": means.get("Shortlist_avg_diff", float("nan")),
                    "Target_avg_diff": means.get("Target_avg_diff", float("nan")),
                    "Shortlist_vs_Target_diff": means.get("Shortlist_vs_Target_diff", float("nan")),
                    "Shortlist_payout_rate": means.get("Shortlist_payout_rate", float("nan")),
                    "Target_payout_rate": means.get("Target_payout_rate", float("nan")),
                    "Shortlist_win_rate": means.get("Shortlist_win_rate", float("nan")),
                    "Target_win_rate": means.get("Target_win_rate", float("nan")),
                }
            )
    return pd.DataFrame(rows)


def build_backtest_outputs(
    df: pd.DataFrame,
    *,
    sections: list[str] | None = None,
    top_n: int = 3,
) -> dict[str, pd.DataFrame]:
    return {
        "period_summary": build_period_summary(df, sections=sections, top_n=top_n),
        "xdds_overlay": build_period_summary(df, sections=sections, top_n=top_n, xday_only=True),
        "shortlist_per_period": build_shortlist_period_table(df, sections=sections, top_n=top_n),
    }


def build_scenario_summary(
    df: pd.DataFrame,
    *,
    scenarios: dict[str, dict[str, object]],
    top_n: int = 2,
) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for scenario_name, config in scenarios.items():
        sections = list(config["sections"])
        xday_only = bool(config.get("xday_only", False))
        outputs = build_backtest_outputs(df, sections=sections, top_n=top_n)
        frame = outputs["xdds_overlay"] if xday_only else outputs["period_summary"]
        means = _mean_metrics(frame)
        rows.append(
            {
                "scenario": scenario_name,
                "sections": ", ".join(sections),
                "xday_only": xday_only,
                "top_n": int(top_n),
                "pairs": int(len(frame)),
                "Shortlist_avg_diff": means.get("Shortlist_avg_diff", float("nan")),
                "Target_avg_diff": means.get("Target_avg_diff", float("nan")),
                "Shortlist_vs_Target_diff": means.get("Shortlist_vs_Target_diff", float("nan")),
                "Shortlist_payout_rate": means.get("Shortlist_payout_rate", float("nan")),
                "Target_payout_rate": means.get("Target_payout_rate", float("nan")),
                "Shortlist_win_rate": means.get("Shortlist_win_rate", float("nan")),
                "Target_win_rate": means.get("Target_win_rate", float("nan")),
            }
        )
    return pd.DataFrame(rows)


def _mean_metrics(df: pd.DataFrame) -> dict[str, float]:
    if df.empty:
        return {}
    numeric = df.select_dtypes(include="number")
    return numeric.mean(numeric_only=True, skipna=True).to_dict()


def _fmt(value: float | int | None, digits: int = 2) -> str:
    if value is None or pd.isna(value):
        return "NaN"
    return f"{value:.{digits}f}"


def build_report(outputs: dict[str, pd.DataFrame]) -> str:
    scopes = [
        ("全体", outputs["period_summary"]),
        ("X_DDS日", outputs["xdds_overlay"]),
    ]
    header = [
        "| scope | pairs | Shortlist_avg_diff | Target_avg_diff | Shortlist_vs_Target_diff | Shortlist_payout | Target_payout | Shortlist_win | Target_win |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    rows: list[str] = []
    means_by_scope: dict[str, dict[str, float]] = {}
    for name, df in scopes:
        means = _mean_metrics(df)
        means_by_scope[name] = means
        rows.append(
            "| "
            + " | ".join(
                [
                    name,
                    str(len(df)),
                    _fmt(means.get("Shortlist_avg_diff")),
                    _fmt(means.get("Target_avg_diff")),
                    _fmt(means.get("Shortlist_vs_Target_diff")),
                    _fmt(means.get("Shortlist_payout_rate")),
                    _fmt(means.get("Target_payout_rate")),
                    _fmt(means.get("Shortlist_win_rate")),
                    _fmt(means.get("Target_win_rate")),
                ]
            )
            + " |"
        )

    overall = means_by_scope.get("全体", {})
    xdds = means_by_scope.get("X_DDS日", {})
    shortlist_boost = xdds.get("Shortlist_avg_diff", float("nan")) - overall.get("Shortlist_avg_diff", float("nan"))
    target_boost = xdds.get("Target_avg_diff", float("nan")) - overall.get("Target_avg_diff", float("nan"))

    report_lines = [
        "# Mitoya Phase 7 Shortlist Backtest",
        "",
        "## 全体比較",
        "",
        *header,
        *rows,
        "",
        "## 主要差分",
        f"- 全体 Shortlist_vs_Target_diff: {_fmt(overall.get('Shortlist_vs_Target_diff'))}",
        f"- X_DDS日 Shortlist boost vs 全体: {_fmt(shortlist_boost)}",
        f"- X_DDS日 Target boost vs 全体: {_fmt(target_boost)}",
        f"- X_DDS日の平均対象日数/ペア: {_fmt(_mean_metrics(outputs['xdds_overlay']).get('n_xdds_dates'))}",
    ]
    return "\n".join(report_lines).rstrip() + "\n"


def build_extended_report(
    outputs: dict[str, pd.DataFrame],
    *,
    top_n_sensitivity: pd.DataFrame,
    section_fixed_summary: pd.DataFrame,
    scenario_summary: pd.DataFrame,
) -> str:
    parts = [build_report(outputs).rstrip()]
    if not top_n_sensitivity.empty:
        parts.extend(["## top_n 感度", "", render_markdown_table(top_n_sensitivity), ""])
    if not section_fixed_summary.empty:
        parts.extend(["## section 固定", "", render_markdown_table(section_fixed_summary), ""])
    if not scenario_summary.empty:
        parts.extend(["## 再バックテスト", "", render_markdown_table(scenario_summary), ""])
    return "\n".join(parts).rstrip() + "\n"


def save_outputs(
    outputs: dict[str, pd.DataFrame],
    output_dir: Path,
    *,
    top_n_sensitivity: pd.DataFrame,
    section_fixed_summary: pd.DataFrame,
    scenario_summary: pd.DataFrame,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    outputs["period_summary"].to_csv(output_dir / "period_summary.csv", index=False, encoding="utf-8-sig")
    outputs["xdds_overlay"].to_csv(output_dir / "xdds_overlay.csv", index=False, encoding="utf-8-sig")
    outputs["shortlist_per_period"].to_csv(output_dir / "shortlist_per_period.csv", index=False, encoding="utf-8-sig")
    top_n_sensitivity.to_csv(output_dir / "top_n_sensitivity.csv", index=False, encoding="utf-8-sig")
    section_fixed_summary.to_csv(output_dir / "section_fixed_summary.csv", index=False, encoding="utf-8-sig")
    scenario_summary.to_csv(output_dir / "scenario_summary.csv", index=False, encoding="utf-8-sig")
    (output_dir / "report.md").write_text(
        build_extended_report(
            outputs,
            top_n_sensitivity=top_n_sensitivity,
            section_fixed_summary=section_fixed_summary,
            scenario_summary=scenario_summary,
        ),
        encoding="utf-8",
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--min-games", type=int, default=MIN_GAMES)
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    return parser.parse_args()


def build_all_artifacts(df: pd.DataFrame) -> tuple[dict[str, pd.DataFrame], pd.DataFrame, pd.DataFrame]:
    outputs = build_backtest_outputs(df, top_n=3)
    top_n_sensitivity = build_top_n_sensitivity_table(df)
    section_fixed_summary = build_section_fixed_summary(df, top_n=1)
    scenarios = {
        "557-573_only": {"sections": ["557-573"], "xday_only": False},
        "501-522_xdds_only": {"sections": ["501-522"], "xday_only": True},
    }
    scenario_summary = build_scenario_summary(df, scenarios=scenarios, top_n=2)
    return outputs, top_n_sensitivity, section_fixed_summary, scenario_summary


def main() -> None:
    args = parse_args()
    ensure_results_dir()
    df = load_data(min_games=args.min_games)
    outputs, top_n_sensitivity, section_fixed_summary, scenario_summary = build_all_artifacts(df)
    save_outputs(
        outputs,
        args.output_dir,
        top_n_sensitivity=top_n_sensitivity,
        section_fixed_summary=section_fixed_summary,
        scenario_summary=scenario_summary,
    )
    print(f"saved outputs to {args.output_dir}")


if __name__ == "__main__":
    main()
