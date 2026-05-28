# 評価サマリ: digit_lag_v2r_current vs digit_lag_v1
## 結論
採用推奨

## 全体スナップショット
- BH有意改善: 11件
- BH有意悪化: 0件
- 平均Cohen's d: -0.054
- 最大改善: pred_span_quartile/Q1 (hit_at_2, d=1.098)
- 最大悪化: なし
- current pairs: 432 (days=144)
- baseline overlap: 432 pairs

## メトリクス別評価
### hit_at_2
代表条件: `anomaly_direction/normal`
Δ mean: +0.1280, CI=[+0.0933, +0.1627], p_BH=4.087e-10, d=0.510 (medium)
有意改善: 5件, 有意悪化: 0件
→ 改善

### loss_value
代表条件: `anomaly_direction/normal`
Δ mean: -1047.7333, CI=[-1614.1667, -502.1333], p_BH=8.284e-05, d=-0.241 (small)
有意改善: 2件, 有意悪化: 0件
→ 改善

### rank2_rescue_on_miss1
データなし

### critical_miss_rate
代表条件: `anomaly_direction/normal`
Δ mean: -0.1227, CI=[-0.1600, -0.0880], p_BH=3.207e-09, d=-0.471 (small)
有意改善: 4件, 有意悪化: 0件
→ 改善

## リスク評価
- 悪化条件の有無: なし
- サンプルサイズ警告（n<10）: なし (0件)
- パイロット検証推奨: 不要

## 補足
- 最も有効な条件: pred_span_quartile/Q1 (hit_at_2)
- ターゲット改善層: pred_span_quartile/Q1
