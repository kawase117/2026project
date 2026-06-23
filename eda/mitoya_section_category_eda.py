"""
Mitoya section/category/regime EDA.

Branches:
  A: Section(列) × DD/X_DDS split-half
  B: A群/AT群 × X_DDS interaction
  C: Hallwide payout monthly regime shift
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd
from scipy.stats import mannwhitneyu, spearmanr
from statsmodels.stats.multitest import multipletests

DB_PATH = Path(__file__).resolve().parents[1] / "db" / "みとや大森町店.db"
MACHINE_MASTER = (
    Path(__file__).resolve().parents[1]
    / "document"
    / "machine_master_research"
    / "machine_list_for_research.csv"
)
X_DDS = {4, 7, 14, 17, 24, 27}
A_GROUP = {"ノーマル", "Aタイプ", "A+AT", "A+ART"}
AT_GROUP = {"AT", "ART", "スマスロ", "AT(擬似ノーマル)"}
OUT_DIR = Path(__file__).resolve().parents[1] / "tmp" / "mitoya_section_category_eda"
DEFAULT_SPLIT_DATE = pd.Timestamp("2025-07-01")
MIN_CELL_DAYS = 20
MIN_SECTION_SIZE = 3

SECTION_RANGES = {
    "501-522": (501, 522),
    "523-556": (523, 556),
    "557-590": (557, 590),
    "591-623": (591, 623),
    "624-657": (624, 657),
    "658-691": (658, 691),
    "692-711": (692, 711),
    "712-733": (712, 733),
    "734-755": (734, 755),
    "805-815": (805, 815),
}

WEEKDAY_ORDER = [
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
    "Sunday",
]


def _format_value(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, (float, np.floating)):
        if np.isnan(value):
            return ""
        return f"{float(value):.3f}" if abs(float(value)) < 100 else f"{float(value):.2f}"
    if isinstance(value, (bool, np.bool_)):
        return "True" if bool(value) else "False"
    return str(value)


def _markdown_table(df: pd.DataFrame, columns: Iterable[str] | None = None) -> str:
    frame = df.copy()
    if columns is not None:
        frame = frame.loc[:, list(columns)]
    if frame.empty:
        return "_no rows_"

    headers = list(frame.columns)
    rows = [headers]
    for _, row in frame.iterrows():
        rows.append([_format_value(row[col]) for col in headers])

    widths = [max(len(str(row[i])) for row in rows) for i in range(len(headers))]
    lines = []
    lines.append("| " + " | ".join(str(headers[i]).ljust(widths[i]) for i in range(len(headers))) + " |")
    lines.append("| " + " | ".join("-" * widths[i] for i in range(len(headers))) + " |")
    for row in rows[1:]:
        lines.append("| " + " | ".join(str(row[i]).ljust(widths[i]) for i in range(len(headers))) + " |")
    return "\n".join(lines)


def _resolve_split_date(df: pd.DataFrame, split_date: pd.Timestamp = DEFAULT_SPLIT_DATE) -> pd.Timestamp:
    if df.empty:
        return split_date
    date_min = pd.Timestamp(df["date"].min())
    date_max = pd.Timestamp(df["date"].max())
    if split_date < date_min or split_date > date_max:
        return date_min + (date_max - date_min) / 2
    return split_date


def _derive_section(machine_number: int) -> str | None:
    for name, (lo, hi) in SECTION_RANGES.items():
        if lo <= machine_number <= hi:
            return name
    return None


def _dd_group(dd: int) -> str:
    if dd in {7, 17, 27}:
        return "7系"
    if dd in {4, 14, 24}:
        return "4系"
    if dd in {1, 11, 21}:
        return "1系"
    if dd in {30, 31}:
        return "月末"
    return "その他"


def _section_order(value: str) -> tuple[int, str]:
    try:
        start = int(value.split("-")[0])
    except Exception:
        return (10_000, value)
    return (start, value)


def load_data_with_section(db_path: Path = DB_PATH) -> pd.DataFrame:
    """Load machine-level data and add section/payout fields."""
    with sqlite3.connect(db_path) as conn:
        layout_schema = pd.read_sql_query("PRAGMA table_info(machine_layout)", conn)
        has_layout = not layout_schema.empty
        has_section = bool(has_layout and "section" in set(layout_schema["name"]))

        if has_section:
            df = pd.read_sql_query(
                """
                SELECT
                    r.date,
                    r.machine_number,
                    r.machine_name,
                    l.y,
                    r.diff_coins_normalized,
                    r.games_normalized,
                    l.section
                FROM machine_detailed_results AS r
                LEFT JOIN machine_layout AS l
                    ON r.machine_number = l.machine_number
                """,
                conn,
            )
        else:
            df = pd.read_sql_query(
                """
                SELECT
                    date,
                    machine_number,
                    machine_name,
                    diff_coins_normalized,
                    games_normalized
                FROM machine_detailed_results
                """,
                conn,
            )
            df["section"] = df["machine_number"].map(_derive_section)
            df["y"] = np.nan

    df["date"] = pd.to_datetime(df["date"], format="%Y%m%d")
    df["dd"] = df["date"].dt.day
    df["dd_group"] = df["dd"].map(_dd_group)
    df["is_xdds"] = df["dd"].isin(X_DDS).astype(int)
    if "y" in df.columns and df["y"].notna().any():
        df["section"] = df["section"].astype(str) + "_y" + df["y"].astype("Int64").astype(str)
    denom = (df["games_normalized"] * 3).replace(0, np.nan)
    df["payout_pct"] = ((denom + df["diff_coins_normalized"]) / denom) * 100
    return df


def classify_category(df: pd.DataFrame, csv_path: Path = MACHINE_MASTER) -> pd.DataFrame:
    """Add `category` column using machine master classification."""
    master = pd.read_csv(csv_path, encoding="utf-8-sig")
    if not {"machine_name", "machine_type"} <= set(master.columns):
        raise ValueError("machine master is missing required columns: machine_name, machine_type")

    master = master.copy()
    master["machine_name"] = master["machine_name"].astype(str).str.strip()
    name_to_type = master.drop_duplicates("machine_name").set_index("machine_name")["machine_type"].to_dict()

    def _cat(name: str) -> str:
        machine_type = name_to_type.get(str(name).strip())
        if machine_type is None or pd.isna(machine_type):
            return "unclassified"
        if machine_type in A_GROUP:
            return "A群"
        if machine_type in AT_GROUP:
            return "AT群"
        return "unclassified"

    out = df.copy()
    out["category"] = out["machine_name"].map(_cat)

    unique_machines = out.drop_duplicates("machine_name")[["machine_name", "category"]]
    counts = unique_machines["category"].value_counts()
    match_rate = 1.0 - counts.get("unclassified", 0) / max(len(unique_machines), 1)
    print(f"[classify_category] {counts.to_dict()}, match_rate={match_rate:.1%}")
    return out


def _ensure_analysis_frame(df: pd.DataFrame, csv_path: Path = MACHINE_MASTER) -> pd.DataFrame:
    out = df.copy()
    if "category" not in out.columns:
        out = classify_category(out, csv_path)
    if "date" in out.columns and "dd_group" not in out.columns:
        out["date"] = pd.to_datetime(out["date"])
        out["dd"] = out["date"].dt.day
        out["dd_group"] = out["dd"].map(_dd_group)
    if "date" in out.columns and "is_xdds" not in out.columns:
        out["date"] = pd.to_datetime(out["date"])
        out["is_xdds"] = out["date"].dt.day.isin(X_DDS).astype(int)
    if "payout_pct" not in out.columns and {"games_normalized", "diff_coins_normalized"} <= set(out.columns):
        denom = (out["games_normalized"] * 3).replace(0, np.nan)
        out["payout_pct"] = ((denom + out["diff_coins_normalized"]) / denom) * 100
    return out


def _dominant_category(sec_df: pd.DataFrame) -> str:
    counts = sec_df.drop_duplicates("machine_number")["category"].value_counts()
    if counts.empty:
        return "unknown"
    top = counts.index[0]
    top_pct = counts.iloc[0] / counts.sum()
    if top_pct < 0.7:
        return "mixed"
    return str(top)


def branch_a_section_split_half(df: pd.DataFrame, min_cell_days: int = MIN_CELL_DAYS) -> pd.DataFrame:
    df = _ensure_analysis_frame(df)
    records: list[dict[str, object]] = []
    split_date = _resolve_split_date(df)
    sections = [
        section
        for section in sorted(df["section"].dropna().astype(str).unique(), key=_section_order)
        if len(df[df["section"] == section]["machine_number"].unique()) >= MIN_SECTION_SIZE
    ]

    for section in sections:
        sec_df = df[df["section"] == section].copy()
        daily = (
            sec_df.groupby("date")
            .agg(
                payout_pct=("payout_pct", "mean"),
                dd_group=("dd_group", "first"),
                is_xdds=("is_xdds", "first"),
            )
            .reset_index()
        )
        dom_cat = _dominant_category(sec_df)

        axis_specs = [
            ("is_xdds", "is_xdds", [0, 1]),
            ("dd_group", "dd_group", ["7系", "4系", "1系", "月末", "その他"]),
        ]
        for axis_label, col, order in axis_specs:
            values = [value for value in order if value in set(daily[col].dropna().tolist())]
            extra = [value for value in daily[col].dropna().unique().tolist() if value not in values]
            values.extend(sorted(extra))
            for value in values:
                cell = daily[daily[col] == value]
                rest = daily[daily[col] != value]
                if len(cell) < min_cell_days or len(rest) < 5:
                    continue
                first_cell = cell[cell["date"] <= split_date]["payout_pct"].to_numpy()
                second_cell = cell[cell["date"] > split_date]["payout_pct"].to_numpy()
                if min(len(first_cell), len(second_cell)) < min_cell_days:
                    continue

                rest_vals = rest["payout_pct"].to_numpy()
                _, p1 = mannwhitneyu(first_cell, rest_vals, alternative="two-sided")
                _, p2 = mannwhitneyu(second_cell, rest_vals, alternative="two-sided")
                delta = cell["payout_pct"].mean() - rest["payout_pct"].mean()
                delta1 = first_cell.mean() - rest_vals.mean()
                delta2 = second_cell.mean() - rest_vals.mean()
                consistent = np.sign(delta1) == np.sign(delta2) and delta1 != 0 and delta2 != 0

                records.append(
                    {
                        "section": section,
                        "axis_label": axis_label,
                        "axis_value": str(value),
                        "delta_pct": round(float(delta), 3),
                        "p1": float(p1),
                        "p2": float(p2),
                        "p_combined": float(max(p1, p2)),
                        "consistent_direction": bool(consistent),
                        "n_cell_first": int(len(first_cell)),
                        "n_cell_second": int(len(second_cell)),
                        "n_rest": int(len(rest_vals)),
                        "dominant_category": dom_cat,
                    }
                )

    result = pd.DataFrame(records)
    if result.empty:
        return pd.DataFrame(
            columns=[
                "section",
                "axis_label",
                "axis_value",
                "delta_pct",
                "p1",
                "p2",
                "p_combined",
                "consistent_direction",
                "n_cell_first",
                "n_cell_second",
                "n_rest",
                "dominant_category",
                "q_value",
                "stable",
            ]
        )

    _, q_values, _, _ = multipletests(result["p_combined"].to_numpy(), method="fdr_bh")
    result["q_value"] = q_values
    result["stable"] = (
        (result["q_value"] < 0.05)
        & (result["consistent_direction"])
        & (result["n_cell_first"] >= min_cell_days)
        & (result["n_cell_second"] >= min_cell_days)
    )
    return result


def branch_b_category_xdds(df: pd.DataFrame) -> pd.DataFrame:
    """Return 2x2 summary for A群/AT群 x day_type."""
    df = _ensure_analysis_frame(df)
    work = df[df["category"].isin(["A群", "AT群"])].copy()
    if work.empty:
        return pd.DataFrame(
            columns=["category", "day_type", "mean_payout", "hit_rate_104", "hit_rate_100", "n_machine_days"]
        )

    work["day_type"] = work["is_xdds"].map({1: "X_DDS", 0: "non_X_DDS"})
    summary = (
        work.groupby(["category", "day_type"])
        .agg(
            mean_payout=("payout_pct", "mean"),
            hit_rate_104=("payout_pct", lambda s: (s >= 104).mean()),
            hit_rate_100=("payout_pct", lambda s: (s >= 100).mean()),
            n_machine_days=("payout_pct", "count"),
        )
        .reset_index()
        .sort_values(["category", "day_type"])
        .reset_index(drop=True)
    )
    return summary


def branch_b_split_half_spearman(df: pd.DataFrame, split_date: pd.Timestamp = DEFAULT_SPLIT_DATE) -> pd.DataFrame:
    df = _ensure_analysis_frame(df)
    work = df[(df["is_xdds"] == 1) & (df["category"].isin(["A群", "AT群"]))].copy()
    rows: list[dict[str, object]] = []
    split_date = _resolve_split_date(work, split_date)
    print("\n[Branch B] Split-half Spearman (X_DDS, machine_name level):")

    for category in ["A群", "AT群"]:
        cat_df = work[work["category"] == category]
        first = cat_df[cat_df["date"] <= split_date].groupby("machine_name")["payout_pct"].mean()
        second = cat_df[cat_df["date"] > split_date].groupby("machine_name")["payout_pct"].mean()
        common = first.index.intersection(second.index)
        if len(common) < 5:
            rows.append({"category": category, "rho": np.nan, "p_value": np.nan, "n_machines": int(len(common))})
            print(f"  {category}: insufficient machines (n={len(common)})")
            continue

        rho, p_value = spearmanr(first.loc[common].to_numpy(), second.loc[common].to_numpy())
        rows.append(
            {
                "category": category,
                "rho": float(rho) if pd.notna(rho) else np.nan,
                "p_value": float(p_value) if pd.notna(p_value) else np.nan,
                "n_machines": int(len(common)),
            }
        )
        print(f"  {category}: rho={rho:.3f} p={p_value:.4f} n_machines={len(common)}")

    return pd.DataFrame(rows)


def branch_c_regime_monthly(df: pd.DataFrame) -> pd.DataFrame:
    work = df.copy()
    if work.empty:
        return pd.DataFrame(columns=["year_month", "median_payout", "hit_rate_104", "hit_rate_100", "n_days"])

    work["year_month"] = work["date"].dt.to_period("M")
    monthly = (
        work.groupby("year_month")
        .agg(
            median_payout=("payout_pct", "median"),
            hit_rate_104=("payout_pct", lambda s: (s >= 104).mean()),
            hit_rate_100=("payout_pct", lambda s: (s >= 100).mean()),
            n_days=("payout_pct", "count"),
        )
        .reset_index()
    )
    monthly["year_month"] = monthly["year_month"].astype(str)
    return monthly


def _load_daily_hall_summary(db_path: Path = DB_PATH) -> pd.DataFrame:
    with sqlite3.connect(db_path) as conn:
        schema = pd.read_sql_query("PRAGMA table_info(daily_hall_summary)", conn)
        columns = set(schema["name"].tolist())
        if {"avg_games_per_machine", "avg_diff_per_machine"} <= columns:
            hall = pd.read_sql_query(
                """
                SELECT date, avg_games_per_machine, avg_diff_per_machine
                FROM daily_hall_summary
                """,
                conn,
            )
        elif {"total_games", "total_diff_coins", "total_machines"} <= columns:
            hall = pd.read_sql_query(
                """
                SELECT date, total_games, total_diff_coins, total_machines
                FROM daily_hall_summary
                """,
                conn,
            )
            hall["avg_games_per_machine"] = hall["total_games"] / hall["total_machines"].replace(0, np.nan)
            hall["avg_diff_per_machine"] = hall["total_diff_coins"] / hall["total_machines"].replace(0, np.nan)
        else:
            raise ValueError(f"Unsupported daily_hall_summary schema: {sorted(columns)}")

    hall["date"] = pd.to_datetime(hall["date"], format="%Y%m%d")
    hall["payout_pct"] = (
        (hall["avg_games_per_machine"] * 3 + hall["avg_diff_per_machine"])
        / (hall["avg_games_per_machine"] * 3).replace(0, np.nan)
        * 100
    )
    return hall


def _regime_shift_test(hall: pd.DataFrame, split_date: pd.Timestamp = DEFAULT_SPLIT_DATE) -> dict[str, object]:
    split_date = _resolve_split_date(hall, split_date)
    first_half = hall[hall["date"] < split_date]["payout_pct"].dropna().to_numpy()
    second_half = hall[hall["date"] >= split_date]["payout_pct"].dropna().to_numpy()
    if len(first_half) == 0 or len(second_half) == 0:
        return {
            "split_date": split_date,
            "first_median": np.nan,
            "second_median": np.nan,
            "first_hit_rate_104": np.nan,
            "second_hit_rate_104": np.nan,
            "p_value": np.nan,
            "detected": False,
        }

    _, p_value = mannwhitneyu(first_half, second_half, alternative="two-sided")
    return {
        "split_date": split_date,
        "first_median": float(np.median(first_half)),
        "second_median": float(np.median(second_half)),
        "first_hit_rate_104": float(np.mean(first_half >= 104)),
        "second_hit_rate_104": float(np.mean(second_half >= 104)),
        "p_value": float(p_value),
        "detected": bool(p_value < 0.05),
    }


def _stable_rate_table(df_a: pd.DataFrame) -> pd.DataFrame:
    sections = (
        df_a[["section", "dominant_category", "stable"]]
        .drop_duplicates("section")
        .copy()
    )
    if sections.empty:
        return pd.DataFrame(columns=["category", "n_sections", "stable_sections", "stable_rate"])
    return (
        sections.groupby("dominant_category")
        .agg(n_sections=("section", "count"), stable_sections=("stable", "sum"))
        .reset_index()
        .rename(columns={"dominant_category": "category"})
        .assign(stable_rate=lambda frame: frame["stable_sections"] / frame["n_sections"])
        .sort_values("category")
        .reset_index(drop=True)
    )


def _branch_b_lift_table(df_b: pd.DataFrame) -> pd.DataFrame:
    if df_b.empty:
        return pd.DataFrame(columns=["category", "non_X_DDS", "X_DDS", "lift"])
    pivot = df_b.pivot(index="category", columns="day_type", values="mean_payout").reset_index()
    for col in ["non_X_DDS", "X_DDS"]:
        if col not in pivot.columns:
            pivot[col] = np.nan
    pivot["lift"] = pivot["X_DDS"] - pivot["non_X_DDS"]
    return pivot[["category", "non_X_DDS", "X_DDS", "lift"]].sort_values("category").reset_index(drop=True)


def _top_branch_a_rows(
    df_a: pd.DataFrame,
    axis_label: str,
    stable_only: bool = True,
    axis_value: str | None = None,
) -> pd.DataFrame:
    work = df_a[df_a["axis_label"] == axis_label].copy()
    if axis_value is not None:
        work = work[work["axis_value"] == axis_value]
    if stable_only:
        work = work[work["stable"]]
    if work.empty:
        return work
    return (
        work.sort_values(["q_value", "delta_pct"], ascending=[True, False])
        .loc[:, ["section", "axis_value", "delta_pct", "q_value", "dominant_category", "n_cell_first", "n_cell_second"]]
        .reset_index(drop=True)
    )


def _branch_a_reverse_rows(df_a: pd.DataFrame) -> pd.DataFrame:
    work = df_a[
        (df_a["axis_label"] == "is_xdds")
        & (df_a["axis_value"] == "1")
        & ((~df_a["stable"]) | (df_a["delta_pct"] < 0))
    ].copy()
    if work.empty:
        return work
    return (
        work.sort_values(["delta_pct", "q_value"], ascending=[True, True])
        .loc[:, ["section", "axis_value", "delta_pct", "q_value", "dominant_category", "stable"]]
        .reset_index(drop=True)
    )


def _write_branch_a_report(df_a: pd.DataFrame) -> str:
    stable_table = _stable_rate_table(df_a)
    stable_xdds = _top_branch_a_rows(df_a, "is_xdds", stable_only=True, axis_value="1")
    stable_weekday = _top_branch_a_rows(df_a, "weekday", stable_only=True)
    reverse_table = _branch_a_reverse_rows(df_a)

    lines = [
        "## Branch A: Section × Weekday/X_DDS Split-Half EDA",
        "",
        "### A群 vs AT群 stable率",
        _markdown_table(
            stable_table.rename(
                columns={
                    "category": "category",
                    "n_sections": "n_sections",
                    "stable_sections": "stable_sections",
                    "stable_rate": "stable_rate",
                }
            ).assign(stable_rate=lambda frame: (frame["stable_rate"] * 100).round(1).astype(str) + "%"),
            columns=["category", "n_sections", "stable_sections", "stable_rate"],
        ),
        "",
        "(Kamata7 reference: A群 56%, AT群 22%)",
        "",
        "### Stable sections - X_DDS日 (is_xdds=1)",
        _markdown_table(stable_xdds if not stable_xdds.empty else stable_xdds),
        "",
        "### Stable sections - 曜日別 top hits",
        _markdown_table(stable_weekday if not stable_weekday.empty else stable_weekday),
        "",
        "### Non-stable / 逆方向 sections (X_DDS, stable=False)",
        _markdown_table(reverse_table),
        "",
    ]
    return "\n".join(lines)


def _write_branch_b_report(df_b: pd.DataFrame, rho_df: pd.DataFrame) -> str:
    lift_table = _branch_b_lift_table(df_b)
    category_summary = df_b.copy()
    category_summary["hit_rate_104"] = category_summary["hit_rate_104"].map(lambda x: f"{x * 100:.1f}%")
    category_summary["hit_rate_100"] = category_summary["hit_rate_100"].map(lambda x: f"{x * 100:.1f}%")
    rho_table = rho_df.copy()
    conclusion = "差なし"
    if not lift_table.empty and lift_table["lift"].notna().any():
        best = lift_table.sort_values("lift", ascending=False).iloc[0]
        if pd.notna(best["lift"]) and best["lift"] > 0:
            conclusion = str(best["category"])

    lines = [
        "## Branch B: A群/AT群 × X_DDS 交互作用",
        "",
        "### 2×2 summary",
        _markdown_table(category_summary, columns=["category", "day_type", "mean_payout", "hit_rate_104", "hit_rate_100", "n_machine_days"]),
        "",
        "### X_DDS lift per category",
        _markdown_table(lift_table),
        "",
        "### Split-half Spearman (X_DDS days, machine_name level)",
        _markdown_table(rho_table),
        "",
        "### 結論",
        f"- X_DDS日のリフトが大きいカテゴリ: {conclusion}",
        f"- 推奨: {('A群を優先' if conclusion == 'A群' else 'AT群を優先' if conclusion == 'AT群' else '差なし')}",
        "- 参考: 全機種合算ではrho=0.346(p=0.020, confirmed in instincts)",
        "",
    ]
    return "\n".join(lines)


def _write_branch_c_report(df_c: pd.DataFrame, hall: pd.DataFrame, regime_test: dict[str, object]) -> str:
    monthly = df_c.copy()
    monthly["median_payout"] = monthly["median_payout"].round(2)
    monthly["hit_rate_104"] = monthly["hit_rate_104"].map(lambda x: f"{x * 100:.1f}%")
    monthly["hit_rate_100"] = monthly["hit_rate_100"].map(lambda x: f"{x * 100:.1f}%")

    first_median = regime_test["first_median"]
    second_median = regime_test["second_median"]
    first_hit = regime_test["first_hit_rate_104"]
    second_hit = regime_test["second_hit_rate_104"]
    p_value = regime_test["p_value"]
    detected = regime_test["detected"]

    lines = [
        "## Branch C: ホール全体 Payout 時系列レジーム変化",
        "",
        "### Monthly summary",
        _markdown_table(monthly, columns=["year_month", "median_payout", "hit_rate_104", "hit_rate_100", "n_days"]),
        "",
        f"### Regime shift test (split {regime_test['split_date'].date()})",
        f"- First half:  median={first_median:.2f}%  hit_rate_104={first_hit:.3f}",
        f"- Second half: median={second_median:.2f}%  hit_rate_104={second_hit:.3f}",
        f"- Mann-Whitney p={p_value:.4f} → {'REGIME SHIFT DETECTED' if detected else 'no significant shift'}",
        "",
        "### 解釈",
    ]
    if detected:
        lines.extend(
            [
                "- 全期間split-half検証は前半・後半で異質な母集団を比較している可能性あり",
                "- Branch A の stable判定は split_date を境界として前後半で再検証推奨",
                "- 既存の mitoya backtest / persistence 結果も再評価対象",
            ]
        )
    else:
        lines.extend(
            [
                "- 全期間データでの split-half は概ね均質な母集団を比較しており有効",
            ]
        )
    lines.append("")
    return "\n".join(lines)


def _write_master_report(df_a: pd.DataFrame, df_b: pd.DataFrame, df_c: pd.DataFrame, hall: pd.DataFrame, regime_test: dict[str, object]) -> str:
    stable_table = _stable_rate_table(df_a)
    lift_table = _branch_b_lift_table(df_b)
    branch_a_stable = _top_branch_a_rows(df_a, "is_xdds", stable_only=True, axis_value="1")
    branch_a_reverse = _branch_a_reverse_rows(df_a)

    if not lift_table.empty and lift_table["lift"].notna().any():
        best_idx = lift_table["lift"].astype(float).idxmax()
        best_category = str(lift_table.loc[best_idx, "category"])
    else:
        best_category = "差なし"

    hall_recent = hall[hall["date"] >= (hall["date"].max() - pd.Timedelta(days=92))].copy()
    hall_recent_median = float(hall_recent["payout_pct"].median()) if not hall_recent.empty else float("nan")
    hall_recent_hit = float((hall_recent["payout_pct"] >= 104).mean()) if not hall_recent.empty else float("nan")
    hall_state = "変化あり" if regime_test.get("detected") else "正常"

    lines = [
        "# Mitoya Section/Category/Regime EDA",
        "",
        "## Summary",
        f"- Branch A stable rows: {int(df_a['stable'].sum()) if not df_a.empty else 0}",
        f"- Branch B strongest category: {best_category}",
        f"- Branch C regime: {hall_state}",
        "",
        "## Branch A stable-rate snapshot",
        _markdown_table(
            stable_table.assign(stable_rate=lambda frame: (frame["stable_rate"] * 100).round(1).astype(str) + "%"),
            columns=["category", "n_sections", "stable_sections", "stable_rate"],
        ),
        "",
        "## Branch B lift snapshot",
        _markdown_table(lift_table),
        "",
        "## Branch C recent state",
        f"- Recent 3 months median payout: {hall_recent_median:.2f}%",
        f"- Recent 3 months hit_rate_104: {hall_recent_hit:.3f}",
        f"- Regime: {hall_state}",
        "",
        "## 今日の実戦向け示唆 (2026-06-17, X_DDS日 DD=7)",
        "",
        "### Section(列)選び - Branch A 結果",
        _markdown_table(branch_a_stable.loc[:, ["section", "delta_pct", "dominant_category"]] if not branch_a_stable.empty else branch_a_stable),
        "",
        "逆方向 / non-stable sections:",
        _markdown_table(branch_a_reverse.loc[:, ["section", "delta_pct", "dominant_category", "stable"]] if not branch_a_reverse.empty else branch_a_reverse),
        "",
        "### A群/AT群 どちらを優先するか - Branch B 結果",
        _markdown_table(lift_table),
        f"結論: {('A群を優先' if best_category == 'A群' else 'AT群を優先' if best_category == 'AT群' else '差なし')}",
        "",
        "### ホール全体の状態 - Branch C 結果",
        f"直近3ヶ月 median payout: {hall_recent_median:.2f}%",
        f"hit_rate_104: {hall_recent_hit:.3f}",
        f"レジーム: {hall_state}",
        "",
    ]
    return "\n".join(lines)


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    print("=== Loading data ===")
    df = classify_category(load_data_with_section())
    print(f"Rows: {len(df)} | Date: {df['date'].min().date()} ~ {df['date'].max().date()}")
    print(f"Sections: {df['section'].nunique()} (null: {int(df['section'].isna().sum())})")

    print("\n=== Branch A: Section × Weekday/X_DDS split-half ===")
    df_a = branch_a_section_split_half(df)
    df_a.to_csv(OUT_DIR / "section_split_half.csv", index=False, encoding="utf-8-sig")
    df_a[df_a["stable"]].to_csv(OUT_DIR / "section_stable_only.csv", index=False, encoding="utf-8-sig")
    (OUT_DIR / "branch_a_report.md").write_text(_write_branch_a_report(df_a), encoding="utf-8")

    print("\n=== Branch B: A群/AT群 × X_DDS ===")
    df_b = branch_b_category_xdds(df)
    df_b.to_csv(OUT_DIR / "branch_b_category_xdds.csv", index=False, encoding="utf-8-sig")
    rho_df = branch_b_split_half_spearman(df)
    (OUT_DIR / "branch_b_report.md").write_text(_write_branch_b_report(df_b, rho_df), encoding="utf-8")

    print("\n=== Branch C: Regime change ===")
    hall = _load_daily_hall_summary()
    print(f"Hall rows: {len(hall)} | Date: {hall['date'].min().date()} ~ {hall['date'].max().date()}")
    df_c = branch_c_regime_monthly(hall)
    regime_test = _regime_shift_test(hall)
    df_c.to_csv(OUT_DIR / "branch_c_regime_monthly.csv", index=False, encoding="utf-8-sig")
    (OUT_DIR / "branch_c_report.md").write_text(_write_branch_c_report(df_c, hall, regime_test), encoding="utf-8")

    master_report = _write_master_report(df_a, df_b, df_c, hall, regime_test)
    (OUT_DIR / "master_report.md").write_text(master_report, encoding="utf-8")

    print(f"\n✅ All outputs written to {OUT_DIR}/")


if __name__ == "__main__":
    main()
