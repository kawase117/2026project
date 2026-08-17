from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


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


def numeric_rows(pages: list[dict[str, Any]]) -> list[list[str]]:
    rows: list[list[str]] = []
    for page in pages:
        for row in page.get("rows", []):
            if row and str(row[0]).strip().isdigit():
                rows.append([str(value).strip() for value in row])
    return rows


def update_date(value: Any) -> str | None:
    match = re.search(r"(\d{4}/\d{2}/\d{2})", str(value or ""))
    return match.group(1) if match else None


def machine_key(item: dict[str, Any]) -> str | None:
    key = item.get("key")
    if key:
        return str(key)
    mdc = item.get("mdc")
    machine_number = item.get("machine_number", item.get("machineNumber"))
    if mdc is None or machine_number is None:
        return None
    return f"{mdc}:{machine_number}"


def build_config(
    source: dict[str, Any],
    min_games: int,
    shared_interval_ms: int = 2500,
    prior_analysis: dict[str, Any] | None = None,
    prior_metrics: dict[str, Any] | None = None,
    force_all_graphs: bool = False,
    allow_incomplete: bool = False,
) -> dict[str, Any]:
    if not source.get("complete") and not allow_incomplete:
        raise ValueError("full data is incomplete")
    source_id = (
        source.get("startedAt") or source.get("completedAt") or source.get("updatedAt")
        if allow_incomplete
        else source.get("completedAt") or source.get("updatedAt")
    )
    if not source_id:
        raise ValueError("full data has no snapshot timestamp")

    prior_analysis_by_key = {
        key: item for item in (prior_analysis or {}).get("machines", []) if (key := machine_key(item))
    }
    prior_metrics_by_key = {
        key: item for item in (prior_metrics or {}).get("machines", []) if (key := machine_key(item))
    }

    targets: list[dict[str, Any]] = []
    all_machine_count = 0
    for model in source.get("models", {}).values():
        for row in numeric_rows(model.get("jackpot", {}).get("pages", [])):
            all_machine_count += 1
            games = parse_int(row[1])
            if games is None or games < min_games:
                continue
            machine_number = row[0]
            key = f"{model['mdc']}:{machine_number}"
            jackpot_update_time = model.get("jackpot", {}).get("updateTime")
            previous_machine = prior_analysis_by_key.get(key)
            previous_metric = prior_metrics_by_key.get(key)
            previous_games = parse_int(previous_machine.get("games") if previous_machine else None)
            same_date = update_date(jackpot_update_time) and update_date(jackpot_update_time) == update_date(
                previous_machine.get("jackpot_update_time") if previous_machine else None
            )
            reusable_metric = bool(
                previous_metric
                and previous_metric.get("status") == "ok"
                and previous_metric.get("estimatedLatestDiff") is not None
            )
            if force_all_graphs:
                action, reason = "collect", "forced"
            elif not previous_machine:
                action, reason = "collect", "prior_machine_missing"
            elif not same_date:
                action, reason = "collect", "business_date_changed"
            elif previous_games is None:
                action, reason = "collect", "prior_games_missing"
            elif games < previous_games:
                action, reason = "collect", "games_decreased"
            elif games != previous_games:
                action, reason = "collect", "games_changed"
            elif not reusable_metric:
                action, reason = "collect", "prior_graph_unusable"
            else:
                action, reason = "reuse", "games_unchanged"
            targets.append(
                {
                    "key": key,
                    "mdc": str(model["mdc"]),
                    "modelName": model.get("name"),
                    "machineNumber": machine_number,
                    "games": games,
                    "jackpotUpdateTime": jackpot_update_time,
                    "action": action,
                    "reason": reason,
                    "priorGames": previous_games,
                }
            )

    safe_source_id = re.sub(r"[^0-9A-Za-z_-]", "", str(source_id))
    return {
        "version": 2,
        "sourceSnapshotId": source_id,
        "sourceComplete": bool(source.get("complete")),
        "sourceStartedAt": source.get("startedAt"),
        "sourceCompletedAt": source.get("completedAt"),
        "expectedMachineCount": source.get("expectedMachineCount"),
        "completedMachineCount": all_machine_count,
        "graphMinGames": min_games,
        "sharedIntervalMs": shared_interval_ms,
        "allMachineCount": all_machine_count,
        "targetCount": len(targets),
        "collectTargetCount": sum(target["action"] == "collect" for target in targets),
        "reuseCount": sum(target["action"] == "reuse" for target in targets),
        "excludedCount": all_machine_count - len(targets),
        "targetModelCount": len({target["mdc"] for target in targets}),
        "collectModelCount": len({target["mdc"] for target in targets if target["action"] == "collect"}),
        "imageDirectory": f"site777_graphs_filtered/{safe_source_id}_{min_games}G",
        "targets": targets,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Build Site Seven graph targets from full data.")
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--min-games", type=int, default=2000)
    parser.add_argument("--interval-ms", type=int, default=2500)
    parser.add_argument("--prior-analysis", type=Path)
    parser.add_argument("--prior-metrics", type=Path)
    parser.add_argument("--force-all-graphs", action="store_true")
    parser.add_argument("--allow-incomplete", action="store_true")
    args = parser.parse_args()
    if args.min_games < 0:
        raise SystemExit("--min-games must be non-negative")

    source = json.loads(args.input.read_text(encoding="utf-8-sig"))
    if args.interval_ms < 1000:
        raise SystemExit("--interval-ms must be at least 1000")
    prior_analysis = (
        json.loads(args.prior_analysis.read_text(encoding="utf-8-sig"))
        if args.prior_analysis and args.prior_analysis.exists()
        else None
    )
    prior_metrics = (
        json.loads(args.prior_metrics.read_text(encoding="utf-8-sig"))
        if args.prior_metrics and args.prior_metrics.exists()
        else None
    )
    config = build_config(
        source,
        args.min_games,
        args.interval_ms,
        prior_analysis,
        prior_metrics,
        args.force_all_graphs,
        args.allow_incomplete,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(config, ensure_ascii=True, indent=2), encoding="utf-8")
    print(json.dumps(config | {"targets": None}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
