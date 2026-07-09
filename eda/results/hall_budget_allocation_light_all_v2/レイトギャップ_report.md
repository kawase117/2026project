# レイトギャップ Hall Budget Allocation Light

- source rows: 172310
- days: 469
- mean budget index: -1.799
- median budget index: -1.856
- mean budget zscore: 0.000
- median budget zscore: -0.012
- under budget days: 94
- balanced days: 265
- over budget days: 110

## Allocation
- top cell: is_x_day=0 (share=0.897, n=423)

## Offset Pairs
- chance same-regime rate: 0.414
- offset 7: n=459, mean_delta=-0.004, same_regime_rate=0.462, uplift=0.047
- offset 1: n=465, mean_delta=0.044, same_regime_rate=0.411, uplift=-0.004
- offset 14: n=452, mean_delta=-0.006, same_regime_rate=0.407, uplift=-0.007

## Lightweight Model
- note: trained
- status basis: roc_auc
- baseline accuracy: 0.7801418439716312
- accuracy: 0.5886524822695035
- accuracy delta: -0.19148936170212771
- roc_auc: 0.7266862170087977
- top feature: is_x_day:1.9710
