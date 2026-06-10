"""
ホール配置図ヒートマップ - 蒲田七 2F版
"""

from datetime import datetime

from heatmap_common import render_heatmap_page


render_heatmap_page(
    title="蒲田七 2F 配置図",
    subtitle="台番号の配置と性能を可視化します",
    coords_file="2F_floor_coordinates_kamata7.csv",
    db_path=r"C:\Users\apto117\Documents\pachinko-analyzer\src\2026project\db\マルハンメガシティ2000-蒲田7.db",
    date_key="heatmap7_date_range",
    metric_key="heatmap7_metric",
    default_start_date=datetime(2026, 1, 1),
    hall_name="マルハンメガシティ2000-蒲田7",
    floor="2F",
)
