"""予測の下書きプロンプトに、予測の形(prediction-format スキル)と当日の基準が入ること。"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import run_morning_docs as morning  # noqa: E402


def write_frozen(directory, key, day, names):
    obj = {"models": [{"machine_name": n} for n in names]}
    path = directory / f"{key}{morning.BASE_RULE_SUFFIX}__{day}.json"
    path.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")


def test_baseline_uses_frozen_plan_and_kamata7_is_reference_only(tmp_path, monkeypatch):
    monkeypatch.setattr(morning, "FORWARD_DIR", tmp_path)
    write_frozen(tmp_path, "rakuen", "20261101", ["A", "B", "C"])
    write_frozen(tmp_path, "kamata7", "20261101", ["D", "E", "F"])
    assert "`基準: A・B・C`" in morning.baseline_block("rakuen", "20261101", False)
    assert "`基準: D・E・F`" in morning.baseline_block("kamata7", "20261101", False)
    assert "`基準: D・E・F`" in morning.baseline_block("kamata7", "20261101", True)


def test_baseline_absent_for_hall_without_rule(tmp_path, monkeypatch):
    monkeypatch.setattr(morning, "FORWARD_DIR", tmp_path)
    assert "基準の行は書かない" in morning.baseline_block("hiroki_max", "20261101", True)


def test_form_is_read_from_skill():
    form = morning.prediction_form()
    assert "基準を最初に載せる" in form
    assert "form:start" not in form and "form:end" not in form
