# 評価サマリ: digit_lag_v2r_current vs digit_lag_v1
## 結論
条件付き採用

## 全体スナップショット
- BH有意改善: 23件
- BH有意悪化: 0件
- 平均Cohen's d: 0.203
- 最大改善: weekday/Saturday (rank2_rescue_on_miss1, d=1.807)
- 最大悪化: なし
- current pairs: 435 (days=145)
- baseline overlap: 432 pairs

## メトリクス別評価
### hit_at_2
代表条件: `anomaly_direction/normal`
Δ mean: +0.1281, CI=[+0.0933, +0.1627], p_BH=3.179e-10, d=0.512 (medium)
有意改善: 7件, 有意悪化: 0件
→ 改善

### loss_value
代表条件: `anomaly_direction/normal`
Δ mean: -1244.4635, CI=[-1790.4133, -714.9267], p_BH=2.426e-05, d=-0.315 (small)
有意改善: 4件, 有意悪化: 0件
→ 改善

### rank2_rescue_on_miss1
代表条件: `pred_span_quartile/Q1`
Δ mean: +0.5619, CI=[+0.3175, +0.7746], p_BH=0.0006387, d=1.317 (large)
有意改善: 5件, 有意悪化: 0件
→ 改善

### critical_miss_rate
代表条件: `anomaly_direction/normal`
Δ mean: -0.1307, CI=[-0.1680, -0.0960], p_BH=3.179e-10, d=-0.518 (medium)
有意改善: 7件, 有意悪化: 0件
→ 改善

## リスク評価
- 悪化条件の有無: なし
- サンプルサイズ警告（n<10）: あり (12件)
- パイロット検証推奨: 推奨

## 補足
- 最も有効な条件: weekday/Saturday (rank2_rescue_on_miss1)
- ターゲット改善層: weekday/Saturday
