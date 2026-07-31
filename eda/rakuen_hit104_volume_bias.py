"""hit104率が「設定の指標」なのか「回転数の指標」なのかを分離する。

背景:
    追試13で hit率 = P(差枚>0) が平均でなく**分布の形**に依存することが判明し、
    区画比較の指標から外された（rakuen_theory.md §1）。hit104率 = P(機械割>104%)
    はまったく同じ構造をしている。機械割は

        rate = 100 + diff / (3 * games) * 100

    で、diff の分散は games に比例するので **Var(rate) ∝ 1/games**。真の期待機械割が
    104% 未満の機種では、回転数が増えるほど分布が 104 の下側に締まり、
    **設定が同じでも hit104率は下がる**。楽園の土日は平日より回転数が 40〜70% 多い
    （rakuen_theory.md §11.4）ので、この一点だけで土日の hit104率は下がりうる。

    §11.4 は「機械割(hit104率)は回転数に左右されにくい比率指標だから、月/日の結論は
    回転数交絡では説明できない」と結論しているが、上記が正しければこの反証は成立しない。

やること:
    (1) スケーリングの検証 — z = (rate - mu_機種) * sqrt(games) の SD が games に
        よらず一定か。一定なら Var(rate) ∝ 1/games が実データで成り立つ
    (2) 反実仮想 — 「各機種の真の機械割はその機種の全期間平均で一定、日ごとの
        ばらつきは回転数由来のノイズだけ」という帰無世界での hit104率を、実際の
        games を使って行ごとに計算する。これを曜日別・DD別に集計すると
        **「回転数の違いだけで説明できる hit104率の差」**が得られる
    (3) 観測 hit104率と (2) の期待値を突き合わせる。差が残らなければ、その軸の
        hit104率は回転数を測っていただけということになる

    比較のため、回転数に依存しない指標として **BB+RB(回/1000G) の機種内残差**を
    同じ軸で並べる。BB+RB はカウントの比なので水準の推定に閾値を使わない。

方法上の約束（プロジェクト規約）:
    * min_games による足切りはしない。games は設定の下流なので足切りは選択バイアス
    * BB/RB は bb_count/rb_count から直接計算（rb_probability_decimal は rb_count==0 で
      NULL になり RB0回の日を非ランダムに落とす。追試9）
    * CI は台単位のクラスタブートストラップ

使い方:
    venv\\Scripts\\python.exe -m eda.rakuen_hit104_volume_bias
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DB_PATH = PROJECT_ROOT / "db" / "楽園蒲田店.db"
OUT_DIR = Path(__file__).parent / "results" / "rakuen_hit104_volume_bias"

DATE_START = "20250101"
DATE_END = "20260727"

# 反実仮想の z 分布を機種ごとに推定するのに必要な最小行数。少ないと経験分布が
# ガタつくだけなので、行数の足りない機種は (2)(3) の集計から外す（(1) には使う）。
MIN_ROWS_PER_MODEL = 200

WEEKDAY_JA = ["月", "火", "水", "木", "金", "土", "日"]


def load() -> pd.DataFrame:
    query = """
        SELECT r.date, r.machine_number, r.machine_name,
               r.games_normalized AS games,
               r.diff_coins_normalized AS diff_coins,
               r.bb_count, r.rb_count
        FROM machine_detailed_results r
        WHERE r.date BETWEEN ? AND ?
          AND r.games_normalized > 0
    """
    with sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True) as con:
        df = pd.read_sql_query(query, con, params=(DATE_START, DATE_END))

    df["dt"] = pd.to_datetime(df["date"], format="%Y%m%d")
    df["weekday"] = df["dt"].dt.weekday
    df["dd"] = df["dt"].dt.day
    df["month"] = df["dt"].dt.month
    df["strong_zorome"] = df["month"] == df["dd"]

    df["rate"] = 100 + df["diff_coins"] / (3 * df["games"]) * 100
    df["hit104"] = (df["rate"] >= 104).astype(float)
    df["bbrb"] = (df["bb_count"].fillna(0) + df["rb_count"].fillna(0)) / df["games"] * 1000
    return df


def add_model_baseline(df: pd.DataFrame) -> pd.DataFrame:
    """機種ごとの games 加重平均機械割 mu と、スケール後の残差 z を付ける。

    mu は「その機種の全期間の総差枚 / 総回転数」に対応する水準推定で、
    行数の偏りにも回転数の偏りにも引きずられにくい。
    """
    g = df.groupby("machine_name")
    tot_diff = g["diff_coins"].transform("sum")
    tot_games = g["games"].transform("sum")
    df["mu_model"] = 100 + tot_diff / (3 * tot_games) * 100
    df["z"] = (df["rate"] - df["mu_model"]) * np.sqrt(df["games"])
    df["n_rows_model"] = g["date"].transform("size")
    return df


def step1_scaling(df: pd.DataFrame) -> pd.DataFrame:
    """z の SD が games によらず一定か。Var(rate) ∝ 1/games の実データ検証。"""
    d = df.copy()
    d["games_decile"] = pd.qcut(d["games"], 10, labels=False, duplicates="drop") + 1
    out = d.groupby("games_decile").agg(
        n=("z", "size"),
        games_median=("games", "median"),
        sd_rate=("rate", "std"),
        sd_z=("z", "std"),
        hit104=("hit104", "mean"),
        mean_rate=("rate", "mean"),
    )
    # 参考: Var(rate) ∝ 1/games が成り立つなら sd_rate * sqrt(games) はほぼ一定
    out["sd_rate_x_sqrt_games"] = out["sd_rate"] * np.sqrt(out["games_median"])
    return out.reset_index()


def expected_hit104(df: pd.DataFrame) -> pd.Series:
    """帰無世界（機種の真の機械割は一定、ばらつきは回転数由来のみ）での hit104 期待値。

    各行 i について、その機種の z の経験分布を使って
        P(rate_i >= 104) = P(z >= (104 - mu) * sqrt(games_i))
    を計算する。z 分布は機種内で共通（＝日ごとの設定差を認めない世界）なので、
    行ごとに違うのは games_i だけ。**回転数の違いだけが hit104 を動かす**世界。
    """
    exp = pd.Series(np.nan, index=df.index, dtype=float)
    for _name, sub in df.groupby("machine_name", sort=False):
        z_sorted = np.sort(sub["z"].to_numpy())
        thresh = (104 - sub["mu_model"].to_numpy()) * np.sqrt(sub["games"].to_numpy())
        # P(z >= thresh) = 1 - ECDF(thresh)
        idx = np.searchsorted(z_sorted, thresh, side="left")
        exp.loc[sub.index] = 1.0 - idx / len(z_sorted)
    return exp


def within_model_resid(df: pd.DataFrame, col: str) -> pd.Series:
    """機種平均（全期間）からの残差。

    DD・曜日は日付の関数なので「同日×同機種」残差では構造上ゼロに潰れる
    （rakuen_theory.md §2 の曜日行と同じ罠）。日レベルの軸を測るときは
    日を統制せず、機種構成だけを落とす。
    """
    return df[col] - df.groupby("machine_name")[col].transform("mean")


def cluster_bootstrap_mean(
    values: np.ndarray,
    clusters: np.ndarray,
    rng: np.random.Generator,
    n_boot: int = 1000,
) -> tuple[float, float]:
    """台単位のクラスタブートストラップで平均の95%CIを返す。"""
    uniq, inv = np.unique(clusters, return_inverse=True)
    order = np.argsort(inv, kind="stable")
    vals_sorted = values[order]
    bounds = np.searchsorted(inv[order], np.arange(len(uniq) + 1))
    pieces = [vals_sorted[bounds[i] : bounds[i + 1]] for i in range(len(uniq))]

    stats = np.empty(n_boot)
    for b in range(n_boot):
        pick = rng.integers(0, len(pieces), len(pieces))
        stats[b] = np.concatenate([pieces[j] for j in pick]).mean()
    return float(np.percentile(stats, 2.5)), float(np.percentile(stats, 97.5))


def axis_table(df: pd.DataFrame, axis: str, rng: np.random.Generator) -> pd.DataFrame:
    """軸（weekday / dd）別に、観測 hit104・期待 hit104・その差・BB+RB残差を並べる。"""
    rows = []
    for key, sub in df.groupby(axis, sort=True):
        resid_bbrb = sub["resid_bbrb"].to_numpy()
        lo, hi = cluster_bootstrap_mean(resid_bbrb, sub["machine_number"].to_numpy(), rng)
        rows.append(
            {
                axis: key,
                "n": len(sub),
                "avg_games": sub["games"].mean(),
                "hit104_obs": sub["hit104"].mean() * 100,
                "hit104_exp_volume_only": sub["hit104_exp"].mean() * 100,
                "hit104_excess_pp": (sub["hit104"].mean() - sub["hit104_exp"].mean()) * 100,
                "avg_diff": sub["diff_coins"].mean(),
                "resid_rate_pp": sub["resid_rate"].mean(),
                "resid_bbrb": resid_bbrb.mean(),
                "resid_bbrb_lo": lo,
                "resid_bbrb_hi": hi,
            }
        )
    return pd.DataFrame(rows)


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(20260728)

    df = add_model_baseline(load())
    print(f"読み込み: {len(df):,}行 / {df['machine_name'].nunique()}機種 / {df['date'].nunique()}日")

    # --- (1) スケーリング検証 -------------------------------------------------
    scaling = step1_scaling(df)
    scaling.to_csv(OUT_DIR / "scaling_check.csv", index=False, encoding="utf-8-sig")
    print("\n=== (1) Var(rate) ∝ 1/games の検証（games十分位） ===")
    print(
        scaling[
            ["games_decile", "n", "games_median", "sd_rate", "sd_rate_x_sqrt_games", "mean_rate", "hit104"]
        ].to_string(index=False, float_format=lambda v: f"{v:,.3f}")
    )

    # --- (2)(3) 反実仮想と軸別比較 -------------------------------------------
    d = df.loc[df["n_rows_model"] >= MIN_ROWS_PER_MODEL].copy()
    print(
        f"\n反実仮想の対象: {len(d):,}行 / {d['machine_name'].nunique()}機種（{MIN_ROWS_PER_MODEL}行以上の機種に限定）"
    )
    d["hit104_exp"] = expected_hit104(d)
    d["resid_rate"] = within_model_resid(d, "rate")
    d["resid_bbrb"] = within_model_resid(d, "bbrb")

    for axis, label in (("weekday", "曜日"), ("dd", "DD")):
        tbl = axis_table(d, axis, rng)
        if axis == "weekday":
            tbl["weekday"] = tbl["weekday"].map(dict(enumerate(WEEKDAY_JA)))
        tbl.to_csv(
            OUT_DIR / f"{axis}_hit104_decomposition.csv",
            index=False,
            encoding="utf-8-sig",
        )
        print(f"\n=== {label}別: 観測hit104 vs 回転数だけで説明される期待hit104 ===")
        show = tbl.sort_values("resid_bbrb", ascending=False) if axis == "dd" else tbl
        print(show.to_string(index=False, float_format=lambda v: f"{v:,.3f}"))

    # 強ゾロ目
    tbl = axis_table(d, "strong_zorome", rng)
    tbl.to_csv(
        OUT_DIR / "strong_zorome_decomposition.csv",
        index=False,
        encoding="utf-8-sig",
    )
    print("\n=== 強ゾロ目（月=日） ===")
    print(tbl.to_string(index=False, float_format=lambda v: f"{v:,.3f}"))

    print(f"\n出力: {OUT_DIR}")


if __name__ == "__main__":
    main()
