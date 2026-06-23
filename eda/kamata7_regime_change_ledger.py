from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from eda.kamata7_verification_common import (
    REPORT_DIR,
    ensure_report_dir,
    prepare_base_frame,
    table_to_markdown,
    write_text,
)

REPORT_PATH = REPORT_DIR / "kamata7_regime_change_ledger_report.md"
FOCUS_DATE = "20251222"


def extract_machine_change_events(df: pd.DataFrame) -> pd.DataFrame:
    base = df[["date", "machine_number", "machine_name", "section"]].copy()
    base["date"] = base["date"].astype(str)
    base["machine_number"] = pd.to_numeric(base["machine_number"], errors="coerce")
    base = base.dropna(subset=["machine_number", "machine_name", "section"]).copy()
    base["machine_number"] = base["machine_number"].astype(int)
    base = base.sort_values(["machine_number", "date"]).reset_index(drop=True)
    base["prev_machine_name"] = base.groupby("machine_number")["machine_name"].shift(1)
    base["prev_date"] = base.groupby("machine_number")["date"].shift(1)
    changed = base[
        base["prev_machine_name"].notna() & (base["machine_name"] != base["prev_machine_name"])
    ].copy()
    changed["old_machine"] = changed["prev_machine_name"].astype(str)
    changed["new_machine"] = changed["machine_name"].astype(str)
    changed["date_from"] = changed["prev_date"].astype(str)
    changed["date_to"] = changed["date"].astype(str)
    return changed[
        ["machine_number", "section", "date_from", "date_to", "old_machine", "new_machine"]
    ].sort_values(["machine_number", "date_to"]).reset_index(drop=True)


def build_stability_table(df: pd.DataFrame, events: pd.DataFrame) -> pd.DataFrame:
    machines = (
        df[["section", "machine_number"]]
        .dropna(subset=["section", "machine_number"])
        .drop_duplicates()
        .copy()
    )
    changed = (
        events[["section", "machine_number"]]
        .drop_duplicates()
        .assign(changed=1)
    )
    merged = machines.merge(changed, on=["section", "machine_number"], how="left")
    merged["changed"] = merged["changed"].fillna(0).astype(int)
    out = (
        merged.groupby("section", dropna=False)
        .agg(
            total_machines=("machine_number", "nunique"),
            changed_machines=("changed", "sum"),
        )
        .reset_index()
    )
    out["stable_machines"] = out["total_machines"] - out["changed_machines"]
    out["stability_rate"] = (out["stable_machines"] / out["total_machines"] * 100).round(1)
    return out.sort_values(["stability_rate", "section"], ascending=[False, True]).reset_index(drop=True)


def build_daily_change_table(events: pd.DataFrame, all_dates: pd.Series) -> pd.DataFrame:
    if events.empty:
        return pd.DataFrame(
            columns=[
                "date",
                "n_changed_machines",
                "n_sections",
                "n_section_regimes",
                "before_days",
                "after_days",
                "before_rows",
                "after_rows",
            ]
        )
    events = events.copy()
    per_section = (
        events.groupby(["date_to", "section"], dropna=False)
        .agg(n_changed=("machine_number", "nunique"))
        .reset_index()
    )
    per_section["is_section_regime_change"] = per_section["n_changed"] >= 2
    daily = (
        per_section.groupby("date_to", dropna=False)
        .agg(
            n_changed_machines=("n_changed", "sum"),
            n_sections=("section", "nunique"),
            n_section_regimes=("is_section_regime_change", "sum"),
        )
        .reset_index()
        .rename(columns={"date_to": "date"})
    )
    unique_dates = pd.Index(sorted(pd.unique(all_dates.astype(str))))
    total_rows = len(unique_dates)
    daily["before_days"] = daily["date"].map(lambda d: int((unique_dates < d).sum()))
    daily["after_days"] = daily["date"].map(lambda d: int((unique_dates >= d).sum()))
    daily["before_rows"] = daily["before_days"]
    daily["after_rows"] = daily["after_days"]
    return daily.sort_values(["n_changed_machines", "date"], ascending=[False, True]).reset_index(drop=True)


def recommend_split_date(candidates: pd.DataFrame) -> str | None:
    if candidates.empty:
        return None
    scored = candidates.copy()
    if "n_section_regimes" not in scored.columns:
        scored["n_section_regimes"] = 0
    total = scored["before_days"] + scored["after_days"]
    scored["balance_penalty"] = (scored["before_days"] - scored["after_days"]).abs() / total.clip(lower=1)
    scored = scored.sort_values(
        ["balance_penalty", "n_changed_machines", "n_section_regimes", "date"],
        ascending=[True, False, False, True],
    )
    return str(scored.iloc[0]["date"])


def _month_section_summaries(events: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    if events.empty:
        empty = pd.DataFrame(columns=["year_month", "n_events"])
        return empty, pd.DataFrame(columns=["section", "n_events"])
    work = events.copy()
    work["year_month"] = work["date_to"].astype(str).str[:6]
    month = work.groupby("year_month", dropna=False).agg(n_events=("machine_number", "size")).reset_index()
    section = work.groupby("section", dropna=False).agg(n_events=("machine_number", "size")).reset_index()
    return (
        month.sort_values(["n_events", "year_month"], ascending=[False, True]).reset_index(drop=True),
        section.sort_values(["n_events", "section"], ascending=[False, True]).reset_index(drop=True),
    )


def build_report() -> str:
    df = prepare_base_frame(include_coords=True)
    events = extract_machine_change_events(df)
    month_summary, section_summary = _month_section_summaries(events)
    stability = build_stability_table(df, events)
    daily = build_daily_change_table(events, df["date"])
    threshold_tables = {
        threshold: daily[daily["n_changed_machines"] >= threshold].copy()
        for threshold in [5, 10, 20]
    }
    recommendation = recommend_split_date(threshold_tables[5] if not threshold_tables[5].empty else daily)
    focus = daily[daily["date"].astype(str).between("20251215", "20251229")].copy()
    focus_events = events[events["date_to"].astype(str).between("20251215", "20251229")].copy()

    lines: list[str] = []
    lines.append("# 蒲田7 機種入替台帳")
    lines.append("")
    lines.append(f"- rows={len(df):,}")
    lines.append(f"- unique_dates={df['date'].nunique():,}")
    lines.append(f"- regime_events={len(events):,}")
    lines.append(f"- 推奨分割日: {recommendation or FOCUS_DATE}")
    lines.append("")
    lines.append("## Section 1: 台番号別の機種変遷")
    lines.append(table_to_markdown(events.head(60)))
    lines.append("")
    lines.append("### 月別サマリー")
    lines.append(table_to_markdown(month_summary))
    lines.append("")
    lines.append("### セクション別サマリー")
    lines.append(table_to_markdown(section_summary))
    lines.append("")
    lines.append("## Section 2: セクション単位のレジーム変化")
    lines.append(table_to_markdown(stability))
    lines.append("")
    lines.append(f"### {FOCUS_DATE} 前後の変化")
    lines.append(table_to_markdown(focus))
    lines.append("")
    lines.append(table_to_markdown(focus_events.head(40)))
    lines.append("")
    lines.append("## Section 3: レジーム分割候補日")
    for threshold in [5, 10, 20]:
        lines.append(f"### 同一日に {threshold} 台以上入替")
        lines.append(table_to_markdown(threshold_tables[threshold].head(20)))
        lines.append("")
    if recommendation is None:
        lines.append(f"- 推奨分割日を自動選定できなかったため、フォールバック {FOCUS_DATE} を採用。")
    else:
        lines.append(
            "- 推奨分割日は、入替台数の多さと前後日数のバランスが最も良い日を採用。"
        )
    return "\n".join(lines).rstrip() + "\n"


def main() -> None:
    ensure_report_dir()
    report = build_report()
    write_text(REPORT_PATH, report)
    print(f"[OK] report saved: {REPORT_PATH}")


if __name__ == "__main__":
    main()
