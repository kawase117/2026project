from __future__ import annotations

import sqlite3
from pathlib import Path

import pandas as pd
import pytest

from ml.analysis import kamata_corner_mirror_analysis as analysis_mod
from ml.analysis.kamata_corner_mirror_analysis import (
    assign_kakuban,
    build_axis_profile,
    build_grid_profile,
    compare_profile_series,
    HallSpec,
    compute_machine_residuals,
    compute_machine_metric_residuals,
    compute_kakuban_dispersion_test,
    infer_hall_name,
    load_hall_frame,
    load_hall_daily_frame,
    summarize_floor_segment_kakuban_cat3,
    summarize_floor_segment_kakuban_epsilon,
    summarize_section_kakuban_cat3,
    summarize_section_kakuban_epsilon,
    summarize_section_kakuban_fixed_effects,
    summarize_kakuban_correlations,
    summarize_sensitivity_stability,
)


def test_compute_machine_residuals_uses_machine_name_mean_within_hall() -> None:
    frame = pd.DataFrame(
        {
            "hall_name": ["Hall"] * 4,
            "machine_number": [1, 2, 3, 4],
            "machine_name": ["A", "A", "B", "B"],
            "diff_coins_normalized": [10.0, 14.0, 20.0, 30.0],
        }
    )

    out = compute_machine_residuals(frame)

    assert out["machine_name_mean_diff"].tolist() == [12.0, 12.0, 25.0, 25.0]
    assert out["residual_diff"].tolist() == [-2.0, 2.0, -5.0, 5.0]


def test_compute_machine_metric_residuals_adds_residual_games() -> None:
    frame = pd.DataFrame(
        {
            "hall_name": ["Hall"] * 4,
            "machine_number": [1, 2, 3, 4],
            "machine_name": ["A", "A", "B", "B"],
            "games_normalized": [100.0, 140.0, 200.0, 260.0],
        }
    )

    out = compute_machine_metric_residuals(
        frame,
        metric_col="games_normalized",
        mean_col="machine_name_mean_games",
        residual_col="residual_games",
    )

    assert out["machine_name_mean_games"].tolist() == [120.0, 120.0, 230.0, 230.0]
    assert out["residual_games"].tolist() == [-20.0, 20.0, -30.0, 30.0]


def test_build_axis_profile_prefers_reflected_x_when_series_is_mirrored() -> None:
    hall1 = pd.DataFrame(
        {
            "machine_number": [1, 2, 3, 4],
            "x_norm": [0.125, 0.375, 0.625, 0.875],
            "y_norm": [0.25, 0.25, 0.25, 0.25],
            "residual_diff": [1.0, 2.0, 3.0, 4.0],
        }
    )
    hall7 = pd.DataFrame(
        {
            "machine_number": [11, 12, 13, 14],
            "x_norm": [0.125, 0.375, 0.625, 0.875],
            "y_norm": [0.25, 0.25, 0.25, 0.25],
            "residual_diff": [4.0, 3.0, 2.0, 1.0],
        }
    )

    forward_1 = build_axis_profile(hall1, bins=4)
    forward_7 = build_axis_profile(hall7, bins=4)
    reflected_7 = build_axis_profile(hall7, bins=4, reflect_x=True)

    forward_corr = compare_profile_series(forward_1["zscore"], forward_7["zscore"])
    reflected_corr = compare_profile_series(forward_1["zscore"], reflected_7["zscore"])

    assert forward_corr == pytest.approx(-1.0)
    assert reflected_corr == pytest.approx(1.0)


def test_build_axis_profile_exposes_sample_counts_per_bin() -> None:
    frame = pd.DataFrame(
        {
            "machine_number": [1, 2, 3, 4],
            "x_norm": [0.125, 0.375, 0.625, 0.875],
            "y_norm": [0.25, 0.25, 0.25, 0.25],
            "residual_diff": [1.0, 2.0, 3.0, 4.0],
        }
    )

    profile = build_axis_profile(frame, bins=4)

    assert "sample_count" in profile.columns
    assert profile["sample_count"].tolist() == [1, 1, 1, 1]
    assert profile["machine_count"].tolist() == [1, 1, 1, 1]


def test_summarize_sensitivity_stability_flags_supported_mirror_case() -> None:
    hall1 = pd.DataFrame(
        {
            "machine_number": [1, 2, 3, 4],
            "x_norm": [0.125, 0.375, 0.625, 0.875],
            "y_norm": [0.25, 0.25, 0.25, 0.25],
            "residual_diff": [1.0, 2.0, 3.0, 4.0],
        }
    )
    hall7 = pd.DataFrame(
        {
            "machine_number": [11, 12, 13, 14],
            "x_norm": [0.125, 0.375, 0.625, 0.875],
            "y_norm": [0.25, 0.25, 0.25, 0.25],
            "residual_diff": [4.0, 3.0, 2.0, 1.0],
        }
    )

    detail, summary = summarize_sensitivity_stability(
        hall1_all=hall1,
        hall7_all=hall7,
        hall1_common=hall1,
        hall7_common=hall7,
        axis_bins=(4,),
        grid_sizes=(),
        min_corr_gap=0.10,
        min_support_rate=0.75,
    )

    assert detail.shape[0] == 2
    assert set(detail["period"]) == {"all", "common"}
    assert detail["support_flag"].tolist() == [1, 1]
    assert summary["support_rate"].tolist() == [1.0, 1.0]
    assert summary["sign_consistency_rate"].tolist() == [1.0, 1.0]
    assert summary["stability_score"].tolist() == [1.0, 1.0]
    assert summary["mirror_candidate"].tolist() == [True, True]


def test_assign_kakuban_uses_hall_specific_anchor_rules() -> None:
    kamata1 = pd.read_csv("Heatmap/2F_floor_coordinates_kamata1.csv")
    kamata7_2f = pd.read_csv("Heatmap/2F_floor_coordinates_kamata7.csv")
    kamata7_3f = pd.read_csv("Heatmap/3F_floor_coordinates_kamata7.csv")

    out_1 = assign_kakuban(
        kamata1[kamata1["section"].isin(["2001-2020", "2021-2031", "2203-2212", "2330-2351"])].copy(),
        hall_label="蒲田1",
        floor="2F",
    )
    assert out_1.loc[out_1["machine_number"].eq(2001), "kakuban"].iloc[0] == 1
    assert out_1.loc[out_1["machine_number"].eq(2020), "kakuban"].iloc[0] == 20
    assert out_1.loc[out_1["machine_number"].eq(2021), "kakuban"].iloc[0] == 1
    assert out_1.loc[out_1["machine_number"].eq(2023), "kakuban"].iloc[0] == 3
    assert out_1.loc[out_1["machine_number"].eq(2031), "kakuban"].iloc[0] == 11

    out_7_2f = assign_kakuban(
        kamata7_2f[kamata7_2f["section"].isin(["2001-2010", "2023-2031", "2187-2195", "2330-2351"])].copy(),
        hall_label="蒲田7",
        floor="2F",
    )
    assert out_7_2f.loc[out_7_2f["machine_number"].eq(2001), "kakuban"].iloc[0] == 1
    assert out_7_2f.loc[out_7_2f["machine_number"].eq(2010), "kakuban"].iloc[0] == 10
    assert out_7_2f.loc[out_7_2f["machine_number"].eq(2023), "kakuban"].iloc[0] == 1
    assert out_7_2f.loc[out_7_2f["machine_number"].eq(2031), "kakuban"].iloc[0] == 9
    assert out_7_2f.loc[out_7_2f["machine_number"].eq(2187), "kakuban"].iloc[0] == 1
    assert out_7_2f.loc[out_7_2f["machine_number"].eq(2195), "kakuban"].iloc[0] == 9
    assert out_7_2f.loc[out_7_2f["machine_number"].eq(2330), "kakuban"].iloc[0] == 22
    assert out_7_2f.loc[out_7_2f["machine_number"].eq(2351), "kakuban"].iloc[0] == 1

    out_7_3f = assign_kakuban(
        kamata7_3f[kamata7_3f["section"].isin(["3191-3208", "3209-3217", "3341-3362", "3400-3401"])].copy(),
        hall_label="蒲田7",
        floor="3F",
    )
    assert out_7_3f.loc[out_7_3f["machine_number"].eq(3191), "kakuban"].iloc[0] == 18
    assert out_7_3f.loc[out_7_3f["machine_number"].eq(3208), "kakuban"].iloc[0] == 1
    assert out_7_3f.loc[out_7_3f["machine_number"].eq(3209), "kakuban"].iloc[0] == 1
    assert out_7_3f.loc[out_7_3f["machine_number"].eq(3217), "kakuban"].iloc[0] == 9
    assert out_7_3f.loc[out_7_3f["machine_number"].eq(3341), "kakuban"].iloc[0] == 22
    assert out_7_3f.loc[out_7_3f["machine_number"].eq(3362), "kakuban"].iloc[0] == 1
    assert out_7_3f.loc[out_7_3f["machine_number"].isin([3400, 3401]), "excluded_from_corr"].all()


def test_load_hall_frame_inner_joins_and_filters_by_games(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "sample.db"
    coords_path = tmp_path / "coords.csv"

    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE machine_detailed_results (
                date TEXT,
                machine_number INTEGER,
                machine_name TEXT,
                diff_coins_normalized INTEGER,
                games_normalized INTEGER
            )
            """
        )
        conn.executemany(
            """
            INSERT INTO machine_detailed_results
            VALUES (?, ?, ?, ?, ?)
            """,
            [
                ("20260101", 1001, "Alpha", 10, 1600),
                ("20260102", 1001, "Alpha", 20, 1400),
                ("20260101", 1002, "Beta", 30, 1700),
            ],
        )
        conn.commit()

    coords_path.write_text(
        "\n".join(
            [
                "hall_name,floor,machine_number,X,Y,display_x,display_y",
                "Target Hall,2F,1001,10,1,10,1",
                "Target Hall,2F,1002,20,1,20,1",
            ]
        ),
        encoding="utf-8",
    )

    out = load_hall_frame(
        db_path=db_path,
        coords_path=coords_path,
        hall_name="Target Hall",
        floor="2F",
        min_games=1500,
    )

    assert out["machine_number"].tolist() == [1001, 1002]
    assert out["date"].dt.strftime("%Y%m%d").tolist() == ["20260101", "20260101"]
    assert out["machine_name_mean_diff"].tolist() == [10.0, 30.0]
    assert out["residual_diff"].tolist() == [0.0, 0.0]
    assert out["residual_games"].tolist() == [0.0, 0.0]
    assert out["x_norm"].tolist() == [0.0, 1.0]
    assert out["y_norm"].tolist() == [0.0, 0.0]


def test_load_hall_frame_can_filter_tuesdays(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "sample.db"
    coords_path = tmp_path / "coords.csv"

    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE machine_detailed_results (
                date TEXT,
                machine_number INTEGER,
                machine_name TEXT,
                diff_coins_normalized INTEGER,
                games_normalized INTEGER
            )
            """
        )
        conn.executemany(
            """
            INSERT INTO machine_detailed_results
            VALUES (?, ?, ?, ?, ?)
            """,
            [
                ("20260105", 1001, "Alpha", 10, 1600),
                ("20260106", 1001, "Alpha", 20, 1600),
            ],
        )
        conn.commit()

    coords_path.write_text(
        "\n".join(
            [
                "hall_name,floor,machine_number,X,Y,display_x,display_y",
                "Target Hall,2F,1001,10,1,10,1",
            ]
        ),
        encoding="utf-8",
    )

    out = load_hall_frame(
        db_path=db_path,
        coords_path=coords_path,
        hall_name="Target Hall",
        floor="2F",
        min_games=1500,
        weekday="Tuesday",
    )

    assert out["date"].dt.strftime("%Y%m%d").tolist() == ["20260106"]


def test_load_hall_frame_joins_machine_master_and_sets_machine_type_segment(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "sample.db"
    coords_path = tmp_path / "coords.csv"

    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE machine_detailed_results (
                date TEXT,
                machine_number INTEGER,
                machine_name TEXT,
                diff_coins_normalized INTEGER,
                games_normalized INTEGER
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE machine_master (
                machine_name_normalized TEXT,
                jug_flag INTEGER,
                hana_flag INTEGER,
                bt_flag INTEGER
            )
            """
        )
        conn.executemany(
            """
            INSERT INTO machine_detailed_results
            VALUES (?, ?, ?, ?, ?)
            """,
            [
                ("20260106", 1001, "Alpha", 10, 1600),
                ("20260106", 1002, "Beta", 20, 1600),
                ("20260106", 1003, "Gamma", 30, 1600),
            ],
        )
        conn.executemany(
            """
            INSERT INTO machine_master
            VALUES (?, ?, ?, ?)
            """,
            [
                ("Alpha", 1, 0, 0),
                ("Beta", 0, 0, 1),
            ],
        )
        conn.commit()

    coords_path.write_text(
        "\n".join(
            [
                "hall_name,floor,machine_number,X,Y,display_x,display_y",
                "Target Hall,2F,1001,10,1,10,1",
                "Target Hall,2F,1002,20,1,20,1",
                "Target Hall,2F,1003,30,1,30,1",
            ]
        ),
        encoding="utf-8",
    )

    out = load_hall_frame(
        db_path=db_path,
        coords_path=coords_path,
        hall_name="Target Hall",
        floor="2F",
        min_games=1500,
    )

    assert out["jug_flag"].tolist() == [1, 0, 0]
    assert out["hana_flag"].tolist() == [0, 0, 0]
    assert out["bt_flag"].tolist() == [0, 1, 0]
    assert out["machine_type_segment"].tolist() == ["A", "N", "N"]


def test_summarize_kakuban_correlations_emits_floor_and_segment_rows() -> None:
    frame = pd.DataFrame(
        {
            "machine_number": [1, 2, 3, 4],
            "kakuban": [1, 2, 1, 2],
            "residual_diff": [1.0, 2.0, 3.0, 4.0],
            "residual_games": [10.0, 20.0, 30.0, 40.0],
            "excluded_from_corr": [False, False, False, False],
            "machine_type_segment": ["A", "A", "N", "N"],
        }
    )

    out = summarize_kakuban_correlations(
        frames=[("蒲田7", "2F", "2025H2", frame)],
        exclude_isolated=True,
    )

    assert set(out["row_type"]) == {"floor", "segment"}
    assert out.loc[out["row_type"].eq("floor"), "n_machines"].iloc[0] == 4
    assert set(out.loc[out["row_type"].eq("segment"), "segment_key"]) == {"2F_A", "2F_N"}
    assert sorted(out.loc[out["row_type"].eq("segment"), "n_machines"].tolist()) == [2, 2]


def test_load_hall_frame_supports_kamata7_3f() -> None:
    coords_path = Path("Heatmap/3F_floor_coordinates_kamata7.csv")
    hall_name = infer_hall_name(coords_path, floor="3F")

    out = load_hall_frame(
        db_path=Path("db/マルハンメガシティ2000-蒲田7.db"),
        coords_path=coords_path,
        hall_name=hall_name,
        floor="3F",
        min_games=0,
    )

    assert not out.empty
    assert set(out["floor"]) == {"3F"}
    assert "section" in out.columns
    assert "residual_games" in out.columns


def test_load_hall_daily_frame_matches_machine_set_and_kakuban_assignment(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "sample.db"
    coords_path = tmp_path / "coords.csv"
    hall_name = infer_hall_name(Path("Heatmap/2F_floor_coordinates_kamata1.csv"), floor="2F")

    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE machine_detailed_results (
                date TEXT,
                machine_number INTEGER,
                machine_name TEXT,
                diff_coins_normalized INTEGER,
                games_normalized INTEGER
            )
            """
        )
        conn.executemany(
            """
            INSERT INTO machine_detailed_results
            VALUES (?, ?, ?, ?, ?)
            """,
            [
                ("20260105", 1001, "Alpha", 10, 1600),
                ("20260106", 1001, "Alpha", 14, 1700),
                ("20260105", 1002, "Beta", 20, 1600),
                ("20260106", 1002, "Beta", 28, 1700),
            ],
        )
        conn.commit()

    coords_path.write_text(
        "\n".join(
            [
                "hall_name,floor,machine_number,X,Y,display_x,display_y",
                f"{hall_name},2F,1001,10,1,10,1",
                f"{hall_name},2F,1002,20,1,20,1",
            ]
        ),
        encoding="utf-8",
    )

    daily = load_hall_daily_frame(
        db_path=db_path,
        coords_path=coords_path,
        hall_name=hall_name,
        floor="2F",
        min_games=1500,
    )
    monthly = load_hall_frame(
        db_path=db_path,
        coords_path=coords_path,
        hall_name=hall_name,
        floor="2F",
        min_games=1500,
    )

    monthly_assigned = assign_kakuban(monthly, hall_label="蒲田1", floor="2F", exclude_isolated=True)

    assert sorted(daily["machine_number"].unique().tolist()) == sorted(monthly["machine_number"].tolist())
    assert (
        daily.groupby("machine_number")["kakuban"].first().sort_index().tolist()
        == monthly_assigned.set_index("machine_number")["kakuban"].sort_index().tolist()
    )


def test_compute_kakuban_dispersion_test_detects_concentrated_group_signal() -> None:
    dates = pd.date_range("2026-01-01", periods=12, freq="D")
    rows: list[dict[str, object]] = []
    for date in dates:
        for machine_number, kakuban in [
            (1, 1),
            (2, 1),
            (3, 1),
            (4, 2),
            (5, 2),
            (6, 2),
            (7, 3),
            (8, 3),
            (9, 3),
            (10, 4),
            (11, 4),
            (12, 4),
            (13, 5),
            (14, 5),
            (15, 5),
            (16, 6),
            (17, 6),
            (18, 6),
        ]:
            value = 0.0
            if kakuban == 1:
                value += 100.0
            rows.append(
                {
                    "machine_number": machine_number,
                    "date": date,
                    "kakuban": kakuban,
                    "residual_diff": value,
                    "residual_games": value,
                    "machine_type_segment": "N",
                    "section": "S",
                    "excluded_from_corr": False,
                }
            )
    daily_frame = pd.DataFrame(rows)

    result = compute_kakuban_dispersion_test(
        daily_frame,
        value_col="residual_diff",
        n_permutations=200,
        seed=42,
    )

    assert result["observed_stat"] > 0
    assert result["p_value"] < 0.05


def test_compute_kakuban_dispersion_test_returns_nonsignificant_noise_only_result() -> None:
    dates = pd.date_range("2026-01-01", periods=16, freq="D")
    rows: list[dict[str, object]] = []
    values = [
        -0.3,
        0.1,
        0.2,
        -0.1,
        0.0,
        0.4,
        -0.2,
        0.3,
    ]
    for date_idx, date in enumerate(dates):
        for machine_number, kakuban in [(1, 1), (2, 1), (3, 2), (4, 2), (5, 3), (6, 3), (7, 4), (8, 4)]:
            rows.append(
                {
                    "machine_number": machine_number,
                    "date": date,
                    "kakuban": kakuban,
                    "residual_diff": values[(machine_number - 1 + date_idx) % len(values)],
                    "residual_games": values[(machine_number + date_idx) % len(values)],
                    "machine_type_segment": "N",
                    "section": "S",
                    "excluded_from_corr": False,
                }
            )
    daily_frame = pd.DataFrame(rows)

    result = compute_kakuban_dispersion_test(
        daily_frame,
        value_col="residual_games",
        n_permutations=200,
        seed=42,
    )

    assert result["observed_stat"] >= 0
    assert result["p_value"] > 0.05


def test_summarize_section_kakuban_epsilon_reports_section_and_segment_rows() -> None:
    frame = pd.DataFrame(
        {
            "section": ["S1"] * 8 + ["S2"] * 8,
            "machine_number": list(range(1, 17)),
            "machine_name": [
                "A",
                "A",
                "B",
                "B",
                "C",
                "C",
                "D",
                "D",
                "E",
                "E",
                "F",
                "F",
                "G",
                "G",
                "H",
                "H",
            ],
            "machine_type_segment": ["A"] * 8 + ["N"] * 8,
            "kakuban": [1, 1, 2, 2, 3, 3, 4, 4, 1, 2, 1, 2, 3, 4, 3, 4],
            "residual_diff": [8.0, 7.5, 0.5, 0.3, -0.2, 0.0, -1.0, -1.2, 1.0, 1.2, 0.8, 0.9, -0.1, -0.2, -0.3, -0.4],
            "residual_games": [0.0] * 16,
        }
    )

    out = summarize_section_kakuban_epsilon(frame, value_col="residual_diff", min_group_size=2)

    assert set(out["row_type"]) == {"section", "segment"}
    assert set(out["section"]) == {"S1", "S2"}
    assert set(out["machine_type_segment"].dropna()) == {"A", "N"}
    assert {"epsilon_sq", "n_rows", "n_groups", "low_sample"}.issubset(out.columns)
    assert out.loc[out["section"].eq("S1") & out["row_type"].eq("section"), "epsilon_sq"].iloc[0] >= 0


def test_summarize_section_kakuban_cat3_groups_near_mid_far() -> None:
    frame = pd.DataFrame(
        {
            "section": ["S1"] * 6,
            "machine_number": [1, 2, 3, 4, 5, 6],
            "kakuban": [1, 2, 3, 4, 5, 6],
            "residual_diff": [9.0, 3.0, 1.0, -1.0, -3.0, -9.0],
        }
    )

    out = summarize_section_kakuban_cat3(frame)

    assert set(out["kakuban_cat3"]) == {"near", "mid", "far"}
    assert out.loc[out["kakuban_cat3"].eq("near"), "mean_residual_diff"].iloc[0] == 9.0
    assert out.loc[out["kakuban_cat3"].eq("far"), "mean_residual_diff"].iloc[0] == -9.0
    assert out["n"].sum() == 6


def test_summarize_section_kakuban_fixed_effects_reports_machine_name_concentration() -> None:
    frame = pd.DataFrame(
        {
            "section": ["S1"] * 6,
            "machine_number": [1, 2, 3, 4, 5, 6],
            "machine_name": ["A", "A", "A", "B", "B", "C"],
            "kakuban": [1, 1, 2, 2, 3, 3],
            "residual_diff": [5.0, 4.0, 1.0, 0.5, -1.0, -1.5],
        }
    )

    out = summarize_section_kakuban_fixed_effects(frame)

    assert set(out["section"]) == {"S1"}
    assert set(out["kakuban"]) == {1, 2, 3}
    assert "machine_name_share" in out.columns
    assert out.loc[out["kakuban"].eq(1), "top_machine_name"].iloc[0] == "A"


def test_summarize_floor_segment_kakuban_epsilon_reports_a_and_n_rows() -> None:
    frame = pd.DataFrame(
        {
            "section": ["S1"] * 4 + ["S2"] * 4,
            "machine_number": list(range(1, 9)),
            "machine_name": ["A", "A", "B", "B", "C", "C", "D", "D"],
            "machine_type_segment": ["A", "A", "A", "A", "N", "N", "N", "N"],
            "kakuban": [1, 2, 1, 2, 1, 2, 1, 2],
            "residual_diff": [10.0, 2.0, 8.0, 1.0, -1.0, -3.0, -2.0, -4.0],
            "residual_games": [0.0] * 8,
        }
    )

    out = summarize_floor_segment_kakuban_epsilon(frame, value_col="residual_diff", min_group_size=2)

    assert set(out["row_type"]) == {"floor_segment"}
    assert set(out["machine_type_segment"].dropna()) == {"A", "N"}
    assert out["low_sample"].tolist() == [False, False]
    assert out["n_groups"].tolist() == [2, 2]


def test_summarize_floor_segment_kakuban_epsilon_flags_low_sample_when_groups_are_sparse() -> None:
    frame = pd.DataFrame(
        {
            "section": ["S1"] * 3,
            "machine_number": [1, 2, 3],
            "machine_name": ["A", "A", "B"],
            "machine_type_segment": ["A", "A", "A"],
            "kakuban": [1, 1, 1],
            "residual_diff": [1.0, 2.0, 3.0],
            "residual_games": [0.0] * 3,
        }
    )

    out = summarize_floor_segment_kakuban_epsilon(frame, value_col="residual_diff", min_group_size=2)

    assert out["low_sample"].tolist() == [True]
    assert out["n_groups"].tolist() == [1]


def test_summarize_floor_segment_kakuban_cat3_groups_near_mid_far() -> None:
    frame = pd.DataFrame(
        {
            "section": ["S1"] * 4 + ["S2"] * 4,
            "machine_number": list(range(1, 9)),
            "kakuban": [1, 2, 3, 4, 1, 2, 3, 4],
            "residual_diff": [8.0, 4.0, 1.0, -1.0, 6.0, 2.0, 0.0, -2.0],
        }
    )

    out = summarize_floor_segment_kakuban_cat3(frame)

    assert out.shape[0] == 1
    assert out["low_sample"].tolist() == [False]
    assert out["n_rows_total"].tolist() == [8]
    assert out["kakuban_cat3_near_mean"].tolist() == [7.0]
    assert out["kakuban_cat3_mid_mean"].tolist() == [1.75]
    assert out["kakuban_cat3_far_mean"].tolist() == [-1.5]


def test_summarize_floor_segment_kakuban_cat3_flags_low_sample_when_groups_are_sparse() -> None:
    frame = pd.DataFrame(
        {
            "section": ["S1"] * 3,
            "machine_number": [1, 2, 3],
            "kakuban": [1, 1, 1],
            "residual_diff": [1.0, 2.0, 3.0],
        }
    )

    out = summarize_floor_segment_kakuban_cat3(frame)

    assert out["low_sample"].tolist() == [True]
    assert out["epsilon_sq_3cat"].isna().all()
    assert out["p_value_3cat"].isna().all()


def test_run_analysis_emits_section_level_kakuban_csvs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    output_dir = tmp_path / "out"
    hall7_db = tmp_path / "hall7.db"

    with sqlite3.connect(hall7_db) as conn:
        conn.execute(
            """
            CREATE TABLE machine_detailed_results (
                date TEXT,
                machine_number INTEGER,
                machine_name TEXT,
                diff_coins_normalized REAL,
                games_normalized REAL
            )
            """
        )
        conn.executemany(
            """
            INSERT INTO machine_detailed_results
            VALUES (?, ?, ?, ?, ?)
            """,
            [
                ("20260601", 3001, "Q", 100.0, 1000.0),
                ("20260602", 3001, "Q", 120.0, 1100.0),
                ("20260603", 3001, "Q2", 140.0, 1200.0),
                ("20260601", 3002, "R", -50.0, 900.0),
                ("20260602", 3002, "R", -40.0, 950.0),
                ("20260603", 3002, "R2", -30.0, 980.0),
                ("20260601", 3005, "U", 60.0, 1300.0),
                ("20260602", 3005, "U", 55.0, 1250.0),
                ("20260603", 3005, "U", 50.0, 1230.0),
                ("20260601", 3006, "V", -10.0, 800.0),
                ("20260602", 3006, "V2", -20.0, 780.0),
                ("20260603", 3006, "V2", -25.0, 760.0),
            ],
        )
        conn.commit()

    hall1_frame = pd.DataFrame(
        {
            "hall_name": ["闥ｲ逕ｰ1 test"] * 8,
            "floor": ["2F"] * 8,
            "machine_number": [1001, 1002, 1003, 1004, 1005, 1006, 1007, 1008],
            "machine_name": ["A", "B", "C", "D", "E", "F", "G", "H"],
                "section": ["S1", "S1", "S1", "S1", "S2", "S2", "S2", "S2"],
                "X": [1, 2, 3, 4, 5, 6, 7, 8],
                "Y": [1] * 8,
                "x_norm": [0.0, 0.2, 0.4, 0.6, 0.4, 0.6, 0.8, 1.0],
                "y_norm": [0.1] * 8,
                "kakuban": [1, 2, 3, 4, 1, 2, 3, 4],
                "residual_diff": [8.0, 4.0, 1.0, -1.0, 7.0, 3.0, 0.0, -2.0],
                "residual_games": [1.0, 0.5, 0.2, -0.1, 1.2, 0.6, 0.1, -0.2],
                "games_normalized": [1100.0, 1110.0, 1120.0, 1130.0, 1200.0, 1210.0, 1220.0, 1230.0],
                "mean_games": [1600.0] * 8,
                "machine_type_segment": ["A", "A", "N", "N", "A", "A", "N", "N"],
                "excluded_from_corr": [False] * 8,
                "is_isolated": [False] * 8,
        }
    )
    hall7_2f_frame = pd.DataFrame(
        {
            "hall_name": ["闥ｲ逕ｰ7 test"] * 8,
            "floor": ["2F"] * 8,
            "machine_number": [2001, 2002, 2003, 2004, 2005, 2006, 2007, 2008],
            "machine_name": ["I", "J", "K", "L", "M", "N", "O", "P"],
                "section": ["T1", "T1", "T1", "T1", "T2", "T2", "T2", "T2"],
                "X": [10, 11, 12, 13, 20, 21, 22, 23],
                "Y": [1] * 8,
                "x_norm": [0.0, 0.2, 0.4, 0.6, 0.4, 0.6, 0.8, 1.0],
                "y_norm": [0.1] * 8,
                "kakuban": [1, 2, 3, 4, 1, 2, 3, 4],
                "residual_diff": [6.0, 2.0, -1.0, -3.0, 5.0, 1.0, -2.0, -4.0],
                "residual_games": [0.8, 0.4, 0.0, -0.2, 0.7, 0.3, -0.1, -0.3],
                "games_normalized": [1010.0, 1020.0, 1030.0, 1040.0, 1050.0, 1060.0, 1070.0, 1080.0],
                "mean_games": [1700.0] * 8,
                "machine_type_segment": ["A", "A", "N", "N", "A", "A", "N", "N"],
                "excluded_from_corr": [False] * 8,
                "is_isolated": [False] * 8,
        }
    )
    hall7_3f_frame = pd.DataFrame(
        {
            "hall_name": ["闥ｲ逕ｰ7 test"] * 8,
            "floor": ["3F"] * 8,
            "machine_number": [3001, 3002, 3003, 3004, 3005, 3006, 3007, 3008],
            "machine_name": ["Q", "R", "S", "T", "U", "V", "W", "X"],
                "section": ["U1", "U1", "U1", "U1", "U2", "U2", "U2", "U2"],
                "X": [30, 31, 32, 33, 40, 41, 42, 43],
                "Y": [1] * 8,
                "x_norm": [0.0, 0.2, 0.4, 0.6, 0.4, 0.6, 0.8, 1.0],
                "y_norm": [0.1] * 8,
                "kakuban": [1, 2, 3, 4, 1, 2, 3, 4],
                "residual_diff": [4.0, 2.0, 1.0, -1.0, 3.0, 1.0, 0.0, -2.0],
                "residual_games": [0.6, 0.2, 0.1, -0.1, 0.5, 0.1, 0.0, -0.2],
                "games_normalized": [910.0, 920.0, 930.0, 940.0, 950.0, 960.0, 970.0, 980.0],
                "mean_games": [1800.0] * 8,
                "machine_type_segment": ["A", "A", "N", "N", "A", "A", "N", "N"],
                "excluded_from_corr": [False] * 8,
                "is_isolated": [False] * 8,
        }
    )

    def fake_load_hall_frame(
        *,
        db_path: Path,
        coords_path: Path,
        hall_name: str,
        floor: str = "2F",
        min_games: int = 1500,
        date_range: tuple[pd.Timestamp | str, pd.Timestamp | str] | None = None,
        weekday: str | int | None = None,
    ) -> pd.DataFrame:
        if "闥ｲ逕ｰ1" in hall_name:
            return hall1_frame.copy()
        if floor == "2F":
            return hall7_2f_frame.copy()
        return hall7_3f_frame.copy()

    def fake_load_hall_daily_frame(
        *,
        db_path: Path,
        coords_path: Path,
        hall_name: str,
        floor: str = "2F",
        min_games: int = 1500,
        date_range: tuple[pd.Timestamp | str, pd.Timestamp | str] | None = None,
        weekday: str | int | None = None,
    ) -> pd.DataFrame:
        base = fake_load_hall_frame(
            db_path=db_path,
            coords_path=coords_path,
            hall_name=hall_name,
            floor=floor,
            min_games=min_games,
            date_range=date_range,
            weekday=weekday,
        ).copy()
        frames = []
        for date in (pd.Timestamp("2026-06-01"), pd.Timestamp("2026-06-02")):
            daily = base.copy()
            daily["date"] = date
            frames.append(daily)
        return pd.concat(frames, ignore_index=True)

    monkeypatch.setattr(analysis_mod, "load_hall_frame", fake_load_hall_frame)
    monkeypatch.setattr(analysis_mod, "load_hall_daily_frame", fake_load_hall_daily_frame)
    monkeypatch.setattr(analysis_mod, "assign_kakuban", lambda frame, **kwargs: frame.copy())
    monkeypatch.setattr(
        analysis_mod,
        "_resolve_hall_label",
        lambda hall_name, coords_path=None: "闥ｲ逕ｰ1" if "闥ｲ逕ｰ1" in str(hall_name) else "闥ｲ逕ｰ7",
    )
    monkeypatch.setattr(analysis_mod, "_read_date_bounds", lambda db_path: (pd.Timestamp("2025-01-01"), pd.Timestamp("2026-12-31")))
    monkeypatch.setattr(analysis_mod, "_maybe_save_plot", lambda summary, output_dir: None)

    hall1 = HallSpec(hall_name="闥ｲ逕ｰ1", db_path=tmp_path / "hall1.db", coords_path=tmp_path / "coords1.csv")
    hall7 = HallSpec(hall_name="闥ｲ逕ｰ7", db_path=hall7_db, coords_path=tmp_path / "coords7.csv")

    result = analysis_mod.run_analysis(hall1=hall1, hall7=hall7, output_dir=output_dir, min_games=1500)

    assert not result["section_kakuban_epsilon"].empty
    assert not result["section_kakuban_epsilon_daily"].empty
    assert not result["floor_segment_kakuban_epsilon"].empty
    assert not result["floor_segment_kakuban_epsilon_daily"].empty
    assert not result["floor_segment_kakuban_cat3"].empty
    assert (output_dir / "kamata7_3F_typeA_kakuban_cat3_by_section_games.csv").exists()
    assert (output_dir / "kamata7_3F_typeA_kakuban_cat3_global_games.csv").exists()
    assert (output_dir / "kamata7_3F_typeA_near_far_machine_transitions.csv").exists()
    assert (output_dir / "kamata_section_kakuban_epsilon_kamata1_2F.csv").exists()
    assert (output_dir / "kamata_section_kakuban_epsilon_daily_kamata1_2F.csv").exists()
    assert (output_dir / "kamata_floor_segment_kakuban_epsilon_kamata7_3F.csv").exists()
    assert (output_dir / "kamata_floor_segment_kakuban_epsilon_daily_kamata7_3F.csv").exists()
    assert (output_dir / "kamata_segment_kakuban_epsilon_kamata7_3F.csv").exists()
    assert (output_dir / "kamata_section_kakuban_cat3_kamata7_2F.csv").exists()
    assert (output_dir / "kamata7_3F_typeA_kakuban_cat3_by_section.csv").exists()
    assert (output_dir / "kamata7_3F_typeA_kakuban_cat3_global.csv").exists()
    assert (output_dir / "kamata_section_kakuban_fixed_effects_kamata1_2F.csv").exists()

    global_games = pd.read_csv(output_dir / "kamata7_3F_typeA_kakuban_cat3_global_games.csv")
    assert set(global_games["value_col"]) == {"residual_games", "games_normalized"}
    assert global_games.shape[0] == 2
    transitions = pd.read_csv(output_dir / "kamata7_3F_typeA_near_far_machine_transitions.csv")
    assert {"segment_id", "segment_start", "segment_end"}.issubset(transitions.columns)
    assert transitions["machine_number"].nunique() == 4
