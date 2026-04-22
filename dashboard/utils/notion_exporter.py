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


def _escape_markdown_pipe(val):
    """Markdown テーブル用にパイプをエスケープ

    Args:
        val: 値（任意の型）

    Returns:
        エスケープされた文字列
    """
    return str(val).replace("|", "\\|")


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
        """DataFrame を Markdown テーブルに変換

        パイプ（|）を含む値は自動的にエスケープされます。

        Args:
            df: 変換対象のデータフレーム

        Returns:
            Markdown テーブル形式の文字列
        """
        if df.empty:
            return "（データなし）"

        # インデックスをリセット
        df = df.reset_index(drop=True)

        # ヘッダー行を作成（列名をエスケープ）
        md_lines = []
        header = "| " + " | ".join(
            _escape_markdown_pipe(col) for col in df.columns
        ) + " |"
        md_lines.append(header)

        # セパレーター行を作成
        separator = "| " + " | ".join(["---"] * len(df.columns)) + " |"
        md_lines.append(separator)

        # データ行を作成（セル値をエスケープ）
        for _, row in df.iterrows():
            row_str = "| " + " | ".join(
                _escape_markdown_pipe(val) for val in row.values
            ) + " |"
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
                    "rich_text": [{"text": {"content": f"{table_name} ({len(df)} 行)"}}]
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

    def _create_parent_page(self, title, metadata):
        """親ページを作成（メタデータ記載）"""
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
        tags = metadata.get("tags", "")
        memo = metadata.get("memo", "")

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

        if tags:
            blocks.append({
                "paragraph": {
                    "rich_text": [
                        {
                            "text": {
                                "content": f"タグ: {tags}"
                            }
                        }
                    ]
                }
            })

        if memo:
            blocks.append({
                "paragraph": {
                    "rich_text": [
                        {
                            "text": {
                                "content": f"メモ: {memo}"
                            }
                        }
                    ]
                }
            })

        blocks.append({"divider": {}})

        # 親ページを作成
        response = self.client.pages.create(
            parent={
                "type": "database_id",
                "database_id": self.database_id
            },
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
        return response

    def _create_database_with_records(self, parent_page_id, table_name, df):
        """
        Notion Database を作成してレコードを挿入

        Args:
            parent_page_id: 親ページID
            table_name: テーブル名
            df: データフレーム（attr2, total_diff, avg_diff, win_rate, count, avg_games）
        """
        try:
            # Database のスキーマを定義（シンプル版）
            db_response = self.client.databases.create(
                parent={
                    "type": "page_id",
                    "page_id": parent_page_id
                },
                title=[
                    {
                        "type": "text",
                        "text": {
                            "content": table_name
                        }
                    }
                ],
                properties={
                    "Name": {
                        "type": "title"
                    }
                }
            )

            db_id = db_response.get("id")
            logger.info(f"✓ Database 作成: {table_name} (ID: {db_id})")

            # Database にプロパティを追加
            self.client.databases.update(
                database_id=db_id,
                properties={
                    "attr2": {
                        "type": "rich_text"
                    },
                    "total_diff": {
                        "type": "number",
                        "number": {"format": "number"}
                    },
                    "avg_diff": {
                        "type": "number",
                        "number": {"format": "number_with_commas"}
                    },
                    "win_rate": {
                        "type": "number",
                        "number": {"format": "percent"}
                    },
                    "count": {
                        "type": "number",
                        "number": {"format": "number"}
                    },
                    "avg_games": {
                        "type": "number",
                        "number": {"format": "number_with_commas"}
                    }
                }
            )
            logger.info(f"✓ プロパティ追加完了: {table_name}")

            # 各行をレコードとして挿入
            for idx, (_, row) in enumerate(df.iterrows()):
                try:
                    self.client.pages.create(
                        parent={
                            "type": "database_id",
                            "database_id": db_id
                        },
                        properties={
                            "Name": {
                                "title": [
                                    {
                                        "text": {
                                            "content": str(row["attr2"])
                                        }
                                    }
                                ]
                            },
                            "attr2": {
                                "rich_text": [
                                    {
                                        "text": {
                                            "content": str(row["attr2"])
                                        }
                                    }
                                ]
                            },
                            "total_diff": {
                                "number": int(row["total_diff"])
                            },
                            "avg_diff": {
                                "number": float(row["avg_diff"])
                            },
                            "win_rate": {
                                "number": float(row["win_rate"])
                            },
                            "count": {
                                "number": int(row["count"])
                            },
                            "avg_games": {
                                "number": float(row["avg_games"])
                            }
                        }
                    )
                except Exception as e:
                    logger.error(f"レコード挿入失敗 (行{idx+1}): {e}")
                    raise

            logger.info(f"✓ {len(df)} 件のレコードを挿入: {table_name}")

        except Exception as e:
            logger.error(f"Database 作成失敗 ({table_name}): {e}")
            raise

    def save_cross_analysis_as_databases(self, tables_dict, metadata):
        """
        クロス分析テーブルを Notion Database として保存

        Args:
            tables_dict: {テーブル名: DataFrame, ...}
            metadata: メタデータ辞書

        Returns:
            (success: bool, page_url: str or error_msg: str)
        """
        try:
            # Notion API 接続テスト
            if not self._test_connection():
                return False, "Notion API への接続に失敗しました。API キー、Database ID を確認してください。"

            title = metadata.get("title", "クロス分析結果")

            # 親ページを作成
            parent_page = self._create_parent_page(title, metadata)
            parent_page_id = parent_page.get("id")
            logger.info(f"✓ 親ページ作成: {parent_page_id}")

            # 各テーブルを Database として作成
            for table_name, df in tables_dict.items():
                self._create_database_with_records(parent_page_id, table_name, df)

            page_url = f"https://www.notion.so/{parent_page_id.replace('-', '')}"
            logger.info(f"✓ Notion に保存成功: {page_url}")
            return True, page_url

        except Exception as e:
            error_message = self._classify_error(e)
            logger.error(f"Notion への保存に失敗: {error_message}")
            return False, error_message

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
                return False, "Notion API への接続に失敗しました。API キー、Database ID を確認してください。"

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
            error_message = self._classify_error(e)
            logger.error(f"Notion への保存に失敗: {error_message}")
            return False, error_message

    def _classify_error(self, error: Exception) -> str:
        """
        Notion API エラーを分類して適切なメッセージを返す

        Args:
            error: 発生した例外

        Returns:
            ユーザーフレンドリーなエラーメッセージ
        """
        error_str = str(error).lower()

        # Rate limit エラー
        if "rate_limit" in error_str or "429" in error_str:
            return "リクエスト数の上限に達しました。少し時間をおいて再度お試しください。"

        # 認証エラー
        if "invalid_grant" in error_str or "unauthorized" in error_str:
            return "Notion API キーが無効です。.env ファイルを確認してください。"

        # Database ID エラー
        if "database_id" in error_str or "not_found" in error_str:
            return "Notion Database が見つかりません。Database ID を確認してください。"

        # その他のエラー
        return f"Notion への保存に失敗しました: {str(error)}"
