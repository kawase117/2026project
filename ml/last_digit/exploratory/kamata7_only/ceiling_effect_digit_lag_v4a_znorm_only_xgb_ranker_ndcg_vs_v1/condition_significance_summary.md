# Ceiling Effect Significance Summary

- Total rows: 48
- BH significant (0.05): 16

## Top Significant Rows (BH <= 0.05)
- pred_span_quartile / Q1 / loss_value: delta=-2635.1852, p_bh=0.016, d=-0.375 (small)
- anomaly_direction / low_anomaly / loss_value: delta=-2395.8333, p_bh=0.03144, d=-0.748 (medium)
- weekday / Wednesday / loss_value: delta=-2358.3333, p_bh=0.04075, d=-0.420 (small)
- weekday / Sunday / loss_value: delta=-1530.1587, p_bh=0.01468, d=-0.250 (small)
- weekday / Friday / loss_value: delta=-1473.0159, p_bh=0.01648, d=-0.445 (small)
- anomaly_direction / normal / loss_value: delta=-1145.0667, p_bh=2.601e-05, d=-0.272 (small)
- pred_span_quartile / Q2 / loss_value: delta=-1105.5556, p_bh=0.03144, d=-0.384 (small)
- weekday / Monday / loss_value: delta=-938.3333, p_bh=0.03144, d=-0.322 (small)
- anomaly_direction / normal / rank2_rescue_on_miss1: delta=0.4933, p_bh=0.002834, d=1.080 (large)
- pred_span_quartile / Q1 / rank2_rescue_on_miss1: delta=0.4286, p_bh=0.016, d=0.975 (large)

## Non-significant But Large Effect (|d| >= 0.5)
- weekday / Wednesday / rank2_rescue_on_miss1: delta=0.7647, p_bh=nan, d=1.855 (large)
- weekday / Saturday / rank2_rescue_on_miss1: delta=0.7000, p_bh=nan, d=1.673 (large)
- anomaly_direction / high_anomaly / rank2_rescue_on_miss1: delta=0.6667, p_bh=nan, d=1.633 (large)
- pred_span_quartile / Q3 / rank2_rescue_on_miss1: delta=0.5714, p_bh=nan, d=1.234 (large)
- pred_span_quartile / Q2 / rank2_rescue_on_miss1: delta=0.5000, p_bh=0.09796, d=1.090 (large)
- weekday / Sunday / rank2_rescue_on_miss1: delta=0.4667, p_bh=0.1232, d=1.020 (large)
- anomaly_direction / low_anomaly / hit_at_2: delta=0.2083, p_bh=0.09796, d=0.605 (medium)
- anomaly_direction / low_anomaly / rank2_rescue_on_miss1: delta=0.2500, p_bh=nan, d=0.500 (medium)

## Low-support Warnings (n_current<10 or n_baseline<10)
- anomaly_direction / high_anomaly / rank2_rescue_on_miss1: n_current=3, n_baseline=3
- anomaly_direction / low_anomaly / rank2_rescue_on_miss1: n_current=2, n_baseline=8
- difficulty_failure / miss_day / hit_at_2: n_current=9, n_baseline=150
- difficulty_failure / miss_day / loss_value: n_current=9, n_baseline=150
- difficulty_failure / miss_day / rank2_rescue_on_miss1: n_current=3, n_baseline=63
- pred_span_quartile / Q2 / rank2_rescue_on_miss1: n_current=5, n_baseline=16
- pred_span_quartile / Q3 / rank2_rescue_on_miss1: n_current=3, n_baseline=7
- pred_span_quartile / Q4 / rank2_rescue_on_miss1: n_current=0, n_baseline=0
- weekday / Friday / rank2_rescue_on_miss1: n_current=1, n_baseline=12
- weekday / Monday / rank2_rescue_on_miss1: n_current=1, n_baseline=16
- weekday / Saturday / rank2_rescue_on_miss1: n_current=4, n_baseline=10
- weekday / Sunday / rank2_rescue_on_miss1: n_current=6, n_baseline=10
- weekday / Thursday / rank2_rescue_on_miss1: n_current=4, n_baseline=12
- weekday / Tuesday / rank2_rescue_on_miss1: n_current=1, n_baseline=9
- weekday / Wednesday / rank2_rescue_on_miss1: n_current=3, n_baseline=17
