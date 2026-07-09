# 金時 Hall Budget Allocation Light

- source rows: 70550
- days: 547
- mean budget index: -0.753
- median budget index: -0.761
- mean budget zscore: 0.000
- median budget zscore: -0.001
- under budget days: 123
- balanced days: 303
- over budget days: 121

## Allocation
- top cell: is_x_day=0 (share=0.865, n=476)

## Offset Pairs
- chance same-regime rate: 0.406
- offset 7: n=537, mean_delta=0.026, same_regime_rate=0.432, uplift=0.026
- offset 14: n=530, mean_delta=0.008, same_regime_rate=0.385, uplift=-0.021
- offset 1: n=543, mean_delta=-0.001, same_regime_rate=0.379, uplift=-0.027

## Lightweight Model
- note: trained
- status basis: roc_auc
- baseline accuracy: 0.7317073170731707
- accuracy: 0.5609756097560976
- accuracy delta: -0.1707317073170731
- roc_auc: 0.5831439393939394
- top feature: weekday_nth_Tue4:1.2677
