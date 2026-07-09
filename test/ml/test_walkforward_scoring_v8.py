from __future__ import annotations

import pandas as pd

from ml.experiments.walkforward_scoring import config as wf_config
from ml.experiments.walkforward_scoring import scoring_model as wf_scoring


def _make_row(
    *,
    date: str,
    machine_number: int,
    machine_name: str,
    last_digit: str,
    games_normalized: int,
    diff_coins_normalized: int,
) -> dict[str, object]:
    return {
        "date": date,
        "machine_number": machine_number,
        "machine_name": machine_name,
        "last_digit": last_digit,
        "is_zorome": int(last_digit in {"0", "5", "6", "9"}),
        "games_normalized": games_normalized,
        "diff_coins_normalized": diff_coins_normalized,
    }


def test_variant_configs_include_v8_dynamic() -> None:
    variants = wf_config.build_variant_configs()

    assert "v8_dynamic" in variants
    assert variants["v8_dynamic"].use_new_kakuban is True
    assert variants["v8_dynamic"].use_v8_dynamic is True
    assert variants["v8_dynamic"].hist_metric == "hit_an"


def test_c5_is_computed_for_multiple_segments() -> None:
    coords = wf_scoring.load_coords_bundle()
    left_machines = coords.loc[(coords["floor"] == "2F") & (coords["lr"] == "L"), "machine_number"].head(2).tolist()
    left_machine_a = int(left_machines[0])
    left_machine_b = int(left_machines[1])

    train = pd.DataFrame(
        [
            _make_row(
                date="2026-03-01",
                machine_number=left_machine_a,
                machine_name="Alpha",
                last_digit="1",
                games_normalized=1000,
                diff_coins_normalized=100,
            ),
            _make_row(
                date="2026-03-02",
                machine_number=left_machine_a,
                machine_name="Alpha",
                last_digit="1",
                games_normalized=1000,
                diff_coins_normalized=200,
            ),
            _make_row(
                date="2026-03-02",
                machine_number=left_machine_a,
                machine_name="Alpha",
                last_digit="1",
                games_normalized=1000,
                diff_coins_normalized=300,
            ),
            _make_row(
                date="2026-03-01",
                machine_number=left_machine_b,
                machine_name="Beta",
                last_digit="2",
                games_normalized=1000,
                diff_coins_normalized=-300,
            ),
            _make_row(
                date="2026-03-02",
                machine_number=left_machine_b,
                machine_name="Beta",
                last_digit="2",
                games_normalized=1000,
                diff_coins_normalized=-400,
            ),
            _make_row(
                date="2026-03-02",
                machine_number=left_machine_b,
                machine_name="Beta",
                last_digit="2",
                games_normalized=1000,
                diff_coins_normalized=-500,
            ),
        ]
    )
    actual = pd.DataFrame(
        [
            _make_row(
                date="2026-03-03",
                machine_number=left_machine_a,
                machine_name="Alpha",
                last_digit="1",
                games_normalized=1000,
                diff_coins_normalized=0,
            ),
            _make_row(
                date="2026-03-03",
                machine_number=left_machine_b,
                machine_name="Beta",
                last_digit="2",
                games_normalized=1000,
                diff_coins_normalized=0,
            ),
        ]
    )

    scored = wf_scoring.score_day(train, actual, wf_config.build_variant_configs()["v8_dynamic"])

    assert set(scored["segment"]) == {"2F_L_N"}
    assert scored["c5"].abs().sum() > 0
    assert scored.loc[scored["machine_number"].eq(left_machine_a), "c5"].iloc[0] != 0


def test_compute_dynamic_lifts_returns_positive_weights() -> None:
    values = list(range(60))
    train = pd.DataFrame(
        {
            "segment": ["2F_L_N"] * 60,
            "diff_coins_normalized": values,
            "c1": values,
            "c2": list(reversed(values)),
            "c3": [1] * 60,
            "c4": [2] * 60,
            "c5": [3] * 60,
            "c6": [4] * 60,
        }
    )

    lifts = wf_scoring._compute_dynamic_lifts(train, "2F_L_N")

    assert set(lifts) == {"c1", "c2", "c3", "c4", "c5", "c6"}
    assert all(value > 0 for value in lifts.values())
    assert all(value == 0.5 for value in lifts.values())


def test_compute_dynamic_hist_ratio_tracks_spearman_signal() -> None:
    train = pd.DataFrame(
        {
            "segment": ["2F_L_N"] * 120,
            "diff_coins_normalized": list(range(120)),
            "hist_metric": list(range(120)),
        }
    )

    ratio = wf_scoring._compute_dynamic_hist_ratio(train, "2F_L_N")

    assert 0.05 <= ratio <= 0.25
    assert ratio > 0.10


def test_score_day_v8_dynamic_returns_ranked_rows() -> None:
    train = pd.DataFrame(
        [
            _make_row(
                date="2026-03-01",
                machine_number=2001,
                machine_name="Alpha",
                last_digit="1",
                games_normalized=1000,
                diff_coins_normalized=100,
            ),
            _make_row(
                date="2026-03-01",
                machine_number=2002,
                machine_name="Alpha",
                last_digit="2",
                games_normalized=1000,
                diff_coins_normalized=50,
            ),
            _make_row(
                date="2026-03-02",
                machine_number=2001,
                machine_name="Alpha",
                last_digit="1",
                games_normalized=1000,
                diff_coins_normalized=200,
            ),
            _make_row(
                date="2026-03-02",
                machine_number=2002,
                machine_name="Alpha",
                last_digit="2",
                games_normalized=1000,
                diff_coins_normalized=-20,
            ),
        ]
    )
    actual = pd.DataFrame(
        [
            _make_row(
                date="2026-03-03",
                machine_number=2001,
                machine_name="Alpha",
                last_digit="1",
                games_normalized=1000,
                diff_coins_normalized=0,
            ),
            _make_row(
                date="2026-03-03",
                machine_number=2002,
                machine_name="Alpha",
                last_digit="2",
                games_normalized=1000,
                diff_coins_normalized=0,
            ),
        ]
    )

    scored = wf_scoring.score_day(train, actual, wf_config.build_variant_configs()["v8_dynamic"])

    assert scored["variant"].nunique() == 1
    assert scored["variant"].iloc[0] == "v8_dynamic"
    assert scored["composite"].notna().all()
    assert list(scored.sort_values("composite", ascending=False)["machine_number"]) == [2001, 2002]
