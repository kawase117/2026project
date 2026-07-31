"""DD を二値イベント日でなく「連続スコア」として、設定事後分布で全ホール比較する。

背景（rakuen_theory.md §3 への疑義）:
    楽園のイベント日定義 {10,11,22,30} は avg_diff と hit104率だけで決めている。
    しかしイベント日は avg_games が通常日比 +49% で、差枚 ≈ 回転数 ×(機械割-100)
    なので**「客が多い日」を測っているだけ**の可能性がある。hit104率も
    P(機械割>104%) という閾値超え確率で、Var(機械割) ∝ 1/games により
    回転数が増えるだけで動く（`eda/rakuen_hit104_volume_bias.py` で実証済み）。
    BB+RB(回/1000G) も低回転行に打ち手の打ち切りバイアスが乗り、games と相関する。

    **日レベルの軸（DD・曜日）は「同日残差」で日を統制できない**ため、
    回転数交絡から逃げられない。逃げる唯一の道は、回転数を
    「足切り」でも「統制変数」でもなく **観測の情報量（尤度の重み）** として
    扱う指標に変えること。それがジャグの BB/RB 二項尤度による設定事後分布。

指標の設計:
    各台×日について、公表設定別 BB/RB 確率に対する二項尤度から
    P(設定5-6) = p56 を出す（一様事前）。回転数が少ない日は尤度が平坦になり
    p56 は事前(=2/6)に戻るだけで、**外れ値方向に暴れない**。足切り不要。

    2つの指標を併記する。両者は回転数交絡が**逆向き**に効くので、
    同じ方向を指したときだけ本物と判断できる（ブラケット設計）:

      mean_p56       台×日の p56 平均。真の高設定率は 1/3 より低いので、
                     回転数が増えるほど事前から離れて **下がる** 方向に歪む
      n_high_per_day p56>=0.8 の台数/日。低回転では 0.8 に到達できないので、
                     回転数が増えるほど **上がる** 方向に歪む

    したがって「回転数が多いのに mean_p56 も高い」DD は、交絡では説明できない。

    さらに 1DD あたり約18日しかないため、生の順位はほぼノイズ。
    経験ベイズでホール全体平均へ縮約したスコア(mean_p56_shrunk)を併記し、
    **順位ではなく縮約後の連続値**を使うことを推奨する。

ホール横断の狙い（ユーザー指示）:
    「楽園・蒲田1・蒲田7 は平常日でも高設定を入れており、他ホールは平日に
    高設定が存在しない可能性が高い」。二値化はこの差を捨てる。連続スコアなら
    **DD上位と下位の落差**および**下位DDの水準**でホールを特徴づけられる。

使い方:
    venv\\Scripts\\python.exe -m eda.dd_setting_posterior_rank
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from ml.experiments.jug_rb_setting_prediction.config import (  # noqa: E402
    JUGGLER_FAMILY_MATCHERS,
    JUGGLER_FAMILY_SPECS,
)

OUT_DIR = Path(__file__).parent / "results" / "dd_setting_posterior_rank"

HALLS: dict[str, str] = {
    "楽園蒲田": "楽園蒲田店.db",
    "蒲田1": "マルハンメガシティ2000-蒲田1.db",
    "蒲田7": "マルハンメガシティ2000-蒲田7.db",
    "みとや": "みとや大森町店.db",
    "ヒロキ": "ヒロキ東口店.db",
    "ザシティ": "ザ-シティ-ベルシティ雑色店.db",
    "レイトギャップ": "レイトギャップ平和島.db",
    "ARROW池上": "ARROW池上店.db",
    "金時京急": "金時京急蒲田店.db",
}

DATE_START = "20250101"
DATE_END = "20260727"

P56_HIGH = 0.80  # 「高設定確定扱い」の閾値（既存パイプライン踏襲）
WEEKDAY_JA = ["月", "火", "水", "木", "金", "土", "日"]


def match_family(name: str) -> str | None:
    for key, kw in JUGGLER_FAMILY_MATCHERS:
        if kw in name:
            return key
    return None


def jug_posterior_p56(df: pd.DataFrame) -> pd.Series:
    """一様事前・BB/RB二項尤度で P(設定5-6)。組合せ項は設定間で相殺するので省略。

    回転数が少ない行は対数尤度差が小さくなり、事後は自動的に事前(1/3)へ戻る。
    これが「games を足切りでなく重みとして扱う」ということ。
    """
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


def load_hall(path: Path) -> pd.DataFrame:
    query = """
        SELECT date, machine_number, machine_name,
               games_normalized AS games, bb_count, rb_count
        FROM machine_detailed_results
        WHERE date BETWEEN ? AND ?
          AND games_normalized > 0
          AND bb_count IS NOT NULL AND rb_count IS NOT NULL
    """
    with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as con:
        df = pd.read_sql_query(query, con, params=(DATE_START, DATE_END))
    df["family"] = df["machine_name"].map(match_family)
    df = df.loc[df["family"].notna()].reset_index(drop=True)
    if df.empty:
        return df
    # BB/RB は物理的に回転数を超えない。壊れた行は尤度を破壊するので落とす
    df = df.loc[
        (df["bb_count"] >= 0) & (df["rb_count"] >= 0) & (df["bb_count"] + df["rb_count"] < df["games"])
    ].reset_index(drop=True)
    df["p56"] = jug_posterior_p56(df)
    dt = pd.to_datetime(df["date"], format="%Y%m%d")
    df["dd"] = dt.dt.day
    df["weekday"] = dt.dt.weekday
    df["strong_zorome"] = dt.dt.month == dt.dt.day
    return df


def shrink(group_means: pd.Series, group_ns: pd.Series, within_var: float) -> pd.Series:
    """経験ベイズ縮約。1DD≈18日しかないので生の平均・順位は使わせない。

    B = tau2 / (tau2 + within_var / n) で全体平均へ引き寄せる。
    tau2（DD間の真のばらつき）は観測分散から観測誤差分を引いて推定する。
    """
    grand = np.average(group_means, weights=group_ns)
    obs_var = np.average((group_means - grand) ** 2, weights=group_ns)
    mean_err = np.average(within_var / group_ns, weights=group_ns)
    tau2 = max(obs_var - mean_err, 0.0)
    b = tau2 / (tau2 + within_var / group_ns)
    return grand + b * (group_means - grand)


def axis_scores(df: pd.DataFrame, axis: str) -> pd.DataFrame:
    n_days = df.groupby(axis)["date"].nunique()
    g = df.groupby(axis)
    tbl = pd.DataFrame(
        {
            "n_machine_days": g.size(),
            "n_days": n_days,
            "avg_games": g["games"].mean(),
            "mean_p56": g["p56"].mean(),
            "n_high_per_day": g["p56"].apply(lambda s: (s >= P56_HIGH).sum()) / n_days,
        }
    )
    tbl["mean_p56_shrunk"] = shrink(tbl["mean_p56"], tbl["n_machine_days"], float(df["p56"].var()))
    tbl["rank_mean_p56"] = tbl["mean_p56"].rank(ascending=False).astype(int)
    return tbl.reset_index()


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    dd_all, wd_all, summary = [], [], []

    for hall, fname in HALLS.items():
        path = PROJECT_ROOT / "db" / fname
        if not path.exists():
            print(f"[skip] {hall}: DBなし")
            continue
        df = load_hall(path)
        if df.empty or df["date"].nunique() < 60:
            print(f"[skip] {hall}: ジャグ行が不足（{len(df)}行）")
            continue

        dd = axis_scores(df, "dd").assign(hall=hall)
        wd = axis_scores(df, "weekday").assign(hall=hall)
        dd_all.append(dd)
        wd_all.append(wd)

        sz = df.groupby("strong_zorome")["p56"].mean()
        summary.append(
            {
                "hall": hall,
                "n_rows": len(df),
                "n_days": df["date"].nunique(),
                "n_jug_machines": df["machine_number"].nunique(),
                "avg_games": df["games"].mean(),
                "mean_p56_all": df["p56"].mean(),
                # 下位DDの水準 = ユーザー仮説「平日にも高設定を入れるホールか」の指標
                "mean_p56_bottom10dd": dd.nsmallest(10, "mean_p56")["mean_p56"].mean(),
                "mean_p56_top3dd": dd.nlargest(3, "mean_p56")["mean_p56"].mean(),
                "spread_top3_minus_bottom10": (
                    dd.nlargest(3, "mean_p56")["mean_p56"].mean() - dd.nsmallest(10, "mean_p56")["mean_p56"].mean()
                ),
                "strong_zorome_lift": sz.get(True, np.nan) - sz.get(False, np.nan),
            }
        )
        print(f"[ok] {hall}: {len(df):,}行 / {df['date'].nunique()}日 / ジャグ{df['machine_number'].nunique()}台")

    dd_df = pd.concat(dd_all, ignore_index=True)
    wd_df = pd.concat(wd_all, ignore_index=True)
    sm_df = pd.DataFrame(summary)
    dd_df.to_csv(OUT_DIR / "dd_scores_by_hall.csv", index=False, encoding="utf-8-sig")
    wd_df.to_csv(OUT_DIR / "weekday_scores_by_hall.csv", index=False, encoding="utf-8-sig")
    sm_df.to_csv(OUT_DIR / "hall_summary.csv", index=False, encoding="utf-8-sig")

    pd.set_option("display.width", 220)
    print("\n=== ホール別サマリー（mean_p56: ジャグ台×日の P(設定5-6) 平均） ===")
    print("※ 一様事前の p56 は情報ゼロなら 0.333。低いほど「実際は低設定が多い」")
    print(sm_df.to_string(index=False, float_format=lambda v: f"{v:,.4f}"))

    print("\n=== 楽園: DD別スコア（mean_p56 降順） ===")
    r = dd_df.loc[dd_df["hall"] == "楽園蒲田"].sort_values("mean_p56", ascending=False)
    print(
        r[["dd", "n_days", "avg_games", "mean_p56", "mean_p56_shrunk", "n_high_per_day", "rank_mean_p56"]].to_string(
            index=False, float_format=lambda v: f"{v:,.4f}"
        )
    )

    print("\n=== 各ホールの上位5DD（mean_p56） ===")
    for hall in sm_df["hall"]:
        top = dd_df.loc[dd_df["hall"] == hall].nlargest(5, "mean_p56")
        print(f"  {hall:8s}: " + ", ".join(f"DD{int(t.dd)}({t.mean_p56:.3f})" for t in top.itertuples()))

    print("\n=== 曜日別 mean_p56 ===")
    piv = wd_df.pivot(index="hall", columns="weekday", values="mean_p56")
    piv.columns = [WEEKDAY_JA[c] for c in piv.columns]
    print(piv.to_string(float_format=lambda v: f"{v:,.4f}"))

    print(f"\n出力: {OUT_DIR}")


if __name__ == "__main__":
    main()
