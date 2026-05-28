# Ceiling Effect Significance Summary

- Total rows: 64
- BH significant (0.05): 23

## Top Significant Rows (BH <= 0.05)
- anomaly_direction / low_anomaly / loss_value: delta=-2500.0000, p_bh=0.03043, d=-0.795 (medium)
- weekday / Sunday / loss_value: delta=-2349.2063, p_bh=0.005693, d=-0.519 (medium)
- anomaly_direction / normal / loss_value: delta=-1244.4635, p_bh=2.426e-05, d=-0.315 (small)
- weekday / Saturday / loss_value: delta=-928.5714, p_bh=0.03483, d=-0.432 (small)
- weekday / Saturday / rank2_rescue_on_miss1: delta=0.7000, p_bh=0.03229, d=1.807 (large)
- weekday / Wednesday / rank2_rescue_on_miss1: delta=0.5980, p_bh=0.03483, d=1.389 (large)
- pred_span_quartile / Q1 / rank2_rescue_on_miss1: delta=0.5619, p_bh=0.0006387, d=1.317 (large)
- anomaly_direction / normal / rank2_rescue_on_miss1: delta=0.5169, p_bh=0.001092, d=1.143 (large)
- pred_span_quartile / Q2 / rank2_rescue_on_miss1: delta=0.5000, p_bh=0.03229, d=1.225 (large)
- pred_span_quartile / Q1 / critical_miss_rate: delta=-0.4164, p_bh=0.03483, d=-1.117 (large)

## Non-significant But Large Effect (|d| >= 0.5)
- weekday / Monday / rank2_rescue_on_miss1: delta=0.8125, p_bh=nan, d=2.082 (large)
- anomaly_direction / low_anomaly / rank2_rescue_on_miss1: delta=0.7500, p_bh=nan, d=1.837 (large)
- anomaly_direction / high_anomaly / rank2_rescue_on_miss1: delta=0.5238, p_bh=nan, d=1.200 (large)
- weekday / Friday / rank2_rescue_on_miss1: delta=0.5833, p_bh=nan, d=1.183 (large)
- weekday / Tuesday / rank2_rescue_on_miss1: delta=0.5556, p_bh=nan, d=1.179 (large)
- weekday / Thursday / rank2_rescue_on_miss1: delta=0.3833, p_bh=0.289, d=0.770 (medium)
- difficulty_failure / miss_day / rank2_rescue_on_miss1: delta=0.1365, p_bh=0.4164, d=0.520 (medium)

## Low-support Warnings (n_current<10 or n_baseline<10)
- anomaly_direction / high_anomaly / rank2_rescue_on_miss1: n_current=7, n_baseline=3
- anomaly_direction / low_anomaly / rank2_rescue_on_miss1: n_current=3, n_baseline=8
- difficulty_failure / miss_day / rank2_rescue_on_miss1: n_current=5, n_baseline=63
- pred_span_quartile / Q3 / rank2_rescue_on_miss1: n_current=2, n_baseline=7
- pred_span_quartile / Q4 / rank2_rescue_on_miss1: n_current=0, n_baseline=0
- weekday / Friday / rank2_rescue_on_miss1: n_current=2, n_baseline=12
- weekday / Monday / rank2_rescue_on_miss1: n_current=2, n_baseline=16
- weekday / Saturday / rank2_rescue_on_miss1: n_current=6, n_baseline=10
- weekday / Sunday / rank2_rescue_on_miss1: n_current=3, n_baseline=10
- weekday / Thursday / rank2_rescue_on_miss1: n_current=5, n_baseline=12
- weekday / Tuesday / rank2_rescue_on_miss1: n_current=3, n_baseline=9
- weekday / Wednesday / rank2_rescue_on_miss1: n_current=6, n_baseline=17
