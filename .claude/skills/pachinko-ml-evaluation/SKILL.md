---
name: pachinko-ml-evaluation
description: LTRモデルの評価設計・指標選択・walk-forward設定を自動チェックするスキル。評価コードを書く前に適用。
evolved_from:
  - ece-metric-for-imbalanced
  - evaluation-step-size-matters
  - min-train-days-is-threshold-not-window
  - multitier-evaluation-metrics-standard
  - rank1-miss-quality-decomposition
  - rolling-window-masks-lows-in-declining-store
  - small-sample-pattern-skepticism
  - low-accuracy-expert-as-confidence-signal
  - daily-topk-beats-fixed-threshold-low-baserate
  - hit-at-2-is-soft-metric-rank1-exact-is-operational
  - group-total-diff-is-not-per-machine
  - test-period-standard-90d
  - evaluation-window-change-no-immediate-top3-effect
confidence: 0.92
---

# Pachinko ML Evaluation Skill

## トリガー
- walk-forward評価のパラメータを設定するとき
- 評価指標（AUC, ECE, hit@K等）を選択するとき
- 不均衡データで評価しているとき
- モデルのミスパターンを分析するとき
- LTRの結果KPIを報告・比較するとき

## 評価設計チェックリスト

### 1. walk-forward パラメータ
```
n_eval_days >= 10 を必ず確保する。
（10未満だとステップ間のノイズが支配的になる）

--min-train-days の解釈:
  → 「訓練窓の幅」ではなく「訓練開始に必要な最低サンプル数の閾値」
  → min-train-days=90 の場合、90日以上のデータが蓄積された時点から訓練開始
  → 窓幅(window_size)とは独立したパラメータ
```

### 2. 不均衡データの評価指標
```
base_rate < 10%:
  → ECE（Expected Calibration Error）を第一指標にする
  → AUCは使えるが、補助指標として扱う
  → Accuracy/Precision/Recall は閾値に依存するため注意

base_rate < 5%:
  → daily top-K 評価（fixed threshold より有効）
  → 毎日 top-K の推薦が何件正解したか を集計する
```

### 3. LTR 標準評価指標セット（多層評価）
```
必須指標:
  - hit@1（厳密指標・運用上の本命）
  - hit@2（soft指標・余裕を持った評価）
  - NDCG（ランキング全体の質）
  - lift@1 = hit@1 / base_rate（ランダム比改善）

報告時の注意:
  - group_total_diff はグループ（expert）合計であり、台あたり差枚ではない
  - hit@2 はソフト指標。hit@1（rank1の完全一致）が運用上の本命
```

### 4. ミスパターン分析
```
モデルがrank1を外した場合の分解:
  A. rank2に推薦 → 惜しいミス（許容）
  B. rank3-5に推薦 → 中程度のミス
  C. rank6以下に推薦 → 致命的ミス

分解を実施してから改善施策を検討する。
```

### 5. 小サンプル警戒
```
n < 5 のパターンから行動パターンを主張しない。
異常検知や末尾別分析で「◯件しかない」場合は結論を留保する。
```

### 6. 低精度エキスパートの扱い
```
特定フロアや機種タイプで hit@2 が他より有意に低い場合
  → そのエキスパートの予測を低信頼度シグナルとして使う
  → 高精度エキスパートとの組み合わせで信頼度スコアを調整する
```

### 7. テスト期間の標準（2026-05-28 追加）
```
主評価指標: recent_90d_standard（過去90日）を使用する。
  → 全期間より expert 間バランスが最良（2F_A/3F_A等の振れ幅が小さい）
  → expert別F1比較: 90日が full/60日に対してバランス最良

60日（recent_60d）: ドリフト検知用補助指標として併用する。
全期間: 回帰監視用に保持するが主判断には使わない。

評価ウィンドウ変更の注意:
  → ウィンドウ変更はモデル選択基準を変えるだけ。
  → 選ばれたモデルが同じなら予測Top3も変わらない（即日効果を期待しない）。
  → 効果は翌日以降の予測と実績の継続突き合わせで確認する。
```

## 進化の背景
14件のインスティンクトから抽出（2026-05-28 更新）。
ml-evaluation(8) + ml-evaluation-design(3) + ltr-evaluation(2) + ml-evaluation-strategy(1)。
