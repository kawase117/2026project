"""みとやの21.3円スロットCSVを変換する。"""

import csv
from datetime import datetime
from pathlib import Path

from .common import model_name
from ..schema import SnapshotRow, number


def adapt(path: Path, hall: str = "みとや大森町店", observed_at: datetime | None = None) -> list[SnapshotRow]:
    result = []
    with Path(path).open(encoding="utf-8-sig", newline="") as stream:
        for item in csv.DictReader(stream):
            if item.get("Price") not in {"21.3", "21.30"}:
                continue
            unit = number(item.get("Unit"))
            if unit is None:
                continue
            raw = item.get("Machine") or ""
            result.append(
                SnapshotRow(
                    hall=hall,
                    observed_at=observed_at or item["ObservedAt"],
                    source_updated_at=None,
                    unit=unit,
                    model=model_name(raw),
                    model_raw=raw,
                    games=number(item.get("CumulativeStart")),
                    bb=number(item.get("BBCount")),
                    rb=number(item.get("RBCount")),
                    max_payout=number(item.get("MaxPayout")),
                    source="daidata",
                )
            )
    return result
