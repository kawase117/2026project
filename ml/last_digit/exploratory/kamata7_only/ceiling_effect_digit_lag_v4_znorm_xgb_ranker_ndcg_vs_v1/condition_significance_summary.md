# Ceiling Effect Significance Summary

- Total rows: 48
- BH significant (0.05): 14

## Top Significant Rows (BH <= 0.05)
- weekday / Wednesday / loss_value: delta=-2891.6667, p_bh=0.008925, d=-0.564 (medium)
- pred_span_quartile / Q1 / loss_value: delta=-2434.2593, p_bh=0.02494, d=-0.326 (small)
- anomaly_direction / low_anomaly / loss_value: delta=-2395.8333, p_bh=0.03397, d=-0.748 (medium)
- weekday / Friday / loss_value: delta=-1463.4921, p_bh=0.02901, d=-0.443 (small)
- pred_span_quartile / Q2 / loss_value: delta=-1255.5556, p_bh=0.02901, d=-0.441 (small)
- anomaly_direction / normal / loss_value: delta=-1109.0667, p_bh=3.991e-05, d=-0.251 (small)
- anomaly_direction / normal / rank2_rescue_on_miss1: delta=0.5058, p_bh=0.002367, d=1.113 (large)
- pred_span_quartile / Q1 / rank2_rescue_on_miss1: delta=0.4286, p_bh=0.01652, d=0.975 (large)
- pred_span_quartile / Q1 / hit_at_2: delta=0.4074, p_bh=0.004998, d=1.098 (large)
- weekday / Monday / hit_at_2: delta=0.2167, p_bh=0.002367, d=0.738 (medium)

## Non-significant But Large Effect (|d| >= 0.5)
- weekday / Wednesday / rank2_rescue_on_miss1: delta=0.7647, p_bh=nan, d=1.855 (large)
- anomaly_direction / high_anomaly / rank2_rescue_on_miss1: delta=0.6667, p_bh=nan, d=1.826 (large)
- weekday / Saturday / rank2_rescue_on_miss1: delta=0.7000, p_bh=nan, d=1.602 (large)
- pred_span_quartile / Q3 / rank2_rescue_on_miss1: delta=0.5714, p_bh=nan, d=1.234 (large)
- weekday / Friday / rank2_rescue_on_miss1: delta=0.5833, p_bh=nan, d=1.232 (large)
- pred_span_quartile / Q2 / rank2_rescue_on_miss1: delta=0.5000, p_bh=0.05503, d=1.146 (large)
- weekday / Tuesday / rank2_rescue_on_miss1: delta=0.5556, p_bh=nan, d=1.118 (large)
- weekday / Sunday / rank2_rescue_on_miss1: delta=0.4000, p_bh=0.2299, d=0.862 (large)
- anomaly_direction / low_anomaly / hit_at_2: delta=0.2083, p_bh=0.09712, d=0.605 (medium)
- anomaly_direction / low_anomaly / rank2_rescue_on_miss1: delta=0.2500, p_bh=nan, d=0.500 (medium)

## Low-support Warnings (n_current<10 or n_baseline<10)
- anomaly_direction / high_anomaly / rank2_rescue_on_miss1: n_current=4, n_baseline=3
- anomaly_direction / low_anomaly / rank2_rescue_on_miss1: n_current=2, n_baseline=8
- difficulty_failure / miss_day / hit_at_2: n_current=9, n_baseline=150
- difficulty_failure / miss_day / loss_value: n_current=9, n_baseline=150
- difficulty_failure / miss_day / rank2_rescue_on_miss1: n_current=3, n_baseline=63
- pred_span_quartile / Q2 / rank2_rescue_on_miss1: n_current=7, n_baseline=16
- pred_span_quartile / Q3 / rank2_rescue_on_miss1: n_current=3, n_baseline=7
- pred_span_quartile / Q4 / rank2_rescue_on_miss1: n_current=0, n_baseline=0
- weekday / Friday / rank2_rescue_on_miss1: n_current=3, n_baseline=12
- weekday / Monday / rank2_rescue_on_miss1: n_current=1, n_baseline=16
- weekday / Saturday / rank2_rescue_on_miss1: n_current=3, n_baseline=10
- weekday / Sunday / rank2_rescue_on_miss1: n_current=5, n_baseline=10
- weekday / Thursday / rank2_rescue_on_miss1: n_current=5, n_baseline=12
- weekday / Tuesday / rank2_rescue_on_miss1: n_current=2, n_baseline=9
- weekday / Wednesday / rank2_rescue_on_miss1: n_current=3, n_baseline=17
