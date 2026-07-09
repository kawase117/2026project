from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from eda import mitoya_phase7_shortlist_backtest as shortlist_bt
from eda import mitoya_phase8_backtest as phase8


def _make_frame() -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    specs = [
        ("557-573", 557, "H1", 1, 14, 29, 400, 350),
        ("557-573", 558, "H2", 2, 15, 29, 380, 330),
        ("557-573", 559, "H3", 3, 16, 29, 360, 310),
        ("557-573", 560, "H4", 4, 17, 29, 340, 290),
        ("557-573", 561, "H5", 5, 18, 29, -200, -180),
        ("557-573", 562, "H6", 6, 19, 29, -220, -200),
        ("574-590", 574, "I1", 1, 3, 28, 60, 40),
        ("574-590", 575, "I2", 2, 4, 28, 75, 55),
        ("574-590", 576, "I3", 3, 5, 28, 30, 10),
        ("574-590", 577, "I4", 4, 6, 28, 20, 0),
        ("712-722", 712, "V1", 1, 8, 13, 70, 65),
        ("712-722", 713, "V2", 2, 8, 12, 72, 67),
        ("712-722", 714, "V3", 3, 8, 11, 68, 63),
        ("712-722", 715, "V4", 4, 8, 10, 66, 61),
        ("712-722", 716, "V5", 5, 8, 9, 64, 59),
    ]
    for period, start in enumerate(("2026-01-01", "2026-04-01")):
        base_date = pd.Timestamp(start)
        for day_offset in range(8):
            date = base_date + pd.Timedelta(days=day_offset)
            is_xdds = date.day in {4, 7}
            for section, machine_number, machine_name, rank_from_aisle, x, y, train_diff, test_diff in specs:
                diff = train_diff if period == 0 else test_diff
                rows.append(
                    {
                        "date": date.strftime("%Y%m%d"),
                        "period": period,
                        "machine_number": machine_number,
                        "machine_name": machine_name,
                        "section": section,
                        "diff": diff,
                        "games": 1200,
                        "rank_from_aisle": rank_from_aisle,
                        "x": x,
                        "y": y,
                        "is_reversed_section": 0,
                        "is_xdds": is_xdds,
                    }
                )
    return pd.DataFrame(rows)


def test_build_backtest_outputs_produces_expected_artifacts(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(shortlist_bt, "SHORTLIST_MIN_N", 0)
    monkeypatch.setattr(phase8, "TARGET_SECTIONS", ["557-573", "574-590", "712-722"])

    outputs = phase8.build_backtest_outputs(_make_frame())

    assert {
        "period_summary",
        "corner_filter_summary",
        "machine_corner_summary",
        "xdds_split_summary",
        "shortlist_period_table",
        "report",
    } <= set(outputs)
    assert not outputs["period_summary"].empty
    assert set(outputs["period_summary"]["scope"]) == {"全体", "X_DDS日"}
    assert (
        outputs["corner_filter_summary"]["corner_bucket"].isin({"corner1", "corner2-4", "corner5-9", "corner10+"}).any()
    )
    assert {"train_avg_diff", "test_avg_diff", "corner_bucket"} <= set(outputs["machine_corner_summary"].columns)
    assert set(outputs["xdds_split_summary"]["scope"]) == {"全体", "X_DDS日"}


def test_corner_rule_beats_target_in_synthetic_frame(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(shortlist_bt, "SHORTLIST_MIN_N", 0)
    monkeypatch.setattr(phase8, "TARGET_SECTIONS", ["557-573", "574-590", "712-722"])

    period_summary = phase8.build_period_summary(_make_frame(), top_n=2, machine_corner_top_n=2)

    assert period_summary["CornerRule_vs_Target_diff"].mean() > 0
    assert period_summary["MachineCorner_vs_Target_diff"].notna().any()
    assert period_summary.loc[period_summary["scope"] == "X_DDS日", "n_xdds_dates"].notna().all()


def test_main_writes_outputs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import pytest

    monkeypatch.setattr(shortlist_bt, "SHORTLIST_MIN_N", 0)
    monkeypatch.setattr(phase8, "TARGET_SECTIONS", ["557-573", "574-590", "712-722"])
    monkeypatch.setattr(phase8, "load_data", lambda min_games=1000: _make_frame())

    exit_code = phase8.main(["--output-dir", str(tmp_path)])

    assert exit_code == 0
    for name in [
        "period_summary.csv",
        "corner_filter_summary.csv",
        "machine_corner_summary.csv",
        "xdds_split_summary.csv",
        "shortlist_period_table.csv",
        "report.md",
    ]:
        assert (tmp_path / name).exists()
