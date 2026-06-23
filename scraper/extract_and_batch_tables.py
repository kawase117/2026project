#!/usr/bin/env python3
"""
Extract HTML tables from 1geki.jp and batch them for processing in Claude Code.

Workflow:
1. Read CSV, find rows with missing RTP
2. curl each 1geki.jp page using SLUG_CACHE
3. Extract <table> blocks
4. Save batches to batch_N.txt (machine_name + HTML table)
"""

import csv
import re
import subprocess
from pathlib import Path
from typing import Optional

REPO_ROOT = Path(__file__).resolve().parents[1]
CSV_PATH = REPO_ROOT / "document" / "machine_master_research" / "machine_list_for_research.csv"
BATCH_OUTPUT_DIR = REPO_ROOT / "scratch" / "1geki_batches"
BATCH_SIZE = 10

SLUG_CACHE = {
    "1000ちゃんA": "lb_1000chan_a",
    "A-SLOT+ 異世界かるてっと": "l_isekai_quartet",
    "SHAKE BONUS TRIGGER": "lb_shake",
    "SHAKE BONUS TRIGGER(スマスロ)": "lb_shake",
    "SLOTドルアーガの塔": "s_druaga",
    "なめ猫～液晶ないけどなめんじゃねぇ～": "s_nameneko",
    "ようこそ実力至上主義の教室へ": "l_youjitsu",
    "アレックス ブライト": "lb_arexbright",
    "ストライクウィッチーズ2": "l_strikewitches2",
    "スマスロ炎炎ノ消防隊2": "l_ennenn2",
    "聖戦士ダンバイン": "l_dunbine",
    "スマート沖スロ スターハナハナ": "l_starhnhn30",
    "スマート沖スロ ニューキングハナハナV": "l_new_king_hanahana_v",
    "ニューキングハナハナV-30": "s_new_king_hanahana_v30",
    "スーパーリオエース2": "l_sp_rioace2",
    "ドッチ": "l_asd",
    "ハイビリターン-30": "s_haibi_return30",
    "ビッグドリーム THE GOLDEN PUSHER": "l_bigdream",
    "プレミアムうまい棒": "lb_umaibou",
    "マタドールIII": "l_mtd3",
    "モモキュンソード": "s_momokyun",
    "回胴黙示録カイジ 狂宴": "l_kaiji_ky",
    "少女☆歌劇 レヴュースタァライト ‐The SLOT‐": "l_revuestarlight",
    "甲鉄城のカバネリ 海門(うなと)決戦": "l_kabaneri2",
    "翔べ!ハーレムエース": "lb_harema",
    "荒野のコトブキ飛行隊": "l_kotobuki",
    "銀河英雄伝説 Die Neue These": "l_gineidendnt",
    "革命機ヴァルヴレイヴ2": "l_valvrave2",
    "鬼武者3": "l_onimusya3",
}


def read_csv():
    with open(CSV_PATH, encoding='utf-8-sig', newline='') as f:
        rows = list(csv.reader(f))
    return rows[0], rows[1:]


def identify_missing_rtp(header, rows):
    rtp_cols = slice(4, 10)
    missing = []
    for idx, row in enumerate(rows, 1):
        if not any(row[rtp_cols]):
            missing.append((idx, row))
    return missing


def get_slug(machine_name: str) -> Optional[str]:
    if machine_name in SLUG_CACHE:
        return SLUG_CACHE[machine_name]
    slug = machine_name.lower().replace(' ', '_').replace('(', '').replace(')', '')
    return slug


def curl_1geki_page(machine_name: str) -> Optional[str]:
    slug = get_slug(machine_name)
    if not slug:
        return None
    try:
        result = subprocess.run(
            ['curl', '-s', '-A', 'Mozilla/5.0', f'https://1geki.jp/slot/{slug}/'],
            capture_output=True, text=True, timeout=10, encoding='utf-8'
        )
        if result.returncode == 0 and result.stdout:
            return result.stdout
    except Exception as e:
        print(f"    curl failed: {e}")
    return None


def extract_tables(html: str) -> list[str]:
    pattern = r'<table[^>]*>.*?</table>'
    matches = re.findall(pattern, html, re.DOTALL)
    return matches


def main():
    print("[TableExtractor] Reading CSV...")
    header, rows = read_csv()
    missing = identify_missing_rtp(header, rows)
    print(f"[TableExtractor] Found {len(missing)} machines with missing RTP\n")

    if not missing:
        print("[TableExtractor] All done!")
        return

    BATCH_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    batch_num = 0
    batch_content = []

    for item_idx, (row_idx, row) in enumerate(missing):
        machine_name = row[0].strip()
        print(f"[{item_idx+1}/{len(missing)}] {machine_name}...", end=" ")

        html = curl_1geki_page(machine_name)
        if html:
            tables = extract_tables(html)
            if tables:
                batch_content.append(f"\n\n{'='*60}\n【{machine_name}】\n{'='*60}\n")
                batch_content.append('\n'.join(tables))
                print("OK")
            else:
                print("SKIP (no tables)")
        else:
            print("FAIL")

        # Write batch every BATCH_SIZE machines
        if len(batch_content) >= BATCH_SIZE or item_idx == len(missing) - 1:
            if batch_content:
                batch_num += 1
                batch_file = BATCH_OUTPUT_DIR / f"batch_{batch_num}.txt"
                with open(batch_file, 'w', encoding='utf-8') as f:
                    f.write(''.join(batch_content))
                print(f"  -> Batch {batch_num} saved to {batch_file}\n")
                batch_content = []

    print(f"[TableExtractor] Complete. Generated {batch_num} batch files.")


if __name__ == '__main__':
    main()
