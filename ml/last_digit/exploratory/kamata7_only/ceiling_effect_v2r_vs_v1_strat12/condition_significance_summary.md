# Ceiling Effect Significance Summary

- Total rows: 48
- BH significant (0.05): 20

## Top Significant Rows (BH <= 0.05)
- weekday / sunday / loss_value: delta=-1211.1111, p_bh=0.04515, d=-0.195 (negligible)
- anomaly_direction / normal / loss_value: delta=-1047.7333, p_bh=0.0001058, d=-0.241 (small)
- weekday / fri_sat / loss_value: delta=-994.4444, p_bh=0.01868, d=-0.334 (small)
- weekday / fri_sat / rank2_rescue_on_miss1: delta=0.6364, p_bh=0.009228, d=1.492 (large)
- anomaly_direction / anomaly / rank2_rescue_on_miss1: delta=0.6273, p_bh=0.01731, d=1.558 (large)
- weekday / wednesday / rank2_rescue_on_miss1: delta=0.5980, p_bh=0.03752, d=1.389 (large)
- weekday / mon_thu / rank2_rescue_on_miss1: delta=0.5757, p_bh=0.00559, d=1.287 (large)
- pred_span_quartile / Q1 / rank2_rescue_on_miss1: delta=0.4678, p_bh=0.001903, d=1.068 (large)
- pred_span_quartile / Q1 / hit_at_2: delta=0.4074, p_bh=0.03871, d=1.098 (large)
- anomaly_direction / normal / rank2_rescue_on_miss1: delta=0.3933, p_bh=0.00559, d=0.845 (large)

## Non-significant But Large Effect (|d| >= 0.5)
- pred_span_quartile / Q1 / critical_miss_rate: delta=-0.3981, p_bh=0.1082, d=-1.039 (large)
- pred_span_quartile / Q2 / rank2_rescue_on_miss1: delta=0.4091, p_bh=0.06697, d=0.923 (large)
- difficulty_failure / miss_day / rank2_rescue_on_miss1: delta=0.1365, p_bh=0.417, d=0.520 (medium)

## Low-support Warnings (n_current<10 or n_baseline<10)
- difficulty_failure / miss_day / rank2_rescue_on_miss1: n_current=5, n_baseline=63
- pred_span_quartile / Q3 / rank2_rescue_on_miss1: n_current=2, n_baseline=7
- pred_span_quartile / Q4 / rank2_rescue_on_miss1: n_current=0, n_baseline=0
- weekday / fri_sat / rank2_rescue_on_miss1: n_current=8, n_baseline=22
- weekday / sunday / rank2_rescue_on_miss1: n_current=6, n_baseline=10
- weekday / wednesday / rank2_rescue_on_miss1: n_current=6, n_baseline=17
