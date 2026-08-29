"""ボーナス確率ベースの高設定投入検出器。

なぜ差枚系スコア（announce.py の gratio_mean_diff）と別に要るか:
    2026-08-27/28 の楽園蒲田 ToLOVEるダークネスで、取材アカウント(Zeno)が両日とも
    【全台】(8/27) / 【1/2】8台中4台(8/28) と発表しているにも関わらず、
    gratio_mean_diff は 8/27 が -306、8/28 が 915 で **2日とも閾値1800に届かなかった**。

    原因は指標の構造にある。score = G比 × 平均差枚 であり、平均差枚は
        平均差枚 ≒ 3 × (機械割 - 1) × 回転数
    なので **score ∝ 出率エッジ × G² / pool** となる。設定が入っていても
    (a) 回転数が足りない低稼働日、(b) AT機で単に引けなかった日 は閾値に届かない。

    実際 ToLOVEるの BB確率は 8/27 が 1/136.0、8/28 が 1/127.4 で
    両日に有意差が無く(z=-0.62, p=0.538)、8月の非対象26日 1/154.7 に対しては
    8/28 が z=+2.27 (p=0.023) と有意に高かった。**差枚では見えず、
    ボーナス確率では見えた。**

    既存の `2026-08-27-rakuen-nibuichi-art-overdispersion` は「機種内で割れているか」
    (過分散)を見る検定だった。本モジュールが見るのは別の量で、
    **機種全体の水準が、その機種自身の平常時より高いか** である。両者は補完関係にある。

設計上の判断:
    - 比較対象は「ホール平均」でも「スペック表」でもなく **その機種自身の直近N日** とする。
      ボーナス確率の絶対値は機種ごとに桁違いなので横断比較は無意味であり、
      スペック表は収録機種が限られる(JUGGLER_FAMILY_SPECS は14ファミリーのみで
      ハナハナ系すら未収録)。自己ベースラインなら全機種に適用できる。
    - ノーマル機(jug/hana/oki/bt)は **RB回数**、それ以外(AT機)は **BB+RB の合計** を使う。
      ノーマル機は bb/rb 両方が埋まっており、設定差は主にRB確率に出る。
      AT機は **機種によって bb_count 側か rb_count 側のどちらか一方にしか値が入らない**
      （2026-08-27 楽園蒲田の実測: ToLOVEるダークネスは BB=218/RB=0、
       モンスターハンターライズは BB=0/RB=79、からくりサーカス2は BB=0/RB=122）。
      「AT機は常にBB」と決め打つと、RB側に入る機種が全滅してベースラインがゼロになり、
      **黙って除外される**。合計を取れば列の入り方に依存しない。
    - **稼働台数フィルタを必須にする。** 2026-08-28 のうみねこのなく頃に2 は
      4台中2台が 202G/212G とほぼ未稼働で、残る1台の大勝ちにより
      gratio_mean_diff 2466 で「全台系HIT」と判定されたが、現場情報では低設定だった。
      min_machines だけでは実質2台の機種を弾けない。
"""

from __future__ import annotations

import argparse
import json
import sys

import numpy as np
import pandas as pd
from scipy import stats

from backtest.run_backtest import load_frame

# ノーマル機はRB確率に設定差が出る。AT機はbb/rbのどちらに入るかが機種依存なので合計する。
NORMAL_FLAGS = ("jug_flag", "hana_flag", "oki_flag", "bt_flag")


def _bonus_counts(rows: pd.DataFrame) -> tuple[pd.Series, str]:
    """その機種でボーナス確率を測るのに使う回数列と、その名前を返す。

    ノーマル機は RB のみ。AT機は bb/rb のどちらに入るかが機種依存なので合計する
    （モジュール docstring 参照。決め打つと機種が黙って落ちる）。
    """
    is_normal = any(rows[f].fillna(0).max() == 1 for f in NORMAL_FLAGS)
    if is_normal:
        return rows["rb_count"].fillna(0), "RB"
    return rows["bb_count"].fillna(0) + rows["rb_count"].fillna(0), "BB+RB"


def _two_proportion_z(k1: float, n1: float, k2: float, n2: float) -> tuple[float, float]:
    """2標本の比率検定。k=ボーナス回数, n=回転数。返り値は (z, 両側p)。"""
    if n1 <= 0 or n2 <= 0 or (k1 + k2) <= 0:
        return float("nan"), float("nan")
    p_pool = (k1 + k2) / (n1 + n2)
    se = np.sqrt(p_pool * (1 - p_pool) * (1 / n1 + 1 / n2))
    if se <= 0:
        return float("nan"), float("nan")
    z = (k1 / n1 - k2 / n2) / se
    return float(z), float(2 * (1 - stats.norm.cdf(abs(z))))


def bonus_rate_scores(
    df: pd.DataFrame,
    target_date: str,
    baseline_days: int = 30,
    min_machines: int = 3,
    min_live: int = 3,
    min_live_games: int = 1000,
    min_total_games: int = 6000,
    exclude_dates: list[str] | None = None,
) -> pd.DataFrame:
    """対象日の各機種について、ボーナス確率が自分の平常時より高いかを検定する。

    Args:
        df: load_frame の返り値（`ds` 列は内部で作る）。
        target_date: YYYYMMDD。
        baseline_days: 比較に使う直近日数（対象日は含まない）。
        min_machines: 設置台数の下限。
        min_live: `min_live_games` 以上回った台数の下限。**うみねこ型の偽陽性対策**。
        min_total_games: 対象日の機種合計回転数の下限。
        exclude_dates: ベースラインから外す日（取材日など既知の投入日）。

    Returns:
        z 降順の DataFrame。`z` が正で `p` が小さいほど「平常時より当たっている」。
        除外された機種は `df.attrs["excluded"]` に理由付きで入る（黙って落とさない）。
    """
    d = df.copy()
    d["ds"] = d["date"].astype(str)
    day = d[d["ds"] == target_date]
    if day.empty:
        raise ValueError(f"{target_date} のデータが無い")

    end = pd.Timestamp(target_date) - pd.Timedelta(days=1)
    start = end - pd.Timedelta(days=baseline_days - 1)
    base_all = d[(d["dt"] >= start) & (d["dt"] <= end)]
    if exclude_dates:
        base_all = base_all[~base_all["ds"].isin(exclude_dates)]

    out = []
    excluded: list[dict] = []
    for name, rows in day.groupby("machine_name"):
        n_machines = rows["machine_number"].nunique()
        n_live = int((rows["games_normalized"] >= min_live_games).sum())
        total_games = float(rows["games_normalized"].sum())

        def drop(reason: str) -> None:
            # 除外は必ず記録する。黙って落とすと「対象外」と「該当なし」が区別できない。
            excluded.append(
                {
                    "machine_name": name,
                    "reason": reason,
                    "n_machines": n_machines,
                    "n_live": n_live,
                    "games": total_games,
                }
            )

        if n_machines < min_machines:
            drop(f"設置台数 {n_machines} < {min_machines}")
            continue
        if n_live < min_live:
            drop(f"稼働台数 {n_live} < {min_live}（{min_live_games}G以上の台）")
            continue
        if total_games < min_total_games:
            drop(f"合計回転数 {total_games:.0f} < {min_total_games}")
            continue

        day_counts, metric = _bonus_counts(rows)
        k_day = float(day_counts.sum())
        base = base_all[base_all["machine_name"] == name]
        n_base = float(base["games_normalized"].sum())
        k_base = float(_bonus_counts(base)[0].sum()) if not base.empty else 0.0
        if n_base <= 0:
            drop("ベースライン期間に回転数が無い")
            continue
        if k_base <= 0:
            drop("ベースライン期間のボーナス回数が0（列の入り方を確認すること）")
            continue

        z, p = _two_proportion_z(k_day, total_games, k_base, n_base)

        # 機種内が均一か（全台系 vs ニブイチの切り分け）。
        g = rows["games_normalized"].to_numpy(dtype=float)
        k = day_counts.to_numpy(dtype=float)
        rate = k_day / total_games if total_games else 0.0
        exp = g * rate
        ok = exp > 0
        if ok.sum() >= 2:
            chi = float(((k[ok] - exp[ok]) ** 2 / exp[ok]).sum())
            p_disp = float(1 - stats.chi2.cdf(chi, ok.sum() - 1))
        else:
            p_disp = float("nan")

        diff = rows["diff_coins_normalized"]
        payout = (3 * total_games + diff.sum()) / (3 * total_games) if total_games else float("nan")
        out.append(
            {
                "machine_name": name,
                "metric": metric,
                "n_machines": n_machines,
                "n_live": n_live,
                "games": total_games,
                "bonus": k_day,
                "rate_1_in": total_games / k_day if k_day else float("inf"),
                "base_1_in": n_base / k_base,
                "base_days": int(base["ds"].nunique()),
                "z": z,
                "p": p,
                "p_dispersion": p_disp,
                "payout_pct": payout * 100,
                "mean_diff": float(diff.mean()),
            }
        )
    res = pd.DataFrame(out).sort_values("z", ascending=False).reset_index(drop=True)
    res.attrs["excluded"] = excluded
    return res


def main() -> int:
    ap = argparse.ArgumentParser(description="ボーナス確率ベースの高設定投入検出")
    ap.add_argument("hall")
    ap.add_argument("--date", required=True, help="YYYYMMDD")
    ap.add_argument("--baseline-days", type=int, default=30)
    ap.add_argument("--min-machines", type=int, default=3)
    ap.add_argument("--min-live", type=int, default=3)
    ap.add_argument("--min-live-games", type=int, default=1000)
    ap.add_argument("--min-total-games", type=int, default=6000)
    ap.add_argument("--exclude", nargs="*", default=None, help="ベースラインから外す日")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    df = load_frame(args.hall)
    res = bonus_rate_scores(
        df,
        args.date,
        baseline_days=args.baseline_days,
        min_machines=args.min_machines,
        min_live=args.min_live,
        min_live_games=args.min_live_games,
        min_total_games=args.min_total_games,
        exclude_dates=args.exclude,
    )
    if args.json:
        print(
            json.dumps(
                {"scored": res.to_dict("records"), "excluded": res.attrs.get("excluded", [])},
                ensure_ascii=False,
                indent=2,
                default=float,
            )
        )
        return 0

    print(f"=== {args.hall} {args.date} ボーナス確率 vs 直近{args.baseline_days}日の自機平常時 ===")
    print(
        f"{'機種':28s} {'指標':>3s} {'台':>3s} {'稼働':>4s} {'合計G':>8s} "
        f"{'当日':>9s} {'平常時':>9s} {'z':>6s} {'p':>7s} {'均一p':>6s} {'出率':>7s}"
    )
    for _, r in res.iterrows():
        mark = " ★" if r.p < 0.05 and r.z > 0 else (" ◇" if r.p < 0.15 and r.z > 0 else "")
        print(
            f"{str(r.machine_name)[:26]:28s} {r.metric:>3s} {int(r.n_machines):3d} {int(r.n_live):4d} "
            f"{r.games:8,.0f} {'1/' + format(r.rate_1_in, '.1f'):>9s} {'1/' + format(r.base_1_in, '.1f'):>9s} "
            f"{r.z:+6.2f} {r.p:7.4f} {r.p_dispersion:6.3f} {r.payout_pct:6.2f}%{mark}"
        )
    print("\n★ p<0.05 かつ z>0（平常時より有意に当たっている） / ◇ p<0.15")
    print("均一p: 機種内のボーナス回数がポアソンと整合するか。小さいほど機種内で割れている（ニブイチ寄り）")

    ex = res.attrs.get("excluded", [])
    if ex:
        print(f"\n--- 除外 {len(ex)}機種（採点対象外。『該当なし』ではない） ---")
        for e in sorted(ex, key=lambda x: -x["games"])[:15]:
            print(f"  {str(e['machine_name'])[:28]:30s} {e['reason']}")
        if len(ex) > 15:
            print(f"  ... 他 {len(ex) - 15}機種")
    return 0


if __name__ == "__main__":
    sys.exit(main())
