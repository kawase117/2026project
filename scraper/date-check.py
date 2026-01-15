import os
import json
from datetime import datetime, timedelta
from pathlib import Path
from collections import defaultdict

# =============== フォルダパス設定 ===============
FOLDER_PATH = r"C:\Users\apto117\scraped_data\ヒロキ東口店"  # ここを変更してください

# ================================================

def extract_date_from_filename(filename):
    """ファイル名から日付を抽出"""
    try:
        date_str = filename.split('_')[0]
        if len(date_str) == 8 and date_str.isdigit():
            return date_str
    except:
        pass
    return None


def get_file_size_kb(filepath):
    """ファイルサイズをKB単位で返す"""
    return os.path.getsize(filepath) / 1024


def validate_scraping_data(folder_path):
    """スクレイピングデータの完全性を検証"""
    
    if not os.path.isdir(folder_path):
        print(f"エラー: フォルダが見つかりません: {folder_path}")
        return
    
    # JSONファイルを収集
    json_files = [f for f in os.listdir(folder_path) if f.endswith('.json')]
    
    if not json_files:
        print(f"エラー: JSONファイルがありません: {folder_path}")
        return
    
    # ファイル情報を集計
    file_info = {}  # {date_str: filepath}
    dates = []
    
    for filename in json_files:
        date_str = extract_date_from_filename(filename)
        if date_str:
            filepath = os.path.join(folder_path, filename)
            file_info[date_str] = filepath
            dates.append(date_str)
    
    if not dates:
        print("エラー: 有効な日付形式のファイルがありません")
        return
    
    # 日付をソート
    dates.sort()
    start_date_str = dates[0]
    end_date_str = dates[-1]
    
    print(f"検証範囲: {start_date_str} ～ {end_date_str}")
    print(f"見つかったファイル数: {len(dates)}\n")
    
    # 期待される日付範囲を生成
    start_date = datetime.strptime(start_date_str, "%Y%m%d")
    end_date = datetime.strptime(end_date_str, "%Y%m%d")
    expected_dates = []
    current_date = start_date
    
    while current_date <= end_date:
        expected_dates.append(current_date.strftime("%Y%m%d"))
        current_date += timedelta(days=1)
    
    # 1. 欠損日付の確認
    missing_dates = [d for d in expected_dates if d not in file_info]
    
    if missing_dates:
        print("【欠損日付】")
        for date in missing_dates:
            print(f"  {date}")
        print(f"合計: {len(missing_dates)}日\n")
    else:
        print("【欠損日付】なし\n")
    
    # 2. ファイルサイズの低下を確認
    size_decrease = []
    
    for i in range(1, len(expected_dates)):
        prev_date = expected_dates[i - 1]
        curr_date = expected_dates[i]
        
        # 両方のファイルが存在する場合のみ比較
        if prev_date in file_info and curr_date in file_info:
            prev_size = get_file_size_kb(file_info[prev_date])
            curr_size = get_file_size_kb(file_info[curr_date])
            
            decrease = prev_size - curr_size
            
            if decrease >= 10:
                size_decrease.append({
                    'prev_date': prev_date,
                    'curr_date': curr_date,
                    'prev_size': prev_size,
                    'curr_size': curr_size,
                    'decrease': decrease
                })
    
    if size_decrease:
        print("【ファイルサイズ低下（10KB以上）】")
        for item in size_decrease:
            print(f"  {item['prev_date']} ({item['prev_size']:.2f}KB) " +
                  f"→ {item['curr_date']} ({item['curr_size']:.2f}KB) " +
                  f"[{item['decrease']:.2f}KB減]")
        print(f"合計: {len(size_decrease)}件\n")
    else:
        print("【ファイルサイズ低下（10KB以上）】なし\n")
    
    # 3. サマリー
    print("=" * 60)
    print(f"ファイル総数（期待値）: {len(expected_dates)}")
    print(f"ファイル総数（実際）: {len(dates)}")
    print(f"欠損ファイル数: {len(missing_dates)}")
    print(f"サイズ低下（10KB以上）: {len(size_decrease)}件")
    print("=" * 60)


if __name__ == "__main__":
    validate_scraping_data(FOLDER_PATH)