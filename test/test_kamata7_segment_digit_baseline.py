from __future__ import annotations

from pathlib import Path

import pandas as pd

import eda.kamata7_segment_digit_baseline as mod


def _make_frame() -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    machine_specs = [
        (2001, "N-machine-1", "2F", "L"),
        (2002, "N-machine-2", "2F", "R"),
        (3001, "ジャグラーA-1", "3F", "L"),
        (3002, "N-machine-3", "3F", "L"),
        (3003, "ハナハナA-2", "3F", "R"),
        (3004, "N-machine-4", "3F", "R"),
    ]
    weekdays = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun", "Mon", "Tue", "Wed"]
    for day_idx in range(10):
        date = f"202606{day_idx + 1:02d}"
        dd = day_idx + 1
        for machine_number, machine_name, floor, side in machine_specs:
            digit = day_idx
            rows.append(
                {
                    "date": date,
                    "machine_name": machine_name,
                    "machine_number": machine_number,
                    "machine_digit": str(digit),
                    "diff": (machine_number % 100) * 10 + digit * 20 + day_idx,
                    "games": 1200,
                    "day_of_week": weekdays[day_idx],
                    "dd": dd,
                    "dd_mod10": dd % 10,
                    "floor": floor,
                    "side": side,
                }
            )
    return pd.DataFrame(rows)


def test_level5_has_six_non_empty_segments() -> None:
    frame = mod.build_segment_frame(_make_frame())
    segments = mod.level_segment_names(frame, 5)

    assert segments == [
        "2F_L_N",
        "2F_R_N",
        "3F_L_A",
        "3F_L_N",
        "3F_R_A",
        "3F_R_N",
    ]
    assert "2F_L_A" not in segments
    assert "2F_R_A" not in segments


def test_ranking_spans_one_to_ten() -> None:
    frame = mod.build_segment_frame(_make_frame())
    rankings = mod.build_level_rankings(frame, 5)
    target = rankings[(rankings["level"] == 5) & (rankings["segment"] == "3F_L_N")]

    assert sorted(target["rank"].dropna().astype(int).unique().tolist()) == list(range(1, 11))


def test_kruskal_h_is_non_negative() -> None:
    frame = mod.build_segment_frame(_make_frame())
    signal = mod.build_signal_strength_table(frame)
    row = signal[(signal["level"] == 5) & (signal["segment"] == "3F_L_N")].iloc[0]

    assert row["kruskal_H"] >= 0


def test_spearman_rho_is_bounded() -> None:
    frame = mod.build_segment_frame(_make_frame())
    rho_table = mod.build_level_rank_correlations(frame)
    row = rho_table[(rho_table["level"] == 5) & (rho_table["segment_a"] == "3F_L_A") & (rho_table["segment_b"] == "3F_R_A")].iloc[0]

    assert -1.0 <= row["spearman_rho"] <= 1.0


def test_empty_segments_are_skipped() -> None:
    frame = mod.build_segment_frame(_make_frame())
    rankings = mod.build_level_rankings(frame, 5)

    assert "2F_L_A" not in rankings["segment"].unique().tolist()
    assert "2F_R_A" not in rankings["segment"].unique().tolist()


def test_run_analysis_writes_bom_csvs_and_report(tmp_path: Path) -> None:
    frame = mod.build_segment_frame(_make_frame())
    report_path = tmp_path / "report.md"
    rankings_path = tmp_path / "rankings.csv"
    signal_path = tmp_path / "signal.csv"
    quickref_path = tmp_path / "quickref.csv"

    outputs = mod.run_analysis(
        df=frame,
        report_path=report_path,
        rankings_path=rankings_path,
        signal_strength_path=signal_path,
        quickref_path=quickref_path,
    )

    assert report_path.exists()
    assert rankings_path.exists()
    assert signal_path.exists()
    assert quickref_path.exists()
    assert report_path.read_bytes().startswith(b"\xef\xbb\xbf")
    assert rankings_path.read_bytes().startswith(b"\xef\xbb\xbf")
    assert signal_path.read_bytes().startswith(b"\xef\xbb\xbf")
    assert quickref_path.read_bytes().startswith(b"\xef\xbb\xbf")
    assert "3F_R_N" not in quickref_path.read_text(encoding="utf-8-sig")
    assert not outputs["signal_strength"].empty
