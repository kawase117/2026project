"""凍結済み事前登録ルールを履歴データに対して walk-forward で回す。

漏洩防止の要:
    対象日 d の選択に使える情報は date < d のものだけ。lookback 窓は
    [d - lookback_days, d) の半開区間で、d 自身は決して含めない。
    実績（diff_coins_normalized）は選択後にのみ参照する。

エッジの定義:
    ホール全体が出た日／絞られた日の影響を除くため、絶対差枚ではなく
    「同日・同 eligible プールの平均との差」をエッジとする。これは
    「その日その条件で適当に1台選んだ場合」に対する上乗せに相当する。

使い方:
    venv\\Scripts\\python.exe -m backtest.run_backtest backtest/prereg/xxx.json
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from backtest.prereg import PreRegistration

REPO_ROOT = Path(__file__).resolve().parent.parent
DB_DIR = REPO_ROOT / "db"
RESULT_DIR = Path(__file__).resolve().parent / "results"

# 差枚→円。等価交換を既定とし、実際の交換率はレポート時のパラメータとして
# 扱う（ルール本体を汚さない）。
DEFAULT_COIN_YEN = 20.0


def load_frame(hall: str) -> pd.DataFrame:
    """ホール1件分の台別日次結果を、機種フラグ・レイアウトと結合して返す。"""
    db_path = DB_DIR / f"{hall}.db"
    if not db_path.exists():
        raise FileNotFoundError(f"DB が見つからない: {db_path}")

    with sqlite3.connect(db_path) as conn:
        df = pd.read_sql(
            """
            SELECT r.date, r.machine_name, r.machine_number, r.last_digit,
                   r.is_zorome, r.games_normalized, r.diff_coins_normalized,
                   r.rb_probability_decimal, r.rb_count, r.bb_count,
                   m.jug_flag, m.hana_flag, m.oki_flag, m.bt_flag,
                   l.section, l.rank_from_aisle, l.rank_from_min, l.rank_from_max
            FROM machine_detailed_results r
            LEFT JOIN machine_master m
                   ON r.machine_name = m.machine_name_normalized
            -- 位置は日付でマッチさせる。machine_layout は単一スナップショットで
            -- 日付次元を持たないため、改装をまたぐと工事後の位置が工事前のデータに
            -- 遡って適用され、効果が消えたように見える（楽園 2026-07-06、
            -- FINDINGS 追試10）。machine_layout_history が正本。
            LEFT JOIN machine_layout_history l
                   ON r.machine_number = l.machine_number
                  AND r.date >= l.valid_from
                  AND (l.valid_to IS NULL OR r.date <= l.valid_to)
            """,
            conn,
        )

    df["dt"] = pd.to_datetime(df["date"], format="%Y%m%d")
    # RB確率はカウントから直接計算する。`rb_probability_decimal` は
    # rb_count == 0 の行で NULL になる列で、これを notna() で絞ると
    # 「RBが1回も出なかった日」が非ランダムに脱落する（回転数の少ない台ほど
    # 多く落ちるので、その台の平均RB確率が過大になる）。9ホール全てで
    # NaN率 == RB0回率が一致することを確認済み。詳細:
    # backtest/results/regime/FINDINGS.md 追試9。
    df["rb_rate"] = np.where(df["games_normalized"] > 0, df["rb_count"] / df["games_normalized"], np.nan)
    # BB+RB。ジャグ・ハナハナでは設定が両方を同じ向きに動かすので、
    # 片方だけ見ると符号が食い違って判断を誤る（FINDINGS 追試9）。
    # AT機は bb_count/rb_count が概念的に対応しないため意味を持たない。
    df["bonus_rate"] = np.where(
        df["games_normalized"] > 0,
        (df["bb_count"] + df["rb_count"]) / df["games_normalized"],
        np.nan,
    )
    # 機械割の近似。3枚掛け前提。
    df["payout"] = np.where(
        df["games_normalized"] > 0,
        (df["games_normalized"] * 3 + df["diff_coins_normalized"]) / (df["games_normalized"] * 3),
        np.nan,
    )
    return df


def apply_eligibility(df: pd.DataFrame, eligibility: dict) -> pd.DataFrame:
    """事前登録の eligibility を適用する。

    値の形は3通り: スカラー（一致）、リスト（いずれかに一致）、
    {"min": a, "max": b}（範囲。片側のみでも可）。
    """
    out = df
    for field, cond in eligibility.items():
        if isinstance(cond, dict):
            # 未知キーや空 dict を黙って no-op にすると、typo が
            # 「条件が緩いだけの別ルール」として静かに評価されてしまう。
            unknown = set(cond) - {"min", "max"}
            if unknown or not cond:
                raise ValueError(
                    f"eligibility[{field!r}] の範囲指定が不正: {cond!r}（min / max の少なくとも一方が必要）"
                )
            if "min" in cond:
                out = out[out[field] >= cond["min"]]
            if "max" in cond:
                out = out[out[field] <= cond["max"]]
        elif isinstance(cond, list):
            out = out[out[field].isin(cond)]
        else:
            out = out[out[field] == cond]
    return out


def restrict_to_current_machine(hist: pd.DataFrame, today: pd.DataFrame) -> pd.DataFrame:
    """台入替をまたいだ履歴を落とす。

    同じ machine_number でも期間中に別機種へ入れ替わることが実際にある
    （みとや 39/266台、蒲田7 104/715台が30日窓内で機種変更）。
    台番号だけで集計すると入替前の機種の成績が現在の台のスコアに混入するため、
    対象日に設置されている機種と一致する履歴行だけを残す。
    """
    current = today[["machine_number", "machine_name"]].drop_duplicates()
    return hist.merge(current, on=["machine_number", "machine_name"], how="inner")


def score_history(hist: pd.DataFrame, score: str) -> pd.Series:
    """lookback 窓の履歴から台ごとのスコアを返す。大きいほど良い向きに揃える。"""
    g = hist.groupby("machine_number")
    if score == "hist_mean_diff":
        return g["diff_coins_normalized"].mean()
    if score == "hist_hit104_rate":
        return g["payout"].apply(lambda s: (s >= 1.04).mean())
    if score == "hist_mean_rb_prob":
        # rb_rate = rb_count / games。高いほど高設定寄り。
        # 注意: 生値なので機種横断で比較すると機種差を拾う（下の _model_z 版を参照）。
        return g["rb_rate"].mean()
    if score == "hist_mean_rb_prob_model_z":
        # ジャグシリーズは機種ごとにRB確率のベースが違う（instinct:
        # juggler-104pct-threshold-meaning-by-model）。生値のランキングは
        # 「高設定台」ではなく「ベースの高い機種」を選んでしまう。
        # 同一機種内の標準化スコアに直してから台ごとに平均する。
        h = hist.copy()
        stats = h.groupby("machine_name")["rb_rate"].agg(["mean", "std"])
        h = h.join(stats, on="machine_name")
        # 機種内に分散がない（1日しかない等）場合は比較不能なので落とす。
        h = h[h["std"] > 0]
        h["z"] = (h["rb_rate"] - h["mean"]) / h["std"]
        return h.groupby("machine_number")["z"].mean()
    raise ValueError(f"scoring 不可の score: {score!r}")


def select_eval_days(eligible_all: pd.DataFrame, reg: PreRegistration) -> list[str]:
    days = sorted(d for d in eligible_all["date"].unique() if reg.eval_start <= d <= reg.eval_end)
    if reg.entry_days.get("dd"):
        allowed = set(reg.entry_days["dd"])
        days = [d for d in days if int(d[6:8]) in allowed]
    if reg.entry_days.get("weekday"):
        allowed_wd = set(reg.entry_days["weekday"])
        days = [d for d in days if pd.Timestamp(d).weekday() in allowed_wd]
    return days


def _data_fingerprint(df: pd.DataFrame, reg: PreRegistration) -> dict:
    """評価期間のデータスナップショット指紋。

    freeze_hash は *ルール定義* のハッシュであって、データの版を含まない。
    そのため DB が再スクレイプ・バックフィルで更新されると、同じ freeze_hash の
    結果ファイルが黙って別の数字に置き換わる。実際 2026-07-27 に
    mitoya_jug_eventdd_rb_top3 を再実行したところ、picks 225件・baseline が同一のまま
    mean_diff_per_pick が 171.9 → 196.6 に動いた。指紋があれば「ルールは同じだが
    データが変わった」と判別できる。
    """
    ev = df[(df["date"] >= reg.eval_start) & (df["date"] <= reg.eval_end)]
    return {
        "n_rows": int(len(ev)),
        "sum_games": int(ev["games_normalized"].sum()),
        "sum_diff": int(ev["diff_coins_normalized"].sum()),
        "max_date_in_db": str(df["date"].max()) if len(df) else None,
    }


def run(reg: PreRegistration) -> tuple[pd.DataFrame, dict]:
    """1本の事前登録ルールを walk-forward で評価する。

    Returns:
        (picks, summary) — picks は1行=1日1台の選択と実績、summary は集計。
    """
    df = load_frame(reg.hall)
    fingerprint = _data_fingerprint(df, reg)
    # universe = ルールが無ければ選んでいた母集団。baseline はここから取る。
    # min_games_today は選択時点で未知の情報なので既定 0（フィルタしない）。
    universe_all = apply_eligibility(df, reg.universe)
    if reg.min_games_today > 0:
        universe_all = universe_all[universe_all["games_normalized"] >= reg.min_games_today]
    eligible_all = apply_eligibility(universe_all, reg.eligibility)
    # 履歴側のみ min_games で絞る。これは対象日より前の情報なので漏洩しない。
    history_all = eligible_all[eligible_all["games_normalized"] >= reg.min_games]
    eval_days = select_eval_days(eligible_all, reg)

    rows: list[dict] = []
    skipped_no_history = 0
    for day in eval_days:
        d0 = pd.Timestamp(day)
        today = eligible_all[eligible_all["date"] == day]
        if today.empty:
            continue

        # baseline は同日の universe 平均 = その日その母集団から適当に1台選んだ期待値。
        universe_today = universe_all[universe_all["date"] == day]
        baseline = universe_today["diff_coins_normalized"].mean()

        if reg.score == "none":
            # フィルタのみの効果を見る。eligible プール全体を選択として扱う。
            picked = today
        else:
            lo = d0 - pd.Timedelta(days=reg.lookback_days)
            # 半開区間 [lo, d0): 対象日は絶対に含めない。
            hist = history_all[(history_all["dt"] >= lo) & (history_all["dt"] < d0)]
            hist = restrict_to_current_machine(hist, today)
            if hist.empty:
                skipped_no_history += 1
                continue

            counts = hist.groupby("machine_number").size()
            usable = counts[counts >= reg.min_history_days].index
            scores = score_history(hist[hist["machine_number"].isin(usable)], reg.score)
            scores = scores[scores.index.isin(today["machine_number"])].dropna()
            if scores.empty:
                skipped_no_history += 1
                continue

            top = scores.sort_values(ascending=False).head(reg.top_n).index
            picked = today[today["machine_number"].isin(top)]

        # picks を除いた母集団の平均。edge（vs universe）は picks 自身を
        # baseline に含むため、選択比率が高いルールでは効果が縮んで見える。
        # 物理的な効果量を見るにはこちらの対比を使う。
        picked_numbers = set(picked["machine_number"])
        excluded = universe_today[~universe_today["machine_number"].isin(picked_numbers)]
        excluded_mean = float(excluded["diff_coins_normalized"].mean()) if not excluded.empty else float("nan")

        for _, r in picked.iterrows():
            rows.append(
                {
                    "date": day,
                    "machine_number": r["machine_number"],
                    "machine_name": r["machine_name"],
                    "games": r["games_normalized"],
                    "diff": r["diff_coins_normalized"],
                    "payout": r["payout"],
                    "day_baseline": baseline,
                    "edge": r["diff_coins_normalized"] - baseline,
                    "edge_vs_excluded": r["diff_coins_normalized"] - excluded_mean,
                    "pool_size": len(today),
                    "universe_size": int((universe_all["date"] == day).sum()),
                }
            )

    picks = pd.DataFrame(rows)
    summary = summarize(reg, picks, n_eval_days=len(eval_days), skipped=skipped_no_history, fingerprint=fingerprint)
    return picks, summary


def block_bootstrap_means(daily: np.ndarray, n_boot: int = 10_000, seed: int = 20260723, block: int = 1) -> np.ndarray:
    """日次系列のブートストラップ平均の分布を返す（長さ n_boot）。

    2つの期間の効果を引き算した「差の CI」が必要な場面（死亡検知）では
    平均の CI だけでは足りず、分布そのものが要る。`bootstrap_ci` は
    この関数の分位点を取るだけの薄いラッパーであり、実装は常にここ1箇所。

    Args:
        block: ブロック長。1 なら iid リサンプル。同じ台が連日選ばれ続けることで
            日次エッジには正の系列相関があり、iid だと有効サンプル数を過大評価して
            CI が狭く出る。block > 1 の moving block bootstrap で相関を保存する。
    """
    n = len(daily)
    if n < 2:
        return np.array([])
    rng = np.random.default_rng(seed)

    if block <= 1:
        idx = rng.integers(0, n, size=(n_boot, n))
        return daily[idx].mean(axis=1)

    n_blocks = int(np.ceil(n / block))
    starts = rng.integers(0, max(n - block + 1, 1), size=(n_boot, n_blocks))
    offsets = np.arange(block)
    # (n_boot, n_blocks, block) -> 連結して先頭 n 個を使う
    idx = (starts[:, :, None] + offsets[None, None, :]).reshape(n_boot, -1)[:, :n]
    return daily[np.clip(idx, 0, n - 1)].mean(axis=1)


def bootstrap_ci(daily: np.ndarray, n_boot: int = 10_000, seed: int = 20260723, block: int = 1) -> tuple[float, float]:
    """日次系列の平均の 95% CI。"""
    means = block_bootstrap_means(daily, n_boot=n_boot, seed=seed, block=block)
    if means.size == 0:
        return (float("nan"), float("nan"))
    return (float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5)))


def _period_slice_stats(picks: pd.DataFrame) -> dict:
    """期間分割サマリー1区間分。summarize 本体と同じ日次集計・同じCI手続きを使う。"""
    if picks.empty:
        return {"n_days_traded": 0, "n_picks": 0, "note": "この区間に選択なし"}
    per_day = picks.groupby("date")["edge"].mean()
    lo, hi = bootstrap_ci(per_day.to_numpy(), block=7)
    return {
        "n_days_traded": int(len(per_day)),
        "n_picks": int(len(picks)),
        "mean_edge_per_pick": round(float(picks["edge"].mean()), 1),
        "edge_ci95_block7": [round(lo, 1), round(hi, 1)],
        "edge_positive_day_rate": round(float((per_day > 0).mean()), 3),
    }


def period_split_summary(picks: pd.DataFrame, split_date: str) -> dict:
    """split_date を境に before/after へ分けたエッジのサマリー。

    ★これは事後（post-hoc）の部分集団解析である。凍結ハッシュ・prereg JSON・
    既存の全期間サマリーは一切変更しない。ルールの採否根拠にしてはならず、
    「変化点の前後で効果が同じか」を目視するための材料に限る。
    分割日を後から動かして都合のよい区間を探すのは事前登録の趣旨に反する。
    店長交代・改装など *外部から与えられた既知の変化点* にのみ使うこと
    （feedback-hall-regime-needs-external-event-calendar）。
    """
    return {
        "split_date": split_date,
        "caveat": "post-hoc 部分集団解析。採否根拠にしないこと。既知の外部変化点にのみ使う。",
        "before": _period_slice_stats(picks[picks["date"] < split_date]),
        "after": _period_slice_stats(picks[picks["date"] >= split_date]),
    }


def summarize(
    reg: PreRegistration,
    picks: pd.DataFrame,
    n_eval_days: int,
    skipped: int,
    *,
    fingerprint: dict | None = None,
) -> dict:
    base = {
        "rule_id": reg.rule_id,
        "hall": reg.hall,
        "freeze_hash": reg.freeze_hash(),
        # freeze_hash はルール定義のみのハッシュ。データの版は下記の指紋で見る。
        "data_fingerprint": fingerprint,
        "hypothesis": reg.hypothesis,
        "source_instinct": reg.source_instinct,
        "success_criterion": reg.success_criterion,
        "eval_range": f"{reg.eval_start}-{reg.eval_end}",
        "n_eval_days": n_eval_days,
        "n_days_skipped_no_history": skipped,
    }
    if picks.empty:
        base["n_picks"] = 0
        base["note"] = "選択が0件。eligibility か min_history_days が厳しすぎる可能性。"
        return base

    per_day = picks.groupby("date").agg(
        edge=("edge", "mean"),
        edge_ex=("edge_vs_excluded", "mean"),
        diff=("diff", "mean"),
    )
    edge_arr = per_day["edge"].to_numpy()
    lo, hi = bootstrap_ci(edge_arr)
    lo_b, hi_b = bootstrap_ci(edge_arr, block=7)
    ex_arr = per_day["edge_ex"].dropna().to_numpy()
    lo_x, hi_x = bootstrap_ci(ex_arr, block=7)

    base.update(
        {
            "n_days_traded": int(len(per_day)),
            "n_picks": int(len(picks)),
            "mean_games_per_pick": round(float(picks["games"].mean()), 1),
            # 当日ほぼ回っていない台を掴んだ割合。高いと実運用では座れていない。
            "pick_low_games_rate": round(float((picks["games"] < 1000).mean()), 3),
            "mean_diff_per_pick": round(float(picks["diff"].mean()), 1),
            "mean_baseline": round(float(picks["day_baseline"].mean()), 1),
            "mean_edge_per_pick": round(float(picks["edge"].mean()), 1),
            "edge_ci95": [round(lo, 1), round(hi, 1)],
            # 系列相関を保存した 7日ブロック版。判定にはこちらを使う。
            "edge_ci95_block7": [round(lo_b, 1), round(hi_b, 1)],
            # picks を除いた母集団との対比（物理的な効果量）
            "mean_edge_vs_excluded": round(float(picks["edge_vs_excluded"].mean()), 1),
            "edge_vs_excluded_ci95_block7": [round(lo_x, 1), round(hi_x, 1)],
            # 母集団に占める選択台の割合。1 に近いほど edge が縮んで見える。
            "mean_pick_share": round(
                float((picks.groupby("date").size() / picks.groupby("date")["universe_size"].first()).mean()),
                3,
            ),
            "edge_positive_day_rate": round(float((per_day["edge"] > 0).mean()), 3),
            "win_rate_abs": round(float((picks["diff"] > 0).mean()), 3),
            "cumulative_diff": round(float(per_day["diff"].sum()), 1),
            "yen_per_day_at_20": round(float(per_day["diff"].mean()) * DEFAULT_COIN_YEN),
        }
    )
    return base


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="事前登録ルールの walk-forward バックテスト")
    p.add_argument("prereg", nargs="+", help="事前登録 JSON のパス（複数可）")
    p.add_argument("--outdir", default=str(RESULT_DIR))
    p.add_argument(
        "--split-date",
        default=None,
        help="YYYYMMDD。この日を境に before/after のエッジを併記する。"
        "店長交代・改装など外部から与えられた既知の変化点にのみ使うこと。"
        "post-hoc 部分集団解析なので採否根拠にはできない。",
    )
    args = p.parse_args(argv)

    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    for path in args.prereg:
        reg = PreRegistration.load(path)
        picks, summary = run(reg)
        if args.split_date and not picks.empty:
            summary["period_split"] = period_split_summary(picks, args.split_date)
        stem = f"{reg.rule_id}__{reg.freeze_hash()}"
        (outdir / f"{stem}.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        if not picks.empty:
            picks.to_csv(outdir / f"{stem}.csv", index=False, encoding="utf-8-sig")
        print(json.dumps(summary, ensure_ascii=False, indent=2))

    return 0


if __name__ == "__main__":
    sys.exit(main())
