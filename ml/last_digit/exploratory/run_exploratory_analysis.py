from __future__ import annotations

import argparse
import json
import math
from dataclasses import dataclass
from itertools import combinations
from pathlib import Path
from statistics import multimode
import sqlite3
import sys

import numpy as np
import pandas as pd
from scipy import stats
from sklearn.feature_selection import mutual_info_classif

sys.stdout.reconfigure(encoding='utf-8')

try:
    from lifelines import KaplanMeierFitter  # type: ignore
except Exception:  # pragma: no cover
    KaplanMeierFitter = None

try:
    from statsmodels.tsa.stattools import acf as sm_acf
    from statsmodels.tsa.stattools import adfuller as sm_adfuller
    from statsmodels.tsa.stattools import pacf as sm_pacf
    from statsmodels.tsa.seasonal import STL as sm_stl
    from statsmodels.stats.outliers_influence import variance_inflation_factor as sm_vif
except Exception:  # pragma: no cover
    sm_acf = None
    sm_adfuller = None
    sm_pacf = None
    sm_stl = None
    sm_vif = None


WEEKDAY_JA = {
    0: "月",
    1: "火",
    2: "水",
    3: "木",
    4: "金",
    5: "土",
    6: "日",
}

TOPK_PREFERRED_NAMES = [
    "tail_ltr_xgb_ndcg_xgb_ranker_ndcg_testperiod_topk.csv",
    "tail_ltr_split4_nextday_prediction_gpu_nofocus_equal_testperiod_topk.csv",
]

DAILY_PREFERRED_NAMES = [
    "tail_ltr_xgb_ndcg_xgb_ranker_ndcg_testperiod_daily.csv",
    "tail_ltr_split4_nextday_prediction_gpu_nofocus_equal_testperiod_testperiod_daily.csv",
]


@dataclass
class PredictionSource:
    kind: str
    path: Path
    frame: pd.DataFrame


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Exploratory analyses for last_digit without GPU usage.")
    p.add_argument("--db-glob", default="db/*.db")
    p.add_argument("--reports-dir", default="ml/last_digit/reports")
    p.add_argument("--output-dir", default="ml/last_digit/exploratory")
    p.add_argument("--hall-mode", choices=["integrated", "largest"], default="integrated")
    p.add_argument("--window-days", type=int, default=30)
    p.add_argument("--iqr-multiplier", type=float, default=2.0)
    p.add_argument("--monthly-start", default="2026-01")
    p.add_argument("--monthly-end", default="2026-05")
    p.add_argument(
        "--analyses",
        nargs="+",
        default=["all"],
        choices=[
            "all",
            "chi_square",
            "acf_pacf",
            "kruskal",
            "mutual_info",
            "mutual_info_ltr",
            "acf_per_digit",
            "adf_stationarity",
            "stl_decompose",
            "vif",
            "multiple_testing_bh",
            "digit3_profile",
            "weekday_digit_cross",
            "day7_hypothesis",
            "weekday_cluster_direction",
            "two_cluster_distance",
            "above_mean_streak",
            "weekday_machine_digit_cross",
            "bt_digit_fullweek",
            "atype_digit_fullweek",
            "row_pattern_analysis",
            "floor_atype_digit_fullweek",
        ],
        help="Additional analyses to run.",
    )
    return p.parse_args()


def _weighted_mean(values: pd.Series, weights: pd.Series) -> float:
    v = pd.to_numeric(values, errors="coerce")
    w = pd.to_numeric(weights, errors="coerce").fillna(0.0)
    mask = v.notna() & w.notna()
    if not mask.any() or float(w[mask].sum()) <= 0.0:
        return float(v.mean())
    return float(np.average(v[mask].to_numpy(dtype=float), weights=w[mask].to_numpy(dtype=float)))


def load_daily_hall_summary(db_glob: str) -> pd.DataFrame:
    db_paths = sorted(Path().glob(db_glob))
    rows: list[pd.DataFrame] = []
    for db_path in db_paths:
        con = sqlite3.connect(db_path)
        try:
            q = """
            SELECT
              date,
              day_of_week,
              total_machines,
              avg_diff_per_machine,
              win_rate,
              avg_games_per_machine
            FROM daily_hall_summary
            """
            df = pd.read_sql_query(q, con)
        finally:
            con.close()
        if df.empty:
            continue
        df["hall_name"] = db_path.stem
        rows.append(df)
    if not rows:
        raise FileNotFoundError(f"No daily_hall_summary rows found under {db_glob}")
    out = pd.concat(rows, ignore_index=True)
    out["date"] = pd.to_datetime(out["date"], format="%Y%m%d", errors="coerce")
    out = out.dropna(subset=["date"]).copy()
    out["date"] = out["date"].dt.normalize()
    return out


def load_machine_detailed_results(db_glob: str) -> pd.DataFrame:
    db_paths = sorted(Path().glob(db_glob))
    rows: list[pd.DataFrame] = []
    for db_path in db_paths:
        con = sqlite3.connect(db_path)
        try:
            q = """
            SELECT
              date,
              machine_number,
              machine_name,
              last_digit,
              diff_coins_normalized
            FROM machine_detailed_results
            """
            df = pd.read_sql_query(q, con)
        finally:
            con.close()
        if df.empty:
            continue
        df["hall_name"] = db_path.stem
        rows.append(df)
    if not rows:
        raise FileNotFoundError(f"No machine_detailed_results rows found under {db_glob}")
    out = pd.concat(rows, ignore_index=True)
    out["date"] = pd.to_datetime(out["date"], format="%Y%m%d", errors="coerce")
    out = out.dropna(subset=["date"]).copy()
    out["date"] = out["date"].dt.normalize()
    out["diff_coins_normalized"] = pd.to_numeric(out["diff_coins_normalized"], errors="coerce")
    out["machine_number"] = pd.to_numeric(out["machine_number"], errors="coerce")
    out["last_digit"] = out["last_digit"].astype(str).str.strip()
    return out


def _select_hall_mode(df: pd.DataFrame, hall_mode: str, date_col: str = "date") -> pd.DataFrame:
    if hall_mode != "largest" or "hall_name" not in df.columns:
        return df.copy()
    by_hall = df.groupby("hall_name", sort=True)[date_col].nunique().sort_values(ascending=False)
    if by_hall.empty:
        return df.copy()
    hall = str(by_hall.index[0])
    return df[df["hall_name"] == hall].copy()


def build_daily_series(raw: pd.DataFrame, hall_mode: str) -> tuple[pd.DataFrame, str]:
    if hall_mode == "largest":
        by_hall = raw.groupby("hall_name", sort=True)["date"].nunique().sort_values(ascending=False)
        hall = str(by_hall.index[0])
        one = raw[raw["hall_name"] == hall].copy()
        one["weekday"] = one["day_of_week"].astype(str)
        one["avg_diff"] = pd.to_numeric(one["avg_diff_per_machine"], errors="coerce")
        one["win_rate"] = pd.to_numeric(one["win_rate"], errors="coerce")
        one["avg_games"] = pd.to_numeric(one["avg_games_per_machine"], errors="coerce")
        out = one[["date", "weekday", "avg_diff", "win_rate", "avg_games"]].sort_values("date").reset_index(drop=True)
        return out, f"largest_hall:{hall}"

    grouped_rows: list[dict[str, object]] = []
    for dt, g in raw.groupby("date", sort=True):
        weekday_candidates = g["day_of_week"].dropna().astype(str).tolist()
        weekday = weekday_candidates[0] if weekday_candidates else dt.day_name()
        grouped_rows.append(
            {
                "date": dt,
                "weekday": weekday,
                "avg_diff": _weighted_mean(g["avg_diff_per_machine"], g["total_machines"]),
                "win_rate": _weighted_mean(g["win_rate"], g["total_machines"]),
                "avg_games": _weighted_mean(g["avg_games_per_machine"], g["total_machines"]),
            }
        )
    out = pd.DataFrame(grouped_rows).sort_values("date").reset_index(drop=True)
    return out, "integrated_all_halls"


def compute_anomaly_report(
    df_daily: pd.DataFrame,
    *,
    window_days: int,
    iqr_multiplier: float,
) -> pd.DataFrame:
    out = df_daily.copy()
    s = pd.to_numeric(out["avg_diff"], errors="coerce")
    min_periods = max(7, min(window_days, 14))
    roll = s.rolling(window=window_days, min_periods=min_periods)
    med = roll.median()
    q1 = roll.quantile(0.25)
    q3 = roll.quantile(0.75)
    iqr = q3 - q1
    upper = med + iqr_multiplier * iqr
    lower = med - iqr_multiplier * iqr
    denom = (iqr / 1.349).replace(0.0, np.nan)
    zscore = (s - med) / denom
    is_anomaly = ((s > upper) | (s < lower)) & upper.notna() & lower.notna()
    direction = np.where(s > upper, "high", np.where(s < lower, "low", ""))

    out["is_anomaly"] = is_anomaly.astype(int)
    out["anomaly_direction"] = direction
    out["zscore"] = zscore.astype(float)
    out["rolling_median"] = med.astype(float)
    out["iqd_bound_upper"] = upper.astype(float)
    out["iqd_bound_lower"] = lower.astype(float)

    report = out[
        [
            "date",
            "weekday",
            "avg_diff",
            "is_anomaly",
            "anomaly_direction",
            "zscore",
            "rolling_median",
            "iqd_bound_upper",
            "iqd_bound_lower",
        ]
    ].copy()
    report["date"] = pd.to_datetime(report["date"]).dt.strftime("%Y-%m-%d")
    return report


def pick_prediction_source(reports_dir: Path) -> PredictionSource:
    for name in TOPK_PREFERRED_NAMES:
        p = reports_dir / name
        if p.exists():
            df = pd.read_csv(p, encoding="utf-8-sig")
            if {"date", "expert", "hit_at_2"}.issubset(df.columns):
                return PredictionSource(kind="topk", path=p, frame=df)

    topk_files = sorted(reports_dir.glob("*_testperiod_topk.csv"), key=lambda x: x.stat().st_mtime, reverse=True)
    for p in topk_files:
        try:
            df = pd.read_csv(p, encoding="utf-8-sig")
        except Exception:
            continue
        if {"date", "expert", "hit_at_2"}.issubset(df.columns):
            return PredictionSource(kind="topk", path=p, frame=df)

    for name in DAILY_PREFERRED_NAMES:
        p = reports_dir / name
        if p.exists():
            df = pd.read_csv(p, encoding="utf-8-sig")
            if {"date", "expert", "hit_at_2"}.issubset(df.columns):
                return PredictionSource(kind="daily", path=p, frame=df)

    daily_files = sorted(reports_dir.glob("*_testperiod_daily.csv"), key=lambda x: x.stat().st_mtime, reverse=True)
    for p in daily_files:
        try:
            df = pd.read_csv(p, encoding="utf-8-sig")
        except Exception:
            continue
        if {"date", "expert", "hit_at_2"}.issubset(df.columns):
            return PredictionSource(kind="daily", path=p, frame=df)

    raise FileNotFoundError("No usable testperiod topk/daily CSV found in ml/last_digit/reports")


def build_failure_days(source: PredictionSource) -> tuple[pd.DataFrame, pd.DataFrame]:
    df = source.frame.copy()
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna(subset=["date"]).copy()
    if "expert" not in df.columns:
        df["expert"] = "ALL"
    df["expert"] = df["expert"].astype(str)
    df["hit_at_2"] = pd.to_numeric(df["hit_at_2"], errors="coerce")
    base = df.dropna(subset=["hit_at_2"]).copy()
    by_day = (
        base.groupby("date", sort=True)
        .agg(
            hit_at_2_mean=("hit_at_2", "mean"),
            hit_at_2_min=("hit_at_2", "min"),
            n_experts=("expert", "nunique"),
        )
        .reset_index()
    )
    by_day["is_fail_day"] = (pd.to_numeric(by_day["hit_at_2_min"], errors="coerce").fillna(0.0) <= 0.0).astype(int)
    hit_by_expert = base[base["hit_at_2"] > 0.0][["date", "expert"]].drop_duplicates().copy()
    return by_day, hit_by_expert


def load_latest_full_history(reports_dir: Path) -> pd.DataFrame:
    files = sorted(reports_dir.glob("*_latest_test_full.csv"), key=lambda x: x.stat().st_mtime)
    rows: list[pd.DataFrame] = []
    for p in files:
        try:
            df = pd.read_csv(p, encoding="utf-8-sig")
        except Exception:
            continue
        required = {"date", "expert", "last_digit", "pred", "actual_raw_diff"}
        if not required.issubset(df.columns):
            continue
        work = df[list(required)].copy()
        work["source_file"] = p.name
        rows.append(work)
    if not rows:
        return pd.DataFrame(columns=["date", "expert", "last_digit", "pred", "actual_raw_diff", "source_file"])
    out = pd.concat(rows, ignore_index=True)
    out["date"] = pd.to_datetime(out["date"], errors="coerce")
    out = out.dropna(subset=["date"]).copy()
    out["last_digit"] = out["last_digit"].astype(str)
    out["pred"] = pd.to_numeric(out["pred"], errors="coerce")
    out["actual_raw_diff"] = pd.to_numeric(out["actual_raw_diff"], errors="coerce")
    return out.sort_values(["date", "expert", "last_digit", "source_file"]).reset_index(drop=True)


def build_tail_hit_events(full_history: pd.DataFrame, hit_day_experts: pd.DataFrame) -> pd.DataFrame:
    if full_history.empty:
        return pd.DataFrame(columns=["date", "expert", "tail_digit"])
    hit_key_df = hit_day_experts.copy()
    hit_key_df["date"] = pd.to_datetime(hit_key_df["date"], errors="coerce")
    hit_key_df = hit_key_df.dropna(subset=["date"]).copy()
    hit_keys = set(
        hit_key_df.assign(date_key=hit_key_df["date"].dt.strftime("%Y-%m-%d"))
        .assign(expert=hit_key_df["expert"].astype(str))
        .apply(lambda r: (r["date_key"], r["expert"]), axis=1)
        .tolist()
    )
    events: list[dict[str, object]] = []
    grouped = full_history.groupby(["date", "expert"], sort=True)
    for (dt, expert), g in grouped:
        dt_key = pd.Timestamp(dt).strftime("%Y-%m-%d")
        ex_key = str(expert)
        if (dt_key, ex_key) not in hit_keys:
            continue
        gp = g.sort_values("pred", ascending=False).head(2)
        ga = g.sort_values("actual_raw_diff", ascending=False).head(2)
        pred_tails = set(gp["last_digit"].astype(str).tolist())
        true_tails = set(ga["last_digit"].astype(str).tolist())
        hit_tails = sorted(pred_tails & true_tails)
        for tail in hit_tails:
            events.append({"date": pd.Timestamp(dt), "expert": ex_key, "tail_digit": str(tail)})
    if not events:
        return pd.DataFrame(columns=["date", "expert", "tail_digit"])
    out = pd.DataFrame(events).sort_values(["expert", "tail_digit", "date"]).reset_index(drop=True)
    return out


def intervals_from_events(events: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    if events.empty:
        return pd.DataFrame(columns=["expert", "tail_digit", "interval_days"])
    for (expert, tail), g in events.groupby(["expert", "tail_digit"], sort=True):
        ds = sorted(pd.to_datetime(g["date"]).tolist())
        if len(ds) < 2:
            continue
        for i in range(1, len(ds)):
            rows.append(
                {
                    "expert": str(expert),
                    "tail_digit": str(tail),
                    "interval_days": int((ds[i] - ds[i - 1]).days),
                }
            )
    return pd.DataFrame(rows)


def _series_mode(s: pd.Series) -> float:
    vals = [int(x) for x in pd.to_numeric(s, errors="coerce").dropna().tolist()]
    if not vals:
        return float("nan")
    modes = multimode(vals)
    return float(modes[0]) if modes else float("nan")


def summarize_intervals(intervals: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    if intervals.empty:
        empty_expert = pd.DataFrame(columns=["expert", "median_days", "mean_days", "mode_days", "max_days", "n_intervals"])
        empty_tail = pd.DataFrame(columns=["tail_digit", "median_days", "mean_days", "mode_days", "max_days", "n_intervals"])
        return empty_expert, empty_tail

    by_expert = (
        intervals.groupby("expert", sort=True)["interval_days"]
        .agg(
            median_days="median",
            mean_days="mean",
            max_days="max",
            n_intervals="count",
        )
        .reset_index()
    )
    by_expert["mode_days"] = (
        intervals.groupby("expert", sort=True)["interval_days"]
        .apply(_series_mode)
        .reindex(by_expert["expert"])
        .to_numpy()
    )
    by_expert = by_expert[["expert", "median_days", "mean_days", "mode_days", "max_days", "n_intervals"]]

    by_tail = (
        intervals.groupby("tail_digit", sort=True)["interval_days"]
        .agg(
            median_days="median",
            mean_days="mean",
            max_days="max",
            n_intervals="count",
        )
        .reset_index()
    )
    by_tail["mode_days"] = (
        intervals.groupby("tail_digit", sort=True)["interval_days"]
        .apply(_series_mode)
        .reindex(by_tail["tail_digit"])
        .to_numpy()
    )
    by_tail = by_tail[["tail_digit", "median_days", "mean_days", "mode_days", "max_days", "n_intervals"]]
    return by_expert, by_tail


def periodicity_comment(intervals: pd.DataFrame) -> str:
    if intervals.empty:
        return "判定保留（interval不足）"
    arr = pd.to_numeric(intervals["interval_days"], errors="coerce").dropna().to_numpy(dtype=float)
    if arr.size == 0:
        return "判定保留（interval不足）"
    near7 = float(np.mean(np.abs(arr - 7.0) <= 1.0))
    near14 = float(np.mean(np.abs(arr - 14.0) <= 2.0))
    near30 = float(np.mean(np.abs(arr - 30.0) <= 3.0))
    m = max(near7, near14, near30)
    if m >= 0.35:
        if near7 >= near14 and near7 >= near30:
            return "7日周期の可能性あり"
        if near14 >= near7 and near14 >= near30:
            return "14日周期の可能性あり"
        return "30日周期の可能性あり"
    return "明確な周期性は弱く、ランダム寄り"


def window_hint(intervals: pd.DataFrame) -> str:
    if intervals.empty:
        return "現状維持（roll7/14/28）推奨: データ不足"
    med = float(pd.to_numeric(intervals["interval_days"], errors="coerce").median())
    if math.isnan(med):
        return "現状維持（roll7/14/28）推奨: データ不足"
    if med <= 8:
        return "短周期寄り。roll7比重を上げ、roll28は補助的に維持"
    if med <= 16:
        return "中周期寄り。roll14中心、roll7/28併用が妥当"
    return "長周期寄り。roll28の寄与を増やし、roll7は補助に縮小"


def build_anomaly_vs_fail(anomaly_report: pd.DataFrame, fail_days: pd.DataFrame) -> pd.DataFrame:
    a = anomaly_report.copy()
    a["date"] = pd.to_datetime(a["date"], errors="coerce")
    b = fail_days.copy()
    b["date"] = pd.to_datetime(b["date"], errors="coerce")
    merged = a.merge(b[["date", "hit_at_2_mean", "is_fail_day"]], on="date", how="inner")
    merged["hit_at_2_mean"] = pd.to_numeric(merged["hit_at_2_mean"], errors="coerce")
    merged["is_fail_day"] = pd.to_numeric(merged["is_fail_day"], errors="coerce").fillna(0).astype(int)
    merged["date"] = merged["date"].dt.strftime("%Y-%m-%d")
    return merged.sort_values("date").reset_index(drop=True)


def print_anomaly_summary(anomaly: pd.DataFrame, merged_fail: pd.DataFrame, monthly_start: str, monthly_end: str) -> None:
    total = len(anomaly)
    n_anom = int(pd.to_numeric(anomaly["is_anomaly"], errors="coerce").fillna(0).sum())
    rate = (n_anom / total * 100.0) if total else 0.0
    high = anomaly[anomaly["anomaly_direction"] == "high"]
    low = anomaly[anomaly["anomaly_direction"] == "low"]
    high_mean = float(pd.to_numeric(high["avg_diff"], errors="coerce").mean()) if not high.empty else 0.0
    low_mean = float(pd.to_numeric(low["avg_diff"], errors="coerce").mean()) if not low.empty else 0.0

    print("\n=== アノマリー検出結果 ===")
    print(f"総日数: {total}日")
    print(f"アノマリー日数: {n_anom}日（{rate:.1f}%）")
    print("方向別:")
    print(f"  high（プラス方向）: {len(high)}日 → 平均差枚 {high_mean:+,.0f}")
    print(f"  low （マイナス方向）: {len(low)}日 → 平均差枚 {low_mean:+,.0f}")

    tmp = anomaly.copy()
    tmp["date"] = pd.to_datetime(tmp["date"], errors="coerce")
    tmp["weekday_key"] = tmp["date"].dt.weekday
    print("曜日別アノマリー率:")
    parts: list[str] = []
    for wd in range(7):
        g = tmp[tmp["weekday_key"] == wd]
        p = float(pd.to_numeric(g["is_anomaly"], errors="coerce").mean() * 100.0) if len(g) else 0.0
        parts.append(f"{WEEKDAY_JA[wd]}: {p:.1f}%")
    print("  " + " / ".join(parts))

    ms = pd.Period(monthly_start, freq="M")
    me = pd.Period(monthly_end, freq="M")
    monthly = (
        tmp.assign(month=tmp["date"].dt.to_period("M").astype(str))
        .groupby("month", sort=True)["is_anomaly"]
        .sum()
        .to_dict()
    )
    print(f"月別アノマリー数（{monthly_start}〜{monthly_end}）:")
    period = ms
    items: list[str] = []
    while period <= me:
        key = str(period)
        items.append(f"{key}: {int(monthly.get(key, 0))}件")
        period += 1
    print("  " + " / ".join(items))

    fail = merged_fail[merged_fail["is_fail_day"] == 1].copy()
    fail_days = len(fail)
    fail_anom = int(pd.to_numeric(fail["is_anomaly"], errors="coerce").fillna(0).sum())
    fail_non = fail_days - fail_anom
    fail_anom_rate = (fail_anom / fail_days * 100.0) if fail_days else 0.0
    fail_non_rate = (fail_non / fail_days * 100.0) if fail_days else 0.0

    print("\n=== 予測失敗日 vs アノマリー日 照合 ===")
    print(f"hit@2=0 の日数: {fail_days}日")
    print(f"うちアノマリー日: {fail_anom}日（{fail_anom_rate:.1f}%）")
    print(f"うち非アノマリー日: {fail_non}日（{fail_non_rate:.1f}%）")
    if fail_days == 0:
        interp = "判定保留"
    elif fail_anom_rate >= 60.0:
        interp = "ホール例外行動"
    elif fail_anom_rate <= 30.0:
        interp = "モデル問題"
    else:
        interp = "判定保留"
    print(f"→ 解釈: {interp}")


def print_survival_summary(
    by_expert: pd.DataFrame,
    by_tail: pd.DataFrame,
    intervals: pd.DataFrame,
    coverage_text: str,
) -> None:
    print("\n=== 生存時間分析（高設定的中間隔） ===")
    print("expert 別の的中間隔（日数）:")
    if by_expert.empty:
        print("  データ不足")
    else:
        for _, r in by_expert.sort_values("expert").iterrows():
            print(
                f"  {r['expert']:<4} 中央値{float(r['median_days']):.1f}  平均{float(r['mean_days']):.1f}  "
                f"最頻値{int(r['mode_days']) if pd.notna(r['mode_days']) else 'NA'}  最大{int(r['max_days'])}"
            )

    print("tail_digit 別の的中間隔（全 expert 合計）:")
    if by_tail.empty:
        print("  データ不足")
    else:
        for _, r in by_tail.sort_values("tail_digit").iterrows():
            print(f"  末尾{r['tail_digit']}: 中央値{float(r['median_days']):.1f}日")

    periodic = periodicity_comment(intervals)
    hint = window_hint(intervals)
    print("→ 周期性の有無:")
    print(f"  {periodic}")
    print("→ window サイズへの示唆:")
    print(f"  {hint}")
    print(f"→ カバレッジ: {coverage_text}")


def build_survival_report(
    by_expert: pd.DataFrame,
    by_tail: pd.DataFrame,
    intervals: pd.DataFrame,
    *,
    source_kind: str,
    source_path: str,
    full_coverage: str,
) -> pd.DataFrame:
    columns = [
        "section",
        "key",
        "median_days",
        "mean_days",
        "mode_days",
        "max_days",
        "n_intervals",
        "source_kind",
        "source_path",
        "coverage",
    ]
    rows: list[dict[str, object]] = []
    for _, r in by_expert.iterrows():
        rows.append(
            {
                "section": "expert",
                "key": str(r["expert"]),
                "median_days": float(r["median_days"]),
                "mean_days": float(r["mean_days"]),
                "mode_days": float(r["mode_days"]) if pd.notna(r["mode_days"]) else np.nan,
                "max_days": float(r["max_days"]),
                "n_intervals": int(r["n_intervals"]),
                "source_kind": source_kind,
                "source_path": source_path,
                "coverage": full_coverage,
            }
        )
    for _, r in by_tail.iterrows():
        rows.append(
            {
                "section": "tail_digit",
                "key": str(r["tail_digit"]),
                "median_days": float(r["median_days"]),
                "mean_days": float(r["mean_days"]),
                "mode_days": float(r["mode_days"]) if pd.notna(r["mode_days"]) else np.nan,
                "max_days": float(r["max_days"]),
                "n_intervals": int(r["n_intervals"]),
                "source_kind": source_kind,
                "source_path": source_path,
                "coverage": full_coverage,
            }
        )

    if KaplanMeierFitter is not None and not intervals.empty:
        kmf = KaplanMeierFitter()
        durations = pd.to_numeric(intervals["interval_days"], errors="coerce").dropna().astype(float)
        if len(durations) > 0:
            kmf.fit(durations=durations.to_numpy(), event_observed=np.ones(len(durations), dtype=int))
            median_survival = float(kmf.median_survival_time_) if pd.notna(kmf.median_survival_time_) else np.nan
            rows.append(
                {
                    "section": "km_overall",
                    "key": "all",
                    "median_days": median_survival,
                    "mean_days": float(durations.mean()),
                    "mode_days": np.nan,
                    "max_days": float(durations.max()),
                    "n_intervals": int(len(durations)),
                    "source_kind": source_kind,
                    "source_path": source_path,
                    "coverage": full_coverage,
                }
            )

    if not rows:
        rows.append(
            {
                "section": "info",
                "key": "no_interval_data",
                "median_days": np.nan,
                "mean_days": np.nan,
                "mode_days": np.nan,
                "max_days": np.nan,
                "n_intervals": 0,
                "source_kind": source_kind,
                "source_path": source_path,
                "coverage": full_coverage,
            }
        )
    return pd.DataFrame(rows, columns=columns)


def _build_top2_tail_flags(machine_df: pd.DataFrame) -> pd.DataFrame:
    work = machine_df.copy()
    work = work[work["last_digit"].str.fullmatch(r"\d+")].copy()
    work["last_digit_int"] = pd.to_numeric(work["last_digit"], errors="coerce")
    work = work[work["last_digit_int"].between(0, 9, inclusive="both")].copy()
    work["last_digit"] = work["last_digit_int"].astype(int).astype(str)
    work["weekday"] = work["date"].dt.weekday.map(WEEKDAY_JA)
    work["day_last_digit"] = work["date"].dt.day % 10

    top2 = (
        work.sort_values(["date", "diff_coins_normalized"], ascending=[True, False])
        .groupby("date", sort=True)
        .head(2)[["date", "last_digit"]]
        .drop_duplicates()
        .assign(is_top2_last_digit=1)
    )
    base = work[["date", "weekday", "day_last_digit", "last_digit"]].drop_duplicates().copy()
    base = base.merge(top2, on=["date", "last_digit"], how="left")
    base["is_top2_last_digit"] = pd.to_numeric(base["is_top2_last_digit"], errors="coerce").fillna(0).astype(int)
    return base


def _cramers_v(chi2: float, n: int, r: int, c: int) -> float:
    if n <= 0:
        return float("nan")
    denom = min(r - 1, c - 1)
    if denom <= 0:
        return float("nan")
    return float(np.sqrt(chi2 / (n * denom)))


def _bh_adjust_pvalues(p_values: pd.Series) -> pd.Series:
    p = pd.to_numeric(p_values, errors="coerce").to_numpy(dtype=float)
    out = np.full_like(p, np.nan, dtype=float)
    valid = np.isfinite(p)
    if not np.any(valid):
        return pd.Series(out, index=p_values.index, dtype=float)
    pv = p[valid]
    m = len(pv)
    order = np.argsort(pv)
    ranked = pv[order]
    adjusted = ranked * m / np.arange(1, m + 1, dtype=float)
    adjusted = np.minimum.accumulate(adjusted[::-1])[::-1]
    adjusted = np.clip(adjusted, 0.0, 1.0)
    restored = np.empty_like(adjusted)
    restored[order] = adjusted
    out[valid] = restored
    return pd.Series(out, index=p_values.index, dtype=float)


def _build_daily_feature_frame(df_daily: pd.DataFrame) -> pd.DataFrame:
    feat = df_daily.copy().sort_values("date").reset_index(drop=True)
    feat["date"] = pd.to_datetime(feat["date"], errors="coerce")
    feat = feat.dropna(subset=["date"]).copy()
    feat["date"] = feat["date"].dt.normalize()
    feat["weekday_num"] = feat["date"].dt.weekday.astype(int)
    feat["day_of_month"] = feat["date"].dt.day.astype(int)
    feat["day_last_digit"] = (feat["date"].dt.day % 10).astype(int)
    feat["avg_diff"] = pd.to_numeric(feat["avg_diff"], errors="coerce")
    feat["lag1_avg_diff"] = feat["avg_diff"].shift(1)
    feat["lag7_avg_diff"] = feat["avg_diff"].shift(7)
    feat["lag14_avg_diff"] = feat["avg_diff"].shift(14)
    feat["roll7_avg_diff"] = feat["avg_diff"].shift(1).rolling(7, min_periods=1).mean()
    feat["roll14_avg_diff"] = feat["avg_diff"].shift(1).rolling(14, min_periods=1).mean()
    feat["roll28_avg_diff"] = feat["avg_diff"].shift(1).rolling(28, min_periods=1).mean()
    if "win_rate" in feat.columns:
        feat["win_rate"] = pd.to_numeric(feat["win_rate"], errors="coerce")
    if "avg_games" in feat.columns:
        feat["avg_games"] = pd.to_numeric(feat["avg_games"], errors="coerce")
    return feat


def run_chi_square_analysis(machine_df: pd.DataFrame, output_dir: Path) -> None:
    try:
        base = _build_top2_tail_flags(machine_df)
        rows: list[dict[str, object]] = []
        for name, group_col in [
            ("weekday_vs_top2", "weekday"),
            ("day_last_digit_vs_top2", "day_last_digit"),
        ]:
            contingency = pd.crosstab(base[group_col], base["is_top2_last_digit"])
            if contingency.empty or contingency.shape[0] < 2 or contingency.shape[1] < 2:
                print(f"[warn] chi_square: insufficient contingency for {name}, skipped.")
                continue
            chi2, p, dof, _ = stats.chi2_contingency(contingency)
            v = _cramers_v(float(chi2), int(contingency.to_numpy().sum()), contingency.shape[0], contingency.shape[1])
            rows.append(
                {
                    "analysis_type": name,
                    "chi2": float(chi2),
                    "p_value": float(p),
                    "cramers_v": v,
                    "dof": int(dof),
                    "is_significant": int(float(p) < 0.05),
                }
            )
        out = pd.DataFrame(
            rows,
            columns=["analysis_type", "chi2", "p_value", "cramers_v", "dof", "is_significant"],
        )
        out.to_csv(output_dir / "chi_square_report.csv", index=False, encoding="utf-8-sig")
    except Exception as exc:
        print(f"[warn] chi_square_analysis skipped: {exc}")


def run_adf_stationarity_analysis(df_daily: pd.DataFrame, output_dir: Path) -> None:
    out_path = output_dir / "adf_report.csv"
    columns = [
        "series_name",
        "n_obs",
        "adf_stat",
        "p_value",
        "used_lag",
        "critical_1pct",
        "critical_5pct",
        "critical_10pct",
        "is_stationary_5pct",
    ]
    try:
        if sm_adfuller is None:
            print("[warn] adf_stationarity_analysis skipped: statsmodels is not available.")
            pd.DataFrame(columns=columns).to_csv(out_path, index=False, encoding="utf-8-sig")
            return

        feat = _build_daily_feature_frame(df_daily)
        series_map = {
            "avg_diff": feat["avg_diff"],
            "lag1_avg_diff": feat["lag1_avg_diff"],
            "lag7_avg_diff": feat["lag7_avg_diff"],
            "roll7_avg_diff": feat["roll7_avg_diff"],
            "roll14_avg_diff": feat["roll14_avg_diff"],
            "roll28_avg_diff": feat["roll28_avg_diff"],
        }
        rows: list[dict[str, object]] = []
        for name, raw in series_map.items():
            s = pd.to_numeric(raw, errors="coerce").dropna().astype(float)
            if len(s) < 30:
                continue
            result = sm_adfuller(s.to_numpy(dtype=float), autolag="AIC")
            critical = result[4] if len(result) > 4 else {}
            p_value = float(result[1])
            rows.append(
                {
                    "series_name": name,
                    "n_obs": int(result[3]),
                    "adf_stat": float(result[0]),
                    "p_value": p_value,
                    "used_lag": int(result[2]),
                    "critical_1pct": float(critical.get("1%", np.nan)),
                    "critical_5pct": float(critical.get("5%", np.nan)),
                    "critical_10pct": float(critical.get("10%", np.nan)),
                    "is_stationary_5pct": int(p_value < 0.05),
                }
            )
        pd.DataFrame(rows, columns=columns).to_csv(out_path, index=False, encoding="utf-8-sig")
    except Exception as exc:
        print(f"[warn] adf_stationarity_analysis skipped: {exc}")
        pd.DataFrame(columns=columns).to_csv(out_path, index=False, encoding="utf-8-sig")


def run_stl_decompose_analysis(df_daily: pd.DataFrame, output_dir: Path) -> None:
    summary_path = output_dir / "stl_summary_report.csv"
    daily_path = output_dir / "stl_daily_components.csv"
    summary_cols = [
        "period",
        "n_obs",
        "trend_strength",
        "seasonal_strength",
        "resid_std",
    ]
    daily_cols = ["date", "period", "observed", "trend", "seasonal", "resid"]
    try:
        if sm_stl is None:
            print("[warn] stl_decompose_analysis skipped: statsmodels is not available.")
            pd.DataFrame(columns=summary_cols).to_csv(summary_path, index=False, encoding="utf-8-sig")
            pd.DataFrame(columns=daily_cols).to_csv(daily_path, index=False, encoding="utf-8-sig")
            return

        feat = _build_daily_feature_frame(df_daily)
        base = feat[["date", "avg_diff"]].dropna().copy()
        if len(base) < 30:
            print("[warn] stl_decompose_analysis skipped: insufficient data length (<30).")
            pd.DataFrame(columns=summary_cols).to_csv(summary_path, index=False, encoding="utf-8-sig")
            pd.DataFrame(columns=daily_cols).to_csv(daily_path, index=False, encoding="utf-8-sig")
            return
        base = base.sort_values("date").reset_index(drop=True)
        s = base["avg_diff"].astype(float).to_numpy()
        dates = pd.to_datetime(base["date"], errors="coerce").dt.strftime("%Y-%m-%d")

        periods = [7]
        if len(base) >= 60:
            periods.append(30)

        summary_rows: list[dict[str, object]] = []
        daily_rows: list[dict[str, object]] = []
        for period in periods:
            result = sm_stl(s, period=period, robust=True).fit()
            trend = result.trend.astype(float)
            seasonal = result.seasonal.astype(float)
            resid = result.resid.astype(float)
            observed = trend + seasonal + resid

            resid_var = float(np.nanvar(resid))
            trend_strength = float(max(0.0, 1.0 - resid_var / max(float(np.nanvar(trend + resid)), 1e-12)))
            seasonal_strength = float(max(0.0, 1.0 - resid_var / max(float(np.nanvar(seasonal + resid)), 1e-12)))
            summary_rows.append(
                {
                    "period": int(period),
                    "n_obs": int(len(base)),
                    "trend_strength": trend_strength,
                    "seasonal_strength": seasonal_strength,
                    "resid_std": float(np.nanstd(resid)),
                }
            )
            for i in range(len(base)):
                daily_rows.append(
                    {
                        "date": dates.iloc[i],
                        "period": int(period),
                        "observed": float(observed[i]),
                        "trend": float(trend[i]),
                        "seasonal": float(seasonal[i]),
                        "resid": float(resid[i]),
                    }
                )
        pd.DataFrame(summary_rows, columns=summary_cols).to_csv(summary_path, index=False, encoding="utf-8-sig")
        pd.DataFrame(daily_rows, columns=daily_cols).to_csv(daily_path, index=False, encoding="utf-8-sig")
    except Exception as exc:
        print(f"[warn] stl_decompose_analysis skipped: {exc}")
        pd.DataFrame(columns=summary_cols).to_csv(summary_path, index=False, encoding="utf-8-sig")
        pd.DataFrame(columns=daily_cols).to_csv(daily_path, index=False, encoding="utf-8-sig")


def run_vif_analysis(df_daily: pd.DataFrame, output_dir: Path) -> None:
    out_path = output_dir / "vif_report.csv"
    columns = ["feature", "vif", "is_high_vif_10"]
    try:
        if sm_vif is None:
            print("[warn] vif_analysis skipped: statsmodels is not available.")
            pd.DataFrame(columns=columns).to_csv(out_path, index=False, encoding="utf-8-sig")
            return

        feat = _build_daily_feature_frame(df_daily)
        feature_cols = [
            "weekday_num",
            "day_of_month",
            "day_last_digit",
            "lag1_avg_diff",
            "lag7_avg_diff",
            "lag14_avg_diff",
            "roll7_avg_diff",
            "roll14_avg_diff",
            "roll28_avg_diff",
            "win_rate",
            "avg_games",
        ]
        available_cols = [c for c in feature_cols if c in feat.columns]
        work = feat[available_cols].apply(pd.to_numeric, errors="coerce").dropna().reset_index(drop=True)
        if work.shape[0] < max(30, len(available_cols) + 2) or work.shape[1] < 2:
            print("[warn] vif_analysis skipped: insufficient samples after dropna.")
            pd.DataFrame(columns=columns).to_csv(out_path, index=False, encoding="utf-8-sig")
            return

        rows: list[dict[str, object]] = []
        x = work.to_numpy(dtype=float)
        for i, col in enumerate(work.columns):
            try:
                vif = float(sm_vif(x, i))
            except Exception:
                vif = float("inf")
            rows.append(
                {
                    "feature": col,
                    "vif": vif,
                    "is_high_vif_10": int(np.isfinite(vif) and vif >= 10.0),
                }
            )
        out = pd.DataFrame(rows, columns=columns).sort_values("vif", ascending=False).reset_index(drop=True)
        out.to_csv(out_path, index=False, encoding="utf-8-sig")
    except Exception as exc:
        print(f"[warn] vif_analysis skipped: {exc}")
        pd.DataFrame(columns=columns).to_csv(out_path, index=False, encoding="utf-8-sig")


def run_multiple_testing_bh(output_dir: Path) -> None:
    out_path = output_dir / "multiple_testing_bh_report.csv"
    columns = [
        "source_file",
        "test_id",
        "p_value",
        "p_value_bh",
        "is_significant_raw",
        "is_significant_bh",
    ]
    try:
        rows: list[dict[str, object]] = []
        for source_file in ["chi_square_report.csv", "kruskal_report.csv"]:
            source_path = output_dir / source_file
            if not source_path.exists():
                continue
            src = pd.read_csv(source_path, encoding="utf-8-sig")
            if "p_value" not in src.columns:
                continue
            for _, r in src.iterrows():
                test_id = ""
                if "analysis_type" in src.columns:
                    test_id = str(r.get("analysis_type", ""))
                if "group_a" in src.columns or "group_b" in src.columns:
                    test_id = f"{test_id}:{r.get('group_a', '')}:{r.get('group_b', '')}"
                rows.append(
                    {
                        "source_file": source_file,
                        "test_id": test_id.strip(":"),
                        "p_value": pd.to_numeric(r.get("p_value"), errors="coerce"),
                    }
                )

        if not rows:
            pd.DataFrame(columns=columns).to_csv(out_path, index=False, encoding="utf-8-sig")
            return

        out = pd.DataFrame(rows)
        out["p_value_bh"] = _bh_adjust_pvalues(out["p_value"])
        out["is_significant_raw"] = (pd.to_numeric(out["p_value"], errors="coerce") < 0.05).fillna(False).astype(int)
        out["is_significant_bh"] = (pd.to_numeric(out["p_value_bh"], errors="coerce") < 0.05).fillna(False).astype(int)
        out = out[columns].sort_values(["p_value_bh", "p_value"], ascending=[True, True], na_position="last").reset_index(drop=True)
        out.to_csv(out_path, index=False, encoding="utf-8-sig")
    except Exception as exc:
        print(f"[warn] multiple_testing_bh skipped: {exc}")
        pd.DataFrame(columns=columns).to_csv(out_path, index=False, encoding="utf-8-sig")


def run_acf_pacf_analysis(df_daily: pd.DataFrame, output_dir: Path) -> None:
    if sm_acf is None or sm_pacf is None:
        print("[warn] acf_pacf_analysis skipped: statsmodels is not available.")
        return
    try:
        s = pd.to_numeric(df_daily["avg_diff"], errors="coerce").dropna().astype(float)
        if len(s) < 40:
            print("[warn] acf_pacf_analysis skipped: insufficient data length (<40).")
            return
        lags = 30
        acf_vals, acf_ci = sm_acf(s.to_numpy(), nlags=lags, alpha=0.05, fft=True)
        pacf_vals, pacf_ci = sm_pacf(s.to_numpy(), nlags=lags, alpha=0.05, method="ywm")

        rows: list[dict[str, object]] = []
        for lag in range(lags + 1):
            a = float(acf_vals[lag])
            p = float(pacf_vals[lag])
            al, ah = float(acf_ci[lag][0]), float(acf_ci[lag][1])
            pl, ph = float(pacf_ci[lag][0]), float(pacf_ci[lag][1])
            a_sig = int((al > 0.0) or (ah < 0.0))
            p_sig = int((pl > 0.0) or (ph < 0.0))
            if lag == 0:
                a_sig = 0
                p_sig = 0
            rows.append(
                {
                    "lag": lag,
                    "acf_value": a,
                    "pacf_value": p,
                    "acf_significant": a_sig,
                    "pacf_significant": p_sig,
                    "in_roll7": int(1 <= lag <= 7),
                    "in_roll14": int(1 <= lag <= 14),
                    "in_roll28": int(1 <= lag <= 28),
                }
            )
        out = pd.DataFrame(rows)
        out.to_csv(output_dir / "acf_pacf_report.csv", index=False, encoding="utf-8-sig")

        sig_lags = out[(out["lag"] >= 1) & ((out["acf_significant"] == 1) | (out["pacf_significant"] == 1))]["lag"].tolist()
        c7 = int(sum(1 for lag in sig_lags if 1 <= lag <= 7))
        c14 = int(sum(1 for lag in sig_lags if 1 <= lag <= 14))
        c28 = int(sum(1 for lag in sig_lags if 1 <= lag <= 28))
        scores = {"roll7": c7, "roll14": c14, "roll28": c28}
        recommended = max(scores, key=scores.get) if sig_lags else "roll14"
        print("\n=== ACF/PACF 分析 ===")
        print(f"有意lag: {sig_lags if sig_lags else 'なし'}")
        print(f"推奨window: {recommended} (counts: roll7={c7}, roll14={c14}, roll28={c28})")
    except Exception as exc:
        print(f"[warn] acf_pacf_analysis skipped: {exc}")


def _mann_whitney_posthoc(values: pd.Series, groups: pd.Series, analysis_type: str) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    labels = sorted(groups.dropna().astype(str).unique().tolist())
    for a, b in combinations(labels, 2):
        ga = pd.to_numeric(values[groups.astype(str) == a], errors="coerce").dropna()
        gb = pd.to_numeric(values[groups.astype(str) == b], errors="coerce").dropna()
        if len(ga) == 0 or len(gb) == 0:
            continue
        st, pv = stats.mannwhitneyu(ga.to_numpy(dtype=float), gb.to_numpy(dtype=float), alternative="two-sided")
        rows.append(
            {
                "analysis_type": analysis_type,
                "group_a": a,
                "group_b": b,
                "statistic": float(st),
                "p_value": float(pv),
                "is_significant": int(float(pv) < 0.05),
            }
        )
    return rows


def run_kruskal_analysis(df_daily: pd.DataFrame, machine_df: pd.DataFrame, output_dir: Path) -> None:
    try:
        rows: list[dict[str, object]] = []

        weekday_df = df_daily.copy()
        weekday_df["weekday"] = weekday_df["date"].dt.weekday.map(WEEKDAY_JA)
        weekday_groups = [pd.to_numeric(g["avg_diff"], errors="coerce").dropna().to_numpy(dtype=float) for _, g in weekday_df.groupby("weekday", sort=True)]
        weekday_labels = [str(k) for k in sorted(weekday_df["weekday"].dropna().unique().tolist(), key=lambda x: list(WEEKDAY_JA.values()).index(x))]
        if len(weekday_groups) >= 2 and all(len(g) > 0 for g in weekday_groups):
            st, pv = stats.kruskal(*weekday_groups)
            rows.append(
                {
                    "analysis_type": "kruskal_weekday",
                    "group_a": "ALL",
                    "group_b": "",
                    "statistic": float(st),
                    "p_value": float(pv),
                    "is_significant": int(float(pv) < 0.05),
                }
            )
            if float(pv) < 0.05:
                rows.extend(_mann_whitney_posthoc(weekday_df["avg_diff"], weekday_df["weekday"], "posthoc_weekday"))
        else:
            print("[warn] kruskal weekday skipped: insufficient data.")

        tail_df = machine_df.copy()
        tail_df = tail_df[tail_df["last_digit"].str.fullmatch(r"\d+")].copy()
        tail_df["last_digit"] = pd.to_numeric(tail_df["last_digit"], errors="coerce")
        tail_df = tail_df[tail_df["last_digit"].between(0, 9, inclusive="both")].copy()
        tail_df["last_digit"] = tail_df["last_digit"].astype(int).astype(str)
        tail_groups = [pd.to_numeric(g["diff_coins_normalized"], errors="coerce").dropna().to_numpy(dtype=float) for _, g in tail_df.groupby("last_digit", sort=True)]
        if len(tail_groups) >= 2 and all(len(g) > 0 for g in tail_groups):
            st, pv = stats.kruskal(*tail_groups)
            rows.append(
                {
                    "analysis_type": "kruskal_last_digit",
                    "group_a": "ALL",
                    "group_b": "",
                    "statistic": float(st),
                    "p_value": float(pv),
                    "is_significant": int(float(pv) < 0.05),
                }
            )
            if float(pv) < 0.05:
                rows.extend(_mann_whitney_posthoc(tail_df["diff_coins_normalized"], tail_df["last_digit"], "posthoc_last_digit"))
        else:
            print("[warn] kruskal last_digit skipped: insufficient data.")

        out = pd.DataFrame(
            rows,
            columns=["analysis_type", "group_a", "group_b", "statistic", "p_value", "is_significant"],
        )
        out.to_csv(output_dir / "kruskal_report.csv", index=False, encoding="utf-8-sig")
    except Exception as exc:
        print(f"[warn] kruskal_analysis skipped: {exc}")


def run_mutual_info_analysis(df_daily: pd.DataFrame, output_dir: Path) -> None:
    try:
        anomaly_path = output_dir / "anomaly_detection_report.csv"
        if not anomaly_path.exists():
            print("[warn] mutual_info_analysis skipped: anomaly_detection_report.csv not found.")
            return
        anomaly = pd.read_csv(anomaly_path, encoding="utf-8-sig")
        required = {"date", "anomaly_direction"}
        if not required.issubset(anomaly.columns):
            print("[warn] mutual_info_analysis skipped: anomaly report columns missing.")
            return

        feat = df_daily.copy().sort_values("date").reset_index(drop=True)
        feat["date"] = pd.to_datetime(feat["date"], errors="coerce")
        feat = feat.dropna(subset=["date"]).copy()
        feat["weekday"] = feat["date"].dt.weekday.astype(int)
        feat["day_of_month"] = feat["date"].dt.day.astype(int)
        feat["day_last_digit"] = (feat["date"].dt.day % 10).astype(int)
        feat["avg_diff"] = pd.to_numeric(feat["avg_diff"], errors="coerce")
        feat["lag1_avg_diff"] = feat["avg_diff"].shift(1)
        feat["lag7_avg_diff"] = feat["avg_diff"].shift(7)
        feat["lag14_avg_diff"] = feat["avg_diff"].shift(14)
        feat["roll7_avg_diff"] = feat["avg_diff"].shift(1).rolling(7, min_periods=1).mean()
        feat["roll14_avg_diff"] = feat["avg_diff"].shift(1).rolling(14, min_periods=1).mean()
        feat["roll28_avg_diff"] = feat["avg_diff"].shift(1).rolling(28, min_periods=1).mean()

        anomaly["date"] = pd.to_datetime(anomaly["date"], errors="coerce")
        anomaly["target_high_anomaly"] = (anomaly["anomaly_direction"].astype(str) == "high").astype(int)
        merged = feat.merge(anomaly[["date", "target_high_anomaly"]], on="date", how="inner")
        feature_cols = [
            "weekday",
            "day_of_month",
            "day_last_digit",
            "lag1_avg_diff",
            "lag7_avg_diff",
            "lag14_avg_diff",
            "roll7_avg_diff",
            "roll14_avg_diff",
            "roll28_avg_diff",
        ]
        work = merged[feature_cols + ["target_high_anomaly"]].copy()
        work = work.dropna().reset_index(drop=True)
        if work.empty or work["target_high_anomaly"].nunique() < 2:
            print("[warn] mutual_info_analysis skipped: insufficient supervised samples.")
            return
        X = work[feature_cols].to_numpy(dtype=float)
        y = work["target_high_anomaly"].to_numpy(dtype=int)
        discrete = [True, True, True, False, False, False, False, False, False]
        mi = mutual_info_classif(X, y, discrete_features=discrete, random_state=42)
        out = pd.DataFrame({"feature": feature_cols, "mi_score": mi.astype(float)})
        out = out.sort_values("mi_score", ascending=False).reset_index(drop=True)
        out["rank"] = np.arange(1, len(out) + 1)
        out = out[["feature", "mi_score", "rank"]]
        out.to_csv(output_dir / "mutual_info_report.csv", index=False, encoding="utf-8-sig")
    except Exception as exc:
        print(f"[warn] mutual_info_analysis skipped: {exc}")


def run_mutual_info_ltr_analysis(machine_df: pd.DataFrame, df_daily: pd.DataFrame, output_dir: Path) -> None:
    try:
        base = machine_df.copy()
        base = base[base["last_digit"].astype(str).str.fullmatch(r"\d+")].copy()
        base["last_digit"] = pd.to_numeric(base["last_digit"], errors="coerce")
        base = base[base["last_digit"].between(0, 9, inclusive="both")].copy()
        if base.empty:
            print("[warn] mutual_info_ltr_analysis skipped: no digit rows in 0-9.")
            return
        base["last_digit"] = base["last_digit"].astype(int)
        base["date"] = pd.to_datetime(base["date"], errors="coerce")
        base = base.dropna(subset=["date"]).copy()
        base["diff_coins_normalized"] = pd.to_numeric(base["diff_coins_normalized"], errors="coerce")
        base = base.dropna(subset=["diff_coins_normalized"]).copy()

        # (date, last_digit) level target and digit series.
        digit_daily = (
            base.groupby(["date", "last_digit"], sort=True)["diff_coins_normalized"]
            .mean()
            .rename("digit_diff")
            .reset_index()
            .sort_values(["last_digit", "date"])
        )
        digit_daily["rank_desc"] = digit_daily.groupby("date")["digit_diff"].rank(ascending=False, method="min")
        digit_daily["is_top2"] = (digit_daily["rank_desc"] <= 2).astype(int)

        # Hall-level features (shared across digits per date).
        hall = df_daily.copy().sort_values("date").reset_index(drop=True)
        hall["date"] = pd.to_datetime(hall["date"], errors="coerce")
        hall = hall.dropna(subset=["date"]).copy()
        hall["weekday"] = hall["date"].dt.weekday.astype(int)
        hall["day_of_month"] = hall["date"].dt.day.astype(int)
        hall["day_last_digit"] = (hall["date"].dt.day % 10).astype(int)
        hall["avg_diff"] = pd.to_numeric(hall["avg_diff"], errors="coerce")
        hall["lag1_avg_diff"] = hall["avg_diff"].shift(1)
        hall["lag7_avg_diff"] = hall["avg_diff"].shift(7)
        hall["lag14_avg_diff"] = hall["avg_diff"].shift(14)
        hall["roll7_avg_diff"] = hall["avg_diff"].shift(1).rolling(7, min_periods=1).mean()
        hall["roll14_avg_diff"] = hall["avg_diff"].shift(1).rolling(14, min_periods=1).mean()
        hall["roll28_avg_diff"] = hall["avg_diff"].shift(1).rolling(28, min_periods=1).mean()
        hall_feats = [
            "weekday",
            "day_of_month",
            "day_last_digit",
            "lag1_avg_diff",
            "lag7_avg_diff",
            "lag14_avg_diff",
            "roll7_avg_diff",
            "roll14_avg_diff",
            "roll28_avg_diff",
        ]

        # Digit-level lag features per last_digit.
        digit_daily["lag1_digit_diff"] = digit_daily.groupby("last_digit")["digit_diff"].shift(1)
        digit_daily["lag7_digit_diff"] = digit_daily.groupby("last_digit")["digit_diff"].shift(7)
        digit_daily["lag14_digit_diff"] = digit_daily.groupby("last_digit")["digit_diff"].shift(14)
        digit_feats = ["lag1_digit_diff", "lag7_digit_diff", "lag14_digit_diff"]

        merged = digit_daily.merge(hall[["date", *hall_feats]], on="date", how="left")
        use_cols = hall_feats + digit_feats
        work = merged[["is_top2", *use_cols]].dropna().reset_index(drop=True)
        if work.empty or work["is_top2"].nunique() < 2:
            print("[warn] mutual_info_ltr_analysis skipped: insufficient supervised samples.")
            return

        x = work[use_cols].to_numpy(dtype=float)
        y = work["is_top2"].to_numpy(dtype=int)
        discrete = [True, True, True] + [False] * (len(use_cols) - 3)
        mi = mutual_info_classif(x, y, discrete_features=discrete, random_state=42)
        out = pd.DataFrame({"feature": use_cols, "mi_score": mi.astype(float)})
        out["feature_level"] = np.where(out["feature"].isin(hall_feats), "hall", "digit")
        out = out.sort_values("mi_score", ascending=False).reset_index(drop=True)
        out["rank"] = np.arange(1, len(out) + 1)
        out = out[["feature", "mi_score", "rank", "feature_level"]]
        out.to_csv(output_dir / "mutual_info_ltr_report.csv", index=False, encoding="utf-8-sig")
    except Exception as exc:
        print(f"[warn] mutual_info_ltr_analysis skipped: {exc}")


def run_acf_per_digit_analysis(machine_df: pd.DataFrame, output_dir: Path) -> None:
    if sm_acf is None or sm_pacf is None:
        print("[warn] acf_per_digit_analysis skipped: statsmodels is not available.")
        return
    try:
        lags = 30
        rows: list[dict[str, object]] = []
        sig_by_digit: dict[int, set[int]] = {}

        base = machine_df.copy()
        base["last_digit"] = base["last_digit"].astype(str).str.strip()
        base["date"] = pd.to_datetime(base["date"], errors="coerce")
        base["diff_coins_normalized"] = pd.to_numeric(base["diff_coins_normalized"], errors="coerce")
        base = base.dropna(subset=["date", "diff_coins_normalized"]).copy()

        for digit in range(10):
            sub = base[base["last_digit"] == str(digit)].copy()
            s = sub.groupby("date", sort=True)["diff_coins_normalized"].mean().dropna().astype(float)
            if len(s) < (lags + 10):
                # Keep digit presence in output even when insufficient.
                for lag in range(lags + 1):
                    rows.append(
                        {
                            "last_digit": str(digit),
                            "lag": lag,
                            "acf_value": np.nan,
                            "pacf_value": np.nan,
                            "acf_significant": 0,
                            "pacf_significant": 0,
                        }
                    )
                sig_by_digit[digit] = set()
                print(f"[warn] acf_per_digit: last_digit={digit} insufficient length ({len(s)}).")
                continue

            acf_vals, acf_ci = sm_acf(s.to_numpy(), nlags=lags, alpha=0.05, fft=True)
            pacf_vals, pacf_ci = sm_pacf(s.to_numpy(), nlags=lags, alpha=0.05, method="ywm")
            sig_lags: set[int] = set()
            for lag in range(lags + 1):
                a = float(acf_vals[lag])
                p = float(pacf_vals[lag])
                al, ah = float(acf_ci[lag][0]), float(acf_ci[lag][1])
                pl, ph = float(pacf_ci[lag][0]), float(pacf_ci[lag][1])
                a_sig = int((al > 0.0) or (ah < 0.0))
                p_sig = int((pl > 0.0) or (ph < 0.0))
                if lag == 0:
                    a_sig = 0
                    p_sig = 0
                if lag >= 1 and (a_sig == 1 or p_sig == 1):
                    sig_lags.add(lag)
                rows.append(
                    {
                        "last_digit": str(digit),
                        "lag": lag,
                        "acf_value": a,
                        "pacf_value": p,
                        "acf_significant": a_sig,
                        "pacf_significant": p_sig,
                    }
                )
            sig_by_digit[digit] = sig_lags
            print(f"[acf_per_digit] last_digit={digit} significant_lags={sorted(sig_lags) if sig_lags else 'none'}")

        out = pd.DataFrame(rows)
        out.to_csv(output_dir / "acf_per_digit_report.csv", index=False, encoding="utf-8-sig")

        common = set.intersection(*[v for v in sig_by_digit.values()]) if sig_by_digit else set()
        print(f"[acf_per_digit] common_significant_lags={sorted(common) if common else 'none'}")
    except Exception as exc:
        print(f"[warn] acf_per_digit_analysis skipped: {exc}")


def run_digit3_profile(machine_df: pd.DataFrame, db_glob: str, output_dir: Path) -> None:
    try:
        # section=all_digits
        base = machine_df.copy()
        base["last_digit"] = base["last_digit"].astype(str).str.strip()
        base["diff_coins_normalized"] = pd.to_numeric(base["diff_coins_normalized"], errors="coerce")
        base = base[base["last_digit"].str.fullmatch(r"\d+")].copy()
        base["last_digit_int"] = pd.to_numeric(base["last_digit"], errors="coerce")
        base = base[base["last_digit_int"].between(0, 9, inclusive="both")].copy()
        base["last_digit"] = base["last_digit_int"].astype(int).astype(str)

        all_digits = (
            base.groupby("last_digit", sort=True)
            .agg(
                mean_diff=("diff_coins_normalized", "mean"),
                median_diff=("diff_coins_normalized", "median"),
                std_diff=("diff_coins_normalized", "std"),
                n_rows=("diff_coins_normalized", "count"),
                n_days=("date", "nunique"),
            )
            .reset_index()
        )
        all_digits["section"] = "all_digits"
        all_digits["machine_type"] = ""
        all_digits = all_digits[
            ["section", "last_digit", "machine_type", "mean_diff", "median_diff", "std_diff", "n_rows", "n_days"]
        ]

        # section=digit3_by_machine_type
        db_paths = sorted(Path().glob(db_glob))
        rows: list[pd.DataFrame] = []
        for db_path in db_paths:
            con = sqlite3.connect(db_path)
            try:
                q = """
                SELECT
                  mdr.date,
                  mdr.diff_coins_normalized,
                  CASE
                    WHEN COALESCE(mm.jug_flag, 0)=1 OR COALESCE(mm.hana_flag, 0)=1 THEN 'A型'
                    WHEN COALESCE(mm.bt_flag, 0)=1 THEN 'BT'
                    ELSE 'AT系'
                  END AS machine_type
                FROM machine_detailed_results mdr
                LEFT JOIN machine_master mm
                  ON mdr.machine_name = mm.machine_name_normalized
                WHERE CAST(mdr.last_digit AS TEXT) = '3'
                """
                qdf = pd.read_sql_query(q, con)
            finally:
                con.close()
            if qdf.empty:
                continue
            qdf["hall_name"] = db_path.stem
            rows.append(qdf)

        by_type = pd.DataFrame(
            columns=["section", "last_digit", "machine_type", "mean_diff", "median_diff", "std_diff", "n_rows", "n_days"]
        )
        if rows:
            qall = pd.concat(rows, ignore_index=True)
            if "hall_name" in machine_df.columns and machine_df["hall_name"].nunique() > 0:
                target_halls = set(machine_df["hall_name"].astype(str).unique().tolist())
                qall = qall[qall["hall_name"].astype(str).isin(target_halls)].copy()
            qall["date"] = pd.to_datetime(qall["date"], format="%Y%m%d", errors="coerce")
            qall["diff_coins_normalized"] = pd.to_numeric(qall["diff_coins_normalized"], errors="coerce")
            qall = qall.dropna(subset=["date"]).copy()
            by_type = (
                qall.groupby("machine_type", sort=True)
                .agg(
                    mean_diff=("diff_coins_normalized", "mean"),
                    median_diff=("diff_coins_normalized", "median"),
                    std_diff=("diff_coins_normalized", "std"),
                    n_rows=("diff_coins_normalized", "count"),
                    n_days=("date", "nunique"),
                )
                .reset_index()
            )
            by_type["section"] = "digit3_by_machine_type"
            by_type["last_digit"] = "3"
            by_type = by_type[
                ["section", "last_digit", "machine_type", "mean_diff", "median_diff", "std_diff", "n_rows", "n_days"]
            ]

        out = pd.concat([all_digits, by_type], ignore_index=True)
        out.to_csv(output_dir / "digit3_profile_report.csv", index=False, encoding="utf-8-sig")
    except Exception as exc:
        print(f"[warn] digit3_profile skipped: {exc}")


def run_weekday_digit_cross(machine_df: pd.DataFrame, anomaly_path: Path, output_dir: Path) -> None:
    try:
        base = machine_df.copy()
        base["date"] = pd.to_datetime(base["date"], errors="coerce").dt.normalize()
        base["last_digit"] = base["last_digit"].astype(str).str.strip()
        base["diff_coins_normalized"] = pd.to_numeric(base["diff_coins_normalized"], errors="coerce")
        base = base.dropna(subset=["date", "diff_coins_normalized"]).copy()
        base = base[base["last_digit"].str.fullmatch(r"\d+")].copy()
        base["last_digit_int"] = pd.to_numeric(base["last_digit"], errors="coerce")
        base = base[base["last_digit_int"].between(0, 9, inclusive="both")].copy()
        base["last_digit"] = base["last_digit_int"].astype(int).astype(str)
        base["weekday"] = base["date"].dt.weekday.map(WEEKDAY_JA)

        cross = (
            base.groupby(["weekday", "last_digit"], sort=True)
            .agg(
                mean_diff=("diff_coins_normalized", "mean"),
                median_diff=("diff_coins_normalized", "median"),
                n_rows=("diff_coins_normalized", "count"),
                n_days=("date", "nunique"),
            )
            .reset_index()
        )
        weekday_order = {v: i for i, v in WEEKDAY_JA.items()}
        cross["weekday_order"] = cross["weekday"].map(weekday_order).fillna(999).astype(int)
        cross["digit_order"] = pd.to_numeric(cross["last_digit"], errors="coerce").fillna(999).astype(int)
        cross = cross.sort_values(["weekday_order", "digit_order"]).drop(columns=["weekday_order", "digit_order"]).reset_index(drop=True)
        cross.to_csv(output_dir / "weekday_digit_cross_report.csv", index=False, encoding="utf-8-sig")

        dist_cols = ["last_digit", "mean_diff", "n_rows", "n_days"]
        dist_out = pd.DataFrame(columns=dist_cols)
        if anomaly_path.exists():
            adf = pd.read_csv(anomaly_path, encoding="utf-8-sig")
            if {"date", "is_anomaly", "anomaly_direction"}.issubset(adf.columns):
                adf["date"] = pd.to_datetime(adf["date"], errors="coerce").dt.normalize()
                high_days = adf[
                    (pd.to_numeric(adf["is_anomaly"], errors="coerce").fillna(0).astype(int) == 1)
                    & (adf["anomaly_direction"].astype(str) == "high")
                ]["date"].dropna().drop_duplicates()
                if not high_days.empty:
                    h = base[base["date"].isin(set(high_days.tolist()))].copy()
                    if not h.empty:
                        dist_out = (
                            h.groupby("last_digit", sort=True)
                            .agg(
                                mean_diff=("diff_coins_normalized", "mean"),
                                n_rows=("diff_coins_normalized", "count"),
                                n_days=("date", "nunique"),
                            )
                            .reset_index()
                        )
        else:
            print("[warn] weekday_digit_cross: anomaly_detection_report.csv not found; high_anomaly_digit_dist.csv created as empty.")

        dist_out = dist_out.reindex(columns=dist_cols)
        dist_out.to_csv(output_dir / "high_anomaly_digit_dist.csv", index=False, encoding="utf-8-sig")
    except Exception as exc:
        print(f"[warn] weekday_digit_cross skipped: {exc}")


def run_day7_hypothesis(machine_df: pd.DataFrame, output_dir: Path) -> None:
    out1_path = output_dir / "day7_digit_report.csv"
    out2_path = output_dir / "special_weekday_digit_report.csv"
    out3_path = output_dir / "digit7_vicinity_summary.csv"
    out1_cols = ["day7_flag", "last_digit", "mean_diff", "median_diff", "n_rows", "n_days"]
    out2_cols = ["weekday_group", "last_digit", "mean_diff", "median_diff", "n_rows", "n_days"]
    out3_cols = ["condition", "last_digit", "mean_diff", "n_days"]
    try:
        base = machine_df.copy()
        base = base[base["last_digit"].astype(str).isin([str(d) for d in range(10)])].copy()
        base["last_digit"] = base["last_digit"].astype(str)
        base["diff_coins_normalized"] = pd.to_numeric(base["diff_coins_normalized"], errors="coerce")
        base = base.dropna(subset=["date", "diff_coins_normalized"]).copy()
        base["weekday"] = base["date"].dt.weekday.map(WEEKDAY_JA)
        base["day_of_month"] = base["date"].dt.day
        base["day7_flag"] = base["day_of_month"].isin([7, 17, 27])

        if base.empty:
            print("[warn] day7_hypothesis: base data empty; writing empty CSV files.")
            pd.DataFrame(columns=out1_cols).to_csv(out1_path, index=False, encoding="utf-8-sig")
            pd.DataFrame(columns=out2_cols).to_csv(out2_path, index=False, encoding="utf-8-sig")
            pd.DataFrame(columns=out3_cols).to_csv(out3_path, index=False, encoding="utf-8-sig")
            return

        # File 1: day7 vs non-day7 by last_digit
        group = base.groupby(["day7_flag", "last_digit"], sort=True)
        stats = group["diff_coins_normalized"].agg(mean_diff="mean", median_diff="median", n_rows="count").reset_index()
        n_days = group["date"].nunique().reset_index(name="n_days")
        result = stats.merge(n_days, on=["day7_flag", "last_digit"], how="left")
        result = result.reindex(columns=out1_cols)
        result.to_csv(out1_path, index=False, encoding="utf-8-sig")

        # File 2: Saturday / Wednesday / Others by last_digit
        def _weekday_group(w: str) -> str:
            if w == "土":
                return "土曜"
            if w == "水":
                return "水曜"
            return "その他"

        base["weekday_group"] = base["weekday"].map(_weekday_group)
        group2 = base.groupby(["weekday_group", "last_digit"], sort=True)
        stats2 = group2["diff_coins_normalized"].agg(mean_diff="mean", median_diff="median", n_rows="count").reset_index()
        n_days2 = group2["date"].nunique().reset_index(name="n_days")
        result2 = stats2.merge(n_days2, on=["weekday_group", "last_digit"], how="left")
        weekday_order = {"土曜": 0, "水曜": 1, "その他": 2}
        result2["weekday_order"] = result2["weekday_group"].map(weekday_order).fillna(999).astype(int)
        result2["digit_order"] = pd.to_numeric(result2["last_digit"], errors="coerce").fillna(999).astype(int)
        result2 = (
            result2.sort_values(["weekday_order", "digit_order"])
            .drop(columns=["weekday_order", "digit_order"])
            .reset_index(drop=True)
        )
        result2 = result2.reindex(columns=out2_cols)
        result2.to_csv(out2_path, index=False, encoding="utf-8-sig")

        # File 3: vicinity 5-9 by condition
        vicinity = base[base["last_digit"].isin(["5", "6", "7", "8", "9"])].copy()

        def _condition(row: pd.Series) -> str:
            if row["weekday"] == "土":
                return "土曜"
            if row["weekday"] == "水":
                return "水曜"
            if bool(row["day7_flag"]):
                return "7含む日"
            return "その他"

        if vicinity.empty:
            print("[warn] day7_hypothesis: vicinity(5-9) empty; writing empty digit7_vicinity_summary.csv.")
            pd.DataFrame(columns=out3_cols).to_csv(out3_path, index=False, encoding="utf-8-sig")
            return

        vicinity["condition"] = vicinity.apply(_condition, axis=1)
        group3 = vicinity.groupby(["condition", "last_digit"], sort=True)
        stats3 = group3["diff_coins_normalized"].agg(mean_diff="mean").reset_index()
        n_days3 = group3["date"].nunique().reset_index(name="n_days")
        result3 = stats3.merge(n_days3, on=["condition", "last_digit"], how="left")
        cond_order = {"土曜": 0, "水曜": 1, "7含む日": 2, "その他": 3}
        result3["cond_order"] = result3["condition"].map(cond_order).fillna(999).astype(int)
        result3["digit_order"] = pd.to_numeric(result3["last_digit"], errors="coerce").fillna(999).astype(int)
        result3 = (
            result3.sort_values(["cond_order", "digit_order"])
            .drop(columns=["cond_order", "digit_order"])
            .reset_index(drop=True)
        )
        result3 = result3.reindex(columns=out3_cols)
        result3.to_csv(out3_path, index=False, encoding="utf-8-sig")
    except Exception as exc:
        print(f"[warn] day7_hypothesis skipped: {exc}")
        pd.DataFrame(columns=out1_cols).to_csv(out1_path, index=False, encoding="utf-8-sig")
        pd.DataFrame(columns=out2_cols).to_csv(out2_path, index=False, encoding="utf-8-sig")
        pd.DataFrame(columns=out3_cols).to_csv(out3_path, index=False, encoding="utf-8-sig")


def run_weekday_cluster_direction(machine_df: pd.DataFrame, output_dir: Path) -> None:
    out_path = output_dir / "weekday_cluster_analysis.csv"
    out_cols = [
        "weekday",
        "top1_digit",
        "top1_mean",
        "top2_digit",
        "top2_mean",
        "best_cluster",
        "best_cluster_mean",
        "top1_position",
        "direction",
        "left_neighbor_mean",
        "right_neighbor_mean",
    ]
    try:
        digits = [str(d) for d in range(10)]
        base = machine_df.copy()
        base = base[base["last_digit"].astype(str).isin(digits)].copy()
        base["last_digit"] = base["last_digit"].astype(str)
        base["diff_coins_normalized"] = pd.to_numeric(base["diff_coins_normalized"], errors="coerce")
        base = base.dropna(subset=["date", "diff_coins_normalized"]).copy()
        base["weekday"] = base["date"].dt.weekday.map(WEEKDAY_JA)
        base = base.dropna(subset=["weekday"]).copy()

        if base.empty:
            print("[warn] weekday_cluster_direction: base data empty; writing empty CSV.")
            pd.DataFrame(columns=out_cols).to_csv(out_path, index=False, encoding="utf-8-sig")
            return

        rows: list[dict[str, object]] = []
        weekday_order = {v: i for i, v in WEEKDAY_JA.items()}
        for weekday, grp in base.groupby("weekday", sort=False):
            means_s = grp.groupby("last_digit")["diff_coins_normalized"].mean()
            means = {d: float(means_s.loc[d]) if d in means_s.index else float("nan") for d in digits}

            # Stable tie-break: higher mean first, then smaller digit first.
            sorted_digits = sorted(digits, key=lambda d: (-means[d], int(d)) if pd.notna(means[d]) else (float("inf"), int(d)))
            valid_sorted = [d for d in sorted_digits if pd.notna(means[d])]
            if len(valid_sorted) < 2:
                print(f"[warn] weekday_cluster_direction: insufficient valid digits on {weekday}.")
                continue

            clusters: list[tuple[list[str], float]] = []
            for i in range(10):
                trio = [digits[i], digits[(i + 1) % 10], digits[(i + 2) % 10]]
                vals = [means[d] for d in trio]
                if any(pd.isna(v) for v in vals):
                    continue
                avg = float(sum(vals) / 3.0)
                clusters.append((trio, avg))
            if not clusters:
                print(f"[warn] weekday_cluster_direction: no valid 3-digit cluster on {weekday}.")
                continue

            # Stable tie-break for clusters: higher avg first, then lexicographically smaller trio.
            best_trio, best_avg = sorted(clusters, key=lambda x: (-x[1], tuple(int(d) for d in x[0])))[0]
            top1 = valid_sorted[0]
            top2 = valid_sorted[1]
            top1_mean = float(means[top1])
            top2_mean = float(means[top2])

            if top1 in best_trio:
                pos_idx = best_trio.index(top1)
                if pos_idx == 0:
                    top1_position = "left"
                    direction = "rightward"
                elif pos_idx == 1:
                    top1_position = "center"
                    direction = "centered"
                else:
                    top1_position = "right"
                    direction = "leftward"
            else:
                top1_position = "outside"
                direction = "top1_outside_cluster"

            top1_i = int(top1)
            left_d = str((top1_i - 1) % 10)
            right_d = str((top1_i + 1) % 10)
            left_neighbor_mean = float(means[left_d]) if pd.notna(means[left_d]) else np.nan
            right_neighbor_mean = float(means[right_d]) if pd.notna(means[right_d]) else np.nan

            rows.append(
                {
                    "weekday": weekday,
                    "top1_digit": top1,
                    "top1_mean": top1_mean,
                    "top2_digit": top2,
                    "top2_mean": top2_mean,
                    "best_cluster": "-".join(best_trio),
                    "best_cluster_mean": float(best_avg),
                    "top1_position": top1_position,
                    "direction": direction,
                    "left_neighbor_mean": left_neighbor_mean,
                    "right_neighbor_mean": right_neighbor_mean,
                }
            )

        out = pd.DataFrame(rows, columns=out_cols)
        if not out.empty:
            out["weekday_order"] = out["weekday"].map(weekday_order).fillna(999).astype(int)
            out = out.sort_values("weekday_order").drop(columns=["weekday_order"]).reset_index(drop=True)
        out.to_csv(out_path, index=False, encoding="utf-8-sig")
    except Exception as exc:
        print(f"[warn] weekday_cluster_direction skipped: {exc}")
        pd.DataFrame(columns=out_cols).to_csv(out_path, index=False, encoding="utf-8-sig")


def run_two_cluster_distance_analysis(machine_df: pd.DataFrame, output_dir: Path) -> None:
    weekday_path = output_dir / "weekday_concentration.csv"
    daily_path = output_dir / "daily_top2_distance.csv"
    dist_path = output_dir / "distance_distribution.csv"
    weekday_cols = [
        "weekday",
        "all_digits_mean",
        "best_cluster",
        "best_cluster_mean",
        "concentration_ratio",
        "concentration_delta",
        "top1_digit",
        "top2_digit",
        "top1_top2_distance",
        "direction",
    ]
    daily_cols = ["date", "weekday", "top1_digit", "top1_mean", "top2_digit", "top2_mean", "top1_top2_distance"]
    dist_cols = ["distance", "n_days", "pct", "weekday_breakdown"]
    try:
        weekday_order = ["月", "火", "水", "木", "金", "土", "日"]
        digits = [str(d) for d in range(10)]

        base = machine_df.copy()
        base = base[base["last_digit"].astype(str).isin(digits)].copy()
        base["last_digit"] = base["last_digit"].astype(str)
        base["diff_coins_normalized"] = pd.to_numeric(base["diff_coins_normalized"], errors="coerce")
        base = base.dropna(subset=["date", "diff_coins_normalized"]).copy()
        base["weekday"] = base["date"].dt.weekday.map(WEEKDAY_JA)
        base = base.dropna(subset=["weekday"]).copy()
        if base.empty:
            print("[warn] two_cluster_distance: base data empty; writing empty CSV files.")
            pd.DataFrame(columns=weekday_cols).to_csv(weekday_path, index=False, encoding="utf-8-sig")
            pd.DataFrame(columns=daily_cols).to_csv(daily_path, index=False, encoding="utf-8-sig")
            pd.DataFrame(columns=dist_cols).to_csv(dist_path, index=False, encoding="utf-8-sig")
            return

        # File 1: weekday_concentration.csv
        weekday_rows: list[dict[str, object]] = []
        for wd in weekday_order:
            grp = base[base["weekday"] == wd].copy()
            if grp.empty:
                continue
            means_s = grp.groupby("last_digit", sort=True)["diff_coins_normalized"].mean()
            means = {d: (float(means_s.loc[d]) if d in means_s.index else np.nan) for d in digits}
            valid = {d: v for d, v in means.items() if pd.notna(v)}
            if len(valid) < 2:
                continue
            all_mean = float(np.mean(list(valid.values()))) if valid else np.nan

            clusters: list[tuple[list[str], float]] = []
            for i in range(10):
                trio = [digits[i], digits[(i + 1) % 10], digits[(i + 2) % 10]]
                vals = [means[d] for d in trio]
                if any(pd.isna(v) for v in vals):
                    continue
                clusters.append((trio, float(sum(vals) / 3.0)))

            best_trio = ["?", "?", "?"]
            best_avg = np.nan
            if clusters:
                # tie-break: cluster mean desc, then lexicographically smaller digits
                best_trio, best_avg = sorted(clusters, key=lambda x: (-x[1], tuple(int(d) for d in x[0])))[0]

            # tie-break: mean desc, then smaller digit
            sorted_digits = sorted(valid.keys(), key=lambda d: (-valid[d], int(d)))
            top1 = sorted_digits[0] if len(sorted_digits) > 0 else "?"
            top2 = sorted_digits[1] if len(sorted_digits) > 1 else "?"

            if top1 != "?" and top2 != "?":
                diff = abs(int(top1) - int(top2))
                distance = min(diff, 10 - diff)
            else:
                distance = np.nan

            if top1 in best_trio:
                pos = best_trio.index(top1)
                direction = ["rightward", "centered", "leftward"][pos]
            else:
                direction = "top1_outside_cluster"

            ratio = np.nan
            if pd.notna(all_mean) and float(all_mean) != 0.0 and pd.notna(best_avg):
                ratio = float(best_avg) / float(all_mean)
            delta = float(best_avg - all_mean) if pd.notna(best_avg) and pd.notna(all_mean) else np.nan

            weekday_rows.append(
                {
                    "weekday": wd,
                    "all_digits_mean": round(all_mean, 2) if pd.notna(all_mean) else np.nan,
                    "best_cluster": "-".join(best_trio),
                    "best_cluster_mean": round(float(best_avg), 2) if pd.notna(best_avg) else np.nan,
                    "concentration_ratio": round(ratio, 4) if pd.notna(ratio) else np.nan,
                    "concentration_delta": round(delta, 2) if pd.notna(delta) else np.nan,
                    "top1_digit": top1,
                    "top2_digit": top2,
                    "top1_top2_distance": distance,
                    "direction": direction,
                }
            )
        weekday_df = pd.DataFrame(weekday_rows, columns=weekday_cols)
        weekday_df.to_csv(weekday_path, index=False, encoding="utf-8-sig")

        # File 2: daily_top2_distance.csv
        daily_rows: list[dict[str, object]] = []
        for dt, day_grp in base.groupby("date", sort=True):
            means_s = day_grp.groupby("last_digit", sort=True)["diff_coins_normalized"].mean().dropna()
            if len(means_s) < 2:
                continue
            valid = {str(k): float(v) for k, v in means_s.to_dict().items()}
            sorted_digits = sorted(valid.keys(), key=lambda d: (-valid[d], int(d)))
            t1 = sorted_digits[0]
            t2 = sorted_digits[1]
            diff = abs(int(t1) - int(t2))
            dist = min(diff, 10 - diff)
            daily_rows.append(
                {
                    "date": dt.strftime("%Y-%m-%d"),
                    "weekday": WEEKDAY_JA.get(dt.weekday(), ""),
                    "top1_digit": t1,
                    "top1_mean": round(valid[t1], 2),
                    "top2_digit": t2,
                    "top2_mean": round(valid[t2], 2),
                    "top1_top2_distance": dist,
                }
            )
        daily_df = pd.DataFrame(daily_rows, columns=daily_cols)
        daily_df.to_csv(daily_path, index=False, encoding="utf-8-sig")

        # File 3: distance_distribution.csv
        dist_rows: list[dict[str, object]] = []
        if daily_df.empty:
            pd.DataFrame(columns=dist_cols).to_csv(dist_path, index=False, encoding="utf-8-sig")
            return
        total = len(daily_df)
        cnt = daily_df["top1_top2_distance"].value_counts().to_dict()
        for d in range(6):
            n = int(cnt.get(d, 0))
            sub = daily_df[daily_df["top1_top2_distance"] == d]
            wcnt = sub.groupby("weekday").size().to_dict() if not sub.empty else {}
            ordered_wcnt = {wd: int(wcnt.get(wd, 0)) for wd in weekday_order}
            dist_rows.append(
                {
                    "distance": d,
                    "n_days": n,
                    "pct": round((n / total) * 100.0, 1) if total else 0.0,
                    "weekday_breakdown": json.dumps(ordered_wcnt, ensure_ascii=False),
                }
            )
        dist_df = pd.DataFrame(dist_rows, columns=dist_cols)
        dist_df.to_csv(dist_path, index=False, encoding="utf-8-sig")
    except Exception as exc:
        print(f"[warn] two_cluster_distance skipped: {exc}")
        pd.DataFrame(columns=weekday_cols).to_csv(weekday_path, index=False, encoding="utf-8-sig")
        pd.DataFrame(columns=daily_cols).to_csv(daily_path, index=False, encoding="utf-8-sig")
        pd.DataFrame(columns=dist_cols).to_csv(dist_path, index=False, encoding="utf-8-sig")


def _max_circular_streak(bits: list[int]) -> int:
    if not bits:
        return 0
    n = len(bits)
    doubled = bits + bits
    best = 0
    cur = 0
    for b in doubled:
        if int(b) == 1:
            cur += 1
            if cur > best:
                best = cur
        else:
            cur = 0
    return int(min(best, n))


def run_above_mean_streak(machine_df: pd.DataFrame, output_dir: Path) -> None:
    report_path = output_dir / "above_mean_streak_report.csv"
    daily_path = output_dir / "daily_above_mean_streak.csv"
    report_cols = ["weekday", "mean_streak", "pct_streak_ge5", "pct_streak_le3", "n_days"]
    daily_cols = ["date", "weekday", "max_streak", "above_mean_digits", "n_above"]
    try:
        digits = [str(d) for d in range(10)]
        weekday_order = ["月", "火", "水", "木", "金", "土", "日"]

        base = machine_df.copy()
        base = base[base["last_digit"].astype(str).isin(digits)].copy()
        base["last_digit"] = base["last_digit"].astype(str)
        base["diff_coins_normalized"] = pd.to_numeric(base["diff_coins_normalized"], errors="coerce")
        base = base.dropna(subset=["date", "diff_coins_normalized"]).copy()
        base["weekday"] = base["date"].dt.weekday.map(WEEKDAY_JA)
        base = base.dropna(subset=["weekday"]).copy()

        if base.empty:
            print("[warn] above_mean_streak: base data empty; writing empty CSV files.")
            pd.DataFrame(columns=report_cols).to_csv(report_path, index=False, encoding="utf-8-sig")
            pd.DataFrame(columns=daily_cols).to_csv(daily_path, index=False, encoding="utf-8-sig")
            return

        daily_rows: list[dict[str, object]] = []
        for dt, g in base.groupby("date", sort=True):
            means_s = g.groupby("last_digit", sort=True)["diff_coins_normalized"].mean()
            valid_vals = [float(v) for v in means_s.dropna().tolist()]
            if not valid_vals:
                continue
            all_mean = float(np.mean(valid_vals))
            flags: list[int] = []
            above_digits: list[str] = []
            for d in digits:
                v = float(means_s.loc[d]) if d in means_s.index and pd.notna(means_s.loc[d]) else np.nan
                is_above = int(pd.notna(v) and float(v) > all_mean)
                flags.append(is_above)
                if is_above == 1:
                    above_digits.append(d)
            max_streak = _max_circular_streak(flags)
            daily_rows.append(
                {
                    "date": dt.strftime("%Y-%m-%d"),
                    "weekday": WEEKDAY_JA.get(dt.weekday(), ""),
                    "max_streak": max_streak,
                    "above_mean_digits": ",".join(above_digits),
                    "n_above": int(sum(flags)),
                }
            )

        daily_df = pd.DataFrame(daily_rows, columns=daily_cols)
        daily_df.to_csv(daily_path, index=False, encoding="utf-8-sig")

        if daily_df.empty:
            pd.DataFrame(columns=report_cols).to_csv(report_path, index=False, encoding="utf-8-sig")
            return

        summary = (
            daily_df.groupby("weekday", sort=False)["max_streak"]
            .agg(
                mean_streak="mean",
                pct_streak_ge5=lambda s: float((s >= 5).mean() * 100.0),
                pct_streak_le3=lambda s: float((s <= 3).mean() * 100.0),
                n_days="count",
            )
            .reset_index()
        )
        summary["weekday_order"] = summary["weekday"].map({w: i for i, w in enumerate(weekday_order)}).fillna(999).astype(int)
        summary = summary.sort_values("weekday_order").drop(columns=["weekday_order"]).reset_index(drop=True)
        summary["mean_streak"] = summary["mean_streak"].round(3)
        summary["pct_streak_ge5"] = summary["pct_streak_ge5"].round(1)
        summary["pct_streak_le3"] = summary["pct_streak_le3"].round(1)
        summary = summary.reindex(columns=report_cols)
        summary.to_csv(report_path, index=False, encoding="utf-8-sig")
    except Exception as exc:
        print(f"[warn] above_mean_streak skipped: {exc}")
        pd.DataFrame(columns=report_cols).to_csv(report_path, index=False, encoding="utf-8-sig")
        pd.DataFrame(columns=daily_cols).to_csv(daily_path, index=False, encoding="utf-8-sig")


def run_weekday_machine_digit_cross(
    machine_df: pd.DataFrame,
    db_glob: str,
    output_dir: Path,
    weekdays: list[str] | None = None,
) -> None:
    cross_path = output_dir / "weekday_machine_digit_cross.csv"
    top_path = output_dir / "weekday_machine_top_digits.csv"
    cross_cols = ["weekday", "machine_type", "last_digit", "mean_diff", "median_diff", "n_rows", "n_days"]
    top_cols = [
        "weekday",
        "machine_type",
        "top1_digit",
        "top1_mean",
        "top2_digit",
        "top2_mean",
        "best_cluster",
        "best_cluster_mean",
    ]
    try:
        if weekdays is None:
            weekdays = ["木", "日"]
        digits = [str(d) for d in range(10)]
        weekday_order = ["月", "火", "水", "木", "金", "土", "日"]
        machine_order = {"A型": 0, "BT": 1, "AT系": 2}

        # pull machine_type from DB with normalized key if available.
        db_paths = sorted(Path().glob(db_glob))
        rows: list[pd.DataFrame] = []
        for db_path in db_paths:
            con = sqlite3.connect(db_path)
            try:
                cur = con.cursor()
                cols = [r[1] for r in cur.execute("PRAGMA table_info(machine_detailed_results)").fetchall()]
                if "machine_name_normalized" in cols:
                    join_expr = "mdr.machine_name_normalized = mm.machine_name_normalized"
                else:
                    join_expr = "mdr.machine_name = mm.machine_name_normalized"
                    print("[warn] weekday_machine_digit_cross: machine_name_normalized missing in mdr; fallback to machine_name join.")
                q = f"""
                SELECT
                  mdr.date,
                  mdr.last_digit,
                  mdr.diff_coins_normalized,
                  CASE
                    WHEN COALESCE(mm.jug_flag, 0)=1 OR COALESCE(mm.hana_flag, 0)=1 THEN 'A型'
                    WHEN COALESCE(mm.bt_flag, 0)=1 THEN 'BT'
                    ELSE 'AT系'
                  END AS machine_type
                FROM machine_detailed_results mdr
                LEFT JOIN machine_master mm
                  ON {join_expr}
                """
                qdf = pd.read_sql_query(q, con)
            finally:
                con.close()
            if qdf.empty:
                continue
            qdf["hall_name"] = db_path.stem
            rows.append(qdf)

        if not rows:
            print("[warn] weekday_machine_digit_cross: no DB rows; writing empty CSV files.")
            pd.DataFrame(columns=cross_cols).to_csv(cross_path, index=False, encoding="utf-8-sig")
            pd.DataFrame(columns=top_cols).to_csv(top_path, index=False, encoding="utf-8-sig")
            return

        db_df = pd.concat(rows, ignore_index=True)
        if "hall_name" in machine_df.columns and machine_df["hall_name"].nunique() > 0:
            target_halls = set(machine_df["hall_name"].astype(str).unique().tolist())
            db_df = db_df[db_df["hall_name"].astype(str).isin(target_halls)].copy()

        db_df["date"] = pd.to_datetime(db_df["date"], format="%Y%m%d", errors="coerce")
        db_df["last_digit"] = db_df["last_digit"].astype(str).str.strip()
        db_df["diff_coins_normalized"] = pd.to_numeric(db_df["diff_coins_normalized"], errors="coerce")
        db_df = db_df.dropna(subset=["date", "diff_coins_normalized"]).copy()
        db_df = db_df[db_df["last_digit"].isin(digits)].copy()
        db_df["weekday"] = db_df["date"].dt.weekday.map(WEEKDAY_JA)
        db_df = db_df[db_df["weekday"].isin(weekdays)].copy()

        if db_df.empty:
            print("[warn] weekday_machine_digit_cross: filtered data empty; writing empty CSV files.")
            pd.DataFrame(columns=cross_cols).to_csv(cross_path, index=False, encoding="utf-8-sig")
            pd.DataFrame(columns=top_cols).to_csv(top_path, index=False, encoding="utf-8-sig")
            return

        cross = (
            db_df.groupby(["weekday", "machine_type", "last_digit"], sort=True)
            .agg(
                mean_diff=("diff_coins_normalized", "mean"),
                median_diff=("diff_coins_normalized", "median"),
                n_rows=("diff_coins_normalized", "count"),
                n_days=("date", "nunique"),
            )
            .reset_index()
        )
        cross["weekday_order"] = cross["weekday"].map({w: i for i, w in enumerate(weekday_order)}).fillna(999).astype(int)
        cross["machine_order"] = cross["machine_type"].map(machine_order).fillna(999).astype(int)
        cross["digit_order"] = pd.to_numeric(cross["last_digit"], errors="coerce").fillna(999).astype(int)
        cross = cross.sort_values(["weekday_order", "machine_order", "digit_order"]).drop(columns=["weekday_order", "machine_order", "digit_order"]).reset_index(drop=True)
        cross = cross.reindex(columns=cross_cols)
        cross.to_csv(cross_path, index=False, encoding="utf-8-sig")

        top_rows: list[dict[str, object]] = []
        for (wd, mt), g in db_df.groupby(["weekday", "machine_type"], sort=True):
            means_s = g.groupby("last_digit", sort=True)["diff_coins_normalized"].mean()
            means = {d: (float(means_s.loc[d]) if d in means_s.index else np.nan) for d in digits}
            valid = {d: v for d, v in means.items() if pd.notna(v)}
            if len(valid) < 1:
                continue
            sorted_digits = sorted(valid.keys(), key=lambda d: (-valid[d], int(d)))
            top1 = sorted_digits[0] if len(sorted_digits) > 0 else "?"
            top2 = sorted_digits[1] if len(sorted_digits) > 1 else "?"
            top1_mean = float(valid[top1]) if top1 != "?" else np.nan
            top2_mean = float(valid[top2]) if top2 != "?" else np.nan

            clusters: list[tuple[list[str], float]] = []
            for i in range(10):
                trio = [digits[i], digits[(i + 1) % 10], digits[(i + 2) % 10]]
                vals = [means[d] for d in trio]
                if any(pd.isna(v) for v in vals):
                    continue
                clusters.append((trio, float(sum(vals) / 3.0)))
            if clusters:
                best_trio, best_avg = sorted(clusters, key=lambda x: (-x[1], tuple(int(d) for d in x[0])))[0]
                best_cluster = "-".join(best_trio)
                best_cluster_mean = float(best_avg)
            else:
                best_cluster = "?"
                best_cluster_mean = np.nan

            top_rows.append(
                {
                    "weekday": wd,
                    "machine_type": mt,
                    "top1_digit": top1,
                    "top1_mean": round(top1_mean, 3) if pd.notna(top1_mean) else np.nan,
                    "top2_digit": top2,
                    "top2_mean": round(top2_mean, 3) if pd.notna(top2_mean) else np.nan,
                    "best_cluster": best_cluster,
                    "best_cluster_mean": round(best_cluster_mean, 3) if pd.notna(best_cluster_mean) else np.nan,
                }
            )

        top_df = pd.DataFrame(top_rows, columns=top_cols)
        if not top_df.empty:
            top_df["weekday_order"] = top_df["weekday"].map({w: i for i, w in enumerate(weekday_order)}).fillna(999).astype(int)
            top_df["machine_order"] = top_df["machine_type"].map(machine_order).fillna(999).astype(int)
            top_df = top_df.sort_values(["weekday_order", "machine_order"]).drop(columns=["weekday_order", "machine_order"]).reset_index(drop=True)
        top_df.to_csv(top_path, index=False, encoding="utf-8-sig")
    except Exception as exc:
        print(f"[warn] weekday_machine_digit_cross skipped: {exc}")
        pd.DataFrame(columns=cross_cols).to_csv(cross_path, index=False, encoding="utf-8-sig")
        pd.DataFrame(columns=top_cols).to_csv(top_path, index=False, encoding="utf-8-sig")


def run_bt_digit_fullweek(machine_df: pd.DataFrame, db_glob: str, output_dir: Path) -> None:
    overall_path = output_dir / "bt_overall_digit.csv"
    mode_path = output_dir / "bt_mode_classification.csv"
    cross_path = output_dir / "bt_weekday_digit_cross.csv"
    cluster_path = output_dir / "bt_weekday_cluster.csv"
    overall_cols = ["last_digit", "mean_diff", "n_rows", "pct_rows", "rank"]
    mode_cols = [
        "date",
        "weekday",
        "mode",
        "bt_mean_diff",
        "bt_min_digit_mean",
        "bt_max_digit_mean",
        "bt_digit_range",
        "n_valid_digits",
    ]
    cross_cols = ["mode", "weekday", "last_digit", "mean_diff", "n_rows", "n_days"]
    cluster_cols = [
        "mode",
        "weekday",
        "top1_digit",
        "top1_mean",
        "top2_digit",
        "top2_mean",
        "best_cluster",
        "best_cluster_mean",
        "all_bt_mean",
        "concentration_delta",
        "n_days",
    ]
    try:
        digits = [str(d) for d in range(10)]
        weekday_order = ["月", "火", "水", "木", "金", "土", "日"]
        machine_order = {w: i for i, w in enumerate(weekday_order)}

        # Load BT rows from DB with robust join-key fallback.
        db_paths = sorted(Path().glob(db_glob))
        rows: list[pd.DataFrame] = []
        for db_path in db_paths:
            con = sqlite3.connect(db_path)
            try:
                cur = con.cursor()
                cols = [r[1] for r in cur.execute("PRAGMA table_info(machine_detailed_results)").fetchall()]
                if "machine_name_normalized" in cols:
                    join_expr = "mdr.machine_name_normalized = mm.machine_name_normalized"
                else:
                    join_expr = "mdr.machine_name = mm.machine_name_normalized"
                    print("[warn] bt_digit_fullweek: machine_name_normalized missing in mdr; fallback to machine_name join.")
                q = f"""
                SELECT
                  mdr.date,
                  mdr.machine_number,
                  mdr.last_digit,
                  mdr.diff_coins_normalized,
                  mdr.machine_name
                FROM machine_detailed_results mdr
                LEFT JOIN machine_master mm
                  ON {join_expr}
                WHERE COALESCE(mm.bt_flag, 0) = 1
                """
                qdf = pd.read_sql_query(q, con)
            finally:
                con.close()
            if qdf.empty:
                continue
            qdf["hall_name"] = db_path.stem
            rows.append(qdf)

        if not rows:
            print("[warn] bt_digit_fullweek: no BT rows from DB; writing empty CSV files.")
            pd.DataFrame(columns=overall_cols).to_csv(overall_path, index=False, encoding="utf-8-sig")
            pd.DataFrame(columns=mode_cols).to_csv(mode_path, index=False, encoding="utf-8-sig")
            pd.DataFrame(columns=cross_cols).to_csv(cross_path, index=False, encoding="utf-8-sig")
            pd.DataFrame(columns=cluster_cols).to_csv(cluster_path, index=False, encoding="utf-8-sig")
            return

        bt = pd.concat(rows, ignore_index=True)
        if "hall_name" in machine_df.columns and machine_df["hall_name"].nunique() > 0:
            target_halls = set(machine_df["hall_name"].astype(str).unique().tolist())
            bt = bt[bt["hall_name"].astype(str).isin(target_halls)].copy()

        bt["date"] = pd.to_datetime(bt["date"], format="%Y%m%d", errors="coerce")
        bt["last_digit"] = bt["last_digit"].astype(str).str.strip()
        bt["diff_coins_normalized"] = pd.to_numeric(bt["diff_coins_normalized"], errors="coerce")
        bt = bt.dropna(subset=["date", "diff_coins_normalized"]).copy()
        bt = bt[bt["last_digit"].isin(digits)].copy()
        bt["weekday"] = bt["date"].dt.weekday.map(WEEKDAY_JA)
        bt = bt.dropna(subset=["weekday"]).copy()

        if bt.empty:
            print("[warn] bt_digit_fullweek: filtered BT rows empty; writing empty CSV files.")
            pd.DataFrame(columns=overall_cols).to_csv(overall_path, index=False, encoding="utf-8-sig")
            pd.DataFrame(columns=mode_cols).to_csv(mode_path, index=False, encoding="utf-8-sig")
            pd.DataFrame(columns=cross_cols).to_csv(cross_path, index=False, encoding="utf-8-sig")
            pd.DataFrame(columns=cluster_cols).to_csv(cluster_path, index=False, encoding="utf-8-sig")
            return

        # Step 0: overall BT digit profile.
        overall = (
            bt.groupby("last_digit", sort=True)["diff_coins_normalized"]
            .agg(mean_diff="mean", n_rows="count")
            .reset_index()
        )
        total_rows = int(overall["n_rows"].sum()) if not overall.empty else 0
        overall["pct_rows"] = (overall["n_rows"] / total_rows * 100.0) if total_rows > 0 else 0.0
        overall = overall.sort_values(["mean_diff", "last_digit"], ascending=[False, True]).reset_index(drop=True)
        overall["rank"] = np.arange(1, len(overall) + 1)
        overall = overall.sort_values("last_digit").reset_index(drop=True)
        overall = overall.reindex(columns=overall_cols)
        overall.to_csv(overall_path, index=False, encoding="utf-8-sig")

        # Step 1: classify day-mode (all_high vs normal).
        bt_global_mean = float(bt["diff_coins_normalized"].mean())
        day_rows: list[dict[str, object]] = []
        for dt, g in bt.groupby("date", sort=True):
            means_s = g.groupby("last_digit", sort=True)["diff_coins_normalized"].mean()
            valid = means_s.dropna()
            n_valid = int(valid.shape[0])
            if n_valid == 0:
                continue
            min_m = float(valid.min())
            max_m = float(valid.max())
            mean_m = float(g["diff_coins_normalized"].mean())
            mode = "all_high" if (min_m > bt_global_mean and n_valid >= 7) else "normal"
            day_rows.append(
                {
                    "date": dt.strftime("%Y-%m-%d"),
                    "weekday": WEEKDAY_JA.get(dt.weekday(), ""),
                    "mode": mode,
                    "bt_mean_diff": mean_m,
                    "bt_min_digit_mean": min_m,
                    "bt_max_digit_mean": max_m,
                    "bt_digit_range": max_m - min_m,
                    "n_valid_digits": n_valid,
                }
            )
        mode_df = pd.DataFrame(day_rows, columns=mode_cols)
        if not mode_df.empty:
            mode_df["weekday_order"] = mode_df["weekday"].map(machine_order).fillna(999).astype(int)
            mode_df = mode_df.sort_values(["date", "weekday_order"]).drop(columns=["weekday_order"]).reset_index(drop=True)
        mode_df.to_csv(mode_path, index=False, encoding="utf-8-sig")

        # attach mode to BT rows.
        if mode_df.empty:
            print("[warn] bt_digit_fullweek: mode classification empty; writing empty cross/cluster files.")
            pd.DataFrame(columns=cross_cols).to_csv(cross_path, index=False, encoding="utf-8-sig")
            pd.DataFrame(columns=cluster_cols).to_csv(cluster_path, index=False, encoding="utf-8-sig")
            return
        mode_key = mode_df[["date", "mode"]].copy()
        mode_key["date"] = pd.to_datetime(mode_key["date"], errors="coerce")
        btm = bt.merge(mode_key, on="date", how="inner")

        # Step 2: mode x weekday x digit cross.
        cross = (
            btm.groupby(["mode", "weekday", "last_digit"], sort=True)
            .agg(
                mean_diff=("diff_coins_normalized", "mean"),
                n_rows=("diff_coins_normalized", "count"),
                n_days=("date", "nunique"),
            )
            .reset_index()
        )
        if not cross.empty:
            cross["mode_order"] = cross["mode"].map({"normal": 0, "all_high": 1}).fillna(999).astype(int)
            cross["weekday_order"] = cross["weekday"].map(machine_order).fillna(999).astype(int)
            cross["digit_order"] = pd.to_numeric(cross["last_digit"], errors="coerce").fillna(999).astype(int)
            cross = cross.sort_values(["mode_order", "weekday_order", "digit_order"]).drop(columns=["mode_order", "weekday_order", "digit_order"]).reset_index(drop=True)
        cross = cross.reindex(columns=cross_cols)
        cross.to_csv(cross_path, index=False, encoding="utf-8-sig")

        # Step 3: mode x weekday cluster summary.
        cluster_rows: list[dict[str, object]] = []
        for (mode, wd), g in btm.groupby(["mode", "weekday"], sort=True):
            means_s = g.groupby("last_digit", sort=True)["diff_coins_normalized"].mean()
            means = {d: (float(means_s.loc[d]) if d in means_s.index else np.nan) for d in digits}
            valid = {d: v for d, v in means.items() if pd.notna(v)}
            if len(valid) < 2:
                continue
            sorted_digits = sorted(valid.keys(), key=lambda d: (-valid[d], int(d)))
            top1 = sorted_digits[0]
            top2 = sorted_digits[1] if len(sorted_digits) > 1 else "?"
            top1_mean = float(valid[top1])
            top2_mean = float(valid[top2]) if top2 != "?" else np.nan
            all_bt_mean = float(np.mean(list(valid.values())))

            clusters: list[tuple[list[str], float]] = []
            for i in range(10):
                trio = [digits[i], digits[(i + 1) % 10], digits[(i + 2) % 10]]
                vals = [means[d] for d in trio]
                if any(pd.isna(v) for v in vals):
                    continue
                clusters.append((trio, float(sum(vals) / 3.0)))
            if clusters:
                best_trio, best_avg = sorted(clusters, key=lambda x: (-x[1], tuple(int(d) for d in x[0])))[0]
                best_cluster = "-".join(best_trio)
                best_cluster_mean = float(best_avg)
            else:
                best_cluster = "?"
                best_cluster_mean = np.nan

            delta = float(best_cluster_mean - all_bt_mean) if pd.notna(best_cluster_mean) else np.nan
            cluster_rows.append(
                {
                    "mode": mode,
                    "weekday": wd,
                    "top1_digit": top1,
                    "top1_mean": round(top1_mean, 3),
                    "top2_digit": top2,
                    "top2_mean": round(top2_mean, 3) if pd.notna(top2_mean) else np.nan,
                    "best_cluster": best_cluster,
                    "best_cluster_mean": round(best_cluster_mean, 3) if pd.notna(best_cluster_mean) else np.nan,
                    "all_bt_mean": round(all_bt_mean, 3),
                    "concentration_delta": round(delta, 3) if pd.notna(delta) else np.nan,
                    "n_days": int(g["date"].nunique()),
                }
            )
        cluster_df = pd.DataFrame(cluster_rows, columns=cluster_cols)
        if not cluster_df.empty:
            cluster_df["mode_order"] = cluster_df["mode"].map({"normal": 0, "all_high": 1}).fillna(999).astype(int)
            cluster_df["weekday_order"] = cluster_df["weekday"].map(machine_order).fillna(999).astype(int)
            cluster_df = cluster_df.sort_values(["mode_order", "weekday_order"]).drop(columns=["mode_order", "weekday_order"]).reset_index(drop=True)
        cluster_df.to_csv(cluster_path, index=False, encoding="utf-8-sig")
    except Exception as exc:
        print(f"[warn] bt_digit_fullweek skipped: {exc}")
        pd.DataFrame(columns=overall_cols).to_csv(overall_path, index=False, encoding="utf-8-sig")
        pd.DataFrame(columns=mode_cols).to_csv(mode_path, index=False, encoding="utf-8-sig")
        pd.DataFrame(columns=cross_cols).to_csv(cross_path, index=False, encoding="utf-8-sig")
        pd.DataFrame(columns=cluster_cols).to_csv(cluster_path, index=False, encoding="utf-8-sig")


def run_atype_digit_fullweek(machine_df: pd.DataFrame, db_glob: str, output_dir: Path) -> None:
    overall_path = output_dir / "atype_overall_digit.csv"
    cross_path = output_dir / "atype_weekday_digit_cross.csv"
    cluster_path = output_dir / "atype_weekday_cluster.csv"
    non_at_path = output_dir / "non_at_overall_digit.csv"
    overall_cols = ["last_digit", "mean_diff", "n_rows", "pct_rows", "rank"]
    cross_cols = ["weekday", "last_digit", "mean_diff", "median_diff", "n_rows", "n_days"]
    cluster_cols = [
        "weekday",
        "top1_digit",
        "top1_mean",
        "top2_digit",
        "top2_mean",
        "best_cluster",
        "best_cluster_mean",
        "all_atype_mean",
        "concentration_delta",
        "n_days",
    ]
    try:
        digits = [str(d) for d in range(10)]
        weekday_order = ["月", "火", "水", "木", "金", "土", "日"]
        weekday_map = {w: i for i, w in enumerate(weekday_order)}

        db_paths = sorted(Path().glob(db_glob))
        rows: list[pd.DataFrame] = []
        for db_path in db_paths:
            con = sqlite3.connect(db_path)
            try:
                cur = con.cursor()
                cols = [r[1] for r in cur.execute("PRAGMA table_info(machine_detailed_results)").fetchall()]
                if "machine_name_normalized" in cols:
                    join_expr = "mdr.machine_name_normalized = mm.machine_name_normalized"
                else:
                    join_expr = "mdr.machine_name = mm.machine_name_normalized"
                    print("[warn] atype_digit_fullweek: machine_name_normalized missing in mdr; fallback to machine_name join.")
                q = f"""
                SELECT
                  mdr.date,
                  mdr.last_digit,
                  mdr.diff_coins_normalized,
                  COALESCE(mm.jug_flag, 0) AS jug_flag,
                  COALESCE(mm.hana_flag, 0) AS hana_flag,
                  COALESCE(mm.bt_flag, 0) AS bt_flag
                FROM machine_detailed_results mdr
                LEFT JOIN machine_master mm
                  ON {join_expr}
                """
                qdf = pd.read_sql_query(q, con)
            finally:
                con.close()
            if qdf.empty:
                continue
            qdf["hall_name"] = db_path.stem
            rows.append(qdf)

        if not rows:
            print("[warn] atype_digit_fullweek: no rows from DB; writing empty CSV files.")
            pd.DataFrame(columns=overall_cols).to_csv(overall_path, index=False, encoding="utf-8-sig")
            pd.DataFrame(columns=cross_cols).to_csv(cross_path, index=False, encoding="utf-8-sig")
            pd.DataFrame(columns=cluster_cols).to_csv(cluster_path, index=False, encoding="utf-8-sig")
            pd.DataFrame(columns=overall_cols).to_csv(non_at_path, index=False, encoding="utf-8-sig")
            return

        df = pd.concat(rows, ignore_index=True)
        if "hall_name" in machine_df.columns and machine_df["hall_name"].nunique() > 0:
            target_halls = set(machine_df["hall_name"].astype(str).unique().tolist())
            df = df[df["hall_name"].astype(str).isin(target_halls)].copy()

        df["date"] = pd.to_datetime(df["date"], format="%Y%m%d", errors="coerce")
        df["last_digit"] = df["last_digit"].astype(str).str.strip()
        df["diff_coins_normalized"] = pd.to_numeric(df["diff_coins_normalized"], errors="coerce")
        df = df.dropna(subset=["date", "diff_coins_normalized"]).copy()
        df = df[df["last_digit"].isin(digits)].copy()
        df["weekday"] = df["date"].dt.weekday.map(WEEKDAY_JA)
        df["is_atype"] = ((pd.to_numeric(df["jug_flag"], errors="coerce").fillna(0).astype(int) == 1) | (pd.to_numeric(df["hana_flag"], errors="coerce").fillna(0).astype(int) == 1)).astype(int)
        df["is_bt"] = (pd.to_numeric(df["bt_flag"], errors="coerce").fillna(0).astype(int) == 1).astype(int)

        atype = df[df["is_atype"] == 1].copy()
        non_at = df[(df["is_atype"] == 1) | (df["is_bt"] == 1)].copy()

        if atype.empty:
            print("[warn] atype_digit_fullweek: A-type rows empty; writing empty A-type CSV files.")
            pd.DataFrame(columns=overall_cols).to_csv(overall_path, index=False, encoding="utf-8-sig")
            pd.DataFrame(columns=cross_cols).to_csv(cross_path, index=False, encoding="utf-8-sig")
            pd.DataFrame(columns=cluster_cols).to_csv(cluster_path, index=False, encoding="utf-8-sig")
        else:
            overall = (
                atype.groupby("last_digit", sort=True)["diff_coins_normalized"]
                .agg(mean_diff="mean", n_rows="count")
                .reset_index()
            )
            total_rows = int(overall["n_rows"].sum()) if not overall.empty else 0
            overall["pct_rows"] = (overall["n_rows"] / total_rows * 100.0) if total_rows > 0 else 0.0
            overall = overall.sort_values(["mean_diff", "last_digit"], ascending=[False, True]).reset_index(drop=True)
            overall["rank"] = np.arange(1, len(overall) + 1)
            overall = overall.sort_values("last_digit").reset_index(drop=True)
            overall = overall.reindex(columns=overall_cols)
            overall.to_csv(overall_path, index=False, encoding="utf-8-sig")

            cross = (
                atype.groupby(["weekday", "last_digit"], sort=True)
                .agg(
                    mean_diff=("diff_coins_normalized", "mean"),
                    median_diff=("diff_coins_normalized", "median"),
                    n_rows=("diff_coins_normalized", "count"),
                    n_days=("date", "nunique"),
                )
                .reset_index()
            )
            cross["weekday_order"] = cross["weekday"].map(weekday_map).fillna(999).astype(int)
            cross["digit_order"] = pd.to_numeric(cross["last_digit"], errors="coerce").fillna(999).astype(int)
            cross = cross.sort_values(["weekday_order", "digit_order"]).drop(columns=["weekday_order", "digit_order"]).reset_index(drop=True)
            cross = cross.reindex(columns=cross_cols)
            cross.to_csv(cross_path, index=False, encoding="utf-8-sig")

            cluster_rows: list[dict[str, object]] = []
            for wd in weekday_order:
                g = atype[atype["weekday"] == wd].copy()
                if g.empty:
                    continue
                means_s = g.groupby("last_digit", sort=True)["diff_coins_normalized"].mean()
                means = {d: (float(means_s.loc[d]) if d in means_s.index else np.nan) for d in digits}
                valid = {d: v for d, v in means.items() if pd.notna(v)}
                if len(valid) < 2:
                    continue
                sorted_digits = sorted(valid.keys(), key=lambda d: (-valid[d], int(d)))
                top1 = sorted_digits[0]
                top2 = sorted_digits[1] if len(sorted_digits) > 1 else "?"
                top1_mean = float(valid[top1])
                top2_mean = float(valid[top2]) if top2 != "?" else np.nan
                all_atype_mean = float(np.mean(list(valid.values())))

                clusters: list[tuple[list[str], float]] = []
                for i in range(10):
                    trio = [digits[i], digits[(i + 1) % 10], digits[(i + 2) % 10]]
                    vals = [means[d] for d in trio]
                    if any(pd.isna(v) for v in vals):
                        continue
                    clusters.append((trio, float(sum(vals) / 3.0)))
                if clusters:
                    best_trio, best_avg = sorted(clusters, key=lambda x: (-x[1], tuple(int(d) for d in x[0])))[0]
                    best_cluster = "-".join(best_trio)
                    best_cluster_mean = float(best_avg)
                else:
                    best_cluster = "?"
                    best_cluster_mean = np.nan

                delta = float(best_cluster_mean - all_atype_mean) if pd.notna(best_cluster_mean) else np.nan
                cluster_rows.append(
                    {
                        "weekday": wd,
                        "top1_digit": top1,
                        "top1_mean": round(top1_mean, 3),
                        "top2_digit": top2,
                        "top2_mean": round(top2_mean, 3) if pd.notna(top2_mean) else np.nan,
                        "best_cluster": best_cluster,
                        "best_cluster_mean": round(best_cluster_mean, 3) if pd.notna(best_cluster_mean) else np.nan,
                        "all_atype_mean": round(all_atype_mean, 3),
                        "concentration_delta": round(delta, 3) if pd.notna(delta) else np.nan,
                        "n_days": int(g["date"].nunique()),
                    }
                )
            cluster_df = pd.DataFrame(cluster_rows, columns=cluster_cols)
            cluster_df.to_csv(cluster_path, index=False, encoding="utf-8-sig")

        if non_at.empty:
            print("[warn] atype_digit_fullweek: non-AT rows empty; writing empty non_at_overall_digit.csv.")
            pd.DataFrame(columns=overall_cols).to_csv(non_at_path, index=False, encoding="utf-8-sig")
        else:
            non_df = (
                non_at.groupby("last_digit", sort=True)["diff_coins_normalized"]
                .agg(mean_diff="mean", n_rows="count")
                .reset_index()
            )
            total_rows2 = int(non_df["n_rows"].sum()) if not non_df.empty else 0
            non_df["pct_rows"] = (non_df["n_rows"] / total_rows2 * 100.0) if total_rows2 > 0 else 0.0
            non_df = non_df.sort_values(["mean_diff", "last_digit"], ascending=[False, True]).reset_index(drop=True)
            non_df["rank"] = np.arange(1, len(non_df) + 1)
            non_df = non_df.sort_values("last_digit").reset_index(drop=True)
            non_df = non_df.reindex(columns=overall_cols)
            non_df.to_csv(non_at_path, index=False, encoding="utf-8-sig")
    except Exception as exc:
        print(f"[warn] atype_digit_fullweek skipped: {exc}")
        pd.DataFrame(columns=overall_cols).to_csv(overall_path, index=False, encoding="utf-8-sig")
        pd.DataFrame(columns=cross_cols).to_csv(cross_path, index=False, encoding="utf-8-sig")
        pd.DataFrame(columns=cluster_cols).to_csv(cluster_path, index=False, encoding="utf-8-sig")
        pd.DataFrame(columns=overall_cols).to_csv(non_at_path, index=False, encoding="utf-8-sig")


def run_floor_atype_digit_fullweek(machine_df: pd.DataFrame, db_glob: str, output_dir: Path) -> None:
    overall_path = output_dir / "floor_atype_overall_digit.csv"
    cluster_path = output_dir / "floor_atype_weekday_cluster.csv"
    overall_cols = ["group_key", "last_digit", "mean_diff", "n_rows", "pct_rows", "rank"]
    cluster_cols = [
        "group_key",
        "weekday",
        "top1_digit",
        "top1_mean",
        "top2_digit",
        "top2_mean",
        "best_cluster",
        "best_cluster_mean",
        "all_group_mean",
        "concentration_delta",
        "n_days",
    ]
    try:
        digits = [str(d) for d in range(10)]
        weekday_order = ["月", "火", "水", "木", "金", "土", "日"]
        weekday_map = {w: i for i, w in enumerate(weekday_order)}
        group_order = {"2F_A": 0, "2F_N": 1, "3F_A": 2, "3F_N": 3}

        db_paths = sorted(Path().glob(db_glob))
        rows: list[pd.DataFrame] = []
        for db_path in db_paths:
            con = sqlite3.connect(db_path)
            try:
                cur = con.cursor()
                cols = [r[1] for r in cur.execute("PRAGMA table_info(machine_detailed_results)").fetchall()]
                if "machine_name_normalized" in cols:
                    join_expr = "mdr.machine_name_normalized = mm.machine_name_normalized"
                else:
                    join_expr = "mdr.machine_name = mm.machine_name_normalized"
                    print("[warn] floor_atype_digit_fullweek: machine_name_normalized missing in mdr; fallback to machine_name join.")
                q = f"""
                SELECT
                  mdr.date,
                  mdr.machine_number,
                  mdr.last_digit,
                  mdr.diff_coins_normalized,
                  COALESCE(mm.jug_flag, 0) AS jug_flag,
                  COALESCE(mm.hana_flag, 0) AS hana_flag,
                  COALESCE(mm.bt_flag, 0) AS bt_flag
                FROM machine_detailed_results mdr
                LEFT JOIN machine_master mm
                  ON {join_expr}
                WHERE CAST(SUBSTR(CAST(mdr.machine_number AS TEXT), 1, 1) AS TEXT) IN ('2', '3')
                """
                qdf = pd.read_sql_query(q, con)
            finally:
                con.close()
            if qdf.empty:
                continue
            qdf["hall_name"] = db_path.stem
            rows.append(qdf)

        if not rows:
            print("[warn] floor_atype_digit_fullweek: no rows from DB; writing empty CSV files.")
            pd.DataFrame(columns=overall_cols).to_csv(overall_path, index=False, encoding="utf-8-sig")
            pd.DataFrame(columns=cluster_cols).to_csv(cluster_path, index=False, encoding="utf-8-sig")
            return

        df = pd.concat(rows, ignore_index=True)
        if "hall_name" in machine_df.columns and machine_df["hall_name"].nunique() > 0:
            target_halls = set(machine_df["hall_name"].astype(str).unique().tolist())
            df = df[df["hall_name"].astype(str).isin(target_halls)].copy()

        df["date"] = pd.to_datetime(df["date"], format="%Y%m%d", errors="coerce")
        df["machine_number"] = pd.to_numeric(df["machine_number"], errors="coerce")
        df["last_digit"] = df["last_digit"].astype(str).str.strip()
        df["diff_coins_normalized"] = pd.to_numeric(df["diff_coins_normalized"], errors="coerce")
        df = df.dropna(subset=["date", "machine_number", "diff_coins_normalized"]).copy()
        df["floor_head"] = df["machine_number"].astype(int).astype(str).str[0]
        df = df[df["floor_head"].isin(["2", "3"])].copy()
        df["floor_bucket"] = df["floor_head"] + "F"
        df["is_a_type"] = (
            (pd.to_numeric(df["jug_flag"], errors="coerce").fillna(0).astype(int) == 1)
            | (pd.to_numeric(df["hana_flag"], errors="coerce").fillna(0).astype(int) == 1)
            | (pd.to_numeric(df["bt_flag"], errors="coerce").fillna(0).astype(int) == 1)
        ).astype(int)
        df["atype_bucket"] = np.where(df["is_a_type"] == 1, "A", "N")
        df["group_key"] = df["floor_bucket"] + "_" + df["atype_bucket"]
        df = df[df["last_digit"].isin(digits)].copy()
        df["weekday"] = df["date"].dt.weekday.map(WEEKDAY_JA)
        df = df.dropna(subset=["weekday"]).copy()

        if df.empty:
            print("[warn] floor_atype_digit_fullweek: filtered rows empty; writing empty CSV files.")
            pd.DataFrame(columns=overall_cols).to_csv(overall_path, index=False, encoding="utf-8-sig")
            pd.DataFrame(columns=cluster_cols).to_csv(cluster_path, index=False, encoding="utf-8-sig")
            return

        overall_rows: list[dict[str, object]] = []
        for gk, gdf in df.groupby("group_key", sort=True):
            per = (
                gdf.groupby("last_digit", sort=True)["diff_coins_normalized"]
                .agg(mean_diff="mean", n_rows="count")
                .reset_index()
            )
            total_rows = int(per["n_rows"].sum()) if not per.empty else 0
            per["pct_rows"] = (per["n_rows"] / total_rows * 100.0) if total_rows > 0 else 0.0
            rank_ref = per.sort_values(["mean_diff", "last_digit"], ascending=[False, True]).reset_index(drop=True)
            rank_ref["rank"] = np.arange(1, len(rank_ref) + 1)
            rank_map = {str(r["last_digit"]): int(r["rank"]) for _, r in rank_ref.iterrows()}
            per["group_key"] = gk
            per["rank"] = per["last_digit"].astype(str).map(rank_map).fillna(999).astype(int)
            per = per[["group_key", "last_digit", "mean_diff", "n_rows", "pct_rows", "rank"]]
            overall_rows.extend(per.to_dict(orient="records"))
        overall_df = pd.DataFrame(overall_rows, columns=overall_cols)
        if not overall_df.empty:
            overall_df["group_order"] = overall_df["group_key"].map(group_order).fillna(999).astype(int)
            overall_df["digit_order"] = pd.to_numeric(overall_df["last_digit"], errors="coerce").fillna(999).astype(int)
            overall_df = overall_df.sort_values(["group_order", "digit_order"]).drop(columns=["group_order", "digit_order"]).reset_index(drop=True)
        overall_df.to_csv(overall_path, index=False, encoding="utf-8-sig")

        cluster_rows: list[dict[str, object]] = []
        for gk, gdf in df.groupby("group_key", sort=True):
            for wd in weekday_order:
                wdf = gdf[gdf["weekday"] == wd].copy()
                if wdf.empty:
                    continue
                means_s = wdf.groupby("last_digit", sort=True)["diff_coins_normalized"].mean()
                means = {d: (float(means_s.loc[d]) if d in means_s.index else np.nan) for d in digits}
                valid = {d: v for d, v in means.items() if pd.notna(v)}
                if len(valid) < 2:
                    continue
                sorted_digits = sorted(valid.keys(), key=lambda d: (-valid[d], int(d)))
                top1 = sorted_digits[0]
                top2 = sorted_digits[1] if len(sorted_digits) > 1 else "?"
                top1_mean = float(valid[top1])
                top2_mean = float(valid[top2]) if top2 != "?" else np.nan
                all_group_mean = float(np.mean(list(valid.values())))

                clusters: list[tuple[list[str], float]] = []
                for i in range(10):
                    trio = [digits[i], digits[(i + 1) % 10], digits[(i + 2) % 10]]
                    vals = [means[d] for d in trio]
                    if any(pd.isna(v) for v in vals):
                        continue
                    clusters.append((trio, float(sum(vals) / 3.0)))
                if clusters:
                    best_trio, best_avg = sorted(clusters, key=lambda x: (-x[1], tuple(int(d) for d in x[0])))[0]
                    best_cluster = "-".join(best_trio)
                    best_cluster_mean = float(best_avg)
                else:
                    best_cluster = "?"
                    best_cluster_mean = np.nan
                delta = float(best_cluster_mean - all_group_mean) if pd.notna(best_cluster_mean) else np.nan
                cluster_rows.append(
                    {
                        "group_key": gk,
                        "weekday": wd,
                        "top1_digit": top1,
                        "top1_mean": round(top1_mean, 3),
                        "top2_digit": top2,
                        "top2_mean": round(top2_mean, 3) if pd.notna(top2_mean) else np.nan,
                        "best_cluster": best_cluster,
                        "best_cluster_mean": round(best_cluster_mean, 3) if pd.notna(best_cluster_mean) else np.nan,
                        "all_group_mean": round(all_group_mean, 3),
                        "concentration_delta": round(delta, 3) if pd.notna(delta) else np.nan,
                        "n_days": int(wdf["date"].nunique()),
                    }
                )
        cluster_df = pd.DataFrame(cluster_rows, columns=cluster_cols)
        if not cluster_df.empty:
            cluster_df["group_order"] = cluster_df["group_key"].map(group_order).fillna(999).astype(int)
            cluster_df["weekday_order"] = cluster_df["weekday"].map(weekday_map).fillna(999).astype(int)
            cluster_df = cluster_df.sort_values(["group_order", "weekday_order"]).drop(columns=["group_order", "weekday_order"]).reset_index(drop=True)
        cluster_df.to_csv(cluster_path, index=False, encoding="utf-8-sig")
    except Exception as exc:
        print(f"[warn] floor_atype_digit_fullweek skipped: {exc}")
        pd.DataFrame(columns=overall_cols).to_csv(overall_path, index=False, encoding="utf-8-sig")
        pd.DataFrame(columns=cluster_cols).to_csv(cluster_path, index=False, encoding="utf-8-sig")


def _gini(values: list[float]) -> float:
    arr = np.asarray(values, dtype=float)
    if arr.size == 0:
        return float("nan")
    if np.any(arr < 0):
        arr = arr - arr.min()
    if float(arr.sum()) == 0.0:
        return 0.0
    arr = np.sort(arr)
    n = arr.size
    idx = np.arange(1, n + 1, dtype=float)
    return float((2.0 * np.sum(idx * arr)) / (n * np.sum(arr)) - (n + 1.0) / n)


def run_row_pattern_analysis(machine_df: pd.DataFrame, output_dir: Path) -> None:
    summary_path = output_dir / "row_weekday_summary.csv"
    daily_path = output_dir / "daily_row_analysis.csv"
    summary_cols = [
        "weekday",
        "mean_row_concentration_ratio",
        "mean_gini_above_mean",
        "pct_high_concentration",
        "pct_low_gini",
        "n_days",
    ]
    daily_cols = [
        "date",
        "weekday",
        "best_row_group",
        "best_row_mean",
        "all_rows_mean",
        "row_concentration_ratio",
        "gini_above_mean",
        "n_row_groups",
    ]
    try:
        weekday_order = ["月", "火", "水", "木", "金", "土", "日"]
        base = machine_df.copy()
        if "machine_number" not in base.columns:
            print("[warn] row_pattern_analysis: machine_number column missing; writing empty CSV files.")
            pd.DataFrame(columns=summary_cols).to_csv(summary_path, index=False, encoding="utf-8-sig")
            pd.DataFrame(columns=daily_cols).to_csv(daily_path, index=False, encoding="utf-8-sig")
            return

        base["machine_number"] = pd.to_numeric(base["machine_number"], errors="coerce")
        base["diff_coins_normalized"] = pd.to_numeric(base["diff_coins_normalized"], errors="coerce")
        base = base.dropna(subset=["date", "machine_number", "diff_coins_normalized"]).copy()
        if base.empty:
            print("[warn] row_pattern_analysis: base data empty; writing empty CSV files.")
            pd.DataFrame(columns=summary_cols).to_csv(summary_path, index=False, encoding="utf-8-sig")
            pd.DataFrame(columns=daily_cols).to_csv(daily_path, index=False, encoding="utf-8-sig")
            return

        base["row_group"] = (base["machine_number"] // 10).astype(int)
        base["weekday"] = base["date"].dt.weekday.map(WEEKDAY_JA)
        base = base.dropna(subset=["weekday"]).copy()

        daily_rows: list[dict[str, object]] = []
        for dt, g in base.groupby("date", sort=True):
            day_mean = float(g["diff_coins_normalized"].mean())
            if pd.isna(day_mean):
                continue
            g = g.copy()
            g["above_mean"] = (g["diff_coins_normalized"] > day_mean).astype(int)
            row = (
                g.groupby("row_group", sort=True)
                .agg(
                    row_mean=("diff_coins_normalized", "mean"),
                    above_count=("above_mean", "sum"),
                )
                .reset_index()
            )
            row = row.dropna(subset=["row_mean"]).copy()
            if row.empty:
                continue
            row = row.sort_values(["row_mean", "row_group"], ascending=[False, True]).reset_index(drop=True)
            best_row_group = int(row.iloc[0]["row_group"])
            best_row_mean = float(row.iloc[0]["row_mean"])
            all_rows_mean = float(row["row_mean"].mean())
            ratio = float(best_row_mean / all_rows_mean) if all_rows_mean != 0.0 else np.nan
            gini = _gini(row["above_count"].astype(float).tolist())
            daily_rows.append(
                {
                    "date": dt.strftime("%Y-%m-%d"),
                    "weekday": WEEKDAY_JA.get(dt.weekday(), ""),
                    "best_row_group": best_row_group,
                    "best_row_mean": best_row_mean,
                    "all_rows_mean": all_rows_mean,
                    "row_concentration_ratio": ratio,
                    "gini_above_mean": gini,
                    "n_row_groups": int(row.shape[0]),
                }
            )

        daily_df = pd.DataFrame(daily_rows, columns=daily_cols)
        daily_df.to_csv(daily_path, index=False, encoding="utf-8-sig")
        if daily_df.empty:
            pd.DataFrame(columns=summary_cols).to_csv(summary_path, index=False, encoding="utf-8-sig")
            return

        summary = (
            daily_df.groupby("weekday", sort=False)
            .agg(
                mean_row_concentration_ratio=("row_concentration_ratio", "mean"),
                mean_gini_above_mean=("gini_above_mean", "mean"),
                pct_high_concentration=("row_concentration_ratio", lambda s: float((pd.to_numeric(s, errors="coerce") > 1.5).mean() * 100.0)),
                pct_low_gini=("gini_above_mean", lambda s: float((pd.to_numeric(s, errors="coerce") < 0.3).mean() * 100.0)),
                n_days=("date", "count"),
            )
            .reset_index()
        )
        summary["weekday_order"] = summary["weekday"].map({w: i for i, w in enumerate(weekday_order)}).fillna(999).astype(int)
        summary = summary.sort_values("weekday_order").drop(columns=["weekday_order"]).reset_index(drop=True)
        for col in ["mean_row_concentration_ratio", "mean_gini_above_mean"]:
            summary[col] = pd.to_numeric(summary[col], errors="coerce").round(4)
        summary["pct_high_concentration"] = pd.to_numeric(summary["pct_high_concentration"], errors="coerce").round(1)
        summary["pct_low_gini"] = pd.to_numeric(summary["pct_low_gini"], errors="coerce").round(1)
        summary = summary.reindex(columns=summary_cols)
        summary.to_csv(summary_path, index=False, encoding="utf-8-sig")
    except Exception as exc:
        print(f"[warn] row_pattern_analysis skipped: {exc}")
        pd.DataFrame(columns=summary_cols).to_csv(summary_path, index=False, encoding="utf-8-sig")
        pd.DataFrame(columns=daily_cols).to_csv(daily_path, index=False, encoding="utf-8-sig")


def main() -> int:
    args = parse_args()
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    reports_dir = Path(args.reports_dir)

    raw = load_daily_hall_summary(args.db_glob)
    daily, daily_source = build_daily_series(raw, hall_mode=args.hall_mode)
    anomaly = compute_anomaly_report(daily, window_days=int(args.window_days), iqr_multiplier=float(args.iqr_multiplier))
    anomaly_path = out_dir / "anomaly_detection_report.csv"
    anomaly.to_csv(anomaly_path, index=False, encoding="utf-8-sig")

    pred_source = pick_prediction_source(reports_dir)
    fail_days, hit_day_experts = build_failure_days(pred_source)
    merged_fail = build_anomaly_vs_fail(anomaly, fail_days)
    merged_path = out_dir / "anomaly_vs_prediction_fail.csv"
    merged_fail.to_csv(merged_path, index=False, encoding="utf-8-sig")

    full_history = load_latest_full_history(reports_dir)
    events = build_tail_hit_events(full_history, hit_day_experts=hit_day_experts)
    intervals = intervals_from_events(events)
    by_expert, by_tail = summarize_intervals(intervals)
    hit_pair_count = len(hit_day_experts)
    covered_pairs = events[["date", "expert"]].drop_duplicates().shape[0] if not events.empty else 0
    coverage_text = f"hit(日×expert) {covered_pairs}/{hit_pair_count} で tail-level 復元可能"

    survival_report = build_survival_report(
        by_expert,
        by_tail,
        intervals,
        source_kind=pred_source.kind,
        source_path=str(pred_source.path),
        full_coverage=coverage_text,
    )
    survival_path = out_dir / "survival_analysis_report.csv"
    survival_report.to_csv(survival_path, index=False, encoding="utf-8-sig")

    machine_raw = load_machine_detailed_results(args.db_glob)
    machine_work = _select_hall_mode(machine_raw, args.hall_mode, date_col="date")
    selected = set(args.analyses)
    if "all" in selected:
        selected = {
            "chi_square",
            "acf_pacf",
            "kruskal",
            "mutual_info",
            "mutual_info_ltr",
            "acf_per_digit",
            "adf_stationarity",
            "stl_decompose",
            "vif",
            "multiple_testing_bh",
            "digit3_profile",
            "weekday_digit_cross",
            "day7_hypothesis",
            "weekday_cluster_direction",
            "two_cluster_distance",
            "above_mean_streak",
            "weekday_machine_digit_cross",
            "bt_digit_fullweek",
            "atype_digit_fullweek",
            "row_pattern_analysis",
            "floor_atype_digit_fullweek",
        }
    if "chi_square" in selected:
        run_chi_square_analysis(machine_work, out_dir)
    if "acf_pacf" in selected:
        run_acf_pacf_analysis(daily, out_dir)
    if "kruskal" in selected:
        run_kruskal_analysis(daily, machine_work, out_dir)
    if "mutual_info" in selected:
        run_mutual_info_analysis(daily, out_dir)
    if "mutual_info_ltr" in selected:
        run_mutual_info_ltr_analysis(machine_work, daily, out_dir)
    if "acf_per_digit" in selected:
        run_acf_per_digit_analysis(machine_work, out_dir)
    if "adf_stationarity" in selected:
        run_adf_stationarity_analysis(daily, out_dir)
    if "stl_decompose" in selected:
        run_stl_decompose_analysis(daily, out_dir)
    if "vif" in selected:
        run_vif_analysis(daily, out_dir)
    if "multiple_testing_bh" in selected:
        run_multiple_testing_bh(out_dir)
    if "digit3_profile" in selected:
        run_digit3_profile(machine_work, args.db_glob, out_dir)
    if "weekday_digit_cross" in selected:
        run_weekday_digit_cross(machine_work, anomaly_path, out_dir)
    if "day7_hypothesis" in selected:
        run_day7_hypothesis(machine_work, out_dir)
    if "weekday_cluster_direction" in selected:
        run_weekday_cluster_direction(machine_work, out_dir)
    if "two_cluster_distance" in selected:
        run_two_cluster_distance_analysis(machine_work, out_dir)
    if "above_mean_streak" in selected:
        run_above_mean_streak(machine_work, out_dir)
    if "weekday_machine_digit_cross" in selected:
        run_weekday_machine_digit_cross(machine_work, args.db_glob, out_dir)
    if "bt_digit_fullweek" in selected:
        run_bt_digit_fullweek(machine_work, args.db_glob, out_dir)
    if "atype_digit_fullweek" in selected:
        run_atype_digit_fullweek(machine_work, args.db_glob, out_dir)
    if "row_pattern_analysis" in selected:
        run_row_pattern_analysis(machine_work, out_dir)
    if "floor_atype_digit_fullweek" in selected:
        run_floor_atype_digit_fullweek(machine_work, args.db_glob, out_dir)

    print(f"[source] daily_hall_summary={daily_source}")
    print(f"[source] prediction={pred_source.kind}:{pred_source.path}")
    print_anomaly_summary(anomaly, merged_fail, args.monthly_start, args.monthly_end)
    print_survival_summary(by_expert, by_tail, intervals, coverage_text=coverage_text)
    print("\n=== 出力ファイル ===")
    print(anomaly_path.as_posix())
    print(merged_path.as_posix())
    print(survival_path.as_posix())
    if "chi_square" in selected:
        print((out_dir / "chi_square_report.csv").as_posix())
    if "acf_pacf" in selected:
        print((out_dir / "acf_pacf_report.csv").as_posix())
    if "kruskal" in selected:
        print((out_dir / "kruskal_report.csv").as_posix())
    if "mutual_info" in selected:
        print((out_dir / "mutual_info_report.csv").as_posix())
    if "mutual_info_ltr" in selected:
        print((out_dir / "mutual_info_ltr_report.csv").as_posix())
    if "acf_per_digit" in selected:
        print((out_dir / "acf_per_digit_report.csv").as_posix())
    if "adf_stationarity" in selected:
        print((out_dir / "adf_report.csv").as_posix())
    if "stl_decompose" in selected:
        print((out_dir / "stl_summary_report.csv").as_posix())
        print((out_dir / "stl_daily_components.csv").as_posix())
    if "vif" in selected:
        print((out_dir / "vif_report.csv").as_posix())
    if "multiple_testing_bh" in selected:
        print((out_dir / "multiple_testing_bh_report.csv").as_posix())
    if "digit3_profile" in selected:
        print((out_dir / "digit3_profile_report.csv").as_posix())
    if "weekday_digit_cross" in selected:
        print((out_dir / "weekday_digit_cross_report.csv").as_posix())
        print((out_dir / "high_anomaly_digit_dist.csv").as_posix())
    if "day7_hypothesis" in selected:
        print((out_dir / "day7_digit_report.csv").as_posix())
        print((out_dir / "special_weekday_digit_report.csv").as_posix())
        print((out_dir / "digit7_vicinity_summary.csv").as_posix())
    if "weekday_cluster_direction" in selected:
        print((out_dir / "weekday_cluster_analysis.csv").as_posix())
    if "two_cluster_distance" in selected:
        print((out_dir / "weekday_concentration.csv").as_posix())
        print((out_dir / "daily_top2_distance.csv").as_posix())
        print((out_dir / "distance_distribution.csv").as_posix())
    if "above_mean_streak" in selected:
        print((out_dir / "above_mean_streak_report.csv").as_posix())
        print((out_dir / "daily_above_mean_streak.csv").as_posix())
    if "weekday_machine_digit_cross" in selected:
        print((out_dir / "weekday_machine_digit_cross.csv").as_posix())
        print((out_dir / "weekday_machine_top_digits.csv").as_posix())
    if "bt_digit_fullweek" in selected:
        print((out_dir / "bt_overall_digit.csv").as_posix())
        print((out_dir / "bt_mode_classification.csv").as_posix())
        print((out_dir / "bt_weekday_digit_cross.csv").as_posix())
        print((out_dir / "bt_weekday_cluster.csv").as_posix())
    if "atype_digit_fullweek" in selected:
        print((out_dir / "atype_overall_digit.csv").as_posix())
        print((out_dir / "atype_weekday_digit_cross.csv").as_posix())
        print((out_dir / "atype_weekday_cluster.csv").as_posix())
        print((out_dir / "non_at_overall_digit.csv").as_posix())
    if "row_pattern_analysis" in selected:
        print((out_dir / "row_weekday_summary.csv").as_posix())
        print((out_dir / "daily_row_analysis.csv").as_posix())
    if "floor_atype_digit_fullweek" in selected:
        print((out_dir / "floor_atype_overall_digit.csv").as_posix())
        print((out_dir / "floor_atype_weekday_cluster.csv").as_posix())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
