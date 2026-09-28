"""結果発表の機種略称を正式名に当てる（2026-09-28、197種類中102種類が当たらなかった件の回帰テスト）。"""

from backtest.model_alias import resolve

NAMES = [
    "スマスロ ハナビ",
    "新ハナビ",
    "スマスロ炎炎ノ消防隊2",
    "スマスロ炎炎ノ消防隊",
    "甲鉄城のカバネリ",
    "甲鉄城のカバネリ 海門(うなと)決戦",
    "北斗の拳 転生の章2",
    "スマスロ北斗の拳",
    "真打 吉宗",
    "マイジャグラーV",
    "ソードアート・オンライン",
    "ソードアート・オンラインII",
    "BIRDIE WING ‐Golf Girls' Story‐",
    "東京リベンジャーズ",
    "ジャグラーガールズ",
    "ガールズ&パンツァー 最終章",
    "交響詩篇エウレカセブン HI-EVOLUTION ZERO TYPE‐ART",
]


def test_smart_prefix_does_not_fall_to_other_model():
    # 旧実装は Lハナビ を別機種の『新ハナビ』に当てていた
    assert resolve("Lハナビ", NAMES)["names"] == ["スマスロ ハナビ"]
    assert resolve("新ハナビ", NAMES)["names"] == ["新ハナビ"]
    assert resolve("L炎炎2", NAMES)["names"] == ["スマスロ炎炎ノ消防隊2"]
    assert resolve("L炎炎", NAMES)["names"] == ["スマスロ炎炎ノ消防隊"]


def test_abbreviations():
    assert resolve("北斗転生", NAMES)["names"] == ["北斗の拳 転生の章2"]
    assert resolve("L北斗", NAMES)["names"] == ["スマスロ北斗の拳"]
    assert resolve("Lカバネリ", NAMES)["names"] == ["甲鉄城のカバネリ"]
    assert resolve("カバネリ海門", NAMES)["names"] == ["甲鉄城のカバネリ 海門(うなと)決戦"]
    assert resolve("エウレカART", NAMES)["names"] == ["交響詩篇エウレカセブン HI-EVOLUTION ZERO TYPE‐ART"]
    assert resolve("東リべ", NAMES)["names"] == ["東京リベンジャーズ"]  # ひらがなの「べ」


def test_s_of_ascii_name_is_not_a_prefix():
    # 「SAO」の S をスマスロの記号として剥がさない
    assert resolve("SAO", NAMES)["names"] == ["ソードアート・オンライン"]
    assert resolve("L BIRDIE WING", NAMES)["names"] == ["BIRDIE WING ‐Golf Girls' Story‐"]


def test_ranges_notes_and_multi_models():
    r = resolve("マイジャグV (1211-1213", NAMES)
    assert r["names"] == ["マイジャグラーV"] and r["ranges"] == [(1211, 1213)]
    assert resolve("L真打吉宗 ※全台系", NAMES)["names"] == ["真打 吉宗"]
    assert resolve("真打吉宗+L北斗", NAMES)["names"] == ["真打 吉宗", "スマスロ北斗の拳"]


def test_not_model_and_ambiguous_are_not_guessed():
    for text in ("【末尾3】", "21箇所", "8機種", "バラエティ"):
        r = resolve(text, NAMES)
        assert r["names"] == [] and r["unresolved"] == []
    # ガールズは基本的にジャグラーガールズ（2026-09-28 ユーザー確認）
    assert resolve("ガールズ", NAMES)["names"] == ["ジャグラーガールズ"]


def test_toaru2_is_decided_by_installed_models_and_numbers():
    both = ["とある魔術の禁書目録2", "とある科学の超電磁砲2"]
    # 片方しか設置されていなければそちら
    assert resolve("とある2", ["とある魔術の禁書目録2"])["names"] == ["とある魔術の禁書目録2"]
    # 両方あれば名前だけでは決めない
    r = resolve("とある2", both)
    assert r["names"] == [] and r["unresolved"][0]["status"] == "ambiguous"
    numbers = {"とある魔術の禁書目録2": {2101, 2102, 2103}, "とある科学の超電磁砲2": {2201, 2202}}
    # 機種欄の台番号の範囲で決める
    assert resolve("とある2 2201-2202", both, numbers_by_name=numbers)["names"] == ["とある科学の超電磁砲2"]
    # 同じ結果発表の画像の台番号で決める
    assert resolve("とある2", both, numbers_by_name=numbers, hint_numbers={2102})["names"] == ["とある魔術の禁書目録2"]
