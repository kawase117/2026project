# 評価サマリ: digit_lag_v2r_current vs digit_lag_v1
## 結論
条件付き採用

## 全体スナップショット
- BH有意改善: 0件
- BH有意悪化: 0件
- 平均Cohen's d: 0.020
- 最大改善: なし
- 最大悪化: なし
- current pairs: 435 (days=145)
- baseline overlap: 435 pairs

## メトリクス別評価
### hit_at_2
代表条件: `pred_span_quartile/Q3`
Δ mean: +0.0092, CI=[+0.0000, +0.0600], p_BH=0.8849, d=0.135 (negligible)
有意改善: 0件, 有意悪化: 0件
→ 不変

### loss_value
代表条件: `anomaly_direction/anomaly`
Δ mean: +514.0351, CI=[-1300.0000, +2240.3509], p_BH=0.8849, d=0.109 (negligible)
有意改善: 0件, 有意悪化: 0件
→ 不変

### rank2_rescue_on_miss1
データなし

### critical_miss_rate
代表条件: `pred_span_quartile/Q3`
Δ mean: -0.0092, CI=[-0.0600, +0.0000], p_BH=0.8849, d=-0.135 (negligible)
有意改善: 0件, 有意悪化: 0件
→ 不変

## リスク評価
- 悪化条件の有無: なし
- サンプルサイズ警告（n<10）: なし (0件)
- パイロット検証推奨: 不要

## 補足
