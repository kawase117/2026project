"""「楽園」の略記を楽園蒲田店と読むのは、別店舗の名前が続かないときだけ。"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scraper" / "twitter_monitor"))
from hall_aliases import plausible_halls  # noqa: E402

HALL = "楽園蒲田店"


@pytest.mark.parametrize(
    "text",
    [
        "11/7楽園溝の口 7の日は近隣対抗に燃える楽園溝の口",
        "10月24日(土) 楽園町田店 四星 ブラックホール",
        "11/7(土) 楽園渋谷駅前 『⑦の日』",
        "10月30日(金) 楽園渋谷道玄坂店",
        "楽園立川 激クレイジー",
        "楽園アメ横の結果",
        "楽園なんばの結果",
        "楽園柏。",
    ],
)
def test_other_branch_is_not_kamata(text):
    assert HALL not in plausible_halls(text, None)


@pytest.mark.parametrize(
    "text",
    [
        "明日の楽園蒲田は末尾7ニブイチ",
        "楽園は先バレあり",
        "楽園全店合同の取材",
        "楽園グループ全22店舗",
        "楽園合同イベント",
        "楽園の特定日",
        "楽園特定日",
        "楽園対抗！",
    ],
)
def test_kamata_or_group_wide_mention_is_kept(text):
    assert HALL in plausible_halls(text, None)


def test_kamata_named_alongside_other_branch_is_kept():
    assert HALL in plausible_halls("楽園溝の口と楽園蒲田の比較", None)
