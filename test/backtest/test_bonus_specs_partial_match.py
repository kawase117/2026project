"""マスター未登録の新機種が旧スペックに部分一致で紐づく件の検出(2026-10-25)。"""

import sqlite3
from contextlib import closing

from backtest import bonus_specs
from backtest.bonus_specs import audit_partial_matches, find_spec, normalize, partial_match_info


def _spec(family, category="ノーマル", judgeable=True):
    return {"family_name": family, "category": category, "judgeable": judgeable, "settings": {}}


def _specs(*families):
    return {normalize(name): _spec(name) for name in families}


def test_exact_match_is_not_a_partial_match():
    specs = _specs("アイムジャグラー")
    assert partial_match_info("アイムジャグラー", specs) is None


def test_partial_match_returns_info():
    specs = _specs("アイムジャグラー")
    info = partial_match_info("アイムジャグラーEX アニバーサリー", specs)
    assert info == {
        "machine_name": "アイムジャグラーEX アニバーサリー",
        "matched_key": normalize("アイムジャグラー"),
        "matched_family": "アイムジャグラー",
        "category": "ノーマル",
        "judgeable": True,
    }


def test_no_match_is_none():
    specs = _specs("アイムジャグラー")
    assert partial_match_info("まったく別の機種名", specs) is None


def test_short_keys_are_not_used():
    specs = _specs("ジャグ")
    assert len(normalize("ジャグ")) < 4
    assert partial_match_info("ジャグラーX", specs) is None
    assert find_spec("ジャグラーX", specs) is None


def test_longest_key_wins_in_either_order():
    short, long_ = "アイムジャグラー", "アイムジャグラーEX"
    for order in ((short, long_), (long_, short)):
        specs = _specs(*order)
        info = partial_match_info("アイムジャグラーEX アニバーサリー", specs)
        assert info["matched_family"] == long_


def test_find_spec_result_is_unchanged():
    specs = _specs("アイムジャグラー", "アイムジャグラーEX")
    name = "アイムジャグラーEX アニバーサリー"
    info = partial_match_info(name, specs)
    assert find_spec(name, specs) is specs[info["matched_key"]]
    assert find_spec("アイムジャグラー", specs) is specs[normalize("アイムジャグラー")]


def _make_db(path, names, with_table=True):
    with closing(sqlite3.connect(path)) as con:
        if with_table:
            con.execute("CREATE TABLE machine_detailed_results (date TEXT, machine_number INTEGER, machine_name TEXT)")
            for number, name in enumerate(names):
                con.execute("INSERT INTO machine_detailed_results VALUES ('20261020', ?, ?)", (number, name))
        con.commit()


def test_audit_collects_only_partial_matches_with_halls_and_days(tmp_path):
    specs = _specs("アイムジャグラー")
    _make_db(
        tmp_path / "ホールA.db",
        ["アイムジャグラー", "アイムジャグラーEX アニバーサリー", "アイムジャグラーEX アニバーサリー", "別機種"],
    )
    _make_db(tmp_path / "ホールB.db", ["アイムジャグラーEX アニバーサリー", "未知の機種"])
    _make_db(tmp_path / "空.db", [], with_table=False)
    _make_db(tmp_path / "analysis_results.db", ["アイムジャグラーEX 除外されるはず"])
    found = audit_partial_matches(tmp_path, specs)
    assert [entry["machine_name"] for entry in found] == ["アイムジャグラーEX アニバーサリー"]
    entry = found[0]
    assert entry["machine_days"] == 3
    assert sorted(entry["halls"]) == ["ホールA", "ホールB"]
    assert entry["matched_family"] == "アイムジャグラー"


def test_audit_sorts_by_machine_days_descending(tmp_path):
    specs = _specs("アイムジャグラー", "ゴーゴージャグラー")
    _make_db(tmp_path / "H.db", ["アイムジャグラーX"] + ["ゴーゴージャグラーY"] * 3)
    found = audit_partial_matches(tmp_path, specs)
    assert [entry["machine_name"] for entry in found] == ["ゴーゴージャグラーY", "アイムジャグラーX"]


def test_functions_are_exported():
    assert callable(bonus_specs.audit_partial_matches)
    assert callable(bonus_specs.partial_match_info)
