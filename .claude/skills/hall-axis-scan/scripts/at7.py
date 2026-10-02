import numpy as np, pandas as pd, os, json, datetime as dt, sys, csv

T = os.environ["TEMP"]
B = int(sys.argv[1]) if len(sys.argv) > 1 else 3000
rng = np.random.default_rng(41)
raw = pd.read_pickle(f"{T}/at_raw_rel.pkl")  # AT等(ノーマル・BT以外)、新台7日以内を除外、6/2〜9/30
L = lambda f: [json.loads(l) for l in open(f"document/registry/{f}.jsonl", encoding="utf-8") if l.strip()]
alias = {
    r["alias"]: r["official_name"]
    for r in csv.DictReader(open("document/registry/MODEL_ALIASES.csv", encoding="utf-8"))
}
names = sorted(raw.machine_name.unique())
GENERIC = {"ジャグ", "ハナハナ", "全"}


def match(t):
    t = alias.get(t, t)
    if t in GENERIC or len(t) < 3:
        return []
    return [m for m in names if t in m or m in t]


pp = {r["date"]: r for r in L("PAST_PROMISES")}
named = {}
for d, r in pp.items():
    s = set()
    for tp in r["targeted_promises"]:
        for t in tp.get("targets", []):
            s |= set(match(t))
    named[d] = s
days = sorted(raw.ds.unique())
di = {d: i for i, d in enumerate(days)}
D = len(days)
wd = np.array([dt.date(int(d[:4]), int(d[4:6]), int(d[6:])).weekday() for d in days])
machs = sorted(raw.machine_name.unique())
mi = {m: i for i, m in enumerate(machs)}
K = len(machs)
raw["nm"] = [m in named.get(d, set()) for m, d in zip(raw.machine_name, raw.ds)]
r2 = raw[~raw.nm]  # その日に名指しされた機種の台日を、全体から除く
t = r2.groupby("ds").apply(lambda g: g.G.sum() / g.Gexp.sum(), include_groups=False)
r2 = r2.join(t.rename("tr"), on="ds")
r2["Gx"] = r2.Gexp * r2.tr


def mat(col):
    A = np.zeros((D, K))
    np.add.at(A, (r2.ds.map(di).to_numpy(), r2.machine_name.map(mi).to_numpy()), r2[col].to_numpy(float))
    return A


P = np.zeros((D, K))
np.add.at(P, (r2.ds.map(di).to_numpy(), r2.machine_name.map(mi).to_numpy()), 1.0)
NP = (P > 0).astype(float)
X = mat("xdiff")
G3 = 3 * mat("G")
GG = mat("G")
GE = mat("Gx")
ev = {r["event_id"]: r for r in L("EVENT_DAYS") if r.get("hall") == "楽園蒲田店"}
series = {}
for r in L("EVENT_SERIES"):
    if r.get("hall") != "楽園蒲田店" or r["label"] == "タイガーダッシュ取材":
        continue
    ds = {ev[e]["date"] for e in r["event_ids"] if e in ev}
    series[("公約: " if r["axis"] == "pledge" else "イベント: ") + r["label"]] = ds
series["種別: coverage"] = {r["date"] for r in ev.values() if r["kind"] == "coverage"}
series["種別: anniversary"] = {r["date"] for r in ev.values() if r["kind"] == "anniversary"}
idx = [np.where(wd == w)[0] for w in range(7)]


def shuf(l):
    x = l.copy()
    for ix in idx:
        x[ix] = l[rng.permutation(ix)]
    return x


rows = []
fam = []
cov = []
for name, ds in series.items():
    lab = np.array([(d in ds) and (d in pp) for d in days])
    n = int(lab.sum())
    cov.append((name, len(ds), n))
    if n < 3:
        continue
    ok = (lab.astype(float) @ NP) >= 3
    if ok.sum() == 0:
        continue

    def stats(l):
        l = l.astype(float)
        with np.errstate(invalid="ignore", divide="ignore"):
            return np.stack([(l @ X) / (l @ G3), (l @ GG) / (l @ GE) - 1])

    obs = stats(lab)
    sims = np.empty((B, 2, K))
    for b in range(B):
        sims[b] = stats(shuf(lab))
    sd = np.nanstd(sims, axis=0)
    sd[sd == 0] = np.nan
    z = obs / sd
    zs = sims / sd
    for o, oc in enumerate(("機械割", "回転数")):
        zm = np.nanmax(np.abs(np.where(ok, z[o], np.nan)))
        fm = np.nanmax(np.where(ok[None], np.abs(zs[:, o]), -1), axis=1)
        fam.append(dict(series=name, days=n, outcome=oc, p_family=(1 + np.sum(fm >= zm)) / (1 + B)))
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
                    machine=machs[m][:24],
                    n=int((lab.astype(float) @ NP)[m]),
                    obs=100 * obs[o, m],
                    z=z[o, m],
                    p=pc[m],
                )
            )
F = pd.DataFrame(fam)
C = pd.DataFrame(rows)
s = C.p.sort_values()
q = np.minimum(1, (s * len(s) / (np.arange(len(s)) + 1))[::-1].cummin()[::-1])
C.loc[s.index, "q"] = q
pd.set_option("display.width", 240)
pd.set_option("display.max_colwidth", 46)
print("系列ごとの、公約記録のある日数(名指し把握済み):")
print(pd.DataFrame(cov, columns=["系列", "台帳の日数", "名指し把握済みの日数"]).to_string(index=False))
print(
    f"\n名指し機種を除いた台日 {len(r2)} / 全体 {len(raw)}。族 {len(F)}本中 p_family<0.05: {np.sum(F.p_family < 0.05)}(偶然なら約{0.05 * len(F):.1f})。セル {len(C)}、p<0.05 {np.sum(C.p < 0.05)}(偶然なら約{0.05 * len(C):.0f})、BH q<0.2: {np.sum(C.q < 0.2)}"
)
for oc in ("機械割", "回転数"):
    c = C[C.outcome == oc]
    f = F[F.outcome == oc]
    print(
        f"\n=== {oc}(名指し機種を除く、客数も除く): 族 {len(f)}中 p_family<0.05 は {np.sum(f.p_family < 0.05)}、セル {len(c)}中 p<0.05 は {np.sum(c.p < 0.05)}(偶然なら約{0.05 * len(c):.0f})、BH q<0.2 は {np.sum(c.q < 0.2)} ==="
    )
    print(f.sort_values("p_family").head(4)[["series", "days", "p_family"]].round(3).to_string(index=False))
    print(
        c.sort_values("p")
        .head(10)[["series", "machine", "n", "obs", "z", "p", "q"]]
        .round(3)
        .rename(columns={"obs": "超過(%)"})
        .to_string(index=False)
    )
C.to_pickle(f"{T}/at7_C.pkl")
F.to_pickle(f"{T}/at7_F.pkl")
