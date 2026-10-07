"""サイトセブンの台表・グラフ・収集サマリを変換する。"""

import json
from datetime import datetime
from pathlib import Path

from .common import model_name
from ..schema import SnapshotRow, number


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _updated(value: str | None) -> str | None:
    if not value:
        return None
    return datetime.strptime(value, "%Y/%m/%d %H:%M").isoformat()


def adapt(
    output_dir: Path, hall: str = "楽園蒲田店", observed_at: datetime | None = None, *, quick: bool = False
) -> list[SnapshotRow]:
    output_dir = Path(output_dir)
    quick_path = output_dir / "site777_quick_data.json"
    # quick は機種を絞った別ファイルに出る。フル収集のデータとは混ぜない。
    full = _read(quick_path if quick and quick_path.exists() else output_dir / "site777_full_data.json")
    graph = {} if quick else _read(output_dir / "site777_graph_metrics_filtered.json")
    summary = {} if quick else _read(output_dir / "site777_graph_summary_filtered.json")
    metrics = {item["key"]: item for item in graph.get("machines", [])}
    flags = []
    if not full.get("complete") or (not quick and not summary.get("complete")):
        flags.append("incomplete")
    if not quick and not summary.get("ok"):
        flags.append("graph_not_ok")
    if not quick and summary.get("stoppedAt"):
        flags.append("stopped")
    if quick and quick_path.exists():
        flags.append("rb_models_only")
    if full.get("failures") or (not quick and summary.get("failures")):
        flags.append("failures")
    observed = observed_at or full.get("completedAt") or full.get("updatedAt")
    rows = []
    for mdc, model in full.get("models", {}).items():
        raw = model.get("name") or model.get("label") or ""
        official = model_name(raw)
        jackpot = model.get("jackpot") or {}
        for page in jackpot.get("pages", []):
            for cells in page.get("rows", [])[1:]:
                unit = number(cells[0]) if cells else None
                if unit is None:
                    continue
                games = number(cells[1]) if len(cells) > 1 else None
                metric = metrics.get(f"{mdc}:{unit}", {})
                diff = None
                local_flags = flags.copy()
                if quick:
                    local_flags.append("diff_not_collected")
                elif games is None or games < 2000 or metric.get("status") != "ok" or metric.get("diffUnreliable"):
                    local_flags.append("diff_unreadable")
                elif metric.get("diffCensoredHigh") or metric.get("diffCensoredLow"):
                    local_flags.append("diff_censored")
                else:
                    diff = number(metric.get("estimatedLatestDiff"))
                    if diff is None:
                        local_flags.append("diff_unreadable")
                rows.append(
                    SnapshotRow(
                        hall=hall,
                        observed_at=observed,
                        source_updated_at=_updated(jackpot.get("updateTime")),
                        unit=unit,
                        model=official,
                        model_raw=raw,
                        games=games,
                        bb=number(cells[2]) if len(cells) > 2 else None,
                        rb=number(cells[3]) if len(cells) > 3 else None,
                        at_first_hits=number(cells[4]) if len(cells) > 4 else None,
                        diff=diff,
                        diff_kind="estimated" if diff is not None else None,
                        source="site777",
                        quality_flags=local_flags,
                    )
                )
    return rows
