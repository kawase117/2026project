from __future__ import annotations

import re
from datetime import date
from html import unescape
from urllib.parse import urljoin, urlparse, parse_qs

from bs4 import BeautifulSoup, Tag


DEVICE_WARNING_PATTERNS = (
    "この端末では接続できません",
    "この端末からは接続できません",
    "スマートフォンからアクセスしてください",
    "スマートフォン専用",
)


def compact_text(value: str | None) -> str:
    return re.sub(r"\s+", " ", unescape(value or "")).strip()


def parse_int(value: str | None) -> int | None:
    text = compact_text(value).replace(",", "")
    match = re.search(r"-?\d+", text)
    return int(match.group()) if match else None


def parse_float(value: str | None) -> float | None:
    text = compact_text(value).replace(",", "")
    match = re.search(r"-?\d+(?:\.\d+)?", text)
    return float(match.group()) if match else None


def find_device_warning(text: str) -> str | None:
    normalized = compact_text(text)
    return next((pattern for pattern in DEVICE_WARNING_PATTERNS if pattern in normalized), None)


def discover_data_url(dmm_html: str) -> str:
    warning = find_device_warning(dmm_html)
    if warning:
        raise ValueError(f"端末警告を検知しました: {warning}")
    patterns = (
        r"iframe\.src\s*=\s*['\"](https://daidata\.goraggio\.com/[^'\"]+)['\"]",
        r"<iframe[^>]+src=['\"](https://daidata\.goraggio\.com/[^'\"]+)['\"]",
    )
    for pattern in patterns:
        match = re.search(pattern, dmm_html, re.IGNORECASE)
        if match:
            return unescape(match.group(1)).rstrip("/")
    raise ValueError("DMM店舗ページから台データURLを検出できません")


def parse_machine_list(html: str, source_url: str) -> list[dict]:
    warning = find_device_warning(html)
    if warning:
        raise ValueError(f"端末警告を検知しました: {warning}")
    soup = BeautifulSoup(html, "html.parser")
    target_table = None
    header_names: list[str] = []
    for table in soup.find_all("table"):
        headers = [compact_text(cell.get_text(" ", strip=True)) for cell in table.select("thead th")]
        if "台番号" in headers and "機種名" in headers:
            target_table = table
            header_names = headers
            break
    if target_table is None:
        raise ValueError("スロット台番号一覧テーブルが見つかりません")

    index = {name: position for position, name in enumerate(header_names)}
    required = ("台番号", "機種名", "BB回数", "RB回数", "前日最終スタート", "スタート回数")
    missing = [name for name in required if name not in index]
    if missing:
        raise ValueError(f"台番号一覧の必須列がありません: {', '.join(missing)}")

    machines: list[dict] = []
    seen: set[str] = set()
    for row in target_table.select("tbody tr"):
        cells = row.find_all("td", recursive=False)
        if len(cells) < len(header_names):
            continue
        values = [compact_text(cell.get_text(" ", strip=True)) for cell in cells]
        machine_number = values[index["台番号"]]
        if not machine_number.isdigit() or machine_number in seen:
            continue
        link = cells[index["台番号"]].find("a", href=True)
        detail_url = (
            urljoin(source_url, link["href"]) if link else urljoin(source_url + "/", f"detail?unit={machine_number}")
        )
        seen.add(machine_number)
        machines.append(
            {
                "machine_number": machine_number,
                "rate": values[index["貸玉"]] if "貸玉" in index else None,
                "machine_name": values[index["機種名"]],
                "bb_count": parse_int(values[index["BB回数"]]),
                "rb_count": parse_int(values[index["RB回数"]]),
                "previous_final_start": parse_int(values[index["前日最終スタート"]]),
                "current_start": parse_int(values[index["スタート回数"]]),
                "detail_url": detail_url,
            }
        )
    if not machines:
        raise ValueError("スロット台一覧が0件です")
    return machines


def _table_mapping(table: Tag | None) -> dict[str, str]:
    result: dict[str, str] = {}
    if table is None:
        return result
    for row in table.find_all("tr", recursive=False):
        cells = row.find_all(["th", "td"], recursive=False)
        if len(cells) == 2:
            result[compact_text(cells[0].get_text(" ", strip=True))] = compact_text(cells[1].get_text(" ", strip=True))
        elif len(cells) >= 4:
            for offset in range(0, len(cells) - 1, 2):
                result[compact_text(cells[offset].get_text(" ", strip=True))] = compact_text(
                    cells[offset + 1].get_text(" ", strip=True)
                )
    return result


def _overview_mapping(table: Tag | None) -> dict[str, str]:
    if table is None:
        return {}
    rows = table.find_all("tr", recursive=False)
    if len(rows) < 2:
        return {}
    headers = [compact_text(cell.get_text(" ", strip=True)) for cell in rows[0].find_all(["th", "td"], recursive=False)]
    values = [compact_text(cell.get_text(" ", strip=True)) for cell in rows[1].find_all(["th", "td"], recursive=False)]
    return dict(zip(headers, values, strict=False))


def _slide_date(slide: Tag, expected_date: date) -> str | None:
    heading = slide.select_one("h4.Text-Left-01")
    if heading is None:
        return None
    match = re.search(r"(\d{1,2})月(\d{1,2})日", compact_text(heading.get_text(" ", strip=True)))
    if not match:
        return None
    month, day = map(int, match.groups())
    year = expected_date.year
    if expected_date.month == 1 and month == 12:
        year -= 1
    return f"{year:04d}-{month:02d}-{day:02d}"


def sanitize_svg(svg: Tag | None) -> str | None:
    if svg is None:
        return None
    for tag in svg.find_all(["script", "foreignObject"]):
        tag.decompose()
    for tag in [svg, *svg.find_all(True)]:
        for attribute in list(tag.attrs):
            if attribute.lower().startswith("on"):
                del tag.attrs[attribute]
    return str(svg)


def estimate_latest_diff(svg: Tag | None) -> int | None:
    if svg is None:
        return None
    path = next(
        (
            item
            for item in svg.find_all("path")
            if compact_text(str(item.get("stroke"))).lower() in {"#ff0000", "red"} and item.get("d")
        ),
        None,
    )
    if path is None:
        return None
    coordinates = re.findall(r"(-?\d+(?:\.\d+)?),(-?\d+(?:\.\d+)?)", str(path.get("d")))
    if not coordinates:
        return None
    endpoint_y = float(coordinates[-1][1])

    axis: list[tuple[float, float]] = []
    for text in svg.find_all("text"):
        if str(text.get("x")) != "5" or text.get("y") is None:
            continue
        label = compact_text(text.get_text(" ", strip=True)).replace(",", "")
        if not re.fullmatch(r"-?\d+", label):
            continue
        axis.append((float(text["y"]) + 10.0, float(label)))
    unique_axis = sorted(set(axis))
    zero_points = [point for point in unique_axis if point[1] == 0]
    if not zero_points:
        return None
    zero = zero_points[0]
    if endpoint_y >= zero[0]:
        side = [point for point in unique_axis if point[1] < 0 and point[0] > zero[0]]
        anchor = max(side, default=None, key=lambda point: point[0])
    else:
        side = [point for point in unique_axis if point[1] > 0 and point[0] < zero[0]]
        anchor = min(side, default=None, key=lambda point: point[0])
    if anchor is None:
        return None
    (y1, value1), (y2, value2) = zero, anchor
    if y1 == y2:
        return None
    estimate = value1 + (endpoint_y - y1) * (value2 - value1) / (y2 - y1)
    return int(round(estimate))


def parse_detail(html: str, expected_date: date, expected_machine_number: str | None = None) -> tuple[dict, str | None]:
    warning = find_device_warning(html)
    if warning:
        raise ValueError(f"端末警告を検知しました: {warning}")
    soup = BeautifulSoup(html, "html.parser")
    header = soup.select_one("article #contentsHeader")
    if header is None:
        raise ValueError("台詳細ヘッダーが見つかりません")
    header_text = compact_text(header.get_text(" ", strip=True))
    number_match = re.search(r"(\d+)番台", header_text)
    machine_number = number_match.group(1) if number_match else expected_machine_number
    if expected_machine_number and machine_number != expected_machine_number:
        raise ValueError(f"台番号が一致しません: expected={expected_machine_number}, actual={machine_number}")
    machine_name_node = header.find("h2")
    machine_name = compact_text(machine_name_node.get_text(" ", strip=True)) if machine_name_node else None
    source_updated_at = (
        compact_text(header.select_one(".suppleMeta time").get_text(" ", strip=True))
        if header.select_one(".suppleMeta time")
        else None
    )

    overview_slide = None
    business_date = None
    for slide in soup.select("div.swiper-slide"):
        if slide.select_one("table.overviewTable") is None:
            continue
        slide_date = _slide_date(slide, expected_date)
        if slide_date == expected_date.isoformat():
            overview_slide = slide
            business_date = slide_date
            break
    if overview_slide is None:
        raise ValueError(f"当日概要が見つかりません: {expected_date.isoformat()}")

    overview = _overview_mapping(overview_slide.select_one("table.overviewTable"))
    metrics = _table_mapping(overview_slide.select_one("table.overviewTable3"))

    histories: list[dict] = []
    history_container = soup.select_one("#list")
    if history_container is not None:
        for slide in history_container.select("div.swiper-slide"):
            if _slide_date(slide, expected_date) != expected_date.isoformat():
                continue
            table = slide.select_one("table.numericValueTable")
            if table is None:
                break
            rows = table.find_all("tr")
            for row in rows[1:]:
                cells = [
                    compact_text(cell.get_text(" ", strip=True)) for cell in row.find_all(["th", "td"], recursive=False)
                ]
                if len(cells) < 5:
                    continue
                histories.append(
                    {
                        "jackpot_number": parse_int(cells[0]),
                        "start": parse_int(cells[1]),
                        "payout": parse_int(cells[2]),
                        "kind": cells[3],
                        "time": cells[4],
                    }
                )
            break

    svg = soup.select_one("#today_graph svg")
    graph_svg = sanitize_svg(svg)
    detail = {
        "machine_number": machine_number,
        "machine_name": machine_name,
        "business_date": business_date,
        "source_updated_at": source_updated_at,
        "bb_count": parse_int(overview.get("BB")),
        "rb_count": parse_int(overview.get("RB")),
        "current_start": parse_int(overview.get("スタート回数")),
        "max_payout": parse_int(metrics.get("最大持ち玉")),
        "games": parse_int(metrics.get("累計スタート")),
        "previous_final_start": parse_int(metrics.get("前日最終スタート")),
        "combined_probability": parse_float(metrics.get("合成確率")),
        "bb_probability": parse_float(metrics.get("BB確率")),
        "rb_probability": parse_float(metrics.get("RB確率")),
        "latest_diff_estimated": estimate_latest_diff(svg),
        "latest_diff_method": "svg_axis_linear_estimate" if svg is not None else None,
        "history": histories,
    }
    return detail, graph_svg


def unit_from_url(url: str) -> str | None:
    values = parse_qs(urlparse(url).query).get("unit")
    return values[0] if values else None
