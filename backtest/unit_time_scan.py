"""単位(機種・島・機種タイプ)×時間軸の総当たり。

`axis_scan.py` が位置軸(末尾・角番・並び)×時間軸を見るのに対し、こちらは
「どの機種(島・機種タイプ)が、どの日付の条件で高いか」を見る。台日表は
`axis_scan.build_day_table` の出力(seg=RB/OTHER、hit/E、Ediff、Gx)をそのまま使う。

指標:
- RB当り: 当り回数/期待回数 - 1(seg=RBの台日のみ)
- 機械割: Σ(差枚-期待差枚) / Σ3G (pt)。seg=OTHERの台日のみ(RB側は差枚を機械割に使わない)
- 回転数: ΣG / ΣGx - 1(客数補正後の期待回転数に対する比)

検定は日付ラベルの並べ替え。曜日の軸は月の中、それ以外は曜日の中で入れ替える。
族(軸×水準×指標)ごとにスチューデント化したzの最大でp、セルは両側pをBH補正。
"""

import datetime as dt
import json
import os

import numpy as np
import pandas as pd

REGISTRY = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "document", "registry")
OUTCOMES = ("RB当り", "機械割", "回転数")


def _bh(p: pd.Series) -> pd.Series:
    s = p.sort_values()
    q = np.minimum(1, np.minimum.accumulate((s * len(s) / (np.arange(len(s)) + 1)).to_numpy()[::-1])[::-1])
    return pd.Series(q, index=s.index).reindex(p.index)


def machine_type(name: str, cat: str) -> str:
    if "ジャグラー" in name:
        return "ジャグラー"
    if "ハナハナ" in name or "ハナビ" in name:
        return "ハナハナ・ハナビ"
    return {"ノーマル": "ノーマル他", "BT": "BT", "A+AT": "A+AT"}.get(cat, "AT・ART")


def event_dates(hall: str) -> dict[str, set[str]]:
    out: dict[str, set[str]] = {}
    path = os.path.join(REGISTRY, "EVENT_DAYS.jsonl")
    for line in open(path, encoding="utf-8"):
        if not line.strip():
            continue
        r = json.loads(line)
        if r.get("hall") == hall:
            out.setdefault(r["kind"], set()).add(r["date"])
    return out


def time_labels(
    days: list[str], day_traffic: pd.Series, event_days: set[str], extra: dict[str, np.ndarray] | None = None
):
    """軸 -> {水準: bool(日)}。入れ替えの層は `strata_of` が決める。extraはホール固有の水準(軸名「ホール固有」)。"""
    import jpholiday

    dd = np.array([int(d[6:]) for d in days])
    mm = np.array([int(d[4:6]) for d in days])
    date = [dt.date(int(d[:4]), int(d[4:6]), int(d[6:])) for d in days]
    wd = np.array([x.weekday() for x in date])
    hol = np.array([jpholiday.is_holiday(x) for x in date])
    pre_hol = np.array([jpholiday.is_holiday(x + dt.timedelta(days=1)) for x in date])
    ax: dict[str, dict[str, np.ndarray]] = {}
    ax["曜日"] = {"月火水木金土日"[w] + "曜": wd == w for w in range(7)}
    ax["D(下一桁)"] = {f"{k}のつく日": (dd % 10) == k for k in range(10)}
    ax["DD(日付)"] = {f"{k}日": dd == k for k in range(1, 32)}
    ax["ゾロ目"] = {"ゾロ目(11,22)": np.isin(dd, [11, 22]), "強ゾロ目(月=日)": dd == mm}
    ax["月内の週"] = {
        "1-7日": dd <= 7,
        "8-14日": (dd >= 8) & (dd <= 14),
        "15-21日": (dd >= 15) & (dd <= 21),
        "22-28日": (dd >= 22) & (dd <= 28),
        "29日以降": dd >= 29,
    }
    ax["給料日・月末"] = {"月初1-3日": dd <= 3, "給料日前後24-26日": (dd >= 24) & (dd <= 26), "月末28日以降": dd >= 28}
    ax["祝日"] = {"祝日": hol, "祝日の前日": pre_hol, "土日祝": hol | (wd >= 5)}
    prev = day_traffic.reindex(days).shift(1)
    hi, lo = prev.quantile(0.75), prev.quantile(0.25)
    ax["前日の稼働"] = {
        "前日が高稼働(上位25%)": (prev >= hi).to_numpy(),
        "前日が低稼働(下位25%)": (prev <= lo).to_numpy(),
    }
    if event_days:
        ax["イベント日(台帳)"] = {"台帳のイベント日": np.array([d in event_days for d in days])}
    if extra:
        ax["ホール固有"] = extra
    return ax


def strata_of(axis: str, days: list[str]) -> np.ndarray:
    if axis == "曜日":
        return np.array([d[:6] for d in days])  # 曜日の軸は、月の中で入れ替える
    return np.array([dt.date(int(d[:4]), int(d[4:6]), int(d[6:])).weekday() for d in days])


def perm_index(strata: np.ndarray, B: int, rng: np.random.Generator) -> np.ndarray:
    """層の中で日を入れ替えるインデックス(B×日)。"""
    D = len(strata)
    out = np.tile(np.arange(D), (B, 1))
    for s in np.unique(strata):
        ix = np.where(strata == s)[0]
        if len(ix) < 2:
            continue
        out[:, ix] = ix[np.argsort(rng.random((B, len(ix))), axis=1)]
    return out


def unit_matrices(df: pd.DataFrame, unit_col: str, days: list[str]):
    r = df.dropna(subset=[unit_col])
    units = sorted(r[unit_col].unique())
    ui = {u: i for i, u in enumerate(units)}
    di = {d: i for i, d in enumerate(days)}
    D, K = len(days), len(units)
    ix = (r.ds.map(di).to_numpy(), r[unit_col].map(ui).to_numpy())
    rb = (r.seg == "RB").to_numpy()
    ot = (r.seg == "OTHER").to_numpy()

    def acc(values, mask=None) -> np.ndarray:
        A = np.zeros((D, K))
        v = np.asarray(values, float)
        if mask is not None:
            v = np.where(mask, v, 0.0)
        np.add.at(A, ix, v)
        return A

    one = np.ones(len(r))
    M = dict(
        O=acc(r.hit, rb),
        E=acc(r.E.fillna(0), rb),
        X=acc((r["diff"] - r.Ediff).fillna(0), ot),
        G3=3 * acc(r.G, ot),
        G=acc(r.G),
        Gx=acc(r.Gx),
        P=acc(one),
        Prb=acc(one, rb),
        Pot=acc(one, ot),
    )
    return units, M


def _stats(L: np.ndarray, M: dict) -> np.ndarray:
    """L: (n, D)のbool/0-1。戻り値: (3, n, K)。"""
    L = L.astype(float)
    with np.errstate(invalid="ignore", divide="ignore"):
        rb = (L @ M["O"]) / (L @ M["E"]) - 1
        ot = 100 * (L @ M["X"]) / (L @ M["G3"])
        gx = (L @ M["G"]) / (L @ M["Gx"]) - 1
    return np.stack([rb, ot, gx])


def scan_units(df, unit_col, time_ax, days, B=2000, min_unit_days=60, min_level_days=3, seed=11):
    """族(軸×水準×指標)とセル(軸×水準×単位×指標)の表を返す。"""
    rng = np.random.default_rng(seed)
    units, M = unit_matrices(df, unit_col, days)
    pres_of = (M["Prb"], M["Pot"], M["P"])
    fam_rows, cell_rows = [], []
    for axis, levels in time_ax.items():
        pix = perm_index(strata_of(axis, days), B, rng)
        for lvl, lab in levels.items():
            lab = np.asarray(lab, bool)
            n = int(lab.sum())
            if n < min_level_days:
                continue
            obs = _stats(lab[None], M)[:, 0, :]
            sims = np.empty((3, B, len(units)))
            for s0 in range(0, B, 500):
                sims[:, s0 : s0 + 500, :] = _stats(lab[pix[s0 : s0 + 500]], M)
            sd = np.nanstd(sims, axis=1)
            sd[sd == 0] = np.nan
            z = obs / sd
            zs = sims / sd[:, None, :]
            for o, oc in enumerate(OUTCOMES):
                P = pres_of[o]
                ok = ((lab.astype(float) @ P) >= min_level_days) & (P.sum(0) >= min_unit_days) & np.isfinite(z[o])
                if ok.sum() == 0:
                    continue
                zm = np.nanmax(np.abs(np.where(ok, z[o], np.nan)))
                fm = np.nanmax(np.where(ok[None], np.abs(zs[o]), -1), axis=1)
                fam_rows.append(
                    dict(
                        axis=axis,
                        level=lvl,
                        outcome=oc,
                        days=n,
                        units=int(ok.sum()),
                        p_family=(1 + np.sum(fm >= zm)) / (1 + B),
                    )
                )
                pc = (1 + np.sum(np.abs(np.nan_to_num(zs[o])) >= np.abs(np.nan_to_num(z[o]))[None], axis=0)) / (1 + B)
                for k in np.where(ok)[0]:
                    cell_rows.append(
                        dict(
                            axis=axis,
                            level=lvl,
                            outcome=oc,
                            unit=str(units[k]),
                            days=n,
                            obs=obs[o, k],
                            z=z[o, k],
                            p=pc[k],
                        )
                    )
    F = pd.DataFrame(fam_rows)
    C = pd.DataFrame(cell_rows)
    if len(C):
        C["q"] = _bh(C.p)
    return F, C


def summarize(F: pd.DataFrame, C: pd.DataFrame) -> str:
    out = []
    for oc in OUTCOMES:
        f, c = F[F.outcome == oc], C[C.outcome == oc]
        if len(c) == 0:
            continue
        out.append(
            f"{oc}: 族{len(f)}本中 p<0.05は{int((f.p_family < 0.05).sum())}(偶然なら約{0.05 * len(f):.1f})、"
            f"セル{len(c)}中 p<0.05は{int((c.p < 0.05).sum())}(約{0.05 * len(c):.0f})、BH q<0.2は{int((c.q < 0.2).sum())}"
        )
    return "\n".join(out)
