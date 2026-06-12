"""Generate a standalone HTML prototype for the Kamata1 floor map."""

from __future__ import annotations

import argparse
from pathlib import Path

try:
    from Heatmap.generate_kamata7_cardmap_html import (
        FloorSpec,
        METRICS,
        WEEKDAY_LABELS,
        build_cardmap_html,
    )
except ModuleNotFoundError:
    from generate_kamata7_cardmap_html import (  # type: ignore[no-redef]
        FloorSpec,
        METRICS,
        WEEKDAY_LABELS,
        build_cardmap_html,
    )


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DB_PATH = PROJECT_ROOT / "db" / "マルハンメガシティ2000-蒲田1.db"
DEFAULT_OUTPUT_PATH = Path(__file__).with_name("kamata1_cardmap_preview.html")
HALL_NAME = "マルハンメガシティ2000-蒲田1"
# 2331-2340 は5円スロット島のため、カード型フロアマップでは除外する。
EXCLUDE_MACHINE_NUMBERS = tuple(range(2331, 2341))

FLOOR_SPECS = (
    FloorSpec(
        floor="2F",
        title="蒲田1 2F",
        coords_path=Path(__file__).with_name("2F_floor_coordinates_kamata1.csv"),
        exclude_machine_numbers=EXCLUDE_MACHINE_NUMBERS,
    ),
)

# 蒲田1は1フロアに島が多く縦長になるため、元グリッドに忠実な正方スロットで
# 描き、自動縮小を抑えてスクロール表示することでカードの可読性を確保する。
CARD_LAYOUT = {
    "slot_x": 40,
    "slot_y": 30,
    "pad": 8,
    "fit_mode": "scroll",
    "min_scale": 0.65,
}


def build_kamata1_cardmap_html(
    *,
    output_path: Path | None = None,
    metric_key: str = "avg_diff",
    start_date: str | None = None,
    end_date: str | None = None,
    weekdays: list[int] | list[str] | None = None,
    day_of_months: list[int] | list[str] | None = None,
) -> str:
    """Build the Kamata1 prototype HTML and optionally write it to disk."""

    return build_cardmap_html(
        hall_name=HALL_NAME,
        db_path=DB_PATH,
        floor_specs=FLOOR_SPECS,
        output_path=output_path,
        metric_key=metric_key,
        start_date=start_date,
        end_date=end_date,
        weekdays=weekdays,
        day_of_months=day_of_months,
        **CARD_LAYOUT,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate the Kamata1 card-map HTML prototype")
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT_PATH,
        help="Output HTML file path",
    )
    parser.add_argument(
        "--metric",
        choices=sorted(METRICS),
        default="avg_diff",
        help="Metric used for card coloring and badge display",
    )
    parser.add_argument(
        "--start-date",
        default=None,
        help="Optional start date in YYYYMMDD format",
    )
    parser.add_argument(
        "--end-date",
        default=None,
        help="Optional end date in YYYYMMDD format",
    )
    parser.add_argument(
        "--weekday",
        action="append",
        choices=list(WEEKDAY_LABELS),
        help="Optional weekday filter (can be repeated)",
    )
    parser.add_argument(
        "--day-of-month",
        action="append",
        type=int,
        choices=list(range(1, 32)),
        help="Optional day-of-month filter (can be repeated)",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    weekday_indices = (
        [WEEKDAY_LABELS.index(label) for label in args.weekday]
        if args.weekday
        else None
    )
    build_kamata1_cardmap_html(
        output_path=args.output,
        metric_key=args.metric,
        start_date=args.start_date,
        end_date=args.end_date,
        weekdays=weekday_indices,
        day_of_months=args.day_of_month,
    )
    print(f"Wrote {args.output}")


if __name__ == "__main__":
    main()
