# 楽園 Hall Budget Allocation Light

- source rows: 257362
- days: 548
- mean budget index: 1.115
- median budget index: 1.153
- mean budget zscore: 0.000
- median budget zscore: 0.009
- under budget days: 129
- balanced days: 294
- over budget days: 125

## Allocation
- top cell: is_x_day=0 (share=0.920, n=512)

## Offset Pairs
- chance same-regime rate: 0.395
- offset 14: n=532, mean_delta=0.032, same_regime_rate=0.430, uplift=0.035
- offset 1: n=545, mean_delta=-0.043, same_regime_rate=0.415, uplift=0.019
- offset 7: n=539, mean_delta=0.052, same_regime_rate=0.397, uplift=0.002

## Lightweight Model
- note: trained
- status basis: roc_auc
- baseline accuracy: 0.7926829268292683
- accuracy: 0.6097560975609756
- accuracy delta: -0.18292682926829273
- roc_auc: 0.6273755656108597
- top feature: weekday_nth_Thu1:-0.9166
