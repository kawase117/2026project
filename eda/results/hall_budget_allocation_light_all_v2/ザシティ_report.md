# ザシティ Hall Budget Allocation Light

- source rows: 61711
- days: 548
- mean budget index: -5.182
- median budget index: -5.636
- mean budget zscore: 0.000
- median budget zscore: -0.062
- under budget days: 127
- balanced days: 285
- over budget days: 136

## Allocation
- top cell: is_x_day=0 (share=0.851, n=440)

## Offset Pairs
- chance same-regime rate: 0.386
- offset 7: n=539, mean_delta=0.057, same_regime_rate=0.412, uplift=0.026
- offset 14: n=532, mean_delta=0.156, same_regime_rate=0.385, uplift=-0.000
- offset 1: n=545, mean_delta=-0.027, same_regime_rate=0.345, uplift=-0.041

## Lightweight Model
- note: trained
- status basis: roc_auc
- baseline accuracy: 0.75
- accuracy: 0.6524390243902439
- accuracy delta: -0.09756097560975607
- roc_auc: 0.5599841364267301
- top feature: is_x_day:1.0020
