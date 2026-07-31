"""「A日{11,22,30}に技術介入の高設定が本館3Fへ寄る」発見の耐久性検証。

検証対象（rakuen_theory.md §3.1b）:
    `eda/rakuen_aday_at_attribute_scan.py` で、A日（公示型イベント日 DD{11,22,30}）に
    技術介入カテゴリの機械割が本館3Fの複数セクションで有意に上がることが判明した
    （3186-3199 +6.56、3226-3237 +3.12、3213-3225 +2.26、3174-3179 +2.78。
    うち複数は BB+RB でも有意）。効果量が §3.1c の末尾仮説より5〜20倍大きく、
    複数の島で独立に有意なため、運用に上げる前に耐久性を潰しておく。

    なお §3.1c の層別検定でも「技術介入×本館3F」だけ BB+RB が置換検定を通過した
    （p=0.041）。別仮説・別検定で同じ場所が反応している点も追試の動機。

検証項目:
    (1) 全期間の基準値（3F vs 2F の対比つき）
    (2) split-half（前半/後半）— 効果が期間の片側だけに依存していないか
    (3) 四半期（3ヶ月区切り）— 符号の一貫性。§2.1c と同じ流儀
    (4) A日の内訳（DD11 / DD22 / DD30 個別）— 3日すべてで出るのか1日の寄与か
    (5) leave-one-section-out — 特定の島1つが牽引していないか
    (6) leave-one-machine-out（最悪値）— 特定の台1台が牽引していないか

指標:
    resid_d = 機械割 - その日の技術介入カテゴリ全台平均（同日内残差）。
    日レベルの交絡（客入り・天候・イベント日の全体的な強さ）が完全に落ちる。
    lift = mean(resid_d | 本館3F, A日) - mean(resid_d | 本館3F, 平常日)。
    「3Fがいつも強い」ではなく「A日に限って強くなる」だけを見る差分形式なので、
    時間不変の交絡（機種構成・立地）は相殺される。

    BB+RB(回/1000G) の同日内残差を必ず併記する。打ち手の技量は小役取得を変えるが
    ボーナス確率は変えないため、機械割と BB+RB が同方向なら設定投入、機械割だけなら
    技量・稼働の可能性がある（§2.1b）。

    min_games による足切りはしない（games は設定の下流。CLAUDE.md）。
    CI は台単位のクラスタブートストラップ（同じ台の連日観測は独立でない）。

判定基準（§9 の流儀を踏襲）:
    同方向を維持し効果量が全期間値の60%以上なら「生存」、25-60%で「弱化」、
    それ未満または符号反転なら「消滅」。

期間は工事前エポック 20250101〜20260705。位置は `machine_layout_history` を
日付条件付きで結合する（§2.2b）。

使い方:
    venv\\Scripts\\python.exe -m eda.rakuen_aday_tech3f_durability
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DB_PATH = PROJECT_ROOT / "db" / "楽園蒲田店.db"
HEATMAP_DIR = PROJECT_ROOT / "Heatmap"
OUT_DIR = Path(__file__).parent / "results" / "rakuen_aday_tech3f_durability"
HALL_NAME = "楽園蒲田店"

DATE_START = "20250101"
DATE_END = "20260705"

A_DDS = {11, 22, 30}
TARGET_FLOOR = "本館3F"

N_BOOT = 2000
SEED = 20260729


def load_floor_map() -> pd.Series:
    frames = [
        pd.read_csv(p, usecols=["floor", "machine_number"])
        for p in sorted(HEATMAP_DIR.glob("*_floor_coordinates_rakuen.csv"))
    ]
    fm = pd.concat(frames, ignore_index=True).drop_duplicates("machine_number")
    return fm.set_index("machine_number")["floor"]


def load() -> pd.DataFrame:
    query = """
        SELECT r.date, r.machine_number, r.machine_name,
               r.games_normalized AS games,
               r.diff_coins_normalized AS diff_coins,
               r.bb_count, r.rb_count,
               l.section,
               m.jug_flag, m.hana_flag, m.bt_flag
        FROM machine_detailed_results r
        JOIN machine_layout_history l
          ON r.machine_number = l.machine_number
         AND r.date >= l.valid_from
         AND (l.valid_to IS NULL OR r.date <= l.valid_to)
        LEFT JOIN machine_master m
          ON r.machine_name = m.machine_name_normalized
        WHERE l.hall_name = ?
          AND r.date BETWEEN ? AND ?
          AND r.games_normalized > 0
    """
    with sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True) as con:
        df = pd.read_sql_query(query, con, params=(HALL_NAME, DATE_START, DATE_END))

    for col in ("jug_flag", "hana_flag", "bt_flag"):
        df[col] = df[col].fillna(0).astype(int)
    df["category"] = np.select(
        [df["jug_flag"] == 1, df["hana_flag"] == 1, df["bt_flag"] == 1],
        ["ジャグ", "ハナハナ", "技術介入"],
        default="AT一般",
    )
    df["rate"] = 100 + df["diff_coins"] / (3 * df["games"]) * 100
    df["bbrb"] = (df["bb_count"].fillna(0) + df["rb_count"].fillna(0)) / df["games"] * 1000
    # 同日内残差はカテゴリ全体（3F/2F両方）を基準にする。
    # 3F内だけで中心化すると「3Fが他より上がる」という主張自体が消えてしまう。
    df["resid_d"] = df["rate"] - df.groupby(["date", "category"])["rate"].transform("mean")
    df["bbrb_d"] = df["bbrb"] - df.groupby(["date", "category"])["bbrb"].transform("mean")

    dt = pd.to_datetime(df["date"], format="%Y%m%d")
    df["dd"] = dt.dt.day
    df["quarter"] = dt.dt.to_period("Q").astype(str)
    df["is_A"] = df["dd"].isin(A_DDS)
    df["floor"] = df["machine_number"].map(load_floor_map())

    return df.loc[df["category"] == "技術介入"].reset_index(drop=True)


def cluster_boot_lift(sub: pd.DataFrame, col: str, rng: np.random.Generator) -> tuple[float, float, float]:
    """lift = mean(col|A日) - mean(col|平常日) と95%CI。台単位で再標本化。"""
    a = sub.loc[sub["is_A"]].groupby("machine_number")[col].apply(lambda s: s.dropna().to_numpy())
    n = sub.loc[~sub["is_A"]].groupby("machine_number")[col].apply(lambda s: s.dropna().to_numpy())
    a = a[a.apply(len) > 0]
    n = n[n.apply(len) > 0]
    machines = np.array(sorted(set(a.index) | set(n.index)))
    if len(machines) < 2 or len(a) == 0 or len(n) == 0:
        return (np.nan, np.nan, np.nan)
    point = np.concatenate(a.to_list()).mean() - np.concatenate(n.to_list()).mean()
    stats = np.full(N_BOOT, np.nan)
    for i in range(N_BOOT):
        pick = rng.choice(machines, len(machines), replace=True)
        av = [a[m] for m in pick if m in a.index]
        nv = [n[m] for m in pick if m in n.index]
        if not av or not nv:
            continue
        stats[i] = np.concatenate(av).mean() - np.concatenate(nv).mean()
    return (float(point), float(np.nanpercentile(stats, 2.5)), float(np.nanpercentile(stats, 97.5)))


def row_for(sub: pd.DataFrame, split_type: str, label: str, rng: np.random.Generator) -> dict:
    lift, lo, hi = cluster_boot_lift(sub, "resid_d", rng)
    blift, blo, bhi = cluster_boot_lift(sub, "bbrb_d", rng)
    return {
        "split_type": split_type,
        "label": label,
        "n_machines": sub["machine_number"].nunique(),
        "n_A": int(sub["is_A"].sum()),
        "n_normal": int((~sub["is_A"]).sum()),
        "lift": lift,
        "lift_lo": lo,
        "lift_hi": hi,
        "bbrb_lift": blift,
        "bbrb_lo": blo,
        "bbrb_hi": bhi,
        "sig": "*" if (lo > 0 or hi < 0) else "",
        "bbrb_sig": "*" if (blo > 0 or bhi < 0) else "",
    }


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(SEED)
    pd.set_option("display.width", 220)

    df = load()
    f3 = df[df["floor"] == TARGET_FLOOR]
    print(f"技術介入 {df['machine_number'].nunique()}台 / {len(df):,}行")
    print(
        f"うち{TARGET_FLOOR}: {f3['machine_number'].nunique()}台 / {len(f3):,}行 "
        f"/ セクション{f3['section'].nunique()}個"
    )

    rows = []
    # (1) 全期間、3F と 2F（対比）
    for fl in sorted(df["floor"].dropna().unique()):
        sub = df[df["floor"] == fl]
        if sub["machine_number"].nunique() < 5:
            continue
        rows.append(row_for(sub, "全期間(フロア別)", fl, rng))

    # (2) split-half
    dates = np.sort(f3["date"].unique())
    mid = dates[len(dates) // 2]
    rows.append(row_for(f3[f3["date"] < mid], "split-half", f"前半(〜{mid})", rng))
    rows.append(row_for(f3[f3["date"] >= mid], "split-half", f"後半({mid}〜)", rng))

    # (3) 四半期
    for q, sub in f3.groupby("quarter"):
        if sub["is_A"].sum() < 20:
            continue
        rows.append(row_for(sub, "四半期", q, rng))

    # (4) A日の内訳
    for dd_val in sorted(A_DDS):
        sub = f3[(f3["dd"] == dd_val) | (~f3["is_A"])].copy()
        sub["is_A"] = sub["dd"] == dd_val
        rows.append(row_for(sub, "A日内訳", f"DD{dd_val}", rng))

    res = pd.DataFrame(rows)
    res.to_csv(OUT_DIR / "period_splits.csv", index=False, encoding="utf-8-sig")

    def fmt(v: float) -> str:
        return f"{v:,.3f}"

    print("\n=== 耐久性検証（lift = A日 - 平常日、同日内残差） ===")
    print(
        res[
            [
                "split_type",
                "label",
                "n_machines",
                "n_A",
                "lift",
                "lift_lo",
                "lift_hi",
                "sig",
                "bbrb_lift",
                "bbrb_lo",
                "bbrb_hi",
                "bbrb_sig",
            ]
        ].to_string(index=False, float_format=fmt)
    )

    base = res.loc[(res["split_type"] == "全期間(フロア別)") & (res["label"] == TARGET_FLOOR), "lift"].iat[0]
    print(
        f"\n{TARGET_FLOOR} 全期間の基準値: {base:+.3f}pp"
        f"（生存判定=60%以上の{base * 0.6:+.3f}pp、弱化=25%の{base * 0.25:+.3f}pp）"
    )

    # (5)(6) leave-one-out
    loo = []
    for sec in sorted(f3["section"].dropna().unique()):
        sub = f3[f3["section"] != sec]
        lift, _, _ = cluster_boot_lift(sub, "resid_d", rng)
        blift, _, _ = cluster_boot_lift(sub, "bbrb_d", rng)
        loo.append({"excluded_kind": "section", "excluded": sec, "lift": lift, "bbrb_lift": blift})
    for m in sorted(f3["machine_number"].unique()):
        sub = f3[f3["machine_number"] != m]
        lift, _, _ = cluster_boot_lift(sub, "resid_d", rng)
        loo.append({"excluded_kind": "machine", "excluded": str(m), "lift": lift, "bbrb_lift": np.nan})
    loo_df = pd.DataFrame(loo)
    loo_df.to_csv(OUT_DIR / "leave_one_out.csv", index=False, encoding="utf-8-sig")

    sec_loo = loo_df[loo_df["excluded_kind"] == "section"].sort_values("lift")
    mac_loo = loo_df[loo_df["excluded_kind"] == "machine"].sort_values("lift")
    print("\n=== leave-one-section-out（除外して最も下がる順・上位6） ===")
    print(sec_loo.head(6).to_string(index=False, float_format=fmt))
    print(f"\n  最悪値 {sec_loo['lift'].min():+.3f}pp / 基準値の {sec_loo['lift'].min() / base:.0%}")
    print(
        f"=== leave-one-machine-out 最悪値: {mac_loo['lift'].min():+.3f}pp "
        f"(台{mac_loo['excluded'].iat[0]}を除外) / 基準値の "
        f"{mac_loo['lift'].min() / base:.0%}"
    )

    print(f"\n出力: {OUT_DIR}")


if __name__ == "__main__":
    main()
