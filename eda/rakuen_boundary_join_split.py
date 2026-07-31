"""楽園蒲田店: 列の境界を「つなげるべきか / 分けるべきか」をデータで決める。

解決したい問題:
    frame（外周22列）と interior_split（U字島等6列）は、柱や通路で物理的に
    分断されている。しかしホールが**その分断を設定投入の単位として扱って
    いるか**は不明で、これまで分析から除外してきた。

    先に試した「柱に隣接する台が優遇されているか」という端番位置ベースの
    判定は、split-half で前半 ns / 後半 * と不安定で決着しなかった
    （`eda/results/rakuen_clean_edge/robustness.csv`）。

ここでの設計 — 端番位置ではなく**連動性**で判定する:
    2つの列が同じ投入単位なら、高設定を入れる日・入れない日が揃うので
    日次残差が連動する。別単位なら独立に近い。
    そこで日次残差系列の相関を測り、次の2つの校正基準と比べる。

      上限（確実に同一単位）  1本の列を前半/後半に割ったペアの相関。
                              同じ列なので定義上「同じ単位」。台数が半分に
                              なるぶんノイズも増えるので、境界ペアと
                              同程度の観測条件になる
      下限（確実に無関係）    物理的に離れた列どうしのペアの相関

    境界ペアの相関が上限寄りなら **JOIN（つなげるべき）**、
    下限寄りなら **SPLIT（分けたままでよい）**。

    相関は水準差に影響されないので、列ごとの強弱や台数差があっても使える。

指標:
    機械割pp・差枚・G数・機械割104%超えの4つ。いずれも同日×同機種平均からの
    残差にしてからセクション単位に集約する（ホール全体のその日の出方と
    機種構成を落とす）。

    **G数は「設定の下流」なので統制変数にはできないが、アウトカムとしては
    有効**（高設定→長く回される）。ここでは統制ではなくアウトカムとして使う。

多重比較:
    セクション×軸×水準×指標のセルは数百になる。個別のp値をそのまま読むと
    偽陽性が量産されるので Benjamini-Hochberg で q 値に直し、q<0.10 の
    セルだけを「周囲より有意」として報告する。

使い方:
    venv\\Scripts\\python.exe -m eda.rakuen_boundary_join_split
"""

from __future__ import annotations

import math
import sys
from itertools import combinations
from pathlib import Path

import numpy as np
import pandas as pd

from eda.rakuen_clean_section_edge_effect import load_frame
from eda.rakuen_section_classification import PRE_EPOCH, classify

OUT_DIR = Path(__file__).parent / "results" / "rakuen_boundary"

MIN_OVERLAP_DAYS = 120
EVENT_DDS = {10, 11, 22, 30}
WEEKDAY_JA = ["月", "火", "水", "木", "金", "土", "日"]

METRICS = [
    ("resid_machine_rate", "機械割pp"),
    ("resid_diff_coins", "差枚"),
    ("resid_games", "G数"),
    ("resid_hit104", "104%超え率"),
]

# 連動性の判定は leave-out ベースラインで残差を作り直すため、生の列名を使う。
RAW_METRICS = [
    ("machine_rate", "機械割pp"),
    ("diff_coins", "差枚"),
    ("games", "G数"),
    ("hit104", "104%超え率"),
]


def add_residuals(df: pd.DataFrame) -> pd.DataFrame:
    """同日×同機種平均からの残差。対照の取れない群（1台のみ）は除外。"""
    df = df.assign(hit104=(df["machine_rate"] >= 104).astype(float))
    grp = df.groupby(["date", "machine_name"])
    df = df.assign(_n=grp["machine_number"].transform("size"))
    for col in ("machine_rate", "diff_coins", "games", "hit104"):
        df[f"resid_{col}"] = df[col] - grp[col].transform("mean")
    return df.loc[df["_n"] >= 2].drop(columns="_n")


def section_geometry(df: pd.DataFrame) -> dict[str, np.ndarray]:
    """セクションごとの台座標。物理的な近さの判定に使う。"""
    return {section: g[["x", "y"]].drop_duplicates().to_numpy() for section, g in df.groupby("section")}


def min_distance(a: np.ndarray, b: np.ndarray) -> float:
    """2セクション間で最も近い台どうしのチェビシェフ距離。"""
    diff = np.abs(a[:, None, :] - b[None, :, :])
    return float(diff.max(axis=2).min())


def model_day_totals(df: pd.DataFrame, raw_col: str) -> pd.DataFrame:
    """同日×同機種の合計と台数。leave-out ベースラインの材料。"""
    return df.groupby(["date", "machine_name"])[raw_col].agg(total_sum="sum", total_n="count")


def leave_out_series(df: pd.DataFrame, totals: pd.DataFrame, arms: dict[str, list[str]], raw_col: str) -> pd.DataFrame:
    """比較する2群を**両方ともベースラインから除いた**上での日次残差系列。

    ここが本スクリプトの要。単純な同日×同機種残差を使うと、同じ機種が
    比較対象の2列に分かれて設置されている場合、残差のゼロ和制約によって
    片方が上がれば他方が必ず下がる。これは「連動していない」のではなく
    **測り方が作り出した機械的な逆相関**で、相関 -0.99 のような値になる。

    そこで各群の残差を「その日・その機種を打っていた台のうち、**比較対象の
    どちらの群にも属さない台**の平均」との差として定義する。参照が共通かつ
    比較群と重ならないので、ゼロ和による人工的な相関が入らない。

    その機種がその2群にしか設置されていない日は参照が作れないので落とす
    （その機種はこのペアの判定に寄与できない）。
    """
    focus = [s for sections in arms.values() for s in sections]
    fdf = df.loc[df["section"].isin(focus)]
    if fdf.empty:
        return pd.DataFrame()

    focus_agg = fdf.groupby(["date", "machine_name"])[raw_col].agg(f_sum="sum", f_n="count")
    base = totals.join(focus_agg, how="left")
    base[["f_sum", "f_n"]] = base[["f_sum", "f_n"]].fillna(0)
    n_out = base["total_n"] - base["f_n"]
    base["mean_out"] = np.where(n_out > 0, (base["total_sum"] - base["f_sum"]) / n_out.replace(0, np.nan), np.nan)

    out = {}
    for arm, sections in arms.items():
        a = fdf.loc[fdf["section"].isin(sections)]
        g = a.groupby(["date", "machine_name"])[raw_col].agg(a_sum="sum", a_n="count")
        g = g.join(base["mean_out"]).dropna(subset=["mean_out"])
        if g.empty:
            continue
        g["resid_sum"] = g["a_sum"] - g["a_n"] * g["mean_out"]
        totals_by_date = g.groupby("date")[["resid_sum", "a_n"]].sum()
        out[arm] = totals_by_date["resid_sum"] / totals_by_date["a_n"]
    return pd.DataFrame(out)


def half_arms(df: pd.DataFrame, section: str) -> dict[str, list[str]]:
    """1本の列を台番号の前半/後半に割る。「確実に同一単位」の校正用。

    返すのは section 名ではなく擬似セクション名なので、呼び出し側で
    `section` 列を差し替えた DataFrame を渡す必要がある。
    """
    machines = sorted(df.loc[df["section"] == section, "machine_number"].unique())
    mid = len(machines) // 2
    return {"A": machines[:mid], "B": machines[mid:]}


def corr_of(series: pd.DataFrame, a: str, b: str) -> tuple[float, int]:
    if series.empty or a not in series.columns or b not in series.columns:
        return float("nan"), 0
    joined = series[[a, b]].dropna()
    if len(joined) < MIN_OVERLAP_DAYS:
        return float("nan"), int(len(joined))
    if joined[a].std() < 1e-9 or joined[b].std() < 1e-9:
        return float("nan"), int(len(joined))
    return float(joined[a].corr(joined[b])), int(len(joined))


def bh_qvalues(pvals: np.ndarray) -> np.ndarray:
    """Benjamini-Hochberg の q 値。"""
    n = len(pvals)
    order = np.argsort(pvals)
    ranked = pvals[order] * n / (np.arange(n) + 1)
    ranked = np.minimum.accumulate(ranked[::-1])[::-1]
    out = np.empty(n)
    out[order] = np.clip(ranked, 0, 1)
    return out


def build_pairs(df: pd.DataFrame) -> pd.DataFrame:
    """判定対象の境界ペアと、校正用の遠隔ペアを作る。"""
    geom = section_geometry(df)
    group_of = {s: classify(s, PRE_EPOCH) for s in geom}
    sections = sorted(geom, key=lambda s: int(s.split("-")[0]))

    rows = []
    for a, b in combinations(sections, 2):
        # フロアが違えば座標系が別なので比較しない（台番号の千の位で判定）
        if a[0] != b[0]:
            continue
        dist = min_distance(geom[a], geom[b])
        contiguous = int(b.split("-")[0]) == int(a.split("-")[1]) + 1
        if dist <= 3 and contiguous:
            kind = "境界ペア"
        elif dist >= 8:
            kind = "遠隔ペア(校正:下限)"
        else:
            continue
        rows.append(
            {
                "a": a,
                "b": b,
                "kind": kind,
                "min_dist": dist,
                "group_a": group_of[a],
                "group_b": group_of[b],
            }
        )
    return pd.DataFrame(rows)


def analyze_boundaries(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    pairs = build_pairs(df)
    totals = {raw: model_day_totals(df, raw) for raw, _ in RAW_METRICS}

    # --- 校正: 同一列を前半/後半に割ったペア（上限） ---
    # 擬似セクション列を作り、その列全体をベースラインから除いて比較する。
    calib_rows = []
    for section in sorted(df["section"].unique()):
        halves = half_arms(df, section)
        if min(len(v) for v in halves.values()) < 2:
            continue
        tagged = df.assign(
            section=np.where(
                df["machine_number"].isin(halves["A"]) & (df["section"] == section),
                f"{section}#A",
                np.where(
                    df["machine_number"].isin(halves["B"]) & (df["section"] == section),
                    f"{section}#B",
                    df["section"],
                ),
            )
        )
        arms = {"A": [f"{section}#A"], "B": [f"{section}#B"]}
        for raw, label in RAW_METRICS:
            series = leave_out_series(tagged, totals[raw], arms, raw)
            c, n = corr_of(series, "A", "B")
            if not np.isnan(c):
                calib_rows.append(
                    {
                        "metric": label,
                        "kind": "同一列の前半/後半(校正:上限)",
                        "pair": section,
                        "corr": round(c, 4),
                        "n_days": n,
                        "group": classify(section, PRE_EPOCH),
                    }
                )
    calib = pd.DataFrame(calib_rows)

    # --- 境界ペア・遠隔ペア ---
    rows = []
    for _, r in pairs.iterrows():
        rec = {
            "pair": f"{r['a']} | {r['b']}",
            "kind": r["kind"],
            "min_dist": r["min_dist"],
            "group": f"{r['group_a']}/{r['group_b']}",
        }
        arms = {"A": [r["a"]], "B": [r["b"]]}
        ok = False
        for raw, label in RAW_METRICS:
            series = leave_out_series(df, totals[raw], arms, raw)
            c, n = corr_of(series, "A", "B")
            rec[f"corr_{label}"] = round(c, 4) if not np.isnan(c) else np.nan
            rec["n_days"] = n
            ok = ok or not np.isnan(c)
        if ok:
            rows.append(rec)
    pair_df = pd.DataFrame(rows)

    # --- 判定: 機械割ppの相関が、下限と上限の間のどこにいるか ---
    upper = float(calib.loc[calib["metric"] == "機械割pp", "corr"].median())
    lower = float(pair_df.loc[pair_df["kind"] == "遠隔ペア(校正:下限)", "corr_機械割pp"].median())
    span = upper - lower

    def verdict(c: float) -> str:
        if np.isnan(c) or span <= 0:
            return "判定不能"
        pos = (c - lower) / span
        if pos >= 0.6:
            return "JOIN寄り"
        if pos <= 0.3:
            return "SPLIT寄り"
        return "中間"

    pair_df["join_score"] = ((pair_df["corr_機械割pp"] - lower) / span).round(3)
    pair_df["verdict"] = pair_df["corr_機械割pp"].map(verdict)
    return pair_df, calib


def analyze_piece_dd_weekday(df: pd.DataFrame) -> pd.DataFrame:
    """(周囲より有意か) セクション×軸×水準×指標。BH で q 値に直す。

    残差は既に同日×同機種平均を引いているので、各セルは「その日ホール内で
    同じ機種を打っていた台の平均に対する超過」を意味する。つまり
    「周囲の環境より」の比較になっている。
    """
    dates = pd.to_datetime(df["date"], format="%Y%m%d")
    sub = df.assign(
        weekday=dates.dt.weekday.map(dict(enumerate(WEEKDAY_JA))),
        dd=dates.dt.day,
    )
    sub["event"] = np.where(sub["dd"].isin(EVENT_DDS), "イベントDD", "通常DD")

    records = []
    for axis, col in (("曜日", "weekday"), ("イベント", "event")):
        for (section, level), g in sub.groupby(["section", col]):
            for metric, label in METRICS:
                # 日次に潰す。同一台の連日は独立でないため行単位では見ない。
                daily = g.groupby("date")[metric].mean().dropna()
                if len(daily) < 20:
                    continue
                mean = float(daily.mean())
                sd = float(daily.std(ddof=1))
                # その機種がこの列にしか無い場合、残差は恒等的に0になる。
                # 浮動小数の誤差で sd が 1e-17 程度の非ゼロになると t が発散し、
                # 中身の無いセルが p=0 で有意判定されてしまう。相対許容差で弾く。
                scale = max(abs(mean), float(daily.abs().max()), 1e-12)
                if sd < 1e-9 * max(scale, 1.0):
                    continue
                se = sd / math.sqrt(len(daily))
                t = mean / se
                p = float(math.erfc(abs(t) / math.sqrt(2)))  # 正規近似の両側p値
                records.append(
                    {
                        "section": section,
                        "group": classify(section, PRE_EPOCH),
                        "axis": axis,
                        "level": level,
                        "metric": label,
                        "effect": round(mean, 4),
                        "n_days": int(len(daily)),
                        "p_value": p,
                    }
                )
    out = pd.DataFrame(records)
    if not out.empty:
        out["q_value_bh"] = bh_qvalues(out["p_value"].to_numpy()).round(4)
        out["p_value"] = out["p_value"].round(5)
    return out


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    df = add_residuals(load_frame())
    df = df.loc[df["section"].map(lambda s: classify(s, PRE_EPOCH)) != "special"]
    print(f"対象 {len(df):,} 行 / {df['section'].nunique()} セクション\n")

    pair_df, calib = analyze_boundaries(df)
    pair_df.to_csv(OUT_DIR / "boundary_comovement.csv", index=False, encoding="utf-8-sig")
    calib.to_csv(OUT_DIR / "calibration.csv", index=False, encoding="utf-8-sig")

    print("=== 校正基準（機械割ppの日次残差相関） ===")
    up = calib.loc[calib["metric"] == "機械割pp", "corr"]
    lo = pair_df.loc[pair_df["kind"] == "遠隔ペア(校正:下限)", "corr_機械割pp"]
    print(
        f"  上限 同一列を前半/後半に分割: 中央値 {up.median():.4f} "
        f"(25-75%: {up.quantile(0.25):.4f}〜{up.quantile(0.75):.4f}, n={len(up)})"
    )
    print(
        f"  下限 物理的に離れた列どうし  : 中央値 {lo.median():.4f} "
        f"(25-75%: {lo.quantile(0.25):.4f}〜{lo.quantile(0.75):.4f}, n={len(lo)})"
    )

    print("\n=== 境界ペアの連動性と判定 ===")
    b = pair_df.loc[pair_df["kind"] == "境界ペア"].sort_values("join_score", ascending=False)
    cols = [
        "pair",
        "group",
        "min_dist",
        "corr_機械割pp",
        "corr_差枚",
        "corr_G数",
        "corr_104%超え率",
        "n_days",
        "join_score",
        "verdict",
    ]
    print(b[cols].to_string(index=False))

    dd = analyze_piece_dd_weekday(df)
    dd.to_csv(OUT_DIR / "piece_dd_weekday.csv", index=False, encoding="utf-8-sig")
    print("\n=== 周囲より有意なセル（BH q<0.10）===")
    sig = dd.loc[dd["q_value_bh"] < 0.10].sort_values("q_value_bh")
    if sig.empty:
        print("  なし（全セルが多重比較補正後に非有意）")
    else:
        print(sig.head(30).to_string(index=False))
    print(f"\n  検定セル総数 {len(dd)} / q<0.10 は {len(sig)} 件")

    print(f"\n出力先: {OUT_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
