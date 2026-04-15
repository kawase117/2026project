import pytest
import pandas as pd
import plotly.graph_objects as go
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

def make_sample_df():
    return pd.DataFrame({
        'x_col': ['月', '火', '水'],
        'y_col': [50.0, 55.0, 60.0],
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
        assert len(fig.data) > 0

    def test_空DataFrameでも例外を出さない(self):
        from dashboard.utils.charts import create_line_chart
        fig = create_line_chart(pd.DataFrame(), x='x', y='y', title='空')
        assert isinstance(fig, go.Figure)

class TestCreateScatterChart:
    def test_正常なDataFrameからfigオブジェクトを返す(self):
        from dashboard.utils.charts import create_scatter_chart
        df = make_sample_df()
        fig = create_scatter_chart(df, x='x_col', y='y_col', title='テスト')
        assert isinstance(fig, go.Figure)
        assert len(fig.data) > 0

    def test_空DataFrameでも例外を出さない(self):
        from dashboard.utils.charts import create_scatter_chart
        fig = create_scatter_chart(pd.DataFrame(), x='x', y='y', title='空')
        assert isinstance(fig, go.Figure)
