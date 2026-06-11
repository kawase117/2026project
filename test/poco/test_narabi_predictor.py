from __future__ import annotations

import pytest

from poco.narabi_predictor import (
    HallRow,
    SignalSummary,
    compute_signal_summary,
    compute_random_baseline,
    parse_strategy_digits,
    prepare_hall_rows,
    score_digits,
    walk_forward_predict,
)


def test_parse_strategy_digits_uses_left_side_only() -> None:
    assert parse_strategy_digits("3,8|2") == [3, 8]
    assert parse_strategy_digits(" 9 | 1 ") == [9]
    assert parse_strategy_digits("") == []


def test_prepare_hall_rows_uses_only_prior_four_weeks_for_recent_freq() -> None:
    records = [
        {"hall": "K1", "date": "20250104", "dd": 4, "strategy_digits": "1|2"},
        {"hall": "K1", "date": "20250111", "dd": 11, "strategy_digits": "2|2"},
        {"hall": "K1", "date": "20250118", "dd": 18, "strategy_digits": "3|2"},
        {"hall": "K1", "date": "20250125", "dd": 25, "strategy_digits": "4|2"},
        {"hall": "K1", "date": "20250201", "dd": 1, "strategy_digits": "5|2"},
        {"hall": "K1", "date": "20250208", "dd": 8, "strategy_digits": "6|2"},
    ]

    rows = prepare_hall_rows(records)

    assert rows[0].prev_first_digit is None
    assert rows[1].prev_first_digit == 1
    assert rows[1].week_diff == 1

    fifth = rows[4]
    assert fifth.recent_freq[1] == 1
    assert fifth.recent_freq[4] == 1
    assert fifth.recent_freq[5] == 0

    sixth = rows[5]
    assert sixth.prev_first_digit == 5
    assert sixth.week_diff == 1
    assert sixth.recent_freq[1] == 0
    assert sixth.recent_freq[2] == 1
    assert sixth.recent_freq[5] == 1


def test_compute_signal_summary_tracks_x5_momentum_direction() -> None:
    rows = [
        HallRow(
            hall="K1",
            date=f"2025010{index + 1}",
            dd=index + 1,
            digits_list=[7] if index >= 2 else [index],
            first_digit=7 if index >= 2 else index,
            dd_mod10=index + 1,
            prev_first_digit=index - 1 if index > 0 else None,
            week_diff=1 if index > 0 else None,
            recent_freq={
                digit: (index if digit == 7 else 0)
                for digit in range(10)
            },
        )
        for index in range(5)
    ]

    summary = compute_signal_summary(rows)

    assert summary.x5_best_positive_r > 0
    assert summary.x5_best_positive_p == pytest.approx(summary.x5_by_digit[7][1])
    assert summary.x5_by_digit[7][0] == pytest.approx(summary.x5_best_positive_r)


def test_score_digits_applies_continuous_x5_scores() -> None:
    target_row = HallRow(
        hall="K1",
        date="20251004",
        dd=4,
        digits_list=[9, 2],
        first_digit=9,
        dd_mod10=4,
        prev_first_digit=7,
        week_diff=2,
        recent_freq={0: 1, 1: 0, 2: 1, 3: 0, 4: 1, 5: 2, 6: 0, 7: 1, 8: 1, 9: 0},
    )
    signal_summary = SignalSummary(
        x2_best_digit=3,
        x2_best_r=0.5,
        x2_best_p=0.01,
        x3_r=0.4,
        x3_p=0.04,
        x4_best_offset=2,
        x4_best_r=0.45,
        x4_best_p=0.03,
        x5_best_negative_r=-0.5,
        x5_best_negative_p=0.02,
        x5_best_positive_r=0.48,
        x5_best_positive_p=0.03,
    )

    ranking, scores = score_digits(target_row, signal_summary)

    assert scores[9] == pytest.approx(4.04)
    assert scores[3] == pytest.approx(3.04)
    assert scores[5] == pytest.approx(2.02)
    assert ranking[:3] == [9, 3, 6]


def test_score_digits_uses_recent_freq_for_default_tie_break() -> None:
    target_row = HallRow(
        hall="K1",
        date="20251011",
        dd=11,
        digits_list=[4],
        first_digit=4,
        dd_mod10=1,
        prev_first_digit=2,
        week_diff=2,
        recent_freq={0: 3, 1: 0, 2: 1, 3: 2, 4: 0, 5: 4, 6: 1, 7: 2, 8: 3, 9: 4},
    )
    signal_summary = SignalSummary(
        x2_best_digit=0,
        x2_best_r=0.0,
        x2_best_p=1.0,
        x3_r=0.0,
        x3_p=1.0,
        x4_best_offset=0,
        x4_best_r=0.0,
        x4_best_p=1.0,
        x5_best_negative_r=0.0,
        x5_best_negative_p=1.0,
        x5_best_positive_r=0.0,
        x5_best_positive_p=1.0,
    )

    ranking, scores = score_digits(target_row, signal_summary)

    assert scores[1] == pytest.approx(0.04)
    assert scores[4] == pytest.approx(0.04)
    assert scores[5] == pytest.approx(0.0)
    assert ranking[:4] == [4, 1, 6, 2]


def test_random_baseline_accounts_for_multi_digit_actuals() -> None:
    hit3, mrr = compute_random_baseline([[1], [2, 3]])

    assert hit3 == pytest.approx((0.3 + (64 / 120)) / 2)
    assert mrr == pytest.approx((0.18333333333333335 + 0.34074074074074073) / 2)


def test_walk_forward_predict_starts_after_initial_train_window(monkeypatch: pytest.MonkeyPatch) -> None:
    rows = [
        HallRow(
            hall="K1",
            date=f"202501{index + 1:02d}",
            dd=index + 1,
            digits_list=[index % 10],
            first_digit=index % 10,
            dd_mod10=(index + 1) % 10,
            prev_first_digit=(index - 1) % 10 if index > 0 else None,
            week_diff=1 if index > 0 else None,
            recent_freq={digit: 0 for digit in range(10)},
        )
        for index in range(12)
    ]

    monkeypatch.setattr(
        "poco.narabi_predictor.compute_signal_summary",
        lambda train_rows: SignalSummary(
            x2_best_digit=0,
            x2_best_r=0.0,
            x2_best_p=1.0,
            x3_r=0.0,
            x3_p=1.0,
            x4_best_offset=0,
            x4_best_r=0.0,
            x4_best_p=1.0,
            x5_best_negative_r=0.0,
            x5_best_negative_p=1.0,
            x5_best_positive_r=0.0,
            x5_best_positive_p=1.0,
        ),
    )
    monkeypatch.setattr(
        "poco.narabi_predictor.score_digits",
        lambda target_row, signal_summary: ([0, 2, 3], {digit: 0 for digit in range(10)}),
    )

    predictions = walk_forward_predict(rows, min_train_size=10)

    assert len(predictions) == 2
    assert predictions[0].date == "20250111"
    assert predictions[0].top3_pred == [0, 2, 3]
    assert predictions[0].hit is True
    assert predictions[1].date == "20250112"
    assert predictions[1].hit is False
