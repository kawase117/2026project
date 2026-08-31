import csv
import json
import sqlite3
import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "scraper"))


SEARCH_HTML = """
<html>
  <body>
    <article>
      <h2 class="entry-title"><a href="https://1geki.jp/slot/s_1000chan/">1000ちゃん（スロット）解析攻略</a></h2>
    </article>
    <article>
      <h2 class="entry-title"><a href="https://1geki.jp/slot/lb_1000chan_a/">LBパチスロ1000ちゃんA（スマスロ/スロット）解析攻略</a></h2>
    </article>
    <article>
      <h2 class="entry-title"><a href="https://1geki.jp/category/slot/">カテゴリ</a></h2>
    </article>
  </body>
</html>
"""

SEARCH_FALLBACK_HTML = """
<html>
  <body>
    <article>
      <h2 class="entry-title"><a href="https://1geki.jp/slot/l_tokyoghoul/">Ｌ 東京喰種（スマスロ）解析攻略</a></h2>
    </article>
    <article>
      <h2 class="entry-title"><a href="https://1geki.jp/category/slot/">カテゴリ</a></h2>
    </article>
  </body>
</html>
"""


def test_normalize_machine_name_variants() -> None:
    from machine_master_research_url_mapper import build_query_variants

    variants = build_query_variants("/いざ番長/SB8")

    assert variants[0] == "/いざ番長/SB8"
    assert "いざ番長 SB8" in variants
    assert "いざ番長SB8" in variants


def test_build_query_variants_includes_heuristic_short_form() -> None:
    from machine_master_research_url_mapper import build_query_variants

    variants = build_query_variants("LB SHAKE BONUS TRIGGER")

    assert "SHAKE BONUS TRIGGER" in variants


def test_build_query_variants_includes_code_geass_alias() -> None:
    from machine_master_research_url_mapper import build_query_variants

    variants = build_query_variants("コードギアス反逆のルルーシュ3 C.C.&Kallen ver.")

    assert "パチスロコードギアス 反逆のルルーシュ3 C.C.＆Kallen ver." in variants


def test_extract_candidate_urls_ignores_slot_root_link() -> None:
    from machine_master_research_url_mapper import extract_candidate_urls

    html = """
    <html>
      <body>
        <a href="https://1geki.jp/slot/">スロット</a>
        <a href="https://1geki.jp/slot/lb_shake/">ＳＨＡＫＥ ＢＯＮＵＳ ＴＲＩＧＧＥＲ</a>
      </body>
    </html>
    """

    candidates = extract_candidate_urls(html)

    assert len(candidates) == 1
    assert candidates[0]["url"] == "https://1geki.jp/slot/lb_shake/"


def test_extract_candidate_urls_filters_non_detail_pages() -> None:
    from machine_master_research_url_mapper import extract_candidate_urls

    candidates = extract_candidate_urls(SEARCH_HTML)

    assert len(candidates) == 2
    assert candidates[0]["url"] == "https://1geki.jp/slot/s_1000chan/"
    assert candidates[1]["url"] == "https://1geki.jp/slot/lb_1000chan_a/"


def test_resolve_machine_url_picks_best_exact_match() -> None:
    from machine_master_research_url_mapper import resolve_machine_url

    result = resolve_machine_url(
        "1000ちゃんA",
        fetch_html=lambda _url: SEARCH_HTML,
    )

    assert result["status"] == "selected"
    assert result["selected_url"] == "https://1geki.jp/slot/lb_1000chan_a/"
    assert result["confidence"] >= 0.8


def test_resolve_machine_url_uses_aliases_for_official_titles() -> None:
    from machine_master_research_url_mapper import resolve_machine_url

    page_index = [
        {"title": "ガルフィー（スロット）解析攻略", "url": "https://1geki.jp/slot/lb_galfy/"},
        {"title": "シスタークエスト（シスクエ）スマスロ解析攻略", "url": "https://1geki.jp/slot/l_sisterquest/"},
    ]

    galfy = resolve_machine_url("GALFY", page_index=page_index)
    sister_quest = resolve_machine_url("Sister Quest", page_index=page_index)

    assert galfy["status"] == "selected"
    assert galfy["selected_url"] == "https://1geki.jp/slot/lb_galfy/"
    assert sister_quest["status"] == "selected"
    assert sister_quest["selected_url"] == "https://1geki.jp/slot/l_sisterquest/"


def test_resolve_machine_url_uses_series_aliases() -> None:
    from machine_master_research_url_mapper import resolve_machine_url

    page_index = [
        {"title": "番長4（スマスロ）解析攻略", "url": "https://1geki.jp/slot/l_osu_bancho4/"},
        {"title": "銭形4（スマスロ）解析攻略", "url": "https://1geki.jp/slot/s_zenigata4/"},
        {"title": "ニューパルサーBT 解析攻略", "url": "https://1geki.jp/slot/l_newpulsar_bt/"},
    ]

    bancho = resolve_machine_url("押忍！番長4", page_index=page_index)
    zenigata = resolve_machine_url("主役は銭形4", page_index=page_index)
    newpulsar = resolve_machine_url("ニューパルサーBT", page_index=page_index)

    assert bancho["status"] == "selected"
    assert bancho["selected_url"] == "https://1geki.jp/slot/l_osu_bancho4/"
    assert zenigata["status"] == "selected"
    assert zenigata["selected_url"] == "https://1geki.jp/slot/s_zenigata4/"
    assert newpulsar["status"] == "selected"
    assert newpulsar["selected_url"] == "https://1geki.jp/slot/l_newpulsar_bt/"


def test_resolve_machine_url_handles_nameneko_and_okidoki_variants() -> None:
    from machine_master_research_url_mapper import resolve_machine_url

    page_index = [
        {"title": "なめ猫 解析攻略", "url": "https://1geki.jp/slot/s_nameneko/"},
        {"title": "沖ドキ!ゴージャス 解析攻略", "url": "https://1geki.jp/slot/s_okidoki_gorgeous/"},
    ]

    nameneko = resolve_machine_url("なめ猫～液晶ないけどなめんじゃねぇ～", page_index=page_index)
    okidoki = resolve_machine_url("沖ドキ!ゴージャス 30Φ", page_index=page_index)

    assert nameneko["status"] == "selected"
    assert nameneko["selected_url"] == "https://1geki.jp/slot/s_nameneko/"
    assert okidoki["status"] == "selected"
    assert okidoki["selected_url"] == "https://1geki.jp/slot/s_okidoki_gorgeous/"


def test_load_machine_master_alias_map_uses_display_names_and_official_name(tmp_path: Path) -> None:
    from machine_master_research_url_mapper import load_machine_master_alias_map

    db_dir = tmp_path / "db"
    db_dir.mkdir()
    db_path = db_dir / "machine_master.db"

    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE machine_master (
                machine_name_normalized TEXT PRIMARY KEY,
                display_names TEXT,
                official_name TEXT
            )
            """
        )
        conn.execute(
            """
            INSERT INTO machine_master (
                machine_name_normalized, display_names, official_name
            ) VALUES (?, ?, ?)
            """,
            ("TEST_MACHINE", "Alpha, Beta / Gamma", "Official Alpha"),
        )
        conn.commit()

    alias_map = load_machine_master_alias_map(db_dir=db_dir)

    assert alias_map["test_machine"] == ["TEST_MACHINE", "Alpha", "Beta", "Gamma", "Official Alpha"]


def test_resolve_machine_url_uses_machine_master_alias_map(tmp_path: Path) -> None:
    from machine_master_research_url_mapper import load_machine_master_alias_map, resolve_machine_url

    db_dir = tmp_path / "db"
    db_dir.mkdir()
    db_path = db_dir / "machine_master.db"

    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE machine_master (
                machine_name_normalized TEXT PRIMARY KEY,
                display_names TEXT,
                official_name TEXT
            )
            """
        )
        conn.execute(
            """
            INSERT INTO machine_master (
                machine_name_normalized, display_names, official_name
            ) VALUES (?, ?, ?)
            """,
            ("TEST_MACHINE", "Alpha, Beta", "Official Alpha"),
        )
        conn.commit()

    alias_map = load_machine_master_alias_map(db_dir=db_dir)
    page_index = [
        {"title": "Official Alpha スペック", "url": "https://1geki.jp/slot/test_machine/"},
        {"title": "Unrelated", "url": "https://1geki.jp/slot/other/"},
    ]

    result = resolve_machine_url(
        "TEST_MACHINE",
        page_index=page_index,
        machine_master_alias_map=alias_map,
    )

    assert result["status"] == "selected"
    assert result["selected_url"] == "https://1geki.jp/slot/test_machine/"


def test_resolve_machine_url_falls_back_to_search_results_when_page_index_misses() -> None:
    from machine_master_research_url_mapper import resolve_machine_url

    page_index = [
        {"title": "Unrelated", "url": "https://1geki.jp/slot/other/"},
    ]

    def fake_fetch_html(url: str) -> str:
        if "/search/?keyword=" in url:
            return SEARCH_FALLBACK_HTML
        raise AssertionError(f"unexpected url: {url}")

    result = resolve_machine_url(
        "東京喰種",
        page_index=page_index,
        fetch_html=fake_fetch_html,
    )

    assert result["status"] == "selected"
    assert result["selected_url"] == "https://1geki.jp/slot/l_tokyoghoul/"


def test_build_url_map_updates_master_and_optionally_writes_audit(tmp_path: Path) -> None:
    from machine_master_research_url_mapper import build_url_map

    input_path = tmp_path / "machine_master.csv"
    audit_path = tmp_path / "url_resolution_audit.json"

    with input_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["machine_name", "manufacturer", "notes"])
        writer.writerow(["1000ちゃんA", "OIZUMI", ""])

    page_index = [
        {
            "title": "LBパチスロ1000ちゃんA（スマスロ/スロット）解析攻略",
            "url": "https://1geki.jp/slot/lb_1000chan_a/",
        },
        {
            "title": "1000ちゃん（スロット）解析攻略",
            "url": "https://1geki.jp/slot/s_1000chan/",
        },
    ]

    summary = build_url_map(
        input_path=input_path,
        audit_path=audit_path,
        page_index=page_index,
        machine_master_alias_map={"1000ちゃんa": ["1000ちゃんA", "LBパチスロ1000ちゃんA"]},
    )

    assert summary["rows_total"] == 1
    assert summary["rows_selected"] == 1
    assert summary["master_rows_updated"] == 1
    assert audit_path.exists()

    with input_path.open("r", encoding="utf-8-sig", newline="") as f:
        master_rows = list(csv.DictReader(f))
    assert master_rows[0]["source_url"] == "https://1geki.jp/slot/lb_1000chan_a/"
    assert master_rows[0]["source_status"] == "selected"
    assert master_rows[0]["source_candidate_count"] == "2"

    with audit_path.open("r", encoding="utf-8") as f:
        payload = json.load(f)
    assert payload[0]["selected_url"] == "https://1geki.jp/slot/lb_1000chan_a/"


def test_parse_duplicate_groups_markdown_extracts_rows(tmp_path: Path) -> None:
    from machine_master_duplicate_url_resolver import parse_duplicate_groups_markdown

    source_path = tmp_path / "duplicate_selected_url_groups_split.md"
    source_path.write_text(
        """
## 同一機種の表記揺れ

| selected_url | machine_names |
|---|---|
| `https://1geki.jp/slot/lb_shake/` | `LB SHAKE BONUS TRIGGER`<br>`SHAKE BONUS TRIGGER` |
""".strip()
        + "\n",
        encoding="utf-8",
    )

    rows = parse_duplicate_groups_markdown(source_path)

    assert len(rows) == 1
    assert rows[0].section == "同一機種の表記揺れ"
    assert rows[0].selected_url == "https://1geki.jp/slot/lb_shake/"
    assert rows[0].machine_names == ["LB SHAKE BONUS TRIGGER", "SHAKE BONUS TRIGGER"]


def test_resolve_duplicate_groups_uses_shared_mapper(tmp_path: Path) -> None:
    from machine_master_duplicate_url_resolver import resolve_duplicate_groups

    source_path = tmp_path / "duplicate_selected_url_groups_split.md"
    json_path = tmp_path / "duplicate_url_resolution.json"
    csv_path = tmp_path / "duplicate_url_resolution.csv"
    md_path = tmp_path / "duplicate_url_resolution.md"
    source_path.write_text(
        """
## 同一機種の表記揺れ

| selected_url | machine_names |
|---|---|
| `https://1geki.jp/slot/lb_shake/` | `LB SHAKE BONUS TRIGGER`<br>`SHAKE BONUS TRIGGER(スマスロ)` |
""".strip()
        + "\n",
        encoding="utf-8",
    )

    page_index = [
        {"title": "LB SHAKE BONUS TRIGGER 繝ｹ繝ｼ繧ｿ", "url": "https://1geki.jp/slot/lb_shake/"},
    ]

    summary = resolve_duplicate_groups(
        source_path=source_path,
        json_path=json_path,
        csv_path=csv_path,
        md_path=md_path,
        page_index=page_index,
    )

    assert summary["rows_total"] == 2
    assert summary["rows_selected"] == 2
    assert json_path.exists()
    assert csv_path.exists()
    assert md_path.exists()

    with json_path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    assert payload["rows_selected"] == 2
    assert payload["sections"][0]["rows"][0]["resolved_url"] == "https://1geki.jp/slot/lb_shake/"
