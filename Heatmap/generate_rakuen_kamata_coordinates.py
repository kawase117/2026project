"""Generate Rakuen Kamata floor coordinates from physical machine runs."""

from __future__ import annotations

import csv
from pathlib import Path


HALL_NAME = "楽園蒲田店"
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


def add_run(
    rows: list[dict[str, object]],
    floor: str,
    machines: list[int],
    start_x: int,
    start_y: int,
    step_x: int,
    step_y: int,
    section: tuple[int, int] | None = None,
) -> None:
    """Append one physical row/column of machines.

    ``section`` overrides the auto-computed (min, max) when a single
    numeric section is split across multiple runs (e.g. a U-shaped
    island made of two columns plus a connecting machine).
    """

    if section is None:
        section_min = min(machines)
        section_max = max(machines)
    else:
        section_min, section_max = section
    section_label = f"{section_min}-{section_max}"

    for index, machine_number in enumerate(machines):
        x = start_x + index * step_x
        y = start_y + index * step_y
        rows.append(
            {
                "hall_name": HALL_NAME,
                "floor": floor,
                "machine_number": machine_number,
                "X": x,
                "Y": y,
                "display_x": x,
                "display_y": y,
                "section": section_label,
                "section_min": section_min,
                "section_max": section_max,
                "rank_from_min": machine_number - section_min + 1,
                "rank_from_max": section_max - machine_number + 1,
            }
        )


def validate_rows(rows: list[dict[str, object]], expected: set[int]) -> None:
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


def build_rows_honkan_3f() -> list[dict[str, object]]:
    floor = "本館3F"
    rows: list[dict[str, object]] = []

    # ===== 外周コの字フレーム（3107-3120, 3164-3185） =====
    # 左縦列 x1：3116(r2,最上段) → 3107(r12,最下段)。3113と3112の間に通路(r6)
    add_run(rows, floor, [3116, 3115, 3114, 3113], 1, 2, 0, 1)
    add_run(rows, floor, [3112, 3111, 3110, 3109, 3108, 3107], 1, 7, 0, 1)

    # 上辺左 x2-5 (r1)：3117-3120（銭形5）
    add_run(rows, floor, list(range(3117, 3121)), 2, 1, 1, 0)

    # 上辺右 x7-16 (r1)：3164-3173（新ハナビ〜ビンビン）
    add_run(rows, floor, list(range(3164, 3174)), 7, 1, 1, 0)

    # 右縦列 x17：3174(r2)-3179(r7), 通路(r8), 3180(r9)-3185(r14)
    add_run(rows, floor, list(range(3174, 3180)), 17, 2, 0, 1, section=(3174, 3185))
    add_run(rows, floor, list(range(3180, 3186)), 17, 9, 0, 1, section=(3174, 3185))

    # ===== 内側島A：3121-3141（星矢/ラブ嬢3） 3120とその右空白の真下 =====
    # 左サブ列 x5：3121(r4)→3131(r14)、右サブ列 x6：3141(r4)→3132(r13)
    add_run(rows, floor, list(range(3121, 3132)), 5, 4, 0, 1, section=(3121, 3141))
    add_run(rows, floor, list(range(3141, 3131, -1)), 6, 4, 0, 1, section=(3121, 3141))

    # ===== 内側島B：3142-3163（ゾンサガ〜シンフォ勇気） 3168-3169の真下 =====
    # 左サブ列 x11：3142(r4)→3152(r14)、右サブ列 x12：3163(r4)→3153(r14)
    add_run(rows, floor, list(range(3142, 3153)), 11, 4, 0, 1, section=(3142, 3163))
    add_run(rows, floor, list(range(3163, 3152, -1)), 12, 4, 0, 1, section=(3142, 3163))

    # ===== 中段ブロック（3186-3249） 左端3238が3119真下(x4)、右端3186が島B右列真下(x12) =====
    # 左群：3238-3249(x4,12台) / 3237-3226(x5,12台)  ※3238が3119の真下
    add_run(rows, floor, list(range(3238, 3250)), 4, 16, 0, 1, section=(3226, 3249))
    add_run(rows, floor, list(range(3237, 3225, -1)), 5, 16, 0, 1, section=(3226, 3249))
    # 中群：3213-3225(x8,13台) / 3212-3200(x9,13台)
    add_run(rows, floor, list(range(3213, 3226)), 8, 16, 0, 1, section=(3200, 3225))
    add_run(rows, floor, list(range(3212, 3199, -1)), 9, 16, 0, 1, section=(3200, 3225))
    # 右群（単列）：3186-3199(x12,14台) 3163-3153の真下
    add_run(rows, floor, list(range(3186, 3200)), 12, 16, 0, 1, section=(3186, 3199))

    # ===== 末尾ブロック（3250-3266） =====
    # 上段：3257-3255(x10,3台) + 3254(x9)を3200の真下に配置
    # 上段：3200の真下(x9)に3254、左へ3255→3256→3257
    add_run(rows, floor, [3254, 3255, 3256, 3257], 9, 31, -1, 0, section=(3250, 3266))
    # 下段：3200の真下(x9)に3253、左へ3252→3251→3250
    add_run(rows, floor, [3253, 3252, 3251, 3250], 9, 32, -1, 0, section=(3250, 3266))
    # 最下段：3266-3263(x10-13,4台) + 3262(x9) + 3261-3258(x5-8,4台)
    add_run(rows, floor, list(range(3266, 3262, -1)), 10, 34, 1, 0, section=(3250, 3266))
    add_run(rows, floor, [3262], 9, 34, 0, 0, section=(3250, 3266))
    add_run(rows, floor, list(range(3261, 3257, -1)), 5, 34, 1, 0, section=(3250, 3266))

    expected = set(range(3107, 3267))
    validate_rows(rows, expected)
    return sorted(rows, key=lambda row: int(row["machine_number"]))


def build_rows_honkan_2f() -> list[dict[str, object]]:
    floor = "本館2F"
    rows: list[dict[str, object]] = []

    # ===== 上辺横列（row 1） =====
    add_run(rows, floor, [2111, 2112, 2113], 2, 1, 1, 0)            # スタァライト
    add_run(rows, floor, list(range(2163, 2171)), 6, 1, 1, 0)      # クレア/不二子/ハーレム
    add_run(rows, floor, [2171, 2172], 16, 1, 1, 0)               # エヴァBT

    # ===== 左縦列 x1：かぐや(r2-6) 通路 Lカバネリ(r9-14) =====
    add_run(rows, floor, [2110, 2109, 2108, 2107, 2106], 1, 2, 0, 1, section=(2100, 2110))
    add_run(rows, floor, [2105, 2104, 2103, 2102, 2101, 2100], 1, 9, 0, 1, section=(2100, 2110))

    # ===== 右縦列 x18：シェイク/アレックス/サンダー(r2-13) =====
    add_run(rows, floor, list(range(2173, 2185)), 18, 2, 0, 1, section=(2173, 2184))

    # ===== 中左島（x8-9, r4-15）いせかる/Lカバネリ + プリナナ/マギレコ =====
    add_run(rows, floor, list(range(2114, 2126)), 8, 4, 0, 1, section=(2114, 2140))   # 左列 2114→2125
    add_run(rows, floor, list(range(2140, 2128, -1)), 9, 4, 0, 1, section=(2114, 2140))  # 右列 2140→2129

    # ===== 右島（x12-13, r4-14）SAO/アズレン/攻殻 + スロット/Lハナビ =====
    add_run(rows, floor, list(range(2141, 2152)), 12, 4, 0, 1, section=(2141, 2162))   # 左列 2141→2151
    add_run(rows, floor, list(range(2162, 2151, -1)), 13, 4, 0, 1, section=(2141, 2162))  # 右列 2162→2152

    # ===== 化物語 三角形：2127(x8,上) / 2126(x7) 2128(x9)（下）。2127は2125の真下=x8 =====
    add_run(rows, floor, [2127], 8, 18, 0, 0, section=(2126, 2128))
    add_run(rows, floor, [2126], 7, 19, 0, 0, section=(2126, 2128))
    add_run(rows, floor, [2128], 9, 19, 0, 0, section=(2126, 2128))

    # ===== 下中島（x8-9, r21-33）乙女4/ガルパン + SBJ/防振り。2220は2127の真下=x8 =====
    add_run(rows, floor, list(range(2210, 2223)), 8, 21, 0, 1, section=(2197, 2222))   # 左列 2210→2222
    add_run(rows, floor, list(range(2209, 2196, -1)), 9, 21, 0, 1, section=(2197, 2222))  # 右列 2209→2197

    # ===== 下左島（x4-5, r24-32）化物語 + ヨルムン/無職転生 =====
    add_run(rows, floor, list(range(2232, 2241)), 4, 24, 0, 1, section=(2223, 2240))   # 左列 2232→2240
    add_run(rows, floor, list(range(2231, 2222, -1)), 5, 24, 0, 1, section=(2223, 2240))  # 右列 2231→2223

    # ===== スマスロ単列（x12, r21-32） =====
    add_run(rows, floor, list(range(2185, 2197)), 12, 21, 0, 1, section=(2185, 2196))

    expected = set(range(2100, 2241))
    validate_rows(rows, expected)
    return sorted(rows, key=lambda row: int(row["machine_number"]))


def build_rows_honkan_1f() -> list[dict[str, object]]:
    floor = "本館1F"
    rows: list[dict[str, object]] = []

    # ===== 上辺横列（row 1）ハッピー =====
    add_run(rows, floor, [1152, 1153, 1154, 1155], 2, 1, 1, 0, section=(1152, 1155))

    # ===== 左縦列 x1：ハッピー/ファンキー(r2-8) 通路 ファンキー(r11-16) 通路 ガールズ(r18-21) =====
    add_run(rows, floor, list(range(1151, 1144, -1)), 1, 2, 0, 1, section=(1135, 1151))   # 1151→1145
    add_run(rows, floor, list(range(1144, 1138, -1)), 1, 11, 0, 1, section=(1135, 1151))  # 1144→1139
    add_run(rows, floor, list(range(1138, 1134, -1)), 1, 18, 0, 1, section=(1135, 1151))  # 1138→1135

    # ===== 島1（x4-5, r4-17）ゴージャグ + ネオアイム =====
    add_run(rows, floor, list(range(1156, 1170)), 4, 4, 0, 1, section=(1156, 1183))   # 左列 1156→1169
    add_run(rows, floor, list(range(1183, 1169, -1)), 5, 4, 0, 1, section=(1156, 1183))  # 右列 1183→1170

    # ===== 島2（x7-8）ネオアイム(左,r4-16) + マイジャグ(右,r4-15) =====
    add_run(rows, floor, list(range(1184, 1197)), 7, 4, 0, 1, section=(1184, 1208))   # 左列 1184→1196
    add_run(rows, floor, list(range(1208, 1196, -1)), 8, 4, 0, 1, section=(1184, 1208))  # 右列 1208→1197

    # ===== マイジャグ単列（x10, r6-13） =====
    add_run(rows, floor, list(range(1209, 1217)), 10, 6, 0, 1, section=(1209, 1216))

    # ===== 下：DUO2/ドキ島（x4-5, r20-24） =====
    add_run(rows, floor, list(range(1106, 1111)), 4, 20, 0, 1, section=(1106, 1115))   # DUO2 1106→1110
    add_run(rows, floor, list(range(1111, 1116)), 5, 20, 0, 1, section=(1106, 1115))   # ドキ 1111→1115

    # ===== ドキ単列（x7, r20-24） =====
    add_run(rows, floor, list(range(1134, 1129, -1)), 7, 20, 0, 1, section=(1130, 1134))

    # ===== 下：キンハナ島（x4-5, r26-31） =====
    add_run(rows, floor, list(range(1100, 1106)), 4, 26, 0, 1, section=(1100, 1121))   # 左列 1100→1105
    add_run(rows, floor, list(range(1116, 1122)), 5, 26, 0, 1, section=(1100, 1121))   # 右列 1116→1121

    # ===== ニューキン単列（x7, r26-33） =====
    add_run(rows, floor, list(range(1129, 1121, -1)), 7, 26, 0, 1, section=(1122, 1129))

    expected = set(range(1100, 1217))
    validate_rows(rows, expected)
    return sorted(rows, key=lambda row: int(row["machine_number"]))


def build_rows_shinkan_1f() -> list[dict[str, object]]:
    floor = "新館1F"
    rows: list[dict[str, object]] = []

    # ===== 上辺横列（row 1, x1-11）真打吉宗(1006-1010) + L北斗(1011-1016) =====
    add_run(rows, floor, list(range(1006, 1017)), 1, 1, 1, 0)

    # ===== 左縦列 x1：GOD(1005→1000) r4-9。1006の真下 =====
    add_run(rows, floor, list(range(1005, 999, -1)), 1, 4, 0, 1, section=(1000, 1005))

    # ===== 島A（x3-4, r3-12）GOD(1017→1026) + 転生(1036→1027) =====
    add_run(rows, floor, list(range(1017, 1027)), 3, 3, 0, 1, section=(1017, 1036))
    add_run(rows, floor, list(range(1036, 1026, -1)), 4, 3, 0, 1, section=(1017, 1036))

    # ===== 島B（x6-7, r3-12）転生(1037→1046) + 転生(1056→1047) =====
    add_run(rows, floor, list(range(1037, 1047)), 6, 3, 0, 1, section=(1037, 1056))
    add_run(rows, floor, list(range(1056, 1046, -1)), 7, 3, 0, 1, section=(1037, 1056))

    # ===== 右小列（x9, r5-7）転生(1057-1059) =====
    add_run(rows, floor, [1057, 1058, 1059], 9, 5, 0, 1, section=(1057, 1059))

    expected = set(range(1000, 1060))
    validate_rows(rows, expected)
    return sorted(rows, key=lambda row: int(row["machine_number"]))


def build_rows_shinkan_2f() -> list[dict[str, object]]:
    floor = "新館2F"
    rows: list[dict[str, object]] = []

    # ===== 上辺横列（row 1, x2-14）モンハン(2008-2013) + 鉄拳6(2014-2016) + GE(2017-2020) =====
    add_run(rows, floor, list(range(2008, 2021)), 2, 1, 1, 0)

    # ===== 左縦列 x1：鏡(2007→2004) r2-5 / 通路 / いざ番長(2003→2000) r9-12 =====
    add_run(rows, floor, list(range(2007, 2003, -1)), 1, 2, 0, 1, section=(2004, 2007))
    add_run(rows, floor, list(range(2003, 1999, -1)), 1, 9, 0, 1, section=(2000, 2003))

    # ===== 島A（x4-5, r3-14）絆2天膳/東リベ(2021→2032) + 新鬼3/ヴヴヴ2(2044→2033) =====
    add_run(rows, floor, list(range(2021, 2033)), 4, 3, 0, 1, section=(2021, 2044))
    add_run(rows, floor, list(range(2044, 2032, -1)), 5, 3, 0, 1, section=(2021, 2044))

    # ===== 島B（x8-9, r3-15）UC2/炎炎2(2045→2057) + バイオ5/刃3(2070→2058) =====
    add_run(rows, floor, list(range(2045, 2058)), 8, 3, 0, 1, section=(2045, 2070))
    add_run(rows, floor, list(range(2070, 2057, -1)), 9, 3, 0, 1, section=(2045, 2070))

    # ===== モンキー5単列（x12, r5-9）2071-2075 =====
    add_run(rows, floor, list(range(2071, 2076)), 12, 5, 0, 1, section=(2071, 2075))

    # ===== 喰種 L字（2076-2090） =====
    # 上：2076(x13) 2077(x14) r12
    add_run(rows, floor, [2076], 13, 12, 0, 0, section=(2076, 2090))
    # 右縦列：x14 を 2077→2082（r12-17）
    add_run(rows, floor, list(range(2077, 2083)), 14, 12, 0, 1, section=(2076, 2090))
    # 最下段横列：r18 を 2083(x13)→2090(x6)、左へ広がる
    add_run(rows, floor, list(range(2083, 2091)), 13, 18, -1, 0, section=(2076, 2090))

    expected = set(range(2000, 2091))
    validate_rows(rows, expected)
    return sorted(rows, key=lambda row: int(row["machine_number"]))


def write_csv(rows: list[dict[str, object]], output_path: Path) -> None:
    with output_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)
    print(f"Wrote {len(rows)} machines to {output_path}")


def main() -> None:
    here = Path(__file__).parent
    write_csv(build_rows_honkan_3f(), here / "honkan3F_floor_coordinates_rakuen.csv")
    write_csv(build_rows_honkan_2f(), here / "honkan2F_floor_coordinates_rakuen.csv")
    write_csv(build_rows_honkan_1f(), here / "honkan1F_floor_coordinates_rakuen.csv")
    write_csv(build_rows_shinkan_1f(), here / "shinkan1F_floor_coordinates_rakuen.csv")
    write_csv(build_rows_shinkan_2f(), here / "shinkan2F_floor_coordinates_rakuen.csv")


if __name__ == "__main__":
    main()
