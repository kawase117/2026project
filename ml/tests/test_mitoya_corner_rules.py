from __future__ import annotations

from pathlib import Path

import pandas as pd

from ml.corner_section.mitoya_jug_corner1_dd_weekday_rules import main as jug_main
from ml.corner_section.mitoya_mix_dd_weekday_rules import main as mix_main


def _seed_corner_composite(output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(
        [
            {"island": "main_jug", "dd_group": "4系", "day_of_week": "Mon", "rank": 1, "avg_diff": 2000, "avg_games": 5200, "plus_rate": 85.0, "sample_n": 12, "corner_metric": "physical_corner"},
            {"island": "main_jug", "dd_group": "4系", "day_of_week": "Mon", "rank": 1, "avg_diff": 2200, "avg_games": 5300, "plus_rate": 82.0, "sample_n": 11, "corner_metric": "rank_from_aisle"},
            {"island": "main_jug", "dd_group": "5系", "day_of_week": "Tue", "rank": 1, "avg_diff": 1500, "avg_games": 4800, "plus_rate": 75.0, "sample_n": 8, "corner_metric": "physical_corner"},
            {"island": "main_jug", "dd_group": "5系", "day_of_week": "Tue", "rank": 1, "avg_diff": 1600, "avg_games": 4900, "plus_rate": 78.0, "sample_n": 9, "corner_metric": "rank_from_aisle"},
            {"island": "main_jug", "dd_group": "7系", "day_of_week": "Fri", "rank": 1, "avg_diff": 400, "avg_games": 4300, "plus_rate": 55.0, "sample_n": 6, "corner_metric": "physical_corner"},
            {"island": "main_jug", "dd_group": "7系", "day_of_week": "Fri", "rank": 1, "avg_diff": 410, "avg_games": 4350, "plus_rate": 57.0, "sample_n": 6, "corner_metric": "rank_from_aisle"},
            {"island": "main_jug", "dd_group": "その他", "day_of_week": "Sun", "rank": 2, "avg_diff": 9999, "avg_games": 9999, "plus_rate": 100.0, "sample_n": 99, "corner_metric": "physical_corner"},
            {"island": "main_mix", "dd_group": "4系", "day_of_week": "Mon", "rank": 1, "avg_diff": 3600, "avg_games": 6100, "plus_rate": 100.0, "sample_n": 24, "corner_metric": "physical_corner"},
            {"island": "main_mix", "dd_group": "4系", "day_of_week": "Mon", "rank": 1, "avg_diff": 3700, "avg_games": 6200, "plus_rate": 100.0, "sample_n": 22, "corner_metric": "rank_from_aisle"},
            {"island": "main_mix", "dd_group": "5系", "day_of_week": "Tue", "rank": 3, "avg_diff": 2600, "avg_games": 5000, "plus_rate": 85.0, "sample_n": 20, "corner_metric": "physical_corner"},
            {"island": "main_mix", "dd_group": "7系", "day_of_week": "Wed", "rank": 2, "avg_diff": 1800, "avg_games": 4600, "plus_rate": 78.0, "sample_n": 18, "corner_metric": "physical_corner"},
            {"island": "main_mix", "dd_group": "その他", "day_of_week": "Thu", "rank": 4, "avg_diff": 500, "avg_games": 3800, "plus_rate": 50.0, "sample_n": 21, "corner_metric": "physical_corner"},
            {"island": "bari", "dd_group": "4系", "day_of_week": "Mon", "rank": 1, "avg_diff": 9999, "avg_games": 9999, "plus_rate": 100.0, "sample_n": 99, "corner_metric": "physical_corner"},
        ]
    ).to_csv(output_dir / "corner_composite.csv", index=False, encoding="utf-8-sig")


def test_jug_corner_rules(tmp_path: Path, capsys) -> None:
    out_dir = tmp_path / "data" / "mitoya_corner_deep"
    _seed_corner_composite(out_dir)

    exit_code = jug_main(["--output-dir", str(out_dir)])

    assert exit_code == 0
    csv_path = out_dir / "jug_corner1_rules.csv"
    assert csv_path.exists()
    df = pd.read_csv(csv_path)
    assert list(df.columns) == [
        "dd_group",
        "day_of_week",
        "rank_tier",
        "avg_diff",
        "plus_rate",
        "sample_n",
        "confidence_reason",
    ]
    assert set(df["rank_tier"].unique()) == {"A", "B", "Avoid"}
    assert (df["sample_n"] >= 5).all()

    captured = capsys.readouterr().out
    assert "=== みとや main_jug 角番1 運用ルール ===" in captured
    assert "[狙い目ランク A" in captured
    assert "[回避推奨ランク" in captured


def test_mix_dd_weekday_rules(tmp_path: Path, capsys) -> None:
    out_dir = tmp_path / "data" / "mitoya_corner_deep"
    _seed_corner_composite(out_dir)

    exit_code = mix_main(["--output-dir", str(out_dir)])

    assert exit_code == 0
    csv_path = out_dir / "mix_dd_weekday_rules.csv"
    assert csv_path.exists()
    df = pd.read_csv(csv_path)
    assert list(df.columns) == [
        "dd_group",
        "day_of_week",
        "rank_tier",
        "avg_diff",
        "plus_rate",
        "sample_n",
    ]
    # dd_group × day_of_week が一意になっていること（rank 集約済み）
    assert df.duplicated(subset=["dd_group", "day_of_week"]).sum() == 0
    assert set(df["rank_tier"].unique()).issubset({"A", "B", "C", "Avoid"})

    captured = capsys.readouterr().out
    assert "AT島" in captured
    assert "AT島全台の加重平均" in captured

