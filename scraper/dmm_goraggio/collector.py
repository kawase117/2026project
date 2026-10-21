from __future__ import annotations

import argparse
import asyncio
import json
import re
import sqlite3
import sys
import time
import unicodedata
from contextlib import closing
from datetime import date, datetime
from pathlib import Path
from urllib.parse import parse_qs, urljoin, urlparse
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup
from playwright.async_api import APIRequestContext, Browser, BrowserContext, Playwright, async_playwright

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scraper.dmm_goraggio.parsing import (  # noqa: E402
    compact_text,
    discover_data_url,
    find_device_warning,
    parse_detail,
    parse_machine_list,
)
from scraper.dmm_goraggio.report import build_analysis, build_html  # noqa: E402
from backtest.model_alias import master_names, resolve_part  # noqa: E402
from scraper.realtime.quick_filter import load_audit, load_master_flags, rb_eligible  # noqa: E402


HALLS = {
    "nishiguchi": {
        "dmm_url": "https://p-town.dmm.com/shops/tokyo/292/jackpot",
        "data_hall_name": "ヒロキ蒲田西口店",  # 暫定・未確認: 実サイトのデータ側ホーム名を要確認
        "db_hall": None,  # db/ に西口のDBは現時点で存在しない
    },
    "max": {
        "dmm_url": "https://p-town.dmm.com/shops/tokyo/265/jackpot",
        "data_hall_name": "ヒロキMAX蒲田店",
        "db_hall": None,
    },
    "higashiguchi": {
        "dmm_url": "https://p-town.dmm.com/shops/tokyo/255/jackpot",
        "data_hall_name": "ヒロキ東口店",
        "db_hall": "ヒロキ東口店",
    },
}
JST = ZoneInfo("Asia/Tokyo")
IPHONE_UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 18_6 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.6 Mobile/15E148 Safari/604.1"
)


class CollectionError(RuntimeError):
    pass


class RateLimitError(CollectionError):
    pass


class ModelJoinError(CollectionError):
    pass


def failure_info(exc: Exception, stage: str, **context) -> dict:
    message = str(exc).strip()[:200]
    status = getattr(exc, "status", None)
    if status is None:
        match = re.search(r"\bHTTP\s+(\d{3})\b", str(exc))
        status = int(match.group(1)) if match else None
    return {
        "stage": stage,
        **context,
        "exception_type": type(exc).__name__,
        "message": message,
        "http_status": status,
        "error": f"{type(exc).__name__}: {message}" if message else type(exc).__name__,
    }


def _same_hall_link(href: str, data_root: str, endpoint: str) -> str | None:
    base = data_root + endpoint if href.startswith("?") else data_root + "/"
    url = urljoin(base, href)
    parsed, root = urlparse(url), urlparse(data_root)
    return url if parsed.netloc == root.netloc and parsed.path == root.path.rstrip("/") + endpoint else None


def parse_ball_price_links(html: str, data_root: str) -> list[tuple[str, str]]:
    """Find the site's links to each slot-rate model index."""
    links = {}
    for link in BeautifulSoup(html, "html.parser").find_all("a", href=True):
        url = _same_hall_link(link["href"], data_root, "/list")
        if url is None:
            continue
        query = parse_qs(urlparse(url).query)
        if query.get("mode") != ["psModelNameSearch"] or query.get("ps") != ["S"]:
            continue
        if "ballPrice" in query:
            links[query["ballPrice"][0]] = url
    return list(links.items())


def parse_model_links(html: str, data_root: str) -> list[tuple[str, str, str]]:
    """Keep model spelling, ballPrice, and URL from the site's unit-list links."""
    links = {}
    for link in BeautifulSoup(html, "html.parser").find_all("a", href=True):
        url = _same_hall_link(link["href"], data_root, "/unit_list")
        if url is None:
            continue
        query = parse_qs(urlparse(url).query)
        if query.get("ps") != ["S"] or "ballPrice" not in query or "model" not in query:
            continue
        model, price = query["model"][0], query["ballPrice"][0]
        links[(model, price)] = url
    return [(model, price, url) for (model, price), url in links.items()]


def _model_key(name: str) -> str:
    return name.strip()


def _rate_price(rate: str | None) -> float | None:
    """Convert yen/coin or coins/yen labels to yen per coin."""
    value = rate or ""
    coins_first = re.search(r"(\d+(?:\.\d+)?)\s*枚\s*/\s*(\d+(?:\.\d+)?)\s*円", value)
    if coins_first:
        coins, yen = map(float, coins_first.groups())
        return yen / coins if coins > 0 else None
    yen_first = re.search(r"(\d+(?:\.\d+)?)\s*円\s*/\s*(\d+(?:\.\d+)?)\s*枚", value)
    if yen_first:
        yen, coins = map(float, yen_first.groups())
        return yen / coins if coins > 0 else None
    direct = re.search(r"(\d+(?:\.\d+)?)\s*円", value)
    return float(direct.group(1)) if direct else None


def keep_standard_rate_machines(machines: list[dict]) -> tuple[list[dict], list[str]]:
    kept = []
    unknown_rates = set()
    for machine in machines:
        rate = machine.get("rate")
        yen_per_coin = _rate_price(rate)
        if yen_per_coin is None:
            kept.append(machine)
            unknown_rates.add(str(rate))
        elif yen_per_coin >= 10:
            kept.append(machine)
    warnings = [f"貸玉レートを換算できません。対象に保持: {rate}" for rate in sorted(unknown_rates)]
    return kept, warnings


def select_model_links(machines: list[dict], links: list[tuple[str, str, str]]) -> list[tuple[str, str, str]]:
    by_model: dict[str, list[tuple[str, str, str]]] = {}
    for link in links:
        by_model.setdefault(_model_key(link[0]), []).append(link)
    selected = []
    for model in {_model_key(machine["machine_name"]) for machine in machines}:
        candidates = by_model.get(model, [])
        if len(candidates) <= 1:
            selected.extend(candidates)
            continue
        rates = {
            _rate_price(machine.get("rate")) for machine in machines if _model_key(machine["machine_name"]) == model
        }
        if None in rates:
            selected.extend(candidates)
            continue
        matching = [link for link in candidates if any(abs(float(link[1]) - rate) < 0.011 for rate in rates)]
        selected.extend(matching if matching else candidates)
    return selected


def _business_date(value: str | date, expected: date) -> date | None:
    if isinstance(value, date):
        return value
    match = re.search(r"(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})", value)
    if match:
        try:
            return date(*map(int, match.groups()))
        except ValueError:
            return None
    match = re.search(r"(\d{1,2})月(\d{1,2})日", value)
    if match:
        month, day = map(int, match.groups())
        year = expected.year - (expected.month == 1 and month == 12)
        try:
            return date(year, month, day)
        except ValueError:
            return None
    return None


def parse_model_page(html: str, expected_date: date) -> tuple[date | None, dict[str, int | None]]:
    """Return the first business-day tab and cumulative starts by unit number."""
    soup = BeautifulSoup(html, "html.parser")
    current_option = soup.select_one('select[name="hist_num"] option[value="0"]')
    first_date = (
        _business_date(compact_text(current_option.get_text(" ", strip=True)), expected_date)
        if current_option is not None
        else None
    )
    if current_option is None:
        # Keep the earlier page form supported by the fixed fragment tests.
        for node in soup.select(".swiper-slide h4.Text-Left-01, .swiper-slide h4, .nav-tabs a, .date-tab, .dateTab"):
            first_date = _business_date(compact_text(node.get_text(" ", strip=True)), expected_date)
            if first_date is not None:
                break
    if first_date is None:
        raise ValueError("モデルページの先頭営業日が見つかりません")
    for table in soup.find_all("table"):
        headers = [compact_text(cell.get_text(" ", strip=True)) for cell in table.select("thead th")]
        if "台番号" not in headers or "累計スタート" not in headers:
            continue
        number_index, games_index = headers.index("台番号"), headers.index("累計スタート")
        units: dict[str, int | None] = {}
        for row in table.select("tbody tr"):
            cells = row.find_all("td", recursive=False)
            if len(cells) < len(headers):
                continue
            number = compact_text(cells[number_index].get_text(" ", strip=True))
            if not number.isdigit():
                continue
            raw = compact_text(cells[games_index].get_text(" ", strip=True)).replace(",", "")
            units[number] = int(raw) if re.fullmatch(r"\d+", raw) else None
        if not units:
            raise ValueError("モデルページの台番号行が見つかりません")
        return first_date, units
    raise ValueError("モデルページの累計スタート表が見つかりません")


def apply_model_games(
    machines: list[dict],
    model_pages: dict[tuple[str, str], tuple[date | None, dict[str, int | None]]],
    links: list[tuple[str, str, str]],
    business_date: date,
    failures: list[dict],
    index_failed: bool = False,
) -> None:
    available = {(model, price) for model, price, _ in links}
    failed = {(item.get("model"), item.get("ballPrice")) for item in failures if item.get("model")}
    index_errors = [item for item in failures if item.get("stage") == "model_index"]
    by_model: dict[str, list[tuple[str, str]]] = {}
    for model, price in available:
        by_model.setdefault(_model_key(model), []).append((model, price))
    missing: dict[str, set[str]] = {}
    for machine in machines:
        machine["total_games"] = None
        model, number = _model_key(machine["machine_name"]), machine["machine_number"]
        candidates = by_model.get(model, [])
        if not candidates:
            if index_failed and index_errors:
                source = index_errors[0]
                reason = f"fetch failure: model index {source['exception_type']}: {source['message']}"
            else:
                reason = "not in list"
            missing.setdefault(model, set()).add(reason)
            continue
        matches = [
            (price, units[number])
            for key in candidates
            if key in model_pages
            for page_date, units in [model_pages[key]]
            if page_date == business_date and number in units
            for price in [key[1]]
        ]
        rate = _rate_price(machine.get("rate"))
        preferred = [
            (price, games) for price, games in matches if rate is not None and abs(float(price) - rate) < 0.011
        ]
        chosen = preferred if preferred else matches
        if len(chosen) == 1:
            machine["total_games"] = chosen[0][1]
        elif len(chosen) > 1:
            missing.setdefault(model, set()).add("ballPrice mismatch: ambiguous unit join")
        elif any(key in failed for key in candidates):
            # The model-page failure already carries the original exception.
            continue
        elif any(key in model_pages and model_pages[key][0] != business_date for key in candidates):
            missing.setdefault(model, set()).add("営業日不一致")
        else:
            missing.setdefault(model, set()).add("ballPrice mismatch: unit number not found")
    for model, reasons in sorted(missing.items()):
        failures.append(failure_info(ModelJoinError("; ".join(sorted(reasons))), "model_page", model=model))


def resolve_hall(hall: str, dmm_url: str | None = None, output_dir: Path | None = None) -> tuple[dict, str, Path]:
    config = HALLS[hall]
    default_dir = "output" if hall == "max" else f"output_{hall}"
    return config, dmm_url or config["dmm_url"], output_dir or Path(__file__).resolve().parent / default_dir


def check_hall_name(home_html: str, data_hall_name: str) -> None:
    if data_hall_name not in home_html:
        raise CollectionError("取得先ホール名が一致しません")


def load_db_names(db_path: Path) -> tuple[dict[int, str], list[str]]:
    """台番号ごとの最新の名称と、略称照合に使う同ホールの名称候補を読む。"""
    if not db_path.is_file():
        print(f"警告: 機種名DBがありません: {db_path}", file=sys.stderr)
        return {}, []
    try:
        with closing(sqlite3.connect(db_path.resolve().as_uri() + "?mode=ro", uri=True)) as connection:
            rows = connection.execute(
                "SELECT machine_number, machine_name FROM machine_detailed_results ORDER BY machine_number, date DESC"
            )
            by_number: dict[int, str] = {}
            names: set[str] = set()
            for number, name in rows:
                if name:
                    by_number.setdefault(number, name)
                    names.add(name)
            return by_number, sorted(names)
    except sqlite3.Error as exc:
        print(f"警告: 機種名DBを読めません: {db_path}: {exc}", file=sys.stderr)
        return {}, []


def normalize_machine_name(machine: dict, by_number: dict[int, str], names: list[str]) -> str | None:
    try:
        number = int(machine["machine_number"])
    except KeyError, TypeError, ValueError:
        number = None
    if number is not None and number in by_number:
        return by_number[number]
    raw = machine.get("machine_name")
    if not raw or not names:
        return None
    match = resolve_part(unicodedata.normalize("NFKC", raw), names)
    # model_alias の成功ステータスは 'ok'。候補が一つのときだけ採用する。
    return match["names"][0] if match["status"] == "ok" and len(match["names"]) == 1 else None


def save_snapshot(result: dict, output_dir: Path, hall: str, payload: str) -> Path:
    observed = datetime.fromisoformat(result["observed_at"]).astimezone(JST)
    snapshot_dir = output_dir / "snapshots"
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    path = snapshot_dir / f"{hall}_{result['mode']}_{observed:%Y%m%d_%H%M%S}.json"
    with path.open("x", encoding="utf-8") as destination:
        destination.write(payload)
    return path


async def response_text(response, stage: str) -> str:
    if response.status == 429:
        raise RateLimitError(f"{stage}: アクセス制限 HTTP 429")
    if response.status == 403:
        raise CollectionError(f"{stage}: アクセス制限 HTTP 403")
    if not response.ok:
        raise CollectionError(f"{stage}: HTTP {response.status}")
    text = await response.text()
    warning = find_device_warning(text)
    if warning:
        raise CollectionError(f"{stage}: 端末警告 {warning}")
    return text


class RequestPacer:
    def __init__(self, request: APIRequestContext, interval_ms: int):
        self.request = request
        self.effective_interval_ms = interval_ms
        self.lock = asyncio.Lock()
        self.last_started = 0.0
        self.pause_until = 0.0
        self.request_count = 0
        self.rate_limit_events = 0

    async def get(self, url: str, stage: str) -> str:
        for attempt in range(3):
            async with self.lock:
                now = time.monotonic()
                wait = max(0.0, self.pause_until - now, self.last_started + self.effective_interval_ms / 1000 - now)
                if wait:
                    await asyncio.sleep(wait)
                self.last_started = time.monotonic()
                self.request_count += 1
            response = await self.request.get(url, timeout=45_000)
            try:
                return await response_text(response, stage)
            except RateLimitError:
                async with self.lock:
                    self.rate_limit_events += 1
                    self.effective_interval_ms = max(self.effective_interval_ms, 2500)
                    self.pause_until = max(self.pause_until, time.monotonic() + 65)
                if attempt == 2:
                    raise
        raise CollectionError(f"{stage}: 応答本文を取得できません")


async def collect_model_pages(
    pacer: RequestPacer, links: list[tuple[str, str, str]], workers: int, business_date: date
) -> tuple[dict[tuple[str, str], tuple[date | None, dict[str, int | None]]], list[dict]]:
    queue = asyncio.Queue()
    for item in links:
        queue.put_nowait(item)
    pages = {}
    failures = []

    async def worker() -> None:
        while True:
            try:
                model, price, url = queue.get_nowait()
            except asyncio.QueueEmpty:
                return
            try:
                html = await pacer.get(url, f"model:{model}")
                pages[(model, price)] = await asyncio.to_thread(parse_model_page, html, business_date)
            except Exception as exc:
                failures.append(failure_info(exc, "model_page", model=model, ballPrice=price))
            finally:
                queue.task_done()

    await asyncio.gather(*(worker() for _ in range(workers)))
    return pages, failures


async def discover_model_links(
    pacer: RequestPacer, data_root: str, machines: list[dict]
) -> tuple[list[tuple[str, str, str]], list[dict]]:
    failures: list[dict] = []
    links: list[tuple[str, str, str]] = []
    try:
        index_url = f"{data_root}/list?mode=psModelNameSearch&ps=S"
        index_html = await pacer.get(index_url, "model_index")
        price_links = parse_ball_price_links(index_html, data_root)
        if not price_links:
            raise CollectionError("ballPrice別の機種一覧リンクがありません")
        price_links = [
            (price, url)
            for price, url in price_links
            if _rate_price(price + "円") is None or _rate_price(price + "円") >= 10
        ]
    except Exception as exc:
        price_links = []
        failures.append(failure_info(exc, "model_index"))
    for price, url in price_links:
        try:
            index_html = await pacer.get(url, f"ball_price_index:{price}")
            price_models = [link for link in parse_model_links(index_html, data_root) if link[1] == price]
            if not price_models:
                raise CollectionError("unit_list機種リンクがありません")
            links.extend(price_models)
        except Exception as exc:
            failures.append(failure_info(exc, "model_index", ballPrice=price))
    return select_model_links(machines, links), failures


async def validate_mobile_entry(playwright: Playwright, dmm_url: str) -> tuple[Browser, BrowserContext, str, int]:
    browser = await playwright.chromium.launch(headless=True)
    device = dict(playwright.devices["iPhone 13"])
    device["user_agent"] = IPHONE_UA
    context = await browser.new_context(**device, locale="ja-JP", timezone_id="Asia/Tokyo")
    page = await context.new_page()

    async def route_handler(route) -> None:
        request = route.request
        if request.resource_type in {"image", "media", "font", "stylesheet"}:
            await route.abort()
        elif any(host in request.url for host in ("googletagmanager", "google-analytics", "doubleclick", "facebook")):
            await route.abort()
        else:
            await route.continue_()

    await page.route("**/*", route_handler)
    response = await page.goto(dmm_url, wait_until="domcontentloaded", timeout=30_000)
    if response is None or not response.ok:
        raise CollectionError(f"DMM入口確認に失敗しました: HTTP {response.status if response else 'none'}")
    html = await page.content()
    body_text = await page.locator("body").inner_text()
    warning = find_device_warning(body_text)
    if warning:
        raise CollectionError(f"DMM入口で端末警告を検知しました: {warning}")
    return browser, context, discover_data_url(html), 1


def load_prior(output_dir: Path, mode: str) -> dict | None:
    candidates = [output_dir / "latest_full.json", output_dir / "latest_quick.json"]
    if mode == "full" and candidates[0].exists():
        candidates = [candidates[0]]
    existing = [path for path in candidates if path.exists()]
    if not existing:
        return None
    path = max(existing, key=lambda item: item.stat().st_mtime)
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except OSError, json.JSONDecodeError:
        return None


def unchanged(machine: dict, prior_machine: dict | None) -> bool:
    if not prior_machine:
        return False
    keys = ("machine_name", "bb_count", "rb_count", "current_start", "previous_final_start")
    return all(machine.get(key) == prior_machine.get(key) for key in keys)


async def collect_details(
    pacer: RequestPacer,
    targets: list[dict],
    business_date,
    graph_dir: Path,
    workers: int,
) -> tuple[dict[str, dict], list[dict], int, int, int]:
    queue: asyncio.Queue[dict] = asyncio.Queue()
    for target in targets:
        queue.put_nowait(target)
    details: dict[str, dict] = {}
    failures: list[dict] = []
    graph_dir.mkdir(parents=True, exist_ok=True)

    async def fetch(target: dict) -> None:
        machine_number = target["machine_number"]
        html = await pacer.get(target["detail_url"], f"detail:{machine_number}")
        detail, svg = await asyncio.to_thread(parse_detail, html, business_date, machine_number)
        if svg:
            graph_path = graph_dir / f"{machine_number}.svg"
            await asyncio.to_thread(graph_path.write_text, svg, encoding="utf-8")
            detail["graph_path"] = f"graphs/{machine_number}.svg"
        detail["detail_url"] = target["detail_url"]
        detail["reused"] = False
        details[machine_number] = detail

    async def worker() -> None:
        while True:
            try:
                target = queue.get_nowait()
            except asyncio.QueueEmpty:
                return
            try:
                await fetch(target)
            except Exception as exc:  # keep partial evidence and continue other machines
                failures.append(failure_info(exc, "detail", machine_number=target["machine_number"]))
            finally:
                queue.task_done()

    await asyncio.gather(*(worker() for _ in range(workers)))
    return details, failures, pacer.request_count, pacer.rate_limit_events, pacer.effective_interval_ms


async def collect_details_then_models(
    pacer: RequestPacer,
    targets: list[dict],
    machines: list[dict],
    data_root: str,
    business_date: date,
    graph_dir: Path,
    workers: int,
) -> tuple[
    dict[str, dict],
    list[dict],
    list[tuple[str, str, str]],
    dict[tuple[str, str], tuple[date | None, dict[str, int | None]]],
    list[dict],
]:
    # Preserve the legacy detail opportunity before additional model requests or backoff.
    details, detail_failures, _, _, _ = await collect_details(pacer, targets, business_date, graph_dir, workers)
    links, index_failures = await discover_model_links(pacer, data_root, machines)
    pages, page_failures = await collect_model_pages(pacer, links, workers, business_date)
    return details, detail_failures, links, pages, index_failures + page_failures


async def run(args: argparse.Namespace) -> dict:
    output_dir: Path = args.output_dir
    hall_config = HALLS[args.hall]
    graph_dir = output_dir / "graphs"
    output_dir.mkdir(parents=True, exist_ok=True)
    started_at = datetime.now(JST)
    prior = load_prior(output_dir, args.mode)
    if prior and prior.get("hall_name") != hall_config["data_hall_name"]:
        prior = None
    request_count = 0

    async with async_playwright() as playwright:
        browser = None
        context = None
        try:
            browser, context, data_root, entrance_requests = await validate_mobile_entry(playwright, args.dmm_url)
            request_count += entrance_requests
            request = context.request
            home_response = await request.get(data_root, timeout=30_000)
            request_count += 1
            home_html = await response_text(home_response, "data_home")
            check_hall_name(home_html, hall_config["data_hall_name"])
            list_url = f"{data_root}/all_list?ps=S"
            list_response = await request.get(list_url, timeout=45_000)
            request_count += 1
            list_html = await response_text(list_response, "slot_list")
            machines = parse_machine_list(list_html, data_root)
            all_unit_numbers = {machine["machine_number"] for machine in machines}
            machines, rate_warnings = keep_standard_rate_machines(machines)
            business_date = started_at.date()
            pacer = RequestPacer(request, args.request_interval_ms)
            db_hall = hall_config["db_hall"]
            by_number, names = (
                load_db_names(Path(__file__).resolve().parents[2] / "db" / f"{db_hall}.db")
                if db_hall
                else ({}, sorted(name for name in master_names() if name))
            )
            for machine in machines:
                machine["machine_name_normalized"] = normalize_machine_name(machine, by_number, names)

            prior_machines = {row["machine_number"]: row for row in (prior or {}).get("machines", [])}
            prior_details = (
                (prior or {}).get("details", {})
                if (prior or {}).get("business_date") == business_date.isoformat()
                else {}
            )
            requested_units = set(args.units or [])
            if args.rb_quick_min_games is not None and args.mode == "quick":
                audit = load_audit()
                master_db = Path(__file__).resolve().parents[2] / "db" / f"{db_hall or 'ヒロキ東口店'}.db"
                master_flags = load_master_flags(master_db)
                eligible_units = set()
                for machine in machines:
                    number = machine["machine_number"]
                    model = machine.get("machine_name_normalized")
                    if not rb_eligible(args.snapshot_hall, model, audit, master_flags):
                        continue
                    old = prior_machines.get(number, {}) if prior_details else {}
                    detail = prior_details.get(number, {})
                    games = detail.get("games")
                    changed = (
                        any(machine.get(key) != old.get(key) for key in ("bb_count", "rb_count")) if old else False
                    )
                    if (games is not None and games >= args.rb_quick_min_games) or changed:
                        eligible_units.add(number)
                # --units は呼び出し側(realtime.run)が判別可能機種で選別済みなので、ここで絞り直さない。
            known_units = {row["machine_number"] for row in machines}
            excluded_requested = sorted(requested_units & (all_unit_numbers - known_units))
            requested_units.difference_update(excluded_requested)
            if excluded_requested:
                rate_warnings.append(f"低貸玉の指定台を対象外: {', '.join(excluded_requested)}")
            unknown_units = sorted(requested_units - known_units)
            if unknown_units:
                raise CollectionError(f"存在しない指定台です: {', '.join(unknown_units)}")

            details: dict[str, dict] = {}
            targets: list[dict] = []
            reused_detail_count = 0
            for machine in machines:
                number = machine["machine_number"]
                prior_detail = prior_details.get(number)
                can_reuse = not args.force and prior_detail and unchanged(machine, prior_machines.get(number))
                if args.mode == "full":
                    if can_reuse:
                        reused = dict(prior_detail)
                        reused["reused"] = True
                        reused["machine_name_normalized"] = normalize_machine_name(reused, by_number, names)
                        details[number] = reused
                        reused_detail_count += 1
                    else:
                        targets.append(machine)
                elif number in requested_units or (args.rb_quick_min_games is not None and number in eligible_units):
                    targets.append(machine)
                elif args.rb_quick_min_games is None and (
                    prior
                    and prior_details.get(number)
                    and (
                        machine.get("bb_count") != prior_machines.get(number, {}).get("bb_count")
                        or machine.get("rb_count") != prior_machines.get(number, {}).get("rb_count")
                    )
                ):
                    targets.append(machine)

            fresh_details, failures, model_links, model_pages, model_failures = await collect_details_then_models(
                pacer,
                targets,
                machines,
                data_root,
                business_date,
                graph_dir,
                args.workers,
            )
            failures.extend(model_failures)
            apply_model_games(
                machines,
                model_pages,
                model_links,
                business_date,
                failures,
                index_failed=any(item["stage"] == "model_index" for item in model_failures),
            )
            request_count += pacer.request_count
            rate_limit_events = pacer.rate_limit_events
            effective_interval_ms = pacer.effective_interval_ms
            details.update(fresh_details)
            for detail in fresh_details.values():
                detail["machine_name_normalized"] = normalize_machine_name(detail, by_number, names)
        finally:
            if context is not None:
                await context.close()
            if browser is not None:
                await browser.close()

    required_detail_count = len(machines) if args.mode == "full" else len(targets)
    successful_target_count = sum(number in details for number in {row["machine_number"] for row in targets})
    complete = (
        not failures
        and (args.mode != "full" or len(details) == len(machines))
        and successful_target_count == required_detail_count - reused_detail_count
    )
    failure_counts = {
        stage: sum(item.get("stage") == stage for item in failures) for stage in ("model_index", "model_page", "detail")
    }
    result = {
        "version": 1,
        "mode": args.mode,
        "hall_name": hall_config["data_hall_name"],
        "dmm_url": args.dmm_url,
        "data_root": data_root,
        "business_date": business_date.isoformat(),
        "observed_at": datetime.now(JST).isoformat(),
        "started_at": started_at.isoformat(),
        "complete": complete,
        "machine_count": len(machines),
        "detail_count": len(details),
        "reused_detail_count": reused_detail_count,
        "fresh_detail_count": len(fresh_details),
        "request_count": request_count,
        "workers": args.workers,
        "request_interval_ms": args.request_interval_ms,
        "effective_interval_ms": effective_interval_ms,
        "rate_limit_events": rate_limit_events,
        "requested_units": sorted(requested_units),
        "failures": failures,
        "warnings": rate_warnings,
        "failure_counts": failure_counts,
        "machines": machines,
        "details": details,
    }
    return result


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="DMM/Goraggioのスロット当日速報を手動取得する")
    parser.add_argument("--mode", choices=("quick", "full"), default="quick")
    parser.add_argument("--hall", choices=tuple(HALLS), default="max")
    parser.add_argument("--units", nargs="*", default=[])
    parser.add_argument("--rb-quick-min-games", type=int)
    parser.add_argument("--snapshot-hall", default="ヒロキMAX蒲田店")
    parser.add_argument("--workers", type=int, choices=range(1, 9), default=4)
    parser.add_argument("--request-interval-ms", type=int, default=2500)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--dmm-url")
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args(argv)
    _, args.dmm_url, args.output_dir = resolve_hall(args.hall, args.dmm_url, args.output_dir)
    return args


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")
    args = parse_args()
    if args.request_interval_ms < 0:
        raise SystemExit("--request-interval-ms は0以上にしてください")
    result = asyncio.run(run(args))
    output_path = args.output_dir / f"latest_{args.mode}.json"
    payload = json.dumps(result, ensure_ascii=False, indent=2)
    save_snapshot(result, args.output_dir, args.hall, payload)
    output_path.write_text(payload, encoding="utf-8")
    analysis = build_analysis(result)
    analysis_path = args.output_dir / "latest_analysis.json"
    report_path = args.output_dir / "mobile_report.html"
    analysis_path.write_text(json.dumps(analysis, ensure_ascii=False, indent=2), encoding="utf-8")
    report_path.write_text(build_html(analysis), encoding="utf-8")
    run_record = {
        key: result[key]
        for key in (
            "version",
            "mode",
            "business_date",
            "observed_at",
            "started_at",
            "complete",
            "machine_count",
            "detail_count",
            "reused_detail_count",
            "fresh_detail_count",
            "request_count",
            "workers",
            "request_interval_ms",
            "effective_interval_ms",
            "rate_limit_events",
            "failures",
            "warnings",
            "failure_counts",
        )
    }
    run_record["data_path"] = str(output_path)
    run_record["report_path"] = str(report_path)
    (args.output_dir / "latest_run.json").write_text(
        json.dumps(run_record, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(run_record, ensure_ascii=False))
    return 0 if result["complete"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
