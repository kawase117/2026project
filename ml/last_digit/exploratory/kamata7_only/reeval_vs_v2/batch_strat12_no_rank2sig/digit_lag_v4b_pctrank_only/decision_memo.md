# 評価サマリ: digit_lag_v2r_current vs digit_lag_v1
## 結論
条件付き採用

## 全体スナップショット
- BH有意改善: 0件
- BH有意悪化: 0件
- 平均Cohen's d: 0.001
- 最大改善: なし
- 最大悪化: なし
- current pairs: 432 (days=144)
- baseline overlap: 432 pairs

## メトリクス別評価
### hit_at_2
代表条件: `anomaly_direction/anomaly`
Δ mean: +0.0175, CI=[+0.0000, +0.0526], p_BH=0.8013, d=0.187 (negligible)
有意改善: 0件, 有意悪化: 0件
→ 不変

### loss_value
代表条件: `anomaly_direction/anomaly`
Δ mean: -457.8947, CI=[-1084.2105, -14.0351], p_BH=0.8013, d=-0.094 (negligible)
有意改善: 0件, 有意悪化: 0件
→ 不変

### rank2_rescue_on_miss1
データなし

### critical_miss_rate
代表条件: `anomaly_direction/anomaly`
Δ mean: -0.0175, CI=[-0.0526, +0.0000], p_BH=0.8013, d=-0.187 (negligible)
有意改善: 0件, 有意悪化: 0件
→ 不変

## リスク評価
- 悪化条件の有無: なし
- サンプルサイズ警告（n<10）: あり (3件)
- パイロット検証推奨: 推奨

## 補足
