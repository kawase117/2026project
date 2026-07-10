"""
Pachinko Analyzer - Dashboard Main
パチスロ分析ダッシュボード メインアプリケーション
python -m streamlit run main_app.py
"""

# Import page modules
from .pages import (
    page_01_hall_overview,
    page_02_single_axis_viewer,
    page_04_dd_analysis,
    page_08_individual_machines,
    page_10_period_top10,
    page_11_cross_search,
    page_12_statistics,
    page_13_hall_selection,
    page_14_notion_exporter,
    page_15_backtest_validation,
    page_16_cross_search_bulk,
    page_17_heatmap,
    page_18_daily_report,
    page_19_daily_report_visual_test,
    page_20_theory_verification,
)
from .app_shell import render_app

# ページキーと関数のマッピング（config.constants.PAGE_DEFS のキーに対応）
PAGE_ROUTER = {
    "hall_overview": page_01_hall_overview.render,
    "single_axis_viewer": page_02_single_axis_viewer.render,
    "dd_analysis": page_04_dd_analysis.render,
    "individual_machines": page_08_individual_machines.render,
    "period_top10": page_10_period_top10.render,
    "cross_search": page_11_cross_search.render,
    "cross_search_bulk": page_16_cross_search_bulk.render,
    "statistics": page_12_statistics.render,
    "hall_selection": page_13_hall_selection.render,
    "notion_exporter": page_14_notion_exporter.render,
    "backtest_validation": page_15_backtest_validation.render,
    "heatmap": page_17_heatmap.render,
    "daily_report": page_18_daily_report.render,
    "daily_report_visual_test": page_19_daily_report_visual_test.render,
    "theory_verification": page_20_theory_verification.render,
}

render_app(PAGE_ROUTER)
