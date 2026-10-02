import pandas as pd, numpy as np, os
from backtest.bonus_specs import load_specs, find_spec
from backtest.monthly_report import rb_posterior

T = os.environ["TEMP"]
raw = pd.read_pickle(f"{T}/pos_raw.pkl")
r = raw[raw.seg == "RB"].copy()
SP = load_specs()
rng = np.random.default_rng(4)
r["d7"] = r.ds.str[6:].astype(int) % 10 == 7
j = r[r.machine_name.str.contains("ジャグラー")].copy()
cache = {}


def p4(m, G, rb):
    spec = cache.setdefault(m, find_spec(m, SP))
    post = rb_posterior(spec, float(G), float(rb)) or {}
    return sum(v for k, v in post.items() if k >= 4), sum(k * v for k, v in post.items())


j["p4"], j["es"] = zip(*[p4(m, G, rb) for m, G, rb in zip(j.machine_name, j.G, j.rb_count)])


def boot(g):  # 日単位ブートストラップで P(設定4以上)の平均の区間
    d = g.groupby("ds").agg(s=("p4", "sum"), n=("p4", "size"))
    v = [(lambda i: d.s.iloc[i].sum() / d.n.iloc[i].sum())(rng.integers(0, len(d), len(d))) for _ in range(2000)]
    return np.percentile(v, [2.5, 97.5])


print("ジャグラー系を、回転数で絞らず全台日で比較(台日ごとのRB事後確率)")
print(
    f"{'群':26s}{'台日':>6s}{'平均G':>7s}{'RB確率(全体)':>12s}{'平均P(設定4以上)':>16s}{'95%区間':>16s}{'平均期待設定':>10s}{'台日の過半数が設定4以上':>20s}{'機械割':>8s}{'平均差枚':>8s}"
)
for lab, g in (
    ("7のつく日×末尾7", j[j.d7 & (j.ld == 7)]),
    ("7のつく日×他の末尾", j[j.d7 & (j.ld != 7)]),
    ("他の日×末尾7", j[~j.d7 & (j.ld == 7)]),
    ("他の日×他の末尾", j[~j.d7 & (j.ld != 7)]),
):
    lo, hi = boot(g)
    G = g.G.sum()
    print(
        f"{lab:26s}{len(g):6d}{g.G.mean():7.0f}{'1/%.0f' % (G / g.rb_count.sum()):>12s}{g.p4.mean():16.3f}{'[%.3f,%.3f]' % (lo, hi):>16s}{g.es.mean():10.2f}{(g.p4 > 0.5).mean():20.2f}{100 + 100 * g.diff_coins_normalized.sum() / (3 * G):8.1f}{g.diff_coins_normalized.mean():8.0f}"
    )
a = j[j.d7 & (j.ld == 7)]
b = j[j.d7 & (j.ld != 7)]
print(
    "\n台日の分布 (7のつく日):  P(設定4以上)>0.9 の台日の割合  末尾7:",
    round((a.p4 > 0.9).mean(), 2),
    "  他の末尾:",
    round((b.p4 > 0.9).mean(), 2),
)
print("参考: 台日の平均G  末尾7:", round(a.G.mean()), "他の末尾:", round(b.G.mean()))
