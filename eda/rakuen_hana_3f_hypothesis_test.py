"""噂「3Fハナハナは毎日1台は高設定」をモデルとして立て、観測と突き合わせる.

なぜ追加検証が要るか:
    `eda/rakuen_hana_3f_verification.py` で「p_high>=0.8 の台が出た日は27日中8日」と出た。
    だがハナハナは設定差が小さく（King REG 設定1=1/489 vs 設定4=1/390）、2700G では
    REG 期待値が 5.5 vs 6.9 しかない。つまり**設定4を設定4と断定できるだけの検出力が無い**。
    「確定台が毎日出ない」ことは「毎日は入っていない」の証明にならない。

    そこで噂を生成モデルとして立て、観測データがどちらの世界から来たかを比べる:

      H0  全台が低設定の混合（ホール実績機械割に合わせて較正）。高設定は入っていない。
      H1  毎日ちょうど1台が最高設定(King=6 / NewKingV=V)、残りは H0 と同じ。
      H1b 毎日ちょうど1台が設定4、残りは H0 と同じ。（噂の弱い版）

    判定統計量は「日ごとの最大 p_high」の平均。1台だけ高設定が居る世界では毎日
    どこかの台の尤度が跳ねるので最大値の分布が右にずれる。確定判定の有無に依らず、
    検出力を捨てずに済む。

    さらにジャグラーにも同じ枠組みを当て、「ハナは扱いがいいのか」を
    検出力（G数・台数）の差を除いた上で比較する。

使い方:
    venv\\Scripts\\python.exe -m eda.rakuen_hana_3f_hypothesis_test
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from eda.rakuen_hana_3f_verification import (  # noqa: E402
    DATA_END,
    MOVE_DATE,
    PRE_START,
    P_HIGH_THRESHOLD,
    SPECS,
    daily_stats,
    load,
    posterior_high,
)

N_SIM = 3000
SEED = 20260805


def calibrate_low_mix(df: pd.DataFrame) -> dict[str, dict[int, float]]:
    """観測の実績機械割に合うよう、低設定側(設定1と設定3)の混合比をファミリ毎に決める.

    実績機械割 = w1*payout1 + (1-w1)*payout3 を満たす w1 を解く。
    中間値を作るための最小限のパラメータ化で、設定2は使わない。
    実績が payout1 を下回る場合は全台設定1に丸める（clip）。
    """
    mix = {}
    for fam, sub in df.groupby("family"):
        spec = SPECS[fam]["settings"]
        lo, hi = min(spec), min(3, max(spec))
        p_lo, p_hi = spec[lo][2], spec[hi][2]
        actual = 100 * (1 + sub["diff_coins_normalized"].sum() / (3 * sub["games_normalized"].sum()))
        w_lo = float(np.clip((p_hi - actual) / (p_hi - p_lo), 0.0, 1.0))
        mix[fam] = {lo: w_lo, hi: 1.0 - w_lo}
    return mix


def simulate(
    df: pd.DataFrame,
    mix: dict,
    rng: np.random.Generator,
    planted_setting: int | None = None,
) -> pd.DataFrame:
    """混合から設定を引いて BB/RB を生成。planted_setting があれば毎日1台だけ差し替える。"""
    sim = df.copy()
    fams = df["family"].to_numpy()
    settings = np.empty(len(df), dtype=int)
    for fam in np.unique(fams):
        pos = np.flatnonzero(fams == fam)
        keys = list(mix[fam])
        settings[pos] = rng.choice(keys, size=len(pos), p=[mix[fam][k] for k in keys])

    if planted_setting is not None:
        # 日ごとに1台をランダムに選び、その機種で planted_setting（上限は最高設定）に置く
        for _, idx in df.groupby("date").groups.items():
            pos = df.index.get_indexer(idx)
            pick = int(rng.choice(pos))
            spec = SPECS[fams[pick]]["settings"]
            settings[pick] = min(max(spec), planted_setting)

    g = df["games_normalized"].to_numpy(int)
    p_bb = np.array([SPECS[f]["settings"][s][0] for f, s in zip(fams, settings)])
    p_rb = np.array([SPECS[f]["settings"][s][1] for f, s in zip(fams, settings)])
    sim["bb_count"] = rng.binomial(g, p_bb)
    sim["rb_count"] = rng.binomial(g, p_rb)
    return sim


def run_scenario(df: pd.DataFrame, mix: dict, planted: int | None, n_sim: int) -> dict:
    rng = np.random.default_rng(SEED)
    acc = {"日別最大p_high平均": [], "高設定判定台数/日": [], "1台以上の日の割合": [], "mean_p_high": []}
    for _ in range(n_sim):
        sim = simulate(df, mix, rng, planted)
        sim["p_high"] = posterior_high(sim)
        d = daily_stats(sim)
        acc["日別最大p_high平均"].append(d["max_p"].mean())
        acc["高設定判定台数/日"].append(d["n_high"].mean())
        acc["1台以上の日の割合"].append((d["n_high"] >= 1).mean())
        acc["mean_p_high"].append(sim["p_high"].mean())
    return {k: np.asarray(v) for k, v in acc.items()}


def observed(df: pd.DataFrame) -> dict:
    d = daily_stats(df)
    return {
        "日別最大p_high平均": d["max_p"].mean(),
        "高設定判定台数/日": d["n_high"].mean(),
        "1台以上の日の割合": (d["n_high"] >= 1).mean(),
        "mean_p_high": df["p_high"].mean(),
    }


def compare(label: str, df: pd.DataFrame, n_sim: int = N_SIM) -> None:
    mix = calibrate_low_mix(df)
    obs = observed(df)
    print(f"\n{'=' * 100}\n{label}   (延べ台日={len(df)}, 日数={df['date'].nunique()})")
    print("較正した低設定混合（実績機械割に一致させた H0 の世界）:")
    for fam, w in mix.items():
        print(f"    {fam:26s} " + "  ".join(f"設定{k}:{v:.2f}" for k, v in w.items()))
    scenarios = {
        name: run_scenario(df, mix, planted, n_sim)
        for name, planted in [
            ("H0 高設定なし", None),
            ("H1b 毎日1台=設定4", 4),
            ("H1 毎日1台=最高設定", 99),
        ]
    }
    rows = []
    for st in observed(df):
        row = {"統計量": st, "観測": f"{obs[st]:.3f}"}
        for name, res in scenarios.items():
            arr = res[st]
            lo, hi = np.percentile(arr, [2.5, 97.5])
            row[name] = f"{np.median(arr):.3f} [{lo:.3f},{hi:.3f}]"
        rows.append(row)
    print(pd.DataFrame(rows).set_index("統計量").to_string())


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    pd.set_option("display.width", 260)
    pd.set_option("display.max_colwidth", 40)

    df = load(PRE_START, DATA_END)
    df["p_high"] = posterior_high(df)

    hana_post = df[(df["date"] >= MOVE_DATE) & df["is_hana"]].reset_index(drop=True)
    hana_pre = df[(df["date"] < MOVE_DATE) & df["is_hana"]].reset_index(drop=True)
    jug_post = df[(df["date"] >= MOVE_DATE) & (~df["is_hana"]) & df["family"].notna()].reset_index(drop=True)

    print(f"判定閾値 p_high >= {P_HIGH_THRESHOLD} / 高設定 = 設定4以上")
    print("各セルは シミュレーション中央値 [95%区間]。観測がどの列の区間に入るかで判定する。")
    compare(f"ハナハナ 3F  {MOVE_DATE}-{DATA_END}", hana_post)
    compare(f"ハナハナ 1F  {PRE_START}-{MOVE_DATE}", hana_pre)
    compare(f"ジャグラー  {MOVE_DATE}-{DATA_END}（対照群）", jug_post, n_sim=300)


if __name__ == "__main__":
    main()
