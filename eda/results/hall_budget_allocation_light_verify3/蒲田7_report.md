# 蒲田7 Hall Budget Allocation Light

- source rows: 253313
- days: 360
- mean budget index: 4.060
- median budget index: 3.824
- mean budget zscore: -0.000
- median budget zscore: -0.053
- under budget days: 65
- balanced days: 234
- over budget days: 61

## Allocation
- top cell: is_x_day=0 (share=0.661, n=259)

## Offset Pairs
- chance same-regime rate: 0.484
- offset 7: n=350, mean_delta=-0.343, same_regime_rate=0.563, uplift=0.079
- offset 1: n=356, mean_delta=-0.139, same_regime_rate=0.534, uplift=0.050
- offset 14: n=343, mean_delta=-0.494, same_regime_rate=0.531, uplift=0.047

## Lightweight Model
- note: trained
- status basis: roc_auc
- baseline accuracy: 0.962962962962963
- accuracy: 0.7037037037037037
- accuracy delta: -0.2592592592592593
- roc_auc: 0.8509615384615384
- top feature: weekday_nth_Sat3:-1.2123
