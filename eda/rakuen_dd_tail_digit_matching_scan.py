"""「日にちの数字を台番号の末尾に寄せる」という現場の噂を、全31日で網羅的に検証する。

背景（ユーザー提供の仮説、2026-07-29）:
    楽園によく行く知人の話として「末尾をDDに寄せる」傾向があるという。
    具体例: DD29→末尾2と9、DD1→末尾1、DD11/22→末尾下二桁ゾロ目。
    加えて `eda/rakuen_aday_at_attribute_scan.py` で発見済みの
    「DD7×技術介入×末尾7」（機械割+1.656pp・BB+RB+0.152、両方有意）の耐久性も検証する。

桁分解ルール（ユーザー確定）:
    DD 1-9（1桁）        → 対象末尾 = {DD}
    DD 10-31・両桁が異なる → 対象末尾 = {十の位, 一の位}（OR、例: 29→{2,9}）
    DD 11・22（両桁一致）  → 対象は「末尾ゾロ目全般」（台番号下2桁が同じ台。11,22,33…どれでも）

指標設計:
    resid_d = 機械割 - その日の同カテゴリ全台平均（**同日内残差**）。
    DD・曜日は日付の関数なので同日残差は日レベルの交絡（客入り・天候・§3.1aで確定した
    イベント日の全体的な強さ）を完全に落とす。これにより「その日は全体的に強い」ではなく
    「その日、特定の末尾だけ他の台より強いか」を切り出せる。
    カテゴリ（ジャグ/技術介入/AT一般/ハナハナ）内で中心化してから全カテゴリをプールする
    （中心化後は各カテゴリの平均が0になるため、プールしても加重平均として妥当）。

    lift(target, DD) = mean(resid_d | target群, dd==DD) - mean(resid_d | target群, dd!=DD)
    「その末尾がいつも強い」ではなく「そのDDに限って強くなる」ものだけを拾う設計。

3種の診断:
    (1) 単一桁の日(DD1-9): 対象末尾1つに対し、末尾0-9すべてのlift point-estimateを計算し、
        仮説の末尾が10候補中何位かを見る（ランダムなら期待順位5.5、上位3以内が偶然なら30%）
    (2) 2桁で異なる日: 対象2桁の合成OR群でlift+ブートストラップCI
    (3) DD11・DD22: 末尾ゾロ目群のliftを全31日で計算し、11・22がその分布内で何位かを見る
        （ゾロ目群が「その日だから」強いのか「たまたま」かを31日の分布で判定）

    さらに DD7×技術介入×末尾7（既発見）については split-half（前半/後半）で耐久性を検証する。

方法上の約束（プロジェクト規約）:
    * min_games による足切りはしない（games は設定の下流。CLAUDE.md）
    * BB/RB は bb_count/rb_count から直接計算（rb_probability_decimal は追試9のバグを持つ）
    * CI は台単位のクラスタブートストラップ（同じ台の連日観測は独立でない）

期間は工事前エポック 20250101〜20260705。位置情報は使わないため machine_layout_history
との結合は不要（末尾は machine_number 自体から決まる）。

使い方:
    venv\\Scripts\\python.exe -m eda.rakuen_dd_tail_digit_matching_scan
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DB_PATH = PROJECT_ROOT / "db" / "楽園蒲田店.db"
OUT_DIR = Path(__file__).parent / "results" / "rakuen_dd_tail_digit_matching_scan"

DATE_START = "20250101"
DATE_END = "20260705"

N_BOOT = 1500
SEED = 20260729


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
    dt = pd.to_datetime(df["date"], format="%Y%m%d")
    df["dd"] = dt.dt.day

    df["resid_d"] = df["rate"] - df.groupby(["date", "category"])["rate"].transform("mean")
    df["bbrb_d"] = df["bbrb"] - df.groupby(["date", "category"])["bbrb"].transform("mean")

    df["last_digit"] = df["machine_number"] % 10
    two = df["machine_number"] % 100
    df["is_tail_zorome"] = (two // 10) == (two % 10)
    return df


def target_spec(dd: int) -> tuple[str, object]:
    """DDから対象末尾を決める（ユーザー確定の桁分解ルール）。"""
    if dd <= 9:
        return "single", {dd}
    tens, ones = divmod(dd, 10)
    if tens == ones:
        return "zorome", None
    return "pair", {tens, ones}


def cluster_boot_diff(
    target_mask: pd.Series,
    dd_val: int,
    df: pd.DataFrame,
    col: str,
    rng: np.random.Generator,
) -> tuple[float, float]:
    """lift = mean(col|対象群,当該DD) - mean(col|対象群,他DD) の95%CI。台単位で再標本化。"""
    sub = df.loc[target_mask, ["machine_number", col, "dd"]].dropna(subset=[col])
    a = sub.loc[sub["dd"] == dd_val].groupby("machine_number")[col].apply(lambda s: s.to_numpy())
    n = sub.loc[sub["dd"] != dd_val].groupby("machine_number")[col].apply(lambda s: s.to_numpy())
    machines = np.array(sorted(set(a.index) | set(n.index)))
    if len(machines) < 2:
        return (np.nan, np.nan)
    stats = np.full(N_BOOT, np.nan)
    for i in range(N_BOOT):
        pick = rng.choice(machines, len(machines), replace=True)
        av = [a[m] for m in pick if m in a.index]
        nv = [n[m] for m in pick if m in n.index]
        if not av or not nv:
            continue
        stats[i] = np.concatenate(av).mean() - np.concatenate(nv).mean()
    return float(np.nanpercentile(stats, 2.5)), float(np.nanpercentile(stats, 97.5))


def point_lift(df: pd.DataFrame, mask: pd.Series, dd_val: int, col: str = "resid_d") -> float:
    sub = df.loc[mask]
    a = sub.loc[sub["dd"] == dd_val, col].mean()
    n = sub.loc[sub["dd"] != dd_val, col].mean()
    return a - n


def single_digit_matrix(df: pd.DataFrame) -> pd.DataFrame:
    """全31日 × 末尾0-9 の point-estimate lift 行列（診断用、ブートストラップなし）。"""
    rows = []
    for dd_val in range(1, 32):
        if dd_val not in df["dd"].unique():
            continue
        for digit in range(10):
            mask = df["last_digit"] == digit
            rows.append({"dd": dd_val, "digit": digit, "lift": point_lift(df, mask, dd_val)})
    return pd.DataFrame(rows)


def zorome_by_day(df: pd.DataFrame) -> pd.DataFrame:
    """末尾ゾロ目群のliftを全31日で計算（11・22の位置づけを見る分布）。"""
    rows = []
    mask = df["is_tail_zorome"]
    for dd_val in range(1, 32):
        if dd_val not in df["dd"].unique():
            continue
        rows.append({"dd": dd_val, "lift": point_lift(df, mask, dd_val)})
    return pd.DataFrame(rows)


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(SEED)
    pd.set_option("display.width", 220)

    df = load()
    print(f"{len(df):,}行 / {df['date'].nunique()}日 / {df['machine_number'].nunique()}台")
    print(df.groupby("category").machine_number.nunique().to_string())

    # --- 診断(1): 単一桁の日 DD1-9 ---------------------------------------------
    digit_mat = single_digit_matrix(df)
    digit_mat.to_csv(OUT_DIR / "single_digit_matrix_all_dd.csv", index=False, encoding="utf-8-sig")

    print("\n=== 診断(1) 単一桁の日(DD1-9): 仮説末尾の順位 ===")
    single_rows = []
    for dd_val in range(1, 10):
        sub = digit_mat[digit_mat["dd"] == dd_val].sort_values("lift", ascending=False).reset_index(drop=True)
        rank = sub.index[sub["digit"] == dd_val][0] + 1
        target_lift = sub.loc[sub["digit"] == dd_val, "lift"].iat[0]
        lo, hi = cluster_boot_diff(df["last_digit"] == dd_val, dd_val, df, "resid_d", rng)
        single_rows.append(
            {
                "dd": dd_val,
                "target_digit": dd_val,
                "lift": target_lift,
                "lift_lo": lo,
                "lift_hi": hi,
                "rank_of_10": rank,
                "sig": "*" if (lo > 0 or hi < 0) else "",
            }
        )
    single_df = pd.DataFrame(single_rows)
    single_df.to_csv(OUT_DIR / "single_digit_days_result.csv", index=False, encoding="utf-8-sig")
    print(single_df.to_string(index=False, float_format=lambda v: f"{v:,.4f}"))
    top3_rate = (single_df["rank_of_10"] <= 3).mean()
    print(f"\n上位3位以内に入った割合: {top3_rate:.1%}（ランダムなら30%）")

    # --- 診断(2): 2桁で異なる日 --------------------------------------------------
    print("\n=== 診断(2) 2桁で異なる日(10,12-21,23-31 except 11,22): 合成OR群のlift ===")
    pair_rows = []
    for dd_val in range(10, 32):
        kind, target = target_spec(dd_val)
        if kind != "pair":
            continue
        mask = df["last_digit"].isin(target)
        lift = point_lift(df, mask, dd_val)
        lo, hi = cluster_boot_diff(mask, dd_val, df, "resid_d", rng)
        n_mach = df.loc[mask, "machine_number"].nunique()
        pair_rows.append(
            {
                "dd": dd_val,
                "target_digits": sorted(target),
                "n_machines": n_mach,
                "lift": lift,
                "lift_lo": lo,
                "lift_hi": hi,
                "sig": "*" if (lo > 0 or hi < 0) else "",
            }
        )
    pair_df = pd.DataFrame(pair_rows).sort_values("lift", ascending=False)
    pair_df.to_csv(OUT_DIR / "pair_digit_days_result.csv", index=False, encoding="utf-8-sig")
    print(pair_df.to_string(index=False, float_format=lambda v: f"{v:,.4f}"))
    n_sig_pair = (pair_df["sig"] == "*").sum()
    print(f"\n有意だった日数: {n_sig_pair}/{len(pair_df)}（ランダムなら5%水準で約{len(pair_df) * 0.05:.1f}日）")

    # --- 診断(3): DD11・DD22 ゾロ目 ----------------------------------------------
    print("\n=== 診断(3) 末尾ゾロ目群のlift、全31日の分布内でDD11・DD22の順位 ===")
    zo = zorome_by_day(df).sort_values("lift", ascending=False).reset_index(drop=True)
    zo.to_csv(OUT_DIR / "zorome_lift_all_dd.csv", index=False, encoding="utf-8-sig")
    for dd_val in (11, 22):
        rank = zo.index[zo["dd"] == dd_val][0] + 1
        lo, hi = cluster_boot_diff(df["is_tail_zorome"], dd_val, df, "resid_d", rng)
        lift = zo.loc[zo["dd"] == dd_val, "lift"].iat[0]
        print(
            f"  DD{dd_val}: lift={lift:+.4f} [{lo:+.4f},{hi:+.4f}] "
            f"順位={rank}/{len(zo)}"
            f"{' *' if (lo > 0 or hi < 0) else ''}"
        )
    print("\n  全31日ランキング（上位5・下位3）:")
    show = pd.concat([zo.head(5), zo.tail(3)])
    print(show.to_string(index=False, float_format=lambda v: f"{v:,.4f}"))

    # --- DD7×技術介入×末尾7 の耐久性検証（split-half） ---------------------------
    print("\n=== DD7×技術介入×末尾7 の耐久性検証（split-half） ===")
    tech = df[df["category"] == "技術介入"].copy()
    dates_sorted = np.sort(tech["date"].unique())
    mid = dates_sorted[len(dates_sorted) // 2]
    tech_h1 = tech[tech["date"] < mid]
    tech_h2 = tech[tech["date"] >= mid]
    for label, sub in (("全期間", tech), ("前半", tech_h1), ("後半", tech_h2)):
        mask7 = sub["last_digit"] == 7
        if mask7.sum() < 20:
            print(f"  {label}: サンプル不足（末尾7行数={mask7.sum()}）")
            continue
        lift = point_lift(sub, mask7, 7)
        lo, hi = cluster_boot_diff(mask7, 7, sub, "resid_d", rng)
        bb_lift = point_lift(sub, mask7, 7, "bbrb_d")
        blo, bhi = cluster_boot_diff(mask7, 7, sub, "bbrb_d", rng)
        print(
            f"  {label}: 機械割lift={lift:+.4f} [{lo:+.4f},{hi:+.4f}]"
            f"{' *' if (lo > 0 or hi < 0) else ''}  "
            f"BB+RB lift={bb_lift:+.4f} [{blo:+.4f},{bhi:+.4f}]"
            f"{' *' if (blo > 0 or bhi < 0) else ''}"
        )

    print(f"\n出力: {OUT_DIR}")


if __name__ == "__main__":
    main()
