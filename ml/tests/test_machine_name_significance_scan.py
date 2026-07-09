from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest


def _make_row(date: str, machine_number: int, machine_name: str, diff: float, games: int = 1500) -> dict[str, object]:
    return {
        "date": date,
        "machine_number": machine_number,
        "machine_name": machine_name,
        "diff": diff,
        "games": games,
    }


def _make_fixed_active_frame() -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    dates = ["20260701", "20260702", "20260703"]
    for day_idx, date in enumerate(dates, start=1):
        rows.extend(
            [
                _make_row(date, 101, "A", 1000 + day_idx),
                _make_row(date, 102, "A", 990 + day_idx),
                _make_row(date, 103, "B", 980 + day_idx),
                _make_row(date, 104, "C", 970 + day_idx),
                _make_row(date, 105, "D", 960 + day_idx),
                _make_row(date, 106, "E", 950 + day_idx),
                _make_row(date, 107, "F", 940 + day_idx),
                _make_row(date, 108, "G", 930 + day_idx),
                _make_row(date, 109, "H", 920 + day_idx),
                _make_row(date, 110, "I", 910 + day_idx),
            ]
        )
    return pd.DataFrame(rows)


def _make_top3_separation_frame() -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for day_idx in range(1, 9):
        date = f"202607{day_idx:02d}"
        rows.extend(
            [
                _make_row(date, 101, "A", 500 + day_idx),
                _make_row(date, 102, "B", 400 + day_idx),
                _make_row(date, 103, "C", 300 + day_idx),
                _make_row(date, 104, "D", 200 + day_idx),
                _make_row(date, 105, "E", 100 + day_idx),
            ]
        )
    return pd.DataFrame(rows)


def _make_shindai_frame() -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for day_idx, date in enumerate(["20260701", "20260702", "20260703", "20260704"], start=1):
        rows.extend(
            [
                _make_row(date, 201, "A", 300 + day_idx),
                _make_row(date, 202, "B" if day_idx >= 3 else "A", 200 + day_idx),
                _make_row(date, 203, "C", 100 + day_idx),
            ]
        )
    return pd.DataFrame(rows)


def _make_sparse_frame() -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for day_idx in range(1, 8):
        date = f"202607{day_idx:02d}"
        for machine_idx, machine_name in enumerate(["A", "B", "C", "D", "E", "F", "G", "H"], start=1):
            rows.append(_make_row(date, 100 + machine_idx, machine_name, 1000 - machine_idx * 10 + day_idx))
    return pd.DataFrame(rows)


def _make_active_filter_frame() -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    rows.extend(
        [
            _make_row("20260701", 101, "A", 300),
            _make_row("20260701", 102, "B", 200),
            _make_row("20260701", 103, "C", 100),
        ]
    )
    rows.extend(
        [
            _make_row("20260702", 101, "A", 10),
            _make_row("20260702", 102, "B", 500),
            _make_row("20260702", 103, "C", 450),
            _make_row("20260702", 104, "D", 400),
            _make_row("20260702", 105, "E", 350),
            _make_row("20260702", 106, "F", 300),
        ]
    )
    return pd.DataFrame(rows)


def test_expected_top3_rate_uses_row_level_active_machine_count() -> None:
    from eda import machine_name_significance_scan as analysis

    frame = analysis._prepare_frame(_make_fixed_active_frame(), shindai_exclude_days=0)
    summary, _ = analysis.build_hall_outputs(
        "蒲田1", frame, shindai_exclude_days=0, min_machine_days=1, min_active_machines=6
    )

    row = summary.loc[summary["machine_name"].eq("A")].iloc[0]
    assert row["n_units"] == 2
    assert row["expected_top3_rate"] == pytest.approx(30.0)


def test_shindai_exclusion_removes_recent_debut_rows() -> None:
    from eda import machine_name_significance_scan as analysis

    raw = _make_shindai_frame()
    summary_excluded, _ = analysis.build_hall_outputs(
        "蒲田1", raw, shindai_exclude_days=30, min_machine_days=1, min_active_machines=3
    )
    summary_all, _ = analysis.build_hall_outputs(
        "蒲田1", raw, shindai_exclude_days=0, min_machine_days=1, min_active_machines=3
    )

    assert "B" not in set(summary_excluded["machine_name"])
    assert "B" in set(summary_all["machine_name"])


def test_top3_lift_separates_favored_and_disfavored_machines() -> None:
    from eda import machine_name_significance_scan as analysis

    summary, _ = analysis.build_hall_outputs(
        "蒲田1", _make_top3_separation_frame(), shindai_exclude_days=0, min_machine_days=1, min_active_machines=3
    )

    top_machine = summary.loc[summary["machine_name"].eq("A")].iloc[0]
    bottom_machine = summary.loc[summary["machine_name"].eq("E")].iloc[0]

    assert top_machine["top3_lift"] > 1.0
    assert bottom_machine["top3_lift"] < 1.0
    assert bottom_machine["bottom3_lift"] > 1.0


def test_min_active_machines_filters_summary_and_significance_rows() -> None:
    from eda import machine_name_significance_scan as analysis

    raw = _make_active_filter_frame()
    unfiltered_summary, unfiltered_significance = analysis.build_hall_outputs(
        "蒲田1",
        raw,
        shindai_exclude_days=0,
        min_machine_days=1,
        min_active_machines=0,
    )
    filtered_summary, filtered_significance = analysis.build_hall_outputs(
        "蒲田1",
        raw,
        shindai_exclude_days=0,
        min_machine_days=1,
        min_active_machines=6,
    )

    unfiltered_a = unfiltered_summary.loc[unfiltered_summary["machine_name"].eq("A")].iloc[0]
    filtered_a = filtered_summary.loc[filtered_summary["machine_name"].eq("A")].iloc[0]

    assert unfiltered_a["n_machine_days"] == 2
    assert unfiltered_a["top3_rate"] == pytest.approx(50.0)
    assert filtered_a["n_machine_days"] == 1
    assert filtered_a["top3_rate"] == pytest.approx(0.0)

    unfiltered_top3 = unfiltered_significance.loc[unfiltered_significance["metric"].eq("top3_selection")].iloc[0]
    filtered_top3 = filtered_significance.loc[filtered_significance["metric"].eq("top3_selection")].iloc[0]
    assert unfiltered_top3["n_obs"] == 9
    assert filtered_top3["n_obs"] == 6


def test_kruskal_and_sparse_chi2_paths_emit_expected_effect_sizes_and_notes() -> None:
    from eda import machine_name_significance_scan as analysis

    frame = analysis._prepare_frame(_make_sparse_frame(), shindai_exclude_days=0)

    hit_summary = analysis._kruskal_summary(
        frame,
        hall="蒲田1",
        metric="hit104_rate",
        value_col="hit104",
        min_machine_days=1,
    )
    assert hit_summary["test"] == "kruskal"
    assert hit_summary["effect_size"] >= 0
    assert hit_summary["n_groups"] >= 2

    with pytest.warns(RuntimeWarning):
        chi2_summary = analysis._chi2_summary(
            frame,
            hall="蒲田1",
            metric="top3_selection",
            flag_col="top3_flag",
            min_machine_days=1,
            min_active_machines=6,
        )
    assert chi2_summary["test"] == "chi2"
    assert chi2_summary["effect_size"] >= 0
    assert str(chi2_summary["note"]).startswith("warning:")


def test_main_writes_two_csvs_for_single_hall(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from eda import machine_name_significance_scan as analysis

    monkeypatch.setattr(analysis, "HALL_DBS", {"蒲田1": "fake.db"})
    monkeypatch.setattr(analysis, "load_hall_df", lambda hall: _make_top3_separation_frame())

    exit_code = analysis.main(
        [
            "--halls",
            "蒲田1",
            "--output-dir",
            str(tmp_path),
            "--shindai-exclude-days",
            "0",
            "--min-machine-days",
            "1",
            "--min-active-machines",
            "3",
        ]
    )

    assert exit_code == 0
    assert (tmp_path / "蒲田1_machine_summary.csv").exists()
    assert (tmp_path / "significance_summary.csv").exists()
