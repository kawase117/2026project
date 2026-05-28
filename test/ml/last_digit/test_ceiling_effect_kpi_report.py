import pandas as pd

from ml.last_digit.ceiling_effect.kpi_report import (
    KpiConfig,
    build_kpi_summary,
    build_kpi_summary_table,
    generate_kpi_decision_memo,
)


def _loss_df() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "date": "2026-01-01",
                "expert": "2F_N",
                "weekday": "Thursday",
                "pred_span_quartile": "Q1",
                "anomaly_direction": "normal",
                "difficulty_failure": "hit_day",
                "hit_at_2": 1.0,
                "top1_match": 1,
                "top2_match": 0,
                "top3_match": 0,
                "loss_scenario": "hit1",
                "loss_value": 0.0,
            },
            {
                "date": "2026-01-02",
                "expert": "2F_N",
                "weekday": "Friday",
                "pred_span_quartile": "Q2",
                "anomaly_direction": "normal",
                "difficulty_failure": "miss_day",
                "hit_at_2": 0.0,
                "top1_match": 0,
                "top2_match": 1,
                "top3_match": 0,
                "loss_scenario": "miss1_hit2",
                "loss_value": 3000.0,
            },
            {
                "date": "2026-01-03",
                "expert": "3F_A",
                "weekday": "Saturday",
                "pred_span_quartile": "Q4",
                "anomaly_direction": "high_anomaly",
                "difficulty_failure": "miss_day",
                "hit_at_2": 0.0,
                "top1_match": 0,
                "top2_match": 0,
                "top3_match": 0,
                "loss_scenario": "critical_miss",
                "loss_value": 20000.0,
            },
        ]
    )


def test_build_kpi_summary_includes_core_metrics_and_delta():
    cur = _loss_df()
    base = cur.copy()
    base.loc[2, "loss_value"] = 26000.0
    summary = build_kpi_summary(current_loss_df=cur, baseline_loss_df=base, config=KpiConfig(catastrophic_threshold=15000))
    overall = summary["current"]["overall"]
    assert overall["n_pairs"] == 3
    assert overall["critical_miss_rate"] == 1 / 3
    assert overall["catastrophic_rate"] == 1 / 3
    assert "overall_delta" in summary
    assert summary["overall_delta"]["loss_mean"]["direction"] == "improved"


def test_build_kpi_summary_table_and_memo():
    cur = _loss_df()
    base = cur.copy()
    summary = build_kpi_summary(current_loss_df=cur, baseline_loss_df=base, config=KpiConfig())
    table = build_kpi_summary_table(summary)
    memo = generate_kpi_decision_memo(summary)
    assert set(["scope"]).issubset(set(table.columns))
    assert "KPI Decision Memo" in memo
    assert "critical_miss_rate" in memo
