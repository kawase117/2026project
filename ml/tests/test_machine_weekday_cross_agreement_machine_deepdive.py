from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest
from statsmodels.stats.multitest import multipletests


def _make_residual_row(
    hall: str,
    weekday: str,
    machine_name: str,
    residual: float,
    *,
    n: int = 10,
    category: str = "other",
    hit104_rate: float | None = None,
    baseline_hit104_rate: float = 40.0,
) -> dict[str, object]:
    if hit104_rate is None:
        hit104_rate = baseline_hit104_rate + residual
    return {
        "hall": hall,
        "weekday": weekday,
        "machine_name": machine_name,
        "category": category,
        "n": n,
        "hit104_rate": hit104_rate,
        "baseline_hit104_rate": baseline_hit104_rate,
        "residual": residual,
    }


def test_build_full_machine_ranking_keeps_all_machines_and_orders_ranks() -> None:
    from eda import machine_weekday_cross_agreement_machine_deepdive as analysis

    residuals = pd.DataFrame(
        [
            _make_residual_row("蒲田7", "月", "m1", 9.0, category="jug"),
            _make_residual_row("蒲田7", "月", "m2", 7.0, category="other"),
            _make_residual_row("蒲田7", "月", "m3", 5.0, category="other"),
            _make_residual_row("蒲田7", "月", "m4", 3.0, category="other"),
            _make_residual_row("蒲田7", "月", "m5", 1.0, category="other"),
            _make_residual_row("蒲田7", "月", "m6", -1.0, category="other"),
        ]
    )
    summary = pd.DataFrame([{"hall": "蒲田7", "weekday": "月", "is_novel": True}])

    ranking = analysis.build_full_machine_ranking(residuals, summary)

    assert len(ranking) == 6
    assert list(ranking["machine_name"]) == ["m1", "m2", "m3", "m4", "m5", "m6"]
    assert list(ranking["rank_desc"]) == [1, 2, 3, 4, 5, 6]
    assert list(ranking.sort_values("rank_asc")["machine_name"]) == ["m6", "m5", "m4", "m3", "m2", "m1"]
    assert list(ranking.sort_values("rank_asc")["rank_asc"]) == [1, 2, 3, 4, 5, 6]


def test_compute_machine_weekday_self_significance_finds_weekday_specific_shift_and_skips_small_cells() -> None:
    from eda import machine_weekday_cross_agreement_machine_deepdive as analysis

    rows: list[dict[str, object]] = []
    for i in range(8):
        rows.append({"hall": "蒲田7", "day_of_week": "月", "machine_name": "strong", "hit104": 1})
    for i in range(12):
        rows.append({"hall": "蒲田7", "day_of_week": "火", "machine_name": "strong", "hit104": 0 if i < 10 else 1})
    for i in range(20):
        rows.append({"hall": "蒲田7", "day_of_week": "月", "machine_name": "skip_me", "hit104": 1 if i % 2 == 0 else 0})
    for i in range(20):
        rows.append({"hall": "蒲田7", "day_of_week": "火", "machine_name": "skip_me", "hit104": 0 if i % 2 == 0 else 1})

    frame = pd.DataFrame(rows)

    result = analysis.compute_machine_weekday_self_significance(
        "蒲田7",
        frame,
        {"月"},
        min_machine_days_total=10,
        min_cell_n=5,
    )

    assert set(result["machine_name"]) == {"strong", "skip_me"}
    strong = result.loc[result["machine_name"].eq("strong")].iloc[0]
    assert strong["n_at_weekday"] == 8
    assert strong["p_value"] < 0.01

    skip_frame = pd.DataFrame(rows[:4])
    skipped = analysis.compute_machine_weekday_self_significance(
        "蒲田7",
        skip_frame,
        {"月"},
        min_machine_days_total=10,
        min_cell_n=5,
    )
    assert skipped.empty


def test_apply_fdr_per_hall_weekday_is_independent_by_hall_and_weekday() -> None:
    from eda import machine_weekday_cross_agreement_machine_deepdive as analysis

    self_sig = pd.DataFrame(
        [
            {
                "hall": "蒲田7",
                "weekday": "月",
                "machine_name": "a",
                "n_at_weekday": 10,
                "hits_at_weekday": 9,
                "hit104_rate_at_weekday": 0.9,
                "n_rest": 20,
                "rest_hit104_rate": 0.2,
                "p_value": 0.001,
            },
            {
                "hall": "蒲田7",
                "weekday": "月",
                "machine_name": "b",
                "n_at_weekday": 10,
                "hits_at_weekday": 7,
                "hit104_rate_at_weekday": 0.7,
                "n_rest": 20,
                "rest_hit104_rate": 0.2,
                "p_value": 0.04,
            },
            {
                "hall": "蒲田7",
                "weekday": "火",
                "machine_name": "c",
                "n_at_weekday": 10,
                "hits_at_weekday": 5,
                "hit104_rate_at_weekday": 0.5,
                "n_rest": 20,
                "rest_hit104_rate": 0.5,
                "p_value": float("nan"),
            },
            {
                "hall": "蒲田1",
                "weekday": "月",
                "machine_name": "d",
                "n_at_weekday": 10,
                "hits_at_weekday": 8,
                "hit104_rate_at_weekday": 0.8,
                "n_rest": 20,
                "rest_hit104_rate": 0.3,
                "p_value": 0.002,
            },
            {
                "hall": "蒲田1",
                "weekday": "火",
                "machine_name": "e",
                "n_at_weekday": 10,
                "hits_at_weekday": 5,
                "hit104_rate_at_weekday": 0.5,
                "n_rest": 20,
                "rest_hit104_rate": 0.5,
                "p_value": float("nan"),
            },
        ]
    )

    result = analysis.apply_fdr_per_hall_weekday(self_sig, fdr_alpha=0.05)

    assert pd.isna(result.loc[result["machine_name"].eq("c"), "q_value"]).all()
    assert pd.isna(result.loc[result["machine_name"].eq("e"), "q_value"]).all()

    hall7 = result.loc[result["hall"].eq("蒲田7") & result["p_value"].notna()]
    _, expected_q7, _, _ = multipletests(hall7["p_value"].to_numpy(), method="fdr_bh")
    assert hall7["q_value"].to_numpy() == pytest.approx(expected_q7)

    hall1 = result.loc[result["hall"].eq("蒲田1") & result["p_value"].notna()]
    _, expected_q1, _, _ = multipletests(hall1["p_value"].to_numpy(), method="fdr_bh")
    assert hall1["q_value"].to_numpy() == pytest.approx(expected_q1)


def test_find_repeat_contributors_tracks_multiple_weekdays() -> None:
    from eda import machine_weekday_cross_agreement_machine_deepdive as analysis

    rows: list[dict[str, object]] = []
    for weekday, residual in [("月", 9.0), ("火", 8.0), ("水", 7.0)]:
        rows.append(
            {
                "hall": "蒲田7",
                "weekday": weekday,
                "is_novel": True,
                "machine_name": "steady",
                "category": "jug",
                "n": 10,
                "hit104_rate": 80.0 + residual,
                "baseline_hit104_rate": 80.0,
                "residual": residual,
                "rank_desc": 1,
                "rank_asc": 5,
                "p_value": 0.001,
                "q_value": 0.002,
                "is_machine_significant": True,
            }
        )
        rows.append(
            {
                "hall": "蒲田7",
                "weekday": weekday,
                "is_novel": True,
                "machine_name": f"oneoff{weekday}",
                "category": "other",
                "n": 10,
                "hit104_rate": 79.0,
                "baseline_hit104_rate": 80.0,
                "residual": -1.0,
                "rank_desc": 4,
                "rank_asc": 1,
                "p_value": 0.2,
                "q_value": 0.3,
                "is_machine_significant": False,
            }
        )

    ranking = pd.DataFrame(rows)
    repeat = analysis.find_repeat_contributors(ranking, top_n=2)

    assert set(repeat["machine_name"]) == {"steady"}
    row = repeat.iloc[0]
    assert row["n_appearances"] == 3
    assert row["weekdays_appeared"] == "月;火;水"
    assert row["n_machine_significant_appearances"] == 3


def test_find_cross_hall_consistency_records_exact_and_mismatch_weekdays() -> None:
    from eda import machine_weekday_cross_agreement_machine_deepdive as analysis

    ranking = pd.DataFrame(
        [
            {
                "hall": "蒲田7",
                "weekday": "月",
                "is_novel": True,
                "machine_name": "shared",
                "category": "jug",
                "n": 10,
                "hit104_rate": 90.0,
                "baseline_hit104_rate": 80.0,
                "residual": 10.0,
                "rank_desc": 1,
                "rank_asc": 5,
                "p_value": 0.001,
                "q_value": 0.01,
                "is_machine_significant": True,
            },
            {
                "hall": "蒲田1",
                "weekday": "月",
                "is_novel": True,
                "machine_name": "shared",
                "category": "jug",
                "n": 10,
                "hit104_rate": 89.0,
                "baseline_hit104_rate": 80.0,
                "residual": 9.0,
                "rank_desc": 2,
                "rank_asc": 4,
                "p_value": 0.002,
                "q_value": 0.02,
                "is_machine_significant": True,
            },
            {
                "hall": "蒲田7",
                "weekday": "火",
                "is_novel": True,
                "machine_name": "mismatch",
                "category": "other",
                "n": 10,
                "hit104_rate": 79.0,
                "baseline_hit104_rate": 80.0,
                "residual": -1.0,
                "rank_desc": 4,
                "rank_asc": 1,
                "p_value": 0.2,
                "q_value": 0.3,
                "is_machine_significant": False,
            },
            {
                "hall": "蒲田1",
                "weekday": "水",
                "is_novel": True,
                "machine_name": "mismatch",
                "category": "other",
                "n": 10,
                "hit104_rate": 78.0,
                "baseline_hit104_rate": 80.0,
                "residual": -2.0,
                "rank_desc": 5,
                "rank_asc": 2,
                "p_value": 0.2,
                "q_value": 0.3,
                "is_machine_significant": False,
            },
        ]
    )

    cross = analysis.find_cross_hall_consistency(ranking)

    shared = cross.loc[cross["machine_name"].eq("shared")].iloc[0]
    assert shared["n_halls"] == 2
    assert shared["weekday_matches_across_halls"] == "月"

    mismatch = cross.loc[cross["machine_name"].eq("mismatch")].iloc[0]
    assert mismatch["n_halls"] == 2
    assert mismatch["weekday_matches_across_halls"] == ""


def test_main_writes_requested_csvs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from eda import machine_weekday_cross_agreement_machine_deepdive as analysis

    fake_outputs = {
        "蒲田7": {
            "residuals": pd.DataFrame(
                [
                    _make_residual_row("蒲田7", "月", "shared", 9.0, category="jug"),
                    _make_residual_row("蒲田7", "月", "other1", -1.0, category="other"),
                    _make_residual_row("蒲田7", "火", "shared", 8.0, category="jug"),
                    _make_residual_row("蒲田7", "火", "other2", -2.0, category="other"),
                ]
            ),
            "summary": pd.DataFrame(
                [
                    {"hall": "蒲田7", "weekday": "月", "is_novel": True},
                    {"hall": "蒲田7", "weekday": "火", "is_novel": False},
                ]
            ),
        }
    }

    def fake_load_hall_df(hall):
        return pd.DataFrame({"hall": [hall]})

    def fake_prepare_frame(raw, *, shindai_exclude_days):
        return pd.DataFrame(
            {
                "hall": ["蒲田7", "蒲田7", "蒲田7", "蒲田7"],
                "machine_name": ["shared", "shared", "other1", "other2"],
                "day_of_week": ["月", "火", "月", "火"],
                "hit104": [1, 1, 0, 0],
            }
        )

    def fake_build_weekday_hall_outputs(
        hall, raw, *, min_machine_days_total, min_cell_n, min_machines_for_test, fdr_alpha, known_event_threshold
    ):
        residuals = fake_outputs[hall]["residuals"].copy()
        summary = fake_outputs[hall]["summary"].copy()
        return {
            "residuals": residuals,
            "agreement": pd.DataFrame(),
            "category_breakdown": pd.DataFrame(),
            "robustness": pd.DataFrame(),
            "summary": summary,
        }

    monkeypatch.setattr(analysis, "HALL_DBS", {"蒲田7": "fake.db"})
    monkeypatch.setattr(analysis, "load_hall_df", fake_load_hall_df)
    monkeypatch.setattr(analysis, "_prepare_frame", fake_prepare_frame)
    monkeypatch.setattr(analysis, "build_weekday_hall_outputs", fake_build_weekday_hall_outputs)

    exit_code = analysis.main(
        [
            "--halls",
            "蒲田7",
            "--output-dir",
            str(tmp_path),
            "--top-n",
            "2",
        ]
    )

    assert exit_code == 0
    assert (tmp_path / "蒲田7_full_ranking.csv").exists()
    assert (tmp_path / "repeat_contributors.csv").exists()
    assert (tmp_path / "cross_hall_consistency.csv").exists()
