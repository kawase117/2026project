"""`判断:` の行の台番号検査。発信者名に含まれる数字を台番号と誤判定しない。"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import run_morning_docs as rmd  # noqa: E402


def _errors(monkeypatch, line: str, allowed: set[str] | None = None) -> list[str]:
    monkeypatch.setattr(rmd, "announce_numbers", lambda key, today: allowed or set())
    return rmd.judgement_number_errors(line, "rakuen", "20261107")


def test_handle_with_digits_is_not_a_machine_number(monkeypatch):
    assert _errors(monkeypatch, "判断: 東京喰種を足す(minnade777judge の過去傾向)。") == []


def test_digits_before_letters_are_not_a_machine_number(monkeypatch):
    assert _errors(monkeypatch, "判断: 東京喰種を足す(999abc の投稿)。") == []


def test_handle_in_fullwidth_is_not_a_machine_number(monkeypatch):
    assert _errors(monkeypatch, "判断: 東京喰種を足す(ｍｉｎｎａｄｅ７７７ｊｕｄｇｅ)。") == []


def test_stray_machine_number_is_still_rejected(monkeypatch):
    errors = _errors(monkeypatch, "判断: 東京喰種の 777 と 1234番を推す。")
    assert len(errors) == 1
    assert "1234" in errors[0] and "777" in errors[0]


def test_number_in_announce_is_allowed(monkeypatch):
    assert _errors(monkeypatch, "判断: 東京喰種の 777 を推す。", allowed={"777"}) == []
