"""蒲田1の 2026-08-03 増台・再配置を machine_layout_history の第2エポックとして入れる。

解決する問題:
    2026-08-03 に 2416-2430 の15台が増設され、いずれも**既存の島の端に継ぎ足された**。
    さらに 2001-2020(対角) と 2021-2031(横列) の間の隙間が 2416-2420 で埋まり、
    2つの島が1つに繋がった（旧マップでは両者の間に明確な空白がある。
    docs/フロアマップ/蒲田一.jpg と docs/フロアマップ/20260803~蒲田一フロアマップ.jpg）。

    その結果、12の島で**片側の角番が新台に置き換わった**。単一スナップショットの
    machine_layout をそのまま過去に当てると、楽園蒲田 2026-07-06 の改装で起きたのと
    同じ事故（工事後の位置が工事前のデータに遡って適用され、端番効果が「消えた」
    ように見える）が蒲田1でも起きる。詳細: backtest/results/regime/FINDINGS.md 追試10。

エポック:
    [20250101 .. 20260802]  工事前。現行 machine_layout の内容そのまま。
    [20260803 .. ∞]         工事後。下の ISLANDS_20260803 が定義する物理順。

なぜ台番号順ではなく物理順で順位を振るか:
    工事前は全30セクションで「台番号順 == 座標順」が成立していた（検証済み）ため、
    rank_from_min は台番号順で正しかった。工事後はこれが崩れる。たとえば 2422 は
    台番号では 2043-2059 のどれより大きいが、物理的には 2043 のさらに外側＝島の端で、
    角番はこの台に移る。台番号順で振ると新台が全部「中間」に落ち、
    角番シグナルの測定対象そのものが壊れる。

section 名と section_min/section_max について:
    section 名は物理順の台番号列を連番区間ごとに "+" で連結した表示名にする
    （例: "2032-2042+2421"、"2422+2043-2059"）。旧来の "min-max" 単純表記だと
    "2032-2042" のように見えて実は12台目(2421)が範囲外に存在するという、
    名前と中身が矛盾する状態になるため。section_min/section_max は引き続き
    min(members)/max(members) を持つが、これは境界の目安であって
    f"{section_min}-{section_max}" が section 名や実在台と一致する保証はない。
    したがって **セクション台数を section_max - section_min + 1 で出してはいけない**。
    件数ベースの eda.core.compute_section_size を使うこと。

prior_section 列（工事前後の位置効果を比較するためのリネージュ）:
    machine_layout_history に prior_section TEXT 列を追加する。工事後エポックの
    各行には、同じ台番号が**直前のエポックで所属していた section 名**を入れる
    （新設台 2416-2430 は工事前に存在しないので NULL）。変更の無かった19島は
    section 名が変わらないため prior_section == section になる（自明なリネージュ）。

    使い方の例（角番効果を工事前後で比較）:
        -- 工事後のある島の「工事前の対応セクション」を引く
        SELECT DISTINCT prior_section FROM machine_layout_history
        WHERE hall_name = ? AND valid_from = '20260803' AND section = '2032-2042+2421';
        -- 結果 "2032-2042" を使って工事前エポックの同じ島だけを抽出し、
        -- 工事後エポックの角番効果と付き合わせる。

使い方:
    venv\\Scripts\\python.exe -m database.migrate_kamata1_layout_20260803 --dry-run
    venv\\Scripts\\python.exe -m database.migrate_kamata1_layout_20260803
    venv\\Scripts\\python.exe -m database.migrate_machine_layout_history verify
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DB_PATH = PROJECT_ROOT / "db" / "マルハンメガシティ2000-蒲田1.db"
HALL_NAME = "マルハンメガシティ2000-蒲田1"

PRE_EPOCH_FROM = "20250101"
PRE_EPOCH_TO = "20260802"
POST_EPOCH_FROM = "20260803"


def _seq(lo: int, hi: int) -> list[int]:
    return list(range(lo, hi + 1))


def format_section_name(members: list[int]) -> str:
    """物理順の台番号列を連番区間ごとに "+" で連結した表示名にする。

    [2032..2042, 2421] -> "2032-2042+2421"。台番号順の "min-max" 表記だと
    2421 が範囲外にいることが名前から読み取れず、section_max=2421 との
    整合も取れない見た目になるため、実在する区間をそのまま名前にする。
    """
    runs: list[tuple[int, int]] = []
    start = prev = members[0]
    for mn in members[1:]:
        if mn == prev + 1:
            prev = mn
            continue
        runs.append((start, prev))
        start = prev = mn
    runs.append((start, prev))
    return "+".join(f"{a}" if a == b else f"{a}-{b}" for a, b in runs)


# 工事後に構成が変わった島だけを、島名 -> 物理順の台番号列 で持つ。
# ここに無い section は工事前のまま引き継ぐ。
#
# 物理順は「工事前に rank_from_min == 1 だった台を先頭とする島の歩き順」。
# 新台は実配置（フロアマップの罫線が繋がっている位置）に挿入する。
#
# 2001-2031 は工事前の "2001-2020"(対角) と "2021-2031"(横列) が
# 2416-2420 で繋がって1島になったもの。ここだけ島名を付け直している。
# 繋がっていないと判断する場合は、このエントリを
#   "2001-2020": _seq(2001, 2020) + [2416],
#   "2021-2031": [2417, 2418, 2419, 2420] + _seq(2021, 2031),
# の2件に差し替えれば旧来の2島構成に戻せる。
ISLANDS_20260803: dict[str, list[int]] = {
    "2001-2031": _seq(2001, 2020) + [2416, 2417, 2418, 2419, 2420] + _seq(2021, 2031),
    "2032-2042": _seq(2032, 2042) + [2421],
    "2043-2059": [2422] + _seq(2043, 2059),
    "2060-2076": _seq(2060, 2076) + [2423],
    "2077-2087": [2424] + _seq(2077, 2087),
    "2088-2098": _seq(2088, 2098) + [2425],
    "2099-2109": [2426] + _seq(2099, 2109),
    "2110-2120": _seq(2110, 2120) + [2427],
    "2121-2131": [2428] + _seq(2121, 2131),
    "2143-2146": [2429] + _seq(2143, 2146),
    "2147-2150": _seq(2147, 2150) + [2430],
}

# 新台の座標。既存台の座標は一切動かさず、隣接する既存台の1つ外側に置く。
# 蒲田1 の x,y は対角島を階段状に描いた図面上のグリッドで、物理距離ではない
# （database/CLAUDE.md 参照）。順位の根拠は ISLANDS_20260803 の並びであって
# 座標ではないので、ここは「衝突しない・単調である」ことだけを満たせばよい。
NEW_COORDS: dict[int, tuple[int, int]] = {
    2416: (30, 3),  # 2020(29,3) の右
    2417: (44, 3),  # 2021(48,3) の左に4台並ぶ
    2418: (45, 3),
    2419: (46, 3),
    2420: (47, 3),
    2421: (47, 8),  # 2042(48,8) の左
    2422: (41, 11),  # 2043(40,11) の右
    2423: (40, 14),  # 2076(39,14) の右
    2424: (47, 11),  # 2077(48,11) の左
    2425: (47, 16),  # 2098(48,16) の左
    2426: (45, 19),  # 2099(44,19) の右
    2427: (45, 22),  # 2120(44,22) の右
    2428: (47, 19),  # 2121(48,19) の左
    2429: (44, 31),  # 2143(43,31) の右
    2430: (44, 34),  # 2150(43,34) の右
}

POS_COLUMNS = [
    "x",
    "y",
    "display_y",
    "section",
    "section_min",
    "section_max",
    "rank_from_min",
    "rank_from_max",
    "rank_from_aisle",
]


def load_pre_epoch(con: sqlite3.Connection) -> dict[int, dict]:
    rows = con.execute(
        f"SELECT machine_number, {', '.join(POS_COLUMNS)} "
        "FROM machine_layout_history WHERE hall_name = ? AND valid_from = ?",
        (HALL_NAME, PRE_EPOCH_FROM),
    ).fetchall()
    if not rows:
        raise SystemExit(
            f"工事前エポック({PRE_EPOCH_FROM})の行が無い。先に migrate_machine_layout_history bootstrap を実行すること"
        )
    return {r[0]: dict(zip(POS_COLUMNS, r[1:])) for r in rows}


def build_post_epoch(pre: dict[int, dict]) -> dict[int, dict]:
    """工事前の行を土台に、変更のあった島だけ振り直した工事後エポックを作る。"""
    changed_members = {mn for members in ISLANDS_20260803.values() for mn in members}
    # 変更後の島に1台でも属する台の「工事前の section」は丸ごと作り直す対象。
    # これをやらないと、旧 section 名の行が工事後エポックに残って二重定義になる。
    touched_old_sections = {pre[mn]["section"] for mn in changed_members if mn in pre}

    post: dict[int, dict] = {}
    for mn, row in pre.items():
        if row["section"] in touched_old_sections:
            continue
        new_row = dict(row)
        new_row["prior_section"] = row["section"]  # 変更なし島は自明なリネージュ
        post[mn] = new_row

    for members in ISLANDS_20260803.values():
        name = format_section_name(members)
        n = len(members)
        smin, smax = min(members), max(members)
        for i, mn in enumerate(members):
            if mn in NEW_COORDS:
                x, y = NEW_COORDS[mn]
                aisle = None  # 蒲田1 は rank_from_aisle 全 NULL。捏造しない。
                prior = None  # 新設台。工事前に存在しないので前身セクションは無い。
            else:
                base = pre[mn]
                x, y, aisle = base["x"], base["y"], base["rank_from_aisle"]
                prior = base["section"]
            post[mn] = {
                "x": x,
                "y": y,
                "display_y": y,
                "section": name,
                "section_min": smin,
                "section_max": smax,
                "rank_from_min": i + 1,
                "rank_from_max": n - i,
                "rank_from_aisle": aisle,
                "prior_section": prior,
            }
    return post


def check(con: sqlite3.Connection, pre: dict[int, dict], post: dict[int, dict]) -> None:
    """書き込み前に落とせる不整合はここで全部落とす。"""
    problems: list[str] = []

    lost = sorted(set(pre) - set(post))
    if lost:
        problems.append(f"工事前にあった台が工事後エポックから消えている: {lost}")

    missing = sorted(set(NEW_COORDS) - set(post))
    if missing:
        problems.append(f"新台が工事後エポックに入っていない: {missing}")

    # 座標の衝突。島の並びを座標から読み直す下流処理が静かに壊れる。
    seen: dict[tuple[int, int], int] = {}
    for mn, row in sorted(post.items()):
        key = (row["x"], row["y"])
        if key in seen:
            problems.append(f"座標が衝突: 台{seen[key]} と 台{mn} がともに {key}")
        seen[key] = mn

    # section 内で rank_from_min が 1..n を過不足なく埋めているか。
    by_section: dict[str, list[int]] = {}
    for row in post.values():
        by_section.setdefault(row["section"], []).append(row["rank_from_min"])
    for sec, ranks in sorted(by_section.items()):
        if sorted(ranks) != list(range(1, len(ranks) + 1)):
            problems.append(f"section {sec} の rank_from_min が 1..{len(ranks)} になっていない")

    orphans = sorted(
        mn
        for (mn,) in con.execute(
            "SELECT DISTINCT machine_number FROM machine_detailed_results WHERE date >= ?",
            (POST_EPOCH_FROM,),
        )
        if mn not in post
    )
    if orphans:
        problems.append(f"{POST_EPOCH_FROM} 以降の実績があるのに位置が無い台: {orphans}")

    # prior_section が NULL でよいのは新設台(NEW_COORDS)だけ。
    # 工事前から存在する台で prior_section が抜けていたらリネージュが繋がっていない。
    broken_lineage = sorted(mn for mn, row in post.items() if row["prior_section"] is None and mn not in NEW_COORDS)
    if broken_lineage:
        problems.append(f"prior_section が無いのに新設台でもない: {broken_lineage}")

    if problems:
        for p in problems:
            print(f"  NG: {p}")
        raise SystemExit(f"{len(problems)} 件の不整合。書き込みを中止する")
    print("  整合チェック: OK")


def report(pre: dict[int, dict], post: dict[int, dict]) -> None:
    print(f"  台数 {len(pre)} -> {len(post)} ({len(post) - len(pre):+d})")
    print(f"  section 数 {len({r['section'] for r in pre.values()})} -> {len({r['section'] for r in post.values()})}")
    print("\n  section 名の変更 [旧 -> 新] と角番(rank==1)の異動 [先頭端 / 末尾端]:")
    for members in ISLANDS_20260803.values():
        name = format_section_name(members)
        olds = sorted({pre[mn]["section"] for mn in members if mn in pre})
        old_head = sorted(mn for mn, r in pre.items() if r["section"] in olds and r["rank_from_min"] == 1)
        old_tail = sorted(mn for mn, r in pre.items() if r["section"] in olds and r["rank_from_max"] == 1)
        old_label = "+".join(olds) if len(olds) > 1 else (olds[0] if olds else "(新規)")
        print(f"    {old_label} -> {name}")
        print(f"      n={len(members):2d}  角番 {old_head} / {old_tail}  ->  [{members[0]}] / [{members[-1]}]")


def ensure_prior_section_column(con: sqlite3.Connection) -> None:
    """machine_layout_history に prior_section 列が無ければ追加する。

    既存DBは列追加前に CREATE TABLE 済みなので IF NOT EXISTS では効かない。
    列があるかを実地に確認してから ALTER する。
    """
    cols = {r[1] for r in con.execute("PRAGMA table_info(machine_layout_history)")}
    if "prior_section" not in cols:
        con.execute("ALTER TABLE machine_layout_history ADD COLUMN prior_section TEXT")


def write(con: sqlite3.Connection, post: dict[int, dict]) -> None:
    ensure_prior_section_column(con)
    con.execute(
        "UPDATE machine_layout_history SET valid_to = ? WHERE hall_name = ? AND valid_from = ?",
        (PRE_EPOCH_TO, HALL_NAME, PRE_EPOCH_FROM),
    )
    con.execute(
        "DELETE FROM machine_layout_history WHERE hall_name = ? AND valid_from = ?",
        (HALL_NAME, POST_EPOCH_FROM),
    )
    history_cols = ", ".join(POS_COLUMNS + ["prior_section"])
    history_ph = ", ".join("?" * (len(POS_COLUMNS) + 1))
    con.executemany(
        f"INSERT INTO machine_layout_history "
        f"(machine_number, hall_name, valid_from, valid_to, {history_cols}) "
        f"VALUES (?, ?, ?, NULL, {history_ph})",
        [
            (mn, HALL_NAME, POST_EPOCH_FROM, *[row[c] for c in POS_COLUMNS], row["prior_section"])
            for mn, row in sorted(post.items())
        ],
    )

    # machine_layout は「現在の位置」のスナップショット。prior_section はエポック間の
    # リネージュ概念なのでここには持たない（列自体が無い）。現在は工事後なので差し替える。
    # 過去に遡る分析が history を見る前提は変わらない。
    cols = ", ".join(POS_COLUMNS)
    ph = ", ".join("?" * len(POS_COLUMNS))
    con.execute("DELETE FROM machine_layout")
    con.executemany(
        f"INSERT INTO machine_layout (machine_number, hall_name, {cols}) VALUES (?, ?, {ph})",
        [(mn, HALL_NAME, *[row[c] for c in POS_COLUMNS]) for mn, row in sorted(post.items())],
    )


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="蒲田1 2026-08-03 レイアウト変更のエポック追加")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if not DB_PATH.exists():
        raise SystemExit(f"DB が無い: {DB_PATH}")

    with sqlite3.connect(str(DB_PATH)) as con:
        pre = load_pre_epoch(con)
        post = build_post_epoch(pre)
        print(f"=== 蒲田1 [{PRE_EPOCH_FROM}..{PRE_EPOCH_TO}] / [{POST_EPOCH_FROM}..∞] ===")
        check(con, pre, post)
        report(pre, post)
        if args.dry_run:
            print("\n  （dry-run のため書き込みなし）")
            return
        write(con, post)
        con.commit()
        print("\n  書き込み完了")

    with sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True) as con:
        print("\n=== 結果 ===")
        for vf, vt, n_sec, n in con.execute(
            "SELECT valid_from, valid_to, COUNT(DISTINCT section), COUNT(*) "
            "FROM machine_layout_history WHERE hall_name = ? GROUP BY valid_from, valid_to",
            (HALL_NAME,),
        ):
            print(f"  [{vf}..{vt or '∞'}] {n_sec} section / {n} 台")
        total, matched = con.execute(
            """
            SELECT COUNT(*), SUM(CASE WHEN l.machine_number IS NULL THEN 0 ELSE 1 END)
            FROM machine_detailed_results r
            LEFT JOIN machine_layout_history l
                   ON r.machine_number = l.machine_number
                  AND r.date >= l.valid_from
                  AND (l.valid_to IS NULL OR r.date <= l.valid_to)
            """
        ).fetchone()
        print(f"  実績 {total} 行 / 位置一致 {matched} ({matched / total * 100:.2f}%)")


if __name__ == "__main__":
    main()
