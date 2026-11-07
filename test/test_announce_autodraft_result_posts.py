"""結果の投稿は予告の下書きにしない(document/procedures/EVENTS.md の仕分けを機械に入れる)。"""

from datetime import datetime
from unittest import mock

from backtest import announce_autodraft as ad


def test_result_only_account_is_excluded():
    assert ad.is_result_post("slokotae7", "楽園蒲田店 新館 45/567台", "20261107")


def test_past_dated_result_is_excluded_for_any_account():
    assert ad.is_result_post("datagasubete", "11月3日(火) 楽園蒲田店 47/567台", "20261104")
    assert ad.is_result_post("Kamacho_data", "10月19日（月）総差枚！ 楽園蒲田", "20261020")


def test_same_day_heading_is_kept_as_announce():
    assert not ad.is_result_post("999999Q9Q", "7月1日（水） #東京大戦 明日行くならココが1番", "20260701")


def test_ordinary_announce_is_kept():
    assert not ad.is_result_post("kawasakislot", "11/7 楽園蒲田 末尾7ニブイチ", "20261107")
    assert not ad.is_result_post("kawasakislot", "明日の楽園蒲田は末尾7ニブイチ", "20261107")


def test_date_in_body_only_is_not_a_heading():
    assert not ad.is_result_post("kawasakislot", "明日の楽園蒲田。前回の10月17日(土)は強かった", "20261107")


def test_year_boundary_december_result_for_january_target():
    assert ad.is_result_post("datagasubete", "12月31日(木) 楽園蒲田店", "20270101")


def test_draft_for_date_skips_result_post():
    tweets = [
        {
            "handle": "slokotae7",
            "tweet_text": "11月6日(金) 楽園蒲田店 45/567台",
            "posted_at_jst": datetime(2026, 11, 6, 22, 0).isoformat(),
        }
    ]
    with (
        mock.patch.object(ad, "_fetch_recent_tweets", return_value=tweets),
        mock.patch.object(ad, "_build_claims") as build,
    ):
        assert ad.draft_for_date("20261107", dry_run=True) == []
    build.assert_not_called()
