# Ceiling Effect Significance Summary

- Total rows: 48
- BH significant (0.05): 14

## Top Significant Rows (BH <= 0.05)
- anomaly_direction / low_anomaly / loss_value: delta=-2500.0000, p_bh=0.03713, d=-0.795 (medium)
- anomaly_direction / normal / loss_value: delta=-1047.7333, p_bh=0.0002359, d=-0.241 (small)
- weekday / Saturday / loss_value: delta=-928.5714, p_bh=0.0419, d=-0.432 (small)
- weekday / Saturday / rank2_rescue_on_miss1: delta=0.7000, p_bh=0.04019, d=1.807 (large)
- weekday / Wednesday / rank2_rescue_on_miss1: delta=0.5980, p_bh=0.0419, d=1.389 (large)
- pred_span_quartile / Q1 / rank2_rescue_on_miss1: delta=0.4678, p_bh=0.003392, d=1.068 (large)
- pred_span_quartile / Q1 / hit_at_2: delta=0.4074, p_bh=0.0419, d=1.098 (large)
- anomaly_direction / normal / rank2_rescue_on_miss1: delta=0.3933, p_bh=0.009965, d=0.845 (large)
- anomaly_direction / low_anomaly / hit_at_2: delta=0.2500, p_bh=0.0419, d=0.799 (medium)
- weekday / Monday / hit_at_2: delta=0.2167, p_bh=0.003392, d=0.738 (medium)

## Non-significant But Large Effect (|d| >= 0.5)
- weekday / Monday / rank2_rescue_on_miss1: delta=0.8125, p_bh=nan, d=2.082 (large)
- anomaly_direction / low_anomaly / rank2_rescue_on_miss1: delta=0.7500, p_bh=nan, d=1.837 (large)
- anomaly_direction / high_anomaly / rank2_rescue_on_miss1: delta=0.5238, p_bh=nan, d=1.200 (large)
- weekday / Friday / rank2_rescue_on_miss1: delta=0.5833, p_bh=nan, d=1.183 (large)
- weekday / Tuesday / rank2_rescue_on_miss1: delta=0.5556, p_bh=nan, d=1.179 (large)
- pred_span_quartile / Q2 / rank2_rescue_on_miss1: delta=0.4091, p_bh=0.07296, d=0.923 (large)
- weekday / Thursday / rank2_rescue_on_miss1: delta=0.3833, p_bh=0.3085, d=0.770 (medium)
- difficulty_failure / miss_day / rank2_rescue_on_miss1: delta=0.1365, p_bh=0.4338, d=0.520 (medium)

## Low-support Warnings (n_current<10 or n_baseline<10)
- anomaly_direction / high_anomaly / rank2_rescue_on_miss1: n_current=7, n_baseline=3
- anomaly_direction / low_anomaly / rank2_rescue_on_miss1: n_current=3, n_baseline=8
- difficulty_failure / miss_day / rank2_rescue_on_miss1: n_current=5, n_baseline=63
- pred_span_quartile / Q3 / rank2_rescue_on_miss1: n_current=2, n_baseline=7
- pred_span_quartile / Q4 / rank2_rescue_on_miss1: n_current=0, n_baseline=0
- weekday / Friday / rank2_rescue_on_miss1: n_current=2, n_baseline=12
- weekday / Monday / rank2_rescue_on_miss1: n_current=2, n_baseline=16
- weekday / Saturday / rank2_rescue_on_miss1: n_current=6, n_baseline=10
- weekday / Sunday / rank2_rescue_on_miss1: n_current=6, n_baseline=10
- weekday / Thursday / rank2_rescue_on_miss1: n_current=5, n_baseline=12
- weekday / Tuesday / rank2_rescue_on_miss1: n_current=3, n_baseline=9
- weekday / Wednesday / rank2_rescue_on_miss1: n_current=6, n_baseline=17
