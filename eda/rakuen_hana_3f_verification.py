"""楽園蒲田のハナハナ「3F移動後は毎日1台は高設定が入る / 扱いがいい」噂の検証.

背景:
    ハナハナは 2026-07-06 に 1F(1100-1129, 20台) から 3F(3166-3181, 16台) へ移動した。

    「毎日1台」は**最大値の主張**なので平均差枚や平均機械割では検証できない
    （15台が設定1で1台だけ設定6でも主張は真になる）。またホール全体との比較は
    AT機の分散が大きく 104%超率を押し上げるため不公平になる。

方針:
    ハナハナはノーマルAタイプなので BB/RB の二項尤度から設定事後分布が出せる
    （ml/experiments/jug_rb_setting_prediction と同じ手法）。台×日ごとに
    p_high = P(設定4以上) を出し、

      1. 日ごとの「p_high >= 0.8」台数と最大 p_high を出す
      2. **全台が設定1だったらどう見えるか**をモンテカルロで出して観測と比較する
         （16台 × 2700G もあれば、偶然だけで毎日1台は「高設定に見える」台が出る。
           これを潰さないと噂は自動的に「真」になる）
      3. 移動前(1F)の同じ統計と比べ、移動で何が変わったのかを見る
      4. 同ホールのジャグラー（同じノーマルA）と比べて「扱いがいい」かを見る
      5. 真なら狙い方: 台番号・島内位置・DD・曜日・前日からの継続性を出す

    事前分布は一様（既存パイプライン踏襲）。真の高設定率より甘いので p_high を
    過大評価する方向に効く。だからこそ「設定1のみ」の帰無分布との比較が要る
    （同じ甘さが帰無側にもかかるので相殺される）。

スペック出典:
    キングハナハナ-30      … eda/highsetting_predictability_hana_at.SPEC_MASTER を再利用
                             （1geki.jp 由来。chonborista.com / pachiseven.jp とも一致を確認）
    ニューキングハナハナV-30 … chonborista.com（2026-08-05取得）。設定1〜4 と設定V の5段階。
                             p-town.dmm.com の「機械割 97%〜108%」と両端一致で裏取り。

使い方:
    venv\\Scripts\\python.exe -m eda.rakuen_hana_3f_verification
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from eda.highsetting_predictability_hana_at import SPEC_MASTER  # noqa: E402
from ml.experiments.jug_rb_setting_prediction.config import (  # noqa: E402
    JUGGLER_FAMILY_MATCHERS,
    JUGGLER_FAMILY_SPECS,
)

DB = PROJECT_ROOT / "db" / "楽園蒲田店.db"
OUT_DIR = Path(__file__).parent / "results" / "rakuen_hana_3f"

MOVE_DATE = "20260706"  # ハナハナが 3F に出現した最初の日
PRE_START = "20260406"  # 移動前の比較期間（移動後 27日 の3倍強を確保）
DATA_END = "20260803"

P_HIGH_THRESHOLD = 0.80  # 「高設定確定扱い」の事後確率閾値（既存パイプライン踏襲）
N_SIM = 2000

# --- スペック（設定 -> (BB確率, RB確率, 公表機械割)） ---------------------------
_KING = SPEC_MASTER["キングハナハナ-30"]["settings"]
_KING_PAYOUT = {1: 97.0, 2: 99.0, 3: 101.0, 4: 104.0, 5: 107.0, 6: 110.0}

SPECS: dict[str, dict] = {
    "キングハナハナ-30": {
        "settings": {s: (bb, rb, _KING_PAYOUT[s]) for s, (bb, rb) in _KING.items()},
        "high_settings": {4, 5, 6},
    },
    # 設定5 は「設定V」（パイオニアの5段階設定）
    "ニューキングハナハナV‐30": {
        "settings": {
            1: (1 / 299.0, 1 / 496.0, 97.0),
            2: (1 / 291.0, 1 / 471.0, 99.0),
            3: (1 / 281.0, 1 / 442.0, 101.0),
            4: (1 / 268.0, 1 / 409.0, 104.0),
            5: (1 / 253.0, 1 / 372.0, 108.0),
        },
        "high_settings": {4, 5},
    },
}
HANA_NAMES = tuple(SPECS)

# ジャグラーも同じ枠組みに載せる（「扱いがいい」の対照群）
for _key, _spec in JUGGLER_FAMILY_SPECS.items():
    SPECS[_key] = {
        "settings": {
            s: (v["bb_probability"], v["rb_probability"], v["payout_rate"]) for s, v in _spec["settings"].items()
        },
        "high_settings": {4, 5, 6},
    }


def assign_family(names: pd.Series) -> pd.Series:
    """機種名 -> SPECS のキー。ハナハナは完全一致、ジャグは既存マッチャに委譲。"""

    def one(n: str) -> str | None:
        if n in HANA_NAMES:
            return n
        for key, kw in JUGGLER_FAMILY_MATCHERS:
            if kw in n:
                return key
        return None

    return names.map(one)


def _log_binom_kernel(k: np.ndarray, n: np.ndarray, p: float) -> np.ndarray:
    """二項対数尤度の設定依存部分のみ（組合せ係数は設定間で共通なので省く）。"""
    return k * np.log(p) + (n - k) * np.log1p(-p)


def posterior_high(df: pd.DataFrame) -> pd.Series:
    """台×日ごとに P(設定4以上) を返す。一様事前・BB/RB独立近似。"""
    out = np.full(len(df), np.nan)
    for fam, idx in df.groupby("family").groups.items():
        spec = SPECS[fam]
        settings = sorted(spec["settings"])
        pos = df.index.get_indexer(idx)
        g = df["games_normalized"].to_numpy(float)[pos]
        bb = df["bb_count"].to_numpy(float)[pos]
        rb = df["rb_count"].to_numpy(float)[pos]
        ll = np.stack(
            [
                _log_binom_kernel(bb, g, spec["settings"][s][0]) + _log_binom_kernel(rb, g, spec["settings"][s][1])
                for s in settings
            ]
        )
        ll -= ll.max(axis=0, keepdims=True)
        post = np.exp(ll)
        post /= post.sum(axis=0, keepdims=True)
        mask = np.array([s in spec["high_settings"] for s in settings])
        out[pos] = post[mask].sum(axis=0)
    return pd.Series(out, index=df.index, name="p_high")


def simulate_all_setting1(df: pd.DataFrame, rng: np.random.Generator) -> pd.DataFrame:
    """観測と同じG数で BB/RB を生成し直した「もし全台が設定1だったら」データ。"""
    sim = df.copy()
    bb = np.empty(len(df))
    rb = np.empty(len(df))
    for fam, idx in df.groupby("family").groups.items():
        pos = df.index.get_indexer(idx)
        p_bb, p_rb, _ = SPECS[fam]["settings"][min(SPECS[fam]["settings"])]
        g = df["games_normalized"].to_numpy(int)[pos]
        bb[pos] = rng.binomial(g, p_bb)
        rb[pos] = rng.binomial(g, p_rb)
    sim["bb_count"] = bb
    sim["rb_count"] = rb
    return sim


def daily_stats(df: pd.DataFrame) -> pd.DataFrame:
    return df.groupby("date").agg(
        n_machines=("p_high", "size"),
        n_high=("p_high", lambda s: int((s >= P_HIGH_THRESHOLD).sum())),
        max_p=("p_high", "max"),
        mean_p=("p_high", "mean"),
    )


def null_distribution(df: pd.DataFrame, n_sim: int, seed: int = 20260805) -> dict:
    """全台設定1のときの各統計量の帰無分布。"""
    rng = np.random.default_rng(seed)
    acc = {"n_high_per_day": [], "frac_days_any": [], "mean_p_high": []}
    base = df.drop(columns=[c for c in ("p_high",) if c in df.columns])
    for _ in range(n_sim):
        sim = simulate_all_setting1(base, rng)
        sim["p_high"] = posterior_high(sim)
        d = daily_stats(sim)
        acc["n_high_per_day"].append(d["n_high"].mean())
        acc["frac_days_any"].append((d["n_high"] >= 1).mean())
        acc["mean_p_high"].append(sim["p_high"].mean())
    return {k: np.asarray(v) for k, v in acc.items()}


def load(start: str, end: str) -> pd.DataFrame:
    con = sqlite3.connect(DB)
    try:
        df = pd.read_sql(
            "select date, machine_number, machine_name, games_normalized, "
            "diff_coins_normalized, bb_count, rb_count "
            "from machine_detailed_results where date >= ? and date <= ?",
            con,
            params=(start, end),
        )
    finally:
        con.close()
    # 20260706（3F移動当日）は全587台が games=0 で、差枚だけホール平均 -6142 が
    # 全行に書かれている不良日。G=0 の行は機械割の分母に入らないのに分子だけ汚すので落とす。
    df = df[df["games_normalized"] > 0].reset_index(drop=True)
    df["family"] = assign_family(df["machine_name"])
    df["is_hana"] = df["machine_name"].isin(HANA_NAMES)
    df["floor"] = df["machine_number"] // 1000
    df["payout"] = 1 + df["diff_coins_normalized"] / (3 * df["games_normalized"].clip(lower=1))
    return df


def describe(label: str, df: pd.DataFrame) -> pd.Series:
    d = daily_stats(df)
    return pd.Series(
        {
            "日数": len(d),
            "台数/日": d["n_machines"].mean(),
            "延べ台日": len(df),
            "平均G": df["games_normalized"].mean(),
            "機械割(実績)": 100 * (1 + df["diff_coins_normalized"].sum() / (3 * df["games_normalized"].sum())),
            "mean_p_high": df["p_high"].mean(),
            "高設定判定台数/日": d["n_high"].mean(),
            "1台以上の日の割合": (d["n_high"] >= 1).mean(),
            "2台以上の日の割合": (d["n_high"] >= 2).mean(),
        },
        name=label,
    )


def report_null(label: str, scored: pd.DataFrame) -> None:
    null = null_distribution(scored, N_SIM)
    d = daily_stats(scored)
    obs = {
        "高設定判定台数/日": d["n_high"].mean(),
        "1台以上の日の割合": (d["n_high"] >= 1).mean(),
        "mean_p_high": scored["p_high"].mean(),
    }
    keys = {
        "高設定判定台数/日": "n_high_per_day",
        "1台以上の日の割合": "frac_days_any",
        "mean_p_high": "mean_p_high",
    }
    print(f"\n-- {label} --")
    for name, o in obs.items():
        arr = null[keys[name]]
        lo, hi = np.percentile(arr, [2.5, 97.5])
        print(
            f"  {name:20s} 観測={o:6.3f}  帰無中央={np.median(arr):6.3f} "
            f"帰無95%=[{lo:.3f}, {hi:.3f}]  p(片側)={(arr >= o).mean():.4f}"
        )


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    pd.set_option("display.width", 240)
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    df = load(PRE_START, DATA_END)
    df["p_high"] = posterior_high(df)

    post = df[(df["date"] >= MOVE_DATE) & df["is_hana"]].reset_index(drop=True)
    pre = df[(df["date"] < MOVE_DATE) & df["is_hana"]].reset_index(drop=True)
    jug_post = df[(df["date"] >= MOVE_DATE) & (~df["is_hana"]) & df["family"].notna()].reset_index(drop=True)
    jug_pre = df[(df["date"] < MOVE_DATE) & (~df["is_hana"]) & df["family"].notna()].reset_index(drop=True)

    print("=" * 104)
    print(f"楽園蒲田 ハナハナ 3F移動検証  (移動日 {MOVE_DATE} / データ最終日 {DATA_END})")
    print(f"高設定 = 設定4以上（=公表機械割104%以上） / 判定閾値 p_high >= {P_HIGH_THRESHOLD}")
    print("=" * 104)

    print("\n【1】水準比較")
    print(
        pd.DataFrame(
            [
                describe(f"ハナ 3F ({MOVE_DATE}-)", post),
                describe(f"ハナ 1F ({PRE_START}-)", pre),
                describe("ジャグ 移動後", jug_post),
                describe("ジャグ 移動前", jug_pre),
            ]
        ).T.to_string(float_format=lambda v: f"{v:.3f}")
    )

    print("\n【2】帰無分布『全台が設定1』を同じG数で再生成（観測が偶然で説明できるか）")
    report_null("ハナ 3F", post)
    report_null("ハナ 1F", pre)

    print("\n【3】3F移動後の日別内訳")
    d = daily_stats(post)
    con = sqlite3.connect(DB)
    hall = pd.read_sql(
        "select date, day_of_week, avg_diff_per_machine from daily_hall_summary where date >= ?",
        con,
        params=(MOVE_DATE,),
    ).set_index("date")
    con.close()
    d = d.join(hall)
    d["dd"] = [int(x[6:8]) for x in d.index]
    d["ハナ平均差枚"] = post.groupby("date")["diff_coins_normalized"].mean()
    best = post.loc[post.groupby("date")["p_high"].idxmax()].set_index("date")
    d["最良台"] = best["machine_number"]
    d["最良台差枚"] = best["diff_coins_normalized"]
    high_list = (
        post[post["p_high"] >= P_HIGH_THRESHOLD]
        .groupby("date")["machine_number"]
        .apply(lambda s: ",".join(map(str, sorted(s))))
    )
    d["高設定判定台"] = high_list
    print(d.to_string(float_format=lambda v: f"{v:.3f}"))

    print("\n【4】3F移動後 台番号別（27日集計）")
    gsum = post.groupby("machine_number")[["games_normalized", "diff_coins_normalized"]].sum()
    per = post.groupby(["machine_number", "machine_name"]).agg(
        日数=("p_high", "size"),
        平均G=("games_normalized", "mean"),
        総差枚=("diff_coins_normalized", "sum"),
        mean_p_high=("p_high", "mean"),
        高設定日数=("p_high", lambda s: int((s >= P_HIGH_THRESHOLD).sum())),
    )
    per["機械割"] = (
        (100 * (1 + gsum["diff_coins_normalized"] / (3 * gsum["games_normalized"])))
        .reindex(per.index.get_level_values(0))
        .to_numpy()
    )
    print(per.sort_values("mean_p_high", ascending=False).to_string(float_format=lambda v: f"{v:.3f}"))

    print("\n【5】狙い方の材料: 前日高設定 -> 翌日も高設定 か（据え置き検定）")
    piv = post.pivot_table(index="date", columns="machine_number", values="p_high")
    prev = (piv.shift(1) >= P_HIGH_THRESHOLD).to_numpy()
    cur = (piv >= P_HIGH_THRESHOLD).to_numpy()
    ok = ~np.isnan(piv.to_numpy()) & ~np.isnan(piv.shift(1).to_numpy())
    a = int((prev & cur & ok).sum())
    b = int((prev & ~cur & ok).sum())
    c = int((~prev & cur & ok).sum())
    dd_ = int((~prev & ~cur & ok).sum())
    print(f"  前日高設定 -> 翌日も高設定: {a}/{a + b} = {a / max(a + b, 1):.3f}")
    print(f"  前日低め   -> 翌日高設定: {c}/{c + dd_} = {c / max(c + dd_, 1):.3f}")

    post.to_csv(OUT_DIR / "hana_3f_scored.csv", index=False, encoding="utf-8-sig")
    d.to_csv(OUT_DIR / "hana_3f_daily.csv", encoding="utf-8-sig")
    per.to_csv(OUT_DIR / "hana_3f_by_machine.csv", encoding="utf-8-sig")
    print(f"\n出力: {OUT_DIR}")


if __name__ == "__main__":
    main()
