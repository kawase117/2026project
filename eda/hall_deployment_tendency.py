# -*- coding: utf-8 -*-
"""ホール別の「いつ入れるか」を、予告と無関係に実績だけから多角的に出す。

単一指標で結論を出さない
------------------------
指標ごとに見えるものが違い、**指標間の乖離そのものが情報**である。

| 指標 | 何を映すか | 弱点 |
|---|---|---|
| 出率(加重) | 総獲得/総投入。ホールの収支に一致する | **回転数で加重される**。低設定台が多く回された日は下がる |
| 機械割(非加重) | 台を等重みで平均。回し方に依らない | 低回転台の分散が大きい |
| 中央差枚 | 分布の中心。1台の万枚に動かされない | 感度が鈍い |
| 勝率 | 差枚>0の台の割合 | 大勝ちと小勝ちを区別しない |
| 104%率 | 高設定の存在に直接効く | ⚠️ `Var(機械割) ∝ 1/games`。低回転日ほど偶然の超えが増える |
| G/台 | 需要側の文脈 | **投入量ではない** |

2026-09-10 の実測: 蒲田7の土曜は 勝率+3.0pp・104率+2.0pp・機械割+1.51pp と明確に高いのに、
**出率+0.01・中央差枚±0**。土日は平日勤めの層が増えて回し方が変わるため、高設定が
増えても加重した出率には出にくい。出率だけを見ると「土曜は平常」、機械割だけを見ると
「土曜は強い」となり、どちらも片面でしかない。

⚠️ **104%率を回転数帯で揃えるのは、やりすぎると選択を持ち込む。** 回転数は設定への
反応でもあるので、帯で切ると「よく回された高設定台」が高稼働日から落ちる。
参考値として併記するに留め、主判定に使わない。

⚠️ ホールを横断してプールしない。同じ軸を各ホールで別々に測って並べるだけにする
（[[feedback-no-cross-hall-pooling]]）。

⚠️ **有意差は通常つかない領域である。** p 値で足切りせず、向き・効果量・n を出す。
"""

import argparse
import os
import sqlite3

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DB_DIR = os.path.join(ROOT, "db")
WEEKDAYS = "月火水木金土日"
# これ未満の台は機械割の分散が大きすぎて、どの指標でもノイズになる
MIN_GAMES = 500
# 104%率の参考値を出すための回転数帯
REFERENCE_BAND = (3000, 6000)
METRICS = ("出率", "機械割", "中央差枚", "勝率", "104率", "104率(帯)", "G/台")


def hall_names():
    """db/ の中で実績テーブルを持つものだけを返す。

    ファイル名の除外リストを持つと、後から増えた作業用DBを足し忘れる。
    """
    names = []
    for filename in sorted(os.listdir(DB_DIR)):
        if not filename.endswith(".db"):
            continue
        try:
            with sqlite3.connect("file:%s?mode=ro" % os.path.join(DB_DIR, filename), uri=True) as connection:
                found = connection.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name='machine_detailed_results'"
                ).fetchone()
        except sqlite3.Error:
            continue
        if found:
            names.append(os.path.splitext(filename)[0])
    return names


def machine_frame(hall, since=None):
    """台×日。休業日と極端な低回転台は落とす。"""
    where = "WHERE games_normalized >= %d AND diff_coins_normalized IS NOT NULL" % MIN_GAMES
    if since:
        where += " AND date >= '%s'" % since
    with sqlite3.connect("file:%s?mode=ro" % os.path.join(DB_DIR, hall + ".db"), uri=True) as connection:
        frame = pd.read_sql(
            "SELECT date, machine_number, games_normalized AS games, "
            "       diff_coins_normalized AS diff FROM machine_detailed_results %s" % where,
            connection,
        )
    if frame.empty:
        return frame
    frame["payout"] = (frame["games"] * 3 + frame["diff"]) / (frame["games"] * 3)
    stamps = pd.to_datetime(frame["date"], format="%Y%m%d")
    frame["dd"] = stamps.dt.day
    frame["dd_tail"] = frame["dd"] % 10
    frame["weekday"] = stamps.dt.weekday.map(lambda i: WEEKDAYS[i])
    frame["zorome"] = (stamps.dt.month == stamps.dt.day).astype(int)
    frame["month_end"] = (stamps.dt.day >= stamps.dt.days_in_month - 1).astype(int)
    return frame


def _metrics(group, banded):
    return {
        "出率": 100 * (group["games"] * 3 + group["diff"]).sum() / (group["games"] * 3).sum(),
        "機械割": 100 * group["payout"].mean(),
        "中央差枚": group["diff"].median(),
        "勝率": 100 * (group["diff"] > 0).mean(),
        "104率": 100 * (group["payout"] >= 1.04).mean(),
        "104率(帯)": 100 * (banded["payout"] >= 1.04).mean() if len(banded) > 100 else float("nan"),
        "G/台": group["games"].mean(),
    }


def panel(frame, column):
    """軸ごとの指標と、ホール全体からの差を返す。"""
    band = frame[(frame["games"] >= REFERENCE_BAND[0]) & (frame["games"] <= REFERENCE_BAND[1])]
    base = _metrics(frame, band)
    rows = {}
    for key, group in frame.groupby(column):
        rows[key] = _metrics(group, band[band[column] == key])
        rows[key]["n"] = len(group)
    table = pd.DataFrame(rows).T
    for metric in METRICS:
        table[metric] = table[metric] - base[metric]
    return base, table


def report(hall, since, top):
    frame = machine_frame(hall, since)
    if frame.empty or frame["date"].nunique() < 30:
        return
    band = frame[(frame["games"] >= REFERENCE_BAND[0]) & (frame["games"] <= REFERENCE_BAND[1])]
    base = _metrics(frame, band)
    print("\n" + "=" * 92)
    print(
        "■ %s   %s〜%s  %d日 / %d台日"
        % (hall, frame["date"].min(), frame["date"].max(), frame["date"].nunique(), len(frame))
    )
    print(
        "   ホール: 出率%.2f%% 機械割%.2f%% 中央差枚%+.0f 勝率%.1f%% 104率%.1f%% G/台%.0f"
        % (base["出率"], base["機械割"], base["中央差枚"], base["勝率"], base["104率"], base["G/台"])
    )
    print("=" * 92)

    header = "%-8s%8s%8s%9s%7s%7s%10s%8s%7s" % (
        "",
        "出率",
        "機械割",
        "中央差枚",
        "勝率",
        "104率",
        "104率(帯)",
        "G/台",
        "n日",
    )
    for column, label, limit in (("weekday", "曜日", None), ("dd_tail", "日の末尾", None), ("dd", "日(DD)", top)):
        _, table = panel(frame, column)
        if column == "weekday":
            table = table.reindex(list(WEEKDAYS))
        else:
            table = table.sort_values("機械割", ascending=False)
            if limit:
                table = pd.concat([table.head(limit), table.tail(limit)])
        print("\n  【%s】ホール平均からの差" % label)
        print("  " + header)
        for key, row in table.iterrows():
            band_text = ("%+10.1f" % row["104率(帯)"]) if row["104率(帯)"] == row["104率(帯)"] else "%10s" % "-"
            print(
                "  %-8s%+8.2f%+8.2f%+9.0f%+7.1f%+7.1f%s%+8.0f%7d"
                % (
                    key,
                    row["出率"],
                    row["機械割"],
                    row["中央差枚"],
                    row["勝率"],
                    row["104率"],
                    band_text,
                    row["G/台"],
                    row["n"],
                )
            )

    for column, label in (("zorome", "月日ゾロ目"), ("month_end", "月末2日")):
        _, table = panel(frame, column)
        if 1 not in table.index:
            continue
        row = table.loc[1]
        print(
            "  【%s】出率%+.2f 機械割%+.2f 中央差枚%+.0f 勝率%+.1f 104率%+.1f G/台%+.0f (n=%d台日)"
            % (label, row["出率"], row["機械割"], row["中央差枚"], row["勝率"], row["104率"], row["G/台"], row["n"])
        )


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--since", default="20260401")
    parser.add_argument("--top", type=int, default=4)
    parser.add_argument("--hall", action="append")
    args = parser.parse_args()
    print("投入傾向スキャン（予告非依存・実績のみ） since=%s  min_games=%d" % (args.since, MIN_GAMES))
    print("⚠️ 単一指標で読まない。出率と機械割の乖離は『入っているが回され方で薄まった』の指標。")
    print("⚠️ ホール横断でプールしない。有意差は通常つかないので向きと効果量で読む。")
    for hall in args.hall or hall_names():
        report(hall, args.since, args.top)


if __name__ == "__main__":
    main()
