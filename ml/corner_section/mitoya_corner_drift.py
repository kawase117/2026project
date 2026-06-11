from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

if __package__ is None or __package__ == "":
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from ml.corner_section.mitoya_corner_deep_common import (
    CORNER_METRICS,
    ISLAND_ORDER,
    build_drift_timeseries,
    corner_rank_profile,
    kruskal_summary,
    load_corner_frame,
    prepare_corner_frame,
    resolve_mitoya_db_path,
)

OUTPUT_DIR_DEFAULT = "data/mitoya_corner_deep"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Mitoya corner drift analysis.")
    parser.add_argument("--db-path", default="", help="Explicit DB path override.")
    parser.add_argument("--db-dir", default="db", help="Directory used for DB auto-resolution.")
    parser.add_argument("--output-dir", default=OUTPUT_DIR_DEFAULT, help="Directory for output CSVs.")
    return parser


def _render_summary(df: pd.DataFrame, timeseries: pd.DataFrame) -> str:
    plus_df = df.loc[df["plus_flag"].eq(1)].copy()

    lines = [
        "=== みとや 角番ドリフト比較 ===",
        "",
    ]
    for island in ISLAND_ORDER:
        island_df = plus_df if island == "all" else plus_df.loc[plus_df["island"].eq(island)].copy()
        island_ts = timeseries if island == "all" else timeseries.loc[timeseries["island"].eq(island)].copy()
        if island_df.empty:
            continue

        recent_cutoff = island_df["date_dt"].max() - pd.Timedelta(days=179)
        recent_df = island_df.loc[island_df["date_dt"] >= recent_cutoff].copy()
        lines.append(f"[island={island}]")
        for metric in CORNER_METRICS:
            full_kw = kruskal_summary(island_df, group_col=metric)
            recent_kw = kruskal_summary(recent_df, group_col=metric)
            full_profile = corner_rank_profile(island_df, metric)
            recent_profile = corner_rank_profile(recent_df, metric)
            full_gradient = float("nan")
            recent_gradient = float("nan")
            if not full_profile.empty and {1, 5}.issubset(set(full_profile["rank"].tolist())):
                row1 = full_profile.loc[full_profile["rank"].eq(1)].iloc[0]
                row5 = full_profile.loc[full_profile["rank"].eq(5)].iloc[0]
                full_gradient = float(row1["avg_diff"] - row5["avg_diff"])
            if not recent_profile.empty and {1, 5}.issubset(set(recent_profile["rank"].tolist())):
                row1 = recent_profile.loc[recent_profile["rank"].eq(1)].iloc[0]
                row5 = recent_profile.loc[recent_profile["rank"].eq(5)].iloc[0]
                recent_gradient = float(row1["avg_diff"] - row5["avg_diff"])

            metric_ts = island_ts.loc[island_ts["corner_metric"].eq(metric)].copy()
            change_date = "n/a"
            change_value = float("nan")
            if not metric_ts.empty:
                metric_ts = metric_ts.sort_values("window_end").reset_index(drop=True)
                metric_ts["gradient_delta"] = metric_ts["gradient_diff"].diff().abs()
                if metric_ts["gradient_delta"].notna().any():
                    idx = metric_ts["gradient_delta"].idxmax()
                    change_date = str(metric_ts.loc[idx, "window_end"])
                    change_value = float(metric_ts.loc[idx, "gradient_delta"])

            lines.extend(
                [
                    f"  [{metric}]",
                    f"    full: epsilon_sq={float(full_kw['epsilon_sq']):.6f} gradient_diff={full_gradient:.2f}",
                    f"    recent(180d): epsilon_sq={float(recent_kw['epsilon_sq']):.6f} gradient_diff={recent_gradient:.2f}",
                    f"    change_point: {change_date} delta_gradient={change_value:.2f}",
                ]
            )
        lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    args = build_parser().parse_args(argv)
    db_path = resolve_mitoya_db_path(str(args.db_path), db_dir=Path(args.db_dir))
    raw = load_corner_frame(db_path)
    df = prepare_corner_frame(raw)
    timeseries = build_drift_timeseries(df, window_days=180)

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    timeseries.to_csv(out_dir / "corner_drift_timeseries.csv", index=False, encoding="utf-8-sig")

    print(_render_summary(df, timeseries))
    print(f"CSV written: {out_dir / 'corner_drift_timeseries.csv'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
