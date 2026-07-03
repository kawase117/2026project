---
name: pachinko-session-recommend
description: ML予測スコア・ゾロ目補正・曜日パターンを統合して当日の台選択推薦を生成する。当日の推薦リスト作成時・実運用の台選択時に使用。
evolved_from:
  - combined-prediction-zorome-strategy-definition
  - combined-vs-simple-simulation-hypothesis
  - zorome-weekday-pattern-is-actionable
  - rank2-not-rank3-equivalent
  - rank1-chaaichi-strategy-effective
  - zorome-machine-efficacy-patterns
  - weekday-dependent-zorome-strategy-variation
  - combined-dynamic-weight-by-expert-reliability
  - zorome-correction-strict-three-conditions
  - segment-specific-top3-comparison
  - tail-vs-zorome-machine-separate-evaluation
  - 3fn-highest-reliability-segment-for-prediction
  - zorome-high-correction-instability
  - hit3-outperforms-hit2-in-live-evaluation
  - event-day-zorome-priority-rule
confidence: 0.88
---

# pachinko-session-recommend

当日のホールデータとMLスコアを統合し、台選択推薦リストを生成する。

## 入力データ
```python
inputs = {
    "today": "YYYYMMDD",
    "hall": "<ホール名>",
    "ltr_scores": "latest_test_top3.csv",
    "is_zorome_day": True or False,
    "weekday": "月〜日",
}
```

## 実行ステップ

### Step 1: ML スコアの読み込み（エキスパート別動的ウェイト）
```
latest_test_top3.csv から当日の推薦を取得。

【最重要】3F_N を最高優先セグメントとして扱う:
  3日間実績: 3F_N Hit@2=50%、他3セグメントはすべて17%（ランダム水準）。
  → 3F_Nとの合意が取れた末尾のみを「強推薦」とする。
  → 3F_Nのみで推薦できる末尾は最優先候補。

各 expert のウェイト（等重みは禁止）:
  → 事前に top1ミス率・直近精度を確認してウェイトを調整する
  → top1ミス率 > 20% の expert はウェイト 0.5倍以下

基本ウェイト（実績ベース・毎月更新）:
  - 3F_N: 0.45（最高信頼性・実績ベース）
  - 3F_A: 0.25（安定しているが相関低め）
  - 2F_N: 0.20（ランダム水準）
  - 2F_A: 0.10（台数少なく不安定）

信頼度の重み付け（rank2 は rank3 と同等ではない）:
  rank1: 1.0 / rank2: 0.7 / rank3: 0.4

【実運用ではTop3を参照する】:
  モデルはhit@2で設計されているが実績ではhit@3の方が有効（38.9% vs 25.0%）。
  1・2位の予測を絶対視せず、3位も同等候補として扱う。
```

### Step 2: ゾロ目補正 ── 3条件チェック（必須）
```
XX台を推薦するには以下3条件を全て満たすこと:
  1. correction > +150（同末尾非ゾロ目台との差が閾値以上）
  2. 直近サンプル数 >= 10日（補正値が安定している）
  3. 複数expertが同じ末尾に合意している

1条件でも欠ける場合は「末尾推奨・XX台にはこだわらない」と明記する。

曜日別ゾロ目強度:
  土・日: 強め / 木・金: 中程度 / 月〜水: 控えめ
```

### Step 3: 最終推薦リスト生成
```
優先度1（ML rank1 + ゾロ目3条件クリア）:
  → expert別 rank1 推薦末尾 + ゾロ目台（3条件満たす場合のみ）

優先度2（ML rank2 or 条件不足のゾロ目台）:
  → rank2推薦 / ゾロ目が条件不足の場合は末尾推薦のみ

見送り:
  → ML rank3以下 かつ ゾロ目3条件未達
```

### Step 4: 評価レポートの出力（2026-05-28 追加）
```
推薦後の振り返りで必ず分離して報告する:
  1. tail hit@3: セグメント別末尾合計差枚によるTop3一致度
  2. XX台実績: 当日のゾロ目台（XX番台）の差枚を個別記載
  3. 「末尾当たり・XX台外れ」パターンを明示的に検出

末尾精度 ≠ ゾロ目台精度（別指標で報告）
```

### Step 5: シミュレーション比較（任意）
```
combined（ML + ゾロ目）と simple（ML のみ）の期待値比較。
combined_advantage > 10% のときのみ combined が有意。
```

## 注意事項
- ゾロ目3条件を満たさない場合はXX台を推薦しない（過去の失敗例あり）
- 等重みcombinedは禁止（信頼度の低いexpertが予測を歪める）
- n < 5 のパターンは信頼度を下げて表示
- 【[狙い]判定でも当日外れは頻繁にある】高補正値(+200超)は長期統計。単日には適用できない
- 【単日の当たり外れでモデルを評価しない】評価は月次(20日以上)の移動平均で行う
- 3F_Aの予測は信頼度低め。3F_Aのみの強推薦は避ける

## 進化の背景
19件のインスティンクトから抽出（2026-05-29 更新）。
operational-strategy(14) + prediction-strategy(4) + prediction-evaluation(11)から抽出。
