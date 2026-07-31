"""経過日数（3フェーズモデル、§5・§5.1）を「台番号単位の設置起点」で測り直す。

背景（rakuen_theory.md §5）:
    既存の経過日数分析（`eda/rakuen_roadmap_3to6.py`, `eda/rakuen_debut_phase_by_segment.py`）は
    `eda/core.py` の `compute_debut_features` に依存する。この関数の debut_date は

        debut_map = df.groupby("machine_name")["date"].min()

    すなわち **機種名(machine_name)単位でホール全体での最古出現日**を「初登場日」とする。
    実測したところ、5台以上ある167機種のうち152機種（91%）で、台番号ごとの設置開始日が
    バラバラだった（例: からくりサーカスは2025-01-01〜2026-06-15まで1年半に渡って
    台番号ごとに新規設置）。つまり既存の「経過日数」は「その台がいつからそこにあるか」
    ではなく「その機種がホールに初めて現れてから何日か」を測っており、後から増設・
    入替された台は実際には新品でも巨大な経過日数を持つことになる。

    加えて既存スクリプトは (a) min_games=2000 の当日足切り（選択バイアス。CLAUDE.md）、
    (b) hit(=plus、差枚>0の二値)を指標に使用（追試13で機種構成のボラティリティを
    測るだけと判明）という、本セッションで確立した2つの既知の欠陥も抱えている。

    さらに「新台は設定不問で高回転する」という既存instinct
    (`feedback_shindai_exclude_from_games_analysis`) 自体が、経過日数と回転数の
    交絡そのものである。elapsed-day効果が回転数の交絡で作られていないか直接確認する。

修正:
    (1) **台番号単位の設置起点**: 同じmachine_numberで連続してmachine_nameが変わらない
        区間ごとに開始日を取り直す（機種入替のたびに経過日数がリセットされる）。
        これが「その台が今の機種でどれだけ設置され続けているか」の正しい定義。
    (2) **指標を機種内残差に変更**（同日×同機種平均からの残差）。日レベル交絡と
        機種構成を同時に落とす。min_gamesによる足切りはしない。
    (3) **回転数交絡の直接確認**: tenure bin別の平均回転数を出し、既存の「新台は
        高回転」パターンがelapsed-day効果とどれだけ重なるかを見る。

    技術介入カテゴリはBB+RB(回/1000G)も併記（打ち手の技量では動かない。§2.1b）。

bin定義は既存踏襲（kamata7と同一）: 1-14日 / 15-60日 / 61-180日 / 181日+。
DB開始日（2025-01-01）からのgrace内に存在していた台は起点不明のため
pre_existingとして別集計にする（既存のpre_existing概念を踏襲）。

期間は工事前エポック 20250101〜20260705（工事後は台番号の新規追加・削除があり
tenureの連続性が保証できないため対象外）。

使い方:
    venv\\Scripts\\python.exe -m eda.rakuen_slot_tenure_recheck
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DB_PATH = PROJECT_ROOT / "db" / "楽園蒲田店.db"
OUT_DIR = Path(__file__).parent / "results" / "rakuen_slot_tenure_recheck"

DATE_START = "20250101"
DATE_END = "20260705"

N_BOOT = 1500
SEED = 20260729

BIN_EDGES = [0, 14, 60, 180, 10_000]
BIN_LABELS = ["1-14日", "15-60日", "61-180日", "181日+"]


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
    df["dt"] = pd.to_datetime(df["date"], format="%Y%m%d")

    # 機種内残差(同日×同機種)。1台しかない群は対照不可なので落とす
    g = df.groupby(["date", "machine_name"])
    df["_n_dm"] = g["machine_number"].transform("size")
    df["resid_dm"] = df["rate"] - g["rate"].transform("mean")
    df["bbrb_dm"] = df["bbrb"] - g["bbrb"].transform("mean")
    df.loc[df["_n_dm"] < 2, ["resid_dm", "bbrb_dm"]] = np.nan
    return df


def add_slot_tenure(df: pd.DataFrame) -> pd.DataFrame:
    """台番号単位の設置起点を再構築する。

    同じmachine_numberで直前の行と同じmachine_nameが続く限り同一run。
    machine_nameが変われば新しいrunとしてtenureを0からリセットする。
    DB開始日(=DATE_START)からgrace_days以内にrunが始まっている場合は
    起点が不明（DB開始前から設置されていた可能性）としてpre_existing=Trueにする。
    """
    df = df.sort_values(["machine_number", "date"]).reset_index(drop=True)
    same_as_prev = df["machine_number"].eq(df["machine_number"].shift()) & df["machine_name"].eq(
        df["machine_name"].shift()
    )
    df["run_id"] = (~same_as_prev).cumsum()
    run_start = df.groupby("run_id")["dt"].transform("min")
    df["slot_start"] = run_start
    df["tenure_days"] = (df["dt"] - df["slot_start"]).dt.days

    db_start = pd.Timestamp(DATE_START)
    df["pre_existing"] = df["slot_start"] <= db_start
    df.loc[df["pre_existing"], "tenure_days"] = np.nan
    df["tenure_bin"] = pd.cut(df["tenure_days"], BIN_EDGES, labels=BIN_LABELS, right=True)
    return df


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

    df = add_slot_tenure(load())
    print(f"{len(df):,}行 / {df['date'].nunique()}日 / {df['machine_number'].nunique()}台")
    print(f"pre_existing行: {df['pre_existing'].sum():,} ({df['pre_existing'].mean() * 100:.1f}%)")
    print(f"tenure_bin別の行数:\n{df['tenure_bin'].value_counts(dropna=False).to_string()}")

    # --- (1) tenure bin別の機種内残差 -----------------------------------------
    rows = []
    for tb, sub in df.groupby("tenure_bin", observed=True):
        if sub["machine_number"].nunique() < 5:
            continue
        m, lo, hi = cluster_boot_mean(sub, "resid_dm", rng)
        rows.append(
            {
                "tenure_bin": tb,
                "n_machines": sub["machine_number"].nunique(),
                "n_rows": len(sub),
                "avg_games": sub["games"].mean(),
                "resid_dm": m,
                "lo": lo,
                "hi": hi,
                "sig": "*" if (lo > 0 or hi < 0) else "",
            }
        )
    res = pd.DataFrame(rows)
    res.to_csv(OUT_DIR / "tenure_bins.csv", index=False, encoding="utf-8-sig")
    print("\n=== (1) 台番号単位tenure bin別 機種内残差(全カテゴリプール) ===")
    print(res.to_string(index=False, float_format=lambda v: f"{v:,.4f}"))

    # --- (2) カテゴリ別 --------------------------------------------------------
    cat_rows = []
    for (tb, cat), sub in df.groupby(["tenure_bin", "category"], observed=True):
        if sub["machine_number"].nunique() < 5:
            continue
        m, lo, hi = cluster_boot_mean(sub, "resid_dm", rng)
        rec = {
            "tenure_bin": tb,
            "category": cat,
            "n_machines": sub["machine_number"].nunique(),
            "avg_games": sub["games"].mean(),
            "resid_dm": m,
            "lo": lo,
            "hi": hi,
            "sig": "*" if (lo > 0 or hi < 0) else "",
        }
        if cat == "技術介入":
            bm, blo, bhi = cluster_boot_mean(sub, "bbrb_dm", rng)
            rec["bbrb_dm"] = bm
            rec["bbrb_sig"] = "*" if (blo > 0 or bhi < 0) else ""
        cat_rows.append(rec)
    cat_res = pd.DataFrame(cat_rows)
    print("\n=== (2) カテゴリ×tenure bin ===")
    print(cat_res.to_string(index=False, float_format=lambda v: f"{v:,.4f}"))

    # --- (3) 回転数交絡の直接確認 ------------------------------------------
    games_tb = df.groupby("tenure_bin", observed=True)["games"].agg(["mean", "median", "std"])
    games_tb.to_csv(OUT_DIR / "games_by_tenure.csv", encoding="utf-8-sig")
    print("\n=== (3) tenure bin別 回転数（新台=高回転パターンの直接確認） ===")
    print(games_tb.to_string(float_format=lambda v: f"{v:,.1f}"))

    # --- 旧定義との比較: 同じ台番号でも機種名ベースの初登場日だと何日ズレるか ---
    old_debut = df.groupby("machine_name")["dt"].min().rename("model_first_seen")
    df2 = df.join(old_debut, on="machine_name")
    df2["old_style_tenure"] = (df2["dt"] - df2["model_first_seen"]).dt.days
    df2["tenure_gap"] = df2["old_style_tenure"] - df2["tenure_days"]
    gap_summary = (
        df2.dropna(subset=["tenure_gap"])
        .groupby("tenure_bin", observed=True)["tenure_gap"]
        .agg(["mean", "median", "max"])
    )
    gap_summary.to_csv(OUT_DIR / "debut_definition_comparison.csv", encoding="utf-8-sig")
    print("\n=== 旧定義(機種名ベース)との経過日数の乖離(日) ===")
    print("正の値 = 旧定義が実際のtenureより過大評価していた日数")
    print(gap_summary.to_string(float_format=lambda v: f"{v:,.1f}"))

    print(f"\n出力: {OUT_DIR}")


if __name__ == "__main__":
    main()
