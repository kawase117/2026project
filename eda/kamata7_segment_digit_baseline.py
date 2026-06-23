from __future__ import annotations

import itertools
import sys
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
REPORT_PATH = REPORT_DIR / "kamata7_segment_digit_baseline_report.md"
RANKINGS_CSV_PATH = REPORT_DIR / "kamata7_segment_digit_baseline_rankings.csv"
SIGNAL_CSV_PATH = REPORT_DIR / "kamata7_segment_digit_signal_strength.csv"
QUICKREF_CSV_PATH = REPORT_DIR / "kamata7_segment_digit_quickref_lv5.csv"

HALL_NAME = "蒲田7"
EXCLUDED_MMDD = "0707"
DIGITS = [str(i) for i in range(10)]
DIGIT_ORDER = DIGITS
WEEKDAY_ORDER = ["月", "火", "水", "木", "金", "土", "日"]

LEVEL_COLUMNS = {
    0: "segment_lv0",
    1: "segment_lv1",
    2: "segment_lv2",
    3: "segment_lv3",
    4: "segment_lv4",
    5: "segment_lv5",
}

LEVEL_ORDER = {
    0: ["ALL"],
    1: ["A", "N"],
    2: ["2F", "3F"],
    3: ["2F_N", "3F_A", "3F_N"],
    4: ["2F_L", "2F_R", "3F_L", "3F_R"],
    5: ["2F_L_N", "2F_R_N", "3F_L_A", "3F_L_N", "3F_R_A", "3F_R_N"],
}


def _fmt_int(value: float | int | None) -> str:
    if value is None or pd.isna(value):
        return "NaN"
    return f"{int(round(float(value))):+d}"


def _segment_label(level: int, row: pd.Series) -> str:
    if level == 0:
        return "ALL"
    if level == 1:
        return str(row["seg"])
    if level == 2:
        return str(row["floor"])
    if level == 3:
        return f"{row['floor']}_{row['seg']}"
    if level == 4:
        return f"{row['floor']}_{row['side']}"
    if level == 5:
        return f"{row['floor']}_{row['side']}_{row['seg']}"
    raise ValueError(f"unsupported level: {level}")


def _parent_segment(level: int, segment: str) -> str:
    if level == 0:
        return "ALL"
    if level == 1:
        return "ALL"
    if level == 2:
        return "ALL"
    if level == 3:
        return segment.split("_", 1)[0]
    if level == 4:
        return segment.split("_", 1)[0]
    if level == 5:
        parts = segment.split("_")
        return "_".join(parts[:2])
    return "ALL"


def _digit_metrics(grp: pd.DataFrame) -> pd.DataFrame:
    if grp.empty:
        return pd.DataFrame(
            {
                "digit": DIGITS,
                "n": [0] * len(DIGITS),
                "avg_diff": [np.nan] * len(DIGITS),
                "plus_rate": [np.nan] * len(DIGITS),
                "hit104_rate": [np.nan] * len(DIGITS),
            }
        )

    stats_df = (
        grp.groupby("machine_digit", dropna=False)
        .agg(
            n=("diff", "size"),
            avg_diff=("diff", "mean"),
            plus_rate=("plus", "mean"),
            hit104_rate=("hit104", "mean"),
        )
        .reindex(range(10))
    )
    stats_df.index.name = "digit"
    stats_df = stats_df.reset_index()
    stats_df["n"] = stats_df["n"].fillna(0).astype(int)
    stats_df["plus_rate"] = stats_df["plus_rate"] * 100.0
    stats_df["hit104_rate"] = stats_df["hit104_rate"] * 100.0
    non_null = stats_df.dropna(subset=["avg_diff"]).sort_values(["avg_diff", "digit"], ascending=[False, True]).reset_index(drop=True)
    rank_map = {int(row["digit"]): idx + 1 for idx, row in non_null.iterrows()}
    stats_df["rank"] = stats_df["digit"].map(rank_map)
    stats_df["digit"] = stats_df["digit"].astype(str)
    return stats_df[["digit", "n", "avg_diff", "plus_rate", "hit104_rate", "rank"]]


def build_segment_frame(df: pd.DataFrame | None = None) -> pd.DataFrame:
    if df is None:
        df = load_hall_df(HALL_NAME)
    frame = df.copy()
    frame["date"] = frame["date"].astype(str)
    frame = frame[frame["date"].str[4:8] != EXCLUDED_MMDD].copy()

    for col in ["machine_number", "machine_digit", "diff", "games", "dd", "dd_mod10"]:
        if col in frame.columns:
            frame[col] = pd.to_numeric(frame[col], errors="coerce")

    if "day_of_week" not in frame.columns:
        dates = pd.to_datetime(frame["date"], format="%Y%m%d", errors="coerce")
        frame["day_of_week"] = dates.dt.day_name()

    frame = frame.dropna(subset=["machine_number", "machine_digit", "diff", "games", "day_of_week"]).copy()
    frame["machine_number"] = frame["machine_number"].astype(int)
    frame["machine_digit"] = frame["machine_digit"].astype(int)
    frame["machine_name"] = frame["machine_name"].astype(str)
    frame["diff"] = pd.to_numeric(frame["diff"], errors="coerce")
    frame["games"] = pd.to_numeric(frame["games"], errors="coerce")
    frame = frame.dropna(subset=["diff", "games"]).copy()
    frame["plus"] = (frame["diff"] > 0).astype(int)
    frame["payout_rate"] = (1 + frame["diff"] / (frame["games"] * 3)) * 100
    frame["hit104"] = (frame["payout_rate"] >= 104).astype(int)

    if "floor" not in frame.columns or "side" not in frame.columns:
        floor_side_map = build_floor_side_map()
        frame = frame.merge(floor_side_map, on="machine_number", how="inner")

    frame["floor"] = frame["floor"].astype(str)
    frame["side"] = frame["side"].astype(str)
    frame["seg"] = frame["machine_name"].map(classify_seg)
    frame = frame.dropna(subset=["seg", "floor", "side"]).copy()

    if "dd" not in frame.columns:
        frame["dd"] = pd.to_numeric(frame["date"].str[6:8], errors="coerce")
    if "dd_mod10" not in frame.columns:
        frame["dd_mod10"] = frame["dd"] % 10
    frame["dd"] = pd.to_numeric(frame["dd"], errors="coerce")
    frame["dd_mod10"] = pd.to_numeric(frame["dd_mod10"], errors="coerce")
    frame = frame.dropna(subset=["dd", "dd_mod10"]).copy()
    frame["dd"] = frame["dd"].astype(int)
    frame["dd_mod10"] = frame["dd_mod10"].astype(int)
    frame["day_of_week"] = frame["day_of_week"].astype(str)

    for level, col in LEVEL_COLUMNS.items():
        frame[col] = frame.apply(lambda row: _segment_label(level, row), axis=1)

    return frame.reset_index(drop=True)


def _prepare_frame(df: pd.DataFrame | None = None) -> pd.DataFrame:
    return build_segment_frame(df)


def level_segment_names(frame: pd.DataFrame, level: int) -> list[str]:
    col = LEVEL_COLUMNS[level]
    observed = [str(value) for value in frame[col].dropna().unique().tolist()]
    preferred = LEVEL_ORDER[level]
    ordered = [segment for segment in preferred if segment in observed]
    extras = sorted(segment for segment in observed if segment not in preferred)
    return ordered + extras


def build_level_rankings(frame: pd.DataFrame, level: int) -> pd.DataFrame:
    col = LEVEL_COLUMNS[level]
    rows: list[pd.DataFrame] = []
    for segment in level_segment_names(frame, level):
        sub = frame[frame[col] == segment]
        stats_df = _digit_metrics(sub).copy()
        stats_df.insert(0, "segment", segment)
        stats_df.insert(0, "level", level)
        rows.append(stats_df)
    if not rows:
        return pd.DataFrame(columns=["level", "segment", "digit", "n", "avg_diff", "plus_rate", "hit104_rate", "rank"])
    result = pd.concat(rows, ignore_index=True)
    result["digit"] = pd.Categorical(result["digit"], categories=DIGIT_ORDER, ordered=True)
    result = result.sort_values(["segment", "rank", "digit"], ascending=[True, True, True], na_position="last").reset_index(drop=True)
    result["digit"] = result["digit"].astype(str)
    return result[["level", "segment", "digit", "n", "avg_diff", "plus_rate", "hit104_rate", "rank"]]


def build_level_rankings_all(frame: pd.DataFrame) -> pd.DataFrame:
    return pd.concat([build_level_rankings(frame, level) for level in range(6)], ignore_index=True)


def build_signal_strength_table(frame: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for level in range(6):
        col = LEVEL_COLUMNS[level]
        for segment in level_segment_names(frame, level):
            sub = frame[frame[col] == segment]
            digit_metrics = _digit_metrics(sub)
            observed = digit_metrics.dropna(subset=["avg_diff"])
            n_obs = int(len(sub))
            n_machines = int(sub["machine_number"].nunique()) if not sub.empty else 0

            if observed.empty:
                digit_range = np.nan
                digit_std = np.nan
                kruskal_h = np.nan
                kruskal_p = np.nan
                epsilon_sq = np.nan
            else:
                digit_range = float(observed["avg_diff"].max() - observed["avg_diff"].min())
                digit_std = float(observed["avg_diff"].std(ddof=0))
                groups = [
                    sub.loc[sub["machine_digit"] == int(digit), "diff"].dropna().to_numpy()
                    for digit in DIGITS
                    if len(sub.loc[sub["machine_digit"] == int(digit)]) > 0
                ]
                if len(groups) >= 2:
                    try:
                        kruskal_h, kruskal_p = stats.kruskal(*groups)
                        epsilon_sq = max(0.0, (float(kruskal_h) - 10 + 1) / (n_obs - 10)) if n_obs > 10 else 0.0
                    except Exception:
                        kruskal_h = np.nan
                        kruskal_p = np.nan
                        epsilon_sq = np.nan
                else:
                    kruskal_h = np.nan
                    kruskal_p = np.nan
                    epsilon_sq = np.nan

            rows.append(
                {
                    "level": level,
                    "segment": segment,
                    "n_machines": n_machines,
                    "n_obs": n_obs,
                    "digit_range": digit_range,
                    "digit_std": digit_std,
                    "kruskal_H": kruskal_h,
                    "kruskal_p": kruskal_p,
                    "epsilon_sq": epsilon_sq,
                }
            )

    result = pd.DataFrame(rows)
    if result.empty:
        return pd.DataFrame(
            columns=["level", "segment", "n_machines", "n_obs", "digit_range", "digit_std", "kruskal_H", "kruskal_p", "epsilon_sq"]
        )
    return result.sort_values(["level", "segment"], ascending=[True, True]).reset_index(drop=True)


def build_level_rank_correlations(frame: pd.DataFrame) -> pd.DataFrame:
    rankings = build_level_rankings_all(frame)
    rows: list[dict[str, object]] = []
    for level in range(6):
        segments = level_segment_names(frame, level)
        for seg_a, seg_b in itertools.combinations(segments, 2):
            a = rankings[(rankings["level"] == level) & (rankings["segment"] == seg_a)].set_index("digit")["avg_diff"]
            b = rankings[(rankings["level"] == level) & (rankings["segment"] == seg_b)].set_index("digit")["avg_diff"]
            merged = pd.concat([a, b], axis=1, join="inner").dropna()
            if len(merged) >= 2:
                rho, p_value = stats.spearmanr(merged.iloc[:, 0], merged.iloc[:, 1])
            else:
                rho, p_value = np.nan, np.nan
            rows.append(
                {
                    "level": level,
                    "segment_a": seg_a,
                    "segment_b": seg_b,
                    "spearman_rho": rho,
                    "p_value": p_value,
                }
            )
    result = pd.DataFrame(rows)
    if result.empty:
        return pd.DataFrame(columns=["level", "segment_a", "segment_b", "spearman_rho", "p_value"])
    return result.sort_values(["level", "segment_a", "segment_b"], ascending=[True, True, True]).reset_index(drop=True)


def build_level_quickref(frame: pd.DataFrame) -> pd.DataFrame:
    level = 5
    col = LEVEL_COLUMNS[level]
    rows: list[dict[str, object]] = []
    for segment in [seg for seg in level_segment_names(frame, level) if seg != "3F_R_N"]:
        for day_of_week in WEEKDAY_ORDER:
            for dd_mod10 in range(10):
                sub = frame[
                    (frame[col] == segment)
                    & (frame["day_of_week"] == day_of_week)
                    & (frame["dd_mod10"] == dd_mod10)
                ]
                if sub.empty:
                    continue
                digit_stats = (
                    sub.groupby("machine_digit", dropna=False)
                    .agg(avg_diff=("diff", "mean"))
                    .reset_index()
                    .sort_values(["avg_diff", "machine_digit"], ascending=[False, True])
                )
                digit_stats["label"] = digit_stats.apply(
                    lambda row: f"d{int(row['machine_digit'])}({_fmt_int(row['avg_diff'])})",
                    axis=1,
                )
                top = digit_stats.head(3)["label"].tolist()
                bottom = digit_stats.tail(2)["label"].tolist()
                top += ["NaN"] * (3 - len(top))
                bottom += ["NaN"] * (2 - len(bottom))
                rows.append(
                    {
                        "segment": segment,
                        "day_of_week": day_of_week,
                        "dd_mod10": dd_mod10,
                        "top1": top[0],
                        "top2": top[1],
                        "top3": top[2],
                        "avoid1": bottom[-1],
                        "avoid2": bottom[0] if len(bottom) > 1 else "NaN",
                    }
                )
    result = pd.DataFrame(rows)
    if result.empty:
        return pd.DataFrame(columns=["segment", "day_of_week", "dd_mod10", "top1", "top2", "top3", "avoid1", "avoid2"])
    result["day_of_week"] = pd.Categorical(result["day_of_week"], categories=WEEKDAY_ORDER, ordered=True)
    return result.sort_values(["segment", "day_of_week", "dd_mod10"], ascending=[True, True, True]).reset_index(drop=True)


def build_recommendations(signal_strength: pd.DataFrame, correlations: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for _, row in signal_strength.iterrows():
        level = int(row["level"])
        segment = str(row["segment"])
        level_corr = correlations[correlations["level"] == level]
        peer_rows = level_corr[(level_corr["segment_a"] == segment) | (level_corr["segment_b"] == segment)]
        best_positive_rho = float(peer_rows["spearman_rho"].max()) if not peer_rows.empty else np.nan
        worst_rho = float(peer_rows["spearman_rho"].min()) if not peer_rows.empty else np.nan
        median_level_eps = float(signal_strength.loc[signal_strength["level"] == level, "epsilon_sq"].median())
        epsilon_sq = float(row["epsilon_sq"]) if pd.notna(row["epsilon_sq"]) else np.nan
        n_machines = int(row["n_machines"])
        n_obs = int(row["n_obs"])
        parent = _parent_segment(level, segment)

        if level == 0:
            recommendation = "keep"
            reason = "reference baseline for all comparisons"
        elif n_machines < 50 or n_obs < 200:
            recommendation = "merge" if level > 0 else "keep"
            reason = f"small sample (n_machines={n_machines}, n_obs={n_obs}) -> merge to {parent}"
        elif pd.notna(epsilon_sq) and epsilon_sq >= max(0.06, median_level_eps):
            if pd.notna(best_positive_rho) and best_positive_rho >= 0.55:
                recommendation = "merge"
                reason = f"ε²={epsilon_sq:.3f} is strong but best peer ρ={best_positive_rho:.3f} is redundant -> merge to {parent}"
            else:
                recommendation = "keep"
                reason = f"ε²={epsilon_sq:.3f} is above level median {median_level_eps:.3f} and peer ρ is not strongly positive"
        elif pd.notna(best_positive_rho) and best_positive_rho >= 0.70:
            recommendation = "merge"
            reason = f"best peer ρ={best_positive_rho:.3f} is high and ε²={epsilon_sq:.3f} is not enough to justify split -> merge to {parent}"
        elif pd.notna(worst_rho) and worst_rho <= -0.20:
            recommendation = "keep"
            reason = f"worst peer ρ={worst_rho:.3f} is negative, so the split carries directional information"
        elif pd.notna(epsilon_sq) and epsilon_sq < 0.01:
            recommendation = "drop"
            reason = f"ε²={epsilon_sq:.3f} is effectively zero"
        else:
            recommendation = "merge"
            reason = f"ε²={epsilon_sq:.3f} and peer ρ profile do not justify a dedicated segment -> merge to {parent}"

        rows.append(
            {
                "level": level,
                "segment": segment,
                "recommendation": recommendation,
                "reason": reason,
            }
        )

    result = pd.DataFrame(rows)
    if result.empty:
        return pd.DataFrame(columns=["level", "segment", "recommendation", "reason"])
    return result.sort_values(["level", "segment"], ascending=[True, True]).reset_index(drop=True)


def _markdown_section(title: str, body: str) -> str:
    return f"## {title}\n\n{body}\n"


def _render_rankings_section(rankings: pd.DataFrame) -> str:
    parts: list[str] = []
    for level in range(6):
        level_df = rankings[rankings["level"] == level].copy()
        if level_df.empty:
            parts.append(_markdown_section(f"Level {level}", "隧ｲ蠖薙↑縺・"))
            continue
        segment_order = level_df["segment"].dropna().unique().tolist()
        preferred = [seg for seg in LEVEL_ORDER[level] if seg in segment_order]
        extras = [seg for seg in segment_order if seg not in preferred]
        ordered_segments = preferred + extras
        section_lines = []
        for segment in ordered_segments:
            sub = level_df[level_df["segment"] == segment][["digit", "n", "avg_diff", "plus_rate", "hit104_rate", "rank"]]
            section_lines.append(f"### {segment}\n\n{table_to_md(sub, float_digits=2)}")
        parts.append(_markdown_section(f"Level {level}", "\n\n".join(section_lines)))
    return "\n".join(parts)


def _render_signal_section(signal_strength: pd.DataFrame) -> str:
    parts: list[str] = []
    for level in range(6):
        level_df = signal_strength[signal_strength["level"] == level].copy()
        if level_df.empty:
            parts.append(_markdown_section(f"Level {level}", "隧ｲ蠖薙↑縺・"))
            continue
        parts.append(_markdown_section(f"Level {level}", table_to_md(level_df, float_digits=3)))
    return "\n".join(parts)


def _render_correlation_section(correlations: pd.DataFrame) -> str:
    parts: list[str] = []
    for level in range(6):
        level_df = correlations[correlations["level"] == level].copy()
        if level_df.empty:
            parts.append(_markdown_section(f"Level {level}", "隧ｲ蠖薙↑縺・"))
            continue
        parts.append(_markdown_section(f"Level {level}", table_to_md(level_df, float_digits=3)))
    return "\n".join(parts)


def _render_quickref_section(quickref: pd.DataFrame) -> str:
    if quickref.empty:
        return "隧ｲ蠖薙↑縺・"
    parts: list[str] = []
    for segment in quickref["segment"].dropna().unique().tolist():
        sub = quickref[quickref["segment"] == segment][["day_of_week", "dd_mod10", "top1", "top2", "top3", "avoid1", "avoid2"]]
        parts.append(f"### {segment}\n\n{table_to_md(sub, float_digits=0)}")
    return "\n\n".join(parts)


def _render_recommendation_section(recommendations: pd.DataFrame) -> str:
    if recommendations.empty:
        return "隧ｲ蠖薙↑縺・"
    return table_to_md(recommendations, float_digits=3)


def _write_csv(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False, encoding="utf-8-sig")


def run_analysis(
    df: pd.DataFrame | None = None,
    report_path: Path = REPORT_PATH,
    rankings_path: Path = RANKINGS_CSV_PATH,
    signal_strength_path: Path = SIGNAL_CSV_PATH,
    quickref_path: Path = QUICKREF_CSV_PATH,
) -> dict[str, pd.DataFrame]:
    frame = build_segment_frame(df)
    rankings = build_level_rankings_all(frame)
    signal_strength = build_signal_strength_table(frame)
    correlations = build_level_rank_correlations(frame)
    quickref = build_level_quickref(frame)
    recommendations = build_recommendations(signal_strength, correlations)

    report_parts = [
        "# 蒲田7 末尾ランキング 粒度比較レポート",
        "",
        "## 前提",
        f"- `load_hall_df(\"{HALL_NAME}\")` を基点に集計",
        f"- `0707` は除外",
        "- `3F_R_N` は quickref から除外し、注記のみ",
        "",
        _markdown_section("Section 1: 粒度別の末尾ランキング", _render_rankings_section(rankings)),
        _markdown_section("Section 2: 粒度別の末尾シグナル強度比較", _render_signal_section(signal_strength)),
        _markdown_section("Section 3: Level間のランキング安定性", _render_correlation_section(correlations)),
        _markdown_section("Section 4: dd_mod10 × 曜日 別の末尾ランキング", _render_quickref_section(quickref)),
        _markdown_section("Section 5: 最適粒度の結論", _render_recommendation_section(recommendations)),
    ]
    report = "\n".join(report_parts).strip() + "\n"

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(report, encoding="utf-8-sig")
    _write_csv(rankings, rankings_path)
    _write_csv(signal_strength, signal_strength_path)
    _write_csv(quickref, quickref_path)

    return {
        "frame": frame,
        "rankings": rankings,
        "signal_strength": signal_strength,
        "correlations": correlations,
        "quickref": quickref,
        "recommendations": recommendations,
    }


def main() -> None:
    run_analysis()


if __name__ == "__main__":
    main()
