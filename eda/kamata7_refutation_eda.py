from __future__ import annotations

import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from eda.kamata7_verification_common import (
    REPORT_DIR,
    ensure_report_dir,
    prepare_base_frame,
    split_half_dates,
    table_to_markdown,
    write_text,
)

REPORT_PATH = REPORT_DIR / "kamata7_refutation_eda_report.md"
REGIME_REPORT_PATH = REPORT_DIR / "kamata7_regime_change_ledger_report.md"
FALLBACK_SPLIT_DATE = "20251222"
KAKUBAN_ORDER = ["角1", "角2", "中間", "角N-1", "角N"]


def select_games_column(df: pd.DataFrame) -> str:
    if "games" in df.columns:
        return "games"
    if "games_normalized" in df.columns:
        return "games_normalized"
    raise KeyError("games or games_normalized not found")


def resolve_regime_split_date(report_path: Path = REGIME_REPORT_PATH) -> str:
    try:
        text = report_path.read_text(encoding="utf-8")
    except OSError:
        return FALLBACK_SPLIT_DATE
    match = re.search(r"推奨分割日:\s*(\d{8})", text)
    return match.group(1) if match else FALLBACK_SPLIT_DATE


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
    df["machine_digit"] = df["machine_digit"].astype(str)
    df["machine_zorome"] = pd.to_numeric(df["machine_zorome"], errors="coerce").fillna(0).astype(int)
    df["dd"] = pd.to_numeric(df.get("dd", df["date"].str[6:8]), errors="coerce")
    df["day_of_week"] = df["day_of_week"].astype(str)
    return df


def _top3_digits(frame: pd.DataFrame) -> list[str]:
    if frame.empty:
        return []
    ranking = frame.groupby("machine_digit", dropna=False)["diff"].mean().sort_values(ascending=False)
    return [str(x) for x in ranking.head(3).index.tolist()]


def _claim_result(frame: pd.DataFrame, claim_id: str, *, reference_frame: pd.DataFrame | None = None) -> dict[str, object]:
    if claim_id == "C1":
        sub = frame[(frame["floor_side"] == "2F_L") & (frame["seg"] == "N")].copy()
        top3 = _top3_digits(sub)
        return {"value": ",".join(top3), "positive": "6" in top3}
    if claim_id == "C2":
        sub = frame[(frame["floor_side"] == "3F_L") & (frame["seg"] == "N")].copy()
        top3 = _top3_digits(sub)
        return {"value": ",".join(top3), "positive": any(d in {"8", "9"} for d in top3)}
    if claim_id == "C3":
        sub = frame.copy()
        mid = sub[sub["kakuban_rank"] == "中間"]["diff"].mean()
        edge = sub[sub["kakuban_rank"].isin(["角1", "角2", "角N-1", "角N"])]["diff"].mean()
        delta = float(mid - edge) if pd.notna(mid) and pd.notna(edge) else np.nan
        return {"value": round(delta, 1) if pd.notna(delta) else np.nan, "positive": bool(pd.notna(delta) and delta > 0)}
    if claim_id == "C4":
        sub = frame[frame["seg"] == "N"].copy()
        sat = sub[sub["day_of_week"] == "土"]["plus"].mean()
        non = sub[sub["day_of_week"] != "土"]["plus"].mean()
        delta = float((sat - non) * 100) if pd.notna(sat) and pd.notna(non) else np.nan
        return {"value": round(delta, 1) if pd.notna(delta) else np.nan, "positive": bool(pd.notna(delta) and delta > 0)}
    if claim_id == "C5":
        sub = frame[frame["dd"] == 11].copy()
        yes = sub[sub["machine_zorome"] == 1]["diff"].mean()
        no = sub[sub["machine_zorome"] == 0]["diff"].mean()
        delta = float(yes - no) if pd.notna(yes) and pd.notna(no) else np.nan
        return {"value": round(delta, 1) if pd.notna(delta) else np.nan, "positive": bool(pd.notna(delta) and delta > 0)}
    if claim_id == "C6":
        sub = frame.copy()
        yes = sub[sub["machine_zorome"] == 1]["diff"].mean()
        no = sub[sub["machine_zorome"] == 0]["diff"].mean()
        delta = float(yes - no) if pd.notna(yes) and pd.notna(no) else np.nan
        return {"value": round(delta, 1) if pd.notna(delta) else np.nan, "positive": bool(pd.notna(delta) and delta > 0)}
    raise ValueError(claim_id)


def _direction_label(flag: bool) -> str:
    return "正方向" if flag else "逆方向/不成立"


def _split_half_table(df: pd.DataFrame) -> pd.DataFrame:
    first_dates, second_dates = split_half_dates(df)
    rows: list[dict[str, object]] = []
    claims = {
        "C1": "2F_L_N d6最強",
        "C2": "3F_L_N d8/d9最強",
        "C3": "角番中間台優位",
        "C4": "AT群×土曜 +1.71pt",
        "C5": "DD11ゾロ目 +210",
        "C6": "台末尾ゾロ目 全体+49",
    }
    for claim_id, label in claims.items():
        first = _claim_result(df[df["date"].isin(first_dates)].copy(), claim_id)
        second = _claim_result(df[df["date"].isin(second_dates)].copy(), claim_id)
        rows.append(
            {
                "claim": claim_id,
                "label": label,
                "前半値": first["value"],
                "後半値": second["value"],
                "前半方向": _direction_label(bool(first["positive"])),
                "後半方向": _direction_label(bool(second["positive"])),
                "split_half": "一致" if first["positive"] and second["positive"] else "不一致",
            }
        )
    return pd.DataFrame(rows)


def _regime_table(df: pd.DataFrame, split_date: str) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    claims = {
        "C1": "2F_L_N d6最強",
        "C2": "3F_L_N d8/d9最強",
        "C3": "角番中間台優位",
        "C4": "AT群×土曜 +1.71pt",
        "C5": "DD11ゾロ目 +210",
        "C6": "台末尾ゾロ目 全体+49",
    }
    before_df = df[df["date"].astype(str) < split_date].copy()
    after_df = df[df["date"].astype(str) >= split_date].copy()
    for claim_id, label in claims.items():
        before = _claim_result(before_df, claim_id)
        after = _claim_result(after_df, claim_id)
        rows.append(
            {
                "claim": claim_id,
                "label": label,
                "入替前値": before["value"],
                "入替後値": after["value"],
                "入替前方向": _direction_label(bool(before["positive"])),
                "入替後方向": _direction_label(bool(after["positive"])),
                "regime": "一致" if before["positive"] and after["positive"] else "不一致",
            }
        )
    return pd.DataFrame(rows)


def _low_activity_table(df: pd.DataFrame) -> pd.DataFrame:
    games_col = select_games_column(df)
    daily_games = df.groupby("date", dropna=False)[games_col].mean()
    threshold = float(daily_games.quantile(0.25))
    keep_dates = daily_games[daily_games >= threshold].index.astype(str)
    filtered = df[df["date"].astype(str).isin(keep_dates)].copy()
    rows: list[dict[str, object]] = []
    claims = {
        "C1": "2F_L_N d6最強",
        "C2": "3F_L_N d8/d9最強",
        "C3": "角番中間台優位",
        "C4": "AT群×土曜 +1.71pt",
        "C5": "DD11ゾロ目 +210",
        "C6": "台末尾ゾロ目 全体+49",
    }
    for claim_id, label in claims.items():
        full = _claim_result(df, claim_id)
        after = _claim_result(filtered, claim_id)
        rows.append(
            {
                "claim": claim_id,
                "label": label,
                "全体値": full["value"],
                "除外後値": after["value"],
                "全体方向": _direction_label(bool(full["positive"])),
                "除外後方向": _direction_label(bool(after["positive"])),
                "low_activity": "一致" if full["positive"] == after["positive"] else "不一致",
            }
        )
    return pd.DataFrame(rows)


def _overall_table(split_half: pd.DataFrame, regime: pd.DataFrame, low_activity: pd.DataFrame) -> pd.DataFrame:
    merged = split_half[["claim", "label", "split_half"]].merge(
        regime[["claim", "regime"]], on="claim", how="left"
    ).merge(
        low_activity[["claim", "low_activity"]], on="claim", how="left"
    )
    score = (
        (merged["split_half"] == "一致").astype(int)
        + (merged["regime"] == "一致").astype(int)
        + (merged["low_activity"] == "一致").astype(int)
    )
    merged["総合判定"] = np.select(
        [score == 3, score == 2],
        ["堅牢", "条件付き"],
        default="脆弱",
    )
    return merged


def build_report() -> str:
    df = _prepare_frame()
    split_date = resolve_regime_split_date()
    split_half = _split_half_table(df)
    regime = _regime_table(df, split_date)
    low_activity = _low_activity_table(df)
    overall = _overall_table(split_half, regime, low_activity)
    downgrade = overall[overall["総合判定"] == "脆弱"]["label"].tolist()

    lines: list[str] = []
    lines.append("# 蒲田7 反証専用EDA")
    lines.append("")
    lines.append(f"- rows={len(df):,}")
    lines.append(f"- unique_dates={df['date'].nunique():,}")
    lines.append(f"- regime_split_date={split_date}")
    lines.append("")
    lines.append("## Section 1: 期間分割テスト")
    lines.append(table_to_markdown(split_half))
    lines.append("")
    lines.append("## Section 2: レジーム分割テスト")
    lines.append(table_to_markdown(regime))
    lines.append("")
    lines.append("## Section 3: 低稼働日除外テスト")
    lines.append(table_to_markdown(low_activity))
    lines.append("")
    lines.append("## Section 4: 総合判定")
    lines.append(table_to_markdown(overall))
    lines.append("")
    if downgrade:
        lines.append(f"- 理論書からの格下げ候補: {', '.join(downgrade)}")
    else:
        lines.append("- 脆弱判定はなし。")
    return "\n".join(lines).rstrip() + "\n"


def main() -> None:
    ensure_report_dir()
    report = build_report()
    write_text(REPORT_PATH, report)
    print(f"[OK] report saved: {REPORT_PATH}")


if __name__ == "__main__":
    main()
