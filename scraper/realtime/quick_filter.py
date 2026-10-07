"""RB判別対象と同日観測の差分で詳細取得台を選ぶ。"""

import csv
import json
import sqlite3
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from .schema import SnapshotRow

ROOT = Path(__file__).resolve().parents[2]


def load_audit(path: Path = ROOT / "document/registry/AT_RB_AUDIT.csv") -> dict[tuple[str, str], str]:
    with Path(path).open(encoding="utf-8-sig", newline="") as stream:
        return {(r["hall"], r["machine"]): r["verdict"] for r in csv.DictReader(stream)}


def load_master_flags(db_path: Path) -> dict[str, bool]:
    if not db_path.exists():
        return {}
    try:
        with sqlite3.connect(db_path.resolve().as_uri() + "?mode=ro", uri=True) as connection:
            cols = {r[1] for r in connection.execute("PRAGMA table_info(machine_master)")}
            flags = [
                c
                for c in ("normal_flag", "bt_flag", "a_at_flag", "jug_flag", "hana_flag", "spec_category")
                if c in cols
            ]
            if not flags:
                return {}
            query = f"SELECT machine_name_normalized, {', '.join(flags)} FROM machine_master"
            return {
                r[0]: any(
                    value in {"ノーマル", "BT", "A+AT"} if col == "spec_category" else bool(value)
                    for col, value in zip(flags, r[1:], strict=True)
                )
                for r in connection.execute(query)
            }
    except sqlite3.Error:
        return {}


def load_master_flags_any(db_dir: Path = ROOT / "db") -> dict[str, bool]:
    """ホールDBが無いホール用。機種の属性(ノーマル/BT/A+AT)は機種固有なので、全ホールDBを合算する(いずれかが真なら真)。"""
    merged: dict[str, bool] = {}
    for path in sorted(Path(db_dir).glob("*.db")):
        if ".bak" in path.name:
            continue
        for name, flag in load_master_flags(path).items():
            merged[name] = merged.get(name, False) or flag
    return merged


def audit_for_hall(audit: dict[tuple[str, str], str], hall: str) -> dict[tuple[str, str], str]:
    """監査表に無いホールでは、他ホールで verdict X の機種を保守的に不可として引き継ぐ(A は引き継がない)。"""
    result = dict(audit)
    for (_, machine), verdict in audit.items():
        if verdict == "X":
            result.setdefault((hall, machine), "X")
    return result


def rb_eligible(hall: str, model: str | None, audit: dict[tuple[str, str], str], master_flags: dict[str, bool]) -> bool:
    if not model:
        return False
    verdict = audit.get((hall, model))
    if verdict == "X":
        return False
    return verdict == "A" or master_flags.get(model, False)


def changed(current: SnapshotRow, previous: SnapshotRow | None) -> bool:
    return previous is not None and any(
        getattr(current, key) != getattr(previous, key) for key in ("bb", "rb", "games")
    )


def select_units(
    rows: list[SnapshotRow],
    previous: list[SnapshotRow],
    audit: dict[tuple[str, str], str],
    master_flags: dict[str, bool],
    min_games: int = 1000,
) -> list[int]:
    if min_games < 0:
        raise ValueError("min_games must be nonnegative")
    prev = {(r.hall, r.unit): r for r in previous}
    return sorted(
        r.unit
        for r in rows
        if rb_eligible(r.hall, r.model, audit, master_flags)
        and ((r.games is not None and r.games >= min_games) or changed(r, prev.get((r.hall, r.unit))))
    )


def select_first_pass(
    rows: list[SnapshotRow],
    audit: dict[tuple[str, str], str],
    master_flags: dict[str, bool],
) -> list[int]:
    """同日の前回が無いときの対象。DMM一覧には累計Gが無いので、RB判別可能で BB+RB>=1 の台を詳細取得する。

    model が照合できない台は推定できないので対象にしない。BB+RB は対象選びにだけ使い、推定には使わない。
    """
    return sorted(
        r.unit for r in rows if rb_eligible(r.hall, r.model, audit, master_flags) and (r.bb or 0) + (r.rb or 0) >= 1
    )


def load_previous(directory: Path, hall: str, now: datetime) -> list[SnapshotRow]:
    """同ホール・同じJST暦日の最新スナップショットだけ読む。"""
    date = now.astimezone(ZoneInfo("Asia/Tokyo")).date()
    for path in sorted(Path(directory).glob(f"{hall}_*.jsonl"), reverse=True):
        try:
            items = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
            if items and datetime.fromisoformat(items[0]["observed_at"]).date() == date:
                return [SnapshotRow(**item) for item in items]
        except OSError, ValueError, TypeError, KeyError:
            continue
    return []
