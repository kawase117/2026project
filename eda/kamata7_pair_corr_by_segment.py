from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from eda.core import load_hall_df
from eda.kamata7_digit_triplet_analysis import table_to_md
from eda.kamata7_lastdigit_lr_eda import build_floor_side_map, classify_seg


PROJECT_ROOT = Path(__file__).resolve().parents[1]
REPORT_DIR = PROJECT_ROOT / "eda" / "reports"
REPORT_PATH = REPORT_DIR / "kamata7_pair_corr_by_segment_report.md"
SUMMARY_CSV_PATH = REPORT_DIR / "kamata7_pair_corr_by_segment_summary.csv"
TOP_PAIRS_CSV_PATH = REPORT_DIR / "kamata7_pair_corr_by_segment_top_pairs.csv"

HALL_NAME = "蒲田7"
EXCLUDED_MMDD = "0707"
DIGITS = list(range(10))
SEGMENT_ORDER = [
    "2F_L_N",
    "2F_R_N",
    "3F_L_A",
    "3F_L_N",
    "3F_R_A",
    "3F_R_N",
]
WEEKDAY_FILTERS = {
    "土": "Sat",
    "水": "Wed",
}


@dataclass(frozen=True)
class SegmentAnalysis:
    segment: str
    data: pd.DataFrame
    daily_digit: pd.DataFrame
    corr_matrix: pd.DataFrame
    pair_table: pd.DataFrame
    pair_test: pd.Series
    top_pairs: pd.DataFrame
    bottom_pairs: pd.DataFrame
    cluster456: pd.Series

    @property
    def pairs(self) -> pd.DataFrame:
        return self.pair_table


@dataclass(frozen=True)
class AnalysisOutputs:
    raw: pd.DataFrame
    segment_frame: pd.DataFrame
    segment_summary: pd.DataFrame
    all_segments: dict[str, SegmentAnalysis]
    saturday_segments: dict[str, SegmentAnalysis]
    wednesday_segments: dict[str, SegmentAnalysis]
    all_pairs_long: pd.DataFrame
    summary: pd.DataFrame


def is_adjacent_pair(digit_a: int, digit_b: int) -> bool:
    a = int(digit_a) % 10
    b = int(digit_b) % 10
    return (a - b) % 10 in {1, 9}


def load_data() -> pd.DataFrame:
    df = load_hall_df(HALL_NAME).copy()
    df["date"] = df["date"].astype(str)
    df = df[df["date"].str[4:8] != EXCLUDED_MMDD].copy()
    df["machine_digit"] = pd.to_numeric(df["machine_digit"], errors="coerce")
    df["diff"] = pd.to_numeric(df["diff"], errors="coerce")
    df["games"] = pd.to_numeric(df["games"], errors="coerce")
    return df.dropna(subset=["machine_digit", "diff", "games"]).copy()


def build_segment_frame(df: pd.DataFrame, floor_side_map: pd.DataFrame | None = None) -> pd.DataFrame:
    frame = df.copy()
    if "floor" not in frame.columns or "side" not in frame.columns:
        if floor_side_map is None:
            floor_side_map = build_floor_side_map()
        frame = frame.merge(floor_side_map, on="machine_number", how="inner")
    frame["machine_number"] = pd.to_numeric(frame["machine_number"], errors="coerce")
    frame["machine_digit"] = pd.to_numeric(frame["machine_digit"], errors="coerce")
    frame["machine_name"] = frame["machine_name"].astype(str)
    frame["seg"] = frame["machine_name"].map(classify_seg)
    frame["floor"] = frame["floor"].astype(str)
    frame["side"] = frame["side"].astype(str)
    frame = frame.dropna(subset=["machine_number", "machine_digit", "floor", "side", "seg"]).copy()
    frame["machine_number"] = frame["machine_number"].astype(int)
    frame["machine_digit"] = frame["machine_digit"].astype(int)
    frame["group_key"] = frame["floor"] + "_" + frame["side"] + "_" + frame["seg"]
    return frame


def build_segment_summary(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        columns = ["segment", "n_machines", "n_days", "avg_diff", *[f"digit_{d}_pct" for d in DIGITS]]
        return pd.DataFrame(columns=columns)

    rows: list[dict[str, object]] = []
    for segment, grp in df.groupby("group_key", dropna=False):
        machine_count = int(grp["machine_number"].nunique())
        n_days = int(grp["date"].nunique())
        digit_share = grp["machine_digit"].value_counts(normalize=True).reindex(DIGITS, fill_value=0.0) * 100
        row: dict[str, object] = {
            "segment": segment,
            "n_machines": machine_count,
            "n_days": n_days,
            "avg_diff": float(grp["diff"].mean()) if len(grp) else np.nan,
        }
        for digit in DIGITS:
            row[f"digit_{digit}_pct"] = float(digit_share.loc[digit])
        rows.append(row)

    result = pd.DataFrame(rows)
    categories = list(dict.fromkeys([*SEGMENT_ORDER, *result["segment"].tolist()]))
    result["segment_order"] = pd.Categorical(result["segment"], categories=categories, ordered=True)
    result = result.sort_values(["segment_order", "segment"]).drop(columns=["segment_order"]).reset_index(drop=True)
    return result


def build_daily_digit_matrix(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=["date", "day_of_week", "dd_mod10", *DIGITS])

    daily = (
        df.groupby(["date", "day_of_week", "dd_mod10", "machine_digit"], dropna=False)
        .agg(avg_diff=("diff", "mean"))
        .reset_index()
    )
    pivot = (
        daily.pivot_table(index=["date", "day_of_week", "dd_mod10"], columns="machine_digit", values="avg_diff", aggfunc="first")
        .reindex(columns=DIGITS)
        .reset_index()
        .sort_values(["date", "day_of_week", "dd_mod10"])
        .reset_index(drop=True)
    )
    return pivot


def build_corr_matrix(daily_digit: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.Series]:
    corr = pd.DataFrame(index=DIGITS, columns=DIGITS, dtype=float)
    pair_rows: list[dict[str, object]] = []

    if daily_digit.empty:
        for digit in DIGITS:
            corr.loc[digit, digit] = 1.0
        pair_df = pd.DataFrame(columns=["digit_a", "digit_b", "pair_label", "n_days", "pearson_r"])
        test = pd.Series(
            {
                "adjacent_n": 0,
                "nonadjacent_n": 0,
                "adjacent_mean": np.nan,
                "nonadjacent_mean": np.nan,
                "adjacent_median": np.nan,
                "nonadjacent_median": np.nan,
                "u_stat": np.nan,
                "p_value": np.nan,
            }
        )
        return corr, pair_df, test

    matrix = daily_digit.set_index(["date", "day_of_week", "dd_mod10"])[DIGITS]
    for i in DIGITS:
        for j in DIGITS:
            valid = matrix[[i, j]].dropna()
            corr_value = valid.iloc[:, 0].corr(valid.iloc[:, 1]) if len(valid) >= 2 else np.nan
            corr.loc[i, j] = corr_value
            if i < j:
                pair_rows.append(
                    {
                        "digit_a": i,
                        "digit_b": j,
                        "pair_label": f"{i}-{j}",
                        "n_days": int(len(valid)),
                        "pearson_r": float(corr_value) if not pd.isna(corr_value) else np.nan,
                    }
                )

    for digit in DIGITS:
        corr.loc[digit, digit] = 1.0

    pair_df = pd.DataFrame(pair_rows).sort_values(["pair_label"]).reset_index(drop=True)
    adjacent = pair_df[pair_df.apply(lambda row: is_adjacent_pair(int(row["digit_a"]), int(row["digit_b"])), axis=1)]["pearson_r"].dropna()
    nonadjacent = pair_df[~pair_df.apply(lambda row: is_adjacent_pair(int(row["digit_a"]), int(row["digit_b"])), axis=1)]["pearson_r"].dropna()

    if len(adjacent) and len(nonadjacent):
        u_stat, p_value = stats.mannwhitneyu(adjacent, nonadjacent, alternative="greater")
    else:
        u_stat, p_value = np.nan, np.nan

    test = pd.Series(
        {
            "adjacent_n": int(len(adjacent)),
            "nonadjacent_n": int(len(nonadjacent)),
            "adjacent_mean": float(adjacent.mean()) if len(adjacent) else np.nan,
            "nonadjacent_mean": float(nonadjacent.mean()) if len(nonadjacent) else np.nan,
            "adjacent_median": float(adjacent.median()) if len(adjacent) else np.nan,
            "nonadjacent_median": float(nonadjacent.median()) if len(nonadjacent) else np.nan,
            "u_stat": float(u_stat) if not pd.isna(u_stat) else np.nan,
            "p_value": float(p_value) if not pd.isna(p_value) else np.nan,
        }
    )
    return corr, pair_df, test


def _pairs_extreme_table(pair_df: pd.DataFrame, segment: str, n_top: int = 5, n_bottom: int = 3) -> tuple[pd.DataFrame, pd.DataFrame]:
    if pair_df.empty:
        empty = pd.DataFrame(columns=["segment", "rank", "pair_label", "pearson_r", "n_days"])
        return empty, empty

    valid = pair_df.dropna(subset=["pearson_r"]).copy()
    if valid.empty:
        empty = pd.DataFrame(columns=["segment", "rank", "pair_label", "pearson_r", "n_days"])
        return empty, empty

    top = valid.sort_values(["pearson_r", "pair_label"], ascending=[False, True]).head(n_top).copy()
    bottom = valid.sort_values(["pearson_r", "pair_label"], ascending=[True, True]).head(n_bottom).copy()
    top.insert(0, "segment", segment)
    bottom.insert(0, "segment", segment)
    top.insert(1, "rank", range(1, len(top) + 1))
    bottom.insert(1, "rank", range(1, len(bottom) + 1))
    return top[["segment", "rank", "pair_label", "pearson_r", "n_days"]], bottom[["segment", "rank", "pair_label", "pearson_r", "n_days"]]


def analyze_segment(df: pd.DataFrame, segment: str) -> SegmentAnalysis:
    if "group_key" not in df.columns:
        df = build_segment_frame(df)
    segment_df = df[df["group_key"] == segment].copy()
    daily_digit = build_daily_digit_matrix(segment_df)
    corr_matrix, pair_table, pair_test = build_corr_matrix(daily_digit)
    top_pairs, bottom_pairs = _pairs_extreme_table(pair_table, segment)
    cluster_pairs = pair_table[pair_table["pair_label"].isin(["4-5", "5-6", "4-6"])].copy()
    cluster_mean = float(cluster_pairs["pearson_r"].mean()) if not cluster_pairs.empty and cluster_pairs["pearson_r"].notna().any() else np.nan
    cluster_series = pd.Series(
        {
            "pair_4_5_r": _get_pair_value(pair_table, "4-5"),
            "pair_5_6_r": _get_pair_value(pair_table, "5-6"),
            "pair_4_6_r": _get_pair_value(pair_table, "4-6"),
            "cluster_mean_r": cluster_mean,
        }
    )
    return SegmentAnalysis(
        segment=segment,
        data=segment_df,
        daily_digit=daily_digit,
        corr_matrix=corr_matrix,
        pair_table=pair_table,
        pair_test=pair_test,
        top_pairs=top_pairs,
        bottom_pairs=bottom_pairs,
        cluster456=cluster_series,
    )


def _get_pair_value(pair_table: pd.DataFrame, pair_label: str) -> float:
    if pair_table.empty:
        return np.nan
    hit = pair_table.loc[pair_table["pair_label"] == pair_label, "pearson_r"]
    return float(hit.iloc[0]) if len(hit) else np.nan


def _segment_order_key(segment: str) -> tuple[int, str]:
    if segment in SEGMENT_ORDER:
        return SEGMENT_ORDER.index(segment), segment
    return len(SEGMENT_ORDER), segment


def _segment_results(df: pd.DataFrame, segments: list[str]) -> dict[str, SegmentAnalysis]:
    return {segment: analyze_segment(df, segment) for segment in segments}


def build_outputs(df: pd.DataFrame) -> AnalysisOutputs:
    segment_frame = build_segment_frame(df)
    segment_summary = build_segment_summary(segment_frame)
    segments = [segment for segment in segment_summary["segment"].tolist()]
    ordered_segments = sorted(segments, key=_segment_order_key)
    all_segments = _segment_results(segment_frame, ordered_segments)
    saturday_segments = _segment_results(segment_frame[segment_frame["day_of_week"] == "土"].copy(), ordered_segments)
    wednesday_segments = _segment_results(segment_frame[segment_frame["day_of_week"] == "水"].copy(), ordered_segments)

    all_pairs_long = _build_all_pairs_long(all_segments)
    summary = build_summary_table(all_segments, saturday_segments, wednesday_segments)

    return AnalysisOutputs(
        raw=df,
        segment_frame=segment_frame,
        segment_summary=segment_summary,
        all_segments=all_segments,
        saturday_segments=saturday_segments,
        wednesday_segments=wednesday_segments,
        all_pairs_long=all_pairs_long,
        summary=summary,
    )


def _build_all_pairs_long(segments: dict[str, SegmentAnalysis]) -> pd.DataFrame:
    rows: list[pd.DataFrame] = []
    for segment, analysis in segments.items():
        pair_df = analysis.pair_table.copy()
        if pair_df.empty:
            continue
        pair_df.insert(0, "segment", segment)
        rows.append(pair_df[["segment", "digit_a", "digit_b", "pair_label", "n_days", "pearson_r"]])
    if not rows:
        return pd.DataFrame(columns=["segment", "digit_a", "digit_b", "pair_label", "n_days", "pearson_r"])
    return pd.concat(rows, ignore_index=True)


def build_summary_table(
    all_segments: dict[str, SegmentAnalysis],
    saturday_segments: dict[str, SegmentAnalysis],
    wednesday_segments: dict[str, SegmentAnalysis],
) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for segment in sorted(all_segments.keys(), key=_segment_order_key):
        all_analysis = all_segments[segment]
        sat_analysis = saturday_segments.get(segment)
        wed_analysis = wednesday_segments.get(segment)
        row = {
            "segment": segment,
            "n_machines": int(all_analysis.data["machine_number"].nunique()) if not all_analysis.data.empty else 0,
            "n_days": int(all_analysis.data["date"].nunique()) if not all_analysis.data.empty else 0,
            "all_dow_p": float(all_analysis.pair_test.get("p_value", np.nan)),
            "sat_p": float(sat_analysis.pair_test.get("p_value", np.nan)) if sat_analysis else np.nan,
            "wed_p": float(wed_analysis.pair_test.get("p_value", np.nan)) if wed_analysis else np.nan,
            "sat_cluster456_mean_r": float(sat_analysis.cluster456.get("cluster_mean_r", np.nan)) if sat_analysis else np.nan,
        }
        rows.append(row)
    return pd.DataFrame(rows)


def _corr_matrix_to_md(matrix: pd.DataFrame) -> str:
    if matrix.empty:
        return "該当なし"
    display = matrix.reset_index().rename(columns={"index": "digit"})
    return table_to_md(display, float_digits=2)


def _segment_table_to_md(analysis: SegmentAnalysis) -> str:
    return table_to_md(analysis.data_summary, float_digits=2) if hasattr(analysis, "data_summary") else "該当なし"


def _format_segment_analysis_section(title: str, analyses: dict[str, SegmentAnalysis], include_pairs: bool = True) -> list[str]:
    lines: list[str] = [title]
    for segment in sorted(analyses.keys(), key=_segment_order_key):
        analysis = analyses[segment]
        lines.extend(
            [
                "",
                f"### {segment}",
                f"- adjacent_mean_r={analysis.pair_test.get('adjacent_mean', np.nan):.3f}, nonadjacent_mean_r={analysis.pair_test.get('nonadjacent_mean', np.nan):.3f}, p_value={analysis.pair_test.get('p_value', np.nan):.4f}, n_days={int(analysis.data['date'].nunique()) if not analysis.data.empty else 0}",
                "",
                _corr_matrix_to_md(analysis.corr_matrix),
            ]
        )
        if include_pairs:
            lines.extend(
                [
                    "",
                    "#### Top5 / Bottom3",
                    table_to_md(
                        pd.concat(
                            [
                                analysis.top_pairs.assign(kind="Top5"),
                                analysis.bottom_pairs.assign(kind="Bottom3"),
                            ],
                            ignore_index=True,
                        )[["segment", "kind", "rank", "pair_label", "pearson_r", "n_days"]],
                        float_digits=3,
                    ),
                ]
            )
    return lines


def _cluster_table(analyses: dict[str, SegmentAnalysis]) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for segment in sorted(analyses.keys(), key=_segment_order_key):
        cluster = analyses[segment].cluster456
        rows.append(
            {
                "segment": segment,
                "pair_4_5_r": float(cluster.get("pair_4_5_r", np.nan)),
                "pair_5_6_r": float(cluster.get("pair_5_6_r", np.nan)),
                "pair_4_6_r": float(cluster.get("pair_4_6_r", np.nan)),
                "cluster_mean_r": float(cluster.get("cluster_mean_r", np.nan)),
            }
        )
    return pd.DataFrame(rows)


def build_report(outputs: AnalysisOutputs) -> str:
    lines: list[str] = [
        "# Kamata7 末尾ペア連動のセグメント分解",
        "",
        "## Section 1: セグメント別概要",
        "- 7/7 は除外済み (`date[4:8] != 0707`)",
        "- `n_machines` はセグメント内のユニーク台数、`n_days` はユニーク日数。",
        "",
        table_to_md(outputs.segment_summary, float_digits=2),
        "",
        "## Section 2: セグメント別ペア連動（全曜日）",
    ]

    lines.extend(_format_segment_analysis_section("", outputs.all_segments, include_pairs=True)[1:])
    lines.extend(
        [
            "",
            "### 全セグメント結果",
            table_to_md(
                pd.DataFrame(
                    [
                        {
                            "segment": segment,
                            "adjacent_mean_r": float(analysis.pair_test.get("adjacent_mean", np.nan)),
                            "nonadjacent_mean_r": float(analysis.pair_test.get("nonadjacent_mean", np.nan)),
                            "p_value": float(analysis.pair_test.get("p_value", np.nan)),
                            "n_days": int(analysis.data["date"].nunique()) if not analysis.data.empty else 0,
                        }
                        for segment, analysis in sorted(outputs.all_segments.items(), key=lambda item: _segment_order_key(item[0]))
                    ]
                ),
                float_digits=3,
            ),
            "",
            "## Section 3: セグメント別ペア連動（土曜日のみ）",
        ]
    )

    lines.extend(_format_segment_analysis_section("", outputs.saturday_segments, include_pairs=True)[1:])
    lines.extend(
        [
            "",
            "### 土曜 d4-5-6 クラスタ",
            table_to_md(_cluster_table(outputs.saturday_segments), float_digits=3),
            "",
            "## Section 4: セグメント別ペア連動（水曜日のみ）",
        ]
    )

    lines.extend(_format_segment_analysis_section("", outputs.wednesday_segments, include_pairs=True)[1:])
    lines.extend(
        [
            "",
            "### 水曜 d4-5-6 クラスタ",
            table_to_md(_cluster_table(outputs.wednesday_segments), float_digits=3),
            "",
            "## Section 5: 全体 vs セグメント別の比較サマリ",
            table_to_md(outputs.summary, float_digits=4),
        ]
    )
    return "\n".join(lines).strip() + "\n"


def write_outputs(outputs: AnalysisOutputs) -> None:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    with REPORT_PATH.open("w", encoding="utf-8-sig", newline="\n") as f:
        f.write(build_report(outputs))
    outputs.summary.to_csv(SUMMARY_CSV_PATH, index=False, encoding="utf-8-sig")
    outputs.all_pairs_long.to_csv(TOP_PAIRS_CSV_PATH, index=False, encoding="utf-8-sig")


def main() -> None:
    df = load_data()
    outputs = build_outputs(df)
    write_outputs(outputs)
    print(f"Saved: {REPORT_PATH}")
    print(f"Saved: {SUMMARY_CSV_PATH}")
    print(f"Saved: {TOP_PAIRS_CSV_PATH}")


if __name__ == "__main__":
    main()
