# -*- coding: utf-8 -*-
"""引退した規則は凍結の対象から外れ、凍結済みの plan の採点だけは続けられる。

2026-11-06: みとやのマイジャグラーVが撤去され、規則2本が毎朝 failed になっていた。
"""

import json
import os
import shutil
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

from backtest import forward  # noqa: E402
from backtest.prereg import PreRegistration  # noqa: E402

RETIRED = os.path.join(ROOT, "backtest", "prereg", "retired", "mitoya_mjv_prevph_top3.json")


def _dir_with_retired(tmp_path, monkeypatch):
    prereg_dir = tmp_path / "prereg"
    (prereg_dir / "retired").mkdir(parents=True)
    shutil.copy(RETIRED, prereg_dir / "retired")
    monkeypatch.setattr(forward, "PREREG_DIR", prereg_dir)
    return prereg_dir


def test_retired_rule_is_not_loaded_for_planning(tmp_path, monkeypatch):
    _dir_with_retired(tmp_path, monkeypatch)
    assert forward.load_preregs() == []


def test_retired_rule_can_still_be_scored(tmp_path, monkeypatch):
    _dir_with_retired(tmp_path, monkeypatch)
    frozen = PreRegistration.load(RETIRED).freeze_hash()
    reg = forward._reg_from_plan({"rule_id": "mitoya_mjv_prevph_top3", "freeze_hash": frozen})
    assert reg.rule_id == "mitoya_mjv_prevph_top3"


def test_myj6_rules_are_registered_and_v_rules_are_not():
    ids = {r.rule_id for r in forward.load_preregs()}
    assert {"mitoya_myj6_prevph_top3", "mitoya_myj6_prevdiff_top3"} <= ids
    assert not {"mitoya_mjv_prevph_top3", "mitoya_mjv_prevdiff_top3"} & ids
    data = json.loads(open(RETIRED, encoding="utf-8").read())
    assert data["universe"]["machine_name"] == "マイジャグラーV"  # 引退後も中身を書き換えない
