from __future__ import annotations

import pandas as pd

from ml.analysis import kamata7_triplet_window_eda as narabi


def _make_frame(*, segment_key: str, section: str, date: str, diffs: list[int]) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for index, diff in enumerate(diffs, start=1):
        rows.append(
            {
                "date": date,
                "segment_key": segment_key,
                "floor": "2F",
                "section": section,
                "rank_from_min": index,
                "rank_from_max": len(diffs) - index + 1,
                "machine_number": 100 + index,
                "machine_name": f"M{index}",
                "diff_coins_normalized": diff,
                "games_normalized": 1000,
            }
        )
    return pd.DataFrame(rows)


def test_build_triplet_window_frame_computes_window_excess_and_edge_distance() -> None:
    frame = _make_frame(
        segment_key="kamata7_2F_A",
        section="S1",
        date="2026-06-01",
        diffs=[10, 20, 30, 40, 50],
    )

    out = narabi.build_triplet_window_frame(frame, window_size=3)

    assert out["window_start_rank"].tolist() == [1, 2, 3]
    assert out["window_mean_diff"].tolist() == [20.0, 30.0, 40.0]
    assert out["section_mean_diff"].tolist() == [30.0, 30.0, 30.0]
    assert out["window_excess"].tolist() == [-10.0, 0.0, 10.0]
    assert out["touches_edge"].tolist() == [True, False, True]
    assert out["distance_to_nearest_edge"].tolist() == [0, 1, 0]


def test_build_start_position_summary_bins_relative_positions() -> None:
    frame = pd.concat(
        [
            _make_frame(
                segment_key="kamata7_2F_A",
                section="S1",
                date="2026-06-01",
                diffs=[10, 20, 30, 40, 50],
            ),
            _make_frame(
                segment_key="kamata7_2F_A",
                section="S2",
                date="2026-06-02",
                diffs=[50, 40, 30, 20, 10],
            ),
        ],
        ignore_index=True,
    )

    window_frame = narabi.build_triplet_window_frame(frame, window_size=3)
    summary = narabi.summarize_start_position_bins(window_frame)

    left = summary[(summary["segment_key"] == "kamata7_2F_A") & (summary["start_position_bin"] == "left_edge")].iloc[0]
    middle = summary[(summary["segment_key"] == "kamata7_2F_A") & (summary["start_position_bin"] == "middle")].iloc[0]
    right = summary[(summary["segment_key"] == "kamata7_2F_A") & (summary["start_position_bin"] == "right_edge")].iloc[0]

    assert int(left["n_windows"]) == 2
    assert int(middle["n_windows"]) == 2
    assert int(right["n_windows"]) == 2
    assert float(left["mean_start_ratio"]) == 0.0
    assert float(right["mean_start_ratio"]) == 1.0


def test_summarize_weekday_comparison_compares_saturday_against_non_saturday() -> None:
    saturday = pd.DataFrame(
        {
            "segment_key": ["kamata7_2F_A", "kamata7_2F_A"],
            "window_excess": [15.0, 20.0],
        }
    )
    non_saturday = pd.DataFrame(
        {
            "segment_key": ["kamata7_2F_A", "kamata7_2F_A"],
            "window_excess": [0.0, 1.0],
        }
    )

    summary = narabi.summarize_weekday_comparison(saturday, non_saturday)
    row = summary.iloc[0]

    assert row["segment_key"] == "kamata7_2F_A"
    assert int(row["saturday_n_windows"]) == 2
    assert int(row["non_saturday_n_windows"]) == 2
    assert float(row["saturday_mean_excess"]) == 17.5
    assert float(row["non_saturday_mean_excess"]) == 0.5
    assert float(row["mean_excess_gap"]) == 17.0
