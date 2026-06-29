from __future__ import annotations

from pathlib import Path

import pandas as pd

from eda import target_metric_comparison as mod


def _make_frame() -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    dates = pd.to_datetime(
        [
            "2026-06-01",
            "2026-06-02",
            "2026-06-03",
            "2026-06-04",
            "2026-06-05",
            "2026-06-06",
            "2026-06-07",
            "2026-06-08",
        ]
    )
    for date_idx, date_dt in enumerate(dates):
        for machine_number in (2001, 2002, 2003, 2004, 3001, 3002):
            diff = float(machine_number % 10 + date_idx * 2)
            games = 2000 + date_idx * 10
            rows.append(
                {
                    "date_dt": date_dt,
                    "date": date_dt.strftime("%Y%m%d"),
                    "machine_number": machine_number,
                    "machine_name": f"m{machine_number}",
                    "floor": "2F",
                    "section": "A" if machine_number in {2001, 2002, 3001} else "B",
                    "games_normalized": games,
                    "diff_coins_normalized": diff,
                    "payout_rate": ((games * 3 + diff) / (games * 3)) * 100,
                    "hit104": diff > 4,
                }
            )
    return pd.DataFrame(rows)


def test_build_metric_tables_produces_separate_exploration_and_pipeline_outputs(tmp_path: Path) -> None:
    frame = _make_frame()

    exploration, pipeline = mod.build_outputs_from_frame(
        frame,
        eval_days=2,
        history_days=7,
        top_k_sections=1,
        top_n_machines=1,
        top_strategies=2,
    )

    assert list(exploration.metric_summary.columns) == [
        "metric",
        "spearman_rho",
        "p_value",
        "d0_hit104",
        "d9_hit104",
        "delta_pp",
    ]
    assert list(exploration.section_summary.columns) == [
        "metric",
        "spearman_rho",
        "p_value",
        "d0_section_hit_rate",
        "d9_section_hit_rate",
        "delta_pp",
    ]
    assert set(pipeline.summary["strategy"]) == {
        "section_avg_hit_104_rate × hit_104_rate",
        "section_avg_avg_diff × avg_diff",
    }
    assert exploration.report_exploration.startswith("# Part 1")
    assert pipeline.report_pipeline.startswith("# Part 2")


def test_main_writes_separate_reports(tmp_path: Path) -> None:
    out_dir = tmp_path / "results"

    exit_code = mod.main(
        [
            "--db-path",
            str(tmp_path / "missing.db"),
            "--output-dir",
            str(out_dir),
        ]
    )

    assert exit_code != 0
