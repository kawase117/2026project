"""楽園蒲田店のsectionを「端番効果の計算に使ってよいか」で分類する。

2026-07-28 のセッションでユーザーと確認した分類基準:

- ``frame``    外周（フロアの物理的境界: X最小/最大、またはY最小=最上段）。
                通路脇の壁面に沿った列で、投入戦略上の区切りかどうかホールの
                意図が不明なため除外。
- ``interior_split``
                外周ではないが、内部の通路で1本の列/島が分断されているもの
                （1100-1121のU字島、1122-1134の単列）。分断が実際の投入単位
                として存在するか不明なため除外。
- ``special``  三角形（2126-2128）やL字（2076-2077/2080-2082/2083-2090）など、
                直線的な列・facing pair islandではない特殊形状。端の定義が
                自明でないため除外。
- ``clean``     2列facing pair island（島の左右）、単列（通路breakなし）、
                S字（1本の折れ線）。rank_from_min/rank_from_maxが物理的な
                端と一致するため、端番効果の計算に使ってよい。

工事前(20250101)・工事後(20260706)の両エポックに対応する。本館2F/3Fは工事で
台番号が +2 シフトしたため、同じ物理位置でも section 名がエポックで異なる。

``frame`` の判定根拠は座標: そのフロアで X が最小/最大（左右の壁面）または
Y が最小（最上段）に貼り付いている列。``python -m eda.rakuen_section_classification``
で分類済みCSVを再生成できる。
"""

from __future__ import annotations

import csv
import sqlite3
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DB_PATH = PROJECT_ROOT / "db" / "楽園蒲田店.db"
HALL_NAME = "楽園蒲田店"

PRE_EPOCH = "20250101"
POST_EPOCH = "20260706"

# エポックごとの section 名。本館2F/3F は工事(2026-07-06)で台番号が +2 シフト
# したため、同じ物理位置でも名前が変わる。
FRAME_SECTIONS: dict[str, set[str]] = {
    PRE_EPOCH: {
        # 本館1F: 左壁 / 上辺 / 右壁
        "1135-1138",
        "1139-1144",
        "1145-1151",
        "1152-1155",
        "1209-1216",
        # 本館2F
        "2100-2105",
        "2106-2110",
        "2111-2113",
        "2163-2170",
        "2171-2172",
        "2173-2184",
        # 本館3F
        "3107-3112",
        "3113-3116",
        "3117-3120",
        "3164-3173",
        "3174-3179",
        "3180-3185",
        # 新館1F
        "1000-1005",
        "1006-1016",
        # 新館2F
        "2000-2003",
        "2004-2007",
        "2008-2020",
    },
    POST_EPOCH: {
        # 本館1F
        "1135-1138",
        "1139-1144",
        "1145-1151",
        "1152-1155",
        "1209-1216",
        # 本館2F
        "2100-2105",
        "2106-2110",
        "2111-2113",
        "2165-2172",
        "2173-2174",
        "2175-2186",
        # 本館3F
        "3107-3112",
        "3113-3116",
        "3117-3120",
        "3166-3175",
        "3176-3181",
        "3182-3187",
        # 新館1F
        "1000-1005",
        "1006-1016",
        # 新館2F
        "2000-2003",
        "2004-2007",
        "2008-2020",
    },
}

# 外周ではないが内部の通路で分断されている列。工事前後で台番号は変わらない。
INTERIOR_SPLIT_SECTIONS: dict[str, set[str]] = {
    epoch: {
        # 1100-1121 U字島（通路で上下に分断）
        "1100-1105",
        "1106-1110",
        "1111-1115",
        "1116-1121",
        # 1122-1134 単列（通路で上下に分断）
        "1122-1129",
        "1130-1134",
    }
    for epoch in (PRE_EPOCH, POST_EPOCH)
}

SPECIAL_SECTIONS: dict[str, set[str]] = {
    epoch: {
        "2126-2128",  # 攻殻機動隊 三角形島
        "2076-2077",
        "2080-2082",
        "2083-2090",  # 喰種 L字島
    }
    for epoch in (PRE_EPOCH, POST_EPOCH)
}


def classify(section: str, epoch: str) -> str:
    if section in FRAME_SECTIONS[epoch]:
        return "frame"
    if section in INTERIOR_SPLIT_SECTIONS[epoch]:
        return "interior_split"
    if section in SPECIAL_SECTIONS[epoch]:
        return "special"
    return "clean"


def clean_sections(epoch: str) -> set[str]:
    """端番効果の計算に使ってよい section 名の集合。"""
    with sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True) as con:
        rows = con.execute(
            "SELECT DISTINCT section FROM machine_layout_history WHERE hall_name = ? AND valid_from = ?",
            (HALL_NAME, epoch),
        ).fetchall()
    return {sec for (sec,) in rows if classify(sec, epoch) == "clean"}


def load_sections(epoch: str) -> list[dict[str, object]]:
    with sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True) as con:
        rows = con.execute(
            "SELECT section, section_min, section_max, COUNT(*) "
            "FROM machine_layout_history "
            "WHERE hall_name = ? AND valid_from = ? "
            "GROUP BY section, section_min, section_max",
            (HALL_NAME, epoch),
        ).fetchall()

    return sorted(
        (
            {
                "epoch": epoch,
                "section": section,
                "section_min": section_min,
                "section_max": section_max,
                "n_machines": n_machines,
                "category": classify(section, epoch),
            }
            for section, section_min, section_max, n_machines in rows
        ),
        key=lambda r: r["section_min"],
    )


def write_csv(records: list[dict[str, object]], output_path: Path) -> None:
    fieldnames = [
        "epoch",
        "section",
        "section_min",
        "section_max",
        "n_machines",
        "category",
    ]
    with output_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(records)
    print(f"Wrote {len(records)} rows to {output_path}")


def main() -> None:
    all_records: list[dict[str, object]] = []
    for epoch in (PRE_EPOCH, POST_EPOCH):
        records = load_sections(epoch)
        all_records.extend(records)

        by_category: dict[str, int] = {}
        machines_by_category: dict[str, int] = {}
        for r in records:
            by_category[r["category"]] = by_category.get(r["category"], 0) + 1
            machines_by_category[r["category"]] = machines_by_category.get(r["category"], 0) + r["n_machines"]

        label = "工事前" if epoch == PRE_EPOCH else "工事後"
        print(f"\n=== {label} ({epoch}) : {len(records)} section ===")
        for category in ("clean", "frame", "interior_split", "special"):
            n_sec = by_category.get(category, 0)
            n_mac = machines_by_category.get(category, 0)
            print(f"  {category:16s} {n_sec:3d} section / {n_mac:4d} 台")

    write_csv(all_records, Path(__file__).parent / "rakuen_section_classification.csv")


if __name__ == "__main__":
    main()
