import asyncio
import nodriver as uc
from datetime import datetime, timedelta
import os
import json
import sqlite3
from bs4 import BeautifulSoup
import urllib.parse

async def find_and_click_link_hybrid(page, target_url, date_str):
    """ハイブリッド方式：HTML解析 + JavaScript遷移"""
    
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
            
            # JavaScript遷移（元のコードと同じ方式）
            try:
                # シンプルなJavaScript実行
                await page.evaluate(f'window.location.href = "{target_url}"')
                await asyncio.sleep(5)  # 遷移待機
                
                # 遷移成功確認（HTML解析）
                current_html = await page.get_content()
                if 'data' in current_html or '全データ一覧' in current_html:
                    print(f"   ✅ 遷移成功")
                    return True
                else:
                    print(f"   ❌ 遷移失敗 - データページの内容が見つかりません")
                    
            except Exception as e:
                print(f"   ❌ JavaScript遷移エラー: {e}")
                return False
                
        else:
            print(f"   ❌ ページ内に '{slash_date}' が見つかりません")
            print(f"   🔍 この日付のデータは存在しない可能性があります")
        
        return False
        
    except Exception as e:
        print(f"   ❌ リンク検索エラー: {e}")
        return False


async def return_to_list_page_hybrid(page, list_url):
    """ハイブリッド方式：JavaScript遷移で一覧ページに戻る"""
    
    print(f"   ⬅️ 一覧ページに戻る...")
    
    try:
        print(f"   🌐 JavaScript遷移で一覧ページに移動: {list_url}")
        # JavaScript遷移（元のコードと同じ方式）
        await page.evaluate(f'window.location.href = "{list_url}"')
        await asyncio.sleep(8)  # 移動待機
        
        # 移動確認（HTML解析）
        html_content = await page.get_content()
        if 'データ一覧' in html_content:
            print(f"   ✅ 一覧ページに移動成功")
        else:
            print(f"   ⚠️ 一覧ページかどうか確認できません")
        
        # 広告処理（自動のみ）
        await manual_ad_step(page, "一覧ページ復帰", auto_only=True)
        
        # ページ安定化のための最終待機
        await asyncio.sleep(10)
        
    except Exception as e:
        print(f"   ❌ 一覧ページ移動エラー: {e}")
        raise


async def get_hall_name_from_html(page):
    """HTML直接解析でホール名取得（元のまま）"""
    
    try:
        print("   📄 HTML取得中...")
        html_content = await page.get_content()
        print(f"   ✅ HTML取得: {len(html_content):,} 文字")
        
        soup = BeautifulSoup(html_content, 'html.parser')
        
        # 複数の方法でホール名を試行
        print("   🔍 ホール名検索中...")
        
        # 方法1: #st-page h1
        st_page = soup.find(id='st-page')
        if st_page:
            h1 = st_page.find('h1')
            if h1:
                hall_name = h1.get_text().replace('データ一覧', '').strip()
                if hall_name:
                    print(f"   ✅ #st-page h1で発見: '{hall_name}'")
                    return hall_name
        
        # 方法2: 全H1要素から検索
        h1_elements = soup.find_all('h1')
        for h1 in h1_elements:
            text = h1.get_text().strip()
            if 'データ一覧' in text:
                hall_name = text.replace('データ一覧', '').strip()
                if hall_name:
                    print(f"   ✅ H1要素で発見: '{hall_name}'")
                    return hall_name
        
        # 方法3: ページタイトルから抽出
        title_tag = soup.find('title')
        if title_tag:
            title_text = title_tag.get_text()
            if 'データ一覧' in title_text:
                hall_name = title_text.replace('データ一覧', '').replace('- アナスロ', '').strip()
                if hall_name:
                    print(f"   ✅ ページタイトルで発見: '{hall_name}'")
                    return hall_name
        
        print("   ❌ どの方法でもホール名を発見できませんでした")
        return None
        
    except Exception as e:
        print(f"   ❌ HTML解析エラー: {e}")
        import traceback
        traceback.print_exc()
        return None


async def process_target_page_html(page, date_str, hall_name, save_dir):
    """HTML解析でターゲットページを処理（元のまま）"""
    
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
        all_data_table = None
        
        # H4要素から「全データ一覧」を探す
        for h4 in soup.find_all('h4'):
            if '全データ一覧' in h4.get_text().strip():
                all_data_table = h4.find_next('table')
                break
        
        if all_data_table:
            rows = all_data_table.find_all('tr')
            print(f"         ✅ 全データ一覧: {len(rows)}行")
            
            if len(rows) > 1:  # ヘッダー行を除く
                # ヘッダー取得
                header = [cell.get_text().strip() for cell in rows[0].find_all(['td', 'th'])]
                print(f"         📊 ヘッダー: {header}")
                
                # データ行処理
                for row in rows[1:]:  # ヘッダーをスキップ
                    cells = [cell.get_text().strip() for cell in row.find_all(['td', 'th'])]
                    if len(cells) >= len(header):  # 有効な行のみ
                        row_data = dict(zip(header, cells))
                        extracted_data['all_data'].append(row_data)
                
                print(f"         ✅ 全データ: {len(extracted_data['all_data'])}件抽出")
        else:
            print(f"         ❌ 全データ一覧テーブルが見つかりません")
        
        # 2. 末尾別集計データを取得
        print(f"      📊 末尾別集計テーブル検索...")
        last_digit_table = soup.find(id="last_digit_data_table")
        
        if last_digit_table:
            print(f"         ✅ 末尾別集計テーブル発見！")
            
            # テーブルを直接探すかネストされているかチェック
            if last_digit_table.name == 'table':
                table = last_digit_table
            else:
                # 内部のテーブルを探す
                table = last_digit_table.find('table')
            
            if table:
                rows = table.find_all('tr')
                if len(rows) > 1:
                    header = [cell.get_text().strip() for cell in rows[0].find_all(['td', 'th'])]
                    
                    for row in rows[1:]:
                        cells = [cell.get_text().strip() for cell in row.find_all(['td', 'th'])]
                        if len(cells) >= len(header):
                            row_data = dict(zip(header, cells))
                            extracted_data['last_digit_data'].append(row_data)
                    
                    print(f"         ✅ 末尾別データ: {len(extracted_data['last_digit_data'])}件抽出")
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
    """広告処理ステップ（簡易版）"""
    
    try:
        # 簡単な自動クローズ試行
        await try_auto_close(page)
        
        if not auto_only:
            print(f"   📢 {page_type}で広告がある場合は手動で閉じてください")
            input("   広告処理完了後、Enterを押してください: ")
        else:
            await asyncio.sleep(3)  # 自動処理時は短時間待機
            
    except Exception as e:
        print(f"   ⚠️ 広告処理エラー: {e}")


async def try_auto_close(page):
    """自動クローズ試行（簡易版）"""
    
    try:
        # ESCキー送信
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


async def date_range_scrape_hybrid(start_date_str, end_date_str, list_url):
    """ハイブリッド版スクレイピング（遷移のみJS、その他HTML解析）"""
    
    browser = None
    try:
        print(f"🎯 ハイブリッド版スクレイピング: {start_date_str} ～ {end_date_str}")
        print(f"🌐 対象URL: {list_url}")
        print("="*70)
        
        # ブラウザ起動
        browser = await uc.start(headless=False)
        
        # 一覧ページアクセス
        print("📄 一覧ページにアクセス中...")
        page = await browser.get(list_url)
        
        # 十分な待機時間
        print("⏳ ページ読み込み待機（15秒）...")
        await asyncio.sleep(15)
        
        # HTML直接取得でホール名取得
        print("🏢 HTML解析でホール名取得中...")
        hall_name = await get_hall_name_from_html(page)
        
        if not hall_name:
            print("❌ ホール名の取得に失敗しました。")
            return 0, 0
            
        print(f"✅ ホール名検出: {hall_name}")
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
        base_save_dir = "scraped_data"
        hall_save_dir = os.path.join(base_save_dir, hall_name)
        os.makedirs(hall_save_dir, exist_ok=True)
        print(f"💾 保存先: {hall_save_dir}/")
        print(f"🗄️ データベース: pachinko_data.db")
        print()
        
        # 初回広告処理
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
                click_success = await find_and_click_link_hybrid(page, target_url, date_str)
                
                if not click_success:
                    print(f"   ❌ {date_str}: リンククリックに失敗しました")
                    failed_dates.append(date_str)
                    consecutive_failures += 1
                    
                    if consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                        print(f"\n🚨 連続失敗回数が{MAX_CONSECUTIVE_FAILURES}回に達しました。処理を中断します。")
                        break
                    
                    continue
                
                # ページ遷移後の処理
                print(f"   🌐 ページ遷移完了")
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
                            consecutive_failures = 0
                        else:
                            print(f"   ⚠️ {date_str}: 取得成功、DB保存失敗")
                            success_dates.append(date_str)  # 取得は成功とする
                            consecutive_failures = 0
                    else:
                        print(f"   ❌ {date_str}: JSONファイルが見つかりません")
                        failed_dates.append(date_str)
                        consecutive_failures += 1
                else:
                    print(f"   ❌ {date_str}: データ抽出失敗")
                    failed_dates.append(date_str)
                    consecutive_failures += 1
                    
                    if consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                        print(f"\n🚨 連続失敗回数が{MAX_CONSECUTIVE_FAILURES}回に達しました。処理を中断します。")
                        break
                
                # 一覧ページに戻る（最後の日付以外）
                if i < len(date_list):
                    await return_to_list_page_hybrid(page, list_url)
                
            except Exception as e:
                print(f"   ❌ {date_str}: エラー - {e}")
                failed_dates.append(date_str)
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
        
        return len(success_dates), len(failed_dates)
        
    except Exception as e:
        print(f"❌ 全体エラー: {e}")
        return 0, 0
    finally:
        if browser:
            print("\n📚 30秒後にブラウザ終了...")
            await asyncio.sleep(30)
            try:
                browser.stop()
            except:
                pass


# メイン関数
async def main():
    """ハイブリッド版メイン処理"""
    
    # URL指定
    target_url = "https://ana-slo.com/%E3%83%9B%E3%83%BC%E3%83%AB%E3%83%87%E3%83%BC%E3%82%BF/%E6%9D%B1%E4%BA%AC%E9%83%BD/%E3%83%9E%E3%83%AB%E3%83%8F%E3%83%B3%E3%83%A1%E3%82%AC%E3%82%B7%E3%83%86%E3%82%A32000-%E8%92%B2%E7%94%B01-%E3%83%87%E3%83%BC%E3%82%BF%E4%B8%80%E8%A6%A7/"
    start_date = "20251210"
    end_date = "20251210"
    
    print("🚀 ハイブリッド版スクレイピング開始...")
    print("   ページ遷移のみJavaScript、その他はHTML解析")
    print("   元のコードの遷移方式を維持しつつ安定性を向上")
    print()
    
    success_count, failed_count = await date_range_scrape_hybrid(start_date, end_date, target_url)
    
    print(f"\n🎯 最終結果: 成功 {success_count}件、失敗 {failed_count}件")
    print(f"💾 データベース: pachinko_data.db に保存完了")
    print(f"📁 フォルダ構成: scraped_data/[ホール名]/[日付]_[ホール名]_data.json")


if __name__ == "__main__":
    asyncio.run(main())