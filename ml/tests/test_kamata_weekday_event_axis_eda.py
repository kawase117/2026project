from __future__ import annotations

import pandas as pd

from ml.analysis.kamata_weekday_event_axis_eda import (
    apply_min_date_filter,
    build_segment_key,
    classify_tail_axis,
    _build_kakuban_axis,
    is_kamata_event_day,
    _build_weekday_reproducibility_summary,
    _split_frame_by_date_half,
)


def test_is_kamata_event_day_marks_month_end_and_explicit_event_days() -> None:
    assert is_kamata_event_day(pd.Timestamp("2026-06-01")) is True
    assert is_kamata_event_day(pd.Timestamp("2026-06-07")) is True
    assert is_kamata_event_day(pd.Timestamp("2026-06-11")) is True
    assert is_kamata_event_day(pd.Timestamp("2026-06-17")) is True
    assert is_kamata_event_day(pd.Timestamp("2026-06-21")) is True
    assert is_kamata_event_day(pd.Timestamp("2026-06-27")) is True
    assert is_kamata_event_day(pd.Timestamp("2026-06-30")) is True
    assert is_kamata_event_day(pd.Timestamp("2026-02-28")) is True
    assert is_kamata_event_day(pd.Timestamp("2026-06-02")) is False


def test_build_segment_key_separates_hall_floor_and_atype() -> None:
    assert build_segment_key(hall_slug="kamata1", floor="2F", is_a_type=True) == "kamata1_2F_A"
    assert build_segment_key(hall_slug="kamata1", floor="2F", is_a_type=False) == "kamata1_2F_N"
    assert build_segment_key(hall_slug="kamata7", floor="3F", is_a_type=True) == "kamata7_3F_A"


def test_classify_tail_axis_labels_zorome_separately() -> None:
    assert classify_tail_axis(machine_number=100, is_zorome=1) == "ゾロ目"
    assert classify_tail_axis(machine_number=101, is_zorome=0) == "1"
    assert classify_tail_axis(machine_number=110, is_zorome=0) == "0"


def test_apply_min_date_filter_drops_sparse_cells() -> None:
    frame = pd.DataFrame(
        {
            "axis_value": ["a", "a", "b", "b", "c", "c"],
            "subgroup": [0, 0, 0, 0, 0, 0],
            "date": pd.to_datetime(
                [
                    "2026-06-01",
                    "2026-06-02",
                    "2026-06-01",
                    "2026-06-02",
                    "2026-06-01",
                    "2026-06-01",
                ]
            ),
            "mean_diff": [1, 2, 3, 4, 5, 6],
        }
    )

    filtered = apply_min_date_filter(frame, axis_col="axis_value", subgroup_col="subgroup", min_dates=2)

    assert filtered["axis_value"].tolist() == ["a", "a", "b", "b"]


def test_split_frame_by_date_half_keeps_chronological_halves() -> None:
    frame = pd.DataFrame(
        {
            "date": pd.to_datetime(
                [
                    "2026-06-01",
                    "2026-06-02",
                    "2026-06-03",
                    "2026-06-04",
                    "2026-06-05",
                ]
            ),
            "axis": ["x"] * 5,
        }
    )

    first_half, second_half, cutoff = _split_frame_by_date_half(frame)

    assert first_half["date"].dt.strftime("%Y-%m-%d").tolist() == ["2026-06-01", "2026-06-02"]
    assert second_half["date"].dt.strftime("%Y-%m-%d").tolist() == ["2026-06-03", "2026-06-04", "2026-06-05"]
    assert str(cutoff.date()) == "2026-06-02"


def test_build_weekday_reproducibility_summary_marks_half_periods(monkeypatch) -> None:
    segment_frame = pd.DataFrame(
        {
            "date": pd.to_datetime(
                [
                    "2026-06-01",
                    "2026-06-02",
                    "2026-06-03",
                    "2026-06-04",
                ]
            ),
            "weekday": [0, 1, 2, 3],
            "is_event_day": [0, 0, 0, 0],
            "mean_diff": [10, 20, 30, 40],
            "win_flag": [1, 0, 1, 0],
            "mean_games": [100, 100, 100, 100],
            "n_machines": [1, 1, 1, 1],
            "axis_value": ["A", "A", "A", "A"],
        }
    )
    segment_frame["axis_value"] = segment_frame["axis_value"].astype(str)

    compare_targets = pd.DataFrame(
        {
            "axis_value": ["A"],
            "judgement": ["without_event_stronger"],
            "kruskal_q_with_event": [0.2],
            "kruskal_q_without_event": [0.01],
            "weekday_spread_with_event": [1.0],
            "weekday_spread_without_event": [2.0],
        }
    )

    def fake_compare_row(frame, *, axis_col, axis_value):
        dates = frame["date"].dt.strftime("%Y-%m-%d").tolist()
        if not dates:
            return None
        if dates[-1] <= "2026-06-02":
            return {
                "judgement": "without_event_stronger",
                "kruskal_q_with_event": 0.4,
                "kruskal_q_without_event": 0.01,
                "weekday_spread_with_event": 1.5,
                "weekday_spread_without_event": 2.5,
                "n_dates": len(dates),
                "period_start": pd.Timestamp(dates[0]),
                "period_end": pd.Timestamp(dates[-1]),
            }
        return {
            "judgement": "with_event_stronger",
            "kruskal_q_with_event": 0.02,
            "kruskal_q_without_event": 0.5,
            "weekday_spread_with_event": 3.5,
            "weekday_spread_without_event": 1.0,
            "n_dates": len(dates),
            "period_start": pd.Timestamp(dates[0]),
            "period_end": pd.Timestamp(dates[-1]),
        }

    monkeypatch.setattr("ml.analysis.kamata_weekday_event_axis_eda._build_weekday_compare_row", fake_compare_row)

    summary = _build_weekday_reproducibility_summary(
        segment_frame=segment_frame,
        axis_col="axis_value",
        compare_targets=compare_targets,
    )

    assert summary.loc[0, "axis_value"] == "A"
    assert summary.loc[0, "first_half_judgement"] == "without_event_stronger"
    assert summary.loc[0, "second_half_judgement"] == "with_event_stronger"
    assert not bool(summary.loc[0, "same_judgement_both_halves"])
    assert summary.loc[0, "repro_status"] == "mixed"


def test_build_kakuban_axis_uses_unique_machines_not_daily_rows() -> None:
    frame = pd.DataFrame(
        {
            "machine_number": [101, 102, 101, 102],
            "section": ["1001-1002", "1001-1002", "1001-1002", "1001-1002"],
            "X": [1.0, 2.0, 1.0, 2.0],
            "Y": [1.0, 1.0, 1.0, 1.0],
        }
    )

    result = _build_kakuban_axis(frame, hall_label="蒲田1", floor="2F")

    assert sorted(result["kakuban"].tolist()) == [1, 2]
    assert result["kakuban"].max() == 2
