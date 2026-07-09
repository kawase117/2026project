from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest


def _make_frame() -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    section_specs = [
        (
            "501-522",
            [501, 502, 503, 504],
            [1, 2, 3, 4],
            [1, 1, 1, 1],
            ["マイジャグラーV", "マイジャグラーV", "マイジャグラーV", "マイジャグラーV"],
        ),
        ("523-539", [523, 524, 525, 526], [1, 2, 3, 4], [1, 1, 1, 1], ["A", "B", "C", "D"]),
        (
            "692-700",
            [692, 693, 694, 695],
            [1, 1, 1, 1],
            [1, 2, 3, 4],
            ["アイムジャグラーEX-TP", "アイムジャグラーEX-TP", "アイムジャグラーEX-TP", "アイムジャグラーEX-TP"],
        ),
        ("701-711", [701, 702, 703, 704], [1, 1, 1, 1], [1, 2, 3, 4], ["A", "B", "C", "D"]),
        (
            "805-815",
            [805, 806, 807, 808],
            [1, 2, 3, 4],
            [1, 1, 1, 1],
            ["マイジャグラーV", "A", "ファンキージャグラー2", "B"],
        ),
    ]

    for dd in range(1, 32):
        date = f"202605{dd:02d}"
        for section_idx, (section, machine_numbers, xs, ys, names) in enumerate(section_specs, start=1):
            for machine_idx, (machine_number, x, y, machine_name) in enumerate(
                zip(machine_numbers, xs, ys, names), start=1
            ):
                diff = float(dd * 8 + section_idx * 9 + machine_idx * 5)
                if dd in {4, 7, 14, 17, 24, 27}:
                    diff += 60.0
                if dd in {11, 22, 31}:
                    diff += 20.0
                if section == "805-815":
                    diff += 15.0
                rows.append(
                    {
                        "date": date,
                        "section": section,
                        "machine_number": machine_number,
                        "machine_name": machine_name,
                        "diff": diff,
                        "games": 1500,
                        "x": x,
                        "y": y,
                        "rank_from_aisle": machine_idx,
                    }
                )
    return pd.DataFrame(rows)


def test_build_all_artifacts_applies_event_scope_rules() -> None:
    from eda import mitoya_104pct_analysis as analysis

    artifacts = analysis.build_all_artifacts(_make_frame())
    step1 = artifacts["step1_dd_104rate"]

    assert len(step1) == 496
    assert set(step1["grain"].astype(str)) == {"hall", "segment", "composite"}
    assert set(step1["event_scope"].astype(str)) == {"", "X_DDS", "非イベント日"}

    hall = step1.loc[step1["grain"].astype(str).eq("hall")]
    assert hall.shape[0] == 31
    assert hall.loc[hall["dd"].eq(4), "n"].iloc[0] > 0
    assert hall.loc[hall["dd"].eq(11), "n"].iloc[0] > 0

    composite_xdds = step1.loc[
        step1["grain"].astype(str).eq("composite")
        & step1["segment"].astype(str).eq("h_jug")
        & step1["event_scope"].astype(str).eq("X_DDS")
    ]
    assert composite_xdds.shape[0] == 31
    assert composite_xdds.loc[composite_xdds["dd"].eq(4), "n"].iloc[0] > 0
    assert composite_xdds.loc[composite_xdds["dd"].eq(5), "n"].iloc[0] == 0
    assert composite_xdds.loc[composite_xdds["dd"].eq(11), "n"].iloc[0] == 0

    composite_nonevent = step1.loc[
        step1["grain"].astype(str).eq("composite")
        & step1["segment"].astype(str).eq("h_jug")
        & step1["event_scope"].astype(str).eq("非イベント日")
    ]
    assert composite_nonevent.loc[composite_nonevent["dd"].eq(12), "n"].iloc[0] > 0
    assert composite_nonevent.loc[composite_nonevent["dd"].eq(4), "n"].iloc[0] == 0

    step5 = artifacts["step5_nonxdds_kw"]
    assert set(step5["grain"].astype(str)) == {"hall", "segment"}
    assert int(step5.loc[step5["grain"].astype(str).eq("hall"), "n_groups"].iloc[0]) == 22
    assert int(step5.loc[step5["grain"].astype(str).eq("segment"), "n_groups"].min()) == 22

    step2 = artifacts["step2_peak_trough"]
    assert set(step2["category"].astype(str)) == {"peak", "trough"}
    assert len(step2) == 10

    step3 = artifacts["step3_diff_vs_104"]
    assert {"hall", "segment", "composite"} <= set(step3["grain"].astype(str))
    composite_summary = step3.loc[
        step3["grain"].astype(str).eq("composite")
        & step3["segment"].astype(str).eq("h_jug")
        & step3["event_scope"].astype(str).eq("X_DDS")
    ]
    assert int(composite_summary["n_dd"].iloc[0]) == 6

    step4 = artifacts["step4_corner_104rate"]
    assert len(step4) == 20
    assert set(step4["corner_bucket"].astype(str)) == {"corner1", "corner2-4", "corner5-9", "corner10+"}

    step6 = artifacts["step6_summary"]
    assert set(step6["finding"].astype(str)) == {
        "hall_peak_trough_gap_pp",
        "hall_diff_vs_104_rho",
        "nonxdds_dd_kw_p_hall",
        "h_jug_corner1_104rate",
        "h_nonjug_corner1_event_104rate",
    }


def test_main_writes_requested_outputs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from eda import mitoya_104pct_analysis as analysis

    monkeypatch.setattr(analysis, "load_mitoya_frame", lambda join_layout=True: _make_frame())

    exit_code = analysis.main(["--output-dir", str(tmp_path)])

    assert exit_code == 0
    for name in [
        "step1_dd_104rate.csv",
        "step2_peak_trough.csv",
        "step3_diff_vs_104.csv",
        "step3_divergent_dd.csv",
        "step4_corner_104rate.csv",
        "step5_nonxdds_kw.csv",
        "step6_summary.csv",
        "report.md",
    ]:
        assert (tmp_path / name).exists()
