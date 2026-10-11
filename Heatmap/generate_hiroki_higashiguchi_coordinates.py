"""Generate ヒロキ東口店 floor coordinates from the official floor map image.

Layout source: kawasakislot 2026-10-10 22:16 のツイート添付の「ヒロキ蒲田東口 フロアマップ 2026/10/09」
(2F, 279台)。画像: scraper/twitter_monitor/images/kawasakislot/2108909412656320890_3.jpg

台番号は連番ではない(欠番多数)。各「列」を物理的に並んだ1本の台列(section)として扱う。
島は背中合わせの2列で、左列は台番号が上から昇順、右列は上から降順に並ぶ。
rank_from_min/max は kamata1 と同じく台番号順(列内で最小番号=1)で振る。
座標: X=列番号(左から)、Y=画像上の段(行)番号。目安であり、角番の判定には使わない。
rank_from_aisle は画像から取れないので出力しない(NULL)。

使い方:
    venv\\Scripts\\python.exe Heatmap\\generate_hiroki_higashiguchi_coordinates.py
"""

from __future__ import annotations

import csv
import sqlite3
from pathlib import Path

HALL_NAME = "ヒロキ東口店"
FLOOR = "2F"
ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "Heatmap" / "hiroki_higashiguchi_floor_coordinates.csv"

# (X, Y開始, 台番号を画像の上から下へ並べた順)。横列(最下段)は左から右。
# 3ブロック(上・中・下)+最下段の横列。Y開始はブロックごとの先頭段の目安。
COLUMNS: list[tuple[int, int, list[int]]] = [
    # --- 上ブロック ---
    (1, 0, [2505, 2503, 2502, 2501, 2500, 2388, 2387, 2386]),
    (3, 0, [2371, 2372, 2373, 2375, 2376, 2377, 2378, 2380, 2381, 2382, 2383, 2385]),
    (4, 0, [2370, 2368, 2367, 2366, 2365, 2363, 2362, 2361, 2360, 2358, 2357, 2356]),
    (6, 0, [2331, 2332, 2333, 2335, 2336, 2337, 2338, 2350, 2351, 2352, 2353, 2355]),
    (7, 0, [2330, 2328, 2327, 2326, 2325, 2323, 2322, 2321, 2320, 2318, 2317, 2316]),
    (9, 3, [2305, 2306, 2307, 2308, 2310, 2311, 2312, 2313, 2315]),
    (10, 3, [2303, 2302, 2301, 2300, 2288, 2287, 2286, 2285, 2283]),
    (12, 3, [2276, 2277, 2278, 2280, 2281, 2282]),
    (12, 12, [2261, 2262, 2263, 2265, 2266, 2267, 2268, 2270, 2271, 2272, 2273, 2275]),
    # --- 中ブロック ---
    (1, 14, [2150, 2138, 2137, 2136, 2135, 2133, 2132]),
    (3, 14, [2151, 2152, 2153, 2155, 2156, 2157, 2158, 2160, 2161, 2162, 2163, 2165]),
    (4, 14, [2180, 2178, 2177, 2176, 2175, 2173, 2172, 2171, 2170, 2168, 2167, 2166]),
    (6, 14, [2181, 2182, 2183, 2185, 2186, 2187, 2188, 2200, 2201, 2202, 2203, 2205]),
    (7, 14, [2220, 2218, 2217, 2216, 2215, 2213, 2212, 2211, 2210, 2208, 2207, 2206]),
    (9, 14, [2221, 2222, 2223, 2225, 2226, 2227, 2228, 2230, 2231, 2232, 2233, 2235]),
    (10, 14, [2260, 2258, 2257, 2256, 2255, 2253, 2252, 2251, 2250, 2238, 2237, 2236]),
    # --- 下ブロック ---
    (1, 27, [2600, 2588, 2587, 2586, 2131, 2130, 2128, 2127, 2126, 2125, 2123, 2122, 2121, 2120, 2118]),
    (3, 28, [2106, 2107, 2108, 2110, 2111, 2112, 2113, 2115, 2116, 2117]),
    (4, 28, [2105, 2103, 2102, 2101, 2100, 2088, 2087, 2086, 2085, 2083]),
    (6, 28, [2068, 2070, 2071, 2072, 2073, 2075, 2076, 2077, 2078, 2080, 2081, 2082]),
    (7, 28, [2067, 2066, 2065, 2063, 2062, 2061, 2060, 2058, 2057, 2056, 2055, 2053]),
    (9, 28, [2028, 2030, 2031, 2032, 2033, 2035, 2036, 2037, 2038, 2050, 2051, 2052]),
    (10, 28, [2027, 2026, 2025, 2023, 2022, 2021, 2020, 2018, 2017, 2016, 2015, 2013]),
    (12, 28, [2001, 2002, 2003, 2005, 2006, 2007, 2008, 2010, 2011, 2012]),
]
# 最下段の横列(左から右)。X=1..15, Y=41
BOTTOM_ROW = [2585, 2583, 2582, 2581, 2580, 2578, 2577, 2576, 2575, 2573, 2572, 2571, 2570, 2568, 2567]

FIELDNAMES = [
    "hall_name",
    "floor",
    "machine_number",
    "X",
    "Y",
    "display_y",
    "section",
    "section_min",
    "section_max",
    "rank_from_min",
    "rank_from_max",
]


def section_name(numbers: list[int]) -> str:
    """連番区間を '+' で連結した名前(蒲田1と同じ規約。台数は件数で数えること)。"""
    ns = sorted(numbers)
    runs: list[list[int]] = [[ns[0], ns[0]]]
    for n in ns[1:]:
        if n == runs[-1][1] + 1:
            runs[-1][1] = n
        else:
            runs.append([n, n])
    return "+".join(str(a) if a == b else f"{a}-{b}" for a, b in runs)


def build_rows() -> list[dict]:
    lines: list[tuple[list[tuple[int, int, int]], list[int]]] = []
    for x, y0, nums in COLUMNS:
        lines.append(([(n, x, y0 + i) for i, n in enumerate(nums)], nums))
    lines.append(([(n, 1 + i, 41) for i, n in enumerate(BOTTOM_ROW)], BOTTOM_ROW))

    rows: list[dict] = []
    for cells, nums in lines:
        ordered = sorted(nums)
        name = section_name(nums)
        total = len(nums)
        for n, x, y in cells:
            r = ordered.index(n) + 1
            rows.append(
                {
                    "hall_name": HALL_NAME,
                    "floor": FLOOR,
                    "machine_number": n,
                    "X": x,
                    "Y": y,
                    "display_y": y,
                    "section": name,
                    "section_min": ordered[0],
                    "section_max": ordered[-1],
                    "rank_from_min": r,
                    "rank_from_max": total - r + 1,
                }
            )
    return rows


def verify(rows: list[dict]) -> list[str]:
    """DBの台番号集合・重複・列内の単調性を検査する。"""
    errs: list[str] = []
    nums = [r["machine_number"] for r in rows]
    dup = sorted({n for n in nums if nums.count(n) > 1})
    if dup:
        errs.append(f"重複: {dup}")
    con = sqlite3.connect(f"file:{ROOT / 'db' / 'ヒロキ東口店.db'}?mode=ro", uri=True)
    db = {
        r[0] for r in con.execute("SELECT DISTINCT machine_number FROM machine_detailed_results WHERE date='20261010'")
    }
    got = set(nums)
    if db - got:
        errs.append(f"DBにあって画像に無い: {sorted(db - got)}")
    if got - db:
        errs.append(f"画像にあってDBに無い: {sorted(got - db)}")
    for x, _, col in COLUMNS:
        inc = all(a < b for a, b in zip(col, col[1:]))
        dec = all(a > b for a, b in zip(col, col[1:]))
        if not (inc or dec):
            errs.append(f"列X={x} の台番号が単調でない: {col}")
    if not all(a > b for a, b in zip(BOTTOM_ROW, BOTTOM_ROW[1:])):
        errs.append("最下段の台番号が単調でない")
    return errs


def main() -> None:
    rows = build_rows()
    errs = verify(rows)
    print(f"台数={len(rows)}  セクション数={len({r['section'] for r in rows})}")
    for e in errs:
        print("NG:", e)
    if errs:
        raise SystemExit(1)
    with OUT.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDNAMES)
        w.writeheader()
        w.writerows(rows)
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
