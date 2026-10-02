"""位置軸(末尾・角番・並び)× 時間軸(曜日・D・DD・ゾロ目・イベント公約)の総当たり検定。

なぜ要るか:
    2026-10-02の探索スクリプト(.claude/skills/hall-axis-scan/scripts/)を、テストつきのモジュールにしたもの。
    手順と落とし穴は `.claude/skills/hall-axis-scan/SKILL.md` にある。

指標は区分で変える:
    RB側   : ノーマル・BT(RB列)と、監査でAのAT機(AT_RB_AUDIT.csv、at_column)。当り回数のO/E(期待は機種×回転数帯)と、回転数。
    OTHER側: それ以外のAT等。機械割(差枚÷3Gの、同機種・同回転数帯の平均との差)と、回転数。
    回転数は、その日の区分全体の客数の増減を除いた期待(機種×曜日の平均G × その日の客数指数)との比。

検定:
    時間軸のラベル(日)を、曜日の中で(曜日の軸だけは月の中で)入れ替える並べ替え検定。
    位置軸は「時間水準の中と外で、位置の効果が違うか」の差の差、並びは時間水準の中と外の差。
    族(時間軸×位置軸×区分×指標)ごとにスチューデント化したzの最大で族のp、セルのpは両側、全セルをBH補正。

使い方:
    venv/Scripts/python.exe -X utf8 -m backtest.axis_scan --start 20260707 --end 20260930 --iters 2000
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd

from backtest import bonus_specs as bs
from backtest import monthly_report as mr

REGISTRY = Path(bs.ROOT) / "document" / "registry"
BAND_EDGES = [2000, 4000, 6000]
NEW_MACHINE_DAYS = 7
MIN_PAIR_MACHINE_UNITS = 3


# ---------------------------------------------------------------- 検定エンジン
def _stats(M, NUM, DEN, mode):
    """時間水準(列)ごとの検定統計量。M: (日, 水準)、NUM/DEN: (日, 位置水準)。"""
    S = np.einsum("dl,dk->lk", M, NUM)
    T = np.einsum("dl,dk->lk", M, DEN)
    NUMt, DENt = NUM.sum(0), DEN.sum(0)
    with np.errstate(invalid="ignore", divide="ignore"):
        if mode == "diff":
            return (S / T) - ((NUMt - S) / (DENt - T))
        s_all, t_all = S.sum(1, keepdims=True), T.sum(1, keepdims=True)
        r_in = S / T
        n_in = (s_all - S) / (t_all - T)
        sx, tx = NUMt - S, DENt - T
        sxa, txa = sx.sum(1, keepdims=True), tx.sum(1, keepdims=True)
        r_out = sx / tx
        n_out = (sxa - sx) / (txa - tx)
        return (r_in - n_in) - (r_out - n_out)


def permutation_scan(M, strata, NUM, DEN, mode="did", iters=2000, rng=None):
    """日ラベルを strata の中で入れ替える検定。

    mode="did" : 位置水準kとそれ以外の差を、時間水準の中と外で比べる(差の差)。
    mode="diff": 時間水準の中と外の差(位置を分けない。並びで使う)。
    戻り値: (族のp, obs, z, セルのp)。obs/z/セルのp は (時間水準, 位置水準)。
    """
    rng = np.random.default_rng() if rng is None else rng
    M = np.asarray(M, dtype=float)
    days = M.shape[0]
    groups = [np.where(strata == s)[0] for s in np.unique(strata)]
    obs = _stats(M, NUM, DEN, mode)
    sims = np.empty((iters,) + obs.shape)
    for i in range(iters):
        perm = np.arange(days)
        for ix in groups:
            perm[ix] = rng.permutation(ix)
        sims[i] = _stats(M[perm], NUM, DEN, mode)
    sd = np.nanstd(sims, axis=0)
    sd[sd == 0] = np.nan
    z, zs = obs / sd, sims / sd
    ok = np.isfinite(z)
    if not ok.any():
        return float("nan"), obs, z, np.full(obs.shape, np.nan)
    fam_max = np.nanmax(np.where(np.isfinite(zs), np.abs(zs), -1), axis=(1, 2))
    p_family = (1 + np.sum(fam_max >= np.nanmax(np.abs(z[ok])))) / (1 + iters)
    cell_p = (1 + np.nansum(np.abs(zs) >= np.abs(z)[None], axis=0)) / (1 + iters)
    cell_p = np.where(ok, cell_p, np.nan)
    return p_family, obs, z, cell_p


def bh_adjust(p):
    """Benjamini-Hochberg の補正後p(q値)。NaNは無視して NaN のまま返す。"""
    p = np.asarray(p, dtype=float)
    q = np.full(p.shape, np.nan)
    ok = np.isfinite(p)
    if not ok.any():
        return q
    values = p[ok]
    order = np.argsort(values)
    scaled = values[order] * len(values) / (np.arange(len(values)) + 1)
    adjusted = np.minimum.accumulate(scaled[::-1])[::-1].clip(max=1.0)
    out = np.empty_like(values)
    out[order] = adjusted
    q[ok] = out
    return q


# ---------------------------------------------------------------- 台日表の準備
def _weekday(ds):
    return dt.date(int(ds[:4]), int(ds[4:6]), int(ds[6:])).weekday()


def build_day_table(hall=mr.DEFAULT_HALL, start="20260707", end="20260930", specs=None):
    """台日表(区分 seg=RB/OTHER、当り回数 hit、期待 E / Ediff / Gexp、配置 ld / edge)を返す。"""
    db = mr.hall_db_path(hall)
    specs = specs or bs.load_specs()
    raw = mr.load_machine_days(db, start, end)
    spec_of = {n: bs.find_spec(n, specs) for n in raw.machine_name.unique()}
    cat = {n: (s or {}).get("category") for n, s in spec_of.items()}
    at_col = {n: s.get("at_column") for n, s in spec_of.items() if s and s.get("at_judgeable")}
    raw["cat"] = raw.machine_name.map(cat)

    def hit(row):
        col = at_col.get(row.machine_name)
        if col == "bb":
            return row.bb_count
        if col == "bb+rb":
            return row.bb_count + row.rb_count
        return row.rb_count

    raw["hit"] = [hit(r) for r in raw.itertuples()]
    is_rb = raw.cat.isin(["ノーマル", "BT"]) | raw.machine_name.isin(at_col)
    empty = (
        raw[raw.cat.isin(["ノーマル", "BT"])]
        .groupby("machine_name")
        .agg(rb=("rb_count", "sum"), bb=("bb_count", "sum"))
    )
    empty = set(empty.index[(empty.rb == 0) & (empty.bb > 0)])  # RB列が空の機種(不二子BTなど)は事後確率を出せない
    raw = raw[~(raw.machine_name.isin(empty) & raw.cat.isin(["ノーマル", "BT"]))].copy()
    raw["seg"] = np.where(is_rb.reindex(raw.index).fillna(False), "RB", "OTHER")
    first, _ = mr.load_first_seen(db)
    since = [
        (
            dt.date(int(d[:4]), int(d[4:6]), int(d[6:]))
            - dt.date(int(first[m][:4]), int(first[m][4:6]), int(first[m][6:]))
        ).days
        for d, m in zip(raw.ds, raw.machine_name)
    ]
    raw = raw[~((raw.seg == "OTHER") & (np.array(since) < NEW_MACHINE_DAYS))].copy()  # 新台は設定不問で高回転する
    raw["wd"] = raw.ds.map(_weekday)
    raw["band"] = np.digitize(raw.games_normalized, BAND_EDGES)
    raw["G"] = raw.games_normalized
    raw["machine_number"] = raw.machine_number.astype(int)
    raw = _attach_layout(raw, db)
    rb = raw[raw.seg == "RB"]
    cnt = rb.groupby(["machine_name", "ds"]).machine_number.transform("nunique")
    mx = cnt.groupby(rb.machine_name).max()
    need = rb.machine_name.map(lambda n: min(3, mx[n]))  # 2台機種は、その全台が稼働した日を使う
    raw = raw.drop(index=rb.index[cnt < need])
    return add_expectations(raw)


def _attach_layout(raw, db):
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        lay = pd.read_sql_query(
            "SELECT machine_number, valid_from, valid_to, section, rank_from_min, rank_from_max FROM machine_layout_history",
            con,
        )
    finally:
        con.close()
    lay["valid_to"] = lay.valid_to.fillna("99999999").astype(str)
    lay["valid_from"] = lay.valid_from.astype(str)
    merged = raw.reset_index().merge(lay, on="machine_number", how="left")
    merged = merged[(merged.ds >= merged.valid_from) & (merged.ds <= merged.valid_to)].set_index(
        "index"
    )  # 日付に対応する配置の版
    raw = raw.join(merged[["section", "rank_from_min", "rank_from_max"]])
    raw = raw[raw.section.notna()].copy()
    raw["edge"] = np.minimum(raw.rank_from_min, raw.rank_from_max)
    raw["ld"] = raw.machine_number % 10
    return raw


def add_expectations(raw):
    """期待当り回数 E(RB側)、期待差枚 Ediff(OTHER側)、期待回転数 Gexp、日の区分別の客数指数で補正した Gx。"""
    out = raw.copy()
    keys = ["machine_name", "band"]
    rb = out[out.seg == "RB"].groupby(keys).agg(hits=("hit", "sum"), games=("G", "sum"))
    other = out[out.seg == "OTHER"].groupby(keys).agg(diff=("diff_coins_normalized", "sum"), games=("G", "sum"))
    out = out.join((rb["hits"] / rb["games"]).rename("r"), on=keys).join(
        (other["diff"] / (3 * other["games"])).rename("pb"), on=keys
    )
    out["E"] = out.G * out.r
    out["Ediff"] = 3 * out.G * out.pb
    out["Gexp"] = out.groupby(["machine_name", "wd"]).G.transform("mean")
    day = out.groupby(["seg", "ds"]).agg(games=("G", "sum"), expected=("Gexp", "sum"))
    out = out.join((day["games"] / day["expected"]).rename("traffic"), on=["seg", "ds"])
    out["Gx"] = out.Gexp * out.traffic  # その日の区分全体の客数の増減を除いた期待回転数
    return out


def pair_residual_products(df, seg):
    """並びの強さ: 同機種・同セクションの連番ペアの、残差の積(日ごとの合計と組数)。

    同機種・同日の平均を引き、3台以上の機種に限る。引かないと全台系を並びと取り違える。
    """
    if seg == "RB":
        z = (df.hit - df.E) / np.sqrt(df.E.clip(lower=1e-6))
    else:
        pr = (df.diff_coins_normalized - df.Ediff) / (3 * df.G)
        z = pr * np.sqrt(df.G)
        z = z / z.std()
    d = df.assign(z=z.to_numpy())[["ds", "machine_number", "machine_name", "section", "z"]]
    size = d.groupby(["ds", "machine_name"]).z.transform("size")
    d = d[size >= MIN_PAIR_MACHINE_UNITS].copy()
    d["z"] = d.z - d.groupby(["ds", "machine_name"]).z.transform("mean")
    nxt = d.assign(machine_number=d.machine_number - 1)
    pairs = d.merge(nxt, on=["ds", "machine_number"], suffixes=("", "_n"))
    pairs = pairs[(pairs.machine_name == pairs.machine_name_n) & (pairs.section == pairs.section_n)]
    pairs = pairs.assign(p=pairs.z * pairs.z_n)
    return pairs.groupby("ds").agg(num=("p", "sum"), den=("p", "size"))


# ---------------------------------------------------------------- 時間軸
def _registry(name):
    path = REGISTRY / f"{name}.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def time_axes(days, hall=mr.DEFAULT_HALL, event_min_days=3, registry=None):
    """{軸名: (水準名, M(日×水準のbool), 入れ替えの層)}。"""
    wd = np.array([_weekday(d) for d in days])
    dd = np.array([int(d[6:]) for d in days])
    mm = np.array([int(d[4:6]) for d in days])
    axes = {
        "曜日": (["月火水木金土日"[w] + "曜" for w in range(7)], np.stack([wd == w for w in range(7)], 1), mm),
        "D(下一桁)": ([f"{k}のつく日" for k in range(10)], np.stack([dd % 10 == k for k in range(10)], 1), wd),
    }
    levels = sorted(set(dd))
    axes["DD(日付)"] = ([f"{k}日" for k in levels], np.stack([dd == k for k in levels], 1), wd)
    axes["ゾロ目"] = (["ゾロ目(11,22日)", "強ゾロ目(月=日)"], np.stack([np.isin(dd, [11, 22]), dd == mm], 1), wd)
    reg = (
        registry
        if registry is not None
        else {"EVENT_DAYS": _registry("EVENT_DAYS"), "EVENT_SERIES": _registry("EVENT_SERIES")}
    )
    events = {r["event_id"]: r for r in reg["EVENT_DAYS"] if r.get("hall") == hall}
    names, members = [], []
    for series in reg["EVENT_SERIES"]:
        if series.get("hall") != hall:
            continue
        dates = {events[e]["date"] for e in series["event_ids"] if e in events}
        flag = np.array([d in dates for d in days])
        if flag.sum() >= event_min_days:
            names.append(
                ("公約: " if series["axis"] == "pledge" else "イベント: ") + series["label"] + f"({int(flag.sum())}日)"
            )
            members.append(flag)
    if names:
        axes["イベント・公約"] = (names, np.stack(members, 1), wd)
    return axes


# ---------------------------------------------------------------- 全体
def position_levels(df, axis):
    if axis == "末尾":
        return [(f"末尾{k}", (df.ld == k).to_numpy()) for k in range(10)]
    return [
        ("角1", (df.edge == 1).to_numpy()),
        ("角2", (df.edge == 2).to_numpy()),
        ("角3以上", (df.edge >= 3).to_numpy()),
    ]


def day_matrices(df, num, den, axis, days):
    index = {d: i for i, d in enumerate(days)}
    levels = position_levels(df, axis)
    NUM = np.zeros((len(days), len(levels)))
    DEN = np.zeros((len(days), len(levels)))
    di = df.ds.map(index).to_numpy()
    for k, (_, mask) in enumerate(levels):
        NUM[:, k] = np.bincount(di[mask], weights=num.to_numpy(float)[mask], minlength=len(days))
        DEN[:, k] = np.bincount(di[mask], weights=den.to_numpy(float)[mask], minlength=len(days))
    return [name for name, _ in levels], NUM, DEN


def run_scan(df, iters=2000, seed=31, hall=mr.DEFAULT_HALL, registry=None):
    """全軸の総当たり。族の表 F とセルの表 C(BH補正つき)を返す。"""
    rng = np.random.default_rng(seed)
    days = sorted(df.ds.unique())
    axes = time_axes(days, hall, registry=registry)
    rb, other = df[df.seg == "RB"], df[df.seg == "OTHER"]
    outcomes = {
        ("RB", "当りO/E"): (rb, rb.hit, rb.E),
        ("RB", "回転数/期待"): (rb, rb.G, rb.Gx),
        ("OTHER", "機械割(差枚/3G)"): (other, other.diff_coins_normalized - other.Ediff, 3 * other.G),
        ("OTHER", "回転数/期待"): (other, other.G, other.Gx),
    }
    nar = {}
    for seg, part in (("RB", rb), ("OTHER", other)):
        if len(part):
            table = pair_residual_products(part, seg).reindex(days).fillna(0.0)
            nar[seg] = (table.num.to_numpy()[:, None], table.den.to_numpy()[:, None])
    fam, rows = [], []

    def record(axis_name, pos, seg, outcome, names, M, strata, NUM, DEN, labels, mode):
        p_family, obs, z, cell_p = permutation_scan(M, strata, NUM, DEN, mode, iters, rng)
        count = 0
        for a in range(len(names)):
            for k in range(NUM.shape[1]):
                if np.isfinite(z[a, k]):
                    count += 1
                    rows.append(
                        dict(
                            axis=axis_name,
                            pos=pos,
                            seg=seg,
                            outcome=outcome,
                            time=names[a],
                            level=labels[k],
                            days=int(M[:, a].sum()),
                            obs=obs[a, k],
                            z=z[a, k],
                            p=cell_p[a, k],
                        )
                    )
        fam.append(dict(axis=axis_name, pos=pos, seg=seg, outcome=outcome, p_family=p_family, cells=count))

    for axis_name, (names, M, strata) in axes.items():
        M = M.astype(float)
        for (seg, outcome), (part, num, den) in outcomes.items():
            if not len(part):
                continue
            for pos in ("末尾", "角番"):
                labels, NUM, DEN = day_matrices(part, num, den, pos, days)
                record(axis_name, pos, seg, outcome, names, M, strata, NUM, DEN, labels, "did")
        for seg, (NUM, DEN) in nar.items():
            record(axis_name, "並び", seg, "隣接ペア残差積", names, M, strata, NUM, DEN, ["隣接ペア"], "diff")
    F, C = pd.DataFrame(fam), pd.DataFrame(rows)
    if len(C):
        C["q"] = bh_adjust(C.p.to_numpy())
    return F, C


def summarize(F, C):
    """族とセルの要約(偶然の期待数と並べる)。"""
    lines = [f"族 {len(F)}本中 p_family<0.05: {int((F.p_family < 0.05).sum())}(偶然なら約{0.05 * len(F):.1f})"]
    if len(C):
        lines.append(
            f"セル {len(C)}、p<0.05 {int((C.p < 0.05).sum())}(偶然なら約{0.05 * len(C):.0f})、BH q<0.2 {int((C.q < 0.2).sum())}"
        )
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description="位置軸×時間軸の総当たり検定")
    parser.add_argument("--hall", default=mr.DEFAULT_HALL)
    parser.add_argument("--start", default="20260707")
    parser.add_argument("--end", default="20260930")
    parser.add_argument("--iters", type=int, default=2000)
    parser.add_argument("--seed", type=int, default=31)
    parser.add_argument("--top", type=int, default=15)
    args = parser.parse_args(argv)
    df = build_day_table(args.hall, args.start, args.end)
    print(
        "台日",
        df.groupby("seg").size().to_dict(),
        "機種",
        df.groupby("seg").machine_name.nunique().to_dict(),
        "日数",
        df.ds.nunique(),
    )
    F, C = run_scan(df, args.iters, args.seed, args.hall)
    pd.set_option("display.width", 250)
    pd.set_option("display.max_colwidth", 46)
    print(summarize(F, C))
    print("\n族(p順)\n", F.sort_values("p_family").round(3).to_string(index=False))
    print("\n上位セル(p順)\n", C.sort_values("p").head(args.top).round(3).to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
