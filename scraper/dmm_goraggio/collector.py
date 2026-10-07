from __future__ import annotations

import argparse
import asyncio
import json
import sqlite3
import sys
import time
import unicodedata
from contextlib import closing
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from playwright.async_api import APIRequestContext, Browser, BrowserContext, Playwright, async_playwright

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scraper.dmm_goraggio.parsing import (  # noqa: E402
    discover_data_url,
    find_device_warning,
    parse_detail,
    parse_machine_list,
)
from scraper.dmm_goraggio.report import build_analysis, build_html  # noqa: E402
from backtest.model_alias import master_names, resolve_part  # noqa: E402


HALLS = {
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
    request: APIRequestContext,
    targets: list[dict],
    business_date,
    graph_dir: Path,
    workers: int,
    request_interval_ms: int,
) -> tuple[dict[str, dict], list[dict], int, int, int]:
    queue: asyncio.Queue[dict] = asyncio.Queue()
    for target in targets:
        queue.put_nowait(target)
    details: dict[str, dict] = {}
    failures: list[dict] = []
    request_count = 0
    request_lock = asyncio.Lock()
    start_lock = asyncio.Lock()
    last_started = 0.0
    pause_until = 0.0
    effective_interval_ms = request_interval_ms
    rate_limit_events = 0
    graph_dir.mkdir(parents=True, exist_ok=True)

    async def fetch(target: dict) -> None:
        nonlocal request_count, last_started, pause_until, effective_interval_ms, rate_limit_events
        machine_number = target["machine_number"]
        html = None
        for attempt in range(3):
            async with start_lock:
                now = time.monotonic()
                start_at = max(pause_until, last_started + effective_interval_ms / 1000)
                wait_seconds = max(0.0, start_at - now)
                if wait_seconds:
                    await asyncio.sleep(wait_seconds)
                last_started = time.monotonic()
            response = await request.get(target["detail_url"], timeout=45_000)
            async with request_lock:
                request_count += 1
            try:
                html = await response_text(response, f"detail:{machine_number}")
                break
            except RateLimitError:
                async with start_lock:
                    rate_limit_events += 1
                    effective_interval_ms = max(effective_interval_ms, 2500)
                    pause_until = max(pause_until, time.monotonic() + 65)
                if attempt == 2:
                    raise
        if html is None:
            raise CollectionError(f"detail:{machine_number}: 応答本文を取得できません")
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
                failures.append({"machine_number": target["machine_number"], "error": str(exc)})
            finally:
                queue.task_done()

    await asyncio.gather(*(worker() for _ in range(workers)))
    return details, failures, request_count, rate_limit_events, effective_interval_ms


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
            db_hall = hall_config["db_hall"]
            by_number, names = (
                load_db_names(Path(__file__).resolve().parents[2] / "db" / f"{db_hall}.db")
                if db_hall
                else ({}, sorted(name for name in master_names() if name))
            )
            for machine in machines:
                machine["machine_name_normalized"] = normalize_machine_name(machine, by_number, names)

            business_date = started_at.date()
            prior_machines = {row["machine_number"]: row for row in (prior or {}).get("machines", [])}
            prior_details = (
                (prior or {}).get("details", {})
                if (prior or {}).get("business_date") == business_date.isoformat()
                else {}
            )
            requested_units = set(args.units or [])
            known_units = {row["machine_number"] for row in machines}
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
                elif number in requested_units:
                    targets.append(machine)
                elif (
                    prior
                    and prior_details.get(number)
                    and (
                        machine.get("bb_count") != prior_machines.get(number, {}).get("bb_count")
                        or machine.get("rb_count") != prior_machines.get(number, {}).get("rb_count")
                    )
                ):
                    targets.append(machine)

            fresh_details, failures, detail_requests, rate_limit_events, effective_interval_ms = await collect_details(
                request,
                targets,
                business_date,
                graph_dir,
                args.workers,
                args.request_interval_ms,
            )
            request_count += detail_requests
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
        "machines": machines,
        "details": details,
    }
    return result


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="DMM/Goraggioのスロット当日速報を手動取得する")
    parser.add_argument("--mode", choices=("quick", "full"), default="quick")
    parser.add_argument("--hall", choices=tuple(HALLS), default="max")
    parser.add_argument("--units", nargs="*", default=[])
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
