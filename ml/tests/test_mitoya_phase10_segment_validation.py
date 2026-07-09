from __future__ import annotations

from pathlib import Path

import pandas as pd


def _make_frame() -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    section_specs = [
        (
            "501-522",
            "horizontal",
            "jug",
            [501, 502, 503],
            [19, 11, 3],
            [1, 1, 1],
            ["マイジャグラーV", "ファンキージャグラー2", "アイムジャグラーEX-TP"],
        ),
        ("523-539", "horizontal", "non_jug", [523, 524, 525], [19, 11, 3], [1, 1, 1], ["A", "B", "C"]),
        (
            "692-700",
            "vertical",
            "jug",
            [692, 693, 694],
            [1, 1, 1],
            [13, 8, 3],
            ["マイジャグラーV", "ファンキージャグラー2", "アイムジャグラーEX-TP"],
        ),
        ("701-711", "vertical", "non_jug", [701, 702, 703], [1, 1, 1], [11, 6, 1], ["A", "B", "C"]),
        (
            "805-815",
            "horizontal",
            "mixed",
            [805, 806, 807, 808],
            [4, 3, 2, 1],
            [1, 1, 1, 1],
            ["マイジャグラーV", "A", "ファンキージャグラー2", "B"],
        ),
    ]

    for dd in range(1, 32):
        date = f"202606{dd:02d}"
        for section_idx, (section, orientation, jug_kind, machine_numbers, xs, ys, names) in enumerate(
            section_specs, start=1
        ):
            for machine_idx, (machine_number, x, y, machine_name) in enumerate(
                zip(machine_numbers, xs, ys, names), start=1
            ):
                jug_flag = "ジャグラー" in machine_name
                orientation_bonus = 15 if orientation == "horizontal" else -10
                jug_bonus = 8 if jug_flag else -4
                interaction_bonus = (
                    6
                    if orientation == "horizontal" and jug_flag
                    else (-3 if orientation == "vertical" and jug_flag else 0)
                )
                day_bonus = dd * 2
                machine_bonus = machine_idx * 3 + section_idx
                diff = float(day_bonus + orientation_bonus + jug_bonus + interaction_bonus + machine_bonus)
                rows.append(
                    {
                        "date": date,
                        "section": section,
                        "machine_number": machine_number,
                        "machine_name": machine_name,
                        "diff": diff,
                        "games": 1000 + dd,
                        "x": x,
                        "y": y,
                        "rank_from_aisle": [1, 2, 5, 10][machine_idx - 1]
                        if section == "805-815"
                        else [1, 5, 10][machine_idx - 1],
                    }
                )
    return pd.DataFrame(rows)


def test_build_all_artifacts_covers_all_required_outputs() -> None:
    from eda import mitoya_phase10_segment_validation as phase10

    artifacts = phase10.build_all_artifacts(_make_frame())

    assert {"step1_single_axis", "step2_interaction", "step3_segment_basics", "step4_digit_kw", "report"} <= set(
        artifacts
    )

    step1 = artifacts["step1_single_axis"]
    assert {"step", "axis", "level", "n", "avg_diff", "plus_rate", "p_value", "epsilon_sq"} <= set(step1.columns)
    assert set(step1["step"].astype(str)) == {"1a", "1b", "1c"}

    step2 = artifacts["step2_interaction"]
    assert {
        "analysis",
        "kind",
        "axis_a",
        "axis_b",
        "level_a",
        "level_b",
        "n",
        "avg_diff",
        "plus_rate",
        "statistic",
        "p_value",
    } <= set(step2.columns)
    assert {"orientation_x_jug_flag", "section805_x_jug_flag"} <= set(step2["analysis"].astype(str))

    step3 = artifacts["step3_segment_basics"]
    assert {"segment", "metric", "level", "n", "avg_diff", "plus_rate"} <= set(step3.columns)
    assert set(step3["segment"].astype(str)) == {"h_jug", "h_nonjug", "v_jug", "v_nonjug", "mixed_805"}
    assert "jug_flag" in set(step3.loc[step3["segment"].astype(str) == "mixed_805", "metric"].astype(str))

    step4 = artifacts["step4_digit_kw"]
    assert {"segment", "test_name", "n_groups", "total_n", "kw_stat", "p_value", "epsilon_sq"} <= set(step4.columns)
    assert len(step4) == 5


def test_main_writes_requested_csvs(tmp_path: Path, monkeypatch) -> None:
    from eda import mitoya_phase10_segment_validation as phase10

    monkeypatch.setattr(phase10, "load_mitoya_frame", lambda join_layout=True: _make_frame())

    exit_code = phase10.main(["--output-dir", str(tmp_path)])

    assert exit_code == 0
    for name in [
        "step1_single_axis.csv",
        "step2_interaction.csv",
        "step3_segment_basics.csv",
        "step4_digit_kw.csv",
        "report.md",
    ]:
        assert (tmp_path / name).exists()
