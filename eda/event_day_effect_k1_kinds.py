# -*- coding: utf-8 -*-
import sqlite3, sys
import numpy as np, pandas as pd

sys.path.insert(0, r"C:\Users\apto117\Documents\pachinko-analyzer\src\2026project")
from backtest import event_days as ev

ROOT = r"C:\Users\apto117\Documents\pachinko-analyzer\src\2026project"
rng = np.random.default_rng(1)
hall = "マルハンメガシティ2000-蒲田1"
con = sqlite3.connect(r"%s\db\%s.db" % (ROOT, hall))
d = pd.read_sql(
    "select date,machine_name,games_normalized g,diff_coins_normalized x from machine_detailed_results where date>='20260601' and games_normalized>=1000",
    con,
)
day = d.groupby("date").agg(mean=("x", "mean"), win=("x", lambda s: (s > 0).mean()))
dt = pd.to_datetime(day.index)
dow = dict(zip(day.index, dt.dayofweek))
dd = dict(zip(day.index, dt.day))
recs = [r for r in ev.active(ev.load()) if r["hall"] == hall]
alld = {r["date"] for r in recs}
kamata = {r["date"] for r in recs if "カマタに集" in r["event_name"]}
sets = {
    "収録(カマタ日除く)": {r["date"] for r in recs if r["kind"] == "recording" and r["date"] not in kamata},
    "取材": {r["date"] for r in recs if r["kind"] == "coverage"},
    "新台入替": {r["date"] for r in recs if r["kind"] == "renovation"},
}
base = [x for x in day.index if x not in alld and dd[x] % 10 not in (1, 7) and dd[x] not in (30, 11, 22)]
for metric in ("mean", "win"):
    dm = day[metric].loc[base].groupby([dow[x] for x in base]).mean()
    resid = day[metric] - pd.Series([dm[dow[x]] if dow[x] in dm.index else np.nan for x in day.index], index=day.index)
    for name, ds in sets.items():
        ds = [x for x in ds if x in day.index and not np.isnan(resid[x])]
        obs = resid[ds].mean()
        cands = {x: np.array([resid[b] for b in base if dow[b] == dow[x] and not np.isnan(resid[b])]) for x in ds}
        perm = np.array([np.mean([rng.choice(cands[x]) for x in ds]) for _ in range(4000)])
        p1 = (np.sum(perm >= obs) + 1) / (len(perm) + 1)
        p0 = (np.sum(perm <= obs) + 1) / (len(perm) + 1)
        print(
            "%-12s n=%d %-4s 曜日平均比 %+.2f  片側p(高い)=%.3f p(低い)=%.3f  日=%s"
            % (name, len(ds), metric, obs, p1, p0, ",".join(sorted(ds)))
        )
