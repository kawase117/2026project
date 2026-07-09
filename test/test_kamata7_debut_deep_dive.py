from __future__ import annotations

import pandas as pd

from eda import kamata7_debut_deep_dive as debut


def test_count_group_kamata7_boundaries() -> None:
    assert debut._count_group_kamata7(1) == "XXS"
    assert debut._count_group_kamata7(3) == "XXS"
    assert debut._count_group_kamata7(4) == "XS"
    assert debut._count_group_kamata7(10) == "XS"
    assert debut._count_group_kamata7(11) == "S"
    assert debut._count_group_kamata7(18) == "S"
    assert debut._count_group_kamata7(19) == "M"
    assert debut._count_group_kamata7(30) == "M"
    assert debut._count_group_kamata7(31) == "L"
    assert debut._count_group_kamata7(42) == "L"
    assert debut._count_group_kamata7(43) == "XL"


def test_dd_category_prioritizes_zorome_then_month_end() -> None:
    assert debut._dd_category(pd.Series({"dd": 22, "is_mmdd_zorome": 1, "is_month_end": 1})) == "強ゾロ目"
    assert debut._dd_category(pd.Series({"dd": 22, "is_mmdd_zorome": 0, "is_month_end": 0})) == "ゾロ目"
    assert debut._dd_category(pd.Series({"dd": 17, "is_mmdd_zorome": 0, "is_month_end": 0})) == "7系"
    assert debut._dd_category(pd.Series({"dd": 11, "is_mmdd_zorome": 0, "is_month_end": 0})) == "ゾロ目"
    assert debut._dd_category(pd.Series({"dd": 30, "is_mmdd_zorome": 0, "is_month_end": 1})) == "月末"
    assert debut._dd_category(pd.Series({"dd": 13, "is_mmdd_zorome": 0, "is_month_end": 0})) == "その他"


def test_keyword_classifiers_cover_common_names() -> None:
    assert debut._classify_seg_keyword("マイジャグラーV") == "A"
    assert debut._classify_seg_keyword("LモンキーターンV") == "N"
    assert debut._classify_family_keyword("アイムジャグラーEX-TP") == "jug"
    assert debut._classify_family_keyword("ニューキングハナハナ") == "hana"
    assert debut._classify_family_keyword("不二子BT") == "bt"
    assert debut._classify_family_keyword("LモンキーターンV") == "other"


def test_agg_summary_marks_low_n() -> None:
    frame = pd.DataFrame(
        {
            "machine_name": ["m1", "m2", "m1", "m2"],
            "diff": [10, -5, 20, -10],
            "games": [100, 200, 150, 250],
            "group": ["A", "A", "B", "B"],
        }
    )

    out = debut._agg_summary(frame, ["group"], note_low_n=5)

    assert list(out["group"]) == ["A", "B"]
    assert list(out["note"]) == ["low_n", "low_n"]
    assert out.loc[out["group"] == "A", "avg_diff"].iloc[0] == 2
