"""既知ルールの効果量が時間とともに動いているか（非定常性）を検定する。

背景:
    これまでの検証は全期間をプールして「効果の平均」を推定してきた。もしホール側が
    2〜3ヶ月単位で方針を入れ替えているなら、符号の違う期間が打ち消し合って
    「効果ゼロ」という結論が出る。それは分散が大きいのではなく推定量のバイアスであり、
    別の問題として切り分ける必要がある。

    ここで検定するのは「ルールが当たるか」ではなく「ルールの当たり方が時期によって
    変わるか」。前者が偽でも後者が真なら、短期追随の設計に進む価値がある。

統計量:
    日次エッジ系列に幅 window 日のローリング窓をかけ、窓平均の標準偏差を取る。
    レジームが入れ替わるなら窓平均は大きく振れ、この値が膨らむ。

帰無仮説:
    「効果は時期によらず一定で、観測される振れは全てノイズ」。
    日付と値の対応を循環ブロック置換（block 日単位）で壊して再計算する。
    ブロック単位にするのは、同じ台が連日選ばれることによる短期の系列相関が
    それ自体で窓平均を振らせるため。これを保存しないと帰無分布が狭くなりすぎ、
    ただの自己相関をレジーム変化と誤認する。

使い方:
    venv\\Scripts\\python.exe -m backtest.regime backtest/prereg/*.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from backtest.prereg import PreRegistration
from backtest.run_backtest import run

RESULT_DIR = Path(__file__).resolve().parent / "results" / "regime"


def daily_edge_series(picks: pd.DataFrame, column: str) -> pd.Series:
    """1日1値のエッジ系列。同日に複数台選ぶルールは平均に潰す。"""
    s = picks.groupby("date")[column].mean().dropna()
    s.index = pd.to_datetime(s.index, format="%Y%m%d")
    return s.sort_index()


def rolling_window_means(s: pd.Series, window_days: int, step_days: int, min_obs: int) -> pd.DataFrame:
    """カレンダー日基準のローリング窓平均。

    営業日ベースの `rolling(n)` ではなく日数で切る。エントリー日が DD 限定の
    ルールでは1窓あたりの観測数が大きく変わるため、n_obs も一緒に返して
    サンプル数の薄い窓を後から判別できるようにする。
    """
    if s.empty:
        return pd.DataFrame(columns=["window_end", "mean", "n_obs"])
    start, end = s.index.min(), s.index.max()
    rows = []
    cur = start + pd.Timedelta(days=window_days)
    while cur <= end:
        lo = cur - pd.Timedelta(days=window_days)
        chunk = s[(s.index >= lo) & (s.index < cur)]
        if len(chunk) >= min_obs:
            rows.append({"window_end": cur, "mean": float(chunk.mean()), "n_obs": len(chunk)})
        cur += pd.Timedelta(days=step_days)
    return pd.DataFrame(rows)


def dispersion(values: np.ndarray) -> float:
    """窓平均のばらつき。窓が2個未満なら定義できない。"""
    return float(np.std(values, ddof=1)) if len(values) >= 2 else float("nan")


def circular_block_permute(values: np.ndarray, block: int, rng: np.random.Generator) -> np.ndarray:
    """循環ブロック置換。長さを保ったままブロック順序だけ入れ替える。

    ブロック内の並びを保つので短期の系列相関は生き残り、ブロックをまたぐ
    長期の構造（＝レジーム）だけが壊れる。
    """
    n = len(values)
    n_blocks = int(np.ceil(n / block))
    starts = rng.integers(0, n, size=n_blocks)
    idx = (starts[:, None] + np.arange(block)[None, :]).reshape(-1)[:n] % n
    return values[idx]


def test_nonstationarity(
    s: pd.Series,
    window_days: int,
    step_days: int,
    min_obs: int,
    block: int,
    n_perm: int,
    seed: int,
) -> dict:
    obs = rolling_window_means(s, window_days, step_days, min_obs)
    if len(obs) < 2:
        return {"n_windows": int(len(obs)), "note": "窓が足りず検定不能"}

    obs_disp = dispersion(obs["mean"].to_numpy())
    rng = np.random.default_rng(seed)
    values = s.to_numpy()
    null = []
    for _ in range(n_perm):
        perm = pd.Series(circular_block_permute(values, block, rng), index=s.index)
        w = rolling_window_means(perm, window_days, step_days, min_obs)
        d = dispersion(w["mean"].to_numpy())
        if not np.isnan(d):
            null.append(d)
    null_arr = np.array(null)
    if not len(null_arr):
        return {"n_windows": int(len(obs)), "note": "帰無分布が空"}

    # 片側。観測が帰無分布の上側に外れるほど「時期で変わっている」証拠。
    p = float((null_arr >= obs_disp).mean())
    return {
        "n_windows": int(len(obs)),
        "window_days": window_days,
        "step_days": step_days,
        "obs_dispersion": round(obs_disp, 1),
        "null_dispersion_median": round(float(np.median(null_arr)), 1),
        "null_dispersion_p95": round(float(np.percentile(null_arr, 95)), 1),
        "dispersion_ratio": round(obs_disp / float(np.median(null_arr)), 2),
        "p_value": p,
        "window_mean_min": round(float(obs["mean"].min()), 1),
        "window_mean_max": round(float(obs["mean"].max()), 1),
        "window_mean_overall": round(float(obs["mean"].mean()), 1),
        # 正負それぞれの窓の割合。レジーム反転が起きていれば両方が無視できない大きさになる。
        "positive_window_rate": round(float((obs["mean"] > 0).mean()), 3),
    }


def analyze(reg: PreRegistration, picks: pd.DataFrame, args: argparse.Namespace) -> dict:
    out: dict = {
        "rule_id": reg.rule_id,
        "hall": reg.hall,
        "freeze_hash": reg.freeze_hash(),
        "eval_range": f"{reg.eval_start}-{reg.eval_end}",
        "n_picks": int(len(picks)),
    }
    if picks.empty:
        out["note"] = "選択0件"
        return out

    for column in ("edge", "edge_vs_excluded"):
        s = daily_edge_series(picks, column)
        out[column] = {
            "n_days": int(len(s)),
            "overall_mean": round(float(s.mean()), 1),
        }
        for window_days in args.windows:
            out[column][f"w{window_days}"] = test_nonstationarity(
                s,
                window_days=window_days,
                step_days=args.step,
                min_obs=args.min_obs,
                block=args.block,
                n_perm=args.n_perm,
                seed=args.seed,
            )
    return out


def write_series(reg: PreRegistration, picks: pd.DataFrame, args, outdir: Path) -> None:
    """可視化・目視確認用に窓平均の推移そのものを CSV で残す。"""
    if picks.empty:
        return
    frames = []
    for column in ("edge", "edge_vs_excluded"):
        s = daily_edge_series(picks, column)
        for window_days in args.windows:
            w = rolling_window_means(s, window_days, args.step, args.min_obs)
            if w.empty:
                continue
            w["metric"] = column
            w["window_days"] = window_days
            frames.append(w)
    if frames:
        pd.concat(frames).to_csv(outdir / f"{reg.rule_id}__rolling.csv", index=False, encoding="utf-8-sig")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="既知ルールの効果量の非定常性検定")
    p.add_argument("prereg", nargs="+", help="事前登録 JSON のパス（複数可）")
    p.add_argument("--windows", type=int, nargs="+", default=[60, 90])
    p.add_argument("--step", type=int, default=7, help="窓をずらす日数")
    p.add_argument("--min-obs", type=int, default=10, help="1窓に要求する観測日数")
    p.add_argument("--block", type=int, default=7, help="置換のブロック長（日）")
    p.add_argument("--n-perm", type=int, default=500)
    p.add_argument("--seed", type=int, default=20260723)
    p.add_argument("--start", help="eval_start を上書き（全期間で見たいとき）")
    p.add_argument("--end", help="eval_end を上書き")
    p.add_argument("--outdir", default=str(RESULT_DIR))
    args = p.parse_args(argv)

    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    results = []
    for path in args.prereg:
        reg = PreRegistration.load(path)
        # 診断目的なので評価期間の上書きを許す。凍結ハッシュは元定義のものを
        # 記録し、これが事前登録の検証ではないことを結果側で判別できるようにする。
        if args.start or args.end:
            reg.eval_start = args.start or reg.eval_start
            reg.eval_end = args.end or reg.eval_end
            reg.validate()
        picks, _ = run(reg)
        res = analyze(reg, picks, args)
        write_series(reg, picks, args, outdir)
        results.append(res)
        print(json.dumps(res, ensure_ascii=False, indent=2))

    (outdir / "nonstationarity.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
