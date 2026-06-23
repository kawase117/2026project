from __future__ import annotations

from pathlib import Path

import pandas as pd

from eda import mitoya_machine_category_axis_deepdive as deepdive  # noqa: E402


def _make_df() -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    dates = pd.date_range("2025-01-01", periods=120, freq="D")
    specs = [
        ("jug_machine", 101, "jug", 80, 20),
        ("bt_machine", 102, "bt", 30, 10),
        ("other_hi", 201, "other", 50, 30),
        ("other_lo", 202, "other", 20, -10),
    ]
    for date in dates:
        is_xdds = date.day in deepdive.X_DDS
        for machine_name, machine_number, category, base_xdds, base_non in specs:
            if machine_name == "other_lo" and is_xdds:
                continue
            diff = base_xdds if is_xdds else base_non
            rows.append(
                {
                    "date": date,
                    "machine_number": machine_number,
                    "machine_name": machine_name,
                    "diff_coins_normalized": diff,
                    "games_normalized": 1000,
                    "category": category,
                    "is_xdds": is_xdds,
                    "payout": (1000 * 3 + diff) / (1000 * 3) * 100,
                }
            )
    return pd.DataFrame(rows)


def test_branch_e_has_all_categories() -> None:
    result = deepdive.branch_e_category_xdds(_make_df())
    assert {"jug", "bt", "other"} <= set(result["category"])


def test_branch_e_delta_direction() -> None:
    result = deepdive.branch_e_category_xdds(_make_df())
    row = result.loc[result["category"].eq("jug")].iloc[0]
    assert row["xdds_payout"] > row["non_xdds_payout"]


def test_branch_f_filtered_by_min_n_xdds() -> None:
    df = _make_df()
    result = deepdive.branch_f_other_machine_xdds(df)
    assert not result.empty
    assert (result["n_xdds"] >= deepdive.MIN_N_XDDS).all()
    assert "other_lo" not in set(result["machine_name"])


def test_branch_f_sorted_by_delta() -> None:
    result = deepdive.branch_f_other_machine_xdds(_make_df())
    deltas = result["delta"].tolist()
    assert deltas == sorted(deltas, reverse=True)
