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

from eda.core import HALL_EVENT_DIGITS
from eda.kamata7_verification_common import (
    DOW_ORDER,
    REPORT_DIR,
    attach_floor_side,
    attach_seg,
    cohen_d,
    ensure_report_dir,
    mann_whitney,
    pct,
    prepare_base_frame,
    signed,
    table_to_markdown,
    write_text,
)

REPORT_PATH = REPORT_DIR / "kamata7_eventday_revalidation_report.md"


def _old_is_x_day(df: pd.DataFrame) -> pd.Series:
    dd = pd.to_numeric(df["dd"], errors="coerce")
    return (
        dd.isin([1, 7, 11, 17, 22, 27, 31])
        | dd.isin([30, 31])
    ).astype(int)


def _prepare_frame() -> pd.DataFrame:
    df = prepare_base_frame(include_floor_side=True)
    df = attach_seg(df)
    df["date"] = df["date"].astype(str)
    df["dd"] = pd.to_numeric(df["date"].str[6:8], errors="coerce").astype(int)
    df["month"] = pd.to_numeric(df["date"].str[4:6], errors="coerce").astype(int)
    df["is_x_day_old"] = _old_is_x_day(df)
    df["is_x_day_new"] = df["is_x_day"].astype(int)
    df["is_mmdd_zorome"] = (df["month"] == df["dd"]).astype(int)
    month_end = pd.to_datetime(df["date"], format="%Y%m%d").dt.days_in_month
    df["is_month_end"] = (df["dd"] == month_end).astype(int)
    return df.reset_index(drop=True)


def _metric_rows(df: pd.DataFrame, flag_col: str, group_cols: list[str]) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for key, grp in df.groupby(group_cols, dropna=False):
        if isinstance(key, tuple):
            row = {col: val for col, val in zip(group_cols, key)}
        else:
            row = {group_cols[0]: key}
        evt = grp[grp[flag_col] == 1]
        non = grp[grp[flag_col] == 0]
        if len(evt) < 5 or len(non) < 5:
            continue
        u_diff, p_diff = mann_whitney(evt["diff"].to_numpy(), non["diff"].to_numpy())
        u_plus, p_plus = mann_whitney(evt["plus"].to_numpy(), non["plus"].to_numpy())
        u_104, p_104 = mann_whitney(evt["hit104"].to_numpy(), non["hit104"].to_numpy())
        row.update(
            {
                "evt_n": len(evt),
                "non_n": len(non),
                "evt_diff": round(float(evt["diff"].mean()), 1),
                "non_diff": round(float(non["diff"].mean()), 1),
                "evt_plus": round(float(evt["plus"].mean() * 100), 1),
                "non_plus": round(float(non["plus"].mean() * 100), 1),
                "evt_hit104": round(float(evt["hit104"].mean() * 100), 1),
                "non_hit104": round(float(non["hit104"].mean() * 100), 1),
                "delta_diff": round(float(evt["diff"].mean() - non["diff"].mean()), 1),
                "delta_plus": round(float((evt["plus"].mean() - non["plus"].mean()) * 100), 1),
                "delta_hit104": round(float((evt["hit104"].mean() - non["hit104"].mean()) * 100), 1),
                "mw_p_diff": round(float(p_diff), 6) if not pd.isna(p_diff) else np.nan,
                "mw_p_plus": round(float(p_plus), 6) if not pd.isna(p_plus) else np.nan,
                "mw_p_hit104": round(float(p_104), 6) if not pd.isna(p_104) else np.nan,
                "cohen_d_diff": round(float(cohen_d(evt["diff"].to_numpy(), non["diff"].to_numpy())), 4),
            }
        )
        rows.append(row)
    return pd.DataFrame(rows)


def _coverage_table(df: pd.DataFrame) -> pd.DataFrame:
    temp = (
        df.assign(year_month=pd.to_datetime(df["date"], format="%Y%m%d").dt.strftime("%Y%m"))
        .groupby(["year_month", "date"], dropna=False)
        .agg(event_day=("is_x_day_new", "max"))
        .reset_index()
    )
    by_month = (
        temp.groupby("year_month", dropna=False)
        .agg(total_days=("date", "nunique"), event_days=("event_day", "sum"))
        .reset_index()
    )
    rows = (
        df.assign(year_month=pd.to_datetime(df["date"], format="%Y%m%d").dt.strftime("%Y%m"))
        .groupby("year_month", dropna=False)
        .agg(total_rows=("date", "size"), event_rows=("is_x_day_new", "sum"))
        .reset_index()
    )
    by_month = by_month.merge(rows, on="year_month", how="left")
    by_month["event_day_rate"] = (by_month["event_days"] / by_month["total_days"] * 100).round(1)
    return by_month


def _changed_dates(df: pd.DataFrame) -> pd.DataFrame:
    changed = df[df["is_x_day_old"] != df["is_x_day_new"]].copy()
    changed["category"] = np.select(
        [
            (changed["dd"] == 21) & (changed["is_x_day_new"] == 1),
            (changed["is_mmdd_zorome"] == 1) & (changed["is_x_day_old"] == 0),
            (changed["is_month_end"] == 1) & (changed["is_x_day_old"] == 0),
            (changed["is_x_day_old"] == 1) & (changed["is_month_end"] == 0) & (changed["dd"].eq(30)),
        ],
        [
            "DD21追加分",
            "強ゾロ目追加分",
            "動的月末で新規追加",
            "旧ハードコードの誤検出",
        ],
        default="その他",
    )
    return (
        changed.groupby(["date", "category"], dropna=False)
        .agg(rows=("machine_number", "size"))
        .reset_index()
        .sort_values(["category", "date"])
    )


def build_report() -> str:
    df = _prepare_frame()
    changed = _changed_dates(df)
    coverage = _coverage_table(df)
    overall = _metric_rows(df, "is_x_day_new", ["seg", "floor_side"])
    by_weekday_new = _metric_rows(df, "is_x_day_new", ["day_of_week"])
    by_weekday_old = _metric_rows(df.assign(is_x_day_new=df["is_x_day_old"]), "is_x_day_new", ["day_of_week"])
    overall_all = _metric_rows(df.assign(all_flag=1), "is_x_day_new", ["all_flag"])
    old_new = pd.DataFrame(
        [
            {
                "flag": "new",
                "event_rows": int(df["is_x_day_new"].sum()),
                "non_rows": int((df["is_x_day_new"] == 0).sum()),
                "event_days": int(df.groupby("date")["is_x_day_new"].max().sum()),
            },
            {
                "flag": "old",
                "event_rows": int(df["is_x_day_old"].sum()),
                "non_rows": int((df["is_x_day_old"] == 0).sum()),
                "event_days": int(df.groupby("date")["is_x_day_old"].max().sum()),
            },
        ]
    )
    old_vs_new = pd.DataFrame([
        {
            "comparison": "new_vs_old",
            "delta_event_rows": int(df["is_x_day_new"].sum() - df["is_x_day_old"].sum()),
            "delta_event_days": int(df.groupby("date")["is_x_day_new"].max().sum() - df.groupby("date")["is_x_day_old"].max().sum()),
        }
    ])
    compare = by_weekday_new.merge(
        by_weekday_old,
        on="day_of_week",
        how="outer",
        suffixes=("_new", "_old"),
    )
    compare["delta_diff_change"] = compare["delta_diff_new"] - compare["delta_diff_old"]

    lines: list[str] = []
    lines.append("# イベント日定義修正後のEDA再検証")
    lines.append("")
    lines.append("## Section 1: イベント日カバレッジ確認")
    lines.append(table_to_markdown(old_new))
    lines.append("")
    lines.append(table_to_markdown(old_vs_new))
    lines.append("")
    lines.append(table_to_markdown(coverage))
    lines.append("")
    lines.append("### 差分日付")
    lines.append(table_to_markdown(changed.head(60)))
    lines.append("")
    lines.append("## Section 2: イベント日効果の再計算")
    lines.append(table_to_markdown(overall_all))
    lines.append("")
    lines.append(table_to_markdown(overall.sort_values(["seg", "floor_side"]).reset_index(drop=True)))
    lines.append("")
    lines.append(table_to_markdown(by_weekday_new.sort_values("day_of_week").reset_index(drop=True)))
    lines.append("")
    lines.append("## Section 3: 旧定義との効果量変化")
    lines.append(table_to_markdown(compare[["day_of_week", "evt_diff_new", "non_diff_new", "delta_diff_new", "evt_diff_old", "non_diff_old", "delta_diff_old", "delta_diff_change"]].sort_values("day_of_week").reset_index(drop=True)))
    lines.append("")
    return "\n".join(lines) + "\n"


def main() -> None:
    ensure_report_dir()
    write_text(REPORT_PATH, build_report())
    print(f"[OK] report saved: {REPORT_PATH}")


if __name__ == "__main__":
    main()
