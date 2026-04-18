"""
Notion API 連携
クロス分析結果を Notion Database に保存する
"""
import os
from notion_client import Client
import pandas as pd
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


class NotionExporter:
    """Notion API クライアント"""

    def __init__(self):
        api_key = os.getenv("NOTION_API_KEY")
        if not api_key:
            raise ValueError("NOTION_API_KEY environment variable not set")
        self.client = Client(auth=api_key)
        self.database_id = os.getenv("NOTION_DATABASE_ID")
        if not self.database_id:
            raise ValueError("NOTION_DATABASE_ID environment variable not set")

    def _test_connection(self):
        """Notion API 接続テスト"""
        try:
            db = self.client.databases.retrieve(self.database_id)
            logger.info(f"✓ Notion API 接続成功: {db.get('title', 'Unknown')}")
            return True
        except Exception as e:
            logger.error(f"✗ Notion API 接続失敗: {e}")
            return False

    def _dataframe_to_markdown_table(self, df):
        """DataFrame を Markdown テーブルに変換"""
        if df.empty:
            return "（データなし）"
        
        # インデックスをリセット
        df = df.reset_index(drop=True)
        
        # ヘッダー行を作成
        md_lines = []
        header = "| " + " | ".join(str(col) for col in df.columns) + " |"
        md_lines.append(header)
        
        # セパレーター行を作成
        separator = "| " + " | ".join(["---"] * len(df.columns)) + " |"
        md_lines.append(separator)
        
        # データ行を作成
        for _, row in df.iterrows():
            row_str = "| " + " | ".join(str(val) for val in row.values) + " |"
            md_lines.append(row_str)
        
        return "\n".join(md_lines)

    def _create_page_blocks(self, title, tables_dict, metadata):
        """
        Notion ページ用のブロック構造を作成
        
        Args:
            title: ページタイトル
            tables_dict: {テーブル名: DataFrame, ...}
            metadata: メタデータ辞書
        
        Returns:
            ブロック辞書のリスト
        """
        blocks = []
        
        # タイトル
        blocks.append({
            "heading_1": {
                "rich_text": [{"text": {"content": title}}]
            }
        })
        
        # メタデータ
        date_range = metadata.get("date_range", ("", ""))
        hall_name = metadata.get("hall_name", "不明")
        
        blocks.append({
            "heading_2": {
                "rich_text": [{"text": {"content": f"ホール: {hall_name}"}}]
            }
        })
        
        blocks.append({
            "paragraph": {
                "rich_text": [
                    {
                        "text": {
                            "content": f"期間: {date_range[0]} 〜 {date_range[1]}"
                        }
                    }
                ]
            }
        })
        
        blocks.append({
            "paragraph": {
                "rich_text": [
                    {
                        "text": {
                            "content": f"保存日時: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                        }
                    }
                ]
            }
        })
        
        blocks.append({"divider": {}})
        
        # テーブル
        for table_name, df in tables_dict.items():
            blocks.append({
                "heading_3": {
                    "rich_text": [{"text": {"content": table_name}}]
                }
            })
            
            md_table = self._dataframe_to_markdown_table(df)
            blocks.append({
                "code": {
                    "rich_text": [{"text": {"content": md_table}}],
                    "language": "markdown"
                }
            })
            
            blocks.append({"divider": {}})
        
        return blocks

    def save_cross_analysis(self, tables_dict, metadata):
        """
        クロス分析テーブルを Notion に保存
        
        Args:
            tables_dict: {
                "DD別＆機種別": DataFrame,
                "DD別＆台番号末尾別": DataFrame,
                ...
            }
            metadata: {
                "date_range": (start_date_str, end_date_str),
                "hall_name": str,
                "title": str,  # ユーザー入力のタイトル
            }
        
        Returns:
            (success: bool, page_url: str or error_msg: str)
        """
        try:
            # Notion API 接続テスト
            if not self._test_connection():
                return False, "Notion API への接続に失敗しました"
            
            title = metadata.get("title", "クロス分析結果")
            blocks = self._create_page_blocks(title, tables_dict, metadata)
            
            # Notion ページを作成
            response = self.client.pages.create(
                parent={"database_id": self.database_id},
                properties={
                    "title": {
                        "title": [
                            {
                                "text": {
                                    "content": title
                                }
                            }
                        ]
                    }
                },
                children=blocks
            )
            
            page_id = response.get("id")
            page_url = f"https://www.notion.so/{page_id.replace('-', '')}"
            
            logger.info(f"✓ Notion に保存成功: {page_url}")
            return True, page_url
        
        except Exception as e:
            error_msg = f"Notion への保存に失敗: {str(e)}"
            logger.error(error_msg)
            return False, error_msg
