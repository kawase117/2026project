"""
蒲田一 DD=11・土曜・イベント日 専用推薦スクリプト
==============================================
document/instincts の以下の確定インスティンクトに基づく（DD残差ではなく
セクション/カクバン/曜日フィルタを正しく適用する）:
  - kamata1-identity-a-specialized-hall: N系はDD軸無効
  - kamata1-2fa-event-near-universal-uplift: A系イベント日 section 2236-2255最強, kakuban=11/19, tail=8
  - kamata1-2fn-event-section-hotspot: N系イベント日 section 2177-2186 / 2099-2109, kakuban=3/9
  - kamata1-2fa-weekday-kakuban9-saturday: A系 土曜は kakuban=9 が突出(+269)
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from ml.analysis.kamata_corner_mirror_analysis import _read_machine_master_flags

DB = PROJECT_ROOT / "db" / "マルハンメガシティ2000-蒲田1.db"
COORD = PROJECT_ROOT / "Heatmap" / "2F_floor_coordinates_kamata1.csv"


def main() -> None:
    coords = pd.read_csv(COORD)
    coords["kakuban"] = coords["rank_from_min"].astype(int)
    coords["tail"] = coords["machine_number"] % 10

    with sqlite3.connect(DB) as conn:
        latest_df = pd.read_sql(
            "SELECT machine_number, machine_name, date FROM machine_detailed_results"
            " WHERE date = (SELECT MAX(date) FROM machine_detailed_results)",
            conn,
        ).drop_duplicates("machine_number")

    mtype_map = (
        _read_machine_master_flags(DB)
        .set_index("machine_name_normalized")
        .apply(
            lambda r: "A" if (r.get("jug_flag", 0) or r.get("hana_flag", 0) or r.get("bt_flag", 0)) else "N",
            axis=1,
        )
        .to_dict()
    )

    merged = coords.merge(latest_df[["machine_number", "machine_name"]], on="machine_number", how="left")
    merged["mtype"] = merged["machine_name"].map(mtype_map).fillna("N")
    print(f"DB最終日: {latest_df['date'].iloc[0]}")

    def in_section(df, lo, hi):
        return df[(df["machine_number"] >= lo) & (df["machine_number"] <= hi)]

    print("\n=== A系 (ジャグ/ハナハナ) --- イベント日 section 2236-2255 最優先 (premium+249) ===")
    a = merged[merged["mtype"] == "A"]
    a_sec = in_section(a, 2236, 2255).copy()
    a_sec["kakuban9_saturday_boost"] = a_sec["kakuban"] == 9
    a_sec["kakuban_pref"] = a_sec["kakuban"].isin([11, 19])
    a_sec["tail8_bonus"] = a_sec["tail"] == 8
    a_sec = a_sec.sort_values(["kakuban9_saturday_boost", "kakuban_pref", "tail8_bonus"], ascending=False)
    print(
        a_sec[
            [
                "machine_number",
                "machine_name",
                "kakuban",
                "tail",
                "kakuban9_saturday_boost",
                "kakuban_pref",
                "tail8_bonus",
            ]
        ].to_string(index=False)
    )

    print("\n=== A系 --- 全域 kakuban=9 (土曜ボーナス+269) / kakuban=11,19 (イベント日) ===")
    a_wide = a[a["kakuban"].isin([9, 11, 19])].copy()
    a_wide = a_wide.sort_values("kakuban")
    print(a_wide[["machine_number", "machine_name", "section", "kakuban", "tail"]].to_string(index=False))

    print("\n=== N系 (AT/ART) --- イベント日 section 2177-2186 最優先 (premium+375) ===")
    n = merged[merged["mtype"] == "N"]
    n_sec1 = in_section(n, 2177, 2186).copy()
    n_sec1["kakuban_pref"] = n_sec1["kakuban"].isin([3, 9])
    n_sec1 = n_sec1.sort_values("kakuban_pref", ascending=False)
    print(n_sec1[["machine_number", "machine_name", "kakuban", "tail", "kakuban_pref"]].to_string(index=False))

    print("\n=== N系 --- section 2099-2109 次点 (premium+353) ===")
    n_sec2 = in_section(n, 2099, 2109).copy()
    n_sec2["kakuban_pref"] = n_sec2["kakuban"].isin([3, 9])
    n_sec2 = n_sec2.sort_values("kakuban_pref", ascending=False)
    print(n_sec2[["machine_number", "machine_name", "kakuban", "tail", "kakuban_pref"]].to_string(index=False))


if __name__ == "__main__":
    main()
