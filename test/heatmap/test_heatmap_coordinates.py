from Heatmap.coordinate_utils import get_display_columns


def test_get_display_columns_prefers_display_coordinates() -> None:
    assert get_display_columns({"X", "Y", "display_x", "display_y"}) == (
        "display_x",
        "display_y",
    )


def test_get_display_columns_supports_legacy_coordinates() -> None:
    assert get_display_columns({"X", "Y"}) == ("X", "Y")
