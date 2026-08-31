"""selection_unit / min_machines_per_model 追加による回帰防止テスト。

freeze_hash は asdict(self) 全体のハッシュなので、フィールドを1つ足すだけで
既存ルールの freeze_hash が変わりうる。変わると backtest/forward/*.json に
蓄積したフォワードテスト証拠が全部「plan 作成後に書き換えられた」扱いで
検証不能になる（_reg_from_plan 参照）。ここでは:

1. 既存 prereg/*.json の freeze_hash が、新フィールド追加前の値と1ビットも
   変わっていないこと（v1 互換）を固定する。
2. 既存の凍結済み plan（backtest/forward/*.json）が _reg_from_plan と
   _verify_ledger を問題なく通ること（= 過去のフォワードテスト証拠が
   引き続き有効であること）を確認する。score() は再実行しない
   （採点済み plan の再採点は禁止）。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from backtest.forward import FORWARD_DIR, PREREG_DIR, _reg_from_plan, _verify_ledger
from backtest.prereg import PreRegistration

# selection_unit / min_machines_per_model を追加する直前（2026-08-04 時点）に
# 実測した freeze_hash。ここに書かれたルールは以後 1本たりとも動いてはいけない。
EXPECTED_V1_FREEZE_HASH = {
    "k1_jug_dd1kei_rbz_top3": "5c176bc76465f438",
    "k1_jug_plain_rbz_top3": "393b78a3e43883fd",
    "k7_at_histdiff_top3": "71526fa786ee4e6e",
    "k7_jug_hit104_top3": "da834a49ac60a45d",
    "k7_jug_kakuban1_avoid": "37bca07db1b6d8b7",
    "k7_jug_rb_top3": "9e914424a794c5e3",
    "mitoya_at_eventdd_histdiff_top3": "e99d60338347d27e",
    "mitoya_jug_eventdd_rb_top3": "fe7f29b77b936fb4",
    "mitoya_jug_eventdd_rbz_top3": "ee07f55cce1c5154",
    "rakuen_jug_renovation_rb_top3": "2c84cf17dfa96448",
    "zassiki_jug_fixed_top3": "a0b246e660ee0d4e",
}


@pytest.mark.parametrize("rule_id,expected_hash", sorted(EXPECTED_V1_FREEZE_HASH.items()))
def test_existing_rule_freeze_hash_unchanged(rule_id: str, expected_hash: str) -> None:
    path = PREREG_DIR / f"{rule_id}.json"
    assert path.exists(), f"prereg 定義が見つからない: {path}"
    reg = PreRegistration.load(path)
    assert reg.freeze_hash() == expected_hash, (
        f"{rule_id} の freeze_hash が変わった。selection_unit / min_machines_per_model が"
        "デフォルト値でも payload に残っていないか確認すること。"
    )


def _all_forward_plans() -> list[Path]:
    if not FORWARD_DIR.exists():
        return []
    return sorted(FORWARD_DIR.glob("*.json"))


@pytest.mark.parametrize("plan_path", _all_forward_plans(), ids=lambda p: p.name)
def test_existing_forward_plans_still_verify(plan_path: Path) -> None:
    """凍結済み plan が freeze_hash 検証・台帳検証を引き続き通ることを確認する。

    score() は呼ばない（採点済み plan の再採点は禁止のため）。
    """
    plan_obj = json.loads(plan_path.read_text(encoding="utf-8"))
    reg = _reg_from_plan(plan_obj)
    assert reg.freeze_hash() == plan_obj["freeze_hash"]
    _verify_ledger(plan_obj)
