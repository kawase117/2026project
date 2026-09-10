# -*- coding: utf-8 -*-
"""イベント窓ルール（today_eligibility）と除外指定を固定する。

どちらも 2026-09-11 に足した。動機はそれぞれ:
  - exclude: 蒲田7の k7_at_histdiff_top3 が13プラン全部で鉄台2026を選んでおり、
    +1,275枚/73% が「台2026を握り続けた成績」だった（除くと +231枚/55%）
  - today_eligibility: 増台の効果は当日〜7日で消えるので、選択条件は対象日に
    ついて評価しないと意味を持たない。eligibility は履歴にもかかるため使えない
"""

import os
import sys

import pandas as pd
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

from backtest import forward  # noqa: E402
from backtest.prereg import PreRegistration  # noqa: E402
from backtest.run_backtest import apply_eligibility  # noqa: E402


@pytest.fixture
def frame():
    return pd.DataFrame(
        {
            "machine_number": [2024, 2025, 2026, 2027],
            "days_since_increase": [0.0, 3.0, 9.0, float("nan")],
        }
    )


def test_exclude_drops_only_the_named_machines(frame):
    out = apply_eligibility(frame, {"machine_number": {"exclude": [2026]}})
    assert sorted(out["machine_number"]) == [2024, 2025, 2027]


def test_exclude_combines_with_range(frame):
    out = apply_eligibility(
        frame, {"days_since_increase": {"min": 1, "max": 10}, "machine_number": {"exclude": [2026]}}
    )
    assert sorted(out["machine_number"]) == [2025]


def test_exclude_must_be_a_non_empty_list(frame):
    with pytest.raises(ValueError, match="非空のリスト"):
        apply_eligibility(frame, {"machine_number": {"exclude": []}})


def test_unknown_range_key_still_rejected(frame):
    with pytest.raises(ValueError, match="範囲指定が不正"):
        apply_eligibility(frame, {"days_since_increase": {"between": [1, 7]}})


def base_reg(**kwargs):
    defaults = dict(
        rule_id="r",
        hall="H",
        hypothesis="h",
        source_instinct="s",
        eval_start="20260101",
        eval_end="20260201",
        success_criterion="c",
        score="hist_mean_diff",
    )
    defaults.update(kwargs)
    return PreRegistration(**defaults)


def test_days_since_increase_min_zero_is_rejected():
    # 0 は「対象日に増台された」で、前日に凍結する時点では知り得ない。
    with pytest.raises(ValueError, match="min は 1 以上"):
        base_reg(today_eligibility={"days_since_increase": {"min": 0, "max": 7}}).validate()


def test_today_eligibility_rejects_unknown_field():
    with pytest.raises(ValueError, match="today_eligibility に未許可"):
        base_reg(today_eligibility={"machine_color": "red"}).validate()


def test_empty_today_eligibility_keeps_the_v1_freeze_hash():
    # 新フィールドを足しただけで既存ルールのハッシュが動くと、蓄積した
    # フォワード証拠が全部「後から書き換えた」扱いになる。
    reg = base_reg()
    assert reg.freeze_hash() == base_reg(today_eligibility={}).freeze_hash()


def test_non_empty_today_eligibility_changes_the_hash():
    reg = base_reg()
    other = base_reg(today_eligibility={"days_since_increase": {"min": 1, "max": 7}})
    assert reg.freeze_hash() != other.freeze_hash()


def test_proxy_day_gap_is_added_to_days_since_increase():
    # data_asof が対象日の3日前なら、代理行の経過日数は3日ぶん若い。
    reg = base_reg(today_eligibility={"days_since_increase": {"min": 1, "max": 7}})
    latest = pd.DataFrame({"machine_number": [1, 2, 3], "days_since_increase": [2.0, 5.0, 9.0]})
    out = forward._apply_today_eligibility(reg, latest, "20260912", "20260909")
    # +3 して 5 / 8 / 12 になるので、窓 1..7 に残るのは 1台目だけ。
    assert sorted(out["machine_number"]) == [1]


def test_no_today_eligibility_is_a_passthrough():
    latest = pd.DataFrame({"machine_number": [1, 2], "days_since_increase": [2.0, 9.0]})
    out = forward._apply_today_eligibility(base_reg(), latest, "20260912", "20260909")
    assert len(out) == 2


def test_outside_event_window_is_a_value_error():
    # plan_all の想定内失敗の枠から外れると、1本の不成立で日次ジョブが倒れる。
    assert issubclass(forward.OutsideEventWindow, ValueError)
