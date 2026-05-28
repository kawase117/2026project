# Ceiling Effect Significance Summary

- Total rows: 48
- BH significant (0.05): 13

## Top Significant Rows (BH <= 0.05)
- anomaly_direction / low_anomaly / loss_value: delta=-2466.6667, p_bh=0.0326, d=-0.784 (medium)
- anomaly_direction / normal / loss_value: delta=-1066.4000, p_bh=0.0001741, d=-0.246 (small)
- weekday / Saturday / rank2_rescue_on_miss1: delta=0.7000, p_bh=0.04988, d=1.742 (large)
- pred_span_quartile / Q1 / hit_at_2: delta=0.3981, p_bh=0.01252, d=1.056 (large)
- pred_span_quartile / Q1 / rank2_rescue_on_miss1: delta=0.3869, p_bh=0.01845, d=0.871 (large)
- anomaly_direction / normal / rank2_rescue_on_miss1: delta=0.3775, p_bh=0.01787, d=0.809 (large)
- anomaly_direction / low_anomaly / hit_at_2: delta=0.2500, p_bh=0.04769, d=0.799 (medium)
- weekday / Monday / hit_at_2: delta=0.2167, p_bh=0.004153, d=0.738 (medium)
- weekday / Wednesday / hit_at_2: delta=0.2000, p_bh=0.00532, d=0.650 (medium)
- anomaly_direction / normal / hit_at_2: delta=0.1253, p_bh=7.56e-10, d=0.495 (small)

## Non-significant But Large Effect (|d| >= 0.5)
- anomaly_direction / high_anomaly / rank2_rescue_on_miss1: delta=0.6667, p_bh=nan, d=2.000 (large)
- anomaly_direction / low_anomaly / rank2_rescue_on_miss1: delta=0.7500, p_bh=nan, d=1.732 (large)
- weekday / Wednesday / rank2_rescue_on_miss1: delta=0.5647, p_bh=0.05958, d=1.286 (large)
- weekday / Friday / rank2_rescue_on_miss1: delta=0.5833, p_bh=nan, d=1.278 (large)
- pred_span_quartile / Q3 / rank2_rescue_on_miss1: delta=0.5714, p_bh=nan, d=1.234 (large)
- pred_span_quartile / Q2 / rank2_rescue_on_miss1: delta=0.5000, p_bh=0.05958, d=1.146 (large)
- weekday / Tuesday / rank2_rescue_on_miss1: delta=0.5556, p_bh=nan, d=1.118 (large)
- difficulty_failure / miss_day / rank2_rescue_on_miss1: delta=0.1365, p_bh=0.3795, d=0.520 (medium)

## Low-support Warnings (n_current<10 or n_baseline<10)
- anomaly_direction / high_anomaly / rank2_rescue_on_miss1: n_current=5, n_baseline=3
- anomaly_direction / low_anomaly / rank2_rescue_on_miss1: n_current=2, n_baseline=8
- difficulty_failure / miss_day / rank2_rescue_on_miss1: n_current=5, n_baseline=63
- pred_span_quartile / Q2 / rank2_rescue_on_miss1: n_current=7, n_baseline=16
- pred_span_quartile / Q3 / rank2_rescue_on_miss1: n_current=3, n_baseline=7
- pred_span_quartile / Q4 / rank2_rescue_on_miss1: n_current=0, n_baseline=0
- weekday / Friday / rank2_rescue_on_miss1: n_current=4, n_baseline=12
- weekday / Monday / rank2_rescue_on_miss1: n_current=1, n_baseline=16
- weekday / Saturday / rank2_rescue_on_miss1: n_current=5, n_baseline=10
- weekday / Sunday / rank2_rescue_on_miss1: n_current=5, n_baseline=10
- weekday / Thursday / rank2_rescue_on_miss1: n_current=4, n_baseline=12
- weekday / Tuesday / rank2_rescue_on_miss1: n_current=2, n_baseline=9
- weekday / Wednesday / rank2_rescue_on_miss1: n_current=5, n_baseline=17
