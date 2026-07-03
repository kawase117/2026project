---
name: ml-hyperparameter-guide
description: パチンコMLのハイパーパラメータ選択・閾値最適化・キャリブレーション戦略を自動ガイドするスキル。
evolved_from:
  - ece-calibration-importance
  - threshold-optimization-precision-recall-tradeoff
  - probability-distribution-analysis-before-threshold
  - ece-metric-for-imbalanced
  - baseline-model-saturation
  - lambda-hyperparameter-opposite-overfitting
  - catboost-gpu-model-params
confidence: 0.91
---

# ML Hyperparameter Guide Skill

## トリガー
- XGBoost/CatBoostのハイパーパラメータをチューニングするとき
- モデルの信頼度閾値（confidence threshold）を設定するとき
- チューニングが AUC +1% 未満の改善しかしないとき
- `combined_lambda` などの正則化パラメータを選ぶとき
- GPU学習パラメータを設定するとき

## ハイパーパラメータ選択ガイド

### 1. 学習打ち切り判断
```
ハイパーパラメータチューニングで AUC 改善 < 1% → 飽和状態と判断。
次の行動:
  A. 特徴量設計に戻る（特徴量が不十分）
  B. 問題設定を変更する（ターゲットの再定義）
  C. セグメント分割を検討する
```

### 2. CatBoostRanker GPU 設定
```python
CatBoostRanker(
    loss_function='PairLogit',
    task_type='GPU',
    devices='0',
    iterations=500,
    learning_rate=0.05,
    depth=6,
    l2_leaf_reg=3.0,
    random_seed=42,
    verbose=False
)
```

### 3. キャリブレーション（ECE）
```
クラス不均衡（minority < 10%）時:
  → scale_pos_weight よりキャリブレーションが有効
  → 手順:
      1. モデルを通常訓練
      2. 検証セットで isotonic / Platt scaling を適用
      3. ECE で改善を確認

ECEの目標値:
  → ECE < 0.05 を目標
  → 0.05-0.10: 許容範囲
  → 0.10超: キャリブレーション必要
```

### 4. 閾値設定（Precision-Recall トレードオフ）
```
閾値を設定する前に確率分布を必ず確認する。

閾値 T の選択基準:
  - 高精度重視（false positive を避けたい）:
      T = 上位10-15%点のスコア値
  - カバレッジ重視（多くの候補を取りたい）:
      T = 上位30-40%点のスコア値

daily top-K の場合は固定閾値不要（毎日スコア上位K件を選ぶ）。
```

### 5. `combined_lambda` の方向性
```
combined_lambda（LTRの正則化強度）がtuning/holdoutで反対方向を示す場合
  → オーバーフィッティングの証拠
  → holdout側の lambda を採用し、訓練をより保守的に
```

## 進化の背景
13件のインスティンクトから抽出。
ml-hyperparameter-tuning(12) + ml-hyperparameter-selection(1)。
