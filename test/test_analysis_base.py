"""analysis_base.py の単体テスト"""

import sys
import pandas as pd
from pathlib import Path

# backtest モジュールのインポート
sys.path.insert(0, str(Path(__file__).parent.parent / 'backtest'))

from analysis_base import split_groups_triple_custom


class TestSplitGroupsTripleCustom:
    """split_groups_triple_custom() のテストクラス"""

    def test_split_groups_triple_custom_5050(self):
        """50-0-50 分割テスト"""
        df = pd.DataFrame({'id': range(100), 'value': range(100)})
        top, mid, low = split_groups_triple_custom(df, 'value', 50, 0, 50)

        assert len(top) == 50, f"Expected top=50, got {len(top)}"
        assert len(mid) == 0, f"Expected mid=0, got {len(mid)}"
        assert len(low) == 50, f"Expected low=50, got {len(low)}"

    def test_split_groups_triple_custom_363636(self):
        """36-28-36 分割テスト"""
        df = pd.DataFrame({'id': range(100), 'value': range(100)})
        top, mid, low = split_groups_triple_custom(df, 'value', 36, 28, 36)

        assert len(top) == 36, f"Expected top=36, got {len(top)}"
        assert len(mid) == 28, f"Expected mid=28, got {len(mid)}"
        assert len(low) == 36, f"Expected low=36, got {len(low)}"

    def test_split_groups_triple_custom_empty_dataframe(self):
        """空の DataFrame テスト"""
        df = pd.DataFrame({'id': [], 'value': []})
        top, mid, low = split_groups_triple_custom(df, 'value', 50, 0, 50)

        assert top is None
        assert mid is None
        assert low is None

    def test_split_groups_triple_custom_values_integrity(self):
        """分割後の値の整合性テスト"""
        df = pd.DataFrame({'id': range(100), 'value': range(100)})
        top, mid, low = split_groups_triple_custom(df, 'value', 36, 28, 36)

        # グループ全体で元のデータ数を復元できることを確認
        assert len(top) + len(mid) + len(low) == len(df), "Sum of groups should equal original dataframe size"

        # 各グループの値が期待範囲にあることを確認（36-28-36 の場合）
        # low: 0-35, mid: 36-63, top: 64-99
        if len(low) > 0 and len(mid) > 0:
            assert low['value'].max() < mid['value'].min(), "Low group should have smaller values than mid"
        if len(mid) > 0 and len(top) > 0:
            assert mid['value'].max() < top['value'].min(), "Mid group should have smaller values than top"

    def test_split_groups_triple_custom_4520(self):
        """45-10-45 分割テスト"""
        df = pd.DataFrame({'id': range(100), 'value': range(100)})
        top, mid, low = split_groups_triple_custom(df, 'value', 45, 10, 45)

        assert len(top) == 45, f"Expected top=45, got {len(top)}"
        assert len(mid) == 10, f"Expected mid=10, got {len(mid)}"
        assert len(low) == 45, f"Expected low=45, got {len(low)}"

    def test_split_groups_triple_custom_4020(self):
        """40-20-40 分割テスト"""
        df = pd.DataFrame({'id': range(100), 'value': range(100)})
        top, mid, low = split_groups_triple_custom(df, 'value', 40, 20, 40)

        assert len(top) == 40, f"Expected top=40, got {len(top)}"
        assert len(mid) == 20, f"Expected mid=20, got {len(mid)}"
        assert len(low) == 40, f"Expected low=40, got {len(low)}"

    def test_split_groups_triple_custom_333433(self):
        """33-34-33 分割テスト"""
        df = pd.DataFrame({'id': range(100), 'value': range(100)})
        top, mid, low = split_groups_triple_custom(df, 'value', 33, 34, 33)

        assert len(top) == 33, f"Expected top=33, got {len(top)}"
        assert len(mid) == 34, f"Expected mid=34, got {len(mid)}"
        assert len(low) == 33, f"Expected low=33, got {len(low)}"


if __name__ == '__main__':
    import pytest
    pytest.main([__file__, '-v'])
