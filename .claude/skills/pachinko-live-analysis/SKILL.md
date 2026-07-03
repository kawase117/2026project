---
name: pachinko-live-analysis
description: ホール戦略分析・ロケール選択・設定継続仮説・分析落とし穴を体系化したスキル。実運用分析時に自動適用。
evolved_from:
  - hall-holdover-strategy-per-hall-verification
  - hit-candidate-holdover-also-absent
  - few-machine-advantage-rate-vs-count
  - excess-count-vs-hit-candidate-dual-metrics
  - percentile-relative-scoring-solves-fixed-threshold
  - excess-count-detects-strategic-investment
  - hit-candidate-vs-unfired-high-setting-separation
  - unfired-hypothesis-absolute-diff-bias
  - nextday-vs-nextweek-tracking-strategy
  - model-score-priority-over-correction-rules
  - zorome-correction-validation-requires-setting-level
  - 3fa-segment-low-model-correlation
confidence: 0.88
---

# Pachinko Live Analysis Skill

## トリガー
- ホールの翌日継続（holdover）戦略を検証するとき
- 少台数ロケールと多台数ロケールのどちらを選ぶか判断するとき
- 差枚ランキングで特定機種が突出しているとき
- 未消化高設定の翌日改善仮説を検証するとき
- モデルスコアとゾロ目補正が競合するとき

## ホール戦略分析

### 1. 翌日継続（holdover）戦略の検証
```
前日高設定台が翌日も高設定を維持するかどうかはホール固有の戦略。
検証方法:
  1. hit_candidate（前日高設定候補）の翌日差枚を追跡
  2. hit_candidate翌日 vs ランダム台翌日の差枚を比較
  3. 20日以上の蓄積で統計的有意性を確認

重要: 蒲田七では hit_candidate が翌日も hit_candidate でないケースが確認済み。
holdover仮説は「自明の真実」ではなく「要検証の仮説」。
```

### 2. ロケール選択（少台数 vs 多台数）
```
少台数ロケール（2〜5台）の優位:
  - 高設定率が高い場合は確率的優位が大きい
  - 「全台高設定」の可能性も

多台数ロケール（16〜50台）の優位:
  - 絶対的に高差枚の台が出る可能性
  - モデルスコアでの絞り込みが有効

ガイドライン:
  少台数で高設定率 > 50% が期待できる → 少台数優先
  モデルが特定台を強く示す → その台のロケールも候補
```

### 3. 機種別シグナルの2指標
```
1. excess_count: 機種全体で「平均以上差枚」の台数
   → 戦略的高設定投入（複数台まとめて）を検出

2. hit_candidate: 個別台の長期高差枚シグナル
   → 特定台の継続的な高設定を検出

両方使う場合: excess_count で機種を選び、hit_candidate で台を絞る。
```

## 分析の落とし穴

### 4. パーセンタイル正規化（固定閾値問題の解決）
```python
# 機種間で差枚分散が大きく異なる場合、固定閾値はノイズになる
# → 機種内パーセンタイルで相対スコアを計算する
df['score'] = df.groupby('machine_name')['diff_coins_normalized'].rank(pct=True)
```

### 5. 未消化高設定の翌日改善仮説
```
禁止: 絶対差枚値（raw diff_coins）で翌日比較すること
  → 外部要因（全体波形・稼働率）が変わるため不公平比較

正しい評価: 同じ翌日期間の「hit_candidate台 vs ランダム台」の差分で相対評価
```

### 6. 翌日 vs 翌週のトラッキング設計
```
翌日追跡: 継続投入を検出したい場合（dailyで追う）
翌週追跡: 周期的パターンを検出したい場合（曜日固定等）

両方の設計が必要。どちらか一方では見えない挙動がある。
```

### 7. ゾロ目補正精度の検証単位（2026-05-29 追加、prediction-evaluationから移動）
```
セッション結果で補正精度を評価しない（設定レベルと独立した事象）。

正しい検証:
  → N>=20の大量サンプルで「同末尾ゾロ目台 vs 非ゾロ目台の平均差枚比較」
  → または設定開示情報との照合

誤った評価例:
  補正値-149の台 → 実際にマイナス差枚 →「補正が正しかった」← 設定が5/6でもマイナスはあり得る
  設定実態（高設定だった）と差枚結果は独立。補正値の方向性が外れていても差枚がマイナスになる。
```

### 8. 3F_Aの信頼度は低め（2026-05-29 追加、prediction-evaluationから移動）
```
3F_A（ジャグラー・ハナビなどA型3F）は予測相関が特に低い可能性がある。

根拠: 2026-05-29の3F_A = 0/3（完全外れ）
  - A型機は設定差が出にくく差枚ランダム性が大きい
  - 台数207台 → 末尾別集計ノイズが大きい

運用ルール:
  - 3F_Aのみで末尾を強く推奨しない
  - combined予測で3F_Aのウェイトを相対的に低く設定
  - 3F_AのTop3一致率を蓄積して他セグメントと定量比較する
```

## モデルスコア vs ゾロ目補正の優先順位
```
競合した場合 → モデルスコアを優先する。

理由: モデルスコアは長期学習の統計的信号。補正値は単日ノイズが大きい。
例外: ゾロ目補正が+300超 かつ サンプル>=20 かつ 複数expert合意 → 競合可能
```

## 進化の背景
12件のインスティンクトから抽出（新規スキル・2026-05-29、2026-07-04にprediction-evaluationから2件追加移動）。
pachinko-hall-strategy(2) + pachinko-locale-strategy(1) + ml-feature-engineering(3)
+ pachinko-analysis-pitfall(3) + pachinko-analysis-design(1) + others(2)。
平均信頼度: 88%。
