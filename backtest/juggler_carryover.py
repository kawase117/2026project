"""ジャグラー設定の持ち越し分析(読み取り専用)。

前日(と過去数日)の結果から、翌日に高設定(設定5以上)である確率がどれだけ上がるかを台単位で測る。
翌日の高設定確率は、BB・RBの二項尤度とスペックから1日ごとに求めた設定5以上の事後確率(事前は機種別に独立EMで推定)。

使い方:
  python -m backtest.juggler_carryover groups   [--hall みとや大森町店] [--since 20260601]
  python -m backtest.juggler_carryover tomorrow [--hall みとや大森町店]   # 最新の収集スナップショットから翌日の候補

考え方・検証結果・限界は document/JUGGLER_SETTING_PATTERNS.md を読むこと。
"""

import argparse
import csv
import glob
import json
import re
import sqlite3
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from backtest import bonus_specs
from backtest.bonus_specs import find_spec, load_specs

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_HALL = "みとや大森町店"
MIN_GAMES = 1500  # 事後確率を出す最低G数
MIN_N = 30  # 群の最低台日数


# 旧設定(ml/experiments/jug_rb_setting_prediction/config.py)のBB・RB確率が公表値と食い違う機種は、
# machine_master.csv(公表値と一致)で上書きする。2026-10-13に外部の解析サイトと機械割で確認した。
# ウルトラミラクルは逆に旧設定が正しくマスターが誤りなので対象に含めない。
CORRECT_FROM_MASTER = {"ゴーゴージャグラー3", "ファンキージャグラー2", "ハッピージャグラーVIII"}


def _master_settings(model):
    out = {}
    with open(bonus_specs.MASTER_CSV, encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            if row.get("canonical_machine_name") != model and row.get("machine_name") != model:
                continue
            for s in range(1, 7):
                bb = re.match(r"1/([\d.]+)", row.get(f"bb_setting{s}") or "")
                rb = re.match(r"1/([\d.]+)", row.get(f"rb_setting{s}") or "")
                if bb and rb:
                    out[s] = {"bb_probability": 1 / float(bb.group(1)), "rb_probability": 1 / float(rb.group(1))}
            break
    return out


def _spec_for(model, specs):
    spec = find_spec(model, specs)
    if spec and model in CORRECT_FROM_MASTER:
        ms = _master_settings(model)
        if len(ms) >= 4:
            spec = {**spec, "settings": {s: {**spec["settings"].get(s, {}), **v} for s, v in ms.items()}}
    return spec


def _layout(hall):
    con = sqlite3.connect(ROOT / "db" / f"{hall}.db")
    return pd.read_sql("select machine_number u, section from machine_layout", con)


def _load_raw(hall, since):
    con = sqlite3.connect(ROOT / "db" / f"{hall}.db")
    df = pd.read_sql(
        "select date,machine_number u,machine_name m,games_normalized g,bb_count bb,rb_count rb,"
        "diff_coins_normalized diff from machine_detailed_results "
        "where date>=? and machine_name like '%ジャグラー%'",
        con,
        params=(since,),
    )
    df["d"] = pd.to_datetime(df["date"])
    return df[df.bb.notna() & df.rb.notna()].copy()


def _latest_snapshot(hall):
    files = sorted(glob.glob(str(ROOT / "scraper" / "realtime" / "output" / "snapshots" / f"{hall}_quick_*.jsonl")))
    if not files:
        raise SystemExit("収集スナップショットが無い")
    f = files[-1]
    rows = [json.loads(line) for line in open(f, encoding="utf-8")]
    out = pd.DataFrame(
        [
            {"u": r["unit"], "m": r["model"], "g": r["games"], "bb": r["bb"], "rb": r["rb"], "diff": r.get("diff")}
            for r in rows
            if r.get("model") and "ジャグラー" in r["model"] and r.get("games") and r.get("bb") is not None
        ]
    )
    stamp = Path(f).stem.split("_")[-2]
    out["date"] = stamp
    out["d"] = pd.to_datetime(stamp)
    out["diff"] = out["diff"].astype(float)
    return out, Path(f).name


def _posteriors(df, specs):
    """台×日の設定5以上の事後確率と、前日の型を判定する閾値。"""
    parts = []
    for m, sub in df.groupby("m"):
        spec = _spec_for(m, specs)
        if not spec:
            continue
        ss = sorted(s for s, v in spec["settings"].items() if v.get("bb_probability") and v.get("rb_probability"))
        if len(ss) < 4:
            continue
        use = sub[sub.g >= MIN_GAMES]
        if use.u.nunique() < 3:
            continue
        g = use.g.values[:, None].astype(float)
        bb = use.bb.values[:, None]
        rb = use.rb.values[:, None]
        pb = np.array([spec["settings"][s]["bb_probability"] for s in ss])[None, :]
        pr = np.array([spec["settings"][s]["rb_probability"] for s in ss])[None, :]
        ll = bb * np.log(pb) + (g - bb) * np.log1p(-pb) + rb * np.log(pr) + (g - rb) * np.log1p(-pr)
        e = np.exp(ll - ll.max(axis=1, keepdims=True))
        prior = np.ones(len(ss)) / len(ss)
        for _ in range(60):
            w = e * prior
            w /= w.sum(axis=1, keepdims=True)
            prior = w.mean(axis=0)
        post = e * prior
        post /= post.sum(axis=1, keepdims=True)
        hi = np.array([s >= 5 for s in ss])
        s5 = [s for s in ss if s >= 5][0]
        s2 = [s for s in ss if s <= 2][-1]
        out = use.copy()
        out["ph"] = post[:, hi].sum(axis=1)
        out["rb5"] = spec["settings"][s5]["rb_probability"]
        out["bb2"] = spec["settings"][s2]["bb_probability"]
        out["rb2"] = spec["settings"][s2]["rb_probability"]
        parts.append(out)
    return pd.concat(parts)


def build(hall, since, snapshot=None):
    raw = _load_raw(hall, since)
    if snapshot is not None:
        raw = pd.concat([raw, snapshot], ignore_index=True)
    raw = raw.merge(_layout(hall), on="u", how="left")
    d = _posteriors(raw, load_specs(hall=hall))
    d["rbp"] = d.rb / d.g
    d["bbp"] = d.bb / d.g
    d["rb_good"] = d.rbp >= d.rb5  # RBが設定5水準以上
    d["bb_bad"] = d.bbp <= d.bb2  # BBが設定2以下
    d["fuhatsu"] = d.rb_good & ((d["diff"] <= 1000) | d.bb_bad)
    d["sec_diff"] = d.groupby(["date", "section"])["diff"].transform("mean")
    pv = raw.pivot_table(index="d", columns="u", values="diff", dropna=False)
    pv = pv.reindex(pd.date_range(pv.index.min(), pv.index.max()))
    r7 = pv.rolling(7, min_periods=4).mean().stack().rename("r7").reset_index()
    r7.columns = ["d", "u", "r7"]
    d = d.merge(r7, on=["d", "u"], how="left")
    d["r7band"] = (
        pd.cut(d.r7, [-1e9, -1500, -500, 500, 1e9], labels=["<=-1500", "-1500~-500", "-500~500", ">=500"])
        .astype(object)
        .fillna("NA")
    )
    return d


def pairs(d):
    nx = d[["u", "d", "ph"]].copy()
    nx["d"] = nx["d"] - pd.Timedelta(days=1)
    return d.merge(nx.rename(columns={"ph": "ph_next"}), on=["u", "d"])


class Boot:
    def __init__(self, z, n=300, seed=0):
        self.z = z
        self.agg = z.groupby("u").ph_next.agg(["sum", "count"])
        self.rng = np.random.default_rng(seed)
        self.n = n
        self.base = z.ph_next.mean()

    def ci(self, mask, ref=None):
        """群の平均 - 基準(既定は全体、refを渡すとその部分集合)の平均 を台単位ブートストラップで区間推定。"""
        idx_u = self.agg.index
        gs = self.z[mask].groupby("u").ph_next.agg(["sum", "count"]).reindex(idx_u).fillna(0).values
        if ref is None:
            b = self.agg.values
        else:
            b = self.z[ref].groupby("u").ph_next.agg(["sum", "count"]).reindex(idx_u).fillna(0).values
        vals = []
        for _ in range(self.n):
            i = self.rng.integers(0, len(idx_u), len(idx_u))
            if gs[i, 1].sum() == 0 or b[i, 1].sum() == 0:
                continue
            vals.append(gs[i, 0].sum() / gs[i, 1].sum() - b[i, 0].sum() / b[i, 1].sum())
        return np.percentile(vals, [5, 95])

    def line(self, label, mask, ref=None):
        """refを渡すと、その部分集合(機種・島)自身の平均との差を出す。"""
        n = int(mask.sum())
        if n < MIN_N:
            return f"{label:<40} n={n:4d} (少数)"
        mean = self.z.ph_next[mask].mean()
        base = self.base if ref is None else self.z.ph_next[ref].mean()
        lo, hi = self.ci(mask, ref)
        tag = "全体比" if ref is None else "自群比"
        return f"{label:<40} n={n:4d} 翌日5以上 {mean:.3f} ({tag} {mean - base:+.3f}, 90%CI {lo:+.3f}~{hi:+.3f})"


def cmd_groups(args):
    d = build(args.hall, args.since)
    z = pairs(d)
    b = Boot(z)
    print(f"{args.hall}: 連続2日の台日 {len(z)} / 台 {z.u.nunique()} / 翌日の平均 設定5以上確率(全体) {b.base:.3f}")
    print("\n[全体]")
    for lab, mk in (
        ("前日RB良(設定5水準以上)", z.rb_good),
        ("  不発(RB良 & 差枚<=1000 or BB設定2以下)", z.fuhatsu),
        ("  RB良 & BBも悪くなく差枚>1000", z.rb_good & ~z.bb_bad & (z["diff"] > 1000)),
        ("前日RB悪(設定2以下) & 差枚<=-1000", (z.rbp <= z.rb2) & (z["diff"] <= -1000)),
        ("過去7日平均 -1500~-500", z.r7band == "-1500~-500"),
        ("過去7日平均 >=500", z.r7band == ">=500"),
    ):
        print(b.line(lab, mk))
    print("\n[条件の組み合わせ: 前日RB良 x 過去7日平均]")
    for rg in (True, False):
        for band in ("-1500~-500", "-500~500", ">=500"):
            print(b.line(f"RB良={'有' if rg else '無'} / 7日{band}", (z.rb_good == rg) & (z.r7band == band)))
    print("\n[機種別: 前日RB良の上乗せ]")
    for m, sub in z.groupby("m"):
        if len(sub) < 300:
            continue
        mk = z.m == m
        print(f"--- {m} ({sub.u.nunique()}台, 翌日平均 {z.ph_next[mk].mean():.3f})")
        print("  " + b.line("前日RB良", mk & z.rb_good, ref=mk))
        print("  " + b.line("過去7日 -1500~-500", mk & (z.r7band == "-1500~-500"), ref=mk))
    print("\n[島別: 前日RB良の上乗せ(島の台日300以上)]")
    for sec, sub in z.groupby("section"):
        if len(sub) < 300:
            continue
        mk = z.section == sec
        print(
            f"--- {sec} ({sub.u.nunique()}台, 翌日平均 {z.ph_next[mk].mean():.3f})  "
            + b.line("前日RB良", mk & z.rb_good, ref=mk).strip()
        )


def cmd_tomorrow(args):
    snap, name = _latest_snapshot(args.hall)
    d = build(args.hall, args.since, snapshot=snap)
    hist = pairs(d[d.d < snap.d.iloc[0]])
    day = d[d.d == snap.d.iloc[0]].copy()
    cell = (
        hist.groupby(["rb_good", "r7band"])
        .ph_next.agg(["mean", "count"])
        .rename(columns={"mean": "cell_mean", "count": "cell_n"})
    )
    day = day.merge(cell, left_on=["rb_good", "r7band"], right_index=True, how="left")
    print(f"スナップショット {name} / 履歴の翌日平均 {hist.ph_next.mean():.3f} / 今日の候補台日 {len(day)}")
    print("今日の差枚が無い収集では差枚由来の型(不発)は使わず、RB良と過去7日で見る。\n")
    cols = ["u", "m", "g", "rb", "bb", "rb_good", "bb_bad", "r7band", "cell_mean", "cell_n", "ph"]
    day = day.sort_values(["cell_mean", "ph"], ascending=False)
    print(day.head(args.top)[cols].round(3).to_string(index=False))


def main(argv=None):
    sys.stdout.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    for name, fn in (("groups", cmd_groups), ("tomorrow", cmd_tomorrow)):
        sp = sub.add_parser(name)
        sp.add_argument("--hall", default=DEFAULT_HALL)
        sp.add_argument("--since", default="20260601")
        if name == "tomorrow":
            sp.add_argument("--top", type=int, default=20)
        sp.set_defaults(fn=fn)
    args = p.parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    main()
