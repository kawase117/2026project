# -*- coding: utf-8 -*-
"""match_models が本文にない機種を拾わないことを固定する(2026-10-27 に見つけた誤抽出)。

方針は「誤って拾うより拾い損ねる方がまし」。ただし正式名・略称で書いた機種は当たること。
"""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

from backtest import prediction_ledger as pl  # noqa: E402

ZASSIKI = ["青春ブタ野郎はバニーガール先輩の夢を見ない", "ネオアイムジャグラーEX", "吉宗"]
KAMATA1 = [
    "戦国乙女5 業火を穿つ宿焔の双刃",
    "甲鉄城のカバネリ",
    "甲鉄城のカバネリ 海門(うなと)決戦",
    "スマスロ北斗の拳",
    "北斗の拳 転生の章2",
    "吉宗",
    "真打 吉宗",
    "喰霊‐零‐Re",
    "彼女、お借りします",
    "邪神ちゃんドロップキック",
    "青春ブタ野郎はバニーガール先輩の夢を見ない",
    "戦国コレクション6",
    "新鬼武者3",
    "からくりサーカス2",
    "キングハナハナ-30",
    "ニューキングハナハナV‐30",
]
# 'ZERO' だけを切り出すと複数の機種名に部分一致して ambiguous になる並び(実際の楽園の機種にもある)
RAKUEN = [
    "交響詩篇エウレカセブン HI-EVOLUTION ZERO TYPE‐ART",
    "キングハナハナ-30",
    "ゼロ ZERO THE SLOT",
    "BLACK ZERO 2",
]


def models(line, names):
    return pl.match_models(line, names)[0]


def test_generic_phrase_does_not_hit_model_suffix():
    # 「ない」が『…夢を見ない』の語尾に当たっていた
    assert models("前日1日の結果しか材料がない", ZASSIKI) == []


def test_official_name_does_not_also_pick_shorter_model():
    # 正式名を書いたのに、それを含む短い別機種(無印カバネリ)まで拾っていた
    assert models("甲鉄城のカバネリ 海門(うなと)決戦", KAMATA1) == ["甲鉄城のカバネリ 海門(うなと)決戦"]


def test_plain_name_still_picks_plain_model():
    assert models("甲鉄城のカバネリ", KAMATA1) == ["甲鉄城のカバネリ"]
    assert models("カバネリ", KAMATA1) == ["甲鉄城のカバネリ"]


def test_list_of_abbreviations_picks_only_listed():
    line = (
        "戦国乙女5、カバネリ、スマスロ北斗、北斗転生、真打吉宗、喰霊、かのかり、邪神ちゃん、青ブタ、戦コレ6、新鬼武者3"
    )
    got = models(line, KAMATA1)
    assert "からくりサーカス2" not in got
    assert got == [
        "戦国乙女5 業火を穿つ宿焔の双刃",
        "甲鉄城のカバネリ",
        "スマスロ北斗の拳",
        "北斗の拳 転生の章2",
        "真打 吉宗",
        "喰霊‐零‐Re",
        "彼女、お借りします",
        "邪神ちゃんドロップキック",
        "青春ブタ野郎はバニーガール先輩の夢を見ない",
        "戦国コレクション6",
        "新鬼武者3",
    ]


def test_name_with_trailing_dash_number_in_long_sentence():
    # 「-30」を差枚と取り違えて落とし、前の語もくっついて当たらなかった
    long_line = "加えて前日に RB で強かったキングハナハナ-30 を推すが、1日の結果からの持ち越しで確度は低い。"
    assert models(long_line, KAMATA1) == ["キングハナハナ-30"]
    assert models("キングハナハナ-30 を推す", KAMATA1) == ["キングハナハナ-30"]


def test_full_official_name_leaves_no_unresolved_fragment():
    got, unres = pl.match_models("交響詩篇エウレカセブン HI-EVOLUTION ZERO TYPE‐ART", RAKUEN)
    assert got == ["交響詩篇エウレカセブン HI-EVOLUTION ZERO TYPE‐ART"]
    assert unres == []


def test_particle_kara_does_not_hit_model_prefix():
    # 助詞「から」が『からくりサーカス2』の語頭に当たっていた(10/24 蒲田1の判断行)
    line = "「カマタに集合」の過去実績から、ホール全体は通常日より強い前提。ヴァルヴレイヴ2を第一候補にする。"
    assert models(line, KAMATA1 + ["革命機ヴァルヴレイヴ2"]) == ["革命機ヴァルヴレイヴ2"]


def test_bare_number_does_not_hit_model_with_number_in_name():
    # 「直近 30 日平均」の 30 が『沖ドキ!GOLD‐30』に当たっていた(10/23 平和島の避ける行)
    line = "避ける: ミリオンゴッド(昨日の先バレで −785、直近 30 日平均スコア −160.8)。"
    got = models(line, ["ミリオンゴッド‐神々の軌跡‐", "沖ドキ!GOLD‐30"])
    assert got == ["ミリオンゴッド‐神々の軌跡‐"]


def test_version_suffix_names_are_not_confused():
    # 「Ⅵ」を NFKC で VI にすると、短い『マイジャグラーV』が先に当たって I が残っていた
    roster = ["マイジャグラーⅥ", "マイジャグラーV"]
    assert models("マイジャグラーⅥ 674番・643番を軸に", roster) == ["マイジャグラーⅥ"]
    assert models("マイジャグラーVを推す", roster) == ["マイジャグラーV"]
    assert models("からくりサーカス2を推す", ["からくりサーカス", "からくりサーカス2"]) == ["からくりサーカス2"]


def test_full_name_followed_by_unit_count_in_parentheses():
    # 「(25台)」の 25 を版数とみなして正式名を取り損ねていた
    got, unres = pl.match_models("交響詩篇エウレカセブン HI-EVOLUTION ZERO TYPE‐ART（25台）、次に", RAKUEN)
    assert got == ["交響詩篇エウレカセブン HI-EVOLUTION ZERO TYPE‐ART"]
    assert unres == []


def test_two_char_name_that_is_only_a_suffix_of_the_official_name():
    # 『真打 吉宗』しか設置がなくても、文書の「吉宗」はそれを指す
    assert models(
        "3台並びはカバネリ・乙女5・吉宗から探す", ["甲鉄城のカバネリ", "戦国乙女5 業火を穿つ宿焔の双刃", "真打 吉宗"]
    ) == [
        "甲鉄城のカバネリ",
        "戦国乙女5 業火を穿つ宿焔の双刃",
        "真打 吉宗",
    ]


def test_two_char_real_names_still_match():
    assert models("獣王を推す", ["獣王", "ネオアイムジャグラーEX"]) == ["獣王"]
    assert models("吉宗を避ける", ["吉宗", "真打 吉宗"]) == ["吉宗"]
