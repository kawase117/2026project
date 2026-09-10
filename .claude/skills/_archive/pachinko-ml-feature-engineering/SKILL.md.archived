---
name: pachinko-ml-feature-engineering
description: パチンコMLの特徴量設計・選択・検証を自動ガイドするスキル。LTRモデルの特徴量追加・削除時に自動適用。
evolved_from:
  - data-binning-for-noisy-features
  - calibrated-beats-rebalancing
  - moving-averages-dominate
  - target-specific-feature-utility
  - multicollinearity-masking-signal
  - hall-digit-lag-complements-entity-level-lag
  - hall-level-rolling-features-mi-zero
  - acf-per-digit-heterogeneous-no-universal-lag
  - cross-expert-agreement-is-random-baseline
  - cross-expert-lag1-performance-signal-null
  - cross-expert-mild-anti-pattern
  - kruskal-posthoc-digit3-outlier
confidence: 0.89
---

# Pachinko ML Feature Engineering Skill

## トリガー
- LTRモデルに新しい特徴量を追加・削除しようとするとき
- 特徴量のMI（相互情報量）を評価しているとき
- 特徴量分布の変動が大きいとき（range > 10x mean）
- ローリング窓幅を決定しようとするとき
- hall-level vs digit-level vs entity-level 特徴量を比較するとき

## チェックリスト（特徴量追加前）

### 1. 階層の確認（必須）
```
Hall-level aggregate（avg_diff_per_machine系）
  → is_top2 LTR に対してMI≈0。削除候補。
  → 「ホール全体の平均」は相対ランク予測に貢献しない。

Digit-level lag（lag7_digit_diff等）
  → MI rank1相当（0.01237）。有効。
  → entity_key単位lag（フロア×末尾）とは別次元の信号。

Entity-level lag（entity_key = "3F_N|7"単位）
  → hall-digit lagと混同しないこと。
```

### 2. Lag窓幅の決定
```
ACF/PACFで末尾別パターンは異質 → 全末尾共通の有意lagは存在しない。
対策: 複数lagを追加してモデルに選ばせる。
推奨: DIGIT_LAGS = [2, 6, 7, 14]（ACF分析に基づく）

実装パターン:
  for lag in DIGIT_LAGS:
      hall_digit_daily[f"lag{lag}_hall_digit_diff"] = (
          hall_digit_daily.groupby("last_digit")["hall_digit_mean_diff"]
          .shift(lag).fillna(0.0)
      )
```

### 3. 移動平均の優先
```
時系列ランク/勝率予測では移動平均が最も効く（moving-averages-dominate）。
roll7, roll14, roll28 を基本セットとして必ず含める。
ただし hall-aggregate のroll は is_top2 で無効（MI=0）なので注意。
```

### 4. 多重共線性チェック
```
カテゴリ特徴量単体で高いEffect sizeを示しても、
組み合わせてAUCが改善しない場合 → 多重共線性疑い。
VIF or 相関行列で確認。
```

### 5. 分布の変動が大きい場合
```
range > 10x mean → ビニング（data-binning-for-noisy-features）。
pd.qcut(df[col], q=10, duplicates='drop') でパーセンタイル分割。
```

### 6. クロスエキスパート特徴量（使用禁止）
```
cross-expert agreement（異なるフロアグループ間の合意）はランダムベースラインと区別不可。
lag=1 での有意信号も実証されていない。
mild anti-pattern が確認されているため、積極採用しない。
```

### 7. クラス不均衡への対処
```
少数クラス < 10% → リバランスよりキャリブレーションが有効。
calibrate_isotonic / Platt scaling を使う。
XGBoost の scale_pos_weight より ECE 改善が大きい。
```

## 進化の背景
38件のインスティンクトから抽出。
ml-feature-engineering(35件) + ltr-feature-engineering(3件)。
