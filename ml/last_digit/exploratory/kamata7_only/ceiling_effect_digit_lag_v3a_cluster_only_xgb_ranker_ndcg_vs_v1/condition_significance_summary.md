# Ceiling Effect Significance Summary

- Total rows: 48
- BH significant (0.05): 11

## Top Significant Rows (BH <= 0.05)
- anomaly_direction / low_anomaly / loss_value: delta=-2395.8333, p_bh=0.0421, d=-0.748 (medium)
- weekday / Sunday / loss_value: delta=-1774.6032, p_bh=0.007105, d=-0.300 (small)
- anomaly_direction / normal / loss_value: delta=-1088.5333, p_bh=0.0001916, d=-0.258 (small)
- pred_span_quartile / Q1 / rank2_rescue_on_miss1: delta=0.4090, p_bh=0.008127, d=0.923 (large)
- pred_span_quartile / Q1 / hit_at_2: delta=0.3981, p_bh=0.03016, d=1.056 (large)
- anomaly_direction / normal / rank2_rescue_on_miss1: delta=0.3933, p_bh=0.008127, d=0.845 (large)
- weekday / Monday / hit_at_2: delta=0.2167, p_bh=0.003842, d=0.738 (medium)
- weekday / Wednesday / hit_at_2: delta=0.2000, p_bh=0.004921, d=0.650 (medium)
- anomaly_direction / normal / hit_at_2: delta=0.1280, p_bh=4.2e-10, d=0.510 (medium)
- weekday / Friday / hit_at_2: delta=0.1111, p_bh=0.03016, d=0.496 (small)

## Non-significant But Large Effect (|d| >= 0.5)
- anomaly_direction / high_anomaly / rank2_rescue_on_miss1: delta=0.6667, p_bh=nan, d=1.633 (large)
- weekday / Saturday / rank2_rescue_on_miss1: delta=0.7000, p_bh=nan, d=1.602 (large)
- weekday / Friday / rank2_rescue_on_miss1: delta=0.5833, p_bh=nan, d=1.278 (large)
- weekday / Tuesday / rank2_rescue_on_miss1: delta=0.5556, p_bh=nan, d=1.179 (large)
- pred_span_quartile / Q3 / rank2_rescue_on_miss1: delta=0.5714, p_bh=nan, d=1.155 (large)
- weekday / Wednesday / rank2_rescue_on_miss1: delta=0.5147, p_bh=nan, d=1.150 (large)
- anomaly_direction / low_anomaly / rank2_rescue_on_miss1: delta=0.4167, p_bh=nan, d=0.849 (large)
- pred_span_quartile / Q2 / rank2_rescue_on_miss1: delta=0.3571, p_bh=0.2079, d=0.743 (medium)
- anomaly_direction / low_anomaly / hit_at_2: delta=0.2083, p_bh=0.1145, d=0.605 (medium)

## Low-support Warnings (n_current<10 or n_baseline<10)
- anomaly_direction / high_anomaly / rank2_rescue_on_miss1: n_current=3, n_baseline=3
- anomaly_direction / low_anomaly / rank2_rescue_on_miss1: n_current=3, n_baseline=8
- difficulty_failure / miss_day / rank2_rescue_on_miss1: n_current=4, n_baseline=63
- pred_span_quartile / Q2 / rank2_rescue_on_miss1: n_current=7, n_baseline=16
- pred_span_quartile / Q3 / rank2_rescue_on_miss1: n_current=2, n_baseline=7
- pred_span_quartile / Q4 / rank2_rescue_on_miss1: n_current=0, n_baseline=0
- weekday / Friday / rank2_rescue_on_miss1: n_current=4, n_baseline=12
- weekday / Monday / rank2_rescue_on_miss1: n_current=1, n_baseline=16
- weekday / Saturday / rank2_rescue_on_miss1: n_current=3, n_baseline=10
- weekday / Sunday / rank2_rescue_on_miss1: n_current=7, n_baseline=10
- weekday / Thursday / rank2_rescue_on_miss1: n_current=4, n_baseline=12
- weekday / Tuesday / rank2_rescue_on_miss1: n_current=3, n_baseline=9
- weekday / Wednesday / rank2_rescue_on_miss1: n_current=4, n_baseline=17
