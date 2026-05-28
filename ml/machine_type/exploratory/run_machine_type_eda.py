from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy import stats
from sklearn.feature_selection import mutual_info_classif
from sklearn.inspection import permutation_importance
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
from sklearn.model_selection import TimeSeriesSplit

try:
    from statsmodels.tsa.stattools import acf as sm_acf
    from statsmodels.tsa.stattools import adfuller as sm_adfuller
except Exception:  # pragma: no cover
    sm_acf = None
    sm_adfuller = None


WEEKDAY_JA = {
    0: "月",
    1: "火",
    2: "水",
    3: "木",
    4: "金",
    5: "土",
    6: "日",
}


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Machine-name entity EDA runner (Kamata7 single hall)")
    p.add_argument("--db-glob", default="db/マルハンメガシティ2000-蒲田7.db")
    p.add_argument("--output-dir", default="ml/machine_type/exploratory/output/kamata7_only")
    p.add_argument("--acf-nlags", type=int, default=30)
    p.add_argument("--anomaly-window", type=int, default=30)
    p.add_argument("--min-entity-days", type=int, default=60)
    p.add_argument("--eval-days", type=int, default=120)
    p.add_argument("--min-train-days", type=int, default=120)
    p.add_argument("--bootstrap-repeats", type=int, default=300)
    p.add_argument("--bootstrap-block-size", type=int, default=7)
    p.add_argument("--recent-days", type=int, default=60)
    return p.parse_args()


def classify_machine_type(jug_flag: Any, hana_flag: Any, bt_flag: Any) -> str:
    jug = int(pd.to_numeric(jug_flag, errors="coerce") or 0)
    hana = int(pd.to_numeric(hana_flag, errors="coerce") or 0)
    bt = int(pd.to_numeric(bt_flag, errors="coerce") or 0)
    if jug == 1 or hana == 1:
        return "A型"
    if bt == 1:
        return "BT"
    return "AT系"


def _date_to_weekday_ja(s: pd.Series) -> pd.Series:
    return s.dt.dayofweek.map(WEEKDAY_JA).fillna("不明")


def _mode_or_default(s: pd.Series, default: str = "AT系") -> str:
    m = s.mode()
    if m.empty:
        return default
    return str(m.iloc[0])


def _bh_adjust(p_values: list[float]) -> list[float]:
    arr = np.asarray(p_values, dtype=float)
    out = np.full(arr.shape, np.nan, dtype=float)
    mask = np.isfinite(arr)
    vals = arr[mask]
    if vals.size == 0:
        return out.tolist()
    order = np.argsort(vals)
    ranked = vals[order]
    m = float(len(ranked))
    q = ranked * m / (np.arange(1, len(ranked) + 1))
    q = np.minimum.accumulate(q[::-1])[::-1]
    q = np.clip(q, 0.0, 1.0)
    restored = np.empty_like(q)
    restored[order] = q
    out[mask] = restored
    return out.tolist()


def _cramers_v(table: pd.DataFrame) -> float:
    if table.empty:
        return np.nan
    try:
        chi2, _, _, _ = stats.chi2_contingency(table)
    except ValueError:
        return np.nan
    n = float(table.to_numpy().sum())
    r, c = table.shape
    denom = n * max(min(r - 1, c - 1), 0)
    if denom <= 0:
        return np.nan
    return float(np.sqrt(chi2 / denom))


def _cliffs_delta(x: np.ndarray, y: np.ndarray) -> float:
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    x = x[np.isfinite(x)]
    y = y[np.isfinite(y)]
    if x.size == 0 or y.size == 0:
        return np.nan
    u_stat, _ = stats.mannwhitneyu(x, y, alternative="two-sided")
    a12 = u_stat / float(x.size * y.size)
    return float((2.0 * a12) - 1.0)


def load_entity_daily_frame(db_glob: str) -> pd.DataFrame:
    db_paths = sorted(Path().glob(db_glob))
    if not db_paths:
        raise FileNotFoundError(f"No DB matched: {db_glob}")
    if len(db_paths) != 1:
        raise ValueError(f"Expected exactly 1 hall DB, got {len(db_paths)}: {db_glob}")

    con = sqlite3.connect(db_paths[0])
    try:
        q = """
        SELECT
            mdr.date,
            mdr.machine_name,
            COALESCE(mm.jug_flag, 0) AS jug_flag,
            COALESCE(mm.hana_flag, 0) AS hana_flag,
            COALESCE(mm.bt_flag, 0) AS bt_flag,
            mdr.diff_coins_normalized,
            mdr.games_normalized
        FROM machine_detailed_results mdr
        LEFT JOIN machine_master mm
          ON mdr.machine_name = mm.machine_name_normalized
        """
        raw = pd.read_sql_query(q, con)
    finally:
        con.close()

    if raw.empty:
        raise ValueError("machine_detailed_results returned no rows")

    raw["date"] = pd.to_datetime(raw["date"], format="%Y%m%d", errors="coerce")
    raw = raw.dropna(subset=["date", "machine_name"]).copy()
    raw["diff_coins_normalized"] = pd.to_numeric(raw["diff_coins_normalized"], errors="coerce").fillna(0.0)
    raw["games_normalized"] = pd.to_numeric(raw["games_normalized"], errors="coerce").fillna(0.0)
    for col in ("jug_flag", "hana_flag", "bt_flag"):
        raw[col] = pd.to_numeric(raw[col], errors="coerce").fillna(0).astype(int)

    out = (
        raw.groupby(["date", "machine_name", "jug_flag", "hana_flag", "bt_flag"], sort=True)
        .agg(
            n_machines=("machine_name", "size"),
            total_diff=("diff_coins_normalized", "sum"),
            avg_diff=("diff_coins_normalized", "mean"),
            avg_games=("games_normalized", "mean"),
            win_rate=("diff_coins_normalized", lambda s: float((s > 0).mean())),
        )
        .reset_index()
    )
    out["entity"] = out["machine_name"].astype(str)
    out["entity_encoded"] = pd.factorize(out["entity"])[0].astype(int)
    out["machine_type"] = out.apply(
        lambda r: classify_machine_type(r["jug_flag"], r["hana_flag"], r["bt_flag"]),
        axis=1,
    )
    out["machine_type_encoded"] = out["machine_type"].map({"AT系": 0, "A型": 1, "BT": 2}).fillna(-1).astype(int)
    out["is_at_series"] = (out["machine_type"] == "AT系").astype(int)
    out["is_atype"] = (out["machine_type"] == "A型").astype(int)
    out["is_bt"] = (out["machine_type"] == "BT").astype(int)
    out["weekday"] = _date_to_weekday_ja(out["date"])
    out["day_of_week_num"] = out["date"].dt.dayofweek.astype(int)
    out["day_of_month"] = out["date"].dt.day.astype(int)
    out["is_weekend"] = out["day_of_week_num"].isin([5, 6]).astype(int)
    out["dow_sin"] = np.sin(2.0 * np.pi * out["day_of_week_num"] / 7.0)
    out["dow_cos"] = np.cos(2.0 * np.pi * out["day_of_week_num"] / 7.0)

    out["rank"] = out.groupby("date", sort=False)["avg_diff"].rank(method="first", ascending=False)
    out["is_rank_1"] = (out["rank"] == 1).astype(int)
    day_n = out.groupby("date", sort=False)["entity"].transform("nunique").clip(lower=1)
    out["rank_pct"] = np.where(day_n > 1, (out["rank"] - 1.0) / (day_n - 1.0), 0.0)
    out = out.sort_values(["date", "entity"]).reset_index(drop=True)
    return out


def prepare_entity_feature_frame(entity_daily: pd.DataFrame) -> pd.DataFrame:
    work = entity_daily.sort_values(["entity", "date"]).copy()
    g_list: list[pd.DataFrame] = []
    for _, g in work.groupby("entity", sort=False):
        h = g.sort_values("date").copy()
        h["lag1_rank_pct"] = h["rank_pct"].shift(1)
        h["lag3_rank_pct"] = h["rank_pct"].shift(3)
        h["lag7_rank_pct"] = h["rank_pct"].shift(7)
        h["lag14_rank_pct"] = h["rank_pct"].shift(14)
        h["roll7_rank_pct"] = h["rank_pct"].shift(1).rolling(window=7, min_periods=1).mean()
        h["roll14_rank_pct"] = h["rank_pct"].shift(1).rolling(window=14, min_periods=1).mean()
        h["prior_top1_rate"] = h["is_rank_1"].shift(1).expanding(min_periods=1).mean().fillna(0.0)
        h["weekday_prior_top1_rate"] = (
            h.groupby("day_of_week_num", sort=False)["is_rank_1"]
            .transform(lambda s: s.shift(1).expanding(min_periods=1).mean())
            .fillna(0.0)
        )
        h["delta_lag1_7"] = h["lag1_rank_pct"] - h["lag7_rank_pct"]
        g_list.append(h)
    out = pd.concat(g_list, ignore_index=True)
    return out


def run_base_diff(df: pd.DataFrame, out_dir: Path) -> pd.DataFrame:
    out = (
        df.groupby("entity", sort=True)
        .agg(
            machine_type=("machine_type", _mode_or_default),
            mean_diff=("avg_diff", "mean"),
            median_diff=("avg_diff", "median"),
            std_diff=("avg_diff", "std"),
            n_days=("date", "nunique"),
        )
        .reset_index()
    )
    out.to_csv(out_dir / "machine_name_base_diff.csv", index=False, encoding="utf-8-sig")
    return out


def run_chi_square(df: pd.DataFrame, out_dir: Path) -> pd.DataFrame:
    ct = pd.crosstab(df["weekday"], df["entity"], values=df["is_rank_1"], aggfunc="sum").fillna(0.0)
    ct = ct.loc[ct.sum(axis=1) > 0, ct.sum(axis=0) > 0]
    chi2, p_val, dof = np.nan, np.nan, np.nan
    expected = np.full(ct.shape, np.nan)
    if ct.shape[0] >= 2 and ct.shape[1] >= 2 and float(ct.to_numpy().sum()) > 0:
        try:
            chi2, p_val, dof, expected = stats.chi2_contingency(ct)
        except ValueError:
            pass
    cramers_v = _cramers_v(ct)
    expected_df = pd.DataFrame(expected, index=ct.index, columns=ct.columns)
    residual_df = ct - expected_df

    rows: list[dict[str, Any]] = []
    for wd in ct.index:
        for entity in ct.columns:
            rows.append(
                {
                    "weekday": wd,
                    "entity": entity,
                    "observed_top1": float(ct.loc[wd, entity]),
                    "expected_top1": float(expected_df.loc[wd, entity]) if pd.notna(expected_df.loc[wd, entity]) else np.nan,
                    "residual": float(residual_df.loc[wd, entity]) if pd.notna(residual_df.loc[wd, entity]) else np.nan,
                    "chi2": float(chi2) if pd.notna(chi2) else np.nan,
                    "p_value": float(p_val) if pd.notna(p_val) else np.nan,
                    "dof": int(dof) if pd.notna(dof) else np.nan,
                    "cramers_v": cramers_v,
                    "is_significant_5pct": int(pd.notna(p_val) and p_val < 0.05),
                }
            )
    out = pd.DataFrame(rows)
    out.to_csv(out_dir / "chi_square_weekday_entity.csv", index=False, encoding="utf-8-sig")
    return out


def run_kruskal(df: pd.DataFrame, out_dir: Path, min_entity_days: int) -> pd.DataFrame:
    eligible = df.groupby("entity", sort=True)["date"].nunique().reset_index(name="n_days")
    keep_entities = set(eligible.loc[eligible["n_days"] >= min_entity_days, "entity"].astype(str))
    sub = df[df["entity"].isin(keep_entities)].copy()
    entities = sorted(sub["entity"].astype(str).unique().tolist())
    rows: list[dict[str, Any]] = []

    groups = [sub.loc[sub["entity"].eq(e), "rank_pct"].dropna().to_numpy() for e in entities]
    valid_groups = [g for g in groups if len(g) > 0]
    stat, p_val = (stats.kruskal(*valid_groups) if len(valid_groups) >= 2 else (np.nan, np.nan))
    rows.append(
        {
            "test_type": "kruskal_overall",
            "group_a": "ALL",
            "group_b": "ALL",
            "n_entities": int(len(entities)),
            "statistic": float(stat) if pd.notna(stat) else np.nan,
            "p_value": float(p_val) if pd.notna(p_val) else np.nan,
            "cliffs_delta": np.nan,
            "is_significant_5pct": int(pd.notna(p_val) and p_val < 0.05),
        }
    )

    for i, a in enumerate(entities):
        for b in entities[i + 1 :]:
            xa = sub.loc[sub["entity"].eq(a), "rank_pct"].dropna().to_numpy()
            xb = sub.loc[sub["entity"].eq(b), "rank_pct"].dropna().to_numpy()
            if len(xa) == 0 or len(xb) == 0:
                u_stat, p_pair, delta = np.nan, np.nan, np.nan
            else:
                u_stat, p_pair = stats.mannwhitneyu(xa, xb, alternative="two-sided")
                delta = _cliffs_delta(xa, xb)
            rows.append(
                {
                    "test_type": "mannwhitney_pair",
                    "group_a": a,
                    "group_b": b,
                    "n_entities": int(len(entities)),
                    "statistic": float(u_stat) if pd.notna(u_stat) else np.nan,
                    "p_value": float(p_pair) if pd.notna(p_pair) else np.nan,
                    "cliffs_delta": delta,
                    "is_significant_5pct": int(pd.notna(p_pair) and p_pair < 0.05),
                }
            )

    out = pd.DataFrame(rows)
    out.to_csv(out_dir / "kruskal_entity.csv", index=False, encoding="utf-8-sig")
    return out


def run_acf_per_entity(entity_daily: pd.DataFrame, out_dir: Path, nlags: int) -> pd.DataFrame:
    all_dates = pd.date_range(entity_daily["date"].min(), entity_daily["date"].max(), freq="D")
    rows: list[dict[str, Any]] = []
    for entity, g in entity_daily.groupby("entity", sort=True):
        ts = g.set_index("date")["is_rank_1"].reindex(all_dates, fill_value=0).astype(float)
        n = len(ts)
        threshold = float(2.0 / np.sqrt(max(n, 1)))
        if sm_acf is None or float(np.nanvar(ts.to_numpy(dtype=float))) == 0.0:
            for lag in range(1, nlags + 1):
                rows.append(
                    {"entity": entity, "lag": lag, "acf_value": np.nan, "significance_threshold": threshold, "is_significant": 0}
                )
            continue
        acf_vals = sm_acf(ts.to_numpy(dtype=float), nlags=nlags, fft=True, missing="drop")
        for lag in range(1, min(nlags, len(acf_vals) - 1) + 1):
            v = float(acf_vals[lag])
            rows.append(
                {"entity": entity, "lag": lag, "acf_value": v, "significance_threshold": threshold, "is_significant": int(abs(v) > threshold)}
            )
    out = pd.DataFrame(rows)
    out.to_csv(out_dir / "acf_per_entity.csv", index=False, encoding="utf-8-sig")
    return out


def run_adf(entity_daily: pd.DataFrame, out_dir: Path) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for entity, g in entity_daily.groupby("entity", sort=True):
        ts = g.sort_values("date")["avg_diff"].dropna()
        if sm_adfuller is None or len(ts) < 20:
            rows.append({"entity": entity, "n_obs": int(len(ts)), "adf_stat": np.nan, "p_value": np.nan, "used_lag": np.nan, "is_stationary_5pct": 0})
            continue
        try:
            adf_stat, p_val, used_lag, *_ = sm_adfuller(ts.to_numpy(dtype=float))
            rows.append(
                {"entity": entity, "n_obs": int(len(ts)), "adf_stat": float(adf_stat), "p_value": float(p_val), "used_lag": int(used_lag), "is_stationary_5pct": int(p_val < 0.05)}
            )
        except Exception:
            rows.append({"entity": entity, "n_obs": int(len(ts)), "adf_stat": np.nan, "p_value": np.nan, "used_lag": np.nan, "is_stationary_5pct": 0})
    out = pd.DataFrame(rows)
    out.to_csv(out_dir / "adf_entity.csv", index=False, encoding="utf-8-sig")
    return out


def run_weekday_entity_cross(df: pd.DataFrame, out_dir: Path) -> pd.DataFrame:
    out = (
        df.groupby(["weekday", "entity"], sort=True)
        .agg(
            machine_type=("machine_type", _mode_or_default),
            mean_diff=("avg_diff", "mean"),
            rank_pct_mean=("rank_pct", "mean"),
            n_days=("date", "nunique"),
            top1_rate=("is_rank_1", "mean"),
        )
        .reset_index()
    )
    out.to_csv(out_dir / "weekday_entity_cross.csv", index=False, encoding="utf-8-sig")
    return out


def _date_based_time_series_auc(df: pd.DataFrame, feature_col: str, target_col: str, n_splits: int = 5) -> float:
    work = df.dropna(subset=[feature_col, target_col, "date"]).sort_values("date").copy()
    if work.empty:
        return np.nan
    unique_dates = np.array(sorted(work["date"].unique()))
    if len(unique_dates) < 10:
        return np.nan
    tscv = TimeSeriesSplit(n_splits=min(max(2, n_splits), len(unique_dates) - 1))
    aucs: list[float] = []
    for tr_idx, te_idx in tscv.split(unique_dates):
        tr_dates = set(unique_dates[tr_idx])
        te_dates = set(unique_dates[te_idx])
        tr = work[work["date"].isin(tr_dates)]
        te = work[work["date"].isin(te_dates)]
        if tr.empty or te.empty:
            continue
        y_tr = tr[target_col].astype(int).to_numpy()
        y_te = te[target_col].astype(int).to_numpy()
        if len(np.unique(y_tr)) < 2 or len(np.unique(y_te)) < 2:
            continue
        model = LogisticRegression(max_iter=1000, solver="lbfgs")
        model.fit(tr[[feature_col]].to_numpy(dtype=float), y_tr)
        score = model.predict_proba(te[[feature_col]].to_numpy(dtype=float))[:, 1]
        aucs.append(float(roc_auc_score(y_te, score)))
    if not aucs:
        return np.nan
    return float(np.mean(aucs))


def run_lag_screening(entity_daily: pd.DataFrame, out_dir: Path) -> pd.DataFrame:
    lags = [1, 2, 3, 5, 7, 10, 14, 21, 28]
    work = entity_daily.sort_values(["entity", "date"]).copy()
    rows: list[dict[str, Any]] = []
    for lag in lags:
        feat = f"lag{lag}_rank_pct"
        work[feat] = work.groupby("entity", sort=False)["rank_pct"].shift(lag)
        valid = work.dropna(subset=[feat, "is_rank_1"]).copy()
        if valid.empty:
            spearman_r, p_val, cv_auc = np.nan, np.nan, np.nan
        else:
            spearman_r, p_val = stats.spearmanr(valid[feat].to_numpy(dtype=float), valid["is_rank_1"].to_numpy(dtype=float))
            cv_auc = _date_based_time_series_auc(valid, feat, "is_rank_1", n_splits=5)
        if pd.isna(spearman_r):
            direction = "near-zero"
        elif spearman_r > 0.02:
            direction = "positive"
        elif spearman_r < -0.02:
            direction = "negative"
        else:
            direction = "near-zero"
        rows.append(
            {"lag": lag, "cv_auc": cv_auc, "spearman_r": spearman_r, "spearman_p_value": p_val, "direction": direction, "n_samples": int(len(valid))}
        )
    out = pd.DataFrame(rows)
    out.to_csv(out_dir / "lag_screening_entity.csv", index=False, encoding="utf-8-sig")
    return out


def run_mi_screening(entity_daily: pd.DataFrame, out_dir: Path) -> pd.DataFrame:
    work = prepare_entity_feature_frame(entity_daily)
    features = [
        "lag1_rank_pct",
        "lag7_rank_pct",
        "roll7_rank_pct",
        "prior_top1_rate",
        "weekday_prior_top1_rate",
        "entity_encoded",
        "machine_type_encoded",
        "is_at_series",
        "is_atype",
        "is_bt",
    ]
    valid = work.dropna(subset=["is_rank_1"]).copy()
    x = valid[features].fillna(0.0)
    y = valid["is_rank_1"].astype(int)
    if len(valid) == 0 or y.nunique() < 2:
        out = pd.DataFrame({"feature": features, "mi_score": [np.nan] * len(features)})
    else:
        mi = mutual_info_classif(x, y, random_state=42)
        out = pd.DataFrame({"feature": features, "mi_score": mi})
    out = out.sort_values("mi_score", ascending=False, na_position="last").reset_index(drop=True)
    out.to_csv(out_dir / "mi_entity_features.csv", index=False, encoding="utf-8-sig")
    return out


def detect_high_anomalies(entity_daily: pd.DataFrame, window: int = 30) -> pd.DataFrame:
    daily = entity_daily.groupby("date", sort=True).agg(avg_diff=("avg_diff", "mean")).reset_index().sort_values("date")
    daily["weekday"] = _date_to_weekday_ja(daily["date"])
    daily["rolling_median"] = daily["avg_diff"].rolling(window=window, min_periods=7).median()
    q1 = daily["avg_diff"].rolling(window=window, min_periods=7).quantile(0.25)
    q3 = daily["avg_diff"].rolling(window=window, min_periods=7).quantile(0.75)
    iqr = (q3 - q1).fillna(0.0)
    daily["upper"] = (daily["rolling_median"] + 1.5 * iqr).fillna(np.inf)
    daily["lower"] = (daily["rolling_median"] - 1.5 * iqr).fillna(-np.inf)
    daily["is_anomaly"] = ((daily["avg_diff"] > daily["upper"]) | (daily["avg_diff"] < daily["lower"])).astype(int)
    daily["anomaly_direction"] = np.where(daily["avg_diff"] > daily["upper"], "high", np.where(daily["avg_diff"] < daily["lower"], "low", "none"))
    return daily


def run_anomaly_response(entity_daily: pd.DataFrame, out_dir: Path, window: int, min_entity_days: int) -> pd.DataFrame:
    anomaly_df = detect_high_anomalies(entity_daily, window=window)
    high_dates = set(anomaly_df.loc[anomaly_df["anomaly_direction"].eq("high"), "date"])
    normal_dates = set(anomaly_df.loc[anomaly_df["is_anomaly"].eq(0), "date"])
    eligible = entity_daily.groupby("entity", sort=True)["date"].nunique().reset_index(name="n_days")
    keep = set(eligible.loc[eligible["n_days"] >= min_entity_days, "entity"].astype(str))
    rows: list[dict[str, Any]] = []
    for entity, sub in entity_daily[entity_daily["entity"].isin(keep)].groupby("entity", sort=True):
        anom = sub[sub["date"].isin(high_dates)]["rank_pct"]
        norm = sub[sub["date"].isin(normal_dates)]["rank_pct"]
        anom_mean = float(anom.mean()) if len(anom) else np.nan
        norm_mean = float(norm.mean()) if len(norm) else np.nan
        change_pct = float((norm_mean - anom_mean) / norm_mean) if pd.notna(anom_mean) and pd.notna(norm_mean) and norm_mean != 0 else np.nan
        rows.append(
            {
                "entity": entity,
                "machine_type": _mode_or_default(sub["machine_type"]),
                "high_anomaly_days": int(len(anom)),
                "normal_days": int(len(norm)),
                "rank_pct_high_anomaly_mean": anom_mean,
                "rank_pct_normal_mean": norm_mean,
                "change_pct": change_pct,
                "enough_high_sample_ge5": int(len(anom) >= 5),
            }
        )
    out = pd.DataFrame(rows)
    out.to_csv(out_dir / "entity_anomaly_response.csv", index=False, encoding="utf-8-sig")
    anomaly_df.to_csv(out_dir / "entity_anomaly_detection_daily.csv", index=False, encoding="utf-8-sig")
    return out


def run_streak(entity_daily: pd.DataFrame, out_dir: Path) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for entity, g in entity_daily.groupby("entity", sort=True):
        h = g.sort_values("date").copy()
        h["flag"] = h["is_rank_1"].astype(int)
        h["streak_id"] = (h["flag"] != h["flag"].shift(1)).cumsum()
        streaks = h[h["flag"].eq(1)].groupby("streak_id", sort=False).size()
        if streaks.empty:
            rows.append({"entity": entity, "machine_type": _mode_or_default(h["machine_type"]), "n_streaks": 0, "mean_streak_days": 0.0, "median_streak_days": 0.0, "pct_streak_1day": 0.0, "pct_streak_ge2days": 0.0})
        else:
            rows.append(
                {
                    "entity": entity,
                    "machine_type": _mode_or_default(h["machine_type"]),
                    "n_streaks": int(len(streaks)),
                    "mean_streak_days": float(streaks.mean()),
                    "median_streak_days": float(streaks.median()),
                    "pct_streak_1day": float((streaks.eq(1).mean()) * 100.0),
                    "pct_streak_ge2days": float((streaks.ge(2).mean()) * 100.0),
                }
            )
    out = pd.DataFrame(rows)
    out.to_csv(out_dir / "entity_streak.csv", index=False, encoding="utf-8-sig")
    return out


def _block_bootstrap_mean_ci(values: np.ndarray, block_size: int, n_boot: int, seed: int = 42) -> tuple[float, float, float]:
    vals = np.asarray(values, dtype=float)
    vals = vals[np.isfinite(vals)]
    if vals.size == 0:
        return np.nan, np.nan, np.nan
    rng = np.random.default_rng(seed)
    n = vals.size
    b = max(1, min(int(block_size), n))
    means = np.zeros(max(1, int(n_boot)), dtype=float)
    for i in range(len(means)):
        idx: list[int] = []
        while len(idx) < n:
            start = int(rng.integers(0, n))
            idx.extend([(start + j) % n for j in range(b)])
        sample = vals[np.array(idx[:n], dtype=int)]
        means[i] = float(np.mean(sample))
    return float(np.mean(vals)), float(np.quantile(means, 0.025)), float(np.quantile(means, 0.975))


def _evaluate_hitk_daily(
    feature_df: pd.DataFrame,
    feature_cols: list[str],
    eval_days: int,
    min_train_days: int,
) -> pd.DataFrame:
    work = feature_df.copy()
    unique_dates = np.array(sorted(work["date"].unique()))
    if len(unique_dates) <= min_train_days + 1:
        return pd.DataFrame()
    start = max(min_train_days, len(unique_dates) - max(int(eval_days), 1))
    eval_dates = unique_dates[start:]
    rows: list[dict[str, Any]] = []

    for pred_date in eval_dates:
        tr = work[work["date"] < pred_date].dropna(subset=feature_cols + ["is_rank_1"]).copy()
        te = work[work["date"] == pred_date].dropna(subset=feature_cols + ["is_rank_1"]).copy()
        if tr.empty or te.empty:
            continue
        if tr["is_rank_1"].nunique() < 2:
            continue
        model = LogisticRegression(max_iter=1200, solver="lbfgs", class_weight="balanced")
        x_tr = tr[feature_cols].to_numpy(dtype=float)
        y_tr = tr["is_rank_1"].astype(int).to_numpy()
        x_te = te[feature_cols].to_numpy(dtype=float)
        model.fit(x_tr, y_tr)
        te = te.sort_values("rank", ascending=True).copy()
        true_top1_entity = str(te.iloc[0]["entity"])
        te["score"] = model.predict_proba(x_te)[:, 1]
        pred_order = te.sort_values("score", ascending=False)["entity"].astype(str).tolist()
        rows.append(
            {
                "date": pd.Timestamp(pred_date),
                "n_entities": int(len(te)),
                "hit_at_1": int(true_top1_entity in pred_order[:1]),
                "hit_at_3": int(true_top1_entity in pred_order[:3]),
                "hit_at_5": int(true_top1_entity in pred_order[:5]),
            }
        )
    return pd.DataFrame(rows).sort_values("date").reset_index(drop=True)


def run_hitk_bootstrap_and_ablation(
    entity_daily: pd.DataFrame,
    out_dir: Path,
    eval_days: int,
    min_train_days: int,
    n_boot: int,
    block_size: int,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    f = prepare_entity_feature_frame(entity_daily)
    lag_features = ["lag1_rank_pct", "lag3_rank_pct", "lag7_rank_pct", "lag14_rank_pct", "roll7_rank_pct", "roll14_rank_pct", "delta_lag1_7", "prior_top1_rate", "weekday_prior_top1_rate"]
    calendar_features = ["day_of_week_num", "day_of_month", "is_weekend", "dow_sin", "dow_cos"]
    entity_features = ["entity_encoded", "machine_type_encoded", "is_at_series", "is_atype", "is_bt"]
    all_features = lag_features + calendar_features + entity_features

    settings = {
        "all": all_features,
        "no_lag": calendar_features + entity_features,
        "no_calendar": lag_features + entity_features,
        "no_entity": lag_features + calendar_features,
    }

    ci_rows: list[dict[str, Any]] = []
    abl_rows: list[dict[str, Any]] = []
    all_ref: dict[str, float] = {}

    for name, cols in settings.items():
        daily = _evaluate_hitk_daily(f, cols, eval_days=eval_days, min_train_days=min_train_days)
        if daily.empty:
            for k in (1, 3, 5):
                ci_rows.append({"setting": name, "metric": f"hit_at_{k}", "mean": np.nan, "ci_low": np.nan, "ci_high": np.nan, "n_days": 0, "random_baseline": np.nan, "lift_vs_random": np.nan})
            continue
        mean_n = float(daily["n_entities"].mean()) if len(daily) else np.nan
        for k in (1, 3, 5):
            arr = daily[f"hit_at_{k}"].to_numpy(dtype=float)
            mean_v, low, high = _block_bootstrap_mean_ci(arr, block_size=block_size, n_boot=n_boot, seed=42 + k)
            random_base = float(np.mean(np.clip(k / np.maximum(daily["n_entities"].to_numpy(dtype=float), 1.0), 0.0, 1.0)))
            lift = mean_v / random_base if random_base > 0 else np.nan
            ci_rows.append(
                {
                    "setting": name,
                    "metric": f"hit_at_{k}",
                    "mean": mean_v,
                    "ci_low": low,
                    "ci_high": high,
                    "n_days": int(len(daily)),
                    "avg_entities": mean_n,
                    "random_baseline": random_base,
                    "lift_vs_random": lift,
                }
            )
            if name == "all":
                all_ref[f"hit_at_{k}"] = mean_v

    ci_df = pd.DataFrame(ci_rows)
    for _, row in ci_df.iterrows():
        metric = str(row["metric"])
        ref = all_ref.get(metric, np.nan)
        abl_rows.append(
            {
                "setting": row["setting"],
                "metric": metric,
                "mean": row["mean"],
                "delta_vs_all": (row["mean"] - ref) if pd.notna(row["mean"]) and pd.notna(ref) else np.nan,
                "lift_vs_random": row["lift_vs_random"],
                "n_days": int(row["n_days"]) if pd.notna(row["n_days"]) else 0,
            }
        )
    abl_df = pd.DataFrame(abl_rows)
    ci_df.to_csv(out_dir / "entity_hitk_bootstrap_ci.csv", index=False, encoding="utf-8-sig")
    abl_df.to_csv(out_dir / "entity_feature_group_ablation.csv", index=False, encoding="utf-8-sig")
    return ci_df, abl_df


def _psi_from_ref_cur(ref: np.ndarray, cur: np.ndarray, n_bins: int = 10) -> float:
    ref = ref[np.isfinite(ref)]
    cur = cur[np.isfinite(cur)]
    if ref.size == 0 or cur.size == 0:
        return np.nan
    quantiles = np.linspace(0.0, 1.0, n_bins + 1)
    edges = np.quantile(ref, quantiles)
    edges[0] = -np.inf
    edges[-1] = np.inf
    ref_hist, _ = np.histogram(ref, bins=edges)
    cur_hist, _ = np.histogram(cur, bins=edges)
    ref_p = np.clip(ref_hist / max(ref_hist.sum(), 1), 1e-6, 1.0)
    cur_p = np.clip(cur_hist / max(cur_hist.sum(), 1), 1e-6, 1.0)
    psi = np.sum((cur_p - ref_p) * np.log(cur_p / ref_p))
    return float(psi)


def run_drift_psi_ks(entity_daily: pd.DataFrame, out_dir: Path, recent_days: int) -> pd.DataFrame:
    f = prepare_entity_feature_frame(entity_daily)
    unique_dates = np.array(sorted(f["date"].unique()))
    if len(unique_dates) < 20:
        out = pd.DataFrame(columns=["feature", "baseline_n", "recent_n", "psi", "ks_stat", "ks_p_value"])
        out.to_csv(out_dir / "entity_drift_psi_ks.csv", index=False, encoding="utf-8-sig")
        return out
    split_idx = max(1, len(unique_dates) - max(int(recent_days), 1))
    baseline_dates = set(unique_dates[:split_idx])
    recent_dates = set(unique_dates[split_idx:])

    features = ["rank_pct", "lag1_rank_pct", "lag7_rank_pct", "roll7_rank_pct", "prior_top1_rate", "weekday_prior_top1_rate"]
    rows: list[dict[str, Any]] = []
    for feat in features:
        if feat not in f.columns:
            continue
        base = f.loc[f["date"].isin(baseline_dates), feat].to_numpy(dtype=float)
        cur = f.loc[f["date"].isin(recent_dates), feat].to_numpy(dtype=float)
        base = base[np.isfinite(base)]
        cur = cur[np.isfinite(cur)]
        if base.size == 0 or cur.size == 0:
            rows.append({"feature": feat, "baseline_n": int(base.size), "recent_n": int(cur.size), "psi": np.nan, "ks_stat": np.nan, "ks_p_value": np.nan})
            continue
        psi = _psi_from_ref_cur(base, cur, n_bins=10)
        ks = stats.ks_2samp(base, cur)
        rows.append(
            {
                "feature": feat,
                "baseline_n": int(base.size),
                "recent_n": int(cur.size),
                "psi": psi,
                "ks_stat": float(ks.statistic),
                "ks_p_value": float(ks.pvalue),
            }
        )
    out = pd.DataFrame(rows)
    out.to_csv(out_dir / "entity_drift_psi_ks.csv", index=False, encoding="utf-8-sig")
    return out


def _fit_and_permutation_for_period(period_df: pd.DataFrame, feature_cols: list[str], period_name: str) -> pd.DataFrame:
    if period_df.empty:
        return pd.DataFrame()
    dates = np.array(sorted(period_df["date"].unique()))
    if len(dates) < 20:
        return pd.DataFrame()
    cut = int(len(dates) * 0.7)
    if cut <= 1 or cut >= len(dates):
        return pd.DataFrame()
    tr_dates = set(dates[:cut])
    te_dates = set(dates[cut:])
    tr = period_df[period_df["date"].isin(tr_dates)].dropna(subset=feature_cols + ["is_rank_1"]).copy()
    te = period_df[period_df["date"].isin(te_dates)].dropna(subset=feature_cols + ["is_rank_1"]).copy()
    if tr.empty or te.empty:
        return pd.DataFrame()
    if tr["is_rank_1"].nunique() < 2 or te["is_rank_1"].nunique() < 2:
        return pd.DataFrame()

    model = LogisticRegression(max_iter=1200, solver="lbfgs", class_weight="balanced")
    x_tr = tr[feature_cols].to_numpy(dtype=float)
    y_tr = tr["is_rank_1"].astype(int).to_numpy()
    x_te = te[feature_cols].to_numpy(dtype=float)
    y_te = te["is_rank_1"].astype(int).to_numpy()
    model.fit(x_tr, y_tr)
    base_score = float(roc_auc_score(y_te, model.predict_proba(x_te)[:, 1]))
    pi = permutation_importance(
        model,
        x_te,
        y_te,
        scoring="roc_auc",
        n_repeats=10,
        random_state=42,
        n_jobs=1,
    )
    rows = []
    for i, feat in enumerate(feature_cols):
        rows.append(
            {
                "period": period_name,
                "feature": feat,
                "base_auc": base_score,
                "importance_mean": float(pi.importances_mean[i]),
                "importance_std": float(pi.importances_std[i]),
            }
        )
    return pd.DataFrame(rows)


def run_permutation_importance_period_compare(entity_daily: pd.DataFrame, out_dir: Path, recent_days: int) -> pd.DataFrame:
    f = prepare_entity_feature_frame(entity_daily)
    feature_cols = [
        "lag1_rank_pct",
        "lag7_rank_pct",
        "roll7_rank_pct",
        "prior_top1_rate",
        "weekday_prior_top1_rate",
        "day_of_week_num",
        "day_of_month",
        "is_weekend",
        "entity_encoded",
        "machine_type_encoded",
    ]
    dates = np.array(sorted(f["date"].unique()))
    split_idx = max(1, len(dates) - max(int(recent_days), 1))
    old_dates = set(dates[:split_idx])
    recent_dates = set(dates[split_idx:])
    old_df = f[f["date"].isin(old_dates)].copy()
    recent_df = f[f["date"].isin(recent_dates)].copy()

    old_imp = _fit_and_permutation_for_period(old_df, feature_cols, "older_period")
    recent_imp = _fit_and_permutation_for_period(recent_df, feature_cols, "recent_period")
    if old_imp.empty and recent_imp.empty:
        out = pd.DataFrame(columns=["period", "feature", "base_auc", "importance_mean", "importance_std", "delta_recent_minus_old"])
        out.to_csv(out_dir / "entity_permutation_importance_period_compare.csv", index=False, encoding="utf-8-sig")
        return out

    out = pd.concat([old_imp, recent_imp], ignore_index=True)
    pivot = out.pivot_table(index="feature", columns="period", values="importance_mean", aggfunc="mean")
    delta_map = (pivot.get("recent_period", pd.Series(dtype=float)) - pivot.get("older_period", pd.Series(dtype=float))).to_dict()
    out["delta_recent_minus_old"] = out["feature"].map(delta_map)
    out = out.sort_values(["feature", "period"]).reset_index(drop=True)
    out.to_csv(out_dir / "entity_permutation_importance_period_compare.csv", index=False, encoding="utf-8-sig")
    return out


def run_multiple_testing_bh(
    out_dir: Path,
    chi_df: pd.DataFrame,
    kruskal_df: pd.DataFrame,
    lag_df: pd.DataFrame,
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []

    if not chi_df.empty:
        one = chi_df[["chi2", "p_value", "dof", "cramers_v"]].drop_duplicates().head(1)
        if not one.empty:
            rows.append(
                {
                    "test_family": "chi_square_weekday_entity",
                    "test_name": "chi_square_overall",
                    "group_a": "ALL",
                    "group_b": "ALL",
                    "raw_p_value": float(one.iloc[0]["p_value"]) if pd.notna(one.iloc[0]["p_value"]) else np.nan,
                    "effect_size": float(one.iloc[0]["cramers_v"]) if pd.notna(one.iloc[0]["cramers_v"]) else np.nan,
                    "effect_size_name": "cramers_v",
                }
            )

    if not kruskal_df.empty:
        for _, r in kruskal_df.iterrows():
            rows.append(
                {
                    "test_family": "kruskal_entity",
                    "test_name": str(r["test_type"]),
                    "group_a": str(r["group_a"]),
                    "group_b": str(r["group_b"]),
                    "raw_p_value": float(r["p_value"]) if pd.notna(r["p_value"]) else np.nan,
                    "effect_size": float(r["cliffs_delta"]) if pd.notna(r["cliffs_delta"]) else np.nan,
                    "effect_size_name": "cliffs_delta",
                }
            )

    if not lag_df.empty:
        for _, r in lag_df.iterrows():
            rows.append(
                {
                    "test_family": "lag_spearman_entity",
                    "test_name": f"lag_{int(r['lag'])}",
                    "group_a": "ALL",
                    "group_b": "ALL",
                    "raw_p_value": float(r["spearman_p_value"]) if pd.notna(r["spearman_p_value"]) else np.nan,
                    "effect_size": float(r["spearman_r"]) if pd.notna(r["spearman_r"]) else np.nan,
                    "effect_size_name": "spearman_r",
                }
            )

    out = pd.DataFrame(rows)
    if out.empty:
        out.to_csv(out_dir / "multiple_testing_bh_entity.csv", index=False, encoding="utf-8-sig")
        return out
    out["p_adj_bh"] = _bh_adjust(out["raw_p_value"].tolist())
    out["is_significant_5pct_raw"] = (out["raw_p_value"] < 0.05).astype(int)
    out["is_significant_5pct_bh"] = (out["p_adj_bh"] < 0.05).astype(int)
    out = out.sort_values(["test_family", "raw_p_value"], na_position="last").reset_index(drop=True)
    out.to_csv(out_dir / "multiple_testing_bh_entity.csv", index=False, encoding="utf-8-sig")
    return out


def main() -> int:
    args = parse_args()
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    df = load_entity_daily_frame(args.db_glob)
    min_days = max(int(args.min_entity_days), 1)

    run_base_diff(df, out_dir)
    chi_df = run_chi_square(df, out_dir)
    kruskal_df = run_kruskal(df, out_dir, min_entity_days=min_days)
    run_acf_per_entity(df, out_dir, nlags=max(int(args.acf_nlags), 1))
    run_adf(df, out_dir)
    run_weekday_entity_cross(df, out_dir)
    lag_df = run_lag_screening(df, out_dir)
    run_mi_screening(df, out_dir)
    run_anomaly_response(df, out_dir, window=max(int(args.anomaly_window), 7), min_entity_days=min_days)
    run_streak(df, out_dir)

    run_multiple_testing_bh(out_dir, chi_df=chi_df, kruskal_df=kruskal_df, lag_df=lag_df)
    run_hitk_bootstrap_and_ablation(
        df,
        out_dir,
        eval_days=max(int(args.eval_days), 1),
        min_train_days=max(int(args.min_train_days), 30),
        n_boot=max(int(args.bootstrap_repeats), 50),
        block_size=max(int(args.bootstrap_block_size), 1),
    )
    run_drift_psi_ks(df, out_dir, recent_days=max(int(args.recent_days), 7))
    run_permutation_importance_period_compare(df, out_dir, recent_days=max(int(args.recent_days), 7))

    print("Saved EDA outputs to:")
    print(out_dir.as_posix())
    for name in [
        "machine_name_base_diff.csv",
        "chi_square_weekday_entity.csv",
        "kruskal_entity.csv",
        "acf_per_entity.csv",
        "adf_entity.csv",
        "weekday_entity_cross.csv",
        "lag_screening_entity.csv",
        "mi_entity_features.csv",
        "entity_anomaly_response.csv",
        "entity_streak.csv",
        "multiple_testing_bh_entity.csv",
        "entity_hitk_bootstrap_ci.csv",
        "entity_feature_group_ablation.csv",
        "entity_drift_psi_ks.csv",
        "entity_permutation_importance_period_compare.csv",
    ]:
        print((out_dir / name).as_posix())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
