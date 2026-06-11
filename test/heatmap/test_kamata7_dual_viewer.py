from pathlib import Path

from Heatmap.HeatmapKamata7Dual import load_report_html


def test_kamata7_dual_viewer_loads_report_html() -> None:
    html = load_report_html(Path("Heatmap") / "kamata7_2f_3f_heatmap.html")

    assert "蒲田7 2F / 3F 同時ヒートマップ" in html
    assert html.count("plotly-graph-div") == 2
