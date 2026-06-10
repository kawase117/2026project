"""Render a floor coordinate CSV as an ASCII grid for visual verification.

Usage:
    python Heatmap/preview_ascii.py <csv_path> [--floor 本館3F] [--hall 楽園蒲田店]

Each cell shows the last 3 digits of the machine number placed at its
(display_x, display_y) grid position (1-indexed, y increases downward).
Empty cells are shown as dots. This mirrors exactly how heatmap_common.py
plots markers, so the ASCII layout should match the source floor image.
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path


def load_cells(csv_path: Path, hall: str | None, floor: str | None) -> dict[tuple[int, int], str]:
    cells: dict[tuple[int, int], str] = {}
    with csv_path.open(encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            if hall is not None and row.get("hall_name") != hall:
                continue
            if floor is not None and row.get("floor") != floor:
                continue
            x = int(row["display_x"])
            y = int(row["display_y"])
            label = str(int(row["machine_number"]))[-3:]
            key = (x, y)
            if key in cells:
                cells[key] = "!!" + label  # collision marker
            else:
                cells[key] = label
    return cells


def render(cells: dict[tuple[int, int], str]) -> str:
    if not cells:
        return "(no cells)"
    max_x = max(x for x, _ in cells)
    max_y = max(y for _, y in cells)
    width = 4  # each cell printed in a fixed 4-char column

    lines: list[str] = []
    header = "y\\x ".rjust(width) + "".join(str(x).rjust(width) for x in range(1, max_x + 1))
    lines.append(header)
    for y in range(1, max_y + 1):
        cell_strs = []
        for x in range(1, max_x + 1):
            cell_strs.append(cells.get((x, y), ".").rjust(width))
        lines.append(str(y).rjust(width) + "".join(cell_strs))
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("csv_path", type=Path)
    parser.add_argument("--hall", default=None)
    parser.add_argument("--floor", default=None)
    args = parser.parse_args()

    cells = load_cells(args.csv_path, args.hall, args.floor)
    print(render(cells))
    print(f"\nTotal cells: {len(cells)}")


if __name__ == "__main__":
    main()
