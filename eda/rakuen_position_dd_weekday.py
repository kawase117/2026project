"""楽園蒲田店: 位置効果の形（勾配か階段か）と、DD・曜日による変動を調べる。

`eda/rakuen_clean_section_edge_effect.py` の続き。あちらで
「clean 35列の端(depth=1)に ジャグ +1.2pp / 技術介入 +1.4pp」
「端を除くと位置構造は消える（omnibus p=0.63/0.74）」まで確定した。

ここで答えるのは4つ:

    (A) 島の中ほどへ進むにつれ弱くなるのか、端だけに現れるのか
        → depth 1..7 の全プロファイルを CI 付きで出す。前スクリプトの (3b) は
          参照群を depth>=4 に固定していたため 4 以降の形が見えなかった
    (B) 端番効果は DD で変わるか
    (C) 端番効果は曜日で変わるか
    (D) セクション効果（どの列が強い/弱い）は DD・曜日で変わるか
        → `rakuen_theory.md` §8 のセクション×DDスイングは統合された誤 section
          時代の分析で「再計算が必要」と明記されている。その再計算にあたる

イベント日定義:
    `event_dds = {10, 11, 22, 30}`。`config/hall_config.json` の
    `event_digits=[11,22]` は実測スキャンで**誤りと確定**している
    （`document/rakuen_theory.md` §3、2026-07-11訂正）。

多重比較の扱い:
    DD は 31 水準、曜日は 7 水準、セクションは 35 列ある。全セルを個別に
    検定すると偽陽性が量産されるので、**まず omnibus 置換検定で「その軸に
    構造があるか」を判定し、通った軸だけ内訳を出す**。置換は日付→ラベルの
    対応を壊す形で行い、列の良し悪しや機種構成は保存する。

使い方:
    venv\\Scripts\\python.exe -m eda.rakuen_position_dd_weekday
"""

from __future__ import annotations

import sys

import numpy as np
import pandas as pd

from eda.rakuen_clean_section_edge_effect import (
    OUT_DIR,
    add_within_model_residual,
    load_frame,
)

N_BOOT = 2000
N_PERM = 2000
SEED = 20260728

EVENT_DDS = {10, 11, 22, 30}
WEEKDAY_JA = ["月", "火", "水", "木", "金", "土", "日"]


def prepare(df: pd.DataFrame) -> pd.DataFrame:
    dates = pd.to_datetime(df["date"], format="%Y%m%d")
    df = df.assign(
        dd=dates.dt.day,
        weekday=dates.dt.weekday.map(dict(enumerate(WEEKDAY_JA))),
    )
    df["is_event"] = df["dd"].isin(EVENT_DDS)
    return df


def depth_profile_ci(df: pd.DataFrame, rng: np.random.Generator) -> pd.DataFrame:
    """(A) depth 1..7 の全プロファイル。

    参照群を固定せず、各 depth の残差平均そのものを台単位ブートストラップの
    CI 付きで出す。機種内残差はゼロ和なので水準の絶対値に意味は無いが、
    **depth 間の形（どこで落ちるか）**は読める。
    """
    sub = df.loc[(df["group"] == "clean") & (df["section_size"] >= 9)]
    records = []
    for category in ("ジャグ", "技術介入", "AT一般"):
        cat = sub.loc[sub["category"] == category]
        for depth in range(1, 8):
            d = cat.loc[cat["depth"] == depth]
            if d.empty:
                continue
            unit = d.groupby("machine_number").agg(
                value=("resid_machine_rate", "mean"), w=("resid_machine_rate", "size")
            )
            if len(unit) < 3:
                continue
            vals, weights = unit["value"].to_numpy(), unit["w"].to_numpy()
            draws = np.empty(N_BOOT)
            for i in range(N_BOOT):
                idx = rng.integers(0, len(vals), len(vals))
                draws[i] = np.average(vals[idx], weights=weights[idx])
            lo, hi = np.percentile(draws, [2.5, 97.5])
            records.append(
                {
                    "category": category,
                    "depth": depth,
                    "n_machines": int(len(unit)),
                    "n_rows": int(len(d)),
                    "mean_pp": round(float(np.average(vals, weights=weights)), 3),
                    "ci_lo": round(float(lo), 3),
                    "ci_hi": round(float(hi), 3),
                    "sig": "*" if (lo > 0 or hi < 0) else "ns",
                }
            )
    return pd.DataFrame(records)


def daily_edge_series(df: pd.DataFrame) -> pd.DataFrame:
    """日ごとの「端 − 非端」。以降の軸別検定はこの1日1値の系列で行う。"""
    g = df.groupby(["date", "is_edge"])["resid_machine_rate"].mean().unstack()
    if not {True, False}.issubset(g.columns):
        return pd.DataFrame()
    out = (g[True] - g[False]).dropna().rename("edge_diff").reset_index()
    dates = pd.to_datetime(out["date"], format="%Y%m%d")
    out["dd"] = dates.dt.day
    out["weekday"] = dates.dt.weekday.map(dict(enumerate(WEEKDAY_JA)))
    out["is_event"] = out["dd"].isin(EVENT_DDS)
    return out


def omnibus_by_level(values: np.ndarray, levels: np.ndarray, rng: np.random.Generator) -> tuple[float, float, float]:
    """水準ラベルを並べ替えて「水準間のばらつき」が偶然を超えるか見る。

    返り値は (観測分散, 帰無中央値, p値)。
    """

    def stat(lab: np.ndarray) -> float:
        frame = pd.DataFrame({"lab": lab, "v": values})
        means = frame.groupby("lab")["v"].mean()
        counts = frame.groupby("lab")["v"].size()
        return float(np.average((means - np.average(means, weights=counts)) ** 2, weights=counts))

    observed = stat(levels)
    null = np.array([stat(rng.permutation(levels)) for _ in range(N_PERM)])
    return observed, float(np.median(null)), float((null >= observed).mean())


def edge_by_axis(df: pd.DataFrame, rng: np.random.Generator) -> pd.DataFrame:
    """(B)(C) 端番効果が DD・曜日で変わるか。omnibus を先に通す。"""
    records = []
    for category in ("ジャグ", "技術介入", "AT一般", "＜全体＞"):
        sub = df.loc[df["group"] == "clean"]
        if category != "＜全体＞":
            sub = sub.loc[sub["category"] == category]
        series = daily_edge_series(sub)
        if series.empty or len(series) < 60:
            continue

        overall = float(series["edge_diff"].mean())
        for axis, levels in (("曜日", series["weekday"]), ("DD", series["dd"])):
            obs, null_med, p = omnibus_by_level(series["edge_diff"].to_numpy(), levels.to_numpy(), rng)
            records.append(
                {
                    "category": category,
                    "axis": axis,
                    "level": "＜omnibus＞",
                    "n_days": int(len(series)),
                    "mean_pp": round(overall, 3),
                    "observed_var": round(obs, 4),
                    "null_median": round(null_med, 4),
                    "p_value": round(p, 4),
                    "sig": "*" if p < 0.05 else "ns",
                }
            )

        # イベント日は事前に定義された2値なので、omnibus とは別に直接比較する。
        ev = series.loc[series["is_event"], "edge_diff"]
        non = series.loc[~series["is_event"], "edge_diff"]
        if len(ev) >= 10 and len(non) >= 10:
            draws = np.empty(N_BOOT)
            e_arr, n_arr = ev.to_numpy(), non.to_numpy()
            for i in range(N_BOOT):
                draws[i] = (
                    e_arr[rng.integers(0, len(e_arr), len(e_arr))].mean()
                    - n_arr[rng.integers(0, len(n_arr), len(n_arr))].mean()
                )
            lo, hi = np.percentile(draws, [2.5, 97.5])
            records.append(
                {
                    "category": category,
                    "axis": "イベントDD{10,11,22,30}",
                    "level": "イベント − 通常",
                    "n_days": int(len(ev)),
                    "mean_pp": round(float(ev.mean() - non.mean()), 3),
                    "ci_lo": round(float(lo), 3),
                    "ci_hi": round(float(hi), 3),
                    "sig": "*" if (lo > 0 or hi < 0) else "ns",
                    "event_mean": round(float(ev.mean()), 3),
                    "normal_mean": round(float(non.mean()), 3),
                }
            )
    return pd.DataFrame(records)


def section_by_axis(df: pd.DataFrame, rng: np.random.Generator) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(D) セクション効果と、その DD・曜日による変動。

    セクション効果 = その列の機種内残差の平均（どの列が強いか）。
    まず主効果を CI 付きで出し、次に「列 × 軸」の交互作用が偶然を
    超えるかを omnibus で見る。交互作用の置換は日付→ラベルの対応だけを
    壊すので、列の主効果と軸の主効果は保存される。
    """
    sub = df.loc[df["group"] == "clean"]

    # --- 主効果: 列ごとの残差平均 ---
    main = []
    for section, g in sub.groupby("section"):
        unit = g.groupby("machine_number").agg(value=("resid_machine_rate", "mean"), w=("resid_machine_rate", "size"))
        vals, weights = unit["value"].to_numpy(), unit["w"].to_numpy()
        if len(vals) < 3:
            continue
        draws = np.empty(N_BOOT)
        for i in range(N_BOOT):
            idx = rng.integers(0, len(vals), len(vals))
            draws[i] = np.average(vals[idx], weights=weights[idx])
        lo, hi = np.percentile(draws, [2.5, 97.5])
        main.append(
            {
                "section": section,
                "n_machines": int(len(unit)),
                "n_rows": int(len(g)),
                "mean_pp": round(float(np.average(vals, weights=weights)), 3),
                "ci_lo": round(float(lo), 3),
                "ci_hi": round(float(hi), 3),
                "sig": "*" if (lo > 0 or hi < 0) else "ns",
            }
        )
    main_df = pd.DataFrame(main).sort_values("mean_pp", ascending=False)

    # --- 交互作用: 列 × 軸 ---
    daily = sub.groupby(["date", "section"])["resid_machine_rate"].mean().rename("v").reset_index()
    dates = pd.to_datetime(daily["date"], format="%Y%m%d")
    daily["weekday"] = dates.dt.weekday.map(dict(enumerate(WEEKDAY_JA)))
    daily["dd"] = dates.dt.day
    daily["event"] = np.where(daily["dd"].isin(EVENT_DDS), "イベント", "通常")

    date_index = daily["date"].unique()
    inter = []
    for axis in ("曜日", "DD", "イベント"):
        col = {"曜日": "weekday", "DD": "dd", "イベント": "event"}[axis]
        label_of = daily.drop_duplicates("date").set_index("date")[col]

        def interaction_var(mapping: pd.Series) -> float:
            """列×水準セル平均から、列主効果と水準主効果を引いた残りのばらつき。"""
            tmp = daily.assign(lab=daily["date"].map(mapping))
            cell = tmp.groupby(["section", "lab"])["v"].mean().unstack()
            cell = cell.sub(cell.mean(axis=1), axis=0).sub(cell.mean(axis=0), axis=1)
            return float(np.nanvar(cell.to_numpy()))

        observed = interaction_var(label_of)
        null = np.empty(N_PERM // 4)  # セル計算が重いので回数を落とす
        values = label_of.to_numpy()
        for i in range(len(null)):
            null[i] = interaction_var(pd.Series(rng.permutation(values), index=date_index))
        p = float((null >= observed).mean())
        inter.append(
            {
                "axis": axis,
                "observed_interaction_var": round(observed, 4),
                "null_median": round(float(np.median(null)), 4),
                "p_value": round(p, 4),
                "sig": "*" if p < 0.05 else "ns",
            }
        )
    return main_df, pd.DataFrame(inter)


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(SEED)

    df = prepare(add_within_model_residual(load_frame(), ["machine_rate", "bbrb"]))
    print(f"対象 {len(df):,} 行 / イベントDD={sorted(EVENT_DDS)}\n")

    prof = depth_profile_ci(df, rng)
    prof.to_csv(OUT_DIR / "depth_profile_ci.csv", index=False, encoding="utf-8-sig")
    print("=== (A) depth 1..7 の全プロファイル（clean・9台以上の列） ===")
    print(prof.to_string(index=False))

    axis = edge_by_axis(df, rng)
    axis.to_csv(OUT_DIR / "edge_by_axis.csv", index=False, encoding="utf-8-sig")
    print("\n=== (B)(C) 端番効果の DD・曜日変動 ===")
    print(axis.to_string(index=False))

    sec_main, sec_inter = section_by_axis(df, rng)
    sec_main.to_csv(OUT_DIR / "section_main_effect.csv", index=False, encoding="utf-8-sig")
    sec_inter.to_csv(OUT_DIR / "section_axis_interaction.csv", index=False, encoding="utf-8-sig")
    print("\n=== (D-1) セクション主効果（上位8・下位8） ===")
    print(pd.concat([sec_main.head(8), sec_main.tail(8)]).to_string(index=False))
    print("\n=== (D-2) セクション × 軸 の交互作用 omnibus ===")
    print(sec_inter.to_string(index=False))

    print(f"\n出力先: {OUT_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
