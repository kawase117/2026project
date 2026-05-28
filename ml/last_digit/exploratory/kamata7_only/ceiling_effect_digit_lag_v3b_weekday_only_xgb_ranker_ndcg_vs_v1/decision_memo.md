# 評価サマリ: digit_lag_v2r_current vs digit_lag_v1
## 結論
条件付き採用

## 全体スナップショット
- BH有意改善: 11件
- BH有意悪化: 0件
- 平均Cohen's d: 0.313
- 最大改善: pred_span_quartile/Q1 (hit_at_2, d=1.056)
- 最大悪化: なし
- current pairs: 432 (days=144)
- baseline overlap: 432 pairs

## メトリクス別評価
### hit_at_2
代表条件: `anomaly_direction/normal`
Δ mean: +0.1280, CI=[+0.0960, +0.1627], p_BH=4.2e-10, d=0.510 (medium)
有意改善: 6件, 有意悪化: 0件
→ 改善

### loss_value
代表条件: `anomaly_direction/normal`
Δ mean: -1103.2000, CI=[-1645.4133, -588.5333], p_BH=0.000183, d=-0.276 (small)
有意改善: 5件, 有意悪化: 0件
→ 改善

### rank2_rescue_on_miss1
代表条件: `anomaly_direction/normal`
Δ mean: +0.3183, CI=[+0.0508, +0.5684], p_BH=0.05266, d=0.677 (medium)
有意改善: 0件, 有意悪化: 0件
→ 不変

## リスク評価
- 悪化条件の有無: なし
- サンプルサイズ警告（n<10）: あり (12件)
- パイロット検証推奨: 推奨

## 補足
- 最も有効な条件: pred_span_quartile/Q1 (hit_at_2)
- ターゲット改善層: pred_span_quartile/Q1
