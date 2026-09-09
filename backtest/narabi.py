"""連番ブロック（並び）の検出と、その日次ベースレート。

なぜ要るか:
    ホール予告の中心的な主張がしばしば「4台並び×15か所」のような並びの箇所数
    なのに、announce.py は機種単位の指標しか持たず原理的に検出できない。
    2026-09-08 の楽園蒲田予告（スロパチガール来店S）がその形だったため、
    採点手順を予告登録時に凍結したうえで実装した。

    手順は rakuen__20260908__kawasakislot.json の
    unscored_claims[0].frozen_scoring_procedure に凍結済み。ここはその実装であり、
    閾値を後から動かさない。

判定の定義（凍結時に固定、実績を見る前に決めた）:
    - 同一 section 内の連続する台番号 n, n+1, ..., n+k-1 を候補にする。
      section をまたぐ連番は物理的に隣接しないので除く。
    - section は machine_layout_history から**その日のエポック**を引く。
      machine_layout は現行エポックのスナップショットしか持たないので、過去日に
      当てると工事後の配置で工事前を測ることになる。楽園蒲田は 2026-07-06 の改装で
      section 定義が書き換わっており、実際にこの取り違えで端番効果が
      +1.127pp → +0.211pp と「消えた」事故が起きている
      （database/CLAUDE.md、backtest/results/regime/FINDINGS.md 追試10）。
    - 「成立」= ブロックの全台が当日ホール中央値を上回り、かつ
      ブロック平均差枚が +1800 以上。
    - 重なるブロックは平均の高い方だけを採り、重複計上しない。

⚠️ 箇所数の絶対値だけで的中と呼ばない:
    通常日にも並びは自然発生する。同じ手順を過去の全営業日に当てて分布を出し、
    当日がその分布のどこに来るかで判断する。ベースレート無しの「15か所あった」は
    何も言っていないのと同じ。
"""

from __future__ import annotations

import argparse
import sqlite3
from collections import defaultdict
from pathlib import Path
from statistics import mean, median

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DB_DIR = PROJECT_ROOT / "db"

BLOCK_SIZE = 4
BLOCK_MEAN_THRESHOLD = 1800.0
NORMAL_KEYWORDS = ("ジャグラー", "ハナハナ", "ハナビ")


def segment_of(machine_name: str) -> str:
    return "ノーマル" if any(w in (machine_name or "") for w in NORMAL_KEYWORDS) else "AT等"


def load_day(connection: sqlite3.Connection, date: str) -> list[dict]:
    rows = connection.execute(
        """
        SELECT m.machine_number, m.machine_name, m.diff_coins_normalized,
               m.games_normalized, l.section
        FROM machine_detailed_results AS m
        LEFT JOIN machine_layout_history AS l
               ON l.machine_number = m.machine_number
              AND m.date >= l.valid_from
              AND (l.valid_to IS NULL OR m.date <= l.valid_to)
        WHERE m.date = ? AND m.games_normalized > 0
        """,
        (date,),
    ).fetchall()
    return [
        {
            "number": int(number),
            "name": name,
            "diff": diff,
            "games": games,
            "section": section,
            "segment": segment_of(name),
        }
        for number, name, diff, games, section in rows
        if str(number).strip().isdigit()
    ]


def find_blocks(machines: list[dict], size: int = BLOCK_SIZE, threshold: float = BLOCK_MEAN_THRESHOLD) -> list[dict]:
    """成立した連番ブロックを、重複を除いて返す。"""
    if not machines:
        return []
    hall_median = median(m["diff"] for m in machines)
    by_number = {m["number"]: m for m in machines}

    candidates = []
    for m in machines:
        start = m["number"]
        block = [by_number.get(start + offset) for offset in range(size)]
        if any(b is None for b in block):
            continue
        # section をまたぐ連番は物理的に隣接しない
        sections = {b["section"] for b in block}
        if len(sections) != 1 or None in sections:
            continue
        if any(b["diff"] <= hall_median for b in block):
            continue
        block_mean = mean(b["diff"] for b in block)
        if block_mean < threshold:
            continue
        candidates.append(
            {
                "start": start,
                "mean_diff": block_mean,
                "section": block[0]["section"],
                "machines": block,
                "names": sorted({b["name"] for b in block}),
                "segments": sorted({b["segment"] for b in block}),
            }
        )

    # 重なるブロックは平均の高い方だけを採る
    candidates.sort(key=lambda c: -c["mean_diff"])
    taken: list[dict] = []
    used: set[int] = set()
    for candidate in candidates:
        numbers = {b["number"] for b in candidate["machines"]}
        if numbers & used:
            continue
        taken.append(candidate)
        used |= numbers
    taken.sort(key=lambda c: c["start"])
    return taken


def baseline(
    connection: sqlite3.Connection, since: str, exclude: str, size: int, threshold: float
) -> list[tuple[str, int]]:
    dates = [
        row[0]
        for row in connection.execute(
            "SELECT DISTINCT date FROM machine_detailed_results WHERE date >= ? ORDER BY date",
            (since,),
        )
        if row[0] != exclude
    ]
    return [(d, len(find_blocks(load_day(connection, d), size, threshold))) for d in dates]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("hall")
    parser.add_argument("date", help="YYYYMMDD")
    parser.add_argument("--size", type=int, default=BLOCK_SIZE)
    parser.add_argument("--threshold", type=float, default=BLOCK_MEAN_THRESHOLD)
    parser.add_argument("--since", default="20260601", help="ベースレートの開始日")
    args = parser.parse_args()

    path = DB_DIR / (args.hall + ".db")
    connection = sqlite3.connect("file:%s?mode=ro" % path, uri=True)
    machines = load_day(connection, args.date)
    if not machines:
        print("%s のデータがありません" % args.date)
        return 1
    blocks = find_blocks(machines, args.size, args.threshold)

    hall_median = median(m["diff"] for m in machines)
    print("=" * 84)
    print("%s  %s  %d台並びの検出" % (args.hall, args.date, args.size))
    print("=" * 84)
    print(
        "成立条件: 同一section内の連番%d台、全台がホール中央値(%+.0f)超え、"
        "ブロック平均 >= %+.0f" % (args.size, hall_median, args.threshold)
    )
    print("稼働 %d台 / 成立ブロック %d か所" % (len(machines), len(blocks)))
    print()
    if blocks:
        print("%-12s %-10s %9s  %s" % ("台番号", "section", "平均差枚", "機種"))
        for b in blocks:
            span = "%d-%d" % (b["start"], b["start"] + args.size - 1)
            print(
                "%-12s %-10s %+9.0f  %s"
                % (span, b["section"] or "-", b["mean_diff"], "/".join(n[:14] for n in b["names"]))
            )
        print()
        seg = defaultdict(int)
        for b in blocks:
            seg["＋".join(b["segments"])] += 1
        print("セグメント内訳: %s" % ", ".join("%s=%d" % kv for kv in sorted(seg.items())))

    history = baseline(connection, args.since, args.date, args.size, args.threshold)
    connection.close()
    if history:
        counts = sorted(c for _d, c in history)
        n = len(counts)
        over = sum(1 for c in counts if c >= len(blocks))
        print()
        print("-" * 84)
        print("ベースレート（%s以降 %d営業日、当日を除く）" % (args.since, n))
        print(
            "  平均 %.1f か所 / 中央値 %d / 上位10%%点 %d / 最大 %d"
            % (mean(counts), counts[n // 2], counts[int(n * 0.9)], counts[-1])
        )
        print("  当日の %d か所以上になった日: %d / %d 日 (%.0f%%)" % (len(blocks), over, n, over / n * 100))
        top = sorted(history, key=lambda x: -x[1])[:5]
        print("  多かった日: %s" % ", ".join("%s(%d)" % t for t in top))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
