# 改善ロードマップ — 直近Instinct（2026-06-23）からの導出

作成日: 2026-06-23
更新日: 2026-06-26（Track A0→B→A1→C 全完了。V12b正式推奨確定）
作成者: Claude (Opus 4.8)
ステータス: 全Track（A0/B/A1/C/D）完了
出典Instinct: `document/instincts/2026-06-23-*.yaml`（gated-prediction-segment-evaluation, catboost-v2-optimization, threshold-evaluation-and-model-comparison, high-rotation-evaluation-and-machine-bias, v10-boost-scaling-failure ほか）

---

## 0. エグゼクティブサマリー

直近のv6→v10探索は**頭打ち**に達した — この診断はV11/V12探索でも裏付けられた。
ただし**V12b（debut_multiplier, base, scale=0.5）はV11に対し統計的に有意な改善**を示し、正式推奨バリアントとして確定した（Track A1検定結果）。

レバレッジは「新モデル」ではなく「①有意性検定 ②評価指標修正 ③運用堅牢化」にある — この方針は正しかった。
Track A0→B→A1→Cの順に完了し、評価基盤が整った状態でTrack Dに進める。

---

## 1. 現状診断（Instinct集約）

### 1-1. モデル探索の飽和
- v6a / v9b / v9c の **2Fセグメント限定** lift_t3500 = 1.234 / 1.238 / 1.258 — **差は誤差レベル、統計的有意性は未検証**
  - 注意: 全体summaryではv9cのlift_t3500≈0.960（ランキング崩壊により）。上記の比較は2F限定でのみ成立する
- v8（動的セグメントウェイト）/ v10a-e（曜日×角番ブースト）は**全スケールでv6aに劣後**
- `scale→0`で単調収束 ＝ 施策そのものが無効（[boost-scale-monotonic-convergence-diagnostic]）
- **統計的有意（q=1e-13）≠予測有効**（[v10-dow-kakuban-boost-monotonic-failure]）
- **クロスセグメントスケール歪みは繰り返し発生する構造的問題**（[cross-segment-scale-distortion-recurring-pattern]）

### 1-2. 評価フレームワークの欠陥 → **Track Bで修正済み**
- ~~`payout_rate` は低回転台で極端に歪む実装のまま~~ → **加重平均 `sum(coins_out)/sum(coins_in)` に修正済み**（2026-06-26）
- 高回転捕捉liftが全モデル1.0未満 ＝ 差枚スコアリングの構造的限界
- ~~**機種別当日平均からの相対回転数**が最良シグナルと結論されたが**未実装**~~ → **`games_relative` として実装済み**（diagnostic指標。Spearman rho=+0.143だがcomposite組み込みには不安定）
- セグメント別vs_otherの単純平均は配分0モデルを不当評価（[vs-other-metric-segment-allocation-bias]）

### 1-3. 運用設計（収束済み）
- 3モデル独立運用、**Consensus/Borda統合は価値破壊につき不使用**で確定（[three-model-independent-operation-design]）
- ゲートの単一セグメント閉じ込めは危険（6/21: vs=-591）→ NOGATEフォールバック＋最低2セグメント保証（[gate-nogate-fallback-reveals-segment-ranking-quality]）
- イベント日=v6aの2F最優先 / 非イベント日=v9bバランス参考 / v9c=Top50 in-outフィルタ（内部順位は無視）

---

## 2. やってはいけないこと（Instinct由来の明示的禁止事項）

1. **composite内へのセグメント固有ブースト** — v8/v10で2回失敗。c1への直接乗数は最も危険。
2. **Borda/Consensus統合** — 6/21:-514, 6/22:-419と一貫悪化。`predict_gated.py:124` の `_build_consensus_table` と `:257` のレポート出力は現存するが、意思決定には使用しない。将来的に削除または「参考出力・非推奨」注釈付きに変更する。
3. **残差有意性のスコアリングファクター化** — 有意でもliftは下がる。定性的判断材料に留める。
4. セグメント固有施策を入れる場合は、必ず (a) blendでグローバル混合、(b) percentile変換後統合、(c) Top50選抜後リランキング限定 のいずれかに制限する。

---

## 3. 優先トラック

| 優先 | トラック | 目的 | 工数 | 状態 |
|---|---|---|---|---|
| **A0** | 統計的有意性検定（暫定） | 現行KPIでpaired bootstrap暫定CI | 小 | **✅ 完了** |
| **B** | 評価指標修正 | 加重payout + 機種別相対回転数 | 中 | **✅ 完了**（2026-06-26） |
| **A1** | 統計的有意性検定（確定） | 修正KPIで再bootstrap → 最終判断 | 小 | **✅ 完了**（2026-06-26） |
| **C** | ゲート運用堅牢化 | NOGATEフォールバック+min2セグメント | 小 | **✅ 完了**（2026-06-26） |
| **D** | セグメント別法則の活用 | フィルタ/リランキング限定 | 中 | **✅ 完了**（2026-06-26） |

### Track A0 — 統計的有意性検定（暫定）【実装済み】
- 実装: `ml/experiments/walkforward_scoring/significance_test.py`（2026-06-26作成）
- 手法: paired bootstrap（IID/block自動切替）+ Wilcoxon符号順位 + 符号検定 + LOO感度 + BH補正
- 出力: モデルペア×セグメント×（イベント/非イベント）の差の有意性マトリクス + vs Random実用性判定
- **制約**: 現行KPI（歪んだpayout_rate、expected逆算）での暫定結果。**A0の結果でモデルの最終選択をしてはいけない**。Track B完了後にA1で再検定し、そこで初めて結論を出す。

### Track A1 — 統計的有意性検定（確定）【✅ 完了 2026-06-26】
- Track B修正後に `significance_test.py` を再実行（V11 vs V12b、baseline=V11）
- **結論**: payout_rate修正はモデル比較結論に影響しなかった（avg_diff_vs_other, hit_t/lift_tは不変）
- payout_rate差の検定を追加: 全セグメントで ±0.3% 以内（非有意）
- **V12b正式推奨確定**: 非イベント日で2F_R_N(+44, p<0.05), 2F_L_N(+18, p<0.05), 3F_L_N(+10, p<0.05)が有意改善
- 最重要: **2F_R_Nが ns→USEFUL に昇格**（V11: p=0.17 → V12b: p=0.002）
- 出力: `results_trackA1/significance_results.csv`, `vs_random_results.csv`
- instinct: `document/instincts/2026-06-26-track-b-a1-evaluation-insights.yaml`

### Track B — 評価指標の二本立て修正【✅ 完了 2026-06-26】
1. `payout_rate` を加重平均化: `sum(coins_out)/sum(coins_in)`（台別meanを廃止）
   - 変更: `walk_forward_engine.py:_summarize_metrics()` L182-190
   - テスト: `test_walkforward_scoring.py::test_summarize_metrics_uses_weighted_payout_rate`
2. 機種別相対回転数 `games_relative` を追加: `games_normalized / machine_name当日平均`
   - 変更: `scoring_model.py:score_day()` L924-929
   - component_analysis / correlation_matrix にも追加（diagnostic指標）
   - 分析結果: Spearman rho=+0.143（100%の日でプラス）、lift@50=1.170だが分散大 → composite組み込み不適
   - テスト: `test_walkforward_scoring.py::test_score_day_adds_games_relative_column`

### Track C — ゲート運用堅牢化【✅ 完了 2026-06-26】
- `predict_gated.py` の `main()` を改修
- **MIN_ACTIVE_SEGMENTS = 2**: active < 2セグメントなら自動的にNOGATEフォールバック
- **NOGATE常時並行出力**: GATED成立時もNOGATEレポート+CSVを常に生成
- フォールバック理由をレポートに明記
- 6/21型の単一セグメント閉じ込め事故は再発しない

---

## 4. 全Track完了

A0 ✅ → B ✅ → A1 ✅ → C ✅ → D ✅

### 成果の全体像
- **V12b（base, scale=0.5）が正式推奨バリアント** — A1検定で2Fセグメント3つが有意改善
- **評価基盤が整った** — 加重payout_rate + games_relative diagnostic + significance_test(payout検定追加)
- **運用安全弁が入った** — ゲートのmin2セグメント保証 + NOGATE常時並行出力
- **Track D（リランキング）は効果なし** — ルックアヘッド除去後、全手法で有意差なし

### 最終運用パイプライン
```
V12b composite → Top50 選抜（リランキングなし）
                    ↓
    predict_gated.py（--rerank で実験的にリランキング有効化可）
```

### Track D — セグメント別法則の活用【✅ 完了（効果なし判定） 2026-06-26】
- 3手法比較（52日サンプル）: seg_percentile(+115) / games_relative(+30) / hist_diff(-15)
  - **ただしseg_percentileの+115はルックアヘッド（当日diff実績をstrength_weightに使用）による偽陽性**
- ルックアヘッド除去後の再検証（260日全期間、方法B: composite平均 / 方法C: train diff平均）:
  - 全pool_n (60/70/80/90/100) で Wilcoxon p > 0.39
  - **リランキングに実効果なし**
- `predict_gated.py` のリランキングはデフォルト無効に変更（`--rerank` で明示的に有効化可）
- **教訓**: ルックアヘッドチェックは検証の必須ステップ。別実装による再現で発見できた
- instinct: `document/instincts/2026-06-26-track-d-seg-percentile-reranking-insights.yaml`

---

## 5. 関連ファイル

- `ml/experiments/walkforward_scoring/walk_forward_engine.py` — 評価エンジン（加重payout_rate, games_relative, THRESHOLD_CUTS）
- `ml/experiments/walkforward_scoring/significance_test.py` — paired bootstrap + Wilcoxon + 符号検定 + LOO + BH補正 + vs Random + **payout_rate検定**
- `ml/experiments/walkforward_scoring/scoring_model.py` — v1-v12d定義、games_relative算出（L924-929）
- `ml/experiments/walkforward_scoring/predict_gated.py` — ゲート付き予測（**Track C完了: min2セグメント + NOGATE並行出力**）
- `ml/experiments/walkforward_scoring/results_trackA1/` — Track A1検定結果
- `document/instincts/2026-06-23-*.yaml` — 本プランの出典（A0まで）
- `document/instincts/2026-06-26-track-b-a1-evaluation-insights.yaml` — Track B/A1/games_relative知見
- `document/plans/2026-06-23-significance-test-unit-and-quantity-spec.md` — Track A の設計仕様
