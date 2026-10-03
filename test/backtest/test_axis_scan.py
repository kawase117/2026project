"""backtest/axis_scan.py のテスト。合成データのみ(DBは使わない)。"""

import numpy as np
import pandas as pd

from backtest import axis_scan as ax


def _planted(effect, days=90, seed=1):
    rng = np.random.default_rng(seed)
    strata = rng.integers(0, 7, days)
    M = np.zeros((days, 3))
    for level in range(3):
        M[rng.choice(days, 12, replace=False), level] = 1
    DEN = np.full((days, 3), 100.0)
    NUM = rng.poisson(10, (days, 3)).astype(float)
    if effect:
        NUM[:, 1] += effect * M[:, 0]  # 時間水準0の中で、位置水準1だけ増える
    return M, strata, NUM, DEN


def test_permutation_scan_detects_planted_interaction():
    M, strata, NUM, DEN = _planted(effect=8)
    p_family, obs, z, cell_p = ax.permutation_scan(M, strata, NUM, DEN, "did", iters=300, rng=np.random.default_rng(5))
    assert p_family < 0.05
    assert z[0, 1] == np.nanmax(z) and z[0, 1] > 3
    assert cell_p[0, 1] < 0.05


def test_permutation_scan_null_is_roughly_calibrated():
    # 効果が無いデータを複数回作り、族のpが大半で有意にならないこと(1回だけだと乱数の当たり外れが出る)
    ps = []
    for seed in range(20):
        M, strata, NUM, DEN = _planted(effect=0, seed=seed)
        p_family, obs, z, cell_p = ax.permutation_scan(
            M, strata, NUM, DEN, "did", iters=100, rng=np.random.default_rng(100 + seed)
        )
        assert np.isfinite(cell_p).all()
        ps.append(p_family)
    assert np.mean(ps) > 0.3 and np.mean(np.array(ps) < 0.05) <= 0.25


def test_permutation_scan_diff_mode_for_single_series():
    rng = np.random.default_rng(2)
    days = 80
    strata = rng.integers(0, 7, days)
    M = np.zeros((days, 2))
    M[rng.choice(days, 10, replace=False), 0] = 1
    DEN = np.full((days, 1), 20.0)
    NUM = rng.normal(0, 1, (days, 1)) + 5 * M[:, [0]]
    p_family, obs, z, cell_p = ax.permutation_scan(M, strata, NUM, DEN, "diff", iters=300, rng=np.random.default_rng(3))
    assert p_family < 0.05 and obs[0, 0] > 0


def test_is_new_machine_covers_first_week_only_and_ignores_machines_present_at_db_start():
    db_min = "20250101"
    assert ax.is_new_machine("20260914", "20260914", db_min) is True  # 導入日
    assert ax.is_new_machine("20260914", "20260920", db_min) is True  # 導入後6日
    assert ax.is_new_machine("20260914", "20260921", db_min) is False  # 導入後7日からは新台にしない(1週間)
    # DBの最初の日にあった機種は、導入日が分からないので、新台にしない(DBの先頭の1週間が全部消えるのを防ぐ)
    assert ax.is_new_machine("20250101", "20250103", db_min) is False


def test_bh_adjust_matches_hand_calculation():
    q = ax.bh_adjust([0.01, 0.04, 0.03, 0.2, np.nan])
    assert np.allclose(q[:4], [0.04, 0.05333333, 0.05333333, 0.2])
    assert np.isnan(q[4])


def _pair_frame(hits):
    n = len(hits)
    return pd.DataFrame(
        {
            "ds": ["20260101"] * n,
            "machine_number": list(range(100, 100 + n)),
            "machine_name": ["機種A"] * n,
            "section": ["s1"] * n,
            "hit": hits,
            "E": [4.0] * n,
            "di": [0] * n,
        }
    )


def test_pair_residual_products_removes_whole_machine_effect():
    all_hot = ax.pair_residual_products(_pair_frame([8, 8, 8]), "RB")
    assert abs(all_hot.num.iloc[0]) < 1e-9 and all_hot.den.iloc[0] == 2  # 全台系は並びではない
    split = ax.pair_residual_products(_pair_frame([8, 8, 0]), "RB")
    assert np.isclose(split.num.iloc[0], 1.3333 * 1.3333 - 1.3333 * 2.6667, atol=1e-3)
    # 2台機種は対象外
    assert ax.pair_residual_products(_pair_frame([8, 0]), "RB").empty


def test_pair_residual_products_ignores_non_adjacent_and_other_sections():
    frame = _pair_frame([8, 8, 0, 0])
    frame.loc[2, "section"] = "s2"  # 3台目は別セクション(物理的に隣ではない)
    frame.loc[3, "machine_number"] = 110  # 連番でない
    out = ax.pair_residual_products(frame, "RB")
    assert out.den.iloc[0] == 1


def test_time_axes_builds_levels_and_event_membership():
    days = ["20260706", "20260707", "20260711", "20260712", "20260713", "20260722", "20260808"]
    registry = {
        "EVENT_DAYS": [
            {"event_id": f"e{d}", "hall": "楽園蒲田店", "date": d}
            for d in ("20260707", "20260711", "20260713", "20260722")
        ],
        "EVENT_SERIES": [
            {
                "hall": "楽園蒲田店",
                "axis": "name",
                "label": "取材",
                "event_ids": ["e20260707", "e20260711", "e20260713"],
            },
            {"hall": "楽園蒲田店", "axis": "pledge", "label": "並び:3台", "event_ids": ["e20260722"]},
            {"hall": "別ホール", "axis": "name", "label": "他", "event_ids": ["e20260707"]},
        ],
    }
    axes = ax.time_axes(days, "楽園蒲田店", registry=registry)
    assert set(axes) == {"曜日", "D(下一桁)", "DD(日付)", "ゾロ目", "イベント・公約"}
    names, M, strata = axes["イベント・公約"]
    assert names == ["イベント: 取材(3日)"]  # 3日未満の系列と他ホールは除く
    assert M[:, 0].sum() == 3
    _, zoro, _ = axes["ゾロ目"]
    assert zoro[:, 0].sum() == 2  # 11日と22日
    assert zoro[:, 1].sum() == 2  # 7/7と8/8は月=日
    digits = axes["D(下一桁)"][1]
    assert digits.sum(1).tolist() == [1] * len(days)  # 各日はちょうど1つの下一桁


def test_add_expectations_scales_games_by_daily_traffic():
    rows = []
    for ds, wd, factor in (("20260101", 3, 1.0), ("20260108", 3, 2.0)):
        for number in (101, 102):
            rows.append(
                dict(
                    ds=ds,
                    wd=wd,
                    machine_name="機種A",
                    machine_number=number,
                    seg="RB",
                    band=1,
                    G=3000.0 * factor,
                    hit=10 * factor,
                    diff_coins_normalized=0.0,
                )
            )
    out = ax.add_expectations(pd.DataFrame(rows))
    assert np.allclose(out.E, out.G * (out.hit.sum() / out.G.sum()))
    # 客数が2倍の日は、期待回転数も、機種×曜日の平均(4500)に、客数指数(6000/4500)を掛けた値
    day2 = out[out.ds == "20260108"].iloc[0]
    assert np.isclose(day2.Gexp, 4500.0) and np.isclose(day2.traffic, 6000.0 / 4500.0)
    assert np.isclose(day2.Gx, 4500.0 * 6000.0 / 4500.0)


def test_day_matrices_aggregates_by_day_and_position_level():
    df = pd.DataFrame(
        {
            "ds": ["20260101", "20260101", "20260102"],
            "ld": [7, 3, 7],
            "edge": [1, 2, 5],
            "num": [2.0, 1.0, 4.0],
            "den": [10.0, 10.0, 20.0],
        }
    )
    days = ["20260101", "20260102"]
    labels, NUM, DEN = ax.day_matrices(df, df.num, df.den, "末尾", days)
    assert labels[7] == "末尾7" and NUM[0, 7] == 2.0 and NUM[0, 3] == 1.0 and NUM[1, 7] == 4.0
    labels, NUM, DEN = ax.day_matrices(df, df.num, df.den, "角番", days)
    assert labels == ["角1", "角2", "角3以上"] and NUM[1, 2] == 4.0 and DEN[0, 0] == 10.0
