from __future__ import annotations

from pathlib import Path

import pandas as pd

from eda.mitoya_section_category_eda import (
    branch_a_section_split_half,
    branch_b_category_xdds,
    branch_c_regime_monthly,
    classify_category,
)

MASTER_CSV = Path("document/machine_master_research/machine_master.csv")


def _make_branch_df() -> pd.DataFrame:
    dates = pd.to_datetime(
        [
            "2025-01-01",
            "2025-01-02",
            "2025-01-04",
            "2025-01-07",
            "2025-01-11",
            "2025-01-14",
            "2025-01-17",
            "2025-01-24",
            "2025-01-27",
            "2025-01-28",
            "2025-02-04",
            "2025-02-07",
            "2025-02-14",
            "2025-02-24",
        ]
    )
    section_specs = [
        (
            "523-556",
            [
                (101, "アイムジャグラーEX-TP", 60),
                (102, "ウルトラミラクルジャグラー", 40),
                (103, "クランキークレスト", 20),
            ],
        ),
        (
            "557-590",
            [
                (201, "アナザーゴッドハーデス‐解き放たれし槍撃ver.‐", -30),
                (202, "ToLOVEるダークネス", -10),
                (203, "かぐや様は告らせたい", 10),
            ],
        ),
    ]

    rows: list[dict[str, object]] = []
    for section, machines in section_specs:
        for machine_number, machine_name, base in machines:
            for idx, date in enumerate(dates):
                xdds_bonus = 35 if date.day in {4, 7, 14, 17, 24, 27} else 0
                if section == "523-556":
                    diff = base + idx * 10 + xdds_bonus
                else:
                    diff = base - idx * 5 + xdds_bonus
                rows.append(
                    {
                        "date": date,
                        "machine_number": machine_number,
                        "machine_name": machine_name,
                        "diff_coins_normalized": diff,
                        "games_normalized": 1000,
                        "section": section,
                    }
                )
    return pd.DataFrame(rows)


def test_classify_category_known() -> None:
    frame = pd.DataFrame(
        {
            "date": pd.to_datetime(["2025-01-01", "2025-01-02"]),
            "machine_number": [101, 202],
            "machine_name": [
                "アイムジャグラーEX-TP",
                "アナザーゴッドハーデス‐解き放たれし槍撃ver.‐",
            ],
            "diff_coins_normalized": [100, -50],
            "games_normalized": [1000, 1000],
            "section": ["523-556", "557-590"],
        }
    )
    out = classify_category(frame, MASTER_CSV)
    assert out.loc[out["machine_name"].eq("アイムジャグラーEX-TP"), "category"].iloc[0] == "A群"
    assert out.loc[out["machine_name"].eq("アナザーゴッドハーデス‐解き放たれし槍撃ver.‐"), "category"].iloc[0] == "AT群"


def test_branch_a_required_columns() -> None:
    df = _make_branch_df()
    df["payout_pct"] = (df["games_normalized"] * 3 + df["diff_coins_normalized"]) / (df["games_normalized"] * 3) * 100
    df["weekday"] = df["date"].dt.day_name()
    df["is_xdds"] = df["date"].dt.day.isin({4, 7, 14, 17, 24, 27}).astype(int)
    result = branch_a_section_split_half(df, min_cell_days=1)
    required = {
        "section",
        "axis_label",
        "axis_value",
        "delta_pct",
        "q_value",
        "stable",
        "dominant_category",
    }
    assert required <= set(result.columns)
    assert not result.empty


def test_branch_b_2x2_shape() -> None:
    df = _make_branch_df()
    df["payout_pct"] = (df["games_normalized"] * 3 + df["diff_coins_normalized"]) / (df["games_normalized"] * 3) * 100
    df["weekday"] = df["date"].dt.day_name()
    df["is_xdds"] = df["date"].dt.day.isin({4, 7, 14, 17, 24, 27}).astype(int)
    df = classify_category(df, MASTER_CSV)
    result = branch_b_category_xdds(df)
    assert {"X_DDS", "non_X_DDS"} <= set(result["day_type"].unique())
    assert {"A群", "AT群"} <= set(result["category"].unique())


def test_branch_c_monthly_columns() -> None:
    df = pd.DataFrame(
        {
            "date": pd.to_datetime(["2025-01-01", "2025-01-15", "2025-02-01", "2025-02-15"]),
            "payout_pct": [101.0, 99.0, 104.0, 106.0],
        }
    )
    result = branch_c_regime_monthly(df)
    assert "year_month" in result.columns
    assert "median_payout" in result.columns
    assert len(result) == 2
