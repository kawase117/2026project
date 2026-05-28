import pandas as pd

from ml.last_digit.ceiling_effect.loaders import ActualRankInfo
from ml.last_digit.ceiling_effect.loss_chain import classify_loss_scenario
from ml.last_digit.ceiling_effect.stratifiers import (
    AnomalyEvaluator,
    FailureDayEvaluator,
    PredSpanEvaluator,
    WeekdayEvaluator,
)


def _actual() -> ActualRankInfo:
    return ActualRankInfo(
        top1_tail="7",
        top2_tail="3",
        top3_tail="1",
        top1_diff=30000.0,
        top2_diff=25000.0,
        top3_diff=20000.0,
        tail_to_diff={"7": 30000.0, "3": 25000.0, "1": 20000.0, "9": 10000.0},
    )


def test_classify_loss_hit1():
    sc = classify_loss_scenario(pred_top1_tail="7", pred_top2_tail="3", pred_top3_tail=None, actual=_actual())
    assert sc.scenario == "hit1"
    assert sc.loss_value == 0.0
    assert sc.top1_match == 1


def test_classify_loss_rank2_rescue():
    sc = classify_loss_scenario(pred_top1_tail="9", pred_top2_tail="3", pred_top3_tail=None, actual=_actual())
    assert sc.scenario == "miss1_hit2"
    assert sc.loss_value == 5000.0
    assert sc.top2_match == 1


def test_classify_loss_critical_miss():
    sc = classify_loss_scenario(pred_top1_tail="9", pred_top2_tail="8", pred_top3_tail=None, actual=_actual())
    assert sc.scenario == "critical_miss"
    assert sc.loss_value >= 0.0


def test_stratifiers_basic_groups():
    df = pd.DataFrame(
        [
            {"weekday": "Monday", "pred_span_quartile": "Q1", "anomaly_direction": "normal", "difficulty_failure": "hit_day"},
            {"weekday": "Tuesday", "pred_span_quartile": "Q2", "anomaly_direction": "high_anomaly", "difficulty_failure": "miss_day"},
        ]
    )
    assert set(WeekdayEvaluator().stratify(df).keys()) == {"mon_thu"}
    assert set(PredSpanEvaluator().stratify(df).keys()) == {"Q1", "Q2"}
    assert set(AnomalyEvaluator().stratify(df).keys()) == {"normal", "anomaly"}
    assert set(FailureDayEvaluator().stratify(df).keys()) == {"hit_day", "miss_day"}
