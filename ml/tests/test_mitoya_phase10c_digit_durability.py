from __future__ import annotations

from pathlib import Path

import pandas as pd


TARGET_SECTIONS = ["641-657", "658-674", "675-691"]
DATES = ["20260602", "20260603", "20260605", "20260608", "20260609", "20260610"]


def _make_frame() -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    digit_base = {
        "4": 180.0,
        "2": 170.0,
        "3": 160.0,
        "1": 120.0,
        "5": 110.0,
        "6": 100.0,
        "7": 90.0,
        "8": 80.0,
        "9": 70.0,
        "0": 60.0,
    }
    for date_idx, date in enumerate(DATES):
        after_regime = date >= "20260606"
        for section_idx, section in enumerate(TARGET_SECTIONS):
            for digit in range(10):
                for slot in range(3):
                    machine_number = 10000 + section_idx * 1000 + digit * 10 + slot
                    name_prefix = "ジャグラーB" if after_regime else "ジャグラーA"
                    machine_name = f"{name_prefix}-{section}-{digit}-{slot}"
                    rows.append(
                        {
                            "date": date,
                            "section": section,
                            "machine_number": machine_number,
                            "machine_name": machine_name,
                            "diff": float(digit_base[str(digit)] + section_idx * 5 + slot * 2 + date_idx),
                            "games": 1200,
                            "x": 1 + slot,
                            "y": 1,
                            "rank_from_aisle": 2,
                            "last_digit": str(digit),
                        }
                    )
    return pd.DataFrame(rows)


def test_build_all_artifacts_returns_expected_tables() -> None:
    from eda import mitoya_phase10c_digit_durability as phase10c

    artifacts = phase10c.build_all_artifacts(_make_frame())

    assert {
        "split_half",
        "regime_split",
        "machine_dependency",
        "corner24_split_half",
        "durability_summary",
        "report",
    } <= set(artifacts)

    split_half = artifacts["split_half"]
    assert {
        "row_type",
        "half",
        "last_digit",
        "n",
        "avg_diff",
        "plus_rate",
        "rank",
        "kw_p_value",
        "kw_epsilon_sq",
    } <= set(split_half.columns)
    split_summary = split_half.loc[split_half["row_type"].astype(str) == "summary"].iloc[0]
    assert split_summary["top3_overlap"] >= 2
    assert str(split_summary["top3_front"]).split(",")[:3] == ["4", "2", "3"]
    assert str(split_summary["top3_back"]).split(",")[:3] == ["4", "2", "3"]

    regime = artifacts["regime_split"]
    regime_summary = regime.loc[regime["row_type"].astype(str) == "summary"].iloc[0]
    assert regime_summary["split_date"] == "20260608"
    assert regime_summary["top3_overlap"] >= 2

    machine = artifacts["machine_dependency"]
    assert {
        "row_type",
        "digit",
        "machine_number",
        "machine_name",
        "top1_share",
        "top2_share",
        "full_avg_diff",
        "excl_top1_avg_diff",
        "excl_top2_avg_diff",
    } <= set(machine.columns)
    machine_summary = machine.loc[machine["row_type"].astype(str) == "summary"]
    assert set(machine_summary["digit"].astype(str)) == {"2", "4"}
    assert float(machine_summary["top2_share"].max()) < 30.0

    corner24 = artifacts["corner24_split_half"]
    assert {"row_type", "half", "last_digit", "n", "avg_diff", "plus_rate", "rank", "kw_p_value"} <= set(
        corner24.columns
    )
    corner_summary = corner24.loc[corner24["row_type"].astype(str) == "summary"].iloc[0]
    assert corner_summary["top3_overlap"] >= 2

    summary = artifacts["durability_summary"]
    assert list(summary.columns) == ["test", "target", "pass/fail", "note"]
    assert set(summary["test"]) == {"split_half", "regime", "machine_dependency", "corner24"}


def test_main_writes_requested_csvs(tmp_path: Path, monkeypatch) -> None:
    from eda import mitoya_phase10c_digit_durability as phase10c

    monkeypatch.setattr(phase10c, "load_mitoya_frame", lambda join_layout=True: _make_frame())

    exit_code = phase10c.main(["--output-dir", str(tmp_path)])

    assert exit_code == 0
    for name in [
        "split_half.csv",
        "regime_split.csv",
        "machine_dependency.csv",
        "corner24_split_half.csv",
        "durability_summary.csv",
        "report.md",
    ]:
        assert (tmp_path / name).exists()
