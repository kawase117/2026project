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
