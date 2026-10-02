import numpy as np, pandas as pd, os, json, sqlite3, datetime as dt, sys
from backtest import monthly_report as mr
from backtest.bonus_specs import load_specs, find_spec

T = os.environ["TEMP"]
B = int(sys.argv[1]) if len(sys.argv) > 1 else 1500
rng = np.random.default_rng(31)
START, END = "20260707", "20260930"
db = mr.hall_db_path()
specs = load_specs()
raw = mr.load_machine_days(db, START, END)
cat = {n: (find_spec(n, specs) or {}).get("category") for n in raw.machine_name.unique()}
raw["cat"] = raw.machine_name.map(cat)
first, _ = mr.load_first_seen(db)
raw["days_since"] = raw.apply(
    lambda r: (
        (
            dt.date(int(r.ds[:4]), int(r.ds[4:6]), int(r.ds[6:]))
            - dt.date(int(first[r.machine_name][:4]), int(first[r.machine_name][4:6]), int(first[r.machine_name][6:]))
        ).days
    ),
    axis=1,
)
rbm = raw[raw.cat.isin(["ノーマル", "BT"])]
bad = rbm.groupby("machine_name").agg(rb=("rb_count", "sum"), bb=("bb_count", "sum"))
bad = set(bad.index[(bad.rb == 0) & (bad.bb > 0)])
raw = raw[~(raw.machine_name.isin(bad) & raw.cat.isin(["ノーマル", "BT"]))]
raw["seg"] = np.where(raw.cat.isin(["ノーマル", "BT"]), "RB", "OTHER")
raw = raw[~((raw.seg == "OTHER") & (raw.days_since < 7))]  # 新台は設定不問で高回転する
raw["wd"] = raw.ds.map(lambda s: dt.date(int(s[:4]), int(s[4:6]), int(s[6:])).weekday())
raw["band"] = np.digitize(raw.games_normalized, [2000, 4000, 6000])
# 配置(日付に対応する版)
con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
lay = pd.read_sql_query(
    "select machine_number,valid_from,valid_to,section,rank_from_min,rank_from_max from machine_layout_history", con
)
con.close()
lay["valid_to"] = lay.valid_to.fillna("99999999").astype(str)
lay["valid_from"] = lay.valid_from.astype(str)
raw["machine_number"] = raw.machine_number.astype(int)
m = raw.reset_index().merge(lay, on="machine_number", how="left")
m = m[(m.ds >= m.valid_from) & (m.ds <= m.valid_to)].set_index("index")
raw = raw.join(m[["section", "rank_from_min", "rank_from_max"]])
raw = raw[raw.section.notna()].copy()
raw["edge"] = np.minimum(raw.rank_from_min, raw.rank_from_max)
raw["ld"] = raw.machine_number % 10
# RB seg: 同時稼働台数の最大に合わせた条件(2台機種を落とさない)
rbs = raw[raw.seg == "RB"]
nd = rbs.groupby(["machine_name", "ds"]).machine_number.transform("nunique")
mx = nd.groupby(rbs.machine_name).max()
thr = rbs.machine_name.map(lambda n: min(3, mx[n]))
raw = raw.drop(index=rbs.index[nd < thr])
print(
    "台日",
    raw.groupby("seg").size().to_dict(),
    "機種",
    raw.groupby("seg").machine_name.nunique().to_dict(),
    "日数",
    raw.ds.nunique(),
)
# 期待値と残差
raw["G"] = raw.games_normalized
rate = (
    raw[raw.seg == "RB"]
    .groupby(["machine_name", "band"])
    .apply(lambda g: g.rb_count.sum() / g.G.sum(), include_groups=False)
    .rename("r")
)
raw = raw.join(rate, on=["machine_name", "band"])
raw["E"] = raw.G * raw.r
pay = (
    raw[raw.seg == "OTHER"]
    .groupby(["machine_name", "band"])
    .apply(lambda g: g.diff_coins_normalized.sum() / (3 * g.G.sum()), include_groups=False)
    .rename("pb")
)
raw = raw.join(pay, on=["machine_name", "band"])
raw["Ediff"] = 3 * raw.G * raw.pb
raw["Gexp"] = raw.groupby(["machine_name", "wd"]).G.transform("mean")
days = sorted(raw.ds.unique())
di = {d: i for i, d in enumerate(days)}
D = len(days)
wd = np.array([dt.date(int(d[:4]), int(d[4:6]), int(d[6:])).weekday() for d in days])
raw["di"] = raw.ds.map(di)


# ---- 結果指標(日×位置水準の NUM/DEN) ----
def pos_levels(df, axis):
    if axis == "末尾":
        return [(f"末尾{k}", (df.ld == k).to_numpy()) for k in range(10)]
    return [
        ("角1", (df.edge == 1).to_numpy()),
        ("角2", (df.edge == 2).to_numpy()),
        ("角3以上", (df.edge >= 3).to_numpy()),
    ]


def mats(df, num, den, axis):
    lv = pos_levels(df, axis)
    NUM = np.zeros((D, len(lv)))
    DEN = np.zeros((D, len(lv)))
    n = num.to_numpy(float)
    dd = den.to_numpy(float)
    di_ = df.di.to_numpy()
    for k, (_, mask) in enumerate(lv):
        NUM[:, k] = np.bincount(di_[mask], weights=n[mask], minlength=D)
        DEN[:, k] = np.bincount(di_[mask], weights=dd[mask], minlength=D)
    return [l for l, _ in lv], NUM, DEN


OUT = {}
rb = raw[raw.seg == "RB"]
ot = raw[raw.seg == "OTHER"]
OUT[("RB", "RB O/E")] = (rb, rb.rb_count, rb.E)
OUT[("RB", "回転数/期待")] = (rb, rb.G, rb.Gexp)
OUT[("OTHER", "機械割(差枚/3G)")] = (ot, ot.diff_coins_normalized - ot.Ediff, 3 * ot.G)
OUT[("OTHER", "回転数/期待")] = (ot, ot.G, ot.Gexp)


# ---- 並び強度(同機種・同セクション・連番の隣接ペアの残差積) ----
def narabi_day(df, kind):
    if kind == "RB":
        z = (df.rb_count - df.E) / np.sqrt(df.E.clip(lower=1e-6))
    else:
        pr = (df.diff_coins_normalized - df.Ediff) / (3 * df.G)
        z = pr * np.sqrt(df.G)
        z = z / z.std()
    d = df.assign(z=z.to_numpy())[["ds", "machine_number", "machine_name", "section", "z", "di"]]
    cnt = d.groupby(["ds", "machine_name"]).z.transform("size")
    d = d[cnt >= 3].copy()
    d["z"] = d.z - d.groupby(["ds", "machine_name"]).z.transform("mean")
    a = d.merge(d.assign(machine_number=d.machine_number - 1), on=["ds", "machine_number"], suffixes=("", "_n"))
    a = a[(a.machine_name == a.machine_name_n) & (a.section == a.section_n)]
    a = a.assign(p=a.z * a.z_n)
    NUM = np.bincount(a.di, weights=a.p, minlength=D)
    DEN = np.bincount(a.di, minlength=D).astype(float)
    return NUM[:, None], DEN[:, None]


NAR = {"RB": narabi_day(rb, "RB"), "OTHER": narabi_day(ot, "OTHER")}
# ---- 時間軸 ----
L = lambda f: [json.loads(l) for l in open(f"document/registry/{f}.jsonl", encoding="utf-8") if l.strip()]
ev = {r["event_id"]: r for r in L("EVENT_DAYS") if r.get("hall") == "楽園蒲田店"}
dd_ = np.array([int(d[6:]) for d in days])
mm_ = np.array([int(d[4:6]) for d in days])
AX = {}
AX["曜日"] = (
    [f"{'月火水木金土日'[w]}曜" for w in range(7)],
    np.stack([wd == w for w in range(7)], 1),
    mm_,
)  # 月の中で入れ替え
AX["D(下一桁)"] = ([f"{k}のつく日" for k in range(10)], np.stack([dd_ % 10 == k for k in range(10)], 1), wd)
lv = sorted(set(dd_))
AX["DD(日付)"] = ([f"{k}日" for k in lv], np.stack([dd_ == k for k in lv], 1), wd)
AX["ゾロ目"] = (["ゾロ目(11,22日)", "強ゾロ目(月=日)"], np.stack([np.isin(dd_, [11, 22]), dd_ == mm_], 1), wd)
names, mem = [], []
for r in L("EVENT_SERIES"):
    if r.get("hall") != "楽園蒲田店":
        continue
    ds = {ev[e]["date"] for e in r["event_ids"] if e in ev and ev[e]["date"] >= START}
    v = np.array([d in ds for d in days])
    if v.sum() >= 3:
        names.append(("公約: " if r["axis"] == "pledge" else "イベント: ") + r["label"] + f"({v.sum()}日)")
        mem.append(v)
for k in ("coverage", "anniversary"):
    ds = {r["date"] for r in ev.values() if r["kind"] == k and r["date"] >= START}
    v = np.array([d in ds for d in days])
    if v.sum() >= 3:
        names.append(f"種別: {k}({v.sum()}日)")
        mem.append(v)
AX["イベント・公約"] = (names, np.stack(mem, 1), wd)


# ---- 走査 ----
def scan(axis, pos, seg, outcome, NUM, DEN, Kl):
    names, M, strata = AX[axis]
    M = M.astype(float)
    Lv = M.shape[1]
    K = NUM.shape[1]
    NUMt, DENt = NUM.sum(0), DEN.sum(0)
    idx = [np.where(strata == s)[0] for s in np.unique(strata)]

    def stats(Mp):
        S = np.einsum("dl,dk->lk", Mp, NUM)
        Tt = np.einsum("dl,dk->lk", Mp, DEN)
        with np.errstate(invalid="ignore", divide="ignore"):
            if pos == "並び":
                return (S / Tt) - ((NUMt - S) / (DENt - Tt))
            Sall = S.sum(1, keepdims=True)
            Tall = Tt.sum(1, keepdims=True)
            Rk_in = S / Tt
            Rn_in = (Sall - S) / (Tall - Tt)
            Sx = NUMt - S
            Tx = DENt - Tt
            Sxa = Sx.sum(1, keepdims=True)
            Txa = Tx.sum(1, keepdims=True)
            Rk_out = Sx / Tx
            Rn_out = (Sxa - Sx) / (Txa - Tx)
            return (Rk_in - Rn_in) - (Rk_out - Rn_out)

    obs = stats(M)
    sims = np.empty((B,) + obs.shape)
    for b in range(B):
        perm = np.arange(D)
        for ix in idx:
            perm[ix] = rng.permutation(ix)
        sims[b] = stats(M[perm])
    sd = np.nanstd(sims, axis=0)
    sd[sd == 0] = np.nan
    z = obs / sd
    zs = sims / sd
    ok = np.isfinite(z)
    fam_max = np.nanmax(np.where(np.isfinite(zs), np.abs(zs), -1), axis=(1, 2))
    zmax = np.nanmax(np.where(ok, np.abs(z), -1))
    pfam = (1 + np.sum(fam_max >= zmax)) / (1 + B)
    pc = (1 + np.nansum(np.abs(zs) >= np.abs(z)[None], axis=0)) / (1 + B)
    rows = []
    for a in range(Lv):
        for k in range(K):
            if ok[a, k]:
                rows.append(
                    dict(
                        axis=axis,
                        pos=pos,
                        seg=seg,
                        outcome=outcome,
                        time=names[a],
                        level=Kl[k] if pos != "並び" else "隣接ペア",
                        obs=obs[a, k],
                        z=z[a, k],
                        p=pc[a, k],
                        days=int(M[:, a].sum()),
                    )
                )
    return pfam, rows


allrows = []
fam = []
for axis in AX:
    for (seg, outcome), (df, num, den) in OUT.items():
        for pos in ("末尾", "角番"):
            Kl, NUM, DEN = mats(df, num, den, pos)
            pf, rows = scan(axis, pos, seg, outcome, NUM, DEN, Kl)
            fam.append((axis, pos, seg, outcome, pf, len(rows)))
            allrows += rows
    for seg in ("RB", "OTHER"):
        NUM, DEN = NAR[seg]
        pf, rows = scan(axis, "並び", seg, "隣接ペア残差積", NUM, DEN, ["隣接ペア"])
        fam.append((axis, "並び", seg, "隣接ペア残差積", pf, len(rows)))
        allrows += rows
    print("done", axis, flush=True)
F = pd.DataFrame(fam, columns=["時間軸", "位置軸", "区分", "指標", "p_family", "セル数"])
C = pd.DataFrame(allrows)
s = C.p.sort_values()
q = np.minimum(1, (s * len(s) / (np.arange(len(s)) + 1))[::-1].cummin()[::-1])
C.loc[s.index, "q"] = q
F.to_pickle(f"{T}/pos_F.pkl")
C.to_pickle(f"{T}/pos_C.pkl")
raw.to_pickle(f"{T}/pos_raw.pkl")
pd.set_option("display.width", 250)
pd.set_option("display.max_colwidth", 50)
print("\n===== 族(時間軸×位置軸×区分×指標)の「最大の効果が偶然より大きいか」 p_family =====")
print(F.sort_values("p_family").round(3).to_string(index=False))
print(
    f"\n族 {len(F)}本中 p_family<0.05: {np.sum(F.p_family < 0.05)}本 (偶然なら約{0.05 * len(F):.1f}本)。セル総数 {len(C)}、p<0.05 {np.sum(C.p < 0.05)}(偶然なら約{0.05 * len(C):.0f})、BH q<0.2: {np.sum(C.q < 0.2)}"
)
print("\n===== 上位セル(p順) =====")
print(
    C.sort_values("p")
    .head(15)[["axis", "pos", "seg", "outcome", "time", "level", "days", "obs", "z", "p", "q"]]
    .round(3)
    .to_string(index=False)
)
