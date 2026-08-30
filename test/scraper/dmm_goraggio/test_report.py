from scraper.dmm_goraggio.report import build_analysis, build_html


def test_report_contains_modes_and_mobile_contract() -> None:
    source = {
        "mode": "quick",
        "business_date": "2026-08-15",
        "observed_at": "2026-08-15T20:00:00+09:00",
        "hall_name": "ヒロキMAX蒲田店",
        "complete": True,
        "request_count": 4,
        "machines": [
            {"machine_number": "1001", "machine_name": "テスト機", "bb_count": 3, "rb_count": 2, "current_start": 10}
        ],
        "details": {},
    }
    analysis = build_analysis(source)
    html = build_html(analysis)
    assert analysis["machine_count"] == 1
    assert 'name="viewport"' in html
    assert "Quickでは詳細未取得台" in html
    assert "ヒロキMAX蒲田店" in html
