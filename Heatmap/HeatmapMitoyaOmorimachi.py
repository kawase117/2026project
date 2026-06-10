"""
ホール配置図ヒートマップ - みとや大森町版
"""

from datetime import datetime

from heatmap_common import render_heatmap_page


render_heatmap_page(
    title="みとや大森町 配置図",
    subtitle="台番号の配置と性能を可視化します",
    coords_file="mitoya_omorimachi_floor_coordinates.csv",
    db_path=r"C:\Users\apto117\Documents\pachinko-analyzer\src\2026project\db\みとや大森町店.db",
    date_key="heatmap_mitoya_date_range",
    metric_key="heatmap_mitoya_metric",
    default_start_date=datetime(2026, 1, 1),
    hall_name="みとや大森町店",
    floor="2F",
)
