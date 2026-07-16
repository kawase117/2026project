"""
Rakuen (rakuen kamata) roadmap items 3-6.

3. last_digit effect conditioned on strong sections (Step1-3 hierarchical residual,
   subset to strong sections detected in Step1-3).
4. event-day (DD in set(11,22)) interaction per section, re-check / extend
   Event-responsive section detection from Step1-3.
5. debut-phase (3-phase-model style) analysis using eda/core.compute_debut_features.
6. zorome effect: machine-number last-two-digit zorome (is_zorome col in
   machine_detailed_results) vs date zorome (dd in set(11,22), daily_hall_summary style).

Output: eda/results/rakuen_roadmap_3to6/*.csv + report.md
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

BASE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE_DIR))

from eda.core import HALL_EVENT_DIGITS, compute_debut_features, load_hall_df  # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

OUT_DIR = BASE_DIR / "eda" / "results" / "rakuen_roadmap_3to6"
OUT_DIR.mkdir(parents=True, exist_ok=True)

FLOOR_CSVS = [
    BASE_DIR / "Heatmap" / "honkan1F_floor_coordinates_rakuen.csv",
    BASE_DIR / "Heatmap" / "honkan2F_floor_coordinates_rakuen.csv",
    BASE_DIR / "Heatmap" / "honkan3F_floor_coordinates_rakuen.csv",
    BASE_DIR / "Heatmap" / "shinkan1F_floor_coordinates_rakuen.csv",
    BASE_DIR / "Heatmap" / "shinkan2F_floor_coordinates_rakuen.csv",
]

HALL = "楽園"
MIN_GAMES = 2000
EVENT_DDS = set(HALL_EVENT_DIGITS[HALL])
THRESHOLD_PP = 3.0

STRONG_SECTIONS = [
    "3164-3173",
    "3200-3225",
    "2141-2162",
    "1122-1129",
    "3174-3185",
    "3226-3249",
    "2173-2184",
    "3186-3199",
    "3142-3163",
]


def label_sig(value):
    return "SIGNIFICANT" if value >= THRESHOLD_PP else "not-significant"


def load_layout():
    dfs = [pd.read_csv(p) for p in FLOOR_CSVS]
    df = pd.concat(dfs, ignore_index=True)
    df["kakuban"] = df[["rank_from_min", "rank_from_max"]].min(axis=1)
    return df[["machine_number", "floor", "section", "kakuban"]]


def load_base():
    df = load_hall_df(HALL)
    df = compute_debut_features(df, db_start_grace_days=0)
    layout = load_layout()
    df = df.merge(layout, on="machine_number", how="inner")
    df = df[df["games"] >= MIN_GAMES].copy()
    df["hit"] = df["plus"]
    df["date_zorome"] = df["dd"].isin(EVENT_DDS).astype(int)
    return df


def task3_lastdigit_in_strong_sections(df):
    work = df.copy()
    work["ds_mean"] = work.groupby(["date", "section"])["hit"].transform("mean")
    work["resid2"] = work["hit"] - work["ds_mean"]

    strong = work[work["section"].isin(STRONG_SECTIONS)].copy()

    overall_eff = work.groupby("machine_digit")["resid2"].agg(["mean", "count"])
    overall_eff["mean"] = overall_eff["mean"] * 100
    overall_range = overall_eff["mean"].max() - overall_eff["mean"].min()

    strong_eff = strong.groupby("machine_digit")["resid2"].agg(["mean", "count"])
    strong_eff["mean"] = strong_eff["mean"] * 100
    strong_eff_filtered = strong_eff[strong_eff["count"] >= 30]
    if len(strong_eff_filtered) > 0:
        strong_range = strong_eff_filtered["mean"].max() - strong_eff_filtered["mean"].min()
    else:
        strong_range = float("nan")

    overall_eff.sort_values("mean", ascending=False).to_csv(
        OUT_DIR / "task3_lastdigit_overall.csv", encoding="utf-8-sig"
    )
    strong_eff.sort_values("mean", ascending=False).to_csv(
        OUT_DIR / "task3_lastdigit_strong_sections.csv", encoding="utf-8-sig"
    )

    print("=== Task3: last_digit in strong sections ===")
    print("overall range:", round(overall_range, 2), "pp ->", label_sig(overall_range))
    print("strong-section range (n>=30):", round(strong_range, 2), "pp ->", label_sig(strong_range))
    print(strong_eff_filtered.sort_values("mean", ascending=False).to_string())

    verdict = label_sig(strong_range) if not np.isnan(strong_range) else "hantei_funou_n_busoku"
    return {
        "overall_range_pp": overall_range,
        "strong_section_range_pp": strong_range,
        "strong_section_n_rows": int(len(strong)),
        "verdict": verdict,
    }


def task4_event_interaction(df):
    overall_hit = df["hit"].mean() * 100

    sec = df.groupby(["floor", "section", "date_zorome"]).agg(hit_rate=("hit", "mean"), n=("hit", "size")).reset_index()
    sec["hit_rate"] = sec["hit_rate"] * 100
    piv = sec.pivot_table(index=["floor", "section"], columns="date_zorome", values="hit_rate").reset_index()
    piv.columns = ["floor", "section", "hit_nonevent", "hit_event"]
    n_by_sec = df.groupby(["floor", "section"]).agg(n=("hit", "size")).reset_index()
    piv = piv.merge(n_by_sec, on=["floor", "section"], how="left")
    piv["event_lift_pp"] = piv["hit_event"] - piv["hit_nonevent"]
    piv["baseline_diff_pp"] = piv["hit_nonevent"] - overall_hit
    piv = piv.sort_values("event_lift_pp", ascending=False)
    piv.to_csv(OUT_DIR / "task4_section_event_lift.csv", index=False, encoding="utf-8-sig")

    reliable = piv[piv["n"] >= 500].copy()

    def classify(row):
        strong_baseline = abs(row["baseline_diff_pp"]) >= THRESHOLD_PP
        strong_lift = abs(row["event_lift_pp"]) >= THRESHOLD_PP
        if strong_lift and not strong_baseline:
            return "Event-responsive"
        if strong_baseline and not strong_lift:
            return "always_Hot_Cold"
        if strong_baseline and strong_lift:
            return "Hot_plus_Event"
        return "Neutral"

    reliable["type"] = reliable.apply(classify, axis=1)
    reliable.to_csv(OUT_DIR / "task4_section_event_lift_reliable.csv", index=False, encoding="utf-8-sig")

    top10 = reliable.sort_values("event_lift_pp", ascending=False).head(10)
    bottom5 = reliable.sort_values("event_lift_pp", ascending=True).head(5)

    print()
    print("=== Task4: event-day section interaction (n>=500) ===")
    print("overall hit_rate:", round(overall_hit, 1))
    print("--- Top10 event-responsive ---")
    print(top10.to_string(index=False))
    print("--- Bottom5 (event-day worse) ---")
    print(bottom5.to_string(index=False))
    print(reliable["type"].value_counts().to_string())

    return {
        "n_sections_reliable": int(len(reliable)),
        "max_event_lift_pp": float(reliable["event_lift_pp"].max()) if len(reliable) else float("nan"),
        "min_event_lift_pp": float(reliable["event_lift_pp"].min()) if len(reliable) else float("nan"),
        "n_event_responsive": int((reliable["type"] == "Event-responsive").sum()),
        "top1_section": (top10.iloc[0]["floor"] + " " + top10.iloc[0]["section"]) if len(top10) else "N/A",
        "top1_lift_pp": float(top10.iloc[0]["event_lift_pp"]) if len(top10) else float("nan"),
    }


def task5_debut_phase(df):
    labels = ["1-14nichi", "15-60nichi", "61-180nichi", "181nichi_plus"]
    work = df[~df["pre_existing"]].copy()
    work["debut_phase"] = pd.cut(
        work["days_since_debut"],
        bins=[-0.5, 14, 60, 180, float("inf")],
        labels=labels,
        include_lowest=True,
    )

    overall_diff = df["diff"].mean()
    overall_hit = df["hit"].mean() * 100

    phase_summary = (
        work.groupby("debut_phase", observed=True)
        .agg(
            avg_diff=("diff", "mean"),
            hit_rate=("hit", "mean"),
            n=("diff", "size"),
            n_machine_names=("machine_name", "nunique"),
        )
        .reset_index()
    )
    phase_summary["hit_rate"] = phase_summary["hit_rate"] * 100
    phase_summary["excess_diff"] = phase_summary["avg_diff"] - overall_diff
    phase_summary["excess_hit_pp"] = phase_summary["hit_rate"] - overall_hit

    pre_row = pd.DataFrame(
        [
            {
                "debut_phase": "teiban_pre_existing",
                "avg_diff": df.loc[df["pre_existing"], "diff"].mean(),
                "hit_rate": df.loc[df["pre_existing"], "hit"].mean() * 100,
                "n": int(df["pre_existing"].sum()),
                "n_machine_names": df.loc[df["pre_existing"], "machine_name"].nunique(),
            }
        ]
    )
    pre_row["excess_diff"] = pre_row["avg_diff"] - overall_diff
    pre_row["excess_hit_pp"] = pre_row["hit_rate"] - overall_hit

    full_summary = pd.concat([phase_summary, pre_row], ignore_index=True)
    full_summary.to_csv(OUT_DIR / "task5_debut_phase_summary.csv", index=False, encoding="utf-8-sig")

    print()
    print("=== Task5: debut phase (3-phase-model style) ===")
    print("overall avg_diff:", round(overall_diff, 1), "overall hit_rate:", round(overall_hit, 1))
    print(full_summary.to_string(index=False))

    row_61_180 = phase_summary[phase_summary["debut_phase"] == "61-180nichi"]
    plus_zone = bool((row_61_180["excess_diff"] > 0).all()) if len(row_61_180) else False

    return {
        "overall_avg_diff": float(overall_diff),
        "phase_61_180_excess_diff": float(row_61_180["excess_diff"].iloc[0]) if len(row_61_180) else float("nan"),
        "phase_61_180_excess_hit_pp": float(row_61_180["excess_hit_pp"].iloc[0]) if len(row_61_180) else float("nan"),
        "phase_61_180_n": int(row_61_180["n"].iloc[0]) if len(row_61_180) else 0,
        "matches_plus_zone_hypothesis": plus_zone,
    }


def task6_zorome(df):
    work = df.copy()
    work["machine_zorome"] = pd.to_numeric(work["machine_zorome"], errors="coerce").fillna(0).astype(int)

    overall_diff = work["diff"].mean()
    overall_hit = work["hit"].mean() * 100

    def summarize(col):
        g = work.groupby(col).agg(avg_diff=("diff", "mean"), hit_rate=("hit", "mean"), n=("diff", "size")).reset_index()
        g["hit_rate"] = g["hit_rate"] * 100
        g["excess_diff"] = g["avg_diff"] - overall_diff
        g["excess_hit_pp"] = g["hit_rate"] - overall_hit
        return g

    machine_zorome_summary = summarize("machine_zorome")
    date_zorome_summary = summarize("date_zorome")

    cross = (
        work.groupby(["machine_zorome", "date_zorome"])
        .agg(avg_diff=("diff", "mean"), hit_rate=("hit", "mean"), n=("diff", "size"))
        .reset_index()
    )
    cross["hit_rate"] = cross["hit_rate"] * 100
    cross["excess_diff"] = cross["avg_diff"] - overall_diff

    machine_zorome_summary.to_csv(OUT_DIR / "task6_machine_zorome.csv", index=False, encoding="utf-8-sig")
    date_zorome_summary.to_csv(OUT_DIR / "task6_date_zorome.csv", index=False, encoding="utf-8-sig")
    cross.to_csv(OUT_DIR / "task6_zorome_cross.csv", index=False, encoding="utf-8-sig")

    print()
    print("=== Task6: zorome (machine-number last-two-digit vs date DD 11/22) ===")
    print("--- machine_zorome (machine_detailed_results.is_zorome) ---")
    print(machine_zorome_summary.to_string(index=False))
    print("--- date_zorome (daily_hall_summary style, dd 11 or 22) ---")
    print(date_zorome_summary.to_string(index=False))
    print("--- cross ---")
    print(cross.to_string(index=False))

    m1 = machine_zorome_summary[machine_zorome_summary["machine_zorome"] == 1]
    d1 = date_zorome_summary[date_zorome_summary["date_zorome"] == 1]

    return {
        "machine_zorome_excess_diff": float(m1["excess_diff"].iloc[0]) if len(m1) else float("nan"),
        "machine_zorome_excess_hit_pp": float(m1["excess_hit_pp"].iloc[0]) if len(m1) else float("nan"),
        "machine_zorome_n": int(m1["n"].iloc[0]) if len(m1) else 0,
        "date_zorome_excess_diff": float(d1["excess_diff"].iloc[0]) if len(d1) else float("nan"),
        "date_zorome_excess_hit_pp": float(d1["excess_hit_pp"].iloc[0]) if len(d1) else float("nan"),
        "date_zorome_n": int(d1["n"].iloc[0]) if len(d1) else 0,
    }


def main():
    df = load_base()
    print("rows (games>=2000):", len(df), "| date range:", df["date"].min(), "-", df["date"].max())

    r3 = task3_lastdigit_in_strong_sections(df)
    r4 = task4_event_interaction(df)
    r5 = task5_debut_phase(df)
    r6 = task6_zorome(df)

    summary = {
        "task3_lastdigit_strong_section_range_pp": r3["strong_section_range_pp"],
        "task3_verdict": r3["verdict"],
        "task4_max_event_lift_pp": r4["max_event_lift_pp"],
        "task4_n_event_responsive_sections": r4["n_event_responsive"],
        "task5_phase_61_180_excess_diff": r5["phase_61_180_excess_diff"],
        "task5_matches_plus_zone_hypothesis": r5["matches_plus_zone_hypothesis"],
        "task6_machine_zorome_excess_diff": r6["machine_zorome_excess_diff"],
        "task6_date_zorome_excess_diff": r6["date_zorome_excess_diff"],
    }
    pd.Series(summary).to_csv(OUT_DIR / "summary.csv", encoding="utf-8-sig")
    print()
    print("=== Summary ===")
    for k, v in summary.items():
        print(k, ":", v)


if __name__ == "__main__":
    main()
