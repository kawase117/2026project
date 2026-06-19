from __future__ import annotations

from pathlib import Path

import pandas as pd

from ml.analysis import kamata7_kakuban_floorlr_eda as floorlr_mod


def _make_frame(
    *,
    segment: str,
    rows: list[dict[str, object]],
) -> pd.DataFrame:
    base_rows: list[dict[str, object]] = []
    for idx, row in enumerate(rows, start=1):
        base_rows.append(
            {
                "date": row["date"],
                "dd": row["dd"],
                "segment": segment,
                "rank_from_min": row["rank_from_min"],
                "lr_side": row["lr_side"],
                "section_size_group": row["section_size_group"],
                "section_machine_count": row.get("section_machine_count", 10),
                "machine_number": row.get("machine_number", 1000 + idx),
                "diff_coins_normalized": row["diff_coins_normalized"],
                "games_normalized": row["games_normalized"],
                "pay_rate": row.get("pay_rate"),
                "section": row.get("section", "S1"),
                "X": row.get("X", 10 + idx),
                "Y": row.get("Y", 1 + idx),
            }
        )
    return pd.DataFrame(base_rows)


def test_aggregate_segment_frame_uses_all_kakuban_ranks() -> None:
    frame = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-06-01"] * 4),
            "dd": [1, 1, 1, 2],
            "segment": ["2F"] * 4,
            "rank_from_min": [1, 5, 13, 6],
            "lr_side": ["L", "L", "R", "R"],
            "section_size_group": ["small", "small", "medium", "large"],
            "section_machine_count": [8, 8, 12, 16],
            "machine_number": [101, 102, 103, 104],
            "diff_coins_normalized": [0, 300, -100, 150],
            "games_normalized": [1000, 1000, 1000, 1000],
            "section": ["S1", "S1", "S2", "S3"],
            "X": [1, 2, 3, 4],
            "Y": [1, 2, 3, 4],
        }
    )

    out = floorlr_mod._aggregate_segment_frame(frame)

    assert out["rank_from_min"].tolist() == [1, 5, 13, 6]
    assert out["section_size_group"].tolist() == ["small", "small", "medium", "large"]
    assert out["pay_rate"].round(2).tolist() == [100.0, 110.0, 96.67, 105.0]


def test_run_analysis_writes_expected_outputs(tmp_path: Path, monkeypatch) -> None:
    frame_2f = pd.concat(
        [
            _make_frame(
                segment="2F",
                rows=[
                    {
                        "date": "2026-06-01",
                        "dd": 1,
                        "rank_from_min": 5,
                        "lr_side": "L",
                        "section_size_group": "small",
                        "section_machine_count": 8,
                        "diff_coins_normalized": 0,
                        "games_normalized": 1000,
                    },
                    {
                        "date": "2026-06-01",
                        "dd": 1,
                        "rank_from_min": 6,
                        "lr_side": "L",
                        "section_size_group": "small",
                        "section_machine_count": 8,
                        "diff_coins_normalized": 300,
                        "games_normalized": 1000,
                    },
                    {
                        "date": "2026-06-02",
                        "dd": 2,
                        "rank_from_min": 7,
                        "lr_side": "R",
                        "section_size_group": "medium",
                        "section_machine_count": 12,
                        "diff_coins_normalized": 150,
                        "games_normalized": 1000,
                    },
                ],
            ),
            _make_frame(
                segment="2F",
                rows=[
                    {
                        "date": "2026-06-01",
                        "dd": 1,
                        "rank_from_min": 6,
                        "lr_side": "R",
                        "section_size_group": "large",
                        "section_machine_count": 16,
                        "diff_coins_normalized": 50,
                        "games_normalized": 1000,
                    }
                ],
            ),
        ],
        ignore_index=True,
    )
    frame_3f = pd.concat(
        [
            _make_frame(
                segment="3F",
                rows=[
                    {
                        "date": "2026-06-01",
                        "dd": 1,
                        "rank_from_min": 6,
                        "lr_side": "L",
                        "section_size_group": "medium",
                        "section_machine_count": 12,
                        "diff_coins_normalized": 100,
                        "games_normalized": 1000,
                    },
                    {
                        "date": "2026-06-02",
                        "dd": 2,
                        "rank_from_min": 11,
                        "lr_side": "R",
                        "section_size_group": "large",
                        "section_machine_count": 16,
                        "diff_coins_normalized": 200,
                        "games_normalized": 1000,
                    },
                ],
            ),
            _make_frame(
                segment="3F",
                rows=[
                    {
                        "date": "2026-06-02",
                        "dd": 2,
                        "rank_from_min": 5,
                        "lr_side": "R",
                        "section_size_group": "large",
                        "section_machine_count": 16,
                        "diff_coins_normalized": 400,
                        "games_normalized": 1000,
                    }
                ],
            ),
        ],
        ignore_index=True,
    )
    frame_at = pd.concat([frame_2f.copy(), frame_3f.copy()], ignore_index=True)
    frame_at["segment"] = "AT"

    def fake_build_segment_frames(*, coords_2f, coords_3f):
        return {"2F": frame_2f.copy(), "3F": frame_3f.copy(), "AT": frame_at.copy()}

    monkeypatch.setattr(floorlr_mod, "_build_segment_frames", fake_build_segment_frames)

    output_dir = tmp_path / "out"
    result = floorlr_mod.run_analysis(
        coords_2f=tmp_path / "coords_2f.csv",
        coords_3f=tmp_path / "coords_3f.csv",
        output_dir=output_dir,
    )

    assert (output_dir / "kamata7_2F_kakuban_dd_floorlr.csv").exists()
    assert (output_dir / "kamata7_3F_kakuban_dd_floorlr.csv").exists()
    assert (output_dir / "kamata7_AT_kakuban_dd_floorlr.csv").exists()
    assert (output_dir / "kamata7_peak_ranks_by_dd_floorlr.csv").exists()
    assert (output_dir / "heatmap_2F_kakuban_dd_floorlr.png").exists()
    assert (output_dir / "report.md").exists()

    peak = result["peak_table"]
    assert not peak.empty

    best_2f_small_dd1 = peak[
        (peak["segment"].eq("2F"))
        & (peak["section_size_group"].eq("small"))
        & (peak["lr_side"].eq("L"))
        & (peak["DD"].eq(1))
    ].iloc[0]
    assert int(best_2f_small_dd1["best_rank_from_min"]) == 6
    assert round(float(best_2f_small_dd1["best_pay_rate"]), 2) == 110.0

    best_at_small_dd1 = peak[
        (peak["segment"].eq("AT"))
        & (peak["section_size_group"].eq("small"))
        & (peak["lr_side"].eq("L"))
        & (peak["DD"].eq(1))
    ].iloc[0]
    assert int(best_at_small_dd1["best_rank_from_min"]) == 6

    report = (output_dir / "report.md").read_text(encoding="utf-8")
    assert "Phase 3-4 uses all kakuban ranks (1-13)." in report
    assert "Phase 6 visualizations are limited to ranks 5-11." in report
    assert "section_size means the actual machine count per island section" in report
