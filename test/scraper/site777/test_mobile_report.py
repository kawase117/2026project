from scraper.site777.site777_mobile_report import build_html


def test_no_diff_data_defaults_to_non_diff_metrics() -> None:
    html = build_html(
        {
            "graph_eligible_count": 0,
            "graph_min_games": 2000,
            "models": [],
            "tails": [],
            "corners": [],
        }
    )

    assert "main: 'average_games'" in html
    assert "tail: 'average_highest_payout'" in html
    assert "three: 'average_games'" in html
    assert "metric = defaultMetric('main')" in html
    assert "metric=defaultMetric(scope)" in html
    assert "差枚・勝率ランキングは未表示" in html
