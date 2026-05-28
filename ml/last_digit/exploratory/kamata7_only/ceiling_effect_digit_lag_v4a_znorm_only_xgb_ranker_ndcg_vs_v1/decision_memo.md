# 評価サマリ: digit_lag_v2r_current vs digit_lag_v1
## 結論
条件付き採用

## 全体スナップショット
- BH有意改善: 16件
- BH有意悪化: 0件
- 平均Cohen's d: 0.330
- 最大改善: pred_span_quartile/Q1 (hit_at_2, d=1.098)
- 最大悪化: なし
- current pairs: 432 (days=144)
- baseline overlap: 432 pairs

## メトリクス別評価
### hit_at_2
代表条件: `anomaly_direction/normal`
Δ mean: +0.1307, CI=[+0.0960, +0.1680], p_BH=2.523e-10, d=0.527 (medium)
有意改善: 6件, 有意悪化: 0件
→ 改善

### loss_value
代表条件: `anomaly_direction/normal`
Δ mean: -1145.0667, CI=[-1740.0400, -556.4600], p_BH=2.601e-05, d=-0.272 (small)
有意改善: 8件, 有意悪化: 0件
→ 改善

### rank2_rescue_on_miss1
代表条件: `anomaly_direction/normal`
Δ mean: +0.4933, CI=[+0.2267, +0.7067], p_BH=0.002834, d=1.080 (large)
有意改善: 2件, 有意悪化: 0件
→ 改善

## リスク評価
- 悪化条件の有無: なし
- サンプルサイズ警告（n<10）: あり (15件)
- パイロット検証推奨: 推奨

## 補足
- 最も有効な条件: pred_span_quartile/Q1 (hit_at_2)
- ターゲット改善層: pred_span_quartile/Q1
