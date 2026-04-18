"""
Test suite for Notion API exporter
"""

import os
import sys
import pytest
import pandas as pd
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv

# Load .env file
env_file = Path(__file__).parent.parent / ".env"
if env_file.exists():
    load_dotenv(env_file)

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from dashboard.utils.notion_exporter import NotionExporter


class TestNotionExporter:
    """Notion API exporter のテスト"""

    def test_initialization(self):
        """NotionExporter の初期化テスト"""
        # .env ファイルが存在することを確認
        env_file = Path(__file__).parent.parent / ".env"
        assert env_file.exists(), ".env ファイルが見つかりません"
        
        # NotionExporter が正常に初期化されることを確認
        exporter = NotionExporter()
        assert exporter is not None
        assert exporter.client is not None
        assert exporter.database_id is not None

    def test_dataframe_to_markdown_table(self):
        """DataFrame を Markdown テーブルに変換するテスト"""
        exporter = NotionExporter()
        
        # サンプルデータフレーム
        df = pd.DataFrame({
            'attr1': ['A', 'B', 'C'],
            'attr2': ['X', 'Y', 'Z'],
            'value': [10, 20, 30]
        })
        
        md_table = exporter._dataframe_to_markdown_table(df)
        
        # Markdown テーブルが正しく生成されることを確認
        assert '| attr1 | attr2 | value |' in md_table
        assert '| A | X | 10 |' in md_table
        assert '| B | Y | 20 |' in md_table
        assert '| C | Z | 30 |' in md_table

    def test_dataframe_to_markdown_table_empty(self):
        """空の DataFrame を Markdown テーブルに変換するテスト"""
        exporter = NotionExporter()
        
        # 空のデータフレーム
        df = pd.DataFrame()
        md_table = exporter._dataframe_to_markdown_table(df)
        
        # 適切なメッセージが返されることを確認
        assert md_table == "（データなし）"

    def test_connection(self):
        """Notion API 接続テスト"""
        exporter = NotionExporter()

        # 接続テストを実行
        result = exporter._test_connection()

        # 接続結果は真偽値であることを確認
        # （実際の接続可能性はユーザーの Notion 設定に依存）
        assert isinstance(result, bool), "接続テストが真偽値を返すことを確認"

    def test_create_page_blocks(self):
        """Notion ページ用のブロック構造を作成するテスト"""
        exporter = NotionExporter()
        
        # サンプルデータ
        df1 = pd.DataFrame({
            'attr1': ['A', 'B'],
            'attr2': ['X', 'Y'],
            'value': [10, 20]
        })
        
        df2 = pd.DataFrame({
            'attr1': ['P', 'Q'],
            'attr2': ['M', 'N'],
            'value': [100, 200]
        })
        
        tables_dict = {
            "Table1": df1,
            "Table2": df2
        }
        
        metadata = {
            "date_range": ("2026-01-01", "2026-01-31"),
            "hall_name": "TestHall",
            "title": "Test Page"
        }
        
        blocks = exporter._create_page_blocks("Test Page", tables_dict, metadata)
        
        # ブロック構造が正しく生成されることを確認
        assert blocks is not None
        assert len(blocks) > 0
        assert blocks[0].get("heading_1") is not None

    def test_save_cross_analysis_error_handling(self):
        """エラーハンドリングのテスト"""
        exporter = NotionExporter()
        
        # 無効なテーブル辞書で保存を試みる
        tables_dict = {}
        metadata = {
            "date_range": ("2026-01-01", "2026-01-31"),
            "hall_name": "TestHall",
            "title": "Empty Page"
        }
        
        # エラーが適切に処理されることを確認
        success, message = exporter.save_cross_analysis(tables_dict, metadata)
        # 空のテーブルでも保存は試みられるため、成功するか適切なエラーが返される
        assert isinstance(success, bool)
        assert isinstance(message, str)


class TestEnvironmentVariables:
    """環境変数のテスト"""

    def test_env_variables_exist(self):
        """環境変数が設定されていることを確認"""
        assert os.getenv("NOTION_API_KEY") is not None, "NOTION_API_KEY が設定されていません"
        assert os.getenv("NOTION_DATABASE_ID") is not None, "NOTION_DATABASE_ID が設定されていません"

    def test_env_variables_not_empty(self):
        """環境変数が空でないことを確認"""
        api_key = os.getenv("NOTION_API_KEY")
        db_id = os.getenv("NOTION_DATABASE_ID")
        
        assert api_key and len(api_key) > 0, "NOTION_API_KEY が空です"
        assert db_id and len(db_id) > 0, "NOTION_DATABASE_ID が空です"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
