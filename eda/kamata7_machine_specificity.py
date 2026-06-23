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

from eda.kamata7_verification_common import (
    REPORT_DIR,
    ensure_report_dir,
    mann_whitney,
    prepare_base_frame,
    table_to_markdown,
    write_text,
)

REPORT_PATH = REPORT_DIR / "kamata7_machine_specificity_report.md"
KAKUBAN_ORDER = ["角1", "角2", "中間", "角N-1", "角N"]


def _add_kakuban_rank(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    left = pd.to_numeric(out["rank_from_min"], errors="coerce")
    right = pd.to_numeric(out["rank_from_max"], errors="coerce")
    out["kakuban_rank"] = np.select(
        [left == 1, left == 2, right == 1, right == 2],
        ["角1", "角2", "角N", "角N-1"],
        default="中間",
    )
    out["kakuban_rank"] = pd.Categorical(out["kakuban_rank"], categories=KAKUBAN_ORDER, ordered=True)
    return out


def _prepare_frame() -> pd.DataFrame:
    df = prepare_base_frame(include_floor_side=True, include_coords=True)
    df = _add_kakuban_rank(df)
    df["day_of_week"] = df["day_of_week"].astype(str)
    df["machine_digit"] = df["machine_digit"].astype(str)
    df["machine_zorome"] = pd.to_numeric(df["machine_zorome"], errors="coerce").fillna(0).astype(int)
    df["dd"] = pd.to_numeric(df.get("dd", df["date"].str[6:8]), errors="coerce")
    return df


def compute_top_machine_share(frame: pd.DataFrame, top_n: int = 1) -> float:
    if frame.empty:
        return np.nan
    per_machine = frame.groupby("machine_number", dropna=False)["diff"].sum().sort_values(ascending=False)
    total_diff = float(per_machine.sum())
    if total_diff <= 0:
        return np.nan
    return float(per_machine.head(top_n).sum() / total_diff * 100)


def _kruskal_p(frame: pd.DataFrame, axis_col: str) -> float:
    groups = [grp["diff"].dropna().to_numpy() for _, grp in frame.groupby(axis_col, dropna=False) if len(grp) >= 5]
    if len(groups) < 2:
        return np.nan
    _, p_value = stats.kruskal(*groups)
    return float(p_value)


def _binary_p(frame: pd.DataFrame, flag_col: str) -> float:
    pos = frame[frame[flag_col] == 1]["diff"].to_numpy()
    neg = frame[frame[flag_col] == 0]["diff"].to_numpy()
    _, p_value = mann_whitney(pos, neg)
    return float(p_value) if not pd.isna(p_value) else np.nan


def _classify_signal(top2_share: float, p_after_top2: float, *, sample_shortage: bool = False) -> str:
    if sample_shortage or pd.isna(top2_share) or pd.isna(p_after_top2):
        return "未判定"
    if top2_share < 30 and p_after_top2 < 0.10:
        return "構造シグナル"
    if top2_share >= 50 or p_after_top2 >= 0.30:
        return "少数台依存"
    return "未判定"


def _focal_rows(frame: pd.DataFrame, law_id: str) -> tuple[pd.DataFrame, str]:
    if law_id == "L1":
        return frame[frame["machine_digit"] == "6"].copy(), "d6"
    if law_id == "L2":
        by_digit = (
            frame[frame["machine_digit"].isin(["8", "9"])]
            .groupby("machine_digit")["diff"]
            .mean()
            .sort_values(ascending=False)
        )
        focal_digit = str(by_digit.index[0]) if not by_digit.empty else "8"
        return frame[frame["machine_digit"] == focal_digit].copy(), focal_digit
    if law_id == "L3":
        return frame[frame["kakuban_rank"] == "中間"].copy(), "中間"
    if law_id == "L4":
        return frame[frame["is_target_day"] == 1].copy(), "土曜"
    if law_id in {"L5", "L6"}:
        return frame[frame["machine_zorome"] == 1].copy(), "台末尾ゾロ目"
    raise ValueError(law_id)


def _remove_top_machines(frame: pd.DataFrame, focal: pd.DataFrame, top_n: int) -> pd.DataFrame:
    if focal.empty:
        return frame.copy()
    top_machines = (
        focal.groupby("machine_number", dropna=False)["diff"]
        .sum()
        .sort_values(ascending=False)
        .head(top_n)
        .index
    )
    return frame[~frame["machine_number"].isin(top_machines)].copy()


def _evaluate_law(
    law_id: str,
    label: str,
    frame: pd.DataFrame,
    axis_col: str,
    *,
    binary: bool = False,
    sample_shortage: bool = False,
) -> dict[str, object]:
    focal, focal_label = _focal_rows(frame, law_id)
    share1 = compute_top_machine_share(focal, top_n=1)
    share2 = compute_top_machine_share(focal, top_n=2)
    p_before = _binary_p(frame, axis_col) if binary else _kruskal_p(frame, axis_col)
    after_top1 = _remove_top_machines(frame, focal, 1)
    after_top2 = _remove_top_machines(frame, focal, 2)
    p_after_top1 = _binary_p(after_top1, axis_col) if binary else _kruskal_p(after_top1, axis_col)
    p_after_top2 = _binary_p(after_top2, axis_col) if binary else _kruskal_p(after_top2, axis_col)
    verdict = _classify_signal(share2, p_after_top2, sample_shortage=sample_shortage)
    return {
        "law": law_id,
        "label": label,
        "focal": focal_label,
        "n_rows": len(frame),
        "top1_share": round(share1, 1) if not pd.isna(share1) else np.nan,
        "top2_share": round(share2, 1) if not pd.isna(share2) else np.nan,
        "p_before": round(p_before, 6) if not pd.isna(p_before) else np.nan,
        "p_after_top1": round(p_after_top1, 6) if not pd.isna(p_after_top1) else np.nan,
        "p_after_top2": round(p_after_top2, 6) if not pd.isna(p_after_top2) else np.nan,
        "判定": verdict,
        "note": "サンプル不足" if sample_shortage else ("diff合計<=0" if pd.isna(share2) else ""),
    }


def _metrics_table(df: pd.DataFrame) -> pd.DataFrame:
    l1 = df[(df["floor_side"] == "2F_L") & (df["seg"] == "N")].copy()
    l2 = df[(df["floor_side"] == "3F_L") & (df["seg"] == "N")].copy()
    l3 = df.copy()
    l4 = df[df["seg"] == "N"].copy()
    l4["is_target_day"] = (l4["day_of_week"] == "土").astype(int)
    l5 = df[df["dd"] == 11].copy()
    l6 = df.copy()

    rows = [
        _evaluate_law("L1", "2F_L_N d6最強", l1, "machine_digit"),
        _evaluate_law("L2", "3F_L_N d8/d9最強", l2, "machine_digit"),
        _evaluate_law("L3", "角番中間台優位", l3, "kakuban_rank"),
        _evaluate_law("L4", "AT群×土曜 +1.71pt", l4, "is_target_day", binary=True),
        _evaluate_law("L5", "DD11ゾロ目 +210", l5, "machine_zorome", binary=True, sample_shortage=len(l5) < 30),
        _evaluate_law("L6", "台末尾ゾロ目 全体+49", l6, "machine_zorome", binary=True),
    ]
    return pd.DataFrame(rows)


def _iron_candidates(df: pd.DataFrame) -> pd.DataFrame:
    out = (
        df.groupby(["machine_number", "section", "floor_side", "seg"], dropna=False)
        .agg(
            n_days=("date", "nunique"),
            pos_rate=("plus", "mean"),
            median_diff=("diff", "median"),
            avg_diff=("diff", "mean"),
        )
        .reset_index()
    )
    out["pos_rate"] = (out["pos_rate"] * 100).round(1)
    out["median_diff"] = out["median_diff"].round(1)
    out["avg_diff"] = out["avg_diff"].round(1)
    out = out[(out["pos_rate"] >= 60) | (out["median_diff"] >= 0)].copy()
    return out.sort_values(["pos_rate", "median_diff", "avg_diff"], ascending=[False, False, False]).reset_index(drop=True)


def build_report() -> str:
    df = _prepare_frame()
    metrics = _metrics_table(df)
    iron = _iron_candidates(df)
    summary = metrics[["law", "label", "top1_share", "top2_share", "p_before", "p_after_top1", "p_after_top2", "判定", "note"]].copy()

    lines: list[str] = []
    lines.append("# 蒲田7 台固有性の定量化")
    lines.append("")
    lines.append(f"- rows={len(df):,}")
    lines.append(f"- unique_dates={df['date'].nunique():,}")
    lines.append("")
    lines.append("## Section 1: 台固有性メトリクス")
    lines.append(table_to_markdown(summary))
    lines.append("")
    lines.append("## Section 2: 鉄台候補")
    lines.append(table_to_markdown(iron.head(60)))
    lines.append("")
    lines.append("## Section 3: サマリーテーブル")
    lines.append(table_to_markdown(summary[["label", "top1_share", "top2_share", "p_before", "p_after_top1", "p_after_top2", "判定"]]))
    lines.append("")
    lines.append("- top_machine_share / top2_machine_share は focal category の diff 合計に対する寄与率。")
    lines.append("- focal category の diff 合計が 0 以下のときは NaN とし、判定は未判定。")
    lines.append("- DD11 は n<30 の場合にサンプル不足として未判定。")
    return "\n".join(lines).rstrip() + "\n"


def main() -> None:
    ensure_report_dir()
    report = build_report()
    write_text(REPORT_PATH, report)
    print(f"[OK] report saved: {REPORT_PATH}")


if __name__ == "__main__":
    main()
