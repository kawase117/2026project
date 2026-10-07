import json

from scraper.realtime.quick_filter import site_model_allowlist

HALL = "楽園蒲田店"


def test_allowlist_keeps_only_rb_eligible_models(tmp_path):
    path = tmp_path / "full.json"
    path.write_text(
        json.dumps({"models": {"1": {"name": "判別可"}, "2": {"name": "判別不可"}, "3": {"name": "未照合"}, "4": {}}}),
        encoding="utf-8-sig",
    )
    resolve = {"判別可": "正式A", "判別不可": "正式X"}.get
    audit = {(HALL, "正式A"): "A", (HALL, "正式X"): "X"}
    assert site_model_allowlist(path, HALL, audit, {}, resolve) == ["判別可"]


def test_allowlist_empty_when_no_previous_full_data(tmp_path):
    assert site_model_allowlist(tmp_path / "none.json", HALL, {}, {}, lambda _: None) == []
