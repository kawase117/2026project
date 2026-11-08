"""朝文書のジャグラー候補表の対象ホールを検証する。"""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import run_morning_docs as morning  # noqa: E402


def _part(tmp_path, key):
    (tmp_path / f"{key}.juggler.md").write_text(
        "履歴の翌日平均 0.14\n 3346 マイジャグラーV 1 5000 30 0 True x\n", encoding="utf-8"
    )


def _announce(
    tmp_path, monkeypatch, key, day, claims, raw_text, *, hall=None, target=None, voided=False, amendments=None
):
    directory = tmp_path / "announce"
    directory.mkdir(exist_ok=True)
    monkeypatch.setattr(morning, "ANNOUNCE_DIR", directory)
    ledger_key = "kamata1__test"
    entry = {
        "key": ledger_key,
        "hall": hall or morning.HALLS[key][0],
        "target_date": target or day,
        "voided": voided,
        "claims_detail": [{"machine_name": name} for name in claims],
        "unscored_claims": [{"machine_name": "ファンキージャグラー2"}],
    }
    (directory / "LEDGER.jsonl").write_text(json.dumps(entry, ensure_ascii=False), encoding="utf-8")
    (directory / f"{ledger_key}.json").write_text(
        json.dumps({"raw_text": raw_text, "amendments": amendments or []}, ensure_ascii=False), encoding="utf-8"
    )


def test_hall_and_rakuen_dates(tmp_path, monkeypatch):
    monkeypatch.setattr(morning, "ANNOUNCE_DIR", tmp_path / "announce")
    for key in ("mitoya", "hiroki_nishiguchi", "kamata7", "rakuen"):
        _part(tmp_path, key)
    text = morning.juggler_section(tmp_path, "20261130", ["mitoya", "hiroki_nishiguchi", "kamata7", "rakuen"])
    assert "| みとや大森町店 |" in text and "| 楽園蒲田店 |" in text
    assert "| ヒロキ蒲田西口店 |" not in text and "| 蒲田7 |" not in text
    assert morning.JUGGLER_STOPPED["kamata7"] in text
    text = morning.juggler_section(tmp_path, "20261201", ["rakuen"])
    assert "| 楽園蒲田店 |" not in text and "掲載終了" in text


@pytest.mark.parametrize(
    "claims,raw_text,voided,hall,target,amendments,expected",
    [
        (["ミスタージャグラー"], "→ミスタージャグラー？", False, None, None, None, False),
        (["マイジャグラーV"], "・マイジャグラーV", False, None, None, None, True),
        (["マイジャグラーV"], "・マイジャグラーV", True, None, None, None, False),
        ([], "・ファンキージャグラー2", False, None, None, None, False),
        (["マイジャグラーV"], "・マイジャグラーV", False, "別ホール", None, None, False),
        (["マイジャグラーV"], "・マイジャグラーV", False, None, "20261129", None, False),
        (["マイジャグラーV"], "・マイジャグラーV", False, None, None, [{"void": True}], False),
    ],
)
def test_kamata1_registered_announcement(
    tmp_path,
    monkeypatch,
    claims,
    raw_text,
    voided,
    hall,
    target,
    amendments,
    expected,
):
    day = "20261130"
    _part(tmp_path, "kamata1")
    _announce(
        tmp_path,
        monkeypatch,
        "kamata1",
        day,
        claims,
        raw_text,
        hall=hall,
        target=target,
        voided=voided,
        amendments=amendments,
    )
    text = morning.juggler_section(tmp_path, day, ["kamata1"])
    assert ("| 蒲田1 |" in text) is expected
