# 有意性検定の「単位」と「量」設計仕様

作成日: 2026-06-23
作成者: Claude (Opus 4.8)
ステータス: 設計仕様（実装前）
親プラン: `document/plans/2026-06-23-post-instinct-improvement-roadmap.md`（Track A）
目的: v6a/v9b/v9c の優劣検定で **何を1標本とし（単位）、何の差を検定するか（量）** を確定する。手法選択の前に、この2点を誤ると全結論が無効になる。

---

## 0. 結論サマリー（先に決定事項）

| 論点 | 決定 |
|---|---|
| **リサンプリング単位** | `test_date`（日）。台ではない。 |
| **ペアリングキー** | `(segment, test_date)`。同一セルで variant をペア比較。 |
| **検定母体** | `segment_daily_results.csv`（既存出力・モデル改変不要） |
| **量：加算系**（avg_diff, avg_diff_vs_other） | 日次差分の平均 → ペアブートストラップ |
| **量：勝敗系**（win） | 日次の勝敗フラグ → 符号/二項検定 |
| **量：比率系**（lift_t*） | **日次liftを平均してはいけない**。プール比 `Σhit/Σexpected` で検定 → 現状 `expected` 列が無く要追加 |
| **検出力の限界** | event=6日サブセットは原則検定不能。定性扱い。 |

---

## 1. 単位（unit of analysis）

### 1-1. なぜ「日」か
- 同一日内の台は独立でない。リピート台が連日出る（[[v9c-model-selects-specific-machines-not-random]]）。台を1標本にすると独立性仮定が崩れ、p値が過小（偽陽性）になる。
- 各日に全variantが同じ台プールをスコアリング → **日単位でモデルがペア**。ペア化で「当たり日/外れ日」の共通変動が相殺され検出力が上がる。
- よってブートストラップ/並べ替えで**入れ替える対象は日**（台ではない）。

### 1-2. ペアリングキー = `(segment, test_date)`
- セグメントごとに店の法則が異なる（[[segment-ranking-quality-varies-by-floor]]）ため、検定はセグメント内で閉じる。
- 同一 `(segment, test_date)` 行で v6a と v9c の指標を引き当て、その差を取る。
- 母体ファイル: `ml/experiments/walkforward_scoring/segment_daily_results.csv`
  - 1行 = 1 `(segment, variant, window, test_date)`
  - `_summarize_metrics` 由来の全指標を保持（avg_diff, avg_diff_vs_other, win_rate, payout_rate, hit_t*, lift_t*, hit@50, lift@50）
  - **重要**: 集計後の `summary` ではなく、この**集計前の日次行**を使う。`_aggregate_daily_results` は `.mean()` で日次分布を捨てるため検定に使えない。

### 1-3. 系列相関のチェック（単位の妥当性検証）
- 連日で同一台が出るため日次差分に自己相関の可能性。
- 実装前に日次差分系列の ACF（lag1-3）を確認。
  - 無相関 → 通常のペアブートストラップ（日を独立リサンプル）でOK
  - 有相関 → moving-block bootstrap（連続日ブロックでリサンプル）に切替

---

## 2. 量（quantity tested）— 指標族ごとに異なる

「何の差を検定するか」は指標の数学的性質で変わる。3族に分けて扱う。

### 2-1. 加算系: avg_diff, avg_diff_vs_other
- 日次値の単純平均が意味を持つ（加算的）。
- 検定量 = 日次差分 `d_t = metric(v6a)_t − metric(v9c)_t` の平均。
- 手法: ペアブートストラップで `mean(d_t)` の95%CI ＋ Wilcoxon符号順位（外れ値頑健）。
- **注意**: あなたのデータは単一日依存が強い（2F_L_N std=3003 はDD07=+12,920、3F_L_NはDD28=+6,126が支配）。
  → 平均ベースは1日に支配されるため **leave-one-day-out 感度を必須併用**。1日抜きで有意性が消える差は本物でない。

### 2-2. 勝敗系: win（その日 v6a が v9c に勝ったか）
- 最も頑健・解釈容易。外れ値の大きさに影響されない（勝敗の0/1のみ）。
- 検定量 = N日中の勝利日数。
- 手法: 符号検定 / 二項検定（H0: p=0.5）。
- Instinctの勝率（2F_R_N 61%, 3F_L_N 44%）を「50%と区別できるか」に正式変換できる。**見出し指標はこれ**。

### 2-3. 比率系: lift_t2500/3500/4500 ← 最も注意
- **日次liftを平均してはいけない**。`lift = hit/expected` の比率を日次で出して平均するのは「比の平均 ≠ 平均の比」で統計的に誤り。
  - 現状 `_aggregate_daily_results` および `segment_daily` は日次liftの `.mean()` を取っている。これは検定用途には不適。
- 正しい量 = リサンプルした日集合で**プール**した `Σ hit_t / Σ expected_t`。
- 問題: `segment_daily_results.csv` には `hit_t`（カウント）と `lift_t`（既に割り算済み）はあるが **`expected_t` が無い**。
  - `expected = hit_t / lift_t` で逆算可能だが、hit_t=0 の日は lift_t=0 となり復元不能（ゼロ除算）。
  - → **最小改修**: `_summarize_metrics` に `expected_t{threshold}` と `top_n`, `n_threshold`, `total_n` を出力追加（`walk_forward_engine.py:197-202` 付近）。1行追加レベル。
- 手法: 日をブートストラップ → 各リサンプルで `Σhit/Σexpected` を再計算 → v6a版とv9c版の比の差の分布で検定。

---

## 3. 多重比較と検出力（量を決めた後の必須補正）

- **多重比較**: 3モデル × 6セグメント × {event, non_event, all} = 数十検定。
  → セグメント横断で集約する際は Benjamini-Hochberg（FDR）補正。既存のq値運用と整合。
- **検出力**: event日はわずか6日。サブセット検定はほぼ何も有意化しない。
  → 「イベント日はv6aが強い」はサンプル6で**確定不能**。定性判断に留めると明記。
- **効果量 vs p値**: 256日では lift差0.02でも有意化し得るが運用無意味。
  → p値単独で判断しない。**差のCI下限が「行動する価値があるか」**を最終基準とする。これがv11以降を作るべきかの意思決定軸。

---

## 4. 実装ステップ（このTrackのスコープ）

1. **母体確認**: `segment_daily_results.csv` を最新の walk-forward 実行で生成（または既存を使用）。列・日数・セグメント網羅を点検。
2. **系列相関チェック**: 日次差分のACF(lag1-3)。block bootstrap要否を判定。
3. **加算系・勝敗系の検定**: avg_diff_vs_other（ペアブートストラップ+Wilcoxon）、win（符号検定）。`expected` 不要なので即着手可能。
4. **比率系のための最小改修**: `_summarize_metrics` に `expected_t*`, `top_n`, `total_n` 出力追加 → 再実行 → プール比ブートストラップ。
5. **多重比較補正＋出力**: モデルペア×セグメント×条件の (差・95%CI・p値・q値・勝率) マトリクス。
6. 既存 `ml/last_digit/compute_4day_bootstrap.py` のブートストラップ実装を 3/4 のベースに流用可能か先に確認。

---

## 5. 未決事項（実装前に確認したい点）

- **window軸の扱い**: `segment_daily_results.csv` は `window` 次元を持つ。検定は単一windowに固定するか、windowもペアリングキーに含めるか。
- **payout_rate**: 現状実装が歪む（[[payout-rate-distortion-by-low-games]]）ため検定対象から除外。Track Bの加重payout修正後に再検討。
- **比率系の改修を待つか**: 加算系・勝敗系だけで意思決定に足りる可能性が高い。lift系プール検定は「加算系で結論が出なかった場合の追加精度」と位置づけ、改修コストと相談。

---

## 6. 関連ファイル

- `ml/experiments/walkforward_scoring/walk_forward_engine.py` — `_summarize_metrics`(L156-203), `segment_daily`生成(L573-582), `expected`算出(L194,200)
- `ml/experiments/walkforward_scoring/results*/segment_daily_results.csv` — 検定母体
- `ml/last_digit/compute_4day_bootstrap.py` — ブートストラップ流用候補
- `document/instincts/2026-06-23-threshold-evaluation-and-model-comparison-insights.yaml` — 指標族の背景
