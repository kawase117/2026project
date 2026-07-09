# 蒲田7: 経過日数3フェーズモデルの生存バイアス検証

## 目的

蒲田7の経過日数3フェーズモデル（回収-367→テコ入れ+107→看板維持+110）は全9ホールで方向が再現されたが、みとやPhase10fで h_nonjug の debut→mature 逆転が生存バイアスと判明した（survived debut=-16.7 vs removed debut=-179.9, MWU p=0.003）。蒲田7でも同じバイアスが混入しているかを検証する。

特に 2F_N（stability=0%, 全台入替済み）は生存バイアスのリスクが最も高い。

## 前提

### 既存コード依存

- `eda/core.py`:
  - `load_hall_df("蒲田7")` — DB読み込み
  - `compute_debut_features(df)` — debut_days / debut_phase を付与
  - `HALL_DBS` — DBパス定数
- `eda/kamata7_debut_deep_dive.py`:
  - `DEBUT_PHASE_LABELS`, `SEGMENT_A_KEYWORDS` — 定数
  - セグメント分類ロジック（A/N判定、2F/3F×L/R分割）
- 座標CSV: `Heatmap/2F_floor_coordinates_kamata7.csv`, `Heatmap/3F_floor_coordinates_kamata7.csv`
- DB: `db/マルハンメガシティ2000-蒲田7.db`

### セグメント定義

蒲田7の6セグメント: 2F_L_N, 2F_R_N, 3F_L_A, 3F_L_N, 3F_R_A, 3F_R_N。
A/N判定は machine_name に SEGMENT_A_KEYWORDS が含まれるかで判定。
L/R判定は座標CSVのx座標ベース。

### debut_phase 定義（蒲田7）

```python
DEBUT_PHASE_LABELS = ["1-14日", "15-60日", "61-180日", "181日+"]
```

- `定番(pre)`: データ開始時点で既設の台（debut_days なし）
- `1-14日`: 導入直後
- `15-60日`: 回収期後半
- `61-180日`: テコ入れ期
- `181日+`: 看板維持期

### 鉄台定義

台番号2026 が代表的鉄台。`pos_rate >= 60%` or `median >= 0` で鉄台を特定。

## ファイル構成

| ファイル | 用途 |
|---------|------|
| `eda/kamata7_survival_bias_verification.py` | 分析メイン |
| `ml/tests/test_kamata7_survival_bias_verification.py` | テスト |

## 分析ステップ

### Step 1: survived / removed 分類

**定義**:
- **survived**: debut_days の最大値が 181 以上の machine_name（看板維持期まで到達）
- **removed**: debut_days の最大値が 180 以下 **かつ** 最終出現日が観測期間末日の30日以上前の machine_name（実際に撤去された台）
- **censored**: debut_days の最大値が 180 以下だが、最終出現日が観測期間末日の30日未満（まだ稼働中の可能性 → 分析から除外）
- `定番(pre)` は debut_days がないため除外

打ち切りバイアス対策: 観測期間末付近にまだ稼働中の台を removed に含めると、「まだ181日に到達していないだけ」の台が混入する。censored として除外する。

セグメント別に survived / removed の台数と debut 期（1-60日）の avg_diff を比較する。censored の台数も参考値として出力する。

出力:
```
segment | group    | debut_avg_diff | debut_n | max_days_median | n_machines
2F_L_N  | survived | ...            | ...     | ...             | ...
2F_L_N  | removed  | ...            | ...     | ...             | ...
...
```

### Step 2: Mann-Whitney U 検定

survived と removed の debut 期 diff を MWU で比較。

出力:
```
segment | u_stat | p_value | survived_debut_avg | removed_debut_avg | diff
2F_L_N  | ...    | ...     | ...                | ...               | ...
...
```

**判定**: survived の debut_avg > removed の debut_avg なら生存バイアスあり。

### Step 3: debut_bin 別コホート追跡

debut_days を bin（1-14, 15-60, 61-180, 181+）に分割し、セグメント別の avg_diff 推移を出力。

出力:
```
segment | debut_bin | n    | avg_diff | plus_rate | n_machines
2F_L_N  | 1-14     | ...  | ...      | ...       | ...
2F_L_N  | 15-60    | ...  | ...      | ...       | ...
...
```

### Step 4: イベント日限定の debut プレミアム

蒲田7の kamata7_theory.md では「新台（1-60日）にはイベント日でも設定を入れない」「181日+定番台にプレミアム+145が集中」と記述されている。これをセグメント別に survived / removed で分解する。

出力:
```
segment | group    | scope      | debut_bin | n    | avg_diff
2F_L_N  | survived | event      | 1-60     | ...  | ...
2F_L_N  | survived | non_event  | 1-60     | ...  | ...
2F_L_N  | removed  | event      | 1-60     | ...  | ...
...
```

scope は蒲田7のイベント日定義（`eda/core.py` の `is_x_day`）を使用。

### Step 5: 2F vs 3F の生存バイアス比較（補助的参考）

**注意**: このステップは補助的な参考情報。floor差と A/N 構成差が混ざるため、主結果は Step 1-4 のセグメント内比較を使うこと。

2F_N（stability=0%）と 3F_A（stability=100%）と 3F_N で生存バイアスの強さを比較する。ただし 2F_N と 3F_A は機種タイプ（N vs A）が異なるため、floor差と機種差を分離できない。同じ機種タイプ同士（2F_N vs 3F_N、または 3F_L_A vs 3F_R_A）の比較を優先すること。

出力:
```
floor_type | survived_debut_avg | removed_debut_avg | mwu_p | bias_magnitude | note
2F_N       | ...                | ...               | ...   | ...            | stability=0%
3F_A       | ...                | ...               | ...   | ...            | stability=100%
3F_N       | ...                | ...               | ...   | ...            |
```

`bias_magnitude` = survived_debut_avg - removed_debut_avg。

## 出力

### Markdown レポート
`tmp/kamata7_survival_bias/report.md`

### CSV 出力
- `step1_survival_groups.csv`
- `step2_mwu.csv`
- `step3_cohort_tracking.csv`
- `step4_event_debut_premium.csv`
- `step5_floor_comparison.csv`

## 出力制約

- テーブル出力は `to_markdown()` を使わず自前の簡易Markdown生成で行う
- ファイルエンコーディングは UTF-8（BOMなし）
- DBデフォルトパスは `eda/core.py` の `HALL_DBS["蒲田7"]` と同一にすること

## テスト要件

`ml/tests/test_kamata7_survival_bias_verification.py`:

- 日付: `20250101`〜`20250601`（YYYYMMDD形式）
- machine_number: 2001〜2020（2F）+ 3001〜3020（3F）
- machine_name: A機種とN機種を混在。1種は途中で撤去（removed生成用）、1種は181日+残る
- イベント日（dd=7等）と非イベント日を含める
- games: 1500以上

テスト項目:
```python
def test_step1_both_groups(dummy_frame)
def test_step2_mwu_returns(dummy_frame)
def test_step3_all_bins(dummy_frame)
def test_step5_floor_comparison(dummy_frame)
def test_report_creates_files(dummy_frame, tmp_path)
```

## 実行確認

```bash
python -m pytest ml/tests/test_kamata7_survival_bias_verification.py -v
python -m eda.kamata7_survival_bias_verification
```
