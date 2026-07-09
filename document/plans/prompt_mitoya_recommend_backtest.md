# みとや大森町 推薦スクリプト バックテスト＋重み最適化

## 目的

`eda/mitoya_recommend.py` のスコアリング重みを walk-forward バックテストで検証・最適化する。
現在の重みは hand-tuned で、推薦精度を最大化する値ではない。

## 背景

`eda/mitoya_recommend.py` は Phase 10-11b の検証結果に基づくルールベース推薦。
5セグメント（h_jug, h_nonjug, v_jug, v_nonjug, mixed_805）に分類し、
セグメント × 角番 × イベント日（X_DDS）の3軸でスコアリングする。

### 現在の重みパラメータ（`_score_machine` 関数内）

```python
# h_jug
corner_bonus = {"corner1": 400, "corner2-4": 150, "corner5-9": 30, "corner10+": 0}
xdds_boost = 100
section_rank_bonus = {"641-657": 80, "675-691": 40, "658-674": 10}

# h_nonjug (X_DDS日)
xdds_boost = 200
corner_bonus_xdds = {"corner1": 300, "corner2-4": 200, "corner5-9": 50, "corner10+": 0}
# h_nonjug (非イベント日) corner1 penalty = -100
# DD=24 特殊 boost = 500

# v_jug
xdds_boost = 100
section_rank_bonus = {"723-733": 20, "734-744": 10, "712-722": 5}

# mixed_805 (X_DDS × debut)
debut_xdds_boost = 300
growth_xdds_penalty = -100

# 全セグメント共通
section_baseline_scale = 0.1
```

## 実装タスク

### 1. バックテストエンジン: `eda/mitoya_recommend_backtest.py`

#### データフロー

```
みとや大森町店.db (machine_detailed_results)
  ↓ load_mitoya_frame(join_layout=True) → machine_number で layout 結合
  ↓ add_event_category() → dd, is_xdds_day 等を追加
  ↓ add_debut_phase() → debut_phase を追加
  ↓ section → segment 分類 (SECTION_TO_SEGMENT マッピング)
  ↓ rank_from_aisle → corner_bucket (1, 2-4, 5-9, 10+)
  ↓ games >= 1000 フィルタ
  → 日別にスコアリング → Top-N を推薦 → 実績と比較
```

- `machine_name` は DB の `machine_detailed_results` から取得。座標データとは `machine_number` で結合。
- 日付フォーマットは `YYYYMMDD`（TEXT型）。

#### Walk-forward 分割

- レジーム境界: `2025-07-07`（74台同日機種変更）
- **Window A (pre)**: 2025-01-01 〜 2025-07-06
- **Window B (post)**: 2025-07-07 〜 データ末尾
- 各ウィンドウ内で section_baselines を算出し、テスト日ごとに推薦を生成
- section_baselines はテスト日**以前**のデータのみから算出（未来情報リーク防止）

#### 評価指標

テスト日ごとに以下を計算：

| 指標 | 定義 |
|------|------|
| avg_diff_topN | 推薦 Top-N 台の当日 avg_diff |
| avg_diff_random | v_nonjug 除外後のランダム N 台の当日 avg_diff（100回サンプリングの平均） |
| lift | avg_diff_topN - avg_diff_random |
| hit@K | 推薦 Top-K 台のうち、当日の実績 Top-K に入った台数 (K=3,5,10) |
| win_rate | 推薦 Top-N 台の当日 plus_rate (diff > 0 の割合) |

#### 出力

- `eda/results/mitoya_backtest_daily.csv` - テスト日ごとの結果
  - 列: test_date, dd, is_xdds, window, avg_diff_top10, avg_diff_random, lift, hit@3, hit@5, hit@10, win_rate, n_machines
- `eda/results/mitoya_backtest_summary.csv` - ウィンドウ × event_type の集計
  - 列: window, event_type(all/xdds/non_xdds), avg_lift, avg_hit@3, avg_hit@5, avg_hit@10, avg_win_rate, n_test_days
  - **event_type=all/xdds/non_xdds の3行を必ず各ウィンドウに出力すること**
- `eda/results/mitoya_backtest_report.md` - 人間可読レポート

### 2. 重み最適化: `eda/mitoya_recommend_optimize.py`

#### 最適化対象パラメータ

段階的に最適化する（一度に全パラメータを探索しない）。

**Stage 1: h_jug corner 重み（最も効果量が大きい軸）**
```python
h_jug_corner1 = [200, 300, 400, 500, 600]
h_jug_corner24 = [50, 100, 150, 200, 250]
h_jug_corner59 = [0, 15, 30, 50]
```

**Stage 2: h_nonjug X_DDS × corner 重み**
```python
h_nonjug_xdds = [100, 150, 200, 250, 300]
h_nonjug_corner1_xdds = [150, 200, 300, 400, 500]
h_nonjug_corner1_nonevent_penalty = [-200, -150, -100, -50, 0]
```

**Stage 3: DD=24 特殊 / section_baseline_scale**
```python
dd24_boost = [200, 300, 400, 500, 600, 700]
section_baseline_scale = [0.0, 0.05, 0.1, 0.15, 0.2]
```

#### 最適化方法

- 各 Stage で grid search。目的関数 = **Window A + Window B の平均 lift@10**
- 計算量対策: **コンポーネント列を1回だけ計算し、候補ウェイトごとの合成は線形結合で算出。_score_machine を繰り返し呼ばない**
  - 具体的には: 各台に `feat_h_jug_corner1`(0/1), `feat_h_jug_corner24`(0/1), ... のバイナリ特徴量列を事前計算
  - スコア = weights @ features の行列演算で一括算出
- Stage 1 の最適値を固定 → Stage 2 を探索 → Stage 2 の最適値を固定 → Stage 3
- 最終的に全パラメータを微調整する fine-tuning round を1回追加

#### 出力

- `eda/results/mitoya_optimize_grid.csv` - 全候補の lift@10
  - 列: stage, param_name, param_value, lift@10_A, lift@10_B, lift@10_avg
- `eda/results/mitoya_optimize_best.json` - 最適パラメータセット
- `eda/results/mitoya_optimize_report.md` - 最適化レポート
  - 現行重み vs 最適重みの比較テーブルを含むこと

### 3. テスト: `test/eda/test_mitoya_recommend_backtest.py`

- ダミーデータ（最低20台 × 10日）を使った単体テスト
- テストデータは **YYYYMMDD 形式**で作成すること
- テストデータに**イベント日（DD∈{4,7,14,17,24,27}）と非イベント日を最低1日ずつ含める**こと
- min_actual_machines をパラメータ化し、テスト時はオーバーライド可能にすること
- テストケース:
  1. バックテストエンジンが daily/summary CSV を出力すること
  2. lift が計算されること（NaN でないこと）
  3. v_nonjug の台が推薦に含まれないこと
  4. X_DDS 日は h_nonjug corner1 のスコアが高いこと
  5. 非イベント日は h_nonjug corner1 のスコアが低い（ペナルティ）こと

## 実装制約

### DBデフォルト
`DB_PATH` は `eda/mitoya_prompt_common.py` の定数 `DB_PATH` を import して使うこと。自分で定義しない。

### 共通モジュール活用
以下の関数は `eda/mitoya_prompt_common.py` から import すること:
- `connect_mitoya_db()`, `load_mitoya_frame()`, `add_event_category()`, `add_debut_phase()`
- `X_DDS` (frozenset: {4, 7, 14, 17, 24, 27})
- `MITOYA_ALL_SECTIONS`

### セグメント定義
`eda/mitoya_recommend.py` の `SEGMENT_SECTIONS`, `SECTION_TO_SEGMENT`, `AVOID_SEGMENTS` を import すること。

### テーブル出力
テーブル出力は `to_markdown()` を使わず、自前の簡易 Markdown 生成で行うこと。
`eda/mitoya_prompt_common.py` の `render_markdown_table()` を流用可。

### 空セグメント対策
cross-bin 集計は実データのあるセグメント/日のみを対象とし、空セグメントはスキップする。NaN が出力に混入しないこと。

### 日本語文字列
日本語を含む関数を編集する場合は関数全体を置き換えること（行単位パッチ禁止）。
ファイルエンコーディングは UTF-8（BOMなし）。
print 出力で em dash (U+2014) は使わない（cp932 環境でエラーになる）。ハイフン (-) で代替する。

### A/N 判定
今回の推薦スクリプトでは A/N 判定（jug_flag）を**使わない**。
セグメント分類はセクション番号ベース（`SECTION_TO_SEGMENT` マッピング）で完結する。

## 実行確認

```bash
# バックテスト実行
python -X utf8 eda/mitoya_recommend_backtest.py

# 最適化実行
python -X utf8 eda/mitoya_recommend_optimize.py

# テスト
python -m pytest test/eda/test_mitoya_recommend_backtest.py -v
```

エラーなく CSV + report.md が生成されること。
summary.csv に all/xdds/non_xdds の3行が各ウィンドウに存在すること。
optimize_best.json が有効な JSON であること。

## 成果物チェックリスト

- [ ] `eda/mitoya_recommend_backtest.py` - バックテストエンジン
- [ ] `eda/mitoya_recommend_optimize.py` - 重み最適化
- [ ] `test/eda/test_mitoya_recommend_backtest.py` - テスト
- [ ] `eda/results/mitoya_backtest_daily.csv`
- [ ] `eda/results/mitoya_backtest_summary.csv`
- [ ] `eda/results/mitoya_backtest_report.md`
- [ ] `eda/results/mitoya_optimize_grid.csv`
- [ ] `eda/results/mitoya_optimize_best.json`
- [ ] `eda/results/mitoya_optimize_report.md`
