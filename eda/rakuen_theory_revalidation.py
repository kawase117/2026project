"""Revalidate the Rakuen theory's unresolved claims without editing the theory.

This is deliberately separate from the July section/DD scripts.  It uses
``machine_layout_history`` for historical positions, never filters on the
target day's games, and reports the post-renovation period separately.

The report answers four questions:
1. Do category-specific DD candidates retain their direction in a temporal
   holdout after BH correction over all 31 DD values?
2. Is the low Rakuen games volume on Juggler-only days still low after a
   same-date, nearby-hall demand control?
3. Does the clean-column edge effect have enough post-renovation evidence to
   begin a forward confirmation?
4. Which legacy section rules cannot be carried into the current layout?

It is an evidence audit, not a replacement recommender.  AT/general and
technical-intervention DD outcomes remain descriptive because an equivalent
setting-likelihood metric is not available for those categories.
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from eda.dd_setting_posterior_rank import jug_posterior_p56, match_family  # noqa: E402
from eda.rakuen_section_classification import POST_EPOCH, PRE_EPOCH, classify  # noqa: E402


RAKUEN_DB = PROJECT_ROOT / "db" / "楽園蒲田店.db"
OUT_DIR = PROJECT_ROOT / "eda" / "results" / "rakuen_theory_revalidation"
HALL_NAME = "楽園蒲田店"
RENOVATION = pd.Timestamp("2026-07-06")
CATEGORY_DDS = {
    "ジャグ": {5, 11, 15, 22, 25},
    "技術介入": {11, 22, 30},
    "AT一般": {10, 11, 22, 30},
    "ハナハナ": {7, 17, 27},
}
PEER_DBS = {
    "蒲田1": "マルハンメガシティ2000-蒲田1.db",
    "蒲田7": "マルハンメガシティ2000-蒲田7.db",
    "金時京急": "金時京急蒲田店.db",
}


def bh_qvalues(pvalues: pd.Series) -> pd.Series:
    """Benjamini-Hochberg q-values, preserving NaN values."""
    out = pd.Series(np.nan, index=pvalues.index, dtype=float)
    valid = pvalues.dropna().sort_values()
    if valid.empty:
        return out
    raw = valid.to_numpy() * len(valid) / np.arange(1, len(valid) + 1)
    adjusted = np.minimum.accumulate(raw[::-1])[::-1]
    out.loc[valid.index] = np.minimum(adjusted, 1.0)
    return out


def db_connect(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True)


def load_rakuen(path: Path) -> pd.DataFrame:
    query = """
        SELECT r.date, r.machine_number, r.machine_name,
               r.games_normalized AS games, r.diff_coins_normalized AS diff_coins,
               r.bb_count, r.rb_count, l.section, l.rank_from_min, l.rank_from_max,
               m.jug_flag, m.hana_flag, m.bt_flag
        FROM machine_detailed_results r
        JOIN machine_layout_history l
          ON r.machine_number = l.machine_number
         AND r.date >= l.valid_from
         AND (l.valid_to IS NULL OR r.date <= l.valid_to)
        LEFT JOIN machine_master m ON r.machine_name = m.machine_name_normalized
        WHERE l.hall_name = ? AND r.games_normalized > 0
    """
    with db_connect(path) as con:
        df = pd.read_sql_query(query, con, params=(HALL_NAME,))
    if df.empty:
        raise RuntimeError("Rakuen query returned no rows")
    for column in ("jug_flag", "hana_flag", "bt_flag"):
        df[column] = df[column].fillna(0).astype(int)
    df["category"] = np.select(
        [df.jug_flag.eq(1), df.hana_flag.eq(1), df.bt_flag.eq(1)],
        ["ジャグ", "ハナハナ", "技術介入"],
        default="AT一般",
    )
    df["date_dt"] = pd.to_datetime(df.date, format="%Y%m%d")
    df["dd"] = df.date_dt.dt.day
    df["epoch"] = np.where(df.date_dt < RENOVATION, "pre", "post")
    df["rate"] = 100 + df.diff_coins / (3 * df.games) * 100
    df["depth"] = df[["rank_from_min", "rank_from_max"]].min(axis=1)
    df["is_edge"] = df.depth.eq(1)
    df["section_class"] = [
        classify(section, PRE_EPOCH if epoch == "pre" else POST_EPOCH)
        for section, epoch in zip(df.section, df.epoch, strict=True)
    ]
    df["family"] = df.machine_name.map(match_family)
    jug = df.family.notna() & df.bb_count.notna() & df.rb_count.notna()
    safe = jug & (df.bb_count >= 0) & (df.rb_count >= 0) & ((df.bb_count + df.rb_count) < df.games)
    df["p56"] = np.nan
    if safe.any():
        work = df.loc[safe, ["family", "games", "bb_count", "rb_count"]].copy()
        df.loc[safe, "p56"] = jug_posterior_p56(work).to_numpy()
    return df


def temporal_dd_validation(df: pd.DataFrame) -> pd.DataFrame:
    """Validate every DD in chronological halves; candidates are never preselected in the test."""
    rows: list[dict[str, object]] = []
    for category, cdf in df.groupby("category"):
        metric = "p56" if category == "ジャグ" else "rate"
        cdf = cdf.dropna(subset=[metric]).copy()
        dates = np.array(sorted(cdf.date_dt.unique()))
        split = pd.Timestamp(dates[len(dates) // 2])
        for dd in range(1, 32):
            rec: dict[str, object] = {
                "category": category,
                "metric": metric,
                "dd": dd,
                "split_date": split.date().isoformat(),
            }
            effects = []
            pvals = []
            for label, part in (("first", cdf[cdf.date_dt < split]), ("second", cdf[cdf.date_dt >= split])):
                target = part[part.dd.eq(dd)][metric]
                other = part[~part.dd.eq(dd)][metric]
                rec[f"n_days_{label}"] = int(part.loc[part.dd.eq(dd), "date"].nunique())
                rec[f"effect_{label}"] = float(target.mean() - other.mean()) if len(target) and len(other) else np.nan
                # Date-level means are the independent units for a calendar claim.
                daily = part.groupby("date").agg(value=(metric, "mean"), dd=("dd", "first"))
                a, b = daily.loc[daily.dd.eq(dd), "value"], daily.loc[~daily.dd.eq(dd), "value"]
                if len(a) >= 3 and len(b) >= 10:
                    rng = np.random.default_rng(20260729 + dd)
                    null = np.empty(4000)
                    values = daily.value.to_numpy()
                    n = len(a)
                    observed = float(a.mean() - b.mean())
                    for i in range(len(null)):
                        shuffled = rng.permutation(values)
                        pick, rest = shuffled[:n], shuffled[n:]
                        null[i] = pick.mean() - rest.mean()
                    pvals.append(float((np.abs(null) >= abs(observed)).mean()))
                else:
                    pvals.append(np.nan)
                effects.append(rec[f"effect_{label}"])
            rec["p_second_raw"] = pvals[1]
            rec["same_direction"] = bool(np.sign(effects[0]) == np.sign(effects[1]) and np.sign(effects[0]) != 0)
            rec["candidate_dd"] = dd in CATEGORY_DDS[category]
            rows.append(rec)
    result = pd.DataFrame(rows)
    result["q_second_bh"] = result.groupby("category")["p_second_raw"].transform(bh_qvalues)
    result["holdout_supported"] = result.same_direction & result.q_second_bh.lt(0.10)
    return result


def load_daily_games(path: Path, hall: str) -> pd.DataFrame:
    query = """SELECT date, AVG(games_normalized) AS avg_games
               FROM machine_detailed_results WHERE games_normalized > 0 GROUP BY date"""
    with db_connect(path) as con:
        df = pd.read_sql_query(query, con)
    df["date_dt"] = pd.to_datetime(df.date, format="%Y%m%d")
    df["hall"] = hall
    return df


def demand_control() -> pd.DataFrame:
    frames = [load_daily_games(RAKUEN_DB, "楽園")]
    for hall, filename in PEER_DBS.items():
        path = PROJECT_ROOT / "db" / filename
        if path.exists():
            frames.append(load_daily_games(path, hall))
    daily = pd.concat(frames, ignore_index=True)
    pivot = daily.pivot(index="date_dt", columns="hall", values="avg_games")
    peers = [name for name in PEER_DBS if name in pivot]
    pivot["peer_median_games"] = pivot[peers].median(axis=1)
    pivot = pivot.dropna(subset=["楽園", "peer_median_games"]).reset_index()
    pivot["dd"] = pivot.date_dt.dt.day
    pivot["weekday"] = pivot.date_dt.dt.weekday
    pivot["month"] = pivot.date_dt.dt.month
    # Remove routine weekday/month seasonality before comparing Rakuen against local demand.
    for col in ("楽園", "peer_median_games"):
        baseline = pivot.groupby(["weekday", "month"])[col].transform("mean")
        scale = pivot.groupby(["weekday", "month"])[col].transform("std").replace(0, np.nan)
        pivot[f"z_{col}"] = (pivot[col] - baseline) / scale
    pivot["rakuen_relative_demand_z"] = pivot["z_楽園"] - pivot["z_peer_median_games"]
    pivot["day_type"] = np.select(
        [pivot.dd.isin([5, 15, 25]), pivot.dd.isin([11, 22, 30])], ["B_jug", "A_public"], default="ordinary"
    )
    rows = []
    ordinary = pivot.loc[pivot.day_type.eq("ordinary"), "rakuen_relative_demand_z"]
    for kind in ("B_jug", "A_public"):
        value = pivot.loc[pivot.day_type.eq(kind), "rakuen_relative_demand_z"]
        rows.append(
            {
                "day_type": kind,
                "n_dates": len(value),
                "relative_demand_z_mean": value.mean(),
                "vs_ordinary": value.mean() - ordinary.mean(),
                "ordinary_mean": ordinary.mean(),
            }
        )
    return pivot, pd.DataFrame(rows)


def edge_epoch_summary(df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for (epoch, category), sub in df[df.section_class.eq("clean") & df.category.isin(["ジャグ", "技術介入"])].groupby(
        ["epoch", "category"]
    ):
        # Same-date/same-machine residual: position comparison, so date-level treatment is appropriate.
        group = sub.groupby(["date", "machine_name"])["rate"]
        work = sub.copy()
        work["resid"] = work.rate - group.transform("mean")
        grouped = work.groupby("is_edge").agg(
            rows=("resid", "size"),
            machines=("machine_number", "nunique"),
            dates=("date", "nunique"),
            mean_resid=("resid", "mean"),
        )
        edge = grouped.loc[True, "mean_resid"] if True in grouped.index else np.nan
        inner = grouped.loc[False, "mean_resid"] if False in grouped.index else np.nan
        rows.append(
            {
                "epoch": epoch,
                "category": category,
                "edge_minus_inner_pp": edge - inner,
                "n_edge_rows": grouped.loc[True, "rows"] if True in grouped.index else 0,
                "n_inner_rows": grouped.loc[False, "rows"] if False in grouped.index else 0,
                "n_dates": work.date.nunique(),
                "n_machines": work.machine_number.nunique(),
                "status": "forward-eligible"
                if epoch == "post" and work.date.nunique() >= 60
                else "insufficient-post-period"
                if epoch == "post"
                else "historical",
            }
        )
    return pd.DataFrame(rows)


def juggler_section_walkforward(df: pd.DataFrame) -> pd.DataFrame:
    """A no-cutoff, pre-renovation replacement for the legacy section backtest.

    This does not claim to be a production recommender: its outcome is the
    Juggler p56 proxy.  Its purpose is only to test whether the old
    all-days-versus-single-event-calendar comparison survives after removing
    target-day games filtering and using the category calendar.
    """
    work = df[(df.epoch == "pre") & (df.category == "ジャグ")].dropna(subset=["p56"]).copy()
    dates = sorted(work.date_dt.unique())
    eval_dates = dates[-120:]
    event_dds = CATEGORY_DDS["ジャグ"]
    rows: list[dict[str, object]] = []
    for target in eval_dates:
        history = work[(work.date_dt < target) & (work.date_dt >= target - pd.Timedelta(days=90))]
        actual = work[work.date_dt.eq(target)]
        if history.empty or actual.empty:
            continue
        is_event = int(pd.Timestamp(target).day) in event_dds
        split_history = history[history.dd.isin(event_dds) if is_event else ~history.dd.isin(event_dds)]
        for model, train in (("all_history", history), ("category_calendar_split", split_history)):
            if train.date.nunique() < 10:
                continue
            ranking = train.groupby("section").p56.mean().sort_values(ascending=False)
            for top_k in (3, 5):
                chosen = ranking.head(top_k).index
                selected = actual[actual.section.isin(chosen)]
                if selected.empty:
                    continue
                rows.append(
                    {
                        "date": pd.Timestamp(target).date().isoformat(),
                        "event_type": "category_event" if is_event else "ordinary",
                        "model": model,
                        "top_k": top_k,
                        "n_train_dates": train.date.nunique(),
                        "selected_p56": selected.p56.mean(),
                        "hall_p56": actual.p56.mean(),
                        "p56_excess": selected.p56.mean() - actual.p56.mean(),
                        "n_selected": len(selected),
                    }
                )
    daily = pd.DataFrame(rows)
    if daily.empty:
        return daily
    summary = daily.groupby(["event_type", "model", "top_k"], as_index=False).agg(
        n_days=("date", "nunique"),
        p56_excess_mean=("p56_excess", "mean"),
        selected_p56_mean=("selected_p56", "mean"),
        hall_p56_mean=("hall_p56", "mean"),
        n_selected_mean=("n_selected", "mean"),
    )
    summary["row_type"] = "summary"
    daily["row_type"] = "daily"
    return pd.concat([summary, daily], ignore_index=True, sort=False)


def legacy_rule_status(df: pd.DataFrame) -> pd.DataFrame:
    legacy = ["1106-1115", "1130-1134", "1209-1216", "3113-3116", "3117-3120", "2141-2162", "1057-1059"]
    rows = []
    for section in legacy:
        pre = df[(df.epoch == "pre") & df.section.eq(section)]
        post = df[(df.epoch == "post") & df.section.eq(section)]
        rows.append(
            {
                "legacy_section": section,
                "pre_rows": len(pre),
                "post_rows_same_label": len(post),
                "carry_to_current_layout": "no: label is historical only"
                if len(pre) and not len(post)
                else "requires physical mapping / re-estimation",
            }
        )
    return pd.DataFrame(rows)


def markdown_table(frame: pd.DataFrame) -> str:
    """Small dependency-free Markdown renderer (pandas.to_markdown needs tabulate)."""
    if frame.empty:
        return "該当なし。"
    shown = frame.copy()
    for col in shown.columns:
        if pd.api.types.is_float_dtype(shown[col]):
            shown[col] = shown[col].map(lambda value: "" if pd.isna(value) else f"{value:.4f}")
        else:
            shown[col] = shown[col].fillna("").astype(str)
    headers = [str(col) for col in shown.columns]
    rows = [[str(value).replace("|", "\\|") for value in row] for row in shown.itertuples(index=False, name=None)]
    return "\n".join(
        [
            "| " + " | ".join(headers) + " |",
            "| " + " | ".join(["---"] * len(headers)) + " |",
            *["| " + " | ".join(row) + " |" for row in rows],
        ]
    )


def write_report(
    path: Path,
    dd: pd.DataFrame,
    demand: pd.DataFrame,
    edge: pd.DataFrame,
    walkforward: pd.DataFrame,
    legacy: pd.DataFrame,
    coverage: dict[str, object],
) -> None:
    supported = dd[dd.holdout_supported].sort_values(["category", "dd"])
    lines = [
        "# 楽園セオリー深掘り再検証",
        "",
        "- 理論本文は変更していない。",
        f"- 実DB: `{coverage['db']}` / `{coverage['first_date']}`〜`{coverage['last_date']}` / {coverage['n_dates']}日。",
        "- 過去位置は `machine_layout_history` を有効期間付きで結合し、当日gamesの足切りは行っていない。",
        "",
        "## 判定",
        "",
        "1. カテゴリ別DD候補は、全31DDを対象に後半時系列holdoutのBH補正で再判定した。`holdout_supported`だけを再利用候補とし、それ以外は探索的扱い。",
        "2. B日を『客が気付いていない』と断定しない。近隣ホール中央値を差し引いた需要差分を出力したが、需要の低さは設定の直接証拠ではない。",
        "3. 工事後は日数が短く、clean端効果はフォワード確認を開始できる段階かを示すのみ。歴史的推定を現行レイアウトに移植しない。",
        "",
        "## 時系列holdoutを通過したDD",
        "",
        markdown_table(supported) if not supported.empty else "該当なし。候補はすべて探索的のまま。",
        "",
        "## 近隣需要差分",
        "",
        markdown_table(demand),
        "",
        "## clean端効果のエポック別集計",
        "",
        markdown_table(edge),
        "",
        "## ジャグ section walk-forward（工事前・p56・当日games足切りなし）",
        "",
        markdown_table(
            walkforward.loc[
                walkforward.row_type.eq("summary"),
                [
                    "event_type",
                    "model",
                    "top_k",
                    "n_days",
                    "p56_excess_mean",
                    "selected_p56_mean",
                    "hall_p56_mean",
                    "n_selected_mean",
                ],
            ]
            if not walkforward.empty
            else walkforward
        ),
        "",
        "## 旧sectionルールの現行適用可否",
        "",
        markdown_table(legacy),
        "",
        "## 限界",
        "",
        "- ジャグ以外には同等の設定尤度指標がないため、AT一般・技術介入のDD水準は設定と回転数選択を完全に分離できない。",
        "- DDの後半検定は各DDの観測日が少ない。BHを通らない候補を『効果なし』と断定しない。",
        "- 近隣ホール差分は地域共通需要を弱める補助分析であり、店固有の告知や客層を完全には観測しない。",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Rakuen theory deep revalidation")
    parser.add_argument("--db-path", type=Path, default=RAKUEN_DB)
    parser.add_argument("--output-dir", type=Path, default=OUT_DIR)
    args = parser.parse_args()
    if not args.db_path.exists():
        raise FileNotFoundError(args.db_path)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    frame = load_rakuen(args.db_path)
    dd = temporal_dd_validation(frame)
    demand_daily, demand_summary = demand_control()
    edge = edge_epoch_summary(frame)
    walkforward = juggler_section_walkforward(frame)
    legacy = legacy_rule_status(frame)
    coverage = {
        "db": str(args.db_path.resolve()),
        "first_date": frame.date.min(),
        "last_date": frame.date.max(),
        "n_dates": frame.date.nunique(),
    }
    dd.to_csv(args.output_dir / "category_dd_temporal_validation.csv", index=False, encoding="utf-8-sig")
    demand_daily.to_csv(args.output_dir / "nearby_demand_daily.csv", index=False, encoding="utf-8-sig")
    demand_summary.to_csv(args.output_dir / "nearby_demand_summary.csv", index=False, encoding="utf-8-sig")
    edge.to_csv(args.output_dir / "clean_edge_epoch_summary.csv", index=False, encoding="utf-8-sig")
    walkforward.to_csv(args.output_dir / "juggler_section_walkforward_p56.csv", index=False, encoding="utf-8-sig")
    legacy.to_csv(args.output_dir / "legacy_section_status.csv", index=False, encoding="utf-8-sig")
    write_report(args.output_dir / "report.md", dd, demand_summary, edge, walkforward, legacy, coverage)
    print(f"[OK] {len(frame):,} rows / {coverage['n_dates']} dates")
    print(f"[OK] report: {args.output_dir / 'report.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
