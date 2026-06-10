"""Generate Kamata1 floor coordinates from physical machine runs."""

from __future__ import annotations

import csv
from pathlib import Path


HALL_NAME = "マルハンメガシティ2000-蒲田1"
FLOOR = "2F"
OUTPUT_PATH = Path(__file__).with_name("2F_floor_coordinates.csv")
FIELDNAMES = [
    "hall_name",
    "floor",
    "machine_number",
    "X",
    "Y",
    "display_x",
    "display_y",
    "section",
    "section_min",
    "section_max",
    "rank_from_min",
    "rank_from_max",
]


def machine_range(start: int, end: int) -> list[int]:
    return list(range(start, end + 1))


def add_run(
    rows: list[dict[str, object]],
    machines: list[int],
    start_x: int,
    start_y: int,
    step_x: int,
    step_y: int,
) -> None:
    """Append one physical row or diagonal of machines."""

    section_min = min(machines)
    section_max = max(machines)
    section = f"{section_min}-{section_max}"

    for index, machine_number in enumerate(machines):
        x = start_x + index * step_x
        y = start_y + index * step_y
        rows.append(
            {
                "hall_name": HALL_NAME,
                "floor": FLOOR,
                "machine_number": machine_number,
                "X": x,
                "Y": y,
                "display_x": x,
                "display_y": y,
                "section": section,
                "section_min": section_min,
                "section_max": section_max,
                "rank_from_min": machine_number - section_min + 1,
                "rank_from_max": section_max - machine_number + 1,
            }
        )


def build_rows() -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []

    runs = [
        (machine_range(1631, 1633), 11, 2, 1, 0),
        (machine_range(2001, 2020), 10, 22, 1, -1),
        (machine_range(2021, 2031), 48, 3, 1, 0),
        (machine_range(2032, 2042), 58, 8, -1, 0),
        (machine_range(2043, 2059), 40, 11, -1, 1),
        (machine_range(2060, 2076), 23, 30, 1, -1),
        (machine_range(2077, 2087), 48, 11, 1, 0),
        (machine_range(2088, 2098), 58, 16, -1, 0),
        (machine_range(2099, 2109), 44, 19, -1, 1),
        (machine_range(2110, 2120), 34, 32, 1, -1),
        (machine_range(2121, 2131), 48, 19, 1, 0),
        (machine_range(2132, 2142), 58, 24, -1, 0),
        (machine_range(2143, 2146), 43, 31, -1, 1),
        (machine_range(2147, 2150), 40, 37, 1, -1),
        (machine_range(2151, 2161), 48, 27, 1, 0),
        (machine_range(2162, 2166), 43, 37, -1, 1),
        (machine_range(2167, 2176), 19, 34, -1, 0),
        (machine_range(2177, 2186), 10, 37, 1, 0),
        (machine_range(2187, 2190), 40, 43, 1, -1),
        (machine_range(2191, 2202), 52, 35, -1, 1),
        (machine_range(2203, 2212), 19, 43, -1, 0),
        (machine_range(2213, 2222), 10, 46, 1, 0),
        (machine_range(2223, 2235), 41, 49, 1, -1),
        (machine_range(2236, 2255), 60, 39, -1, 1),
        (machine_range(2256, 2268), 22, 52, -1, 0),
        (machine_range(2269, 2281), 10, 55, 1, 0),
        (machine_range(2282, 2301), 41, 61, 1, -1),
        (machine_range(2302, 2316), 65, 49, -1, 1),
        (machine_range(2317, 2330), 27, 68, -1, 0),
        (machine_range(2331, 2340), 31, 68, 0, 1),
        (machine_range(2399, 2415), 3, 56, 0, 1),
    ]

    for run in runs:
        add_run(rows, *run)

    validate_rows(rows)
    return sorted(rows, key=lambda row: int(row["machine_number"]))


def validate_rows(rows: list[dict[str, object]]) -> None:
    machine_numbers = [int(row["machine_number"]) for row in rows]
    coordinates = [
        (int(row["display_x"]), int(row["display_y"])) for row in rows
    ]
    expected = (
        set(range(2001, 2341))
        | set(range(2399, 2416))
        | {1631, 1632, 1633}
    )

    if set(machine_numbers) != expected:
        missing = sorted(expected - set(machine_numbers))
        extra = sorted(set(machine_numbers) - expected)
        raise ValueError(f"Machine coverage mismatch: missing={missing}, extra={extra}")
    if len(machine_numbers) != len(set(machine_numbers)):
        raise ValueError("Duplicate machine numbers found")
    if len(coordinates) != len(set(coordinates)):
        duplicates = sorted(
            coordinate
            for coordinate in set(coordinates)
            if coordinates.count(coordinate) > 1
        )
        raise ValueError(f"Duplicate display coordinates found: {duplicates}")


def main() -> None:
    rows = build_rows()
    with OUTPUT_PATH.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)

    print(f"Wrote {len(rows)} machines to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
