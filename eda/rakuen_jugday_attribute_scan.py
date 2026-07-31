"""(B)群「ジャグ限定日」DD{5,15,25} の高設定がどの属性に集中しているかを走査する。

背景（rakuen_theory.md §3.1a）:
    楽園のイベント日は2型に分かれた。

      (A) 公示型 DD{11,22,30} — 全4カテゴリがプラス、回転数 +1,100〜1,900G。
          客が期待して集まる日。競合が多い
      (B) ジャグ限定日 DD{5,15,25} — ジャグだけ +1.5〜1.9pp、他3カテゴリはマイナス、
          回転数の増加が小さい。**客の期待が乗っていない日**

    「イベント日は差枚が大きい」で止まるのは他の客と同じ読みでしかない。
    知りたいのは **(B)日にどのセグメント・どの属性へ高設定が入るか**（ユーザー指示）。

指標:
    ジャグの BB/RB 二項尤度による設定事後分布 P(設定5-6)=p56。回転数が少ない日は
    尤度が平坦になり事前へ戻るだけなので **min_games 足切りは不要かつ有害**
    （games は設定の下流。CLAUDE.md / §6.1追記）。

    主指標は **同日内残差 wd = p56 - その日の全ジャグ平均**。
    「どこに入るか」は**その日のホール内での配分**の話なので、日を統制するのが正しい。
    これにより日レベルの交絡（客入り・天候・地域需要）が完全に落ちる。
    §3.1a で DD 軸そのものを測ったときは日を統制できなかったが、
    本節は日**内**の比較なので同日残差が使える。

    各属性水準について **lift_B = wd(B日) - wd(平常日)** を見る。
    「その区画がいつも強い」ではなく「**B日に限って強くなる**」ものだけを拾う設計。

属性:
    section（63列）/ section分類（clean・frame・interior_split・special）/ フロア /
    端番 depth（端=1）/ is_edge / 台番号末尾 / 末尾ゾロ目 / 機種 / section_size /
    台番号そのもの（個別台ランキング）

期間は工事前エポック 20250101〜20260705。工事後は22日しかなくDD別には足りない。
位置は必ず `machine_layout_history` を日付条件付きで結合する（単純な `machine_layout`
結合は現行エポックの位置を過去データに誤って当てる。§2.2b）。

使い方:
    venv\\Scripts\\python.exe -m eda.rakuen_jugday_attribute_scan
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
from ml.experiments.jug_rb_setting_prediction.config import (  # noqa: E402
    JUGGLER_FAMILY_MATCHERS,
    JUGGLER_FAMILY_SPECS,
)

DB_PATH = PROJECT_ROOT / "db" / "楽園蒲田店.db"
HEATMAP_DIR = PROJECT_ROOT / "Heatmap"
OUT_DIR = Path(__file__).parent / "results" / "rakuen_jugday_attribute_scan"
HALL_NAME = "楽園蒲田店"

DATE_START = "20250101"
DATE_END = "20260705"

B_DDS = {5, 15, 25}  # ジャグ限定日
A_DDS = {11, 22, 30}  # 公示型イベント日

N_BOOT = 2000
SEED = 20260729


def match_family(name: str) -> str | None:
    for key, kw in JUGGLER_FAMILY_MATCHERS:
        if kw in name:
            return key
    return None


def jug_posterior_p56(df: pd.DataFrame) -> pd.Series:
    """一様事前・BB/RB二項尤度で P(設定5-6)。組合せ項は設定間で相殺するので省略。"""
    out = np.full(len(df), np.nan)
    for fam, grp in df.groupby("family"):
        specs = JUGGLER_FAMILY_SPECS[fam]["settings"]
        n = grp["games"].to_numpy(dtype=float)
        bb = grp["bb_count"].to_numpy(dtype=float)
        rb = grp["rb_count"].to_numpy(dtype=float)
        logliks = []
        for s in range(1, 7):
            pb = specs[s]["bb_probability"]
            pr = specs[s]["rb_probability"]
            logliks.append(bb * np.log(pb) + (n - bb) * np.log1p(-pb) + rb * np.log(pr) + (n - rb) * np.log1p(-pr))
        ll = np.vstack(logliks)
        ll -= ll.max(axis=0, keepdims=True)
        post = np.exp(ll)
        post /= post.sum(axis=0, keepdims=True)
        out[df.index.get_indexer(grp.index)] = post[4] + post[5]
    return pd.Series(out, index=df.index, name="p56")


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
               r.games_normalized AS games, r.bb_count, r.rb_count,
               l.section, l.rank_from_min, l.rank_from_max
        FROM machine_detailed_results r
        JOIN machine_layout_history l
          ON r.machine_number = l.machine_number
         AND r.date >= l.valid_from
         AND (l.valid_to IS NULL OR r.date <= l.valid_to)
        WHERE l.hall_name = ?
          AND r.date BETWEEN ? AND ?
          AND r.games_normalized > 0
          AND r.bb_count IS NOT NULL AND r.rb_count IS NOT NULL
    """
    with sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True) as con:
        df = pd.read_sql_query(query, con, params=(HALL_NAME, DATE_START, DATE_END))

    df["family"] = df["machine_name"].map(match_family)
    df = df.loc[df["family"].notna()].reset_index(drop=True)
    # BB/RB は物理的に回転数を超えない。壊れた行は尤度を破壊する
    df = df.loc[
        (df["bb_count"] >= 0) & (df["rb_count"] >= 0) & (df["bb_count"] + df["rb_count"] < df["games"])
    ].reset_index(drop=True)

    df["p56"] = jug_posterior_p56(df)
    # 同日内残差 — 「その日のホール内でどこに配分されたか」。日レベル交絡が完全に落ちる
    df["wd"] = df["p56"] - df.groupby("date")["p56"].transform("mean")

    dt = pd.to_datetime(df["date"], format="%Y%m%d")
    df["dd"] = dt.dt.day
    df["day_type"] = np.select([df["dd"].isin(B_DDS), df["dd"].isin(A_DDS)], ["B", "A"], default="normal")

    # --- 属性 -----------------------------------------------------------------
    df["floor"] = df["machine_number"].map(load_floor_map())
    df["sec_group"] = df["section"].map(lambda s: classify(s, PRE_EPOCH))
    df["section_size"] = df.groupby("section")["machine_number"].transform("nunique")
    df["depth"] = df[["rank_from_min", "rank_from_max"]].min(axis=1)
    df["is_edge"] = np.where(df["depth"] == 1, "端(depth=1)", "非端")
    # depth は列の長さで上限が違うので、粗いビンも用意する
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


def cluster_boot_diff(sub_b: pd.DataFrame, sub_n: pd.DataFrame, rng: np.random.Generator) -> tuple[float, float]:
    """lift = mean(wd|B日) - mean(wd|平常日) の95%CI。台単位で再標本化する。

    同じ台の連日の観測は独立でない。行単位のCIは幅が数分の一になり、
    効いていない差を有意に見せてしまう。
    """
    gb = {m: g["wd"].to_numpy() for m, g in sub_b.groupby("machine_number")}
    gn = {m: g["wd"].to_numpy() for m, g in sub_n.groupby("machine_number")}
    machines = np.array(sorted(set(gb) | set(gn)))
    stats = np.full(N_BOOT, np.nan)
    for i in range(N_BOOT):
        pick = rng.choice(machines, len(machines), replace=True)
        bs = [gb[m] for m in pick if m in gb]
        ns = [gn[m] for m in pick if m in gn]
        if not bs or not ns:
            continue
        stats[i] = np.concatenate(bs).mean() - np.concatenate(ns).mean()
    return float(np.nanpercentile(stats, 2.5)), float(np.nanpercentile(stats, 97.5))


def scan(df: pd.DataFrame, attrs: list[str], rng: np.random.Generator) -> pd.DataFrame:
    rows = []
    for attr in attrs:
        for level, sub in df.groupby(attr):
            b = sub[sub["day_type"] == "B"]
            a = sub[sub["day_type"] == "A"]
            nm = sub[sub["day_type"] == "normal"]
            if len(b) < 10 or len(nm) < 10:
                continue
            lo, hi = cluster_boot_diff(b, nm, rng)
            rows.append(
                {
                    "attribute": attr,
                    "level": str(level),
                    "n_machines": sub["machine_number"].nunique(),
                    "n_B": len(b),
                    "n_A": len(a),
                    "n_normal": len(nm),
                    "p56_normal": nm["p56"].mean(),
                    "p56_A": a["p56"].mean() if len(a) else np.nan,
                    "p56_B": b["p56"].mean(),
                    "wd_normal": nm["wd"].mean(),
                    "wd_A": a["wd"].mean() if len(a) else np.nan,
                    "wd_B": b["wd"].mean(),
                    "lift_B": b["wd"].mean() - nm["wd"].mean(),
                    "lift_B_lo": lo,
                    "lift_B_hi": hi,
                    "lift_A": (a["wd"].mean() - nm["wd"].mean()) if len(a) else np.nan,
                    "sig": "*" if (lo > 0 or hi < 0) else "",
                }
            )
    return pd.DataFrame(rows)


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(SEED)
    pd.set_option("display.width", 240)

    df = load()
    nd = df.groupby("day_type")["date"].nunique()
    print(
        f"ジャグ {df['machine_number'].nunique()}台 / {len(df):,}行 / "
        f"{df['date'].nunique()}日  （B日{nd.get('B', 0)} / A日{nd.get('A', 0)} / "
        f"平常{nd.get('normal', 0)}）"
    )
    print(
        f"p56平均: B={df[df.day_type == 'B'].p56.mean():.4f} "
        f"A={df[df.day_type == 'A'].p56.mean():.4f} "
        f"平常={df[df.day_type == 'normal'].p56.mean():.4f}"
    )

    attrs = [
        "floor",
        "sec_group",
        "section",
        "is_edge",
        "depth_bin",
        "last_digit",
        "tail_zorome",
        "machine_name",
        "size_bin",
    ]
    res = scan(df, attrs, rng)
    res.to_csv(OUT_DIR / "attribute_lift.csv", index=False, encoding="utf-8-sig")

    def fmt(v: float) -> str:
        return f"{v:,.4f}"

    cols = [
        "level",
        "n_machines",
        "n_B",
        "n_normal",
        "wd_normal",
        "wd_B",
        "lift_B",
        "lift_B_lo",
        "lift_B_hi",
        "lift_A",
        "sig",
    ]

    for attr in attrs:
        sub = res[res["attribute"] == attr].sort_values("lift_B", ascending=False)
        if sub.empty:
            continue
        print(f"\n=== {attr} （lift_B 降順 / wd=同日内残差, lift_B = B日 - 平常日） ===")
        show = sub if len(sub) <= 12 else pd.concat([sub.head(8), sub.tail(4)])
        print(show[cols].to_string(index=False, float_format=fmt))
        if len(sub) > 12:
            print(f"  …全{len(sub)}水準（上位8・下位4のみ表示）")

    # 個別台ランキング
    rows = []
    for m, sub in df.groupby("machine_number"):
        b = sub[sub["day_type"] == "B"]
        nm = sub[sub["day_type"] == "normal"]
        if len(b) < 10 or len(nm) < 30:
            continue
        rows.append(
            {
                "machine_number": m,
                "machine_name": sub["machine_name"].mode().iat[0],
                "section": sub["section"].mode().iat[0],
                "floor": sub["floor"].mode().iat[0],
                "depth": int(sub["depth"].median()),
                "last_digit": m % 10,
                "n_B": len(b),
                "wd_B": b["wd"].mean(),
                "wd_normal": nm["wd"].mean(),
                "lift_B": b["wd"].mean() - nm["wd"].mean(),
            }
        )
    mt = pd.DataFrame(rows).sort_values("lift_B", ascending=False)
    mt.to_csv(OUT_DIR / "top_machines_Bday.csv", index=False, encoding="utf-8-sig")
    print("\n=== 個別台 lift_B 上位15 / 下位5 ===")
    print(pd.concat([mt.head(15), mt.tail(5)]).to_string(index=False, float_format=fmt))

    print(f"\n出力: {OUT_DIR}")


if __name__ == "__main__":
    main()
