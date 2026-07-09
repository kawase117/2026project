from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest
from statsmodels.stats.multitest import multipletests


def _make_row(
    date: str,
    machine_number: int,
    machine_name: str,
    diff: float,
    *,
    games: int = 1000,
    day_of_week: str = "月",
    is_weekend: int = 0,
) -> dict[str, object]:
    payout_rate = ((games * 3 + diff) / (games * 3)) * 100.0
    return {
        "date": date,
        "machine_number": machine_number,
        "machine_name": machine_name,
        "diff": diff,
        "games": games,
        "day_of_week": day_of_week,
        "is_weekend": is_weekend,
        "hit104": int(payout_rate >= 104.0),
    }


def _make_frame_for_residuals() -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    weekdays = ["月", "火", "水"]
    for idx in range(12):
        weekday = weekdays[0] if idx < 6 else weekdays[1]
        is_weekend = int(weekday in {"土", "日"})
        date = f"2026{(idx // 2) + 1:02d}01"
        rows.extend(
            [
                _make_row(
                    date,
                    100 + idx,
                    "eligible",
                    500 if weekday == "月" else 100,
                    day_of_week=weekday,
                    is_weekend=is_weekend,
                ),
                _make_row(
                    date,
                    200 + idx,
                    "sparse",
                    300 if weekday == "月" else 50,
                    day_of_week=weekday,
                    is_weekend=is_weekend,
                ),
            ]
        )
    for idx in range(6):
        date = f"2026{idx + 1:02d}03"
        rows.append(_make_row(date, 300 + idx, "short", 600, day_of_week="水", is_weekend=0))
    return pd.DataFrame(rows)


def test_compute_machine_weekday_residuals_filters_short_machine_and_sparse_weekday(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from eda import machine_weekday_cross_agreement_scan as analysis

    frame = _make_frame_for_residuals()

    def fake_axis_breakdown(hall, machine_name, machine_frame, *, axis, outcome):
        if machine_name == "eligible":
            return pd.DataFrame(
                {
                    "hall": [hall, hall, hall],
                    "machine_name": [machine_name] * 3,
                    "axis": [axis] * 3,
                    "outcome": [outcome] * 3,
                    "axis_level": ["月", "火", "水"],
                    "axis_level_order": [0, 1, 2],
                    "n": [6, 4, 3],
                    "avg_diff": [10.0, 20.0, 30.0],
                    "plus_rate": [100.0, 100.0, 100.0],
                    "hit104_rate": [90.0, 80.0, 70.0],
                }
            )
        if machine_name == "sparse":
            return pd.DataFrame(
                {
                    "hall": [hall, hall],
                    "machine_name": [machine_name] * 2,
                    "axis": [axis] * 2,
                    "outcome": [outcome] * 2,
                    "axis_level": ["月", "火"],
                    "axis_level_order": [0, 1],
                    "n": [2, 1],
                    "avg_diff": [10.0, 20.0],
                    "plus_rate": [100.0, 100.0],
                    "hit104_rate": [50.0, 40.0],
                }
            )
        return pd.DataFrame(columns=analysis.RESIDUAL_COLUMNS)

    monkeypatch.setattr(analysis, "_axis_breakdown", fake_axis_breakdown)

    residuals = analysis.compute_machine_weekday_residuals(
        "蒲田7",
        frame,
        min_machine_days_total=10,
        min_cell_n=5,
    )

    assert set(residuals["machine_name"].astype(str)) == {"eligible"}
    assert set(residuals["weekday"].tolist()) == {"月"}
    assert residuals.loc[0, "baseline_hit104_rate"] == pytest.approx(
        frame.loc[frame["machine_name"].eq("eligible"), "hit104"].mean() * 100.0
    )


def test_aggregate_weekday_agreement_counts_zero_residual_as_negative() -> None:
    from eda import machine_weekday_cross_agreement_scan as analysis

    rows: list[dict[str, object]] = []
    for i in range(20):
        residual = 3.0 if i < 18 else 0.0 if i == 18 else -2.0
        rows.append(
            {
                "hall": "蒲田7",
                "machine_name": f"m{i:02d}",
                "weekday": "月",
                "n": 10,
                "hit104_rate": 80.0 + residual,
                "baseline_hit104_rate": 80.0,
                "residual": residual,
            }
        )
    for i in range(20):
        residual = 1.0 if i < 10 else 0.0 if i == 10 else -1.0
        rows.append(
            {
                "hall": "蒲田7",
                "machine_name": f"n{i:02d}",
                "weekday": "火",
                "n": 10,
                "hit104_rate": 80.0 + residual,
                "baseline_hit104_rate": 80.0,
                "residual": residual,
            }
        )
    rows.extend(
        [
            {
                "hall": "蒲田7",
                "machine_name": "tiny0",
                "weekday": "水",
                "n": 10,
                "hit104_rate": 81.0,
                "baseline_hit104_rate": 80.0,
                "residual": 1.0,
            },
            {
                "hall": "蒲田7",
                "machine_name": "tiny1",
                "weekday": "水",
                "n": 10,
                "hit104_rate": 79.0,
                "baseline_hit104_rate": 80.0,
                "residual": -1.0,
            },
        ]
    )
    residuals = pd.DataFrame(rows)

    agreement = analysis.aggregate_weekday_agreement(residuals, min_machines_for_test=15)

    row = agreement.loc[agreement["weekday"].eq("月")].iloc[0]
    assert row["agreement_rate"] == pytest.approx(0.9)
    assert row["n_positive"] == 18
    assert row["n_negative"] == 2
    assert row["p_value"] < 0.01

    row = agreement.loc[agreement["weekday"].eq("火")].iloc[0]
    assert row["agreement_rate"] == pytest.approx(0.5)
    assert row["p_value"] == pytest.approx(1.0)

    row = agreement.loc[agreement["weekday"].eq("水")].iloc[0]
    assert pd.isna(row["p_value"])
    assert "insufficient machines" in str(row["note"])


def test_apply_fdr_per_hall_preserves_nan_rows_and_adjusts_valid_rows() -> None:
    from eda import machine_weekday_cross_agreement_scan as analysis

    agreement = pd.DataFrame(
        [
            {
                "hall": "蒲田7",
                "weekday": "月",
                "n_machines": 10,
                "n_positive": 7,
                "n_negative": 3,
                "agreement_rate": 0.7,
                "mean_residual": 1.0,
                "median_residual": 1.0,
                "p_value": 0.001,
                "cohens_h": 0.3,
                "note": "",
            },
            {
                "hall": "蒲田7",
                "weekday": "火",
                "n_machines": 10,
                "n_positive": 6,
                "n_negative": 4,
                "agreement_rate": 0.6,
                "mean_residual": 0.5,
                "median_residual": 0.4,
                "p_value": 0.04,
                "cohens_h": 0.2,
                "note": "",
            },
            {
                "hall": "蒲田7",
                "weekday": "水",
                "n_machines": 10,
                "n_positive": 5,
                "n_negative": 5,
                "agreement_rate": 0.5,
                "mean_residual": 0.0,
                "median_residual": 0.0,
                "p_value": float("nan"),
                "cohens_h": float("nan"),
                "note": "skip",
            },
            {
                "hall": "蒲田1",
                "weekday": "月",
                "n_machines": 10,
                "n_positive": 8,
                "n_negative": 2,
                "agreement_rate": 0.8,
                "mean_residual": 1.5,
                "median_residual": 1.4,
                "p_value": 0.002,
                "cohens_h": 0.4,
                "note": "",
            },
            {
                "hall": "蒲田1",
                "weekday": "火",
                "n_machines": 10,
                "n_positive": 5,
                "n_negative": 5,
                "agreement_rate": 0.5,
                "mean_residual": 0.1,
                "median_residual": 0.1,
                "p_value": float("nan"),
                "cohens_h": float("nan"),
                "note": "skip",
            },
        ]
    )

    result = analysis.apply_fdr_per_hall(agreement, fdr_alpha=0.05)

    assert pd.isna(result.loc[result["weekday"].eq("水") & result["hall"].eq("蒲田7"), "q_value"]).all()
    assert pd.isna(result.loc[result["weekday"].eq("火") & result["hall"].eq("蒲田1"), "q_value"]).all()

    hall7 = result.loc[result["hall"].eq("蒲田7") & result["p_value"].notna()]
    _, expected_q, _, _ = multipletests(hall7["p_value"].to_numpy(), method="fdr_bh")
    assert hall7["q_value"].to_numpy() == pytest.approx(expected_q)

    hall1 = result.loc[result["hall"].eq("蒲田1") & result["p_value"].notna()]
    _, expected_q1, _, _ = multipletests(hall1["p_value"].to_numpy(), method="fdr_bh")
    assert hall1["q_value"].to_numpy() == pytest.approx(expected_q1)


def test_attach_weekday_coverage_flags_known_weekend_days() -> None:
    from eda import machine_weekday_cross_agreement_scan as analysis

    agreement = pd.DataFrame(
        [
            {
                "hall": "蒲田7",
                "weekday": "土",
                "n_machines": 3,
                "n_positive": 2,
                "n_negative": 1,
                "agreement_rate": 0.67,
                "mean_residual": 1.0,
                "median_residual": 1.0,
                "p_value": 0.01,
                "cohens_h": 0.2,
                "note": "",
                "q_value": 0.01,
                "is_significant": True,
            },
            {
                "hall": "蒲田7",
                "weekday": "月",
                "n_machines": 3,
                "n_positive": 1,
                "n_negative": 2,
                "agreement_rate": 0.33,
                "mean_residual": -1.0,
                "median_residual": -1.0,
                "p_value": 0.2,
                "cohens_h": -0.2,
                "note": "",
                "q_value": 0.2,
                "is_significant": False,
            },
        ]
    )
    hall_frames = {
        "蒲田7": pd.DataFrame(
            {
                "day_of_week": ["土", "土", "月", "月"],
                "is_weekend": [1, 1, 0, 0],
            }
        )
    }

    result = analysis.attach_weekday_coverage(agreement, hall_frames, known_event_threshold=0.5)

    row1 = result.loc[result["weekday"].eq("土")].iloc[0]
    row2 = result.loc[result["weekday"].eq("月")].iloc[0]
    assert row1["weekday_event_coverage_rate"] == pytest.approx(1.0)
    assert bool(row1["is_known_weekend_day"]) is True
    assert row2["weekday_event_coverage_rate"] == pytest.approx(0.0)
    assert bool(row2["is_known_weekend_day"]) is False


def test_build_summary_report_orders_top_positive_machines_and_truncates() -> None:
    from eda import machine_weekday_cross_agreement_scan as analysis

    agreement = pd.DataFrame(
        [
            {
                "hall": "蒲田7",
                "weekday": "土",
                "n_machines": 6,
                "n_positive": 6,
                "n_negative": 0,
                "agreement_rate": 1.0,
                "mean_residual": 5.0,
                "median_residual": 5.0,
                "p_value": 0.001,
                "cohens_h": 0.9,
                "note": "",
                "q_value": 0.002,
                "is_significant": True,
                "weekday_event_coverage_rate": 0.0,
                "is_known_weekend_day": False,
            },
            {
                "hall": "蒲田7",
                "weekday": "月",
                "n_machines": 3,
                "n_positive": 1,
                "n_negative": 2,
                "agreement_rate": 0.33,
                "mean_residual": 1.0,
                "median_residual": 1.0,
                "p_value": 0.2,
                "cohens_h": 0.1,
                "note": "",
                "q_value": 0.2,
                "is_significant": False,
                "weekday_event_coverage_rate": 1.0,
                "is_known_weekend_day": True,
            },
        ]
    )
    residuals = pd.DataFrame(
        [
            {
                "hall": "蒲田7",
                "machine_name": "alpha",
                "weekday": "土",
                "n": 10,
                "hit104_rate": 110.0,
                "baseline_hit104_rate": 100.0,
                "residual": 9.1,
            },
            {
                "hall": "蒲田7",
                "machine_name": "beta",
                "weekday": "土",
                "n": 10,
                "hit104_rate": 109.0,
                "baseline_hit104_rate": 100.0,
                "residual": 8.2,
            },
            {
                "hall": "蒲田7",
                "machine_name": "gamma",
                "weekday": "土",
                "n": 10,
                "hit104_rate": 108.0,
                "baseline_hit104_rate": 100.0,
                "residual": 7.3,
            },
            {
                "hall": "蒲田7",
                "machine_name": "delta",
                "weekday": "土",
                "n": 10,
                "hit104_rate": 107.0,
                "baseline_hit104_rate": 100.0,
                "residual": 6.4,
            },
            {
                "hall": "蒲田7",
                "machine_name": "epsilon",
                "weekday": "土",
                "n": 10,
                "hit104_rate": 106.0,
                "baseline_hit104_rate": 100.0,
                "residual": 5.5,
            },
            {
                "hall": "蒲田7",
                "machine_name": "zeta",
                "weekday": "土",
                "n": 10,
                "hit104_rate": 105.0,
                "baseline_hit104_rate": 100.0,
                "residual": 4.6,
            },
        ]
    )

    summary = analysis.build_summary_report(agreement, residuals)

    assert list(summary["weekday"]) == ["土"]
    text = summary.loc[0, "top_positive_machines"]
    assert text.startswith("alpha(+9.1);beta(+8.2);gamma(+7.3);delta(+6.4);epsilon(+5.5)")
    assert text.endswith("...(他1件)")


def test_attach_pooled_stats_merges_on_hall_and_weekday() -> None:
    from eda import machine_weekday_cross_agreement_scan as analysis

    agreement = pd.DataFrame(
        [
            {
                "hall": "蒲田7",
                "weekday": "土",
                "n_machines": 20,
                "n_positive": 14,
                "n_negative": 6,
                "agreement_rate": 0.7,
                "mean_residual": 3.0,
                "median_residual": 3.0,
                "p_value": 0.01,
                "cohens_h": 0.3,
                "note": "",
                "q_value": 0.01,
                "is_significant": True,
                "weekday_event_coverage_rate": 1.0,
                "is_known_weekend_day": True,
            },
        ]
    )
    hall_frames = {
        "蒲田7": pd.DataFrame(
            {"day_of_week": ["土", "土", "月"], "hit104": [1, 0, 0], "diff": [500.0, -100.0, -200.0]}
        ),
    }

    result = analysis.attach_pooled_stats(agreement, hall_frames)

    assert "pooled_hit104_rate_vs_hall" in result.columns
    assert not result.loc[0, "pooled_hit104_rate_vs_hall"] != result.loc[0, "pooled_hit104_rate_vs_hall"]


def test_attach_machine_category_fills_unknown_for_unmatched(monkeypatch: pytest.MonkeyPatch) -> None:
    from eda import machine_weekday_cross_agreement_scan as analysis

    residuals = pd.DataFrame(
        [
            {
                "hall": "蒲田7",
                "machine_name": "juggler_girls",
                "weekday": "土",
                "n": 10,
                "hit104_rate": 50.0,
                "baseline_hit104_rate": 40.0,
                "residual": 10.0,
            },
            {
                "hall": "蒲田7",
                "machine_name": "unlisted_machine",
                "weekday": "土",
                "n": 10,
                "hit104_rate": 30.0,
                "baseline_hit104_rate": 35.0,
                "residual": -5.0,
            },
        ]
    )

    monkeypatch.setattr(
        analysis,
        "load_machine_categories",
        lambda hall: pd.DataFrame({"machine_name": ["juggler_girls"], "category": ["jug"]}),
    )

    result = analysis.attach_machine_category(residuals, "蒲田7")

    assert result.loc[result["machine_name"].eq("juggler_girls"), "category"].iloc[0] == "jug"
    assert result.loc[result["machine_name"].eq("unlisted_machine"), "category"].iloc[0] == analysis.UNKNOWN_CATEGORY


def test_build_category_breakdown_restricted_to_agreement_pairs() -> None:
    from eda import machine_weekday_cross_agreement_scan as analysis

    residuals = pd.DataFrame(
        [
            {
                "hall": "蒲田7",
                "machine_name": "j1",
                "weekday": "土",
                "n": 10,
                "hit104_rate": 50.0,
                "baseline_hit104_rate": 40.0,
                "residual": 10.0,
                "category": "jug",
            },
            {
                "hall": "蒲田7",
                "machine_name": "j2",
                "weekday": "土",
                "n": 10,
                "hit104_rate": 45.0,
                "baseline_hit104_rate": 40.0,
                "residual": 5.0,
                "category": "jug",
            },
            {
                "hall": "蒲田7",
                "machine_name": "o1",
                "weekday": "土",
                "n": 10,
                "hit104_rate": 35.0,
                "baseline_hit104_rate": 40.0,
                "residual": -5.0,
                "category": "other",
            },
            {
                "hall": "蒲田7",
                "machine_name": "j3",
                "weekday": "月",
                "n": 10,
                "hit104_rate": 50.0,
                "baseline_hit104_rate": 40.0,
                "residual": 10.0,
                "category": "jug",
            },
        ]
    )
    agreement = pd.DataFrame([{"hall": "蒲田7", "weekday": "土", "is_significant": True}])

    breakdown = analysis.build_category_breakdown(residuals, agreement)

    assert set(breakdown["weekday"].unique()) == {"土"}
    jug_row = breakdown.loc[breakdown["category"].eq("jug")].iloc[0]
    assert jug_row["n_machines"] == 2
    assert jug_row["n_positive"] == 2
    other_row = breakdown.loc[breakdown["category"].eq("other")].iloc[0]
    assert other_row["n_machines"] == 1
    assert other_row["n_positive"] == 0


def test_compute_dominant_category_robustness_detects_concentration() -> None:
    from eda import machine_weekday_cross_agreement_scan as analysis

    rows: list[dict[str, object]] = []
    for i in range(18):
        rows.append(
            {
                "hall": "蒲田7",
                "machine_name": f"jug{i}",
                "weekday": "土",
                "n": 10,
                "hit104_rate": 50.0,
                "baseline_hit104_rate": 40.0,
                "residual": 10.0,
                "category": "jug",
            }
        )
    for i in range(10):
        residual = 1.0 if i < 5 else -1.0
        rows.append(
            {
                "hall": "蒲田7",
                "machine_name": f"oth{i}",
                "weekday": "土",
                "n": 10,
                "hit104_rate": 41.0,
                "baseline_hit104_rate": 40.0,
                "residual": residual,
                "category": "other",
            }
        )
    residuals = pd.DataFrame(rows)

    agreement = pd.DataFrame(
        [
            {
                "hall": "蒲田7",
                "weekday": "土",
                "n_machines": 28,
                "n_positive": 23,
                "agreement_rate": 23 / 28,
                "is_significant": True,
            },
        ]
    )

    robustness = analysis.compute_dominant_category_robustness(
        residuals, agreement, min_machines_for_test=10, fdr_alpha=0.05
    )

    row = robustness.iloc[0]
    assert row["dominant_category"] == "jug"
    assert row["dominant_category_share_of_majority"] == pytest.approx(18 / 23)
    assert row["n_machines_excl_dominant"] == 10
    assert row["agreement_rate_excl_dominant"] == pytest.approx(0.5)
    assert bool(row["signal_survives_without_dominant_category"]) is False


def test_merge_robustness_into_summary_overwrites_placeholder_columns() -> None:
    from eda import machine_weekday_cross_agreement_scan as analysis

    summary = pd.DataFrame(
        [
            {
                "hall": "蒲田7",
                "weekday": "土",
                "n_machines": 20,
                "n_positive": 14,
                "agreement_rate": 0.7,
                "mean_residual": 3.0,
                "q_value": 0.01,
                "cohens_h": 0.3,
                "is_known_weekend_day": True,
                "is_novel": False,
                "pooled_hit104_rate_vs_hall": 2.0,
                "pooled_diff_vs_hall": 100.0,
                "dominant_category": "",
                "dominant_category_share_of_majority": float("nan"),
                "agreement_rate_excl_dominant": float("nan"),
                "p_value_excl_dominant": float("nan"),
                "signal_survives_without_dominant_category": False,
                "top_positive_machines": "a(+1.0)",
            }
        ]
    )
    robustness = pd.DataFrame(
        [
            {
                "hall": "蒲田7",
                "weekday": "土",
                "dominant_category": "jug",
                "dominant_category_share_of_majority": 0.8,
                "n_machines_excl_dominant": 10,
                "n_positive_excl_dominant": 5,
                "agreement_rate_excl_dominant": 0.5,
                "p_value_excl_dominant": 1.0,
                "signal_survives_without_dominant_category": False,
                "note": "",
            }
        ]
    )

    merged = analysis.merge_robustness_into_summary(summary, robustness)

    assert merged.loc[0, "dominant_category"] == "jug"
    assert merged.loc[0, "dominant_category_share_of_majority"] == pytest.approx(0.8)
    assert merged.loc[0, "top_positive_machines"] == "a(+1.0)"


def test_main_writes_requested_csvs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from eda import machine_weekday_cross_agreement_scan as analysis

    raw = pd.DataFrame(
        [
            _make_row("20260101", 101, "machine_a", 500, day_of_week="月", is_weekend=0),
            _make_row("20260102", 101, "machine_a", 300, day_of_week="土", is_weekend=1),
            _make_row("20260101", 102, "machine_b", 200, day_of_week="月", is_weekend=0),
            _make_row("20260102", 102, "machine_b", -100, day_of_week="土", is_weekend=1),
            _make_row("20260101", 103, "machine_c", 100, day_of_week="月", is_weekend=0),
            _make_row("20260102", 103, "machine_c", 100, day_of_week="土", is_weekend=1),
            _make_row("20260101", 104, "machine_d", 600, day_of_week="月", is_weekend=0),
            _make_row("20260102", 104, "machine_d", 300, day_of_week="土", is_weekend=1),
            _make_row("20260101", 105, "machine_e", 700, day_of_week="月", is_weekend=0),
            _make_row("20260102", 105, "machine_e", 400, day_of_week="土", is_weekend=1),
            _make_row("20260101", 106, "machine_f", 800, day_of_week="月", is_weekend=0),
            _make_row("20260102", 106, "machine_f", 500, day_of_week="土", is_weekend=1),
            _make_row("20260101", 107, "machine_g", 900, day_of_week="月", is_weekend=0),
            _make_row("20260102", 107, "machine_g", 600, day_of_week="土", is_weekend=1),
            _make_row("20260101", 108, "machine_h", 1000, day_of_week="月", is_weekend=0),
            _make_row("20260102", 108, "machine_h", 700, day_of_week="土", is_weekend=1),
        ]
    )

    def fake_prepare_frame(frame, *, shindai_exclude_days):
        prepared = frame.copy()
        prepared["plus"] = (prepared["diff"] > 0).astype(int)
        prepared["day_of_week"] = prepared["day_of_week"].astype(str)
        prepared["is_weekend"] = pd.to_numeric(prepared["is_weekend"], errors="coerce").fillna(0).astype(int)
        return prepared

    monkeypatch.setattr(analysis, "HALL_DBS", {"蒲田7": "fake.db"})
    monkeypatch.setattr(analysis, "load_hall_df", lambda hall: raw.copy())
    monkeypatch.setattr(analysis, "_prepare_frame", fake_prepare_frame)
    monkeypatch.setattr(
        analysis,
        "build_weekday_hall_outputs",
        lambda hall, raw, **kwargs: {
            "residuals": pd.DataFrame(
                [
                    {
                        "hall": "蒲田7",
                        "machine_name": "shared",
                        "weekday": "月",
                        "n": 10,
                        "hit104_rate": 50.0,
                        "baseline_hit104_rate": 40.0,
                        "residual": 10.0,
                        "category": "jug",
                    },
                ]
            ),
            "agreement": pd.DataFrame(
                [
                    {
                        "hall": "蒲田7",
                        "weekday": "月",
                        "n_machines": 1,
                        "n_positive": 1,
                        "n_negative": 0,
                        "agreement_rate": 1.0,
                        "mean_residual": 10.0,
                        "median_residual": 10.0,
                        "p_value": 0.01,
                        "cohens_h": 0.2,
                        "note": "",
                        "q_value": 0.01,
                        "is_significant": True,
                        "weekday_event_coverage_rate": 0.0,
                        "is_known_weekend_day": False,
                    },
                ]
            ),
            "category_breakdown": pd.DataFrame(),
            "robustness": pd.DataFrame(),
            "summary": pd.DataFrame(
                [
                    {
                        "hall": "蒲田7",
                        "weekday": "月",
                        "n_machines": 1,
                        "n_positive": 1,
                        "agreement_rate": 1.0,
                        "mean_residual": 10.0,
                        "q_value": 0.01,
                        "cohens_h": 0.2,
                        "is_known_weekend_day": False,
                        "is_novel": True,
                        "pooled_hit104_rate_vs_hall": 0.0,
                        "pooled_diff_vs_hall": 0.0,
                        "dominant_category": "",
                        "dominant_category_share_of_majority": float("nan"),
                        "agreement_rate_excl_dominant": float("nan"),
                        "p_value_excl_dominant": float("nan"),
                        "signal_survives_without_dominant_category": False,
                        "top_positive_machines": "shared(+10.0)",
                    },
                ]
            ),
        },
    )

    exit_code = analysis.main(
        [
            "--halls",
            "蒲田7",
            "--output-dir",
            str(tmp_path),
        ]
    )

    assert exit_code == 0
    assert (tmp_path / "蒲田7_machine_weekday_residuals.csv").exists()
    assert (tmp_path / "蒲田7_weekday_agreement.csv").exists()
    assert (tmp_path / "蒲田7_category_breakdown.csv").exists()
    assert (tmp_path / "蒲田7_category_robustness.csv").exists()
    assert (tmp_path / "summary_report.csv").exists()
