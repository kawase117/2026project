from scraper.realtime.quick_filter import select_first_pass
from scraper.realtime.schema import SnapshotRow

HALL = "ヒロキMAX蒲田店"


def row(unit, model, bb, rb):
    return SnapshotRow(
        hall=HALL,
        observed_at="2026-10-07T13:00:00+09:00",
        source_updated_at=None,
        unit=unit,
        model=model,
        model_raw=model or "",
        games=None,
        bb=bb,
        rb=rb,
        diff=None,
        source="dmm",
    )


def test_first_pass_selects_eligible_with_hits_only():
    audit = {(HALL, "A機"): "A", (HALL, "X機"): "X"}
    rows = [
        row(1, "A機", 1, 0),  # 判別可能・当たりあり -> 対象
        row(2, "A機", 0, 0),  # 当たり無し -> 対象外
        row(3, "X機", 5, 5),  # verdict X -> 対象外
        row(4, None, 5, 5),  # 機種名照合不能 -> 対象外
        row(5, "BT機", 0, 2),  # マスターフラグで判別可能 -> 対象
        row(6, "AT機", 3, 3),  # 判別不可 -> 対象外
    ]
    assert select_first_pass(rows, audit, {"BT機": True}) == [1, 5]
