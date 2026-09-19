# -*- coding: utf-8 -*-
import sqlite3
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, r"C:\Users\apto117\Documents\pachinko-analyzer\src\2026project")
sys.path.insert(
    0,
    r"C:\Users\apto117\AppData\Local\Temp\claude\C--Users-apto117-Documents-pachinko-analyzer-src-2026project\275d6cea-e473-4767-8ef1-c9aff42d4e6e\scratchpad",
)
from backtest import event_days as ev

ROOT = r"C:\Users\apto117\Documents\pachinko-analyzer\src\2026project"
HALLS = {"蒲田1": "マルハンメガシティ2000-蒲田1", "蒲田7": "マルハンメガシティ2000-蒲田7"}
rng = np.random.default_rng(0)


def load(hall):
    con = sqlite3.connect(r"%s\db\%s.db" % (ROOT, hall))
    d = pd.read_sql(
        "select date,machine_name,machine_number,games_normalized g,diff_coins_normalized x from machine_detailed_results "
        "where date>='20260601' and games_normalized>=1000",
        con,
    )
    return d


for key, hall in HALLS.items():
    d = load(hall)
    day = d.groupby("date").agg(mean=("x", "mean"), win=("x", lambda s: (s > 0).mean()), g=("g", "mean"))
    m = d.groupby(["date", "machine_name"]).agg(n=("x", "size"), x=("x", "mean")).reset_index()
    m = m[m.n >= 3]
    day["over"] = m[m.x >= 1800].groupby("date").size().reindex(day.index).fillna(0)
    dt = pd.to_datetime(day.index)
    dow = dt.dayofweek
    dd = dt.day
    ev_dates = {r["date"] for r in ev.active(ev.load()) if r["hall"] == hall}
    kamata = {r["date"] for r in ev.active(ev.load()) if r["hall"] == hall and "カマタに集" in r["event_name"]}
    # 1・7の付く日は除いた平常日だけを基準に、曜日ごとの平均からの差を残差とする
    base_mask = ~day.index.isin(ev_dates) & ~np.isin(dd % 10, [1, 7]) & ~np.isin(dd, [30, 11, 22])
    print("=" * 60)
    print(hall, "基準日数", int(base_mask.sum()))
    for metric in ("mean", "win", "over"):
        dow_mean = day[metric][base_mask].groupby(dow[base_mask]).mean()
        resid = day[metric] - pd.Series(dow[:], index=day.index).map(dow_mean)
        obs_days = [x for x in kamata if x in day.index]
        obs = resid.loc[obs_days].mean()
        pool = resid[base_mask].index.tolist()
        dow_of = dict(zip(day.index, dow))
        cands = {x: np.array([resid[p] for p in pool if dow_of[p] == dow_of[x]]) for x in obs_days}
        perm = np.array([np.mean([rng.choice(cands[x]) for x in obs_days]) for _ in range(5000)])
        p = (np.sum(perm >= obs) + 1) / (len(perm) + 1)
        print("カマタに集合(n=%d) %s: 曜日平均比 +%.2f, 並べ替え片側p=%.3f" % (len(obs_days), metric, obs, p))
    r919 = day.loc["20260919"]
    print(
        "9/19 全日中のパーセンタイル: mean %.0f%%, win %.0f%%, over %.0f%%"
        % (
            100 * (day["mean"] <= r919["mean"]).mean(),
            100 * (day["win"] <= r919["win"]).mean(),
            100 * (day["over"] <= r919["over"]).mean(),
        )
    )
    sat = day[dow == 5]
    print(
        "9/19 土曜内パーセンタイル(n=%d): mean %.0f%%, over %.0f%%"
        % (len(sat), 100 * (sat["mean"] <= r919["mean"]).mean(), 100 * (sat["over"] <= r919["over"]).mean())
    )
    top = m[m.date == "20260919"].sort_values("x", ascending=False).head(8)
    print("9/19 機種平均TOP:", [(r.machine_name[:10], int(r.n), int(r.x)) for r in top.itertuples()])
