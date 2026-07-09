# Phase11b: レジーム分割による角番効果・debut効果の耐久性検証

## 目的

Phase 10 で確立した角番効果と debut_phase 効果が、機種入替（レジーム変化）の前後で維持されるかを検証する。蒲田7では 2F の末尾法則が stability=0% で全面格下げされた前例がある。

検証対象:
1. **角番効果のレジーム安定性** — h_jug corner1 の構造的プレミアム（+405）は機種入替後も維持されるか
2. **debut効果のレジーム安定性** — h_nonjug の生存バイアスパターンは前期/後期で一貫しているか

## 前提

### 既存コード依存

- `eda/mitoya_prompt_common.py` の関数群をそのまま流用する：
  - `load_mitoya_frame(join_layout=True)` — DB読み込み + machine_layout JOIN
  - `add_event_category(df)` — event_category を付与
  - `add_debut_phase(df)` — debut_days / debut_phase / is_moved を付与
  - `render_markdown_table(df)` — テーブル出力（**to_markdown() 禁止**）
  - `kw_epsilon_squared(statistic, n_groups, n_rows)` — 効果量計算
  - DB パスは `DB_PATH` 定数を使用
- `eda/mitoya_phase10_segment_validation.py`:
  - `_prepare_frame(df)` — games>=1000フィルタ、orientation/jug_flag/corner_bucket付与
  - `_segment_frame(work, segment)` — セグメントフィルタ
  - `_kruskal_summary(frame, group_col, order=...)` — Kruskal-Wallis + epsilon^2
  - `_group_stats(frame, group_col, order=...)` — n/avg_diff/plus_rate

### 呼び出し順序の固定（厳守）

1. `add_debut_phase(df)` を先に呼ぶ（`machine_name` が生きている状態で）
2. `add_event_category(work)` を呼ぶ
3. `phase10._prepare_frame(work)` を呼ぶ
4. `is_moved` 列（bool）で moved を除外する

**重要**: レジーム境界検出は `_prepare_frame` の前に実施すること。`_prepare_frame` 通過後は `machine_name` が空文字化される可能性がある。

### セグメント定義

```python
SEGMENT_ORDER = ["h_jug", "h_nonjug", "v_jug", "v_nonjug", "mixed_805"]
CORNER_BUCKET_ORDER = ["corner1", "corner2-4", "corner5-9", "corner10+"]
DEBUT_PHASE_ORDER = ["pre_existing", "debut", "growth", "mature"]
```

## ファイル構成

| ファイル | 用途 |
|---------|------|
| `eda/mitoya_phase11b_regime_durability.py` | 分析メイン |
| `ml/tests/test_mitoya_phase11b_regime_durability.py` | テスト |

## レジーム境界の定義

### 方法: machine_name 変化数が最大の日

DB から machine_name の変化を検出し、「machine_name が前日と異なる台番号の数」を日ごとにカウントする。最大の日をレジーム境界とし、前半（regime="pre"）と後半（regime="post"）に分割する。

```python
def detect_regime_boundary(work: pd.DataFrame) -> pd.Timestamp:
    daily = work.sort_values(["machine_number", "date_dt"])
    daily["prev_name"] = daily.groupby("machine_number")["machine_name"].shift(1)
    daily["name_changed"] = (
        daily["machine_name"].ne(daily["prev_name"]) & daily["prev_name"].notna()
    ).astype(int)
    change_counts = daily.groupby("date_dt")["name_changed"].sum()
    return change_counts.idxmax()
```

レジーム境界検出は `_prepare_frame` の**前**に、元の `machine_name` を使って実施する。検出した boundary_date を `_prepare_frame` 後の work に `regime` 列として付与する。

### フォールバック

machine_name 変化がない（全日 change=0）場合は、日付の中央値で分割する。

## 分析ステップ

### Step 1: レジーム境界の検出 — `detect_regime_boundary(work)`

レジーム境界日と前後の日数・行数を出力する。

出力:
```
boundary_date | pre_days | post_days | pre_n | post_n | max_changes
20250715      | 195      | 343       | ...   | ...    | 42
```

### Step 2: 角番効果のレジーム安定性 — `build_step2_corner_regime(work)`

各セグメントについて、regime="pre" と regime="post" それぞれで corner_bucket 別の avg_diff / plus_rate + KW 検定を実施。

出力（基本統計）:
```
segment | regime | corner_bucket | n    | avg_diff | plus_rate
h_jug   | pre    | corner1       | ...  | ...      | ...
h_jug   | pre    | corner2-4     | ...  | ...      | ...
...
h_jug   | post   | corner1       | ...  | ...      | ...
...
```

出力（KW検定）:
```
segment | regime | kw_stat | p_value | epsilon_sq | n_groups | n
h_jug   | pre    | ...     | ...     | ...        | ...      | ...
h_jug   | post   | ...     | ...     | ...        | ...      | ...
...
```

### Step 3: 角番ランキングの Spearman 相関 — `build_step3_corner_rank_correlation(corner_stats)`

pre と post で corner_bucket 別の avg_diff ランキングの Spearman ρ を算出。ρ ≈ 1.0 なら角番の序列が安定。

出力:
```
segment   | spearman_rho | p_value | n_groups | pre_top1       | post_top1
h_jug     | ...          | ...     | 4        | corner1        | corner1
h_nonjug  | ...          | ...     | 4        | corner2-4      | corner1
...
```

`pre_top1` / `post_top1` は各期間の avg_diff 最大の corner_bucket。

### Step 4: debut_phase 効果のレジーム安定性 — `build_step4_debut_regime(work)`

各セグメントについて、regime="pre" と regime="post" それぞれで debut_phase 別の avg_diff / plus_rate + KW 検定。

出力（基本統計）:
```
segment  | regime | debut_phase  | n    | avg_diff | plus_rate
h_nonjug | pre    | pre_existing | ...  | ...      | ...
h_nonjug | pre    | debut        | ...  | ...      | ...
...
h_nonjug | post   | pre_existing | ...  | ...      | ...
...
```

出力（KW検定）:
```
segment  | regime | kw_stat | p_value | epsilon_sq | n_groups | n
h_nonjug | pre    | ...     | ...     | ...        | ...      | ...
h_nonjug | post   | ...     | ...     | ...        | ...      | ...
...
```

### Step 5: debut ランキングの Spearman 相関 — `build_step5_debut_rank_correlation(debut_stats)`

pre と post で debut_phase 別の avg_diff ランキングの Spearman ρ を算出。

出力:
```
segment   | spearman_rho | p_value | n_groups | pre_best_phase | post_best_phase
h_nonjug  | ...          | ...     | 4        | mature         | mature
...
```

### Step 6: 安定性サマリ — `build_step6_stability_summary(corner_corr, debut_corr, corner_kw, debut_kw)`

全セグメントの角番/debut のレジーム安定性を1テーブルに。

出力:
```
segment   | axis    | pre_p  | post_p | rank_rho | rank_p  | top1_stable | verdict
h_jug     | corner  | <0.001 | <0.001 | 1.000    | 0.000   | True        | ✅安定
h_jug     | debut   | 0.036  | ...    | ...      | ...     | ...         | ...
h_nonjug  | corner  | ...    | ...    | ...      | ...     | ...         | ...
h_nonjug  | debut   | ...    | ...    | ...      | ...     | ...         | ...
...
```

verdict 判定:
- pre/post 両方 p<0.05 かつ rank_rho > 0.8 かつ top1_stable=True: ✅安定
- pre/post 片方のみ p<0.05: ⚠️不安定
- pre/post 両方 p≥0.05: ✗効果なし
- rank_rho < 0.5: ❌崩壊

## 出力

### Markdown レポート
`tmp/mitoya_phase11b_regime_durability/report.md`

見出し構造:
```markdown
# Phase11b: レジーム分割耐久性検証

## Step 1: レジーム境界
（境界日、前後の行数）

## Step 2: 角番効果のレジーム安定性
### 基本統計（segment別、regime別）
### KW検定（segment別、regime別）

## Step 3: 角番ランキング Spearman相関
（1テーブル）

## Step 4: debut効果のレジーム安定性
### 基本統計（segment別、regime別）
### KW検定（segment別、regime別）

## Step 5: debutランキング Spearman相関
（1テーブル）

## Step 6: 安定性サマリ
（1テーブル + verdict）
```

### CSV 出力
`tmp/mitoya_phase11b_regime_durability/` 配下に:
- `step1_regime_boundary.csv`
- `step2_corner_regime_stats.csv`
- `step2_corner_regime_kw.csv`
- `step3_corner_rank_correlation.csv`
- `step4_debut_regime_stats.csv`
- `step4_debut_regime_kw.csv`
- `step5_debut_rank_correlation.csv`
- `step6_stability_summary.csv`

## 出力制約

- テーブル出力は `render_markdown_table()` を使用する（**`to_markdown()` 禁止**）
- 空セグメントはスキップし NaN が出ないこと
- 日本語を含む関数を編集する場合は関数全体を置き換えること（行単位パッチ禁止）
- ファイルエンコーディングは UTF-8（BOMなし）

## テスト要件

`ml/tests/test_mitoya_phase11b_regime_durability.py` に以下を含める。

### テストデータ生成

ダミー DataFrame を生成する fixture `dummy_frame()`:

- 日付: `20250101`〜`20250401` の期間（YYYYMMDD形式）。レジーム分割に十分な期間
- machine_number: 641〜660（h_jug用）+ 501〜520（h_nonjug用）
- machine_name: 
  - 台641〜650: 前半は "マイジャグラーV"、`20250201` 以降の一部台で "ファンキージャグラー2" に変更（レジーム境界生成用）
  - 台501〜520: 非ジャグラー機種
- section: "641-657"（h_jug）, "501-522"（h_nonjug）
- x, y: 水平セクション用に y 一定
- rank_from_aisle: 1〜15
- games: 全行 1500 以上
- diff: corner1 の台に高めの値を設定（角番効果テスト用）

### テスト項目

```python
def test_detect_regime_boundary(dummy_frame):
    """detect_regime_boundary が Timestamp を返す"""

def test_step2_corner_both_regimes(dummy_frame):
    """build_step2_corner_regime が pre/post 両方の行を含む"""

def test_step3_corner_rank_rho(dummy_frame):
    """build_step3_corner_rank_correlation が各セグメントの rho を返す"""

def test_step4_debut_both_regimes(dummy_frame):
    """build_step4_debut_regime が pre/post 両方の行を含む"""

def test_step5_debut_rank_rho(dummy_frame):
    """build_step5_debut_rank_correlation が各セグメントの rho を返す"""

def test_step6_verdict_values(dummy_frame):
    """build_step6_stability_summary の verdict が定義済みの値のみ"""

def test_generate_report_creates_files(dummy_frame, tmp_path):
    """report.md と 8 CSV が生成される"""
```

## 実行確認

```bash
cd C:\Users\apto117\Documents\pachinko-analyzer\src\2026project
python -m pytest ml/tests/test_mitoya_phase11b_regime_durability.py -v
python -m eda.mitoya_phase11b_regime_durability
```

エラーなく report.md と 8 CSV が生成されること。
