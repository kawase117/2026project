# 評価サマリ: digit_lag_v2r_current vs digit_lag_v1
## 結論
条件付き採用

## 全体スナップショット
- BH有意改善: 13件
- BH有意悪化: 0件
- 平均Cohen's d: 0.397
- 最大改善: weekday/Saturday (rank2_rescue_on_miss1, d=1.742)
- 最大悪化: なし
- current pairs: 432 (days=144)
- baseline overlap: 432 pairs

## メトリクス別評価
### hit_at_2
代表条件: `anomaly_direction/normal`
Δ mean: +0.1253, CI=[+0.0933, +0.1600], p_BH=7.56e-10, d=0.495 (small)
有意改善: 8件, 有意悪化: 0件
→ 改善

### loss_value
代表条件: `anomaly_direction/normal`
Δ mean: -1066.4000, CI=[-1634.1400, -538.6267], p_BH=0.0001741, d=-0.246 (small)
有意改善: 2件, 有意悪化: 0件
→ 改善

### rank2_rescue_on_miss1
代表条件: `anomaly_direction/normal`
Δ mean: +0.3775, CI=[+0.1277, +0.6021], p_BH=0.01787, d=0.809 (large)
有意改善: 3件, 有意悪化: 0件
→ 改善

## リスク評価
- 悪化条件の有無: なし
- サンプルサイズ警告（n<10）: あり (13件)
- パイロット検証推奨: 推奨

## 補足
- 最も有効な条件: weekday/Saturday (rank2_rescue_on_miss1)
- ターゲット改善層: weekday/Saturday
