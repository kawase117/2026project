"""ヒロキ蒲田西口店・ヒロキMAX蒲田店が予告・答え合わせの収集対象に登録されている（2026-10-25）。

hall_config.json に足しただけではツイート収集・台帳・予告の下書きには効かない。
東口と取り違えないこと（「ヒロキ」単独の語は使わない）も確かめる。
"""

import sys
from datetime import date
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scraper" / "twitter_monitor"))

import run_daily  # noqa: E402
from backtest import announce_autodraft, prediction_ledger  # noqa: E402
from hall_aliases import HALL_ALIASES, mentions_target_hall, plausible_halls  # noqa: E402

NISHI = "ヒロキ蒲田西口店"
MAX = "ヒロキMAX蒲田店"
HIGASHI = "ヒロキ東口店"
ON = date(2026, 10, 25)


@pytest.mark.parametrize(
    "text, expected",
    [
        ("10/26 ヒロキ蒲田西口 全台系", {NISHI}),
        ("ヒロキ西口の結果", {NISHI}),
        ("ヒロキMAX蒲田 取材", {MAX}),
        ("ヒロキMAXでイベント", {MAX}),
        ("ヒロキ東口 アスロボ7", {HIGASHI}),
        ("ヒロキの新台入替", set()),  # 「ヒロキ」単独は店舗を特定できない
    ],
)
def test_plausible_halls_distinguishes_three_hiroki_halls(text, expected):
    assert plausible_halls(text, ON) == expected


def test_mentions_target_hall_for_new_halls():
    assert mentions_target_hall("ヒロキ蒲田西口の結果", ON)
    assert mentions_target_hall("ヒロキMAX蒲田の結果", ON)


def test_hall_keywords_cover_both_halls_and_keep_higashi():
    kw = run_daily.HALL_KEYWORDS
    assert "ヒロキ西口" in kw[NISHI]
    assert "ヒロキMAX" in kw[MAX]
    assert kw[HIGASHI] == ("ヒロキ東口",)
    assert "ヒロキ蒲田西口" in run_daily.FULLTEXT_EXTRA_KEYWORDS
    assert "ヒロキMAX蒲田" in run_daily.FULLTEXT_EXTRA_KEYWORDS


def test_every_hall_keyword_hall_is_in_ledger_and_aliases():
    for hall in run_daily.HALL_KEYWORDS:
        assert hall in prediction_ledger.HALLS, hall
    for hall in (NISHI, MAX):
        assert hall in HALL_ALIASES


@pytest.mark.parametrize(
    "heading, expected",
    [
        ("ヒロキ蒲田西口店", NISHI),
        ("ヒロキ西口", NISHI),
        ("ヒロキMAX蒲田店", MAX),
        ("ヒロキ東口", HIGASHI),
    ],
)
def test_ledger_hall_of(heading, expected):
    assert prediction_ledger.hall_of(heading) == expected


def test_slohunter_account_is_monitored_for_both_halls():
    from config import ACCOUNTS

    assert ACCOUNTS["pachi_slohunter"]["hall"] == "hiroki_nishiguchi_max"
    # ホールのグループ名は --halls の絞り込みに使われるので、他アカウントと衝突しない
    others = {h for h, d in ACCOUNTS.items() if d["hall"] == "hiroki_nishiguchi_max"}
    assert others == {"pachi_slohunter"}


def test_ledger_keys_and_announce_slugs_are_unique_and_complete():
    assert set(prediction_ledger.HALL_KEY) == set(prediction_ledger.HALLS)
    keys = list(prediction_ledger.HALL_KEY.values())
    assert len(keys) == len(set(keys))
    slugs = [announce_autodraft._slug(h) for h in (NISHI, MAX, HIGASHI)]
    assert slugs == ["hiroki_nishiguchi", "hiroki_max", "hiroki"]
