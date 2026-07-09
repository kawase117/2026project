# Phase10f: h_nonjug debut→mature 逆転パターンの生存バイアス検証

## 目的

Phase10e で h_nonjug セグメントに debut avg_diff=-89.9 → mature avg_diff=+107.9 という逆転が見つかった。
以下3仮説のどれが正しいかを分離する。

- **仮説A（ホール戦略）**: 新台は低設定で導入し、定着後に設定を上げる
- **仮説B（生存バイアス）**: 好成績の機種だけが長く残り、mature に生き残る
- **仮説C（X_DDS限定）**: X_DDS日だけ debut 台に高設定を入れている（debut×X_DDS 交互作用 F=7.6）

検証方法: **同一機種を時系列で追跡し、debut_days vs diff の推移を見る**。

## 前提

### 既存コード依存

`eda/mitoya_phase10e_xdds_kakuban_debut.py` の枠組みを踏襲する。

- `eda/mitoya_prompt_common.py` の関数群をそのまま流用する：
  - `load_mitoya_frame(join_layout=True)` — DB読み込み + machine_layout JOIN
  - `add_event_category(df)` — `is_xdds_day` 列（0/1）を含む event_category を付与
  - `add_debut_phase(df)` — `debut_days`（int）と `debut_phase`（str）と `is_moved`（bool）を付与
  - `render_markdown_table(df)` — テーブル出力（**to_markdown() 禁止**）
  - DB パスは `DB_PATH` 定数を使用
- `eda/mitoya_phase10_segment_validation.py`:
  - `_prepare_frame(df)` — games>=1000フィルタ、orientation/jug_flag/corner_bucket付与
  - `_segment_frame(work, segment)` — セグメントフィルタ

### 呼び出し順序の固定（厳守）

1. `add_debut_phase(df)` を先に呼ぶ（`machine_name` が生きている状態で）
2. `add_event_category(work)` を呼ぶ
3. `phase10._prepare_frame(work)` を呼ぶ
4. `is_moved` 列（bool）で moved を除外する

この順序を入れ替えてはならない。`phase10._prepare_frame` が `machine_name` を空文字化するため。

### 対象セグメント

h_nonjug を主対象とする。比較用に h_jug も出力する（h_jug は debut=+136 → mature=+14 で通常の減衰パターン）。

## ファイル構成

| ファイル | 用途 |
|---------|------|
| `eda/mitoya_phase10f_debut_timeseries.py` | 分析メイン |
| `ml/tests/test_mitoya_phase10f_debut_timeseries.py` | テスト |

## 分析ステップ

### Step 1: 同一機種コホート追跡 — `build_step1_cohort_tracking(work)`

同一 `machine_name` × `section` の組み合わせごとに、debut_days を 30日 bin（0-30, 31-60, 61-90, 91-120, 121+）に分割し、各 bin の avg_diff / plus_rate / n を算出する。

- h_nonjug と h_jug それぞれで算出
- **同一機種を追跡**するため、machine_name ごとに時系列を追う（異なる machine_name 間の比較ではない）
- moved は除外済み（`is_moved` 列で判定）
- pre_existing は debut_days=None のため除外

bin 定義:
```python
DEBUT_BIN_EDGES = [0, 30, 60, 90, 120, float("inf")]
DEBUT_BIN_LABELS = ["0-30", "31-60", "61-90", "91-120", "121+"]
```

出力:
```
segment  | debut_bin | n    | avg_diff | plus_rate | n_machines
h_nonjug | 0-30      | ...  | ...      | ...       | ...
h_nonjug | 31-60     | ...  | ...      | ...       | ...
...
h_jug    | 0-30      | ...  | ...      | ...       | ...
...
```

`n_machines` = そのbinに含まれるユニーク machine_name 数。

### Step 2: 生存バイアス検証 — `build_step2_survival_bias(work)`

**核心**: mature（91日+）まで生き残った機種と、早期撤去された機種の debut 期（0-30日）での diff を比較する。

定義:
- **survived**: debut_days の最大値が 91 以上の machine_name（mature まで到達）
- **removed**: debut_days の最大値が 90 以下の machine_name（growth 以前に撤去）

各グループの debut 期（debut_days 0-30）の avg_diff を比較する。

出力:
```
segment  | group    | debut_avg_diff | debut_n | max_days_median | n_machines
h_nonjug | survived | ...            | ...     | ...             | ...
h_nonjug | removed  | ...            | ...     | ...             | ...
h_jug    | survived | ...            | ...     | ...             | ...
h_jug    | removed  | ...            | ...     | ...             | ...
```

**判定ロジック**:
- survived の debut_avg_diff ≈ removed の debut_avg_diff → 生存バイアスなし（仮説A支持）
- survived の debut_avg_diff > removed の debut_avg_diff → 生存バイアスあり（仮説B支持）
- Mann-Whitney U 検定で有意差を検定する

追加出力:
```
segment  | u_stat  | p_value | survived_debut_avg | removed_debut_avg | diff
h_nonjug | ...     | ...     | ...                | ...               | ...
h_jug    | ...     | ...     | ...                | ...               | ...
```

### Step 3: X_DDS限定 debut プレミアム — `build_step3_xdds_debut_premium(work)`

仮説C の検証: X_DDS日限定で debut_bin 別の avg_diff を算出し、非イベント日と比較する。

- **母集団**: X_DDS日 + 非イベント日のみ。ゾロ目日・月末・強ゾロ目は母集団から除外する

出力:
```
segment  | scope       | debut_bin | n    | avg_diff | plus_rate
h_nonjug | X_DDS       | 0-30      | ...  | ...      | ...
h_nonjug | X_DDS       | 31-60     | ...  | ...      | ...
...
h_nonjug | 非イベント日 | 0-30      | ...  | ...      | ...
...
h_jug    | X_DDS       | 0-30      | ...  | ...      | ...
...
```

scope の許可値: "X_DDS" と "非イベント日" の2値のみ。

### Step 4: 機種別 debut→mature 推移ランキング — `build_step4_machine_ranking(work)`

h_nonjug の各 machine_name について、debut 期 avg_diff と mature 期 avg_diff を算出し、mature - debut の差分でランキング。

出力:
```
machine_name | debut_avg_diff | debut_n | mature_avg_diff | mature_n | improvement | rank
...          | ...            | ...     | ...             | ...      | ...         | ...
```

- debut_n >= 30 かつ mature_n >= 30 の機種のみ出力
- improvement = mature_avg_diff - debut_avg_diff
- rank は improvement 降順

## 出力

### Markdown レポート
`tmp/mitoya_phase10f_debut_timeseries/report.md`

見出し構造:
```markdown
# Phase10f: h_nonjug debut→mature 逆転の生存バイアス検証

## Step 1: コホート追跡
（segment別テーブル）

## Step 2: 生存バイアス検証
（比較テーブル + Mann-Whitney結果）

## Step 3: X_DDS限定 debut プレミアム
（segment × scope × debut_bin テーブル）

## Step 4: 機種別ランキング
（h_nonjug のみ）

## 判定
- 仮説A（ホール戦略）: [支持/棄却/不明]
- 仮説B（生存バイアス）: [支持/棄却/不明]
- 仮説C（X_DDS限定）: [支持/棄却/不明]
```

### CSV 出力
`tmp/mitoya_phase10f_debut_timeseries/` 配下に:
- `step1_cohort_tracking.csv`
- `step2_survival_bias.csv`
- `step2_survival_mwu.csv`
- `step3_xdds_debut_premium.csv`
- `step4_machine_ranking.csv`

## 出力制約

- テーブル出力は `render_markdown_table()` を使用する（**`to_markdown()` 禁止**）
- 空セグメントはスキップし NaN が出ないこと
- 日本語を含む関数を編集する場合は関数全体を置き換えること（行単位パッチ禁止）
- ファイルエンコーディングは UTF-8（BOMなし）

## テスト要件

`ml/tests/test_mitoya_phase10f_debut_timeseries.py` に以下を含める。

### テストデータ生成

ダミー DataFrame を生成する fixture `dummy_frame()`:

- 日付: `20260101`〜`20260401` の期間（YYYYMMDD形式）。debut→growth→mature を生成するために最低 100日必要
- dd=7（X_DDS日）と dd=3（非イベント日）を含めること
- machine_number: 501〜540 の範囲
- machine_name: 非ジャグラー機種を3種以上。うち1種は途中で撤去（30日で消える）、1種は mature まで残る
- section: "501-522"（水平セクション）
- x, y: 水平セクション用に y が一定
- rank_from_aisle: 1〜15
- games: 全行 1500 以上
- diff: survived 機種は debut 期に低め、mature 期に高めに設定（生存バイアスの検出テスト用）

### テスト項目

```python
def test_step1_cohort_has_all_bins(dummy_frame):
    """build_step1_cohort_tracking が全 debut_bin を含む"""

def test_step2_survival_groups(dummy_frame):
    """build_step2_survival_bias が survived/removed 両グループを返す"""

def test_step2_mwu_result(dummy_frame):
    """Mann-Whitney U 検定結果が返る"""

def test_step3_scope_values(dummy_frame):
    """scope が X_DDS と 非イベント日 の2値のみ"""

def test_step4_ranking_threshold(dummy_frame):
    """debut_n >= 30 かつ mature_n >= 30 のフィルタが機能する"""

def test_generate_report_creates_files(dummy_frame, tmp_path):
    """report.md と 5 CSV が生成される"""
```

## 実行確認

```bash
cd C:\Users\apto117\Documents\pachinko-analyzer\src\2026project
python -m pytest ml/tests/test_mitoya_phase10f_debut_timeseries.py -v
python -m eda.mitoya_phase10f_debut_timeseries
```

エラーなく report.md と 5 CSV が生成されること。
