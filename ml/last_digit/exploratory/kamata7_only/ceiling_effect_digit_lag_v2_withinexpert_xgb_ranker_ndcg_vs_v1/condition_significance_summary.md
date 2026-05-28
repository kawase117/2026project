# Ceiling Effect Significance Summary

- Total rows: 48
- BH significant (0.05): 11

## Top Significant Rows (BH <= 0.05)
- anomaly_direction / low_anomaly / loss_value: delta=-2362.5000, p_bh=0.0421, d=-0.737 (medium)
- weekday / Sunday / loss_value: delta=-1628.5714, p_bh=0.01566, d=-0.323 (small)
- anomaly_direction / normal / loss_value: delta=-1074.4000, p_bh=0.0003043, d=-0.268 (small)
- anomaly_direction / normal / rank2_rescue_on_miss1: delta=0.4828, p_bh=0.001752, d=1.059 (large)
- pred_span_quartile / Q1 / rank2_rescue_on_miss1: delta=0.4542, p_bh=0.009145, d=1.037 (large)
- pred_span_quartile / Q1 / hit_at_2: delta=0.4074, p_bh=0.0421, d=1.098 (large)
- weekday / Monday / hit_at_2: delta=0.2167, p_bh=0.002305, d=0.738 (medium)
- weekday / Wednesday / hit_at_2: delta=0.2167, p_bh=0.002305, d=0.738 (medium)
- anomaly_direction / normal / hit_at_2: delta=0.1307, p_bh=2.523e-10, d=0.527 (medium)
- weekday / Friday / hit_at_2: delta=0.1111, p_bh=0.03351, d=0.496 (small)

## Non-significant But Large Effect (|d| >= 0.5)
- weekday / Monday / rank2_rescue_on_miss1: delta=0.8125, p_bh=nan, d=2.082 (large)
- weekday / Wednesday / rank2_rescue_on_miss1: delta=0.7647, p_bh=nan, d=1.906 (large)
- weekday / Saturday / rank2_rescue_on_miss1: delta=0.7000, p_bh=nan, d=1.602 (large)
- anomaly_direction / high_anomaly / rank2_rescue_on_miss1: delta=0.6667, p_bh=nan, d=1.414 (large)
- weekday / Friday / rank2_rescue_on_miss1: delta=0.5833, p_bh=nan, d=1.232 (large)
- weekday / Tuesday / rank2_rescue_on_miss1: delta=0.5556, p_bh=nan, d=1.118 (large)
- pred_span_quartile / Q2 / rank2_rescue_on_miss1: delta=0.4000, p_bh=0.1019, d=0.885 (large)
- difficulty_failure / miss_day / rank2_rescue_on_miss1: delta=0.1865, p_bh=nan, d=0.709 (medium)
- anomaly_direction / low_anomaly / hit_at_2: delta=0.2083, p_bh=0.1208, d=0.605 (medium)
- anomaly_direction / low_anomaly / rank2_rescue_on_miss1: delta=0.2500, p_bh=nan, d=0.500 (medium)

## Low-support Warnings (n_current<10 or n_baseline<10)
- anomaly_direction / high_anomaly / rank2_rescue_on_miss1: n_current=2, n_baseline=3
- anomaly_direction / low_anomaly / rank2_rescue_on_miss1: n_current=2, n_baseline=8
- difficulty_failure / miss_day / hit_at_2: n_current=9, n_baseline=150
- difficulty_failure / miss_day / loss_value: n_current=9, n_baseline=150
- difficulty_failure / miss_day / rank2_rescue_on_miss1: n_current=4, n_baseline=63
- pred_span_quartile / Q3 / rank2_rescue_on_miss1: n_current=0, n_baseline=7
- pred_span_quartile / Q4 / rank2_rescue_on_miss1: n_current=0, n_baseline=0
- weekday / Friday / rank2_rescue_on_miss1: n_current=3, n_baseline=12
- weekday / Monday / rank2_rescue_on_miss1: n_current=2, n_baseline=16
- weekday / Saturday / rank2_rescue_on_miss1: n_current=3, n_baseline=10
- weekday / Sunday / rank2_rescue_on_miss1: n_current=6, n_baseline=10
- weekday / Thursday / rank2_rescue_on_miss1: n_current=3, n_baseline=12
- weekday / Tuesday / rank2_rescue_on_miss1: n_current=2, n_baseline=9
- weekday / Wednesday / rank2_rescue_on_miss1: n_current=4, n_baseline=17
