from __future__ import annotations

from scraper.site777.reference import normalize_machine_key, strip_title_prefixes
from scraper.site777.site777_analyze import (
    MIN_RANKED_DIFF_MACHINES,
    classify_candidates,
    graph_age_minutes,
    graph_time_skew_minutes,
    model_rankings,
    normal_machine_models,
    probability,
    probability_ranking_models,
    rank_rows,
    rb_absent_models,
)


def _model(
    mdc: str,
    name: str,
    category: str | None,
    *,
    diff_valid: int,
    win_rate: float | None,
    total_rb: int = 20,
    total_games: int = 20000,
) -> dict:
    return {
        "mdc": mdc,
        "model_name": name,
        "machine_category": category,
        "machine_count": max(diff_valid, 1),
        "diff_valid_count": diff_valid,
        "total_rb": total_rb,
        "total_games": total_games,
        "win_rate": win_rate,
        "average_diff": 100.0,
        "average_games": 3000.0,
        "average_highest_payout": 1500.0,
        "bb_probability": 250.0,
        "rb_probability": 400.0,
        "combined_probability": 154.0,
    }


def test_win_rate_ranking_drops_models_below_the_minimum_sample() -> None:
    models = [
        _model("1", "1台だけ勝った機種", "jug", diff_valid=1, win_rate=1.0),
        _model("2", "2台だけ勝った機種", "jug", diff_valid=2, win_rate=1.0),
        _model("3", "母数のある機種", "jug", diff_valid=MIN_RANKED_DIFF_MACHINES, win_rate=0.6),
    ]

    ranking = model_rankings(models)["win_rate"]

    assert [row["model_name"] for row in ranking] == ["母数のある機種"]


def test_probability_rankings_exclude_non_normal_machines() -> None:
    normal = _model("1", "マイジャグラーV", "jug", diff_valid=5, win_rate=0.5)
    at_machine = _model("2", "L化物語", "other", diff_valid=5, win_rate=0.5)
    at_machine["rb_probability"] = 164.5
    unmatched = _model("3", "マスター未対応機", None, diff_valid=5, win_rate=0.5)
    models = [normal, at_machine, unmatched]

    rankings = model_rankings(models, normal_machine_models(models))

    assert [row["model_name"] for row in rankings["rb_probability"]] == ["マイジャグラーV"]
    # 差枚・平均Gは全機種を対象に残す。
    assert len(rankings["average_diff"]) == 3


def test_rb_absent_models_are_dropped_from_probability_rankings() -> None:
    # 区分はbtだがRBが全台0回。擬似ボーナスのAT機にbt_flagが誤って立っている状態。
    fake_normal = _model("9", "エウレカTYPE-ART", "bt", diff_valid=25, win_rate=0.4, total_rb=0)
    real_normal = _model("1", "マイジャグラーV", "jug", diff_valid=20, win_rate=0.5)
    models = [fake_normal, real_normal]

    assert [m["model_name"] for m in rb_absent_models(models)] == ["エウレカTYPE-ART"]
    assert [m["model_name"] for m in probability_ranking_models(models)] == ["マイジャグラーV"]
    # normal_machine_models 自体は区分だけを見る。
    assert len(normal_machine_models(models)) == 2

    ranking = model_rankings(models, probability_ranking_models(models))["bb_probability"]
    assert [row["model_name"] for row in ranking] == ["マイジャグラーV"]


def test_rb_absent_needs_enough_games_before_blaming_the_master() -> None:
    """開店直後や1台設置の機種が「まだRBを引いていない」だけで区分誤りと名指しされないこと。"""
    structural = _model("9", "エウレカTYPE-ART", "bt", diff_valid=25, win_rate=0.4, total_rb=0, total_games=43499)
    just_early = _model("8", "ハイパーラッシュ", "bt", diff_valid=1, win_rate=0.0, total_rb=0, total_games=350)
    models = [structural, just_early, _model("1", "マイジャグラーV", "jug", diff_valid=20, win_rate=0.5)]

    assert [m["model_name"] for m in rb_absent_models(models)] == ["エウレカTYPE-ART"]
    # 母数不足の機種は除外リストに載せないが、確率ランキングには残す。
    names = [m["model_name"] for m in probability_ranking_models(models)]
    assert "ハイパーラッシュ" in names
    assert "エウレカTYPE-ART" not in names


def test_prefix_fallback_matches_site_seven_title_prefixes() -> None:
    pairs = [
        ("LBサンダーV", "スマスロ サンダーV"),
        ("LB SHAKE BONUS TRIGGER", "SHAKE BONUS TRIGGER"),
        ("パチスロ戦国恋姫", "戦国†恋姫"),
        ("パチスロ　ピンクパンサーＳＰ", "ピンクパンサーSP"),
        ("ＳＬＯＴマッピー", "マッピー"),
        ("A-SLOT+ ディスクアップ ULTRAREMIX", "ディスクアップ ULTRAREMIX"),
        ("回胴式遊技機グランベルム", "グランベルム"),
    ]
    for site_name, master_name in pairs:
        site_key = strip_title_prefixes(normalize_machine_key(site_name))
        master_key = strip_title_prefixes(normalize_machine_key(master_name))
        assert site_key == master_key, site_name


def test_strict_key_is_unchanged_so_distinct_titles_do_not_collide() -> None:
    # 厳密キーは接頭辞を残す。ここが潰れると2機種が衝突して両方失われる。
    smart = normalize_machine_key("スマスロ ドルアーガの塔")
    slot = normalize_machine_key("SLOTドルアーガの塔")

    assert smart != slot
    assert strip_title_prefixes(smart) == strip_title_prefixes(slot)


def test_rank_rows_without_min_count_keeps_current_behaviour() -> None:
    rows = [{"value": 1, "n": 0}, {"value": 3, "n": 9}, {"value": None, "n": 9}]

    ranked = rank_rows(rows, "value", reverse=True)

    assert [row["value"] for row in ranked] == [3, 1]
    assert [row["rank"] for row in ranked] == [1, 2]


def test_graph_skew_keeps_sign_and_age_uses_magnitude() -> None:
    # グラフが一覧より30分新しいケース（並行収集では常に起こる）。
    assert graph_time_skew_minutes("2026/08/15 14:55", "2026/08/15 15:25") == -30
    assert graph_age_minutes("2026/08/15 14:55", "2026/08/15 15:25") == 30
    # グラフが古いケースは従来どおり正の値。
    assert graph_time_skew_minutes("2026/08/15 15:25", "2026/08/15 14:55") == 30
    assert graph_age_minutes("2026/08/15 15:25", "2026/08/15 14:55") == 30
    assert graph_age_minutes(None, "2026/08/15 14:55") is None


def _machine(number: str, category: str | None, *, games: int, bb: int, rb: int, diff: int | None) -> dict:
    return {
        "mdc": "120010",
        "model_name": "マイジャグラーV",
        "machine_number": number,
        "machine_category": category,
        "games": games,
        "bb_count": bb,
        "rb_count": rb,
        "bb_probability": probability(games, bb),
        "rb_probability": probability(games, rb),
        "latest_diff": diff,
    }


def test_candidates_split_setting_expectation_from_payout() -> None:
    good_rb = _machine("101", "jug", games=6000, bb=24, rb=24, diff=1500)
    bb_heavy = _machine("102", "jug", games=6000, bb=30, rb=15, diff=3000)
    short = _machine("103", "jug", games=500, bb=3, rb=3, diff=200)
    machines = [good_rb, bb_heavy, short]
    total_games = sum(machine["games"] for machine in machines)
    models = [
        {
            "mdc": "120010",
            "bb_probability": probability(total_games, sum(m["bb_count"] for m in machines)),
            "rb_probability": probability(total_games, sum(m["rb_count"] for m in machines)),
        }
    ]

    classify_candidates(machines, models, graph_min_games=2000)

    assert good_rb["setting_candidate"] is True
    assert good_rb["candidate_label"] == "高設定期待(RB)"
    assert bb_heavy["setting_candidate"] is False
    assert bb_heavy["bb_heavy"] is True
    assert bb_heavy["candidate_label"] == "出玉候補(BB偏重)"
    # 累計Gがしきい値未満の台は設定評価の対象外。差枚がプラスでも出玉候補どまり。
    assert short["setting_eval_eligible"] is False
    assert short["setting_candidate"] is False
    assert short["payout_candidate"] is True


def test_at_machines_never_become_setting_candidates() -> None:
    at_machine = _machine("201", "other", games=8000, bb=40, rb=40, diff=9000)
    at_machine["model_name"] = "L化物語"
    models = [{"mdc": "120010", "bb_probability": 400.0, "rb_probability": 400.0}]

    classify_candidates([at_machine], models, graph_min_games=2000)

    assert at_machine["evaluation_track"] == "payout"
    assert at_machine["setting_candidate"] is False
    assert at_machine["candidate_label"] == "出玉候補(設定判定外)"
