from pathlib import Path

import pandas as pd
import pytest


CSV_PATHS = {
    "2F": Path("Heatmap/2F_floor_coordinates_kamata7.csv"),
    "3F": Path("Heatmap/3F_floor_coordinates_kamata7.csv"),
}
REQUIRED_COLUMNS = {
    "hall_name",
    "floor",
    "machine_number",
    "X",
    "Y",
    "display_x",
    "display_y",
    "section",
    "section_min",
    "section_max",
    "rank_from_min",
    "rank_from_max",
}
EXPECTED_SECTIONS = {
    "2F": [
        (2001, 2010),
        (2011, 2022),
        (2023, 2031),
        (2032, 2040),
        (2041, 2052),
        (2053, 2064),
        (2065, 2076),
        (2077, 2088),
        (2089, 2101),
        (2102, 2114),
        (2115, 2128),
        (2129, 2142),
        (2143, 2154),
        (2155, 2164),
        (2165, 2171),
        (2172, 2178),
        (2179, 2186),
        (2187, 2195),
        (2196, 2212),
        (2213, 2229),
        (2230, 2246),
        (2247, 2263),
        (2264, 2280),
        (2281, 2297),
        (2298, 2313),
        (2314, 2329),
        (2330, 2351),
    ],
    "3F": [
        (3001, 3016),
        (3017, 3030),
        (3031, 3042),
        (3043, 3057),
        (3058, 3072),
        (3073, 3087),
        (3088, 3102),
        (3103, 3116),
        (3117, 3130),
        (3131, 3143),
        (3144, 3155),
        (3156, 3167),
        (3168, 3180),
        (3181, 3190),
        (3191, 3208),
        (3209, 3217),
        (3218, 3233),
        (3234, 3249),
        (3250, 3264),
        (3265, 3280),
        (3281, 3294),
        (3295, 3309),
        (3310, 3324),
        (3325, 3340),
        (3341, 3362),
        (3400, 3401),
    ],
}


@pytest.mark.parametrize(
    ("floor", "expected"),
    [
        ("2F", set(range(2001, 2352))),
        ("3F", set(range(3001, 3363)) | {3400, 3401}),
    ],
)
def test_kamata7_floor_coordinate_contract(floor: str, expected: set[int]) -> None:
    df = pd.read_csv(CSV_PATHS[floor])

    assert REQUIRED_COLUMNS.issubset(df.columns)
    assert set(df["floor"]) == {floor}
    assert set(df["hall_name"]) == {"マルハンメガシティ2000-蒲田7"}
    assert set(df["machine_number"]) == expected
    assert df["machine_number"].is_unique
    assert not df[["display_x", "display_y"]].duplicated().any()


@pytest.mark.parametrize("floor", ["2F", "3F"])
def test_kamata7_section_ranks_are_continuous(floor: str) -> None:
    df = pd.read_csv(CSV_PATHS[floor])

    for _, section in df.groupby("section"):
        size = len(section)
        assert sorted(section["rank_from_min"]) == list(range(1, size + 1))
        assert sorted(section["rank_from_max"]) == list(range(1, size + 1))
        assert section["section_min"].nunique() == 1
        assert section["section_max"].nunique() == 1


@pytest.mark.parametrize("floor", ["2F", "3F"])
def test_kamata7_sections_match_store_floor_map(floor: str) -> None:
    df = pd.read_csv(CSV_PATHS[floor])

    actual = {
        (int(section_min), int(section_max))
        for section_min, section_max in df[
            ["section_min", "section_max"]
        ].drop_duplicates().itertuples(index=False, name=None)
    }
    expected = set(EXPECTED_SECTIONS[floor])

    assert actual == expected
    for section_min, section_max in expected:
        section = df[
            (df["section_min"] == section_min)
            & (df["section_max"] == section_max)
        ]
        assert len(section) == section_max - section_min + 1
        assert set(section["section"]) == {f"{section_min}-{section_max}"}


def test_kamata7_3f_known_rows_match_the_map() -> None:
    df = pd.read_csv(CSV_PATHS["3F"]).set_index("machine_number")

    top = df.loc[3001:3016]
    assert top["display_y"].nunique() == 1
    assert top["display_x"].diff().dropna().eq(1).all()

    left_side = df.loc[3191:3208]
    assert left_side["display_x"].nunique() == 1
    assert left_side["display_y"].diff().dropna().eq(-1).all()

    right_side = df.loc[3209:3217]
    assert right_side["display_x"].nunique() == 1
    assert right_side["display_y"].diff().dropna().eq(1).all()


def test_kamata7_2f_right_column_is_straight() -> None:
    df = pd.read_csv(CSV_PATHS["2F"]).set_index("machine_number")

    right_column = df.loc[list(range(2187, 2196)) + list(range(2330, 2335))]
    assert right_column["display_x"].nunique() == 1
    assert right_column["display_x"].iloc[0] == 38
    assert right_column["display_y"].tolist() == [
        3,
        4,
        5,
        6,
        8,
        9,
        10,
        11,
        12,
        14,
        15,
        16,
        18,
        19,
    ]


def test_kamata7_2f_lower_left_islands_match_the_map() -> None:
    df = pd.read_csv(CSV_PATHS["2F"]).set_index("machine_number")

    assert df.loc[2155:2164, "display_x"].tolist() == list(range(6, 16))
    assert df.loc[2165:2171, "display_x"].tolist() == list(range(16, 9, -1))
    assert df.loc[2172:2178, "display_x"].tolist() == list(range(10, 17))
    assert df.loc[2179:2186, "display_x"].tolist() == list(range(17, 9, -1))
    assert df.loc[2155:2164, "display_y"].nunique() == 1
    assert df.loc[2165:2171, "display_y"].unique().tolist() == [23]
    assert df.loc[2172:2178, "display_y"].unique().tolist() == [24]
    assert df.loc[2179:2186, "display_y"].unique().tolist() == [26]


def test_kamata7_2f_left_vertical_aisle_is_aligned() -> None:
    df = pd.read_csv(CSV_PATHS["2F"]).set_index("machine_number")

    aisle_edges = [
        (2098, 2097),
        (2105, 2106),
        (2123, 2122),
        (2134, 2135),
        (2151, 2150),
    ]
    for left_machine, right_machine in aisle_edges:
        assert df.loc[left_machine, "display_x"] == 6
        assert df.loc[right_machine, "display_x"] == 8


def test_kamata7_2f_upper_left_blocks_match_the_map() -> None:
    df = pd.read_csv(CSV_PATHS["2F"]).set_index("machine_number")

    assert df.loc[2006, "display_y"] == 8
    assert df.loc[2005, "display_y"] == 10
    assert df.loc[2006, "display_y"] + 2 == df.loc[2005, "display_y"]

    assert df.loc[2043, "display_x"] + 1 == df.loc[2042, "display_x"]
    assert df.loc[2062, "display_x"] + 1 == df.loc[2063, "display_x"]

    assert df.loc[2041, "display_x"] == 16
    assert df.loc[2064, "display_x"] == 16
    assert df.loc[2088, "display_x"] == 16
