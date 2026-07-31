"""A日 DD{30,22,11} に技術介入・AT一般の高設定がどの属性へ入るかを走査する。

背景（rakuen_theory.md §3.1a）:
    楽園の予算の本体はジャグではない。DD30 は技術介入 +2.50pp・AT一般 +2.41pp で
    ともにカテゴリ内1位、DD22/DD11 がそれに続く（機種内機械割残差）。
    台数も技術介入238・AT一般467 とジャグ117を大きく上回り、配置も館内に広がる。
    ジャグは工事前エポックでは82台が本館1Fの一角に固まっており、
    属性分解の余地が構造的に乏しかった（`eda/rakuen_jugday_attribute_scan.py`）。

    「イベント日は差枚が大きい」で止まらず **A日にどのセグメント・属性へ入るか** を出す。

指標設計:
    主指標は **同日内残差の差分** lift_A = mean(resid | A日) - mean(resid | 平常日)。

      resid_d  = 機械割 - その日の同カテゴリ全台平均（**同日内残差**）
      resid_dm = 機械割 - その日の同機種平均（同日×同機種残差）

    同日内比較なので日レベルの交絡（客入り・天候・地域需要・ホール全体の出方）が落ちる。
    さらに **差分を取ることで機種構成のような時間不変の交絡が相殺される** ため、
    「島＝単一機種」でも section 効果が構造的にゼロにならない（ジャグで問題になった点）。
    resid_dm は機種構成を完全に落とすが、機種と完全共線な属性はゼロに潰れる。
    両方出して読み比べる。

    **技術介入は BB+RB(回/1000G) も併記する。** §2.1b のとおり打ち手の技量は小役取得を
    変えるがボーナス確率は変えないので、機械割と BB+RB が同方向なら設定投入、
    機械割だけなら技量・稼働の可能性がある。AT一般の bb_count/rb_count は
    AT機では意味を持たないため計算しない。

    min_games による足切りはしない（games は設定の下流。CLAUDE.md / §6.1追記）。
    BB/RB は bb_count/rb_count から直接計算（rb_probability_decimal は rb_count==0 で
    NULL になり RB0回の日を非ランダムに落とす。追試9）。

属性:
    フロア / section（63列）/ section分類（clean・frame・interior_split・special）/
    端番 depth / is_edge / 台番号末尾 / 末尾ゾロ目 / セクション規模 / 機種 / 個別台

期間は工事前エポック 20250101〜20260705。位置は必ず `machine_layout_history` を
日付条件付きで結合する（単純な `machine_layout` 結合は現行エポックの位置を
過去データに誤って当てる。§2.2b）。

使い方:
    venv\\Scripts\\python.exe -m eda.rakuen_aday_at_attribute_scan
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from eda.rakuen_section_classification import PRE_EPOCH, classify  # noqa: E402

DB_PATH = PROJECT_ROOT / "db" / "楽園蒲田店.db"
HEATMAP_DIR = PROJECT_ROOT / "Heatmap"
OUT_DIR = Path(__file__).parent / "results" / "rakuen_aday_at_attribute_scan"
HALL_NAME = "楽園蒲田店"

DATE_START = "20250101"
DATE_END = "20260705"

A_DDS = {11, 22, 30}  # 公示型イベント日（技術介入・AT一般が最も動く）
B_DDS = {5, 15, 25}  # ジャグ限定日（対照として併記）

TARGET_CATEGORIES = ("技術介入", "AT一般")

N_BOOT = 1500
SEED = 20260729


def load_floor_map() -> pd.Series:
    """台番号→フロア名。`machine_layout_history` に floor 列がないため座標CSVから取る。"""
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
               l.section, l.rank_from_min, l.rank_from_max,
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
    # 優先度つきの排他カテゴリ。ジャグ・ハナハナは bt_flag と重なりうるので先に取る
    df["category"] = np.select(
        [df["jug_flag"] == 1, df["hana_flag"] == 1, df["bt_flag"] == 1],
        ["ジャグ", "ハナハナ", "技術介入"],
        default="AT一般",
    )
    df = df.loc[df["category"].isin(TARGET_CATEGORIES)].reset_index(drop=True)

    df["rate"] = 100 + df["diff_coins"] / (3 * df["games"]) * 100
    df["bbrb"] = (df["bb_count"].fillna(0) + df["rb_count"].fillna(0)) / df["games"] * 1000

    dt = pd.to_datetime(df["date"], format="%Y%m%d")
    df["dd"] = dt.dt.day
    df["day_type"] = np.select([df["dd"].isin(A_DDS), df["dd"].isin(B_DDS)], ["A", "B"], default="normal")

    # --- 残差 -----------------------------------------------------------------
    # 同日内（カテゴリ内）残差: 日レベルの交絡が落ちる。機種構成は lift の差分で相殺
    df["resid_d"] = df["rate"] - df.groupby(["date", "category"])["rate"].transform("mean")
    df["bbrb_d"] = df["bbrb"] - df.groupby(["date", "category"])["bbrb"].transform("mean")
    # 同日×同機種残差: 機種構成を完全に落とす。機種と共線な属性はゼロに潰れる
    g = df.groupby(["date", "machine_name"])
    df["_n_dm"] = g["machine_number"].transform("size")
    df["resid_dm"] = df["rate"] - g["rate"].transform("mean")
    df.loc[df["_n_dm"] < 2, "resid_dm"] = np.nan

    # --- 属性 -----------------------------------------------------------------
    df["floor"] = df["machine_number"].map(load_floor_map())
    df["sec_group"] = df["section"].map(lambda s: classify(s, PRE_EPOCH))
    df["section_size"] = df.groupby("section")["machine_number"].transform("nunique")
    df["depth"] = df[["rank_from_min", "rank_from_max"]].min(axis=1)
    df["is_edge"] = np.where(df["depth"] == 1, "端(depth=1)", "非端")
    df["depth_bin"] = pd.cut(
        df["depth"],
        [0, 1, 2, 3, 5, 8, 99],
        labels=["1(端)", "2", "3", "4-5", "6-8", "9+"],
    ).astype(str)
    df["last_digit"] = (df["machine_number"] % 10).astype(str)
    two = df["machine_number"] % 100
    df["tail_zorome"] = np.where(two // 10 == two % 10, "末尾ゾロ目", "非ゾロ目")
    df["size_bin"] = pd.cut(
        df["section_size"],
        [0, 5, 8, 12, 99],
        labels=["mini(<=5)", "small(6-8)", "medium(9-12)", "large(13+)"],
    ).astype(str)
    return df


def cluster_boot_diff(
    sub_a: pd.DataFrame, sub_n: pd.DataFrame, col: str, rng: np.random.Generator
) -> tuple[float, float]:
    """lift = mean(col|A日) - mean(col|平常日) の95%CI。台単位で再標本化する。

    同じ台の連日の観測は独立でない。行単位のCIは幅が数分の一になり、
    実際には効いていない差を有意に見せてしまう。
    """
    ga = {m: v.dropna().to_numpy() for m, v in sub_a.groupby("machine_number")[col]}
    gn = {m: v.dropna().to_numpy() for m, v in sub_n.groupby("machine_number")[col]}
    ga = {m: v for m, v in ga.items() if len(v)}
    gn = {m: v for m, v in gn.items() if len(v)}
    machines = np.array(sorted(set(ga) | set(gn)))
    if len(machines) < 2:
        return (np.nan, np.nan)
    stats = np.full(N_BOOT, np.nan)
    for i in range(N_BOOT):
        pick = rng.choice(machines, len(machines), replace=True)
        a = [ga[m] for m in pick if m in ga]
        n = [gn[m] for m in pick if m in gn]
        if not a or not n:
            continue
        stats[i] = np.concatenate(a).mean() - np.concatenate(n).mean()
    return float(np.nanpercentile(stats, 2.5)), float(np.nanpercentile(stats, 97.5))


def scan(df: pd.DataFrame, attrs: list[str], rng: np.random.Generator) -> pd.DataFrame:
    rows = []
    for cat, cdf in df.groupby("category"):
        for attr in attrs:
            for level, sub in cdf.groupby(attr):
                a = sub[sub["day_type"] == "A"]
                b = sub[sub["day_type"] == "B"]
                nm = sub[sub["day_type"] == "normal"]
                if len(a) < 20 or len(nm) < 20:
                    continue
                lo, hi = cluster_boot_diff(a, nm, "resid_d", rng)
                rec = {
                    "category": cat,
                    "attribute": attr,
                    "level": str(level),
                    "n_machines": sub["machine_number"].nunique(),
                    "n_A": len(a),
                    "n_normal": len(nm),
                    "resid_normal": nm["resid_d"].mean(),
                    "resid_A": a["resid_d"].mean(),
                    "lift_A": a["resid_d"].mean() - nm["resid_d"].mean(),
                    "lift_A_lo": lo,
                    "lift_A_hi": hi,
                    "lift_A_dm": a["resid_dm"].mean() - nm["resid_dm"].mean(),
                    "lift_B": (b["resid_d"].mean() - nm["resid_d"].mean()) if len(b) else np.nan,
                    "sig": "*" if (lo > 0 or hi < 0) else "",
                }
                if cat == "技術介入":
                    rec["bbrb_lift_A"] = a["bbrb_d"].mean() - nm["bbrb_d"].mean()
                    blo, bhi = cluster_boot_diff(a, nm, "bbrb_d", rng)
                    rec["bbrb_sig"] = "*" if (blo > 0 or bhi < 0) else ""
                else:
                    rec["bbrb_lift_A"] = np.nan
                    rec["bbrb_sig"] = ""
                rows.append(rec)
    return pd.DataFrame(rows)


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(SEED)
    pd.set_option("display.width", 250)

    df = load()
    nd = df.groupby("day_type")["date"].nunique()
    print(
        f"{len(df):,}行 / {df['date'].nunique()}日  "
        f"（A日{nd.get('A', 0)} / B日{nd.get('B', 0)} / 平常{nd.get('normal', 0)}）"
    )
    print(
        df.groupby("category")
        .agg(台数=("machine_number", "nunique"), 行数=("date", "size"), 機種数=("machine_name", "nunique"))
        .to_string()
    )
    for cat, cdf in df.groupby("category"):
        m = cdf.groupby("day_type")["rate"].mean()
        gm = cdf.groupby("day_type")["games"].mean()
        print(
            f"  {cat}: 機械割 A={m.get('A', np.nan):.2f} B={m.get('B', np.nan):.2f} "
            f"平常={m.get('normal', np.nan):.2f} / 回転数 A={gm.get('A', np.nan):,.0f} "
            f"平常={gm.get('normal', np.nan):,.0f}"
        )

    attrs = [
        "floor",
        "sec_group",
        "size_bin",
        "is_edge",
        "depth_bin",
        "last_digit",
        "tail_zorome",
        "section",
        "machine_name",
    ]
    res = scan(df, attrs, rng)
    res.to_csv(OUT_DIR / "attribute_lift_at.csv", index=False, encoding="utf-8-sig")

    def fmt(v: float) -> str:
        return f"{v:,.3f}"

    cols = [
        "level",
        "n_machines",
        "n_A",
        "resid_normal",
        "lift_A",
        "lift_A_lo",
        "lift_A_hi",
        "lift_A_dm",
        "lift_B",
        "bbrb_lift_A",
        "sig",
        "bbrb_sig",
    ]

    for cat in TARGET_CATEGORIES:
        print(f"\n{'=' * 28} {cat} {'=' * 28}")
        for attr in attrs:
            sub = res[(res["category"] == cat) & (res["attribute"] == attr)]
            sub = sub.sort_values("lift_A", ascending=False)
            if sub.empty:
                continue
            print(f"\n--- {attr} （lift_A = A日 - 平常日、機械割pp） ---")
            show = sub if len(sub) <= 12 else pd.concat([sub.head(8), sub.tail(4)])
            print(show[cols].to_string(index=False, float_format=fmt))
            if len(sub) > 12:
                print(f"  …全{len(sub)}水準（上位8・下位4のみ）")

    # 個別台
    rows = []
    for (cat, m), sub in df.groupby(["category", "machine_number"]):
        a = sub[sub["day_type"] == "A"]
        nm = sub[sub["day_type"] == "normal"]
        if len(a) < 15 or len(nm) < 60:
            continue
        rows.append(
            {
                "category": cat,
                "machine_number": m,
                "machine_name": sub["machine_name"].mode().iat[0],
                "section": sub["section"].mode().iat[0],
                "floor": sub["floor"].mode().iat[0],
                "depth": int(sub["depth"].median()),
                "last_digit": m % 10,
                "n_A": len(a),
                "resid_A": a["resid_d"].mean(),
                "resid_normal": nm["resid_d"].mean(),
                "lift_A": a["resid_d"].mean() - nm["resid_d"].mean(),
            }
        )
    mt = pd.DataFrame(rows).sort_values("lift_A", ascending=False)
    mt.to_csv(OUT_DIR / "top_machines_Aday.csv", index=False, encoding="utf-8-sig")
    for cat in TARGET_CATEGORIES:
        s = mt[mt["category"] == cat]
        print(f"\n=== 個別台 {cat}: lift_A 上位12 / 下位4 ===")
        print(pd.concat([s.head(12), s.tail(4)]).to_string(index=False, float_format=fmt))

    print(f"\n出力: {OUT_DIR}")


if __name__ == "__main__":
    main()
