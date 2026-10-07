"""DMM latest_full/quick.json の台一覧と詳細を変換する。"""

import json
from datetime import datetime
from pathlib import Path

from .common import model_name
from ..schema import SnapshotRow, number


def adapt(path: Path, hall: str, observed_at: datetime | None = None) -> list[SnapshotRow]:
    document = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    observed = observed_at or document["observed_at"]
    details = document.get("details") or {}
    flags = [] if document.get("complete", False) else ["incomplete"]
    if document.get("failures"):
        flags.append("failures")
    result = []
    for machine in document.get("machines", []):
        unit = number(machine.get("machine_number"))
        if unit is None:
            continue
        detail = details.get(str(unit), {})
        raw = machine.get("machine_name") or detail.get("machine_name") or ""
        model = detail.get("machine_name_normalized") or machine.get("machine_name_normalized")
        if model is None:
            model = model_name(raw)
        diff = number(detail.get("latest_diff_estimated"))
        result.append(
            SnapshotRow(
                hall=hall,
                observed_at=observed,
                source_updated_at=detail.get("source_updated_at"),
                unit=unit,
                model=model,
                model_raw=raw,
                games=number(detail.get("games")),
                bb=number(detail.get("bb_count", machine.get("bb_count"))),
                rb=number(detail.get("rb_count", machine.get("rb_count"))),
                diff=diff,
                diff_kind="estimated" if diff is not None else None,
                max_payout=number(detail.get("max_payout")),
                source="dmm",
                quality_flags=flags + (["detail_missing"] if not detail else []),
            )
        )
    return result
