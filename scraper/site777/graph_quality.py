"""出玉推移グラフから読んだ差枚の品質判定。

サイトセブンのグラフ画像は縦軸が ±5,000枚で固定されている。これを超えた台は推移線の
終点が上端（下端）に張り付き、差枚の推定値は +4,900〜+5,000 付近で頭打ちになる。
2026-09-13 19:25 のランでは 267台中12台が上端に張り付いており（例: 2119 は最高出玉
11,415枚）、そのままでは機種平均・並びブロック合計が過小に出ていた。

もう一つの罠は軸ラベルのOCR誤読。2119 は「5,000」を「500」と読み、軸の縮尺が
1/10 になって、上端に張り付いた台の差枚が +600 と出ていた。軸は固定なので、ラベルの
値が ±5,000 以外なら誤読とみなし、ラベル間のピクセル間隔が他の台と一致するときだけ
固定軸で補正する。間隔も合わないなら縮尺を信用せず、差枚を「読取不能」と印を付ける。

ana-slo の DB 側のクリップ（backtest/censoring.py の +15,477）とは別物。混同しないこと。

この判定は保存済みの axisLabels と latestY だけで計算できるので、site777_graph_analyze.py
の出力に加えて、判定フラグを持たない過去の metrics JSON にも後から適用できる。
"""

from __future__ import annotations

from typing import Any

# グラフ縦軸の上下限（枚）。サイト側で固定。
AXIS_LIMIT = 5000
# +5,000 と -5,000 のラベル中心の縦方向ピクセル間隔。19:25 ランの 267台で 316.5〜318.5。
EXPECTED_LABEL_SPACING_PX = 318.5
LABEL_SPACING_TOLERANCE_PX = 8.0
# 終点がこのピクセル数以内まで上端（下端）ラベル行に近ければ軸に張り付いたとみなす。
# 1px ≒ 31.4枚。19:25 ランでは張り付き台が y=26〜29（ラベル y=26）、張り付いていない
# 最も高い台が y=30（+4,870）だった。線の太さ（2〜3px）を見込んで 3.5px とする。
SATURATION_TOLERANCE_PX = 3.5


def _round_ten(value: float) -> int:
    return int(round(value / 10.0) * 10)


def assess_axis_labels(labels: Any) -> dict[str, Any]:
    """軸ラベルを検証し、使ってよい (y, 値) の2点を返す。

    status:
    - "ok": +5,000 / -5,000 の2ラベルで、間隔も既知の値と一致。
    - "corrected": ラベルは2つで間隔は一致するが値が ±5,000 でない（OCR誤読）。固定軸で補正した。
    - "unreliable": ラベル数か間隔が合わない。縮尺を信用できない。
    """
    points: list[tuple[float, int]] = []
    for label in labels or []:
        try:
            points.append((float(label["y"]), int(label["value"])))
        except KeyError, TypeError, ValueError:
            continue
    points.sort()
    if len(points) != 2:
        return {"status": "unreliable", "issue": f"label_count_{len(points)}", "points": points}

    (y_top, value_top), (y_bottom, value_bottom) = points
    spacing = y_bottom - y_top
    if abs(spacing - EXPECTED_LABEL_SPACING_PX) > LABEL_SPACING_TOLERANCE_PX:
        return {"status": "unreliable", "issue": f"label_spacing_{spacing:.1f}px", "points": points}
    if (value_top, value_bottom) == (AXIS_LIMIT, -AXIS_LIMIT):
        return {"status": "ok", "issue": None, "points": points}
    return {
        "status": "corrected",
        "issue": f"label_values_{value_top}_{value_bottom}",
        "points": [(y_top, AXIS_LIMIT), (y_bottom, -AXIS_LIMIT)],
    }


def assess_graph_item(item: dict[str, Any] | None) -> dict[str, Any]:
    """グラフ解析結果1台分から、補正後の差枚と品質フラグを返す。何度適用しても同じ結果になる。"""
    result: dict[str, Any] = {
        "estimated_diff": None,
        "raw_diff": None,
        "diff_censored_high": False,
        "diff_censored_low": False,
        "axis_label_suspect": False,
        "axis_label_corrected": False,
        "axis_label_issue": None,
        "diff_unreliable": False,
    }
    if not item:
        return result
    result["estimated_diff"] = item.get("estimatedLatestDiff")
    result["raw_diff"] = item.get("rawLatestDiff")
    if item.get("status") != "ok" or item.get("zeroGames") or item.get("latestY") is None:
        return result

    axis = assess_axis_labels(item.get("axisLabels"))
    if axis["status"] == "unreliable":
        result.update(axis_label_suspect=True, axis_label_issue=axis["issue"], diff_unreliable=True)
        return result

    (y1, v1), (y2, v2) = axis["points"]
    slope = (v2 - v1) / (y2 - y1)
    intercept = v1 - slope * y1
    latest_y = float(item["latestY"])
    y_high = (AXIS_LIMIT - intercept) / slope
    y_low = (-AXIS_LIMIT - intercept) / slope
    censored_high = latest_y <= y_high + SATURATION_TOLERANCE_PX
    censored_low = latest_y >= y_low - SATURATION_TOLERANCE_PX
    corrected = axis["status"] == "corrected"

    if corrected:
        raw = slope * latest_y + intercept
        result["raw_diff"] = round(raw, 2)
        result["estimated_diff"] = _round_ten(raw)
    if censored_high:
        # 真の値は +5,000 以上。下限値として +5,000 を入れ、表示側で「≥」を付ける。
        result["estimated_diff"] = AXIS_LIMIT
    elif censored_low:
        result["estimated_diff"] = -AXIS_LIMIT
    result.update(
        diff_censored_high=censored_high,
        diff_censored_low=censored_low,
        axis_label_suspect=corrected,
        axis_label_corrected=corrected,
        axis_label_issue=axis["issue"],
    )
    return result


def censor_bound(censored_high_count: int, censored_low_count: int) -> str | None:
    """打ち切られた台を含む合計・平均がどちら側の境界か。

    上端だけなら真の値は表示値以上（lower）、下端だけなら以下（upper）、
    両方を含めば上下どちらにもずれうる（indeterminate）。
    """
    if censored_high_count and censored_low_count:
        return "indeterminate"
    if censored_high_count:
        return "lower"
    if censored_low_count:
        return "upper"
    return None
