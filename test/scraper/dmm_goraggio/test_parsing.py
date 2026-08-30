from datetime import date

from scraper.dmm_goraggio.parsing import discover_data_url, parse_detail, parse_machine_list


def test_discover_data_url_from_dmm_script() -> None:
    html = "<script>iframe.src = 'https://daidata.goraggio.com/dedamajyoho-P-townDMMpachi/101426'</script>"
    assert discover_data_url(html).endswith("/101426")


def test_parse_machine_list() -> None:
    html = """
    <table><thead><tr><th></th><th>台番号</th><th>貸玉</th><th>機種名</th><th>BB回数</th><th>RB回数</th><th>前日最終スタート</th><th>スタート回数</th></tr></thead>
    <tbody><tr><td></td><td><a href="/base/detail?unit=1001">1001</a></td><td>21.74円スロット</td><td>テスト機</td><td>27</td><td>13</td><td>5</td><td>114</td></tr></tbody></table>
    """
    rows = parse_machine_list(html, "https://example.com/base")
    assert rows == [
        {
            "machine_number": "1001",
            "rate": "21.74円スロット",
            "machine_name": "テスト機",
            "bb_count": 27,
            "rb_count": 13,
            "previous_final_start": 5,
            "current_start": 114,
            "detail_url": "https://example.com/base/detail?unit=1001",
        }
    ]


def test_parse_detail_only_expected_date_and_estimates_diff() -> None:
    html = """
    <article><div id="contentsHeader"><h2>テスト機</h2><div>1001番台</div><div class="suppleMeta"><time>2026.08.15 22:57</time></div></div>
    <section><div class="swiper-slide"><h4 class="Text-Left-01">8月15日</h4>
      <table class="overviewTable"><tr><th>BB</th><th>RB</th><th>スタート回数</th></tr><tr><td>27</td><td>13</td><td>114</td></tr></table>
      <table class="overviewTable3"><tr><th>最大持ち玉</th><td>721</td><th>累計スタート</th><td>6289</td></tr><tr><th>前日最終スタート</th><td>5</td><th>合成確率</th><td>157.2</td></tr><tr><th>BB確率</th><td>232.9</td><th>RB確率</th><td>483.8</td></tr></table>
    </div><div id="list"><div class="swiper-slide"><h4 class="Text-Left-01">8月15日</h4><table class="numericValueTable"><tr><th>大当たり</th><th>スタート</th><th>出玉</th><th>種別</th><th>時間</th></tr><tr><td>27</td><td>1</td><td>45</td><td>BB</td><td>19:05</td></tr></table></div><div class="swiper-slide"><h4 class="Text-Left-01">8月14日</h4><table class="numericValueTable"><tr><th>大当たり</th></tr></table></div></div>
    <div id="today_graph"><svg><text x="5" y="40"><tspan>8000</tspan></text><text x="5" y="190"><tspan>0</tspan></text><text x="5" y="360"><tspan>-8000</tspan></text><path d="M0,200 ,290,344" stroke="#ff0000"></path></svg></div></section></article>
    """
    detail, svg = parse_detail(html, date(2026, 8, 15), "1001")
    assert detail["business_date"] == "2026-08-15"
    assert detail["games"] == 6289
    assert detail["history"] == [{"jackpot_number": 27, "start": 1, "payout": 45, "kind": "BB", "time": "19:05"}]
    assert detail["latest_diff_estimated"] == -6776
    assert "<svg>" in svg
