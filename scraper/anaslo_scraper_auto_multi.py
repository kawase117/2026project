#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
複数ホール対応の自動化版スクレイパー。

anaslo_scraper_auto.py のヘルパーを再利用し、
hall_config.json の active/enabled ホールを順次処理する。
"""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path
from typing import Any

import anaslo_scraper_auto as base


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="ana-slo.com 複数ホール自動スクレイパー")
    parser.add_argument("--start-date", default=base.DEFAULT_START_DATE, help="開始日 YYYYMMDD")
    parser.add_argument("--end-date", default=base.DEFAULT_END_DATE, help="終了日 YYYYMMDD")
    parser.add_argument("--db-path", default="pachinko_data.db", help="SQLite DB パス")
    parser.add_argument("--headless", action="store_true", help="ヘッドレスで起動")
    parser.add_argument(
        "--manual-challenge",
        action="store_true",
        help="Cloudflareチャレンジが出た場合、画面上での手動解決を待つ",
    )
    parser.add_argument("--config", default="hall_config.json", help="設定ファイル名")
    return parser


async def scrape_one_hall(
    browser,
    hall: dict[str, Any],
    *,
    start_date: str | None,
    end_date: str | None,
    db_path: str,
    manual_challenge: bool = False,
) -> tuple[str, int, int]:
    list_url = hall.get("scraper_url") or hall.get("url") or base.DEFAULT_LIST_URL
    page = await browser.get(list_url)
    list_html = await base.ensure_page_accessible(page, manual_challenge=manual_challenge)
    date_links = base.extract_date_links(list_html)
    if not date_links:
        raise RuntimeError(f"{list_url}: 日付リンクを抽出できません")

    hall_name = hall.get("hall_name") or hall.get("name")
    if not hall_name:
        hall_name = await base.get_hall_name_from_html(page)
    if not hall_name:
        hall_name = (
            base.normalize_hall_name(hall.get("name")) or base.extract_hall_name_from_url(list_url) or "unknown_hall"
        )

    if start_date is None and end_date is None:
        date_list = [max(date_links)]
        print(f"[DATE] 指定なしのため最新掲載日を使用: {date_list[0]}")
    else:
        resolved_start = start_date or min(date_links)
        resolved_end = end_date or max(date_links)
        date_list = base.generate_date_list(resolved_start, resolved_end)
    print(f"[DATE] 一覧から確認できた日付リンク: {len(date_links)}件")
    hall_save_dir = base.resolve_data_dir() / hall_name
    hall_save_dir.mkdir(parents=True, exist_ok=True)

    success_dates: list[str] = []
    failed_dates: list[str] = []
    consecutive_failures = 0
    max_consecutive_failures = 3

    print("\n" + "=" * 80)
    print(f"[HALL] {hall_name}")
    print(f"[URL ] {list_url}")
    print(f"[DATE] {start_date} -> {end_date} ({len(date_list)} days)")
    print("=" * 80)

    for i, date_str in enumerate(date_list, 1):
        try:
            if date_str not in date_links:
                print(f"   [WARN] {date_str}: 一覧ページに日付リンクがありません")
                failed_dates.append(date_str)
                continue

            target_url = base.generate_target_url(date_str, hall_name)
            click_success = await base.find_and_click_link_hybrid(page, target_url, date_str)
            if not click_success:
                print(f"   [ERROR] {date_str}: リンククリックに失敗")
                failed_dates.append(date_str)
                consecutive_failures += 1
                if consecutive_failures >= max_consecutive_failures:
                    break
                continue

            extracted_data = await base.process_target_page_html(page, date_str, hall_name, hall_save_dir)
            if extracted_data is None:
                print(f"   [ERROR] {date_str}: データ抽出失敗")
                failed_dates.append(date_str)
                consecutive_failures += 1
            else:
                db_success = await base.save_to_database(extracted_data, db_path=db_path)
                if db_success:
                    print(f"   [OK] {date_str}: 取得・保存成功")
                    success_dates.append(date_str)
                else:
                    print(f"   [WARN] {date_str}: 取得成功、DB保存失敗のため失敗扱い")
                    failed_dates.append(date_str)
                # サイトアクセス自体は成功しているのでブロック検知用カウンタは戻す
                consecutive_failures = 0

            if i < len(date_list):
                await base.return_to_list_page_hybrid(page, list_url, manual_challenge=manual_challenge)

        except Exception as e:
            print(f"   [ERROR] {date_str}: {e}")
            failed_dates.append(date_str)
            consecutive_failures += 1
            if consecutive_failures >= max_consecutive_failures:
                break
            try:
                if i < len(date_list):
                    await base.return_to_list_page_hybrid(page, list_url, manual_challenge=manual_challenge)
            except Exception:
                pass

    base.print_summary(success_dates, failed_dates, hall_name)
    return hall_name, len(success_dates), len(failed_dates)


async def main_async(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    halls = base.load_hall_config(args.config)
    if not halls:
        return 1

    browser = None
    log_lines: list[str] = []
    try:
        browser = await base.launch_browser(headless=args.headless)

        total_success = 0
        total_failed = 0

        for hall in halls:
            hall_name, success_count, failed_count = await scrape_one_hall(
                browser,
                hall,
                start_date=args.start_date,
                end_date=args.end_date,
                db_path=args.db_path,
                manual_challenge=args.manual_challenge,
            )
            total_success += success_count
            total_failed += failed_count
            log_lines.append(f"{hall_name}: success={success_count}, failed={failed_count}")

        log_path = base.resolve_data_dir() / "scraping_log.txt"
        with open(log_path, "w", encoding="utf-8") as f:
            f.write("\n".join(log_lines) + ("\n" if log_lines else ""))

        print("\n" + "=" * 80)
        print(f"[TOTAL] success={total_success}, failed={total_failed}")
        print(f"[LOG  ] {log_path}")
        print("=" * 80)
        return 0
    finally:
        if browser:
            try:
                await browser.stop()
            except Exception:
                pass


def main() -> None:
    asyncio.run(main_async())


if __name__ == "__main__":
    main()
