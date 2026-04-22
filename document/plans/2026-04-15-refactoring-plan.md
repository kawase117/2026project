# Pachinko Analyzer リファクタリング計画

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** ダッシュボードの保守性・安全性・拡張性を向上させる段階的リファクタリング

**Architecture:** 全13ページに分散する重複コードを `utils/` に集約し、セキュリティ修正を先行実施。データベース側は型の不整合をドキュメント化で対処しつつ、エラーハンドリングを改善する。

**Tech Stack:** Streamlit 1.56.0 / Plotly 6.7.0 / SQLite / Pandas 3.0.2 / pytest

---

## 調査で特定された問題一覧

| ID | 問題 | 場所 | 優先度 |
|----|------|------|--------|
| A | フィルタロジックの重複（全ページで同じコード） | 全13ページ | 高 |
| B | グラフ生成の重複 | 全13ページ | 高 |
| C | SQLインジェクション脆弱性 | data_loader.py:137 | 高 |
| D | page_11のテーブル表示コードが2重定義 | page_11:140-340 | 高 |
| E | 配色定数の分散（constants.py / design_system.py） | 2ファイル | 中 |
| F | エラーハンドリングの不均一 | 全ページ | 中 |
| G | ランク計算のO(n²)サブクエリ | rank_calculator.py:18-26 | 中 |
| H | スクレイパーのXSS脆弱性（JS埋め込み） | anaslo-scraper_multi.py:387 | 中 |
| I | テスト体制がほぼゼロ | 全体 | 低 |
| J | ロギングがprintのみ | database/, scraper/ | 低 |

---

## フェーズ構成

```
Phase 1: セキュリティ修正（1-2時間）
  └─ Task 1: data_loader.py SQLインジェクション対策

Phase 2: ダッシュボード共通化（3-5時間）
  ├─ Task 2: utils/filters.py 新規作成（共通フィルタリング）
  ├─ Task 3: utils/charts.py 新規作成（共通グラフ生成）
  ├─ Task 4: page_11 重複テーブルコード統合
  └─ Task 5: 全ページへ共通関数を適用

Phase 3: 定数管理の整理（1時間）
  └─ Task 6: constants.py の未使用定数削除・整理

Phase 4: データベース側の改善（2-3時間）
  ├─ Task 7: main_processor.py エラーハンドリング改善
  └─ Task 8: rank_calculator.py サブクエリ最適化
```

---

## 変更ファイルマップ

| ファイル | 操作 | 内容 |
|---------|------|------|
| `dashboard/utils/data_loader.py` | 修正 | SQLインジェクション対策（ホワイトリスト） |
| `dashboard/utils/filters.py` | **新規作成** | 共通フィルタリング関数 |
| `dashboard/utils/charts.py` | **新規作成** | 共通グラフ生成関数 |
| `dashboard/pages/page_11_cross_search.py` | 修正 | 重複テーブル表示コードを関数化 |
| `dashboard/pages/page_01〜13.py` | 修正 | 共通関数に置き換え |
| `dashboard/config/constants.py` | 修正 | 未使用定数削除、COLORS参照をdesign_system.pyに統一 |
| `database/main_processor.py` | 修正 | エラーハンドリング改善 |
| `database/rank_calculator.py` | 修正 | ウィンドウ関数への置き換え |
| `test/test_filters.py` | **新規作成** | フィルタ関数のユニットテスト |
| `test/test_charts.py` | **新規作成** | グラフ生成関数のユニットテスト |

---

## Phase 1: セキュリティ修正

### Task 1: data_loader.py の SQLインジェクション対策

**問題**: `attribute` パラメータが未検証のままSQL文字列に埋め込まれている

```python
# dashboard/utils/data_loader.py 現在のコード（137行目）
query = f"SELECT * FROM daily_hall_summary WHERE {attribute} = ? ORDER BY date"
```

**Files:**
- Modify: `dashboard/utils/data_loader.py`

- [ ] **Step 1: 現在のdata_loader.pyを読んで load_daily_hall_by_attribute 関数を確認する**

- [ ] **Step 2: ホワイトリストによる検証を追加する**

`dashboard/utils/data_loader.py` の `load_daily_hall_by_attribute` 関数を以下のように修正：

```python
ALLOWED_ATTRIBUTES = {
    'day_of_week', 'last_digit', 'weekday_nth',
    'is_zorome', 'is_strong_zorome', 'is_month_start',
    'is_month_end', 'is_weekend', 'is_holiday'
}

@st.cache_data(ttl=3600)
def load_daily_hall_by_attribute(db_path: str, attribute: str, attribute_value) -> pd.DataFrame:
    if attribute not in ALLOWED_ATTRIBUTES:
        raise ValueError(f"許可されていないattribute: {attribute}")
    try:
        conn = sqlite3.connect(db_path)
        query = f"SELECT * FROM daily_hall_summary WHERE {attribute} = ? ORDER BY date"
        df = pd.read_sql_query(query, conn, params=[attribute_value])
        conn.close()
        return df
    except Exception as e:
        st.error(f"データ読み込みエラー: {e}")
        return pd.DataFrame()
```

- [ ] **Step 3: 動作確認**

```bash
python -c "
from dashboard.utils.data_loader import load_daily_hall_by_attribute
# ホワイトリスト外のattributeでValueErrorが発生することを確認
try:
    load_daily_hall_by_attribute('./db/test.db', 'date; DROP TABLE--', '20260101')
    print('NG: エラーが発生しなかった')
except ValueError as e:
    print(f'OK: {e}')
"
```

- [ ] **Step 4: コミット**

```bash
git add dashboard/utils/data_loader.py
git commit -m "fix: data_loaderのSQLインジェクション脆弱性にホワイトリスト対策を追加"
```

---

## Phase 2: ダッシュボード共通化

### Task 2: utils/filters.py 新規作成

**問題**: 以下のフィルタリングコードが全13ページで重複している

```python
# 現在の重複コード（例: page_01:23-29, page_02:24-30, 全ページ）
df_filtered = df[
    (df['date'] >= date_range[0]) &
    (df['date'] <= date_range[1])
]
if not st.session_state.show_low_confidence:
    df_filtered = df_filtered[df_filtered['avg_games_per_machine'] >= min_games]
```

**Files:**
- Create: `dashboard/utils/filters.py`
- Create: `test/test_filters.py`

- [ ] **Step 1: テストファイルを先に作成する**

`test/test_filters.py` を作成：

```python
import pytest
import pandas as pd
from datetime import datetime

# テスト用DataFrameを作成するヘルパー
def make_hall_summary_df():
    return pd.DataFrame({
        'date': pd.to_datetime(['2026-01-10', '2026-01-15', '2026-01-20']),
        'avg_games_per_machine': [800, 1200, 1500],
        'avg_diff_per_machine': [100, 200, 300],
        'win_rate': [45.0, 55.0, 60.0],
    })

def make_machine_df():
    return pd.DataFrame({
        'date': pd.to_datetime(['2026-01-10', '2026-01-15', '2026-01-20']),
        'games_normalized': [800, 1200, 1500],
        'diff_coins_normalized': [100, 200, 300],
        'machine_number': [101, 102, 103],
    })

class TestFilterByDateRange:
    def test_日付範囲内のデータのみ返す(self):
        from dashboard.utils.filters import filter_by_date_range
        df = make_hall_summary_df()
        start = datetime(2026, 1, 12)
        end = datetime(2026, 1, 18)
        result = filter_by_date_range(df, (start, end))
        assert len(result) == 1
        assert result.iloc[0]['avg_games_per_machine'] == 1200

    def test_空のDataFrameを受け取った場合空を返す(self):
        from dashboard.utils.filters import filter_by_date_range
        result = filter_by_date_range(pd.DataFrame(), (datetime(2026, 1, 1), datetime(2026, 12, 31)))
        assert result.empty

class TestFilterByMinGames:
    def test_ホール集計テーブルでmin_games未満を除外する(self):
        from dashboard.utils.filters import filter_by_min_games
        df = make_hall_summary_df()
        result = filter_by_min_games(df, 1000, column='avg_games_per_machine')
        assert len(result) == 2
        assert result['avg_games_per_machine'].min() >= 1000

    def test_個別台テーブルでmin_games未満を除外する(self):
        from dashboard.utils.filters import filter_by_min_games
        df = make_machine_df()
        result = filter_by_min_games(df, 1000, column='games_normalized')
        assert len(result) == 2

    def test_show_low_confidenceがTrueなら除外しない(self):
        from dashboard.utils.filters import apply_sidebar_filters
        df = make_hall_summary_df()
        start = datetime(2026, 1, 1)
        end = datetime(2026, 12, 31)
        result = apply_sidebar_filters(df, (start, end), min_games=9999, show_low_confidence=True)
        assert len(result) == 3  # 全件残る
```

- [ ] **Step 2: テストを実行して失敗を確認**

```bash
cd C:\Users\apto117\Documents\pachinko-analyzer\src\2026project
python -m pytest test/test_filters.py -v
```

Expected: `ModuleNotFoundError: No module named 'dashboard.utils.filters'`

- [ ] **Step 3: filters.py を実装する**

`dashboard/utils/filters.py` を作成：

```python
"""
共通フィルタリング関数
全ページで重複していたフィルタロジックを集約
"""

import pandas as pd
from typing import Tuple
from datetime import datetime


def filter_by_date_range(
    df: pd.DataFrame,
    date_range: Tuple[datetime, datetime],
    date_column: str = 'date'
) -> pd.DataFrame:
    """日付範囲でDataFrameをフィルタリングする"""
    if df.empty:
        return df
    start, end = date_range
    return df[(df[date_column] >= start) & (df[date_column] <= end)]


def filter_by_min_games(
    df: pd.DataFrame,
    min_games: int,
    column: str = 'avg_games_per_machine'
) -> pd.DataFrame:
    """最小G数でDataFrameをフィルタリングする（集計前適用）"""
    if df.empty:
        return df
    return df[df[column] >= min_games]


def apply_sidebar_filters(
    df: pd.DataFrame,
    date_range: Tuple[datetime, datetime],
    min_games: int,
    show_low_confidence: bool,
    date_column: str = 'date',
    games_column: str = 'avg_games_per_machine'
) -> pd.DataFrame:
    """
    サイドバーのフィルタ設定を一括適用する（ホール集計用）

    Args:
        df: フィルタ対象DataFrame
        date_range: (開始日, 終了日) のタプル
        min_games: 最小G数（show_low_confidence=Falseのとき適用）
        show_low_confidence: Trueの場合min_gamesフィルタをスキップ
        date_column: 日付カラム名
        games_column: G数カラム名（デフォルト: avg_games_per_machine）
    """
    df = filter_by_date_range(df, date_range, date_column)
    if not show_low_confidence and not df.empty:
        df = filter_by_min_games(df, min_games, games_column)
    return df


def apply_machine_filters(
    df: pd.DataFrame,
    date_range: Tuple[datetime, datetime],
    min_games: int,
    show_low_confidence: bool,
    date_column: str = 'date',
    games_column: str = 'games_normalized'
) -> pd.DataFrame:
    """
    サイドバーのフィルタ設定を一括適用する（個別台データ用）
    min_gamesは集計前に個別台レベルで適用する。
    """
    df = filter_by_date_range(df, date_range, date_column)
    if not show_low_confidence and not df.empty:
        df = filter_by_min_games(df, min_games, games_column)
    return df
```

- [ ] **Step 4: テストを実行してパスを確認**

```bash
python -m pytest test/test_filters.py -v
```

Expected: 全テストPASS

- [ ] **Step 5: コミット**

```bash
git add dashboard/utils/filters.py test/test_filters.py
git commit -m "feat: 共通フィルタリング関数を utils/filters.py に集約"
```

---

### Task 3: utils/charts.py 新規作成

**問題**: `px.bar()` / `px.line()` の呼び出しが各ページで繰り返される（パラメータ差分が1-2個）

**Files:**
- Create: `dashboard/utils/charts.py`
- Create: `test/test_charts.py`

- [ ] **Step 1: テストファイルを作成する**

`test/test_charts.py` を作成：

```python
import pytest
import pandas as pd
import plotly.graph_objects as go

def make_sample_df():
    return pd.DataFrame({
        'x_col': ['月', '火', '水'],
        'y_col': [50.0, 55.0, 60.0],
        'y_col2': [1000, 1200, 1500],
    })

class TestCreateBarChart:
    def test_正常なDataFrameからfigオブジェクトを返す(self):
        from dashboard.utils.charts import create_bar_chart
        df = make_sample_df()
        fig = create_bar_chart(df, x='x_col', y='y_col', title='テスト')
        assert isinstance(fig, go.Figure)
        assert len(fig.data) > 0

    def test_空DataFrameでも例外を出さない(self):
        from dashboard.utils.charts import create_bar_chart
        fig = create_bar_chart(pd.DataFrame(), x='x', y='y', title='空')
        assert isinstance(fig, go.Figure)

class TestCreateLineChart:
    def test_正常なDataFrameからfigオブジェクトを返す(self):
        from dashboard.utils.charts import create_line_chart
        df = make_sample_df()
        fig = create_line_chart(df, x='x_col', y='y_col', title='テスト')
        assert isinstance(fig, go.Figure)
```

- [ ] **Step 2: テストを実行して失敗を確認**

```bash
python -m pytest test/test_charts.py -v
```

Expected: `ModuleNotFoundError: No module named 'dashboard.utils.charts'`

- [ ] **Step 3: charts.py を実装する**

`dashboard/utils/charts.py` を作成：

```python
"""
共通グラフ生成関数
全ページで重複していたグラフ生成ロジックを集約
"""

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from dashboard.design_system import COLORS


def create_bar_chart(
    df: pd.DataFrame,
    x: str,
    y: str,
    title: str,
    color: str = None,
    height: int = 400,
    **kwargs
) -> go.Figure:
    """統一されたバーチャートを生成する"""
    if df.empty:
        fig = go.Figure()
        fig.update_layout(title=title, height=height)
        return fig
    bar_color = color or COLORS.get('secondary_blue', '#3b82f6')
    fig = px.bar(df, x=x, y=y, title=title, height=height, **kwargs)
    fig.update_traces(marker_color=bar_color)
    fig.update_layout(
        plot_bgcolor='rgba(0,0,0,0)',
        paper_bgcolor='rgba(0,0,0,0)',
        font_color='#e2e8f0',
    )
    return fig


def create_line_chart(
    df: pd.DataFrame,
    x: str,
    y: str,
    title: str,
    color: str = None,
    height: int = 400,
    **kwargs
) -> go.Figure:
    """統一された折れ線グラフを生成する"""
    if df.empty:
        fig = go.Figure()
        fig.update_layout(title=title, height=height)
        return fig
    line_color = color or COLORS.get('secondary_blue', '#3b82f6')
    fig = px.line(df, x=x, y=y, title=title, height=height, **kwargs)
    fig.update_traces(line_color=line_color)
    fig.update_layout(
        plot_bgcolor='rgba(0,0,0,0)',
        paper_bgcolor='rgba(0,0,0,0)',
        font_color='#e2e8f0',
    )
    return fig


def create_scatter_chart(
    df: pd.DataFrame,
    x: str,
    y: str,
    title: str,
    color: str = None,
    size: str = None,
    height: int = 400,
    **kwargs
) -> go.Figure:
    """統一された散布図を生成する"""
    if df.empty:
        fig = go.Figure()
        fig.update_layout(title=title, height=height)
        return fig
    fig = px.scatter(df, x=x, y=y, title=title, size=size, height=height, **kwargs)
    fig.update_layout(
        plot_bgcolor='rgba(0,0,0,0)',
        paper_bgcolor='rgba(0,0,0,0)',
        font_color='#e2e8f0',
    )
    return fig
```

- [ ] **Step 4: テストを実行してパスを確認**

```bash
python -m pytest test/test_charts.py -v
```

Expected: 全テストPASS

- [ ] **Step 5: コミット**

```bash
git add dashboard/utils/charts.py test/test_charts.py
git commit -m "feat: 共通グラフ生成関数を utils/charts.py に集約"
```

---

### Task 4: page_11 の重複テーブル表示コードを関数化

**問題**: `page_11_cross_search.py` で TOP20 テーブルと全データテーブルの表示コードがほぼ同一で2回書かれている（140-235行 / 241-282行）

**Files:**
- Modify: `dashboard/pages/page_11_cross_search.py`

- [ ] **Step 1: 現在の page_11_cross_search.py を読む（重複箇所を確認）**

重複している箇所：
- 140-235行（TOP20用の表示データ構築）
- 241-282行（全データ用の表示データ構築）

- [ ] **Step 2: テーブル表示を関数化する**

`page_11_cross_search.py` に以下のヘルパー関数を追加し、重複部分を置き換える：

```python
def _build_display_rows(
    df: pd.DataFrame,
    attr1: str,
    attr2: str,
    machine_names_dict: dict,
    latest_machine_dict: dict,
    show_latest_only: bool
) -> list:
    """クロス検索結果テーブルの行データを構築する（TOP20・全件共用）"""
    rows = []
    for _, row in df.iterrows():
        row_data = {attr1: str(row['attr1'])}
        if attr1 == '台番号別' and row['attr1'] in machine_names_dict:
            row_data['機種'] = (
                latest_machine_dict[row['attr1']] if show_latest_only
                else machine_names_dict[row['attr1']]
            )
        row_data[attr2] = str(row['attr2'])
        if attr2 == '台番号別' and row['attr2'] in machine_names_dict:
            row_data['機種'] = (
                latest_machine_dict[row['attr2']] if show_latest_only
                else machine_names_dict[row['attr2']]
            )
        row_data['勝率'] = float(row['win_rate'])
        row_data['合計差枚'] = int(row['total_diff'])
        row_data['平均差枚'] = int(row['avg_diff'])
        row_data['平均G数'] = int(row['avg_games'])
        row_data['台数'] = int(row['count'])
        rows.append(row_data)
    return rows


def _render_cross_table(
    df: pd.DataFrame,
    attr1: str,
    attr2: str,
    machine_names_dict: dict,
    latest_machine_dict: dict,
    show_latest_only: bool,
    title: str
):
    """クロス検索結果テーブルを描画する"""
    rows = _build_display_rows(df, attr1, attr2, machine_names_dict, latest_machine_dict, show_latest_only)
    if not rows:
        st.warning("⚠️ フィルタ条件に該当するデータがありません")
        return
    df_display = pd.DataFrame(rows)
    df_display['勝率'] = df_display['勝率'].apply(lambda x: f"{x:.1f}%")
    st.markdown(f"### {title}")
    st.dataframe(df_display, use_container_width=True, hide_index=True)
```

既存の重複コード（140-235行 / 241-282行）を以下で置き換える：

```python
# TOP20テーブル
premium_divider()
_render_cross_table(
    cross_filtered.head(20), attr1, attr2,
    machine_names_dict, latest_machine_dict, show_latest_only,
    "📋 クロス検索結果（TOP20）"
)

# 全データテーブル
premium_divider()
_render_cross_table(
    cross_filtered, attr1, attr2,
    machine_names_dict, latest_machine_dict, show_latest_only,
    "📋 クロス検索結果（全データ）"
)
```

- [ ] **Step 3: ダッシュボードを起動して動作確認**

```bash
streamlit run main_app.py
```

クロス検索分析ページを開き、TOP20・全データの両テーブルが正常に表示されることを確認。

- [ ] **Step 4: コミット**

```bash
git add dashboard/pages/page_11_cross_search.py
git commit -m "refactor: page_11の重複テーブル表示コードを_render_cross_tableに統合"
```

---

### Task 5: 全ページに共通フィルタ関数を適用

**対象ページ**: page_01〜page_13（ただし page_11 は Task 4 で対応済み）
**適用パターン**: 各ページの先頭にある重複フィルタリングコードを `apply_sidebar_filters()` または `apply_machine_filters()` に置き換える

**Files:**
- Modify: `dashboard/pages/page_01_hall_overview.py`
- Modify: `dashboard/pages/page_02_daily_analysis.py`
- Modify: `dashboard/pages/page_03_weekday_analysis.py`
- Modify: `dashboard/pages/page_04_dd_analysis.py`
- Modify: `dashboard/pages/page_05_last_digit.py`
- Modify: `dashboard/pages/page_06_day_last_digit.py`
- Modify: `dashboard/pages/page_07_nth_weekday.py`
- Modify: `dashboard/pages/page_08_individual_machines.py`
- Modify: `dashboard/pages/page_09_machine_tail.py`
- Modify: `dashboard/pages/page_10_period_top10.py`
- Modify: `dashboard/pages/page_12_statistics.py`
- Modify: `dashboard/pages/page_13_hall_selection.py`

- [ ] **Step 1: 各ページのインポートに追加**

ホール集計データを使うページ（page_01〜07, page_12）：
```python
from ..utils.filters import apply_sidebar_filters
```

個別台データを使うページ（page_08〜10, page_13）：
```python
from ..utils.filters import apply_machine_filters
```

- [ ] **Step 2: ホール集計系ページの置き換え（page_01 を例に）**

置き換え前（現在のコード）：
```python
df = st.session_state.df_hall_summary
date_range = st.session_state.date_range
min_games = st.session_state.min_games

df_filtered = df[
    (df['date'] >= date_range[0]) &
    (df['date'] <= date_range[1])
]
if not st.session_state.show_low_confidence:
    df_filtered = df_filtered[df_filtered['avg_games_per_machine'] >= min_games]
```

置き換え後：
```python
df = st.session_state.df_hall_summary
df_filtered = apply_sidebar_filters(
    df,
    date_range=st.session_state.date_range,
    min_games=st.session_state.min_games,
    show_low_confidence=st.session_state.show_low_confidence,
)
```

- [ ] **Step 3: 個別台系ページの置き換え（page_08 を例に）**

置き換え前：
```python
all_machines = load_machine_detailed_results(str(st.session_state.db_path))
date_range = st.session_state.date_range
min_games = st.session_state.min_games

df = all_machines[
    (all_machines['date'] >= date_range[0]) &
    (all_machines['date'] <= date_range[1])
]
if not st.session_state.show_low_confidence:
    df = df[df['games_normalized'] >= min_games]
```

置き換え後：
```python
all_machines = load_machine_detailed_results(str(st.session_state.db_path))
df = apply_machine_filters(
    all_machines,
    date_range=st.session_state.date_range,
    min_games=st.session_state.min_games,
    show_low_confidence=st.session_state.show_low_confidence,
)
```

- [ ] **Step 4: 全ページで同様に置き換えて動作確認**

```bash
streamlit run main_app.py
```

全12ページを巡回してフィルタが正常に動作することを確認。

- [ ] **Step 5: コミット**

```bash
git add dashboard/pages/
git commit -m "refactor: 全ページのフィルタロジックをutils/filters.pyに統一"
```

---

## Phase 3: 定数管理の整理

### Task 6: constants.py の未使用定数削除・整理

**問題**:
- `constants.py` の `COLORS` 定義が実際には使われていない（各ページは `design_system.py` の `COLORS` を使用）
- page_05_last_digit が PAGES リストから欠落している

**Files:**
- Modify: `dashboard/config/constants.py`

- [ ] **Step 1: constants.py を読んで現状把握**

- [ ] **Step 2: 未使用の COLORS 定義を削除し、PAGES リストを修正**

```python
# constants.py から削除するもの
# COLORS = {...}  ← 削除（design_system.py を使う）

# PAGES リストに page_05 が抜けているので追加を確認
PAGES = [
    {"icon": "🏠", "title": "ホール全体", ...},
    ...
    {"icon": "🔢", "title": "末尾別分析", ...},  # page_05 が含まれているか確認
    ...
]
```

- [ ] **Step 3: 各ページで constants.COLORS を参照していないか確認**

```bash
grep -r "from.*constants.*import.*COLORS\|constants\.COLORS" dashboard/
```

使用箇所があれば `design_system.py` の COLORS 参照に変更。

- [ ] **Step 4: コミット**

```bash
git add dashboard/config/constants.py
git commit -m "refactor: constants.pyの未使用COLORS定義を削除、design_system.pyに一元化"
```

---

## Phase 4: データベース側の改善

### Task 7: main_processor.py のエラーハンドリング改善

**問題**:
- 致命的エラー（データ整合性に影響）と一時的エラーを区別せずに全てスキップ
- ランク計算失敗 + 日付フラグ追加成功 → データが不完全な状態で継続

**Files:**
- Modify: `database/main_processor.py`

- [ ] **Step 1: main_processor.py を読んで現状確認**

- [ ] **Step 2: エラー分類と処理を改善**

```python
# 改善後の処理フロー（main_processor.py 該当箇所）

class ProcessingError(Exception):
    """データ処理の致命的エラー（ロールバック必要）"""
    pass

# ランク計算と日付フラグ追加をトランザクション的に扱う
try:
    self.rank_calc.calculate_ranks_for_date(date)
    self.rank_calc.calculate_history_for_date(date)
    self.date_info_calc.update_date_info(date)
    print(f"✅ {date}: ランク計算・日付フラグ追加完了")
except Exception as e:
    # 両方失敗した場合のみスキップ（一方だけ成功の不整合を防ぐ）
    print(f"⚠️ {date}: ランク計算・日付フラグ追加スキップ - {str(e)}")
    # ここでは処理継続（次の日付へ）
```

- [ ] **Step 3: 動作確認**

```bash
python -c "
from database.main_processor import DataImporter
# テスト用ホールで実行確認
importer = DataImporter('テストホール')
print('インポート完了')
"
```

- [ ] **Step 4: コミット**

```bash
git add database/main_processor.py
git commit -m "fix: main_processorのエラーハンドリングを改善（ランク計算と日付フラグを原子的に処理）"
```

---

### Task 8: rank_calculator.py のクエリ最適化

**問題**: サブクエリがO(n²)になっている可能性

```sql
-- 現在（N行 × N行のサブクエリ）
COUNT(*) + 1 FROM {table} t2 WHERE t2.date = ? AND t2.avg_diff_coins > {table}.avg_diff_coins
```

**Files:**
- Modify: `database/rank_calculator.py`

- [ ] **Step 1: rank_calculator.py を読んで現在のクエリを確認**

- [ ] **Step 2: SQLiteがウィンドウ関数をサポートしているか確認**

```bash
python -c "
import sqlite3
conn = sqlite3.connect(':memory:')
version = conn.execute('SELECT sqlite_version()').fetchone()[0]
print(f'SQLite version: {version}')
# SQLite 3.25.0以上でウィンドウ関数サポート
conn.close()
"
```

- [ ] **Step 3: SQLite バージョンが 3.25.0 以上なら ROW_NUMBER() に置き換え**

```python
# 置き換え後のクエリ
rank_query = f"""
WITH ranked AS (
    SELECT
        *,
        ROW_NUMBER() OVER (PARTITION BY date ORDER BY avg_diff_coins DESC) as rank_diff,
        ROW_NUMBER() OVER (PARTITION BY date ORDER BY avg_games DESC) as rank_games
    FROM {table}
    WHERE date = ?
)
UPDATE {table}
SET
    {prefix}_rank_diff = (SELECT rank_diff FROM ranked WHERE ranked.date = {table}.date AND ...),
    ...
WHERE date = ?
"""
```

- [ ] **Step 4: パフォーマンス比較**

```bash
python -c "
import time, sqlite3
# 旧クエリと新クエリの実行時間を比較
"
```

- [ ] **Step 5: コミット**

```bash
git add database/rank_calculator.py
git commit -m "perf: rank_calculatorのサブクエリをROW_NUMBER()ウィンドウ関数に置き換え"
```

---

## 実施しない・後回しにするもの

| 問題 | 理由 |
|------|------|
| last_digit の型統一（TEXT vs INTEGER） | 変更コスト大（全DBの再生成が必要）。CLAUDE.mdのドキュメントで注意を促す運用で対処 |
| スクレイパーのXSS（JS埋め込み） | スクレイパーは内部ツール。ホール名は hall_config.json で管理するため実被害なし |
| logging モジュール導入 | 機能改善でなく運用改善。優先度低 |
| テスト体制の全面整備 | Task 2・3 のテスト追加をまず実施し、徐々に拡充 |

---

## 完了チェックリスト

- [ ] Task 1: SQLインジェクション対策
- [ ] Task 2: utils/filters.py 新規作成
- [ ] Task 3: utils/charts.py 新規作成
- [ ] Task 4: page_11 重複テーブルコード統合
- [ ] Task 5: 全ページにフィルタ共通関数を適用
- [ ] Task 6: constants.py 整理
- [ ] Task 7: main_processor.py エラーハンドリング改善
- [ ] Task 8: rank_calculator.py クエリ最適化

---

**作成日**: 2026-04-15
**対象バージョン**: v2.0（モジュール化版）
**見直し予定**: 各フェーズ完了後
