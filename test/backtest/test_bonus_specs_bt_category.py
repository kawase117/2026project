"""アレックス ブライト・クレアの秘宝伝BT・翔べ!ハーレムエースはBT。ノーマルとの重複登録も無い(2026-10-25)。"""

import pytest

from backtest import bonus_specs

BT_MACHINES = [
    "アレックス ブライト",
    "クレアの秘宝伝BT",
    "LBクレアの秘宝伝ボーナストリガー",
    "翔べ！ハーレムエース",
    "翔べ!ハーレムエース(スマスロ)",
]


@pytest.fixture(scope="module")
def specs():
    return bonus_specs.load_specs()


@pytest.mark.parametrize("name", BT_MACHINES)
def test_machine_is_bt_and_judgeable(specs, name):
    spec = bonus_specs.find_spec(name, specs)
    assert spec is not None
    assert spec["category"] == "BT"
    assert spec["judgeable"]


@pytest.mark.parametrize("keyword", ["ハーレムエース", "クレアの秘宝伝", "アレックス"])
def test_no_duplicate_entries(specs, keyword):
    entries = [s for s in specs.values() if keyword in s["family_name"]]
    assert len(entries) == 1
