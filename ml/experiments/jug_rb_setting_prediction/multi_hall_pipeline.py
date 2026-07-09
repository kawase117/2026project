from __future__ import annotations

import argparse
import sqlite3
import sys
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[3]

if __package__ in {None, ""}:
    sys.path.insert(0, str(PROJECT_ROOT))
    from ml.experiments.jug_rb_setting_prediction import (  # noqa: E402
        stage1_machine_catalog as stage1,
        stage2_daily_posterior as stage2,
        stage3_features as stage3,
        stage4_real_money as stage4_money,
        stage4_walkforward as stage4_walkforward,
        stage5_alloc_eda as stage5_alloc,
        stage5_shrinkage_bias_check as stage5_bias,
        stage5_rank_daily as stage5_rank,
    )
else:  # pragma: no cover - exercised via package imports in tests
    from . import (  # noqa: E402
        stage1_machine_catalog as stage1,
        stage2_daily_posterior as stage2,
        stage3_features as stage3,
        stage4_real_money as stage4_money,
        stage4_walkforward as stage4_walkforward,
        stage5_alloc_eda as stage5_alloc,
        stage5_shrinkage_bias_check as stage5_bias,
        stage5_rank_daily as stage5_rank,
    )

OUTPUT_ROOT = PROJECT_ROOT / "ml" / "experiments" / "results" / "jug_rb_setting_prediction"
MULTI_HALL_DIR = OUTPUT_ROOT / "multi_hall"


@dataclass(frozen=True)
class HallSpec:
    hall: str
    hall_slug: str
    db_path: Path


HALL_SPECS: tuple[HallSpec, ...] = (
    HallSpec("kamata7", "kamata7", PROJECT_ROOT / "db" / "マルハンメガシティ2000-蒲田7.db"),
    HallSpec("kamata1", "kamata1", PROJECT_ROOT / "db" / "マルハンメガシティ2000-蒲田1.db"),
    HallSpec("arrow", "arrow", PROJECT_ROOT / "db" / "ARROW池上店.db"),
    HallSpec("lategap", "lategap", PROJECT_ROOT / "db" / "レイトギャップ平和島.db"),
    HallSpec("mitoya", "mitoya", PROJECT_ROOT / "db" / "みとや大森町店.db"),
    HallSpec("rakuen", "rakuen", PROJECT_ROOT / "db" / "楽園蒲田店.db"),
    HallSpec("hiroki", "hiroki", PROJECT_ROOT / "db" / "ヒロキ東口店.db"),
    HallSpec("zashiti", "zashiti", PROJECT_ROOT / "db" / "ザ-シティ-ベルシティ雑色店.db"),
    HallSpec("kintoki", "kintoki", PROJECT_ROOT / "db" / "金時京急蒲田店.db"),
)


def _ensure_utf8_stdout() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")


def _load_layout_frame(db_path: Path) -> pd.DataFrame:
    if not db_path.exists():
        raise FileNotFoundError(db_path)
    with sqlite3.connect(str(db_path)) as conn:
        layout = pd.read_sql_query(
            """
            SELECT
                machine_number,
                x,
                section,
                section_min,
                section_max,
                rank_from_min,
                rank_from_max
            FROM machine_layout
            """,
            conn,
        )
    required = ["machine_number", "x", "section", "section_min", "section_max", "rank_from_min", "rank_from_max"]
    missing = [column for column in required if column not in layout.columns]
    if missing:
        raise ValueError(f"machine_layout is missing required columns: {missing}")

    for column in ("machine_number", "x", "section_min", "section_max", "rank_from_min", "rank_from_max"):
        layout[column] = pd.to_numeric(layout[column], errors="coerce")
    layout["section"] = layout["section"].astype(str)
    layout = layout.dropna(
        subset=["machine_number", "x", "section_min", "section_max", "rank_from_min", "rank_from_max"]
    ).copy()
    layout["machine_number"] = layout["machine_number"].astype(int)
    layout["kakuban_rank_min"] = layout["rank_from_min"].astype(int)
    layout["kakuban_rank_max"] = layout["rank_from_max"].astype(int)
    layout["section_size"] = (layout["section_max"] - layout["section_min"] + 1).astype(int)
    layout["is_corner1"] = layout[["rank_from_min", "rank_from_max"]].eq(1).any(axis=1).astype(int)
    section_medians = layout.groupby("section", dropna=False)["x"].transform("median")
    layout["side_lr"] = layout["x"].lt(section_medians).map({True: "L", False: "R"})
    return layout.loc[
        :,
        ["machine_number", "section", "kakuban_rank_min", "kakuban_rank_max", "section_size", "is_corner1", "side_lr"],
    ].copy()


def _weighted_group_mean(table: pd.DataFrame, *, group_col: str, value_col: str = "mean_pct_family") -> pd.DataFrame:
    if table.empty:
        return pd.DataFrame(columns=[group_col, "weighted_mean"])
    work = table.copy()
    work["n_rows"] = pd.to_numeric(work["n_rows"], errors="coerce")
    work[value_col] = pd.to_numeric(work[value_col], errors="coerce")
    work = work.dropna(subset=["n_rows", value_col]).copy()
    rows: list[dict[str, object]] = []
    for key, group in work.groupby(group_col, sort=True, dropna=False):
        weight = float(group["n_rows"].sum())
        weighted_mean = float((group[value_col] * group["n_rows"]).sum() / weight) if weight > 0 else float("nan")
        rows.append({group_col: key, "weighted_mean": weighted_mean, "weight": weight})
    return pd.DataFrame(rows)


def _alloc_hall_metrics(output_dir: Path) -> dict[str, float]:
    weekday_table = pd.read_csv(output_dir / "stage5_alloc_machine_weekday.csv", encoding="utf-8-sig")
    event_table = pd.read_csv(output_dir / "stage5_alloc_section_event_day.csv", encoding="utf-8-sig")
    kakuban_table = pd.read_csv(output_dir / "stage5_alloc_kakuban_rank_min_section_size.csv", encoding="utf-8-sig")
    family_gap_table = pd.read_csv(output_dir / "stage5_alloc_family_gap.csv", encoding="utf-8-sig")

    weekday_summary = _weighted_group_mean(weekday_table, group_col="weekday")
    event_summary = _weighted_group_mean(event_table, group_col="is_event_day")
    kakuban_summary = _weighted_group_mean(kakuban_table, group_col="kakuban_rank_min")
    family_gap_table["mean_pct_gap"] = pd.to_numeric(family_gap_table["mean_pct_gap"], errors="coerce")

    weekday_gap = (
        float(weekday_summary["weighted_mean"].max() - weekday_summary["weighted_mean"].min())
        if not weekday_summary.empty
        else float("nan")
    )
    event_gap = (
        float(event_summary["weighted_mean"].max() - event_summary["weighted_mean"].min())
        if len(event_summary) >= 2
        else float("nan")
    )
    kakuban1 = kakuban_summary.loc[kakuban_summary["kakuban_rank_min"].eq(1), "weighted_mean"]
    kakuban1_mean = float(kakuban1.iloc[0]) if not kakuban1.empty else float("nan")
    family_gap_mean = float(family_gap_table["mean_pct_gap"].mean()) if not family_gap_table.empty else float("nan")

    return {
        "alloc_weekday_gap": weekday_gap,
        "alloc_event_gap": event_gap,
        "alloc_kakuban1_mean": kakuban1_mean,
        "alloc_family_gap_mean": family_gap_mean,
    }


def _prepare_stage5_rank_frame(stage2_frame: pd.DataFrame, *, hall: str) -> pd.DataFrame:
    work = stage2_frame.copy()
    work["date"] = work["date"].astype(str)
    work["date_dt"] = pd.to_datetime(work["date"], format="%Y%m%d", errors="coerce")
    work["machine_number"] = pd.to_numeric(work["machine_number"], errors="coerce")
    work["machine_name"] = work["machine_name"].astype(str)
    for column in ("G", "rb", "bb", "p_high", "e_setting", "e_payout"):
        work[column] = pd.to_numeric(work[column], errors="coerce")
    work = work.dropna(subset=["date_dt", "machine_number", "machine_name", "G", "rb", "bb", "p_high"]).copy()
    work["machine_number"] = work["machine_number"].astype(int)
    work["hall"] = hall
    work = work.sort_values(["date_dt", "machine_number", "machine_name"], kind="mergesort").reset_index(drop=True)
    return work


def run_hall_pipeline(spec: HallSpec) -> dict[str, object]:
    output_dir = OUTPUT_ROOT / spec.hall_slug
    output_dir.mkdir(parents=True, exist_ok=True)

    stage1_outputs = stage1.build_stage1_outputs(db_path=spec.db_path, hall=spec.hall)
    stage1.save_stage1_outputs(stage1_outputs, output_dir)

    stage2_outputs = stage2.build_stage2_outputs(db_path=spec.db_path, hall=spec.hall, prior_mode="empirical")
    stage2.save_stage2_outputs(stage2_outputs, output_dir)

    layout_frame = _load_layout_frame(spec.db_path)
    stage2_frame = stage2_outputs["daily_posterior"]
    assert isinstance(stage2_frame, pd.DataFrame)
    stage3_features = stage3.build_stage3_features(stage2_frame, hall=spec.hall, layout_frame=layout_frame)
    stage3.save_stage3_features(stage3_features, output_dir)

    stage4_walk_outputs = stage4_walkforward.build_stage4_outputs(frame=stage3_features, hall=spec.hall)
    stage4_walkforward.save_stage4_outputs(stage4_walk_outputs, output_dir)

    stage5_stage2_frame = stage2_frame.copy()
    try:
        prepared_stage5, counts = stage5_rank._prepare_stage2_frame(stage5_stage2_frame, hall=spec.hall)  # type: ignore[attr-defined]
        rank_daily = stage5_rank.build_stage5_rank_daily(prepared_stage5, hall=spec.hall, layout_frame=layout_frame)
    except Exception:
        counts = {
            "raw_rows": int(len(stage5_stage2_frame)),
            "non_juggler_rows": 0,
            "unknown_family_rows": 0,
            "unmatched_layout_rows": 0,
        }
        prepared_stage5 = _prepare_stage5_rank_frame(stage5_stage2_frame, hall=spec.hall)
        rank_daily = stage5_rank.build_stage5_rank_daily(prepared_stage5, hall=spec.hall, layout_frame=layout_frame)
    report = stage5_rank._build_report(  # type: ignore[attr-defined]
        hall=spec.hall,
        output_csv=output_dir / "stage5_rank_daily.csv",
        source_stage2=output_dir / "stage2_daily_posterior.csv",
        db_path=spec.db_path,
        frame=rank_daily,
        counts=counts,
    )
    stage5_rank.save_stage5_outputs({"rank_daily": rank_daily, "report": report}, output_dir)

    stage5_alloc_outputs = stage5_alloc.build_stage5_alloc_outputs(
        hall=spec.hall,
        stage3_csv=output_dir / "stage3_features.csv",
        stage5_csv=output_dir / "stage5_rank_daily.csv",
        output_dir=output_dir,
    )
    stage5_alloc.save_stage5_alloc_outputs(stage5_alloc_outputs, output_dir)

    stage4_money_outputs = stage4_money.build_stage4_real_money_outputs(
        hall=spec.hall,
        db_path=spec.db_path,
        stage3_csv=output_dir / "stage3_features.csv",
        stage5_csv=output_dir / "stage5_rank_daily.csv",
        output_dir=output_dir,
    )
    stage4_money.save_stage4_real_money_outputs(stage4_money_outputs, output_dir)

    if spec.hall == "mitoya":
        bias_outputs = stage5_bias.build_stage5_shrinkage_bias_check_outputs(
            hall=spec.hall,
            db_path=spec.db_path,
            stage3_csv=output_dir / "stage3_features.csv",
            stage5_csv=output_dir / "stage5_rank_daily.csv",
            output_dir=output_dir,
        )
        stage5_bias.save_stage5_shrinkage_bias_check_outputs(bias_outputs, output_dir)

    summary = stage4_money_outputs["summary"]
    bootstrap_json = stage4_money_outputs["bootstrap_json"]
    alloc_metrics = _alloc_hall_metrics(output_dir)
    assert isinstance(summary, pd.DataFrame)
    assert isinstance(bootstrap_json, dict)

    b1r_row = summary.loc[summary["method"].eq("B1R")].iloc[0]
    comparison = bootstrap_json["comparisons"]["B1R_minus_B0"]
    machine_catalog = stage1_outputs["machine_catalog"]
    assert isinstance(machine_catalog, pd.DataFrame)

    return {
        "hall": spec.hall,
        "hall_slug": spec.hall_slug,
        "db_path": str(spec.db_path),
        "n_stage1_catalog": int(len(machine_catalog)),
        "n_stage1_unknown": int(
            pd.to_numeric(machine_catalog["is_unknown_family"], errors="coerce").fillna(False).sum()
        ),
        "n_stage2_rows": int(len(stage2_frame)),
        "n_stage3_rows": int(len(stage3_features)),
        "n_eval_days": int(b1r_row["n_eval_days"]),
        "B1R_minus_B0_mean": float(comparison["mean"]),
        "ci_lower": float(comparison["ci_lower"]),
        "ci_upper": float(comparison["ci_upper"]),
        "verdict": "positive"
        if float(comparison["ci_lower"]) > 0
        else ("negative" if float(comparison["ci_upper"]) < 0 else "neutral"),
        **alloc_metrics,
    }


def build_multi_hall_summary(rows: list[dict[str, object]]) -> pd.DataFrame:
    frame = pd.DataFrame(rows)
    if frame.empty:
        return frame
    order = [
        "hall",
        "hall_slug",
        "db_path",
        "n_stage1_catalog",
        "n_stage1_unknown",
        "n_stage2_rows",
        "n_stage3_rows",
        "n_eval_days",
        "B1R_minus_B0_mean",
        "ci_lower",
        "ci_upper",
        "verdict",
        "alloc_weekday_gap",
        "alloc_event_gap",
        "alloc_kakuban1_mean",
        "alloc_family_gap_mean",
    ]
    return frame.loc[:, order].copy()


def render_summary_markdown(summary: pd.DataFrame) -> str:
    if summary.empty:
        return "# Multi Hall Summary\n\n_no rows_\n"

    def _format_cell(value: object) -> str:
        if pd.isna(value):
            return "N/A"
        return str(value)

    header = "| " + " | ".join(summary.columns) + " |"
    separator = "| " + " | ".join(["---"] * len(summary.columns)) + " |"
    rows = [
        "| " + " | ".join(_format_cell(value) for value in row) + " |"
        for row in summary.itertuples(index=False, name=None)
    ]
    lines = [
        "# Multi Hall Summary",
        "",
        "\n".join([header, separator, *rows]),
        "",
        "## Notes",
        "",
        "- `verdict` is based on the B1R-minus-B0 bootstrap CI.",
        "- Allocation metrics are descriptive and come from stage5_alloc outputs.",
        "- `N/A` means the hall has no `machine_layout` coverage, so section/kakuban allocation metrics are intentionally omitted.",
    ]
    return "\n".join(lines).rstrip() + "\n"


def main(argv: list[str] | None = None) -> int:
    _ensure_utf8_stdout()
    parser = argparse.ArgumentParser(description="Run the juggler RB pipeline across the multi-hall expansion set")
    parser.add_argument("--output-root", type=Path, default=MULTI_HALL_DIR)
    parser.add_argument(
        "--hall", action="append", choices=[spec.hall for spec in HALL_SPECS], help="Run only selected hall(s)"
    )
    args = parser.parse_args(argv)

    specs = [spec for spec in HALL_SPECS if args.hall is None or spec.hall in args.hall]
    rows = [run_hall_pipeline(spec) for spec in specs]
    summary = build_multi_hall_summary(rows)

    args.output_root.mkdir(parents=True, exist_ok=True)
    summary.to_csv(args.output_root / "multi_hall_summary.csv", index=False, encoding="utf-8-sig")
    (args.output_root / "multi_hall_summary.md").write_text(render_summary_markdown(summary), encoding="utf-8")
    print(args.output_root / "multi_hall_summary.csv")
    print(args.output_root / "multi_hall_summary.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
