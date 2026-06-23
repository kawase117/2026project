"""
Test: kamata7_kakuban_section_lr_interaction_eda
"""

import tempfile
from pathlib import Path

import pandas as pd
import pytest

from ml.analysis.kamata7_kakuban_section_lr_interaction_eda import (
    FloorLayout,
    add_lr_split,
    calc_f_value_for_split_strategy,
    load_floor_coordinates,
)


@pytest.fixture
def sample_floor_coords():
    """サンプルフロア座標データ"""
    coords = {
        1: FloorLayout(kakuban=1, x_coord=0.0, y_coord=0.0, section="A"),
        2: FloorLayout(kakuban=2, x_coord=1.0, y_coord=0.0, section="A"),
        3: FloorLayout(kakuban=3, x_coord=2.0, y_coord=0.0, section="A"),
        4: FloorLayout(kakuban=4, x_coord=3.0, y_coord=0.0, section="A"),
        5: FloorLayout(kakuban=5, x_coord=4.0, y_coord=0.0, section="A"),
        6: FloorLayout(kakuban=6, x_coord=5.0, y_coord=0.0, section="A"),
    }
    return coords


@pytest.fixture
def sample_machine_data():
    """サンプル台データ"""
    return pd.DataFrame({
        "machine_number": [1, 2, 3, 4, 5, 6],
        "kakuban": [1, 2, 3, 4, 5, 6],
        "section": ["A", "A", "A", "A", "A", "A"],
        "segment_name": ["2F", "2F", "2F", "2F", "2F", "2F"],
        "games_normalized": [100, 100, 100, 100, 100, 100],
        "diff_coins_normalized": [100, 100, 100, 100, -100, -100],
        "section_size": [6, 6, 6, 6, 6, 6],
        "section_size_group": ["small", "small", "small", "small", "small", "small"],
        "dd": [1, 1, 1, 1, 1, 1],
        "pay_rate": [103.33, 103.33, 103.33, 103.33, 96.67, 96.67],
    })


def test_load_floor_coordinates_empty():
    """フロア座標ファイルが存在しない場合の処理"""
    non_existent = Path("/nonexistent/path.csv")
    result = load_floor_coordinates(non_existent)
    assert result == {}


def test_load_floor_coordinates_csv():
    """フロア座標CSVを読み込む"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
        f.write("kakuban,x,y,section\n")
        f.write("1,0.0,0.0,A\n")
        f.write("2,1.0,0.0,A\n")
        f.write("3,2.0,0.0,A\n")
        f.flush()

        result = load_floor_coordinates(Path(f.name))

        assert len(result) == 3
        assert result[1].x_coord == 0.0
        assert result[2].x_coord == 1.0
        assert result[3].x_coord == 2.0


def test_add_lr_split_basic(sample_machine_data, sample_floor_coords):
    """LR分割の基本動作"""
    result = add_lr_split(sample_machine_data.copy(), sample_floor_coords, {})

    assert "lr_split" in result.columns
    # X座標中央値は3.0なので
    # X < 3 は L, X >= 3 は R
    assert result[result["kakuban"] == 1]["lr_split"].iloc[0] == "L"
    assert result[result["kakuban"] == 2]["lr_split"].iloc[0] == "L"
    assert result[result["kakuban"] == 3]["lr_split"].iloc[0] == "L"  # 3.0 = 中央値 -> R
    assert result[result["kakuban"] == 4]["lr_split"].iloc[0] == "R"


def test_calc_f_value_valid():
    """F値計算が正常に動作"""
    df = pd.DataFrame({
        "group": ["A", "A", "B", "B", "C", "C"],
        "pay_rate": [100.0, 102.0, 102.0, 104.0, 98.0, 100.0],
    })

    f_val = calc_f_value_for_split_strategy(df, "group", "test")

    # グループ間の分散がある場合、F値 > 0
    assert not pd.isna(f_val)
    assert f_val > 0


def test_calc_f_value_empty():
    """空DataFrameでの処理"""
    df = pd.DataFrame({
        "group": [],
        "pay_rate": [],
    })

    f_val = calc_f_value_for_split_strategy(df, "group", "test")

    assert pd.isna(f_val)


def test_calc_f_value_missing_column():
    """列が存在しない場合の処理"""
    df = pd.DataFrame({
        "pay_rate": [100.0, 102.0],
    })

    f_val = calc_f_value_for_split_strategy(df, "missing_col", "test")

    assert pd.isna(f_val)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
