import numpy as np, pandas as pd, os, json, datetime as dt, sys
from backtest import monthly_report as mr
from backtest.bonus_specs import load_specs, find_spec

T = os.environ["TEMP"]
B = int(sys.argv[1]) if len(sys.argv) > 1 else 3000
START = sys.argv[2] if len(sys.argv) > 2 else "20260602"
END = "20260930"
TAG = sys.argv[3] if len(sys.argv) > 3 else "full"
rng = np.random.default_rng(17)
db = mr.hall_db_path()
specs = load_specs()
raw = mr.load_machine_days(db, START, END)
raw["cat"] = raw.machine_name.map({n: (find_spec(n, specs) or {}).get("category") for n in raw.machine_name.unique()})
raw = raw[~raw.cat.isin(["ノーマル", "BT"])].copy()  # ノーマル・BT以外(AT、A+ATなど)。差枚と回転数で見る
first, _ = mr.load_first_seen(db)
fs = raw.machine_name.map(first)
raw["since"] = [
    (dt.date(int(d[:4]), int(d[4:6]), int(d[6:])) - dt.date(int(f[:4]), int(f[4:6]), int(f[6:]))).days
    for d, f in zip(raw.ds, fs)
]
raw = raw[raw.since >= 7].copy()  # 入替後7日以内の新台は設定不問で高回転する
raw["wd"] = raw.ds.map(lambda s: dt.date(int(s[:4]), int(s[4:6]), int(s[6:])).weekday())
raw["band"] = np.digitize(raw.games_normalized, [2000, 4000, 6000])
raw["G"] = raw.games_normalized
pay = (
    raw.groupby(["machine_name", "band"])
    .apply(lambda g: g.diff_coins_normalized.sum() / (3 * g.G.sum()), include_groups=False)
    .rename("pb")
)
raw = raw.join(pay, on=["machine_name", "band"])
raw["xdiff"] = raw.diff_coins_normalized - 3 * raw.G * raw.pb  # 回転数帯が同じ台の平均を基準にした差枚の超過
raw["Gexp"] = raw.groupby(["machine_name", "wd"]).G.transform("mean")
days = sorted(raw.ds.unique())
di = {d: i for i, d in enumerate(days)}
D = len(days)
wd = np.array([dt.date(int(d[:4]), int(d[4:6]), int(d[6:])).weekday() for d in days])
cnt = raw.groupby("machine_name").ds.nunique()
keep = cnt[cnt >= 30].index
raw = raw[raw.machine_name.isin(keep)]
machs = sorted(raw.machine_name.unique())
mi = {m: i for i, m in enumerate(machs)}
K = len(machs)
print(f"[{TAG}] 期間 {raw.ds.min()}〜{raw.ds.max()} 日数{D} 機種{K} 台日{len(raw)}")


def mat(col):
    A = np.zeros((D, K))
    np.add.at(A, (raw.ds.map(di).to_numpy(), raw.machine_name.map(mi).to_numpy()), raw[col].to_numpy(float))
    return A


P = np.zeros((D, K))
np.add.at(P, (raw.ds.map(di).to_numpy(), raw.machine_name.map(mi).to_numpy()), 1.0)
NP = (P > 0).astype(float)
X = mat("xdiff")
G3 = 3 * mat("G")
GG = mat("G")
GE = mat("Gexp")
GE = GE * (GG.sum(1) / GE.sum(1))[:, None]  # その日のAT等全体の客数の増減を除く
L = lambda f: [json.loads(l) for l in open(f"document/registry/{f}.jsonl", encoding="utf-8") if l.strip()]
ev = {r["event_id"]: r for r in L("EVENT_DAYS") if r.get("hall") == "楽園蒲田店"}
series = {}
for r in L("EVENT_SERIES"):
    if r.get("hall") != "楽園蒲田店":
        continue
    ds = {ev[e]["date"] for e in r["event_ids"] if e in ev}
    series[("公約: " if r["axis"] == "pledge" else "イベント: ") + r["label"]] = ds
for k in ("coverage", "anniversary"):
    series["種別: " + k] = {r["date"] for r in ev.values() if r["kind"] == k}
idx = [np.where(wd == w)[0] for w in range(7)]


def shuf(lab):
    x = lab.copy()
    for ix in idx:
        x[ix] = lab[rng.permutation(ix)]
    return x


rows = []
fam = []
for name, ds in series.items():
    lab = np.array([d in ds for d in days])
    n = int(lab.sum())
    if n < 3:
        continue
    npres = lab.astype(float) @ NP
    ok = npres >= 3
    if ok.sum() == 0:
        continue

    def stats(l):
        l = l.astype(float)
        with np.errstate(invalid="ignore", divide="ignore"):
            return np.stack([(l @ X) / (l @ G3), (l @ GG) / (l @ GE) - 1])  # 機械割の超過(分率)、回転数の超過(分率)

    obs = stats(lab)
    sims = np.empty((B, 2, K))
    for b in range(B):
        sims[b] = stats(shuf(lab))
    sd = np.nanstd(sims, axis=0)
    sd[sd == 0] = np.nan
    z = obs / sd
    zs = sims / sd
    for o, oc in enumerate(("機械割(差枚/3G)の超過", "回転数/期待")):
        zo = np.where(ok, z[o], np.nan)
        zm = np.nanmax(np.abs(zo))
        fm = np.nanmax(np.where(ok[None], np.abs(zs[:, o]), -1), axis=1)
        pf = (1 + np.sum(fm >= zm)) / (1 + B)
        fam.append(dict(series=name, days=n, outcome=oc, n_mach=int(ok.sum()), p_family=pf))
        pc = (
            1
            + np.sum(np.abs(np.where(np.isfinite(zs[:, o]), zs[:, o], 0)) >= np.abs(np.nan_to_num(z[o]))[None], axis=0)
        ) / (1 + B)
        for m in np.where(ok)[0]:
            rows.append(
                dict(
                    series=name,
                    days=n,
                    outcome=oc,
                    machine=machs[m],
                    n=int(npres[m]),
                    obs=obs[o, m],
                    z=z[o, m],
                    p=pc[m],
                )
            )
F = pd.DataFrame(fam)
C = pd.DataFrame(rows)
s = C.p.sort_values()
q = np.minimum(1, (s * len(s) / (np.arange(len(s)) + 1))[::-1].cummin()[::-1])
C.loc[s.index, "q"] = q
F.to_pickle(f"{T}/at_F_{TAG}.pkl")
C.to_pickle(f"{T}/at_C_{TAG}.pkl")
raw.to_pickle(f"{T}/at_raw_{TAG}.pkl")
pd.set_option("display.width", 240)
pd.set_option("display.max_colwidth", 44)
print(
    f"系列×指標の族 {len(F)}本中 p_family<0.05: {np.sum(F.p_family < 0.05)}(偶然なら約{0.05 * len(F):.1f})。セル {len(C)}、p<0.05 {np.sum(C.p < 0.05)}(偶然なら約{0.05 * len(C):.0f})、BH q<0.2: {np.sum(C.q < 0.2)}"
)
for oc in ("機械割(差枚/3G)の超過", "回転数/期待"):
    f = F[F.outcome == oc]
    c = C[C.outcome == oc]
    print(
        f"\n=== {oc}: 族 {len(f)}本中 p_family<0.05 は {np.sum(f.p_family < 0.05)}、セル {len(c)}中 p<0.05 は {np.sum(c.p < 0.05)}(偶然なら約{0.05 * len(c):.0f})、BH q<0.2 は {np.sum(c.q < 0.2)} ==="
    )
    print(f.sort_values("p_family").head(5)[["series", "days", "n_mach", "p_family"]].round(3).to_string(index=False))
    print(
        c.sort_values("p")
        .head(10)[["series", "machine", "n", "obs", "z", "p", "q"]]
        .assign(obs=lambda t: (100 * t.obs).round(1))
        .round(3)
        .to_string(index=False)
    )
hall = {
    n: (lambda lab: (lab.astype(float) @ X.sum(1)) / (lab.astype(float) @ G3.sum(1)))(np.array([d in ds for d in days]))
    for n, ds in series.items()
}
print("\nAT等全体の機械割の超過(ポイント): ", {k[:24]: round(100 * v, 2) for k, v in list(hall.items())[:6]}, "...")
