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
    REPORT_DIR,
    attach_seg,
    bootstrap_mean_ci,
    ensure_report_dir,
    mann_whitney,
    prepare_base_frame,
    table_to_markdown,
    write_text,
)

REPORT_PATH = REPORT_DIR / "kamata7_2f_dd_kakuban_verification_report.md"
CSV_PATH = REPORT_DIR / "kamata7_2f_triple_filter_candidates.csv"


def _prepare_frame() -> pd.DataFrame:
    df = prepare_base_frame(include_floor_side=True)
    df = attach_seg(df)
    coords = load_coords().copy()
    coords = coords.drop_duplicates(subset=["machine_number"], keep="first")
    coords["kakuban_rank"] = np.where(
        pd.to_numeric(coords["rank_from_min"], errors="coerce") == 1,
        "角1",
        np.where(
            pd.to_numeric(coords["rank_from_min"], errors="coerce") == 2,
            "角2",
            np.where(
                pd.to_numeric(coords["rank_from_max"], errors="coerce") == 1,
                "角N",
                np.where(
                    pd.to_numeric(coords["rank_from_max"], errors="coerce") == 2,
                    "角N-1",
                    "中間",
                ),
            ),
        ),
    )
    df = df.merge(coords[["machine_number", "section", "section_min", "display_x", "kakuban_rank"]], on="machine_number", how="inner")
    df["kakuban_rank"] = pd.Categorical(df["kakuban_rank"], categories=["角1", "角2", "中間", "角N-1", "角N"], ordered=True)
    df["machine_digit"] = df["machine_digit"].astype(str)
    df["dd"] = pd.to_numeric(df["date"].str[6:8], errors="coerce").astype(int)
    return df.reset_index(drop=True)


def _dd_kakuban_table(df: pd.DataFrame) -> pd.DataFrame:
    out = (
        df.groupby(["dd", "kakuban_rank"], dropna=False)
        .agg(n=("diff", "size"), avg_diff=("diff", "mean"), plus_rate=("plus", "mean"), hit104_rate=("hit104", "mean"))
        .reset_index()
    )
    out = out[out["n"] > 0].copy()
    out["avg_diff"] = out["avg_diff"].round(0)
    out["plus_rate"] = (out["plus_rate"] * 100).round(1)
    out["hit104_rate"] = (out["hit104_rate"] * 100).round(1)
    return out.sort_values(["avg_diff", "n"], ascending=[False, False]).reset_index(drop=True)


def _triple_candidates(df: pd.DataFrame) -> pd.DataFrame:
    sub = df[(df["floor"] == "2F") & (df["side"] == "L") & (df["seg"] == "N")].copy()
    cand = (
        sub.groupby(["dd", "kakuban_rank", "machine_digit"], dropna=False)
        .agg(n=("diff", "size"), avg_diff=("diff", "mean"), plus_rate=("plus", "mean"), hit104_rate=("hit104", "mean"))
        .reset_index()
    )
    cand = cand[cand["n"] >= 15].copy()
    if cand.empty:
        return cand
    cand["avg_diff"] = cand["avg_diff"].round(0)
    cand["plus_rate"] = (cand["plus_rate"] * 100).round(1)
    cand["hit104_rate"] = (cand["hit104_rate"] * 100).round(1)
    return cand.sort_values(["avg_diff", "n"], ascending=[False, False]).reset_index(drop=True)


def _split_dates(df: pd.DataFrame) -> tuple[pd.Index, pd.Index]:
    dates = pd.Index(sorted(pd.unique(df["date"].astype(str))))
    mid = len(dates) // 2
    return dates[:mid], dates[mid:]


def _candidate_stability(df: pd.DataFrame, candidates: pd.DataFrame) -> pd.DataFrame:
    if candidates.empty:
        return pd.DataFrame()
    first_dates, second_dates = _split_dates(df)
    sub = df[(df["floor"] == "2F") & (df["side"] == "L") & (df["seg"] == "N")].copy()
    rows: list[dict[str, object]] = []
    for _, cand in candidates.head(5).iterrows():
        mask = (
            (sub["dd"] == cand["dd"])
            & (sub["kakuban_rank"] == cand["kakuban_rank"])
            & (sub["machine_digit"] == str(cand["machine_digit"]))
        )
        vals = sub[mask]["diff"].dropna().to_numpy()
        ci_lo, ci_hi = bootstrap_mean_ci(vals, n_boot=1000)
        first = sub[mask & sub["date"].isin(first_dates)]
        second = sub[mask & sub["date"].isin(second_dates)]
        rows.append(
            {
                "dd": int(cand["dd"]),
                "kakuban_rank": cand["kakuban_rank"],
                "machine_digit": str(cand["machine_digit"]),
                "n": int(cand["n"]),
                "avg_diff": float(cand["avg_diff"]),
                "ci_lo": round(float(ci_lo), 1) if not pd.isna(ci_lo) else np.nan,
                "ci_hi": round(float(ci_hi), 1) if not pd.isna(ci_hi) else np.nan,
                "first_n": len(first),
                "second_n": len(second),
                "top10_first": False,
                "top10_second": False,
            }
        )
    out = pd.DataFrame(rows)
    if out.empty:
        return out
    first_rank = _triple_candidates(sub[sub["date"].isin(first_dates)]).head(10)
    second_rank = _triple_candidates(sub[sub["date"].isin(second_dates)]).head(10)
    for idx, row in out.iterrows():
        key = (int(row["dd"]), str(row["kakuban_rank"]), str(row["machine_digit"]))
        out.loc[idx, "top10_first"] = any(
            (int(r["dd"]), str(r["kakuban_rank"]), str(r["machine_digit"])) == key for _, r in first_rank.iterrows()
        )
        out.loc[idx, "top10_second"] = any(
            (int(r["dd"]), str(r["kakuban_rank"]), str(r["machine_digit"])) == key for _, r in second_rank.iterrows()
        )
    out["stable"] = ((out["ci_lo"] > 0) & (out["top10_first"]) & (out["top10_second"]))
    return out


def build_report() -> str:
    df = _prepare_frame()
    section1 = _dd_kakuban_table(df[df["floor"] == "2F"])
    section2_l = _dd_kakuban_table(df[(df["floor"] == "2F") & (df["side"] == "L")])
    section2_r = _dd_kakuban_table(df[(df["floor"] == "2F") & (df["side"] == "R")])
    candidates = _triple_candidates(df)
    stability = _candidate_stability(df, candidates)
    if not candidates.empty:
        candidates.to_csv(CSV_PATH, index=False, encoding="utf-8-sig")

    lines: list[str] = []
    lines.append("# DD×角番の2F検証")
    lines.append("")
    lines.append("## Section 1: 2F全体のDD×角番")
    lines.append(table_to_markdown(section1.head(20)))
    lines.append("")
    lines.append("## Section 2: 2F_L vs 2F_R の分離")
    lines.append("### 2F_L")
    lines.append(table_to_markdown(section2_l.head(20)))
    lines.append("")
    lines.append("### 2F_R")
    lines.append(table_to_markdown(section2_r.head(20)))
    lines.append("")
    lines.append("## Section 3: 2F_L_N の三重フィルタ候補")
    lines.append(table_to_markdown(candidates.head(20)))
    lines.append("")
    lines.append("## Section 4: 安定性検証（多重比較を考慮）")
    lines.append(table_to_markdown(stability))
    lines.append("")
    lines.append("- 探索結果は記述的に扱い、安定候補のみを実用候補とする。")
    return "\n".join(lines) + "\n"


def main() -> None:
    ensure_report_dir()
    write_text(REPORT_PATH, build_report())
    print(f"[OK] report saved: {REPORT_PATH}")
    if CSV_PATH.exists():
        print(f"[OK] csv saved: {CSV_PATH}")


if __name__ == "__main__":
    main()
