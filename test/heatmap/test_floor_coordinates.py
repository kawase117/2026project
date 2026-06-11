from pathlib import Path

import pandas as pd


COORDS_PATH = Path("Heatmap/2F_floor_coordinates.csv")
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


def load_coordinates() -> pd.DataFrame:
    return pd.read_csv(COORDS_PATH)


def test_kamata1_coordinate_contract() -> None:
    df = load_coordinates()

    assert REQUIRED_COLUMNS.issubset(df.columns)
    assert len(df) == 360
    assert df["machine_number"].is_unique
    assert not df[["display_x", "display_y"]].duplicated().any()

    excluded = set(range(2341, 2399))
    assert excluded.isdisjoint(set(df["machine_number"]))


def test_kamata1_floor_column_is_present_and_constant() -> None:
    df = load_coordinates()

    assert set(df["floor"]) == {"2F"}


def test_kamata1_machine_number_coverage() -> None:
    df = load_coordinates()
    expected = set(range(2001, 2341)) | set(range(2399, 2416)) | {1631, 1632, 1633}

    assert set(df["machine_number"]) == expected


def test_section_ranks_are_continuous() -> None:
    df = load_coordinates()

    for _, section in df.groupby("section"):
        size = len(section)
        assert sorted(section["rank_from_min"]) == list(range(1, size + 1))
        assert sorted(section["rank_from_max"]) == list(range(1, size + 1))
        assert section["section_min"].nunique() == 1
        assert section["section_max"].nunique() == 1


def test_2001_to_2020_is_a_diagonal_run() -> None:
    df = load_coordinates().set_index("machine_number").loc[2001:2020].reset_index()

    assert df["display_x"].diff().dropna().eq(1).all()
    assert df["display_y"].diff().dropna().eq(-1).all()


def test_2399_to_2415_is_a_vertical_run() -> None:
    df = load_coordinates().set_index("machine_number").loc[2399:2415].reset_index()

    assert df["display_x"].nunique() == 1
    assert df["display_y"].diff().dropna().eq(1).all()


def test_2143_to_2150_is_two_rows_of_four() -> None:
    df = load_coordinates().set_index("machine_number")

    assert df.loc[2143:2146, ["display_x", "display_y"]].values.tolist() == [
        [43, 31],
        [42, 32],
        [41, 33],
        [40, 34],
    ]
    assert df.loc[2147:2150, ["display_x", "display_y"]].values.tolist() == [
        [40, 37],
        [41, 36],
        [42, 35],
        [43, 34],
    ]
    assert set(df.loc[2143:2146, "section"]) == {"2143-2146"}
    assert set(df.loc[2147:2150, "section"]) == {"2147-2150"}


def test_2162_to_2166_and_2187_to_2190_are_back_to_back() -> None:
    df = load_coordinates().set_index("machine_number")

    pairs = [
        (2162, 2190),
        (2163, 2189),
        (2164, 2188),
        (2165, 2187),
    ]
    for front_machine, back_machine in pairs:
        assert df.loc[front_machine, "display_x"] == df.loc[back_machine, "display_x"]
        assert (
            df.loc[back_machine, "display_y"]
            - df.loc[front_machine, "display_y"]
            == 3
        )
