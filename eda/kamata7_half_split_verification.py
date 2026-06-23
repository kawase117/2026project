from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from eda.kamata7_lastdigit_lr_eda import load_coords
from eda.kamata7_verification_common import (
    DOW_ORDER,
    REPORT_DIR,
    attach_floor_side,
    attach_seg,
    bootstrap_mean_ci,
    ensure_report_dir,
    mann_whitney,
    prepare_base_frame,
    signed,
    table_to_markdown,
    write_text,
)

REPORT_PATH = REPORT_DIR / "kamata7_half_split_verification_report.md"


def _prepare_frame() -> pd.DataFrame:
    df = prepare_base_frame(include_floor_side=True)
    df = attach_seg(df)
    coords = load_coords().copy()
    coords = coords.drop_duplicates(subset=["machine_number"], keep="first")
    df = df.merge(coords[["machine_number", "section", "section_min", "display_x"]], on="machine_number", how="inner")
    df["section_key"] = df["floor"].astype(str) + "_" + df["section_min"].astype(str)
    df["day_of_week"] = pd.Categorical(df["day_of_week"], categories=DOW_ORDER, ordered=True)
    return df.reset_index(drop=True)


def _split_dates(df: pd.DataFrame) -> tuple[pd.Index, pd.Index]:
    dates = pd.Index(sorted(pd.unique(df["date"].astype(str))))
    mid = len(dates) // 2
    return dates[:mid], dates[mid:]


def _adjacent_pairs(coords: pd.DataFrame) -> pd.DataFrame:
    pairs: list[dict[str, object]] = []
    coords = coords.copy()
    coords["section_key"] = coords["floor"].astype(str) + "_" + coords["section_min"].astype(str)
    for (floor, section_key), grp in coords.sort_values(["floor", "section_min", "display_x", "machine_number"]).groupby(["floor", "section_key"], dropna=False):
        ordered = grp.sort_values(["display_x", "machine_number"]).reset_index(drop=True)
        for idx in range(len(ordered) - 1):
            a = ordered.iloc[idx]
            b = ordered.iloc[idx + 1]
            pairs.append(
                {
                    "floor": floor,
                    "section_key": section_key,
                    "machine_a": int(a["machine_number"]),
                    "machine_b": int(b["machine_number"]),
                    "pair_label": f"{int(a['machine_number'])}-{int(b['machine_number'])}",
                }
            )
    return pd.DataFrame(pairs)


def _pair_corr(df: pd.DataFrame, weekday: str, dates: pd.Index) -> pd.DataFrame:
    sub = df[(df["day_of_week"] == weekday) & (df["date"].isin(dates))].copy()
    if sub.empty:
        return pd.DataFrame(columns=["floor", "section_key", "pair_label", "n_days", "spearman_r", "p_value"])
    pair_map = _adjacent_pairs(sub[["machine_number", "floor", "section_min", "display_x"]].drop_duplicates())
    rows: list[dict[str, object]] = []
    for _, pair in pair_map.iterrows():
        left = sub[sub["machine_number"] == pair["machine_a"]][["date", "diff"]].rename(columns={"diff": "a"})
        right = sub[sub["machine_number"] == pair["machine_b"]][["date", "diff"]].rename(columns={"diff": "b"})
        merged = left.merge(right, on="date", how="inner")
        if len(merged) < 4:
            continue
        r, p = stats.spearmanr(merged["a"], merged["b"])
        rows.append(
            {
                "floor": pair["floor"],
                "section_key": pair["section_key"],
                "pair_label": pair["pair_label"],
                "n_days": len(merged),
                "spearman_r": round(float(r), 4) if not pd.isna(r) else np.nan,
                "p_value": round(float(p), 6) if not pd.isna(p) else np.nan,
            }
        )
    return pd.DataFrame(rows)


def _streak_stats(df: pd.DataFrame, weekday: str, dates: pd.Index) -> pd.DataFrame:
    sub = df[(df["day_of_week"] == weekday) & (df["date"].isin(dates))].copy()
    if sub.empty:
        return pd.DataFrame(columns=["weekday", "section_key", "opportunities", "observed", "positive_rate", "expected", "ratio"])
    rows: list[dict[str, object]] = []
    for section_key, grp in sub.groupby("section_key", dropna=False):
        ordered = grp[["machine_number", "display_x"]].drop_duplicates().sort_values(["display_x", "machine_number"])
        machine_order = ordered["machine_number"].astype(int).tolist()
        if len(machine_order) < 3:
            continue
        by_date = grp.pivot_table(index="date", columns="machine_number", values="diff", aggfunc="mean")
        opportunities = 0
        observed = 0
        for date, row in by_date.iterrows():
            for i in range(len(machine_order) - 2):
                trio = machine_order[i : i + 3]
                vals = row.reindex(trio)
                if vals.notna().sum() < 3:
                    continue
                opportunities += 1
                if (vals > 0).all():
                    observed += 1
        if opportunities == 0:
            continue
        positive_rate = float((grp.groupby("machine_number")["diff"].mean() > 0).mean())
        expected = opportunities * (positive_rate ** 3)
        rows.append(
            {
                "weekday": weekday,
                "section_key": section_key,
                "opportunities": opportunities,
                "observed": observed,
                "positive_rate": round(positive_rate * 100, 1),
                "expected": round(expected, 1),
                "ratio": round(observed / expected, 3) if expected > 0 else np.nan,
            }
        )
    return pd.DataFrame(rows)


def _concentration(df: pd.DataFrame, weekday: str, dates: pd.Index) -> pd.DataFrame:
    sub = df[(df["day_of_week"] == weekday) & (df["date"].isin(dates))].copy()
    if sub.empty:
        return pd.DataFrame(columns=["weekday", "section_key", "top3_mean", "section_mean", "delta", "gini", "hhi"])
    rows: list[dict[str, object]] = []
    for section_key, grp in sub.groupby("section_key", dropna=False):
        machine_means = grp.groupby("machine_number")["diff"].mean().sort_values(ascending=False)
        if len(machine_means) < 3:
            continue
        top3_mean = float(machine_means.head(3).mean())
        section_mean = float(machine_means.mean())
        vals = machine_means.clip(lower=0).to_numpy()
        total = vals.sum()
        if total > 0:
            weights = vals / total
            hhi = float(np.square(weights).sum())
            sorted_vals = np.sort(vals)
            n = len(sorted_vals)
            if n > 0 and sorted_vals.sum() > 0:
                cum = np.cumsum(sorted_vals)
                gini = float((n + 1 - 2 * (cum.sum() / cum[-1])) / n)
            else:
                gini = np.nan
        else:
            hhi = np.nan
            gini = np.nan
        rows.append(
            {
                "weekday": weekday,
                "section_key": section_key,
                "top3_mean": round(top3_mean, 1),
                "section_mean": round(section_mean, 1),
                "delta": round(top3_mean - section_mean, 1),
                "gini": round(gini, 3) if not pd.isna(gini) else np.nan,
                "hhi": round(hhi, 3) if not pd.isna(hhi) else np.nan,
            }
        )
    return pd.DataFrame(rows)


def build_report() -> str:
    df = _prepare_frame()
    first_dates, second_dates = _split_dates(df)

    def _pair_compare(weekday: str) -> pd.DataFrame:
        first = _pair_corr(df, weekday, first_dates)
        second = _pair_corr(df, weekday, second_dates)
        merged = first.merge(second, on=["floor", "section_key", "pair_label"], how="outer", suffixes=("_first", "_second"))
        if merged.empty:
            return merged
        merged["delta_r"] = merged["spearman_r_second"] - merged["spearman_r_first"]
        merged["fisher_p"] = merged.apply(
            lambda r: np.nan if pd.isna(r["spearman_r_first"]) or pd.isna(r["spearman_r_second"]) else stats.norm.sf(
                abs(np.arctanh(np.clip(r["spearman_r_first"], -0.999999, 0.999999)) - np.arctanh(np.clip(r["spearman_r_second"], -0.999999, 0.999999)))
                / np.sqrt((1 / max(r["n_days_first"] - 3, 1)) + (1 / max(r["n_days_second"] - 3, 1)))
            ) * 2,
            axis=1,
        )
        return merged.sort_values("delta_r", ascending=False)

    sections: list[str] = []
    sections.append("# ハーフ×2本移行後の再検証")
    sections.append("")
    sections.append("## Section 1: 期間分割")
    sections.append(table_to_markdown(pd.DataFrame([{
        "start_date": first_dates.min() if len(first_dates) else "",
        "mid_date": second_dates.min() if len(second_dates) else "",
        "end_date": second_dates.max() if len(second_dates) else "",
        "first_n_days": len(first_dates),
        "second_n_days": len(second_dates),
        "total_days": df["date"].nunique(),
    }])))
    sections.append("")

    for label, dates in [("前半", first_dates), ("後半", second_dates)]:
        sat_corr = _pair_corr(df, "土", dates)
        sat_streak = _streak_stats(df, "土", dates)
        sat_conc = _concentration(df, "土", dates)
        fri = _pair_corr(df, "金", dates)
        sun = _pair_corr(df, "日", dates)
        sections.append(f"## Section 2: 土曜日の並び検出力の期間比較 - {label}")
        sections.append(table_to_markdown(sat_corr.sort_values(["spearman_r", "pair_label"], ascending=[False, True]).head(20).reset_index(drop=True)))
        sections.append("")
        sections.append(table_to_markdown(sat_streak.sort_values(["section_key"]).reset_index(drop=True)))
        sections.append("")
        sections.append(table_to_markdown(sat_conc.sort_values(["delta"], ascending=False).reset_index(drop=True)))
        sections.append("")
        sections.append(f"## Section 3: 非土曜日との比較 - {label}")
        sections.append(table_to_markdown(fri.sort_values(["spearman_r", "pair_label"], ascending=[False, True]).head(10).reset_index(drop=True)))
        sections.append("")
        sections.append(table_to_markdown(sun.sort_values(["spearman_r", "pair_label"], ascending=[False, True]).head(10).reset_index(drop=True)))
        sections.append("")

    sections.append("## Section 4: 結論")
    sections.append(table_to_markdown(_pair_compare("土").head(20)))
    sections.append("")
    sections.append(table_to_markdown(_pair_compare("金").head(20)))
    sections.append("")
    sections.append(table_to_markdown(_pair_compare("日").head(20)))
    sections.append("")
    return "\n".join(sections) + "\n"


def main() -> None:
    ensure_report_dir()
    write_text(REPORT_PATH, build_report())
    print(f"[OK] report saved: {REPORT_PATH}")


if __name__ == "__main__":
    main()
