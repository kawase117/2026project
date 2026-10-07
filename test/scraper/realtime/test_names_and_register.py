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
