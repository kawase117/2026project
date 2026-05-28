# KPI Decision Memo

## Current KPI Snapshot
- n_pairs: 432
- hit_at_2_rate: 0.9907
- loss_mean: 917.82
- loss_p50 / p90 / p95: 0.00 / 1300.00 / 4960.00
- rank2_rescue_on_miss1: 0.7667
- critical_miss_rate: 0.0162
- catastrophic_rate: 0.0208

## Baseline Delta
- hit_at_2_rate: current=0.9907, baseline=0.8634, delta=+0.1273, direction=improved
- loss_mean: current=917.8241, baseline=1885.4167, delta=-967.5926, direction=improved
- rank2_rescue_on_miss1: current=0.7667, baseline=0.3023, delta=+0.4643, direction=improved
- critical_miss_rate: current=0.0162, baseline=0.1389, delta=-0.1227, direction=improved
- catastrophic_rate: current=0.0208, baseline=0.0347, delta=-0.0139, direction=improved

## Decision
adopt_or_pilot
