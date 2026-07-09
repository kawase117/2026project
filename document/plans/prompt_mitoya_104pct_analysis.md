# みとや: 104%率分析（蒲田7手法の導入）

## 目的

蒲田7では DD を差枚ではなく 104% 率で分析して DD18-23 のトラフゾーン（98.6-99.2%）を発見した。差枚平均では見えない「高設定台の出現率」の構造が 104% 率で可視化される。

みとやの Phase11a では差枚ベースの KW で DD full spectrum を検証し「X_DDS 引き上げのみ、トラフなし」と結論したが、104% 率で再検証することで差枚では見えない構造がないか確認する。

## 前提

### 104%率の定義

`payout_rate >= 104%` の台の出現率。`payout_rate` は `machine_detailed_results` テーブルの `payout_rate` 列（パーセント）。104% は高設定の目安（設定5-6相当）。

計算: `rate_104 = (payout_rate >= 104).sum() / len(frame) * 100`

### 既存コード依存

- `eda/mitoya_prompt_common.py`:
  - `load_mitoya_frame(join_layout=True)` — DB読み込み
  - `add_event_category(df)` — event_category を付与
  - `render_markdown_table(df)` — テーブル出力（**to_markdown() 禁止**）
  - DB パスは `DB_PATH`
- `eda/mitoya_phase10_segment_validation.py`:
  - `_prepare_frame(df)` — games>=1000フィルタ等
  - `_segment_frame(work, segment)` — セグメントフィルタ

### payout_rate 列の確認

`machine_detailed_results` テーブルに `payout_rate` 列がない場合は `diff` と `games` から算出する:
```python
if "payout_rate" not in work.columns:
    work["payout_rate"] = 100.0 + (work["diff"] / (work["games"] * 3.0)) * 100.0
```

※ 3.0 は1ゲームあたり投入枚数（3枚掛け）。ホールによって異なる場合は調整が必要だが、みとやは全台3枚掛けと仮定する。

### セグメント定義

```python
SEGMENT_ORDER = ["h_jug", "h_nonjug", "v_jug", "v_nonjug", "mixed_805"]
```

## ファイル構成

| ファイル | 用途 |
|---------|------|
| `eda/mitoya_104pct_analysis.py` | 分析メイン |
| `ml/tests/test_mitoya_104pct_analysis.py` | テスト |

## 分析ステップ

### Step 1: DD full spectrum × 104%率 — `build_step1_dd_104rate(work)`

DD 1-31 別の 104%率を算出。3粒度（ホール全体 / セグメント別 / セグメント×event_scope）。

出力:
```
grain     | segment   | event_scope | dd | n    | rate_104 | avg_payout | avg_diff
hall      |           |             | 1  | ...  | ...      | ...        | ...
hall      |           |             | 2  | ...  | ...      | ...        | ...
...（31行 × 各粒度）
```

`rate_104` = 104%超え台の割合（%）。`avg_payout` = 平均 payout_rate。

event_scope は "X_DDS" と "非イベント日" の2値。ゾロ目日・月末・強ゾロ目は母集団から除外する。

### Step 2: DD ピーク/トラフ構造 — `build_step2_peak_trough(dd_104)`

Step 1 の hall 粒度から、rate_104 の Top5（ピーク）と Bottom5（トラフ）を抽出。

出力:
```
category | dd | rate_104 | avg_payout | n    | is_xdds
peak     | 4  | ...      | ...        | ...  | True
peak     | 7  | ...      | ...        | ...  | True
...
trough   | 29 | ...      | ...        | ...  | False
trough   | 13 | ...      | ...        | ...  | False
...
```

蒲田7ではピークが全てイベント日、トラフが DD18-23 に集中していた。みとやでも同じ構造があるか確認。

### Step 3: 差枚 vs 104%率の乖離 — `build_step3_diff_vs_104(dd_stats)`

DD 別の avg_diff ランキングと rate_104 ランキングの Spearman ρ を算出。乖離が大きい DD を特定。

出力:
```
grain   | segment   | spearman_rho | p_value | n
hall    |           | ...          | ...     | 31
segment | h_jug     | ...          | ...     | 31
...
```

追加出力（乖離の大きい DD）:
```
grain   | segment   | dd | diff_rank | rate104_rank | gap | avg_diff | rate_104
hall    |           | 30 | 3         | 15           | 12  | +159     | 28.5
...
```

### Step 4: 角番 × 104%率 — `build_step4_corner_104rate(work)`

セグメント別に corner_bucket × 104%率を算出。蒲田7では角番ごとの 104%率と差枚のランキングが一致しないことが判明（設定4集中 vs 設定6一点の違い）。

出力:
```
segment   | corner_bucket | n    | rate_104 | avg_payout | avg_diff | diff_rank | rate104_rank
h_jug     | corner1       | ...  | ...      | ...        | ...      | 1         | ...
h_jug     | corner2-4     | ...  | ...      | ...        | ...      | 2         | ...
...
```

### Step 5: 非X_DDS の DD 内部構造（104%率版） — `build_step5_nonxdds_104(work)`

Phase11a で差枚ベースでは「X_DDS 引き上げのみ」と結論した DD full spectrum を、104%率で再検証。non-X_DDS の DD のみを対象に KW 検定。

出力:
```
grain   | segment   | kw_stat | p_value | epsilon_sq | n_groups | n
hall    |           | ...     | ...     | ...        | ...      | ...
segment | h_jug     | ...     | ...     | ...        | ...      | ...
...
```

### Step 6: サマリ — `build_step6_summary(all_results)`

主要 finding を1テーブルに。

出力:
```
finding                          | value   | note
hall_peak_trough_gap_pp          | ...     | ピークとトラフの 104%率差（pp）
hall_diff_vs_104_rho             | ...     | 差枚と104%率の Spearman ρ
nonxdds_dd_kw_p_hall             | ...     | 非X_DDS DD の KW p値（ホール全体）
h_jug_corner1_104rate            | ...     | h_jug corner1 の 104%率
h_nonjug_corner1_event_104rate   | ...     | h_nonjug corner1 X_DDS日の 104%率
```

## 出力

### Markdown レポート
`tmp/mitoya_104pct_analysis/report.md`

見出し構造:
```markdown
# みとや 104%率分析

## Step 1: DD full spectrum × 104%率
## Step 2: ピーク/トラフ構造
## Step 3: 差枚 vs 104%率の乖離
## Step 4: 角番 × 104%率
## Step 5: 非X_DDS DD 内部構造（104%率版）
## Step 6: サマリ
```

### CSV 出力
`tmp/mitoya_104pct_analysis/` 配下に:
- `step1_dd_104rate.csv`
- `step2_peak_trough.csv`
- `step3_diff_vs_104.csv`
- `step3_divergent_dd.csv`
- `step4_corner_104rate.csv`
- `step5_nonxdds_kw.csv`
- `step6_summary.csv`

## 出力制約

- テーブル出力は `render_markdown_table()` を使用する（**`to_markdown()` 禁止**）
- ファイルエンコーディングは UTF-8（BOMなし）
- DBデフォルトは `DB_PATH`
- payout_rate が存在しない場合の算出ロジックを含めること

## テスト要件

`ml/tests/test_mitoya_104pct_analysis.py`:

- 日付: `20260101`〜`20260131`（YYYYMMDD形式）
- machine_number: 501〜560（水平）+ 701〜720（垂直）
- payout_rate: 一部の台に 104% 以上を設定（rate_104 算出テスト用）
- games: 1500以上

```python
def test_step1_dd_31_rows(dummy_frame)
def test_step2_peak_trough_count(dummy_frame)
def test_step3_rho_returns(dummy_frame)
def test_step4_corner_per_segment(dummy_frame)
def test_step5_nonxdds_only(dummy_frame)
def test_report_creates_files(dummy_frame, tmp_path)
```

## 実行確認

```bash
python -m pytest ml/tests/test_mitoya_104pct_analysis.py -v
python -m eda.mitoya_104pct_analysis
```
