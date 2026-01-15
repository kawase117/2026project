#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
複数ホール対応版 パチスロデータスクレイピング
hall_config.json から複数ホールを一括処理
2025年全体テスト対応版（メモリ最適化とCSVレポート機能付き）
"""

import asyncio
import nodriver as uc
from datetime import datetime, timedelta
import os
import json
import sqlite3
import csv
import gc
from bs4 import BeautifulSoup
import urllib.parse


def extract_hall_name_from_url(url):
    """
    URL から hall_name を抽出
    パターン: https://ana-slo.com/YYYY-MM-DD-{hall_name_encoded}-data/
    
    戻り値: デコード済みの hall_name、または None
    """
    
    try:
        # URL から -data/ までの部分を抽出
        if '-data/' not in url:
            return None
        
        # "-data/" の前の部分を抽出
        before_data = url.split('-data/')[0]  # "https://...YYYY-MM-DD-hall_name_encoded"
        
        # 最後の "/" 以降を取得
        last_part = before_data.split('/')[-1]  # "YYYY-MM-DD-hall_name_encoded"
        
        if not last_part:
            return None
        
        # "YYYY-MM-DD-" を除去
        # 最初の3つの "-" の後ろ（日付）を除去
        parts = last_part.split('-')
        
        # parts = ['YYYY', 'MM', 'DD', 'hall', 'name', 'encoded', ...]
        # 最初の3つ（日付）を除いて残りを結合
        if len(parts) <= 3:
            return None
        
        hall_name_encoded = '-'.join(parts[3:])
        
        # URLデコード
        hall_name = urllib.parse.unquote(hall_name_encoded)
        
        if hall_name:
            print(f"   ✅ URL から hall_name 抽出: '{hall_name}'")
            return hall_name
        
        return None
        
    except Exception as e:
        print(f"   ❌ URL解析エラー: {e}")
        return None


def normalize_hall_name(hall_name):
    """
    ホール名を正規化（URL 用）
    スペース → ハイフン、スラッシュ → ハイフン
    
    例: "ザ シティ/ベルシティ雑色店" → "ザ-シティ-ベルシティ雑色店"
    """
    if not hall_name:
        return None
    
    # スペースをハイフンに変換
    normalized = hall_name.replace(' ', '-')
    # スラッシュをハイフンに変換
    normalized = normalized.replace('/', '-')
    
    print(f"   🔄 ホール名正規化: '{hall_name}' → '{normalized}'")
    return normalized


async def find_and_click_link_hybrid(page, target_url, date_str):
    """ハイブリッド方式：HTML解析 + JavaScript遷移
    
    戻り値: (success: bool, reason: str or None)
    """
    
    print(f"   🔍 HTML解析でリンク検索...")
    
    try:
        # HTML取得
        html_content = await page.get_content()
        soup = BeautifulSoup(html_content, 'html.parser')
        
        # 日付変換
        slash_date = date_str[:4] + "/" + date_str[4:6] + "/" + date_str[6:8]
        
        # ページ内にテキストが存在するか確認
        page_text = soup.get_text()
        
        if slash_date in page_text:
            print(f"   ✅ ページ内に '{slash_date}' を発見")
            print(f"   🌐 JavaScript遷移で目標URLへ: {target_url}")
            
            # JavaScript遷移
            try:
                await page.evaluate(f'window.location.href = "{target_url}"')
                await asyncio.sleep(5)
                
                # 遷移成功確認
                current_html = await page.get_content()
                if 'data' in current_html or '全データ一覧' in current_html:
                    print(f"   ✅ 遷移成功")
                    return True, None
                else:
                    reason = 'データページの内容が見つかりません'
                    print(f"   ❌ 遷移失敗 - {reason}")
                    return False, reason
                    
            except Exception as e:
                reason = f'JavaScript遷移エラー: {e}'
                print(f"   ❌ {reason}")
                return False, reason
                
        else:
            reason = f"ページ内に '{slash_date}' が見つかりません（データなし）"
            print(f"   ❌ {reason}")
            print(f"   🔍 この日付のデータは存在しない可能性があります")
        
        return False, reason
        
    except Exception as e:
        reason = f'リンク検索エラー: {e}'
        print(f"   ❌ {reason}")
        return False, reason


async def return_to_list_page_hybrid(page, list_url):
    """ハイブリッド方式：JavaScript遷移で一覧ページに戻る"""
    
    print(f"   ⬅️ 一覧ページに戻る...")
    
    try:
        print(f"   🌐 JavaScript遷移で一覧ページに移動: {list_url}")
        await page.evaluate(f'window.location.href = "{list_url}"')
        await asyncio.sleep(8)
        
        # 移動確認
        html_content = await page.get_content()
        if 'データ一覧' in html_content:
            print(f"   ✅ 一覧ページに移動成功")
        else:
            print(f"   ⚠️ 一覧ページかどうか確認できません")
        
        # 広告処理（自動のみ）
        await manual_ad_step(page, "一覧ページ復帰", auto_only=True)
        
        # ページ安定化
        await asyncio.sleep(10)
        
    except Exception as e:
        print(f"   ❌ 一覧ページ移動エラー: {e}")
        raise


async def get_hall_name_from_html(page):
    """HTML直接解析でホール名取得（正規化済み）"""
    
    try:
        print("   📄 HTML取得中...")
        html_content = await page.get_content()
        print(f"   ✅ HTML取得: {len(html_content):,} 文字")
        
        soup = BeautifulSoup(html_content, 'html.parser')
        
        # 複数の方法でホール名を試行
        print("   🔍 ホール名検索中...")
        
        raw_hall_name = None
        
        # 方法1: #st-page h1
        st_page = soup.find(id='st-page')
        if st_page:
            h1 = st_page.find('h1')
            if h1:
                raw_hall_name = h1.get_text().replace('データ一覧', '').strip()
                if raw_hall_name:
                    print(f"   ✅ #st-page h1で発見: '{raw_hall_name}'")
        
        # 方法2: 全H1要素から検索
        if not raw_hall_name:
            h1_elements = soup.find_all('h1')
            for h1 in h1_elements:
                text = h1.get_text().strip()
                if 'データ一覧' in text:
                    raw_hall_name = text.replace('データ一覧', '').strip()
                    if raw_hall_name:
                        print(f"   ✅ H1要素で発見: '{raw_hall_name}'")
                        break
        
        # 方法3: ページタイトルから抽出
        if not raw_hall_name:
            title_tag = soup.find('title')
            if title_tag:
                title_text = title_tag.get_text()
                if 'データ一覧' in title_text:
                    raw_hall_name = title_text.replace('データ一覧', '').replace('- アナスロ', '').strip()
                    if raw_hall_name:
                        print(f"   ✅ ページタイトルで発見: '{raw_hall_name}'")
        
        if not raw_hall_name:
            print("   ❌ どの方法でもホール名を発見できませんでした")
            return None
        
        # ホール名を正規化
        normalized_hall_name = normalize_hall_name(raw_hall_name)
        return normalized_hall_name
        
    except Exception as e:
        print(f"   ❌ HTML解析エラー: {e}")
        import traceback
        traceback.print_exc()
        return None


async def process_target_page_html(page, date_str, hall_name, save_dir):
    """HTML解析でターゲットページを処理"""
    
    try:
        # 広告処理
        await manual_ad_step(page, f"{date_str}詳細ページ", auto_only=True)
        await asyncio.sleep(10)
        
        # HTML取得
        print(f"   📄 HTML取得中...")
        html_content = await page.get_content()
        print(f"   ✅ HTML取得: {len(html_content):,} 文字")
        
        # BeautifulSoupで解析
        soup = BeautifulSoup(html_content, 'html.parser')
        
        print(f"   🔍 データ抽出...")
        
        # データ格納用辞書
        extracted_data = {
            'date': date_str,
            'hall_name': hall_name,
            'all_data': [],
            'last_digit_data': [],
            'url': html_content[:200] if html_content else ''
        }
        
        # 1. 全データ一覧テーブルを取得
        print(f"      📋 全データ一覧テーブル検索...")
        
        # ID で直接取得（レイアウト変化に対応）
        all_data_table = soup.find(id="all_data_table")
        
        if all_data_table:
            # <thead> と <tbody> を区別して処理
            thead = all_data_table.find('thead')
            tbody = all_data_table.find('tbody')
            
            # ヘッダー行を取得
            header = None
            if thead:
                # <thead> がある場合
                header_row = thead.find('tr')
                if header_row:
                    header = [cell.get_text().strip() for cell in header_row.find_all(['th', 'td'])]
                    print(f"         ℹ️ <thead> からヘッダー取得")
            
            # <thead> がない場合は最初の <tr> をヘッダーと見なす
            if not header and tbody:
                first_row = tbody.find('tr')
                if first_row:
                    header = [cell.get_text().strip() for cell in first_row.find_all(['th', 'td'])]
                    print(f"         ℹ️ <tbody> 最初の行をヘッダーと見なす")
            
            if header:
                print(f"         ✅ ヘッダー検出: {header}")
                
                # データ行を処理
                if tbody:
                    rows = tbody.find_all('tr')
                    # <thead> がない場合は最初の行をスキップ
                    start_idx = 0 if thead else 1
                    
                    for row in rows[start_idx:]:
                        cells = [cell.get_text().strip() for cell in row.find_all(['td', 'th'])]
                        if len(cells) >= len(header):
                            row_data = dict(zip(header, cells))
                            extracted_data['all_data'].append(row_data)
                    
                    print(f"         ✅ 全データ: {len(extracted_data['all_data'])}件抽出")
            else:
                print(f"         ⚠️ ヘッダー行が見つかりません")
        else:
            print(f"         ❌ 全データ一覧テーブルが見つかりません")
        
        # 2. 末尾別集計データを取得
        print(f"      📊 末尾別集計テーブル検索...")
        last_digit_table = soup.find(id="last_digit_data_table")
        
        if last_digit_table:
            print(f"         ✅ 末尾別集計テーブル発見！")
            
            # テーブル要素を確認
            if last_digit_table.name == 'table':
                table = last_digit_table
            else:
                table = last_digit_table.find('table')
            
            if table:
                # <thead> と <tbody> を区別して処理
                thead = table.find('thead')
                tbody = table.find('tbody')
                
                # ヘッダー行を取得
                header = None
                if thead:
                    # <thead> がある場合
                    header_row = thead.find('tr')
                    if header_row:
                        header = [cell.get_text().strip() for cell in header_row.find_all(['th', 'td'])]
                        print(f"         ℹ️ <thead> からヘッダー取得")
                
                # <thead> がない場合は最初の <tr> をヘッダーと見なす
                if not header and tbody:
                    first_row = tbody.find('tr')
                    if first_row:
                        header = [cell.get_text().strip() for cell in first_row.find_all(['th', 'td'])]
                        print(f"         ℹ️ <tbody> 最初の行をヘッダーと見なす")
                
                if header:
                    print(f"         ℹ️ ヘッダー: {header}")
                    
                    # データ行を処理
                    if tbody:
                        rows = tbody.find_all('tr')
                        # <thead> がない場合は最初の行をスキップ
                        start_idx = 0 if thead else 1
                        
                        for row in rows[start_idx:]:
                            cells = [cell.get_text().strip() for cell in row.find_all(['td', 'th'])]
                            if len(cells) >= len(header):
                                row_data = dict(zip(header, cells))
                                extracted_data['last_digit_data'].append(row_data)
                        
                        print(f"         ✅ 末尾別データ: {len(extracted_data['last_digit_data'])}件抽出")
                else:
                    print(f"         ⚠️ ヘッダー行が見つかりません")
            else:
                print(f"         ❌ テーブル要素が見つかりません")
        else:
            print(f"         ❌ ID 'last_digit_data_table' の要素が見つかりません")
        
        # 3. JSONファイルとして保存
        json_filename = f"{date_str}_{hall_name}_data.json"
        json_filepath = os.path.join(save_dir, json_filename)
        
        with open(json_filepath, 'w', encoding='utf-8') as f:
            json.dump(extracted_data, f, ensure_ascii=False, indent=2)
        
        print(f"   💾 JSON保存: {json_filename}")
        
        # 抽出結果サマリー
        total_all_data = len(extracted_data['all_data'])
        total_last_digit = len(extracted_data['last_digit_data'])
        
        print(f"   📊 抽出サマリー:")
        print(f"      - 全データ: {total_all_data}件")
        print(f"      - 末尾別データ: {total_last_digit}件")
        
        # 成功判定
        success = total_all_data > 0
        
        if success:
            print(f"   ✅ データ抽出成功")
        else:
            print(f"   ❌ データ抽出失敗（全データが0件）")
        
        return success
        
    except Exception as e:
        print(f"   ❌ ページ処理エラー: {e}")
        import traceback
        traceback.print_exc()
        return False


async def manual_ad_step(page, page_type, auto_only=False):
    """広告処理ステップ"""
    
    try:
        # 簡単な自動クローズ試行
        await try_auto_close(page)
        
        if not auto_only:
            print(f"   📢 {page_type}で広告がある場合は手動で閉じてください")
            input("   広告処理完了後、Enterを押してください: ")
        else:
            await asyncio.sleep(3)
            
    except Exception as e:
        print(f"   ⚠️ 広告処理エラー: {e}")


async def try_auto_close(page):
    """自動クローズ試行"""
    try:
        await asyncio.sleep(1)
    except:
        pass


def generate_date_list(start_date_str, end_date_str):
    """日付リスト生成"""
    
    start_date = datetime.strptime(start_date_str, "%Y%m%d")
    end_date = datetime.strptime(end_date_str, "%Y%m%d")
    
    date_list = []
    current_date = start_date
    
    while current_date <= end_date:
        date_list.append(current_date.strftime("%Y%m%d"))
        current_date += timedelta(days=1)
    
    return date_list


def generate_target_url(date_str, hall_name):
    """目標URL生成"""
    
    # YYYYMMDD → YYYY-MM-DD 変換
    year = date_str[:4]
    month = date_str[4:6]
    day = date_str[6:8]
    formatted_date = f"{year}-{month}-{day}"
    
    # ホール名をURLエンコード（小文字）
    hall_encoded = urllib.parse.quote(hall_name, safe='').lower()
    
    return f"https://ana-slo.com/{formatted_date}-{hall_encoded}-data/"


async def save_to_database(extracted_data, db_path="pachinko_data.db"):
    """データベース保存"""
    
    try:
        print(f"   💾 データベース保存開始...")
        
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # テーブル作成
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS hall_daily_data (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT NOT NULL,
                hall_name TEXT NOT NULL,
                url TEXT,
                all_data_count INTEGER,
                last_digit_data_count INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(date, hall_name)
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS machine_data (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT NOT NULL,
                hall_name TEXT NOT NULL,
                machine_name TEXT,
                machine_number TEXT,
                games INTEGER,
                diff_coins INTEGER,
                bb_count INTEGER,
                rb_count INTEGER,
                total_probability TEXT,
                bb_probability TEXT,
                rb_probability TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS last_digit_summary (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT NOT NULL,
                hall_name TEXT NOT NULL,
                last_digit TEXT,
                machine_count INTEGER,
                total_games INTEGER,
                total_diff_coins INTEGER,
                avg_games REAL,
                avg_diff_coins REAL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # 日次サマリーデータ保存
        cursor.execute('''
            INSERT OR REPLACE INTO hall_daily_data 
            (date, hall_name, url, all_data_count, last_digit_data_count)
            VALUES (?, ?, ?, ?, ?)
        ''', (
            extracted_data['date'],
            extracted_data['hall_name'], 
            extracted_data['url'],
            len(extracted_data['all_data']),
            len(extracted_data['last_digit_data'])
        ))
        
        # 全データ保存
        for machine in extracted_data['all_data']:
            def safe_int(value):
                try:
                    return int(str(value).replace(',', '').replace('+', '').replace('-', ''))
                except:
                    return None
            
            cursor.execute('''
                INSERT INTO machine_data 
                (date, hall_name, machine_name, machine_number, games, diff_coins, 
                 bb_count, rb_count, total_probability, bb_probability, rb_probability)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                extracted_data['date'],
                extracted_data['hall_name'],
                machine.get('機種名', ''),
                machine.get('台番号', ''),
                safe_int(machine.get('G数', 0)),
                safe_int(machine.get('差枚', 0)),
                safe_int(machine.get('BB', 0)),
                safe_int(machine.get('RB', 0)),
                machine.get('合成確率', ''),
                machine.get('BB確率', ''),
                machine.get('RB確率', '')
            ))
        
        # 末尾別データ保存
        for last_digit in extracted_data['last_digit_data']:
            def safe_float(value):
                try:
                    return float(str(value).replace(',', ''))
                except:
                    return None
            
            cursor.execute('''
                INSERT INTO last_digit_summary 
                (date, hall_name, last_digit, machine_count, total_games, 
                 total_diff_coins, avg_games, avg_diff_coins)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                extracted_data['date'],
                extracted_data['hall_name'],
                last_digit.get('末尾', last_digit.get('last_digit', '')),
                safe_int(last_digit.get('台数', last_digit.get('count', 0))),
                safe_int(last_digit.get('総G数', last_digit.get('total_games', 0))),
                safe_int(last_digit.get('総差枚', last_digit.get('total_diff', 0))),
                safe_float(last_digit.get('平均G数', last_digit.get('avg_games', 0))),
                safe_float(last_digit.get('平均差枚', last_digit.get('avg_diff', 0)))
            ))
        
        conn.commit()
        
        print(f"   ✅ データベース保存完了: {db_path}")
        print(f"      - 全データ: {len(extracted_data['all_data'])}件")
        print(f"      - 末尾別データ: {len(extracted_data['last_digit_data'])}件")
        
        conn.close()
        return True
        
    except Exception as e:
        print(f"   ❌ データベース保存エラー: {e}")
        import traceback
        traceback.print_exc()
        return False


def optimize_memory(iteration, clear_interval=50):
    """メモリ最適化関数
    
    定期的なガベージコレクションと待機時間の調整
    
    Args:
        iteration: 現在の反復回数
        clear_interval: クリア間隔（デフォルト50日ごと）
    """
    
    if iteration % clear_interval == 0 and iteration > 0:
        print(f"\n   🧹 メモリ最適化中... ({iteration}日処理済み)")
        gc.collect()
        import time
        time.sleep(5)
        print(f"   ✅ メモリ最適化完了")


def export_failed_dates_to_csv(hall_results, output_dir="data"):
    """失敗日のみを集計したCSVレポート作成
    
    CSVの構成:
    - ホール名
    - 失敗日付（YYYY-MM-DD形式）
    - 失敗理由
    """
    
    try:
        output_path = os.path.join(output_dir, "failed_dates_report.csv")
        
        # 失敗日を集計
        failed_records = []
        
        for hall_name, result in hall_results.items():
            if 'detailed_log' in result and 'dates' in result['detailed_log']:
                for date_info in result['detailed_log']['dates']:
                    if date_info['status'] == 'failed':
                        # 日付フォーマット: YYYYMMDD → YYYY-MM-DD
                        date_str = date_info['date']
                        formatted_date = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}"
                        
                        failed_records.append({
                            'hall_name': hall_name,
                            'date': formatted_date,
                            'reason': date_info.get('reason', '不明')
                        })
        
        # CSVに出力
        if failed_records:
            with open(output_path, 'w', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(f, fieldnames=['hall_name', 'date', 'reason'])
                writer.writeheader()
                writer.writerows(failed_records)
            
            print(f"\n📈 失敗日レポートを出力: {output_path}")
            print(f"   失敗件数: {len(failed_records)}件")
            
            # 失敗理由の集計
            reason_count = {}
            for record in failed_records:
                reason = record['reason']
                reason_count[reason] = reason_count.get(reason, 0) + 1
            
            print(f"\n   失敗理由の内訳:")
            for reason, count in sorted(reason_count.items(), key=lambda x: x[1], reverse=True):
                print(f"      - {reason}: {count}件")
            
            return output_path
        else:
            print(f"\n✅ 失敗日がありません（全て成功）")
            return None
            
    except Exception as e:
        print(f"\n❌ CSVエクスポートエラー: {e}")
        return None


def print_summary(success_dates, failed_dates, hall_name):
    """結果サマリー出力"""
    
    print(f"\n" + "="*70)
    print(f"📊 取得結果サマリー - {hall_name}")
    print("="*70)
    
    print(f"✅ 成功: {len(success_dates)}件")
    if success_dates:
        success_formatted = [f"{d[4:6]}/{d[6:8]}" for d in success_dates]
        print(f"   {', '.join(success_formatted)}")
    
    print(f"\n❌ 失敗: {len(failed_dates)}件")
    if failed_dates:
        failed_formatted = [f"{d[4:6]}/{d[6:8]}" for d in failed_dates]
        print(f"   {', '.join(failed_formatted)} が取得できませんでした")
    
    total = len(success_dates) + len(failed_dates)
    if total > 0:
        success_rate = (len(success_dates) / total) * 100
        print(f"\n📈 成功率: {success_rate:.1f}% ({len(success_dates)}/{total})")
    
    print("="*70)


async def date_range_scrape_hybrid(start_date_str, end_date_str, list_url, page=None):
    """ハイブリッド版スクレイピング（既存ページを使用可能）
    
    戻り値: (success_count, failed_count, page, detailed_log)
    detailed_log: {
        'hall_name': str,
        'status': 'success' | 'error',
        'error_message': str or None,
        'dates': [
            {'date': str, 'status': 'success' | 'failed', 'reason': str or None}
        ]
    }
    """
    
    browser = None
    own_page = False
    detailed_log = {
        'hall_name': None,
        'status': 'error',
        'error_message': None,
        'dates': []
    }
    
    try:
        print(f"🎯 ハイブリッド版スクレイピング: {start_date_str} ～ {end_date_str}")
        print(f"🌐 対象URL: {list_url}")
        print("="*70)
        
        # ページが渡されていない場合はブラウザを起動
        if page is None:
            browser = await uc.start(headless=False)
            own_page = True
            
            # 一覧ページアクセス
            print("📄 一覧ページにアクセス中...")
            page = await browser.get(list_url)
            
            # 十分な待機時間
            print("⏳ ページ読み込み待機（15秒）...")
            await asyncio.sleep(15)
        else:
            print("📄 既存ページを使用して処理開始...")
        
        # 初回：一覧ページから HTML で hall_name を取得
        print("🏢 HTML解析でホール名取得中...")
        hall_name = await get_hall_name_from_html(page)
        
        if not hall_name:
            print("❌ ホール名の取得に失敗しました。")
            detailed_log['status'] = 'error'
            detailed_log['error_message'] = 'ホール名取得失敗'
            return 0, 0, page, detailed_log
            
        print(f"✅ ホール名検出: {hall_name}")
        detailed_log['hall_name'] = hall_name
        print("="*70)
        
        # 日付リストを生成
        date_list = generate_date_list(start_date_str, end_date_str)
        print(f"📅 対象日付: {len(date_list)}日間")
        for date in date_list:
            print(f"   {date}")
        print()
        
        # 結果記録用
        success_dates = []
        failed_dates = []
        consecutive_failures = 0
        MAX_CONSECUTIVE_FAILURES = 3
        
        # ホール別保存ディレクトリ作成
        script_dir = os.path.dirname(os.path.abspath(__file__))
        project_root = os.path.dirname(script_dir)
        base_save_dir = os.path.join(project_root, "data")
        hall_save_dir = os.path.join(base_save_dir, hall_name)
        os.makedirs(hall_save_dir, exist_ok=True)
        print(f"💾 保存先: {hall_save_dir}/")
        print(f"🗄️ データベース: pachinko_data.db")
        print()
        
        # 初回広告処理（最初のホールのみ）
        if own_page:
            print("\n🚫 初回広告処理:")
            await manual_ad_step(page, "一覧ページ初回")
            
            print("\n⏳ ページ安定化待機（10秒）...")
            await asyncio.sleep(10)
        
        print(f"\n📄 日付別データ取得開始...")
        print("="*50)
        
        # 日付ループ
        for i, date_str in enumerate(date_list, 1):
            print(f"\n📅 [{i}/{len(date_list)}] {date_str} の処理開始")
            print("-" * 40)
            
            try:
                # 目標URLを生成
                target_url = generate_target_url(date_str, hall_name)
                print(f"   🎯 目標URL: {target_url}")
                
                # ハイブリッド方式でリンクを探してクリック
                click_success, click_reason = await find_and_click_link_hybrid(page, target_url, date_str)
                
                if not click_success:
                    print(f"   ❌ {date_str}: リンククリックに失敗しました")
                    failed_dates.append(date_str)
                    detailed_log['dates'].append({
                        'date': date_str,
                        'status': 'failed',
                        'reason': click_reason or 'リンククリック失敗'
                    })
                    consecutive_failures += 1
                    
                    if consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                        print(f"\n🚨 連続失敗回数が{MAX_CONSECUTIVE_FAILURES}回に達しました。処理を中断します。")
                        break
                    
                    continue
                
                # ページ遷移後の処理
                print(f"   🌐 ページ遷移完了")
                
                # 詳細ページから URL で hall_name を検証・更新
                detail_url = await page.evaluate('window.location.href')
                extracted_hall_name = extract_hall_name_from_url(detail_url)
                if extracted_hall_name:
                    if extracted_hall_name != hall_name:
                        print(f"   ⚠️ ホール名を更新: '{hall_name}' → '{extracted_hall_name}'")
                        hall_name = extracted_hall_name
                        detailed_log['hall_name'] = hall_name
                        # ディレクトリも更新
                        hall_save_dir = os.path.join(base_save_dir, hall_name)
                        os.makedirs(hall_save_dir, exist_ok=True)
                    else:
                        print(f"   ✅ ホール名確認: '{hall_name}'")
                
                success = await process_target_page_html(page, date_str, hall_name, hall_save_dir)
                
                if success:
                    # JSONファイルからデータを読み込んでデータベースに保存
                    json_filepath = os.path.join(hall_save_dir, f"{date_str}_{hall_name}_data.json")
                    if os.path.exists(json_filepath):
                        with open(json_filepath, 'r', encoding='utf-8') as f:
                            extracted_data = json.load(f)
                        
                        # データベース保存
                        db_success = await save_to_database(extracted_data)
                        
                        if db_success:
                            print(f"   ✅ {date_str}: 取得・保存成功")
                            success_dates.append(date_str)
                            detailed_log['dates'].append({
                                'date': date_str,
                                'status': 'success',
                                'reason': None
                            })
                            consecutive_failures = 0
                        else:
                            print(f"   ⚠️ {date_str}: 取得成功、DB保存失敗")
                            success_dates.append(date_str)
                            detailed_log['dates'].append({
                                'date': date_str,
                                'status': 'success',
                                'reason': 'DB保存失敗（JSONは取得済み）'
                            })
                            consecutive_failures = 0
                    else:
                        print(f"   ❌ {date_str}: JSONファイルが見つかりません")
                        failed_dates.append(date_str)
                        detailed_log['dates'].append({
                            'date': date_str,
                            'status': 'failed',
                            'reason': 'JSONファイル未検出'
                        })
                        consecutive_failures += 1
                else:
                    print(f"   ❌ {date_str}: データ抽出失敗")
                    failed_dates.append(date_str)
                    detailed_log['dates'].append({
                        'date': date_str,
                        'status': 'failed',
                        'reason': 'データ抽出失敗'
                    })
                    consecutive_failures += 1
                    
                    if consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                        print(f"\n🚨 連続失敗回数が{MAX_CONSECUTIVE_FAILURES}回に達しました。処理を中断します。")
                        break
                
                # 一覧ページに戻る（最後の日付以外）
                if i < len(date_list):
                    await return_to_list_page_hybrid(page, list_url)
                
                # メモリ最適化（50日ごと）
                optimize_memory(i, clear_interval=50)
                
            except Exception as e:
                print(f"   ❌ {date_str}: エラー - {e}")
                failed_dates.append(date_str)
                detailed_log['dates'].append({
                    'date': date_str,
                    'status': 'failed',
                    'reason': f'例外エラー: {str(e)}'
                })
                consecutive_failures += 1
                
                if consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                    print(f"\n🚨 連続失敗回数が{MAX_CONSECUTIVE_FAILURES}回に達しました。処理を中断します。")
                    break
                
                # エラー時も一覧ページに戻る（最後の日付以外）
                if i < len(date_list):
                    try:
                        await return_to_list_page_hybrid(page, list_url)
                    except:
                        pass
        
        # 結果サマリー
        print_summary(success_dates, failed_dates, hall_name)
        
        # 詳細ログを完成させる
        detailed_log['status'] = 'success'
        
        # ページを返す（複数ホール処理で再利用）
        return len(success_dates), len(failed_dates), page, detailed_log
        
    except Exception as e:
        print(f"❌ 全体エラー: {e}")
        detailed_log['error_message'] = str(e)
        return 0, 0, None, detailed_log
    finally:
        # 自分でブラウザを起動した場合のみ終了処理を後回し
        # 複数ホール処理の場合はページを保持
        pass


def load_hall_config(config_filename="hall_config.json"):
    """hall_config.json からアクティブなホール設定を読み込み（scraper/ から ../config/ を参照）"""
    try:
        # スクリプトと同じディレクトリのパスを取得
        script_dir = os.path.dirname(os.path.abspath(__file__))
        project_root = os.path.dirname(script_dir)
        config_path = os.path.join(project_root, "config", config_filename)
        
        with open(config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)
        
        active_halls = [hall for hall in config['halls'] if hall.get('active', True)]
        
        if not active_halls:
            print("❌ アクティブなホール設定が見つかりません")
            return []
        
        print(f"✅ {len(active_halls)}個のホール設定を読み込みました")
        return active_halls
        
    except FileNotFoundError:
        script_dir = os.path.dirname(os.path.abspath(__file__))
        project_root = os.path.dirname(script_dir)
        config_path = os.path.join(project_root, "config", config_filename)
        print(f"❌ 設定ファイルが見つかりません: {config_path}")
        return []
    except json.JSONDecodeError:
        print(f"❌ 設定ファイルの形式が不正です")
        return []
    except Exception as e:
        print(f"❌ 設定ファイル読み込みエラー: {str(e)}")
        return []


async def main():
    """マルチホール版メイン処理 - ブラウザを共有"""
    
    # ログファイル初期化
    script_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(script_dir)
    log_file = os.path.join(project_root, "data", "scraping_log.txt")
    os.makedirs(os.path.dirname(log_file), exist_ok=True)
    log_buffer = []
    
    def log_message(msg):
        """ログをメモリに格納（後で一括保存）"""
        log_buffer.append(msg)
        print(msg)
    
    print("🚀 複数ホール対応スクレイピング開始")
    print("=" * 80)
    print()
    
    # hall_config.json からホール設定を読み込み
    halls = load_hall_config()
    
    if not halls:
        print("❌ スクレイピングを開始できません")
        return
    
    # ===== 日付範囲（ここで変更） =====
    start_date = "20250303"
    end_date = "20250303"
    # ===================================
    
    print(f"📅 対象期間: {start_date} ～ {end_date}")
    print(f"🏢 ホール数: {len(halls)}")
    print("=" * 80)
    print()
    
    # ブラウザを1回だけ起動
    browser = None
    shared_page = None
    
    try:
        # 全体の統計
        overall_success = 0
        overall_failed = 0
        hall_results = {}
        
        # 各ホールを順番に処理
        for i, hall in enumerate(halls, 1):
            hall_name = hall['hall_name']
            scraper_url = hall['scraper_url']
            has_layout_csv = hall.get('has_layout_csv', False)
            
            print(f"\n{'=' * 80}")
            print(f"📍 [{i}/{len(halls)}] {hall_name} の処理開始")
            print(f"{'=' * 80}")
            print(f"🌐 URL: {scraper_url}")
            print(f"📋 台位置CSV: {'あり' if has_layout_csv else 'なし'}")
            print()
            
            try:
                # 最初のホールの場合はブラウザを起動
                if i == 1:
                    browser = await uc.start(headless=False)
                    shared_page = await browser.get(scraper_url)
                    print("⏳ ページ読み込み待機（15秒）...")
                    await asyncio.sleep(15)
                    
                    print("\n🚫 初回広告処理:")
                    from bs4 import BeautifulSoup
                    # ここで初回広告処理
                    print("   📢 広告がある場合は手動で閉じてください")
                    input("   広告処理完了後、Enterを押してください: ")
                    
                    print("\n⏳ ページ安定化待機（10秒）...")
                    await asyncio.sleep(10)
                else:
                    # 次のホールのURLに遷移
                    print("📄 次のホールへ遷移中...")
                    shared_page = await browser.get(scraper_url)
                    await asyncio.sleep(15)
                
                # date_range_scrape_hybrid() を呼び出し（ページを渡す）
                success_count, failed_count, shared_page, detailed_log = await date_range_scrape_hybrid(
                    start_date,
                    end_date,
                    scraper_url,
                    page=shared_page
                )
                
                # 統計を更新
                overall_success += success_count
                overall_failed += failed_count
                
                # detailed_log をログバッファに追加
                log_buffer.append(json.dumps(detailed_log, ensure_ascii=False, indent=2))
                
                hall_results[hall_name] = {
                    'status': '✅ 完了',
                    'success': success_count,
                    'failed': failed_count,
                    'has_csv': has_layout_csv,
                    'detailed_log': detailed_log
                }
                
                print(f"\n✅ {hall_name}: 成功 {success_count}件, 失敗 {failed_count}件")
                
            except Exception as e:
                print(f"\n❌ {hall_name}: エラーが発生しました")
                print(f"   エラー内容: {str(e)}")
                
                error_log = {
                    'hall_name': hall_name,
                    'status': 'error',
                    'error_message': str(e),
                    'dates': []
                }
                
                # エラーログをバッファに追加
                log_buffer.append(json.dumps(error_log, ensure_ascii=False, indent=2))
                
                hall_results[hall_name] = {
                    'status': f'❌ エラー',
                    'success': 0,
                    'failed': 0,
                    'has_csv': has_layout_csv,
                    'error': str(e),
                    'detailed_log': error_log
                }
                
                print(f"\n⏭️ 次のホール処理に進みます...")
                await asyncio.sleep(2)
        
        # 最終結果サマリーを表示
        print_final_summary(overall_success, overall_failed, hall_results)
        
        # 失敗日のCSVレポートをエクスポート
        export_failed_dates_to_csv(hall_results, output_dir=os.path.join(project_root, "data"))
        
        # ログファイルに保存
        try:
            # JSON形式で保存するために、log_bufferを解析して構造化する
            logs_json = {
                'session_start': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'date_range': f'{start_date} ～ {end_date}',
                'total_halls': len(halls),
                'overall_success': overall_success,
                'overall_failed': overall_failed,
                'halls': []
            }
            
            # hall_resultsから詳細ログを抽出
            for hall_name, result in hall_results.items():
                if 'detailed_log' in result:
                    logs_json['halls'].append(result['detailed_log'])
            
            with open(log_file, 'w', encoding='utf-8') as f:
                json.dump(logs_json, f, ensure_ascii=False, indent=2)
            print(f"\n💾 ログファイル保存: {log_file}")
        except Exception as e:
            print(f"\n⚠️ ログファイル保存エラー: {e}")
        
    finally:
        # 全ホール処理後に1回だけブラウザを終了
        if browser:
            print("\n📚 ブラウザを終了します...")
            await asyncio.sleep(10)
            try:
                browser.stop()
            except:
                pass


def print_final_summary(overall_success, overall_failed, hall_results):
    """最終結果サマリーを表示"""
    
    print("\n" + "=" * 80)
    print("📊 全ホール処理完了 - 最終結果")
    print("=" * 80)
    print()
    
    # 全体統計
    total_all = overall_success + overall_failed
    success_rate = (overall_success / total_all * 100) if total_all > 0 else 0
    
    print("🎯 全体統計:")
    print(f"   ✅ 総成功件数: {overall_success}件")
    print(f"   ❌ 総失敗件数: {overall_failed}件")
    print(f"   📈 全体成功率: {success_rate:.1f}% ({overall_success}/{total_all})")
    print()
    
    # ホール別結果
    print("🏢 ホール別処理結果:")
    print()
    
    for hall_name, result in hall_results.items():
        status = result['status']
        success = result['success']
        failed = result['failed']
        csv_status = "✅" if result['has_csv'] else "❌"
        
        if success > 0 or failed > 0:
            print(f"   {status}")
            print(f"      ホール名: {hall_name}")
            print(f"      結果: 成功 {success}件, 失敗 {failed}件")
            print(f"      台位置CSV: {csv_status}")
        else:
            print(f"   {status}")
            print(f"      ホール名: {hall_name}")
            if 'error' in result:
                print(f"      エラー: {result['error']}")
            print(f"      台位置CSV: {csv_status}")
        print()
    
    # 処理結果の統計
    print("📋 処理統計:")
    success_halls = [h for h in hall_results.keys() if '✅' in hall_results[h]['status']]
    error_halls = [h for h in hall_results.keys() if '❌' in hall_results[h]['status']]
    print(f"   正常完了ホール: {len(success_halls)}/{len(hall_results)}")
    print(f"   エラーホール: {len(error_halls)}/{len(hall_results)}")
    print()
    
    if error_halls:
        print("⚠️ エラーが発生したホール:")
        for hall_name in error_halls:
            print(f"      - {hall_name}")
        print()
    
    # 出力先情報
    print("💾 データ保存先:")
    print(f"   📁 JSONファイル: data/[ホール名]/[日付]_[ホール名]_data.json")
    print(f"   📄 失敗日レポート: data/failed_dates_report.csv")
    print(f"   🗄️ データベース: pachinko_data.db")
    print()
    
    # 実行時間
    print(f"⏰ 完了時刻: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 80)


if __name__ == "__main__":
    asyncio.run(main())