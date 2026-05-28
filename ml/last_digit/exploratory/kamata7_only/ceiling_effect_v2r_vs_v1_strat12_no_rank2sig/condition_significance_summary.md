# Ceiling Effect Significance Summary

- Total rows: 36
- BH significant (0.05): 11

## Top Significant Rows (BH <= 0.05)
- anomaly_direction / normal / loss_value: delta=-1047.7333, p_bh=8.284e-05, d=-0.241 (small)
- weekday / fri_sat / loss_value: delta=-994.4444, p_bh=0.02193, d=-0.334 (small)
- pred_span_quartile / Q1 / hit_at_2: delta=0.4074, p_bh=0.04682, d=1.098 (large)
- weekday / wednesday / critical_miss_rate: delta=-0.2000, p_bh=0.002128, d=-0.650 (medium)
- weekday / wednesday / hit_at_2: delta=0.2000, p_bh=0.002128, d=0.650 (medium)
- weekday / mon_thu / hit_at_2: delta=0.1311, p_bh=2.265e-05, d=0.527 (medium)
- weekday / mon_thu / critical_miss_rate: delta=-0.1311, p_bh=2.265e-05, d=-0.527 (medium)
- anomaly_direction / normal / hit_at_2: delta=0.1280, p_bh=4.087e-10, d=0.510 (medium)
- anomaly_direction / normal / critical_miss_rate: delta=-0.1227, p_bh=3.207e-09, d=-0.471 (small)
- weekday / fri_sat / hit_at_2: delta=0.1111, p_bh=0.0009402, d=0.498 (small)

## Non-significant But Large Effect (|d| >= 0.5)
- pred_span_quartile / Q1 / critical_miss_rate: delta=-0.3981, p_bh=0.1176, d=-1.039 (large)

## Low-support Warnings (n_current<10 or n_baseline<10)
- None
