from __future__ import annotations

from pathlib import Path

import pandas as pd

from ml.analysis import kamata7_kakuban_dd_precision_eda as precision_mod


def _make_frame(
    *,
    floor: str,
    machine_type_segment: str,
    rows: list[dict[str, object]],
) -> pd.DataFrame:
    base_rows: list[dict[str, object]] = []
    for idx, row in enumerate(rows, start=1):
        base_rows.append(
            {
                "date": row["date"],
                "dd": row["dd"],
                "floor": floor,
                "machine_number": row.get("machine_number", 1000 + idx),
                "machine_name": f"M{idx}",
                "machine_type_segment": machine_type_segment,
                "section": row.get("section", "S1"),
                "section_size": row.get("section_size", 10),
                "section_size_group": row.get("section_size_group", "small"),
                "section_machine_count": row.get("section_machine_count", 10),
                "rank_from_min": row["rank_from_min"],
                "diff_coins_normalized": row["diff_coins_normalized"],
                "games_normalized": row["games_normalized"],
            }
        )
    return pd.DataFrame(base_rows)


def test_aggregate_segment_frame_uses_all_kakuban_ranks() -> None:
    frame = pd.DataFrame(
        {
            "dd": [1, 1, 1, 2],
            "rank_from_min": [1, 5, 13, 6],
            "section_size_group": ["small", "small", "medium", "large"],
            "section_machine_count": [8, 8, 12, 16],
            "diff_coins_normalized": [0, 300, -100, 150],
            "games_normalized": [1000, 1000, 1000, 1000],
            "machine_number": [101, 102, 103, 104],
            "floor": ["2F", "2F", "2F", "2F"],
            "machine_type_segment": ["A", "A", "A", "N"],
            "date": pd.to_datetime(["2026-06-01"] * 4),
        }
    )

    out = precision_mod._aggregate_segment_frame(frame)

    assert out["rank_from_min"].tolist() == [1, 5, 13, 6]
    assert out["section_size_group"].tolist() == ["small", "small", "medium", "large"]
    assert out["pay_rate"].round(2).tolist() == [100.0, 110.0, 96.67, 105.0]


def test_run_analysis_writes_expected_outputs(tmp_path: Path, monkeypatch) -> None:
    frame_2f = pd.concat(
        [
            _make_frame(
                floor="2F",
                machine_type_segment="A",
                rows=[
                    {
                        "date": "2026-06-01",
                        "dd": 1,
                        "rank_from_min": 5,
                        "section_size": "small",
                        "section_machine_count": 8,
                        "diff_coins_normalized": 0,
                        "games_normalized": 1000,
                    },
                    {
                        "date": "2026-06-01",
                        "dd": 1,
                        "rank_from_min": 6,
                        "section_size": "small",
                        "section_machine_count": 8,
                        "diff_coins_normalized": 300,
                        "games_normalized": 1000,
                    },
                    {
                        "date": "2026-06-02",
                        "dd": 2,
                        "rank_from_min": 7,
                        "section_size": "medium",
                        "section_machine_count": 12,
                        "diff_coins_normalized": 150,
                        "games_normalized": 1000,
                    },
                ],
            ),
            _make_frame(
                floor="2F",
                machine_type_segment="N",
                rows=[
                    {
                        "date": "2026-06-01",
                        "dd": 1,
                        "rank_from_min": 5,
                        "section_size": "small",
                        "section_machine_count": 8,
                        "diff_coins_normalized": 200,
                        "games_normalized": 1000,
                    },
                    {
                        "date": "2026-06-02",
                        "dd": 2,
                        "rank_from_min": 6,
                        "section_size": "large",
                        "section_machine_count": 16,
                        "diff_coins_normalized": 0,
                        "games_normalized": 1000,
                    },
                ],
            ),
        ],
        ignore_index=True,
    )
    frame_3f = pd.concat(
        [
            _make_frame(
                floor="3F",
                machine_type_segment="A",
                rows=[
                    {
                        "date": "2026-06-01",
                        "dd": 1,
                        "rank_from_min": 6,
                        "section_size": "medium",
                        "section_machine_count": 12,
                        "diff_coins_normalized": 100,
                        "games_normalized": 1000,
                    },
                    {
                        "date": "2026-06-02",
                        "dd": 2,
                        "rank_from_min": 11,
                        "section_size": "large",
                        "section_machine_count": 16,
                        "diff_coins_normalized": 200,
                        "games_normalized": 1000,
                    },
                ],
            ),
            _make_frame(
                floor="3F",
                machine_type_segment="N",
                rows=[
                    {
                        "date": "2026-06-01",
                        "dd": 1,
                        "rank_from_min": 6,
                        "section_size": "medium",
                        "section_machine_count": 12,
                        "diff_coins_normalized": 50,
                        "games_normalized": 1000,
                    },
                    {
                        "date": "2026-06-02",
                        "dd": 2,
                        "rank_from_min": 5,
                        "section_size": "large",
                        "section_machine_count": 16,
                        "diff_coins_normalized": 400,
                        "games_normalized": 1000,
                    },
                ],
            ),
        ],
        ignore_index=True,
    )

    def fake_build_floor_frames(**kwargs):
        return {"2F": frame_2f.copy(), "3F": frame_3f.copy()}

    monkeypatch.setattr(precision_mod, "_build_floor_frames", fake_build_floor_frames)

    output_dir = tmp_path / "out"
    result = precision_mod.run_analysis(
        db_path=tmp_path / "dummy.db",
        coords_2f=tmp_path / "coords_2f.csv",
        coords_3f=tmp_path / "coords_3f.csv",
        output_dir=output_dir,
        min_games=0,
        min_section_size=0,
        min_cell_games=0,
    )

    assert (output_dir / "kamata7_2F_kakuban_dd_sectionsize.csv").exists()
    assert (output_dir / "kamata7_3F_kakuban_dd_sectionsize.csv").exists()
    assert (output_dir / "kamata7_AT_kakuban_dd_sectionsize.csv").exists()
    assert (output_dir / "kamata7_peak_ranks_by_dd_sectionsize.csv").exists()
    assert (output_dir / "heatmap_2F_kakuban_dd_sectionsize.png").exists()
    assert (output_dir / "report.md").exists()

    peak = result["peak_table"]
    assert not peak.empty

    best_2f_small_dd1 = peak[
        (peak["segment"].eq("2F")) & (peak["section_size"].eq("small")) & (peak["DD"].eq(1))
    ].iloc[0]
    assert int(best_2f_small_dd1["best_rank_from_min"]) == 6
    assert round(float(best_2f_small_dd1["best_pay_rate"]), 2) == 110.0

    best_at_small_dd1 = peak[
        (peak["segment"].eq("AT")) & (peak["section_size"].eq("small")) & (peak["DD"].eq(1))
    ].iloc[0]
    assert int(best_at_small_dd1["best_rank_from_min"]) == 5

    report = (output_dir / "report.md").read_text(encoding="utf-8")
    assert "Phase 3-4 uses all kakuban ranks (1-13)." in report
    assert "Phase 6 visualizations are limited to ranks 5-11." in report
    assert "## 1. Coverage" in report
