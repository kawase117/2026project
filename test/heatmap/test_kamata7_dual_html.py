from pathlib import Path

from Heatmap.generate_kamata7_dual_html import build_kamata7_dual_html


def test_kamata7_dual_html_contains_both_floors_and_controls() -> None:
    html = build_kamata7_dual_html()

    assert "<script src=\"https://cdn.tailwindcss.com\"></script>" in html
    assert "https://cdn.plot.ly/plotly-" in html
    assert "蒲田7 2F / 3F 同時ヒートマップ" in html
    assert "2F" in html
    assert "3F" in html
    assert "勝率(%)" in html
    assert "平均差枚" not in html
    assert "平均G数" not in html


def test_kamata7_dual_html_can_be_written() -> None:
    output_path = Path("tmp") / "kamata7_2f_3f_heatmap_test.html"

    build_kamata7_dual_html(output_path=output_path)

    assert output_path.exists()
    text = output_path.read_text(encoding="utf-8")
    assert "蒲田7 2F / 3F 同時ヒートマップ" in text
    assert text.count("plotly-graph-div") == 2
