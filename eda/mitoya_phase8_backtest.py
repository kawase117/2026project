from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from eda.cross_hall_pattern_verification import COINS_PER_GAME
from eda.mitoya_phase7_shortlist import TARGET_SECTIONS
from eda.mitoya_phase7_shortlist_backtest import _build_period_plan, _limit_shortlist, load_data
from eda.mitoya_phase8_row_analysis import build_machine_layout_table
from eda.mitoya_prompt_common import RESULTS_DIR, ensure_results_dir, render_markdown_table, section_sort_key

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


OUTPUT_DIR = Path(__file__).resolve().parents[1] / "tmp" / "mitoya_phase8_backtest"
VERTICAL_ISLAND_SECTIONS = {"712-722", "723-733"}
CORNER_RULE_BUCKETS = {"corner1", "corner2-4"}
DEFAULT_TOP_N = 3
DEFAULT_MACHINE_CORNER_TOP_N = 3


def _prepare_frame(df: pd.DataFrame) -> pd.DataFrame:
    prepared = df.copy()
    if "date_dt" not in prepared.columns:
        prepared["date_dt"] = pd.to_datetime(prepared["date"], format="%Y%m%d", errors="coerce")
    if "is_xdds" not in prepared.columns:
        prepared["is_xdds"] = prepared["date_dt"].dt.day.isin({4, 7, 14, 17, 24, 27})
    if "period" not in prepared.columns:
        from eda.cross_hall_pattern_verification import WINDOW_MONTHS, assign_period

        prepared["period"] = assign_period(prepared["date_dt"], WINDOW_MONTHS)
    return prepared


def _attach_layout(df: pd.DataFrame) -> pd.DataFrame:
    required = {
        "row_order_in_section",
        "row_label",
        "row_corner_rank",
        "corner_bucket",
        "row_machine_count",
        "aisle_side_machine_number",
        "far_side_machine_number",
        "section_orientation",
    }
    if required.issubset(df.columns):
        return df.copy()
    layout = build_machine_layout_table(df, sections=[str(section) for section in TARGET_SECTIONS])
    if layout.empty:
        return df.copy()
    keep = layout[
        [
            "section",
            "machine_number",
            "row_order_in_section",
            "row_label",
            "row_corner_rank",
            "corner_bucket",
            "row_machine_count",
            "aisle_side_machine_number",
            "far_side_machine_number",
            "section_orientation",
        ]
    ].drop_duplicates(subset=["section", "machine_number"])
    return df.merge(keep, on=["section", "machine_number"], how="inner", validate="many_to_one")


def _payout_rate(df: pd.DataFrame) -> float:
    if df.empty:
        return float("nan")
    total_games = df["games"].sum()
    if total_games <= 0:
        return float("nan")
    return float(((total_games * COINS_PER_GAME + df["diff"].sum()) / (total_games * COINS_PER_GAME)) * 100)


def _summarize_subset(df: pd.DataFrame, prefix: str) -> dict[str, float]:
    if df.empty:
        return {
            f"{prefix}_avg_diff": float("nan"),
            f"{prefix}_payout_rate": float("nan"),
            f"{prefix}_win_rate": float("nan"),
            f"{prefix}_n_machine_days": float("nan"),
        }
    return {
        f"{prefix}_avg_diff": float(df["diff"].mean()),
        f"{prefix}_payout_rate": _payout_rate(df),
        f"{prefix}_win_rate": float((df["diff"] > 0).mean()),
        f"{prefix}_n_machine_days": float(len(df)),
    }


def _summarize_comparison(selected: pd.DataFrame, target: pd.DataFrame, prefix: str) -> dict[str, float]:
    rows = {}
    rows.update(_summarize_subset(selected, prefix))
    rows.update(_summarize_subset(target, "Target"))
    rows[f"{prefix}_vs_Target_diff"] = rows[f"{prefix}_avg_diff"] - rows["Target_avg_diff"]
    return rows


def _section_scope(df: pd.DataFrame, *, xday_only: bool) -> pd.DataFrame:
    scope = df.loc[df["section"].astype(str).isin([str(section) for section in TARGET_SECTIONS])].copy()
    if xday_only:
        scope = scope.loc[scope["is_xdds"]].copy()
    return scope


def _corner_rule_mask(df: pd.DataFrame) -> pd.Series:
    return df["section_orientation"].eq("horizontal") & df["is_reversed_section"].eq(0) & df["row_corner_rank"].le(4)


def _vertical_island_mask(df: pd.DataFrame) -> pd.Series:
    return df["section"].astype(str).isin(VERTICAL_ISLAND_SECTIONS)


def _train_machine_corner_table(train: pd.DataFrame, *, top_n: int) -> pd.DataFrame:
    if train.empty:
        return train.iloc[0:0].copy()

    train_combo = (
        train.groupby(["section", "machine_name", "corner_bucket"], dropna=False)
        .agg(
            train_avg_diff=("diff", "mean"),
            train_n=("diff", "size"),
            train_plus_rate=("diff", lambda s: float((s > 0).mean() * 100)),
        )
        .reset_index()
    )
    if train_combo.empty:
        return train.iloc[0:0].copy()

    train_combo = train_combo.sort_values(
        ["section", "train_avg_diff", "train_n", "machine_name", "corner_bucket"],
        ascending=[True, False, False, True, True],
        key=lambda col: col.map(section_sort_key) if col.name == "section" else col,
        kind="mergesort",
    )
    return train_combo.groupby("section", as_index=False, sort=False).head(top_n).reset_index(drop=True)


def _apply_machine_corner(target: pd.DataFrame, train_combo: pd.DataFrame) -> pd.DataFrame:
    if target.empty or train_combo.empty:
        return target.iloc[0:0].copy()
    return target.merge(
        train_combo[["section", "machine_name", "corner_bucket"]].drop_duplicates(),
        on=["section", "machine_name", "corner_bucket"],
        how="inner",
    )


def _evaluate_machine_corner(target: pd.DataFrame, train: pd.DataFrame, *, top_n: int) -> pd.DataFrame:
    train_combo = _train_machine_corner_table(train, top_n=top_n)
    if train_combo.empty:
        return target.iloc[0:0].copy()
    test_combo = _apply_machine_corner(target, train_combo)
    if test_combo.empty:
        return train_combo.assign(test_avg_diff=float("nan"), test_n=float("nan"), test_plus_rate=float("nan"))
    test_combo = (
        test_combo.groupby(["section", "machine_name", "corner_bucket"], dropna=False)
        .agg(
            test_avg_diff=("diff", "mean"),
            test_n=("diff", "size"),
            test_plus_rate=("diff", lambda s: float((s > 0).mean() * 100)),
        )
        .reset_index()
    )
    return train_combo.merge(test_combo, on=["section", "machine_name", "corner_bucket"], how="left")


def build_period_summary(
    df: pd.DataFrame, *, top_n: int = DEFAULT_TOP_N, machine_corner_top_n: int = DEFAULT_MACHINE_CORNER_TOP_N
) -> pd.DataFrame:
    prepared = _attach_layout(_prepare_frame(df))
    plan = _build_period_plan(
        prepared, sections=[str(section) for section in TARGET_SECTIONS], max_top_n=max(top_n, machine_corner_top_n)
    )

    rows: list[dict[str, object]] = []
    for item in plan:
        train = item["train"].copy()
        test = item["test"].copy()
        shortlist = _limit_shortlist(item["shortlist_max"].copy(), top_n)

        for scope_name, scoped_test in (("全体", test), ("X_DDS日", test.loc[test["is_xdds"]].copy())):
            target = _section_scope(scoped_test, xday_only=scope_name == "X_DDS日")
            if target.empty:
                rows.append(
                    {
                        "period_train": float(item["period_train"]),
                        "period_test": float(item["period_test"]),
                        "scope": scope_name,
                        **_summarize_subset(target, "Target"),
                        **_summarize_subset(target.iloc[0:0], "Shortlist"),
                        **_summarize_subset(target.iloc[0:0], "CornerRule"),
                        **_summarize_subset(target.iloc[0:0], "MachineCorner"),
                        **_summarize_subset(target.iloc[0:0], "VerticalIsland"),
                        "Shortlist_vs_Target_diff": float("nan"),
                        "CornerRule_vs_Target_diff": float("nan"),
                        "MachineCorner_vs_Target_diff": float("nan"),
                        "VerticalIsland_vs_Target_diff": float("nan"),
                        "n_xdds_dates": float(scoped_test["date_dt"].dt.normalize().nunique())
                        if scope_name == "X_DDS日"
                        else float("nan"),
                    }
                )
                continue

            shortlist_df = _filter_shortlist(target, shortlist)
            corner_df = target.loc[_corner_rule_mask(target)].copy()
            vertical_df = target.loc[_vertical_island_mask(target)].copy()
            machine_corner_keys = _train_machine_corner_table(train, top_n=machine_corner_top_n)
            machine_corner_df = _apply_machine_corner(target, machine_corner_keys)

            row = {
                "period_train": float(item["period_train"]),
                "period_test": float(item["period_test"]),
                "scope": scope_name,
                "n_xdds_dates": float(scoped_test["date_dt"].dt.normalize().nunique())
                if scope_name == "X_DDS日"
                else float("nan"),
            }
            row.update(_summarize_subset(target, "Target"))
            row.update(_summarize_subset(shortlist_df, "Shortlist"))
            row.update(_summarize_subset(corner_df, "CornerRule"))
            row.update(_summarize_subset(machine_corner_df, "MachineCorner"))
            row.update(_summarize_subset(vertical_df, "VerticalIsland"))
            row["Shortlist_vs_Target_diff"] = row["Shortlist_avg_diff"] - row["Target_avg_diff"]
            row["CornerRule_vs_Target_diff"] = row["CornerRule_avg_diff"] - row["Target_avg_diff"]
            row["MachineCorner_vs_Target_diff"] = row["MachineCorner_avg_diff"] - row["Target_avg_diff"]
            row["VerticalIsland_vs_Target_diff"] = row["VerticalIsland_avg_diff"] - row["Target_avg_diff"]
            rows.append(row)

    return pd.DataFrame(rows)


def _filter_shortlist(test_df: pd.DataFrame, shortlist: pd.DataFrame) -> pd.DataFrame:
    if shortlist.empty or test_df.empty:
        return test_df.iloc[0:0].copy()
    keys = shortlist.loc[:, ["section", "machine_name"]].drop_duplicates()
    return test_df.merge(keys, on=["section", "machine_name"], how="inner")


def build_corner_filter_summary(df: pd.DataFrame) -> pd.DataFrame:
    prepared = _attach_layout(_prepare_frame(df))
    plan = _build_period_plan(prepared, sections=[str(section) for section in TARGET_SECTIONS], max_top_n=DEFAULT_TOP_N)
    rows: list[dict[str, object]] = []
    for item in plan:
        train = item["train"].copy()
        test = item["test"].copy()
        for scoped_name, scoped_train, scoped_test in (
            ("全体", train, test),
            ("X_DDS日", train.loc[train["is_xdds"]].copy(), test.loc[test["is_xdds"]].copy()),
        ):
            train_groups = _corner_group_table(scoped_train, prefix="train")
            test_groups = _corner_group_table(scoped_test, prefix="test")
            merged = train_groups.merge(
                test_groups,
                on=["section", "section_orientation", "corner_bucket"],
                how="outer",
            )
            merged["period_train"] = float(item["period_train"])
            merged["period_test"] = float(item["period_test"])
            merged["scope"] = scoped_name
            rows.append(merged)
    if not rows:
        return pd.DataFrame()
    return pd.concat(rows, ignore_index=True)


def _corner_group_table(df: pd.DataFrame, *, prefix: str) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(
            columns=[
                "section",
                "section_orientation",
                "corner_bucket",
                f"{prefix}_n",
                f"{prefix}_avg_diff",
                f"{prefix}_plus_rate",
                f"{prefix}_payout_rate",
            ]
        )
    rows: list[dict[str, object]] = []
    for (section, section_orientation, corner_bucket), grp in df.groupby(
        ["section", "section_orientation", "corner_bucket"], dropna=False
    ):
        rows.append(
            {
                "section": str(section),
                "section_orientation": str(section_orientation),
                "corner_bucket": str(corner_bucket),
                f"{prefix}_n": int(len(grp)),
                f"{prefix}_avg_diff": float(grp["diff"].mean()),
                f"{prefix}_plus_rate": float((grp["diff"] > 0).mean() * 100),
                f"{prefix}_payout_rate": _payout_rate(grp),
            }
        )
    return pd.DataFrame(rows)


def build_machine_corner_summary(df: pd.DataFrame, *, top_n: int = DEFAULT_MACHINE_CORNER_TOP_N) -> pd.DataFrame:
    prepared = _attach_layout(_prepare_frame(df))
    plan = _build_period_plan(prepared, sections=[str(section) for section in TARGET_SECTIONS], max_top_n=DEFAULT_TOP_N)
    rows: list[dict[str, object]] = []
    for item in plan:
        train = item["train"].copy()
        test = item["test"].copy()
        train_combo = _train_machine_corner_table(train, top_n=top_n)
        if train_combo.empty:
            continue
        evaluated = _evaluate_machine_corner(test, train, top_n=top_n)
        merged = train_combo.merge(
            evaluated[["section", "machine_name", "corner_bucket", "test_avg_diff", "test_n", "test_plus_rate"]],
            on=["section", "machine_name", "corner_bucket"],
            how="left",
        )
        merged["period_train"] = float(item["period_train"])
        merged["period_test"] = float(item["period_test"])
        rows.append(merged)
    if not rows:
        return pd.DataFrame()
    return pd.concat(rows, ignore_index=True)


def build_xdds_split_summary(period_summary: pd.DataFrame) -> pd.DataFrame:
    if period_summary.empty:
        return pd.DataFrame()
    cols = [
        "Target_avg_diff",
        "Shortlist_avg_diff",
        "CornerRule_avg_diff",
        "MachineCorner_avg_diff",
        "VerticalIsland_avg_diff",
        "Shortlist_vs_Target_diff",
        "CornerRule_vs_Target_diff",
        "MachineCorner_vs_Target_diff",
        "VerticalIsland_vs_Target_diff",
    ]
    grouped = period_summary.groupby("scope", dropna=False)[cols].mean(numeric_only=True).reset_index()
    return grouped


def build_report(
    period_summary: pd.DataFrame,
    corner_filter_summary: pd.DataFrame,
    machine_corner_summary: pd.DataFrame,
    xdds_split_summary: pd.DataFrame,
    shortlist_period_table: pd.DataFrame,
) -> str:
    lines = [
        "# Mitoya Phase 8 Backtest",
        "",
        f"- target_sections: {', '.join(TARGET_SECTIONS)}",
        "",
        "## period summary",
        "",
        render_markdown_table(period_summary.head(40)) if not period_summary.empty else "_no rows_",
        "",
        "## corner filter summary",
        "",
        render_markdown_table(corner_filter_summary.head(40)) if not corner_filter_summary.empty else "_no rows_",
        "",
        "## machine_name x corner summary",
        "",
        render_markdown_table(machine_corner_summary.head(40)) if not machine_corner_summary.empty else "_no rows_",
        "",
        "## X_DDS split summary",
        "",
        render_markdown_table(xdds_split_summary) if not xdds_split_summary.empty else "_no rows_",
        "",
        "## shortlist period table",
        "",
        render_markdown_table(shortlist_period_table.head(40)) if not shortlist_period_table.empty else "_no rows_",
        "",
    ]
    return "\n".join(lines).rstrip() + "\n"


def build_backtest_outputs(df: pd.DataFrame) -> dict[str, pd.DataFrame | str]:
    prepared = _attach_layout(_prepare_frame(df))
    plan = _build_period_plan(prepared, sections=[str(section) for section in TARGET_SECTIONS], max_top_n=DEFAULT_TOP_N)

    shortlist_frames: list[pd.DataFrame] = []
    for item in plan:
        shortlist = _limit_shortlist(item["shortlist_max"].copy(), DEFAULT_TOP_N)
        if shortlist.empty:
            continue
        shortlist["period_train"] = float(item["period_train"])
        shortlist["period_test"] = float(item["period_test"])
        shortlist_frames.append(shortlist)

    shortlist_period_table = pd.concat(shortlist_frames, ignore_index=True) if shortlist_frames else pd.DataFrame()
    period_summary = build_period_summary(prepared)
    corner_filter_summary = build_corner_filter_summary(prepared)
    machine_corner_summary = build_machine_corner_summary(prepared)
    xdds_split_summary = build_xdds_split_summary(period_summary)
    report = build_report(
        period_summary, corner_filter_summary, machine_corner_summary, xdds_split_summary, shortlist_period_table
    )
    return {
        "period_summary": period_summary,
        "corner_filter_summary": corner_filter_summary,
        "machine_corner_summary": machine_corner_summary,
        "xdds_split_summary": xdds_split_summary,
        "shortlist_period_table": shortlist_period_table,
        "report": report,
    }


def save_outputs(artifacts: dict[str, pd.DataFrame | str], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    artifacts["period_summary"].to_csv(output_dir / "period_summary.csv", index=False, encoding="utf-8-sig")
    artifacts["corner_filter_summary"].to_csv(
        output_dir / "corner_filter_summary.csv", index=False, encoding="utf-8-sig"
    )
    artifacts["machine_corner_summary"].to_csv(
        output_dir / "machine_corner_summary.csv", index=False, encoding="utf-8-sig"
    )
    artifacts["xdds_split_summary"].to_csv(output_dir / "xdds_split_summary.csv", index=False, encoding="utf-8-sig")
    artifacts["shortlist_period_table"].to_csv(
        output_dir / "shortlist_period_table.csv", index=False, encoding="utf-8-sig"
    )
    (output_dir / "report.md").write_text(str(artifacts["report"]), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--min-games", type=int, default=1000)
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    return parser.parse_args()


def main(argv: list[str] | None = None) -> int:
    ensure_results_dir()
    parser = argparse.ArgumentParser()
    parser.add_argument("--min-games", type=int, default=1000)
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    args = parser.parse_args(argv)

    df = load_data(min_games=args.min_games)
    artifacts = build_backtest_outputs(df)
    save_outputs(artifacts, args.output_dir)
    print(f"Wrote {args.output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
