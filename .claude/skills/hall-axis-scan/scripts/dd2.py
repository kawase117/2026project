import numpy as np, pandas as pd, os, sys, datetime as dt
from backtest import monthly_report as mr
from backtest.bonus_specs import load_specs, find_spec

START, END, TAG = sys.argv[1], sys.argv[2], sys.argv[3]
rng = np.random.default_rng(9)
B = 3000
specs = load_specs()
raw = mr.load_machine_days(mr.hall_db_path(), START, END)
cat = {n: (find_spec(n, specs) or {}).get("category") for n in raw.machine_name.unique()}
raw = raw[raw.machine_name.map(cat).isin(["ノーマル", "BT"])].copy()
bad = raw.groupby("machine_name").agg(rb=("rb_count", "sum"), bb=("bb_count", "sum"))
bad = set(bad.index[(bad.rb == 0) & (bad.bb > 0)])
raw = raw[~raw.machine_name.isin(bad)]
raw["wd"] = raw.ds.map(lambda s: dt.date(int(s[:4]), int(s[4:6]), int(s[6:])).weekday())
raw["band"] = np.digitize(raw.games_normalized, [2000, 4000, 6000])
nd = raw.groupby(["machine_name", "ds"]).machine_number.transform("nunique")
mx = nd.groupby(raw.machine_name).max()
thr = raw.machine_name.map(lambda n: min(3, mx[n]))
raw = raw[nd >= thr]
print(TAG, "期間", raw.ds.min(), raw.ds.max(), "日数", raw.ds.nunique(), "機種", raw.machine_name.nunique())
raw["dd"] = raw.ds.str[6:].astype(int)
raw["mm"] = raw.ds.str[4:6].astype(int)
raw.to_pickle(os.environ["TEMP"] + f"/dd2_raw_{TAG}.pkl")
rate = (
    raw.groupby(["machine_name", "band"])
    .apply(lambda g: g.rb_count.sum() / g.games_normalized.sum(), include_groups=False)
    .rename("r")
)
raw = raw.join(rate, on=["machine_name", "band"])
raw["E"] = raw.games_normalized * raw.r
rows = []
for m, g in raw.groupby("machine_name"):
    d = (
        g.groupby("ds")
        .agg(O=("rb_count", "sum"), E=("E", "sum"), wd=("wd", "first"), dd=("dd", "first"), mm=("mm", "first"))
        .reset_index()
    )
    if len(d) < 30 or d.O.sum() < 100:
        continue
    d["dig"] = d.dd % 10
    d["zoro"] = d.dd.isin([11, 22])
    d["strong"] = d.dd == d.mm
    O = d.O.to_numpy(float)
    E = d.E.to_numpy(float)
    wd = d.wd.to_numpy()
    idx = [np.where(wd == w)[0] for w in range(7)]

    def shuf(l):
        x = l.copy()
        for ix in idx:
            x[ix] = l[rng.permutation(ix)]
        return x

    out = dict(machine=m, days=len(d))
    dig = d.dig.to_numpy()
    L = range(10)
    ob = np.array([O[dig == l].sum() / E[dig == l].sum() if (dig == l).any() else np.nan for l in L])
    w = int(np.nanargmax(ob))
    mxv = []
    for _ in range(B):
        x = shuf(dig)
        v = [O[x == l].sum() / E[x == l].sum() for l in L if (x == l).any()]
        mxv.append(max(v))
    out.update(
        best_digit=w, best_oe=ob[w], p_dig=(1 + np.sum(np.array(mxv) >= ob[w])) / (1 + B), n_best=int((dig == w).sum())
    )
    for col in ("zoro", "strong"):
        lab = d[col].to_numpy()
        if lab.sum() == 0:
            out[col + "_oe"] = np.nan
            out["p_" + col] = np.nan
            out["n_" + col] = 0
            continue
        o = O[lab].sum() / E[lab].sum()
        n = sum((lambda x: O[x].sum() / E[x].sum())(shuf(lab)) >= o for _ in range(B))
        out[col + "_oe"] = o
        out["p_" + col] = (1 + n) / (1 + B)
        out["n_" + col] = int(lab.sum())
    rows.append(out)
R = pd.DataFrame(rows)
for c in ("p_dig", "p_zoro", "p_strong"):
    s = R[c].dropna().sort_values()
    q = np.minimum(1, (s * len(s) / (np.arange(len(s)) + 1))[::-1].cummin()[::-1])
    R.loc[s.index, "q" + c[1:]] = q
print(
    f"\n[{TAG}] 機種 {len(R)}。p<0.05: 下一桁最大 {np.sum(R.p_dig < 0.05)} / ゾロ目 {np.sum(R.p_zoro < 0.05)} / 強ゾロ目 {np.sum(R.p_strong < 0.05)} (偶然なら各約{0.05 * len(R):.1f})。BH q<0.2: {np.sum(R.q_dig < 0.2)}/{np.sum(R.q_zoro < 0.2)}/{np.sum(R.q_strong < 0.2)}"
)
pd.set_option("display.width", 200)
print(
    R.sort_values("p_dig")
    .head(6)[["machine", "days", "best_digit", "n_best", "best_oe", "p_dig", "q_dig"]]
    .round(3)
    .to_string(index=False)
)
print(
    R.sort_values("p_zoro")
    .head(5)[["machine", "n_zoro", "zoro_oe", "p_zoro", "q_zoro"]]
    .round(3)
    .to_string(index=False)
)
print(
    R.sort_values("p_strong")
    .head(5)[["machine", "n_strong", "strong_oe", "p_strong", "q_strong"]]
    .round(3)
    .to_string(index=False)
)
R.to_pickle(os.environ["TEMP"] + f"/dd2_R_{TAG}.pkl")
