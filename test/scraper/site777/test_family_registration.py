from __future__ import annotations

import importlib.util
import math
from pathlib import Path

from scraper.site777.setting_estimator import (
    build_family_matcher,
    estimate_setting,
    load_family_specs,
    match_family,
)

PROJECT_ROOT = Path(__file__).resolve().parents[3]


def _load_live_brief():
    path = PROJECT_ROOT / "scraper" / "site777" / "site777_live_brief.py"
    spec = importlib.util.spec_from_file_location("_live_brief_for_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_fujiko_and_claire_are_registered_with_site_names() -> None:
    specs = load_family_specs()
    matcher = build_family_matcher(specs)

    assert match_family("Ｌ不二子ＢＴ", matcher) == "FUJIKO_BT"
    assert match_family("LBクレアの秘宝伝ボーナストリガーver.", matcher) == "CLAIRE_BT"
    # 不二子は設定3が未掲載の5段階機、クレアは設定1〜6が揃う
    assert sorted(specs["FUJIKO_BT"]["settings"]) == [1, 2, 4, 5, 6]
    assert sorted(specs["CLAIRE_BT"]["settings"]) == [1, 2, 3, 4, 5, 6]


def test_fujiko_ignores_bb_but_claire_uses_it() -> None:
    specs = load_family_specs()
    fujiko = specs["FUJIKO_BT"]["settings"]
    claire = specs["CLAIRE_BT"]["settings"]

    # 不二子はサイトのBB欄がスペックのBIGと一致しないので、BBを変えても結果は同じ
    assert estimate_setting(2288, 33, 7, fujiko) == estimate_setting(2288, 0, 7, fujiko)
    # クレアはBBも尤度に入る
    assert estimate_setting(2800, 8, 18, claire) != estimate_setting(2800, 0, 18, claire)


def test_claire_high_rb_leans_high_setting() -> None:
    specs = load_family_specs()
    result = estimate_setting(2800, 8, 18, specs["CLAIRE_BT"]["settings"])

    assert result is not None
    assert result["ml_setting"] == 6
    assert result["setting_lean"] == "高設定寄り"
    # 手計算（RB+BB、一様事前）で設定5以上が約83%
    assert math.isclose(result["p_high_setting_uniform_prior"], 0.83, abs_tol=0.01)


def test_harem_ace_is_registered_and_uses_bb() -> None:
    specs = load_family_specs()
    matcher = build_family_matcher(specs)

    assert match_family("翔べ！ハーレムエース", matcher) == "HAREM_ACE"
    settings = specs["HAREM_ACE"]["settings"]
    # 設定3・4なしの4段階機。不二子と違い、BBは尤度に入る
    assert sorted(settings) == [1, 2, 5, 6]
    assert estimate_setting(5836, 27, 18, settings) != estimate_setting(5836, 0, 18, settings)

    result = estimate_setting(5836, 27, 18, settings)
    assert result is not None
    assert result["setting_lean"] == "高設定寄り"
    # 手計算（BB+RB、一様事前）で3210は設定5以上が約98%
    assert math.isclose(result["p_high_setting_uniform_prior"], 0.98, abs_tol=0.01)


def test_norm_unifies_full_width_site_names() -> None:
    brief = _load_live_brief()

    assert brief.norm("Ｌ不二子ＢＴ") == brief.norm("不二子BT")
    assert brief.norm("ゴーゴージャグラー３") == brief.norm("ゴーゴージャグラー3")


def test_by_norm_finds_machine_when_site_drops_the_subtitle() -> None:
    brief = _load_live_brief()
    by_norm = brief.build_by_norm(
        {
            "クレアの秘宝伝 ～はじまりの扉と太陽の石～ ボーナストリガーver.": "BT",
            "不二子BT": "BT",
        }
    )

    entry = by_norm.get(brief.norm("LBクレアの秘宝伝ボーナストリガーver."))
    assert entry is not None and entry[1] == "BT"


def test_by_norm_does_not_alias_ambiguous_subtitles() -> None:
    brief = _load_live_brief()
    # サブタイトルを落とすと同じ名前になる2機種は、別名キーを足さない
    by_norm = brief.build_by_norm({"テスト機 ～甲～ 本編": "AT", "テスト機 ～乙～ 本編": "BT"})

    assert brief.norm("テスト機本編") not in dict.keys(by_norm)


def test_by_norm_falls_back_to_longest_containment() -> None:
    brief = _load_live_brief()
    by_norm = brief.build_by_norm({"ファンキージャグラー2": "ノーマル", "ジャグラーガールズ": "ノーマル"})

    assert by_norm.get(brief.norm("ファンキージャグラー２ＫＴ"))[0] == "ファンキージャグラー2"
    assert by_norm.get(brief.norm("ジャグラーガールズSS"))[0] == "ジャグラーガールズ"
    assert by_norm.get(brief.norm("全く無関係な機種")) is None
