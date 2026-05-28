import pandas as pd

from ml.last_digit.ceiling_effect.stats import StatsConfig, compute_condition_significance


def _make_df(offset: float) -> pd.DataFrame:
    rows = []
    for i in range(12):
        dt = pd.Timestamp("2026-01-01") + pd.Timedelta(days=i)
        rows.append(
            {
                "date": dt,
                "expert": "2F_N" if i % 2 == 0 else "3F_N",
                "weekday": dt.day_name(),
                "pred_span_quartile": "Q1" if i < 6 else "Q4",
                "anomaly_direction": "normal",
                "difficulty_failure": "hit_day",
                "hit_at_2": 1.0 if i % 3 else 0.0 + offset,
                "loss_value": float(max(0.0, 5000 - i * 100 + offset * 100)),
                "top1_match": 0 if i % 4 == 0 else 1,
                "top2_match": 1 if i % 4 == 0 else 0,
            }
        )
    return pd.DataFrame(rows)


def test_compute_condition_significance_outputs_adjusted_pvalues():
    cur = _make_df(0.05)
    base = _make_df(0.0)
    out = compute_condition_significance(
        current_loss_df=cur,
        baseline_loss_df=base,
        config=StatsConfig(n_boot=200, seed=123, min_paired_for_wilcoxon=5, min_unpaired_for_mwu=3),
        metrics=["hit_at_2", "loss_value", "rank2_rescue_on_miss1"],
    )
    assert not out.empty
    assert "p_value_adj_bh" in out.columns
    assert "p_value_adj_bonferroni" in out.columns
    assert "cohens_d_label" in out.columns
    assert set(["condition", "difficulty", "metric"]).issubset(set(out.columns))

