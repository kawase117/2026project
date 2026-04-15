#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
イベントカレンダー統合版 - 日付情報を daily_hall_summary に追加
各ホール固有の設定情報を hall_config.json から読み込み、日付情報を計算・DB に追加
weekday_nth実装版（TEXT型, 'Mon1'～'Sun5'形式）
"""

import os
import sys
import json
import sqlite3
import calendar
from datetime import datetime
from pathlib import Path

try:
    import jpholiday
except ImportError:
    jpholiday = None


class DateInfoCalculator:
    """日付情報計算クラス"""
    
    def __init__(self, hall_name: str, db_path: str = None, config_path: str = None):
        """
        初期化
        
        Args:
            hall_name: ホール名
            db_path: DBファイルパス（省略時はデフォルトから生成）
            config_path: hall_config.json のパス
        """
        self.hall_name = hall_name
        
        # config_path の決定
        if config_path is None:
            script_dir = os.path.dirname(os.path.abspath(__file__))
            project_root = os.path.dirname(script_dir) if script_dir.endswith(('database', 'scraper')) else script_dir
            config_path = os.path.join(project_root, "config", "hall_config.json")  # ← "config"を追加
            db_dir = os.path.join(project_root, "db")
            os.makedirs(db_dir, exist_ok=True)
            safe_hall_name = hall_name.replace(" ", "_").replace("（", "(").replace("）", ")")
            self.db_path = os.path.join(db_dir, f"{safe_hall_name}.db")
        else:
            self.db_path = db_path
        
        # config_path の決定
        if config_path is None:
            script_dir = os.path.dirname(os.path.abspath(__file__))
            project_root = os.path.dirname(script_dir) if script_dir.endswith(('database', 'scraper')) else script_dir
            config_path = os.path.join(project_root, "hall_config.json")
        
        self.config_path = config_path
        self.hall_config = self._load_hall_config()
    
    def _load_hall_config(self) -> dict:
        """
        hall_config.json からホール設定を読み込む
        
        Returns:
            ホールの event_settings 辞書
        """
        try:
            with open(self.config_path, 'r', encoding='utf-8') as f:
                config = json.load(f)
            
            # 該当ホールの設定を取得
            for hall in config.get('halls', []):
                if hall.get('hall_name') == self.hall_name:
                    event_settings = hall.get('event_settings', {})
                    return {
                        'event_digits': event_settings.get('event_digits', []),
                        'anniversary_date': event_settings.get('anniversary_date', '')
                    }
            
            # ホールが見つからない場合は空の設定を返す
            return {
                'event_digits': [],
                'anniversary_date': ''
            }
        
        except Exception as e:
            raise Exception(f"config.json読み込みエラー ({self.config_path}): {e}")
    
    def _validate_config(self) -> bool:
        """
        ホール設定の妥当性を検証
        
        Returns:
            妥当性が確認できたら True、エラーの場合は例外を raise
        """
        # anniversary_date の検証
        anniversary_date = self.hall_config.get('anniversary_date', '')
        if anniversary_date:
            if len(anniversary_date) != 4 or not anniversary_date.isdigit():
                raise ValueError(f"anniversary_date の形式が不正です (MMDD形式): {anniversary_date}")
            
            month = int(anniversary_date[:2])
            day = int(anniversary_date[2:])
            
            if not (1 <= month <= 12):
                raise ValueError(f"anniversary_date の月が範囲外です: {month}")
            if not (1 <= day <= 31):
                raise ValueError(f"anniversary_date の日が範囲外です: {day}")
        
        # event_digits の検証
        event_digits = self.hall_config.get('event_digits', [])
        for digit in event_digits:
            if not isinstance(digit, int) or not (1 <= digit <= 31):
                raise ValueError(f"event_digits に無効な値があります: {digit}")
        
        return True
    
    def _get_day_of_week(self, date_obj: datetime) -> str:
        """曜日を日本語で取得"""
        weekday_names = ['月', '火', '水', '木', '金', '土', '日']
        return weekday_names[date_obj.weekday()]
    
    def _get_nth_weekday(self, date_obj: datetime) -> str:
        """
        第N曜日を複合表記で取得（例: 'Mon1', 'Wed2', 'Fri3'）
        
        Returns:
            str: '{曜日2文字}{第N週}' 形式（例: 'Mon1', 'Wed2'）
        """
        weekday_abbr = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
        day = date_obj.day
        weekday_num = date_obj.weekday()  # 0=月, 6=日
        nth = (day - 1) // 7 + 1
        
        return f"{weekday_abbr[weekday_num]}{nth}"
    
    def _get_last_digit(self, day: int) -> int:
        """日の末尾（0-9）を取得"""
        return day % 10
    
    def _check_strong_zorome(self, month: int, day: int) -> bool:
        """強ゾロ目判定（月日が同じ値）"""
        return month == day and month <= 12
    
    def _check_zorome(self, day: int) -> bool:
        """ゾロ目判定（11, 22）"""
        return day in [11, 22]
    
    def _check_month_start(self, day: int) -> bool:
        """月初判定（1日）"""
        return day == 1
    
    def _check_month_end(self, date_obj: datetime) -> bool:
        """月末判定"""
        last_day = calendar.monthrange(date_obj.year, date_obj.month)[1]
        return date_obj.day == last_day
    
    def _check_weekend(self, date_obj: datetime) -> bool:
        """土日判定"""
        return date_obj.weekday() >= 5
    
    def _check_holiday(self, date_obj: datetime) -> bool:
        """祝日判定"""
        try:
            if jpholiday:
                return jpholiday.is_holiday(date_obj.date())
        except:
            pass
        
        # jpholiday が利用できない場合は固定祝日で判定
        month, day = date_obj.month, date_obj.day
        fixed_holidays = [
            (1, 1), (2, 11), (4, 29), (5, 3), (5, 4), (5, 5),
            (8, 11), (11, 3), (11, 23), (12, 23)
        ]
        return (month, day) in fixed_holidays
    
    def _check_x_day(self, day: int) -> bool:
        """X の付く日判定（ホール設定の event_digits と合致）"""
        event_digits = self.hall_config.get('event_digits', [])
        return day in event_digits
    
    def _check_hall_anniversary(self, month: int, day: int) -> bool:
        """周年判定"""
        anniversary_date = self.hall_config.get('anniversary_date', '')
        if not anniversary_date:
            return False
        
        ann_month = int(anniversary_date[:2])
        ann_day = int(anniversary_date[2:])
        
        return month == ann_month and day == ann_day
    
    def _get_week_of_month(self, day: int) -> int:
        """月の第何週かを取得（1日スタート）"""
        return (day - 1) // 7 + 1
    
    def calculate_date_info(self, date_str: str) -> dict:
        """
        指定日の日付情報を全て計算
        
        Args:
            date_str: 日付（YYYYMMDD）
        
        Returns:
            日付情報の辞書
        """
        try:
            date_obj = datetime.strptime(date_str, '%Y%m%d')
        except ValueError:
            raise ValueError(f"日付形式が不正です: {date_str}")
        
        month = date_obj.month
        day = date_obj.day
        last_digit = self._get_last_digit(day)
        
        # 各フラグを計算
        is_strong_zorome = self._check_strong_zorome(month, day)
        is_zorome = self._check_zorome(day)
        is_month_start = self._check_month_start(day)
        is_month_end = self._check_month_end(date_obj)
        is_weekend = self._check_weekend(date_obj)
        is_holiday = self._check_holiday(date_obj)
        is_x_day = self._check_x_day(day)
        hall_anniversary = self._check_hall_anniversary(month, day)
        
        # is_any_event の計算
        is_any_event = is_holiday or is_weekend or is_x_day
        
        info = {
            'date': date_str,
            'day_of_week': self._get_day_of_week(date_obj),
            'last_digit': last_digit,
            'weekday_nth': self._get_nth_weekday(date_obj),
            'is_strong_zorome': 1 if is_strong_zorome else 0,
            'is_zorome': 1 if is_zorome else 0,
            'is_month_start': 1 if is_month_start else 0,
            'is_month_end': 1 if is_month_end else 0,
            'is_weekend': 1 if is_weekend else 0,
            'is_holiday': 1 if is_holiday else 0,
            'hall_anniversary': 1 if hall_anniversary else 0,
            'is_x_day': 1 if is_x_day else 0,
            'week_of_month': self._get_week_of_month(day),
            'is_any_event': 1 if is_any_event else 0
        }
        
        return info
    
    def add_date_info_columns(self) -> bool:
        """
        daily_hall_summary に日付情報カラムを追加（未存在の場合）
        
        Returns:
            成功時 True
        """
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # 既存カラムを確認
            cursor.execute("PRAGMA table_info(daily_hall_summary)")
            existing_columns = {row[1] for row in cursor.fetchall()}
            
            # 追加すべきカラム
            columns_to_add = [
                'day_of_week',
                'last_digit',
                'weekday_nth',
                'is_strong_zorome',
                'is_zorome',
                'is_month_start',
                'is_month_end',
                'is_weekend',
                'is_holiday',
                'hall_anniversary',
                'is_x_day',
                'week_of_month',
                'is_any_event'
            ]
            
            # 不足しているカラムを追加
            for col in columns_to_add:
                if col not in existing_columns:
                    if col in ['day_of_week', 'weekday_nth']:
                        cursor.execute(f"ALTER TABLE daily_hall_summary ADD COLUMN {col} TEXT")
                    elif col in ['last_digit', 'week_of_month']:
                        cursor.execute(f"ALTER TABLE daily_hall_summary ADD COLUMN {col} INTEGER")
                    else:  # boolean フラグ
                        cursor.execute(f"ALTER TABLE daily_hall_summary ADD COLUMN {col} INTEGER DEFAULT 0")
            
            conn.commit()
            conn.close()
            return True
        
        except Exception as e:
            raise Exception(f"カラム追加エラー: {e}")
    
    def update_date_info(self, date_str: str) -> bool:
        """
        指定日の日付情報を計算して daily_hall_summary に追加・更新
        
        Args:
            date_str: 日付（YYYYMMDD）
        
        Returns:
            成功時 True
        """
        try:
            # 日付情報を計算
            date_info = self.calculate_date_info(date_str)
            
            # DB に追加・更新
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # 日付がテーブルに存在するか確認
            cursor.execute("SELECT 1 FROM daily_hall_summary WHERE date = ?", (date_str,))
            exists = cursor.fetchone() is not None
            
            if exists:
                # UPDATE: 既存日付の場合は日付情報を上書き
                update_sql = """
                UPDATE daily_hall_summary
                SET day_of_week = ?,
                    last_digit = ?,
                    weekday_nth = ?,
                    is_strong_zorome = ?,
                    is_zorome = ?,
                    is_month_start = ?,
                    is_month_end = ?,
                    is_weekend = ?,
                    is_holiday = ?,
                    hall_anniversary = ?,
                    is_x_day = ?,
                    week_of_month = ?,
                    is_any_event = ?
                WHERE date = ?
                """
                
                cursor.execute(update_sql, (
                    date_info['day_of_week'],
                    date_info['last_digit'],
                    date_info['weekday_nth'],
                    date_info['is_strong_zorome'],
                    date_info['is_zorome'],
                    date_info['is_month_start'],
                    date_info['is_month_end'],
                    date_info['is_weekend'],
                    date_info['is_holiday'],
                    date_info['hall_anniversary'],
                    date_info['is_x_day'],
                    date_info['week_of_month'],
                    date_info['is_any_event'],
                    date_str
                ))
            else:
                # INSERT: 新規日付の場合は日付情報のみで行を作成
                # （他のカラムは daily_hall_summary で別途計算される）
                insert_sql = """
                INSERT OR IGNORE INTO daily_hall_summary
                (date, day_of_week, last_digit, weekday_nth, is_strong_zorome, is_zorome,
                 is_month_start, is_month_end, is_weekend, is_holiday,
                 hall_anniversary, is_x_day, week_of_month, is_any_event)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """
                
                cursor.execute(insert_sql, (
                    date_str,
                    date_info['day_of_week'],
                    date_info['last_digit'],
                    date_info['weekday_nth'],
                    date_info['is_strong_zorome'],
                    date_info['is_zorome'],
                    date_info['is_month_start'],
                    date_info['is_month_end'],
                    date_info['is_weekend'],
                    date_info['is_holiday'],
                    date_info['hall_anniversary'],
                    date_info['is_x_day'],
                    date_info['week_of_month'],
                    date_info['is_any_event']
                ))
            
            conn.commit()
            conn.close()
            return True
        
        except Exception as e:
            raise Exception(f"日付情報更新エラー ({date_str}): {e}")
    
    def process_date_list(self, date_list: list) -> dict:
        """
        複数の日付を処理
        
        Args:
            date_list: YYYYMMDD の日付リスト
        
        Returns:
            処理結果の辞書
        """
        results = {
            'processed': 0,
            'failed': 0,
            'errors': []
        }
        
        for date_str in date_list:
            try:
                self.update_date_info(date_str)
                results['processed'] += 1
            except Exception as e:
                results['failed'] += 1
                results['errors'].append({'date': date_str, 'error': str(e)})
        
        return results


def initialize_date_info_for_hall(hall_name: str, db_path: str = None) -> dict:
    """
    ホール DB の日付情報セットアップ（外部呼び出し用）
    
    Args:
        hall_name: ホール名
        db_path: DB パス（省略時はデフォルト）
    
    Returns:
        初期化結果の辞書
    """
    try:
        calculator = DateInfoCalculator(hall_name, db_path)
        
        # 設定を検証
        calculator._validate_config()
        
        # カラムを追加
        calculator.add_date_info_columns()
        
        return {
            'status': 'success',
            'message': f'{hall_name} の日付情報セットアップが完了しました',
            'hall_name': hall_name,
            'db_path': calculator.db_path
        }
    
    except Exception as e:
        return {
            'status': 'error',
            'message': str(e),
            'hall_name': hall_name
        }


def update_date_info_for_new_dates(hall_name: str, date_list: list, db_path: str = None) -> dict:
    """
    新規日付に対して日付情報を追加（外部呼び出し用）
    
    Args:
        hall_name: ホール名
        date_list: YYYYMMDD リスト
        db_path: DB パス（省略時はデフォルト）
    
    Returns:
        処理結果の辞書
    """
    try:
        calculator = DateInfoCalculator(hall_name, db_path)
        
        # 設定を検証
        calculator._validate_config()
        
        # カラムを追加（念のため）
        calculator.add_date_info_columns()
        
        # 日付情報を処理
        results = calculator.process_date_list(date_list)
        
        return {
            'status': 'success' if results['failed'] == 0 else 'partial',
            'message': f'{results["processed"]}件を処理しました',
            'hall_name': hall_name,
            'processed': results['processed'],
            'failed': results['failed'],
            'errors': results['errors']
        }
    
    except Exception as e:
        return {
            'status': 'error',
            'message': str(e),
            'hall_name': hall_name,
            'processed': 0,
            'failed': 0
        }


def main():
    """テスト用メイン処理"""
    if len(sys.argv) < 2:
        print("使用方法: python date_info_calculator.py <ホール名> [<YYYYMMDD> ...]")
        print("例: python date_info_calculator.py マルハンメガシティ柏 20250101 20250102")
        return 1
    
    hall_name = sys.argv[1]
    date_list = sys.argv[2:] if len(sys.argv) > 2 else []
    
    print(f"ホール: {hall_name}")
    print(f"対象日付: {date_list if date_list else '（初期化のみ）'}")
    print()
    
    # 初期化
    init_result = initialize_date_info_for_hall(hall_name)
    print(f"初期化: {init_result['status']}")
    if init_result['status'] != 'success':
        print(f"  エラー: {init_result['message']}")
        return 1
    
    # 日付情報を処理
    if date_list:
        result = update_date_info_for_new_dates(hall_name, date_list)
        print(f"処理: {result['status']}")
        print(f"  処理済み: {result['processed']}件")
        print(f"  失敗: {result['failed']}件")
        
        if result['errors']:
            print(f"  エラー詳細:")
            for error in result['errors']:
                print(f"    {error['date']}: {error['error']}")
    
    return 0


if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code)
