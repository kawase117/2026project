"""機種×月×設置コホート の「同日同カテゴリ比エッジ」表。

なぜ要るか:
    2026-07-27、楽園蒲田のネオアイムジャグラーEX が同日ジャグ全台平均に対して
    2026/03 +0.00pp → 04 +0.30 → 05 +0.40 → 06 +0.82 → 07 +1.08pp と単調上昇していた。
    これは eda/hall_monthly_matrix.py のカテゴリ粒度（JUG全体）では見えず、
    eda/machine_cards.py の台粒度でも「どの機種が伸びているか」は読めなかった。
    機種粒度が両者の隙間に落ちていた。

設置コホートを分ける理由:
    同じ楽園ネオアイムでも、初出日は 20250929(13台) / 20251016(7台) / 20251104(7台) /
    20260706(35台) の4つに割れる。前3つは1回のロールアウトの段階的増台だが、
    最後の35台は8ヶ月空いた別世代の増台で、新装出玉サービスの減衰局面にある
    （初日103.9% → 直近99〜100%）。混ぜると月の数字が甘く出る。

    そこで「同一機種内で、台ごとの初出日を gap<=N日 でクラスタリング」してコホートとする。
    実測（全9ホール1495機種）では初出日が4種類以上に割れる機種が 395件(26%) あり、
    素朴に初出日そのままで分けるとコホートが砕ける。N=30 で 228件まで減る。

    N=30 の根拠（gap分布に自然な切れ目が無いこと）:
        DB開始日を除いた初出日gap 2262件の分布は
        1日 0.2% / 2-3日 0.3% / 4-7日 2.6% / 8-14日 15.5% / 15-30日 20.9% /
        31-60日 22.1% / 61-120日 22.5% / 121日以上 15.9%。
        「登録ずれの1-3日の山」は存在せず（合計0.5%）、そこから単調に増えるだけ。
        したがって N=3 は 99.5% の gap を境界にしてしまい「初出日そのまま」と同義になる。
        N=30 は物理的な切れ目ではなく「1回のロールアウトはひと月以内に終わる」という
        運用上の仮定であり、それ以上の意味は無い。

    ★コホートは均質なグループではない:
        楽園ネオアイムの 20251016(7台) と 20251104(7台) は、同じ島 section 1170-1183 の
        前半 1170-1176 と後半 1177-1183 だった。2026/07 のエッジは前半 -0.13pp、
        後半 +1.36pp と割れており、これは設置時期ではなく島内の位置で決まっている
        （5週間離れた 20250929 の別島 1184-1196 は +1.40pp で後半と同値）。
        日付コホートは新装/世代の軸しか捉えない。machine_number_range 列を必ず読み、
        島を割っていないか確認すること。位置の効果は section / rank_from_* で別途見る。

エッジの主指標について:
    baseline は「同日・同カテゴリの全台」で、自機種を含む。シェアが大きい機種ほど
    自分がbaselineに入りエッジが機械的に圧縮される。実測では楽園ネオアイム 2026/07 が
    シェア48.2%で edge +1.11pp(自分込み) vs +2.18pp(自分除外) と 1.07pp 違った。
    backtest/run_backtest.py が mean_edge_per_pick / mean_edge_vs_excluded /
    mean_pick_share の3点セットで扱う規約に揃え、**主指標は edge_pp（自分込み）**、
    share_of_category を必ず併記、edge_vs_excluded_pp は補助とする。
    share が大きいほど edge_vs_excluded は機械的に大きく出るので、単独で読まないこと。

★この表は探索用であって判定用ではない:
    9ホール × 各20〜60機種 × 11ヶ月 のセルを走査すれば、CIがゼロを跨がないセルは
    偶然でも大量に出る。FDR補正はあえてかけていない。補正した「有意」も
    in-sample の呪いからは逃れられず、事前登録の代わりにはならないからである
    （backtest/prereg.py の思想を参照）。
    ここで見つけたものは backtest/prereg/ に事前登録し、フォワードでのみ判定すること。

実行:
    venv\\Scripts\\python.exe -m eda.model_monthly_edge
    venv\\Scripts\\python.exe -m eda.model_monthly_edge --show 楽園 --category JUG
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

from eda.briefing_common import all_halls, iron_machines, load_hall_frame, payout_w, use_utf8_stdout

OUT_DIR = Path(__file__).resolve().parents[1] / "eda" / "results" / "briefing"
OUT_PATH = OUT_DIR / "model_monthly_edge.csv"

DEFAULT_COHORT_GAP_DAYS = 30
_SEED = 20260727
CAVEAT = "探索用。多重比較補正なし。判定は事前登録+フォワードのみ（backtest/prereg.py）。"


def assign_cohort(frame: pd.DataFrame, gap_days: int = DEFAULT_COHORT_GAP_DAYS) -> pd.Series:
    """台ごとの初出日を機種内で gap<=N日 にクラスタリングし、コホート初日を返す。

    数日のデータ欠損で別コホートに割れないよう、また段階的増台が1世代に収まるよう、
    初出日そのものではなく「隣接する初出日との間隔」で切る。
    """
    first = frame.groupby(["machine_name", "machine_number"])["date"].min().rename("first_date")
    out: dict[tuple, str] = {}
    for name, s in first.groupby(level="machine_name"):
        uniq = sorted(s.unique())
        ts = pd.to_datetime(pd.Series(uniq), format="%Y%m%d")
        # 直前の初出日から gap_days を超えて空いたら新しいコホート。
        # ★先頭は必ず新コホート。diff() の先頭 NaN に .gt() を掛けると False になり
        #   fillna(True) が効かないため、明示的に True を置く（これを忘れると
        #   各機種の最初のコホートが None になり groupby から丸ごと落ちる）。
        new = ts.diff().dt.days.gt(gap_days).to_numpy(copy=True)
        new[0] = True
        label = pd.Series(np.where(new, uniq, None), index=uniq).ffill()
        for num, fd in s.droplevel("machine_name").items():
            out[(name, num)] = label[fd]
    idx = pd.MultiIndex.from_arrays([frame["machine_name"], frame["machine_number"]])
    return pd.Series(idx.map(out), index=frame.index, name="cohort_first_date")


def _daily_payout(frame: pd.DataFrame) -> pd.Series:
    """日次 games加重機械割。groupby.apply は遅いので和からベクトル化して求める。

    セル数が 2700 超あり、素朴に apply するとベースラインを機種ごとに
    作り直して 10 分以上かかる。ベースラインは pool ごとに1回だけ作ること。
    """
    g = frame.groupby("date")["games"].sum()
    d = frame.groupby("date")["diff"].sum()
    return ((g * 3 + d) / (g * 3) * 100).where(g > 0)


def _edge(sub_daily: pd.Series, base_daily: pd.Series) -> pd.Series:
    return (sub_daily - base_daily).dropna()


def _block_ci(values: np.ndarray, n_boot: int = 1000, block: int = 7) -> tuple[float, float]:
    """日次エッジ系列の平均の 95%CI（循環ブロックなしの移動ブロックbootstrap）。

    セルが 2700 超あるため、ブロック連結を Python ループでやると全体で 10 分以上かかる。
    開始位置の行列を作って一括インデックスする。
    """
    v = np.asarray(values, dtype=float)
    n = len(v)
    if n < block * 2:
        return (float("nan"), float("nan"))
    rng = np.random.default_rng(_SEED)
    nb = int(np.ceil(n / block))
    starts = rng.integers(0, n - block + 1, size=(n_boot, nb))
    idx = (starts[:, :, None] + np.arange(block)[None, None, :]).reshape(n_boot, -1)[:, :n]
    means = v[idx].mean(axis=1)
    return (float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5)))


def build(
    halls: list[str] | None = None,
    *,
    date_from: str | None = "20250101",
    cohort_gap_days: int = DEFAULT_COHORT_GAP_DAYS,
    min_machine_days: int = 20,
) -> pd.DataFrame:
    rows: list[dict] = []
    for hall in halls or all_halls():
        raw = load_hall_frame(hall, date_from=date_from)
        if raw.empty:
            continue
        db_min = raw["date"].min()
        raw = raw[raw["is_valid_games"]].copy()
        raw["cohort_first_date"] = assign_cohort(raw, cohort_gap_days)
        hall_label = raw["hall"].iloc[0]

        for (ym, cat), pool in raw.groupby(["year_month", "category"]):
            if cat == "UNKNOWN":
                continue
            base_daily = _daily_payout(pool)  # ★pool ごとに1回だけ
            rest_daily: dict[str, pd.Series] = {}
            for (name, cohort), sub in pool.groupby(["machine_name", "cohort_first_date"]):
                if len(sub) < min_machine_days:
                    continue
                sub_daily = _daily_payout(sub)
                edge = _edge(sub_daily, base_daily)
                lo, hi = _block_ci(edge.values)
                share = sub["games"].sum() / pool["games"].sum()
                if name not in rest_daily:
                    rest = pool[pool["machine_name"] != name]
                    rest_daily[name] = _daily_payout(rest) if len(rest) else pd.Series(dtype=float)
                edge_ex = _edge(sub_daily, rest_daily[name]).mean() if len(rest_daily[name]) else float("nan")

                # 少数台依存チェック。除外するのは分子（自機種）のみで baseline は動かさない。
                # baseline は「そのカテゴリから適当に1台選んだ期待値」であり、
                # どの台を分析から外したかとは無関係だからである。
                per_machine = sub.groupby("machine_number")["diff"].mean().sort_values(ascending=False)
                excl = {}
                for k in (1, 2, 3):
                    kept = sub[~sub["machine_number"].isin(per_machine.head(k).index)]
                    excl[f"edge_excl_top{k}"] = (
                        _edge(_daily_payout(kept), base_daily).mean() if kept["machine_number"].nunique() else np.nan
                    )

                pre_existing = str(cohort) == db_min
                days_since = (
                    pd.to_datetime(sub["date"], format="%Y%m%d") - pd.to_datetime(str(cohort), format="%Y%m%d")
                ).dt.days
                nums = sub["machine_number"]
                iron = iron_machines(hall)
                rows.append(
                    {
                        "hall": hall_label,
                        "year_month": ym,
                        "machine_name": name,
                        "category": cat,
                        "cohort_first_date": cohort,
                        # DB開始日に張り付くコホートは真のデビュー日が不明（それ以前から設置）
                        "is_pre_existing": pre_existing,
                        # ★台番号レンジは必ず読むこと。日付コホートが「島の前半/後半」を
                        # 割っているだけのことがある。実例: 楽園ネオアイムの 20251016(7台) と
                        # 20251104(7台) は同じ section 1170-1183 の前半 1170-1176 と
                        # 後半 1177-1183 で、性能差は設置時期ではなく島内の位置で決まっていた。
                        "machine_number_range": f"{nums.min()}-{nums.max()}",
                        "n_machines": nums.nunique(),
                        "n_machine_days": len(sub),
                        "n_days": sub["date"].nunique(),
                        "total_games": int(sub["games"].sum()),
                        "payout_w": payout_w(sub),
                        "baseline_payout": payout_w(pool),
                        "edge_pp": edge.mean(),
                        "edge_ci95_lo": lo,
                        "edge_ci95_hi": hi,
                        "edge_vs_excluded_pp": edge_ex,
                        "share_of_category": share,
                        # share が大きいほど edge_vs_excluded は「残り少数機種との差」になり
                        # 機械的に膨らむ。単独で読まないための注記。
                        "baseline_note": (
                            "excluded_baseline_unstable_high_share" if share >= 0.30 else "excluded_baseline_reference"
                        ),
                        "category_n_machines": pool["machine_number"].nunique(),
                        "category_n_models": pool["machine_name"].nunique(),
                        "win_rate": (sub["diff"] > 0).mean(),
                        **excl,
                        # DB開始日に張り付くコホートはデビュー日が不明なので日数を出さない
                        # （出すと「DB開始からの日数」を機齢と誤読する）。
                        "days_since_debut_median": np.nan if pre_existing else float(days_since.median()),
                        # 生存バイアス: 成績の悪い台が月中に撤去されると残存コホートが甘く見える
                        "cohort_last_date": sub["date"].max(),
                        "active_until_month_end": sub["date"].max() == pool["date"].max(),
                        "n_iron_machine_days": int(nums.isin(iron).sum()),
                        "caveat": CAVEAT,
                    }
                )
    out = pd.DataFrame(rows)
    if out.empty:
        return out
    return out.sort_values(
        ["hall", "year_month", "category", "edge_pp"], ascending=[True, True, True, False]
    ).reset_index(drop=True)


def main() -> None:
    use_utf8_stdout()
    ap = argparse.ArgumentParser(description="機種×月×設置コホート のエッジ表")
    ap.add_argument("--date-from", default="20250101")
    ap.add_argument("--cohort-gap-days", type=int, default=DEFAULT_COHORT_GAP_DAYS)
    ap.add_argument("--min-machine-days", type=int, default=20)
    ap.add_argument("--show", default=None)
    ap.add_argument("--category", default=None)
    ap.add_argument("--months", type=int, default=3, help="--show 時に表示する直近月数")
    args = ap.parse_args()

    out = build(
        date_from=args.date_from,
        cohort_gap_days=args.cohort_gap_days,
        min_machine_days=args.min_machine_days,
    )
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out.to_csv(OUT_PATH, index=False, encoding="utf-8-sig")
    print(f"書き出し: {OUT_PATH}  ({len(out)} セル / {out['hall'].nunique()} ホール)")
    print(f"★{CAVEAT}")
    sig = out[(out["edge_ci95_lo"] > 0) & out["edge_ci95_lo"].notna()]
    print(f"CI下限>0 のセル: {len(sig)} / {len(out)} — 偶然でもこの程度は出る。入口としてのみ使うこと。")

    if args.show:
        sub = out[out["hall"] == args.show]
        if args.category:
            sub = sub[sub["category"] == args.category]
        months = sorted(sub["year_month"].unique())[-args.months :]
        sub = sub[sub["year_month"].isin(months)]
        cols = [
            "year_month",
            "machine_name",
            "cohort_first_date",
            "n_machines",
            "payout_w",
            "edge_pp",
            "edge_ci95_lo",
            "edge_ci95_hi",
            "share_of_category",
            "win_rate",
            "edge_excl_top3",
            "days_since_debut_median",
        ]
        print(f"\n### {args.show}" + (f" / {args.category}" if args.category else ""))
        print(sub[cols].to_string(index=False, float_format=lambda x: f"{x:8.2f}"))


if __name__ == "__main__":
    main()
