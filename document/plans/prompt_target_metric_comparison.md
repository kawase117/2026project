# Codex プロンプト: ターゲット指標の比較検証

## 背景

現在のスコアリングモデルは「104%超え（二値）」をターゲットに使っている。
しかしキャリブレーション検証で以下が判明した:

1. **104%二値化は情報を大量に捨てている**
   - 103%の台と80%の台が同じ「0」、105%の台と150%の台が同じ「1」になる
   - この情報損失が構造シグナルの検出を妨げている可能性がある

2. **hist_metricが「104%超え率」を経由して機能していること自体が不自然**
   - 「過去90日の平均差枚」や「平均出玉率」を直接使った方が情報量は多いはず
   - 二値化が選ばれたのはキャリブレーション検証なしの過去のバリアント比較による

3. **セクション×日のsection_avg_histがrho=+0.195で最も強いシグナル**
   - これも内部では104%超え率を使っている
   - 連続値に変えればさらに改善する可能性がある

## 目的

hist_metricおよびsection_avg_histの内部指標を変えて、以下の候補を比較する。
どの指標が最も高い予測力（Spearman rho, D0→D9分離幅）を持つかを確定する。

## 指標候補

### 台レベル（hist_metric の代替）

過去90日間（target_date未満）の台ごとの集計:

1. **hit_104_rate** (現行): 出玉率104%を超えた日の割合。二値化による情報損失あり
2. **avg_diff**: 平均差枚（diff_coins_normalized）。連続値、外れ値の影響大
3. **avg_payout**: 平均出玉率（payout_rate）。連続値、avg_diffよりスケールが安定
4. **median_diff**: 差枚の中央値。外れ値に頑健
5. **median_payout**: 出玉率の中央値。外れ値に頑健
6. **winsorized_diff**: 差枚の上下5%をWinsorize（上下5%パーセンタイルに置換）した平均。外れ値抑制
7. **positive_rate**: 差枚プラスの日の割合。104%より緩い二値化

### セクションレベル（section_avg_hist の代替）

セクション内全台の台レベル指標を平均したもの:

上記7指標それぞれについて `section_avg_X` を算出する。
例: section_avg_median_payout = セクション内全台のmedian_payoutの平均

## 固定前提（ユーザー確認済み）

- DB: `db/マルハンメガシティ2000-蒲田7.db`
- セクション定義: `ml/experiments/walkforward_scoring/config.py` の SECTION_RANGES_2F, SECTION_RANGES_3F
- フィルタ: `games_normalized >= 1500`、日付`0707`除外、台番号`2026`除外
- リーク防止: 全指標の計算は `date_dt < target_date` を厳密に適用
- 評価期間: 60日walk-forward、window=90日

## 実装

```
ファイル: eda/target_metric_comparison.py
DB: db/マルハンメガシティ2000-蒲田7.db
```

### 処理内容

1. 60日walk-forwardの各日付で:
   - trainデータ（target_date未満、90日窓）から7指標を台ごとに算出
   - actualデータ（target_date当日）の実績（payout_rate, diff_coins_normalized, hit_104）を取得
   - 台レベル: 各指標とactualのhit_104のSpearman相関を計算
   - セクションレベル: section_avg_Xとsection_hit_rate（当日）のSpearman相関を計算

2. Winsorizeの実装:
   ```python
   from scipy.stats import mstats
   winsorized = mstats.winsorize(values, limits=[0.05, 0.05])
   avg = winsorized.mean()
   ```

3. payout_rateの計算:
   ```python
   payout_rate = ((games_normalized * 3 + diff_coins_normalized) / (games_normalized * 3)) * 100
   ```

### 出力（2段階で明確に分離すること）

出力は **Part 1: 探索的指標比較** と **Part 2: パイプライン統合検証** に分ける。
レポートファイルも分離する。混在させない。

#### Part 1: 探索的指標比較（report_exploration.md）

各指標の予測力を単独で評価する。ここではランキング戦略の比較は行わない。

**台レベル評価テーブル**:
```
| metric | spearman_rho | p_value | d0_hit104 | d9_hit104 | delta_pp |
```
d0/d9はその指標で台を十分位に分け、最低群/最高群の104%超え率。

**セクションレベル評価テーブル**:
```
| metric | spearman_rho | p_value | d0_section_hit_rate | d9_section_hit_rate | delta_pp |
```
d0/d9はsection_avg_Xでセクションを十分位に分け、最低群/最高群のsection_hit_rate平均。

**ベンチマーク比較**:
- 台レベルベンチマーク: hit_104_rate（現行）rho=+0.038
- セクションレベルベンチマーク: section_avg_hit_104_rate（現行）rho=+0.195

#### Part 2: パイプライン統合検証（report_pipeline.md）

Part 1で上位3指標を選び、predict_section.pyと同じ2段階評価を実施する。
Part 1の結果が出た後にこちらを実行する（Part 1の結果に基づいて指標を選ぶため）。

- Stage 1: section_avg_Xでセクションをランキング
- Stage 2: 選ばれたセクション内でXの台レベル指標で台をランキング
- Top-Kセクション×Top-N台の104%超え率を、現行（section_avg_hist × hit_104_rate）と比較
- 台数を揃えて比較すること

```
| strategy | top_k_sec | top_n_machine | total_n | hit_104_rate | baseline | lift |
| section_avg_hit104 × hit104 (現行) | 5 | 5 | 25 | XX.X% | XX.X% | X.XXx |
| section_avg_median_payout × median_payout | 5 | 5 | 25 | XX.X% | XX.X% | X.XXx |
| ... | ... | ... | ... | ... | ... | ... |
```

### 注意
- DBデフォルトパスは `db/マルハンメガシティ2000-蒲田7.db`（`--db-path`引数で変更可能にする）
- `to_markdown()` は使わない。print文で出力する
- 出力ファイル: `eda/results/target_metric_comparison/report_exploration.md`, `report_pipeline.md` + CSV

### 防御的ガード（必須）

以下のエッジケースを全て処理すること。ガードが不十分だと比較結果より先に実行が壊れる:

1. **Winsorize**: 入力が全て同一値（分散ゼロ）の場合、Winsorize後も同一値になる。mean()は正常に返るのでエラーにはならないが、Spearman相関の入力としては定数列になるためrho=NaNになる。→ `nunique() < 3` のチェックでスキップ

2. **空セクション**: セクション内の全台がフィルタ（games_normalized >= 1500）で除外される日がある。→ section_avg_Xの計算時に台数0ならNaNを返す

3. **台の履歴不足**: 新台や長期休止台はtrain期間に1行もない。→ hist_metricをNaN（0ではない）にし、ランキングから除外

4. **十分位分割の失敗**: `pd.qcut`は同値が多いとbin数が足りずエラーになる。→ `duplicates="drop"` を常に指定し、実際のbin数が3未満ならその指標のSpearman計算をスキップ

5. **Spearman相関の入力チェック**: 片方が定数列（全て同じ値）の場合、scipy.stats.spearmanrはwarningを出してNaNを返す。→ 入力の`nunique() >= 3`を事前チェック

6. **母数不足**: セクション内台数が2台以下、またはtrain期間のデータが10行未満の場合、指標の信頼性が低い。→ セクション内台数3台以上、台ごとのtrain行数5行以上をフィルタ条件とする

## 評価基準

- 固定閾値での成否判定は行わない
- 主指標: Spearman rho の大きさ（ベンチマーク比）
- 副指標: D0→D9分離幅（pp）
- 最終判定: 2段階パイプラインでの104%超え率（同じ台数での比較）
- 現行のhit_104_rateがベストなら、そのまま使い続ける（変更は改善が確認された場合のみ）
