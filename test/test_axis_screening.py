from __future__ import annotations

import pandas as pd


def _make_screen_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "date": ["20260701", "20260702", "20260401", "20260402"],
            "machine_name": ["alpha", "alpha", "beta", "beta"],
            "machine_number": [101, 101, 201, 201],
            "diff": [300, 250, -50, 20],
            "games": [1000, 1000, 1000, 1000],
        }
    )


def test_ranked_screening_results_are_filtered_and_sorted() -> None:
    from dashboard.pages import page_11c_axis_screening as page

    pattern_summary = pd.DataFrame(
        {
            "machine_name": ["a", "b", "c"],
            "axis": ["dd_bin", "day_of_week", "dd_bin"],
            "outcome": ["diff", "hit104", "plus"],
            "n_obs": [50, 60, 70],
            "effect_size": [0.21, 0.31, 0.11],
            "p_value": [0.01, 0.02, 0.03],
            "n_sparse_levels": [0, 1, 0],
            "note": ["", "warning: sparse", ""],
        }
    )

    ranked = page._rank_screening_results(pattern_summary, effect_threshold=0.1)

    assert list(ranked["machine_name"]) == ["b", "a", "c"]
    assert bool(ranked.iloc[0]["sparse_warning"]) is True
    assert set(ranked.columns) >= {
        "machine_name",
        "axis",
        "outcome",
        "n_obs",
        "effect_size",
        "p_value",
        "sparse_warning",
        "note",
    }


def test_reproducibility_table_uses_two_90_day_windows(monkeypatch) -> None:
    from dashboard.pages import page_11c_axis_screening as page

    frame = _make_screen_frame().copy()
    frame["date_dt"] = pd.to_datetime(frame["date"], format="%Y%m%d")
    ranked = pd.DataFrame(
        {
            "machine_name": ["alpha"],
            "axis": ["dd_bin"],
            "outcome": ["diff"],
            "n_obs": [50],
            "effect_size": [0.22],
            "p_value": [0.01],
            "sparse_warning": [False],
            "note": [""],
        }
    )

    recent_rows = pd.DataFrame(
        {
            "hall": ["kamata7"],
            "machine_name": ["alpha"],
            "axis": ["dd_bin"],
            "outcome": ["diff"],
            "test": ["kruskal"],
            "statistic": [10.0],
            "p_value": [0.01],
            "effect_size": [0.25],
            "n_obs": [12],
            "n_groups": [2],
            "n_sparse_levels": [0],
            "note": [""],
        }
    )
    previous_rows = recent_rows.copy()

    calls: list[tuple[pd.Timestamp, pd.Timestamp]] = []

    def _fake_window_rows(_frame, *, hall_key, machine_name, start, end):
        calls.append((start, end))
        return recent_rows.copy() if len(calls) == 1 else previous_rows.copy()

    monkeypatch.setattr(page, "_window_machine_rows", _fake_window_rows)

    repro = page._build_reproducibility_table(frame, ranked, hall_key="kamata7", top_n=1, effect_threshold=0.2)

    assert len(calls) == 2
    assert bool(repro.iloc[0]["holds_in_both"]) is True
    assert repro.iloc[0]["recent_90_effect_size"] == 0.25
    assert repro.iloc[0]["previous_90_effect_size"] == 0.25


def test_screening_cache_key_changes_with_window_and_threshold() -> None:
    from dashboard.pages import page_11c_axis_screening as page

    base = page._screening_cache_key(
        "kamata7",
        "C:/db/kamata7.db",
        min_games=1000,
        min_machine_days_total=30,
        min_obs_for_ranking=100,
        top_n=20,
        effect_threshold=0.1,
        date_range=(pd.Timestamp("2026-01-01"), pd.Timestamp("2026-03-31")),
    )
    changed = page._screening_cache_key(
        "kamata7",
        "C:/db/kamata7.db",
        min_games=1000,
        min_machine_days_total=30,
        min_obs_for_ranking=100,
        top_n=20,
        effect_threshold=0.2,
        date_range=(pd.Timestamp("2026-01-01"), pd.Timestamp("2026-03-31")),
    )

    assert base != changed
