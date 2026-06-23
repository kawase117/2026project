from __future__ import annotations

from pathlib import Path

import pandas as pd

from eda import mitoya_machinename_axis_eda as axis  # noqa: E402


def _make_df() -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    periods = [
        ("2025-01-01", "2025-03-31"),
        ("2025-04-01", "2025-06-30"),
    ]
    for period_idx, (start, end) in enumerate(periods):
        dates = pd.date_range(start, end, freq="7D")
        for machine_name, base, spread in [
            ("Q5", 120, 1),
            ("Q1", -40, 12),
            ("ALL", 20, 6),
        ]:
            for idx, date in enumerate(dates):
                diff = base + (idx % 3 - 1) * spread
                if machine_name == "Q5" and date.day in axis.X_DDS:
                    diff += 20
                rows.append(
                    {
                        "date": date,
                        "machine_number": 100 + period_idx * 10 + (0 if machine_name == "Q5" else 1 if machine_name == "Q1" else 2),
                        "machine_name": machine_name,
                        "diff_coins_normalized": diff,
                        "games_normalized": 1000,
                    }
                )
    return pd.DataFrame(rows)


def test_branch_a_q5_beats_q1() -> None:
    result = axis.branch_a_q5_persistence(_make_df())
    assert not result.empty
    row = result.iloc[0]
    assert row["q5_payout_mean"] > row["q1_payout_mean"]


def test_branch_b_q5_lower_std() -> None:
    result = axis.branch_b_stability(_make_df())
    assert not result.empty
    row = result.iloc[0]
    assert row["q5_diff_std_median"] <= row["q1_diff_std_median"]


def test_branch_c_xdds_lift_sorted() -> None:
    rows: list[dict[str, object]] = []
    for month in range(1, 5):
        for dd in axis.X_DDS:
            date = pd.Timestamp(f"2025-{month:02d}-{dd:02d}")
            for machine_name, machine_number, base in [
                ("Q5", 301, 120),
                ("Q1", 302, 10),
                ("ALL", 303, 40),
            ]:
                rows.append(
                    {
                        "date": date,
                        "machine_number": machine_number,
                        "machine_name": machine_name,
                        "diff_coins_normalized": base + (20 if machine_name == "Q5" else 0),
                        "games_normalized": 1000,
                    }
                )
        for dd in [1, 2, 3, 5, 6, 8]:
            date = pd.Timestamp(f"2025-{month:02d}-{dd:02d}")
            for machine_name, machine_number, base in [
                ("Q5", 301, 120),
                ("Q1", 302, 10),
                ("ALL", 303, 40),
            ]:
                rows.append(
                    {
                        "date": date,
                        "machine_number": machine_number,
                        "machine_name": machine_name,
                        "diff_coins_normalized": base - (10 if machine_name == "Q1" else 0),
                        "games_normalized": 1000,
                    }
                )
    df = pd.DataFrame(rows)
    result = axis.branch_c_xdds_cross(df)
    assert not result.empty
    lifts = result["lift"].tolist()
    assert lifts == sorted(lifts, reverse=True)


def test_branch_d_has_category_column() -> None:
    df = _make_df()
    master = pd.DataFrame(
        [
            {"machine_name": "Q5", "jug_flag": 1, "hana_flag": 0, "oki_flag": 0, "bt_flag": 0},
            {"machine_name": "Q1", "jug_flag": 0, "hana_flag": 0, "oki_flag": 0, "bt_flag": 1},
            {"machine_name": "ALL", "jug_flag": 0, "hana_flag": 0, "oki_flag": 0, "bt_flag": 0},
        ]
    )
    result = axis.branch_d_category(df, master)
    assert {"category", "q5_entry_rate"} <= set(result.columns)
    assert set(result["category"]) == {"jug", "bt", "other"}
