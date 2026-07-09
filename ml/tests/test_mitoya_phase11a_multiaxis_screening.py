from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from eda.mitoya_prompt_common import WEEKDAY_ORDER, X_DDS


@pytest.fixture()
def dummy_frame() -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    segment_specs = [
        {
            "segment": "h_jug",
            "section": "501-522",
            "machine_numbers": list(range(501, 513)),
            "x_values": list(range(1, 13)),
            "y_values": [1] * 12,
            "machine_names": ["マイジャグラーV"] * 12,
        },
        {
            "segment": "h_nonjug",
            "section": "523-539",
            "machine_numbers": list(range(523, 535)),
            "x_values": list(range(1, 13)),
            "y_values": [2] * 12,
            "machine_names": ["ハマリ台A"] * 12,
        },
        {
            "segment": "v_jug",
            "section": "701-711",
            "machine_numbers": list(range(701, 713)),
            "x_values": [1] * 12,
            "y_values": list(range(1, 13)),
            "machine_names": ["ファンキージャグラー"] * 12,
        },
        {
            "segment": "v_nonjug",
            "section": "712-722",
            "machine_numbers": list(range(713, 725)),
            "x_values": [2] * 12,
            "y_values": list(range(1, 13)),
            "machine_names": ["ノーマル台B"] * 12,
        },
        {
            "segment": "mixed_805",
            "section": "805-815",
            "machine_numbers": list(range(805, 817)),
            "x_values": list(range(1, 13)),
            "y_values": list(range(1, 13)),
            "machine_names": [
                "マイジャグラーV",
                "ノーマル台C",
                "ファンキージャグラー",
                "ノーマル台D",
                "マイジャグラーV",
                "ノーマル台E",
                "ファンキージャグラー",
                "ノーマル台F",
                "マイジャグラーV",
                "ノーマル台G",
                "ファンキージャグラー",
                "ノーマル台H",
            ],
        },
    ]

    for dd in range(1, 32):
        date = f"202601{dd:02d}"
        for spec in segment_specs:
            if dd in X_DDS:
                event_category = "X_DDS"
            elif dd in {11, 22}:
                event_category = "ゾロ目日"
            elif dd == 1:
                event_category = "強ゾロ目"
            elif dd == 31:
                event_category = "月末"
            else:
                event_category = "非イベント日"

            for machine_index, (machine_number, x_value, y_value, machine_name) in enumerate(
                zip(spec["machine_numbers"], spec["x_values"], spec["y_values"], spec["machine_names"]),
                start=1,
            ):
                rows.append(
                    {
                        "date": date,
                        "segment_label": spec["segment"],
                        "event_category_label": event_category,
                        "machine_number": machine_number,
                        "machine_name": machine_name,
                        "section": spec["section"],
                        "x": x_value,
                        "y": y_value,
                        "rank_from_aisle": machine_index,
                        "games": 1500 + dd,
                        "is_zorome": int(str(machine_number)[-2:] in {f"{i}{i}" for i in range(10)}),
                    }
                )

    frame = pd.DataFrame(rows)

    weekday_cycle = list(WEEKDAY_ORDER)
    weekday_rows: list[pd.DataFrame] = []
    for _, grp in frame.groupby(["segment_label", "event_category_label"], sort=False):
        ordered = grp.sort_values(["date", "machine_number"]).copy()
        ordered["day_of_week"] = [weekday_cycle[i % len(weekday_cycle)] for i in range(len(ordered))]
        weekday_rows.append(ordered)

    frame = pd.concat(weekday_rows, ignore_index=True)

    weekday_bonus = {"月": 0.0, "火": 1.0, "水": 2.0, "木": 3.0, "金": 4.0, "土": 6.0, "日": 5.0}
    segment_bonus = {"h_jug": 12.0, "h_nonjug": -2.0, "v_jug": 5.0, "v_nonjug": -4.0, "mixed_805": 3.0}
    event_bonus = {"X_DDS": 15.0, "ゾロ目日": 1.0, "強ゾロ目": 4.0, "月末": 6.0, "非イベント日": 0.0}
    frame["diff"] = (
        frame["date"].astype(str).str[-2:].astype(int) * 0.8
        + frame["day_of_week"].map(weekday_bonus).astype(float)
        + frame["segment_label"].map(segment_bonus).astype(float)
        + frame["event_category_label"].map(event_bonus).astype(float)
        + frame["is_zorome"].map({0: -1.0, 1: 6.0}).astype(float)
        + ((frame["event_category_label"].eq("X_DDS")) & frame["day_of_week"].eq("土")).astype(float) * 5.0
    )

    return frame.drop(columns=["segment_label", "event_category_label"])


def test_step1_dd_kw_three_grains(dummy_frame: pd.DataFrame) -> None:
    from eda import mitoya_phase11a_multiaxis_screening as phase11a

    table = phase11a.build_step1_dd_kw(dummy_frame)

    assert set(table["grain"].astype(str)) == {"hall", "segment", "composite"}
    assert set(table.loc[table["grain"].astype(str) == "composite", "event_scope"].astype(str)) == {
        "X_DDS",
        "非イベント日",
    }
    assert len(table) == 16


def test_step2_dd_stats_31_values(dummy_frame: pd.DataFrame) -> None:
    from eda import mitoya_phase11a_multiaxis_screening as phase11a

    table = phase11a.build_step2_dd_stats(dummy_frame)

    hall = table.loc[table["grain"].astype(str).eq("hall")]
    assert set(hall["dd"].astype(str)) == {str(i) for i in range(1, 32)}


def test_step3_weekday_kw_seven_groups(dummy_frame: pd.DataFrame) -> None:
    from eda import mitoya_phase11a_multiaxis_screening as phase11a

    table = phase11a.build_step3_weekday_kw(dummy_frame)

    assert table["n_groups"].dropna().astype(int).eq(7).all()


def test_step5_event_weekday_cross_structure(dummy_frame: pd.DataFrame) -> None:
    from eda import mitoya_phase11a_multiaxis_screening as phase11a

    table = phase11a.build_step5_event_weekday_cross(dummy_frame)

    assert set(table["event_category"].astype(str)) == {"X_DDS", "ゾロ目日", "強ゾロ目", "月末", "非イベント日"}
    assert set(table["segment"].astype(str)) >= {"", "h_jug", "h_nonjug", "v_jug", "v_nonjug", "mixed_805"}
    assert set(table["day_of_week"].astype(str)) <= set(WEEKDAY_ORDER)


def test_step6_anova_interaction_term(dummy_frame: pd.DataFrame) -> None:
    from eda import mitoya_phase11a_multiaxis_screening as phase11a

    table = phase11a.build_step6_event_weekday_anova(dummy_frame)

    interaction = table.loc[table["source"].astype(str).eq("C(is_xdds_day):C(day_of_week)")]
    assert not interaction.empty
    assert interaction["p_value"].notna().any()


def test_step7_zorome_kw_binary(dummy_frame: pd.DataFrame) -> None:
    from eda import mitoya_phase11a_multiaxis_screening as phase11a

    table = phase11a.build_step7_zorome_kw(dummy_frame)

    assert table["n_groups"].dropna().astype(int).eq(2).all()


def test_step9_summary_all_axes(dummy_frame: pd.DataFrame) -> None:
    from eda import mitoya_phase11a_multiaxis_screening as phase11a

    artifacts = phase11a.build_all_artifacts(dummy_frame)
    summary = artifacts["step9_summary"]

    assert {"dd_spectrum", "day_of_week", "is_zorome", "event_x_weekday"} <= set(summary["axis"].astype(str))
    assert {"◎有望", "○要検討", "△境界的", "✗脱落", "skip"} >= set(summary["verdict"].astype(str))


def test_generate_report_creates_files(
    dummy_frame: pd.DataFrame, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from eda import mitoya_phase11a_multiaxis_screening as phase11a

    monkeypatch.setattr(phase11a, "load_mitoya_frame", lambda join_layout=True: dummy_frame)

    exit_code = phase11a.main(["--output-dir", str(tmp_path)])

    assert exit_code == 0
    for name in [
        "step1_dd_kw.csv",
        "step2_dd_stats.csv",
        "step3_weekday_kw.csv",
        "step4_weekday_stats.csv",
        "step5_event_weekday_cross.csv",
        "step6_event_weekday_anova.csv",
        "step7_zorome_kw.csv",
        "step8_zorome_stats.csv",
        "step9_summary.csv",
        "report.md",
    ]:
        assert (tmp_path / name).exists()
