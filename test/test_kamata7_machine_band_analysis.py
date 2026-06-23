from __future__ import annotations

import pandas as pd

from eda import kamata7_machine_band_analysis as section_eda


def _make_coords_frame() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"machine_number": 2026, "section": "2023-2031", "floor": "2F"},
            {"machine_number": 2001, "section": "2001-2010", "floor": "2F"},
            {"machine_number": 2099, "section": "2011-2022", "floor": "2F"},
            {"machine_number": 3001, "section": "3001-3016", "floor": "3F"},
            {"machine_number": 3400, "section": "3400-3401", "floor": "3F"},
            {"machine_number": 3401, "section": "3400-3401", "floor": "3F"},
        ]
    )


def _make_raw_frame() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"date": "20260108", "machine_number": 2026, "machine_name": "TETSU", "diff_coins_normalized": 1000, "games_normalized": 1200},
            {"date": "20260109", "machine_number": 2001, "machine_name": "A", "diff_coins_normalized": 10, "games_normalized": 1200},
            {"date": "20260111", "machine_number": 2001, "machine_name": "A", "diff_coins_normalized": 15, "games_normalized": 1200},
            {"date": "20260117", "machine_number": 2099, "machine_name": "B", "diff_coins_normalized": 20, "games_normalized": 1200},
            {"date": "20260118", "machine_number": 3001, "machine_name": "C", "diff_coins_normalized": 30, "games_normalized": 1200},
            {"date": "20260119", "machine_number": 3400, "machine_name": "D", "diff_coins_normalized": 40, "games_normalized": 1200},
            {"date": "20260408", "machine_number": 2026, "machine_name": "TETSU", "diff_coins_normalized": 1200, "games_normalized": 1200},
            {"date": "20260409", "machine_number": 2001, "machine_name": "A", "diff_coins_normalized": 50, "games_normalized": 1200},
            {"date": "20260417", "machine_number": 2099, "machine_name": "B", "diff_coins_normalized": 60, "games_normalized": 1200},
            {"date": "20260418", "machine_number": 3001, "machine_name": "C", "diff_coins_normalized": 70, "games_normalized": 1200},
            {"date": "20260419", "machine_number": 3401, "machine_name": "D", "diff_coins_normalized": 80, "games_normalized": 1200},
            {"date": "20260420", "machine_number": 9999, "machine_name": "DROP", "diff_coins_normalized": 90, "games_normalized": 1200},
        ]
    )


def _make_section_frame() -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    values = {
        "騾壼ｸｸ譌･": {
            "2023-2031": [(2026, 600), (2026, 580)],
            "2001-2010": [(2001, 100), (2001, 120)],
            "2011-2022": [(2099, 50), (2099, 60)],
            "3001-3016": [(3001, -20), (3001, -10)],
            "3400-3401": [(3400, -5), (3401, 0)],
        },
        "7邉ｻ譌･": {
            "2023-2031": [(2026, 650), (2026, 610)],
            "2001-2010": [(2001, 130), (2001, 140)],
            "2011-2022": [(2099, 80), (2099, 90)],
            "3001-3016": [(3001, 0), (3001, 10)],
            "3400-3401": [(3400, 30), (3401, 40)],
        },
        "騾ｱ譛ｫ": {
            "2023-2031": [(2026, 700), (2026, 720)],
            "2001-2010": [(2001, 90), (2001, 100)],
            "2011-2022": [(2099, 70), (2099, 80)],
            "3001-3016": [(3001, 20), (3001, 30)],
            "3400-3401": [(3400, 50), (3401, 60)],
        },
    }
    day_dates = {
        "騾壼ｸｸ譌･": ["20260108", "20260408"],
        "7邉ｻ譌･": ["20260117", "20260417"],
        "騾ｱ譛ｫ": ["20260118", "20260418"],
    }
    floors = {
        "2023-2031": "2F",
        "2001-2010": "2F",
        "2011-2022": "2F",
        "3001-3016": "3F",
        "3400-3401": "3F",
    }
    for day_type, section_map in values.items():
        for period_idx, date in enumerate(day_dates[day_type]):
            for section, pair in section_map.items():
                machine_number, diff = pair[period_idx]
                rows.append(
                    {
                        "date": date,
                        "period": period_idx,
                        "day_type": day_type,
                        "floor": floors[section],
                        "section": section,
                        "machine_number": machine_number,
                        "diff_coins_normalized": diff,
                        "games_normalized": 1200,
                    }
                )
                if section == "2023-2031":
                    rows.append(
                        {
                            "date": date,
                            "period": period_idx,
                            "day_type": day_type,
                            "floor": "2F",
                            "section": section,
                            "machine_number": 2001,
                            "diff_coins_normalized": diff - 500,
                            "games_normalized": 1200,
                        }
                    )
    return pd.DataFrame(rows)


def test_load_data_excludes_tetsu_by_default(monkeypatch) -> None:
    monkeypatch.setattr(section_eda, "base_load_data", lambda _db_path: _make_raw_frame())
    monkeypatch.setattr(section_eda, "load_section_coords", _make_coords_frame)

    loaded = section_eda.load_data(section_eda.DB_PATH, exclude_tetsu=True)

    assert loaded["section"].notna().all()
    assert 2026 not in loaded["machine_number"].tolist()
    assert "DROP" not in loaded["machine_name"].tolist()
    assert set(loaded.loc[loaded["machine_number"].isin([3400, 3401]), "section"]) == {"3400-3401"}
    assert loaded.loc[loaded["date"] == pd.Timestamp("2026-01-11"), "day_type"].eq("1系日").all()


def test_load_data_can_include_tetsu(monkeypatch) -> None:
    monkeypatch.setattr(section_eda, "base_load_data", lambda _db_path: _make_raw_frame())
    monkeypatch.setattr(section_eda, "load_section_coords", _make_coords_frame)

    loaded = section_eda.load_data(section_eda.DB_PATH, exclude_tetsu=False)

    assert 2026 in loaded["machine_number"].tolist()
    assert loaded.loc[loaded["machine_number"] == 2026, "section"].eq("2023-2031").all()


def test_build_section_outputs_and_tetsu_effect() -> None:
    df = _make_section_frame()
    detail_excluded = section_eda.build_section_detail(df[df["machine_number"] != 2026].copy())
    summary_excluded = section_eda.build_section_summary(detail_excluded)
    detail_included = section_eda.build_section_detail(df.copy())
    summary_included = section_eda.build_section_summary(detail_included)

    excluded_row = summary_excluded[
        (summary_excluded["day_type"] == "騾壼ｸｸ譌･")
        & (summary_excluded["floor"] == "2F")
        & (summary_excluded["section"] == "2023-2031")
    ].iloc[0]
    included_row = summary_included[
        (summary_included["day_type"] == "騾壼ｸｸ譌･")
        & (summary_included["floor"] == "2F")
        & (summary_included["section"] == "2023-2031")
    ].iloc[0]

    assert excluded_row["excess"] < included_row["excess"]
    assert excluded_row["avg_diff"] < included_row["avg_diff"]
    assert excluded_row["note"] == "サンプル少（参考値）"


def test_build_report_mentions_tetsu_note_and_include_paths() -> None:
    df = _make_section_frame()
    detail = section_eda.build_section_detail(df)
    summary = section_eda.build_section_summary(detail)
    report = section_eda.build_report(detail, summary, exclude_tetsu=True)

    assert "machine_number=2026" in report
    assert "--include-tetsu" in report
    assert "3400-3401" in report
    assert "サンプル少（参考値）" in report

    detail_path, summary_path, report_path = section_eda._output_paths(
        section_eda.OUTPUT_DIR, exclude_tetsu=True
    )
    assert detail_path.name == "section_detail.csv"
    assert summary_path.name == "section_summary.csv"
    assert report_path.name == "report.md"

    detail_path, summary_path, report_path = section_eda._output_paths(
        section_eda.OUTPUT_DIR, exclude_tetsu=False
    )
    assert detail_path.name == "section_detail_with_tetsu.csv"
    assert summary_path.name == "section_summary_with_tetsu.csv"
    assert report_path.name == "report_with_tetsu.md"


def _make_large_report_frame() -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    sections = [f"S{i:02d}" for i in range(1, 12)]
    day_types = ["通常日", "7系日", "1系日", "週末"]
    for period in [0, 1, 2]:
        for day_type in day_types:
            for idx, section in enumerate(sections):
                rows.append(
                    {
                        "period": period,
                        "day_type": day_type,
                        "floor": "2F",
                        "section": section,
                        "avg_diff": float(idx),
                        "baseline": 0.0,
                        "excess": float(idx),
                        "n_machine_days": 60,
                        "n_dates": 3,
                        "note": "",
                    }
                )
    return pd.DataFrame(rows)


def test_build_report_shows_all_sections_and_ichikei_day_type() -> None:
    detail = pd.DataFrame(
        [
            {"period": 0, "day_type": "通常日", "floor": "2F", "section": "S01", "avg_diff": 0.0, "baseline": 0.0, "excess": 0.0, "n_machine_days": 60, "n_dates": 3, "note": ""},
            {"period": 1, "day_type": "7系日", "floor": "2F", "section": "S01", "avg_diff": 0.0, "baseline": 0.0, "excess": 0.0, "n_machine_days": 60, "n_dates": 3, "note": ""},
            {"period": 2, "day_type": "1系日", "floor": "2F", "section": "S01", "avg_diff": 0.0, "baseline": 0.0, "excess": 0.0, "n_machine_days": 60, "n_dates": 3, "note": ""},
        ]
    )
    summary = _make_large_report_frame()

    report = section_eda.build_report(detail, summary, exclude_tetsu=True)

    assert "1系日" in report
    assert "全" in report
    assert "S06" in report
    assert "S11" in report
