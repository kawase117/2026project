from __future__ import annotations

import argparse
import json
import math
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from statistics import fmean
from typing import Any, Callable, Iterable

try:
    from .reference import (
        DEFAULT_ALIAS_FILE,
        DEFAULT_REFERENCE_DB,
        build_physical_lanes,
        enrich_machines,
        load_reference_context,
    )
    from .setting_estimator import annotate_setting_estimates, load_family_specs
except ImportError:
    from reference import (  # type: ignore[no-redef]
        DEFAULT_ALIAS_FILE,
        DEFAULT_REFERENCE_DB,
        build_physical_lanes,
        enrich_machines,
        load_reference_context,
    )
    from setting_estimator import (  # type: ignore[no-redef]
        annotate_setting_estimates,
        load_family_specs,
    )


def parse_int(value: Any) -> int | None:
    if value is None:
        return None
    text = str(value).strip().replace(",", "")
    if not text or text in {"--", "-"}:
        return None
    try:
        return int(text)
    except ValueError:
        return None


def probability(games: int, bonus_count: int) -> float | None:
    if games < 0 or bonus_count <= 0:
        return None
    return games / bonus_count


def mean_or_none(values: Iterable[float | int | None]) -> float | None:
    valid = [float(value) for value in values if value is not None]
    return fmean(valid) if valid else None


def numeric_rows(pages: Iterable[dict[str, Any]]) -> list[list[str]]:
    result: list[list[str]] = []
    for page in pages:
        for row in page.get("rows", []):
            if row and str(row[0]).strip().isdigit():
                result.append([str(value).strip() for value in row])
    return result


# 勝率のような率指標は母数が小さいと 100% が並ぶだけになるため、最低台数を課す。
MIN_RANKED_DIFF_MACHINES = 3
# ボーナス確率から設定を読めるのはノーマル機（ジャグ・ハナハナ・沖ドキ・A タイプ）だけ。
# 擬似ボーナスの AT 機は BB/RB 回数が仕様値なので、同じ表に混ぜない。
NORMAL_MACHINE_CATEGORIES = ("jug", "hana", "oki", "bt")
# RBが1回も出ていない機種を「RB契機がない」と断定してよい累計G数の下限。
RB_ABSENT_MIN_GAMES = 3000


def rank_rows(
    rows: Iterable[dict[str, Any]],
    key: str,
    *,
    reverse: bool,
    min_count_key: str | None = None,
    min_count: int = 0,
) -> list[dict[str, Any]]:
    valid = [
        row
        for row in rows
        if row.get(key) is not None and (min_count_key is None or (row.get(min_count_key) or 0) >= min_count)
    ]
    ordered = sorted(valid, key=lambda row: row[key], reverse=reverse)
    return [{"rank": index, **row} for index, row in enumerate(ordered, 1)]


def source_time_label(row: dict[str, Any]) -> str:
    jackpot = row.get("jackpot_update_time") or "不明"
    highest = row.get("highest_update_time") or "不明"
    graph = row.get("graph_update_time") or "不明"
    return f"大当り {jackpot} / 最高出玉 {highest} / グラフ {graph}"


def normal_machine_models(models: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [model for model in models if model.get("machine_category") in NORMAL_MACHINE_CATEGORIES]


def rb_absent_models(models: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """ノーマル機とされているのにRBが全台0回の機種。マスターの区分誤りを疑う。

    累計G下限を課さないと、開店直後や設置1台の機種が「まだRBを引いていない」だけで
    区分誤りと名指しされる。実測（2026-08-17 13:55）では、構造的にRBがないエウレカ
    TYPE-ARTが43,499G/RB0だったのに対し、誤検出された4機種は93〜696Gだった。
    最も重いノーマル機でもRB確率は1/600程度なので、3,000Gあれば期待5回は出る。
    """
    return [
        model
        for model in normal_machine_models(models)
        if not (model.get("total_rb") or 0) and (model.get("total_games") or 0) >= RB_ABSENT_MIN_GAMES
    ]


def probability_ranking_models(models: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """ボーナス確率で設定を読める機種だけを返す。

    ノーマル機の区分に加えて、RBが全台0回の機種を落とす。RB契機のない機種は
    マスターの bt_flag が誤っていてもここで除外される（擬似ボーナスのAT機など）。
    """
    absent = {model["mdc"] for model in rb_absent_models(models)}
    return [model for model in normal_machine_models(models) if model["mdc"] not in absent]


def model_rankings(
    models: list[dict[str, Any]],
    probability_models: list[dict[str, Any]] | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """Rank models. BB/RB/合成確率だけは probability_models（既定は全機種）で集計する。"""
    probability_rows = models if probability_models is None else probability_models
    return {
        "average_games": rank_rows(models, "average_games", reverse=True),
        "bb_probability": rank_rows(probability_rows, "bb_probability", reverse=False),
        "rb_probability": rank_rows(probability_rows, "rb_probability", reverse=False),
        "combined_probability": rank_rows(probability_rows, "combined_probability", reverse=False),
        "average_highest_payout": rank_rows(models, "average_highest_payout", reverse=True),
        "average_diff": rank_rows(models, "average_diff", reverse=True),
        "win_rate": rank_rows(
            models,
            "win_rate",
            reverse=True,
            min_count_key="diff_valid_count",
            min_count=MIN_RANKED_DIFF_MACHINES,
        ),
    }


def percentile_score(values: list[float], value: float) -> float:
    if len(values) <= 1:
        return 100.0
    less = sum(candidate < value for candidate in values)
    equal = sum(candidate == value for candidate in values)
    return 100.0 * (less + (equal - 1) / 2) / (len(values) - 1)


def site_time(value: Any) -> datetime | None:
    try:
        return datetime.strptime(str(value), "%Y/%m/%d %H:%M")
    except TypeError, ValueError:
        return None


def graph_time_skew_minutes(jackpot_time: Any, graph_time: Any) -> int | None:
    """一覧とグラフの取得時刻差（符号付き・分）。正ならグラフが古い、負ならグラフが新しい。"""
    jackpot = site_time(jackpot_time)
    graph = site_time(graph_time)
    if not jackpot or not graph:
        return None
    return int((jackpot - graph).total_seconds() // 60)


def graph_age_minutes(jackpot_time: Any, graph_time: Any) -> int | None:
    """時刻差の大きさ（分）。並行収集ではグラフが新しい側にもズレるので符号を落とさず絶対値を取る。"""
    skew = graph_time_skew_minutes(jackpot_time, graph_time)
    return None if skew is None else abs(skew)


def build_three_machine_runs(
    machines: list[dict[str, Any]],
    physical_lanes: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    available = {int(machine["machine_number"]): machine for machine in machines}
    candidates: list[tuple[list[dict[str, Any]], dict[str, Any]]] = []
    if physical_lanes:
        for lane in physical_lanes:
            ordered = lane["machines"]
            lane_numbers = [int(machine["machine_number"]) for machine in ordered]
            for start_index in range(max(0, len(ordered) - 2)):
                numbers = lane_numbers[start_index : start_index + 3]
                if all(number in available for number in numbers):
                    candidates.append(
                        (
                            [available[number] for number in numbers],
                            {
                                "adjacency_mode": "physical_layout",
                                "section": lane["section"],
                                "lane_axis": lane["lane_axis"],
                                "lane_value": lane["lane_value"],
                                "_adjacency_key": lane["key"],
                                "_adjacency_start": start_index,
                                "_lane_numbers": lane_numbers,
                            },
                        )
                    )
    else:
        for start in sorted(available):
            numbers = [start, start + 1, start + 2]
            if all(number in available for number in numbers):
                candidates.append(
                    (
                        [available[number] for number in numbers],
                        {
                            "adjacency_mode": "machine_number",
                            "section": None,
                            "lane_axis": None,
                            "lane_value": None,
                        },
                    )
                )

    runs: list[dict[str, Any]] = []
    for group, adjacency in candidates:
        numbers = [int(machine["machine_number"]) for machine in group]
        model_names = list(dict.fromkeys(machine["model_name"] for machine in group))
        diff_complete = all(machine["graph_eligible"] and machine["latest_diff"] is not None for machine in group)
        graph_times = sorted({machine["graph_update_time"] for machine in group if machine["graph_update_time"]})
        ages = [machine["graph_age_minutes"] for machine in group if machine["graph_age_minutes"] is not None]
        runs.append(
            {
                "start_machine": str(numbers[0]),
                "end_machine": str(numbers[-1]),
                "machine_numbers": [str(number) for number in numbers],
                "models": model_names,
                "model_label": " / ".join(model_names),
                "total_games": sum(machine["games"] for machine in group),
                "average_games": mean_or_none(machine["games"] for machine in group),
                "diff_complete": diff_complete,
                "total_diff": (sum(machine["latest_diff"] for machine in group) if diff_complete else None),
                "average_diff": (mean_or_none(machine["latest_diff"] for machine in group) if diff_complete else None),
                "win_count": (sum(machine["win"] is True for machine in group) if diff_complete else None),
                "win_rate": (sum(machine["win"] is True for machine in group) / 3 if diff_complete else None),
                "average_highest_payout": mean_or_none(machine["highest_payout"] for machine in group),
                "graph_reused_count": sum(machine["graph_reused"] for machine in group),
                "low_confidence_count": sum(machine["diff_confidence"] == "low" for machine in group),
                "medium_confidence_count": sum(machine["diff_confidence"] == "medium" for machine in group),
                "max_graph_age_minutes": max(ages) if ages else None,
                "graph_update_time": ", ".join(graph_times),
                "machines": [
                    {
                        "machine_number": machine["machine_number"],
                        "model_name": machine["model_name"],
                        "games": machine["games"],
                        "highest_payout": machine["highest_payout"],
                        "latest_diff": machine["latest_diff"],
                        "win": machine["win"],
                    }
                    for machine in group
                ],
                **adjacency,
            }
        )

    games_values = [float(run["average_games"]) for run in runs]
    diff_values = [float(run["average_diff"]) for run in runs if run["average_diff"] is not None]
    for run in runs:
        run["games_percentile"] = percentile_score(games_values, float(run["average_games"]))
        if run["average_diff"] is not None:
            run["diff_percentile"] = percentile_score(diff_values, float(run["average_diff"]))
            run["high_rotation_high_diff_score"] = (run["games_percentile"] + run["diff_percentile"]) / 2
        else:
            run["diff_percentile"] = None
            run["high_rotation_high_diff_score"] = None
    return runs


def build_positive_blocks(runs: list[dict[str, Any]], machines: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if any(run.get("adjacency_mode") == "physical_layout" for run in runs):
        return build_physical_positive_blocks(runs, machines)

    positive = sorted(
        (run for run in runs if run["total_diff"] is not None and run["total_diff"] > 0),
        key=lambda run: int(run["start_machine"]),
    )
    intervals: list[list[int]] = []
    for run in positive:
        start, end = int(run["start_machine"]), int(run["end_machine"])
        if intervals and start <= intervals[-1][1]:
            intervals[-1][1] = max(intervals[-1][1], end)
        else:
            intervals.append([start, end])
    by_number = {int(machine["machine_number"]): machine for machine in machines}
    blocks: list[dict[str, Any]] = []
    for start, end in intervals:
        group = [by_number[number] for number in range(start, end + 1)]
        model_names = list(dict.fromkeys(machine["model_name"] for machine in group))
        graph_times = sorted({machine["graph_update_time"] for machine in group if machine["graph_update_time"]})
        confidences = [machine["diff_confidence"] for machine in group]
        ages = [machine["graph_age_minutes"] for machine in group if machine["graph_age_minutes"] is not None]
        blocks.append(
            {
                "start_machine": str(start),
                "end_machine": str(end),
                "machine_count": len(group),
                "model_label": " / ".join(model_names),
                "total_games": sum(machine["games"] for machine in group),
                "average_games": mean_or_none(machine["games"] for machine in group),
                "total_diff": sum(machine["latest_diff"] for machine in group),
                "average_diff": mean_or_none(machine["latest_diff"] for machine in group),
                "win_count": sum(machine["win"] is True for machine in group),
                "win_rate": sum(machine["win"] is True for machine in group) / len(group),
                "graph_reused_count": sum(machine["graph_reused"] for machine in group),
                "low_confidence_count": sum(value == "low" for value in confidences),
                "medium_confidence_count": sum(value == "medium" for value in confidences),
                "max_graph_age_minutes": max(ages) if ages else None,
                "graph_update_time": ", ".join(graph_times),
                "machines": [
                    {
                        "machine_number": machine["machine_number"],
                        "model_name": machine["model_name"],
                        "games": machine["games"],
                        "latest_diff": machine["latest_diff"],
                        "win": machine["win"],
                    }
                    for machine in group
                ],
            }
        )
    games_values = [float(block["average_games"]) for block in blocks]
    diff_values = [float(block["average_diff"]) for block in blocks]
    for block in blocks:
        block["games_percentile"] = percentile_score(games_values, float(block["average_games"]))
        block["diff_percentile"] = percentile_score(diff_values, float(block["average_diff"]))
        block["block_score"] = (block["games_percentile"] + block["diff_percentile"]) / 2
    return blocks


def build_physical_positive_blocks(runs: list[dict[str, Any]], machines: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_number = {int(machine["machine_number"]): machine for machine in machines}
    by_lane: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for run in runs:
        if run["total_diff"] is not None and run["total_diff"] > 0 and run.get("_adjacency_key"):
            by_lane[str(run["_adjacency_key"])].append(run)

    blocks: list[dict[str, Any]] = []
    for lane_runs in by_lane.values():
        lane_runs.sort(key=lambda row: int(row["_adjacency_start"]))
        intervals: list[list[int]] = []
        for run in lane_runs:
            start = int(run["_adjacency_start"])
            end = start + 2
            if intervals and start <= intervals[-1][1]:
                intervals[-1][1] = max(intervals[-1][1], end)
            else:
                intervals.append([start, end])

        lane_numbers = [int(number) for number in lane_runs[0]["_lane_numbers"]]
        for start, end in intervals:
            numbers = lane_numbers[start : end + 1]
            group = [by_number[number] for number in numbers]
            model_names = list(dict.fromkeys(machine["model_name"] for machine in group))
            graph_times = sorted({machine["graph_update_time"] for machine in group if machine["graph_update_time"]})
            confidences = [machine["diff_confidence"] for machine in group]
            ages = [machine["graph_age_minutes"] for machine in group if machine["graph_age_minutes"] is not None]
            blocks.append(
                {
                    "start_machine": str(numbers[0]),
                    "end_machine": str(numbers[-1]),
                    "machine_numbers": [str(number) for number in numbers],
                    "machine_count": len(group),
                    "model_label": " / ".join(model_names),
                    "section": lane_runs[0].get("section"),
                    "adjacency_mode": "physical_layout",
                    "total_games": sum(machine["games"] for machine in group),
                    "average_games": mean_or_none(machine["games"] for machine in group),
                    "total_diff": sum(machine["latest_diff"] for machine in group),
                    "average_diff": mean_or_none(machine["latest_diff"] for machine in group),
                    "win_count": sum(machine["win"] is True for machine in group),
                    "win_rate": sum(machine["win"] is True for machine in group) / len(group),
                    "graph_reused_count": sum(machine["graph_reused"] for machine in group),
                    "low_confidence_count": sum(value == "low" for value in confidences),
                    "medium_confidence_count": sum(value == "medium" for value in confidences),
                    "max_graph_age_minutes": max(ages) if ages else None,
                    "graph_update_time": ", ".join(graph_times),
                    "machines": [
                        {
                            "machine_number": machine["machine_number"],
                            "model_name": machine["model_name"],
                            "games": machine["games"],
                            "latest_diff": machine["latest_diff"],
                            "win": machine["win"],
                        }
                        for machine in group
                    ],
                }
            )

    games_values = [float(block["average_games"]) for block in blocks]
    diff_values = [float(block["average_diff"]) for block in blocks]
    for block in blocks:
        block["games_percentile"] = percentile_score(games_values, float(block["average_games"]))
        block["diff_percentile"] = percentile_score(diff_values, float(block["average_diff"]))
        block["block_score"] = (block["games_percentile"] + block["diff_percentile"]) / 2
    return blocks


def build_lane_edge_summaries(
    machines: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """列の端からの位置で集計する。プロジェクトの「角番」とは別概念なので角番とは呼ばない。"""
    groups: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for machine in machines:
        edge_rank = machine.get("lane_edge_rank")
        if isinstance(edge_rank, int) and edge_rank > 0:
            groups[edge_rank].append(machine)

    corners: list[dict[str, Any]] = []
    for corner_rank in sorted(groups):
        group = groups[corner_rank]
        valid_diffs = [
            machine["latest_diff"]
            for machine in group
            if machine["graph_eligible"] and machine["latest_diff"] is not None
        ]
        wins = sum(value > 0 for value in valid_diffs)
        total_games = sum(machine["games"] for machine in group)
        total_bb = sum(machine["bb_count"] for machine in group)
        total_rb = sum(machine["rb_count"] for machine in group)
        corners.append(
            {
                "lane_edge_rank": corner_rank,
                "lane_edge_label": f"列端{corner_rank}",
                "machine_count": len(group),
                "graph_eligible_count": sum(machine["graph_eligible"] for machine in group),
                "diff_valid_count": len(valid_diffs),
                "win_count": wins,
                "win_rate": wins / len(valid_diffs) if valid_diffs else None,
                "average_diff": mean_or_none(valid_diffs),
                "average_games": mean_or_none(machine["games"] for machine in group),
                "average_highest_payout": mean_or_none(machine["highest_payout"] for machine in group),
                "bb_probability": probability(total_games, total_bb),
                "rb_probability": probability(total_games, total_rb),
                "combined_probability": probability(total_games, total_bb + total_rb),
            }
        )
    return corners


def classify_candidates(
    machines: list[dict[str, Any]],
    models: list[dict[str, Any]],
    graph_min_games: int,
) -> None:
    """「高設定期待」と「出玉候補」を台ごとに切り分けて machine に書き込む。

    判定は累計G・累計BB・累計RBだけを使う。直近区間の不振は、固定設定を仮定する限り
    累計成績と独立した根拠にはならないため、マイナス材料として二重計上しない。
    ノーマル機はRB確率を主軸に機種平均と比べ、BBだけが機種平均より良い台は
    「出玉候補（BB偏重）」として高設定期待とは分けて表示する。
    AT機・マスター未対応機は差枚から設定を断定できないため出玉候補に留める。
    """
    model_by_mdc = {model["mdc"]: model for model in models}
    for machine in machines:
        model = model_by_mdc.get(machine["mdc"], {})
        category = machine.get("machine_category")
        track = "setting" if category in NORMAL_MACHINE_CATEGORIES else "payout"
        machine["evaluation_track"] = track

        # 確率は分母表記なので、値が小さいほど良い。正なら台のほうが機種平均より良い。
        model_rb = model.get("rb_probability")
        model_bb = model.get("bb_probability")
        rb_vs_model = (
            model_rb - machine["rb_probability"]
            if model_rb is not None and machine["rb_probability"] is not None
            else None
        )
        bb_vs_model = (
            model_bb - machine["bb_probability"]
            if model_bb is not None and machine["bb_probability"] is not None
            else None
        )
        machine["rb_vs_model"] = rb_vs_model
        machine["bb_vs_model"] = bb_vs_model

        eligible = track == "setting" and machine["games"] >= graph_min_games and rb_vs_model is not None
        machine["setting_eval_eligible"] = eligible
        bb_heavy = bool(
            eligible and bb_vs_model is not None and bb_vs_model > 0 and rb_vs_model is not None and rb_vs_model < 0
        )
        machine["bb_heavy"] = bb_heavy
        machine["setting_candidate"] = bool(eligible and rb_vs_model is not None and rb_vs_model > 0)
        machine["payout_candidate"] = bool(machine["latest_diff"] is not None and machine["latest_diff"] > 0)

        if machine["setting_candidate"]:
            label = "高設定期待(RB)"
        elif bb_heavy:
            label = "出玉候補(BB偏重)"
        elif track == "payout" and machine["payout_candidate"]:
            label = "出玉候補(設定判定外)"
        elif machine["payout_candidate"]:
            label = "出玉候補"
        else:
            label = "--"
        machine["candidate_label"] = label


def analyze(
    source: dict[str, Any],
    graph_metrics: dict[str, Any],
    reference_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    graph_min_games = int(graph_metrics.get("graphMinGames", 0) or 0)
    graph_by_key = {item["key"]: item for item in graph_metrics.get("machines", []) if item.get("status") == "ok"}
    model_values = [item for item in source["models"].values() if item.get("complete")]
    machines: list[dict[str, Any]] = []
    models: list[dict[str, Any]] = []

    for model in model_values:
        jackpot_rows = numeric_rows(model["jackpot"]["pages"])
        highest_rows = numeric_rows(model["highest"]["pages"])
        highest_by_number = {row[0]: parse_int(row[1]) for row in highest_rows if len(row) >= 2}

        model_machines: list[dict[str, Any]] = []
        for row in jackpot_rows:
            if len(row) < 4:
                continue
            machine_number = row[0]
            games = parse_int(row[1])
            bb_count = parse_int(row[2])
            rb_count = parse_int(row[3])
            art_count = parse_int(row[4]) if len(row) >= 5 else None
            if games is None or bb_count is None or rb_count is None:
                continue

            graph = graph_by_key.get(f"{model['mdc']}:{machine_number}")
            latest_diff = graph.get("estimatedLatestDiff") if graph else None
            graph_eligible = games >= graph_min_games
            machine = {
                "mdc": model["mdc"],
                "model_name": model["name"],
                "machine_number": machine_number,
                "last_digit": int(machine_number[-1]),
                "is_zorome": len(machine_number) >= 2 and machine_number[-1] == machine_number[-2],
                "games": games,
                "bb_count": bb_count,
                "rb_count": rb_count,
                "art_count": art_count,
                "bb_probability": probability(games, bb_count),
                "rb_probability": probability(games, rb_count),
                "combined_probability": probability(games, bb_count + rb_count),
                "highest_payout": highest_by_number.get(machine_number),
                "graph_eligible": graph_eligible,
                "latest_diff": latest_diff,
                "win": latest_diff > 0 if latest_diff is not None else None,
                "diff_confidence": graph.get("confidence") if graph else None,
                "graph_reused": bool(graph.get("graphReused")) if graph else False,
                "graph_captured_games": graph.get("capturedGames") if graph else None,
                "highest_reused": bool(model["highest"].get("reused")),
                "jackpot_update_time": model["jackpot"].get("updateTime"),
                "highest_update_time": model["highest"].get("updateTime"),
                "graph_update_time": graph.get("updateTime") if graph else None,
            }
            machine["graph_time_skew_minutes"] = graph_time_skew_minutes(
                machine["jackpot_update_time"], machine["graph_update_time"]
            )
            machine["graph_age_minutes"] = graph_age_minutes(
                machine["jackpot_update_time"], machine["graph_update_time"]
            )
            machine["quality_status"] = (
                "warning"
                if machine["graph_reused"]
                or machine["diff_confidence"] == "low"
                or (machine["graph_age_minutes"] or 0) > 30
                else "fresh"
            )
            machine["update_time"] = source_time_label(machine)
            model_machines.append(machine)
            machines.append(machine)

        total_games = sum(machine["games"] for machine in model_machines)
        total_bb = sum(machine["bb_count"] for machine in model_machines)
        total_rb = sum(machine["rb_count"] for machine in model_machines)
        valid_diffs = [
            machine["latest_diff"]
            for machine in model_machines
            if machine["graph_eligible"] and machine["latest_diff"] is not None
        ]
        wins = sum(value > 0 for value in valid_diffs)
        graph_times = sorted(
            {machine["graph_update_time"] for machine in model_machines if machine["graph_update_time"]}
        )
        summary = {
            "mdc": model["mdc"],
            "model_name": model["name"],
            "machine_count": len(model_machines),
            "graph_eligible_count": sum(machine["graph_eligible"] for machine in model_machines),
            "diff_valid_count": len(valid_diffs),
            "graph_reused_count": sum(
                machine["graph_eligible"] and machine["graph_reused"] for machine in model_machines
            ),
            "highest_reused": bool(model["highest"].get("reused")),
            "low_confidence_count": sum(machine["diff_confidence"] == "low" for machine in model_machines),
            "medium_confidence_count": sum(machine["diff_confidence"] == "medium" for machine in model_machines),
            "max_graph_age_minutes": max(
                (
                    machine["graph_age_minutes"]
                    for machine in model_machines
                    if machine["graph_age_minutes"] is not None
                ),
                default=None,
            ),
            "win_count": wins,
            "total_games": total_games,
            "average_games": mean_or_none(machine["games"] for machine in model_machines),
            "total_bb": total_bb,
            "total_rb": total_rb,
            "bb_probability": probability(total_games, total_bb),
            "rb_probability": probability(total_games, total_rb),
            "combined_probability": probability(total_games, total_bb + total_rb),
            "average_highest_payout": mean_or_none(machine["highest_payout"] for machine in model_machines),
            "average_diff": mean_or_none(valid_diffs),
            "win_rate": wins / len(valid_diffs) if valid_diffs else None,
            "jackpot_update_time": model["jackpot"].get("updateTime"),
            "highest_update_time": model["highest"].get("updateTime"),
            "graph_update_time": ", ".join(graph_times),
        }
        summary["update_time"] = source_time_label(summary)
        models.append(summary)

    reference_summary = {"enabled": False}
    physical_lanes: list[dict[str, Any]] | None = None
    if reference_context is not None:
        reference_summary = enrich_machines(machines, reference_context)
        physical_lanes = build_physical_lanes(machines)
        reference_summary["physical_lane_count"] = len(physical_lanes)
        first_by_mdc = {machine["mdc"]: machine for machine in machines}
        for model in models:
            mapped = first_by_mdc.get(model["mdc"], {})
            model["machine_name_normalized"] = mapped.get("machine_name_normalized")
            model["machine_category"] = mapped.get("machine_category")
            model["master_matched"] = bool(mapped.get("master_matched"))

    tail_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for machine in machines:
        tail_groups[str(machine["last_digit"])].append(machine)
        if machine["is_zorome"]:
            tail_groups["ゾロ目"].append(machine)

    tails: list[dict[str, Any]] = []
    for group_name in [str(number) for number in range(10)] + ["ゾロ目"]:
        group = tail_groups.get(group_name, [])
        valid_diffs = [
            machine["latest_diff"]
            for machine in group
            if machine["graph_eligible"] and machine["latest_diff"] is not None
        ]
        wins = sum(value > 0 for value in valid_diffs)
        tails.append(
            {
                "tail": group_name,
                "machine_count": len(group),
                "graph_eligible_count": sum(machine["graph_eligible"] for machine in group),
                "diff_valid_count": len(valid_diffs),
                "graph_reused_count": sum(machine["graph_eligible"] and machine["graph_reused"] for machine in group),
                "win_count": wins,
                "win_rate": wins / len(valid_diffs) if valid_diffs else None,
                "average_diff": mean_or_none(valid_diffs),
                "average_games": mean_or_none(machine["games"] for machine in group),
                "average_highest_payout": mean_or_none(machine["highest_payout"] for machine in group),
                "graph_update_time": ", ".join(
                    sorted({machine["graph_update_time"] for machine in group if machine["graph_update_time"]})
                ),
            }
        )

    classify_candidates(machines, models, graph_min_games)
    setting_summary = annotate_setting_estimates(machines, load_family_specs())

    main_models = [model for model in models if model["machine_count"] > 1]
    single_models = [model for model in models if model["machine_count"] == 1]
    normal_main_models = probability_ranking_models(main_models)
    normal_single_models = probability_ranking_models(single_models)
    rb_absent = rb_absent_models(models)
    # マスター未対応でカテゴリが取れないときだけ全機種にフォールバックし、その事実を記録する。
    probability_scope = "normal_only" if normal_main_models or normal_single_models else "all_models"
    corners = build_lane_edge_summaries(machines)
    three_machine_runs = build_three_machine_runs(machines, physical_lanes)
    positive_blocks = build_positive_blocks([run for run in three_machine_runs if run["diff_complete"]], machines)
    for run in three_machine_runs:
        for internal_key in ("_adjacency_key", "_adjacency_start", "_lane_numbers"):
            run.pop(internal_key, None)
    rankings = {
        "main_models": model_rankings(main_models, normal_main_models if probability_scope == "normal_only" else None),
        "single_models": model_rankings(
            single_models, normal_single_models if probability_scope == "normal_only" else None
        ),
        "tails": {
            "win_rate": rank_rows(
                tails,
                "win_rate",
                reverse=True,
                min_count_key="diff_valid_count",
                min_count=MIN_RANKED_DIFF_MACHINES,
            ),
            "average_diff": rank_rows(tails, "average_diff", reverse=True),
            "average_highest_payout": rank_rows(tails, "average_highest_payout", reverse=True),
        },
        "corners": {
            "average_diff": rank_rows(corners, "average_diff", reverse=True),
            "win_rate": rank_rows(
                corners,
                "win_rate",
                reverse=True,
                min_count_key="diff_valid_count",
                min_count=MIN_RANKED_DIFF_MACHINES,
            ),
            "average_games": rank_rows(corners, "average_games", reverse=True),
            "average_highest_payout": rank_rows(corners, "average_highest_payout", reverse=True),
        },
        "three_machine_runs": {
            "combined": rank_rows(
                [run for run in three_machine_runs if run["total_diff"] is not None and run["total_diff"] > 0],
                "high_rotation_high_diff_score",
                reverse=True,
            ),
            "average_diff": rank_rows(three_machine_runs, "average_diff", reverse=True),
            "average_games": rank_rows(three_machine_runs, "average_games", reverse=True),
            "average_highest_payout": rank_rows(three_machine_runs, "average_highest_payout", reverse=True),
        },
        "positive_blocks": rank_rows(positive_blocks, "block_score", reverse=True),
    }

    time_status = snapshot_time_status(source, graph_metrics)
    return {
        "generated_at": datetime.now().astimezone().isoformat(),
        "source_started_at": source.get("startedAt"),
        "source_completed_at": source.get("completedAt"),
        "source_complete": source.get("complete", False),
        "graph_source_complete": graph_metrics.get("sourceComplete", False),
        "graph_source_snapshot_id": graph_metrics.get("sourceSnapshotId"),
        "source_time_status": time_status,
        "graph_min_games": graph_min_games,
        "machine_rate_status": "保留（推定差枚から算出する前提条件を別途確定する）",
        "win_definition": "推定最新差枚が0枚より大きい台を勝ち台とする",
        "min_ranked_diff_machines": MIN_RANKED_DIFF_MACHINES,
        "probability_ranking_scope": probability_scope,
        "normal_machine_categories": list(NORMAL_MACHINE_CATEGORIES),
        "rb_absent_models": [
            {
                "mdc": model["mdc"],
                "model_name": model["model_name"],
                "machine_category": model.get("machine_category"),
                "machine_count": model["machine_count"],
                "total_games": model["total_games"],
                "total_bb": model["total_bb"],
            }
            for model in rb_absent
        ],
        "setting_estimate": setting_summary,
        "setting_candidate_count": sum(machine["setting_candidate"] for machine in machines),
        "payout_candidate_count": sum(machine["payout_candidate"] for machine in machines),
        "bb_heavy_count": sum(machine["bb_heavy"] for machine in machines),
        "setting_eval_eligible_count": sum(machine["setting_eval_eligible"] for machine in machines),
        "model_count": len(models),
        "main_model_count": len(main_models),
        "single_model_count": len(single_models),
        "machine_count": len(machines),
        "graph_eligible_count": sum(machine["graph_eligible"] for machine in machines),
        "diff_valid_count": sum(
            machine["graph_eligible"] and machine["latest_diff"] is not None for machine in machines
        ),
        "graph_reused_count": sum(machine["graph_eligible"] and machine["graph_reused"] for machine in machines),
        "reference": reference_summary,
        "models": models,
        "machines": machines,
        "tails": tails,
        "corner_count": len(corners),
        "corners": corners,
        "three_machine_run_count": len(three_machine_runs),
        "three_machine_runs": three_machine_runs,
        "positive_block_count": len(positive_blocks),
        "positive_blocks": positive_blocks,
        "rankings": rankings,
    }


def fmt_number(value: float | int | None, digits: int = 1) -> str:
    return "--" if value is None else f"{value:,.{digits}f}"


def fmt_probability(value: float | None) -> str:
    return "--" if value is None else f"1/{value:,.1f}"


def fmt_percent(value: float | None) -> str:
    return "--" if value is None else f"{value * 100:.1f}%"


def snapshot_time_status(source: dict[str, Any], graph_metrics: dict[str, Any]) -> dict[str, Any]:
    """Describe, but do not reject, the list/graph acquisition relationship."""
    graph_snapshot_id = graph_metrics.get("sourceSnapshotId")
    source_started_at = source.get("startedAt")
    source_completed_at = source.get("completedAt")
    same_run = graph_snapshot_id in {value for value in (source_started_at, source_completed_at) if value}
    if same_run:
        note = (
            "一覧とグラフは同じ収集ランです。大当り・最高出玉・グラフの"
            "実データ更新時刻は異なる場合があるため、各行に併記しています。"
        )
    else:
        note = (
            "一覧とグラフは別時刻の取得データです。同じランキング内で集計し、"
            "大当り・最高出玉・グラフの各時刻を行内に併記しています。"
        )
    return {
        "same_run": same_run,
        "source_started_at": source_started_at,
        "source_completed_at": source_completed_at,
        "graph_source_snapshot_id": graph_snapshot_id,
        "note": note,
    }


def model_table(
    title: str,
    rows: list[dict[str, Any]],
    value_key: str,
    value_label: str,
    formatter: Callable[[Any], str],
) -> list[str]:
    show_ranking_value = value_key not in {
        "average_diff",
        "average_games",
        "win_rate",
    }
    value_header = f" | {value_label}" if show_ranking_value else ""
    separator = "|---:" if show_ranking_value else ""
    lines = [
        f"## {title}",
        "",
        f"| 順位 | 機種 | 区分 | 台数 | 差枚対象台 | 有効差枚台 | 平均差枚 | 平均G | 勝率{value_header} | データ時刻 |",
        f"|---:|---|---|---:|---:|---:|---:|---:|---:{separator}|---|",
    ]
    for row in rows:
        ranking_value = f" | {formatter(row[value_key])}" if show_ranking_value else ""
        category = row.get("machine_category") or "未対応"
        lines.append(
            f"| {row['rank']} | {row['model_name']} | {category} | {row['machine_count']} | "
            f"{row['graph_eligible_count']} | {row['diff_valid_count']} | "
            f"{fmt_number(row['average_diff'])} | {fmt_number(row['average_games'])} | "
            f"{fmt_percent(row['win_rate'])}{ranking_value} | {row['update_time']} |"
        )
    lines.append("")
    return lines


MODEL_SECTIONS = [
    ("機種別平均G数ランキング", "average_games", "平均G数", fmt_number),
    ("機種別BB確率ランキング", "bb_probability", "BB確率", fmt_probability),
    ("機種別RB確率ランキング", "rb_probability", "RB確率", fmt_probability),
    ("機種別合成確率ランキング", "combined_probability", "合成確率", fmt_probability),
    (
        "機種別平均最高出玉ランキング",
        "average_highest_payout",
        "平均最高出玉",
        fmt_number,
    ),
    ("機種別平均差枚ランキング", "average_diff", "平均差枚", fmt_number),
    ("機種別勝率ランキング", "win_rate", "勝率", fmt_percent),
]


def build_model_report(
    result: dict[str, Any],
    ranking_key: str,
    title: str,
    scope_note: str,
    *,
    include_candidates: bool = False,
) -> str:
    lines = [
        f"# {title}",
        "",
        scope_note,
        "",
        f"差枚・勝率は{result['graph_min_games']:,}G以上の台だけを対象にしています。平均G、BB/RB確率、最高出玉は全台集計です。",
        "",
        f"勝率定義: {result['win_definition']}。差枚は出玉推移グラフ終点からの推定値です。",
        "",
        f"勝率ランキングは有効差枚台が{result['min_ranked_diff_machines']}台以上の機種だけを掲載します"
        "（1〜2台の100%を上位に並べないため）。",
        "",
        probability_scope_note(result),
        "",
        result["source_time_status"]["note"],
        "",
    ]
    rankings = result["rankings"][ranking_key]
    for section_title, key, label, formatter in MODEL_SECTIONS:
        lines.extend(model_table(section_title, rankings[key], key, label, formatter))
    if include_candidates:
        lines.extend(candidate_section(result))
    return "\n".join(lines)


def probability_scope_note(result: dict[str, Any]) -> str:
    categories = "/".join(result.get("normal_machine_categories", []))
    if result.get("probability_ranking_scope") != "normal_only":
        return (
            "警告: 機種マスターの区分が1件も取得できなかったため、BB/RB/合成確率のランキングに"
            "AT機を含む全機種が混在しています。設定推定には使えません。"
        )
    note = (
        f"BB確率・RB確率・合成確率のランキングは、ボーナス確率に設定差があるノーマル機（区分 {categories}）"
        "だけを対象にしています。擬似ボーナスのAT機はBB/RB回数が仕様値のため、同じ表に混ぜていません。"
    )
    absent = result.get("rb_absent_models", [])
    if absent:
        names = "、".join(f"{model['model_name']}（{model['machine_count']}台）" for model in absent)
        note += (
            f" また、区分上はノーマル機でもRBが全台0回の機種は除外しました: {names}。"
            "RB契機がない機種なので、機種マスターの区分が誤っている可能性があります。"
        )
    return note


def candidate_section(result: dict[str, Any]) -> list[str]:
    """高設定期待（ノーマル機のRB）と出玉候補（AT機・BB偏重）を分けて掲載する。"""
    machines = [
        machine
        for machine in result.get("machines", [])
        if machine.get("setting_candidate") or machine.get("bb_heavy") or machine.get("payout_candidate")
    ]
    setting_rows = sorted(
        (machine for machine in machines if machine.get("setting_candidate")),
        key=lambda machine: machine["rb_probability"],
    )
    payout_rows = sorted(
        (machine for machine in machines if not machine.get("setting_candidate") and machine.get("payout_candidate")),
        key=lambda machine: -(machine["latest_diff"] or 0),
    )
    lines = [
        "## 高設定期待と出玉候補",
        "",
        "判定は累計G・累計BB・累計RBだけを使います。固定設定を仮定する限り、直近区間の不振は"
        "累計成績と独立した根拠にならないため、マイナス材料として二重計上しません。",
        "",
        f"高設定期待は、ノーマル機のうち累計{result['graph_min_games']:,}G以上でRB確率が機種平均より良い台です。"
        "AT機・マスター未対応機は差枚から設定を断定できないため、出玉候補にとどめます。",
        "",
        f"### 高設定期待（RB確率が機種平均超え） {len(setting_rows)}台",
        "",
        "| 台番 | 機種 | 区分 | 累計G | BB | RB | RB確率 | 機種RB確率 | 差枚 | 判定 |",
        "|---:|---|---|---:|---:|---:|---:|---:|---:|---|",
    ]
    for machine in setting_rows:
        lines.append(_candidate_row(machine))
    lines.extend(
        [
            "",
            f"### 出玉候補（設定は断定しない） {len(payout_rows)}台",
            "",
            "| 台番 | 機種 | 区分 | 累計G | BB | RB | RB確率 | 機種RB確率 | 差枚 | 判定 |",
            "|---:|---|---|---:|---:|---:|---:|---:|---:|---|",
        ]
    )
    for machine in payout_rows:
        lines.append(_candidate_row(machine))
    lines.append("")
    return lines


def _candidate_row(machine: dict[str, Any]) -> str:
    model_rb = machine["rb_probability"] + machine["rb_vs_model"] if machine.get("rb_vs_model") is not None else None
    diff = "--" if machine["latest_diff"] is None else f"{machine['latest_diff']:+,}"
    return (
        f"| {machine['machine_number']} | {machine['model_name']} | "
        f"{machine.get('machine_category') or '未対応'} | {machine['games']:,} | "
        f"{machine['bb_count']} | {machine['rb_count']} | "
        f"{fmt_probability(machine['rb_probability'])} | {fmt_probability(model_rb)} | "
        f"{diff} | {machine['candidate_label']} |"
    )


def tail_table(
    title: str,
    rows: list[dict[str, Any]],
    value_key: str,
    value_label: str,
    formatter: Callable[[Any], str],
) -> list[str]:
    lines = [
        f"## {title}",
        "",
        "| 順位 | 末尾 | 対象台 | 差枚対象台 | 有効差枚台 | 勝ち台 | 平均差枚 | 平均G | 勝率 | 平均最高出玉 | グラフ時刻 |",
        "|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for row in rows:
        lines.append(
            f"| {row['rank']} | {row['tail']} | {row['machine_count']} | "
            f"{row['graph_eligible_count']} | {row['diff_valid_count']} | {row['win_count']} | "
            f"{fmt_number(row['average_diff'])} | {fmt_number(row['average_games'])} | "
            f"{fmt_percent(row['win_rate'])} | {fmt_number(row['average_highest_payout'])} | "
            f"{row['graph_update_time']} |"
        )
    lines.append("")
    return lines


def _segment_of(machine: dict[str, Any]) -> str:
    """ノーマル機カテゴリ(jug/hana/oki/bt)以外はAT・その他としてまとめる。

    backtest/announce.py の assign_segment と同じ切り方（末尾・角番の効果は
    セグメントで符号が反転するため、プールした集計だけで判断してはいけない。
    2026-08-07 楽園蒲田で実証済み）。
    """
    category = machine.get("machine_category")
    return category if category in NORMAL_MACHINE_CATEGORIES else "AT"


SEGMENT_LABELS = {
    "jug": "ジャグ(jug)",
    "hana": "ハナハナ(hana)",
    "oki": "沖ドキ(oki)",
    "bt": "BT(bt)",
    "AT": "AT・その他",
}


def _tail_rows_for(machines: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """末尾0〜9・ゾロ目ごとの集計行を作る（build_tail_reportの本体集計と同じロジック）。"""
    tail_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for machine in machines:
        tail_groups[str(machine["last_digit"])].append(machine)
        if machine["is_zorome"]:
            tail_groups["ゾロ目"].append(machine)

    rows: list[dict[str, Any]] = []
    for group_name in [str(number) for number in range(10)] + ["ゾロ目"]:
        group = tail_groups.get(group_name, [])
        valid_diffs = [
            machine["latest_diff"]
            for machine in group
            if machine["graph_eligible"] and machine["latest_diff"] is not None
        ]
        wins = sum(value > 0 for value in valid_diffs)
        rows.append(
            {
                "tail": group_name,
                "machine_count": len(group),
                "graph_eligible_count": sum(machine["graph_eligible"] for machine in group),
                "diff_valid_count": len(valid_diffs),
                "graph_reused_count": sum(machine["graph_eligible"] and machine["graph_reused"] for machine in group),
                "win_count": wins,
                "win_rate": wins / len(valid_diffs) if valid_diffs else None,
                "average_diff": mean_or_none(valid_diffs),
                "average_games": mean_or_none(machine["games"] for machine in group),
                "average_highest_payout": mean_or_none(machine["highest_payout"] for machine in group),
                "graph_update_time": ", ".join(
                    sorted({machine["graph_update_time"] for machine in group if machine["graph_update_time"]})
                ),
            }
        )
    return rows


def build_tail_segment_report(machines: list[dict[str, Any]]) -> str:
    """末尾別ランキングをセグメント(jug/hana/oki/bt/AT)ごとに分割する。

    全機種をプールした末尾ランキングは、ノーマル機とAT機で末尾効果の符号が
    反転する場合に打ち消し合って見えなくなる（feedback-lastdigit-kakuban-segment-split）。
    これを毎回スクラッチで確認していた作業をレポートに一本化する。
    """
    lines = [
        "# サイトセブン末尾別×セグメント別ランキング",
        "",
        "末尾の設定投入効果はセグメント（ノーマル機のjug/hana/oki/bt、擬似ボーナスのAT機）で"
        "符号が反転することがある。全機種プールの末尾別ランキング（site777_last_digit_report）"
        "だけで『末尾に仕掛けが無い』と判断しないこと。",
        "",
        "差枚・勝率は2,000G以上の台だけを対象。平均Gは全台集計。勝率ランキングは有効差枚台が"
        "3台以上の末尾だけを掲載する。",
        "",
    ]
    for segment in ("jug", "hana", "oki", "bt", "AT"):
        segment_machines = [machine for machine in machines if _segment_of(machine) == segment]
        label = SEGMENT_LABELS[segment]
        lines.append(f"## セグメント: {label}（{len(segment_machines)}台）")
        lines.append("")
        if not segment_machines:
            lines.append("該当台なし。")
            lines.append("")
            continue
        rows = _tail_rows_for(segment_machines)
        ranked_diff = rank_rows(rows, "average_diff", reverse=True)
        ranked_win = rank_rows(
            rows, "win_rate", reverse=True, min_count_key="diff_valid_count", min_count=MIN_RANKED_DIFF_MACHINES
        )
        lines.extend(tail_table(f"{label} 末尾別平均差枚", ranked_diff, "average_diff", "平均差枚", fmt_number))
        lines.extend(tail_table(f"{label} 末尾別勝率", ranked_win, "win_rate", "勝率", fmt_percent))
    return "\n".join(lines)


def build_machine_setting_summary(result: dict[str, Any]) -> list[str]:
    """スペック表がある機種を machine_name 単位で集約し、高設定寄りの台数を見る。

    site777_setting_report の台単位ランキングだけでは『どの機種に高設定が
    多く投入されているか』が読めない。BT/ジャグ/ハナハナ等RB確率で設定差が
    出る機種について、機種単位で高設定寄りの集中を確認できるようにする。
    """
    all_machines = result["machines"]
    by_name: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for machine in all_machines:
        if machine.get("setting_family_key"):
            by_name[machine["model_name"]].append(machine)

    rows = []
    for name, group in by_name.items():
        estimated = [machine for machine in group if machine.get("ml_setting") is not None]
        high = [machine for machine in estimated if machine.get("setting_lean") == "高設定寄り"]
        ratios = [machine["high_low_ratio"] for machine in estimated if machine.get("high_low_ratio") is not None]
        if not estimated:
            continue
        rows.append(
            {
                "machine_name": name,
                "n_total": len(group),
                "n_estimated": len(estimated),
                "n_high": len(high),
                "high_rate": len(high) / len(estimated),
                "mean_ratio": mean_or_none(ratios),
            }
        )
    ranked = sorted(
        rows,
        key=lambda row: (
            -row["high_rate"],
            -(row["mean_ratio"] if row["mean_ratio"] is not None else -math.inf),
        ),
    )
    lines = [
        "## 機種別 高設定寄り集計",
        "",
        "台単位のランキングだけでは『どの機種に高設定が多く投入されているか』が読めないため、"
        "スペック表がある機種を machine_name 単位で集約する。high_rateは推定成立台数のうち"
        "高/低尤度比>1.0（高設定寄り）だった割合、mean_ratioはその平均。",
        "",
        "| 機種 | 対象台数 | 推定成立 | 高設定寄り | 高設定寄り率 | 平均高/低尤度比 |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for row in ranked:
        lines.append(
            f"| {row['machine_name']} | {row['n_total']} | {row['n_estimated']} | {row['n_high']} | "
            f"{fmt_percent(row['high_rate'])} | {fmt_number(row['mean_ratio'], 2)}倍 |"
        )
    lines.append("")
    return lines


def build_tail_report(result: dict[str, Any]) -> str:
    lines = [
        "# サイトセブン末尾別ランキング",
        "",
        "末尾0～9とゾロ目は重複集計です。ゾロ目台は通常の末尾にも含まれます。",
        "",
        f"差枚・勝率は{result['graph_min_games']:,}G以上の台だけを対象にしています。平均Gと平均最高出玉は全台集計です。",
        "",
        f"勝率定義: {result['win_definition']}。差枚は出玉推移グラフ終点からの推定値です。",
        "",
        f"勝率ランキングは有効差枚台が{result['min_ranked_diff_machines']}台以上の末尾だけを掲載します。",
        "",
        result["source_time_status"]["note"],
        "",
    ]
    rankings = result["rankings"]["tails"]
    lines.extend(tail_table("末尾別勝率ランキング", rankings["win_rate"], "win_rate", "勝率", fmt_percent))
    lines.extend(
        tail_table(
            "末尾別平均差枚ランキング",
            rankings["average_diff"],
            "average_diff",
            "平均差枚",
            fmt_number,
        )
    )
    lines.extend(
        tail_table(
            "末尾別平均最高出玉ランキング",
            rankings["average_highest_payout"],
            "average_highest_payout",
            "平均最高出玉",
            fmt_number,
        )
    )
    lines.append("")
    lines.append(build_tail_segment_report(result["machines"]))
    return "\n".join(lines)


def corner_table(title: str, rows: list[dict[str, Any]]) -> list[str]:
    lines = [
        f"## {title}",
        "",
        "| 順位 | 列端位置 | 全台 | 差枚対象 | 有効差枚 | 勝ち台 | 平均差枚 | 平均G | 勝率 | 平均最高出玉 |",
        "|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in rows:
        lines.append(
            f"| {row['rank']} | {row['lane_edge_label']} | {row['machine_count']} | "
            f"{row['graph_eligible_count']} | {row['diff_valid_count']} | "
            f"{row['win_count']} | {fmt_number(row['average_diff'])} | "
            f"{fmt_number(row['average_games'])} | {fmt_percent(row['win_rate'])} | "
            f"{fmt_number(row['average_highest_payout'])} |"
        )
    lines.append("")
    return lines


def build_corner_report(result: dict[str, Any]) -> str:
    lines = [
        "# サイトセブン列端位置別ランキング",
        "",
        "列端位置はmachine_layoutの座標から島内の列を復元し、各列の両端を列端1、その内側を列端2…として計算しています。",
        "",
        "注意: これはプロジェクトの「角番」ではありません。角番はrank_from_aisle（通路角番）または"
        "rank_from_min/rank_from_max（台番号順）で定義されますが、楽園蒲田店のmachine_layoutでは"
        "rank_from_aisleが全台NULLのため、通路角番は算出できません。既存の角番分析と直接比較しないでください。",
        "",
        f"差枚・勝率は{result['graph_min_games']:,}G以上の台だけを対象にしています。平均Gと平均最高出玉は全台集計です。",
        "",
        f"勝率ランキングは有効差枚台が{result['min_ranked_diff_machines']}台以上の位置だけを掲載します。",
        "",
        result["source_time_status"]["note"],
        "",
    ]
    rankings = result["rankings"]["corners"]
    lines.extend(corner_table("列端位置別平均差枚ランキング", rankings["average_diff"]))
    lines.extend(corner_table("列端位置別勝率ランキング", rankings["win_rate"]))
    lines.extend(corner_table("列端位置別平均Gランキング", rankings["average_games"]))
    lines.extend(
        corner_table(
            "列端位置別平均最高出玉ランキング",
            rankings["average_highest_payout"],
        )
    )
    return "\n".join(lines)


def setting_table(title: str, rows: list[dict[str, Any]]) -> list[str]:
    lines = [
        f"## {title}",
        "",
        "| 順位 | 台番 | 機種 | 累計G | BB | RB | 実測BB確率 | 実測RB確率 | 最尤設定 | 否定できない設定 | 高/低 尤度比 | 判定 | 信用度 | 差枚 |",
        "|---:|---:|---|---:|---:|---:|---:|---:|:--:|:--:|---:|:--:|:--:|---:|",
    ]
    for index, row in enumerate(rows, 1):
        diff = "--" if row["latest_diff"] is None else f"{row['latest_diff']:+,}"
        ratio = "--" if row["high_low_ratio"] is None else f"{row['high_low_ratio']:,.2f}倍"
        lines.append(
            f"| {index} | {row['machine_number']} | {row['model_name']} | {row['games']:,} | "
            f"{row['bb_count']} | {row['rb_count']} | "
            f"{fmt_probability(row['bb_probability'])} | {fmt_probability(row['rb_probability'])} | "
            f"{row['ml_setting']} | {row['setting_band_label']} | {ratio} | "
            f"{row['setting_lean']} | {row['setting_confidence']} | {diff} |"
        )
    lines.append("")
    return lines


def build_setting_report(result: dict[str, Any]) -> str:
    summary = result.get("setting_estimate", {})
    if not summary.get("enabled"):
        return "# サイトセブン設定推定\n\nスペック表が見つからないため設定推定を生成していません。\n"

    machines = [machine for machine in result["machines"] if machine.get("ml_setting") is not None]
    lines = [
        "# サイトセブン設定推定",
        "",
        f"対象: スペック表のある{summary['spec_covered_machines']}台のうち、"
        f"累計{summary['min_games']:,}G以上の{summary['estimated_machines']}台。"
        f"母数不足で対象外が{summary['below_threshold_machines']}台。",
        "",
        "推定は累計G・累計BB・累計RBの二項尤度を設定1〜6で比べ、最も当てはまる設定を選びます。"
        "直近区間の成績は使いません。固定設定を仮定する限り、直近の不振は累計成績と独立した根拠にならないためです。",
        "",
        "**最尤設定を鵜呑みにしないでください。** スペック表からの合成試行では、8,000G回しても"
        "最尤設定が真の設定にぴったり一致するのは3〜4割です（6択の偶然は16.7%）。"
        "設定をピンポイントで当てるのは原理的に無理なので、順位付けは「高/低 尤度比」で行っています。",
        "",
        "高/低 尤度比は `max L(設定5,6) / max L(設定1〜4)` です。事前分布を仮定せず、観測がどちら側を"
        "どれだけ支持するかだけを表します。1.00倍を境に高設定寄り・低設定寄りが分かれ、"
        "10倍以上で信用度「高」、3倍以上で「中」、それ未満は「低」です。",
        "",
        "「否定できない設定」は、最尤設定の1/8以上の尤度を持つ設定の幅です。設定1〜6が全部残った台は"
        "「絞れず」と表示します。回転数が足りない台だけでなく、実測値が設定の中間に落ちた台も絞れません。",
        "",
        "ホールの設定配分を仮定していないので、この尤度比は「その台が高設定である確率」ではありません。"
        "実際の高設定投入率は1/6よりずっと低いはずで、絶対値ではなく台どうしの相対比較に使ってください。",
        "",
    ]

    false_rates = summary.get("false_high_rate_at_3000g", {})
    if false_rates:
        names = "、".join(
            f"{key} {rate * 100:.1f}%" for key, rate in sorted(false_rates.items(), key=lambda kv: -kv[1])
        )
        lines.extend(
            [
                f"誤警報率の目安（累計3,000G時点で、真が設定1なのに最尤が設定5-6と出る割合）: {names}。"
                "ゴーゴージャグラー3は設定間のスペック差が小さく、5,000G回しても17%残ります。",
                "",
            ]
        )

    for family_key, groups in summary.get("indistinguishable", {}).items():
        for members in groups:
            joined = "と".join(str(member) for member in members)
            lines.extend(
                [
                    f"注意: {family_key} は設定{joined}のRB確率が同一です。回転数を重ねても両者は分離できません。",
                    "",
                ]
            )

    ranked = sorted(
        machines,
        key=lambda machine: (
            -(machine["high_low_log_ratio"] if machine["high_low_log_ratio"] is not None else -math.inf),
            -machine["games"],
        ),
    )
    lines.extend(setting_table("高/低 尤度比の降順", ranked))

    reliable = [machine for machine in ranked if machine["setting_confidence"] in {"高", "中"}]
    lines.extend(setting_table(f"信用度 高・中 に限定 {len(reliable)}台", reliable))
    lines.extend(build_machine_setting_summary(result))
    return "\n".join(lines)


def three_machine_table(title: str, rows: list[dict[str, Any]]) -> list[str]:
    lines = [
        f"## {title}",
        "",
        "| 順位 | 3台並び | 島 | 機種 | 平均G | 合計G | 平均最高出玉 | 平均差枚 | 合計差枚 | 勝率 | 総合点 | 各台（G / 最高出玉 / 差枚） | グラフ時刻 |",
        "|---:|---|---|---|---:|---:|---:|---:|---:|---:|---:|---|---|",
    ]
    for row in rows:
        machine_details = []
        for machine in row["machines"]:
            diff_text = "--" if machine["latest_diff"] is None else f"{machine['latest_diff']:+,}枚"
            payout_text = "--" if machine["highest_payout"] is None else f"{machine['highest_payout']:,}枚"
            machine_details.append(
                f"{machine['machine_number']}（{machine['games']:,}G / {payout_text} / {diff_text}）"
            )
        machine_detail = " / ".join(machine_details)
        total_diff = "--" if row["total_diff"] is None else f"{row['total_diff']:+,}"
        lines.append(
            f"| {row['rank']} | {row['start_machine']}～{row['end_machine']} | "
            f"{row.get('section') or '--'} | {row['model_label']} | {fmt_number(row['average_games'])} | "
            f"{row['total_games']:,} | {fmt_number(row['average_highest_payout'])} | "
            f"{fmt_number(row['average_diff'])} | {total_diff} | {fmt_percent(row['win_rate'])} | "
            f"{fmt_number(row['high_rotation_high_diff_score'])} | "
            f"{machine_detail} | {row['graph_update_time']} |"
        )
    lines.append("")
    return lines


def positive_block_table(rows: list[dict[str, Any]]) -> list[str]:
    lines = [
        "## 重複統合・連続好調ブロック",
        "",
        "| 順位 | 連続区間 | 島 | 台数 | 機種 | 平均G | 合計差枚 | 平均差枚 | 勝率 | 総合点 | 再利用 | 品質 |",
        "|---:|---|---|---:|---|---:|---:|---:|---:|---:|---:|---|",
    ]
    for row in rows:
        quality = (
            f"低信頼 {row['low_confidence_count']} / 中 {row['medium_confidence_count']} / "
            f"最大遅れ {row['max_graph_age_minutes'] if row['max_graph_age_minutes'] is not None else '--'}分"
        )
        lines.append(
            f"| {row['rank']} | {row['start_machine']}～{row['end_machine']} | "
            f"{row.get('section') or '--'} | {row['machine_count']} | {row['model_label']} | {fmt_number(row['average_games'])} | "
            f"{row['total_diff']:+,} | {fmt_number(row['average_diff'])} | "
            f"{fmt_percent(row['win_rate'])} | {fmt_number(row['block_score'])} | "
            f"{row['graph_reused_count']} | {quality} |"
        )
    lines.append("")
    return lines


def build_three_machine_report(result: dict[str, Any]) -> str:
    reference = result.get("reference", {})
    if reference.get("enabled") and reference.get("layout_matches"):
        target_rule = "既存machine_layoutの座標上で物理的に隣接"
    else:
        target_rule = "台番号が3つ連続"
    lines = [
        "# サイトセブン3台並びランキング",
        "",
        f"対象: {target_rule}する全3台組。候補は{result['three_machine_run_count']}組です。平均G・平均最高出玉は全候補、差枚・勝率・総合点は3台すべてが{result['graph_min_games']:,}G以上かつ差枚解析済みの候補だけを集計します。",
        "",
        "機種の境界をまたぐ並びも対象です。4台以上連続する場合は、物理順で開始台を1台ずつずらした重複候補を表示します。",
        "",
        "総合ランキングは3台合計差枚がプラスの候補だけを対象とします。総合点は、全候補内における平均Gの百分位点と平均差枚の百分位点を50%ずつ平均した0～100点です。",
        "",
        "差枚は出玉推移グラフ終点からの推定値です。グラフ時刻が異なる場合は同じ行に併記します。",
        "",
        result["source_time_status"]["note"],
        "",
    ]
    rankings = result["rankings"]["three_machine_runs"]
    lines.extend(positive_block_table(result["rankings"]["positive_blocks"]))
    lines.extend(three_machine_table("高回転・高差枚 総合ランキング", rankings["combined"]))
    lines.extend(three_machine_table("3台並び平均差枚ランキング", rankings["average_diff"]))
    lines.extend(three_machine_table("3台並び平均Gランキング", rankings["average_games"]))
    lines.extend(
        three_machine_table(
            "3台並び平均最高出玉ランキング",
            rankings["average_highest_payout"],
        )
    )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="サイトセブン取得結果を分析する")
    script_dir = Path(__file__).resolve().parent
    output_dir = script_dir / "output"
    parser.add_argument("--input", type=Path, default=output_dir / "site777_full_data.json")
    parser.add_argument("--graph-input", type=Path, default=output_dir / "site777_graph_metrics_filtered.json")
    parser.add_argument("--json-output", type=Path, default=output_dir / "site777_analysis.json")
    parser.add_argument("--report-output", type=Path, default=output_dir / "site777_analysis_report.md")
    parser.add_argument(
        "--single-report-output",
        type=Path,
        default=output_dir / "site777_single_machine_report.md",
    )
    parser.add_argument(
        "--tail-report-output",
        type=Path,
        default=output_dir / "site777_last_digit_report.md",
    )
    parser.add_argument(
        "--three-machine-report-output",
        type=Path,
        default=output_dir / "site777_three_machine_report.md",
    )
    parser.add_argument(
        "--corner-report-output",
        type=Path,
        default=output_dir / "site777_corner_report.md",
    )
    parser.add_argument(
        "--setting-report-output",
        type=Path,
        default=output_dir / "site777_setting_report.md",
    )
    parser.add_argument(
        "--reference-db",
        type=Path,
        default=DEFAULT_REFERENCE_DB,
        help="配置・機種マスターだけを読み取る2026Project DB",
    )
    parser.add_argument("--machine-aliases", type=Path, default=DEFAULT_ALIAS_FILE)
    parser.add_argument("--business-date", help="配置履歴を選ぶ日付（YYYYMMDD）")
    parser.add_argument("--no-reference", action="store_true")
    args = parser.parse_args()

    source = json.loads(args.input.read_text(encoding="utf-8-sig"))
    graph_metrics = json.loads(args.graph_input.read_text(encoding="utf-8-sig"))
    if not source.get("complete"):
        raise SystemExit("途中データのためランキングを生成しません: 一覧データが未完了です")
    if not graph_metrics.get("sourceComplete") or graph_metrics.get("failed"):
        raise SystemExit("途中データのためランキングを生成しません: 差枚データが未完了です")
    reference_context = None
    if not args.no_reference:
        reference_context = load_reference_context(
            args.reference_db,
            business_date=args.business_date,
            alias_path=args.machine_aliases,
        )
    result = analyze(source, graph_metrics, reference_context)
    if result["diff_valid_count"] != result["graph_eligible_count"]:
        raise SystemExit("途中データのためランキングを生成しません: G数しきい値以上の差枚が揃っていません")

    for output_path in (
        args.json_output,
        args.report_output,
        args.single_report_output,
        args.tail_report_output,
        args.three_machine_report_output,
        args.corner_report_output,
        args.setting_report_output,
    ):
        output_path.parent.mkdir(parents=True, exist_ok=True)
    args.json_output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    args.report_output.write_text(
        build_model_report(
            result,
            "main_models",
            "サイトセブン機種別ランキング",
            f"対象: 2台以上設置の{result['main_model_count']}機種。一台機種は別レポートです。",
            include_candidates=True,
        ),
        encoding="utf-8",
    )
    args.single_report_output.write_text(
        build_model_report(
            result,
            "single_models",
            "サイトセブン一台機種ランキング",
            f"対象: 一台設置の{result['single_model_count']}機種。",
        ),
        encoding="utf-8",
    )
    args.tail_report_output.write_text(build_tail_report(result), encoding="utf-8")
    args.three_machine_report_output.write_text(build_three_machine_report(result), encoding="utf-8")
    args.corner_report_output.write_text(build_corner_report(result), encoding="utf-8")
    args.setting_report_output.write_text(build_setting_report(result), encoding="utf-8")

    print(
        json.dumps(
            {
                "model_count": result["model_count"],
                "main_model_count": result["main_model_count"],
                "single_model_count": result["single_model_count"],
                "machine_count": result["machine_count"],
                "graph_min_games": result["graph_min_games"],
                "graph_eligible_count": result["graph_eligible_count"],
                "diff_valid_count": result["diff_valid_count"],
                "json_output": str(args.json_output),
                "report_output": str(args.report_output),
                "single_report_output": str(args.single_report_output),
                "tail_report_output": str(args.tail_report_output),
                "three_machine_run_count": result["three_machine_run_count"],
                "three_machine_report_output": str(args.three_machine_report_output),
                "corner_count": result["corner_count"],
                "corner_report_output": str(args.corner_report_output),
                "setting_report_output": str(args.setting_report_output),
                "setting_estimated_machines": result["setting_estimate"]["estimated_machines"],
                "setting_spec_covered_machines": result["setting_estimate"]["spec_covered_machines"],
                "probability_ranking_scope": result["probability_ranking_scope"],
                "prefix_fallback_matches": result["reference"].get("prefix_fallback_matches"),
                "rb_absent_models": [
                    f"{item['model_name']}({item['machine_count']}台)" for item in result["rb_absent_models"]
                ],
                "setting_candidate_count": result["setting_candidate_count"],
                "payout_candidate_count": result["payout_candidate_count"],
                "master_unmatched": result["reference"].get("master_unmatched"),
                "master_unmatched_model_count": result["reference"].get("master_unmatched_model_count"),
                # config/machine_aliases.json を埋める判断ができるよう、落ちた機種名を必ず出す。
                "master_unmatched_models": [
                    f"{item['mdc']}:{item['model_name']}({item['machine_count']}台)"
                    for item in result["reference"].get("master_unmatched_models", [])
                ],
                "ambiguous_aliases": result["reference"].get("ambiguous_aliases", {}),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
