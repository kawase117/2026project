"""「本館>新館という建物単位の粗い勾配（7.8pp差）」を機種内残差で測り直す。

背景（rakuen_theory.md §0-2, §1）:
    §0サマリーの1番目・§12台選びフローの第一歩に「まず本館か新館かを見る」が
    置かれているが、根拠は本館3F(49.8%)〜新館2F(42.0%)というhit率のみ
    （`diff_coins_normalized > 0`比率、games_normalized≥2000フィルタ付き）。
    追試13でhit率は「区画の機種構成のボラティリティ」を測っていただけと判明し
    （§1のHot/Cold自体は撤回済み）、この本館/新館勾配は一度も測り直されていない。

    さらに §1.1 で「本館1F_Nだけ極端に弱い」というSimpson's Paradoxが判明しており、
    本館3館・新館2館を単純に「本館」「新館」の二値に潰す比較自体が
    フロア構成比の違いを隠している疑いがある。

指標:
    同日×同機種残差（機種内残差）。日レベルの交絡（客入り・天候）と
    機種構成の違い（本館と新館で設置機種が異なる）を同時に落とす
    （`eda/rakuen_clean_section_edge_effect.py`と同じ設計）。
    技術介入カテゴリはBB+RB(回/1000G)も併記し、機械割との併読で
    「設定投入の署名」か「稼働・技量由来」かを判別する（§2.1b）。

    min_games による足切りはしない（games は設定の下流。CLAUDE.md）。
    CI は台単位のクラスタブートストラップ。

やること:
    (1) フロア別（5フロア）× カテゴリ別の機種内残差
    (2) 本館(3F合算) vs 新館(2F合算) の二値比較（元の主張の直接再検証）
    (3) 本館1Fを除いた「本館2F+3F」vs「新館」の比較（Simpson's Paradox除外版）

期間は工事前エポック 20250101〜20260705（座標CSVがこのエポックに対応するため）。

使い方:
    venv\\Scripts\\python.exe -m eda.rakuen_building_gradient_recheck
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DB_PATH = PROJECT_ROOT / "db" / "楽園蒲田店.db"
HEATMAP_DIR = PROJECT_ROOT / "Heatmap"
OUT_DIR = Path(__file__).parent / "results" / "rakuen_building_gradient_recheck"

DATE_START = "20250101"
DATE_END = "20260705"

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
               m.jug_flag, m.hana_flag, m.bt_flag
        FROM machine_detailed_results r
        LEFT JOIN machine_master m
          ON r.machine_name = m.machine_name_normalized
        WHERE r.date BETWEEN ? AND ?
          AND r.games_normalized > 0
    """
    with sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True) as con:
        df = pd.read_sql_query(query, con, params=(DATE_START, DATE_END))

    for col in ("jug_flag", "hana_flag", "bt_flag"):
        df[col] = df[col].fillna(0).astype(int)
    df["category"] = np.select(
        [df["jug_flag"] == 1, df["hana_flag"] == 1, df["bt_flag"] == 1],
        ["ジャグ", "ハナハナ", "技術介入"],
        default="AT一般",
    )
    df["rate"] = 100 + df["diff_coins"] / (3 * df["games"]) * 100
    df["bbrb"] = (df["bb_count"].fillna(0) + df["rb_count"].fillna(0)) / df["games"] * 1000

    # 機種内残差: 同日×同機種平均からの残差。1台しかない群(対照不可)は落とす
    g = df.groupby(["date", "machine_name"])
    df["_n_dm"] = g["machine_number"].transform("size")
    df["resid_dm"] = df["rate"] - g["rate"].transform("mean")
    df["bbrb_dm"] = df["bbrb"] - g["bbrb"].transform("mean")
    df.loc[df["_n_dm"] < 2, ["resid_dm", "bbrb_dm"]] = np.nan

    df["floor"] = df["machine_number"].map(load_floor_map())
    df["building"] = np.where(df["floor"].str.startswith("本館"), "本館", "新館")
    return df


def cluster_boot_mean(sub: pd.DataFrame, col: str, rng: np.random.Generator) -> tuple[float, float, float]:
    """機種内残差の平均と95%CI。台単位で再標本化。"""
    g = sub.dropna(subset=[col]).groupby("machine_number")[col].apply(lambda s: s.to_numpy())
    machines = np.array(sorted(g.index))
    if len(machines) < 2:
        return (np.nan, np.nan, np.nan)
    point = float(np.concatenate(g.to_list()).mean())
    stats = np.full(N_BOOT, np.nan)
    for i in range(N_BOOT):
        pick = rng.choice(machines, len(machines), replace=True)
        vals = [g[m] for m in pick if m in g.index]
        if vals:
            stats[i] = np.concatenate(vals).mean()
    return (point, float(np.nanpercentile(stats, 2.5)), float(np.nanpercentile(stats, 97.5)))


def cluster_boot_diff(
    sub_a: pd.DataFrame, sub_b: pd.DataFrame, col: str, rng: np.random.Generator
) -> tuple[float, float, float]:
    """群Aと群Bの平均差(A-B)と95%CI。台単位で再標本化。"""
    ga = sub_a.dropna(subset=[col]).groupby("machine_number")[col].apply(lambda s: s.to_numpy())
    gb = sub_b.dropna(subset=[col]).groupby("machine_number")[col].apply(lambda s: s.to_numpy())
    ma, mb = np.array(sorted(ga.index)), np.array(sorted(gb.index))
    if len(ma) < 2 or len(mb) < 2:
        return (np.nan, np.nan, np.nan)
    point = float(np.concatenate(ga.to_list()).mean() - np.concatenate(gb.to_list()).mean())
    stats = np.full(N_BOOT, np.nan)
    for i in range(N_BOOT):
        pa = rng.choice(ma, len(ma), replace=True)
        pb = rng.choice(mb, len(mb), replace=True)
        va = [ga[m] for m in pa if m in ga.index]
        vb = [gb[m] for m in pb if m in gb.index]
        if va and vb:
            stats[i] = np.concatenate(va).mean() - np.concatenate(vb).mean()
    return (point, float(np.nanpercentile(stats, 2.5)), float(np.nanpercentile(stats, 97.5)))


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(SEED)
    pd.set_option("display.width", 200)

    df = load()
    print(f"{len(df):,}行 / {df['date'].nunique()}日 / {df['machine_number'].nunique()}台")
    print(df.groupby("floor").machine_number.nunique().to_string())

    # --- (1) フロア別×カテゴリ別 -------------------------------------------
    rows = []
    for floor, sub_f in df.groupby("floor"):
        for cat, sub in sub_f.groupby("category"):
            if sub["machine_number"].nunique() < 5:
                continue
            m, lo, hi = cluster_boot_mean(sub, "resid_dm", rng)
            rec = {
                "floor": floor,
                "category": cat,
                "n_machines": sub["machine_number"].nunique(),
                "n_rows": len(sub),
                "resid_dm": m,
                "lo": lo,
                "hi": hi,
                "sig": "*" if (lo > 0 or hi < 0) else "",
            }
            if cat == "技術介入":
                bm, blo, bhi = cluster_boot_mean(sub, "bbrb_dm", rng)
                rec["bbrb_dm"], rec["bbrb_sig"] = bm, "*" if (blo > 0 or bhi < 0) else ""
            rows.append(rec)
    res1 = pd.DataFrame(rows).sort_values(["floor", "category"])
    res1.to_csv(OUT_DIR / "floor_by_category.csv", index=False, encoding="utf-8-sig")
    print("\n=== (1) フロア×カテゴリ別 機種内残差 ===")
    cols = ["floor", "category", "n_machines", "n_rows", "resid_dm", "lo", "hi", "sig"]
    if "bbrb_dm" in res1.columns:
        cols += ["bbrb_dm", "bbrb_sig"]
    print(res1[cols].to_string(index=False, float_format=lambda v: f"{v:,.4f}"))

    # --- (2) 本館 vs 新館（全カテゴリプール、元の主張の直接再検証） -----------
    hon = df[df["building"] == "本館"]
    shin = df[df["building"] == "新館"]
    m, lo, hi = cluster_boot_diff(hon, shin, "resid_dm", rng)
    print("\n=== (2) 本館 vs 新館（全カテゴリプール） ===")
    print(f"本館-新館 差: {m:+.4f}pp [{lo:+.4f}, {hi:+.4f}]{' 有意' if (lo > 0 or hi < 0) else ' 非有意'}")
    print(f"  本館 n_machines={hon['machine_number'].nunique()}, 新館 n_machines={shin['machine_number'].nunique()}")

    # カテゴリ別の本館vs新館
    print("\n  カテゴリ別内訳:")
    cat_rows = []
    for cat in df["category"].unique():
        hon_c, shin_c = hon[hon["category"] == cat], shin[shin["category"] == cat]
        if hon_c["machine_number"].nunique() < 5 or shin_c["machine_number"].nunique() < 5:
            continue
        m2, lo2, hi2 = cluster_boot_diff(hon_c, shin_c, "resid_dm", rng)
        cat_rows.append({"category": cat, "diff": m2, "lo": lo2, "hi": hi2, "sig": "*" if (lo2 > 0 or hi2 < 0) else ""})
    cat_df = pd.DataFrame(cat_rows)
    print(cat_df.to_string(index=False, float_format=lambda v: f"{v:,.4f}"))

    # --- (3) 本館1F除外版（Simpson's Paradox除外） ---------------------------
    hon_no1f = df[(df["building"] == "本館") & (df["floor"] != "本館1F")]
    m3, lo3, hi3 = cluster_boot_diff(hon_no1f, shin, "resid_dm", rng)
    print("\n=== (3) 本館(1F除く2F+3F) vs 新館 ===")
    print(f"差: {m3:+.4f}pp [{lo3:+.4f}, {hi3:+.4f}]{' 有意' if (lo3 > 0 or hi3 < 0) else ' 非有意'}")
    print(f"  本館(1F除く) n_machines={hon_no1f['machine_number'].nunique()}")

    building_summary = pd.DataFrame(
        [
            {"comparison": "本館 vs 新館(全カテゴリ)", "diff": m, "lo": lo, "hi": hi},
            {"comparison": "本館(1F除く) vs 新館", "diff": m3, "lo": lo3, "hi": hi3},
        ]
    )
    cat_df2 = cat_df.rename(columns={"category": "comparison"})
    cat_df2["comparison"] = "本館vs新館@" + cat_df2["comparison"]
    building_summary = pd.concat([building_summary, cat_df2], ignore_index=True)
    building_summary.to_csv(OUT_DIR / "building_binary.csv", index=False, encoding="utf-8-sig")

    print(f"\n出力: {OUT_DIR}")


if __name__ == "__main__":
    main()
