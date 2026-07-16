#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ananlo-scraper.py をベースにした自動化版。

方針:
- JSON スキーマは既存維持
- 手動待ちを廃止し、DOM 監視ベースでページ安定化
- 既存の URL 揺れ対策と HTML 直接解析を維持
- 取得結果は JSON と SQLite に保存
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sqlite3
import urllib.parse
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from bs4 import BeautifulSoup
import nodriver as uc


DEFAULT_LIST_URL = "https://ana-slo.com/%E3%83%9B%E3%83%BC%E3%83%AB%E3%83%87%E3%83%BC%E3%82%BF/%E6%9D%B1%E4%BA%AC%E9%83%BD/%E6%A5%BD%E5%9C%92%E8%92%B2%E7%94%B0%E5%BA%97-%E3%83%87%E3%83%BC%E3%82%BF%E4%B8%80%E8%A6%A7/"
DEFAULT_START_DATE = None
DEFAULT_END_DATE = None

CHALLENGE_TEXT_MARKERS = (
    "just a moment",
    "verify you are human",
    "performing security verification",
    "enable javascript and cookies to continue",
    "error 1015",
    "403 forbidden",
)


def classify_page_html(html: str, status: int | None = None) -> str:
    """ページを、取得処理で使える粗い状態に分類する。

    status が None の場合（nodriver でステータスを取得できなかった場合）は
    HTML本文ベースの判定のみで分類する。403/429 の blocked 判定は
    status が渡されたときだけ機能する。
    """

    soup = BeautifulSoup(html, "html.parser")
    visible_text = soup.get_text(" ", strip=True).casefold()
    title = soup.title.get_text(" ", strip=True).casefold() if soup.title else ""
    if any(marker in visible_text or marker in title for marker in CHALLENGE_TEXT_MARKERS):
        return "challenge"
    if soup.find(id="challenge-stage") or soup.find(id=re.compile(r"^cf-chl-")):
        return "challenge"

    if status in {403, 429}:
        return "blocked"

    if soup.find("h4", string=lambda text: text and "全データ一覧" in text):
        return "detail"

    for table in soup.find_all("table"):
        header = table.get_text(" ", strip=True)
        if "台番号" in header and "機種名" in header:
            return "detail"

    if soup.find("a", href=re.compile(r"\d{4}-\d{2}-\d{2}.*-data/")):
        return "list"

    if "日付をクリックすると詳細データ" in soup.get_text(" ", strip=True):
        return "list"

    if len(html.strip()) < 500:
        return "blank"

    return "unknown"


def extract_date_links(html: str) -> dict[str, str]:
    """一覧HTMLから、実在する日付別詳細URLを抽出する。"""

    soup = BeautifulSoup(html, "html.parser")
    links: dict[str, str] = {}
    date_pattern = re.compile(r"(?<!\d)(\d{4})-(\d{2})-(\d{2})(?=.*-data/)")
    for tag in soup.find_all("a", href=True):
        href = str(tag["href"])
        match = date_pattern.search(href)
        if not match:
            continue
        date_str = "".join(match.groups())
        links[date_str] = urllib.parse.urljoin("https://ana-slo.com/", href)
    return links


def project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def resolve_config_path(config_filename: str = "hall_config.json") -> Path:
    return project_root() / "config" / config_filename


def resolve_data_dir() -> Path:
    path = project_root() / "data"
    path.mkdir(parents=True, exist_ok=True)
    return path


def normalize_hall_name(hall_name: str | None) -> str | None:
    if not hall_name:
        return None
    normalized = hall_name.replace(" ", "-").replace("/", "-")
    return normalized


def extract_hall_name_from_url(url: str) -> str | None:
    try:
        if "-data/" not in url:
            return None
        before_data = url.split("-data/")[0]
        last_part = before_data.split("/")[-1]
        parts = last_part.split("-")
        if len(parts) <= 3:
            return None
        hall_name_encoded = "-".join(parts[3:])
        hall_name = urllib.parse.unquote(hall_name_encoded)
        return hall_name or None
    except Exception:
        return None


def generate_date_list(start_date_str: str, end_date_str: str) -> list[str]:
    start_date = datetime.strptime(start_date_str, "%Y%m%d")
    end_date = datetime.strptime(end_date_str, "%Y%m%d")
    date_list: list[str] = []
    current_date = start_date
    while current_date <= end_date:
        date_list.append(current_date.strftime("%Y%m%d"))
        current_date += timedelta(days=1)
    return date_list


def generate_target_url(date_str: str, hall_name: str) -> str:
    year = date_str[:4]
    month = date_str[4:6]
    day = date_str[6:8]
    formatted_date = f"{year}-{month}-{day}"
    hall_encoded = urllib.parse.quote(hall_name, safe="").lower()
    return f"https://ana-slo.com/{formatted_date}-{hall_encoded}-data/"


def load_hall_config(config_filename: str = "hall_config.json") -> list[dict[str, Any]]:
    config_path = resolve_config_path(config_filename)
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)
    except FileNotFoundError:
        print(f"[ERROR] 設定ファイルが見つかりません: {config_path}")
        return []
    except json.JSONDecodeError:
        print(f"[ERROR] 設定ファイルの形式が不正です: {config_path}")
        return []

    halls = config.get("halls", [])
    active_halls = [hall for hall in halls if hall.get("active", hall.get("enabled", True))]
    if not active_halls:
        print("[ERROR] アクティブなホール設定が見つかりません")
        return []

    print(f"[OK] {len(active_halls)}個のホール設定を読み込みました")
    return active_halls


class NodriverPageAdapter:
    def __init__(self, page) -> None:
        self._page = page
        self.last_status = None

    async def get_content(self) -> str:
        return await self._page.get_content()

    async def refresh_status(self) -> int | None:
        # nodriver はレスポンスの HTTP ステータスを直接公開しないため、
        # PerformanceNavigationTiming.responseStatus (Chrome 109+) を参照する。
        # 取得できない環境では last_status を None のまま維持し、
        # classify_page_html は HTML 本文ベースの判定にフォールバックする。
        try:
            status = await self._page.evaluate(
                "(() => {"
                " const entries = performance.getEntriesByType('navigation');"
                " if (!entries.length) return null;"
                " const s = entries[entries.length - 1].responseStatus;"
                " return (typeof s === 'number' && s > 0) ? s : null;"
                " })()"
            )
            if isinstance(status, (int, float)) and status:
                self.last_status = int(status)
        except Exception as exc:
            print(f"   [DEBUG] HTTPステータス取得に失敗（HTML判定にフォールバック）: {exc}")
        return self.last_status

    async def evaluate(self, js: str):
        return await self._page.evaluate(js)

    async def navigate(self, url: str) -> None:
        # 旧版で実績のある、同一タブ内のJavaScript遷移を維持する。
        escaped_url = json.dumps(url, ensure_ascii=False)
        await self._page.evaluate(f"window.location.href = {escaped_url}")


class NodriverBrowserAdapter:
    def __init__(self, browser) -> None:
        self._browser = browser
        self._page = None

    async def get(self, url: str) -> NodriverPageAdapter:
        if self._page is None:
            self._page = await self._browser.get(url)
        else:
            await NodriverPageAdapter(self._page).navigate(url)
        return NodriverPageAdapter(self._page)

    async def stop(self) -> None:
        self._browser.stop()


async def launch_browser(headless: bool):
    browser = await uc.start(headless=headless, sandbox=False)
    return NodriverBrowserAdapter(browser)


async def wait_for_page_stable(page, *, timeout: int = 15, poll_interval: float = 1.0, expected: str = "either") -> str:
    """
    manual_ad_step の代替。

    手動入力は使わず、HTML を監視して必要なテーブルが出るまで待つ。
    広告らしき要素があれば、JS で閉じられる範囲だけ試す。
    """

    await attempt_auto_close_overlays(page)

    deadline = asyncio.get_event_loop().time() + timeout
    last_html = ""
    while asyncio.get_event_loop().time() < deadline:
        try:
            refresh_status = getattr(page, "refresh_status", None)
            if refresh_status:
                await refresh_status()
            last_html = await page.get_content()
            state = classify_page_html(last_html, getattr(page, "last_status", None))
            if state in {"blocked", "challenge"}:
                return last_html
            if state == "blank":
                # Same-tab navigation can briefly expose an empty document.
                await asyncio.sleep(poll_interval)
                continue
            if expected == "list" and state == "list":
                return last_html
            if expected == "detail" and state == "detail":
                return last_html
            if expected == "either" and state in {"list", "detail"}:
                return last_html
        except Exception as exc:
            print(f"   [DEBUG] ページ状態の取得に失敗（再試行します）: {exc}")
        await asyncio.sleep(poll_interval)

    return last_html


async def ensure_page_accessible(
    page,
    *,
    manual_challenge: bool = False,
    timeout: int = 90,
    initial_wait_timeout: int = 30,
) -> str:
    """一覧ページが実データページとして利用可能か確認する。"""

    html = await wait_for_page_stable(
        page,
        timeout=initial_wait_timeout,
        poll_interval=1,
        expected="list",
    )
    state = classify_page_html(html, getattr(page, "last_status", None))

    if state == "challenge" and manual_challenge:
        print("[WAIT] Cloudflareチャレンジをブラウザ画面で解決してください")
        deadline = asyncio.get_event_loop().time() + timeout
        while asyncio.get_event_loop().time() < deadline:
            await asyncio.sleep(2)
            html = await page.get_content()
            # チャレンジ初回応答の403を保持していても、解決後のHTMLを再評価する。
            state = classify_page_html(html, None)
            if state == "list":
                return html

    if state != "list":
        status = getattr(page, "last_status", None)
        raise RuntimeError(f"一覧ページを利用できません: state={state}, status={status}")
    return html


async def attempt_auto_close_overlays(page) -> None:
    """
    自動で閉じられる広告・オーバーレイを閉じる試行。

    ここでは repository 内の既存依存を増やさず、JS でクリック可能な
    close/dismiss 系要素だけを触る。失敗しても処理は継続する。
    """

    js = r"""
(() => {
  const selectors = [
    'button[aria-label*="close" i]',
    'button[title*="close" i]',
    'button[class*="close" i]',
    'a[aria-label*="close" i]',
    '[data-dismiss]',
    '[data-close]',
    '[class*="modal"] button',
    '[class*="overlay"] button',
  ];
  const textPattern = /(close|dismiss|skip|閉じる|×|✕)/i;
  let clicked = 0;

  for (const selector of selectors) {
    for (const el of document.querySelectorAll(selector)) {
      try {
        el.click();
        clicked += 1;
      } catch (_) {}
    }
  }

  for (const el of document.querySelectorAll('button, a, div, span')) {
    try {
      const text = (el.innerText || el.textContent || '').trim();
      if (text && textPattern.test(text) && text.length <= 30) {
        el.click();
        clicked += 1;
      }
    } catch (_) {}
  }

  return clicked;
})()
"""

    try:
        await page.evaluate(js)
    except Exception:
        pass


async def find_and_click_link_hybrid(page, target_url: str, date_str: str) -> bool:
    try:
        html_content = await page.get_content()
        state = classify_page_html(html_content, getattr(page, "last_status", None))
        if state != "list":
            print(f"   [ERROR] 一覧ページ状態が不正です: {state}")
            return False

        actual_url = extract_date_links(html_content).get(date_str)
        if not actual_url:
            print(f"   [WARN] {date_str}: 一覧ページに実在リンクがありません")
            return False

        navigate = getattr(page, "navigate", None)
        if navigate:
            await navigate(actual_url)
        else:
            await page.evaluate("url => { window.location.href = url; }", actual_url)

        current_html = await wait_for_page_stable(page, timeout=12, poll_interval=1, expected="detail")
        current_state = classify_page_html(current_html, getattr(page, "last_status", None))
        if current_state == "detail":
            return True

        print(
            f"   [ERROR] {date_str}: 詳細ページを確認できません "
            f"(state={current_state}, status={getattr(page, 'last_status', None)})"
        )
        return False
    except Exception as e:
        print(f"   [ERROR] リンク検索エラー: {e}")
        return False


async def return_to_list_page_hybrid(
    page,
    list_url: str,
    *,
    manual_challenge: bool = False,
    retries: int = 3,
) -> None:
    """一覧ページへ戻る。短時間の白紙HTMLは再試行して吸収する。"""

    last_error: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            if attempt > 1:
                await asyncio.sleep(min(2 * attempt, 6))

            navigate = getattr(page, "navigate", None)
            if navigate:
                await navigate(list_url)
            else:
                await page.evaluate("url => { window.location.href = url; }", list_url)

            await ensure_page_accessible(
                page,
                manual_challenge=manual_challenge,
                timeout=90 if attempt == 1 else 30,
                initial_wait_timeout=45 if attempt == 1 else 30,
            )
            return
        except Exception as e:
            last_error = e
            if attempt < retries:
                print(f"   [RETRY] 一覧ページ復旧 {attempt}/{retries}: {e}")

    raise RuntimeError(f"一覧ページ遷移エラー（{retries}回試行）: {last_error}") from last_error


async def get_hall_name_from_html(page) -> str | None:
    try:
        html_content = await page.get_content()
        soup = BeautifulSoup(html_content, "html.parser")

        raw_hall_name = None

        st_page = soup.find(id="st-page")
        if st_page:
            h1 = st_page.find("h1")
            if h1:
                raw_hall_name = h1.get_text().replace("データ一覧", "").strip()

        if not raw_hall_name:
            for h1 in soup.find_all("h1"):
                text = h1.get_text().strip()
                if "データ一覧" in text:
                    raw_hall_name = text.replace("データ一覧", "").strip()
                    break

        if not raw_hall_name:
            title_tag = soup.find("title")
            if title_tag:
                title_text = title_tag.get_text()
                if "データ一覧" in title_text:
                    raw_hall_name = title_text.replace("データ一覧", "").replace("- アナスロ", "").strip()

        return normalize_hall_name(raw_hall_name)
    except Exception as e:
        print(f"   [ERROR] HTML解析エラー: {e}")
        return None


def _extract_table_rows(table) -> list[dict[str, str]]:
    rows = table.find_all("tr")
    if len(rows) <= 1:
        return []
    header = [cell.get_text().strip() for cell in rows[0].find_all(["td", "th"])]
    extracted: list[dict[str, str]] = []
    for row in rows[1:]:
        cells = [cell.get_text().strip() for cell in row.find_all(["td", "th"])]
        if len(cells) >= len(header):
            extracted.append(dict(zip(header, cells)))
    return extracted


async def process_target_page_html(page, date_str: str, hall_name: str, save_dir: Path) -> dict[str, Any] | None:
    try:
        await wait_for_page_stable(page, timeout=12, poll_interval=1, expected="detail")
        html_content = await page.get_content()
        state = classify_page_html(html_content, getattr(page, "last_status", None))
        if state != "detail":
            print(f"   [ERROR] 詳細ページ状態が不正です: {state}")
            return None
        soup = BeautifulSoup(html_content, "html.parser")

        extracted_data: dict[str, Any] = {
            "date": date_str,
            "hall_name": hall_name,
            "all_data": [],
            "last_digit_data": [],
            "url": html_content[:200] if html_content else "",
        }

        all_data_table = soup.find(id="all_data_table")
        if not all_data_table:
            for h4 in soup.find_all("h4"):
                if "全データ一覧" in h4.get_text().strip():
                    all_data_table = h4.find_next("table")
                    break
        if all_data_table:
            extracted_data["all_data"] = _extract_table_rows(all_data_table)

        last_digit_table = soup.find(id="last_digit_data_table")
        if last_digit_table:
            table = last_digit_table if last_digit_table.name == "table" else last_digit_table.find("table")
            if table:
                extracted_data["last_digit_data"] = _extract_table_rows(table)

        if not extracted_data["all_data"]:
            print("   [ERROR] 全データ一覧の行が0件です")
            return None

        json_filename = f"{date_str}_{hall_name}_data.json"
        json_filepath = save_dir / json_filename
        with open(json_filepath, "w", encoding="utf-8") as f:
            json.dump(extracted_data, f, ensure_ascii=False, indent=2)

        return extracted_data
    except Exception as e:
        print(f"   [ERROR] ページ処理エラー: {e}")
        return None


def _safe_int(value: Any) -> int | None:
    try:
        return int(str(value).replace(",", "").replace("+", "").replace("-", ""))
    except Exception:
        return None


def _safe_float(value: Any) -> float | None:
    try:
        return float(str(value).replace(",", ""))
    except Exception:
        return None


async def save_to_database(extracted_data: dict[str, Any], db_path: str = "pachinko_data.db") -> bool:
    conn = None
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        cursor.execute(
            """
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
            """
        )

        cursor.execute(
            """
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
            """
        )

        cursor.execute(
            """
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
            """
        )

        # 同じ日付・ホールを再実行しても明細が二重登録されないよう、
        # スナップショット対象の子テーブルを先に置き換える。
        cursor.execute(
            "DELETE FROM machine_data WHERE date=? AND hall_name=?",
            (extracted_data["date"], extracted_data["hall_name"]),
        )
        cursor.execute(
            "DELETE FROM last_digit_summary WHERE date=? AND hall_name=?",
            (extracted_data["date"], extracted_data["hall_name"]),
        )

        cursor.execute(
            """
            INSERT OR REPLACE INTO hall_daily_data
            (date, hall_name, url, all_data_count, last_digit_data_count)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                extracted_data["date"],
                extracted_data["hall_name"],
                extracted_data["url"],
                len(extracted_data["all_data"]),
                len(extracted_data["last_digit_data"]),
            ),
        )

        for machine in extracted_data["all_data"]:
            cursor.execute(
                """
                INSERT INTO machine_data
                (date, hall_name, machine_name, machine_number, games, diff_coins,
                 bb_count, rb_count, total_probability, bb_probability, rb_probability)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    extracted_data["date"],
                    extracted_data["hall_name"],
                    machine.get("機種名", ""),
                    machine.get("台番号", ""),
                    _safe_int(machine.get("G数", 0)),
                    _safe_int(machine.get("差枚", 0)),
                    _safe_int(machine.get("BB", 0)),
                    _safe_int(machine.get("RB", 0)),
                    machine.get("合成確率", ""),
                    machine.get("BB確率", ""),
                    machine.get("RB確率", ""),
                ),
            )

        for last_digit in extracted_data["last_digit_data"]:
            cursor.execute(
                """
                INSERT INTO last_digit_summary
                (date, hall_name, last_digit, machine_count, total_games,
                 total_diff_coins, avg_games, avg_diff_coins)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    extracted_data["date"],
                    extracted_data["hall_name"],
                    last_digit.get("末尾", last_digit.get("last_digit", "")),
                    _safe_int(last_digit.get("台数", last_digit.get("count", 0))),
                    _safe_int(last_digit.get("総G数", last_digit.get("total_games", 0))),
                    _safe_int(last_digit.get("総差枚", last_digit.get("total_diff", 0))),
                    _safe_float(last_digit.get("平均G数", last_digit.get("avg_games", 0))),
                    _safe_float(last_digit.get("平均差枚", last_digit.get("avg_diff", 0))),
                ),
            )

        conn.commit()
        conn.close()
        return True
    except Exception as e:
        print(f"[ERROR] データベース保存エラー: {e}")
        # DELETE後にINSERTで失敗した場合、部分削除がコミットされないよう明示的に戻す
        if conn is not None:
            try:
                conn.rollback()
                conn.close()
            except Exception:
                pass
        return False


def print_summary(success_dates: list[str], failed_dates: list[str], hall_name: str) -> None:
    print("\n" + "=" * 70)
    print(f"📊 取得結果サマリー - {hall_name}")
    print("=" * 70)

    print(f"✅ 成功: {len(success_dates)}件")
    if success_dates:
        print("   " + ", ".join(f"{d[4:6]}/{d[6:8]}" for d in success_dates))

    print(f"\n❌ 失敗: {len(failed_dates)}件")
    if failed_dates:
        print("   " + ", ".join(f"{d[4:6]}/{d[6:8]}" for d in failed_dates))

    total = len(success_dates) + len(failed_dates)
    if total > 0:
        success_rate = (len(success_dates) / total) * 100
        print(f"\n📈 成功率: {success_rate:.1f}% ({len(success_dates)}/{total})")

    print("=" * 70)


async def date_range_scrape(
    start_date_str: str | None,
    end_date_str: str | None,
    list_url: str,
    *,
    headless: bool = False,
    db_path: str = "pachinko_data.db",
    manual_challenge: bool = False,
) -> tuple[int, int]:
    browser = None
    try:
        browser = await launch_browser(headless=headless)
        page = await browser.get(list_url)
        try:
            list_html = await ensure_page_accessible(
                page,
                manual_challenge=manual_challenge,
                initial_wait_timeout=45,
            )
        except Exception as initial_error:
            print(f"[RETRY] 初回一覧ページが白紙/未読込のため再遷移します: {initial_error}")
            await return_to_list_page_hybrid(
                page,
                list_url,
                manual_challenge=manual_challenge,
            )
            list_html = await page.get_content()
        date_links = extract_date_links(list_html)
        if not date_links:
            raise RuntimeError("一覧ページから日付リンクを抽出できません")

        hall_name = await get_hall_name_from_html(page)
        if not hall_name:
            hall_name = extract_hall_name_from_url(list_url) or "unknown_hall"

        if start_date_str is None and end_date_str is None:
            date_list = [max(date_links)]
            print(f"[DATE] 指定なしのため最新掲載日を使用: {date_list[0]}")
        else:
            resolved_start = start_date_str or min(date_links)
            resolved_end = end_date_str or max(date_links)
            date_list = generate_date_list(resolved_start, resolved_end)
        print(f"[DATE] 一覧から確認できた日付リンク: {len(date_links)}件")

        script_dir = project_root()
        hall_save_dir = resolve_data_dir() / hall_name
        hall_save_dir.mkdir(parents=True, exist_ok=True)

        success_dates: list[str] = []
        failed_dates: list[str] = []
        consecutive_failures = 0
        max_consecutive_failures = 3

        for i, date_str in enumerate(date_list, 1):
            date_saved = False
            try:
                if date_str not in date_links:
                    print(f"   [WARN] {date_str}: 一覧ページに日付リンクがありません")
                    if date_str not in failed_dates:
                        failed_dates.append(date_str)
                    continue

                target_url = generate_target_url(date_str, hall_name)
                click_success = await find_and_click_link_hybrid(page, target_url, date_str)
                if not click_success:
                    if date_str not in failed_dates:
                        failed_dates.append(date_str)
                    consecutive_failures += 1
                    if consecutive_failures >= max_consecutive_failures:
                        break
                    continue

                extracted_data = await process_target_page_html(page, date_str, hall_name, hall_save_dir)
                if extracted_data is None:
                    if date_str not in failed_dates:
                        failed_dates.append(date_str)
                    consecutive_failures += 1
                else:
                    db_success = await save_to_database(extracted_data, db_path=db_path)
                    if db_success:
                        if date_str not in success_dates:
                            success_dates.append(date_str)
                    else:
                        print(f"   [WARN] {date_str}: JSONは保存済みですがDB保存に失敗したため失敗扱いにします")
                        if date_str not in failed_dates:
                            failed_dates.append(date_str)
                    # サイトアクセス自体は成功しているのでブロック検知用カウンタは戻す
                    consecutive_failures = 0
                    date_saved = True

                if i < len(date_list):
                    try:
                        await return_to_list_page_hybrid(
                            page,
                            list_url,
                            manual_challenge=manual_challenge,
                        )
                    except Exception as navigation_error:
                        # 詳細ページの保存後に一覧復帰だけ失敗しても、
                        # その日付自体を失敗扱いにしない。
                        print(f"   [ERROR] {date_str}: 一覧ページ復旧に失敗しました: {navigation_error}")
                        if date_saved:
                            consecutive_failures = 0
                        raise
            except Exception as e:
                print(f"   [ERROR] {date_str}: {e}")
                if not date_saved:
                    if date_str not in failed_dates:
                        failed_dates.append(date_str)
                    consecutive_failures += 1
                if consecutive_failures >= max_consecutive_failures:
                    break
                try:
                    if i < len(date_list):
                        await return_to_list_page_hybrid(
                            page,
                            list_url,
                            manual_challenge=manual_challenge,
                        )
                except Exception:
                    pass

        print_summary(success_dates, failed_dates, hall_name)
        return len(success_dates), len(failed_dates)
    finally:
        if browser:
            try:
                await browser.stop()
            except Exception:
                pass


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="ana-slo.com 自動スクレイパー")
    parser.add_argument("--list-url", default=DEFAULT_LIST_URL, help="ホール一覧ページ URL")
    parser.add_argument("--start-date", default=DEFAULT_START_DATE, help="開始日 YYYYMMDD")
    parser.add_argument("--end-date", default=DEFAULT_END_DATE, help="終了日 YYYYMMDD")
    parser.add_argument("--db-path", default="pachinko_data.db", help="SQLite DB パス")
    parser.add_argument("--headless", action="store_true", help="ヘッドレスで起動")
    parser.add_argument(
        "--manual-challenge",
        action="store_true",
        help="Cloudflareチャレンジが出た場合、画面上での手動解決を待つ",
    )
    parser.add_argument("--config", default="hall_config.json", help="設定ファイル名")
    return parser


async def main_async(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    start_date = args.start_date
    end_date = args.end_date
    list_url = args.list_url

    if list_url == DEFAULT_LIST_URL:
        halls = load_hall_config(args.config)
        if halls:
            selected = halls[0]
            list_url = selected.get("scraper_url") or selected.get("url") or list_url

    success_count, failed_count = await date_range_scrape(
        start_date,
        end_date,
        list_url,
        headless=args.headless,
        db_path=args.db_path,
        manual_challenge=args.manual_challenge,
    )

    print(f"\n🎯 最終結果: 成功 {success_count}件、失敗 {failed_count}件")
    print(f"💾 データベース: {args.db_path}")
    return 0


def main() -> None:
    asyncio.run(main_async())


if __name__ == "__main__":
    main()
