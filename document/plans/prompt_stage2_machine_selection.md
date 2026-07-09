# Codex プロンプト: Stage 2（セクション内台選び）の改善検証

## 背景

predict_section.pyの2段階パイプラインで:
- Stage 1（セクション選択）: rho=+0.19, 十分に機能している
- Stage 2（セクション内台選び）: hist_metric rho=+0.04, ほぼランダムに近い

Stage 2を改善できれば、同じ25台の選出枠で収益が直接上がる。

過去の検証（台×日, 全台対象）では角番・debut_phase・trailing payoutは台レベルで効果なしだった。
しかし「Top5セクション内の25台」に限定した検証はしていない。
セクション内に限定することでノイズが減り、信号が検出できる可能性がある。

## 固定前提

- DB: `db/マルハンメガシティ2000-蒲田7.db`
- セクション定義: `ml/experiments/walkforward_scoring/config.py` の SECTION_RANGES_2F, SECTION_RANGES_3F
- 座標: `scoring_model.build_score_context()` を使用
- フィルタ: `games_normalized >= 1500`、日付`0707`除外、台番号`2026`除外
- リーク防止: `date_dt < target_date` を厳密適用
- 窓幅: 60日（先行検証で決定済み）
- セクション選択: Top5セクション（Stage 1は現行のまま、Stage 2のみ変える）
- 差枚は1台あたり平均で出力する
- 評価期間: 60日walk-forward

## 検証対象の特徴量

### A. セクション内角番位置（kakuban）

台の角番（セクション内の通路からの位置）と104%超えの関係。
角番は `scoring_model.py` の `kakuban_new` を使用。

特徴量:
- `kakuban_raw`: 角番の生値（1, 2, 3, ...）
- `kakuban_group`: カテゴリ化（K1, K2, K3-4, K5-9, K10-14, K15+）
- `kakuban_edge`: 角番1 or 角番max（両端）かどうかの二値

### B. debut_phase（台の導入からの経過日数）

特徴量:
- `debut_days`: 導入からの日数（連続値）
- `debut_phase`: カテゴリ（debut=14日以内, growth=15-60日, mature=61-180日, pre_existing=181日+）

導入日の計算: trainデータ内でその台番号が初めて出現した日。
ただし窓幅60日では初出現日が実際の導入日より遅い可能性がある。
窓幅外の過去データも参照して初出現日を計算する（リーク防止: 台の存在自体は未来情報ではない）。

### C. 直近トレンド（trailing performance）

特徴量:
- `trail_7d_hit`: 直近7日の104%超え率
- `trail_14d_hit`: 直近14日の104%超え率
- `trail_diff_7d`: 直近7日の平均差枚
- `momentum`: trail_7d_hit - hist_metric（直近が全体平均より上か下か）

### D. 交互作用

- `kakuban_group × hist_metric`: 角番グループ別のhist_metric平均との差
- `debut_phase × hist_metric`: debut_phase別のhist_metric平均との差

## スコープの明確化

- Stage 1は **Top5セクション固定**。predict_section.pyのデフォルト(10)とは別に、この実験ではtop_sections=5で統一する
- Stage 2のみを変更し、Stage 1には手を加えない
- 評価単位: Top5セクション × 5台 = 25台/日

## debut_phaseのリーク防止ルール

導入日（初出現日）は**全履歴（date_dt < target_date の全行）**から計算する。60日窓の外も参照してよい。
台の存在自体は未来情報ではないため、リークにならない。
ただし、debut_phaseの計算に使う日付は厳密に `date_dt < target_date` を守ること。
```python
# OK: 台の初出現日を全履歴から計算
all_history = data[data["date_dt"] < target_date]
first_seen = all_history.groupby("machine_number")["date_dt"].min()
debut_days = (target_date - first_seen).dt.days

# NG: target_date以降のデータを参照
# first_seen = data.groupby("machine_number")["date_dt"].min()  ← リーク
```

## 特徴量の正規化ルール

全特徴量をブレンドする際、スケールを揃えるために**セクション内パーセンタイルランク**に変換する。
```python
# 各特徴量をセクション内で0-1のパーセンタイルに変換
for feature in features:
    df[f"{feature}_prank"] = df.groupby("section")[feature].rank(pct=True)
# ブレンド
df["blend_score"] = hist_prank + α × kakuban_prank + β × debut_prank + γ × trail_prank
```
これにより、hist_metric（0-1の比率）とkakuban_raw（1-22の整数）のスケール差を解消する。

## 五分位評価のフォールバック

- `pd.qcut` は `duplicates="drop"` を常に指定
- 実際のbin数が3未満の場合、その特徴量のSpearman計算をスキップ
- セクション内台数が5台未満のセクションはプールから除外
- Top5セクション全体のプール台数が20台未満の日はスキップ

## 実装

```
ファイル: eda/stage2_machine_selection.py
```

### 処理

1. 60日walk-forwardの各日付で:
   - Stage 1でTop5セクションを選択（現行と同じ、top_sections=5固定）
   - Top5セクション内の全台（台数5未満のセクションは除外）に対して上記特徴量を計算
   - 各特徴量をセクション内パーセンタイルランクに変換
   - 各特徴量と当日hit_104のSpearman相関を計算（**セクション内限定**）

2. 特徴量の評価:
   - セクション内pooled Spearman rho（全日×全Top5セクション内台をプール）
   - 特徴量の五分位別hit率（プール全体で五分位に分割、duplicates="drop"、bin<3はスキップ）

3. Stage 2のランキング戦略比較:
   Top5セクション内の台を**セクション内パーセンタイルランク**でランキングし、上位5台を選ぶ方法を比較
   
   ```
   strategies:
   - hist_only: hist_metric_prank降順（現行相当）
   - kakuban_weighted: hist_prank + α × kakuban_prank
   - debut_weighted: hist_prank + β × debut_prank
   - trail_weighted: hist_prank + γ × trail_7d_prank
   - momentum_weighted: hist_prank + δ × momentum_prank
   - combined: hist_prank + α × kakuban_prank + β × debut_prank + γ × trail_prank
   ```
   
   α, β, γ, δのグリッドサーチは行わない。
   まず各特徴量単体のSpearman rhoを見て、rho > 0 かつ p < 0.1 のもののみ組み合わせを検討する。
   組み合わせ時の重みは全て1.0（等重み）で開始し、結果を見て判断する。

4. 最終評価:
   - 各戦略のTop5セクション×5台の104%超え率とavg_diff/台
   - 現行（hist_only）との台数揃え比較

### 出力

**Part 1: 特徴量の予測力**（report_features.md）
```
| feature | rho_in_section | p_value | q0_hit | q4_hit | delta_pp |
```

**Part 2: 戦略比較**（report_strategies.md）
```
| strategy | hit_rate | baseline | lift | avg_diff | vs_hist_only |
```

### 注意
- DBデフォルトパスは `db/マルハンメガシティ2000-蒲田7.db`（`--db-path`引数で変更可能にする）
- `to_markdown()` は使わない。print文で出力する
- 出力先: `eda/results/stage2_machine_selection/`
- セクション内の台数が5台未満のセクションはスキップ
- trail_7d/14dで対象期間にデータがない台はNaN処理
- 角番はkakuban_newを使用（config.pyのREVERSED_NEWに基づく方向補正済み）

## 評価基準

- 各特徴量のセクション内Spearman rhoが+0.02以上かつp < 0.1なら「信号あり」と判断
- 戦略比較では現行（hist_only）のavg_diff/台を上回れば改善とする
- 効果量が小さい（+50枚/台以下）場合は、複雑さに見合わないため採用しない
- 過去の全台検証で効果なしだった特徴量でも、セクション内限定で結論が変わるかが検証の主眼
