from database.register_1geki_machine import build
from scraper.realtime.adapters.common import _width_variant, model_name


def test_width_variant_prefers_full_width_only_when_names_differ_by_width():
    assert _width_variant(["いざ!番長", "いざ！番長"]) == "いざ！番長"
    assert _width_variant(["いざ!番長", "別の機種"]) is None


def test_aliases_confirmed_by_user():
    assert model_name("L/ﾖｼﾑﾈS/SC2") == "吉宗(スマスロ)"
    assert model_name("LｷﾝｸﾞﾊﾟﾙｻｰSLCC") == "スマスロキングパルサー"
    assert model_name("Lいざ!番長") == "いざ！番長"
    assert model_name("LB翔べ!ﾊｰﾚﾑｴｰｽ") == "翔べ！ハーレムエース"


def test_new_machines_resolve_through_master_csv():
    assert model_name("L戦国ｺﾚｸｼｮﾝ5GJ") == "戦国コレクション5"
    assert model_name("LBｽﾛｯﾄｶﾞﾙﾌｨｰA4") == "ガルフィー"


def test_register_refuses_pages_missing_identity_fields():
    result, reason = build(
        "CCエンジェル", "https://1geki.jp/slot/s_ccangel/", None, html="<html><body>none</body></html>"
    )
    assert result is None and reason.startswith("missing:")


def test_user_provided_machines_load_with_correct_setting_sets():
    from backtest.bonus_specs import load_specs, normalize

    specs = load_specs()
    for name in ("CCエンジェル", "ガルフィー"):  # 4設定機: 3・4を補間しない
        assert set(specs[normalize(name)]["settings"]) == {1, 2, 5, 6}
    assert set(specs[normalize("ツインエンジェルPARTY")]["settings"]) == {1, 2, 3, 4, 5, 6}


def test_new_machine_names_resolve_from_dmm_labels():
    assert model_name("S CCエンジェル CA") == "CCエンジェル"
    assert model_name("Sツインエンジェル PARTY ZF") == "ツインエンジェルPARTY"
    assert model_name("SミルキィホームズGNB") == "ミルキィホームズR 大収穫祭"
    assert model_name("LBﾏｼﾞｶﾙﾊﾛｳｨﾝGS") == "マジカルハロウィン ボーナストリガー"


def test_machine_without_rb_spec_is_not_estimated():
    from scraper.realtime.estimate import estimate
    from scraper.realtime.schema import SnapshotRow

    row = SnapshotRow(
        hall="ヒロキMAX蒲田店",
        observed_at="2026-10-07T15:00:00+09:00",
        source_updated_at=None,
        unit=1,
        model="ツインエンジェルPARTY",
        model_raw="x",
        games=2000,
        bb=6,
        rb=3,
        diff=None,
        source="dmm",
    )
    result = estimate(row)
    assert result["p_high"] is None and result["kind"] == "none"


def test_versus_spec_page_variant_uses_master_csv_and_has_four_settings():
    from scraper.realtime.estimate import _versus_spec_page, estimate
    from scraper.realtime.schema import SnapshotRow

    assert set(_versus_spec_page()) == {1, 2, 5, 6}
    row = SnapshotRow(
        hall="ヒロキ東口店",
        observed_at="2026-10-07T15:00:00+09:00",
        source_updated_at=None,
        unit=2288,
        model="バーサスリヴァイズ",
        model_raw="x",
        games=2000,
        bb=8,
        rb=6,
        diff=None,
        source="dmm",
    )
    default, page = estimate(row), estimate(row, spec_variant="spec_page")
    assert default["p_high"] is not None and page["p_high"] is not None
    assert default["setting_probabilities"] != page["setting_probabilities"]


def test_user_confirmed_aliases_2026_10_07():
    expected = {
        "L ﾊﾟﾁｽﾛ北斗の拳AD XR": "スマスロ北斗の拳",
        "Lﾚﾝﾀﾙ彼女bK": "レンタル彼女",
        "LﾊﾟﾁｽﾛD4DJKB": "D4DJ Pachi‐Slot Mix",
        "Lﾊﾟﾁｽﾛｷﾝﾆｸﾏﾝ4SLDC": "キン肉マン～7人の悪魔超人編～",
        "対魔導学園35試験小隊 H1": "対魔導学園35試験小隊",
        "Angel Beats！ XF": "Angel Beats!",
        "交響詩篇ｴｳﾚｶｾﾌﾞﾝTYPE-ART": "交響詩篇エウレカセブン HI-EVOLUTION ZERO TYPE‐ART",
    }
    for raw, official in expected.items():
        assert model_name(raw) == official
    assert model_name("パチスロ戦国恋姫") == "戦国†恋姫"


def test_five_setting_machine_has_no_setting_3():
    from backtest.bonus_specs import load_specs, normalize

    spec = load_specs()[normalize("キン肉マン～7人の悪魔超人編～")]
    assert 3 not in spec["settings"] or spec["settings"][3].get("payout_rate") is None


def test_konosuba_and_mhr_aliases_confirmed():
    assert model_name("L A このすば FX") == model_name("この素晴らしい世界に祝福")
    assert "A" in model_name("この素晴らしい世界に祝福") and "SLOT" in model_name("この素晴らしい世界に祝福")
    assert model_name("スマスロ モンスターハンターライズ") == "モンスターハンターライズ"
