"""ユーザーが指定した要注目日を、朝の予測文書の先頭に機械的に出す。

記憶に頼ると見落とす(2026-11-07 にみとやの7のつく日を見落とした)ので、日付で必ず出す。
載せるのは指定の事実と過去の数字だけで、推す判断は書かない。少台数機種で、後から期間を
選んだ観察なので、`判断:` の行に入れるかは人が決める。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

RECENT_DAYS = 6
WATCHES = (
    {
        "hall": "みとや大森町店",
        "label": "みとやの7のつく日",
        "days": ("07", "17", "27"),
        "source": "ユーザー指定 2026-10-28",
        "machines": ("うみねこのなく頃に2", "獣王"),
    },
)


def _machine_cell(rows: list[int]) -> str:
    if not rows:
        return "-"
    wins = sum(1 for diff in rows if diff > 0)
    return "%d/%d台勝ち、平均 %+d" % (wins, len(rows), round(sum(rows) / len(rows)))


def _history(db_path: Path, watch: dict, today: str) -> list[str]:
    conn = sqlite3.connect("file:%s?mode=ro" % db_path, uri=True)
    try:
        dates = [
            row[0]
            for row in conn.execute(
                "SELECT DISTINCT date FROM machine_detailed_results WHERE date < ? ORDER BY date DESC", (today,)
            )
            if row[0][-2:] in watch["days"]
        ][:RECENT_DAYS]
        if not dates:
            return []
        lines = [
            "| 日 | ホール平均 | %s |" % " | ".join(watch["machines"]),
            "|---|---:|%s" % ("---:|" * len(watch["machines"])),
        ]
        for day in dates:
            mean = conn.execute(
                "SELECT AVG(diff_coins_normalized) FROM machine_detailed_results WHERE date = ?", (day,)
            ).fetchone()[0]
            cells = []
            for name in watch["machines"]:
                rows = conn.execute(
                    "SELECT diff_coins_normalized FROM machine_detailed_results WHERE date = ? AND machine_name = ?",
                    (day, name),
                ).fetchall()
                cells.append(_machine_cell([row[0] for row in rows if row[0] is not None]))
            lines.append("| %s/%s | %+d | %s |" % (day[4:6].lstrip("0"), day[6:], round(mean), " | ".join(cells)))
        return lines
    finally:
        conn.close()


def watch_note(today: str, db_dir: Path) -> str:
    """今日が要注目日なら文書の先頭に置く文章を返す。該当しなければ空文字。"""
    parts = []
    shown = "%d/%d" % (int(today[4:6]), int(today[6:]))
    for watch in WATCHES:
        if today[-2:] not in watch["days"]:
            continue
        head = (
            "**要注目: %s(%s)**。%s。名指し: %s。推しかどうかは人が決める(少台数機種で、後から期間を選んだ観察)。"
            % (
                watch["label"],
                shown,
                watch["source"],
                "・".join(watch["machines"]),
            )
        )
        try:
            table = _history(db_dir / ("%s.db" % watch["hall"]), watch, today)
        except sqlite3.Error as exc:
            table = ["過去の成績を読めなかった: %s" % exc]
        parts.append("\n\n".join([head, "\n".join(table)]) if table else head)
    return "\n\n".join(parts)
