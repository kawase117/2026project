# Cross-Attribute Performance Analysis 設計仕様

**作成日：** 2026-04-24  
**対象：** backtest/ 新規分析モジュール

---

## 1. 目的

訓練期間の **G数 / 勝率 / 差枚** が高いグループは、テスト期間の **差枚** が高くなるかを検証する。

**既存コードとの違い：**
| | 既存（relative_performance_*_triple.py） | 新規 |
|---|---|---|
| 訓練属性 | G数 / 勝率 / 差枚 | G数 / 勝率 / 差枚 |
| 測定属性 | 同じ属性（G数→G数 など） | **常に差枚** |
| 目的 | 属性の安定性検証 | **差枚予測力の検証** |

---

## 2. 全体アーキテクチャ

### ファイル構成

```
backtest/
├── analysis_base.py（拡張）
│   ├── split_groups_triple()（既存）
│   ├── map_groups_by_attr()（新規追加）
│   ├── aggregate_group_metrics()（新規追加）
│   └── calculate_rank_correlation()（新規追加）
│
└── cross_attribute_performance_analysis.py（新規）
    ├── analyze_cross_attribute()        # 単一属性×条件の分析
    └── run_cross_attribute_analysis()   # 3属性 全条件を一括実行
```

### 処理フロー

```
loader.py → DB からデータ読み込み
  ↓
condition_type / condition_value でフィルタ
  ↓
訓練期間 / テスト期間 に分割
  ↓
訓練期間で train_attr（G数/勝率/差枚）別に Top/Mid/Low 分割
  ↓
テスト期間で各グループのデータを抽出
  ↓
グループ別 差枚平均・勝率 を集計
スピアマン相関係数・p値 を計算
  ↓
テキスト出力（results/ に保存）
```

---

## 3. 入出力仕様

### 関数シグネチャ

```python
run_cross_attribute_analysis(
    db_path: str,           # DBファイルパス（例："db/マルハン蒲田1.db"）
    train_start: str,       # 訓練開始 YYYYMMDD（例："20250101"）
    train_end: str,         # 訓練終了 YYYYMMDD（例："20250331"）
    test_start: str,        # テスト開始 YYYYMMDD（例："20260401"）
    test_end: str,          # テスト終了 YYYYMMDD（例："20260430"）
    condition_type: str,    # 条件属性（"weekday"/"dd"/"is_zorome" など）
    condition_value,        # 条件値（"Monday"/"1"/0 など）
) -> None
```

### 出力フォーマット（コンソール＋ファイル）

```
========================================
訓練属性: G数（games_normalized）
条件: weekday = Monday
訓練期間: 2025-01-01 〜 2025-03-31 / テスト期間: 2026-04
========================================
グループ      | 台数 | 平均差枚   | 勝率(%)
Top（上位33%）|  12  | +148枚    | 58.3%
Mid（中位33%）|   9  |  +22枚    | 50.0%
Low（下位33%）|  11  |  -85枚    | 36.4%
----------------------------------------
スピアマン相関: 0.72  有意性: p=0.031 (*)
========================================
```

同様のブロックが **勝率訓練 → 差枚**、**差枚訓練 → 差枚** の順で続く。

### 出力ファイルパス

```
backtest/results/cross_attribute_analysis_{condition_type}_{condition_value}_{test_month}.txt
例：cross_attribute_analysis_weekday_Monday_2026-04.txt
```

---

## 4. analysis_base.py 拡張仕様

### 4-1. `map_groups_by_attr()`

```python
def map_groups_by_attr(
    train_df: pd.DataFrame,
    test_df: pd.DataFrame,
    train_attr: str,        # グループ分割に使う訓練属性（"games_normalized"/"diff_coins_normalized" など）
    split_unit: str,        # 集計・分割の単位（既存コードの "attr" に相当。例："dd"/"last_digit"/"weekday"）
    percentile: tuple = (33, 66),
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """
    訓練期間で split_unit 単位に train_attr を集計し Top/Mid/Low 分割。
    テスト期間データに対してグループラベルを付与して返す。

    ※ split_unit は既存コード（relative_performance_*）の `attr` 引数と同じ役割。
       condition_type（データ絞り込み）とは異なる。
    """
```

**内部処理：**
1. 訓練期間で `split_unit` 単位に `train_attr` を平均集計
2. 既存の `split_groups_triple()` でパーセンタイル分割
3. テスト期間データに Top/Mid/Low ラベルを付与

---

### 4-2. `aggregate_group_metrics()`

```python
def aggregate_group_metrics(
    df: pd.DataFrame,
    group_col: str = 'group',
    result_col: str = 'diff_coins_normalized',
) -> pd.DataFrame:
    """
    グループ別に台数・平均差枚・勝率を集計して返す。
    """
```

**返却カラム：** `group`, `count`, `avg_coin`, `win_rate`

---

### 4-3. `calculate_rank_correlation()`

```python
def calculate_rank_correlation(
    train_vals: list[float],   # 訓練期間グループ平均値 [Top_avg, Mid_avg, Low_avg]
    test_vals: list[float],    # テスト期間グループ平均値 [Top_avg, Mid_avg, Low_avg]
) -> tuple[float, float]:
    """
    スピアマン相関係数と p値を返す。
    """
```

---

## 5. 対応する condition_type

既存コードと完全共通：

| condition_type | 値の例 |
|---|---|
| `weekday` | "Monday", "Tuesday" ... |
| `dd` | 1〜31（月内日付） |
| `is_zorome` | 0 / 1 |
| `last_digit` | "0"〜"9" |

---

## 6. 対象ホール・実行例

```python
# マルハン蒲田1：月曜日、3ヶ月訓練、4月テスト
run_cross_attribute_analysis(
    db_path="db/マルハン蒲田1.db",
    train_start="20250101",
    train_end="20250331",
    test_start="20260401",
    test_end="20260430",
    condition_type="weekday",
    condition_value="Monday",
)
```

---

## 7. 制約事項

- 台数が 3 未満の場合はグループ分割不可 → スキップして警告を出力
- テスト期間にデータが存在しない condition_value → スキップ
- スピアマン相関は 3 点（グループ平均値）で計算するため参考値として扱う

---

## 8. 関連ドキュメント

- `document/CODE_SPECIFICATION.md` — backtest モジュール既知制約・改善計画
- `document/plans/2026-04-15-refactoring-plan.md` — 2026-04 リファクタリング計画
