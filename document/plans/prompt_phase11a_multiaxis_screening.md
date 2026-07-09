# Phase11a: DD full spectrum・曜日・イベント日×曜日・ゾロ目の4軸スクリーニング

## 目的

Phase 10 で確立した 5 セグメント分割の上で、未検証の 4 軸を 3 粒度（ホール全体 → セグメント別 → 複合セグメント別）で系統的にスクリーニングする。

対象軸:
1. **DD full spectrum（1-31個別）** — non-X_DDS の DD 内部構造。蒲田7では DD18-23 のトラフゾーン発見が重要だった
2. **曜日（day_of_week）** — Phase 4 で却下されたがセグメント別では浮かぶ可能性
3. **イベント日×曜日** — 蒲田7ではイベント日×土曜が逆効果だった
4. **ゾロ目（is_zorome）** — Phase 3 で脱落だがセグメント別では浮かぶ可能性

## 前提

### 既存コード依存

- `eda/mitoya_prompt_common.py` の関数群をそのまま流用する：
  - `load_mitoya_frame(join_layout=True)` — DB読み込み + machine_layout JOIN
  - `add_event_category(df)` — `is_xdds_day`, `event_category`, `dd`, `mm` 列を付与
  - `render_markdown_table(df)` — テーブル出力（**to_markdown() 禁止**）
  - `kw_epsilon_squared(statistic, n_groups, n_rows)` — 効果量計算
  - DB パスは `DB_PATH` 定数を使用
  - 定数: `X_DDS`, `EVENT_CATEGORY_ORDER`, `WEEKDAY_ORDER`
- `eda/mitoya_phase10_segment_validation.py`:
  - `_prepare_frame(df)` — games>=1000フィルタ、orientation/jug_flag/corner_bucket付与
  - `_segment_frame(work, segment)` — セグメントフィルタ
  - `_kruskal_summary(frame, group_col, order=...)` — Kruskal-Wallis + epsilon^2
  - `_group_stats(frame, group_col, order=...)` — n/avg_diff/plus_rate

### 呼び出し順序の固定（厳守）

本分析では `add_debut_phase` は不要。ただし呼ぶ場合は `_prepare_frame` の前に呼ぶこと。

1. `add_event_category(df)` を呼ぶ
2. `phase10._prepare_frame(work)` を呼ぶ（games>=1000フィルタ等）

### セグメント定義

```python
SEGMENT_ORDER = ["h_jug", "h_nonjug", "v_jug", "v_nonjug", "mixed_805"]
```

### 変数定義

```python
DD_ORDER = [str(i) for i in range(1, 32)]  # "1"〜"31"
WEEKDAY_ORDER = ["月", "火", "水", "木", "金", "土", "日"]
ZOROME_ORDER = ["0", "1"]  # 台番号末尾ゾロ目（machine_detailed_results.is_zorome）
EVENT_CATEGORY_ORDER = ["X_DDS", "ゾロ目日", "強ゾロ目", "月末", "非イベント日"]
```

### ゾロ目の定義（重要）

ここでの is_zorome は **台番号末尾ゾロ目**（台番号の下2桁が同じ: 00, 11, 22, ..., 99）であり、日付ゾロ目（11日/22日）ではない。`machine_detailed_results.is_zorome` 列を使用する。日付ゾロ目は `event_category` の「ゾロ目日」として既に扱われている。

### 曜日の取得

`day_of_week` 列が DataFrame にない場合、`date_dt.dt.day_name()` から日本語曜日に変換する。マッピング:
```python
DOW_MAP = {"Monday": "月", "Tuesday": "火", "Wednesday": "水",
           "Thursday": "木", "Friday": "金", "Saturday": "土", "Sunday": "日"}
```

## ファイル構成

| ファイル | 用途 |
|---------|------|
| `eda/mitoya_phase11a_multiaxis_screening.py` | 分析メイン |
| `ml/tests/test_mitoya_phase11a_multiaxis_screening.py` | テスト |

## 分析ステップ

### 共通構造

全4軸について、以下の3粒度で KW 検定 + 基本統計を実施する:

- **Grain 1: ホール全体** (grain="hall") — 全台を対象。segment="" / event_scope="" で出力
- **Grain 2: セグメント別** (grain="segment") — 5セグメント各々。event_scope="" で出力
- **Grain 3: セグメント × event_scope** (grain="composite") — 5セグメント × event_scope（"X_DDS" / "非イベント日" の2水準）

Grain 3 の event_scope フィルタ: "X_DDS" → event_category=="X_DDS" の行のみ、"非イベント日" → event_category=="非イベント日" の行のみ。ゾロ目日・月末・強ゾロ目は母集団から除外する。

---

### Step 1: DD full spectrum KW — `build_step1_dd_kw(work)`

dd 列（1-31、文字列化）を group_col として KW 検定。3粒度。

出力:
```
grain     | segment   | event_scope | kw_stat | p_value | epsilon_sq | n_groups | n
hall      |           |             | ...     | ...     | ...        | ...      | ...
segment   | h_jug     |             | ...     | ...     | ...        | ...      | ...
segment   | h_nonjug  |             | ...     | ...     | ...        | ...      | ...
...
composite | h_jug     | X_DDS       | ...     | ...     | ...        | ...      | ...
composite | h_jug     | 非イベント日 | ...     | ...     | ...        | ...      | ...
...
```

### Step 2: DD full spectrum 基本統計 — `build_step2_dd_stats(work)`

dd 列（1-31）を group_col として n / avg_diff / plus_rate を算出。3粒度。

出力:
```
grain     | segment   | event_scope | dd | n    | avg_diff | plus_rate
hall      |           |             | 1  | ...  | ...      | ...
hall      |           |             | 2  | ...  | ...      | ...
...（31行 × 各粒度）
```

### Step 3: 曜日 KW — `build_step3_weekday_kw(work)`

day_of_week を group_col として KW 検定。3粒度。カラム構成は Step 1 と同じ。

### Step 4: 曜日 基本統計 — `build_step4_weekday_stats(work)`

day_of_week を group_col として n / avg_diff / plus_rate。3粒度。

出力:
```
grain     | segment   | event_scope | day_of_week | n | avg_diff | plus_rate
```

### Step 5: イベント日×曜日 クロス統計 — `build_step5_event_weekday_cross(work)`

event_category × day_of_week のクロス集計。セグメント別 + ホール全体。

出力:
```
segment   | event_category | day_of_week | n    | avg_diff | plus_rate
          | X_DDS          | 月          | ...  | ...      | ...
          | X_DDS          | 火          | ...  | ...      | ...
...
h_jug     | X_DDS          | 月          | ...  | ...      | ...
...
h_jug     | 非イベント日    | 月          | ...  | ...      | ...
...
```

- event_category は EVENT_CATEGORY_ORDER の全5値を出力する（ゾロ目日・月末・強ゾロ目も含む）
- ホール全体は segment="" で出力

### Step 6: イベント日×曜日 2-way ANOVA — `build_step6_event_weekday_anova(work)`

各セグメント + ホール全体で `diff ~ C(is_xdds_day) + C(day_of_week) + C(is_xdds_day):C(day_of_week)` を検定。

- **母集団**: X_DDS日 + 非イベント日のみ。ゾロ目日・月末・強ゾロ目は母集団から除外する
- 各セル（is_xdds × day_of_week）に n≥10 がなければスキップ
- `statsmodels.formula.api.ols` と `statsmodels.stats.anova.anova_lm(type=2)` を使用

出力:
```
segment   | source                              | df  | sum_sq | F     | p_value | n
          | C(is_xdds_day)                      | ... | ...    | ...   | ...     | ...
          | C(day_of_week)                      | ... | ...    | ...   | ...     | ...
          | C(is_xdds_day):C(day_of_week)       | ... | ...    | ...   | ...     | ...
          | Residual                            | ... | ...    | ...   | ...     | ...
h_jug     | ...                                 | ... | ...    | ...   | ...     | ...
...
```

ホール全体は segment="" で出力。

### Step 7: ゾロ目 KW — `build_step7_zorome_kw(work)`

is_zorome（台番号末尾ゾロ目、0/1 を文字列化）を group_col として KW 検定。3粒度。

is_zorome 列の確保:
```python
if "is_zorome" not in work.columns:
    mn = pd.to_numeric(work["machine_number"], errors="coerce")
    work["is_zorome"] = ((mn % 100 // 10) == (mn % 10)).astype(int)
```

### Step 8: ゾロ目 基本統計 — `build_step8_zorome_stats(work)`

is_zorome を group_col として n / avg_diff / plus_rate。3粒度。

出力:
```
grain     | segment   | event_scope | is_zorome | n | avg_diff | plus_rate
```

### Step 9: サマリテーブル — `build_step9_summary(all_kw_results, anova_results)`

全4軸 × 全粒度の KW p値を 1 テーブルにまとめる。

出力:
```
axis              | grain     | segment   | event_scope | p_value | epsilon_sq | verdict
dd_spectrum       | hall      |           |             | ...     | ...        | ◎/○/△/✗
dd_spectrum       | segment   | h_jug     |             | ...     | ...        | ...
...
day_of_week       | hall      |           |             | ...     | ...        | ...
...
is_zorome         | hall      |           |             | ...     | ...        | ...
...
event_x_weekday   | hall      |           |             | ...     | ...        | ...（交互作用のp）
event_x_weekday   | segment   | h_jug     |             | ...     | ...        | ...
...
```

verdict 判定:
- p < 0.001 かつ ε² ≥ 0.003: ◎有望
- p < 0.01: ○要検討
- p < 0.05: △境界的
- p ≥ 0.05: ✗脱落

event_x_weekday の verdict は ANOVA 交互作用項の p_value を使用。epsilon_sq は空欄。

## 出力

### Markdown レポート
`tmp/mitoya_phase11a_multiaxis_screening/report.md`

見出し構造:
```markdown
# Phase11a: 4軸スクリーニング

## Axis 1: DD full spectrum
### KW検定（3粒度）
### DD別統計（有意な粒度のみ展開）

## Axis 2: 曜日
### KW検定（3粒度）
### 曜日別統計（有意な粒度のみ展開）

## Axis 3: イベント日×曜日
### クロス統計
### 2-way ANOVA

## Axis 4: ゾロ目（台番号末尾）
### KW検定（3粒度）
### ゾロ目別統計（有意な粒度のみ展開）

## Summary
（サマリテーブル + 主要 finding）
```

レポートの基本統計テーブルは、KW で p < 0.05 だった粒度のみ展開する。p ≥ 0.05 の粒度は「KW 非有意のため省略」と1行記載するのみ。

### CSV 出力
`tmp/mitoya_phase11a_multiaxis_screening/` 配下に:
- `step1_dd_kw.csv`
- `step2_dd_stats.csv`
- `step3_weekday_kw.csv`
- `step4_weekday_stats.csv`
- `step5_event_weekday_cross.csv`
- `step6_event_weekday_anova.csv`
- `step7_zorome_kw.csv`
- `step8_zorome_stats.csv`
- `step9_summary.csv`

## 出力制約

- テーブル出力は `render_markdown_table()` を使用する（**`to_markdown()` 禁止**）
- 空セグメント・空セルはスキップし NaN が出ないこと
- 各 Step の DataFrame に grain / segment / event_scope 列を必ず含めること
- 日本語を含む関数を編集する場合は関数全体を置き換えること（行単位パッチ禁止）
- ファイルエンコーディングは UTF-8（BOMなし）

## テスト要件

`ml/tests/test_mitoya_phase11a_multiaxis_screening.py` に以下を含める。

### テストデータ生成

ダミー DataFrame を生成する fixture `dummy_frame()`:

- 日付: `20260101`〜`20260131` の31日間（YYYYMMDD形式）。DD 1-31 全てカバー
- 曜日が全7種含まれること（31日間なら自動的に満たす）
- dd=7（X_DDS日）と dd=3（非イベント日）を含めること
- machine_number: 501〜560（水平）+ 701〜720（垂直）+ 805〜815（mixed_805）
  - 台番号末尾ゾロ目（例: 511, 522）を含めること
- machine_name: ジャグラー機種（"マイジャグラーV"等）と非ジャグラー機種を混在
- section: "501-522", "624-640"（水平）, "712-722"（垂直）, "805-815"（mixed_805）
- x, y: 水平は y 一定、垂直は x 一定
- rank_from_aisle: 1〜15
- games: 全行 1500 以上
- diff: ランダムまたは固定値
- is_zorome: 台番号末尾ゾロ目で算出（テストデータに台511, 522等を含める）

### テスト項目

```python
def test_step1_dd_kw_three_grains(dummy_frame):
    """build_step1_dd_kw が hall/segment/composite の3粒度を返す"""

def test_step2_dd_stats_31_values(dummy_frame):
    """build_step2_dd_stats が DD 1-31 の行を含む（hall粒度）"""

def test_step3_weekday_kw_seven_groups(dummy_frame):
    """build_step3_weekday_kw の n_groups が 7"""

def test_step5_event_weekday_cross_structure(dummy_frame):
    """build_step5_event_weekday_cross が event_category × day_of_week の行を返す"""

def test_step6_anova_interaction_term(dummy_frame):
    """build_step6_event_weekday_anova に交互作用項が含まれる"""

def test_step7_zorome_kw_binary(dummy_frame):
    """build_step7_zorome_kw の n_groups が 2"""

def test_step9_summary_all_axes(dummy_frame):
    """build_step9_summary に dd_spectrum/day_of_week/is_zorome/event_x_weekday が含まれる"""

def test_generate_report_creates_files(dummy_frame, tmp_path):
    """report.md と 9 CSV が生成される"""
```

## 実行確認

```bash
cd C:\Users\apto117\Documents\pachinko-analyzer\src\2026project
python -m pytest ml/tests/test_mitoya_phase11a_multiaxis_screening.py -v
python -m eda.mitoya_phase11a_multiaxis_screening
```

エラーなく report.md と 9 CSV が生成されること。各粒度のテーブルにセグメント行が埋まっていること。
