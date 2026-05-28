# 評価サマリ: digit_lag_v2r_current vs digit_lag_v1
## 結論
条件付き採用

## 全体スナップショット
- BH有意改善: 0件
- BH有意悪化: 0件
- 平均Cohen's d: -0.026
- 最大改善: なし
- 最大悪化: なし
- current pairs: 584 (days=146)
- baseline overlap: 584 pairs

## メトリクス別評価
### hit_at_2
代表条件: `pred_span_quartile/Q1`
Δ mean: -0.0699, CI=[-0.2083, -0.0278], p_BH=0.3766, d=-0.307 (small)
有意改善: 0件, 有意悪化: 0件
→ 不変

### loss_value
代表条件: `difficulty_failure/miss_day`
Δ mean: -2808.0357, CI=[-6674.1295, +291.9643], p_BH=0.4621, d=-0.645 (medium)
有意改善: 0件, 有意悪化: 0件
→ 不変

### rank2_rescue_on_miss1
データなし

### critical_miss_rate
代表条件: `pred_span_quartile/Q1`
Δ mean: +0.0769, CI=[+0.0278, +0.2083], p_BH=0.3766, d=0.329 (small)
有意改善: 0件, 有意悪化: 0件
→ 不変

## リスク評価
- 悪化条件の有無: なし
- サンプルサイズ警告（n<10）: なし (0件)
- パイロット検証推奨: 不要

## 補足
