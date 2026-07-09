from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import kruskal, spearmanr

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from eda import mitoya_phase10b_digit_nonevent as phase10b  # noqa: E402
from eda.mitoya_prompt_common import add_debut_phase, ensure_results_dir, load_mitoya_frame, render_markdown_table  # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


OUTPUT_DIR = Path(__file__).resolve().parents[1] / "tmp" / "mitoya_phase10c_digit_durability"
TARGET_SEGMENT = "h_jug"
TARGET_SECTIONS = ["641-657", "658-674", "675-691"]
LAST_DIGIT_ORDER = [str(i) for i in range(10)]
CORNER_BUCKET_ORDER = ["corner1", "corner2-4", "corner5-9", "corner10+"]
EVENT_CATEGORY_ORDER = ["X_DDS", "ゾロ目日", "強ゾロ目", "月末", "非イベント日"]
SPLIT_HALF_LABELS = ["front", "back"]
TARGET_DIGITS = ["4", "2"]


def _prepare_frame(df: pd.DataFrame) -> pd.DataFrame:
    work = phase10b._prepare_frame(df)  # noqa: SLF001
    work = work.copy()
    work["date_dt"] = pd.to_datetime(work.get("date"), format="%Y%m%d", errors="coerce")
    if "section" in work.columns:
        work["section"] = work["section"].astype(str)
    return work


def _target_frame(work: pd.DataFrame) -> pd.DataFrame:
    frame = phase10b._segment_frame(work, TARGET_SEGMENT)  # noqa: SLF001
    frame = frame.loc[frame["section"].astype(str).isin(TARGET_SECTIONS)].copy()
    frame = frame.loc[frame["event_category"].astype(str).eq("非イベント日")].copy()
    frame = frame.dropna(subset=["date_dt", "last_digit", "diff"]).copy()
    frame["last_digit"] = frame["last_digit"].astype("string").str.strip()
    frame["last_digit"] = frame["last_digit"].where(frame["last_digit"].isin(LAST_DIGIT_ORDER))
    frame = frame[frame["last_digit"].isin(LAST_DIGIT_ORDER)].copy()
    frame["corner_bucket"] = frame["corner_bucket"].fillna("unknown").astype(str)
    frame["machine_number"] = pd.to_numeric(frame["machine_number"], errors="coerce")
    return frame


def _digit_stats(frame: pd.DataFrame) -> pd.DataFrame:
    stats = phase10b._group_stats(frame, "last_digit", order=LAST_DIGIT_ORDER)  # noqa: SLF001
    if stats.empty:
        return pd.DataFrame(columns=["last_digit", "n", "avg_diff", "plus_rate", "rank"])
    stats = stats.copy()
    stats["rank"] = stats["avg_diff"].rank(method="min", ascending=False, na_option="bottom").astype("Int64")
    stats = stats.sort_values(["rank", "last_digit"], kind="mergesort").reset_index(drop=True)
    return stats


def _kw_summary(frame: pd.DataFrame, group_col: str = "last_digit") -> dict[str, object]:
    return phase10b._kruskal_summary(frame, group_col, order=LAST_DIGIT_ORDER)  # noqa: SLF001


def _sorted_unique_dates(frame: pd.DataFrame) -> list[pd.Timestamp]:
    dates = pd.to_datetime(frame["date_dt"], errors="coerce").dropna().drop_duplicates().sort_values()
    return [pd.Timestamp(value) for value in dates.tolist()]


def _split_dates(frame: pd.DataFrame) -> tuple[list[pd.Timestamp], list[pd.Timestamp]]:
    dates = _sorted_unique_dates(frame)
    if len(dates) < 2:
        return dates, []
    split_idx = len(dates) // 2
    if split_idx <= 0:
        split_idx = 1
    front = dates[:split_idx]
    back = dates[split_idx:]
    if not back:
        back = dates[-1:]
        front = dates[:-1]
    return front, back


def _ranking_series(frame: pd.DataFrame) -> pd.Series:
    stats = _digit_stats(frame)
    if stats.empty:
        return pd.Series(dtype=float)
    ordered = stats.set_index("last_digit")["rank"].reindex(LAST_DIGIT_ORDER)
    return pd.to_numeric(ordered, errors="coerce")


def _top3(frame: pd.DataFrame) -> list[str]:
    stats = _digit_stats(frame)
    if stats.empty:
        return []
    return stats.sort_values(["rank", "last_digit"], kind="mergesort").head(3)["last_digit"].astype(str).tolist()


def _spearman_rank(front: pd.DataFrame, back: pd.DataFrame) -> float:
    front_rank = _ranking_series(front)
    back_rank = _ranking_series(back)
    common = front_rank.dropna().index.intersection(back_rank.dropna().index)
    if len(common) < 2:
        return float("nan")
    rho, _ = spearmanr(front_rank.loc[common].to_numpy(dtype=float), back_rank.loc[common].to_numpy(dtype=float))
    return float(rho) if pd.notna(rho) else float("nan")


def _shared_top3(front: list[str], back: list[str]) -> int:
    return len(set(front) & set(back))


def _half_label_frame(frame: pd.DataFrame, half: str, dates: list[pd.Timestamp]) -> pd.DataFrame:
    date_set = {pd.Timestamp(date) for date in dates}
    sub = frame.loc[frame["date_dt"].isin(date_set)].copy()
    sub["half"] = half
    return sub


def build_split_half(work: pd.DataFrame) -> pd.DataFrame:
    front_dates, back_dates = _split_dates(work)
    front = _half_label_frame(work, "front", front_dates)
    back = _half_label_frame(work, "back", back_dates)
    front_stats = _digit_stats(front)
    back_stats = _digit_stats(back)
    front_top3 = _top3(front)
    back_top3 = _top3(back)
    rho = _spearman_rank(front, back)
    overlap = _shared_top3(front_top3, back_top3)
    front_kw = _kw_summary(front)
    back_kw = _kw_summary(back)

    rows: list[dict[str, object]] = []
    for half_name, stats, kw in [("front", front_stats, front_kw), ("back", back_stats, back_kw)]:
        for _, row in stats.iterrows():
            rows.append(
                {
                    "row_type": "digit",
                    "half": half_name,
                    "last_digit": str(row["last_digit"]),
                    "n": int(row["n"]),
                    "avg_diff": float(row["avg_diff"]),
                    "plus_rate": float(row["plus_rate"]),
                    "rank": int(row["rank"]),
                    "kw_p_value": float(kw["p_value"]),
                    "kw_epsilon_sq": float(kw["epsilon_sq"]),
                    "top3_overlap": overlap,
                    "spearman_rho": rho,
                    "top3_front": ",".join(front_top3),
                    "top3_back": ",".join(back_top3),
                }
            )
    rows.append(
        {
            "row_type": "summary",
            "half": "both",
            "last_digit": "",
            "n": int(len(work)),
            "avg_diff": float(pd.to_numeric(work["diff"], errors="coerce").mean()),
            "plus_rate": float(work["diff"].gt(0).mean() * 100),
            "rank": np.nan,
            "kw_p_value": float(front_kw["p_value"]),
            "kw_epsilon_sq": float(front_kw["epsilon_sq"]),
            "top3_overlap": overlap,
            "spearman_rho": rho,
            "top3_front": ",".join(front_top3),
            "top3_back": ",".join(back_top3),
        }
    )
    table = pd.DataFrame(rows)
    table["row_type"] = pd.Categorical(table["row_type"], categories=["digit", "summary"], ordered=True)
    table["half"] = pd.Categorical(table["half"], categories=["front", "back", "both"], ordered=True)
    table = table.sort_values(["row_type", "half", "rank", "last_digit"], kind="mergesort").reset_index(drop=True)
    return table


def _regime_split_date(work: pd.DataFrame) -> tuple[str, pd.DataFrame]:
    change_rows: list[dict[str, object]] = []
    machine_history = work.sort_values(
        ["machine_number", "date_dt", "section", "last_digit"], kind="mergesort"
    ).groupby("machine_number", dropna=False, sort=False)
    for machine_number, grp in machine_history:
        history = grp.sort_values("date_dt", kind="mergesort").copy()
        history["prev_machine_name"] = history["machine_name"].shift(1)
        history["changed"] = (
            history["machine_name"].ne(history["prev_machine_name"]) & history["prev_machine_name"].notna()
        )
        changed = history.loc[history["changed"] & history["date_dt"].notna(), ["date_dt", "machine_number"]]
        for _, row in changed.iterrows():
            change_rows.append({"date_dt": row["date_dt"], "machine_number": int(machine_number)})

    changes = pd.DataFrame(change_rows)
    if not changes.empty:
        counts = changes.groupby("date_dt", dropna=False)["machine_number"].nunique().sort_values(ascending=False)
        top_count = int(counts.iloc[0])
        candidate_dates = counts[counts == top_count].index.sort_values()
        split_date = pd.Timestamp(candidate_dates[-1]).strftime("%Y%m%d")
        return split_date, changes

    debut = add_debut_phase(work)
    debut["date_dt"] = pd.to_datetime(debut.get("date"), format="%Y%m%d", errors="coerce")
    debut_counts = (
        debut.assign(is_new_phase=debut["debut_phase"].astype(str).ne("pre_existing"))
        .groupby("date_dt", dropna=False)["is_new_phase"]
        .mean()
        .sort_values(ascending=False)
    )
    if not debut_counts.empty:
        split_date = pd.Timestamp(debut_counts.index[0]).strftime("%Y%m%d")
        return split_date, pd.DataFrame(columns=["date_dt", "machine_number"])
    dates = _sorted_unique_dates(work)
    split_date = dates[len(dates) // 2].strftime("%Y%m%d") if dates else "unknown"
    return split_date, pd.DataFrame(columns=["date_dt", "machine_number"])


def build_regime_split(work: pd.DataFrame) -> pd.DataFrame:
    split_date, changes = _regime_split_date(work)
    split_ts = pd.Timestamp(split_date)
    before = work.loc[work["date_dt"] < split_ts].copy()
    after = work.loc[work["date_dt"] >= split_ts].copy()
    before_stats = _digit_stats(before)
    after_stats = _digit_stats(after)
    before_top3 = _top3(before)
    after_top3 = _top3(after)
    rho = _spearman_rank(before, after)
    overlap = _shared_top3(before_top3, after_top3)
    before_kw = _kw_summary(before)
    after_kw = _kw_summary(after)

    rows: list[dict[str, object]] = []
    for period_name, stats, kw in [("before", before_stats, before_kw), ("after", after_stats, after_kw)]:
        for _, row in stats.iterrows():
            rows.append(
                {
                    "row_type": "digit",
                    "period": period_name,
                    "last_digit": str(row["last_digit"]),
                    "n": int(row["n"]),
                    "avg_diff": float(row["avg_diff"]),
                    "plus_rate": float(row["plus_rate"]),
                    "rank": int(row["rank"]),
                    "kw_p_value": float(kw["p_value"]),
                    "kw_epsilon_sq": float(kw["epsilon_sq"]),
                    "top3_overlap": overlap,
                    "spearman_rho": rho,
                    "split_date": split_date,
                    "top3_before": ",".join(before_top3),
                    "top3_after": ",".join(after_top3),
                }
            )
    rows.append(
        {
            "row_type": "summary",
            "period": "both",
            "last_digit": "",
            "n": int(len(work)),
            "avg_diff": float(pd.to_numeric(work["diff"], errors="coerce").mean()),
            "plus_rate": float(work["diff"].gt(0).mean() * 100),
            "rank": np.nan,
            "kw_p_value": float(before_kw["p_value"]),
            "kw_epsilon_sq": float(before_kw["epsilon_sq"]),
            "top3_overlap": overlap,
            "spearman_rho": rho,
            "split_date": split_date,
            "top3_before": ",".join(before_top3),
            "top3_after": ",".join(after_top3),
        }
    )
    table = pd.DataFrame(rows)
    table["row_type"] = pd.Categorical(table["row_type"], categories=["digit", "summary"], ordered=True)
    table["period"] = pd.Categorical(table["period"], categories=["before", "after", "both"], ordered=True)
    table = table.sort_values(["row_type", "period", "rank", "last_digit"], kind="mergesort").reset_index(drop=True)
    return table


def _machine_stats(frame: pd.DataFrame, digit: str) -> pd.DataFrame:
    sub = frame.loc[frame["last_digit"].astype(str).eq(digit)].copy()
    if sub.empty:
        return pd.DataFrame(columns=["machine_number", "machine_name", "n", "avg_diff", "share"])
    stats = (
        sub.groupby(["machine_number", "machine_name"], dropna=False)
        .agg(n=("diff", "size"), avg_diff=("diff", "mean"))
        .reset_index()
        .sort_values(["avg_diff", "machine_number"], ascending=[False, True], kind="mergesort")
        .reset_index(drop=True)
    )
    total = float(stats["avg_diff"].sum())
    stats["share"] = stats["avg_diff"] / total * 100 if total > 0 else np.nan
    stats["rank"] = np.arange(1, len(stats) + 1)
    return stats


def build_machine_dependency(work: pd.DataFrame) -> pd.DataFrame:
    frame = _target_frame(work)
    rows: list[dict[str, object]] = []
    for digit in TARGET_DIGITS:
        stats = _machine_stats(frame, digit)
        if stats.empty:
            continue
        total = float(stats["avg_diff"].sum())
        top1 = stats.head(1)
        top2 = stats.head(2)
        top1_share = float(top1["avg_diff"].sum() / total * 100) if total > 0 else np.nan
        top2_share = float(top2["avg_diff"].sum() / total * 100) if total > 0 else np.nan
        if len(stats) <= 1:
            excl_top1 = pd.DataFrame(columns=stats.columns)
        else:
            excl_top1 = stats.iloc[1:].copy()
        if len(stats) <= 2:
            excl_top2 = pd.DataFrame(columns=stats.columns)
        else:
            excl_top2 = stats.iloc[2:].copy()
        rows.append(
            {
                "row_type": "summary",
                "digit": digit,
                "machine_number": "",
                "machine_name": "",
                "n": int(stats["n"].sum()),
                "avg_diff": float(stats["avg_diff"].mean()),
                "top1_machine": str(top1.iloc[0]["machine_number"]) if not top1.empty else "",
                "top1_avg_diff": float(top1.iloc[0]["avg_diff"]) if not top1.empty else np.nan,
                "top1_share": top1_share,
                "top2_share": top2_share,
                "full_avg_diff": float(frame.loc[frame["last_digit"].astype(str).eq(digit), "diff"].mean()),
                "excl_top1_avg_diff": float(excl_top1["avg_diff"].mean()) if not excl_top1.empty else np.nan,
                "excl_top2_avg_diff": float(excl_top2["avg_diff"].mean()) if not excl_top2.empty else np.nan,
            }
        )
        for _, row in stats.iterrows():
            rows.append(
                {
                    "row_type": "machine",
                    "digit": digit,
                    "machine_number": int(row["machine_number"]),
                    "machine_name": str(row["machine_name"]),
                    "n": int(row["n"]),
                    "avg_diff": float(row["avg_diff"]),
                    "top1_machine": "",
                    "top1_avg_diff": np.nan,
                    "top1_share": top1_share,
                    "top2_share": top2_share,
                    "full_avg_diff": float(frame.loc[frame["last_digit"].astype(str).eq(digit), "diff"].mean()),
                    "excl_top1_avg_diff": float(excl_top1["avg_diff"].mean()) if not excl_top1.empty else np.nan,
                    "excl_top2_avg_diff": float(excl_top2["avg_diff"].mean()) if not excl_top2.empty else np.nan,
                }
            )
    table = pd.DataFrame(rows)
    table["row_type"] = pd.Categorical(table["row_type"], categories=["summary", "machine"], ordered=True)
    table["digit"] = pd.Categorical(table["digit"], categories=TARGET_DIGITS, ordered=True)
    table = table.sort_values(
        ["digit", "row_type", "avg_diff"], ascending=[True, True, False], kind="mergesort"
    ).reset_index(drop=True)
    return table


def build_corner24_split_half(work: pd.DataFrame) -> pd.DataFrame:
    frame = _target_frame(work)
    frame = frame.loc[frame["corner_bucket"].astype(str).eq("corner2-4")].copy()
    front_dates, back_dates = _split_dates(frame)
    front = _half_label_frame(frame, "front", front_dates)
    back = _half_label_frame(frame, "back", back_dates)
    front_stats = _digit_stats(front)
    back_stats = _digit_stats(back)
    front_top3 = _top3(front)
    back_top3 = _top3(back)
    rho = _spearman_rank(front, back)
    overlap = _shared_top3(front_top3, back_top3)
    front_kw = _kw_summary(front)
    back_kw = _kw_summary(back)

    rows: list[dict[str, object]] = []
    for half_name, stats, kw in [("front", front_stats, front_kw), ("back", back_stats, back_kw)]:
        for _, row in stats.iterrows():
            rows.append(
                {
                    "row_type": "digit",
                    "half": half_name,
                    "last_digit": str(row["last_digit"]),
                    "n": int(row["n"]),
                    "avg_diff": float(row["avg_diff"]),
                    "plus_rate": float(row["plus_rate"]),
                    "rank": int(row["rank"]),
                    "kw_p_value": float(kw["p_value"]),
                    "kw_epsilon_sq": float(kw["epsilon_sq"]),
                    "top3_overlap": overlap,
                    "spearman_rho": rho,
                    "top3_front": ",".join(front_top3),
                    "top3_back": ",".join(back_top3),
                }
            )
    rows.append(
        {
            "row_type": "summary",
            "half": "both",
            "last_digit": "",
            "n": int(len(frame)),
            "avg_diff": float(pd.to_numeric(frame["diff"], errors="coerce").mean()),
            "plus_rate": float(frame["diff"].gt(0).mean() * 100),
            "rank": np.nan,
            "kw_p_value": float(front_kw["p_value"]),
            "kw_epsilon_sq": float(front_kw["epsilon_sq"]),
            "top3_overlap": overlap,
            "spearman_rho": rho,
            "top3_front": ",".join(front_top3),
            "top3_back": ",".join(back_top3),
        }
    )
    table = pd.DataFrame(rows)
    table["row_type"] = pd.Categorical(table["row_type"], categories=["digit", "summary"], ordered=True)
    table["half"] = pd.Categorical(table["half"], categories=["front", "back", "both"], ordered=True)
    table = table.sort_values(["row_type", "half", "rank", "last_digit"], kind="mergesort").reset_index(drop=True)
    return table


def build_summary(
    split_half: pd.DataFrame, regime_split: pd.DataFrame, machine_dependency: pd.DataFrame, corner24: pd.DataFrame
) -> pd.DataFrame:
    split_overlap = int(split_half.loc[split_half["row_type"].eq("summary"), "top3_overlap"].iloc[0])
    regime_overlap = int(regime_split.loc[regime_split["row_type"].eq("summary"), "top3_overlap"].iloc[0])
    corner_overlap = int(corner24.loc[corner24["row_type"].eq("summary"), "top3_overlap"].iloc[0])
    machine_summary = machine_dependency.loc[
        machine_dependency["row_type"].eq("summary"), ["digit", "top1_share", "top2_share"]
    ].copy()
    machine_top2 = float(machine_summary["top2_share"].max())
    machine_note = ", ".join(
        f"d{row.digit}: top1={row.top1_share:.1f}%, top2={row.top2_share:.1f}%"
        for row in machine_summary.itertuples(index=False)
    )
    regime_before = str(regime_split.loc[regime_split["row_type"].eq("summary"), "top3_before"].iloc[0])
    regime_after = str(regime_split.loc[regime_split["row_type"].eq("summary"), "top3_after"].iloc[0])
    rows = []
    rows.append(
        {
            "test": "split_half",
            "target": "h_jug non-event last_digit",
            "pass/fail": "PASS" if split_overlap >= 2 else "FAIL",
            "note": f"top3_overlap={split_overlap}; rho={split_half.loc[split_half['row_type'].eq('summary'), 'spearman_rho'].iloc[0]:.3f}",
        }
    )
    rows.append(
        {
            "test": "regime",
            "target": "h_jug non-event last_digit",
            "pass/fail": "PASS" if regime_overlap >= 2 else "FAIL",
            "note": f"split_date={regime_split.loc[regime_split['row_type'].eq('summary'), 'split_date'].iloc[0]}; before_top3={regime_before}; after_top3={regime_after}",
        }
    )
    if pd.isna(machine_top2):
        machine_status = "WARN"
        machine_note = "top2_share unavailable"
    elif machine_top2 < 30:
        machine_status = "PASS"
        machine_note = f"top2_share={machine_top2:.1f}%"
    elif machine_top2 >= 50:
        machine_status = "FAIL"
        machine_note = f"top2_share={machine_top2:.1f}%"
    else:
        machine_status = "WARN"
        machine_note = f"top2_share={machine_top2:.1f}% gray zone"
    rows.append(
        {
            "test": "machine_dependency",
            "target": "d4/d2 in h_jug non-event",
            "pass/fail": machine_status,
            "note": f"{machine_note}; max_top2_share={machine_top2:.1f}%",
        }
    )
    rows.append(
        {
            "test": "corner24",
            "target": "corner2-4 non-event last_digit",
            "pass/fail": "PASS" if corner_overlap >= 2 else "FAIL",
            "note": f"top3_overlap={corner_overlap}; rho={corner24.loc[corner24['row_type'].eq('summary'), 'spearman_rho'].iloc[0]:.3f}",
        }
    )
    return pd.DataFrame(rows, columns=["test", "target", "pass/fail", "note"])


def build_report(artifacts: dict[str, pd.DataFrame | str], *, source_latest_date: str, regime_split_date: str) -> str:
    lines = [
        "# Mitoya Phase 10c: digit durability",
        "",
        f"- source_latest_date: {source_latest_date}",
        f"- regime_split_date: {regime_split_date}",
        "- target_segment: h_jug",
        "- target_sections: 641-657, 658-674, 675-691",
        "- filters: non_event only, games >= 1000",
        "",
        "## split_half",
        "",
        render_markdown_table(artifacts["split_half"].head(30)) if not artifacts["split_half"].empty else "_no rows_",
        "",
        "## regime_split",
        "",
        render_markdown_table(artifacts["regime_split"].head(30))
        if not artifacts["regime_split"].empty
        else "_no rows_",
        "",
        "## machine_dependency",
        "",
        render_markdown_table(artifacts["machine_dependency"].head(40))
        if not artifacts["machine_dependency"].empty
        else "_no rows_",
        "",
        "## corner24_split_half",
        "",
        render_markdown_table(artifacts["corner24_split_half"].head(30))
        if not artifacts["corner24_split_half"].empty
        else "_no rows_",
        "",
        "## durability_summary",
        "",
        render_markdown_table(artifacts["durability_summary"])
        if not artifacts["durability_summary"].empty
        else "_no rows_",
        "",
    ]
    return "\n".join(lines).rstrip() + "\n"


def build_all_artifacts(df: pd.DataFrame) -> dict[str, pd.DataFrame | str]:
    work = _prepare_frame(df)
    target = _target_frame(work)
    source_dates = (
        pd.to_datetime(work.get("date_dt"), errors="coerce")
        if "date_dt" in work.columns
        else pd.Series(dtype="datetime64[ns]")
    )
    latest_date = source_dates.max() if not source_dates.empty else pd.NaT
    source_latest_date = latest_date.strftime("%Y%m%d") if pd.notna(latest_date) else "unknown"

    split_half = build_split_half(target)
    regime_split = build_regime_split(target)
    regime_split_date = (
        str(regime_split.loc[regime_split["row_type"].eq("summary"), "split_date"].iloc[0])
        if not regime_split.empty
        else "unknown"
    )
    machine_dependency = build_machine_dependency(work)
    corner24_split_half = build_corner24_split_half(target)
    durability_summary = build_summary(split_half, regime_split, machine_dependency, corner24_split_half)

    artifacts: dict[str, pd.DataFrame | str] = {
        "split_half": split_half,
        "regime_split": regime_split,
        "machine_dependency": machine_dependency,
        "corner24_split_half": corner24_split_half,
        "durability_summary": durability_summary,
    }
    artifacts["report"] = build_report(
        artifacts, source_latest_date=source_latest_date, regime_split_date=regime_split_date
    )
    return artifacts


def save_outputs(artifacts: dict[str, pd.DataFrame | str], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    artifacts["split_half"].to_csv(output_dir / "split_half.csv", index=False, encoding="utf-8-sig")
    artifacts["regime_split"].to_csv(output_dir / "regime_split.csv", index=False, encoding="utf-8-sig")
    artifacts["machine_dependency"].to_csv(output_dir / "machine_dependency.csv", index=False, encoding="utf-8-sig")
    artifacts["corner24_split_half"].to_csv(output_dir / "corner24_split_half.csv", index=False, encoding="utf-8-sig")
    artifacts["durability_summary"].to_csv(output_dir / "durability_summary.csv", index=False, encoding="utf-8-sig")
    (output_dir / "report.md").write_text(str(artifacts["report"]), encoding="utf-8")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    ensure_results_dir()
    args = parse_args(argv)
    df = load_mitoya_frame(join_layout=True)
    artifacts = build_all_artifacts(df)
    save_outputs(artifacts, args.output_dir)
    print(f"Wrote {args.output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
