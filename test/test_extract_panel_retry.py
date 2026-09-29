"""台データ画面の数字がたまたま空で返ったら、1回だけ読み直す（2026-09-29）。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scraper" / "twitter_monitor"))

import extract_answers  # noqa: E402

ENTRIES = [{"hall_hint": None, "machine_name": "A", "machine_numbers": ["1", "2", "3", "4", "5"], "note": None}]
PANEL = {"machine_number": "1", "machine_name": "A", "bb": 10, "rb": 5, "games": 3000}


def _fake(responses, calls):
    def extract_image(image_path):
        calls.append(image_path)
        return responses[len(calls) - 1], "raw"

    return extract_image


def test_empty_panels_are_retried_once_and_replaced(monkeypatch):
    calls = []
    first = {"hall_hint": None, "date_hint": None, "entries": ENTRIES, "panels": []}
    second = {"hall_hint": None, "date_hint": None, "entries": [], "panels": [PANEL]}
    monkeypatch.setattr(extract_answers, "extract_image", _fake([first, second], calls))
    parsed, _ = extract_answers.extract_image_with_panel_retry("x.jpg")
    assert len(calls) == 2
    assert parsed["panels"] == [PANEL] and parsed["entries"] == ENTRIES


def test_table_image_stays_empty_after_one_retry(monkeypatch):
    calls = []
    empty = {"hall_hint": None, "date_hint": None, "entries": ENTRIES, "panels": []}
    monkeypatch.setattr(extract_answers, "extract_image", _fake([empty, empty, empty], calls))
    parsed, _ = extract_answers.extract_image_with_panel_retry("x.jpg")
    assert len(calls) == 2 and parsed["panels"] == []


def test_no_retry_when_numbers_are_read(monkeypatch):
    calls = []
    ok = {"hall_hint": None, "date_hint": None, "entries": ENTRIES, "panels": [PANEL]}
    monkeypatch.setattr(extract_answers, "extract_image", _fake([ok], calls))
    extract_answers.extract_image_with_panel_retry("x.jpg")
    assert len(calls) == 1
