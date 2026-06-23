from __future__ import annotations

from pathlib import Path

import pandas as pd

from eda import kamata7_pair_corr_by_segment as paircorr


def _make_base_df() -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    dates = ["20260501", "20260502", "20260503"]
    machine_specs = [
        (101, "A機ジャグラー", 0, "2F", "L"),
        (102, "N機海", 1, "2F", "L"),
        (201, "N機海", 2, "2F", "R"),
        (202, "A機ジャグラー", 3, "3F", "L"),
        (301, "N機海", 4, "3F", "L"),
        (302, "N機海", 5, "3F", "R"),
        (303, "A機ジャグラー", 6, "3F", "R"),
    ]
    for day_idx, date in enumerate(dates):
        dd = int(date[6:8])
        for machine_number, machine_name, digit, floor, side in machine_specs:
            rows.append(
                {
                    "date": date,
                    "machine_name": machine_name,
                    "machine_number": machine_number,
                    "machine_digit": str(digit),
                    "diff": day_idx * 10 + digit,
                    "games": 1200,
                    "dd": dd,
                    "dd_mod10": dd % 10,
                    "day_of_week": "金",
                    "floor": floor,
                    "side": side,
                }
            )
    return pd.DataFrame(rows)


def test_build_segment_key_uses_floor_side_and_type() -> None:
    df = _make_base_df()
    seg_df = paircorr.build_segment_frame(df)

    keys = sorted(seg_df["group_key"].unique().tolist())

    assert "2F_L_N" in keys
    assert "2F_R_N" in keys
    assert "3F_L_A" in keys
    assert "3F_L_N" in keys
    assert "3F_R_A" in keys
    assert "3F_R_N" in keys


def test_build_corr_matrix_returns_10x10_matrix() -> None:
    df = _make_base_df()
    seg_df = paircorr.build_segment_frame(df)
    target = seg_df[seg_df["group_key"] == "2F_L_N"].copy()
    daily = paircorr.build_daily_digit_matrix(target)

    matrix, pairs, test = paircorr.build_corr_matrix(daily)

    assert matrix.shape == (10, 10)
    assert list(matrix.index) == list(range(10))
    assert list(matrix.columns) == list(range(10))
    assert matrix.loc[0, 0] == 1.0
    assert len(pairs) == 45
    assert "p_value" in test.index


def test_is_adjacent_pair_handles_wraparound() -> None:
    assert paircorr.is_adjacent_pair(0, 1) is True
    assert paircorr.is_adjacent_pair(8, 9) is True
    assert paircorr.is_adjacent_pair(0, 9) is True
    assert paircorr.is_adjacent_pair(3, 5) is False


def test_empty_segment_returns_nan_results() -> None:
    empty = pd.DataFrame(columns=["date", "machine_name", "machine_number", "machine_digit", "diff", "games", "dd", "dd_mod10", "day_of_week"])

    outputs = paircorr.analyze_segment(empty, "2F_L_A")

    assert outputs.segment == "2F_L_A"
    assert pd.isna(outputs.pair_test["p_value"])
    assert outputs.pairs.empty


def test_write_outputs_creates_report_and_csvs(tmp_path: Path, monkeypatch: object) -> None:
    df = _make_base_df()
    seg_df = paircorr.build_segment_frame(df)
    analysis = paircorr.build_outputs(seg_df)

    report_path = tmp_path / "report.md"
    summary_path = tmp_path / "summary.csv"
    top_pairs_path = tmp_path / "top_pairs.csv"

    monkeypatch.setattr(paircorr, "REPORT_PATH", report_path)
    monkeypatch.setattr(paircorr, "SUMMARY_CSV_PATH", summary_path)
    monkeypatch.setattr(paircorr, "TOP_PAIRS_CSV_PATH", top_pairs_path)

    paircorr.write_outputs(analysis)

    assert report_path.exists()
    assert summary_path.exists()
    assert top_pairs_path.exists()
    assert summary_path.read_bytes().startswith(b"\xef\xbb\xbf")
    assert top_pairs_path.read_bytes().startswith(b"\xef\xbb\xbf")
