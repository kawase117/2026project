"""
Rakuen (rakuen kamata) segment structure analysis Step1-3.

Step1: combine 5 floor coordinate CSVs to understand section structure.
Step2: hit rate (diff_coins_normalized > 0) based Hot/Cold section detection,
       10-machine block heatmap, position quartile analysis.
Step3: hierarchical residual method (remove (date, section) mean) to test
       weekday / last_digit / kakuban effect size (pp), threshold = 3pp.

Output: eda/results/rakuen_segment_structure/*.csv
"""

from pathlib import Path

import pandas as pd
import sqlite3

BASE_DIR = Path(__file__).resolve().parents[1]
DB_PATH = BASE_DIR / "db" / "楽園蒲田店.db"
OUT_DIR = BASE_DIR / "eda" / "results" / "rakuen_segment_structure"
OUT_DIR.mkdir(parents=True, exist_ok=True)

FLOOR_CSVS = [
    BASE_DIR / "Heatmap" / "honkan1F_floor_coordinates_rakuen.csv",
    BASE_DIR / "Heatmap" / "honkan2F_floor_coordinates_rakuen.csv",
    BASE_DIR / "Heatmap" / "honkan3F_floor_coordinates_rakuen.csv",
    BASE_DIR / "Heatmap" / "shinkan1F_floor_coordinates_rakuen.csv",
    BASE_DIR / "Heatmap" / "shinkan2F_floor_coordinates_rakuen.csv",
]

MIN_GAMES = 2000
EVENT_DDS = {11, 22}
THRESHOLD_PP = 3.0


def label_sig(value):
    if value >= THRESHOLD_PP:
        return "SIGNIFICANT"
    return "not-significant"


def load_layout():
    dfs = [pd.read_csv(p) for p in FLOOR_CSVS]
    df = pd.concat(dfs, ignore_index=True)
    df["kakuban"] = df[["rank_from_min", "rank_from_max"]].min(axis=1)
    return df


def load_results():
    conn = sqlite3.connect(DB_PATH)
    df = pd.read_sql_query(
        "SELECT date, machine_number, machine_name, last_digit, "
        "games_normalized, diff_coins_normalized FROM machine_detailed_results",
        conn,
    )
    conn.close()
    df["date"] = pd.to_datetime(df["date"], format="%Y%m%d")
    return df


def step1_section_structure(layout):
    sec = (
        layout.groupby(["floor", "section", "section_min", "section_max"])
        .agg(n_machines=("machine_number", "count"))
        .reset_index()
        .sort_values(["floor", "section_min"])
    )
    sec.to_csv(OUT_DIR / "step1_section_structure.csv", index=False, encoding="utf-8-sig")
    return sec


def main():
    layout = load_layout()
    sec_struct = step1_section_structure(layout)

    n_sections = sec_struct["section"].nunique()
    n_machines = layout["machine_number"].nunique()
    mini_sections = sec_struct[sec_struct["n_machines"] <= 5]
    max_island = sec_struct.loc[sec_struct["n_machines"].idxmax()]

    print("=== Step1: section structure ===")
    print("valid sections:", n_sections)
    print("machines:", n_machines)
    print("mini sections (<=5):", len(mini_sections))
    print(mini_sections[["floor", "section", "n_machines"]].to_string(index=False))
    print("max island:", max_island["section"], max_island["n_machines"], max_island["floor"])

    results = load_results()
    df = results.merge(layout, on="machine_number", how="inner")
    df = df[df["games_normalized"] >= MIN_GAMES].copy()

    df["hit"] = (df["diff_coins_normalized"] > 0).astype(int)
    df["dd"] = df["date"].dt.day
    df["weekday"] = df["date"].dt.day_name()
    df["is_event"] = df["dd"].isin(EVENT_DDS)

    overall_hit = df["hit"].mean() * 100
    print()
    print("=== Step2: overall hit rate =", round(overall_hit, 1), "n=", len(df), "===")

    sec_hit = df.groupby(["floor", "section"]).agg(hit_rate=("hit", "mean"), n=("hit", "size")).reset_index()
    sec_hit["hit_rate"] = sec_hit["hit_rate"] * 100
    sec_hit["diff_pp"] = sec_hit["hit_rate"] - overall_hit
    sec_hit = sec_hit.merge(sec_struct[["floor", "section", "n_machines"]], on=["floor", "section"], how="left")
    sec_hit = sec_hit.sort_values("diff_pp", ascending=False)
    sec_hit.to_csv(OUT_DIR / "step2_section_hit_rate.csv", index=False, encoding="utf-8-sig")

    hot3 = sec_hit.head(3)
    cold3 = sec_hit.tail(3).sort_values("diff_pp")
    print()
    print("--- Hot Top3 ---")
    print(hot3.to_string(index=False))
    print()
    print("--- Cold Top3 ---")
    print(cold3.to_string(index=False))

    df["block10"] = (df["machine_number"] // 10) * 10
    block_hit = df.groupby(["floor", "block10"]).agg(hit_rate=("hit", "mean"), n=("hit", "size")).reset_index()
    block_hit["hit_rate"] = block_hit["hit_rate"] * 100
    block_hit["diff_pp"] = block_hit["hit_rate"] - overall_hit
    block_hit = block_hit.sort_values("diff_pp", ascending=False)
    block_hit.to_csv(OUT_DIR / "step2_block10_heatmap.csv", index=False, encoding="utf-8-sig")

    df["pos_quartile"] = pd.qcut(df["machine_number"], 4, labels=["Q1", "Q2", "Q3", "Q4"])
    quart = df.groupby("pos_quartile", observed=True)["hit"].mean() * 100
    quart_range = quart.max() - quart.min()
    print()
    print("--- position quartile (machine_number order) --- range=", round(quart_range, 1), "pp")
    print(quart.to_string())
    quart.to_csv(OUT_DIR / "step2_position_quartile.csv", encoding="utf-8-sig")

    sec_event = (
        df.groupby(["floor", "section", "is_event"]).agg(hit_rate=("hit", "mean"), n=("hit", "size")).reset_index()
    )
    sec_event["hit_rate"] = sec_event["hit_rate"] * 100
    sec_event_piv = sec_event.pivot_table(
        index=["floor", "section"], columns="is_event", values="hit_rate"
    ).reset_index()
    sec_event_piv.columns = ["floor", "section", "hit_nonevent", "hit_event"]
    sec_event_piv["event_lift_pp"] = sec_event_piv["hit_event"] - sec_event_piv["hit_nonevent"]
    sec_event_piv = sec_event_piv.merge(sec_hit[["floor", "section", "n"]], on=["floor", "section"], how="left")
    sec_event_piv = sec_event_piv.sort_values("event_lift_pp", ascending=False)
    sec_event_piv.to_csv(OUT_DIR / "step2_section_event_responsive.csv", index=False, encoding="utf-8-sig")
    print()
    print("--- Event-responsive sections Top5 (event_lift_pp) ---")
    print(sec_event_piv.head(5).to_string(index=False))

    df["ds_mean"] = df.groupby(["date", "section"])["hit"].transform("mean")
    df["resid2"] = df["hit"] - df["ds_mean"]

    weekday_eff = df.groupby("weekday")["resid2"].mean() * 100
    weekday_range = weekday_eff.max() - weekday_eff.min()

    lastdigit_eff = df.groupby("last_digit")["resid2"].mean() * 100
    lastdigit_range = lastdigit_eff.max() - lastdigit_eff.min()

    kakuban_eff = df.groupby("kakuban")["resid2"].agg(["mean", "count"])
    kakuban_eff["mean"] = kakuban_eff["mean"] * 100
    kakuban_eff_filtered = kakuban_eff[kakuban_eff["count"] >= 30]
    if len(kakuban_eff_filtered) > 0:
        kakuban_range = kakuban_eff_filtered["mean"].max() - kakuban_eff_filtered["mean"].min()
    else:
        kakuban_range = float("nan")

    weekday_eff.to_csv(OUT_DIR / "step3_weekday_residual.csv", encoding="utf-8-sig")
    lastdigit_eff.to_csv(OUT_DIR / "step3_lastdigit_residual.csv", encoding="utf-8-sig")
    kakuban_eff.to_csv(OUT_DIR / "step3_kakuban_residual.csv", encoding="utf-8-sig")

    print()
    print("=== Step3: hierarchical residual method (threshold 3pp) ===")
    print("weekday range:", round(weekday_range, 2), "pp ->", label_sig(weekday_range))
    print(weekday_eff.sort_values(ascending=False).to_string())
    print()
    print("last_digit range:", round(lastdigit_range, 2), "pp ->", label_sig(lastdigit_range))
    print(lastdigit_eff.sort_values(ascending=False).to_string())
    print()
    print("kakuban range (n>=30 only):", round(kakuban_range, 2), "pp ->", label_sig(kakuban_range))
    print(kakuban_eff_filtered.sort_values("mean", ascending=False).to_string())

    summary = {
        "n_sections": n_sections,
        "n_machines": n_machines,
        "n_mini_sections": len(mini_sections),
        "overall_hit_rate": overall_hit,
        "n_rows_filtered": len(df),
        "position_quartile_range_pp": quart_range,
        "weekday_range_pp": weekday_range,
        "lastdigit_range_pp": lastdigit_range,
        "kakuban_range_pp": kakuban_range,
    }
    pd.Series(summary).to_csv(OUT_DIR / "summary.csv", encoding="utf-8-sig")

    print()
    print("=== Summary ===")
    for k, v in summary.items():
        print(k, ":", v)


if __name__ == "__main__":
    main()
