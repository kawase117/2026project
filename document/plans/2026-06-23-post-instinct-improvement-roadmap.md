# 改善ロードマップ — 直近Instinct（2026-06-23）からの導出

作成日: 2026-06-23
作成者: Claude (Opus 4.8)
ステータス: プラン（未着手）
出典Instinct: `document/instincts/2026-06-23-*.yaml`（gated-prediction-segment-evaluation, catboost-v2-optimization, threshold-evaluation-and-model-comparison, high-rotation-evaluation-and-machine-bias, v10-boost-scaling-failure ほか）

---

## 0. エグゼクティブサマリー

直近のv6→v10探索は**頭打ち**に達した。新しいモデルvariant（v11, v12…）の作成は推奨しない。
理由: モデル間のlift差は誤差レベル（2F lift_t3500 = 1.234/1.238/1.258）で、かつ**その差が本物か判定する手段が存在しない**。
レバレッジは「新モデル」ではなく「①有意性検定 ②評価指標修正 ③運用堅牢化」にある。

---

## 1. 現状診断（Instinct集約）

### 1-1. モデル探索の飽和
- v6a / v9b / v9c の 2F lift_t3500 = 1.234 / 1.238 / 1.258 — **差は誤差レベル、統計的有意性は未検証**
- v8（動的セグメントウェイト）/ v10a-e（曜日×角番ブースト）は**全スケールでv6aに劣後**
- `scale→0`で単調収束 ＝ 施策そのものが無効（[boost-scale-monotonic-convergence-diagnostic]）
- **統計的有意（q=1e-13）≠予測有効**（[v10-dow-kakuban-boost-monotonic-failure]）
- **クロスセグメントスケール歪みは繰り返し発生する構造的問題**（[cross-segment-scale-distortion-recurring-pattern]）

### 1-2. 評価フレームワークの欠陥（真のボトルネック）
- `payout_rate` は低回転台で極端に歪む実装のまま
  （`ml/experiments/walkforward_scoring/walk_forward_engine.py:186`、`(games*3+diff)/(games*3)` の台別meanで確認済み）
  → 加重平均 `sum(coins_out)/sum(coins_in)` は**未実装**
- 高回転捕捉liftが全モデル1.0未満 ＝ 差枚スコアリングの構造的限界
- **機種別当日平均からの相対回転数**が最良シグナルと結論されたが**未実装**（[games-relative-to-machine-avg-best-signal]）
- セグメント別vs_otherの単純平均は配分0モデルを不当評価（[vs-other-metric-segment-allocation-bias]）

### 1-3. 運用設計（収束済み）
- 3モデル独立運用、**Consensus/Borda統合は価値破壊につき不使用**で確定（[three-model-independent-operation-design]）
- ゲートの単一セグメント閉じ込めは危険（6/21: vs=-591）→ NOGATEフォールバック＋最低2セグメント保証（[gate-nogate-fallback-reveals-segment-ranking-quality]）
- イベント日=v6aの2F最優先 / 非イベント日=v9bバランス参考 / v9c=Top50 in-outフィルタ（内部順位は無視）

---

## 2. やってはいけないこと（Instinct由来の明示的禁止事項）

1. **composite内へのセグメント固有ブースト** — v8/v10で2回失敗。c1への直接乗数は最も危険。
2. **Borda/Consensus統合** — 6/21:-514, 6/22:-419と一貫悪化。
3. **残差有意性のスコアリングファクター化** — 有意でもliftは下がる。定性的判断材料に留める。
4. セグメント固有施策を入れる場合は、必ず (a) blendでグローバル混合、(b) percentile変換後統合、(c) Top50選抜後リランキング限定 のいずれかに制限する。

---

## 3. 優先トラック

| 優先 | トラック | 目的 | 工数 | 状態 |
|---|---|---|---|---|
| **A** | 統計的有意性検定 | v6a/v9b/v9cの優劣をpaired bootstrapで確定 | 小 | 未着手 |
| **B** | 評価指標修正 | 加重payout + 機種別相対回転数 | 中 | 未着手 |
| **C** | ゲート運用堅牢化 | NOGATEフォールバック+min2セグメント | 小 | 未着手 |
| **D** | セグメント別法則の活用 | フィルタ/リランキング限定 | 中 | 未着手（A/B完了後） |

### Track A — 統計的有意性検定
- 対象: `walk_forward_engine` の日次セグメント別 vs_other（28日〜256日）
- 手法: 日次差分の paired bootstrap（B=10,000）で v6a−v9c 等の95%CI
- 出力: モデルペア×セグメント×（イベント/非イベント）の差の有意性マトリクス
- ゴール: 「v9cに絞るべきか」「どの条件で有意差があるか」に定量回答
- 注意: 既存の `ml/last_digit/compute_4day_bootstrap.py` のbootstrap実装が流用可能か先に確認

### Track B — 評価指標の二本立て修正
1. `payout_rate` を加重平均化: `sum(coins_out)/sum(coins_in)`（台別meanを廃止）
   - `coins_in = games_normalized*3`, `coins_out = games_normalized*3 + diff_coins_normalized`
   - 対象: `walk_forward_engine.py:186`, 227, 255 の集約
2. 機種別相対回転数の追加: `games / machine_day_avg_games`
   - A型: 日/セグメント単位の集計シグナル（[atype-high-games-is-hall-level-signal]）
   - N型: 台単位の相対回転数（新台・人気台バイアスを差し引く、[ntype-high-rotation-three-factors]）
   - test_dateごとに machine_name別 avg_games を事前計算

### Track C — ゲート運用堅牢化
- `ml/experiments/walkforward_scoring/predict_gated.py`（前セッションで着手済み）
- NOGATEフォールバックを並行出力、active判定が1セグメントなら全714台対象に切替
- 「active≧2セグメント」を安全基準として明示
- ゴール: 6/21の単一セグメント閉じ込め（vs=-591 → NOGATE +35）の再発防止

---

## 4. 推奨着手順

A（有意性検定）→ B（評価指標）→ C（ゲート）→ D（セグメント法則）

理由: A・Bは「すべてのモデル比較の土台」。土台が歪んだままTrack C/Dを進めても評価が信用できない。
特にAは最小工数で「これ以上variantを増やす価値があるか」の意思決定根拠を与える。

---

## 5. 関連ファイル

- `ml/experiments/walkforward_scoring/walk_forward_engine.py` — 評価エンジン（payout_rate, THRESHOLD_CUTS）
- `ml/experiments/walkforward_scoring/scoring_model.py` — v6a/v9b/v9c定義、seg_weight（L751-757）
- `ml/experiments/walkforward_scoring/predict_gated.py` — ゲート付き予測（Track C）
- `ml/last_digit/compute_4day_bootstrap.py` — bootstrap実装の流用候補（Track A）
- `document/instincts/2026-06-23-*.yaml` — 本プランの全出典
