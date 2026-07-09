# ヒロキ Hall Budget Allocation Light

- source rows: 121335
- days: 547
- mean budget index: -2.229
- median budget index: -2.124
- mean budget zscore: 0.000
- median budget zscore: 0.019
- under budget days: 118
- balanced days: 305
- over budget days: 124

## Allocation
- top cell: is_x_day=0 (share=0.915, n=493)

## Offset Pairs
- chance same-regime rate: 0.409
- offset 7: n=537, mean_delta=-0.025, same_regime_rate=0.423, uplift=0.014
- offset 14: n=530, mean_delta=-0.056, same_regime_rate=0.408, uplift=-0.001
- offset 1: n=543, mean_delta=0.006, same_regime_rate=0.387, uplift=-0.022

## Lightweight Model
- note: trained
- status basis: roc_auc
- baseline accuracy: 0.7682926829268293
- accuracy: 0.6646341463414634
- accuracy delta: -0.10365853658536583
- roc_auc: 0.6276106934001671
- top feature: is_x_day:1.8858
