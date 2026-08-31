import csv

from scraper.fetch_rtp_via_llm import (
    extract_specs_from_html,
    find_unresolved_fields,
    identify_incomplete_rows,
    identify_missing_rtp,
    identity_matches,
    load_master_source_urls,
    normalize_machine_type,
    parse_probability,
    parse_rtp_value,
    resolve_1geki_url,
    update_csv_with_results,
    validate_master,
)


HEADER = [
    "machine_name",
    "manufacturer",
    "release_date",
    "machine_type",
    *[f"rtp_setting{i}" for i in range(1, 7)],
    *[f"bb_setting{i}" for i in range(1, 7)],
    *[f"rb_setting{i}" for i in range(1, 7)],
    "notes",
    "source_url",
    "source_status",
    "source_confidence",
    "source_query",
    "source_candidate_count",
    "source_reason",
    "canonical_machine_name",
    "manufacturer_canonical",
    "cabinet_type",
    "game_type",
    "bt_flag",
    *[
        f"{metric}_setting{i}"
        for metric in ("at_initial", "bonus_initial", "bonus_combined", "combined_initial", "rtp_complete")
        for i in range(1, 7)
    ],
    "source_title",
    "source_checked_at",
]


def _row(name: str) -> list[str]:
    row = [name, "", "", "スマスロ", *([""] * 18), "", *([""] * 6)]
    row.extend([""] * (len(HEADER) - len(row)))
    row[HEADER.index("canonical_machine_name")] = name
    row[HEADER.index("cabinet_type")] = "スマスロ"
    row[HEADER.index("bt_flag")] = "0"
    return row


def test_partial_rtp_row_is_selected_for_refresh():
    row = _row("four-setting-machine")
    row[9] = "109.0"

    missing = identify_missing_rtp(HEADER, [row])

    assert missing == [(1, row)]


def test_unresolved_scope_includes_generic_smart_slot_and_normal_bonus_gaps():
    row = _row("normal-smart-slot")
    row[1] = "maker"
    row[2] = "2025-10-20"
    row[4:10] = ["98.6", "100.6", "", "", "103.0", "106.1"]

    assert find_unresolved_fields(HEADER, row) == ["machine_type"]
    assert identify_incomplete_rows(HEADER, [row]) == [(1, row)]

    row[3] = "スマスロ / ノーマル / BT"
    assert find_unresolved_fields(HEADER, row) == ["bb", "rb"]


def test_standard_four_setting_rtp_blanks_are_not_treated_as_missing():
    row = _row("four-setting")
    row[1:4] = ["maker", "2026-04-06", "スマスロ / ノーマル / BT"]
    row[4:10] = ["97.9", "99.9", "", "", "104.4", "109.0"]
    row[10] = "1/200.0"
    row[16] = "1/300.0"

    assert find_unresolved_fields(HEADER, row) == []


def test_machine_type_normalization_keeps_platform_system_and_bt():
    assert normalize_machine_type("スマスロ、ノーマル(A)タイプ、ボーナストリガー") == "スマスロ / ノーマル / BT"
    assert normalize_machine_type("スマスロ / ATタイプ") == "スマスロ / AT"
    assert normalize_machine_type("AT スマスロ") == "スマスロ / AT"
    assert normalize_machine_type("ボーナス+AT スマスロ") == "スマスロ / AT"
    assert normalize_machine_type("BONUS スマスロ") == "スマスロ / ノーマル"
    assert normalize_machine_type("A+RTタイプ、スマスロ") == "スマスロ / A+RT"


def test_master_source_url_is_used_before_heuristic_fallback():
    mapped = resolve_1geki_url(
        "machine",
        {"machine": "https://1geki.jp/slot/from_master/"},
    )
    fallback = resolve_1geki_url("SHAKE BONUS TRIGGER", {})

    assert mapped == "https://1geki.jp/slot/from_master/"
    assert fallback == "https://1geki.jp/slot/lb_shake/"


def test_load_master_source_urls_reads_only_selected_entries(tmp_path):
    path = tmp_path / "machine_master.csv"
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["machine_name", "source_url", "source_status"])
        writer.writeheader()
        writer.writerow(
            {"machine_name": "selected", "source_url": "https://1geki.jp/slot/selected/", "source_status": "selected"}
        )
        writer.writerow(
            {"machine_name": "review", "source_url": "https://1geki.jp/slot/review/", "source_status": "needs_review"}
        )

    assert load_master_source_urls(path) == {"selected": "https://1geki.jp/slot/selected/"}


def test_identity_gate_rejects_same_series_different_release():
    row = _row("ToLOVEるダークネス")
    row[2] = "2024-06-03"
    result = {
        "official_name": "L ToLOVEるダークネス TRANCE ver.8.7",
        "release_date": "2025-05-19",
    }

    ok, reason = identity_matches(row[0], row, result)

    assert not ok
    assert reason.startswith("release_mismatch:")


def test_identity_gate_allows_exact_name_to_correct_bad_release_date():
    row = _row("ゴジラ")
    row[2] = "2025-08-18"
    result = {
        "official_name": "L ゴジラ",
        "identity_names": ["L ゴジラ"],
        "release_date": "2025-04-07",
    }

    ok, reason = identity_matches(row[0], row, result)

    assert ok
    assert reason == "exact_identity_release_correction"


def test_identity_gate_accepts_shake_title_alias():
    row = _row("SHAKE BONUS TRIGGER(スマスロ)")
    row[2] = "2025-10-20"
    result = {
        "page_title": "シェイク（スマスロ）解析攻略｜ＳＨＡＫＥ ＢＯＮＵＳ ＴＲＩＧＧＥＲ",
        "release_date": "2025-10-20",
    }

    ok, reason = identity_matches(row[0], row, result)

    assert ok
    assert reason == "exact_identity"


def test_identity_gate_accepts_release_matched_short_alias():
    row = _row("Sister Quest")
    row[2] = "2025-03-03"
    row[1] = "Carmina（カルミナ）"
    result = {
        "identity_names": ["シスタークエスト スマスロ解析攻略"],
        "release_date": "2025-03-03",
        "manufacturer": "Carmina（カルミナ）",
    }

    ok, reason = identity_matches(row[0], row, result)

    assert ok
    assert reason == "release_and_manufacturer"


def test_identity_gate_rejects_digit_conflict_even_when_release_matches():
    row = _row("Example 2")
    row[2] = "2025-03-03"
    result = {
        "identity_names": ["Example 3"],
        "release_date": "2025-03-03",
    }

    ok, reason = identity_matches(row[0], row, result)

    assert not ok
    assert reason.startswith("name_mismatch:")


def test_identity_gate_accepts_formal_model_name_contained_in_page_title():
    row = _row("LB翔べ!ハーレムエースCF")
    row[2] = "2025-06-02"
    result = {
        "identity_names": ["翔べ！ハーレムエース スマスロ解析攻略まとめ"],
        "release_date": "2025-06-02",
    }

    ok, reason = identity_matches(row[0], row, result)

    assert ok
    assert reason == "exact_identity"


def test_identity_gate_accepts_two_character_japanese_name():
    row = _row("島娘")
    row[2] = "2025-01-20"
    result = {
        "identity_names": ["島娘（スマスロ）解析攻略"],
        "release_date": "2025-01-20",
        "source_machine_type": "ATタイプ / スマスロ",
    }

    ok, reason = identity_matches(row[0], row, result)

    assert ok
    assert reason == "exact_identity"


def test_identity_gate_accepts_registered_transliteration_alias():
    row = _row("009 RE:CYBORG")
    result = {
        "identity_names": ["パチスロ009 リ・サイボーグ"],
        "source_machine_type": "ATタイプ / スマスロ",
    }

    ok, reason = identity_matches(row[0], row, result)

    assert ok
    assert reason == "exact_identity"


def test_identity_gate_accepts_registered_new_onimusha_subtitle():
    row = _row("パチスロ新鬼武者")
    row[2] = "2020-03-23"
    result = {
        "identity_names": ["新鬼武者～DAWN OF DREAMS～"],
        "release_date": "2020-03-23",
    }

    ok, reason = identity_matches(row[0], row, result)

    assert ok
    assert reason == "exact_identity"


def test_identity_gate_ignores_page_title_alias_and_analysis_suffix():
    row = _row("ありふれた職業で世界最強")
    row[2] = "2024-07-22"
    result = {
        "identity_names": ["ありふれた職業で世界最強（スロット/スマスロ）解析攻略"],
        "release_date": "2025-02-03",
        "source_machine_type": "ATタイプ / スマスロ",
    }

    ok, reason = identity_matches(row[0], row, result)

    assert ok
    assert reason == "exact_identity_release_correction"


def test_identity_gate_rejects_contained_title_without_release_evidence():
    row = _row("legacy-title")
    result = {
        "identity_names": ["legacy-title new version"],
    }

    ok, reason = identity_matches(row[0], row, result)

    assert not ok
    assert reason.startswith("name_mismatch:")


def test_identity_gate_rejects_legacy_page_for_smart_slot_target():
    row = _row("スマスロ ハナビ")
    result = {"identity_names": ["ハナビ - 【一撃】パチスロ解析攻略"]}

    ok, reason = identity_matches(row[0], row, result)

    assert not ok
    assert reason.startswith("platform_mismatch:")


def test_identity_gate_keeps_blank_date_legacy_row_out_of_automatic_updates():
    row = _row("化物語")
    row[3] = "AT"
    row[22] = "5号機データ割愛"
    result = {"identity_names": ["化物語"]}

    ok, reason = identity_matches(row[0], row, result)

    assert not ok
    assert reason == "legacy_row_requires_manual_source"


def test_four_setting_values_are_mapped_by_setting_number():
    row = _row("A-SLOT+ sample")
    row[6] = "104.4"
    row[7] = "109.0"
    result = {
        "name": "A-SLOT+ sample",
        "rtp1": 97.9,
        "rtp2": 99.9,
        "rtp3": None,
        "rtp4": None,
        "rtp5": 104.4,
        "rtp6": 109.0,
        "published_rtp_settings": [1, 2, 5, 6],
        "bonus_initial1": "1/197.6",
        "bonus_initial2": "1/193.9",
        "bonus_initial5": "1/175.4",
        "bonus_initial6": "1/161.1",
        "bonus_combined1": "1/99.9",
        "bonus_combined2": "1/98.1",
        "bonus_combined5": "1/89.1",
        "bonus_combined6": "1/82.1",
    }

    updated = update_csv_with_results([row], HEADER, [result], overwrite_existing=True)

    assert updated == 1
    assert row[4:10] == ["97.9", "99.9", "", "", "104.4", "109.0"]
    assert row[10:22] == [""] * 12
    assert row[HEADER.index("bonus_initial_setting1")] == "1/197.6"
    assert row[HEADER.index("bonus_combined_setting1")] == "1/99.9"


def test_onegeki_table_is_parsed_by_printed_setting_number():
    html = """
    <table>
      <thead><tr><th>設定</th><th>ボーナス<br>初当たり</th><th>ボーナス<br>合算</th><th>出玉率<br>（完全攻略）</th></tr></thead>
      <tbody>
        <tr><th>1</th><td>1/197.6</td><td>1/99.9</td><td>97.9%<br>（99.0%）</td></tr>
        <tr><th>2</th><td>1/193.9</td><td>1/98.1</td><td>99.9%<br>（101.1%）</td></tr>
        <tr><th>5</th><td>1/175.4</td><td>1/89.1</td><td>104.4%<br>（105.7%）</td></tr>
        <tr><th>6</th><td>1/161.1</td><td>1/82.1</td><td>109.0%<br>（110.6%）</td></tr>
      </tbody>
    </table>
    <table><tbody>
      <tr><th>正式名称</th><td>A-SLOT+ 異世界かるてっと BT</td></tr>
      <tr><th>メーカー</th><td>GINZA（銀座）</td></tr>
      <tr><th>導入開始日</th><td>2026年4月6日</td></tr>
      <tr><th>タイプ</th><td>スマスロ、ノーマル(A)タイプ、ボーナストリガー</td></tr>
    </tbody></table>
    """

    result = extract_specs_from_html(
        "A-SLOT+ 異世界かるてっと",
        html,
        source_url="https://1geki.jp/slot/l_isekai_quartet/",
    )

    assert [result.get(f"rtp{i}") for i in range(1, 7)] == [
        "97.9",
        "99.9",
        None,
        None,
        "104.4",
        "109.0",
    ]
    assert result["bonus_initial5"] == "1/175.4"
    assert result["bonus_combined6"] == "1/82.1"
    assert result["rtp_complete5"] == "105.7"
    assert result["published_rtp_settings"] == [1, 2, 5, 6]
    assert not any(key.startswith(("bb", "rb")) for key in result)
    assert result["manufacturer"] == "GINZA（銀座）"
    assert result["release_date"] == "2026-04-06"
    assert result["machine_type"] == "スマスロ / ノーマル / BT"


def test_explicit_bb_and_rb_are_written_only_to_exact_setting_columns():
    row = _row("normal-machine")
    result = {
        "name": "normal-machine",
        "bb1": "1/270.8",
        "bb6": "1/240.1",
        "rb1": "1/420.0",
        "rb6": "1/260.3",
    }

    update_csv_with_results([row], HEADER, [result])

    assert row[10:16] == ["1/270.8", "", "", "", "", "1/240.1"]
    assert row[16:22] == ["1/420.0", "", "", "", "", "1/260.3"]


def test_legacy_onegeki_table_without_thead_parses_shake_columns():
    html = """
    <table class="tb1">
      <tr><td>設定</td><td>BB<br>確率</td><td>RB<br>確率</td><td>ボーナス<br>合算</td><td>出玉率<br>（完全攻略）</td></tr>
      <tr><td>1</td><td>1/350.5</td><td>1/425.6</td><td>1/192.2</td><td>98.6%<br>（100.4%）</td></tr>
      <tr><td>2</td><td>1/327.7</td><td>1/332.7</td><td>1/165.1</td><td>100.6%<br>（102.4%）</td></tr>
      <tr><td>5</td><td>1/341.3</td><td>1/409.6</td><td>1/186.2</td><td>103.0%<br>（104.9%）</td></tr>
      <tr><td>6</td><td>1/297.9</td><td>1/297.9</td><td>106.1%<br>（108.1%）</td></tr>
    </table>
    <table class="tb1">
      <tr><td colspan="2">機種情報</td></tr>
      <tr><td>導入日</td><td>2025年10月20日</td></tr>
      <tr><td>メーカー</td><td>Daito（大都技研）</td></tr>
      <tr><td>スペック</td><td>スマスロ / ノーマル(A)タイプ / ボーナストリガー</td></tr>
    </table>
    """

    result = extract_specs_from_html("SHAKE BONUS TRIGGER", html)

    assert [result.get(f"rtp{i}") for i in range(1, 7)] == [
        "98.6",
        "100.6",
        None,
        None,
        "103.0",
        "106.1",
    ]
    assert result["bb1"] == "1/350.5"
    assert result["bb6"] == "1/297.9"
    assert result["rb1"] == "1/425.6"
    assert result["rb6"] == "1/297.9"
    assert result["bonus_combined5"] == "1/186.2"
    assert "bonus_combined6" not in result
    assert result["published_bb_settings"] == [1, 2, 5, 6]
    assert result["published_rb_settings"] == [1, 2, 5, 6]
    assert result["manufacturer"] == "Daito（大都技研）"
    assert result["release_date"] == "2025-10-20"


def test_separate_complete_strategy_rtp_does_not_overwrite_nominal_rtp():
    html = """
    <table>
      <tr><td>設定</td><td>ボーナス合算</td><td>出玉率</td><td>出玉率<br>【完全攻略時】</td></tr>
      <tr><td>1</td><td>1/183.1</td><td>98.7%</td><td>100.0%</td></tr>
      <tr><td>2</td><td>1/173.4</td><td>100.1%</td><td>101.5%</td></tr>
      <tr><td>5</td><td>1/166.3</td><td>103.0%</td><td>104.5%</td></tr>
      <tr><td>6</td><td>1/156.0</td><td>106.8%</td><td>108.3%</td></tr>
    </table>
    """

    result = extract_specs_from_html("LBニューパルサー", html)

    assert [result.get(f"rtp{i}") for i in (1, 2, 5, 6)] == ["98.7", "100.1", "103.0", "106.8"]
    assert [result.get(f"rtp_complete{i}") for i in (1, 2, 5, 6)] == ["100.0", "101.5", "104.5", "108.3"]

    row = _row("LBニューパルサー")
    update_csv_with_results([row], HEADER, [result], overwrite_existing=True)
    assert row[HEADER.index("rtp_complete_setting6")] == "108.3"


def test_pay_header_is_rtp_and_explicit_at_metric_infers_machine_type():
    html = """
    <title>スマスロ ハナビ 解析攻略</title>
    <table>
      <tr><td>設定</td><td>AT確率</td><td>PAY</td></tr>
      <tr><td>1</td><td>1/300.0</td><td>98.0%</td></tr>
      <tr><td>6</td><td>1/200.0</td><td>108.5%</td></tr>
    </table>
    """

    result = extract_specs_from_html("sample", html)

    assert result["rtp1"] == "98.0"
    assert result["rtp6"] == "108.5"
    assert result["machine_type"] == "スマスロ / AT"


def test_special_v_setting_is_kept_in_notes_not_numeric_setting_columns():
    row = _row("special-v")
    row[1:4] = ["maker", "2026-01-05", "ノーマル / BT"]
    result = {
        "name": row[0],
        "published_rtp_settings": [1, 2, 3, 4],
        "rtp1": "97",
        "rtp2": "99",
        "rtp3": "101",
        "rtp4": "104",
        "special_settings": {"V": {"rtp": "108", "bb": "1/253", "rb": "1/372"}},
    }

    update_csv_with_results([row], HEADER, [result], overwrite_existing=True)

    assert row[4:10] == ["97.0", "99.0", "101.0", "104.0", "", ""]
    assert "設定V:出玉率=108/BB=1/253/RB=1/372" in row[22]
    assert "rtp" not in find_unresolved_fields(HEADER, row)


def test_generic_bonus_only_table_records_that_individual_bb_rb_are_unpublished():
    row = _row("generic-only")
    row[1:4] = ["maker", "2026-04-06", "スマスロ / ノーマル / BT"]
    row[4:10] = ["97.9", "99.9", "", "", "104.4", "109.0"]
    result = {
        "name": row[0],
        "source_machine_type": "スマスロ、ノーマル(A)タイプ、ボーナストリガー",
        "bonus_combined1": "1/99.9",
    }

    update_csv_with_results([row], HEADER, [result], overwrite_existing=True)

    assert "一撃掲載表にBB/RB個別確率なし" in row[22]
    assert row[HEADER.index("bonus_combined_setting1")] == "1/99.9"
    assert "bb" not in find_unresolved_fields(HEADER, row)
    assert "rb" not in find_unresolved_fields(HEADER, row)


def test_value_parsers_reject_cross_column_fragments():
    assert parse_rtp_value("109.0%") == 109.0
    assert parse_rtp_value("1/197.6") is None
    assert parse_probability("1／197.6") == "1/197.6"
    assert parse_probability("BB確率(設定1") is None


def test_overwrite_clears_unpublished_bb_rb_settings():
    row = _row("four-setting-normal")
    row[10:22] = ["1/999"] * 12
    result = {
        "name": row[0],
        "published_bb_settings": [1, 2, 5, 6],
        "published_rb_settings": [1, 2, 5, 6],
        "bb1": "1/350.5",
        "bb2": "1/327.7",
        "bb5": "1/341.3",
        "bb6": "1/297.9",
        "rb1": "1/425.6",
        "rb2": "1/332.7",
        "rb5": "1/409.6",
        "rb6": "1/297.9",
    }

    update_csv_with_results([row], HEADER, [result], overwrite_existing=True)

    assert row[10:16] == ["1/350.5", "1/327.7", "", "", "1/341.3", "1/297.9"]
    assert row[16:22] == ["1/425.6", "1/332.7", "", "", "1/409.6", "1/297.9"]


def test_llm_can_replace_generic_machine_type_without_overwriting_other_values():
    row = _row("typed-by-llm")
    row[1] = "existing maker"

    update_csv_with_results(
        [row],
        HEADER,
        [{"name": row[0], "manufacturer": "other maker", "machine_type": "スマスロ / AT"}],
    )

    assert row[1] == "existing maker"
    assert row[3] == "スマスロ / AT"


def test_machine_name_preserves_smart_platform_when_source_type_omits_it():
    row = _row("スマート沖スロ sample")

    update_csv_with_results(
        [row],
        HEADER,
        [{"name": row[0], "machine_type": "ノーマル / BT"}],
        overwrite_existing=True,
    )

    assert row[3] == "スマスロ / ノーマル / BT"


def test_master_validation_rejects_bad_probability_and_duplicate_name():
    first = _row("duplicate")
    second = _row("duplicate")
    first[10] = "BB 1/300"

    errors = validate_master(HEADER, [first, second])

    assert "row_2:invalid_bb1:BB 1/300" in errors
    assert "row_3:duplicate_machine_name:duplicate" in errors
