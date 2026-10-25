"""backfill_search --keyword: 検索語で絞った取得が、元の窓の進捗を上書きしない（2026-10-26）。"""

import sqlite3
import sys
from datetime import date
from pathlib import Path
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scraper" / "twitter_monitor"))

import backfill_search as bs  # noqa: E402

WINDOW = bs.DateWindow(date(2026, 8, 17), date(2026, 8, 20))


def _query(url):
    return parse_qs(urlparse(url).query)["q"][0]


def test_search_url_without_keyword_is_unchanged():
    assert _query(bs.search_url("pachi_slohunter", WINDOW)) == (
        "from:pachi_slohunter since:2026-08-17 until:2026-08-20"
    )


def test_search_url_with_keyword_narrows_the_query():
    assert _query(bs.search_url("pachi_slohunter", WINDOW, "ヒロキ")) == (
        "from:pachi_slohunter ヒロキ since:2026-08-17 until:2026-08-20"
    )


def test_progress_key_separates_keyword_runs():
    assert bs.progress_key("pachi_slohunter") == "pachi_slohunter"
    assert bs.progress_key("pachi_slohunter", "ヒロキ") == "pachi_slohunter#ヒロキ"


def test_keyword_progress_does_not_overwrite_the_full_window():
    con = sqlite3.connect(":memory:")
    bs.initialize_progress_table(con)
    bs.save_progress(con, bs.progress_key("pachi_slohunter"), WINDOW, 0, "failed")
    bs.save_progress(con, bs.progress_key("pachi_slohunter", "ヒロキ"), WINDOW, 12, "done")
    assert bs.progress_status(con, "pachi_slohunter", WINDOW) == "failed"
    assert bs.progress_status(con, "pachi_slohunter#ヒロキ", WINDOW) == "done"
    # --redo-failed は元の窓の failed だけを拾い、絞り込みの done は拾わない
    assert bs.should_process(bs.progress_status(con, "pachi_slohunter", WINDOW), True)
    assert not bs.should_process(bs.progress_status(con, "pachi_slohunter#ヒロキ", WINDOW), True)
