# 評価サマリ: digit_lag_v2r_current vs digit_lag_v1
## 結論
条件付き採用

## 全体スナップショット
- BH有意改善: 15件
- BH有意悪化: 0件
- 平均Cohen's d: 0.404
- 最大改善: pred_span_quartile/Q2 (rank2_rescue_on_miss1, d=1.173)
- 最大悪化: なし
- current pairs: 432 (days=144)
- baseline overlap: 432 pairs

## メトリクス別評価
### hit_at_2
代表条件: `anomaly_direction/normal`
Δ mean: +0.1253, CI=[+0.0933, +0.1600], p_BH=7.371e-10, d=0.495 (small)
有意改善: 8件, 有意悪化: 0件
→ 改善

### loss_value
代表条件: `anomaly_direction/normal`
Δ mean: -1153.8667, CI=[-1684.8667, -663.4600], p_BH=6.906e-05, d=-0.287 (small)
有意改善: 4件, 有意悪化: 0件
→ 改善

### rank2_rescue_on_miss1
代表条件: `anomaly_direction/normal`
Δ mean: +0.4552, CI=[+0.2381, +0.6648], p_BH=0.002493, d=0.993 (large)
有意改善: 3件, 有意悪化: 0件
→ 改善

## リスク評価
- 悪化条件の有無: なし
- サンプルサイズ警告（n<10）: あり (13件)
- パイロット検証推奨: 推奨

## 補足
- 最も有効な条件: pred_span_quartile/Q2 (rank2_rescue_on_miss1)
- ターゲット改善層: pred_span_quartile/Q2
