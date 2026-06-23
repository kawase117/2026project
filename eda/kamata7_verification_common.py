from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

from eda.core import _bootstrap_ci, _epsilon_squared, load_hall_df
from eda.kamata7_lastdigit_lr_eda import build_floor_side_map, classify_seg, load_coords

PROJECT_ROOT = Path(__file__).resolve().parents[1]
REPORT_DIR = PROJECT_ROOT / "eda" / "reports"

HALL = "蒲田7"
ANNIVERSARY_MMDD = "0707"

DOW_ORDER = ["月", "火", "水", "木", "金", "土", "日"]
SEGMENT_ORDER = ["A", "N"]
FLOOR_SIDE_ORDER = ["2F_L", "2F_R", "3F_L", "3F_R"]
KAKUBAN_ORDER = ["角1", "角2", "中間", "角N-1", "角N"]
DIGIT_ORDER = [str(i) for i in range(10)]


def ensure_report_dir() -> None:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def table_to_markdown(df: pd.DataFrame, float_digits: int = 1) -> str:
    if df.empty:
        return "_no rows_"
    cols = list(df.columns)
    lines = ["| " + " | ".join(cols) + " |", "| " + " | ".join(["---"] * len(cols)) + " |"]
    for _, row in df.iterrows():
        cells: list[str] = []
        for col in cols:
            val = row[col]
            if pd.isna(val):
                cells.append("NaN")
            elif isinstance(val, (float, np.floating)):
                if float(val).is_integer():
                    cells.append(str(int(round(float(val)))))
                else:
                    cells.append(f"{float(val):.{float_digits}f}")
            elif isinstance(val, (int, np.integer)):
                cells.append(str(int(val)))
            else:
                cells.append(str(val))
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def pct(value: float, digits: int = 1) -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return "NaN"
    return f"{value:.{digits}f}%"


def signed(value: float, digits: int = 0) -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return "NaN"
    return f"{value:+.{digits}f}"


def compute_payout_rate(df: pd.DataFrame) -> pd.Series:
    games = pd.to_numeric(df["games"], errors="coerce")
    diff = pd.to_numeric(df["diff"], errors="coerce")
    return np.where(games > 0, (1 + diff / (games * 3)) * 100, np.nan)


def prepare_base_frame(*, include_floor_side: bool = False, include_coords: bool = False) -> pd.DataFrame:
    df = load_hall_df(HALL).copy()
    df["date"] = df["date"].astype(str)
    df["machine_number"] = pd.to_numeric(df["machine_number"], errors="coerce")
    df["games"] = pd.to_numeric(df["games"], errors="coerce")
    df["diff"] = pd.to_numeric(df["diff"], errors="coerce")
    df["machine_digit"] = df["machine_digit"].astype(str)
    df["payout_rate"] = compute_payout_rate(df)
    df["hit104"] = (df["payout_rate"] >= 104.0).astype(int)

    mmdd = df["date"].str[4:8]
    df = df[mmdd != ANNIVERSARY_MMDD].copy()
    df = df[df["machine_number"] != 2026].copy()
    df = df.dropna(subset=["machine_number", "games", "diff"]).copy()
    df["machine_number"] = df["machine_number"].astype(int)
    df["plus"] = (df["diff"] > 0).astype(int)

    if include_floor_side:
        floor_side = build_floor_side_map()
        df = df.merge(floor_side, on="machine_number", how="inner")
        df["floor"] = df["floor"].astype(str)
        df["side"] = df["side"].astype(str)
        df["floor_side"] = df["floor"].astype(str) + "_" + df["side"].astype(str)

    if include_coords:
        coords = load_coords().copy()
        coords = coords.drop_duplicates(subset=["machine_number"], keep="first")
        coords = coords[[
            "machine_number",
            "section",
            "section_min",
            "section_max",
            "display_x",
            "display_y",
            "rank_from_min",
            "rank_from_max",
        ]]
        df = df.merge(coords, on="machine_number", how="inner")

    if "machine_name" in df.columns:
        df["machine_name"] = df["machine_name"].astype(str)
        df["seg"] = df["machine_name"].map(classify_seg)

    return df.reset_index(drop=True)


def attach_coords(df: pd.DataFrame) -> pd.DataFrame:
    coords = load_coords().copy()
    coords = coords.drop_duplicates(subset=["machine_number"], keep="first")
    coords = coords[[
        "machine_number",
        "section",
        "section_min",
        "section_max",
        "display_x",
        "display_y",
        "rank_from_min",
        "rank_from_max",
    ]]
    return df.merge(coords, on="machine_number", how="inner")


def attach_floor_side(df: pd.DataFrame) -> pd.DataFrame:
    floor_side = build_floor_side_map()
    merged = df.merge(floor_side, on="machine_number", how="inner")
    merged["floor"] = merged["floor"].astype(str)
    merged["side"] = merged["side"].astype(str)
    merged["floor_side"] = merged["floor"] + "_" + merged["side"]
    return merged


def attach_seg(df: pd.DataFrame) -> pd.DataFrame:
    merged = df.copy()
    merged["machine_name"] = merged["machine_name"].astype(str)
    merged["seg"] = merged["machine_name"].map(classify_seg)
    return merged


def group_stats(df: pd.DataFrame, group_cols: list[str], value_col: str = "diff", min_n: int = 1) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=[*group_cols, "n", "avg_diff", "plus_rate", "hit104_rate"])
    agg = (
        df.groupby(group_cols, dropna=False)
        .agg(
            n=(value_col, "size"),
            avg_diff=(value_col, "mean"),
            plus_rate=("plus", "mean"),
            hit104_rate=("hit104", "mean"),
        )
        .reset_index()
    )
    agg = agg[agg["n"] >= min_n].copy()
    agg["avg_diff"] = agg["avg_diff"].round(0)
    agg["plus_rate"] = (agg["plus_rate"] * 100).round(1)
    agg["hit104_rate"] = (agg["hit104_rate"] * 100).round(1)
    return agg


def kruskal_groups(df: pd.DataFrame, group_cols: list[str], value_col: str = "diff", min_n_per_group: int = 10) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    if df.empty:
        return pd.DataFrame(columns=[*group_cols, "kruskal_stat", "p_value", "epsilon_sq", "n_groups", "total_n"])
    for key, grp in df.groupby(group_cols, dropna=False):
        if isinstance(key, tuple):
            row = {col: val for col, val in zip(group_cols, key)}
        else:
            row = {group_cols[0]: key}
        values = [
            g[value_col].dropna().to_numpy()
            for _, g in grp.groupby(next(c for c in ["last_digit", "machine_digit", "dd", "kakuban_rank", "seg", "day_of_week"] if c in grp.columns), dropna=False)
            if len(g) >= min_n_per_group
        ]
        if len(values) < 2:
            continue
        stat, p_value = stats.kruskal(*values)
        row.update(
            {
                "kruskal_stat": round(float(stat), 3),
                "p_value": round(float(p_value), 6),
                "epsilon_sq": round(float(_epsilon_squared(float(stat), len(values), int(sum(len(v) for v in values)))), 6),
                "n_groups": len(values),
                "total_n": int(sum(len(v) for v in values)),
            }
        )
        rows.append(row)
    if not rows:
        return pd.DataFrame(columns=[*group_cols, "kruskal_stat", "p_value", "epsilon_sq", "n_groups", "total_n"])
    out = pd.DataFrame(rows)
    sort_cols = ["p_value"] if "p_value" in out.columns else []
    if sort_cols:
        out = out.sort_values(sort_cols + [c for c in group_cols if c in out.columns]).reset_index(drop=True)
    return out


def kruskal_digit_groups(df: pd.DataFrame, group_cols: list[str], digit_col: str = "last_digit", value_col: str = "diff", min_n_per_digit: int = 10) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    if df.empty:
        return pd.DataFrame(columns=[*group_cols, "kruskal_stat", "p_value", "epsilon_sq", "n_groups", "total_n"])
    for key, grp in df.groupby(group_cols, dropna=False):
        if isinstance(key, tuple):
            row = {col: val for col, val in zip(group_cols, key)}
        else:
            row = {group_cols[0]: key}
        groups = [g[value_col].dropna().to_numpy() for _, g in grp.groupby(digit_col, dropna=False) if len(g) >= min_n_per_digit]
        if len(groups) < 2:
            continue
        stat, p_value = stats.kruskal(*groups)
        row.update(
            {
                "kruskal_stat": round(float(stat), 3),
                "p_value": round(float(p_value), 6),
                "epsilon_sq": round(float(_epsilon_squared(float(stat), len(groups), int(sum(len(v) for v in groups)))), 6),
                "n_groups": len(groups),
                "total_n": int(sum(len(v) for v in groups)),
            }
        )
        rows.append(row)
    if not rows:
        return pd.DataFrame(columns=[*group_cols, "kruskal_stat", "p_value", "epsilon_sq", "n_groups", "total_n"])
    out = pd.DataFrame(rows)
    sort_cols = ["p_value"] if "p_value" in out.columns else []
    if sort_cols:
        out = out.sort_values(sort_cols + [c for c in group_cols if c in out.columns]).reset_index(drop=True)
    return out


def mann_whitney(a: np.ndarray, b: np.ndarray) -> tuple[float, float]:
    a = np.asarray(a, dtype=float)
    b = np.asarray(b, dtype=float)
    a = a[~np.isnan(a)]
    b = b[~np.isnan(b)]
    if len(a) < 5 or len(b) < 5:
        return np.nan, np.nan
    stat, p_value = stats.mannwhitneyu(a, b, alternative="two-sided")
    return float(stat), float(p_value)


def cohen_d(a: np.ndarray, b: np.ndarray) -> float:
    a = np.asarray(a, dtype=float)
    b = np.asarray(b, dtype=float)
    a = a[~np.isnan(a)]
    b = b[~np.isnan(b)]
    if len(a) < 2 or len(b) < 2:
        return np.nan
    na = len(a)
    nb = len(b)
    va = a.var(ddof=1)
    vb = b.var(ddof=1)
    pooled = ((na - 1) * va + (nb - 1) * vb) / (na + nb - 2)
    if pooled <= 0 or np.isnan(pooled):
        return np.nan
    return float((a.mean() - b.mean()) / math.sqrt(pooled))


def fisher_z_pvalue(r1: float, n1: int, r2: float, n2: int) -> float:
    if any(pd.isna(v) for v in [r1, r2]) or n1 <= 3 or n2 <= 3:
        return np.nan
    r1 = float(np.clip(r1, -0.999999, 0.999999))
    r2 = float(np.clip(r2, -0.999999, 0.999999))
    z1 = np.arctanh(r1)
    z2 = np.arctanh(r2)
    se = math.sqrt(1 / (n1 - 3) + 1 / (n2 - 3))
    if se <= 0:
        return np.nan
    z = abs(z1 - z2) / se
    return float(2 * (1 - stats.norm.cdf(z)))


def bootstrap_mean_ci(values: np.ndarray, n_boot: int = 1000, ci: float = 95) -> tuple[float, float]:
    return _bootstrap_ci(np.asarray(values, dtype=float), n_boot=n_boot, ci=ci)


def epsilon_from_kruskal(stat: float, k: int, n: int) -> float:
    if pd.isna(stat):
        return np.nan
    return float(_epsilon_squared(float(stat), int(k), int(n)))


def resample_stratified_kruskal(
    df: pd.DataFrame,
    digit_col: str = "last_digit",
    value_col: str = "diff",
    target_n: int | None = None,
    n_boot: int = 1000,
    min_n_per_digit: int = 10,
    random_state: int = 42,
) -> float:
    if df.empty:
        return np.nan
    source = df[[digit_col, value_col]].dropna().copy()
    digit_counts = source[digit_col].value_counts()
    digits = [d for d in digit_counts.index.tolist() if digit_counts.loc[d] >= min_n_per_digit]
    if len(digits) < 2:
        return np.nan
    if target_n is None:
        target_n = int(len(source))
    rng = np.random.default_rng(random_state)
    proportions = digit_counts.loc[digits] / digit_counts.loc[digits].sum()
    digit_targets = {d: int(round(target_n * float(proportions.loc[d]))) for d in digits}
    diff = target_n - sum(digit_targets.values())
    if diff != 0:
        largest = max(digits, key=lambda d: digit_targets[d])
        digit_targets[largest] += diff

    successes = 0
    for _ in range(n_boot):
        sample_parts: list[pd.DataFrame] = []
        for digit in digits:
            grp = source[source[digit_col] == digit]
            n_take = max(min_n_per_digit, digit_targets[digit])
            idx = rng.integers(0, len(grp), size=n_take)
            sample_parts.append(grp.iloc[idx])
        sample = pd.concat(sample_parts, ignore_index=True)
        groups = [
            g[value_col].to_numpy()
            for _, g in sample.groupby(digit_col)
            if len(g) >= min_n_per_digit
        ]
        if len(groups) < 2:
            continue
        _, p_value = stats.kruskal(*groups)
        if p_value < 0.05:
            successes += 1
    return successes / n_boot


def split_half_dates(df: pd.DataFrame, date_col: str = "date") -> tuple[pd.Series, pd.Series]:
    dates = pd.Index(sorted(pd.unique(df[date_col].astype(str))))
    mid = len(dates) // 2
    return pd.Series(dates[:mid]), pd.Series(dates[mid:])
