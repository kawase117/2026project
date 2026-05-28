# Ceiling Effect Significance Summary

- Total rows: 36
- BH significant (0.05): 15

## Top Significant Rows (BH <= 0.05)
- weekday / sunday / loss_value: delta=-2494.8413, p_bh=0.00366, d=-0.594 (medium)
- anomaly_direction / normal / loss_value: delta=-1359.1585, p_bh=1.559e-05, d=-0.370 (small)
- weekday / fri_sat / loss_value: delta=-1041.4683, p_bh=0.01993, d=-0.375 (small)
- pred_span_quartile / Q1 / critical_miss_rate: delta=-0.4235, p_bh=0.02257, d=-1.228 (large)
- pred_span_quartile / Q1 / hit_at_2: delta=0.4142, p_bh=0.02257, d=1.204 (large)
- weekday / wednesday / hit_at_2: delta=0.2042, p_bh=0.002128, d=0.718 (medium)
- weekday / wednesday / critical_miss_rate: delta=-0.2042, p_bh=0.002128, d=-0.718 (medium)
- anomaly_direction / normal / critical_miss_rate: delta=-0.1328, p_bh=2.043e-10, d=-0.570 (medium)
- weekday / mon_thu / hit_at_2: delta=0.1326, p_bh=1.812e-05, d=0.581 (medium)
- weekday / mon_thu / critical_miss_rate: delta=-0.1326, p_bh=1.812e-05, d=-0.581 (medium)

## Non-significant But Large Effect (|d| >= 0.5)
- pred_span_quartile / Q1 / loss_value: delta=-3434.3499, p_bh=0.1677, d=-0.569 (medium)

## Low-support Warnings (n_current<10 or n_baseline<10)
- None
