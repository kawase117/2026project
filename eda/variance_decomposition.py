# -*- coding: utf-8 -*-
"""シグナル上限の定量化：機械割の分散分解.

台×日の機械割 y = diff/(3G) を
  y_it = m + a_t(日効果) + b_i(台効果) + c_it(台×日シグナル) + e_it(出玉ノイズ)
に分解し、各成分の「真の」分散を推定する。

- a_t, b_i: 二元固定効果 + split-half信頼性(Spearman-Brown)でノイズ補正
- c_it vs e_it: E[r^2] = Var(c) + v/(9G) の 1/(9G) 回帰で分離（機種クラス別）
- 日効果のカレンダー予測可能性: 5-fold CV の OOS R^2

実行: venv/Scripts/python.exe eda/variance_decomposition.py
出力: 標準出力サマリ + JSON（--out で指定）
"""

import argparse
import glob
import json
import os
import sqlite3
import sys

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")

MIN_GAMES = 100
MIN_MACHINES_PER_DAY = 30
NEW_MACHINE_EXCLUDE_DAYS = 7
FE_MAX_ITER = 300
FE_TOL = 1e-12
SEED = 42


def classify(name: str) -> str:
    if "ジャグラー" in name:
        return "jug"
    if "ハナハナ" in name:
        return "hana"
    return "other"


def load_hall(db_path: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    con = sqlite3.connect(db_path)
    df = pd.read_sql_query(
        """SELECT date, machine_number, machine_name,
                  games_normalized AS games, diff_coins_normalized AS diff,
                  bb_count, rb_count
           FROM machine_detailed_results
           WHERE games_normalized IS NOT NULL AND diff_coins_normalized IS NOT NULL""",
        con,
    )
    cal = pd.read_sql_query(
        """SELECT date, day_of_week, last_digit, is_zorome, is_strong_zorome,
                  is_month_start, is_month_end, is_holiday
           FROM daily_hall_summary""",
        con,
    )
    con.close()
    return df, cal


def apply_filters(df: pd.DataFrame, hall: str) -> pd.DataFrame:
    df = df[df["games"] >= MIN_GAMES].copy()

    # 蒲田7: 7/7全台設定6日と鉄台2026を除外
    if "蒲田7" in hall:
        df = df[~df["date"].str.endswith("0707")]
        df = df[df["machine_number"] != 2026]

    # 新台除外: (台番, 機種)ペア初出現から7日間。ホール初日から存在するペアは対象外
    df["dt"] = pd.to_datetime(df["date"], format="%Y%m%d")
    hall_start = df["dt"].min()
    first_seen = df.groupby(["machine_number", "machine_name"])["dt"].transform("min")
    is_new_period = (first_seen > hall_start) & ((df["dt"] - first_seen).dt.days < NEW_MACHINE_EXCLUDE_DAYS)
    df = df[~is_new_period]

    # 稼働台数の少ない日（休業・データ欠落）を除外
    day_counts = df.groupby("date")["machine_number"].transform("count")
    df = df[day_counts >= MIN_MACHINES_PER_DAY]

    df["y"] = df["diff"] / (3.0 * df["games"])
    df["cls"] = df["machine_name"].map(classify)
    return df


def twoway_fe(df: pd.DataFrame) -> tuple[float, pd.Series, pd.Series, pd.Series]:
    """反復demeanで y = m + a_t + b_i + r を推定."""
    m = df["y"].mean()
    a = pd.Series(0.0, index=pd.Index(sorted(df["date"].unique()), name="date"))
    b = pd.Series(0.0, index=pd.Index(sorted(df["machine_number"].unique()), name="machine_number"))
    y = df["y"].to_numpy()
    dates = df["date"].to_numpy()
    machs = df["machine_number"].to_numpy()
    for _ in range(FE_MAX_ITER):
        res_a = pd.Series(y - m - b.reindex(machs).to_numpy(), index=dates)
        a_new = res_a.groupby(level=0).mean()
        res_b = pd.Series(y - m - a_new.reindex(dates).to_numpy(), index=machs)
        b_new = res_b.groupby(level=0).mean()
        delta = max(
            (a_new - a.reindex(a_new.index).fillna(0)).abs().max(),
            (b_new - b.reindex(b_new.index).fillna(0)).abs().max(),
        )
        a, b = a_new, b_new
        if delta < FE_TOL:
            break
    r = y - m - a.reindex(dates).to_numpy() - b.reindex(machs).to_numpy()
    return m, a, b, pd.Series(r, index=df.index)


def spearman_brown(r_half: float) -> float:
    if r_half <= 0:
        return 0.0
    return 2 * r_half / (1 + r_half)


def day_effect_reliability(df: pd.DataFrame, b: pd.Series, rng) -> float:
    """台効果除去後、日内で台を半分に割り、半分平均同士の日間相関→SB補正."""
    adj = df["y"].to_numpy() - b.reindex(df["machine_number"].to_numpy()).to_numpy()
    tmp = pd.DataFrame({"date": df["date"].to_numpy(), "adj": adj})
    tmp["half"] = rng.integers(0, 2, len(tmp))
    piv = tmp.groupby(["date", "half"])["adj"].mean().unstack("half")
    piv = piv.dropna()
    counts = tmp.groupby(["date", "half"]).size().unstack("half").reindex(piv.index)
    piv = piv[(counts[0] >= 10) & (counts[1] >= 10)]
    if len(piv) < 30:
        return np.nan
    r = np.corrcoef(piv[0], piv[1])[0, 1]
    return spearman_brown(r)


def machine_effect_reliability(df: pd.DataFrame, a: pd.Series, min_days: int = 60) -> float:
    """日効果除去後、各台の稼働日を交互に2分し、半分平均同士の台間相関→SB補正."""
    adj = df["y"].to_numpy() - a.reindex(df["date"].to_numpy()).to_numpy()
    tmp = pd.DataFrame({"mach": df["machine_number"].to_numpy(), "date": df["date"].to_numpy(), "adj": adj})
    tmp = tmp.sort_values(["mach", "date"])
    tmp["k"] = tmp.groupby("mach").cumcount() % 2
    piv = tmp.groupby(["mach", "k"])["adj"].mean().unstack("k")
    counts = tmp.groupby(["mach", "k"]).size().unstack("k").reindex(piv.index)
    piv = piv[(counts[0] >= min_days // 2) & (counts[1] >= min_days // 2)].dropna()
    if len(piv) < 30:
        return np.nan
    r = np.corrcoef(piv[0], piv[1])[0, 1]
    return spearman_brown(r)


def _fit_var_c(res: np.ndarray, x: np.ndarray, n_bins: int = 5):
    """Gビン内の var(r) を x=1/(9G) のビン平均に回帰し (var_c=切片, v=傾き) を返す.

    E[r^2] でなく Var(r|bin) を使う理由: 出玉が良い台ほど長く回される内生性で
    高Gビンの E[r] が正にシフトし、E[r^2] だと (E[r])^2 分だけ切片が過大になる。
    """
    tmp = pd.DataFrame({"res": res, "x": x})
    nq = min(n_bins, tmp["x"].nunique())
    if nq < 2:
        return None
    q = pd.qcut(tmp["x"], nq, duplicates="drop")
    g = tmp.groupby(q, observed=True)
    bm = pd.DataFrame({"x": g["x"].mean(), "vr": g["res"].var(), "n": g.size()})
    bm = bm[bm["n"] >= 20].dropna()
    if len(bm) < 2:
        return None
    slope, intercept = np.polyfit(bm["x"], bm["vr"], 1)
    return float(intercept), float(slope)


def residual_noise_split(df: pd.DataFrame, r: pd.Series, min_n_per_name: int = 300) -> dict:
    """E[r^2] = Var(c) + v/(9G) を機種名別に回帰し、クラス・ホールへ加重集計.

    機種名別に行う理由: 機種ごとに出玉ノイズ v が大きく異なり（ジャグ≒200,
    AT≒2500 coins^2/G）、G分布とも相関するため、プール回帰では切片が歪む。
    機種名単位の var_c は負も許容して集計し、集計後に0で下限を取る。
    """
    rr_all = r.to_numpy()
    x_all = 1.0 / (9.0 * df["games"].to_numpy())
    pos = {idx: i for i, idx in enumerate(df.index)}

    per_name = []
    fallback_idx = []
    for name, sub_idx in df.groupby("machine_name").groups.items():
        if len(sub_idx) < min_n_per_name:
            fallback_idx.extend(sub_idx)
            continue
        rows = [pos[i] for i in sub_idx]
        fit = _fit_var_c(rr_all[rows], x_all[rows])
        if fit is None:
            fallback_idx.extend(sub_idx)
            continue
        cls = df.loc[sub_idx[0], "cls"]
        per_name.append({"name": name, "cls": cls, "n": len(sub_idx), "var_c": fit[0], "v": fit[1]})

    # 小規模機種はクラス単位でフォールバック回帰
    fb = pd.Series(fallback_idx)
    if len(fb) > 0:
        fb_df = df.loc[fb]
        for cls, sub_idx in fb_df.groupby("cls").groups.items():
            rows = [pos[i] for i in sub_idx]
            fit = _fit_var_c(rr_all[rows], x_all[rows])
            if fit is not None:
                per_name.append(
                    {"name": f"_fallback_{cls}", "cls": cls, "n": len(sub_idx), "var_c": fit[0], "v": fit[1]}
                )

    out = {}
    total_n = sum(p["n"] for p in per_name)
    for cls in sorted({p["cls"] for p in per_name}):
        ps = [p for p in per_name if p["cls"] == cls]
        n_cls = sum(p["n"] for p in ps)
        var_c_cls = sum(p["var_c"] * p["n"] for p in ps) / n_cls
        v_cls = sum(p["v"] * p["n"] for p in ps) / n_cls
        out[cls] = {
            "n": int(n_cls),
            "n_models_fit": int(sum(1 for p in ps if not p["name"].startswith("_fallback"))),
            "var_c": float(max(var_c_cls, 0.0)),
            "var_c_raw": float(var_c_cls),
            "v_per_game": float(max(v_cls, 0.0)),
        }
    var_c_w = sum(p["var_c"] * p["n"] for p in per_name) / total_n
    v_w = sum(p["v"] * p["n"] for p in per_name) / total_n
    out["_weighted"] = {
        "var_c": float(max(var_c_w, 0.0)),
        "var_c_raw": float(var_c_w),
        "v_per_game": float(v_w),
        "coverage_per_name": float(1 - len(fb) / max(len(df), 1)),
    }
    return out


def calendar_cv_r2(a: pd.Series, cal: pd.DataFrame, seed: int = SEED) -> dict:
    """日効果 a_t をカレンダー特徴で5-fold CV回帰し OOS R^2 を返す."""
    from sklearn.linear_model import LinearRegression
    from sklearn.model_selection import KFold

    cal = cal.copy()
    cal["date"] = cal["date"].astype(str)
    flag_cols = ["is_zorome", "is_strong_zorome", "is_month_start", "is_month_end", "is_holiday"]
    cal[flag_cols] = cal[flag_cols].fillna(0)
    day_df = (
        a.rename_axis("date")
        .rename("a")
        .reset_index()
        .assign(date=lambda d: d["date"].astype(str))
        .merge(cal[["date"] + flag_cols], on="date", how="left")
        .dropna(subset=["a"])
    )
    day_df[flag_cols] = day_df[flag_cols].fillna(0)
    # day_of_week / last_digit はDB側の欠損が多いため date から導出する
    dt = pd.to_datetime(day_df["date"], format="%Y%m%d")
    day_df["day_of_week"] = dt.dt.weekday.astype(str)
    day_df["last_digit"] = (dt.dt.day % 10).astype(str)
    if len(day_df) < 60:
        return {"n_days": int(len(day_df)), "oos_r2": None}
    X = pd.get_dummies(day_df[["day_of_week", "last_digit"]].astype(str), drop_first=True)
    for f in ["is_zorome", "is_strong_zorome", "is_month_start", "is_month_end", "is_holiday"]:
        X[f] = day_df[f].fillna(0).astype(float)
    Xv = X.to_numpy(dtype=float)
    yv = day_df["a"].to_numpy()
    kf = KFold(n_splits=5, shuffle=True, random_state=seed)
    sse, sst = 0.0, 0.0
    for tr, te in kf.split(Xv):
        model = LinearRegression().fit(Xv[tr], yv[tr])
        pred = model.predict(Xv[te])
        sse += float(((yv[te] - pred) ** 2).sum())
        sst += float(((yv[te] - yv[tr].mean()) ** 2).sum())
    return {"n_days": int(len(day_df)), "oos_r2": float(1 - sse / sst)}


# ジャグラー設定1→6でのRB確率差とペイアウト差の概算比（Δpayout/Δp_RB）。
# マイジャグV: (1.094-0.970)/(1/240-1/409)≈72, アイム: ≈89。中庸の75を採用。
RB_TO_PAYOUT_SLOPE = 75.0


def jug_rb_decomposition(df: pd.DataFrame, rng) -> dict | None:
    """ジャグラーのRB率 z=RB/G を分解。二項ノイズ p(1-p)/G は解析的に既知のため、
    G→稼働の内生性（打ち切り選択）に汚染されない Var(c) 推定が得られる."""
    jug = df[(df["cls"] == "jug") & df["rb_count"].notna() & (df["games"] >= 500)].copy()
    if len(jug) < 5000:
        return None
    jug["y"] = jug["rb_count"] / jug["games"]
    m, a, b, r = twoway_fe(jug)
    mu = np.clip(
        m + a.reindex(jug["date"].to_numpy()).to_numpy() + b.reindex(jug["machine_number"].to_numpy()).to_numpy(),
        1e-4,
        0.05,
    )
    binom_var = mu * (1 - mu) / jug["games"].to_numpy()
    var_c_z = float(r.var() - binom_var.mean())

    rel_day = day_effect_reliability(jug, b, rng)
    rel_mach = machine_effect_reliability(jug, a)
    var_a_true = float(a.var()) * rel_day if np.isfinite(rel_day) else np.nan
    var_b_true = float(b.var()) * rel_mach if np.isfinite(rel_mach) else np.nan

    def to_pp(var_z):
        if var_z is None or not np.isfinite(var_z) or var_z <= 0:
            return 0.0
        return float(np.sqrt(var_z) * RB_TO_PAYOUT_SLOPE * 100)

    return {
        "n": int(len(jug)),
        "mean_rb_per_game": float(m),
        "var_c_z": var_c_z,
        "machine_day_signal_sd_payout_pp": to_pp(var_c_z),
        "day_effect_sd_payout_pp": to_pp(var_a_true),
        "day_reliability": float(rel_day) if np.isfinite(rel_day) else None,
        "machine_effect_sd_payout_pp": to_pp(var_b_true),
        "machine_reliability": float(rel_mach) if np.isfinite(rel_mach) else None,
        "note": f"payout換算はΔpayout/Δp_RB={RB_TO_PAYOUT_SLOPE}の近似",
    }


def analyze_hall(db_path: str, rng) -> dict:
    hall = os.path.splitext(os.path.basename(db_path))[0]
    raw, cal = load_hall(db_path)
    df = apply_filters(raw, hall)
    if len(df) < 5000:
        return {"hall": hall, "skipped": True, "n": int(len(df))}

    m, a, b, r = twoway_fe(df)

    var_a_raw = float(a.var())
    var_b_raw = float(b.var())
    rel_day = day_effect_reliability(df, b, rng)
    rel_mach = machine_effect_reliability(df, a)
    var_a_true = var_a_raw * rel_day if np.isfinite(rel_day) else np.nan
    var_b_true = var_b_raw * rel_mach if np.isfinite(rel_mach) else np.nan

    noise = residual_noise_split(df, r)
    var_c_true = noise["_weighted"]["var_c"]
    v = noise["_weighted"]["v_per_game"]

    cal_r2 = calendar_cv_r2(a, cal)
    jug_rb = jug_rb_decomposition(df, rng)

    mean_games = float(df["games"].mean())
    noise_var_at_mean_g = v / (9.0 * mean_games)

    return {
        "hall": hall,
        "n_rows": int(len(df)),
        "n_days": int(df["date"].nunique()),
        "n_machines": int(df["machine_number"].nunique()),
        "mean_payout": float(1 + m),
        "mean_games": mean_games,
        "grand_var_y": float(df["y"].var()),
        "day_effect": {
            "var_raw": var_a_raw,
            "reliability": float(rel_day) if np.isfinite(rel_day) else None,
            "var_true": float(var_a_true) if np.isfinite(var_a_true) else None,
            "sd_true_pp": float(np.sqrt(var_a_true) * 100) if var_a_true == var_a_true else None,
        },
        "machine_effect": {
            "var_raw": var_b_raw,
            "reliability": float(rel_mach) if np.isfinite(rel_mach) else None,
            "var_true": float(var_b_true) if np.isfinite(var_b_true) else None,
            "sd_true_pp": float(np.sqrt(var_b_true) * 100) if var_b_true == var_b_true else None,
        },
        "machine_day_signal": {
            "var_true": var_c_true,
            "sd_true_pp": float(np.sqrt(var_c_true) * 100),
            "by_class": {k: v_ for k, v_ in noise.items() if k != "_weighted"},
        },
        "sampling_noise": {
            "v_per_game": v,
            "sd_at_mean_games_pp": float(np.sqrt(noise_var_at_mean_g) * 100),
        },
        "calendar_day_effect": cal_r2,
        "jug_rb": jug_rb,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db-glob", default="db/*.db")
    ap.add_argument("--out", default="variance_decomposition_results.json")
    args = ap.parse_args()

    rng = np.random.default_rng(SEED)
    results = []
    for p in sorted(glob.glob(args.db_glob)):
        if "poco_analysis" in p:
            continue
        print(f"=== {os.path.basename(p)} ===", flush=True)
        try:
            res = analyze_hall(p, rng)
        except Exception as e:
            res = {"hall": os.path.basename(p), "error": str(e)}
        results.append(res)
        summary = {k: res.get(k) for k in ("hall", "n_rows", "n_days", "mean_payout", "error", "skipped") if k in res}
        print(json.dumps(summary, ensure_ascii=False), flush=True)

    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2, default=str)
    print(f"\nsaved: {args.out}")


if __name__ == "__main__":
    main()
