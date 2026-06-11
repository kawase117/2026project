from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

if __package__ is None or __package__ == "":
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from ml.corner_section.mitoya_corner_rules_common import (
    classify_mix_tier,
    load_corner_composite,
    normalize_corner_composite,
)

OUTPUT_DIR_DEFAULT = "data/mitoya_corner_deep"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Mitoya main_mix DD/weekday rule analysis.")
    parser.add_argument("--db-path", default="", help="Explicit DB path override (reserved for parity).")
    parser.add_argument("--output-dir", default=OUTPUT_DIR_DEFAULT, help="Directory containing corner_composite.csv and output CSV.")
    return parser


def build_rule_table(df: pd.DataFrame) -> pd.DataFrame:
    work = df.loc[
        df["island"].eq("main_mix")
        & df["corner_metric"].eq("physical_corner")
    ].copy()
    if work.empty:
        return pd.DataFrame(columns=["dd_group", "day_of_week", "rank_tier", "avg_diff", "plus_rate", "sample_n"])

    # AT島全台を DD×曜日 で加重平均集約（rank 軸を潰す）
    agg = (
        work.groupby(["dd_group", "day_of_week"])
        .apply(
            lambda g: pd.Series({
                "avg_diff": (g["avg_diff"] * g["sample_n"]).sum() / g["sample_n"].sum(),
                "plus_rate": (g["plus_rate"] * g["sample_n"]).sum() / g["sample_n"].sum(),
                "sample_n": g["sample_n"].sum(),
            })
        )
        .reset_index()
    )
    agg["avg_diff"] = agg["avg_diff"].round(0).astype(int)
    agg["plus_rate"] = agg["plus_rate"].round(1)
    agg["sample_n"] = agg["sample_n"].astype(int)
    agg = agg.sort_values(["avg_diff", "sample_n"], ascending=[False, False]).reset_index(drop=True)
    agg["rank_tier"] = agg.apply(
        lambda row: classify_mix_tier(float(row["avg_diff"]), float(row["plus_rate"]), int(row["sample_n"])),
        axis=1,
    )
    return agg.loc[:, ["dd_group", "day_of_week", "rank_tier", "avg_diff", "plus_rate", "sample_n"]]


def _render_section(title: str, df: pd.DataFrame) -> str:
    lines = [title]
    if df.empty:
        lines.append("(no rows)")
    else:
        lines.append(df.loc[:, ["dd_group", "day_of_week", "avg_diff", "plus_rate", "sample_n"]].to_string(index=False))
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    args = build_parser().parse_args(argv)
    output_dir = Path(args.output_dir)
    composite = normalize_corner_composite(load_corner_composite(output_dir))
    rule_table = build_rule_table(composite)

    out_csv = output_dir / "mix_dd_weekday_rules.csv"
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    rule_table.to_csv(out_csv, index=False, encoding="utf-8-sig")

    top20 = rule_table.sort_values(["avg_diff", "sample_n"], ascending=[False, False]).head(20).copy()
    section_a = rule_table.loc[rule_table["rank_tier"].eq("A")].sort_values(["avg_diff", "sample_n"], ascending=[False, False])
    section_b = rule_table.loc[rule_table["rank_tier"].eq("B")].sort_values(["avg_diff", "sample_n"], ascending=[False, False])
    section_c = rule_table.loc[rule_table["rank_tier"].eq("C")].sort_values(["avg_diff", "sample_n"], ascending=[False, False])
    section_av = rule_table.loc[rule_table["rank_tier"].eq("Avoid")].sort_values(["avg_diff", "sample_n"], ascending=[False, False])

    print("=== みとや AT島 DD×曜日 島全体傾向ルール ===")
    print("  (AT島全台の加重平均。機種別詳細は別スクリプト参照)")
    print("")
    print(_render_section("[Top20 by avg_diff]", top20))
    print("")
    print(_render_section("[A：強い日程（avg_diff>=1000, plus_rate>=57%, n>=50）]", section_a))
    print("")
    print(_render_section("[B：やや好調（avg_diff>=600, plus_rate>=52%）]", section_b))
    print("")
    print(_render_section("[C：参考（その他）]", section_c))
    print("")
    print(_render_section("[Avoid：マイナス傾向または勝率<40%]", section_av))
    print(f"CSV written: {out_csv}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

