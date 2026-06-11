"""
mitoya_aisle_distance_analysis.py
==================================
「角番」定義の比較検証:
  1. rank_from_min   : 低番号端からの順位（ノーマル）
  2. rank_from_aisle : メイン通路からの距離（DB格納済み、逆順補正後）
  3. physical_corner : min(rank_from_min, rank_from_max)（両端最小距離）

逆順セクション定義は hall_config.json の layout_settings.reversed_sections に記載。
DB の machine_layout.is_reversed_section / rank_from_aisle に展開済み。
このスクリプトはセクションのハードコードを一切持たない。
"""
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
    resolve_mitoya_db_path,
)

OUTPUT_DIR_DEFAULT = "data/mitoya_aisle_distance_analysis"
METRIC_LABELS = {
    "rank_from_min": "ノーマル (rank_from_min)",
    "rank_from_aisle": "通路距離ベース (rank_from_aisle)",
    "physical_corner": "両端最小距離 min(min,max)",
}


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def _load_raw(db_path: Path) -> pd.DataFrame:
    # rank_from_aisle / is_reversed_section は DB に格納済み
    # (hall_config.json の layout_settings.reversed_sections から展開)
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
        ml.rank_from_aisle,
        ml.is_reversed_section,
        ml.section,
        COALESCE(mm.jug_flag, 0)  AS jug_flag,
        COALESCE(mm.hana_flag, 0) AS hana_flag,
        COALESCE(mm.oki_flag, 0)  AS oki_flag,
        COALESCE(mm.bt_flag, 0)   AS bt_flag,
        COALESCE(dh.avg_diff_per_machine, 0) AS avg_diff_per_machine
    FROM machine_detailed_results m
    LEFT JOIN machine_layout ml ON m.machine_number = ml.machine_number
    LEFT JOIN machine_master mm ON m.machine_name = mm.machine_name_normalized
    LEFT JOIN daily_hall_summary dh ON m.date = dh.date
    """
    con = sqlite3.connect(db_path)
    try:
        df = pd.read_sql_query(query, con)
    finally:
        con.close()
    if df.empty:
        raise ValueError(f"No rows loaded from {db_path}")
    return df


def _prepare(df: pd.DataFrame) -> pd.DataFrame:
    work = df.copy()
    work = work.dropna(subset=["rank_from_min", "rank_from_max", "rank_from_aisle", "section"]).copy()
    for col in ["rank_from_min", "rank_from_max", "rank_from_aisle"]:
        work[col] = pd.to_numeric(work[col], errors="coerce")
    work = work.dropna(subset=["rank_from_min", "rank_from_max", "rank_from_aisle"]).copy()
    for col in ["rank_from_min", "rank_from_max", "rank_from_aisle"]:
        work[col] = work[col].astype(int)

    # machine_type
    conds = [
        pd.to_numeric(work["jug_flag"],  errors="coerce").fillna(0).eq(1),
        pd.to_numeric(work["hana_flag"], errors="coerce").fillna(0).eq(1),
        pd.to_numeric(work["oki_flag"],  errors="coerce").fillna(0).eq(1),
        pd.to_numeric(work["bt_flag"],   errors="coerce").fillna(0).eq(1),
    ]
    work["machine_type"] = np.select(conds, ["jug", "hana", "oki", "bt"], default="other")

    work["is_hall_plus"] = (
        pd.to_numeric(work["avg_diff_per_machine"], errors="coerce").fillna(0).gt(0).astype(int)
    )

    # physical_corner のみここで計算（rank_from_aisle は DB から取得済み）
    work["physical_corner"] = (
        work[["rank_from_min", "rank_from_max"]]
        .astype(float)
        .min(axis=1)
        .astype(int)
    )

    return work


# ---------------------------------------------------------------------------
# Kruskal-Wallis helper
# ---------------------------------------------------------------------------

def _epsilon_sq(statistic: float, n_groups: int, n_rows: int) -> float:
    if not np.isfinite(statistic) or n_groups < 2 or n_rows <= n_groups:
        return float("nan")
    return float(max((statistic - n_groups + 1) / (n_rows - n_groups), 0.0))


def _kruskal(df: pd.DataFrame, group_col: str, min_n: int = 30) -> dict:
    work = df.dropna(subset=[group_col, "diff_coins_normalized"]).copy()
    work[group_col] = pd.to_numeric(work[group_col], errors="coerce")
    work = work.dropna(subset=[group_col]).copy()
    work[group_col] = work[group_col].astype(int)

    counts = work.groupby(group_col).size()
    valid = counts[counts >= min_n].index.tolist()
    filtered = work[work[group_col].isin(valid)]
    n_rows = len(filtered)
    n_groups = len(valid)

    statistic = p_value = float("nan")
    if n_groups >= 2:
        groups = [
            filtered[filtered[group_col] == g]["diff_coins_normalized"].to_numpy(float)
            for g in valid
        ]
        try:
            statistic, p_value = stats.kruskal(*groups)
        except ValueError:
            pass

    return {
        "n_groups": n_groups,
        "n_rows": n_rows,
        "H": round(float(statistic), 4) if np.isfinite(statistic) else float("nan"),
        "p_value": float(p_value) if np.isfinite(p_value) else float("nan"),
        "epsilon_sq": round(_epsilon_sq(statistic, n_groups, n_rows), 6),
        "significant": "Yes" if np.isfinite(p_value) and p_value < 0.05 else "No",
    }


# ---------------------------------------------------------------------------
# Rank-level avg diff (gradient table)
# ---------------------------------------------------------------------------

def _rank_table(df: pd.DataFrame, col: str, max_rank: int = 10) -> pd.DataFrame:
    work = df.dropna(subset=[col, "diff_coins_normalized"]).copy()
    work[col] = pd.to_numeric(work[col], errors="coerce").astype("Int64")
    work = work[work[col] <= max_rank]
    result = (
        work.groupby(col, sort=True)
        .agg(
            avg_diff=("diff_coins_normalized", "mean"),
            plus_rate=("diff_coins_normalized", lambda s: float((pd.to_numeric(s, errors="coerce") > 0).mean())),
            n=("diff_coins_normalized", "size"),
        )
        .reset_index()
        .rename(columns={col: "rank"})
    )
    result["avg_diff"] = result["avg_diff"].round(0).astype(int)
    result["plus_rate"] = (result["plus_rate"] * 100).round(1)
    return result


# ---------------------------------------------------------------------------
# Reversed section coverage report
# ---------------------------------------------------------------------------

def _reversed_coverage(df: pd.DataFrame) -> str:
    """逆順セクションの統計を DB の is_reversed_section カラムから集計する。"""
    rev_sections = sorted(df[df["is_reversed_section"] == 1]["section"].dropna().unique())
    total_rows = len(df)
    reversed_rows = int((df["is_reversed_section"] == 1).sum())
    lines = [
        f"[逆順セクション（DBより）]: {len(rev_sections)} セクション",
        f"  {rev_sections}",
        f"  逆順セクション行数: {reversed_rows:,} / {total_rows:,} ({reversed_rows / total_rows * 100:.1f}%)",
        f"  (定義は hall_config.json > layout_settings.reversed_sections)",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main comparison
# ---------------------------------------------------------------------------

def run_comparison(df: pd.DataFrame) -> dict[str, object]:
    plus_df = df[df["is_hall_plus"] == 1].copy()
    metrics = ["rank_from_min", "rank_from_aisle", "physical_corner"]

    kruskal_rows = []
    rank_tables: dict[str, pd.DataFrame] = {}
    for col in metrics:
        kw = _kruskal(plus_df, col)
        kruskal_rows.append({"metric": col, "label": METRIC_LABELS[col], **kw})
        rank_tables[col] = _rank_table(plus_df, col)

    kruskal_df = pd.DataFrame(kruskal_rows)
    return {"kruskal": kruskal_df, "rank_tables": rank_tables}


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

def _render(results: dict, df: pd.DataFrame) -> str:
    kdf = results["kruskal"]
    rank_tables = results["rank_tables"]
    lines: list[str] = []

    lines.append("=" * 70)
    lines.append("  みとや 角番定義比較分析")
    lines.append("  ノーマル / 通路距離ベース / 両端最小距離")
    lines.append("=" * 70)
    lines.append("")
    lines.append(_reversed_coverage(df))
    lines.append("")

    # Kruskal-Wallis comparison
    lines.append("[Kruskal-Wallis 比較（プラス日限定）]")
    lines.append(f"{'指標':<32} {'n_g':>5} {'H':>8} {'p':>10} {'ε²':>10} {'有意':>6}")
    lines.append("-" * 75)
    for _, row in kdf.iterrows():
        p_str = f"{row['p_value']:.4g}" if pd.notna(row["p_value"]) else "nan"
        eps_str = f"{row['epsilon_sq']:.6f}" if pd.notna(row["epsilon_sq"]) else "nan"
        lines.append(
            f"{row['label']:<32} {int(row['n_groups']):>5} {row['H']:>8.2f} {p_str:>10} {eps_str:>10} {row['significant']:>6}"
        )
    lines.append("")

    # Rank gradient tables (side by side comparison: rank 1-5)
    lines.append("[ランク1〜5 の avg_diff 比較（プラス日限定）]")
    header = f"{'rank':>5}  "
    header += "  ".join(f"{'avg[' + METRIC_LABELS[col][:6] + ']':>20}" for col in ["rank_from_min", "rank_from_aisle", "physical_corner"])
    lines.append(header)
    lines.append("-" * 80)
    for rank in range(1, 6):
        row_parts = [f"{rank:>5}  "]
        for col in ["rank_from_min", "rank_from_aisle", "physical_corner"]:
            rt = rank_tables[col]
            match = rt[rt["rank"] == rank]
            if match.empty:
                row_parts.append(f"{'---':>20}  ")
            else:
                r = match.iloc[0]
                row_parts.append(f"{int(r['avg_diff']):>+8,d} ({r['plus_rate']:>4.1f}% n={int(r['n']):>5,})  ")
        lines.append("".join(row_parts))
    lines.append("")

    # Full rank tables
    for col in ["rank_from_min", "rank_from_aisle", "physical_corner"]:
        label = METRIC_LABELS[col]
        lines.append(f"[ランク別 avg_diff — {label}]")
        rt = rank_tables[col]
        if rt.empty:
            lines.append("  (no data)")
        else:
            lines.append(rt.to_string(index=False))
        lines.append("")

    # Winner summary
    lines.append("[判定サマリー]")
    best = kdf.loc[kdf["epsilon_sq"].idxmax()]
    lines.append(f"  ε² 最大（最も説明力が高い指標）: {best['label']}")
    lines.append(f"  ε²={best['epsilon_sq']:.6f}  H={best['H']:.2f}  p={best['p_value']:.4g}")
    lines.append("")
    for _, row in kdf.sort_values("epsilon_sq", ascending=False).iterrows():
        lines.append(
            f"    {row['label']}: ε²={row['epsilon_sq']:.6f}  H={row['H']:.2f}  {row['significant']}"
        )
    lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Compare corner definitions: rank_from_min vs rank_from_aisle vs physical_corner"
    )
    p.add_argument("--db-path", default="", help="DB path override")
    p.add_argument("--db-dir", default="db")
    p.add_argument("--output-dir", default=OUTPUT_DIR_DEFAULT)
    return p


def main(argv: list[str] | None = None) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    args = build_parser().parse_args(argv)
    db_path = resolve_mitoya_db_path(str(args.db_path), db_dir=Path(args.db_dir))

    print(f"DB: {db_path}")
    raw = _load_raw(db_path)
    df = _prepare(raw)
    print(
        f"行数: {len(df):,}  "
        f"(逆順セクション: {int((df['is_reversed_section'] == 1).sum()):,}行)"
    )

    results = run_comparison(df)

    out = Path(args.output_dir)
    out.mkdir(parents=True, exist_ok=True)
    results["kruskal"].to_csv(out / "kruskal_comparison.csv", index=False, encoding="utf-8-sig")
    for col, rt in results["rank_tables"].items():
        rt.to_csv(out / f"rank_table_{col}.csv", index=False, encoding="utf-8-sig")

    print(_render(results, df))
    print(f"CSV保存: {out}/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
