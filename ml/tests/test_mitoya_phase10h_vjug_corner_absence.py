from __future__ import annotations

from pathlib import Path

import pandas as pd


def _make_frame() -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    dates = ["20260101", "20260103", "20260105"]
    section_specs = [
        ("501-522", "horizontal", True, 501, 1, 1, "h_jug"),
        ("523-539", "horizontal", False, 523, 2, 1, "h_nonjug"),
        ("624-640", "vertical", True, 624, 1, 2, "v_jug"),
    ]
    machine_offsets = list(range(12))
    machine_names = [
        "ジャグラーV",
        "ファンキージャグラー2",
        "アイムジャグラーEX-TP",
        "A",
        "B",
        "C",
        "D",
        "E",
        "F",
        "G",
        "H",
        "I",
    ]

    for date_idx, date in enumerate(dates):
        dd = int(date[-2:])
        for section_idx, (section, orientation, is_jug, base_machine, x, y, segment) in enumerate(section_specs):
            for offset, machine_name in zip(machine_offsets, machine_names, strict=True):
                machine_number = base_machine + offset
                rank = (offset % 4) + 1
                diff = 100 + section_idx * 15 + offset * 2 + date_idx * 5
                if segment == "v_jug" and rank == 1:
                    diff += 45
                if segment == "h_jug" and rank == 1:
                    diff += 20
                if segment == "h_nonjug" and rank == 4:
                    diff -= 10
                x_value = x
                y_value = y
                if segment == "v_jug":
                    y_value = y + offset
                rows.append(
                    {
                        "date": date,
                        "machine_number": machine_number,
                        "machine_name": f"ジャグラー{machine_name}" if is_jug else f"{machine_name}_N",
                        "diff": float(diff),
                        "games": 1500,
                        "section": section,
                        "x": x_value,
                        "y": y_value,
                        "rank_from_aisle": rank,
                        "dd": dd,
                    }
                )
    return pd.DataFrame(rows)


def test_build_all_artifacts_returns_expected_tables() -> None:
    import eda.mitoya_phase10h_vjug_corner_absence as phase10h

    artifacts = phase10h.build_all_artifacts(_make_frame())

    assert {
        "step1_corner_distribution",
        "step2_layout_stats",
        "step3_corner_comparison",
        "step4_machine_composition",
        "step5_residual_corner",
        "report",
    } <= set(artifacts)

    step1 = artifacts["step1_corner_distribution"]
    assert list(step1.columns) == ["section", "orientation", "corner_bucket", "n", "pct"]
    assert set(step1["orientation"].astype(str)) == {"horizontal", "vertical"}
    for section, grp in step1.groupby("section", dropna=False):
        total = float(pd.to_numeric(grp["pct"], errors="coerce").sum())
        assert abs(total - 100.0) < 1e-6

    step2 = artifacts["step2_layout_stats"]
    assert list(step2.columns) == [
        "segment",
        "rank_from_aisle_mean",
        "rank_from_aisle_std",
        "section_size_mean",
        "section_size_std",
        "n_sections",
        "n",
    ]
    assert set(step2["segment"].astype(str)) == {"h_jug", "v_jug"}

    step3 = artifacts["step3_corner_comparison"]
    assert list(step3.columns) == [
        "corner_bucket",
        "h_jug_avg_diff",
        "h_jug_n",
        "h_jug_plus_rate",
        "v_jug_avg_diff",
        "v_jug_n",
        "v_jug_plus_rate",
    ]
    assert set(step3["corner_bucket"].astype(str)) == {"corner1", "corner2-4", "corner5-9", "corner10+"}

    step4 = artifacts["step4_machine_composition"]
    assert list(step4.columns) == ["segment", "machine_name", "n", "avg_diff", "plus_rate", "share_pct"]
    assert set(step4["segment"].astype(str)) == {"h_jug", "v_jug"}
    assert len(step4) == 20

    step5 = artifacts["step5_residual_corner"]
    assert list(step5.columns) == ["segment", "kw_stat", "p_value", "epsilon_sq", "n_groups", "n", "note"]
    assert set(step5["note"].astype(str)) == {"raw", "residual"}

    report = artifacts["report"]
    assert "# Phase10h: v_jug corner absence analysis" in report


def test_main_writes_requested_files(tmp_path: Path, monkeypatch) -> None:
    import eda.mitoya_phase10h_vjug_corner_absence as phase10h

    monkeypatch.setattr(phase10h, "load_mitoya_frame", lambda join_layout=True: _make_frame())

    exit_code = phase10h.main(["--output-dir", str(tmp_path)])

    assert exit_code == 0
    for name in [
        "step1_corner_distribution.csv",
        "step2_layout_stats.csv",
        "step3_corner_comparison.csv",
        "step4_machine_composition.csv",
        "step5_residual_corner.csv",
        "report.md",
    ]:
        assert (tmp_path / name).exists()
