from __future__ import annotations

import pandas as pd
import pytest


def test_top2_share_returns_nan_when_total_sum_is_small() -> None:
    from eda import mitoya_phase4_durability as phase4

    frame = pd.DataFrame(
        [
            {"machine_number": 1, "mean_diff": 40.0},
            {"machine_number": 2, "mean_diff": -30.0},
            {"machine_number": 3, "mean_diff": -15.0},
        ]
    )

    assert pd.isna(phase4.compute_top2_share(frame))


def test_split_half_label_keeps_both_halves() -> None:
    from eda import mitoya_phase4_durability as phase4

    dates = pd.date_range("2026-01-01", periods=6, freq="D")
    frame = pd.DataFrame({"date": dates, "value": range(6)})

    labeled = phase4.add_split_half_label(frame)

    assert labeled["split_half"].tolist() == ["first", "first", "first", "second", "second", "second"]
