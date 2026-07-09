from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from eda import mitoya_phase10_segment_validation as phase10  # noqa: E402
from eda.mitoya_prompt_common import (  # noqa: E402
    add_debut_phase,
    add_event_category,
    ensure_results_dir,
    load_mitoya_frame,
    render_markdown_table,
)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


OUTPUT_DIR = Path(__file__).resolve().parents[1] / "tmp" / "mitoya_phase11b_regime_durability"
REGIME_ORDER = ["pre", "post"]
SEGMENT_ORDER = ["h_jug", "h_nonjug", "v_jug", "v_nonjug", "mixed_805"]
CORNER_BUCKET_ORDER = ["corner1", "corner2-4", "corner5-9", "corner10+"]
DEBUT_PHASE_ORDER = ["pre_existing", "debut", "growth", "mature"]

STEP1_COLUMNS = ["boundary_date", "pre_days", "post_days", "pre_n", "post_n", "max_changes"]
STEP2_COLUMNS = ["segment", "regime", "corner_bucket", "n", "avg_diff", "plus_rate"]
STEP2_KW_COLUMNS = ["segment", "regime", "kw_stat", "p_value", "epsilon_sq", "n_groups", "n"]
STEP3_COLUMNS = ["segment", "spearman_rho", "p_value", "n_groups", "pre_top1", "post_top1"]
STEP4_COLUMNS = ["segment", "regime", "debut_phase", "n", "avg_diff", "plus_rate"]
STEP4_KW_COLUMNS = ["segment", "regime", "kw_stat", "p_value", "epsilon_sq", "n_groups", "n"]
STEP5_COLUMNS = ["segment", "spearman_rho", "p_value", "n_groups", "pre_best_phase", "post_best_phase"]
STEP6_COLUMNS = ["segment", "axis", "pre_p", "post_p", "rank_rho", "rank_p", "top1_stable", "verdict"]


def detect_regime_boundary(work: pd.DataFrame) -> pd.Timestamp:
    work = work.copy()
    if "date_dt" not in work.columns:
        work["date_dt"] = pd.to_datetime(work.get("date"), format="%Y%m%d", errors="coerce")
    daily = work.dropna(subset=["date_dt", "machine_number"]).sort_values(["machine_number", "date_dt"]).copy()
    if daily.empty:
        return pd.NaT

    daily["prev_name"] = daily.groupby("machine_number")["machine_name"].shift(1)
    daily["name_changed"] = daily["machine_name"].ne(daily["prev_name"]) & daily["prev_name"].notna()
    change_counts = daily.groupby("date_dt")["name_changed"].sum()
    if change_counts.empty:
        unique_dates = pd.Index(sorted(daily["date_dt"].dropna().unique()))
        return pd.Timestamp(unique_dates[len(unique_dates) // 2]) if len(unique_dates) else pd.NaT

    max_changes = int(change_counts.max())
    if max_changes <= 0:
        unique_dates = pd.Index(sorted(daily["date_dt"].dropna().unique()))
        return pd.Timestamp(unique_dates[len(unique_dates) // 2]) if len(unique_dates) else pd.NaT
    return pd.Timestamp(change_counts.idxmax())


def _assign_regime(work: pd.DataFrame, boundary_date: pd.Timestamp) -> pd.DataFrame:
    out = work.copy()
    date_dt = (
        out["date_dt"]
        if "date_dt" in out.columns
        else pd.to_datetime(out.get("date"), format="%Y%m%d", errors="coerce")
    )
    if pd.isna(boundary_date):
        out["regime"] = "unknown"
        return out
    out["regime"] = np.where(date_dt < boundary_date, "pre", "post")
    out.loc[date_dt.isna(), "regime"] = "unknown"
    out["regime"] = pd.Categorical(out["regime"], categories=REGIME_ORDER, ordered=True)
    return out


def _boundary_summary(work: pd.DataFrame, boundary_date: pd.Timestamp, max_changes: int) -> pd.DataFrame:
    if "date_dt" in work.columns:
        date_dt = pd.to_datetime(work["date_dt"], errors="coerce")
    else:
        date_dt = pd.to_datetime(work.get("date"), format="%Y%m%d", errors="coerce")
    valid_dates = date_dt.dropna()
    if pd.isna(boundary_date) or valid_dates.empty:
        return pd.DataFrame(columns=STEP1_COLUMNS)

    boundary_norm = pd.Timestamp(boundary_date).normalize()
    pre_days = int(valid_dates.dt.normalize().lt(boundary_norm).sum())
    post_days = int(valid_dates.dt.normalize().ge(boundary_norm).sum())
    pre_n = int(date_dt.lt(boundary_norm).sum())
    post_n = int(date_dt.ge(boundary_norm).sum())
    return pd.DataFrame(
        [
            {
                "boundary_date": boundary_norm.strftime("%Y%m%d"),
                "pre_days": pre_days,
                "post_days": post_days,
                "pre_n": pre_n,
                "post_n": post_n,
                "max_changes": int(max_changes),
            }
        ],
        columns=STEP1_COLUMNS,
    )


def _segment_frame(work: pd.DataFrame, segment: str) -> pd.DataFrame:
    return phase10._segment_frame(work, segment)


def _build_regime_group_tables(
    work: pd.DataFrame,
    *,
    group_col: str,
    order: list[str],
    group_name: str,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    stats_rows: list[dict[str, object]] = []
    kw_rows: list[dict[str, object]] = []

    for segment in SEGMENT_ORDER:
        segment_frame = _segment_frame(work, segment)
        if segment_frame.empty:
            continue
        segment_frame = segment_frame.loc[segment_frame["regime"].isin(REGIME_ORDER)].copy()
        if segment_frame.empty:
            continue

        for regime in REGIME_ORDER:
            frame = segment_frame.loc[segment_frame["regime"].eq(regime)].copy()
            if frame.empty:
                continue

            stats = phase10._group_stats(frame, group_col, order=order)
            if stats.empty:
                continue
            for _, row in stats.iterrows():
                stats_rows.append(
                    {
                        "segment": segment,
                        "regime": regime,
                        group_name: str(row[group_col]),
                        "n": int(row["n"]),
                        "avg_diff": float(row["avg_diff"]),
                        "plus_rate": float(row["plus_rate"]),
                    }
                )

            kw = phase10._kruskal_summary(frame, group_col, order=order)
            kw_rows.append(
                {
                    "segment": segment,
                    "regime": regime,
                    "kw_stat": float(kw["kw_stat"]),
                    "p_value": float(kw["p_value"]),
                    "epsilon_sq": float(kw["epsilon_sq"]),
                    "n_groups": int(kw["n_groups"]),
                    "n": int(kw["total_n"]),
                }
            )

    stats_df = pd.DataFrame(stats_rows, columns=STEP2_COLUMNS if group_name == "corner_bucket" else STEP4_COLUMNS)
    kw_df = pd.DataFrame(kw_rows, columns=STEP2_KW_COLUMNS)
    if not stats_df.empty:
        stats_df["segment"] = pd.Categorical(stats_df["segment"], categories=SEGMENT_ORDER, ordered=True)
        stats_df["regime"] = pd.Categorical(stats_df["regime"], categories=REGIME_ORDER, ordered=True)
        stats_df[group_name] = pd.Categorical(stats_df[group_name], categories=order, ordered=True)
        stats_df = stats_df.sort_values(["segment", "regime", group_name], kind="mergesort").reset_index(drop=True)
        stats_df["segment"] = stats_df["segment"].astype(str)
        stats_df["regime"] = stats_df["regime"].astype(str)
        stats_df[group_name] = stats_df[group_name].astype(str)
    if not kw_df.empty:
        kw_df["segment"] = pd.Categorical(kw_df["segment"], categories=SEGMENT_ORDER, ordered=True)
        kw_df["regime"] = pd.Categorical(kw_df["regime"], categories=REGIME_ORDER, ordered=True)
        kw_df = kw_df.sort_values(["segment", "regime"], kind="mergesort").reset_index(drop=True)
        kw_df["segment"] = kw_df["segment"].astype(str)
        kw_df["regime"] = kw_df["regime"].astype(str)
    return stats_df, kw_df


def build_step2_corner_regime(work: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    return _build_regime_group_tables(
        work, group_col="corner_bucket", order=CORNER_BUCKET_ORDER, group_name="corner_bucket"
    )


def _rank_table_from_stats(
    stats: pd.DataFrame,
    *,
    group_col: str,
    order: list[str],
    output_columns: list[str],
    top1_columns: tuple[str, str],
) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    if stats.empty:
        return pd.DataFrame(columns=output_columns)

    for segment in SEGMENT_ORDER:
        segment_stats = stats.loc[stats["segment"].eq(segment)].copy()
        if segment_stats.empty:
            continue

        pre = segment_stats.loc[segment_stats["regime"].eq("pre")].copy()
        post = segment_stats.loc[segment_stats["regime"].eq("post")].copy()
        if pre.empty or post.empty:
            continue

        pre = pre.set_index(group_col, drop=False).reindex(order).dropna(subset=["avg_diff"])
        post = post.set_index(group_col, drop=False).reindex(order).dropna(subset=["avg_diff"])
        common = [level for level in order if level in pre.index and level in post.index]
        if len(common) < 2:
            continue

        pre_vals = pre.loc[common, "avg_diff"].astype(float).to_numpy()
        post_vals = post.loc[common, "avg_diff"].astype(float).to_numpy()
        rho, p_value = spearmanr(pre_vals, post_vals)

        pre_top1 = str(pre["avg_diff"].astype(float).idxmax()) if not pre.empty else ""
        post_top1 = str(post["avg_diff"].astype(float).idxmax()) if not post.empty else ""

        rows.append(
            {
                "segment": segment,
                "spearman_rho": float(rho) if pd.notna(rho) else float("nan"),
                "p_value": float(p_value) if pd.notna(p_value) else float("nan"),
                "n_groups": int(len(common)),
                top1_columns[0]: str(pre_top1),
                top1_columns[1]: str(post_top1),
            }
        )

    table = pd.DataFrame(rows, columns=output_columns)
    if not table.empty:
        table["segment"] = pd.Categorical(table["segment"], categories=SEGMENT_ORDER, ordered=True)
        table = table.sort_values("segment", kind="mergesort").reset_index(drop=True)
        table["segment"] = table["segment"].astype(str)
    return table


def build_step3_corner_rank_correlation(corner_stats: pd.DataFrame) -> pd.DataFrame:
    return _rank_table_from_stats(
        corner_stats,
        group_col="corner_bucket",
        order=CORNER_BUCKET_ORDER,
        output_columns=STEP3_COLUMNS,
        top1_columns=("pre_top1", "post_top1"),
    )


def build_step4_debut_regime(work: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    return _build_regime_group_tables(work, group_col="debut_phase", order=DEBUT_PHASE_ORDER, group_name="debut_phase")


def build_step5_debut_rank_correlation(debut_stats: pd.DataFrame) -> pd.DataFrame:
    return _rank_table_from_stats(
        debut_stats,
        group_col="debut_phase",
        order=DEBUT_PHASE_ORDER,
        output_columns=STEP5_COLUMNS,
        top1_columns=("pre_best_phase", "post_best_phase"),
    )


def _verdict(pre_p: float, post_p: float, rank_rho: float, top1_stable: bool) -> str:
    pre_sig = pd.notna(pre_p) and float(pre_p) < 0.05
    post_sig = pd.notna(post_p) and float(post_p) < 0.05
    rho = float(rank_rho) if pd.notna(rank_rho) else float("nan")

    if pd.notna(rho) and rho < 0.5:
        return "❌崩壊"
    if pre_sig and post_sig and pd.notna(rho) and rho > 0.8 and top1_stable:
        return "✅安定"
    if pre_sig ^ post_sig:
        return "⚠️不安定"
    if not pre_sig and not post_sig:
        return "✗効果なし"
    return "⚠️不安定"


def build_step6_stability_summary(
    corner_corr: pd.DataFrame,
    debut_corr: pd.DataFrame,
    corner_kw: pd.DataFrame,
    debut_kw: pd.DataFrame,
) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for segment in SEGMENT_ORDER:
        corner_corr_row = corner_corr.loc[corner_corr["segment"].eq(segment)]
        debut_corr_row = debut_corr.loc[debut_corr["segment"].eq(segment)]
        corner_kw_pre = corner_kw.loc[corner_kw["segment"].eq(segment) & corner_kw["regime"].eq("pre")]
        corner_kw_post = corner_kw.loc[corner_kw["segment"].eq(segment) & corner_kw["regime"].eq("post")]
        debut_kw_pre = debut_kw.loc[debut_kw["segment"].eq(segment) & debut_kw["regime"].eq("pre")]
        debut_kw_post = debut_kw.loc[debut_kw["segment"].eq(segment) & debut_kw["regime"].eq("post")]

        if not corner_corr_row.empty and not corner_kw_pre.empty and not corner_kw_post.empty:
            rho = float(corner_corr_row.iloc[0]["spearman_rho"])
            pre_top1 = str(corner_corr_row.iloc[0]["pre_top1"])
            post_top1 = str(corner_corr_row.iloc[0]["post_top1"])
            rows.append(
                {
                    "segment": segment,
                    "axis": "corner",
                    "pre_p": float(corner_kw_pre.iloc[0]["p_value"]),
                    "post_p": float(corner_kw_post.iloc[0]["p_value"]),
                    "rank_rho": rho,
                    "rank_p": float(corner_corr_row.iloc[0]["p_value"]),
                    "top1_stable": bool(pre_top1 == post_top1),
                    "verdict": _verdict(
                        float(corner_kw_pre.iloc[0]["p_value"]),
                        float(corner_kw_post.iloc[0]["p_value"]),
                        rho,
                        bool(pre_top1 == post_top1),
                    ),
                }
            )

        if not debut_corr_row.empty and not debut_kw_pre.empty and not debut_kw_post.empty:
            rho = float(debut_corr_row.iloc[0]["spearman_rho"])
            pre_top1 = str(debut_corr_row.iloc[0]["pre_best_phase"])
            post_top1 = str(debut_corr_row.iloc[0]["post_best_phase"])
            rows.append(
                {
                    "segment": segment,
                    "axis": "debut",
                    "pre_p": float(debut_kw_pre.iloc[0]["p_value"]),
                    "post_p": float(debut_kw_post.iloc[0]["p_value"]),
                    "rank_rho": rho,
                    "rank_p": float(debut_corr_row.iloc[0]["p_value"]),
                    "top1_stable": bool(pre_top1 == post_top1),
                    "verdict": _verdict(
                        float(debut_kw_pre.iloc[0]["p_value"]),
                        float(debut_kw_post.iloc[0]["p_value"]),
                        rho,
                        bool(pre_top1 == post_top1),
                    ),
                }
            )

    table = pd.DataFrame(rows, columns=STEP6_COLUMNS)
    if not table.empty:
        table["segment"] = pd.Categorical(table["segment"], categories=SEGMENT_ORDER, ordered=True)
        table["axis"] = pd.Categorical(table["axis"], categories=["corner", "debut"], ordered=True)
        table = table.sort_values(["segment", "axis"], kind="mergesort").reset_index(drop=True)
        table["segment"] = table["segment"].astype(str)
        table["axis"] = table["axis"].astype(str)
    return table


def _prepare_work(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.Timestamp, int]:
    raw = add_debut_phase(df)
    raw = add_event_category(raw)
    boundary_date = detect_regime_boundary(raw)

    daily = raw.copy()
    if "date_dt" not in daily.columns:
        daily["date_dt"] = pd.to_datetime(daily.get("date"), format="%Y%m%d", errors="coerce")
    daily = daily.dropna(subset=["date_dt", "machine_number"]).sort_values(["machine_number", "date_dt"]).copy()
    daily["prev_name"] = daily.groupby("machine_number")["machine_name"].shift(1)
    daily["name_changed"] = daily["machine_name"].ne(daily["prev_name"]) & daily["prev_name"].notna()
    change_counts = daily.groupby("date_dt")["name_changed"].sum()
    max_changes = int(change_counts.max()) if not change_counts.empty else 0

    prepared = phase10._prepare_frame(raw)
    prepared = prepared.loc[~prepared["is_moved"].fillna(False)].copy()
    prepared = _assign_regime(prepared, boundary_date)
    return raw, prepared, boundary_date, max_changes


def build_all_artifacts(df: pd.DataFrame) -> dict[str, pd.DataFrame | str]:
    raw, prepared, boundary_date, max_changes = _prepare_work(df)

    step1 = _boundary_summary(raw, boundary_date, max_changes)
    step2_stats, step2_kw = build_step2_corner_regime(prepared)
    step3 = build_step3_corner_rank_correlation(step2_stats)
    step4_stats, step4_kw = build_step4_debut_regime(prepared)
    step5 = build_step5_debut_rank_correlation(step4_stats)
    step6 = build_step6_stability_summary(step3, step5, step2_kw, step4_kw)

    artifacts: dict[str, pd.DataFrame | str] = {
        "step1_regime_boundary": step1,
        "step2_corner_regime_stats": step2_stats,
        "step2_corner_regime_kw": step2_kw,
        "step3_corner_rank_correlation": step3,
        "step4_debut_regime_stats": step4_stats,
        "step4_debut_regime_kw": step4_kw,
        "step5_debut_rank_correlation": step5,
        "step6_stability_summary": step6,
    }
    artifacts["report"] = build_report(artifacts, boundary_date=boundary_date)
    return artifacts


def build_report(artifacts: dict[str, pd.DataFrame | str], *, boundary_date: pd.Timestamp) -> str:
    boundary_text = pd.Timestamp(boundary_date).strftime("%Y%m%d") if pd.notna(boundary_date) else "unknown"
    lines = [
        "# Phase11b: レジーム分割耐久性検証",
        "",
        f"- boundary_date: {boundary_text}",
        "- regime_rule: machine_name change peak split, fallback to median date",
        "- filters: add_debut_phase -> add_event_category -> phase10._prepare_frame -> drop is_moved",
        "",
        "## Step 1: レジーム境界",
        "",
        render_markdown_table(artifacts["step1_regime_boundary"])
        if not artifacts["step1_regime_boundary"].empty
        else "_no rows_",
        "",
        "## Step 2: 角番効果のレジーム安定性",
        "### 基本統計（segment別、regime別）",
        render_markdown_table(artifacts["step2_corner_regime_stats"])
        if not artifacts["step2_corner_regime_stats"].empty
        else "_no rows_",
        "",
        "### KW検定（segment別、regime別）",
        render_markdown_table(artifacts["step2_corner_regime_kw"])
        if not artifacts["step2_corner_regime_kw"].empty
        else "_no rows_",
        "",
        "## Step 3: 角番ランキング Spearman相関",
        render_markdown_table(artifacts["step3_corner_rank_correlation"])
        if not artifacts["step3_corner_rank_correlation"].empty
        else "_no rows_",
        "",
        "## Step 4: debut効果のレジーム安定性",
        "### 基本統計（segment別、regime別）",
        render_markdown_table(artifacts["step4_debut_regime_stats"])
        if not artifacts["step4_debut_regime_stats"].empty
        else "_no rows_",
        "",
        "### KW検定（segment別、regime別）",
        render_markdown_table(artifacts["step4_debut_regime_kw"])
        if not artifacts["step4_debut_regime_kw"].empty
        else "_no rows_",
        "",
        "## Step 5: debutランキング Spearman相関",
        render_markdown_table(artifacts["step5_debut_rank_correlation"])
        if not artifacts["step5_debut_rank_correlation"].empty
        else "_no rows_",
        "",
        "## Step 6: 安定性サマリ",
        render_markdown_table(artifacts["step6_stability_summary"])
        if not artifacts["step6_stability_summary"].empty
        else "_no rows_",
        "",
    ]
    return "\n".join(lines).rstrip() + "\n"


def save_outputs(artifacts: dict[str, pd.DataFrame | str], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    artifacts["step1_regime_boundary"].to_csv(
        output_dir / "step1_regime_boundary.csv", index=False, encoding="utf-8-sig"
    )
    artifacts["step2_corner_regime_stats"].to_csv(
        output_dir / "step2_corner_regime_stats.csv", index=False, encoding="utf-8-sig"
    )
    artifacts["step2_corner_regime_kw"].to_csv(
        output_dir / "step2_corner_regime_kw.csv", index=False, encoding="utf-8-sig"
    )
    artifacts["step3_corner_rank_correlation"].to_csv(
        output_dir / "step3_corner_rank_correlation.csv", index=False, encoding="utf-8-sig"
    )
    artifacts["step4_debut_regime_stats"].to_csv(
        output_dir / "step4_debut_regime_stats.csv", index=False, encoding="utf-8-sig"
    )
    artifacts["step4_debut_regime_kw"].to_csv(
        output_dir / "step4_debut_regime_kw.csv", index=False, encoding="utf-8-sig"
    )
    artifacts["step5_debut_rank_correlation"].to_csv(
        output_dir / "step5_debut_rank_correlation.csv", index=False, encoding="utf-8-sig"
    )
    artifacts["step6_stability_summary"].to_csv(
        output_dir / "step6_stability_summary.csv", index=False, encoding="utf-8-sig"
    )
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
