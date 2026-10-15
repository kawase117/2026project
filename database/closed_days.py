"""休業日・改装日の台帳(document/registry/KNOWN_CLOSED_DAYS.csv)を読む。

なぜ要るか:
    ana-slo は休業日にも「全台 G数0・差枚が全台同じ値(-6,142 等)」のページを出す。
    楽園蒲田店の 2025-04-21(入替)・2026-07-06(改装)はこれが取り込まれていたので、
    database/migrate_exclude_closed_days.py で DB から外し、元 JSON を data/<ホール>/_excluded/ に移した。
    増分取り込み(incremental_db_updater)は「JSON はあるが DB に無い日」を新規として拾うので、
    JSON が何かの拍子に元の場所へ戻っても再投入しないよう、台帳の日は取り込まない(二重の安全網)。

台帳(CSV): hall_name,date(YYYY-MM-DD),reason,source。reason に「休業日(入替)」「休業日(改装)」のように種類を書く。
監査(data_audit)も同じ台帳を読み、台帳の日を欠けとして扱わない。
"""

from __future__ import annotations

import csv
from pathlib import Path

DEFAULT_PATH = Path(__file__).resolve().parents[1] / "document" / "registry" / "KNOWN_CLOSED_DAYS.csv"


def closed_dates(hall: str, path: Path = DEFAULT_PATH) -> dict[str, str]:
    """そのホールの {YYYYMMDD: 理由}。ホール名は大文字小文字を区別しない(ARROW 対策)。"""
    path = Path(path)
    if not path.exists():
        return {}
    key = hall.lower()
    out: dict[str, str] = {}
    with path.open(encoding="utf-8-sig") as f:
        for rec in csv.DictReader(f):
            day = (rec.get("date") or "").strip().replace("-", "")
            if (rec.get("hall_name") or "").strip().lower() == key and len(day) == 8 and day.isdigit():
                out[day] = (rec.get("reason") or "").strip()
    return out
