from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .decision_report import generate_decision_memo
from .kpi_report import KpiConfig, build_kpi_summary, build_kpi_summary_table, generate_kpi_decision_memo
from .loaders import build_actual_rank_map, load_topk_with_conditions
from .loss_chain import attach_loss_scenarios
from .stats import StatsConfig, compute_condition_significance, generate_summary_report
from .stratifiers import default_evaluators


@dataclass
class ConditionStats:
    condition: str
    difficulty: str
    n_pairs: int
    n_days: int
    hit_at_2_mean: float
    hit_at_3_mean: float
    loss_mean: float
    loss_p50: float
    loss_p75: float
    loss_p95: float
    rank2_rescue_rate: float
    rank3_rescue_rate: float
    critical_miss_rate: float


def _safe_mean(series: pd.Series) -> float:
    if len(series) == 0:
        return float("nan")
    return float(pd.to_numeric(series, errors="coerce").mean())


def _safe_quantile(series: pd.Series, q: float) -> float:
    ser = pd.to_numeric(series, errors="coerce").dropna()
    if len(ser) == 0:
        return float("nan")
    return float(ser.quantile(q))


def _compute_condition_stats(group: pd.DataFrame, *, condition: str, difficulty: str) -> ConditionStats:
    miss1 = group[group["top1_match"] == 0]
    rank2_rescue = float((miss1["top2_match"] == 1).mean()) if len(miss1) > 0 else float("nan")
    miss12 = group[(group["top1_match"] == 0) & (group["top2_match"] == 0)]
    rank3_rescue = float((miss12["top3_match"] == 1).mean()) if len(miss12) > 0 else float("nan")
    critical_miss = float((group["loss_scenario"] == "critical_miss").mean()) if len(group) > 0 else float("nan")
    return ConditionStats(
        condition=condition,
        difficulty=difficulty,
        n_pairs=int(len(group)),
        n_days=int(group["date"].nunique()),
        hit_at_2_mean=_safe_mean(group["hit_at_2"]),
        hit_at_3_mean=_safe_mean(group["hit_at_3"]) if "hit_at_3" in group.columns else float("nan"),
        loss_mean=_safe_mean(group["loss_value"]),
        loss_p50=_safe_quantile(group["loss_value"], 0.50),
        loss_p75=_safe_quantile(group["loss_value"], 0.75),
        loss_p95=_safe_quantile(group["loss_value"], 0.95),
        rank2_rescue_rate=rank2_rescue,
        rank3_rescue_rate=rank3_rescue,
        critical_miss_rate=critical_miss,
    )


def _build_condition_metrics(df_loss: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for evaluator in default_evaluators():
        groups = evaluator.stratify(df_loss)
        for difficulty, sub in groups.items():
            if len(sub) == 0:
                continue
            rows.append(asdict(_compute_condition_stats(sub, condition=evaluator.condition_name, difficulty=difficulty)))
    return pd.DataFrame(rows).sort_values(["condition", "difficulty"]).reset_index(drop=True)


def _build_rank_complement_chain(df_loss: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for evaluator in default_evaluators():
        for difficulty, sub in evaluator.stratify(df_loss).items():
            miss1 = sub[sub["top1_match"] == 0]
            miss12 = sub[(sub["top1_match"] == 0) & (sub["top2_match"] == 0)]
            rows.append(
                {
                    "condition": evaluator.condition_name,
                    "difficulty": difficulty,
                    "n_pairs": int(len(sub)),
                    "n_miss1": int(len(miss1)),
                    "rank2_rescue_rate": float((miss1["top2_match"] == 1).mean()) if len(miss1) > 0 else np.nan,
                    "rank3_rescue_rate": float((miss12["top3_match"] == 1).mean()) if len(miss12) > 0 else np.nan,
                    "critical_miss_rate": float((sub["loss_scenario"] == "critical_miss").mean()) if len(sub) > 0 else np.nan,
                    "loss_when_miss1_p50": _safe_quantile(miss1["loss_value"], 0.50),
                    "loss_when_miss1_p75": _safe_quantile(miss1["loss_value"], 0.75),
                }
            )
    return pd.DataFrame(rows).sort_values(["condition", "difficulty"]).reset_index(drop=True)


def _build_json_summary(condition_metrics: pd.DataFrame, rank_chain: pd.DataFrame) -> dict[str, Any]:
    out: dict[str, Any] = {"conditions": {}}
    for condition, g in condition_metrics.groupby("condition", sort=True):
        out["conditions"][condition] = {}
        for rec in g.to_dict(orient="records"):
            diff = rec.pop("difficulty")
            out["conditions"][condition][diff] = rec
    out["rank_complement_chain"] = rank_chain.to_dict(orient="records")
    return out


def _pair_index(df: pd.DataFrame) -> pd.MultiIndex:
    return pd.MultiIndex.from_frame(df[["date", "expert"]].drop_duplicates())


def _build_run_diagnostics(
    *,
    current_loss_df: pd.DataFrame,
    baseline_loss_df: pd.DataFrame | None,
    condition_metrics: pd.DataFrame,
    sig_df: pd.DataFrame,
    stats_config: StatsConfig | None,
) -> dict[str, Any]:
    diag: dict[str, Any] = {
        "current": {
            "rows": int(len(current_loss_df)),
            "unique_pairs": int(len(_pair_index(current_loss_df))),
            "n_days": int(current_loss_df["date"].nunique()),
            "n_experts": int(current_loss_df["expert"].nunique()),
        },
        "condition_group_count_by_condition": {
            str(k): int(v) for k, v in condition_metrics.groupby("condition")["difficulty"].nunique().to_dict().items()
        },
        "total_condition_groups": int(len(condition_metrics)),
        "bootstrap_unit": "date_expert_pair",
    }

    if stats_config is not None:
        diag["stats_config"] = asdict(stats_config)

    if baseline_loss_df is not None and not baseline_loss_df.empty:
        cur_idx = _pair_index(current_loss_df)
        base_idx = _pair_index(baseline_loss_df)
        overlap = cur_idx.intersection(base_idx)
        diag["baseline"] = {
            "rows": int(len(baseline_loss_df)),
            "unique_pairs": int(len(base_idx)),
            "n_days": int(baseline_loss_df["date"].nunique()),
            "n_experts": int(baseline_loss_df["expert"].nunique()),
            "overlap_pairs": int(len(overlap)),
            "overlap_ratio_vs_current": float(len(overlap) / max(len(cur_idx), 1)),
            "overlap_ratio_vs_baseline": float(len(overlap) / max(len(base_idx), 1)),
        }
        if not sig_df.empty:
            diag["significance_rows"] = int(len(sig_df))
            diag["significance_sig_bh_0_05"] = int((pd.to_numeric(sig_df["sig_bh_0_05"], errors="coerce") == 1).sum())
    return diag


def _build_significance_summary_markdown(sig_df: pd.DataFrame) -> str:
    if sig_df.empty:
        return "# Ceiling Effect Significance Summary\n\nNo significance rows were generated.\n"

    lines: list[str] = []
    lines.append("# Ceiling Effect Significance Summary")
    lines.append("")
    lines.append(f"- Total rows: {len(sig_df)}")
    sig_bh = sig_df[pd.to_numeric(sig_df["sig_bh_0_05"], errors="coerce") == 1].copy()
    lines.append(f"- BH significant (0.05): {len(sig_bh)}")
    lines.append("")

    top_sig = pd.DataFrame()
    if not sig_bh.empty:
        top_sig = sig_bh.copy()
        top_sig["abs_delta"] = pd.to_numeric(top_sig["delta_mean"], errors="coerce").abs()
        top_sig = top_sig.sort_values(["abs_delta", "p_value_adj_bh"], ascending=[False, True]).head(10)

    lines.append("## Top Significant Rows (BH <= 0.05)")
    if top_sig.empty:
        lines.append("- None")
    else:
        for rec in top_sig.to_dict(orient="records"):
            lines.append(
                "- "
                f"{rec['condition']} / {rec['difficulty']} / {rec['metric']}: "
                f"delta={float(rec['delta_mean']):.4f}, "
                f"p_bh={float(rec['p_value_adj_bh']):.4g}, "
                f"d={float(rec['cohens_d']):.3f} ({rec['cohens_d_label']})"
            )
    lines.append("")

    ns = sig_df[pd.to_numeric(sig_df["sig_bh_0_05"], errors="coerce") != 1].copy()
    ns["abs_d"] = pd.to_numeric(ns["cohens_d"], errors="coerce").abs()
    ns_large = ns[ns["abs_d"] >= 0.5].sort_values("abs_d", ascending=False).head(10)
    lines.append("## Non-significant But Large Effect (|d| >= 0.5)")
    if ns_large.empty:
        lines.append("- None")
    else:
        for rec in ns_large.to_dict(orient="records"):
            lines.append(
                "- "
                f"{rec['condition']} / {rec['difficulty']} / {rec['metric']}: "
                f"delta={float(rec['delta_mean']):.4f}, "
                f"p_bh={float(rec['p_value_adj_bh']):.4g}, "
                f"d={float(rec['cohens_d']):.3f} ({rec['cohens_d_label']})"
            )
    lines.append("")

    low_support = sig_df[
        (pd.to_numeric(sig_df["n_current"], errors="coerce") < 10)
        | (pd.to_numeric(sig_df["n_baseline"], errors="coerce") < 10)
    ]
    lines.append("## Low-support Warnings (n_current<10 or n_baseline<10)")
    if low_support.empty:
        lines.append("- None")
    else:
        for rec in low_support.sort_values(["condition", "difficulty", "metric"]).to_dict(orient="records"):
            lines.append(
                "- "
                f"{rec['condition']} / {rec['difficulty']} / {rec['metric']}: "
                f"n_current={int(rec['n_current'])}, n_baseline={int(rec['n_baseline'])}"
            )
    lines.append("")
    return "\n".join(lines)


def analyze_ceiling_effect(
    *,
    input_topk_csv: str | Path,
    output_dir: str | Path,
    baseline_topk_csv: str | Path | None = None,
    db_path: str | Path | None = None,
    stats_config: StatsConfig | None = None,
    catastrophic_threshold: float = 15000.0,
) -> dict[str, Path]:
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    resolved_db_path = Path(db_path) if db_path is not None and str(db_path).strip() else None
    topk = load_topk_with_conditions(input_topk_csv, db_path=resolved_db_path)
    rank_map = build_actual_rank_map(db_path=resolved_db_path)
    loss_df = attach_loss_scenarios(topk, rank_map)
    if loss_df.empty:
        raise RuntimeError("No rows after attaching loss scenarios. Check date/expert consistency.")

    condition_metrics = _build_condition_metrics(loss_df)
    rank_chain = _build_rank_complement_chain(loss_df)
    json_summary = _build_json_summary(condition_metrics, rank_chain)
    sig_df = pd.DataFrame()
    baseline_loss_df: pd.DataFrame | None = None
    if baseline_topk_csv is not None:
        base_topk = load_topk_with_conditions(baseline_topk_csv, db_path=resolved_db_path)
        base_loss_df = attach_loss_scenarios(base_topk, rank_map)
        baseline_loss_df = base_loss_df
        sig_df = compute_condition_significance(
            current_loss_df=loss_df,
            baseline_loss_df=base_loss_df,
            config=stats_config or StatsConfig(),
        )
        json_summary["condition_significance"] = sig_df.to_dict(orient="records")

    kpi_summary = build_kpi_summary(
        current_loss_df=loss_df,
        baseline_loss_df=baseline_loss_df,
        config=KpiConfig(catastrophic_threshold=float(catastrophic_threshold)),
    )
    kpi_table = build_kpi_summary_table(kpi_summary)

    diagnostics = _build_run_diagnostics(
        current_loss_df=loss_df,
        baseline_loss_df=baseline_loss_df,
        condition_metrics=condition_metrics,
        sig_df=sig_df,
        stats_config=stats_config,
    )
    json_summary["run_diagnostics"] = diagnostics
    json_summary["kpi_summary"] = kpi_summary

    out_loss = out_dir / "loss_scenarios.csv"
    out_metrics = out_dir / "condition_layer_metrics.csv"
    out_chain = out_dir / "rank_complement_chain.csv"
    out_json = out_dir / "ceiling_effect_analysis.json"
    out_sig = out_dir / "condition_significance.csv"
    out_diag = out_dir / "ceiling_effect_diagnostics.json"
    out_sig_summary = out_dir / "condition_significance_summary.md"
    out_sig_report = out_dir / "condition_significance_report.txt"
    out_decision_memo = out_dir / "decision_memo.md"
    out_kpi_json = out_dir / "kpi_summary.json"
    out_kpi_csv = out_dir / "kpi_summary.csv"
    out_kpi_memo = out_dir / "kpi_decision.md"

    loss_df.to_csv(out_loss, index=False, encoding="utf-8-sig")
    condition_metrics.to_csv(out_metrics, index=False, encoding="utf-8-sig")
    rank_chain.to_csv(out_chain, index=False, encoding="utf-8-sig")
    kpi_table.to_csv(out_kpi_csv, index=False, encoding="utf-8-sig")
    if not sig_df.empty:
        sig_df.to_csv(out_sig, index=False, encoding="utf-8-sig")
        out_sig_summary.write_text(_build_significance_summary_markdown(sig_df), encoding="utf-8")
        out_sig_report.write_text(generate_summary_report(sig_df), encoding="utf-8")
        out_decision_memo.write_text(generate_decision_memo(sig_df, diagnostics), encoding="utf-8")
    out_kpi_json.write_text(json.dumps(kpi_summary, ensure_ascii=False, indent=2), encoding="utf-8")
    out_kpi_memo.write_text(generate_kpi_decision_memo(kpi_summary), encoding="utf-8")
    out_diag.write_text(json.dumps(diagnostics, ensure_ascii=False, indent=2), encoding="utf-8")
    out_json.write_text(json.dumps(json_summary, ensure_ascii=False, indent=2), encoding="utf-8")

    outputs = {
        "loss_scenarios": out_loss,
        "condition_layer_metrics": out_metrics,
        "rank_complement_chain": out_chain,
        "ceiling_effect_analysis": out_json,
        "ceiling_effect_diagnostics": out_diag,
        "kpi_summary_json": out_kpi_json,
        "kpi_summary_csv": out_kpi_csv,
        "kpi_decision": out_kpi_memo,
    }
    if not sig_df.empty:
        outputs["condition_significance"] = out_sig
        outputs["condition_significance_summary"] = out_sig_summary
        outputs["condition_significance_report"] = out_sig_report
        outputs["decision_memo"] = out_decision_memo
    return outputs
