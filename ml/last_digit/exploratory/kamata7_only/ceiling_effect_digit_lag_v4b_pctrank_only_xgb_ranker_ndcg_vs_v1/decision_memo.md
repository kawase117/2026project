# 評価サマリ: digit_lag_v2r_current vs digit_lag_v1
## 結論
条件付き採用

## 全体スナップショット
- BH有意改善: 12件
- BH有意悪化: 0件
- 平均Cohen's d: 0.392
- 最大改善: pred_span_quartile/Q1 (hit_at_2, d=1.056)
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
Δ mean: -891.2000, CI=[-1460.8133, -303.4200], p_BH=0.001055, d=-0.195 (negligible)
有意改善: 3件, 有意悪化: 0件
→ 改善

### rank2_rescue_on_miss1
代表条件: `pred_span_quartile/Q1`
Δ mean: +0.3333, CI=[+0.0554, +0.6111], p_BH=0.04767, d=0.749 (medium)
有意改善: 1件, 有意悪化: 0件
→ 改善

## リスク評価
- 悪化条件の有無: なし
- サンプルサイズ警告（n<10）: あり (13件)
- パイロット検証推奨: 推奨

## 補足
- 最も有効な条件: pred_span_quartile/Q1 (hit_at_2)
- ターゲット改善層: pred_span_quartile/Q1
