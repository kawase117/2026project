from __future__ import annotations

from scraper.site777.graph_quality import AXIS_LIMIT, assess_graph_item, censor_bound
from scraper.site777.site777_analyze import (
    analyze,
    build_model_report,
    build_setting_report,
    build_three_machine_report,
)

# 2026-09-13 19:25 ランの標準的な軸ラベル位置（+5,000 が y=26、-5,000 が y=344.5）。
STANDARD_LABELS = ((26.0, 5000, "5,000"), (344.5, -5000, "-5,000"))
# 2119 の実例: 「5,000」を「500」と誤読。間隔は 317.5px で他の台と一致する。
MISREAD_LABELS = ((32.5, 500, "5.00"), (350.0, -5000, "-5.000"))


def _graph_item(latest_y: float, estimated: int, labels=STANDARD_LABELS, key: str = "1:1") -> dict:
    return {
        "key": key,
        "status": "ok",
        "axisLabels": [{"y": y, "value": value, "text": text} for y, value, text in labels],
        "latestY": latest_y,
        "rawLatestDiff": float(estimated),
        "estimatedLatestDiff": estimated,
        "confidence": "medium",
        "updateTime": "2026/09/13 18:55",
    }


def test_saturated_top_is_censored_high_and_uses_axis_limit() -> None:
    quality = assess_graph_item(_graph_item(28.0, 4940))

    assert quality["diff_censored_high"] is True
    assert quality["diff_censored_low"] is False
    assert quality["estimated_diff"] == AXIS_LIMIT
    assert quality["axis_label_suspect"] is False


def test_saturated_bottom_is_censored_low() -> None:
    quality = assess_graph_item(_graph_item(343.0, -4950))

    assert quality["diff_censored_low"] is True
    assert quality["diff_censored_high"] is False
    assert quality["estimated_diff"] == -AXIS_LIMIT


def test_normal_trace_is_left_untouched() -> None:
    # 上端から4px下（+4,870）は張り付きではない。19:25 ランの 2139 と同じ位置。
    for latest_y, estimated in ((210.0, -780), (30.0, 4870)):
        quality = assess_graph_item(_graph_item(latest_y, estimated))
        assert quality["estimated_diff"] == estimated
        assert not any(
            quality[key] for key in ("diff_censored_high", "diff_censored_low", "axis_label_suspect", "diff_unreliable")
        )


def test_misread_axis_label_is_corrected_with_fixed_axis() -> None:
    # 2119 の再現: 誤読した縮尺では +600 と出ていたが、終点は上端に張り付いている。
    quality = assess_graph_item(_graph_item(27.0, 600, MISREAD_LABELS))

    assert quality["axis_label_suspect"] is True
    assert quality["axis_label_corrected"] is True
    assert quality["diff_censored_high"] is True
    assert quality["estimated_diff"] == AXIS_LIMIT
    assert quality["diff_unreliable"] is False

    # 軸の中央なら補正後は 0 枚付近になる（誤読した縮尺のままでは約 -2,250）。
    middle = assess_graph_item(_graph_item(191.25, -2250, MISREAD_LABELS))
    assert middle["axis_label_corrected"] is True
    assert middle["diff_censored_high"] is False
    assert middle["estimated_diff"] == 0


def test_axis_with_inconsistent_geometry_is_marked_unreliable() -> None:
    wrong_spacing = ((26.0, 500, "500"), (200.0, -5000, "-5,000"))
    quality = assess_graph_item(_graph_item(100.0, 1200, wrong_spacing))

    assert quality["diff_unreliable"] is True
    assert quality["axis_label_suspect"] is True
    assert quality["axis_label_corrected"] is False
    assert quality["diff_censored_high"] is False

    single_label = assess_graph_item(_graph_item(100.0, 1200, ((26.0, 5000, "5,000"),)))
    assert single_label["diff_unreliable"] is True


def test_assessment_is_idempotent_on_already_flagged_metrics() -> None:
    first = assess_graph_item(_graph_item(27.0, 600, MISREAD_LABELS))
    stored = _graph_item(27.0, first["estimated_diff"], MISREAD_LABELS)
    stored["rawLatestDiff"] = first["raw_diff"]

    assert assess_graph_item(stored) == first


def test_censor_bound_direction() -> None:
    assert censor_bound(0, 0) is None
    assert censor_bound(2, 0) == "lower"
    assert censor_bound(0, 1) == "upper"
    assert censor_bound(1, 1) == "indeterminate"


MDC = "120010"


def _source(rows: list[list[str]]) -> dict:
    return {
        "complete": True,
        "models": {
            MDC: {
                "complete": True,
                "mdc": MDC,
                "name": "マイジャグラーV",
                "jackpot": {"updateTime": "2026/09/13 18:55", "pages": [{"rows": [["台番", "G", "BB", "RB"], *rows]}]},
                "highest": {"updateTime": "2026/09/13 18:55", "pages": [{"rows": [[row[0], "1000"] for row in rows]}]},
            }
        },
    }


def _analyze_synthetic() -> dict:
    # 101: 上端張り付き / 102・103: カウント完全一致（重複疑い）/ 103: 軸ラベル誤読 / 104: 下端張り付き
    rows = [
        ["101", "4000", "15", "14"],
        ["102", "3000", "12", "10"],
        ["103", "3000", "12", "10"],
        ["104", "2500", "5", "3"],
    ]
    graph_metrics = {
        "graphMinGames": 2000,
        "sourceComplete": True,
        "machines": [
            _graph_item(27.0, 4970, key=f"{MDC}:101"),
            _graph_item(174.0, 500, key=f"{MDC}:102"),
            _graph_item(191.25, -2250, MISREAD_LABELS, key=f"{MDC}:103"),
            _graph_item(344.0, -4980, key=f"{MDC}:104"),
        ],
    }
    return analyze(_source(rows), graph_metrics, None)


def test_analyze_carries_flags_to_machines_and_aggregates() -> None:
    result = _analyze_synthetic()
    by_number = {machine["machine_number"]: machine for machine in result["machines"]}

    assert by_number["101"]["diff_censored_high"] is True
    assert by_number["101"]["latest_diff"] == AXIS_LIMIT
    assert by_number["104"]["diff_censored_low"] is True
    assert by_number["103"]["axis_label_corrected"] is True
    assert by_number["103"]["latest_diff"] == 0
    assert by_number["102"]["counts_duplicate_suspect"] is True
    assert by_number["102"]["counts_duplicate_with"] == ["103"]
    assert by_number["101"]["counts_duplicate_suspect"] is False

    quality = result["diff_quality"]
    assert quality["diff_censored_high_machines"] == ["101"]
    assert quality["diff_censored_low_machines"] == ["104"]
    assert quality["axis_label_corrected_machines"] == ["103"]
    assert quality["counts_duplicate_suspect_groups"] == [["102", "103"]]

    model = result["models"][0]
    assert model["diff_bound"] == "indeterminate"
    assert model["counts_duplicate_suspect_count"] == 2

    runs = {run["start_machine"]: run for run in result["three_machine_runs"]}
    assert runs["101"]["diff_bound"] == "lower"
    assert runs["102"]["diff_bound"] == "upper"
    assert runs["101"]["machines"][0]["diff_censored_high"] is True
    block = result["positive_blocks"][0]
    assert block["diff_bound"] == "lower"


def test_reports_show_censored_values_as_bounds_and_mark_duplicates() -> None:
    result = _analyze_synthetic()

    three = build_three_machine_report(result)
    assert "≥+5,000枚" in three
    assert "≥+5,500" in three  # 101〜103 の合計差枚は下限
    assert "上端張り付き1台（101）" in three

    model_report = build_model_report(result, "main_models", "t", "s", include_candidates=True)
    assert "上下打切り混在" in model_report
    assert "102※重複疑い" in model_report

    setting = build_setting_report(result)
    assert "102※重複疑い" in setting
    assert "要確認(カウント重複)" in setting
    reliable_section = setting.split("信用度 高・中 に限定")[1].split("##")[0]
    assert "※重複疑い" not in reliable_section
    assert "102、103を含む（除外時の判定:" in setting


def test_zentaikei_notes_duplicate_suspects() -> None:
    result = _analyze_synthetic()
    rows = result["model_zentaikei"]

    assert len(rows) == 1
    assert rows[0]["counts_duplicate_suspect_machines"] == ["102", "103"]
    # 重複疑いを外すと2台で、全台系判定の最低台数(3)に届かない。
    assert rows[0]["verdict_excluding_duplicate_suspects"] == "台数不足"
