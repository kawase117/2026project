# Ceiling Effect Significance Summary

- Total rows: 48
- BH significant (0.05): 15

## Top Significant Rows (BH <= 0.05)
- anomaly_direction / low_anomaly / loss_value: delta=-2466.6667, p_bh=0.03179, d=-0.784 (medium)
- weekday / Sunday / loss_value: delta=-1517.4603, p_bh=0.04563, d=-0.305 (small)
- weekday / Friday / loss_value: delta=-1392.0635, p_bh=0.04292, d=-0.420 (small)
- anomaly_direction / normal / loss_value: delta=-1153.8667, p_bh=6.906e-05, d=-0.287 (small)
- pred_span_quartile / Q2 / rank2_rescue_on_miss1: delta=0.5000, p_bh=0.04746, d=1.173 (large)
- anomaly_direction / normal / rank2_rescue_on_miss1: delta=0.4552, p_bh=0.002493, d=0.993 (large)
- pred_span_quartile / Q1 / rank2_rescue_on_miss1: delta=0.4494, p_bh=0.004591, d=1.023 (large)
- pred_span_quartile / Q1 / hit_at_2: delta=0.3981, p_bh=0.008722, d=1.056 (large)
- anomaly_direction / low_anomaly / hit_at_2: delta=0.2500, p_bh=0.04292, d=0.799 (medium)
- weekday / Monday / hit_at_2: delta=0.2167, p_bh=0.003037, d=0.738 (medium)

## Non-significant But Large Effect (|d| >= 0.5)
- anomaly_direction / low_anomaly / rank2_rescue_on_miss1: delta=0.7500, p_bh=nan, d=1.732 (large)
- weekday / Saturday / rank2_rescue_on_miss1: delta=0.7000, p_bh=nan, d=1.673 (large)
- anomaly_direction / high_anomaly / rank2_rescue_on_miss1: delta=0.6667, p_bh=nan, d=1.633 (large)
- weekday / Wednesday / rank2_rescue_on_miss1: delta=0.5647, p_bh=0.06006, d=1.286 (large)
- weekday / Friday / rank2_rescue_on_miss1: delta=0.5833, p_bh=nan, d=1.278 (large)
- weekday / Tuesday / rank2_rescue_on_miss1: delta=0.5556, p_bh=nan, d=1.179 (large)
- pred_span_quartile / Q3 / rank2_rescue_on_miss1: delta=0.5714, p_bh=nan, d=1.155 (large)
- weekday / Sunday / rank2_rescue_on_miss1: delta=0.4000, p_bh=0.2272, d=0.862 (large)
- difficulty_failure / miss_day / rank2_rescue_on_miss1: delta=0.1365, p_bh=0.3832, d=0.520 (medium)

## Low-support Warnings (n_current<10 or n_baseline<10)
- anomaly_direction / high_anomaly / rank2_rescue_on_miss1: n_current=3, n_baseline=3
- anomaly_direction / low_anomaly / rank2_rescue_on_miss1: n_current=2, n_baseline=8
- difficulty_failure / miss_day / rank2_rescue_on_miss1: n_current=5, n_baseline=63
- pred_span_quartile / Q2 / rank2_rescue_on_miss1: n_current=8, n_baseline=16
- pred_span_quartile / Q3 / rank2_rescue_on_miss1: n_current=2, n_baseline=7
- pred_span_quartile / Q4 / rank2_rescue_on_miss1: n_current=0, n_baseline=0
- weekday / Friday / rank2_rescue_on_miss1: n_current=4, n_baseline=12
- weekday / Monday / rank2_rescue_on_miss1: n_current=1, n_baseline=16
- weekday / Saturday / rank2_rescue_on_miss1: n_current=4, n_baseline=10
- weekday / Sunday / rank2_rescue_on_miss1: n_current=5, n_baseline=10
- weekday / Thursday / rank2_rescue_on_miss1: n_current=4, n_baseline=12
- weekday / Tuesday / rank2_rescue_on_miss1: n_current=3, n_baseline=9
- weekday / Wednesday / rank2_rescue_on_miss1: n_current=5, n_baseline=17
