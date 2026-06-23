"""Generate Kamata7 2F and 3F floor coordinates from physical machine runs."""

from __future__ import annotations

import csv
from pathlib import Path


HALL_NAME = "マルハンメガシティ2000-蒲田7"
OUTPUT_PATHS = {
    "2F": Path(__file__).with_name("2F_floor_coordinates_kamata7.csv"),
    "3F": Path(__file__).with_name("3F_floor_coordinates_kamata7.csv"),
}
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
    "rank_from_aisle",
]
AISLE_X = 17.5
SECTION_RANGES = {
    "2F": [
        (2001, 2010),
        (2011, 2022),
        (2023, 2031),
        (2032, 2040),
        (2041, 2052),
        (2053, 2064),
        (2065, 2076),
        (2077, 2088),
        (2089, 2101),
        (2102, 2114),
        (2115, 2128),
        (2129, 2142),
        (2143, 2154),
        (2155, 2164),
        (2165, 2171),
        (2172, 2178),
        (2179, 2186),
        (2187, 2195),
        (2196, 2212),
        (2213, 2229),
        (2230, 2246),
        (2247, 2263),
        (2264, 2280),
        (2281, 2297),
        (2298, 2313),
        (2314, 2329),
        (2330, 2351),
    ],
    "3F": [
        (3001, 3016),
        (3017, 3030),
        (3031, 3042),
        (3043, 3057),
        (3058, 3072),
        (3073, 3087),
        (3088, 3102),
        (3103, 3116),
        (3117, 3130),
        (3131, 3143),
        (3144, 3155),
        (3156, 3167),
        (3168, 3180),
        (3181, 3190),
        (3191, 3208),
        (3209, 3217),
        (3218, 3233),
        (3234, 3249),
        (3250, 3264),
        (3265, 3280),
        (3281, 3294),
        (3295, 3309),
        (3310, 3324),
        (3325, 3340),
        (3341, 3362),
        (3400, 3401),
    ],
}


def machine_range(start: int, end: int) -> list[int]:
    return list(range(start, end + 1))


def add_points(
    rows: list[dict[str, object]],
    floor: str,
    machines: list[int],
    points: list[tuple[int, int]],
) -> None:
    if len(machines) != len(points):
        raise ValueError("Machine and coordinate counts differ")

    section_min = min(machines)
    section_max = max(machines)
    section = f"{section_min}-{section_max}"

    for machine_number, (x, y) in zip(machines, points, strict=True):
        rows.append(
            {
                "hall_name": HALL_NAME,
                "floor": floor,
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


def add_run(
    rows: list[dict[str, object]],
    floor: str,
    start: int,
    end: int,
    start_x: int,
    start_y: int,
    step_x: int,
    step_y: int,
) -> None:
    machines = machine_range(start, end)
    points = [
        (start_x + index * step_x, start_y + index * step_y)
        for index in range(len(machines))
    ]
    add_points(rows, floor, machines, points)


def apply_store_sections(
    rows: list[dict[str, object]],
    floor: str,
) -> None:
    section_by_machine: dict[int, tuple[int, int]] = {}
    for section_min, section_max in SECTION_RANGES[floor]:
        for machine_number in range(section_min, section_max + 1):
            if machine_number in section_by_machine:
                raise ValueError(
                    f"Overlapping section for machine {machine_number}"
                )
            section_by_machine[machine_number] = (section_min, section_max)

    row_machines = {int(row["machine_number"]) for row in rows}
    section_machines = set(section_by_machine)
    if row_machines != section_machines:
        missing = sorted(row_machines - section_machines)
        extra = sorted(section_machines - row_machines)
        raise ValueError(
            f"Section coverage mismatch: missing={missing}, extra={extra}"
        )

    section_rows: dict[tuple[int, int], list[dict[str, object]]] = {}
    for row in rows:
        machine_number = int(row["machine_number"])
        section_min, section_max = section_by_machine[machine_number]
        row["section"] = f"{section_min}-{section_max}"
        row["section_min"] = section_min
        row["section_max"] = section_max
        row["rank_from_min"] = machine_number - section_min + 1
        row["rank_from_max"] = section_max - machine_number + 1
        section_rows.setdefault((section_min, section_max), []).append(row)

    for members in section_rows.values():
        min_row = min(members, key=lambda r: int(r["machine_number"]))
        max_row = max(members, key=lambda r: int(r["machine_number"]))
        x_varies = int(min_row["X"]) != int(max_row["X"])
        if x_varies:
            min_dist = abs(int(min_row["X"]) - AISLE_X)
            max_dist = abs(int(max_row["X"]) - AISLE_X)
            use_min = min_dist < max_dist
        else:
            use_min = int(min_row["Y"]) < int(max_row["Y"])
        for row in members:
            row["rank_from_aisle"] = row["rank_from_min"] if use_min else row["rank_from_max"]


def build_2f_rows() -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    runs = [
        (2011, 2014, 3, 1, 1, 0),
        (2015, 2022, 8, 1, 1, 0),
        (2023, 2028, 13, 4, -1, 0),
        (2029, 2031, 5, 4, -1, 0),
        (2032, 2034, 3, 5, 1, 0),
        (2035, 2040, 8, 5, 1, 0),
        (2041, 2042, 16, 8, -1, 0),
        (2043, 2049, 14, 8, -1, 0),
        (2050, 2052, 5, 8, -1, 0),
        (2053, 2055, 3, 9, 1, 0),
        (2056, 2062, 8, 9, 1, 0),
        (2063, 2064, 15, 9, 1, 0),
        (2065, 2073, 16, 11, -1, 0),
        (2074, 2076, 5, 11, -1, 0),
        (2077, 2079, 3, 12, 1, 0),
        (2080, 2088, 8, 12, 1, 0),
        (2089, 2097, 16, 14, -1, 0),
        (2098, 2101, 6, 14, -1, 0),
        (2102, 2105, 3, 15, 1, 0),
        (2106, 2114, 8, 15, 1, 0),
        (2115, 2122, 15, 17, -1, 0),
        (2123, 2128, 6, 17, -1, 0),
        (2129, 2134, 1, 18, 1, 0),
        (2135, 2142, 8, 18, 1, 0),
        (2143, 2150, 15, 20, -1, 0),
        (2151, 2154, 6, 20, -1, 0),
        (2155, 2164, 6, 21, 1, 0),
        (2165, 2171, 16, 23, -1, 0),
        (2172, 2178, 10, 24, 1, 0),
        (2179, 2186, 17, 26, -1, 0),
        (2196, 2204, 36, 4, -1, 0),
        (2205, 2212, 26, 4, -1, 0),
        (2213, 2220, 19, 5, 1, 0),
        (2221, 2229, 28, 5, 1, 0),
        (2230, 2238, 36, 8, -1, 0),
        (2239, 2246, 26, 8, -1, 0),
        (2247, 2254, 19, 9, 1, 0),
        (2255, 2263, 28, 9, 1, 0),
        (2264, 2272, 36, 11, -1, 0),
        (2273, 2280, 26, 11, -1, 0),
        (2281, 2288, 19, 12, 1, 0),
        (2289, 2297, 28, 12, 1, 0),
        (2298, 2305, 35, 14, -1, 0),
        (2306, 2313, 26, 14, -1, 0),
        (2314, 2321, 19, 15, 1, 0),
        (2322, 2329, 28, 15, 1, 0),
        (2335, 2343, 36, 17, -1, 0),
        (2344, 2351, 26, 17, -1, 0),
    ]
    for run in runs:
        add_run(rows, "2F", *run)

    add_points(
        rows,
        "2F",
        machine_range(2001, 2010),
        [(1, y) for y in [14, 13, 12, 11, 10, 8, 7, 6, 5, 4]],
    )
    add_points(
        rows,
        "2F",
        machine_range(2187, 2195),
        [(38, y) for y in [3, 4, 5, 6, 8, 9, 10, 11, 12]],
    )
    add_points(
        rows,
        "2F",
        machine_range(2330, 2334),
        [(38, y) for y in [14, 15, 16, 18, 19]],
    )

    apply_store_sections(rows, "2F")
    validate_rows(rows, set(range(2001, 2352)))
    return sorted(rows, key=lambda row: int(row["machine_number"]))


def build_3f_rows() -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    runs = [
        (3001, 3016, 2, 1, 1, 0),
        (3017, 3030, 17, 4, -1, 0),
        (3031, 3042, 4, 5, 1, 0),
        (3043, 3057, 17, 8, -1, 0),
        (3058, 3072, 3, 9, 1, 0),
        (3073, 3087, 17, 12, -1, 0),
        (3088, 3102, 3, 13, 1, 0),
        (3103, 3116, 17, 16, -1, 0),
        (3117, 3130, 4, 17, 1, 0),
        (3131, 3143, 17, 20, -1, 0),
        (3144, 3155, 5, 21, 1, 0),
        (3156, 3167, 17, 24, -1, 0),
        (3168, 3180, 5, 25, 1, 0),
        (3181, 3190, 17, 28, -1, 0),
        (3191, 3208, 1, 33, 0, -1),
        (3209, 3217, 43, 4, 0, 1),
        (3218, 3233, 38, 4, -1, 0),
        (3234, 3249, 23, 5, 1, 0),
        (3250, 3264, 37, 8, -1, 0),
        (3265, 3280, 23, 9, 1, 0),
        (3281, 3294, 36, 12, -1, 0),
        (3295, 3309, 23, 13, 1, 0),
        (3310, 3324, 37, 16, -1, 0),
        (3325, 3340, 23, 17, 1, 0),
        (3341, 3345, 43, 16, 0, 1),
        (3346, 3362, 39, 20, -1, 0),
        (3400, 3401, 15, 30, -1, 0),
    ]
    for run in runs:
        add_run(rows, "3F", *run)

    expected = set(range(3001, 3363)) | {3400, 3401}
    apply_store_sections(rows, "3F")
    validate_rows(rows, expected)
    return sorted(rows, key=lambda row: int(row["machine_number"]))


def validate_rows(
    rows: list[dict[str, object]], expected: set[int]
) -> None:
    machine_numbers = [int(row["machine_number"]) for row in rows]
    coordinates = [
        (int(row["display_x"]), int(row["display_y"])) for row in rows
    ]

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


def write_rows(path: Path, rows: list[dict[str, object]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    floor_rows = {
        "2F": build_2f_rows(),
        "3F": build_3f_rows(),
    }
    for floor, rows in floor_rows.items():
        path = OUTPUT_PATHS[floor]
        write_rows(path, rows)
        print(f"Wrote {len(rows)} machines to {path}")


if __name__ == "__main__":
    main()
