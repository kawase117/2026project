import asyncio
import json
import sqlite3
import tempfile
from datetime import date
from pathlib import Path
from urllib.parse import quote

import pytest

from scraper.dmm_goraggio.collector import (
    CollectionError,
    check_hall_name,
    load_db_names,
    load_prior,
    normalize_machine_name,
    parse_args,
    save_snapshot,
    parse_model_links,
    parse_ball_price_links,
    parse_model_page,
    apply_model_games,
    select_model_links,
    discover_model_links,
    collect_details_then_models,
    collect_model_pages,
    failure_info,
    keep_standard_rate_machines,
)


def test_full_cache_is_preferred_even_when_quick_is_newer() -> None:
    with tempfile.TemporaryDirectory() as directory:
        temp_path = Path(directory)
        full = temp_path / "latest_full.json"
        quick = temp_path / "latest_quick.json"
        full.write_text(json.dumps({"mode": "full", "details": {"1001": {}}}), encoding="utf-8")
        quick.write_text(json.dumps({"mode": "quick", "details": {}}), encoding="utf-8")
        assert load_prior(temp_path, "full")["mode"] == "full"


def test_hall_settings_and_overrides(tmp_path: Path) -> None:
    default = parse_args([])
    assert default.hall == "max"
    assert default.dmm_url.endswith("/265/jackpot")
    assert default.output_dir.name == "output"

    east = parse_args(["--hall", "higashiguchi"])
    assert east.dmm_url.endswith("/255/jackpot")
    assert east.output_dir.name == "output_higashiguchi"

    from scraper.dmm_goraggio.collector import HALLS

    assert HALLS["higashiguchi"]["db_hall"] == "ヒロキ東口店"
    override = parse_args(
        ["--hall", "higashiguchi", "--dmm-url", "https://example.test", "--output-dir", str(tmp_path)]
    )
    assert override.dmm_url == "https://example.test"
    assert override.output_dir == tmp_path


def test_hall_name_guard_rejects_other_hall() -> None:
    max_html = "<title>ヒロキMAX蒲田店 - 台データオンライン</title>"
    east_html = "<title>ヒロキ東口店 - 台データオンライン</title>"
    check_hall_name(max_html, "ヒロキMAX蒲田店")
    check_hall_name(east_html, "ヒロキ東口店")
    with pytest.raises(CollectionError, match="取得先ホール名が一致しません"):
        check_hall_name(max_html, "ヒロキ東口店")
    with pytest.raises(CollectionError, match="取得先ホール名が一致しません"):
        check_hall_name(east_html, "ヒロキMAX蒲田店")


def test_machine_name_from_latest_db_date_then_alias(tmp_path: Path) -> None:
    db_path = tmp_path / "hall.db"
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            "CREATE TABLE machine_detailed_results (date TEXT, machine_number INTEGER, machine_name TEXT)"
        )
        connection.executemany(
            "INSERT INTO machine_detailed_results VALUES (?, ?, ?)",
            [
                ("20261001", 1001, "旧機種"),
                ("20261006", 1001, "マイジャグラーV"),
                ("20261005", 1002, "スマスロ北斗の拳"),
            ],
        )
    by_number, names = load_db_names(db_path)
    assert (
        normalize_machine_name({"machine_number": "1001", "machine_name": "別表記"}, by_number, names)
        == "マイジャグラーV"
    )
    assert (
        normalize_machine_name({"machine_number": "9999", "machine_name": "ﾏｲｼﾞｬｸﾞﾗｰV"}, by_number, names)
        == "マイジャグラーV"
    )
    assert normalize_machine_name({"machine_number": "bad", "machine_name": "不明機種"}, by_number, names) is None


def test_missing_db_continues_with_null(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    by_number, names = load_db_names(tmp_path / "missing.db")
    assert "警告" in capsys.readouterr().err
    assert normalize_machine_name({"machine_number": "1001", "machine_name": "ﾏｲｼﾞｬｸﾞﾗｰV"}, by_number, names) is None


def test_snapshot_path_and_no_overwrite(tmp_path: Path) -> None:
    result = {"mode": "quick", "observed_at": "2026-10-07T12:34:56+09:00"}
    payload = json.dumps(result)
    path = save_snapshot(result, tmp_path, "higashiguchi", payload)
    assert path == tmp_path / "snapshots" / "higashiguchi_quick_20261007_123456.json"
    assert path.read_text(encoding="utf-8") == payload
    with pytest.raises(FileExistsError):
        save_snapshot(result, tmp_path, "higashiguchi", "changed")
    assert path.read_text(encoding="utf-8") == payload


def test_model_page_links_and_games_with_gaps_and_raw_spaces() -> None:
    model = "1F L　ｽﾏｽﾛ ﾘｺﾘｽ･ﾘｺｲﾙ KX"
    root = "https://daidata.goraggio.com/dedamajyoho-P-townDMMpachi/101426"
    href = f"/dedamajyoho-P-townDMMpachi/101426/unit_list?model={quote(model)}&ballPrice=21.74&ps=S"
    links = parse_model_links(f'<a href="{href}">model</a>', root)
    assert links == [(model, "21.74", root + "/unit_list?model=" + quote(model) + "&ballPrice=21.74&ps=S")]
    html = """
    <div class="swiper-slide"><h4 class="Text-Left-01">10月20日</h4></div>
    <table><thead><tr><th>台番号</th><th>累計スタート</th><th>BB回数</th></tr></thead>
    <tbody><tr><td>1001</td><td>1,234</td><td>0</td></tr>
    <tr><td>1003</td><td>--</td><td>0</td></tr>
    <tr><td>1005</td><td></td><td>0</td></tr>
    <tr><td>1008</td><td>0</td><td>0</td></tr></tbody></table>
    """
    page_date, units = parse_model_page(html, date(2026, 10, 20))
    assert page_date == date(2026, 10, 20)
    assert units == {"1001": 1234, "1003": None, "1005": None, "1008": 0}
    machines = [{"machine_name": model, "machine_number": number} for number in ("1001", "1002", "1008")]
    failures = []
    apply_model_games(machines, {(model, "21.74"): (page_date, units)}, links, date(2026, 10, 20), failures)
    assert [row["total_games"] for row in machines] == [1234, None, 0]
    assert "ballPrice mismatch" in failures[0]["error"]


def test_model_date_mismatch_keeps_games_missing_and_records_failure() -> None:
    html = """
    <div class="swiper-slide"><h4 class="Text-Left-01">2026/10/19</h4></div>
    <table><thead><tr><th>台番号</th><th>累計スタート</th></tr></thead>
    <tbody><tr><td>1001</td><td>2345</td></tr></tbody></table>
    """
    page = parse_model_page(html, date(2026, 10, 20))
    machines = [{"machine_name": "AT", "machine_number": "1001"}]
    failures = []
    apply_model_games(machines, {("AT", "21.74"): page}, [("AT", "21.74", "url")], date(2026, 10, 20), failures)
    assert machines[0]["total_games"] is None
    assert "営業日不一致" in failures[0]["error"]


@pytest.mark.parametrize(
    "shop_id,prices",
    [
        ("101425", ("21.70", "5.40")),
        ("101424", ("21.74",)),
    ],
)
def test_discovers_all_slot_ball_prices_from_index(shop_id: str, prices: tuple[str, ...]) -> None:
    root = f"https://daidata.goraggio.com/dedamajyoho-P-townDMMpachi/{shop_id}"
    html = "".join(
        f'<a href="/dedamajyoho-P-townDMMpachi/{shop_id}/list?mode=psModelNameSearch&amp;ps=S&amp;ballPrice={price}">{price}</a>'
        for price in prices
    )
    links = parse_ball_price_links(html, root)
    assert [price for price, _ in links] == list(prices)
    assert all(f"ballPrice={price}" in url for price, url in links)
    query_only = f'<a href="?mode=psModelNameSearch&amp;ps=S&amp;ballPrice={prices[0]}">rate</a>'
    assert parse_ball_price_links(query_only, root) == [
        (prices[0], root + f"/list?mode=psModelNameSearch&ps=S&ballPrice={prices[0]}")
    ]


@pytest.mark.parametrize(
    "shop_id,prices",
    [
        ("101425", ("21.70", "5.40")),
        ("101424", ("21.74",)),
    ],
)
def test_fetches_each_discovered_ball_price_index(shop_id: str, prices: tuple[str, ...]) -> None:
    root = f"https://daidata.goraggio.com/dedamajyoho-P-townDMMpachi/{shop_id}"
    index_url = root + "/list?mode=psModelNameSearch&ps=S"
    index_html = "".join(
        f'<a href="{root}/list?mode=psModelNameSearch&amp;ps=S&amp;ballPrice={price}">{price}</a>' for price in prices
    )
    html_by_url = {index_url: index_html}
    machines = []
    for i, price in enumerate(prices):
        model = f"model{i}"
        machines.append({"machine_name": model, "machine_number": str(1000 + i), "rate": f"{price}円スロット"})
        html_by_url[root + f"/list?mode=psModelNameSearch&ps=S&ballPrice={price}"] = (
            f'<a href="{root}/unit_list?model={model}&amp;ballPrice={price}&amp;ps=S">{model}</a>'
        )

    class FakePacer:
        def __init__(self):
            self.urls = []

        async def get(self, url, stage):
            self.urls.append(url)
            return html_by_url[url]

    pacer = FakePacer()
    machines, warnings = keep_standard_rate_machines(machines)
    assert warnings == []
    links, failures = asyncio.run(discover_model_links(pacer, root, machines))
    assert failures == []
    standard_prices = [price for price in prices if float(price) >= 10]
    assert pacer.urls == [index_url] + [
        root + f"/list?mode=psModelNameSearch&ps=S&ballPrice={p}" for p in standard_prices
    ]
    assert {(model, price) for model, price, _ in links} == {
        (f"model{i}", p) for i, p in enumerate(prices) if p in standard_prices
    }


def test_low_rate_units_removed_but_nishiguchi_coin_label_retained() -> None:
    machines = [
        {"machine_number": "1001", "rate": "21.7円スロット"},
        {"machine_number": "1002", "rate": "21.74円スロット"},
        {"machine_number": "1003", "rate": "5.4円スロット"},
        {"machine_number": "1004", "rate": "46枚/1000円 SLOT"},
        {"machine_number": "1005", "rate": "不明"},
    ]
    kept, warnings = keep_standard_rate_machines(machines)
    assert [item["machine_number"] for item in kept] == ["1001", "1002", "1004", "1005"]
    assert len(kept) == 4
    assert warnings == ["貸玉レートを換算できません。対象に保持: 不明"]


def test_higashiguchi_low_rate_model_page_is_never_requested(tmp_path: Path) -> None:
    root = "https://daidata.goraggio.com/dedamajyoho-P-townDMMpachi/101425"
    index_url = root + "/list?mode=psModelNameSearch&ps=S"
    high_index = index_url + "&ballPrice=21.70"
    low_index = index_url + "&ballPrice=5.40"
    high_model = root + "/unit_list?model=High&ballPrice=21.70&ps=S"
    low_model = root + "/unit_list?model=Low&ballPrice=5.40&ps=S"
    responses = {
        index_url: f'<a href="{high_index}">21.70</a><a href="{low_index}">5.40</a>',
        high_index: f'<a href="{high_model}">High</a>',
        high_model: '''<select name="hist_num"><option value="0" selected>2026-10-21</option></select>
            <table><thead><tr><th>台番号</th><th>累計スタート</th></tr></thead>
            <tbody><tr><td>1001</td><td>1234</td></tr></tbody></table>''',
    }

    class FakePacer:
        def __init__(self):
            self.urls = []
            self.request_count = 0
            self.rate_limit_events = 0
            self.effective_interval_ms = 0

        async def get(self, url, stage):
            self.urls.append(url)
            self.request_count += 1
            return responses[url]  # low_index and low_model are intentionally absent

    machines, warnings = keep_standard_rate_machines(
        [
            {"machine_number": "1001", "machine_name": "High", "rate": "21.7円スロット"},
            {"machine_number": "5001", "machine_name": "Low", "rate": "5.4円スロット"},
        ]
    )
    assert warnings == [] and len(machines) == 1
    pacer = FakePacer()
    _, detail_failures, links, pages, model_failures = asyncio.run(
        collect_details_then_models(pacer, [], machines, root, date(2026, 10, 21), tmp_path / "graphs", 1)
    )
    assert pacer.urls == [index_url, high_index, high_model]
    assert detail_failures == [] and model_failures == []
    assert len(links) == 1 and set(pages) == {("High", "21.70")}


@pytest.mark.parametrize(
    "model,raw_suffix",
    [
        ("ひぐらしのなく頃に祭2", " "),
        ("L 聖闘士星矢 海皇覚醒", "　"),
        ("1F　L ｽﾏｽﾛ", " "),
    ],
)
def test_model_link_trailing_whitespace_joins_without_changing_href(model: str, raw_suffix: str) -> None:
    root = "https://daidata.goraggio.com/dedamajyoho-P-townDMMpachi/101426"
    raw_model = model + raw_suffix
    href = f"{root}/unit_list?model={quote(raw_model)}&ballPrice=21.74&ps=S"
    links = parse_model_links(f'<a href="{href}">model</a>', root)
    machine = {"machine_name": model, "machine_number": "1001", "rate": "21.74円スロット"}
    selected = select_model_links([machine], links)
    assert selected == [(raw_model, "21.74", href)]
    page_html = '''<select name="hist_num"><option value="0" selected>2026-10-21</option></select>
        <table><thead><tr><th>台番号</th><th>累計スタート</th></tr></thead>
        <tbody><tr><td>1001</td><td>1234</td></tr></tbody></table>'''

    class FakePacer:
        async def get(self, url, stage):
            assert url == href
            return page_html

    fetched_pages, fetch_failures = asyncio.run(collect_model_pages(FakePacer(), selected, 1, date(2026, 10, 21)))
    assert fetch_failures == []
    failures = []
    apply_model_games([machine], fetched_pages, selected, date(2026, 10, 21), failures)
    assert machine["total_games"] == 1234
    assert failures == []


def test_same_model_prefers_rate_then_joins_units_when_rate_unknown() -> None:
    root = "https://daidata.goraggio.com/dedamajyoho-P-townDMMpachi/101425"
    model = "L テスト　AT"
    indexes = [
        f'<a href="/dedamajyoho-P-townDMMpachi/101425/unit_list?model={quote(model)}&amp;ballPrice={price}&amp;ps=S">{model}</a>'
        for price in ("21.70", "5.40")
    ]
    links = [link for html in indexes for link in parse_model_links(html, root)]
    day = date(2026, 10, 20)
    pages = {
        (model, "21.70"): (day, {"1001": 1234}),
        (model, "5.40"): (day, {"5001": 567}),
    }
    machines = [
        {"machine_name": model, "machine_number": "1001", "rate": "21.70円スロット"},
        {"machine_name": model, "machine_number": "5001", "rate": "5.40円スロット"},
    ]
    assert {(model, price) for model, price, _ in select_model_links(machines, links)} == set(pages)
    failures = []
    apply_model_games(machines, pages, links, day, failures)
    assert [item["total_games"] for item in machines] == [1234, 567]
    assert failures == []
    unknown_rate = [{"machine_name": model, "machine_number": "5001", "rate": "46枚/1000円 SLOT"}]
    assert len(select_model_links(unknown_rate, links)) == 2
    apply_model_games(unknown_rate, pages, links, day, failures)
    assert unknown_rate[0]["total_games"] == 567
    assert failures == []


def test_model_join_failures_have_distinct_reasons() -> None:
    day = date(2026, 10, 20)
    links = [("WrongPrice", "21.70", "url"), ("FetchFailed", "5.40", "url")]
    machines = [{"machine_name": name, "machine_number": "1001"} for name in ("NotListed", "WrongPrice", "FetchFailed")]
    failures = [{"model": "FetchFailed", "ballPrice": "5.40", "error": "fetch failure: HTTP 503"}]
    apply_model_games(machines, {("WrongPrice", "21.70"): (day, {"9001": 10})}, links, day, failures)
    reasons = {item["model"]: item["error"] for item in failures if "model" in item}
    assert "not in list" in reasons["NotListed"]
    assert "ballPrice mismatch" in reasons["WrongPrice"]
    assert "fetch failure" in reasons["FetchFailed"]
    assert all(item["total_games"] is None for item in machines)


def test_real_higashiguchi_model_fixture_parses_current_day_and_all_units() -> None:
    fixture = Path(__file__).parent / "fixtures" / "model_page_higashiguchi_20261020.html"
    business_date, units = parse_model_page(fixture.read_text(encoding="utf-8"), date(2026, 10, 20))
    assert business_date == date(2026, 10, 20)
    assert units == {
        "2567": 1015,
        "2568": 1828,
        "2570": 940,
        "2571": 834,
        "2572": 158,
        "2573": 1109,
        "2575": 1631,
        "2576": 2355,
        "2577": 537,
        "2578": 1243,
        "2580": 753,
        "2581": 581,
        "2582": 141,
        "2583": 3553,
        "2585": 504,
    }


def test_real_higashiguchi_index_fixture_has_76_unit_links() -> None:
    fixture = Path(__file__).parent / "fixtures" / "model_index_higashiguchi_2170_20261020.html"
    root = "https://daidata.goraggio.com/dedamajyoho-P-townDMMpachi/101425"
    links = parse_model_links(fixture.read_text(encoding="utf-8"), root)
    assert len(links) == 76
    assert all(price == "21.70" for _, price, _ in links)
    assert ("Lﾘｺﾘｽ･ﾘｺｲﾙ", "21.70") in {(model, price) for model, price, _ in links}


def test_empty_exception_keeps_type_and_http_failure_keeps_status() -> None:
    empty = failure_info(RuntimeError(), "model_page", model="AT")
    assert empty["exception_type"] == "RuntimeError" and empty["error"] == "RuntimeError"
    assert empty["message"] == "" and empty["http_status"] is None
    limited = failure_info(CollectionError("detail: HTTP 429"), "detail", machine_number="1001")
    assert limited["http_status"] == 429
    assert limited["message"] == "detail: HTTP 429"


def test_model_page_failures_do_not_prevent_legacy_detail_fetch(tmp_path: Path, monkeypatch) -> None:
    root = "https://daidata.goraggio.com/dedamajyoho-P-townDMMpachi/101425"
    detail_url = root + "/detail?unit=2567"
    second_detail_url = root + "/detail?unit=2568"
    model_url = root + "/unit_list?model=AT&ballPrice=21.70&ps=S"
    second_model_url = root + "/unit_list?model=BT&ballPrice=21.70&ps=S"
    index_url = root + "/list?mode=psModelNameSearch&ps=S"
    price_url = root + "/list?mode=psModelNameSearch&ps=S&ballPrice=21.70"
    responses = {
        detail_url: "<detail/>",
        second_detail_url: "<detail/>",
        index_url: f'<a href="{price_url}">21.70</a>',
        price_url: f'<a href="{model_url}">AT</a><a href="{second_model_url}">BT</a>',
        model_url: "<html>model page fails parsing</html>",
        second_model_url: "<html>model page fails parsing</html>",
    }

    class FakePacer:
        def __init__(self):
            self.urls = []
            self.request_count = 0
            self.rate_limit_events = 0
            self.effective_interval_ms = 0

        async def get(self, url, stage):
            self.urls.append(url)
            self.request_count += 1
            return responses[url]

    monkeypatch.setattr(
        "scraper.dmm_goraggio.collector.parse_detail",
        lambda html, day, unit: (
            {"machine_number": unit, "games": 1200, "max_payout": 500},
            None,
        ),
    )
    machine = {"machine_name": "AT", "machine_number": "2567", "rate": "21.70円スロット", "detail_url": detail_url}
    second = {
        "machine_name": "BT",
        "machine_number": "2568",
        "rate": "21.70円スロット",
        "detail_url": second_detail_url,
    }
    pacer = FakePacer()
    details, detail_failures, links, pages, model_failures = asyncio.run(
        collect_details_then_models(
            pacer, [machine, second], [machine, second], root, date(2026, 10, 20), tmp_path / "graphs", 1
        )
    )
    # 詳細ページ→機種一覧→貸玉別一覧の順は固定。機種ページはワーカーが並行して取るので順序を問わない。
    assert pacer.urls[:4] == [detail_url, second_detail_url, index_url, price_url]
    assert sorted(pacer.urls[4:]) == sorted([model_url, second_model_url])
    assert {unit: detail["games"] for unit, detail in details.items()} == {"2567": 1200, "2568": 1200}
    assert detail_failures == [] and pages == {}
    assert len(links) == 2 and len(model_failures) == 2
    assert all(item["stage"] == "model_page" and item["exception_type"] == "ValueError" for item in model_failures)
    all_failures = list(model_failures)
    apply_model_games([machine, second], pages, links, date(2026, 10, 20), all_failures)
    assert len(all_failures) == 2  # no duplicate bare "fetch failure" join records
