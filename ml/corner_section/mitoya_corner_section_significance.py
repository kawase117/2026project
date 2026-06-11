from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

if __package__ is None or __package__ == "":
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from ml.corner_section.mitoya_corner_section_analysis import (
    load_analysis_frame,
    prepare_analysis_frame,
    resolve_mitoya_db_path,
)

DEFAULT_OUTPUT_DIR = "data/mitoya_corner_section_analysis"
DEFAULT_OUTPUT_CSV = "data/mitoya_corner_section_analysis/kruskal_rank_from_min.csv"


def _epsilon_squared(statistic: float, n_groups: int, n_rows: int) -> float:
    if not np.isfinite(statistic) or n_groups < 2 or n_rows <= n_groups:
        return float("nan")
    return float(max((statistic - n_groups + 1) / (n_rows - n_groups), 0.0))


def build_significance_report(df: pd.DataFrame, group_col: str) -> pd.DataFrame:
    if group_col not in {"rank_from_min", "section"}:
        raise ValueError(f"Unsupported group_col: {group_col}")

    work = df.loc[df["is_hall_plus"].eq(1)].copy()
    work[group_col] = work[group_col].astype("string")
    work = work.dropna(subset=[group_col, "diff_coins_normalized"]).copy()
    if group_col == "rank_from_min":
        work[group_col] = pd.to_numeric(work[group_col], errors="coerce")
        work = work.dropna(subset=[group_col]).copy()
        work[group_col] = work[group_col].astype(int)
    else:
        work[group_col] = work[group_col].astype(str)

    if work.empty:
        raise ValueError(f"No hall-plus rows available for {group_col} significance testing.")

    group_summary = (
        work.groupby(group_col, sort=True)
        .agg(
            sample_n=("diff_coins_normalized", "size"),
            avg_diff=("diff_coins_normalized", "mean"),
            median_diff=("diff_coins_normalized", "median"),
            plus_rate=("diff_coins_normalized", lambda s: float((pd.to_numeric(s, errors="coerce") > 0).mean())),
        )
        .reset_index()
        .sort_values("avg_diff", ascending=False)
        .reset_index(drop=True)
    )

    groups = [
        group["diff_coins_normalized"].dropna().to_numpy(dtype=float)
        for _, group in work.groupby(group_col, sort=True)
        if len(group) > 0
    ]
    valid_groups = [group for group in groups if len(group) > 0]
    statistic = float("nan")
    p_value = float("nan")
    if len(valid_groups) >= 2:
        try:
            statistic, p_value = stats.kruskal(*valid_groups)
        except ValueError:
            statistic, p_value = float("nan"), float("nan")

    overall = pd.DataFrame(
        [
            {
                "test_type": "kruskal_overall",
                "group_col": group_col,
                "group_value": "ALL",
                "n_groups": int(len(valid_groups)),
                "n_rows": int(sum(len(group) for group in valid_groups)),
                "statistic": statistic,
                "p_value": p_value,
                "epsilon_sq": _epsilon_squared(statistic, len(valid_groups), int(sum(len(group) for group in valid_groups))),
                "is_significant_5pct": int(np.isfinite(p_value) and p_value < 0.05),
            }
        ]
    )

    report = group_summary.copy()
    report.insert(0, "group_col", group_col)
    report.insert(1, "test_type", "group_summary")
    report.insert(2, "p_value", p_value)
    report.insert(3, "statistic", statistic)
    report.insert(4, "epsilon_sq", _epsilon_squared(statistic, len(valid_groups), int(sum(len(group) for group in valid_groups))))
    report.insert(5, "n_groups", int(len(valid_groups)))
    report["group_value"] = report[group_col]
    report = report.drop(columns=[group_col])
    report = report.loc[
        :,
        [
            "test_type",
            "group_col",
            "group_value",
            "sample_n",
            "avg_diff",
            "median_diff",
            "plus_rate",
            "n_groups",
            "statistic",
            "p_value",
            "epsilon_sq",
        ],
    ]
    return pd.concat([overall, report], ignore_index=True)


def build_rank_from_min_significance_report(df: pd.DataFrame) -> pd.DataFrame:
    return build_significance_report(df, "rank_from_min")


def build_section_significance_report(df: pd.DataFrame) -> pd.DataFrame:
    return build_significance_report(df, "section")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run Kruskal-Wallis significance check for Mitoya corner positions.")
    parser.add_argument("--db-path", default="", help="Explicit DB path override.")
    parser.add_argument("--db-dir", default="db", help="Directory used for DB auto-resolution.")
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR, help="Directory for the two CSV outputs.")
    parser.add_argument(
        "--output-csv",
        default="",
        help="Backward-compatible single-file output path for rank_from_min only.",
    )
    return parser


def _render_summary(report: pd.DataFrame, group_col: str) -> str:
    overall = report.loc[report["test_type"].eq("kruskal_overall")].iloc[0]
    group_rows = report.loc[report["test_type"].eq("group_summary")].copy()
    title = "角番（rank_from_min）" if group_col == "rank_from_min" else "列（section）"
    lines = [
        f"=== みとや {title}有意性検定 ===",
        "",
        "[Kruskal-Wallis]",
        "  ".join(
            [
                f"n_groups: {int(overall['n_groups'])}",
                f"n_rows: {int(overall['n_rows'])}",
                f"p: {float(overall['p_value']):.6g}" if pd.notna(overall["p_value"]) else "p: nan",
                f"epsilon_sq: {float(overall['epsilon_sq']):.6f}" if pd.notna(overall["epsilon_sq"]) else "epsilon_sq: nan",
                f"significant: {'Yes' if int(overall['is_significant_5pct']) == 1 else 'No'}",
            ]
        ),
        "",
        "[TOP5 by avg_diff]",
    ]
    if group_rows.empty:
        lines.append("(no rows)")
    else:
        lines.append(
            group_rows.sort_values("avg_diff", ascending=False)
            .loc[:, ["group_value", "sample_n", "avg_diff", "median_diff", "plus_rate"]]
            .head(5)
            .to_string(index=False)
        )
    return "\n".join(lines) + "\n"


def _write_single_output(report: pd.DataFrame, output_csv: Path) -> None:
    output_csv.parent.mkdir(parents=True, exist_ok=True)
    report.to_csv(output_csv, index=False, encoding="utf-8-sig")


def main(argv: list[str] | None = None) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    args = build_parser().parse_args(argv)
    db_path = resolve_mitoya_db_path(str(args.db_path), db_dir=Path(args.db_dir))
    base_df = prepare_analysis_frame(load_analysis_frame(db_path))
    rank_report = build_rank_from_min_significance_report(base_df)

    if str(args.output_csv).strip():
        _write_single_output(rank_report, Path(args.output_csv))
        print(_render_summary(rank_report, "rank_from_min"))
        return 0

    section_report = build_section_significance_report(base_df)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    _write_single_output(rank_report, output_dir / "kruskal_rank_from_min.csv")
    _write_single_output(section_report, output_dir / "kruskal_section.csv")
    print(_render_summary(rank_report, "rank_from_min"))
    print(_render_summary(section_report, "section"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
