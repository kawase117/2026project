# 評価サマリ: digit_lag_v2r_current vs digit_lag_v1
## 結論
条件付き採用

## 全体スナップショット
- BH有意改善: 14件
- BH有意悪化: 0件
- 平均Cohen's d: 0.400
- 最大改善: weekday/Saturday (rank2_rescue_on_miss1, d=1.807)
- 最大悪化: なし
- current pairs: 432 (days=144)
- baseline overlap: 432 pairs

## メトリクス別評価
### hit_at_2
代表条件: `anomaly_direction/normal`
Δ mean: +0.1280, CI=[+0.0933, +0.1627], p_BH=4.654e-10, d=0.510 (medium)
有意改善: 7件, 有意悪化: 0件
→ 改善

### loss_value
代表条件: `anomaly_direction/normal`
Δ mean: -1047.7333, CI=[-1623.7400, -513.0000], p_BH=0.0002359, d=-0.241 (small)
有意改善: 3件, 有意悪化: 0件
→ 改善

### rank2_rescue_on_miss1
代表条件: `pred_span_quartile/Q1`
Δ mean: +0.4678, CI=[+0.2166, +0.6965], p_BH=0.003392, d=1.068 (large)
有意改善: 4件, 有意悪化: 0件
→ 改善

## リスク評価
- 悪化条件の有無: なし
- サンプルサイズ警告（n<10）: あり (12件)
- パイロット検証推奨: 推奨

## 補足
- 最も有効な条件: weekday/Saturday (rank2_rescue_on_miss1)
- ターゲット改善層: weekday/Saturday
