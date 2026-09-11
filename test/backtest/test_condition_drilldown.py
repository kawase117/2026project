# -*- coding: utf-8 -*-
"""判定ロジックを固定する。ここは今日踏んだ罠をそのまま規則にした部分。

- 全期間がプラスでも直近が反転していれば採用しない
- 直近を確認できない（回転数が落ちた）場合は採用しない。ここをカレンダー基準に
  すると、台数を削られた機種ほど確認セルが埋まらず失効をすり抜ける
- 台数が少ないことは棄却の理由にならない。足りないのは判断材料であって、
  結論は「悪い」ではなく「分からない」
"""

import os
import sys

import numpy as np
import pandas as pd
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

from backtest import condition_drilldown as cd  # noqa: E402


def build(per_quarter, days_per_quarter=40, games=4000, base_bonus=40):
    """四半期ごとに条件日の上振れ率を指定してフレームを作る。

    per_quarter: {"2025Q1": +0.20, ...} 条件日のボーナスを何割増しにするか
    各四半期で、条件日と非条件日を半々に作る。
    """
    rows = []
    for qi, (q, lift) in enumerate(per_quarter.items()):
        year, quarter = int(q[:4]), int(q[-1])
        month = (quarter - 1) * 3 + 1
        for i in range(days_per_quarter):
            day = 1 + i % 25
            is_cond = i % 2 == 0
            date = "%04d%02d%02d" % (year, month + (i // 25) % 3, day)
            bonus = int(base_bonus * (1 + lift)) if is_cond else base_bonus
            rows.append((date, 100 + qi, "機種", games, bonus * 10, bonus, is_cond))
    frame = pd.DataFrame(rows, columns=["date", "machine_number", "machine_name", "games", "diff", "bonus", "cond"])
    frame["edge"] = frame["diff"] - frame["diff"].mean()
    frame["ts"] = pd.to_datetime(frame.date, format="%Y%m%d")
    frame["quarter"] = frame.ts.dt.to_period("Q")
    return frame


def run(frame):
    quarters = sorted(frame.quarter.unique())
    return cd.verdict(frame, frame["cond"], quarters)


def test_steadily_positive_is_adopted():
    f = build({"2025Q1": 0.10, "2025Q2": 0.10, "2025Q3": 0.10, "2025Q4": 0.10})
    state, got, _ = run(f)
    assert state == "採用"
    assert got[0] == pytest.approx(10, abs=2)


def test_reversal_in_recent_quarters_is_expired_even_if_whole_period_is_strong():
    # レヴュースタァライトの月末。全期間はプラスだが2026年に入って反転。
    f = build({"2025Q1": 0.30, "2025Q2": 0.30, "2026Q1": -0.10, "2026Q2": -0.10})
    state, got, note = run(f)
    assert state == "失効"
    assert got[0] > 0  # 全期間はプラスのまま
    assert "反転" in note


def test_recent_is_measured_by_quarters_that_have_data_not_by_calendar():
    # 直近の四半期が薄くて測れない機種ほど死にかけている。
    # カレンダー基準だと確認セルが埋まらず、失効をすり抜ける。
    f = build({"2025Q1": 0.30, "2025Q2": 0.30, "2026Q1": -0.10, "2026Q2": -0.10})
    thin = build({"2026Q3": -0.10}, days_per_quarter=2)
    merged = pd.concat([f, thin], ignore_index=True)
    state, _, _ = run(merged)
    assert state == "失効"


def test_rise_from_negative_to_positive_is_not_rejected():
    # 前半マイナス→後半プラスはレジーム変化。符号が揃わないことを棄却理由にしない。
    f = build({"2025Q1": -0.08, "2025Q2": 0.10, "2026Q1": 0.12, "2026Q2": 0.22})
    state, _, _ = run(f)
    assert state == "採用"


def test_too_few_days_is_undecidable_not_bad():
    f = build({"2025Q1": -0.30, "2025Q2": -0.30}, days_per_quarter=10)
    state, _, note = run(f)
    assert state == "判断不能"
    assert "台日" in note or "σ" in note


def test_single_machine_is_not_rejected_for_being_single():
    # 1台でも法則があれば狙い台。台数そのものを棄却条件にしない。
    f = build({"2025Q1": 0.15, "2025Q2": 0.15, "2025Q3": 0.15, "2025Q4": 0.15})
    f["machine_number"] = 2139
    state, _, _ = run(f)
    assert state == "採用"


def test_bonus_up_but_coins_down_is_flagged():
    # 蒲田1のBT。ボーナスは増えているのに差枚が付いてこない。
    f = build({"2025Q1": 0.10, "2025Q2": 0.10, "2025Q3": 0.10, "2025Q4": 0.10})
    f.loc[f["cond"], "edge"] = -500.0
    f.loc[~f["cond"], "edge"] = 0.0
    state, _, note = run(f)
    assert state == "要注意"
    assert "差枚" in note


def test_clearly_negative_is_avoided():
    f = build({"2025Q1": -0.15, "2025Q2": -0.15, "2025Q3": -0.15, "2025Q4": -0.15})
    f.loc[f["cond"], "edge"] = -800.0
    f.loc[~f["cond"], "edge"] = 0.0
    state, _, _ = run(f)
    assert state == "回避"


def test_only_one_measurable_quarter_needs_confirmation():
    f = build({"2026Q3": 0.20}, days_per_quarter=60)
    state, _, note = run(f)
    assert state == "要確認"
    assert "確認できるのが" in note


def test_cell_returns_none_when_the_window_is_too_thin():
    f = build({"2025Q1": 0.10}, days_per_quarter=4)
    assert cd.cell(f, f["cond"]) is None


def test_cell_reports_the_lift_and_the_coin_difference():
    f = build({"2025Q1": 0.20, "2025Q2": 0.20})
    f.loc[f["cond"], "edge"] = 300.0
    f.loc[~f["cond"], "edge"] = 100.0
    lift, z, coins, days, games = cd.cell(f, f["cond"])
    assert lift == pytest.approx(20, abs=2)
    assert coins == pytest.approx(200, abs=1)
    assert z > 2
    assert days == int(f["cond"].sum())
    assert games == int(f.loc[f["cond"], "games"].sum())


def test_sigma_grows_with_games_not_with_the_effect():
    small = build({"2025Q1": 0.10, "2025Q2": 0.10}, games=1000)
    large = build({"2025Q1": 0.10, "2025Q2": 0.10}, games=10000, base_bonus=400)
    z_small = cd.cell(small, small["cond"])[1]
    z_large = cd.cell(large, large["cond"])[1]
    assert z_large > z_small
    assert np.isclose(cd.cell(small, small["cond"])[0], cd.cell(large, large["cond"])[0], atol=2)


def test_composition_change_does_not_fake_a_lift():
    """機種構成が入れ替わるだけで比が動いてはいけない。

    設定は1日も動かさず、条件日だけ高ベース機種の回転を増やす。合算で割ると
    上振れが出るが、機種ごとの基準から期待値を積めばゼロになる。
    """
    rows = []
    for i in range(200):
        date = "2025%02d%02d" % (1 + i // 25, 1 + i % 25)
        is_cond = i % 2 == 0
        # 低ベース: 1/200。条件日も非条件日も同じ回転。
        rows.append((date, 1, "低ベース", 4000, 0, 20, is_cond))
        # 高ベース: 1/50。条件日だけ回転が8倍。設定は動かしていない。
        games = 8000 if is_cond else 1000
        rows.append((date, 2, "高ベース", games, 0, games // 50, is_cond))
    f = pd.DataFrame(rows, columns=["date", "machine_number", "machine_name", "games", "diff", "bonus", "cond"])
    f["edge"] = 0.0
    f["ts"] = pd.to_datetime(f.date, format="%Y%m%d")
    f["quarter"] = f.ts.dt.to_period("Q")

    pooled = 100 * (
        (f[f["cond"]].bonus.sum() / f[f["cond"]].games.sum()) / (f[~f["cond"]].bonus.sum() / f[~f["cond"]].games.sum())
        - 1
    )
    assert pooled > 10, "合算で割ると偽の上振れが出るはず（テストの前提）"

    lift, _, _, _, _ = cd.cell(f, f["cond"])
    assert lift == pytest.approx(0.0, abs=0.5)
