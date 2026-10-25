"""日付の末尾が7・8・9の日の予測・答え合わせに添える、タコスロの機械集計(2026-10-26 追加)。

根拠と限界: document/instincts/2026-10-26-rb-judgeable-prediction-and-takoslot-h.yaml
  - 末尾7・8・9の日はタコスロのRB設定1比が1.12〜1.15と少し高かったが、区間は全体をまたぎ、後付けの観察。
  - 設定はRBの設定1比で読む(BB欄・差枚では読まない)。BB0回の台日は「設定H(ユーザー申告)」か欠損か未確定。
文書に載せるのは数字と注意書きだけで、推す・避けるの判断は書かない(prediction_ledger が拾う語を使わない)。
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

from scipy.stats import poisson

TARGET_DIGITS = ("7", "8", "9")
FIRST_DAY = "20260907"  # 全ホールの導入日。これより前は機種が存在しない
MIN_GAMES = 2000  # 設定の読みを出す最低G数(bonus_specs.MIN_GAMES_FOR_SETTING と同じ)
BB0_MIN_GAMES = 3000  # この回転数でBB0回の台日は印を付ける
# 設定1・2・5・6のRB確率(1/x)。document/machine_master_research/machine_master.csv の LBタコスロ。
RB_DENOM = {1: 352.3, 2: 336.1, 5: 312.1, 6: 300.6}
CAVEAT = (
    "注意: 設定はRBの設定1比で読む。BB欄はスペックと合わない。末尾7〜9の傾向は後付けの観察で、"
    "区間は全体をまたぐ（根拠: 2026-10-26 instinct）。設定5以上の確率は設定1・2・5・6を等確率とした事前での値で、0.5が情報なし。"
)


def is_target_day(day: str) -> bool:
    return day[-1] in TARGET_DIGITS


def p_high(games: float, rb: float) -> float:
    like = {s: poisson.pmf(int(rb), games / d) for s, d in RB_DENOM.items()}
    total = sum(like.values())
    return (like[5] + like[6]) / total if total else float("nan")


def _rows(hall_db: Path, start: str, end: str) -> list[tuple]:
    if not hall_db.exists():
        return []
    with sqlite3.connect(f"file:{hall_db}?mode=ro", uri=True) as con:
        return con.execute(
            "SELECT date, machine_number, games_normalized, bb_count, rb_count, diff_coins_normalized "
            "FROM machine_detailed_results WHERE machine_name LIKE '%タコスロ%' AND date BETWEEN ? AND ? "
            "AND games_normalized IS NOT NULL AND rb_count IS NOT NULL ORDER BY date, machine_number",
            (start, end),
        ).fetchall()


def _ratio(games: float, rb: float) -> float:
    return rb / (games / RB_DENOM[1]) if games else float("nan")


def unit_lines(rows: list[tuple]) -> list[str]:
    lines = [
        "| 台 | G | BB | RB | RB確率 | 設定1比 | 設定5以上の確率 | 差枚 | 印 |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for _, unit, games, bb, rb, diff in rows:
        diff = diff or 0
        if games < MIN_GAMES:
            lines.append(f"| {unit} | {games:.0f} | {bb} | {rb:.0f} | 2,000G未満 | - | - | {diff:+.0f} | |")
            continue
        mark = "BB0回(要確認)" if (bb == 0 and games >= BB0_MIN_GAMES) else ""
        rate = f"1/{games / rb:.0f}" if rb else "-"
        lines.append(
            f"| {unit} | {games:.0f} | {bb} | {rb:.0f} | {rate} | {_ratio(games, rb):.2f} | "
            f"{p_high(games, rb):.2f} | {diff:+.0f} | {mark} |"
        )
    return lines


def history_lines(hall_db: Path, before: str) -> list[str]:
    """before より前（導入後）の、末尾7〜9の日とそれ以外の日の台日合算。"""
    rows = [r for r in _rows(hall_db, FIRST_DAY, before) if r[0] < before and r[2] >= MIN_GAMES]
    out = []
    for label, want in (("末尾7〜9の日", True), ("それ以外の日", False)):
        part = [r for r in rows if is_target_day(r[0]) == want]
        if not part:
            out.append(f"- {label}: 該当なし")
            continue
        games = sum(r[2] for r in part)
        rb = sum(r[4] for r in part)
        days = len({r[0] for r in part})
        out.append(
            f"- {label}: {days}日・{len(part)}台日、RB設定1比 {_ratio(games, rb):.2f}（RB {rb:.0f}回/{games:.0f}G）"
        )
    return out


def takoslot_section(hall_db: Path, day: str, display: str, kind: str) -> str:
    """kind: 'answer'(day の結果を載せる) / 'prediction'(day は当日。前日の結果と、前日までの履歴を載せる)。
    対象日でない、またはそのホールにタコスロのデータが無ければ空文字。"""
    if not is_target_day(day):
        return ""
    if kind == "answer":
        rows = _rows(hall_db, day, day)
        if not rows:
            return ""
        head = f"### {display} タコスロ（{day}分、末尾{day[-1]}の日）"
        body = unit_lines(rows)
    else:
        prev_day = (datetime.strptime(day, "%Y%m%d") - timedelta(days=1)).strftime("%Y%m%d")
        if not _rows(hall_db, FIRST_DAY, prev_day):
            return ""
        rows = _rows(hall_db, prev_day, prev_day)
        head = f"### {display} タコスロ（{day}は末尾{day[-1]}の日）"
        body = [f"前日（{prev_day}）の台別:", "", *unit_lines(rows)] if rows else ["前日の台別: データなし"]
    return "\n".join([head, "", *body, "", *history_lines(hall_db, day), "", CAVEAT, ""])
