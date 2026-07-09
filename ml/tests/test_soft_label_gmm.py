from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest


def _row(
    date: str,
    machine_number: int,
    machine_name: str,
    games: int,
    diff: int,
) -> dict[str, object]:
    return {
        "date": date,
        "machine_number": machine_number,
        "machine_name": machine_name,
        "games": games,
        "diff": diff,
    }


def _make_separated_frame() -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for idx in range(6):
        rows.append(_row(f"202607{idx + 1:02d}", 101, "A", 3000, -300))
    for idx in range(6):
        rows.append(_row(f"202607{idx + 7:02d}", 101, "A", 3000, 900))
    for idx in range(3):
        rows.append(_row(f"202607{idx + 1:02d}", 202, "B", 3000, -300))
    for idx in range(3):
        rows.append(_row(f"202607{idx + 4:02d}", 202, "B", 3000, -240))
    return pd.DataFrame(rows)


def _make_sparse_frame() -> pd.DataFrame:
    return pd.DataFrame(
        [
            _row("20260701", 301, "C", 1000, -100),
            _row("20260702", 301, "C", 1000, -80),
            _row("20260703", 301, "C", 1000, -60),
        ]
    )


def _make_sparse_fit_frame() -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for idx in range(6):
        rows.append(_row(f"202607{idx + 1:02d}", 601, "F", 1000, -90))
    rows.append(_row("20260707", 601, "F", 3000, -120))
    rows.append(_row("20260708", 601, "F", 3000, 180))
    rows.append(_row("20260709", 601, "F", 3000, 420))
    return pd.DataFrame(rows)


def _make_low_games_frame() -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for idx in range(6):
        rows.append(_row(f"202607{idx + 1:02d}", 401, "D", 3000, -120))
    rows.append(_row("20260707", 401, "D", 1000, 420))
    return pd.DataFrame(rows)


def _make_main_frame() -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for idx in range(6):
        rows.append(_row(f"202607{idx + 1:02d}", 501, "E", 1000, -90))
    for idx in range(6):
        rows.append(_row(f"202607{idx + 7:02d}", 501, "E", 1000, 300))
    return pd.DataFrame(rows)


def test_machine_fit_subset_excludes_low_games() -> None:
    from ml.experiments.label_redesign import soft_label_gmm as analysis

    frame = _make_low_games_frame()
    subset = analysis._machine_fit_subset(frame, min_games_for_gmm_fit=2000)

    assert subset["games"].tolist() == [3000, 3000, 3000, 3000, 3000, 3000]


def test_build_hall_outputs_scores_high_group_above_half_and_tracks_variance() -> None:
    from ml.experiments.label_redesign import soft_label_gmm as analysis

    soft_frame, cell_frame, summary = analysis.build_hall_outputs(
        "蒲田7",
        _make_separated_frame(),
        shindai_exclude_days=0,
        min_games_for_gmm_fit=2000,
        min_machine_days_for_gmm=4,
    )

    high_rows = soft_frame.loc[soft_frame["diff"].eq(900)]
    low_rows = soft_frame.loc[soft_frame["diff"].eq(-300)]

    assert high_rows["p_high_setting"].min() > 0.5
    assert low_rows["p_high_setting"].max() < 0.5
    assert set(
        ["hall", "dd", "machine_digit", "n_days", "var_hit104", "var_p_high_setting", "variance_reduced"]
    ).issubset(cell_frame.columns)
    assert summary["pearson_r"] > 0.0
    assert summary["spearman_r"] > 0.0


def test_short_machine_group_is_skipped_with_note() -> None:
    from ml.experiments.label_redesign import soft_label_gmm as analysis

    soft_frame, cell_frame, summary = analysis.build_hall_outputs(
        "蒲田7",
        _make_sparse_frame(),
        shindai_exclude_days=0,
        min_games_for_gmm_fit=2000,
        min_machine_days_for_gmm=5,
    )

    assert soft_frame["gmm_fit_used"].eq(False).all()
    assert soft_frame["p_high_setting"].isna().all()
    assert soft_frame["note"].str.contains("skipped", case=False).all()
    assert cell_frame["variance_reduced"].eq(False).all()
    assert summary["pearson_r"] is None
    assert summary["spearman_r"] is None


def test_machine_group_is_skipped_when_fit_rows_are_below_threshold() -> None:
    from ml.experiments.label_redesign import soft_label_gmm as analysis

    soft_frame, _, _ = analysis.build_hall_outputs(
        "蒲田7",
        _make_sparse_fit_frame(),
        shindai_exclude_days=0,
        min_games_for_gmm_fit=2000,
        min_machine_days_for_gmm=4,
    )

    assert soft_frame["gmm_fit_used"].eq(False).all()
    assert soft_frame["p_high_setting"].isna().all()
    assert soft_frame["note"].str.contains("fit rows 3 < 4", case=False).any()


def test_main_writes_expected_csvs_for_single_hall(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from ml.experiments.label_redesign import soft_label_gmm as analysis

    monkeypatch.setattr(analysis, "HALL_DBS", {"蒲田7": "fake.db"})
    monkeypatch.setattr(analysis, "load_hall_df", lambda hall: _make_main_frame())

    exit_code = analysis.main(
        [
            "--halls",
            "蒲田7",
            "--output-dir",
            str(tmp_path),
            "--min-games-for-gmm-fit",
            "2000",
            "--min-machine-days-for-gmm",
            "4",
            "--shindai-exclude-days",
            "0",
        ]
    )

    assert exit_code == 0
    assert (tmp_path / "蒲田7_soft_label_comparison.csv").exists()
    assert (tmp_path / "蒲田7_cell_variance_comparison.csv").exists()
