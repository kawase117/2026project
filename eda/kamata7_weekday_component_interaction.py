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

from eda.kamata7_dd_internal_structure import _classify_kakuban_rank
from eda.kamata7_lastdigit_lr_eda import load_coords
from eda.kamata7_verification_common import (  # noqa: E402
    DOW_ORDER,
    DIGIT_ORDER,
    KAKUBAN_ORDER,
    REPORT_DIR,
    prepare_base_frame,
    table_to_markdown,
    write_text,
)

HALL = "蒲田7"
ANNIVERSARY_MMDD = "0707"
REPORT_PATH = REPORT_DIR / "kamata7_weekday_component_interaction_report.md"
PAIRWISE_CSV = REPORT_DIR / "kamata7_weekday_component_pairwise.csv"
F_MATRIX_CSV = REPORT_DIR / "kamata7_weekday_component_f_matrix.csv"
TRIPLET_CSV = REPORT_DIR / "kamata7_weekday_triplet_daily.csv"

SEGMENT_ORDER = ["A", "N"]
WEEKDAY_ALIASES = {
    "Monday": "月",
    "Tuesday": "火",
    "Wednesday": "水",
    "Thursday": "木",
    "Friday": "金",
    "Saturday": "土",
    "Sunday": "日",
    "Mon": "月",
    "Tue": "火",
    "Wed": "水",
    "Thu": "木",
    "Fri": "金",
    "Sat": "土",
    "Sun": "日",
    "月曜日": "月",
    "火曜日": "火",
    "水曜日": "水",
    "木曜日": "木",
    "金曜日": "金",
    "土曜日": "土",
    "日曜日": "日",
}


def _normalize_weekday(value: object) -> str:
    text = str(value).strip()
    if text in DOW_ORDER:
        return text
    return WEEKDAY_ALIASES.get(text, text[:1] if text else "")


def _normalize_triplet_label(values: list[int]) -> str:
    return "-".join(str(v) for v in sorted(values))


def is_consecutive_ring(digits: list[int] | tuple[int, ...] | pd.Series) -> bool:
    values = [int(d) % 10 for d in digits]
    if len(values) != len(set(values)):
        return False
    if len(values) < 2:
        return True

    sorted_values = sorted(values)
    if sorted_values[-1] - sorted_values[0] == len(sorted_values) - 1:
        return True

    for offset in range(10):
        rotated = sorted(((d - offset) % 10 for d in values))
        if rotated[-1] - rotated[0] == len(rotated) - 1:
            return True
    return False


def _format_float(value: float | int | None, digits: int = 1) -> str:
    if value is None or pd.isna(value):
        return "NaN"
    return f"{float(value):.{digits}f}"


def _cohen_d(a: np.ndarray, b: np.ndarray) -> float:
    a = np.asarray(a, dtype=float)
    b = np.asarray(b, dtype=float)
    a = a[~np.isnan(a)]
    b = b[~np.isnan(b)]
    if len(a) < 2 or len(b) < 2:
        return np.nan
    var_a = a.var(ddof=1)
    var_b = b.var(ddof=1)
    pooled = ((len(a) - 1) * var_a + (len(b) - 1) * var_b) / (len(a) + len(b) - 2)
    if pooled <= 0:
        return np.nan
    return float((a.mean() - b.mean()) / np.sqrt(pooled))


def _bonferroni_adjust(p_value: float, n_tests: int) -> float:
    if pd.isna(p_value):
        return np.nan
    return float(min(1.0, p_value * max(1, n_tests)))


def _eta_squared_from_f(f_stat: float, n_groups: int, n_total: int) -> float:
    if pd.isna(f_stat) or n_groups < 2 or n_total <= n_groups:
        return np.nan
    numerator = f_stat * (n_groups - 1)
    denominator = numerator + (n_total - n_groups)
    if denominator <= 0:
        return np.nan
    return float(numerator / denominator)


def _prepare_frame() -> pd.DataFrame:
    df = prepare_base_frame(include_coords=False).copy()
    df["date"] = df["date"].astype(str)
    df["day_of_week"] = df["day_of_week"].map(_normalize_weekday)
    df["machine_number"] = pd.to_numeric(df["machine_number"], errors="coerce")
    df["games"] = pd.to_numeric(df["games"], errors="coerce")
    df["diff"] = pd.to_numeric(df["diff"], errors="coerce")
    df["machine_digit"] = pd.to_numeric(df["machine_digit"], errors="coerce")
    df = df.dropna(subset=["machine_number", "games", "diff", "machine_digit", "day_of_week"]).copy()
    df = df[df["games"] >= 2000].copy()
    df["machine_number"] = df["machine_number"].astype(int)
    df["machine_digit"] = df["machine_digit"].astype(int).astype(str)

    coords = load_coords().copy()
    coords = coords.drop_duplicates(subset=["machine_number"], keep="first")
    coords["kakuban_rank"] = coords.apply(_classify_kakuban_rank, axis=1)
    df = df.merge(coords[["machine_number", "kakuban_rank"]], on="machine_number", how="left")
    df = df.dropna(subset=["kakuban_rank"]).copy()

    df["day_of_week"] = pd.Categorical(df["day_of_week"], categories=DOW_ORDER, ordered=True)
    df["seg"] = pd.Categorical(df["seg"], categories=SEGMENT_ORDER, ordered=True)
    df["kakuban_rank"] = pd.Categorical(df["kakuban_rank"], categories=KAKUBAN_ORDER, ordered=True)
    df["machine_digit"] = pd.Categorical(df["machine_digit"], categories=DIGIT_ORDER, ordered=True)
    return df.reset_index(drop=True)


def _aggregate_numeric(df: pd.DataFrame, group_cols: list[str], value_col: str = "diff") -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=[*group_cols, "n", "avg_diff", "plus_rate", "hit104_rate"])
    out = (
        df.groupby(group_cols, observed=True)
        .agg(
            n=(value_col, "size"),
            avg_diff=(value_col, "mean"),
            plus_rate=("plus", "mean"),
            hit104_rate=("hit104", "mean"),
        )
        .reset_index()
    )
    out["avg_diff"] = out["avg_diff"].round(0)
    out["plus_rate"] = (out["plus_rate"] * 100).round(1)
    out["hit104_rate"] = (out["hit104_rate"] * 100).round(1)
    return out


def _anova_for_subset(df: pd.DataFrame, group_col: str, value_col: str) -> dict[str, object]:
    groups = [
        g[value_col].dropna().to_numpy()
        for _, g in df.groupby(group_col, observed=True)
        if len(g) >= 5
    ]
    if len(groups) < 2:
        return {
            "f_stat": np.nan,
            "p_value": np.nan,
            "eta_sq": np.nan,
            "n_groups": len(groups),
            "n_rows": int(len(df)),
        }

    stat, p_value = stats.f_oneway(*groups)
    total_n = int(sum(len(g) for g in groups))
    return {
        "f_stat": float(stat),
        "p_value": float(p_value),
        "eta_sq": _eta_squared_from_f(float(stat), len(groups), total_n),
        "n_groups": len(groups),
        "n_rows": total_n,
    }


def _compare_focus_vs_rest(
    df: pd.DataFrame,
    *,
    focus_weekday: str,
    group_col: str,
    value_col: str = "diff",
) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for category in df[group_col].dropna().drop_duplicates().tolist():
        sub = df[df[group_col] == category].copy()
        focus = sub[sub["day_of_week"] == focus_weekday][value_col].dropna().to_numpy()
        rest = sub[sub["day_of_week"] != focus_weekday][value_col].dropna().to_numpy()
        if len(focus) < 5 or len(rest) < 5:
            continue
        u_stat, p_value = stats.mannwhitneyu(focus, rest, alternative="two-sided")
        rows.append(
            {
                group_col: category,
                "focus_weekday": focus_weekday,
                "focus_n": int(len(focus)),
                "focus_avg_diff": float(np.mean(focus)),
                "rest_n": int(len(rest)),
                "rest_avg_diff": float(np.mean(rest)),
                "delta_diff": float(np.mean(focus) - np.mean(rest)),
                "cohen_d": _cohen_d(focus, rest),
                "mw_u": float(u_stat),
                "raw_p_value": float(p_value),
            }
        )

    out = pd.DataFrame(rows)
    if out.empty:
        return out
    out["bonferroni_p"] = out["raw_p_value"].apply(lambda p: _bonferroni_adjust(p, len(out)))
    out["abs_delta"] = out["delta_diff"].abs()
    out = out.sort_values(["bonferroni_p", "abs_delta", "raw_p_value"], ascending=[True, False, True]).reset_index(drop=True)
    return out


def _weekday_f_matrix(df: pd.DataFrame) -> pd.DataFrame:
    triplet_df = build_triplet_day_frame(df)
    analyses: list[tuple[str, pd.DataFrame, str, str]] = [
        ("火曜×角番", df[df["seg"] == "N"].copy(), "kakuban_rank", "diff"),
        ("水曜×末尾(A)", df[df["seg"] == "A"].copy(), "machine_digit", "diff"),
        ("水曜×末尾(N)", df[df["seg"] == "N"].copy(), "machine_digit", "diff"),
        ("土曜×3連番AT", triplet_df.copy(), "triplet_kind", "top3_avg_diff"),
    ]

    rows: list[dict[str, object]] = []
    for analysis_name, source_df, group_col, value_col in analyses:
        for weekday in DOW_ORDER:
            sub = source_df[source_df["day_of_week"] == weekday].copy()
            result = _anova_for_subset(sub, group_col, value_col)
            result.update(
                {
                    "analysis_name": analysis_name,
                    "weekday": weekday,
                    "group_col": group_col,
                    "value_col": value_col,
                }
            )
            rows.append(result)

    out = pd.DataFrame(rows)
    if out.empty:
        return out
    valid_mask = out["p_value"].notna()
    n_tests = int(valid_mask.sum())
    out["bonferroni_p"] = out["p_value"].apply(lambda p: _bonferroni_adjust(p, n_tests))
    out = out.sort_values(["f_stat", "bonferroni_p", "analysis_name", "weekday"], ascending=[False, True, True, True]).reset_index(drop=True)
    return out


def build_triplet_day_frame(df: pd.DataFrame) -> pd.DataFrame:
    n_df = df[df["seg"] == "N"].copy()
    digit_daily = (
        n_df.groupby(["date", "day_of_week", "machine_digit"], observed=True)
        .agg(avg_diff=("diff", "mean"), n=("diff", "size"))
        .reset_index()
    )
    pivot = (
        digit_daily.pivot(index=["date", "day_of_week"], columns="machine_digit", values="avg_diff")
        .reindex(columns=DIGIT_ORDER)
        .reset_index()
    )

    rows: list[dict[str, object]] = []
    for _, row in pivot.iterrows():
        valid = row[DIGIT_ORDER].dropna().astype(float)
        if len(valid) < 3:
            continue
        ranked = valid.sort_values(ascending=False)
        top_digits = [int(col) for col in ranked.index[:3]]
        is_consecutive = bool(is_consecutive_ring(top_digits))
        if is_consecutive and 7 in top_digits:
            triplet_kind = "consecutive_with7"
        elif is_consecutive:
            triplet_kind = "consecutive_without7"
        else:
            triplet_kind = "non_consecutive"
        rows.append(
            {
                "date": str(row["date"]),
                "day_of_week": row["day_of_week"],
                "top1": int(top_digits[0]),
                "top2": int(top_digits[1]),
                "top3": int(top_digits[2]),
                "triplet_label": _normalize_triplet_label(top_digits),
                "triplet_kind": triplet_kind,
                "contains_7": 7 in top_digits,
                "is_consecutive": is_consecutive,
                "top3_avg_diff": float(ranked.iloc[:3].mean()),
            }
        )

    out = pd.DataFrame(rows)
    if out.empty:
        return out
    out["day_of_week"] = pd.Categorical(out["day_of_week"], categories=DOW_ORDER, ordered=True)
    out["triplet_kind"] = pd.Categorical(
        out["triplet_kind"],
        categories=["consecutive_with7", "consecutive_without7", "non_consecutive"],
        ordered=True,
    )
    return out.sort_values(["day_of_week", "date"]).reset_index(drop=True)


def _triplet_summary(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=["day_of_week", "n_days", "avg_top3_diff", "consecutive_rate", "with7_rate", "top_triplet"])
    rows: list[dict[str, object]] = []
    for weekday in DOW_ORDER:
        sub = df[df["day_of_week"] == weekday]
        if sub.empty:
            continue
        top_triplet = sub["triplet_label"].value_counts().index[0]
        rows.append(
            {
                "day_of_week": weekday,
                "n_days": int(len(sub)),
                "avg_top3_diff": float(sub["top3_avg_diff"].mean()),
                "consecutive_rate": float(sub["is_consecutive"].mean() * 100),
                "with7_rate": float(sub["contains_7"].mean() * 100),
                "top_triplet": top_triplet,
            }
        )
    return pd.DataFrame(rows)


def _weekday_block_title(title: str) -> str:
    return f"## {title}\n"


def _markdown_block(title: str, df: pd.DataFrame) -> str:
    return "\n".join([f"**{title}**", table_to_markdown(df), ""])


def build_report(df: pd.DataFrame) -> tuple[str, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    triplet_df = build_triplet_day_frame(df)
    pairwise_frames: list[pd.DataFrame] = []

    # 火曜 × 角番
    tue_kakuban = _aggregate_numeric(df[(df["seg"] == "N") & (df["day_of_week"] == "火")], ["kakuban_rank"])
    tue_kakuban_compare = _compare_focus_vs_rest(df[df["seg"] == "N"], focus_weekday="火", group_col="kakuban_rank")
    tue_kakuban_compare["analysis_name"] = "火曜×角番(N)"
    pairwise_frames.append(tue_kakuban_compare)

    # 水曜 × 末尾
    wed_tail_a = _aggregate_numeric(df[(df["seg"] == "A") & (df["day_of_week"] == "水")], ["machine_digit"])
    wed_tail_n = _aggregate_numeric(df[(df["seg"] == "N") & (df["day_of_week"] == "水")], ["machine_digit"])
    wed_tail_a_compare = _compare_focus_vs_rest(df[df["seg"] == "A"], focus_weekday="水", group_col="machine_digit")
    wed_tail_a_compare["analysis_name"] = "水曜×末尾(A)"
    wed_tail_n_compare = _compare_focus_vs_rest(df[df["seg"] == "N"], focus_weekday="水", group_col="machine_digit")
    wed_tail_n_compare["analysis_name"] = "水曜×末尾(N)"
    pairwise_frames.extend([wed_tail_a_compare, wed_tail_n_compare])

    # 土曜 × 3連番AT
    sat_triplet_summary = _triplet_summary(triplet_df[triplet_df["day_of_week"] == "土"])
    sat_triplet_compare = _compare_focus_vs_rest(triplet_df, focus_weekday="土", group_col="triplet_kind", value_col="top3_avg_diff")
    sat_triplet_compare["analysis_name"] = "土曜×3連番AT"
    pairwise_frames.append(sat_triplet_compare)

    pairwise = pd.concat([frame for frame in pairwise_frames if not frame.empty], ignore_index=True) if any(not frame.empty for frame in pairwise_frames) else pd.DataFrame()
    if not pairwise.empty:
        pairwise["analysis_name"] = pd.Categorical(
            pairwise["analysis_name"],
            categories=["火曜×角番(N)", "水曜×末尾(A)", "水曜×末尾(N)", "土曜×3連番AT"],
            ordered=True,
        )
        pairwise["p_rank"] = pairwise.groupby("analysis_name", observed=True)["raw_p_value"].rank(method="first", ascending=True)
        pairwise = pairwise.sort_values(["analysis_name", "bonferroni_p", "abs_delta"], ascending=[True, True, False]).reset_index(drop=True)

    f_matrix = _weekday_f_matrix(df)
    ranking = f_matrix.sort_values(["f_stat", "bonferroni_p"], ascending=[False, True]).reset_index(drop=True)

    lines: list[str] = []
    lines.append("# 蒲田7 曜日別コンポーネント交互作用分析")
    lines.append("")
    lines.append(f"- 対象ホール: {HALL}")
    lines.append("- 前処理: 7/7除外、台番号2026除外、games>=2000 に限定")
    lines.append("- 補正: 各比較群ごとに Bonferroni 補正を適用")
    lines.append("")

    lines.append(_weekday_block_title("1. 火曜 × 角番（N機）"))
    lines.append(_markdown_block("火曜の角番ベースライン", tue_kakuban))
    if not tue_kakuban_compare.empty:
        lines.append(_markdown_block("火曜 vs 他曜日の角番比較", tue_kakuban_compare))
    lines.append("")

    lines.append(_weekday_block_title("2. 水曜 × 末尾（A機 / N機）"))
    lines.append(_markdown_block("水曜の末尾ベースライン（A機）", wed_tail_a))
    lines.append(_markdown_block("水曜の末尾ベースライン（N機）", wed_tail_n))
    if not wed_tail_a_compare.empty:
        lines.append(_markdown_block("水曜 vs 他曜日の末尾比較（A機）", wed_tail_a_compare))
    if not wed_tail_n_compare.empty:
        lines.append(_markdown_block("水曜 vs 他曜日の末尾比較（N機）", wed_tail_n_compare))
    lines.append("")

    lines.append(_weekday_block_title("3. 土曜 × 3連番AT（末尾7含む）"))
    lines.append(_markdown_block("土曜の3連番ATサマリ", sat_triplet_summary))
    if not sat_triplet_compare.empty:
        lines.append(_markdown_block("土曜 vs 他曜日の3連番AT比較", sat_triplet_compare))
    lines.append("")

    lines.append(_weekday_block_title("4. 全曜日 × 全コンポーネント F-stat ランキング"))
    if not ranking.empty:
        lines.append(
            _markdown_block(
                "F-statランキング上位",
                ranking[
                    [
                        "analysis_name",
                        "weekday",
                        "group_col",
                        "value_col",
                        "f_stat",
                        "p_value",
                        "bonferroni_p",
                        "eta_sq",
                        "n_groups",
                        "n_rows",
                    ]
                ].head(20),
            )
        )
    else:
        lines.append("_no rows_")
    lines.append("")

    lines.append("### 補足")
    lines.append("- `analysis_name` は火曜×角番、火曜×末尾、水曜×末尾、土曜×3連番AT の4系列をまとめたものです。")
    lines.append("- `bonferroni_p` は各系列内の比較数に応じて補正済みです。")
    lines.append("- `triplet_kind` は `consecutive_with7` / `consecutive_without7` / `non_consecutive` の3分類です。")
    lines.append("")

    report = "\n".join(lines).rstrip() + "\n"
    return report, pairwise, f_matrix, triplet_df


def main() -> None:
    df = _prepare_frame()
    report, pairwise, f_matrix, triplet_df = build_report(df)

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    write_text(REPORT_PATH, report)
    if not pairwise.empty:
        pairwise.to_csv(PAIRWISE_CSV, index=False, encoding="utf-8-sig")
    else:
        pd.DataFrame(columns=["analysis_name"]).to_csv(PAIRWISE_CSV, index=False, encoding="utf-8-sig")
    if not f_matrix.empty:
        f_matrix.to_csv(F_MATRIX_CSV, index=False, encoding="utf-8-sig")
    else:
        pd.DataFrame(columns=["analysis_name"]).to_csv(F_MATRIX_CSV, index=False, encoding="utf-8-sig")
    if not triplet_df.empty:
        triplet_df.to_csv(TRIPLET_CSV, index=False, encoding="utf-8-sig")
    else:
        pd.DataFrame(columns=["date"]).to_csv(TRIPLET_CSV, index=False, encoding="utf-8-sig")

    print(f"[OK] report saved: {REPORT_PATH}")
    print(f"[OK] csv saved: {PAIRWISE_CSV}")
    print(f"[OK] csv saved: {F_MATRIX_CSV}")
    print(f"[OK] csv saved: {TRIPLET_CSV}")


if __name__ == "__main__":
    main()
