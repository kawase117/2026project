"""持続して強い台の週次一覧。

なぜこれが要るか（document/reviews/2026-11-01-tokyoghoul-wari-oct.md ほか）:
    蒲田1の東京喰種2174番は、2025-03から毎週の差枚集計で旗が立ち続けていた。
    「直近の上位を追う」一般則は蒲田7を除くと効果が0と区別できないが、旗が立った週数が
    多い台（=持続している台）に絞ると、一部のホール（蒲田7・ヒロキMAX蒲田・
    BIGディッパー戸越銀座・みとや大森町・楽園蒲田）で翌週の差枚が同ホール全台平均を上回った
    （walk-forward、旗8週以上、全13ホール超過+113枚/台日、蒲田7を除くと+38で0と区別できない）。

    この監視は予測器ではなく、持続している台の一覧を毎週出し、凍結して前向きに採点する。

ルール（事前固定。結果を見て変えない）:
    ・基準日 t（=DBの最新日の翌日）の直前28日の差枚/1000Gが、同機種の台の平均より+250以上なら、その週は「旗」。
      稼働20日以上・窓内で機種が不変の台のみ。窓内の台が10未満の機種・ホールは出さない。
    ・過去26週（t-182日〜t）に旗が立った週数が8以上の台を「持続台」として出す。

使い方:
    venv\\Scripts\\python.exe -m backtest.persistent_units weekly   # 一覧を出して凍結する
    venv\\Scripts\\python.exe -m backtest.persistent_units score    # 翌週が終わった凍結リストを採点する
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

WINDOW_DAYS = 28
MIN_DAYS = 20
MIN_UNITS_IN_WINDOW = 10
FLAG_THRESHOLD = 250.0  # 差枚/1000G。同機種の台の平均との差
LOOKBACK_WEEKS = 26
MIN_FLAG_WEEKS = 8
EVAL_DAYS = 7
MIN_DB_BYTES = 5_000_000  # 0バイトのダミーDBと小さな補助DBを除く

ROOT = Path(__file__).resolve().parent.parent
DB_DIR = ROOT / "db"
OUT_DIR = Path(__file__).resolve().parent / "persistent"
LIST_DIR = OUT_DIR / "lists"
SCORES_PATH = OUT_DIR / "SCORES.jsonl"
REPORT_PATH = OUT_DIR / "PERSISTENT_UNITS.md"

_FLAG_COLS = ["n", "nm", "s", "r", "k"]


def hall_db_paths(db_dir: Path = DB_DIR) -> list[Path]:
    return sorted(p for p in db_dir.glob("*.db") if p.stat().st_size >= MIN_DB_BYTES)


def load_hall(path: Path) -> pd.DataFrame | None:
    """台日表（date, n, nm, g, df）。machine_detailed_results が無いDBは None。"""
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        d = pd.read_sql(
            "select date, machine_number as n, machine_name as nm, "
            "games_normalized as g, diff_coins_normalized as df "
            "from machine_detailed_results",
            conn,
        )
    except Exception:
        return None
    finally:
        conn.close()
    d = d[d["g"] > 0].copy()
    if d.empty:
        return None
    d["date"] = pd.to_datetime(d["date"], format="%Y%m%d")
    return d


def _window_table(d: pd.DataFrame, t: pd.Timestamp) -> pd.DataFrame:
    """基準日 t の直前窓の台別集計。窓内で機種が不変・稼働 MIN_DAYS 日以上の台に限る。
    列: nm, n, G, D, k, r(差枚/1000G), s(同機種の台の平均との差)。"""
    w = d[(d["date"] >= t - timedelta(days=WINDOW_DAYS)) & (d["date"] < t)]
    nunique = w.groupby("n")["nm"].nunique()
    w = w[w["n"].isin(nunique[nunique == 1].index)]
    a = w.groupby(["nm", "n"]).agg(G=("g", "sum"), D=("df", "sum"), k=("g", "size")).reset_index()
    a = a[a["k"] >= MIN_DAYS].copy()
    if a.empty:
        return a.assign(r=pd.Series(dtype=float), s=pd.Series(dtype=float))
    a["r"] = a["D"] / a["G"] * 1000
    machine_mean = a.groupby("nm").apply(lambda x: x["D"].sum() / x["G"].sum() * 1000, include_groups=False)
    a["s"] = a["r"] - a["nm"].map(machine_mean)
    return a


def flagged_units(d: pd.DataFrame, t: pd.Timestamp) -> pd.DataFrame:
    """基準日 t の直前窓で旗が立った台。列: n, nm, s(機種差), r(差枚/1000G), k(稼働日数)。"""
    a = _window_table(d, t)
    if len(a) < MIN_UNITS_IN_WINDOW:
        return pd.DataFrame(columns=_FLAG_COLS)
    return a[a["s"] >= FLAG_THRESHOLD][_FLAG_COLS].reset_index(drop=True)


def persistent_units(d: pd.DataFrame, t: pd.Timestamp) -> pd.DataFrame:
    """過去 LOOKBACK_WEEKS+1 週（t, t-7, ...）で旗の立った週数が MIN_FLAG_WEEKS 以上の台。
    列: n, nm, flag_weeks, latest_s, latest_r（latest_* は基準日 t の直前窓の値）。"""
    cols = ["n", "nm", "flag_weeks", "latest_s", "latest_r"]
    parts = []
    for k in range(LOOKBACK_WEEKS + 1):
        f = flagged_units(d, t - timedelta(days=7 * k))
        if len(f):
            parts.append(f.assign(week=k))
    if not parts:
        return pd.DataFrame(columns=cols)
    cnt = pd.concat(parts).groupby(["n", "nm"])["week"].nunique().rename("flag_weeks").reset_index()
    cnt = cnt[cnt["flag_weeks"] >= MIN_FLAG_WEEKS]
    # 現在も設置されている台（最新日に同じ機種で稼働がある）に限る
    cur = d[d["date"] == d["date"].max()][["n", "nm"]].drop_duplicates()
    cnt = cnt.merge(cur, on=["n", "nm"])
    latest = _window_table(d, t).rename(columns={"s": "latest_s", "r": "latest_r"})[["n", "nm", "latest_s", "latest_r"]]
    out = cnt.merge(latest, on=["n", "nm"], how="left")
    return out.sort_values("flag_weeks", ascending=False)[cols].reset_index(drop=True)


def weekly(force: bool = False) -> int:
    LIST_DIR.mkdir(parents=True, exist_ok=True)
    halls: dict[str, dict] = {}
    asof = None
    for p in hall_db_paths():
        d = load_hall(p)
        if d is None:
            continue
        t = d["date"].max() + timedelta(days=1)
        asof = t if asof is None else max(asof, t)
        units = persistent_units(d, t)
        halls[p.stem] = {
            "asof": t.strftime("%Y%m%d"),
            "units": [
                {
                    "n": int(r.n),
                    "nm": r.nm,
                    "flag_weeks": int(r.flag_weeks),
                    "latest_s": None if pd.isna(r.latest_s) else round(float(r.latest_s), 1),
                    "latest_r": None if pd.isna(r.latest_r) else round(float(r.latest_r), 1),
                }
                for r in units.itertuples()
            ],
        }
    if asof is None:
        print("対象のDBがありません", file=sys.stderr)
        return 1
    path = LIST_DIR / f"{asof.strftime('%Y%m%d')}.json"
    if path.exists() and not force:
        print(f"{path.name} は凍結済み。上書きは --force", file=sys.stderr)
        return 1
    payload = {
        "asof": asof.strftime("%Y%m%d"),
        "params": {
            "window_days": WINDOW_DAYS,
            "min_days": MIN_DAYS,
            "flag_threshold": FLAG_THRESHOLD,
            "lookback_weeks": LOOKBACK_WEEKS,
            "min_flag_weeks": MIN_FLAG_WEEKS,
        },
        "halls": halls,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    write_report(payload)
    total = sum(len(h["units"]) for h in halls.values())
    print(f"凍結: {path.name} ホール{len(halls)} 持続台{total}")
    return 0


def _fmt(v: float | None) -> str:
    return "—" if v is None else f"{v:+.0f}"


def write_report(payload: dict) -> None:
    lines = [
        "# 持続して強い台の週次一覧",
        "",
        f"基準日: {payload['asof']}（DBの最新日の翌日）。ルールは `backtest/persistent_units.py` の冒頭を参照。",
        "旗の週数は、過去26週のうち旗が立った週の数（窓が重なるので、独立な回数ではない）。",
        "",
    ]
    for hall, h in payload["halls"].items():
        lines.append(f"## {hall}")
        if not h["units"]:
            lines += ["持続台なし", ""]
            continue
        lines += ["| 台 | 機種 | 旗の週数 | 直近28日の機種差 | 直近28日の差枚/1000G |", "|---|---|---|---|---|"]
        for u in h["units"]:
            lines.append(
                f"| {u['n']} | {u['nm']} | {u['flag_weeks']} | {_fmt(u['latest_s'])} | {_fmt(u['latest_r'])} |"
            )
        lines.append("")
    REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")


def score() -> int:
    """翌週（asof〜asof+6日）が終わった凍結リストを採点し、SCORES.jsonl に書く。"""
    done: set[str] = set()
    if SCORES_PATH.exists():
        for line in SCORES_PATH.read_text(encoding="utf-8").splitlines():
            if line.strip():
                done.add(json.loads(line)["asof"])
    data = {p.stem: load_hall(p) for p in hall_db_paths()}
    n_new = 0
    for lp in sorted(LIST_DIR.glob("*.json")):
        payload = json.loads(lp.read_text(encoding="utf-8"))
        if payload["asof"] in done:
            continue
        asof = pd.Timestamp(datetime.strptime(payload["asof"], "%Y%m%d"))
        end = asof + timedelta(days=EVAL_DAYS - 1)
        total_d = total_k = total_win = total_base = 0.0
        covered = True
        per_hall: dict[str, list[float]] = {}
        for hall, h in payload["halls"].items():
            d = data.get(hall)
            if d is None or d["date"].max() < end:
                covered = False
                break
            f = d[(d["date"] >= asof) & (d["date"] <= end)]
            base = f["df"].mean()
            for u in h["units"]:
                fd = f[(f["n"] == u["n"]) & (f["nm"] == u["nm"])]
                if fd.empty:
                    continue
                total_d += fd["df"].sum()
                total_k += len(fd)
                total_win += (fd["df"] > 0).sum()
                total_base += base * len(fd)
                ph = per_hall.setdefault(hall, [0.0, 0.0, 0.0])
                ph[0] += fd["df"].sum()
                ph[1] += len(fd)
                ph[2] += base * len(fd)
        if not covered:
            continue
        k = total_k
        rec = {
            "asof": payload["asof"],
            "台日": int(k),
            "台日平均差枚": round(total_d / k, 1) if k else None,
            "同ホール全台平均": round(total_base / k, 1) if k else None,
            "超過": round((total_d - total_base) / k, 1) if k else None,
            "勝率": round(total_win / k, 3) if k else None,
            "ホール別超過": {h: round((v[0] - v[2]) / v[1], 1) for h, v in per_hall.items() if v[1]},
        }
        with SCORES_PATH.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
        n_new += 1
        print(f"採点: {rec['asof']} 台日{rec['台日']} 超過{rec['超過']}")
    if not n_new:
        print("採点できる凍結リストはありません（翌週が終わっていない、または採点済み）")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    w = sub.add_parser("weekly", help="持続台の一覧を出して凍結する")
    w.add_argument("--force", action="store_true", help="凍結済みの同じ基準日を上書きする")
    sub.add_parser("score", help="翌週が終わった凍結リストを採点する")
    args = ap.parse_args(argv)
    if args.cmd == "weekly":
        return weekly(force=args.force)
    return score()


if __name__ == "__main__":
    sys.exit(main())
