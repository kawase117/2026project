"""「もっと！クレアの秘宝伝」「CREA Newクレアの秘宝伝」は「クレアの秘宝伝BT」のスペックに紐づけない(2026-10-25)。"""

import pytest

from backtest import bonus_specs
from backtest.bonus_specs import NOT_SAME_MACHINE, find_spec, normalize, partial_match_info

OTHER_MACHINES = [
    "もっと！クレアの秘宝伝 女神の歌声と太陽の子供達",
    "CREA Newクレアの秘宝伝",
]
KUREA_BT_NAMES = [
    "クレアの秘宝伝BT",
    "LBクレアの秘宝伝ボーナストリガー",
    "クレアの秘宝伝 ～はじまりの扉と太陽の石～ ボーナストリガーver.",
]


def _spec(family):
    return {"family_name": family, "category": "BT", "judgeable": True, "settings": {}}


@pytest.fixture(scope="module")
def specs():
    return bonus_specs.load_specs()


@pytest.mark.parametrize("name", OTHER_MACHINES)
def test_other_machines_do_not_get_kurea_bt_spec(specs, name):
    assert find_spec(name, specs) is None
    assert partial_match_info(name, specs) is None


@pytest.mark.parametrize("name", KUREA_BT_NAMES)
def test_kurea_bt_names_still_resolve(specs, name):
    spec = find_spec(name, specs)
    assert spec is not None
    assert spec["category"] == "BT"
    assert spec["judgeable"]


def test_exclusion_set_uses_normalized_names():
    assert all(name == normalize(name) for name in NOT_SAME_MACHINE)
    assert len(NOT_SAME_MACHINE) == len(OTHER_MACHINES)


def test_exact_registration_wins_over_exclusion():
    name = "CREA Newクレアの秘宝伝"
    own = _spec(name)
    specs = {normalize("クレアの秘宝伝"): _spec("クレアの秘宝伝BT"), normalize(name): own}
    assert find_spec(name, specs) is own
    assert partial_match_info(name, specs) is None


def test_other_names_are_unaffected():
    specs = {normalize("クレアの秘宝伝"): _spec("クレアの秘宝伝BT")}
    assert find_spec("クレアの秘宝伝 続編", specs)["family_name"] == "クレアの秘宝伝BT"
    assert find_spec("CREA Newクレアの秘宝伝", specs) is None
