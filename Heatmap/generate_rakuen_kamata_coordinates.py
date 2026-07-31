"""Generate Rakuen Kamata floor coordinates from physical machine runs.

Layout source: 楽園蒲田 公式フロアマップ 2026/07/13 (本館1F/2F/3F・新館1F/2F)。
2026-07-06 にホールが大規模な台番号再割り当て＋増台を実施したため、それ以前の
座標定義は無効。主な変更点:

* 増台 +20: 本館2F 2241-2242(化物語列延長) / 2243-2250(新島) / 2251-2258(最下段列)、
  本館3F 3267-3268(最下段列の左端)
* 撤去 -2: 新館2F 2078, 2079（喰種L字の右縦列上部）。欠番として扱う
* 本館2F/3F は島構成をほぼ据え置いたまま台番号が +2 前後シフト
* 本館1F は台番号の変更なし。ただし旧定義は下部2島の左列が上下反転しており、
  かつ通路で分断された同一島を別セクション扱いしていたため本版で是正した
  （1100-1121 の U字島、1122-1134 の単列。ホール内の他フロアと同じ規約に統一）

台数: 本館1F 117 / 本館2F 159 / 本館3F 162 / 新館1F 60 / 新館2F 89 = 587
"""

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
    coordinates = [(int(row["display_x"]), int(row["display_y"])) for row in rows]

    if set(machine_numbers) != expected:
        missing = sorted(expected - set(machine_numbers))
        extra = sorted(set(machine_numbers) - expected)
        raise ValueError(f"Machine coverage mismatch: missing={missing}, extra={extra}")
    if len(machine_numbers) != len(set(machine_numbers)):
        raise ValueError("Duplicate machine numbers found")
    if len(coordinates) != len(set(coordinates)):
        duplicates = sorted(coordinate for coordinate in set(coordinates) if coordinates.count(coordinate) > 1)
        raise ValueError(f"Duplicate display coordinates found: {duplicates}")


def build_rows_honkan_3f() -> list[dict[str, object]]:
    floor = "本館3F"
    rows: list[dict[str, object]] = []

    # ===== 外周コの字フレーム =====
    # 左縦列 x1：3116(r2,最上段) → 3107(r12)。3113と3112の間に通路(r6)
    # 通路で分断された2つの独立列。それぞれ別セクション（3113-3116 / 3107-3112）
    add_run(rows, floor, [3116, 3115, 3114, 3113], 1, 2, 0, 1)
    add_run(rows, floor, [3112, 3111, 3110, 3109, 3108, 3107], 1, 7, 0, 1)

    # 上辺左 x2-5 (r1)：3117-3120（SAO）
    add_run(rows, floor, list(range(3117, 3121)), 2, 1, 1, 0)

    # 上辺右 x7-16 (r1)：3166-3175（キンハナ×8 → ニューキン×2）
    add_run(rows, floor, list(range(3166, 3176)), 7, 1, 1, 0)

    # 右縦列 x17：3176(r2)-3181(r7), 通路(r8), 3182(r9)-3187(r14)
    # 通路で分断された2つの独立列。それぞれ別セクション（3176-3181 / 3182-3187）
    add_run(rows, floor, list(range(3176, 3182)), 17, 2, 0, 1)
    add_run(rows, floor, list(range(3182, 3188)), 17, 9, 0, 1)

    # ===== 内側島A：3121-3143（モンキー5 / サンダー・不二子ほか） =====
    # 左サブ列 x5：3121(r4)→3132(r15)、右サブ列 x6：3143(r4)→3133(r14)
    add_run(rows, floor, list(range(3121, 3133)), 5, 4, 0, 1, section=(3121, 3143))
    add_run(rows, floor, list(range(3143, 3132, -1)), 6, 4, 0, 1, section=(3121, 3143))

    # ===== 内側島B：3144-3165（GALFY・Lハナビ / 沖ドキB） =====
    # 左サブ列 x11：3144(r4)→3154(r14)、右サブ列 x12：3165(r4)→3155(r14)
    add_run(rows, floor, list(range(3144, 3155)), 11, 4, 0, 1, section=(3144, 3165))
    add_run(rows, floor, list(range(3165, 3154, -1)), 12, 4, 0, 1, section=(3144, 3165))

    # ===== 中段ブロック =====
    # 左群：3240-3251(x4,12台) / 3239-3228(x5,12台)
    add_run(rows, floor, list(range(3240, 3252)), 4, 16, 0, 1, section=(3228, 3251))
    add_run(rows, floor, list(range(3239, 3227, -1)), 5, 16, 0, 1, section=(3228, 3251))
    # 中群：3215-3227(x8,13台) / 3214-3202(x9,13台)
    add_run(rows, floor, list(range(3215, 3228)), 8, 16, 0, 1, section=(3202, 3227))
    add_run(rows, floor, list(range(3214, 3201, -1)), 9, 16, 0, 1, section=(3202, 3227))
    # 右群（単列）：3188-3201(x12,14台)
    add_run(rows, floor, list(range(3188, 3202)), 12, 16, 0, 1, section=(3188, 3201))

    # ===== 末尾ブロック =====
    # 上段(r31)：3252(x6)→3255(x9) / 下段(r32)：3256(x9)→3259(x6) のS字
    add_run(rows, floor, [3252, 3253, 3254, 3255], 6, 31, 1, 0, section=(3252, 3259))
    add_run(rows, floor, [3256, 3257, 3258, 3259], 9, 32, -1, 0, section=(3252, 3259))
    # 最下段(r34)：3260(x13)→3268(x5) 右から左へ
    add_run(rows, floor, list(range(3260, 3269)), 13, 34, -1, 0, section=(3260, 3268))

    expected = set(range(3107, 3269))
    validate_rows(rows, expected)
    return sorted(rows, key=lambda row: int(row["machine_number"]))


def build_rows_honkan_2f() -> list[dict[str, object]]:
    floor = "本館2F"
    rows: list[dict[str, object]] = []

    # ===== 上辺横列（row 1） =====
    add_run(rows, floor, [2111, 2112, 2113], 2, 1, 1, 0)  # スタァライト
    add_run(rows, floor, list(range(2165, 2173)), 6, 1, 1, 0)  # いせかる/クレア/シェイク/ハーレムA
    add_run(rows, floor, [2173, 2174], 16, 1, 1, 0)  # エヴァBT

    # ===== 左縦列 x1：かぐや(r2-6) 通路 Lカバネリ(r9-14) =====
    # 通路で分断された2つの独立列。それぞれ別セクション（2106-2110 / 2100-2105）
    add_run(rows, floor, [2110, 2109, 2108, 2107, 2106], 1, 2, 0, 1)
    add_run(rows, floor, [2105, 2104, 2103, 2102, 2101, 2100], 1, 9, 0, 1)

    # ===== 右縦列 x18：ケロット5〜ななつま(r2-13) =====
    add_run(rows, floor, list(range(2175, 2187)), 18, 2, 0, 1, section=(2175, 2186))

    # ===== 中左島（x8-9, r4-15）Lカバネリ + プリナナ/マギレコ =====
    add_run(rows, floor, list(range(2114, 2126)), 8, 4, 0, 1, section=(2114, 2140))  # 左列 2114→2125
    add_run(rows, floor, list(range(2140, 2128, -1)), 9, 4, 0, 1, section=(2114, 2140))  # 右列 2140→2129

    # ===== 右島（x12-13, r4-15）SBJ/戦国コレ + ローティス/ウルトラほか =====
    add_run(rows, floor, list(range(2141, 2153)), 12, 4, 0, 1, section=(2141, 2164))  # 左列 2141→2152
    add_run(rows, floor, list(range(2164, 2152, -1)), 13, 4, 0, 1, section=(2141, 2164))  # 右列 2164→2153

    # ===== 攻殻 三角形：2127(x8,上) / 2126(x7) 2128(x9)（下） =====
    add_run(rows, floor, [2127], 8, 18, 0, 0, section=(2126, 2128))
    add_run(rows, floor, [2126], 7, 19, 0, 0, section=(2126, 2128))
    add_run(rows, floor, [2128], 9, 19, 0, 0, section=(2126, 2128))

    # ===== 下中島（x8-9, r21-33）乙女5 + シャーマン/リオ2 =====
    add_run(rows, floor, list(range(2212, 2225)), 8, 21, 0, 1, section=(2199, 2224))  # 左列 2212→2224
    add_run(rows, floor, list(range(2211, 2198, -1)), 9, 21, 0, 1, section=(2199, 2224))  # 右列 2211→2199

    # ===== 下左島（x4-5, r24-32）化物語 + 乙女5 =====
    add_run(rows, floor, list(range(2234, 2243)), 4, 24, 0, 1, section=(2225, 2242))  # 左列 2234→2242
    add_run(rows, floor, list(range(2233, 2224, -1)), 5, 24, 0, 1, section=(2225, 2242))  # 右列 2233→2225

    # ===== バディゴル/無職転生/防振り単列（x12, r21-32） =====
    add_run(rows, floor, list(range(2187, 2199)), 12, 21, 0, 1, section=(2187, 2198))

    # ===== 【増台】ディスクUR/うみねこ島（x5-8, r35-36） =====
    # 下段(r36)：2243(x5)→2246(x8) / 上段(r35)：2247(x8)→2250(x5) のS字
    add_run(rows, floor, [2243, 2244, 2245, 2246], 5, 36, 1, 0, section=(2243, 2250))
    add_run(rows, floor, [2247, 2248, 2249, 2250], 8, 35, -1, 0, section=(2243, 2250))

    # ===== 【増台】ディスクUR最下段列（x4-11, r38）：2251(x11)→2258(x4) =====
    add_run(rows, floor, list(range(2251, 2259)), 11, 38, -1, 0, section=(2251, 2258))

    expected = set(range(2100, 2259))
    validate_rows(rows, expected)
    return sorted(rows, key=lambda row: int(row["machine_number"]))


def build_rows_honkan_1f() -> list[dict[str, object]]:
    floor = "本館1F"
    rows: list[dict[str, object]] = []

    # ===== 上辺横列（row 1）ハッピー =====
    add_run(rows, floor, [1152, 1153, 1154, 1155], 2, 1, 1, 0, section=(1152, 1155))

    # ===== 左縦列 x1：ハッピー/ファンキー(r2-8) 通路 ファンキー(r11-16) 通路 ガールズ(r18-21) =====
    # 通路で分断された3つの独立列。それぞれ別セクション（1145-1151 / 1139-1144 / 1135-1138）
    add_run(rows, floor, list(range(1151, 1144, -1)), 1, 2, 0, 1)  # 1151→1145
    add_run(rows, floor, list(range(1144, 1138, -1)), 1, 11, 0, 1)  # 1144→1139
    add_run(rows, floor, list(range(1138, 1134, -1)), 1, 18, 0, 1)  # 1138→1135

    # ===== 島1（x4-5, r4-17）ゴージャグ + ネオアイム =====
    add_run(rows, floor, list(range(1156, 1170)), 4, 4, 0, 1, section=(1156, 1183))  # 左列 1156→1169
    add_run(rows, floor, list(range(1183, 1169, -1)), 5, 4, 0, 1, section=(1156, 1183))  # 右列 1183→1170

    # ===== 島2（x7-8）ネオアイム(左,r4-16) + マイジャグ(右,r4-15) =====
    add_run(rows, floor, list(range(1184, 1197)), 7, 4, 0, 1, section=(1184, 1208))  # 左列 1184→1196
    add_run(rows, floor, list(range(1208, 1196, -1)), 8, 4, 0, 1, section=(1184, 1208))  # 右列 1208→1197

    # ===== マイジャグ単列（x10, r6-13） =====
    add_run(rows, floor, list(range(1209, 1217)), 10, 6, 0, 1, section=(1209, 1216))

    # ===== 下部U字島 1100-1121（全台ネオアイム、r25の通路で上下に分断） =====
    # 左列 x4：1110(r20)→1106(r24) / 通路 / 1105(r26)→1100(r31)
    add_run(rows, floor, list(range(1110, 1105, -1)), 4, 20, 0, 1, section=(1100, 1121))
    add_run(rows, floor, list(range(1105, 1099, -1)), 4, 26, 0, 1, section=(1100, 1121))
    # 右列 x5：1111(r20)→1115(r24) / 通路 / 1116(r26)→1121(r31)
    add_run(rows, floor, list(range(1111, 1116)), 5, 20, 0, 1, section=(1100, 1121))
    add_run(rows, floor, list(range(1116, 1122)), 5, 26, 0, 1, section=(1100, 1121))

    # ===== 下部単列 1122-1134（x7、通路で上下に分断） =====
    # 通路で分断された2つの独立列。それぞれ別セクション（1130-1134 / 1122-1129）
    add_run(rows, floor, list(range(1134, 1129, -1)), 7, 20, 0, 1)
    add_run(rows, floor, list(range(1129, 1121, -1)), 7, 26, 0, 1)

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

    # ===== 上辺横列（row 1, x2-14）いざ番長(2008)〜アニマル(2020) =====
    add_run(rows, floor, list(range(2008, 2021)), 2, 1, 1, 0)

    # ===== 左縦列 x1：バイオ系(2007→2004) r2-5 / 通路 / 鏡(2003→2000) r9-12 =====
    add_run(rows, floor, list(range(2007, 2003, -1)), 1, 2, 0, 1, section=(2004, 2007))
    add_run(rows, floor, list(range(2003, 1999, -1)), 1, 9, 0, 1, section=(2000, 2003))

    # ===== 島A（x4-5, r3-14）天膳/東リベ/GE(2021→2032) + 新鬼3/ヴヴヴ2(2044→2033) =====
    add_run(rows, floor, list(range(2021, 2033)), 4, 3, 0, 1, section=(2021, 2044))
    add_run(rows, floor, list(range(2044, 2032, -1)), 5, 3, 0, 1, section=(2021, 2044))

    # ===== 島B（x8-9, r3-15）ライズ/炎炎2(2045→2057) + からくり2(2070→2058) =====
    add_run(rows, floor, list(range(2045, 2058)), 8, 3, 0, 1, section=(2045, 2070))
    add_run(rows, floor, list(range(2070, 2057, -1)), 9, 3, 0, 1, section=(2045, 2070))

    # ===== 喰種単列（x12, r5-9）2071-2075 =====
    add_run(rows, floor, list(range(2071, 2076)), 12, 5, 0, 1, section=(2071, 2075))

    # ===== 喰種 L字（2076-2090、2078/2079は撤去済みで欠番） =====
    # 上：2076(x13) 2077(x14) r12
    add_run(rows, floor, [2076], 13, 12, 0, 0, section=(2076, 2090))
    add_run(rows, floor, [2077], 14, 12, 0, 0, section=(2076, 2090))
    # 右縦列：x14 を 2080→2082（r14-16）※2078,2079 が抜けた分の空きが r13
    add_run(rows, floor, list(range(2080, 2083)), 14, 14, 0, 1, section=(2076, 2090))
    # 最下段横列：r18 を 2083(x13)→2090(x6)、左へ広がる
    add_run(rows, floor, list(range(2083, 2091)), 13, 18, -1, 0, section=(2076, 2090))

    expected = set(range(2000, 2091)) - {2078, 2079}
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
