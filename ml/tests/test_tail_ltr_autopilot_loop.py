from ml.experiments import tail_ltr_autopilot_loop as loop


def test_shift_seeds_disabled_keeps_values() -> None:
    assert loop.shift_seeds([42, 77], 3, step=1000, enabled=False) == [42, 77]


def test_shift_seeds_enabled_offsets_by_round() -> None:
    assert loop.shift_seeds([42, 77], 0, step=1000, enabled=True) == [42, 77]
    assert loop.shift_seeds([42, 77], 2, step=1000, enabled=True) == [2042, 2077]


def test_extract_best_lift_reads_top10_rows() -> None:
    summary = {
        "top10_by_lift": [
            {"lift_vs_random": 0.01},
            {"lift_vs_random": 0.08},
            {"lift_vs_random": -0.03},
        ]
    }
    assert loop.extract_best_lift(summary) == 0.08


def test_extract_executed_trials_reads_trial_counts() -> None:
    summary = {"trial_counts": {"executed_this_run": 12}}
    assert loop.extract_executed_trials(summary) == 12
