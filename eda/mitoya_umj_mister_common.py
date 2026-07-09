from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd
from scipy.stats import chi2_contingency, pearsonr, spearmanr


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RESULT_DIR = PROJECT_ROOT / "eda" / "results" / "mitoya_umj_mister_dd_investigation"
DB_NEEDLE = "\u307f\u3068\u3084"
TARGET_MODELS = [
    "\u30a6\u30eb\u30c8\u30e9\u30df\u30e9\u30af\u30eb\u30b8\u30e3\u30b0\u30e9\u30fc",
    "\u30df\u30b9\u30bf\u30fc\u30b8\u30e3\u30b0\u30e9\u30fc",
    "\u30de\u30a4\u30b8\u30e3\u30b0\u30e9\u30fcV",
    "\u30a2\u30a4\u30e0\u30b8\u30e3\u30b0\u30e9\u30fcEX-TP",
    "\u30cd\u30aa\u30a2\u30a4\u30e0\u30b8\u30e3\u30b0\u30e9\u30fcEX",
    "\u30d5\u30a1\u30f3\u30ad\u30fc\u30b8\u30e3\u30b0\u30e9\u30fc2",
    "\u30b4\u30fc\u30b4\u30fc\u30b8\u30e3\u30b0\u30e9\u30fc3",
    "\u30b8\u30e3\u30b0\u30e9\u30fc\u30ac\u30fc\u30eb\u30ba",
]
DD19_29_MODELS = [
    "\u30de\u30a4\u30b8\u30e3\u30b0\u30e9\u30fcV",
    "\u30a2\u30a4\u30e0\u30b8\u30e3\u30b0\u30e9\u30fcEX-TP",
    "\u30cd\u30aa\u30a2\u30a4\u30e0\u30b8\u30e3\u30b0\u30e9\u30fcEX",
    "\u30d5\u30a1\u30f3\u30ad\u30fc\u30b8\u30e3\u30b0\u30e9\u30fc2",
    "\u30b4\u30fc\u30b4\u30fc\u30b8\u30e3\u30b0\u30e9\u30fc3",
    "\u30df\u30b9\u30bf\u30fc\u30b8\u30e3\u30b0\u30e9\u30fc",
    "\u30a6\u30eb\u30c8\u30e9\u30df\u30e9\u30af\u30eb\u30b8\u30e3\u30b0\u30e9\u30fc",
    "\u30b8\u30e3\u30b0\u30e9\u30fc\u30ac\u30fc\u30eb\u30ba",
]
WEEKDAY_ORDER = list(range(7))
WEEKDAY_LABELS = {
    0: "月",
    1: "火",
    2: "水",
    3: "木",
    4: "金",
    5: "土",
    6: "日",
}
TIER_BINS = [
    (100, 500, "100-500"),
    (500, 1000, "500-1k"),
    (1000, 2000, "1k-2k"),
    (2000, None, "2k+"),
]


def ensure_result_dir() -> Path:
    RESULT_DIR.mkdir(parents=True, exist_ok=True)
    return RESULT_DIR


def resolve_db_path() -> Path:
    db_dir = PROJECT_ROOT / "db"
    matches = [p for p in db_dir.glob("*.db") if DB_NEEDLE in p.name]
    if not matches:
        raise FileNotFoundError(f"could not find DB containing {DB_NEEDLE!r} under {db_dir}")
    if len(matches) > 1:
        matches = sorted(matches, key=lambda p: (p.stat().st_size, p.name), reverse=True)
    return matches[0].resolve()


def load_frame(*, machine_names: Iterable[str] | None = None) -> pd.DataFrame:
    db_path = resolve_db_path()
    conn = sqlite3.connect(str(db_path))
    try:
        frame = pd.read_sql_query(
            """
            SELECT date, machine_number, machine_name, games_normalized, rb_count, bb_count
            FROM machine_detailed_results
            """,
            conn,
        )
    finally:
        conn.close()

    frame["date"] = pd.to_datetime(frame["date"], format="%Y%m%d", errors="coerce")
    frame["machine_number"] = pd.to_numeric(frame["machine_number"], errors="coerce")
    frame["games_normalized"] = pd.to_numeric(frame["games_normalized"], errors="coerce")
    frame["rb_count"] = pd.to_numeric(frame["rb_count"], errors="coerce")
    frame["bb_count"] = pd.to_numeric(frame["bb_count"], errors="coerce")
    frame = frame.dropna(subset=["date", "machine_number", "machine_name", "games_normalized", "rb_count"]).copy()
    frame["machine_number"] = frame["machine_number"].astype(int)
    frame["games_normalized"] = frame["games_normalized"].astype(float)
    frame["rb_count"] = frame["rb_count"].astype(float)
    frame["bb_count"] = frame["bb_count"].astype(float)
    frame = frame.loc[frame["games_normalized"] > 0].copy()

    if machine_names is not None:
        names = list(machine_names)
        frame = frame.loc[frame["machine_name"].isin(names)].copy()

    frame["dd"] = frame["date"].dt.day.astype(int)
    frame["year"] = frame["date"].dt.year.astype(int)
    frame["weekday_num"] = frame["date"].dt.dayofweek.astype(int)
    frame["weekday_name"] = frame["weekday_num"].map(WEEKDAY_LABELS)
    frame["is_weekend"] = frame["weekday_num"].isin([5, 6])
    frame["games_tier"] = pd.cut(
        frame["games_normalized"],
        bins=[100, 500, 1000, 2000, np.inf],
        labels=["100-500", "500-1k", "1k-2k", "2k+"],
        right=False,
    )
    frame["payout_rate"] = np.where(
        frame["games_normalized"].gt(0),
        ((frame["games_normalized"] * 3.0 + frame["rb_count"]) / (frame["games_normalized"] * 3.0)) * 100.0,
        np.nan,
    )
    return frame.reset_index(drop=True)


def safe_rate(numer: pd.Series | float, denom: pd.Series | float) -> pd.Series | float:
    if isinstance(denom, pd.Series):
        denom = denom.astype(float)
        numer = (
            pd.Series(numer, index=denom.index, dtype=float)
            if not isinstance(numer, pd.Series)
            else numer.astype(float)
        )
        return numer.where(denom.gt(0), np.nan) / denom.where(denom.gt(0), np.nan)
    denom = float(denom)
    numer = float(numer)
    return numer / denom if denom > 0 else float("nan")


def _pooled_rate(frame: pd.DataFrame) -> float:
    games = float(frame["games_normalized"].sum())
    rb = float(frame["rb_count"].sum())
    return float(rb / games) if games > 0 else float("nan")


def _rate_diff_pp(left: float, right: float) -> float:
    if pd.isna(left) or pd.isna(right):
        return float("nan")
    return float((left - right) * 100.0)


def _chi2_rate_test(left: pd.DataFrame, right: pd.DataFrame) -> dict[str, float]:
    left_rb = float(left["rb_count"].sum())
    left_games = float(left["games_normalized"].sum())
    right_rb = float(right["rb_count"].sum())
    right_games = float(right["games_normalized"].sum())
    left_non = left_games - left_rb
    right_non = right_games - right_rb
    if min(left_rb, left_non, right_rb, right_non) < 0:
        return {"chi2": np.nan, "p_value": np.nan, "cramers_v": np.nan}
    table = np.array([[left_rb, left_non], [right_rb, right_non]], dtype=float)
    if not np.isfinite(table).all() or table.sum() <= 0:
        return {"chi2": np.nan, "p_value": np.nan, "cramers_v": np.nan}
    chi2, p_value, _, expected = chi2_contingency(table, correction=False)
    n_obs = float(table.sum())
    cramers_v = float(np.sqrt(chi2 / n_obs)) if n_obs > 0 else float("nan")
    return {"chi2": float(chi2), "p_value": float(p_value), "cramers_v": cramers_v}


def _weekday_summary(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame(
            columns=[
                "weekday_num",
                "weekday_name",
                "rows",
                "dates",
                "games_sum",
                "rb_sum",
                "pooled_rb_rate",
            ]
        )
    grouped = (
        frame.groupby("weekday_num", sort=True)
        .agg(
            weekday_name=("weekday_name", "first"),
            rows=("date", "size"),
            dates=("date", "nunique"),
            games_sum=("games_normalized", "sum"),
            rb_sum=("rb_count", "sum"),
        )
        .reset_index()
    )
    grouped["pooled_rb_rate"] = grouped.apply(
        lambda row: float(row["rb_sum"] / row["games_sum"]) if row["games_sum"] > 0 else np.nan,
        axis=1,
    )
    grouped["weekday_num"] = grouped["weekday_num"].astype(int)
    grouped = grouped.sort_values("weekday_num", kind="mergesort").reset_index(drop=True)
    return grouped


def _weekday_weekend_summary(frame: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, float]]:
    if frame.empty:
        empty = pd.DataFrame(columns=["bucket", "rows", "dates", "games_sum", "rb_sum", "pooled_rb_rate"])
        return empty, {"chi2": np.nan, "p_value": np.nan, "cramers_v": np.nan}
    work = frame.copy()
    work["bucket"] = np.where(work["is_weekend"], "weekend", "weekday")
    grouped = (
        work.groupby("bucket", sort=True)
        .agg(
            rows=("date", "size"),
            dates=("date", "nunique"),
            games_sum=("games_normalized", "sum"),
            rb_sum=("rb_count", "sum"),
        )
        .reset_index()
    )
    grouped["pooled_rb_rate"] = grouped.apply(
        lambda row: float(row["rb_sum"] / row["games_sum"]) if row["games_sum"] > 0 else np.nan,
        axis=1,
    )
    grouped = grouped.sort_values("bucket", kind="mergesort").reset_index(drop=True)
    weekday = work.loc[work["bucket"] == "weekday"]
    weekend = work.loc[work["bucket"] == "weekend"]
    stats = _chi2_rate_test(weekday, weekend)
    return grouped, stats


def _games_tier_summary(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame(columns=["games_tier", "rows", "dates", "games_sum", "rb_sum", "pooled_rb_rate"])
    grouped = (
        frame.groupby("games_tier", observed=False)
        .agg(
            rows=("date", "size"),
            dates=("date", "nunique"),
            games_sum=("games_normalized", "sum"),
            rb_sum=("rb_count", "sum"),
        )
        .reset_index()
    )
    grouped["pooled_rb_rate"] = grouped.apply(
        lambda row: float(row["rb_sum"] / row["games_sum"]) if row["games_sum"] > 0 else np.nan,
        axis=1,
    )
    grouped["games_tier"] = pd.Categorical(
        grouped["games_tier"], categories=[label for _, _, label in TIER_BINS], ordered=True
    )
    grouped = grouped.sort_values("games_tier", kind="mergesort").reset_index(drop=True)
    return grouped


def _date_summary(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame(
            columns=[
                "date",
                "weekday_num",
                "weekday_name",
                "rows",
                "games_mean",
                "games_sum",
                "rb_sum",
                "pooled_rb_rate",
            ]
        )
    grouped = (
        frame.groupby("date", sort=True)
        .agg(
            weekday_num=("weekday_num", "first"),
            weekday_name=("weekday_name", "first"),
            rows=("date", "size"),
            games_mean=("games_normalized", "mean"),
            games_sum=("games_normalized", "sum"),
            rb_sum=("rb_count", "sum"),
        )
        .reset_index()
    )
    grouped["pooled_rb_rate"] = grouped.apply(
        lambda row: float(row["rb_sum"] / row["games_sum"]) if row["games_sum"] > 0 else np.nan,
        axis=1,
    )
    return grouped.sort_values("date", kind="mergesort").reset_index(drop=True)


def _year_summary(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame(columns=["year", "rows", "dates", "games_sum", "rb_sum", "pooled_rb_rate"])
    grouped = (
        frame.groupby("year", sort=True)
        .agg(
            rows=("date", "size"),
            dates=("date", "nunique"),
            games_sum=("games_normalized", "sum"),
            rb_sum=("rb_count", "sum"),
        )
        .reset_index()
    )
    grouped["pooled_rb_rate"] = grouped.apply(
        lambda row: float(row["rb_sum"] / row["games_sum"]) if row["games_sum"] > 0 else np.nan,
        axis=1,
    )
    return grouped.sort_values("year", kind="mergesort").reset_index(drop=True)


def _pearson_date_correlation(date_df: pd.DataFrame) -> dict[str, float]:
    valid = date_df.loc[
        date_df["games_mean"].notna() & date_df["pooled_rb_rate"].notna(), ["games_mean", "pooled_rb_rate"]
    ]
    if len(valid) < 3:
        return {"r": np.nan, "p_value": np.nan, "n": int(len(valid))}
    if valid["games_mean"].nunique() < 2 or valid["pooled_rb_rate"].nunique() < 2:
        return {"r": np.nan, "p_value": np.nan, "n": int(len(valid))}
    r, p_value = pearsonr(valid["games_mean"].to_numpy(), valid["pooled_rb_rate"].to_numpy())
    return {"r": float(r), "p_value": float(p_value), "n": int(len(valid))}


def _period_split_summary(frame: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, float]]:
    if frame.empty:
        empty = pd.DataFrame(columns=["period", "rows", "dates", "games_sum", "rb_sum", "pooled_rb_rate"])
        return empty, {"chi2": np.nan, "p_value": np.nan, "cramers_v": np.nan}

    years = sorted(frame["year"].dropna().astype(int).unique().tolist())
    if len(years) >= 2:
        first_year = years[0]
        second_year = years[-1]
        first = frame.loc[frame["year"] == first_year].copy()
        second = frame.loc[frame["year"] == second_year].copy()
        period_labels = [str(first_year), str(second_year)]
    else:
        mid_date = frame["date"].sort_values(kind="mergesort").iloc[len(frame) // 2]
        first = frame.loc[frame["date"] < mid_date].copy()
        second = frame.loc[frame["date"] >= mid_date].copy()
        period_labels = ["first_half", "second_half"]

    summary = pd.DataFrame(
        [
            {
                "period": period_labels[0],
                "rows": int(len(first)),
                "dates": int(first["date"].nunique()),
                "games_sum": float(first["games_normalized"].sum()),
                "rb_sum": float(first["rb_count"].sum()),
                "pooled_rb_rate": float(_pooled_rate(first)),
            },
            {
                "period": period_labels[1],
                "rows": int(len(second)),
                "dates": int(second["date"].nunique()),
                "games_sum": float(second["games_normalized"].sum()),
                "rb_sum": float(second["rb_count"].sum()),
                "pooled_rb_rate": float(_pooled_rate(second)),
            },
        ]
    )
    stats = _chi2_rate_test(first, second)
    return summary, stats


def _dd_ranking(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame(columns=["dd", "rows", "dates", "games_sum", "rb_sum", "pooled_rb_rate"])
    grouped = (
        frame.groupby("dd", sort=True)
        .agg(
            rows=("date", "size"),
            dates=("date", "nunique"),
            games_sum=("games_normalized", "sum"),
            rb_sum=("rb_count", "sum"),
        )
        .reset_index()
    )
    grouped["pooled_rb_rate"] = grouped.apply(
        lambda row: float(row["rb_sum"] / row["games_sum"]) if row["games_sum"] > 0 else np.nan,
        axis=1,
    )
    grouped = grouped.sort_values(
        ["pooled_rb_rate", "rb_sum", "dates", "dd"],
        ascending=[False, False, False, True],
        kind="mergesort",
    ).reset_index(drop=True)
    grouped["rank"] = np.arange(1, len(grouped) + 1)
    return grouped


def _machine_summary(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame(columns=["machine_number", "rows", "dates", "games_sum", "rb_sum", "pooled_rb_rate"])
    grouped = (
        frame.groupby("machine_number", sort=True)
        .agg(
            rows=("date", "size"),
            dates=("date", "nunique"),
            games_sum=("games_normalized", "sum"),
            rb_sum=("rb_count", "sum"),
        )
        .reset_index()
    )
    grouped["pooled_rb_rate"] = grouped.apply(
        lambda row: float(row["rb_sum"] / row["games_sum"]) if row["games_sum"] > 0 else np.nan,
        axis=1,
    )
    grouped = grouped.sort_values(
        ["pooled_rb_rate", "rb_sum", "dates", "machine_number"],
        ascending=[False, False, False, True],
        kind="mergesort",
    ).reset_index(drop=True)
    grouped["rank"] = np.arange(1, len(grouped) + 1)
    return grouped


def _half_rank_spearman(frame: pd.DataFrame) -> dict[str, float]:
    if frame.empty:
        return {"rho": np.nan, "p_value": np.nan, "n_common": 0}
    ordered_dates = sorted(frame["date"].dropna().unique().tolist())
    if len(ordered_dates) < 2:
        return {"rho": np.nan, "p_value": np.nan, "n_common": 0}
    split_idx = len(ordered_dates) // 2
    first_dates = set(ordered_dates[:split_idx])
    second_dates = set(ordered_dates[split_idx:])
    first = frame.loc[frame["date"].isin(first_dates)].copy()
    second = frame.loc[frame["date"].isin(second_dates)].copy()
    if first.empty or second.empty:
        return {"rho": np.nan, "p_value": np.nan, "n_common": 0}

    first_rank = first.groupby("machine_number").agg(games_sum=("games_normalized", "sum"), rb_sum=("rb_count", "sum"))
    second_rank = second.groupby("machine_number").agg(
        games_sum=("games_normalized", "sum"), rb_sum=("rb_count", "sum")
    )
    first_rank["rb_rate"] = first_rank["rb_sum"] / first_rank["games_sum"].replace(0, np.nan)
    second_rank["rb_rate"] = second_rank["rb_sum"] / second_rank["games_sum"].replace(0, np.nan)
    merged = first_rank[["rb_rate"]].join(second_rank[["rb_rate"]], how="inner", lsuffix="_first", rsuffix="_second")
    merged = merged.dropna()
    if len(merged) < 3:
        return {"rho": np.nan, "p_value": np.nan, "n_common": int(len(merged))}
    first_rank_values = merged["rb_rate_first"].rank(ascending=False, method="average")
    second_rank_values = merged["rb_rate_second"].rank(ascending=False, method="average")
    if first_rank_values.nunique() < 2 or second_rank_values.nunique() < 2:
        return {"rho": np.nan, "p_value": np.nan, "n_common": int(len(merged))}
    rho, p_value = spearmanr(first_rank_values.to_numpy(), second_rank_values.to_numpy())
    return {"rho": float(rho), "p_value": float(p_value), "n_common": int(len(merged))}


def analyze_dd_candidate(frame: pd.DataFrame, dd: int) -> dict[str, object]:
    target = frame.loc[frame["dd"] == dd].copy()
    rest = frame.loc[frame["dd"] != dd].copy()

    dd_rate = _pooled_rate(target)
    rest_rate = _pooled_rate(rest)
    dd_vs_rest = _chi2_rate_test(target, rest)
    weekday_df = _weekday_summary(target)
    weekday_weekend_df, weekday_weekend_stats = _weekday_weekend_summary(target)
    tier_df = _games_tier_summary(target)
    date_df = _date_summary(target)
    date_corr = _pearson_date_correlation(date_df)
    year_df, year_stats = _period_split_summary(target)

    top_date_share = np.nan
    top_date = ""
    top_date_rb_sum = np.nan
    if not date_df.empty and float(date_df["rb_sum"].sum()) > 0:
        top_row = date_df.sort_values(
            ["rb_sum", "pooled_rb_rate", "games_sum", "date"], ascending=[False, False, False, True], kind="mergesort"
        ).iloc[0]
        top_date = top_row["date"].strftime("%Y-%m-%d")
        top_date_rb_sum = float(top_row["rb_sum"])
        top_date_share = float(top_row["rb_sum"] / date_df["rb_sum"].sum())

    tier_rows = tier_df.rename(columns={"games_tier": "label"}).copy()
    date_rows = date_df.copy()
    year_rows = year_df.copy()

    weekday_support = weekday_weekend_stats["p_value"] < 0.05 if pd.notna(weekday_weekend_stats["p_value"]) else False
    concentration_support = pd.notna(top_date_share) and top_date_share > 0.30
    games_support = (
        pd.notna(date_corr["r"])
        and abs(date_corr["r"]) >= 0.4
        and pd.notna(date_corr["p_value"])
        and date_corr["p_value"] < 0.05
    )
    period_support = pd.notna(year_stats["p_value"]) and year_stats["p_value"] < 0.05
    dd_support = pd.notna(dd_vs_rest["p_value"]) and dd_vs_rest["p_value"] < 0.05 and dd_rate > rest_rate
    overall_support = bool(
        dd_support and not weekday_support and not concentration_support and not games_support and not period_support
    )

    if pd.isna(date_corr["r"]) or pd.isna(date_corr["p_value"]):
        games_verdict = "保留" if len(date_df) < 3 else "否定"
    else:
        games_verdict = "支持" if games_support else "否定"

    if pd.isna(year_stats["p_value"]):
        period_verdict = "保留"
    else:
        period_verdict = "支持" if period_support else "否定"

    if pd.isna(weekday_weekend_stats["p_value"]):
        weekday_verdict = "保留"
    else:
        weekday_verdict = "支持" if weekday_support else "否定"

    if pd.isna(top_date_share):
        concentration_verdict = "保留"
    else:
        concentration_verdict = "支持" if concentration_support else "否定"

    return {
        "dd": int(dd),
        "target_rows": int(len(target)),
        "target_dates": int(target["date"].nunique()),
        "target_games_sum": float(target["games_normalized"].sum()),
        "target_rb_sum": float(target["rb_count"].sum()),
        "target_pooled_rb_rate": float(dd_rate),
        "rest_rows": int(len(rest)),
        "rest_dates": int(rest["date"].nunique()),
        "rest_games_sum": float(rest["games_normalized"].sum()),
        "rest_rb_sum": float(rest["rb_count"].sum()),
        "rest_pooled_rb_rate": float(rest_rate),
        "rate_diff_pp": _rate_diff_pp(dd_rate, rest_rate),
        "dd_vs_rest_chi2": float(dd_vs_rest["chi2"]),
        "dd_vs_rest_p": float(dd_vs_rest["p_value"]),
        "dd_vs_rest_cramers_v": float(dd_vs_rest["cramers_v"]),
        "weekday_df": weekday_df,
        "weekday_weekend_df": weekday_weekend_df,
        "weekday_weekend_chi2": float(weekday_weekend_stats["chi2"]),
        "weekday_weekend_p": float(weekday_weekend_stats["p_value"]),
        "weekday_weekend_cramers_v": float(weekday_weekend_stats["cramers_v"]),
        "tier_df": tier_df,
        "date_df": date_df,
        "date_games_pearson_r": float(date_corr["r"]),
        "date_games_pearson_p": float(date_corr["p_value"]),
        "date_games_pearson_n": int(date_corr["n"]),
        "year_df": year_df,
        "year_chi2": float(year_stats["chi2"]),
        "year_p": float(year_stats["p_value"]),
        "year_cramers_v": float(year_stats["cramers_v"]),
        "top_date": top_date,
        "top_date_rb_sum": float(top_date_rb_sum) if pd.notna(top_date_rb_sum) else np.nan,
        "top_date_share": float(top_date_share) if pd.notna(top_date_share) else np.nan,
        "weekday_verdict": weekday_verdict,
        "concentration_verdict": concentration_verdict,
        "games_verdict": games_verdict,
        "period_verdict": period_verdict,
        "overall_verdict": "支持" if overall_support else "否定",
    }


def analyze_machine_numbers(frame: pd.DataFrame) -> dict[str, object]:
    summary = _machine_summary(frame)
    if summary.empty:
        return {
            "machine_summary": summary,
            "chi2_stat": np.nan,
            "chi2_p": np.nan,
            "chi2_dof": np.nan,
            "chi2_expected_sparse_share": np.nan,
            "spearman_rho": np.nan,
            "spearman_p": np.nan,
            "spearman_n_common": 0,
            "overall_verdict": "保留",
        }

    contingency = summary[["rb_sum", "games_sum"]].copy()
    contingency["non_rb"] = contingency["games_sum"] - contingency["rb_sum"]
    contingency = contingency.loc[contingency["non_rb"].ge(0)].copy()
    if contingency.empty or contingency.shape[0] < 2:
        chi2_stat = chi2_p = chi2_dof = sparse_share = np.nan
    else:
        table = contingency[["rb_sum", "non_rb"]].to_numpy(dtype=float)
        if np.isfinite(table).all() and table.sum() > 0:
            chi2_stat, chi2_p, chi2_dof, expected = chi2_contingency(table, correction=False)
            sparse_share = float((expected < 5).mean())
        else:
            chi2_stat = chi2_p = chi2_dof = sparse_share = np.nan

    half_stats = _half_rank_spearman(frame)
    overall_verdict = (
        "支持"
        if pd.notna(chi2_p) and chi2_p < 0.05 and pd.notna(half_stats["rho"]) and half_stats["rho"] >= 0.4
        else "否定"
    )
    return {
        "machine_summary": summary,
        "chi2_stat": float(chi2_stat) if pd.notna(chi2_stat) else np.nan,
        "chi2_p": float(chi2_p) if pd.notna(chi2_p) else np.nan,
        "chi2_dof": float(chi2_dof) if pd.notna(chi2_dof) else np.nan,
        "chi2_expected_sparse_share": float(sparse_share) if pd.notna(sparse_share) else np.nan,
        "spearman_rho": float(half_stats["rho"]) if pd.notna(half_stats["rho"]) else np.nan,
        "spearman_p": float(half_stats["p_value"]) if pd.notna(half_stats["p_value"]) else np.nan,
        "spearman_n_common": int(half_stats["n_common"]),
        "overall_verdict": overall_verdict,
    }


def summarize_model_rankings(frame: pd.DataFrame, *, top_n: int = 3) -> tuple[pd.DataFrame, pd.DataFrame]:
    ranking = _dd_ranking(frame)
    top = ranking.head(top_n).copy()
    return ranking, top


def candidate_detail_frames(candidate: dict[str, object]) -> dict[str, pd.DataFrame]:
    return {
        "weekday": candidate["weekday_df"].copy(),
        "weekday_weekend": candidate["weekday_weekend_df"].copy(),
        "tier": candidate["tier_df"].copy(),
        "date": candidate["date_df"].copy(),
        "year": candidate["year_df"].copy(),
    }


def compact_float(value: float, digits: int = 4) -> str:
    if value is None or pd.isna(value):
        return "NaN"
    return f"{float(value):.{digits}f}"


def compact_pct(value: float, digits: int = 1) -> str:
    if value is None or pd.isna(value):
        return "NaN"
    return f"{float(value) * 100.0:.{digits}f}%"


def verdict_mark(verdict: str) -> str:
    return verdict if verdict in {"支持", "否定", "保留"} else str(verdict)
