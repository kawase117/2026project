# Ceiling Effect Significance Summary

- Total rows: 48
- BH significant (0.05): 12

## Top Significant Rows (BH <= 0.05)
- anomaly_direction / low_anomaly / loss_value: delta=-2500.0000, p_bh=0.03532, d=-0.795 (medium)
- weekday / Wednesday / loss_value: delta=-2486.6667, p_bh=0.03532, d=-0.472 (small)
- anomaly_direction / normal / loss_value: delta=-891.2000, p_bh=0.001055, d=-0.195 (negligible)
- pred_span_quartile / Q1 / hit_at_2: delta=0.3981, p_bh=0.01221, d=1.056 (large)
- pred_span_quartile / Q1 / rank2_rescue_on_miss1: delta=0.3333, p_bh=0.04767, d=0.749 (medium)
- anomaly_direction / low_anomaly / hit_at_2: delta=0.2500, p_bh=0.04767, d=0.799 (medium)
- weekday / Monday / hit_at_2: delta=0.2167, p_bh=0.004049, d=0.738 (medium)
- weekday / Wednesday / hit_at_2: delta=0.2000, p_bh=0.005187, d=0.650 (medium)
- anomaly_direction / normal / hit_at_2: delta=0.1253, p_bh=7.371e-10, d=0.495 (small)
- weekday / Friday / hit_at_2: delta=0.1111, p_bh=0.03532, d=0.496 (small)

## Non-significant But Large Effect (|d| >= 0.5)
- weekday / Monday / rank2_rescue_on_miss1: delta=0.8125, p_bh=nan, d=2.082 (large)
- anomaly_direction / low_anomaly / rank2_rescue_on_miss1: delta=0.7500, p_bh=nan, d=1.837 (large)
- anomaly_direction / high_anomaly / rank2_rescue_on_miss1: delta=0.6667, p_bh=nan, d=1.826 (large)
- weekday / Saturday / rank2_rescue_on_miss1: delta=0.7000, p_bh=nan, d=1.673 (large)
- weekday / Wednesday / rank2_rescue_on_miss1: delta=0.5647, p_bh=0.06666, d=1.286 (large)
- weekday / Tuesday / rank2_rescue_on_miss1: delta=0.5556, p_bh=nan, d=1.118 (large)
- difficulty_failure / miss_day / rank2_rescue_on_miss1: delta=0.2698, p_bh=0.06666, d=0.980 (large)
- pred_span_quartile / Q2 / rank2_rescue_on_miss1: delta=0.3889, p_bh=0.1087, d=0.843 (large)
- anomaly_direction / normal / rank2_rescue_on_miss1: delta=0.2816, p_bh=0.06666, d=0.596 (medium)

## Low-support Warnings (n_current<10 or n_baseline<10)
- anomaly_direction / high_anomaly / rank2_rescue_on_miss1: n_current=4, n_baseline=3
- anomaly_direction / low_anomaly / rank2_rescue_on_miss1: n_current=3, n_baseline=8
- difficulty_failure / miss_day / rank2_rescue_on_miss1: n_current=6, n_baseline=63
- pred_span_quartile / Q2 / rank2_rescue_on_miss1: n_current=9, n_baseline=16
- pred_span_quartile / Q3 / rank2_rescue_on_miss1: n_current=1, n_baseline=7
- pred_span_quartile / Q4 / rank2_rescue_on_miss1: n_current=0, n_baseline=0
- weekday / Friday / rank2_rescue_on_miss1: n_current=1, n_baseline=12
- weekday / Monday / rank2_rescue_on_miss1: n_current=2, n_baseline=16
- weekday / Saturday / rank2_rescue_on_miss1: n_current=4, n_baseline=10
- weekday / Sunday / rank2_rescue_on_miss1: n_current=6, n_baseline=10
- weekday / Thursday / rank2_rescue_on_miss1: n_current=4, n_baseline=12
- weekday / Tuesday / rank2_rescue_on_miss1: n_current=2, n_baseline=9
- weekday / Wednesday / rank2_rescue_on_miss1: n_current=5, n_baseline=17
