# Codex プロンプト: セクション×日 2段階推薦パイプライン

## 背景

予測粒度シフト実験で以下が確認された:

1. **セクション×日の粒度がベンチマークを大幅に上回る**
   - section_avg_hist: Spearman rho=+0.195, D0→D9=+10.1pp（台×日のhist_metric rho=+0.038, +6.0ppの5倍）
   - hist_section_hit_rate: rho=+0.192, D0→D9=+10.1pp
   - section_avg_hist Top1セクション、閾値45%でlift=1.79x

2. **台×週の粒度は改善なし**（rho=+0.043、台×日と同等）

3. **台×日のcompositeスコアは予測力ゼロ**（全9バリアントでrho≈0）

4. **台×日でhist_metricのみが有効**（rho=+0.038, +6.0pp）

これらを踏まえ、2段階の推薦パイプラインを構築する:
- **Stage 1**: セクション×日で「今日どのセクションが熱いか」を予測
- **Stage 2**: 選ばれたセクション内でhist_metricによる台ランキング

## 固定前提（ユーザー確認済み）

- セクション定義: `ml/experiments/walkforward_scoring/config.py` の SECTION_RANGES_2F, SECTION_RANGES_3F
- フィルタ: `games_normalized >= 1500`、日付`0707`除外、台番号`2026`除外
- リーク防止: 全特徴量の計算は `date_dt < target_date` を厳密に適用

## 実装

```
ファイル: ml/experiments/walkforward_scoring/predict_section.py
DB: db/マルハンメガシティ2000-蒲田7.db
```

### データの分離（リーク防止の詳細）

予測時に2つのデータセットを厳密に分けること:

1. **履歴データ（train）**: `date_dt < target_date` かつ `date_dt >= target_date - window_days` の全行。
   Stage 1のsection_avg_histとStage 2のhist_metricの計算に使う。
2. **当日の台一覧（roster）**: target_dateのデータが存在する場合はその日の台一覧。
   存在しない場合（前方予測）は最新日の台一覧を使用。
   rosterは「どの台がどのセクションに属するか」の紐付けにのみ使い、
   rosterの出力データ（diff_coins_normalized, games_normalized等）はStage 1/2の特徴量計算に一切含めない。

この分離を実装上明示するため、以下の変数名を使うこと:
```python
train = data[(data["date_dt"] < target_date) & (data["date_dt"] >= target_date - pd.Timedelta(days=window_days))]
roster = data[data["date_dt"] == roster_date]  # roster_date = target_date or latest available
# section_avg_hist は train のみから計算
# hist_metric は train のみから計算
# roster は台→セクションの紐付けと出力にのみ使用
```

### Stage 1: セクションスコアリング

各セクションに対して以下のスコアを算出する:

```
section_score = section_avg_hist
```

section_avg_histの定義:
- **trainデータのみ**から、セクション内の全台について104%超え率を台ごとに算出
- その平均値をセクションスコアとする
- これは実験Aで最も高いrho（+0.195）を示した特徴量

prev_day_section_hot（前日のsection_hit_rate）はrho=+0.080で有意だったが、section_avg_histとの相関が高く、
追加による改善が不明なため、まずはsection_avg_hist単体で実装する。
改善検証は後続タスクとする。

### Stage 2: セクション内台ランキング

Stage 1で選ばれたセクション内の台をhist_metric降順でランキングする。
hist_metricの定義は現行と同じ: **trainデータのみ**から、過去90日間の104%超え率（A系は104%閾値、N系は106%閾値）。

### 出力形式

セクションスコア降順で全セクションを表示し、各セクション内でhist_metric上位N台を表示する。

```
# Section Prediction: 2026-06-28 (DD28, Sun, non-event)

## Section 3209-3217 (section_score=38.2, rank=1/53)
| 順位 | 台番 | 機種名 | hist | 角番 |
|:---:|:---:|:---|---:|:---:|
| 1 | 3211 | 東京喰種 | 39.8 | 3 |
| 2 | 3215 | 東京喰種 | 36.4 | 7 |
...

## Section 2298-2313 (section_score=37.5, rank=2/53)
...
```

### CLI引数

```
python -m ml.experiments.walkforward_scoring.predict_section \
    --date 20260628 \
    --db-path db/マルハンメガシティ2000-蒲田7.db \
    --window-days 90 \
    --top-sections 10 \
    --top-machines-per-section 5
```

- `--date`: 予測対象日（YYYYMMDD）。必須
- `--db-path`: DBパス。デフォルトは蒲田7
- `--window-days`: 履歴窓。デフォルト90
- `--top-sections`: 表示するセクション数。デフォルト10
- `--top-machines-per-section`: セクション内表示台数。デフォルト5

### 実装上の注意

- `score_day()` は使わない。セクションスコアリングは独立した計算で、既存のcompositeスコアリングとは別系統
- セクション定義は `config.py` の SECTION_RANGES_2F, SECTION_RANGES_3F から動的にロードする
- 座標データ（`Heatmap/2F_floor_coordinates_kamata7.csv`, `3F_floor_coordinates_kamata7.csv`）からsection, rank_from_min等を取得
- 実績データがまだない日（前方予測）の場合は、最新日の台リストをrosterとして使用する（predict_gated.pyの前方予測と同じ方式）
- 出力はMDファイル（`results/predict_section_YYYYMMDD.md`）とCSV（セクション別）

### walk-forward評価モード

`--eval` フラグで評価モードを有効化:

```
python -m ml.experiments.walkforward_scoring.predict_section \
    --eval --eval-days 60
```

評価モードでは:
1. 過去60日分の各日付でStage 1 + Stage 2を実行
2. セクション単位の評価:
   - Top-Kセクション（K=1,3,5,10）の実際のsection_hit_rateをベースラインと比較
   - Spearman rhoを算出
3. 台単位の評価:
   - Top-Kセクション内のhist_metric上位N台の104%超え率
   - ベースライン（全台ランダム）との比較
   - Stage 1のみ（セクション選択）の改善と、Stage 1+2（セクション選択＋台選び）の改善を分離して計測
4. 出力: evaluation_report.md に結果を書き出す

## 成功基準（評価モードでの確認事項）

- 固定閾値での成否判定は行わない
- 以下の指標を併記し、台×日のhist_metric単体（Spearman rho=+0.038, D0→D9=+6.0pp）との比較で評価する:
  - Stage 1: section_avg_histのSpearman rho（実験Aでは+0.195）が再現されるか
  - Stage 1+2: Top-Kセクション内hist上位N台の104%超え率とベースラインの差（pp）
  - Stage 1+2 vs hist_metricグローバルTop-N: **台数を揃えて比較する**

### 台数を揃えた比較の方法

Stage 1+2で選ばれる台数は `top_sections × top_machines_per_section` で決まる。
比較対象のグローバルhist_metric Top-Nは、同じ台数Nを使う。

例: top_sections=5, top_machines_per_section=5 → 25台
→ 比較対象: グローバルhist_metric Top25

評価レポートには以下の比較テーブルを含めること:

```
| 戦略 | 台数 | 104%+率 | Base | Lift |
|:---|---:|---:|---:|---:|
| Stage1+2 (top5sec × top5台) | 25 | XX.X% | XX.X% | +X.Xpp |
| グローバルhist Top25 | 25 | XX.X% | XX.X% | +X.Xpp |
| Stage1+2 (top10sec × top5台) | 50 | XX.X% | XX.X% | +X.Xpp |
| グローバルhist Top50 | 50 | XX.X% | XX.X% | +X.Xpp |
```

これにより「セクション選択を経由した方が、単純なグローバルhist順より良いか」が同一台数で判定できる。

## 既存コードとの関係

- `predict_gated.py` の `--segment-ranking` モードとは独立。predict_sectionは新規ファイル
- `config.py` のSECTION_RANGES_2F/3Fを再利用
- `walk_forward_engine.py` のload_machine_data()を再利用
- `scoring_model.py` のbuild_score_context()（座標ロード）を再利用
- `eda/granularity_shift_common.py` のヘルパー関数があれば再利用可
- compositeスコア（c1-c6）は使用しない
