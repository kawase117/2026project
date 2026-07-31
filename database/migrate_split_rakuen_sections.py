"""楽園の統合 section を実際の列単位に分割する。

解決する問題:
    `Heatmap/generate_rakuen_kamata_coordinates.py` が背中合わせの2列を
    1つの section にまとめて生成していた（例: 1017-1036 は実際には
    1017-1026 と 1027-1036 の2列）。台番号は片側を下ってもう片側を戻る
    蛇行(U字)で振られるため、統合された section の中では

      - `rank_from_min == 1` / `rank_from_max == 1` が拾うのは
        **島の片方の端に背中合わせで並ぶ2台だけ**
      - **反対側の端の2台は順位が中央**(n/2, n/2+1)になり「最も中間」扱い

    となり、端番の定義が壊れていた。section 自体を分析単位にしている
    Hot/Cold・section×DD の集計も、実際には2列を混ぜた単位で行われていた。
    詳細: backtest/results/regime/FINDINGS.md 追試11。

やること:
    `machine_layout_history` の section / section_min / section_max /
    rank_from_min / rank_from_max を、正しい列単位で振り直す。
    行の追加・削除はしない。`machine_layout`（現行スナップショット）は
    触らない。

section の定義はホールの物理配置そのものなので座標から機械的に導出せず、
実配置の確認に基づく明示的な台番号レンジで指定する（座標が崩れている
section があり、機械的な導出では正しく分割できないため）。

使い方:
    venv\\Scripts\\python.exe -m database.migrate_split_rakuen_sections --dry-run
    venv\\Scripts\\python.exe -m database.migrate_split_rakuen_sections
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DB_PATH = PROJECT_ROOT / "db" / "楽園蒲田店.db"
HALL_NAME = "楽園蒲田店"

PRE_EPOCH = "20250101"
POST_EPOCH = "20260706"

# 分割対象の section と、その正しい列構成（台番号レンジの下限・上限）。
# ここに挙がっていない section は元から1列なので変更しない。
#
# 標準の2列島は「X列ごとに台番号が連続」という形が確認できているが、
# 座標が崩れている section（3250-3266 等）もあるため、全て明示レンジで持つ。
# 2026-07-24 に適用済みだった旧エントリ（1017-1036 等）は、実行後に section 名
# 自体が分割後の名前に置き換わるため、このスクリプトを再実行すると
# 「section が存在しない」エラーになる。ワンショット実行が終わった分割は
# ここから削除する運用とし、常に「まだ未分割の section」だけを持つ。
SPLITS: dict[str, dict[str, list[tuple[int, int]]]] = {
    PRE_EPOCH: {
        # 工事後の 3176-3187 に対応する工事前の名前（3F は工事で +2 シフト）。
        # X=17 の右壁面で Y=8 が通路。Y2-7 と Y9-14 の2列。
        # 1135-1151 / 2100-2110 は適用済み（2026-07-28）。
        "3174-3185": [(3174, 3179), (3180, 3185)],
    },
    POST_EPOCH: {
        # 適用済み（2026-07-28）。再実行時はここを空にする。
    },
}


def split_epoch(
    con: sqlite3.Connection, valid_from: str, splits: dict[str, list[tuple[int, int]]], dry_run: bool
) -> None:
    rows = con.execute(
        "SELECT machine_number, section FROM machine_layout_history WHERE hall_name = ? AND valid_from = ?",
        (HALL_NAME, valid_from),
    ).fetchall()
    if not rows:
        raise SystemExit(f"エポック {valid_from} の行が無い")
    current = {mn: sec for mn, sec in rows}

    missing = set(splits) - set(current.values())
    if missing:
        raise SystemExit(f"エポック {valid_from} に存在しない section を指定している: {sorted(missing)}")

    # 台番号 -> 新しい列（下限, 上限）。分割対象外の台は据え置き。
    assign: dict[int, tuple[int, int]] = {}
    unassigned: list[int] = []
    for mn, sec in current.items():
        if sec not in splits:
            continue
        for lo, hi in splits[sec]:
            if lo <= mn <= hi:
                assign[mn] = (lo, hi)
                break
        else:
            unassigned.append(mn)

    # どの列にも属さない台は、実績データが1日も無い幽霊エントリか確認する。
    # 幽霊なら削除する（旧 section 名のまま残ると、分割後に「その section に
    # 2台しかいない」ように見えて誤解を招く）。実績があるなら配置の指定漏れ
    # なので止める。
    ghosts: list[int] = []
    if unassigned:
        placeholders = ",".join("?" * len(unassigned))
        with_data = {
            r[0]
            for r in con.execute(
                f"SELECT DISTINCT machine_number FROM machine_detailed_results "
                f"WHERE machine_number IN ({placeholders})",
                unassigned,
            )
        }
        ghosts = sorted(set(unassigned) - with_data)
        real = sorted(with_data)
        if real:
            raise SystemExit(
                f"エポック {valid_from}: 実績データがあるのにどの列にも属さない台がある: "
                f"{real}。配置の指定漏れなので SPLITS を直すこと"
            )
        print(f"  幽霊エントリ（実績データ0日）を削除: {ghosts}")

    # 新 section 内で台番号順に順位を振り直す。
    by_col: dict[tuple[int, int], list[int]] = {}
    for mn, col in assign.items():
        by_col.setdefault(col, []).append(mn)

    updates = []
    names: dict[tuple[int, int], str] = {}
    for col, members in by_col.items():
        members.sort()
        # section 名は「実在する台の最小-最大」で付ける。指定レンジが
        # 実在台より広い場合（2083-2099 等）に空番を含めないため。
        name = f"{members[0]}-{members[-1]}"
        names[col] = name
        n = len(members)
        for i, mn in enumerate(members):
            updates.append((name, members[0], members[-1], i + 1, n - i, mn, HALL_NAME, valid_from))

    print(f"  対象 {len(splits)} section / {len(assign)} 台 → {len(by_col)} 列に分割")
    for old in sorted(splits):
        news = sorted(names[col] for col, members in by_col.items() if current[members[0]] == old)
        print(f"    {old} -> {' / '.join(news)}")

    if dry_run:
        print("  （dry-run のため書き込みなし）")
        return

    con.executemany(
        "UPDATE machine_layout_history "
        "SET section = ?, section_min = ?, section_max = ?, "
        "    rank_from_min = ?, rank_from_max = ? "
        "WHERE machine_number = ? AND hall_name = ? AND valid_from = ?",
        updates,
    )
    print(f"  {len(updates)} 行を更新")

    if ghosts:
        con.executemany(
            "DELETE FROM machine_layout_history WHERE machine_number = ? AND hall_name = ? AND valid_from = ?",
            [(mn, HALL_NAME, valid_from) for mn in ghosts],
        )
        print(f"  幽霊エントリ {len(ghosts)} 行を削除")


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="楽園の統合 section を列単位に分割")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if not DB_PATH.exists():
        raise SystemExit(f"DB が無い: {DB_PATH}")

    with sqlite3.connect(str(DB_PATH)) as con:
        for epoch, splits in SPLITS.items():
            print(f"\n=== エポック {epoch} ===")
            split_epoch(con, epoch, splits, args.dry_run)
        if not args.dry_run:
            con.commit()

    if not args.dry_run:
        with sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True) as con:
            print("\n=== 結果 ===")
            for epoch in SPLITS:
                n_sec, n_machine = con.execute(
                    "SELECT COUNT(DISTINCT section), COUNT(*) "
                    "FROM machine_layout_history "
                    "WHERE hall_name = ? AND valid_from = ?",
                    (HALL_NAME, epoch),
                ).fetchone()
                # 各 section で rank_from_min の最大値が台数と一致するはず
                bad = con.execute(
                    "SELECT COUNT(*) FROM ("
                    "  SELECT section FROM machine_layout_history "
                    "  WHERE hall_name = ? AND valid_from = ? "
                    "  GROUP BY section HAVING COUNT(*) != MAX(rank_from_min)"
                    ")",
                    (HALL_NAME, epoch),
                ).fetchone()[0]
                print(f"  {epoch}: {n_sec} section / {n_machine} 台 / 順位不整合 {bad} section")


if __name__ == "__main__":
    main()
