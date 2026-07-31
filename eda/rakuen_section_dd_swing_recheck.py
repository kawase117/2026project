"""§8 Type A/B（セクション×DDスイング）を機種内残差で再検証する。

背景（rakuen_theory.md §8、§12.5）:
    §8の元分析（`eda/rakuen_section_dd_swing_analysis.py`）は avg_diff（回転数の
    影響を受ける生の差枚平均）と旧43 sectionの定義に基づく。本セッションで
    (a) hit率/差枚が回転数交絡・機種構成のボラティリティを測るだけと判明（追試13）、
    (b) 旧sectionの一部（1106-1115・2141-2162）が2列を1つに誤って統合していたと判明
    （§2.1a）——のうち§8で扱う4区画（1130-1134・3117-3120・3113-3116・1209-1216）は
    境界自体は変わっていないが、指標は避けられない旧課題を抱えたまま。

    機種構成を確認したところ:
      1130-1134・3117-3120・3113-3116: AT一般中心で機種入替が頻繁
      1209-1216: 全期間マイジャグラーV単一機種（ジャグ、§1のHot/Coldとは別区画）

指標:
    resid_dm = 機械割 - 同日×同機種平均（機種内残差）。日レベルの交絡と機種構成の
    違い（入替の多いAT一般ほど深刻）を同時に落とす。技術介入・ジャグはBB+RBも併記
    （打ち手の技量では動かない。§2.1b）。min_gamesによる足切りはしない。

    DD別に31日分の機種内残差平均＋台単位クラスタブートストラップCIを算出し、
    §8の元の主張（1130-1134=全DD一貫マイナス、3117-3120=DD11/29/30favorable・
    DD25/31/14avoid、3113-3116=符号一致率51.6%でランダム、1209-1216=DD10/11/22/30
    でリフト）が機種内残差でも再現するかを見る。

期間は工事前エポック 20250101〜20260705。

使い方:
    venv\\Scripts\\python.exe -m eda.rakuen_section_dd_swing_recheck
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DB_PATH = PROJECT_ROOT / "db" / "楽園蒲田店.db"
OUT_DIR = Path(__file__).parent / "results" / "rakuen_section_dd_swing_recheck"
HALL_NAME = "楽園蒲田店"

DATE_START = "20250101"
DATE_END = "20260705"

TARGET_SECTIONS = ["1130-1134", "3117-3120", "3113-3116", "1209-1216"]

N_BOOT = 1500
SEED = 20260729


def load() -> pd.DataFrame:
    """ホール全体を読み込み、機種内残差をホール全体の母集団で計算してから
    対象4区画へ絞り込む。

    ⚠️ 対象区画だけをSQLで絞ってから残差を計算すると、他区画にも設置されている
    機種（例: マイジャグラーVは1197-1208と1209-1216の両方に設置）の残差が
    「対象区画内だけ」で計算し直されてしまい、モデルがその区画に閉じ込められて
    いるかのような人為的なゼロ退化を生む（§1のB-3で発見した構造的退化と同型の
    アーティファクトだが、今回はクエリ設計のバグ）。必ずホール全体で残差を
    計算してから対象区画へ絞ること。
    """
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

    # 機種内残差はホール全体（577台）で計算する
    g = df.groupby(["date", "machine_name"])
    df["_n_dm"] = g["machine_number"].transform("size")
    df["resid_dm"] = df["rate"] - g["rate"].transform("mean")
    df["bbrb_dm"] = df["bbrb"] - g["bbrb"].transform("mean")
    df.loc[df["_n_dm"] < 2, ["resid_dm", "bbrb_dm"]] = np.nan

    dt = pd.to_datetime(df["date"], format="%Y%m%d")
    df["dd"] = dt.dt.day

    # 対象4区画へ絞り込むのは残差計算の後
    return df[df["section"].isin(TARGET_SECTIONS)].copy()


def cluster_boot_mean(sub: pd.DataFrame, col: str, rng: np.random.Generator) -> tuple[float, float, float]:
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


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(SEED)
    pd.set_option("display.width", 200)

    df = load()
    print(f"{len(df):,}行 / {df['date'].nunique()}日")
    print(
        df.groupby("section")
        .agg(
            カテゴリ=("category", lambda s: ",".join(sorted(s.unique()))),
            機種数=("machine_name", "nunique"),
            台数=("machine_number", "nunique"),
        )
        .to_string()
    )

    rows = []
    for sec in TARGET_SECTIONS:
        sub_sec = df[df["section"] == sec]
        cat_here = sub_sec["category"].mode().iat[0]
        for dd_val, sub in sub_sec.groupby("dd"):
            m, lo, hi = cluster_boot_mean(sub, "resid_dm", rng)
            rec = {
                "section": sec,
                "dd": dd_val,
                "n_rows": len(sub),
                "n_machines": sub["machine_number"].nunique(),
                "resid_dm": m,
                "lo": lo,
                "hi": hi,
                "sig": "*" if (lo > 0 or hi < 0) else "",
            }
            if cat_here in ("ジャグ", "技術介入"):
                bm, blo, bhi = cluster_boot_mean(sub, "bbrb_dm", rng)
                rec["bbrb_dm"] = bm
                rec["bbrb_sig"] = "*" if (blo > 0 or bhi < 0) else ""
            rows.append(rec)
    res = pd.DataFrame(rows)
    res.to_csv(OUT_DIR / "dd_swing_by_section.csv", index=False, encoding="utf-8-sig")

    def fmt(v: float) -> str:
        return f"{v:,.4f}"

    for sec in TARGET_SECTIONS:
        sub = res[res["section"] == sec].sort_values("resid_dm", ascending=False)
        n_sig_pos = ((sub["sig"] == "*") & (sub["resid_dm"] > 0)).sum()
        n_sig_neg = ((sub["sig"] == "*") & (sub["resid_dm"] < 0)).sum()
        sign_match = (sub["resid_dm"] > 0).mean()
        print(f"\n=== {sec} (機種内残差、DD別、31日分) ===")
        cols = [
            c
            for c in ["dd", "n_rows", "n_machines", "resid_dm", "lo", "hi", "sig", "bbrb_dm", "bbrb_sig"]
            if c in sub.columns
        ]
        show = pd.concat([sub.head(5), sub.tail(5)]) if len(sub) > 10 else sub
        print(show[cols].to_string(index=False, float_format=fmt))
        print(
            f"  符号がプラスの割合: {sign_match:.1%}  "
            f"有意プラス:{n_sig_pos}件 有意マイナス:{n_sig_neg}件 / 全{len(sub)}日"
        )

    print(f"\n出力: {OUT_DIR}")


if __name__ == "__main__":
    main()
