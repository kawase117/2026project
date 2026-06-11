from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

if __package__ is None or __package__ == "":
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from ml.corner_section.mitoya_corner_deep_common import (
    CORNER_METRICS,
    DD_GROUP_ORDER,
    ISLAND_ORDER,
    iter_island_frames,
    WEEKDAY_ORDER,
    corner_rank_profile,
    load_corner_frame,
    resolve_mitoya_db_path,
    prepare_corner_frame,
)

OUTPUT_DIR_DEFAULT = "data/mitoya_corner_deep"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Mitoya DD/weekday/corner composite analysis.")
    parser.add_argument("--db-path", default="", help="Explicit DB path override.")
    parser.add_argument("--db-dir", default="db", help="Directory used for DB auto-resolution.")
    parser.add_argument("--output-dir", default=OUTPUT_DIR_DEFAULT, help="Directory for output CSVs.")
    return parser


def build_composite_table(df: pd.DataFrame) -> pd.DataFrame:
    rows: list[pd.DataFrame] = []
    work = df.copy()
    if work.empty:
        return pd.DataFrame()

    for island, island_df in iter_island_frames(work):
        for metric in CORNER_METRICS:
            metric_df = island_df.dropna(subset=[metric]).copy()
            metric_df[metric] = pd.to_numeric(metric_df[metric], errors="coerce")
            metric_df = metric_df.dropna(subset=[metric]).copy()
            metric_df[metric] = metric_df[metric].astype(int)
            grouped = (
                metric_df.groupby(["dd_group", "day_of_week", metric], sort=True)
                .agg(
                    avg_diff=("diff_coins_normalized", "mean"),
                    avg_games=("games_normalized", "mean"),
                    plus_rate=("plus_flag", "mean"),
                    sample_n=("diff_coins_normalized", "size"),
                )
                .reset_index()
                .rename(columns={metric: "rank"})
            )
            grouped["island"] = island
            grouped["corner_metric"] = metric
            rows.append(grouped)

    result = pd.concat(rows, ignore_index=True)
    result["sample_n"] = result["sample_n"].astype(int)
    result["avg_diff"] = result["avg_diff"].round(0).astype(int)
    result["avg_games"] = result["avg_games"].round(0).astype(int)
    result["plus_rate"] = (result["plus_rate"] * 100).round(1)
    result["island"] = pd.Categorical(result["island"], categories=ISLAND_ORDER, ordered=True)
    result["dd_group"] = pd.Categorical(result["dd_group"], categories=DD_GROUP_ORDER, ordered=True)
    result["day_of_week"] = pd.Categorical(result["day_of_week"], categories=WEEKDAY_ORDER, ordered=True)
    result = result.sort_values(
        ["island", "corner_metric", "dd_group", "day_of_week", "rank"],
        kind="mergesort",
    ).reset_index(drop=True)
    result["island"] = result["island"].astype(str)
    result["dd_group"] = result["dd_group"].astype(str)
    result["day_of_week"] = result["day_of_week"].astype(str)
    return result


def _render_summary(df: pd.DataFrame, composite: pd.DataFrame) -> str:
    plus_df = df.loc[df["plus_flag"].eq(1)].copy()
    lines = [
        "=== みとや DD×曜日×角番 複合シグナル ===",
        "",
    ]
    for island in ISLAND_ORDER:
        island_df = plus_df if island == "all" else plus_df.loc[plus_df["island"].eq(island)].copy()
        island_composite = composite if island == "all" else composite.loc[composite["island"].eq(island)].copy()
        if island_df.empty:
            continue

        lines.append(f"[island={island}]")
        for metric in CORNER_METRICS:
            lines.append(f"  [{metric} rank summary]")
            profile = corner_rank_profile(island_df, metric)
            if profile.empty:
                lines.append("  (no rows)")
            else:
                lines.append(profile.to_string(index=False))
            lines.append("")

            metric_rows = island_composite.loc[island_composite["corner_metric"].eq(metric)].copy()
            if metric_rows.empty:
                continue

            lines.append(f"  [{metric} TOP5 by avg_games]")
            lines.append(
                metric_rows.sort_values(["avg_games", "sample_n"], ascending=[False, False])
                .loc[:, ["dd_group", "day_of_week", "rank", "avg_games", "avg_diff", "plus_rate", "sample_n"]]
                .head(5)
                .to_string(index=False)
            )
            lines.append("")
            lines.append(f"  [{metric} TOP5 by avg_diff]")
            lines.append(
                metric_rows.sort_values(["avg_diff", "sample_n"], ascending=[False, False])
                .loc[:, ["dd_group", "day_of_week", "rank", "avg_games", "avg_diff", "plus_rate", "sample_n"]]
                .head(5)
                .to_string(index=False)
            )
            lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    args = build_parser().parse_args(argv)
    db_path = resolve_mitoya_db_path(str(args.db_path), db_dir=Path(args.db_dir))
    raw = load_corner_frame(db_path)
    df = prepare_corner_frame(raw)
    composite = build_composite_table(df)

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    composite.to_csv(out_dir / "corner_composite.csv", index=False, encoding="utf-8-sig")

    print(_render_summary(df, composite))
    print(f"CSV written: {out_dir / 'corner_composite.csv'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
