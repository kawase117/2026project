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
RANGE_MARGIN = 0.05  # ホール単独の実測は、設定1〜6の範囲に、この余裕で入ること
DISPERSION_LIMIT = 5.0
MIN_DAYS_A = 300  # ホールごとの台日がこれ未満は、列の特定が不安定なのでAにしない
CONSISTENCY_LIMIT = (
    1.3  # ホール間の最大÷最小がこれを超える機種は、列の意味がホールで違う可能性(既知のジャグラーは1.05〜1.18)
)
MIN_HALLS_FOR_SPREAD = 4
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


def _column_counts(group):
    return {"bb": group.bb, "rb": group.rb, "bb+rb": group.bb + group.rb}


def across_halls_ratio(machine_days, column, min_days=MIN_DAYS_A, min_halls=MIN_HALLS_FOR_SPREAD):
    """ホール間の実測の最大÷最小。台日が足りるホールが min_halls 未満なら NaN。"""
    rates = []
    for _, group in machine_days.groupby("hall"):
        if len(group) < min_days:
            continue
        counts = _column_counts(group)[column]
        if counts.sum() > 0:
            rates.append(counts.sum() / group.g.sum())
    if len(rates) < min_halls:
        return float("nan")
    return max(rates) / min(rates)


def audit(days, specs):
    """機種×ホールごとの判定。ホール単独の実測で、列がマスターの範囲に入るかを見る。

    ホールによって、bb/rbに入る意味が違う機種がある(2026-10-03、マギアレコードは、楽園のbbが1/350で
    設定1の1/241より遅い)ので、全ホールをまとめた平均では判定しない。
    """
    rows = []
    days = days.assign(key=days.machine_name.map(bs.normalize))
    for key, machine_days in days[days.key.isin(specs)].groupby("key"):
        entry = specs[key]
        bounds = spec_bounds(entry)
        spreads = {column: across_halls_ratio(machine_days, column) for column in COLUMNS}
        for hall, group in machine_days.groupby("hall"):
            games = group.g
            stats = {}
            for column, counts in _column_counts(group).items():
                rate = counts.sum() / games.sum()
                in_range = column_in_range(rate, bounds) if rate > 0 else False
                stats[column] = (rate, in_range, dispersion_ratio(counts, games) if rate > 0 else float("nan"))
            # bbかrbが常に0のホール(楽園の多くのAT機)では、bb+rbは片方と同じ値で、別の列ではない
            candidates = [c for c in COLUMNS if c != "bb+rb" or (group.bb.sum() > 0 and group.rb.sum() > 0)]
            inside = [c for c in candidates if stats[c][1]]
            if len(inside) == 1 and stats[inside[0]][2] <= DISPERSION_LIMIT and len(group) >= MIN_DAYS_A:
                verdict, column = "A", inside[0]
            elif inside:
                verdict, column = "B", ",".join(inside)
            else:
                verdict, column = "X", ""
            across = spreads[inside[0]] if len(inside) == 1 else float("nan")
            rows.append(
                {
                    "machine": entry["name"],
                    "hall": hall,
                    "verdict": verdict,
                    "column": column,
                    "days": len(group),
                    "spec_low": round(1 / bounds[1], 1),
                    "spec_high": round(1 / bounds[0], 1),
                    "bb": round(1 / stats["bb"][0], 1) if stats["bb"][0] > 0 else "",
                    "rb": round(1 / stats["rb"][0], 1) if stats["rb"][0] > 0 else "",
                    "bb_rb": round(1 / stats["bb+rb"][0], 1) if stats["bb+rb"][0] > 0 else "",
                    "dispersion": round(stats[inside[0]][2], 2) if len(inside) == 1 else "",
                    "across_ratio": round(across, 2) if across == across else "",
                    "across_inconsistent": bool(across == across and across > CONSISTENCY_LIMIT),
                    "per_setting": bool(entry["per"]),
                }
            )
    return (
        pd.DataFrame(rows)
        .sort_values(["hall", "verdict", "days"], ascending=[True, True, False])
        .reset_index(drop=True)
    )


def main(argv=None):
    parser = argparse.ArgumentParser(description="AT機のAT初当り確率の列を監査して登録簿を書く")
    parser.add_argument("--out", default=str(AUDIT_CSV))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    result = audit(collect_days(), load_at_specs())
    print(result.groupby(["hall", "verdict"]).size().unstack(fill_value=0).to_string())
    if not args.dry_run:
        result.to_csv(args.out, index=False, encoding="utf-8")
        print("wrote", args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
