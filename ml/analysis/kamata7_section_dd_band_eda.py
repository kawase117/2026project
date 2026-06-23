from __future__ import annotations

import argparse
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy import stats

if __package__ is None or __package__ == "":
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from ml.analysis.kamata_kakuban_section_residual_eda import _df_to_markdown, _section_size_group
from ml.analysis.kamata7_kakuban_section_lr_interaction_eda import (
    SEGMENT_NAMES,
    _build_floor_frames,
    _build_segment_views,
    _calc_pay_rate,
    _normalize_segment_frame,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _resolve_default_db7() -> Path:
    candidates = [
        path
        for path in (PROJECT_ROOT / "db").glob("*蒲田7*.db")
        if path.is_file() and path.stat().st_size > 0
    ]
    if candidates:
        return sorted(candidates, key=lambda path: path.stat().st_size, reverse=True)[0]
    return PROJECT_ROOT / "db" / "マルハンメガシティ2000-蒲田7.db"


DEFAULT_DB_7 = _resolve_default_db7()
DEFAULT_COORDS_7_2F = PROJECT_ROOT / "Heatmap" / "2F_floor_coordinates_kamata7.csv"
DEFAULT_COORDS_7_3F = PROJECT_ROOT / "Heatmap" / "3F_floor_coordinates_kamata7.csv"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "ml" / "analysis" / "results" / "kamata7_section_dd_band_eda"
DEFAULT_MIN_GAMES_ANALYSIS = 100
DD_BAND_ORDER = ("event", "early", "mid", "late")
SECTION_SIZE_ORDER = ("small", "medium", "large")


def _categorize_dd_band(dd: int) -> str:
    if pd.isna(dd):
        return "unknown"
    dd_int = int(dd)
    if dd_int in [1, 10, 20, 30]:
        return "event"
    elif 1 <= dd_int < 11:
        return "early"
    elif 11 <= dd_int < 21:
        return "mid"
    elif 21 <= dd_int <= 31:
        return "late"
    return "unknown"


def _format_number(value: object, digits: int = 2) -> str:
    if pd.isna(value):
        return "nan"
    if isinstance(value, (int, np.integer)):
        return str(int(value))
    if isinstance(value, (float, np.floating)):
        return f"{float(value):.{digits}f}"
    return str(value)


def _table_md(df: pd.DataFrame) -> str:
    if df.empty:
        return "No rows."
    return _df_to_markdown(df)


def _prepare_segments(
    *,
    db_path: Path,
    coords_2f: Path,
    coords_3f: Path,
    min_games: int = DEFAULT_MIN_GAMES_ANALYSIS,
) -> dict[str, pd.DataFrame]:
    floor_frames = _build_floor_frames(
        db_path=db_path,
        coords_2f=coords_2f,
        coords_3f=coords_3f,
        min_games=min_games,
    )
    segments = _build_segment_views(floor_frames)
    for segment_name in SEGMENT_NAMES:
        frame = segments.get(segment_name, pd.DataFrame())
        if frame.empty:
            continue
        segments[segment_name] = _normalize_segment_frame(frame)
    return segments


def _compute_daily_aggregations(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame(
            columns=[
                "date",
                "segment",
                "section",
                "section_size_group",
                "dd",
                "dd_band",
                "games_sum",
                "diff_sum",
                "pay_rate",
                "n_machines",
                "n_days",
            ]
        )

    work = frame.copy()
    work["date"] = pd.to_datetime(work["date"], errors="coerce").dt.normalize()
    work["dd"] = pd.to_numeric(work["dd"], errors="coerce").astype("Int64")
    work["segment"] = work["segment"].astype(str)
    work["section"] = work["section"].astype(str)
    work["section_size_group"] = work["section_size_group"].astype("string")
    work["dd_band"] = work["dd"].map(_categorize_dd_band).astype("string")
    work["games_normalized"] = pd.to_numeric(work["games_normalized"], errors="coerce")
    work["diff_coins_normalized"] = pd.to_numeric(work["diff_coins_normalized"], errors="coerce")
    work = work.dropna(subset=["date", "dd", "segment", "section", "section_size_group", "games_normalized", "diff_coins_normalized"]).copy()
    work = work[work["dd_band"].ne("unknown")].copy()
    if work.empty:
        return pd.DataFrame(
            columns=[
                "date",
                "segment",
                "section",
                "section_size_group",
                "dd",
                "dd_band",
                "games_sum",
                "diff_sum",
                "pay_rate",
                "n_machines",
                "n_days",
            ]
        )

    daily = (
        work.groupby(["date", "segment", "section", "section_size_group", "dd", "dd_band"], as_index=False)
        .agg(
            games_sum=("games_normalized", "sum"),
            diff_sum=("diff_coins_normalized", "sum"),
            n_machines=("machine_number", "nunique"),
        )
        .sort_values(["segment", "section_size_group", "dd_band", "date", "section"], na_position="last")
        .reset_index(drop=True)
    )
    daily["pay_rate"] = _calc_pay_rate(daily["games_sum"], daily["diff_sum"]).round(2)
    daily["n_days"] = 1
    return daily


def _summarize_by_section_and_band(daily: pd.DataFrame) -> pd.DataFrame:
    if daily.empty:
        return pd.DataFrame(
            columns=[
                "section_size_group",
                "dd_band",
                "games_sum",
                "diff_sum",
                "pay_rate",
                "n_machines",
                "n_days",
                "pay_rate_std",
            ]
        )

    work = daily.copy()
    work["section_size_group"] = work["section_size_group"].astype("string")
    work["dd_band"] = pd.Categorical(work["dd_band"], categories=DD_BAND_ORDER, ordered=True)
    summary = (
        work.groupby(["section_size_group", "dd_band"], as_index=False)
        .agg(
            games_sum=("games_sum", "sum"),
            diff_sum=("diff_sum", "sum"),
            n_machines=("n_machines", "sum"),
            n_days=("date", "nunique"),
            pay_rate_std=("pay_rate", "std"),
        )
        .copy()
    )
    summary["pay_rate"] = _calc_pay_rate(summary["games_sum"], summary["diff_sum"]).round(2)
    summary["section_size_group"] = pd.Categorical(summary["section_size_group"], categories=SECTION_SIZE_ORDER, ordered=True)
    summary = summary.sort_values(["section_size_group", "dd_band"], na_position="last").reset_index(drop=True)
    summary["section_size_group"] = summary["section_size_group"].astype(str)
    summary["dd_band"] = summary["dd_band"].astype(str)
    summary["n_machines"] = pd.to_numeric(summary["n_machines"], errors="coerce").fillna(0).astype(int)
    summary["n_days"] = pd.to_numeric(summary["n_days"], errors="coerce").fillna(0).astype(int)
    return summary


def _compute_segment_summary(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame(
            columns=[
                "segment",
                "section_size_group",
                "dd_band",
                "games_sum",
                "diff_sum",
                "pay_rate",
                "n_machines",
                "n_days",
                "pay_rate_std",
            ]
        )

    work = frame.copy()
    work["segment"] = work["segment"].astype(str)
    work["section_size_group"] = work["section_size_group"].astype("string")
    work["dd_band"] = pd.Categorical(work["dd_band"], categories=DD_BAND_ORDER, ordered=True)
    summary = (
        work.groupby(["segment", "section_size_group", "dd_band"], as_index=False)
        .agg(
            games_sum=("games_sum", "sum"),
            diff_sum=("diff_sum", "sum"),
            n_machines=("n_machines", "sum"),
            n_days=("date", "nunique"),
            pay_rate_std=("pay_rate", "std"),
        )
        .copy()
    )
    summary["pay_rate"] = _calc_pay_rate(summary["games_sum"], summary["diff_sum"]).round(2)
    summary["segment"] = pd.Categorical(summary["segment"], categories=SEGMENT_NAMES, ordered=True)
    summary["section_size_group"] = pd.Categorical(summary["section_size_group"], categories=SECTION_SIZE_ORDER, ordered=True)
    summary = summary.sort_values(["segment", "section_size_group", "dd_band"], na_position="last").reset_index(drop=True)
    summary["segment"] = summary["segment"].astype(str)
    summary["section_size_group"] = summary["section_size_group"].astype(str)
    summary["dd_band"] = summary["dd_band"].astype(str)
    summary["n_machines"] = pd.to_numeric(summary["n_machines"], errors="coerce").fillna(0).astype(int)
    summary["n_days"] = pd.to_numeric(summary["n_days"], errors="coerce").fillna(0).astype(int)
    return summary


def _anova_for_groups(work: pd.DataFrame) -> tuple[float, float, dict[str, float], dict[str, float], dict[str, int]]:
    band_means: dict[str, float] = {}
    band_stds: dict[str, float] = {}
    band_counts: dict[str, int] = {}
    groups: list[pd.Series] = []
    for band in DD_BAND_ORDER:
        series = work.loc[work["dd_band"].eq(band), "pay_rate"].dropna().astype(float)
        band_counts[band] = int(len(series))
        band_means[band] = float(series.mean()) if len(series) else np.nan
        band_stds[band] = float(series.std(ddof=1)) if len(series) > 1 else np.nan
        if len(series) >= 2:
            groups.append(series)
    if len(groups) < 2:
        return np.nan, np.nan, band_means, band_stds, band_counts
    try:
        result = stats.f_oneway(*groups)
        return float(result.statistic), float(result.pvalue), band_means, band_stds, band_counts
    except Exception:
        return np.nan, np.nan, band_means, band_stds, band_counts


def _compute_dd_band_anova(daily: pd.DataFrame) -> pd.DataFrame:
    if daily.empty:
        return pd.DataFrame(
            columns=[
                "segment",
                "section_size_group",
                "f_value",
                "p_value",
                "group_mean",
                "group_std",
                "n_observations",
                "n_groups",
                "event_mean",
                "event_std",
                "event_n",
                "early_mean",
                "early_std",
                "early_n",
                "mid_mean",
                "mid_std",
                "mid_n",
                "late_mean",
                "late_std",
                "late_n",
                "best_band",
                "worst_band",
                "spread_pp",
            ]
        )

    rows: list[dict[str, object]] = []
    for (segment, section_size_group), group in daily.groupby(["segment", "section_size_group"], dropna=False):
        work = group.copy()
        f_value, p_value, band_means, band_stds, band_counts = _anova_for_groups(work)
        observed = pd.to_numeric(work["pay_rate"], errors="coerce").dropna().astype(float)
        valid_means = {band: value for band, value in band_means.items() if np.isfinite(value)}
        best_band = max(valid_means.items(), key=lambda item: item[1])[0] if valid_means else ""
        worst_band = min(valid_means.items(), key=lambda item: item[1])[0] if valid_means else ""
        spread_pp = valid_means.get(best_band, np.nan) - valid_means.get(worst_band, np.nan) if valid_means else np.nan
        rows.append(
            {
                "segment": segment,
                "section_size_group": section_size_group,
                "f_value": f_value,
                "p_value": p_value,
                "group_mean": float(observed.mean()) if len(observed) else np.nan,
                "group_std": float(observed.std(ddof=1)) if len(observed) > 1 else np.nan,
                "n_observations": int(len(observed)),
                "n_groups": int(sum(1 for band in DD_BAND_ORDER if band_counts.get(band, 0) > 0)),
                "event_mean": band_means.get("event", np.nan),
                "event_std": band_stds.get("event", np.nan),
                "event_n": band_counts.get("event", 0),
                "early_mean": band_means.get("early", np.nan),
                "early_std": band_stds.get("early", np.nan),
                "early_n": band_counts.get("early", 0),
                "mid_mean": band_means.get("mid", np.nan),
                "mid_std": band_stds.get("mid", np.nan),
                "mid_n": band_counts.get("mid", 0),
                "late_mean": band_means.get("late", np.nan),
                "late_std": band_stds.get("late", np.nan),
                "late_n": band_counts.get("late", 0),
                "best_band": best_band,
                "worst_band": worst_band,
                "spread_pp": spread_pp,
            }
        )

    out = pd.DataFrame(rows)
    if out.empty:
        return out
    out["segment"] = pd.Categorical(out["segment"], categories=SEGMENT_NAMES, ordered=True)
    out["section_size_group"] = pd.Categorical(out["section_size_group"], categories=SECTION_SIZE_ORDER, ordered=True)
    out = out.sort_values(["section_size_group", "segment"], na_position="last").reset_index(drop=True)
    out["segment"] = out["segment"].astype(str)
    out["section_size_group"] = out["section_size_group"].astype(str)
    return out


def _build_large_summary(daily: pd.DataFrame) -> pd.DataFrame:
    if daily.empty:
        return pd.DataFrame(
            columns=[
                "segment",
                "dd_band",
                "games_sum",
                "diff_sum",
                "pay_rate",
                "n_machines",
                "n_days",
                "pay_rate_std",
            ]
        )

    large = daily[daily["section_size_group"].astype(str).eq("large")].copy()
    if large.empty:
        return pd.DataFrame(
            columns=[
                "segment",
                "dd_band",
                "games_sum",
                "diff_sum",
                "pay_rate",
                "n_machines",
                "n_days",
                "pay_rate_std",
            ]
        )

    summary = _compute_segment_summary(large)
    return summary[["segment", "dd_band", "games_sum", "diff_sum", "pay_rate", "n_machines", "n_days", "pay_rate_std"]].copy()


def _build_heatmap(heatmap_summary: pd.DataFrame, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if heatmap_summary.empty:
        fig, ax = plt.subplots(figsize=(8, 4))
        ax.text(0.5, 0.5, "No data", ha="center", va="center", transform=ax.transAxes)
        ax.axis("off")
        fig.tight_layout()
        fig.savefig(output_path, dpi=160)
        plt.close(fig)
        return

    pivot = (
        heatmap_summary.pivot_table(index="section_size_group", columns="dd_band", values="pay_rate", aggfunc="mean")
        .reindex(index=list(SECTION_SIZE_ORDER), columns=list(DD_BAND_ORDER))
    )
    fig, ax = plt.subplots(figsize=(9, 4.5))
    im = ax.imshow(pivot.to_numpy(dtype=float), aspect="auto", cmap="RdYlGn")
    ax.set_xticks(np.arange(len(pivot.columns)))
    ax.set_xticklabels([str(col) for col in pivot.columns.tolist()])
    ax.set_yticks(np.arange(len(pivot.index)))
    ax.set_yticklabels([str(idx) for idx in pivot.index.tolist()])
    ax.set_xlabel("dd_band")
    ax.set_ylabel("section_size_group")
    ax.set_title("Kamata7 section size x DD band pay rate")
    cbar = fig.colorbar(im, ax=ax)
    cbar.set_label("pay_rate (%)")
    fig.tight_layout()
    fig.savefig(output_path, dpi=160, bbox_inches="tight")
    plt.close(fig)


def _build_large_chart(large_summary: pd.DataFrame, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if large_summary.empty:
        fig, ax = plt.subplots(figsize=(8, 4))
        ax.text(0.5, 0.5, "No data", ha="center", va="center", transform=ax.transAxes)
        ax.axis("off")
        fig.tight_layout()
        fig.savefig(output_path, dpi=160)
        plt.close(fig)
        return

    fig, axes = plt.subplots(1, len(SEGMENT_NAMES), figsize=(16, 4.8), sharey=True)
    if len(SEGMENT_NAMES) == 1:
        axes = [axes]
    x = np.arange(len(DD_BAND_ORDER))
    width = 0.72
    for ax, segment in zip(axes, SEGMENT_NAMES, strict=True):
        block = large_summary[large_summary["segment"].astype(str).eq(segment)].copy()
        if block.empty:
            ax.text(0.5, 0.5, "No data", ha="center", va="center", transform=ax.transAxes)
            ax.set_title(segment)
            ax.axis("off")
            continue
        block = block.set_index("dd_band").reindex(list(DD_BAND_ORDER))
        values = block["pay_rate"].astype(float).to_numpy()
        errors = block["pay_rate_std"].astype(float).fillna(0.0).to_numpy()
        ax.bar(x, values, width=width, yerr=errors, capsize=4, color=["#2b8cbe", "#7bccc4", "#fdae61", "#d7191c"])
        ax.set_xticks(x)
        ax.set_xticklabels(list(DD_BAND_ORDER))
        ax.set_title(f"{segment} large")
        ax.set_ylim(90, max(115, np.nanmax(values) + 5))
        ax.axhline(100, color="#666666", linestyle="--", linewidth=1)
    axes[0].set_ylabel("pay_rate (%)")
    fig.suptitle("Kamata7 large section DD band comparison", y=1.02)
    fig.tight_layout()
    fig.savefig(output_path, dpi=160, bbox_inches="tight")
    plt.close(fig)


def _build_report(
    *,
    daily: pd.DataFrame,
    section_summary: pd.DataFrame,
    anova: pd.DataFrame,
    large_summary: pd.DataFrame,
) -> str:
    lines = [
        "# Kamata7 section size x DD band EDA",
        "",
        "Daily aggregation uses the key `(date, segment, section, section_size_group, dd_band)`.",
        "ANOVA is run on daily pay_rate values per `(segment, section_size_group, dd_band)` group.",
        "",
        "## 1. Daily overview",
        "",
        f"- rows: `{len(daily)}`",
        f"- dates: `{int(daily['date'].nunique()) if not daily.empty else 0}`",
        f"- segments: `{int(daily['segment'].nunique()) if not daily.empty else 0}`",
        f"- dd bands: `{', '.join(DD_BAND_ORDER)}`",
        "",
        _table_md(daily.head(30)),
        "",
        "## 2. Section x DD band pay rate summary",
        "",
        _table_md(section_summary),
        "",
        "## 3. ANOVA results",
        "",
        _table_md(anova),
        "",
        "## 4. Large section detail",
        "",
        _table_md(large_summary),
        "",
        "## 5. Findings",
        "",
    ]

    sig = anova[pd.to_numeric(anova.get("p_value"), errors="coerce").lt(0.05)].copy() if not anova.empty else pd.DataFrame()
    if sig.empty:
        lines.append("No segment/section_size_group combination reached p < 0.05.")
    else:
        lines.append(f"Significant ANOVA rows: `{len(sig)}`")
        lines.append(_table_md(sig[["segment", "section_size_group", "f_value", "p_value", "best_band", "worst_band", "spread_pp"]]))
    lines.append("")

    if not large_summary.empty:
        late = large_summary[large_summary["dd_band"].astype(str).eq("late")][["segment", "pay_rate"]].rename(columns={"pay_rate": "late_pay_rate"})
        early = large_summary[large_summary["dd_band"].astype(str).eq("early")][["segment", "pay_rate"]].rename(columns={"pay_rate": "early_pay_rate"})
        compare = late.merge(early, on="segment", how="outer")
        compare["late_minus_early_pp"] = compare["late_pay_rate"] - compare["early_pay_rate"]
        lines.extend(
            [
                "### Large late vs early",
                "",
                _table_md(compare),
                "",
                f"Rows with late_minus_early_pp >= 3.0: `{int(compare['late_minus_early_pp'].ge(3.0).fillna(False).sum())}`",
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def run_analysis(
    *,
    db_path: Path,
    coords_2f: Path,
    coords_3f: Path,
    output_dir: Path,
    min_games: int = DEFAULT_MIN_GAMES_ANALYSIS,
) -> dict[str, pd.DataFrame]:
    output_dir.mkdir(parents=True, exist_ok=True)

    segments = _prepare_segments(db_path=db_path, coords_2f=coords_2f, coords_3f=coords_3f, min_games=min_games)
    frames: list[pd.DataFrame] = []
    for segment_name in SEGMENT_NAMES:
        frame = segments.get(segment_name, pd.DataFrame())
        if frame.empty:
            continue
        work = frame.copy()
        work["segment"] = segment_name
        frames.append(work)

    combined = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    daily = _compute_daily_aggregations(combined)
    section_summary = _summarize_by_section_and_band(daily)
    anova = _compute_dd_band_anova(daily)
    large_summary = _build_large_summary(daily)

    daily.to_csv(output_dir / "kamata7_section_dd_band_daily.csv", index=False, encoding="utf-8-sig")
    large_summary.to_csv(output_dir / "kamata7_large_dd_band_summary.csv", index=False, encoding="utf-8-sig")
    anova.to_csv(output_dir / "kamata7_dd_band_anova_results.csv", index=False, encoding="utf-8-sig")

    _build_heatmap(section_summary, output_dir / "heatmap_section_dd_band_payrate.png")
    _build_large_chart(large_summary, output_dir / "chart_large_dd_band_detail.png")

    report = _build_report(daily=daily, section_summary=section_summary, anova=anova, large_summary=large_summary)
    (output_dir / "report.md").write_text(report, encoding="utf-8")

    return {
        "daily": daily,
        "section_summary": section_summary,
        "anova": anova,
        "large_summary": large_summary,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Kamata7 section size x DD band EDA")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_7)
    parser.add_argument("--coords-2f", dest="coords_2f", type=Path, default=DEFAULT_COORDS_7_2F)
    parser.add_argument("--coords-3f", dest="coords_3f", type=Path, default=DEFAULT_COORDS_7_3F)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--min-games", type=int, default=DEFAULT_MIN_GAMES_ANALYSIS)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    run_analysis(
        db_path=args.db,
        coords_2f=args.coords_2f,
        coords_3f=args.coords_3f,
        output_dir=args.output_dir,
        min_games=args.min_games,
    )
    print(args.output_dir)
    print(args.output_dir / "report.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
