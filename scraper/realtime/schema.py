"""1観測時刻・1ホール・1台を表す共通行。"""

from dataclasses import asdict, dataclass, field
from datetime import datetime
import re
from typing import Literal
from zoneinfo import ZoneInfo

JST = ZoneInfo("Asia/Tokyo")


def jst_iso(value: str | datetime | None) -> str | None:
    if value is None or value == "":
        return None
    if isinstance(value, str):
        value = datetime.fromisoformat(re.sub(r"^(\d{4})\.(\d{2})\.(\d{2})", r"\1-\2-\3", value).replace("Z", "+00:00"))
    if value.tzinfo is None:
        value = value.replace(tzinfo=JST)
    return value.astimezone(JST).isoformat()


def number(value: object) -> int | None:
    if value is None or str(value).strip() in {"", "--", "-"}:
        return None
    try:
        return int(str(value).replace(",", ""))
    except ValueError:
        return None


@dataclass
class SnapshotRow:
    hall: str
    observed_at: str
    source_updated_at: str | None
    unit: int
    model: str | None
    model_raw: str
    games: int | None = None
    bb: int | None = None
    rb: int | None = None
    at_first_hits: int | None = None
    diff: int | None = None
    diff_kind: Literal["measured", "estimated"] | None = None
    max_payout: int | None = None
    source: Literal["dmm", "site777", "daidata"] = "dmm"
    quality_flags: list[str] = field(default_factory=list)
    is_new_machine: bool | None = None

    def __post_init__(self) -> None:
        self.unit = int(self.unit)
        self.observed_at = jst_iso(self.observed_at)
        self.source_updated_at = jst_iso(self.source_updated_at)
        if self.diff is None and self.diff_kind is not None:
            raise ValueError("diff_kind requires diff")
        if self.diff is not None and self.diff_kind not in {"measured", "estimated"}:
            raise ValueError("diff requires diff_kind")

    def to_dict(self) -> dict:
        return asdict(self)
