from __future__ import annotations

from scraper.site777.setting_estimator import (
    MIN_GAMES_FOR_SETTING,
    annotate_setting_estimates,
    build_family_matcher,
    estimate_setting,
    indistinguishable_settings,
    load_family_specs,
    match_family,
)

# 実機と同程度の設定差を持たせた合成機。BBを全設定同じにすると情報量が半減し、
# 設定6ちょうどの観測でも高低が分離できなくなるため、RBとBBの両方に差を付ける。
SYNTHETIC = {
    "TEST": {
        "family_name": "合成ジャグラー",
        "machine_keyword": "合成ジャグラー",
        "settings": {
            1: {"rb_probability": 1 / 409.6, "bb_probability": 1 / 273.1, "payout_rate": 97.0},
            2: {"rb_probability": 1 / 385.5, "bb_probability": 1 / 270.8, "payout_rate": 98.0},
            3: {"rb_probability": 1 / 336.1, "bb_probability": 1 / 266.4, "payout_rate": 99.9},
            4: {"rb_probability": 1 / 290.0, "bb_probability": 1 / 254.0, "payout_rate": 102.8},
            5: {"rb_probability": 1 / 268.6, "bb_probability": 1 / 240.1, "payout_rate": 105.3},
            6: {"rb_probability": 1 / 229.1, "bb_probability": 1 / 229.1, "payout_rate": 109.4},
        },
    }
}


def test_below_threshold_games_are_not_estimated() -> None:
    settings = SYNTHETIC["TEST"]["settings"]

    assert estimate_setting(MIN_GAMES_FOR_SETTING - 1, 7, 5, settings) is None
    assert estimate_setting(MIN_GAMES_FOR_SETTING, 7, 5, settings) is not None


def test_observation_on_setting6_spec_picks_setting6() -> None:
    settings = SYNTHETIC["TEST"]["settings"]
    games = 8000
    bb = round(games * settings[6]["bb_probability"])
    rb = round(games * settings[6]["rb_probability"])

    result = estimate_setting(games, bb, rb, settings)

    assert result["ml_setting"] == 6
    assert result["setting_band_max"] == 6
    assert result["setting_lean"] == "高設定寄り"
    assert result["high_low_ratio"] > 1.0


def test_observation_on_setting1_spec_picks_low_setting() -> None:
    settings = SYNTHETIC["TEST"]["settings"]
    games = 8000
    bb = round(games * settings[1]["bb_probability"])
    rb = round(games * settings[1]["rb_probability"])

    result = estimate_setting(games, bb, rb, settings)

    assert result["ml_setting"] <= 2
    assert result["setting_lean"] == "低設定寄り"
    assert result["high_low_ratio"] < 1.0


def test_more_games_narrows_the_band_and_raises_confidence() -> None:
    settings = SYNTHETIC["TEST"]["settings"]
    spec6 = settings[6]
    short = estimate_setting(
        2000, round(2000 * spec6["bb_probability"]), round(2000 * spec6["rb_probability"]), settings
    )
    long = estimate_setting(
        8000, round(8000 * spec6["bb_probability"]), round(8000 * spec6["rb_probability"]), settings
    )

    short_width = short["setting_band_max"] - short["setting_band_min"]
    long_width = long["setting_band_max"] - long["setting_band_min"]
    assert long_width < short_width
    assert long["high_low_ratio"] > short["high_low_ratio"]
    # 短いほうは全設定が残る＝絞れない。
    assert short["setting_band_narrowed"] is False
    assert short["setting_band_label"] == "絞れず"
    assert long["setting_band_narrowed"] is True


def test_confidence_reflects_high_low_separation_not_adjacent_settings() -> None:
    settings = SYNTHETIC["TEST"]["settings"]
    games = 8000
    # 設定3と4のちょうど中間に落ちた観測は高低どちらとも言えない。
    middle_rb = (settings[3]["rb_probability"] + settings[4]["rb_probability"]) / 2
    ambiguous = estimate_setting(
        games, round(games * settings[3]["bb_probability"]), round(games * middle_rb), settings
    )
    clear = estimate_setting(
        games,
        round(games * settings[6]["bb_probability"]),
        round(games * settings[6]["rb_probability"]),
        settings,
    )

    assert ambiguous["setting_confidence"] == "低"
    # 設定6ちょうどの観測は、隣の設定5とは割れなくても高低の分離はできる。
    assert clear["setting_confidence"] in {"中", "高"}
    assert clear["high_low_ratio"] > ambiguous["high_low_ratio"]


def test_low_setting_separates_earlier_than_high_setting() -> None:
    """設定4が5-6に近いため、高設定の判定は低設定の判定より多くの回転を要する。"""
    settings = SYNTHETIC["TEST"]["settings"]
    games = 6000

    low = estimate_setting(
        games,
        round(games * settings[1]["bb_probability"]),
        round(games * settings[1]["rb_probability"]),
        settings,
    )
    high = estimate_setting(
        games,
        round(games * settings[6]["bb_probability"]),
        round(games * settings[6]["rb_probability"]),
        settings,
    )

    assert low["setting_lean"] == "低設定寄り"
    assert high["setting_lean"] == "高設定寄り"
    # 同じ回転数でも、低設定側のほうが先に信用度が上がる。
    assert low["setting_confidence"] == "中"
    assert high["setting_confidence"] == "低"


def test_uniform_prior_posterior_is_kept_but_labelled_as_such() -> None:
    settings = SYNTHETIC["TEST"]["settings"]
    games = 8000
    spec6 = settings[6]
    result = estimate_setting(
        games, round(games * spec6["bb_probability"]), round(games * spec6["rb_probability"]), settings
    )

    # 参考値として残すが、主指標ではないことを名前で示す。
    assert "p_high_setting" not in result
    assert 0.0 <= result["p_high_setting_uniform_prior"] <= 1.0
    assert 1.0 <= result["expected_setting_uniform_prior"] <= 6.0


def test_settings_sharing_rb_probability_are_reported_as_indistinguishable() -> None:
    settings = {
        1: {"rb_probability": 1 / 400, "bb_probability": 1 / 270, "payout_rate": 97.0},
        5: {"rb_probability": 1 / 255, "bb_probability": 1 / 259, "payout_rate": 103.3},
        6: {"rb_probability": 1 / 255, "bb_probability": 1 / 255, "payout_rate": 105.5},
    }

    assert indistinguishable_settings(settings) == [[5, 6]]


def test_family_matching_handles_full_width_and_suffixes() -> None:
    specs = load_family_specs()
    if not specs:  # スペック表が無い環境では照合を検査できない
        return
    matcher = build_family_matcher(specs)

    assert match_family("ネオアイムジャグラーEX", matcher) == "IMEX"
    assert match_family("マイジャグラーV", matcher) == "MYV"
    # 全角数字・全角ローマ数字・型式サフィックスを含むサイトセブン表記
    assert match_family("ゴーゴージャグラー３", matcher) == "GOGO3"
    assert match_family("ハッピージャグラーＶＩＩＩ", matcher) == "HAPPY8"
    assert match_family("ファンキージャグラー２ＫＴ", matcher) == "FUNKY2"
    assert match_family("ジャグラーガールズSS", matcher) == "GALS"
    assert match_family("スマスロ 北斗の拳 転生の章2", matcher) is None


def test_annotate_marks_out_of_scope_machines_with_none() -> None:
    machines = [
        {"model_name": "合成ジャグラー", "games": 6000, "bb_count": 22, "rb_count": 24},
        {"model_name": "合成ジャグラー", "games": 500, "bb_count": 2, "rb_count": 2},
        {"model_name": "スマスロ 北斗の拳 転生の章2", "games": 6000, "bb_count": 30, "rb_count": 0},
    ]

    summary = annotate_setting_estimates(machines, SYNTHETIC)

    assert summary["spec_covered_machines"] == 2
    assert summary["estimated_machines"] == 1
    assert summary["below_threshold_machines"] == 1
    assert machines[0]["ml_setting"] is not None
    assert machines[1]["ml_setting"] is None
    assert machines[2]["setting_family_key"] is None
    assert machines[2]["ml_setting"] is None
