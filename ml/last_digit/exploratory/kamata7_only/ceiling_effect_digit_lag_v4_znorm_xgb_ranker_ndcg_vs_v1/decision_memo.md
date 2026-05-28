# 評価サマリ: digit_lag_v2r_current vs digit_lag_v1
## 結論
条件付き採用

## 全体スナップショット
- BH有意改善: 14件
- BH有意悪化: 0件
- 平均Cohen's d: 0.375
- 最大改善: anomaly_direction/normal (rank2_rescue_on_miss1, d=1.113)
- 最大悪化: なし
- current pairs: 432 (days=144)
- baseline overlap: 432 pairs

## メトリクス別評価
### hit_at_2
代表条件: `anomaly_direction/normal`
Δ mean: +0.1307, CI=[+0.0960, +0.1680], p_BH=2.592e-10, d=0.527 (medium)
有意改善: 6件, 有意悪化: 0件
→ 改善

### loss_value
代表条件: `anomaly_direction/normal`
Δ mean: -1109.0667, CI=[-1714.8400, -518.3267], p_BH=3.991e-05, d=-0.251 (small)
有意改善: 6件, 有意悪化: 0件
→ 改善

### rank2_rescue_on_miss1
代表条件: `anomaly_direction/normal`
Δ mean: +0.5058, CI=[+0.2691, +0.6976], p_BH=0.002367, d=1.113 (large)
有意改善: 2件, 有意悪化: 0件
→ 改善

## リスク評価
- 悪化条件の有無: なし
- サンプルサイズ警告（n<10）: あり (15件)
- パイロット検証推奨: 推奨

## 補足
- 最も有効な条件: anomaly_direction/normal (rank2_rescue_on_miss1)
- ターゲット改善層: anomaly_direction/normal
