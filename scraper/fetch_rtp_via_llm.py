#!/usr/bin/env python3
"""
Fetch RTP/BB/RB data from 1geki.jp using LLM interpretation.

Process:
1. Read CSV, identify rows with missing RTP
2. curl each 1geki.jp page, extract <table> blocks
3. Send HTML tables to Claude in batches (10 machines)
4. Parse JSON response → update CSV columns
5. Save HTML table to notes column for audit
"""

import csv
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Optional

import anthropic

REPO_ROOT = Path(__file__).resolve().parents[1]
CSV_PATH = REPO_ROOT / "document" / "machine_master_research" / "machine_list_for_research.csv"
BATCH_SIZE = 10
MACHINES_TO_PROCESS = 50  # Limit for initial run

# Known 1geki.jp slugs from prior research (from previous curl + regex extraction)
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
    """Read CSV and identify rows needing RTP data."""
    with open(CSV_PATH, encoding='utf-8-sig', newline='') as f:
        rows = list(csv.reader(f))
    return rows[0], rows[1:]  # header, data rows


def identify_missing_rtp(header, rows):
    """Find rows where RTP (columns 4-9) are all empty."""
    rtp_cols = slice(4, 10)  # columns 4-9: rtp_setting1-6
    missing = []
    for idx, row in enumerate(rows, 1):
        if not any(row[rtp_cols]):
            missing.append((idx, row))
    return missing


def get_1geki_slug(machine_name: str) -> Optional[str]:
    """Get 1geki.jp slug: check cache first, then try heuristic."""
    # Check known slugs
    if machine_name in SLUG_CACHE:
        return SLUG_CACHE[machine_name]

    # Fallback to heuristic (lowercase, replace spaces/parens)
    slug = machine_name.lower().replace(' ', '_').replace('(', '').replace(')', '')
    return slug


def curl_1geki_page(machine_name: str) -> Optional[tuple[str, str]]:
    """curl 1geki.jp/<slug>/ and return (slug, HTML) or (None, None)."""
    slug = get_1geki_slug(machine_name)
    if not slug:
        return None, None

    try:
        result = subprocess.run(
            ['curl', '-s', '-A', 'Mozilla/5.0', f'https://1geki.jp/slot/{slug}/'],
            capture_output=True, text=True, timeout=10, encoding='utf-8'
        )
        if result.returncode == 0 and result.stdout:
            return slug, result.stdout
    except Exception as e:
        print(f"    curl failed: {e}")
    return None, None


def extract_tables_from_html(html: str) -> list[str]:
    """Extract all <table>...</table> blocks from HTML."""
    pattern = r'<table[^>]*>.*?</table>'
    matches = re.findall(pattern, html, re.DOTALL)
    return matches


def format_batch_for_llm(machines_with_html: list[dict]) -> str:
    """Format a batch of machines + their HTML tables for LLM."""
    prompt_parts = []
    for item in machines_with_html:
        prompt_parts.append(f"\n【{item['name']}】\n")
        prompt_parts.append(item['html_snippet'])
    return "".join(prompt_parts)


def query_llm_for_specs(batch_prompt: str) -> Optional[str]:
    """Send HTML batch to Claude, get JSON response with RTP/BB/RB data."""
    client = anthropic.Anthropic()

    system_msg = """You are a Japanese pachislot data extraction expert.
Given HTML tables from 1geki.jp, extract numerical data for each machine.
Return a JSON array with one object per machine (in order), containing:
- name: 機種名
- rtp1, rtp2, rtp5, rtp6: 機械割 (e.g., 97.3)
- bb_init1, bb_init2, bb_init5, bb_init6: BB初当たり確率 (e.g., "1/309.1")
- rb_init1, rb_init2, rb_init5, rb_init6: RB初当たり確率 (e.g., "1/428.3")

If a value is unavailable or unclear, use null.
Return ONLY valid JSON, no markdown or extra text."""

    try:
        message = client.messages.create(
            model="claude-opus-4-8",
            max_tokens=2000,
            system=system_msg,
            messages=[
                {
                    "role": "user",
                    "content": batch_prompt
                }
            ]
        )
        return message.content[0].text
    except Exception as e:
        print(f"  ✗ LLM query failed: {e}")
        return None


def parse_rtp_value(s: str) -> Optional[float]:
    """Parse RTP string like '97.3%' or '97.3' to float."""
    if not s:
        return None
    s = str(s).replace('%', '').strip()
    try:
        return float(s)
    except:
        return None


def parse_probability(s: str) -> Optional[str]:
    """Parse probability like '1/309.1' or keep as-is."""
    if not s:
        return None
    return str(s).strip()


def update_csv_with_results(rows, header, results: list[dict]):
    """Update CSV rows with extracted RTP/BB/RB data."""
    updated_count = 0
    for result in results:
        machine_name = result.get('name')
        if not machine_name:
            continue

        # Find matching row
        for row in rows:
            if row[0].strip().lower() == machine_name.lower():
                # Update RTP columns (4-9)
                rtps = [
                    parse_rtp_value(result.get('rtp1')),
                    parse_rtp_value(result.get('rtp2')),
                    parse_rtp_value(result.get('rtp5')),
                    parse_rtp_value(result.get('rtp6')),
                ]
                for i, rtp in enumerate(rtps):
                    if rtp is not None and not row[4+i]:
                        row[4+i] = str(rtp)

                # Update BB columns (10-15)
                bbs = [
                    parse_probability(result.get('bb_init1')),
                    parse_probability(result.get('bb_init2')),
                    parse_probability(result.get('bb_init5')),
                    parse_probability(result.get('bb_init6')),
                ]
                for i, bb in enumerate(bbs):
                    if bb is not None and not row[10+i]:
                        row[10+i] = bb

                # Update RB columns (16-21)
                rbs = [
                    parse_probability(result.get('rb_init1')),
                    parse_probability(result.get('rb_init2')),
                    parse_probability(result.get('rb_init5')),
                    parse_probability(result.get('rb_init6')),
                ]
                for i, rb in enumerate(rbs):
                    if rb is not None and not row[16+i]:
                        row[16+i] = rb

                # Append HTML to notes
                html_tables = result.get('html_tables', '')
                if html_tables and not row[22]:
                    row[22] = html_tables[:500]  # Truncate to reasonable size

                updated_count += 1
                break

    return updated_count


def main():
    print("[RTP Fetcher] Fetching RTP data via LLM...\n")

    header, rows = read_csv()
    missing = identify_missing_rtp(header, rows)

    print(f"[RTP Fetcher] Found {len(missing)} machines with missing RTP")
    if not missing:
        print("[RTP Fetcher] All machines have RTP data")
        return

    # Process in batches
    total_updated = 0
    for batch_start in range(0, min(len(missing), MACHINES_TO_PROCESS), BATCH_SIZE):
        batch = missing[batch_start:batch_start+BATCH_SIZE]
        batch_num = batch_start // BATCH_SIZE + 1
        print(f"\n[Batch {batch_num}] ({len(batch)} machines)")

        machines_with_html = []
        for row_idx, row in batch:
            machine_name = row[0].strip()

            print(f"  {machine_name}...", end=" ")
            slug, html = curl_1geki_page(machine_name)

            if html:
                tables = extract_tables_from_html(html)
                if tables:
                    print(f"OK ({len(tables)} tables)")
                    machines_with_html.append({
                        'name': machine_name,
                        'html_snippet': ''.join(tables),
                        'row_idx': row_idx
                    })
                else:
                    print("SKIP (no tables)")
            else:
                print("FAIL (curl error)")

        if not machines_with_html:
            print("  WARNING: No machines fetched in this batch, skipping LLM")
            continue

        # Query LLM
        print(f"\n  Querying LLM for {len(machines_with_html)} machines...")
        batch_prompt = format_batch_for_llm(machines_with_html)
        response = query_llm_for_specs(batch_prompt)

        if response:
            try:
                results = json.loads(response)
                updated = update_csv_with_results(rows, header, results)
                total_updated += updated
                print(f"  DONE: Updated {updated} machines")
            except json.JSONDecodeError as e:
                print(f"  ERROR: Failed to parse LLM response: {e}")
                print(f"  Response: {response[:200]}")
        else:
            print("  ERROR: LLM query failed")

    # Write CSV
    print(f"\n[RTP Fetcher] Writing CSV with {total_updated} updates...")
    with open(CSV_PATH, 'w', encoding='utf-8-sig', newline='') as f:
        csv.writer(f).writerows([header] + rows)

    print(f"[RTP Fetcher] Complete. Updated {total_updated} machines.")


if __name__ == '__main__':
    main()
