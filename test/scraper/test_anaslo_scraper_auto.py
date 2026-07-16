import asyncio
import sqlite3
import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "scraper"))


def test_extract_date_links_uses_actual_hrefs() -> None:
    from anaslo_scraper_auto import extract_date_links

    html = """
    <html><body>
      <a href="https://ana-slo.com/2026-07-15-%e6%a5%bd%e5%9c%92%e8%92%b2%e7%94%b0%e5%ba%97-data/">2026/07/15(水)</a>
      <a href="/2026-07-14-%e6%a5%bd%e5%9c%92%e8%92%b2%e7%94%b0%e5%ba%97-data/">2026/07/14(火)</a>
    </body></html>
    """

    links = extract_date_links(html)

    assert set(links) == {"20260715", "20260714"}
    assert links["20260714"].startswith("https://ana-slo.com/")


def test_classify_page_html_distinguishes_list_detail_and_blocked() -> None:
    from anaslo_scraper_auto import classify_page_html

    list_html = """
    <html><body>
      <p>日付をクリックすると詳細データが閲覧出来ます。</p>
      <a href="/2026-07-15-hall-data/">2026/07/15</a>
      <div>{}</div>
    </body></html>
    """.format("x" * 500)
    detail_html = """
    <html><body><h4>全データ一覧</h4>
      <table><tr><th>台番号</th><th>機種名</th></tr>
      <tr><td>101</td><td>ハナハナ</td></tr></table>
    </body></html>
    """

    assert classify_page_html(list_html, 200) == "list"
    assert classify_page_html(detail_html, 200) == "detail"
    assert classify_page_html("<html><body>403</body></html>", 403) == "blocked"
    assert classify_page_html("<html><body>Just a moment...</body></html>", 403) == "challenge"
    normal_html = (
        "<html><head><script>challenge-platform</script></head><body>正常な一覧" + ("x" * 500) + "</body></html>"
    )
    assert classify_page_html(normal_html, 200) == "unknown"


def test_default_date_range_is_resolved_from_the_list() -> None:
    import anaslo_scraper_auto as module

    assert module.DEFAULT_START_DATE is None
    assert module.DEFAULT_END_DATE is None


def test_save_to_database_is_idempotent_for_same_date_and_hall(tmp_path) -> None:
    from anaslo_scraper_auto import save_to_database

    payload = {
        "date": "20260715",
        "hall_name": "test-hall",
        "url": "https://example.invalid/detail",
        "all_data": [{"台番号": "101", "機種名": "test", "G数": "1000"}],
        "last_digit_data": [{"末尾": "1", "台数": "1"}],
    }
    db_path = tmp_path / "test.db"

    assert asyncio.run(save_to_database(payload, db_path=str(db_path)))
    assert asyncio.run(save_to_database(payload, db_path=str(db_path)))

    conn = sqlite3.connect(db_path)
    assert conn.execute("SELECT COUNT(*) FROM machine_data").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM last_digit_summary").fetchone()[0] == 1
    conn.close()
