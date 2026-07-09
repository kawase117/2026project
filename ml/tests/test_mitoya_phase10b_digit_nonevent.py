from __future__ import annotations

from pathlib import Path

import pandas as pd


SEGMENT_SPECS = [
    (
        "501-522",
        "horizontal",
        "jug",
        [1, 2, 3],
        [1, 1, 1],
        ["マイジャグラーV", "ファンキージャグラー2", "アイムジャグラーEX-TP"],
    ),
    ("523-539", "horizontal", "non_jug", [11, 12, 13], [2, 2, 2], ["A", "B", "C"]),
    (
        "692-700",
        "vertical",
        "jug",
        [21, 22, 23],
        [1, 1, 1],
        ["マイジャグラーV", "ファンキージャグラー2", "アイムジャグラーEX-TP"],
    ),
    ("701-711", "vertical", "non_jug", [31, 32, 33], [2, 2, 2], ["A", "B", "C"]),
    ("805-815", "mixed", "mixed", [41, 42, 43], [3, 3, 3], ["マイジャグラーV", "A", "ファンキージャグラー2"]),
]

DATE_SPECS = [
    ("20260602", "非イベント日", 0),
    ("20260604", "X_DDS", 30),
    ("20260611", "ゾロ目日", 20),
    ("20260505", "強ゾロ目", 40),
    ("20260630", "月末", 10),
]


def _make_frame() -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    segment_offset = {
        "501-522": 120,
        "523-539": 60,
        "692-700": -40,
        "701-711": -10,
        "805-815": 30,
    }
    for date, _, category_offset in DATE_SPECS:
        for section, orientation, jug_kind, machine_numbers, ys, names in SEGMENT_SPECS:
            for digit in range(10):
                idx = digit % len(machine_numbers)
                machine_number = machine_numbers[idx] * 10 + digit
                machine_name = names[idx]
                if jug_kind == "jug" and "ジャグラー" not in machine_name:
                    machine_name = f"ジャグラー{machine_name}"
                if jug_kind == "non_jug" and "ジャグラー" in machine_name:
                    machine_name = machine_name.replace("ジャグラー", "")
                if section == "805-815" and digit % 2 == 0:
                    machine_name = "ジャグラーMIX" if digit % 4 == 0 else "MIX"
                x = digit + 1 if orientation != "vertical" else 1
                y = ys[idx] if orientation != "vertical" else digit + 1
                diff = float(segment_offset[section] + category_offset + (digit - 5) * 20)
                rows.append(
                    {
                        "date": date,
                        "section": section,
                        "machine_number": machine_number,
                        "machine_name": machine_name,
                        "diff": diff,
                        "games": 1200,
                        "x": x,
                        "y": y,
                        "rank_from_aisle": digit + 1,
                        "last_digit": str(digit),
                    }
                )
    return pd.DataFrame(rows)


def test_build_all_artifacts_returns_expected_outputs() -> None:
    from eda import mitoya_phase10b_digit_nonevent as phase10b

    artifacts = phase10b.build_all_artifacts(_make_frame())

    assert {
        "nonevent_digit_kw",
        "nonevent_digit_ranking",
        "event_category_digit_kw",
        "nonevent_corner_digit",
        "report",
    } <= set(artifacts)

    kw = artifacts["nonevent_digit_kw"]
    assert {"segment", "kw_stat", "p_value", "epsilon_sq", "n_groups", "n"} <= set(kw.columns)
    assert set(kw["segment"].astype(str)) == {"h_jug", "h_nonjug", "v_jug", "v_nonjug", "mixed_805"}
    assert set(kw["n"].astype(int)) == {10}

    ranking = artifacts["nonevent_digit_ranking"]
    assert {"segment", "last_digit", "n", "avg_diff", "plus_rate"} <= set(ranking.columns)
    assert len(ranking) == 50
    assert set(ranking["last_digit"].astype(str)) == {str(i) for i in range(10)}

    event_kw = artifacts["event_category_digit_kw"]
    assert {"segment", "event_category", "kw_stat", "p_value", "epsilon_sq", "n_groups", "n"} <= set(event_kw.columns)
    assert set(event_kw["event_category"].astype(str)) == {"X_DDS", "ゾロ目日", "強ゾロ目", "月末", "非イベント日"}
    assert set(event_kw["n"].astype(int)) == {10}

    corner = artifacts["nonevent_corner_digit"]
    assert {"segment", "corner_bucket", "last_digit", "n", "avg_diff", "plus_rate"} <= set(corner.columns)
    assert set(corner["segment"].astype(str)) == {"h_jug", "h_nonjug"}
    assert len(corner) == 80


def test_main_writes_requested_csvs(tmp_path: Path, monkeypatch) -> None:
    from eda import mitoya_phase10b_digit_nonevent as phase10b

    monkeypatch.setattr(phase10b, "load_mitoya_frame", lambda join_layout=True: _make_frame())

    exit_code = phase10b.main(["--output-dir", str(tmp_path)])

    assert exit_code == 0
    for name in [
        "nonevent_digit_kw.csv",
        "nonevent_digit_ranking.csv",
        "event_category_digit_kw.csv",
        "nonevent_corner_digit.csv",
        "report.md",
    ]:
        assert (tmp_path / name).exists()
