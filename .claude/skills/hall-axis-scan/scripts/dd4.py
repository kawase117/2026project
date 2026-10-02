import numpy as np, pandas as pd, os, json, collections

rng = np.random.default_rng(21)
B = 4000
T = os.environ["TEMP"]
raw = pd.read_pickle(f"{T}/dd2_raw_ev.pkl")
rate = (
    raw.groupby(["machine_name", "band"])
    .apply(lambda g: g.rb_count.sum() / g.games_normalized.sum(), include_groups=False)
    .rename("r")
)
raw = raw.join(rate, on=["machine_name", "band"])
raw["E"] = raw.games_normalized * raw.r
md = raw.groupby(["ds", "machine_name"]).agg(O=("rb_count", "sum"), E=("E", "sum")).reset_index()
days = sorted(md.ds.unique())
di = {d: i for i, d in enumerate(days)}
machs = sorted(md.machine_name.unique())
mi = {m: i for i, m in enumerate(machs)}
O = np.zeros((len(days), len(machs)))
E = np.zeros_like(O)
P = np.zeros_like(O)
for r in md.itertuples():
    O[di[r.ds], mi[r.machine_name]] = r.O
    E[di[r.ds], mi[r.machine_name]] = r.E
    P[di[r.ds], mi[r.machine_name]] = 1
import datetime as dt

wd = np.array([dt.date(int(d[:4]), int(d[4:6]), int(d[6:])).weekday() for d in days])
idx = [np.where(wd == w)[0] for w in range(7)]
L = lambda f: [json.loads(l) for l in open(f"document/registry/{f}.jsonl", encoding="utf-8") if l.strip()]
ev = {r["event_id"]: r for r in L("EVENT_DAYS") if r.get("hall") == "楽園蒲田店"}
series = {}
for r in L("EVENT_SERIES"):
    if r.get("hall") != "楽園蒲田店":
        continue
    ds = {ev[e]["date"] for e in r["event_ids"] if e in ev}
    series[("name" if r["axis"] == "name" else "公約") + ": " + r["label"]] = ds
for k in ("coverage", "anniversary"):
    series["種別: " + k] = {r["date"] for r in ev.values() if r["kind"] == k}
res = []


def shuf(lab):
    x = lab.copy()
    for ix in idx:
        x[ix] = lab[rng.permutation(ix)]
    return x


for name, ds in series.items():
    lab = np.zeros(len(days), bool)
    for d in ds:
        if d in di:
            lab[di[d]] = True
    if lab.sum() < 3:
        continue
    npres = (lab[:, None] * P).sum(0)
    ok = npres >= 3
    if ok.sum() == 0:
        continue
    obs = np.where(ok, (lab @ O) / np.maximum(lab @ E, 1e-9), np.nan)
    mxn = []
    mnn = []
    cnt_hi = np.zeros(len(machs))
    cnt_lo = np.zeros(len(machs))
    for _ in range(B):
        x = shuf(lab).astype(float)
        v = np.where(ok, (x @ O) / np.maximum(x @ E, 1e-9), np.nan)
        mxn.append(np.nanmax(v))
        mnn.append(np.nanmin(v))
        cnt_hi += np.nan_to_num(v, nan=-1) >= np.nan_to_num(obs, nan=9)
        cnt_lo += np.nan_to_num(v, nan=9) <= np.nan_to_num(obs, nan=-1)
    hall = (lab @ O.sum(1)) / (lab @ E.sum(1))
    best = int(np.nanargmax(obs))
    worst = int(np.nanargmin(obs))
    res.append(
        dict(
            series=name,
            days=int(lab.sum()),
            hallOE=hall,
            n_mach=int(ok.sum()),
            best=machs[best],
            best_oe=obs[best],
            best_n=int(npres[best]),
            p_best_family=(1 + np.sum(np.array(mxn) >= obs[best])) / (1 + B),
            worst=machs[worst],
            worst_oe=obs[worst],
            p_worst_family=(1 + np.sum(np.array(mnn) <= obs[worst])) / (1 + B),
        )
    )
    for m in np.where(ok)[0]:
        res[-1].setdefault("cells", []).append(
            (machs[m], obs[m], int(npres[m]), (1 + cnt_hi[m]) / (1 + B), (1 + cnt_lo[m]) / (1 + B))
        )
R = pd.DataFrame([{k: v for k, v in r.items() if k != "cells"} for r in res])
cells = pd.DataFrame(
    [dict(series=r["series"], machine=c[0], oe=c[1], n=c[2], p_hi=c[3], p_lo=c[4]) for r in res for c in r["cells"]]
)
for c in ("p_hi", "p_lo"):
    s = cells[c].sort_values()
    q = np.minimum(1, (s * len(s) / (np.arange(len(s)) + 1))[::-1].cummin()[::-1])
    cells.loc[s.index, "q_" + c[2:]] = q
pd.set_option("display.width", 220)
pd.set_option("display.max_colwidth", 34)
print("系列数", len(R), "セル数(系列×機種)", len(cells))
print(
    f"系列内で最大の機種が偶然より突出: p<0.05 は {np.sum(R.p_best_family < 0.05)}/{len(R)}系列(偶然なら約{0.05 * len(R):.1f}) / 最小(低い側) p<0.05 は {np.sum(R.p_worst_family < 0.05)}"
)
print(
    f"セル p_hi<0.05: {np.sum(cells.p_hi < 0.05)}(偶然なら約{0.05 * len(cells):.0f}) BH q_hi<0.2: {np.sum(cells.q_hi < 0.2)} / p_lo<0.05: {np.sum(cells.p_lo < 0.05)} BH q_lo<0.2: {np.sum(cells.q_lo < 0.2)}"
)
print("\n[ホール全体(ノーマル+BT)のO/E 系列別]")
print(R.sort_values("hallOE", ascending=False)[["series", "days", "hallOE"]].round(3).to_string(index=False))
print("\n[高い側の上位セル]")
print(
    cells.sort_values("p_hi").head(12)[["series", "machine", "n", "oe", "p_hi", "q_hi"]].round(3).to_string(index=False)
)
print("\n[低い側の上位セル]")
print(
    cells.sort_values("p_lo").head(6)[["series", "machine", "n", "oe", "p_lo", "q_lo"]].round(3).to_string(index=False)
)
R.to_pickle(f"{T}/ev_R.pkl")
cells.to_pickle(f"{T}/ev_cells.pkl")
