from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

if __package__ is None or __package__ == "":
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from ml.corner_section.mitoya_corner_section_analysis import (
    load_analysis_frame,
    prepare_analysis_frame,
    resolve_mitoya_db_path,
)

TYPE_ORDER = ["jug", "bt", "hana", "oki", "other"]
TYPE_ORDER_WITH_ALL = ["ALL", *TYPE_ORDER]
OUTPUT_DIR_DEFAULT = "data/mitoya_corner_section_analysis"


def _epsilon_squared(statistic: float, n_groups: int, n_rows: int) -> float:
    if not np.isfinite(statistic) or n_groups < 2 or n_rows <= n_groups:
        return float("nan")
    return float(max((statistic - n_groups + 1) / (n_rows - n_groups), 0.0))


def load_analysis_frame_with_corner(db_path: Path) -> pd.DataFrame:
    query = """
    SELECT
        m.date,
        m.machine_number,
        m.machine_name,
        m.diff_coins_normalized,
        m.machine_rank_in_type,
        m.games_normalized,
        ml.rank_from_min,
        ml.rank_from_max,
        ml.section,
        COALESCE(mm.jug_flag, 0) AS jug_flag,
        COALESCE(mm.hana_flag, 0) AS hana_flag,
        COALESCE(mm.oki_flag, 0) AS oki_flag,
        COALESCE(mm.bt_flag, 0) AS bt_flag,
        COALESCE(dh.avg_diff_per_machine, 0) AS avg_diff_per_machine
    FROM machine_detailed_results m
    LEFT JOIN machine_layout ml
      ON m.machine_number = ml.machine_number
    LEFT JOIN machine_master mm
      ON m.machine_name = mm.machine_name_normalized
    LEFT JOIN daily_hall_summary dh
      ON m.date = dh.date
    """
    con = sqlite3.connect(db_path)
    try:
        df = pd.read_sql_query(query, con)
    finally:
        con.close()
    if df.empty:
        raise ValueError(f"No rows loaded from {db_path}")
    return df


def _prepare_plus_frame(db_path: Path) -> pd.DataFrame:
    return prepare_analysis_frame(load_analysis_frame_with_corner(db_path))


def build_section_type_cross(df: pd.DataFrame) -> pd.DataFrame:
    work = df.loc[df["is_hall_plus"].eq(1)].copy()
    work["machine_type"] = work["machine_type"].astype(str)
    work["section"] = work["section"].astype(str)

    cross = (
        work.groupby(["section", "machine_type"], sort=True)
        .agg(
            sample_n=("diff_coins_normalized", "size"),
            avg_diff=("diff_coins_normalized", "mean"),
            plus_rate=("diff_coins_normalized", lambda s: float((pd.to_numeric(s, errors="coerce") > 0).mean())),
        )
        .reset_index()
    )
    cross["section_total_n"] = cross.groupby("section")["sample_n"].transform("sum")
    cross["machine_type_share_in_section"] = cross["sample_n"] / cross["section_total_n"].replace(0, np.nan)
    cross["machine_type_share_in_section"] = cross["machine_type_share_in_section"].fillna(0.0)
    cross = cross.loc[
        :,
        [
            "section",
            "machine_type",
            "sample_n",
            "section_total_n",
            "machine_type_share_in_section",
            "avg_diff",
            "plus_rate",
        ],
    ].sort_values(["section", "machine_type"], kind="mergesort").reset_index(drop=True)
    return cross


def _kruskal_scope_report(scope_df: pd.DataFrame, group_col: str, *, min_group_n: int = 30) -> dict[str, object]:
    work = scope_df.dropna(subset=[group_col, "diff_coins_normalized"]).copy()
    if group_col in {"rank_from_min", "rank_from_max", "physical_corner"}:
        work[group_col] = pd.to_numeric(work[group_col], errors="coerce")
        work = work.dropna(subset=[group_col]).copy()
        work[group_col] = work[group_col].astype(int)
    else:
        work[group_col] = work[group_col].astype(str)

    counts = work.groupby(group_col, sort=True).size()
    valid_groups = counts.loc[counts >= min_group_n].index.tolist()
    filtered = work.loc[work[group_col].isin(valid_groups)].copy()
    valid_groups = sorted(valid_groups)
    n_rows = int(len(filtered))
    statistic = float("nan")
    p_value = float("nan")
    if len(valid_groups) >= 2 and n_rows > len(valid_groups):
        try:
            groups = [
                filtered.loc[filtered[group_col].eq(group), "diff_coins_normalized"].to_numpy(dtype=float)
                for group in valid_groups
            ]
            statistic, p_value = stats.kruskal(*groups)
        except ValueError:
            statistic, p_value = float("nan"), float("nan")

    return {
        "n_groups": int(len(valid_groups)),
        "n_rows": n_rows,
        "statistic": float(statistic) if np.isfinite(statistic) else np.nan,
        "p_value": float(p_value) if np.isfinite(p_value) else np.nan,
        "epsilon_sq": _epsilon_squared(statistic, len(valid_groups), n_rows),
        "is_significant_5pct": int(np.isfinite(p_value) and p_value < 0.05),
    }


def _build_scope_table(
    df: pd.DataFrame,
    *,
    group_col: str,
    machine_types: list[str],
    include_all: bool = False,
) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    scopes = [(machine_type, df.loc[df["machine_type"].eq(machine_type)].copy()) for machine_type in machine_types]
    if include_all:
        scopes = [("ALL", df)] + scopes
    for machine_type, scope_df in scopes:
        report = _kruskal_scope_report(scope_df, group_col)
        rows.append({"machine_type": machine_type, **report})
    out = pd.DataFrame(rows)
    categories = TYPE_ORDER_WITH_ALL if include_all else TYPE_ORDER
    out["machine_type"] = pd.Categorical(out["machine_type"], categories=categories, ordered=True)
    return out.sort_values("machine_type", kind="mergesort").reset_index(drop=True)


def build_within_type_section_kruskal(df: pd.DataFrame) -> pd.DataFrame:
    work = df.loc[df["is_hall_plus"].eq(1)].copy()
    return _build_scope_table(work, group_col="section", machine_types=TYPE_ORDER, include_all=False)


def build_physical_corner_kruskal(df: pd.DataFrame) -> pd.DataFrame:
    work = df.loc[df["is_hall_plus"].eq(1)].copy()
    work["physical_corner"] = pd.to_numeric(
        work[["rank_from_min", "rank_from_max"]].min(axis=1), errors="coerce"
    )
    return _build_scope_table(work, group_col="physical_corner", machine_types=TYPE_ORDER, include_all=True)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Analyze whether section effects are independent of machine type in Mitoya.")
    parser.add_argument("--db-path", default="", help="Explicit DB path override.")
    parser.add_argument("--db-dir", default="db", help="Directory used for DB auto-resolution.")
    parser.add_argument("--output-dir", default=OUTPUT_DIR_DEFAULT, help="Directory for CSV outputs.")
    return parser


def _format_percent(value: float) -> str:
    if pd.isna(value):
        return "nan"
    return f"{float(value) * 100:.1f}%"


def _render_section_composition(cross: pd.DataFrame) -> str:
    if cross.empty:
        return "(no rows)"
    type_cols = TYPE_ORDER
    pivot = cross.pivot_table(index="section", columns="machine_type", values="sample_n", aggfunc="sum", fill_value=0)
    pivot = pivot.reindex(columns=type_cols, fill_value=0)
    section_totals = cross.groupby("section", sort=False)["sample_n"].sum().sort_values(ascending=False)
    avg_diff = cross.groupby("section", sort=False).apply(
        lambda g: float(np.average(g["avg_diff"], weights=g["sample_n"])) if float(g["sample_n"].sum()) > 0 else np.nan
    )
    rows = []
    for section in section_totals.head(5).index.tolist():
        counts = pivot.loc[section]
        total = float(counts.sum())
        rows.append(
            {
                "section": section,
                "jug%": _format_percent(counts.get("jug", 0) / total if total else np.nan),
                "bt%": _format_percent(counts.get("bt", 0) / total if total else np.nan),
                "hana%": _format_percent(counts.get("hana", 0) / total if total else np.nan),
                "oki%": _format_percent(counts.get("oki", 0) / total if total else np.nan),
                "other%": _format_percent(counts.get("other", 0) / total if total else np.nan),
                "avg_diff": float(avg_diff.get(section, np.nan)),
            }
        )
    return pd.DataFrame(rows).to_string(index=False)


def _render_within_type_table(report: pd.DataFrame) -> str:
    table = report.loc[:, ["machine_type", "n_groups", "epsilon_sq", "is_significant_5pct"]].copy()
    table["significant"] = table["is_significant_5pct"].map({0: "No", 1: "Yes"})
    table = table.loc[:, ["machine_type", "n_groups", "epsilon_sq", "significant"]]
    return table.to_string(index=False)


def _render_physical_corner(report: pd.DataFrame) -> str:
    rows = []
    for _, row in report.iterrows():
        rows.append(
            f"{row['machine_type']}: epsilon_sq={float(row['epsilon_sq']):.6f}  significant={'Yes' if int(row['is_significant_5pct']) == 1 else 'No'}"
        )
    return "\n".join(rows)


def _render_summary(section_cross: pd.DataFrame, section_kruskal: pd.DataFrame, physical_corner_kruskal: pd.DataFrame) -> str:
    within_eps = section_kruskal["epsilon_sq"].dropna()
    physical_eps = physical_corner_kruskal.loc[physical_corner_kruskal["machine_type"].eq("ALL"), "epsilon_sq"].iloc[0]
    lines = [
        "=== section の独立効果検証 ===",
        "",
        "[machine_type 構成比 by section（TOP5 section）]",
        "section | jug% | bt% | hana% | oki% | other% | avg_diff",
        _render_section_composition(section_cross),
        "",
        "[同一 machine_type 内 section 差（Kruskal-Wallis）]",
        "machine_type | n_groups | epsilon_sq | significant",
        _render_within_type_table(section_kruskal),
        "",
        "[physical_corner Kruskal-Wallis]",
        _render_physical_corner(physical_corner_kruskal),
        "",
        "[解釈]",
        f"- section 内の machine_type 別 epsilon_sq 最大値: {float(within_eps.max()):.6f}" if not within_eps.empty else "- section 内の machine_type 別 epsilon_sq は算出不可",
        f"- physical_corner (ALL) epsilon_sq: {float(physical_eps):.6f}" if pd.notna(physical_eps) else "- physical_corner (ALL) epsilon_sq: nan",
        "- section の強弱が machine_type で説明できる場合: 同一 machine_type 内の epsilon_sq が全体より大幅に小さい",
        "- section に独立した位置効果がある場合: 同一 machine_type 内でも section 差が有意",
        "- physical_corner が有意: 角番位置に独立効果あり",
    ]
    return "\n".join(lines) + "\n"


def _write_csv(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False, encoding="utf-8-sig")


def main(argv: list[str] | None = None) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    args = build_parser().parse_args(argv)
    db_path = resolve_mitoya_db_path(str(args.db_path), db_dir=Path(args.db_dir))
    prepared = _prepare_plus_frame(db_path)

    section_cross = build_section_type_cross(prepared)
    section_kruskal = build_within_type_section_kruskal(prepared)
    physical_corner_kruskal = build_physical_corner_kruskal(prepared)

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    _write_csv(section_cross, output_dir / "section_type_cross.csv")
    _write_csv(section_kruskal, output_dir / "section_within_type_kruskal.csv")
    _write_csv(physical_corner_kruskal, output_dir / "physical_corner_kruskal.csv")

    print(_render_summary(section_cross, section_kruskal, physical_corner_kruskal))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
