from __future__ import annotations

from pathlib import Path

import pandas as pd


DATES = ["20260604", "20260607", "20260614", "20260617", "20260624", "20260627"]
RANKS = [1, 2, 3, 4, 5]


def _make_frame() -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    segment_specs = [
        ("h_jug", "501-522", "horizontal", True, [501, 502, 503, 504, 505], [1, 2, 3, 4, 5], [1, 1, 1, 1, 1]),
        ("h_nonjug", "523-539", "horizontal", False, [523, 524, 525, 526, 527], [1, 2, 3, 4, 5], [1, 1, 1, 1, 1]),
        ("v_jug", "692-700", "vertical", True, [692, 693, 694, 695, 696], [1, 1, 1, 1, 1], [1, 2, 3, 4, 5]),
        ("v_nonjug", "701-711", "vertical", False, [701, 702, 703, 704, 705], [1, 1, 1, 1, 1], [1, 2, 3, 4, 5]),
        ("mixed_805", "805-815", "horizontal", False, [805, 806, 807, 808, 809], [1, 2, 3, 4, 5], [1, 1, 1, 1, 1]),
    ]
    segment_base = {
        "h_jug": 120.0,
        "h_nonjug": 60.0,
        "v_jug": 30.0,
        "v_nonjug": 10.0,
        "mixed_805": -10.0,
    }
    rank_base = {1: 620.0, 2: 420.0, 3: 250.0, 4: 120.0, 5: 20.0}
    dd_base = {4: 0.0, 7: 40.0, 14: 20.0, 17: 30.0, 24: 10.0, 27: 5.0}
    rank1_dd_bonus = {4: 0.0, 7: 240.0, 14: 50.0, 17: 80.0, 24: 30.0, 27: 15.0}
    segment_rank1_bonus = {
        "h_jug": 60.0,
        "h_nonjug": 180.0,
        "v_jug": 20.0,
        "v_nonjug": 10.0,
        "mixed_805": 0.0,
    }

    for date_idx, date in enumerate(DATES):
        dd = int(date[-2:])
        for segment_idx, (segment, section, orientation, is_jug, machine_numbers, xs, ys) in enumerate(segment_specs):
            for rank, machine_number, x, y in zip(RANKS, machine_numbers, xs, ys):
                machine_name = f"{'ジャグラー' if is_jug else 'ノーマル'}-{segment}-{rank}"
                diff = segment_base[segment] + rank_base[rank] + dd_base[dd] + date_idx * 2.0 + segment_idx * 3.0
                if rank == 1:
                    diff += rank1_dd_bonus[dd] + segment_rank1_bonus[segment]
                if segment == "mixed_805" and rank == 1:
                    machine_name = "ジャグラー-mixed_805-1"
                if segment == "mixed_805" and rank in {2, 4}:
                    machine_name = f"ノーマル-mixed_805-{rank}"
                rows.append(
                    {
                        "date": date,
                        "section": section,
                        "machine_number": machine_number + date_idx * 100 + segment_idx * 10,
                        "machine_name": machine_name,
                        "diff": float(diff),
                        "games": 1200,
                        "x": x,
                        "y": y,
                        "rank_from_aisle": rank,
                    }
                )
    return pd.DataFrame(rows)


def test_build_all_artifacts_returns_expected_tables() -> None:
    from eda import mitoya_phase10d_xdds_corner_deep as phase10d

    artifacts = phase10d.build_all_artifacts(_make_frame())

    assert {"xdds_fine_rank", "dd_corner1_delta", "xdds_fine_rank_kw", "dd_corner1_mwu", "report"} <= set(artifacts)

    fine_rank = artifacts["xdds_fine_rank"]
    assert list(fine_rank.columns) == ["segment", "rank_from_aisle", "n", "avg_diff", "plus_rate"]
    assert len(fine_rank) == 25
    for segment in ["h_jug", "h_nonjug", "v_jug", "v_nonjug", "mixed_805"]:
        segment_rows = fine_rank.loc[fine_rank["segment"].astype(str) == segment].sort_values("rank_from_aisle")
        assert segment_rows["rank_from_aisle"].tolist() == [1, 2, 3, 4, 5]
        assert segment_rows["avg_diff"].is_monotonic_decreasing
    h_nonjug_rank1 = fine_rank.loc[
        (fine_rank["segment"].astype(str) == "h_nonjug") & (fine_rank["rank_from_aisle"] == 1), "avg_diff"
    ].iloc[0]
    v_nonjug_rank1 = fine_rank.loc[
        (fine_rank["segment"].astype(str) == "v_nonjug") & (fine_rank["rank_from_aisle"] == 1), "avg_diff"
    ].iloc[0]
    assert h_nonjug_rank1 > v_nonjug_rank1

    dd_delta = artifacts["dd_corner1_delta"]
    assert list(dd_delta.columns) == [
        "segment",
        "dd",
        "corner1_n",
        "corner1_avg_diff",
        "corner1_plus_rate",
        "rest_n",
        "rest_avg_diff",
        "rest_plus_rate",
        "delta_diff",
    ]
    assert len(dd_delta) == 30
    h_nonjug = dd_delta.loc[dd_delta["segment"].astype(str).eq("h_nonjug")].copy()
    assert h_nonjug.loc[h_nonjug["dd"].astype(str).eq("7"), "delta_diff"].iloc[0] == h_nonjug["delta_diff"].max()

    kw = artifacts["xdds_fine_rank_kw"]
    assert list(kw.columns) == ["segment", "kw_stat", "p_value", "epsilon_sq", "n_groups", "n"]
    assert len(kw) == 5
    assert set(kw["n_groups"].astype(int)) == {5}
    assert set(kw["n"].astype(int)) == {30}

    mwu = artifacts["dd_corner1_mwu"]
    assert list(mwu.columns) == ["segment", "dd", "corner1_n", "rest_n", "u_stat", "p_value", "n"]
    assert len(mwu) == 30
    assert mwu["p_value"].notna().all()
    assert (
        mwu.loc[(mwu["segment"].astype(str) == "h_nonjug") & (mwu["dd"].astype(str) == "7"), "p_value"].iloc[0]
        == mwu.loc[mwu["segment"].astype(str) == "h_nonjug", "p_value"].min()
    )


def test_main_writes_requested_csvs(tmp_path: Path, monkeypatch) -> None:
    from eda import mitoya_phase10d_xdds_corner_deep as phase10d

    monkeypatch.setattr(phase10d, "load_mitoya_frame", lambda join_layout=True: _make_frame())

    exit_code = phase10d.main(["--output-dir", str(tmp_path)])

    assert exit_code == 0
    for name in [
        "xdds_fine_rank.csv",
        "dd_corner1_delta.csv",
        "xdds_fine_rank_kw.csv",
        "dd_corner1_mwu.csv",
        "report.md",
    ]:
        assert (tmp_path / name).exists()
