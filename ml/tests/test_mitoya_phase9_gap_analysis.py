from __future__ import annotations

from pathlib import Path

import pandas as pd


def _make_gap_frame() -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for dd in range(1, 32):
        rows.append(
            {
                "date": f"202606{dd:02d}",
                "dd": dd,
                "section": "501-522",
                "machine_number": 501 + dd,
                "machine_name": f"M{dd:02d}",
                "diff": float(dd * 10),
                "games": 1000,
                "last_digit": str(dd % 10),
                "is_zorome": 1 if dd in {11, 22} else 0,
                "is_reversed_section": 0,
                "rank_from_aisle": (dd % 4) + 1,
                "corner_bucket": "corner1"
                if dd % 4 == 0
                else ("corner2-4" if dd % 4 == 1 else ("corner5-9" if dd % 4 == 2 else "corner10+")),
                "debut_phase": "pre_existing"
                if dd <= 8
                else ("debut" if dd <= 16 else ("growth" if dd <= 24 else "mature")),
            }
        )
        rows.append(
            {
                "date": f"202606{dd:02d}",
                "dd": dd,
                "section": "523-539",
                "machine_number": 700 + dd,
                "machine_name": f"R{dd:02d}",
                "diff": float(dd * 5),
                "games": 1000,
                "last_digit": str((dd + 1) % 10),
                "is_zorome": 1 if dd in {11, 22} else 0,
                "is_reversed_section": 1,
                "rank_from_aisle": (dd % 3) + 1,
                "corner_bucket": "corner1" if dd % 3 == 0 else ("corner2-4" if dd % 3 == 1 else "corner5-9"),
                "debut_phase": "pre_existing"
                if dd <= 8
                else ("debut" if dd <= 16 else ("growth" if dd <= 24 else "mature")),
            }
        )
    return pd.DataFrame(rows)


def test_build_all_artifacts_covers_all_four_analyses() -> None:
    from eda import mitoya_phase9_gap_analysis as phase9

    frame = _make_gap_frame()
    artifacts = phase9.build_all_artifacts(frame, sections=["501-522", "523-539"], main_sections=["501-522"])

    assert {
        "last_digit_by_section",
        "zorome_by_section",
        "xdds_corner_interaction",
        "debut_event_premium",
        "dd_fullspectrum",
        "report",
    } <= set(artifacts)

    last_digit = artifacts["last_digit_by_section"]
    assert {"section", "is_reversed_section", "last_digit", "n", "avg_diff", "kw_stat", "p_value", "epsilon_sq"} <= set(
        last_digit.columns
    )

    zorome = artifacts["zorome_by_section"]
    assert {"section", "is_reversed_section", "avg_diff_zorome", "avg_diff_non_zorome", "zorome_lift"} <= set(
        zorome.columns
    )

    xdds_corner = artifacts["xdds_corner_interaction"]
    assert {
        "section",
        "is_reversed_section",
        "corner_bucket",
        "avg_diff_xdds",
        "avg_diff_non_xdds",
        "xdds_premium",
    } <= set(xdds_corner.columns)

    debut = artifacts["debut_event_premium"]
    assert set(debut["debut_phase"]) == {"pre_existing", "debut", "growth", "mature"}
    assert {
        "section",
        "is_reversed_section",
        "debut_phase",
        "avg_diff_xdds",
        "avg_diff_non_xdds",
        "event_premium",
    } <= set(debut.columns)

    dd = artifacts["dd_fullspectrum"]
    assert len(dd) == 31
    assert dd["dd"].tolist() == list(range(1, 32))
    assert {
        "overall_avg_diff",
        "overall_hit104_rate_pct",
        "overall_n",
        "reversed0_avg_diff",
        "reversed0_n",
        "reversed0_corner1_4_avg_diff",
        "reversed0_corner1_4_n",
    } <= set(dd.columns)


def test_main_writes_requested_csvs(tmp_path: Path, monkeypatch) -> None:
    from eda import mitoya_phase9_gap_analysis as phase9

    monkeypatch.setattr(phase9, "load_mitoya_frame", lambda join_layout=True: _make_gap_frame())

    exit_code = phase9.main(
        ["--output-dir", str(tmp_path), "--sections", "501-522", "523-539", "--main-sections", "501-522"]
    )

    assert exit_code == 0
    for name in [
        "last_digit_by_section.csv",
        "zorome_by_section.csv",
        "xdds_corner_interaction.csv",
        "debut_event_premium.csv",
        "dd_fullspectrum.csv",
        "report.md",
    ]:
        assert (tmp_path / name).exists()
