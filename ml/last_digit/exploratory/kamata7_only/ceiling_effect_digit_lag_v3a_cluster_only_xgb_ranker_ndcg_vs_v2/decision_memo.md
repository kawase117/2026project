# 評価サマリ: digit_lag_v2r_current vs digit_lag_v1
## 結論
条件付き採用

## 全体スナップショット
- BH有意改善: 0件
- BH有意悪化: 0件
- 平均Cohen's d: -0.099
- 最大改善: なし
- 最大悪化: なし
- current pairs: 432 (days=144)
- baseline overlap: 432 pairs

## メトリクス別評価
### hit_at_2
代表条件: `anomaly_direction/high_anomaly`
Δ mean: +0.0000, CI=[+0.0000, +0.0000], p_BH=1, d=nan (na)
有意改善: 0件, 有意悪化: 0件
→ 不変

### loss_value
代表条件: `anomaly_direction/high_anomaly`
Δ mean: -1403.0303, CI=[-3921.2121, +103.0303], p_BH=1, d=-0.289 (small)
有意改善: 0件, 有意悪化: 0件
→ 不変

### rank2_rescue_on_miss1
代表条件: `anomaly_direction/normal`
Δ mean: -0.0895, CI=[-0.3500, +0.1684], p_BH=1, d=-0.201 (small)
有意改善: 0件, 有意悪化: 0件
→ 不変

## リスク評価
- 悪化条件の有無: なし
- サンプルサイズ警告（n<10）: あり (15件)
- パイロット検証推奨: 推奨

## 補足
