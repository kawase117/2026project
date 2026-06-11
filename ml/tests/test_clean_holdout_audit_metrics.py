import pandas as pd

from ml.last_digit.audit_metrics import span_band, summarize_holdout, with_audit_columns


def test_span_band_thresholds() -> None:
    assert span_band(float("nan")) == "unknown"
    assert span_band(0.0) == "<0.01"
    assert span_band(0.0099) == "<0.01"
    assert span_band(0.01) == "0.01-0.1"
    assert span_band(0.10) == "0.1-0.3"
    assert span_band(0.30) == ">=0.3"


def test_with_audit_columns_adds_expected_fields() -> None:
    df = pd.DataFrame(
        [
            {
                "pred_span_top12": 0.05,
                "top1_actual_raw_diff": 1000,
                "top2_actual_raw_diff": 700,
                "operational_pick_actual_raw_diff": 900,
                "hit_at_2": 1.0,
                "precision": 0.5,
                "exact_top1_hit": 1,
            }
        ]
    )
    out = with_audit_columns(df)
    assert "span_band" in out.columns
    assert "top1_minus_top2_actual" in out.columns
    assert out.iloc[0]["span_band"] == "0.01-0.1"
    assert out.iloc[0]["top1_minus_top2_actual"] == 300


def test_summarize_holdout_returns_expected_keys() -> None:
    topk = pd.DataFrame(
        [
            {
                "date": "2026-01-01",
                "expert": "2F_N",
                "pred_span_top12": 0.02,
                "top1_actual_raw_diff": 2000,
                "top2_actual_raw_diff": 1000,
                "operational_pick_actual_raw_diff": 1800,
                "hit_at_2": 1.0,
                "precision": 0.5,
                "exact_top1_hit": 1,
            },
            {
                "date": "2026-01-02",
                "expert": "2F_N",
                "pred_span_top12": 0.40,
                "top1_actual_raw_diff": 3000,
                "top2_actual_raw_diff": 500,
                "operational_pick_actual_raw_diff": 2800,
                "hit_at_2": 1.0,
                "precision": 1.0,
                "exact_top1_hit": 0,
            },
        ]
    )
    daily = pd.DataFrame(
        [
            {"date": "2026-01-01", "expert": "2F_N", "status": "ok", "hit_at_2": 1.0, "hit_at_3": 1.0, "precision": 0.5},
            {"date": "2026-01-02", "expert": "2F_N", "status": "ok", "hit_at_2": 1.0, "hit_at_3": 1.0, "precision": 1.0},
        ]
    )
    summary = summarize_holdout(topk, daily)
    assert set(summary.keys()) == {"overall_by_expert", "span_band_by_expert", "daily_overall"}
    assert len(summary["overall_by_expert"]) == 1
    assert summary["overall_by_expert"][0]["expert"] == "2F_N"
    assert summary["daily_overall"]["n_days"] == 2
