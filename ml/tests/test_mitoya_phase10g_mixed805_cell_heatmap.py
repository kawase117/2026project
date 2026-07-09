from __future__ import annotations

from pathlib import Path

import pandas as pd


DATES = pd.date_range("2026-01-01", "2026-02-01", freq="D")


def _make_frame() -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    rows.append(
        {
            "date": "20251101",
            "machine_number": 809,
            "machine_name": "MIX-G-A",
            "diff": 120.0,
            "games": 1500,
            "section": "805-815",
            "x": 5,
            "y": 1,
            "rank_from_aisle": 4,
        }
    )
    rows.append(
        {
            "date": "20251201",
            "machine_number": 809,
            "machine_name": "MIX-G-B",
            "diff": 135.0,
            "games": 1500,
            "section": "805-815",
            "x": 5,
            "y": 1,
            "rank_from_aisle": 4,
        }
    )
    segment_specs = [
        {
            "segment": "mixed_805",
            "section": "805-815",
            "orientation": "horizontal",
            "machines": [
                (805, "MIX-A", 1, 1),
                (806, "MIX-B", 2, 1),
                (807, "MIX-C", 3, 1),
                (808, "MIX-D", 4, 1),
                (809, "MIX-G", 5, 1),
            ],
            "debut_switch": pd.Timestamp("2026-01-12"),
        },
        {
            "segment": "h_nonjug",
            "section": "501-522",
            "orientation": "horizontal",
            "machines": [
                (501, "N-A", 1, 2),
                (502, "N-B", 2, 2),
                (503, "N-C", 3, 2),
            ],
            "debut_switch": pd.Timestamp("2026-01-12"),
        },
        {
            "segment": "h_jug",
            "section": "501-522",
            "orientation": "horizontal",
            "machines": [
                (521, "ジャグラーA", 4, 2),
                (522, "ジャグラーB", 5, 2),
                (523, "ジャグラーC", 6, 2),
            ],
            "debut_switch": pd.Timestamp("2026-01-20"),
        },
    ]

    for date_idx, date in enumerate(DATES):
        dd = int(date.day)
        is_xdds_day = dd in {4, 7, 14, 17, 24, 27}
        is_non_event = dd not in {4, 7, 11, 14, 17, 22, 24, 27, 31}
        for segment_idx, spec in enumerate(segment_specs):
            for machine_idx, (machine_number, base_name, x, y) in enumerate(spec["machines"], start=1):
                machine_name = base_name
                if spec["segment"] == "mixed_805" and machine_idx == 5:
                    machine_name = "MIX-G-B"
                elif date >= spec["debut_switch"] and spec["segment"] == "mixed_805":
                    machine_name = f"{base_name}-B"
                elif date >= spec["debut_switch"] and machine_idx == 1:
                    machine_name = f"{base_name}-B"
                diff = 90.0 + segment_idx * 40.0 + machine_idx * 12.0 + date_idx * 1.5
                if spec["segment"] == "mixed_805" and is_xdds_day and machine_idx == 1:
                    diff += 1200.0
                if spec["segment"] == "h_nonjug" and is_non_event and machine_idx == 2:
                    diff += 40.0
                if spec["segment"] == "h_jug" and is_xdds_day and machine_idx == 1:
                    diff += 30.0
                rows.append(
                    {
                        "date": date.strftime("%Y%m%d"),
                        "machine_number": machine_number,
                        "machine_name": machine_name,
                        "diff": float(diff),
                        "games": 1500,
                        "section": spec["section"],
                        "x": x,
                        "y": y,
                        "rank_from_aisle": machine_idx,
                    }
                )
    return pd.DataFrame(rows)


def test_build_all_artifacts_returns_expected_tables() -> None:
    from eda import mitoya_phase10g_mixed805_cell_heatmap as phase10g

    artifacts = phase10g.build_all_artifacts(_make_frame())

    assert {"step1_cell_stats", "step2_cell_contrast", "step3_driver_identification", "step4_summary", "report"} <= set(
        artifacts
    )

    step1 = artifacts["step1_cell_stats"]
    assert list(step1.columns) == ["segment", "debut_phase", "is_xdds", "n", "avg_diff", "plus_rate"]
    assert len(step1) == 24
    assert set(step1["segment"].astype(str)) == {"mixed_805", "h_nonjug", "h_jug"}
    assert set(step1["debut_phase"].astype(str)) == set(phase10g.DEBUT_PHASE_ORDER)
    assert set(step1["is_xdds"].astype(int)) == {0, 1}
    assert step1[["n", "avg_diff", "plus_rate"]].notna().all().all()

    step2 = artifacts["step2_cell_contrast"]
    assert list(step2.columns) == [
        "segment",
        "debut_phase",
        "xdds_avg_diff",
        "nonevent_avg_diff",
        "contrast",
        "xdds_n",
        "nonevent_n",
    ]
    mixed = step2.loc[step2["segment"].astype(str).eq("mixed_805")].copy()
    debut_row = mixed.loc[mixed["debut_phase"].astype(str).eq("debut")].iloc[0]
    assert debut_row["contrast"] > 0

    step3 = artifacts["step3_driver_identification"]
    assert list(step3.columns) == ["segment", "debut_phase", "is_xdds", "avg_diff", "z_score", "is_outlier"]
    mixed_outliers = step3.loc[step3["segment"].astype(str).eq("mixed_805")]
    assert bool(
        mixed_outliers.loc[
            mixed_outliers["debut_phase"].astype(str).eq("debut") & mixed_outliers["is_xdds"].astype(int).eq(1),
            "is_outlier",
        ].iloc[0]
    )

    step4 = artifacts["step4_summary"]
    assert list(step4.columns) == ["segment", "max_contrast_phase", "contrast", "xdds_n", "nonevent_n"]
    assert set(step4["segment"].astype(str)) == {"mixed_805", "h_nonjug", "h_jug"}
    assert (
        step4.loc[step4["segment"].astype(str).eq("mixed_805"), "max_contrast_phase"].iloc[0]
        in phase10g.DEBUT_PHASE_ORDER
    )
    assert step4.loc[step4["segment"].astype(str).eq("mixed_805"), "contrast"].iloc[0] > 0

    report = artifacts["report"]
    assert "# Phase10g: mixed_805 debut×X_DDS セル分解" in report
    assert "## Finding" in report


def test_main_writes_requested_files(tmp_path: Path, monkeypatch) -> None:
    from eda import mitoya_phase10g_mixed805_cell_heatmap as phase10g

    monkeypatch.setattr(phase10g, "load_mitoya_frame", lambda join_layout=True: _make_frame())

    exit_code = phase10g.main(["--output-dir", str(tmp_path)])

    assert exit_code == 0
    for name in [
        "step1_cell_stats.csv",
        "step2_cell_contrast.csv",
        "step3_driver_identification.csv",
        "step4_summary.csv",
        "report.md",
    ]:
        assert (tmp_path / name).exists()
