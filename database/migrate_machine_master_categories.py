# -*- coding: utf-8 -*-
"""各ホールの `machine_master` に、一撃マスター由来の機種分類を足す。

なぜ要るか
----------
現行の `machine_master` は `jug_flag` / `hana_flag` / `oki_flag` / `bt_flag` の4つしか
持たず、**`bt_flag` が4種類の混合になっていた**。楽園蒲田の44機種の内訳:

    A+AT 15（エウレカART、この素晴らしい…）  ← ARTが混入
    BT   15（ニューパルサーBT、ハーレムエース）← 本来のBT
    ノーマル 9（新ハナビ、クランキークレスト）  ← ノーマル機が混入
    AT    5（キングパルサー、ファイヤードリフト）← AT機が混入

逆に `bt_flag=0` 側にも A+AT が12機種（頭文字D、えとたま、コードギアス）ある。
この状態で「BT機の傾向」を語ると、実際には4種類を混ぜた何かを見ていることになる。

`document/machine_master_research/machine_master.csv`（一撃 1geki.jp、330機種）は
`game_type` と `bt_flag` を別に持つので、そこから分類を取り直す。

何を足し、何を触らないか
------------------------
**既存の4フラグは一切変更しない。** 約60ファイルがこれらを参照しており、
値を書き換えると過去の分析結果と突き合わせられなくなる。列を足すだけにする
（行は増えないので、`machine_layout` のときのような二重計上は起きない）。

    game_type        一撃の生値（AT / ノーマル / A+AT / A+ART / ART / A+RT）
    spec_category    ノーマル / BT / A+AT / AT / ART に丸めたもの
    bonus_judgeable  ボーナス確率で設定を判別できるか（ノーマル・BT・A+ATのみ1）
    spec_source      1geki / 実機解析値 / NULL

⚠️ **メイン/サブのような「役割」は入れない。** 2026-09-10 の実測では、BTが低いのは
10ホール中9で一貫する（機械割 -1.63pp）が、A+AT はホールによって符号が逆
（ヒロキ +0.43 / 蒲田1 -1.99）、「メインはAT」も楽園・ARROW・ヒロキでは成り立たない。
役割はホール固有なので、全ホール共通の列に焼き込むと誤りを固定してしまう。

使い方
------
    python database/migrate_machine_master_categories.py --dry-run
    python database/migrate_machine_master_categories.py --apply
"""

import argparse
import os
import sqlite3
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DB_DIR = os.path.join(ROOT, "db")
sys.path.insert(0, ROOT)

from backtest.bonus_specs import find_spec, load_specs  # noqa: E402

NEW_COLUMNS = (
    ("game_type", "TEXT"),
    ("spec_category", "TEXT"),
    ("bonus_judgeable", "INTEGER"),
    ("spec_source", "TEXT"),
)


def hall_names():
    names = []
    for filename in sorted(os.listdir(DB_DIR)):
        if not filename.endswith(".db"):
            continue
        try:
            with sqlite3.connect("file:%s?mode=ro" % os.path.join(DB_DIR, filename), uri=True) as connection:
                found = connection.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name='machine_master'"
                ).fetchone()
        except sqlite3.Error:
            continue
        if found:
            names.append(os.path.splitext(filename)[0])
    return names


def migrate(hall, specs, apply_changes):
    path = os.path.join(DB_DIR, hall + ".db")
    connection = sqlite3.connect(path)
    existing = {row[1] for row in connection.execute("PRAGMA table_info(machine_master)")}
    if apply_changes:
        for column, kind in NEW_COLUMNS:
            if column not in existing:
                connection.execute("ALTER TABLE machine_master ADD COLUMN %s %s" % (column, kind))

    rows = connection.execute("SELECT machine_name_normalized FROM machine_master").fetchall()
    matched = unmatched = 0
    counts = {}
    unmatched_names = []
    for (name,) in rows:
        spec = find_spec(name, specs)
        if spec is None:
            unmatched += 1
            unmatched_names.append(name)
            continue
        matched += 1
        counts[spec["category"]] = counts.get(spec["category"], 0) + 1
        if apply_changes:
            connection.execute(
                "UPDATE machine_master SET game_type = ?, spec_category = ?, "
                "  bonus_judgeable = ?, spec_source = ? WHERE machine_name_normalized = ?",
                (spec.get("game_type"), spec["category"], int(spec["judgeable"]), spec.get("source"), name),
            )
    if apply_changes:
        connection.commit()
    connection.close()

    summary = " ".join("%s=%d" % (k, v) for k, v in sorted(counts.items(), key=lambda t: -t[1]))
    print("  %-28s %3d機種  照合 %3d / 未照合 %2d   %s" % (hall, len(rows), matched, unmatched, summary))
    if unmatched_names:
        print("      未照合: %s" % ", ".join(str(n)[:20] for n in unmatched_names[:6]))
    return matched, unmatched


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--apply", action="store_true", help="実際に列を足して書き込む")
    parser.add_argument("--hall", action="append")
    args = parser.parse_args()

    specs = load_specs()
    print("一撃マスター %d 機種を読み込み" % len(specs))
    print("既存の jug/hana/oki/bt フラグは変更しない。列を足すだけ。")
    print("%s\n" % ("--apply（書き込む）" if args.apply else "--dry-run（既定・書き込まない）"))

    total_matched = total_unmatched = 0
    for hall in args.hall or hall_names():
        matched, unmatched = migrate(hall, specs, args.apply)
        total_matched += matched
        total_unmatched += unmatched
    print(
        "\n合計: 照合 %d / 未照合 %d (%.1f%%)"
        % (total_matched, total_unmatched, 100 * total_unmatched / max(1, total_matched + total_unmatched))
    )
    if not args.apply:
        print("書き込むには --apply を付けること。")


if __name__ == "__main__":
    main()
