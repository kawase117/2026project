# 評価サマリ: digit_lag_v2r_current vs digit_lag_v1
## 結論
採用推奨

## 全体スナップショット
- BH有意改善: 15件
- BH有意悪化: 0件
- 平均Cohen's d: -0.115
- 最大改善: pred_span_quartile/Q1 (critical_miss_rate, d=-1.228)
- 最大悪化: なし
- current pairs: 584 (days=146)
- baseline overlap: 432 pairs

## メトリクス別評価
### hit_at_2
代表条件: `anomaly_direction/normal`
Δ mean: +0.1301, CI=[+0.0933, +0.1627], p_BH=2.043e-10, d=0.563 (medium)
有意改善: 6件, 有意悪化: 0件
→ 改善

### loss_value
代表条件: `anomaly_direction/normal`
Δ mean: -1359.1585, CI=[-1790.4133, -714.9267], p_BH=1.559e-05, d=-0.370 (small)
有意改善: 3件, 有意悪化: 0件
→ 改善

### rank2_rescue_on_miss1
データなし

### critical_miss_rate
代表条件: `anomaly_direction/normal`
Δ mean: -0.1328, CI=[-0.1680, -0.0960], p_BH=2.043e-10, d=-0.570 (medium)
有意改善: 6件, 有意悪化: 0件
→ 改善

## リスク評価
- 悪化条件の有無: なし
- サンプルサイズ警告（n<10）: なし (0件)
- パイロット検証推奨: 不要

## 補足
- 最も有効な条件: pred_span_quartile/Q1 (critical_miss_rate)
- ターゲット改善層: pred_span_quartile/Q1
