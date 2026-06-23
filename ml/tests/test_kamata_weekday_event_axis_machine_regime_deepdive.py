from __future__ import annotations

import pandas as pd

from ml.analysis.kamata_weekday_event_axis_machine_regime_deepdive import (
    TARGET_MACHINES,
    TARGET_SECTION,
    _machine_history,
    _machine_sunday_concentration,
    _section_sunday_summary,
)


def _synthetic_section_frame() -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    dates = pd.date_range("2025-12-15", periods=28, freq="D")
    for date in dates:
        weekday = date.strftime("%a")
        for machine_number, machine_name, sunday_value in (
            (2179, "OTHER", 97.0),
            (2180, "EVA", 105.0),
            (2182, "SHAKE", 106.0),
        ):
            payoutrate = sunday_value if weekday == "Sun" else 97.0
            rows.append(
                {
                    "date": date,
                    "weekday_label": weekday,
                    "machine_number": machine_number,
                    "machine_name": machine_name,
                    "section": TARGET_SECTION,
                    "payoutrate_pct": payoutrate,
                }
            )
    return pd.DataFrame(rows)


def test_machine_history_tracks_name_swap_and_weekday_shift() -> None:
    frame = pd.DataFrame(
        {
            "date": pd.to_datetime(
                [
                    "2025-12-21",
                    "2025-12-22",
                    "2025-12-28",
                    "2025-12-29",
                ]
            ),
            "weekday_label": ["Sun", "Mon", "Sun", "Mon"],
            "machine_number": [2182, 2182, 2182, 2182],
            "machine_name": ["旧機種", "新機種", "新機種", "新機種"],
            "section": [TARGET_SECTION] * 4,
            "payoutrate_pct": [100.0, 101.0, 104.0, 105.0],
        }
    )

    history = _machine_history(frame, 2182)
    period_weekday = (
        frame.assign(
            period=pd.Series(["before_2025-12-22", "on_or_after_2025-12-22", "on_or_after_2025-12-22", "on_or_after_2025-12-22"])
        )
    )
    period_weekday = period_weekday.groupby(["period", "machine_name", "weekday_label"], as_index=False).agg(
        median_payoutrate_pct=("payoutrate_pct", "median"),
        mean_payoutrate_pct=("payoutrate_pct", "mean"),
        share_104_plus=("payoutrate_pct", lambda s: float((pd.Series(s) >= 104.0).mean())),
        n_rows=("date", "size"),
        n_dates=("date", "nunique"),
    )

    assert history["machine_name"].tolist() == ["旧機種", "新機種"]
    assert history.iloc[0]["first_date"] == pd.Timestamp("2025-12-21")
    assert history.iloc[0]["last_date"] == pd.Timestamp("2025-12-21")
    assert history.iloc[1]["first_date"] == pd.Timestamp("2025-12-22")
    assert history.iloc[1]["last_date"] == pd.Timestamp("2025-12-29")
    assert history.iloc[1]["mean_payoutrate_pct"] > history.iloc[0]["mean_payoutrate_pct"]

    before_sun = period_weekday.loc[
        (period_weekday["period"].eq("before_2025-12-22"))
        & (period_weekday["weekday_label"].eq("Sun"))
    ].iloc[0]
    after_sun = period_weekday.loc[
        (period_weekday["period"].eq("on_or_after_2025-12-22"))
        & (period_weekday["weekday_label"].eq("Sun"))
    ].iloc[0]

    assert after_sun["median_payoutrate_pct"] > before_sun["median_payoutrate_pct"]
    assert after_sun["share_104_plus"] >= before_sun["share_104_plus"]


def test_section_sunday_summary_weakens_after_excluding_focus_machines() -> None:
    frame = _synthetic_section_frame()

    summary_full, compare_full, _ = _section_sunday_summary(frame)
    summary_excl, compare_excl, _ = _section_sunday_summary(frame, exclude_machines=TARGET_MACHINES)
    concentration = _machine_sunday_concentration(frame[frame["section"].eq(TARGET_SECTION)])
    concentration_excl = _machine_sunday_concentration(
        frame[frame["section"].eq(TARGET_SECTION) & ~frame["machine_number"].isin(TARGET_MACHINES)]
    )

    assert summary_full.loc[summary_full["weekday_label"].eq("Sun"), "n_dates"].iloc[0] == 4
    assert summary_full.loc[summary_full["weekday_label"].eq("Sun"), "n_machines"].iloc[0] == 12
    assert summary_excl.loc[summary_excl["weekday_label"].eq("Sun"), "n_machines"].iloc[0] == 4

    full_sun = compare_full.loc[compare_full["weekday_label"].eq("Sun")].iloc[0]
    excl_sun = compare_excl.loc[compare_excl["weekday_label"].eq("Sun")].iloc[0]

    assert summary_full.loc[summary_full["weekday_label"].eq("Sun"), "median_payoutrate_pct"].iloc[0] > summary_excl.loc[
        summary_excl["weekday_label"].eq("Sun"), "median_payoutrate_pct"
    ].iloc[0]
    assert full_sun["delta"] > excl_sun["delta"]

    assert concentration.iloc[0]["machine_number"] in TARGET_MACHINES
    assert concentration.iloc[0]["top_machine_share"] > 0.5
    assert pd.isna(concentration_excl.iloc[0]["top_machine_share"]) or concentration_excl.iloc[0]["top_machine_share"] <= 0.5
