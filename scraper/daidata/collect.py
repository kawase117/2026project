"""ダイデータオンライン みとや大森町店(101309)の当日スロット収集。

仕様は .claude/skills/daidata-mitoya-daily/SKILL.md。21.3円スロットのみ。
全機種の取得と検算が通るまで最終CSVを書かない。429/403/台数不一致/列ずれで停止する。
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup

STORE_ID = "101309"
BASE = f"https://daidata.goraggio.com/{STORE_ID}"
PRICE = "21.30"
JST = ZoneInfo("Asia/Tokyo")
INTERVAL_SECONDS = 3.0
UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 18_6 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.6 Mobile/15E148 Safari/604.1"
)
OUTPUT_DIR = Path(__file__).resolve().parent / "output"
COLUMNS = [
    "BusinessDate",
    "ObservedAt",
    "Price",
    "Machine",
    "Unit",
    "CumulativeStart",
    "BBCount",
    "RBCount",
    "MaxPayout",
    "BBProbability",
    "RBProbability",
    "CombinedProbability",
    "PreviousFinalStart",
    "StartCount",
]
HEADERS = [
    "",
    "台番号",
    "累計スタート",
    "BB回数",
    "RB回数",
    "最大持ち玉",
    "BB確率",
    "RB確率",
    "合成確率",
    "前日最終スタート",
    "スタート回数",
]


class CollectError(RuntimeError):
    pass


class RateLimited(CollectError):
    pass


def _text(node) -> str:
    return re.sub(r"\s+", " ", node.get_text(" ", strip=True)).strip()


def parse_model_links(html: str) -> list[dict]:
    """機種一覧ページから (機種名, 台数, URL)。"""
    soup = BeautifulSoup(html, "html.parser")
    models = []
    for a in soup.find_all("a", href=re.compile(r"unit_list")):
        href = a["href"]
        if f"ballPrice={PRICE}" not in href:
            continue
        label = _text(a)
        m = re.match(r"(.+?)\s*21\.3円スロット\s*\|?\s*(\d+)台", label)
        if not m:
            raise CollectError(f"機種リンクの表記を解釈できません: {label!r}")
        models.append({"machine": m.group(1).strip(), "count": int(m.group(2)), "url": urljoin(BASE + "/", href)})
    if not models:
        raise CollectError("21.3円の機種リンクが0件です")
    return models


def parse_updated_at(html: str) -> tuple[str, str]:
    """ページの『YYYY.MM.DD HH:MM』更新表記 → (日付ISO, 'HH:MM')。"""
    m = re.search(r"(\d{4})\.(\d{2})\.(\d{2})\s+(\d{1,2}:\d{2})", _text(BeautifulSoup(html, "html.parser")))
    if not m:
        raise CollectError("ページの更新日時を取得できません")
    return f"{m.group(1)}-{m.group(2)}-{m.group(3)}", m.group(4)


def parse_unit_table(html: str, model: dict) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    table = next((t for t in soup.find_all("table") if "台番号" in [_text(th) for th in t.select("th")]), None)
    if table is None:
        raise CollectError(f"{model['machine']}: 台番号表がありません(同意画面の可能性)")
    headers = [_text(th) for th in table.select("th")]
    if headers != HEADERS:
        raise CollectError(f"{model['machine']}: 列構造が想定と違います {headers}")
    rows = []
    for tr in table.select("tr"):
        cells = tr.find_all("td", recursive=False)
        if not cells:
            continue
        if len(cells) != len(HEADERS):
            raise CollectError(f"{model['machine']}: セル数{len(cells)}が想定{len(HEADERS)}と違います")
        vals = [_text(c) for c in cells]
        link = tr.find("a", href=re.compile(r"detail\?unit="))
        unit_from_link = re.search(r"unit=(\d+)", link["href"]).group(1) if link else None
        if not vals[1].isdigit() or unit_from_link != vals[1]:
            raise CollectError(f"{model['machine']}: 台番号がリンクと一致しません {vals[1]} vs {unit_from_link}")
        rows.append(
            dict(
                zip(
                    [
                        "Unit",
                        "CumulativeStart",
                        "BBCount",
                        "RBCount",
                        "MaxPayout",
                        "BBProbability",
                        "RBProbability",
                        "CombinedProbability",
                        "PreviousFinalStart",
                        "StartCount",
                    ],
                    vals[1:],
                    strict=True,
                )
            )
        )
    if len(rows) != model["count"]:
        raise CollectError(f"{model['machine']}: 台数不一致 表示{model['count']} 取得{len(rows)}")
    return rows


class Session:
    def __init__(self) -> None:
        self.s = requests.Session()
        self.s.headers["User-Agent"] = UA
        self.last = 0.0

    def _wait(self) -> None:
        gap = INTERVAL_SECONDS - (time.monotonic() - self.last)
        if gap > 0:
            time.sleep(gap)
        self.last = time.monotonic()

    def _check(self, r: requests.Response, stage: str) -> str:
        if r.status_code == 429:
            raise RateLimited(f"{stage}: HTTP 429")
        if r.status_code == 403:
            raise CollectError(f"{stage}: HTTP 403")
        if not r.ok:
            raise CollectError(f"{stage}: HTTP {r.status_code}")
        r.encoding = "utf-8"
        return r.text

    def get(self, url: str, stage: str) -> str:
        # 接続系の失敗だけ10秒空けて1回再試行する。429/403は再試行しない。
        for attempt in (1, 2):
            self._wait()
            try:
                return self._check(self.s.get(url, timeout=60), stage)
            except requests.RequestException as e:
                if attempt == 2:
                    raise CollectError(f"{stage}: 通信失敗 {type(e).__name__}") from e
                time.sleep(10)
        raise AssertionError("unreachable")

    def accept_terms(self, html: str, referer: str) -> str:
        """同意画面の通常フォームを送る(ユーザー承認済み)。セッションごとに1回で足りる。"""
        tok = BeautifulSoup(html, "html.parser").find("input", {"name": "_token"})
        if tok is None:
            raise CollectError("同意フォームのトークンがありません")
        self._wait()
        r = self.s.post(f"{BASE}/accept", data={"_token": tok["value"]}, headers={"Referer": referer}, timeout=30)
        return self._check(r, "accept")


def collect() -> tuple[list[dict], dict]:
    sess = Session()
    started = datetime.now(JST)
    sess.get(f"{BASE}/ballPriceList?ps=S", "ballPriceList")
    list_html = sess.get(f"{BASE}/list?mode=psModelNameSearch&ballPrice={PRICE}&ps=S", "modelList")
    models = parse_model_links(list_html)
    list_date, _ = parse_updated_at(list_html)
    today = started.date().isoformat()
    if list_date != today:
        raise CollectError(f"ページ日付{list_date}が今日{today}と一致しません")
    expected = sum(m["count"] for m in models)
    print(f"機種{len(models)} 台数{expected}")

    rows: list[dict] = []
    seen_updates: list[str] = []
    accepted = False
    for i, model in enumerate(models, 1):
        html = sess.get(model["url"], model["machine"])
        if "利用規約に同意する" in html:
            if accepted:
                raise CollectError(f"{model['machine']}: 同意画面が繰り返し表示されました")
            html = sess.accept_terms(html, model["url"])
            accepted = True
        page_date, page_time = parse_updated_at(html)
        if page_date != today:
            raise CollectError(f"{model['machine']}: ページ日付{page_date}が今日と不一致")
        seen_updates.append(page_time)
        for r in parse_unit_table(html, model):
            r["Machine"] = model["machine"]
            rows.append(r)
        print(f"[{i}/{len(models)}] {model['machine']} {model['count']}台", flush=True)

    units = [r["Unit"] for r in rows]
    if len(units) != len(set(units)):
        raise CollectError("台番号が重複しています")
    if len(rows) != expected:
        raise CollectError(f"総台数不一致 一覧{expected} 取得{len(rows)}")
    ended = datetime.now(JST)
    meta = {
        "business_date": today,
        "observed_at": ended.isoformat(timespec="seconds"),
        "started_at": started.isoformat(timespec="seconds"),
        "page_update_first": min(seen_updates),
        "page_update_last": max(seen_updates),
        "models": len(models),
        "units": len(rows),
    }
    for r in rows:
        r["BusinessDate"] = today
        r["ObservedAt"] = meta["observed_at"]
        r["Price"] = "21.3"
    return rows, meta


def write_csv(rows: list[dict], meta: dict, out_dir: Path = OUTPUT_DIR) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"mitoya_omorimachi_slots_21.3yen_{meta['business_date']}.csv"
    if path.exists():
        stamp = datetime.fromisoformat(meta["observed_at"]).strftime("%H%M%S")
        path = out_dir / f"mitoya_omorimachi_slots_21.3yen_{meta['business_date']}_{stamp}.csv"
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        w.writeheader()
        w.writerows(rows)
    return path


def main() -> int:
    argparse.ArgumentParser(description=__doc__).parse_args()
    try:
        rows, meta = collect()
    except RateLimited as e:
        print(f"STOP(429): {e}", file=sys.stderr)
        return 2
    except CollectError as e:
        print(f"STOP: {e}", file=sys.stderr)
        return 1
    path = write_csv(rows, meta)
    print(f"CSV: {path}")
    print(meta)
    return 0


if __name__ == "__main__":
    sys.exit(main())
