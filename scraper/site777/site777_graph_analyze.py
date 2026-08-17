from __future__ import annotations

import argparse
import json
import math
import re
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from PIL import Image


MODULE_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = MODULE_DIR / "output"
DEFAULT_OCR = OUTPUT_DIR / "site777_graph_ocr.json"
DEFAULT_GRAPH_DATA = OUTPUT_DIR / "site777_graph_data.json"
DEFAULT_TARGET_CONFIG = OUTPUT_DIR / "site777_graph_targets.json"
DEFAULT_OUTPUT = OUTPUT_DIR / "site777_graph_metrics.json"


def numeric_value(text: str) -> int | None:
    normalized = text.strip().replace("−", "-").replace("—", "-")
    normalized = re.sub(r"[^0-9,.-]", "", normalized)
    if not normalized or normalized in {"-", ".", ","}:
        return None
    sign = -1 if normalized.startswith("-") else 1
    digits = re.sub(r"[^0-9]", "", normalized)
    if not digits:
        return None
    return sign * int(digits)


def words(item: dict) -> list[dict]:
    return [word for line in item.get("lines", []) for word in line.get("words", [])]


def axis_points(item: dict, width: int, height: int) -> list[tuple[float, float, str]]:
    found: list[tuple[float, float, str]] = []
    for word in words(item):
        x = float(word["x"])
        y = float(word["y"]) + float(word["height"]) / 2
        value = numeric_value(str(word["text"]))
        if value is None:
            continue
        if x <= width * 0.24 and y <= height * 0.98 and abs(value) >= 100:
            found.append((y, float(value), str(word["text"])))
    found.sort()
    return found


def fit_axis(points: list[tuple[float, float, str]], height: int) -> tuple[float, float] | None:
    if len(points) == 1:
        y, value, _ = points[0]
        span = height * 0.847
        slope = -2.0 * abs(value) / span
        return slope, float(value - slope * y)
    if len(points) < 2:
        return None
    ys = np.array([point[0] for point in points], dtype=float)
    values = np.array([point[1] for point in points], dtype=float)
    if np.ptp(ys) < 20 or np.ptp(values) < 100:
        return None
    slope, intercept = np.polyfit(ys, values, 1)
    if slope >= 0:
        return None
    return float(slope), float(intercept)


def trace_masks(rgb: np.ndarray) -> dict[str, np.ndarray]:
    """推移線の色ごとのマスク。サイト側が線色を変えるので複数色を許容する。

    2026-08-17にサイトセブンが線色を青紫(103,99,245)系から橙(251,134,103)系へ変更した。
    橙は黄色マスクの (green - blue) >= 50 に僅差で外れ、検出0で全143台が
    trace_unreadable になった。線色を1つに決め打ちしないこと。
    """
    red = rgb[:, :, 0].astype(np.int16)
    green = rgb[:, :, 1].astype(np.int16)
    blue = rgb[:, :, 2].astype(np.int16)
    return {
        "purple": (red >= 120) & (blue >= 150) & (green <= 180) & ((red - green) >= 25) & ((blue - green) >= 35),
        "blue": (blue >= 150) & ((blue - red) >= 60) & ((blue - green) >= 60),
        "yellow": (
            (red >= 150)
            & (green >= 80)
            & (green <= 220)
            & (blue <= 140)
            & ((red - blue) >= 70)
            & ((green - blue) >= 50)
        ),
        # 背景(245,236,231)と灰の軸(153,153,153)は赤緑差が10未満なので拾わない。
        "orange": (red >= 150) & ((red - green) >= 60) & ((red - blue) >= 60),
    }


def trace_color_counts(rgb: np.ndarray) -> dict[str, int]:
    return {name: int(mask.sum()) for name, mask in trace_masks(rgb).items()}


def colored_trace(rgb: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    combined = np.zeros(rgb.shape[:2], dtype=bool)
    for mask in trace_masks(rgb).values():
        combined |= mask
    return np.where(combined)


def maximum_label(item: dict, width: int, height: int) -> int | None:
    candidates: list[tuple[float, int]] = []
    for word in words(item):
        x = float(word["x"])
        y = float(word["y"]) + float(word["height"]) / 2
        value = numeric_value(str(word["text"]))
        if value is not None and x > width * 0.24 and y > height * 0.68 and value >= 0:
            candidates.append((x, value))
    return candidates[-1][1] if candidates else None


def round_ten(value: float) -> int:
    return int(round(value / 10.0) * 10)


def analyze_image(image_path: Path, ocr_item: dict) -> dict:
    rgb = np.asarray(Image.open(image_path).convert("RGB"))
    height, width = rgb.shape[:2]
    points = axis_points(ocr_item, width, height)
    fit = fit_axis(points, height)
    ys, xs = colored_trace(rgb)

    result = {
        "status": "ok",
        "axisLabels": [{"y": round(y, 2), "value": int(value), "text": text} for y, value, text in points],
        "purplePixels": int(xs.size),
        "tracePixels": int(xs.size),
        # 線色が変わったときに tracePixels=0 だけを見て白紙と誤診しないための内訳。
        "traceColorCounts": trace_color_counts(rgb),
    }
    if fit is None:
        return {**result, "status": "axis_unreadable"}
    if xs.size < 5:
        return {**result, "status": "trace_unreadable"}

    slope, intercept = fit
    last_x = int(xs.max())
    endpoint_ys = ys[xs >= last_x - 1]
    endpoint_y = float(np.median(endpoint_ys))
    raw_latest = slope * endpoint_y + intercept
    pixel_resolution = abs(slope)
    estimated_latest = round_ten(raw_latest)

    trace_values = slope * ys.astype(float) + intercept
    graph_max = float(np.max(trace_values))
    label_max = maximum_label(ocr_item, width, height)
    max_error = abs(graph_max - label_max) if label_max is not None else None
    tolerance = max(250.0, pixel_resolution * 5)
    if label_max is not None and max_error <= tolerance and xs.size >= 20:
        confidence = "high"
    elif xs.size >= 10:
        confidence = "medium"
    else:
        confidence = "low"

    result.update(
        {
            "latestX": last_x,
            "latestY": round(endpoint_y, 2),
            "rawLatestDiff": round(raw_latest, 2),
            "estimatedLatestDiff": estimated_latest,
            "win": estimated_latest > 0,
            "nearZero": abs(raw_latest) <= pixel_resolution,
            "pixelResolution": round(pixel_resolution, 2),
            "graphMaximum": round(graph_max, 2),
            "ocrMaximum": label_max,
            "maximumError": round(max_error, 2) if max_error is not None else None,
            "confidence": confidence,
        }
    )
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Estimate latest coin difference from Site Seven graph images.")
    parser.add_argument("--ocr", type=Path, default=DEFAULT_OCR)
    parser.add_argument("--graph-data", type=Path, default=DEFAULT_GRAPH_DATA)
    parser.add_argument("--target-config", type=Path, default=DEFAULT_TARGET_CONFIG)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)

    ocr_document = json.loads(args.ocr.read_text(encoding="utf-8-sig"))
    graph_document = json.loads(args.graph_data.read_text(encoding="utf-8-sig"))
    target_config = json.loads(args.target_config.read_text(encoding="utf-8-sig"))
    ocr_by_file = {item["fileName"]: item for item in ocr_document["items"]}

    prior: dict[str, dict] = {}
    if args.output.exists():
        old = json.loads(args.output.read_text(encoding="utf-8-sig"))
        prior = {item["key"]: item for item in old.get("machines", [])}

    results: list[dict] = []
    processed_this_run = 0
    collected_by_key = graph_document.get("machines", {})
    for target in sorted(target_config.get("targets", []), key=lambda item: item["key"]):
        key = target["key"]
        if target.get("action") == "reuse":
            old = prior.get(key)
            if old and old.get("status") == "ok" and old.get("estimatedLatestDiff") is not None:
                results.append(
                    {
                        **old,
                        "key": key,
                        "mdc": target["mdc"],
                        "modelName": target.get("modelName"),
                        "machineNumber": target["machineNumber"],
                        "graphReused": True,
                        "reuseReason": target.get("reason"),
                        "currentGames": target.get("games"),
                        "capturedGames": (old.get("capturedGames") or old.get("currentGames") or target.get("games")),
                    }
                )
            else:
                results.append(
                    {
                        "key": key,
                        "mdc": target["mdc"],
                        "modelName": target.get("modelName"),
                        "machineNumber": target["machineNumber"],
                        "status": "missing_reuse_source",
                        "graphReused": True,
                        "reuseReason": target.get("reason"),
                        "currentGames": target.get("games"),
                    }
                )
            continue

        machine = collected_by_key.get(key)
        if not machine:
            results.append(
                {
                    "key": key,
                    "mdc": target["mdc"],
                    "modelName": target.get("modelName"),
                    "machineNumber": target["machineNumber"],
                    "status": "missing_collected_graph",
                    "graphReused": False,
                    "reuseReason": target.get("reason"),
                    "currentGames": target.get("games"),
                }
            )
            continue
        image_path = Path(machine["imagePath"])
        if not image_path.is_absolute():
            image_path = MODULE_DIR / image_path
        file_name = image_path.name
        ocr_item = ocr_by_file.get(file_name)
        if not image_path.exists() or not ocr_item or ocr_item.get("error"):
            metrics = {"status": "missing_input"}
        else:
            # 検出ロジックを変えたらこのバージョンを上げる。上げないと過去の解析結果が
            # そのまま再利用され、修正が既存画像に適用されない。v6=橙の推移線に対応。
            signature = f'v6:{ocr_item.get("lastWriteTimeUtc")}:{ocr_item.get("length")}'
            old = prior.get(key)
            if old and old.get("inputSignature") == signature:
                results.append(
                    {
                        **old,
                        "mdc": machine["mdc"],
                        "modelName": machine["modelName"],
                        "machineNumber": machine["machineNumber"],
                        "updateTime": machine.get("updateTime"),
                        "imagePath": machine["imagePath"],
                        "graphReused": False,
                        "reuseReason": target.get("reason"),
                        "currentGames": target.get("games"),
                        "capturedGames": target.get("games"),
                    }
                )
                continue
            metrics = analyze_image(image_path, ocr_item)
            total_games = numeric_value(str(machine.get("lamp", {}).get("totalGames", "")))
            if metrics.get("status") == "trace_unreadable" and total_games == 0:
                metrics.update(
                    {
                        "status": "ok",
                        "rawLatestDiff": 0.0,
                        "estimatedLatestDiff": 0,
                        "win": False,
                        "nearZero": True,
                        "confidence": "high",
                        "zeroGames": True,
                    }
                )
            metrics["inputSignature"] = signature
            processed_this_run += 1

        results.append(
            {
                "key": key,
                "mdc": machine["mdc"],
                "modelName": machine["modelName"],
                "machineNumber": machine["machineNumber"],
                "updateTime": machine.get("updateTime"),
                "imagePath": machine["imagePath"],
                "graphReused": False,
                "reuseReason": target.get("reason"),
                "currentGames": target.get("games"),
                "capturedGames": target.get("games"),
                **metrics,
            }
        )

    ok = [item for item in results if item.get("status") == "ok"]
    document = {
        "version": 3,
        "updatedAt": datetime.now(timezone.utc).isoformat(),
        "sourceComplete": bool(graph_document.get("complete")),
        "sourceSnapshotId": graph_document.get("sourceSnapshotId"),
        "sourceStartedAt": graph_document.get("sourceStartedAt"),
        "sourceCompletedAt": graph_document.get("sourceCompletedAt"),
        "graphMinGames": graph_document.get("graphMinGames", 0),
        "allMachineCount": graph_document.get("allMachineCount"),
        "targetCount": target_config.get("targetCount", len(results)),
        "collectTargetCount": target_config.get("collectTargetCount", 0),
        "reuseCount": sum(item.get("graphReused") for item in results),
        "collectedCount": sum(not item.get("graphReused") for item in results),
        "excludedCount": graph_document.get("excludedCount"),
        "total": len(results),
        "successful": len(ok),
        "failed": len(results) - len(ok),
        "processedThisRun": processed_this_run,
        "confidence": {
            level: sum(item.get("confidence") == level for item in ok) for level in ("high", "medium", "low")
        },
        "machines": results,
    }
    args.output.write_text(json.dumps(document, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "total": document["total"],
                "successful": document["successful"],
                "failed": document["failed"],
                "processedThisRun": processed_this_run,
                "collected": document["collectedCount"],
                "reused": document["reuseCount"],
                "confidence": document["confidence"],
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
