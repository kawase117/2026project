"""AT機のAT初当り確率が、DBのどの列(bb / rb / bb+rb)に入っているかの監査。

なぜ要るか:
    ATは一律「ボーナス確率で設定を判別できない」と扱われていたが、一撃マスターには
    AT機の設定別AT初当り確率(at_initial_setting1..6)や、notesの範囲(「AT初当り:1/a〜1/b」)がある。
    DBの bb/rb のどちらがAT初当りかは機種ごとに違うので、全ホールの台日を集め、
    実測が設定1〜設定6のスペック範囲に入る列を機種ごとに決める。

判定(verdict):
    A: 範囲内の列が1つだけで、台日あたりのカウントの塊が大きくない(分散比<=DISPERSION_LIMIT)。
       設定推定に使ってよい(暫定)。
    B: 範囲内の列が複数ある、または分散比が大きい。列の意味をユーザーに確認するまで使わない。
    X: 範囲内の列がない。使わない。

注意:
    範囲は全ホール・全設定の混合なので、設定1〜6の両端に±15%の幅を持たせる。
    これは「列の意味が合っているか」の確認であり、設定を判別できることの証明ではない。
    機械割との相関は、AT当選数が出玉に直結するため機械的に高く出る(at-gate-r-is-mechanical)ので使わない。
"""

from __future__ import annotations

import argparse
import glob
import os
import sqlite3
from pathlib import Path

import pandas as pd

from backtest import bonus_specs as bs

AUDIT_CSV = Path(bs.ROOT) / "document" / "registry" / "AT_RB_AUDIT.csv"
RANGE_MARGIN = 0.15
DISPERSION_LIMIT = 5.0
MIN_DAYS_A = 300  # 台日がこれ未満の機種は、列の特定が不安定なのでAにしない
MIN_GAMES = 1000
COLUMNS = ("bb", "rb", "bb+rb")


def load_at_specs(master_csv=bs.MASTER_CSV):
    """{正規化名: {name, per, rng}}。perは設定別のAT初当り確率、rngは(設定1側, 設定6側)の確率。"""
    return bs.load_at_hit_specs(master_csv)


def spec_bounds(entry):
    """スペックの(最小確率, 最大確率)。設定別があればその範囲、なければnotesの両端。"""
    values = list(entry["per"].values()) if entry["per"] else list(entry["rng"])
    return min(values), max(values)


def column_in_range(rate, bounds, margin=RANGE_MARGIN):
    low, high = bounds
    return low * (1 - margin) <= rate <= high * (1 + margin)


def dispersion_ratio(counts, games):
    """台日ごとのカウントが、プールした率のポアソンからどれだけ散らばるか(Pearsonのχ²/自由度)。"""
    rate = counts.sum() / games.sum()
    expected = (rate * games).clip(lower=1e-9)
    return float((((counts - expected) ** 2) / expected).sum() / max(len(counts) - 1, 1))


def collect_days(db_dir=bs.DB_DIR, min_games=MIN_GAMES):
    """全ホールDBの台日(G>=min_games)。bb/rbの意味はホール共通。"""
    frames = []
    for path in glob.glob(os.path.join(db_dir, "*.db")):
        if os.path.getsize(path) == 0:
            continue
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            frame = pd.read_sql_query(
                "SELECT machine_name, games_normalized AS g, bb_count AS bb, rb_count AS rb "
                "FROM machine_detailed_results WHERE games_normalized >= ?",
                con,
                params=(min_games,),
            )
            frame["hall"] = os.path.basename(path)[:-3]
            frames.append(frame)
        except sqlite3.DatabaseError, pd.errors.DatabaseError:
            pass
        finally:
            con.close()
    if not frames:
        return pd.DataFrame(columns=["machine_name", "g", "bb", "rb", "hall"])
    return pd.concat(frames, ignore_index=True)


def audit(days, specs):
    rows = []
    days = days.assign(key=days.machine_name.map(bs.normalize))
    for key, group in days[days.key.isin(specs)].groupby("key"):
        entry = specs[key]
        bounds = spec_bounds(entry)
        games = group.g
        series = {"bb": group.bb, "rb": group.rb, "bb+rb": group.bb + group.rb}
        stats = {}
        for column, counts in series.items():
            rate = counts.sum() / games.sum()
            in_range = column_in_range(rate, bounds) if rate > 0 else False
            stats[column] = (rate, in_range, dispersion_ratio(counts, games) if rate > 0 else float("nan"))
        inside = [c for c in COLUMNS if stats[c][1]]
        if len(inside) == 1 and stats[inside[0]][2] <= DISPERSION_LIMIT and len(group) >= MIN_DAYS_A:
            verdict, column = "A", inside[0]
        elif inside:
            verdict, column = "B", ",".join(inside)
        else:
            verdict, column = "X", ""
        rows.append(
            {
                "machine": entry["name"],
                "verdict": verdict,
                "column": column,
                "days": len(group),
                "halls": group.hall.nunique(),
                "spec_low": round(1 / bounds[1], 1),
                "spec_high": round(1 / bounds[0], 1),
                "bb": round(1 / stats["bb"][0], 1) if stats["bb"][0] > 0 else "",
                "rb": round(1 / stats["rb"][0], 1) if stats["rb"][0] > 0 else "",
                "bb_rb": round(1 / stats["bb+rb"][0], 1) if stats["bb+rb"][0] > 0 else "",
                "dispersion": round(stats[inside[0]][2], 2) if len(inside) == 1 else "",
                "per_setting": bool(entry["per"]),
            }
        )
    return pd.DataFrame(rows).sort_values(["verdict", "days"], ascending=[True, False]).reset_index(drop=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description="AT機のAT初当り確率の列を監査して登録簿を書く")
    parser.add_argument("--out", default=str(AUDIT_CSV))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    result = audit(collect_days(), load_at_specs())
    print(result.groupby("verdict").size().to_string())
    if not args.dry_run:
        result.to_csv(args.out, index=False, encoding="utf-8")
        print("wrote", args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
