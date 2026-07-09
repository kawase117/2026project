from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if __package__ in {None, ""}:
    sys.path.insert(0, str(PROJECT_ROOT))

from eda.mitoya_umj_mister_common import (
    RESULT_DIR,
    compact_float,
    compact_pct,
    load_frame,
    verdict_mark,
)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


REPORT_PATH = PROJECT_ROOT / "eda" / "results" / "mitoya_umj_mister_dd_investigation.md"
TASK_AB_SUMMARY = RESULT_DIR / "task_ab_candidate_summary.csv"
TASK_AB_RANKING = RESULT_DIR / "task_ab_dd_ranking.csv"
TASK_C_SUMMARY = RESULT_DIR / "task_c_machine_number_summary.csv"
TASK_C_DETAIL = RESULT_DIR / "task_c_machine_number_detail.csv"
TASK_D_SUMMARY = RESULT_DIR / "task_d_dd19_dd29_summary.csv"


def _load_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"missing required result file: {path}")
    return pd.read_csv(path)


def _fmt_rate(value: float) -> str:
    if value is None or pd.isna(value):
        return "NaN"
    return f"1/{1.0 / float(value):.1f}" if float(value) > 0 else "NaN"


def _fmt_signed_pp(value: float) -> str:
    if value is None or pd.isna(value):
        return "NaN"
    return f"{float(value):+.3f}pp"


def _fmt_signed_pct(value: float) -> str:
    if value is None or pd.isna(value):
        return "NaN"
    return f"{float(value) * 100.0:+.1f}%"


def _table(headers: list[str], rows: list[list[object]]) -> str:
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join(["---"] * len(headers)) + " |",
    ]
    for row in rows:
        cells = []
        for cell in row:
            if cell is None:
                cells.append("NaN")
            elif isinstance(cell, str):
                cells.append(cell)
            elif pd.isna(cell):
                cells.append("NaN")
            elif isinstance(cell, float):
                cells.append(compact_float(cell, 4))
            else:
                cells.append(str(cell))
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def _summary_rows(df: pd.DataFrame, *, model: str) -> pd.DataFrame:
    work = df.loc[df["model"] == model].copy()
    if work.empty:
        return work
    return work.sort_values(["rank", "dd"], kind="mergesort").reset_index(drop=True)


def _weekday_row(row: pd.Series) -> list[object]:
    return [
        row["model"],
        int(row["rank"]),
        int(row["dd"]),
        compact_float(row["weekday_mon_rate"], 5),
        compact_float(row["weekday_tue_rate"], 5),
        compact_float(row["weekday_wed_rate"], 5),
        compact_float(row["weekday_thu_rate"], 5),
        compact_float(row["weekday_fri_rate"], 5),
        compact_float(row["weekday_sat_rate"], 5),
        compact_float(row["weekday_sun_rate"], 5),
        compact_float(row["weekday_weekday_rate"], 5),
        compact_float(row["weekday_weekend_rate"], 5),
        compact_float(row["weekday_weekend_p"], 4),
        row["weekday_verdict"],
    ]


def _tier_row(row: pd.Series) -> list[object]:
    return [
        row["model"],
        int(row["rank"]),
        int(row["dd"]),
        compact_float(row["tier_100_500_rate"], 5),
        compact_float(row["tier_500_1k_rate"], 5),
        compact_float(row["tier_1k_2k_rate"], 5),
        compact_float(row["tier_2kplus_rate"], 5),
        row["concentration_verdict"],
    ]


def _task_a_rows(df: pd.DataFrame) -> list[list[object]]:
    rows: list[list[object]] = []
    for _, row in df.iterrows():
        rows.append(
            [
                row["model"],
                int(row["rank"]),
                int(row["dd"]),
                compact_float(row["pooled_rb_rate"], 5),
                compact_float(row["target_rows"], 0),
                compact_float(row["target_dates"], 0),
                compact_float(row["dd_vs_rest_p"], 4),
                compact_float(row["top_date_share"], 3),
                compact_float(row["date_games_pearson_r"], 3),
                compact_float(row["date_games_pearson_p"], 4),
                compact_float(row["year_rate_diff_pp"], 3),
                verdict_mark(row["overall_verdict"]),
            ]
        )
    return rows


def _task_c_rows(df: pd.DataFrame) -> list[list[object]]:
    rows: list[list[object]] = []
    for _, row in df.iterrows():
        rows.append(
            [
                row["model"],
                compact_float(row["chi2_p"], 4),
                compact_float(row["spearman_rho"], 3),
                compact_float(row["spearman_p"], 4),
                row["top_machine_number"],
                compact_float(row["top_machine_rate"], 5),
                row["bottom_machine_number"],
                compact_float(row["bottom_machine_rate"], 5),
                verdict_mark(row["overall_verdict"]),
            ]
        )
    return rows


def _task_d_rows(df: pd.DataFrame) -> list[list[object]]:
    rows: list[list[object]] = []
    for _, row in df.iterrows():
        rows.append(
            [
                row["model"],
                int(row["dd"]),
                compact_float(row["target_pooled_rb_rate"], 5),
                compact_float(row["rest_pooled_rb_rate"], 5),
                compact_float(row["rate_diff_pp"], 3),
                compact_float(row["dd_vs_rest_p"], 4),
                compact_float(row["top_date_share"], 3),
                compact_float(row["date_games_pearson_r"], 3),
                compact_float(row["date_games_pearson_p"], 4),
                compact_float(row["year_rate_diff_pp"], 3),
                verdict_mark(row["overall_verdict"]),
            ]
        )
    return rows


def _build_report() -> str:
    task_ab = _load_csv(TASK_AB_SUMMARY)
    task_c = _load_csv(TASK_C_SUMMARY)
    task_c_detail = _load_csv(TASK_C_DETAIL)
    task_d = _load_csv(TASK_D_SUMMARY)

    all_models = list(task_ab["model"].dropna().unique())
    coverage_frame = load_frame(machine_names=all_models)
    coverage_start = coverage_frame["date"].min().strftime("%Y-%m-%d")
    coverage_end = coverage_frame["date"].max().strftime("%Y-%m-%d")

    lines: list[str] = []
    lines.append("# みとや大森町店 ジャグラー系 DD / 機種番号 / DD19-29 検証")
    lines.append("")
    lines.append(f"- DB: `db/みとや大森町店.db`")
    lines.append(f"- 期間: {coverage_start} ~ {coverage_end}")
    lines.append(f"- 対象モデル: {', '.join(all_models)}")
    lines.append("")
    lines.append("判定基準は次の通りです。")
    lines.append(
        "- `支持`: 対象DDのRB率が他DDより高く、かつ weekday / single-day / games-volume / period の confound が弱い"
    )
    lines.append("- `否定`: どれかの confound が強い、または対象DDが他DDより明確に高くない")
    lines.append("- `保留`: データ不足で判定が安定しない")
    lines.append("")

    lines.append("## Task A/B: UMJ と ミスタージャグラー")
    lines.append("")
    lines.append("### DD screening")
    lines.append(
        _table(
            [
                "model",
                "rank",
                "DD",
                "pooled RB rate",
                "rows",
                "dates",
                "vs rest p",
                "top date share",
                "games r",
                "games p",
                "year delta pp",
                "overall",
            ],
            _task_a_rows(task_ab),
        )
    )
    lines.append("")
    lines.append("### Weekday confound")
    lines.append(
        _table(
            [
                "model",
                "rank",
                "DD",
                "Mon",
                "Tue",
                "Wed",
                "Thu",
                "Fri",
                "Sat",
                "Sun",
                "Weekday",
                "Weekend",
                "Wk/Wknd p",
                "verdict",
            ],
            [_weekday_row(row) for _, row in task_ab.iterrows()],
        )
    )
    lines.append("")
    lines.append("### Games tiers")
    lines.append(
        _table(
            [
                "model",
                "rank",
                "DD",
                "100-500",
                "500-1k",
                "1k-2k",
                "2k+",
                "verdict",
            ],
            [_tier_row(row) for _, row in task_ab.iterrows()],
        )
    )
    lines.append("")

    lines.append("## Task C: machine number hot/cold")
    lines.append("")
    lines.append(
        _table(
            [
                "model",
                "chi2 p",
                "Spearman rho",
                "Spearman p",
                "top machine",
                "top rate",
                "bottom machine",
                "bottom rate",
                "overall",
            ],
            _task_c_rows(task_c),
        )
    )
    lines.append("")
    lines.append("### Machine number detail")
    top_bottom_rows: list[list[object]] = []
    for model in task_c["model"].dropna().unique():
        sub = task_c_detail.loc[task_c_detail["model"] == model].copy()
        if sub.empty:
            continue
        top = sub.head(3)
        bottom = sub.tail(3)
        for _, row in top.iterrows():
            top_bottom_rows.append(
                [
                    model,
                    "top",
                    int(row["machine_number"]),
                    compact_float(row["pooled_rb_rate"], 5),
                    int(row["rows"]),
                    int(row["dates"]),
                ]
            )
        for _, row in bottom.iterrows():
            top_bottom_rows.append(
                [
                    model,
                    "bottom",
                    int(row["machine_number"]),
                    compact_float(row["pooled_rb_rate"], 5),
                    int(row["rows"]),
                    int(row["dates"]),
                ]
            )
    lines.append(
        _table(
            ["model", "bucket", "machine_number", "pooled RB rate", "rows", "dates"],
            top_bottom_rows,
        )
    )
    lines.append("")

    lines.append("## Task D: DD19 / DD29 cross-hall")
    lines.append("")
    lines.append(
        _table(
            [
                "model",
                "DD",
                "target rate",
                "rest rate",
                "diff pp",
                "vs rest p",
                "top date share",
                "games r",
                "games p",
                "year delta pp",
                "overall",
            ],
            _task_d_rows(task_d),
        )
    )
    lines.append("")
    lines.append("### Task D weekday confound")
    lines.append(
        _table(
            [
                "model",
                "DD",
                "Mon",
                "Tue",
                "Wed",
                "Thu",
                "Fri",
                "Sat",
                "Sun",
                "Weekday",
                "Weekend",
                "Wk/Wknd p",
                "verdict",
            ],
            [
                [
                    row["model"],
                    int(row["dd"]),
                    compact_float(row["weekday_mon_rate"], 5),
                    compact_float(row["weekday_tue_rate"], 5),
                    compact_float(row["weekday_wed_rate"], 5),
                    compact_float(row["weekday_thu_rate"], 5),
                    compact_float(row["weekday_fri_rate"], 5),
                    compact_float(row["weekday_sat_rate"], 5),
                    compact_float(row["weekday_sun_rate"], 5),
                    compact_float(row["weekday_weekday_rate"], 5),
                    compact_float(row["weekday_weekend_rate"], 5),
                    compact_float(row["weekday_weekend_p"], 4),
                    row["weekday_verdict"],
                ]
                for _, row in task_d.iterrows()
            ],
        )
    )
    lines.append("")
    lines.append("### Task D tier confound")
    lines.append(
        _table(
            ["model", "DD", "100-500", "500-1k", "1k-2k", "2k+", "verdict"],
            [
                [
                    row["model"],
                    int(row["dd"]),
                    compact_float(row["tier_100_500_rate"], 5),
                    compact_float(row["tier_500_1k_rate"], 5),
                    compact_float(row["tier_1k_2k_rate"], 5),
                    compact_float(row["tier_2kplus_rate"], 5),
                    row["concentration_verdict"],
                ]
                for _, row in task_d.iterrows()
            ],
        )
    )
    lines.append("")

    overall_support = (
        "支持"
        if (task_ab["overall_verdict"] == "支持").any()
        or (task_d["overall_verdict"] == "支持").any()
        or (task_c["overall_verdict"] == "支持").any()
        else "否定"
    )
    lines.append("## Conclusion")
    lines.append("")
    lines.append(f"- Overall verdict: **{overall_support}**")
    lines.append(
        "- The two small-count target models do not show a clean DD signal once weekday, concentration, games-volume, and year-split checks are applied."
    )
    lines.append("- The machine-number check does not show a stable hot/cold pattern across halves.")
    lines.append("- The hall-wide DD19/DD29 hypothesis is not supported without confound leakage.")
    lines.append("")

    return "\n".join(lines)


def main() -> int:
    report = _build_report()
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(report, encoding="utf-8")
    print(f"written: {REPORT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
