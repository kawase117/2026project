# Phase10g: mixed_805 debut×X_DDS 交互作用のセル分解

## 目的

Phase10e で mixed_805 セグメントに以下の異常が見つかった:
- debut 主効果: F=0.471, **p=0.702**（差なし）
- debut×X_DDS 交互作用: F=10.819, **p<0.001**（強い交互作用）

主効果がないのに交互作用だけ強い — 特定の debut_phase × X_DDS セルが突出している可能性がある。
セル別の avg_diff を可視化し、どのセルが駆動しているかを特定する。

## 前提

### 既存コード依存

`eda/mitoya_phase10e_xdds_kakuban_debut.py` の枠組みを踏襲する。

- `eda/mitoya_prompt_common.py` の関数群をそのまま流用する：
  - `load_mitoya_frame(join_layout=True)` — DB読み込み + machine_layout JOIN
  - `add_event_category(df)` — `is_xdds_day` 列（0/1）を含む event_category を付与
  - `add_debut_phase(df)` — `debut_days`（int）と `debut_phase`（str）と `is_moved`（bool）を付与
  - `render_markdown_table(df)` — テーブル出力（**to_markdown() 禁止**）
  - DB パスは `DB_PATH` 定数を使用
  - 定数: `DEBUT_PHASE_ORDER = ["pre_existing", "debut", "growth", "mature"]`
- `eda/mitoya_phase10_segment_validation.py`:
  - `_prepare_frame(df)` — games>=1000フィルタ、orientation/jug_flag/corner_bucket付与
  - `_segment_frame(work, segment)` — セグメントフィルタ

### 呼び出し順序の固定（厳守）

1. `add_debut_phase(df)` を先に呼ぶ（`machine_name` が生きている状態で）
2. `add_event_category(work)` を呼ぶ
3. `phase10._prepare_frame(work)` を呼ぶ
4. `is_moved` 列（bool）で moved を除外する

### 対象セグメント

mixed_805 を主対象。比較用に h_nonjug と h_jug も出力する。

## ファイル構成

| ファイル | 用途 |
|---------|------|
| `eda/mitoya_phase10g_mixed805_cell_heatmap.py` | 分析メイン |
| `ml/tests/test_mitoya_phase10g_mixed805_cell_heatmap.py` | テスト |

## 分析ステップ

### Step 1: debut_phase × is_xdds セル別統計 — `build_step1_cell_stats(work)`

各セグメントごとに、debut_phase × is_xdds_day（0/1）の全セル（最大 4×2=8セル）の n / avg_diff / plus_rate を算出する。

- **母集団**: X_DDS日 + 非イベント日のみ。ゾロ目日・月末・強ゾロ目は母集団から除外する
- moved は除外済み（`is_moved` 列で判定）

出力:
```
segment   | debut_phase  | is_xdds | n    | avg_diff | plus_rate
mixed_805 | pre_existing | 0       | ...  | ...      | ...
mixed_805 | pre_existing | 1       | ...  | ...      | ...
mixed_805 | debut        | 0       | ...  | ...      | ...
mixed_805 | debut        | 1       | ...  | ...      | ...
mixed_805 | growth       | 0       | ...  | ...      | ...
mixed_805 | growth       | 1       | ...  | ...      | ...
mixed_805 | mature       | 0       | ...  | ...      | ...
mixed_805 | mature       | 1       | ...  | ...      | ...
h_nonjug  | ...          | ...     | ...  | ...      | ...
h_jug     | ...          | ...     | ...  | ...      | ...
```

`is_xdds` は int (0 or 1)。

### Step 2: セル間コントラスト — `build_step2_cell_contrast(cell_stats)`

Step 1 の結果から、各 debut_phase について X_DDS日(1) - 非イベント日(0) の avg_diff 差分を算出。

出力:
```
segment   | debut_phase  | xdds_avg_diff | nonevent_avg_diff | contrast | xdds_n | nonevent_n
mixed_805 | pre_existing | ...           | ...               | ...      | ...    | ...
mixed_805 | debut        | ...           | ...               | ...      | ...    | ...
mixed_805 | growth       | ...           | ...               | ...      | ...    | ...
mixed_805 | mature       | ...           | ...               | ...      | ...    | ...
h_nonjug  | ...          | ...           | ...               | ...      | ...    | ...
h_jug     | ...          | ...           | ...               | ...      | ...    | ...
```

`contrast` = xdds_avg_diff - nonevent_avg_diff。正なら「X_DDS日にそのフェーズが優遇」。

### Step 3: 駆動セル特定 — `build_step3_driver_identification(cell_stats)`

各セグメントについて、全セルの avg_diff を z-score に変換し、|z| > 1.5 のセルを「外れセル」としてリストアップ。

出力:
```
segment   | debut_phase | is_xdds | avg_diff | z_score | is_outlier
mixed_805 | debut       | 1       | ...      | 2.3     | True
...
```

z_score はセグメント内全セルの avg_diff 平均・標準偏差から算出。n < 10 のセルは除外する。

### Step 4: セグメント横断サマリ — `build_step4_summary(contrast_df)`

全セグメントの contrast 最大セル（どの debut_phase で X_DDS プレミアムが最大か）を1テーブルに。

出力:
```
segment   | max_contrast_phase | contrast | xdds_n | nonevent_n
mixed_805 | ...                | ...      | ...    | ...
h_nonjug  | ...                | ...      | ...    | ...
h_jug     | ...                | ...      | ...    | ...
```

## 出力

### Markdown レポート
`tmp/mitoya_phase10g_mixed805_cell_heatmap/report.md`

見出し構造:
```markdown
# Phase10g: mixed_805 debut×X_DDS セル分解

## Step 1: セル別統計
（segment別テーブル）

## Step 2: セル間コントラスト
（segment別テーブル）

## Step 3: 駆動セル特定
（外れセルのみ）

## Step 4: セグメント横断サマリ
（1テーブル）

## Finding
（どのセルが交互作用を駆動しているかの結論）
```

### CSV 出力
`tmp/mitoya_phase10g_mixed805_cell_heatmap/` 配下に:
- `step1_cell_stats.csv`
- `step2_cell_contrast.csv`
- `step3_driver_identification.csv`
- `step4_summary.csv`

## 出力制約

- テーブル出力は `render_markdown_table()` を使用する（**`to_markdown()` 禁止**）
- 空セグメントはスキップし NaN が出ないこと
- 日本語を含む関数を編集する場合は関数全体を置き換えること（行単位パッチ禁止）
- ファイルエンコーディングは UTF-8（BOMなし）

## テスト要件

`ml/tests/test_mitoya_phase10g_mixed805_cell_heatmap.py` に以下を含める。

### テストデータ生成

ダミー DataFrame を生成する fixture `dummy_frame()`:

- 日付: `20260101`〜`20260201` の期間（YYYYMMDD形式）
- dd=7（X_DDS日）と dd=3（非イベント日）を含めること
- machine_number: 805〜815 の範囲（mixed_805 セクション用）+ 501〜520（h_nonjug 用）
- machine_name: 非ジャグラー機種を2種以上。うち1種は途中で変更（debut 生成用）
- section: "805-815" と "501-522"
- x, y: 適切な値
- rank_from_aisle: 1〜10
- games: 全行 1500 以上
- diff: 特定セル（例: debut × X_DDS）に高い値を設定（駆動セル検出テスト用）

### テスト項目

```python
def test_step1_cell_count(dummy_frame):
    """build_step1_cell_stats が debut_phase × is_xdds の全セルを返す"""

def test_step2_contrast_calculation(dummy_frame):
    """contrast = xdds_avg_diff - nonevent_avg_diff が正しい"""

def test_step3_outlier_detection(dummy_frame):
    """z_score と is_outlier が算出される"""

def test_step4_summary_per_segment(dummy_frame):
    """各セグメントの max_contrast_phase が返る"""

def test_generate_report_creates_files(dummy_frame, tmp_path):
    """report.md と 4 CSV が生成される"""
```

## 実行確認

```bash
cd C:\Users\apto117\Documents\pachinko-analyzer\src\2026project
python -m pytest ml/tests/test_mitoya_phase10g_mixed805_cell_heatmap.py -v
python -m eda.mitoya_phase10g_mixed805_cell_heatmap
```

エラーなく report.md と 4 CSV が生成されること。
