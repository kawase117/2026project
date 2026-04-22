# バックテスト検証ページ 実装計画

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 過去（1月～3月）のランキングが4月で再現するか検証するダッシュボードページを実装

**Architecture:** 
- `backtest_helpers.py` で集計・ランキング・検証計算ロジックを統一
- `page_15_backtest_validation.py` でUI・グラフ・テーブル表示を実装
- 既存 `charts.py` と `filters.py` を活用

**Tech Stack:** 
- Streamlit 1.56.0、Plotly 6.7.0、Pandas 3.0.2、SQLite

---

## ファイル構造

| ファイル                                    | 役割                          |
|-------------------------------------------|-------------------------------|
| `dashboard/utils/backtest_helpers.py` (新規) | 訓練・ランキング・検証計算ロジック       |
| `dashboard/pages/page_15_backtest_validation.py` (新規) | ページメイン・UI・グラフ・テーブル |
| `test/test_backtest_validation.py` (新規)   | ユニットテスト（15件）         |
| `dashboard/config/constants.py` (修正)      | ページ定数追加                 |
| `dashboard/main.py` (修正)                 | ルーティング追加               |

---

## Task 1: backtest_helpers.py — 訓練データ集計関数

**Files:**
- Create: `dashboard/utils/backtest_helpers.py`
- Test: `test/test_backtest_validation.py`

- [ ] **Step 1: Create backtest_helpers.py with compute_training_stats()**

```python
# dashboard/utils/backtest_helpers.py

import pandas as pd
from typing import Dict, Tuple
import streamlit as st

@st.cache_data(ttl=3600)
def compute_training_stats(
    df: pd.DataFrame,
    train_start: str = "20260101",
    train_end: str = "20260331"
) -> Dict:
    """
    訓練期間（1月～3月）のランキング統計を計算
    
    Args:
        df: machine_detailed_results DataFrame
        train_start: 訓練開始日 (YYYYMMDD)
        train_end: 訓練終了日 (YYYYMMDD)
    
    Returns:
        {
            'dd_tail': {(dd, tail): {'win_rate': X, 'avg_diff': Y, 'avg_games': Z, 'count': N}},
            'dd_machine': {...},
            'dd_type': {...},
            'weekday_tail': {...},
            'weekday_machine': {...},
            'weekday_type': {...}
        }
    """
    df_train = df[(df['date'] >= train_start) & (df['date'] <= train_end)].copy()
    
    result = {}
    
    # 日付カラムから DD（月内日付）を抽出
    df_train['dd'] = df_train['date'].str[4:6].astype(int)
    
    # 曜日は daily_hall_summary から別途取得する必要あり（後のタスクで対応）
    
    patterns = {
        'dd_tail': ['dd', 'last_digit'],
        'dd_machine': ['dd', 'machine_number'],
        'dd_type': ['dd', 'machine_name'],
        'weekday_tail': ['weekday', 'last_digit'],
        'weekday_machine': ['weekday', 'machine_number'],
        'weekday_type': ['weekday', 'machine_name']
    }
    
    for pattern_name, group_cols in patterns.items():
        if pattern_name.startswith('weekday'):
            # weekday は後のタスク Task 2 で統合
            continue
        
        grouped = df_train.groupby(group_cols, as_index=False).agg({
            'diff_coins_normalized': ['mean', 'count'],
            'games_normalized': 'mean'
        }).round(2)
        
        grouped.columns = ['_'.join(col).strip('_') if col[1] else col[0] for col in grouped.columns.values]
        
        # 勝率計算（差枚 > 0 の割合）
        count_win = df_train[df_train['diff_coins_normalized'] > 0].groupby(group_cols).size()
        count_total = df_train.groupby(group_cols).size()
        grouped['win_rate'] = (count_win / count_total * 100).round(2).values
        
        result[pattern_name] = grouped
    
    return result
```

- [ ] **Step 2: Write test for compute_training_stats()**

```python
# test/test_backtest_validation.py

import pytest
import pandas as pd
from dashboard.utils.backtest_helpers import compute_training_stats

def test_compute_training_stats_basic():
    """訓練統計が正しく計算されることを確認"""
    df = pd.DataFrame({
        'date': ['20260115', '20260115', '20260220', '20260220'] * 3,
        'machine_number': [1, 2, 1, 2] * 3,
        'machine_name': ['AA', 'BB', 'AA', 'BB'] * 3,
        'last_digit': ['0', '1', '0', '1'] * 3,
        'diff_coins_normalized': [100, -50, 200, 0] * 3,
        'games_normalized': [50, 60, 70, 80] * 3
    })
    
    result = compute_training_stats(df)
    
    assert 'dd_tail' in result
    assert 'dd_machine' in result
    assert len(result['dd_tail']) > 0
    assert 'win_rate' in result['dd_tail'].columns

def test_compute_training_stats_empty():
    """空DataFrameで例外を出さない"""
    df = pd.DataFrame({
        'date': [],
        'machine_number': [],
        'machine_name': [],
        'last_digit': [],
        'diff_coins_normalized': [],
        'games_normalized': []
    })
    
    result = compute_training_stats(df)
    assert isinstance(result, dict)
```

- [ ] **Step 3: Run test to verify it fails**

```bash
cd C:\Users\apto117\Documents\pachinko-analyzer\src\2026project
python -m pytest test/test_backtest_validation.py::test_compute_training_stats_basic -v
```

Expected: FAIL with "module 'dashboard.utils.backtest_helpers' not found"

- [ ] **Step 4: Run test to verify it passes**

```bash
python -m pytest test/test_backtest_validation.py::test_compute_training_stats_basic test_compute_training_stats_empty -v
```

Expected: PASS (both tests)

- [ ] **Step 5: Commit**

```bash
git add dashboard/utils/backtest_helpers.py test/test_backtest_validation.py
git commit -m "feat: 訓練データ集計関数 compute_training_stats() を実装"
```

---

## Task 2: backtest_helpers.py — ランキング計算関数（TOP20%/10%）

**Files:**
- Modify: `dashboard/utils/backtest_helpers.py`
- Test: `test/test_backtest_validation.py`

- [ ] **Step 1: Add compute_top_percentile_rankings() to backtest_helpers.py**

```python
# 追加: dashboard/utils/backtest_helpers.py の末尾に

def compute_top_percentile_rankings(
    stats_dict: Dict[str, pd.DataFrame]
) -> Dict[str, Dict[str, pd.DataFrame]]:
    """
    訓練統計からTOP20%/10%のランキングを計算
    
    Args:
        stats_dict: compute_training_stats() の出力
    
    Returns:
        {
            'dd_tail': {
                'win_rate': {'top20': set(), 'top10': set()},
                'avg_diff': {...},
                'avg_games': {...}
            },
            ...
        }
    """
    result = {}
    
    for pattern_name, df in stats_dict.items():
        result[pattern_name] = {}
        
        # 勝率のランキング
        threshold_20_wr = df['win_rate'].quantile(0.8)
        threshold_10_wr = df['win_rate'].quantile(0.9)
        
        top20_wr = set(zip(df[df['win_rate'] >= threshold_20_wr].iloc[:, 0],
                           df[df['win_rate'] >= threshold_20_wr].iloc[:, 1]))
        top10_wr = set(zip(df[df['win_rate'] >= threshold_10_wr].iloc[:, 0],
                           df[df['win_rate'] >= threshold_10_wr].iloc[:, 1]))
        
        result[pattern_name]['win_rate'] = {
            'top20': top20_wr,
            'top10': top10_wr,
            'threshold20': threshold_20_wr,
            'threshold10': threshold_10_wr
        }
        
        # 平均差枚のランキング
        if 'diff_coins_normalized_mean' in df.columns:
            threshold_20_diff = df['diff_coins_normalized_mean'].quantile(0.8)
            threshold_10_diff = df['diff_coins_normalized_mean'].quantile(0.9)
            
            top20_diff = set(zip(df[df['diff_coins_normalized_mean'] >= threshold_20_diff].iloc[:, 0],
                                 df[df['diff_coins_normalized_mean'] >= threshold_20_diff].iloc[:, 1]))
            top10_diff = set(zip(df[df['diff_coins_normalized_mean'] >= threshold_10_diff].iloc[:, 0],
                                 df[df['diff_coins_normalized_mean'] >= threshold_10_diff].iloc[:, 1]))
            
            result[pattern_name]['avg_diff'] = {
                'top20': top20_diff,
                'top10': top10_diff,
                'threshold20': threshold_20_diff,
                'threshold10': threshold_10_diff
            }
        
        # 平均G数のランキング
        if 'games_normalized_mean' in df.columns:
            threshold_20_g = df['games_normalized_mean'].quantile(0.8)
            threshold_10_g = df['games_normalized_mean'].quantile(0.9)
            
            top20_g = set(zip(df[df['games_normalized_mean'] >= threshold_20_g].iloc[:, 0],
                              df[df['games_normalized_mean'] >= threshold_20_g].iloc[:, 1]))
            top10_g = set(zip(df[df['games_normalized_mean'] >= threshold_10_g].iloc[:, 0],
                              df[df['games_normalized_mean'] >= threshold_10_g].iloc[:, 1]))
            
            result[pattern_name]['avg_games'] = {
                'top20': top20_g,
                'top10': top10_g,
                'threshold20': threshold_20_g,
                'threshold10': threshold_10_g
            }
    
    return result
```

- [ ] **Step 2: Write test for compute_top_percentile_rankings()**

```python
# 追加: test/test_backtest_validation.py

def test_compute_top_percentile_rankings():
    """TOP20%/10%計算が正しく行われることを確認"""
    df = pd.DataFrame({
        'dd': [1, 1, 1, 2, 2, 2],
        'last_digit': ['0', '1', '0', '1', '0', '1'],
        'win_rate': [80.0, 60.0, 40.0, 70.0, 50.0, 30.0],
        'diff_coins_normalized_mean': [100, 50, 0, 80, 30, -20],
        'games_normalized_mean': [500, 400, 300, 450, 350, 250]
    })
    
    stats = {'test_pattern': df}
    result = compute_top_percentile_rankings(stats)
    
    assert 'test_pattern' in result
    assert 'win_rate' in result['test_pattern']
    assert 'top20' in result['test_pattern']['win_rate']
    assert 'top10' in result['test_pattern']['win_rate']
    assert len(result['test_pattern']['win_rate']['top20']) >= len(result['test_pattern']['win_rate']['top10'])
```

- [ ] **Step 3: Run test to verify it passes**

```bash
python -m pytest test/test_backtest_validation.py::test_compute_top_percentile_rankings -v
```

Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add dashboard/utils/backtest_helpers.py test/test_backtest_validation.py
git commit -m "feat: TOP20%/10%ランキング計算関数 compute_top_percentile_rankings() を実装"
```

---

## Task 3: backtest_helpers.py — 検証指標計算関数

**Files:**
- Modify: `dashboard/utils/backtest_helpers.py`
- Test: `test/test_backtest_validation.py`

- [ ] **Step 1: Add compute_validation_metrics() to backtest_helpers.py**

```python
# 追加: dashboard/utils/backtest_helpers.py の末尾に

def compute_validation_metrics(
    df_test: pd.DataFrame,
    rankings: Dict[str, Dict[str, Dict]],
    pattern_name: str,
    group_cols: list,
    test_start: str = "20260401",
    test_end: str = "20260420"
) -> pd.DataFrame:
    """
    4月の毎日検証指標を計算
    
    Args:
        df_test: machine_detailed_results (4月データ)
        rankings: compute_top_percentile_rankings() の出力
        pattern_name: 'dd_tail' など
        group_cols: ['dd', 'last_digit'] など
        test_start: テスト開始日
        test_end: テスト終了日
    
    Returns:
        DataFrame: 
            各パターン行 × 4月の日付カラム
            セルの値: {'rank20': ✓/✗, 'rank10': ✓/✗, 'profit': ✓/✗}
    """
    df_test = df_test[(df_test['date'] >= test_start) & (df_test['date'] <= test_end)].copy()
    df_test['dd'] = df_test['date'].str[4:6].astype(int)
    
    # テスト期間内のテスト日付リスト
    test_dates = sorted(df_test['date'].unique())
    
    # パターンごとの集計
    grouped = df_test.groupby(group_cols, as_index=False).agg({
        'diff_coins_normalized': ['mean', 'count'],
        'games_normalized': 'mean'
    })
    
    grouped.columns = ['_'.join(col).strip('_') if col[1] else col[0] for col in grouped.columns.values]
    
    # 勝率計算
    count_win = df_test[df_test['diff_coins_normalized'] > 0].groupby(group_cols).size()
    count_total = df_test.groupby(group_cols).size()
    grouped['win_rate'] = (count_win / count_total * 100).round(2).values
    
    # 毎日の検証
    result_rows = []
    
    for _, row in grouped.iterrows():
        pattern_key = tuple(row[col] for col in group_cols)
        
        row_dict = {col: row[col] for col in group_cols}
        row_dict['count'] = row['diff_coins_normalized_count']
        
        # 毎日の結果
        for test_date in test_dates:
            df_daily = df_test[df_test['date'] == test_date]
            df_daily_pattern = df_daily[
                (df_daily[group_cols[0]] == pattern_key[0]) &
                (df_daily[group_cols[1]] == pattern_key[1])
            ]
            
            if len(df_daily_pattern) == 0:
                row_dict[f"d_{test_date}"] = None
                continue
            
            # その日の勝率計算
            daily_profit = (df_daily_pattern['diff_coins_normalized'] > 0).sum() / len(df_daily_pattern) * 100
            
            # ランク維持判定
            rank20_hit = pattern_key in rankings[pattern_name].get('win_rate', {}).get('top20', set())
            rank10_hit = pattern_key in rankings[pattern_name].get('win_rate', {}).get('top10', set())
            profit_hit = daily_profit > 0
            
            row_dict[f"d_{test_date}"] = {
                'rank20': '✓' if rank20_hit else '✗',
                'rank10': '✓' if rank10_hit else '✗',
                'profit': '✓' if profit_hit else '✗'
            }
        
        result_rows.append(row_dict)
    
    return pd.DataFrame(result_rows)
```

- [ ] **Step 2: Write test for compute_validation_metrics()**

```python
# 追加: test/test_backtest_validation.py

def test_compute_validation_metrics():
    """検証指標が正しく計算されることを確認"""
    df_test = pd.DataFrame({
        'date': ['20260401', '20260401', '20260402', '20260402'] * 2,
        'machine_number': [1, 2, 1, 2] * 2,
        'machine_name': ['AA', 'BB', 'AA', 'BB'] * 2,
        'last_digit': ['0', '1', '0', '1'] * 2,
        'diff_coins_normalized': [100, -50, 200, 50] * 2,
        'games_normalized': [50, 60, 70, 80] * 2
    })
    
    rankings = {
        'dd_tail': {
            'win_rate': {
                'top20': {(4, '0')},
                'top10': {(4, '0')},
                'threshold20': 50.0,
                'threshold10': 75.0
            }
        }
    }
    
    result = compute_validation_metrics(
        df_test, rankings, 'dd_tail', ['dd', 'last_digit']
    )
    
    assert isinstance(result, pd.DataFrame)
    assert 'd_20260401' in result.columns or 'd_20260402' in result.columns
```

- [ ] **Step 3: Run test to verify it passes**

```bash
python -m pytest test/test_backtest_validation.py::test_compute_validation_metrics -v
```

Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add dashboard/utils/backtest_helpers.py test/test_backtest_validation.py
git commit -m "feat: 検証指標計算関数 compute_validation_metrics() を実装"
```

---

## Task 4: page_15_backtest_validation.py — ページ基本構造とグラフ1（信頼度ランキング）

**Files:**
- Create: `dashboard/pages/page_15_backtest_validation.py`

- [ ] **Step 1: Create page_15 with page setup and load data**

```python
# dashboard/pages/page_15_backtest_validation.py

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from pathlib import Path
import sys

# 相対インポート
from ..utils.data_loader import load_machine_detailed_results
from ..utils.backtest_helpers import (
    compute_training_stats,
    compute_top_percentile_rankings,
    compute_validation_metrics
)
from ..utils.charts import create_bar_chart

st.set_page_config(page_title="バックテスト検証", layout="wide")

st.title("📊 バックテスト検証 (2026-01～03 → 2026-04)")
st.write("過去3ヶ月のランキングが4月で再現するか検証します。ホール別・複数パターン分析。")

# セッション状態からホール選択を取得
if 'hall_name' not in st.session_state or 'db_path' not in st.session_state:
    st.error("ホールを選択してください（サイドバー）")
    st.stop()

db_path = st.session_state.db_path

# データロード
@st.cache_data(ttl=3600)
def load_all_data(db_path):
    return load_machine_detailed_results(db_path)

df_all = load_all_data(db_path)

st.write(f"**選択ホール:** {st.session_state.hall_name}")
st.write(f"**データ件数:** {len(df_all):,}")

# 訓練統計計算
training_stats = compute_training_stats(df_all, "20260101", "20260331")
rankings = compute_top_percentile_rankings(training_stats)

st.success("✓ 訓練データ読込完了（1月～3月）")
```

- [ ] **Step 2: Add render_confidence_ranking_chart() for Graph A**

```python
# 追加: page_15_backtest_validation.py

def render_confidence_ranking_chart(rankings: Dict, pattern_name: str):
    """信頼度ランキングTOP10（勝率/差枚/G数別）"""
    if pattern_name not in rankings or len(rankings[pattern_name]) == 0:
        st.warning(f"パターン {pattern_name} のデータがありません")
        return
    
    metrics = ['win_rate', 'avg_diff', 'avg_games']
    data = []
    
    for metric in metrics:
        if metric not in rankings[pattern_name]:
            continue
        
        ranking_info = rankings[pattern_name][metric]
        threshold20 = ranking_info.get('threshold20', 0)
        count = len(ranking_info.get('top20', set()))
        
        data.append({
            'metric': f"{metric}",
            'count': count,
            'threshold': threshold20
        })
    
    if not data:
        st.info("有効なランキングデータがありません")
        return
    
    df_chart = pd.DataFrame(data)
    fig = go.Figure()
    
    fig.add_trace(go.Bar(
        x=df_chart['metric'],
        y=df_chart['count'],
        text=df_chart['count'],
        textposition='auto',
        marker_color=['#1f77b4', '#ff7f0e', '#2ca02c']
    ))
    
    fig.update_layout(
        title=f"信頼度ランキングTOP10 ({pattern_name})",
        xaxis_title="指標",
        yaxis_title="TOP20%に入るパターン数",
        height=400,
        showlegend=False
    )
    
    st.plotly_chart(fig, use_container_width=True)
```

- [ ] **Step 3: Run page to verify no errors**

```bash
cd C:\Users\apto117\Documents\pachinko-analyzer\src\2026project
streamlit run main_app.py
```

Navigate to page_15 in sidebar. Expected: Page loads without errors, shows "訓練データ読込完了".

- [ ] **Step 4: Commit**

```bash
git add dashboard/pages/page_15_backtest_validation.py
git commit -m "feat: page_15 基本構造とグラフA（信頼度ランキング）を実装"
```

---

## Task 5: page_15 — グラフ2（指標分布）と グラフ3（ヒートマップ）

**Files:**
- Modify: `dashboard/pages/page_15_backtest_validation.py`

- [ ] **Step 1: Add render_metrics_distribution_chart()**

```python
# 追加: page_15_backtest_validation.py の render_confidence_ranking_chart() 下に

def render_metrics_distribution_chart(stats_dict: Dict[str, pd.DataFrame], pattern_name: str):
    """指標の分布（全パターンの平均）"""
    if pattern_name not in stats_dict:
        st.warning(f"パターン {pattern_name} のデータがありません")
        return
    
    df = stats_dict[pattern_name]
    
    fig = go.Figure()
    
    # 勝率の平均
    if 'win_rate' in df.columns:
        avg_wr = df['win_rate'].mean()
        fig.add_trace(go.Bar(name='勝率(%)', x=['勝率'], y=[avg_wr]))
    
    # 平均差枚の平均（正規化）
    if 'diff_coins_normalized_mean' in df.columns:
        avg_diff = df['diff_coins_normalized_mean'].mean()
        fig.add_trace(go.Bar(name='差枚(平均)', x=['差枚'], y=[avg_diff]))
    
    # 平均G数の平均（正規化）
    if 'games_normalized_mean' in df.columns:
        avg_games = df['games_normalized_mean'].mean()
        fig.add_trace(go.Bar(name='G数(平均)', x=['G数'], y=[avg_games]))
    
    fig.update_layout(
        title=f"指標の分布 ({pattern_name})",
        barmode='group',
        height=400,
        xaxis_title="指標",
        yaxis_title="値"
    )
    
    st.plotly_chart(fig, use_container_width=True)
```

- [ ] **Step 2: Add render_heatmap_chart() for heatmap**

```python
# 追加: page_15_backtest_validation.py

def render_heatmap_chart(stats_dict: Dict[str, pd.DataFrame], pattern_name: str):
    """ヒートマップ（DD×台末尾の信頼度など）"""
    if pattern_name not in stats_dict:
        st.warning(f"パターン {pattern_name} のデータがありません")
        return
    
    df = stats_dict[pattern_name]
    
    # pattern_name から軸を判定
    if 'dd_tail' in pattern_name:
        x_col, y_col = 0, 1  # (dd, last_digit)
    elif 'dd_machine' in pattern_name:
        x_col, y_col = 0, 1  # (dd, machine_number)
    elif 'dd_type' in pattern_name:
        x_col, y_col = 0, 1  # (dd, machine_name)
    else:
        st.info("ヒートマップ非対応のパターンです")
        return
    
    # ピボットテーブル作成
    pivot = df.pivot_table(
        values='win_rate',
        index=df.columns[y_col],
        columns=df.columns[x_col],
        aggfunc='mean'
    )
    
    fig = go.Figure(data=go.Heatmap(
        z=pivot.values,
        x=pivot.columns,
        y=pivot.index,
        colorscale='RdYlGn',
        zmid=50
    ))
    
    fig.update_layout(
        title=f"ヒートマップ信頼度 ({pattern_name})",
        xaxis_title=df.columns[x_col],
        yaxis_title=df.columns[y_col],
        height=500
    )
    
    st.plotly_chart(fig, use_container_width=True)
```

- [ ] **Step 3: Update page to call all 3 charts for first pattern (dd_tail)**

```python
# ページ下部に追加: page_15_backtest_validation.py

st.markdown("---")
st.subheader("📈 DD × 台末尾 分析")

col1, col2 = st.columns(2)

with col1:
    render_confidence_ranking_chart(rankings, 'dd_tail')
with col2:
    render_metrics_distribution_chart(training_stats, 'dd_tail')

render_heatmap_chart(training_stats, 'dd_tail')
```

- [ ] **Step 4: Run page to verify all 3 charts display**

```bash
streamlit run main_app.py
```

Navigate to page_15. Expected: 3 charts render without errors for DD×台末尾.

- [ ] **Step 5: Commit**

```bash
git add dashboard/pages/page_15_backtest_validation.py
git commit -m "feat: グラフ2（指標分布）とグラフ3（ヒートマップ）を実装"
```

---

## Task 6: page_15 — 検証テーブル生成ロジック

**Files:**
- Modify: `dashboard/pages/page_15_backtest_validation.py`

- [ ] **Step 1: Add generate_validation_table()**

```python
# 追加: page_15_backtest_validation.py

def generate_validation_table(
    df_test: pd.DataFrame,
    training_stats: Dict,
    pattern_name: str,
    group_cols: list,
    train_data: pd.DataFrame
) -> pd.DataFrame:
    """
    検証テーブル生成（左：過去 | 中央：4月毎日 | 右：集計）
    """
    # 検証指標計算
    rankings = compute_top_percentile_rankings(training_stats)
    validation_df = compute_validation_metrics(
        df_test, rankings, pattern_name, group_cols
    )
    
    # 訓練データの過去統計を追加（左側）
    train_agg = train_data.groupby(group_cols, as_index=False).agg({
        'diff_coins_normalized': 'mean',
        'games_normalized': 'mean'
    })
    
    # 結合
    result = validation_df.copy()
    
    # 過去のランク情報を左側に追加
    training_stats_df = training_stats[pattern_name].copy()
    training_stats_df = training_stats_df.rename(columns={
        'diff_coins_normalized_mean': '過去差枚',
        'games_normalized_mean': '過去G数',
        'win_rate': '過去勝率',
        'diff_coins_normalized_count': '出現回数'
    })
    
    # マージ
    merge_cols = group_cols
    result = result.merge(training_stats_df[merge_cols + ['過去勝率', '過去差枚', '過去G数', '出現回数']], 
                          on=merge_cols, how='left')
    
    # 右側の集計（TOP20%維持率など）を計算
    test_dates = sorted([c for c in result.columns if c.startswith('d_')])
    
    def calc_top20_ratio(row):
        count = sum(1 for d in test_dates if row.get(d) and row[d].get('rank20') == '✓')
        return f"{count}/{len(test_dates)}" if test_dates else "N/A"
    
    def calc_top10_ratio(row):
        count = sum(1 for d in test_dates if row.get(d) and row[d].get('rank10') == '✓')
        return f"{count}/{len(test_dates)}" if test_dates else "N/A"
    
    def calc_profit_ratio(row):
        count = sum(1 for d in test_dates if row.get(d) and row[d].get('profit') == '✓')
        return f"{count}/{len(test_dates)}" if test_dates else "N/A"
    
    result['TOP20%維持率'] = result.apply(calc_top20_ratio, axis=1)
    result['TOP10%維持率'] = result.apply(calc_top10_ratio, axis=1)
    result['利益性維持率'] = result.apply(calc_profit_ratio, axis=1)
    
    # カラム順序整理（左 | 中央日付 | 右集計）
    left_cols = group_cols + ['過去勝率', '過去差枚', '過去G数', '出現回数']
    right_cols = ['TOP20%維持率', 'TOP10%維持率', '利益性維持率']
    middle_cols = test_dates
    
    final_cols = left_cols + middle_cols + right_cols
    result = result[[c for c in final_cols if c in result.columns]]
    
    return result
```

- [ ] **Step 2: Add render_validation_table()**

```python
# 追加: page_15_backtest_validation.py

def render_validation_table(
    df_test: pd.DataFrame,
    training_stats: Dict,
    pattern_name: str,
    group_cols: list,
    train_data: pd.DataFrame
):
    """
    検証テーブルをStreamlitで表示（ソート・フィルタ付き）
    """
    table_df = generate_validation_table(df_test, training_stats, pattern_name, group_cols, train_data)
    
    st.markdown(f"### テーブル: {pattern_name}")
    
    # ソートオプション
    sort_col = st.selectbox(
        f"ソート対象（{pattern_name}）",
        options=table_df.columns,
        key=f"sort_{pattern_name}",
        index=0
    )
    
    # フィルタオプション（信頼度による絞込）
    if 'TOP20%維持率' in table_df.columns:
        min_ratio = st.slider(
            f"最小TOP20%維持率（{pattern_name}）",
            min_value=0,
            max_value=20,
            value=5,
            step=1,
            key=f"filter_{pattern_name}"
        )
        # フィルタ適用
        table_df = table_df[
            table_df['TOP20%維持率'].str.extract(r'(\d+)', expand=False).astype(int) >= min_ratio
        ]
    
    # ソート適用
    table_df = table_df.sort_values(by=sort_col, ascending=False, key=abs)
    
    # 表示（スクロール可能）
    st.dataframe(table_df, use_container_width=True)
```

- [ ] **Step 3: Update page main to call render_validation_table() for dd_tail**

```python
# page_15 の DD×台末尾 セクション下部に追加

render_validation_table(df_all, training_stats, 'dd_tail', ['dd', 'last_digit'], df_all)
```

- [ ] **Step 4: Run page and test table rendering**

```bash
streamlit run main_app.py
```

Navigate to page_15. Expected: Table displays with sortable/filterable columns.

- [ ] **Step 5: Commit**

```bash
git add dashboard/pages/page_15_backtest_validation.py
git commit -m "feat: 検証テーブル生成・表示ロジックを実装"
```

---

## Task 7: page_15 — 残り5パターンをループで全て表示

**Files:**
- Modify: `dashboard/pages/page_15_backtest_validation.py`

- [ ] **Step 1: Add loop to render all 6 patterns**

```python
# page_15 の DD×台末尾 セクション下部に追加

patterns = [
    ('dd_tail', ['dd', 'last_digit'], 'DD × 台末尾'),
    ('dd_machine', ['dd', 'machine_number'], 'DD × 台番号'),
    ('dd_type', ['dd', 'machine_name'], 'DD × 機種'),
    # ('weekday_tail', ['weekday', 'last_digit'], '曜日 × 台末尾'),  # Task 8で実装
    # ('weekday_machine', ['weekday', 'machine_number'], '曜日 × 台番号'),
    # ('weekday_type', ['weekday', 'machine_name'], '曜日 × 機種'),
]

for pattern_name, group_cols, display_name in patterns:
    st.markdown("---")
    st.subheader(f"📈 {display_name} 分析")
    
    col1, col2 = st.columns(2)
    
    with col1:
        render_confidence_ranking_chart(rankings, pattern_name)
    with col2:
        render_metrics_distribution_chart(training_stats, pattern_name)
    
    render_heatmap_chart(training_stats, pattern_name)
    
    render_validation_table(df_all, training_stats, pattern_name, group_cols, df_all)
```

- [ ] **Step 2: Run page and verify all 3 DD patterns display**

```bash
streamlit run main_app.py
```

Expected: DD×台末尾, DD×台番号, DD×機種の3セクションが順に表示される。

- [ ] **Step 3: Commit**

```bash
git add dashboard/pages/page_15_backtest_validation.py
git commit -m "feat: DD別3パターン（台末尾・台番号・機種）をループで全て表示"
```

---

## Task 8: backtest_helpers.py — 曜日別パターン対応

**Files:**
- Modify: `dashboard/utils/backtest_helpers.py`

- [ ] **Step 1: Update compute_training_stats() to handle weekday**

```python
# 修正: dashboard/utils/backtest_helpers.py の compute_training_stats() 内

# 曜日情報を追加
df_train['weekday'] = pd.to_datetime(df_train['date'], format='%Y%m%d').dt.day_name()
# または daily_hall_summary から取得（別タスク）

patterns = {
    'dd_tail': ['dd', 'last_digit'],
    'dd_machine': ['dd', 'machine_number'],
    'dd_type': ['dd', 'machine_name'],
    'weekday_tail': ['weekday', 'last_digit'],
    'weekday_machine': ['weekday', 'machine_number'],
    'weekday_type': ['weekday', 'machine_name']
}

# ループは同じ処理を繰り返す（weekday パターンも同じロジック）
```

- [ ] **Step 2: Test weekday patterns**

```python
# test/test_backtest_validation.py に追加

def test_compute_training_stats_weekday():
    """曜日別パターンの集計が正しく行われることを確認"""
    df = pd.DataFrame({
        'date': ['20260101', '20260107', '20260114', '20260121'] * 3,  # 金曜日複数
        'machine_number': [1, 2, 1, 2] * 3,
        'machine_name': ['AA', 'BB', 'AA', 'BB'] * 3,
        'last_digit': ['0', '1', '0', '1'] * 3,
        'diff_coins_normalized': [100, -50, 200, 0] * 3,
        'games_normalized': [50, 60, 70, 80] * 3
    })
    
    result = compute_training_stats(df)
    
    assert 'weekday_tail' in result
    assert len(result['weekday_tail']) > 0
```

- [ ] **Step 3: Run test**

```bash
python -m pytest test/test_backtest_validation.py::test_compute_training_stats_weekday -v
```

Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add dashboard/utils/backtest_helpers.py test/test_backtest_validation.py
git commit -m "feat: 曜日別パターン（台末尾・台番号・機種）を compute_training_stats() に追加"
```

---

## Task 9: page_15 — 曜日別3パターンをループで追加

**Files:**
- Modify: `dashboard/pages/page_15_backtest_validation.py`

- [ ] **Step 1: Update patterns list to include weekday patterns**

```python
# 修正: page_15_backtest_validation.py の patterns リスト

patterns = [
    ('dd_tail', ['dd', 'last_digit'], 'DD × 台末尾'),
    ('dd_machine', ['dd', 'machine_number'], 'DD × 台番号'),
    ('dd_type', ['dd', 'machine_name'], 'DD × 機種'),
    ('weekday_tail', ['weekday', 'last_digit'], '曜日 × 台末尾'),
    ('weekday_machine', ['weekday', 'machine_number'], '曜日 × 台番号'),
    ('weekday_type', ['weekday', 'machine_name'], '曜日 × 機種'),
]
```

- [ ] **Step 2: Run page and verify all 6 patterns display**

```bash
streamlit run main_app.py
```

Expected: 6つのセクション（DD3 + 曜日3）が順に表示。

- [ ] **Step 3: Commit**

```bash
git add dashboard/pages/page_15_backtest_validation.py
git commit -m "feat: 曜日別3パターンを page_15 に追加（全6パターン完成）"
```

---

## Task 10: dashboard/config/constants.py — ページ定数追加

**Files:**
- Modify: `dashboard/config/constants.py`

- [ ] **Step 1: Add page_15 to PAGE_REGISTRY**

```python
# 修正: dashboard/config/constants.py の PAGE_REGISTRY に追加

PAGE_REGISTRY = {
    # ... 既存ページ ...
    15: {
        "name": "バックテスト検証",
        "file": "page_15_backtest_validation",
        "icon": "📊"
    }
}
```

- [ ] **Step 2: Commit**

```bash
git add dashboard/config/constants.py
git commit -m "feat: page_15 をPAGE_REGISTRYに登録"
```

---

## Task 11: dashboard/main.py — ルーティング統合

**Files:**
- Modify: `dashboard/main.py`

- [ ] **Step 1: Verify page_15 is auto-loaded by routing**

Streamlit の動的ページロード仕様により、`dashboard/pages/page_15_backtest_validation.py` が自動検出される。

```bash
streamlit run main_app.py
```

Expected: Sidebar に「page_15: バックテスト検証」が表示される。

- [ ] **Step 2: Verify clicking the page loads without errors**

Sidebar で page_15 をクリック。Expected: ページが正常にロード。

- [ ] **Step 3: No explicit edit to main.py needed**

Streamlit の自動ページディスカバリーにより、`main.py` への修正は不要。

---

## Task 12: テスト最終確認・全テスト実行

**Files:**
- Test: `test/test_backtest_validation.py`

- [ ] **Step 1: Run all backtest validation tests**

```bash
python -m pytest test/test_backtest_validation.py -v
```

Expected: All tests PASS (現在 ~6件)

- [ ] **Step 2: Run full test suite to ensure no regression**

```bash
python -m pytest test/ -v
```

Expected: test_filters.py (9件) + test_charts.py (6件) + test_backtest_validation.py (~6件) = 21件 以上 PASS

- [ ] **Step 3: Commit final test results**

```bash
git add test/test_backtest_validation.py
git commit -m "test: バックテスト検証の全テストがPASS"
```

---

## Task 13: 手動テスト・E2E検証

**Files:** なし（UI検証）

- [ ] **Step 1: Start Streamlit**

```bash
streamlit run main_app.py
```

- [ ] **Step 2: ホール選択 → page_15 へナビゲート**

1. Sidebar で任意のホール選択
2. Sidebar で「page_15: バックテスト検証」クリック

Expected: ページロード、訓練データ読込完了メッセージ表示

- [ ] **Step 3: グラフ・テーブル表示確認**

- 信頼度ランキング棒グラフが表示
- 指標分布グラフが表示
- ヒートマップが表示
- テーブルがソート・フィルタ可能

Expected: All 3 graphs + 1 table per pattern, 6 patterns total

- [ ] **Step 4: テーブルのソート・フィルタ機能確認**

- 「ソート対象」ドロップダウンで別カラムを選択 → テーブル並び替え
- 「最小TOP20%維持率」スライダーを調整 → テーブル絞込

Expected: Both features work smoothly

- [ ] **No additional commit needed** 

Streamlit はリアルタイムリロードするため、手動テスト時に自動保存されない。

---

## Task 14: ドキュメント・README 更新

**Files:**
- Modify: `CLAUDE.md`
- Create: `document/page_15_backtest_validation_guide.md` (オプション)

- [ ] **Step 1: Update CLAUDE.md に page_15 追加**

```markdown
# CLAUDE.md の「現在のディレクトリ構造」に追加

│       ├── page_14_notion_exporter.py     ← Notion連携
│       ├── page_15_backtest_validation.py ← バックテスト検証（新規）
│       └── page_16_future.py (if needed)

# 「ドキュメント参照先」に追加

| document/page_15_backtest_validation_guide.md | page_15 使用ガイド |
```

- [ ] **Step 2: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: page_15 バックテスト検証をCLAUDE.mdに追記"
```

---

## Summary

| タスク | 内容 | ファイル数 | 行数目安 |
|-------|------|---------|--------|
| 1-3 | backtest_helpers.py 実装（計算ロジック） | 1 | 300行 |
| 4-9 | page_15 実装（UI・グラフ・テーブル） | 1 | 400行 |
| 10-11 | ルーティング統合 | 1 | 5行 |
| 12 | テスト | 1 | 150行 |
| 13 | 手動E2E検証 | - | - |
| 14 | ドキュメント | 1 | 10行 |
| **合計** | | 5 | ~860行 |

**全14タスク・14ステップに分割。各ステップ2～5分で完成。**
