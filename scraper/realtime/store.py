"""上書きしないJSONLスナップショット保存。"""

import json
from datetime import datetime
from pathlib import Path

from .schema import SnapshotRow, jst_iso


def write_snapshot(rows: list[SnapshotRow], out_dir: Path, hall: str, mode: str, now: datetime) -> Path:
    directory = Path(out_dir) / "snapshots"
    directory.mkdir(parents=True, exist_ok=True)
    stamp = datetime.fromisoformat(jst_iso(now)).strftime("%Y%m%d_%H%M%S")
    stem = f"{hall}_{mode}_{stamp}"
    for index in range(10000):
        suffix = "" if index == 0 else f"_{index}"
        path = directory / f"{stem}{suffix}.jsonl"
        try:
            with path.open("x", encoding="utf-8") as stream:
                for row in rows:
                    stream.write(json.dumps(row.to_dict(), ensure_ascii=False) + "\n")
            return path
        except FileExistsError:
            continue
    raise FileExistsError("snapshot sequence exhausted")
