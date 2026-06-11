from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

if __package__ is None or __package__ == "":
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from ml.corner_section.mitoya_corner_rules_common import (
    classify_jug_tier,
    load_corner_composite,
    normalize_corner_composite,
)

OUTPUT_DIR_DEFAULT = "data/mitoya_corner_deep"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Mitoya main_jug corner1 DD/weekday rule analysis.")
    parser.add_argument("--db-path", default="", help="Explicit DB path override (reserved for parity).")
    parser.add_argument("--output-dir", default=OUTPUT_DIR_DEFAULT, help="Directory containing corner_composite.csv and output CSV.")
    return parser


def build_rule_table(df: pd.DataFrame) -> pd.DataFrame:
    work = df.loc[
        df["island"].eq("main_jug")
        & df["rank"].eq(1)
        & df["sample_n"].ge(5)
        & df["corner_metric"].eq("physical_corner")
    ].copy()
    if work.empty:
        return pd.DataFrame(columns=["dd_group", "day_of_week", "rank_tier", "avg_diff", "plus_rate", "sample_n", "confidence_reason"])

    work = work.sort_values(["avg_diff", "sample_n"], ascending=[False, False]).reset_index(drop=True)
    tiers = work.apply(
        lambda row: pd.Series(classify_jug_tier(float(row["avg_diff"]), float(row["plus_rate"]), int(row["sample_n"])), index=["rank_tier", "confidence_reason"]),
        axis=1,
    )
    result = pd.concat([work, tiers], axis=1)
    return result.loc[:, ["dd_group", "day_of_week", "rank_tier", "avg_diff", "plus_rate", "sample_n", "confidence_reason"]]


def _render_section(title: str, df: pd.DataFrame, limit: int | None = None) -> str:
    lines = [title]
    if df.empty:
        lines.append("(no rows)")
    else:
        view = df if limit is None else df.head(limit)
        lines.append(
            view.loc[:, ["dd_group", "day_of_week", "avg_diff", "plus_rate", "sample_n", "confidence_reason"]]
            .to_string(index=False)
        )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    args = build_parser().parse_args(argv)
    output_dir = Path(args.output_dir)
    composite = normalize_corner_composite(load_corner_composite(output_dir))
    rule_table = build_rule_table(composite)

    out_csv = output_dir / "jug_corner1_rules.csv"
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    rule_table.to_csv(out_csv, index=False, encoding="utf-8-sig")

    top15 = rule_table.sort_values(["avg_diff", "sample_n"], ascending=[False, False]).head(15).copy()
    section_a = rule_table.loc[rule_table["rank_tier"].eq("A")].sort_values(["avg_diff", "sample_n"], ascending=[False, False])
    section_b = rule_table.loc[rule_table["rank_tier"].eq("B")].sort_values(["avg_diff", "sample_n"], ascending=[False, False])
    section_avoid = rule_table.loc[rule_table["rank_tier"].eq("Avoid")].sort_values(["avg_diff", "sample_n"], ascending=[False, False])

    print("=== みとや main_jug 角番1 運用ルール ===")
    print("")
    print(_render_section("[狙い目ランキング Top15]", top15, limit=15))
    print("")
    print(_render_section("[狙い目ランク A（n>=10, plus_rate>=80%, avg_diff>=1500）]", section_a))
    print("")
    print(_render_section("[狙い目ランク B（n>=5, plus_rate>=70%, avg_diff>=1200）]", section_b))
    print("")
    print(_render_section("[回避推奨ランク（plus_rate<60% または avg_diff<500）]", section_avoid))
    print(f"CSV written: {out_csv}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

