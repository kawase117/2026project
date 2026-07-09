# Phase10h: v_jug 角番効果の不在検証

## 目的

Phase10e で h_jug は corner_bucket の主効果が F=51.3, p<0.001 と非常に強いが、v_jug は F=1.84, **p=0.137** で角番効果が検出されなかった。

この差の原因を物理配置と島構造の違いから検証する。

- **仮説D（物理的可視性）**: 水平島は通路から角台が目立つためホールが角に高設定を置くが、垂直島は角の意味が薄く差が出ない
- **仮説E（セクションサイズ差）**: 垂直セクションは台数が少なく、corner_bucket の分布が偏っているだけ
- **仮説F（機種構成差）**: v_jug は特定のジャグラー機種に偏り、角番効果が機種効果と交絡している

## 前提

### 既存コード依存

`eda/mitoya_phase10e_xdds_kakuban_debut.py` の枠組みを踏襲する。

- `eda/mitoya_prompt_common.py` の関数群をそのまま流用する：
  - `load_mitoya_frame(join_layout=True)` — DB読み込み + machine_layout JOIN
  - `add_event_category(df)` — event_category を付与
  - `render_markdown_table(df)` — テーブル出力（**to_markdown() 禁止**）
  - DB パスは `DB_PATH` 定数を使用
  - 定数: `MITOYA_ALL_SECTIONS`
  - `kw_epsilon_squared(statistic, n_groups, n_rows)` — 効果量計算
- `eda/mitoya_phase10_segment_validation.py`:
  - `_prepare_frame(df)` — games>=1000フィルタ、orientation/jug_flag/corner_bucket付与
  - `_segment_frame(work, segment)` — セグメントフィルタ
  - `_kruskal_summary(frame, group_col, order=...)` — Kruskal-Wallis + epsilon^2

### 呼び出し順序

本分析では `add_debut_phase` は不要。ただし呼ぶ場合は `_prepare_frame` の前に呼ぶこと（`phase10._prepare_frame` が `machine_name` を空文字化するため）。

### 対象セグメント

h_jug と v_jug の比較が主目的。補助的に h_nonjug / v_nonjug も出力する。

## ファイル構成

| ファイル | 用途 |
|---------|------|
| `eda/mitoya_phase10h_vjug_corner_absence.py` | 分析メイン |
| `ml/tests/test_mitoya_phase10h_vjug_corner_absence.py` | テスト |

## 分析ステップ

### Step 1: セクション別 corner_bucket 分布 — `build_step1_corner_distribution(work)`

各セクション（MITOYA_ALL_SECTIONS）ごとに orientation と corner_bucket の分布を出す。

出力:
```
section   | orientation | corner_bucket | n    | pct
501-522   | horizontal  | corner1       | ...  | ...
501-522   | horizontal  | corner2-4     | ...  | ...
...
624-640   | vertical    | corner1       | ...  | ...
...
```

`pct` = そのセクション内でのパーセント。水平と垂直でcorner_bucket分布に偏りがあるかを確認する（仮説E）。

### Step 2: 物理配置の記述統計 — `build_step2_layout_stats(work)`

h_jug / v_jug それぞれで、角番（rank_from_aisle）の分布統計を出す。

出力:
```
segment | rank_from_aisle_mean | rank_from_aisle_std | section_size_mean | section_size_std | n_sections | n
h_jug   | ...                  | ...                 | ...               | ...              | ...        | ...
v_jug   | ...                  | ...                 | ...               | ...              | ...        | ...
```

`section_size` = 各セクションのユニーク台番号数。

### Step 3: corner_bucket 別 avg_diff（h_jug vs v_jug 直接比較） — `build_step3_corner_comparison(work)`

h_jug と v_jug を横並びで corner_bucket 別の avg_diff / plus_rate を比較する。

出力:
```
corner_bucket | h_jug_avg_diff | h_jug_n | h_jug_plus_rate | v_jug_avg_diff | v_jug_n | v_jug_plus_rate
corner1       | ...            | ...     | ...             | ...            | ...     | ...
corner2-4     | ...            | ...     | ...             | ...            | ...     | ...
corner5-9     | ...            | ...     | ...             | ...            | ...     | ...
corner10+     | ...            | ...     | ...             | ...            | ...     | ...
```

h_jug は corner1 → corner10+ の勾配が急で、v_jug はフラットなはず。

### Step 4: 機種構成比較 — `build_step4_machine_composition(work)`

h_jug と v_jug の machine_name 上位10機種の n と avg_diff を比較する（仮説F）。

出力:
```
segment | machine_name | n    | avg_diff | plus_rate | share_pct
h_jug   | ...          | ...  | ...      | ...       | ...
...
v_jug   | ...          | ...  | ...      | ...       | ...
...
```

`share_pct` = そのセグメント内での当該機種の行数比率。

### Step 5: 残差法での角番効果再検定 — `build_step5_residual_corner(work)`

機種効果を除去した上で角番効果を再検定する。

手順:
1. 各セグメントで machine_name ごとの全体平均 diff を算出
2. 各行の diff から機種平均を引いた residual を作成
3. residual に対して corner_bucket の Kruskal-Wallis を実施

出力:
```
segment | kw_stat | p_value | epsilon_sq | n_groups | n    | note
h_jug   | ...     | ...     | ...        | ...      | ...  | raw
h_jug   | ...     | ...     | ...        | ...      | ...  | residual
v_jug   | ...     | ...     | ...        | ...      | ...  | raw
v_jug   | ...     | ...     | ...        | ...      | ...  | residual
```

`note` が "raw" は元の diff、"residual" は機種効果除去後。v_jug で residual でも p>0.05 なら「角番効果は本当にない」（仮説D支持）。

## 出力

### Markdown レポート
`tmp/mitoya_phase10h_vjug_corner_absence/report.md`

見出し構造:
```markdown
# Phase10h: v_jug 角番効果の不在検証

## Step 1: セクション別 corner_bucket 分布
（テーブル）

## Step 2: 物理配置の記述統計
（テーブル）

## Step 3: corner_bucket 別 h_jug vs v_jug
（1テーブル）

## Step 4: 機種構成比較
（segment別テーブル）

## Step 5: 残差法再検定
（1テーブル）

## 判定
- 仮説D（物理的可視性）: [支持/棄却/不明]
- 仮説E（セクションサイズ差）: [支持/棄却/不明]
- 仮説F（機種構成差）: [支持/棄却/不明]
```

### CSV 出力
`tmp/mitoya_phase10h_vjug_corner_absence/` 配下に:
- `step1_corner_distribution.csv`
- `step2_layout_stats.csv`
- `step3_corner_comparison.csv`
- `step4_machine_composition.csv`
- `step5_residual_corner.csv`

## 出力制約

- テーブル出力は `render_markdown_table()` を使用する（**`to_markdown()` 禁止**）
- 空セグメントはスキップし NaN が出ないこと
- 日本語を含む関数を編集する場合は関数全体を置き換えること（行単位パッチ禁止）
- ファイルエンコーディングは UTF-8（BOMなし）

## テスト要件

`ml/tests/test_mitoya_phase10h_vjug_corner_absence.py` に以下を含める。

### テストデータ生成

ダミー DataFrame を生成する fixture `dummy_frame()`:

- 日付: `20260101`〜`20260110` の期間（YYYYMMDD形式）
- machine_number: 501〜560（水平）+ 625〜650（垂直）
- machine_name: ジャグラー機種2種以上（"マイジャグラーV", "ファンキージャグラー2" 等）
- section: "501-522"（水平）, "624-640"（垂直）
- x, y: 水平は y 一定、垂直は x 一定
- rank_from_aisle: 1〜15
- games: 全行 1500 以上
- diff: h_jug の corner1 に高い値を設定（角番効果テスト用）

### テスト項目

```python
def test_step1_has_both_orientations(dummy_frame):
    """build_step1_corner_distribution に horizontal/vertical 両方が含まれる"""

def test_step2_layout_segments(dummy_frame):
    """build_step2_layout_stats に h_jug/v_jug が含まれる"""

def test_step3_all_corner_buckets(dummy_frame):
    """build_step3_corner_comparison に全 corner_bucket が含まれる"""

def test_step4_top10_per_segment(dummy_frame):
    """build_step4_machine_composition が各セグメント最大10行を返す"""

def test_step5_raw_and_residual(dummy_frame):
    """build_step5_residual_corner に raw と residual 両方のnoteが含まれる"""

def test_generate_report_creates_files(dummy_frame, tmp_path):
    """report.md と 5 CSV が生成される"""
```

## 実行確認

```bash
cd C:\Users\apto117\Documents\pachinko-analyzer\src\2026project
python -m pytest ml/tests/test_mitoya_phase10h_vjug_corner_absence.py -v
python -m eda.mitoya_phase10h_vjug_corner_absence
```

エラーなく report.md と 5 CSV が生成されること。
