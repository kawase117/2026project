# 蒲田7ヒートマップ HTML試作 実装計画

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 蒲田7の2F/3Fをカード型HTMLで描画する試作を作り、`page_17_heatmap` を置き換えられるか確認する

**Architecture:** 座標CSVとSQLiteから台別集計を作り、HTML/CSSの絶対配置カードとして描画する。`Plotly` は試作から外し、見た目の自由度を優先する。出力は `Heatmap/` 配下の単体HTMLとし、既存の `page_17_heatmap` は壊さない。

**Tech Stack:** Python 3.11+, Pandas, SQLite, 既存の `Heatmap/` 座標CSV, 静的HTML/CSS

---

## ファイル構造

| ファイル | 役割 |
|---|---|
| `Heatmap/generate_kamata7_cardmap_html.py` (新規) | 蒲田7の台別集計、HTML/CSSカード描画、出力HTML生成 |
| `Heatmap/kamata7_cardmap_preview.html` (生成物) | 試作結果の単体HTML |

---

## Task 1: 蒲田7の台別集計を作る

**Files:**
- Create: `Heatmap/generate_kamata7_cardmap_html.py`

- [ ] **Step 1: 読み込み・集計関数を実装する**

```python
def load_machine_stats(db_path: Path, start_date: str | None = None, end_date: str | None = None) -> pd.DataFrame:
    """machine_detailed_results を machine_number 単位で集計する"""
```

- [ ] **Step 2: 座標CSV読み込みと結合を実装する**

```python
def load_floor_coordinates(coords_path: Path) -> pd.DataFrame:
    """display_x/display_y を含む座標フレームを返す"""
```

## Task 2: HTML/CSS カード描画を作る

**Files:**
- Modify: `Heatmap/generate_kamata7_cardmap_html.py`

- [ ] **Step 1: フロアごとのカードHTMLを生成する**

```python
def render_floor_section(frame: pd.DataFrame, floor_label: str, metric_key: str) -> str:
    """フロア見出しと台カード群を含むHTML断片を返す"""
```

- [ ] **Step 2: 色分けと省略表示を実装する**

```python
def classify_metric(value: float | None) -> str:
    """平均差枚を tier-high / tier-mid / tier-neutral / tier-low / tier-missing に分類する"""
```

## Task 3: 出力HTMLとCLIを作る

**Files:**
- Modify: `Heatmap/generate_kamata7_cardmap_html.py`

- [ ] **Step 1: HTML全体テンプレートを組み立てる**

```python
def build_html_document(floor_sections: list[str], generated_at: str, date_range_label: str) -> str:
    """単体HTMLを返す"""
```

- [ ] **Step 2: `main()` から preview HTML を保存できるようにする**

```python
def main() -> int:
    """kamata7_cardmap_preview.html を生成する"""
```

- [ ] **Step 3: 実行して HTML が生成されることを確認する**

```bash
python Heatmap/generate_kamata7_cardmap_html.py
```

Expected: `Heatmap/kamata7_cardmap_preview.html` が生成される

---
