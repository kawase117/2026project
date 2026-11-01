"""日の軸(曜日・末尾日・イベント台帳の日)を、差枚だけでなく割とジャグラーの平均phで測る。

なぜ要るか:
    客の多い日は回転が増え、低設定でも差枚が沈むので、差枚だけだと「回る日」を「出ない日」と読み違える
    (2026-10-31 蒲田1の土曜、LESSONS L007)。割 = 1 + Σ差枚 ÷ (3ΣG) と、ジャグラーの設定5以上の
    事後確率(ph)の台平均を並べて見る。

    2026-10-31 のパターンスキャンで事前登録した日の仮説
    (backtest/hypothesis_prereg/pattern_scan_trials_20261031.json の hm/割/ph の採点手順)を、
    月末にこのモジュールで採点する。対象日の平均 − 同じ期間の対象外の日の平均を、日を単位にした
    ブートストラップの95%区間つきで出す。

使い方:
    venv/Scripts/python.exe -X utf8 -m backtest.day_wari --hall ARROW池上店 --start 20261101 --end 20261130 --dd 8
    venv/Scripts/python.exe -X utf8 -m backtest.day_wari --hall ヒロキ東口店 --start 20261101 --end 20261130 --event-days
    venv/Scripts/python.exe -X utf8 -m backtest.day_wari --prereg backtest/hypothesis_prereg/pattern_scan_trials_20261031.json --start 20261101 --end 20261130
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
AT_TYPES = ("AT", "ART", "A+AT", "A+ART")
METRICS = ("hm", "w_all", "w_at", "w_jug", "ph", "G")
WEEKDAYS = "月火水木金土日"
# 事前登録の日の仮説 id → 対象日の条件(仮説の文面と同じもの)
DAY_HYPOTHESES = {
    "k1-d8-weak": {"dd": 8},
    "arrow-d8-strong": {"dd": 8},
    "hiroki-e-d6-strong": {"dd": 6},
    "hiroki-e-d7-weak": {"dd": 7},
    "hiroki-e-eventdays": {"event_days": True},
    "heiwajima-d6-strong": {"dd": 6},
    "kinji-h-d3-strong": {"dd": 3},
    "k7-sun-jug-ph-low": {"weekday": 6},
}


def wari_by_day(df: pd.DataFrame) -> pd.DataFrame:
    """台×日の行(date, g, diff, grp)から、日ごとの hm・割(全台・AT・ジャグ)・平均G を出す。"""
    df = df[df["g"] > 0]

    def wari(x):
        s = x.groupby("date")[["diff", "g"]].sum()
        return 1 + s["diff"] / (3 * s["g"])

    return pd.DataFrame(
        {
            "hm": df.groupby("date")["diff"].mean(),
            "w_all": wari(df),
            "w_at": wari(df[df["grp"] == "AT"]),
            "w_jug": wari(df[df["grp"] == "JUG"]),
            "G": df.groupby("date")["g"].mean(),
        }
    )


def bootstrap_diff(a, b, iters: int = 2000, seed: int = 5) -> dict:
    """対象日の平均 − 対象外の日の平均と、日を単位にしたブートストラップの95%区間。どちらかが3日未満なら区間は出さない。"""
    a = np.asarray(a, float)
    a = a[~np.isnan(a)]
    b = np.asarray(b, float)
    b = b[~np.isnan(b)]
    out = {"n_in": len(a), "n_out": len(b), "diff": np.nan, "lo": np.nan, "hi": np.nan}
    if len(a) == 0 or len(b) == 0:
        return out
    out["diff"] = a.mean() - b.mean()
    if len(a) < 3 or len(b) < 3:
        return out
    rng = np.random.default_rng(seed)
    bs = rng.choice(a, (iters, len(a))).mean(1) - rng.choice(b, (iters, len(b))).mean(1)
    out["lo"], out["hi"] = np.percentile(bs, 2.5), np.percentile(bs, 97.5)
    return out


def _norm(s):
    return (s or "").replace("-", "").replace(" ", "").replace("　", "")


def event_dates(hall: str) -> set[str]:
    path = ROOT / "document" / "registry" / "EVENT_DAYS.jsonl"
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    return {r["date"] for r in rows if _norm(r.get("hall")) == _norm(hall) and r.get("date")}


def day_table(hall: str, start: str, end: str, ph_from: str | None = None) -> pd.DataFrame:
    """DB から日ごとの指標を作る。ph はジャグラーの設定5以上の事後確率の台平均(事前は ph_from 以降でEM推定)。"""
    con = sqlite3.connect(ROOT / "db" / f"{hall}.db")
    df = pd.read_sql(
        """select m.date, m.games_normalized g, m.diff_coins_normalized diff, mm.game_type gtype, mm.jug_flag jug
        from machine_detailed_results m left join machine_master mm on m.machine_name = mm.machine_name_normalized
        where m.date between ? and ?""",
        con,
        params=(start, end),
    )
    con.close()
    df = df.fillna({"g": 0, "diff": 0})
    df["grp"] = np.where(df["gtype"].isin(AT_TYPES), "AT", np.where(df["jug"] == 1, "JUG", "他"))
    day = wari_by_day(df)
    from backtest.juggler_carryover import build

    try:
        with contextlib.redirect_stdout(io.StringIO()):
            jug = build(hall, ph_from or start)
        day["ph"] = jug[jug["date"].between(start, end)].groupby("date")["ph"].mean()
    except ValueError, KeyError, sqlite3.Error:
        day["ph"] = np.nan
    day.index = day.index.astype(str)
    dates = pd.to_datetime(day.index)
    day["weekday"] = dates.dayofweek
    day["dd"] = dates.day % 10
    day["event_days"] = day.index.isin(event_dates(hall))
    return day


def target_mask(day: pd.DataFrame, cond: dict) -> pd.Series:
    if "dd" in cond:
        return day["dd"] == cond["dd"]
    if "weekday" in cond:
        return day["weekday"] == cond["weekday"]
    if cond.get("event_days"):
        return day["event_days"].astype(bool)
    raise ValueError(f"未対応の条件: {cond}")


def score_day_hypothesis(day: pd.DataFrame, cond: dict) -> pd.DataFrame:
    m = target_mask(day, cond)
    rows = [{"metric": k, **bootstrap_diff(day.loc[m, k], day.loc[~m, k])} for k in METRICS if k in day]
    return pd.DataFrame(rows).set_index("metric")


def _label(cond):
    if "dd" in cond:
        return f"{cond['dd']}のつく日"
    if "weekday" in cond:
        return f"{WEEKDAYS[cond['weekday']]}曜"
    return "EVENT_DAYS"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--start", required=True)
    ap.add_argument("--end", required=True)
    ap.add_argument("--ph-from", help="ph の事前を推定する開始日(既定: start の60日前)")
    ap.add_argument("--hall")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--dd", type=int)
    g.add_argument("--weekday", type=int, help="0=月 … 6=日")
    g.add_argument("--event-days", action="store_true")
    ap.add_argument("--prereg", help="日の仮説をまとめて採点する事前登録ファイル")
    a = ap.parse_args(argv)
    ph_from = a.ph_from or (pd.Timestamp(a.start) - pd.Timedelta(days=60)).strftime("%Y%m%d")
    pd.set_option("display.float_format", "{:.3f}".format)
    if a.prereg:
        reg = json.loads(Path(a.prereg).read_text(encoding="utf-8"))
        tables = {}
        for h in reg["hypotheses"]:
            cond = DAY_HYPOTHESES.get(h["id"])
            if cond is None:
                continue
            if h["hall"] not in tables:
                tables[h["hall"]] = day_table(h["hall"], a.start, a.end, ph_from)
            print(f"\n## {h['id']}({h['hall']} {_label(cond)})\n主張: {h.get('claim', h.get('hypothesis', ''))}")
            print(score_day_hypothesis(tables[h["hall"]], cond).to_string())
        return
    if not a.hall:
        ap.error("--hall か --prereg が要る")
    cond = {"dd": a.dd} if a.dd is not None else {"weekday": a.weekday} if a.weekday is not None else {}
    if a.event_days:
        cond = {"event_days": True}
    if not cond:
        ap.error("--dd / --weekday / --event-days のどれかが要る")
    print(f"{a.hall} {_label(cond)} {a.start}〜{a.end}")
    print(score_day_hypothesis(day_table(a.hall, a.start, a.end, ph_from), cond).to_string())


if __name__ == "__main__":
    main()
